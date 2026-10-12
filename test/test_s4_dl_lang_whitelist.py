"""S4 (2026-10-12): `lang` del body di /api/register_email finiva nel token di
download e poi in `<html lang="__P0__">` delle pagine /dl senza whitelist:
un link legittimo spedito dal server alla vittima eseguiva JavaScript
sull'origine dell'app. Ora `i18n.safe_lang` all'ingresso (register_email,
consegna email) e in ogni pagina /dl, podcast index compreso."""
import pytest

import audiobook_app
import i18n
import routes_dl

CID = "cid_s4_test"
EVIL = '"><svg onload=alert(1)>'


def test_safe_lang_whitelist():
    assert i18n.safe_lang("it-IT") == "it" and i18n.safe_lang("ZH") == "zh"
    for bad in (EVIL, "xx", "", None, "it<script>", "en\n"):
        assert i18n.safe_lang(bad) == "en", bad
    assert i18n.safe_lang("fr", supported=("en", "it")) == "en"


@pytest.fixture
def job(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_abuse_note", lambda *a, **k: None, raising=False)
    j = {"status": "generating", "client_id": CID, "original_filename": "x.epub",
         "created_at": 0, "last_poll": 0}
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["s4-job"] = j
    yield j
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop("s4-job", None)


def test_register_email_stores_only_a_supported_lang(job):
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", CID)
        r = c.post("/api/register_email", json={"job_id": "s4-job", "email": "a@example.com", "lang": EVIL})
        assert r.status_code == 200, r.get_json()
        assert job["notify_lang"] == "en"
        r = c.post("/api/register_email", json={"job_id": "s4-job", "email": "a@example.com", "lang": "it-IT"})
        assert r.status_code == 200 and job["notify_lang"] == "it"


def test_arm_email_delivery_normalizes_lang(job):
    audiobook_app._arm_email_delivery(job, "s4-job", "a@example.com", lang=EVIL)
    assert job["notify_lang"] == "en"


def test_every_dl_page_renders_a_safe_html_lang(tmp_path):
    pages = [
        routes_dl._render_dl_expired_page(EVIL, retention_hours=24),
        routes_dl._render_dl_deleted_page(EVIL),
        routes_dl._render_dl_cooldown_page(EVIL, seconds=30),
        routes_dl._render_dl_page("tok", "Libro", "23h", "audio", lang=EVIL),
    ]
    for html in pages:
        assert EVIL not in html and "<svg onload" not in html
        assert 'lang="en"' in html
    routes_dl._generate_podcast_index_html(str(tmp_path), "T", "A", "", "feed.xml", ["001.mp3"], language=EVIL)
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert EVIL not in index and 'lang="en"' in index
