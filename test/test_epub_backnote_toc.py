"""
Regressione: EPUB con TOC composto SOLO da apparato di note (back-link).

File di riferimento: test/books/L'éternel-adolescent.-Word (1).epub
Export da Word il cui toc.ncx NON elenca alcun capitolo reale: contiene solo
- le note finali            -> voci "1".."10"  (file index_split_022..031)
- i back-link alle note     -> voci "←1".."←10" (frecce indietro)

I capitoli veri ("Chapitre 0".."Chapitre 19", + divisori "Première partie",
ecc.) vivono nel body come <p>, senza heading semantici.

Bug osservato:
- Le voci "←7","←8","←9","←10" puntano tutte a index_split_021.html (differendo
  solo per fragment #back_note_N). La mappa TOC collassava sul filename e
  _split_html_by_headings falliva (titoli "←N" non sono heading) -> il file
  finiva in UN solo capitolo mistitolato "←10", facendo sparire ←7/←8/←9.
- Le voci-freccia mis-ancoravano lo spine: i file body senza voce TOC
  (009-020) venivano accorpati come orfani in un blob gigante sotto "←6".

Fix atteso: le voci-freccia di back-note vanno riconosciute come apparato e
ignorate; i file body restano capitoli distinti con titolo derivato dal corpo.
"""
import os
import re

import pytest

import epub_to_tts as E

EPUB = os.path.join(
    os.path.dirname(__file__), "books", "L’éternel-adolescent.-Word (1).epub"
)


@pytest.fixture(scope="module")
def info():
    if not os.path.exists(EPUB):
        pytest.skip("file EPUB di riferimento non disponibile")
    return E.parse_epub(EPUB)


def test_nessun_titolo_freccia_backnote(info):
    """Nessun capitolo deve avere un titolo che è una freccia di back-link a nota."""
    arrows = [c.title for c in info.chapters
              if any(a in c.title for a in ("←", "↩", "⇐", "⬅"))]
    assert not arrows, f"capitoli mistitolati con freccia back-note: {arrows}"


def test_contenuto_chap19_presente_e_standalone(info):
    """Il corpo di index_split_021 (ex ←7/←8/←9/←10) deve essere un capitolo
    a sé, non collassato sotto una freccia e non perso."""
    needle = "Ziyad était revenu dans son deux-pièces"
    hits = [c for c in info.chapters if needle in c.text]
    assert hits, "corpo di index_split_021 (←7..←10) perso"
    ch = hits[0]
    assert "←" not in ch.title, f"capitolo mistitolato: {ch.title!r}"


def test_nessun_blob_gigante(info):
    """Il merge-orfani mis-innescato dalle frecce produceva un capitolo blob da
    ~157k char (files 009-020 accorpati sotto ←6). Non deve più accadere."""
    biggest = max((c.char_count for c in info.chapters), default=0)
    assert biggest < 60000, f"blob gigante residuo: {biggest} char"


def test_capitoli_body_separati(info):
    """I file body sono un capitolo ciascuno: deve emergere una struttura a più
    capitoli, non gli 8 pseudo-capitoli-freccia del comportamento buggato."""
    assert len(info.chapters) >= 15, f"chapterizzazione collassata: {len(info.chapters)}"


def test_contenuto_non_regredito(info):
    """Il totale caratteri narrativi non deve calare rispetto al pre-fix (~267k)."""
    assert info.total_chars >= 250000, f"contenuto perso: total_chars={info.total_chars}"
