"""Test per POST /api/gemini_estimate."""
import pytest
from audiobook_app import app, jobs, _jobs_lock
from epub_to_tts import BookInfo, Chapter


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def _make_chapter(idx, text):
    """Costruisce un Chapter dataclass con i campi minimi richiesti."""
    ch = Chapter(
        index=idx,
        title=f"Cap{idx}",
        text=text,
    )
    return ch


@pytest.fixture
def job_with_text():
    chs = [_make_chapter(0, "Lorem ipsum dolor sit amet. " * 80)]
    info = BookInfo(
        title="Test",
        author="A",
        language="it",
        chapters=chs,
        total_words=sum(c.word_count for c in chs),
        total_chars=sum(c.char_count for c in chs),
        estimated_duration_minutes=1.0,
    )
    with _jobs_lock:
        jobs["testjob1"] = {"info": info, "status": "analyzed"}
    yield
    with _jobs_lock:
        jobs.pop("testjob1", None)


def test_gemini_estimate_returns_price_for_gemini_voice(client, job_with_text):
    r = client.post("/api/gemini_estimate", json={
        "job_id": "testjob1",
        "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0],
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    assert "user_price_eur" in data
    assert "is_free" in data
    assert data["model_key"] == "flash25"
    assert data["model_label"] == "Gemini 2.5 Flash TTS"
    assert data["chars_total"] > 0


def test_gemini_estimate_rejects_non_gemini_voice(client, job_with_text):
    r = client.post("/api/gemini_estimate", json={
        "job_id": "testjob1",
        "voice_id": "edge:it-IT-DiegoNeural",
        "selected_chapters": [0],
    })
    assert r.status_code == 400


def test_gemini_estimate_missing_job(client):
    r = client.post("/api/gemini_estimate", json={
        "job_id": "nope",
        "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0],
    })
    assert r.status_code == 404


def test_gemini_estimate_empty_selection_uses_all(client, job_with_text):
    r = client.post("/api/gemini_estimate", json={
        "job_id": "testjob1",
        "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [],
    })
    # quando selected è vuoto, deve usare TUTTI i capitoli (non errore)
    assert r.status_code == 200
    data = r.get_json()
    assert data["chars_total"] > 0
