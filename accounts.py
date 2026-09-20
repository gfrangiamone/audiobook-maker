# accounts.py
"""Account opzionali: magic link + codice a 6 cifre, sessioni, storico job.

Modulo foglia: dipende solo da `db` e dalla stdlib. Lo stato dell'app
(percorso di `_payments.json`, funzioni di voice_clone, logger) arriva via
`configure()`. Nessuna email in chiaro nei log: usare `email_hash()`.
"""
import hashlib
import hmac
import json
import os
import secrets
import time

import db


def _env_int(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


ENABLE = os.environ.get("ABM_ACCOUNT_ENABLE", "1").strip().lower() not in ("0", "false", "no", "off")
SESSION_DAYS = _env_int("ABM_ACCOUNT_SESSION_DAYS", 90)
CODE_TTL_MIN = _env_int("ABM_ACCOUNT_CODE_TTL_MIN", 10)
CODE_MAX_ATTEMPTS = _env_int("ABM_ACCOUNT_CODE_MAX_ATTEMPTS", 5)
HISTORY_MONTHS = _env_int("ABM_ACCOUNT_HISTORY_MONTHS", 24)
GRACE_DAYS = _env_int("ABM_ACCOUNT_GRACE_DAYS", 90)

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
_log = print


def configure(*, payments_path=None, voice_clone_ids_for_email_fn=None,
              link_voice_fn=None, log_fn=None):
    global _payments_path, _voice_ids_for_email, _link_voice, _log
    if payments_path is not None:
        _payments_path = str(payments_path)
    if voice_clone_ids_for_email_fn is not None:
        _voice_ids_for_email = voice_clone_ids_for_email_fn
    if link_voice_fn is not None:
        _link_voice = link_voice_fn
    if log_fn is not None:
        _log = log_fn


def enabled():
    return bool(ENABLE) and db.is_ready()


def init_schema():
    db.migrate("accounts_v1", SCHEMA)


# ---------------------------------------------------------------- helpers

def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _norm(email):
    return (email or "").strip().lower()


def email_hash(email):
    return _sha(_norm(email))


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
        code = f"{secrets.randbelow(10**6):06d}"
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


# ---------------------------------------------------------------- accounts

def get(account_id):
    with db.tx() as c:
        return _row(c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())


def account_for_email(email):
    with db.tx() as c:
        return _row(c.execute(
            "SELECT * FROM accounts WHERE email=? AND deleted_at IS NULL", (_norm(email),)
        ).fetchone())


# ---------------------------------------------------------------- history (Task 3)

def adopt_history(account):
    """Adozione retroattiva: completata nel Task 3. Qui non fa nulla."""
    return 0, 0
