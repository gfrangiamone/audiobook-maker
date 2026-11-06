"""Spine con documenti ripetuti.

ws-export (export EPUB di Wikisource) mette nello spine i capitoli di ogni
parte due volte: dopo la pagina della parte e di nuovo in coda. ABM li leggeva
entrambe le volte e I Vicere' (06/11/2026) usciva di 49 ore invece di 25.
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


def test_spine_senza_ripetizioni_invariato(tmp_path):
    p = tmp_path / "ok.epub"
    docs = {f"c{i}": (f"Capitolo {i}", [f"{i}. {_PARA}"] * 8) for i in range(1, 4)}
    _write_epub(p, docs, ["c1", "c2", "c3"])
    assert [c.title for c in E.parse_epub(str(p)).chapters] == ["Capitolo 1", "Capitolo 2", "Capitolo 3"]
