"""PDF col testo sovrastampato due volte nello stesso punto.

Catalogo gratuito, 21/11/2026: i PDF di Liber Liber (La guerra e la pace,
Viaggi di Gulliver) hanno ogni pagina stampata due volte, stessi blocchi e
stesse coordinate. ABM leggeva ogni pagina due volte: 5,75 milioni di
caratteri invece di 2,84, pagati e sintetizzati doppi.
"""
import fitz

import pdf_to_tts as P

_LINES = ["Alle nove, sul fianco destro, dov'era Bagration, l'azione",
          "non ancora era impegnata. Il principe propose che si mandasse",
          "per ordini dal generalissimo, e il primo che vide fu Rostow."]


def _pdf(path, copies):
    doc = fitz.open()
    toc = []
    for n, title in enumerate(("Capitolo I", "Capitolo II"), 1):
        page = doc.new_page()
        for _ in range(copies):
            y = 73
            page.insert_text((72, y), title, fontsize=12)
            for t in _LINES * 4:
                y += 21
                page.insert_text((72, y), t, fontsize=12)
        toc.append([1, title, n])
    doc.set_toc(toc)
    doc.save(path)
    doc.close()


def test_testo_sovrastampato_si_legge_una_volta(tmp_path):
    single, double = tmp_path / "uno.pdf", tmp_path / "due.pdf"
    _pdf(str(single), 1)
    _pdf(str(double), 2)
    a, b = P.parse_pdf(str(single)), P.parse_pdf(str(double))
    assert [c.title for c in b.chapters] == ["Capitolo I", "Capitolo II"]
    assert [c.text for c in b.chapters] == [c.text for c in a.chapters]
    assert b.chapters[0].text.count("generalissimo") == 4


def test_blocchi_uguali_in_punti_diversi_restano(tmp_path):
    # Una riga ripetuta piu' in basso (un ritornello) non e' un doppione.
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Dormi, dormi.", fontsize=12)
    page.insert_text((72, 400), "Dormi, dormi.", fontsize=12)
    blocks = P._text_blocks(page)
    assert len(blocks) == 2
    doc.close()
