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
