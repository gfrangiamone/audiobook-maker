"""Test per POST /api/combined_estimate."""
import pytest
import audiobook_app
from epub_to_tts import BookInfo, Chapter

# NB: accesso a app/jobs/_jobs_lock via attributo a runtime, mai from-import:
# altri test (test_translation_audit_write.py, test_cold_*.py) fanno
# importlib.reload(generation_engine)/reload(audiobook_app) e ri-bindano
# audiobook_app.jobs; un from-import a collection time resterebbe legato agli
# oggetti pre-reload -> 404 "job not found" solo nella suite completa.


@pytest.fixture
def client():
    audiobook_app.app.config['TESTING'] = True
    with audiobook_app.app.test_client() as c:
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
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["cj1"] = {"info": info, "status": "analyzed"}
    yield
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop("cj1", None)


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
    """The /api/combined_estimate endpoint must honour the canonical LLM rate.

    Dopo il consolidamento la fonte unica del prezzo e' payment.llm_price_eur,
    che legge payment.LLM_RATE_EUR_PER_MCHAR. Il test patcha quella costante e
    verifica che llm_eur scali proporzionalmente. I valori restano sotto la
    soglia gratuita (default 0.50), quindi due == grezzo (nessun floor).
    """
    import payment

    payload = {
        "job_id": "cj1",
        "voice_id": "edge:it-IT-DiegoNeural",  # non-gemini => gemini_eur=0
        "selected_chapters": [0],
        "ai_opt_enabled": True,
    }

    monkeypatch.setattr(payment, "LLM_RATE_EUR_PER_MCHAR", 1.10)
    d1 = client.post("/api/combined_estimate", json=payload).get_json()

    monkeypatch.setattr(payment, "LLM_RATE_EUR_PER_MCHAR", 5.50)
    d2 = client.post("/api/combined_estimate", json=payload).get_json()

    chars = d1["llm_breakdown"]["chars"]
    assert chars > 0
    # Grezzo (sotto soglia -> nessun floor): chars * rate / 1e6, round a 2.
    assert d1["llm_eur"] == round((chars / 1_000_000.0) * 1.10, 2)
    assert d2["llm_eur"] == round((chars / 1_000_000.0) * 5.50, 2)
    assert d1["llm_breakdown"]["rate_eur_per_mchar"] == 1.10
    assert d2["llm_breakdown"]["rate_eur_per_mchar"] == 5.50
    # Sanity: cost must differ with rate.
    assert d2["llm_eur"] > d1["llm_eur"]


def test_standalone_ai_applies_min_cost_floor(client, jb, monkeypatch):
    """Regressione: voce standard + AI standalone deve mostrare l'importo
    REALMENTE dovuto (con floor minimo), non la stima grezza.

    Incidente: la stima combinata esponeva il grezzo (~0,48 €) mentre il
    voucher/PayPal addebitava il floor (1,00 €). Ora combined_estimate passa
    per payment.llm_price_eur e applica il floor sul ramo standalone.
    """
    import payment

    # Grezzo 0,60 € (300k chars * 2,00/1M) -> sopra soglia 0,20, sotto floor 1,00.
    monkeypatch.setattr(payment, "LLM_RATE_EUR_PER_MCHAR", 2.00)
    monkeypatch.setattr(payment, "LLM_FREE_THRESHOLD_EUR", 0.20)
    monkeypatch.setattr(payment, "LLM_MIN_COST_EUR", 1.00)

    ch = _make_chapter(0, "A" * 300_000)
    info = BookInfo(
        title="T", author="A", language="it", chapters=[ch],
        total_words=ch.word_count, total_chars=ch.char_count,
        estimated_duration_minutes=1.0,
    )
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["cjfloor"] = {"info": info, "status": "analyzed"}
    try:
        d = client.post("/api/combined_estimate", json={
            "job_id": "cjfloor",
            "voice_id": "edge:it-IT-DiegoNeural",  # standard => standalone LLM
            "selected_chapters": [0],
            "ai_opt_enabled": True,
        }).get_json()
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop("cjfloor", None)

    assert d["gemini_eur"] == 0
    assert d["speechify_eur"] == 0
    # Prezzo mostrato = importo dovuto con floor, NON il grezzo.
    assert d["llm_eur"] == pytest.approx(1.00)
    assert d["total_eur"] == pytest.approx(1.00)
    assert d["llm_breakdown"]["raw_eur"] == pytest.approx(0.60)
    # Sopra soglia -> non gratuito.
    assert d["is_free"] is False


def test_combined_premium_ai_not_floored(client, jb, monkeypatch):
    """Sul ramo PREMIUM combinato la quota LLM NON ha floor: resta il grezzo,
    sommato al costo TTS (il pagamento e' del totale combinato)."""
    import payment

    monkeypatch.setattr(payment, "LLM_RATE_EUR_PER_MCHAR", 2.00)
    monkeypatch.setattr(payment, "LLM_FREE_THRESHOLD_EUR", 0.20)
    monkeypatch.setattr(payment, "LLM_MIN_COST_EUR", 1.00)

    ch = _make_chapter(0, "A" * 300_000)
    info = BookInfo(
        title="T", author="A", language="it", chapters=[ch],
        total_words=ch.word_count, total_chars=ch.char_count,
        estimated_duration_minutes=1.0,
    )
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["cjprem"] = {"info": info, "status": "analyzed"}
    try:
        d = client.post("/api/combined_estimate", json={
            "job_id": "cjprem",
            "voice_id": "gemini:flash25:Zephyr",  # premium => combinato
            "selected_chapters": [0],
            "ai_opt_enabled": True,
        }).get_json()
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop("cjprem", None)

    # Quota LLM grezza (0,60), nessun floor a 1,00.
    assert d["llm_eur"] == pytest.approx(0.60)
    assert d["gemini_eur"] > 0
