"""Indice SQLite dell'activity log (modulo foglia, sola stdlib).

`activity.db` affianca i file `activity_YYYY-MM.log` (fasi 2-3 di
docs/superpowers/specs/2026-09-24-activity-log-db-design.md). Fino alla
fase 4 il file resta il registro completo: ogni mese del DB si puo' rifare
da capo dal suo file. Qui stanno schema, mappatura riga <-> colonne e
query; modi, lock e dedup stanno in activity_log.

Le righe entrano ed escono come tuple di 9 stringhe nell'ordine di
activity_log.Row (FIELDS): questo modulo non importa activity_log.
"""
import sqlite3
import time
from pathlib import Path
from typing import cast

DB_FILENAME = "activity.db"
FIELDS = ("job_id", "ts", "filename", "op", "client_id", "ip", "voice",
          "lang", "platform")

# Famiglie di op che scrivono un payload in una colonna nata per altro: nel
# DB il valore passa in `detail` e la colonna resta vuota. Vince il primo
# prefisso che combacia con l'op senza suffisso. La mappatura e' invertibile:
# la riga riletta e' identica a quella del file.
DETAIL_FIELD = (
    ("M4B_", "voice"),             # size_mb=... pct=... (generation_engine)
    ("ADMIN_VOUCHER_", "lang"),    # email del destinatario o motivo della revoca
    ("VOUCHER_ATTEMPT", "lang"),   # esito del tentativo
    ("PAYMENT_", "lang"),          # errore della capture
    ("VOICE_CLONE_", "filename"),  # extra di _vc_log
    ("ACCOUNT_", "filename"),      # extra di _acct_log
)

# L'op come sta nel file: base piu' eventuale ':' + argomento.
_FULL_OP = "op || IFNULL(':' || op_arg, '')"
_COLS = ("ym", "ts", "job_id", "op", "op_arg", "filename", "client_id", "ip",
         "voice", "detail", "lang", "platform", "epoch", "seq")
_INSERT = ("INSERT {} INTO events (" + ", ".join(_COLS) + ") VALUES ("
           + ", ".join("?" * len(_COLS)) + ")")
_SEL = ("job_id", "ts", "filename", "op", "op_arg", "client_id", "ip",
        "voice", "detail", "lang", "platform")

_MIGRATIONS = (
    ("001_events", (
        """CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            ym TEXT NOT NULL,
            ts TEXT NOT NULL,
            job_id TEXT NOT NULL,
            op TEXT NOT NULL,
            op_arg TEXT,
            filename TEXT NOT NULL,
            client_id TEXT NOT NULL,
            ip TEXT NOT NULL,
            voice TEXT NOT NULL,
            detail TEXT NOT NULL,
            lang TEXT NOT NULL,
            platform TEXT NOT NULL,
            epoch REAL,
            seq INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX events_ym ON events (ym, id)",
        "CREATE INDEX events_ts ON events (ts)",
        "CREATE INDEX events_job ON events (job_id)",
        "CREATE INDEX events_op_ts ON events (op, ts)",
        "CREATE INDEX events_client_ts ON events (client_id, ts)",
        # Regola C1 (job vuoto mai deduplicato) + reset mensile (ym) + le
        # ripetizioni storiche del file (seq): vedi l'addendum della spec.
        "CREATE UNIQUE INDEX events_dedup ON events (ym, job_id, op, "
        "IFNULL(op_arg, ''), IFNULL(epoch, -1), seq) WHERE job_id <> ''",
        "CREATE TABLE sync_state (ym TEXT PRIMARY KEY, size INTEGER NOT NULL, "
        "rows INTEGER NOT NULL)",
    )),
)


# --------------------------------------------------------------- connessioni

def _migrate(conn, name, statements):
    conn.execute("BEGIN IMMEDIATE")
    try:
        done = conn.execute("SELECT 1 FROM schema_migrations WHERE name = ?",
                            (name,)).fetchone()
        if done is None:
            for s in statements:
                conn.execute(s)
            conn.execute("INSERT INTO schema_migrations (name, applied_at) "
                         "VALUES (?, ?)", (name, int(time.time())))
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def connect(path):
    """Connessione di scrittura (autocommit): crea il file se manca e
    applica le migrazioni. Chi la condivide fra thread la serializza."""
    conn = sqlite3.connect(str(path), check_same_thread=False,
                           isolation_level=None, timeout=2.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=2000")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                     "(name TEXT PRIMARY KEY, applied_at INTEGER NOT NULL)")
        for name, statements in _MIGRATIONS:
            _migrate(conn, name, statements)
    except BaseException:
        conn.close()
        raise
    return conn


def reader(path):
    """Connessione di sola lettura su un DB esistente: se il file manca
    solleva sqlite3.OperationalError invece di crearlo vuoto."""
    uri = Path(path).resolve().as_uri() + "?mode=rw"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=2.0)
    conn.execute("PRAGMA query_only=1")
    return conn


# --------------------------------------------------------------- mappatura

def _detail_field(op):
    for prefix, field in DETAIL_FIELD:
        if op.startswith(prefix):
            return field
    return None


def to_columns(row):
    """Tupla di 9 campi (ordine FIELDS) -> colonne di `events` senza
    ym/epoch/seq."""
    rec: dict[str, str | None] = dict(zip(FIELDS, row))
    # "op" e' sempre popolato (mai None) dalla tupla di 9 stringhe di
    # activity_log.Row; il cast serve solo a Pyright, che dopo
    # l'annotazione sopra vede tutti i valori come str | None.
    base, sep, arg = cast(str, rec["op"]).partition(":")
    rec["op"], rec["op_arg"] = base, (arg if sep else None)
    rec["detail"] = ""
    field = _detail_field(base)
    if field is not None:
        rec["detail"], rec[field] = rec[field], ""
    return rec


def from_columns(rec):
    """Inversa di to_columns: dalle colonne (mapping) alla tupla del file."""
    out = {f: rec[f] for f in FIELDS}
    field = _detail_field(rec["op"])
    if field is not None:
        out[field] = rec["detail"]
    if rec["op_arg"] is not None:
        out["op"] = f'{rec["op"]}:{rec["op_arg"]}'
    return tuple(out[f] for f in FIELDS)


def _values(ym, rec, epoch, seq):
    return (ym, rec["ts"], rec["job_id"], rec["op"], rec["op_arg"],
            rec["filename"], rec["client_id"], rec["ip"], rec["voice"],
            rec["detail"], rec["lang"], rec["platform"], epoch, seq)


# --------------------------------------------------------------- scrittura

def insert_new(conn, ym, row, epoch=None):
    """Dedup del modo db: True se la riga e' entrata, False se la chiave
    (ym, job_id, op, op_arg, epoch) c'era gia'. Job vuoto: entra sempre."""
    return _insert_new_row(conn, ym, row, epoch) is not None


def _insert_new_row(conn, ym, row, epoch=None):
    """Come insert_new ma ritorna l'id della riga appena entrata (None se
    la chiave c'era gia'). Uso interno di activity_log: se la scrittura sul
    file fallisce dopo un insert riuscito, l'id serve a compensare con
    `delete_row` cosi' il DB non resta avanti al file."""
    cur = conn.execute(_INSERT.format("OR IGNORE"),
                       _values(ym, to_columns(row), epoch, 0))
    return cur.lastrowid if cur.rowcount == 1 else None


def delete_row(conn, rowid):
    """Cancella una riga per id: compensazione best-effort di chi scrive."""
    conn.execute("DELETE FROM events WHERE id = ?", (rowid,))


def insert_mirror(conn, ym, row, epoch=None):
    """Copia fedele del modo dual: la riga e' gia' nel file ed entra sempre,
    con `seq` = prossimo libero della sua chiave. Il chiamante serializza."""
    rec = to_columns(row)
    seq = 0
    if rec["job_id"]:
        seq = conn.execute(
            "SELECT IFNULL(MAX(seq) + 1, 0) FROM events WHERE job_id <> '' "
            "AND ym = ? AND job_id = ? AND op = ? AND IFNULL(op_arg, '') = ? "
            "AND IFNULL(epoch, -1) = ?",
            (ym, rec["job_id"], rec["op"], rec["op_arg"] or "",
             -1 if epoch is None else epoch)).fetchone()[0]
    conn.execute(_INSERT.format(""), _values(ym, rec, epoch, seq))
    return True


def rebuild_month(conn, ym, rows, size):
    """Rifa da capo il mese `ym` con `rows` (righe del file, in ordine) in
    una transazione. Le chiavi ripetute nel file prendono seq crescente,
    cosi' entrano tutte; l'epoca non sta nel file e resta NULL. Registra
    la dimensione del file allineato. Ritorna le righe scritte."""
    seen = {}
    n = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM events WHERE ym = ?", (ym,))
        for row in rows:
            rec = to_columns(row)
            seq = 0
            if rec["job_id"]:
                k = (rec["job_id"], rec["op"], rec["op_arg"] or "")
                seq = seen.get(k, 0)
                seen[k] = seq + 1
            conn.execute(_INSERT.format(""), _values(ym, rec, None, seq))
            n += 1
        mark_synced(conn, ym, size, n)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return n


def mark_synced(conn, ym, size, rows):
    conn.execute("INSERT OR REPLACE INTO sync_state (ym, size, rows) "
                 "VALUES (?, ?, ?)", (ym, size, rows))


# --------------------------------------------------------------- lettura

def synced_size(conn, ym):
    r = conn.execute("SELECT size FROM sync_state WHERE ym = ?", (ym,)).fetchone()
    return r[0] if r else None


def count(conn, ym):
    return conn.execute("SELECT COUNT(*) FROM events WHERE ym = ?",
                        (ym,)).fetchone()[0]


def op_counts(conn, ym):
    """{op completa: righe} del mese."""
    return dict(conn.execute(
        f"SELECT {_FULL_OP}, COUNT(*) FROM events WHERE ym = ? GROUP BY 1",
        (ym,)).fetchall())


def fingerprint(conn, ym):
    """Firma del mese per invalidare le cache; None se il mese e' vuoto."""
    n, last = conn.execute("SELECT COUNT(*), MAX(id) FROM events WHERE ym = ?",
                           (ym,)).fetchone()
    return (last, n) if n else None


def select_rows(conn, ym_from, ym_to, since_ts=None, until_ts=None, ops=None,
                batch=2000):
    """Righe (tuple di 9) dei mesi ym_from..ym_to inclusi, in ordine di mese
    e di scrittura. since_ts/until_ts: stringhe nel formato del file, since
    incluso, until escluso. ops: op complete (con suffisso) da tenere."""
    sql = ["SELECT", ", ".join(_SEL), "FROM events WHERE ym >= ? AND ym <= ?"]
    args = [ym_from, ym_to]
    if since_ts is not None:
        sql.append("AND ts >= ?")
        args.append(since_ts)
    if until_ts is not None:
        sql.append("AND ts < ?")
        args.append(until_ts)
    if ops is not None:
        ops = sorted(ops)
        if not ops:
            return
        sql.append(f"AND {_FULL_OP} IN ({', '.join('?' * len(ops))})")
        args.extend(ops)
    sql.append("ORDER BY ym, id")
    cur = conn.execute(" ".join(sql), args)
    while True:
        chunk = cur.fetchmany(batch)
        if not chunk:
            return
        for r in chunk:
            yield from_columns(dict(zip(_SEL, r)))
