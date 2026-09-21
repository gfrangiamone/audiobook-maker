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


def init_schema():
    db.migrate("accounts_v1", SCHEMA)
    db.migrate("account_jobs_plan_v1", JOBS_PLAN_MIGRATION)


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
    if not _payments_path or not os.path.exists(_payments_path):
        return {}
    try:
        with open(_payments_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        _log(f"WARNING accounts: _payments.json non leggibile: {e}")
        return {}
    return data if isinstance(data, dict) else {}


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
            "status=excluded.status, source=excluded.source, updated_at=excluded.updated_at",
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


def list_jobs(account_id, page=1, per_page=50):
    if not enabled():
        return [], 0
    page = max(1, int(page or 1))
    per_page = max(1, min(200, int(per_page or 50)))
    with db.tx() as c:
        total = c.execute(
            "SELECT COUNT(*) FROM account_jobs WHERE account_id=?", (account_id,)
        ).fetchone()[0]
        rows = c.execute(
            "SELECT * FROM account_jobs WHERE account_id=? ORDER BY created_at DESC, job_id DESC "
            "LIMIT ? OFFSET ?",
            (account_id, per_page, (page - 1) * per_page),
        ).fetchall()
    return [dict(r) for r in rows], total


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
            "UPDATE accounts SET email=?, deleted_at=? WHERE id=?",
            (f"deleted:{row['email_hash'][:16]}:{account_id}", now, account_id),
        )
    # Fuori dalla transazione: il registro delle voci e' un file JSON e il
    # lock del DB non va tenuto durante l'I/O (stesso criterio di
    # adopt_history). Best-effort: una voce non scollegata non annulla una
    # cancellazione gia' committata.
    _unlink_voices(email)
    return True


def purge_expired(now=None):
    """Retention: storico oltre HISTORY_MONTHS per account free (o con piano
    scaduto da piu' di GRACE_DAYS), codici scaduti da >24h, sessioni
    scadute/revocate da >30 giorni. Ritorna i conteggi."""
    if not enabled():
        return {"jobs": 0, "codes": 0, "sessions": 0}
    now = _now(now)
    job_cut = now - HISTORY_MONTHS * MONTH_SEC
    grace_cut = now - GRACE_DAYS * 86400
    with db.tx() as c:
        jobs = c.execute(
            "DELETE FROM account_jobs WHERE created_at<? AND account_id IN ("
            "SELECT id FROM accounts WHERE plan='free' "
            "OR (plan_until IS NOT NULL AND plan_until<?))",
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
