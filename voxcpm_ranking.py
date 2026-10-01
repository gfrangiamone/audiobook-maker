"""voxcpm_ranking.py — la classifica delle voci VoxCPM, fatta dall'uso.

Ogni volta che una voce VoxCPM viene usata davvero — la generazione parte,
pagamento o quota gia' passati — la voce guadagna un punto. I punti si
tengono per voce E per giorno, non come somma sola: l'ordine del catalogo
segue gli ultimi 30 giorni (oggi compreso), e a pari punti nella finestra
vince chi ne ha di piu' in assoluto. Cosi' una voce nuova non resta per
sempre sotto a chi ha accumulato prima di lei, e la storia decide solo i
pareggi. La finestra e' mobile e non il mese di calendario: col mese, il
primo del mese azzerava tutti e i primi job decidevano l'ordine.

Struttura del file:
    {"mesi":   {"YYYY-MM": {"voxcpm:v2:it-IT/Matteo": 3, ...}, ...},
     "giorni": {"YYYY-MM-DD": {"voxcpm:v2:it-IT/Matteo": 1, ...}, ...},
     "jobs":   {"<job_id>": "YYYY-MM-DD", ...}}

`mesi` non si pota mai (e' il totale assoluto). `giorni` e' la finestra e
si pota ai 30 giorni. `jobs` serve all'idempotenza — un job conta una volta
sola anche se il recovery lo rilancia — e si pota ai 60 giorni; i job
scritti prima della finestra mobile hanno il mese al posto del giorno.
Nessun dato personale.

Al primo caricamento di un file senza `giorni` la finestra si ricostruisce
dalle GENERATE del business log (activity.db) dei job gia' contati: senza,
per 30 giorni l'ordine sarebbe deciso dal solo totale.

Best-effort, thread-safe, scrittura atomica: nessuna eccezione propagata.
La cache in memoria e' corretta perche' la produzione gira a processo
singolo (vedi project_deploy_reality); un file modificato a mano richiede
`invalidate_cache()` o un riavvio.
"""
import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

from community_store import atomic_write_json
from voice_utils import is_voxcpm_voice

_lock = threading.RLock()
_cache = None  # dict | None
_FINESTRA_GIORNI = 30
_KEEP_JOB_GIORNI = 60


def _file():
    # Letto a ogni chiamata: ABM_DATA_DIR e' definito all'avvio del processo,
    # ma i test lo cambiano per isolare lo stato.
    return Path(os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data")) \
        / "_voxcpm_voice_points.json"


def _now():
    return datetime.now()


def _month():
    return _now().strftime("%Y-%m")


def _giorno():
    return _now().strftime("%Y-%m-%d")


def _giorni_fa(n):
    return (_now() - timedelta(days=n)).strftime("%Y-%m-%d")


def _inizio_finestra():
    """Il primo giorno della finestra: oggi e i 29 giorni prima."""
    return _giorni_fa(_FINESTRA_GIORNI - 1)


def invalidate_cache():
    global _cache
    with _lock:
        _cache = None


def _righe_generate():
    """(job_id, voce, primo ts) delle GENERATE nel business log.

    Vuota se il backend DB e' spento o illeggibile: la finestra parte allora
    da zero e si riempie coi job nuovi."""
    try:
        import activity_db
        import activity_log
        if activity_log.mode() == "off":
            return []
        conn = activity_db.reader(activity_log.db_path())
        try:
            return conn.execute(
                "SELECT job_id, voice, MIN(ts) FROM events "
                "WHERE op = 'GENERATE' AND job_id <> '' GROUP BY job_id"
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []


def _semina_giorni(jobs):
    """La finestra ricostruita dai job gia' contati, per giorno di partenza."""
    inizio = _inizio_finestra()
    giorni = {}
    for jid, vid, ts in _righe_generate():
        day = str(ts or "")[:10]
        if jid not in jobs or day < inizio or not is_voxcpm_voice(vid):
            continue
        bucket = giorni.setdefault(day, {})
        bucket[vid] = bucket.get(vid, 0) + 1
    return giorni


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
    if "giorni" not in d:
        d["giorni"] = _semina_giorni(d["jobs"])
    elif not isinstance(d["giorni"], dict):
        d["giorni"] = {}
    _cache = d
    return d


def _somma(buckets, vid, dal=None):
    """I punti di `vid` nei bucket, solo da `dal` in poi se dato."""
    tot = 0
    for k, bucket in buckets.items():
        if dal is not None and k < dal:
            continue
        if not isinstance(bucket, dict):
            continue
        try:
            tot += int(bucket.get(vid, 0) or 0)
        except (TypeError, ValueError):
            pass
    return tot


def _incrementa(buckets, key, vid):
    bucket = buckets.get(key)
    if not isinstance(bucket, dict):
        bucket = buckets[key] = {}
    try:
        bucket[vid] = int(bucket.get(vid, 0) or 0) + 1
    except (TypeError, ValueError):
        bucket[vid] = 1


def punto(voice_id, job_id):
    """Un punto alla voce, per questo job. Idempotente sul job.

    Ritorna i punti della voce negli ultimi 30 giorni dopo l'operazione, 0
    se la voce non e' VoxCPM o qualcosa e' andato storto: chi chiama non
    deve mai fermarsi per la classifica.
    """
    vid = (voice_id or "").strip()
    jid = (job_id or "").strip()
    if not is_voxcpm_voice(vid):
        return 0
    try:
        with _lock:
            d = _load()
            inizio = _inizio_finestra()
            if jid and jid in d["jobs"]:
                return _somma(d["giorni"], vid, inizio)
            _incrementa(d["mesi"], _month(), vid)
            _incrementa(d["giorni"], _giorno(), vid)
            d["giorni"] = {k: b for k, b in d["giorni"].items() if k >= inizio}
            if jid:
                d["jobs"][jid] = _giorno()
                # Un valore "YYYY-MM" (job di prima della finestra mobile) si
                # confronta col mese del taglio: resta finche' il suo mese e'
                # dentro i 60 giorni.
                taglio = _giorni_fa(_KEEP_JOB_GIORNI)
                d["jobs"] = {j: k for j, k in d["jobs"].items()
                             if str(k) >= taglio[:len(str(k))]}
            try:
                atomic_write_json(_file(), d)
            except Exception:
                pass
            return _somma(d["giorni"], vid, inizio)
    except Exception:
        return 0


def punti(voice_id):
    """(punti degli ultimi 30 giorni, punti in assoluto) della voce."""
    vid = (voice_id or "").strip()
    try:
        with _lock:
            d = _load()
            return (_somma(d["giorni"], vid, _inizio_finestra()),
                    _somma(d["mesi"], vid))
    except Exception:
        return 0, 0


def chiave(entry):
    """La chiave d'ordine di una voce nel catalogo.

    Prima il blocco (Female prima di Male, com'era), poi i punti degli
    ultimi 30 giorni, poi i punti assoluti, poi il nome. Le voci degli altri
    motori hanno sempre zero punti, quindi fra loro restano in ordine di
    nome: la classifica tocca solo VoxCPM.
    """
    vid = entry.get("id", "")
    recenti, totale = punti(vid) if is_voxcpm_voice(vid) else (0, 0)
    return (entry.get("gender", ""), -recenti, -totale, entry.get("name", ""))


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
    """Tutte le voci con punti, {voice_id: {"finestra": n, "totale": n}}."""
    try:
        with _lock:
            d = _load()
            inizio = _inizio_finestra()
            out = {}
            for nome, dal in (("totale", None), ("finestra", inizio)):
                for k, bucket in d["mesi" if nome == "totale" else "giorni"].items():
                    if (dal is not None and k < dal) or not isinstance(bucket, dict):
                        continue
                    for vid, n in bucket.items():
                        try:
                            n = int(n or 0)
                        except (TypeError, ValueError):
                            continue
                        rec = out.setdefault(vid, {"finestra": 0, "totale": 0})
                        rec[nome] += n
            return out
    except Exception:
        return {}
