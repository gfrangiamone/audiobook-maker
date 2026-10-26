"""text_reflow.py — Ricomposizione di righe e paragrafi spezzati, comune a PDF, EPUB e TXT.

Modulo foglia: dal progetto importa solo la foglia `env_utils`.

Da F1c (2026-10-10) ospita anche le regole di testo pre-TTS che stavano in
`tts_split` (parentesi, maiuscole urlate, pausa dopo heading, `prepare_tts_text`,
dedup del titolo, `_sanitize_tts_text`, `spoken_title_prefix`): `tts_split` le
riesporta con gli stessi nomi, i motori le importano da qui.

Il testo che arriva al TTS tratta ogni "\\n\\n" come fine paragrafo e, se il
paragrafo è corto e senza punteggiatura finale, ci aggiunge un punto
(_ensure_heading_pause, qui sotto): un a-capo tipografico scambiato per
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
import unicodedata

from env_utils import env_int

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


# ---------------------------------------------------------------------------
# Abbreviazioni (F1b, 2026-10-10; prima solo in epub_to_tts.clean_text_for_tts)
# ---------------------------------------------------------------------------

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

# Regole compilate una volta, dalla piu' lunga alla piu' corta (cosi' "op. cit."
# viene prima di "cit."), con confini di parola e senza distinzione di
# maiuscole: stesso risultato del ciclo storico di clean_text_for_tts.
_ABBR_RULES = [
    (re.compile(r"(?<!\w)" + re.escape(abbr) + r"(?!\w)", re.IGNORECASE), expansion)
    for abbr, expansion in sorted(ABBREVIATIONS.items(), key=lambda x: -len(x[0]))
]


def expand_abbreviations(text):
    """Espande le abbreviazioni di ABBREVIATIONS perche' il TTS le legga per
    esteso ("ecc." -> "eccetera"). Usata da EPUB/PDF (clean_text_for_tts) e,
    da F1b, anche da TXT e ABM (plain_parsers)."""
    for rule, expansion in _ABBR_RULES:
        text = rule.sub(expansion, text)
    return text


# ---------------------------------------------------------------------------
# Regole di testo pre-TTS (F1c, 2026-10-10; prima in tts_split)
# ---------------------------------------------------------------------------

def _flatten_ws(text):
    """Porta il testo su una riga sola: collassa ogni whitespace in uno spazio e
    riattacca la punteggiatura rimasta staccata."""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s+([,;:.!?])', r'\1', text)
    return text.strip()


# Guardia sugli incisi (incidente 25/10/2026): in un PDF OCR una parentesi
# letta male ("[hr" per "Ihr", "Pal]" per "Fall") apre uno span che la regex
# chiude decine di migliaia di caratteri dopo; tolto quello, una tonda senza
# chiusa si accoppiava con la successiva. Il libro e' stato fatturato intero e
# letto per meta'. Uno span piu' lungo della soglia, misurato sul testo di
# partenza (coppie interne gia' tolte comprese), o che attraversa una riga
# vuota non e' un inciso: resta nel testo, parentesi comprese.
PAREN_STRIP_MAX_CHARS_DEFAULT = 400
_ROUND_SPAN_RE = re.compile(r'\([^()]*\)')
_SQUARE_SPAN_RE = re.compile(r'\[[^\[\]]*\]')
_BLANK_LINE_RE = re.compile(r'\n\s*\n')


def _paren_strip_max_chars():
    """Soglia letta a ogni chiamata; <= 0 toglie il limite di lunghezza."""
    return env_int("ABM_PAREN_STRIP_MAX_CHARS", PAREN_STRIP_MAX_CHARS_DEFAULT)


def drop_parenthetical(text, strip_round=True, strip_square=True):
    """Il testo senza gli incisi tra tonde e/o quadre (anche annidati), con
    spazi e a-capo lasciati come sono. E' la parte di `_strip_parenthetical`
    che decide cosa la voce non legge: la usa anche il prezzo
    (`pricing_common.billable_text`), che fattura il testo letto.

    Uno span oltre `ABM_PAREN_STRIP_MAX_CHARS` caratteri, o con una riga vuota
    dentro, resta intatto (vedi la guardia qui sopra). Gli span tolti diventano
    un carattere segnaposto ripetuto per la loro lunghezza, cosi' la coppia che
    li contiene si misura sul testo di partenza; i segnaposto spariscono alla
    fine. Una coppia tenuta non fa da ancora: `[^()]*` non la attraversa.
    """
    if not (strip_round or strip_square):
        return text
    max_chars = _paren_strip_max_chars()
    used = set(text)  # una scansione sola, non una per candidato PUA
    # PUA piena: hole '' toglie gli span a vuoto e replace('', '') e' neutro (misura storica).
    hole = next((chr(c) for c in range(0xE000, 0xF900) if chr(c) not in used), '')

    def _drop(m):
        span = m.group(0)
        if (max_chars > 0 and len(span) > max_chars) or _BLANK_LINE_RE.search(span):
            return span
        return hole * len(span)

    prev = None
    while prev != text:
        prev = text
        if strip_round:
            text = _ROUND_SPAN_RE.sub(_drop, text)
        if strip_square:
            text = _SQUARE_SPAN_RE.sub(_drop, text)
    return text.replace(hole, '')


def paren_strip_flags(src):
    """`{"strip_round", "strip_square"}` dalle scelte dell'utente
    `read_round_parens` / `read_square_brackets` di un job, di un descrittore
    o del body di una richiesta: assenti = testo tra parentesi tolto (il
    default). Da passare con `**` a `_plan_chunks`, `prepare_tts_text` e alle
    stime di prezzo, che cosi' leggono e fatturano lo stesso testo."""
    src = src or {}
    return {"strip_round": not bool(src.get("read_round_parens", False)),
            "strip_square": not bool(src.get("read_square_brackets", False))}


def _strip_parenthetical(text, strip_round=True, strip_square=True, flatten=True):
    """Rimuove il contenuto tra parentesi tonde e/o quadre (anche annidate).

    strip_round:  se True rimuove il contenuto tra parentesi tonde ().
    strip_square: se True rimuove il contenuto tra parentesi quadre [].

    Se entrambi False la funzione non rimuove alcun contenuto: applica comunque
    la sola normalizzazione whitespace/punteggiatura finale, cosi` l'unica
    differenza tra le modalita` e` la presenza/assenza del testo tra parentesi
    (nessun altro effetto collaterale sul testo). Default: rimuove entrambe
    (comportamento storico).

    flatten: se True (default storico) il testo viene portato su una riga sola.
        `_plan_chunks` passa False perche' le normalizzazioni successive
        (`_normalize_shouting`, `_ensure_heading_pause`) ragionano per riga e
        hanno bisogno degli a-capo: appiattisce lui alla fine. Con False gli
        spazi DENTRO la riga vengono comunque collassati, gli a-capo no.

    La rimozione degli span e' `drop_parenthetical`.
    """
    text = drop_parenthetical(text, strip_round, strip_square)
    if flatten:
        return _flatten_ws(text)
    text = re.sub(r'[^\S\n]+', ' ', text)
    text = re.sub(r'[^\S\n]+([,;:.!?])', r'\1', text)
    text = re.sub(r'[^\S\n]*\n[^\S\n]*', '\n', text)
    return text.strip()


# Numero romano in forma stretta (IL, IC... non passano). Attenzione: matcha
# anche la stringa vuota, i chiamanti devono escluderla.
_ROMAN_RE = re.compile(r'^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$')

# Parole che introducono una numerazione: solo dopo una di queste un token
# romano corto (I, V, XI...) viene letto come numero e non come parola.
_NUMBERING_WORDS = frozenset((
    "capitolo", "capitoli", "cap", "parte", "libro", "tomo", "volume", "vol",
    "sezione", "atto", "scena", "canto", "appendice",
    "chapter", "part", "book", "act", "scene", "section", "appendix",
    "capitulo", "capítulo", "seccion", "sección", "acto", "escena",
    "kapitel", "teil", "buch", "abschnitt", "akt", "szene",
    "chapitre", "partie", "livre", "acte", "scène",
))

_SENT_END_CHARS = '.!?…'


def _word_core(token):
    """Nucleo del token, senza la punteggiatura ai bordi.
    «ADESSO,» -> «ADESSO», «"BASTA"» -> «BASTA», «L'AMORE» -> «L'AMORE»."""
    return re.sub(r'^\W+|\W+$', '', token, flags=re.UNICODE)


def _is_roman_numeral(core):
    return bool(core) and bool(_ROMAN_RE.match(core))


def _is_shouted_word(core):
    """True se il token ha almeno 2 lettere e sono tutte maiuscole."""
    letters = [c for c in core if c.isalpha()]
    if len(letters) < 2:
        return False
    return all(c.isupper() for c in letters)


def _line_is_shouted(line):
    """True se la riga e` interamente maiuscola (heading urlato).

    Una riga di una sola parola deve avere >=5 lettere: sotto quella soglia e`
    piu` probabilmente una sigla (NATO, ONU) che un titolo.
    """
    letters = [c for c in line if c.isalpha()]
    if not letters or not all(c.isupper() for c in letters):
        return False
    if len(line.split()) == 1:
        return len(letters) >= 5
    return len(letters) >= 4


def _recapitalize(text):
    """Rimette la maiuscola a inizio testo e dopo ogni terminatore di frase."""
    chars = list(text)
    need_upper = True
    for i, c in enumerate(chars):
        if need_upper and c.isalpha():
            chars[i] = c.upper()
            need_upper = False
        elif c in _SENT_END_CHARS:
            need_upper = True
    return ''.join(chars)


def _sentence_case_shouted_line(line):
    """Porta a sentence case una riga interamente maiuscola.

    I numeri romani di numerazione restano maiuscoli, ma solo dove il contesto
    lo conferma: preceduti da una parola di numerazione («CAPITOLO XIV»), oppure
    ultimo token della riga e lunghi almeno 3 caratteri («XVIII»). Senza questo
    vincolo l'italiano si rovina: DI, MI, CI, VI, LI sono numeri romani validi e
    «STORIA DI UN UOMO» diventerebbe «Storia DI un uomo».
    """
    tokens = re.split(r'(\s+)', line)
    word_idx = [i for i, t in enumerate(tokens) if t.strip()]
    out = list(tokens)
    prev_core = ""
    for pos, i in enumerate(word_idx):
        core = _word_core(tokens[i])
        is_last = (pos == len(word_idx) - 1)
        keep_upper = _is_roman_numeral(core) and (
            prev_core.lower() in _NUMBERING_WORDS
            or (is_last and len(core) >= 3))
        if not keep_upper:
            out[i] = tokens[i].lower()
        prev_core = core
    return _recapitalize(''.join(out))


def _is_caps_filler(core):
    """True per una parola di una sola lettera maiuscola («E», «A», «I»).

    Dentro una sequenza urlata fa parte dell'urlato («SEMPRE E COMUNQUE») e non
    deve spezzarla; da sola pero` non ne apre una, o «una A maiuscola» finirebbe
    per essere riscritta.
    """
    letters = [c for c in core if c.isalpha()]
    return len(letters) == 1 and letters[0].isupper()


def _lower_inline_shouted_runs(line):
    """Abbassa le sequenze di 2+ parole maiuscole consecutive dentro una riga a
    case misto (enfasi tipografica: «era VERAMENTE MOLTO stanco»).

    La sequenza serve perche' un token maiuscolo isolato e` quasi sempre un
    acronimo («la NASA ha confermato»), che il TTS deve continuare a sillabare.
    """
    tokens = re.split(r'(\s+)', line)
    word_idx = [i for i, t in enumerate(tokens) if t.strip()]
    cores = [_word_core(tokens[i]) for i in word_idx]
    shouted = [_is_shouted_word(c) for c in cores]
    filler = [_is_caps_filler(c) for c in cores]
    out = list(tokens)
    changed = False
    pos = 0
    while pos < len(word_idx):
        if not shouted[pos]:
            pos += 1
            continue
        # La sequenza si estende oltre i filler ma deve CHIUDERE su una parola
        # urlata vera: «SEMPRE E COMUNQUE» si prende tutto, «SEMPRE E poi» no.
        end = pos
        real = 1
        scan = pos
        while scan + 1 < len(word_idx) and (shouted[scan + 1] or filler[scan + 1]):
            scan += 1
            if shouted[scan]:
                end = scan
                real += 1
        if real >= 2:
            for k in range(pos, end + 1):
                out[word_idx[k]] = tokens[word_idx[k]].lower()
            # La maiuscola torna solo se la sequenza apriva una frase. Il resto
            # della riga ha la sua punteggiatura originale: un _recapitalize
            # globale rovinerebbe le abbreviazioni («es. testo» -> «es. Testo»).
            starts_sentence = (
                pos == 0
                or tokens[word_idx[pos - 1]].rstrip()[-1:] in _SENT_END_CHARS)
            if starts_sentence:
                out[word_idx[pos]] = _recapitalize(out[word_idx[pos]])
            changed = True
        pos = end + 1
    return ''.join(out) if changed else line


def _normalize_shouting(text):
    """Normalizza il MAIUSCOLO, che i motori neurali leggono male (VoxCPM in
    italiano su tutti: lo stesso titolo in minuscolo viene letto correttamente).

    Riga per riga: se e` interamente maiuscola (heading urlato) va a sentence
    case; altrimenti si abbassano solo le sequenze di 2+ parole maiuscole
    consecutive (enfasi), lasciando intatti gli acronimi isolati.

    L'ortografia dei nomi propri si perde («IL SIGNORE DEGLI ANELLI» ->
    «Il signore degli anelli») ed e` accettabile: il case delle minuscole non
    cambia la pronuncia, mentre il maiuscolo pieno la rovina.
    """
    if not text:
        return text
    out = []
    for line in text.split("\n"):
        if _line_is_shouted(line):
            out.append(_sentence_case_shouted_line(line))
        else:
            out.append(_lower_inline_shouted_runs(line))
    return "\n".join(out)


# Punteggiatura che chiude gia` una riga o un titolo: niente punto in coda.
# Comprese le forme CJK (a larghezza piena, e «｡» a mezza): un punto latino
# dopo «。» e` un segno in piu` che il motore puo` leggere.
_CHIUSA_RE = re.compile(
    r'[.!?…:;。．！？：；｡]\s*$')


def _ensure_heading_pause(text):
    """Aggiunge un punto finale alle righe che sembrano heading nel testo,
    così il TTS inserisce una pausa naturale prima del corpo del paragrafo.

    Un heading è una riga breve (<=120 char) isolata da righe vuote che non
    termina già con punteggiatura (.!?…:; e le forme CJK, vedi _CHIUSA_RE).
    """
    lines = text.split("\n")
    result = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if (stripped
                and len(stripped) <= 120
                and not _CHIUSA_RE.search(stripped)):
            prev_empty = (idx == 0) or (not lines[idx - 1].strip())
            next_empty = (idx == len(lines) - 1) or (not lines[idx + 1].strip())
            if prev_empty and next_empty:
                result.append(line.rstrip() + ".")
                continue
        result.append(line)
    return "\n".join(result)


def prepare_tts_text(text, strip_round=True, strip_square=True, flatten=True):
    """Catena unica di preparazione del testo prima del TTS.

    L'ordine e` obbligato: `_normalize_shouting` e `_ensure_heading_pause`
    ragionano per riga, quindi devono girare PRIMA dell'appiattimento. Chi
    appiattisce a monte le disattiva senza accorgersene — su una riga sola non
    esiste piu` un heading isolato, e il titolo resta incollato al paragrafo.
    E` esattamente cosi` che l'anteprima voce e` rimasta indietro rispetto alla
    generazione: questa funzione esiste per non avere piu` due catene da tenere
    allineate a mano.

    flatten: True (default) restituisce una riga sola, com'e` giusto per il
        testo che va al motore. False conserva gli a-capo per chi il testo lo
        deve mostrare — lo snapshot .abm — dove l'appiattimento sarebbe solo
        una perdita di leggibilita`: le parole sono comunque le stesse.
    """
    prepared = _strip_parenthetical(text, strip_round=strip_round,
                                    strip_square=strip_square, flatten=False)
    prepared = _normalize_shouting(prepared)
    prepared = _ensure_heading_pause(prepared)
    return _flatten_ws(prepared) if flatten else prepared.strip()


def _normalize_for_title_match(s):
    """Normalizza una stringa per fuzzy-match titolo: minuscolo, senza diacritici,
    senza punteggiatura/quote, whitespace compatto.

    Es: 'AINULINDALË"LA MUSICA"' -> 'ainulindale la musica'
    """
    if not s:
        return ""
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return s.strip()


def _title_already_in_text(title, text, lookahead_chars=300):
    """True se il titolo del capitolo compare gia` in testa al testo del capitolo,
    a meno di diacritici/punteggiatura/quote/prefissi numerici.

    Evita la duplicazione quando l'estrazione capitoli include gia` un heading
    nel body identico al titolo derivato dai metadati (es. EPUB + filename
    normalizzato).
    """
    if not title or not text:
        return False
    norm_title = _normalize_for_title_match(title)
    # Rimuovi prefisso numerico tipo "003 ", "01 ", "chapter 3 ", "capitolo 4 "
    tokens = norm_title.split()
    while tokens and (tokens[0].isdigit() or tokens[0] in ("chapter", "capitolo", "cap", "ch")):
        tokens.pop(0)
    norm_title_core = ' '.join(tokens)
    # Titolo troppo corto/generico (<= 4 char): meglio non dedupliccare per evitare falsi positivi
    if not norm_title_core or len(norm_title_core) <= 4:
        return False
    head = text[:lookahead_chars]
    norm_head = _normalize_for_title_match(head)
    return norm_title_core in norm_head


def _sanitize_tts_text(text: str):
    """Pulisce il testo per TTS: normalizza Unicode in NFC, rimuove caratteri
    di controllo/zero-width, collassa whitespace eccessivo, normalizza newline.

    Ritorna il testo pulito, oppure None se vuoto o diventato vuoto dopo pulizia
    (il chiamante deve generare silenzio in quel caso).

    PERCHE' L'NFC STA QUI E NON A MONTE
        Un accento puo' essere scritto in due modi che sullo schermo sono
        identici: `\u00e9` (U+00E9, NFC) oppure `e` + U+0301 (NFD). I motori TTS
        leggono la forma decomposta come vocale nuda: `perch\u00e9` in NFD viene
        letto \u00abperche\u00bb. Misurato su VoxCPM: stesso seme, stesso testo logico,
        audio diverso e durata diversa (6,08 s in NFC contro 6,40 s in NFD).
        Il problema non e' del singolo motore, e nemmeno dell'ottimizzazione
        AI del testo \u2014 un LLM non vede la differenza e restituisce quello che
        gli e' arrivato.

        `clean_text_for_tts` normalizza gia' i corpi dei capitoli di EPUB e
        PDF, ma non copre i titoli (che arrivano dal TOC o dagli heading), i
        .txt e i .abm (`parse_txt`/`parse_abm` non normalizzano), ne' il testo
        che torna dall'ottimizzazione LLM o dalla traduzione. Questa funzione
        e' invece l'ultimo punto comune: la chiamano tutte e quattro le
        `generate_chunk_*` (edge, Gemini, Speechify, Google), quindi qualunque
        provenienza del testo e qualunque motore \u2014 compresi quelli che
        verranno \u2014 passano di qui.

        NFC e non NFKC: NFKC riscriverebbe anche le legature e gli apici
        tipografici, che sono scelte dell'autore, non danni di codifica.
    """
    clean = unicodedata.normalize('NFC', text).strip()
    if not clean:
        return None
    # U+FFFD: residuo di un'estrazione PDF fallita, nessun motore lo legge
    # (pagine intere di soli U+FFFD fallivano su edge-tts a ogni tentativo).
    clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u00ad\u200b-\u200f\u2028-\u202f\ufeff\ufffd\ufffe\uffff]', '', clean)
    clean = re.sub(r'\n{3,}', '\n\n', clean)
    clean = re.sub(r' {3,}', ' ', clean)
    if not clean.strip():
        return None
    return clean


def spoken_title_prefix(ch, text):
    """Il titolo che il TTS legge in testa al capitolo, separatore compreso.

    "" quando il titolo non si legge. E' la sola fonte di questa regola: la
    usa il piano e la usa la stima VoxCPM, cosi' il prezzo conta le stesse
    parole che la voce pronuncera'. Il 27/09/2026 un libro da 402 capitoli
    ha letto ~15 mila caratteri di titoli non fatturati.

    `text` e' il corpo con cui confrontare il titolo: nel piano quello gia'
    preparato per il TTS, nella stima quello grezzo (il confronto normalizza
    diacritici e punteggiatura, la differenza non sposta il verdetto).
    """
    title = _normalize_shouting((getattr(ch, "title", "") or "").strip())
    # Titolo sintetico (placeholder "Section N" generato dal parser per uno
    # spine item senza titolo reale, es. front-matter): NON leggerlo, non e'
    # un titolo del libro. Altrimenti dedup heading: se il titolo compare
    # gia` in testa al testo (a meno di diacritici/punteggiatura/quote/
    # prefissi numerici), evita di prependerlo per non farlo leggere due volte.
    if (not title
            or getattr(ch, "synthetic_title", False)
            or _title_already_in_text(title, text)):
        return ""
    # Il punto serve a dare la pausa prima del corpo, ma solo se il
    # titolo non ha gia` una punteggiatura sua («Perche'?» -> «Perche'?.»).
    sep = "" if _CHIUSA_RE.search(title) else "."
    return f"{title}{sep}\n\n"


def trim_preview(text, min_chars=400, max_chars=600):
    """Tronca tra min e max caratteri a fine frase, oppure all'ultimo spazio.

    Normalizza prima di troncare, non dopo: `prepare_tts_text` ragiona per
    riga, e questo testo esce di qui su una riga sola. Appiattirlo prima
    significherebbe spegnere la pausa dopo il titolo — e l'anteprima voce
    e` proprio il posto dove l'utente quella pausa la deve sentire.
    Le parentesi qui restano: i flag di lettura li sceglie l'utente dopo,
    e li applica l'endpoint dell'anteprima.
    """
    text = prepare_tts_text(text, strip_round=False, strip_square=False)
    if len(text) <= max_chars:
        return text
    window = text[min_chars:max_chars]
    m = re.search(r'[.!?]["""»\)\s]', window)
    cut = (min_chars + m.start() + 1) if m else text.rfind(' ', min_chars, max_chars)
    if cut <= 0:
        cut = max_chars
    return text[:cut].rstrip()
