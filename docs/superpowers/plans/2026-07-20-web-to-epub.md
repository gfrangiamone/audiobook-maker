# web_to_epub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uno script CLI che converte una pagina web (o un documento su più pagine collegate) in un `.epub` con TOC a due livelli — capitoli e sottocapitoli — funzionando sia su HTML semantico sia su HTML sporco, in lingue e sistemi di scrittura diversi.

**Architecture:** Wrapper PowerShell sottile (`scripts/web_to_epub.ps1`) che valida i parametri e invoca un engine Python monolitico (`scripts/web_to_epub.py`). L'engine esegue una pipeline lineare: fetch → de-boilerplate → linearizzazione in blocchi con feature → rilevamento lingua → assegnazione livelli (euristica, opzionalmente assistita da LLM) → assemblaggio outline → scrittura EPUB. Riusa `translation_core` del progetto per il client LLM; scrive l'EPUB con `ebooklib` tramite una funzione locale a TOC annidata.

**Tech Stack:** Python 3, `requests`, `beautifulsoup4`, `ebooklib`, `openai` (via `translation_core`), `pytest`, PowerShell 7.

**Spec di riferimento:** `docs/superpowers/specs/2026-07-20-web-to-epub-design.md`

## Global Constraints

- Tutti i file dell'engine vivono in `scripts/`, che è **ignorata da git** (`.gitignore` riga 14). Scelta esplicita dell'utente: i file restano **locali, non versionati, non deployati**.
- **Conseguenza sui commit:** nessuno step di questo piano committa codice. Le voci "Commit" dello standard TDD sono sostituite da **"Checkpoint"**: eseguire l'intera suite e verificare che sia verde prima di passare al task successivo. Non usare `git add -f` sui file in `scripts/`.
- I test vivono in `scripts/test_web_to_epub.py`, **fuori** da `test/`: non girano nella CI di deploy. Comando: `pytest scripts/test_web_to_epub.py -v`.
- I test sono **interamente offline**: nessuna chiamata di rete, nessuna chiamata LLM reale. Fixture HTML in `scripts/fixtures_web_to_epub/`.
- Nessuna nuova dipendenza in `requirements.txt`. Usare solo `requests`, `beautifulsoup4`, `ebooklib`, `openai`, stdlib.
- Massimo **due livelli** di gerarchia. Un terzo livello va degradato a corpo, mai emesso.
- L'engine non deve **mai** importare `audiobook_app` (re-import dell'entry point = job di produzione uccisi). Importare solo `translation_core`.
- Nomi di variabili e commenti: convenzione del progetto, italiano/inglese misti. Messaggi a schermo in italiano.
- Ogni funzione pubblica dell'engine è pura rispetto alla rete: le funzioni che scaricano accettano un parametro `fetcher` iniettabile, così i test passano una funzione fittizia.

---

## File Structure

| File | Responsabilità |
|---|---|
| `scripts/web_to_epub.py` | Engine completo: fetch, de-boilerplate, crawl, feature, lingua, outline, LLM, writer EPUB, CLI `main()` |
| `scripts/web_to_epub.ps1` | Wrapper PowerShell: parametri, individuazione interprete Python, propagazione exit code |
| `scripts/test_web_to_epub.py` | Suite pytest offline |
| `scripts/fixtures_web_to_epub/semantic.html` | Pagina con `h1/h2` semantici |
| `scripts/fixtures_web_to_epub/vatican_like.html` | Pagina stile vatican.va: `<p><b>` maiuscolo, note `[n]`, indice interno |
| `scripts/fixtures_web_to_epub/cjk.html` | Pagina cinese con `第一章` e `<html lang>` assente |
| `scripts/fixtures_web_to_epub/mislabeled.html` | `<html lang="en">` ma testo italiano |

L'engine è un modulo unico (~700 righe) coerente con gli altri script operativi del progetto (`scripts/translate_abm.py`). Le sezioni interne sono separate da commenti banner.

---

### Task 1: Scaffolding, costanti e fetch HTTP

**Files:**
- Create: `scripts/web_to_epub.py`
- Create: `scripts/test_web_to_epub.py`

**Interfaces:**
- Consumes: nulla
- Produces:
  - `class FetchError(Exception)`
  - `fetch_page(url, *, session=None, timeout=20, retries=2, sleep=time.sleep) -> str` — ritorna l'HTML decodificato; solleva `FetchError` dopo l'ultimo tentativo fallito
  - `USER_AGENT: str`

- [ ] **Step 1: Scrivere il test che fallisce**

Creare `scripts/test_web_to_epub.py`:

```python
"""Suite offline per scripts/web_to_epub.py. Nessuna rete, nessun LLM."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import web_to_epub as w2e


class FakeResponse:
    """Sostituto di requests.Response per i test."""

    def __init__(self, content=b"", status_code=200, encoding=None,
                 apparent_encoding="utf-8"):
        self.content = content
        self.status_code = status_code
        self.encoding = encoding
        self.apparent_encoding = apparent_encoding
        self.headers = {"Content-Type": "text/html"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Sessione che restituisce risposte predefinite e registra le chiamate."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_fetch_page_decodes_with_apparent_encoding():
    html = "<html><body><p>perché città</p></body></html>"
    resp = FakeResponse(content=html.encode("utf-8"),
                        encoding="ISO-8859-1",
                        apparent_encoding="utf-8")
    session = FakeSession([resp])

    out = w2e.fetch_page("https://example.org/doc.html", session=session)

    assert "perché città" in out


def test_fetch_page_retries_then_succeeds():
    ok = FakeResponse(content=b"<html><body>ok</body></html>")
    session = FakeSession([RuntimeError("boom"), ok])
    slept = []

    out = w2e.fetch_page("https://example.org/doc.html", session=session,
                         sleep=slept.append)

    assert "ok" in out
    assert len(session.calls) == 2
    assert slept == [1]


def test_fetch_page_raises_after_retries_exhausted():
    session = FakeSession([RuntimeError("boom"), RuntimeError("boom"),
                           RuntimeError("boom")])

    with pytest.raises(w2e.FetchError) as exc:
        w2e.fetch_page("https://example.org/doc.html", session=session,
                       sleep=lambda _s: None)

    assert "example.org" in str(exc.value)
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web_to_epub'`

- [ ] **Step 3: Implementazione minima**

Creare `scripts/web_to_epub.py`:

```python
"""web_to_epub — converte una pagina web (o un documento su più pagine
collegate) in un EPUB con capitoli e sottocapitoli.

Script operativo locale: non versionato, non deployato. Vedi
docs/superpowers/specs/2026-07-20-web-to-epub-design.md
"""
import re
import time

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 "
              "Safari/537.36 web_to_epub/1.0")


class FetchError(Exception):
    """Errore di rete non recuperabile dopo i retry."""


# ---------------------------------------------------------------- fetch

def fetch_page(url, *, session=None, timeout=20, retries=2, sleep=time.sleep):
    """Scarica una pagina e ritorna l'HTML decodificato.

    L'encoding dichiarato viene ignorato in favore di apparent_encoding
    quando differiscono: molti siti istituzionali dichiarano charset errati.
    """
    if session is None:
        import requests
        session = requests.Session()

    last = None
    for attempt in range(retries + 1):
        try:
            resp = session.get(url, timeout=timeout,
                               headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            enc = resp.apparent_encoding or resp.encoding or "utf-8"
            return resp.content.decode(enc, errors="replace")
        except Exception as e:  # noqa: BLE001 - retry su qualsiasi errore
            last = e
            if attempt < retries:
                sleep(2 ** attempt)
    raise FetchError(f"fetch fallito per {url}: {last}")
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: PASS — 3 passed

- [ ] **Step 5: Checkpoint**

Run: `python -m py_compile scripts/web_to_epub.py`
Expected: nessun output, exit 0. Nessun commit (file gitignored per scelta).

---

### Task 2: De-boilerplate e selezione del contenitore

**Files:**
- Modify: `scripts/web_to_epub.py`
- Modify: `scripts/test_web_to_epub.py`
- Create: `scripts/fixtures_web_to_epub/semantic.html`

**Interfaces:**
- Consumes: nulla dal Task 1
- Produces:
  - `extract_container(html) -> bs4.element.Tag` — ritorna il nodo con maggiore densità di testo, ripulito dal boilerplate
  - `NOISE_TAGS: tuple[str, ...]`

- [ ] **Step 1: Scrivere la fixture**

Creare `scripts/fixtures_web_to_epub/semantic.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <title>The Sample Document - Example Site</title>
  <meta property="og:title" content="The Sample Document"/>
  <meta name="author" content="Jane Doe"/>
</head>
<body>
  <nav><a href="/home">Home</a><a href="/about">About</a></nav>
  <header><h1>Example Site</h1></header>
  <main>
    <h1>The Sample Document</h1>
    <p>An opening paragraph that belongs to the introduction of the work.</p>
    <h2>First Chapter</h2>
    <p>The first chapter body text goes here and is reasonably long.</p>
    <h3>A Subsection</h3>
    <p>The subsection body text goes here and is also reasonably long.</p>
    <h3>Another Subsection</h3>
    <p>More body text for the second subsection of the first chapter.</p>
    <h2>Second Chapter</h2>
    <p>The second chapter body text goes here for testing purposes.</p>
  </main>
  <aside><p>Related links you should ignore completely.</p></aside>
  <footer><p>Copyright notice that must not appear in the book.</p></footer>
  <script>var tracker = 1;</script>
</body>
</html>
```

- [ ] **Step 2: Scrivere il test che fallisce**

Aggiungere a `scripts/test_web_to_epub.py`:

```python
FIXTURES = Path(__file__).resolve().parent / "fixtures_web_to_epub"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_extract_container_picks_main_and_drops_noise():
    container = w2e.extract_container(fixture("semantic.html"))
    text = container.get_text(" ", strip=True)

    assert "first chapter body text" in text.lower()
    assert "Related links" not in text
    assert "Copyright notice" not in text
    assert "Home" not in text
    assert "tracker" not in text


def test_extract_container_falls_back_to_body():
    html = ("<html><body><p>" + "parola " * 60 + "</p></body></html>")
    container = w2e.extract_container(html)

    assert container.get_text(strip=True).startswith("parola")


def test_extract_container_picks_densest_of_several_candidates():
    html = ("<html><body>"
            "<div id='content'><p>corto</p></div>"
            "<div class='container'><p>" + "testo " * 80 + "</p></div>"
            "</body></html>")
    container = w2e.extract_container(html)

    assert "testo" in container.get_text()
    assert "corto" not in container.get_text()
```

- [ ] **Step 3: Eseguire i test e verificare che falliscano**

Run: `pytest scripts/test_web_to_epub.py -v -k container`
Expected: FAIL — `AttributeError: module 'web_to_epub' has no attribute 'extract_container'`

- [ ] **Step 4: Implementazione minima**

Aggiungere a `scripts/web_to_epub.py`:

```python
# -------------------------------------------------------- de-boilerplate

NOISE_TAGS = ("script", "style", "nav", "header", "footer", "aside",
              "form", "noscript", "iframe", "svg")

_CANDIDATE_SELECTORS = ("main", "article", "[role=main]", "#content",
                        "#main", ".container", ".content")


def extract_container(html):
    """Ritorna il nodo con maggiore densità di testo, senza boilerplate."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(NOISE_TAGS):
        tag.decompose()

    best, best_len = None, 0
    for sel in _CANDIDATE_SELECTORS:
        for node in soup.select(sel):
            n = len(node.get_text(" ", strip=True))
            if n > best_len:
                best, best_len = node, n

    body = soup.body or soup
    if best is None or best_len < len(body.get_text(" ", strip=True)) * 0.25:
        return body
    return best
```

- [ ] **Step 5: Eseguire i test e verificare che passino**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: PASS — 6 passed

- [ ] **Step 6: Checkpoint**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: suite verde. Nessun commit.

---

### Task 3: Rilevamento lingua

**Files:**
- Modify: `scripts/web_to_epub.py`
- Modify: `scripts/test_web_to_epub.py`
- Create: `scripts/fixtures_web_to_epub/mislabeled.html`
- Create: `scripts/fixtures_web_to_epub/cjk.html`

**Interfaces:**
- Consumes: `extract_container` (Task 2)
- Produces:
  - `detect_script(text) -> str` — uno tra `latin`, `cyrillic`, `greek`, `cjk`, `arabic`, `hebrew`, `devanagari`, `unknown`
  - `detect_language(html, text, *, override=None, llm=None) -> tuple[str, str]` — ritorna `(codice_lingua, fonte)` dove fonte ∈ `override|meta|stopwords|script|llm|unknown`. `llm` è un callable `(sample_text) -> str|None`, invocato solo se i passi precedenti falliscono.

- [ ] **Step 1: Scrivere le fixture**

Creare `scripts/fixtures_web_to_epub/mislabeled.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head><title>Documento</title></head>
<body><main>
<p>Il documento che segue non e scritto in inglese, per quanto la pagina
lo dichiari. La lingua del testo e l italiano, e le parole piu frequenti
sono quelle che il rilevatore deve riconoscere per correggere il metadato
errato che il sito espone nella intestazione della pagina.</p>
</main></body>
</html>
```

Creare `scripts/fixtures_web_to_epub/cjk.html`:

```html
<!DOCTYPE html>
<html>
<head><title>示例文件</title></head>
<body><main>
<p><b>第一章</b></p>
<p>这是第一章的正文内容用于测试中文文档的章节识别功能和语言检测功能。</p>
<p><b>第二章</b></p>
<p>这是第二章的正文内容同样用于测试中文文档的章节识别与断句处理逻辑。</p>
</main></body>
</html>
```

- [ ] **Step 2: Scrivere il test che fallisce**

Aggiungere a `scripts/test_web_to_epub.py`:

```python
def test_detect_script_recognises_writing_systems():
    assert w2e.detect_script("Questo e un testo latino di prova") == "latin"
    assert w2e.detect_script("这是中文的正文内容用于测试") == "cjk"
    assert w2e.detect_script("Это русский текст для проверки") == "cyrillic"
    assert w2e.detect_script("هذا نص عربي للاختبار") == "arabic"


def test_detect_language_uses_html_lang_when_consistent():
    html = fixture("semantic.html")
    text = w2e.extract_container(html).get_text(" ", strip=True)

    lang, source = w2e.detect_language(html, text)

    assert lang == "en"
    assert source == "meta"


def test_detect_language_overrides_mislabeled_meta_with_stopwords():
    html = fixture("mislabeled.html")
    text = w2e.extract_container(html).get_text(" ", strip=True)

    lang, source = w2e.detect_language(html, text)

    assert lang == "it"
    assert source == "stopwords"


def test_detect_language_falls_back_to_script_for_cjk():
    html = fixture("cjk.html")
    text = w2e.extract_container(html).get_text(" ", strip=True)

    lang, source = w2e.detect_language(html, text)

    assert lang == "zh"
    assert source == "script"


def test_detect_language_manual_override_wins():
    html = fixture("semantic.html")
    lang, source = w2e.detect_language(html, "whatever", override="fr")

    assert (lang, source) == ("fr", "override")


def test_detect_language_calls_llm_only_when_undetermined():
    calls = []

    def fake_llm(sample):
        calls.append(sample)
        return "pt"

    # testo senza stopword note e senza meta: cascata esaurita
    lang, source = w2e.detect_language("<html><body></body></html>",
                                       "zzz qqq xxx yyy", llm=fake_llm)

    assert (lang, source) == ("pt", "llm")
    assert len(calls) == 1

    # con meta valido l'LLM non viene mai chiamato
    calls.clear()
    w2e.detect_language(fixture("semantic.html"), "the of and to in that",
                        llm=fake_llm)
    assert calls == []
```

- [ ] **Step 3: Eseguire i test e verificare che falliscano**

Run: `pytest scripts/test_web_to_epub.py -v -k "script or language"`
Expected: FAIL — `AttributeError: module 'web_to_epub' has no attribute 'detect_script'`

- [ ] **Step 4: Implementazione minima**

Aggiungere a `scripts/web_to_epub.py`:

```python
# ------------------------------------------------------- rilevamento lingua

_SCRIPT_RANGES = (
    ("cjk", ((0x3040, 0x30FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF),
             (0xAC00, 0xD7AF))),
    ("cyrillic", ((0x0400, 0x04FF),)),
    ("greek", ((0x0370, 0x03FF),)),
    ("arabic", ((0x0600, 0x06FF), (0x0750, 0x077F))),
    ("hebrew", ((0x0590, 0x05FF),)),
    ("devanagari", ((0x0900, 0x097F),)),
)

# lingua di default per gli script non alfabetici latini, usata quando i
# metadati mancano: sufficiente a scegliere il profilo euristico.
_SCRIPT_DEFAULT_LANG = {
    "cjk": "zh", "cyrillic": "ru", "greek": "el",
    "arabic": "ar", "hebrew": "he", "devanagari": "hi",
}

_STOPWORDS = {
    "it": {"il", "la", "di", "che", "non", "per", "con", "del", "una", "sono"},
    "en": {"the", "of", "and", "to", "in", "that", "is", "for", "with", "as"},
    "fr": {"le", "la", "de", "et", "les", "des", "que", "pour", "dans", "une"},
    "es": {"el", "la", "de", "que", "los", "en", "por", "con", "una", "para"},
    "de": {"der", "die", "und", "den", "des", "zu", "das", "ist", "mit", "auf"},
    "pt": {"que", "os", "as", "do", "da", "em", "para", "com", "uma", "nao"},
    "nl": {"de", "het", "een", "van", "en", "dat", "is", "op", "voor", "met"},
    "pl": {"nie", "sie", "jest", "na", "do", "ze", "oraz", "przez", "tego",
           "jak"},
}

_LANG_META_RE = (
    re.compile(r'<html[^>]*\blang=["\']([a-zA-Z\-]{2,8})["\']', re.I),
    re.compile(r'<meta[^>]+property=["\']og:locale["\'][^>]+'
               r'content=["\']([a-zA-Z\-_]{2,8})["\']', re.I),
    re.compile(r'<meta[^>]+http-equiv=["\']content-language["\'][^>]+'
               r'content=["\']([a-zA-Z\-]{2,8})["\']', re.I),
)


def detect_script(text):
    """Classe di scrittura dominante nei primi 2000 caratteri."""
    sample = text[:2000]
    counts = {}
    latin = 0
    for ch in sample:
        cp = ord(ch)
        if ch.isalpha() and cp < 0x0250:
            latin += 1
            continue
        for name, ranges in _SCRIPT_RANGES:
            if any(lo <= cp <= hi for lo, hi in ranges):
                counts[name] = counts.get(name, 0) + 1
                break
    if counts:
        top = max(counts, key=counts.get)
        if counts[top] >= latin:
            return top
    return "latin" if latin else "unknown"


def _stopword_language(text):
    """Lingua più probabile per frequenza di stopword. None se incerta."""
    words = re.findall(r"[^\W\d_]+", text.lower(), flags=re.UNICODE)[:1500]
    if len(words) < 20:
        return None
    scores = {lang: sum(1 for wd in words if wd in sw)
              for lang, sw in _STOPWORDS.items()}
    best = max(scores, key=scores.get)
    ordered = sorted(scores.values(), reverse=True)
    # richiede un margine netto sul secondo classificato
    if ordered[0] < 5 or ordered[0] < ordered[1] * 1.5:
        return None
    return best


def detect_language(html, text, *, override=None, llm=None):
    """Cascata di rilevamento. Ritorna (codice_lingua, fonte)."""
    if override:
        return override.lower()[:2], "override"

    script = detect_script(text)

    meta_lang = None
    for rx in _LANG_META_RE:
        m = rx.search(html or "")
        if m:
            meta_lang = m.group(1).lower().replace("_", "-")[:2]
            break

    guess = _stopword_language(text) if script == "latin" else None
    if guess and meta_lang and guess != meta_lang:
        return guess, "stopwords"      # il metadato mente
    if meta_lang:
        return meta_lang, "meta"
    if guess:
        return guess, "stopwords"
    if script in _SCRIPT_DEFAULT_LANG:
        return _SCRIPT_DEFAULT_LANG[script], "script"
    if llm:
        got = llm(text[:500])
        if got:
            return got.strip().lower()[:2], "llm"
    return "", "unknown"
```

- [ ] **Step 5: Eseguire i test e verificare che passino**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: PASS — 12 passed

- [ ] **Step 6: Checkpoint**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: suite verde. Nessun commit.

---

### Task 4: Profili lingua

**Files:**
- Modify: `scripts/web_to_epub.py`
- Modify: `scripts/test_web_to_epub.py`

**Interfaces:**
- Consumes: `detect_script` (Task 3)
- Produces:
  - `LANG_PROFILES: dict[str, dict]` — chiavi: codici lingua, classi di script, `generic`. Ogni profilo ha `script`, `keywords` (tuple lowercase), `max_title_len` (int), `sentence_end` (tuple di caratteri), `use_case` (bool)
  - `profile_for(lang, script) -> dict` — risoluzione con fallback lingua → script → `generic`

- [ ] **Step 1: Scrivere il test che fallisce**

Aggiungere a `scripts/test_web_to_epub.py`:

```python
def test_profile_for_exact_language():
    prof = w2e.profile_for("it", "latin")

    assert "capitolo" in prof["keywords"]
    assert prof["max_title_len"] == 120
    assert prof["use_case"] is True


def test_profile_for_falls_back_to_script_when_language_unknown():
    prof = w2e.profile_for("ja", "cjk")

    assert prof["max_title_len"] == 40
    assert prof["use_case"] is False
    assert "。" in prof["sentence_end"]


def test_profile_for_falls_back_to_generic():
    prof = w2e.profile_for("", "unknown")

    assert prof["keywords"] == ()
    assert prof["use_case"] is False
    assert prof["max_title_len"] == 120


def test_every_profile_has_the_required_keys():
    required = {"script", "keywords", "max_title_len", "sentence_end",
                "use_case"}
    for name, prof in w2e.LANG_PROFILES.items():
        assert required <= set(prof), f"profilo incompleto: {name}"
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest scripts/test_web_to_epub.py -v -k profile`
Expected: FAIL — `AttributeError: module 'web_to_epub' has no attribute 'profile_for'`

- [ ] **Step 3: Implementazione minima**

Aggiungere a `scripts/web_to_epub.py`:

```python
# ---------------------------------------------------------- profili lingua

_LATIN_END = (".", "!", "?", ":", ";")

# Estendere questo dizionario per supportare nuove lingue: nessuna logica
# altrove va toccata.
LANG_PROFILES = {
    "it": {"script": "latin", "max_title_len": 120, "use_case": True,
           "sentence_end": _LATIN_END,
           "keywords": ("capitolo", "parte", "sezione", "libro",
                        "introduzione", "conclusione", "premessa",
                        "appendice", "prefazione")},
    "en": {"script": "latin", "max_title_len": 120, "use_case": True,
           "sentence_end": _LATIN_END,
           "keywords": ("chapter", "part", "section", "book",
                        "introduction", "conclusion", "foreword",
                        "appendix", "preface")},
    "fr": {"script": "latin", "max_title_len": 120, "use_case": True,
           "sentence_end": _LATIN_END,
           "keywords": ("chapitre", "partie", "section", "livre",
                        "introduction", "conclusion", "avant-propos",
                        "annexe", "preface")},
    "es": {"script": "latin", "max_title_len": 120, "use_case": True,
           "sentence_end": _LATIN_END,
           "keywords": ("capitulo", "parte", "seccion", "libro",
                        "introduccion", "conclusion", "prologo",
                        "apendice", "prefacio")},
    "de": {"script": "latin", "max_title_len": 120, "use_case": True,
           "sentence_end": _LATIN_END,
           "keywords": ("kapitel", "teil", "abschnitt", "buch",
                        "einleitung", "schluss", "vorwort", "anhang")},
    "pt": {"script": "latin", "max_title_len": 120, "use_case": True,
           "sentence_end": _LATIN_END,
           "keywords": ("capitulo", "parte", "seccao", "livro",
                        "introducao", "conclusao", "prefacio", "apendice")},
    "nl": {"script": "latin", "max_title_len": 120, "use_case": True,
           "sentence_end": _LATIN_END,
           "keywords": ("hoofdstuk", "deel", "sectie", "boek",
                        "inleiding", "conclusie", "voorwoord", "bijlage")},
    "pl": {"script": "latin", "max_title_len": 120, "use_case": True,
           "sentence_end": _LATIN_END,
           "keywords": ("rozdzial", "czesc", "sekcja", "wstep",
                        "zakonczenie", "dodatek")},
    # profili per classe di script: usati quando la lingua esatta non è nota
    "latin": {"script": "latin", "max_title_len": 120, "use_case": True,
              "sentence_end": _LATIN_END, "keywords": ()},
    "cyrillic": {"script": "cyrillic", "max_title_len": 120, "use_case": True,
                 "sentence_end": _LATIN_END,
                 "keywords": ("глава", "часть", "раздел", "введение",
                              "заключение")},
    "greek": {"script": "greek", "max_title_len": 120, "use_case": True,
              "sentence_end": (".", "!", ";", ":"),
              "keywords": ("κεφάλαιο", "μέρος", "εισαγωγή")},
    "cjk": {"script": "cjk", "max_title_len": 40, "use_case": False,
            "sentence_end": ("。", "！", "？", "．", "."),
            "keywords": ("章", "節", "节", "部", "序", "前言", "结论")},
    "arabic": {"script": "arabic", "max_title_len": 120, "use_case": False,
               "sentence_end": ("۔", ".", "؟", "!"),
               "keywords": ("الفصل", "الباب", "القسم", "مقدمة", "خاتمة")},
    "hebrew": {"script": "hebrew", "max_title_len": 120, "use_case": False,
               "sentence_end": (".", "!", "?"),
               "keywords": ("פרק", "חלק", "מבוא")},
    "devanagari": {"script": "devanagari", "max_title_len": 120,
                   "use_case": False, "sentence_end": ("।", ".", "?", "!"),
                   "keywords": ("अध्याय", "भाग", "प्रस्तावना")},
    "generic": {"script": "unknown", "max_title_len": 120, "use_case": False,
                "sentence_end": _LATIN_END, "keywords": ()},
}

# lingue senza profilo dedicato ma con script noto: zh/ja/ko → cjk, ecc.
_LANG_TO_SCRIPT = {"zh": "cjk", "ja": "cjk", "ko": "cjk", "ru": "cyrillic",
                   "uk": "cyrillic", "bg": "cyrillic", "el": "greek",
                   "ar": "arabic", "fa": "arabic", "he": "hebrew",
                   "hi": "devanagari", "mr": "devanagari"}


def profile_for(lang, script):
    """Profilo euristico: lingua esatta → classe di script → generic."""
    lang = (lang or "").lower()[:2]
    if lang in LANG_PROFILES:
        return LANG_PROFILES[lang]
    key = _LANG_TO_SCRIPT.get(lang) or script
    if key in LANG_PROFILES:
        return LANG_PROFILES[key]
    return LANG_PROFILES["generic"]
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: PASS — 16 passed

- [ ] **Step 5: Checkpoint**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: suite verde. Nessun commit.

---

### Task 5: Linearizzazione in blocchi e calcolo delle feature

**Files:**
- Modify: `scripts/web_to_epub.py`
- Modify: `scripts/test_web_to_epub.py`
- Create: `scripts/fixtures_web_to_epub/vatican_like.html`

**Interfaces:**
- Consumes: `extract_container` (Task 2), `profile_for` (Task 4)
- Produces:
  - `@dataclass class Block` con campi: `tag: str`, `text: str`, `bold: bool`, `italic: bool`, `upper: bool`, `centered: bool`, `big_font: bool`, `length: int`, `ends_sentence: bool`, `numbered: bool`, `keyword: bool`, `level: int = 0`
  - `iter_blocks(container, profile) -> list[Block]`
  - `NUMBERING_PATTERNS: tuple[re.Pattern, ...]`

- [ ] **Step 1: Scrivere la fixture**

Creare `scripts/fixtures_web_to_epub/vatican_like.html`. Riproduce lo schema di vatican.va: nessun heading semantico, titoli in `<p><b>` maiuscolo, sottotitoli in `<p><b><i>`, marker di nota `[n]`, blocco note finale, indice interno con àncore.

```html
<!DOCTYPE html>
<html lang="it">
<head>
  <title>Lettera Enciclica Exemplum Fidei | Sito di Prova</title>
  <meta property="og:image" content="https://example.org/img/cover.jpg"/>
</head>
<body>
<div class="container">
  <p align="center"><b>LETTERA ENCICLICA</b></p>
  <p align="center"><b>EXEMPLUM FIDEI</b></p>
  <p align="center">DEL SANTO PADRE</p>

  <p><a href="#c1">CAPITOLO 1</a> - <a href="#c2">CAPITOLO 2</a></p>

  <p><b>INTRODUZIONE</b></p>
  <p>Questo e il paragrafo di apertura del documento di prova, scritto in
  italiano e sufficientemente lungo da non essere scambiato per un titolo
  dalla euristica di rilevamento.[1]</p>

  <p><b>CAPITOLO 1</b></p>
  <p><b>UN PENSIERO DINAMICO</b></p>
  <p>Il corpo del primo capitolo si estende per alcune righe e contiene una
  citazione con nota a pie di pagina.[2] Il testo prosegue oltre il marker
  per verificare che la rimozione non tronchi il paragrafo.</p>

  <p><b><i>La prima articolazione</i></b></p>
  <p>Corpo del primo sottocapitolo, abbastanza lungo da non essere confuso
  con un titolo dalla soglia di lunghezza del profilo italiano.</p>

  <p><b><i>La seconda articolazione</i></b></p>
  <p>Corpo del secondo sottocapitolo, anch esso di lunghezza adeguata per
  il riconoscimento corretto da parte della euristica.</p>

  <p><b>CAPITOLO 2</b></p>
  <p>Corpo del secondo capitolo, privo di sottocapitoli, con lunghezza
  sufficiente a essere classificato come corpo del testo.</p>

  <p><b>NOTE</b></p>
  <p>[1] Prima nota di riferimento del documento di prova.</p>
  <p>[2] Seconda nota di riferimento del documento di prova.</p>
</div>
</body>
</html>
```

- [ ] **Step 2: Scrivere il test che fallisce**

Aggiungere a `scripts/test_web_to_epub.py`:

```python
def blocks_of(fixture_name, lang="it"):
    container = w2e.extract_container(fixture(fixture_name))
    prof = w2e.profile_for(lang, "latin")
    return w2e.iter_blocks(container, prof)


def find_block(blocks, needle):
    for b in blocks:
        if needle.lower() in b.text.lower():
            return b
    raise AssertionError(f"blocco non trovato: {needle}")


def test_iter_blocks_computes_features_on_bold_uppercase_title():
    blocks = blocks_of("vatican_like.html")
    b = find_block(blocks, "CAPITOLO 1")

    assert b.bold is True
    assert b.upper is True
    assert b.numbered is True
    assert b.keyword is True
    assert b.ends_sentence is False
    assert b.length < 40


def test_iter_blocks_marks_body_paragraph_as_non_title():
    blocks = blocks_of("vatican_like.html")
    b = find_block(blocks, "paragrafo di apertura")

    assert b.bold is False
    assert b.upper is False
    assert b.ends_sentence is True
    assert b.length > 120


def test_iter_blocks_detects_italic_bold_subtitle():
    blocks = blocks_of("vatican_like.html")
    b = find_block(blocks, "La prima articolazione")

    assert b.bold is True
    assert b.italic is True
    assert b.upper is False


def test_iter_blocks_keeps_semantic_tag_names():
    container = w2e.extract_container(fixture("semantic.html"))
    prof = w2e.profile_for("en", "latin")
    blocks = w2e.iter_blocks(container, prof)

    assert find_block(blocks, "First Chapter").tag == "h2"
    assert find_block(blocks, "A Subsection").tag == "h3"


def test_iter_blocks_detects_cjk_numbering():
    container = w2e.extract_container(fixture("cjk.html"))
    prof = w2e.profile_for("zh", "cjk")
    blocks = w2e.iter_blocks(container, prof)
    b = find_block(blocks, "第一章")

    assert b.numbered is True
    assert b.keyword is True
    assert b.upper is False       # use_case=False per CJK


def test_iter_blocks_skips_empty_and_whitespace_nodes():
    html = "<html><body><main><p>  </p><p>&nbsp;</p><p>reale</p></main></body></html>"
    container = w2e.extract_container(html)
    blocks = w2e.iter_blocks(container, w2e.profile_for("it", "latin"))

    assert [b.text for b in blocks] == ["reale"]
```

- [ ] **Step 3: Eseguire i test e verificare che falliscano**

Run: `pytest scripts/test_web_to_epub.py -v -k iter_blocks`
Expected: FAIL — `AttributeError: module 'web_to_epub' has no attribute 'iter_blocks'`

- [ ] **Step 4: Implementazione minima**

Aggiungere a `scripts/web_to_epub.py`:

```python
# ------------------------------------------------------- blocchi e feature

from dataclasses import dataclass


@dataclass
class Block:
    """Un nodo di testo linearizzato, con le feature per il rilevamento."""
    tag: str
    text: str
    bold: bool = False
    italic: bool = False
    upper: bool = False
    centered: bool = False
    big_font: bool = False
    length: int = 0
    ends_sentence: bool = False
    numbered: bool = False
    keyword: bool = False
    level: int = 0          # 0=corpo, 1=capitolo, 2=sottocapitolo


NUMBERING_PATTERNS = (
    re.compile(r'^\s*[IVXLCDM]{1,7}\s*[.)–-]'),          # romana
    re.compile(r'^\s*\d{1,3}\s*[.)–-]'),                 # araba
    re.compile(r'^\s*[٠-٩]{1,3}\s*[.)]'),           # arabo-indiana
    re.compile(r'^\s*第\s*[一二三四五六七八九十百零\d]+\s*[章節节部]'),  # CJK
    re.compile(r'^\s*[一二三四五六七八九十]+\s*[、.]'),          # CJK elenco
    re.compile(r'\b(?:capitolo|chapter|chapitre|kapitel|capitulo|'
               r'rozdzial|hoofdstuk|глава)\s+[\dIVXLCDM]', re.I),
)

_BLOCK_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "li",
               "blockquote")

_EMPHASIS = {"b", "strong"}
_ITALIC = {"i", "em"}


def _is_wrapped_in(node, tags):
    """True se tutto il testo del nodo sta dentro tag di enfasi."""
    own = node.get_text(strip=True)
    if not own:
        return False
    inner = "".join(c.get_text(strip=True)
                    for c in node.find_all(list(tags), recursive=True))
    return len(inner) >= len(own) * 0.9


def _big_font(node):
    style = (node.get("style") or "").lower()
    m = re.search(r'font-size\s*:\s*([\d.]+)\s*(px|pt|em|rem|%)', style)
    if not m:
        return False
    val, unit = float(m.group(1)), m.group(2)
    thresholds = {"px": 18.0, "pt": 14.0, "em": 1.2, "rem": 1.2, "%": 120.0}
    return val >= thresholds[unit]


def _centered(node):
    if (node.get("align") or "").lower() == "center":
        return True
    return "text-align:center" in (node.get("style") or "").replace(" ", "")


def iter_blocks(container, profile):
    """Linearizza il contenitore in blocchi con le feature calcolate."""
    blocks = []
    for node in container.find_all(_BLOCK_TAGS):
        # salta i contenitori che contengono altri blocchi: si prende il
        # nodo foglia, altrimenti il testo verrebbe duplicato
        if node.find(_BLOCK_TAGS):
            continue
        text = re.sub(r'\s+', ' ', node.get_text(" ", strip=True)).strip()
        text = text.replace("\xa0", " ").strip()
        if not text:
            continue

        low = text.lower()
        blocks.append(Block(
            tag=node.name,
            text=text,
            bold=_is_wrapped_in(node, _EMPHASIS),
            italic=_is_wrapped_in(node, _ITALIC),
            upper=(profile["use_case"] and text.upper() == text
                   and any(c.isalpha() for c in text)),
            centered=_centered(node),
            big_font=_big_font(node),
            length=len(text),
            ends_sentence=text.endswith(profile["sentence_end"]),
            numbered=any(rx.search(text) for rx in NUMBERING_PATTERNS),
            keyword=any(k in low for k in profile["keywords"]),
        ))
    return blocks
```

- [ ] **Step 5: Eseguire i test e verificare che passino**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: PASS — 22 passed

- [ ] **Step 6: Checkpoint**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: suite verde. Nessun commit.

---

### Task 6: Assegnazione dei livelli — semantica ed euristica

**Files:**
- Modify: `scripts/web_to_epub.py`
- Modify: `scripts/test_web_to_epub.py`

**Interfaces:**
- Consumes: `Block`, `iter_blocks` (Task 5), `profile_for` (Task 4)
- Produces:
  - `assign_levels(blocks, profile) -> str` — muta `Block.level` in loco, ritorna la strategia usata: `"semantic"` o `"heuristic"`
  - `score_block(block, profile) -> int`

- [ ] **Step 1: Scrivere il test che fallisce**

Aggiungere a `scripts/test_web_to_epub.py`:

```python
def test_assign_levels_uses_semantic_headings_when_present():
    container = w2e.extract_container(fixture("semantic.html"))
    prof = w2e.profile_for("en", "latin")
    blocks = w2e.iter_blocks(container, prof)

    strategy = w2e.assign_levels(blocks, prof)

    assert strategy == "semantic"
    assert find_block(blocks, "First Chapter").level == 1
    assert find_block(blocks, "Second Chapter").level == 1
    assert find_block(blocks, "A Subsection").level == 2
    assert find_block(blocks, "Another Subsection").level == 2
    assert find_block(blocks, "first chapter body text").level == 0


def test_assign_levels_falls_back_to_heuristic_on_dirty_html():
    prof = w2e.profile_for("it", "latin")
    blocks = blocks_of("vatican_like.html")

    strategy = w2e.assign_levels(blocks, prof)

    assert strategy == "heuristic"
    assert find_block(blocks, "CAPITOLO 1").level == 1
    assert find_block(blocks, "CAPITOLO 2").level == 1
    assert find_block(blocks, "INTRODUZIONE").level == 1
    assert find_block(blocks, "La prima articolazione").level == 2
    assert find_block(blocks, "La seconda articolazione").level == 2
    assert find_block(blocks, "paragrafo di apertura").level == 0


def test_assign_levels_never_emits_a_third_level():
    html = ("<html><body><main>"
            "<h1>A</h1><p>x</p><h2>B</h2><p>y</p>"
            "<h3>C</h3><p>z</p><h4>D</h4><p>w</p>"
            "</main></body></html>")
    container = w2e.extract_container(html)
    prof = w2e.profile_for("en", "latin")
    blocks = w2e.iter_blocks(container, prof)

    w2e.assign_levels(blocks, prof)

    assert {b.level for b in blocks} <= {0, 1, 2}
    assert find_block(blocks, "C").level == 0    # h3 degradato a corpo
    assert find_block(blocks, "D").level == 0


def test_assign_levels_respects_cjk_title_length_threshold():
    prof = w2e.profile_for("zh", "cjk")
    container = w2e.extract_container(fixture("cjk.html"))
    blocks = w2e.iter_blocks(container, prof)

    w2e.assign_levels(blocks, prof)

    assert find_block(blocks, "第一章").level == 1
    assert find_block(blocks, "这是第一章的正文").level == 0


def test_long_bold_paragraph_is_not_a_title():
    prof = w2e.profile_for("it", "latin")
    b = w2e.Block(tag="p", text="x" * 300, bold=True, upper=True,
                  length=300, ends_sentence=False)

    assert w2e.score_block(b, prof) == 0
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest scripts/test_web_to_epub.py -v -k "assign_levels or score_block"`
Expected: FAIL — `AttributeError: module 'web_to_epub' has no attribute 'assign_levels'`

- [ ] **Step 3: Implementazione minima**

Aggiungere a `scripts/web_to_epub.py`:

```python
# ------------------------------------------------------- outline: livelli

_SEMANTIC_TAGS = ("h1", "h2", "h3")


def score_block(block, profile):
    """Punteggio di 'titolosità'. 0 se il blocco non può essere un titolo."""
    if not block.length or block.length > profile["max_title_len"]:
        return 0
    score = 0
    if block.bold:
        score += 2
    if block.upper:
        score += 2
    if block.numbered:
        score += 2
    if block.keyword:
        score += 2
    if not block.ends_sentence:
        score += 1
    if block.centered:
        score += 1
    if block.big_font:
        score += 1
    return score


def assign_levels(blocks, profile):
    """Assegna Block.level in loco. Ritorna 'semantic' o 'heuristic'."""
    heads = [b for b in blocks if b.tag in _SEMANTIC_TAGS]
    if len(heads) >= 2:
        present = [t for t in _SEMANTIC_TAGS
                   if any(b.tag == t for b in heads)]
        top = present[0]
        second = present[1] if len(present) > 1 else None
        for b in blocks:
            if b.tag == top:
                b.level = 1
            elif second and b.tag == second:
                b.level = 2
            else:
                b.level = 0          # h3+ residui degradati a corpo
        return "semantic"

    for b in blocks:
        s = score_block(b, profile)
        b.level = 1 if s >= 5 else (2 if s >= 3 else 0)
    return "heuristic"
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: PASS — 27 passed

Se `test_assign_levels_falls_back_to_heuristic_on_dirty_html` fallisce su un blocco specifico, ispezionare le feature con:

```python
for b in blocks_of("vatican_like.html"):
    print(b.level, w2e.score_block(b, w2e.profile_for("it", "latin")), b.text[:40])
```

e ricalibrare **solo le soglie** in `assign_levels` (5 e 3), non i pesi in `score_block`.

- [ ] **Step 5: Checkpoint**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: suite verde. Nessun commit.

---

### Task 7: Classificazione LLM opzionale

**Files:**
- Modify: `scripts/web_to_epub.py`
- Modify: `scripts/test_web_to_epub.py`

**Interfaces:**
- Consumes: `Block` (Task 5), `assign_levels` (Task 6)
- Produces:
  - `make_llm_classifier() -> callable | None` — costruisce il callable che parla con l'LLM via `translation_core`; ritorna `None` se l'LLM non è configurato
  - `llm_assign_levels(blocks, classifier, *, batch_size=200) -> bool` — sovrascrive `Block.level` con il verdetto LLM; ritorna `False` (e lascia i livelli invariati) se il classifier fallisce
  - `make_llm_language_detector() -> callable | None` — il callable `(sample) -> str|None` atteso da `detect_language`
  - `LLM_SYSTEM_PROMPT: str`

- [ ] **Step 1: Scrivere il test che fallisce**

Aggiungere a `scripts/test_web_to_epub.py`:

```python
import json


def sample_blocks():
    return [
        w2e.Block(tag="p", text="CAPITOLO 1", bold=True, upper=True,
                  length=10, numbered=True),
        w2e.Block(tag="p", text="Una articolazione", bold=True, length=17),
        w2e.Block(tag="p", text="Corpo del testo lungo " * 5, length=110,
                  ends_sentence=True),
    ]


def test_llm_assign_levels_applies_returned_levels():
    seen = {}

    def classifier(payload):
        seen["payload"] = payload
        return json.dumps({"0": 1, "1": 2, "2": 0})

    blocks = sample_blocks()
    ok = w2e.llm_assign_levels(blocks, classifier)

    assert ok is True
    assert [b.level for b in blocks] == [1, 2, 0]
    # il payload contiene solo i candidati compatti, mai il testo integrale
    assert "Corpo del testo lungo Corpo del testo lungo Corpo" not in seen["payload"]
    assert "CAPITOLO 1" in seen["payload"]


def test_llm_assign_levels_returns_false_on_error_and_keeps_levels():
    def classifier(_payload):
        raise RuntimeError("provider down")

    blocks = sample_blocks()
    for b in blocks:
        b.level = 9        # sentinella: non deve essere toccata

    ok = w2e.llm_assign_levels(blocks, classifier)

    assert ok is False
    assert [b.level for b in blocks] == [9, 9, 9]


def test_llm_assign_levels_rejects_malformed_json():
    blocks = sample_blocks()
    ok = w2e.llm_assign_levels(blocks, lambda _p: "non e json")

    assert ok is False


def test_llm_assign_levels_clamps_out_of_range_levels():
    blocks = sample_blocks()
    ok = w2e.llm_assign_levels(blocks, lambda _p: json.dumps({"0": 7, "1": 2,
                                                              "2": 0}))

    assert ok is True
    assert blocks[0].level == 0      # 7 non valido → corpo


def test_llm_assign_levels_batches_large_inputs():
    payloads = []

    def classifier(payload):
        payloads.append(payload)
        data = json.loads(payload)
        return json.dumps({str(item["i"]): 0 for item in data})

    blocks = [w2e.Block(tag="p", text=f"t{i}", length=3) for i in range(450)]
    ok = w2e.llm_assign_levels(blocks, classifier, batch_size=200)

    assert ok is True
    assert len(payloads) == 3
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest scripts/test_web_to_epub.py -v -k llm_assign`
Expected: FAIL — `AttributeError: module 'web_to_epub' has no attribute 'llm_assign_levels'`

- [ ] **Step 3: Implementazione minima**

Aggiungere a `scripts/web_to_epub.py`:

```python
# ------------------------------------------------------------- LLM (opt-in)

import json

LLM_SYSTEM_PROMPT = (
    "Sei un classificatore di struttura documentale. Ricevi un array JSON di "
    "candidati-titolo estratti da una pagina web, ciascuno con le sue "
    "caratteristiche tipografiche. Assegna a ognuno un livello: 1 = titolo di "
    "capitolo, 2 = titolo di sottocapitolo, 0 = testo di corpo. "
    "Non esistono livelli oltre il 2. "
    "Rispondi ESCLUSIVAMENTE con un oggetto JSON {\"indice\": livello}, "
    "senza commenti e senza blocchi di codice."
)

LLM_LANG_PROMPT = (
    "Identifica la lingua del testo. Rispondi con il solo codice ISO 639-1 "
    "di due lettere, in minuscolo, senza altro testo."
)


def _llm_pieces():
    """Ritorna (call_llm, provider, model, UsageTracker) o None se l'LLM
    non e configurato. Import locale: translation_core e opzionale."""
    try:
        import translation_core as tc
    except Exception:
        return None
    if not tc.is_available():
        return None
    try:
        provider, model, _base = tc.make_client_provider(tc.resolve_backend())
    except Exception:
        return None
    return tc, provider, model


def make_llm_classifier():
    """Callable (payload_json) -> testo di risposta. None se LLM assente."""
    pieces = _llm_pieces()
    if pieces is None:
        return None
    tc, provider, model = pieces

    def classify(payload):
        return tc.call_llm(provider, LLM_SYSTEM_PROMPT, payload,
                           model=model, usage=tc.UsageTracker(),
                           label="w2e-outline", log=lambda *_a, **_k: None)

    return classify


def make_llm_language_detector():
    """Callable (sample) -> codice lingua. None se LLM assente."""
    pieces = _llm_pieces()
    if pieces is None:
        return None
    tc, provider, model = pieces

    def detect(sample):
        try:
            out = tc.call_llm(provider, LLM_LANG_PROMPT, sample,
                              model=model, usage=tc.UsageTracker(),
                              label="w2e-lang", log=lambda *_a, **_k: None)
            m = re.search(r'[a-z]{2}', out.strip().lower())
            return m.group(0) if m else None
        except Exception:
            return None

    return detect


def _candidate_payload(blocks, indices):
    items = []
    for i in indices:
        b = blocks[i]
        items.append({"i": i, "text": b.text[:120], "tag": b.tag,
                      "bold": b.bold, "upper": b.upper, "len": b.length,
                      "numbered": b.numbered})
    return json.dumps(items, ensure_ascii=False)


def llm_assign_levels(blocks, classifier, *, batch_size=200):
    """Sovrascrive i livelli col verdetto LLM. False se qualcosa fallisce
    (in tal caso i livelli restano quelli calcolati dall'euristica)."""
    indices = list(range(len(blocks)))
    verdict = {}
    for start in range(0, len(indices), batch_size):
        chunk = indices[start:start + batch_size]
        try:
            raw = classifier(_candidate_payload(blocks, chunk))
            data = json.loads(raw)
        except Exception:
            return False
        if not isinstance(data, dict):
            return False
        verdict.update(data)

    for key, lvl in verdict.items():
        try:
            i = int(key)
            lvl = int(lvl)
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(blocks):
            blocks[i].level = lvl if lvl in (0, 1, 2) else 0
    return True
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: PASS — 32 passed

- [ ] **Step 5: Checkpoint**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: suite verde. Nessun commit.

---

### Task 8: Assemblaggio dell'outline e gestione note

**Files:**
- Modify: `scripts/web_to_epub.py`
- Modify: `scripts/test_web_to_epub.py`

**Interfaces:**
- Consumes: `Block` (Task 5), `assign_levels` (Task 6)
- Produces:
  - `strip_notes(blocks, profile) -> list[Block]` — rimuove i marker `[n]` inline e i blocchi-nota; ritorna la lista filtrata
  - `build_outline(blocks, *, intro_title="Introduzione") -> list[dict]` — struttura: `[{"title": str, "text": str, "subs": [{"title": str, "text": str}]}]`
  - `NOTE_LINE_RE`, `NOTE_MARKER_RE`

- [ ] **Step 1: Scrivere il test che fallisce**

Aggiungere a `scripts/test_web_to_epub.py`:

```python
def test_strip_notes_removes_markers_without_truncating_text():
    prof = w2e.profile_for("it", "latin")
    blocks = blocks_of("vatican_like.html")

    cleaned = w2e.strip_notes(blocks, prof)
    body = find_block(cleaned, "Il corpo del primo capitolo")

    assert "[2]" not in body.text
    assert "Il testo prosegue oltre il marker" in body.text


def test_strip_notes_drops_note_lines_and_note_heading():
    prof = w2e.profile_for("it", "latin")
    cleaned = w2e.strip_notes(blocks_of("vatican_like.html"), prof)
    texts = [b.text for b in cleaned]

    assert not any(t.startswith("[1] Prima nota") for t in texts)
    assert not any(t.startswith("[2] Seconda nota") for t in texts)
    assert "NOTE" not in texts


def test_build_outline_nests_subchapters_under_chapters():
    prof = w2e.profile_for("it", "latin")
    blocks = w2e.strip_notes(blocks_of("vatican_like.html"), prof)
    w2e.assign_levels(blocks, prof)

    outline = w2e.build_outline(blocks)
    titles = [c["title"] for c in outline]

    assert "CAPITOLO 1" in titles
    cap1 = next(c for c in outline if c["title"] == "CAPITOLO 1")
    assert [s["title"] for s in cap1["subs"]] == ["La prima articolazione",
                                                  "La seconda articolazione"]
    assert "Corpo del primo sottocapitolo" in cap1["subs"][0]["text"]


def test_build_outline_creates_intro_chapter_for_leading_text():
    blocks = [
        w2e.Block(tag="p", text="Testo prima di ogni titolo.", level=0),
        w2e.Block(tag="p", text="CAPITOLO 1", level=1),
        w2e.Block(tag="p", text="Corpo.", level=0),
    ]
    outline = w2e.build_outline(blocks)

    assert outline[0]["title"] == "Introduzione"
    assert outline[0]["text"] == "Testo prima di ogni titolo."
    assert outline[1]["title"] == "CAPITOLO 1"


def test_build_outline_promotes_orphan_subchapter():
    blocks = [
        w2e.Block(tag="p", text="Sottotitolo orfano", level=2),
        w2e.Block(tag="p", text="Corpo.", level=0),
        w2e.Block(tag="p", text="CAPITOLO 1", level=1),
        w2e.Block(tag="p", text="Altro corpo.", level=0),
    ]
    outline = w2e.build_outline(blocks)

    assert outline[0]["title"] == "Sottotitolo orfano"
    assert outline[0]["subs"] == []
    assert outline[1]["title"] == "CAPITOLO 1"


def test_build_outline_single_chapter_when_no_titles():
    blocks = [w2e.Block(tag="p", text="Solo corpo, nessun titolo.", level=0)]
    outline = w2e.build_outline(blocks)

    assert len(outline) == 1
    assert outline[0]["title"] == "Introduzione"
    assert outline[0]["subs"] == []


def test_build_outline_joins_paragraphs_with_blank_lines():
    blocks = [
        w2e.Block(tag="p", text="CAP", level=1),
        w2e.Block(tag="p", text="Primo.", level=0),
        w2e.Block(tag="p", text="Secondo.", level=0),
    ]
    outline = w2e.build_outline(blocks)

    assert outline[0]["text"] == "Primo.\n\nSecondo."
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest scripts/test_web_to_epub.py -v -k "strip_notes or build_outline"`
Expected: FAIL — `AttributeError: module 'web_to_epub' has no attribute 'strip_notes'`

- [ ] **Step 3: Implementazione minima**

Aggiungere a `scripts/web_to_epub.py`:

```python
# ---------------------------------------------------- note e assemblaggio

NOTE_MARKER_RE = re.compile(r'\[\s*\d{1,3}\s*\]')
NOTE_LINE_RE = re.compile(r'^\s*\[\s*\d{1,3}\s*\]')

# intestazioni del blocco note nelle lingue supportate
_NOTE_HEADINGS = ("note", "notes", "notas", "anmerkungen", "przypisy",
                  "noten", "примечания", "注释", "注")


def strip_notes(blocks, profile):
    """Rimuove marker inline e blocchi-nota. Ritorna la lista filtrata."""
    out = []
    for b in blocks:
        if NOTE_LINE_RE.match(b.text):
            continue                       # riga di nota
        if (b.length <= 30
                and b.text.strip().strip(":").lower() in _NOTE_HEADINGS):
            continue                       # intestazione del blocco note
        b.text = re.sub(r'\s{2,}', ' ',
                        NOTE_MARKER_RE.sub('', b.text)).strip()
        b.length = len(b.text)
        if not b.text:
            continue
        out.append(b)
    return out


def build_outline(blocks, *, intro_title="Introduzione"):
    """Costruisce capitoli e sottocapitoli dai blocchi con livello assegnato.

    - il testo che precede il primo titolo diventa un capitolo introduttivo
    - un sottocapitolo che precede qualsiasi capitolo viene promosso
    """
    outline = []
    current_ch = None
    current_sub = None
    lead = []

    def new_chapter(title):
        ch = {"title": title, "text": "", "subs": [], "_buf": []}
        outline.append(ch)
        return ch

    for b in blocks:
        if b.level == 1:
            current_ch = new_chapter(b.text)
            current_sub = None
        elif b.level == 2:
            if current_ch is None:
                current_ch = new_chapter(b.text)   # orfano promosso
                current_sub = None
            else:
                current_sub = {"title": b.text, "text": "", "_buf": []}
                current_ch["subs"].append(current_sub)
        else:
            if current_ch is None:
                lead.append(b.text)
            elif current_sub is not None:
                current_sub["_buf"].append(b.text)
            else:
                current_ch["_buf"].append(b.text)

    if lead or not outline:
        intro = {"title": intro_title, "text": "\n\n".join(lead),
                 "subs": [], "_buf": []}
        outline.insert(0, intro)

    for ch in outline:
        ch["text"] = ch["text"] or "\n\n".join(ch.pop("_buf", []))
        ch.pop("_buf", None)
        for sub in ch["subs"]:
            sub["text"] = "\n\n".join(sub.pop("_buf", []))
    return outline
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: PASS — 39 passed

- [ ] **Step 5: Checkpoint**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: suite verde. Nessun commit.

---

### Task 9: Writer EPUB con TOC annidata

**Files:**
- Modify: `scripts/web_to_epub.py`
- Modify: `scripts/test_web_to_epub.py`

**Interfaces:**
- Consumes: `build_outline` (Task 8)
- Produces:
  - `write_epub_nested(out_path, meta, outline, cover=None) -> None` — `meta` è `{"title": str, "author": str, "language": str, "source": str}`; `cover` è `(bytes, filename)` o `None`
  - `_stable_identifier(source_url) -> str`

- [ ] **Step 1: Scrivere il test che fallisce**

Aggiungere a `scripts/test_web_to_epub.py`:

```python
def demo_outline():
    return [
        {"title": "Capitolo 1", "text": "Corpo uno.\n\nCorpo due.",
         "subs": [{"title": "Sotto 1.1", "text": "Testo 1.1"},
                  {"title": "Sotto 1.2", "text": "Testo 1.2"}]},
        {"title": "Capitolo 2", "text": "Corpo tre.", "subs": []},
    ]


def demo_meta():
    return {"title": "Libro di prova", "author": "Autore Test",
            "language": "it", "source": "https://example.org/doc.html"}


def test_write_epub_nested_produces_two_level_toc(tmp_path):
    from ebooklib import epub

    out = tmp_path / "libro.epub"
    w2e.write_epub_nested(out, demo_meta(), demo_outline())
    book = epub.read_epub(str(out))

    assert out.exists()
    top = book.toc
    assert len(top) == 2
    section, children = top[0]
    assert section.title == "Capitolo 1"
    assert [c.title for c in children] == ["Sotto 1.1", "Sotto 1.2"]
    assert top[1].title == "Capitolo 2"


def test_write_epub_nested_spine_is_in_reading_order(tmp_path):
    from ebooklib import epub

    out = tmp_path / "libro.epub"
    w2e.write_epub_nested(out, demo_meta(), demo_outline())
    book = epub.read_epub(str(out))

    names = [item[0] if isinstance(item, tuple) else item
             for item in book.spine]
    assert names[0] == "nav"
    assert len(names) == 5      # nav + 2 capitoli + 2 sottocapitoli


def test_write_epub_nested_escapes_html_in_titles(tmp_path):
    from ebooklib import epub
    import ebooklib

    outline = [{"title": "A <b>&</b> B", "text": "corpo", "subs": []}]
    out = tmp_path / "esc.epub"
    w2e.write_epub_nested(out, demo_meta(), outline)
    book = epub.read_epub(str(out))

    docs = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    content = b"".join(d.get_content() for d in docs).decode("utf-8")
    assert "&lt;b&gt;" in content


def test_stable_identifier_is_deterministic():
    a = w2e._stable_identifier("https://example.org/doc.html")
    b = w2e._stable_identifier("https://example.org/doc.html")
    c = w2e._stable_identifier("https://example.org/other.html")

    assert a == b
    assert a != c
    assert a.startswith("urn:uuid:")


def test_write_epub_nested_sets_metadata(tmp_path):
    from ebooklib import epub

    out = tmp_path / "meta.epub"
    w2e.write_epub_nested(out, demo_meta(), demo_outline())
    book = epub.read_epub(str(out))

    assert book.get_metadata("DC", "title")[0][0] == "Libro di prova"
    assert book.get_metadata("DC", "creator")[0][0] == "Autore Test"
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest scripts/test_web_to_epub.py -v -k epub`
Expected: FAIL — `AttributeError: module 'web_to_epub' has no attribute 'write_epub_nested'`

- [ ] **Step 3: Implementazione minima**

Aggiungere a `scripts/web_to_epub.py`:

```python
# ------------------------------------------------------------ writer EPUB

import hashlib
import html as _html
import uuid


def _stable_identifier(source_url):
    """UUID deterministico: la stessa URL produce sempre lo stesso ID."""
    digest = hashlib.sha256((source_url or "").encode("utf-8")).digest()
    return "urn:uuid:" + str(uuid.UUID(bytes=digest[:16]))


def _xhtml(title, text, heading_tag):
    esc = _html.escape(title)
    paras = [p.strip() for p in re.split(r'\n\s*\n', text or "") if p.strip()]
    body = "\n".join(f"<p>{_html.escape(p)}</p>" for p in paras)
    return (f"<html><head><title>{esc}</title></head>"
            f"<body><{heading_tag}>{esc}</{heading_tag}>{body}</body></html>")


def write_epub_nested(out_path, meta, outline, cover=None):
    """Scrive l'EPUB con TOC a due livelli (capitoli + sottocapitoli)."""
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier(_stable_identifier(meta.get("source", "")))
    book.set_title(meta.get("title") or "Untitled")
    book.set_language(meta.get("language") or "en")
    if meta.get("author"):
        book.add_author(meta["author"])
    book.add_metadata("DC", "contributor", "Audiobook Maker web_to_epub")
    if meta.get("source"):
        book.add_metadata("DC", "source", meta["source"])

    if cover:
        data, orig_name = cover
        ext = ".png" if str(orig_name).lower().endswith(".png") else ".jpg"
        book.set_cover(f"cover{ext}", data)

    toc = []
    spine_items = []
    for ci, ch in enumerate(outline, start=1):
        item = epub.EpubHtml(title=ch["title"],
                             file_name=f"ch_{ci:03d}.xhtml",
                             lang=meta.get("language") or "en")
        item.content = _xhtml(ch["title"], ch.get("text", ""), "h1")
        book.add_item(item)
        spine_items.append(item)

        children = []
        for si, sub in enumerate(ch.get("subs", []), start=1):
            sit = epub.EpubHtml(title=sub["title"],
                                file_name=f"ch_{ci:03d}_{si:02d}.xhtml",
                                lang=meta.get("language") or "en")
            sit.content = _xhtml(sub["title"], sub.get("text", ""), "h2")
            book.add_item(sit)
            spine_items.append(sit)
            children.append(sit)

        if children:
            section = epub.Section(ch["title"], href=item.file_name)
            toc.append((section, children))
        else:
            toc.append(item)

    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + spine_items
    epub.write_epub(str(out_path), book)
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: PASS — 45 passed

- [ ] **Step 5: Checkpoint**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: suite verde. Nessun commit.

---

### Task 10: Metadati, cover, crawl e robots

**Files:**
- Modify: `scripts/web_to_epub.py`
- Modify: `scripts/test_web_to_epub.py`

**Interfaces:**
- Consumes: `fetch_page` (Task 1), `extract_container` (Task 2)
- Produces:
  - `extract_meta(html, url, container) -> dict` — `{"title", "author", "cover_url"}`
  - `collect_links(container, page_url, start_url) -> list[str]` — link interni al documento, deduplicati, in ordine di apparizione
  - `crawl(start_url, *, follow=False, max_pages=50, fetcher=fetch_page, robots=None, sleep=time.sleep, log=print) -> list[tuple[str, str]]` — lista `(url, html)`; `robots` è un callable `(url) -> bool` (True = consentito)
  - `make_robots_checker(start_url, *, fetcher=fetch_page) -> callable`

- [ ] **Step 1: Scrivere il test che fallisce**

Aggiungere a `scripts/test_web_to_epub.py`:

```python
def test_extract_meta_prefers_og_title_and_author():
    html = fixture("semantic.html")
    container = w2e.extract_container(html)

    meta = w2e.extract_meta(html, "https://example.org/doc.html", container)

    assert meta["title"] == "The Sample Document"
    assert meta["author"] == "Jane Doe"


def test_extract_meta_cleans_title_suffix_when_no_og_title():
    html = fixture("vatican_like.html")
    container = w2e.extract_container(html)

    meta = w2e.extract_meta(html, "https://example.org/doc.html", container)

    assert meta["title"] == "Lettera Enciclica Exemplum Fidei"
    assert meta["cover_url"] == "https://example.org/img/cover.jpg"


def test_extract_meta_falls_back_to_host_for_author():
    html = "<html><head><title>T</title></head><body><p>x</p></body></html>"
    container = w2e.extract_container(html)

    meta = w2e.extract_meta(html, "https://www.example.org/a/b.html",
                            container)

    assert meta["author"] == "www.example.org"


def test_collect_links_keeps_only_same_directory_documents():
    html = ("<html><body><main>"
            "<a href='part2.html'>due</a>"
            "<a href='/other/part9.html'>fuori</a>"
            "<a href='https://altro.org/x.html'>esterno</a>"
            "<a href='#anchor'>ancora</a>"
            "<a href='part2.html'>duplicato</a>"
            "<a href='part3.html'>tre</a>"
            "</main></body></html>")
    container = w2e.extract_container(html)
    start = "https://example.org/docs/part1.html"

    links = w2e.collect_links(container, start, start)

    assert links == ["https://example.org/docs/part2.html",
                     "https://example.org/docs/part3.html"]


def test_collect_links_excludes_language_variants():
    html = ("<html><body><main>"
            "<a href='/docs/en/part2.html'>en</a>"
            "<a href='part2.html'>ok</a>"
            "</main></body></html>")
    container = w2e.extract_container(html)
    start = "https://example.org/docs/it/part1.html"

    links = w2e.collect_links(container, start, start)

    assert links == ["https://example.org/docs/it/part2.html"]


def test_crawl_without_follow_fetches_only_start_page():
    calls = []

    def fetcher(url, **_kw):
        calls.append(url)
        return "<html><body><main><p>solo questa</p></main></body></html>"

    pages = w2e.crawl("https://example.org/docs/a.html", fetcher=fetcher,
                      sleep=lambda _s: None)

    assert len(pages) == 1
    assert calls == ["https://example.org/docs/a.html"]


def test_crawl_follows_links_and_respects_max_pages():
    pages_html = {
        "https://example.org/d/a.html":
            "<html><body><main><a href='b.html'>b</a>"
            "<a href='c.html'>c</a><p>A</p></main></body></html>",
        "https://example.org/d/b.html":
            "<html><body><main><p>B</p></main></body></html>",
        "https://example.org/d/c.html":
            "<html><body><main><p>C</p></main></body></html>",
    }

    def fetcher(url, **_kw):
        return pages_html[url]

    pages = w2e.crawl("https://example.org/d/a.html", follow=True,
                      max_pages=2, fetcher=fetcher, sleep=lambda _s: None)

    assert [u for u, _h in pages] == ["https://example.org/d/a.html",
                                      "https://example.org/d/b.html"]


def test_crawl_skips_unreachable_pages_and_continues():
    def fetcher(url, **_kw):
        if url.endswith("b.html"):
            raise w2e.FetchError("boom")
        if url.endswith("a.html"):
            return ("<html><body><main><a href='b.html'>b</a>"
                    "<a href='c.html'>c</a><p>A</p></main></body></html>")
        return "<html><body><main><p>C</p></main></body></html>"

    pages = w2e.crawl("https://example.org/d/a.html", follow=True,
                      fetcher=fetcher, sleep=lambda _s: None)

    assert [u for u, _h in pages] == ["https://example.org/d/a.html",
                                      "https://example.org/d/c.html"]


def test_crawl_honours_robots_checker():
    def fetcher(url, **_kw):
        if url.endswith("a.html"):
            return ("<html><body><main><a href='b.html'>b</a><p>A</p>"
                    "</main></body></html>")
        return "<html><body><main><p>B</p></main></body></html>"

    pages = w2e.crawl("https://example.org/d/a.html", follow=True,
                      fetcher=fetcher, sleep=lambda _s: None,
                      robots=lambda url: not url.endswith("b.html"))

    assert [u for u, _h in pages] == ["https://example.org/d/a.html"]
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest scripts/test_web_to_epub.py -v -k "meta or links or crawl"`
Expected: FAIL — `AttributeError: module 'web_to_epub' has no attribute 'extract_meta'`

- [ ] **Step 3: Implementazione minima**

Aggiungere a `scripts/web_to_epub.py`:

```python
# --------------------------------------------------- metadati, crawl, robots

from urllib.parse import urljoin, urlparse

_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
    re.I)
_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.I)
_AUTHOR_RE = re.compile(
    r'<meta[^>]+name=["\']author["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_SITE_NAME_RE = re.compile(
    r'<meta[^>]+property=["\']og:site_name["\'][^>]+'
    r'content=["\']([^"\']+)["\']', re.I)
_TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)

# codici lingua usati nei path dei siti multilingua
_LANG_SEGMENTS = {"it", "en", "fr", "es", "de", "pt", "nl", "pl", "zh", "ru",
                  "ar", "he", "hi", "ja", "ko", "la", "el"}


def _clean_title(raw):
    """Rimuove il suffisso del sito: 'Titolo | Sito' → 'Titolo'."""
    txt = re.sub(r'\s+', ' ', _html.unescape(raw or "")).strip()
    for sep in (" | ", " - ", " — ", " :: "):
        if sep in txt:
            head = txt.split(sep)[0].strip()
            if len(head) >= 8:
                return head
    return txt


def extract_meta(html, url, container):
    """Titolo, autore e URL di copertina secondo la cascata dello spec."""
    m = _OG_TITLE_RE.search(html or "")
    title = _clean_title(m.group(1)) if m else ""
    if not title:
        h1 = container.find(["h1", "h2"])
        if h1:
            title = _clean_title(h1.get_text(" ", strip=True))
    if not title:
        m = _TITLE_RE.search(html or "")
        title = _clean_title(m.group(1)) if m else ""

    m = _AUTHOR_RE.search(html or "")
    author = _html.unescape(m.group(1)).strip() if m else ""
    if not author:
        m = _SITE_NAME_RE.search(html or "")
        author = _html.unescape(m.group(1)).strip() if m else ""
    if not author:
        author = urlparse(url).netloc

    m = _OG_IMAGE_RE.search(html or "")
    cover_url = urljoin(url, _html.unescape(m.group(1))) if m else ""

    return {"title": title or "Untitled", "author": author,
            "cover_url": cover_url}


def _dir_of(url):
    p = urlparse(url)
    path = p.path.rsplit("/", 1)[0] + "/"
    return p.scheme, p.netloc, path


def collect_links(container, page_url, start_url):
    """Link interni al documento: stesso host, stessa directory di partenza,
    nessuna àncora, nessuna variante di lingua, deduplicati."""
    _s, host, base_dir = _dir_of(start_url)
    start_segments = {seg for seg in base_dir.strip("/").split("/")
                      if seg in _LANG_SEGMENTS}

    seen, out = set(), []
    for a in container.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:"):
            continue
        absolute = urljoin(page_url, href).split("#")[0]
        p = urlparse(absolute)
        if p.scheme not in ("http", "https") or p.netloc != host:
            continue
        if not p.path.startswith(base_dir):
            continue
        segments = {seg for seg in p.path.strip("/").split("/")
                    if seg in _LANG_SEGMENTS}
        if segments != start_segments:
            continue                       # variante di lingua
        if absolute == start_url or absolute in seen:
            continue
        seen.add(absolute)
        out.append(absolute)
    return out


def make_robots_checker(start_url, *, fetcher=fetch_page):
    """Ritorna (url) -> bool. In caso di robots.txt assente: tutto permesso."""
    from urllib.robotparser import RobotFileParser

    p = urlparse(start_url)
    rp = RobotFileParser()
    try:
        rp.parse(fetcher(f"{p.scheme}://{p.netloc}/robots.txt").splitlines())
    except Exception:
        return lambda _url: True
    return lambda url: rp.can_fetch(USER_AGENT, url)


def crawl(start_url, *, follow=False, max_pages=50, fetcher=fetch_page,
          robots=None, sleep=time.sleep, log=print):
    """Scarica la pagina di partenza ed eventualmente i link interni.

    Ritorna [(url, html)] nell'ordine di lettura. Le pagine irraggiungibili
    o negate da robots.txt vengono saltate con avviso.
    """
    pages = []
    queue = [start_url]
    visited = set()

    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        if robots and not robots(url):
            log(f"  robots.txt nega {url}: saltata")
            continue
        try:
            html = fetcher(url)
        except FetchError as e:
            if not pages:
                raise                      # la prima pagina è fatale
            log(f"  pagina non raggiungibile, saltata: {e}")
            continue
        pages.append((url, html))
        log(f"[{len(pages)}] {url}")

        if follow:
            container = extract_container(html)
            for link in collect_links(container, url, start_url):
                if link not in visited and link not in queue:
                    queue.append(link)
            if queue:
                sleep(1)
    return pages
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: PASS — 54 passed

- [ ] **Step 5: Checkpoint**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: suite verde. Nessun commit.

---

### Task 11: CLI dell'engine, dry-run ed exit code

**Files:**
- Modify: `scripts/web_to_epub.py`
- Modify: `scripts/test_web_to_epub.py`

**Interfaces:**
- Consumes: tutto quanto prodotto dai Task 1-10
- Produces:
  - `convert(start_url, *, out_path=None, follow=False, max_pages=50, use_llm=False, lang=None, title=None, author=None, cover_path=None, keep_notes=False, ignore_robots=False, dry_run=False, fetcher=fetch_page, cover_downloader=None, log=print) -> dict` — ritorna `{"outline": list, "meta": dict, "language": str, "strategy": str, "out_path": str|None}`. `cover_downloader` è un callable `(url) -> bytes|None` iniettabile: i test lo passano per non toccare la rete
  - `download_cover_bytes(url) -> bytes | None` — download reale della copertina, usato come default da `convert`
  - `main(argv=None) -> int` — exit code secondo lo spec
  - `EXIT_OK=0`, `EXIT_NETWORK=2`, `EXIT_EMPTY=3`, `EXIT_WRITE=4`

- [ ] **Step 1: Scrivere il test che fallisce**

Aggiungere a `scripts/test_web_to_epub.py`:

```python
def test_convert_end_to_end_on_dirty_html(tmp_path):
    from ebooklib import epub

    def fetcher(url, **_kw):
        return fixture("vatican_like.html")

    out = tmp_path / "enciclica.epub"
    res = w2e.convert("https://example.org/d/a.html", out_path=str(out),
                      fetcher=fetcher, cover_downloader=lambda _u: None,
                      log=lambda *_a: None)

    assert res["language"] == "it"
    assert res["strategy"] == "heuristic"
    titles = [c["title"] for c in res["outline"]]
    assert "CAPITOLO 1" in titles and "CAPITOLO 2" in titles

    book = epub.read_epub(str(out))
    section, children = next(t for t in book.toc if isinstance(t, tuple))
    assert section.title == "CAPITOLO 1"
    assert len(children) == 2


def test_convert_dry_run_writes_no_file(tmp_path):
    out = tmp_path / "nope.epub"
    res = w2e.convert("https://example.org/d/a.html", out_path=str(out),
                      dry_run=True,
                      fetcher=lambda _u, **_k: fixture("semantic.html"),
                      log=lambda *_a: None)

    assert not out.exists()
    assert res["out_path"] is None
    assert res["outline"]


def test_convert_keep_notes_preserves_note_chapter(tmp_path):
    res = w2e.convert("https://example.org/d/a.html", keep_notes=True,
                      dry_run=True,
                      fetcher=lambda _u, **_k: fixture("vatican_like.html"),
                      log=lambda *_a: None)

    flat = " ".join(c["text"] for c in res["outline"])
    flat += " ".join(s["text"] for c in res["outline"] for s in c["subs"])
    assert "Prima nota di riferimento" in flat


def test_convert_title_and_author_overrides(tmp_path):
    res = w2e.convert("https://example.org/d/a.html", dry_run=True,
                      title="Mio Titolo", author="Mio Autore",
                      fetcher=lambda _u, **_k: fixture("semantic.html"),
                      log=lambda *_a: None)

    assert res["meta"]["title"] == "Mio Titolo"
    assert res["meta"]["author"] == "Mio Autore"


def test_convert_single_chapter_when_no_titles_detected():
    html = ("<html><body><main><p>" + "testo di corpo. " * 40 +
            "</p></main></body></html>")
    res = w2e.convert("https://example.org/d/a.html", dry_run=True,
                      fetcher=lambda _u, **_k: html, log=lambda *_a: None)

    assert len(res["outline"]) == 1
    assert res["outline"][0]["title"] == "Introduzione"


def test_main_returns_network_exit_code(monkeypatch):
    def boom(*_a, **_kw):
        raise w2e.FetchError("host irraggiungibile")

    monkeypatch.setattr(w2e, "fetch_page", boom)
    code = w2e.main(["--url", "https://example.org/x.html", "--dry-run"])

    assert code == w2e.EXIT_NETWORK


def test_main_returns_empty_exit_code(monkeypatch):
    monkeypatch.setattr(w2e, "fetch_page",
                        lambda *_a, **_kw: "<html><body></body></html>")
    code = w2e.main(["--url", "https://example.org/x.html", "--dry-run"])

    assert code == w2e.EXIT_EMPTY


def test_main_dry_run_returns_ok(monkeypatch, capsys):
    monkeypatch.setattr(w2e, "fetch_page",
                        lambda *_a, **_kw: fixture("semantic.html"))
    code = w2e.main(["--url", "https://example.org/x.html", "--dry-run"])
    printed = capsys.readouterr().out

    assert code == w2e.EXIT_OK
    assert "First Chapter" in printed
    assert "A Subsection" in printed
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest scripts/test_web_to_epub.py -v -k "convert or main"`
Expected: FAIL — `AttributeError: module 'web_to_epub' has no attribute 'convert'`

- [ ] **Step 3: Implementazione minima**

Aggiungere a `scripts/web_to_epub.py`:

```python
# --------------------------------------------------------------------- CLI

import argparse
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_NETWORK = 2
EXIT_EMPTY = 3
EXIT_WRITE = 4


def _safe_name(text):
    out = re.sub(r'[\\/:*?"<>|]+', "_", (text or "libro").strip())
    return (out[:120] or "libro")


def download_cover_bytes(url):
    """Scarica l'immagine di copertina. None se non disponibile."""
    import requests
    r = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.content


def _load_cover(cover_path, cover_url, downloader, log):
    """Copertina da file locale o da URL. None se non ottenibile.

    `downloader` è iniettabile: i test passano una funzione che ritorna
    None, così nessun test tocca la rete.
    """
    if cover_path:
        p = Path(cover_path)
        try:
            return p.read_bytes(), p.name
        except OSError as e:
            log(f"  cover non leggibile ({e}): EPUB senza copertina")
            return None
    if not cover_url or downloader is None:
        return None
    try:
        data = downloader(cover_url)
    except Exception as e:  # noqa: BLE001
        log(f"  cover non scaricabile ({e}): EPUB senza copertina")
        return None
    if not data:
        return None
    return data, cover_url.rsplit("/", 1)[-1]


def convert(start_url, *, out_path=None, follow=False, max_pages=50,
            use_llm=False, lang=None, title=None, author=None,
            cover_path=None, keep_notes=False, ignore_robots=False,
            dry_run=False, fetcher=fetch_page, cover_downloader=None,
            log=print):
    """Pipeline completa. Vedi lo spec per la semantica dei parametri."""
    robots = None
    if follow and not ignore_robots:
        robots = make_robots_checker(start_url, fetcher=fetcher)

    pages = crawl(start_url, follow=follow, max_pages=max_pages,
                  fetcher=fetcher, robots=robots, log=log)

    first_url, first_html = pages[0]
    first_container = extract_container(first_html)
    meta = extract_meta(first_html, first_url, first_container)
    if title:
        meta["title"] = title
    if author:
        meta["author"] = author

    full_text = " ".join(extract_container(h).get_text(" ", strip=True)
                         for _u, h in pages)
    if not full_text.strip():
        raise ValueError("nessun contenuto testuale estratto")

    llm_lang = make_llm_language_detector() if use_llm else None
    language, source = detect_language(first_html, full_text,
                                       override=lang, llm=llm_lang)
    script = detect_script(full_text)
    profile = profile_for(language, script)
    log(f"lingua: {language or 'ignota'} (fonte: {source})")

    blocks = []
    for _u, html in pages:
        blocks.extend(iter_blocks(extract_container(html), profile))
    if not keep_notes:
        blocks = strip_notes(blocks, profile)
    if not blocks:
        raise ValueError("nessun blocco di testo dopo il filtraggio")

    strategy = assign_levels(blocks, profile)
    if use_llm:
        classifier = make_llm_classifier()
        if classifier is None:
            log("  LLM non configurato: euristica")
        elif llm_assign_levels(blocks, classifier):
            strategy = "llm"
        else:
            log("  LLM non disponibile o risposta non valida: euristica")

    outline = build_outline(blocks)
    n_sub = sum(len(c["subs"]) for c in outline)
    log(f"outline ({strategy}): {len(outline)} capitoli, {n_sub} sottocapitoli")
    if len(outline) == 1 and not n_sub:
        log("  attenzione: nessun titolo rilevato, EPUB a capitolo unico")

    meta_out = {"title": meta["title"], "author": meta["author"],
                "language": language or "en", "source": start_url}

    if dry_run:
        for ch in outline:
            log(f"- {ch['title']}")
            for sub in ch["subs"]:
                log(f"    - {sub['title']}")
        return {"outline": outline, "meta": meta_out, "language": language,
                "strategy": strategy, "out_path": None}

    dest = Path(out_path) if out_path else Path(
        f"{_safe_name(meta_out['title'])}.epub")
    cover = _load_cover(cover_path, meta.get("cover_url"), cover_downloader,
                        log)
    try:
        write_epub_nested(dest, meta_out, outline, cover)
    except Exception:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise
    log(f"scritto: {dest}")
    return {"outline": outline, "meta": meta_out, "language": language,
            "strategy": strategy, "out_path": str(dest)}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="web_to_epub",
        description="Converte una pagina web in EPUB con capitoli e "
                    "sottocapitoli.")
    ap.add_argument("--url", required=True)
    ap.add_argument("--out")
    ap.add_argument("--follow-links", action="store_true")
    ap.add_argument("--max-pages", type=int, default=50)
    ap.add_argument("--use-llm", action="store_true")
    ap.add_argument("--lang")
    ap.add_argument("--title")
    ap.add_argument("--author")
    ap.add_argument("--cover")
    ap.add_argument("--keep-notes", action="store_true")
    ap.add_argument("--ignore-robots", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    try:
        convert(args.url, out_path=args.out, follow=args.follow_links,
                max_pages=args.max_pages, use_llm=args.use_llm,
                lang=args.lang, title=args.title, author=args.author,
                cover_path=args.cover, keep_notes=args.keep_notes,
                ignore_robots=args.ignore_robots, dry_run=args.dry_run,
                fetcher=fetch_page, cover_downloader=download_cover_bytes)
    except FetchError as e:
        print(f"errore di rete: {e}", file=sys.stderr)
        return EXIT_NETWORK
    except ValueError as e:
        print(f"contenuto non estraibile: {e}", file=sys.stderr)
        print("suggerimento: rilanciare con --dry-run per ispezionare",
              file=sys.stderr)
        return EXIT_EMPTY
    except OSError as e:
        print(f"scrittura EPUB fallita: {e}", file=sys.stderr)
        return EXIT_WRITE
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
```

Nota per l'implementatore: `main()` invoca `convert(..., fetcher=fetch_page)` leggendo l'attributo **dal modulo** al momento della chiamata, così `monkeypatch.setattr(w2e, "fetch_page", ...)` nei test ha effetto. Se si passasse il default della firma, la patch non verrebbe vista.

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: PASS — 62 passed

- [ ] **Step 5: Checkpoint**

Run: `python -m py_compile scripts/web_to_epub.py`
Expected: exit 0, nessun output. Nessun commit.

---

### Task 12: Wrapper PowerShell

**Files:**
- Create: `scripts/web_to_epub.ps1`

**Interfaces:**
- Consumes: `scripts/web_to_epub.py` CLI (Task 11)
- Produces: nessuna interfaccia Python; propaga l'exit code dell'engine

- [ ] **Step 1: Scrivere il wrapper**

Creare `scripts/web_to_epub.ps1`:

```powershell
<#
.SYNOPSIS
Converte una pagina web in un EPUB con capitoli e sottocapitoli.

.DESCRIPTION
Wrapper dell'engine scripts/web_to_epub.py. Vedi
docs/superpowers/specs/2026-07-20-web-to-epub-design.md

.EXAMPLE
.\scripts\web_to_epub.ps1 -Url "https://www.vatican.va/content/leo-xiv/it/encyclicals/documents/20260515-magnifica-humanitas.html" -DryRun

.EXAMPLE
.\scripts\web_to_epub.ps1 -Url "https://esempio.org/libro/parte1.html" -FollowLinks -Out "libro.epub"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^https?://')]
    [string]$Url,

    [string]$Out,
    [switch]$FollowLinks,
    [ValidateRange(1, 500)]
    [int]$MaxPages = 50,
    [switch]$UseLLM,
    [string]$Lang,
    [string]$Title,
    [string]$Author,
    [string]$Cover,
    [switch]$KeepNotes,
    [switch]$IgnoreRobots,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$engine = Join-Path $PSScriptRoot 'web_to_epub.py'
if (-not (Test-Path $engine)) {
    Write-Error "engine non trovato: $engine"
    exit 1
}

$python = $null
foreach ($candidate in @(
        (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'),
        (Join-Path $PSScriptRoot '..\venv\Scripts\python.exe'))) {
    if (Test-Path $candidate) { $python = (Resolve-Path $candidate).Path; break }
}
if (-not $python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { Write-Error "interprete Python non trovato"; exit 1 }
    $python = $cmd.Source
}

if ($Cover -and -not (Test-Path $Cover)) {
    Write-Error "file di copertina non trovato: $Cover"
    exit 1
}

$argsList = @($engine, '--url', $Url, '--max-pages', $MaxPages)
if ($Out)          { $argsList += @('--out', $Out) }
if ($Lang)         { $argsList += @('--lang', $Lang) }
if ($Title)        { $argsList += @('--title', $Title) }
if ($Author)       { $argsList += @('--author', $Author) }
if ($Cover)        { $argsList += @('--cover', $Cover) }
if ($FollowLinks)  { $argsList += '--follow-links' }
if ($UseLLM)       { $argsList += '--use-llm' }
if ($KeepNotes)    { $argsList += '--keep-notes' }
if ($IgnoreRobots) { $argsList += '--ignore-robots' }
if ($DryRun)       { $argsList += '--dry-run' }

Write-Verbose "python: $python"
Write-Verbose ("args: " + ($argsList -join ' '))

& $python @argsList
exit $LASTEXITCODE
```

- [ ] **Step 2: Verificare la sintassi PowerShell**

Run:
```powershell
$null = [System.Management.Automation.Language.Parser]::ParseFile("scripts/web_to_epub.ps1", [ref]$null, [ref]$errors); $errors
```
Expected: nessun errore stampato.

- [ ] **Step 3: Verificare la guida**

Run: `Get-Help .\scripts\web_to_epub.ps1 -Full`
Expected: sinossi, descrizione e i due esempi.

- [ ] **Step 4: Prova a vuoto sul parametro obbligatorio**

Run: `.\scripts\web_to_epub.ps1 -Url "ftp://esempio.org/x"`
Expected: errore di validazione su `-Url` (pattern `^https?://`), l'engine non viene invocato.

- [ ] **Step 5: Checkpoint**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: 62 passed. Nessun commit.

---

### Task 13: Validazione sul documento reale

**Files:** nessuna modifica prevista; eventuali ricalibrazioni in `scripts/web_to_epub.py`

**Interfaces:**
- Consumes: l'intero engine
- Produces: nessuna nuova interfaccia

- [ ] **Step 1: Dry-run sull'enciclica di riferimento**

Run:
```powershell
.\scripts\web_to_epub.ps1 -Url "https://www.vatican.va/content/leo-xiv/it/encyclicals/documents/20260515-magnifica-humanitas.html" -DryRun
```
Expected: `lingua: it (fonte: meta)`, poi un albero con più capitoli e i rispettivi sottocapitoli indentati. I titoli non devono contenere marker `[n]`.

- [ ] **Step 2: Giudicare l'outline**

Criteri di accettazione:
- ogni `CAPITOLO n` del documento compare come capitolo di livello 1
- nessun paragrafo di corpo compare come titolo
- nessun titolo di sezione manca

Se un titolo è classificato male, correggere **solo** le soglie in `assign_levels` (5 e 3) o aggiungere una parola chiave al profilo `it`; poi rieseguire l'intera suite: `pytest scripts/test_web_to_epub.py -v`. La suite deve restare verde — è la rete di sicurezza contro le ricalibrazioni che rompono gli altri casi.

- [ ] **Step 3: Generare l'EPUB**

Run:
```powershell
.\scripts\web_to_epub.ps1 -Url "https://www.vatican.va/content/leo-xiv/it/encyclicals/documents/20260515-magnifica-humanitas.html" -Out "$env:TEMP\enciclica.epub"
```
Expected: `scritto: ...enciclica.epub`, exit code 0.

- [ ] **Step 4: Verificare l'EPUB con il parser dell'app**

Run:
```powershell
python -c "import epub_to_tts, os; info = epub_to_tts.parse_epub(os.environ['TEMP'] + r'\enciclica.epub'); print(info.title, '|', info.language, '|', len(info.chapters)); [print(' -', c.title) for c in info.chapters[:10]]"
```
Expected: titolo e lingua corretti, numero di capitoli pari a capitoli + sottocapitoli rilevati, titoli leggibili.

- [ ] **Step 5: Prova con LLM attivo (facoltativa)**

Richiede `ABM_TRANSLATE_MODEL` e un backend configurato.

Run:
```powershell
.\scripts\web_to_epub.ps1 -Url "https://www.vatican.va/content/leo-xiv/it/encyclicals/documents/20260515-magnifica-humanitas.html" -UseLLM -DryRun
```
Expected: `outline (llm): ...`. Se l'LLM non è configurato, il messaggio è `LLM non configurato: euristica` e l'esecuzione prosegue con exit 0.

- [ ] **Step 6: Checkpoint finale**

Run: `pytest scripts/test_web_to_epub.py -v`
Expected: 62 passed. Nessun commit: i file restano locali per scelta.

---

## Note di calibrazione per l'implementatore

**Perché le soglie sono 5 e 3.** Con i pesi di `score_block`, un titolo di capitolo tipico dei documenti istituzionali (`CAPITOLO 1`, bold + maiuscolo + numerato + parola chiave + senza punto finale) totalizza 9. Un sottotitolo in corsivo-grassetto senza numerazione (`La prima articolazione`, bold + senza punto) totalizza 3. Un paragrafo di corpo lungo viene azzerato dal controllo di lunghezza. Il margine tra 9 e 3 è ampio: se un sito reale cade in mezzo, si sposta la soglia, non i pesi — i pesi sono già validati dai test.

**Perché i test iniettano `fetcher`.** Tutte le funzioni che scaricano accettano un callable iniettabile. Nessun test tocca la rete e la suite gira offline in meno di un secondo.

**Perché `_llm_pieces()` importa `translation_core` localmente.** L'import in cima al modulo renderebbe l'engine inutilizzabile fuori dal repo o senza `openai` installato. Con l'import locale, senza LLM lo script funziona comunque in modalità euristica.
