# test/test_translate_endpoints.py
import time
import pytest
from unittest.mock import patch

import audiobook_app


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


@pytest.fixture(autouse=True)
def _bootstrap(monkeypatch):
    """Translation configurata + jobs puliti tra i test."""
    monkeypatch.setattr(audiobook_app.translation_core, "is_available",
                        lambda: True, raising=False)
    audiobook_app.jobs.clear()
    yield
    audiobook_app.jobs.clear()


class _Ch:
    def __init__(self, index, title, text):
        self.index, self.title, self.text = index, title, text
        self.char_count = len(text)
        self.word_count = len(text.split())


class _Info:
    title = "Libro"
    author = "A"
    language = "it"
    def __init__(self):
        self.chapters = [_Ch(1, "Uno", "x" * 100_000),
                         _Ch(2, "Due", "y" * 300_000)]


def _seed(job_id="TJ1", status="analyzed", **extra):
    job = {"status": status, "client_id": "c1", "client_ip": "127.0.0.1",
           "info": _Info(), "original_filename": "libro.epub",
           "last_poll": time.time()}
    job.update(extra)
    audiobook_app.jobs[job_id] = job
    return job


def _own(job_id="TJ1"):
    return patch("audiobook_app._check_job_owner",
                 return_value=(audiobook_app.jobs[job_id], None, None))


def test_estimate_translation(client):
    _seed()
    with _own():
        r = client.get("/api/translate_estimate/TJ1?target=en&optimize=0")
    assert r.status_code == 200
    d = r.get_json()
    assert d["chars"] == 400_000
    assert d["requires_payment"] is True
    assert d["due_eur"] == max(round(0.4 * audiobook_app.payment.TRANSLATE_RATE_EUR_PER_MCHAR, 2),
                               audiobook_app.payment.TRANSLATE_MIN_COST_EUR)


def test_estimate_translation_selected_chapters(client):
    _seed()
    with _own():
        r = client.get("/api/translate_estimate/TJ1?target=en&selected_chapters=1")
    assert r.get_json()["chars"] == 100_000


def test_translate_rejects_same_lang(client):
    _seed()
    with _own():
        r = client.post("/api/translate", json={
            "job_id": "TJ1", "source_lang": "it", "target_lang": "it",
            "output_format": "abm"})
    assert r.status_code == 400


def test_translate_rejects_bad_format(client):
    _seed()
    with _own():
        r = client.post("/api/translate", json={
            "job_id": "TJ1", "source_lang": "it", "target_lang": "en",
            "output_format": "pdf"})
    assert r.status_code == 400


def test_translate_requires_payment_above_threshold(client):
    _seed()
    with _own():
        r = client.post("/api/translate", json={
            "job_id": "TJ1", "source_lang": "it", "target_lang": "en",
            "output_format": "abm"})
    assert r.status_code == 402


def test_translate_free_book_starts_thread(client, monkeypatch):
    job = _seed()
    job["info"].chapters = [_Ch(1, "Uno", "x" * 10_000)]  # sotto soglia
    started = []
    monkeypatch.setattr(audiobook_app, "run_translation",
                        lambda jid: started.append(jid), raising=False)
    import threading
    real_thread = threading.Thread
    monkeypatch.setattr(threading, "Thread",
                        lambda target, args, daemon: real_thread(
                            target=lambda: target(*args), daemon=True))
    with _own():
        r = client.post("/api/translate", json={
            "job_id": "TJ1", "source_lang": "it", "target_lang": "en",
            "output_format": "txt", "output_name": "libro"})
    assert r.status_code == 200
    assert job["status"] == "translating"
    assert job["tr_params"]["target_lang"] == "en"


def test_translate_concurrency_limit(client, monkeypatch):
    # In dev ABM_MAX_CONCURRENT_LLM_PER_CLIENT puo' essere >1; forziamo 1.
    monkeypatch.setattr(audiobook_app, "MAX_CONCURRENT_LLM_PER_CLIENT", 1)
    _seed("TJ1")
    _seed("TJ2", status="translating")
    with _own("TJ1"):
        r = client.post("/api/translate", json={
            "job_id": "TJ1", "source_lang": "it", "target_lang": "en",
            "output_format": "abm"})
    assert r.status_code == 429


def test_translate_cancel_sets_flag(client):
    job = _seed(status="translating")
    with _own():
        r = client.post("/api/translate_cancel/TJ1")
    assert r.status_code == 200
    assert job["tr_cancelled"] is True


def test_translate_batch_bad_email_does_not_consume_voucher(client, monkeypatch):
    _seed()  # 400k chars -> a pagamento
    # Voucher con saldo sufficiente
    audiobook_app.payment._vouchers["VTEST1"] = {
        "code": "VTEST1", "email": "u@x.it", "amount_eur": 10.0,
        "remaining_eur": 10.0, "expires_at": time.time() + 86400,
        "used": False, "uses": [],
    }
    try:
        with _own():
            r = client.post("/api/translate", json={
                "job_id": "TJ1", "source_lang": "it", "target_lang": "en",
                "output_format": "abm", "payment_token": "VTEST1",
                "batch": True, "email": "non-una-email"})
        assert r.status_code == 400
        v = audiobook_app.payment._vouchers["VTEST1"]
        # Il voucher NON deve essere stato scalato
        assert audiobook_app.payment._voucher_remaining(v) == 10.0
        # E il claim deve essere stato rilasciato
        assert audiobook_app.jobs["TJ1"]["status"] == "analyzed"
    finally:
        audiobook_app.payment._vouchers.pop("VTEST1", None)


def test_download_translation(client, tmp_path):
    f = tmp_path / "libro.txt"
    f.write_text("tradotto", encoding="utf-8")
    _seed(status="translated", translated_path=str(f),
          translated_name="libro.txt")
    with _own():
        r = client.get("/api/download_translation/TJ1")
    assert r.status_code == 200
    assert b"tradotto" in r.data


def test_dl_token_translated(client, tmp_path):
    f = tmp_path / "libro.epub"
    f.write_bytes(b"PK fake epub")
    audiobook_app._download_tokens["tok-tr-1"] = {
        "job_id": "TJ9", "created_at": time.time(),
        "download_type": "translated",
        "translated_path": str(f), "translated_name": "libro.epub",
        "book_title": "Libro", "lang": "it", "is_gemini": False,
    }
    try:
        r = client.get("/dl/tok-tr-1/translated")
        assert r.status_code == 200
        assert b"PK fake epub" in r.data
    finally:
        audiobook_app._download_tokens.pop("tok-tr-1", None)


def test_dl_token_translated_expired(client, tmp_path):
    audiobook_app._download_tokens["tok-tr-2"] = {
        "job_id": "TJ9", "created_at": time.time() - 10 * 365 * 86400,
        "download_type": "translated",
        "translated_path": "/nope", "translated_name": "x.txt",
        "book_title": "Libro", "lang": "it", "is_gemini": False,
    }
    try:
        r = client.get("/dl/tok-tr-2/translated")
        assert r.status_code == 410
    finally:
        audiobook_app._download_tokens.pop("tok-tr-2", None)


def test_paypal_create_order_translate_amount(client, monkeypatch):
    _seed("TJP")
    captured = {}

    def _fake_create(amount_eur, *a, **kw):
        captured["amount"] = amount_eur
        return {"id": "OID1", "status": "CREATED"}

    # Forza la disponibilità PayPal e intercetta il vero helper di creazione
    # ordine (payment._paypal_create_order, importato in audiobook_app).
    monkeypatch.setattr(audiobook_app, "_paypal_available",
                        lambda: True, raising=False)
    monkeypatch.setattr(audiobook_app, "_paypal_create_order",
                        _fake_create, raising=False)
    with _own("TJP"):
        r = client.post("/api/paypal_create_order_translate", json={
            "job_id": "TJP", "target_lang": "en", "optimize": False,
            "selected_chapters": [1, 2]})
    # 400.000 chars × 3.0/M = 1.20 → floor 1.50
    assert r.status_code == 200
    assert captured.get("amount") == 1.5
    assert r.get_json()["order_id"] == "OID1"


def test_translate_adopt_replaces_chapters(client):
    job = _seed(status="translated",
                translated_lang="en", translated_optimized=True,
                translated_chapters=[
                    {"index": 1, "title": "One", "text": "Translated one."},
                    {"index": 2, "title": "Two", "text": "Translated two."},
                ])
    with _own():
        r = client.post("/api/translate_adopt/TJ1")
    assert r.status_code == 200
    d = r.get_json()
    assert job["status"] == "analyzed"
    assert job["info"].language == "en"
    assert [c.title for c in job["info"].chapters] == ["One", "Two"]
    assert job["info"].chapters[0].text == "Translated one."
    assert job["ai_optimized"] is True
    assert sorted(job["optimized_chapters"]) == [1, 2]
    assert d["language"] == "en"
    assert len(d["chapters"]) == 2


def test_translate_adopt_requires_translated_status(client):
    _seed(status="analyzed")
    with _own():
        r = client.post("/api/translate_adopt/TJ1")
    assert r.status_code == 400


def test_paypal_create_order_translate_free_book(client, monkeypatch):
    job = _seed("TJF")
    job["info"].chapters = [_Ch(1, "Uno", "x" * 10_000)]  # sotto soglia free
    monkeypatch.setattr(audiobook_app, "_paypal_available", lambda: True)
    with _own("TJF"):
        r = client.post("/api/paypal_create_order_translate", json={
            "job_id": "TJF", "target_lang": "en", "optimize": False})
    assert r.status_code == 400


# __ /api/translate_title (spec 2026-06-06-translated-title-filename) __

def _mock_title_llm(monkeypatch, replies):
    """Mocka il layer LLM del titolo; ritorna la lista delle chiamate."""
    calls = []
    monkeypatch.setattr(audiobook_app.translation_core, "resolve_backend",
                        lambda: "apikey")
    monkeypatch.setattr(audiobook_app.translation_core, "make_client_provider",
                        lambda b: ((lambda: None), "m", "http://x"))
    def _tt(provider, titles, s, t, **kw):
        calls.append(list(titles))
        return replies
    monkeypatch.setattr(audiobook_app.translation_core, "translate_titles", _tt)
    return calls


def test_translate_title_returns_translation(client, monkeypatch):
    _seed()
    calls = _mock_title_llm(monkeypatch, ["The Book"])
    with _own():
        r = client.get("/api/translate_title/TJ1?target=en&source=it")
    assert r.status_code == 200
    assert r.get_json()["title"] == "The Book"
    assert calls == [["Libro"]]


def test_translate_title_cached_second_call(client, monkeypatch):
    _seed()
    calls = _mock_title_llm(monkeypatch, ["The Book"])
    with _own():
        client.get("/api/translate_title/TJ1?target=en&source=it")
        r2 = client.get("/api/translate_title/TJ1?target=en&source=it")
    assert r2.get_json()["title"] == "The Book"
    assert len(calls) == 1  # seconda risposta dalla cache


def test_translate_title_same_lang_no_llm(client, monkeypatch):
    _seed()
    calls = _mock_title_llm(monkeypatch, ["BOOM"])
    with _own():
        r = client.get("/api/translate_title/TJ1?target=it&source=it")
    assert r.get_json()["title"] == "Libro"
    assert calls == []


def test_translate_title_unavailable_empty(client, monkeypatch):
    _seed()
    monkeypatch.setattr(audiobook_app.translation_core, "is_available",
                        lambda: False)
    with _own():
        r = client.get("/api/translate_title/TJ1?target=en&source=it")
    assert r.status_code == 200
    assert r.get_json()["title"] == ""


def test_translate_title_bad_target_empty(client, monkeypatch):
    _seed()
    with _own():
        r = client.get("/api/translate_title/TJ1?target=123&source=it")
    assert r.get_json()["title"] == ""


def test_translate_title_llm_error_silent(client, monkeypatch):
    _seed()
    monkeypatch.setattr(audiobook_app.translation_core, "resolve_backend",
                        lambda: "apikey")
    monkeypatch.setattr(audiobook_app.translation_core, "make_client_provider",
                        lambda b: ((lambda: None), "m", "http://x"))
    def _boom(*a, **kw):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(audiobook_app.translation_core, "translate_titles", _boom)
    with _own():
        r = client.get("/api/translate_title/TJ1?target=en&source=it")
    assert r.status_code == 200
    assert r.get_json()["title"] == ""


def test_translate_title_source_fallback_info_language(client, monkeypatch):
    """Senza ?source usa info.language ("it")."""
    _seed()
    calls = _mock_title_llm(monkeypatch, ["The Book"])
    with _own():
        r = client.get("/api/translate_title/TJ1?target=en")
    assert r.get_json()["title"] == "The Book"
    assert len(calls) == 1


# -- Adopt col titolo tradotto --------------------------------------------------

def _seed_translated(**extra):
    job = _seed(status="translated")
    job["translated_chapters"] = [
        {"index": 1, "title": "One_EN", "text": "Translated text one."}]
    job["translated_lang"] = "en"
    job.update(extra)
    return job


def test_adopt_sets_translated_title(client):
    job = _seed_translated(translated_title="The Book")
    with _own():
        r = client.post("/api/translate_adopt/TJ1")
    assert r.status_code == 200
    assert r.get_json()["title"] == "The Book"
    assert job["info"].title == "The Book"


def test_adopt_without_translated_title_keeps_original(client):
    job = _seed_translated()
    with _own():
        r = client.post("/api/translate_adopt/TJ1")
    assert r.get_json()["title"] == "Libro"
    assert job["info"].title == "Libro"
