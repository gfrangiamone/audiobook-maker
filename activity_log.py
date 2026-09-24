"""Business log mensile delle attivita' (modulo foglia, sola stdlib).

Unico punto di accesso a `activity_YYYY-MM.log`: scrittura con dedup,
parsing, letture per mese o per intervallo. Formato su disco:

    <job_id> # <ts> # "<file>" # <op> # <cid> # <ip> # <voice> # <lang> # <platform>

Fase 1 di docs/superpowers/specs/2026-09-24-activity-log-db-design.md: oggi
file di testo, in fase 2-3 SQLite dietro la stessa API. Nessun import dal
progetto: la cartella arriva con `configure()`.
"""
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

TS_FMT = "%Y-%m-%d %H:%M:%S"
_YM_RE = re.compile(r"^\d{4}-\d{2}\Z")
_YM_IN_NAME = re.compile(r"^activity_(\d{4}-\d{2})\.log\Z")
# Il recovery interroga molti descrittori in sequenza: 5 minuti bastano.
_DELIVERED_TTL = 300.0


class Row(NamedTuple):
    job_id: str
    ts: str
    filename: str
    op: str
    client_id: str
    ip: str
    voice: str
    lang: str
    platform: str


_log_dir = None            # callable -> Path, risolta a ogni chiamata
_lock = threading.Lock()   # scrittura + dedup
_month = ""
_keys = set()              # (job_id, op) o (job_id, op, epoch) per gli eventi di ciclo
_delivered_lock = threading.Lock()
_delivered_cache = {"value": None, "expires": 0.0}


def configure(log_dir):
    """`log_dir`: callable senza argomenti che ritorna la cartella dei log.

    Risolta a ogni chiamata: i test che sostituiscono `SCRIPT_DIR` in
    audiobook_app restano validi senza riconfigurare nulla."""
    global _log_dir
    _log_dir = log_dir


def _dir():
    if _log_dir is None:
        raise RuntimeError("activity_log non configurato")
    return Path(_log_dir())


def _path(ym):
    return _dir() / f"activity_{ym}.log"


def reset():
    """Stato come a processo appena avviato (per i test)."""
    global _month
    with _lock:
        _month = ""
        _keys.clear()
    with _delivered_lock:
        _delivered_cache["value"] = None
        _delivered_cache["expires"] = 0.0


# --------------------------------------------------------------- parsing

def split_line(line):
    """Spezza una riga del log nei 9 campi, tollerando '#' nel nome file.

    Il separatore e' ' # ' ma un titolo tipo "Riftwar Saga # 2 Empire.epub"
    lo contiene: uno split secco sfasa i campi. Si ancorano quindi i 2 campi
    di testa e i 6 di coda, lasciando al nome file tutto il resto. Le righe
    storiche corte (senza lang/platform) si completano a destra.

    Ritorna None se la riga non ha nemmeno i campi minimi.
    """
    line = line.rstrip("\r\n")
    if line.endswith(" #"):
        # `platform` vuota: la riga finisce con " # " e chi ha gia' fatto
        # strip() si e' mangiato l'ultimo separatore.
        line += " "
    head = line.split(" # ", 2)
    if len(head) < 3:
        return None
    sid, ts, rest = head
    tail = rest.rsplit(" # ", 6)
    if len(tail) < 7:
        tail = tail + [""] * (7 - len(tail))
    filename, op, client_id, ip, voice, lang, platform = tail[:7]
    return Row(sid.strip(), ts.strip(), filename.strip().strip('"'), op.strip(),
               client_id.strip(), ip.strip(), voice.strip(), lang.strip(),
               platform.strip())


def file_rows(path):
    """Righe valide di un file di log qualsiasi; file assente: nessuna riga."""
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            row = split_line(line)
            if row is not None:
                yield row


# --------------------------------------------------------------- scrittura

def log(job_id, filename, op, client_id="", ip="", voice="", lang="",
        platform="", epoch=None):
    """Scrive una riga nel file del mese corrente. Non solleva mai.

    Dedup per (job_id, op), o (job_id, op, epoch) se `epoch` e' dato: cosi'
    GENERATE/COMPLETE di una ri-generazione dello stesso job non vengono
    soppressi, mentre i download ripetuti (chiamati senza epoch) si'.
    Le righe senza job_id (voucher, admin, backend TTS) non si deduplicano
    mai: ogni evento conta.
    """
    global _month
    now = datetime.now()
    ym = now.strftime("%Y-%m")
    key = None
    if job_id:
        key = (job_id, op) if epoch is None else (job_id, op, epoch)
    line = (f'{job_id} # {now.strftime(TS_FMT)} # "{filename}" # {op} # {client_id}'
            f' # {ip} # {voice} # {lang} # {platform}\n')
    with _lock:
        if ym != _month:
            _month = ym
            _keys.clear()
        if key is not None and key in _keys:
            return
        try:
            with open(_path(ym), "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            print(f"[activity_log] scrittura {op} fallita: {e}")
            return
        if key is not None:
            _keys.add(key)


def init_dedup():
    """Ricostruisce il set di dedup dal file del mese corrente (all'avvio).

    Solo chiavi (job_id, op): l'epoca non sta sulla riga, quindi dopo un
    riavvio un job ri-eseguito puo' ri-loggare il proprio evento di ciclo."""
    global _month
    ym = datetime.now().strftime("%Y-%m")
    keys = {(r.job_id, r.op) for r in month_rows(ym) if r.job_id}
    with _lock:
        _month = ym
        _keys.clear()
        _keys.update(keys)


# --------------------------------------------------------------- lettura

def months():
    """Mesi YYYY-MM con un file di log, dal piu' recente."""
    try:
        names = [p.name for p in _dir().glob("activity_*.log")]
    except (OSError, RuntimeError):
        return []
    found = {m.group(1) for n in names if (m := _YM_IN_NAME.match(n))}
    return sorted(found, reverse=True)


def month_rows(ym):
    """Righe del mese YYYY-MM; mese non valido o assente: nessuna riga."""
    if not _YM_RE.match(ym or ""):
        return
    try:
        path = _path(ym)
    except RuntimeError:
        return
    yield from file_rows(path)


def _months_between(since, until):
    end = until or datetime.now()
    y, m = since.year, since.month
    while (y, m) <= (end.year, end.month):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def iter_rows(since, until=None, ops=None):
    """Righe con `since <= ts < until` (until assente: fino a oggi), in
    ordine di file; `ops`: insieme di operazioni esatte da tenere."""
    since_s = since.strftime(TS_FMT)
    until_s = until.strftime(TS_FMT) if until else None
    for ym in _months_between(since, until):
        for row in month_rows(ym):
            if row.ts < since_s:
                continue
            if until_s is not None and row.ts >= until_s:
                continue
            if ops is not None and row.op not in ops:
                continue
            yield row


def fingerprint(ym):
    """Firma del mese per invalidare le cache; None se il mese non c'e'."""
    if not _YM_RE.match(ym or ""):
        return None
    try:
        st = _path(ym).stat()
    except (OSError, RuntimeError):
        return None
    return (st.st_mtime_ns, st.st_size)


def delivered_ids(months=3):
    """job_id con COMPLETE / OPT_COMPLETE negli ultimi `months` mesi.

    E' la sola traccia persistente di "consegnato": il dict jobs e' in RAM e
    al boot e' vuoto. Cache di 5 minuti."""
    now = time.time()
    with _delivered_lock:
        cached = _delivered_cache["value"]
        if cached is not None and now < _delivered_cache["expires"]:
            return cached
    complete, opt = set(), set()
    d = datetime.now()
    y, m = d.year, d.month
    for _ in range(max(1, int(months))):
        for row in month_rows(f"{y:04d}-{m:02d}"):
            if row.op == "COMPLETE":
                complete.add(row.job_id)
            elif row.op == "OPT_COMPLETE":
                opt.add(row.job_id)
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    value = {"complete": complete, "opt_complete": opt}
    with _delivered_lock:
        _delivered_cache["value"] = value
        _delivered_cache["expires"] = time.time() + _DELIVERED_TTL
    return value
