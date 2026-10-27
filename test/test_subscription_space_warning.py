# test/test_subscription_space_warning.py
"""Email a libreria quasi piena ad abbonati e gratuiti: soglia, riarmo, proposta del piano."""
import accounts
import db
import email_service
import subscriptions
from test.test_subscriptions import T0, DAY, _change, _paid, sub_env  # noqa: F401

NOW = T0 + 3600
FIVE = {"plan_space": "5 GB", "price": "5", "voucher": "5"}
TEN = {"plan_space": "10 GB", "price": "10", "voucher": "10"}


def _fill(acct, job_id, pct, plan="sub_5"):
    accounts.record_job(acct["id"], job_id, kind="generate", status="done", created_at=T0)
    assert accounts.mark_archived(job_id, int(accounts.plan_quota_bytes(plan) * pct / 100), now=T0)


def _free(env, email):
    acct = env.login(email)
    accounts.free_plan_action(acct["id"], "activate", "account", now=T0)
    return acct


def _warn(now=NOW):
    subscriptions._sweep_state["space_at"] = 0         # il fixture lo ripristina
    return subscriptions._archive_warnings(now)


def _space(env):
    return [m for m in env.mails if m[0] == "space"]


def _kw(env):
    return {m[1]: m[2] for m in _space(env)}


def _warned(acct):
    a = accounts.get(acct["id"])
    return a["space_warned_at"], a["space_warned_plan"]


def test_five_gb_over_80_gets_one_email_with_the_upgrade(sub_env):
    acct, _ext = _paid(sub_env, "a@x.it")
    _fill(acct, "j1", 85)
    assert _warn() == 1
    [(_kind, email, kw)] = _space(sub_env)
    assert email == "a@x.it" and kw["pct"] == 85 and kw["space"] == "5 GB"
    assert kw["offer"] == TEN and kw["free_plan"] is False
    assert _warned(acct) == (NOW, "sub_5")
    assert _warn(NOW + 600) == 0 and len(_space(sub_env)) == 1               # una sola volta


def test_rearmed_only_below_70_then_warned_again(sub_env):
    acct, _ext = _paid(sub_env, "a@x.it")
    for jid, pct in (("j1", 60), ("j2", 15), ("j3", 10)):
        _fill(acct, jid, pct)
    assert _warn() == 1
    accounts.hide_job(acct["id"], "j3")                                      # 75%: resta segnato
    assert _warn(NOW + 600) == 0 and _warned(acct) == (NOW, "sub_5")
    accounts.hide_job(acct["id"], "j2")                                      # 60%: si riarma
    assert _warn(NOW + 1200) == 0 and _warned(acct) == (None, "")
    _fill(acct, "j4", 25)                                                    # 85%
    assert _warn(NOW + 1800) == 1 and len(_space(sub_env)) == 2


def test_ten_gb_gets_the_email_without_offer(sub_env):
    acct, _ext = _paid(sub_env, "a@x.it", plan="sub_10", amount=10.0)
    _fill(acct, "j1", 90, plan="sub_10")
    assert _warn() == 1
    kw = _space(sub_env)[0][2]
    assert kw["offer"] is None and kw["space"] == "10 GB" and kw["pct"] == 90


def test_below_threshold_and_cancelled_get_nothing(sub_env):
    low, _ = _paid(sub_env, "low@x.it")
    _fill(low, "j1", 79)
    gone, _ = _paid(sub_env, "gone@x.it")
    _fill(gone, "j2", 95)
    assert subscriptions.request_cancel(gone["id"], "user", now=T0 + 120)
    assert _warn() == 0 and _space(sub_env) == []
    assert _warned(gone) == (None, "")                                       # nulla da riarmare dopo


def test_past_due_gets_the_email_without_offer(sub_env):
    late, ext = _paid(sub_env, "late@x.it")
    _fill(late, "j1", 85)
    with db.tx() as c:
        c.execute("UPDATE subscriptions SET status='past_due' WHERE external_id=?", (ext,))
    ok, _ = _paid(sub_env, "ok@x.it")
    _fill(ok, "j2", 85)
    assert _warn() == 2
    kw = _kw(sub_env)
    assert kw["late@x.it"]["offer"] is None and kw["ok@x.it"]["offer"] == TEN


def test_sale_off_still_warns_without_offer(sub_env, monkeypatch):
    acct, _ = _paid(sub_env, "a@x.it")
    _fill(acct, "j1", 85)
    free = _free(sub_env, "free@x.it")
    _fill(free, "j2", 85, plan="free")
    monkeypatch.setenv("ABM_SUBSCRIPTIONS_ENABLE", "0")
    assert _warn() == 2
    assert all(kw["offer"] is None for kw in _kw(sub_env).values())


def test_pending_change_waits(sub_env):
    acct, _ext = _paid(sub_env, "a@x.it")
    _fill(acct, "j1", 85)
    _change(sub_env, acct, "sub_10", T0 + DAY)
    assert _warn(T0 + DAY + 60) == 0 and _warned(acct) == (None, "")


def test_failed_send_is_marked_anyway(sub_env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("smtp")
    monkeypatch.setattr(email_service, "send_subscription_space", boom)
    acct, _ext = _paid(sub_env, "a@x.it")
    _fill(acct, "j1", 85)
    assert _warn() == 1 and _warned(acct) == (NOW, "sub_5")                  # niente raffiche
    assert _warn(NOW + 600) == 0


def test_sweep_runs_the_warning_at_most_every_interval(sub_env):
    acct, _ = _paid(sub_env, "a@x.it")
    _fill(acct, "j1", 85)
    subscriptions._sweep_state["space_at"] = NOW - 10
    assert subscriptions.sweep(now=NOW, force=True)["space_warned"] == 0
    later = NOW - 10 + subscriptions.ARCHIVE_WARN_INTERVAL_SEC
    assert subscriptions.sweep(now=later, force=True)["space_warned"] == 1


# ------------------------------------------------------------------ piano gratuito

def test_free_plan_over_80_gets_the_offer_to_subscribe(sub_env):
    """Anche chi era gia' oltre l'80% prima del deploy: conta lo stato, non il passaggio."""
    acct = _free(sub_env, "free@x.it")
    _fill(acct, "j1", 84, plan="free")
    assert _warn() == 1
    kw = _space(sub_env)[0][2]
    assert kw["free_plan"] is True and kw["offer"] == FIVE
    assert kw["space"] == accounts.format_bytes(accounts.plan_quota_bytes("free")) and kw["pct"] == 84
    assert _warned(acct) == (NOW, "free")
    assert _warn(NOW + 600) == 0


def test_free_plan_rearmed_when_the_plan_changes(sub_env):
    acct = _free(sub_env, "free@x.it")
    _fill(acct, "j1", 90, plan="free")
    assert _warn() == 1
    with db.tx() as c:                                   # passa al 5 GB: il 90% del gratuito e' poco
        c.execute("UPDATE accounts SET plan='sub_5', plan_source='paid' WHERE id=?", (acct["id"],))
    assert _warn(NOW + 600) == 0 and _warned(acct) == (None, "")


def test_gift_no_consent_tolerance_and_activating_get_nothing(sub_env):
    gift = sub_env.login("gift@x.it")
    assert accounts.gift_plan(gift["id"], "sub_5", T0 + 30 * DAY, now=T0)[0] == "ok"
    _fill(gift, "j1", 90)
    none = sub_env.login("none@x.it")                                        # nessun consenso: quota 0
    _fill(none, "j2", 90, plan="free")
    late = _free(sub_env, "late@x.it")
    _fill(late, "j3", 120, plan="free")
    with db.tx() as c:                                   # gia' in tolleranza: parte l'avviso di rimozione
        c.execute("UPDATE accounts SET archive_over_since=? WHERE id=?", (T0, late["id"]))
    paying = _free(sub_env, "paying@x.it")
    _fill(paying, "j4", 90, plan="free")
    st, _url = subscriptions.start_checkout(paying, "sub_5", accepted_terms=True, waived_withdrawal=True,
                                            return_url="https://h/r", cancel_url="https://h/c", now=T0)
    assert st == "ok"
    with db.tx() as c:                                   # approvato, primo pagamento non ancora arrivato
        c.execute("UPDATE subscriptions SET status='activating' WHERE account_id=?", (paying["id"],))
    assert _warn() == 0 and _space(sub_env) == []
