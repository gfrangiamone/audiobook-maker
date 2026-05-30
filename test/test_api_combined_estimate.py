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


def test_llm_rate_respects_module_constant(client, jb, monkeypatch):
    """The /api/combined_estimate endpoint must honour the canonical
    module-level LLM_RATE_EUR_PER_MCHAR constant (driven by
    ABM_LLM_RATE_EUR_PER_MCHAR), not a private/typo'd env var.

    Patches the rate to two distinct values and asserts the returned
    llm_eur scales proportionally.
    """
    import audiobook_app

    payload = {
        "job_id": "cj1",
        "voice_id": "edge:it-IT-DiegoNeural",  # non-gemini => gemini_eur=0
        "selected_chapters": [0],
        "ai_opt_enabled": True,
    }

    monkeypatch.setattr(audiobook_app, "LLM_RATE_EUR_PER_MCHAR", 1.10)
    d1 = client.post("/api/combined_estimate", json=payload).get_json()

    monkeypatch.setattr(audiobook_app, "LLM_RATE_EUR_PER_MCHAR", 5.50)
    d2 = client.post("/api/combined_estimate", json=payload).get_json()

    chars = d1["llm_breakdown"]["chars"]
    assert chars > 0
    # Exact formula: chars * rate / 1e6, rounded to 2.
    assert d1["llm_eur"] == round((chars / 1_000_000.0) * 1.10, 2)
    assert d2["llm_eur"] == round((chars / 1_000_000.0) * 5.50, 2)
    assert d1["llm_breakdown"]["rate_eur_per_mchar"] == 1.10
    assert d2["llm_breakdown"]["rate_eur_per_mchar"] == 5.50
    # Sanity: cost must differ with rate.
    assert d2["llm_eur"] > d1["llm_eur"]
