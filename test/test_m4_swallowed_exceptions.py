"""M4 (analisi post-piano 2026-10): le sei eccezioni ingoiate hanno un esito.

- `retry_util.run_with_timeout`: il timeout dell'anteprima audio limita davvero
  (prima `with ThreadPoolExecutor` aspettava la fine del lavoro nello shutdown).
- `_accumulate_speechify_actual`: un chunk malformato viene contato in
  `skipped_chunks`, non perso in silenzio (costo sottostimato).
- `_cancel_cleanup_workdir`: un errore di pulizia finisce nel log.
- `_write_gemini_audit`: `release_reservation` fallita viene segnalata.
- `cleanup._job_service_was_delivered`: marker illeggibile = esito ignoto
  (None), e la riconciliazione del capture NON rimborsa ne' incassa.
- Il ratchet di test_module_boundaries conta `except: pass` e gli accessi a
  `payment._vouchers/_payments`.
"""
import inspect
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import audiobook_app
import cleanup
import gemini_tts
import generation_engine
import payment
import retry_util


# --- run_with_timeout -------------------------------------------------------

def test_run_with_timeout_ritorna_il_risultato():
    assert retry_util.run_with_timeout(lambda: 42, 1.0) == 42


def test_run_with_timeout_non_aspetta_la_fine_del_lavoro():
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        retry_util.run_with_timeout(lambda: time.sleep(1.5), 0.1)
    assert time.monotonic() - t0 < 1.0


def test_run_with_timeout_rilancia_l_eccezione_del_lavoro():
    class Boom(RuntimeError):
        pass

    def _fn():
        raise Boom("x")

    with pytest.raises(Boom):
        retry_util.run_with_timeout(_fn, 1.0)


def test_anteprima_audio_usa_run_with_timeout_non_l_executor():
    src = inspect.getsource(audiobook_app.api_preview_audio)
    assert "retry_util.run_with_timeout(_generate, _wrapper_timeout)" in src
    assert "ThreadPoolExecutor" not in src
    assert "except TimeoutError:" in src


# --- speechify actual ----------------------------------------------------------

def _sa_job():
    return {"speechify_actual": {"chars": 0, "billable_chars": 0,
                                 "audio_seconds": 0.0, "model_key": None}}


def test_speechify_chunk_malformato_contato_non_perso(capsys):
    job = _sa_job()
    generation_engine._accumulate_speechify_actual(
        job, {"text": "ciao"}, {"billable_chars": "boh", "bytes_written": 10})
    sa = job["speechify_actual"]
    assert sa["skipped_chunks"] == 1
    assert sa["chars"] == 0 and sa["billable_chars"] == 0   # niente scrittura a meta'
    assert "chunk non contabilizzato" in capsys.readouterr().out


def test_speechify_chunk_valido_invariato():
    job = _sa_job()
    generation_engine._accumulate_speechify_actual(
        job, {"text": "ciao"}, {"billable_chars": 4, "bytes_written": 96000, "sample_rate": 48000})
    sa = job["speechify_actual"]
    assert sa["chars"] == 4 and sa["billable_chars"] == 4
    assert abs(sa["audio_seconds"] - 1.0) < 1e-6
    assert "skipped_chunks" not in sa


# --- cancel cleanup work_dir ------------------------------------------------

def test_cancel_cleanup_workdir_logga_l_errore(capsys):
    class _BadDir:
        def exists(self):
            raise PermissionError("disco negato")

    generation_engine._cancel_cleanup_workdir({}, "j-m4", _BadDir(), partial_audio_delivered=False)
    assert "pulizia work_dir fallita: disco negato" in capsys.readouterr().out


# --- release_reservation --------------------------------------------------------

def test_release_reservation_fallita_viene_segnalata(monkeypatch, capsys):
    def _boom(job_id):
        raise RuntimeError("lock rotto")

    monkeypatch.setattr(gemini_tts, "release_reservation", _boom)
    job = {"payment": {"token": "X", "total_eur": 2.0, "method": "paypal"},
           "gemini_actual": {"google_cost_eur": 0.3, "chars": 1000, "audio_seconds": 30.0},
           "rate": "+0%"}
    captured = {}
    with patch("generation_engine.gemini_cost_audit.append_record",
               side_effect=lambda r: captured.update(r)):
        generation_engine._write_gemini_audit("j-m4", job, "gemini:flash31:Zephyr", "it", "completed")
    assert captured.get("outcome") == "completed"      # l'audit e' stato scritto comunque
    assert "release_reservation fallita: lock rotto" in capsys.readouterr().out


# --- cleanup: marker illeggibile ----------------------------------------------

@pytest.fixture
def cleanup_store(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "AUTO_REFUND_UNUSED_CAPTURES", True)
    monkeypatch.setattr(audiobook_app, "ADMIN_EMAIL", "")
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    return tmp_path


def _unused_capture(order_id, job_id):
    payment._payments[order_id] = {
        "order_id": order_id, "amount_eur": 2.27, "email": "buyer@x.it",
        "job_id": job_id, "captured_at": time.time(), "used": False,
        "used_at": None, "capture_id": "C" + order_id,
    }


def test_marker_illeggibile_e_esito_ignoto(cleanup_store):
    # Il marker e' una cartella: read_text solleva OSError su ogni piattaforma.
    (cleanup_store / "job-io" / cleanup.EMAIL_MARKER_FILENAME).mkdir(parents=True)
    assert cleanup._job_service_was_delivered("job-io") is None
    assert cleanup._job_service_was_delivered("job-senza-marker") is False
    (cleanup_store / "job-ok").mkdir()
    (cleanup_store / "job-ok" / cleanup.EMAIL_MARKER_FILENAME).write_text("1700000000", encoding="utf-8")
    assert cleanup._job_service_was_delivered("job-ok") is True


def test_esito_ignoto_non_rimborsa_ne_incassa(cleanup_store, capsys):
    (cleanup_store / "job-io" / cleanup.EMAIL_MARKER_FILENAME).mkdir(parents=True)
    _unused_capture("ORD_IO", "job-io")
    cleanup._reconcile_unused_capture_for_job("job-io", "stale analyzed")
    pay = payment._payments["ORD_IO"]
    assert pay["used"] is False                 # nessun settle
    assert not pay.get("refund_voucher")        # nessun rimborso
    assert len(payment._vouchers) == 0
    assert "riconciliazione rinviata" in capsys.readouterr().out


def test_marker_assente_rimborsa_come_prima(cleanup_store):
    _unused_capture("ORD_NO", "job-no")
    cleanup._reconcile_unused_capture_for_job("job-no", "stale analyzed")
    assert payment._payments["ORD_NO"]["used"] is True
    assert len(payment._vouchers) == 1


# --- cancel: rimborso di fallback fallito -------------------------------------------

def test_rimborso_di_fallback_fallito_lascia_traccia():
    src = inspect.getsource(generation_engine.run_generation)
    i = src.index('_refund_gemini_payment(job_id, job, "cancelled", retained_eur=0.0)')
    tail = src[i:i + 900]
    assert '"REFUND_FAILED"' in tail and 'job["refund_error"]' in tail
    assert "except Exception:\n                    pass" not in tail


# --- ratchet ---------------------------------------------------------------------

def test_il_ratchet_conta_le_eccezioni_mute_e_lo_stato_privato_di_payment():
    src = (Path(__file__).with_name("test_module_boundaries.py")).read_text(encoding="utf-8")
    assert '("silent_except", ' in src and '("payment_private_state", ' in src
    base = json.loads(Path(__file__).with_name("boundaries_baseline.json").read_text(encoding="utf-8"))
    assert base["silent_except"] and base["payment_private_state"]
