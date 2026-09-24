"""Lettori del business log in audiobook_app dopo il passaggio ad activity_log."""
from datetime import datetime, timedelta

import pytest

import activity_log
import audiobook_app


def _line(job, ts, op, fn="a.epub", cid="c", ip="1.1.1.1", voice="it-IT-X",
          lang="it", plat="web"):
    return f'{job} # {ts} # "{fn}" # {op} # {cid} # {ip} # {voice} # {lang} # {plat}'


def _write_by_month(d, lines_with_ts):
    """lines_with_ts: [(datetime, riga)] -> un file per mese."""
    by_month = {}
    for when, line in lines_with_ts:
        by_month.setdefault(when.strftime("%Y-%m"), []).append(line)
    for ym, lines in by_month.items():
        with open(d / f"activity_{ym}.log", "a", encoding="utf-8") as f:
            f.write("".join(l + "\n" for l in lines))


@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", tmp_path)
    activity_log.reset()
    for c in (audiobook_app._stats_today_cache, audiobook_app._stats_month_cache):
        c["value"] = None
        c["expires"] = 0.0
    yield tmp_path
    activity_log.reset()
    for c in (audiobook_app._stats_today_cache, audiobook_app._stats_month_cache):
        c["value"] = None
        c["expires"] = 0.0


def test_statistiche_community_contano_anche_i_titoli_col_cancelletto(logs):
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    _write_by_month(logs, [
        (now, _line("J1", ts, "COMPLETE", voice="it-IT-DiegoNeural")),
        (now, _line("J2", ts, "OPT_COMPLETE", fn="Saga # 2.epub", voice="en-US-GuyNeural")),
        (now, _line("J3", ts, "GENERATE", voice="it-IT-DiegoNeural")),
        (now, _line("J4", ts, "COMPLETE", voice="")),
    ])
    assert audiobook_app._stats_today_count() == 3
    res = audiobook_app._stats_month_by_lang()
    assert res["monthly"] == 3
    assert {r["lang"]: r["count"] for r in res["top"]} == {"it": 1, "en": 1}
    assert res["other"] == 0


def test_statistiche_community_escludono_ieri_dal_conteggio_di_oggi(logs):
    now = datetime.now()
    ieri = now - timedelta(days=1)
    _write_by_month(logs, [
        (ieri, _line("OLD", ieri.strftime("%Y-%m-%d %H:%M:%S"), "COMPLETE")),
        (now, _line("NEW", now.strftime("%Y-%m-%d %H:%M:%S"), "COMPLETE")),
    ])
    assert audiobook_app._stats_today_count() == 1


def test_sessioni_admin_ignorano_le_righe_senza_job_e_reggono_byte_rotti(logs):
    raw = (
        ' # 2026-08-01 09:00:00 # "" # ADMIN_TTS_PROBE #  # 9.9.9.9 # k # avviata=True # \n'
        ' # 2026-08-01 09:01:00 # "" # VOUCHER_ATTEMPT #  # 9.9.9.9 # AB12... # ok # \n'
    ).encode("utf-8") + b"\xff\xfe\n" + (
        _line("J1", "2026-08-01 10:00:00", "GENERATE", fn="Saga # 2.epub", cid="cidA") + "\n"
        + _line("J1", "2026-08-01 10:30:00", "COMPLETE", fn="Saga # 2.epub", cid="cidA") + "\n"
    ).encode("utf-8")
    (logs / "activity_2026-08.log").write_bytes(raw)

    sessions, per_client = audiobook_app._parse_log_sessions("2026-08")

    assert list(sessions) == ["J1"]
    s = sessions["J1"]
    assert s["filename"] == "Saga # 2.epub"
    assert s["events"] == ["GENERATE", "COMPLETE"] and s["last_op"] == "COMPLETE"
    assert per_client == {"cidA": 1}


def test_sessioni_admin_mese_assente(logs):
    assert audiobook_app._parse_log_sessions("2026-01") == ({}, {})


def test_sessioni_admin_m4b_non_sovrascrive_voce_sessione(logs):
    """Item 1: generation_engine._log_m4b_progress scrive il proprio payload
    libero (size_mb=... elapsed_s=... pct=... status=...) nel campo voice
    delle righe M4B_*. La sessione deve conservare la voce reale del GENERATE."""
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    _write_by_month(logs, [
        (now, _line("J1", ts, "GENERATE", voice="gemini:Kore")),
        (now, _line("J1", ts, "M4B_START", voice="size_mb=12.3")),
        (now, _line("J1", ts, "M4B_END", voice="elapsed_s=8 pct=100 status=ok")),
    ])
    sessions, _ = audiobook_app._parse_log_sessions(now.strftime("%Y-%m"))
    s = sessions["J1"]
    assert s["voice"] == "gemini:Kore"
    # Le righe M4B_* contano comunque come eventi della sessione.
    assert s["events"] == ["GENERATE", "M4B_START", "M4B_END"]
    assert s["last_op"] == "M4B_END"


def test_pagina_admin_regge_byte_non_utf8(logs, monkeypatch):
    from unittest.mock import patch
    ym = datetime.now().strftime("%Y-%m")
    (logs / f"activity_{ym}.log").write_bytes(
        b"\xff\xfe\n" + _line("J1", f"{ym}-01 10:00:00", "COMPLETE").encode("utf-8") + b"\n")
    # ADMIN_TOKEN vuoto fa uscire la route con 404 prima del controllo auth
    # patchato: adattamento di plumbing rispetto al brief, non nella logica.
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    with patch("audiobook_app._admin_auth_ok", return_value=True):
        r = audiobook_app.app.test_client().get("/admin/log-activity")
    assert r.status_code == 200


def test_export_xlsx_regge_byte_non_utf8(logs, monkeypatch):
    """Item 4: /admin/log-activity/export (xlsx) non deve rompersi quando il
    file del mese contiene byte non-UTF8 (stesso fixture del test equivalente
    per /admin/log-activity)."""
    from unittest.mock import patch
    ym = datetime.now().strftime("%Y-%m")
    (logs / f"activity_{ym}.log").write_bytes(
        b"\xff\xfe\n" + _line("J1", f"{ym}-01 10:00:00", "COMPLETE").encode("utf-8") + b"\n")
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    with patch("audiobook_app._admin_auth_ok", return_value=True):
        r = audiobook_app.app.test_client().get("/admin/log-activity/export")
    assert r.status_code == 200


def test_power_users_data_legge_il_mese_corrente(logs, monkeypatch):
    monkeypatch.setattr(audiobook_app, "POWER_USER_JOBS_PER_DAY", 3)
    now = datetime.now()
    righe = []
    for i in range(3):
        when = now - timedelta(minutes=10 * (i + 1))
        righe.append((when, _line(f"p{i}", when.strftime("%Y-%m-%d %H:%M:%S"),
                                  "GENERATE", cid="heavy", voice="en-US-AriaNeural")))
    _write_by_month(logs, righe)
    data = audiobook_app._power_users_data()
    assert [r["client_id"] for r in data["rows"]] == ["heavy"]
    assert data["rows"][0]["jobs_24h"] == 3


def test_endpoint_user_stats_invalida_la_cache_quando_il_log_cresce(logs, monkeypatch):
    from unittest.mock import patch
    # ADMIN_TOKEN vuoto fa uscire la route con 404 prima del controllo auth
    # patchato: stesso adattamento di plumbing di test_pagina_admin_regge_byte_non_utf8.
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    audiobook_app._USER_STATS_CACHE.clear()
    p = logs / "activity_2026-08.log"
    p.write_text(_line("J1", "2026-08-01 10:00:00", "COMPLETE", cid="a") + "\n", encoding="utf-8")
    with patch("audiobook_app._admin_auth_ok", return_value=True):
        c = audiobook_app.app.test_client()
        d1 = c.get("/api/admin/user_stats?ym=2026-08").get_json()
        with open(p, "a", encoding="utf-8") as f:
            f.write(_line("J2", "2026-08-01 11:00:00", "COMPLETE", cid="b") + "\n")
        d2 = c.get("/api/admin/user_stats?ym=2026-08").get_json()
    audiobook_app._USER_STATS_CACHE.clear()
    assert d1["coorti"]["totale"]["generazioni"] == 1
    assert d2["coorti"]["totale"]["generazioni"] == 2
    assert d2["file"] == "activity_2026-08.log"
