"""Voci d'indice con il rimando a nota in coda: l'NCX di Liber Liber scrive
"XXXI. Regina Mabnota 35" e ABM leggeva "nota 35" nel titolo del capitolo
(Moby Dick tradotto da Pavese, catalogo 12/11/2026)."""
import epub_to_tts as E
from book_model import clean_toc_title


def test_rimando_a_nota_attaccato_o_staccato():
    assert clean_toc_title("XXXI. Regina Mabnota 35") == "XXXI. Regina Mab"
    assert clean_toc_title("CII. Una pergola fra gli Arsacidinota 121") == "CII. Una pergola fra gli Arsacidi"
    assert clean_toc_title("XXXI. Regina Mab nota\u00a035 ") == "XXXI. Regina Mab"
    assert clean_toc_title("Titolo nota 3 nota 4") == "Titolo"


def test_titoli_senza_rimando_restano_uguali():
    assert clean_toc_title("  Capitolo 3 ") == "Capitolo 3"
    assert clean_toc_title("La nota") == "La nota"
    assert clean_toc_title("Nota 3") == "Nota 3"           # tutta la voce: non si svuota
    assert clean_toc_title("nota 12") == "nota 12"
    assert clean_toc_title(None) == ""


def test_l_indice_usa_il_titolo_pulito():
    assert E.clean_toc_title is clean_toc_title

    class Voce:
        def __init__(self, title, href):
            self.title, self.href = title, href

    class Libro:
        toc = [(Voce("Parte primanota 1", "p1.xhtml"), [Voce("XXXI. Regina Mabnota 35", "c31.xhtml")])]

    assert E._toc_entries(Libro()) == [("p1.xhtml", "", "Parte prima"), ("c31.xhtml", "", "XXXI. Regina Mab")]
    assert E._build_toc_parents(Libro()) == {"c31.xhtml": "Parte prima"}
