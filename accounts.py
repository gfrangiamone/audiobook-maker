# accounts.py
"""Account opzionali: magic link + codice a 6 cifre, sessioni, storico job.

Modulo foglia: dipende solo da `db` e dalla stdlib. Lo stato dell'app
(percorso di `_payments.json`, funzioni di voice_clone, logger) arriva via
`configure()`. Nessuna email in chiaro nei log: usare `email_hash()`.
"""
import hashlib
import hmac
import json
import math
from client_identity import email_hash as _ci_email_hash, norm_email as _norm
from fileio import load_json
from env_utils import env_int as _env_int, env_str
import secrets
import threading
import time

import db


ENABLE = env_str("ABM_ACCOUNT_ENABLE", "1").lower() not in ("0", "false", "no", "off")
SESSION_DAYS = _env_int("ABM_ACCOUNT_SESSION_DAYS", 90)
CODE_TTL_MIN = _env_int("ABM_ACCOUNT_CODE_TTL_MIN", 10)
CODE_MAX_ATTEMPTS = _env_int("ABM_ACCOUNT_CODE_MAX_ATTEMPTS", 5)
HISTORY_MONTHS = _env_int("ABM_ACCOUNT_HISTORY_MONTHS", 24)
GRACE_DAYS = _env_int("ABM_ACCOUNT_GRACE_DAYS", 90)

# Account demo per la revisione degli store (Play Console / App Review): per
# questa email il codice di login e' fisso e non parte nessuna email. Spento
# se una delle due variabili manca o il codice non e' di 6 cifre.
REVIEW_EMAIL = env_str("ABM_REVIEW_EMAIL").lower()
REVIEW_CODE = env_str("ABM_REVIEW_CODE")

PURPOSES = ("login", "delete")
EMAIL_RATE_MAX = 3            # richieste di codice per email ...
EMAIL_RATE_WINDOW_SEC = 600   # ... in questa finestra
SESSION_TOUCH_SEC = 3600      # rinnovo rolling solo oltre quest'inattivita'
JOB_STATUSES = ("running", "done", "error", "cancelled")

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        email_hash TEXT NOT NULL,
        lang TEXT NOT NULL DEFAULT 'en',
        plan TEXT NOT NULL DEFAULT 'free',
        plan_until INTEGER,
        created_at INTEGER NOT NULL,
        last_login_at INTEGER,
        deleted_at INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES accounts(id),
        created_at INTEGER NOT NULL,
        last_seen_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        revoked_at INTEGER,
        device_name TEXT NOT NULL DEFAULT '',
        ip_hash TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS ix_sessions_account ON sessions(account_id)",
    """CREATE TABLE IF NOT EXISTS auth_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL,
        purpose TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        code_hash TEXT NOT NULL,
        lang TEXT NOT NULL DEFAULT 'en',
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        consumed_at INTEGER,
        ip_hash TEXT NOT NULL DEFAULT '',
        ua TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS ix_auth_codes_email ON auth_codes(email, created_at)",
    """CREATE TABLE IF NOT EXISTS account_jobs (
        job_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES accounts(id),
        created_at INTEGER NOT NULL,
        kind TEXT NOT NULL,
        book_title TEXT NOT NULL DEFAULT '',
        output_format TEXT NOT NULL DEFAULT '',
        voice TEXT NOT NULL DEFAULT '',
        lang TEXT NOT NULL DEFAULT '',
        paid_eur REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'running',
        source TEXT NOT NULL DEFAULT 'forced',
        download_token TEXT NOT NULL DEFAULT '',
        updated_at INTEGER NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_account_jobs_account ON account_jobs(account_id, created_at DESC)",
]

_payments_path = None
_voice_ids_for_email = None
_link_voice = None
_unlink_voice = None
_log = print


def configure(*, payments_path=None, voice_clone_ids_for_email_fn=None,
              link_voice_fn=None, unlink_voice_fn=None, log_fn=None):
    global _payments_path, _voice_ids_for_email, _link_voice, _unlink_voice, _log
    if payments_path is not None:
        _payments_path = str(payments_path)
    if voice_clone_ids_for_email_fn is not None:
        _voice_ids_for_email = voice_clone_ids_for_email_fn
    if link_voice_fn is not None:
        _link_voice = link_voice_fn
    if unlink_voice_fn is not None:
        _unlink_voice = unlink_voice_fn
    if log_fn is not None:
        _log = log_fn


def enabled():
    return bool(ENABLE) and db.is_ready()


# Storico: piano (standard/premium) e modello del job. Colonne aggiunte dopo
# `accounts_v1`, quindi in una migrazione a parte: i DB gia' creati non
# ricevono due volta la CREATE TABLE. Le righe preesistenti restano con i
# campi vuoti (il dato non e' ricostruibile: il job non c'e' piu').
JOBS_PLAN_MIGRATION = [
    "ALTER TABLE account_jobs ADD COLUMN engine TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE account_jobs ADD COLUMN model TEXT NOT NULL DEFAULT ''",
]


# Storico: righe eliminate dall'utente dall'area personale. Nascoste, non
# cancellate: il pannello admin conta job e incassi da questa tabella, e
# adopt_history (INSERT OR IGNORE) resusciterebbe una riga cancellata.
JOBS_HIDDEN_MIGRATION = [
    "ALTER TABLE account_jobs ADD COLUMN hidden_at INTEGER",
]


# Abbonamento di archivio: job conservati su cold storage oltre la retention.
# `archived_at` dice che il job e' entrato nell'archivio dell'account,
# `archived_bytes` quanto pesa sulla quota (misurato all'ingresso).
JOBS_ARCHIVE_MIGRATION = [
    "ALTER TABLE account_jobs ADD COLUMN archived_at INTEGER",
    "ALTER TABLE account_jobs ADD COLUMN archived_bytes INTEGER NOT NULL DEFAULT 0",
]


# Archivio dell'app: libri archiviati dalla libreria dello smartphone. Ogni
# riga e' un file caricato dall'app sotto `user_archive/<account_id>/` (`r2_key`,
# pesa `size_bytes` sulla quota anche mentre e' `pending`, cioe' prenotato)
# oppure un collegamento a un job gia' nell'archivio dell'account (`job_id`,
# peso zero: i byte li conta gia' il job). Logica in `user_archive`.
ARCHIVE_ITEMS_MIGRATION = [
    """CREATE TABLE IF NOT EXISTS archive_items (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES accounts(id),
        fingerprint TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending',
        filename TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        author TEXT NOT NULL DEFAULT '',
        duration_ms INTEGER NOT NULL DEFAULT 0,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        r2_key TEXT NOT NULL DEFAULT '',
        job_id TEXT NOT NULL DEFAULT '',
        link_token TEXT NOT NULL DEFAULT '',
        link_kind TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_archive_items_fp ON archive_items(account_id, fingerprint)",
    "CREATE INDEX IF NOT EXISTS ix_archive_items_job ON archive_items(job_id)",
]


# Impronta (stesso algoritmo dell'app) del file dell'audiolibro di un job,
# calcolata una volta per download token: l'app la confronta con i file della
# sua libreria per non elencare fra gli archiviati un libro che ha gia'.
JOBS_LIBFP_MIGRATION = [
    "ALTER TABLE account_jobs ADD COLUMN lib_fp TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE account_jobs ADD COLUMN lib_size INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE account_jobs ADD COLUMN lib_token TEXT NOT NULL DEFAULT ''",
]


# Copia R2 di un libro caricato dall'app e poi convertito in collegamento a un
# job archiviato con lo stesso contenuto: la riga si aggiorna prima, l'oggetto
# si cancella dopo, e finche' il delete non riesce la chiave resta qui.
ARCHIVE_ITEMS_ORPHAN_MIGRATION = [
    "ALTER TABLE archive_items ADD COLUMN orphan_key TEXT NOT NULL DEFAULT ''",
]


# Piani v2: archivio gratuito con consenso + piani di spazio regalati dall'admin.
# `plan_source` dice da dove viene `plan` ('' = nessuno, 'gift' = regalo admin,
# 'paid' = abbonamento, scritto da `set_paid_plan`); `free_consent_*` il consenso al piano gratuito (versione
# dei termini accettata), `free_offer_at` quando gli e' stato proposto;
# `archive_over_since`/`archive_notice_stage` la tolleranza dopo la perdita della
# quota, `archive_notice_ids` l'array JSON delle chiavi `job:<id>`/`item:<id>` dei
# libri elencati dall'ultima email di avviso, riavvio o promemoria (NULL = nessuno,
# niente da confrontare: vedi `archive_notice_keys`);
# `archive_evicted_at` il job tolto dall'archivio. `plan_consents` e' il registro
# delle scelte dell'utente: solo INSERT, mai UPDATE/DELETE.
PLANS_V2_MIGRATION = [
    "ALTER TABLE accounts ADD COLUMN plan_source TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE accounts ADD COLUMN free_consent_at INTEGER",
    "ALTER TABLE accounts ADD COLUMN free_consent_version TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE accounts ADD COLUMN free_offer_at INTEGER",
    "ALTER TABLE accounts ADD COLUMN archive_over_since INTEGER",
    "ALTER TABLE accounts ADD COLUMN archive_notice_stage INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE accounts ADD COLUMN archive_notice_ids TEXT",
    "ALTER TABLE account_jobs ADD COLUMN archive_evicted_at INTEGER",
    """CREATE TABLE IF NOT EXISTS plan_consents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id TEXT NOT NULL,
        at INTEGER NOT NULL,
        action TEXT NOT NULL,
        version TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_plan_consents_account ON plan_consents(account_id)",
]


def _insert_consents(c, rows):
    """Aggiunge al registro `plan_consents` le righe (account_id, at, action,
    version, source): e' l'unico punto che lo scrive."""
    c.executemany(
        "INSERT INTO plan_consents(account_id, at, action, version, source) "
        "VALUES (?, ?, ?, ?, ?)", rows)


def _grant_migrated_consent(c, ids, now):
    """Consenso al piano gratuito (source='migration') per gli account `ids`."""
    c.executemany(
        "UPDATE accounts SET free_consent_at=?, free_consent_version=?, free_offer_at=? WHERE id=?",
        [(now, FREE_TERMS_VERSION, now, i) for i in ids])
    _insert_consents(c, [(i, now, "grant", FREE_TERMS_VERSION, "migration") for i in ids])


# Piani di archivio della versione precedente (10/20/50 GB): servono solo alla
# migrazione dei dati, che li converte in sub_10 regalato.
_LEGACY_ARCHIVE_PLANS = ("archive_10", "archive_20", "archive_50")


def _migrate_plans_v2_data(c):
    """Dati dei piani v2, una volta sola e nell'ordine: account cancellati ->
    free; archive_10/20/50 -> sub_10 regalato (con consenso); revocati ancora
    in grazia -> free con consenso; revocati a grazia scaduta -> tolleranza gia'
    scaduta (la vecchia regola aveva promesso la cancellazione: niente nuova
    email); ogni altro `plan_until` -> NULL."""
    now = int(time.time())
    grace_sec = _env_int("ABM_ARCHIVE_GRACE_DAYS", 30, floor=0) * 86400
    tolerance_sec = archive_tolerance_days() * 86400
    c.execute("UPDATE accounts SET plan=?, plan_source='', plan_until=NULL "
              "WHERE deleted_at IS NOT NULL", (PLAN_FREE,))
    legacy = _LEGACY_ARCHIVE_PLANS
    marks = ",".join("?" * len(legacy))
    gifted = [r[0] for r in c.execute(f"SELECT id FROM accounts WHERE plan IN ({marks})", legacy)]
    c.execute(f"UPDATE accounts SET plan='sub_10', plan_source='gift' WHERE plan IN ({marks})", legacy)
    _grant_migrated_consent(c, gifted, now)
    in_grace = [r[0] for r in c.execute(
        "SELECT id FROM accounts WHERE plan=? AND plan_until IS NOT NULL AND plan_until + ? > ?",
        (PLAN_FREE, grace_sec, now))]
    c.executemany("UPDATE accounts SET plan_until=NULL WHERE id=?", [(i,) for i in in_grace])
    _grant_migrated_consent(c, in_grace, now)
    c.execute("UPDATE accounts SET plan_until=NULL, archive_over_since=?, archive_notice_stage=2 "
              "WHERE plan=? AND plan_until IS NOT NULL", (now - tolerance_sec - 1, PLAN_FREE))
    space_marks = ",".join("?" * len(SPACE_PLANS))
    c.execute("UPDATE accounts SET plan_until=NULL WHERE plan_until IS NOT NULL "
              f"AND plan NOT IN ({space_marks})", SPACE_PLANS)


def init_schema():
    db.migrate("accounts_v1", SCHEMA)
    db.migrate("account_jobs_plan_v1", JOBS_PLAN_MIGRATION)
    db.migrate("account_jobs_hidden_v1", JOBS_HIDDEN_MIGRATION)
    db.migrate("account_jobs_archive_v1", JOBS_ARCHIVE_MIGRATION)
    db.migrate("archive_items_v1", ARCHIVE_ITEMS_MIGRATION)
    db.migrate("account_jobs_libfp_v1", JOBS_LIBFP_MIGRATION)
    db.migrate("archive_items_orphan_v1", ARCHIVE_ITEMS_ORPHAN_MIGRATION)
    db.migrate("accounts_plans_v2", PLANS_V2_MIGRATION)
    db.migrate("accounts_plans_v2_data", [_migrate_plans_v2_data])


# ---------------------------------------------------------------- helpers

def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def is_review_login(email, purpose="login"):
    """True per il login dell'account demo di revisione (codice fisso, nessuna
    email). Solo `login`: la cancellazione account resta col codice casuale."""
    return (purpose == "login" and bool(REVIEW_EMAIL)
            and len(REVIEW_CODE) == 6 and REVIEW_CODE.isdigit()
            and _norm(email) == REVIEW_EMAIL)


def email_hash(email):
    return _ci_email_hash(email)


def _now(now):
    return int(now if now is not None else time.time())


def _row(r):
    return dict(r) if r is not None else None


# ---------------------------------------------------------------- codes

def request_code(email, purpose="login", lang="en", ip_hash="", ua="", now=None):
    """Genera token (magic link) e codice a 6 cifre per `email`.

    Ritorna (token, code) oppure None se l'email ha gia' chiesto
    EMAIL_RATE_MAX codici nella finestra (risposta neutra a monte).
    """
    if purpose not in PURPOSES:
        raise ValueError("purpose non valido: %r" % (purpose,))
    email = _norm(email)
    now = _now(now)
    with db.tx() as c:
        n = c.execute(
            "SELECT COUNT(*) FROM auth_codes WHERE email=? AND created_at>?",
            (email, now - EMAIL_RATE_WINDOW_SEC),
        ).fetchone()[0]
        if n >= EMAIL_RATE_MAX:
            return None
        # Un nuovo codice invalida quelli ancora pendenti per la stessa email+purpose:
        # solo l'ultimo emesso deve essere spendibile.
        c.execute(
            "UPDATE auth_codes SET consumed_at=? WHERE email=? AND purpose=? AND consumed_at IS NULL",
            (now, email, purpose),
        )
        token = secrets.token_urlsafe(32)
        code = (REVIEW_CODE if is_review_login(email, purpose)
                else f"{secrets.randbelow(10**6):06d}")
        c.execute(
            "INSERT INTO auth_codes(email, purpose, token_hash, code_hash, lang, "
            "created_at, expires_at, attempts, ip_hash, ua) "
            "VALUES (?,?,?,?,?,?,?,0,?,?)",
            (email, purpose, _sha(token), _sha(email + ":" + code),
             (lang or "en")[:8], now, now + CODE_TTL_MIN * 60,
             ip_hash or "", (ua or "")[:200]),
        )
    return token, code


def _login_or_get(c, email, lang, purpose, now):
    row = c.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
    if purpose == "delete":
        if row is None or row["deleted_at"] is not None:
            return None
        return _row(row)
    created = False
    if row is None:
        aid = "ac_" + secrets.token_hex(8)
        c.execute(
            "INSERT INTO accounts(id, email, email_hash, lang, plan, created_at, last_login_at) "
            "VALUES (?,?,?,?,'free',?,?)",
            (aid, email, _sha(email), lang or "en", now, now),
        )
        created = True
    else:
        aid = row["id"]
        c.execute(
            "UPDATE accounts SET lang=?, last_login_at=? WHERE id=?",
            (lang or row["lang"] or "en", now, aid),
        )
    acct = _row(c.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone())
    if created:
        try:
            adopt_history(acct)
        except Exception as e:  # mai bloccare il login per l'adozione
            _log(f"WARNING accounts.adopt_history: {e}")
    return acct


def verify(token=None, email=None, code=None, purpose="login", now=None):
    """Verifica magic link (token) o coppia email+codice.

    Ritorna (stato, account): stato in ok|wrong|expired|locked|none.
    Il codice e' consumato solo su `ok`. Un token consumato vale `none`.
    """
    now = _now(now)
    with db.tx() as c:
        if token:
            row = c.execute(
                "SELECT * FROM auth_codes WHERE token_hash=? AND purpose=?",
                (_sha(token), purpose),
            ).fetchone()
        else:
            row = c.execute(
                "SELECT * FROM auth_codes WHERE email=? AND purpose=? AND consumed_at IS NULL "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (_norm(email), purpose),
            ).fetchone()
        if row is None or row["consumed_at"] is not None:
            return "none", None
        if row["expires_at"] <= now:
            return "expired", None
        if row["attempts"] >= CODE_MAX_ATTEMPTS:
            return "locked", None
        if not token:
            got = _sha(row["email"] + ":" + str(code or "").strip())
            if not hmac.compare_digest(row["code_hash"], got):
                c.execute("UPDATE auth_codes SET attempts=attempts+1 WHERE id=?", (row["id"],))
                return "wrong", None
        acct = _login_or_get(c, row["email"], row["lang"], purpose, now)
        if acct is None:
            return "none", None
        c.execute("UPDATE auth_codes SET consumed_at=? WHERE id=?", (now, row["id"]))
        return "ok", acct


def peek(token, purpose="login", now=None):
    """Stato di un magic link senza consumarlo, per il GET di /auth/<token>
    (i client di posta pre-aprono i link). Stessi esiti di verify() tranne
    "wrong": ok | expired | locked | none. Nessuna scrittura.

    Ritorna (state, info): info e' {"email": ..., "lang": ...} quando la riga
    esiste e non e' consumata (ok/expired/locked), altrimenti None.
    """
    if not enabled() or not token:
        return "none", None
    now = _now(now)
    with db.tx() as c:
        row = c.execute(
            "SELECT email, lang, expires_at, consumed_at, attempts "
            "FROM auth_codes WHERE token_hash=? AND purpose=?",
            (_sha(token), purpose)).fetchone()
    if row is None or row["consumed_at"] is not None:
        return "none", None
    info = {"email": row["email"], "lang": row["lang"]}
    if row["expires_at"] <= now:
        return "expired", info
    if row["attempts"] >= CODE_MAX_ATTEMPTS:
        return "locked", info
    return "ok", info


# ---------------------------------------------------------------- sessions

def open_session(account_id, device_name="", ip_hash="", now=None):
    now = _now(now)
    token = secrets.token_urlsafe(32)
    with db.tx() as c:
        c.execute(
            "INSERT INTO sessions(id, account_id, created_at, last_seen_at, expires_at, "
            "device_name, ip_hash) VALUES (?,?,?,?,?,?,?)",
            (_sha(token), account_id, now, now, now + SESSION_DAYS * 86400,
             (device_name or "")[:80], ip_hash or ""),
        )
    return token


def resolve_session(token, now=None):
    """Account della sessione (con `session_id`) o None. Rinnovo rolling.

    Se la sessione e' ancora valida e sono passati piu' di SESSION_TOUCH_SEC
    dall'ultima attivita', il rinnovo scatta sempre (anche nell'ultima ora
    di vita): e' lettura attiva, non una resurrezione, e la sessione a 90
    giorni rolling deve restare viva finche' c'e' attivita'.
    """
    if not token:
        return None
    now = _now(now)
    with db.tx() as c:
        row = c.execute(
            "SELECT s.id AS session_id, s.last_seen_at AS s_last_seen, "
            "s.expires_at AS s_expires, s.revoked_at AS s_revoked, a.* "
            "FROM sessions s JOIN accounts a ON a.id = s.account_id WHERE s.id=?",
            (_sha(token),),
        ).fetchone()
        if row is None or row["s_revoked"] is not None or row["s_expires"] <= now \
                or row["deleted_at"] is not None:
            return None
        if now - row["s_last_seen"] > SESSION_TOUCH_SEC:
            c.execute(
                "UPDATE sessions SET last_seen_at=?, expires_at=? WHERE id=?",
                (now, now + SESSION_DAYS * 86400, row["session_id"]),
            )
        d = dict(row)
        for k in ("s_last_seen", "s_expires", "s_revoked"):
            d.pop(k, None)
        return d


def revoke_session(token):
    if not token:
        return False
    with db.tx() as c:
        cur = c.execute(
            "UPDATE sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
            (int(time.time()), _sha(token)),
        )
        return cur.rowcount > 0


def revoke_all(account_id):
    with db.tx() as c:
        cur = c.execute(
            "UPDATE sessions SET revoked_at=? WHERE account_id=? AND revoked_at IS NULL",
            (int(time.time()), account_id),
        )
        return cur.rowcount


def sessions_count(account_id, now=None):
    now = _now(now)
    with db.tx() as c:
        return c.execute(
            "SELECT COUNT(*) FROM sessions WHERE account_id=? AND revoked_at IS NULL AND expires_at>?",
            (account_id, now),
        ).fetchone()[0]


def list_sessions(account_id, now=None):
    """Sessioni vive dell'account per il pannello «I tuoi dispositivi»:
    id (hash del token, mai il token), nome dispositivo, data di login e
    ultimo utilizzo. Le piu' usate di recente per prime."""
    now = _now(now)
    with db.tx() as c:
        rows = c.execute(
            "SELECT id, device_name, created_at, last_seen_at FROM sessions "
            "WHERE account_id=? AND revoked_at IS NULL AND expires_at>? "
            "ORDER BY last_seen_at DESC, created_at DESC",
            (account_id, now),
        ).fetchall()
    return [{"id": r["id"], "device_name": r["device_name"] or "",
             "created_at": int(r["created_at"]), "last_seen_at": int(r["last_seen_at"])}
            for r in rows]


def revoke_session_id(account_id, session_id):
    """Revoca per id (dal pannello dispositivi). Il vincolo sull'account e'
    nella WHERE: un id di un altro account non revoca nulla."""
    if not session_id:
        return False
    with db.tx() as c:
        cur = c.execute(
            "UPDATE sessions SET revoked_at=? WHERE id=? AND account_id=? AND revoked_at IS NULL",
            (int(time.time()), str(session_id), account_id),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------- accounts

def get(account_id):
    with db.tx() as c:
        return _row(c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())


def account_for_email(email):
    with db.tx() as c:
        return _row(c.execute(
            "SELECT * FROM accounts WHERE email=? AND deleted_at IS NULL", (_norm(email),)
        ).fetchone())


# ---------------------------------------------------------------- history

MONTH_SEC = 2629800  # 30.44 giorni


def _load_payments_file():
    if not _payments_path:
        return {}
    return load_json(_payments_path, {}, on_error=lambda e: _log(
        f"WARNING accounts: _payments.json non leggibile: {e}"))


def record_job(account_id, job_id, *, kind, book_title="", output_format="", voice="",
               lang="", paid_eur=0.0, source="forced", status="running", created_at=None,
               engine="", model=""):
    """Registra (o aggiorna) un job nello storico dell'account.

    Upsert su job_id: i campi testuali vuoti non sovrascrivono valori gia'
    presenti; paid_eur tiene il massimo; status e source seguono l'ultima
    chiamata (chi registra l'avvio conosce la verita').
    """
    if not enabled():
        return False
    now = int(time.time())
    created = int(created_at if created_at is not None else now)
    with db.tx() as c:
        c.execute(
            "INSERT INTO account_jobs(job_id, account_id, created_at, kind, book_title, "
            "output_format, voice, lang, paid_eur, status, source, download_token, updated_at, "
            "engine, model) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,'',?,?,?) "
            "ON CONFLICT(job_id) DO UPDATE SET "
            "account_id=excluded.account_id, kind=excluded.kind, "
            "book_title=CASE WHEN excluded.book_title<>'' THEN excluded.book_title ELSE account_jobs.book_title END, "
            "output_format=CASE WHEN excluded.output_format<>'' THEN excluded.output_format ELSE account_jobs.output_format END, "
            "voice=CASE WHEN excluded.voice<>'' THEN excluded.voice ELSE account_jobs.voice END, "
            "lang=CASE WHEN excluded.lang<>'' THEN excluded.lang ELSE account_jobs.lang END, "
            "paid_eur=MAX(account_jobs.paid_eur, excluded.paid_eur), "
            "engine=CASE WHEN excluded.engine<>'' THEN excluded.engine ELSE account_jobs.engine END, "
            "model=CASE WHEN excluded.model<>'' THEN excluded.model ELSE account_jobs.model END, "
            "status=excluded.status, source=excluded.source, updated_at=excluded.updated_at, "
            # Un job rilanciato torna visibile: e' di nuovo attivita' dell'utente.
            "hidden_at=CASE WHEN excluded.status='running' THEN NULL ELSE account_jobs.hidden_at END",
            (str(job_id), account_id, created, kind or "generate", (book_title or "")[:200],
             output_format or "", voice or "", (lang or "")[:8], float(paid_eur or 0),
             status or "running", source or "forced", now, (engine or "")[:16],
             (model or "")[:32]),
        )


def update_status(job_id, status, download_token=""):
    if not enabled():
        return False
    status = "cancelled" if status == "canceled" else status
    if status not in JOB_STATUSES:
        return False
    with db.tx() as c:
        if download_token:
            cur = c.execute(
                "UPDATE account_jobs SET status=?, download_token=?, updated_at=? WHERE job_id=?",
                (status, download_token, int(time.time()), str(job_id)),
            )
        else:
            cur = c.execute(
                "UPDATE account_jobs SET status=?, updated_at=? WHERE job_id=?",
                (status, int(time.time()), str(job_id)),
            )
        return cur.rowcount > 0


def settle_running(job_id, status):
    """Chiude la riga solo se e' ancora 'running': non sovrascrive mai un esito
    gia' scritto dal motore. Usata dalla riconciliazione dei job spariti."""
    if not enabled():
        return False
    status = "cancelled" if status == "canceled" else status
    if status not in JOB_STATUSES or status == "running":
        return False
    with db.tx() as c:
        cur = c.execute(
            "UPDATE account_jobs SET status=?, updated_at=? WHERE job_id=? AND status='running'",
            (status, int(time.time()), str(job_id)),
        )
        return cur.rowcount > 0


def hide_job(account_id, job_id, now=None):
    """Toglie un job dall'area personale dell'account. Solo righe proprie e
    concluse: un job "running" sta ancora lavorando. Ritorna "ok",
    "not_found" o "running". File e link di download non vengono toccati,
    salvo l'archivio: un job archiviato esce dall'archivio (libera quota) e
    da li' segue la retention ordinaria, cioe' di norma sparisce subito. Fa
    eccezione il job a cui e' collegato un libro dell'archivio dell'app: resta
    archiviato (vedi _JOB_IN_ARCHIVE) finche' il collegamento esiste."""
    if not enabled():
        return "not_found"
    with db.tx() as c:
        row = c.execute(
            "SELECT status FROM account_jobs WHERE job_id=? AND account_id=? AND hidden_at IS NULL",
            (str(job_id), account_id),
        ).fetchone()
        if row is None:
            return "not_found"
        if row["status"] == "running":
            return "running"
        linked = c.execute("SELECT 1 FROM archive_items WHERE job_id=? AND account_id=? LIMIT 1",
                           (str(job_id), account_id)).fetchone() is not None
        if linked:
            c.execute("UPDATE account_jobs SET hidden_at=? WHERE job_id=?",
                      (int(_now(now)), str(job_id)))
        else:
            c.execute("UPDATE account_jobs SET hidden_at=?, archived_at=NULL, archived_bytes=0 "
                      "WHERE job_id=?", (int(_now(now)), str(job_id)))
    _archive_cache_clear()
    return "ok"


def set_download_token(job_id, token):
    if not enabled() or not token:
        return False
    with db.tx() as c:
        cur = c.execute(
            "UPDATE account_jobs SET download_token=?, updated_at=? WHERE job_id=?",
            (token, int(time.time()), str(job_id)),
        )
        return cur.rowcount > 0


def job_owner(job_id):
    """account_id gia' proprietario della riga di storico di quel job, o None.

    record_job e' un upsert che riassegna account_id: chi registra un job in
    un punto qualunque del flusso deve prima chiedere qui se la riga e' di
    qualcun altro, altrimenti un secondo account che tocca lo stesso job_id si
    porterebbe via lo storico del primo.
    """
    if not enabled():
        return None
    with db.tx() as c:
        row = c.execute(
            "SELECT account_id FROM account_jobs WHERE job_id=?", (str(job_id),)
        ).fetchone()
    return row["account_id"] if row is not None else None


def attach_if_known(job_id, email, **fields):
    """Aggancia un job a un account SOLO se l'email ha gia' un account.

    Usato dai pagamenti: un job pagato da un utente non loggato finisce nel
    suo storico se l'account esiste. Se il job e' gia' registrato (forced),
    aggiorna solo importo e campi vuoti, senza toccare status/source.
    """
    if not enabled():
        return False
    acct = account_for_email(email)
    if acct is None:
        return False
    with db.tx() as c:
        row = c.execute("SELECT job_id FROM account_jobs WHERE job_id=?", (str(job_id),)).fetchone()
        if row is None:
            fields.setdefault("source", "payments")
            fields.setdefault("kind", "generate")
            record_job(acct["id"], job_id, **fields)
            return True
        c.execute(
            "UPDATE account_jobs SET paid_eur=MAX(paid_eur, ?), "
            "book_title=CASE WHEN book_title='' THEN ? ELSE book_title END, "
            "output_format=CASE WHEN output_format='' THEN ? ELSE output_format END, "
            "voice=CASE WHEN voice='' THEN ? ELSE voice END, "
            "engine=CASE WHEN engine='' THEN ? ELSE engine END, "
            "model=CASE WHEN model='' THEN ? ELSE model END, "
            "lang=CASE WHEN lang='' THEN ? ELSE lang END, updated_at=? WHERE job_id=?",
            (float(fields.get("paid_eur") or 0), (fields.get("book_title") or "")[:200],
             fields.get("output_format") or "", fields.get("voice") or "",
             (fields.get("engine") or "")[:16], (fields.get("model") or "")[:32],
             (fields.get("lang") or "")[:8], int(time.time()), str(job_id)),
        )
        return True


# Righe che sono un audiolibro importabile dall'app: generazione m4b/mp3 (o
# formato non registrato) e ottimizzazione con audiolibro (wizard combinato).
_AUDIOBOOK_WHERE = (
    "((kind='generate' AND LOWER(output_format) IN ('', 'm4b', 'mp3')) "
    "OR (kind='optimize' AND LOWER(output_format) IN ('m4b', 'mp3')))")


def list_jobs(account_id, page=1, per_page=50, q="", audio_only=False):
    """Storico visibile dell'account, dal piu' recente. `q` filtra sul
    titolo (sottostringa, maiuscole/minuscole indifferenti) su TUTTO lo
    storico, non sulla pagina; `audio_only` tiene i soli audiolibri."""
    if not enabled():
        return [], 0
    page = max(1, int(page or 1))
    per_page = max(1, min(200, int(per_page or 50)))
    where = ["account_id=?", "hidden_at IS NULL"]
    args = [account_id]
    q = (q or "").strip()[:100]
    if q:
        esc = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        where.append("book_title LIKE ? ESCAPE '!'")
        args.append(f"%{esc}%")
    if audio_only:
        where.append(_AUDIOBOOK_WHERE)
    cond = " AND ".join(where)
    with db.tx() as c:
        total = c.execute(f"SELECT COUNT(*) FROM account_jobs WHERE {cond}",
                          tuple(args)).fetchone()[0]
        rows = c.execute(
            f"SELECT * FROM account_jobs WHERE {cond} "
            "ORDER BY created_at DESC, job_id DESC "
            "LIMIT ? OFFSET ?",
            tuple(args) + (per_page, (page - 1) * per_page),
        ).fetchall()
    return [dict(r) for r in rows], total


def get_job(account_id, job_id):
    """Riga di storico visibile del job dell'account, o None."""
    if not enabled():
        return None
    with db.tx() as c:
        r = c.execute("SELECT * FROM account_jobs WHERE job_id=? AND account_id=? "
                      "AND hidden_at IS NULL", (str(job_id), account_id)).fetchone()
    return _row(r)


def adopt_history(account):
    """Adozione retroattiva: job pagati (_payments.json, email+job_id) e voci
    campionate con owner_email uguale. Idempotente: INSERT OR IGNORE sui job,
    link_voice ritorna False se gia' collegata."""
    if not enabled():
        return 0, 0
    email = _norm(account.get("email"))
    aid = account["id"]
    n_jobs = 0
    pays = _load_payments_file()
    now = int(time.time())
    with db.tx() as c:
        for p in pays.values():
            if not isinstance(p, dict) or _norm(p.get("email")) != email:
                continue
            jid = str(p.get("job_id") or "").strip()
            cap = p.get("captured_at") or 0
            if not jid or not cap:
                continue
            cur = c.execute(
                "INSERT OR IGNORE INTO account_jobs(job_id, account_id, created_at, kind, "
                "book_title, output_format, voice, lang, paid_eur, status, source, "
                "download_token, updated_at) VALUES (?,?,?,'generate','','','','',?,'done',"
                "'payments','',?)",
                (jid, aid, int(float(cap)), float(p.get("amount_eur") or 0), now),
            )
            n_jobs += cur.rowcount
    n_voices = 0
    if _voice_ids_for_email is not None and _link_voice is not None:
        try:
            for cid in _voice_ids_for_email(email):
                if _link_voice(cid, aid):
                    n_voices += 1
        except Exception as e:  # noqa: BLE001
            _log(f"WARNING accounts: collegamento voci fallito: {e}")
    return n_jobs, n_voices


def _unlink_voices(email):
    """Scollega dall'account le voci campionate di quell'email (best-effort).

    La voce resta viva (il suo flusso e il suo link di gestione sono
    indipendenti dall'account), ma `account_id` deve sparire: e' un
    riferimento a un account cancellato, cioe' un residuo di collegamento
    fra l'indirizzo e i dati dopo una richiesta di cancellazione."""
    if _voice_ids_for_email is None or _unlink_voice is None:
        return 0
    n = 0
    try:
        for cid in _voice_ids_for_email(email):
            try:
                if _unlink_voice(cid):
                    n += 1
            except Exception as e:  # noqa: BLE001
                _log(f"WARNING accounts: scollegamento voce fallito: {e}")
    except Exception as e:  # noqa: BLE001
        _log(f"WARNING accounts: elenco voci non disponibile: {e}")
    return n


def delete_account(account_id, now=None):
    """Cancellazione self-service: email sostituita da un segnaposto,
    sessioni revocate, storico e codici eliminati, `account_id` rimosso
    dalle voci campionate dell'indirizzo. Le voci in se' e `_payments.json`
    restano (flusso proprio / obblighi fiscali)."""
    if not enabled():
        return False
    now = _now(now)
    with db.tx() as c:
        row = c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if row is None or row["deleted_at"] is not None:
            return False
        email = row["email"]
        c.execute("DELETE FROM account_jobs WHERE account_id=?", (account_id,))
        c.execute("DELETE FROM auth_codes WHERE email=?", (email,))
        c.execute(
            "UPDATE sessions SET revoked_at=? WHERE account_id=? AND revoked_at IS NULL",
            (now, account_id),
        )
        c.execute(
            "UPDATE accounts SET email=?, deleted_at=?, plan=?, plan_source='', plan_until=NULL, "
            "free_consent_at=NULL, archive_over_since=NULL, archive_notice_stage=0, "
            "archive_notice_ids=NULL WHERE id=?",
            (f"deleted:{row['email_hash'][:16]}:{account_id}", now, PLAN_FREE, account_id),
        )
    # Fuori dalla transazione: il registro delle voci e' un file JSON e il
    # lock del DB non va tenuto durante l'I/O (stesso criterio di
    # adopt_history). Best-effort: una voce non scollegata non annulla una
    # cancellazione gia' committata.
    _unlink_voices(email)
    # Storico cancellato = archivio cancellato: i file tornano alla retention
    # ordinaria e il cleanup li rimuove.
    _archive_cache_clear()
    return True


def purge_expired(now=None):
    """Retention: storico oltre HISTORY_MONTHS per account free (o con piano
    scaduto da piu' di GRACE_DAYS) senza toccare i job che stanno nell'archivio,
    codici scaduti da >24h, sessioni scadute/revocate da >30 giorni. Ritorna i
    conteggi."""
    if not enabled():
        return {"jobs": 0, "codes": 0, "sessions": 0}
    now = _now(now)
    job_cut = now - HISTORY_MONTHS * MONTH_SEC
    grace_cut = now - GRACE_DAYS * 86400
    with db.tx() as c:
        jobs = c.execute(
            "DELETE FROM account_jobs WHERE created_at<? AND account_id IN ("
            "SELECT id FROM accounts WHERE plan='free' "
            "OR (plan_until IS NOT NULL AND plan_until<?)) "
            "AND NOT EXISTS (SELECT 1 FROM account_jobs j WHERE j.job_id=account_jobs.job_id "
            "AND " + _JOB_IN_ARCHIVE + ")",
            (job_cut, grace_cut),
        ).rowcount
        codes = c.execute(
            "DELETE FROM auth_codes WHERE expires_at<?", (now - 86400,)
        ).rowcount
        sessions = c.execute(
            "DELETE FROM sessions WHERE expires_at<? OR (revoked_at IS NOT NULL AND revoked_at<?)",
            (now - 30 * 86400, now - 30 * 86400),
        ).rowcount
    return {"jobs": jobs, "codes": codes, "sessions": sessions}


# ---------------------------------------------------------------- archivio

# Archivio dei lavori conclusi che l'utente tiene oltre la retention ordinaria.
# La quota dipende dal consenso al piano gratuito (`free_consent_at`: entrano i
# job creati da quel momento) oppure da un piano di spazio regalato attivo
# (entra tutto lo storico, anche senza consenso). Un job archiviato resta
# protetto (file locali e cold non scadono piu') indipendentemente dal piano:
# lo libera solo la cancellazione dell'account, il nascondimento del job o la
# tolleranza del cleanup (vedi archive_over_since).
PLAN_FREE = "free"
# Piani di spazio regalati dall'admin e versione dei termini del piano gratuito
# registrata con ogni consenso.
SPACE_PLANS = ("sub_5", "sub_10")
# Origini di un piano di spazio (`plan_source`): 'paid' e' riservato alla fase 2.
PLAN_SOURCES = ("paid", "gift")
FREE_TERMS_VERSION = "2026-10-21"
GIB = 1024 ** 3
MIB = 1024 ** 2
# Piano -> (variabile d'ambiente, default, unita'): letta a ogni chiamata.
_PLAN_QUOTAS = {
    PLAN_FREE: ("ABM_PLAN_FREE_MB", 512, MIB),
    "sub_5": ("ABM_PLAN_SUB5_GB", 5, GIB),
    "sub_10": ("ABM_PLAN_SUB10_GB", 10, GIB),
}
# Retention "infinita" restituita per i token di un job archiviato.
ARCHIVE_RETENTION_SEC = 100 * 365 * 86400
_ARCHIVE_CACHE_TTL_SEC = 60

_archive_cache = {"at": 0.0, "ids": frozenset()}

# Job (alias `j`) che sta nell'archivio: archiviato e visibile nell'area
# personale, oppure nascosto ma collegato a un libro dell'archivio dell'app.
_JOB_IN_ARCHIVE = (
    "j.archived_at IS NOT NULL AND (j.hidden_at IS NULL OR EXISTS ("
    "SELECT 1 FROM archive_items i WHERE i.job_id=j.job_id AND i.account_id=j.account_id))")
_archive_cache_lock = threading.Lock()


def plan_quota_bytes(plan):
    """Quota di archivio del piano in byte (0 per un piano sconosciuto)."""
    spec = _PLAN_QUOTAS.get(plan or "")
    if spec is None:
        return 0
    name, default, unit = spec
    return _env_int(name, default, floor=0) * unit


def space_plan_active(account, now=None):
    """True se l'account ha un piano di spazio (sub_5/sub_10) non scaduto:
    `plan_until` assente, oppure strettamente nel futuro."""
    if not account or account.get("plan") not in SPACE_PLANS:
        return False
    until = account.get("plan_until")
    return until is None or int(until) > _now(now)


def effective_plan(account, now=None):
    """Piano in vigore: quello di spazio se attivo, altrimenti PLAN_FREE."""
    return account["plan"] if space_plan_active(account, now) else PLAN_FREE


def gift_active(account, now=None):
    """True se il piano di spazio attivo e' un regalo dell'admin."""
    return space_plan_active(account, now) and account.get("plan_source") == "gift"


def plan_origin(account, now=None):
    """Origine del piano in vigore: "paid"/"gift" se c'e' un piano di spazio
    attivo con quella `plan_source`; altrimenti "free" (consenso al piano
    gratuito dato) o "none"."""
    if space_plan_active(account, now) and account.get("plan_source") in PLAN_SOURCES:
        return account["plan_source"]
    return "free" if account.get("free_consent_at") is not None else "none"


def _space_plan_sql(now, source=None, alias="a"):
    """Condizione SQL (tabella `alias`) di un piano di spazio attivo, con la
    stessa regola di `space_plan_active`: `plan` in SPACE_PLANS e `plan_until`
    assente o strettamente futuro. `source` (stringa o tupla di `plan_source`)
    la restringe all'origine. Ritorna (sql, args)."""
    marks = ",".join("?" * len(SPACE_PLANS))
    sql = f"{alias}.plan IN ({marks}) AND ({alias}.plan_until IS NULL OR {alias}.plan_until>?)"
    args = [*SPACE_PLANS, now]
    if source is not None:
        sources = (source,) if isinstance(source, str) else tuple(source)
        sql = f"{alias}.plan_source IN ({','.join('?' * len(sources))}) AND " + sql
        args = [*sources, *args]
    return sql, args


def archive_quota_for(account, now=None):
    """Byte di archivio di cui l'account dispone adesso: 0 se manca o e' stato
    cancellato; la quota del piano se c'e' un regalo attivo (anche senza
    consenso: l'admin lo raccoglie fuori dal sito); 0 senza consenso al piano
    gratuito; altrimenti la quota del piano in vigore (gratuito, o di spazio
    non regalato)."""
    if not account or account.get("deleted_at") is not None:
        return 0
    if gift_active(account, now):
        return plan_quota_bytes(account["plan"])
    if account.get("free_consent_at") is None:
        return 0
    return plan_quota_bytes(effective_plan(account, now))


def archive_tolerance_days():
    """Giorni di tolleranza fra l'avviso di perdita della quota e la prima
    cancellazione di libri (almeno 1)."""
    return _env_int("ABM_ARCHIVE_TOLERANCE_DAYS", 15, floor=1)


def archive_tolerance_remind_days():
    """Quanti giorni prima della fine della tolleranza parte il promemoria (0 =
    nessuno)."""
    return _env_int("ABM_ARCHIVE_TOLERANCE_REMIND_DAYS", 3, floor=0)


def format_bytes(n):
    """Dimensione leggibile per email e pagine: "380 MB" sotto 1 GiB, poi GB
    con due decimali senza zeri finali ("1.25 GB", "10 GB")."""
    n = max(0, int(n or 0))
    if n < GIB:
        return f"{n / MIB:.0f} MB"
    return f"{n / GIB:.2f}".rstrip("0").rstrip(".") + " GB"


def utc_day(epoch):
    """Data UTC `YYYY-MM-DD` di un epoch: l'unico formato di giorno di email e
    pagine dell'archivio (scadenze, ultimo giorno di un regalo)."""
    return time.strftime("%Y-%m-%d", time.gmtime(int(epoch)))


def _archive_cache_clear():
    with _archive_cache_lock:
        _archive_cache["at"] = 0.0


def _archive_active_where(now):
    """Condizione SQL (alias `a`) di un account il cui archivio e' protetto:
    ogni account vivo, qualunque sia il piano (la protezione di un job gia'
    archiviato non dipende da piano o consenso). Ritorna (sql, args)."""
    return "a.deleted_at IS NULL", []


def archived_job_ids(now=None):
    """Job archiviati e protetti, con cache di _ARCHIVE_CACHE_TTL_SEC: la
    chiama la retention di ogni token, piu' volte al minuto."""
    if not enabled():
        return frozenset()
    t = time.time()
    with _archive_cache_lock:
        if now is None and t - _archive_cache["at"] < _ARCHIVE_CACHE_TTL_SEC:
            return _archive_cache["ids"]
    cond, args = _archive_active_where(_now(now))
    with db.tx() as c:
        rows = c.execute(
            "SELECT j.job_id FROM account_jobs j JOIN accounts a ON a.id=j.account_id "
            "WHERE " + _JOB_IN_ARCHIVE + " AND " + cond,
            tuple(args)).fetchall()
    ids = frozenset(r["job_id"] for r in rows)
    if now is None:
        with _archive_cache_lock:
            _archive_cache.update(at=t, ids=ids)
    return ids


def archive_protects(job_id):
    """True se i file del job non devono scadere ne' essere cancellati."""
    if not job_id:
        return False
    try:
        return str(job_id) in archived_job_ids()
    except Exception as e:  # noqa: BLE001  DB illeggibile: nel dubbio si protegge
        _log(f"WARNING accounts: archivio non leggibile ({e}), job {job_id} protetto")
        return True


def archive_usage(account_id):
    """(byte archiviati, job archiviati) dell'account. I byte comprendono i
    libri caricati dall'app, anche quelli con l'upload ancora in corso: la
    quota e' unica per job e app."""
    if not enabled():
        return 0, 0
    with db.tx() as c:
        r = c.execute(
            "SELECT COALESCE(SUM(j.archived_bytes),0) AS b, COUNT(*) AS n FROM account_jobs j "
            "WHERE j.account_id=? AND " + _JOB_IN_ARCHIVE,
            (account_id,)).fetchone()
        up = c.execute(
            "SELECT COALESCE(SUM(size_bytes),0) FROM archive_items "
            "WHERE account_id=? AND job_id=''", (account_id,)).fetchone()[0]
    return int(r["b"]) + int(up), int(r["n"])


def archive_items_count(account_id):
    """Libri dell'app nell'archivio (upload completati e collegamenti)."""
    if not enabled():
        return 0
    with db.tx() as c:
        return int(c.execute("SELECT COUNT(*) FROM archive_items WHERE account_id=? "
                             "AND state='ready'", (account_id,)).fetchone()[0])


def archive_grace_until(account):
    """Epoch di fine tolleranza (inizio + ABM_ARCHIVE_TOLERANCE_DAYS), None se
    l'account non e' in tolleranza."""
    since = (account or {}).get("archive_over_since")
    if since is None:
        return None
    return int(since) + archive_tolerance_days() * 86400


def archive_state(account, now=None, quota=None):
    """"grace" (tolleranza aperta: quota persa con l'archivio oltre la nuova
    quota), "active" (c'e' una quota) o "none". `quota`: la quota gia' calcolata
    da `archive_quota_for`, per non ripeterne il calcolo."""
    if not account:
        return "none"
    if account.get("archive_over_since") is not None:
        return "grace"
    if quota is None:
        quota = archive_quota_for(account, now)
    return "active" if quota > 0 else "none"


def archive_status(account, now=None):
    """Riepilogo per l'area personale e per l'app, o None senza quota, senza
    archivio e senza tolleranza. `state`/`grace_until` dicono all'app se avvisare
    l'utente che dei libri solo-cloud stanno per essere tolti; `plan`,
    `plan_source` e `plan_until` descrivono il piano in vigore (vuoti se e' il
    gratuito), `free_active` se c'e' il consenso al piano gratuito."""
    if not account:
        return None
    now = _now(now)
    used, n = archive_usage(account["id"])
    items = archive_items_count(account["id"])
    quota = archive_quota_for(account, now)
    state = archive_state(account, now, quota)
    if not (quota or used or n or items) and state != "grace":
        return None
    spaced = space_plan_active(account, now)
    until = account.get("plan_until")
    return {"plan": effective_plan(account, now),
            "plan_source": (account.get("plan_source") or "") if spaced else "",
            "plan_until": int(until) if spaced and until is not None else None,
            "free_active": account.get("free_consent_at") is not None,
            "quota_bytes": quota, "used_bytes": used, "jobs": n, "items": items,
            "state": state,
            "grace_until": archive_grace_until(account) if state == "grace" else None}


def archive_candidates(now=None):
    """Job conclusi, visibili e non ancora archiviati che possono entrare
    nell'archivio, con la quota dell'account: dei job creati dal consenso al
    piano gratuito in poi, e di tutto lo storico se c'e' un regalo attivo.
    Esclusi gli account cancellati o in tolleranza e i job gia' tolti
    dall'archivio (`archive_evicted_at`). Dal piu' recente: con la quota
    stretta vince il lavoro nuovo."""
    if not enabled():
        return []
    now = _now(now)
    cond, args = _archive_active_where(now)
    gift_sql, gift_args = _space_plan_sql(now, "gift")
    with db.tx() as c:
        rows = c.execute(
            "SELECT j.job_id, j.account_id, a.plan, a.plan_source, a.plan_until, "
            "a.free_consent_at, a.deleted_at FROM account_jobs j "
            "JOIN accounts a ON a.id=j.account_id "
            "WHERE " + cond + " AND a.archive_over_since IS NULL "
            "AND j.status='done' AND j.archived_at IS NULL AND j.hidden_at IS NULL "
            "AND j.archive_evicted_at IS NULL "
            "AND ((a.free_consent_at IS NOT NULL AND j.created_at>=a.free_consent_at) "
            "OR (" + gift_sql + ")) "
            "ORDER BY j.created_at DESC, j.job_id DESC",
            (*args, *gift_args)).fetchall()
    quotas, out = {}, []
    for r in rows:
        acc = r["account_id"]
        if acc not in quotas:
            quotas[acc] = archive_quota_for(dict(r), now)
        out.append({"job_id": r["job_id"], "account_id": acc, "quota_bytes": quotas[acc]})
    return out


def job_fingerprint(job_id, token):
    """(impronta, byte) gia' calcolate per il file del job servito da
    `token`, o None se mancano o si riferiscono a un altro token."""
    if not enabled():
        return None
    with db.tx() as c:
        r = c.execute("SELECT lib_fp, lib_size, lib_token FROM account_jobs WHERE job_id=?",
                      (str(job_id),)).fetchone()
    if r is None or not r["lib_fp"] or r["lib_token"] != token:
        return None
    return r["lib_fp"], int(r["lib_size"])


def archived_job_fingerprints(account_id, now=None):
    """[{job_id, lib_fp, lib_size, lib_token}] dei job dell'account
    nell'archivio protetto (vedi archived_job_ids), dal piu' recente."""
    if not enabled():
        return []
    cond, args = _archive_active_where(_now(now))
    with db.tx() as c:
        rows = c.execute(
            "SELECT j.job_id, j.lib_fp, j.lib_size, j.lib_token FROM account_jobs j "
            "JOIN accounts a ON a.id=j.account_id "
            "WHERE j.account_id=? AND " + _JOB_IN_ARCHIVE + " AND " + cond +
            " ORDER BY j.archived_at DESC, j.job_id",
            (account_id, *args)).fetchall()
    return [dict(r) for r in rows]


def set_job_fingerprint(job_id, token, fp, size):
    if not enabled():
        return False
    with db.tx() as c:
        cur = c.execute("UPDATE account_jobs SET lib_fp=?, lib_size=?, lib_token=? WHERE job_id=?",
                        (fp or "", max(0, int(size or 0)), token or "", str(job_id)))
    return cur.rowcount > 0


def mark_archived(job_id, nbytes, now=None):
    if not enabled():
        return False
    with db.tx() as c:
        cur = c.execute(
            "UPDATE account_jobs SET archived_at=?, archived_bytes=? "
            "WHERE job_id=? AND archived_at IS NULL",
            (_now(now), max(0, int(nbytes or 0)), str(job_id)))
    _archive_cache_clear()
    return cur.rowcount > 0


def archive_accounts_to_check():
    """Account vivi su cui la tolleranza deve guardare: con un job nell'archivio,
    con un libro caricato dall'app (`job_id=''`) o con la tolleranza gia' aperta.
    Quelli cancellati li ripulisce `user_archive.sweep`."""
    if not enabled():
        return []
    cond, args = _archive_active_where(_now(None))
    with db.tx() as c:
        rows = c.execute(
            "SELECT a.* FROM accounts a WHERE " + cond + " AND (a.archive_over_since IS NOT NULL "
            "OR EXISTS (SELECT 1 FROM account_jobs j WHERE j.account_id=a.id AND " + _JOB_IN_ARCHIVE + ") "
            "OR EXISTS (SELECT 1 FROM archive_items i WHERE i.account_id=a.id AND i.job_id='')) "
            "ORDER BY a.id", tuple(args)).fetchall()
    return [dict(r) for r in rows]


def archive_entries(account_id):
    """Voci che la tolleranza puo' togliere, dalla piu' vecchia: i job nell'archivio
    (`entered_at` = ingresso nell'archivio) e i libri caricati dall'app pronti
    (`entered_at` = caricamento), sempre con byte > 0. `title` non e' mai vuoto:
    ripiega sul nome file e poi sull'id. [{kind, id, title, bytes, entered_at}]."""
    if not enabled():
        return []
    cond, args = _archive_active_where(_now(None))
    with db.tx() as c:
        jobs = c.execute(
            "SELECT j.job_id, j.book_title, j.archived_bytes, j.archived_at FROM account_jobs j "
            "JOIN accounts a ON a.id=j.account_id WHERE j.account_id=? AND " + _JOB_IN_ARCHIVE +
            " AND j.archived_bytes>0 AND " + cond, (account_id, *args)).fetchall()
        items = c.execute(
            "SELECT i.id, i.title, i.filename, i.size_bytes, i.created_at FROM archive_items i "
            "JOIN accounts a ON a.id=i.account_id WHERE i.account_id=? AND i.job_id='' "
            "AND i.state='ready' AND i.size_bytes>0 AND " + cond, (account_id, *args)).fetchall()
    out = [{"kind": "job", "id": r["job_id"], "title": r["book_title"] or r["job_id"],
            "bytes": int(r["archived_bytes"]), "entered_at": int(r["archived_at"])} for r in jobs]
    out += [{"kind": "item", "id": r["id"], "title": r["title"] or r["filename"] or r["id"],
             "bytes": int(r["size_bytes"]), "entered_at": int(r["created_at"])} for r in items]
    out.sort(key=lambda e: (e["entered_at"], e["id"]))
    return out


def set_archive_tolerance(account_id, over_since, stage, notice_ids=None):
    """Apre (`over_since` = epoch), avanza (`stage` 1 avviso inviato, 2 promemoria
    inviato) o chiude (None, 0) la tolleranza di un account vivo. `notice_ids` sono
    le chiavi (`job:<id>`/`item:<id>`) dei libri elencati dall'ultima email partita,
    salvate come array JSON ordinato; None o chiusura della tolleranza: NULL."""
    if not enabled():
        return
    ids = None if over_since is None or notice_ids is None else json.dumps(sorted(notice_ids))
    with db.tx() as c:
        c.execute("UPDATE accounts SET archive_over_since=?, archive_notice_stage=?, "
                  "archive_notice_ids=? WHERE id=? AND deleted_at IS NULL",
                  (None if over_since is None else int(over_since), int(stage), ids, account_id))


def archive_notice_keys(account):
    """Insieme delle chiavi dei libri elencati dall'ultima email di un account (riga di
    `get`), o None se non c'e' niente da confrontare: solo la colonna NULL (stato migrato,
    nessuna email mai partita con un elenco). JSON illeggibile (o non una lista di stringhe)
    vale l'insieme vuoto, cioe' "nessun libro e' stato elencato": chi chiama manda un nuovo
    avviso invece di togliere un libro che l'utente non sa di rischiare. Si registra come
    WARNING e non solleva mai."""
    raw = account.get("archive_notice_ids")
    if raw is None:
        return None
    try:
        keys = json.loads(raw)
        if isinstance(keys, list) and all(isinstance(k, str) for k in keys):
            return set(keys)
    except (TypeError, ValueError):
        pass
    _log(f"WARNING accounts: archive_notice_ids illeggibile per l'account {account.get('id')}, "
         f"trattato come vuoto (nuovo avviso prima di togliere qualcosa)")
    return set()


def evict_archived_job(job_id, now=None):
    """Toglie il job dall'archivio: finisce la protezione e i suoi file tornano
    alla retention ordinaria. La riga di storico resta (`archive_evicted_at`).
    True se il job era nell'archivio."""
    if not enabled():
        return False
    with db.tx() as c:
        cur = c.execute(
            "UPDATE account_jobs SET archived_at=NULL, archived_bytes=0, archive_evicted_at=? "
            "WHERE job_id=? AND archived_at IS NOT NULL", (_now(now), str(job_id)))
    _archive_cache_clear()
    return cur.rowcount > 0


ADMIN_PLAN_FILTERS = (PLAN_FREE, *SPACE_PLANS)
ADMIN_ORIGINS = (*PLAN_SOURCES, "free", "none")
# Ordinamenti dell'elenco: registrazione (piu' recenti prima) o riempimento dell'archivio.
ADMIN_SORTS = ("recent", "fill")
# Account vivo nella tolleranza del cleanup dell'archivio (alias `a`).
_ADMIN_TOLERANCE_SQL = "a.deleted_at IS NULL AND a.archive_over_since IS NOT NULL"
# Casella degli aggregati -> filtri di `_admin_where` che la console applica
# al clic: il numero della casella e' il conteggio di quelle stesse righe.
# "last30" (date_from = mezzanotte UTC di 30 giorni fa) si calcola a parte.
_ADMIN_AGGREGATES = (
    ("total", {}),
    ("with_session", {"state": "active"}),
    ("never_logged", {"state": "never"}),
    ("deleted", {"state": "deleted"}),
    ("paid", {"origin": "paid"}),
    ("gift", {"origin": "gift"}),
    ("free_active", {"origin": "free"}),
    ("in_tolerance", {"tolerance": True}),
)


def _admin_state_where(state, now):
    """Condizioni SQL (alias `a`) del filtro per stato della console admin,
    come ([sql, ...], [args]): `active` = account vivo con almeno una sessione
    valida, `dormant` = account vivo senza, `never` = vivo e mai entrato,
    `deleted` = cancellato. Altri valori non filtrano."""
    live_session = ("EXISTS (SELECT 1 FROM sessions s WHERE s.account_id=a.id "
                    "AND s.revoked_at IS NULL AND s.expires_at>?)")
    if state == "active":
        return ["a.deleted_at IS NULL AND " + live_session], [now]
    if state == "dormant":
        return ["a.deleted_at IS NULL AND NOT " + live_session], [now]
    if state == "deleted":
        return ["a.deleted_at IS NOT NULL"], []
    if state == "never":
        return ["a.deleted_at IS NULL AND a.last_login_at IS NULL"], []
    return [], []


def _admin_plan_where(plan, origin, now):
    """Condizioni SQL (alias `a`) dei filtri per piano effettivo e per origine
    della console admin, come ([sql, ...], [args]). Valori sconosciuti non
    filtrano, come `state`. `plan=free` e ogni `origin` valgono solo per gli
    account vivi (un account cancellato torna a `free`, ma non ha piano ne'
    origine), come gli aggregati."""
    where, args = [], []
    if plan in SPACE_PLANS:
        sql, a = _space_plan_sql(now)
        where.append(sql + " AND a.plan=?")
        args += [*a, plan]
    elif plan == PLAN_FREE:
        sql, a = _space_plan_sql(now)
        where.append("a.deleted_at IS NULL AND NOT (" + sql + ")")
        args += a
    if origin in PLAN_SOURCES:
        sql, a = _space_plan_sql(now, origin)
        where.append("a.deleted_at IS NULL AND " + sql)
        args += a
    elif origin in ("free", "none"):
        sql, a = _space_plan_sql(now, PLAN_SOURCES)
        where.append("a.deleted_at IS NULL AND NOT (" + sql + ") AND a.free_consent_at IS "
                     + ("NOT NULL" if origin == "free" else "NULL"))
        args += a
    return where, args


def _admin_where(now, state="all", q="", date_from=None, date_to=None,
                 plan="", origin="", tolerance=False):
    """Condizioni SQL (alias `a`) di tutti i filtri della console admin, in AND,
    come ([sql, ...], [args]): le usano sia l'elenco sia gli aggregati."""
    where, args = _admin_state_where(state, now)
    if q:
        where.append("(LOWER(a.email) LIKE ? OR a.id LIKE ?)")
        like = "%" + str(q).strip().lower() + "%"
        args += [like, like]
    if date_from:
        where.append("a.created_at>=?")
        args.append(int(date_from))
    if date_to:
        where.append("a.created_at<?")
        args.append(int(date_to))
    plan_where, plan_args = _admin_plan_where(plan, origin, now)
    where += plan_where
    args += plan_args
    if tolerance:
        where.append(_ADMIN_TOLERANCE_SQL)
    return where, args


def _admin_fill_key(rec):
    """Chiave dell'ordinamento per riempimento: occupazione della quota; un
    archivio senza quota (regalo revocato, consenso assente) vale piu' di ogni
    quota piena, nessun archivio e nessuna quota va in fondo."""
    used, quota = rec["archive_bytes"] or 0, rec["archive_quota_bytes"]
    if quota:
        return used / quota
    return math.inf if used else -1.0


def admin_list(state="all", q="", date_from=None, date_to=None,
               limit=500, offset=0, now=None, plan="", origin="", tolerance=False,
               sort="recent"):
    """Elenco account per la console admin: registrazione, ultimo accesso,
    cancellazione, sessioni attive e storico.

    `state`: all | active (account vivo con una sessione valida) | deleted |
    never (mai entrati) | dormant (nessuna sessione valida, account vivo). `q`
    filtra sull'email (substring, case-insensitive); sugli account cancellati
    l'email e' gia' un segnaposto `deleted:...`, quindi la ricerca li trova
    solo per id. `date_from`/`date_to` sono epoch sulla data di registrazione.
    `plan` (free | sub_5 | sub_10) filtra sul piano effettivo; `origin`
    (paid | gift | free | none) sull'origine: `paid`/`gift` = piano di spazio
    attivo con quella `plan_source`, `free` = nessun piano attivo e consenso al
    piano gratuito, `none` = nessun piano attivo e nessun consenso.
    `tolerance` tiene solo gli account vivi nella tolleranza dell'archivio.
    `sort`: recent (registrazione, piu' recenti prima; default) | fill
    (riempimento dell'archivio, piu' pieni prima, vedi `_admin_fill_key`).
    Ogni record porta `archive_fill_pct`, l'occupazione della quota in
    percento (None senza quota).

    Ritorna {"records": [...], "count": <totale filtrato>, "plans": [...],
    "origins": [...], "aggregates": {...}, "last30_since": "YYYY-MM-DD"}: ogni
    aggregato conta le righe del filtro corrispondente (`_ADMIN_AGGREGATES`),
    "last30" quelle con `date_from` = `last30_since`, mezzanotte UTC.
    """
    if not enabled():
        return {"records": [], "count": 0, "aggregates": {}}
    now = _now(now)
    limit = max(1, min(int(limit or 500), 2000))
    offset = max(0, int(offset or 0))
    where, args = _admin_where(now, state, q, date_from, date_to, plan, origin, tolerance)
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    since30 = (now - 30 * 86400) // 86400 * 86400

    sel = (
        "SELECT a.id, a.email, a.email_hash, a.lang, a.plan, a.plan_source, a.plan_until, "
        "a.free_consent_at, a.archive_over_since, a.created_at, a.last_login_at, a.deleted_at, "
        "(SELECT COUNT(*) FROM sessions s WHERE s.account_id=a.id "
        " AND s.revoked_at IS NULL AND s.expires_at>?) AS sessions_active, "
        "(SELECT MAX(s.last_seen_at) FROM sessions s WHERE s.account_id=a.id) AS last_seen_at, "
        "(SELECT COUNT(*) FROM account_jobs j WHERE j.account_id=a.id) AS jobs, "
        "(SELECT COALESCE(SUM(j.paid_eur),0) FROM account_jobs j WHERE j.account_id=a.id) AS paid_eur, "
        "(SELECT COALESCE(SUM(j.archived_bytes),0) FROM account_jobs j WHERE j.account_id=a.id "
        " AND " + _JOB_IN_ARCHIVE + ") + "
        "(SELECT COALESCE(SUM(i.size_bytes),0) FROM archive_items i WHERE i.account_id=a.id "
        " AND i.job_id='') AS archive_bytes "
        "FROM accounts a " + sql_where +
        " ORDER BY a.created_at DESC, a.id DESC"
    )
    # La quota viene da `archive_quota_for`, non dal DB: per riempimento si
    # leggono tutte le righe filtrate e la pagina si taglia dopo l'ordinamento.
    by_fill = sort == "fill"
    page = [] if by_fill else [limit, offset]
    if not by_fill:
        sel += " LIMIT ? OFFSET ?"
    with db.tx() as c:
        def count(cond, cargs):
            sql = "SELECT COUNT(*) FROM accounts a" + (" WHERE " + " AND ".join(cond) if cond else "")
            return int(c.execute(sql, tuple(cargs)).fetchone()[0])

        total = count(where, args)
        rows = c.execute(sel, tuple([now] + args + page)).fetchall()
        # Aggregati sull'intera anagrafica (non sul filtro): servono da
        # cruscotto e da filtri rapidi, non da conteggio della pagina mostrata.
        aggregates = {key: count(*_admin_where(now, **kw)) for key, kw in _ADMIN_AGGREGATES}
        aggregates["last30"] = count(*_admin_where(now, date_from=since30))
        aggregates["filtered"] = total

    recs = []
    for r in rows:
        d = dict(r)
        deleted = d.get("deleted_at") is not None
        if deleted:
            # L'indirizzo e' gia' stato sostituito da `delete_account`: non
            # c'e' nulla da mostrare oltre all'hash troncato del segnaposto.
            d["email"] = ""
        if deleted:
            d["state"] = "deleted"
        elif not d.get("last_login_at"):
            d["state"] = "never"
        elif not d.get("sessions_active"):
            d["state"] = "dormant"
        else:
            d["state"] = "active"
        d["paid_eur"] = round(float(d.get("paid_eur") or 0), 2)
        d["archive_quota_bytes"] = quota = archive_quota_for(d, now)
        d["archive_fill_pct"] = round((d["archive_bytes"] or 0) * 100 / quota, 1) if quota else None
        d["plan_effective"] = effective_plan(d, now)
        d["origin"] = plan_origin(d, now)
        d["archive_grace_until"] = archive_grace_until(d)
        d.pop("email_hash", None)
        recs.append(d)
    if by_fill:
        # sort stabile: a parita' resta l'ordine di registrazione della query.
        recs.sort(key=_admin_fill_key, reverse=True)
        recs = recs[offset:offset + limit]
    return {
        "records": recs,
        "count": total,
        "plans": list(ADMIN_PLAN_FILTERS),
        "origins": list(ADMIN_ORIGINS),
        "aggregates": aggregates,
        "last30_since": utc_day(since30),
    }


# ---------------------------------------------------------------- piano gratuito

# Il piano gratuito (archivio da `plan_quota_bytes(PLAN_FREE)`) si attiva solo
# con il consenso dell'utente: lo si propone una volta (`free_offer_at`) e ogni
# scelta resta nel registro `plan_consents`. `migration` e `subscription` sono
# sorgenti valide nel registro ma le scrivono solo la migrazione dei dati e
# `set_paid_plan` (sottoscrivere un abbonamento vale come consenso), mai questa
# funzione.
FREE_PLAN_ACTIONS = ("activate", "decline", "deactivate")
FREE_CONSENT_SOURCES = ("prompt", "account")


def _free_plan_offerable(account, now):
    """True se il piano gratuito ha senso per l'account: vivo, senza consenso,
    quota gratuita maggiore di 0 e nessun regalo attivo (con un regalo l'offerta
    non compare e ricompare, senza consenso, al primo accesso dopo la scadenza)."""
    if not account or account.get("deleted_at") is not None:
        return False
    if account.get("free_consent_at") is not None:
        return False
    if plan_quota_bytes(PLAN_FREE) <= 0:      # quota azzerata da env: niente da offrire
        return False
    return not gift_active(account, now)


def free_offer_pending(account, now=None):
    """True se all'utente va proposto il piano gratuito (la proposta una tantum):
    offerta sensata e mai fatta."""
    return _free_plan_offerable(account, now) and account.get("free_offer_at") is None


def free_nudge_pending(account, now=None):
    """True se all'utente va ricordato il piano gratuito (il fumetto della SPA):
    offerta sensata ma gia' fatta, cioe' rifiutata o con il consenso ritirato.
    La cadenza del promemoria la decide la SPA."""
    return _free_plan_offerable(account, now) and account.get("free_offer_at") is not None


def free_plan_action(account_id, action, source, now=None):
    """Registra la scelta dell'utente sul piano gratuito e ritorna l'account
    aggiornato (None se manca o e' stato cancellato).

    `activate` da' il consenso (riga `grant`), `decline` chiude la proposta senza
    consenso (riga `decline`), `deactivate` ritira il consenso (riga `withdraw`).
    Le azioni che non cambiano nulla non scrivono righe: attivare con il consenso
    gia' dato, ritirarlo quando manca, rifiutare con il consenso dato o a proposta
    gia' chiusa (`free_offer_at`: la riga `decline` e' la prima risposta, non una
    per ogni click). Con un abbonamento attivo (`plan_origin` "paid") `deactivate`
    non fa nulla: il consenso fa parte dell'abbonamento e ritirarlo azzererebbe la
    quota di chi sta pagando. Lettura e scrittura stanno nella stessa
    transazione: un doppio click non duplica righe. ValueError su azione o
    sorgente sconosciute."""
    if action not in FREE_PLAN_ACTIONS:
        raise ValueError(f"unknown free plan action: {action!r}")
    if source not in FREE_CONSENT_SOURCES:
        raise ValueError(f"unknown free plan source: {source!r}")
    now = _now(now)
    with db.tx() as c:
        row = _live_account(c, account_id)
        if row is None:
            return None
        has_consent = row["free_consent_at"] is not None
        if action == "deactivate" and plan_origin(row, now) == "paid":
            return row
        if action == "activate" and not has_consent:
            c.execute("UPDATE accounts SET free_consent_at=?, free_consent_version=?, "
                      "free_offer_at=COALESCE(free_offer_at, ?) WHERE id=?",
                      (now, FREE_TERMS_VERSION, now, account_id))
            _insert_consents(c, [(account_id, now, "grant", FREE_TERMS_VERSION, source)])
        elif action == "decline" and not has_consent and row["free_offer_at"] is None:
            c.execute("UPDATE accounts SET free_offer_at=? WHERE id=?", (now, account_id))
            _insert_consents(c, [(account_id, now, "decline", "", source)])
        elif action == "deactivate" and has_consent:
            c.execute("UPDATE accounts SET free_consent_at=NULL, free_consent_version='' WHERE id=?",
                      (account_id,))
            _insert_consents(c, [(account_id, now, "withdraw", "", source)])
        return _row(c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())


# ---------------------------------------------------------------- piani regalati

# Un piano di spazio (sub_5/sub_10) regalato dall'admin vale fino a `plan_until`
# (epoch; NULL = senza scadenza, il caso dei regali migrati) e non registra
# consensi: l'admin lo concorda fuori dal sito. Alla scadenza o alla revoca
# l'account torna a `free`/''/NULL; l'archivio che eccede la quota segue la
# tolleranza del cleanup.

def _reset_plan(c, account_id):
    c.execute("UPDATE accounts SET plan=?, plan_source='', plan_until=NULL WHERE id=?",
              (PLAN_FREE, account_id))


def _live_account(c, account_id):
    """Riga dell'account (dict) o None se manca o e' stato cancellato."""
    row = _row(c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())
    return None if row is None or row["deleted_at"] is not None else row


def gift_plan(account_id, plan, until, now=None):
    """Regala il piano di spazio `plan` fino a `until` (epoch intero, nel
    futuro). ValueError su piano sconosciuto o `until` non intero o non futuro.
    Il regalo si fa solo con origine "free" o "none" (`plan_origin`).

    Ritorna (esito, account): "ok" (account aggiornato), "not_found" (assente,
    cancellato o account disattivati, None), "paid" (c'e' un piano pagato
    attivo: non si sovrascrive) o "gift" (c'e' gia' un regalo attivo: va
    revocato prima di farne un altro); negli ultimi due l'account e'
    invariato. Lettura e scrittura nella stessa transazione."""
    if plan not in SPACE_PLANS:
        raise ValueError(f"unknown space plan: {plan!r}")
    now = _now(now)
    if isinstance(until, bool) or not isinstance(until, int) or until <= now:
        raise ValueError(f"gift end must be a future epoch: {until!r}")
    if not enabled():
        return "not_found", None
    with db.tx() as c:
        acct = _live_account(c, account_id)
        if acct is None:
            return "not_found", None
        origin = plan_origin(acct, now)
        if origin in PLAN_SOURCES:
            return origin, acct
        c.execute("UPDATE accounts SET plan=?, plan_source='gift', plan_until=? WHERE id=?",
                  (plan, until, account_id))
        acct = _live_account(c, account_id)
    _archive_cache_clear()
    return "ok", acct


def revoke_gift(account_id, now=None):
    """Toglie il piano regalato e riporta l'account a `free`. Ritorna (esito,
    account): "ok", "not_found" (assente, cancellato o account disattivati) o
    "not_gift" (il piano non e' un regalo: un piano pagato non si revoca da qui)."""
    if not enabled():
        return "not_found", None
    with db.tx() as c:
        acct = _live_account(c, account_id)
        if acct is None:
            return "not_found", None
        if acct["plan_source"] != "gift":
            return "not_gift", acct
        _reset_plan(c, account_id)
        acct = _live_account(c, account_id)
    _archive_cache_clear()
    return "ok", acct


def expire_gifts(now=None):
    """Riporta a `free` i regali con `plan_until <= now` (quelli senza scadenza
    restano); ritorna quanti. I piani pagati scaduti non si toccano qui."""
    if not enabled():
        return 0
    now = _now(now)
    with db.tx() as c:
        ids = [r[0] for r in c.execute(
            "SELECT id FROM accounts WHERE plan_source='gift' "
            "AND plan_until IS NOT NULL AND plan_until<=?", (now,))]
        for account_id in ids:
            _reset_plan(c, account_id)
    if ids:
        _archive_cache_clear()
    return len(ids)


# ---------------------------------------------------------------- piani pagati

# Il piano di un abbonamento lo scrive solo `subscriptions` attraverso queste due
# funzioni: `plan_until` e' la fine del periodo pagato (piu' la grazia per i
# rinnovi in corso), quindi quota e tolleranza seguono le stesse regole dei
# regali. Il pagato sovrascrive un regalo attivo (il regalo non torna).

def set_paid_plan(account_id, plan, until, now=None):
    """Mette l'account sul piano pagato `plan` fino a `until` (epoch intero).
    Sottoscrivere vale come consenso alla conservazione: se il consenso al
    piano gratuito manca lo registra (riga `grant`, sorgente `subscription`)
    nella stessa transazione. Ritorna "ok" o "not_found" (assente, cancellato o
    account disattivati). ValueError su piano sconosciuto o `until` non intero."""
    if plan not in SPACE_PLANS:
        raise ValueError(f"unknown space plan: {plan!r}")
    if isinstance(until, bool) or not isinstance(until, int):
        raise ValueError(f"paid plan end must be an epoch: {until!r}")
    if not enabled():
        return "not_found"
    now = _now(now)
    with db.tx() as c:
        acct = _live_account(c, account_id)
        if acct is None:
            return "not_found"
        c.execute("UPDATE accounts SET plan=?, plan_source='paid', plan_until=? WHERE id=?",
                  (plan, until, account_id))
        if acct["free_consent_at"] is None:
            c.execute("UPDATE accounts SET free_consent_at=?, free_consent_version=?, "
                      "free_offer_at=COALESCE(free_offer_at, ?) WHERE id=?",
                      (now, FREE_TERMS_VERSION, now, account_id))
            _insert_consents(c, [(account_id, now, "grant", FREE_TERMS_VERSION, "subscription")])
    _archive_cache_clear()
    return "ok"


def end_paid_plan(account_id):
    """Riporta a `free` un piano pagato (fine dell'abbonamento). False se il
    piano in colonna non e' pagato: un regalo arrivato dopo resta com'e'."""
    if not enabled():
        return False
    with db.tx() as c:
        acct = _live_account(c, account_id)
        if acct is None or acct["plan_source"] != "paid":
            return False
        _reset_plan(c, account_id)
    _archive_cache_clear()
    return True
