"""Ricomposizione delle righe PDF in paragrafi.

Incidente 30/09/2026: romanzo tedesco esportato da Word, capitoli riconosciuti
per stile del titolo. La strategia univa ogni riga visiva con "\\n\\n", cosi'
ogni a-capo tipografico diventava un paragrafo (10.087 su 14.248 troncati a
meta' frase): pause brusche in tutto l'audiolibro e sillabazioni ("zurück-" /
"kehren") lette spezzate. Il paragrafo deve chiudersi solo sulla riga vuota o
su un confine di blocco/pagina che chiude davvero la frase.
"""
import fitz

import pdf_to_tts as P


# ── Unione di due righe ──

def test_join_plain_lines_with_space():
    assert P._join_pdf_line("Die Sonne lag", "noch warm") == "Die Sonne lag noch warm"


def test_join_dehyphenates_before_lowercase():
    assert P._join_pdf_line("Sie wollte zurück-", "kehren") == "Sie wollte zurückkehren"


def test_join_keeps_compound_hyphen_before_uppercase():
    assert P._join_pdf_line("nach Ost-", "Berlin") == "nach Ost-Berlin"


def test_join_spaced_dash_is_not_hyphenation():
    assert P._join_pdf_line("sie zögerte –", "dann ging sie") == "sie zögerte – dann ging sie"


# ── Paragrafi ──

def test_lines_without_breaks_form_one_paragraph():
    items = [(None, "Die Sonne lag noch warm auf dem"),
             (None, "Kopfsteinpflaster, obwohl der Nachmittag"),
             (None, "bereits weit fortgeschritten war.")]
    assert P._lines_to_paragraphs(items) == (
        "Die Sonne lag noch warm auf dem Kopfsteinpflaster, obwohl der "
        "Nachmittag bereits weit fortgeschritten war.")


def test_blank_line_closes_paragraph():
    items = [(None, "Erster Absatz endet hier."),
             ("hard", "Zweiter Absatz beginnt.")]
    assert P._lines_to_paragraphs(items) == (
        "Erster Absatz endet hier.\n\nZweiter Absatz beginnt.")


def test_soft_break_mid_sentence_is_joined():
    # Cambio pagina a meta' frase: la riga prima e' lunga e non chiude la frase.
    items = [(None, "Johanna sah hinaus und bemerkte, dass der"),
             ("soft", "Zug bereits langsamer wurde.")]
    assert P._lines_to_paragraphs(items) == (
        "Johanna sah hinaus und bemerkte, dass der Zug bereits langsamer wurde.")


def test_soft_break_after_sentence_end_closes_paragraph():
    items = [(None, "Der Zug hielt an."), ("soft", "Am Bahnsteig wartete Marie.")]
    assert P._lines_to_paragraphs(items) == (
        "Der Zug hielt an.\n\nAm Bahnsteig wartete Marie.")


def test_soft_break_after_short_subheading_closes_paragraph():
    items = [(None, "26. Mai 1935"), ("soft", "Die Sonne lag noch warm.")]
    assert P._lines_to_paragraphs(items) == "26. Mai 1935\n\nDie Sonne lag noch warm."


def test_cross_page_hyphenation_rejoined_in_clean():
    assert P._clean_pdf_text("Sie wollte zurück-\n\nkehren.") == "Sie wollte zurückkehren."
    assert P._clean_pdf_text("Ende Ost-\n\nBerlin.") == "Ende Ost-\n\nBerlin."


# ── End-to-end: PDF stile Word, una riga per "line", paragrafi su riga vuota ──

def _word_like_pdf(path):
    doc = fitz.open()
    lines = [
        ("Kapitel 1", 18),
        ("", 11),
        ("Die Sonne lag noch warm auf dem Kopfsteinpflaster", 11),
        ("des Löwenberger Rings, obwohl der Nachmittag", 11),
        ("bereits weit fortgeschritten war. Sie wollte zurück-", 11),
        ("kehren, doch niemand wartete.", 11),
        ("", 11),
        ("In der Mühle am Markt roch es noch nach dem Fest.", 11),
        ("", 11),
        ("Kapitel 2", 18),
        ("", 11),
        ("Der Zug fuhr langsam aus dem Bahnhof hinaus und", 11),
        ("Johanna sah den Turm der Kirche kleiner werden.", 11),
    ]
    page = doc.new_page()
    y = 60
    # Riga vuota = span di soli spazi, come nell'export di Word.
    for t, size in lines:
        page.insert_text((50, y), t if t else " ", fontsize=size)
        y += size + 6
    doc.save(path)
    doc.close()


def test_heading_strategy_reflows_paragraphs(tmp_path):
    pdf = tmp_path / "word.pdf"
    _word_like_pdf(str(pdf))
    doc = fitz.open(str(pdf))
    raw = P._detect_chapters_from_headings(doc, 11.0, set())
    doc.close()
    texts = {title: body for title, body in raw}
    assert texts["Kapitel 1"] == (
        "Die Sonne lag noch warm auf dem Kopfsteinpflaster des Löwenberger "
        "Rings, obwohl der Nachmittag bereits weit fortgeschritten war. Sie "
        "wollte zurückkehren, doch niemand wartete."
        "\n\nIn der Mühle am Markt roch es noch nach dem Fest.")
    assert texts["Kapitel 2"] == (
        "Der Zug fuhr langsam aus dem Bahnhof hinaus und Johanna sah den Turm "
        "der Kirche kleiner werden.")


# ── Libro ben composto: a-capo legittimi senza riga vuota ──
# Paragrafi separati solo da rientro o da riga finale corta, versi, battute di
# dialogo: il reflow non deve fonderli (la pausa di paragrafo va conservata).

def _typeset_pdf(path, lines):
    """lines: (x, testo). Testo giustificato a mano: righe piene ~ stessa larghezza."""
    doc = fitz.open()
    page = doc.new_page()
    y = 60
    for x, t in lines:
        page.insert_text((x, y), t, fontsize=11)
        y += 15
    doc.save(path)
    doc.close()


_FULL = [
    "Die Sonne lag noch warm auf dem Kopfsteinpflaster des Löwenberger Rings, ob-",
    "wohl der Nachmittag bereits weit fortgeschritten war und die Schatten der Häu-",
    "ser lang über den Platz fielen, wo die Händler ihre Stände abbauten und riefen.",
]


def _body_text(tmp_path, lines):
    pdf = tmp_path / "book.pdf"
    _typeset_pdf(str(pdf), lines)
    doc = fitz.open(str(pdf))
    text = P._extract_page_text_filtered(doc[0], 11.0, set())
    doc.close()
    return text



PARA = chr(10) * 2


def _para(*lines):
    out = lines[0]
    for nxt in lines[1:]:
        out = P._join_pdf_line(out, nxt)
    return out


def test_short_last_line_closes_paragraph(tmp_path):
    # Nessuna riga vuota, nessun rientro: solo la riga finale corta.
    text = _body_text(tmp_path, [(50, _FULL[0]), (50, _FULL[1]), (50, "Niemand wartete."),
                                 (50, _FULL[2]), (50, "Dann ging sie.")])
    assert text.split(PARA) == [
        _para(_FULL[0], _FULL[1], "Niemand wartete."),
        _para(_FULL[2], "Dann ging sie."),
    ]


def test_first_line_indent_opens_paragraph(tmp_path):
    # Paragrafo precedente chiuso da riga piena: il rientro basta a separarli.
    text = _body_text(tmp_path, [(50, _FULL[0]), (50, _FULL[1]),
                                 (68, _FULL[2]), (50, _FULL[0])])
    assert text.split(PARA) == [
        _para(_FULL[0], _FULL[1]),
        _para(_FULL[2], _FULL[0]),
    ]


def test_verse_and_dialogue_lines_stay_separate(tmp_path):
    verse = ["Über allen Gipfeln", "Ist Ruh,", "In allen Wipfeln",
             "Spürest du", "\"Kommst du mit?\"", "\"Ja.\""]
    # Corpo della pagina abbastanza lungo da stimare la colonna (>= 3 righe piene).
    text = _body_text(tmp_path, [(50, _FULL[0]), (50, _FULL[1]), (50, _FULL[2]),
                                 (50, "Niemand wartete.")]
                      + [(50, v) for v in verse])
    assert text.split(PARA) == [_para(*_FULL, "Niemand wartete.")] + verse


def test_suspended_hyphen_keeps_dash():
    assert P._join_pdf_line("Ein- und", "Ausgang") == "Ein- und Ausgang"
    assert P._join_pdf_line("die Haus-", "und Gartenarbeit") == "die Haus- und Gartenarbeit"


def test_visual_lines_merges_words_on_same_baseline():
    def ln(x0, x1, t):
        return {"bbox": (x0, 100, x1, 112), "spans": [{"text": t, "size": 11, "flags": 0}]}
    merged = P._visual_lines([ln(50, 80, "Die"), ln(90, 130, "Sonne"), ln(140, 160, "lag"),
                              {"bbox": (50, 115, 90, 127),
                               "spans": [{"text": "noch", "size": 11, "flags": 0}]}])
    assert len(merged) == 2
    assert "".join(s["text"] for s in merged[0]["spans"]) == "Die Sonne lag"
    assert merged[0]["bbox"][0] == 50 and merged[0]["bbox"][2] == 160


def test_narrow_box_wrap_is_not_paragraph_break():
    # Voce di elenco in un riquadro più stretto della colonna: la riga che
    # riempie il riquadro non è "corta" rispetto alla pagina.
    def ln(x0, x1, y, t):
        return {"bbox": (x0, y, x1, y + 12), "spans": [{"text": t, "size": 11, "flags": 0}]}
    vlines = P._visual_lines([
        ln(54, 293, 100, "4. Distinguish between consent and assent and explain"),
        ln(74, 293, 115, "how both concepts are accomplished in research with"),
        ln(74, 109, 130, "children."),
    ])
    assert P._block_geometry_breaks(vlines, (54, 540)) == [None, None, None]


def test_dialogue_dash_after_full_line_opens_paragraph():
    # Testo a bandiera: la riga prima della battuta arriva quasi al margine.
    def ln(x1, y, t):
        return {"bbox": (57, y, x1, y + 12), "spans": [{"text": t, "size": 11, "flags": 0}]}
    vlines = P._visual_lines([
        ln(540, 100, "Bueno, pero es hora de presentarse. A mí me llaman Yarpen Zigrin. ¿Y a ti"),
        ln(538, 115, "cómo te llaman, canija? Dímelo ya, que el convoy no espera a nadie, niña."),
        ln(540, 130, "-De otra forma -ladró Ciri, y los ojos le brillaron mientras el enano reía."),
    ])
    assert P._block_geometry_breaks(vlines, None) == [None, None, "hard"]


def test_justified_text_narrowing_around_figure_stays_joined():
    # Il giustificato si restringe accanto a una figura: righe più corte della
    # colonna ma tutte allo stesso margine destro, nessun a-capo voluto.
    def ln(x1, y, t):
        return {"bbox": (83, y, x1, y + 12), "spans": [{"text": t, "size": 11, "flags": 0}]}
    vlines = P._visual_lines([
        ln(469.5, 100, "Ordinal scales have no absolute zero point. In the case of a test of job"),
        ln(469.5, 115, "every testtaker, regardless of standing on the test, is presumed to have"),
        ln(343.5, 130, "is presumed to have zero ability. Zero is without meaning in"),
        ln(343.5, 145, "such a test because the number of units that separate one"),
        ln(343.4, 160, "testtaker's score from another's is simply not known. The scores"),
        ln(343.3, 175, "from the next may be many, just a few, or practically none."),
    ])
    assert P._block_geometry_breaks(vlines, None) == [None] * 6
