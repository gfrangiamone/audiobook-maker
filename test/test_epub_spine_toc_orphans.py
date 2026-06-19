"""
Regressione: riconciliazione spine↔TOC negli EPUB con file "orfani".

Molti EPUB (light novel, generati automaticamente) listano nel TOC solo il
primo file di un capitolo, lasciando i file successivi dello stesso capitolo
nello spine ma SENZA voce TOC. La logica originale trasformava questi file
orfani in capitoli fantasma "Sezione N", mutilando il capitolo TOC reale
(che restava col solo incipit) o facendo sparire del tutto i capitoli TOC il
cui corpo era una pagina-immagine.

File di riferimento reale: WEAKEST_TAMER_AUDIOBOOK-MAKER_TEST_FILE.epub
- "Chapter 514: Books"  -> incipit in section-0012 + corpo in section-0014 (orfano)
- "SIDE: In Moderation!" -> titolo TOC in section-0066 (vuoto) + corpo in section-0067 (orfano)
"""
import os
import re

import pytest

import epub_to_tts as E

EPUB = os.path.join(
    os.path.dirname(__file__), "WEAKEST_TAMER_AUDIOBOOK-MAKER_TEST_FILE.epub"
)


@pytest.fixture(scope="module")
def info():
    if not os.path.exists(EPUB):
        pytest.skip("file EPUB di riferimento non disponibile")
    return E.parse_epub(EPUB)


def _by_title(info, needle):
    return [c for c in info.chapters if needle in c.title]


def test_nessun_capitolo_fantasma_sezione(info):
    """Nessun capitolo deve avere titolo generico 'Sezione N' (orfano non agganciato)."""
    phantom = [c.title for c in info.chapters if re.match(r"^Sezione \d+$", c.title.strip())]
    assert not phantom, f"capitoli fantasma residui: {phantom}"


def test_capitolo_514_contiene_il_corpo_orfano(info):
    """Il corpo reale del cap. 514 (section-0014) deve stare DENTRO 'Chapter 514: Books'."""
    chs = _by_title(info, "Chapter 514")
    assert chs, "capitolo 514 mancante"
    ch = chs[0]
    assert ch.char_count > 5000, f"cap. 514 mutilato: solo {ch.char_count} char"
    assert "He had one point" in ch.text, "corpo orfano di section-0014 non agganciato al 514"


def test_capitolo_side_recuperato_con_titolo_corretto(info):
    """Il capitolo TOC col corpo-immagine deve esistere col titolo TOC e il corpo orfano."""
    chs = _by_title(info, "SIDE: In Moderation")
    assert chs, "capitolo 'SIDE: In Moderation!' perso (corpo finito in una Sezione fantasma)"
    assert chs[0].char_count > 5000


def test_completezza_contenuto_non_regredita(info):
    """Il totale caratteri non deve calare rispetto alla baseline pre-fix (~412k)."""
    assert info.total_chars >= 400000, f"contenuto perso: total_chars={info.total_chars}"
