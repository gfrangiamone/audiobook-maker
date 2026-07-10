"""Speechify Simba-3.2 TTS — engine PREMIUM inglese.

Modello unico `simba-3.2` (flagship English-only). Speculare a gemini_tts.py:
config via env `ABM_SPEECHIFY_*`, catalogo voci/emozioni, pricing riusando la
pipeline premium, gate di concorrenza globale (limite abbonamento).

Anti-import-circolare: nessun import di audiobook_app. Le costanti condivise
(USD->EUR, fee PayPal) sono lette dalle STESSE env var di Gemini per coerenza.
"""

import base64
import contextlib as _contextlib
import io
import os
import threading
import time
import wave

# === Gate di concorrenza globale (limite abbonamento) =======================
# Un permesso per chiamata API. Ogni synthesize acquisisce/rilascia uno slot;
# l'invariante `active <= max_concurrency()` vale su tutti i job/client del
# processo. max_concurrency() e' riletto a ogni acquire (reload runtime).

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
SPEECH_ENDPOINT = "/v1/audio/speech"   # non-streaming: JSON con audio_data base64
STREAM_ENDPOINT = "/v1/audio/stream"   # streaming: corpo audio grezzo (no JSON)

# Limite hard dell'endpoint: l'`input` SSML (testo + tag) non puo' superare
# 2000 char, altrimenti HTTP 400 validation_failed.
ENDPOINT_MAX_INPUT_CHARS = 2000
# Riserva per l'overhead dei tag SSML aggiunti da build_ssml nel caso peggiore
# (<speak> + <prosody rate="..."> + <speechify:style emotion="...">, ~102 char)
# piu' margine. Il testo del chunk non deve mai eccedere ENDPOINT - riserva.
_SSML_OVERHEAD_RESERVE = 150
# Cap massimo di sicurezza sul testo: garantisce input SSML < 2000 anche con i
# tag peggiori. E' anche il tetto a cui viene clampato l'override via env.
SAFE_MAX_CHUNK_CHARS = ENDPOINT_MAX_INPUT_CHARS - _SSML_OVERHEAD_RESERVE  # 1850
# Default del cap testo/chunk (override via ABM_SPEECHIFY_CHUNK_CHARS).
CHUNK_MAX_CHARS = 1800  # cap sotto il limite ~2000 char/richiesta dell'endpoint
_CHUNK_MIN_CHARS = 200  # floor: sotto questo il TTS perde contesto/qualita'


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


def _b(env, default=False):
    """Parsing booleano da env: 1/true/yes/on (case-insensitive) -> True."""
    raw = os.environ.get(env)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in ("1", "true", "yes", "on")


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


def use_stream_api():
    """True se usare l'endpoint di streaming (STREAM_ENDPOINT) invece del
    non-streaming (SPEECH_ENDPOINT). Override via ABM_SPEECHIFY_USE_STREAM.

    Default False (endpoint /v1/audio/speech, comportamento storico). Con lo
    streaming il corpo della risposta e' audio grezzo (nessun wrapper JSON /
    base64): synthesize richiede comunque audio_format=wav e ne estrae il PCM.
    """
    return _b("ABM_SPEECHIFY_USE_STREAM", False)


def chunk_max_chars():
    """Cap caratteri/chunk sul testo (override via ABM_SPEECHIFY_CHUNK_CHARS).

    Clampato a [_CHUNK_MIN_CHARS, SAFE_MAX_CHUNK_CHARS]: il tetto garantisce che
    l'`input` SSML (testo + tag di build_ssml) resti sotto il limite hard di
    ENDPOINT_MAX_INPUT_CHARS (2000) dell'endpoint, evitando l'HTTP 400 che
    silenzierebbe il chunk. Valori non validi ricadono sul default
    CHUNK_MAX_CHARS.
    """
    val = _i("ABM_SPEECHIFY_CHUNK_CHARS", CHUNK_MAX_CHARS)
    return max(_CHUNK_MIN_CHARS, min(SAFE_MAX_CHUNK_CHARS, val))


# Costanti condivise con Gemini (stesse env per non divergere sui prezzi).
def usd_eur_rate():
    return _f("ABM_GEMINI_USD_EUR_RATE", 0.86)


def paypal_fixed_fee_eur():
    return _f("ABM_GEMINI_PAYPAL_FIXED_FEE_EUR", 0.34)


def paypal_percent_fee():
    return _f("ABM_GEMINI_PAYPAL_PERCENT_FEE", 3.4)


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


def _is_retryable(status_code):
    """Determina se uno status HTTP e' retriabile: 429 o qualunque 5xx."""
    return status_code == 429 or 500 <= status_code <= 599


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
    use_stream = use_stream_api()
    url = API_BASE + (STREAM_ENDPOINT if use_stream else SPEECH_ENDPOINT)

    last_error = None
    for attempt in range(max_attempts):
        with slot():  # gate globale: un permesso per l'intera chiamata
            resp = session.post(url, json=payload, headers=headers,
                                timeout=120, stream=use_stream)
            # In streaming il corpo si scarica solo all'accesso: consumalo DENTRO
            # lo slot cosi' la call occupa il permesso per header + download audio
            # (invariante di concorrenza).
            raw_body = resp.content if (use_stream and resp.status_code == 200) else None
        if resp.status_code == 200:
            if use_stream:
                # Streaming: il corpo E' l'audio WAV grezzo (audio_format=wav),
                # nessun wrapper JSON/base64. billable_characters_count non e'
                # disponibile qui: fallback a len(text) (serve solo al reconcile;
                # il costo e' gia' riservato sui caratteri di input).
                wav_bytes = raw_body or b""
                billable_chars = len(text)
            else:
                data = resp.json()
                wav_b64 = data.get("audio_data") or ""
                wav_bytes = base64.b64decode(wav_b64)
                # Billable chars parsing: fallback robusto a len(text) su missing/null/non-numeric
                billable_chars = len(text)
                try:
                    val = data.get("billable_characters_count")
                    if val is not None:
                        billable_chars = int(val)
                except (ValueError, TypeError):
                    pass  # fallback a len(text)
            pcm, rate_hz, channels = _wav_bytes_to_pcm(wav_bytes)
            with open(output_path, "wb") as fp:
                fp.write(pcm)
            return {
                "success": True,
                "bytes_written": len(pcm),
                "sample_rate": rate_hz,
                "channels": channels,
                "billable_chars": billable_chars,
                "voice_name": voice_name,
            }
        if not _is_retryable(resp.status_code):
            raise RuntimeError(f"Speechify HTTP {resp.status_code} (fatal): {getattr(resp, 'text', '')[:200]}")
        last_error = f"HTTP {resp.status_code}"
        if attempt < max_attempts - 1:
            time.sleep(_retry_after_seconds(resp, attempt))

    raise RuntimeError(f"Speechify synthesis failed after {max_attempts} attempts: {last_error}")


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
