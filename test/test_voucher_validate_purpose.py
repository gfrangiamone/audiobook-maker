"""Test per l'estensione di /api/voucher_validate con purpose + amount_eur."""
import pytest
from audiobook_app import app
import payment


@pytest.fixture
def client(monkeypatch):
    app.config['TESTING'] = True
    # Disabilita rate limit per i test (rispondi sempre "allowed").
    import audiobook_app as ab
    monkeypatch.setattr(ab, "_voucher_rl_check", lambda ip, email: (True, 0, ""))
    monkeypatch.setattr(ab, "_voucher_rl_record_result", lambda email, success: None)
    with app.test_client() as c:
        yield c


def _make_voucher(email, amount):
    code, _ = payment._create_voucher(
        email=email, amount_eur=amount,
        kind="promo", note="test", apply_bonus=False,
    )
    return code


def test_voucher_validate_accepts_purpose(client):
    code = _make_voucher("purpose_test_1@x.it", 2.0)
    r = client.post("/api/voucher_validate", json={
        "code": code, "email": "purpose_test_1@x.it",
        "purpose": "gemini", "amount_eur": 1.5,
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d["valid"] is True
    assert d["remaining_eur"] >= 1.5
    assert d.get("purpose_requested") == "gemini"


def test_voucher_validate_insufficient(client):
    code = _make_voucher("purpose_test_2@x.it", 0.5)
    r = client.post("/api/voucher_validate", json={
        "code": code, "email": "purpose_test_2@x.it",
        "purpose": "gemini", "amount_eur": 2.0,
    })
    assert r.status_code == 400
    d = r.get_json()
    assert d["valid"] is False
    assert "insufficient" in (d.get("reason", "") or "").lower()
    assert d["remaining_eur"] == pytest.approx(0.5)
    assert d["required_eur"] == pytest.approx(2.0)


def test_voucher_validate_legacy_no_purpose(client):
    """Senza purpose/amount_eur (chiamata legacy dal vecchio flusso) — funziona ancora come prima ma include valid: true."""
    code = _make_voucher("purpose_test_3@x.it", 1.0)
    r = client.post("/api/voucher_validate", json={
        "code": code, "email": "purpose_test_3@x.it",
    })
    assert r.status_code == 200
    d = r.get_json()
    assert d["valid"] is True
    assert d["remaining_eur"] == pytest.approx(1.0)
    # Campi legacy preservati
    assert d["payment_token"] == code
    assert "expires_at" in d


def test_voucher_validate_email_mismatch_has_valid_false(client):
    code = _make_voucher("purpose_test_4@x.it", 1.0)
    r = client.post("/api/voucher_validate", json={
        "code": code, "email": "wrong@x.it",
    })
    assert r.status_code == 400
    d = r.get_json()
    assert d["valid"] is False
    assert d.get("reason") == "email_mismatch"


def test_voucher_validate_not_found_has_valid_false(client):
    r = client.post("/api/voucher_validate", json={
        "code": "NONEXISTENT", "email": "x@x.it",
    })
    assert r.status_code == 404
    d = r.get_json()
    assert d["valid"] is False
    assert d.get("reason") == "not_found"


def test_amount_eur_non_numeric_does_not_crash(client):
    """Issue 1: amount_eur='abc' must NOT return 500. Treat as 0 (skip insufficient branch)."""
    code = _make_voucher("purpose_test_5@x.it", 1.0)
    r = client.post("/api/voucher_validate", json={
        "code": code, "email": "purpose_test_5@x.it",
        "purpose": "gemini", "amount_eur": "abc",
    })
    assert r.status_code != 500, r.get_data(as_text=True)
    # Non-numeric treated as 0 → success path
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d["valid"] is True


def test_rate_limit_response_includes_valid_and_reason(monkeypatch):
    """Issue 2: 429 rate-limit response must include valid:False and reason."""
    import audiobook_app as ab
    app.config['TESTING'] = True
    # Force rate limit denial
    monkeypatch.setattr(ab, "_voucher_rl_check", lambda ip, email: (False, 60, "rate_limit"))
    monkeypatch.setattr(ab, "_voucher_rl_record_result", lambda email, success: None)
    with app.test_client() as c:
        r = c.post("/api/voucher_validate", json={
            "code": "ANY", "email": "rl@x.it",
        })
    assert r.status_code == 429
    d = r.get_json()
    assert d.get("valid") is False
    assert "reason" in d
    assert d["reason"] == "rate_limit"
