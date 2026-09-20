"""Polling di /admin/log-activity in una sola richiesta: /api/admin/jobs_progress.

Origine: in produzione la pagina lanciava ogni 5 s una fetch parallela per
ogni job in corso (`/api/job_status/<sid>`); con piu' di 20 job vivi il
bucket nginx per IP (10 r/s, burst 20) si svuotava e la richiesta della
modale Stats prendeva 503 (`limit_req`). Un endpoint bulk = una richiesta
per tick, qualunque sia il numero di card.
"""
from unittest.mock import patch

import pytest

import audiobook_app as app


@pytest.fixture
def client():
    app.app.config["TESTING"] = True
    return app.app.test_client()


@pytest.fixture
def live_jobs():
    saved = dict(app.jobs)
    app.jobs.clear()
    app.jobs.update({
        "gen1": {"status": "generating", "progress_current": 25, "progress_total": 100,
                 "progress_message": "cap 3"},
        "opt1": {"status": "optimizing", "opt_total_chars": 1000,
                 "opt_processed_chars": 500, "opt_current_chapter_chars": 200,
                 "opt_streamed_chars": 999},
        "tr1": {"status": "translating", "tr_progress_current": 3, "tr_progress_total": 4},
        "done1": {"status": "done"},
    })
    yield
    app.jobs.clear()
    app.jobs.update(saved)


def test_requires_admin_auth(client, live_jobs):
    with patch.object(app, "_admin_auth_ok", return_value=False):
        r = client.get("/api/admin/jobs_progress?ids=gen1")
    assert r.status_code == 403


def test_one_request_returns_every_requested_job(client, live_jobs):
    with patch.object(app, "_admin_auth_ok", return_value=True):
        r = client.get("/api/admin/jobs_progress?ids=gen1,opt1,tr1,done1")
    assert r.status_code == 200
    d = r.get_json()
    assert d["gen1"] == {"status": "generating", "pct": 25}
    # streamed clampato ai char del capitolo corrente: (500+200)/1000
    assert d["opt1"] == {"status": "optimizing", "pct": 70}
    assert d["tr1"] == {"status": "translating", "pct": 75}
    assert d["done1"] == {"status": "done", "pct": 0}


def test_unknown_ids_are_omitted_not_errors(client, live_jobs):
    with patch.object(app, "_admin_auth_ok", return_value=True):
        r = client.get("/api/admin/jobs_progress?ids=gen1,ghost,,%20")
    assert r.status_code == 200
    assert set(r.get_json().keys()) == {"gen1"}


def test_empty_ids_is_empty_dict(client, live_jobs):
    with patch.object(app, "_admin_auth_ok", return_value=True):
        r = client.get("/api/admin/jobs_progress")
    assert r.status_code == 200
    assert r.get_json() == {}


def test_single_job_status_endpoint_agrees_with_bulk(client, live_jobs):
    """Stessa aritmetica del pct: l'endpoint singolo (kill modal) e il bulk
    devono usare la stessa funzione, non due copie."""
    with patch.object(app, "_admin_auth_ok", return_value=True), \
         patch.object(app, "_check_job_owner",
                      side_effect=lambda jid: (app.jobs[jid], None, 200)):
        single = client.get("/api/job_status/opt1").get_json()
        bulk = client.get("/api/admin/jobs_progress?ids=opt1").get_json()
    assert single["pct"] == bulk["opt1"]["pct"] == 70


def test_admin_page_polls_with_one_bulk_request(admin_log_page):
    html = admin_log_page
    assert "/api/admin/jobs_progress?ids=" in html
    # il polling periodico non deve piu' aprire una fetch per card
    poll = html[html.index("async function updateLiveProgress"):]
    poll = poll[:poll.index("\nif (document.querySelectorAll('.live-timer')")]
    assert "/api/job_status/" not in poll
    assert "Promise.all" not in poll
