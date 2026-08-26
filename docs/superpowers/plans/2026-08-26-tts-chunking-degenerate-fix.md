# Fix dei chunk degeneri nel piano TTS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** eliminare i chunk degeneri (frammenti brevissimi composti quasi solo da numerali, tipicamente titoli di capitolo come `XIV.`) che i backend Gemini rifiutano per moderazione contenuti (codice `2017`), fondendoli con i chunk adiacenti e, quando irriducibili, silenziandoli senza chiamata API e senza contarli come fallimenti.

**Architecture:** l'intervento è confinato a `tts_split.py` e non tocca i due loop di generazione di `generation_engine.py`. Un predicato puro riconosce il chunk degenere; una funzione pura di merge, consapevole dei cap `max_chars`/`max_bytes`, li fonde in avanti o all'indietro dentro `_plan_chunks`; il caso irriducibile viene intercettato nel wrapper di sintesi Gemini, che già possiede il ramo «testo vuoto → silenzio», ma restituendo un esito di successo invece di un fallimento.

**Tech Stack:** Python 3.12, pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-cloudflare-tts-prod-backend-design.md` (§5 «Fix del chunking», §11 Fase 1).

## Global Constraints

- `ABM_TTS_MIN_CHUNK_CHARS` — soglia sotto la quale un chunk è degenere per sola lunghezza. Default **40**. Letta una volta a import time, come le altre costanti di `tts_split.py`.
- Soglia di lunghezza per il criterio «quasi solo numerali»: **120** caratteri. Costante interna, non parametrica.
- Frazione di token numerali che rende degenere un chunk sotto i 120 caratteri: **almeno la metà**.
- Invariante non negoziabile: **nessun chunk può superare `max_bytes` UTF-8 né `max_chars`** dopo il merge. Se la fusione violerebbe un cap, non si fonde.
- Il ramo degenere-irriducibile **non deve produrre una chiamata API** e **non deve incrementare `failed_chunks`**.
- Nessun provider AI/TTS va nominato in testo rivolto all'utente finale. Log e commenti tecnici sono esenti.
- Commit in stile Conventional Commits, senza trailer di attribuzione.
- Questa fase è rilasciabile da sola, prima di qualunque lavoro su Cloudflare.

---

### Task 1: predicato del chunk degenere

**Files:**
- Modify: `tts_split.py` (nuove costanti accanto a `CHUNK_MAX_CHARS`, riga 42; nuova funzione prima di `_plan_chunks`, riga 421)
- Test: `test/test_chunk_degenerate.py` (nuovo)

**Interfaces:**
- Consumes: niente da task precedenti.
- Produces: `MIN_CHUNK_CHARS: int`, `_DEGENERATE_MAX_CHARS: int`, `_is_degenerate_chunk(text: str, min_chars: int = MIN_CHUNK_CHARS) -> bool`.

- [ ] **Step 1: Scrivi il test che fallisce**

Crea `test/test_chunk_degenerate.py`:

```python
"""Riconoscimento dei chunk degeneri (frammenti che i TTS rifiutano)."""
import pytest

from tts_split import _is_degenerate_chunk


@pytest.mark.parametrize("text", [
    "XIV.",
    "14.",
    "Capitolo XIV",
    "  III  ",
    "1793",
    "Cap. 12",
    "",
    "   ",
])
def test_degenerate_fragments(text):
    assert _is_degenerate_chunk(text) is True


@pytest.mark.parametrize("text", [
    "Nel mezzo del cammin di nostra vita mi ritrovai per una selva oscura.",
    "Il quattordicesimo giorno del mese di maggio, la nave lasciò il porto.",
    "Nel 1793 la Convenzione decise di processare il re, e la città intera trattenne il fiato.",
])
def test_regular_text_is_not_degenerate(text):
    assert _is_degenerate_chunk(text) is False


def test_short_but_wordy_is_degenerate_by_length():
    # Sotto min_chars e' un frammento anche senza numerali: il TTS lo legge male.
    assert _is_degenerate_chunk("Buongiorno.") is True


def test_min_chars_is_parametric():
    text = "Una frase di media lunghezza che supera i quaranta caratteri."
    assert _is_degenerate_chunk(text, min_chars=10) is False
    assert _is_degenerate_chunk(text, min_chars=200) is True
```

- [ ] **Step 2: Esegui il test e verifica che fallisca**

Run: `python -m pytest test/test_chunk_degenerate.py -v`
Expected: FAIL con `ImportError: cannot import name '_is_degenerate_chunk'`

- [ ] **Step 3: Implementa il predicato**

In `tts_split.py`, sotto `CHUNK_MAX_CHARS = 2000` (riga 42) aggiungi:

```python
# Un chunk piu' corto di questa soglia e' un frammento, non una frase: i
# backend Gemini lo rifiutano per moderazione (codice 2017) quando e' composto
# quasi solo da numerali (tipico dei titoli di capitolo: "XIV."). Parametrico
# perche' la soglia giusta dipende dalla lingua e dal corpus.
MIN_CHUNK_CHARS = int(os.environ.get("ABM_TTS_MIN_CHUNK_CHARS", "40") or 40)
# Sopra questa lunghezza un chunk contiene abbastanza contesto perche' il
# rapporto di numerali non conti piu': "Nel 1793 la Convenzione..." e' testo.
_DEGENERATE_MAX_CHARS = 120
# Numerale arabo o romano, eventualmente circondato da punteggiatura.
_NUMERAL_TOKEN_RE = re.compile(r'^[\W_]*(?:\d+|[IVXLCDM]+)[\W_]*$', re.IGNORECASE)
```

Prima di `_plan_chunks` (riga 421) aggiungi:

```python
def _is_degenerate_chunk(text, min_chars=MIN_CHUNK_CHARS):
    """True se il chunk e' un frammento che non va mandato al TTS.

    Due criteri, in OR:
      1. piu' corto di `min_chars`: e' un frammento comunque, indipendentemente
         dal contenuto;
      2. piu' corto di `_DEGENERATE_MAX_CHARS` e composto per almeno meta' dei
         token da numerali (arabi o romani): e' un'intestazione di capitolo, il
         caso che fa scattare la moderazione contenuti.
    """
    clean = (text or "").strip()
    if len(clean) < min_chars:
        return True
    if len(clean) >= _DEGENERATE_MAX_CHARS:
        return False
    tokens = [t for t in re.split(r'\s+', clean) if t]
    if not tokens:
        return True
    numerals = sum(1 for t in tokens if _NUMERAL_TOKEN_RE.match(t))
    return numerals * 2 >= len(tokens)
```

Verifica che `os` e `re` siano già importati in testa al modulo; se `os` non lo è, aggiungilo.

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `python -m pytest test/test_chunk_degenerate.py -v`
Expected: PASS (12 test)

- [ ] **Step 5: Verifica di non aver rotto nulla**

Run: `python -m pytest test/test_chunker_golden.py test/test_tts_split_pcm.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tts_split.py test/test_chunk_degenerate.py
git commit -m "feat(tts): predicato per i chunk degeneri rifiutati dalla moderazione"
```

---

### Task 2: merge dei chunk degeneri nel piano

**Files:**
- Modify: `tts_split.py` (nuova funzione dopo `_is_degenerate_chunk`; `_plan_chunks`, righe 421-455)
- Test: `test/test_chunk_degenerate.py` (estendi)

**Interfaces:**
- Consumes: `_is_degenerate_chunk`, `MIN_CHUNK_CHARS` dal Task 1; `_within(text, max_chars, max_bytes) -> bool`, già esistente in `tts_split.py`.
- Produces: `_merge_degenerate_chunks(chunks, max_chars, max_bytes, min_chars=MIN_CHUNK_CHARS) -> list[str]`; le voci di `plan` prodotte da `_plan_chunks` guadagnano la chiave `"degenerate": bool`.

- [ ] **Step 1: Scrivi i test che falliscono**

Aggiungi in fondo a `test/test_chunk_degenerate.py`:

```python
from tts_split import _merge_degenerate_chunks


def test_merges_forward_into_next_chunk():
    body = "Il mattino dopo la nave lasciò il porto con il vento a favore. " * 2
    out = _merge_degenerate_chunks(["XIV.", body], max_chars=2000, max_bytes=None)
    assert len(out) == 1
    assert out[0].startswith("XIV.")
    assert body.strip() in out[0]


def test_merges_backward_when_no_next_chunk():
    body = "Il mattino dopo la nave lasciò il porto con il vento a favore. " * 2
    out = _merge_degenerate_chunks([body, "XIV."], max_chars=2000, max_bytes=None)
    assert len(out) == 1
    assert out[0].rstrip().endswith("XIV.")


def test_does_not_merge_when_it_would_break_max_chars():
    body = "a" * 1990
    out = _merge_degenerate_chunks(["XIV.", body], max_chars=2000, max_bytes=None)
    assert out == ["XIV.", body]


def test_does_not_merge_when_it_would_break_max_bytes():
    # Ogni ideogramma pesa 3 byte UTF-8.
    body = "書" * 300  # 900 byte
    out = _merge_degenerate_chunks(["XIV.", body], max_chars=2000, max_bytes=950)
    assert out == ["XIV.", body]


def test_single_irreducible_chunk_survives_untouched():
    out = _merge_degenerate_chunks(["XIV."], max_chars=2000, max_bytes=None)
    assert out == ["XIV."]


def test_regular_chunks_are_returned_unchanged():
    a = "Prima frase lunga abbastanza da non essere un frammento qualunque."
    b = "Seconda frase lunga abbastanza da non essere un frammento qualunque."
    assert _merge_degenerate_chunks([a, b], max_chars=2000, max_bytes=None) == [a, b]


def test_plan_chunks_marks_irreducible_degenerate():
    from types import SimpleNamespace
    from tts_split import _plan_chunks

    ch = SimpleNamespace(index=0, title="XIV", text="XIV.", synthetic_title=False)
    info = SimpleNamespace(chapters=[ch], language="it")
    plan = _plan_chunks(info)
    assert len(plan) == 1
    assert plan[0]["degenerate"] is True


def test_plan_chunks_marks_regular_chapter_as_not_degenerate():
    from types import SimpleNamespace
    from tts_split import _plan_chunks

    body = "Il mattino dopo la nave lasciò il porto con il vento a favore. " * 5
    ch = SimpleNamespace(index=0, title="Capitolo I", text=body, synthetic_title=False)
    info = SimpleNamespace(chapters=[ch], language="it")
    plan = _plan_chunks(info)
    assert all(b["degenerate"] is False for b in plan)
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `python -m pytest test/test_chunk_degenerate.py -v`
Expected: FAIL con `ImportError: cannot import name '_merge_degenerate_chunks'`

- [ ] **Step 3: Implementa il merge**

In `tts_split.py`, subito dopo `_is_degenerate_chunk`:

```python
def _merge_degenerate_chunks(chunks, max_chars, max_bytes, min_chars=MIN_CHUNK_CHARS):
    """Fonde i chunk degeneri con un vicino, senza mai violare i cap.

    Preferenza in avanti (il titolo sta naturalmente davanti al corpo del
    capitolo), fallback all'indietro. Se nessuna delle due fusioni resta dentro
    `max_chars`/`max_bytes`, il chunk resta com'e': l'invariante sui cap vale
    piu' del fix, e il caso irriducibile viene silenziato a valle.
    """
    if len(chunks) < 2:
        return list(chunks)
    out = list(chunks)
    i = 0
    while i < len(out):
        if not _is_degenerate_chunk(out[i], min_chars=min_chars):
            i += 1
            continue
        merged = None
        target = None
        if i + 1 < len(out):
            candidate = f"{out[i].strip()}\n\n{out[i + 1].lstrip()}"
            if _within(candidate, max_chars, max_bytes):
                merged, target = candidate, i + 1
        if merged is None and i > 0:
            candidate = f"{out[i - 1].rstrip()}\n\n{out[i].strip()}"
            if _within(candidate, max_chars, max_bytes):
                merged, target = candidate, i - 1
        if merged is None:
            i += 1
            continue
        out[target] = merged
        del out[i]
        # Fusione all'indietro: l'indice corrente punta gia' al chunk successivo.
        # Fusione in avanti: `del out[i]` ha portato il fuso in posizione i, che
        # va rivalutato perche' potrebbe essere ancora degenere.
        if target < i:
            i = target + 1
    return out
```

- [ ] **Step 4: Aggancia il merge a `_plan_chunks`**

In `_plan_chunks` (riga ~453) sostituisci:

```python
        chunks = split_text_into_chunks(full_text, max_chars=max_chars, max_bytes=max_bytes)
        for ci, chunk_text in enumerate(chunks):
            plan.append({
                "chapter_index": ch.index,
                "chapter_title": ch.title,
                "chunk_index": ci,
                "chunks_in_chapter": len(chunks),
                "text": chunk_text,
                "chars": len(chunk_text),
            })
```

con:

```python
        chunks = split_text_into_chunks(full_text, max_chars=max_chars, max_bytes=max_bytes)
        # Un frammento tipo "XIV." fa scattare la moderazione contenuti dei
        # backend Gemini (codice 2017): fondilo col vicino finche' i cap lo
        # permettono. Cio' che resta degenere e' irriducibile e viene silenziato
        # in fase di sintesi, senza chiamata API.
        chunks = _merge_degenerate_chunks(chunks, max_chars, max_bytes)
        for ci, chunk_text in enumerate(chunks):
            plan.append({
                "chapter_index": ch.index,
                "chapter_title": ch.title,
                "chunk_index": ci,
                "chunks_in_chapter": len(chunks),
                "text": chunk_text,
                "chars": len(chunk_text),
                "degenerate": _is_degenerate_chunk(chunk_text),
            })
```

- [ ] **Step 5: Esegui i test e verifica che passino**

Run: `python -m pytest test/test_chunk_degenerate.py -v`
Expected: PASS

- [ ] **Step 6: Verifica la non-regressione sui consumatori del piano**

Run: `python -m pytest test/test_chunker_golden.py test/test_tts_split_pcm.py test/test_parenthetical_flags.py test/test_generation_engine_accumulation.py test/test_generation_engine_style.py test/test_speechify_engine_dispatch.py test/test_chunk_reuse.py -v`
Expected: PASS. Se un test golden confronta il numero di chunk attesi, aggiornalo solo se la differenza è una fusione legittima di un frammento; qualunque altra differenza è un bug del merge.

- [ ] **Step 7: Commit**

```bash
git add tts_split.py test/test_chunk_degenerate.py
git commit -m "feat(tts): fonde i chunk degeneri col vicino rispettando i cap"
```

---

### Task 3: silenzio senza chiamata API per il degenere irriducibile

**Files:**
- Modify: `tts_split.py` (`generate_chunk_pcm_gemini`, righe 850-965; inserimento subito dopo il ramo `clean is None`, righe 885-888)
- Test: `test/test_chunk_degenerate.py` (estendi)

**Interfaces:**
- Consumes: `_is_degenerate_chunk` (Task 1), `_generate_silence_pcm(output_path, duration_sec=1, sample_rate=None)`, già esistente (riga 570).
- Produces: `generate_chunk_pcm_gemini` può restituire un dict di successo con la chiave `"skipped_degenerate": True`.

**Perché qui e non nei loop di `generation_engine.py`:** i due loop (righe 4657 e 5015) sono lunghi e densi di stato (marker M4B, gap, contatori). Il wrapper di sintesi possiede già il ramo «testo non sintetizzabile → silenzio» e ha una sola forma di ritorno da rispettare: intercettare qui costa tre righe e zero rischio sui loop.

**Perché un dict di successo e non `_fail(...)`:** il ramo esistente `empty_after_sanitize` restituisce `False`, che il chiamante conta in `failed_chunks`. Un capitolo il cui testo è solo `XIV.` non è un fallimento di sintesi: contarlo tale inquina le soglie di consegna. La spec (§5) chiede esplicitamente «skipped, non failed».

- [ ] **Step 1: Scrivi i test che falliscono**

Aggiungi in fondo a `test/test_chunk_degenerate.py`:

```python
def test_irreducible_degenerate_chunk_is_silenced_without_api_call(tmp_path, monkeypatch):
    import tts_split

    called = []

    class _FakeGemini:
        class GeminiQuotaExhausted(Exception): pass
        class GeminiBudgetExceeded(Exception): pass
        class GeminiUnavailable(Exception): pass

        @staticmethod
        def synthesize(*a, **kw):
            called.append(1)
            raise AssertionError("il chunk degenere non deve arrivare all'API")

    monkeypatch.setattr(tts_split, "_gemini", _FakeGemini)
    out = tmp_path / "chunk.pcm"

    res = tts_split.generate_chunk_pcm_gemini("XIV.", "gemini:Kore", str(out))

    assert called == []
    assert isinstance(res, dict)
    assert res["success"] is True
    assert res["skipped_degenerate"] is True
    assert res["input_tokens"] == 0
    assert res["output_tokens"] == 0
    assert out.exists() and out.stat().st_size > 0


def test_regular_chunk_still_reaches_the_api(tmp_path, monkeypatch):
    import tts_split

    called = []

    class _FakeGemini:
        class GeminiQuotaExhausted(Exception): pass
        class GeminiBudgetExceeded(Exception): pass
        class GeminiUnavailable(Exception): pass

        @staticmethod
        def synthesize(text, voice_id, output_path=None, **kw):
            called.append(text)
            with open(output_path, "wb") as f:
                f.write(b"\x00" * 100)
            return {"success": True, "bytes_written": 100, "audio_seconds_real": 1.0,
                    "input_tokens": 5, "output_tokens": 25, "model_key": "flash31",
                    "voice_name": "Kore", "attempts_used": 1}

    monkeypatch.setattr(tts_split, "_gemini", _FakeGemini)
    out = tmp_path / "chunk.pcm"
    body = "Il mattino dopo la nave lasciò il porto con il vento a favore. " * 3

    res = tts_split.generate_chunk_pcm_gemini(body, "gemini:Kore", str(out))

    assert len(called) == 1
    assert res["output_tokens"] == 25
    assert "skipped_degenerate" not in res
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `python -m pytest test/test_chunk_degenerate.py -k degenerate_chunk_is_silenced -v`
Expected: FAIL — il fake solleva `AssertionError` perché la chiamata API avviene.

- [ ] **Step 3: Implementa il ramo di skip**

In `tts_split.py`, subito dopo il blocco `if clean is None:` (righe 885-888) di `generate_chunk_pcm_gemini`, inserisci:

```python
    # Frammento irriducibile (il merge nel piano non ha potuto fonderlo): i
    # backend Gemini lo rifiutano per moderazione contenuti (codice 2017).
    # Silenzialo senza spendere una chiamata: non e' un fallimento di sintesi,
    # e' un chunk che non contiene parlato.
    if _is_degenerate_chunk(clean):
        _generate_silence_pcm(output_path, duration_sec=1)
        print(f"[gemini-tts] Chunk degenere silenziato senza chiamata API: "
              f"{clean[:40]!r}")
        return {
            "success": True,
            "bytes_written": os.path.getsize(output_path),
            "audio_seconds_real": 1.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model_key": None,
            "voice_name": voice_id,
            "attempts_used": 0,
            "skipped_degenerate": True,
        }
```

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `python -m pytest test/test_chunk_degenerate.py -v`
Expected: PASS

- [ ] **Step 5: Verifica la suite completa**

Run: `python -m pytest test/ -q --tb=short`
Expected: nessun fallimento nuovo rispetto alla baseline.

- [ ] **Step 6: Commit**

```bash
git add tts_split.py test/test_chunk_degenerate.py
git commit -m "feat(tts): silenzia il chunk degenere irriducibile senza chiamata API"
```

---

### Task 4: documentazione del parametro e bump di versione

**Files:**
- Modify: `PARAMETRI_CONFIGURAZIONE.md`
- Modify: `version.py`

- [ ] **Step 1: Documenta `ABM_TTS_MIN_CHUNK_CHARS`**

Aggiungi la voce nella sezione dei parametri TTS/chunking di `PARAMETRI_CONFIGURAZIONE.md`, nello stesso formato delle voci vicine: nome, descrizione, default `40`, file e riga della costante `MIN_CHUNK_CHARS` in `tts_split.py`. Descrizione: «Soglia caratteri sotto la quale un chunk è considerato un frammento e viene fuso con il vicino; se irriducibile viene silenziato senza chiamata API.»

- [ ] **Step 2: Bump di versione**

In `version.py` incrementa la patch di `__version__`.

- [ ] **Step 3: Commit**

```bash
git add -f PARAMETRI_CONFIGURAZIONE.md version.py
git commit -m "docs(tts): parametro ABM_TTS_MIN_CHUNK_CHARS e bump versione"
```

Nota: `PARAMETRI_CONFIGURAZIONE.md` e i file sotto `docs/` sono coperti da `*.md` in `.gitignore` — serve `git add -f`.

---

## Criterio di uscita della fase

Un intero libro con capitoli titolati a numerale romano viene pianificato senza che nessun chunk degenere raggiunga l'API, e la suite resta verde. Questo chiude il criterio **G5** della spec.
