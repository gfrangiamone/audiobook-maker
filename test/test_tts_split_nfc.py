# -*- coding: utf-8 -*-
"""Normalizzazione Unicode NFC prima della sintesi.

Un accento puo' essere scritto in due modi identici sullo schermo: `e'` acuta
come singolo carattere U+00E9 (NFC) oppure come `e` + U+0301 (NFD). I motori
TTS leggono la forma decomposta come vocale nuda, quindi `perche'` scritto in
NFD viene letto «perche». Misurato su VoxCPM: stesso seme, stesso testo
logico, audio diverso e durata diversa (6,08 s in NFC contro 6,40 s in NFD).

`clean_text_for_tts` normalizza gia' i corpi dei capitoli di EPUB e PDF, ma
non i titoli, non i .txt, non i .abm e non il testo che torna
dall'ottimizzazione LLM. `_sanitize_tts_text` e' l'ultimo punto comune: la
chiamano tutte e quattro le `generate_chunk_*`, quindi la garanzia vale per
qualunque provenienza del testo e qualunque motore.

Le stringhe decomposte sono costruite concatenando i punti di codice
combinanti in modo esplicito, non scritte come caratteri letterali: un editor
o un tool che salva il file in NFC svuoterebbe silenziosamente il test.
"""
import unicodedata

from tts_split import _sanitize_tts_text

PERCHE_NFD = "perche" + "́"            # perche + accento acuto combinante
RESTO_NFD = "resto" + "̀"              # resto + accento grave combinante
MANANA_NFD = "man" + "̃" + "ana"       # mana + tilde combinante


def test_le_costanti_sono_davvero_decomposte():
    """Se questa cade, le altre prove NFD non stanno provando nulla."""
    for s in (PERCHE_NFD, RESTO_NFD, MANANA_NFD):
        assert s != unicodedata.normalize("NFC", s)


def test_nfd_diventa_nfc():
    assert len(PERCHE_NFD) == 7      # la forma decomposta e' piu' lunga
    out = _sanitize_tts_text(PERCHE_NFD)
    assert out == "perché"
    assert out == unicodedata.normalize("NFC", out)
    assert len(out) == 6


def test_nfd_su_frase_intera():
    out = _sanitize_tts_text(f"{PERCHE_NFD} {RESTO_NFD} immobile")
    assert out == "perché restò immobile"


def test_tilde_combinante():
    assert _sanitize_tts_text(MANANA_NFD) == "mañana"


def test_testo_gia_nfc_invariato():
    frase = "perché restò immobile, è così che andò."
    assert _sanitize_tts_text(frase) == frase


def test_non_e_nfkc():
    """NFKC riscriverebbe legature, apici tipografici e frazioni, che sono
    scelte dell'autore e non danni di codifica: quelli devono restare."""
    frase = "l’œuvre ﬁnale — ½ giro"
    out = _sanitize_tts_text(frase)
    assert "ﬁ" in out     # legatura fi
    assert "’" in out     # apostrofo tipografico
    assert "½" in out     # un mezzo
    assert "œ" in out     # oe


def test_vuoto_resta_none():
    assert _sanitize_tts_text("") is None
    assert _sanitize_tts_text("   \n  ") is None


def test_zero_width_ancora_rimossi():
    """La normalizzazione non deve aver disattivato la pulizia preesistente."""
    assert _sanitize_tts_text("a​b") == "ab"
    assert _sanitize_tts_text("a﻿b") == "ab"
