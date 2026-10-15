"""Voucher ristretti a servizi premium scelti dall'admin (2026-10-15)."""
import pytest

import audiobook_app
import payment


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(payment, "_vouchers", {}, raising=False)
    monkeypatch.setattr(payment, "_save_vouchers", lambda: None)
    monkeypatch.setattr(payment, "_save_paid_jobs_done", lambda: None)


def _voucher(services=None, amount=10.0, email="svc@x.it"):
    code, _ = payment._create_voucher(email, amount, kind="promo", apply_bonus=False,
                                      created_by="admin", services=services)
    return code


@pytest.mark.parametrize("voice,service", [
    ("gemini:flash31:Zephyr", "flash31"),
    ("gemini:flash38:Kore", "flash38"),
    ("speechify:simba32:george", "speechify"),
    ("voxcpm:v2:it-IT/Stefano", "voxcpm"),
    ("voxcpm:mine:abc", "voxcpm"),
    ("it-IT-IsabellaNeural", ""),
    ("", ""),
])
def test_service_for_voice(voice, service):
    assert payment.voucher_service_for_voice(voice) == service


def test_service_for_purpose():
    assert payment.voucher_service_for_purpose("llm") == "llm"
    assert payment.voucher_service_for_purpose("translate") == "translate"
    assert payment.voucher_service_for_purpose("voice_clone") == "voice_clone"
    assert payment.voucher_service_for_purpose("gemini", "gemini:flash38:Kore") == "flash38"
    assert payment.voucher_service_for_purpose("gemini", "") == ""
    assert payment.voucher_service_for_purpose("any") == ""


def test_normalize_services():
    assert payment.normalize_voucher_services(["flash38", "LLM"]) == ["llm", "flash38"]
    for bad in ([], ["nope"], "llm", None):
        with pytest.raises(ValueError):
            payment.normalize_voucher_services(bad)


def test_unrestricted_voucher_covers_everything(store):
    code = _voucher(services=None)
    v = payment.voucher_info(code)
    assert "services" not in v
    for s in payment.VOUCHER_SERVICES + ("",):
        assert payment.voucher_covers(v, s)


def test_consume_rejects_uncovered_service(store):
    code = _voucher(services=["llm", "voxcpm"])
    with pytest.raises(ValueError, match="not valid for service"):
        payment._voucher_consume(code, 1.0, job_id="j1", service="flash38")
    # Senza servizio dichiarato un voucher ristretto non si spende (fail-closed).
    with pytest.raises(ValueError):
        payment._voucher_consume(code, 1.0, job_id="j1")
    assert payment._voucher_remaining(payment.voucher_info(code)) == 10.0
    assert payment._voucher_consume(code, 1.0, job_id="j1", service="voxcpm") == 9.0


def test_consume_payment_token_passes_service(store):
    code = _voucher(services=["flash31"])
    with pytest.raises(ValueError):
        payment.consume_payment_token(code, 2.0, "j2", purpose="voice_clone",
                                      service="voice_clone")
    # Job TTS combinato (sintesi + ottimizzazione AI): basta il servizio TTS.
    assert payment.consume_payment_token(code, 2.0, "j3", purpose="gemini",
                                         service="flash31") == "voucher"


@pytest.fixture
def client(monkeypatch, store):
    audiobook_app.app.config["TESTING"] = True
    monkeypatch.setattr(audiobook_app, "_voucher_rl_check", lambda ip, email: (True, 0, ""))
    monkeypatch.setattr(audiobook_app, "_voucher_rl_record_result", lambda email, success: None)
    with audiobook_app.app.test_client() as c:
        yield c


def test_validate_rejects_uncovered_voice(client):
    code = _voucher(services=list(payment.VOUCHER_DEFAULT_SERVICES))
    r = client.post("/api/voucher_validate", json={
        "code": code, "email": "svc@x.it", "purpose": "gemini",
        "voice": "gemini:flash38:Kore", "amount_eur": 1.0})
    assert r.status_code == 400
    d = r.get_json()
    assert d["valid"] is False and d["reason"] == "not_applicable"
    assert d["service"] == "flash38"
    r = client.post("/api/voucher_validate", json={
        "code": code, "email": "svc@x.it", "purpose": "gemini",
        "voice": "voxcpm:v2:it-IT/Stefano", "amount_eur": 1.0})
    assert r.status_code == 200 and r.get_json()["valid"] is True


def test_validate_by_purpose(client):
    code = _voucher(services=["flash38"])
    for purpose in ("llm", "translate", "voice_clone"):
        r = client.post("/api/voucher_validate", json={
            "code": code, "email": "svc@x.it", "purpose": purpose})
        assert r.get_json()["reason"] == "not_applicable", purpose
    # Modale premium senza voce: il controllo resta al consumo.
    r = client.post("/api/voucher_validate", json={
        "code": code, "email": "svc@x.it", "purpose": "gemini"})
    assert r.status_code == 200


def _admin(monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-svc")
    monkeypatch.setattr(audiobook_app, "_admin_auth_ok", lambda provided: True)
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    return {"X-Admin-Token": "tok-svc"}


def test_admin_create_with_services(client, monkeypatch):
    h = _admin(monkeypatch)
    r = client.post("/admin/api/vouchers", headers=h, json={
        "email": "a@x.it", "amount_eur": 3, "services": ["speechify", "llm"]})
    assert r.status_code == 200, r.get_data(as_text=True)
    code = r.get_json()["code"]
    assert r.get_json()["services"] == ["llm", "speechify"]
    assert payment.voucher_info(code)["services"] == ["llm", "speechify"]
    listed = {v["code"]: v for v in client.get("/admin/api/vouchers", headers=h).get_json()["vouchers"]}
    assert listed[code]["services"] == ["llm", "speechify"]


def test_admin_create_defaults_and_errors(client, monkeypatch):
    h = _admin(monkeypatch)
    r = client.post("/admin/api/vouchers", headers=h, json={"email": "a@x.it", "amount_eur": 3})
    assert r.get_json()["services"] == list(payment.VOUCHER_DEFAULT_SERVICES)
    for bad in ([], ["flash99"]):
        r = client.post("/admin/api/vouchers", headers=h, json={
            "email": "a@x.it", "amount_eur": 3, "services": bad})
        assert r.status_code == 400
