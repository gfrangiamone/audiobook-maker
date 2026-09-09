"""voxcpm_ranking.py — la classifica delle voci VoxCPM, fatta dall'uso.

Ogni volta che una voce VoxCPM viene usata davvero — la generazione parte,
pagamento o quota gia' passati — la voce guadagna un punto. I punti si
tengono per voce E per mese, non come somma sola: l'ordine del catalogo
segue il mese in corso, e a pari punti nel mese vince chi ne ha di piu' in
assoluto. Cosi' una voce nuova non resta per sempre sotto a chi ha
accumulato prima di lei, e la storia decide solo i pareggi.

Struttura del file:
    {"mesi": {"YYYY-MM": {"voxcpm:v2:it-IT/Matteo": 3, ...}, ...},
     "jobs": {"<job_id>": "YYYY-MM", ...}}

`mesi` non si pota mai (e' il totale assoluto). `jobs` serve
all'idempotenza — un job conta una volta sola anche se il recovery lo
rilancia — e si pota ai due mesi piu' recenti. Nessun dato personale.

Best-effort, thread-safe, scrittura atomica: nessuna eccezione propagata.
La cache in memoria e' corretta perche' la produzione gira a processo
singolo (vedi project_deploy_reality); un file modificato a mano richiede
`invalidate_cache()` o un riavvio.
"""
import json
import os
import threading
from datetime import datetime
from pathlib import Path

from community_store import atomic_write_json
from voice_utils import is_voxcpm_voice

_lock = threading.RLock()
_cache = None  # dict | None
_KEEP_JOB_MONTHS = 2


def _file():
    # Letto a ogni chiamata: ABM_DATA_DIR e' definito all'avvio del processo,
    # ma i test lo cambiano per isolare lo stato.
    return Path(os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data")) \
        / "_voxcpm_voice_points.json"


def _month():
    return datetime.now().strftime("%Y-%m")


def invalidate_cache():
    global _cache
    with _lock:
        _cache = None


def _load():
    """Il file, riparato dove lo schema non torna. Chiamare sotto `_lock`."""
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    if not isinstance(d.get("mesi"), dict):
        d["mesi"] = {}
    if not isinstance(d.get("jobs"), dict):
        d["jobs"] = {}
    _cache = d
    return d


def punto(voice_id, job_id):
    """Un punto alla voce, per questo job. Idempotente sul job.

    Ritorna i punti della voce nel mese dopo l'operazione, 0 se la voce non
    e' VoxCPM o qualcosa e' andato storto: chi chiama non deve mai fermarsi
    per la classifica.
    """
    vid = (voice_id or "").strip()
    jid = (job_id or "").strip()
    if not is_voxcpm_voice(vid):
        return 0
    try:
        with _lock:
            d = _load()
            month = _month()
            if jid and jid in d["jobs"]:
                bucket = d["mesi"].get(d["jobs"][jid]) or {}
                return int(bucket.get(vid, 0) or 0)
            bucket = d["mesi"].setdefault(month, {})
            if not isinstance(bucket, dict):
                bucket = d["mesi"][month] = {}
            try:
                n = int(bucket.get(vid, 0) or 0) + 1
            except (TypeError, ValueError):
                n = 1
            bucket[vid] = n
            if jid:
                d["jobs"][jid] = month
                mesi_vivi = sorted(set(d["jobs"].values()))[-_KEEP_JOB_MONTHS:]
                d["jobs"] = {j: m for j, m in d["jobs"].items()
                             if m in mesi_vivi}
            try:
                atomic_write_json(_file(), d)
            except Exception:
                pass
            return n
    except Exception:
        return 0


def punti(voice_id):
    """(punti del mese, punti in assoluto) della voce."""
    vid = (voice_id or "").strip()
    try:
        with _lock:
            d = _load()
            month = _month()
            mese = 0
            totale = 0
            for m, bucket in d["mesi"].items():
                if not isinstance(bucket, dict):
                    continue
                try:
                    n = int(bucket.get(vid, 0) or 0)
                except (TypeError, ValueError):
                    n = 0
                totale += n
                if m == month:
                    mese = n
            return mese, totale
    except Exception:
        return 0, 0


def chiave(entry):
    """La chiave d'ordine di una voce nel catalogo.

    Prima il blocco (Female prima di Male, com'era), poi i punti del mese,
    poi i punti assoluti, poi il nome. Le voci degli altri motori hanno
    sempre zero punti, quindi fra loro restano in ordine di nome: la
    classifica tocca solo VoxCPM.
    """
    vid = entry.get("id", "")
    mese, totale = punti(vid) if is_voxcpm_voice(vid) else (0, 0)
    return (entry.get("gender", ""), -mese, -totale, entry.get("name", ""))


def ordina(languages):
    """Riordina sul posto le voci di ogni lingua del catalogo unito.

    `languages` e' la forma di `_fetch_voices`: {codice: {"voices": [...]}}
    piu' eventuali chiavi di servizio che iniziano con `_`, che si saltano.
    """
    if not isinstance(languages, dict):
        return languages
    for code, lang in languages.items():
        if str(code).startswith("_") or not isinstance(lang, dict):
            continue
        voci = lang.get("voices")
        if isinstance(voci, list):
            voci.sort(key=chiave)
    return languages


def classifica():
    """Tutte le voci con punti, {voice_id: {"mese": n, "totale": n}}."""
    try:
        with _lock:
            d = _load()
            month = _month()
            out = {}
            for m, bucket in d["mesi"].items():
                if not isinstance(bucket, dict):
                    continue
                for vid, n in bucket.items():
                    try:
                        n = int(n or 0)
                    except (TypeError, ValueError):
                        continue
                    rec = out.setdefault(vid, {"mese": 0, "totale": 0})
                    rec["totale"] += n
                    if m == month:
                        rec["mese"] += n
            return out
    except Exception:
        return {}
