"""Recovery orfani: un job già consegnato non deve essere rimborsato.

Il descrittore di recupero restava aperto quando il COMPLETE non passava
dall'invio email (job mobile senza notify_email, o SMTP fallito): a ogni
riavvio _recover_orphan_jobs bumpava attempts e, superato il cap,
_orphan_fallback emetteva un voucher di rimborso su un audiolibro in realtà
già consegnato. Qui si verifica che l'activity log faccia da prova di consegna.
"""
import time
import pytest
import payment
import audiobook_app


def _write_activity(script_dir, lines):
    ym = time.strftime("%Y-%m")
    path = script_dir / f"activity_{ym}.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _activity_line(job_id, op):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    return f'{job_id} # {ts} # "book.epub" # {op} # cid # 1.2.3.4 # it-IT-X # it'


@pytest.fixture
def recovery_env(monkeypatch, tmp_path):
    """SCRIPT_DIR isolata, cache consegne azzerata, store pagamenti su tmp."""
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", tmp_path)
    audiobook_app._delivered_ids_cache["value"] = None
    audiobook_app._delivered_ids_cache["expires"] = 0.0
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    calls = {"finalize": [], "mark_failed": []}
    monkeypatch.setattr(audiobook_app.pending_jobs, "finalize",
                        lambda jid: calls["finalize"].append(jid))
    monkeypatch.setattr(audiobook_app.pending_jobs, "mark_failed",
                        lambda jid: calls["mark_failed"].append(jid))
    monkeypatch.setattr(audiobook_app, "_send_interrupted_email",
                        lambda rec, refund_code=None: None)
    yield tmp_path, calls
    audiobook_app._delivered_ids_cache["value"] = None
    audiobook_app._delivered_ids_cache["expires"] = 0.0


def _paid_rec(job_id, phase="generate"):
    payment._payments["ORD_" + job_id] = {
        "order_id": "ORD_" + job_id, "amount_eur": 9.0, "email": "buyer@x.it",
        "captured_at": time.time(), "used": True, "used_for_job": job_id,
    }
    return {"id": job_id, "phase": phase, "notify_email": "",
            "payment": {"token": "ORD_" + job_id, "total_eur": 9.0, "method": "paypal"}}


def test_delivered_job_is_closed_without_refund(recovery_env):
    tmp_path, calls = recovery_env
    _write_activity(tmp_path, [_activity_line("jobDELIVERED", "COMPLETE")])
    rec = _paid_rec("jobDELIVERED")
    audiobook_app._orphan_fallback("jobDELIVERED", rec)
    assert payment._vouchers == {}          # nessun rimborso
    assert calls["finalize"] == ["jobDELIVERED"]
    assert calls["mark_failed"] == []


def test_job_without_complete_is_refunded(recovery_env):
    tmp_path, calls = recovery_env
    _write_activity(tmp_path, [_activity_line("jobOTHER", "COMPLETE")])
    rec = _paid_rec("jobLOST")
    audiobook_app._orphan_fallback("jobLOST", rec)
    assert len(payment._vouchers) == 1      # rimborso emesso
    assert calls["mark_failed"] == ["jobLOST"]
    assert calls["finalize"] == []


def test_optimize_phase_accepts_opt_complete(recovery_env):
    tmp_path, calls = recovery_env
    _write_activity(tmp_path, [_activity_line("jobOPT", "OPT_COMPLETE")])
    rec = _paid_rec("jobOPT", phase="optimize")
    audiobook_app._orphan_fallback("jobOPT", rec)
    assert payment._vouchers == {}
    assert calls["finalize"] == ["jobOPT"]


def test_generate_phase_ignores_opt_complete(recovery_env):
    """OPT_COMPLETE senza COMPLETE = audio mai prodotto: il rimborso è dovuto."""
    tmp_path, calls = recovery_env
    _write_activity(tmp_path, [_activity_line("jobGEN", "OPT_COMPLETE")])
    rec = _paid_rec("jobGEN", phase="generate")
    audiobook_app._orphan_fallback("jobGEN", rec)
    assert len(payment._vouchers) == 1
    assert calls["mark_failed"] == ["jobGEN"]


def test_missing_activity_log_does_not_block_refund(recovery_env):
    _tmp, calls = recovery_env  # nessun file di log scritto
    rec = _paid_rec("jobNOLOG")
    audiobook_app._orphan_fallback("jobNOLOG", rec)
    assert len(payment._vouchers) == 1
    assert calls["mark_failed"] == ["jobNOLOG"]
