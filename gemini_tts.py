"""
gemini_tts.py — Gemini 2.5/3.1 Flash TTS integration.

Parallel to google_tts.py for Chirp3-HD. Uses google-genai SDK with separate
API key (or Vertex AI service account). Native output is PCM 24kHz mono 16-bit.

Plan A scope: standalone module — synthesis + pricing + usage tracking + preview cap.
Integration with tts_split / generation_engine / audiobook_app is Plan B.
"""

import os
import re
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

# Chunk piccoli (default 700 char) per stabilita` acustica e prosodia uniforme.
# Lo strumento richiede Gemini Tier 2/3 (RPD elevato), quindi il costo aggiuntivo
# in numero di richieste e` accettabile in cambio di un audio piu` naturale.
# Override globale: ABM_GEMINI_CHUNK_CHARS. Override per-lingua:
# ABM_GEMINI_MAX_CHUNK_CHARS_<LANG_UPPER> (vince sempre).
DEFAULT_CHUNK_CHARS = int(os.environ.get("ABM_GEMINI_CHUNK_CHARS", "700"))

# Target QUALITA` (soft) sui byte UTF-8 del TESTO PURO da sintetizzare
# (esclusi i prefissi style/rate, che sono direttive di prompt e non audio).
# Sopra questa soglia Gemini TTS tende a degradare acusticamente, ma la
# chiamata API non fallisce -- synthesize() logga solo un warning.
MAX_BYTES_PER_CALL = int(os.environ.get("ABM_GEMINI_MAX_BYTES_PER_CALL", "8000"))

# Hard cap API sul PAYLOAD TOTALE (testo + prefissi style + prefix rate).
# E` il limite tecnico oltre il quale Gemini TTS rifiuta la chiamata. Distinto
# da MAX_BYTES_PER_CALL: quest'ultimo e` un target qualita` sul solo testo,
# mentre API_HARD_BYTES_CAP protegge dall'overshoot complessivo della call.
API_HARD_BYTES_CAP = int(os.environ.get("ABM_GEMINI_API_HARD_BYTES_CAP", "8000"))


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
PREVIEW_CAP_PER_DAY = int(_f("ABM_GEMINI_PREVIEW_CAP_PER_DAY", 3))
PREVIEW_WINDOW_SECONDS = int(_f("ABM_GEMINI_PREVIEW_WINDOW_SEC", 300))

# === Rate limiting & retry tuning (Tier 1 friendly) =========================
# Free tier defaults qui sotto sono prudenti; alza i valori se hai billing
# attivo (vedi .env.gemini.tier1.example). I valori vengono letti a ogni call
# (no caching) per supportare reload a runtime durante test.
def _i(env, default):
    try:
        return int(os.environ.get(env, str(default)))
    except (ValueError, TypeError):
        return int(default)


def _b(env, default):
    v = os.environ.get(env)
    if v is None:
        return bool(default)
    return v.strip().lower() in ("1", "true", "yes", "on")


# Max attempts e backoff
SYNTH_MAX_ATTEMPTS_DEFAULT = 3

# Throttle RPM (millisecondi minimi tra due chiamate consecutive per modello).
# 0 = nessun throttle. Free tier: 6500 (flash25, 10 RPM) / 21000 (flash31, 3 RPM).
# Tier 1: 80 (flash25, ~750 RPM) / 200 (flash31, ~300 RPM).
def _min_interval_ms(model_key):
    if model_key == "flash25":
        return _i("ABM_GEMINI_MIN_INTERVAL_FLASH25_MS", 0)
    return _i("ABM_GEMINI_MIN_INTERVAL_FLASH31_MS", 0)


# RPD safety cap per modello (numero massimo di richieste/giorno).
# 0 = nessun cap locale (l'API Google fa da unica barriera).
def _rpd_cap(model_key):
    if model_key == "flash25":
        return _i("ABM_GEMINI_RPD_FLASH25", 0)
    return _i("ABM_GEMINI_RPD_FLASH31", 0)


def _rpd_safety_reserve():
    return _i("ABM_GEMINI_RPD_SAFETY_RESERVE", 0)


# Retry policy
def _synth_max_attempts():
    return _i("ABM_GEMINI_SYNTH_MAX_ATTEMPTS", SYNTH_MAX_ATTEMPTS_DEFAULT)


def _retry_honor_delay():
    return _b("ABM_GEMINI_RETRY_HONOR_DELAY", True)


def _retry_max_wait_sec():
    return _i("ABM_GEMINI_RETRY_MAX_WAIT_SEC", 60)


def _abort_on_daily_quota():
    # Free tier: True (inutile riprovare se retry è ore). Tier 1: False.
    return _b("ABM_GEMINI_ABORT_ON_QUOTA", True)


# === Quality tuning =========================================================
# Lo strumento e` pensato per Gemini Tier 2/3 (RPD elevato): privilegiamo
# stabilita` acustica e prosodia uniforme rispetto al numero di richieste.
# Defaults: temperature 0.75 (riduce deriva metallica sui chunk lunghi),
# gap 250 ms tra chunk consecutivi (respiro naturale al confine). Ogni
# parametro e` override-abile via env dedicata.
def _temperature():
    """Temperature passata al GenerateContentConfig. Default 0.75.
    Override: ABM_GEMINI_TEMPERATURE (float, accetta virgola decimale)."""
    val = os.environ.get("ABM_GEMINI_TEMPERATURE")
    if val is not None and val.strip() != "":
        try:
            return float(val.replace(",", "."))
        except ValueError:
            pass
    return 0.75


def inter_chunk_gap_ms():
    """Silenzio (ms) inserito tra chunk PCM consecutivi in concatenazione.
    Default 250. Override: ABM_GEMINI_INTER_CHUNK_GAP_MS (intero >= 0)."""
    val = os.environ.get("ABM_GEMINI_INTER_CHUNK_GAP_MS")
    if val is not None and val.strip() != "":
        try:
            return max(0, int(val))
        except ValueError:
            pass
    return 250


class GeminiQuotaExhausted(RuntimeError):
    """Sollevata quando l'errore 429 è daily-quota e ABORT_ON_QUOTA è True,
    oppure quando il cap RPD locale è raggiunto. Il chiamante può intercettare
    per sospendere il job invece di silenziare il chunk."""

    def __init__(self, message, retry_after_sec=None, reason="quota"):
        super().__init__(message)
        self.retry_after_sec = retry_after_sec
        self.reason = reason

# Direttive di velocita` in linguaggio naturale (Gemini comprende molto meglio
# linguaggio naturale di tag come [slow]/[fast]). 7 step coprono la corsa del
# slider UI (-30% .. +30% a passi di 10%).
_GEMINI_RATE_DIRECTIVES = {
    -3: "Read this text very slowly, with deliberate, measured pacing and long pauses between sentences.",
    -2: "Read this text slowly, taking your time and articulating clearly.",
    -1: "Read this text at a slightly relaxed, slower than normal pace.",
     0: "",
     1: "Read this text at a slightly brisk pace, a bit faster than normal.",
     2: "Read this text at a quick, energetic pace.",
     3: "Read this text very quickly, with rapid pacing and minimal pauses.",
}

GEMINI_VOICE_NAMES = [
    "Achernar", "Achird", "Algenib", "Algieba", "Alnilam",
    "Aoede", "Autonoe", "Callirrhoe", "Charon", "Despina",
    "Enceladus", "Erinome", "Fenrir", "Gacrux", "Iapetus",
    "Kore", "Laomedeia", "Leda", "Orus", "Pulcherrima",
    "Puck", "Rasalgethi", "Sadachbia", "Sadaltager", "Schedar",
    "Sulafat", "Umbriel", "Vindemiatrix", "Zephyr", "Zubenelgenubi",
]

# Gender ufficiale Google per le voci Gemini TTS (Female / Male).
# Fonte: doc Google AI Studio - elenco voci Gemini 2.5/3.1 Flash TTS.
GEMINI_VOICE_GENDER = {
    "Achernar":     "Female",
    "Achird":       "Male",
    "Algenib":      "Male",
    "Algieba":      "Male",
    "Alnilam":      "Male",
    "Aoede":        "Female",
    "Autonoe":      "Female",
    "Callirrhoe":   "Female",
    "Charon":       "Male",
    "Despina":      "Female",
    "Enceladus":    "Male",
    "Erinome":      "Female",
    "Fenrir":       "Male",
    "Gacrux":       "Female",
    "Iapetus":      "Male",
    "Kore":         "Female",
    "Laomedeia":    "Female",
    "Leda":         "Female",
    "Orus":         "Male",
    "Pulcherrima":  "Female",
    "Puck":         "Male",
    "Rasalgethi":   "Male",
    "Sadachbia":    "Male",
    "Sadaltager":   "Male",
    "Schedar":      "Male",
    "Sulafat":      "Female",
    "Umbriel":      "Male",
    "Vindemiatrix": "Female",
    "Zephyr":       "Female",
    "Zubenelgenubi": "Male",
}


def _gender_icon(gender):
    """Icona unicode per gender (allineata con catalogo Edge)."""
    if gender == "Female":
        return "♀"  # ♀
    if gender == "Male":
        return "♂"  # ♂
    return ""


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
    # Ordina: prima tutte le Female, poi tutte le Male (per coerenza con
    # l'optgroup label="♀|♂" del combo Edge).
    sorted_names = sorted(
        GEMINI_VOICE_NAMES,
        key=lambda n: (0 if GEMINI_VOICE_GENDER.get(n) == "Female" else 1, n),
    )
    for lang in SUPPORTED_UI_LANGUAGES:
        locale = _LANG_LOCALE.get(lang, lang)
        lang_voices = []
        for model_key, model_info in GEMINI_MODELS.items():
            for voice_name in sorted_names:
                gender = GEMINI_VOICE_GENDER.get(voice_name, "")
                lang_voices.append({
                    "id": f"gemini:{model_key}:{voice_name}",
                    "name": f"{voice_name} ({model_info['label']})",
                    "locale": locale,
                    "engine": "gemini",
                    "model_key": model_key,
                    "model_label": model_info["label"],
                    "gender": gender,
                    "gender_icon": _gender_icon(gender),
                })
        out[lang] = lang_voices
    return out


def _normalize_text(text):
    """Collassa whitespace/newline a singolo spazio e fa strip.

    Necessario perche` len(text) viene usato come proxy del numero di caratteri
    "parlati": senza questa normalizzazione, formattazione (newline tra paragrafi,
    indentazione) gonfia il conteggio e disallinea le stime durata/costo dalle
    stime word-count.
    """
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()


def estimate_input_tokens(text, language="it"):
    """Stima token input dal testo. Usa CHARS_PER_TOKEN_BY_LANG."""
    norm = _normalize_text(text)
    if not norm:
        return 0
    ratio = CHARS_PER_TOKEN_BY_LANG.get(language, CHARS_PER_TOKEN_BY_LANG["default"])
    return int(len(norm) / ratio)


def _rate_pct_to_step(rate_pct):
    """Converte percentuale (-30..+30) o stringa ('+10%') a step intero [-3, +3]."""
    if rate_pct is None or rate_pct == "":
        return 0
    if isinstance(rate_pct, str):
        try:
            rate_pct = int(rate_pct.replace("%", "").replace("+", ""))
        except ValueError:
            return 0
    try:
        n = int(rate_pct)
    except (TypeError, ValueError):
        return 0
    return max(-3, min(3, round(n / 10)))


def estimate_audio_seconds(text, language=None, model_key=None, rate_pct=0):
    """Stima durata audio in secondi a una data velocita`.

    Strategia:
      1. Recupera un rate empirico "baseline" (rate_step=0) per (lang, model)
         con fallback a tier-2/3. Questo evita che il rate-step richiesto
         non abbia campioni e produca un risultato invariato rispetto al
         cursore velocità.
      2. Applica un fattore esplicito di velocità ricavato da rate_pct:
            speed_factor = max(0.5, 1 + rate_pct/100)
            audio_seconds = baseline_seconds / speed_factor
         Così la stima è monotonica rispetto allo slider velocità.
    Fallback finale: CHARS_PER_AUDIO_SECOND.
    Il testo viene normalizzato per coerenza con il conteggio dei sample.
    """
    norm = _normalize_text(text)
    if not norm:
        return 0.0
    rate = None
    if language is not None:
        try:
            # rate_step=0 (baseline): la scalatura su rate_pct la applichiamo
            # esplicitamente sotto per garantire monotonia con lo slider.
            rate = get_empirical_rate(language, model_key, rate_step=0)
        except Exception:
            rate = None
    if not rate or rate <= 0:
        rate = CHARS_PER_AUDIO_SECOND
    base_seconds = len(norm) / rate
    # Converti rate_pct ("+10%", 10, "+0%", ecc.) a fattore moltiplicativo.
    try:
        if isinstance(rate_pct, str):
            rp = int(rate_pct.replace("%", "").replace("+", ""))
        else:
            rp = int(rate_pct) if rate_pct is not None else 0
    except (TypeError, ValueError):
        rp = 0
    rp = max(-50, min(50, rp))
    speed_factor = max(0.5, 1.0 + (rp / 100.0))
    return base_seconds / speed_factor


def estimate_output_tokens(text, language=None, model_key=None, rate_pct=0):
    """Stima token audio output. 25 tok/s x secondi stimati alla velocita` data."""
    return int(estimate_audio_seconds(text, language=language, model_key=model_key, rate_pct=rate_pct) * AUDIO_TOKENS_PER_SECOND)


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


def estimate_book_cost(chapters, voice_id, language="it", rate_pct=0):
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

    # Normalizziamo ogni capitolo separatamente per evitare che whitespace/newline
    # gonfino il conteggio caratteri rispetto a word_count*split() usato altrove.
    chars_per_chapter = []
    chars_total = 0
    normalized_parts = []
    for ch in chapters:
        txt = getattr(ch, "text", "") or ""
        norm = _normalize_text(txt)
        chars_per_chapter.append(len(norm))
        chars_total += len(norm)
        normalized_parts.append(norm)

    combined = " ".join(normalized_parts)
    input_tokens = estimate_input_tokens(combined, language)
    audio_seconds = estimate_audio_seconds(combined, language=language, model_key=model_key, rate_pct=rate_pct)
    output_tokens = estimate_output_tokens(combined, language=language, model_key=model_key, rate_pct=rate_pct)

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
        "rate_pct": rate_pct,
        "rate_step": _rate_pct_to_step(rate_pct),
    }


# ===========================================================================
# Budget guard — pre-flight job vs cap di spesa (€/giorno e €/job).
# Pensato per Tier 1: in free tier il guard primario è RPD (vedi _check_rpd_cap).
# ===========================================================================

class GeminiBudgetExceeded(RuntimeError):
    """Sollevata quando un nuovo job supererebbe il budget. Il chiamante deve
    intercettare e restituire un messaggio "riprova al reset di mezzanotte UTC"
    o "supera budget per-job, riduci selezione capitoli"."""

    def __init__(self, message, scope, estimated_eur, cap_eur, used_eur=None):
        super().__init__(message)
        self.scope = scope          # 'per_job' | 'daily'
        self.estimated_eur = estimated_eur
        self.cap_eur = cap_eur
        self.used_eur = used_eur


def _daily_budget_eur():
    return _f("ABM_GEMINI_DAILY_BUDGET_EUR", 0.0)  # 0 = disabilitato


def _per_job_budget_eur():
    return _f("ABM_GEMINI_PER_JOB_BUDGET_EUR", 0.0)  # 0 = disabilitato


def _budget_alert_pct():
    return _i("ABM_GEMINI_BUDGET_ALERT_PCT", 80)


def _budget_hard_stop():
    return _b("ABM_GEMINI_BUDGET_HARD_STOP", True)


def get_daily_spent_eur():
    """Spesa Google del giorno corrente in EUR (UTC). Aggrega l'audit log
    gemini_cost_audit_YYYY-MM.jsonl filtrando per data odierna. Cade su 0
    se il file non esiste / non leggibile (graceful)."""
    if _data_dir is None:
        return 0.0
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month = _current_month()
    audit_file = _data_dir / f"gemini_cost_audit_{month}.jsonl"
    if not audit_file.exists():
        return 0.0
    spent = 0.0
    try:
        with audit_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = rec.get("ts", "")
                if not ts.startswith(today_iso):
                    continue
                spent += float(rec.get("google_cost_eur_actual", 0.0) or 0.0)
    except Exception as e:
        print(f"[gemini-tts] get_daily_spent_eur failed: {e}")
        return 0.0
    return spent


def budget_status():
    """Snapshot del budget (per admin/UI)."""
    daily_cap = _daily_budget_eur()
    spent = get_daily_spent_eur()
    pct = (spent / daily_cap * 100.0) if daily_cap > 0 else 0.0
    return {
        "daily_cap_eur": daily_cap,
        "daily_spent_eur": round(spent, 4),
        "daily_remaining_eur": round(max(0.0, daily_cap - spent), 4) if daily_cap > 0 else None,
        "daily_used_pct": round(pct, 1) if daily_cap > 0 else None,
        "per_job_cap_eur": _per_job_budget_eur(),
        "alert_pct": _budget_alert_pct(),
        "hard_stop": _budget_hard_stop(),
    }


def preflight_budget_check(estimated_cost_eur):
    """Verifica che un job da `estimated_cost_eur` EUR possa partire.

    Solleva GeminiBudgetExceeded(scope='per_job') se sopra il cap singolo,
    GeminiBudgetExceeded(scope='daily') se sommato allo speso di oggi supera
    il cap giornaliero. Se `BUDGET_HARD_STOP` è False, fa solo un log warning
    e NON blocca (utile in dev/admin con cap conservativi per allarmi).
    """
    if estimated_cost_eur is None or estimated_cost_eur < 0:
        return {"ok": True, "warning": None}
    per_job = _per_job_budget_eur()
    daily = _daily_budget_eur()
    spent = get_daily_spent_eur() if daily > 0 else 0.0
    alert_pct = _budget_alert_pct()
    hard = _budget_hard_stop()
    warning = None

    # Per-job
    if per_job > 0 and estimated_cost_eur > per_job:
        msg = (f"Job estimated cost {estimated_cost_eur:.2f} € exceeds "
               f"per-job cap {per_job:.2f} €")
        if hard:
            raise GeminiBudgetExceeded(msg, scope="per_job",
                                       estimated_eur=estimated_cost_eur,
                                       cap_eur=per_job)
        warning = msg

    # Daily
    if daily > 0:
        projected = spent + estimated_cost_eur
        if projected > daily:
            msg = (f"Job would push daily spend to {projected:.2f} € (cap {daily:.2f} €, "
                   f"already spent {spent:.2f} €)")
            if hard:
                raise GeminiBudgetExceeded(msg, scope="daily",
                                           estimated_eur=estimated_cost_eur,
                                           cap_eur=daily, used_eur=spent)
            warning = msg
        elif projected > daily * alert_pct / 100.0:
            warning = (f"[alert] Daily spend will reach "
                       f"{projected:.2f}/{daily:.2f} € ({projected/daily*100:.0f}%)")
            print(f"[gemini-tts] {warning}")

    return {"ok": True, "warning": warning, "spent_eur": spent,
            "estimated_eur": estimated_cost_eur,
            "daily_cap_eur": daily, "per_job_cap_eur": per_job}


def check_text_byte_size(text):
    """Verifica che il testo stia nel target QUALITA` MAX_BYTES_PER_CALL (UTF-8).

    NB: MAX_BYTES_PER_CALL e` un target QUALITA` soft sul TESTO PURO (oltre
    quella soglia Gemini TTS degrada acusticamente), NON un hard cap API.
    L'hard cap API sul payload completo (testo + prefissi) e` API_HARD_BYTES_CAP.
    Chi chiama decide se trattare ok=False come errore o solo come warning.

    Returns:
        (ok: bool, size_bytes: int)
    """
    if not text:
        return True, 0
    size = len(text.encode("utf-8"))
    return size <= MAX_BYTES_PER_CALL, size


def get_max_chunk_chars(language):
    """Max chars per chunk per la lingua data.

    Default: DEFAULT_CHUNK_CHARS (700) — chunk piccoli per stabilita` acustica.
    Override per-lingua ABM_GEMINI_MAX_CHUNK_CHARS_<LANG_UPPER> ha precedenza
    sull'override globale ABM_GEMINI_CHUNK_CHARS.
    """
    if language:
        env_specific = os.environ.get(f"ABM_GEMINI_MAX_CHUNK_CHARS_{language.upper()}")
        if env_specific:
            try:
                return int(env_specific)
            except ValueError:
                pass
    return DEFAULT_CHUNK_CHARS


_data_dir = None
_usage_file_path = None
_usage_lock = threading.Lock()
_usage_cache = None


def init(data_dir):
    """Inizializza il modulo con la directory dati persistente."""
    global _data_dir, _usage_file_path, _usage_cache, _preview_file_path, _preview_cache
    global _rpd_file_path, _rpd_cache
    _data_dir = Path(data_dir)
    _data_dir.mkdir(parents=True, exist_ok=True)
    _usage_file_path = _data_dir / "gemini_tts_usage.json"
    _usage_cache = None
    _preview_file_path = None
    _preview_cache = None
    _rpd_file_path = _data_dir / "gemini_tts_rpd.json"
    _rpd_cache = None


def _current_month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _empty_usage():
    return {
        "month": _current_month(),
        "chars_total": 0,
        "input_tokens_total": 0,
        "output_tokens_total": 0,
        # google_cost_eur: somma costi REALI calcolati da usage_metadata.token_count
        # (input+output) x rate per MTok del modello. Aggregato chunk-per-chunk.
        "google_cost_eur": 0.0,
        "user_revenue_eur_net": 0.0,
        "margin_eur": 0.0,
        "previews_count": 0,
        "previews_cost_eur": 0.0,
        # Reconciliation ex-ante (estimate_book_cost) vs ex-post (usage_metadata
        # reale). Aggiornata a fine job da record_job_completion().
        "jobs_completed": 0,
        "estimated_cost_eur_total": 0.0,
        "actual_cost_eur_total": 0.0,
        "cost_delta_eur_total": 0.0,    # actual - estimated (positivo = sottostima)
        "cost_delta_pct_sum": 0.0,      # somma dei delta% per calcolo media
        "by_model": {
            "flash25": {"chars": 0, "input_tok": 0, "output_tok": 0,
                        "google_cost": 0.0, "revenue_net": 0.0, "jobs_count": 0,
                        "estimated_eur": 0.0, "actual_eur": 0.0},
            "flash31": {"chars": 0, "input_tok": 0, "output_tok": 0,
                        "google_cost": 0.0, "revenue_net": 0.0, "jobs_count": 0,
                        "estimated_eur": 0.0, "actual_eur": 0.0},
        },
    }


def _ensure_reconciliation_fields(data):
    """Migra usage data legacy aggiungendo i campi reconciliation se mancanti.

    Permette di leggere file gemini_tts_usage.json scritti prima dell'introduzione
    della reconciliation senza perdere i totali storici (chars/tokens/cost).
    """
    data.setdefault("jobs_completed", 0)
    data.setdefault("estimated_cost_eur_total", 0.0)
    data.setdefault("actual_cost_eur_total", 0.0)
    data.setdefault("cost_delta_eur_total", 0.0)
    data.setdefault("cost_delta_pct_sum", 0.0)
    by_model = data.get("by_model") or {}
    for mk in ("flash25", "flash31"):
        m = by_model.setdefault(mk, {})
        m.setdefault("chars", 0)
        m.setdefault("input_tok", 0)
        m.setdefault("output_tok", 0)
        m.setdefault("google_cost", 0.0)
        m.setdefault("revenue_net", 0.0)
        m.setdefault("jobs_count", 0)
        m.setdefault("estimated_eur", 0.0)
        m.setdefault("actual_eur", 0.0)
    return data


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
                data = _ensure_reconciliation_fields(data)
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


def record_job_completion(model_key, estimated_eur, actual_eur, user_price_eur=0.0):
    """Registra la chiusura di un job: stima ex-ante vs costo reale ex-post.

    Da chiamare una sola volta a fine job (success o cancel parziale), DOPO che
    tutti i chunk hanno gia` chiamato record_usage(). Tiene traccia dell'errore
    sistematico di estimate_book_cost rispetto ai token reali di usage_metadata.

    Args:
        model_key: 'flash25' | 'flash31'
        estimated_eur: costo Google stimato pre-job (da estimate_book_cost)
        actual_eur: costo Google REALE (somma chunk usage_metadata x rate)
        user_price_eur: prezzo pagato dall'utente (se 0 = job gratuito o ignoto)
    """
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown model_key: {model_key}")
    try:
        est = float(estimated_eur or 0.0)
        act = float(actual_eur or 0.0)
        rev = float(user_price_eur or 0.0)
    except (TypeError, ValueError):
        return
    delta_eur = act - est
    delta_pct = (delta_eur / est * 100.0) if est > 0 else 0.0
    with _usage_lock:
        data = _load_usage()
        data["jobs_completed"] += 1
        data["estimated_cost_eur_total"] += est
        data["actual_cost_eur_total"] += act
        data["cost_delta_eur_total"] += delta_eur
        data["cost_delta_pct_sum"] += delta_pct
        if rev > 0:
            data["user_revenue_eur_net"] += rev
            data["margin_eur"] = data["user_revenue_eur_net"] - data["google_cost_eur"]
        m = data["by_model"][model_key]
        m["estimated_eur"] += est
        m["actual_eur"] += act
        if rev > 0:
            m["revenue_net"] += rev
        _save_usage(data)


def get_usage():
    """Restituisce lo snapshot di utilizzo del mese corrente."""
    with _usage_lock:
        data = dict(_load_usage())
        # Campo derivato: media percentuale errore stima.
        jobs = data.get("jobs_completed", 0) or 0
        data["cost_delta_pct_avg"] = (
            round(data.get("cost_delta_pct_sum", 0.0) / jobs, 2) if jobs > 0 else 0.0
        )
        return data


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


# ───────────────── Empirical rate log (chars/sec per lang+model) ─────────────────
#
# Ad ogni sintesi reale registriamo (chars_normalizzati, audio_secs_reali, lang,
# model). La media mobile sugli ultimi N campioni per (lang, model) diventa il
# rate usato dalle stime. Cosi` le stime ex-ante migliorano automaticamente man
# mano che l'app viene usata e si tarano per ogni lingua.

_rate_log_path = None
_rate_log_lock = threading.Lock()
_rate_log_cache = None

RATE_LOG_MAX_SAMPLES = int(_f("ABM_GEMINI_RATE_LOG_MAX_SAMPLES", 2000))
RATE_LOG_WINDOW = int(_f("ABM_GEMINI_RATE_LOG_WINDOW", 20))
RATE_LOG_MIN_SAMPLES = int(_f("ABM_GEMINI_RATE_LOG_MIN_SAMPLES", 5))


def _rate_log_file():
    global _rate_log_path
    if _rate_log_path is None and _data_dir is not None:
        _rate_log_path = _data_dir / "gemini_tts_rate_log.json"
    return _rate_log_path


def _load_rate_log():
    global _rate_log_cache
    if _rate_log_cache is not None:
        return _rate_log_cache
    p = _rate_log_file()
    if p and p.exists():
        try:
            _rate_log_cache = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(_rate_log_cache, dict) or "samples" not in _rate_log_cache:
                _rate_log_cache = {"samples": []}
            return _rate_log_cache
        except Exception:
            pass
    _rate_log_cache = {"samples": []}
    return _rate_log_cache


def _save_rate_log(data):
    global _rate_log_cache
    _rate_log_cache = data
    p = _rate_log_file()
    if p is None:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:
        print(f"[gemini-tts] Warning: could not save rate log: {e}")


def record_rate_sample(chars, audio_seconds, lang, model_key, rate_pct=0):
    """Registra un campione (chars_normalizzati, audio_seconds, lang, model, rate).

    Scarta campioni degeneri (chars<=0, audio_seconds<=0.5, rate fuori range
    plausibile 5-40 char/sec) per non avvelenare la media empirica con outlier
    derivati da chunk troppo corti o da errori di misurazione.
    """
    try:
        chars = int(chars)
        audio_seconds = float(audio_seconds)
    except (TypeError, ValueError):
        return
    if chars <= 0 or audio_seconds <= 0.5:
        return
    inst_rate = chars / audio_seconds
    if inst_rate < 5.0 or inst_rate > 40.0:
        return
    sample = {
        "chars": chars,
        "secs": round(audio_seconds, 3),
        "lang": (lang or "default")[:8],
        "model": model_key or "unknown",
        "rate_step": _rate_pct_to_step(rate_pct),
        "ts": int(time.time()),
    }
    with _rate_log_lock:
        data = _load_rate_log()
        samples = data.get("samples", [])
        samples.append(sample)
        if len(samples) > RATE_LOG_MAX_SAMPLES:
            samples = samples[-RATE_LOG_MAX_SAMPLES:]
        data["samples"] = samples
        _save_rate_log(data)


def get_empirical_rate(lang, model_key=None, rate_step=0, window=None, min_samples=None):
    """Media mobile char/sec per (lang, model_key, rate_step) con fallback a tier
    progressivamente piu` larghi:

      1. (lang, model, rate_step) — combo esatta
      2. (lang, model)            — qualsiasi velocita`
      3. (lang)                   — qualsiasi modello

    I sample legacy senza rate_step vengono trattati come rate_step=0 (normale).
    Ritorna None se nemmeno il tier piu` largo ha min_samples campioni.
    """
    if not lang:
        return None
    win = window if window is not None else RATE_LOG_WINDOW
    minN = min_samples if min_samples is not None else RATE_LOG_MIN_SAMPLES
    with _rate_log_lock:
        samples = list(_load_rate_log().get("samples", []))
    if not samples:
        return None

    def _avg(filtered):
        last = filtered[-win:] if win > 0 else filtered
        if len(last) < minN:
            return None
        total_chars = sum(s.get("chars", 0) for s in last)
        total_secs = sum(s.get("secs", 0.0) for s in last)
        if total_secs <= 0:
            return None
        return total_chars / total_secs

    def _step(s):
        return s.get("rate_step", 0)

    # Tier 1: lang + model + rate_step
    if model_key:
        tier1 = [s for s in samples if s.get("lang") == lang and s.get("model") == model_key and _step(s) == rate_step]
        rate = _avg(tier1)
        if rate is not None:
            return rate
        # Tier 2: lang + model, qualsiasi velocita`
        tier2 = [s for s in samples if s.get("lang") == lang and s.get("model") == model_key]
        rate = _avg(tier2)
        if rate is not None:
            return rate
    # Tier 3: solo lang
    tier3 = [s for s in samples if s.get("lang") == lang]
    return _avg(tier3)


def get_rate_log_stats():
    """Snapshot diagnostico: numero campioni e rate medio per (lang, model)."""
    with _rate_log_lock:
        samples = list(_load_rate_log().get("samples", []))
    by_key = {}
    for s in samples:
        k = (s.get("lang", "?"), s.get("model", "?"))
        b = by_key.setdefault(k, {"n": 0, "chars": 0, "secs": 0.0})
        b["n"] += 1
        b["chars"] += s.get("chars", 0)
        b["secs"] += s.get("secs", 0.0)
    out = []
    for (lang, model), b in by_key.items():
        rate = (b["chars"] / b["secs"]) if b["secs"] > 0 else 0.0
        out.append({"lang": lang, "model": model, "samples": b["n"], "chars_per_sec": round(rate, 2)})
    out.sort(key=lambda x: (-x["samples"], x["lang"]))
    return {"total_samples": len(samples), "by_key": out}


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


SYNTH_MAX_ATTEMPTS = 3  # kept for backward import compat; runtime uses _synth_max_attempts()


# ---------------------------------------------------------------------------
# Request guard: RPM throttle + RPD daily counter
# ---------------------------------------------------------------------------

_last_call_ts_by_model = {}
_throttle_lock = threading.Lock()

_rpd_file_path = None
_rpd_lock = threading.Lock()
_rpd_cache = None  # {"date": "YYYY-MM-DD", "flash25": N, "flash31": M}


def _today_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _rpd_load():
    """Carica contatore RPD per modello dal file su disco. Rolla a mezzanotte UTC."""
    global _rpd_cache
    if _rpd_cache is not None and _rpd_cache.get("date") == _today_utc_str():
        return _rpd_cache
    if _rpd_file_path is None:
        # Fallback in-memory only
        _rpd_cache = {"date": _today_utc_str(), "flash25": 0, "flash31": 0}
        return _rpd_cache
    if _rpd_file_path.exists():
        try:
            data = json.loads(_rpd_file_path.read_text(encoding="utf-8"))
            if data.get("date") == _today_utc_str():
                data.setdefault("flash25", 0)
                data.setdefault("flash31", 0)
                _rpd_cache = data
                return data
        except Exception as e:
            print(f"[gemini-tts] RPD load failed: {e}")
    _rpd_cache = {"date": _today_utc_str(), "flash25": 0, "flash31": 0}
    return _rpd_cache


def _rpd_save():
    if _rpd_file_path is None or _rpd_cache is None:
        return
    try:
        _rpd_file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = _rpd_file_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_rpd_cache), encoding="utf-8")
        tmp.replace(_rpd_file_path)
    except Exception as e:
        print(f"[gemini-tts] RPD save failed: {e}")


def _rpd_increment(model_key):
    with _rpd_lock:
        data = _rpd_load()
        data[model_key] = data.get(model_key, 0) + 1
        _rpd_save()


def rpd_status():
    """Espone lo stato corrente del contatore RPD (per admin/dashboard)."""
    with _rpd_lock:
        data = _rpd_load()
        return {
            "date": data.get("date"),
            "flash25": {
                "used": data.get("flash25", 0),
                "cap": _rpd_cap("flash25"),
                "reserve": _rpd_safety_reserve(),
            },
            "flash31": {
                "used": data.get("flash31", 0),
                "cap": _rpd_cap("flash31"),
                "reserve": _rpd_safety_reserve(),
            },
        }


def rpd_available(model_key):
    """Numero di richieste residue al model_key prima di esaurire la quota giornaliera.

    Tiene conto del cap configurato meno l'utilizzato e meno la safety reserve.
    Ritorna 0 quando il job non puo' partire; un cap <= 0 (non configurato) ritorna
    un valore "infinito" sentinella (es. 10**9) per non bloccare configurazioni
    senza limite.
    """
    cap = _rpd_cap(model_key)
    if cap <= 0:
        return 10**9
    with _rpd_lock:
        used = _rpd_load().get(model_key, 0)
    reserve = _rpd_safety_reserve()
    return max(0, cap - used - reserve)


def preflight_can_run(model_key, chunks_needed):
    """Verifica preventiva: il job puo' partire senza saturare la quota?

    Ritorna dict:
        {"ok": bool, "available": int, "needed": int, "shortfall": int,
         "cap": int, "used": int, "reserve": int, "retry_after_sec": int}

    retry_after_sec e' calcolato come secondi residui fino a mezzanotte UTC
    (quando il counter rolla). Per cap non configurato (cap<=0) ritorna sempre ok=True.
    """
    cap = _rpd_cap(model_key)
    if cap <= 0:
        return {"ok": True, "available": 10**9, "needed": int(chunks_needed),
                "shortfall": 0, "cap": 0, "used": 0, "reserve": 0,
                "retry_after_sec": 0}
    with _rpd_lock:
        used = _rpd_load().get(model_key, 0)
    reserve = _rpd_safety_reserve()
    available = max(0, cap - used - reserve)
    shortfall = max(0, int(chunks_needed) - available)
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=23, minute=59, second=59).timestamp()
    retry_after = max(60, int(midnight - now.timestamp()))
    return {
        "ok": shortfall == 0,
        "available": available,
        "needed": int(chunks_needed),
        "shortfall": shortfall,
        "cap": cap,
        "used": used,
        "reserve": reserve,
        "retry_after_sec": retry_after,
    }


def _check_rpd_cap(model_key):
    """Solleva GeminiQuotaExhausted se il cap locale è stato raggiunto."""
    cap = _rpd_cap(model_key)
    if cap <= 0:
        return  # nessun cap configurato
    with _rpd_lock:
        used = _rpd_load().get(model_key, 0)
    reserve = _rpd_safety_reserve()
    available = cap - used - reserve
    if available <= 0:
        # retry teorico: a mezzanotte UTC
        now = datetime.now(timezone.utc)
        midnight = now.replace(hour=23, minute=59, second=59).timestamp()
        wait_sec = max(60, int(midnight - now.timestamp()))
        raise GeminiQuotaExhausted(
            f"Local RPD cap reached for {model_key}: used={used} cap={cap} reserve={reserve}",
            retry_after_sec=wait_sec,
            reason="rpd_local_cap",
        )


def _throttle_rpm(model_key):
    """Rispetta l'intervallo minimo tra due call (RPM floor)."""
    min_ms = _min_interval_ms(model_key)
    if min_ms <= 0:
        return
    with _throttle_lock:
        last = _last_call_ts_by_model.get(model_key, 0.0)
        elapsed_ms = (time.time() - last) * 1000.0
        wait_ms = min_ms - elapsed_ms
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)
        _last_call_ts_by_model[model_key] = time.time()


# ---------------------------------------------------------------------------
# 429 / retry parsing
# ---------------------------------------------------------------------------

# Match `retry in 6h12m51.7s`, `retryDelay: '22371s'`, `Please retry in 5.4s`,
# o numeri puri di secondi nei messaggi di errore Google API.
_RE_RETRY_HMS = re.compile(r"retry\s+in\s+(?:(\d+)h)?(?:(\d+)m)?([\d.]+)?s", re.IGNORECASE)
_RE_RETRY_SECS = re.compile(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", re.IGNORECASE)


def _parse_retry_after(err):
    """Estrae retry-after in secondi dall'errore. Restituisce None se non trovato.

    Tentativi (ordinati):
      1. attributo `error.retry_delay` / `error.details[*].retry_delay.seconds`
         (se l'SDK lo espone come oggetto strutturato)
      2. parsing della stringa: 'retryDelay: 22371s'
      3. parsing della stringa: 'retry in 6h12m51.7s' / 'retry in 5s'
    """
    # 1) Structured access via SDK
    try:
        details = getattr(err, "details", None) or []
        for d in details:
            rd = getattr(d, "retry_delay", None) or (d.get("retryDelay") if isinstance(d, dict) else None)
            if rd is not None:
                if isinstance(rd, str) and rd.endswith("s"):
                    return float(rd[:-1])
                secs = getattr(rd, "seconds", None) if not isinstance(rd, dict) else rd.get("seconds")
                if secs is not None:
                    return float(secs)
    except Exception:
        pass

    # 2/3) String parsing
    s = str(err)
    m = _RE_RETRY_SECS.search(s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    m = _RE_RETRY_HMS.search(s)
    if m:
        try:
            h = int(m.group(1) or 0)
            mn = int(m.group(2) or 0)
            sc = float(m.group(3) or 0)
            return h * 3600 + mn * 60 + sc
        except ValueError:
            pass
    return None


def _is_daily_quota_error(err):
    """Heuristica per distinguere quota daily da rate-limit transient."""
    s = str(err).lower()
    return ("per_day" in s) or ("per_model_per_day" in s) or ("perdayper" in s.replace("-", ""))


def _is_429(err):
    s = str(err)
    return ("429" in s) or ("RESOURCE_EXHAUSTED" in s) or ("ResourceExhausted" in s)


class GeminiEmptyResponse(RuntimeError):
    """Sollevata quando la response Gemini non contiene payload audio.
    Causa tipica: safety filter, prompt block, finish_reason!=STOP, o modello
    preview instabile. Il caller puo' decidere se considerarla non-retryable
    (block_reason=SAFETY/PROHIBITED_CONTENT) o transient (OTHER/MAX_TOKENS).
    """

    def __init__(self, message, block_reason=None, finish_reason=None,
                 safety_ratings=None, retryable=True):
        super().__init__(message)
        self.block_reason = block_reason
        self.finish_reason = finish_reason
        self.safety_ratings = safety_ratings
        self.retryable = retryable


def _extract_audio_pcm(response, model_key):
    """Estrae il payload PCM da una response Gemini. Se mancano candidates,
    content, parts, o inline_data, solleva GeminiEmptyResponse con tutti i
    metadati diagnostici (prompt_feedback.block_reason, finish_reason,
    safety_ratings) loggati per chiarire il motivo del rifiuto."""
    # 1) prompt_feedback.block_reason: il prompt e' stato bloccato prima
    #    dell'inferenza (es. safety filter sul testo di input).
    pf = getattr(response, "prompt_feedback", None)
    block_reason = None
    if pf is not None:
        br = getattr(pf, "block_reason", None)
        if br:
            block_reason = getattr(br, "name", str(br))
    # 2) candidates: lista delle risposte; se vuota -> nessun output prodotto.
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        msg = (f"Gemini returned no candidates (model={model_key}, "
               f"block_reason={block_reason or 'unknown'})")
        print(f"[gemini-tts] EMPTY-RESPONSE: {msg}")
        raise GeminiEmptyResponse(
            msg, block_reason=block_reason,
            retryable=(block_reason not in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST")),
        )
    cand = candidates[0]
    finish_reason = getattr(cand, "finish_reason", None)
    finish_label = getattr(finish_reason, "name", str(finish_reason)) if finish_reason else None
    safety_ratings = getattr(cand, "safety_ratings", None)
    content = getattr(cand, "content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    if not parts:
        # Logga safety_ratings in modo leggibile per capire quale categoria
        # ha triggerato il block (HARM_CATEGORY_DANGEROUS_CONTENT, ecc).
        ratings_str = "n/a"
        if safety_ratings:
            try:
                ratings_str = ", ".join(
                    f"{getattr(r.category, 'name', r.category)}={getattr(r.probability, 'name', r.probability)}"
                    for r in safety_ratings
                )
            except Exception:
                ratings_str = str(safety_ratings)[:200]
        msg = (f"Gemini response has no audio parts "
               f"(model={model_key}, finish_reason={finish_label}, "
               f"block_reason={block_reason or 'none'}, safety=[{ratings_str}])")
        print(f"[gemini-tts] EMPTY-RESPONSE: {msg}")
        # Retryable solo se NON e' un block content-based.
        non_retryable_finish = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "RECITATION"}
        retryable = (finish_label not in non_retryable_finish
                     and block_reason not in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"))
        raise GeminiEmptyResponse(
            msg, block_reason=block_reason,
            finish_reason=finish_label,
            safety_ratings=ratings_str,
            retryable=retryable,
        )
    inline = getattr(parts[0], "inline_data", None)
    data = getattr(inline, "data", None) if inline is not None else None
    if not data:
        msg = (f"Gemini response part has no inline_data "
               f"(model={model_key}, finish_reason={finish_label})")
        print(f"[gemini-tts] EMPTY-RESPONSE: {msg}")
        raise GeminiEmptyResponse(
            msg, finish_reason=finish_label, retryable=True,
        )
    return data


def synthesize(text, voice_id, rate="+0%", output_path="output.pcm", style_instruction=None,
               debug_prompt_path=None):
    """Sintetizza testo in PCM raw 24kHz mono 16-bit usando Gemini TTS.

    Args:
        text: testo da sintetizzare. MAX_BYTES_PER_CALL e` un TARGET QUALITA`
            (soft) che si applica SOLO a questo testo (esclusi i prefissi
            style/rate aggiunti internamente): se sforato, warning ma si procede.
        voice_id: 'gemini:<model_key>:<voice_name>'.
        rate: parametro di compatibilita' — Gemini TTS non ha speaking_rate API,
              quando rate != '+0%' viene aggiunta come direttiva in linguaggio
              naturale DENTRO il blocco [style: ...] (es. "Read this text quickly...").
        output_path: percorso file PCM in output.
        style_instruction: opzionale, istruzione di stile/tono (max 300 char dopo
            strip). Viene fusa con l'eventuale rate directive in un singolo
            blocco "[style: <user_style> <rate_directive>] " prefissato al testo.
            Non concorre al target qualita`: e` un prompt, non testo audio.

    Returns:
        dict con success, bytes_written, input_tokens, output_tokens, model_key,
        voice_name, attempts_used.

    Raises:
        ValueError se il payload totale (testo + prefissi) supera API_HARD_BYTES_CAP
            o voice_id e' invalido.
        RuntimeError se tutti i retry falliscono.
    """
    if not is_available():
        raise RuntimeError("Gemini TTS not available (check ABM_GEMINI_API_KEY)")

    model_key, model_id, voice_name = parse_voice_id(voice_id)

    # Check 1: target QUALITA` sul TESTO PURO (escluso prefissi). Se lo splitter
    # ha lavorato correttamente questo non scatta; e` un warning di sicurezza che
    # non blocca la sintesi (l'API regge il payload, e` solo l'acustica a degradare).
    text_ok, text_size = check_text_byte_size(text)
    if not text_ok:
        print(f"[gemini-tts] WARN: testo {text_size}b oltre soglia qualita` "
              f"{MAX_BYTES_PER_CALL}b -- possibile lieve degrado acustico")

    # Kill-switch del rate prompt-directive. Default "prompt" = directive attiva.
    # Qualsiasi altro valore (incluso il legacy "token"/"estimate") disattiva
    # l'iniezione. Nessun altro effetto: non e` usato per cost calc o altro.
    rate_mode = os.environ.get("ABM_GEMINI_RATE_MODE", "prompt")
    # Costruiamo un singolo blocco "[style: ... ]" che combina lo stile utente
    # con la direttiva di velocita`. Il rate non e` esposto dall'API Gemini come
    # parametro audio, quindi va comunicato in linguaggio naturale. Inserirlo
    # DENTRO il blocco style (anziche` come prefisso separato in fila al testo)
    # ha due vantaggi:
    #   1. Semanticamente piu` corretto: "come leggere" = stile, non testo.
    #   2. Aderenza maggiore: Gemini ignora spesso istruzioni in linguaggio
    #      diverso da quello del testo se non sono incapsulate.
    # Lo style utente viene capato a 300 char (qualita` UI); la directive rate
    # e` costante e si appende dopo senza re-cap (max ~110 char system-added).
    style_parts = []
    if style_instruction:
        s = str(style_instruction).strip()[:300]
        if s:
            style_parts.append(s)
    # Iniezione della rate directive nel blocco [style:...]. Silenziosa su
    # successo (per non spammare il log con N chunk * stesso messaggio). Loud
    # solo quando il rate non-default viene scartato: utile per diagnosi rapida
    # ("ho chiesto +30% ma l'audio e` a velocita` normale").
    if rate and rate != "+0%":
        if rate_mode != "prompt":
            print(f"[gemini-tts] WARN: rate={rate!r} richiesto ma "
                  f"ABM_GEMINI_RATE_MODE={rate_mode!r} disattiva la directive. "
                  f"Setta ABM_GEMINI_RATE_MODE=prompt (o unset) per attivarla.")
        else:
            pct = str(rate).replace("%", "").replace("+", "")
            try:
                n = int(pct)
                step = max(-3, min(3, round(n / 10)))
                directive = _GEMINI_RATE_DIRECTIVES.get(step, "")
                if directive:
                    style_parts.append(directive)
                # step 0 = directive vuota = niente da appendere (silenzioso).
            except ValueError as _ve:
                print(f"[gemini-tts] WARN: rate={rate!r} parse failed ({_ve}). "
                      f"Directive non aggiunta.")

    if style_parts:
        final_text = f"[style: {' '.join(style_parts)}] {text}"
    else:
        final_text = text

    # Check 2: hard cap API sul PAYLOAD COMPLETO (testo + prefissi). E` il vero
    # limite tecnico oltre il quale Gemini TTS rifiuta la chiamata.
    payload_size = len(final_text.encode("utf-8"))
    if payload_size > API_HARD_BYTES_CAP:
        raise ValueError(
            f"Payload exceeds API hard cap ({payload_size} > {API_HARD_BYTES_CAP} bytes; "
            f"testo {text_size}b + prefissi {payload_size - text_size}b)"
        )

    # Debug: dump del prompt finale (testo + prefissi style/rate) per ispezione.
    if debug_prompt_path:
        try:
            Path(debug_prompt_path).parent.mkdir(parents=True, exist_ok=True)
            with open(debug_prompt_path, "w", encoding="utf-8") as fp:
                fp.write(final_text)
        except Exception as e:
            print(f"[gemini-tts] could not write debug prompt to {debug_prompt_path}: {e}")

    from google.genai import types as genai_types

    # Guard pre-call: cap RPD locale + throttle RPM. Il cap RPD può sollevare
    # GeminiQuotaExhausted; il throttle invece blocca (sleep) finché c'è budget.
    _check_rpd_cap(model_key)
    _throttle_rpm(model_key)

    client = _get_client()
    last_err = None
    pcm_data = None
    usage_input = 0
    usage_output = 0
    attempt = 0
    max_attempts = _synth_max_attempts()
    honor_delay = _retry_honor_delay()
    max_wait = _retry_max_wait_sec()
    abort_daily = _abort_on_daily_quota()

    while attempt < max_attempts:
        attempt += 1
        try:
            config_kwargs = {
                "response_modalities": ["AUDIO"],
                "speech_config": genai_types.SpeechConfig(
                    voice_config=genai_types.VoiceConfig(
                        prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                            voice_name=voice_name,
                        )
                    )
                ),
            }
            # Temperature: in modalita` Premium (default 0.75) e tunable via env.
            # Una temperature piu` bassa riduce la "deriva metallica" sui chunk
            # lunghi e rende la prosodia piu` stabile job-su-job.
            temp = _temperature()
            if temp is not None:
                config_kwargs["temperature"] = temp
            response = client.models.generate_content(
                model=model_id,
                contents=final_text,
                config=genai_types.GenerateContentConfig(**config_kwargs),
            )
            pcm_data = _extract_audio_pcm(response, model_key)
            um = getattr(response, "usage_metadata", None)
            if um:
                usage_input = getattr(um, "prompt_token_count", 0) or 0
                usage_output = getattr(um, "candidates_token_count", 0) or 0
            # Successo: conta nella quota RPD locale
            _rpd_increment(model_key)
            break
        except Exception as e:
            last_err = e
            is_429 = _is_429(e)
            is_daily = is_429 and _is_daily_quota_error(e)
            retry_after = _parse_retry_after(e) if is_429 else None

            # Response vuota non-retryable (safety/prohibited/recitation):
            # inutile riprovare lo stesso testo, abortire subito.
            if isinstance(e, GeminiEmptyResponse) and not e.retryable:
                print(f"[gemini-tts] Empty response non-retryable: "
                      f"finish_reason={e.finish_reason} block={e.block_reason}. "
                      f"Aborting attempts.")
                raise

            # Daily quota: inutile riprovare se il delay è ore.
            if is_daily and abort_daily:
                print(f"[gemini-tts] Daily quota exhausted ({model_key}). "
                      f"retry_after={retry_after}s. Aborting (ABM_GEMINI_ABORT_ON_QUOTA=true).")
                raise GeminiQuotaExhausted(
                    f"Gemini daily quota exhausted: {e}",
                    retry_after_sec=retry_after,
                    reason="api_daily_quota",
                )

            # Decidi la wait: rispetta retry_after se presente e ragionevole,
            # altrimenti fallback a backoff esponenziale (2/4/8/16 s).
            if honor_delay and retry_after is not None:
                if retry_after > max_wait:
                    print(f"[gemini-tts] 429 retry_after={retry_after}s > max_wait={max_wait}s. "
                          f"Suspending instead of sleeping ({model_key}).")
                    raise GeminiQuotaExhausted(
                        f"Gemini 429 with long retry: {e}",
                        retry_after_sec=retry_after,
                        reason="retry_too_long",
                    )
                wait = max(1.0, retry_after)
            else:
                wait = min(30.0, 2 ** attempt)

            if attempt < max_attempts:
                print(f"[gemini-tts] Attempt {attempt}/{max_attempts} failed "
                      f"({'429' if is_429 else 'other'}). Sleeping {wait:.1f}s. Err: {str(e)[:200]}")
                time.sleep(wait)
            else:
                raise RuntimeError(f"Gemini TTS failed after {max_attempts} attempts: {last_err}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(pcm_data)

    audio_seconds_real = len(pcm_data) / float(AUDIO_SAMPLE_RATE * AUDIO_SAMPLE_WIDTH_BYTES * AUDIO_CHANNELS)
    return {
        "success": True,
        "bytes_written": len(pcm_data),
        "audio_seconds_real": audio_seconds_real,
        "input_tokens": usage_input,
        "output_tokens": usage_output,
        "model_key": model_key,
        "voice_name": voice_name,
        "attempts_used": attempt,
    }
