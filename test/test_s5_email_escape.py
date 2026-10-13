"""S5 (2026-10-12): il titolo del libro (metadati del file caricato) e l'URL
del podcast (dal body di /api/register_email) entravano nell'HTML delle email
senza escape: HTML e link a scelta di chi carica il file, spediti dal dominio
del servizio. Ora `title_html` nei cinque builder, URL escapati nella sezione
podcast, `base_url` solo http(s) all'ingresso."""
import types
from unittest.mock import patch

import pytest

import audiobook_app
import email_service
import generation_engine as ge

TITLE = '<a href="https://evil.test">Libro</a> & "Co"'
BAD_URL = 'https://pods.test/"><script>alert(1)</script>'
CID = "cid_s5_test"


def _capture(send_fn, job):
    job_id = "s5-job"
    sent = []
    ge._jobs[job_id] = job
    try:
        with patch.object(email_service, "_send_email", side_effect=lambda to, subj, html: sent.append((subj, html)) or True), \
             patch.object(ge, "_save_tokens", lambda: None), \
             patch.object(ge, "_log_activity", lambda *a, **k: None), \
             patch.object(ge, "_write_email_marker", None), \
             patch.object(ge.pending_jobs, "finalize", lambda jid: None), \
             patch.object(ge, "BASE_URL", "https://example.test"):
            send_fn(job_id)
    finally:
        ge._jobs.pop(job_id, None)
        for t in list(ge._download_tokens):
            if isinstance(ge._download_tokens[t], dict) and ge._download_tokens[t].get("job_id") == job_id:
                ge._download_tokens.pop(t, None)
    assert len(sent) == 1
    return sent[0]


def _job(**extra):
    j = {"status": "done", "client_id": CID, "notify_email": "x@example.test", "email_registered": True,
         "notify_lang": "it", "original_filename": "x.epub", "voice": "it-IT-ElsaNeural", "rate": "+0%",
         "info": types.SimpleNamespace(title=TITLE, author="A", language="it"), "last_poll": 0,
         "notify_download_type": "audio", "output_format": "m4b"}
    j.update(extra)
    return j


def test_completion_email_escapes_the_title_in_html_only():
    subj, html = _capture(ge._send_completion_email, _job())
    assert '<a href="https://evil.test">' not in html
    assert "&lt;a href=&quot;https://evil.test&quot;&gt;Libro&lt;/a&gt; &amp; &quot;Co&quot;" in html
    assert TITLE in subj                                   # il subject e' testo, non HTML


def test_podcast_email_escapes_base_url_and_rss_url():
    subj, html = _capture(ge._send_completion_email, _job(
        notify_download_type="podcast", notify_base_url=BAD_URL, podcast_safe_name="libro", podcast_ready=True))
    assert "<script>" not in html and 'href="https://pods.test/"' not in html
    assert "&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_every_builder_escapes_the_title_in_the_body():
    for texts in (ge._completion_email_texts(TITLE, 24), ge._opt_email_texts(TITLE, 24),
                  ge._opt_failed_email_texts(TITLE, 1.0), ge._premium_failed_email_texts(TITLE, 1.0, "", ""),
                  ge._tr_email_texts(TITLE, 24)):
        for lang, t in texts.items():
            assert "<a href" not in t["body"] and "&lt;a href" in t["body"], lang
            assert TITLE in t["subject"], lang


@pytest.fixture
def job(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_abuse_note", lambda *a, **k: None, raising=False)
    j = {"status": "generating", "client_id": CID, "original_filename": "x.epub", "created_at": 0, "last_poll": 0}
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["s5-job"] = j
    yield j
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop("s5-job", None)


def test_register_email_accepts_only_http_urls(job):
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", CID)
        for bad in ("javascript:alert(1)", BAD_URL, "ftp://x", "https://x y", "https://" + "a" * 2050):
            r = c.post("/api/register_email", json={"job_id": "s5-job", "email": "a@example.com",
                                                    "download_type": "podcast", "base_url": bad})
            assert r.status_code == 400 and r.get_json()["error"] == "invalid_base_url", bad
        r = c.post("/api/register_email", json={"job_id": "s5-job", "email": "a@example.com",
                                                "download_type": "podcast", "base_url": "https://pods.example.test/"})
        assert r.status_code == 200 and job["notify_base_url"] == "https://pods.example.test/"
