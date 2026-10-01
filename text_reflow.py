"""text_reflow.py — Ricomposizione di righe e paragrafi spezzati, comune a PDF, EPUB e TXT.

Modulo foglia: non importa nulla dal progetto.

Il testo che arriva al TTS tratta ogni "\\n\\n" come fine paragrafo e, se il
paragrafo è corto e senza punteggiatura finale, ci aggiunge un punto
(tts_split._ensure_heading_pause): un a-capo tipografico scambiato per
paragrafo diventa una pausa a metà frase e una parola sillabata ("zurück-" /
"kehren") viene letta spezzata. Succede nei PDF (una riga visiva per
paragrafo) e negli EPUB/TXT ricavati da PDF (un <p> o una riga vuota per ogni
riga stampata). Qui stanno le regole testuali condivise; quelle geometriche
(rientri, margine destro) restano in pdf_to_tts.

Confronto su 254 EPUB di produzione (01/10/2026): distribuzione bimodale,
204 libri sotto l'1% di paragrafi spezzati a metà frase, 31 oltre il 20%
(conversioni da PDF). Il reflow di un libro intero scatta solo sopra soglia,
così versi, dialoghi e titoli dei libri ben composti non vengono toccati.
"""

import re

# Fine frase (o chiusura di citazione/parentesi) in coda alla riga.
TERMINAL_RE = re.compile(r"[.!?…:;\"'»«“”’)\]。！？」』）]\s*$")
# Sotto questa lunghezza una riga seguita da maiuscola è un sottotitolo.
SOFT_BREAK_MIN_LINE = 40
# Trattino sospeso ("Hin- und Rückfahrt", "pre- e post-"): non è sillabazione.
SUSPENDED_HYPHEN_NEXT = frozenset({
    "und", "oder", "bis", "sowie", "noch", "als", "wie",
    "and", "or", "to", "nor",
    "e", "ed", "o", "od", "y", "u", "et", "ou", "ni",
})

# Reflow di un libro intero (EPUB/TXT): quota minima di confini di paragrafo
# a metà frase, numero minimo di paragrafi per giudicare, lunghezza mediana
# minima del paragrafo spezzato (i versi sono righe corte, le righe di una
# pagina convertita no).
BOOK_REFLOW_MIN_RATIO = 0.10
BOOK_REFLOW_MIN_PARAGRAPHS = 50
BOOK_REFLOW_MIN_MEDIAN_LEN = SOFT_BREAK_MIN_LINE

_PARA_SPLIT_RE = re.compile(r"\n[ \t]*\n\s*")
_HYPHEN_BREAK_RE = re.compile(r"([^\W\d_])-(\n+)(\w+)")


def strip_soft_hyphens(text: str) -> str:
    """Toglie il trattino morbido U+00AD: invisibile a schermo, ma spezza la parola al TTS."""
    return text.replace("\u00ad", "")


def join_lines(prev: str, nxt: str) -> str:
    """Unisce due righe della stessa frase, ricomponendo la sillabazione.

    "zurück-" + "kehren" → "zurückkehren"; "Ost-" + "Berlin" → "Ost-Berlin"
    (trattino di composto davanti a maiuscola); "Hin-" + "und" → "Hin- und"
    (trattino sospeso); "parola –" + "altra" → spazio.
    """
    if re.search(r"[^\W\d_]-$", prev):
        first = nxt.split(" ", 1)[0].strip(",;.").lower()
        if first in SUSPENDED_HYPHEN_NEXT:
            return prev + " " + nxt
        if nxt[:1].islower():
            return prev[:-1] + nxt
        return prev + nxt
    return prev + " " + nxt


def lines_to_paragraphs(items: list) -> str:
    """Ricompone righe in paragrafi separati da "\\n\\n".

    `items`: lista di (brk, testo) dove `brk` è il tipo di confine che precede
    la riga: None (stessa sequenza di righe), "hard" (fine paragrafo certa),
    "soft" (nuovo blocco o nuova pagina: fine paragrafo solo se la riga
    precedente chiude la frase o è corta come un sottotitolo).
    """
    paragraphs = []
    cur = ""
    last_line = ""
    for brk, text in items:
        text = text.strip()
        if not text:
            continue
        if not cur:
            cur = text
        elif brk == "hard":
            paragraphs.append(cur)
            cur = text
        elif brk == "soft" and (
                TERMINAL_RE.search(last_line)
                or (len(last_line) < SOFT_BREAK_MIN_LINE
                    and not text[:1].islower())):
            paragraphs.append(cur)
            cur = text
        else:
            cur = join_lines(cur, text)
        last_line = text
    if cur:
        paragraphs.append(cur)
    return "\n\n".join(paragraphs)


def dehyphenate_breaks(text: str) -> str:
    """Ricompone le parole sillabate a cavallo di un a-capo.

    Con un solo "\\n" vale la regola di join_lines; con una riga vuota in
    mezzo ("zurück-\\n\\nkehren", cambio pagina o paragrafo spurio) si unisce
    solo davanti a minuscola: davanti a maiuscola è un vero paragrafo.
    """
    def _fix(m):
        letter, nl, word = m.group(1), m.group(2), m.group(3)
        if word.lower() in SUSPENDED_HYPHEN_NEXT:
            return f"{letter}- {word}"
        if word[:1].islower():
            return letter + word
        if len(nl) == 1:
            return f"{letter}-{word}"
        return m.group(0)
    return _HYPHEN_BREAK_RE.sub(_fix, text)


def is_mid_sentence_break(prev: str, nxt: str) -> bool:
    """Confine di paragrafo che cade a metà frase."""
    return not TERMINAL_RE.search(prev) and nxt[:1].islower()


def _paragraphs(text: str) -> list:
    return [p.strip() for p in _PARA_SPLIT_RE.split(text) if p.strip()]


def book_needs_reflow(texts: list) -> bool:
    """Il libro ha paragrafi spezzati a metà frase in modo sistematico?"""
    mids = []
    total = 0
    for t in texts:
        paras = _paragraphs(t)
        total += len(paras)
        for a, b in zip(paras, paras[1:]):
            if is_mid_sentence_break(a, b):
                mids.append(len(a))
    if total < BOOK_REFLOW_MIN_PARAGRAPHS or len(mids) < BOOK_REFLOW_MIN_RATIO * total:
        return False
    mids.sort()
    return mids[len(mids) // 2] >= BOOK_REFLOW_MIN_MEDIAN_LEN


def reflow_paragraphs(text: str) -> str:
    """Unisce i paragrafi spezzati a metà frase, ricomponendo la sillabazione."""
    out = []
    for p in _paragraphs(text):
        if out and is_mid_sentence_break(out[-1], p):
            out[-1] = join_lines(out[-1], p)
        else:
            out.append(p)
    return "\n\n".join(out)


def reflow_book(texts: list):
    """Testi dei capitoli ricomposti, o None se il libro non ne ha bisogno."""
    if not book_needs_reflow(texts):
        return None
    return [reflow_paragraphs(t) for t in texts]
