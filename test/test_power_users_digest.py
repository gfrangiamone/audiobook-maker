"""Sezione "power user" del digest admin: user_stats.power_users + blocco HTML."""
from datetime import datetime

import user_stats

STD = "en-US-AriaNeural"
PREM = "gemini:flash25:Zephyr"


def _line(sid, ts, fn, op, cid, ip, voice=STD, lang="en", plat="web"):
    return f'{sid} # {ts} # "{fn}" # {op} # {cid} # {ip} # {voice} # {lang} # {plat}'


def _write_log(tmp_path, lines, ym="2026-08"):
    p = tmp_path / f"activity_{ym}.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_power_users_counts_and_threshold(tmp_path):
    since = datetime(2026, 8, 30, 12, 0, 0)
    lines = []
    # heavy: 6 GENERATE recenti (1 premium), 1 REUSE, 1 gate, 1 block, 2 IP, 3 COMPLETE nel mese
    for i in range(5):
        lines.append(_line(f"h{i}", f"2026-08-30 {12 + i}:30:00", "Book z-lib.org.epub", "GENERATE", "heavy", "1.1.1.1"))
    lines.append(_line("hp", "2026-08-30 18:00:00", "x.epub", "GENERATE", "heavy", "2.2.2.2", voice=PREM))
    lines.append(_line("hr", "2026-08-30 19:00:00", "x.epub", "REUSE", "heavy", "2.2.2.2"))
    lines.append(_line("hg", "2026-08-30 19:10:00", "x.epub", "QUOTA_GATE", "heavy", "2.2.2.2"))
    lines.append(_line("hb", "2026-08-30 19:20:00", "x.epub", "QUOTA_BLOCK", "heavy", "2.2.2.2"))
    lines.append(_line("ha", "2026-08-30 19:30:00", "Book z-lib.org.epub", "ANALYZE", "heavy", "2.2.2.2"))
    lines.append(_line("ha2", "2026-08-30 19:31:00", "Anna's Archive - x.pdf", "ANALYZE", "heavy", "2.2.2.2"))
    for i in range(3):
        lines.append(_line(f"hc{i}", f"2026-08-0{i + 1} 10:00:00", "x.epub", "COMPLETE", "heavy", "1.1.1.1"))
    # vecchio: 10 GENERATE ma fuori finestra 24h
    for i in range(10):
        lines.append(_line(f"o{i}", f"2026-08-10 10:{i:02d}:00", "y.epub", "GENERATE", "old", "3.3.3.3"))
    # light: 2 GENERATE recenti -> sotto soglia
    lines.append(_line("l1", "2026-08-30 13:00:00", "z.epub", "GENERATE", "light", "4.4.4.4"))
    lines.append(_line("l2", "2026-08-30 14:00:00", "z.epub", "GENERATE", "light", "4.4.4.4"))
    p = _write_log(tmp_path, lines)

    rows = user_stats.power_users([p], since, min_jobs=5,
                                  quota_table={"heavy": {"chars": 12_000_000, "jobs": 9, "gated": 1}})
    assert [r["client_id"] for r in rows] == ["heavy"]
    h = rows[0]
    assert h["jobs_24h"] == 6 and h["reuse_24h"] == 1 and h["premium_24h"] == 1
    assert h["gate_24h"] == 1 and h["block_24h"] == 1
    assert h["books_month"] == 3 and h["starts_month"] == 6
    assert h["chars_month"] == 12_000_000 and h["gated_month"] == 1
    assert h["ips_24h"] == 2 and h["platform"] == "web" and h["langs"] == ["en"]
    assert h["sources"] == {"zlib": 1, "anna": 1}


def test_power_users_ip_fallback_and_missing_file(tmp_path):
    since = datetime(2026, 8, 30, 0, 0, 0)
    lines = [_line(f"a{i}", f"2026-08-30 0{i}:00:00", "b.epub", "GENERATE", "", "9.9.9.9") for i in range(3)]
    p = _write_log(tmp_path, lines)
    rows = user_stats.power_users([p, tmp_path / "activity_2026-07.log"], since, min_jobs=3)
    assert rows and rows[0]["client_id"] == "ip:9.9.9.9" and rows[0]["jobs_24h"] == 3
    assert user_stats.power_users([p], since, min_jobs=4) == []


def test_grey_source_hints():
    assert user_stats.grey_source("Dune (z-lib.org).epub") == "zlib"
    assert user_stats.grey_source("Anna’s Archive - Dune.pdf") == "anna"
    assert user_stats.grey_source("libgen.li 1234.epub") == "libgen"
    assert user_stats.grey_source("Dune.epub") == ""


def test_digest_block_html_with_rows_and_without():
    import email_service as es
    es.set_power_users_provider(lambda: {
        "rows": [{"client_id": "abc-<x>", "jobs_24h": 7, "reuse_24h": 2, "premium_24h": 0,
                  "gate_24h": 1, "block_24h": 0, "books_month": 40, "starts_month": 44,
                  "chars_month": 12_500_000, "gated_month": 3, "ips_24h": 2,
                  "platform": "web", "langs": ["en", "it"], "sources": {"zlib": 5}}],
        "min_jobs": 5, "quota_limit_chars": 10_000_000, "window_hours": 24})
    html = es._power_users_block_html()
    assert "Power user" in html and "abc-&lt;x&gt;" in html
    assert "7 (riusi 2)" in html and "12,500,000 (125%)" in html and "oltre quota: 3" in html
    assert "zlib:5" in html and "en, it" in html
    es.set_power_users_provider(lambda: {"rows": []})
    assert es._power_users_block_html() == ""
    es.set_power_users_provider(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert es._power_users_block_html() == ""
    es.set_power_users_provider(None)
    assert es._power_users_block_html() == ""


def test_digest_html_includes_power_block(monkeypatch):
    import email_service as es
    sent = {}
    monkeypatch.setattr(es, "_send_email", lambda to, subj, html, reply_to=None: sent.update(html=html))
    monkeypatch.setattr(es, "_smtp_available", lambda: True)
    monkeypatch.setattr(es, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(es, "_admin_last_sent", 0.0)
    monkeypatch.setattr(es, "_admin_queue", [{
        "timestamp": "10:00", "title": "T", "author": "A", "filename": "f.epub",
        "chapters": 1, "words": 10, "duration_est": "1m", "voice": STD}])
    es.set_funnel_provider(None)
    es.set_power_users_provider(lambda: {
        "rows": [{"client_id": "pu-1", "jobs_24h": 9}], "min_jobs": 5,
        "quota_limit_chars": 0, "window_hours": 24})
    try:
        es._try_send_admin_digest()
    finally:
        es.set_power_users_provider(None)
    assert "pu-1" in sent.get("html", "")


def test_power_users_counts_abuse_ops(tmp_path):
    since = datetime(2026, 8, 30, 12, 0, 0)
    lines = [_line(f"g{i}", f"2026-08-30 {13 + i}:00:00", "b.epub", "GENERATE", "bad", "5.5.5.5")
             for i in range(5)]
    lines.append(_line("k1", "2026-08-30 19:00:00", "b.epub", "QUOTA_ABUSE_KILL", "bad", "5.5.5.5"))
    lines.append(_line("k2", "2026-08-30 19:05:00", "b.epub", "QUOTA_ABUSE_BLOCK", "bad", "5.5.5.5"))
    lines.append(_line("k3", "2026-08-01 19:05:00", "b.epub", "QUOTA_ABUSE_BLOCK", "bad", "5.5.5.5"))
    p = _write_log(tmp_path, lines)
    rows = user_stats.power_users([p], since, min_jobs=5)
    assert rows[0]["client_id"] == "bad" and rows[0]["abuse_24h"] == 2


def test_power_users_visible_below_min_jobs_with_abuse_events(tmp_path):
    """Un cid con pochi GENERATE (sotto min_jobs) ma con kill/block anti-abuso
    deve restare visibile nel pannello power user (issue #9): il criterio
    abuse_24h > 0 e' una OR indipendente dalla soglia jobs_24h."""
    since = datetime(2026, 8, 30, 12, 0, 0)
    lines = [_line("g1", "2026-08-30 13:00:00", "b.epub", "GENERATE", "sneaky", "6.6.6.6")]
    lines.append(_line("k1", "2026-08-30 13:05:00", "b.epub", "QUOTA_ABUSE_KILL", "sneaky", "6.6.6.6"))
    p = _write_log(tmp_path, lines)
    rows = user_stats.power_users([p], since, min_jobs=5)
    assert [r["client_id"] for r in rows] == ["sneaky"]
    assert rows[0]["jobs_24h"] == 1 and rows[0]["abuse_24h"] == 1
