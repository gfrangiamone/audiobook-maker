# subscriptions.py
"""Abbonamenti mensili (spazio cloud + voucher): stato, periodi, pagamenti.

Dominio indipendente dal fornitore: parla con un adattatore (`billing_paypal`)
attraverso un'interfaccia minima e riflette il piano in vigore su
`accounts.plan/plan_source/plan_until` con `set_paid_plan`/`end_paid_plan`,
cosi' quota e tolleranza dell'archivio non cambiano. Tabelle in SQLite (`db`).
Spec: docs/superpowers/specs/2026-10-20-abbonamenti-design.md.
"""
import db


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
