"""Blocco B4: client_identity e ratelimit, con parita' byte per byte sugli
hash (sono chiavi su disco) e sul comportamento dei limitatori."""
import pytest

import client_identity as ci
import ratelimit as rl


# --- golden catturato il 2026-10-07 dalle funzioni storiche (ABM_IP_SALT="") --
GOLDEN = {
    "hash_ip[1.2.3.4]": "f848ce7604f638e9",
    "hash_ip[]": "3dcc51b802768f1c",
    "abuse_hash[x]": "b386694e12e53454",
    "abuse_hash[net:1.2.3]": "efdf31aceb5090fd",
    "mail_key[A@B.it]": "mail:b9add3ad1bdce957",
    "email_hash[A@B.it]": "b9add3ad1bdce957b0161161b8e069b4b62173712e1a2b39f6d0f2d560c759ab",
    "email_hash[]": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
}


def test_hashes_match_the_historical_forms(monkeypatch):
    monkeypatch.setenv("ABM_IP_SALT", "")
    assert ci.ip_salt() == ci.DEFAULT_IP_SALT and ci.ip_salt(default="") == ""
    assert ci.salted_hash("1.2.3.4", salt=ci.ip_salt(), sep=":") == GOLDEN["hash_ip[1.2.3.4]"]
    assert ci.salted_hash("", salt=ci.ip_salt(), sep=":") == GOLDEN["hash_ip[]"]
    assert ci.salted_hash("x", salt=ci.ip_salt()) == GOLDEN["abuse_hash[x]"]
    assert ci.salted_hash("net:1.2.3", salt=ci.ip_salt()) == GOLDEN["abuse_hash[net:1.2.3]"]
    assert "mail:" + ci.salted_hash("a@b.it", salt=ci.ip_salt(default="")) == GOLDEN["mail_key[A@B.it]"]
    assert ci.email_hash("A@B.it") == ci.email_hash(" a@b.it ") == GOLDEN["email_hash[A@B.it]"]
    assert ci.email_hash("") == GOLDEN["email_hash[]"]


def test_callers_still_produce_the_same_hashes(monkeypatch):
    monkeypatch.setenv("ABM_IP_SALT", "")
    import abuse_watch, accounts, free_tts_quota, voice_clone
    import audiobook_app
    assert audiobook_app._hash_ip("1.2.3.4") == GOLDEN["hash_ip[1.2.3.4]"]
    assert abuse_watch._hash("net:1.2.3") == GOLDEN["abuse_hash[net:1.2.3]"]
    assert free_tts_quota.mail_key(" A@B.it ") == GOLDEN["mail_key[A@B.it]"]
    assert free_tts_quota.mail_key("nope") == "" and free_tts_quota.mail_key("") == ""
    assert accounts.email_hash("A@B.it") == voice_clone.email_hash(" a@b.it ") == GOLDEN["email_hash[A@B.it]"]


def test_norm_valid_and_mask():
    assert ci.norm_email("  A@B.IT ") == "a@b.it" and ci.norm_email(None) == ""
    assert ci.is_valid_email("john.doe@x.com") and not ci.is_valid_email("nope") and not ci.is_valid_email("")
    assert ci.mask_email("john.doe@x.com") == "j***@x.com"
    assert ci.mask_email("  a@b.c ") == "a***@b.c"
    assert ci.mask_email("  a@b.c ", strip=False) == " ***@b.c "       # pagina account
    assert ci.mask_email("nope") == "" and ci.mask_email("nope", invalid=None) == "nope"
    assert ci.mask_email("@x.com", invalid=None) == "@x.com" and ci.mask_email("@x.com") == ""
    assert ci.mask_email(None) == "" and ci.mask_email(None, invalid=None) == ""


def test_callers_mask_as_before():
    import audiobook_app, account_page
    assert audiobook_app._mask_email("  a@b.c ") == "a***@b.c"
    assert audiobook_app._mask_email("nope") == "nope" and audiobook_app._mask_email(None) == ""
    assert account_page.mask_email("  a@b.c ") == " ***@b.c " and account_page.mask_email("nope") == ""


def test_email_regex_is_shared():
    import audiobook_app, email_service
    assert audiobook_app._ACCT_EMAIL_RE is ci.EMAIL_RE
    assert email_service._EMAIL_RE is ci.EMAIL_RE


# --- ratelimit ----------------------------------------------------------------

def test_window_check_matches_the_historical_algorithm():
    store = {}
    lim = [(60, 2), (3600, 3)]
    assert rl.sliding_check(store, "ip", lim, now=1000.0) == (True, 0, -1)
    assert rl.sliding_check(store, "ip", lim, now=1010.0) == (True, 0, -1)
    # terzo colpo nel minuto: bloccato dal limite al minuto, retry = 60 - (now - primo)
    assert rl.sliding_check(store, "ip", lim, now=1020.0) == (False, 40, 0)
    assert store["ip"] == [1000.0, 1010.0]                      # il colpo negato non si registra
    # un minuto dopo: il limite al minuto e' libero, quello all'ora blocca al 4o colpo
    assert rl.sliding_check(store, "ip", lim, now=1100.0) == (True, 0, -1)
    assert rl.sliding_check(store, "ip", lim, now=1200.0) == (False, 3600 - 200, 1)
    # oltre l'ora i colpi vecchi cadono
    assert rl.sliding_check(store, "ip", lim, now=5000.0) == (True, 0, -1)
    assert store["ip"] == [5000.0]
    # record=False non registra
    assert rl.sliding_check(store, "ip2", lim, now=1.0, record=False) == (True, 0, -1)
    assert store["ip2"] == []
    rl.window_record(store, "ip2", now=2.0)
    assert store["ip2"] == [2.0]


def test_ip_rl_check_keeps_its_contract(monkeypatch):
    import audiobook_app as app
    monkeypatch.setattr(app, "_ip_rl_buckets", {})
    t = {"now": 1000.0}
    monkeypatch.setattr(app.time, "time", lambda: t["now"])
    assert app._ip_rl_check("b", "9.9.9.9", 2, 3) == (True, 0)
    assert app._ip_rl_check("b", "9.9.9.9", 2, 3) == (True, 0)
    assert app._ip_rl_check("b", "9.9.9.9", 2, 3) == (False, 60)
    assert app._ip_rl_check("b", "", 2, 3) == (True, 0)        # ip vuoto: mai limitato
    assert "9.9.9.9" in app._ip_rl_buckets["b"]


def test_lockout_and_throttle():
    store = {}
    assert rl.lockout_remaining(store, "e", now=0) == 0
    for i in range(2):
        assert rl.lockout_record(store, "e", False, max_fails=3, lock_sec=900, now=10) is False
    assert rl.lockout_record(store, "e", False, max_fails=3, lock_sec=900, now=10) is True
    assert rl.lockout_remaining(store, "e", now=100) == 810
    assert store["e"]["fail_count"] == 0
    rl.lockout_record(store, "e", True, max_fails=3, lock_sec=900, now=200)
    assert "e" not in store
    last = {}
    assert rl.throttle_ok(last, "k", 60, now=100.0) is True
    assert rl.throttle_ok(last, "k", 60, now=130.0) is False
    assert last["k"] == 100.0
    assert rl.throttle_ok(last, "k", 60, now=161.0) is True


def test_voucher_limiter_keeps_its_contract(monkeypatch):
    import payment
    monkeypatch.setattr(payment, "_voucher_attempts_ip", {})
    monkeypatch.setattr(payment, "_voucher_attempts_email", {})
    monkeypatch.setattr(payment, "_voucher_attempts_global", [])
    monkeypatch.setattr(payment, "VOUCHER_RL_PER_MIN", 2)
    t = {"now": 1000.0}
    monkeypatch.setattr(payment.time, "time", lambda: t["now"])
    assert payment._voucher_rl_check("1.1.1.1", "u@x.it") == (True, 0, None)
    assert payment._voucher_rl_check("1.1.1.1", "u@x.it") == (True, 0, None)
    assert payment._voucher_rl_check("1.1.1.1", "u@x.it") == (False, 60, "rate_limit_ip_minute")
    assert len(payment._voucher_attempts_global) == 2          # il colpo negato non e' registrato
    for _ in range(payment.VOUCHER_EMAIL_FAIL_LIMIT):
        payment._voucher_rl_record_result("U@x.it ", False)
    ok, retry, reason = payment._voucher_rl_check("2.2.2.2", "u@x.it")
    assert (ok, reason) == (False, "email_locked") and retry == payment.VOUCHER_EMAIL_LOCKOUT_SEC
    payment._voucher_rl_record_result("u@x.it", True)
    assert payment._voucher_rl_check("2.2.2.2", "u@x.it") == (True, 0, None)


def test_cooldown_counter():
    store = {}
    assert rl.cooldown_counter(store, "f", cooldown_sec=30, max_count=2, now=0) == ("ok", 1)
    assert rl.cooldown_counter(store, "f", cooldown_sec=30, max_count=2, now=10) == ("cooldown", 20)
    assert rl.cooldown_counter(store, "f", cooldown_sec=30, max_count=2, now=40) == ("last", 0)
    assert rl.cooldown_counter(store, "f", cooldown_sec=30, max_count=2, now=80) == ("exhausted", None)


def test_leaves():
    import ast, pathlib
    for mod, allowed in ((ci, {"hashlib", "re", "env_utils"}), (rl, {"time"})):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        mods = {(n.names[0].name if isinstance(n, ast.Import) else n.module).split(".")[0]
                for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))}
        assert mods <= allowed, mod.__name__
