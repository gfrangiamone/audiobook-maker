"""Sezione «Casi di abuso» del digest admin: solo hash e contatori."""
import email_service as es


def _rows():
    return [{"group": "net:abcdef0123456789", "signals": {"S1": True, "S2": True, "S3": False, "S4": True},
             "cids_n": 2, "verdict": "abuse", "confidence": 0.93, "scope": "cids",
             "reason": "one voice, 103 files in 2 days", "kills": 3, "blocks": 12,
             "unjudged": 0, "generate_24h": 40, "chars_24h": 9_500_000},
            {"group": "net:ffff000011112222", "signals": {"S1": True, "S2": False, "S3": True, "S4": False},
             "cids_n": 1, "verdict": "", "confidence": 0.0, "scope": "", "reason": "",
             "kills": 0, "blocks": 0, "unjudged": 2, "generate_24h": 3, "chars_24h": 12_000}]


def test_abuse_block_html_renders_rows_and_mode():
    es.set_abuse_provider(lambda: {"rows": _rows(), "window_hours": 24, "kill_enabled": True})
    html = es._abuse_block_html()
    assert "Casi di abuso" in html and "kill attiva" in html
    assert "net:abcdef0123456789" in html and "S1 S2 S4" in html
    assert "abuse (0.93, cids)" in html and "103 files" in html
    assert ">3<" in html and ">12<" in html and "non giudicat" in html
    assert "/admin/api/abuse/clear/" in html
    es.set_abuse_provider(None)


def test_abuse_block_html_observation_mode_and_empty():
    es.set_abuse_provider(lambda: {"rows": _rows()[:1], "window_hours": 24, "kill_enabled": False})
    assert "solo osservazione" in es._abuse_block_html()
    es.set_abuse_provider(lambda: {"rows": [], "window_hours": 24, "kill_enabled": True})
    assert es._abuse_block_html() == ""
    es.set_abuse_provider(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert es._abuse_block_html() == ""
    es.set_abuse_provider(None)
    assert es._abuse_block_html() == ""


def test_abuse_block_escapes_reason():
    rows = _rows()[:1]
    rows[0]["reason"] = "<script>alert(1)</script>"
    es.set_abuse_provider(lambda: {"rows": rows, "window_hours": 24, "kill_enabled": True})
    html = es._abuse_block_html()
    assert "<script>" not in html and "&lt;script&gt;" in html
    es.set_abuse_provider(None)


def test_audiobook_app_provider_wraps_abuse_watch(monkeypatch, tmp_path):
    import abuse_watch as aw
    import audiobook_app
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "0")
    assert audiobook_app._abuse_digest_data() is None
    g = aw.group_key("3.3.3.3", "z")
    aw.record_event(g, "z", "generate", {"chars": 5})
    aw.record_judgement_failed(g, "timeout")
    d = audiobook_app._abuse_digest_data()
    assert d["rows"][0]["group"] == g and d["kill_enabled"] is False and d["window_hours"] == 24
