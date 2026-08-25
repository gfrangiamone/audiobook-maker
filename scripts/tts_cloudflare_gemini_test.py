#!/usr/bin/env python3
"""tts_cloudflare_gemini_test.py — banco di prova Gemini 3.1 Flash TTS su Cloudflare Workers AI.

Misura costo reale, robustezza (troncamenti/risposte vuote), throughput e
parita' di qualita' rispetto al backend Vertex usato in produzione.

Riusa SOLO helper puri del progetto (gemini_tts, tts_split, audio_utils):
non importa mai audiobook_app ne' generation_engine, non tocca i job ne' i
database JSON.

Spec: docs/superpowers/specs/2026-08-25-cloudflare-gemini-tts-bench-design.md
"""
import base64
import binascii
import io
import os
import sys
import time
import wave

import requests

# Il bench vive in scripts/: la root del progetto va in sys.path per importare
# gli helper puri (gemini_tts, tts_split, audio_utils).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gemini_tts

# --- Costanti del banco di prova -------------------------------------------
CF_MODEL = "google/gemini-3.1-flash-tts"
CF_API_BASE = "https://api.cloudflare.com/client/v4/accounts"

# Tariffe Cloudflare per il modello (USD per milione di token).
CF_INPUT_USD_PER_MTOK = 0.75
CF_OUTPUT_USD_PER_MTOK = 12.00
USD_EUR_RATE = 0.86

# Token audio output per secondo. Sull'audit di produzione vale costantemente 25.
AUDIO_TOKENS_PER_SECOND = 25.0

# Formato PCM atteso da Gemini TTS: 24 kHz mono 16 bit.
EXPECTED_RATE = 24000
EXPECTED_CHANNELS = 1
EXPECTED_WIDTH = 2

# Banda del gate di durata (reale/attesa). Volutamente piu' larga della banda
# empirica di prod (0.75-1.35): qui serve a intercettare troncamenti
# grossolani, non a calibrare un preventivo.
RATIO_LOW = 0.6
RATIO_HIGH = 1.6

DEFAULT_CHUNK_CHARS = 450
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_SPEND_EUR = 2.00
HTTP_TIMEOUT_SEC = 60


class WavFormatError(Exception):
    """Il payload audio non e' un WAV leggibile o e' vuoto."""


def resolve_credentials():
    """Ritorna (account_id, api_token) dalle env. Esce con errore se mancano.

    Il valore del token non compare mai nel messaggio d'errore.
    """
    account_id = (os.environ.get("CF_ACCOUNT_ID") or "").strip()
    token = (os.environ.get("CF_API_TOKEN") or "").strip()
    missing = [n for n, v in (("CF_ACCOUNT_ID", account_id),
                              ("CF_API_TOKEN", token)) if not v]
    if missing:
        raise SystemExit(
            "Credenziali Cloudflare mancanti: " + ", ".join(missing) +
            ". Impostale nell'ambiente (vedi scripts/cf_tts_bench.env.ps1.example)."
        )
    return account_id, token


def wav_bytes_to_pcm(wav_bytes, out_path):
    """Scrive in `out_path` il PCM grezzo estratto dal WAV e ne ritorna il formato.

    Returns:
        {"rate": int, "channels": int, "width": int, "bytes": int}
    Raises:
        WavFormatError: payload non decodificabile o senza frame.
    """
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            rate = wf.getframerate()
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())
    except Exception as exc:
        raise WavFormatError(f"payload audio non decodificabile: {exc}") from exc
    if not frames:
        raise WavFormatError("WAV senza frame audio")
    with open(out_path, "wb") as fh:
        fh.write(frames)
    return {"rate": rate, "channels": channels, "width": width,
            "bytes": len(frames)}


class SpendCapExceeded(Exception):
    """Il cap di spesa del run e' stato raggiunto."""


def estimate_tokens(chars, audio_seconds, language):
    """Token input/output stimati per una chiamata.

    L'output usa i secondi audio REALI quando disponibili (dai byte PCM), non
    una previsione: l'unica approssimazione residua e' il rapporto
    token/secondo, che Cloudflare non espone in risposta.
    """
    return {
        "tokens_in": int(gemini_tts.estimate_input_tokens("x" * int(chars), language)),
        "tokens_out": int(round(float(audio_seconds) * AUDIO_TOKENS_PER_SECOND)),
    }


def cost_usd(tokens_in, tokens_out):
    """Costo USD di una chiamata alle tariffe Cloudflare."""
    return (tokens_in * CF_INPUT_USD_PER_MTOK / 1e6
            + tokens_out * CF_OUTPUT_USD_PER_MTOK / 1e6)


def predict_call_usd(chars, language):
    """Costo previsto PRIMA della chiamata, dal baseline char/sec della lingua."""
    seconds = float(chars) / gemini_tts.baseline_rate(language)
    tok = estimate_tokens(chars, seconds, language)
    return cost_usd(tok["tokens_in"], tok["tokens_out"])


class SpendGuard:
    """Accumulatore di spesa con tetto in euro. `max_eur=0` disattiva il tetto."""

    def __init__(self, max_eur=DEFAULT_MAX_SPEND_EUR):
        self.max_eur = float(max_eur or 0)
        self.spent_usd = 0.0

    def spent_eur(self):
        return self.spent_usd * USD_EUR_RATE

    def check(self, projected_usd):
        """Solleva SpendCapExceeded se aggiungere `projected_usd` sfonda il cap."""
        if self.max_eur <= 0:
            return
        proiettato = (self.spent_usd + float(projected_usd)) * USD_EUR_RATE
        if proiettato > self.max_eur:
            raise SpendCapExceeded(
                f"cap di spesa raggiunto: {proiettato:.4f} EUR previsti "
                f"contro un tetto di {self.max_eur:.2f} EUR"
            )

    def add(self, usd):
        self.spent_usd += float(usd)


def evaluate_duration(chars, language, audio_seconds):
    """Confronta la durata reale dell'audio con quella attesa per il testo.

    Sostituisce il finish_reason che l'API Cloudflare non restituisce: senza
    questo controllo un chunk troncato e' indistinguibile da uno completo.
    """
    seconds = float(audio_seconds or 0.0)
    expected = float(chars or 0) / gemini_tts.baseline_rate(language)
    if seconds <= 0.0 or expected <= 0.0:
        return {"expected_seconds": expected, "ratio": 0.0, "anomaly": "empty"}
    ratio = seconds / expected
    anomaly = None
    if ratio < RATIO_LOW:
        anomaly = "truncated"
    elif ratio > RATIO_HIGH:
        anomaly = "overlong"
    return {"expected_seconds": expected, "ratio": ratio, "anomaly": anomaly}


def evaluate_format(fmt):
    """Ritorna "format" se il PCM decodificato non e' 24 kHz mono 16 bit."""
    if (fmt.get("rate") != EXPECTED_RATE
            or fmt.get("channels") != EXPECTED_CHANNELS
            or fmt.get("width") != EXPECTED_WIDTH):
        return "format"
    return None


class CFAuthError(Exception):
    """Credenziali rifiutate da Cloudflare (401/403): nessun retry ha senso."""


class CFCallError(Exception):
    """Chiamata fallita dopo tutti i tentativi."""

    def __init__(self, message, status=None, attempts=0):
        super().__init__(message)
        self.status = status
        self.attempts = attempts


def build_payload(text, voice, temperature):
    """Corpo della richiesta /ai/run per il modello TTS."""
    return {
        "model": CF_MODEL,
        "input": {
            "text": text,
            "voice": voice,
            "temperature": float(temperature),
        },
    }


def _retry_after_seconds(resp, attempt):
    """Attesa prima del prossimo tentativo: header se presente, altrimenti 2^n."""
    raw = (resp.headers or {}).get("retry-after") if resp is not None else None
    if raw:
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
    return float(2 ** attempt)


def call_cf(session, account_id, api_token, text, voice, temperature,
            max_attempts=4, timeout=HTTP_TIMEOUT_SEC, sleep=time.sleep):
    """Una sintesi su Cloudflare, con retry su 429/5xx e su timeout di rete.

    Returns:
        {"wav": bytes, "latency_ms": float, "status": int, "attempts": int,
         "retry_statuses": [int, ...]}
    Raises:
        CFAuthError: 401/403.
        CFCallError: tentativi esauriti o risposta 200 senza audio.
    """
    url = f"{CF_API_BASE}/{account_id}/ai/run"
    headers = {"Authorization": f"Bearer {api_token}",
               "Content-Type": "application/json"}
    payload = build_payload(text, voice, temperature)
    retry_statuses = []
    last_status = None
    for attempt in range(1, int(max_attempts) + 1):
        t0 = time.time()
        try:
            resp = session.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            latency_ms = (time.time() - t0) * 1000.0
            last_status = None
            retry_statuses.append(0)
            if attempt >= max_attempts:
                raise CFCallError(f"errore di rete dopo {attempt} tentativi: {exc}",
                                  status=None, attempts=attempt) from exc
            sleep(float(2 ** attempt))
            continue
        latency_ms = (time.time() - t0) * 1000.0
        last_status = resp.status_code
        if resp.status_code in (401, 403):
            # Il token non entra mai nel messaggio.
            raise CFAuthError(
                f"Cloudflare ha rifiutato le credenziali (HTTP {resp.status_code}): "
                f"verifica CF_ACCOUNT_ID e CF_API_TOKEN."
            )
        if resp.status_code == 429 or resp.status_code >= 500:
            retry_statuses.append(resp.status_code)
            if attempt >= max_attempts:
                raise CFCallError(
                    f"HTTP {resp.status_code} dopo {attempt} tentativi",
                    status=resp.status_code, attempts=attempt)
            sleep(_retry_after_seconds(resp, attempt))
            continue
        if resp.status_code != 200:
            raise CFCallError(f"HTTP {resp.status_code} non gestibile con retry",
                              status=resp.status_code, attempts=attempt)
        try:
            body = resp.json()
        except Exception as exc:
            raise CFCallError(f"risposta non JSON: {exc}",
                              status=resp.status_code, attempts=attempt) from exc
        audio_b64 = ((body.get("result") or {}).get("audio")
                     if isinstance(body, dict) else None)
        if not audio_b64:
            raise CFCallError("risposta 200 senza campo audio",
                              status=resp.status_code, attempts=attempt)
        try:
            wav_bytes = base64.b64decode(audio_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise CFCallError("campo audio non decodificabile da base64",
                              status=resp.status_code, attempts=attempt) from exc
        return {
            "wav": wav_bytes,
            "latency_ms": latency_ms,
            "status": resp.status_code,
            "attempts": attempt,
            "retry_statuses": retry_statuses,
        }
    raise CFCallError("tentativi esauriti", status=last_status,
                      attempts=int(max_attempts))
