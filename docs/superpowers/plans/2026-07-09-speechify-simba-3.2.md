# Speechify Simba-3.2 (voce PREMIUM inglese) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aggiungere il modello TTS Speechify Simba-3.2 come voce PREMIUM disponibile solo per lingua inglese, con concorrenza/costo/margine parametrizzati e API key da env.

**Architecture:** Nuovo modulo `speechify_tts.py` speculare a `gemini_tts.py` (4° engine TTS accanto a edge/google/gemini). Voice id `speechify:simba-3.2:<voiceId>`. Sintesi via endpoint speech (WAV→PCM), assemblaggio sul percorso PCM esistente. Concorrenza governata da un semaforo globale (limite abbonamento) attraversato da ogni chiamata API; per-job concurrency come dimensione del pool di worker del job; admission gating emergente (i worker si bloccano sul semaforo finché non si libera uno slot). Pricing riusa la pipeline premium Gemini.

**Tech Stack:** Python 3 / Flask, `requests` (già dipendenza), FFmpeg (già presente), vanilla JS frontend, pytest.

## Global Constraints

- **Solo `simba-3.2`**, **solo inglese** (locale `en-US` / `en-GB`), **solo engine speech**. Niente multilingual/simba-english, niente stream, niente denoise (YAGNI da spec §1.2).
- **API key solo da env** `ABM_SPEECHIFY_API_KEY`: mai hardcoded, mai loggata, mai committata.
- **Mai nominare il provider nella UI utente**: l'opzione modello si chiama **"Simba (English)"**, mai "Speechify".
- **8 voci Simba-3.2** (suffisso `_32`): en-US → `dominic_32`, `geffen_32`, `harper_32`, `wyatt_32`; en-GB → `beatrice_32`, `edmund_32`, `hugh_32`, `imogen_32`.
- **13 emozioni**: `angry, cheerful, sad, terrified, relaxed, fearful, surprised, calm, assertive, energetic, warm, direct, bright` + "nessuna (neutro)".
- **WAV reale**: 48000 Hz mono 16-bit; l'header va **riletto dinamicamente**, mai assunto.
- **Invariante concorrenza**: chiamate API simultanee verso Speechify ≤ `ABM_SPEECHIFY_MAX_CONCURRENCY` (default 3) in ogni istante, su tutti i job/client del processo.
- **Config env** (default): `ABM_SPEECHIFY_MAX_CONCURRENCY`=3, `ABM_SPEECHIFY_PER_JOB_CONCURRENCY`=1, `ABM_SPEECHIFY_COST_USD_PER_MCHAR`=11.18, `ABM_SPEECHIFY_MARGIN_PERCENT`=60, `ABM_SPEECHIFY_FREE_THRESHOLD_EUR`=0.50. Fee PayPal e USD→EUR riusano le env Gemini (`ABM_GEMINI_USD_EUR_RATE`=0.86, `ABM_GEMINI_PAYPAL_FIXED_FEE_EUR`=0.34, `ABM_GEMINI_PAYPAL_PERCENT_FEE`=3.4).
- **Endpoint API**: `POST https://api.speechify.ai/v1/audio/speech`, auth `Authorization: Bearer <key>`. Risposta JSON: `{"audio_data": <base64 WAV>, "billable_characters_count": <int>, ...}`. Cap ~2000 char/richiesta → chunk ≤ 1800 char.
- **Anti-import-circolare**: nessun sotto-modulo importa `audiobook_app`. `voice_utils.py` resta modulo foglia (nessun import di progetto).
- **Convenzioni progetto**: commenti/variabili miste IT/EN; validare con `python -m py_compile`; PowerShell per dev, no `&&`; test in `test/` con pytest.

---

## File Structure

**Nuovi:**
- `speechify_tts.py` — engine: config reader, catalogo voci/accenti/emozioni, `parse_voice_id`, pricing, gate concorrenza globale, `synthesize`.
- `test/test_speechify_catalog.py`, `test/test_speechify_pricing.py`, `test/test_speechify_concurrency.py`, `test/test_speechify_synthesize.py`, `test/test_speechify_engine_dispatch.py`, `test/test_speechify_endpoints.py`, `test/test_speechify_frontend_assets.py`

**Modificati:**
- `voice_utils.py` — prefisso + predicato.
- `tts_split.py` — `generate_chunk_pcm_speechify`.
- `generation_engine.py` — `_engine_for_voice`, `run_generation` (ramo speechify).
- `audiobook_app.py` — `/api/voices`, `/api/combined_estimate`, `/api/generate`, `/api/preview_audio`, create-order premium, `run_generation` wrapper.
- `templates/_fragments/html_head.html` — riordino UI premium + combo emozioni.
- `static/js/app.js` — modello Simba su EN, toggle stile↔emozioni, payload.
- `templates/_fragments/i18n_data.js`, `i18n/en.json`, `i18n/it.json` (+ fr/es/de/zh fallback en) — stringhe.
- `PARAMETRI_CONFIGURAZIONE.md` — 6 nuovi parametri.

---

## Task 1: `voice_utils` — prefisso e predicato Speechify

**Files:**
- Modify: `voice_utils.py`
- Test: `test/test_speechify_catalog.py` (creazione, prima porzione)

**Interfaces:**
- Produces: `voice_utils.SPEECHIFY_VOICE_PREFIX = "speechify:"`; `voice_utils.is_speechify_voice(voice) -> bool`.

- [ ] **Step 1: Write the failing test**

Create `test/test_speechify_catalog.py`:

```python
import voice_utils


def test_is_speechify_voice_true():
    assert voice_utils.is_speechify_voice("speechify:simba-3.2:dominic_32") is True


def test_is_speechify_voice_false_on_gemini():
    assert voice_utils.is_speechify_voice("gemini:flash25:Zephyr") is False


def test_is_speechify_voice_safe_on_none_and_empty():
    assert voice_utils.is_speechify_voice(None) is False
    assert voice_utils.is_speechify_voice("") is False
    assert voice_utils.is_speechify_voice(123) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_catalog.py -v`
Expected: FAIL con `AttributeError: module 'voice_utils' has no attribute 'is_speechify_voice'`.

- [ ] **Step 3: Add prefix + predicate**

Append to `voice_utils.py`:

```python
SPEECHIFY_VOICE_PREFIX = "speechify:"


def is_speechify_voice(voice):
    """True se la voce e' una voce PREMIUM Speechify (formato speechify:<model>:<voice>).

    Safe su input non-stringa/None/"": ritorna False senza sollevare.
    """
    return bool(voice) and isinstance(voice, str) and voice.startswith(SPEECHIFY_VOICE_PREFIX)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_catalog.py -v`
Expected: PASS (3 test).

- [ ] **Step 5: Commit**

```bash
git add voice_utils.py test/test_speechify_catalog.py
git commit -m "feat(speechify): prefisso voce e predicato is_speechify_voice"
```

---

## Task 2: `speechify_tts` — catalogo voci/accenti/emozioni + `parse_voice_id`

**Files:**
- Create: `speechify_tts.py`
- Test: `test/test_speechify_catalog.py` (estensione)

**Interfaces:**
- Produces:
  - `MODEL_ID = "simba-3.2"`, `MODEL_LABEL = "Simba (English)"`.
  - `ACCENTS = [("en-US", "American English"), ("en-GB", "British English")]`.
  - `EMOTIONS = ["angry","cheerful","sad","terrified","relaxed","fearful","surprised","calm","assertive","energetic","warm","direct","bright"]`.
  - `VOICES` — lista dict `{"id","gender","locale"}` (8 voci `_32`).
  - `voice_locale(voice_name) -> "en-US"|"en-GB"|None`.
  - `get_voices(ui_lang="en") -> {lang: [entry, ...]}` con entry `{id,name,locale,engine:"speechify",model_key:"simba-3.2",model_label,gender,gender_icon}`.
  - `parse_voice_id(voice_id) -> (model_key, voice_name, locale)`; `ValueError` se invalido.

- [ ] **Step 1: Write the failing test (append to `test/test_speechify_catalog.py`)**

```python
import pytest
import speechify_tts


def test_voices_are_eight_all_32():
    ids = [v["id"] for v in speechify_tts.VOICES]
    assert len(ids) == 8
    assert all(i.endswith("_32") for i in ids)


def test_voice_locale_mapping():
    assert speechify_tts.voice_locale("dominic_32") == "en-US"
    assert speechify_tts.voice_locale("beatrice_32") == "en-GB"
    assert speechify_tts.voice_locale("nope") is None


def test_emotions_are_thirteen():
    assert len(speechify_tts.EMOTIONS) == 13
    assert "cheerful" in speechify_tts.EMOTIONS


def test_get_voices_only_english():
    cat = speechify_tts.get_voices()
    assert set(cat.keys()) == {"en"}
    entry = cat["en"][0]
    assert entry["engine"] == "speechify"
    assert entry["model_key"] == "simba-3.2"
    assert entry["id"].startswith("speechify:simba-3.2:")


def test_parse_voice_id_ok():
    mk, vn, loc = speechify_tts.parse_voice_id("speechify:simba-3.2:harper_32")
    assert mk == "simba-3.2"
    assert vn == "harper_32"
    assert loc == "en-US"


def test_parse_voice_id_invalid():
    with pytest.raises(ValueError):
        speechify_tts.parse_voice_id("gemini:flash25:Zephyr")
    with pytest.raises(ValueError):
        speechify_tts.parse_voice_id("speechify:simba-3.2:unknown_voice")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_catalog.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'speechify_tts'`.

- [ ] **Step 3: Create `speechify_tts.py` (catalogo)**

```python
"""Speechify Simba-3.2 TTS — engine PREMIUM inglese.

Modello unico `simba-3.2` (flagship English-only). Speculare a gemini_tts.py:
config via env `ABM_SPEECHIFY_*`, catalogo voci/emozioni, pricing riusando la
pipeline premium, gate di concorrenza globale (limite abbonamento).

Anti-import-circolare: nessun import di audiobook_app. Le costanti condivise
(USD->EUR, fee PayPal) sono lette dalle STESSE env var di Gemini per coerenza.
"""

import base64
import io
import os
import threading
import wave

MODEL_ID = "simba-3.2"
MODEL_LABEL = "Simba (English)"

# (code, descrizione leggibile). Il primo e' il default.
ACCENTS = [
    ("en-US", "American English"),
    ("en-GB", "British English"),
]

# Tutte accettate (HTTP 200) da simba-3.2. Set di prodotto, non vincolo API.
EMOTIONS = [
    "angry", "cheerful", "sad", "terrified", "relaxed", "fearful",
    "surprised", "calm", "assertive", "energetic", "warm", "direct", "bright",
]

# 8 voci `_32`. gender: "Female"/"Male".
VOICES = [
    {"id": "dominic_32",  "gender": "Male",   "locale": "en-US"},
    {"id": "geffen_32",   "gender": "Male",   "locale": "en-US"},
    {"id": "harper_32",   "gender": "Female", "locale": "en-US"},
    {"id": "wyatt_32",    "gender": "Male",   "locale": "en-US"},
    {"id": "beatrice_32", "gender": "Female", "locale": "en-GB"},
    {"id": "edmund_32",   "gender": "Male",   "locale": "en-GB"},
    {"id": "hugh_32",     "gender": "Male",   "locale": "en-GB"},
    {"id": "imogen_32",   "gender": "Female", "locale": "en-GB"},
]

_VOICE_LOCALE = {v["id"]: v["locale"] for v in VOICES}
_VOICE_GENDER = {v["id"]: v["gender"] for v in VOICES}
_VALID_VOICE_NAMES = set(_VOICE_LOCALE.keys())

API_BASE = "https://api.speechify.ai"
SPEECH_ENDPOINT = "/v1/audio/speech"
CHUNK_MAX_CHARS = 1800  # cap sotto il limite ~2000 char/richiesta dell'endpoint


def voice_locale(voice_name):
    """Locale (en-US/en-GB) della voce, o None se sconosciuta."""
    return _VOICE_LOCALE.get(voice_name)


def _gender_icon(gender):
    return "♀" if gender == "Female" else "♂"  # ♀ / ♂


def get_voices(ui_lang="en"):
    """Catalogo voci per l'UI. Solo inglese (chiave 'en').

    Returns: {"en": [voice_entry, ...]} — Female prima, poi Male (coerente col
    combo Edge). Ogni entry porta id `speechify:simba-3.2:<voiceId>`.
    """
    sorted_voices = sorted(
        VOICES,
        key=lambda v: (0 if v["gender"] == "Female" else 1, v["id"]),
    )
    entries = []
    for v in sorted_voices:
        entries.append({
            "id": f"speechify:{MODEL_ID}:{v['id']}",
            "name": f"{v['id']} ({MODEL_LABEL})",
            "locale": v["locale"],
            "engine": "speechify",
            "model_key": MODEL_ID,
            "model_label": MODEL_LABEL,
            "gender": v["gender"],
            "gender_icon": _gender_icon(v["gender"]),
        })
    return {"en": entries}


def parse_voice_id(voice_id):
    """Estrae (model_key, voice_name, locale) da 'speechify:simba-3.2:harper_32'.

    Raises ValueError se formato non valido, modello != simba-3.2 o voce ignota.
    """
    if not isinstance(voice_id, str) or not voice_id.startswith("speechify:"):
        raise ValueError(f"Invalid Speechify voice ID: {voice_id!r}")
    parts = voice_id.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid Speechify voice ID: {voice_id!r} (expected 'speechify:<model>:<voice>')")
    _, model_key, voice_name = parts
    if model_key != MODEL_ID:
        raise ValueError(f"Unknown Speechify model: {model_key!r} (only {MODEL_ID!r})")
    if voice_name not in _VALID_VOICE_NAMES:
        raise ValueError(f"Unknown Speechify voice: {voice_name!r}")
    return model_key, voice_name, _VOICE_LOCALE[voice_name]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_catalog.py -v`
Expected: PASS (tutti).

- [ ] **Step 5: Commit**

```bash
git add speechify_tts.py test/test_speechify_catalog.py
git commit -m "feat(speechify): catalogo voci/accenti/emozioni + parse_voice_id"
```

---

## Task 3: `speechify_tts` — `is_available` + reader config dinamici

**Files:**
- Modify: `speechify_tts.py`
- Test: `test/test_speechify_pricing.py` (creazione, prima porzione — env gating)

**Interfaces:**
- Produces:
  - `api_key() -> str` (env `ABM_SPEECHIFY_API_KEY`, strip).
  - `is_available() -> bool` (True sse api_key valorizzata).
  - `max_concurrency() -> int` (env, default 3, min 1).
  - `per_job_concurrency() -> int` (env, default 1, min 1).
  - `cost_usd_per_mchar() -> float`, `margin_percent() -> float`, `free_threshold_eur() -> float`.
  - `usd_eur_rate() -> float`, `paypal_fixed_fee_eur() -> float`, `paypal_percent_fee() -> float` (env Gemini condivise).

- [ ] **Step 1: Write the failing test — create `test/test_speechify_pricing.py`**

```python
import importlib
import speechify_tts


def test_is_available_gated_by_key(monkeypatch):
    monkeypatch.delenv("ABM_SPEECHIFY_API_KEY", raising=False)
    assert speechify_tts.is_available() is False
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    assert speechify_tts.is_available() is True


def test_config_defaults(monkeypatch):
    for k in ("ABM_SPEECHIFY_MAX_CONCURRENCY", "ABM_SPEECHIFY_PER_JOB_CONCURRENCY",
              "ABM_SPEECHIFY_COST_USD_PER_MCHAR", "ABM_SPEECHIFY_MARGIN_PERCENT",
              "ABM_SPEECHIFY_FREE_THRESHOLD_EUR"):
        monkeypatch.delenv(k, raising=False)
    assert speechify_tts.max_concurrency() == 3
    assert speechify_tts.per_job_concurrency() == 1
    assert speechify_tts.cost_usd_per_mchar() == 11.18
    assert speechify_tts.margin_percent() == 60.0
    assert speechify_tts.free_threshold_eur() == 0.50


def test_config_overrides(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_MAX_CONCURRENCY", "5")
    monkeypatch.setenv("ABM_SPEECHIFY_PER_JOB_CONCURRENCY", "2")
    assert speechify_tts.max_concurrency() == 5
    assert speechify_tts.per_job_concurrency() == 2


def test_concurrency_floor_at_one(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_MAX_CONCURRENCY", "0")
    monkeypatch.setenv("ABM_SPEECHIFY_PER_JOB_CONCURRENCY", "-3")
    assert speechify_tts.max_concurrency() == 1
    assert speechify_tts.per_job_concurrency() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_pricing.py -v`
Expected: FAIL con `AttributeError: module 'speechify_tts' has no attribute 'is_available'`.

- [ ] **Step 3: Add config readers to `speechify_tts.py`** (dopo le costanti, prima di `voice_locale`)

```python
def _f(env, default):
    try:
        return float(str(os.environ.get(env, default)).replace(",", "."))
    except (ValueError, TypeError):
        return float(default)


def _i(env, default):
    try:
        return int(os.environ.get(env, str(default)))
    except (ValueError, TypeError):
        return int(default)


def api_key():
    return os.environ.get("ABM_SPEECHIFY_API_KEY", "").strip()


def is_available():
    """True sse la API key Speechify e' configurata."""
    return bool(api_key())


def max_concurrency():
    """Concorrenza API globale (limite abbonamento). Floor a 1."""
    return max(1, _i("ABM_SPEECHIFY_MAX_CONCURRENCY", 3))


def per_job_concurrency():
    """Chiamate API simultanee per singolo job. Floor a 1."""
    return max(1, _i("ABM_SPEECHIFY_PER_JOB_CONCURRENCY", 1))


def cost_usd_per_mchar():
    return _f("ABM_SPEECHIFY_COST_USD_PER_MCHAR", 11.18)


def margin_percent():
    return _f("ABM_SPEECHIFY_MARGIN_PERCENT", 60.0)


def free_threshold_eur():
    return _f("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", 0.50)


# Costanti condivise con Gemini (stesse env per non divergere sui prezzi).
def usd_eur_rate():
    return _f("ABM_GEMINI_USD_EUR_RATE", 0.86)


def paypal_fixed_fee_eur():
    return _f("ABM_GEMINI_PAYPAL_FIXED_FEE_EUR", 0.34)


def paypal_percent_fee():
    return _f("ABM_GEMINI_PAYPAL_PERCENT_FEE", 3.4)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_pricing.py -v`
Expected: PASS (4 test).

- [ ] **Step 5: Commit**

```bash
git add speechify_tts.py test/test_speechify_pricing.py
git commit -m "feat(speechify): is_available + reader config dinamici da env"
```

---

## Task 4: `speechify_tts` — pricing (`compute_user_price_eur`, `estimate_book_cost`)

**Files:**
- Modify: `speechify_tts.py`
- Test: `test/test_speechify_pricing.py` (estensione)

**Interfaces:**
- Consumes: `cost_usd_per_mchar`, `margin_percent`, `usd_eur_rate`, `paypal_fixed_fee_eur`, `paypal_percent_fee`, `free_threshold_eur` (Task 3).
- Produces:
  - `compute_user_price_eur(chars) -> dict` con `chars, cost_usd, base_price_eur, margin_percent, user_price_eur, is_free, free_threshold_eur`.
  - `estimate_book_cost(chapters, language="en") -> dict` con `chars_total, chars_per_chapter, cost_usd, user_price_eur, is_free, margin_percent, language, model_key, model_label`.

- [ ] **Step 1: Write the failing test (append to `test/test_speechify_pricing.py`)**

```python
def test_price_zero_chars_is_free():
    p = speechify_tts.compute_user_price_eur(0)
    assert p["user_price_eur"] == 0.0
    assert p["is_free"] is True


def test_price_matches_formula(monkeypatch):
    for k, v in {
        "ABM_SPEECHIFY_COST_USD_PER_MCHAR": "11.18",
        "ABM_SPEECHIFY_MARGIN_PERCENT": "60",
        "ABM_SPEECHIFY_FREE_THRESHOLD_EUR": "0.50",
        "ABM_GEMINI_USD_EUR_RATE": "0.86",
        "ABM_GEMINI_PAYPAL_FIXED_FEE_EUR": "0.34",
        "ABM_GEMINI_PAYPAL_PERCENT_FEE": "3.4",
    }.items():
        monkeypatch.setenv(k, v)
    chars = 200_000
    cost_usd = chars / 1e6 * 11.18
    base = cost_usd * 0.86 * 1.60
    gross = (base + 0.34) / (1 - 3.4 / 100)
    expected = round(gross, 2)
    p = speechify_tts.compute_user_price_eur(chars)
    assert p["user_price_eur"] == expected
    assert p["is_free"] is False


def test_estimate_book_cost_sums_chapters(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_COST_USD_PER_MCHAR", "11.18")

    class _Ch:
        def __init__(self, text):
            self.text = text

    chapters = [_Ch("a" * 100_000), _Ch("b" * 100_000)]
    est = speechify_tts.estimate_book_cost(chapters, language="en")
    assert est["chars_total"] == 200_000
    assert est["chars_per_chapter"] == [100_000, 100_000]
    assert est["model_key"] == "simba-3.2"
    assert est["user_price_eur"] == speechify_tts.compute_user_price_eur(200_000)["user_price_eur"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_pricing.py::test_price_matches_formula -v`
Expected: FAIL con `AttributeError: ... 'compute_user_price_eur'`.

- [ ] **Step 3: Add pricing to `speechify_tts.py`**

```python
def compute_user_price_eur(chars):
    """Prezzo finale utente per `chars` caratteri.

    Formula (allineata a gemini_tts.compute_user_price_eur):
        cost_usd = chars/1e6 * COST_USD_PER_MCHAR
        base_eur = cost_usd * USD_EUR_RATE * (1 + margin/100)
        gross    = (base_eur + PAYPAL_FIXED_FEE) / (1 - PAYPAL_PERCENT/100)
        user     = round(gross, 2); is_free se < FREE_THRESHOLD.
    """
    if chars is None or chars < 0:
        chars = 0
    cost_usd = chars / 1_000_000.0 * cost_usd_per_mchar()
    margin = margin_percent()
    base_eur = cost_usd * usd_eur_rate() * (1.0 + margin / 100.0)
    paypal_factor = 1.0 - (paypal_percent_fee() / 100.0)
    if paypal_factor <= 0:
        raise ValueError("PAYPAL_PERCENT_FEE >= 100, invalid config")
    gross = (base_eur + paypal_fixed_fee_eur()) / paypal_factor
    user_price = round(gross, 2)
    threshold = free_threshold_eur()
    is_free = user_price < threshold
    return {
        "chars": chars,
        "cost_usd": round(cost_usd, 6),
        "base_price_eur": round(base_eur, 4),
        "margin_percent": margin,
        "user_price_eur": 0.0 if is_free else user_price,
        "is_free": is_free,
        "free_threshold_eur": threshold,
    }


def estimate_book_cost(chapters, language="en"):
    """Stima costo end-to-end su caratteri di input (somma capitoli).

    Args:
        chapters: lista di oggetti con attributo `.text`.
        language: ISO 639-1 (solo 'en' supportato; parametro per simmetria).
    """
    chars_per_chapter = []
    chars_total = 0
    for ch in chapters:
        txt = getattr(ch, "text", "") or ""
        n = len(txt)
        chars_per_chapter.append(n)
        chars_total += n
    price = compute_user_price_eur(chars_total)
    return {
        "chars_total": chars_total,
        "chars_per_chapter": chars_per_chapter,
        "cost_usd": price["cost_usd"],
        "user_price_eur": price["user_price_eur"],
        "is_free": price["is_free"],
        "margin_percent": price["margin_percent"],
        "language": language,
        "model_key": MODEL_ID,
        "model_label": MODEL_LABEL,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_pricing.py -v`
Expected: PASS (tutti).

- [ ] **Step 5: Commit**

```bash
git add speechify_tts.py test/test_speechify_pricing.py
git commit -m "feat(speechify): pricing utente (formula premium condivisa)"
```

---

## Task 5: `speechify_tts` — gate concorrenza globale + admission

**Files:**
- Modify: `speechify_tts.py`
- Test: `test/test_speechify_concurrency.py`

**Interfaces:**
- Consumes: `max_concurrency` (Task 3).
- Produces:
  - `acquire_slot(timeout=None) -> bool` — blocca finché un permesso globale e' libero (o timeout); True se acquisito.
  - `release_slot()` — rilascia un permesso.
  - `slot()` — context manager (`with speechify_tts.slot(): ...`).
  - `active_slots() -> int`, `free_slots() -> int` — introspezione (per status "in attesa").
  - `_reset_gate_for_test()` — reset stato (solo test).

**Design:** Un contatore protetto da `Condition` che **rilegge `max_concurrency()` a ogni acquire** (reload runtime senza restart, come da spec §5.3). L'invariante `active ≤ N` vale in ogni istante; se N viene abbassato a runtime sotto il numero di slot gia' attivi, non si forza il rilascio (i job in corso finiscono) ma non se ne concedono di nuovi finché `active < N`.

- [ ] **Step 1: Write the failing test — create `test/test_speechify_concurrency.py`**

```python
import threading
import time
import speechify_tts


def setup_function():
    speechify_tts._reset_gate_for_test()


def test_acquire_release_counts(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_MAX_CONCURRENCY", "2")
    assert speechify_tts.active_slots() == 0
    assert speechify_tts.acquire_slot(timeout=1) is True
    assert speechify_tts.active_slots() == 1
    speechify_tts.release_slot()
    assert speechify_tts.active_slots() == 0


def test_gate_blocks_beyond_n(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_MAX_CONCURRENCY", "2")
    assert speechify_tts.acquire_slot(timeout=1) is True
    assert speechify_tts.acquire_slot(timeout=1) is True
    # Terzo acquire deve fallire in timeout (nessuno slot libero).
    t0 = time.time()
    assert speechify_tts.acquire_slot(timeout=0.3) is False
    assert time.time() - t0 >= 0.3
    speechify_tts.release_slot()
    speechify_tts.release_slot()


def test_blocked_acquire_unblocks_on_release(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_MAX_CONCURRENCY", "1")
    assert speechify_tts.acquire_slot(timeout=1) is True
    results = []

    def _worker():
        results.append(speechify_tts.acquire_slot(timeout=2))

    th = threading.Thread(target=_worker)
    th.start()
    time.sleep(0.2)
    assert results == []            # ancora bloccato
    speechify_tts.release_slot()    # libera lo slot
    th.join(timeout=2)
    assert results == [True]        # sbloccato
    speechify_tts.release_slot()


def test_context_manager(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_MAX_CONCURRENCY", "1")
    with speechify_tts.slot():
        assert speechify_tts.active_slots() == 1
    assert speechify_tts.active_slots() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_concurrency.py -v`
Expected: FAIL con `AttributeError: ... '_reset_gate_for_test'`.

- [ ] **Step 3: Add gate to `speechify_tts.py`**

```python
# === Gate di concorrenza globale (limite abbonamento) =======================
# Un permesso per chiamata API. Ogni synthesize acquisisce/rilascia uno slot;
# l'invariante `active <= max_concurrency()` vale su tutti i job/client del
# processo. max_concurrency() e' riletto a ogni acquire (reload runtime).
import contextlib as _contextlib

_gate_lock = threading.Condition()
_gate_active = 0


def _reset_gate_for_test():
    """Reset dello stato del gate (solo test)."""
    global _gate_active
    with _gate_lock:
        _gate_active = 0
        _gate_lock.notify_all()


def acquire_slot(timeout=None):
    """Acquisisce un permesso globale, bloccando finche' `active < N`.

    Returns True se acquisito, False su timeout. timeout=None => attesa
    indefinita (admission gating trasparente).
    """
    global _gate_active
    deadline = None if timeout is None else (time.monotonic() + timeout)
    with _gate_lock:
        while _gate_active >= max_concurrency():
            if deadline is None:
                _gate_lock.wait()
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                _gate_lock.wait(timeout=remaining)
        _gate_active += 1
        return True


def release_slot():
    """Rilascia un permesso globale e sveglia un eventuale waiter."""
    global _gate_active
    with _gate_lock:
        if _gate_active > 0:
            _gate_active -= 1
        _gate_lock.notify()


def active_slots():
    with _gate_lock:
        return _gate_active


def free_slots():
    with _gate_lock:
        return max(0, max_concurrency() - _gate_active)


@_contextlib.contextmanager
def slot(timeout=None):
    """Context manager: acquisisce uno slot per la durata del blocco."""
    ok = acquire_slot(timeout=timeout)
    if not ok:
        raise TimeoutError("Speechify concurrency slot not available")
    try:
        yield
    finally:
        release_slot()
```

Aggiungere `import time` in cima al modulo (con gli altri import).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_concurrency.py -v`
Expected: PASS (4 test).

- [ ] **Step 5: Commit**

```bash
git add speechify_tts.py test/test_speechify_concurrency.py
git commit -m "feat(speechify): gate concorrenza globale con admission gating"
```

---

## Task 6: `speechify_tts` — `synthesize` (HTTP, WAV→PCM, 429/Retry-After)

**Files:**
- Modify: `speechify_tts.py`
- Test: `test/test_speechify_synthesize.py`

**Interfaces:**
- Consumes: `api_key`, `parse_voice_id`, `voice_locale`, gate `slot()` (Task 5), `EMOTIONS`.
- Produces:
  - `class SpeechifyUnavailable(RuntimeError)`.
  - `synthesize(text, voice_id, output_path, emotion=None, rate="+0%", max_attempts=3, session=None) -> dict` con `success, bytes_written, sample_rate, channels, billable_chars, voice_name`. Scrive **PCM raw** (little-endian 16-bit) in `output_path`. Ogni chiamata HTTP e' avvolta dal gate globale. 429/5xx → retry con `Retry-After`/backoff; 4xx non-429 → `RuntimeError` immediata (fail-fast). Se non disponibile → `SpeechifyUnavailable`.
  - `_wav_bytes_to_pcm(wav_bytes) -> (pcm_bytes, sample_rate, channels)` — legge l'header WAV dinamicamente.
  - `build_ssml(text, emotion=None, rate="+0%") -> str`.

- [ ] **Step 1: Write the failing test — create `test/test_speechify_synthesize.py`**

```python
import base64
import io
import wave
import types
import pytest
import speechify_tts


def _make_wav_bytes(sample_rate=48000, n_frames=2400):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x01\x00" * n_frames)
    return buf.getvalue()


class _Resp:
    def __init__(self, status, json_data=None, headers=None):
        self.status_code = status
        self._json = json_data or {}
        self.headers = headers or {}
        self.text = "err"

    def json(self):
        return self._json


class _Session:
    """Finto requests.Session: restituisce risposte da una coda."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self._responses.pop(0)


def test_build_ssml_includes_emotion():
    ssml = speechify_tts.build_ssml("Hello", emotion="cheerful")
    assert "cheerful" in ssml
    assert "Hello" in ssml


def test_build_ssml_ignores_unknown_emotion():
    ssml = speechify_tts.build_ssml("Hi", emotion="not_an_emotion")
    assert "not_an_emotion" not in ssml


def test_synthesize_writes_pcm(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    monkeypatch.setenv("ABM_SPEECHIFY_MAX_CONCURRENCY", "2")
    speechify_tts._reset_gate_for_test()
    wav = _make_wav_bytes()
    resp = _Resp(200, {"audio_data": base64.b64encode(wav).decode(),
                       "billable_characters_count": 5})
    sess = _Session([resp])
    out = tmp_path / "chunk.pcm"
    res = speechify_tts.synthesize("Hello", "speechify:simba-3.2:harper_32",
                                   str(out), emotion="calm", session=sess)
    assert res["success"] is True
    assert res["sample_rate"] == 48000
    assert res["channels"] == 1
    assert res["billable_chars"] == 5
    assert out.read_bytes() == b"\x01\x00" * 2400
    # gate rilasciato a fine chiamata
    assert speechify_tts.active_slots() == 0
    # language derivato dalla voce (en-US)
    assert sess.calls[0]["json"].get("language") == "en-US"


def test_synthesize_retries_on_429(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    speechify_tts._reset_gate_for_test()
    monkeypatch.setattr(speechify_tts.time, "sleep", lambda *_: None)
    wav = _make_wav_bytes()
    ok = _Resp(200, {"audio_data": base64.b64encode(wav).decode(),
                     "billable_characters_count": 1})
    sess = _Session([_Resp(429, headers={"Retry-After": "0"}), ok])
    out = tmp_path / "c.pcm"
    res = speechify_tts.synthesize("Hi", "speechify:simba-3.2:dominic_32",
                                   str(out), session=sess, max_attempts=3)
    assert res["success"] is True
    assert len(sess.calls) == 2


def test_synthesize_fatal_on_400(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    speechify_tts._reset_gate_for_test()
    sess = _Session([_Resp(400)])
    out = tmp_path / "c.pcm"
    with pytest.raises(RuntimeError):
        speechify_tts.synthesize("Hi", "speechify:simba-3.2:dominic_32",
                                 str(out), session=sess, max_attempts=3)
    assert len(sess.calls) == 1  # nessun retry su 4xx
    assert speechify_tts.active_slots() == 0


def test_synthesize_unavailable_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ABM_SPEECHIFY_API_KEY", raising=False)
    with pytest.raises(speechify_tts.SpeechifyUnavailable):
        speechify_tts.synthesize("Hi", "speechify:simba-3.2:dominic_32",
                                 str(tmp_path / "c.pcm"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_synthesize.py -v`
Expected: FAIL con `AttributeError: ... 'build_ssml'`.

- [ ] **Step 3: Add synthesize to `speechify_tts.py`**

```python
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class SpeechifyUnavailable(RuntimeError):
    """TTS Speechify non disponibile (API key mancante)."""


def build_ssml(text, emotion=None, rate="+0%"):
    """Costruisce l'SSML con emozione (se valida) e rate (se != +0%)."""
    inner = text
    if rate and rate not in ("+0%", "0%", "+0", 0):
        pct = str(rate).replace("%", "").replace("+", "")
        try:
            n = int(pct)
            if n != 0:
                inner = f'<prosody rate="{n:+d}%">{inner}</prosody>'
        except ValueError:
            pass
    emo = (emotion or "").strip().lower()
    if emo and emo in EMOTIONS:
        inner = f'<speechify:style emotion="{emo}">{inner}</speechify:style>'
    return f'<speak>{inner}</speak>'


def _wav_bytes_to_pcm(wav_bytes):
    """Estrae PCM raw + (sample_rate, channels) leggendo l'header WAV.

    L'header e' riletto dinamicamente (mai assunto 48kHz).
    """
    with _wave_open(io.BytesIO(wav_bytes)) as w:
        channels = w.getnchannels()
        rate = w.getframerate()
        frames = w.readframes(w.getnframes())
    return frames, rate, channels


def _wave_open(fileobj):
    return wave.open(fileobj, "rb")


def _retry_after_seconds(resp, attempt):
    """Secondi da attendere: header Retry-After se presente, altrimenti backoff."""
    ra = resp.headers.get("Retry-After") if resp is not None else None
    if ra is not None:
        try:
            return max(0.0, float(ra))
        except (ValueError, TypeError):
            pass
    return min(30.0, 2.0 ** attempt)


def synthesize(text, voice_id, output_path, emotion=None, rate="+0%",
               max_attempts=3, session=None):
    """Sintetizza `text` in PCM raw 16-bit mono via Speechify Simba-3.2.

    Scrive PCM in output_path. Ogni chiamata HTTP passa dal gate globale
    (invariante concorrenza). Ritorna dict con success/bytes_written/
    sample_rate/channels/billable_chars/voice_name.

    Raises:
        SpeechifyUnavailable se API key mancante.
        RuntimeError su 4xx non-429 (fail-fast) o dopo esaurimento retry.
        ValueError se voice_id invalido.
    """
    if not is_available():
        raise SpeechifyUnavailable("Speechify TTS not available (check ABM_SPEECHIFY_API_KEY)")
    model_key, voice_name, locale = parse_voice_id(voice_id)

    if session is None:
        import requests
        session = requests.Session()

    ssml = build_ssml(text, emotion=emotion, rate=rate)
    payload = {
        "input": ssml,
        "voice_id": voice_name,
        "model": MODEL_ID,
        "language": locale,
        "audio_format": "wav",
    }
    headers = {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
    }
    url = API_BASE + SPEECH_ENDPOINT

    last_error = None
    for attempt in range(max_attempts):
        with slot():  # gate globale: acquisisce/rilascia un permesso per chiamata
            resp = session.post(url, json=payload, headers=headers, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            wav_b64 = data.get("audio_data") or ""
            wav_bytes = base64.b64decode(wav_b64)
            pcm, rate_hz, channels = _wav_bytes_to_pcm(wav_bytes)
            with open(output_path, "wb") as fp:
                fp.write(pcm)
            return {
                "success": True,
                "bytes_written": len(pcm),
                "sample_rate": rate_hz,
                "channels": channels,
                "billable_chars": int(data.get("billable_characters_count", len(text)) or 0),
                "voice_name": voice_name,
            }
        if resp.status_code not in _RETRYABLE_STATUS:
            raise RuntimeError(f"Speechify HTTP {resp.status_code} (fatal): {getattr(resp, 'text', '')[:200]}")
        last_error = f"HTTP {resp.status_code}"
        if attempt < max_attempts - 1:
            time.sleep(_retry_after_seconds(resp, attempt))

    raise RuntimeError(f"Speechify synthesis failed after {max_attempts} attempts: {last_error}")
```

Nota: `_wave_open` e' un wrapper indiretto per facilitare eventuali mock; `io`/`wave`/`base64` sono gia' importati (Task 2/import top).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_synthesize.py -v`
Expected: PASS (6 test).

- [ ] **Step 5: Commit**

```bash
git add speechify_tts.py test/test_speechify_synthesize.py
git commit -m "feat(speechify): synthesize speech endpoint (WAV->PCM, 429/Retry-After, gate)"
```

---

## Task 7: `tts_split` — `generate_chunk_pcm_speechify`

**Files:**
- Modify: `tts_split.py`
- Test: `test/test_speechify_synthesize.py` (estensione)

**Interfaces:**
- Consumes: `speechify_tts.synthesize`, `_sanitize_tts_text`, `_generate_silence_pcm` (già in tts_split.py).
- Produces:
  - `generate_chunk_pcm_speechify(text, voice_id, output_path, emotion=None, rate="+0%", max_retries=1, failure_info=None) -> dict|False`. Su `SpeechifyUnavailable` **ri-solleva** (non silenzia: un errore permanente silenzierebbe l'intero libro, cfr. incidente Gemini 2026-06). Su testo vuoto o fallimento totale scrive silenzio PCM e ritorna False.

- [ ] **Step 1: Write the failing test (append to `test/test_speechify_synthesize.py`)**

```python
import tts_split


def test_generate_chunk_speechify_success(monkeypatch, tmp_path):
    calls = {}

    def _fake_synth(text, voice_id, output_path, emotion=None, rate="+0%", **kw):
        calls["text"] = text
        calls["emotion"] = emotion
        with open(output_path, "wb") as fp:
            fp.write(b"\x00\x00" * 100)
        return {"success": True, "bytes_written": 200, "sample_rate": 48000,
                "channels": 1, "billable_chars": len(text), "voice_name": "harper_32"}

    monkeypatch.setattr("speechify_tts.synthesize", _fake_synth)
    out = tmp_path / "c.pcm"
    res = tts_split.generate_chunk_pcm_speechify(
        "Hello world", "speechify:simba-3.2:harper_32", str(out), emotion="warm")
    assert res["success"] is True
    assert calls["emotion"] == "warm"
    assert out.exists()


def test_generate_chunk_speechify_reraises_unavailable(monkeypatch, tmp_path):
    import speechify_tts

    def _boom(*a, **k):
        raise speechify_tts.SpeechifyUnavailable("no key")

    monkeypatch.setattr("speechify_tts.synthesize", _boom)
    with pytest.raises(speechify_tts.SpeechifyUnavailable):
        tts_split.generate_chunk_pcm_speechify(
            "Hi", "speechify:simba-3.2:harper_32", str(tmp_path / "c.pcm"))


def test_generate_chunk_speechify_empty_text_silence(monkeypatch, tmp_path):
    out = tmp_path / "c.pcm"
    res = tts_split.generate_chunk_pcm_speechify(
        "   ", "speechify:simba-3.2:harper_32", str(out))
    assert res is False
    assert out.exists()  # silenzio PCM scritto
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_synthesize.py::test_generate_chunk_speechify_success -v`
Expected: FAIL con `AttributeError: module 'tts_split' has no attribute 'generate_chunk_pcm_speechify'`.

- [ ] **Step 3: Add wrapper to `tts_split.py`** (subito dopo `generate_chunk_pcm_gemini`)

```python
def generate_chunk_pcm_speechify(text, voice_id, output_path, emotion=None,
                                 rate="+0%", max_retries=1, failure_info=None):
    """Genera PCM 16-bit mono da testo via Speechify Simba-3.2 con fallback silenzio.

    SpeechifyUnavailable viene ri-sollevata (errore permanente: silenziarlo
    silenzierebbe l'intero libro). Su testo vuoto o fallimento totale scrive
    silenzio PCM e ritorna False.
    """
    import speechify_tts as _spx

    def _fail(reason, detail=""):
        if isinstance(failure_info, dict):
            failure_info["reason"] = reason
            failure_info["detail"] = str(detail)[:300]
        return False

    clean = _sanitize_tts_text(text)
    if clean is None:
        _generate_silence_pcm(output_path, duration_sec=1)
        return _fail("empty_after_sanitize")

    last_error = None
    for attempt in range(max_retries):
        try:
            return _spx.synthesize(clean, voice_id, output_path,
                                   emotion=emotion, rate=rate)
        except _spx.SpeechifyUnavailable:
            raise  # non silenziare: il caller decide
        except Exception as e:
            last_error = e
            snippet = clean[:60].replace('\n', ' ')
            print(f"[speechify] Attempt {attempt+1}/{max_retries} failed "
                  f"({len(clean)} chars: \"{snippet}...\"): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    print(f"[speechify] WARNING: all {max_retries} attempts failed, silence "
          f"({len(clean)} chars). Last error: {last_error}")
    _generate_silence_pcm(output_path, duration_sec=1)
    return _fail("synthesize_failed", str(last_error) if last_error else "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_synthesize.py -v`
Expected: PASS (tutti, inclusi i 3 nuovi).

- [ ] **Step 5: Commit**

```bash
git add tts_split.py test/test_speechify_synthesize.py
git commit -m "feat(speechify): generate_chunk_pcm_speechify con fallback silenzio"
```

---

## Task 8: `generation_engine` — `_engine_for_voice` ramo speechify

**Files:**
- Modify: `generation_engine.py` (import + `_engine_for_voice` :2801)
- Test: `test/test_speechify_engine_dispatch.py`

**Interfaces:**
- Consumes: `voice_utils.is_speechify_voice` (Task 1).
- Produces: `_engine_for_voice("speechify:...") == "speechify"`.

- [ ] **Step 1: Write the failing test — create `test/test_speechify_engine_dispatch.py`**

```python
import generation_engine


def test_engine_for_speechify_voice():
    assert generation_engine._engine_for_voice("speechify:simba-3.2:harper_32") == "speechify"


def test_engine_for_gemini_still_gemini():
    assert generation_engine._engine_for_voice("gemini:flash25:Zephyr") == "gemini"


def test_engine_for_edge_default():
    assert generation_engine._engine_for_voice("en-US-GuyNeural") == "edge"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_engine_dispatch.py -v`
Expected: FAIL (`_engine_for_voice` ritorna "edge" per speechify).

- [ ] **Step 3: Wire the branch**

In `generation_engine.py`, verificare che in cima al modulo sia importato `is_speechify_voice` (accanto a `_is_gemini_voice`). Cercare l'import esistente di `voice_utils`:

```python
from voice_utils import is_gemini_voice as _is_gemini_voice
```

Aggiungere sulla riga seguente:

```python
from voice_utils import is_speechify_voice as _is_speechify_voice
```

Poi in `_engine_for_voice` (:2801), aggiungere il ramo **prima** del check gemini:

```python
def _engine_for_voice(voice):
    """Sceglie il motore TTS dal voice ID.

    Prefissi:
      - "speechify:..." -> Speechify Simba-3.2 (PCM native)
      - "gemini:..."    -> Gemini TTS (PCM native)
      - "gcloud:..."    -> Google Cloud TTS Chirp3-HD (MP3)
      - altrimenti      -> Microsoft Edge TTS (MP3, default)
    """
    if not voice:
        return "edge"
    if _is_speechify_voice(voice):
        return "speechify"
    if _is_gemini_voice(voice):
        return "gemini"
    if _google_tts is not None and _google_tts.is_google_voice(voice):
        return "google"
    return "edge"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_engine_dispatch.py -v`
Expected: PASS (3 test).

- [ ] **Step 5: Commit**

```bash
git add generation_engine.py test/test_speechify_engine_dispatch.py
git commit -m "feat(speechify): _engine_for_voice riconosce l'engine speechify"
```

---

## Task 9: `generation_engine` — `run_generation` ramo sintesi Speechify

**Files:**
- Modify: `generation_engine.py` (`run_generation` :3218, `_synthesize_chunk` :3477, firma + wrapper)
- Test: `test/test_speechify_engine_dispatch.py` (estensione, integrazione con synth mockata)

**Interfaces:**
- Consumes: `generate_chunk_pcm_speechify` (Task 7), gate `speechify_tts` (Task 5).
- Produces:
  - `run_generation(..., gemini_style_instruction=None, speechify_emotion=None)` — firma estesa.
  - Ramo `use_speechify`: sintesi PCM per-chunk via `generate_chunk_pcm_speechify`, emozione da `speechify_emotion`, riuso del percorso di assemblaggio PCM esistente (`use_gemini`-like). Concorrenza per-job tramite `ThreadPoolExecutor(max_workers=min(K, N))` che pre-sintetizza i chunk; ogni chiamata attraversa il gate globale (admission gating trasparente).

**Design note (concorrenza):** La sintesi PCM dei chunk avviene in un pool di dimensione `min(per_job_concurrency(), max_concurrency())`. Ogni task chiama `generate_chunk_pcm_speechify` → `synthesize` che acquisisce **1 permesso globale** per la durata della chiamata HTTP. Quindi: chiamate simultanee del singolo job ≤ K, chiamate simultanee su tutti i job ≤ N. Se il pool globale e' saturo, i task si bloccano sull'`acquire_slot` (attesa trasparente); il job resta "generating" con messaggio "in attesa di uno slot". L'assemblaggio (concat PCM, marker M4B) resta sequenziale e legge i file gia' prodotti.

- [ ] **Step 1: Write the failing integration test (append to `test/test_speechify_engine_dispatch.py`)**

```python
import os
import types


def test_run_generation_speechify_smoke(monkeypatch, tmp_path):
    """Smoke: run_generation con voce speechify sintetizza tutti i chunk via
    generate_chunk_pcm_speechify (mockata) e assembla un output PCM->M4B senza
    toccare l'API reale."""
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    import generation_engine as ge
    import speechify_tts
    speechify_tts._reset_gate_for_test()

    synth_calls = []

    def _fake_chunk(text, voice_id, output_path, emotion=None, rate="+0%", **kw):
        synth_calls.append({"text": text, "emotion": emotion})
        with open(output_path, "wb") as fp:
            fp.write(b"\x00\x00" * 4800)  # 0.1s @ 48kHz mono 16-bit
        return {"success": True, "bytes_written": 9600, "sample_rate": 48000,
                "channels": 1, "billable_chars": len(text), "voice_name": "harper_32"}

    monkeypatch.setattr(ge, "generate_chunk_pcm_speechify", _fake_chunk, raising=False)

    # Job minimale + info a 1 capitolo. Riusare l'helper di fixture del progetto
    # se presente; altrimenti costruire un _SimpleBookInfo con un capitolo.
    job_id, info = _make_speechify_job(ge, tmp_path, text="Hello world. Second sentence.")
    ge.run_generation(job_id, info, "speechify:simba-3.2:harper_32", "+0%",
                      single_file=True, output_format="mp3",
                      speechify_emotion="cheerful")

    job = ge._jobs.get(job_id)
    assert job["status"] in ("done", "completed")
    assert len(synth_calls) >= 1
    assert all(c["emotion"] == "cheerful" for c in synth_calls)
```

> **Nota per l'implementatore:** `_make_speechify_job` e' un helper di test da scrivere in cima al file, che replica il minimo setup usato dai test esistenti di `run_generation` (registra `ge._jobs[job_id]`, crea `UPLOAD_DIR/job_id`, costruisce un `_SimpleBookInfo` con un `Chapter`). Ispezionare un test di generazione esistente (es. `test/test_engine_dispatch.py` o simili in `test/`) e riusare lo stesso pattern di `configure()`/fixture. Se l'ambiente di test non ha FFmpeg, marcare il test con `@pytest.mark.skipif` sulla presenza di ffmpeg, coerente con gli altri test audio.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_engine_dispatch.py::test_run_generation_speechify_smoke -v`
Expected: FAIL (firma `run_generation` non accetta `speechify_emotion`, ramo assente).

- [ ] **Step 3a: Estendere la firma e i flag engine**

In `run_generation` (:3218) cambiare la firma:

```python
def run_generation(job_id, info, voice, rate, single_file, output_format='m4b', podcast_base_url='', gemini_style_instruction=None, speechify_emotion=None):
```

Dopo il blocco che imposta `use_google`/`use_gemini` (:3262-3263), aggiungere:

```python
    use_speechify = (engine == "speechify")
    # Emozione Speechify (None/"" = neutro). Persistita anche su job per diagnosi.
    if use_speechify:
        speechify_emotion = speechify_emotion or job.get("speechify_emotion")
```

- [ ] **Step 3b: Trattare speechify come PCM nell'assemblaggio**

Il percorso di assemblaggio PCM e' gateato da `use_gemini` in piu' punti (silence sizing :3620, `pcm_size_to_seconds`, concat PCM, M4B). Introdurre una variabile locale `use_pcm = use_gemini or use_speechify` **subito dopo** `use_speechify = ...` e sostituire nei punti di assemblaggio i test `if use_gemini:` **che riguardano il formato audio PCM** (NON la contabilita' token/costo Gemini) con `if use_pcm:`. Punti da aggiornare (verificare per contesto, sono tutti nel corpo di `run_generation`):

- Silence sizing single-file (:3620): `if use_gemini and os.path.exists(silence_path):` → `if use_pcm and os.path.exists(silence_path):`
- Eventuale ramo analogo nel percorso multi-file (cercare `pcm_size_to_seconds` e `silence_ms` nel ramo `else`/multi-file).
- Concatenazione finale: dove si sceglie `pcm_concat` vs concat MP3 in base a `use_gemini`, usare `use_pcm`.
- Sample rate dell'encode: per Gemini e' 24000 fisso; per Speechify va usato il sample rate REALE letto dal primo chunk. Dove il codice passa `24000` all'encoder PCM→AAC in ramo Gemini, per speechify passare `job.get("speechify_sample_rate", 48000)` (popolato in 3d).

> **Nota:** la contabilita' Gemini (`gemini_usage`, `job["gemini_actual"]`, `record_usage`, `record_rate_sample`, `google_cost_breakdown`, trim silenzio, accent directive, preflight RPD) resta gateata da `use_gemini` e NON deve attivarsi per speechify.

- [ ] **Step 3c: Ramo speechify in `_synthesize_chunk`**

In `_synthesize_chunk` (:3477), aggiungere il ramo speechify **prima** di `if use_gemini:`, e usare i risultati pre-sintetizzati se presenti (vedi 3d):

```python
            if use_speechify:
                part_path = str(work_dir / f"chunk_{i:06d}.pcm")
                pre = _speechify_pre.get(i) if '_speechify_pre' in dir() else None
                if pre is not None:
                    return pre, part_path
                _chunk_fi = {}
                result = generate_chunk_pcm_speechify(
                    block["text"], voice, part_path,
                    emotion=speechify_emotion, rate=rate, failure_info=_chunk_fi)
                if result is False:
                    return result, part_path
                # Registra il sample rate reale una volta (per l'encode M4B).
                if not job.get("speechify_sample_rate"):
                    job["speechify_sample_rate"] = result.get("sample_rate", 48000)
                return result, part_path
```

> Semplificazione: se il pattern `'_speechify_pre' in dir()` risulta fragile nel contesto della closure, definire `_speechify_pre = {}` come variabile del frame di `run_generation` **prima** della definizione di `_synthesize_chunk` (analogo a `gemini_usage`). Allora il ramo diventa `pre = _speechify_pre.get(i)`.

- [ ] **Step 3d: Pre-sintesi parallela (per-job concurrency)**

Subito **prima** del ramo `if single_file:` (:3616), dopo la definizione di `_synthesize_chunk`, inserire la pre-sintesi parallela per speechify:

```python
        # Pre-sintesi parallela Speechify: pool di min(K, N) worker; ogni chiamata
        # attraversa il gate globale (invariante concorrenza abbonamento). L'attesa
        # su slot saturo e' trasparente (admission gating). L'assemblaggio sotto
        # resta sequenziale e legge i .pcm gia' prodotti.
        _speechify_pre = {}
        if use_speechify:
            import concurrent.futures as _cf
            k = speechify_tts.per_job_concurrency()
            n = speechify_tts.max_concurrency()
            workers = max(1, min(k, n))
            if speechify_tts.free_slots() <= 0:
                job["progress_message"] = "In attesa di uno slot disponibile..."
            def _pre_one(idx_block):
                _idx, _block = idx_block
                _pp = str(work_dir / f"chunk_{_idx:06d}.pcm")
                _fi = {}
                _res = generate_chunk_pcm_speechify(
                    _block["text"], voice, _pp,
                    emotion=speechify_emotion, rate=rate, failure_info=_fi)
                return _idx, _res
            with _cf.ThreadPoolExecutor(max_workers=workers) as _ex:
                for _idx, _res in _ex.map(_pre_one, list(enumerate(plan))):
                    _speechify_pre[_idx] = _res
                    if not job.get("speechify_sample_rate") and isinstance(_res, dict):
                        job["speechify_sample_rate"] = _res.get("sample_rate", 48000)
            job["progress_message"] = "Assembling audio..."
```

> **SpeechifyUnavailable durante la pre-sintesi:** propaga fuori dal pool e viene intercettata dal `try/except` esterno di `run_generation` che marca il job in errore (stesso trattamento job-fatal di `GeminiUnavailable`). Verificare che il blocco `except` generale di `run_generation` marchi status "error" e faccia refund via i path esistenti (non aggiungere logica nuova qui; il refund premium e' agganciato al fallimento job come per Gemini).

- [ ] **Step 3e: Import del gate e del wrapper**

In cima a `generation_engine.py`, dove si importano `gemini_tts`/`generate_chunk_pcm_gemini`, aggiungere:

```python
import speechify_tts
from tts_split import generate_chunk_pcm_speechify
```

(coerente con come `generate_chunk_pcm_gemini` e' gia' importato/nominato nel modulo; se gli import di `tts_split` sono raggruppati, aggiungere `generate_chunk_pcm_speechify` alla stessa riga).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_engine_dispatch.py -v`
Expected: PASS. Se FFmpeg assente in CI, lo smoke e' skippato ma i test di dispatch passano.

Verifica sintassi: `python -m py_compile generation_engine.py`

- [ ] **Step 5: Commit**

```bash
git add generation_engine.py test/test_speechify_engine_dispatch.py
git commit -m "feat(speechify): run_generation ramo sintesi PCM + concorrenza per-job"
```

---

## Task 10: `audiobook_app` — `/api/voices` merge Speechify

**Files:**
- Modify: `audiobook_app.py` (endpoint `/api/voices` ~:6027; import in cima)
- Test: `test/test_speechify_endpoints.py`

**Interfaces:**
- Consumes: `speechify_tts.is_available`, `speechify_tts.get_voices` (Task 2/3).
- Produces: `/api/voices` include, sotto `voices["en"]`, le 8 voci speechify quando `is_available()`; assenti se key mancante.

- [ ] **Step 1: Write the failing test — create `test/test_speechify_endpoints.py`**

```python
import json
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    import audiobook_app
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


def test_voices_include_speechify_when_available(client):
    r = client.get("/api/voices")
    assert r.status_code == 200
    data = r.get_json()
    en = data["voices"].get("en", {})
    entries = en.get("voices", en) if isinstance(en, dict) else en
    ids = [v["id"] for v in entries]
    assert any(i.startswith("speechify:simba-3.2:") for i in ids)


def test_voices_exclude_speechify_without_key(monkeypatch):
    monkeypatch.delenv("ABM_SPEECHIFY_API_KEY", raising=False)
    import importlib, audiobook_app
    importlib.reload(audiobook_app)
    audiobook_app.app.config["TESTING"] = True
    c = audiobook_app.app.test_client()
    r = c.get("/api/voices")
    data = r.get_json()
    en = data["voices"].get("en", {})
    entries = en.get("voices", en) if isinstance(en, dict) else en
    ids = [v["id"] for v in entries]
    assert not any(i.startswith("speechify:") for i in ids)
```

> **Nota:** adeguare l'accesso a `data["voices"]["en"]` alla forma reale dell'endpoint (leggere `/api/voices` :6027-6060 per la struttura esatta: `{lang: {voices:[...]}}` vs `{lang:[...]}`). Il test sopra e' difensivo su entrambe.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_endpoints.py::test_voices_include_speechify_when_available -v`
Expected: FAIL (nessuna voce speechify nel merge).

- [ ] **Step 3: Merge nel `/api/voices`**

In cima a `audiobook_app.py`, accanto agli import engine (`import gemini_tts`), aggiungere:

```python
import speechify_tts
```

Nell'endpoint `/api/voices` (~:6027), dopo che il catalogo Gemini viene fuso nel dict `voices`, aggiungere un merge analogo (adattare i nomi variabile alla struttura reale letta al passo 1):

```python
    # Merge voci Speechify Simba-3.2 (solo inglese, solo se API key configurata).
    try:
        if speechify_tts.is_available():
            spx = speechify_tts.get_voices()
            for lang_code, entries in spx.items():
                bucket = voices.setdefault(lang_code, {"voices": []})
                # Adattare alla forma reale: se voices[lang] e' una lista, appendere
                # direttamente; se e' {"voices": [...]}, appendere in bucket["voices"].
                target = bucket["voices"] if isinstance(bucket, dict) else bucket
                target.extend(entries)
    except Exception as _e:
        print(f"[/api/voices] speechify merge failed (non-fatal): {_e}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_endpoints.py -v`
Expected: PASS (2 test).

- [ ] **Step 5: Commit**

```bash
git add audiobook_app.py test/test_speechify_endpoints.py
git commit -m "feat(speechify): merge voci Simba-3.2 in /api/voices (gated su API key)"
```

---

## Task 11: `audiobook_app` — `/api/combined_estimate` branch Speechify

**Files:**
- Modify: `audiobook_app.py` (`/api/combined_estimate` ~:9601)
- Test: `test/test_speechify_endpoints.py` (estensione)

**Interfaces:**
- Consumes: `speechify_tts.estimate_book_cost` (Task 4), `voice_utils.is_speechify_voice`.
- Produces: `/api/combined_estimate` riconosce voci `speechify:` e ritorna `premium_eur`/breakdown calcolato con la pipeline Speechify (chiave `speechify_breakdown` con `user_price_eur`, `is_free`, `chars_total`, `model_label`).

- [ ] **Step 1: Write the failing test (append to `test/test_speechify_endpoints.py`)**

```python
def test_combined_estimate_speechify(client, monkeypatch):
    """La stima per una voce speechify usa il pricing Speechify."""
    import audiobook_app, speechify_tts

    # Registra un job analizzato minimale con un capitolo noto.
    job_id = _register_estimate_job(audiobook_app, chars=200_000)

    r = client.post("/api/combined_estimate", json={
        "job_id": job_id,
        "voice": "speechify:simba-3.2:harper_32",
        "lang": "en",
    })
    assert r.status_code == 200
    data = r.get_json()
    bd = data.get("speechify_breakdown") or {}
    expected = speechify_tts.compute_user_price_eur(200_000)["user_price_eur"]
    assert bd.get("user_price_eur") == expected
```

> **Nota:** `_register_estimate_job` e' un helper da scrivere che inserisce in `audiobook_app`'s jobs dict un job con `info.chapters` da `chars` caratteri, replicando il setup dei test esistenti di `/api/combined_estimate`. Leggere l'endpoint (:9601-9710) per il contratto esatto di input (nomi campo `job_id`/`voice`/`lang`, gestione `selected_chapters`).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_endpoints.py::test_combined_estimate_speechify -v`
Expected: FAIL (nessun `speechify_breakdown` nella risposta).

- [ ] **Step 3: Branch nell'endpoint**

In `/api/combined_estimate` (:9601), individuare il ramo che gestisce `_is_gemini_voice(voice)` e affiancargli un ramo speechify (prima del gemini, dato che sono prefissi distinti):

```python
    if is_speechify_voice(voice):
        info_est = job.get("info")
        all_chs = list(getattr(info_est, "chapters", []) or [])
        sel = selected_chapters or []
        if sel:
            _by_index = {ch.index: ch for ch in all_chs}
            chs = [_by_index[i] for i in sel if i in _by_index]
        else:
            chs = all_chs
        est = speechify_tts.estimate_book_cost(chs, language="en")
        return jsonify({
            "speechify_breakdown": {
                "user_price_eur": est["user_price_eur"],
                "is_free": est["is_free"],
                "chars_total": est["chars_total"],
                "model_label": est["model_label"],
                "margin_percent": est["margin_percent"],
            },
            "premium_eur": est["user_price_eur"],
            "is_free": est["is_free"],
        })
```

Assicurarsi che `is_speechify_voice` sia importato in `audiobook_app.py` (accanto a `_is_gemini_voice`):

```python
from voice_utils import is_speechify_voice
```

> Adeguare il payload di risposta alla forma attesa dal frontend per la stima premium (vedere come il ramo Gemini popola `gemini_breakdown`/`premium_eur` e replicare i campi che il JS legge in `renderEstimate`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_endpoints.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add audiobook_app.py test/test_speechify_endpoints.py
git commit -m "feat(speechify): /api/combined_estimate calcola il prezzo Simba-3.2"
```

---

## Task 12: `audiobook_app` — `/api/generate` payload + create-order premium + wrapper

**Files:**
- Modify: `audiobook_app.py` (`/api/generate` :7869-8112, wrapper `run_generation` :1890, create-order premium ~:9717)
- Test: `test/test_speechify_endpoints.py` (estensione)

**Interfaces:**
- Consumes: `is_speechify_voice`, `speechify_tts.estimate_book_cost`.
- Produces:
  - `/api/generate` legge `speechify_emotion` (validato contro `EMOTIONS`, altrimenti ""), lo salva in `job["speechify_emotion"]`, e passa `speechify_emotion` a `run_generation` via kwargs.
  - Il preflight pagamento premium riconosce le voci speechify (specchio del ramo gemini): calcola il prezzo con `speechify_tts.estimate_book_cost`, applica lo stesso gate soglia gratuita/consumo token del ramo gemini.
  - Create-order PayPal premium: se esiste un endpoint dedicato `/api/paypal_create_order_gemini`, generalizzarlo o affiancare la stima speechify (l'importo deve combaciare con `/api/combined_estimate`).

- [ ] **Step 1: Write the failing test (append to `test/test_speechify_endpoints.py`)**

```python
def test_generate_passes_speechify_emotion(client, monkeypatch):
    """/api/generate salva l'emozione e la inoltra a run_generation."""
    import audiobook_app

    captured = {}

    def _fake_run(job_id, info, voice, rate, single_file, **kw):
        captured["voice"] = voice
        captured["speechify_emotion"] = kw.get("speechify_emotion")

    monkeypatch.setattr(audiobook_app, "run_generation", _fake_run)
    # Evita che il thread reale parta: patchamo threading.Thread.start se serve,
    # oppure il wrapper e' invocato direttamente. Vedi nota.

    job_id = _register_generate_job(audiobook_app, chars=1000, lang="en")
    r = client.post("/api/generate", json={
        "job_id": job_id,
        "voice": "speechify:simba-3.2:harper_32",
        "rate": "+0%",
        "output_format": "mp3",
        "speechify_emotion": "cheerful",
        "lang": "en",
    })
    assert r.status_code in (200, 202)
    # L'emozione e' stata salvata sul job
    assert audiobook_app._jobs_or_jobs_ref(job_id).get("speechify_emotion") == "cheerful"
```

> **Nota implementativa:** i test esistenti di `/api/generate` mostrano come neutralizzare lo spawn del thread (spesso mockando `threading.Thread` o `run_generation`). `_register_generate_job` e `_jobs_or_jobs_ref` sono helper da scrivere replicando quei test. Se un libro da 1000 char e' sotto soglia gratuita, non serve payment_token (percorso free), semplificando il test. Verificare la soglia con i default (1000 char → prezzo ~0 → free).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_endpoints.py::test_generate_passes_speechify_emotion -v`
Expected: FAIL (`speechify_emotion` non letto/inoltrato).

- [ ] **Step 3a: Leggere e validare `speechify_emotion` in `/api/generate`**

Accanto alla lettura di `style_instruction`/`accent_variant` (:7869-7870), aggiungere:

```python
    speechify_emotion = (data.get("speechify_emotion") or "").strip().lower()
    if speechify_emotion and speechify_emotion not in speechify_tts.EMOTIONS:
        speechify_emotion = ""  # valore ignoto -> neutro
```

- [ ] **Step 3b: Preflight pagamento per voci speechify**

Dopo il blocco `if _is_gemini_voice(voice):` del preflight premium (:7871+), aggiungere un blocco gemello `if is_speechify_voice(voice):` che:
- ricalcola `chs_pre` (selezione) come nel ramo gemini;
- verifica il cap `_effective_max_text_chars(voice, job)` (estendere `_effective_max_text_chars` per trattare le voci speechify come premium — stesso cap dei gemini, `MAX_GEMINI_TEXT_CHARS`, oppure un nuovo `MAX_SPEECHIFY_TEXT_CHARS` che di default eguaglia quello gemini);
- calcola il prezzo con `speechify_tts.estimate_book_cost(chs_pre, language="en")`;
- applica lo stesso gate soglia/consumo token del ramo gemini (riusare la funzione condivisa che consuma `payment_token` e imposta `job["payment"]`; se tale logica e' inline nel ramo gemini, estrarla in un helper `_consume_premium_payment(job, total_eur, payment_token, ...)` e chiamarla da entrambi i rami — refactoring mirato che riduce duplicazione).

> **Refactoring mirato (raccomandato):** il ramo gemini di preflight/consume pagamento e' lungo. Estrarre la parte "dato un prezzo premium, valida e consuma il token (PayPal/voucher), imposta job['payment'], gestisce free-threshold" in un helper condiviso rende il ramo speechify poche righe e previene divergenze. Se l'estrazione risultasse troppo invasiva in questo task, duplicare fedelmente il blocco gemini adattando la sola sorgente del prezzo (`speechify_tts` invece di `gemini_tts`) e loggare un TODO di refactor.

- [ ] **Step 3c: Salvare l'emozione e inoltrarla**

Nel punto in cui si fa lo stash per run_generation (:8106-8112), aggiungere (fuori dal `if _is_gemini_voice` — vale per speechify):

```python
        if is_speechify_voice(voice) and speechify_emotion:
            job["speechify_emotion"] = speechify_emotion
```

Nel wrapper thread (:8223-8228), aggiungere il kwarg:

```python
    thread = threading.Thread(
        target=run_generation, args=(job_id, info, voice, rate, single_file),
        kwargs={'output_format': output_format, 'podcast_base_url': podcast_base_url,
                'gemini_style_instruction': job.get("gemini_style_instruction"),
                'speechify_emotion': job.get("speechify_emotion")},
        daemon=True
    )
```

- [ ] **Step 3d: Propagare nel wrapper `run_generation` di `audiobook_app.py` (:1890)**

```python
def run_generation(job_id, info, voice, rate, single_file, output_format='m4b', podcast_base_url='', gemini_style_instruction=None, speechify_emotion=None):
    return generation_engine.run_generation(job_id, info, voice, rate, single_file,
                                            output_format=output_format,
                                            podcast_base_url=podcast_base_url,
                                            gemini_style_instruction=gemini_style_instruction,
                                            speechify_emotion=speechify_emotion)
```

(adeguare alle righe reali :1890-1894).

- [ ] **Step 3e: Create-order PayPal premium**

Nell'endpoint di creazione ordine premium (`/api/paypal_create_order_gemini` ~:9717), estendere il calcolo importo per riconoscere le voci speechify (usare `speechify_tts.estimate_book_cost`) così che l'`amount` combaci con `/api/combined_estimate`. Se il nome dell'endpoint deve restare gemini-specifico, aggiungere la ramificazione interna sul prefisso voce; il refund premium esistente resta invariato (aggancia il fallimento job).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_endpoints.py -v`
Expected: PASS.
Verifica: `python -m py_compile audiobook_app.py`

- [ ] **Step 5: Commit**

```bash
git add audiobook_app.py test/test_speechify_endpoints.py
git commit -m "feat(speechify): /api/generate emozione + pagamento premium + wrapper"
```

---

## Task 13: `audiobook_app` — `/api/preview_audio` Speechify

**Files:**
- Modify: `audiobook_app.py` (`/api/preview_audio` :7353-7580)
- Test: `test/test_speechify_endpoints.py` (estensione)

**Interfaces:**
- Consumes: `speechify_tts.synthesize` (con `max_attempts=1`), audio utils PCM→MP3.
- Produces: la preview per voci speechify sintetizza un breve campione via l'engine speechify (WAV→PCM→MP3), rispettando emozione/velocita' scelte. Fallback silenzio su errore (come per gli altri engine).

- [ ] **Step 1: Write the failing test (append to `test/test_speechify_endpoints.py`)**

```python
def test_preview_audio_speechify(client, monkeypatch, tmp_path):
    import audiobook_app, speechify_tts

    def _fake_synth(text, voice_id, output_path, emotion=None, rate="+0%", **kw):
        with open(output_path, "wb") as fp:
            fp.write(b"\x00\x00" * 4800)
        return {"success": True, "bytes_written": 9600, "sample_rate": 48000,
                "channels": 1, "billable_chars": len(text), "voice_name": "harper_32"}

    monkeypatch.setattr(speechify_tts, "synthesize", _fake_synth)
    job_id = _register_preview_job(audiobook_app, lang="en")
    r = client.post(f"/api/preview_audio/{job_id}", json={
        "voice": "speechify:simba-3.2:harper_32",
        "rate": "+0%",
        "speechify_emotion": "calm",
    })
    assert r.status_code == 200
    assert r.mimetype in ("audio/mpeg", "audio/mp3")
```

> **Nota:** `_register_preview_job` replica il setup dei test preview esistenti. Skip su assenza FFmpeg se la conversione PCM→MP3 lo richiede.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_endpoints.py::test_preview_audio_speechify -v`
Expected: FAIL (ramo speechify assente in preview).

- [ ] **Step 3: Ramo speechify nella preview**

In `/api/preview_audio` (:7353), dove si sceglie l'engine per il campione (esiste gia' un ramo `_is_gemini_voice` che chiama `gemini_tts.synthesize` in PCM e converte in MP3), aggiungere un ramo speechify **prima** del gemini:

```python
        elif is_speechify_voice(voice):
            emotion = (data.get("speechify_emotion") or "").strip().lower()
            if emotion not in speechify_tts.EMOTIONS:
                emotion = None
            pcm_path = os.path.join(tmp_dir, "preview.pcm")
            try:
                res = speechify_tts.synthesize(
                    sample_text, voice, pcm_path,
                    emotion=emotion, rate=rate, max_attempts=1)
                sr = res.get("sample_rate", 48000)
                # PCM raw -> MP3 con il sample rate REALE letto dal WAV.
                _pcm_to_mp3(pcm_path, out_mp3_path, sample_rate=sr, channels=1)
            except Exception as _e:
                print(f"[preview] speechify failed, silence fallback: {_e}")
                _generate_silence_mp3(out_mp3_path, duration_sec=1)
```

> Adeguare i nomi (`sample_text`, `tmp_dir`, `out_mp3_path`, l'helper PCM→MP3 realmente usato dal ramo gemini — riusare **lo stesso** helper del ramo gemini, passando il sample rate corretto). Se il ramo gemini assume 24000, per speechify passare `sr` reale.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_endpoints.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add audiobook_app.py test/test_speechify_endpoints.py
git commit -m "feat(speechify): anteprima audio Simba-3.2 (PCM->MP3)"
```

---

## Task 14: Frontend — riordino UI premium + opzione modello + default EN

**Files:**
- Modify: `templates/_fragments/html_head.html` (:408-444)
- Modify: `static/js/app.js` (`syncLanguageOptions` :921, `updVoicesPremium` :1052, nuova `updModelsPremium`)
- Test: `test/test_speechify_frontend_assets.py` (asserzioni statiche sugli asset)

**Interfaces:**
- Consumes: catalogo `/api/voices` con voci `speechify:` (Task 10).
- Produces:
  - Ordine DOM tab Premium: **lingua → modello → accento → voce → (stile|emozioni)**.
  - `#vmPremium` ripopolato al cambio lingua: opzione `simba-3.2` ("Simba (English)") presente **solo** con lingua inglese e **preselezionata di default** quando la lingua e' inglese; altrimenti solo modelli Gemini.
  - Nuova combo `#speechifyEmotion` (Nessuna + 13 emozioni) nella posizione di `#geminiStyle`.

- [ ] **Step 1: Write the failing test — create `test/test_speechify_frontend_assets.py`**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_html_has_speechify_emotion_combo():
    html = (ROOT / "templates/_fragments/html_head.html").read_text(encoding="utf-8")
    assert 'id="speechifyEmotion"' in html
    # Accento deve precedere la voce nel markup del tab Premium.
    i_accent = html.find('id="geminiAccentRow"')
    i_voice = html.find('id="vvPremium"')
    assert i_accent != -1 and i_voice != -1
    assert i_accent < i_voice, "accent row must come before the voice select"


def test_appjs_has_model_population():
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "updModelsPremium" in js
    assert "simba-3.2" in js
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_frontend_assets.py -v`
Expected: FAIL (markup/JS non ancora presenti).

- [ ] **Step 3a: Riordinare il markup `#tabPremium`**

In `html_head.html`, riscrivere il blocco `#tabPremium` (:408-444) spostando **`#geminiAccentRow` sopra `#vvPremium`** e aggiungendo la combo emozioni accanto a `#geminiStyle`:

```html
      <div class="tab-panel" id="tabPremium" role="tabpanel" hidden aria-labelledby="tabPremiumBtn">
        <div class="form-row">
          <div class="form-group">
            <label for="vlPremium" data-t="lbl_lang">Lingua</label>
            <select id="vlPremium"></select>
          </div>
          <div class="form-group">
            <label for="vmPremium" data-t="lbl_model">Modello</label>
            <select id="vmPremium"></select>
            <div class="model-rate-hint" id="modelRateHint"></div>
          </div>
        </div>
        <div class="form-row" id="geminiAccentRow" hidden>
          <div class="form-group" style="flex:1 1 100%">
            <label for="geminiAccent" data-t="lbl_accent">Accento di lettura</label>
            <select id="geminiAccent"></select>
            <div class="model-rate-hint" data-t="accent_hint"></div>
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label for="vvPremium" data-t="lbl_voice">Voce</label>
            <select id="vvPremium"></select>
          </div>
        </div>
        <div class="form-row" id="geminiStyleRow">
          <div class="form-group" style="flex:1 1 100%">
            <label for="geminiStyle" data-t="lbl_style_instruction">Istruzioni di stile (opzionale)</label>
            <textarea id="geminiStyle" maxlength="200" rows="2"
                      placeholder="es. tono calmo, ritmo narrativo lento"></textarea>
            <div class="char-counter"><span id="styleCounter">0</span>/200</div>
          </div>
        </div>
        <div class="form-row" id="speechifyEmotionRow" hidden>
          <div class="form-group" style="flex:1 1 100%">
            <label for="speechifyEmotion" data-t="lbl_emotion">Emozione</label>
            <select id="speechifyEmotion"></select>
          </div>
        </div>
      </div>
```

Nota: `#vmPremium` ora e' vuoto nel markup (le `<option>` sono iniettate da JS in `updModelsPremium`).

- [ ] **Step 3b: `updModelsPremium` in app.js**

Aggiungere una funzione che popola `#vmPremium` in base alla lingua premium corrente, e che aggiunge l'opzione Simba solo per l'inglese, preselezionandola:

```javascript
// Popola #vmPremium in base alla lingua premium corrente. Per l'inglese aggiunge
// l'opzione "Simba (English)" (id modello 'simba-3.2') e la preseleziona come
// default; per le altre lingue elenca solo i modelli Gemini.
function updModelsPremium(){
  const vlEl=document.getElementById('vlPremium');
  const vmEl=document.getElementById('vmPremium');
  if(!vmEl)return;
  const lang=(vlEl&&vlEl.value)||'it';
  const prev=vmEl.value;
  vmEl.innerHTML='';
  const addOpt=(val,label)=>{const o=document.createElement('option');o.value=val;o.textContent=label;vmEl.appendChild(o);};
  const isEnglish=(lang==='en');
  // Modelli Gemini (sempre presenti). Le etichette usano i18n se disponibili.
  addOpt('flash25', t('lbl_model_flash25')||'Standard');
  addOpt('flash31', t('lbl_model_flash31')||'Avanzato');
  if(isEnglish){
    // Speechify Simba disponibile solo se il catalogo espone voci speechify per 'en'.
    const en=voices&&voices['en'];
    const arr=en&&Array.isArray(en.voices)?en.voices:[];
    const hasSimba=arr.some(v=>v&&typeof v.id==='string'&&v.id.startsWith('speechify:simba-3.2:'));
    if(hasSimba){
      addOpt('simba-3.2', t('lbl_model_simba')||'Simba (English)');
    }
  }
  // Default: su inglese preferisci Simba (se presente), altrimenti mantieni la
  // scelta precedente se ancora valida, altrimenti il primo modello.
  let target=null;
  if(isEnglish && vmEl.querySelector('option[value="simba-3.2"]')) target='simba-3.2';
  else if(prev && vmEl.querySelector('option[value="'+prev+'"]')) target=prev;
  else target=vmEl.options.length?vmEl.options[0].value:'flash25';
  vmEl.value=target;
  vmEl.onchange=()=>{_onPremiumModelChanged();};
}
```

- [ ] **Step 3c: Agganciare `updModelsPremium` al cambio lingua**

In `syncLanguageOptions` (:921), in coda (dopo la pre-selezione di `dst.value`), invocare `updModelsPremium()` e aggiornare voce+toggle:

```javascript
  if(typeof updModelsPremium==='function')updModelsPremium();
```

E impostare l'handler sul cambio lingua premium (dove viene registrato `vlPremium.onchange`, o aggiungerlo): al cambio di `#vlPremium` chiamare `updModelsPremium()` poi `updVoicesPremium()` poi `_onPremiumModelChanged()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_frontend_assets.py -v`
Expected: PASS.
Verifica manuale (browser): tab Premium con lingua inglese mostra "Simba (English)" preselezionato; l'accento appare sopra la voce.

- [ ] **Step 5: Commit**

```bash
git add templates/_fragments/html_head.html static/js/app.js test/test_speechify_frontend_assets.py
git commit -m "feat(speechify): UI premium riordinata + opzione modello Simba (default EN)"
```

---

## Task 15: Frontend — toggle stile↔emozioni, voci Simba, payload, i18n

**Files:**
- Modify: `static/js/app.js` (`updVoicesPremium` :1052, `getCurrentVoiceId` :1262, payload :2839-2847 e :3235-3243, nuova `_onPremiumModelChanged`)
- Modify: `templates/_fragments/i18n_data.js`, `i18n/en.json`, `i18n/it.json` (+ fr/es/de/zh: chiavi con fallback inglese)
- Test: `test/test_speechify_frontend_assets.py` (estensione)

**Interfaces:**
- Consumes: catalogo `speechify:` voci; `updModelsPremium` (Task 14).
- Produces:
  - `_onPremiumModelChanged()`: se modello = `simba-3.2` → mostra `#speechifyEmotionRow`, nasconde `#geminiStyleRow` e `#geminiAccentRow` con accenti **speechify** (en-US/en-GB); popola `#vvPremium` con le voci speechify filtrate per accento; popola `#speechifyEmotion`. Se modello Gemini → comportamento attuale (stile visibile, emozioni nascoste, accenti gemini).
  - `getCurrentVoiceId()`: ritorna l'id speechify quando il tab Premium ha modello Simba.
  - Payload `/api/generate` e `/api/preview_audio`: aggiunge `speechify_emotion` quando la voce e' speechify.

- [ ] **Step 1: Write the failing test (append to `test/test_speechify_frontend_assets.py`)**

```python
def test_appjs_toggle_and_payload():
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "_onPremiumModelChanged" in js
    assert "speechifyEmotionRow" in js
    assert "speechify_emotion" in js  # payload key


def test_i18n_has_emotion_keys():
    import json
    en = json.loads((ROOT / "i18n/en.json").read_text(encoding="utf-8"))
    assert "lbl_emotion" in en
    assert "lbl_model_simba" in en
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_speechify_frontend_assets.py -v`
Expected: FAIL (funzioni/chiavi assenti).

- [ ] **Step 3a: `_onPremiumModelChanged` + accenti speechify + voci**

Aggiungere in app.js:

```javascript
// Accenti Speechify Simba: locale che filtrano le 8 voci _32 e valorizzano
// il campo language inviato all'API.
const _SPEECHIFY_ACCENTS=[['en-US','American English'],['en-GB','British English']];

function _isSpeechifyModelSelected(){
  const vm=document.getElementById('vmPremium');
  return !!(vm&&vm.value==='simba-3.2');
}

// Mostra/nasconde i controlli in base al modello premium selezionato e
// (ri)popola voci/emozioni/accento coerentemente.
function _onPremiumModelChanged(){
  const styleRow=document.getElementById('geminiStyleRow');
  const emoRow=document.getElementById('speechifyEmotionRow');
  const accentRow=document.getElementById('geminiAccentRow');
  const simba=_isSpeechifyModelSelected();
  if(styleRow)styleRow.hidden=simba;
  if(emoRow)emoRow.hidden=!simba;
  if(simba){
    _populateSpeechifyAccents();
    _populateSpeechifyEmotions();
    if(accentRow)accentRow.hidden=false;   // accento (locale) sempre visibile per Simba
  }else{
    // Gemini: ripristina l'accento gemini gestito da _updateAccentDropdown().
    if(typeof _updateAccentDropdown==='function')_updateAccentDropdown();
  }
  updVoicesPremium();
  if(typeof _onPreviewParamsChanged==='function')_onPreviewParamsChanged();
}

function _populateSpeechifyAccents(){
  const acc=document.getElementById('geminiAccent');
  if(!acc)return;
  const prev=acc.value;
  acc.innerHTML='';
  for(const [code,label] of _SPEECHIFY_ACCENTS){
    const o=document.createElement('option');o.value=code;o.textContent=label;acc.appendChild(o);
  }
  acc.value=(_SPEECHIFY_ACCENTS.some(a=>a[0]===prev))?prev:'en-US';
  acc.onchange=()=>{updVoicesPremium();if(typeof _onPreviewParamsChanged==='function')_onPreviewParamsChanged();};
}

function _populateSpeechifyEmotions(){
  const sel=document.getElementById('speechifyEmotion');
  if(!sel)return;
  const emotions=['angry','cheerful','sad','terrified','relaxed','fearful','surprised','calm','assertive','energetic','warm','direct','bright'];
  const prev=sel.value;
  sel.innerHTML='';
  const none=document.createElement('option');none.value='';none.textContent=t('emotion_none')||'Nessuna (neutro)';sel.appendChild(none);
  for(const e of emotions){
    const o=document.createElement('option');o.value=e;o.textContent=(t('emotion_'+e)||e);sel.appendChild(o);
  }
  sel.value=prev||'';
  sel.onchange=()=>{if(typeof _onPreviewParamsChanged==='function')_onPreviewParamsChanged();};
}
```

- [ ] **Step 3b: `updVoicesPremium` — ramo Speechify**

In cima a `updVoicesPremium` (:1052), gestire il caso Simba costruendo la lista dal catalogo speechify filtrata per accento/locale:

```javascript
function updVoicesPremium(){
  const vlEl=document.getElementById('vlPremium');
  const vmEl=document.getElementById('vmPremium');
  const sel=document.getElementById('vvPremium');
  if(!sel)return;
  // --- Ramo Speechify Simba-3.2 ---
  if(vmEl&&vmEl.value==='simba-3.2'){
    const accEl=document.getElementById('geminiAccent');
    const locale=(accEl&&accEl.value)||'en-US';
    const en=voices&&voices['en'];
    const arr=en&&Array.isArray(en.voices)?en.voices:[];
    const spx=arr.filter(v=>v&&typeof v.id==='string'&&v.id.startsWith('speechify:simba-3.2:')&&v.locale===locale);
    sel.innerHTML='';
    let lg='';
    for(const v of spx){
      if(v.gender!==lg){const g=document.createElement('optgroup');g.label=v.gender==='Female'?'♀':'♂';sel.appendChild(g);lg=v.gender;}
      const o=document.createElement('option');o.value=v.id;
      o.textContent=(v.gender_icon?v.gender_icon+' ':'')+(v.name||v.id.split(':').pop());
      sel.lastElementChild.appendChild(o);
    }
    sel.onchange=()=>{if(typeof _onPreviewParamsChanged==='function')_onPreviewParamsChanged();};
    return;
  }
  // --- Ramo Gemini (esistente) ---
  const lang=(vlEl&&vlEl.value)||'it';
  const modelKey=(vmEl&&vmEl.value)||'flash25';
  // ... (corpo esistente invariato da qui in poi) ...
```

- [ ] **Step 3c: `getCurrentVoiceId` — includere Simba**

In `getCurrentVoiceId` (:1262), quando il tab attivo e' Premium, se `#vmPremium` = `simba-3.2` ritornare `#vvPremium.value` (che e' gia' un id `speechify:...`). Il codice esistente probabilmente ritorna gia' `vvPremium.value` per il tab premium — in tal caso nessuna modifica necessaria oltre a garantire che il valore sia l'id speechify. Verificare e, se il ramo premium costruisce l'id da model+voice, aggiungere:

```javascript
    // Premium tab: se modello Simba, la <option> porta gia' l'id speechify completo.
    if(document.getElementById('vmPremium') && document.getElementById('vmPremium').value==='simba-3.2'){
      return document.getElementById('vvPremium').value;
    }
```

- [ ] **Step 3d: Payload `speechify_emotion`**

Nei due punti che costruiscono il payload (generate :2839-2847, preview :3235-3243), accanto a `gemini_style_instruction`/`gemini_accent`, aggiungere:

```javascript
    // Emozione Speechify (solo quando la voce e' speechify:)
    var _vid=(typeof getCurrentVoiceId==='function')?getCurrentVoiceId():'';
    if(_vid&&_vid.startsWith('speechify:')){
      var _emo=document.getElementById('speechifyEmotion');
      if(_emo&&_emo.value)genPayload.speechify_emotion=_emo.value; // (payload.speechify_emotion nel blocco preview)
    }
```

(usare `genPayload` nel blocco generate e `payload` nel blocco preview, coerentemente con le variabili locali esistenti).

- [ ] **Step 3e: i18n**

Aggiungere le chiavi in `i18n/en.json` e `i18n/it.json` (e replicare in fr/es/de/zh con testo inglese come fallback — regola "testo UI monolingua → inglese"):

`i18n/en.json` (aggiungere):
```json
  "lbl_model_simba": "Simba (English)",
  "lbl_emotion": "Emotion",
  "emotion_none": "None (neutral)",
  "emotion_angry": "Angry",
  "emotion_cheerful": "Cheerful",
  "emotion_sad": "Sad",
  "emotion_terrified": "Terrified",
  "emotion_relaxed": "Relaxed",
  "emotion_fearful": "Fearful",
  "emotion_surprised": "Surprised",
  "emotion_calm": "Calm",
  "emotion_assertive": "Assertive",
  "emotion_energetic": "Energetic",
  "emotion_warm": "Warm",
  "emotion_direct": "Direct",
  "emotion_bright": "Bright"
```

`i18n/it.json` (aggiungere; label emozioni in italiano, "Simba (English)" invariato):
```json
  "lbl_model_simba": "Simba (English)",
  "lbl_emotion": "Emozione",
  "emotion_none": "Nessuna (neutro)",
  "emotion_angry": "Arrabbiato",
  "emotion_cheerful": "Allegro",
  "emotion_sad": "Triste",
  "emotion_terrified": "Terrorizzato",
  "emotion_relaxed": "Rilassato",
  "emotion_fearful": "Timoroso",
  "emotion_surprised": "Sorpreso",
  "emotion_calm": "Calmo",
  "emotion_assertive": "Deciso",
  "emotion_energetic": "Energico",
  "emotion_warm": "Caldo",
  "emotion_direct": "Diretto",
  "emotion_bright": "Brillante"
```

Se `templates/_fragments/i18n_data.js` contiene un dizionario JS parallelo, aggiungere le stesse chiavi lì (almeno `lbl_model_simba`, `lbl_emotion`, `emotion_none` e le 13) per le lingue presenti, con fallback inglese.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_speechify_frontend_assets.py -v`
Expected: PASS.
Verifica manuale (browser): selezionando "Simba (English)" il box stile sparisce e compare la combo Emozione; l'accento (en-US/en-GB) filtra le 4 voci; preview e generate inviano `speechify_emotion`.

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js templates/_fragments/i18n_data.js i18n/en.json i18n/it.json i18n/fr.json i18n/es.json i18n/de.json i18n/zh.json test/test_speechify_frontend_assets.py
git commit -m "feat(speechify): toggle stile/emozioni, voci Simba per accento, payload e i18n"
```

---

## Task 16: `PARAMETRI_CONFIGURAZIONE.md` + suite completa verde

**Files:**
- Modify: `PARAMETRI_CONFIGURAZIONE.md`
- Test: intera suite `test/`

**Interfaces:**
- Nessuna nuova interfaccia. Documentazione + gate finale.

- [ ] **Step 1: Documentare i parametri in `PARAMETRI_CONFIGURAZIONE.md`**

Aggiungere una sezione (con file/riga sorgente come le altre voci del file):

```markdown
### Speechify (Simba-3.2, voci PREMIUM inglese)

| Variabile | Descrizione | Default | Sorgente |
|-----------|-------------|---------|----------|
| `ABM_SPEECHIFY_API_KEY` | API key Speechify (abilita l'engine se presente) | *(vuoto)* | speechify_tts.py `api_key()` |
| `ABM_SPEECHIFY_MAX_CONCURRENCY` | Concorrenza API globale (limite abbonamento) | `3` | speechify_tts.py `max_concurrency()` |
| `ABM_SPEECHIFY_PER_JOB_CONCURRENCY` | Chiamate API simultanee per job | `1` | speechify_tts.py `per_job_concurrency()` |
| `ABM_SPEECHIFY_COST_USD_PER_MCHAR` | Costo USD per 1M caratteri | `11.18` | speechify_tts.py `cost_usd_per_mchar()` |
| `ABM_SPEECHIFY_MARGIN_PERCENT` | Ricarico % (margine netto operatore) | `60` | speechify_tts.py `margin_percent()` |
| `ABM_SPEECHIFY_FREE_THRESHOLD_EUR` | Soglia gratuita | `0.50` | speechify_tts.py `free_threshold_eur()` |

Note:
- USD→EUR e fee PayPal riusano le env Gemini (`ABM_GEMINI_USD_EUR_RATE`, `ABM_GEMINI_PAYPAL_FIXED_FEE_EUR`, `ABM_GEMINI_PAYPAL_PERCENT_FEE`).
- Il modello e' fisso `simba-3.2` (costante interna). Solo lingua inglese, solo engine speech.
- Invariante concorrenza: chiamate simultanee verso l'API ≤ `ABM_SPEECHIFY_MAX_CONCURRENCY` su tutti i job del processo.
```

- [ ] **Step 2: Eseguire l'intera suite**

Run: `python -m pytest test/ -v --tb=short`
Expected: tutti i test speechify PASS; nessuna regressione sui test preesistenti.

- [ ] **Step 3: Verifica sintassi globale dei moduli toccati**

Run:
```bash
python -m py_compile speechify_tts.py voice_utils.py tts_split.py generation_engine.py audiobook_app.py
```
Expected: nessun errore.

- [ ] **Step 4: Smoke import**

Run: `python -c "import speechify_tts, generation_engine, audiobook_app; print('ok')"`
Expected: `ok` (nessun errore di import; l'app non deve richiedere la API key per importare).

- [ ] **Step 5: Commit**

```bash
git add PARAMETRI_CONFIGURAZIONE.md
git commit -m "docs(speechify): parametri ABM_SPEECHIFY_* in PARAMETRI_CONFIGURAZIONE"
```

---

## Self-Review

**1. Spec coverage:**
- §A Architettura → Task 1,2,6,7,8,9 (modulo, voice id, engine, synth, dispatch). ✓
- §B UI (ordine, opzione Simba solo EN + default, accento sopra voce, combo emozioni, payload) → Task 14,15. ✓
- §C Concorrenza (globale N + per-job K + admission gating + reload runtime + invariante) → Task 5 (gate), Task 9 (pool per-job + admission). ✓
- §D Pricing (formula, stima su input chars, riuso pipeline, soglia gratuita) → Task 4,11,12. ✓
- §E Config (6 env + doc) → Task 3,16. ✓
- §F /api/voices, tests, YAGNI → Task 10, tutti i test, vincoli globali. ✓

**2. Placeholder scan:** nessun "TODO/TBD" nel codice di produzione. Le "Note per l'implementatore" nei task 9-13 indicano dove leggere il contratto reale degli endpoint/fixture esistenti (necessario perche' quei punti hanno logica di pagamento/preview lunga non integralmente citabile qui) e non sostituiscono codice mancante: il codice concreto e' fornito, le note ne guidano l'innesto.

**3. Type consistency:**
- `synthesize(...)` → dict con `sample_rate`/`billable_chars`: usato coerentemente in Task 7/9/13.
- `generate_chunk_pcm_speechify(text, voice_id, output_path, emotion, rate, max_retries, failure_info)`: firma identica in Task 7 (def) e Task 9 (call).
- `parse_voice_id` → `(model_key, voice_name, locale)`: coerente Task 2/6.
- gate `acquire_slot/release_slot/slot/free_slots`: coerente Task 5/6/9.
- `estimate_book_cost(chapters, language)` / `compute_user_price_eur(chars)`: coerente Task 4/11/12.

**Punti di attenzione noti (verificare in implementazione, non bloccanti):**
- La forma esatta di `voices[lang]` in `/api/voices` (lista vs `{voices:[...]}`) va confermata leggendo :6027 — i Task 10/15 sono difensivi ma vanno allineati.
- L'estrazione dell'helper `_consume_premium_payment` (Task 12) e' raccomandata ma opzionale; se troppo invasiva, duplicare il blocco gemini.
- L'encode PCM→AAC/MP3 deve usare il sample rate REALE (48000) per speechify, non 24000: verificato nei Task 9/13.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-09-speechify-simba-3.2.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch di un subagent fresco per task, review tra un task e l'altro, iterazione rapida.
2. **Inline Execution** — esecuzione dei task in questa sessione (executing-plans), batch con checkpoint di review.

Which approach?
