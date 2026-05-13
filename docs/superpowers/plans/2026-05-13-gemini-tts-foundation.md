# Gemini TTS Integration — Plan A: Foundation Module

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone `gemini_tts.py` module + PCM audio utilities that can: synthesize audio via Gemini 2.5/3.1 Flash TTS, estimate book costs with configurable margins, track usage/previews, and encode PCM chunks directly to M4B (single AAC encode) or MP3 — all testable via pytest + CLI script with no impact on existing Chirp3-HD/Edge TTS paths.

**Architecture:** New module `gemini_tts.py` parallel to `google_tts.py` using `google-genai` SDK with API key auth (separate from Chirp3-HD service account). Two model variants (Flash 2.5 / Flash 3.1) exposed via voice ID prefix `gemini:<model_key>:<voice_name>`. Pricing computed from token estimates (input chars→tokens by language, output audio seconds→tokens at 25 tok/s), with per-model margin and PayPal fee compensation. PCM (24kHz mono 16-bit) is the native output format; new `audio_utils.py` helpers handle PCM→AAC for direct M4B encoding (96 kbps mono) and PCM→MP3 for legacy paths. No integration with `tts_split.py`, `generation_engine.py`, or `audiobook_app.py` in this plan — those are Plan B.

**Tech Stack:** Python 3.11, `google-genai` SDK, FFmpeg (system binary, already required), `pytest` for tests, JSON file persistence (no DB), Flask not used in this plan (module is framework-independent).

---

## File Structure

**To create:**
- `gemini_tts.py` — main module: voices, parsing, token estimation, pricing, usage tracking, preview cap, synthesis
- `test/test_gemini_tts.py` — pytest unit tests (mocks google-genai client)
- `test/test_audio_utils_pcm.py` — pytest tests for new PCM helpers (uses real FFmpeg)
- `scripts/gemini_tts_cli.py` — manual integration CLI for real API smoke test

**To modify:**
- `audio_utils.py` — add `pcm_concat()`, `pcm_to_mp3()`, `pcm_to_aac_m4b()`, `pcm_size_to_seconds()`
- `PARAMETRI_CONFIGURAZIONE.md` — document new `ABM_GEMINI_*` env vars
- `requirements.txt` — add `google-genai>=0.3.0`

**Out of scope (Plan B/C/D):**
- Integration into `tts_split.py` or `generation_engine.py`
- API endpoints (`/api/gemini_estimate`, `/api/gemini_pay/*`)
- `audiobook_app.py` modifications
- `payment.py` extension for cross-purpose vouchers
- Frontend exposure

---

## Key Constants and Defaults

These values are referenced across multiple tasks. Define them once in `gemini_tts.py`:

| Constant | Value | Source |
|---|---|---|
| `AUDIO_TOKENS_PER_SECOND` | `25` | Doc Gemini 3.1 Flash TTS |
| `CHARS_PER_AUDIO_SECOND` | `15` | Standard narration rate |
| `CHARS_PER_TOKEN_BY_LANG` | `{"it":4.0,"en":4.0,"fr":4.0,"es":4.0,"de":4.0,"pt":4.0,"zh":1.5,"ja":1.5,"hi":2.0,"ar":2.0,"ru":3.0,"default":4.0}` | Gemini tokenizer SentencePiece |
| `MAX_CHUNK_CHARS_BY_LANG` | `{"zh":1500,"ja":1500,"hi":1500,"ar":1500,"default":2000}` | User decision (d) |
| `MAX_BYTES_PER_CALL` | `4000` | Gemini API hard limit |
| `AUDIO_SAMPLE_RATE` | `24000` | Gemini TTS native |
| `AUDIO_CHANNELS` | `1` | Mono |
| `AUDIO_SAMPLE_WIDTH_BYTES` | `2` | 16-bit PCM |
| `AAC_BITRATE_M4B` | `"96k"` | User decision (b) |
| `MP3_BITRATE_DEFAULT` | `"64k"` | Coerente con edge-tts |

**Model registry:**

```python
GEMINI_MODELS = {
    "flash25": {
        "id": "gemini-2.5-flash-preview-tts",
        "label": "Gemini 2.5 Flash TTS",
        "input_usd_per_mtok": 0.50,
        "output_usd_per_mtok": 10.00,
        "default_margin_percent": 35.0,
    },
    "flash31": {
        "id": "gemini-3.1-flash-preview-tts",
        "label": "Gemini 3.1 Flash TTS",
        "input_usd_per_mtok": 1.00,
        "output_usd_per_mtok": 20.00,
        "default_margin_percent": 25.0,
    },
}
```

**30 Gemini voices** (model-agnostic, identical roster on 2.5 and 3.1):

```python
GEMINI_VOICE_NAMES = [
    "Achernar", "Achird", "Algenib", "Algieba", "Alnilam",
    "Aoede", "Autonoe", "Callirrhoe", "Charon", "Despina",
    "Enceladus", "Erinome", "Fenrir", "Gacrux", "Iapetus",
    "Kore", "Laomedeia", "Leda", "Orus", "Pulcherrima",
    "Puck", "Rasalgethi", "Sadachbia", "Sadaltager", "Schedar",
    "Sulafat", "Umbriel", "Vindemiatrix", "Zephyr", "Zubenelgenubi",
]
```

Voices are multilingual (each voice supports 70+ languages). For voice listing we expose them under each supported language. For Plan A keep the language list aligned with current UI: `["it","en","fr","es","de","zh","hi"]`.

---

## Environment Variables

All vars optional with safe defaults. Documented in `PARAMETRI_CONFIGURAZIONE.md` at Task 22.

```
ABM_GEMINI_API_KEY                          (empty) — disables module
ABM_GEMINI_USE_VERTEX                       false
ABM_GEMINI_VERTEX_CREDENTIALS_FILE          (empty)
ABM_GEMINI_25FLASH_INPUT_USD_PER_MTOK       0.50
ABM_GEMINI_25FLASH_OUTPUT_USD_PER_MTOK      10.00
ABM_GEMINI_31FLASH_INPUT_USD_PER_MTOK       1.00
ABM_GEMINI_31FLASH_OUTPUT_USD_PER_MTOK      20.00
ABM_GEMINI_USD_EUR_RATE                     0.86
ABM_GEMINI_25FLASH_MARGIN_PERCENT           35
ABM_GEMINI_31FLASH_MARGIN_PERCENT           25
ABM_GEMINI_PAYPAL_FIXED_FEE_EUR             0.34
ABM_GEMINI_PAYPAL_PERCENT_FEE               3.4
ABM_GEMINI_FREE_THRESHOLD_EUR               0.50
ABM_GEMINI_PREVIEW_CAP_PER_DAY              5
ABM_GEMINI_MAX_BYTES_PER_CALL               4000
```

---

## Tasks

### Task 1: Module skeleton with constants and env-var loading

**Files:**
- Create: `gemini_tts.py`
- Create: `test/test_gemini_tts.py`

- [ ] **Step 1: Write the failing test**

`test/test_gemini_tts.py`:
```python
"""Tests for gemini_tts module."""
import os
import pytest
import gemini_tts


def test_module_constants_present():
    assert gemini_tts.AUDIO_TOKENS_PER_SECOND == 25
    assert gemini_tts.CHARS_PER_AUDIO_SECOND == 15
    assert gemini_tts.AUDIO_SAMPLE_RATE == 24000
    assert gemini_tts.AUDIO_CHANNELS == 1
    assert gemini_tts.AAC_BITRATE_M4B == "96k"


def test_model_registry_has_two_models():
    assert "flash25" in gemini_tts.GEMINI_MODELS
    assert "flash31" in gemini_tts.GEMINI_MODELS
    assert gemini_tts.GEMINI_MODELS["flash25"]["id"] == "gemini-2.5-flash-preview-tts"
    assert gemini_tts.GEMINI_MODELS["flash31"]["id"] == "gemini-3.1-flash-preview-tts"


def test_thirty_voices_defined():
    assert len(gemini_tts.GEMINI_VOICE_NAMES) == 30
    assert "Zephyr" in gemini_tts.GEMINI_VOICE_NAMES
    assert "Puck" in gemini_tts.GEMINI_VOICE_NAMES
    assert "Kore" in gemini_tts.GEMINI_VOICE_NAMES


def test_env_var_override_margin(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_25FLASH_MARGIN_PERCENT", "50")
    import importlib
    importlib.reload(gemini_tts)
    assert gemini_tts.get_margin_percent("flash25") == 50.0
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest test/test_gemini_tts.py -v
```
Expected: `ModuleNotFoundError: No module named 'gemini_tts'`

- [ ] **Step 3: Write minimal module**

`gemini_tts.py`:
```python
"""
gemini_tts.py — Gemini 2.5/3.1 Flash TTS integration.

Parallel to google_tts.py for Chirp3-HD. Uses google-genai SDK with separate
API key (or Vertex AI service account). Native output is PCM 24kHz mono 16-bit.

Plan A scope: standalone module — synthesis + pricing + usage tracking + preview cap.
Integration with tts_split / generation_engine / audiobook_app is Plan B.
"""

import os

# Audio output constants
AUDIO_TOKENS_PER_SECOND = 25
CHARS_PER_AUDIO_SECOND = 15
AUDIO_SAMPLE_RATE = 24000
AUDIO_CHANNELS = 1
AUDIO_SAMPLE_WIDTH_BYTES = 2
AAC_BITRATE_M4B = "96k"
MP3_BITRATE_DEFAULT = "64k"

# Per-language token ratios (chars per token)
CHARS_PER_TOKEN_BY_LANG = {
    "it": 4.0, "en": 4.0, "fr": 4.0, "es": 4.0, "de": 4.0, "pt": 4.0,
    "ru": 3.0, "zh": 1.5, "ja": 1.5, "hi": 2.0, "ar": 2.0,
    "default": 4.0,
}

# Per-language chunk size (chars) — accounts for UTF-8 byte expansion
MAX_CHUNK_CHARS_BY_LANG = {
    "zh": 1500, "ja": 1500, "hi": 1500, "ar": 1500,
    "default": 2000,
}

MAX_BYTES_PER_CALL = int(os.environ.get("ABM_GEMINI_MAX_BYTES_PER_CALL", "4000"))


def _f(env, default):
    try:
        return float(os.environ.get(env, str(default)).replace(",", "."))
    except (ValueError, TypeError):
        return float(default)


GEMINI_MODELS = {
    "flash25": {
        "id": "gemini-2.5-flash-preview-tts",
        "label": "Gemini 2.5 Flash TTS",
        "input_usd_per_mtok": _f("ABM_GEMINI_25FLASH_INPUT_USD_PER_MTOK", 0.50),
        "output_usd_per_mtok": _f("ABM_GEMINI_25FLASH_OUTPUT_USD_PER_MTOK", 10.00),
        "default_margin_percent": _f("ABM_GEMINI_25FLASH_MARGIN_PERCENT", 35.0),
    },
    "flash31": {
        "id": "gemini-3.1-flash-preview-tts",
        "label": "Gemini 3.1 Flash TTS",
        "input_usd_per_mtok": _f("ABM_GEMINI_31FLASH_INPUT_USD_PER_MTOK", 1.00),
        "output_usd_per_mtok": _f("ABM_GEMINI_31FLASH_OUTPUT_USD_PER_MTOK", 20.00),
        "default_margin_percent": _f("ABM_GEMINI_31FLASH_MARGIN_PERCENT", 25.0),
    },
}

USD_EUR_RATE = _f("ABM_GEMINI_USD_EUR_RATE", 0.86)
PAYPAL_FIXED_FEE_EUR = _f("ABM_GEMINI_PAYPAL_FIXED_FEE_EUR", 0.34)
PAYPAL_PERCENT_FEE = _f("ABM_GEMINI_PAYPAL_PERCENT_FEE", 3.4)
FREE_THRESHOLD_EUR = _f("ABM_GEMINI_FREE_THRESHOLD_EUR", 0.50)
PREVIEW_CAP_PER_DAY = int(_f("ABM_GEMINI_PREVIEW_CAP_PER_DAY", 5))

GEMINI_VOICE_NAMES = [
    "Achernar", "Achird", "Algenib", "Algieba", "Alnilam",
    "Aoede", "Autonoe", "Callirrhoe", "Charon", "Despina",
    "Enceladus", "Erinome", "Fenrir", "Gacrux", "Iapetus",
    "Kore", "Laomedeia", "Leda", "Orus", "Pulcherrima",
    "Puck", "Rasalgethi", "Sadachbia", "Sadaltager", "Schedar",
    "Sulafat", "Umbriel", "Vindemiatrix", "Zephyr", "Zubenelgenubi",
]


def get_margin_percent(model_key):
    """Margine corrente per il modello (legge env var aggiornata)."""
    if model_key == "flash25":
        return _f("ABM_GEMINI_25FLASH_MARGIN_PERCENT", 35.0)
    if model_key == "flash31":
        return _f("ABM_GEMINI_31FLASH_MARGIN_PERCENT", 25.0)
    raise ValueError(f"Unknown model_key: {model_key}")
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest test/test_gemini_tts.py -v
```
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```
git add gemini_tts.py test/test_gemini_tts.py
git commit -m "feat(gemini-tts): module skeleton with constants and env-var loading"
```

---

### Task 2: Voice ID parsing

**Files:**
- Modify: `gemini_tts.py` (add functions)
- Modify: `test/test_gemini_tts.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Add to `test/test_gemini_tts.py`:
```python
def test_is_gemini_voice_recognizes_prefix():
    assert gemini_tts.is_gemini_voice("gemini:flash25:Zephyr") is True
    assert gemini_tts.is_gemini_voice("gcloud:it-IT-Chirp3-HD-Achernar") is False
    assert gemini_tts.is_gemini_voice("it-IT-IsabellaNeural") is False
    assert gemini_tts.is_gemini_voice("") is False


def test_parse_voice_id_returns_tuple():
    model_key, model_id, voice_name = gemini_tts.parse_voice_id("gemini:flash25:Zephyr")
    assert model_key == "flash25"
    assert model_id == "gemini-2.5-flash-preview-tts"
    assert voice_name == "Zephyr"


def test_parse_voice_id_flash31():
    model_key, model_id, voice_name = gemini_tts.parse_voice_id("gemini:flash31:Puck")
    assert model_key == "flash31"
    assert model_id == "gemini-3.1-flash-preview-tts"
    assert voice_name == "Puck"


def test_parse_voice_id_rejects_unknown_model():
    with pytest.raises(ValueError, match="Unknown Gemini model"):
        gemini_tts.parse_voice_id("gemini:flash99:Zephyr")


def test_parse_voice_id_rejects_unknown_voice():
    with pytest.raises(ValueError, match="Unknown Gemini voice"):
        gemini_tts.parse_voice_id("gemini:flash25:UnknownVoiceXYZ")


def test_parse_voice_id_rejects_bad_format():
    with pytest.raises(ValueError, match="Invalid Gemini voice ID format"):
        gemini_tts.parse_voice_id("gemini:Zephyr")
    with pytest.raises(ValueError, match="Invalid Gemini voice ID format"):
        gemini_tts.parse_voice_id("not-a-gemini-voice")
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest test/test_gemini_tts.py -v
```
Expected: 6 new tests fail with `AttributeError: module 'gemini_tts' has no attribute 'is_gemini_voice'`.

- [ ] **Step 3: Implement functions**

Append to `gemini_tts.py`:
```python
def is_gemini_voice(voice_id):
    """True se il voice_id ha prefisso 'gemini:'."""
    return isinstance(voice_id, str) and voice_id.startswith("gemini:")


def parse_voice_id(voice_id):
    """Estrae (model_key, model_full_id, voice_name) da 'gemini:flash25:Zephyr'.

    Raises ValueError se formato non valido, modello sconosciuto o voce sconosciuta.
    """
    if not isinstance(voice_id, str) or not voice_id.startswith("gemini:"):
        raise ValueError(f"Invalid Gemini voice ID format: {voice_id!r}")
    parts = voice_id.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid Gemini voice ID format: {voice_id!r} (expected 'gemini:<model>:<voice>')")
    _, model_key, voice_name = parts
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown Gemini model: {model_key!r} (allowed: {list(GEMINI_MODELS.keys())})")
    if voice_name not in GEMINI_VOICE_NAMES:
        raise ValueError(f"Unknown Gemini voice: {voice_name!r}")
    return model_key, GEMINI_MODELS[model_key]["id"], voice_name
```

- [ ] **Step 4: Run tests**

```
pytest test/test_gemini_tts.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```
git add gemini_tts.py test/test_gemini_tts.py
git commit -m "feat(gemini-tts): voice ID parsing with model + voice validation"
```

---

### Task 3: Voice catalog (get_voices)

**Files:**
- Modify: `gemini_tts.py`
- Modify: `test/test_gemini_tts.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_get_voices_returns_dict_by_language():
    voices = gemini_tts.get_voices()
    assert isinstance(voices, dict)
    for lang in ["it", "en", "fr", "es", "de", "zh", "hi"]:
        assert lang in voices, f"Missing language: {lang}"


def test_each_language_has_all_voices_x_models():
    voices = gemini_tts.get_voices()
    for lang, lang_voices in voices.items():
        # 30 voices × 2 models = 60 entries per language
        assert len(lang_voices) == 60, f"Lang {lang} has {len(lang_voices)} voices, expected 60"


def test_voice_entry_shape():
    voices = gemini_tts.get_voices()
    sample = voices["it"][0]
    assert "id" in sample
    assert sample["id"].startswith("gemini:")
    assert "name" in sample
    assert "locale" in sample
    assert "engine" in sample and sample["engine"] == "gemini"
    assert "model_key" in sample
    assert "model_label" in sample


def test_voice_ids_are_unique():
    voices = gemini_tts.get_voices()
    all_ids = [v["id"] for lang_voices in voices.values() for v in lang_voices]
    # IDs are repeated across languages (multilingual voices), but unique within a language
    for lang, lang_voices in voices.items():
        ids = [v["id"] for v in lang_voices]
        assert len(ids) == len(set(ids)), f"Duplicate IDs in lang {lang}"
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: `AttributeError: module 'gemini_tts' has no attribute 'get_voices'`

- [ ] **Step 3: Implement get_voices**

Append to `gemini_tts.py`:
```python
SUPPORTED_UI_LANGUAGES = ["it", "en", "fr", "es", "de", "zh", "hi"]
_LANG_LOCALE = {
    "it": "it-IT", "en": "en-US", "fr": "fr-FR", "es": "es-ES",
    "de": "de-DE", "zh": "zh-CN", "hi": "hi-IN",
}


def get_voices():
    """Catalogo voci Gemini per lingua.

    Le voci Gemini sono multilingue: ogni voce appare sotto ogni lingua UI
    supportata. 30 voci × 2 modelli = 60 entry per lingua.

    Returns:
        dict {lang_code: [voice_entry, ...]}
    """
    out = {}
    for lang in SUPPORTED_UI_LANGUAGES:
        locale = _LANG_LOCALE.get(lang, lang)
        lang_voices = []
        for model_key, model_info in GEMINI_MODELS.items():
            for voice_name in GEMINI_VOICE_NAMES:
                lang_voices.append({
                    "id": f"gemini:{model_key}:{voice_name}",
                    "name": f"{voice_name} ({model_info['label']})",
                    "locale": locale,
                    "engine": "gemini",
                    "model_key": model_key,
                    "model_label": model_info["label"],
                })
        out[lang] = lang_voices
    return out
```

- [ ] **Step 4: Run tests**

```
pytest test/test_gemini_tts.py -v
```
Expected: all pass (13 total).

- [ ] **Step 5: Commit**

```
git add gemini_tts.py test/test_gemini_tts.py
git commit -m "feat(gemini-tts): voice catalog exposing 60 voices per UI language"
```

---

### Task 4: Token estimation (chars → input/output tokens)

**Files:**
- Modify: `gemini_tts.py`
- Modify: `test/test_gemini_tts.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_estimate_input_tokens_italian():
    # 1000 chars Italian / 4 chars per token = 250 tokens
    assert gemini_tts.estimate_input_tokens("a" * 1000, "it") == 250


def test_estimate_input_tokens_chinese():
    # 1000 chars Chinese / 1.5 chars per token = 666 tokens
    assert gemini_tts.estimate_input_tokens("a" * 1000, "zh") == 666


def test_estimate_input_tokens_unknown_language_uses_default():
    # default is 4.0 chars/token
    assert gemini_tts.estimate_input_tokens("a" * 1000, "xx") == 250


def test_estimate_audio_seconds():
    # 1500 chars / 15 chars per second = 100 seconds
    assert gemini_tts.estimate_audio_seconds("a" * 1500) == pytest.approx(100.0, abs=0.1)


def test_estimate_output_tokens():
    # 1500 chars → 100s → 100 × 25 = 2500 tokens
    assert gemini_tts.estimate_output_tokens("a" * 1500) == 2500


def test_estimate_zero_text():
    assert gemini_tts.estimate_input_tokens("", "it") == 0
    assert gemini_tts.estimate_audio_seconds("") == 0.0
    assert gemini_tts.estimate_output_tokens("") == 0
```

- [ ] **Step 2: Run tests** → fail (functions missing).

- [ ] **Step 3: Implement**

Append to `gemini_tts.py`:
```python
def estimate_input_tokens(text, language="it"):
    """Stima token input dal testo. Usa CHARS_PER_TOKEN_BY_LANG."""
    if not text:
        return 0
    ratio = CHARS_PER_TOKEN_BY_LANG.get(language, CHARS_PER_TOKEN_BY_LANG["default"])
    return int(len(text) / ratio)


def estimate_audio_seconds(text):
    """Stima durata audio in secondi a velocità di narrazione standard."""
    if not text:
        return 0.0
    return len(text) / CHARS_PER_AUDIO_SECOND


def estimate_output_tokens(text):
    """Stima token audio output. 25 tok/s × secondi stimati."""
    return int(estimate_audio_seconds(text) * AUDIO_TOKENS_PER_SECOND)
```

- [ ] **Step 4: Run tests** → pass.

- [ ] **Step 5: Commit**

```
git add gemini_tts.py test/test_gemini_tts.py
git commit -m "feat(gemini-tts): token estimation (input by lang, output 25 tok/s)"
```

---

### Task 5: Google cost calculation

**Files:**
- Modify: `gemini_tts.py`
- Modify: `test/test_gemini_tts.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_google_cost_flash25():
    # 125k input + 833k output tokens
    # = 125000 × 0.50/M + 833000 × 10.00/M = $0.0625 + $8.33 = $8.3925
    # × 0.86 EUR/USD = €7.218
    cost = gemini_tts.estimate_google_cost_eur(125_000, 833_000, "flash25")
    assert cost == pytest.approx(7.22, abs=0.02)


def test_google_cost_flash31():
    # 125k input + 833k output
    # = 125000 × 1.00/M + 833000 × 20.00/M = $0.125 + $16.66 = $16.785
    # × 0.86 = €14.43
    cost = gemini_tts.estimate_google_cost_eur(125_000, 833_000, "flash31")
    assert cost == pytest.approx(14.44, abs=0.02)


def test_google_cost_zero():
    assert gemini_tts.estimate_google_cost_eur(0, 0, "flash25") == 0.0


def test_google_cost_breakdown():
    breakdown = gemini_tts.google_cost_breakdown(125_000, 833_000, "flash25")
    assert "input_usd" in breakdown
    assert "output_usd" in breakdown
    assert "total_usd" in breakdown
    assert "total_eur" in breakdown
    assert breakdown["input_usd"] == pytest.approx(0.0625, abs=0.0001)
    assert breakdown["output_usd"] == pytest.approx(8.33, abs=0.01)
```

- [ ] **Step 2: Run tests** → fail.

- [ ] **Step 3: Implement**

Append to `gemini_tts.py`:
```python
def google_cost_breakdown(input_tokens, output_tokens, model_key):
    """Costo Google netto, dettagliato USD/EUR."""
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown model_key: {model_key}")
    m = GEMINI_MODELS[model_key]
    input_usd = input_tokens * m["input_usd_per_mtok"] / 1_000_000
    output_usd = output_tokens * m["output_usd_per_mtok"] / 1_000_000
    total_usd = input_usd + output_usd
    return {
        "input_usd": input_usd,
        "output_usd": output_usd,
        "total_usd": total_usd,
        "total_eur": total_usd * USD_EUR_RATE,
    }


def estimate_google_cost_eur(input_tokens, output_tokens, model_key):
    """Costo Google totale in EUR (semplificato, restituisce solo il totale)."""
    return google_cost_breakdown(input_tokens, output_tokens, model_key)["total_eur"]
```

- [ ] **Step 4: Run tests** → pass.

- [ ] **Step 5: Commit**

```
git add gemini_tts.py test/test_gemini_tts.py
git commit -m "feat(gemini-tts): Google cost calculation in EUR by model"
```

---

### Task 6: User price calculation (margin + PayPal fee compensation)

**Files:**
- Modify: `gemini_tts.py`
- Modify: `test/test_gemini_tts.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_user_price_flash25_with_margin():
    # google_cost €7.22, margin 35%, PayPal fee 0.34 fixed + 3.4%
    # base = 7.22 × 1.35 = 9.747
    # gross = (9.747 + 0.34) / (1 - 0.034) = 10.087 / 0.966 = 10.44
    result = gemini_tts.compute_user_price_eur(7.22, "flash25")
    assert result["user_price_eur"] == pytest.approx(10.44, abs=0.05)
    assert result["margin_percent"] == 35.0
    assert result["is_free"] is False


def test_user_price_flash31_with_margin():
    # google_cost €14.44, margin 25%
    # base = 14.44 × 1.25 = 18.05
    # gross = (18.05 + 0.34) / 0.966 = 19.04
    result = gemini_tts.compute_user_price_eur(14.44, "flash31")
    assert result["user_price_eur"] == pytest.approx(19.04, abs=0.05)
    assert result["margin_percent"] == 25.0


def test_user_price_below_free_threshold():
    # very small cost
    result = gemini_tts.compute_user_price_eur(0.10, "flash25")
    # 0.10 × 1.35 = 0.135, gross = (0.135 + 0.34) / 0.966 = 0.491 < 0.50
    assert result["is_free"] is True
    assert result["user_price_eur"] == 0.0


def test_user_price_zero_cost():
    result = gemini_tts.compute_user_price_eur(0.0, "flash25")
    assert result["user_price_eur"] == 0.0
    assert result["is_free"] is True


def test_user_price_rejects_negative():
    with pytest.raises(ValueError):
        gemini_tts.compute_user_price_eur(-1.0, "flash25")
```

- [ ] **Step 2: Run tests** → fail.

- [ ] **Step 3: Implement**

Append to `gemini_tts.py`:
```python
def compute_user_price_eur(google_cost_eur, model_key):
    """Calcola prezzo finale all'utente da costo Google netto.

    Formula:
        base   = google_cost × (1 + margin/100)
        gross  = (base + PAYPAL_FIXED_FEE) / (1 - PAYPAL_PERCENT_FEE/100)
        user_price = round(gross, 2)

    Sotto FREE_THRESHOLD_EUR: user_price = 0.0, is_free = True.
    """
    if google_cost_eur < 0:
        raise ValueError("google_cost_eur must be >= 0")
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown model_key: {model_key}")

    margin_pct = get_margin_percent(model_key)
    base_eur = google_cost_eur * (1.0 + margin_pct / 100.0)
    paypal_factor = 1.0 - (PAYPAL_PERCENT_FEE / 100.0)
    if paypal_factor <= 0:
        raise ValueError("PAYPAL_PERCENT_FEE >= 100, invalid config")
    gross = (base_eur + PAYPAL_FIXED_FEE_EUR) / paypal_factor
    user_price = round(gross, 2)
    is_free = user_price < FREE_THRESHOLD_EUR
    return {
        "google_cost_eur": round(google_cost_eur, 4),
        "margin_percent": margin_pct,
        "base_price_eur": round(base_eur, 4),
        "user_price_eur": 0.0 if is_free else user_price,
        "is_free": is_free,
        "paypal_fixed_fee_eur": PAYPAL_FIXED_FEE_EUR,
        "paypal_percent_fee": PAYPAL_PERCENT_FEE,
        "free_threshold_eur": FREE_THRESHOLD_EUR,
    }
```

- [ ] **Step 4: Run tests** → pass.

- [ ] **Step 5: Commit**

```
git add gemini_tts.py test/test_gemini_tts.py
git commit -m "feat(gemini-tts): user price with margin and PayPal fee compensation"
```

---

### Task 7: End-to-end book cost estimation

**Files:**
- Modify: `gemini_tts.py`
- Modify: `test/test_gemini_tts.py`

- [ ] **Step 1: Write the failing tests**

```python
class _FakeChapter:
    def __init__(self, text):
        self.text = text
        self.char_count = len(text)


def test_estimate_book_cost_500k_italian_flash25():
    chapters = [_FakeChapter("a" * 100_000) for _ in range(5)]  # 500k chars total
    result = gemini_tts.estimate_book_cost(
        chapters, voice_id="gemini:flash25:Zephyr", language="it"
    )
    assert result["chars_total"] == 500_000
    assert result["input_tokens_est"] == 125_000  # 500k / 4
    assert result["audio_seconds_est"] == pytest.approx(33333.33, abs=1)  # 500k / 15
    assert result["output_tokens_est"] == 833_333  # 33333 × 25 (floor)
    assert result["google_cost_eur"] == pytest.approx(7.22, abs=0.05)
    assert result["user_price_eur"] == pytest.approx(10.44, abs=0.10)
    assert result["estimated_audio_minutes"] == pytest.approx(555.56, abs=0.5)
    assert result["model_key"] == "flash25"
    assert result["language"] == "it"
    assert result["is_free"] is False


def test_estimate_book_cost_short_text_is_free():
    chapters = [_FakeChapter("Brevissimo testo.")]
    result = gemini_tts.estimate_book_cost(
        chapters, voice_id="gemini:flash25:Zephyr", language="it"
    )
    assert result["is_free"] is True
    assert result["user_price_eur"] == 0.0


def test_estimate_book_cost_empty_chapters():
    result = gemini_tts.estimate_book_cost(
        [], voice_id="gemini:flash25:Zephyr", language="it"
    )
    assert result["chars_total"] == 0
    assert result["user_price_eur"] == 0.0
    assert result["is_free"] is True


def test_estimate_book_cost_rejects_non_gemini_voice():
    chapters = [_FakeChapter("ciao")]
    with pytest.raises(ValueError):
        gemini_tts.estimate_book_cost(
            chapters, voice_id="gcloud:it-IT-Chirp3-HD-Achernar", language="it"
        )
```

- [ ] **Step 2: Run tests** → fail.

- [ ] **Step 3: Implement**

Append to `gemini_tts.py`:
```python
def estimate_book_cost(chapters, voice_id, language="it"):
    """Stima costo end-to-end della generazione audio di un libro.

    Args:
        chapters: lista di oggetti con attributo `.text` (es. Chapter dataclass).
        voice_id: deve iniziare con 'gemini:'.
        language: ISO 639-1 (it/en/fr/es/de/zh/hi/...). Default 'it'.

    Returns:
        dict con chars_total, input_tokens_est, audio_seconds_est,
        output_tokens_est, google_cost_eur, user_price_eur, is_free,
        estimated_audio_minutes, model_key, language, model_label.
    """
    model_key, _, _ = parse_voice_id(voice_id)

    chars_per_chapter = []
    chars_total = 0
    full_text_for_estimate = []
    for ch in chapters:
        txt = getattr(ch, "text", "") or ""
        chars_per_chapter.append(len(txt))
        chars_total += len(txt)
        full_text_for_estimate.append(txt)

    combined = "".join(full_text_for_estimate)
    input_tokens = estimate_input_tokens(combined, language)
    audio_seconds = estimate_audio_seconds(combined)
    output_tokens = estimate_output_tokens(combined)

    breakdown = google_cost_breakdown(input_tokens, output_tokens, model_key)
    price = compute_user_price_eur(breakdown["total_eur"], model_key)

    return {
        "chars_total": chars_total,
        "chars_per_chapter": chars_per_chapter,
        "input_tokens_est": input_tokens,
        "audio_seconds_est": audio_seconds,
        "output_tokens_est": output_tokens,
        "google_cost_eur": breakdown["total_eur"],
        "google_cost_breakdown": breakdown,
        "user_price_eur": price["user_price_eur"],
        "is_free": price["is_free"],
        "margin_percent": price["margin_percent"],
        "estimated_audio_minutes": audio_seconds / 60.0,
        "model_key": model_key,
        "model_label": GEMINI_MODELS[model_key]["label"],
        "language": language,
    }
```

- [ ] **Step 4: Run tests** → pass.

- [ ] **Step 5: Commit**

```
git add gemini_tts.py test/test_gemini_tts.py
git commit -m "feat(gemini-tts): end-to-end book cost estimation"
```

---

### Task 8: Byte-size safety check + per-language chunk size

**Files:**
- Modify: `gemini_tts.py`
- Modify: `test/test_gemini_tts.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_check_text_byte_size_ok():
    ok, size = gemini_tts.check_text_byte_size("a" * 1000)
    assert ok is True
    assert size == 1000


def test_check_text_byte_size_too_big():
    # Latin: 1 char = 1 byte; 5000 chars > 4000 byte cap
    ok, size = gemini_tts.check_text_byte_size("a" * 5000)
    assert ok is False
    assert size == 5000


def test_check_text_byte_size_chinese_expansion():
    # CJK: typically 3 bytes per char UTF-8
    cjk_text = "中" * 1500  # 4500 bytes > 4000
    ok, size = gemini_tts.check_text_byte_size(cjk_text)
    assert ok is False
    assert size > 4000


def test_get_max_chunk_chars_default():
    assert gemini_tts.get_max_chunk_chars("it") == 2000
    assert gemini_tts.get_max_chunk_chars("en") == 2000
    assert gemini_tts.get_max_chunk_chars("xx") == 2000


def test_get_max_chunk_chars_cjk_hindi():
    assert gemini_tts.get_max_chunk_chars("zh") == 1500
    assert gemini_tts.get_max_chunk_chars("ja") == 1500
    assert gemini_tts.get_max_chunk_chars("hi") == 1500
    assert gemini_tts.get_max_chunk_chars("ar") == 1500
```

- [ ] **Step 2: Run tests** → fail.

- [ ] **Step 3: Implement**

Append to `gemini_tts.py`:
```python
def check_text_byte_size(text):
    """Verifica che il testo stia nel cap MAX_BYTES_PER_CALL (UTF-8).

    Returns:
        (ok: bool, size_bytes: int)
    """
    if not text:
        return True, 0
    size = len(text.encode("utf-8"))
    return size <= MAX_BYTES_PER_CALL, size


def get_max_chunk_chars(language):
    """Max chars per chunk per la lingua data. CJK/Hindi/Arabic: 1500. Altri: 2000."""
    return MAX_CHUNK_CHARS_BY_LANG.get(language, MAX_CHUNK_CHARS_BY_LANG["default"])
```

- [ ] **Step 4: Run tests** → pass.

- [ ] **Step 5: Commit**

```
git add gemini_tts.py test/test_gemini_tts.py
git commit -m "feat(gemini-tts): byte-size safety check and per-language chunk sizing"
```

---

### Task 9: Usage tracking (JSON persistence)

**Files:**
- Modify: `gemini_tts.py`
- Modify: `test/test_gemini_tts.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_init_creates_data_dir_state(temp_data_dir):
    gemini_tts.init(temp_data_dir)
    usage = gemini_tts.get_usage()
    assert usage["chars_total"] == 0
    assert usage["google_cost_eur"] == 0.0
    assert "by_model" in usage
    assert "flash25" in usage["by_model"]
    assert "flash31" in usage["by_model"]


def test_record_usage_accumulates(temp_data_dir):
    gemini_tts.init(temp_data_dir)
    gemini_tts.record_usage(
        model_key="flash25",
        chars=10_000,
        input_tokens=2500,
        output_tokens=16_666,
        google_cost_eur=0.15,
        revenue_eur=0.25,
    )
    gemini_tts.record_usage(
        model_key="flash25",
        chars=5_000,
        input_tokens=1250,
        output_tokens=8333,
        google_cost_eur=0.08,
        revenue_eur=0.12,
    )
    usage = gemini_tts.get_usage()
    assert usage["chars_total"] == 15_000
    assert usage["google_cost_eur"] == pytest.approx(0.23, abs=0.001)
    assert usage["user_revenue_eur_net"] == pytest.approx(0.37, abs=0.001)
    assert usage["margin_eur"] == pytest.approx(0.14, abs=0.001)
    assert usage["by_model"]["flash25"]["chars"] == 15_000
    assert usage["by_model"]["flash25"]["jobs_count"] == 2


def test_record_usage_persists_across_reload(temp_data_dir):
    gemini_tts.init(temp_data_dir)
    gemini_tts.record_usage("flash31", 1000, 250, 1666, 0.03, 0.05)
    # Simulate fresh module load: reset internal cache and reload from disk
    gemini_tts._usage_cache = None
    usage = gemini_tts.get_usage()
    assert usage["by_model"]["flash31"]["chars"] == 1000


def test_record_usage_rejects_unknown_model(temp_data_dir):
    gemini_tts.init(temp_data_dir)
    with pytest.raises(ValueError):
        gemini_tts.record_usage("flashXX", 100, 25, 200, 0.01, 0.02)
```

Note: `temp_data_dir` fixture is already defined in `test/conftest.py`.

- [ ] **Step 2: Run tests** → fail.

- [ ] **Step 3: Implement**

Append to `gemini_tts.py`:
```python
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_data_dir = None
_usage_file_path = None
_usage_lock = threading.Lock()
_usage_cache = None


def init(data_dir):
    """Inizializza il modulo con la directory dati persistente."""
    global _data_dir, _usage_file_path, _usage_cache
    _data_dir = Path(data_dir)
    _data_dir.mkdir(parents=True, exist_ok=True)
    _usage_file_path = _data_dir / "gemini_tts_usage.json"
    _usage_cache = None  # forza ricarica


def _current_month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _empty_usage():
    return {
        "month": _current_month(),
        "chars_total": 0,
        "input_tokens_total": 0,
        "output_tokens_total": 0,
        "google_cost_eur": 0.0,
        "user_revenue_eur_net": 0.0,
        "margin_eur": 0.0,
        "previews_count": 0,
        "previews_cost_eur": 0.0,
        "by_model": {
            "flash25": {"chars": 0, "input_tok": 0, "output_tok": 0,
                        "google_cost": 0.0, "revenue_net": 0.0, "jobs_count": 0},
            "flash31": {"chars": 0, "input_tok": 0, "output_tok": 0,
                        "google_cost": 0.0, "revenue_net": 0.0, "jobs_count": 0},
        },
    }


def _load_usage():
    global _usage_cache
    if _usage_cache is not None:
        return _usage_cache
    if _usage_file_path is None:
        return _empty_usage()
    if _usage_file_path.exists():
        try:
            data = json.loads(_usage_file_path.read_text(encoding="utf-8"))
            if data.get("month") == _current_month():
                _usage_cache = data
                return data
        except Exception as e:
            print(f"[gemini-tts] Warning: could not read usage file: {e}")
    data = _empty_usage()
    _usage_cache = data
    return data


def _save_usage(data):
    global _usage_cache
    _usage_cache = data
    if _usage_file_path is None:
        return
    try:
        _usage_file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = _usage_file_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_usage_file_path)
    except Exception as e:
        print(f"[gemini-tts] Warning: could not save usage file: {e}")


def record_usage(model_key, chars, input_tokens, output_tokens, google_cost_eur, revenue_eur):
    """Registra l'utilizzo di un job completato. Aggiorna anche aggregati globali."""
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown model_key: {model_key}")
    with _usage_lock:
        data = _load_usage()
        data["chars_total"] += chars
        data["input_tokens_total"] += input_tokens
        data["output_tokens_total"] += output_tokens
        data["google_cost_eur"] += google_cost_eur
        data["user_revenue_eur_net"] += revenue_eur
        data["margin_eur"] = data["user_revenue_eur_net"] - data["google_cost_eur"]
        m = data["by_model"][model_key]
        m["chars"] += chars
        m["input_tok"] += input_tokens
        m["output_tok"] += output_tokens
        m["google_cost"] += google_cost_eur
        m["revenue_net"] += revenue_eur
        m["jobs_count"] += 1
        _save_usage(data)


def get_usage():
    """Restituisce lo snapshot di utilizzo del mese corrente."""
    with _usage_lock:
        return dict(_load_usage())  # shallow copy
```

- [ ] **Step 4: Run tests** → pass.

- [ ] **Step 5: Commit**

```
git add gemini_tts.py test/test_gemini_tts.py
git commit -m "feat(gemini-tts): monthly usage tracking with atomic JSON persistence"
```

---

### Task 10: Preview cap (rolling 24h per cookie)

**Files:**
- Modify: `gemini_tts.py`
- Modify: `test/test_gemini_tts.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_preview_cap_initial_state(temp_data_dir):
    gemini_tts.init(temp_data_dir)
    count, remaining, reset_ts = gemini_tts.check_preview_cap("cookie123")
    assert count == 0
    assert remaining == 5  # default cap


def test_preview_cap_allows_under_limit(temp_data_dir):
    gemini_tts.init(temp_data_dir)
    for i in range(5):
        assert gemini_tts.increment_preview("cookieA") is True
    count, remaining, _ = gemini_tts.check_preview_cap("cookieA")
    assert count == 5
    assert remaining == 0


def test_preview_cap_blocks_over_limit(temp_data_dir):
    gemini_tts.init(temp_data_dir)
    for _ in range(5):
        gemini_tts.increment_preview("cookieB")
    # 6th attempt blocked
    assert gemini_tts.increment_preview("cookieB") is False


def test_preview_cap_per_cookie_isolated(temp_data_dir):
    gemini_tts.init(temp_data_dir)
    for _ in range(5):
        gemini_tts.increment_preview("cookieX")
    # Different cookie still has full quota
    assert gemini_tts.increment_preview("cookieY") is True


def test_preview_cap_resets_after_24h(temp_data_dir, monkeypatch):
    import time
    gemini_tts.init(temp_data_dir)
    fake_now = [1_000_000.0]
    monkeypatch.setattr(gemini_tts.time, "time", lambda: fake_now[0])
    for _ in range(5):
        gemini_tts.increment_preview("cookieZ")
    assert gemini_tts.increment_preview("cookieZ") is False
    # Jump 25 hours forward
    fake_now[0] += 25 * 3600
    assert gemini_tts.increment_preview("cookieZ") is True
```

- [ ] **Step 2: Run tests** → fail.

- [ ] **Step 3: Implement**

Append to `gemini_tts.py`:
```python
import time

_preview_file_path = None
_preview_lock = threading.Lock()
_preview_cache = None


def _preview_path():
    global _preview_file_path
    if _preview_file_path is None and _data_dir is not None:
        _preview_file_path = _data_dir / "gemini_tts_previews.json"
    return _preview_file_path


def _load_previews():
    global _preview_cache
    if _preview_cache is not None:
        return _preview_cache
    p = _preview_path()
    if p and p.exists():
        try:
            _preview_cache = json.loads(p.read_text(encoding="utf-8"))
            return _preview_cache
        except Exception:
            pass
    _preview_cache = {}
    return _preview_cache


def _save_previews(data):
    global _preview_cache
    _preview_cache = data
    p = _preview_path()
    if p is None:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:
        print(f"[gemini-tts] Warning: could not save previews file: {e}")


def _maybe_reset_cookie(entry, now):
    """Resetta il counter se il primo timestamp ha superato 24h."""
    window_start = entry.get("window_start_ts", 0)
    if now - window_start >= 24 * 3600:
        entry["count"] = 0
        entry["window_start_ts"] = now
    return entry


def check_preview_cap(cookie_id):
    """Stato corrente del cap preview per il cookie. Non incrementa.

    Returns: (count_in_window, remaining, window_reset_ts)
    """
    cap = PREVIEW_CAP_PER_DAY
    now = time.time()
    with _preview_lock:
        data = _load_previews()
        entry = dict(data.get(cookie_id, {"count": 0, "window_start_ts": now}))
        entry = _maybe_reset_cookie(entry, now)
        count = entry["count"]
        remaining = max(0, cap - count)
        reset_ts = entry["window_start_ts"] + 24 * 3600
        return count, remaining, int(reset_ts)


def increment_preview(cookie_id):
    """Incrementa il counter se sotto cap. Restituisce True se incremento ok, False se cap raggiunto."""
    cap = PREVIEW_CAP_PER_DAY
    now = time.time()
    with _preview_lock:
        data = _load_previews()
        entry = data.get(cookie_id, {"count": 0, "window_start_ts": now})
        entry = _maybe_reset_cookie(entry, now)
        if entry["count"] >= cap:
            data[cookie_id] = entry
            _save_previews(data)
            return False
        entry["count"] += 1
        data[cookie_id] = entry
        _save_previews(data)
        return True
```

- [ ] **Step 4: Run tests** → pass.

- [ ] **Step 5: Commit**

```
git add gemini_tts.py test/test_gemini_tts.py
git commit -m "feat(gemini-tts): rolling 24h preview cap per cookie"
```

---

### Task 11: is_available() — env-var + SDK availability check

**Files:**
- Modify: `gemini_tts.py`
- Modify: `test/test_gemini_tts.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_is_available_false_without_api_key(monkeypatch):
    monkeypatch.delenv("ABM_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ABM_GEMINI_USE_VERTEX", raising=False)
    # Force recheck
    gemini_tts._available = None
    assert gemini_tts.is_available() is False


def test_is_available_caches_result(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "")
    gemini_tts._available = False
    # Should not re-check
    assert gemini_tts.is_available() is False
```

- [ ] **Step 2: Run tests** → fail (missing `_available` and `is_available`).

- [ ] **Step 3: Implement**

Append to `gemini_tts.py`:
```python
_available = None
_available_lock = threading.Lock()
_genai_client = None


def is_available():
    """True se ABM_GEMINI_API_KEY (o credenziali Vertex) sono configurate e google-genai è installato."""
    global _available, _genai_client
    if _available is not None:
        return _available
    with _available_lock:
        if _available is not None:
            return _available

        use_vertex = os.environ.get("ABM_GEMINI_USE_VERTEX", "false").lower() == "true"
        api_key = os.environ.get("ABM_GEMINI_API_KEY", "").strip()
        vertex_file = os.environ.get("ABM_GEMINI_VERTEX_CREDENTIALS_FILE", "").strip()

        if use_vertex:
            if not vertex_file or not os.path.exists(vertex_file):
                _available = False
                print(f"[gemini-tts] Disabled: ABM_GEMINI_USE_VERTEX=true but credentials file not found")
                return False
        else:
            if not api_key:
                _available = False
                print("[gemini-tts] Disabled: ABM_GEMINI_API_KEY not set")
                return False

        try:
            from google import genai  # noqa: F401
            _available = True
            print(f"[gemini-tts] Enabled (vertex={use_vertex})")
            return True
        except ImportError:
            _available = False
            print("[gemini-tts] Disabled: google-genai not installed. Run: pip install google-genai")
            return False


def _get_client():
    """Lazy init del client google-genai (singleton)."""
    global _genai_client
    if _genai_client is not None:
        return _genai_client
    from google import genai
    use_vertex = os.environ.get("ABM_GEMINI_USE_VERTEX", "false").lower() == "true"
    if use_vertex:
        vertex_file = os.environ["ABM_GEMINI_VERTEX_CREDENTIALS_FILE"]
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", vertex_file)
        _genai_client = genai.Client(vertexai=True)
    else:
        api_key = os.environ["ABM_GEMINI_API_KEY"].strip()
        _genai_client = genai.Client(api_key=api_key)
    return _genai_client
```

- [ ] **Step 4: Run tests** → pass.

- [ ] **Step 5: Commit**

```
git add gemini_tts.py test/test_gemini_tts.py
git commit -m "feat(gemini-tts): is_available check supporting API key and Vertex modes"
```

---

### Task 12: synthesize() — actual TTS call with retry

**Files:**
- Modify: `gemini_tts.py`
- Modify: `test/test_gemini_tts.py`

- [ ] **Step 1: Write the failing tests**

```python
class _FakeResponse:
    def __init__(self, pcm_bytes=b"\x00\x01" * 12_000, usage_input=100, usage_output=2500):
        # candidates[0].content.parts[0].inline_data.data
        class _Part:
            def __init__(self, data):
                class _InlineData:
                    def __init__(self, d):
                        self.data = d
                        self.mime_type = "audio/L16;rate=24000"
                self.inline_data = _InlineData(data)
        class _Content:
            def __init__(self, parts):
                self.parts = parts
        class _Candidate:
            def __init__(self, content):
                self.content = content
        self.candidates = [_Candidate(_Content([_Part(pcm_bytes)]))]
        class _Usage:
            def __init__(self, i, o):
                self.prompt_token_count = i
                self.candidates_token_count = o
                self.total_token_count = i + o
        self.usage_metadata = _Usage(usage_input, usage_output)


def test_synthesize_writes_pcm_file(temp_data_dir, monkeypatch):
    gemini_tts.init(temp_data_dir)
    fake_client = type("C", (), {})()
    fake_client.models = type("M", (), {"generate_content": lambda self, **kw: _FakeResponse()})()
    monkeypatch.setattr(gemini_tts, "_get_client", lambda: fake_client)
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)

    out = Path(temp_data_dir) / "out.pcm"
    result = gemini_tts.synthesize(
        text="Ciao mondo",
        voice_id="gemini:flash25:Zephyr",
        output_path=str(out),
    )
    assert result["success"] is True
    assert out.exists()
    assert out.stat().st_size > 0
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 2500
    assert result["bytes_written"] == 24_000


def test_synthesize_rejects_oversized_text(temp_data_dir, monkeypatch):
    gemini_tts.init(temp_data_dir)
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    with pytest.raises(ValueError, match="exceeds MAX_BYTES_PER_CALL"):
        gemini_tts.synthesize(
            text="a" * 5000,
            voice_id="gemini:flash25:Zephyr",
            output_path="/tmp/x.pcm",
        )


def test_synthesize_retries_on_transient_error(temp_data_dir, monkeypatch):
    from pathlib import Path as _P
    gemini_tts.init(temp_data_dir)
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    calls = {"n": 0}

    def flaky_generate(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient 503")
        return _FakeResponse()

    fake_client = type("C", (), {})()
    fake_client.models = type("M", (), {"generate_content": lambda self, **kw: flaky_generate(**kw)})()
    monkeypatch.setattr(gemini_tts, "_get_client", lambda: fake_client)
    monkeypatch.setattr(gemini_tts.time, "sleep", lambda s: None)

    out = _P(temp_data_dir) / "retry.pcm"
    result = gemini_tts.synthesize(
        text="ciao",
        voice_id="gemini:flash25:Zephyr",
        output_path=str(out),
    )
    assert result["success"] is True
    assert calls["n"] == 3
```

- [ ] **Step 2: Run tests** → fail.

- [ ] **Step 3: Implement**

Append to `gemini_tts.py`:
```python
SYNTH_MAX_ATTEMPTS = 3


def synthesize(text, voice_id, rate="+0%", output_path="output.pcm"):
    """Sintetizza testo in PCM raw 24kHz mono 16-bit usando Gemini TTS.

    Args:
        text: testo da sintetizzare (≤ MAX_BYTES_PER_CALL UTF-8 bytes).
        voice_id: 'gemini:<model_key>:<voice_name>'.
        rate: parametro di compatibilità — Gemini TTS non ha speaking_rate API,
              quando rate != '+0%' viene aggiunto un prompt instruction.
        output_path: percorso file PCM in output.

    Returns:
        dict con success, bytes_written, input_tokens, output_tokens, model_key,
        voice_name, attempts_used.

    Raises:
        ValueError se text supera il cap byte o voice_id è invalido.
        RuntimeError se tutti i retry falliscono.
    """
    if not is_available():
        raise RuntimeError("Gemini TTS not available (check ABM_GEMINI_API_KEY)")

    model_key, model_id, voice_name = parse_voice_id(voice_id)
    ok, size = check_text_byte_size(text)
    if not ok:
        raise ValueError(f"Text exceeds MAX_BYTES_PER_CALL ({size} > {MAX_BYTES_PER_CALL} bytes)")

    # Speaking rate via prompt instruction (Gemini TTS has no native rate param)
    rate_mode = os.environ.get("ABM_GEMINI_RATE_MODE", "prompt")
    final_text = text
    if rate_mode == "prompt" and rate and rate != "+0%":
        pct = rate.replace("%", "").replace("+", "")
        try:
            n = int(pct)
            if n < -5:
                final_text = f"[slow] {text}"
            elif n > 5:
                final_text = f"[fast] {text}"
        except ValueError:
            pass

    from google.genai import types as genai_types

    client = _get_client()
    last_err = None
    pcm_data = None
    usage_input = 0
    usage_output = 0
    attempt = 0

    while attempt < SYNTH_MAX_ATTEMPTS:
        attempt += 1
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=final_text,
                config=genai_types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=genai_types.SpeechConfig(
                        voice_config=genai_types.VoiceConfig(
                            prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                                voice_name=voice_name,
                            )
                        )
                    ),
                ),
            )
            pcm_data = response.candidates[0].content.parts[0].inline_data.data
            um = getattr(response, "usage_metadata", None)
            if um:
                usage_input = getattr(um, "prompt_token_count", 0) or 0
                usage_output = getattr(um, "candidates_token_count", 0) or 0
            break
        except Exception as e:
            last_err = e
            if attempt < SYNTH_MAX_ATTEMPTS:
                time.sleep(2 ** attempt)
            else:
                raise RuntimeError(f"Gemini TTS failed after {SYNTH_MAX_ATTEMPTS} attempts: {last_err}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(pcm_data)

    return {
        "success": True,
        "bytes_written": len(pcm_data),
        "input_tokens": usage_input,
        "output_tokens": usage_output,
        "model_key": model_key,
        "voice_name": voice_name,
        "attempts_used": attempt,
    }
```

- [ ] **Step 4: Run tests** → pass.

- [ ] **Step 5: Commit**

```
git add gemini_tts.py test/test_gemini_tts.py
git commit -m "feat(gemini-tts): synthesize() with retry/backoff and PCM file output"
```

---

### Task 13: pcm_size_to_seconds helper in audio_utils

**Files:**
- Modify: `audio_utils.py`
- Create: `test/test_audio_utils_pcm.py`

- [ ] **Step 1: Write the failing tests**

`test/test_audio_utils_pcm.py`:
```python
"""Tests for PCM helpers in audio_utils.py."""
import pytest
import audio_utils


def test_pcm_size_to_seconds_one_second_24k_mono_16bit():
    # 1 second of 24kHz mono 16-bit = 48000 bytes
    assert audio_utils.pcm_size_to_seconds(48_000) == pytest.approx(1.0, abs=0.001)


def test_pcm_size_to_seconds_zero():
    assert audio_utils.pcm_size_to_seconds(0) == 0.0


def test_pcm_size_to_seconds_custom_format():
    # 44.1kHz stereo 16-bit, 1 second = 44100 × 2 × 2 = 176400 bytes
    result = audio_utils.pcm_size_to_seconds(176_400, sample_rate=44100, channels=2, sample_width=2)
    assert result == pytest.approx(1.0, abs=0.001)
```

- [ ] **Step 2: Run tests** → fail.

- [ ] **Step 3: Implement**

Append to `audio_utils.py`:
```python
# ---------------------------------------------------------------------------
# PCM helpers (Gemini TTS native output: 24kHz mono 16-bit)
# ---------------------------------------------------------------------------

def pcm_size_to_seconds(byte_size, sample_rate=24000, channels=1, sample_width=2):
    """Converte byte di PCM raw in secondi di durata.

    sample_width: byte per sample (16-bit = 2).
    """
    if byte_size <= 0:
        return 0.0
    bytes_per_second = sample_rate * channels * sample_width
    return byte_size / bytes_per_second
```

- [ ] **Step 4: Run tests** → pass.

- [ ] **Step 5: Commit**

```
git add audio_utils.py test/test_audio_utils_pcm.py
git commit -m "feat(audio): pcm_size_to_seconds helper"
```

---

### Task 14: pcm_concat helper

**Files:**
- Modify: `audio_utils.py`
- Modify: `test/test_audio_utils_pcm.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_pcm_concat_simple(tmp_path):
    p1 = tmp_path / "a.pcm"
    p2 = tmp_path / "b.pcm"
    p1.write_bytes(b"\x01\x02\x03\x04")
    p2.write_bytes(b"\x05\x06\x07\x08")
    out = tmp_path / "combined.pcm"
    audio_utils.pcm_concat([str(p1), str(p2)], str(out))
    assert out.read_bytes() == b"\x01\x02\x03\x04\x05\x06\x07\x08"


def test_pcm_concat_empty_list(tmp_path):
    out = tmp_path / "empty.pcm"
    audio_utils.pcm_concat([], str(out))
    assert out.exists()
    assert out.read_bytes() == b""


def test_pcm_concat_skips_missing(tmp_path):
    p1 = tmp_path / "a.pcm"
    p1.write_bytes(b"data1")
    missing = tmp_path / "missing.pcm"
    out = tmp_path / "out.pcm"
    audio_utils.pcm_concat([str(p1), str(missing)], str(out), skip_missing=True)
    assert out.read_bytes() == b"data1"
```

- [ ] **Step 2: Run tests** → fail.

- [ ] **Step 3: Implement**

Append to `audio_utils.py`:
```python
def pcm_concat(pcm_paths, output_path, skip_missing=False):
    """Concatena raw PCM byte-wise (tutti i file devono avere stesso formato).

    Non c'è header da gestire: PCM raw è solo sequenza di campioni.
    Crea il file di output anche se la lista è vuota.

    Args:
        pcm_paths: lista path PCM in ordine.
        output_path: file di destinazione.
        skip_missing: se True, file non esistenti vengono saltati con log; altrimenti raise FileNotFoundError.
    """
    out = open(output_path, "wb")
    try:
        for p in pcm_paths:
            if not os.path.exists(p):
                if skip_missing:
                    print(f"[pcm_concat] skip missing: {p}")
                    continue
                raise FileNotFoundError(p)
            with open(p, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)  # 1 MB
                    if not chunk:
                        break
                    out.write(chunk)
    finally:
        out.close()
```

- [ ] **Step 4: Run tests** → pass.

- [ ] **Step 5: Commit**

```
git add audio_utils.py test/test_audio_utils_pcm.py
git commit -m "feat(audio): pcm_concat byte-wise helper"
```

---

### Task 15: pcm_to_mp3 (single FFmpeg encode)

**Files:**
- Modify: `audio_utils.py`
- Modify: `test/test_audio_utils_pcm.py`

- [ ] **Step 1: Write the failing tests**

```python
import subprocess as _sp
import shutil as _sh

ffmpeg_missing = _sh.which("ffmpeg") is None


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_pcm_to_mp3_produces_valid_mp3(tmp_path):
    # Generate 0.5s of silence PCM 24kHz mono 16-bit = 24000 bytes
    pcm = tmp_path / "silence.pcm"
    pcm.write_bytes(b"\x00\x00" * 12_000)
    out = tmp_path / "out.mp3"
    ok = audio_utils.pcm_to_mp3([str(pcm)], str(out))
    assert ok is True
    assert out.exists()
    # First bytes of MP3 frame header start with 0xFF
    assert out.read_bytes()[:2] in (b"\xff\xfb", b"\xff\xfa", b"\xff\xf3", b"ID3")


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_pcm_to_mp3_concatenates_multiple(tmp_path):
    pcm1 = tmp_path / "a.pcm"
    pcm2 = tmp_path / "b.pcm"
    pcm1.write_bytes(b"\x00\x00" * 6_000)  # 0.25s
    pcm2.write_bytes(b"\x00\x00" * 6_000)  # 0.25s
    out = tmp_path / "concat.mp3"
    ok = audio_utils.pcm_to_mp3([str(pcm1), str(pcm2)], str(out))
    assert ok is True
    assert out.stat().st_size > 0


def test_pcm_to_mp3_empty_list_returns_false(tmp_path):
    out = tmp_path / "out.mp3"
    ok = audio_utils.pcm_to_mp3([], str(out))
    assert ok is False
```

- [ ] **Step 2: Run tests** → fail.

- [ ] **Step 3: Implement**

Append to `audio_utils.py`:
```python
def pcm_to_mp3(pcm_paths, output_path, sample_rate=24000, channels=1,
               sample_width=2, bitrate="64k"):
    """Concatena raw PCM e codifica in MP3 con singola passata ffmpeg.

    Args:
        pcm_paths: lista path PCM (24kHz mono 16-bit by default).
        output_path: file MP3 risultante.
        sample_rate, channels, sample_width: formato sorgente.
        bitrate: bitrate MP3 (es. '64k').

    Returns:
        True se ok, False se nessun input o ffmpeg fallisce.
    """
    if not pcm_paths:
        return False
    ffmpeg_ok, _ = _check_audio_dependencies()
    if not ffmpeg_ok:
        print("[pcm_to_mp3] ffmpeg not available")
        return False

    import subprocess
    # Concatena in un PCM temp unico
    tmp_pcm = output_path + ".tmp.pcm"
    try:
        pcm_concat(pcm_paths, tmp_pcm)
        fmt = {1: "s16le", 2: "s16le"}.get(sample_width, "s16le")  # we only support 16-bit
        cmd = [
            "ffmpeg", "-y",
            "-f", fmt,
            "-ar", str(sample_rate),
            "-ac", str(channels),
            "-i", tmp_pcm,
            "-c:a", "libmp3lame",
            "-b:a", bitrate,
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=600, **_SUBPROCESS_FLAGS)
        if result.returncode != 0:
            print(f"[pcm_to_mp3] ffmpeg failed: {result.stderr.decode('utf-8', errors='ignore')[:500]}")
            return False
        return True
    except Exception as e:
        print(f"[pcm_to_mp3] error: {e}")
        return False
    finally:
        try:
            os.remove(tmp_pcm)
        except OSError:
            pass
```

- [ ] **Step 4: Run tests** → pass (skip on systems without ffmpeg).

- [ ] **Step 5: Commit**

```
git add audio_utils.py test/test_audio_utils_pcm.py
git commit -m "feat(audio): pcm_to_mp3 single-pass encoder"
```

---

### Task 16: pcm_to_aac_m4b (PCM → AAC → M4B direct)

**Files:**
- Modify: `audio_utils.py`
- Modify: `test/test_audio_utils_pcm.py`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_pcm_to_aac_m4b_basic(tmp_path):
    pcm = tmp_path / "sample.pcm"
    pcm.write_bytes(b"\x00\x00" * 24_000)  # 1s of silence at 24kHz mono 16-bit
    out = tmp_path / "out.m4b"
    ok = audio_utils.pcm_to_aac_m4b([str(pcm)], str(out))
    assert ok is True
    assert out.exists()
    assert out.stat().st_size > 0
    # M4B = MP4 container: starts with 'ftyp' atom at offset 4
    header = out.read_bytes()[:12]
    assert b"ftyp" in header


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_pcm_to_aac_m4b_with_chapters(tmp_path):
    pcm1 = tmp_path / "ch1.pcm"
    pcm2 = tmp_path / "ch2.pcm"
    pcm1.write_bytes(b"\x00\x00" * 24_000)  # 1s
    pcm2.write_bytes(b"\x00\x00" * 48_000)  # 2s
    out = tmp_path / "book.m4b"
    chapters = [
        {"title": "Capitolo 1", "start": 0, "end": 1000},
        {"title": "Capitolo 2", "start": 1000, "end": 3000},
    ]
    ok = audio_utils.pcm_to_aac_m4b(
        [str(pcm1), str(pcm2)],
        str(out),
        chapters=chapters,
        title="Libro Test",
        author="Autore Test",
    )
    assert ok is True
    assert out.stat().st_size > 0


def test_pcm_to_aac_m4b_empty_returns_false(tmp_path):
    out = tmp_path / "empty.m4b"
    assert audio_utils.pcm_to_aac_m4b([], str(out)) is False
```

- [ ] **Step 2: Run tests** → fail.

- [ ] **Step 3: Implement**

Append to `audio_utils.py`:
```python
def pcm_to_aac_m4b(pcm_paths, output_path, sample_rate=24000, channels=1,
                   sample_width=2, bitrate="96k", chapters=None, title=None,
                   author=None, cover_path=None, date=None, language=None,
                   description=None, genre="Audiobook"):
    """Codifica PCM concatenato direttamente in M4B (AAC) con capitoli/cover/metadati.

    Vantaggio vs pcm_to_mp3 + mp3_to_m4b: una sola encode AAC (no doppia lossy).

    Args:
        pcm_paths: lista PCM in ordine.
        output_path: file .m4b destinazione.
        bitrate: AAC bitrate (default '96k' mono).
        chapters: [{'title', 'start' ms, 'end' ms}, ...] opzionale.
        title/author/cover_path/date/language/description/genre: metadati M4B.

    Returns:
        True se ok, False altrimenti.
    """
    if not pcm_paths:
        return False
    ffmpeg_ok, _ = _check_audio_dependencies()
    if not ffmpeg_ok:
        print("[pcm_to_aac_m4b] ffmpeg not available")
        return False

    import subprocess

    tmp_pcm = output_path + ".tmp.pcm"
    metadata_file = None
    try:
        pcm_concat(pcm_paths, tmp_pcm)

        # Build metadata file (FFMETADATA1 + chapters) reusing the same convention as _convert_mp3_to_m4b
        def escape_meta(s):
            return str(s).replace('\\', '\\\\').replace('=', '\\=').replace(';', '\\;').replace('#', '\\#').replace('\n', ' ')

        year = _extract_year_from_date(date) if date else ""
        lang_iso = _normalize_language_iso(language) if language else ""
        desc_trunc = (description or "").strip()[:1000] if description else ""

        valid_chapters = None
        if chapters:
            valid_chapters = [ch for ch in chapters if ch.get("end", 0) > ch.get("start", 0)]
            if not valid_chapters:
                valid_chapters = None

        has_global_meta = bool(title or author or year or lang_iso or desc_trunc or genre)
        if has_global_meta or valid_chapters:
            metadata_file = output_path + ".metadata.txt"
            with open(metadata_file, "w", encoding="utf-8") as f:
                f.write(";FFMETADATA1\n")
                if title:
                    f.write(f"title={escape_meta(title)}\n")
                    f.write(f"album={escape_meta(title)}\n")
                if author:
                    f.write(f"artist={escape_meta(author)}\n")
                    f.write(f"album_artist={escape_meta(author)}\n")
                if year:
                    f.write(f"date={escape_meta(year)}\n")
                if genre:
                    f.write(f"genre={escape_meta(genre)}\n")
                if desc_trunc:
                    f.write(f"comment={escape_meta(desc_trunc)}\n")
                    f.write(f"description={escape_meta(desc_trunc)}\n")
                if valid_chapters:
                    for ch in valid_chapters:
                        f.write("\n[CHAPTER]\n")
                        f.write("TIMEBASE=1/1000\n")
                        f.write(f"START={int(round(ch['start']))}\n")
                        f.write(f"END={int(round(ch['end']))}\n")
                        f.write(f"title={escape_meta(ch['title'])}\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "s16le",
            "-ar", str(sample_rate),
            "-ac", str(channels),
            "-i", tmp_pcm,
        ]
        if metadata_file:
            cmd.extend(["-i", metadata_file, "-map_metadata", "1", "-map_chapters", "1"])
        if cover_path and os.path.exists(cover_path):
            cmd.extend(["-i", cover_path, "-map", "0:a", "-map", f"{2 if metadata_file else 1}:v",
                        "-disposition:v", "attached_pic", "-c:v", "copy"])
        else:
            cmd.extend(["-map", "0:a"])

        cmd.extend(["-c:a", "aac", "-b:a", bitrate])
        if lang_iso:
            cmd.extend(["-metadata:s:a:0", f"language={lang_iso}"])
        cmd.extend(["-metadata", "media_type=2", "-f", "ipod", output_path])

        result = subprocess.run(cmd, capture_output=True, timeout=3600, **_SUBPROCESS_FLAGS)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="ignore")[:800]
            print(f"[pcm_to_aac_m4b] ffmpeg failed: {stderr}")
            return False
        return True
    except Exception as e:
        print(f"[pcm_to_aac_m4b] error: {e}")
        return False
    finally:
        for f in (tmp_pcm, metadata_file):
            if f:
                try:
                    os.remove(f)
                except OSError:
                    pass
```

- [ ] **Step 4: Run tests** → pass.

- [ ] **Step 5: Commit**

```
git add audio_utils.py test/test_audio_utils_pcm.py
git commit -m "feat(audio): pcm_to_aac_m4b direct PCM→AAC→M4B with chapters and metadata"
```

---

### Task 17: CLI smoke test script

**Files:**
- Create: `scripts/gemini_tts_cli.py`

- [ ] **Step 1: Write the script**

`scripts/gemini_tts_cli.py`:
```python
#!/usr/bin/env python3
"""
gemini_tts_cli.py — Smoke test manuale per gemini_tts module.

Usage:
    export ABM_GEMINI_API_KEY=...
    python scripts/gemini_tts_cli.py synthesize "Ciao mondo" gemini:flash25:Zephyr out.pcm
    python scripts/gemini_tts_cli.py estimate "testo molto lungo..." flash25 it
    python scripts/gemini_tts_cli.py list-voices
    python scripts/gemini_tts_cli.py m4b out1.pcm out2.pcm output.m4b
"""

import sys
import os
import json
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import gemini_tts
import audio_utils


def cmd_synthesize(text, voice_id, output_path):
    data_dir = os.environ.get("ABM_DATA_DIR", "./.gemini_cli_data")
    gemini_tts.init(data_dir)
    if not gemini_tts.is_available():
        print("ERROR: Gemini TTS not available. Set ABM_GEMINI_API_KEY.")
        sys.exit(1)
    result = gemini_tts.synthesize(text, voice_id, output_path=output_path)
    print(json.dumps(result, indent=2))


def cmd_estimate(text, model_key, language):
    class _Ch:
        def __init__(self, t):
            self.text = t
    result = gemini_tts.estimate_book_cost(
        [_Ch(text)], voice_id=f"gemini:{model_key}:Zephyr", language=language
    )
    print(json.dumps(result, indent=2, default=str))


def cmd_list_voices():
    voices = gemini_tts.get_voices()
    for lang, vs in voices.items():
        print(f"\n--- {lang} ({len(vs)} voices) ---")
        for v in vs[:5]:
            print(f"  {v['id']}  ({v['name']})")
        if len(vs) > 5:
            print(f"  ... and {len(vs) - 5} more")


def cmd_m4b(pcm_paths_and_output):
    *pcm_paths, output_path = pcm_paths_and_output
    ok = audio_utils.pcm_to_aac_m4b(
        pcm_paths, output_path,
        title="Gemini TTS Smoke Test",
        author="Audiobook Maker",
        genre="Audiobook",
    )
    print(f"M4B created: {ok} → {output_path}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "synthesize":
        cmd_synthesize(*args)
    elif cmd == "estimate":
        cmd_estimate(*args)
    elif cmd == "list-voices":
        cmd_list_voices()
    elif cmd == "m4b":
        cmd_m4b(args)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify by running list-voices (no API key needed)**

```
python scripts/gemini_tts_cli.py list-voices
```
Expected output: 7 language sections, ~5 voices each shown, "and 55 more" message.

- [ ] **Step 3: Verify estimation (no API key needed)**

```
python scripts/gemini_tts_cli.py estimate "Ciao mondo, questo è un test di stima del costo." flash25 it
```
Expected: JSON with `chars_total`, `user_price_eur: 0.0` (sotto soglia), `is_free: true`.

- [ ] **Step 4: Commit**

```
git add scripts/gemini_tts_cli.py
git commit -m "feat(gemini-tts): CLI smoke test script for manual integration test"
```

---

### Task 18: Add google-genai to requirements

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Read current requirements**

```
type requirements.txt
```

- [ ] **Step 2: Append google-genai**

Add this line to `requirements.txt`:
```
google-genai>=0.3.0
```

- [ ] **Step 3: Install in dev environment**

```
pip install google-genai
```
Expected: package and dependencies installed without conflicts.

- [ ] **Step 4: Re-run all gemini tests** (verify SDK import path works)

```
pytest test/test_gemini_tts.py test/test_audio_utils_pcm.py -v
```
Expected: all tests still pass.

- [ ] **Step 5: Commit**

```
git add requirements.txt
git commit -m "chore(deps): add google-genai for Gemini TTS"
```

---

### Task 19: Update PARAMETRI_CONFIGURAZIONE.md

**Files:**
- Modify: `PARAMETRI_CONFIGURAZIONE.md`

- [ ] **Step 1: Locate the right section**

Find the "Google Cloud TTS" section (Chirp3-HD config) and add a new "Gemini TTS" subsection immediately after.

- [ ] **Step 2: Append documentation**

```markdown
### Gemini TTS (2.5 / 3.1 Flash)

Modulo `gemini_tts.py` indipendente da Chirp3-HD. Usa SDK `google-genai`,
account separato. Native output PCM 24kHz mono 16-bit → AAC per M4B diretto.

**Autenticazione**

| Variabile | Default | Note |
|---|---|---|
| `ABM_GEMINI_API_KEY` | *(vuoto)* | Disabilita Gemini TTS se vuoto |
| `ABM_GEMINI_USE_VERTEX` | `false` | Se `true` usa Vertex AI (service account) |
| `ABM_GEMINI_VERTEX_CREDENTIALS_FILE` | *(vuoto)* | Path JSON service account (se Vertex) |

**Costi Google (USD per 1M token, sovrascrivibili per pricing changes)**

| Variabile | Default |
|---|---|
| `ABM_GEMINI_25FLASH_INPUT_USD_PER_MTOK` | `0.50` |
| `ABM_GEMINI_25FLASH_OUTPUT_USD_PER_MTOK` | `10.00` |
| `ABM_GEMINI_31FLASH_INPUT_USD_PER_MTOK` | `1.00` |
| `ABM_GEMINI_31FLASH_OUTPUT_USD_PER_MTOK` | `20.00` |
| `ABM_GEMINI_USD_EUR_RATE` | `0.86` |

**Margini di vendita (% sul costo Google)**

| Variabile | Default |
|---|---|
| `ABM_GEMINI_25FLASH_MARGIN_PERCENT` | `35` |
| `ABM_GEMINI_31FLASH_MARGIN_PERCENT` | `25` |

**PayPal fee compensation e soglia gratuità**

| Variabile | Default |
|---|---|
| `ABM_GEMINI_PAYPAL_FIXED_FEE_EUR` | `0.34` |
| `ABM_GEMINI_PAYPAL_PERCENT_FEE` | `3.4` |
| `ABM_GEMINI_FREE_THRESHOLD_EUR` | `0.50` |

**Limiti e anti-abuso**

| Variabile | Default |
|---|---|
| `ABM_GEMINI_PREVIEW_CAP_PER_DAY` | `5` |
| `ABM_GEMINI_MAX_BYTES_PER_CALL` | `4000` |
| `ABM_GEMINI_RATE_MODE` | `prompt` |

**Note:**
- Voce ID formato: `gemini:<model_key>:<voice_name>` (es. `gemini:flash25:Zephyr`).
- Modelli supportati: `flash25` (Gemini 2.5 Flash TTS), `flash31` (Gemini 3.1 Flash TTS).
- 30 voci prebuilt × 2 modelli = 60 entry per lingua UI.
- Chunk max chars per lingua: 1500 per zh/ja/hi/ar, 2000 per altre.
- Stato utilizzo in `<DATA_DIR>/gemini_tts_usage.json`, preview cap in `gemini_tts_previews.json`.
```

- [ ] **Step 3: Commit**

```
git add PARAMETRI_CONFIGURAZIONE.md
git commit -m "docs: document ABM_GEMINI_* environment variables"
```

---

### Task 20: Final integration check — full test suite + import smoke test

**Files:** None modified.

- [ ] **Step 1: Run all tests in repo**

```
pytest test/ -v
```
Expected: all existing tests still pass + new Gemini TTS tests pass.

- [ ] **Step 2: Verify gemini_tts module imports cleanly with no env vars set**

```
python -c "import gemini_tts; print('ok:', len(gemini_tts.GEMINI_VOICE_NAMES), 'voices')"
```
Expected: `ok: 30 voices` printed; no errors.

- [ ] **Step 3: Verify is_available returns False with no API key**

```
python -c "import gemini_tts; print('available:', gemini_tts.is_available())"
```
Expected: `available: False` and a log line "Disabled: ABM_GEMINI_API_KEY not set".

- [ ] **Step 4: (Optional, real API) Run synthesize smoke test**

```
$env:ABM_GEMINI_API_KEY="<your-key>"
python scripts/gemini_tts_cli.py synthesize "Ciao mondo." gemini:flash25:Zephyr ./smoke.pcm
python scripts/gemini_tts_cli.py m4b ./smoke.pcm ./smoke.m4b
```
Expected: `smoke.pcm` exists (~30-50 KB), `smoke.m4b` exists and plays in VLC/iTunes with 1-2s of audio.

Clean up:
```
del smoke.pcm
del smoke.m4b
```

- [ ] **Step 5: Verify no temp files left in repo**

```
git status
```
Expected: only intended changes (or fully clean if all committed). No `.pcm`/`.m4b`/`.tmp` artifacts.

- [ ] **Step 6: Commit nothing (verification only)** — Plan A complete.

---

## Definition of Done (Plan A)

✅ `gemini_tts.py` module loaded, all 30 voices × 2 models exposed.
✅ Token estimation accurate within documented ratios.
✅ User price computed correctly with margin + PayPal fee compensation.
✅ Usage tracking persists across sessions.
✅ Preview cap enforces 5/24h per cookie with rolling reset.
✅ `synthesize()` produces PCM file from real API call (manual CLI test).
✅ `pcm_to_aac_m4b()` produces valid M4B with chapters from PCM input.
✅ `pcm_to_mp3()` produces valid MP3 from PCM input.
✅ All env vars documented in `PARAMETRI_CONFIGURAZIONE.md`.
✅ All tests pass.
✅ Zero impact on existing TTS paths (no imports added to `tts_split.py` / `generation_engine.py` / `audiobook_app.py`).

**Plan B prerequisites:** This plan must be complete before Plan B starts (Plan B integrates this module into the generation pipeline).

---

## Open Decisions Documented Here (For Plan B/C)

These are not implemented in Plan A but recorded for continuity:

1. **Voice ID prefix is `gemini:<model_key>:<voice_name>`** — Plan B's dispatch in `tts_split.py` will rely on this.
2. **Native format is PCM 24kHz mono 16-bit** — Plan B's chunk metadata must track engine + native format per chunk.
3. **M4B direct path** applies only when ALL chunks of the book are PCM (mixed engines fall back to MP3 path). Plan B implements this check.
4. **Usage tracking is per-month UTC**, reset on month change. No cross-month aggregation. Plan D adds admin reporting.
5. **Preview cap is per-cookie** (using existing `abm_cid` cookie infrastructure). Plan C wires it into `/api/preview_audio`.
6. **Voucher cross-purpose** (LLM ↔ Gemini TTS) is Plan C scope — `payment.py` extension with `consumption_history.purpose` field.
