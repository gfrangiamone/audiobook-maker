# -*- coding: utf-8 -*-
"""Chunking byte-aware per giapponese/cinese.

Causa incidente 27/06: il tokenizer di frase usava solo terminatori latini
([.!?…] + spazio). Il CJK usa 。！？ senza spazi -> nessun taglio -> chunk
giganti oltre il cap di 8000 byte Gemini -> "Payload exceeds API hard cap" e
timeout. Invariante chiave: NESSUN chunk supera mai max_bytes.
"""
import tts_split
from tts_split import split_text_into_chunks

MAX_CHARS = 700
MAX_BYTES = 8000


def _all_within(chunks, max_chars=MAX_CHARS, max_bytes=MAX_BYTES):
    return all(len(c) <= max_chars and len(c.encode("utf-8")) <= max_bytes
               for c in chunks)


def test_japanese_splits_on_cjk_terminators():
    # Frasi giapponesi separate da 。！？ senza spazi.
    text = ("俺は驚いた。黒髪のポニーテール！絶滅が危惧されているポニーテール！"
            "この学園で彼女に出会った。") * 20
    chunks = split_text_into_chunks(text, max_chars=MAX_CHARS, max_bytes=MAX_BYTES)
    assert len(chunks) > 1            # prima il testo restava un unico chunk gigante
    assert _all_within(chunks)
    # nessuna perdita di caratteri (a meno degli spazi di giunzione)
    assert text.replace(" ", "") == "".join(chunks).replace(" ", "")


def test_chinese_splits_and_bounded():
    text = ("我是一个测试。这是第二句话！第三句话呢？最后一句。") * 30
    chunks = split_text_into_chunks(text, max_chars=MAX_CHARS, max_bytes=MAX_BYTES)
    assert len(chunks) > 1
    assert _all_within(chunks)


def test_giant_cjk_without_punctuation_hard_split():
    # Sequenza CJK lunghissima SENZA punteggiatura: deve comunque essere
    # spezzata sotto il cap byte (taglio duro per byte).
    text = "あ" * 5000   # 5000 * 3 byte = 15000 byte
    chunks = split_text_into_chunks(text, max_chars=MAX_CHARS, max_bytes=MAX_BYTES)
    assert len(chunks) >= 2
    assert _all_within(chunks)
    assert "".join(chunks) == text   # nessuna perdita nel taglio duro


def test_cjk_soft_break_on_commas():
    # Frase lunga con virgole giapponesi 、 ma senza terminatori di frase.
    text = "これは" + "とても長い文章、".replace(" ", "") * 400  # molte 、
    chunks = split_text_into_chunks(text, max_chars=MAX_CHARS, max_bytes=MAX_BYTES)
    assert _all_within(chunks)
    assert "".join(chunks) == text


def test_byte_cap_strictly_enforced_mixed():
    # Mix latino + CJK con cap byte basso: l'invariante deve reggere.
    text = "Hello world. " + ("混合テキストです。" * 50) + " End."
    chunks = split_text_into_chunks(text, max_chars=300, max_bytes=900)
    assert _all_within(chunks, max_chars=300, max_bytes=900)


def test_latin_behaviour_unchanged():
    # Regressione: testo latino normale resta accorpato come prima.
    text = "Hello world. This is a test. Another sentence here."
    chunks = split_text_into_chunks(text, max_chars=2000, max_bytes=None)
    assert chunks == ["Hello world. This is a test. Another sentence here."]


def test_latin_splits_when_over_char_cap():
    text = "A. " * 500  # 500 frasi corte
    chunks = split_text_into_chunks(text, max_chars=50, max_bytes=None)
    assert len(chunks) > 1
    assert all(len(c) <= 50 for c in chunks)


def test_empty_and_whitespace():
    assert split_text_into_chunks("") == [""]
    assert split_text_into_chunks("   ") == ["   "]
