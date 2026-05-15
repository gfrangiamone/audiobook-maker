"""
gemini_tts.py — Gemini 2.5/3.1 Flash TTS integration.

Parallel to google_tts.py for Chirp3-HD. Uses google-genai SDK with separate
API key (or Vertex AI service account). Native output is PCM 24kHz mono 16-bit.

Plan A scope: standalone module — synthesis + pricing + usage tracking + preview cap.
Integration with tts_split / generation_engine / audiobook_app is Plan B.
"""

import os
import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

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
        "id": "gemini-3.1-flash-tts-preview",
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
PREVIEW_CAP_PER_DAY = int(_f("ABM_GEMINI_PREVIEW_CAP_PER_DAY", 10))
PREVIEW_WINDOW_SECONDS = int(_f("ABM_GEMINI_PREVIEW_WINDOW_SEC", 300))

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


SUPPORTED_UI_LANGUAGES = ["it", "en", "fr", "es", "de", "zh", "hi"]
_LANG_LOCALE = {
    "it": "it-IT", "en": "en-US", "fr": "fr-FR", "es": "es-ES",
    "de": "de-DE", "zh": "zh-CN", "hi": "hi-IN",
}


def get_voices():
    """Catalogo voci Gemini per lingua.

    Le voci Gemini sono multilingue: ogni voce appare sotto ogni lingua UI
    supportata. 30 voci x 2 modelli = 60 entry per lingua.

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
    """Stima token audio output. 25 tok/s x secondi stimati."""
    return int(estimate_audio_seconds(text) * AUDIO_TOKENS_PER_SECOND)


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


def compute_user_price_eur(google_cost_eur, model_key):
    """Calcola prezzo finale all'utente da costo Google netto.

    Formula:
        base   = google_cost x (1 + margin/100)
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


_data_dir = None
_usage_file_path = None
_usage_lock = threading.Lock()
_usage_cache = None


def init(data_dir):
    """Inizializza il modulo con la directory dati persistente."""
    global _data_dir, _usage_file_path, _usage_cache, _preview_file_path, _preview_cache
    _data_dir = Path(data_dir)
    _data_dir.mkdir(parents=True, exist_ok=True)
    _usage_file_path = _data_dir / "gemini_tts_usage.json"
    _usage_cache = None
    _preview_file_path = None
    _preview_cache = None


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
        return dict(_load_usage())


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
    """Resetta il counter se il primo timestamp ha superato la finestra rolling."""
    window_start = entry.get("window_start_ts", 0)
    if now - window_start >= PREVIEW_WINDOW_SECONDS:
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
        reset_ts = entry["window_start_ts"] + PREVIEW_WINDOW_SECONDS
        return count, remaining, int(reset_ts)


def increment_preview(cookie_id):
    """Incrementa il counter se sotto cap. Restituisce True se ok, False se cap raggiunto."""
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


_available = None
_available_lock = threading.Lock()
_genai_client = None


def is_available():
    """True se ABM_GEMINI_API_KEY (o credenziali Vertex) sono configurate e google-genai e' installato."""
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
                print("[gemini-tts] Disabled: ABM_GEMINI_USE_VERTEX=true but credentials file not found")
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


SYNTH_MAX_ATTEMPTS = 3


def synthesize(text, voice_id, rate="+0%", output_path="output.pcm", style_instruction=None):
    """Sintetizza testo in PCM raw 24kHz mono 16-bit usando Gemini TTS.

    Args:
        text: testo da sintetizzare (<= MAX_BYTES_PER_CALL UTF-8 bytes).
        voice_id: 'gemini:<model_key>:<voice_name>'.
        rate: parametro di compatibilita' — Gemini TTS non ha speaking_rate API,
              quando rate != '+0%' viene aggiunto un prompt instruction.
        output_path: percorso file PCM in output.
        style_instruction: opzionale, istruzione di stile/tono (max 300 char dopo
            strip) che viene prefissata al testo come "[style: <stripped>] ".

    Returns:
        dict con success, bytes_written, input_tokens, output_tokens, model_key,
        voice_name, attempts_used.

    Raises:
        ValueError se text (dopo i prefissi) supera il cap byte o voice_id e' invalido.
        RuntimeError se tutti i retry falliscono.
    """
    if not is_available():
        raise RuntimeError("Gemini TTS not available (check ABM_GEMINI_API_KEY)")

    model_key, model_id, voice_name = parse_voice_id(voice_id)

    rate_mode = os.environ.get("ABM_GEMINI_RATE_MODE", "prompt")
    final_text = text
    # Style prefix (cap stripped style at 300 chars to avoid blowing the byte budget)
    if style_instruction:
        style = str(style_instruction).strip()[:300]
        if style:
            final_text = f"[style: {style}] {final_text}"
    # Existing rate prefix
    if rate_mode == "prompt" and rate and rate != "+0%":
        pct = rate.replace("%", "").replace("+", "")
        try:
            n = int(pct)
            if n < -5:
                final_text = f"[slow] {final_text}"
            elif n > 5:
                final_text = f"[fast] {final_text}"
        except ValueError:
            pass

    # Byte-size cap AFTER prefixes
    ok, size = check_text_byte_size(final_text)
    if not ok:
        raise ValueError(f"Text exceeds MAX_BYTES_PER_CALL ({size} > {MAX_BYTES_PER_CALL} bytes)")

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
