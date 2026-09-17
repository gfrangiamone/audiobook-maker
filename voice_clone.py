"""Voci campionate: store, identita', stati, dispositivi, resolver (spec §6,
§9, §10).

Tutto sta in `<data_dir>/user_voices/`, fuori dal tiering hot/cold dei job:

    user_voices/_voice_clones.json      registro (community_store.JsonStore:
    user_voices/_voice_clones.json.bak  lock, scrittura atomica, .bak)
    user_voices/<token>/sample.wav      campione normalizzato
    user_voices/<token>/original.<ext>  file caricato
    user_voices/<token>/demo_*.wav      demo

Su R2 la cartella ha uno specchio fedele sotto lo stesso prefisso `user_voices/`
(vedi la sezione «replica R2»): il registro si ricarica dopo ogni scrittura,
con in piu' una copia datata al giorno in `user_voices/_backup/` (ultime
BACKUP_KEEP); i file dei campioni si caricano appena scritti e `sync_r2()`
ricarica ogni ora quelli mancanti e cancella i prefissi delle voci finite.
Cancellare una voce la cancella anche da R2. Nessun import di audiobook_app:
la data dir arriva da `init()`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
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
# La cartella dei campioni e delle demo delle voci clonate dentro il data dir,
# con lo stesso nome come prefisso su R2. Ha un nome tutto suo (e non
# l'ambiguo 'voices') perche' nel data dir ogni altra cartella e' di un job:
# il cleanup deve poterla riconoscere a colpo sicuro e non toccarla mai.
VOICES_DIRNAME = "user_voices"
R2_PREFIX = VOICES_DIRNAME + "/"
# Il registro sta nella stessa cartella, cosi' `user_voices/` (e il suo
# specchio su R2) contiene tutto quel che serve a ricostruire le voci.
STORE_FILENAME = "_voice_clones.json"
BACKUP_PREFIX = R2_PREFIX + "_backup/"
BACKUP_KEEP = 30
REPLICA_DEBOUNCE_SEC = 2
REPLICA_RETRY_SEC = 30
_RESTORE_ATTEMPTS = 3
_RESTORE_PAUSE_SEC = 2
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # niente 0/O, 1/I/L
RESUME_TOKEN_DAYS = 30
NAME_MAX = 40
_NAME_CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
# ZWJ/ZWNJ (u200c/u200d) restano: servono alla scrittura hindi e alle emoji composte.
_NAME_DROP_RE = re.compile(r"[\u200b\u200e\u200f\u202a-\u202e\u2060-\u206f\ufeff]")

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


class ClaimIncomplete(ValueError):
    """Richiesta con il codice-voce senza il nome del dispositivo o senza la
    presentazione di chi la fa. `field` dice quale dei due manca."""

    def __init__(self, field):
        super().__init__(field)
        self.field = field


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
    """Prepara `user_voices/` e apre il registro. Con R2 attivo, un registro
    assente in locale (server nuovo, disco perso) si scarica da R2 PRIMA di
    aprire lo store: altrimenti ne nascerebbe uno vuoto che la replica
    caricherebbe sopra quello buono."""
    global _data_dir, _store
    _data_dir = str(data_dir)
    os.makedirs(voices_dir(), exist_ok=True)
    _replica_reset()
    _migrate_legacy_store()
    stato = "off"
    if storage_backend.is_enabled():
        stato = "armed" if os.path.exists(store_path()) else _restore_store_from_r2()
    with _replica_cv:
        _replica["state"] = stato
    _store = community_store.JsonStore(VOICES_DIRNAME + "/" + STORE_FILENAME,
                                       on_write=_replica_mark_dirty)


def store():
    if _store is None:
        raise RuntimeError("voice_clone.init() must be called first")
    return _store


def voices_dir():
    return os.path.join(_data_dir, VOICES_DIRNAME)


def voice_dir(token):
    return os.path.join(voices_dir(), token)


def store_path():
    return os.path.join(voices_dir(), STORE_FILENAME)


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


def demo_retries():
    return max(1, _env_int("ABM_VOICE_CLONE_DEMO_RETRIES", 3))


def max_upload_mb():
    return max(1, _env_int("ABM_VOICE_CLONE_MAX_UPLOAD_MB", 20))


def accepted_ext():
    """Estensioni accettate per il campione caricato (lette dall'app per il 400 `format`)."""
    return frozenset(_ACCEPTED_EXT)


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


# ---------------------------------------------------------------------------
# replica R2 di user_voices/
# ---------------------------------------------------------------------------
# Il registro e' l'unico file che cambia di continuo: ogni scrittura dello
# store lo segna "da caricare" e un thread lo carica intero su R2 poco dopo
# (le scritture ravvicinate diventano un solo PUT, e la rete resta fuori dal
# lock dello store). Stati: "off" (R2 spento all'avvio), "armed" (si replica),
# "blocked" (registro locale assente e R2 irraggiungibile all'avvio: non si sa
# se su R2 ce n'e' uno buono, quindi non si carica nulla fino al riavvio).
_replica = {"state": "off", "dirty": False, "backup_day": None}
_replica_cv = threading.Condition()
_replica_thread = None


def _replica_reset():
    with _replica_cv:
        _replica.update(state="off", dirty=False, backup_day=None)


def _today():
    return time.strftime("%Y-%m-%d", time.gmtime())


def _migrate_legacy_store():
    """Il registro stava nella radice del data dir: lo sposta (con il .bak)
    in `user_voices/`. Se esistono entrambi non tocca nulla e lo segnala."""
    vecchio = os.path.join(_data_dir, STORE_FILENAME)
    if not os.path.exists(vecchio):
        return
    nuovo = store_path()
    if os.path.exists(nuovo):
        print(f"[voice_clone] ATTENZIONE: {STORE_FILENAME} presente sia nel data dir sia in "
              f"{VOICES_DIRNAME}/: uso quello in {VOICES_DIRNAME}/, l'altro resta da verificare a mano",
              flush=True)
        return
    os.replace(vecchio, nuovo)
    if os.path.exists(vecchio + ".bak") and not os.path.exists(nuovo + ".bak"):
        os.replace(vecchio + ".bak", nuovo + ".bak")
    print(f"[voice_clone] registro spostato in {VOICES_DIRNAME}/{STORE_FILENAME}", flush=True)


def _registro_valido(data):
    try:
        parsed = json.loads(data)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, dict) and isinstance(parsed.get("items"), list)


def _restore_store_from_r2():
    """Scarica il registro da R2 se il locale manca. Ritorna lo stato della
    replica: "armed" se R2 ha risposto (copia recuperata o assente davvero),
    "blocked" se R2 non risponde o la copia remota non si legge."""
    key = R2_PREFIX + STORE_FILENAME
    for tentativo in range(_RESTORE_ATTEMPTS):
        try:
            if not storage_backend.download_file(key, store_path()):
                return "armed"
            break
        except Exception as e:      # noqa: BLE001
            print(f"[voice_clone] download del registro da R2 fallito "
                  f"({tentativo + 1}/{_RESTORE_ATTEMPTS}): {type(e).__name__}: {e}", flush=True)
            if tentativo + 1 < _RESTORE_ATTEMPTS:
                time.sleep(_RESTORE_PAUSE_SEC)
    else:
        print("[voice_clone] ATTENZIONE: registro assente in locale e R2 irraggiungibile: "
              "replica sospesa fino al riavvio", flush=True)
        return "blocked"
    with open(store_path(), "rb") as f:
        valido = _registro_valido(f.read())
    if valido:
        print(f"[voice_clone] registro recuperato da R2 ({key})", flush=True)
        return "armed"
    os.replace(store_path(), store_path() + ".r2-illeggibile")
    print("[voice_clone] ATTENZIONE: il registro su R2 non si legge: messo da parte, "
          "replica sospesa fino al riavvio", flush=True)
    return "blocked"


def _replica_mark_dirty():
    """Callback dello store (sotto il suo lock): solo segnalare."""
    with _replica_cv:
        stato = _replica["state"]
        if stato == "armed":
            _replica["dirty"] = True
            _replica_cv.notify_all()
    if stato == "armed":
        _start_replica_thread()
    elif stato == "blocked":
        print("[voice_clone] registro modificato ma replica R2 sospesa", flush=True)


def flush_replica():
    """Carica ora il registro su R2 se ci sono scritture non replicate.
    True se ha caricato. Un errore di rete lascia la replica da rifare; un
    registro illeggibile non si carica mai (sovrascriverebbe la copia buona)."""
    with _replica_cv:
        if _replica["state"] != "armed" or not _replica["dirty"]:
            return False
        _replica["dirty"] = False
    if not storage_backend.is_enabled() or _store is None:
        with _replica_cv:
            _replica["dirty"] = True
        return False
    data = _store.raw_bytes()
    if not _registro_valido(data):
        print("[voice_clone] ATTENZIONE: registro locale illeggibile, non replicato su R2", flush=True)
        return False
    try:
        storage_backend.upload_bytes(data, R2_PREFIX + STORE_FILENAME)
    except Exception as e:      # noqa: BLE001
        print(f"[voice_clone] replica del registro su R2 fallita: {type(e).__name__}: {e}", flush=True)
        with _replica_cv:
            _replica["dirty"] = True
        return False
    _backup_daily(data)
    return True


def _backup_daily(data):
    """Una copia datata al giorno, le ultime BACKUP_KEEP: lo specchio
    replica anche gli errori, le copie datate permettono di tornare indietro."""
    giorno = _today()
    if _replica["backup_day"] == giorno:
        return
    stem = STORE_FILENAME[:-len(".json")]
    try:
        storage_backend.upload_bytes(data, f"{BACKUP_PREFIX}{stem}-{giorno}.json")
        _replica["backup_day"] = giorno
        copie = sorted(storage_backend.list_prefix(BACKUP_PREFIX) or [])
        for key in copie[:-BACKUP_KEEP]:
            storage_backend.delete_object(key)
    except Exception as e:      # noqa: BLE001
        print(f"[voice_clone] copia giornaliera del registro fallita: {type(e).__name__}: {e}", flush=True)


def _replica_loop():
    import traceback
    while True:
        try:
            with _replica_cv:
                while not _replica["dirty"]:
                    _replica_cv.wait()
            time.sleep(REPLICA_DEBOUNCE_SEC)
            if not flush_replica() and _replica["dirty"]:
                time.sleep(REPLICA_RETRY_SEC)
        except Exception:      # noqa: BLE001
            traceback.print_exc()
            time.sleep(REPLICA_RETRY_SEC)


def _start_replica_thread():
    global _replica_thread
    with _replica_cv:
        if _replica_thread is not None and _replica_thread.is_alive():
            return
        _replica_thread = threading.Thread(target=_replica_loop, daemon=True,
                                           name="voice-clone-replica")
        _replica_thread.start()


def _files_to_replicate(rec):
    """I file stabili di una voce viva: campione e originale sempre, le demo
    solo da `ready` (prima si rigenerano; `demo_try_*` e i .pcm mai)."""
    ext = (rec.get("sample") or {}).get("original_ext") or "wav"
    nomi = ["sample.wav", f"original.{ext}"]
    if rec.get("state") == "ready":
        nomi += list(DEMO_NAMES)
    return nomi


def sync_r2():
    """Allinea lo specchio R2 di `user_voices/` ai record: carica i file
    delle voci vive che mancano su R2, cancella da R2 (e dal disco) quelli
    delle voci finite. I prefissi senza record si contano e basta: un registro
    perso o rovinato non deve poter cancellare i campioni (incidente del
    12/09/2026). Non solleva."""
    out = {"uploaded": 0, "removed": 0, "unknown": 0}
    if not storage_backend.is_enabled():
        return out
    remoti = {}
    try:
        chiavi = storage_backend.list_prefix(R2_PREFIX) or []
    except Exception as e:      # noqa: BLE001
        print(f"[voice_clone] sync R2: elenco fallito: {type(e).__name__}: {e}", flush=True)
        return out
    for key in chiavi:
        token, sep, nome = key[len(R2_PREFIX):].partition("/")
        if sep and nome and not token.startswith("_"):
            remoti.setdefault(token, set()).add(nome)
    noti = set()
    for rec in list(_all()):
        token = rec.get("token")
        if not token:
            continue
        noti.add(token)
        try:
            if rec.get("state") in HAS_SAMPLE:
                for nome in _files_to_replicate(rec):
                    locale = os.path.join(voice_dir(token), nome)
                    if nome not in remoti.get(token, ()) and os.path.exists(locale):
                        if upload_to_r2(rec, nome):
                            out["uploaded"] += 1
            elif token in remoti or os.path.isdir(voice_dir(token)):
                remove_files(rec)
                if token in remoti:
                    out["removed"] += 1
        except Exception as e:      # noqa: BLE001
            print(f"[voice_clone] sync R2 {rec.get('id')}: {type(e).__name__}: {e}", flush=True)
    out["unknown"] = len(set(remoti) - noti)
    if out["unknown"]:
        print(f"[voice_clone] sync R2: {out['unknown']} prefissi su R2 senza record (lasciati intatti)",
              flush=True)
    return out


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
def discard_draft(clone_id, cid):
    """Abbandono di una bozza mai pagata, dal dispositivo che l'ha creata.

    Serve una via d'uscita: finche' una bozza resta in piedi il bottone del
    campionamento dice «riprendi» e porta dritto al pagamento, e la
    cancellazione dal link di gestione non e' disponibile perche' l'email si
    indica solo al momento del pagamento. Senza questo l'unico modo di
    liberarsene era aspettarne la scadenza.

    Solo da `sample_ok`: dopo il pagamento la rinuncia passa da `reject`, che
    emette il voucher. Restituisce None se la voce non esiste, non e' in quello
    stato o il dispositivo non e' il creatore.
    """
    with _lock:
        rec = get(clone_id)
        if rec is None or rec.get("state") != "sample_ok" or not is_owner(rec, cid):
            return None
        out = store().update(rec["id"], {"state": "deleted", "deleted_at": time.time(),
                                         "delete_reason": "draft_discarded"})
    remove_files(out)
    # Una bozza puo' avere un capture PayPal gia' incassato che non verra' mai
    # consumato (l'ordine nasce prima di commit()): stessa cura di C1.
    _refund_captures(out["id"], "voice_clone_draft_discarded")
    return out


def normalize_name(s):
    """Il nome che l'utente da' alla propria voce, come comparira' nella combo.

    Facoltativo: '' se manca. I caratteri di controllo valgono uno spazio, gli
    invisibili spariscono (anche i marcatori di direzione, che rovescerebbero
    la riga della combo), spazi compattati, al massimo NAME_MAX caratteri."""
    s = _NAME_DROP_RE.sub("", _NAME_CTRL_RE.sub(" ", str(s or "")))
    return " ".join(s.split())[:NAME_MAX].strip()


DEVICE_NAME_MAX = 40

# Browser e sistema riconoscibili dallo User-Agent, nell'ordine in cui vanno
# provati: Edge e Opera si dichiarano anche Chrome, Chrome si dichiara Safari,
# iPad e iPhone si dichiarano «like Mac OS X».
_UA_BROWSERS = (("Edg", "Edge"), ("OPR", "Opera"), ("Firefox", "Firefox"), ("FxiOS", "Firefox"),
                ("CriOS", "Chrome"), ("Chrome", "Chrome"), ("Safari", "Safari"))
_UA_SYSTEMS = (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
               ("Windows", "Windows"), ("Mac OS X", "Mac"), ("CrOS", "ChromeOS"), ("Linux", "Linux"))


def normalize_device_name(s):
    """Il nome con cui l'utente riconosce un dispositivo nella pagina di
    gestione: stessa pulizia del nome della voce, al massimo DEVICE_NAME_MAX."""
    return normalize_name(s)[:DEVICE_NAME_MAX].strip()


IDENTITY_MIN = 10
IDENTITY_MAX = 300


def normalize_identity(s):
    """La presentazione che chi usa un codice-voce scrive per il proprietario
    (§6.4): stessa pulizia del nome, una riga sola, al massimo IDENTITY_MAX
    caratteri. Finisce nell'email e nella pagina dei dispositivi."""
    s = _NAME_DROP_RE.sub("", _NAME_CTRL_RE.sub(" ", str(s or "")))
    return " ".join(s.split())[:IDENTITY_MAX].strip()


def device_name_from_ua(ua):
    """Nome di partenza proposto all'utente («Chrome · Windows»), uguale in
    tutte le lingue. '' se lo User-Agent non dice nulla di riconoscibile."""
    ua = str(ua or "")
    browser = next((n for k, n in _UA_BROWSERS if k in ua), "")
    sistema = next((n for k, n in _UA_SYSTEMS if k in ua), "")
    if not (browser and sistema):
        return ""
    return f"{browser} · {sistema}"


def device_of(rec, cid):
    return next((d for d in (rec or {}).get("devices") or [] if d.get("cid") == cid), None)


def rename(clone_id, cid, name):
    """Rinomina dalla lista «Le tue voci»: solo il dispositivo creatore e solo
    una voce ancora viva. None se non e' possibile; '' toglie il nome."""
    with _lock:
        rec = get(clone_id)
        if rec is None or rec.get("state") in _TERMINAL or not is_owner(rec, cid):
            return None
        return store().update(rec["id"], {"name": normalize_name(name)})


def create_draft(cid, *, lang, locale, gender, prompt_text, sample_wav,
                 original_path, original_ext, metrics, ui_lang, name="", device_name="", now=None):
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
                "name": normalize_name(name),
                "prompt_text": prompt_text,
                "prompt_version": voice_clone_prompts.prompt_version(prompt_text),
                "sample": dict(metrics or {}, original_ext=original_ext),
                "demo": None, "payment": None,
                "devices": [{"cid": cid, "added_at": t, "via": "creator",
                             "name": normalize_device_name(device_name)}],
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
        # Il nome con cui questo dispositivo e' gia' registrato: il wizard lo
        # ripropone alla voce successiva invece di chiederne uno nuovo.
        pub["device_name"] = (device_of(rec, cid) or {}).get("name") or ""
        # Il player della scheda fa sentire il CAMPIONE registrato, non una
        # prova sintetizzata: e' l'unico audio che l'utente riconosce come suo.
        pub["sample_url"] = f"/api/voice_clone/{rec['id']}/sample.wav"
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
def active_voice_for_email(email, exclude_id=None):
    """La voce viva che occupa quell'indirizzo, o None.

    Serve a chi si vede rifiutare l'email in fase di commit: per liberarla
    deve cancellare quella voce dal link di gestione, e il link va rimandato
    proprio a quella voce li'.
    """
    h = email_hash(email)
    for rec in _all():
        if rec.get("id") == exclude_id or rec.get("state") in _TERMINAL:
            continue
        if rec.get("owner_email_hash") == h:
            return rec
    return None


def email_has_active_voice(email, exclude_id=None):
    return active_voice_for_email(email, exclude_id=exclude_id) is not None


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
                     "extra_text": extra_text, "runpod_job_id": None},
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
# Il proprietario puo' leggere l'email ore dopo: il codice vale un giorno
# dalla richiesta, non oltre.
CONFIRM_TTL_SEC = 24 * 3600
CONFIRM_MAX_TRIES = 5
CONFIRM_LOCK_SEC = 900


def _by_code_alive(voice_code):
    rec = by_voice_code(voice_code)
    if rec is None or rec.get("state") in _TERMINAL:
        raise VoiceGone("codice-voce sconosciuto")
    return rec


def _code_hash(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def claim(voice_code, cid, now=None, device_name="", identity=""):
    """Primo passo del recupero/dono: o il cid e' gia' dentro, o parte un
    codice di conferma per il proprietario. Il codice in chiaro torna al
    chiamante (che lo spedisce) e nel record resta solo l'hash.

    Un dispositivo nuovo deve dire come si chiama e chi c'e' dietro
    (`ClaimIncomplete` altrimenti): il proprietario li legge nell'email prima
    di dare il codice, e alla conferma il dispositivo entra con quel nome."""
    t = _now(now)
    with _lock:
        rec = _by_code_alive(voice_code)
        if _has_cid(rec, cid):
            return "ok", rec, None
        locks = rec.get("confirm_locks") or {}
        if locks.get(cid, 0) > t:
            raise ValueError("locked")
        nome = normalize_device_name(device_name)
        if not nome:
            raise ClaimIncomplete("device_name")
        chi = normalize_identity(identity)
        if len(chi) < IDENTITY_MIN:
            raise ClaimIncomplete("identity")
        code = f"{secrets.randbelow(1000000):06d}"
        # Pulizia di passaggio: i lock scaduti non restano per sempre nel
        # record solo perche' nessuno li ha mai riletti dopo la scadenza.
        pruned = {k: v for k, v in locks.items() if v > t}
        rec = store().update(rec["id"], {"pending_confirm": {
            "cid": cid, "code_hash": _code_hash(code),
            "expires_at": t + CONFIRM_TTL_SEC, "tries": 0,
            "device_name": nome, "identity": chi},
            "confirm_locks": pruned})
        return "pending", rec, code


def confirm(voice_code, cid, confirm_code, now=None, device_name=""):
    """Il dispositivo entra con il nome e la presentazione della richiesta,
    cioe' quelli che il proprietario ha letto nell'email. `device_name` serve
    solo per le richieste aperte prima che la richiesta li portasse con se'."""
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
            devices.append({"cid": cid, "added_at": t, "via": "code",
                            "name": pc.get("device_name") or normalize_device_name(device_name),
                            "identity": pc.get("identity") or ""})
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


def add_resume_device(clone_id, cid, device_name, now=None):
    """Autorizza il dispositivo arrivato dal link di ripresa. False se era
    gia' dentro (o la voce non c'e'): nessun duplicato nella lista."""
    t = _now(now)
    with _lock:
        rec = get(clone_id)
        if rec is None or _has_cid(rec, cid):
            return False
        devices = list(rec.get("devices") or []) + [
            {"cid": cid, "added_at": t, "via": "resume", "name": normalize_device_name(device_name)}]
        store().update(rec["id"], {"devices": devices})
        return True


def rename_device(manage_token, cid, name):
    """Rinomina dal link di gestione, l'unico posto dove i dispositivi si
    vedono tutti insieme."""
    with _lock:
        rec = by_manage_token(manage_token)
        if not rec or device_of(rec, cid) is None:
            return False
        devices = [dict(d, name=normalize_device_name(name)) if d.get("cid") == cid else d
                   for d in rec.get("devices") or []]
        store().update(rec["id"], {"devices": devices})
        return True


def devices_view(rec):
    return [{"cid_tail": str(d.get("cid") or "")[-4:], "added_at": d.get("added_at"),
             "via": d.get("via")} for d in rec.get("devices") or []]


RESEND_MAX = 3
RESEND_WINDOW_SEC = 86400


def check_and_record_resend(clone_id, now=None):
    """I3: limita il resend manuale a RESEND_MAX invii per RESEND_WINDOW_SEC
    *per voce* (non per IP: _ip_rl_check e' per-IP, aggirabile cambiando
    client e comunque non lega il limite alla voce che lo subisce).
    Finestra scorrevole su `rec["resend_ts"]`, potata e scritta sotto _lock.
    Ritorna (permesso: bool, retry_after: int|None)."""
    t = _now(now)
    with _lock:
        rec = get(clone_id)
        if rec is None:
            raise VoiceGone(clone_id)
        ts = [x for x in (rec.get("resend_ts") or []) if x > t - RESEND_WINDOW_SEC]
        if len(ts) >= RESEND_MAX:
            store().update(clone_id, {"resend_ts": ts})
            retry_after = int(ts[0] + RESEND_WINDOW_SEC - t) + 1
            return False, max(retry_after, 1)
        ts.append(t)
        store().update(clone_id, {"resend_ts": ts})
        return True, None


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
