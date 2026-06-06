"""Test rilevamento lingua via LLM (spec 2026-06-06-detect-language-llm)."""
import pytest

import generation_engine as ge


# -- Helpers ----

class _Ch:
    def __init__(self, text):
        self.text = text


def _paras(*texts):
    """Un capitolo per blocco di paragrafi (separati da riga vuota)."""
    return [_Ch("\n\n".join(texts))]


LONG_A = "A" * 100   # >= 80 char -> "sostanzioso"
LONG_B = "B" * 100
LONG_C = "C" * 100
LONG_D = "D" * 100
SHORT = "corto"      # < 80 char


class _FakeLLM:
    """Client OpenAI-compatibile minimale: registra i kwargs della chiamata."""
    def __init__(self, reply=None, exc=None):
        self.kwargs = None
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.kwargs = kwargs
                if exc is not None:
                    raise exc
                msg = type("M", (), {"content": reply})
                choice = type("C", (), {"message": msg})
                return type("R", (), {"choices": [choice]})

        self.chat = type("Chat", (), {"completions": _Completions()})()


class _Info:
    def __init__(self, chapters):
        self.chapters = chapters


# -- _pick_language_sample --

def test_sample_starts_from_middle():
    # 8 paragrafi sostanziosi: mid = 4 -> campione = paragrafi 4,5,6 (E,F,G)
    texts = [c * 100 for c in "ABCDEFGH"]
    sample = ge._pick_language_sample(_paras(*texts))
    parts = sample.split("\n\n")
    assert parts == ["E" * 100, "F" * 100, "G" * 100]


def test_sample_skips_short_paragraphs_after_middle():
    # mid = 3 ("corto") -> la prima terna sostanziosa dal centro e' B,C,D
    sample = ge._pick_language_sample(
        _paras(LONG_A, SHORT, SHORT, SHORT, LONG_B, LONG_C, LONG_D))
    assert sample.split("\n\n") == [LONG_B, LONG_C, LONG_D]


def test_sample_retries_from_start_when_tail_short():
    # Dal centro in poi solo paragrafi corti -> terna trovata dall'inizio
    sample = ge._pick_language_sample(
        _paras(LONG_A, LONG_B, LONG_C, SHORT, SHORT, SHORT, SHORT))
    assert sample.split("\n\n") == [LONG_A, LONG_B, LONG_C]


def test_sample_fallback_any_three_consecutive():
    # Nessuna terna >= 80 char -> 3 consecutivi non vuoti dal centro
    texts = ["uno", "due", "tre", "quattro", "cinque", "sei"]
    sample = ge._pick_language_sample(_paras(*texts))
    assert sample.split("\n\n") == ["quattro", "cinque", "sei"]


def test_sample_fallback_first_1500_chars():
    # Meno di 3 paragrafi totali -> primi 1500 char del testo
    sample = ge._pick_language_sample(_paras("X" * 5000))
    assert len(sample) == 1500
    assert sample == "X" * 1500


def test_sample_two_paragraphs_fallback():
    # Solo 2 paragrafi: nessuna terna possibile -> fallback testo unito
    sample = ge._pick_language_sample(_paras(LONG_A, LONG_B))
    assert LONG_A in sample
    assert LONG_B in sample
    assert len(sample) <= 1500


def test_sample_truncates_each_paragraph_to_600():
    texts = ["P" * 2000, "Q" * 2000, "R" * 2000]
    sample = ge._pick_language_sample(_paras(*texts))
    parts = sample.split("\n\n")
    assert [len(p) for p in parts] == [600, 600, 600]


def test_sample_spans_chapters():
    # I paragrafi si accumulano attraverso i capitoli in ordine
    chapters = [_Ch(LONG_A), _Ch(LONG_B + "\n\n" + LONG_C), _Ch(LONG_D)]
    sample = ge._pick_language_sample(chapters)
    # 4 paragrafi, mid = 2 -> terna C,D non esiste (solo 2 dal centro) ->
    # retry dall'inizio -> A,B,C
    assert sample.split("\n\n") == [LONG_A, LONG_B, LONG_C]


def test_sample_empty_inputs():
    assert ge._pick_language_sample([]) == ""
    assert ge._pick_language_sample(None) == ""
    assert ge._pick_language_sample(_paras("   ")) == ""


# -- detect_book_language --

@pytest.fixture
def book():
    return _Info(_paras(LONG_A, LONG_B, LONG_C))


def test_detect_returns_code(monkeypatch, book):
    fake = _FakeLLM(reply="it")
    monkeypatch.setattr(ge, "_llm_client", fake)
    assert ge.detect_book_language(book) == "it"
    # Parametri chiamata: non-streaming, deterministica, output minimo
    assert fake.kwargs["temperature"] == 0
    assert fake.kwargs["max_tokens"] == 8
    assert fake.kwargs["timeout"] == ge.LANG_DETECT_TIMEOUT_SEC
    assert "stream" not in fake.kwargs
    assert fake.kwargs["model"] == ge.LLM_MODEL
    # Il campione finisce nel messaggio user
    assert LONG_B in fake.kwargs["messages"][1]["content"]


def test_detect_normalizes_reply(monkeypatch, book):
    monkeypatch.setattr(ge, "_llm_client", _FakeLLM(reply="  EN \n"))
    assert ge.detect_book_language(book) == "en"


def test_detect_strips_region_suffix(monkeypatch, book):
    monkeypatch.setattr(ge, "_llm_client", _FakeLLM(reply="en-US"))
    assert ge.detect_book_language(book) == "en"


def test_detect_strips_backticks(monkeypatch, book):
    monkeypatch.setattr(ge, "_llm_client", _FakeLLM(reply="`it`"))
    assert ge.detect_book_language(book) == "it"


def test_detect_rejects_garbage(monkeypatch, book):
    monkeypatch.setattr(ge, "_llm_client",
                        _FakeLLM(reply="The language is Italian."))
    assert ge.detect_book_language(book) == ""


def test_detect_empty_reply(monkeypatch, book):
    monkeypatch.setattr(ge, "_llm_client", _FakeLLM(reply=""))
    assert ge.detect_book_language(book) == ""
    monkeypatch.setattr(ge, "_llm_client", _FakeLLM(reply=None))
    assert ge.detect_book_language(book) == ""


def test_detect_swallows_llm_errors(monkeypatch, book):
    monkeypatch.setattr(ge, "_llm_client",
                        _FakeLLM(exc=RuntimeError("network down")))
    assert ge.detect_book_language(book) == ""


def test_detect_no_client(monkeypatch, book):
    monkeypatch.setattr(ge, "_llm_client", None)
    assert ge.detect_book_language(book) == ""


def test_detect_no_text(monkeypatch):
    monkeypatch.setattr(ge, "_llm_client", _FakeLLM(reply="it"))
    assert ge.detect_book_language(_Info([])) == ""


# -- Integrazione /api/analyze ──────────────────────────────────────────
import io

import audiobook_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    audiobook_app.app.config["TESTING"] = True
    # Upload in dir temporanea, niente rate-limit ne' activity log
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(audiobook_app, "_ip_rl_check",
                        lambda *a, **kw: (True, 0))
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda *a, **kw: None)
    audiobook_app.jobs.clear()
    yield audiobook_app.app.test_client()
    audiobook_app.jobs.clear()


_TXT = ("Primo paragrafo del libro di prova, con testo sufficiente.\n\n"
        "Secondo paragrafo con altro testo di prova per il parser.\n\n"
        "Terzo paragrafo conclusivo del piccolo libro di prova.\n").encode("utf-8")


def _upload_txt(client):
    return client.post("/api/analyze", data={
        "epub": (io.BytesIO(_TXT), "libro.txt"),
    }, content_type="multipart/form-data")


def test_analyze_txt_detects_language(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    monkeypatch.setattr(ge, "detect_book_language", lambda info: "de")
    r = _upload_txt(client)
    assert r.status_code == 200
    d = r.get_json()
    assert d["language"] == "de"
    assert d["language_detected"] is True
    job = audiobook_app.jobs[d["job_id"]]
    assert job["language_detected"] is True
    assert job["info"].language == "de"


def test_analyze_detect_failure_is_silent(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    monkeypatch.setattr(ge, "detect_book_language", lambda info: "")
    r = _upload_txt(client)
    assert r.status_code == 200
    d = r.get_json()
    assert d["language"] == ""
    assert d["language_detected"] is False
    assert d["total_chapters"] >= 1  # analisi completata comunque


def test_analyze_skips_detect_when_llm_unavailable(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: False)
    called = []
    monkeypatch.setattr(ge, "detect_book_language",
                        lambda info: called.append(1) or "it")
    r = _upload_txt(client)
    assert r.status_code == 200
    assert called == []
    assert r.get_json()["language"] == ""


def test_analyze_skips_detect_when_metadata_present(client, monkeypatch):
    """File .abm con language nel manifest: nessuna chiamata LLM."""
    import json as _json
    import zipfile as _zf
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    called = []
    monkeypatch.setattr(ge, "detect_book_language",
                        lambda info: called.append(1) or "xx")
    buf = io.BytesIO()
    with _zf.ZipFile(buf, "w") as zf:
        zf.writestr("chapters/001_uno.txt",
                    "Testo di prova del capitolo uno del libro.")
        zf.writestr("manifest.json", _json.dumps({
            "format": "audiobook-maker-project", "format_version": "1.0",
            "title": "Test", "author": "A", "language": "fr",
            "has_cover": False, "cover_file": "",
            "chapters": [{"index": 1, "filename": "001_uno.txt",
                          "title": "Uno", "word_count": 8}]}))
    buf.seek(0)
    r = client.post("/api/analyze", data={
        "epub": (buf, "libro.abm"),
    }, content_type="multipart/form-data")
    assert r.status_code == 200
    assert called == []
    d = r.get_json()
    assert d["language"] == "fr"
    assert d["language_detected"] is False


def test_analyze_reuse_keeps_detected_flag(client, monkeypatch):
    """Secondo upload identico (riuso job): flag riportato, niente 2a chiamata.

    Il browser reale riceve abm_cid al primo caricamento della pagina e lo
    invia gia' sul primo /api/analyze. Il test client non ha quel flusso, quindi
    pre-seminiamo il cookie prima dei due upload per replicare il comportamento.
    """
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    calls = []
    monkeypatch.setattr(ge, "detect_book_language",
                        lambda info: calls.append(1) or "de")
    # Pre-seed cookie: simula il browser che ha gia' ricevuto abm_cid
    # alla prima navigazione (prima di arrivare a /api/analyze).
    client.set_cookie("abm_cid", "test-client-reuse-001")
    r1 = _upload_txt(client)
    assert r1.get_json()["language_detected"] is True
    r2 = _upload_txt(client)
    d2 = r2.get_json()
    assert d2["job_id"] == r1.get_json()["job_id"]
    assert d2["language"] == "de"
    assert d2["language_detected"] is True
    assert len(calls) == 1
