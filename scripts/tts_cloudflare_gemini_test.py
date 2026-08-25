#!/usr/bin/env python3
"""tts_cloudflare_gemini_test.py — banco di prova Gemini 3.1 Flash TTS su Cloudflare Workers AI.

Misura costo reale, robustezza (troncamenti/risposte vuote), throughput e
parita' di qualita' rispetto al backend Vertex usato in produzione.

Riusa SOLO helper puri del progetto (gemini_tts, tts_split, audio_utils):
non importa mai audiobook_app ne' generation_engine, non tocca i job ne' i
database JSON.

Spec: docs/superpowers/specs/2026-08-25-cloudflare-gemini-tts-bench-design.md
"""
import io
import os
import sys
import wave

# Il bench vive in scripts/: la root del progetto va in sys.path per importare
# gli helper puri (gemini_tts, tts_split, audio_utils).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
