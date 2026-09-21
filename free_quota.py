"""free_quota.py — Quota gratuita cumulativa per client sui TTS premium.

Struttura del file: {"YYYY-MM": {"<client_id>": {"eur": 1.37, "jobs": {"<chiave>": 0.29}}}}
La chiave di addebito e' `charge_key()`: job_id + impronta di voce e capitoli,
cioe' UNA generazione. Prima del 21/09/2026 era il solo job_id, e un libro da
5 EUR e' stato letto gratis un capitolo per volta sullo stesso job (53
generazioni via reset_to_chapters): dal secondo capitolo l'idempotenza per
job vedeva il job "gia' addebitato" e la quota non si muoveva piu'.
Nessun dato personale oltre al client_id (cookie anonimo abm_cid).
Best-effort, thread-safe, scrittura atomica: nessuna eccezione propagata.
"""
import hashlib
import json
import os
import threading
from datetime import datetime
from pathlib import Path

from community_store import atomic_write_json
from voice_utils import is_speechify_voice, is_voxcpm_voice

_lock = threading.RLock()
_KEEP_MONTHS = 3
_ANON = "_anon"


def _quota_file():
    # Letto a ogni chiamata: ABM_DATA_DIR e' definito all'avvio del processo,
    # ma i test lo cambiano per isolare lo stato.
    return Path(os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data")) / "_free_quota.json"


def _month():
    return datetime.now().strftime("%Y-%m")


def _env_float(name, default):
    try:
        return float(str(os.environ.get(name, default)).replace(",", "."))
    except (TypeError, ValueError):
        return float(default)


def limit_eur():
    """Quota gratuita mensile per client. 0 = feature disattivata."""
    return _env_float("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")


def _norm_client(client_id):
    return (client_id or "").strip() or _ANON


def _load():
    try:
        with open(_quota_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def used_eur(client_id):
    """Valore di listino gia' regalato al client nel mese corrente."""
    with _lock:
        d = _load()
    month = _month()
    # Valida schema: mese deve mappare a dict
    month_data = d.get(month)
    if not isinstance(month_data, dict):
        return 0.0
    bucket = month_data.get(_norm_client(client_id)) or {}
    # Valida schema: client deve mappare a dict
    if not isinstance(bucket, dict):
        return 0.0
    try:
        return float(bucket.get("eur", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def consume(client_id, eur, job_id):
    """Somma `eur` al bucket del mese. Idempotente per `job_id`.

    Ritorna il totale del mese dopo l'operazione.
    """
    cid = _norm_client(client_id)
    jid = (job_id or "").strip()
    try:
        amount = max(0.0, float(eur or 0.0))
    except (TypeError, ValueError):
        amount = 0.0
    with _lock:
        d = _load()
        month = _month()
        # Ripara schema corrotto: mese deve essere dict
        if not isinstance(d.get(month), dict):
            d[month] = {}
        # Ripara schema corrotto: client deve essere dict
        month_bucket = d[month]
        if not isinstance(month_bucket.get(cid), dict):
            month_bucket[cid] = {"eur": 0.0, "jobs": {}}
        bucket = month_bucket[cid]
        # Ripara schema corrotto: jobs deve essere dict
        if not isinstance(bucket.get("jobs"), dict):
            bucket["jobs"] = {}
        jobs = bucket["jobs"]
        try:
            current = float(bucket.get("eur", 0.0) or 0.0)
        except (TypeError, ValueError):
            current = 0.0
        if jid and jid in jobs:
            return current
        current = round(current + amount, 4)
        bucket["eur"] = current
        if jid:
            jobs[jid] = round(amount, 4)
        for old in sorted(d.keys())[:-_KEEP_MONTHS]:
            d.pop(old, None)
        try:
            atomic_write_json(_quota_file(), d)
        except Exception:
            pass
        return current


def charge_key(job_id, voice_id, chapter_indexes=None):
    """Chiave di addebito di UNA generazione: job + voce + capitoli.

    L'idempotenza di `decision()`/`consume()` (I1) serve al retry della stessa
    generazione, non a rileggere lo stesso job con altri capitoli o un'altra
    voce: quelle sono sintesi nuove che il fornitore fattura di nuovo.
    `chapter_indexes` vuoto/None = libro intero (il chiamante normalizza una
    selezione esplicita di tutti i capitoli a None, cosi' "tutti" ha una sola
    grafia). Senza voce ne' capitoli la chiave resta il job_id nudo, com'era
    nei record scritti prima del 21/09/2026.
    """
    jid = (job_id or "").strip()
    voice = (voice_id or "").strip()
    idx = sorted({int(i) for i in (chapter_indexes or []) if i is not None})
    if not voice and not idx:
        return jid
    sig = f"{voice}|{','.join(str(i) for i in idx) or 'all'}"
    return f"{jid}:{hashlib.sha1(sig.encode('utf-8')).hexdigest()[:12]}"


def job_charged(client_id, job_id):
    """True se `job_id` (chiave di `charge_key()`) ha gia' consumato quota per
    questo client nel mese.

    Serve all'idempotenza per job di `decision()`: al retry della stessa
    generazione il contributo del job e' gia' dentro `used_eur`, quindi
    ricalcolare `used + list` produrrebbe un 402 che chiede denaro per un
    credito gia' speso.
    """
    jid = (job_id or "").strip()
    if not jid:
        return False
    with _lock:
        d = _load()
    month_data = d.get(_month())
    if not isinstance(month_data, dict):
        return False
    bucket = month_data.get(_norm_client(client_id))
    if not isinstance(bucket, dict):
        return False
    jobs = bucket.get("jobs")
    return isinstance(jobs, dict) and jid in jobs


def snapshot(client_id):
    """Stato quota per UI/admin."""
    lim = limit_eur()
    used = used_eur(client_id)
    return {
        "used_eur": round(used, 2),
        "limit_eur": round(lim, 2),
        "remaining_eur": round(max(0.0, lim - used), 2),
        "exhausted": bool(lim > 0 and used >= lim),
    }


def _premium_threshold_eur(voice_id):
    """Soglia sotto la quale il job premium e' gratuito, per motore."""
    if is_voxcpm_voice(voice_id):
        return _env_float("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.50")
    if is_speechify_voice(voice_id):
        return _env_float("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "0.50")
    return _env_float("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.50")


def _premium_floor_eur(voice_id):
    """Importo minimo fatturato quando la quota non copre, per motore.

    Gemini e Speechify restano sulla costante storica `ABM_PREMIUM_MIN_COST_EUR`:
    scorporare la lettura dal corpo di `decision()` non cambia il loro prezzo.
    VoxCPM ha la sua perche' il suo costo non sta nei caratteri ma
    nell'accensione del worker (§8.3), e il minimo esiste proprio per quello.
    """
    if is_voxcpm_voice(voice_id):
        return _env_float("ABM_VOXCPM_MIN_COST_EUR", "0.50")
    return _env_float("ABM_PREMIUM_MIN_COST_EUR", "0.50")


def _premium_free_max_chars(voice_id):
    """Cap di caratteri del LIBRO (non della selezione) oltre il quale la voce
    non e' mai gratuita, per motore. 0 = nessun cap.

    Solo VoxCPM: il worker GPU costa per accensione e un libro grande letto a
    pezzi (un capitolo per generazione, ognuno sotto soglia) resta un libro
    grande. Il cap guarda il testo intero del job, cosi' la selezione dei
    capitoli non lo aggira.
    """
    if is_voxcpm_voice(voice_id):
        try:
            return max(0, int(float(os.environ.get("ABM_VOXCPM_FREE_MAX_CHARS", "100000"))))
        except (TypeError, ValueError):
            return 100000
    return 0


def decision(client_id, voice_id, list_total_eur, job_id=None, book_chars=None):
    """Prezzo dovuto per un job premium, applicando la quota gratuita.

    `list_total_eur` e' il prezzo di LISTINO (TTS premium + eventuale quota LLM
    combinata), cioe' prima dell'azzeramento sotto soglia. Non consuma nulla:
    il consumo e' esplicito via `consume()` dove il job parte davvero.

    `job_id` (opzionale, in coda per retrocompatibilita' della firma) e' la
    chiave di `charge_key()` e rende la decisione idempotente per generazione:
    se quella generazione ha gia' addebitato quota in questo mese, il suo
    retry resta gratuito.

    `book_chars` (opzionale) e' il numero di caratteri del libro INTERO: sopra
    `_premium_free_max_chars(voice_id)` la voce non e' gratuita neanche sotto
    soglia (`free_cap_exceeded`), e si paga il floor.
    """
    try:
        list_total = round(float(list_total_eur or 0.0), 2)
    except (TypeError, ValueError):
        list_total = 0.0
    threshold = _premium_threshold_eur(voice_id)
    limit = limit_eur()
    used = used_eur(client_id) if limit > 0 else 0.0
    out = {
        "due_eur": list_total,
        "is_free": False,
        "quota_exhausted": False,
        "quota_used_eur": round(used, 2),
        "quota_limit_eur": round(limit, 2),
        "threshold_eur": threshold,
        "list_total_eur": list_total,
    }
    if list_total > threshold:
        # Job gia' a pagamento: la quota non c'entra, percorso invariato.
        return out
    cap = _premium_free_max_chars(voice_id)
    try:
        book = int(book_chars or 0)
    except (TypeError, ValueError):
        book = 0
    if cap > 0 and book > cap:
        # Libro troppo grande per la gratuita' di questo motore: non importa
        # quanto sia piccola la selezione di oggi. Viene prima dell'idempotenza
        # per generazione: una generazione a pagamento non ha mai addebitato
        # quota, quindi non c'e' nulla da riconoscere.
        out["free_cap_exceeded"] = True
        out["free_cap_chars"] = cap
        out["book_chars"] = book
        out["due_eur"] = round(max(list_total, _premium_floor_eur(voice_id)), 2)
        return out
    if job_id and limit > 0 and job_charged(client_id, job_id):
        # Retry della stessa generazione (btnRetryWiz, reload di pagina, app
        # mobile): il credito di questa generazione e' gia' stato speso e
        # `used_eur` lo contiene gia'. Senza questa uscita il confronto
        # `used + list` lo conterebbe due volte e produrrebbe un 402 che chiede
        # il floor per un lavoro gia' pagato in quota. `consume()` e' a sua
        # volta idempotente per chiave, quindi non si addebita nulla. La chiave
        # e' per generazione (voce + capitoli, vedi charge_key): un capitolo
        # diverso o un'altra voce NON passano di qui.
        out["due_eur"] = 0.0
        out["is_free"] = True
        return out
    if limit <= 0 or round(used + list_total, 4) <= limit:
        out["due_eur"] = 0.0
        out["is_free"] = True
        return out
    floor = _premium_floor_eur(voice_id)
    out["due_eur"] = round(max(list_total, floor), 2)
    out["quota_exhausted"] = True
    return out
