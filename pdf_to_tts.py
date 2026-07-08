#!/usr/bin/env python3
"""
pdf_to_tts.py — Converte un file PDF in testo ottimizzato per sintesi vocale (TTS).

Produce output pulito e strutturato per capitoli, pronto per essere usato
con il motore TTS di Audiobook Maker (edge-tts, Azure, ecc.).

Il modulo rimuove automaticamente elementi non adatti all'ascolto:
  - Note a piè di pagina e note finali
  - Testo tra parentesi tonde e quadre
  - Didascalie di figure e tabelle
  - Intestazioni e piè di pagina ripetuti
  - Numeri di pagina
  - Indici, bibliografie, glossari
  - URL, ISBN, DOI e riferimenti incrociati

Strategia di segmentazione in capitoli (in ordine di priorità):
  1. Outline/bookmarks del PDF (se presenti)
  2. Rilevamento heading per font size (titoli più grandi del body text)
  3. Indice visuale — pagina "Indice"/"Contents" con titoli e numeri di pagina
  4. Fallback: intero documento come singolo capitolo

Se una strategia produce capitoli che vengono tutti filtrati come non-contenuto,
si passa automaticamente alla successiva. In ultima istanza, se il PDF contiene
testo ma nessuna strategia produce capitoli validi, il testo viene forzato
come singolo capitolo (recovery di sicurezza).

Requisiti: pip install pymupdf

Uso:
  from pdf_to_tts import parse_pdf
  info = parse_pdf("libro.pdf")  # restituisce BookInfo (stessa interfaccia di epub_to_tts)
"""

import argparse
import os
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    try:
        import pymupdf as fitz  # PyMuPDF >= 1.24 new import name
    except ImportError:
        print("ERRORE: PyMuPDF non installato. Eseguire: pip install pymupdf", file=sys.stderr)
        sys.exit(1)

# Importa strutture dati e funzioni di pulizia dal modulo EPUB
# (evita duplicazione di logica — stessa interfaccia BookInfo/Chapter)
try:
    from epub_to_tts import (
        BookInfo, Chapter, clean_text_for_tts, is_content_chapter,
        _title_is_non_content,
    )
except ImportError:
    # Fallback: definisci localmente se epub_to_tts non è disponibile
    from dataclasses import field

    @dataclass
    class Chapter:
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
        title: str = "Sconosciuto"
        author: str = "Sconosciuto"
        language: str = ""
        publisher: str = ""
        description: str = ""
        chapters: list = field(default_factory=list)
        total_words: int = 0
        total_chars: int = 0
        estimated_duration_minutes: float = 0.0

    def clean_text_for_tts(text, expand_abbr=True):
        """Fallback minimale se epub_to_tts non è disponibile."""
        text = unicodedata.normalize("NFC", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()
        if text and text[-1] not in ".!?…":
            text += "."
        return text

    def is_content_chapter(text, title=""):
        if len(text.strip()) < 100 or len(text.split()) < 30:
            return False
        return True

    def _title_is_non_content(title, phrases):
        """Fallback: match per parola intera (confini \\w Unicode)."""
        tl = (title or "").lower()
        for skip in phrases:
            if re.search(r"(?<!\w)" + re.escape(skip) + r"(?!\w)", tl):
                return True
        return False


# ═══════════════════════════════════════════════════════════════════
# CONFIGURAZIONE PULIZIA PDF
# ═══════════════════════════════════════════════════════════════════

# Font size threshold: testo più piccolo di questa percentuale rispetto
# al body text viene considerato nota/didascalia e rimosso.
# Es: body 10pt, soglia 0.85 → tutto sotto 8.5pt viene scartato.
SMALL_TEXT_RATIO = 0.85

# Margini per header/footer detection (percentuale dell'altezza pagina)
HEADER_MARGIN_RATIO = 0.08   # top 8% della pagina
FOOTER_MARGIN_RATIO = 0.08   # bottom 8% della pagina

# Pattern per riconoscere didascalie di figure/tabelle (multilingua)
CAPTION_PATTERNS = [
    # Italiano
    r"^(?:Fig(?:ura)?|Tabella|Tab|Tav(?:ola)?|Grafico|Immagine|Illustrazione|Foto)"
    r"\.?\s*\d+",
    # Inglese
    r"^(?:Fig(?:ure)?|Table|Tab|Chart|Graph|Image|Plate|Photo|Illustration)"
    r"\.?\s*\d+",
    # Francese
    r"^(?:Fig(?:ure)?|Tableau|Tab|Graphique|Image|Planche|Photo|Illustration)"
    r"\.?\s*\d+",
    # Spagnolo
    r"^(?:Fig(?:ura)?|Tabla|Tab|Gráfico|Imagen|Lámina|Foto|Ilustración)"
    r"\.?\s*\d+",
    # Tedesco
    r"^(?:Abb(?:ildung)?|Tabelle|Tab|Grafik|Bild|Tafel|Foto)"
    r"\.?\s*\d+",
    # Cinese
    r"^(?:图|表|图表)\s*\d+",
    # Generico: "Source:" / "Fonte:" a inizio riga
    r"^(?:Source|Fonte|Fuente|Quelle)\s*:",
]
_caption_re = re.compile("|".join(CAPTION_PATTERNS), re.IGNORECASE | re.MULTILINE)

# Titoli di sezioni non-contenuto da escludere (stesso approccio di epub_to_tts)
NON_CONTENT_TITLES = {
    # Indice
    "indice", "indice generale", "indice dei contenuti", "indice analitico",
    "sommario", "table of contents", "contents", "toc",
    "table des matières", "sommaire", "índice", "índice general",
    "inhaltsverzeichnis", "inhalt", "目录",
    # Copyright / Colophon
    "copyright", "colophon", "note legali", "informazioni legali",
    "legal notice", "mentions légales", "aviso legal", "impressum",
    # Copertina
    "frontespizio", "title page", "cover", "copertina",
    "half title", "halftitle",
    # Bibliografia
    "bibliografia", "bibliography", "bibliographie", "bibliografía",
    "riferimenti bibliografici", "references", "riferimenti",
    "works cited", "fonti", "sources", "letture consigliate",
    "further reading", "suggested reading",
    # Note
    "note", "notes", "note al testo", "note a piè di pagina",
    "note finali", "endnotes", "footnotes", "anmerkungen",
    # Glossario
    "glossario", "glossary", "glossaire", "glosario", "glossar",
    # Indice analitico
    "indice analitico", "indice dei nomi", "indice dei luoghi",
    "index", "name index", "subject index",
    # Informazioni autore
    "about the author", "sull'autore", "l'autore", "l'autrice",
    "biography", "biografia",
    # Ringraziamenti (opzionale — li teniamo come non-contenuto)
    "ringraziamenti", "acknowledgements", "acknowledgments",
    "remerciements", "agradecimientos", "danksagung",
    # Appendice
    "appendice", "appendix", "annexe", "apéndice", "anhang",
    # Errata / Crediti
    "errata", "credits", "crediti",
}

# Pattern per numeri di pagina isolati (righe con solo un numero)
PAGE_NUMBER_RE = re.compile(r"^\s*[-—–]?\s*\d{1,4}\s*[-—–]?\s*$")

# Pattern per header/footer ripetuti (rilevati statisticamente)
MIN_REPEAT_FOR_HEADER = 3  # minimo ripetizioni per considerare una riga header/footer


# ═══════════════════════════════════════════════════════════════════
# ESTRAZIONE TESTO DA PDF
# ═══════════════════════════════════════════════════════════════════

def _detect_body_font_size(doc: fitz.Document, sample_pages: int = 10) -> float:
    """Rileva il font size predominante nel documento (il "body text").

    Campiona le prime N pagine e trova la dimensione di font più frequente.
    """
    size_counter = Counter()
    pages_to_check = min(len(doc), sample_pages)

    for page_num in range(pages_to_check):
        page = doc[page_num]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block["type"] != 0:  # solo testo, no immagini
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if len(text) > 5:  # ignora frammenti troppo corti
                        size = round(span.get("size", 0), 1)
                        # Peso proporzionale alla lunghezza del testo
                        size_counter[size] += len(text)

    if not size_counter:
        return 10.0  # fallback standard

    return size_counter.most_common(1)[0][0]


def _detect_repeated_headers_footers(doc: fitz.Document, sample_pages: int = 20) -> set:
    """Rileva testi che si ripetono identici in cima/fondo di molte pagine.

    Restituisce un set di stringhe normalizzate da escludere.
    """
    header_candidates = Counter()
    footer_candidates = Counter()
    pages_to_check = min(len(doc), sample_pages)

    for page_num in range(pages_to_check):
        page = doc[page_num]
        page_height = page.rect.height
        header_y = page_height * HEADER_MARGIN_RATIO
        footer_y = page_height * (1 - FOOTER_MARGIN_RATIO)

        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block["type"] != 0:
                continue
            bbox = block["bbox"]  # (x0, y0, x1, y1)
            text = ""
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text += span.get("text", "")
            text = text.strip()
            if not text or len(text) > 150:
                continue

            # Normalizza per confronto
            normalized = re.sub(r"\d+", "N", text).strip()
            if len(normalized) < 3:
                continue

            if bbox[1] < header_y:
                header_candidates[normalized] += 1
            elif bbox[3] > footer_y:
                footer_candidates[normalized] += 1

    # Stringhe che compaiono in almeno MIN_REPEAT_FOR_HEADER pagine
    repeated = set()
    for text, count in header_candidates.items():
        if count >= MIN_REPEAT_FOR_HEADER:
            repeated.add(text)
    for text, count in footer_candidates.items():
        if count >= MIN_REPEAT_FOR_HEADER:
            repeated.add(text)

    return repeated


def _get_pdf_outline(doc: fitz.Document) -> list:
    """Estrae l'outline (bookmarks/segnalibri) dal PDF.

    Restituisce lista di (level, title, page_number).
    """
    outline = []
    try:
        toc = doc.get_toc(simple=True)  # [(level, title, page), ...]
        for level, title, page in toc:
            title = title.strip()
            if title and page >= 1:
                outline.append((level, title, page - 1))  # 0-based
    except Exception:
        pass
    return outline


def _extract_page_text_filtered(page: fitz.Page, body_font_size: float,
                                 repeated_headers: set) -> str:
    """Estrae il testo di una singola pagina, filtrando:
    - Testo con font troppo piccolo (note, didascalie)
    - Header/footer ripetuti
    - Numeri di pagina isolati

    Restituisce il testo pulito della pagina.
    """
    page_height = page.rect.height
    header_y = page_height * HEADER_MARGIN_RATIO
    footer_y = page_height * (1 - FOOTER_MARGIN_RATIO)
    small_threshold = body_font_size * SMALL_TEXT_RATIO

    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

    # Ordina i blocchi per posizione verticale (top-to-bottom reading order)
    text_blocks = [b for b in blocks if b["type"] == 0]
    text_blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))

    paragraphs = []

    for block in text_blocks:
        bbox = block["bbox"]
        block_text_parts = []
        is_small = True  # Assumi piccolo fino a prova contraria

        for line in block.get("lines", []):
            line_parts = []
            for span in line.get("spans", []):
                text = span.get("text", "")
                size = span.get("size", 0)
                flags = span.get("flags", 0)

                # Flag bit 0 = superscript in PyMuPDF
                if flags & 1:
                    continue  # Salta numeri in apice (riferimenti a note)

                if size >= small_threshold:
                    is_small = False

                line_parts.append(text)

            line_text = "".join(line_parts).strip()
            if line_text:
                block_text_parts.append(line_text)

        block_text = " ".join(block_text_parts).strip()
        if not block_text:
            continue

        # ── Filtro: testo troppo piccolo (note a piè, didascalie piccole) ──
        if is_small and len(block_text) < 500:
            continue

        # ── Filtro: header/footer ripetuti ──
        normalized = re.sub(r"\d+", "N", block_text).strip()
        if normalized in repeated_headers:
            continue

        # ── Filtro: posizione header/footer con testo corto ──
        if len(block_text) < 80:
            if bbox[1] < header_y or bbox[3] > footer_y:
                # Probabilmente header o footer
                continue

        # ── Filtro: numeri di pagina isolati ──
        if PAGE_NUMBER_RE.match(block_text):
            continue

        paragraphs.append(block_text)

    return "\n\n".join(paragraphs)


def _clean_pdf_text(text: str) -> str:
    """Pulizia specifica per testo estratto da PDF, prima della pulizia TTS generica.

    Rimuove:
    - Didascalie di figure e tabelle
    - Testo tra parentesi tonde e quadre
    - Note a piè di pagina (pattern numerici)
    - Sillabazione da a-capo (ri- unisce parole spezzate)
    - URL, ISBN, DOI
    - Riferimenti incrociati
    """
    if not text:
        return ""

    # 1. Rimuovi sillabazione da a-capo (parola spezzata con trattino a fine riga)
    #    es: "mate-\nmatica" → "matematica"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # 2. Rimuovi didascalie di figure/tabelle
    text = _caption_re.sub("", text)

    # 3. Rimuovi blocchi di note a piè di pagina
    #    Pattern: righe che iniziano con un numero seguito da punto/parentesi e testo breve
    #    (tipiche note a fondo pagina nei PDF)
    lines = text.split("\n")
    cleaned_lines = []
    in_footnote_block = False

    for line in lines:
        stripped = line.strip()

        # Rileva inizio blocco note (riga separatore + note numerate)
        if re.match(r"^[-_─—━]{3,}\s*$", stripped):
            in_footnote_block = True
            continue

        if in_footnote_block:
            # Le note continuano finché troviamo righe che iniziano con numero
            # o righe di continuazione (indentate o corte)
            if re.match(r"^\d{1,3}[\.\)]\s", stripped):
                continue  # nota numerata — salta
            elif stripped and not re.match(r"^[A-Z\u00C0-\u024F]", stripped):
                continue  # continuazione di nota (non inizia con maiuscola)
            else:
                in_footnote_block = False  # fine del blocco note

        # Rimuovi note inline tipo "1. Testo della nota" a fine pagina
        # (solo se la riga è corta, tipico delle note)
        if (re.match(r"^\d{1,3}[\.\)]\s+\S", stripped)
                and len(stripped) < 200
                and not re.match(r"^\d{1,3}\.\s+[A-Z].*[.!?]$", stripped)):
            # Distinzione: "1. Primo punto di un elenco reale" vs "1) nota"
            # Le note tipicamente non terminano con punto e sono brevi
            if re.match(r"^\d{1,3}\)", stripped):
                continue  # Formato "1) nota" — quasi certamente una nota

        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)

    # 4. Rimuovi testo tra parentesi tonde (note inline, riferimenti)
    #    Iterativo per gestire annidamento
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\([^()]*\)", "", text)

    # 5. Rimuovi testo tra parentesi quadre [note], [riferimenti]
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\[[^\[\]]*\]", "", text)

    # 6. Rimuovi URL
    text = re.sub(r"https?://\S+", "", text)

    # 7. Rimuovi ISBN
    text = re.sub(r"ISBN[\s:-]*[\d-]{10,}", "", text, flags=re.IGNORECASE)

    # 8. Rimuovi DOI
    text = re.sub(r"doi[\s:]*10\.\S+", "", text, flags=re.IGNORECASE)

    # 9. Rimuovi riferimenti a pagina/figura/tabella nel testo
    #    es: "(vedi pag. 45)", "(see Fig. 3)", "(cf. Tab. 2)"
    text = re.sub(r"\(?\b(?:vedi|see|voir|véase|siehe|cfr\.?|cf\.?)\s+"
                  r"(?:pag\.?|p\.?|fig\.?|tab\.?|cap\.?|ch\.?)\s*\.?\s*\d+[^)]*\)?",
                  "", text, flags=re.IGNORECASE)

    # 10. Rimuovi riferimenti bibliografici inline tipo "(Rossi, 2020)"
    text = re.sub(r"\(\s*[A-Z][a-záàèéìíòóùú]+(?:\s+(?:et\.?\s+al\.?|and|e|&)\s+"
                  r"[A-Z][a-záàèéìíòóùú]+)?,?\s*\d{4}[a-z]?\s*\)", "", text)

    # 11. Pulizia spazi risultanti
    text = re.sub(r"\s+([,;:.!?])", r"\1", text)  # spazio prima di punteggiatura
    text = re.sub(r"  +", " ", text)                # spazi multipli
    text = re.sub(r"\n{3,}", "\n\n", text)          # righe vuote eccessive

    return text.strip()


def _is_non_content_section(title: str, text: str) -> bool:
    """Determina se una sezione PDF è non-contenuto (indice, bibliografia, ecc.)."""
    # Match per parola intera (vedi epub_to_tts._title_is_non_content): evita
    # falsi positivi su token corti ("note" in "notevole", "toc" in
    # "autocrazia"). NON_CONTENT_TITLES include "目录" (sommario cinese).
    if _title_is_non_content(title, NON_CONTENT_TITLES):
        return True

    # Euristica content-based
    if not is_content_chapter(text, title):
        return True

    return False


# ═══════════════════════════════════════════════════════════════════
# CHAPTER DETECTION
# ═══════════════════════════════════════════════════════════════════

def _detect_chapters_from_outline(doc: fitz.Document, outline: list,
                                   body_font_size: float,
                                   repeated_headers: set) -> list:
    """Segmenta il PDF in capitoli usando l'outline (bookmarks).

    Restituisce lista di (title, text) tuple.
    """
    if not outline:
        return []

    # Usa solo il primo livello (o i primi due se pochi al primo)
    min_level = min(lvl for lvl, _, _ in outline)
    # Filtra: prendi livello min e (se < 5 entry) anche min+1
    top_entries = [(t, p) for lvl, t, p in outline if lvl == min_level]
    if len(top_entries) < 3:
        top_entries = [(t, p) for lvl, t, p in outline if lvl <= min_level + 1]

    if not top_entries:
        return []

    chapters = []
    total_pages = len(doc)

    for i, (title, start_page) in enumerate(top_entries):
        # Fine capitolo = inizio del prossimo (o fine documento)
        end_page = top_entries[i + 1][1] if i + 1 < len(top_entries) else total_pages

        # Estrai testo delle pagine del capitolo
        chapter_text_parts = []
        for page_num in range(start_page, min(end_page, total_pages)):
            page = doc[page_num]
            page_text = _extract_page_text_filtered(page, body_font_size, repeated_headers)
            if page_text:
                chapter_text_parts.append(page_text)

        chapter_text = "\n\n".join(chapter_text_parts)
        if chapter_text.strip():
            chapters.append((title, chapter_text))

    return chapters


def _detect_chapters_from_headings(doc: fitz.Document, body_font_size: float,
                                    repeated_headers: set) -> list:
    """Fallback: rileva capitoli dal font size (titoli = font più grande del body).

    Cerca righe con font significativamente più grande del body text come
    delimitatori di capitolo.
    """
    heading_threshold = body_font_size * 1.2  # 20% più grande del body
    all_text_parts = []  # (page_num, text, is_heading, heading_text)

    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        text_blocks = [b for b in blocks if b["type"] == 0]
        text_blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))

        for block in text_blocks:
            block_parts = []
            max_size = 0

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    size = span.get("size", 0)
                    flags = span.get("flags", 0)
                    if flags & 1:  # superscript
                        continue
                    block_parts.append(text)
                    if size > max_size:
                        max_size = size

            block_text = " ".join(block_parts).strip()
            if not block_text:
                continue

            # Un heading candidato: font grande, testo breve, possibilmente bold
            is_heading = (
                max_size >= heading_threshold
                and len(block_text) < 150
                and len(block_text.split()) < 20
            )

            all_text_parts.append((page_num, block_text, is_heading, max_size))

    if not all_text_parts:
        return []

    # Trova gli heading e segmenta
    heading_indices = [i for i, (_, _, is_h, _) in enumerate(all_text_parts) if is_h]

    if not heading_indices:
        return []

    chapters = []
    for idx, h_idx in enumerate(heading_indices):
        title = all_text_parts[h_idx][1]
        # Raccogli testo fino al prossimo heading
        end_idx = heading_indices[idx + 1] if idx + 1 < len(heading_indices) else len(all_text_parts)
        content_parts = []
        for j in range(h_idx + 1, end_idx):
            _, text, _, _ = all_text_parts[j]
            content_parts.append(text)
        chapter_text = "\n\n".join(content_parts)
        if chapter_text.strip():
            chapters.append((title, chapter_text))

    return chapters


def _detect_page_number_offset(doc: fitz.Document, body_font_size: float) -> int:
    """Rileva l'offset tra i numeri di pagina stampati e gli indici PDF (0-based).

    Molti libri hanno pagine iniziali (copertina, colophon, indice) che spostano
    la numerazione. Es: pagina stampata "11" potrebbe essere PDF page index 11
    (offset 0) o 12 (offset 1), ecc.

    Controlla le prime 30 pagine cercando numeri di pagina isolati in font piccolo
    e confronta con l'indice PDF.

    Restituisce l'offset: pdf_page_0based = printed_page + offset - 1
    """
    for page_idx in range(min(30, len(doc))):
        page = doc[page_idx]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

        for block in blocks:
            if block["type"] != 0:
                continue
            # Cerca blocchi con solo un numero (tipico page number)
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    size = span.get("size", 0)
                    # Numero di pagina: font piccolo, testo è solo un numero
                    if (size < body_font_size * 0.95
                            and text.isdigit()
                            and 1 <= int(text) <= 999):
                        printed_num = int(text)
                        # offset = page_idx - (printed_num - 1)
                        # perché: pdf_page_0based = printed_page - 1 + offset
                        offset = page_idx - (printed_num - 1)
                        if 0 <= offset <= 10:  # offset ragionevole
                            return offset

    return 0  # nessun offset rilevato


def _detect_chapters_from_visual_toc(doc: fitz.Document, body_font_size: float,
                                      repeated_headers: set) -> list:
    """Strategia 2b: rileva capitoli dalla pagina "Indice" visuale del PDF.

    Molti libri PDF senza bookmarks hanno comunque una pagina "Indice" o
    "Table of Contents" con la lista dei capitoli e i numeri di pagina.
    Questa funzione cerca tali pagine e ne estrae la struttura.

    Pattern riconosciuti:
    - Righe alternate: titolo (con tab finale) + numero di pagina
    - Righe con "..." o tab seguiti da numero di pagina
    - Righe "Titolo   123" con spazi/tab/puntini come separatore

    Restituisce lista di (title, text) tuple.
    """
    # Nomi tipici per la pagina indice (multilingua)
    toc_page_titles = {
        "indice", "indice generale", "indice dei contenuti",
        "sommario", "table of contents", "contents", "toc",
        "table des matières", "sommaire",
        "índice", "índice general", "contenido",
        "inhaltsverzeichnis", "inhalt",
        "目录",
    }

    # Cerca la pagina Indice nelle prime 15 pagine
    toc_page_idx = -1
    toc_pages = []

    for page_idx in range(min(15, len(doc))):
        page = doc[page_idx]
        text = page.get_text("text").strip()
        if not text:
            continue

        first_line = text.split("\n")[0].strip().lower()
        # La prima riga della pagina è il titolo dell'indice
        if first_line in toc_page_titles:
            toc_page_idx = page_idx
            toc_pages.append(page_idx)
            # L'indice potrebbe estendersi su più pagine consecutive
            for next_pg in range(page_idx + 1, min(page_idx + 4, len(doc))):
                next_text = doc[next_pg].get_text("text").strip()
                # Se la pagina successiva continua con lo stesso pattern
                # (righe con numeri, niente titolo nuovo)
                if next_text and not next_text.split("\n")[0].strip().lower() in toc_page_titles:
                    lines = next_text.split("\n")
                    # Verifica che abbia il pattern TOC (righe con numeri a fine riga)
                    has_numbers = sum(1 for l in lines
                                     if l.strip() and re.match(r"^\d{1,4}$", l.strip()))
                    if has_numbers >= 2:
                        toc_pages.append(next_pg)
                    else:
                        break
            break

    if toc_page_idx < 0:
        return []

    # Estrai le righe dalle pagine TOC
    toc_lines = []
    for pg_idx in toc_pages:
        page = doc[pg_idx]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block["type"] != 0:
                continue
            for line in block.get("lines", []):
                line_text = ""
                for span in line.get("spans", []):
                    line_text += span.get("text", "")
                line_text = line_text.strip()
                if line_text:
                    toc_lines.append(line_text)

    if not toc_lines:
        return []

    # Parsing delle entry TOC
    # Pattern 1: righe alternate "Titolo\t" + "123"
    # Pattern 2: righe "Titolo ... 123" o "Titolo\t123"
    entries = []  # (title, printed_page_num)

    i = 0
    # Salta il titolo "Indice"
    if toc_lines and toc_lines[0].lower().strip() in toc_page_titles:
        i = 1

    while i < len(toc_lines):
        line = toc_lines[i]

        # Pattern 1: la riga corrente è un titolo (termina con tab o non è un numero),
        # e la riga successiva è un numero di pagina
        if (i + 1 < len(toc_lines)
                and re.match(r"^\d{1,4}$", toc_lines[i + 1].strip())
                and not re.match(r"^\d{1,4}$", line.strip())):
            title = line.rstrip("\t .")
            page_num = int(toc_lines[i + 1].strip())
            if title and 1 <= page_num <= 9999:
                entries.append((title, page_num))
            i += 2
            continue

        # Pattern 2: "Titolo ... 123" o "Titolo\t\t123" sulla stessa riga
        m = re.match(r"^(.+?)[\s.·…\t]{3,}(\d{1,4})\s*$", line)
        if m:
            title = m.group(1).strip()
            page_num = int(m.group(2))
            if title and 1 <= page_num <= 9999:
                entries.append((title, page_num))
            i += 1
            continue

        i += 1

    if len(entries) < 2:
        return []

    # Calcola l'offset tra pagine stampate e indici PDF
    page_offset = _detect_page_number_offset(doc, body_font_size)

    print(f"[pdf] Indice visuale trovato a pagina {toc_page_idx + 1}, "
          f"{len(entries)} voci, offset pagina: {page_offset}")

    # Costruisci i capitoli usando le entry TOC
    chapters = []
    total_pages = len(doc)

    for i, (title, printed_page) in enumerate(entries):
        # Converti da pagina stampata a indice PDF (0-based)
        start_page = printed_page - 1 + page_offset
        if start_page < 0 or start_page >= total_pages:
            continue

        # Fine capitolo = inizio del prossimo (o fine documento)
        if i + 1 < len(entries):
            end_page = entries[i + 1][1] - 1 + page_offset
            end_page = min(end_page, total_pages)
        else:
            end_page = total_pages

        # Estrai testo delle pagine del capitolo
        chapter_text_parts = []
        for page_num in range(start_page, end_page):
            page = doc[page_num]
            page_text = _extract_page_text_filtered(page, body_font_size, repeated_headers)
            if page_text:
                chapter_text_parts.append(page_text)

        chapter_text = "\n\n".join(chapter_text_parts)
        if chapter_text.strip():
            chapters.append((title, chapter_text))

    return chapters


# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT PRINCIPALE
# ═══════════════════════════════════════════════════════════════════

def _build_chapters_from_raw(raw_chapters: list, pdf_path: str) -> list:
    """Pulisce e filtra i capitoli grezzi, restituendo una lista di Chapter.

    Applica pulizia PDF, pulizia TTS e filtra le sezioni non-contenuto.
    """
    chapters = []
    chapter_index = 0
    for title, raw_text in raw_chapters:
        # Pulizia specifica PDF
        cleaned = _clean_pdf_text(raw_text)

        # Pulizia generica TTS (condivisa con epub_to_tts)
        cleaned = clean_text_for_tts(cleaned)

        # Filtro contenuto
        if _is_non_content_section(title, cleaned):
            continue

        chapter_index += 1
        chapter = Chapter(
            index=chapter_index,
            title=title.strip(),
            text=cleaned.strip(),
            source_file=os.path.basename(pdf_path),
        )
        chapters.append(chapter)

    return chapters


def _extract_full_text(doc: fitz.Document, body_font_size: float,
                       repeated_headers: set) -> str:
    """Estrae tutto il testo del documento, pagina per pagina, con filtri base."""
    all_text_parts = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        page_text = _extract_page_text_filtered(page, body_font_size, repeated_headers)
        if page_text:
            all_text_parts.append(page_text)
    return "\n\n".join(all_text_parts)


def parse_pdf(pdf_path: str) -> BookInfo:
    """Parsa un file PDF ed estrae capitoli ottimizzati per TTS.

    Restituisce un oggetto BookInfo compatibile con epub_to_tts.py.

    Strategia di segmentazione (in ordine di priorità):
    1. Outline/bookmarks del PDF (se presenti)
    2. Rilevamento heading per font size
    3. Indice visuale (pagina "Indice" / "Contents" nel PDF)
    4. Fallback: intero documento come singolo capitolo

    Se una strategia produce capitoli ma tutti vengono filtrati come
    non-contenuto, si passa alla strategia successiva. Se anche il
    fallback finale viene filtrato, si forza l'inclusione dell'intero
    testo come singolo capitolo (recovery di ultima istanza).
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"File non trovato: {pdf_path}")

    doc = fitz.open(pdf_path)

    if doc.page_count == 0:
        raise ValueError("Il PDF è vuoto (0 pagine)")

    # ── Metadati ──
    info = BookInfo()
    metadata = doc.metadata or {}
    info.title = (metadata.get("title") or "").strip() or Path(pdf_path).stem
    info.author = (metadata.get("author") or "").strip() or ""
    # PyMuPDF non ha un campo "language" standard; proviamo dal metadata
    info.language = (metadata.get("language") or "").strip()
    info.publisher = (metadata.get("producer") or metadata.get("creator") or "").strip()

    # ── Analisi del documento ──
    body_font_size = _detect_body_font_size(doc)
    repeated_headers = _detect_repeated_headers_footers(doc)
    outline = _get_pdf_outline(doc)

    print(f"[pdf] Pagine: {doc.page_count}, font body: {body_font_size:.1f}pt, "
          f"outline: {len(outline)} voci, "
          f"header/footer ripetuti: {len(repeated_headers)}")

    # ── Segmentazione in capitoli ──
    # Ogni strategia produce raw_chapters → pulizia → filtro.
    # Se dopo il filtro restano 0 capitoli, si prova la strategia successiva.

    strategies = []

    # Strategia 1: outline/bookmarks
    if outline:
        raw = _detect_chapters_from_outline(doc, outline, body_font_size, repeated_headers)
        if raw:
            strategies.append(("outline", raw))

    # Strategia 2: heading detection per font size
    raw = _detect_chapters_from_headings(doc, body_font_size, repeated_headers)
    if raw:
        strategies.append(("heading font-size", raw))

    # Strategia 3: indice visuale
    raw = _detect_chapters_from_visual_toc(doc, body_font_size, repeated_headers)
    if raw:
        strategies.append(("indice visuale", raw))

    # Strategia 4: fallback — tutto il documento come singolo capitolo
    full_text = _extract_full_text(doc, body_font_size, repeated_headers)
    if full_text.strip():
        strategies.append(("documento singolo", [(info.title, full_text)]))

    doc.close()

    # ── Prova ogni strategia in ordine ──
    for strategy_name, raw_chapters in strategies:
        chapters = _build_chapters_from_raw(raw_chapters, pdf_path)
        if chapters:
            print(f"[pdf] Capitoli da {strategy_name}: {len(chapters)}")
            info.chapters = chapters
            break

    # ── Recovery di ultima istanza ──
    # Se tutte le strategie hanno prodotto 0 capitoli dopo il filtro,
    # ma c'è testo nel documento, forza l'inclusione senza filtri.
    if not info.chapters and full_text.strip():
        print("[pdf] Recovery: tutti i capitoli filtrati, forza inclusione testo completo")
        cleaned = _clean_pdf_text(full_text)
        cleaned = clean_text_for_tts(cleaned)
        if cleaned.strip() and len(cleaned.split()) >= 30:
            info.chapters.append(Chapter(
                index=1,
                title=info.title,
                text=cleaned.strip(),
                source_file=os.path.basename(pdf_path),
            ))

    # ── Totali ──
    info.total_words = sum(c.word_count for c in info.chapters)
    info.total_chars = sum(c.char_count for c in info.chapters)
    info.estimated_duration_minutes = info.total_words / 150  # ~150 parole/min

    if not info.chapters:
        raise ValueError("Nessun contenuto testuale trovato nel PDF")

    return info


# ═══════════════════════════════════════════════════════════════════
# CLI (standalone usage)
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Converte un PDF in testo ottimizzato per TTS / audiolibro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  %(prog)s libro.pdf                  # Mostra info ed estrae capitoli
  %(prog)s libro.pdf --info           # Solo info sul libro
  %(prog)s libro.pdf -o output_dir    # Salva capitoli in cartella
        """
    )

    parser.add_argument("pdf", help="File PDF di input")
    parser.add_argument("-o", "--output", help="Cartella di output per i capitoli .txt")
    parser.add_argument("--info", action="store_true",
                        help="Mostra solo informazioni sul libro senza produrre output")

    args = parser.parse_args()

    if not os.path.exists(args.pdf):
        print(f"ERRORE: File non trovato: {args.pdf}", file=sys.stderr)
        sys.exit(1)

    print(f"Analisi PDF: {args.pdf}...")
    info = parse_pdf(args.pdf)

    # Stampa info
    print(f"\n{'═' * 60}")
    print(f"  {info.title}")
    if info.author:
        print(f"  di {info.author}")
    print(f"{'═' * 60}")
    print(f"  Capitoli:   {len(info.chapters)}")
    print(f"  Parole:     {info.total_words:,}")
    print(f"  Caratteri:  {info.total_chars:,}")
    print(f"  Durata ~    {info.estimated_duration_minutes:.0f} minuti")
    print(f"{'─' * 60}")
    for ch in info.chapters:
        est = ch.word_count / 150
        print(f"  {ch.index:3d}. {ch.title[:45]:<45s} {ch.word_count:>6,} parole  ~{est:.0f} min")
    print(f"{'═' * 60}\n")

    if args.info:
        return

    # Output
    if args.output:
        out_dir = Path(args.output)
        out_dir.mkdir(parents=True, exist_ok=True)
        for ch in info.chapters:
            safe_title = re.sub(r"[^\w\s-]", "", ch.title)
            safe_title = re.sub(r"\s+", "_", safe_title.strip())[:50]
            filename = f"{ch.index:03d}_{safe_title}.txt"
            filepath = out_dir / filename
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"{ch.title}\n\n{ch.text}\n")
            print(f"  ✓ {filename}")
        print(f"\n✓ {len(info.chapters)} capitoli salvati in {out_dir}/")
    else:
        print("Usa -o CARTELLA per salvare i capitoli come file .txt")


if __name__ == "__main__":
    main()
