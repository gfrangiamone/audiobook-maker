# subscriptions.py
"""Abbonamenti mensili (spazio cloud + voucher): stato, periodi, pagamenti.

Dominio indipendente dal fornitore: parla con un adattatore (`billing_paypal`)
attraverso un'interfaccia minima e riflette il piano in vigore su
`accounts.plan/plan_source/plan_until` con `set_paid_plan`/`end_paid_plan`,
cosi' quota e tolleranza dell'archivio non cambiano. Tabelle in SQLite (`db`).
Spec: docs/superpowers/specs/2026-10-20-abbonamenti-design.md.

Lo stato remoto letto con `fetch` e' la fonte di verita': il webhook e' il
segnale veloce (`handle_event`), il giro di riconciliazione (`sweep`, dal loop
di cleanup) recupera quello che il webhook perde. Un pagamento si registra una
volta sola (`subscription_payments`) e da' un solo voucher (chiave
`<provider>:<payment_id>`); un pagamento che non doveva arrivare (dopo una
richiesta di disdetta, su un abbonamento chiuso o in piu') si rimborsa.
"""
import calendar
import secrets
import time
from datetime import datetime, timezone

import accounts
import billing_paypal
import db
import email_service
import payment
import retry_util
from env_utils import env_bool, env_float, env_int


# Stati di una riga `subscriptions`:
# - pending: checkout creato, approvazione non ancora data;
# - activating: approvato dal fornitore, primo pagamento non ancora confermato;
# - active: periodo pagato in corso;
# - past_due: rinnovo non riuscito, il fornitore ritenta (benefici per la grazia);
# - cancelled: disdetto, benefici fino alla fine del periodo pagato;
# - ended: chiuso (scaduto, sospeso dal fornitore, disdetto e finito);
# - abandoned: checkout mai approvato, o sostituito da un altro checkout.
STATUSES = ("pending", "activating", "active", "past_due", "cancelled", "ended", "abandoned")
LIVE = ("activating", "active", "past_due", "cancelled")
SUB_TERMS_VERSION = "2026-10-23"

# `subscription_events` rende idempotenti i webhook (id evento del fornitore);
# `subscription_payments` registra ogni pagamento una volta sola e il voucher che
# ha generato: `state` e' completed | rejected (rimborsato da noi: non doveva
# arrivare) | refunded | reversed. Un solo abbonamento vivo per account.
SCHEMA_V1 = [
    """CREATE TABLE IF NOT EXISTS subscriptions (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        external_id TEXT,
        plan TEXT NOT NULL,
        status TEXT NOT NULL,
        approve_url TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        approved_at INTEGER,
        activated_at INTEGER,
        period_start INTEGER,
        period_end INTEGER,
        cancel_requested_at INTEGER,
        cancel_reason TEXT NOT NULL DEFAULT '',
        cancel_confirmed_at INTEGER,
        ended_at INTEGER,
        next_check_at INTEGER NOT NULL DEFAULT 0,
        check_failures INTEGER NOT NULL DEFAULT 0,
        terms_version TEXT NOT NULL,
        withdrawal_waived_at INTEGER NOT NULL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_subscriptions_external "
    "ON subscriptions(provider, external_id) WHERE external_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_subscriptions_one_live ON subscriptions(account_id) "
    "WHERE status IN ('activating','active','past_due','cancelled')",
    "CREATE INDEX IF NOT EXISTS ix_subscriptions_check ON subscriptions(next_check_at)",
    """CREATE TABLE IF NOT EXISTS subscription_events (
        provider TEXT NOT NULL,
        event_id TEXT NOT NULL,
        type TEXT NOT NULL,
        external_id TEXT NOT NULL DEFAULT '',
        received_at INTEGER NOT NULL,
        processed_at INTEGER,
        outcome TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (provider, event_id)
    )""",
    """CREATE TABLE IF NOT EXISTS subscription_payments (
        provider TEXT NOT NULL,
        payment_id TEXT NOT NULL,
        subscription_id TEXT NOT NULL,
        amount_eur REAL NOT NULL,
        paid_at INTEGER NOT NULL,
        period_start INTEGER NOT NULL,
        period_end INTEGER NOT NULL,
        state TEXT NOT NULL,
        voucher_code TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL,
        PRIMARY KEY (provider, payment_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_subscription_payments_sub ON subscription_payments(subscription_id)",
]


def init_schema():
    db.migrate("subscriptions_v1", SCHEMA_V1)


def _ready():
    """True se il DB e' aperto e ha le tabelle degli abbonamenti (la app le
    crea all'avvio; un DB con il solo schema degli account non ha abbonamenti)."""
    if not db.is_ready():
        return False
    with db.tx() as c:
        return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='subscriptions'"
                         ).fetchone() is not None


# ---------------------------------------------------------------- configurazione

PROVIDERS = {"paypal": billing_paypal}      # i test sostituiscono la voce
DEFAULT_PROVIDER = "paypal"
PRICE_ENV = {"sub_5": ("ABM_SUB5_PRICE_EUR", 5.0), "sub_10": ("ABM_SUB10_PRICE_EUR", 10.0)}
VOUCHER_ENV = {"sub_5": ("ABM_SUB5_VOUCHER_EUR", 5.0), "sub_10": ("ABM_SUB10_VOUCHER_EUR", 10.0)}
SWEEP_BATCH = 50                 # righe controllate per giro
ABANDONED_WATCH_SEC = 7 * 86400  # un checkout abbandonato si sorveglia ancora (link vecchio approvato)
# Approvato ma senza pagamento confermato: PayPal elenca la transazione qualche
# secondo dopo il ritorno, quindi nella prima ora la riga si ricontrolla a ogni
# minuto (poi ogni 10); chi guarda la pagina la fa ricontrollare subito (`poke`),
# al piu' ogni POKE_MIN_SEC.
ACTIVATING_RECHECK_SEC = 60
ACTIVATING_FAST_SEC = 3600
POKE_MIN_SEC = 15
_DAY = 86400

_cfg = {"log_activity": None}
_sweep_state = {"at": 0}


def configure(*, log_activity=None):
    """`log_activity(op, detail)`: riga nel log attivita' della app (opzionale)."""
    _cfg["log_activity"] = log_activity


def _now(now):
    return int(time.time() if now is None else now)


def price_eur(plan):
    """Canone mensile del piano (EUR)."""
    name, default = PRICE_ENV[plan]
    return round(env_float(name, default, floor=0.5), 2)


def voucher_eur(plan):
    """Importo del voucher emesso a ogni periodo pagato del piano (EUR)."""
    name, default = VOUCHER_ENV[plan]
    return round(env_float(name, default, floor=0.0), 2)


def _past_due_sec():
    return env_int("ABM_SUB_PAST_DUE_DAYS", 10, floor=0) * _DAY


def _voucher_days():
    return env_int("ABM_SUB_VOUCHER_DAYS", 30, floor=1)


def _checkout_ttl():
    return env_int("ABM_SUB_CHECKOUT_TTL_SEC", 10800, floor=600)


def _reconcile_sec():
    return env_int("ABM_SUB_RECONCILE_SEC", 60, floor=60)


def _provider(name=DEFAULT_PROVIDER):
    return PROVIDERS[name]


def enabled():
    """True se si possono sottoscrivere nuovi abbonamenti. Webhook e
    riconciliazione lavorano comunque sugli abbonamenti esistenti."""
    return bool(env_bool("ABM_SUBSCRIPTIONS_ENABLE", False) and accounts.enabled()
                and _provider().available())


def plan_offer():
    """Piani in vendita: canone, voucher e spazio."""
    return [{"plan": p, "price_eur": price_eur(p), "voucher_eur": voucher_eur(p),
             "quota_bytes": accounts.plan_quota_bytes(p)} for p in accounts.SPACE_PLANS]


def _log(op, detail=""):
    print(f"[subscriptions] {op} {detail}".rstrip(), flush=True)
    fn = _cfg["log_activity"]
    if fn is not None:
        try:
            fn(op, detail)
        except Exception as e:  # noqa: BLE001 - il log non deve fermare un pagamento
            print(f"[subscriptions] log_activity: {type(e).__name__}: {e}", flush=True)


def _alert(kind, **details):
    """Email all'admin per un caso da guardare a mano (best-effort)."""
    _log(f"SUB_ALERT:{kind}", " ".join(f"{k}={v}" for k, v in details.items()))
    try:
        email_service.admin_notify_subscription(kind, details)
    except Exception as e:  # noqa: BLE001
        print(f"[subscriptions] alert {kind} non inviato: {type(e).__name__}: {e}", flush=True)


def _add_month(ts):
    """Stesso istante un mese di calendario dopo (giorno limitato a fine mese)."""
    d = datetime.fromtimestamp(int(ts), timezone.utc)
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    day = min(d.day, calendar.monthrange(year, month)[1])
    return int(d.replace(year=year, month=month, day=day).timestamp())


# ---------------------------------------------------------------- righe

def _one(c, sql, args):
    r = c.execute(sql, args).fetchone()
    return dict(r) if r is not None else None


def _get(c, sub_id):
    return _one(c, "SELECT * FROM subscriptions WHERE id=?", (sub_id,))


def get(sub_id):
    with db.tx() as c:
        return _get(c, sub_id)


def _live_row(c, account_id, exclude=None):
    marks = ",".join("?" * len(LIVE))
    return _one(c, f"SELECT * FROM subscriptions WHERE account_id=? AND status IN ({marks}) "
                   "AND id<>?", (account_id, *LIVE, exclude or ""))


def _update(c, sub_id, now, **cols):
    cols["updated_at"] = now
    sets = ", ".join(f"{k}=?" for k in cols)
    c.execute(f"UPDATE subscriptions SET {sets} WHERE id=?", (*cols.values(), sub_id))


def _has_payment(c, sub_id):
    return c.execute("SELECT 1 FROM subscription_payments WHERE subscription_id=? AND state='completed'",
                     (sub_id,)).fetchone() is not None


def current(account_id, now=None):
    """Abbonamento da mostrare all'account: quello vivo, altrimenti un checkout
    aperto da meno di `ABM_SUB_CHECKOUT_TTL_SEC`; None se non c'e' nulla."""
    now = _now(now)
    with db.tx() as c:
        live = _live_row(c, account_id)
        if live:
            return live
        return _one(c, "SELECT * FROM subscriptions WHERE account_id=? AND status='pending' "
                       "AND created_at>? ORDER BY created_at DESC LIMIT 1",
                    (account_id, now - _checkout_ttl()))


def _next_check(status, period_end, now, cancel_pending=False, approved_at=None):
    """Quando ricontrollare la riga (0 = mai piu'). Un'attivazione recente
    (`approved_at` nell'ultima ora) si ricontrolla a ogni minuto."""
    if status == "activating" and not cancel_pending:
        fast = approved_at is not None and now - int(approved_at) < ACTIVATING_FAST_SEC
        return now + (ACTIVATING_RECHECK_SEC if fast else 600)
    if cancel_pending or status == "pending":
        return now + 600
    end = period_end or now
    if status == "active":
        return min(now + _DAY, max(now + 600, end + 3600))
    if status == "past_due":
        return now + 6 * 3600
    if status == "cancelled":
        return max(now + 600, end + 60)
    return 0


# ---------------------------------------------------------------- piano dell'account

def _project(sub):
    """Riflette lo stato della riga sul piano dell'account: periodo pagato piu'
    la grazia dei rinnovi, solo il periodo pagato se la disdetta e' chiesta."""
    st, end = sub["status"], sub["period_end"]
    if st in ("active", "past_due") and end:
        grace = 0 if sub["cancel_requested_at"] else _past_due_sec()
        accounts.set_paid_plan(sub["account_id"], sub["plan"], int(end) + grace)
    elif st == "cancelled" and end:
        accounts.set_paid_plan(sub["account_id"], sub["plan"], int(end))
    elif st in ("ended", "abandoned"):
        with db.tx() as c:
            other = _live_row(c, sub["account_id"], exclude=sub["id"])
        if other is None:
            accounts.end_paid_plan(sub["account_id"])


def _account_email(account_id):
    acct = accounts.get(account_id)
    if not acct or acct.get("deleted_at") is not None:
        return None, None
    return acct["email"], acct.get("lang") or "en"


def _day(ts):
    return accounts.utc_day(int(ts)) if ts else ""


def _mail(kind, sub, *, voucher_until=None, renews_at=None, ends_at=None):
    """Email all'utente (`kind`: active | cancelled), best-effort."""
    email, lang = _account_email(sub["account_id"])
    if not email:
        return
    space = accounts.format_bytes(accounts.plan_quota_bytes(sub["plan"]))
    try:
        if kind == "active":
            email_service.send_subscription_active(
                email, lang, space=space, voucher=accounts.format_eur(voucher_eur(sub["plan"])),
                voucher_until=_day(voucher_until), renews_at=_day(renews_at))
        else:
            email_service.send_subscription_cancelled(
                email, lang, space=space, ends_at=_day(ends_at),
                days=accounts.archive_tolerance_days())
    except Exception as e:  # noqa: BLE001 - email best-effort
        print(f"[subscriptions] email {kind} per {sub['id']}: {type(e).__name__}: {e}", flush=True)


# ---------------------------------------------------------------- checkout

def start_checkout(account, plan, *, accepted_terms, waived_withdrawal, return_url, cancel_url,
                   now=None):
    """Apre (o riprende) un checkout. Ritorna (esito, approve_url): esito
    ok | disabled | bad_plan | terms_required | exists | error. Un checkout aperto
    da meno del TTL con lo stesso piano restituisce lo stesso link; con un piano
    diverso il vecchio diventa `abandoned`. `return_url` riceve `sid=<id>`."""
    if not enabled():
        return "disabled", None
    if plan not in accounts.SPACE_PLANS:
        return "bad_plan", None
    if not (accepted_terms is True and waived_withdrawal is True):
        return "terms_required", None
    now = _now(now)
    sub_id = "sub_" + secrets.token_urlsafe(12)
    with db.tx() as c:
        if _live_row(c, account["id"]):
            return "exists", None
        for p in [dict(r) for r in c.execute(
                "SELECT * FROM subscriptions WHERE account_id=? AND status='pending' "
                "ORDER BY created_at DESC", (account["id"],))]:
            if p["plan"] == plan and p["approve_url"] and now - p["created_at"] < _checkout_ttl():
                return "ok", p["approve_url"]
            _update(c, p["id"], now, status="abandoned", ended_at=now,
                    next_check_at=now + 600 if p["external_id"] else 0)
        c.execute("INSERT INTO subscriptions(id, account_id, provider, plan, status, created_at, "
                  "updated_at, next_check_at, terms_version, withdrawal_waived_at) "
                  "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
                  (sub_id, account["id"], DEFAULT_PROVIDER, plan, now, now, now + 600,
                   SUB_TERMS_VERSION, now))
    sep = "&" if "?" in return_url else "?"
    try:
        ext, url = _provider().create_checkout(
            sub_id=sub_id, plan=plan, email=account.get("email") or "",
            lang=account.get("lang") or "en", return_url=f"{return_url}{sep}sid={sub_id}",
            cancel_url=cancel_url)
    except Exception as e:  # noqa: BLE001 - il checkout fallito non lascia righe aperte
        print(f"[subscriptions] checkout {sub_id}: {type(e).__name__}: {e}", flush=True)
        with db.tx() as c:
            _update(c, sub_id, now, status="abandoned", ended_at=now, next_check_at=0)
        return "error", None
    with db.tx() as c:
        _update(c, sub_id, now, external_id=ext, approve_url=url)
    _log(f"SUB_CHECKOUT:{plan}", sub_id)
    return "ok", url


# ---------------------------------------------------------------- stato remoto

def _status_from_remote(sub, remote, now, paid):
    """Nuovo stato della riga dato lo stato remoto (vedi STATUSES)."""
    st, end = sub["status"], sub["period_end"] or 0
    rs = remote.status
    if rs == "APPROVAL_PENDING":
        return st
    if rs in ("APPROVED", "ACTIVE") and not paid:
        return "activating" if st in ("pending", "activating") else st
    if rs == "ACTIVE":
        if st == "cancelled":
            return st
        return "past_due" if now > end and remote.failed_payments > 0 else "active"
    if rs == "CANCELLED":
        return "cancelled" if paid and now < end else "ended"
    if rs in ("SUSPENDED", "EXPIRED"):
        return "ended"
    return st


def refresh(sub_id, now=None):
    """Rilegge lo stato remoto e aggiorna riga e piano. Le righe `ended` e
    `abandoned` non cambiano piu' stato. ProviderError se il fornitore non risponde."""
    now = _now(now)
    sub = get(sub_id)
    if not sub or not sub["external_id"] or sub["status"] in ("ended", "abandoned"):
        return sub
    remote = _provider(sub["provider"]).fetch(sub["external_id"])
    with db.tx() as c:
        sub = _get(c, sub_id)
        if sub["status"] in ("ended", "abandoned"):
            return sub
        old = sub["status"]
        new = _status_from_remote(sub, remote, now, _has_payment(c, sub_id))
        if new in LIVE and old not in LIVE and _live_row(c, sub["account_id"], exclude=sub_id):
            new = "abandoned"           # un secondo abbonamento: lo chiude la riconciliazione
        cols = {"status": new, "check_failures": 0}
        if new != "pending" and sub["approved_at"] is None:
            cols["approved_at"] = now
        if remote.status == "CANCELLED" and sub["cancel_confirmed_at"] is None:
            cols["cancel_confirmed_at"] = now
            if sub["cancel_requested_at"] is None:          # disdetto dal lato del fornitore
                cols["cancel_requested_at"] = now
                cols["cancel_reason"] = "provider"
        if new in ("ended", "abandoned") and sub["ended_at"] is None:
            cols["ended_at"] = now
        cancel_pending = bool(sub["cancel_requested_at"]) and not (
            sub["cancel_confirmed_at"] or cols.get("cancel_confirmed_at"))
        cols["next_check_at"] = (now + 600 if new == "abandoned"
                                 else _next_check(new, sub["period_end"], now, cancel_pending,
                                                  sub["approved_at"] or cols.get("approved_at")))
        _update(c, sub_id, now, **cols)
        sub = _get(c, sub_id)
    _project(sub)
    if cols.get("cancel_reason") == "provider" and new == "cancelled":
        _mail("cancelled", sub, ends_at=sub["period_end"])
    if new != old:
        _log(f"SUB_STATE:{old}->{new}", sub_id)
    return sub


def _find_or_link(provider, external_id, now):
    """Riga dell'id esterno; se manca (crash fra la creazione remota e il
    salvataggio) la ritrova dal `custom_id` dello stato remoto e la collega."""
    if not external_id:
        return None
    with db.tx() as c:
        row = _one(c, "SELECT * FROM subscriptions WHERE provider=? AND external_id=?",
                   (provider, external_id))
    if row:
        return row
    try:
        remote = _provider(provider).fetch(external_id)
    except Exception as e:  # noqa: BLE001
        print(f"[subscriptions] id esterno sconosciuto {external_id}: {e}", flush=True)
        return None
    with db.tx() as c:
        row = _one(c, "SELECT * FROM subscriptions WHERE id=? AND provider=? AND external_id IS NULL",
                   (remote.custom_id, provider))
        if row is None:
            return None
        _update(c, row["id"], now, external_id=external_id)
        return _get(c, row["id"])


# ---------------------------------------------------------------- pagamenti

def _reject_reason(c, sub, pay):
    if sub["status"] in ("ended", "abandoned"):
        return "closed"
    if sub["cancel_requested_at"] and pay.paid_at > sub["cancel_requested_at"]:
        return "after_cancel"
    if _live_row(c, sub["account_id"], exclude=sub["id"]):
        return "duplicate_subscription"
    return None


def _insert_payment(c, sub, pay, start, end, state, now):
    c.execute("INSERT INTO subscription_payments(provider, payment_id, subscription_id, amount_eur, "
              "paid_at, period_start, period_end, state, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
              (sub["provider"], pay.payment_id, sub["id"], float(pay.amount_eur), int(pay.paid_at),
               int(start), int(end), state, now))


def _reject(sub, pay, reason, now):
    """Rimborsa un pagamento che non doveva arrivare e chiude l'abbonamento remoto."""
    prov = _provider(sub["provider"])
    try:
        prov.refund_payment(pay.payment_id, pay.amount_eur)
    except Exception as e:  # noqa: BLE001
        _alert("refund_failed", subscription=sub["id"], payment=pay.payment_id,
               amount=pay.amount_eur, error=f"{type(e).__name__}: {e}"[:200])
    if sub["cancel_confirmed_at"] is None and sub["external_id"]:
        try:
            prov.cancel(sub["external_id"], f"rejected: {reason}")
            with db.tx() as c:
                _update(c, sub["id"], now, cancel_confirmed_at=now,
                        cancel_requested_at=sub["cancel_requested_at"] or now)
        except Exception as e:  # noqa: BLE001 - la riconciliazione ritenta
            print(f"[subscriptions] cancel dopo rifiuto {sub['id']}: {e}", flush=True)
            with db.tx() as c:
                _update(c, sub["id"], now, cancel_requested_at=sub["cancel_requested_at"] or now,
                        next_check_at=now + 600)
    _alert("rejected_payment", subscription=sub["id"], payment=pay.payment_id,
           amount=pay.amount_eur, reason=reason)


def _issue_voucher(sub, payment_id):
    """Voucher del pagamento (idempotente). Senza account vivo non si emette e
    il pagamento si segna con `-` (la riconciliazione non lo ricerca piu')."""
    email, _lang = _account_email(sub["account_id"])
    if not email:
        with db.tx() as c:
            c.execute("UPDATE subscription_payments SET voucher_code='-' WHERE provider=? "
                      "AND payment_id=?", (sub["provider"], payment_id))
        return None
    code = payment.issue_subscription_voucher(
        key=f"{sub['provider']}:{payment_id}", account_id=sub["account_id"], email=email,
        amount_eur=voucher_eur(sub["plan"]), days=_voucher_days())
    with db.tx() as c:
        c.execute("UPDATE subscription_payments SET voucher_code=? WHERE provider=? AND payment_id=?",
                  (code, sub["provider"], payment_id))
    return code


def record_payment(sub_id, pay, now=None):
    """Registra un pagamento: issued | duplicate | rejected | ignored."""
    now = _now(now)
    sub = get(sub_id)
    if sub is None or pay is None or pay.state != "completed" or not pay.payment_id:
        return "ignored"
    try:
        remote = _provider(sub["provider"]).fetch(sub["external_id"]) if sub["external_id"] else None
    except Exception as e:  # noqa: BLE001 - senza stato remoto il periodo e' di un mese
        print(f"[subscriptions] fetch per il periodo di {sub_id}: {e}", flush=True)
        remote = None
    with db.tx() as c:
        sub = _get(c, sub_id)
        if c.execute("SELECT 1 FROM subscription_payments WHERE provider=? AND payment_id=?",
                     (sub["provider"], pay.payment_id)).fetchone():
            return "duplicate"
        reason = _reject_reason(c, sub, pay)
        if reason:
            _insert_payment(c, sub, pay, pay.paid_at, pay.paid_at, "rejected", now)
        else:
            start = int(pay.paid_at)
            nxt = remote.next_billing_at if remote else None
            end = nxt if nxt and nxt > start + 20 * _DAY else _add_month(start)
            first = sub["activated_at"] is None
            status = "cancelled" if sub["status"] == "cancelled" else "active"
            _insert_payment(c, sub, pay, start, end, "completed", now)
            _update(c, sub_id, now, status=status, period_start=start, period_end=end,
                    activated_at=sub["activated_at"] or now, approved_at=sub["approved_at"] or now,
                    check_failures=0,
                    next_check_at=_next_check(status, end, now,
                                              bool(sub["cancel_requested_at"])
                                              and not sub["cancel_confirmed_at"]))
            sub = _get(c, sub_id)
    if reason:
        _reject(sub, pay, reason, now)
        return "rejected"
    _project(sub)
    try:
        code = _issue_voucher(sub, pay.payment_id)
    except Exception as e:  # noqa: BLE001 - la riconciliazione lo riemette
        print(f"[subscriptions] voucher di {pay.payment_id}: {type(e).__name__}: {e}", flush=True)
        code = None
    if abs(float(pay.amount_eur) - price_eur(sub["plan"])) > 0.01 or (pay.currency or "EUR") != "EUR":
        _alert("amount_mismatch", subscription=sub_id, payment=pay.payment_id,
               amount=pay.amount_eur, currency=pay.currency, expected=price_eur(sub["plan"]))
    if first:
        v = payment.voucher_info(code) if code else None
        _mail("active", sub, voucher_until=int(v["expires_at"]) if v else None,
              renews_at=sub["period_end"])
        _log(f"SUB_ACTIVE:{sub['plan']}", sub_id)
    else:
        _log(f"SUB_RENEWED:{sub['plan']}", sub_id)
    return "issued"


def reverse_payment(provider, pay, now=None):
    """Rimborso o storno di un pagamento: revoca il voucher che aveva generato."""
    now = _now(now)
    if pay is None or not pay.payment_id:
        return "ignored"
    with db.tx() as c:
        row = _one(c, "SELECT * FROM subscription_payments WHERE provider=? AND payment_id=?",
                   (provider, pay.payment_id))
        if row is None:
            return "unknown_payment"
        if row["state"] in ("refunded", "reversed"):
            return "duplicate"
        c.execute("UPDATE subscription_payments SET state=? WHERE provider=? AND payment_id=?",
                  (pay.state, provider, pay.payment_id))
    if row["voucher_code"]:
        payment.revoke_voucher(row["voucher_code"], f"subscription payment {pay.state}")
    if row["state"] == "rejected":          # il rimborso l'abbiamo fatto noi
        return "refund_confirmed"
    _alert("reversal", subscription=row["subscription_id"], payment=pay.payment_id,
           state=pay.state, voucher=payment.mask_code(row["voucher_code"]))
    return "reversed"


# ---------------------------------------------------------------- eventi

def handle_event(provider, event, now=None):
    """Applica un webhook normalizzato, una volta sola per id evento. Su
    eccezione l'evento resta da processare e l'errore risale (il fornitore
    ritenta)."""
    now = _now(now)
    with db.tx() as c:
        seen = _one(c, "SELECT processed_at FROM subscription_events WHERE provider=? AND event_id=?",
                    (provider, event.event_id))
        if seen and seen["processed_at"] is not None:
            return "duplicate_event"
        if not seen:
            c.execute("INSERT INTO subscription_events(provider, event_id, type, external_id, "
                      "received_at) VALUES (?, ?, ?, ?, ?)",
                      (provider, event.event_id, event.raw_type, event.external_id or "", now))
    if event.type == "payment_reversed":
        outcome = reverse_payment(provider, event.payment, now)
    else:
        sub = _find_or_link(provider, event.external_id, now)
        if sub is None:
            outcome = "unknown"
        elif event.type == "renewed":
            outcome = record_payment(sub["id"], event.payment, now=now)
        else:
            refresh(sub["id"], now=now)
            outcome = "refreshed"
    with db.tx() as c:
        c.execute("UPDATE subscription_events SET processed_at=?, outcome=? WHERE provider=? "
                  "AND event_id=?", (now, outcome, provider, event.event_id))
    return outcome


# ---------------------------------------------------------------- disdetta

def _try_cancel(sub, reason, now):
    """Chiede la disdetta al fornitore; True se confermata."""
    try:
        _provider(sub["provider"]).cancel(sub["external_id"], reason)
    except Exception as e:  # noqa: BLE001 - la riconciliazione ritenta
        print(f"[subscriptions] cancel {sub['id']}: {type(e).__name__}: {e}", flush=True)
        with db.tx() as c:
            failures = (_get(c, sub["id"])["check_failures"] or 0) + 1
            _update(c, sub["id"], now, check_failures=failures, next_check_at=now + 600)
        if failures == 5:
            _alert("cancel_failing", subscription=sub["id"], error=str(e)[:200])
        return False
    with db.tx() as c:
        cur = _get(c, sub["id"])
        paid = _has_payment(c, sub["id"])
        end = cur["period_end"] or 0
        status = "cancelled" if paid and end > now else "ended"
        _update(c, sub["id"], now, status=status, cancel_confirmed_at=now, check_failures=0,
                ended_at=cur["ended_at"] or (now if status == "ended" else None),
                next_check_at=_next_check(status, end, now))
        cur = _get(c, sub["id"])
    _project(cur)
    if cur["cancel_reason"] == "user":
        _mail("cancelled", cur, ends_at=cur["period_end"] if status == "cancelled" else now)
    _log(f"SUB_CANCELLED:{cur['cancel_reason']}", sub["id"])
    return True


def request_cancel(account_id, reason, now=None):
    """Disdetta dell'abbonamento vivo dell'account (`reason`: user |
    account_deleted). La richiesta resta registrata anche se il fornitore non
    risponde (si ritenta dalla riconciliazione): i benefici durano fino alla
    fine del periodo pagato. Con `account_deleted` si abbandonano anche i
    checkout aperti. Ritorna {status, ends_at, confirmed} o None."""
    now = _now(now)
    if not _ready():
        return None
    with db.tx() as c:
        if reason == "account_deleted":
            for p in [dict(r) for r in c.execute(
                    "SELECT * FROM subscriptions WHERE account_id=? AND status='pending'", (account_id,))]:
                _update(c, p["id"], now, status="abandoned", ended_at=now,
                        next_check_at=now + 600 if p["external_id"] else 0)
        sub = _live_row(c, account_id)
        if sub is None:
            return None
        if sub["cancel_requested_at"] is None:
            _update(c, sub["id"], now, cancel_requested_at=now, cancel_reason=reason)
        sub = _get(c, sub["id"])
    confirmed = sub["cancel_confirmed_at"] is not None or _try_cancel(sub, reason, now)
    sub = get(sub["id"])
    if not confirmed:
        _project(sub)               # disdetta chiesta: niente grazia oltre il periodo pagato
    return {"status": sub["status"], "confirmed": confirmed,
            "ends_at": sub["period_end"] if sub["status"] in ("cancelled", "active", "past_due")
            else sub["ended_at"]}


# ---------------------------------------------------------------- riconciliazione

def _collect_payments(sub, now):
    """Registra i pagamenti remoti che i webhook non hanno portato e applica i
    rimborsi persi: un pagamento che il fornitore da' come rimborsato revoca il
    suo voucher anche senza webhook."""
    since = int(sub["period_start"] or sub["created_at"]) - 2 * _DAY
    for pay in _provider(sub["provider"]).list_payments(sub["external_id"], since, now):
        if pay.state == "completed":
            record_payment(sub["id"], pay, now=now)
        elif pay.state in ("refunded", "reversed"):
            reverse_payment(sub["provider"], pay, now)


def _sweep_abandoned(sub, now, out):
    """Un checkout abbandonato approvato piu' tardi va chiuso e rimborsato."""
    if not sub["external_id"] or now - sub["created_at"] > ABANDONED_WATCH_SEC:
        with db.tx() as c:
            _update(c, sub["id"], now, next_check_at=0)
        return
    remote = _provider(sub["provider"]).fetch(sub["external_id"])
    if remote.status in ("APPROVED", "ACTIVE", "SUSPENDED"):
        _provider(sub["provider"]).cancel(sub["external_id"], "abandoned checkout")
        _collect_payments(sub, now)
        out["closed"] += 1
    with db.tx() as c:
        _update(c, sub["id"], now, next_check_at=now + 6 * 3600)


def _sweep_row(sub, now, out):
    if sub["status"] == "abandoned":
        _sweep_abandoned(sub, now, out)
        return
    if sub["status"] == "pending" and now - sub["created_at"] >= _checkout_ttl():
        with db.tx() as c:
            _update(c, sub["id"], now, status="abandoned", ended_at=now,
                    next_check_at=now + 600 if sub["external_id"] else 0)
        out["abandoned"] += 1
        _log("SUB_ABANDONED", sub["id"])
        return
    if sub["cancel_requested_at"] and not sub["cancel_confirmed_at"] and sub["external_id"]:
        if _try_cancel(sub, sub["cancel_reason"] or "user", now):
            out["cancelled"] += 1
    sub = refresh(sub["id"], now)
    if sub and sub["external_id"] and sub["status"] not in ("pending", "abandoned"):
        _collect_payments(sub, now)
    out["checked"] += 1


def reconcile_one(sub_id, now=None):
    """Stato remoto e pagamenti di una riga subito (ritorno dal checkout):
    l'attivazione non aspetta il giro di riconciliazione. Ritorna la riga."""
    now = _now(now)
    try:
        sub = refresh(sub_id, now)
        if sub and sub["external_id"] and sub["status"] not in ("pending", "abandoned"):
            _collect_payments(sub, now)
    except Exception as e:  # noqa: BLE001 - ci pensano webhook e riconciliazione
        print(f"[subscriptions] riconciliazione di {sub_id}: {type(e).__name__}: {e}", flush=True)
    return get(sub_id)


def poke(account, now=None):
    """Chi guarda l'abbonamento mentre e' in attivazione non aspetta il giro:
    la riga si ricontrolla subito, al piu' ogni POKE_MIN_SEC. Ritorna la riga
    corrente (o None)."""
    now = _now(now)
    if not account or not _ready():
        return None
    sub = current(account["id"], now)
    if not sub or sub["status"] != "activating" or now - int(sub["updated_at"]) < POKE_MIN_SEC:
        return sub
    return reconcile_one(sub["id"], now)


def _note_failure(sub, now, err):
    with db.tx() as c:
        cur = _get(c, sub["id"])
        failures = (cur["check_failures"] or 0) + 1
        wait = retry_util.backoff(min(failures, 6), base=600, cap=6 * 3600)
        _update(c, sub["id"], now, check_failures=failures, next_check_at=now + int(wait))
    if failures == 5:
        _alert("check_failures", subscription=sub["id"], error=f"{type(err).__name__}: {err}"[:200])


def sweep(now=None, force=False):
    """Un giro di riconciliazione (dal loop di cleanup, al piu' ogni
    `ABM_SUB_RECONCILE_SEC`; `force` salta l'attesa): checkout scaduti, disdette
    da confermare, stato remoto e pagamenti persi delle righe in scadenza di
    controllo, voucher non emessi. Ritorna i conteggi."""
    t = _now(now)
    out = dict.fromkeys(("checked", "abandoned", "cancelled", "closed", "vouchers", "errors"), 0)
    if not force and t - _sweep_state["at"] < _reconcile_sec():
        return out
    _sweep_state["at"] = t
    if not accounts.enabled() or not _ready():
        return out
    with db.tx() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM subscriptions WHERE next_check_at>0 AND next_check_at<=? "
            "ORDER BY next_check_at LIMIT ?", (t, SWEEP_BATCH))]
        missing = [dict(r) for r in c.execute(
            "SELECT p.payment_id, s.* FROM subscription_payments p JOIN subscriptions s "
            "ON s.id=p.subscription_id WHERE p.state='completed' AND p.voucher_code='' LIMIT ?",
            (SWEEP_BATCH,))]
    for sub in rows:
        try:
            _sweep_row(sub, t, out)
        except Exception as e:  # noqa: BLE001 - una riga non ferma le altre
            out["errors"] += 1
            print(f"[subscriptions] sweep {sub['id']}: {type(e).__name__}: {e}", flush=True)
            _note_failure(sub, t, e)
    for row in missing:
        try:
            if _issue_voucher(row, row["payment_id"]):
                out["vouchers"] += 1
        except Exception as e:  # noqa: BLE001
            out["errors"] += 1
            print(f"[subscriptions] voucher {row['payment_id']}: {type(e).__name__}: {e}", flush=True)
    if any(out.values()):
        print(f"[subscriptions] sweep: {out}", flush=True)
    return out


# ---------------------------------------------------------------- stato per UI/API

def _voucher_summary(account_id, now):
    live = [v for _code, v in payment.iter_vouchers()
            if v.get("kind") == "subscription" and v.get("account_id") == account_id
            and not v.get("revoked") and v.get("expires_at", 0) > now
            and payment._voucher_remaining(v) >= 0.01]
    if not live:
        return None
    return {"remaining_eur": round(sum(payment._voucher_remaining(v) for v in live), 2),
            "expires_at": int(min(v["expires_at"] for v in live))}


def status_for(account, *, for_app=False, now=None):
    """Stato dell'abbonamento per l'Area personale (con i prezzi) o per l'app
    (`for_app`: mai prezzi)."""
    now = _now(now)
    out = {"enabled": enabled(), "subscription": None}
    if not for_app:
        out["plans"] = plan_offer()
    if not account or not _ready():
        return out
    sub = current(account["id"], now)
    if sub:
        cancelling = bool(sub["cancel_requested_at"])
        out["subscription"] = {
            "plan": sub["plan"], "status": sub["status"], "period_end": sub["period_end"],
            "renews": sub["status"] in ("active", "past_due") and not cancelling,
            "ends_at": sub["period_end"] if (cancelling or sub["status"] == "cancelled") else None,
            "voucher": _voucher_summary(account["id"], now),
        }
    return out
