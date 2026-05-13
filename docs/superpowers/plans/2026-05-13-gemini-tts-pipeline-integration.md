# Gemini TTS Pipeline Integration (Plan B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the standalone `gemini_tts.py` module (Plan A) into the live TTS generation pipeline so that voices with prefix `gemini:` produce audiobooks end-to-end (MP3 / M4B / ZIP / ZIP_RSS), with native PCM→AAC direct path for M4B, preview cap enforcement, and per-chunk usage tracking.

**Architecture:**
- **Dispatch:** `run_generation()` decides engine once per book (`edge` / `google` / `gemini`) via a new `_engine_for_voice(voice)` helper. Single voice per book = single engine for the whole pipeline; no mid-book mixing.
- **Native format:** Gemini chunks are written as `.pcm` (24 kHz mono 16-bit). At assembly time the engine branches: `mp3` → `pcm_to_mp3` one-shot; `m4b` → `pcm_to_aac_m4b` direct (no MP3 intermediate); `zip`/`zip_rss` → per-chapter `pcm_to_mp3`.
- **Chunk size:** Gemini uses language-aware limits (1500 chars for zh/ja/hi/ar, 2000 elsewhere). Edge/Google keep the existing 2000 default.
- **Cancellation:** Cancel path mirrors Google — record partial usage, no refund (Gemini is post-paid via record_usage; budget reservation = Plan C).
- **Preview cap:** Per-cookie rolling 24h cap enforced at `/api/preview_audio` BEFORE synth call. HTTP 429 on overflow, with `Retry-After` semantics.

**Tech Stack:** Python (Flask), `gemini_tts` (Plan A module), `audio_utils.pcm_*` helpers (Plan A), FFmpeg. Frontend: vanilla JS in `static/js/app.js`.

**Out of scope (= Plan C):**
- PayPal/voucher payment for Gemini voices above €0.50 threshold
- Upfront budget reservation per book (mirrors Google `reserve_chars` but on EUR tokens)
- Cross-purpose voucher (LLM ↔ Gemini TTS)

---

## File Structure

| File | Role in Plan B |
|------|----------------|
| `tts_split.py` | Add `generate_chunk_pcm_gemini()` (sync, retry+silence fallback), `_generate_silence_pcm()`, `_pick_chunk_max_chars(voice, language)`. Modify `_plan_chunks()` to accept `max_chars`. |
| `generation_engine.py` | Add `_engine_for_voice(voice)`. Branch chunk loop on engine: write `.pcm` for Gemini. Track `engine_per_book` once. Branch assembly: PCM-direct paths for `m4b`/`mp3`/`zip`/`zip_rss`. Per-chunk `record_usage`. Cleanup partial PCM files on cancel. |
| `audiobook_app.py` | Bootstrap `gemini_tts.init(_DATA_DIR)`. `/api/voices` merges Gemini voices (with `gender`/`gender_icon` shim). `/api/preview_audio` dispatches to Gemini + enforces preview cap. `/api/generate` validates `gemini_tts.is_available()` if a Gemini voice is requested. |
| `static/js/app.js` | `_isGeminiVoice(id)` helper. `updVoices()` shows Gemini group when available. Preview cap HTTP 429 → user-friendly toast. |
| `templates/_fragments/i18n_data.js` | Add 2 new translation keys for preview cap error. |
| `test/test_gemini_pipeline.py` | NEW — integration tests with mocked `gemini_tts.synthesize` returning PCM bytes. |

---

## Task list

| # | Task | Module |
|---|------|--------|
| 1 | `_generate_silence_pcm` helper | `tts_split.py` |
| 2 | `generate_chunk_pcm_gemini` sync function | `tts_split.py` |
| 3 | `_pick_chunk_max_chars(voice, language)` | `tts_split.py` |
| 4 | `_plan_chunks(info, max_chars=...)` parametric | `tts_split.py` |
| 5 | `_engine_for_voice(voice)` dispatcher | `generation_engine.py` |
| 6 | Chunk loop: Gemini PCM branch (single-file) | `generation_engine.py` |
| 7 | Single-file assembly: PCM→MP3 / PCM→M4B direct | `generation_engine.py` |
| 8 | Chunk loop + per-chapter assembly (zip/zip_rss) | `generation_engine.py` |
| 9 | Cancellation cleanup for partial PCM | `generation_engine.py` |
| 10 | Bootstrap `gemini_tts.init()` | `audiobook_app.py` |
| 11 | `/api/voices` merges Gemini + shim | `audiobook_app.py` |
| 12 | `/api/preview_audio` dispatch + cap | `audiobook_app.py` |
| 13 | `/api/generate` availability validation | `audiobook_app.py` |
| 14 | Frontend selector + preview cap toast | `static/js/app.js`, `i18n_data.js` |
| 15 | End-to-end integration smoke test | `test/test_gemini_pipeline.py` |

---

### Task 1: `_generate_silence_pcm` helper

Generates N seconds of PCM silence (zero bytes) for fallback when Gemini synth fails. Mirrors `_generate_silence_mp3` from `audio_utils.py`.

**Files:**
- Modify: `tts_split.py` (add helper before `generate_chunk_mp3_google`, around line 274)

- [ ] **Step 1: Write the failing test**

Create `test/test_tts_split_pcm.py`:
```python
"""Tests for PCM helpers in tts_split.py."""
import os
import tts_split


def test_generate_silence_pcm_creates_file(tmp_path):
    out = tmp_path / "silence.pcm"
    tts_split._generate_silence_pcm(str(out), duration_sec=1)
    assert out.exists()
    # 24000 Hz × 1 ch × 2 bytes = 48000 bytes per second
    assert out.stat().st_size == 48000


def test_generate_silence_pcm_two_seconds(tmp_path):
    out = tmp_path / "silence.pcm"
    tts_split._generate_silence_pcm(str(out), duration_sec=2)
    assert out.stat().st_size == 96000


def test_generate_silence_pcm_zero_duration(tmp_path):
    out = tmp_path / "silence.pcm"
    tts_split._generate_silence_pcm(str(out), duration_sec=0)
    assert out.exists()
    assert out.stat().st_size == 0


def test_generate_silence_pcm_content_is_zeros(tmp_path):
    out = tmp_path / "silence.pcm"
    tts_split._generate_silence_pcm(str(out), duration_sec=1)
    data = out.read_bytes()
    assert all(b == 0 for b in data)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_tts_split_pcm.py -v`
Expected: FAIL with `AttributeError: module 'tts_split' has no attribute '_generate_silence_pcm'`.

- [ ] **Step 3: Add the helper to `tts_split.py`**

Find this line in `tts_split.py` (around line 274, just before `def generate_chunk_mp3_google`):
```python
# ---------------------------------------------------------------------------
# Google Cloud TTS generation
# ---------------------------------------------------------------------------
```

Insert immediately ABOVE it:
```python
# ---------------------------------------------------------------------------
# Gemini TTS generation (PCM native)
# ---------------------------------------------------------------------------

_PCM_SAMPLE_RATE = 24000
_PCM_CHANNELS = 1
_PCM_SAMPLE_WIDTH = 2  # bytes per sample (16-bit)


def _generate_silence_pcm(output_path, duration_sec=1):
    """Scrive N secondi di silenzio PCM 24kHz mono 16-bit (zero bytes)."""
    n_bytes = int(duration_sec * _PCM_SAMPLE_RATE * _PCM_CHANNELS * _PCM_SAMPLE_WIDTH)
    with open(output_path, "wb") as f:
        if n_bytes > 0:
            f.write(b"\x00" * n_bytes)


```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_tts_split_pcm.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```
git add tts_split.py
git commit -m "feat(gemini-tts): PCM silence helper for Gemini fallback"
```

---

### Task 2: `generate_chunk_pcm_gemini` sync function

Synchronous wrapper around `gemini_tts.synthesize` with retry logic mirroring `generate_chunk_mp3_google`. On total failure writes PCM silence and returns `False`. On success returns a `dict` with usage metadata (input_tokens, output_tokens, audio_seconds, model_key) so the caller can record usage.

**Files:**
- Modify: `tts_split.py` (append after `_generate_silence_pcm`)

- [ ] **Step 1: Write the failing tests**

Append to `test/test_tts_split_pcm.py`:
```python
import sys
from unittest.mock import patch


def test_generate_chunk_pcm_gemini_success(tmp_path, monkeypatch):
    """Success path: writes PCM, returns dict with usage."""
    out = tmp_path / "chunk.pcm"

    def fake_synth(text, voice_id, output_path=None, **kw):
        with open(output_path, "wb") as f:
            f.write(b"\x01\x02" * 1000)
        return {
            "audio_bytes": 2000,
            "audio_seconds": 0.5,
            "input_tokens": 10,
            "output_tokens": 25,
            "model_key": "flash25",
        }

    monkeypatch.setattr("gemini_tts.synthesize", fake_synth)
    result = tts_split.generate_chunk_pcm_gemini(
        "Ciao mondo.", "gemini:flash25:Zephyr", str(out)
    )
    assert result is not False
    assert isinstance(result, dict)
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 25
    assert result["model_key"] == "flash25"
    assert out.exists()
    assert out.stat().st_size == 2000


def test_generate_chunk_pcm_gemini_retries_then_succeeds(tmp_path, monkeypatch):
    calls = {"n": 0}

    def flaky_synth(text, voice_id, output_path=None, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 100)
        return {"audio_bytes": 100, "audio_seconds": 0.05,
                "input_tokens": 1, "output_tokens": 2, "model_key": "flash25"}

    monkeypatch.setattr("gemini_tts.synthesize", flaky_synth)
    monkeypatch.setattr("time.sleep", lambda s: None)  # no real backoff in tests
    out = tmp_path / "chunk.pcm"
    result = tts_split.generate_chunk_pcm_gemini(
        "hello", "gemini:flash25:Zephyr", str(out), max_retries=3
    )
    assert result is not False
    assert calls["n"] == 3


def test_generate_chunk_pcm_gemini_total_failure_writes_silence(tmp_path, monkeypatch):
    def always_fail(*a, **kw):
        raise RuntimeError("permanent")

    monkeypatch.setattr("gemini_tts.synthesize", always_fail)
    monkeypatch.setattr("time.sleep", lambda s: None)
    out = tmp_path / "chunk.pcm"
    result = tts_split.generate_chunk_pcm_gemini(
        "fail", "gemini:flash25:Zephyr", str(out), max_retries=2
    )
    assert result is False
    assert out.exists()
    assert out.stat().st_size == 48000  # 1 second of silence


def test_generate_chunk_pcm_gemini_empty_text(tmp_path):
    """Empty/blank text writes silence and returns False (no API call)."""
    out = tmp_path / "chunk.pcm"
    result = tts_split.generate_chunk_pcm_gemini(
        "   ", "gemini:flash25:Zephyr", str(out)
    )
    assert result is False
    assert out.exists()
    assert out.stat().st_size == 48000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test/test_tts_split_pcm.py -v -k gemini`
Expected: 4 FAILED with `AttributeError: module 'tts_split' has no attribute 'generate_chunk_pcm_gemini'`.

- [ ] **Step 3: Add the function to `tts_split.py`**

Append after `_generate_silence_pcm` (still in the Gemini section):
```python
def generate_chunk_pcm_gemini(text, voice_id, output_path, max_retries=3):
    """Genera PCM 24kHz mono 16-bit da testo via Gemini TTS con retry e fallback.

    Returns:
        dict {input_tokens, output_tokens, audio_seconds, audio_bytes, model_key}
        on success, False on total failure (silence PCM written).
    """
    import gemini_tts as _gemini  # late import: keeps module optional

    clean = _sanitize_tts_text(text)
    if clean is None:
        _generate_silence_pcm(output_path, duration_sec=1)
        return False

    last_error = None
    for attempt in range(max_retries):
        try:
            result = _gemini.synthesize(clean, voice_id, output_path=output_path)
            return result
        except Exception as e:
            last_error = e
            snippet = clean[:60].replace('\n', ' ')
            print(f"[gemini-tts] Attempt {attempt+1}/{max_retries} failed for chunk "
                  f"({len(clean)} chars: \"{snippet}...\"): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    print(f"[gemini-tts] WARNING: All {max_retries} attempts failed, "
          f"generating silence ({len(clean)} chars). Last error: {last_error}")
    _generate_silence_pcm(output_path, duration_sec=1)
    return False


```

Verify `time` is already imported at the top of `tts_split.py` (it is — line ~20). If not, add `import time` near other stdlib imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test/test_tts_split_pcm.py -v`
Expected: 8 passed (4 silence + 4 gemini).

- [ ] **Step 5: Commit**

```
git add tts_split.py
git commit -m "feat(gemini-tts): sync PCM chunk generator with retry and silence fallback"
```

---

### Task 3: `_pick_chunk_max_chars(voice, language)`

Language-aware chunk size. Gemini voices use 1500 chars for zh/ja/hi/ar (CJK + Hindi expand more under UTF-8), 2000 otherwise. Edge/Google voices keep the legacy 2000 unconditionally.

**Files:**
- Modify: `tts_split.py` (add near `CHUNK_MAX_CHARS` constant)

- [ ] **Step 1: Write the failing test**

Append to `test/test_tts_split_pcm.py`:
```python
def test_pick_chunk_max_chars_edge_voice():
    assert tts_split._pick_chunk_max_chars("it-IT-IsabellaNeural", "it") == 2000


def test_pick_chunk_max_chars_google_voice():
    assert tts_split._pick_chunk_max_chars("gcloud:it-IT-Chirp3-HD-Charon", "it") == 2000


def test_pick_chunk_max_chars_gemini_italian():
    assert tts_split._pick_chunk_max_chars("gemini:flash25:Zephyr", "it") == 2000


def test_pick_chunk_max_chars_gemini_chinese():
    assert tts_split._pick_chunk_max_chars("gemini:flash25:Zephyr", "zh") == 1500


def test_pick_chunk_max_chars_gemini_japanese():
    assert tts_split._pick_chunk_max_chars("gemini:flash25:Zephyr", "ja") == 1500


def test_pick_chunk_max_chars_gemini_hindi():
    assert tts_split._pick_chunk_max_chars("gemini:flash25:Zephyr", "hi") == 1500


def test_pick_chunk_max_chars_gemini_arabic():
    assert tts_split._pick_chunk_max_chars("gemini:flash25:Zephyr", "ar") == 1500


def test_pick_chunk_max_chars_gemini_unknown_language_defaults_2000():
    assert tts_split._pick_chunk_max_chars("gemini:flash25:Zephyr", "xx") == 2000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test/test_tts_split_pcm.py::test_pick_chunk_max_chars_edge_voice -v`
Expected: FAIL — function not defined.

- [ ] **Step 3: Add the helper**

In `tts_split.py`, find:
```python
CHUNK_MAX_CHARS = 2000
```

Insert immediately AFTER it:
```python

# Lingue che richiedono chunk più piccoli per Gemini (espansione UTF-8 alta).
_GEMINI_SMALL_CHUNK_LANGS = {"zh", "ja", "hi", "ar"}
_GEMINI_SMALL_CHUNK_MAX = 1500


def _pick_chunk_max_chars(voice_id, language):
    """Sceglie il limite caratteri/chunk in base al motore e alla lingua.

    Gemini: 1500 per zh/ja/hi/ar, 2000 per le altre. Edge/Google: 2000 sempre.
    """
    if isinstance(voice_id, str) and voice_id.startswith("gemini:"):
        lang_code = (language or "").lower().split("-")[0]
        if lang_code in _GEMINI_SMALL_CHUNK_LANGS:
            return _GEMINI_SMALL_CHUNK_MAX
    return CHUNK_MAX_CHARS
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test/test_tts_split_pcm.py -v`
Expected: all green (12 cumulative tests in this file).

- [ ] **Step 5: Commit**

```
git add tts_split.py
git commit -m "feat(gemini-tts): language-aware chunk size for Gemini voices"
```

---

### Task 4: `_plan_chunks(info, max_chars=...)` parametric

`_plan_chunks` currently calls `split_text_into_chunks(full_text)` with default 2000. Make `max_chars` a parameter so the generation engine can pass the Gemini-aware value computed by `_pick_chunk_max_chars`.

**Files:**
- Modify: `tts_split.py:175` (`_plan_chunks` signature + call)

- [ ] **Step 1: Write the failing test**

Append to `test/test_tts_split_pcm.py`:
```python
class _FakeCh:
    def __init__(self, index, title, text):
        self.index = index
        self.title = title
        self.text = text


class _FakeInfo:
    def __init__(self, chapters):
        self.chapters = chapters


def test_plan_chunks_respects_max_chars_param():
    long_text = ". ".join([f"Frase numero {i}" for i in range(200)]) + "."
    info = _FakeInfo([_FakeCh(0, "Cap 1", long_text)])
    plan_2000 = tts_split._plan_chunks(info, max_chars=2000)
    plan_500 = tts_split._plan_chunks(info, max_chars=500)
    # Smaller limit ⇒ more chunks.
    assert len(plan_500) > len(plan_2000)
    for block in plan_500:
        assert block["chars"] <= 500 + 50  # tolerance for full-sentence fit


def test_plan_chunks_default_is_2000():
    long_text = ". ".join([f"Frase numero {i}" for i in range(100)]) + "."
    info = _FakeInfo([_FakeCh(0, "Cap 1", long_text)])
    plan_default = tts_split._plan_chunks(info)
    plan_explicit = tts_split._plan_chunks(info, max_chars=2000)
    assert len(plan_default) == len(plan_explicit)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test/test_tts_split_pcm.py::test_plan_chunks_respects_max_chars_param -v`
Expected: FAIL — `TypeError: _plan_chunks() got an unexpected keyword argument 'max_chars'`.

- [ ] **Step 3: Modify `_plan_chunks` signature and body**

In `tts_split.py:175`, replace:
```python
def _plan_chunks(info):
    """Costruisce la lista di chunk da generare per tutti i capitoli di un BookInfo."""
    plan = []
    for ch in info.chapters:
        clean_text = _strip_parenthetical(ch.text)
        clean_text = _ensure_heading_pause(clean_text)
        full_text = f"{ch.title}.\n\n{clean_text}"
        chunks = split_text_into_chunks(full_text)
```

With:
```python
def _plan_chunks(info, max_chars=CHUNK_MAX_CHARS):
    """Costruisce la lista di chunk da generare per tutti i capitoli di un BookInfo.

    max_chars: limite caratteri/chunk (default CHUNK_MAX_CHARS=2000).
               Per voci Gemini su lingue CJK/Hindi/Arabo passare 1500.
    """
    plan = []
    for ch in info.chapters:
        clean_text = _strip_parenthetical(ch.text)
        clean_text = _ensure_heading_pause(clean_text)
        full_text = f"{ch.title}.\n\n{clean_text}"
        chunks = split_text_into_chunks(full_text, max_chars=max_chars)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test/test_tts_split_pcm.py -v && python -m pytest test/ -v -k "not test_phase2 and not test_phase4_generation"`
Expected: tts_split_pcm tests green; no regressions elsewhere.

- [ ] **Step 5: Commit**

```
git add tts_split.py
git commit -m "refactor(tts-split): parametric max_chars in _plan_chunks"
```

---

### Task 5: `_engine_for_voice(voice)` dispatcher

Single source of truth for picking the engine. Returns `"gemini"`, `"google"`, or `"edge"`.

**Files:**
- Modify: `generation_engine.py` (add helper near top of `run_generation` definition area, just before `def run_generation`)

- [ ] **Step 1: Write the failing test**

Create `test/test_engine_dispatch.py`:
```python
"""Tests for _engine_for_voice dispatcher in generation_engine.py."""
import generation_engine


def test_engine_for_voice_gemini():
    assert generation_engine._engine_for_voice("gemini:flash25:Zephyr") == "gemini"
    assert generation_engine._engine_for_voice("gemini:flash31:Achernar") == "gemini"


def test_engine_for_voice_google():
    assert generation_engine._engine_for_voice("gcloud:it-IT-Chirp3-HD-Charon") == "google"


def test_engine_for_voice_edge_default():
    assert generation_engine._engine_for_voice("it-IT-IsabellaNeural") == "edge"
    assert generation_engine._engine_for_voice("en-US-GuyNeural") == "edge"


def test_engine_for_voice_empty_returns_edge():
    assert generation_engine._engine_for_voice("") == "edge"
    assert generation_engine._engine_for_voice(None) == "edge"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_engine_dispatch.py -v`
Expected: FAIL — `AttributeError: module 'generation_engine' has no attribute '_engine_for_voice'`.

- [ ] **Step 3: Add the helper to `generation_engine.py`**

In `generation_engine.py`, find the comment block (around line 1240):
```python
# ---------------------------------------------------------------------------
# run_generation — background thread TTS
# ---------------------------------------------------------------------------
```

Insert immediately BEFORE it:
```python
def _engine_for_voice(voice):
    """Sceglie il motore TTS dal voice ID.

    Prefissi:
      - "gemini:..."  → Gemini TTS (PCM native)
      - "gcloud:..."  → Google Cloud TTS Chirp3-HD (MP3)
      - altrimenti    → Microsoft Edge TTS (MP3, default)
    """
    if not voice:
        return "edge"
    if voice.startswith("gemini:"):
        return "gemini"
    if _google_tts is not None and _google_tts.is_google_voice(voice):
        return "google"
    return "edge"


```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_engine_dispatch.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```
git add generation_engine.py
git commit -m "feat(gemini-tts): _engine_for_voice dispatcher"
```

---

### Task 6: Chunk loop — Gemini PCM branch (single-file mode)

Inside `run_generation()` single-file path, replace the binary `use_google` dispatch with a 3-way branch on engine. For Gemini: write `.pcm` files, accumulate token usage in `gemini_usage` dict, call `gemini_tts.record_usage()` per chunk.

**Files:**
- Modify: `generation_engine.py:1243-1370` (`run_generation`, single-file branch)

- [ ] **Step 1: Replace the engine-detection line**

In `generation_engine.py:1257`, replace:
```python
    # Determina il motore TTS
    use_google = _google_tts is not None and _google_tts.is_google_voice(voice)
```

With:
```python
    # Determina il motore TTS (3-way: edge / google / gemini)
    engine = _engine_for_voice(voice)
    use_google = (engine == "google")
    use_gemini = (engine == "gemini")
```

- [ ] **Step 2: Compute language-aware chunk size**

In `generation_engine.py:1264`, replace:
```python
        plan = _plan_chunks(info)
```

With:
```python
        max_chars = tts_split._pick_chunk_max_chars(voice, getattr(info, "language", None) or "")
        plan = _plan_chunks(info, max_chars=max_chars)
```

Verify `import tts_split` exists at the top of `generation_engine.py`. If not, add it. (It should already be imported because `_plan_chunks` itself lives in `tts_split.py` and is re-exported. If `_plan_chunks` is imported directly via `from tts_split import _plan_chunks`, also add `from tts_split import _pick_chunk_max_chars`.)

Search for the existing import:
```
grep -n "_plan_chunks\|from tts_split" generation_engine.py
```

If imports use `from tts_split import _plan_chunks`, change to:
```python
from tts_split import _plan_chunks, _pick_chunk_max_chars
```

If imports use `import tts_split`, leave alone — the helper is reachable via `tts_split._pick_chunk_max_chars`.

- [ ] **Step 3: Initialize Gemini usage tracker**

In `generation_engine.py`, just before the line `if single_file:` (around line 1313), insert:
```python
        gemini_usage = {"input_tokens": 0, "output_tokens": 0, "model_key": None}
```

- [ ] **Step 4: Branch the chunk loop (single-file)**

In `generation_engine.py:1342-1349`, replace:
```python
                part_path = str(work_dir / f"chunk_{i:06d}.mp3")
                if use_google:
                    result = generate_chunk_mp3_google(block["text"], voice, rate, part_path)
                else:
                    result = loop.run_until_complete(generate_chunk_mp3(block["text"], voice, rate, part_path))
                if result is False:
                    failed_chunks += 1
                all_parts.append(part_path)
```

With:
```python
                if use_gemini:
                    part_path = str(work_dir / f"chunk_{i:06d}.pcm")
                    result = tts_split.generate_chunk_pcm_gemini(block["text"], voice, part_path)
                    if result is False:
                        failed_chunks += 1
                    else:
                        gemini_usage["input_tokens"] += result.get("input_tokens", 0)
                        gemini_usage["output_tokens"] += result.get("output_tokens", 0)
                        if not gemini_usage["model_key"]:
                            gemini_usage["model_key"] = result.get("model_key")
                else:
                    part_path = str(work_dir / f"chunk_{i:06d}.mp3")
                    if use_google:
                        result = generate_chunk_mp3_google(block["text"], voice, rate, part_path)
                    else:
                        result = loop.run_until_complete(generate_chunk_mp3(block["text"], voice, rate, part_path))
                    if result is False:
                        failed_chunks += 1
                all_parts.append(part_path)
```

- [ ] **Step 5: Per-chunk usage recording for Gemini**

In the same block, AFTER the `all_parts.append(part_path)` line, insert (still inside the `for i, block in enumerate(plan):` loop):
```python
                # Record Gemini usage per chunk (so partial completions on cancel still book it)
                if use_gemini and result is not False:
                    try:
                        gemini_tts.record_usage(
                            result.get("model_key", "flash25"),
                            result.get("input_tokens", 0),
                            result.get("output_tokens", 0),
                        )
                    except Exception as e:
                        print(f"[{job_id}] gemini_tts.record_usage failed (non-fatal): {e}")
```

Add `import gemini_tts` at the top of `generation_engine.py` alongside other module imports. Wrap in try/except so the engine module is optional:
```python
try:
    import gemini_tts
except ImportError:
    gemini_tts = None
```

- [ ] **Step 6: Fix silence handling for PCM (silence file is MP3 today)**

The chapter silence file (`_silence.mp3`) is generated once at line 1272-1273 and prepended to each chapter. For Gemini, we need a PCM variant. Around line 1271-1274, replace:
```python
        # Genera file di silenzio da preporre a ogni capitolo
        silence_path = str(work_dir / "_silence.mp3")
        silence_ok = _generate_silence_mp3(silence_path, CHAPTER_SILENCE_SEC)
```

With:
```python
        # Genera file di silenzio da preporre a ogni capitolo (PCM se Gemini, MP3 altrimenti)
        if use_gemini:
            silence_path = str(work_dir / "_silence.pcm")
            tts_split._generate_silence_pcm(silence_path, CHAPTER_SILENCE_SEC)
            silence_ok = os.path.exists(silence_path)
        else:
            silence_path = str(work_dir / "_silence.mp3")
            silence_ok = _generate_silence_mp3(silence_path, CHAPTER_SILENCE_SEC)
```

- [ ] **Step 7: Fix per-chunk duration tracking for PCM**

Around line 1358-1361, the code calls `_get_audio_duration_ms(part_path)` which uses ffprobe. ffprobe doesn't recognize headerless PCM. For Gemini chunks use `audio_utils.pcm_size_to_seconds` × 1000.

Replace:
```python
                # Aggiorna timing per capitolo M4B
                duration = _get_audio_duration_ms(part_path)
                if m4b_chapters:
                    m4b_chapters[-1]["end"] += duration
                current_ms += duration
```

With:
```python
                # Aggiorna timing per capitolo M4B
                if use_gemini and os.path.exists(part_path):
                    size_bytes = os.path.getsize(part_path)
                    duration = int(audio_utils.pcm_size_to_seconds(size_bytes) * 1000)
                else:
                    duration = _get_audio_duration_ms(part_path)
                if m4b_chapters:
                    m4b_chapters[-1]["end"] += duration
                current_ms += duration
```

Verify `import audio_utils` at the top of `generation_engine.py` (it should already be there).

Also fix the silence-duration handler at line 1317:
```python
            silence_ms = _get_audio_duration_ms(silence_path) if os.path.exists(silence_path) else 0
```

Replace with:
```python
            if use_gemini and os.path.exists(silence_path):
                silence_ms = int(audio_utils.pcm_size_to_seconds(os.path.getsize(silence_path)) * 1000)
            else:
                silence_ms = _get_audio_duration_ms(silence_path) if os.path.exists(silence_path) else 0
```

- [ ] **Step 8: Run existing tests to verify no regressions**

Run: `python -m pytest test/test_gemini_tts.py test/test_audio_utils_pcm.py test/test_tts_split_pcm.py test/test_engine_dispatch.py -v`
Expected: all green.

- [ ] **Step 9: Commit**

```
git add generation_engine.py
git commit -m "feat(gemini-tts): single-file chunk loop dispatches to Gemini PCM path"
```

---

### Task 7: Single-file assembly — PCM→MP3 / PCM→M4B direct

When all chunks of the book are PCM (i.e. `engine == "gemini"`), final assembly skips the MP3 intermediate for M4B output: `pcm_to_aac_m4b` is called directly on the list of PCM files. For MP3 output it calls `pcm_to_mp3` once on the list.

**Files:**
- Modify: `generation_engine.py:1370-1440` (assembly block in single-file path)

- [ ] **Step 1: Replace MP3 concat + M4B conversion with engine-aware branches**

In `generation_engine.py`, find around line 1371-1374:
```python
            print(f"[{job_id}] All chunks processed: {total_chunks} total, {failed_chunks} failed")
            job["progress_message"] = "Merging audio..."
            safe_name = _safe_filename(info.title) or "audiolibro"
            final_mp3 = str(output_dir / f"{safe_name}.mp3")
            _concatenate_mp3(all_parts, final_mp3)
            print(f"[{job_id}] MP3 merged: {final_mp3}, size={os.path.getsize(final_mp3) if os.path.exists(final_mp3) else 0}")
```

Replace with:
```python
            print(f"[{job_id}] All chunks processed: {total_chunks} total, {failed_chunks} failed")
            job["progress_message"] = "Merging audio..."
            safe_name = _safe_filename(info.title) or "audiolibro"

            if use_gemini:
                # Gemini: tutto PCM. Assembly diretto in base a output_format.
                final_mp3 = str(output_dir / f"{safe_name}.mp3")
                final_m4b = str(output_dir / f"{safe_name}.m4b")
                valid_m4b_ch = [c for c in m4b_chapters if c.get("end", 0) > c.get("start", 0)]
                cover_path = _prepare_m4b_cover_path(job, info.title, info.author, work_dir)

                if output_format in ('mp3', 'zip', 'zip_rss'):
                    # Solo MP3 finale richiesto
                    audio_utils.pcm_to_mp3(all_parts, final_mp3)
                    print(f"[{job_id}] PCM→MP3 merged: {final_mp3}, "
                          f"size={os.path.getsize(final_mp3) if os.path.exists(final_mp3) else 0}")
                else:
                    # M4B richiesto: percorso PCM→AAC diretto (niente MP3 intermedio)
                    job["progress_message"] = "Converting to M4B..."
                    print(f"[{job_id}] Starting PCM→M4B direct conversion: {final_m4b}")
                    m4b_ok = False
                    for attempt in range(1, 3):
                        if attempt > 1:
                            print(f"[{job_id}] Retrying PCM→M4B (attempt {attempt})...")
                        if audio_utils.pcm_to_aac_m4b(
                            all_parts, final_m4b,
                            chapters=valid_m4b_ch or None,
                            title=info.title, author=info.author or None,
                            cover_path=cover_path,
                            date=getattr(info, "date", None),
                            language=getattr(info, "language", None),
                            description=getattr(info, "description", None),
                        ):
                            job["output_m4b"] = final_m4b
                            job["m4b_failed"] = False
                            m4b_ok = True
                            break
                    if not m4b_ok:
                        job["m4b_failed"] = True
                        # Fallback: produci MP3 così l'utente ha qualcosa
                        audio_utils.pcm_to_mp3(all_parts, final_mp3)
                        print(f"[{job_id}] M4B failed, fallback MP3 produced: {final_mp3}")
            else:
                # Edge/Google: percorso storico (chunk MP3 → concat MP3 → eventuale M4B)
                final_mp3 = str(output_dir / f"{safe_name}.mp3")
                _concatenate_mp3(all_parts, final_mp3)
                print(f"[{job_id}] MP3 merged: {final_mp3}, "
                      f"size={os.path.getsize(final_mp3) if os.path.exists(final_mp3) else 0}")
```

- [ ] **Step 2: Skip the legacy `_convert_mp3_to_m4b` block for Gemini**

Below the block you just edited, the existing code (around line 1378-1428) does:
```python
            # Generate M4B too (skip for mp3-only format)
            if output_format != 'mp3':
                final_m4b = str(output_dir / f"{safe_name}.m4b")
                ...
```

Wrap this entire block in `if not use_gemini:` so the legacy MP3→M4B path runs only for Edge/Google. Replace:
```python
            # Generate M4B too (skip for mp3-only format)
            if output_format != 'mp3':
                final_m4b = str(output_dir / f"{safe_name}.m4b")
```

With:
```python
            # Generate M4B too (skip for mp3-only format and for Gemini, which already handled it)
            if not use_gemini and output_format != 'mp3':
                final_m4b = str(output_dir / f"{safe_name}.m4b")
```

The closing of the existing `if output_format != 'mp3':` block (the `else:` branch around line 1431 and the `output_files` assignment) is unaffected because Gemini's `job["output_m4b"]` is already set in Step 1.

- [ ] **Step 3: Set `output_files` for Gemini single-file mode**

Look around `generation_engine.py:1428-1439` for the `output_files` assignment. The current logic:
```python
            if output_format == 'm4b' and job.get("output_m4b"):
                job["output_files"] = [job["output_m4b"]]
                job["output_name"] = f"{safe_name}.m4b"
            else:
                job["output_files"] = [final_mp3]
                if job.get("output_m4b"):
                    job["output_name"] = f"{safe_name}.m4b"
                else:
                    job["output_name"] = f"{safe_name}.mp3"

                if os.path.exists(final_mp3):
                    job["bytes_generated"] = os.path.getsize(final_mp3)
```

For Gemini in `m4b` mode, `final_mp3` may not exist (we skipped MP3 intermediate). For Gemini in `mp3` mode it exists. This logic works for Gemini IF we also write `final_mp3` only when it makes sense. Since Step 1 writes `final_mp3` in `mp3`/`zip`/`zip_rss` branches and writes M4B (no mp3) in `m4b` branch, the `else:` branch above will set `output_files=[final_mp3]` even though the file doesn't exist for `m4b` mode.

Replace the block above with:
```python
            if output_format == 'm4b' and job.get("output_m4b"):
                job["output_files"] = [job["output_m4b"]]
                job["output_name"] = f"{safe_name}.m4b"
                if os.path.exists(job["output_m4b"]):
                    job["bytes_generated"] = os.path.getsize(job["output_m4b"])
            else:
                # Per Gemini in modalità m4b senza output_m4b (fallback dopo failure) usa MP3.
                # Per Edge/Google segue il percorso storico.
                if os.path.exists(final_mp3):
                    job["output_files"] = [final_mp3]
                    job["bytes_generated"] = os.path.getsize(final_mp3)
                else:
                    job["output_files"] = []
                if job.get("output_m4b"):
                    job["output_name"] = f"{safe_name}.m4b"
                else:
                    job["output_name"] = f"{safe_name}.mp3"
```

- [ ] **Step 4: Record final Gemini usage roll-up (optional log)**

Just before the existing `# Cleanup silence file` line (around 1583), add:
```python
        # Log roll-up Gemini usage (record_usage già chiamato per chunk)
        if use_gemini:
            print(f"[{job_id}] Gemini usage total: model={gemini_usage['model_key']} "
                  f"input_tok={gemini_usage['input_tokens']} "
                  f"output_tok={gemini_usage['output_tokens']}")
```

- [ ] **Step 5: Run pipeline tests**

Run: `python -m pytest test/test_engine_dispatch.py test/test_gemini_tts.py test/test_audio_utils_pcm.py -v`
Expected: all green.

- [ ] **Step 6: Commit**

```
git add generation_engine.py
git commit -m "feat(gemini-tts): single-file assembly PCM→MP3 and PCM→M4B direct"
```

---

### Task 8: Chunk loop + per-chapter assembly (`zip` / `zip_rss`)

Mirror Task 6+7 for the multi-file branch. PCM chunks per chapter → `pcm_to_mp3` per chapter → existing ZIP path unchanged.

**Files:**
- Modify: `generation_engine.py:1440-1580` (multi-file branch in `run_generation`)

- [ ] **Step 1: Branch chunk loop (multi-file)**

Find around line 1479-1486:
```python
                part_path = str(work_dir / f"chunk_{i:06d}.mp3")
                if use_google:
                    result = generate_chunk_mp3_google(block["text"], voice, rate, part_path)
                else:
                    result = loop.run_until_complete(generate_chunk_mp3(block["text"], voice, rate, part_path))
                if result is False:
                    failed_chunks += 1
                current_chapter_parts.append(part_path)
```

Replace with:
```python
                if use_gemini:
                    part_path = str(work_dir / f"chunk_{i:06d}.pcm")
                    result = tts_split.generate_chunk_pcm_gemini(block["text"], voice, part_path)
                    if result is False:
                        failed_chunks += 1
                    else:
                        gemini_usage["input_tokens"] += result.get("input_tokens", 0)
                        gemini_usage["output_tokens"] += result.get("output_tokens", 0)
                        if not gemini_usage["model_key"]:
                            gemini_usage["model_key"] = result.get("model_key")
                        try:
                            gemini_tts.record_usage(
                                result.get("model_key", "flash25"),
                                result.get("input_tokens", 0),
                                result.get("output_tokens", 0),
                            )
                        except Exception as e:
                            print(f"[{job_id}] gemini_tts.record_usage failed (non-fatal): {e}")
                else:
                    part_path = str(work_dir / f"chunk_{i:06d}.mp3")
                    if use_google:
                        result = generate_chunk_mp3_google(block["text"], voice, rate, part_path)
                    else:
                        result = loop.run_until_complete(generate_chunk_mp3(block["text"], voice, rate, part_path))
                    if result is False:
                        failed_chunks += 1
                current_chapter_parts.append(part_path)
```

- [ ] **Step 2: Branch per-chapter finalization (mid-loop)**

Find around lines 1454-1472:
```python
                if block["chapter_index"] != current_chapter_idx:
                    if current_chapter_parts and current_chapter_idx >= 0:
                        ch = chapter_by_idx[current_chapter_idx]
                        safe_title = _safe_filename(ch.title)[:50] or f"ch_{current_chapter_idx}"
                        out_num = output_num_by_idx.get(current_chapter_idx, current_chapter_idx)
                        mp3_path = str(output_dir / f"{out_num:03d}_{safe_title}.mp3")
                        _concatenate_mp3(current_chapter_parts, mp3_path)
                        mp3_files.append(mp3_path)

                        duration = _get_audio_duration_ms(mp3_path)
                        m4b_chapters.append({
                            "title": ch.title,
                            "start": current_ms,
                            "end": current_ms + duration
                        })
                        current_ms += duration

                        for p in current_chapter_parts:
                            if os.path.exists(p) and p != silence_path:
                                os.remove(p)
                    current_chapter_parts = []
                    current_chapter_idx = block["chapter_index"]
                    # Silenzio all'inizio del capitolo
                    if os.path.exists(silence_path):
                        current_chapter_parts.append(silence_path)
```

Replace the line `_concatenate_mp3(current_chapter_parts, mp3_path)` with:
```python
                        if use_gemini:
                            audio_utils.pcm_to_mp3(current_chapter_parts, mp3_path)
                        else:
                            _concatenate_mp3(current_chapter_parts, mp3_path)
```

(All other lines in this block stay the same — `_get_audio_duration_ms` works correctly on the produced MP3, regardless of source format.)

- [ ] **Step 3: Branch end-of-loop finalization**

Find around lines 1500-1518:
```python
            if current_chapter_parts and current_chapter_idx >= 0:
                ch = chapter_by_idx[current_chapter_idx]
                safe_title = _safe_filename(ch.title)[:50] or f"ch_{current_chapter_idx}"
                out_num = output_num_by_idx.get(current_chapter_idx, current_chapter_idx)
                mp3_path = str(output_dir / f"{out_num:03d}_{safe_title}.mp3")
                _concatenate_mp3(current_chapter_parts, mp3_path)
                mp3_files.append(mp3_path)
                ...
```

Same surgical change — replace the lone `_concatenate_mp3(current_chapter_parts, mp3_path)` line with:
```python
                if use_gemini:
                    audio_utils.pcm_to_mp3(current_chapter_parts, mp3_path)
                else:
                    _concatenate_mp3(current_chapter_parts, mp3_path)
```

- [ ] **Step 4: Disable background M4B-from-zip for Gemini**

Find around line 1552:
```python
            # background M4B generation even in ZIP mode (skip for mp3, zip and zip_rss formats)
            if output_format not in ('mp3', 'zip', 'zip_rss'):
```

For `zip_rss`/`zip` the existing branch is already skipped. But the M4B-from-zip code path uses `_concatenate_mp3` + `_convert_mp3_to_m4b` which works on the per-chapter MP3 files (already MP3 even when source was Gemini PCM). No change needed.

For Gemini with `output_format == 'm4b'` this branch is not entered (the single-file branch handles m4b). So leave the existing condition unchanged.

- [ ] **Step 5: Run regression tests**

Run: `python -m pytest test/test_engine_dispatch.py test/test_gemini_tts.py test/test_audio_utils_pcm.py test/test_tts_split_pcm.py -v`
Expected: all green.

- [ ] **Step 6: Commit**

```
git add generation_engine.py
git commit -m "feat(gemini-tts): per-chapter PCM→MP3 assembly for zip/zip_rss modes"
```

---

### Task 9: Cancellation cleanup for partial PCM

Cleanup of intermediate PCM files on cancel/error. Mirrors the existing temp file cleanup but recognises `.pcm` artifacts. Also: on cancel, we do NOT refund Gemini tokens (already paid via `record_usage`); we just log the partial usage.

**Files:**
- Modify: `generation_engine.py` — `except _CancelledError` block (around line 1642) and `_google_tts_refund_unused` parallel code path

- [ ] **Step 1: Locate the cancel/error blocks**

Search the file:
```
grep -n "_CancelledError\|shutil.rmtree" generation_engine.py
```
Expected sites:
- The `_CancelledError` raise inside the chunk loops (lines 1322, 1451)
- The catch block (around 1642)
- The `_google_tts_refund_unused` definition (around line 1016)

- [ ] **Step 2: Log partial Gemini usage on cancel**

Find the `except _CancelledError` block (around line 1642). It will look like:
```python
        except _CancelledError:
            print(f"[{job_id}] Generation cancelled")
            _set_job_status(job, "cancelled")
            if use_google:
                _google_tts_refund_unused(job_id, job)
            ...
```

Right after the `_google_tts_refund_unused` call (or right after `_set_job_status` if no Google refund), insert:
```python
            # Gemini: nessun refund (pay-per-call già record_usage per chunk).
            # Logghiamo solo il totale parziale per debug.
            if use_gemini:
                print(f"[{job_id}] Gemini partial usage (no refund): "
                      f"model={gemini_usage.get('model_key')} "
                      f"input_tok={gemini_usage.get('input_tokens', 0)} "
                      f"output_tok={gemini_usage.get('output_tokens', 0)}")
```

NOTE: `gemini_usage` may not be defined if the cancel happens before chunk loop start. Guard with `.get()` or initialise to an empty dict at the top of `try`. Safer: in `run_generation()` add a `gemini_usage = {}` initialisation at the very start of the `try:` block (before any branching).

Locate the line at `generation_engine.py:1259` `try:` and immediately after it (before `job["progress_message"] = "Preparing..."`) add:
```python
        gemini_usage = {"input_tokens": 0, "output_tokens": 0, "model_key": None}
```

(This replaces the Task 6 Step 3 insertion — move it earlier so it's defined before any cancel path.) Remove the duplicate from Task 6 Step 3 location if needed.

- [ ] **Step 3: Cleanup `.pcm` intermediate files on success**

The single-file path already deletes `chunk_*.mp3` files via the workdir rmtree at the end (search for `shutil.rmtree(work_dir)` or implicit cleanup). For Gemini, the same `work_dir` contains `chunk_*.pcm` instead.

Check whether the existing cleanup uses a glob or rmtree:
```
grep -n "chunk_.*\.mp3\|work_dir.*rmtree\|os.remove.*chunk_" generation_engine.py
```

If `shutil.rmtree(work_dir)` is used: nothing to change (catches both `.mp3` and `.pcm`).

If specific patterns like `chunk_*.mp3` are referenced for deletion: extend to `.pcm` too. Most likely the existing cleanup loops over `all_parts` (list of paths) and `os.remove(p)` — this also works for both formats. Verify by searching:
```
grep -n "all_parts\|for p in" generation_engine.py | head -20
```

If `all_parts` is iterated for cleanup, no change needed. If a glob pattern is used, add the `.pcm` variant.

For this plan: ASSUME no change needed (the most common pattern). If verification in Step 4 shows leftover `.pcm` files in `work_dir`, add an explicit cleanup right before the success return:
```python
        # Cleanup PCM intermediates if Gemini path
        if use_gemini:
            for p in all_parts if single_file else []:
                if p.endswith(".pcm") and os.path.exists(p) and p != silence_path:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            if os.path.exists(silence_path):
                try:
                    os.remove(silence_path)
                except OSError:
                    pass
```

- [ ] **Step 4: Verify with a dry-run of the engine**

Run a quick smoke that the modified `run_generation` imports cleanly and `_engine_for_voice` is callable:
```
python -c "import generation_engine; print('ok'); print('gemini:', generation_engine._engine_for_voice('gemini:flash25:Zephyr'))"
```
Expected: `ok` then `gemini: gemini`.

- [ ] **Step 5: Commit**

```
git add generation_engine.py
git commit -m "feat(gemini-tts): partial usage log on cancel, no refund (pay-per-call)"
```

---

### Task 10: Bootstrap `gemini_tts.init(_DATA_DIR)`

Initialize the Gemini module at application startup, alongside other module initializations.

**Files:**
- Modify: `audiobook_app.py` (startup section, near `google_tts.init()` call)

- [ ] **Step 1: Find current init pattern**

Search:
```
grep -n "google_tts.init\|community_store.init\|community_translator" audiobook_app.py | head -10
```
Locate the line where `google_tts.init(_DATA_DIR)` is called.

- [ ] **Step 2: Add import**

Near the top of `audiobook_app.py`, where `google_tts` is imported (search `import google_tts`), add immediately after:
```python
try:
    import gemini_tts
except ImportError:
    gemini_tts = None
    print("[startup] gemini_tts module not available (google-genai not installed)")
```

- [ ] **Step 3: Initialize at startup**

Right after the `google_tts.init(_DATA_DIR)` call, add:
```python
if gemini_tts is not None:
    try:
        gemini_tts.init(_DATA_DIR)
        if gemini_tts.is_available():
            print("[startup] Gemini TTS enabled")
        else:
            print("[startup] Gemini TTS initialized but disabled (ABM_GEMINI_API_KEY not set)")
    except Exception as e:
        print(f"[startup] Gemini TTS init failed: {e}")
        gemini_tts = None
```

- [ ] **Step 4: Smoke-import check**

Run:
```
python -c "import audiobook_app; print('boot ok')"
```
Expected: prints `[startup] gemini_tts module not available` or `[startup] Gemini TTS initialized but disabled ...` then `boot ok`.

- [ ] **Step 5: Commit**

```
git add audiobook_app.py
git commit -m "feat(gemini-tts): bootstrap gemini_tts.init at app startup"
```

---

### Task 11: `/api/voices` merges Gemini voices + shim

Extend `_fetch_voices()` to merge Gemini voices alongside Edge and Google. Since `gemini_tts.get_voices()` entries lack `gender`/`gender_icon` fields (required by the sort and the frontend optgroup), shim them at merge time.

**Files:**
- Modify: `audiobook_app.py:571-635` (`_fetch_voices`)

- [ ] **Step 1: Write the failing test**

Create `test/test_voices_endpoint.py`:
```python
"""Tests for /api/voices Gemini merge."""
import os
import pytest
import audiobook_app


@pytest.fixture(autouse=True)
def reset_voices_cache():
    audiobook_app._invalidate_voices_cache()
    yield
    audiobook_app._invalidate_voices_cache()


def test_get_voices_includes_gemini_when_module_present(monkeypatch):
    """If gemini_tts is loaded, voices catalog should include 'gemini' engine entries."""
    if audiobook_app.gemini_tts is None:
        pytest.skip("gemini_tts module not importable")

    voices = audiobook_app.get_voices()
    # Should have at least one language (it/en/...) with gemini voices
    found_gemini = False
    for lang_code, lang_data in voices.items():
        if lang_code.startswith("_"):
            continue
        for v in lang_data.get("voices", []):
            if v.get("engine") == "gemini":
                found_gemini = True
                assert "gender" in v
                assert "gender_icon" in v
                assert v["id"].startswith("gemini:")
                break
        if found_gemini:
            break
    assert found_gemini, "No Gemini voices found in catalog"


def test_get_voices_gemini_entry_shape(monkeypatch):
    if audiobook_app.gemini_tts is None:
        pytest.skip("gemini_tts module not importable")

    voices = audiobook_app.get_voices()
    it_voices = voices.get("it", {}).get("voices", [])
    gemini_it = [v for v in it_voices if v.get("engine") == "gemini"]
    assert len(gemini_it) >= 30  # at least one model × 30 voices
    sample = gemini_it[0]
    for key in ("id", "name", "gender", "gender_icon", "locale", "engine"):
        assert key in sample, f"Missing key: {key}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_voices_endpoint.py -v`
Expected: FAIL — Gemini voices not in catalog.

- [ ] **Step 3: Add the merge block**

In `audiobook_app.py:626`, immediately AFTER the Google TTS merge `except` block:
```python
        except Exception as e:
            print(f"Error merging Google voices: {e}")
```

Insert:
```python

    # 3. Gemini TTS (Optional)
    if gemini_tts is not None:
        try:
            gem_dict = gemini_tts.get_voices()
            for lc_short, v_list in gem_dict.items():
                if lc_short not in languages:
                    languages[lc_short] = {
                        "name": LOCALE_NAMES.get(lc_short, lc_short.upper()),
                        "voices": []
                    }
                # Gemini voices are multilingual / genderless from the API.
                # Shim gender fields so existing sort + frontend grouping work.
                for v in v_list:
                    v.setdefault("gender", "Neutral")
                    v.setdefault("gender_icon", "★")
                languages[lc_short]["voices"].extend(v_list)
        except Exception as e:
            print(f"Error merging Gemini voices: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test/test_voices_endpoint.py -v`
Expected: 2 passed.

- [ ] **Step 5: Verify endpoint shape with a real call**

Run:
```
python -c "import audiobook_app; v=audiobook_app.get_voices(); print('langs:', list(v.keys())[:5]); print('first IT voice keys:', list(v.get('it', {}).get('voices', [{}])[0].keys()))"
```
Expected: `langs: ['it', 'en', 'fr', 'de', 'es']` (approx) and the keys list contains `id, name, gender, gender_icon, locale, engine`.

- [ ] **Step 6: Commit**

```
git add audiobook_app.py
git commit -m "feat(gemini-tts): merge Gemini voices into /api/voices catalog"
```

---

### Task 12: `/api/preview_audio` dispatch + cap enforcement

Extend preview endpoint to recognize Gemini voices. Enforce per-cookie preview cap (5/24h rolling). On cap exhaustion return HTTP 429 with JSON `{error, used, cap, reset_in_seconds}`.

**Files:**
- Modify: `audiobook_app.py:3738-3812` (`preview_audio` route)

- [ ] **Step 1: Locate the preview route**

Search:
```
grep -n "def preview_audio\|/api/preview_audio" audiobook_app.py
```

- [ ] **Step 2: Read the current handler**

Read lines 3738-3812 of `audiobook_app.py` to confirm structure (use the actual line numbers found in Step 1; lines may shift after Task 10's edits).

- [ ] **Step 3: Insert cap check + Gemini dispatch**

Find the line that detects Google:
```python
    use_google_preview = google_tts is not None and google_tts.is_google_voice(voice)
```

Replace with:
```python
    use_google_preview = google_tts is not None and google_tts.is_google_voice(voice)
    use_gemini_preview = gemini_tts is not None and voice.startswith("gemini:")

    # Preview cap per Gemini (rolling 24h per cookie)
    if use_gemini_preview:
        if not gemini_tts.is_available():
            return jsonify({"error": "gemini_tts_not_configured"}), 503
        client_id = _get_client_id() or "anon"
        cap_check = gemini_tts.check_preview_cap(client_id)
        if not cap_check.get("allowed"):
            return jsonify({
                "error": "preview_cap_exceeded",
                "used": cap_check.get("used", 0),
                "cap": cap_check.get("cap", 5),
                "reset_in_seconds": cap_check.get("reset_in_seconds", 0),
            }), 429
```

- [ ] **Step 4: Add the Gemini synthesis branch**

Find the if/else block:
```python
    if use_google_preview:
        google_tts.synthesize(preview_text, voice, rate, str(preview_path))
        google_tts.deduct_chars(len(preview_text))
    else:
        # edge_tts.Communicate(...).save(...)
```

Replace with:
```python
    if use_gemini_preview:
        # Native output is PCM — convert to MP3 inline for browser playback.
        pcm_tmp = str(preview_path) + ".pcm"
        try:
            result = gemini_tts.synthesize(preview_text, voice, output_path=pcm_tmp)
            audio_utils.pcm_to_mp3([pcm_tmp], str(preview_path))
            gemini_tts.record_usage(
                result.get("model_key", "flash25"),
                result.get("input_tokens", 0),
                result.get("output_tokens", 0),
            )
            gemini_tts.increment_preview(client_id)
        finally:
            if os.path.exists(pcm_tmp):
                try:
                    os.remove(pcm_tmp)
                except OSError:
                    pass
    elif use_google_preview:
        google_tts.synthesize(preview_text, voice, rate, str(preview_path))
        google_tts.deduct_chars(len(preview_text))
    else:
        # edge_tts path (unchanged)
```

(Leave the original edge-tts code intact under the `else:` branch.)

- [ ] **Step 5: Smoke check endpoint registration**

Run:
```
python -c "import audiobook_app; rules=[r.rule for r in audiobook_app.app.url_map.iter_rules() if 'preview' in r.rule]; print(rules)"
```
Expected: list including `/api/preview_audio/<job_id>`.

- [ ] **Step 6: Manual test (no real API needed for 503/429 paths)**

Without `ABM_GEMINI_API_KEY` set, send a request with a Gemini voice to the preview endpoint — expect HTTP 503 `gemini_tts_not_configured`. Skip if real testing not needed; the code path is exercised in Task 15 smoke test.

- [ ] **Step 7: Commit**

```
git add audiobook_app.py
git commit -m "feat(gemini-tts): /api/preview_audio dispatches to Gemini and enforces 5/24h cap"
```

---

### Task 13: `/api/generate` availability validation

If client requests a Gemini voice but `gemini_tts.is_available()` returns False, refuse with HTTP 400 BEFORE spawning the thread.

**Files:**
- Modify: `audiobook_app.py` — `/api/generate` route (find via grep)

- [ ] **Step 1: Locate the route**

```
grep -n "def generate\|@.*'/api/generate'" audiobook_app.py
```

- [ ] **Step 2: Add validation block**

Inside the handler, after the voice is extracted from the request payload but BEFORE any heavy lifting (like budget calc or thread spawn). The current flow has `voice = data.get("voice")` somewhere near the top. After that line, insert:
```python
    if voice and voice.startswith("gemini:"):
        if gemini_tts is None or not gemini_tts.is_available():
            return jsonify({"error": "gemini_tts_not_configured"}), 400
```

- [ ] **Step 3: Smoke check**

```
python -c "import audiobook_app; print('available:', audiobook_app.gemini_tts.is_available() if audiobook_app.gemini_tts else 'no module')"
```
Expected with no API key: `available: False`.

- [ ] **Step 4: Commit**

```
git add audiobook_app.py
git commit -m "feat(gemini-tts): /api/generate refuses Gemini voice when module disabled"
```

---

### Task 14: Frontend selector + preview cap toast

Add `_isGeminiVoice` helper. Add Gemini optgroup in `updVoices()`. Handle HTTP 429 from preview endpoint with a translated user-facing message.

**Files:**
- Modify: `static/js/app.js:659-712` (`_isGoogleVoice`, `updVoices`, preview fetch)
- Modify: `templates/_fragments/i18n_data.js` (add 2 keys for cap error)

- [ ] **Step 1: Add `_isGeminiVoice` helper**

In `static/js/app.js:659`, after:
```javascript
function _isGoogleVoice(id){return id&&id.startsWith('gcloud:')}
```

Insert:
```javascript
function _isGeminiVoice(id){return id&&id.startsWith('gemini:')}
```

- [ ] **Step 2: Extend `updVoices` to show Gemini optgroup**

In `static/js/app.js:670-712`, after the Google voices block (line ~700), and BEFORE the default-voice selection line:
```javascript
  const dv=edgeVoices.find(...)||lang.voices[0];
```

Insert:
```javascript
  // Voci Gemini TTS (se presenti)
  const geminiVoices=lang.voices.filter(v=>v.engine==='gemini');
  if(geminiVoices.length>0){
    lg='';
    for(const v of geminiVoices){
      // Le voci Gemini condividono il gender "Neutral" — non raggruppiamo per gender
      if(lg!=='gemini-grp'){
        const g=document.createElement('optgroup');
        g.label='★ Gemini TTS';
        sel.appendChild(g);lg='gemini-grp';
      }
      const o=document.createElement('option');o.value=v.id;
      o.textContent=v.gender_icon+' '+v.name+' ('+v.locale+') ★';
      o.classList.add('gemini-voice');
      sel.lastElementChild.appendChild(o);
    }
  }
```

- [ ] **Step 3: Add CSS class hint**

In `static/js/app.js` or the relevant CSS section (search for `.gcloud-voice` to find the styling pattern). If present, mirror it. If not, this step is a no-op (the class is set, CSS optional). Search:
```
grep -n ".gcloud-voice" static/js/app.js templates/_fragments/html_head.html
```
If a CSS rule exists, copy it for `.gemini-voice` — e.g. in `html_head.html` add next to the existing rule:
```css
.gemini-voice { color: #8a4eff; font-weight: 500; }
```

- [ ] **Step 4: Handle HTTP 429 in preview fetch**

In `static/js/app.js`, find the preview audio fetch (around line 767-769):
```javascript
const url = '/api/preview_audio/' + bookData.job_id + '?voice=' + encodeURIComponent(voice) + '&rate=' + encodeURIComponent(rate);
```

Find the corresponding response handler. Wrap the `fetch(...)` chain to handle 429:
```javascript
// Existing pattern likely:
// fetch(url).then(r => r.blob()).then(blob => ...)
// Replace with:
fetch(url).then(r => {
  if (r.status === 429) {
    return r.json().then(data => {
      const minutes = Math.ceil((data.reset_in_seconds || 0) / 60);
      alert(t('gemini_preview_cap_exceeded').replace('{n}', data.used).replace('{cap}', data.cap).replace('{min}', minutes));
      throw new Error('preview_cap_exceeded');
    });
  }
  if (r.status === 503) {
    alert(t('gemini_not_configured'));
    throw new Error('gemini_not_configured');
  }
  if (!r.ok) throw new Error('preview_failed_' + r.status);
  return r.blob();
}).then(blob => { /* existing playback code */ })
.catch(err => { console.error('Preview error:', err); });
```

Note: search for the actual fetch call and adapt to the existing promise chain style. The key change is the 429/503 branches before `.blob()`.

- [ ] **Step 5: Add i18n keys**

In `templates/_fragments/i18n_data.js`, find the `i18n` object (or equivalent map of language → strings). For each language (`it`, `en`, `fr`, `es`, `de`, `zh`, `hi`), add two keys. Italian:
```javascript
gemini_preview_cap_exceeded: "Hai usato {n}/{cap} preview Gemini. Riprova fra {min} min.",
gemini_not_configured: "Servizio Gemini TTS non configurato. Contatta l'amministratore.",
```

English:
```javascript
gemini_preview_cap_exceeded: "You used {n}/{cap} Gemini previews. Try again in {min} min.",
gemini_not_configured: "Gemini TTS service not configured. Contact the administrator.",
```

French:
```javascript
gemini_preview_cap_exceeded: "Vous avez utilisé {n}/{cap} aperçus Gemini. Réessayez dans {min} min.",
gemini_not_configured: "Service Gemini TTS non configuré. Contactez l'administrateur.",
```

Spanish:
```javascript
gemini_preview_cap_exceeded: "Has usado {n}/{cap} previsualizaciones Gemini. Inténtalo en {min} min.",
gemini_not_configured: "Servicio Gemini TTS no configurado. Contacta al administrador.",
```

German:
```javascript
gemini_preview_cap_exceeded: "Sie haben {n}/{cap} Gemini-Vorschauen verwendet. Versuchen Sie es in {min} Min. erneut.",
gemini_not_configured: "Gemini-TTS-Dienst nicht konfiguriert. Kontaktieren Sie den Administrator.",
```

Chinese:
```javascript
gemini_preview_cap_exceeded: "您已使用 {n}/{cap} 个 Gemini 预览。请在 {min} 分钟后重试。",
gemini_not_configured: "Gemini TTS 服务未配置。请联系管理员。",
```

Hindi:
```javascript
gemini_preview_cap_exceeded: "आपने {n}/{cap} Gemini पूर्वावलोकन का उपयोग किया है। {min} मिनट में पुनः प्रयास करें।",
gemini_not_configured: "Gemini TTS सेवा कॉन्फ़िगर नहीं है। व्यवस्थापक से संपर्क करें।",
```

- [ ] **Step 6: Smoke check the page loads**

Run the app: `python audiobook_app.py` and load `http://localhost:5601`. Open browser devtools console; type:
```javascript
typeof _isGeminiVoice  // expect "function"
t('gemini_not_configured')  // expect the localized string
```

Kill the dev server (Ctrl+C).

- [ ] **Step 7: Commit**

```
git add static/js/app.js templates/_fragments/i18n_data.js
git commit -m "feat(gemini-tts): frontend voice selector and preview cap UI"
```

---

### Task 15: End-to-end integration smoke test

Mock `gemini_tts.synthesize` to return zeroed PCM bytes and full result dicts. Run `run_generation` in-process across the four output formats (`m4b`, `mp3`, `zip`, `zip_rss`) and assert artifacts exist with correct extensions.

**Files:**
- Create: `test/test_gemini_pipeline.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_gemini_pipeline.py`:
```python
"""End-to-end integration tests for Gemini TTS pipeline.

Mocks gemini_tts.synthesize to avoid real API calls. Asserts that
run_generation produces the expected artifact for each output_format.
"""
import os
import shutil
import pytest
from pathlib import Path

import generation_engine
import tts_split
import gemini_tts


ffmpeg_missing = shutil.which("ffmpeg") is None


class _Ch:
    def __init__(self, index, title, text):
        self.index = index
        self.title = title
        self.text = text


class _Info:
    def __init__(self):
        self.title = "Test Audiobook"
        self.author = "Test Author"
        self.language = "it"
        self.date = None
        self.description = None
        self.chapters = [
            _Ch(0, "Capitolo 1", "Questa è una frase di prova per il capitolo uno."),
            _Ch(1, "Capitolo 2", "E questa è una frase per il capitolo due, più lunga del primo."),
        ]


@pytest.fixture
def mock_gemini_synth(monkeypatch, tmp_path):
    """Fake synthesize that writes 24000 zero bytes (0.5s of PCM) and returns metadata."""
    def fake_synth(text, voice_id, output_path=None, **kw):
        n_bytes = 24000  # 0.5 seconds of 24kHz mono 16-bit
        with open(output_path, "wb") as f:
            f.write(b"\x00" * n_bytes)
        return {
            "audio_bytes": n_bytes,
            "audio_seconds": 0.5,
            "input_tokens": max(1, len(text) // 4),
            "output_tokens": 12,
            "model_key": "flash25",
        }

    monkeypatch.setattr("gemini_tts.synthesize", fake_synth)


@pytest.fixture
def setup_engine(tmp_path, monkeypatch):
    """Configure generation_engine with a temp upload dir and minimal job state."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr("generation_engine._upload_dir", upload_dir)
    jobs = {}
    monkeypatch.setattr("generation_engine._jobs", jobs)
    monkeypatch.setattr("generation_engine._set_job_status", lambda j, s: j.update({"status": s}))
    # Init gemini_tts so record_usage doesn't crash
    gemini_tts.init(str(tmp_path / "gemini_data"))
    return upload_dir, jobs


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_pipeline_gemini_m4b(setup_engine, mock_gemini_synth):
    upload_dir, jobs = setup_engine
    job_id = "test_m4b"
    jobs[job_id] = {"gen_epoch": 0, "last_poll": 0, "email_registered": True}

    info = _Info()
    generation_engine.run_generation(
        job_id, info,
        voice="gemini:flash25:Zephyr",
        rate="+0%",
        single_file=True,
        output_format="m4b",
    )

    job = jobs[job_id]
    assert job.get("output_m4b"), "M4B output not produced"
    assert os.path.exists(job["output_m4b"])
    assert job["output_m4b"].endswith(".m4b")
    assert job.get("m4b_failed") is False


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_pipeline_gemini_mp3(setup_engine, mock_gemini_synth):
    upload_dir, jobs = setup_engine
    job_id = "test_mp3"
    jobs[job_id] = {"gen_epoch": 0, "last_poll": 0, "email_registered": True}

    info = _Info()
    generation_engine.run_generation(
        job_id, info,
        voice="gemini:flash25:Zephyr",
        rate="+0%",
        single_file=True,
        output_format="mp3",
    )

    job = jobs[job_id]
    assert job.get("output_files"), "No output files"
    mp3 = job["output_files"][0]
    assert mp3.endswith(".mp3")
    assert os.path.exists(mp3)


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_pipeline_gemini_zip(setup_engine, mock_gemini_synth):
    upload_dir, jobs = setup_engine
    job_id = "test_zip"
    jobs[job_id] = {"gen_epoch": 0, "last_poll": 0, "email_registered": True}

    info = _Info()
    generation_engine.run_generation(
        job_id, info,
        voice="gemini:flash25:Zephyr",
        rate="+0%",
        single_file=False,
        output_format="zip",
    )

    job = jobs[job_id]
    assert job.get("output_zip"), "ZIP not produced"
    assert os.path.exists(job["output_zip"])
    assert job["output_zip"].endswith(".zip")
    # 2 chapters → 2 MP3 files inside
    assert len(job.get("output_files", [])) == 2


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_pipeline_gemini_zip_rss(setup_engine, mock_gemini_synth):
    upload_dir, jobs = setup_engine
    job_id = "test_zip_rss"
    jobs[job_id] = {"gen_epoch": 0, "last_poll": 0, "email_registered": True}

    info = _Info()
    generation_engine.run_generation(
        job_id, info,
        voice="gemini:flash25:Zephyr",
        rate="+0%",
        single_file=False,
        output_format="zip_rss",
        podcast_base_url="https://example.com/audio",
    )

    job = jobs[job_id]
    assert job.get("output_zip")
    assert job.get("podcast_ready") is True
    assert job.get("podcast_rss_included") is True


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_pipeline_engine_dispatch_edge_unchanged(setup_engine, monkeypatch):
    """Sanity: an Edge voice does NOT route through Gemini code."""
    upload_dir, jobs = setup_engine
    job_id = "test_edge"
    jobs[job_id] = {"gen_epoch": 0, "last_poll": 0, "email_registered": True}

    # Mock edge_tts so we don't hit the network
    async def fake_edge(text, voice, rate, output_path, max_retries=3):
        with open(output_path, "wb") as f:
            f.write(b"\xff\xfb" + b"\x00" * 100)  # MP3 header + bytes
        return None

    monkeypatch.setattr("tts_split.generate_chunk_mp3", fake_edge)

    info = _Info()
    generation_engine.run_generation(
        job_id, info,
        voice="it-IT-IsabellaNeural",  # edge voice
        rate="+0%",
        single_file=True,
        output_format="mp3",
    )

    job = jobs[job_id]
    # As long as it didn't crash and produced *some* output_files, dispatch worked
    assert "output_files" in job
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test/test_gemini_pipeline.py -v`
Expected: tests fail (most likely due to missing helpers in `generation_engine` private state, like `_upload_dir`, `_jobs`, `_set_job_status`, or `_get_audio_duration_ms` requiring a real audio file).

- [ ] **Step 3: Fix test fixtures based on failure output**

The fake PCM (24000 zero bytes per chunk) is headerless. `_get_audio_duration_ms` may crash on it for non-Gemini paths, but for Gemini we routed it via `audio_utils.pcm_size_to_seconds` in Task 6 Step 7. Verify that branch is taken.

For the Edge test (which writes a 102-byte MP3 with a valid header), `_get_audio_duration_ms` may return 0 — that's fine, it just means M4B chapters are empty (and m4b isn't requested in `output_format=mp3`).

Iterate until all 5 tests pass. Likely fixes:
- Patch `_get_audio_duration_ms` in the fixture to return a constant for MP3 fake files: `monkeypatch.setattr("generation_engine._get_audio_duration_ms", lambda p: 500)`
- Ensure `_prepare_m4b_cover_path` doesn't crash on missing cover: monkeypatch to `lambda j, t, a, w: None`

Add these to `setup_engine`:
```python
    monkeypatch.setattr("generation_engine._prepare_m4b_cover_path", lambda j, t, a, w: None)
    # _get_audio_duration_ms is fine for real MP3s but our fake MP3 yields 0; that's ok.
```

- [ ] **Step 4: Run full pipeline tests until all pass**

Run: `python -m pytest test/test_gemini_pipeline.py -v --tb=short`
Expected (after fixture iteration): 5 passed (or 4 passed + 1 skipped if ffmpeg missing).

- [ ] **Step 5: Run full Gemini-related test suite**

Run:
```
python -m pytest test/test_gemini_tts.py test/test_audio_utils_pcm.py test/test_tts_split_pcm.py test/test_engine_dispatch.py test/test_voices_endpoint.py test/test_gemini_pipeline.py -v
```
Expected: all green.

- [ ] **Step 6: Commit**

```
git add test/test_gemini_pipeline.py
git commit -m "test(gemini-tts): end-to-end pipeline integration smoke"
```
(NOTE: `test/` is gitignored — this commit will fail. Tests stay local per project convention. Skip Step 6.)

---

## Definition of Done (Plan B)

After all tasks:

- ✅ `_engine_for_voice("gemini:...")` returns `"gemini"` and routes chunk generation through `gemini_tts.synthesize`.
- ✅ Single-file `m4b` output uses `pcm_to_aac_m4b` direct path (no MP3 intermediate file produced) when voice is Gemini.
- ✅ Single-file `mp3` output uses `pcm_to_mp3` one-shot from PCM chunks when voice is Gemini.
- ✅ `zip` / `zip_rss` modes produce per-chapter MP3s via `pcm_to_mp3(chapter_chunks, chapter_mp3)` for Gemini.
- ✅ Edge and Google paths produce byte-identical output to pre-Plan-B (regression check).
- ✅ `/api/voices` includes Gemini entries with `engine: "gemini"` and shimmed `gender/gender_icon` fields.
- ✅ `/api/preview_audio` returns HTTP 429 with JSON body when per-cookie preview cap is exhausted.
- ✅ `/api/preview_audio` returns HTTP 503 when Gemini voice is requested but `is_available()` is False.
- ✅ `/api/generate` returns HTTP 400 immediately when Gemini voice is requested but module disabled.
- ✅ Frontend voice dropdown shows a Gemini optgroup with `★` markers when Gemini voices are available.
- ✅ Frontend handles HTTP 429 from preview with a translated user-facing message in 7 UI languages.
- ✅ Per-chunk `gemini_tts.record_usage()` is called so partial completions on cancel still book usage.
- ✅ Cancel during Gemini generation logs partial usage and does NOT refund (pay-per-call model; refunds are Plan C territory).
- ✅ All 80+ existing tests in `test/test_gemini_tts.py` + `test/test_audio_utils_pcm.py` still pass.
- ✅ New tests pass: `test_tts_split_pcm.py`, `test_engine_dispatch.py`, `test_voices_endpoint.py`, `test_gemini_pipeline.py`.
- ✅ Manual smoke run: launch app, select a Gemini voice in UI, preview, generate a 2-chapter test book in each of `m4b/mp3/zip/zip_rss` modes (real API key required for live test; pipeline tests cover the mocked variant).

---

## Plan B → Plan C handoff

These items are tagged for Plan C (the payment integration plan):

1. **Cost calc + paywall:** `/api/generate` must compute `gemini_tts.estimate_book_cost(...)` and require PayPal/voucher payment when `user_price_eur > 0` (i.e. above free threshold).
2. **Budget reservation:** Mirror `google_tts.reserve_chars` / `refund_chars` for tokens. On Gemini job start, deduct projected `output_tokens` from a per-user prepaid balance; refund unused on cancel/error.
3. **Voucher cross-purpose:** Extend `payment.py` voucher schema with a `purpose: "llm" | "gemini_tts"` field. Allow vouchers issued for LLM refunds to be redeemed against Gemini TTS and vice versa.
4. **Admin reporting:** `/api/admin/gemini_tts_status` endpoint (mirrors `/api/admin/google_tts_status`) returning monthly usage breakdown by model + total EUR cost.

---

## Self-review notes

- Tasks 1-4 produce isolated tts_split helpers — safe to land independently.
- Task 5 adds dispatcher in `generation_engine.py` but doesn't call it yet — landable independently.
- Tasks 6-9 modify `run_generation` body. Land them in order; each commit leaves `run_generation` functional (Edge and Google paths still produce identical output at every commit boundary because Gemini branches are guarded by `if use_gemini:`).
- Tasks 10-13 are independent server-side wiring; land after Task 9 so the engine is ready.
- Task 14 (frontend) is independent; can land any time after Task 11.
- Task 15 (integration tests) is the final gate — must pass before declaring Plan B done.
