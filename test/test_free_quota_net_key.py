"""Chiave di rete della quota gratuita PREMIUM (incidente del 28/10/2026).

Un romanzo letto a pezzi da 0,10-0,15 EUR su 7 cid ruotati a quota esaurita:
la quota contava solo sul cookie. `free_quota.who()` aggiunge l'account della
sessione (`mail:`) e la rete della connessione (`net:`, IPv4 esatto o /64),
la decisione guarda la piu' consumata. `ABM_FREE_QUOTA_NET_KEY` decide se la
rete e' spenta, osservata (default) o applicata.
"""
import pytest

import client_identity
import free_quota
import free_tts_quota
from monthly_ledger import MonthlyLedger

VOICE = "gemini:flash31:Zephyr"
IP = "46.185.190.253"


@pytest.fixture
def fq(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_PREMIUM_MIN_COST_EUR", "0.50")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.50")
    monkeypatch.delenv("ABM_FREE_QUOTA_NET_KEY", raising=False)
    return free_quota


# --------------------------------------------------------------- client_identity

@pytest.mark.parametrize("ip,expected", [
    ("46.185.190.253", "46.185.190.253"),
    (" 46.185.190.253 ", "46.185.190.253"),
    ("::ffff:46.185.190.253", "46.185.190.253"),
    ("2a01:4f8:c0c:1234:aaaa:bbbb:cccc:dddd", "2a01:4f8:c0c:1234::/64"),
    ("2a01:4f8:c0c:1234::1", "2a01:4f8:c0c:1234::/64"),
    ("", ""),
    (None, ""),
    ("not-an-ip", ""),
    ("46.185.190", ""),
])
def test_network_of(ip, expected):
    assert client_identity.network_of(ip) == expected


def test_network_hash_ipv4_coincide_con_la_forma_di_hash_ip():
    # Stessa forma di audiobook_app._hash_ip (sep=":" con ip_salt()): un
    # IPv4 si ritrova con lo stesso hash nei log e nei rate limit.
    expected = client_identity.salted_hash(IP, salt=client_identity.ip_salt(), sep=":")
    assert client_identity.network_hash(IP) == expected


def test_network_hash_ipv6_stesso_slash64_stessa_chiave():
    a = client_identity.network_hash("2a01:4f8:c0c:1234::1")
    b = client_identity.network_hash("2a01:4f8:c0c:1234:ffff::9")
    c = client_identity.network_hash("2a01:4f8:c0c:1235::1")
    assert a and a == b and a != c


def test_network_hash_vuoto_senza_indirizzo():
    assert client_identity.network_hash("") == ""
    assert client_identity.network_hash("x") == ""


# --------------------------------------------------------------- MonthlyLedger.worst

@pytest.fixture
def ledger(tmp_path):
    return MonthlyLedger(lambda: tmp_path / "_l.json", "eur", cast=float, round_to=4)


def test_worst_sceglie_la_chiave_piu_consumata(ledger):
    ledger.consume("a", 0.5, "j1")
    ledger.consume("b", 1.5, "j2")
    assert ledger.worst([("cid", "a"), ("net", "b")]) == (False, "net", 1.5)


def test_worst_a_parita_vince_la_prima(ledger):
    ledger.consume("a", 1.0, "j1")
    ledger.consume("b", 1.0, "j2")
    assert ledger.worst([("cid", "a"), ("net", "b")])[1] == "cid"


def test_worst_senza_consumi_e_chiavi_vuote(ledger):
    assert ledger.worst([("cid", "a"), ("mail", "")]) == (False, "cid", 0.0)
    assert ledger.worst([]) == (False, "", 0.0)


def test_worst_addebitato_su_qualunque_chiave(ledger):
    ledger.consume("b", 0.2, "gen1")
    assert ledger.worst([("cid", "a"), ("net", "b")], "gen1")[0] is True
    assert ledger.worst([("cid", "a"), ("net", "b")], "gen2")[0] is False
    assert ledger.worst([("cid", "a")], "gen1")[0] is False


def test_free_tts_quota_worst_usage_invariato(tmp_path, monkeypatch):
    """Parita' del refactor: `_worst_usage` delega a MonthlyLedger.worst con
    lo stesso esito (cid vince a parita', email piu' consumata vince,
    addebito riconosciuto su una qualunque chiave, tipo int)."""
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    keys = free_tts_quota._quota_keys("cidX", "Reader@Example.com")
    assert free_tts_quota._worst_usage(keys) == (False, "cid", 0)
    free_tts_quota.consume("cidX", 100, "j1")
    free_tts_quota.consume("cidY", 400, "j2", email="reader@example.com")
    charged, kind, used = free_tts_quota._worst_usage(keys, "j2")
    assert (charged, kind, used) == (True, "mail", 400)
    assert isinstance(used, int)


# --------------------------------------------------------------- identita'

def test_who_include_rete_e_account(fq):
    w = fq.who("cid1", ip=IP)
    assert w.cid == "cid1"
    assert w.net == "net:" + client_identity.network_hash(IP)
    assert w.mail == ""
    w2 = fq.who("cid1", ip=IP, account_email="Reader@Example.com")
    assert w2.mail == free_tts_quota.mail_key("reader@example.com") != ""


def test_who_senza_rete_per_account_app_e_modo_off(fq, monkeypatch):
    assert fq.who("c", ip=IP, account_email="a@b.it").net == ""
    assert fq.who("c", ip=IP, app_device=True).net == ""
    assert fq.who("c", ip="").net == ""
    monkeypatch.setenv("ABM_FREE_QUOTA_NET_KEY", "off")
    assert fq.who("c", ip=IP).net == ""


@pytest.mark.parametrize("raw,mode", [
    (None, "observe"), ("", "observe"), ("ON", "on"), (" off ", "off"),
    ("observe", "observe"), ("boh", "observe"),
])
def test_net_mode(fq, monkeypatch, raw, mode):
    if raw is None:
        monkeypatch.delenv("ABM_FREE_QUOTA_NET_KEY", raising=False)
    else:
        monkeypatch.setenv("ABM_FREE_QUOTA_NET_KEY", raw)
    assert fq.net_mode() == mode


def test_consume_addebita_tutte_le_chiavi_anche_in_observe(fq):
    w = fq.who("cid1", ip=IP, account_email="a@b.it")
    assert w.net == ""  # con l'account la rete non c'e'
    w = fq.who("cid1", ip=IP)
    assert fq.consume(w, 0.30, "g1") == pytest.approx(0.30)
    fq.consume(w, 0.30, "g1")  # retry: idempotente su ogni chiave
    assert fq._LEDGER.used("cid1") == pytest.approx(0.30)
    assert fq._LEDGER.used(w.net) == pytest.approx(0.30)


def test_cid_nudo_resta_compatibile(fq):
    fq.consume("cid1", 0.40, "g1")
    assert fq.used_eur("cid1") == pytest.approx(0.40)
    assert fq.job_charged("cid1", "g1") is True
    assert fq.decision("cid1", VOICE, 0.10)["is_free"] is True


# --------------------------------------------------------------- decisione

def _exhaust_network(fq):
    """Primo cookie della connessione: consuma 1,95 EUR."""
    first = fq.who("cid-old", ip=IP)
    fq.consume(first, 1.95, "g-old")
    return first


def test_observe_non_nega_ma_segnala(fq):
    _exhaust_network(fq)
    fresh = fq.who("cid-new", ip=IP)
    dec = fq.decision(fresh, VOICE, 0.10, "g-new")
    assert dec["is_free"] is True and dec["due_eur"] == 0.0
    assert dec["quota_key"] == "cid"
    assert dec["net_would_charge"] is True
    assert dec["net_used_eur"] == pytest.approx(1.95)
    assert "quota_scope" not in dec


def test_observe_non_segnala_se_la_rete_ha_spazio(fq):
    fq.consume(fq.who("cid-old", ip=IP), 0.50, "g-old")
    dec = fq.decision(fq.who("cid-new", ip=IP), VOICE, 0.10, "g-new")
    assert dec["is_free"] is True
    assert "net_would_charge" not in dec


def test_on_nega_il_cookie_nuovo_sulla_stessa_rete(fq, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_NET_KEY", "on")
    _exhaust_network(fq)
    dec = fq.decision(fq.who("cid-new", ip=IP), VOICE, 0.10, "g-new")
    assert dec["is_free"] is False
    assert dec["quota_exhausted"] is True
    assert dec["quota_key"] == "net"
    assert dec["quota_scope"] == "network"
    assert dec["quota_used_eur"] == pytest.approx(1.95)
    assert dec["due_eur"] == pytest.approx(0.50)
    assert fq.snapshot(fq.who("cid-new", ip=IP))["used_eur"] == pytest.approx(1.95)


def test_on_altra_rete_resta_libera(fq, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_NET_KEY", "on")
    _exhaust_network(fq)
    dec = fq.decision(fq.who("cid-new", ip="46.185.191.128"), VOICE, 0.10, "g-new")
    assert dec["is_free"] is True


def test_on_chi_accede_usa_il_proprio_credito(fq, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_NET_KEY", "on")
    _exhaust_network(fq)
    me = fq.who("cid-new", ip=IP, account_email="vicino@example.com")
    assert fq.decision(me, VOICE, 0.10, "g-new")["is_free"] is True


def test_on_app_con_device_usa_il_proprio_credito(fq, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_NET_KEY", "on")
    _exhaust_network(fq)
    app = fq.who("app-x", ip=IP, app_device=True)
    assert fq.decision(app, VOICE, 0.10, "g-app")["is_free"] is True


def test_account_su_un_cookie_nuovo_ritrova_il_proprio_consumo(fq):
    """L'account vale in ogni modo, come per le voci standard: un secondo
    dispositivo dello stesso account non riparte da zero."""
    fq.consume(fq.who("cid-a", account_email="me@example.com"), 1.95, "g1")
    dec = fq.decision(fq.who("cid-b", account_email="me@example.com"), VOICE, 0.10, "g2")
    assert dec["is_free"] is False
    assert dec["quota_key"] == "mail"
    assert dec["quota_scope"] == "client"


def test_on_retry_della_stessa_generazione_resta_gratis(fq, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_NET_KEY", "on")
    w = fq.who("cid1", ip=IP)
    fq.consume(w, 1.95, "g-pre")
    fq.consume(w, 0.05, "g1")
    dec = fq.decision(w, VOICE, 0.05, "g1")
    assert dec["is_free"] is True


def test_off_ignora_la_rete_e_non_la_addebita(fq, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_NET_KEY", "off")
    _exhaust_network(fq)
    assert fq._LEDGER.used("net:" + client_identity.network_hash(IP)) == 0.0
    dec = fq.decision(fq.who("cid-new", ip=IP), VOICE, 0.10, "g-new")
    assert dec["is_free"] is True and "net_would_charge" not in dec


def test_client_fields(fq, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_FREE_QUOTA_NET_KEY", "on")
    _exhaust_network(fq)
    dec = fq.decision(fq.who("cid-new", ip=IP), VOICE, 0.10)
    assert fq.client_fields(dec) == {
        "quota_used_eur": pytest.approx(1.95),
        "quota_limit_eur": pytest.approx(2.00),
        "free_cap_exceeded": False,
        "quota_scope": "network",
    }
    free = fq.decision("cid-other", VOICE, 0.10)
    assert fq.client_fields(free)["quota_scope"] == ""
