"""Voci campionate: store, identita', stati, dispositivi, resolver (spec §6,
§9, §10).

Il record vive in `_voice_clones.json` (community_store.JsonStore: lock,
scrittura atomica, .bak). I file del campione stanno in
`<data_dir>/voices/<token>/`, fuori dal tiering hot/cold dei job, con copia
su R2 sotto `voices/<token>/`. Nessun import di audiobook_app: la data dir
arriva da `init()`.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import shutil
import threading
import time

import community_store
import storage_backend
import voice_clone_prompts
import voxcpm_catalog

VOICE_ID_PREFIX = "voxcpm:mine:"
R2_PREFIX = "voices/"
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # niente 0/O, 1/I/L
RESUME_TOKEN_DAYS = 30

STATES = ("sample_ok", "paid", "demos_generating", "demos_ready", "ready",
          "demo_failed", "refunded", "expired", "deleted")
TRANSITIONS = {
    "sample_ok": {"paid"},
    "paid": {"demos_generating", "refunded"},
    "demos_generating": {"demos_ready", "demo_failed", "refunded"},
    "demos_ready": {"ready", "demos_generating", "refunded"},
    "demo_failed": {"demos_generating", "refunded"},
    "ready": {"expired", "deleted"},
    "refunded": set(), "expired": set(), "deleted": set(),
}
HAS_SAMPLE = frozenset({"sample_ok", "paid", "demos_generating", "demos_ready",
                        "demo_failed", "ready"})
_STAMP_ON_ENTER = {"ready": "ready_at", "paid": "paid_at", "refunded": "refunded_at",
                   "expired": "expired_at", "deleted": "deleted_at"}

_lock = threading.RLock()
_data_dir = None
_store = None


class VoiceGone(ValueError):
    """Voce inesistente o senza campione (cancellata, rimborsata, scaduta)."""


class SampleUnavailable(Exception):
    """Il campione esiste ma non e' raggiungibile ora (R2 in errore di
    trasporto/credenziali): NON e' una voce sparita, va trattata come
    condizione transitoria/riprovabile, non come VoiceGone."""


class BadTransition(ValueError):
    """Passaggio di stato non previsto dalla tabella."""


# Copia locale della whitelist di voice_clone_audio.ACCEPTED_EXT: import
# diretto non voluto qui (trascina numpy solo per una validazione di stringa).
_ACCEPTED_EXT = ("wav", "mp3", "webm", "opus", "ogg", "m4a", "mp4")
_EXT_RE = re.compile(r"^[a-z0-9]{1,5}$")

# Un lock per token, creato pigramente sotto `_lock`, per serializzare il
# download R2 di un dato campione: due thread che risolvono la stessa voce
# nello stesso istante non devono avviare due download dello stesso file.
_local_locks = {}


def init(data_dir):
    global _data_dir, _store
    _data_dir = str(data_dir)
    _store = community_store.JsonStore("_voice_clones.json")
    os.makedirs(voices_dir(), exist_ok=True)


def store():
    if _store is None:
        raise RuntimeError("voice_clone.init() must be called first")
    return _store


def voices_dir():
    return os.path.join(_data_dir, "voices")


def voice_dir(token):
    return os.path.join(voices_dir(), token)


def _now(now):
    return int(now if now is not None else time.time())


def _env_int(name, default):
    raw = (os.environ.get(name) or "").strip()
    try:
        return int(float(raw.replace(",", "."))) if raw else default
    except ValueError:
        return default


def sample_ttl_sec():
    return _env_int("ABM_VOICE_CLONE_SAMPLE_TTL_H", 24) * 3600


def retention_sec():
    return _env_int("ABM_VOICE_CLONE_RETENTION_DAYS", 365) * 86400


# ---------------------------------------------------------------------------
# identita'
# ---------------------------------------------------------------------------
def new_token():
    return secrets.token_hex(16)


def new_voice_code():
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
    return "-".join((raw[0:4], raw[4:8], raw[8:12]))


def normalize_voice_code(s):
    raw = "".join(c for c in (s or "").upper() if c.isalnum())
    return "-".join((raw[0:4], raw[4:8], raw[8:12])) if len(raw) == 12 else raw


def voice_id_of(rec):
    return VOICE_ID_PREFIX + rec["token"]


def token_of(voice_id):
    if not isinstance(voice_id, str) or not voice_id.startswith(VOICE_ID_PREFIX):
        return None
    tok = voice_id[len(VOICE_ID_PREFIX):]
    return tok if len(tok) == 32 and all(c in "0123456789abcdef" for c in tok) else None


def email_hash(email):
    return hashlib.sha256((email or "").strip().lower().encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# ricerca (scansione lineare: decine di record, vedi piano §Global Constraints)
# ---------------------------------------------------------------------------
def _all():
    return store().all(include_archived=True)


def _find(pred):
    for rec in _all():
        if pred(rec):
            return rec
    return None


def get(clone_id):
    return store().get(clone_id) if clone_id else None


def by_token(token):
    if not token:
        return None
    return _find(lambda r: hmac.compare_digest(str(r.get("token") or ""), str(token)))


def by_voice_code(code):
    code = normalize_voice_code(code)
    if not code:
        return None
    return _find(lambda r: hmac.compare_digest(str(r.get("voice_code") or ""), str(code)))


def by_manage_token(token):
    if not token:
        return None
    return _find(lambda r: hmac.compare_digest(str(r.get("manage_token") or ""), str(token)))


def by_resume_token(token, now=None):
    if not token:
        return None
    rec = _find(lambda r: hmac.compare_digest(
        str((r.get("resume_token") or {}).get("value") or ""), str(token)))
    if rec is None or (rec["resume_token"].get("expires_at") or 0) < _now(now):
        return None
    return rec


def draft_for_cid(cid, now=None):
    t = _now(now)
    return _find(lambda r: r.get("state") == "sample_ok"
                 and any(d.get("cid") == cid for d in r.get("devices") or [])
                 and (r.get("expires_at") or 0) > t)


def offered_languages():
    """Lingua -> locali attivi, per le sole lingue con frase guidata (D3)."""
    con_frase = set(voice_clone_prompts.languages())
    out = {}
    for rec in voxcpm_catalog.voices():
        if rec["lang"] in con_frase:
            out.setdefault(rec["lang"], set()).add(rec["locale"])
    return {k: sorted(v) for k, v in out.items()}


# ---------------------------------------------------------------------------
# file
# ---------------------------------------------------------------------------
def r2_key(token, name):
    return f"{R2_PREFIX}{token}/{name}"


def upload_to_r2(rec, name):
    """Copia `voice_dir/<name>` su R2, se attivo. Best effort: un fallimento
    lascia il locale come unica copia e lo scrive a stdout."""
    if not storage_backend.is_enabled():
        return False
    path = os.path.join(voice_dir(rec["token"]), name)
    try:
        storage_backend.upload_file(path, r2_key(rec["token"], name))
        return True
    except Exception as e:
        print(f"[voice_clone] upload R2 fallito per {rec['id']}/{name}: {e}")
        return False


def remove_files(rec):
    """Cancella cartella locale e prefisso R2 della voce. Non solleva."""
    shutil.rmtree(voice_dir(rec["token"]), ignore_errors=True)
    if storage_backend.is_enabled():
        try:
            storage_backend.delete_prefix(r2_key(rec["token"], ""))
        except Exception as e:
            print(f"[voice_clone] delete R2 fallita per {rec['id']}: {e}")


# ---------------------------------------------------------------------------
# bozza
# ---------------------------------------------------------------------------
def create_draft(cid, *, lang, locale, gender, prompt_text, sample_wav,
                 original_path, original_ext, metrics, ui_lang, now=None):
    """Il campione approvato dal gate diventa una voce in stato `sample_ok`.

    Un solo draft per cid (§3.3): il precedente viene cancellato con i suoi
    file. Lingua, locale e genere devono essere fra quelli offerti.
    """
    original_ext = (original_ext or "").strip().lower()
    if not _EXT_RE.match(original_ext) or original_ext not in _ACCEPTED_EXT:
        raise ValueError(f"original_ext non ammessa: {original_ext!r}")
    offerte = offered_languages()
    if lang not in offerte or locale not in offerte[lang]:
        raise ValueError(f"lingua/locale non offerti: {lang}/{locale}")
    if gender not in ("m", "f"):
        raise ValueError(f"genere non valido: {gender!r}")
    if not (prompt_text or "").strip():
        raise ValueError("prompt_text vuoto")
    t = _now(now)
    token = new_token()
    with _lock:
        while by_token(token) is not None:
            token = new_token()
        code = new_voice_code()
        while by_voice_code(code) is not None:
            code = new_voice_code()
        prev = _find(lambda r: r.get("state") == "sample_ok"
                     and any(d.get("cid") == cid for d in r.get("devices") or []))
        d = voice_dir(token)
        # La bozza precedente resta intatta finche' la nuova non e' interamente
        # al sicuro (file spostati + record salvato): uno spostamento fallito
        # (disco pieno, permessi, file temporaneo gia' sparito) non deve mai
        # cancellare l'unica copia buona che esisteva prima.
        try:
            os.makedirs(d, exist_ok=True)
            shutil.move(sample_wav, os.path.join(d, "sample.wav"))
            shutil.move(original_path, os.path.join(d, "original." + original_ext))
            rec = {
                "id": "vc_" + secrets.token_hex(6),
                "token": token,
                "voice_code": code,
                "state": "sample_ok",
                "state_changed_at": t,
                "manage_token": new_token(),
                "resume_token": {"value": new_token(), "expires_at": t + RESUME_TOKEN_DAYS * 86400},
                "owner_email": None, "owner_email_hash": None,
                "lang": lang, "locale": locale, "gender": gender,
                "prompt_text": prompt_text,
                "prompt_version": voice_clone_prompts.prompt_version(prompt_text),
                "sample": dict(metrics or {}, original_ext=original_ext),
                "demo": None, "payment": None,
                "devices": [{"cid": cid, "added_at": t, "via": "creator"}],
                "pending_confirm": None, "confirm_locks": {},
                "consent_at": t, "ui_lang": ui_lang,
                "created_at": t, "ready_at": None, "last_used_at": t,
                "expires_at": t + sample_ttl_sec(), "expiry_warned_at": None,
                "archived": False, "deleted_at": None, "delete_reason": None,
            }
            store().add(rec)
        except Exception:
            shutil.rmtree(d, ignore_errors=True)
            raise
        # Il nuovo record e' gia' salvato: solo ora si puo' far cadere il
        # precedente. La cancellazione dei suoi file (I/O, R2 incluso) resta
        # fuori dal lock del modulo.
        if prev is not None:
            store().delete(prev["id"])
    if prev is not None:
        remove_files(prev)
    upload_to_r2(rec, "sample.wav")
    upload_to_r2(rec, "original." + original_ext)
    return rec


def purge_stale_drafts(now=None):
    """Bozze `sample_ok` oltre la TTL: record via, poi file. Ritorna quante.

    Il record cade per primo: se `remove_files` fallisce su una bozza la
    voce e' comunque sparita per il resto del sistema (nessuna bozza
    orfana rivista da un utente), e le altre bozze scadute non vengono
    trascinate giu' da un singolo errore d'I/O.
    """
    t = _now(now)
    with _lock:
        scadute = [rec for rec in _all()
                   if rec.get("state") == "sample_ok" and (rec.get("expires_at") or 0) <= t]
    n = 0
    for rec in scadute:
        try:
            store().delete(rec["id"])
        except Exception as e:
            print(f"[voice_clone] purge: cancellazione record fallita per {rec['id']}: {e}")
            continue
        n += 1
        try:
            remove_files(rec)
        except Exception as e:
            print(f"[voice_clone] purge: rimozione file fallita per {rec['id']}: {e}")
    return n


# ---------------------------------------------------------------------------
# stati
# ---------------------------------------------------------------------------
def transition(clone_id, new_state, patch=None, now=None):
    if new_state not in STATES:
        raise BadTransition(f"stato sconosciuto: {new_state}")
    with _lock:
        rec = get(clone_id)
        if rec is None:
            raise VoiceGone(clone_id)
        cur = rec.get("state")
        if new_state not in TRANSITIONS.get(cur, set()):
            raise BadTransition(f"{clone_id}: {cur} -> {new_state}")
        t = _now(now)
        upd = dict(patch or {})
        upd["state"] = new_state
        upd["state_changed_at"] = t
        stamp = _STAMP_ON_ENTER.get(new_state)
        if stamp:
            upd.setdefault(stamp, t)
        return store().update(clone_id, upd)


# ---------------------------------------------------------------------------
# vista pubblica
# ---------------------------------------------------------------------------
_SECRET_KEYS = ("token", "manage_token", "resume_token", "owner_email",
                "pending_confirm", "confirm_locks")


def public_view(rec):
    pub = {k: v for k, v in rec.items() if k not in _SECRET_KEYS}
    if rec.get("state") == "ready":
        pub["voice_id"] = voice_id_of(rec)
    return pub


# ---------------------------------------------------------------------------
# uso in generazione (§9)
# ---------------------------------------------------------------------------
def _record_for_voice_id(voice_id):
    tok = token_of(voice_id)
    rec = by_token(tok) if tok else None
    if rec is None:
        raise VoiceGone("voce campione sconosciuta")
    return rec


def _local_lock(token):
    with _lock:
        lk = _local_locks.get(token)
        if lk is None:
            lk = threading.Lock()
            _local_locks[token] = lk
        return lk


def _ensure_local(rec, name):
    """Il file locale, scaricato da R2 se manca (§5.5: nuovo server).

    Serializzato per token: due thread che risolvono la stessa voce nello
    stesso momento non devono avviare due download dello stesso file (il
    secondo trova gia' pronto quanto scaricato dal primo). Il download vero
    e proprio resta fuori dal lock del modulo, solo sotto il lock per token.
    """
    path = os.path.join(voice_dir(rec["token"]), name)
    if os.path.exists(path):
        return path
    with _local_lock(rec["token"]):
        if os.path.exists(path):
            return path
        if storage_backend.is_enabled():
            try:
                ok = storage_backend.download_file(r2_key(rec["token"], name), path)
            except Exception as e:
                print(f"[voice_clone] download R2 fallito per {rec['id']}/{name}: {e}")
                raise SampleUnavailable("campione temporaneamente non disponibile") from e
            if ok:
                return path
        raise VoiceGone(f"voce {rec['id']} senza campione")


def resolve(voice_id):
    """Per `voxcpm_tts.clone_block`: wav normalizzato e frase letta."""
    rec = _record_for_voice_id(voice_id)
    if rec.get("state") not in HAS_SAMPLE:
        raise VoiceGone(f"voce {rec['id']} in stato {rec.get('state')}")
    return {"wav_path": _ensure_local(rec, "sample.wav"),
            "prompt_text": rec["prompt_text"], "lang": rec["lang"], "locale": rec["locale"]}


def language_of(voice_id):
    try:
        return _record_for_voice_id(voice_id)["lang"]
    except VoiceGone:
        return None


def _has_cid(rec, cid):
    return any(d.get("cid") == cid for d in rec.get("devices") or [])


def check_use(voice_id, cid, lang, locale):
    """'' se la voce si puo' usare per questo libro, altrimenti il codice
    d'errore della spec §9: gone (D16: solo `ready`), not_authorized, lang_mismatch."""
    try:
        rec = _record_for_voice_id(voice_id)
    except VoiceGone:
        return "voice_gone"
    if rec.get("state") != "ready":
        return "voice_gone"
    if not _has_cid(rec, cid):
        return "voice_not_authorized"
    if (lang or "").lower() != rec["lang"] or (locale or "") != rec["locale"]:
        return "voice_lang_mismatch"
    return ""


def authorized(voice_id, cid):
    try:
        rec = _record_for_voice_id(voice_id)
    except VoiceGone:
        return False
    return rec.get("state") == "ready" and _has_cid(rec, cid)


_TERMINAL = frozenset({"refunded", "expired", "deleted"})


def mine(cid, now=None):
    """Le voci del dispositivo, pronte e in sospeso, senza segreti (§3.6)."""
    out = []
    for rec in _all():
        if rec.get("state") in _TERMINAL or not _has_cid(rec, cid):
            continue
        if rec.get("state") == "sample_ok" and (rec.get("expires_at") or 0) <= _now(now):
            continue
        pub = public_view(rec)
        pub["owner"] = any(d.get("cid") == cid and d.get("via") == "creator"
                           for d in rec.get("devices") or [])
        pub["pending"] = rec.get("state") != "ready"
        out.append(pub)
    out.sort(key=lambda p: (p["pending"], -(p.get("created_at") or 0)))
    return out


def touch_used(clone_id, now=None):
    """Rinnovo della retention a ogni uso (D15). Solo su voci `ready`."""
    with _lock:
        rec = get(clone_id)
        if rec is None or rec.get("state") != "ready":
            return None
        t = _now(now)
        return store().update(clone_id, {"last_used_at": t, "expires_at": t + retention_sec()})


# ---------------------------------------------------------------------------
# dispositivi (§6.3, §6.4)
# ---------------------------------------------------------------------------
CONFIRM_TTL_SEC = 900
CONFIRM_MAX_TRIES = 5
CONFIRM_LOCK_SEC = 900


def _by_code_alive(voice_code):
    rec = by_voice_code(voice_code)
    if rec is None or rec.get("state") in _TERMINAL:
        raise VoiceGone("codice-voce sconosciuto")
    return rec


def _code_hash(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def claim(voice_code, cid, now=None):
    """Primo passo del recupero/dono: o il cid e' gia' dentro, o parte un
    codice di conferma per il proprietario. Il codice in chiaro torna al
    chiamante (che lo spedisce) e nel record resta solo l'hash."""
    t = _now(now)
    with _lock:
        rec = _by_code_alive(voice_code)
        if _has_cid(rec, cid):
            return "ok", rec, None
        locks = rec.get("confirm_locks") or {}
        if locks.get(cid, 0) > t:
            raise ValueError("locked")
        code = f"{secrets.randbelow(1000000):06d}"
        # Pulizia di passaggio: i lock scaduti non restano per sempre nel
        # record solo perche' nessuno li ha mai riletti dopo la scadenza.
        pruned = {k: v for k, v in locks.items() if v > t}
        rec = store().update(rec["id"], {"pending_confirm": {
            "cid": cid, "code_hash": _code_hash(code),
            "expires_at": t + CONFIRM_TTL_SEC, "tries": 0},
            "confirm_locks": pruned})
        return "pending", rec, code


def confirm(voice_code, cid, confirm_code, now=None):
    t = _now(now)
    with _lock:
        rec = _by_code_alive(voice_code)
        pc = rec.get("pending_confirm")
        if not pc or pc.get("cid") != cid:
            return "none"
        if (pc.get("expires_at") or 0) < t:
            store().update(rec["id"], {"pending_confirm": None})
            return "expired"
        if hmac.compare_digest(pc.get("code_hash") or "", _code_hash((confirm_code or "").strip())):
            devices = list(rec.get("devices") or [])
            devices.append({"cid": cid, "added_at": t, "via": "code"})
            store().update(rec["id"], {"pending_confirm": None, "devices": devices})
            return "ok"
        pc = dict(pc, tries=int(pc.get("tries") or 0) + 1)
        if pc["tries"] >= CONFIRM_MAX_TRIES:
            locks = {k: v for k, v in (rec.get("confirm_locks") or {}).items() if v > t}
            locks[cid] = t + CONFIRM_LOCK_SEC
            store().update(rec["id"], {"pending_confirm": None, "confirm_locks": locks})
            return "locked"
        store().update(rec["id"], {"pending_confirm": pc})
        return "wrong"


def _drop_device(rec, cid):
    devices = [d for d in rec.get("devices") or [] if d.get("cid") != cid]
    if len(devices) == len(rec.get("devices") or []):
        return False
    store().update(rec["id"], {"devices": devices})
    return True


def forget(clone_id, cid):
    """«Rimuovi da questo dispositivo»: solo il legame, la voce sopravvive."""
    with _lock:
        rec = get(clone_id)
        return bool(rec) and _drop_device(rec, cid)


def revoke_device(manage_token, cid):
    """Revoca dal proprietario (link con manage_token)."""
    with _lock:
        rec = by_manage_token(manage_token)
        return bool(rec) and _drop_device(rec, cid)


def devices_view(rec):
    return [{"cid_tail": str(d.get("cid") or "")[-4:], "added_at": d.get("added_at"),
             "via": d.get("via")} for d in rec.get("devices") or []]
