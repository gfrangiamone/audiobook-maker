"""Test per POST /api/combined_estimate."""
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
    return Chapter(index=idx, title=f"Cap{idx}", text=text)


@pytest.fixture
def jb():
    # Testo grande per generare un costo LLM > 0 (>= 1k chars dopo rate 1.10/Mchars).
    # Per ottenere llm_eur > 0 dopo round(x, 2), serve almeno ~5000 chars.
    txt = "A" * 50000
    ch = _make_chapter(0, txt)
    info = BookInfo(
        title="T",
        author="A",
        language="it",
        chapters=[ch],
        total_words=ch.word_count,
        total_chars=ch.char_count,
        estimated_duration_minutes=1.0,
    )
    with _jobs_lock:
        jobs["cj1"] = {"info": info, "status": "analyzed"}
    yield
    with _jobs_lock:
        jobs.pop("cj1", None)


def test_combined_both(client, jb):
    r = client.post("/api/combined_estimate", json={
        "job_id": "cj1",
        "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0],
        "ai_opt_enabled": True,
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d["gemini_eur"] > 0
    assert d["llm_eur"] > 0
    assert d["total_eur"] == pytest.approx(d["gemini_eur"] + d["llm_eur"], abs=0.01)
    assert "is_free" in d
    assert "threshold_eur" in d


def test_combined_standard_voice_no_gemini(client, jb):
    r = client.post("/api/combined_estimate", json={
        "job_id": "cj1",
        "voice_id": "edge:it-IT-DiegoNeural",
        "selected_chapters": [0],
        "ai_opt_enabled": True,
    })
    assert r.status_code == 200
    d = r.get_json()
    assert d["gemini_eur"] == 0
    assert d["llm_eur"] > 0


def test_combined_no_ai_opt(client, jb):
    r = client.post("/api/combined_estimate", json={
        "job_id": "cj1",
        "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0],
        "ai_opt_enabled": False,
    })
    assert r.status_code == 200
    d = r.get_json()
    assert d["llm_eur"] == 0
    assert d["gemini_eur"] > 0


def test_combined_missing_job(client):
    r = client.post("/api/combined_estimate", json={
        "job_id": "nope",
        "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0],
        "ai_opt_enabled": False,
    })
    assert r.status_code == 404
