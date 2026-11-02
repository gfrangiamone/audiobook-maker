"""IndexNow (2026-11-02): chiave da ABM_INDEXNOW_KEY, file chiave su
/<chiave>.txt, invio dei soli URL della sitemap con lastmod cambiato."""
import json

import pytest

import audiobook_app
import indexnow
import routes_pages as rp

KEY = "0123456789abcdef0123456789abcdef"
BASE = "https://audiobook-maker.example"

SITEMAP = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
  <url>
    <loc>{BASE}/</loc>
    <lastmod>2026-11-01</lastmod>
    <xhtml:link rel="alternate" hreflang="it" href="{BASE}/it/"/>
  </url>
  <url>
    <loc>{BASE}/guide/m4b-format/</loc>
    <lastmod>2026-10-20</lastmod>
  </url>
</urlset>"""


class _Resp:
    def __init__(self, status):
        self.status_code = status


class _Post:
    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.calls = []

    def __call__(self, url, json=None, timeout=None, headers=None):
        self.calls.append((url, json))
        return _Resp(self.statuses.pop(0))


@pytest.fixture
def on(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_INDEXNOW_KEY", KEY)
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    return tmp_path


def _sync(post, xml=SITEMAP, base=BASE):
    return indexnow.sync(lambda: xml, lambda: base, post=post, sleep=lambda s: None)


def test_key_validation(monkeypatch):
    monkeypatch.delenv("ABM_INDEXNOW_KEY", raising=False)
    assert indexnow.key() == ""
    monkeypatch.setenv("ABM_INDEXNOW_KEY", "  " + KEY + " ")
    assert indexnow.key() == KEY
    for bad in ("short", "has space inside", "x" * 129, "bad/slash1"):
        monkeypatch.setenv("ABM_INDEXNOW_KEY", bad)
        assert indexnow.key() == "", bad


@pytest.mark.parametrize("base,ok", [
    ("https://audiobook-maker.com", True),
    ("https://audiobook-maker.com/", True),
    ("http://audiobook-maker.com", False),
    ("http://localhost:5601", False),
    ("https://localhost:5601", False),
    ("https://app.localhost", False),
    ("https://staging.test", False),
    ("", False),
])
def test_only_public_https_base(base, ok):
    assert indexnow.is_public_base(base) is ok


def test_entries_ignore_alternates_and_diff_by_lastmod():
    e = indexnow.sitemap_entries(SITEMAP)
    assert e == {f"{BASE}/": "2026-11-01", f"{BASE}/guide/m4b-format/": "2026-10-20"}
    assert indexnow.changed_urls(e, {}) == sorted(e)
    assert indexnow.changed_urls(e, {f"{BASE}/": "2026-11-01", f"{BASE}/guide/m4b-format/": "2026-10-01"}) \
        == [f"{BASE}/guide/m4b-format/"]


def test_sync_sends_changed_then_nothing(on):
    post = _Post(202)
    assert _sync(post) == 2
    url, payload = post.calls[0]
    assert url == indexnow.ENDPOINT
    assert payload["host"] == "audiobook-maker.example" and payload["key"] == KEY
    assert payload["keyLocation"] == f"{BASE}/{KEY}.txt"
    assert sorted(payload["urlList"]) == [f"{BASE}/", f"{BASE}/guide/m4b-format/"]
    state = json.loads((on / "_indexnow_sent.json").read_text(encoding="utf-8"))
    assert state == indexnow.sitemap_entries(SITEMAP)
    # Stessa sitemap: nessun POST.
    assert _sync(_Post()) == 0
    # Un solo lastmod cambiato: parte solo quell'URL; URL spariti dalla sitemap escono dallo stato.
    newer = SITEMAP.replace("2026-10-20", "2026-11-02")
    post = _Post(200)
    assert _sync(post, xml=newer) == 1
    assert post.calls[0][1]["urlList"] == [f"{BASE}/guide/m4b-format/"]


def test_sync_rejected_keeps_state_and_retries_transient(on):
    assert _sync(_Post(403)) == 0
    assert not (on / "_indexnow_sent.json").exists()
    post = _Post(429, 503, 202)
    assert _sync(post) == 2
    assert len(post.calls) == 3


def test_sync_off_without_key_or_public_base(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ABM_INDEXNOW_KEY", raising=False)
    assert _sync(_Post()) == 0
    monkeypatch.setenv("ABM_INDEXNOW_KEY", KEY)
    assert _sync(_Post(), base="http://localhost:5601") == 0
    assert indexnow.start(lambda: SITEMAP, lambda: "http://localhost:5601") is None


def test_key_file_route(monkeypatch):
    audiobook_app.app.config["TESTING"] = True
    c = audiobook_app.app.test_client()
    monkeypatch.delenv("ABM_INDEXNOW_KEY", raising=False)
    assert c.get(f"/{KEY}.txt").status_code == 404
    monkeypatch.setenv("ABM_INDEXNOW_KEY", KEY)
    r = c.get(f"/{KEY}.txt")
    assert r.status_code == 200 and r.get_data(as_text=True) == KEY
    assert r.headers["Content-Type"].startswith("text/plain")
    assert c.get("/someotherkey123.txt").status_code == 404
    assert c.get("/robots.txt").status_code == 200          # le route .txt statiche vincono


def test_sitemap_xml_outside_request_feeds_indexnow(monkeypatch):
    monkeypatch.setattr(audiobook_app, "BASE_URL", BASE)
    xml = rp.sitemap_xml()
    e = indexnow.sitemap_entries(xml)
    assert f"{BASE}/" in e and f"{BASE}/guide/m4b-format/" in e and f"{BASE}/guide/m4b-format/it/" in e
    assert len(e) == xml.count("<loc>")
    monkeypatch.setattr(audiobook_app, "BASE_URL", "")
    assert rp.sitemap_xml() is None
