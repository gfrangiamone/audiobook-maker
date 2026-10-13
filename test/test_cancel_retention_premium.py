"""Cancel dei job premium senza audio parziale (VoxCPM/Speechify): trattenuta
proporzionale solo sul cancel utente, email col buono PayPal, capitoli
conservati per il riuso (incidente vTq5ItTo--xGTcjoVDWHMg, 13/10/2026)."""
from unittest.mock import patch

import pytest

import chunk_reuse
import email_service
import generation_engine
import tts_engines


def _job(method="paypal", reason="user", chars=285_558, paid=4.02):
    return {
        "payment": {"token": "PAY-1", "total_eur": paid, "method": method},
        "cancel_reason": reason,
        "voice": "voxcpm:v2:en-US/Brooke",
        "gen_lang": "en",
        "voxcpm_actual": {"chars": chars},
        "original_filename": "book.pdf",
        "browser_lang": "en",
    }


@pytest.fixture
def vox_price(monkeypatch):
    """Listino VoxCPM lineare: 10 EUR per Mchar, senza soglia gratuita."""
    import voxcpm_tts

    def _price(chars, language=None):
        lp = round(int(chars or 0) * 10 / 1_000_000, 2)
        return {"list_price_eur": lp, "user_price_eur": lp}
    monkeypatch.setattr(voxcpm_tts, "compute_user_price_eur", _price)


def _run(job, refund_result=None):
    with patch.object(generation_engine, "_refund_gemini_payment",
                      return_value=refund_result) as ref, \
         patch.object(generation_engine, "_write_premium_audit") as audit, \
         patch.object(generation_engine, "_send_cancel_email") as mail:
        generation_engine._cancel_refund_no_partial("j1", job, job["voice"], None, "voxcpm")
    return ref, audit, mail


# --- listino consumato per motore ------------------------------------------

def test_consumed_list_price_voxcpm(vox_price):
    job = _job(chars=300_000)
    assert tts_engines.ENGINES["voxcpm"].consumed_list_price_eur(job, job["voice"], "en") == 3.0


def test_consumed_list_price_speechify_prefers_billable(monkeypatch):
    import speechify_tts
    seen = {}

    def _price(chars):
        seen["chars"] = chars
        return {"list_price_eur": 1.5}
    monkeypatch.setattr(speechify_tts, "compute_user_price_eur", _price)
    job = {"speechify_actual": {"chars": 900, "billable_chars": 1000}}
    assert tts_engines.ENGINES["speechify"].consumed_list_price_eur(job) == 1.5
    assert seen["chars"] == 1000


def test_consumed_list_price_without_measures_is_zero():
    assert tts_engines.ENGINES["voxcpm"].consumed_list_price_eur({}, "voxcpm:v2:en-US/Brooke") == 0.0


# --- trattenuta -------------------------------------------------------------

def test_user_cancel_retains_consumed_share(vox_price):
    job = _job()  # 285.558 caratteri -> 2,86 EUR di listino su 4,02 pagati
    ref, audit, mail = _run(job, {"method": "paypal", "email": "u@x.it",
                                  "voucher_code": "REF-1"})
    assert ref.call_args.kwargs["retained_eur"] == pytest.approx(2.86)
    assert job["cancel_meta"]["refund_eur"] == pytest.approx(1.16)
    assert audit.call_args.args[4] == "cancelled_partial"
    mail.assert_called_once()
    assert mail.call_args.args[-1] is None  # nessun link di download


def test_retention_capped_at_paid(vox_price):
    job = _job(chars=900_000, paid=4.02)
    _run(job)
    assert job["cancel_meta"]["retained_eur"] == pytest.approx(4.02)
    assert job["cancel_meta"]["refund_eur"] == 0.0


@pytest.mark.parametrize("reason,extra", [
    ("heartbeat", {}), ("abuse", {}), ("user", {"server_interrupted": True}),
])
def test_non_user_cancel_full_refund(vox_price, reason, extra):
    job = _job(reason=reason)
    job.update(extra)
    ref, audit, _ = _run(job)
    assert ref.call_args.kwargs["retained_eur"] == 0.0
    assert job["cancel_meta"]["refund_eur"] == pytest.approx(4.02)
    assert audit.call_args.args[4] == "cancelled_refunded"


def test_voucher_payment_refund_is_silent(vox_price):
    _, _, mail = _run(_job(method="voucher"), {"method": "voucher", "email": "u@x.it"})
    mail.assert_not_called()


def test_retention_error_falls_back_to_full_refund(vox_price):
    job = _job()
    with patch.object(generation_engine, "_cancel_retention", side_effect=RuntimeError("x")):
        ref, _, _ = _run(job)
    assert ref.call_args.kwargs["retained_eur"] == 0.0


# --- anteprima della modale -------------------------------------------------

def test_cancel_preview_amounts_voxcpm(vox_price):
    out = generation_engine.cancel_preview_amounts(_job())
    assert out == {"engine": "voxcpm", "paid_eur": 4.02, "retained_eur": 2.86,
                   "refund_eur": 1.16, "partial_audio": False}


def test_cancel_preview_amounts_none_for_standard_or_unpaid():
    assert generation_engine.cancel_preview_amounts({"voice": "it-IT-ElsaNeural"}) is None
    assert generation_engine.cancel_preview_amounts({"voice": "voxcpm:v2:en-US/Brooke"}) is None


# --- email senza audio parziale ----------------------------------------------

def test_cancel_email_without_partial_audio(monkeypatch):
    sent = {}
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)
    monkeypatch.setattr(email_service, "_send_email",
                        lambda to, subj, body: sent.update(subj=subj, body=body))
    email_service._send_gemini_cancelled_partial_email(
        "u@x.it", 4.02, 2.86, 1.16, "REF-1", "Book", None, lang="en")
    assert "partial audio" not in sent["subj"]
    assert "1.16 EUR" in sent["subj"]
    assert "REF-1" in sent["body"] and 'href=""' not in sent["body"]


def test_cancel_email_with_partial_audio_keeps_download(monkeypatch):
    sent = {}
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)
    monkeypatch.setattr(email_service, "_send_email",
                        lambda to, subj, body: sent.update(subj=subj, body=body))
    email_service._send_gemini_cancelled_partial_email(
        "u@x.it", 2.0, 0.5, 1.5, None, "Book", "https://x/dl/t/download", lang="it")
    assert "audio parziale" in sent["subj"] and "https://x/dl/t/download" in sent["body"]


# --- capitoli conservati per il riuso ----------------------------------------

def test_cancel_cleanup_keeps_reusable_chunks(tmp_path):
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "chunk_000000.pcm").write_bytes(b"xx")
    (wd / "prompt_1.txt").write_text("p", encoding="utf-8")
    chunk_reuse.write_manifest(wd, {"engine": "voxcpm"})
    generation_engine._cancel_cleanup_workdir({}, "j1", wd, partial_audio_delivered=False)
    assert (wd / "chunk_000000.pcm").exists()
    assert chunk_reuse.read_manifest(wd) == {"engine": "voxcpm"}
    assert not (wd / "prompt_1.txt").exists()


def test_cancel_cleanup_without_reusable_manifest_removes_workdir(tmp_path):
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "chunk_000000.pcm").write_bytes(b"xx")
    chunk_reuse.write_manifest(wd, {"engine": "speechify"})
    generation_engine._cancel_cleanup_workdir({}, "j1", wd, partial_audio_delivered=False)
    assert not wd.exists()
