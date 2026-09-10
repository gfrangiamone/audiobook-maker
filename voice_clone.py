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
import payment
import storage_backend
import voice_clone_prompts
import voxcpm_catalog

VOICE_ID_PREFIX = "voxcpm:mine:"
R2_PREFIX = "voices/"
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # niente 0/O, 1/I/L
RESUME_TOKEN_DAYS = 30

SWEEP_INTERVAL_SEC = 3600
EXPIRY_WARN_SEC = 30 * 86400
DEMO_FAILED_RELAUNCH_SEC = 6 * 3600
DEMO_FAILED_REFUND_SEC = 7 * 86400
STALE_INFLIGHT_SEC = 3600
APPROVAL_REMINDER_SEC = (24 * 3600, 7 * 86400)
APPROVAL_REFUND_SEC = 30 * 86400
RECORD_PURGE_SEC = 90 * 86400

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
                   "expired": "expired_at", "deleted": "deleted_at",
                   "demos_ready": "demos_ready_at"}

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


class EmailHasVoice(ValueError):
    """L'email ha gia' una voce viva (§3.4): si recupera con il codice o si cancella."""


class PaymentInvalid(ValueError):
    """Il payment_token non e' valido/consumabile (m4): sottoclasse dedicata
    cosi' il chiamante puo' distinguere il fallimento del pagamento da
    qualunque altro ValueError sollevato da commit()."""


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


def enabled():
    raw = (os.environ.get("ABM_VOICE_CLONE_ENABLED") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def regen_max():
    return max(0, _env_int("ABM_VOICE_CLONE_REGEN_MAX", 3))


def demo_retries():
    return max(1, _env_int("ABM_VOICE_CLONE_DEMO_RETRIES", 3))


def max_upload_mb():
    return max(1, _env_int("ABM_VOICE_CLONE_MAX_UPLOAD_MB", 20))


DEMO_NAMES = ("demo_common.wav", "demo_extra.wav")


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


def _refund_captures(clone_id, reason):
    """Rimborso best-effort dei capture PayPal non consumati legati a questa
    voce (C1). Idempotente (`refund_unused_captures_for_job` salta `used`/
    `pending_unfunded`) e non solleva mai: chi chiama e' gia' in un percorso
    di terminazione/pulizia che non deve fallire per questo."""
    try:
        payment.refund_unused_captures_for_job("vc:" + clone_id, reason=reason)
    except Exception as e:
        print(f"[voice_clone] refund capture fallito per {clone_id}: {type(e).__name__}")


def delete_by_owner(manage_token):
    """§6.6: cancellazione dal link di gestione. Da qualunque stato non
    terminale a `deleted`, file rimossi; None se il token e' ignoto.

    `TRANSITIONS` ammette `deleted` solo da `ready` (rifiuto esplicito da
    `demos_ready`/`demo_failed` passa per `reject`, col rimborso). Da uno
    stato intermedio senza quella transizione il proprietario puo' comunque
    cancellare: qui si forza lo stato senza passare da `transition()`. Il
    rimborso automatico (C1) copre entrambi i rami: se `transition()` lo ha
    gia' fatto (ramo normale) la seconda chiamata e' un no-op idempotente.
    """
    with _lock:
        rec = by_manage_token(manage_token)
        if rec is None or rec.get("state") in _TERMINAL:
            return None
        if rec.get("state") not in TRANSITIONS or "deleted" not in TRANSITIONS[rec["state"]]:
            out = store().update(rec["id"], {"state": "deleted", "deleted_at": time.time()})
        else:
            out = transition(rec["id"], "deleted")
    remove_files(out)
    _refund_captures(out["id"], "voice_clone_deleted")
    return out


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
        # C1: la bozza rimpiazzata puo' avere un capture PayPal gia' incassato
        # (l'ordine si crea a partire dalla bozza, prima di commit()) che ora
        # non verra' mai consumato: rimborso automatico, idempotente.
        _refund_captures(prev["id"], "voice_clone_draft_replaced")
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
        _refund_captures(rec["id"], "voice_clone_draft_expired")
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
        out = store().update(clone_id, upd)
    # C1: ogni ingresso in uno stato terminale rimborsa i capture non
    # consumati di questa voce. Fuori dal lock di modulo (il rimborso prende
    # il lock di payment.py: evita un ordine di lock annidato).
    if new_state in _TERMINAL:
        _refund_captures(clone_id, "voice_clone_" + new_state)
    return out


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


def is_owner(rec, cid):
    """Predicato unico di proprieta' (m1): il dispositivo che ha creato la
    voce (`via == "creator"`), non il primo della lista ne' un dispositivo
    autorizzato per altra via (resume/confirm)."""
    return any(d.get("cid") == cid and d.get("via") == "creator"
              for d in rec.get("devices") or [])


def check_use(voice_id, cid, lang, locale=None):
    """'' se la voce si puo' usare per questo libro, altrimenti il codice
    d'errore della spec §9: gone (D16: solo `ready`), not_authorized, lang_mismatch.

    `locale` e' opzionale: vuoto/None -> si confronta solo `lang`; valorizzato
    -> confronto stretto contro `rec["locale"]` (spec §9 riga 479: mismatch su
    lingua/accento del libro). Il chiamante non deve rileggere il locale della
    voce per farlo combaciare con se stesso: passare '' quando non lo ha."""
    try:
        rec = _record_for_voice_id(voice_id)
    except VoiceGone:
        return "voice_gone"
    if rec.get("state") != "ready":
        return "voice_gone"
    if not _has_cid(rec, cid):
        return "voice_not_authorized"
    if (lang or "").lower() != rec["lang"]:
        return "voice_lang_mismatch"
    if locale and locale != rec["locale"]:
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
        pub["owner"] = is_owner(rec, cid)
        pub["pending"] = rec.get("state") != "ready"
        if not pub["owner"]:
            pub.pop("voice_code", None)
        if rec.get("state") == "ready":
            pub["demo_urls"] = {"common": f"/api/voice_clone/{rec['id']}/demo/common",
                                "extra": f"/api/voice_clone/{rec['id']}/demo/extra"}
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
        return store().update(clone_id, {"last_used_at": t, "expires_at": t + retention_sec(),
                                         "expiry_warned_at": None})


# ---------------------------------------------------------------------------
# commit (§3.4, §7.2)
# ---------------------------------------------------------------------------
def email_has_active_voice(email, exclude_id=None):
    h = email_hash(email)
    for rec in _all():
        if rec.get("id") == exclude_id or rec.get("state") in _TERMINAL:
            continue
        if rec.get("owner_email_hash") == h:
            return True
    return False


def _norm_email(email):
    return (email or "").strip().lower()


def commit(clone_id, cid, *, email, extra_id, extra_text, common_text,
           payment_token, price_eur, now=None):
    """Dal campione alla voce pagata (`paid`).

    Sotto il lock di modulo: un doppio click trova la voce gia' oltre
    `sample_ok` e riceve `(rec, False)`; un cid estraneo riceve
    PermissionError; un'email gia' in uso su una voce viva riceve
    EmailHasVoice PRIMA di toccare il pagamento (§10). Con `price_eur <= 0`
    la voce e' gratis. Altrimenti il token viene consumato per primo e, se
    la scrittura del record fallisce, rilasciato (§7.2).
    """
    email = _norm_email(email)
    t = _now(now)
    with _lock:
        rec = get(clone_id)
        if rec is None:
            raise VoiceGone(clone_id)
        if not _has_cid(rec, cid):
            raise PermissionError("cid non autorizzato")
        if rec.get("state") != "sample_ok":
            if rec.get("state") in _TERMINAL:
                raise VoiceGone(clone_id)
            return rec, False
        if email_has_active_voice(email, exclude_id=clone_id):
            raise EmailHasVoice("email gia' associata a una voce")
        price = round(float(price_eur or 0.0), 2)
        job_id = "vc:" + clone_id
        if price <= 0:
            pay = {"type": "free", "token": "", "amount_eur": 0.0, "paid_at": t}
        else:
            try:
                method = payment.consume_payment_token(payment_token, price, job_id,
                                                       purpose="voice_clone")
            except ValueError as e:
                raise PaymentInvalid(str(e)) from e
            pay = {"type": method, "token": payment_token, "amount_eur": price, "paid_at": t}
        patch = {
            "owner_email": email, "owner_email_hash": email_hash(email),
            "demo": {"common_text": common_text, "extra_id": extra_id,
                     "extra_text": extra_text, "regen_used": 0,
                     "regen_max": regen_max(), "runpod_job_id": None},
            "payment": pay,
            "resume_token": {"value": rec["resume_token"]["value"],
                             "expires_at": t + RESUME_TOKEN_DAYS * 86400},
        }
        try:
            out = transition(clone_id, "paid", patch, now=t)
        except Exception:
            if pay["type"] != "free":
                payment.release_payment_token(payment_token, price, job_id, pay["type"],
                                              reason="voice clone commit failed")
            raise
        return out, True


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
    """«Rimuovi da questo dispositivo»: solo il legame, la voce sopravvive.

    m1: il dispositivo creatore non puo' essere rimosso qui, altrimenti il
    proprietario perderebbe per sempre il voice_code (nessun altro modo di
    recuperarlo). Chi vuole liberarsene usa "Cancella" (delete_by_owner)."""
    with _lock:
        rec = get(clone_id)
        if rec is None:
            return False
        if is_owner(rec, cid):
            raise BadTransition("il dispositivo proprietario non puo' essere dimenticato")
        return _drop_device(rec, cid)


def revoke_device(manage_token, cid):
    """Revoca dal proprietario (link con manage_token)."""
    with _lock:
        rec = by_manage_token(manage_token)
        return bool(rec) and _drop_device(rec, cid)


def devices_view(rec):
    return [{"cid_tail": str(d.get("cid") or "")[-4:], "added_at": d.get("added_at"),
             "via": d.get("via")} for d in rec.get("devices") or []]


# ---------------------------------------------------------------------------
# ciclo di vita (§6.5, §10)
# ---------------------------------------------------------------------------
_hooks = {"notify": None, "relaunch": None, "refund": None}


def set_hooks(notify=None, relaunch=None, refund=None):
    _hooks.update({"notify": notify, "relaunch": relaunch, "refund": refund})


def _hook(name, *args, **kw):
    fn = _hooks.get(name)
    if fn is None:
        return
    try:
        fn(*args, **kw)
    except Exception as e:      # noqa: BLE001
        # m3: mai str(e) qui. Gli hook (notify/refund) possono incapsulare
        # errori SMTP che riportano l'indirizzo email del destinatario nel
        # testo dell'eccezione: solo il tipo, mai il messaggio.
        print(f"[voice_clone] hook {name} fallito: {type(e).__name__}", flush=True)


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        raise ValueError(f"timestamp non numerico: {v!r}")


def _sweep_one(rec, t, out):
    state = rec.get("state")
    cid = rec["id"]
    if state == "ready":
        exp = _num(rec.get("expires_at"))
        if exp <= t:
            done = None
            with _lock:
                cur = get(cid)
                if cur and cur.get("state") == "ready":
                    done = transition(cid, "expired", now=t)
            if done is None:
                return  # sparito o gia' mosso da un altro attore: niente da fare
            remove_files(done)
            out["expired"] += 1
            _hook("notify", "expired", done)
        elif exp - t <= EXPIRY_WARN_SEC and not rec.get("expiry_warned_at"):
            store().update(cid, {"expiry_warned_at": t})
            out["warned"] += 1
            _hook("notify", "expiring", rec, days=max(0, int((exp - t) // 86400)))
        return
    if state in _TERMINAL:
        stamp = _num(rec.get(_STAMP_ON_ENTER.get(state) or "") or rec.get("created_at"))
        if t - stamp >= RECORD_PURGE_SEC:
            store().delete(cid)
            out["purged"] += 1
        return
    if state in ("paid", "demos_generating"):
        # I1: un record fermo in uno stato "in volo" oltre STALE_INFLIGHT_SEC
        # (nessun cambio di stato) e' quasi sempre un thread di generazione
        # morto senza che demo_failed/demos_ready sia mai stato scritto
        # (crash, riavvio). Rilancia come per demo_failed: idempotente lato
        # relaunch hook (start_demos su un record non piu' in questo stato
        # e' un no-op).
        # TODO piano 3: rilancio ogni sweep senza backoff ne' cap sui tentativi.
        if t - _num(rec.get("state_changed_at")) >= STALE_INFLIGHT_SEC:
            out["relaunched"] += 1
            _hook("relaunch", cid)
        return
    demo = rec.get("demo") or {}
    if state == "demo_failed":
        first = _num(demo.get("first_failed_at") or demo.get("failed_at") or rec.get("paid_at"))
        if t - first >= DEMO_FAILED_REFUND_SEC:
            out["refunded"] += 1
            _hook("refund", cid, "demo_failed_timeout")
        elif t - _num(demo.get("failed_at")) >= DEMO_FAILED_RELAUNCH_SEC:
            # TODO piano 3: rilancio ogni 6h senza backoff ne' cap sui tentativi.
            out["relaunched"] += 1
            _hook("relaunch", cid)
        return
    if state == "demos_ready":
        since = _num(rec.get("demos_ready_at") or rec.get("paid_at"))
        if t - since >= APPROVAL_REFUND_SEC:
            out["refunded"] += 1
            _hook("refund", cid, "no_approval")
            return
        sent = list(demo.get("reminders") or [])
        for stage, delay in enumerate(APPROVAL_REMINDER_SEC, start=1):
            if stage not in sent and t - since >= delay:
                sent.append(stage)
                store().update(cid, {"demo": dict(demo, reminders=sent)})
                out["reminded"] += 1
                _hook("notify", "approval_reminder", rec, stage=stage)
                break


def sweep(now=None):
    """Un giro del ciclo di vita. Ogni record e' isolato: un errore su uno
    non ferma gli altri (incidente cleanup loop 2026-06-15)."""
    t = _now(now)
    out = {"drafts_purged": 0, "warned": 0, "expired": 0, "purged": 0,
           "relaunched": 0, "refunded": 0, "reminded": 0}
    try:
        purged = purge_stale_drafts(now=t)
        out["drafts_purged"] = purged if isinstance(purged, int) else len(purged or [])
    except Exception as e:      # noqa: BLE001
        print(f"[voice_clone] purge bozze fallita: {e}", flush=True)
    for rec in list(_all()):
        try:
            _sweep_one(rec, t, out)
        except Exception as e:      # noqa: BLE001
            print(f"[voice_clone] sweep {rec.get('id')}: {type(e).__name__}: {e}", flush=True)
    try:
        reconcile_orphan_captures(now=t)
    except Exception as e:      # noqa: BLE001
        print(f"[voice_clone] reconcile_orphan_captures fallita: {type(e).__name__}", flush=True)
    return out


def reconcile_orphan_captures(now=None):
    """C1 safety net: rete di sicurezza per capture PayPal `vc:<id>` mai
    consumati che i punti di rimborso mirati (draft sostituita/scaduta,
    ingresso in stato terminale) non hanno intercettato — es. un capture
    creato per una bozza mai diventata record (crash fra create-order e
    create_draft) o un record cancellato dal DB con un capture ancora
    aperto. Non solleva mai: e' chiamata dallo sweep orario e da
    `voice_clone_demo.recover()` al boot.

    Per ogni capture PayPal incassato e non consumato con `job_id` che
    inizia per "vc:", piu' vecchio di `sample_ttl_sec()` (evita falsi
    positivi sulla normale finestra pagamento -> commit):
      - record assente, terminale o ancora `sample_ok` -> rimborso
        (`refund_unused_capture`, idempotente).
      - record vivo (paid/demos_*/ready) con capture non consumato: per
        costruzione impossibile (commit consuma il token PRIMA di scrivere
        il record) -> anomalia, loggata per revisione admin, MAI rimborsata
        automaticamente qui (potrebbe essere un secondo capture legittimo
        non ancora riconciliato).
    """
    t = _now(now)
    try:
        capture = payment.iter_unused_captures(min_age_sec=sample_ttl_sec(), now=t)
    except Exception as e:      # noqa: BLE001
        print(f"[voice_clone] reconcile: iter_unused_captures fallita: {type(e).__name__}")
        return 0
    n = 0
    for row in capture:
        job_id = row.get("job_id") or ""
        if not job_id.startswith("vc:"):
            continue
        clone_id = job_id[len("vc:"):]
        rec = get(clone_id)
        if rec is None or rec.get("state") in _TERMINAL or rec.get("state") == "sample_ok":
            try:
                payment.refund_unused_capture(row["order_id"], reason="voice_clone_orphan_reconcile")
                n += 1
            except Exception as e:      # noqa: BLE001
                print(f"[voice_clone] reconcile: refund fallito order={row.get('order_id')}: "
                     f"{type(e).__name__}")
        else:
            # Vivo con capture non consumato: impossibile per costruzione,
            # mai email/token nel log.
            print(f"[voice_clone] ORPHAN capture on live voice id={clone_id} "
                 f"order={row.get('order_id')}")
    return n


def digest_data(window_hours=24, now=None):
    """Sezione «Voci campionate» del digest admin (§12): solo contatori."""
    t = _now(now)
    since = t - int(window_hours) * 3600
    counts = {}
    active = 0

    def bump(label):
        counts[label] = counts.get(label, 0) + 1

    for rec in _all():
        st = rec.get("state")
        if st == "ready":
            active += 1
        if st == "demo_failed":
            bump("demo_failed")
        if (rec.get("paid_at") or 0) >= since:
            bump("paid")
        if (rec.get("ready_at") or 0) >= since:
            bump("ready")
        if st == "refunded" and (rec.get("refunded_at") or 0) >= since:
            bump("refunded:" + ((rec.get("refund") or {}).get("reason") or "unknown"))
        if st == "expired" and (rec.get("expired_at") or 0) >= since:
            bump("expired")
        if st == "deleted" and (rec.get("deleted_at") or 0) >= since:
            bump("deleted")
    rows = [{"label": k, "count": v} for k, v in sorted(counts.items())]
    return {"window_hours": int(window_hours), "rows": rows, "active_ready": active}
