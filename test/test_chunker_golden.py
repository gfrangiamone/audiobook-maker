"""Golden-test dei confini del chunker paragrafo/frase (LLM + traduzione).

Storia: il chunker era duplicato in generation_engine
(_split_text_into_chunks, usato per l'ottimizzazione LLM) e in
translation_core (split_text_into_chunks, usato dalla traduzione libri).
La copia translation_core include il fix "sep space" (conteggio dello
spazio di join tra frasi); quella generation_engine no: nel caso di
paragrafi oltre max_chars i suoi chunk potevano SUPERARE max_chars di
(n_frasi - 1) caratteri dopo lo " ".join, rischiando output LLM troncati
(LLM_SAFE_OUTPUT_CHUNK e' dimensionato sul MAX_TOKENS di risposta).

Questi test fissano i confini della versione canonica e l'equivalenza
della delega generation_engine -> translation_core (guardia anti-drift).

NB: tts_split.split_text_into_chunks e' un chunker DIVERSO (TTS,
max_bytes, CJK) e non rientra in questa unificazione.
"""
import re

import translation_core as tc
import generation_engine as ge


def _flat(s):
    """Contenuto senza whitespace, per verificare che nulla vada perso."""
    return re.sub(r"\s+", "", s)


# ---------------------------------------------------------------------------
# Confini golden della versione canonica (translation_core)
# ---------------------------------------------------------------------------

def test_golden_paragraph_grouping():
    """Paragrafi corti accorpati fino al limite, separati da riga vuota."""
    text = "Uno.\n\nDue.\n\nTre.\n\nQuattro."
    # Budget para = len + 2 (separatore "\n\n"): 6+6=12 ok; +6=18 > 14 flush;
    # "Tre."(6) + "Quattro."(8+2=10) = 16 > 14 flush.
    chunks = tc.split_text_into_chunks(text, 14)
    assert chunks == ["Uno.\n\nDue.", "Tre.", "Quattro."]


def test_golden_giant_paragraph_sentence_split():
    """Paragrafo oltre il limite: spezzato sui confini di frase."""
    para = "Alfa uno. Beta due. Gamma tre. Delta quattro."
    chunks = tc.split_text_into_chunks(para, 20)
    assert chunks == ["Alfa uno. Beta due.", "Gamma tre.", "Delta quattro."]
    assert all(len(c) <= 20 for c in chunks)


def test_golden_unicode_ellipsis_is_sentence_boundary():
    para = "Attese a lungo… Poi arrivo' qualcuno… Fine della storia davvero."
    chunks = tc.split_text_into_chunks(para, 40)
    assert chunks[0].endswith("…")
    assert all(len(c) <= 40 for c in chunks)


def test_sep_space_regression_never_exceeds_max():
    """Caso che la copia generation_engine PRE-unificazione sbagliava:
    due frasi da 5 char con max 10 — senza contare lo spazio di join il
    vecchio chunker produceva un chunk da 11 (> max)."""
    para = "abcd. efgh."  # 11 char > max -> path frasi
    chunks = tc.split_text_into_chunks(para, 10)
    assert chunks == ["abcd.", "efgh."]
    assert all(len(c) <= 10 for c in chunks)


def test_invariant_max_chars_with_many_sentences():
    """Su un corpus di frasi variabili nessun chunk supera max_chars
    (nessuna singola frase eccede il limite da sola)."""
    sentences = [f"Frase numero {i} con contenuto variabile {'x' * (i % 17)}."
                 for i in range(80)]
    para = " ".join(sentences)
    for max_chars in (80, 120, 300):
        chunks = tc.split_text_into_chunks(para, max_chars)
        assert all(len(c) <= max_chars for c in chunks), max_chars
        assert _flat("".join(chunks)) == _flat(para)


def test_content_preserved_mixed_corpus():
    """Nessuna perdita di contenuto su testo misto paragrafi corti/giganti."""
    giant = " ".join(f"Sentenza {i} del paragrafo gigante." for i in range(40))
    text = f"Intro breve.\n\n{giant}\n\nCoda finale."
    chunks = tc.split_text_into_chunks(text, 200)
    assert _flat("".join(chunks)) == _flat(text)
    assert all(len(c) <= 200 for c in chunks)


def test_single_oversized_sentence_kept_whole():
    """Una frase singola oltre il limite non viene spezzata (comportamento
    storico di entrambe le copie: il cap duro e' a valle)."""
    para = "x" * 50  # nessun confine di frase
    chunks = tc.split_text_into_chunks(para, 10)
    assert chunks == [para]


def test_empty_and_whitespace():
    assert tc.split_text_into_chunks("", 100) == [""]
    assert tc.split_text_into_chunks("   ", 100) == ["   "]


# ---------------------------------------------------------------------------
# Equivalenza post-unificazione (guardia anti-drift)
# ---------------------------------------------------------------------------

def test_generation_engine_delegates_to_canonical():
    """generation_engine._split_text_into_chunks e' la stessa funzione
    canonica di translation_core: un nuovo fork/drift fa fallire qui."""
    assert ge._split_text_into_chunks is tc.split_text_into_chunks


def test_equivalence_on_corpus():
    corpus = [
        "Uno.\n\nDue.\n\nTre.",
        "abcd. efgh.",
        " ".join(f"Frase {i} abbastanza lunga da contare." for i in range(30)),
        "Attese… Poi arrivo'… Fine.",
        "",
    ]
    for text in corpus:
        for max_chars in (10, 50, 2000):
            assert (ge._split_text_into_chunks(text, max_chars)
                    == tc.split_text_into_chunks(text, max_chars))
