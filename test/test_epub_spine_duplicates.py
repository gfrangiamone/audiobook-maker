"""EPUB di ws-export (Wikisource): spine con documenti ripetuti e indici di parte.

ws-export mette nello spine i capitoli di ogni parte due volte: dopo la pagina
della parte e di nuovo in coda. ABM li leggeva entrambe le volte e I Vicere'
(06/11/2026) usciva di 49 ore invece di 25. La pagina della parte porta
"<h2>Indice</h2>" e l'elenco dei suoi capitoli, che finiva letto ad alta voce.
"""
from ebooklib import epub

import epub_to_tts as E

_PARA = ("Il principe scese le scale del palazzo senza voltarsi, mentre la servitu' "
         "raccolta nel cortile commentava a bassa voce la lettura del testamento.")


def _write_epub(path, docs, spine):
    book = epub.EpubBook()
    book.set_identifier("spine-dup-test")
    book.set_title("Spine")
    book.set_language("it")
    items = {}
    for name, (title, paras) in docs.items():
        it = epub.EpubHtml(title=title, file_name=f"{name}.xhtml", lang="it")
        it.content = f"<html><body><h1>{title}</h1>{''.join(f'<p>{p}</p>' for p in paras)}</body></html>"
        book.add_item(it)
        items[name] = it
    book.toc = [items[n] for n in docs]
    book.spine = [items[n] for n in spine]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)


def test_documento_ripetuto_nello_spine_si_legge_una_volta(tmp_path):
    p = tmp_path / "ws-export.epub"
    docs = {f"c{i}": (f"Capitolo {i}", [f"{i}. {_PARA}"] * 8) for i in range(1, 4)}
    _write_epub(p, docs, ["c1", "c2", "c3", "c1", "c2", "c3"])
    info = E.parse_epub(str(p))
    assert [c.title for c in info.chapters] == ["Capitolo 1", "Capitolo 2", "Capitolo 3"]


def test_indice_di_parte_non_si_legge():
    html = ("<html><body><p>PARTE SECONDA</p><h2>Indice</h2><ul>"
            '<li><a href="c12.xhtml">Pescatori</a></li>'
            '<li><a href="c13.xhtml">Il piccolo patriotta padovano</a> (racconto mensile)</li>'
            "</ul></body></html>")
    text = E.html_to_text(html)
    assert "PARTE SECONDA" in text and "Indice" not in text and "Pescatori" not in text


def test_elenchi_che_non_sono_indici_restano():
    html = ("<html><body><h2>Indice</h2><ul><li>Pane</li><li>Vino</li></ul>"
            '<ul><li><a href="#n1">Nota</a></li></ul>'
            '<ul><li><a href="https://example.org">Sito</a></li></ul>'
            '<ul><li>Vedi <a href="c2.xhtml">il capitolo</a> dove si racconta di tutta la vicenda del principe</li></ul>'
            "</body></html>")
    text = E.html_to_text(html)
    assert all(w in text for w in ("Indice", "Pane", "Nota", "Sito", "il capitolo"))


def _write_parts_epub(path, parts):
    """EPUB con indice annidato: [(parte, [(titolo capitolo, testo)])]; la
    pagina di ogni parte ha solo il titolo, come in ws-export."""
    book = epub.EpubBook()
    book.set_identifier("parts-test")
    book.set_title("Parti")
    book.set_language("it")
    toc, spine, n = [], [], 0
    for part, chapters in parts:
        n += 1
        page = epub.EpubHtml(title=part, file_name=f"p{n}.xhtml", lang="it")
        page.content = f"<html><body><p>{part.upper()}</p></body></html>"
        book.add_item(page)
        spine.append(page)
        kids = []
        for title, text in chapters:
            n += 1
            it = epub.EpubHtml(title=title, file_name=f"c{n}.xhtml", lang="it")
            it.content = f"<html><body>{''.join(f'<p>{text} {_PARA}</p>' for _ in range(8))}</body></html>"
            book.add_item(it)
            spine.append(it)
            kids.append(it)
        toc.append((epub.Link(f"p{n - len(chapters)}.xhtml", part, f"p{n}"), kids))
    book.toc = toc
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)


def test_capitoli_generici_ripetuti_prendono_il_nome_della_parte(tmp_path):
    p = tmp_path / "parti.epub"
    _write_parts_epub(p, [("Parte prima", [("Capitolo 1", "Uno."), ("Capitolo 2", "Due.")]),
                          ("Parte seconda", [("Capitolo 1", "Tre."), ("Capitolo 2", "Quattro.")])])
    titles = [c.title for c in E.parse_epub(str(p)).chapters]
    assert titles == ["Parte prima – Capitolo 1", "Parte prima – Capitolo 2",
                      "Parte seconda – Capitolo 1", "Parte seconda – Capitolo 2"]


def test_titoli_distinti_la_parte_si_legge_in_testa(tmp_path):
    p = tmp_path / "parti.epub"
    _write_parts_epub(p, [("Parte prima", [("Risotto e tartufi", "Uno."), ("Il gran passo", "Due.")]),
                          ("Parte seconda", [("Pescatori", "Tre.")])])
    chapters = E.parse_epub(str(p)).chapters
    assert [c.title for c in chapters] == ["Risotto e tartufi", "Il gran passo", "Pescatori"]
    assert chapters[0].text.startswith("Parte prima.\n\n")
    assert not chapters[1].text.startswith("Parte")
    assert chapters[2].text.startswith("Parte seconda.\n\n")


def test_spine_senza_ripetizioni_invariato(tmp_path):
    p = tmp_path / "ok.epub"
    docs = {f"c{i}": (f"Capitolo {i}", [f"{i}. {_PARA}"] * 8) for i in range(1, 4)}
    _write_epub(p, docs, ["c1", "c2", "c3"])
    assert [c.title for c in E.parse_epub(str(p)).chapters] == ["Capitolo 1", "Capitolo 2", "Capitolo 3"]
