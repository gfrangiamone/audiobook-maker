"""Business log mensile delle attivita' (modulo foglia, sola stdlib).

Unico punto di accesso a `activity_YYYY-MM.log`: scrittura con dedup,
parsing, letture per mese o per intervallo. Formato su disco:

    <job_id> # <ts> # "<file>" # <op> # <cid> # <ip> # <voice> # <lang> # <platform>

Fasi 1-3 di docs/superpowers/specs/2026-09-24-activity-log-db-design.md.
Il modo arriva a ogni chiamata da ABM_ACTIVITY_DB: `off` (default) solo
file; `dual` file piu' copia in activity.db, letture dal file; `db` dedup e
letture sul DB, file sempre scritto. Fino alla fase 4 il file e' il
registro completo e il DB un indice ricostruibile (`sync_month`). Nessun
import dal progetto oltre ad activity_db: la cartella arriva con
`configure()`.
"""
import contextlib
import os
import re
import sqlite3
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import activity_db

TS_FMT = "%Y-%m-%d %H:%M:%S"
_YM_RE = re.compile(r"^\d{4}-\d{2}\Z")
_YM_IN_NAME = re.compile(r"^activity_(\d{4}-\d{2})\.log\Z")
# Il recovery interroga molti descrittori in sequenza: 5 minuti bastano.
_DELIVERED_TTL = 300.0

MODES = ("off", "dual", "db")
# Oltre questa soglia una scrittura sul DB finisce nel log di servizio: e'
# la misura che decide fra scrittura sincrona e coda (spec, addendum 7).
_SLOW_DB_MS = 50.0


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
_wconn = None              # connessione di scrittura su activity.db, sotto _lock
_wpath = None
_db_ready = threading.Event()   # sync_all finito senza errori: il modo db legge dal DB
_db_stats = {"writes": 0, "total_ms": 0.0, "max_ms": 0.0}


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


def mode():
    """Modo del backend, letto a ogni chiamata; valore ignoto = off."""
    m = os.environ.get("ABM_ACTIVITY_DB", "off").strip().lower()
    return m if m in MODES else "off"


def _db_path():
    return _dir() / activity_db.DB_FILENAME


def _writer():
    """Connessione di scrittura, da usare sotto `_lock`; riaperta se la
    cartella cambia (i test la spostano)."""
    global _wconn, _wpath
    path = _db_path()
    if _wconn is None or _wpath != path:
        _close_writer()
        _wconn = activity_db.connect(path)
        _wpath = path
    return _wconn


def _close_writer():
    """Chiude la connessione di scrittura. Con `_lock` preso."""
    global _wconn, _wpath
    if _wconn is not None:
        try:
            _wconn.close()
        except Exception:
            pass
    _wconn, _wpath = None, None


def _db_write(fn, ym, row, epoch):
    """`fn(conn, ym, row, epoch)` sul DB, con `_lock` gia' preso. Mai
    un'eccezione: None se il DB non risponde."""
    try:
        conn = _writer()
        t0 = time.perf_counter()
        res = fn(conn, ym, row, epoch)
    except Exception as e:
        _close_writer()
        print(f"[activity_log] scrittura DB {row[3]} fallita: {e}")
        return None
    ms = (time.perf_counter() - t0) * 1000.0
    _db_stats["writes"] += 1
    _db_stats["total_ms"] += ms
    _db_stats["max_ms"] = max(_db_stats["max_ms"], ms)
    if ms > _SLOW_DB_MS:
        print(f"[activity_log] scrittura DB lenta: {row[3]} {ms:.0f} ms")
    return res


def db_stats():
    """Scritture sul DB di questo processo e loro latenza in ms."""
    w = _db_stats["writes"]
    return {"writes": w,
            "avg_ms": (_db_stats["total_ms"] / w) if w else 0.0,
            "max_ms": _db_stats["max_ms"]}


def reset():
    """Stato come a processo appena avviato (per i test)."""
    global _month
    with _lock:
        _month = ""
        _keys.clear()
        _close_writer()
    _db_ready.clear()
    _db_stats.update(writes=0, total_ms=0.0, max_ms=0.0)
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
    """Scrive una riga nel mese corrente. Non solleva mai.

    Dedup per (job_id, op), o (job_id, op, epoch) se `epoch` e' dato: cosi'
    GENERATE/COMPLETE di una ri-generazione dello stesso job non vengono
    soppressi, mentre i download ripetuti (chiamati senza epoch) si'.
    Le righe senza job_id (voucher, admin, backend TTS) non si deduplicano
    mai: ogni evento conta.

    `off`: file, dedup sul set in RAM. `dual`: come off, poi la stessa riga
    entra tale e quale nel DB. `db`: decide il DB (chiave del mese, epoca
    compresa, anche dopo un riavvio) e il file riceve solo le righe nuove;
    se il DB non risponde la riga va comunque nel file, senza dedup.
    """
    global _month
    now = datetime.now()
    ym = now.strftime("%Y-%m")
    key = None
    if job_id:
        key = (job_id, op) if epoch is None else (job_id, op, epoch)
    line = (f'{job_id} # {now.strftime(TS_FMT)} # "{filename}" # {op} # {client_id}'
            f' # {ip} # {voice} # {lang} # {platform}\n')
    m = mode()
    # La riga del DB e' quella che il file restituira' rileggendola.
    row = tuple(split_line(line)) if m != "off" else None
    with _lock:
        if m == "db":
            if _db_write(activity_db.insert_new, ym, row, epoch) is False:
                return
        else:
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
        if m == "db":
            return
        if key is not None:
            _keys.add(key)
        if m == "dual":
            _db_write(activity_db.insert_mirror, ym, row, epoch)


def init_dedup():
    """Ricostruisce il set di dedup dal file del mese corrente (all'avvio).

    Solo chiavi (job_id, op): l'epoca non sta sulla riga, quindi dopo un
    riavvio un job ri-eseguito puo' ri-loggare il proprio evento di ciclo.
    Nel modo db non serve: il dedup lo fa il DB."""
    global _month
    ym = datetime.now().strftime("%Y-%m")
    if mode() == "db":
        with _lock:
            _month = ym
            _keys.clear()
        return
    keys = {(r.job_id, r.op) for r in month_rows(ym) if r.job_id}
    with _lock:
        _month = ym
        _keys.clear()
        _keys.update(keys)


# --------------------------------------------------------------- allineamento

def sync_month(ym, force=False):
    """Allinea il mese `ym` del DB al suo file; True se l'ha ricostruito.

    Mese chiuso con la dimensione dell'ultimo allineamento: saltato senza
    leggerlo. Altrimenti si contano le righe valide del file e, se non
    tornano con il DB (o con `force`), il mese si rifa' da capo. Il mese
    corrente si tratta sotto `_lock`: nessuna riga nuova entra nel file fra
    la lettura e la riscrittura."""
    if not _YM_RE.match(ym or ""):
        return False
    try:
        path = _path(ym)
        path.stat()
    except (OSError, RuntimeError):
        return False
    current = ym == datetime.now().strftime("%Y-%m")
    with (_lock if current else contextlib.nullcontext()):
        size = path.stat().st_size
        conn = activity_db.connect(_db_path())
        try:
            if not force:
                if not current and activity_db.synced_size(conn, ym) == size:
                    return False
                n = sum(1 for _ in file_rows(path))
                if activity_db.count(conn, ym) == n:
                    activity_db.mark_synced(conn, ym, size, n)
                    return False
            activity_db.rebuild_month(conn, ym, file_rows(path), size)
            return True
        finally:
            conn.close()


def sync_all():
    """Allinea il DB ai file, dal mese piu' vecchio al corrente (all'avvio,
    in un thread). Senza errori i lettori del modo db passano al DB; finche'
    non succede leggono dal file. Mai un'eccezione. Modo off: nulla."""
    if mode() == "off":
        return 0
    rebuilt = failed = 0
    for ym in sorted(months()):
        try:
            if sync_month(ym):
                rebuilt += 1
        except Exception as e:
            failed += 1
            print(f"[activity_log] sync {ym} fallito: {e}")
    if not failed:
        _db_ready.set()
    print(f"[activity_log] sync: {rebuilt} mesi ricostruiti, {failed} falliti")
    return rebuilt


def parity(ym):
    """Op del mese con conteggi diversi fra file e DB: {op: (file, db)}."""
    if not _YM_RE.match(ym or ""):
        raise ValueError(f"mese non valido: {ym!r}")
    in_file = Counter(r.op for r in file_rows(_path(ym)))
    try:
        conn = activity_db.reader(_db_path())
    except sqlite3.OperationalError:
        in_db = {}
    else:
        try:
            in_db = activity_db.op_counts(conn, ym)
        finally:
            conn.close()
    return {op: (in_file.get(op, 0), in_db.get(op, 0))
            for op in set(in_file) | set(in_db)
            if in_file.get(op, 0) != in_db.get(op, 0)}


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
