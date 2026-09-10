"""Tests per la normalizzazione del testo prima del TTS.

Due problemi osservati sui motori neurali (VoxCPM in italiano su tutti):

1. Il MAIUSCOLO dei titoli viene letto malissimo. Lo stesso testo in minuscolo
   viene letto correttamente -> `_normalize_shouting` porta le righe urlate a
   sentence case, preservando i numeri romani di numerazione.

2. Un titolo isolato senza punto finale si incolla al primo paragrafo, senza
   pausa. `_ensure_heading_pause` esisteva gia` ma era codice morto: in
   `_plan_chunks` girava DOPO `_strip_parenthetical`, che appiattiva tutti gli
   a-capo. Il riordino (e il flag `flatten`) la rimette in funzione.

Le due normalizzazioni sono sempre attive e valgono per tutti i motori, perche'
`_plan_chunks` e` il funnel unico di preparazione del testo.
"""
import shutil

import pytest

from tts_split import (
    _normalize_shouting,
    _strip_parenthetical,
    _ensure_heading_pause,
    _plan_chunks,
)


class _FakeCh:
    def __init__(self, index, title, text):
        self.index = index
        self.title = title
        self.text = text


class _FakeInfo:
    def __init__(self, chapters):
        self.chapters = chapters


def _joined(plan):
    return " ".join(b["text"] for b in plan)


# ── _normalize_shouting: righe interamente maiuscole ──

def test_shouted_line_becomes_sentence_case_keeping_accents():
    src = "L'AMORE E LA SUA DISINTEGRAZIONE NELLA SOCIETÀ OCCIDENTALE"
    assert _normalize_shouting(src) == (
        "L'amore e la sua disintegrazione nella società occidentale")


def test_shouted_line_recapitalizes_after_sentence_terminator():
    src = "IL VENTO SOFFIAVA. LA NOTTE ERA BUIA"
    assert _normalize_shouting(src) == "Il vento soffiava. La notte era buia"


def test_single_shouted_word_line_is_normalized():
    assert _normalize_shouting("PROLOGO") == "Prologo"


def test_lone_short_acronym_line_is_left_alone():
    # Una riga di una sola parola corta (<5 lettere) e` piu` probabilmente una
    # sigla che un titolo: non toccarla.
    assert _normalize_shouting("NATO") == "NATO"


def test_mixed_case_line_is_untouched():
    src = "Era una notte buia e tempestosa."
    assert _normalize_shouting(src) == src


def test_shouted_lines_normalized_independently():
    src = "PRIMA PARTE\n\nEra una notte buia.\n\nSECONDA PARTE"
    assert _normalize_shouting(src) == (
        "Prima parte\n\nEra una notte buia.\n\nSeconda parte")


# ── _normalize_shouting: numeri romani ──

def test_roman_numeral_after_numbering_keyword_stays_uppercase():
    assert _normalize_shouting("CAPITOLO XIV") == "Capitolo XIV"


def test_single_letter_roman_after_keyword_stays_uppercase():
    assert _normalize_shouting("PARTE V") == "Parte V"


def test_roman_alone_on_line_stays_uppercase():
    assert _normalize_shouting("XVIII") == "XVIII"


def test_italian_words_that_look_roman_are_lowercased():
    # DI, MI, CI, VI, LI sono numeri romani validi: senza il vincolo di
    # contesto (keyword di numerazione, oppure ultimo token lungo >=3)
    # verrebbero preservati maiuscoli in mezzo alla frase.
    assert _normalize_shouting("STORIA DI UN UOMO") == "Storia di un uomo"
    assert _normalize_shouting("VIENI CON MI") == "Vieni con mi"


# ── _normalize_shouting: enfasi inline ──

def test_two_consecutive_shouted_words_inline_are_lowercased():
    src = "Era VERAMENTE MOLTO stanco."
    assert _normalize_shouting(src) == "Era veramente molto stanco."


def test_inline_run_at_line_start_keeps_initial_capital():
    src = "VERAMENTE MOLTO stanco, disse."
    assert _normalize_shouting(src) == "Veramente molto stanco, disse."


def test_isolated_acronym_inline_is_preserved():
    src = "La NASA ha confermato il lancio."
    assert _normalize_shouting(src) == src


def test_single_letter_word_does_not_break_inline_run():
    # «E» maiuscola in mezzo alla sequenza fa parte dell'urlato, non e` un
    # acronimo: da sola non apre una sequenza, ma non la deve spezzare.
    src = "Il giorno dopo, come SEMPRE E COMUNQUE, tornò."
    assert _normalize_shouting(src) == (
        "Il giorno dopo, come sempre e comunque, tornò.")


def test_lone_single_letter_capital_is_preserved():
    src = "Scrisse una A maiuscola sul foglio."
    assert _normalize_shouting(src) == src


def test_inline_run_with_trailing_punctuation():
    src = "Gridò: BASTA ADESSO, e uscì."
    assert _normalize_shouting(src) == "Gridò: basta adesso, e uscì."


# ── _strip_parenthetical: flag flatten ──

def test_strip_parenthetical_default_still_flattens_newlines():
    # Regressione: i chiamanti storici (preview UI) si aspettano una riga sola.
    out = _strip_parenthetical("Titolo\n\nCorpo   del testo")
    assert out == "Titolo Corpo del testo"


def test_strip_parenthetical_flatten_false_preserves_newlines():
    out = _strip_parenthetical("Titolo   qui\n\nCorpo   testo", flatten=False)
    assert out == "Titolo qui\n\nCorpo testo"


def test_strip_parenthetical_flatten_false_still_removes_parentheses():
    out = _strip_parenthetical("Alfa (tonda)\n\nBeta [quadra]", flatten=False)
    assert out == "Alfa\n\nBeta"


# ── _ensure_heading_pause ──

def test_ensure_heading_pause_adds_period_to_isolated_heading():
    src = "Titolo del capitolo\n\nEra una notte buia."
    assert _ensure_heading_pause(src) == (
        "Titolo del capitolo.\n\nEra una notte buia.")


def test_ensure_heading_pause_skips_wrapped_paragraph_line():
    # Riga breve preceduta da riga vuota ma SEGUITA da altro testo: e` l'inizio
    # di un paragrafo a capo fisso, non un heading. Un punto qui spezza la frase.
    src = "Era una notte buia\ne il vento soffiava forte."
    assert _ensure_heading_pause(src) == src


def test_ensure_heading_pause_handles_heading_as_last_line():
    src = "Era una notte buia.\n\nFine del capitolo"
    assert _ensure_heading_pause(src) == "Era una notte buia.\n\nFine del capitolo."


# ── _plan_chunks: integrazione ──

def test_plan_chunks_normalizes_shouted_heading_and_adds_pause():
    # Il caso reale osservato: heading urlato dentro il corpo del capitolo,
    # senza punto finale, incollato al primo paragrafo.
    text = ("L'AMORE E LA SUA DISINTEGRAZIONE NELLA SOCIETÀ OCCIDENTALE\n\n"
            "Era una notte buia e tempestosa.")
    info = _FakeInfo([_FakeCh(0, "Capitolo 1", text)])
    joined = _joined(_plan_chunks(info))
    assert ("L'amore e la sua disintegrazione nella società occidentale."
            in joined)


def test_plan_chunks_normalizes_shouted_chapter_title():
    info = _FakeInfo([_FakeCh(0, "IL RITORNO DEL RE", "Corpo del capitolo.")])
    joined = _joined(_plan_chunks(info))
    assert "Il ritorno del re." in joined
    assert "IL RITORNO" not in joined


def test_plan_chunks_does_not_double_punctuate_title():
    info = _FakeInfo([_FakeCh(0, "Perché?", "Corpo del capitolo.")])
    joined = _joined(_plan_chunks(info))
    assert "Perché?." not in joined
    assert "Perché?" in joined


def test_plan_chunks_keeps_title_ending_with_period_unchanged():
    info = _FakeInfo([_FakeCh(0, "Capitolo 1.", "Corpo del capitolo.")])
    joined = _joined(_plan_chunks(info))
    assert "Capitolo 1.." not in joined


def test_plan_chunks_output_has_no_newlines():
    # Invariante storica: il testo consegnato al TTS resta su una riga sola.
    text = "PRIMA PARTE\n\nEra una notte buia."
    info = _FakeInfo([_FakeCh(0, "Cap", text)])
    for block in _plan_chunks(info):
        assert "\n" not in block["text"]


# ── parita' anteprima voce / generazione finale ──

@pytest.fixture
def preview_client(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    import audiobook_app
    audiobook_app._invalidate_voices_cache()
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not in PATH")
def test_preview_audio_gets_same_normalization_as_generation(preview_client,
                                                             monkeypatch):
    """L'anteprima voce deve ricevere il testo normalizzato come la generazione.

    Senza parita' l'utente sceglie la voce su una clip che suona peggio
    dell'audiolibro che poi riceve — l'endpoint applica gia` lo stesso
    stripping delle parentesi proprio per questo motivo.
    """
    import audiobook_app
    import speechify_tts
    from epub_to_tts import BookInfo, Chapter

    seen = {}

    def _fake_synth(text, voice_id, output_path, emotion=None, rate="+0%", **kw):
        seen["text"] = text
        with open(output_path, "wb") as fp:
            fp.write(b"\x00\x00" * 4800)  # 0.1s @ 48kHz mono 16-bit
        return {"success": True, "bytes_written": 9600, "sample_rate": 48000,
                "channels": 1, "billable_chars": len(text),
                "voice_name": "harper_32"}

    monkeypatch.setattr(speechify_tts, "synthesize", _fake_synth)

    job_id = "norm-preview-1"
    preview_text = ("L'AMORE E LA SUA DISINTEGRAZIONE\n\n"
                    "Era una notte buia e tempestosa.")
    ch = Chapter(index=0, title="Cap0", text=preview_text)
    info = BookInfo(title="T", author="A", language="it", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {"info": info, "status": "analyzed",
                                      "preview_text": preview_text}
    # Pulizia anche in SETUP: l'endpoint serve la preview dalla cache su disco,
    # e su Windows il rmtree di teardown puo` fallire (send_file tiene aperto
    # l'handle). Senza questa il test riuserebbe l'MP3 della run precedente e
    # `synthesize` non verrebbe mai chiamata.
    shutil.rmtree(audiobook_app.UPLOAD_DIR / job_id, ignore_errors=True)
    try:
        r = preview_client.get(
            f"/api/preview_audio/{job_id}",
            query_string={"voice": "speechify:simba-3.2:harper_32",
                          "rate": "+0%"})
        assert r.status_code == 200, r.get_data(as_text=True)
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(job_id, None)
        shutil.rmtree(audiobook_app.UPLOAD_DIR / job_id, ignore_errors=True)

    assert "L'amore e la sua disintegrazione." in seen["text"]
    assert "L'AMORE" not in seen["text"]
