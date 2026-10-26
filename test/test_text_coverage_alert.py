"""Copertura del testo fatturato (incidente sLRx3imAutQ0nHWhuJTyuQ, 25/10/2026):
piano TTS sotto la soglia dei caratteri quotati -> il job prosegue, ma restano
un evento TEXT_DROP nell'activity log, i campi nell'audit e una sezione nel
digest admin."""
from datetime import datetime

import pytest

import activity_db
import activity_log
import email_service as es
import generation_engine as ge
import routes_admin_logs
import user_stats


@pytest.fixture
def eventi(monkeypatch):
    calls = []
    monkeypatch.setattr(ge, "_log_activity", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.delenv("ABM_TEXT_COVERAGE_ALERT_PCT", raising=False)
    return calls


def _job(chars_total, key="gemini_estimate", **extra):
    job = {key: {"chars_total": chars_total}, "original_filename": "libro.pdf",
           "client_id": "cid1", "client_ip": "1.2.3.4", "browser_lang": "it", "gen_epoch": 3}
    job.update(extra)
    return job


def test_drop_sotto_soglia_scrive_evento_e_prosegue(eventi):
    job = _job(481_000)
    cov = ge._check_text_coverage("J1", job, "gemini", 220_000)
    assert cov == {"chars_billed": 481_000, "plan_chars": 220_000, "pct": 45.7, "drop": True}
    assert job["text_coverage"] is cov
    (args, kw), = eventi
    assert args[:5] == ("J1", "libro.pdf", "TEXT_DROP", "cid1", "1.2.3.4")
    assert args[5] == "plan=220000 billed=481000 pct=45.7 engine=gemini opt=0"
    assert args[6] == "it" and kw == {"epoch": 3}


def test_copertura_sopra_soglia_niente_evento(eventi):
    job = _job(100_000, key="voxcpm_estimate")
    cov = ge._check_text_coverage("J2", job, "voxcpm", 95_000)
    assert cov is not None and cov["drop"] is False and cov["pct"] == 95.0
    assert eventi == []


def test_testo_ottimizzato_marcato_opt(eventi):
    job = _job(10_000, key="speechify_estimate", optimized_chapters=[{"title": "x"}])
    ge._check_text_coverage("J3", job, "speechify", 1_000)
    assert eventi[0][0][5].endswith("engine=speechify opt=1")


def test_edge_e_job_senza_stima_ignorati(eventi):
    assert ge._check_text_coverage("J4", _job(1000), "edge", 10) is None
    job = {"original_filename": "x"}
    assert ge._check_text_coverage("J5", job, "gemini", 10) is None
    assert ge._check_text_coverage("J6", _job(0), "gemini", 10) is None
    assert "text_coverage" not in job and eventi == []


def test_soglia_da_env(eventi, monkeypatch):
    monkeypatch.setenv("ABM_TEXT_COVERAGE_ALERT_PCT", "50")
    assert ge._check_text_coverage("J7", _job(100), "gemini", 60)["drop"] is False
    monkeypatch.setenv("ABM_TEXT_COVERAGE_ALERT_PCT", "0")
    assert ge._check_text_coverage("J8", _job(100), "gemini", 0)["drop"] is False
    assert eventi == []


def test_errore_mai_fatale(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("log giu'")
    monkeypatch.setattr(ge, "_log_activity", boom)
    assert ge._check_text_coverage("J9", _job(100), "gemini", 10) is None


def test_audit_tail_riporta_la_copertura():
    rec = {}
    ge._common_audit_tail(rec, {"text_coverage": {"chars_billed": 481_000, "plan_chars": 220_000,
                                                  "pct": 45.7, "drop": True}})
    assert rec["chars_billed"] == 481_000 and rec["plan_chars"] == 220_000
    assert rec["text_coverage_pct"] == 45.7 and rec["text_drop"] is True
    rec = {}
    ge._common_audit_tail(rec, {})
    assert "text_drop" not in rec


def _row(job_id, ts, payload, op="TEXT_DROP"):
    return activity_log.Row(job_id, ts, "libro.pdf", op, "cid1", "1.2.3.4", payload, "it", "")


def test_text_drop_data_un_riga_per_job(monkeypatch):
    seen = {}

    def fake_iter(since, until=None, ops=None):
        seen["ops"] = ops
        return [_row("J1", "2026-10-25 10:00:00", "plan=1 billed=10 pct=10.0 engine=gemini opt=0"),
                _row("J1", "2026-10-25 11:00:00", "plan=2 billed=10 pct=20.0 engine=gemini opt=0"),
                _row("", "2026-10-25 11:00:00", "plan=2 billed=10 pct=20.0"),
                _row("J2", "2026-10-25 12:00:00", "plan=5 billed=10 pct=50.0 engine=voxcpm opt=1")]
    monkeypatch.setattr(activity_log, "iter_rows", fake_iter)
    data = routes_admin_logs._text_drop_data()
    assert seen["ops"] == {"TEXT_DROP"} and data["window_hours"] == 24
    rows = {r["job_id"]: r for r in data["rows"]}
    assert set(rows) == {"J1", "J2"}
    assert rows["J1"]["pct"] == "20.0" and rows["J1"]["ts"] == "2026-10-25 11:00:00"
    assert rows["J2"]["engine"] == "voxcpm" and rows["J2"]["opt"] == "1"
    monkeypatch.setattr(activity_log, "iter_rows", lambda *a, **kw: [])
    assert routes_admin_logs._text_drop_data() is None


def _drop_rows():
    return [{"job_id": "J1", "ts": "2026-10-25 11:00:00", "filename": "<b>libro</b>.pdf",
             "plan": "220000", "billed": "481000", "pct": "45.7", "engine": "gemini", "opt": "1"}]


def test_blocco_html_con_escape(monkeypatch):
    monkeypatch.setattr(es, "_text_drop_provider", None)
    html = es._text_drop_block_html({"rows": _drop_rows(), "window_hours": 24})
    assert "Testo fatturato e non letto (ultime 24h)" in html
    assert "<b>libro" not in html and "&lt;b&gt;libro" in html
    assert "45.7%" in html and "gemini (AI)" in html and "481000" in html
    assert es._text_drop_block_html({"rows": []}) == ""
    assert es._text_drop_block_html() == ""          # provider assente
    es.set_text_drop_provider(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert es._text_drop_block_html() == ""


def test_digest_parte_con_le_sole_righe_text_drop(monkeypatch):
    sent = {}
    monkeypatch.setattr(es, "_send_email", lambda to, subj, html, reply_to=None: sent.update(subj=subj, html=html))
    monkeypatch.setattr(es, "_smtp_available", lambda: True)
    monkeypatch.setattr(es, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(es, "_admin_last_sent", 0.0)
    monkeypatch.setattr(es, "_admin_queue", [])
    for name in ("_funnel_provider", "_power_users_provider", "_abuse_provider", "_voice_clone_provider"):
        monkeypatch.setattr(es, name, None)
    monkeypatch.setattr(es, "_text_drop_provider", lambda: {"rows": _drop_rows(), "window_hours": 24})
    es._try_send_admin_digest()
    assert "1 job con testo non letto" in sent["subj"]
    assert "0 nuovi libri" not in sent["subj"] and "abuso" not in sent["subj"]
    assert "Testo fatturato e non letto" in sent["html"]


def test_parse_sessions_non_prende_la_voce_dal_payload():
    rows = [activity_log.Row("J1", "2026-10-25 10:00:00", "f", "GENERATE", "cid1", "1.2.3.4",
                             "it-IT-Voce", "it", ""),
            _row("J1", "2026-10-25 10:01:00", "plan=1 billed=10 pct=10.0 engine=gemini opt=0")]
    s = user_stats.parse_sessions(rows)["J1"]
    assert s["voice"] == "it-IT-Voce" and "TEXT_DROP" in s["events"]


def test_activity_db_payload_nella_colonna_detail():
    row = tuple(_row("J1", datetime(2026, 10, 25).strftime("%Y-%m-%d %H:%M:%S"),
                     "plan=1 billed=10 pct=10.0 engine=gemini opt=0"))
    rec = activity_db.to_columns(row)
    assert rec["detail"].startswith("plan=1") and rec["voice"] == ""
    assert activity_db.from_columns(rec) == row
