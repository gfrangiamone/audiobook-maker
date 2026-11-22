"""Audit di sicurezza del 21/11/2026: i quattro rilievi gravi.

1. Un rifiuto di /api/generate rimborsava il pagamento che un'altra richiesta
   aveva consumato sullo stesso job (due POST in parallelo = libro gratis).
2. La capture PayPal non controllava la valuta: 1000 JPY valevano 1000 EUR.
3-4. `esc()` della console admin non codificava le virgolette: un valore
   dell'utente in `title="${esc(v)}"` diventava codice eseguito dall'admin.
"""
import re
import time
from pathlib import Path

import pytest

import audiobook_app
import payment

ROOT = Path(audiobook_app.__file__).resolve().parent


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    yield


def _voucher_spent(job_id, amount=1.5):
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    payment._voucher_consume(code, amount, job_id=job_id)
    return code, {"token": code, "total_eur": amount, "method": "voucher"}


def test_rejected_request_without_payment_leaves_the_other_payment(isolated_store):
    code, pocket = _voucher_spent("job-race")
    before = payment._voucher_remaining(payment._vouchers[code])
    job = {"payment": pocket}
    assert audiobook_app._refund_payment_on_orphan(
        "job-race", job, "status_conflict", own=None) is None
    assert payment._voucher_remaining(payment._vouchers[code]) == before
    assert job["payment"] is pocket


def test_rejected_request_refunds_only_its_own_payment(isolated_store):
    code_a, pocket_a = _voucher_spent("job-race2")
    code_b, own_b = _voucher_spent("job-race2")
    before_a = payment._voucher_remaining(payment._vouchers[code_a])
    before_b = payment._voucher_remaining(payment._vouchers[code_b])
    job = {"payment": pocket_a}
    audiobook_app._refund_payment_on_orphan(
        "job-race2", job, "status_conflict", own=own_b)
    assert payment._voucher_remaining(payment._vouchers[code_a]) == before_a
    assert payment._voucher_remaining(payment._vouchers[code_b]) > before_b
    assert job["payment"] is pocket_a


def test_generate_rejects_before_the_claim_pass_the_request_payment():
    src = (ROOT / "audiobook_app.py").read_text(encoding="utf-8")
    for reason in ("status_conflict", "concurrent_limit", "server_busy"):
        assert f'job, "{reason}", own=_own_payment)' in src, reason


def test_reset_to_chapters_drops_the_delivered_payment(monkeypatch):
    job_id = "a" * 22
    info = type("I", (), {"chapters": [object()]})()
    job = {"status": "done", "info": info, "client_id": "",
           "payment": {"token": "T", "total_eur": 3.0, "method": "voucher"},
           "payment_token": "T", "payment_amount_eur": 3.0}
    monkeypatch.setitem(audiobook_app.jobs, job_id, job)
    monkeypatch.setattr(audiobook_app, "_check_job_owner",
                        lambda jid: (job, None, 200))
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    c = audiobook_app.app.test_client()
    r = c.post(f"/api/reset_to_chapters/{job_id}",
               headers={"Origin": "http://localhost"})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert job["status"] == "analyzed"
    for key in ("payment", "payment_token", "payment_amount_eur"):
        assert key not in job


def _captured(currency):
    amount = {"value": "1000.00"}
    if currency:
        amount["currency_code"] = currency
    return {"payer": {"email_address": "buyer@x.it"},
            "purchase_units": [{"payments": {"captures": [{
                "id": "CAPX", "status": "COMPLETED", "amount": amount}]}}]}


@pytest.mark.parametrize("currency", ["JPY", "USD", ""])
def test_capture_in_another_currency_is_not_credited(isolated_store, monkeypatch, currency):
    monkeypatch.setattr(payment, "_paypal_capture_order", lambda oid: _captured(currency))
    with pytest.raises(payment.CaptureAmountMismatchError):
        payment.capture_and_store_order("ORDJPY1", job_id="job-cur")
    assert "ORDJPY1" not in payment._payments


def test_capture_in_eur_is_credited(isolated_store, monkeypatch):
    monkeypatch.setattr(payment, "_paypal_capture_order", lambda oid: _captured("EUR"))
    res = payment.capture_and_store_order("ORDEUR1", job_id="job-cur2")
    assert res["amount_eur"] == 1000.0 and "ORDEUR1" in payment._payments


def test_admin_esc_encodes_quotes():
    page = (ROOT / "templates" / "pages" / "admin_audit_premium.html").read_text(encoding="utf-8")
    body = re.search(r"function esc\(s\)\{(.*?)\n  \}", page, flags=re.S).group(1)
    assert "&quot;" in body and "&#39;" in body


# ---------------------------------------------------------------- medi e minori

import generation_engine
import cover_utils
import routes_mobile
import voice_clone_audio


def test_llm_refund_is_skipped_once_the_paid_text_was_delivered(monkeypatch):
    calls = []
    monkeypatch.setattr(generation_engine, "_refund_job_payment",
                        lambda *a, **k: calls.append(a))
    generation_engine._refund_llm_unless_delivered("j", {"abm_exported": True}, "x")
    generation_engine._refund_llm_unless_delivered("j", {"translated_path": "/t.epub"}, "x")
    assert calls == []
    generation_engine._refund_llm_unless_delivered("j", {}, "x")
    assert len(calls) == 1


def test_revoked_voucher_is_neither_spendable_nor_recredited(isolated_store):
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    payment._voucher_consume(code, 2.0, job_id="job-rev")
    assert payment.revoke_voucher(code, "storno")
    with pytest.raises(ValueError):
        payment._voucher_consume(code, 1.0, job_id="job-rev2")
    payment._voucher_refund(code, 2.0, job_id="job-rev")
    assert payment._voucher_remaining(payment._vouchers[code]) == 0.0
    assert payment._vouchers[code]["used"] is True


def test_rate_limit_counts_an_ipv6_by_its_64(monkeypatch):
    monkeypatch.setattr(audiobook_app, "_ip_rl_buckets", {})
    a, b = "2001:db8:1:2::1", "2001:db8:1:2:ffff::9"
    assert audiobook_app._ip_rl_check("t64", a, 1, 5)[0] is True
    assert audiobook_app._ip_rl_check("t64", b, 1, 5)[0] is False
    assert audiobook_app._ip_rl_check("t64", "2001:db8:1:3::1", 1, 5)[0] is True
    # le chiavi che non sono indirizzi restano distinte
    assert audiobook_app._ip_rl_check("t64", "cid-a", 1, 5)[0] is True
    assert audiobook_app._ip_rl_check("t64", "cid-b", 1, 5)[0] is True


def test_share_upload_must_look_like_audio():
    ok = routes_mobile._looks_like_audio
    assert ok(b"\x00\x00\x00\x20ftypM4B \x00\x00\x00\x00")
    assert ok(b"ID3\x04\x00\x00\x00\x00\x00\x00")
    assert ok(b"\xff\xfb\x90\x64")
    assert not ok(b"PK\x03\x04aaaaaaaaaaaa")
    assert not ok(b"<!doctype html>")
    assert not ok(b"MZ\x90\x00")
    assert not ok(b"")


def test_cover_bytes_that_are_not_an_image_are_not_saved(tmp_path):
    out = tmp_path / "c.jpg"
    assert cover_utils.save_cover_jpeg(b"#EXTM3U\n#EXTINF:1,\n/etc/passwd\n", str(out), (400, 600)) is False
    assert not out.exists()


def test_podcast_base_url_shape():
    ok = audiobook_app._base_url_ok
    assert ok("") and ok("https://example.org/pod")
    assert not ok("javascript:alert(1)")
    assert not ok('https://x.org/"><script>')
    assert not ok("https://x.org/" + "a" * 2100)


def test_admin_pages_keep_no_token_in_browser_storage():
    pages = ROOT / "templates" / "pages"
    for name in ("admin_gate.html", "admin_audit_premium.html", "admin_log_activity.html",
                 "admin_audit_catalog.html", "admin_community.html"):
        src = (pages / name).read_text(encoding="utf-8")
        assert "setItem('abm_admin_token'" not in src, name
        assert "getItem('abm_admin_token'" not in src, name
        assert "get('token')" not in src, name


def test_voice_samples_reach_ffmpeg_with_restricted_input():
    src = Path(voice_clone_audio.__file__).read_text(encoding="utf-8")
    assert src.count("*UNTRUSTED_INPUT") >= 3
    assert "-protocol_whitelist" in voice_clone_audio.UNTRUSTED_INPUT
    assert "(r.stderr or \"\")[-300:])" not in src.split("def convert")[1].split("def ")[0].replace(
        "print(", "")


def test_new_client_ids_carry_128_bits():
    src = (ROOT / "audiobook_app.py").read_text(encoding="utf-8")
    assert "cid = secrets.token_urlsafe(16)" in src
    assert "str(uuid.uuid4())[:12]" not in src


def test_unused_capture_is_refunded_without_bonus(isolated_store, monkeypatch):
    monkeypatch.setattr(payment, "AUTO_REFUND_UNUSED_CAPTURES", True)
    payment._payments["ORDUNUSED"] = {
        "order_id": "ORDUNUSED", "amount_eur": 10.0, "email": "buyer@x.it",
        "job_id": "job-unused", "captured_at": time.time() - 99999, "used": False}
    res = payment.refund_unused_capture("ORDUNUSED", reason="test")
    code = payment._payments["ORDUNUSED"]["refund_voucher"]
    assert res and payment._vouchers[code]["amount_eur"] == 10.0
