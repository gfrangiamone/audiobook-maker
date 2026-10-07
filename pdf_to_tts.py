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

# Regole testuali di ricomposizione righe/paragrafi, comuni a EPUB e TXT.
from text_reflow import (
    TERMINAL_RE as _PDF_LINE_TERMINAL_RE,
    dehyphenate_breaks,
    join_lines as _join_pdf_line,
    lines_to_paragraphs as _lines_to_paragraphs,
)

# Strutture dati e funzioni di pulizia condivise con il parser EPUB
# (stessa interfaccia BookInfo/Chapter). epub_to_tts e' una dipendenza
# obbligatoria: nessun fallback locale (era una copia stantia).
from epub_to_tts import (
    BookInfo, Chapter, clean_text_for_tts, is_content_chapter,
    _title_is_non_content,
    is_chapter_marker_line as _is_chapter_marker_line,
)


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
    # Quarta di copertina / sinossi
    "quarta di copertina", "risvolto di copertina", "risvolto",
    "back cover", "quatrième de couverture", "quatrieme de couverture",
    "klappentext", "contraportada", "plot summary",
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

# Copertura minima di testo per accettare una strategia di riconoscimento titoli
# (outline, heading font-size, indice visuale). Se una di queste strategie cattura
# meno di questa frazione del testo complessivo estratto dal documento — cioè
# scarta più del 5% — la si considera inaffidabile (tipicamente un titolo non
# riconosciuto fa collassare intere sezioni in un unico capitolo, perdendo tutto
# il testo che le precede) e si passa alla strategia successiva.
MIN_TITLE_STRATEGY_COVERAGE = 0.95

# ── Rilevamento suddivisioni per pattern testuale ──
# Definito una sola volta in epub_to_tts (modulo base condiviso) per evitare
# divergenze fra parser PDF ed EPUB. Alias locale `_line_is_chapter_marker`
# mantenuto per compatibilità con il codice e i test esistenti.
_line_is_chapter_marker = _is_chapter_marker_line


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


# ── Ricomposizione righe → paragrafi ──
# Nel PDF ogni riga visiva è una "line" a sé: unirle con "\n\n" trasforma ogni
# a-capo tipografico in un paragrafo, e la sintesi si ferma a metà frase
# (incidente 30/09/2026, romanzo da Word: 10.087 paragrafi su 14.248 troncati
# a metà frase, pause brusche in tutto il libro). Le righe si uniscono con uno
# spazio; il paragrafo si chiude su una riga vuota (separatore tipico dei PDF
# da Word), su una riga corta o un rientro di prima riga (a-capo voluto: fine
# paragrafo, versi, elenchi) o su un confine di blocco/pagina che chiude
# davvero la frase.
#
# Riga corta = la prima parola della riga successiva ci sarebbe stata: chi
# ha composto il testo è andato a capo apposta (fine paragrafo, verso, voce
# di elenco, battuta di dialogo). Vale per il giustificato e per il testo a
# bandiera, dove una soglia fissa di spazio libero sbagliava in entrambi i
# sensi (confronto su 180 PDF di produzione, 01/10/2026). Il rientro di prima
# riga si misura dal margine sinistro del blocco, così due paragrafi di una
# riga sola, entrambi rientrati, restano separati.
_PDF_DIALOGUE_DASH_RE = re.compile(r"[-–—―]\s*\S")
_PDF_NEXT_WORD_FIT = 1.3        # margine sulla larghezza stimata della parola
_PDF_INDENT_MIN_RATIO = 0.025   # rientro di prima riga, frazione della colonna
_PDF_INDENT_MIN_PT = 6.0
_PDF_INDENT_MAX_RATIO = 0.20    # oltre: riga centrata o citazione, non rientro
_PDF_COLUMN_MIN_CHARS = 30      # righe usate per stimare la colonna
_PDF_SAME_EDGE_PT = 1.0         # margine destro "uguale" fra righe giustificate


def _visual_lines(lines: list) -> list:
    """Fonde le "line" PyMuPDF che stanno sulla stessa riga visiva.

    Nel testo giustificato con spaziatura larga PyMuPDF restituisce spesso una
    "line" per parola (stessa linea di base, x crescente): trattate come righe
    distinte diventavano un paragrafo per parola. Restituisce dict con
    `spans` (con uno span-spazio fra i pezzi fusi) e `bbox`.
    """
    out = []
    for line in lines:
        bbox = tuple(line.get("bbox", (0, 0, 0, 0)))
        spans = list(line.get("spans", []))
        if out:
            prev = out[-1]
            pb = prev["bbox"]
            if abs(pb[3] - bbox[3]) < 2 and bbox[0] >= pb[2] - 1:
                prev["spans"] = prev["spans"] + [{"text": " ", "size": 0, "flags": 0}] + spans
                prev["bbox"] = (pb[0], min(pb[1], bbox[1]), max(pb[2], bbox[2]), max(pb[3], bbox[3]))
                continue
        out.append({"spans": spans, "bbox": bbox})
    return out


def _page_text_column(text_blocks: list):
    """Stima (sinistra, destra) della colonna di testo della pagina.

    Usa solo le righe lunghe (corpo del testo). None se la pagina ne ha troppo
    poche: in quel caso la geometria non decide nulla.
    """
    xs0, xs1 = [], []
    for block in text_blocks:
        for vl in _visual_lines(block.get("lines", [])):
            text = "".join(s.get("text", "") for s in vl["spans"]).strip()
            if len(text) >= _PDF_COLUMN_MIN_CHARS:
                xs0.append(vl["bbox"][0])
                xs1.append(vl["bbox"][2])
    if len(xs0) < 3:
        return None
    left, right = min(xs0), max(xs1)
    if right - left <= 0:
        return None
    return left, right


def _vline_text(vl: dict) -> str:
    return "".join(sp.get("text", "") for sp in vl["spans"]
                   if not sp.get("flags", 0) & 1).strip()


def _block_geometry_breaks(vlines: list, page_column) -> list:
    """Per ogni riga visiva del blocco: "hard" se la geometria dice che lì
    comincia un paragrafo (rientro di prima riga, o riga precedente lasciata
    corta pur avendo spazio per la parola seguente), altrimenti None.

    Il riferimento è la colonna del blocco quando ha abbastanza righe lunghe
    (citazioni e versi rientrati fanno blocco a sé), altrimenti quella della
    pagina, col margine destro ristretto alla riga più larga del blocco.
    Senza riferimento la geometria non decide nulla.
    """
    texts = [_vline_text(vl) for vl in vlines]
    out: list = [None] * len(vlines)
    longs = [vl["bbox"] for vl, t in zip(vlines, texts)
             if len(t) >= _PDF_COLUMN_MIN_CHARS]
    if len(longs) >= 3:
        left, right = min(b[0] for b in longs), max(b[2] for b in longs)
    elif page_column:
        left, right = page_column
        # Blocco in un riquadro più stretto della colonna (domande, elenchi
        # numerati, box): il margine destro è quello della sua riga più larga.
        widths = [vl["bbox"][2] for vl, t in zip(vlines, texts) if t]
        if len(widths) >= 2:
            right = min(right, max(widths))
    else:
        return out
    width = right - left
    if width <= 0:
        return out
    ind_min = max(_PDF_INDENT_MIN_PT, width * _PDF_INDENT_MIN_RATIO)

    def indented(bbox):
        return ind_min <= bbox[0] - left <= width * _PDF_INDENT_MAX_RATIO

    # Rientro sospeso (elenchi, bibliografie): quasi tutte le righe rientrano,
    # il rientro non segna l'inizio del paragrafo.
    cont = [vl["bbox"] for vl, t in zip(vlines[1:], texts[1:]) if t]
    use_indent = not cont or sum(indented(b) for b in cont) * 2 <= len(cont)

    prev = pprev = None  # indici delle ultime due righe non vuote
    for i, (vl, t) in enumerate(zip(vlines, texts)):
        if not t:
            continue
        if prev is not None:
            pb, pt = vlines[prev]["bbox"], texts[prev]
            # Giustificato che si restringe (testo attorno a una figura): la
            # riga "corta" finisce allo stesso x di una vicina, non è voluta.
            near = [vl] + ([vlines[pprev]] if pprev is not None else [])
            same_edge = any(abs(pb[2] - n["bbox"][2]) <= _PDF_SAME_EDGE_PT for n in near)
            if use_indent and indented(vl["bbox"]):
                out[i] = "hard"
            elif (_PDF_LINE_TERMINAL_RE.search(pt)
                  and _PDF_DIALOGUE_DASH_RE.match(t)):
                # Battuta di dialogo a inizio riga dopo una frase chiusa: nel
                # testo a bandiera la riga prima può essere piena.
                out[i] = "hard"
            elif not same_edge and not re.search(r"[^\W\d_][-\u00ad]$", pt):
                char_w = (pb[2] - pb[0]) / max(len(pt), 1)
                word = t.split(" ", 1)[0]
                if right - pb[2] > (len(word) + 1) * char_w * _PDF_NEXT_WORD_FIT:
                    out[i] = "hard"
        pprev, prev = prev, i
    return out


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
    column = _page_text_column(text_blocks)

    for block in text_blocks:
        bbox = block["bbox"]
        block_text_parts = []
        pending_brk = None
        is_small = True  # Assumi piccolo fino a prova contraria

        vlines = _visual_lines(block.get("lines", []))
        geo = _block_geometry_breaks(vlines, column)
        for li, line in enumerate(vlines):
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
                if geo[li]:
                    pending_brk = "hard"
                block_text_parts.append((pending_brk, line_text))
                pending_brk = None
            elif block_text_parts:
                pending_brk = "hard"  # riga vuota: separatore di paragrafo

        block_text = _lines_to_paragraphs(block_text_parts).strip()
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
    - Note a piè di pagina (pattern numerici)
    - Sillabazione da a-capo (ri- unisce parole spezzate)
    - URL, ISBN, DOI
    - Riferimenti incrociati
    """
    if not text:
        return ""

    # 1. Rimuovi sillabazione da a-capo (parola spezzata con trattino a fine riga)
    #    es: "mate-\nmatica" → "matematica"
    #    anche a cavallo di pagina/blocco ("zurück-\n\nkehren"): regola comune
    #    a EPUB e TXT, vedi text_reflow.dehyphenate_breaks.
    text = dehyphenate_breaks(text)

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

    # 4-5. Il testo tra parentesi tonde e quadre NON si tocca qui: come per
    #    EPUB e TXT lo decide l'opzione dell'utente (read_round_parens /
    #    read_square_brackets) in _strip_parenthetical. Le note bibliografiche
    #    ([12], [a], (see ...)) le toglie clean_text_for_tts, come per l'EPUB.

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


def _span_is_bold(span: dict) -> bool:
    """True se lo span è in grassetto (flag bold di PyMuPDF o nome del font)."""
    if span.get("flags", 0) & 16:  # bit 4 = bold in PyMuPDF
        return True
    font = span.get("font", "").lower()
    return any(k in font for k in ("bold", "black", "heavy"))


def _adaptive_heading_threshold(raw_lines: list, body_font_size: float) -> float:
    """Determina in modo adattivo la soglia di font-size per i titoli.

    Un multiplo fisso del body (es. 1.2×) fallisce quando i titoli sono solo
    di poco più grandi del corpo: caso reale osservato con body 11.8pt e titoli
    a 13.7pt (1.16×), sotto la soglia 1.2× → capitoli non riconosciuti. Qui si
    cerca il più piccolo livello di font *ricorrente* su righe brevi nettamente
    sopra il body e si pone la soglia a metà strada tra body e quel livello.

    `raw_lines` è una lista di (max_size, is_all_bold, line_text).
    """
    short_sizes = Counter()
    for max_size, _is_bold, text in raw_lines:
        if len(text) < 150 and len(text.split()) < 20:
            short_sizes[round(max_size, 1)] += 1

    recurring = sorted(
        s for s, c in short_sizes.items()
        if s >= body_font_size * 1.10 and c >= 2
    )
    if recurring:
        return (body_font_size + recurring[0]) / 2

    return body_font_size * 1.2  # fallback: nessun livello-titolo distinto


def _detect_chapters_from_headings(doc: fitz.Document, body_font_size: float,
                                    repeated_headers: set) -> list:
    """Fallback: rileva capitoli dallo stile del titolo (font size, grassetto o
    pattern testuale).

    Una riga è un titolo/delimitatore se soddisfa almeno uno di questi segnali:
      1. dimensione del font sopra la soglia adattiva (`_adaptive_heading_threshold`);
      2. riga interamente in grassetto (indizio utile quando il titolo ha la
         stessa dimensione del corpo, es. sezioni di coda "Anmerkungen");
      3. pattern testuale di marcatore di suddivisione (`_line_is_chapter_marker`:
         "Chapter 4", "Capitolo III", "Kapitel 5", "第2章"…), necessario quando il
         titolo è tipograficamente identico al corpo e l'unico segnale è il testo.

    Grassetto e pattern richiedono la riga più corta per non confondere enfasi o
    inizi di frase nel corpo del testo con un titolo.

    La rilevazione lavora a livello di **riga**, non di blocco: molti PDF
    raggruppano titolo e primo paragrafo nello stesso blocco (es. la riga
    "Part I" a 13.7pt seguita dal body a 11.8pt nello stesso block). Valutare
    il font a livello di blocco mascherava il titolo dietro la lunghezza del
    testo di corpo, facendo fallire il riconoscimento. Analizzando ogni riga
    singolarmente il titolo resta distinguibile anche se condivide il blocco.
    """
    # ── Pass unico: raccogli (max_size, is_all_bold, testo) per ogni riga ──
    raw_lines = []
    # Confine che precede ogni riga di raw_lines (vedi _lines_to_paragraphs):
    # serve a ricomporre i paragrafi invece di fare di ogni riga un paragrafo.
    line_breaks = []
    pending_brk = None

    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        text_blocks = [b for b in blocks if b["type"] == 0]
        text_blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
        column = _page_text_column(text_blocks)

        for block in text_blocks:
            if pending_brk is None:
                pending_brk = "soft"
            vlines = _visual_lines(block.get("lines", []))
            geo = _block_geometry_breaks(vlines, column)
            for li, line in enumerate(vlines):
                line_parts = []
                max_size = 0
                bold_spans = 0
                total_spans = 0
                for span in line.get("spans", []):
                    if span.get("flags", 0) & 1:  # superscript
                        continue
                    text = span.get("text", "")
                    line_parts.append(text)
                    # La dimensione considera anche gli span di soli spazi: molti
                    # PDF codificano l'altezza-riga del titolo in uno span-spazio
                    # a font grande accanto al testo visibile reso più piccolo
                    # (es. divisori di capitolo "XXXX" 11.5pt + " " 15.4pt). Senza
                    # includerli il titolo non verrebbe riconosciuto.
                    size = span.get("size", 0)
                    if size > max_size:
                        max_size = size
                    if not text.strip():
                        continue  # spazi: non contano per il grassetto
                    total_spans += 1
                    if _span_is_bold(span):
                        bold_spans += 1

                line_text = "".join(line_parts).strip()
                if not line_text:
                    pending_brk = "hard"  # riga vuota: separatore di paragrafo
                    continue

                is_all_bold = total_spans > 0 and bold_spans == total_spans
                raw_lines.append((max_size, is_all_bold, line_text))
                if geo[li]:
                    pending_brk = "hard"
                line_breaks.append(pending_brk)
                pending_brk = None

    if not raw_lines:
        return []

    heading_threshold = _adaptive_heading_threshold(raw_lines, body_font_size)

    # ── Classifica ogni riga come heading o contenuto ──
    lines_seq = []
    for max_size, is_all_bold, line_text in raw_lines:
        words = len(line_text.split())
        short = len(line_text) < 150 and words < 20
        by_size = short and max_size >= heading_threshold
        # Grassetto: vincoli più stretti (riga molto corta, dimensione >= body)
        # per evitare falsi positivi da enfasi in linea nel corpo del testo.
        by_bold = (
            is_all_bold
            and max_size >= body_font_size * 0.98
            and len(line_text) < 60
            and words <= 8
        )
        # Pattern testuale: cattura i marcatori anche a dimensione-corpo.
        by_pattern = _line_is_chapter_marker(line_text)
        lines_seq.append((by_size or by_bold or by_pattern, line_text))
    breaks_seq = line_breaks

    if not any(is_h for is_h, _ in lines_seq):
        return []

    n = len(lines_seq)
    chapters = []

    # Testo che precede il primo heading: preservato come capitolo iniziale
    # (senza titolo) per non perdere contenuto quando il documento inizia con
    # del testo prima del primo titolo riconosciuto.
    first_heading = next(i for i, (h, _) in enumerate(lines_seq) if h)
    if first_heading > 0:
        pre_text = _lines_to_paragraphs(
            [(breaks_seq[j], lines_seq[j][1]) for j in range(first_heading)])
        if pre_text.strip():
            chapters.append(("", pre_text))

    # Segmenta: righe-heading consecutive → un unico titolo, poi le righe di
    # contenuto fino al prossimo heading.
    i = first_heading
    while i < n:
        title_parts = []
        while i < n and lines_seq[i][0]:
            title_parts.append(lines_seq[i][1])
            i += 1
        title = " ".join(title_parts).strip()

        content_parts = []
        while i < n and not lines_seq[i][0]:
            content_parts.append((breaks_seq[i], lines_seq[i][1]))
            i += 1

        chapter_text = _lines_to_paragraphs(content_parts)
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
        # Fallback per capitoli senza titolo (es. testo che precede il primo
        # heading riconosciuto): etichetta generica in inglese.
        chapter_title = title.strip() or f"Chapter {chapter_index}"
        chapter = Chapter(
            index=chapter_index,
            title=chapter_title,
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
        raise FileNotFoundError(f"File not found: {pdf_path}")

    doc = fitz.open(pdf_path)

    if doc.page_count == 0:
        raise ValueError("PDF is empty (0 pages)")

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

    # Strategia 2: titoli per stile (font size / grassetto) o pattern testuale
    raw = _detect_chapters_from_headings(doc, body_font_size, repeated_headers)
    if raw:
        strategies.append(("titoli (font/grassetto/pattern)", raw))

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
    # `full_text` è il testo completo del documento (strategia "documento singolo")
    # e funge da riferimento per la guardia di copertura: una strategia di
    # riconoscimento titoli che ne cattura troppo poco sta perdendo contenuto.
    full_text_chars = len(full_text.strip())

    for strategy_name, raw_chapters in strategies:
        # Guardia di copertura: applicata solo alle strategie di riconoscimento
        # titoli, NON al fallback "documento singolo" (che È il testo completo).
        if strategy_name != "documento singolo" and full_text_chars > 0:
            captured = sum(len(t or "") for _, t in raw_chapters)
            coverage = captured / full_text_chars
            if coverage < MIN_TITLE_STRATEGY_COVERAGE:
                print(f"[pdf] Strategia '{strategy_name}' scarta "
                      f"{100 * (1 - coverage):.0f}% del testo "
                      f"(soglia max 5%): ignorata")
                continue

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
        # Caso tipico: PDF fatto di sole immagini (scansione o foto convertite).
        # Il codice "pdf_no_text" viene riconosciuto da /api/analyze e tradotto
        # nella lingua dell'utente: qui resta un fallback in inglese, mai in
        # italiano (un utente pakistano si e' visto un errore in italiano).
        raise ValueError("pdf_no_text: no extractable text found in the PDF "
                         "(image-only or scanned document)")

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
