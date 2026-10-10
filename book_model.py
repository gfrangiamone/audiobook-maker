"""book_model — il modello del libro comune a EPUB, PDF, TXT e ABM (F1a, 2026-10-10).

Modulo foglia (solo stdlib). Prima: `Chapter`/`BookInfo` in `epub_to_tts`
reimportati da `pdf_to_tts`, una copia duck-typed (`_SimpleChapter`,
`_SimpleBookInfo`) in `generation_engine` per TXT/ABM, il ricalcolo dei
totali (`total_words / 150`) in undici punti, due liste di titoli di
apparato (`NON_CONTENT_TITLE_PHRASES` dell'EPUB e `NON_CONTENT_TITLES` del
PDF) divergenti.

- `Chapter`, `BookInfo` (+ `recompute_totals()`, `BookInfo.from_text()` per
  un testo unico); `WORDS_PER_MINUTE` = 150 e' l'unica stima di durata.
- `synthetic_section_title(n, language)`: placeholder localizzato per una
  sezione senza titolo (il `Chapter` va marcato `synthetic_title=True`).
- Liste di apparato: `NON_CONTENT_FILENAMES_EXACT`/`_SUBSTR` (stem del file
  nello spine EPUB), `NON_CONTENT_TITLE_PHRASES` (match per parola intera,
  ora l'unione delle liste EPUB e PDF) e `NON_CONTENT_TITLE_EXACT` (solo
  titolo intero), `title_is_non_content(title)`, `is_backnote_toc_title`.
- `print_book_info(info)`: il riepilogo della CLI, prima duplicato nel PDF.
"""
import re
from dataclasses import dataclass, field

WORDS_PER_MINUTE = 150      # ~parole al minuto di una lettura TTS, per la stima di durata


@dataclass
class Chapter:
    """Un capitolo del libro."""
    index: int
    title: str
    text: str
    word_count: int = 0
    char_count: int = 0
    source_file: str = ""
    # True quando `title` non e' un titolo reale del libro ma un placeholder
    # generato dal parser (spine item senza TOC/heading, tipico front-matter:
    # disclaimer, epigrafi, dedica). Consumato da _plan_chunks per NON far
    # leggere al TTS un'etichetta artificiale come se fosse un titolo.
    synthetic_title: bool = False

    def __post_init__(self):
        self.word_count = len(self.text.split())
        self.char_count = len(self.text)


@dataclass
class BookInfo:
    """Metadati del libro e capitoli."""
    title: str = "Sconosciuto"
    author: str = "Sconosciuto"
    language: str = ""
    publisher: str = ""
    description: str = ""
    date: str = ""  # Data di pubblicazione (YYYY, YYYY-MM, YYYY-MM-DD da dc:date)
    chapters: list = field(default_factory=list)
    total_words: int = 0
    total_chars: int = 0
    estimated_duration_minutes: float = 0.0

    def recompute_totals(self):
        """Parole, caratteri e durata stimata dai capitoli correnti. Ritorna self."""
        self.total_words = sum(ch.word_count for ch in self.chapters)
        self.total_chars = sum(ch.char_count for ch in self.chapters)
        self.estimated_duration_minutes = self.total_words / WORDS_PER_MINUTE
        return self

    @classmethod
    def from_text(cls, title, author, text, language=""):
        """Libro di un solo capitolo (TXT): titolo del capitolo = titolo del libro."""
        info = cls(title=title, author=author, language=language,
                   chapters=[Chapter(index=1, title=title, text=text)])
        return info.recompute_totals()


# Etichetta localizzata per i placeholder di sezione senza titolo. La lingua e'
# quella del LIBRO (info.language), non della UI. Fallback "Section" (inglese)
# per lingue non mappate: mai italiano hardcodato su libri di altra lingua.
_SECTION_LABELS = {
    "it": "Sezione", "en": "Section", "fr": "Section", "es": "Sección",
    "de": "Abschnitt", "pt": "Seção", "nl": "Sectie", "ru": "Раздел",
    "zh": "章节", "ja": "セクション", "hi": "अनुभाग", "ar": "قسم",
}


def synthetic_section_title(n, language=""):
    """Placeholder localizzato per una sezione senza titolo ("Section N")."""
    code = (language or "").strip().lower().replace("_", "-").split("-")[0]
    label = _SECTION_LABELS.get(code, "Section")
    return f"{label} {n}"


# ---------------------------------------------------------------------------
# Sezioni di apparato (non narrative)
# ---------------------------------------------------------------------------

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

# Frasi che identificano sezioni di apparato critico (non narrative). Lista
# canonica condivisa da EPUB e PDF (F1a: unione delle due liste storiche). Il
# match e' per PAROLA INTERA (vedi title_is_non_content): un token corto come
# "note"/"toc"/"cover"/"index" NON deve scartare titoli legittimi
# ("Notevole...", "Autocrazia", "Discovering...", "Indexed...").
NON_CONTENT_TITLE_PHRASES = [
    # ── Indice / TOC ──
    "indice", "indice generale", "indice dei contenuti", "indice analitico",
    "sommario", "table of contents", "contents", "toc",
    "table des matières", "sommaire", "índice", "índice general",
    "inhaltsverzeichnis", "inhalt", "目录",
    # ── Copyright / Colophon ──
    "copyright", "colophon", "note legali", "informazioni legali",
    "avviso legale", "legal notice", "all rights reserved",
    "copyright notice", "mentions légales", "aviso legal",
    "impressum",
    # ── Copertina / Frontespizio ──
    "frontespizio", "title page", "cover", "copertina",
    "half title", "halftitle", "page de titre",
    # ── Quarta di copertina / sinossi ──
    "quarta di copertina", "risvolto di copertina", "risvolto",
    "back cover", "quatrième de couverture", "quatrieme de couverture",
    "klappentext", "contraportada", "plot summary",
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
    # ── Indice riferimenti (testi religiosi/critici) ──
    "indice dei riferimenti",
]

# Titoli di apparato che valgono SOLO come titolo intero. "Trama" e
# "Sinossi" intitolano la quarta di copertina, ma sono anche parole comuni:
# "La trama del destino" e "Sinossi dei Vangeli" sono capitoli veri. Il match
# per parola intera li scarterebbe tutti, quello esatto prende solo la
# sezione di apparato.
NON_CONTENT_TITLE_EXACT = {
    "trama", "sinossi", "synopsis", "sinopsis", "resumen", "blurb",
}


def title_is_non_content(title, phrases=NON_CONTENT_TITLE_PHRASES):
    """True se il titolo corrisponde a una frase di apparato critico.

    Match per PAROLA INTERA usando confini \\w Unicode (i caratteri accentati
    sono word-char in Python 3): "note" matcha "Note" / "Note al testo" ma NON
    "Notevole"; "toc" non matcha "Autocrazia"; "cover" non matcha "Discovering".
    Per frasi multi-parola i confini si applicano agli estremi della frase.
    """
    tl = (title or "").lower()
    # I titoli ambigui valgono solo per intero, non come parola.
    if tl.strip().strip(".:;–—- ") in NON_CONTENT_TITLE_EXACT:
        return True
    for skip in phrases:
        if re.search(r"(?<!\w)" + re.escape(skip) + r"(?!\w)", tl):
            return True
    return False


# Caratteri di freccia "indietro" usati dai back-link a nota (return-to-text).
# Un titolo TOC che è SOLO una di queste frecce seguita da cifre è un rimando
# di apparato (es. "←7"), non un capitolo.
_BACKNOTE_ARROWS = "←↩⇐⬅⟵‹◀↺⎌"
_BACKNOTE_TITLE_RE = re.compile(
    rf"^\s*(?:<[-‐-―]|[{_BACKNOTE_ARROWS}])\s*\d*\s*$"
)


def is_backnote_toc_title(title) -> bool:
    """True se il titolo TOC è un back-link a nota (freccia indietro + numero).

    Alcuni EPUB esportati da Word listano nel TOC i rimandi di ritorno dalle
    note ("←1", "←2", … o la forma ASCII "<-1"): non sono capitoli ma apparato.
    Match volutamente stretto: un titolo reale non inizia mai con una freccia
    indietro isolata.
    """
    if not title:
        return False
    return bool(_BACKNOTE_TITLE_RE.match(str(title)))


def print_book_info(info):
    """Stampa un riepilogo del libro estratto (CLI di epub_to_tts e pdf_to_tts)."""
    print(f"\n{'═'*60}")
    print(f"  {info.title}")
    if info.author:
        print(f"  di {info.author}")
    print(f"{'═'*60}")
    if getattr(info, "language", ""):
        print(f"  Lingua:     {info.language}")
    if getattr(info, "publisher", ""):
        print(f"  Editore:    {info.publisher}")
    print(f"  Capitoli:   {len(info.chapters)}")
    print(f"  Parole:     {info.total_words:,}")
    print(f"  Caratteri:  {info.total_chars:,}")
    print(f"  Durata ~    {info.estimated_duration_minutes:.0f} minuti")
    print(f"{'─'*60}")
    for ch in info.chapters:
        est = ch.word_count / WORDS_PER_MINUTE
        print(f"  {ch.index:3d}. {ch.title[:45]:<45s} {ch.word_count:>6,} parole  ~{est:.0f} min")
    print(f"{'═'*60}\n")
