"""cleanup — cleanup loop e supervisore, tiering hot/cold, marker, memoria
(E3, seam cleanup/tiering/supervisor, 2026-10-10).

Spostato pari pari da `audiobook_app`: eviction hot->cold e riconciliazione
dell'offload, marker email e forense che proteggono una work dir, cleanup
di un job e delle share scadute, riconciliazione dei capture PayPal non
consumati, statistiche di memoria e `malloc_trim`, campionatore del carico
col suo supervisore, `_cleanup_loop` e `_cleanup_supervisor`. Nessuna
route. Leggere `docs/STORAGE_TIERING.md` prima di toccare eviction e
offload (invariante copy-before-delete).

`configure(...)` riceve dalla app, come funzioni risolte a ogni chiamata
(i test le sostituiscono sulla app), gli helper in FUNCS e i valori in
VALUES (`jobs`, `UPLOAD_DIR`, `_DATA_DIR`, email admin, retention, mappa
degli esiti account); per riferimento il lock dei job e il modulo
`generation_engine` (che un modulo di servizio non importa). Non importa
`audiobook_app`.
"""
import html as html_mod
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import accounts
import assembly_queue
import db
import jsonl_audit
import load_metrics
import payment
import pending_jobs
import storage_backend
import storage_tiering
import token_store as _tkstore
import voice_clone
import voxcpm_tts
import retry_util as _retry
from env_utils import env_int

_cfg = {}
_jobs_lock = None
generation_engine = None

FUNCS = ['_activity_log_dir', '_log_activity', '_effective_retention_for_job', '_effective_retention_for_token_info', '_send_email', '_smtp_available', '_abuse_cleanup_decision', '_abuse_keep_state', '_active_generating_total_unlocked', '_try_send_admin_digest', '_try_send_voxcpm_digest']
VALUES = ('jobs', 'upload_dir', 'data_dir', 'admin_email', 'email_file_retention_sec', 'gemini_file_retention_sec', 'gemini_no_download_retention_multiplier', 'share_ttl_sec', 'acct_settle_map')


def configure(*, jobs_lock, engine, **fns):
    """`fns`: una funzione per ogni nome in FUNCS e VALUES (la app passa
    lambda che risolvono i suoi globali a ogni chiamata)."""
    missing = [n for n in FUNCS + list(VALUES) if n not in fns]
    assert not missing, f"cleanup.configure: mancano {missing}"
    _cfg.update(fns)
    globals()["_jobs_lock"] = jobs_lock
    globals()["generation_engine"] = engine


# Valori della app usati dal codice spostato: risolti a ogni chiamata.
def _jobs():
    return _cfg["jobs"]()

def _upload_dir():
    return _cfg["upload_dir"]()

def _data_dir():
    return _cfg["data_dir"]()

def _admin_email():
    return _cfg["admin_email"]()

def _email_file_retention_sec():
    return _cfg["email_file_retention_sec"]()

def _gemini_file_retention_sec():
    return _cfg["gemini_file_retention_sec"]()

def _gemini_no_download_retention_multiplier():
    return _cfg["gemini_no_download_retention_multiplier"]()

def _share_ttl_sec():
    return _cfg["share_ttl_sec"]()

def _acct_settle_map():
    return _cfg["acct_settle_map"]()


# Gli stessi nomi che il codice usava in audiobook_app: ogni chiamata passa
# dalla funzione configurata, cosi' `monkeypatch.setattr(audiobook_app, ...)`
# nei test vale anche qui.
def _activity_log_dir(*a, **k):
    return _cfg["_activity_log_dir"](*a, **k)


def _log_activity(*a, **k):
    return _cfg["_log_activity"](*a, **k)

def _effective_retention_for_job(*a, **k):
    return _cfg["_effective_retention_for_job"](*a, **k)

def _effective_retention_for_token_info(*a, **k):
    return _cfg["_effective_retention_for_token_info"](*a, **k)

def _send_email(*a, **k):
    return _cfg["_send_email"](*a, **k)

def _smtp_available(*a, **k):
    return _cfg["_smtp_available"](*a, **k)

def _abuse_cleanup_decision(*a, **k):
    return _cfg["_abuse_cleanup_decision"](*a, **k)

def _abuse_keep_state(*a, **k):
    return _cfg["_abuse_keep_state"](*a, **k)

def _active_generating_total_unlocked(*a, **k):
    return _cfg["_active_generating_total_unlocked"](*a, **k)

def _try_send_admin_digest(*a, **k):
    return _cfg["_try_send_admin_digest"](*a, **k)

def _try_send_voxcpm_digest(*a, **k):
    return _cfg["_try_send_voxcpm_digest"](*a, **k)


CLEANUP_GRACE_AFTER_DOWNLOAD_SEC = 5 * 60  # 5 min grazia dopo download diretto
CLEANUP_HEARTBEAT_TIMEOUT_SEC = 60          # heartbeat perso per 60s = browser chiuso
CLEANUP_INTERVAL_SEC = 60                   # check every 60 seconds
CLEANUP_ORPHAN_DIR_AGE_SEC = 2 * 60 * 60   # cartelle orfane > 2h vengono rimosse
# Finestra in cui il purge per heartbeat perso resta sospeso perche' il job e'
# nella fase di assembly (in coda per uno slot FFmpeg, o gia' sotto encode).
# Copre il timeout della coda (ABM_ASSEMBLY_WAIT_TIMEOUT_SEC, 1800s) piu'
# l'encode: oltre, il job torna purgabile e non puo' restare vivo per sempre.
CLEANUP_ASSEMBLY_GRACE_SEC = 60 * 60

# Nel data dir non ci sono solo le cartelle dei job: `user_voices/` e' la casa
# delle voci campionate (registro `_voice_clones.json` e cartelle dei campioni),
# e su R2 e' il prefisso con lo stesso nome, uno specchio permanente tenuto
# allineato da voice_clone (replica del registro + sync_r2). Lo sweep delle
# cartelle orfane la scambiava per una job dir abbandonata e la cancellava da
# disco E da cold (12/09/2026: campioni e demo di tutte le voci distrutti, con
# i record ancora in stato ready e i file spariti). Ogni scansione del data dir
# passa da _is_job_dir, e il cold delete rifiuta i prefissi riservati.
# "voices" e' il nome storico della stessa cartella: resta riservato perche'
# una copia rimasta da prima del rename non deve finire nel tritacarne.
# "accounts" e' il prefisso cold dei backup di abm.db (_ACCT_R2_PREFIX): oggi
# nessuno sweep lo raggiunge (i backup sono file, non cartelle), ma riservarlo
# costa una parola e impedisce che un domani un delete_prefix("accounts/")
# cancelli le copie del database degli account.
# "logs" e' la cartella del business log in prod (ABM_ACTIVITY_LOG_DIR =
# data/logs): file mensili + activity.db, mai una job dir. In piu' qualunque
# ABM_ACTIVITY_LOG_DIR che cada dentro il data dir e' riservata col suo nome,
# qualunque esso sia (vedi _reserved_data_dir_names).
_RESERVED_DATA_DIRS = frozenset({voice_clone.VOICES_DIRNAME, "voices", "accounts", "logs"})


def _reserved_data_dir_names():
    """_RESERVED_DATA_DIRS piu' il nome della cartella dei log, se sta
    direttamente nel data dir. Risolta a ogni chiamata: segue l'env."""
    names = set(_RESERVED_DATA_DIRS)
    try:
        log_dir = _activity_log_dir().resolve()
        if log_dir.parent == _upload_dir().resolve():
            names.add(log_dir.name)
    except OSError:
        pass
    return names


def _is_job_dir(entry):
    """True se la voce del data dir e' (o e' stata) la cartella di un job."""
    return (entry.is_dir()
            and not entry.name.startswith("_")
            and entry.name not in _reserved_data_dir_names())


def _assembly_purge_hold(job, now):
    """True se il job va risparmiato dal purge perche' e' in fase di assembly.

    `assembly_started_at` viene messo da `generation_engine._acquire_assembly_slot`
    all'ingresso in coda e tolto al rilascio dello slot. Un timestamp assurdo o
    troppo vecchio non deve rendere il job immortale: oltre la finestra di
    grazia il purge riprende normalmente.
    """
    ts = job.get("assembly_started_at")
    if not ts:
        return False
    try:
        return (now - float(ts)) < CLEANUP_ASSEMBLY_GRACE_SEC
    except (TypeError, ValueError):
        return False


# Quiete richiesta prima di considerare "finito" un file locale rigenerato dopo
# l'offload (stesso valore usato dall'offload in generation_engine).
EVICT_REGEN_QUIET_SEC = env_int("ABM_OFFLOAD_QUIET_SEC", 180)
# Dedup dei log di mismatch sospetto: la condizione persiste per tutta la
# retention e senza dedup riempirebbe syslog con una riga ogni 60s per file.
_EVICT_MISMATCH_LOGGED = {}


def _local_output_intact(path):
    """Verifica strutturale LOCALE di un output rigenerato.
    True = integro, False = corrotto/troncato, None = formato per cui non
    esiste un check economico (il chiamante lo tratta come NON verificato)."""
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError:
        return False
    if size <= 0:
        return False
    suf = p.suffix.lower()
    if suf in (".abm", ".zip"):
        import zipfile
        try:
            if not zipfile.is_zipfile(str(p)):
                return False
            with zipfile.ZipFile(str(p), "r") as zf:
                return zf.testzip() is None
        except Exception:
            return False
    if suf in (".m4b", ".m4a", ".mp4"):
        # Stessa camminata atom di _cold_m4b_valid, ma sul file locale: un m4b
        # senza 'moov' è un output interrotto, mai autoritativo.
        try:
            with open(str(p), "rb") as fh:
                offset = 0
                guard = 0
                while offset < size:
                    guard += 1
                    if guard > 64:
                        return False
                    fh.seek(offset)
                    hdr = fh.read(16)
                    if len(hdr) < 8:
                        return False
                    boxsize = int.from_bytes(hdr[0:4], "big")
                    boxtype = hdr[4:8]
                    header = 8
                    if boxsize == 1:
                        if len(hdr) < 16:
                            return False
                        boxsize = int.from_bytes(hdr[8:16], "big")
                        header = 16
                    elif boxsize == 0:
                        boxsize = size - offset
                    if boxtype == b"moov":
                        return True
                    if boxsize < header:
                        return False
                    offset += boxsize
            return False
        except OSError:
            return False
    return None


def _evict_mismatch_should_log(key, cold_size, local_size):
    """True solo la prima volta che si osserva questa coppia di dimensioni per
    la chiave: evita il loop di log a ogni sweep sullo stesso mismatch."""
    sig = (cold_size, local_size)
    if _EVICT_MISMATCH_LOGGED.get(key) == sig:
        return False
    if len(_EVICT_MISMATCH_LOGGED) > 500:
        _EVICT_MISMATCH_LOGGED.clear()
    _EVICT_MISMATCH_LOGGED[key] = sig
    return True


def _evict_hot_local():
    """Cancella i file di output LOCALI dei job la cui finestra calda è scaduta
    e che risultano già su cold storage. Preserva dir + marker .cloud_uploaded
    così i download successivi vengono rediretti al presigned URL.
    No-op se il cold storage non è configurato."""
    if not storage_backend.is_enabled():
        return
    now = time.time()
    with _jobs_lock:
        job_by_id = dict(_jobs())
    try:
        for jdir in _upload_dir().iterdir():
            if not _is_job_dir(jdir):
                continue
            job = job_by_id.get(jdir.name, {})
            hot = storage_tiering.hot_window_sec(job)
            # B3 guard A (incidente 2026-06): job fallito/rimborsato → l'output
            # locale NON è autoritativo (es. m4b silente da un run quality-fail).
            # Niente eviction né re-upload per l'intera job dir: il vecchio
            # comportamento ha sovrascritto su cold una copia da 15.4MB con il
            # garbage da 696KB del re-run fallito. Entrambe le copie restano
            # congelate finché il marker forense è valido / il job è in error.
            if job.get("status") == "error" or _forensic_marker_protects(jdir, now):
                continue
            try:
                for od in jdir.iterdir():
                    if not od.is_dir():
                        continue
                    if not (od.name == "output" or od.name.startswith("output_")):
                        continue
                    uploaded_at = storage_tiering.cloud_uploaded_at(od)
                    if uploaded_at is None or (now - uploaded_at) <= hot:
                        continue
                    for f in od.rglob("*"):
                        if not f.is_file() or not storage_tiering.is_offloadable(f.name):
                            continue
                        key = storage_tiering.key_for_path(str(f))
                        if not key:
                            continue
                        try:
                            # INVARIANTE (F3): non cancellare mai un file HOT se la
                            # copia COLD non COMBACIA per dimensione. La sola
                            # esistenza non basta: un cold TRONCATO (es. m4b senza
                            # moov caricato mid-write) esiste ma è più piccolo del
                            # locale completo. Verifica size cold == size local; se
                            # manca o differisce, ri-CARICA il locale (autoritativo),
                            # ri-verifica, e SOLO a match confermato rimuovi il locale.
                            local_size = f.stat().st_size
                            cold_size = storage_backend.object_size(key)
                            cold_ok = (cold_size == local_size)
                            if not cold_ok:
                                # B3 guard B: il re-upload "locale autoritativo"
                                # vale SOLO nella direzione F3 (cold assente o
                                # TRONCATO, cioe' piu' piccolo del locale). Un
                                # cold PIU' GRANDE del locale e' il segnale
                                # opposto (locale sospetto/garbage): mai
                                # sovrascriverlo alla cieca — si tengono
                                # entrambe le copie e si logga per ispezione.
                                # NB: una re-gen legittima con output diverso
                                # aggiorna il cold gia' al COMPLETE (offload
                                # idempotente per size), quindi non passa di qui.
                                # ECCEZIONE (2026-08): un locale SCRITTO DOPO il
                                # marker .cloud_uploaded è una RIgenerazione
                                # post-offload (es. lo snapshot .abm ricostruito
                                # da /api/download?type=abm), non garbage: lo
                                # zip nuovo può essere di pochi byte più piccolo
                                # del cold e senza questa eccezione il guard B
                                # bloccava l'evict per sempre, ri-loggando a ogni
                                # sweep. Si promuove solo se il file è ormai
                                # quiescente (non mid-write) e supera il check
                                # strutturale locale.
                                if cold_size is not None and cold_size > local_size:
                                    local_mtime = f.stat().st_mtime
                                    regenerated = (
                                        local_mtime > uploaded_at
                                        and (now - local_mtime) >= EVICT_REGEN_QUIET_SEC
                                        and _local_output_intact(f) is True
                                    )
                                    if not regenerated:
                                        if _evict_mismatch_should_log(key, cold_size, local_size):
                                            print(f"[hot-evict] MISMATCH SOSPETTO "
                                                  f"(cold={cold_size} > local={local_size}): "
                                                  f"NO overwrite, NO evict — ispezione "
                                                  f"manuale richiesta: {f}")
                                        continue
                                    print(f"[hot-evict] locale RIGENERATO dopo l'offload "
                                          f"(mtime +{int(local_mtime - uploaded_at)}s, integro): "
                                          f"cold={cold_size} → local={local_size}, re-upload: {f}")
                                print(f"[hot-evict] cold copy MISSING/TRUNCATED "
                                      f"(cold={cold_size} vs local={local_size}) — "
                                      f"re-upload before evict: {f}")
                                try:
                                    storage_backend.upload_file(str(f), key)
                                    cold_size = storage_backend.object_size(key)
                                    cold_ok = (cold_size == local_size)
                                except Exception as e:
                                    print(f"[hot-evict] upload-before-evict failed for {f}: {e}")
                                    cold_ok = False
                            if cold_ok:
                                _EVICT_MISMATCH_LOGGED.pop(key, None)
                                f.unlink()
                                print(f"[hot-evict] Local removed (cold copy ok, {local_size}B): {f}")
                            else:
                                print(f"[hot-evict] KEEP local (cold copy NOT confirmed): {f}")
                        except OSError:
                            pass
                        except Exception as e:
                            print(f"[hot-evict] error on {f}: {e}")
            except OSError:
                continue
    except OSError:
        pass


def _reconcile_cold_offload():
    """Ri-tenta l'offload su cold per gli output completati che NON risultano
    ancora caricati (marker .cloud_uploaded assente). Copre il caso in cui il
    tentativo a fine generazione sia fallito o abbia fatto no-op silenzioso:
    senza questo pass un job PREMIUM resterebbe single-tier (solo locale) e una
    perdita del locale (anche un rm manuale) sarebbe irrecuperabile.
    No-op se il cold storage non è configurato."""
    if not storage_backend.is_enabled():
        return
    now = time.time()
    with _jobs_lock:
        job_by_id = dict(_jobs())
    try:
        for jdir in _upload_dir().iterdir():
            if not _is_job_dir(jdir):
                continue
            # Salta i job ANCORA ATTIVI: offloaderanno al proprio COMPLETE.
            # Toccarli ora rischierebbe di copiare file mid-write (vedi F1);
            # _offload_to_cloud comunque rifiuta, ma evitiamo il log a ogni giro.
            # "translated"/"optimized" sono stati TERMINALI quanto "done": senza
            # includerli, gli output di traduzione e i .abm ottimizzati non
            # venivano mai riconciliati finche' il job restava in memoria — e
            # restavano single-tier (solo locale) a tempo indeterminato.
            _j = job_by_id.get(jdir.name)
            if _j is not None and _j.get("status") not in (
                    "done", "partial", "error", "translated", "optimized"):
                continue
            try:
                for od in jdir.iterdir():
                    if not od.is_dir():
                        continue
                    if not (od.name == "output" or od.name.startswith("output_")):
                        continue
                    if storage_tiering.cloud_uploaded_at(od) is not None:
                        continue  # già confermato su cold
                    has_offloadable = any(
                        f.is_file() and storage_tiering.is_offloadable(f.name)
                        for f in od.rglob("*")
                    )
                    if not has_offloadable:
                        continue
                    try:
                        generation_engine._offload_to_cloud(jdir.name, str(od), now)
                    except Exception as e:
                        print(f"[reconcile] offload error {od}: {e}")
            except OSError:
                continue
    except OSError:
        pass


# Marker scritto nella job dir per proteggere la cartella dal cleanup orfani
# di OGNI worker Gunicorn. Il filesystem è l'unica fonte autoritativa condivisa.
# Due stati possibili nel contenuto del file:
#   - "pending"  → email registrata, lavorazione in corso. Protezione illimitata
#                  fino al cap EMAIL_PENDING_MAX_AGE_SEC (anti-orphan se worker
#                  crasha durante un job lungo).
#   - "<float>"  → email inviata al timestamp indicato. Protezione per
#                  EMAIL_FILE_RETENTION_SEC + 300s da quel timestamp.
EMAIL_MARKER_FILENAME = ".email_sent"
_EMAIL_MARKER_PENDING = "pending"
EMAIL_PENDING_MAX_AGE_SEC = 48 * 3600  # cap di sicurezza se la lavorazione si interrompe senza email

# Marker scritto in work_dir dei job Gemini falliti con refund per consentire
# analisi forense post-mortem. Contiene JSON {retain_until, created_at, kind,
# outcome, reason, job_id, days}. Sopravvive a restart del service e blocca
# TUTTI i branch di cleanup (status=error, orphan dir, token-orphan, orphan
# output) finché now < retain_until. Retention configurabile via
# ABM_GEMINI_FORENSIC_RETENTION_DAYS (default 7; 0 = disabilita).
FORENSIC_MARKER_FILENAME = ".forensic_retain.json"
try:
    FORENSIC_RETENTION_DAYS = env_int("ABM_GEMINI_FORENSIC_RETENTION_DAYS", 7)
except (TypeError, ValueError):
    FORENSIC_RETENTION_DAYS = 7
FORENSIC_RETENTION_DAYS = max(0, FORENSIC_RETENTION_DAYS)


def _delete_cold_for_job(job_id):
    """Cancella tutti gli oggetti cold del job (prefisso '<job_id>/'). No-op se
    il backend non è configurato. Tollerante agli errori: non deve mai bloccare
    il cleanup locale."""
    if not storage_backend.is_enabled() or not job_id:
        return
    if job_id in _reserved_data_dir_names():
        # Non e' un job: sotto quel prefisso ci sono campioni vocali, log o
        # backup degli account.
        print(f"[cleanup] Cold delete rifiutato sul prefisso riservato {job_id}/")
        return
    try:
        storage_backend.delete_prefix(f"{job_id}/")
        print(f"[cleanup] Cold objects removed for job {job_id}")
    except Exception as e:
        print(f"[cleanup] Cold delete error for {job_id}: {e}")


def _marker_protection_window(is_gemini):
    """Finestra di protezione (sec) da incidere nel marker email, per tipo voce.

    - Gemini (True): finestra estesa no-download (prudenza massima sui file
      PREMIUM, mai cancellati prima della finestra completa).
    - Standard (False): retention base email (18h): la dir standard NON va
      sovra-protetta con la finestra Gemini.
    - Ignoto (None): ritorna None → il lettore usa il fallback conservativo
      max() (favorisce sempre la conservazione del file generato)."""
    if is_gemini is True:
        return _gemini_file_retention_sec() * _gemini_no_download_retention_multiplier()
    if is_gemini is False:
        return _email_file_retention_sec()
    return None


def _write_email_marker(work_dir, when=None, is_gemini=None):
    """Marca una job dir come 'email inviata' (timestamp epoch in secondi).
    Sovrascrive un eventuale marker 'pending'. Idempotente.

    Formato del contenuto:
      - "<ts>"                  → legacy, lettura con fallback conservativo max().
      - "<ts>|<retention_sec>"  → self-describing: il cleanup applica la finestra
                                  CORRETTA per tipo voce senza sovra-proteggere le
                                  dir standard con la finestra Gemini (96h).
    Quando `is_gemini` è None (tipo voce ignoto) si scrive la forma legacy: il
    lettore protegge in modo conservativo. La forma self-describing si usa solo
    quando il tipo voce è noto con certezza."""
    ts = float(when) if when is not None else time.time()
    marker = Path(work_dir) / EMAIL_MARKER_FILENAME
    window = _marker_protection_window(is_gemini)
    content = f"{ts:.3f}|{int(window)}" if window is not None else f"{ts:.3f}"
    # G6: il marker è l'unica protezione marker-based della dir dal cleanup.
    # Una scrittura fallita silenziosamente lasciava la dir esposta: qui
    # ritentiamo, verifichiamo la presenza e logghiamo forte il fallimento.
    def _write(attempt):
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(content, encoding="utf-8")
        if not marker.exists():
            raise OSError("marker assente dopo la scrittura")

    try:
        _retry.retry_call(_write, attempts=3, is_retryable=lambda e: isinstance(e, OSError),
                          wait=lambda attempt, e: 0.2 * (attempt + 1),
                          on_retry=lambda attempt, e, secs: print(
                              f"[email-marker] write failed in {work_dir} (attempt {attempt + 1}/3): {e}"))
        return
    except OSError as e:
        print(f"[email-marker] write failed in {work_dir} (attempt 3/3): {e}")
    print(f"[email-marker] PERSISTENT FAILURE in {work_dir} — dir NON protetta "
          f"dal cleanup marker-based (resta la protezione via token)")


def _write_email_pending_marker(work_dir):
    """Marca una job dir come 'email registrata, lavorazione in corso'.
    Non sovrascrive un marker timestamp già presente (email già inviata).
    Non riscrive se è già 'pending' (preserva mtime → cap age coerente)."""
    try:
        marker = Path(work_dir) / EMAIL_MARKER_FILENAME
        marker.parent.mkdir(parents=True, exist_ok=True)
        if marker.exists():
            try:
                existing = marker.read_text(encoding="utf-8").strip()
                if existing == _EMAIL_MARKER_PENDING:
                    return
                # Se è un timestamp valido (legacy "<ts>" o self-describing
                # "<ts>|<win>"), l'email è già stata inviata: NON degradare a
                # 'pending' (ridurrebbe la finestra di protezione del file).
                float(existing.partition("|")[0])
                return
            except (OSError, ValueError):
                pass  # contenuto illeggibile/corrotto: sovrascriviamo
        marker.write_text(_EMAIL_MARKER_PENDING, encoding="utf-8")
    except OSError as e:
        print(f"[email-marker] pending write failed in {work_dir}: {e}")


def _email_marker_protects(work_dir, now):
    """True se il marker email protegge la dir.
    Pending: protetto se mtime entro EMAIL_PENDING_MAX_AGE_SEC.
    Timestamp: protetto se entro max(_email_file_retention_sec(),
    _gemini_file_retention_sec() * _gemini_no_download_retention_multiplier()) + 300s.
    Usiamo il max perche' il marker su disco non conosce voice/downloaded_at del job;
    moltiplichiamo per il fattore no-download per non cancellare un Gemini job dir
    mai scaricato prima della finestra estesa (default 96h)."""
    marker = Path(work_dir) / EMAIL_MARKER_FILENAME
    try:
        if not marker.exists():
            return False
    except OSError:
        return False
    try:
        content = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if content == _EMAIL_MARKER_PENDING:
        try:
            mtime = marker.stat().st_mtime
        except OSError:
            return False
        return (now - mtime) < EMAIL_PENDING_MAX_AGE_SEC
    # Forma self-describing "<ts>|<retention_sec>": usa la finestra esplicita.
    # Legacy "<ts>" o contenuto corrotto: fallback conservativo al max()
    # (favorisce SEMPRE la conservazione del file generato).
    ts_str, sep, win_str = content.partition("|")
    try:
        ts = float(ts_str)
    except ValueError:
        try:
            ts = marker.stat().st_mtime
        except OSError:
            return False
    window = None
    if sep:
        try:
            window = int(win_str)
        except ValueError:
            window = None
    if window is None or window <= 0:
        window = max(
            _email_file_retention_sec(),
            _gemini_file_retention_sec() * _gemini_no_download_retention_multiplier(),
        )
    return (now - ts) < window + 300


def _forensic_marker_protects(work_dir, now):
    """True se il marker forense protegge la work_dir dal cleanup.
    Scritto da generation_engine al refund per job Gemini falliti; sopravvive
    a restart e blocca tutti i branch di cleanup finché now < retain_until.
    """
    marker = Path(work_dir) / FORENSIC_MARKER_FILENAME
    try:
        if not marker.exists():
            return False
    except OSError:
        return False
    try:
        with marker.open("r", encoding="utf-8") as f:
            data = json.load(f)
        retain_until = float(data.get("retain_until", 0) or 0)
    except (OSError, ValueError, TypeError):
        return False
    return now < retain_until


def _job_service_was_delivered(job_id):
    """True se il servizio pagato risulta EROGATO per questo job.

    Serve a distinguere un capture PayPal davvero orfano (denaro incassato, zero
    servizio → rimborso) da un capture rimasto `used=false` solo perché il
    mark-consume non è mai avvenuto su un job in realtà consegnato (falso
    positivo → nessun rimborso). Vedi incidente JM9_Vyd3UmB_J9GTfLNT7w.

    Segnali di consegna (uno basta):
      - status del job in done/translated/optimized
      - email di completamento inviata (`email_sent_at`)
      - traduzione prodotta (`translated_chapters`/`translated_lang`)
      - ottimizzazione AA completata (`ai_optimized`/`opt_completed_at`)
      - marker `.email_sent` finalizzato su disco (cross-restart, job già fuori memoria)
    """
    try:
        with _jobs_lock:
            job = _jobs().get(job_id)
            snap = dict(job) if isinstance(job, dict) else None
    except Exception:
        snap = None
    if snap:
        if snap.get("status") in ("done", "translated", "optimized"):
            return True
        if snap.get("email_sent_at"):
            return True
        if snap.get("translated_chapters") or snap.get("translated_lang"):
            return True
        if snap.get("ai_optimized") or snap.get("opt_completed_at"):
            return True
    # Cross-restart / job già rimosso dalla memoria: marker email finalizzato.
    try:
        marker = _upload_dir() / job_id / EMAIL_MARKER_FILENAME
        if marker.exists():
            content = marker.read_text(encoding="utf-8").strip()
            if content and content != _EMAIL_MARKER_PENDING:
                return True
    except Exception:
        pass
    return False


def _notify_duplicate_capture_refund(job_id, dup_refunds, reason=""):
    """Notifica l'admin che un job CONSEGNATO aveva capture PayPal duplicati
    (doppio addebito) ora rimborsati. Best-effort in thread daemon: l'SMTP non
    deve bloccare il chiamante (cleanup loop). Vedi incidente K1Rpn 2026-07."""
    def _notify():
        try:
            if not _admin_email() or not _smtp_available():
                return
            def _e(v):
                return html_mod.escape(str(v if v is not None else ""))
            rows = ""
            for r in dup_refunds:
                vc = r.get("voucher_code")
                refund_txt = (f"voucher <code>{_e(vc)}</code>" if vc
                              else "<strong>RIMBORSO MANUALE PayPal richiesto</strong>")
                rows += (
                    f"<tr><td><code>{_e(r.get('order_id'))}</code></td>"
                    f"<td>{r.get('amount_eur', 0):.2f} EUR</td>"
                    f"<td>{_e(r.get('email') or '—')}</td>"
                    f"<td>{refund_txt}</td></tr>"
                )
            body = (
                f"<h2>Doppio pagamento PayPal su job consegnato — rimborso duplicato</h2>"
                f"<p>Il job <code>{_e(job_id)}</code> (<em>{_e(reason)}</em>) risulta "
                f"<strong>erogato</strong> ma aveva piu' di un capture PayPal incassato. "
                f"Il servizio è coperto da un solo pagamento; i capture in eccesso "
                f"elencati sotto sono <strong>doppi addebiti</strong> e sono stati "
                f"rimborsati automaticamente.</p>"
                f"<table border='1' cellpadding='6' cellspacing='0'>"
                f"<tr><th>Order</th><th>Importo</th><th>Email</th><th>Rimborso</th></tr>"
                f"{rows}</table>"
                f"<p style='color:#888;font-size:12px'>Audiobook Maker — auto-refund "
                f"capture duplicato su job consegnato.</p>"
            )
            _send_email(_admin_email(),
                        f"[ABM] Rimborso doppio pagamento PayPal — {_e(job_id)}", body)
        except Exception as e:
            print(f"[cleanup] {job_id} admin notify (duplicate capture) failed: {e}")

    try:
        threading.Thread(target=_notify, daemon=True,
                         name=f"dup-capture-notify-{job_id}").start()
    except Exception:
        _notify()


def _reconcile_unused_capture_for_job(job_id, reason=""):
    """Riconcilia i capture PayPal incassati ma mai consumati legati al job.
    Invocata dalla cleanup PRIMA di distruggere il job.

    Due esiti distinti:
      - Servizio EROGATO (falso positivo): il capture è rimasto `used=false` solo
        perché il mark-consume non è avvenuto (es. divergenza di stima
        frontend/backend). Il denaro è dovuto → lo marchiamo consumato in
        silenzio, niente rimborso né alert.
      - Servizio NON erogato (orfano reale): payment.refund_unused_captures_for_job
        emette il voucher di rimborso (o segna `needs_manual_refund`); logghiamo
        e notifichiamo l'admin via email in un thread daemon (l'SMTP non deve
        bloccare il loop di cleanup).
    """
    # Guard falso-positivo: servizio già consegnato → settle silenzioso.
    if _job_service_was_delivered(job_id):
        try:
            settled = payment.settle_delivered_captures_for_job(job_id, reason=reason)
        except Exception as e:
            settled = []
            print(f"[cleanup] {job_id} settle delivered captures failed: {e}")
        dup_refunds = []
        for s in settled:
            if s.get("refunded_duplicate"):
                # Doppio addebito reale su job consegnato: rimborsato, non incassato.
                kind = "voucher" if s.get("voucher_code") else "MANUALE"
                dup_refunds.append(s)
                print(f"[cleanup] {job_id} delivered — DUPLICATE capture refunded "
                      f"({kind}): order={s.get('order_id')} amount={s.get('amount_eur'):.2f} "
                      f"email={s.get('email') or '-'} reason={reason}")
                try:
                    _log_activity(job_id, "", "REFUND_DUPLICATE_CAPTURE", "", "",
                                  f"order={s.get('order_id')} amount={s.get('amount_eur'):.2f} "
                                  f"{kind} voucher={s.get('voucher_code') or '-'}", "")
                except Exception:
                    pass
            else:
                print(f"[cleanup] {job_id} delivered — capture settled (no refund): "
                      f"order={s.get('order_id')} amount={s.get('amount_eur'):.2f} "
                      f"email={s.get('email') or '-'} reason={reason}")
                try:
                    _log_activity(job_id, "", "CAPTURE_SETTLED_DELIVERED", "", "",
                                  f"order={s.get('order_id')} amount={s.get('amount_eur'):.2f}", "")
                except Exception:
                    pass
        if dup_refunds:
            _notify_duplicate_capture_refund(job_id, dup_refunds, reason)
        return

    results = payment.refund_unused_captures_for_job(job_id, reason=reason)
    if not results:
        return
    for r in results:
        kind = "voucher" if r.get("voucher_code") else "MANUALE"
        print(f"[cleanup] {job_id} unused PayPal capture refunded "
              f"({kind}): order={r.get('order_id')} amount={r.get('amount_eur'):.2f} "
              f"email={r.get('email') or '-'} reason={reason}")
        try:
            _log_activity(job_id, "", "REFUND_UNUSED_CAPTURE", "", "",
                          f"order={r.get('order_id')} amount={r.get('amount_eur'):.2f} "
                          f"{kind} voucher={r.get('voucher_code') or '-'}", "")
        except Exception:
            pass

    def _notify():
        try:
            if not _admin_email() or not _smtp_available():
                return
            def _e(v):
                return html_mod.escape(str(v if v is not None else ""))
            rows = ""
            for r in results:
                vc = r.get("voucher_code")
                # vc/order_id/email sono potenzialmente attacker-influenced
                # (email = payer PayPal): escape di ogni valore interpolato.
                refund_txt = (f"voucher <code>{_e(vc)}</code>" if vc
                              else "<strong>RIMBORSO MANUALE PayPal richiesto</strong>")
                rows += (
                    f"<tr><td><code>{_e(r.get('order_id'))}</code></td>"
                    f"<td>{r.get('amount_eur', 0):.2f} EUR</td>"
                    f"<td>{_e(r.get('email') or '—')}</td>"
                    f"<td>{refund_txt}</td></tr>"
                )
            body = (
                f"<h2>Capture PayPal non consumato — job smaltito</h2>"
                f"<p>Il job <code>{_e(job_id)}</code> è stato rimosso (<em>{_e(reason)}</em>) "
                f"ma aveva pagamenti PayPal incassati e mai consumati "
                f"(il servizio <strong>non risulta erogato</strong>: nessun segnale di "
                f"consegna — completamento/email/download — è stato rilevato per il job).</p>"
                f"<table border='1' cellpadding='6' cellspacing='0'>"
                f"<tr><th>Order</th><th>Importo</th><th>Email</th><th>Rimborso</th></tr>"
                f"{rows}</table>"
                f"<p style='color:#888;font-size:12px'>Audiobook Maker — auto-reconcile "
                f"capture non consumati.</p>"
            )
            _send_email(_admin_email(), f"[ABM] Refund capture PayPal non consumato — {_e(job_id)}", body)
        except Exception as e:
            print(f"[cleanup] {job_id} admin notify (unused capture) failed: {e}")

    try:
        threading.Thread(target=_notify, daemon=True,
                         name=f"unused-capture-notify-{job_id}").start()
    except Exception:
        _notify()


def _cleanup_job(job_id, reason=""):
    """Remove all files for a job and delete the job entry.
    NOTA: nessun gate marker qui — questo path viene invocato solo dal branch
    per-status che opera su `_jobs()` locali con info complete (cancelled/error/
    done+retention-scaduta). La protezione cross-worker è nei branch orfani.

    Gate forense: se la work_dir contiene `.forensic_retain.json` valido
    (refund Gemini in attesa di analisi admin), rimuoviamo l'entry in memoria
    ma preserviamo la dir su disco finché il marker è valido.
    """
    # Riconciliazione pagamenti: se questo job ha capture PayPal incassati ma MAI
    # consumati (la traduzione/ottimizzazione non è mai partita), rimborsa prima
    # di distruggere il job — altrimenti il capture resta orfano in _payments.json
    # (cliente addebitato, zero servizio, zero rimborso). Best-effort, non-fatale:
    # NON deve mai impedire la pulizia.
    try:
        _reconcile_unused_capture_for_job(job_id, reason)
    except Exception as e:
        print(f"[cleanup] {job_id} unused-capture reconcile failed (non-fatal): {e}")

    with _jobs_lock:
        _prev = _jobs().pop(job_id, None)
    # Job tolto dalla memoria prima di un terminale (cancel riportato ad
    # "analyzed", heartbeat perso, ...): lo storico account non deve restare
    # "running" per sempre. settle_running non tocca esiti gia' scritti.
    if isinstance(_prev, dict) and _prev.get("status") not in _acct_settle_map():
        try:
            accounts.settle_running(
                job_id, "cancelled" if (_prev.get("cancelled")
                                        and not _prev.get("server_interrupted")) else "error")
        except Exception as e:  # noqa: BLE001
            print(f"[cleanup] {job_id} account settle failed (non-fatal): {e}")
    # Job mai partito (status analyzed): un descrittore di recovery ancora
    # aperto (register_email prima di un /api/generate poi rifiutato) farebbe
    # ripartire al boot un job che nessuno ha piu' — con voce premium, gratis.
    if isinstance(_prev, dict) and _prev.get("status") == "analyzed":
        try:
            pending_jobs.mark_failed(job_id)
        except Exception as e:
            print(f"[cleanup] {job_id} pending mark_failed failed (non-fatal): {e}")
    work_dir = _upload_dir() / job_id
    now = time.time()
    if work_dir.exists():
        if _forensic_marker_protects(work_dir, now):
            print(f"[cleanup] {job_id} entry removed but dir preserved "
                  f"(forensic retention) — {reason}")
            return                         # cold objects ALSO preserved
        # G4: NON distruggere locale+cold finché il marker email protegge la dir
        # o esiste un download token ancora valido. Evita che una transizione
        # anomala a error/cancel cancelli un job già consegnato via email.
        if _email_marker_protects(work_dir, now) or _tkstore.has_active_download_tokens(job_id, now):
            print(f"[cleanup] {job_id} entry removed but dir+cold preserved "
                  f"(email marker/token still valid) — {reason}")
            return
        _delete_cold_for_job(job_id)       # solo sul path che procede alla rimozione
        shutil.rmtree(str(work_dir), ignore_errors=True)
    else:
        # G5: dir già assente — cancella il cold SOLO se non resta alcun token
        # vivo. Il cold è il tier durevole: non va purgato finché un link email
        # è valido (anche se il locale è sparito).
        if not _tkstore.has_active_download_tokens(job_id, now):
            _delete_cold_for_job(job_id)
        else:
            print(f"[cleanup] {job_id} local gone but cold preserved "
                  f"(token still valid) — {reason}")
    print(f"[cleanup] {job_id} removed ({reason})")


def _cleanup_expired_shares(now=None):
    """Rimuove le share scadute (oltre ttl_sec); per le upload cancella anche il
    file su R2. Ritorna il numero di share rimosse."""
    now = now or time.time()
    removed = 0
    with _tkstore.share_lock:
        for stok in list(_tkstore.share_tokens.keys()):
            info = _tkstore.share_tokens.get(stok)
            if not isinstance(info, dict):
                _tkstore.share_tokens.pop(stok, None); removed += 1; continue
            if (now - info.get("created_at", 0)) <= info.get("ttl_sec", _share_ttl_sec()):
                continue
            if info.get("kind") in ("upload", "pending") and info.get("s3_key"):
                try:
                    storage_backend.delete_object(info["s3_key"])
                except Exception as e:
                    print(f"[share] cleanup delete failed {info.get('s3_key')}: {e}")
            _tkstore.share_tokens.pop(stok, None); removed += 1
    if removed:
        _tkstore.save_share_tokens()
    return removed


# Osservabilita' memoria: nessuna metrica RSS/swap veniva mai loggata, quindi
# la crescita monotona che ha portato al freeze del 2026-08-21 e' rimasta
# invisibile fino al blocco. Campionamento leggero da /proc (solo Linux), ogni
# MEM_LOG_INTERVAL_SEC, piu' un WARN quando la memoria disponibile scende sotto
# soglia o lo swap e' quasi pieno.
MEM_LOG_INTERVAL_SEC = env_int("ABM_MEM_LOG_INTERVAL_SEC", 300)
MEM_WARN_AVAIL_MB = env_int("ABM_MEM_WARN_AVAIL_MB", 300)
MEM_WARN_SWAP_PCT = env_int("ABM_MEM_WARN_SWAP_PCT", 80)
_last_mem_log = [0.0]


def _read_proc_kv(path):
    """Parsa un file /proc stile 'Chiave:  N kB' -> {chiave: N} (in kB)."""
    out = {}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                k, _, v = line.partition(":")
                v = v.strip().split(" ")[0]
                if v.isdigit():
                    out[k.strip()] = int(v)
    except OSError:
        return {}
    return out


def _log_memory_stats(now, force=False):
    """Logga RSS del processo + memoria/swap di sistema. No-op fuori da Linux."""
    if not force and (now - _last_mem_log[0]) < MEM_LOG_INTERVAL_SEC:
        return
    status = _read_proc_kv("/proc/self/status")
    if not status:
        _last_mem_log[0] = now      # non-Linux: non riprovare a ogni giro
        return
    _last_mem_log[0] = now
    meminfo = _read_proc_kv("/proc/meminfo")
    rss_mb = status.get("VmRSS", 0) / 1024.0
    avail_mb = meminfo.get("MemAvailable", 0) / 1024.0
    swap_total = meminfo.get("SwapTotal", 0)
    swap_used = swap_total - meminfo.get("SwapFree", 0)
    swap_pct = (swap_used * 100.0 / swap_total) if swap_total else 0.0
    with _jobs_lock:
        n_jobs = len(_jobs())
        n_gen = _active_generating_total_unlocked()
        n_spilled = sum(1 for j in _jobs().values() if j.get("_texts_spilled"))
    try:
        _asm = assembly_queue.stats()
        # "+5q(2p)": 5 in coda per l'assembly, di cui 2 PREMIUM (che passano
        # davanti). Serve a leggere dal log se la coda sta trattenendo job
        # pagati o solo gratuiti.
        _asm_prem = _asm.get("waiting_premium", 0)
        asm_part = (f" asm={_asm['held']}/{_asm['max']}+{_asm['waiting']}q"
                    + (f"({_asm_prem}p)" if _asm_prem else ""))
    except Exception:
        asm_part = ""
    line = (f"[mem] rss={rss_mb:.0f}MB avail={avail_mb:.0f}MB "
            f"swap={swap_pct:.0f}% jobs={n_jobs} (gen={n_gen}, spilled={n_spilled}) "
            f"threads={status.get('Threads', 0)}{asm_part}")
    if avail_mb < MEM_WARN_AVAIL_MB or swap_pct >= MEM_WARN_SWAP_PCT:
        print(f"[mem] WARN memoria in esaurimento — {line}")
        try:
            _log_activity("system", line, "MEMORY_PRESSURE")
        except Exception:
            pass
        load_metrics.incr("memp")
    else:
        print(line)


# ----------------------------------------------------------------------
# TELEMETRIA DI CARICO — campionatore
# ----------------------------------------------------------------------
# Heartbeat del cleanup loop: [epoch dell'ultimo giro completato]. L'eta' di
# questo valore e' il segnale che mancava quando il thread mori' silenziosamente
# (incidente 2026-06-15: 17h senza retention, disco al 100%).
_cleanup_heartbeat = [time.time()]
_cpu_prev = [None]          # (total, idle, iowait) della lettura precedente


def _cpu_percent():
    """(cpu%, iowait%) dal delta di /proc/stat. (None, None) fuori da Linux."""
    try:
        with open("/proc/stat", "r", encoding="utf-8") as fh:
            fields = fh.readline().split()
        if not fields or fields[0] != "cpu":
            return None, None
        vals = [int(v) for v in fields[1:11]]
    except (OSError, ValueError, IndexError):
        return None, None
    total = sum(vals)
    idle = vals[3] + vals[4]        # idle + iowait
    iowait = vals[4]
    prev = _cpu_prev[0]
    _cpu_prev[0] = (total, idle, iowait)
    if prev is None:
        return None, None           # serve un delta: il primo giro non conta
    d_total = total - prev[0]
    if d_total <= 0:
        return None, None
    d_idle = idle - prev[1]
    d_iow = iowait - prev[2]
    return (round(100.0 * (d_total - d_idle) / d_total, 1),
            round(100.0 * d_iow / d_total, 1))


def _collect_load_sample():
    """Gauge di un giro di campionamento, pronti per load_metrics.sample()."""
    g = {}
    with _jobs_lock:
        snapshot = list(_jobs().values())
    gen = gen_p = 0
    for j in snapshot:
        if j.get("status") == "generating":
            gen += 1
            try:
                if generation_engine.is_premium_job(j):
                    gen_p += 1
            except Exception:
                pass
    g["gen"] = gen
    g["gen_p"] = gen_p
    g["jobs"] = len(snapshot)
    try:
        asm = assembly_queue.stats()
        g["asm_h"] = asm["held"]
        g["asm_q"] = asm["waiting"]
        g["asm_qp"] = asm["waiting_premium"]
    except Exception:
        pass
    status = _read_proc_kv("/proc/self/status")
    if status:
        g["rss"] = round(status.get("VmRSS", 0) / 1024.0, 1)
        g["threads"] = status.get("Threads", 0)
    meminfo = _read_proc_kv("/proc/meminfo")
    if meminfo:
        total = meminfo.get("MemTotal", 0)
        if total:
            g["ram"] = round(100.0 * (total - meminfo.get("MemAvailable", 0)) / total, 1)
        swap_total = meminfo.get("SwapTotal", 0)
        if swap_total:
            g["swap"] = round(100.0 * (swap_total - meminfo.get("SwapFree", 0)) / swap_total, 1)
    cpu, iowait = _cpu_percent()
    if cpu is not None:
        g["cpu"] = cpu
        g["iowait"] = iowait
    try:
        load1 = os.getloadavg()[0]
        g["load"] = round(load1 / max(1, os.cpu_count() or 1), 2)
    except (OSError, AttributeError):
        pass
    try:
        usage = shutil.disk_usage(str(_upload_dir()))
        g["disk"] = round(100.0 * usage.used / usage.total, 1)
        g["disk_free_gb"] = round(usage.free / (1024 ** 3), 2)
    except Exception:
        pass
    g["hb"] = round(max(0.0, time.time() - _cleanup_heartbeat[0]), 1)
    # Worker RunPod di VoxCPM2 in `running`: vx_busy (0/1) mediato sui
    # campioni da' la quota di tempo con almeno un worker al lavoro, il dato
    # che dice quando conviene tenerne uno sempre attivo (niente avviamento a
    # freddo). Sonda fallita = gauge assente, non zero.
    if voxcpm_tts is not None:
        try:
            workers = voxcpm_tts.worker_health()
        except Exception:
            workers = None
        if workers is not None:
            running = max(0, int(workers.get("running", 0)))
            g["vx_run"] = running
            g["vx_busy"] = 1 if running > 0 else 0
    return g


def _assembly_metrics_observer(event, job_id, priority, waited, held):
    """Ponte fra la coda di assembly (modulo foglia) e la telemetria."""
    premium = priority >= assembly_queue.PRIORITY_PREMIUM
    if event == "timeout":
        load_metrics.observe("asm_wait", waited, premium=premium)
        load_metrics.incr("asm_timeout")
        return
    load_metrics.observe("asm_wait", waited, premium=premium)
    load_metrics.observe("enc", held)


def _load_metrics_sampler():
    """Campiona il carico ogni SAMPLE_SEC, scrive i bucket chiusi, fa retention.

    Thread PROPRIO e non un innesto nel _cleanup_loop: il cleanup fa lavoro
    pesante a cadenza variabile ed e' gia' morto una volta in produzione. Una
    telemetria che muore insieme al componente che deve sorvegliare non serve
    a niente.
    """
    last_purge = [0.0]
    while True:
        time.sleep(load_metrics.SAMPLE_SEC)
        try:
            load_metrics.sample(**_collect_load_sample())
            load_metrics.flush()
            now = time.time()
            if now - last_purge[0] > 86400:
                last_purge[0] = now
                load_metrics.purge()
                # Stessa cadenza per gli audit JSONL (costi 48 mesi, judge/leak/
                # code tagliate 6): ogni store registrato purga con la sua retention.
                gone = jsonl_audit.purge_all()
                if gone:
                    print("[audit-retention] rimossi: " + ", ".join(
                        f"{k} x{len(v)}" for k, v in sorted(gone.items())), flush=True)
        except Exception as e:
            print(f"[load-metrics] errore di campionamento (non fatale): {e}")


def _load_metrics_supervisor():
    """Mantiene vivo il campionatore, come _cleanup_supervisor fa col cleanup."""
    import traceback
    while True:
        try:
            _load_metrics_sampler()
        except Exception as e:
            traceback.print_exc()
            print(f"[load-metrics] sampler crashed, restarting: {type(e).__name__}: {e}")
            time.sleep(5)


MALLOC_TRIM_INTERVAL_SEC = env_int("ABM_MALLOC_TRIM_INTERVAL_SEC", 1800)
_last_malloc_trim = [0.0]
_libc_trim = []      # [] = non ancora risolto, [None] = non disponibile


def _malloc_trim(now, force=False):
    """Restituisce al sistema operativo l'heap glibc gia' libero.

    Ogni generazione tiene il testo del libro in RAM due volte (i capitoli di
    BookInfo e il piano dei chunk): un picco di alcuni MB per job che CPython
    libera regolarmente ma che glibc trattiene nell'heap del processo invece di
    restituirlo al kernel. Il risultato e' una RSS che cresce in modo monotono
    (~12 MB per job misurati in produzione il 21-23/08/2026) mentre i dati vivi
    restano pochi: i job spillati tengono in vita qualche decina di KB, non
    megabyte. malloc_trim(0) ricompatta le arene e restituisce le pagine libere.

    Complementare — non alternativo — a MALLOC_MMAP_THRESHOLD_/MALLOC_ARENA_MAX
    nell'unit systemd, che agiscono a monte impedendo che quelle pagine finiscano
    nell'heap non restituibile. No-op fuori da glibc (Windows, musl).
    """
    if not force and (now - _last_malloc_trim[0]) < MALLOC_TRIM_INTERVAL_SEC:
        return
    _last_malloc_trim[0] = now
    if not _libc_trim:
        fn = None
        if sys.platform.startswith("linux"):
            try:
                import ctypes
                fn = ctypes.CDLL("libc.so.6").malloc_trim
                fn.argtypes = [ctypes.c_size_t]
                fn.restype = ctypes.c_int
            except Exception as e:
                print(f"[mem] malloc_trim non disponibile ({e}): trim disattivato")
                fn = None
        _libc_trim.append(fn)
    fn = _libc_trim[0]
    if fn is None:
        return
    before = _read_proc_kv("/proc/self/status").get("VmRSS", 0) / 1024.0
    try:
        released = fn(0)
    except Exception as e:
        print(f"[mem] malloc_trim error (non-fatal): {e}")
        return
    after = _read_proc_kv("/proc/self/status").get("VmRSS", 0) / 1024.0
    print(f"[mem] malloc_trim: rss {before:.0f}MB -> {after:.0f}MB "
          f"(liberati {before - after:.0f}MB, released={released})")


def _cleanup_supervisor():
    """Mantiene vivo _cleanup_loop a ogni costo.

    Incidente 2026-06-15: il thread _cleanup_loop e' morto con
    `RuntimeError: dictionary changed size during iteration` (race con un
    mutatore non-lockato di _jobs()/_tkstore.download_tokens). Senza supervisione un
    `while True` che solleva un'eccezione termina il thread per SEMPRE: niente
    piu' hot-evict ne' retention-cleanup → il disco si e' riempito al 100% in
    ~17h. Qui ri-avviamo il loop su qualunque eccezione (la sleep iniziale del
    loop fa da backoff naturale), loggando lo stacktrace per diagnosi.
    """
    import traceback
    while True:
        try:
            _cleanup_loop()
        except Exception as e:
            traceback.print_exc()
            load_metrics.incr("cl_restart")
            print(f"[cleanup] loop crashed, restarting: {type(e).__name__}: {e}")
            time.sleep(5)


def _voice_clone_sweep_supervisor():
    """Sweep del ciclo di vita delle voci campionate, riavviato su crash
    come _cleanup_supervisor (incidente 2026-06-15). Ogni giro, e subito
    all'avvio, allinea anche lo specchio R2 di `user_voices/` (file mancanti
    caricati, voci finite cancellate): gira anche a feature spenta, perche' i
    campioni gia' registrati vanno replicati comunque."""
    import traceback
    while True:
        try:
            sync = voice_clone.sync_r2()
            if any(sync.values()):
                print(f"[voice_clone] sync R2: {sync}", flush=True)
            time.sleep(voice_clone.SWEEP_INTERVAL_SEC)
            if voxcpm_tts is None or not voice_clone.enabled():
                continue
            out = voice_clone.sweep()
            if any(out.values()):
                print(f"[voice_clone] sweep: {out}", flush=True)
        except Exception as e:      # noqa: BLE001
            traceback.print_exc()
            print(f"[voice_clone] sweep crashed, restarting: {type(e).__name__}: {e}", flush=True)
            time.sleep(60)


_ACCT_MAINT_FIRST_SEC = 300          # prima manutenzione 5 min dopo il boot
_ACCT_MAINT_INTERVAL_SEC = 6 * 3600  # poi ogni 6 ore
_ACCT_R2_PREFIX = "accounts/"
_ACCT_R2_KEEP = 14                   # copie giornaliere conservate su R2


def _account_maintenance_once(now=None):
    """Un giro di manutenzione dello stato account: purge di codici/sessioni
    scaduti e storico oltre retention, backup locale coerente di abm.db
    (API online di SQLite) e copia del giorno su R2 con rotazione.
    Ogni passo e' indipendente e best-effort."""
    out = {"purged": {}, "backup": None, "r2_key": None, "r2_pruned": 0}
    if not db.is_ready():
        return out
    try:
        out["purged"] = accounts.purge_expired(now=now)
    except Exception as e:  # noqa: BLE001
        print(f"[account] purge_expired failed: {e}", flush=True)
    bak = Path(_data_dir()) / (db.DB_FILENAME + ".bak")
    try:
        db.backup_to(bak)
        out["backup"] = str(bak)
    except Exception as e:  # noqa: BLE001
        print(f"[account] db backup failed: {e}", flush=True)
        return out
    try:
        if not storage_backend.is_enabled():
            return out
        day = time.strftime("%Y-%m-%d", time.gmtime(now if now is not None else time.time()))
        key = f"{_ACCT_R2_PREFIX}abm-{day}.db"
        storage_backend.upload_file(str(bak), key)
        out["r2_key"] = key
        keys = sorted(k for k in storage_backend.list_prefix(_ACCT_R2_PREFIX)
                      if k.endswith(".db"))
        for old in keys[:-_ACCT_R2_KEEP]:
            try:
                storage_backend.delete_object(old)
                out["r2_pruned"] += 1
            except Exception as e:  # noqa: BLE001
                print(f"[account] R2 prune {old} failed: {e}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[account] R2 backup failed (non-fatal): {e}", flush=True)
    return out


def _account_maintenance_supervisor():
    """Manutenzione periodica dello stato account, riavviata su crash come
    _cleanup_supervisor (incidente 2026-06-15)."""
    import traceback
    delay = _ACCT_MAINT_FIRST_SEC
    while True:
        try:
            time.sleep(delay)
            delay = _ACCT_MAINT_INTERVAL_SEC
            out = _account_maintenance_once()
            if any(out["purged"].values()) or out["r2_pruned"]:
                print(f"[account] maintenance: {out}", flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            print(f"[account] maintenance crashed, restarting: {type(e).__name__}: {e}", flush=True)
            delay = 60


def _cleanup_loop():
    """Background thread: periodically clean up finished/abandoned jobs."""
    while True:
        time.sleep(CLEANUP_INTERVAL_SEC)
        now = time.time()
        try:
            _log_memory_stats(now)
        except Exception as e:
            print(f"[mem] sampling error (non-fatal): {e}")
        _cleanup_expired_shares(now)

        # Multi-worker: absorb tokens created by other workers before deciding
        # what to delete. Without this, this worker's view of _tkstore.download_tokens
        # misses peers' tokens and the orphan-dir branch wipes their job dirs.
        _tkstore.merge_tokens_from_disk()

        with _jobs_lock:
            to_remove = []
            for jid, job in list(_jobs().items()):
                status = job.get("status", "")
                # Un job e' "emailato" se l'utente ha registrato l'email OPPURE
                # se una notifica e' comunque partita (path fallback post-COMPLETE
                # che imposta email_sent_at senza email_registered). Senza questo
                # OR, un job consegnato via email-fallback ricadeva nella regola
                # "downloaded + 5 min" e veniva cancellato pochi minuti dopo il
                # primo accesso, ignorando la retention 18h/48h.
                has_email = bool(job.get("email_registered")) or bool(job.get("email_sent_at"))

                if status == "cancelled":
                    # Non rimuovere job con download token ancora attivi
                    # (es. email inviata prima del cancel con link validi).
                    if not _tkstore.has_active_download_tokens(jid, now):
                        to_remove.append((jid, "cancelled"))
                    continue

                if status == "error":
                    start = job.get("start_time", now)
                    if (now - start) > 120:
                        to_remove.append((jid, "error"))
                    continue

                if status == "analyzed":
                    # Job ucciso dalla moderazione anti-abuso: la work_dir
                    # resta per il ripristino da console (ABM_ABUSE_KEEP_HOURS),
                    # poi via come un analyzed qualunque.
                    if _abuse_keep_state(job, now) is not None:
                        _decision = _abuse_cleanup_decision(
                            job, now, _tkstore.has_active_download_tokens(jid, now))
                        if _decision == "remove":
                            to_remove.append((jid, "abuse retention expired"))
                        continue
                    last_poll = job.get("last_poll", job.get("start_time", now))
                    if (now - last_poll) > CLEANUP_HEARTBEAT_TIMEOUT_SEC * 30:
                        # Non rimuovere job con download token ancora attivi
                        # (es. email inviata in generazione precedente).
                        if not _tkstore.has_active_download_tokens(jid, now):
                            to_remove.append((jid, "stale analyzed"))
                    continue

                if status == "optimizing":
                    if has_email:
                        continue
                    last_poll = job.get("last_poll", job.get("opt_start_time", now))
                    if (now - last_poll) > CLEANUP_HEARTBEAT_TIMEOUT_SEC:
                        job["opt_cancelled"] = True
                        to_remove.append((jid, f"heartbeat lost during optimization ({int(now - last_poll)}s)"))
                    continue

                if status == "optimized":
                    opt_done = job.get("opt_completed_at") or job.get("email_sent_at") or now
                    # Effective retention: per voci PREMIUM senza alcun download
                    # del .abm, raddoppia il timer.
                    _ret = _effective_retention_for_job(job)
                    if (now - opt_done) > _ret:
                        h = _ret // 3600
                        reason = ("optimization email retention expired" if has_email
                                  else f"optimized project retention expired ({h}h)")
                        to_remove.append((jid, reason))
                    continue

                if status == "translated":
                    # Senza questo ramo il job restava in `jobs` PER SEMPRE: i
                    # capitoli tradotti (fino a ~1.5M caratteri) non uscivano
                    # mai dalla RAM e la job dir veniva recuperata solo per via
                    # traversa dal ramo token-orphan. Stessa forma di
                    # "optimized": il token attivo comanda, quindi i file non
                    # spariscono prima di quanto succeda gia' oggi.
                    if _tkstore.has_active_download_tokens(jid, now):
                        continue
                    tr_done = job.get("translated_at") or job.get("email_sent_at") or now
                    _ret = _effective_retention_for_job(job)
                    if (now - tr_done) > _ret:
                        h = _ret // 3600
                        to_remove.append((jid, f"translation retention expired ({h}h)"))
                    continue

                if status == "generating":
                    if has_email:
                        continue
                    # Sintesi finita, job in coda per uno slot di assembly (o
                    # gia' sotto encode): il thread non aggiorna piu' nulla di
                    # visibile e le attese osservate arrivano a 10 minuti.
                    # Cancellare qui la job dir fa morire l'encode su ENOENT
                    # quando lo slot arriva, buttando via una sintesi completa.
                    if _assembly_purge_hold(job, now):
                        continue
                    last_poll = job.get("last_poll", job.get("start_time", now))
                    if (now - last_poll) > CLEANUP_HEARTBEAT_TIMEOUT_SEC:
                        job["cancelled"] = True
                        to_remove.append((jid, f"heartbeat lost during generation ({int(now - last_poll)}s)"))
                    continue

                if status == "done":
                    # Un download token attivo (job emailato, batch, o trasferito
                    # all'app via QR) governa la retention dei file: non rimuovere
                    # il job finché esiste un token valido, altrimenti si cancella
                    # un audiolibro ancora scaricabile (regressione transfer QR).
                    if _tkstore.has_active_download_tokens(jid, now):
                        continue
                    dl_at = job.get("downloaded_at")
                    email_sent_at = job.get("email_sent_at")
                    last_poll = job.get("last_poll", 0)

                    if has_email and email_sent_at:
                        # Effective retention: voci PREMIUM senza download → 2x.
                        if (now - email_sent_at) > _effective_retention_for_job(job):
                            to_remove.append((jid, f"email retention expired ({int(now - email_sent_at)}s)"))
                        continue

                    if has_email and not email_sent_at:
                        continue

                    if dl_at:
                        if (now - dl_at) > CLEANUP_GRACE_AFTER_DOWNLOAD_SEC:
                            to_remove.append((jid, f"downloaded {int(now - dl_at)}s ago"))
                        continue

                    if last_poll and (now - last_poll) > CLEANUP_HEARTBEAT_TIMEOUT_SEC:
                        to_remove.append((jid, f"abandoned (heartbeat lost {int(now - last_poll)}s)"))
                        continue

        # File I/O outside lock
        for jid, reason in to_remove:
            try:
                _cleanup_job(jid, reason)
            except Exception as e:
                print(f"[cleanup] error removing {jid}: {e}")

        #  -  -  Cleanup expired download tokens  -  -
        # Retention per-token: se il token e' marcato is_gemini (voce PREMIUM)
        # vale GEMINI_FILE_RETENTION_SEC, altrimenti EMAIL_FILE_RETENTION_SEC.
        # _effective_* raddoppia per voci PREMIUM mai scaricate (protezione costo).
        with _tkstore.tokens_lock:
            expired_tokens = [(t, info) for t, info in list(_tkstore.download_tokens.items())
                              if (now - info["created_at"]) > _effective_retention_for_token_info(info) + 300]
        for t, t_info in expired_tokens:
            with _tkstore.tokens_lock:
                _tkstore.download_tokens.pop(t, None)
            jid = t_info.get("job_id", "")
            with _jobs_lock:
                job_in_memory = jid in _jobs()
            if jid:
                job_dir = _upload_dir() / jid
                # Legacy: tokens created before the per-epoch refactor may have an
                # `output_archive_dir` field pointing to a manually-built archive.
                archive_rel = t_info.get("output_archive_dir", "")
                if archive_rel and job_dir.exists():
                    archive_path = job_dir / archive_rel
                    if archive_path.exists() and archive_path.is_dir():
                        shutil.rmtree(str(archive_path), ignore_errors=True)
                        print(f"[cleanup] Legacy archive removed (token expired): {archive_path}")
                if not job_in_memory and job_dir.exists():
                    if _email_marker_protects(job_dir, now):
                        continue
                    if _forensic_marker_protects(job_dir, now):
                        continue
                    # G5: un job può avere più token (es. audio + .abm). Abbiamo
                    # rimosso UNO scaduto, ma se un fratello è ancora valido NON
                    # distruggere dir + cold.
                    if _tkstore.has_active_download_tokens(jid, now):
                        continue
                    _delete_cold_for_job(jid)
                    shutil.rmtree(str(job_dir), ignore_errors=True)
                    print(f"[cleanup] Token-orphan dir removed: {jid}")
        if expired_tokens:
            # _tkstore.save_tokens() acquires _tkstore.tokens_lock internally; wrapping it here
            # would deadlock on the non-reentrant lock and freeze every later
            # caller (including the post-COMPLETE email notification).
            _tkstore.save_tokens()

        #  -  -  Cleanup orphan per-epoch output dirs  -  -
        # An output_{epoch}/ directory is removable when:
        # - It is NOT the current output_dir of the job (if job is alive)
        # - AND it is not referenced by any active token's output_zip/output_file/output_m4b
        # - AND its mtime is older than the retention window
        with _jobs_lock:
            current_output_dirs = {_jobs()[j].get("output_dir", ""): j for j in list(_jobs())}
        with _tkstore.tokens_lock:
            referenced_paths = set()
            for info in list(_tkstore.download_tokens.values()):
                # translated_path/optimized_abm_path/kit M4B: anche questi sono
                # l'UNICO output referenziato da un token (traduzione, .abm,
                # ripiego M4B). Senza di loro la relativa output_<epoch> risulta
                # orfana e cancellabile pur avendo un token valido.
                for key in ("output_zip", "output_file", "output_m4b",
                            "output_m4b_fallback_zip", "optimized_abm_path",
                            "translated_path"):
                    p = info.get(key) or ""
                    if p:
                        try:
                            referenced_paths.add(str(Path(p).parent.resolve()))
                        except OSError:
                            pass
        try:
            for jdir in _upload_dir().iterdir():
                if not _is_job_dir(jdir):
                    continue
                for od in jdir.iterdir():
                    if not od.is_dir():
                        continue
                    if not (od.name == "output" or od.name.startswith("output_")):
                        continue
                    try:
                        od_resolved = str(od.resolve())
                    except OSError:
                        continue
                    if od_resolved in current_output_dirs:
                        continue
                    if od_resolved in referenced_paths:
                        continue
                    try:
                        age = now - od.stat().st_mtime
                    except OSError:
                        continue
                    # Senza contesto-job, usiamo la retention piu' lunga (Gemini)
                    # moltiplicata per il fattore no-download: la dir orfana puo'
                    # appartenere a un job PREMIUM mai scaricato.
                    if age > max(
                        _email_file_retention_sec(),
                        _gemini_file_retention_sec() * _gemini_no_download_retention_multiplier(),
                    ):
                        if _email_marker_protects(od.parent, now):
                            continue
                        if _forensic_marker_protects(od.parent, now):
                            continue
                        shutil.rmtree(str(od), ignore_errors=True)
                        print(f"[cleanup] Orphan output dir removed: {od} (age: {int(age)}s)")
        except OSError:
            pass

        #  -  -  Riconciliazione offload cold (ri-tenta upload mancati/no-op)  -  -
        # PRIMA dell'eviction: garantisce che la copia cold esista (e il marker
        # sia scritto) prima di valutare la rimozione del locale. L'eviction non
        # toccherà comunque i file appena caricati (sono dentro la finestra calda).
        try:
            _reconcile_cold_offload()
        except Exception as e:
            print(f"[reconcile] loop error: {e}")

        #  -  -  Evacuazione finestra calda (hot -> cold)  -  -
        try:
            _evict_hot_local()
        except Exception as e:
            print(f"[hot-evict] loop error: {e}")

        #  -  -  Cleanup cartelle orfane su disco  -  -
        with _jobs_lock:
            _known_job_ids = set(_jobs().keys())
        with _tkstore.tokens_lock:
            _known_token_jobs = set(info.get("job_id", "") for info in list(_tkstore.download_tokens.values()))
        _all_known = _known_job_ids | _known_token_jobs
        try:
            for entry in _upload_dir().iterdir():
                if not _is_job_dir(entry):
                    continue
                if entry.name in _all_known:
                    continue
                try:
                    dir_age = now - entry.stat().st_mtime
                except OSError:
                    continue
                if dir_age > CLEANUP_ORPHAN_DIR_AGE_SEC:
                    if _email_marker_protects(entry, now):
                        continue
                    if _forensic_marker_protects(entry, now):
                        continue
                    _delete_cold_for_job(entry.name)
                    shutil.rmtree(str(entry), ignore_errors=True)
                    print(f"[cleanup] Orphan dir removed: {entry.name} (age: {int(dir_age)}s)")
        except OSError:
            pass

        # Flush pending admin digest (rate-limited: max 1/hour)
        _try_send_admin_digest()

        # Il digest quotidiano VoxCPM: decide da se' se c'e' un giorno
        # arretrato da riepilogare, e nella grande maggioranza dei giri non
        # fa nulla.
        _try_send_voxcpm_digest()

        # Ultimo passo del ciclo: restituisce al SO l'heap liberato dalla purga
        # appena fatta (rate-limited a MALLOC_TRIM_INTERVAL_SEC).
        try:
            _malloc_trim(time.time())
        except Exception as e:
            print(f"[mem] malloc_trim skipped (non-fatal): {e}")

        # Heartbeat: il giro e' arrivato in fondo. L'eta' di questo timestamp
        # e' cio' che il campionatore pubblica come metrica "hb": un cleanup
        # morto diventa visibile in pochi minuti invece che in 17 ore.
        _cleanup_heartbeat[0] = time.time()
