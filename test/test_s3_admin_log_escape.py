"""S3 (2026-10-12): il job_id del body di /api/paypal_capture_order finiva
grezzo nel log delle attivita' e poi, senza escape, nella card della console
admin (XSS memorizzato col cookie admin); un a capo nel campo falsificava
righe intere del log. Ora: forma del job_id nel route (test_s1), campi del
log senza caratteri di controllo, escape di sid/cid/ip nella card."""
from collections import OrderedDict
from datetime import datetime

import pytest

import activity_log
import routes_admin_logs

EVIL = '<img src=x onerror=alert(1)>'


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "off")
    prev = activity_log._log_dir
    activity_log.configure(lambda: tmp_path)
    activity_log.reset()
    activity_log.sync_all()
    yield tmp_path
    activity_log.reset()
    activity_log.configure(prev)


def test_log_fields_cannot_forge_lines(log_dir):
    activity_log.log("J1\nJ2 # 2026-01-01 00:00:00 # \"x\" # COMPLETE # c # 1.1.1.1 # v # it # web",
                     "Saga # 2\r\n.epub", "GENERATE", client_id="c1\n", ip="1.2.3.4",
                     voice="it-IT-X\x00", lang="it")
    files = list(log_dir.glob("activity_*.log"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert text.count("\n") == 1 and "\r" not in text and "\x00" not in text
    rows = list(activity_log.month_rows(datetime.now().strftime("%Y-%m")))
    assert len(rows) == 1 and rows[0].op == "GENERATE"
    assert rows[0].filename == "Saga # 2 .epub"             # nel nome file `#` resta, a capo no
    assert rows[0].job_id.startswith("J1 J2 ＃ ") and "#" not in rows[0].job_id
    assert rows[0].client_id == "c1" and rows[0].voice == "it-IT-X"   # il parser fa strip


def test_admin_card_escapes_session_id_client_and_ip(monkeypatch):
    session = {
        "session_id": EVIL, "first_dt": datetime(2026, 6, 1, 10, 0, 0),
        "last_dt": datetime(2026, 6, 1, 10, 5, 0), "filename": "test.epub",
        "last_op": "COMPLETE", "events": ["ANALYZE", "GENERATE", "COMPLETE"],
        "client_id": '"><b>c</b>', "client_ip": "1.1.1.1<svg onload=1>",
        "voice": "it-IT-Isola", "browser_lang": "it",
    }
    monkeypatch.setattr(routes_admin_logs, "_jobs", lambda: {}, raising=False)
    html = routes_admin_logs._log_card_html(EVIL, session, {'"><b>c</b>': 1}, {}, datetime(2026, 6, 1, 11))
    assert EVIL not in html and "<svg onload" not in html and "<b>c</b>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert 'data-sid="&lt;img' in html
    assert "1.1.1.1&lt;svg onload=1&gt;" in html
