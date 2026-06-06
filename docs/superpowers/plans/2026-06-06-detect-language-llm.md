# Rilevamento Lingua via LLM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Se il file caricato non ha metadato lingua, `/api/analyze` rileva la lingua via LLM (stesso client dell'ottimizzazione AI) esaminando 3 paragrafi consecutivi presi da metà libro.

**Architecture:** Due funzioni nuove in `generation_engine.py` — `_pick_language_sample(chapters)` (pura, campiona 3 paragrafi consecutivi ≥80 char da metà libro con fallback) e `detect_book_language(info)` (chiamata non-streaming a `_llm_client`, 1 tentativo, timeout 20 s, fallimento silenzioso → `""`). `audiobook_app.api_analyze` la invoca inline dopo il parse quando `info.language` è vuota e l'LLM è configurato; il downstream (stime durata, preselezione voci, prefill `trSrcLang`, manifest .abm) funziona da solo. Zero modifiche frontend.

**Tech Stack:** Python/Flask, OpenAI SDK (client `ABM_LLM_*` già inizializzato in `generation_engine._init_llm`), pytest.

**Spec:** `docs/superpowers/specs/2026-06-06-detect-language-llm-design.md`

**Branch:** `TRADUZ` (lavorare e committare qui; mai push senza conferma esplicita).

**Convenzioni vincolanti:**
- Shell di sviluppo: PowerShell. Niente `&&` per concatenare; comandi singoli.
- Validare la sintassi Python prima di committare: `python -m py_compile <file>`.
- I file `.md` sono in `.gitignore`: per committare piani/doc usare `git add -f`.
- Test in `test/` (non `tests/`). Eseguire con `pytest test/<file> -v --tb=short`.

---

## File Structure

| File | Azione | Responsabilità |
|---|---|---|
| `generation_engine.py` | **Modify** | Nuova sezione "Rilevamento lingua" subito dopo `_llm_available()` (riga ~227): costanti, prompt, `_pick_language_sample`, `detect_book_language`. |
| `audiobook_app.py` | **Modify** | `api_analyze` (riga ~6283): hook di rilevamento dopo il check `if not info.chapters`; flag `language_detected` nel job e nelle risposte JSON (nuova analisi + riuso job). |
| `test/test_lang_detect.py` | **Create** | Unit campionamento + detect con client fake; integrazione `/api/analyze` con Flask test client. |

**Riferimenti verificati (con riga, stato attuale del branch TRADUZ):**
- `_llm_client` (module global): `generation_engine.py:120`; `_init_llm`: `:204`; `_llm_available`: `:224-226`; `LLM_MODEL`: `:87`. `import re` già presente (`:25`).
- `audiobook_app` importa il modulo intero: `import generation_engine` (`audiobook_app.py:124`); wrapper `_llm_available()`: `:146-148`.
- `api_analyze`: `audiobook_app.py:6151`; check `if not info.chapters`: `:6283-6284`; creazione `jobs[job_id]`: `:6292-6297`; risposta riuso job esistente: `:6254-6267`; risposta nuova analisi: `:6405-6420`.
- Convenzioni test endpoint: `test/test_translate_endpoints.py` (fixture `client`, `_seed`, monkeypatch su `audiobook_app.*`).

---

### Task 1: `generation_engine.py` — campionamento e `detect_book_language`

**Files:**
- Modify: `generation_engine.py` (inserire dopo `_llm_available()`, riga ~227)
- Create: `test/test_lang_detect.py`

- [ ] **Step 1.1: Scrivi i test falliti (unit)**

```python
# test/test_lang_detect.py
"""Test rilevamento lingua via LLM (spec 2026-06-06-detect-language-llm)."""
import pytest

import generation_engine as ge


# ── Helpers ────────────────────────────────────────────────────────────

class _Ch:
    def __init__(self, text):
        self.text = text


def _paras(*texts):
    """Un capitolo per blocco di paragrafi (separati da riga vuota)."""
    return [_Ch("\n\n".join(texts))]


LONG_A = "A" * 100   # ≥ 80 char → "sostanzioso"
LONG_B = "B" * 100
LONG_C = "C" * 100
LONG_D = "D" * 100
SHORT = "corto"      # < 80 char


class _FakeLLM:
    """Client OpenAI-compatibile minimale: registra i kwargs della chiamata."""
    def __init__(self, reply=None, exc=None):
        self.kwargs = None
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.kwargs = kwargs
                if exc is not None:
                    raise exc
                msg = type("M", (), {"content": reply})
                choice = type("C", (), {"message": msg})
                return type("R", (), {"choices": [choice]})

        self.chat = type("Chat", (), {"completions": _Completions()})()


class _Info:
    def __init__(self, chapters):
        self.chapters = chapters


# ── _pick_language_sample ──────────────────────────────────────────────

def test_sample_starts_from_middle():
    # 8 paragrafi sostanziosi: mid = 4 → campione = paragrafi 4,5,6 (E,F,G)
    texts = [c * 100 for c in "ABCDEFGH"]
    sample = ge._pick_language_sample(_paras(*texts))
    parts = sample.split("\n\n")
    assert parts == ["E" * 100, "F" * 100, "G" * 100]


def test_sample_skips_short_paragraphs_after_middle():
    # mid = 3 ("corto") → la prima terna sostanziosa dal centro è B,C,D
    sample = ge._pick_language_sample(
        _paras(LONG_A, SHORT, SHORT, SHORT, LONG_B, LONG_C, LONG_D))
    assert sample.split("\n\n") == [LONG_B, LONG_C, LONG_D]


def test_sample_retries_from_start_when_tail_short():
    # Dal centro in poi solo paragrafi corti → terna trovata dall'inizio
    sample = ge._pick_language_sample(
        _paras(LONG_A, LONG_B, LONG_C, SHORT, SHORT, SHORT, SHORT))
    assert sample.split("\n\n") == [LONG_A, LONG_B, LONG_C]


def test_sample_fallback_any_three_consecutive():
    # Nessuna terna ≥80 char → 3 consecutivi non vuoti dal centro
    texts = ["uno", "due", "tre", "quattro", "cinque", "sei"]
    sample = ge._pick_language_sample(_paras(*texts))
    assert sample.split("\n\n") == ["quattro", "cinque", "sei"]


def test_sample_fallback_first_1500_chars():
    # Meno di 3 paragrafi totali → primi 1500 char del testo
    sample = ge._pick_language_sample(_paras("X" * 5000))
    assert len(sample) == 1500
    assert sample == "X" * 1500


def test_sample_truncates_each_paragraph_to_600():
    texts = ["P" * 2000, "Q" * 2000, "R" * 2000]
    sample = ge._pick_language_sample(_paras(*texts))
    parts = sample.split("\n\n")
    assert [len(p) for p in parts] == [600, 600, 600]


def test_sample_spans_chapters():
    # I paragrafi si accumulano attraverso i capitoli in ordine
    chapters = [_Ch(LONG_A), _Ch(LONG_B + "\n\n" + LONG_C), _Ch(LONG_D)]
    sample = ge._pick_language_sample(chapters)
    # 4 paragrafi, mid = 2 → terna C,D non esiste (solo 2 dal centro) →
    # retry dall'inizio → A,B,C
    assert sample.split("\n\n") == [LONG_A, LONG_B, LONG_C]


def test_sample_empty_inputs():
    assert ge._pick_language_sample([]) == ""
    assert ge._pick_language_sample(None) == ""
    assert ge._pick_language_sample(_paras("   ")) == ""


# ── detect_book_language ───────────────────────────────────────────────

@pytest.fixture
def book():
    return _Info(_paras(LONG_A, LONG_B, LONG_C))


def test_detect_returns_code(monkeypatch, book):
    fake = _FakeLLM(reply="it")
    monkeypatch.setattr(ge, "_llm_client", fake)
    assert ge.detect_book_language(book) == "it"
    # Parametri chiamata: non-streaming, deterministica, output minimo
    assert fake.kwargs["temperature"] == 0
    assert fake.kwargs["max_tokens"] == 8
    assert fake.kwargs["timeout"] == ge.LANG_DETECT_TIMEOUT_SEC
    assert "stream" not in fake.kwargs
    assert fake.kwargs["model"] == ge.LLM_MODEL
    # Il campione finisce nel messaggio user
    assert LONG_B in fake.kwargs["messages"][1]["content"]


def test_detect_normalizes_reply(monkeypatch, book):
    monkeypatch.setattr(ge, "_llm_client", _FakeLLM(reply="  EN \n"))
    assert ge.detect_book_language(book) == "en"


def test_detect_strips_region_suffix(monkeypatch, book):
    monkeypatch.setattr(ge, "_llm_client", _FakeLLM(reply="en-US"))
    assert ge.detect_book_language(book) == "en"


def test_detect_rejects_garbage(monkeypatch, book):
    monkeypatch.setattr(ge, "_llm_client",
                        _FakeLLM(reply="The language is Italian."))
    assert ge.detect_book_language(book) == ""


def test_detect_empty_reply(monkeypatch, book):
    monkeypatch.setattr(ge, "_llm_client", _FakeLLM(reply=""))
    assert ge.detect_book_language(book) == ""
    monkeypatch.setattr(ge, "_llm_client", _FakeLLM(reply=None))
    assert ge.detect_book_language(book) == ""


def test_detect_swallows_llm_errors(monkeypatch, book):
    monkeypatch.setattr(ge, "_llm_client",
                        _FakeLLM(exc=RuntimeError("network down")))
    assert ge.detect_book_language(book) == ""


def test_detect_no_client(monkeypatch, book):
    monkeypatch.setattr(ge, "_llm_client", None)
    assert ge.detect_book_language(book) == ""


def test_detect_no_text(monkeypatch):
    monkeypatch.setattr(ge, "_llm_client", _FakeLLM(reply="it"))
    assert ge.detect_book_language(_Info([])) == ""
```

- [ ] **Step 1.2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_lang_detect.py -v --tb=short`
Expected: FAIL/ERROR con `AttributeError: module 'generation_engine' has no attribute '_pick_language_sample'` (e simili per `detect_book_language`, `LANG_DETECT_TIMEOUT_SEC`)

- [ ] **Step 1.3: Implementa in `generation_engine.py`**

Inserire subito dopo la funzione `_llm_available()` (riga ~227, prima del commento di sezione successivo):

```python
# ---------------------------------------------------------------------------
# Rilevamento lingua del libro (stesso client LLM dell'ottimizzazione)
# ---------------------------------------------------------------------------

LANG_DETECT_MIN_PARA_CHARS = 80    # paragrafo "sostanzioso"
LANG_DETECT_MAX_PARA_CHARS = 600   # tetto per paragrafo nel campione
LANG_DETECT_TIMEOUT_SEC = 20.0     # un solo tentativo, niente retry

_LANG_DETECT_PROMPT = (
    "You are a language identification system. The user sends an excerpt "
    "from a book. Reply with ONLY the ISO 639-1 two-letter code of the "
    "language the excerpt is written in (for example: it, en, de, fr). "
    "No other text, no punctuation, no explanations."
)


def _pick_language_sample(chapters):
    """Campione di 3 paragrafi consecutivi per il rilevamento lingua.

    Parte da metà libro e cerca la prima terna di paragrafi consecutivi
    "sostanziosi" (>= LANG_DETECT_MIN_PARA_CHARS char); se non la trova dal
    centro in poi riprova dall'inizio. Fallback: 3 paragrafi consecutivi
    non vuoti dal centro (o dall'inizio), poi primi 1500 caratteri del
    testo. Ogni paragrafo del campione e' troncato a
    LANG_DETECT_MAX_PARA_CHARS. Ritorna "" se non c'e' testo.
    """
    paras = []
    for ch in chapters or []:
        for p in re.split(r"\n\s*\n", getattr(ch, "text", "") or ""):
            p = p.strip()
            if p:
                paras.append(p)
    if not paras:
        return ""

    def _find_run(start, min_chars):
        for i in range(start, len(paras) - 2):
            run = paras[i:i + 3]
            if all(len(p) >= min_chars for p in run):
                return run
        return None

    mid = len(paras) // 2
    run = (_find_run(mid, LANG_DETECT_MIN_PARA_CHARS)
           or _find_run(0, LANG_DETECT_MIN_PARA_CHARS)
           or _find_run(mid, 1)
           or _find_run(0, 1))
    if run:
        return "\n\n".join(p[:LANG_DETECT_MAX_PARA_CHARS] for p in run)
    return "\n\n".join(paras)[:1500]


def detect_book_language(info):
    """Rileva la lingua del libro via LLM quando i metadati non la indicano.

    Usa lo stesso client dell'ottimizzazione AI (_llm_client, ABM_LLM_*).
    Chiamata non-streaming, deterministica, un solo tentativo. Fallimento
    silenzioso: ritorna il codice ISO 639-1 ("it", "en", ...) oppure ""
    (LLM non configurato, campione vuoto, errore o risposta non valida).
    """
    if _llm_client is None:
        return ""
    sample = _pick_language_sample(getattr(info, "chapters", None))
    if not sample:
        return ""
    try:
        resp = _llm_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _LANG_DETECT_PROMPT},
                {"role": "user", "content": sample},
            ],
            temperature=0,
            max_tokens=8,
            timeout=LANG_DETECT_TIMEOUT_SEC,
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[lang-detect] LLM call failed (non-fatal): {e}")
        return ""
    code = raw.lower().split()[0].strip("\"'.,;:") if raw else ""
    code = code.split("-")[0]
    # ISO 639-1 = sempre 2 lettere: una regex piu' lasca ({2,3}) farebbe
    # passare token inglesi tipo "the" da risposte verbose.
    if re.fullmatch(r"[a-z]{2}", code):
        print(f"[lang-detect] detected language: {code}")
        return code
    print(f"[lang-detect] invalid LLM reply {raw!r} (non-fatal)")
    return ""
```

Nota su `test_sample_fallback_first_1500_chars`: con un solo paragrafo gigante, `_find_run` non trova mai terne (servono 3 paragrafi) → si arriva all'ultima riga `"\n\n".join(paras)[:1500]`. Con `test_sample_fallback_any_three_consecutive` invece `_find_run(mid, 1)` trova la terna corta dal centro.

- [ ] **Step 1.4: Valida sintassi ed esegui i test**

Run: `python -m py_compile generation_engine.py`
Run: `pytest test/test_lang_detect.py -v --tb=short`
Expected: PASS (tutti i 17 test)

- [ ] **Step 1.5: Commit**

```
git add generation_engine.py test/test_lang_detect.py
git commit -m "feat(lang-detect): campionamento 3 paragrafi + detect_book_language via LLM"
```

---

### Task 2: `audiobook_app.py` — hook in `/api/analyze` + flag `language_detected`

**Files:**
- Modify: `audiobook_app.py` (api_analyze, righe ~6283, ~6292, ~6254, ~6405)
- Test: `test/test_lang_detect.py` (append)

- [ ] **Step 2.1: Scrivi i test falliti (integrazione)**

Append a `test/test_lang_detect.py`:

```python
# ── Integrazione /api/analyze ──────────────────────────────────────────
import io

import audiobook_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    audiobook_app.app.config["TESTING"] = True
    # Upload in dir temporanea, niente rate-limit ne' activity log
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(audiobook_app, "_ip_rl_check",
                        lambda *a, **kw: (True, 0))
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda *a, **kw: None)
    audiobook_app.jobs.clear()
    yield audiobook_app.app.test_client()
    audiobook_app.jobs.clear()


_TXT = ("Primo paragrafo del libro di prova, con testo sufficiente.\n\n"
        "Secondo paragrafo con altro testo di prova per il parser.\n\n"
        "Terzo paragrafo conclusivo del piccolo libro di prova.\n").encode("utf-8")


def _upload_txt(client):
    return client.post("/api/analyze", data={
        "epub": (io.BytesIO(_TXT), "libro.txt"),
    }, content_type="multipart/form-data")


def test_analyze_txt_detects_language(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    monkeypatch.setattr(ge, "detect_book_language", lambda info: "de")
    r = _upload_txt(client)
    assert r.status_code == 200
    d = r.get_json()
    assert d["language"] == "de"
    assert d["language_detected"] is True
    job = audiobook_app.jobs[d["job_id"]]
    assert job["language_detected"] is True
    assert job["info"].language == "de"


def test_analyze_detect_failure_is_silent(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    monkeypatch.setattr(ge, "detect_book_language", lambda info: "")
    r = _upload_txt(client)
    assert r.status_code == 200
    d = r.get_json()
    assert d["language"] == ""
    assert d["language_detected"] is False
    assert d["total_chapters"] >= 1  # analisi completata comunque


def test_analyze_skips_detect_when_llm_unavailable(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: False)
    called = []
    monkeypatch.setattr(ge, "detect_book_language",
                        lambda info: called.append(1) or "it")
    r = _upload_txt(client)
    assert r.status_code == 200
    assert called == []
    assert r.get_json()["language"] == ""


def test_analyze_skips_detect_when_metadata_present(client, monkeypatch):
    """File .abm con language nel manifest: nessuna chiamata LLM."""
    import json as _json
    import zipfile as _zf
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    called = []
    monkeypatch.setattr(ge, "detect_book_language",
                        lambda info: called.append(1) or "xx")
    buf = io.BytesIO()
    with _zf.ZipFile(buf, "w") as zf:
        zf.writestr("chapters/001_uno.txt",
                    "Testo di prova del capitolo uno del libro.")
        zf.writestr("manifest.json", _json.dumps({
            "format": "audiobook-maker-project", "format_version": "1.0",
            "title": "Test", "author": "A", "language": "fr",
            "has_cover": False, "cover_file": "",
            "chapters": [{"index": 1, "filename": "001_uno.txt",
                          "title": "Uno", "word_count": 8}]}))
    buf.seek(0)
    r = client.post("/api/analyze", data={
        "epub": (buf, "libro.abm"),
    }, content_type="multipart/form-data")
    assert r.status_code == 200
    assert called == []
    d = r.get_json()
    assert d["language"] == "fr"
    assert d["language_detected"] is False


def test_analyze_reuse_keeps_detected_flag(client, monkeypatch):
    """Secondo upload identico (riuso job): flag riportato, niente 2a chiamata."""
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    calls = []
    monkeypatch.setattr(ge, "detect_book_language",
                        lambda info: calls.append(1) or "de")
    r1 = _upload_txt(client)
    assert r1.get_json()["language_detected"] is True
    r2 = _upload_txt(client)
    d2 = r2.get_json()
    assert d2["job_id"] == r1.get_json()["job_id"]
    assert d2["language"] == "de"
    assert d2["language_detected"] is True
    assert len(calls) == 1
```

Nota: `monkeypatch.setattr(ge, "detect_book_language", ...)` funziona perché `api_analyze` chiamerà `generation_engine.detect_book_language(...)` (lookup sul modulo a runtime, `audiobook_app.py:124` importa il modulo intero).

- [ ] **Step 2.2: Esegui — verifica che i nuovi test falliscano**

Run: `pytest test/test_lang_detect.py -v --tb=short -k analyze`
Expected: FAIL — `d["language"]` resta `""` in `test_analyze_txt_detects_language` e `KeyError: 'language_detected'` (campo assente dalla risposta)

- [ ] **Step 2.3: Implementa l'hook in `api_analyze`**

**(a)** Subito dopo il check contenuto (`audiobook_app.py:6283-6284`):

```python
    if not info.chapters:
        return jsonify({"error": "No content found."}), 400

    # Lingua assente nei metadati (txt sempre; pdf/epub/abm a volte):
    # rilevamento via LLM (stesso client dell'ottimizzazione AI) su 3
    # paragrafi consecutivi da meta' libro. Fallimento silenzioso: la
    # lingua resta vuota e l'analisi completa comunque (spec 2026-06-06).
    language_detected = False
    if not (getattr(info, "language", "") or "").strip() and _llm_available():
        _detected = generation_engine.detect_book_language(info)
        if _detected:
            info.language = _detected
            language_detected = True
```

**(b)** Nella creazione del job (`:6292-6297`) aggiungere la chiave al dict:

```python
        jobs[job_id] = {"status": "analyzed", "epub_path": str(file_path), "info": info,
                         "last_poll": time.time(), "original_filename": file.filename,
                         "client_id": _get_client_id(), "client_ip": _get_client_ip(),
                         "browser_lang": _get_browser_lang(),
                         "optimized_chapters": [], "file_hash": file_hash,
                         "language_detected": language_detected}
```

**(c)** Nella risposta finale (`:6405-6420`), dopo la riga `"language": info.language,` aggiungere:

```python
        "language_detected": language_detected,
```

**(d)** Nella risposta di riuso job esistente (`:6254-6267`), dopo la riga `"language": info.language,` aggiungere:

```python
                "language_detected": existing_job.get("language_detected", False),
```

- [ ] **Step 2.4: Valida ed esegui tutto il file di test**

Run: `python -m py_compile audiobook_app.py`
Run: `pytest test/test_lang_detect.py -v --tb=short`
Expected: PASS (tutti, unit + integrazione)

- [ ] **Step 2.5: Commit**

```
git add audiobook_app.py test/test_lang_detect.py
git commit -m "feat(lang-detect): hook in /api/analyze + flag language_detected"
```

---

### Task 3: Regressione completa e chiusura

**Files:**
- Modify: `docs/superpowers/specs/2026-06-06-detect-language-llm-design.md` (stato)

- [ ] **Step 3.1: Suite completa + lint sintassi**

Run: `python -m py_compile audiobook_app.py generation_engine.py`
Run: `pytest test/ -v --tb=short`
Expected: nessuna nuova failure rispetto allo stato pre-piano (nota: eventuali failure pre-esistenti `test_paypal_create_gemini` da ordering/reload non sono regressioni di questo piano — confrontare con una run su HEAD precedente in caso di dubbio).

- [ ] **Step 3.2: Verifica manuale rapida (opzionale se LLM non configurato in dev)**

Run: `python audiobook_app.py` — caricare un `.txt` in una lingua riconoscibile.
Expected con `ABM_LLM_API_KEY` configurata: log `[lang-detect] detected language: <code>` e lingua precompilata in UI (capitoli e wizard). Senza API key: nessun log, lingua vuota come oggi. Fermare il server.

- [ ] **Step 3.3: Aggiorna stato spec e committa**

Nella spec, cambiare la riga `**Stato:** approvato (brainstorming concluso)` in `**Stato:** implementato (2026-06-06)`.

```
git add -f docs/superpowers/specs/2026-06-06-detect-language-llm-design.md
git add -f docs/superpowers/plans/2026-06-06-detect-language-llm.md
git commit -m "docs(lang-detect): chiusura spec + piano rilevamento lingua"
```

**NON pushare:** il push si fa solo su conferma esplicita dell'utente.

---

## Note trasversali per l'esecutore

1. **Nomi da verificare sul codice reale** prima di modificare (se un nome differisce, adeguare il nuovo codice, mai il vecchio): `_llm_client`, `_llm_available` (esiste sia in `generation_engine` sia come wrapper in `audiobook_app`), `UPLOAD_DIR`, `_ip_rl_check`, `_log_activity`, `jobs`.
2. **Mai** importare `audiobook_app` da `generation_engine` (incidente double-import documentato in CLAUDE.md). Il flusso è unidirezionale: `audiobook_app` → `generation_engine.detect_book_language`.
3. Convenzione lingua: commenti/log in italiano+inglese misti come il codice circostante (apostrofi ASCII `'` nei commenti Python, mai accentate nei sorgenti `.py` — vedi stile esistente).
4. I test di integrazione importano `audiobook_app`: il primo import esegue l'init del modulo (lento ma già fatto da altri test della suite — nessuna config extra necessaria).
