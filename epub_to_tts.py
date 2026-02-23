#!/usr/bin/env python3
"""
epub_to_tts.py — Converte un file EPUB in testo ottimizzato per sintesi vocale (TTS).

Produce output pulito e strutturato per capitoli, pronto per essere usato
con tts_reader.py o qualsiasi motore TTS (edge-tts, Azure, ecc.).

Requisiti: pip install ebooklib beautifulsoup4 lxml

Uso:
  python epub_to_tts.py libro.epub
  python epub_to_tts.py libro.epub -o cartella_output
  python epub_to_tts.py libro.epub --single-file
  python epub_to_tts.py libro.epub --info
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import ebooklib
    from ebooklib import epub
except ImportError:
    print("ERRORE: ebooklib non installato. Eseguire: pip install ebooklib", file=sys.stderr)
    sys.exit(1)

try:
    from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning
    import warnings
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:
    print("ERRORE: beautifulsoup4 non installato. Eseguire: pip install beautifulsoup4 lxml", file=sys.stderr)
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════
# CONFIGURAZIONE PULIZIA TESTO
# ═══════════════════════════════════════════════════════════════════

# Tag HTML il cui contenuto viene completamente scartato
TAGS_TO_REMOVE_WITH_CONTENT = {
    "script", "style", "nav", "aside", "footer", "header",
    "figcaption", "figure", "table", "svg", "math", "code", "pre",
    "sup", "sub",  # apici/pedici — quasi sempre numeri di nota o formule
    "noscript", "iframe", "object", "embed", "canvas", "form", "input",
    "select", "textarea", "button", "map", "area",
}

# Tag che indicano un'interruzione di blocco (paragrafo/sezione)
BLOCK_TAGS = {
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "blockquote", "section", "article", "br", "hr",
}

# Tag heading per identificare titoli di capitolo
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

# Classi CSS comuni da escludere (non fruibili in audio)
CLASSES_TO_SKIP = {
    # Note
    "footnote", "footnotes", "endnote", "endnotes", "note", "notes",
    "noteref", "noterefs", "fn", "fnref",
    # Numeri di pagina
    "pagenum", "page-number", "pageno", "page-break", "running-head",
    # Indice / TOC
    "toc", "table-of-contents", "contents", "calibre_toc",
    "toc-entry", "toc-item", "toc-link", "toc-list",
    # Indice analitico
    "index", "index-entry", "index-item", "index-group",
    "book-index", "subject-index", "name-index",
    # Bibliografia / riferimenti
    "bibliography", "references", "biblio", "bib-entry",
    "citation", "citations", "works-cited", "further-reading",
    "ref-list", "reference-list", "sources",
    # Sidebar / decorazioni
    "sidebar", "pullquote", "infobox", "textbox", "tip", "warning",
    # Copyright / colophon
    "copyright", "colophon", "imprint", "legal",
    # Glossario
    "glossary", "glossary-entry", "glossary-term", "glossary-def",
    # Appendici editoriali
    "appendix-notes", "editorial-note", "editors-note",
    "translator-note", "pub-info", "book-info",
}

# ── epub:type values da escludere (EPUB3 semantic inflection) ──
EPUB_TYPES_TO_SKIP = {
    # Note
    "footnote", "footnotes", "endnote", "endnotes", "noteref",
    "annotation", "rearnote", "rearnotes",
    # Apparato critico
    "bibliography", "biblioentry", "glossary", "glossterm", "glossdef",
    "index", "index-headnotes", "index-group", "index-entry",
    "index-term", "index-locator",
    # Front/back matter non narrativo
    "toc", "landmarks", "lot", "loi", "loa",  # list of tables/illustrations/audio
    "colophon", "imprint", "copyright-page",
    "errata", "appendix",
    # Riferimenti editoriali
    "contributors", "other-credits", "acknowledgments",
}

# ── Nomi file tipici di sezioni non-audio ──
# Match ESATTO sullo stem (dopo strip di - e _) — per nomi brevi/ambigui
NON_CONTENT_FILENAMES_EXACT = {
    "toc", "nav", "contents", "cover", "colophon",
    "copyright", "titlepage", "halftitle", "frontmatter", "backmatter",
    "landmarks", "dedication", "epigraph", "notes", "endnotes",
    "footnotes", "biblio", "bibliography", "references", "glossary",
    # NON includiamo "index" — troppo ambiguo, in molti EPUB è il file principale
}
# Match SUBSTRING sullo stem — solo per termini lunghi e inequivocabili
NON_CONTENT_FILENAMES_SUBSTR = {
    "bibliography", "footnotes", "endnotes", "glossary",
    "colophon", "frontmatter", "backmatter", "tableofcontents",
}

# Pattern di testo da rimuovere
# ── Pattern che causano SKIP dell'intera riga (righe che sono solo rumore) ──
LINE_SKIP_PATTERNS = [
    r"^\s*\d{1,4}\s*$",                  # Numeri di pagina isolati
    r"^\s*[*\u2022\u25CF]{1,5}\s*$",     # Asterischi/bullet decorativi isolati
    r"^\s*[-*_=~#]{3,}\s*$",             # Separatori visivi (---, ***, ===, ###)
    r"^\s*#{1,6}\s*$",                   # Solo hash senza testo
]

# ── Pattern di sostituzione (rimuovono porzioni dal testo) ──
NOISE_PATTERNS = [
    # Riferimenti a note [1], [2], (1), {1}, [a], ecc.
    (r"\[\d+\]", ""),
    (r"\{\d+\}", ""),
    (r"\[[a-z]\]", ""),
    # Apici numerici rimasti (Unicode superscript digits)
    (r"[\u00b9\u00b2\u00b3\u2070-\u2079]+", ""),
    # Daggers, asterischi di nota (†, ‡)
    (r"[†‡\u2020\u2021]", ""),
    # Simboli di sezione § e paragrafo ¶
    (r"[§¶]", ""),
    # Markdown heading markers a inizio riga (## ### ecc.)
    (r"^\s*#{1,6}\s+", ""),
    # Cancelletti in sequenza
    (r"#{2,}", ""),
    # URL
    (r"https?://\S+", ""),
    # Email
    (r"\S+@\S+\.\S+", ""),
    # ISBN
    (r"ISBN[\s:-]*[\d-]{10,}", ""),
    # DOI
    (r"doi[\s:]*10\.\S+", ""),
    # Riferimenti bibliografici tipo "pp. 123-456" o "p. 23"
    (r"\bp+\.\s*\d[\d\s,\-–—]+", ""),
    # Indicazioni tipo "(vedi cap. 3)" "(see p. 45)" "(cfr. nota 12)"
    (r"\([Vv]edi\s+[^)]*\)", ""),
    (r"\([Ss]ee\s+[^)]*\)", ""),
    (r"\([Cc]fr\.?\s+[^)]*\)", ""),
    # Parentesi quadre residue vuote
    (r"\[\s*\]", ""),
    # Pipe | da tabelle
    (r"\|", " "),
    # Backslash isolati
    (r"\\(?!\w)", ""),
]

# Espansione abbreviazioni comuni per TTS più naturale
ABBREVIATIONS = {
    "ecc.": "eccetera",
    "etc.": "eccetera",
    "pag.": "pagina",
    "pagg.": "pagine",
    "cap.": "capitolo",
    "capp.": "capitoli",
    "vol.": "volume",
    "voll.": "volumi",
    "fig.": "figura",
    "figg.": "figure",
    "tab.": "tabella",
    "tabb.": "tabelle",
    "cfr.": "confronta",
    "cit.": "citato",
    "op. cit.": "opera citata",
    "ibid.": "ibidem",
    "n.d.r.": "nota del redattore",
    "n.d.t.": "nota del traduttore",
    "n.d.a.": "nota dell'autore",
    "es.": "esempio",
    "ad es.": "ad esempio",
    "p.es.": "per esempio",
    "sig.": "signor",
    "sig.ra": "signora",
    "dott.": "dottor",
    "dott.ssa": "dottoressa",
    "prof.": "professor",
    "prof.ssa": "professoressa",
    "avv.": "avvocato",
    "ing.": "ingegner",
    "arch.": "architetto",
    "geom.": "geometra",
    "sez.": "sezione",
    "par.": "paragrafo",
    "art.": "articolo",
    "artt.": "articoli",
    "lett.": "lettera",
    "c.d.": "cosiddetto",
    "ca.": "circa",
    "sec.": "secolo",
    "a.C.": "avanti Cristo",
    "d.C.": "dopo Cristo",
    # Inglesi comuni
    "e.g.": "for example",
    "i.e.": "that is",
    "vs.": "versus",
    "Dr.": "Doctor",
    "Mr.": "Mister",
    "Mrs.": "Missis",
    "St.": "Saint",
    "Jr.": "Junior",
    "Sr.": "Senior",
}

# Marker di pausa TTS (inseriti nel testo, interpretati dal motore TTS o dallo script)
CHAPTER_PAUSE = "\n\n...\n\n"  # Pausa lunga tra capitoli
SECTION_PAUSE = "\n\n"         # Pausa media tra sezioni


# ═══════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Chapter:
    """Un capitolo estratto dall'EPUB."""
    index: int
    title: str
    text: str
    word_count: int = 0
    char_count: int = 0
    source_file: str = ""

    def __post_init__(self):
        self.word_count = len(self.text.split())
        self.char_count = len(self.text)


@dataclass
class BookInfo:
    """Metadati del libro."""
    title: str = "Sconosciuto"
    author: str = "Sconosciuto"
    language: str = ""
    publisher: str = ""
    description: str = ""
    chapters: list[Chapter] = field(default_factory=list)
    total_words: int = 0
    total_chars: int = 0
    estimated_duration_minutes: float = 0.0


# ═══════════════════════════════════════════════════════════════════
# HTML → TEXT EXTRACTION
# ═══════════════════════════════════════════════════════════════════

def should_skip_element(tag: Tag) -> bool:
    """Determina se un elemento HTML va ignorato."""
    if not isinstance(tag, Tag) or tag.name is None:
        return False

    if tag.name in TAGS_TO_REMOVE_WITH_CONTENT:
        return True

    # Protezione: alcuni tag hanno attrs=None (es. in documenti XML/XHTML)
    if tag.attrs is None:
        return False

    css_classes = tag.get("class", [])
    if isinstance(css_classes, str):
        css_classes = css_classes.split()

    for cls in css_classes:
        cls_lower = cls.lower()
        if any(skip in cls_lower for skip in CLASSES_TO_SKIP):
            return True

    # Elementi con id che suggerisce contenuto non-audio
    el_id = (tag.get("id") or "").lower()
    if el_id and any(skip in el_id for skip in CLASSES_TO_SKIP):
        return True

    # Elementi con role specifici da saltare
    role = tag.get("role", "").lower()
    if role in ("navigation", "complementary", "contentinfo", "note",
                "directory", "doc-bibliography", "doc-endnotes",
                "doc-glossary", "doc-index", "doc-toc"):
        return True

    # epub:type — controlla contro il set esteso (con supporto namespace)
    epub_type = tag.get("epub:type", "").lower()
    if epub_type:
        for et in epub_type.split():
            if et in EPUB_TYPES_TO_SKIP:
                return True
            if ":" in et:
                short = et.split(":", 1)[1]
                if short in EPUB_TYPES_TO_SKIP:
                    return True

    return False


def extract_text_from_element(element, depth: int = 0) -> list[str]:
    """
    Estrae ricorsivamente testo da un elemento HTML,
    rispettando la struttura a blocchi e heading.
    """
    parts = []

    if isinstance(element, NavigableString):
        text = str(element)
        if text.strip():
            parts.append(text)
        return parts

    if not isinstance(element, Tag):
        return parts

    if should_skip_element(element):
        return parts

    tag_name = element.name.lower() if element.name else ""

    # Heading → raccolgo come titolo di sezione (senza marcatori)
    if tag_name in HEADING_TAGS:
        heading_text = element.get_text(strip=True)
        if heading_text:
            parts.append(f"\n\n{heading_text}\n\n")
        return parts

    # <br> → newline
    if tag_name == "br":
        parts.append("\n")
        return parts

    # <hr> → pausa di sezione
    if tag_name == "hr":
        parts.append(SECTION_PAUSE)
        return parts

    # Raccoglie contenuto figli
    is_block = tag_name in BLOCK_TAGS

    if is_block:
        parts.append("\n")

    for child in element.children:
        parts.extend(extract_text_from_element(child, depth + 1))

    if is_block:
        parts.append("\n")

    # Gestione <li> → aggiungi punto elenco leggibile
    if tag_name == "li":
        # Trasforma in frase leggibile
        inner = "".join(parts).strip()
        if inner:
            return [f"\n{inner}.\n"]
        return []

    return parts


def html_to_text(html_content: str) -> str:
    """Converte HTML in testo pulito per TTS."""
    soup = BeautifulSoup(html_content, "lxml")

    # Rimuovi completamente tag non voluti
    for tag_name in TAGS_TO_REMOVE_WITH_CONTENT:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Rimuovi note (epub:type, class, role)
    for tag in soup.find_all(True):
        if should_skip_element(tag):
            tag.decompose()

    # Rimuovi link a note (<a> con href="#note...", "#fn...", "#ref...", ecc.)
    NOTE_HREF_PATTERNS = ("#note", "#fn", "#endnote", "#footnote",
                          "#ref", "#bib", "#cite", "#annot", "#en-",
                          "#sdfootnote", "#_ftn", "#_edn")
    for a_tag in soup.find_all("a"):
        href = (a_tag.get("href") or "").lower()
        if any(n in href for n in NOTE_HREF_PATTERNS):
            a_tag.decompose()
            continue
        # epub:type noteref su <a>
        epub_type = (a_tag.get("epub:type") or "").lower()
        if "noteref" in epub_type:
            a_tag.decompose()
            continue
        # <a> che contiene solo un numero (tipico riferimento a nota)
        a_text = a_tag.get_text(strip=True)
        if a_text.isdigit() and len(a_text) <= 3:
            a_tag.decompose()
            continue

    # Estrai testo
    body = soup.find("body") or soup
    parts = extract_text_from_element(body)
    text = "".join(parts)

    return text


# ═══════════════════════════════════════════════════════════════════
# PULIZIA E OTTIMIZZAZIONE TESTO PER TTS
# ═══════════════════════════════════════════════════════════════════

def clean_text_for_tts(text: str, expand_abbr: bool = True) -> str:
    """Pulisce e ottimizza il testo per la sintesi vocale."""

    # 1. Normalizza Unicode (NFC)
    text = unicodedata.normalize("NFC", text)

    # 2. Sostituisci caratteri problematici
    replacements = {
        "\u00a0": " ",      # Non-breaking space → spazio
        "\u200b": "",       # Zero-width space → rimuovi
        "\u200c": "",       # Zero-width non-joiner
        "\u200d": "",       # Zero-width joiner
        "\ufeff": "",       # BOM
        "\u2013": " — ",    # En-dash → em-dash con spazi (pausa naturale)
        "\u2014": " — ",    # Em-dash → con spazi
        "\u2018": "'",      # Virgolette smart → dritte
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",    # Ellipsis
        "\u00ab": '"',      # Guillemets «»
        "\u00bb": '"',
        "\u2022": "",       # Bullet
        "\u25cf": "",       # Black circle
        "\u25cb": "",       # White circle
        "\u25a0": "",       # Black square
        "\u25a1": "",       # White square
        "\u25aa": "",       # Small black square
        "\u25ab": "",       # Small white square
        "\u25b6": "",       # Right triangle
        "\u25c0": "",       # Left triangle
        "\u2023": "",       # Triangular bullet
        "\u2043": "",       # Hyphen bullet
        "\u204b": "",       # Reversed pilcrow
        "\u2020": "",       # Dagger †
        "\u2021": "",       # Double dagger ‡
        "\u00a7": "",       # Section sign §
        "\u00b6": "",       # Pilcrow ¶
        "\u00b0": " gradi ",  # Degree sign → parola
        "\u00b9": "",       # Superscript 1
        "\u00b2": "",       # Superscript 2
        "\u00b3": "",       # Superscript 3
        "\u2070": "",       # Superscript 0
        "\u2074": "",       # Superscript 4
        "\u2075": "",       # Superscript 5
        "\u2076": "",       # Superscript 6
        "\u2077": "",       # Superscript 7
        "\u2078": "",       # Superscript 8
        "\u2079": "",       # Superscript 9
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # 2b. Rimuovi caratteri di formattazione inutili per la lettura
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)    # Markdown headings a inizio riga (# ## ### ...)
    text = re.sub(r"(?<!\w)#+(?!\w)", "", text)    # # isolati (non dentro parole come C#)
    text = re.sub(r"\*{1,3}(\S)", r"\1", text)  # *bold* / **bold** → solo testo
    text = re.sub(r"(\S)\*{1,3}", r"\1", text)  # chiusura bold/italic
    text = re.sub(r"_{2,}", "", text)            # Underscore decorativi __
    text = re.sub(r"~{2,}", "", text)            # Tilde decorativi ~~strikethrough~~
    text = re.sub(r"`+", "", text)               # Backtick di codice
    text = re.sub(r"\|", " ", text)               # Pipe (artefatti di tabelle)
    text = re.sub(r"\\(?![nrt])", "", text)       # Backslash non-escape
    text = re.sub(r"<[^>]+>", "", text)          # Tag HTML residui
    text = re.sub(r"&\w+;", "", text)            # Entità HTML residue (&amp; ecc.)
    text = re.sub(r"&\#\d+;", "", text)          # Entità HTML numeriche

    # 3. Rimuovi pattern di rumore
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        skip = False
        for pattern, replacement in NOISE_PATTERNS:
            if re.match(pattern, line):
                if replacement:
                    line = replacement
                else:
                    skip = True
                break
            line = re.sub(pattern, replacement, line)
        if not skip:
            cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    # 4. Espandi abbreviazioni
    if expand_abbr:
        # Ordina per lunghezza decrescente (così "op. cit." viene prima di "cit.")
        sorted_abbr = sorted(ABBREVIATIONS.items(), key=lambda x: -len(x[0]))
        for abbr, expansion in sorted_abbr:
            # Usa word boundary per evitare sostituzioni parziali
            escaped = re.escape(abbr)
            text = re.sub(
                rf"(?<!\w){escaped}(?!\w)",
                expansion,
                text,
                flags=re.IGNORECASE
            )

    # 5. Gestione numeri romani per capitoli
    def roman_to_readable(m):
        roman = m.group(1)
        prefix = m.group(0).replace(roman, "").strip()
        return f"{prefix} {roman}"

    text = re.sub(
        r"(Capitolo|Chapter|Cap\.?|Parte|Part)\s+((?=[MDCLXVI])[MDCLXVI]+)",
        roman_to_readable,
        text,
        flags=re.IGNORECASE,
    )

    # 6. Normalizza spazi e righe vuote
    text = re.sub(r"[ \t]+", " ", text)           # Spazi multipli → singolo
    text = re.sub(r" *\n *", "\n", text)           # Trim spazi intorno a newline
    text = re.sub(r"\n{4,}", "\n\n\n", text)       # Max 3 newline consecutive
    text = re.sub(r"(\n\s*){3,}", "\n\n", text)    # Righe vuote eccessive

    # 7. Pulisci punteggiatura
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)   # Spazio prima di punteggiatura
    text = re.sub(r"([.,;:!?]){3,}", r"\1\1", text)  # Punteggiatura ripetuta
    text = re.sub(r'"{2,}', '"', text)              # Virgolette doppie

    # 8. Rimuovi righe troppo corte isolate (probabilmente artefatti)
    lines = text.split("\n")
    result_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and len(stripped) < 3 and not stripped[-1] in ".!?:":
            # Riga cortissima senza punteggiatura — probabilmente rumore
            continue
        result_lines.append(line)
    text = "\n".join(result_lines)

    # 9. Assicura che il testo finisca con un punto
    text = text.strip()
    if text and text[-1] not in ".!?…":
        text += "."

    return text


def format_heading_for_tts(heading: str) -> str:
    """Formatta un heading di capitolo per lettura TTS naturale."""
    heading = heading.strip()

    # Rimuovi numerazione tipo "Capitolo 1:" / "Chapter 3 -" e tieni solo il titolo
    # ma mantieni "Capitolo X" se è l'unica cosa
    m = re.match(
        r"^(Capitolo|Chapter|Cap\.?|Parte|Part|Sezione|Section)\s*[.:—\-]?\s*(\d+|[IVXLCDM]+)\s*[.:—\-]?\s*(.*)",
        heading,
        re.IGNORECASE,
    )
    if m:
        prefix = m.group(1)
        number = m.group(2)
        title = m.group(3).strip(" .:—-")
        if title:
            return f"{prefix} {number}. {title}."
        else:
            return f"{prefix} {number}."

    # Se è solo un titolo, aggiunge punto finale per pausa TTS
    if heading and heading[-1] not in ".!?":
        heading += "."

    return heading


# ═══════════════════════════════════════════════════════════════════
# EPUB PARSING
# ═══════════════════════════════════════════════════════════════════

def detect_chapter_title(html_content: str) -> Optional[str]:
    """Tenta di estrarre il titolo del capitolo dall'HTML."""
    soup = BeautifulSoup(html_content, "lxml")

    # Cerca il primo heading
    for tag_name in ["h1", "h2", "h3"]:
        tag = soup.find(tag_name)
        if tag:
            title = tag.get_text(strip=True)
            if title and len(title) < 200:
                return title

    # Cerca titolo in <title>
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)
        if title and len(title) < 200 and title.lower() not in ("", "untitled"):
            return title

    return None


def is_content_chapter(text: str, title: str = "") -> bool:
    """Determina se un blocco di testo è un capitolo con contenuto narrativo reale."""
    clean = text.strip()

    # Troppo corto — probabilmente frontespizio, colophon, ecc.
    if len(clean) < 100:
        return False

    word_count = len(clean.split())
    if word_count < 30:
        return False

    # Filtra pagine tipicamente non-contenuto (multilingua)
    title_lower = title.lower()
    skip_titles = [
        # ── Indice / TOC ──
        "indice", "indice generale", "indice dei contenuti", "indice analitico",
        "sommario", "table of contents", "contents", "toc",
        "table des matières", "sommaire", "índice", "índice general",
        "inhaltsverzeichnis", "inhalt",
        # ── Copyright / Colophon ──
        "copyright", "colophon", "note legali", "informazioni legali",
        "avviso legale", "legal notice", "all rights reserved",
        "copyright notice", "mentions légales", "aviso legal",
        "impressum",
        # ── Copertina / Frontespizio ──
        "frontespizio", "title page", "cover", "copertina",
        "half title", "halftitle", "page de titre",
        # ── Dedica / Epigrafe ──
        "dedica", "dedication", "dédicace", "dedicatoria",
        "epigrafe", "epigraph", "épigraphe",
        # ── Bibliografia / Riferimenti ──
        "bibliografia", "bibliography", "bibliographie", "bibliografía",
        "riferimenti bibliografici", "riferimenti", "references",
        "opere citate", "works cited", "fonti", "sources",
        "letture consigliate", "further reading", "suggested reading",
        "per approfondire", "lectures complémentaires",
        # ── Note ──
        "note", "notes", "note al testo", "note a piè di pagina",
        "note finali", "endnotes", "footnotes", "anmerkungen",
        "note dell'autore", "note del traduttore", "note del curatore",
        "note bibliografiche", "note critiche",
        # ── Glossario ──
        "glossario", "glossary", "glossaire", "glosario", "glossar",
        # ── Indice analitico ──
        "indice analitico", "indice dei nomi", "indice dei luoghi",
        "indice delle opere", "indice tematico",
        "index", "name index", "subject index", "word index",
        # ── Appendice (se puro riferimento) ──
        "appendice", "appendix", "annexe", "apéndice", "anhang",
        # ── Informazioni autore ──
        "about the author", "sull'autore", "l'autore", "l'autrice",
        "biography", "biografia", "biographie",
        "about the translator", "nota del traduttore",
        "dello stesso autore", "also by", "du même auteur",
        "altre opere", "other books",
        # ── Ringraziamenti ──
        "ringraziamenti", "acknowledgements", "acknowledgments",
        "remerciements", "agradecimientos", "danksagung",
        # ── Errata / Crediti ──
        "errata", "errata corrige", "credits", "crediti",
        "photo credits", "image credits", "illustration credits",
        # ── Prefazione / Postfazione editoriale (opzionale — includi se vuoi) ──
        # "prefazione", "preface", "foreword", "postfazione", "afterword",
    ]
    if any(skip in title_lower for skip in skip_titles):
        return False

    # Euristica content-based: rileva sezioni non-narrative dal contenuto
    lines = clean.split("\n")
    non_empty = [l.strip() for l in lines if l.strip()]
    if non_empty:
        n_lines = len(non_empty)

        # 1. Troppo righe cortissime → probabile indice/elenco
        short_lines = sum(1 for l in non_empty if len(l) < 15)
        if n_lines > 10 and short_lines / n_lines > 0.7:
            return False

        # 2. Alta densità di numeri di pagina → probabile indice
        page_ref_lines = sum(1 for l in non_empty
                            if re.search(r"\b\d{1,4}\s*$", l)  # riga finisce con numero
                            or re.search(r"\.\s*\.\s*\.\s*\d", l))  # puntini + numero
        if n_lines > 5 and page_ref_lines / n_lines > 0.4:
            return False

        # 3. Alta densità di pattern bibliografici
        bib_patterns = sum(1 for l in non_empty
                          if re.search(r"\b(19|20)\d{2}\b", l)  # anno pubblicazione
                          and re.search(r"[,;]\s", l)  # separatori multipli
                          and len(l) > 40)
        if n_lines > 5 and bib_patterns / n_lines > 0.5:
            return False

        # 4. Testo che inizia con tipici pattern di colophon/copyright
        first_500 = clean[:500].lower()
        colophon_signals = [
            "tutti i diritti", "all rights reserved", "tous droits",
            "prima edizione", "first published", "printed in",
            "stampato in", "finito di stampare", "tipografia",
            "isbn", "© ", "propriet", "vietata la riproduzione",
        ]
        if sum(1 for s in colophon_signals if s in first_500) >= 2:
            return False

    return True


def parse_epub(epub_path: str, include_toc_chapters: bool = False) -> BookInfo:
    """Parsa un file EPUB ed estrae capitoli ottimizzati per TTS."""
    book = epub.read_epub(epub_path, options={"ignore_ncx": False})

    # Metadati
    info = BookInfo()
    info.title = _get_metadata(book, "title") or Path(epub_path).stem
    info.author = _get_metadata(book, "creator") or "Sconosciuto"
    info.language = _get_metadata(book, "language") or ""
    info.publisher = _get_metadata(book, "publisher") or ""
    info.description = _get_metadata(book, "description") or ""

    # Strategia: usa la spine (ordine di lettura) per ottenere i documenti nell'ordine giusto
    spine_items = []
    for item_id, linear in book.spine:
        item = book.get_item_with_id(item_id)
        if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
            spine_items.append(item)

    # Fallback: se la spine è vuota, prendi tutti i documenti
    if not spine_items:
        spine_items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))

    # TOC per mappare file → titoli capitolo
    toc_map = _build_toc_map(book)

    # Mappa file con più voci TOC (potenziali single-file EPUB)
    toc_fragments = _build_toc_fragments(book)

    # Estrazione capitoli
    chapter_index = 0
    for item in spine_items:
        html_content = item.get_content().decode("utf-8", errors="replace")
        file_name = item.get_name()

        # ── Filtro spine-level: salta file non-contenuto per nome ──
        fn_lower = Path(file_name).stem.lower().replace("-", "").replace("_", "")
        if fn_lower in NON_CONTENT_FILENAMES_EXACT:
            continue
        if any(skip in fn_lower for skip in NON_CONTENT_FILENAMES_SUBSTR):
            continue

        # ── Filtro spine-level: salta per epub:type sull'item ──
        item_props = getattr(item, "properties", None) or []
        if isinstance(item_props, str):
            item_props = item_props.split()
        if any(p.lower() in EPUB_TYPES_TO_SKIP for p in item_props):
            continue

        # ── Filtro spine-level: salta <body epub:type="..."> ──
        if _body_has_skip_type(html_content):
            continue

        # ── Controlla se questo file contiene più capitoli ──
        if file_name in toc_fragments:
            toc_titles = toc_fragments[file_name]
            sections = _split_html_by_headings(html_content, toc_titles)

            if sections:
                # File multi-capitolo: processa ogni sezione
                for section_title, section_html in sections:
                    raw_text = html_to_text(section_html)
                    clean = clean_text_for_tts(raw_text)

                    if not is_content_chapter(clean, section_title):
                        continue

                    clean = _remove_duplicate_heading(clean, section_title)

                    chapter_index += 1
                    chapter = Chapter(
                        index=chapter_index,
                        title=section_title,
                        text=clean.strip(),
                        source_file=file_name,
                    )
                    info.chapters.append(chapter)

                continue  # Non processare il file come capitolo singolo

        # ── File singolo capitolo (comportamento originale) ──
        # Titolo: prima dal TOC, poi dall'HTML
        title = toc_map.get(file_name)
        if not title:
            title = detect_chapter_title(html_content)
        if not title:
            title = f"Sezione {chapter_index + 1}"

        # Estrai e pulisci testo
        raw_text = html_to_text(html_content)
        clean = clean_text_for_tts(raw_text)

        # Filtra capitoli vuoti o non-contenuto
        if not is_content_chapter(clean, title):
            continue

        # Rimuovi l'heading dal corpo se appare anche come titolo
        # (evita che il TTS lo legga due volte)
        clean = _remove_duplicate_heading(clean, title)

        chapter_index += 1
        chapter = Chapter(
            index=chapter_index,
            title=title,
            text=clean.strip(),
            source_file=file_name,
        )
        info.chapters.append(chapter)

    # Totali
    info.total_words = sum(c.word_count for c in info.chapters)
    info.total_chars = sum(c.char_count for c in info.chapters)
    info.estimated_duration_minutes = info.total_words / 150  # ~150 parole/min

    return info


def _get_metadata(book: epub.EpubBook, field: str) -> Optional[str]:
    """Estrae un campo metadata dall'EPUB."""
    try:
        values = book.get_metadata("DC", field)
        if values:
            val = values[0][0]
            if isinstance(val, str):
                return val.strip()
    except Exception:
        pass
    return None


def _body_has_skip_type(html_content: str) -> bool:
    """Controlla se il <body> o <section> principale ha epub:type non-audio."""
    # Fast check senza parsing completo — cerca nell'header del documento
    head = html_content[:2000].lower()
    for etype in EPUB_TYPES_TO_SKIP:
        if f'epub:type="{etype}"' in head or f"epub:type='{etype}'" in head:
            return True
        if f'epub:type="{etype} ' in head or f"epub:type='{etype} " in head:
            return True
    return False


def _build_toc_map(book: epub.EpubBook) -> dict[str, str]:
    """Costruisce una mappa file_path → titolo dal Table of Contents."""
    toc_map = {}

    def walk_toc(items):
        for item in items:
            if isinstance(item, tuple):
                section, children = item
                if hasattr(section, "href") and hasattr(section, "title"):
                    href = section.href.split("#")[0]
                    toc_map[href] = section.title
                walk_toc(children)
            elif hasattr(item, "href") and hasattr(item, "title"):
                href = item.href.split("#")[0]
                toc_map[href] = item.title

    try:
        walk_toc(book.toc)
    except Exception:
        pass

    return toc_map


def _build_toc_fragments(book: epub.EpubBook) -> dict[str, list[str]]:
    """
    Costruisce una mappa file_path → [titoli ordinati] per file con più voci TOC.
    Serve per rilevare EPUB "single-file" dove tutti i capitoli sono in un unico HTML.
    """
    file_titles = {}

    def walk_toc(items):
        for item in items:
            if isinstance(item, tuple):
                section, children = item
                if hasattr(section, "href") and hasattr(section, "title"):
                    href_file = section.href.split("#")[0]
                    file_titles.setdefault(href_file, []).append(section.title)
                walk_toc(children)
            elif hasattr(item, "href") and hasattr(item, "title"):
                href_file = item.href.split("#")[0]
                file_titles.setdefault(href_file, []).append(item.title)

    try:
        walk_toc(book.toc)
    except Exception:
        pass

    # Ritorna solo i file con 2+ voci TOC (quelli da spezzare)
    return {f: titles for f, titles in file_titles.items() if len(titles) >= 2}


def _split_html_by_headings(html_content: str, toc_titles: list[str]) -> list[tuple[str, str]]:
    """
    Spezza un singolo documento HTML in sezioni basandosi sugli heading.

    Strategia:
    1. Trova tutti gli heading (h1-h6) nel documento
    2. Matcha ogni heading con un titolo del TOC (fuzzy match)
    3. Estrai il contenuto HTML tra heading consecutivi
    4. Converti ogni sezione in testo

    Returns: lista di (titolo, html_della_sezione)
    """
    soup = BeautifulSoup(html_content, "lxml")

    # Rimuovi tag non voluti
    for tag_name in TAGS_TO_REMOVE_WITH_CONTENT:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    body = soup.find("body") or soup

    # Trova tutti gli heading nel documento
    all_headings = body.find_all(HEADING_TAGS)

    if not all_headings:
        return []

    # Normalizza i titoli TOC per matching
    def normalize(text: str) -> str:
        """Normalizza testo per confronto fuzzy."""
        text = re.sub(r"\s+", " ", text.strip().lower())
        text = re.sub(r"[^\w\s]", "", text)
        return text

    normalized_toc = [normalize(t) for t in toc_titles]

    def matches_toc(heading_text: str) -> Optional[int]:
        """Ritorna l'indice del titolo TOC corrispondente, o None."""
        norm = normalize(heading_text)
        if not norm or len(norm) < 3:
            return None

        # Match esatto
        for i, toc_norm in enumerate(normalized_toc):
            if norm == toc_norm:
                return i

        # Il titolo TOC è contenuto nell'heading o viceversa
        for i, toc_norm in enumerate(normalized_toc):
            if toc_norm in norm or norm in toc_norm:
                return i

        # Match parziale: almeno 60% delle parole del TOC presenti nell'heading
        for i, toc_norm in enumerate(normalized_toc):
            toc_words = set(toc_norm.split())
            head_words = set(norm.split())
            if len(toc_words) >= 2:
                overlap = len(toc_words & head_words) / len(toc_words)
                if overlap >= 0.6:
                    return i

        return None

    # Identifica gli heading che corrispondono a capitoli del TOC
    chapter_headings = []
    for heading in all_headings:
        text = heading.get_text(strip=True)
        toc_idx = matches_toc(text)
        if toc_idx is not None:
            chapter_headings.append({
                "element": heading,
                "toc_index": toc_idx,
                "title": toc_titles[toc_idx],
            })

    if not chapter_headings:
        # Nessun match con il TOC — prova a usare tutti gli heading dello stesso livello
        # più frequente come separatori di capitolo
        from collections import Counter
        level_counts = Counter(h.name for h in all_headings)
        if level_counts:
            most_common_level = level_counts.most_common(1)[0][0]
            level_headings = [h for h in all_headings if h.name == most_common_level]
            if len(level_headings) >= 2:
                for i, heading in enumerate(level_headings):
                    text = heading.get_text(strip=True)
                    chapter_headings.append({
                        "element": heading,
                        "toc_index": i,
                        "title": text if len(text) < 150 else text[:100],
                    })

    if len(chapter_headings) < 2:
        return []

    # Estrai HTML tra heading consecutivi
    sections = []
    for i, ch in enumerate(chapter_headings):
        heading_el = ch["element"]
        title = ch["title"]

        # Raccogli tutti gli elementi tra questo heading e il prossimo
        section_parts = []
        current = heading_el.next_sibling

        # Determina l'elemento di stop (prossimo heading capitolo)
        stop_element = None
        if i + 1 < len(chapter_headings):
            stop_element = chapter_headings[i + 1]["element"]

        while current:
            if current == stop_element:
                break
            if isinstance(current, Tag):
                section_parts.append(str(current))
            elif isinstance(current, NavigableString):
                text = str(current).strip()
                if text:
                    section_parts.append(text)
            current = current.next_sibling

        section_html = "".join(section_parts)
        if section_html.strip():
            sections.append((title, f"<body>{section_html}</body>"))

    return sections


def _remove_duplicate_heading(text: str, title: str) -> str:
    """Rimuove il titolo dal corpo del testo se appare all'inizio."""
    if not title:
        return text

    # Cerca titolo all'inizio del testo (con eventuale punto finale)
    pattern = re.escape(title.rstrip("."))
    text = re.sub(rf"^\s*{pattern}\.?\s*\n+", "", text, count=1, flags=re.IGNORECASE)

    return text


# ═══════════════════════════════════════════════════════════════════
# OUTPUT FORMATTERS
# ═══════════════════════════════════════════════════════════════════

def write_single_file(info: BookInfo, output_path: str):
    """Scrive tutti i capitoli in un unico file .txt."""
    with open(output_path, "w", encoding="utf-8") as f:
        # Intestazione libro
        f.write(f"{info.title}\n")
        f.write(f"di {info.author}\n")
        f.write(CHAPTER_PAUSE)

        for i, chapter in enumerate(info.chapters):
            # Titolo capitolo (formattato per TTS)
            tts_title = format_heading_for_tts(chapter.title)
            f.write(f"{tts_title}\n\n")

            # Corpo
            f.write(chapter.text)

            # Pausa tra capitoli
            if i < len(info.chapters) - 1:
                f.write(CHAPTER_PAUSE)

        f.write("\n\nFine.\n")


def write_chapter_files(info: BookInfo, output_dir: str):
    """Scrive ogni capitolo in un file separato, numerato."""
    os.makedirs(output_dir, exist_ok=True)

    # File indice/manifesto
    manifest = {
        "title": info.title,
        "author": info.author,
        "language": info.language,
        "total_chapters": len(info.chapters),
        "total_words": info.total_words,
        "estimated_duration_minutes": round(info.estimated_duration_minutes, 1),
        "chapters": [],
    }

    for chapter in info.chapters:
        # Nome file: 001_titolo_capitolo.txt
        safe_title = re.sub(r"[^\w\s-]", "", chapter.title)
        safe_title = re.sub(r"\s+", "_", safe_title.strip())[:50]
        filename = f"{chapter.index:03d}_{safe_title}.txt"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            tts_title = format_heading_for_tts(chapter.title)
            f.write(f"{tts_title}\n\n")
            f.write(chapter.text)
            f.write("\n")

        manifest["chapters"].append({
            "index": chapter.index,
            "title": chapter.title,
            "file": filename,
            "words": chapter.word_count,
            "chars": chapter.char_count,
            "estimated_minutes": round(chapter.word_count / 150, 1),
        })

    # Scrivi manifesto JSON
    manifest_path = os.path.join(output_dir, "_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # Scrivi script batch per generazione audio
    write_batch_script(info, output_dir, manifest)


def write_batch_script(info: BookInfo, output_dir: str, manifest: dict):
    """Genera script batch per convertire tutti i capitoli in audio."""
    # Determina voce default dalla lingua
    lang = info.language.lower()[:2] if info.language else "it"
    default_voice = "it-IT-IsabellaNeural" if lang == "it" else "en-US-JennyNeural"

    # Script bash/shell
    sh_path = os.path.join(output_dir, "genera_audio.sh")
    with open(sh_path, "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\n")
        f.write(f'# Genera audiolibro: {info.title}\n')
        f.write(f'# Autore: {info.author}\n')
        f.write(f'# Capitoli: {len(info.chapters)}, Parole: {info.total_words:,}\n')
        f.write(f'# Durata stimata: ~{info.estimated_duration_minutes:.0f} minuti\n\n')
        f.write(f'VOICE="${{1:-{default_voice}}}"\n')
        f.write(f'RATE="${{2:-+0%}}"\n')
        f.write('SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n')
        f.write('AUDIO_DIR="${SCRIPT_DIR}/audio"\n')
        f.write('mkdir -p "${AUDIO_DIR}"\n\n')
        f.write(f'echo "Generazione audiolibro: {info.title}"\n')
        f.write(f'echo "Voce: $VOICE | Velocità: $RATE"\n')
        f.write(f'echo "Capitoli: {len(info.chapters)}"\n')
        f.write('echo "─────────────────────────────────"\n\n')

        for ch in manifest["chapters"]:
            mp3_name = ch["file"].replace(".txt", ".mp3")
            f.write(f'echo "[{ch["index"]}/{len(info.chapters)}] {ch["title"]}"\n')
            f.write(f'python tts_reader.py "${{SCRIPT_DIR}}/{ch["file"]}" '
                    f'-v "$VOICE" -r "$RATE" -o "${{AUDIO_DIR}}/{mp3_name}"\n\n')

        f.write('echo ""\n')
        f.write('echo "✓ Audiolibro generato in ${AUDIO_DIR}"\n')

    os.chmod(sh_path, 0o755)

    # Script PowerShell (Windows)
    ps_path = os.path.join(output_dir, "genera_audio.ps1")
    with open(ps_path, "w", encoding="utf-8") as f:
        f.write(f'# Genera audiolibro: {info.title}\n')
        f.write(f'# Autore: {info.author}\n')
        f.write(f'# Capitoli: {len(info.chapters)}, Parole: {info.total_words:,}\n')
        f.write(f'# Durata stimata: ~{info.estimated_duration_minutes:.0f} minuti\n\n')
        f.write(f'param(\n')
        f.write(f'    [string]$Voice = "{default_voice}",\n')
        f.write(f'    [string]$Rate = "+0%"\n')
        f.write(f')\n\n')
        f.write('$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition\n')
        f.write('$AudioDir = Join-Path $ScriptDir "audio"\n')
        f.write('New-Item -ItemType Directory -Force -Path $AudioDir | Out-Null\n\n')
        f.write(f'Write-Host "Generazione audiolibro: {info.title}"\n')
        f.write(f'Write-Host "Voce: $Voice | Velocita: $Rate"\n')
        f.write(f'Write-Host "Capitoli: {len(info.chapters)}"\n')
        f.write('Write-Host ("-" * 40)\n\n')

        for ch in manifest["chapters"]:
            mp3_name = ch["file"].replace(".txt", ".mp3")
            f.write(f'Write-Host "[{ch["index"]}/{len(info.chapters)}] {ch["title"]}"\n')
            f.write(f'python tts_reader.py "$ScriptDir\\{ch["file"]}" '
                    f'-v $Voice -r $Rate -o "$AudioDir\\{mp3_name}"\n\n')

        f.write('Write-Host ""\n')
        f.write('Write-Host "Audiolibro generato in $AudioDir"\n')


def print_book_info(info: BookInfo):
    """Stampa un riepilogo del libro estratto."""
    print(f"\n{'═'*60}")
    print(f"  {info.title}")
    print(f"  di {info.author}")
    print(f"{'═'*60}")

    if info.language:
        print(f"  Lingua:     {info.language}")
    if info.publisher:
        print(f"  Editore:    {info.publisher}")

    print(f"  Capitoli:   {len(info.chapters)}")
    print(f"  Parole:     {info.total_words:,}")
    print(f"  Caratteri:  {info.total_chars:,}")
    print(f"  Durata ~    {info.estimated_duration_minutes:.0f} minuti")
    print(f"{'─'*60}")

    for ch in info.chapters:
        est = ch.word_count / 150
        print(f"  {ch.index:3d}. {ch.title[:45]:<45s} {ch.word_count:>6,} parole  ~{est:.0f} min")

    print(f"{'═'*60}\n")


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Converte un EPUB in testo ottimizzato per TTS / audiolibro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  %(prog)s libro.epub                          # Crea cartella libro_tts/ con capitoli separati
  %(prog)s libro.epub -o mio_output            # Cartella di output personalizzata
  %(prog)s libro.epub --single-file            # Un unico file .txt
  %(prog)s libro.epub --single-file -o out.txt # File singolo con nome specifico
  %(prog)s libro.epub --info                   # Solo info sul libro, senza output
  %(prog)s libro.epub --no-expand-abbr         # Non espandere abbreviazioni
        """
    )

    parser.add_argument("epub", help="File EPUB di input")
    parser.add_argument("-o", "--output", help="Percorso output (cartella o file .txt)")
    parser.add_argument("--single-file", action="store_true",
                        help="Produce un unico file .txt invece di cartella con capitoli separati")
    parser.add_argument("--info", action="store_true",
                        help="Mostra solo informazioni sul libro senza produrre output")
    parser.add_argument("--no-expand-abbr", action="store_true",
                        help="Non espandere le abbreviazioni")
    parser.add_argument("--min-words", type=int, default=30,
                        help="Parole minime per considerare un capitolo valido (default: 30)")

    args = parser.parse_args()

    # Validazione input
    epub_path = args.epub
    if not os.path.exists(epub_path):
        print(f"ERRORE: File non trovato: {epub_path}", file=sys.stderr)
        sys.exit(1)

    if not epub_path.lower().endswith(".epub"):
        print(f"ATTENZIONE: Il file non ha estensione .epub", file=sys.stderr)

    # Parsing
    print(f"Analisi EPUB: {epub_path}...")
    info = parse_epub(epub_path)

    if not info.chapters:
        print("ERRORE: Nessun capitolo con contenuto trovato nell'EPUB.", file=sys.stderr)
        sys.exit(1)

    # Info
    print_book_info(info)

    if args.info:
        return

    # Output
    if args.single_file:
        # File singolo
        output_path = args.output or Path(epub_path).with_suffix(".txt").name
        if not output_path.endswith(".txt"):
            output_path += ".txt"
        write_single_file(info, output_path)
        print(f"✓ File generato: {output_path}")
        print(f"  Uso: python tts_reader.py \"{output_path}\" -o audiolibro.mp3")

    else:
        # Cartella con capitoli separati
        output_dir = args.output or f"{Path(epub_path).stem}_tts"
        write_chapter_files(info, output_dir)
        print(f"✓ Cartella generata: {output_dir}/")
        print(f"  Contenuto: {len(info.chapters)} capitoli .txt + _manifest.json")
        print(f"  Per generare l'audio:")
        if os.name == "nt":
            print(f"    .\\{output_dir}\\genera_audio.ps1")
            print(f"    .\\{output_dir}\\genera_audio.ps1 -Voice it-IT-DiegoNeural -Rate \"-10%\"")
        else:
            print(f"    ./{output_dir}/genera_audio.sh")
            print(f"    ./{output_dir}/genera_audio.sh it-IT-DiegoNeural \"-10%\"")


if __name__ == "__main__":
    main()
