#!/usr/bin/env python3
"""
Audiobook Maker  -  Web app to convert EPUB/PDF into MP3 audiobooks.

Requirements:
    pip install flask edge-tts ebooklib beautifulsoup4 lxml Pillow pymupdf

Usage:
    python audiobook_app.py
    Then open http://localhost:5601
"""

import asyncio
import concurrent.futures
import re
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
import hmac
from datetime import datetime
from copy import copy
from pathlib import Path

from flask import (
    Flask, render_template_string, request, jsonify,
    send_file, Response, stream_with_context
)

#  -  -  Import epub_to_tts (must be in the same folder)  -  - 
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from epub_to_tts import parse_epub, write_single_file, write_chapter_files, BookInfo
except ImportError:
    print("ERROR: epub_to_tts.py not found in the same folder.", file=sys.stderr)
    print(f"  Script folder: {SCRIPT_DIR}", file=sys.stderr)
    sys.exit(1)

try:
    from pdf_to_tts import parse_pdf
except ImportError:
    parse_pdf = None
    print("WARNING: pdf_to_tts.py not found  -  PDF support disabled.", file=sys.stderr)

try:
    import edge_tts
except ImportError:
    print("ERROR: edge-tts not installed. Run: pip install edge-tts", file=sys.stderr)
    sys.exit(1)

#  -  -  Google Cloud TTS (Chirp3-HD)  -  opzionale  -  -
try:
    import google_tts
except ImportError:
    google_tts = None
    print("WARNING: google_tts.py not found  -  Google Cloud TTS disabled.", file=sys.stderr)

from audio_utils import (
    _zip_safe_read, _extract_cover_from_epub, _generate_fallback_cover,
    _extract_cover_for_preview, _include_cover_in_dir, _generate_podcast_rss,
    _generate_silence_mp3, _concatenate_mp3, _get_audio_duration_ms,
    _convert_mp3_to_m4b, _prepare_m4b_cover_path, _safe_filename,
    _check_audio_dependencies,
)
from tts_split import (
    CHUNK_MAX_CHARS, split_text_into_chunks, _is_multilingual_voice,
    _TTS_MIN_SENT_CHARS, _TTS_MAX_SENT_CHARS, _split_sentences_for_tts,
    _edge_tts_call, generate_chunk_mp3, generate_chunk_mp3_google,
    _strip_parenthetical, _ensure_heading_pause, _plan_chunks,
)

import email_service
import payment

# Carica traduzioni pagine di download da file JSON esterno
_DL_PAGES_I18N = {}
try:
    with open(SCRIPT_DIR / "i18n" / "download_pages.json", encoding="utf-8") as _f:
        _DL_PAGES_I18N = json.load(_f)
except Exception as _e:
    print(f"WARNING: Could not load i18n/download_pages.json: {_e}", file=sys.stderr)

#  -  -  DeepSeek LLM per ottimizzazione testo TTS  -  opzionale  -  -
DEEPSEEK_API_KEY = os.environ.get("ABM_DEEPSEEK_API_KEY", "")
DEEPSEEK_API_BASE = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_MAX_TOKENS = 8192
DEEPSEEK_TEMPERATURE = 0.3
DEEPSEEK_CHARS_PER_TOKEN = 3.5
DEEPSEEK_MAX_CONTEXT_TOKENS = 128000
DEEPSEEK_RESERVED_OUTPUT_TOKENS = 8192
DEEPSEEK_RESERVED_PROMPT_TOKENS = 4000
DEEPSEEK_MAX_INPUT_TOKENS = DEEPSEEK_MAX_CONTEXT_TOKENS - DEEPSEEK_RESERVED_OUTPUT_TOKENS - DEEPSEEK_RESERVED_PROMPT_TOKENS
DEEPSEEK_MAX_INPUT_CHARS = int(DEEPSEEK_MAX_INPUT_TOKENS * DEEPSEEK_CHARS_PER_TOKEN)

_deepseek_client = None
_deepseek_prompt = ""

def _init_deepseek():
    """Initialize DeepSeek client and load TTS optimization prompt."""
    global _deepseek_client, _deepseek_prompt
    if not DEEPSEEK_API_KEY:
        print("[startup] DeepSeek LLM optimization disabled (ABM_DEEPSEEK_API_KEY not set)")
        return
    try:
        from openai import OpenAI
        _deepseek_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_API_BASE)
        prompt_path = SCRIPT_DIR / "prompt_tts_optimization.md"
        if prompt_path.exists():
            _deepseek_prompt = prompt_path.read_text(encoding="utf-8").strip()
            print(f"[startup] DeepSeek LLM optimization enabled (prompt: {len(_deepseek_prompt)} chars)")
        else:
            print(f"WARNING: prompt_tts_optimization.md not found  -  LLM optimization disabled.", file=sys.stderr)
            _deepseek_client = None
    except ImportError:
        print("WARNING: openai library not installed  -  LLM optimization disabled. Run: pip install openai", file=sys.stderr)
        _deepseek_client = None

def _llm_available():
    """True se l'ottimizzazione LLM è disponibile."""
    return _deepseek_client is not None and bool(_deepseek_prompt)


#  -  -  PayPal payment config per LLM optimization  -  - 
PAYPAL_CLIENT_ID = os.environ.get("ABM_PAYPAL_CLIENT_ID", "").strip()
PAYPAL_SECRET = os.environ.get("ABM_PAYPAL_SECRET", "").strip()
PAYPAL_MODE = os.environ.get("ABM_PAYPAL_MODE", "sandbox").strip().lower()  # sandbox|live
PAYPAL_API_BASE = "https://api-m.sandbox.paypal.com" if PAYPAL_MODE == "sandbox" else "https://api-m.paypal.com"
LLM_RATE_EUR_PER_MCHAR = float(os.environ.get("ABM_LLM_RATE_EUR_PER_MCHAR", "1.10"))
LLM_FREE_THRESHOLD_EUR = float(os.environ.get("ABM_LLM_FREE_THRESHOLD_EUR", "0.50"))
VOUCHER_EXPIRY_DAYS = int(os.environ.get("ABM_VOUCHER_EXPIRY_DAYS", "180"))
VOUCHER_BONUS_PERCENT = int(os.environ.get("ABM_VOUCHER_BONUS_PERCENT", "10"))
PAYMENT_RETENTION_DAYS = int(os.environ.get("ABM_PAYMENT_RETENTION_DAYS", "730"))  # 24 mesi GDPR

_paypal_token_cache = {"access_token": None, "expires_at": 0}

def _paypal_available():
    """True se PayPal è configurato."""
    return bool(PAYPAL_CLIENT_ID and PAYPAL_SECRET)


def _estimate_llm_cost_eur(char_count):
    """Stima il costo in EUR per ottimizzare N caratteri."""
    return round((char_count / 1_000_000.0) * LLM_RATE_EUR_PER_MCHAR, 2)


#  -  -  Import version and template builder  -  - 
from version import __version__
from templates.index_page import build_html_template

#  -  -  Import favicon data (embedded, served via Flask routes for SEO)  -  - 
from favicon_data import (
    get_favicon_ico, get_favicon_png_192,
    get_apple_touch_icon, get_favicon_svg,
)



# ----------------------------------------------------------------------
# APP CONFIG
# ----------------------------------------------------------------------

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB

@app.after_request
def add_security_headers(response):
    """Aggiunge header di sicurezza alle risposte HTTP."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # Content Security Policy (base)
    # Permettiamo script inline per la nostra app (SPA-like) ma blocchiamo fonti esterne non autorizzate.
    # Nota: per una configurazione più rigida, bisognerebbe usare i nonce.
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://www.paypal.com https://www.googletagmanager.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://api.producthunt.com; "
        "connect-src 'self' https://api-m.sandbox.paypal.com https://api-m.paypal.com https://www.google-analytics.com; "
        "frame-src https://www.paypal.com;"
    )
    return response

# Directory di lavoro persistente (sopravvive ai restart del servizio)
# Configurabile via ABM_DATA_DIR, default: /var/lib/audiobook-maker/data
_DATA_DIR = os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data")
UPLOAD_DIR = Path(_DATA_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Inizializza Google Cloud TTS (tracking utilizzo nella data dir)
if google_tts is not None:
    google_tts.init(_DATA_DIR)

jobs = {}


def _has_active_google_tts_jobs():
    """True se c'è almeno un job Google TTS in corso (caratteri prenotati ma
    non ancora visibili al Cloud Monitoring). Usato per decidere se è sicuro
    riconciliare al ribasso il contatore locale.
    """
    if google_tts is None:
        return False
    try:
        for j in jobs.values():
            if j.get("status") in ("queued", "running", "generating"):
                if j.get("google_tts_reserved", 0) > 0:
                    return True
                voice = j.get("voice", "")
                if voice and google_tts.is_google_voice(voice):
                    return True
    except Exception:
        return True  # safe default
    return False


if google_tts is not None and hasattr(google_tts, "set_active_jobs_callback"):
    google_tts.set_active_jobs_callback(_has_active_google_tts_jobs)

from email_service import (
    _smtp_available, _send_email, _admin_notify_generation,
    _try_send_admin_digest, _send_payment_receipt_email, _send_voucher_email,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, ADMIN_EMAIL,
    BASE_URL, ADMIN_DIGEST_INTERVAL_SEC
)

EMAIL_FILE_RETENTION_SEC = 24 * 60 * 60  # 24 ore di retention dopo invio email

#  -  -  Admin activity digest (email log)  -  - 
# Set ABM_ADMIN_EMAIL to enable. Leave empty to disable.
#   export ABM_ADMIN_EMAIL=gfrangiamone@gmail.com
# Rate limited: max 1 digest email per hour, batches all pending events.
# Token admin per UI web /admin/vouchers. Se vuoto, l'endpoint è disabilitato.
ADMIN_TOKEN = os.environ.get("ABM_ADMIN_TOKEN", "").strip()

#  -  -  Client tracking & rate limiting  -  - 
# Max concurrent generating jobs per client device (cookie-based).
# Set via ABM_MAX_CONCURRENT_PER_CLIENT env var; default 2.
MAX_CONCURRENT_PER_CLIENT = int(os.environ.get("ABM_MAX_CONCURRENT_PER_CLIENT", "2"))

# Max concurrent LLM optimization jobs per client device.
# Set via ABM_MAX_CONCURRENT_LLM_PER_CLIENT env var; default 1.
MAX_CONCURRENT_LLM_PER_CLIENT = int(os.environ.get("ABM_MAX_CONCURRENT_LLM_PER_CLIENT", "1"))

# Cookie name and max-age for client identification
_CLIENT_COOKIE_NAME = "abm_cid"
_CLIENT_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # 1 year


def _get_client_id():
    """Return the client_id from cookie, or generate a new one (will be set later)."""
    return request.cookies.get(_CLIENT_COOKIE_NAME, "")


def _get_client_ip():
    """Return client IP address, respecting reverse proxy headers."""
    # X-Forwarded-For: client, proxy1, proxy2  →  take the first
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def _get_browser_lang():
    """Return primary browser language from Accept-Language header (e.g. 'it', 'en', 'fr')."""
    accept = request.headers.get("Accept-Language", "")
    if not accept:
        return ""
    # Parse first language tag: "it-IT,it;q=0.9,en;q=0.8"  →  "it"
    first = accept.split(",")[0].split(";")[0].strip()
    # Return just the primary subtag (e.g. "it-IT"  →  "it")
    return first.split("-")[0].lower() if first else ""


def _active_generating_for_client(client_id):
    """Count how many jobs are currently generating for the given client_id."""
    if not client_id:
        return 0
    return sum(
        1 for j in jobs.values()
        if j.get("client_id") == client_id and j.get("status") == "generating"
    )


def _active_optimizing_for_client(client_id):
    """Count how many LLM optimization jobs are running for the given client_id."""
    if not client_id:
        return 0
    return sum(
        1 for j in jobs.values()
        if j.get("client_id") == client_id and j.get("status") == "optimizing"
    )


FAVICON_B64 = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCI+CiAgPGRlZnM+CiAgICA8bGluZWFyR3JhZGllbnQgaWQ9ImJnIiB4MT0iMCUiIHkxPSIwJSIgeDI9IjEwMCUiIHkyPSIxMDAlIj4KICAgICAgPHN0b3Agb2Zmc2V0PSIwJSIgc3R5bGU9InN0b3AtY29sb3I6I2MyOWE2YyIvPgogICAgICA8c3RvcCBvZmZzZXQ9IjEwMCUiIHN0eWxlPSJzdG9wLWNvbG9yOiNhMDc4NTAiLz4KICAgIDwvbGluZWFyR3JhZGllbnQ+CiAgPC9kZWZzPgogIDxyZWN0IHdpZHRoPSI2NCIgaGVpZ2h0PSI2NCIgcng9IjE0IiBmaWxsPSJ1cmwoI2JnKSIvPgogIDxwYXRoIGQ9Ik0xNiA0NFYyMGMwLTIgMS41LTMuNSAzLjUtMy41QzIzIDE2LjUgMjggMTcgMzIgMTljNC0yIDktMi41IDEyLjUtMi41IDIgMCAzLjUgMS41IDMuNSAzLjV2MjQiIGZpbGw9Im5vbmUiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMi41IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz4KICA8cGF0aCBkPSJNMzIgMTl2MjUiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+CiAgPHBhdGggZD0iTTE3IDM2YzAtOSA2LjctMTUgMTUtMTVzMTUgNiAxNSAxNSIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJ3aGl0ZSIgc3Ryb2tlLXdpZHRoPSIyLjgiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgogIDxyZWN0IHg9IjEzIiB5PSIzNCIgd2lkdGg9IjciIGhlaWdodD0iMTAiIHJ4PSIzIiBmaWxsPSJ3aGl0ZSIvPgogIDxyZWN0IHg9IjQ0IiB5PSIzNCIgd2lkdGg9IjciIGhlaWdodD0iMTAiIHJ4PSIzIiBmaWxsPSJ3aGl0ZSIvPgogIDxwYXRoIGQ9Ik0yMiAzNy41YzEuMi0xIDEuMi0zIDAtNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjYzI5YTZjIiBzdHJva2Utd2lkdGg9IjEuMyIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+CiAgPHBhdGggZD0iTTQyIDM3LjVjLTEuMi0xLTEuMi0zIDAtNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjYzI5YTZjIiBzdHJva2Utd2lkdGg9IjEuMyIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+Cjwvc3ZnPg=="

_download_tokens = {}  # token -> {job_id, created_at, download_type, base_url, ...}
_TOKENS_FILE = UPLOAD_DIR / "_download_tokens.json"
_tokens_lock = threading.Lock()


def _save_tokens():
    """Persist download tokens to disk (survives restart)."""
    try:
        with _tokens_lock:
            # Save only serializable data
            data = {}
            for tok, info in _download_tokens.items():
                data[tok] = {
                    "job_id": info["job_id"],
                    "created_at": info["created_at"],
                    "download_type": info.get("download_type", "audio"),
                    "base_url": info.get("base_url", ""),
                    # Snapshot of job data needed for download after restart
                    "book_title": info.get("book_title", ""),
                    "output_zip": info.get("output_zip", ""),
                    "output_name": info.get("output_name", ""),
                    "output_file": info.get("output_file", ""),
                    "epub_path": info.get("epub_path", ""),
                    "podcast_safe_name": info.get("podcast_safe_name", ""),
                    "podcast_ready": info.get("podcast_ready", False),
                    "podcast_mp3s": info.get("podcast_mp3s", []),
                    "podcast_info_title": info.get("podcast_info_title", ""),
                    "podcast_info_author": info.get("podcast_info_author", ""),
                    "podcast_info_language": info.get("podcast_info_language", ""),
                    "original_filename": info.get("original_filename", ""),
                    "lang": info.get("lang", "en"),
                }
            with open(_TOKENS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[tokens] Failed to save tokens: {e}")


def _load_tokens():
    """Reload download tokens from disk on startup."""
    global _download_tokens
    if not _TOKENS_FILE.exists():
        return
    try:
        with open(_TOKENS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        now = time.time()
        loaded = 0
        expired = 0
        for tok, info in data.items():
            # Skip expired tokens
            if (now - info.get("created_at", 0)) > EMAIL_FILE_RETENTION_SEC + 300:
                expired += 1
                continue
            # Verify that job files still exist
            job_dir = UPLOAD_DIR / info.get("job_id", "")
            if not job_dir.exists():
                expired += 1
                continue
            _download_tokens[tok] = info
            loaded += 1
        if loaded or expired:
            print(f"[tokens] Loaded {loaded} tokens from disk ({expired} expired/invalid)")
    except Exception as e:
        print(f"[tokens] Failed to load tokens: {e}")


# ----------------------------------------------------------------------
# PAYMENTS & VOUCHERS (for LLM optimization)
# ----------------------------------------------------------------------

_payments = {}   # order_id -> {amount_eur, email, job_id, captured_at, used, used_at?}
_vouchers = {}   # code -> {email, amount_eur, created_at, expires_at, used, used_at?, origin_order_id}
_PAYMENTS_FILE = UPLOAD_DIR / "_payments.json"
_VOUCHERS_FILE = UPLOAD_DIR / "_vouchers.json"
_PAID_OPT_DONE_FILE = UPLOAD_DIR / "_paid_opt_done.json"
_payments_lock = threading.Lock()
_vouchers_lock = threading.Lock()

#  -  Rate limit voucher_validate (Point 1)  - 
# IP -> list[timestamps] (sliding window). Limiti: 5/min, 30/ora.
# Email -> (fail_count, lockout_until) dopo N fallimenti consecutivi.
_voucher_attempts_ip = {}
_voucher_attempts_email = {}
_voucher_rl_lock = threading.Lock()
VOUCHER_RL_PER_MIN = 5
VOUCHER_RL_PER_HOUR = 30
VOUCHER_EMAIL_FAIL_LIMIT = 10    # fallimenti consecutivi prima del lockout
VOUCHER_EMAIL_LOCKOUT_SEC = 900  # 15 minuti


def _voucher_rl_check(ip, email):
    """Return (allowed, retry_after_sec, reason)."""
    now = time.time()
    with _voucher_rl_lock:
        #  -  IP sliding window  - 
        hits = _voucher_attempts_ip.get(ip, [])
        hits = [t for t in hits if now - t < 3600]
        last_min = [t for t in hits if now - t < 60]
        if len(last_min) >= VOUCHER_RL_PER_MIN:
            retry = 60 - int(now - last_min[0])
            _voucher_attempts_ip[ip] = hits
            return False, max(1, retry), "rate_limit_ip_minute"
        if len(hits) >= VOUCHER_RL_PER_HOUR:
            retry = 3600 - int(now - hits[0])
            _voucher_attempts_ip[ip] = hits
            return False, max(1, retry), "rate_limit_ip_hour"
        #  -  Email lockout  - 
        em = (email or "").lower().strip()
        if em:
            info = _voucher_attempts_email.get(em)
            if info and info.get("lockout_until", 0) > now:
                return False, int(info["lockout_until"] - now), "email_locked"
        # Record hit for IP  -  caller can trigger email-fail separately
        hits.append(now)
        _voucher_attempts_ip[ip] = hits
    return True, 0, None


def _voucher_rl_record_result(email, success):
    """Aggiorna contatore fallimenti per email; reset on success."""
    em = (email or "").lower().strip()
    if not em:
        return
    now = time.time()
    with _voucher_rl_lock:
        if success:
            _voucher_attempts_email.pop(em, None)
            return
        info = _voucher_attempts_email.get(em) or {"fail_count": 0, "lockout_until": 0}
        info["fail_count"] = info.get("fail_count", 0) + 1
        if info["fail_count"] >= VOUCHER_EMAIL_FAIL_LIMIT:
            info["lockout_until"] = now + VOUCHER_EMAIL_LOCKOUT_SEC
            info["fail_count"] = 0  # reset contatore dopo lockout
        _voucher_attempts_email[em] = info



def _save_payments():
    try:
        with _payments_lock:
            with open(_PAYMENTS_FILE, "w", encoding="utf-8") as f:
                json.dump(_payments, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[payments] Failed to save: {e}")


def _load_payments():
    global _payments
    if not _PAYMENTS_FILE.exists():
        return
    try:
        with open(_PAYMENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Retention: drop payments older than PAYMENT_RETENTION_DAYS
        now = time.time()
        cutoff = now - PAYMENT_RETENTION_DAYS * 86400
        _payments = {k: v for k, v in data.items() if v.get("captured_at", 0) > cutoff}
        if len(data) != len(_payments):
            _save_payments()
        print(f"[payments] Loaded {len(_payments)} payment records")
    except Exception as e:
        print(f"[payments] Failed to load: {e}")


def _save_vouchers():
    try:
        with _vouchers_lock:
            with open(_VOUCHERS_FILE, "w", encoding="utf-8") as f:
                json.dump(_vouchers, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[vouchers] Failed to save: {e}")


def _load_vouchers():
    global _vouchers
    if not _VOUCHERS_FILE.exists():
        return
    try:
        with open(_VOUCHERS_FILE, "r", encoding="utf-8") as f:
            _vouchers = json.load(f)
        print(f"[vouchers] Loaded {len(_vouchers)} voucher records")
    except Exception as e:
        print(f"[vouchers] Failed to load: {e}")


def _generate_voucher_code():
    """Generate a 12-char uppercase alphanumeric voucher code (no ambiguous chars)."""
    import secrets
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
    while True:
        code = "-".join("".join(secrets.choice(chars) for _ in range(4)) for _ in range(3))
        if code not in _vouchers:
            return code


def _create_voucher(email, amount_eur, origin_order_id=None, origin_job_id=None,
                    kind="refund", note="", created_by="auto_refund",
                    expiry_days=None, apply_bonus=True, code=None):
    """Create a voucher.

    kind: "refund" (auto-emesso dopo fallimento pagato), "promo" (generato da admin),
          "gift" (regalo admin). Solo "refund" applica il bonus % predefinito.
    note: testo libero amministrativo (motivo/causale).
    created_by: "auto_refund" per l'emissione automatica, "admin" per CLI.
    expiry_days: None  →  usa VOUCHER_EXPIRY_DAYS (refund). Gli admin possono passare un valore custom.
    apply_bonus: se False salva l'importo nominale (usato per promo/gift).
    code: se fornito, usa quel codice invece di generarne uno (utile per PROMO- prefix).
    """
    if code is None:
        code = _generate_voucher_code()
    now = time.time()
    if apply_bonus:
        bonus_amount = round(amount_eur * (1 + VOUCHER_BONUS_PERCENT / 100.0), 2)
    else:
        bonus_amount = round(float(amount_eur), 2)
    days = VOUCHER_EXPIRY_DAYS if expiry_days is None else int(expiry_days)
    _vouchers[code] = {
        "code": code,
        "email": (email or "").lower().strip(),
        "amount_eur": bonus_amount,
        "base_amount_eur": amount_eur,
        "remaining_eur": bonus_amount,   # Saldo residuo (decresce ad ogni uso)
        "uses": [],                       # list[{"job_id","amount_eur","at","remaining_after"}]
        "created_at": now,
        "expires_at": now + days * 86400,
        "used": False,                    # True solo quando saldo ≤ 0.01
        "used_at": None,
        "origin_order_id": origin_order_id,
        "origin_job_id": origin_job_id,
        #  -  Nuovi campi (Point 4)  - 
        "kind": kind,                # "refund" | "promo" | "gift"
        "note": (note or "")[:500],
        "created_by": created_by,    # "auto_refund" | "admin"
    }
    _save_vouchers()
    return code, bonus_amount


def _voucher_remaining(v: dict) -> float:
    """Saldo residuo del voucher. Gestisce record legacy privi di ``remaining_eur``:
    se esiste il flag ``used`` binario  →  0 residuo; altrimenti l'importo originale.
    """
    if "remaining_eur" in v:
        try:
            return max(0.0, round(float(v["remaining_eur"]), 2))
        except (TypeError, ValueError):
            return 0.0
    # Legacy: nessun remaining_eur memorizzato
    if v.get("used"):
        return 0.0
    try:
        return round(float(v.get("amount_eur", 0) or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _voucher_consume(code: str, amount: float, job_id: str = "") -> float:
    """Scala ``amount`` EUR dal saldo del voucher ``code``. Ritorna il nuovo saldo
    residuo. Se il saldo scende sotto 0.01 EUR il voucher viene marcato ``used=True``.
    Solleva ``ValueError`` se il voucher non è spendibile o il saldo è insufficiente.
    """
    v = _vouchers.get(code)
    if not v:
        raise ValueError("voucher not found")
    if v.get("expires_at", 0) <= time.time():
        raise ValueError("voucher expired")
    remaining = _voucher_remaining(v)
    # Arrotondamenti: se la differenza è ≤ 0.01 permettiamo lo spend (evita errori di 1 cent)
    if amount > remaining + 0.01:
        raise ValueError(f"insufficient balance: need {amount:.2f}, have {remaining:.2f}")
    spent = round(min(amount, remaining), 2)
    new_remaining = round(remaining - spent, 2)
    now = time.time()
    v["remaining_eur"] = new_remaining
    uses = v.get("uses")
    if not isinstance(uses, list):
        uses = []
    uses.append({
        "job_id": job_id,
        "amount_eur": spent,
        "at": now,
        "remaining_after": new_remaining,
    })
    v["uses"] = uses
    # Mark fully used solo quando il saldo è praticamente zero
    if new_remaining < 0.01:
        v["used"] = True
        v["used_at"] = now
    else:
        v["used"] = False
    _save_vouchers()
    return new_remaining


def _voucher_refund(code: str, amount: float, job_id: str = "", reason: str = "") -> float:
    """Ri-accredita ``amount`` EUR sul voucher ``code`` (operazione inversa a consume).
    Ritorna il nuovo saldo residuo. Se il voucher era marcato used, lo riattiva.
    Solleva ``ValueError`` se il voucher non esiste.
    """
    v = _vouchers.get(code)
    if not v:
        raise ValueError("voucher not found")
    remaining = _voucher_remaining(v)
    original = float(v.get("amount_eur", 0) or 0)
    new_remaining = round(min(remaining + amount, original), 2)
    now = time.time()
    v["remaining_eur"] = new_remaining
    uses = v.get("uses")
    if not isinstance(uses, list):
        uses = []
    uses.append({
        "job_id": job_id,
        "amount_eur": -round(amount, 2),  # negativo = refund
        "at": now,
        "remaining_after": new_remaining,
        "reason": reason,
    })
    v["uses"] = uses
    # Riattiva il voucher se aveva saldo e non è scaduto
    if new_remaining >= 0.01:
        v["used"] = False
        if "used_at" in v:
            del v["used_at"]
    _save_vouchers()
    print(f"[vouchers] Refund {amount:.2f} EUR  →  {code} (new balance {new_remaining:.2f} EUR) reason={reason}")
    return new_remaining


#  -  -  Tracking job pagati completati con successo (persistenza su disco)  -  - 
# Set di job_id per cui l'ottimizzazione a pagamento è terminata con successo.
# Serve al recovery all'avvio per distinguere job completati da job interrotti.
_paid_opt_done: set = set()

def _save_paid_opt_done():
    try:
        with open(_PAID_OPT_DONE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(_paid_opt_done), f)
    except Exception as e:
        print(f"[paid_opt_done] Failed to save: {e}")

def _load_paid_opt_done():
    global _paid_opt_done
    if not _PAID_OPT_DONE_FILE.exists():
        return
    try:
        with open(_PAID_OPT_DONE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _paid_opt_done = set(data) if isinstance(data, list) else set()
        print(f"[startup] Loaded {len(_paid_opt_done)} paid optimization completion record(s)")
    except Exception as e:
        print(f"[paid_opt_done] Failed to load: {e}")

def _mark_paid_opt_done(job_id: str):
    """Segna un job come completato con successo (persistente su disco)."""
    _paid_opt_done.add(job_id)
    _save_paid_opt_done()

def _cleanup_paid_opt_done():
    """Rimuovi record più vecchi di 4 ore (non servono più al recovery)."""
    # Chiamata dal cleanup loop; qui rimuoviamo solo i job_id che non sono
    # più nei voucher uses recenti (semplice: teniamo solo quelli < 4h).
    # Nota: non abbiamo timestamp nel set, quindi puliamo solo se il set è troppo grande.
    if len(_paid_opt_done) > 1000:
        _paid_opt_done.clear()
        _save_paid_opt_done()


def _recover_orphaned_voucher_charges():
    """Recovery all'avvio: cerca addebiti voucher recenti (ultime 2 ore) il cui
    job_id non è né in memoria (``jobs``) né tra quelli completati con successo
    (``_paid_opt_done``). Questo copre il caso in cui il server è stato
    riavviato/crashato durante un'ottimizzazione a pagamento: il voucher era già
    stato addebitato ma il job non è mai terminato.
    Ri-accredita automaticamente l'importo sul voucher.
    """
    cutoff = time.time() - 2 * 3600  # ultime 2 ore
    recovered = 0
    for code, v in _vouchers.items():
        uses = v.get("uses")
        if not isinstance(uses, list):
            continue
        for use in uses:
            # Solo addebiti (positivi), non refund (negativi)
            amt = float(use.get("amount_eur", 0) or 0)
            if amt <= 0:
                continue
            use_time = float(use.get("at", 0) or 0)
            if use_time < cutoff:
                continue
            use_job_id = use.get("job_id", "")
            if not use_job_id:
                continue
            # Se il job è completato con successo  →  non rimborsare
            if use_job_id in _paid_opt_done:
                continue
            # Se il job è ancora in memoria  →  non rimborsare (non dovrebbe accadere al restart)
            if use_job_id in jobs:
                continue
            # Verifica che non sia già stato rimborsato (cerca refund con stesso job_id)
            already_refunded = any(
                float(u.get("amount_eur", 0) or 0) < 0 and u.get("job_id") == use_job_id
                for u in uses
            )
            if already_refunded:
                continue
            try:
                _voucher_refund(
                    code, amt, job_id=use_job_id,
                    reason="Recovery avvio server: job orfano",
                )
                recovered += 1
            except Exception as e:
                print(f"[startup] Recovery failed for voucher {code} job {use_job_id}: {e}")
    if recovered:
        print(f"[startup] Recovered {recovered} orphaned voucher charge(s)")


# ----------------------------------------------------------------------
# PAYPAL REST API v2
# ----------------------------------------------------------------------

def _paypal_get_access_token():
    """Get OAuth2 access token (cached ~8h)."""
    import requests
    now = time.time()
    if _paypal_token_cache["access_token"] and _paypal_token_cache["expires_at"] > now + 60:
        return _paypal_token_cache["access_token"]
    if not _paypal_available():
        return None
    r = requests.post(
        f"{PAYPAL_API_BASE}/v1/oauth2/token",
        auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json"},
        timeout=15,
    )
    if r.status_code != 200:
        # Diagnostic info  -  don't leak the secret, but show ID prefix and mode
        cid_hint = (PAYPAL_CLIENT_ID[:6] + "…" + PAYPAL_CLIENT_ID[-4:]) if len(PAYPAL_CLIENT_ID) > 12 else "(too short)"
        body = (r.text or "")[:300]
        raise RuntimeError(
            f"PayPal OAuth failed: HTTP {r.status_code} on {PAYPAL_API_BASE} "
            f"(mode={PAYPAL_MODE}, client_id={cid_hint}, secret_len={len(PAYPAL_SECRET)}). "
            f"Response: {body}. "
            f"Verifica che le credenziali siano dell'app {PAYPAL_MODE.upper()} "
            f"creata su https://developer.paypal.com/dashboard/applications/{PAYPAL_MODE}"
        )
    data = r.json()
    _paypal_token_cache["access_token"] = data["access_token"]
    _paypal_token_cache["expires_at"] = now + int(data.get("expires_in", 28800)) - 60
    return data["access_token"]


def _paypal_create_order(amount_eur, description, custom_id=None):
    """Create a PayPal Order. Returns dict with 'id' and 'status'."""
    import requests
    token = _paypal_get_access_token()
    if not token:
        raise RuntimeError("PayPal not configured")
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "amount": {"currency_code": "EUR", "value": f"{amount_eur:.2f}"},
            "description": description[:127],
        }],
        "application_context": {
            "brand_name": "Audiobook Maker",
            "user_action": "PAY_NOW",
            "shipping_preference": "NO_SHIPPING",
        },
    }
    if custom_id:
        payload["purchase_units"][0]["custom_id"] = custom_id[:127]
    r = requests.post(
        f"{PAYPAL_API_BASE}/v2/checkout/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _paypal_capture_order(order_id):
    """Capture a previously-approved order. Returns captured order dict."""
    import requests
    token = _paypal_get_access_token()
    if not token:
        raise RuntimeError("PayPal not configured")
    r = requests.post(
        f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


#  -  -  Admin activity digest  -  - 

# (Functions imported from email_service)

def _send_completion_email(job_id):
    """Send download link email when a job completes with email registered."""
    job = jobs.get(job_id)
    if not job or not job.get("notify_email"):
        return
    email = job["notify_email"]
    info = job.get("info", None)
    book_title = info.title if info else "Audiobook"
    dl_type = job.get("notify_download_type", "audio")
    base_url = job.get("notify_base_url", "").rstrip("/")
    lang = job.get("notify_lang", "en")

    # Generate unique download token with job snapshot for restart survival
    token = str(uuid.uuid4())
    _download_tokens[token] = {
        "job_id": job_id,
        "created_at": time.time(),
        "download_type": dl_type,
        "base_url": base_url,
        # Snapshot: everything needed to serve download after restart
        "book_title": book_title,
        "output_zip": job.get("output_zip", ""),
        "output_name": job.get("output_name", ""),
        "output_file": job.get("output_files", [""])[0] if job.get("output_files") else "",
        "output_m4b": job.get("output_m4b", ""),
        "epub_path": job.get("epub_path", ""),
        "podcast_safe_name": job.get("podcast_safe_name", ""),
        "podcast_ready": job.get("podcast_ready", False),
        "podcast_mp3s": job.get("podcast_mp3s", []),
        "podcast_info_title": info.title if info else "",
        "podcast_info_author": info.author if info else "",
        "podcast_info_language": info.language if info else "",
        "original_filename": job.get("original_filename", ""),
        "lang": lang,
        # Optional: optimized .abm snapshot (when auto_generate flow produced one)
        "optimized_abm_path": job.get("optimized_abm_path", ""),
        "optimized_abm_name": job.get("optimized_abm_name", ""),
    }
    _save_tokens()
    job["email_token"] = token
    job["email_sent_at"] = time.time()

    dl_url = f"{BASE_URL}/dl/{token}" if BASE_URL else f"/dl/{token}"

    # RSS XML filename for podcast
    safe_name = job.get("podcast_safe_name", _safe_filename(book_title) or "audiolibro")
    rss_filename = f"{safe_name}_podcast.xml"
    rss_url = f"{base_url}/{rss_filename}" if base_url else rss_filename

    #  -  -  i18n email content  -  - 
    _email_i18n = {
        "it": {
            "subject": f"Audiobook Maker  -  \"{book_title}\" pronto per il download",
            "heading": "&#x1F3A7; Il tuo audiolibro &egrave; pronto!",
            "body": f"La generazione di <strong>{book_title}</strong> &egrave; stata completata con successo.",
            "m4b_failed_msg": "<div style='margin:15px 0;padding:12px;background:#fffbeb;border:1px solid #fef3c7;color:#92400e;border-radius:6px;font-size:14px'>&#x26A0;&#xFE0F; La conversione in formato M4B non &egrave; andata a buon fine dopo diversi tentativi. Ti forniamo comunque la versione MP3 singola.</div>",
            "btn_m4b": "&#x1F4D6; Scarica audiolibro (M4B)",
            "btn_zip": "&#x1F4C2; Scarica archivio (ZIP/MP3)",
            "btn_mp3": "&#x1F50A; Scarica file audio (MP3)",
            "warn": "&#x23F0; Attenzione: i file saranno disponibili per il download soltanto per 24 ore a partire dalla ricezione di questa email. Dopo tale periodo verranno cancellati automaticamente.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Istruzioni per la pubblicazione del Podcast</strong>",
            "podcast_p1": f"Il file ZIP scaricato contiene tutti i file necessari per il tuo podcast. Per renderlo fruibile online, <strong>decomprimi il file ZIP</strong> e carica tutti i file contenuti sul tuo server web, in modo che siano raggiungibili all'indirizzo:",
            "podcast_p2": f"Il file XML del feed RSS del podcast sar&agrave;:",
            "podcast_p3": f"Per rendere il podcast disponibile su app come <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> o altri aggregatori, fornisci l'indirizzo del file XML come URL del feed.",
            "footer": "Questa email &egrave; stata generata automaticamente da Audiobook Maker.",
        },
        "en": {
            "subject": f"Audiobook Maker  -  \"{book_title}\" ready for download",
            "heading": "&#x1F3A7; Your audiobook is ready!",
            "body": f"The generation of <strong>{book_title}</strong> has been completed successfully.",
            "m4b_failed_msg": "<div style='margin:15px 0;padding:12px;background:#fffbeb;border:1px solid #fef3c7;color:#92400e;border-radius:6px;font-size:14px'>&#x26A0;&#xFE0F; M4B conversion failed after several attempts. We are providing the single MP3 version instead.</div>",
            "btn_m4b": "&#x1F4D6; Download audiobook (M4B)",
            "btn_zip": "&#x1F4C2; Download archive (ZIP/MP3)",
            "btn_mp3": "&#x1F50A; Download audio file (MP3)",
            "warn": "&#x23F0; Please note: the files will be available for download for 24 hours only from the time you receive this email. After that, they will be automatically deleted.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Podcast Publishing Instructions</strong>",
            "podcast_p1": f"The downloaded ZIP file contains all the files needed for your podcast. To make it available online, <strong>extract the ZIP file</strong> and upload all files to your web server so they are reachable at:",
            "podcast_p2": f"The podcast RSS feed XML file will be:",
            "podcast_p3": f"To make the podcast available on apps like <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> or other aggregators, provide the XML file URL as the feed URL.",
            "footer": "This email was automatically generated by Audiobook Maker.",
        },
        "fr": {
            "subject": f"Audiobook Maker  -  \"{book_title}\" pr&ecirc;t au t&eacute;l&eacute;chargement",
            "heading": "&#x1F3A7; Votre livre audio est pr&ecirc;t !",
            "body": f"La g&eacute;n&eacute;ration de <strong>{book_title}</strong> a &eacute;t&eacute; compl&eacute;t&eacute;e avec succ&egrave;s.",
            "btn": "&#x2B07;&#xFE0F; T&eacute;l&eacute;charger l'audiolibro",
            "warn": "&#x23F0; Attention : les fichiers seront disponibles au t&eacute;l&eacute;chargement pendant 24 heures seulement &agrave; compter de la r&eacute;ception de cet email. Pass&eacute; ce d&eacute;lai, ils seront automatiquement supprim&eacute;s.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Instructions de publication du podcast</strong>",
            "podcast_p1": f"Le fichier ZIP t&eacute;l&eacute;charg&eacute; contient tous les fichiers n&eacute;cessaires &agrave; votre podcast. Pour le rendre accessible en ligne, <strong>d&eacute;compressez le fichier ZIP</strong> et t&eacute;l&eacute;versez tous les fichiers sur votre serveur web, de sorte qu'ils soient accessibles &agrave; l'adresse :",
            "podcast_p2": f"Le fichier XML du flux RSS du podcast sera :",
            "podcast_p3": f"Pour rendre le podcast disponible sur des apps comme <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> ou d'autres agr&eacute;gateurs, fournissez l'URL du fichier XML comme URL du flux.",
            "footer": "Cet email a &eacute;t&eacute; g&eacute;n&eacute;r&eacute; automatiquement par Audiobook Maker.",
        },
        "es": {
            "subject": f"Audiobook Maker  -  \"{book_title}\" listo para descargar",
            "heading": "&#x1F3A7; &iexcl;Tu audiolibro est&aacute; listo!",
            "body": f"La generaci&oacute;n de <strong>{book_title}</strong> se ha completado con &eacute;xito.",
            "btn": "&#x2B07;&#xFE0F; Descargar audiolibro",
            "warn": "&#x23F0; Atenci&oacute;n: los archivos estar&aacute;n disponibles para descargar solo durante 24 horas desde la recepci&oacute;n de este email. Despu&eacute;s de ese periodo se eliminar&aacute;n autom&aacute;ticamente.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Instrucciones para publicar el podcast</strong>",
            "podcast_p1": f"El archivo ZIP descargado contiene todos los archivos necesarios para tu podcast. Para hacerlo accesible en l&iacute;nea, <strong>descomprime el archivo ZIP</strong> y sube todos los archivos a tu servidor web para que sean accesibles en:",
            "podcast_p2": f"El archivo XML del feed RSS del podcast ser&aacute;:",
            "podcast_p3": f"Para que el podcast est&eacute; disponible en apps como <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> u otros agregadores, proporciona la URL del archivo XML como URL del feed.",
            "footer": "Este email fue generado autom&aacute;ticamente por Audiobook Maker.",
        },
        "de": {
            "subject": f"Audiobook Maker  -  \"{book_title}\" bereit zum Download",
            "heading": "&#x1F3A7; Dein H&ouml;rbuch ist fertig!",
            "body": f"Die Generierung von <strong>{book_title}</strong> wurde erfolgreich abgeschlossen.",
            "btn": "&#x2B07;&#xFE0F; Hörbuch herunterladen",
            "warn": "&#x23F0; Hinweis: Die Dateien stehen nur 24 Stunden ab Erhalt dieser E-Mail zum Download bereit. Danach werden sie automatisch gel&ouml;scht.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Anleitung zur Podcast-Ver&ouml;ffentlichung</strong>",
            "podcast_p1": f"Die heruntergeladene ZIP-Datei enth&auml;lt alle Dateien f&uuml;r deinen Podcast. Um ihn online verf&uuml;gbar zu machen, <strong>entpacke die ZIP-Datei</strong> und lade alle Dateien auf deinen Webserver hoch, sodass sie unter folgender Adresse erreichbar sind:",
            "podcast_p2": f"Die XML-Datei des Podcast-RSS-Feeds lautet:",
            "podcast_p3": f"Um den Podcast in Apps wie <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> oder anderen Aggregatoren verf&uuml;gbar zu machen, gib die URL der XML-Datei als Feed-URL an.",
            "footer": "Diese E-Mail wurde automatisch von Audiobook Maker generiert.",
        },
        "zh": {
            "subject": f"Audiobook Maker  -  \"{book_title}\" \u5df2\u51c6\u5907\u597d\u4e0b\u8f7d",
            "heading": "&#x1F3A7; \u60a8\u7684\u6709\u58f0\u8bfb\u7269\u5df2\u51c6\u5907\u597d\uff01",
            "body": f"<strong>{book_title}</strong> \u5df2\u6210\u529f\u751f\u6210\u3002",
            "btn": "&#x2B07;&#xFE0F; \u4e0b\u8f7d\u6587\u4ef6",
            "warn": "&#x23F0; \u8bf7\u6ce8\u610f\uff1a\u6587\u4ef6\u4ec5\u5728\u6536\u5230\u6b64\u90ae\u4ef6\u540e24\u5c0f\u65f6\u5185\u53ef\u4f9b\u4e0b\u8f7d\u3002\u4e4b\u540e\u5c06\u81ea\u52a8\u5220\u9664\u3002",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>\u64ad\u5ba2\u53d1\u5e03\u8bf4\u660e</strong>",
            "podcast_p1": f"\u4e0b\u8f7d\u7684ZIP\u6587\u4ef6\u5305\u542b\u64ad\u5ba2\u6240\u9700\u7684\u6240\u6709\u6587\u4ef6\u3002\u8981\u5728\u7ebf\u53d1\u5e03\uff0c\u8bf7<strong>\u89e3\u538bZIP\u6587\u4ef6</strong>\uff0c\u5e76\u5c06\u6240\u6709\u6587\u4ef6\u4e0a\u4f20\u5230\u60a8\u7684\u7f51\u7edc\u670d\u52a1\u5668\uff0c\u4f7f\u5176\u53ef\u901a\u8fc7\u4ee5\u4e0b\u5730\u5740\u8bbf\u95ee\uff1a",
            "podcast_p2": f"\u64ad\u5ba2RSS\u8ba2\u9605\u6e90\u7684XML\u6587\u4ef6\u5730\u5740\u4e3a\uff1a",
            "podcast_p3": f"\u8981\u5728<strong>Pocket Casts</strong>\u3001<strong>Apple Podcasts (iTunes)</strong>\u7b49\u5e94\u7528\u4e0a\u53d1\u5e03\u64ad\u5ba2\uff0c\u8bf7\u5c06XML\u6587\u4ef6\u7684URL\u4f5c\u4e3a\u8ba2\u9605\u6e90\u5730\u5740\u63d0\u4f9b\u3002",
            "footer": "\u6b64\u90ae\u4ef6\u7531 Audiobook Maker \u81ea\u52a8\u751f\u6210\u3002",
        },
    }

    t = dict(_email_i18n.get(lang, _email_i18n["en"]))

    # Se il job ha incluso ottimizzazione AI + generazione TTS nel medesimo flusso,
    # l'utente si aspetta di scaricare anche l'audio: chiariamo il bottone con
    # "file audio" per distinguerlo dall'email di sola ottimizzazione (.abm).
    if job.get("ai_optimized"):
        _btn_audio = {
            "it": "&#x2B07;&#xFE0F; Scarica audiolibro",
            "en": "&#x2B07;&#xFE0F; Download audiobook",
            "fr": "&#x2B07;&#xFE0F; T&eacute;l&eacute;charger l'audiolibro",
            "es": "&#x2B07;&#xFE0F; Descargar audiolibro",
            "de": "&#x2B07;&#xFE0F; Hörbuch herunterladen",
            "zh": "&#x2B07;&#xFE0F; \u4e0b\u8f7d\u60a8\u7684\u97f3\u9891\u6587\u4ef6",
        }
        t["btn"] = _btn_audio.get(lang, _btn_audio["en"])

    #  -  -  Button and Warning logic based on job outcome  -  - 
    is_m4b = (dl_type == "audio" and job.get("output_m4b"))
    m4b_failed = job.get("m4b_failed", False)
    
    if m4b_failed:
        t["body"] = t.get("m4b_failed_msg", "") + t["body"]
        t["btn_final"] = t["btn_mp3"]
    elif is_m4b:
        t["btn_final"] = t["btn_m4b"]
    elif dl_type == "podcast":
        t["btn_final"] = t["btn_zip"]
    else:
        # ZIP or fallback
        t["btn_final"] = t["btn_zip"]

    #  -  -  Podcast section (only for podcast downloads)  -  - 
    podcast_section = ""
    if dl_type == "podcast" and base_url:
        podcast_section = f"""
      <div style="margin:20px 0;padding:16px 20px;background:#f0f7ff;border-left:4px solid #3b82f6;border-radius:4px">
        <p style="margin:0 0 10px">{t['podcast_intro']}</p>
        <p style="margin:0 0 8px">{t['podcast_p1']}</p>
        <p style="margin:0 0 12px;padding:8px 12px;background:#e2e8f0;border-radius:4px;font-family:monospace;word-break:break-all">
          &#x1F4C1; <a href="{base_url}" style="color:#3b82f6">{base_url}/</a>
        </p>
        <p style="margin:0 0 8px">{t['podcast_p2']}</p>
        <p style="margin:0 0 12px;padding:8px 12px;background:#e2e8f0;border-radius:4px;font-family:monospace;word-break:break-all">
          &#x1F4E1; <a href="{rss_url}" style="color:#3b82f6">{rss_url}</a>
        </p>
        <p style="margin:0">{t['podcast_p3']}</p>
      </div>"""

    #  -  -  Optional: link to optimized .abm file (only present when auto_generate flow produced one)  -  - 
    abm_section = ""
    has_abm = bool(job.get("optimized_abm_path")) and os.path.exists(job.get("optimized_abm_path", ""))
    if has_abm:
        abm_url = f"{BASE_URL}/dl/{token}/abm" if BASE_URL else f"/dl/{token}/abm"
        _abm_labels = {
            "it": ("&#x1F4DD; Scarica progetto ottimizzato (.abm)", "Contiene il testo ottimizzato dall'AI, utile per future ri-generazioni audio o revisioni manuali."),
            "en": ("&#x1F4DD; Download optimized project (.abm)", "Contains the AI-optimized text, useful for future audio re-generations or manual revisions."),
            "fr": ("&#x1F4DD; T&eacute;l&eacute;charger le projet optimis&eacute; (.abm)", "Contient le texte optimis&eacute; par l'IA, utile pour les futures re-g&eacute;n&eacute;rations audio ou r&eacute;visions manuelles."),
            "es": ("&#x1F4DD; Descargar proyecto optimizado (.abm)", "Contiene el texto optimizado por IA, &uacute;til para futuras regeneraciones de audio o revisiones manuales."),
            "de": ("&#x1F4DD; Optimiertes Projekt herunterladen (.abm)", "Enth&auml;lt den KI-optimierten Text, n&uuml;tzlich f&uuml;r zuk&uuml;nftige Audio-Regenerierung oder manuelle &Uuml;berarbeitung."),
            "zh": ("&#x1F4DD; \u4e0b\u8f7d\u4f18\u5316\u540e\u7684\u9879\u76ee\u6587\u4ef6 (.abm)", "\u5305\u542bAI\u4f18\u5316\u540e\u7684\u6587\u672c\uff0c\u53ef\u7528\u4e8e\u672a\u6765\u97f3\u9891\u91cd\u65b0\u751f\u6210\u6216\u624b\u52a8\u4fee\u8ba2\u3002"),
        }
        abm_btn, abm_hint = _abm_labels.get(lang, _abm_labels["en"])
        abm_section = f"""
      <p style="margin:16px 0 6px">
        <a href="{abm_url}" style="display:inline-block;padding:12px 24px;background:#8b5cf6;color:white;
           text-decoration:none;border-radius:8px;font-weight:600;font-size:15px">
          {abm_btn}
        </a>
      </p>
      <p style="margin:0 0 16px;color:#666;font-size:13px">{abm_hint}</p>"""

    subject = t["subject"]
    html_body = f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <h2 style="color:#2c3e50">{t['heading']}</h2>
      <p>{t['body']}</p>
      <p style="margin:24px 0">
        <a href="{dl_url}" style="display:inline-block;padding:14px 28px;background:#3b82f6;color:white;
           text-decoration:none;border-radius:8px;font-weight:600;font-size:16px">
          {t['btn']}
        </a>
      </p>
      {abm_section}
      <p style="color:#e74c3c;font-weight:600">{t['warn']}</p>
      {podcast_section}
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
      <p style="color:#999;font-size:12px">
        {t['footer']}
        {('Visita ' + BASE_URL) if BASE_URL else ''}
      </p>
    </div>
    """
    success = _send_email(email, subject, html_body)
    if success:
        _log_activity(job_id, job.get("original_filename", ""), "EMAIL_SENT",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      job.get("voice", ""), job.get("browser_lang", ""))
    else:
        _log_activity(job_id, job.get("original_filename", ""), "EMAIL_FAILED",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      job.get("voice", ""), job.get("browser_lang", ""))

#  -  -  Activity log  -  - 
_log_lock = threading.Lock()


def _log_activity(session_id, filename, operation, client_id="", client_ip="", voice="", browser_lang=""):
    """Append one line to the activity log file (one file per month).

    Format (# separated):
        session_id # datetime # "filename" # operation # client_id # client_ip # voice # browser_lang
    Operations: ANALYZE, GENERATE, COMPLETE, DOWNLOAD, DOWNLOAD_PODCAST
    """
    from datetime import datetime
    now = datetime.now()
    log_path = SCRIPT_DIR / f"activity_{now.strftime('%Y-%m')}.log"
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    line = f'{session_id} # {ts} # "{filename}" # {operation} # {client_id} # {client_ip} # {voice} # {browser_lang}\n'
    try:
        with _log_lock:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line)
    except OSError:
        pass


# ----------------------------------------------------------------------
# VOICE MANAGEMENT
# ----------------------------------------------------------------------

_voices_cache = None
_voices_lock = threading.Lock()

LANGUAGE_NAMES = {
    "af": "Afrikaans", "am": "Amarico", "ar": "Arabo", "az": "Azerbaigiano",
    "bg": "Bulgaro", "bn": "Bengalese", "bs": "Bosniaco", "ca": "Catalano",
    "cs": "Ceco", "cy": "Gallese", "da": "Danese", "de": "Tedesco",
    "el": "Greco", "en": "Inglese", "es": "Spagnolo", "et": "Estone",
    "fa": "Persiano", "fi": "Finlandese", "fil": "Filippino", "fr": "Francese",
    "ga": "Irlandese", "gl": "Galiziano", "gu": "Gujarati", "he": "Ebraico",
    "hi": "Hindi", "hr": "Croato", "hu": "Ungherese", "id": "Indonesiano",
    "is": "Islandese", "it": "Italiano", "ja": "Giapponese", "jv": "Giavanese",
    "ka": "Georgiano", "kk": "Kazako", "km": "Khmer", "kn": "Kannada",
    "ko": "Coreano", "lo": "Lao", "lt": "Lituano", "lv": "Lettone",
    "mk": "Macedone", "ml": "Malayalam", "mn": "Mongolo", "mr": "Marathi",
    "ms": "Malese", "mt": "Maltese", "my": "Birmano", "nb": "Norvegese Bokmal",
    "ne": "Nepalese", "nl": "Olandese", "pl": "Polacco", "ps": "Pashto",
    "pt": "Portoghese", "ro": "Romeno", "ru": "Russo", "si": "Singalese",
    "sk": "Slovacco", "sl": "Sloveno", "so": "Somalo", "sq": "Albanese",
    "sr": "Serbo", "su": "Sundanese", "sv": "Svedese", "sw": "Swahili",
    "ta": "Tamil", "te": "Telugu", "th": "Thailandese", "tr": "Turco",
    "uk": "Ucraino", "ur": "Urdu", "uz": "Uzbeco", "vi": "Vietnamita",
    "zh": "Cinese", "zu": "Zulu",
}


async def _fetch_voices():
    return await edge_tts.list_voices()


def get_voices():
    global _voices_cache
    with _voices_lock:
        if _voices_cache is not None:
            return _voices_cache

    loop = asyncio.new_event_loop()
    try:
        raw = loop.run_until_complete(_fetch_voices())
    finally:
        loop.close()

    languages = {}
    for v in raw:
        locale = v["Locale"]
        lang_code = locale.split("-")[0]
        lang_name = LANGUAGE_NAMES.get(lang_code, lang_code)
        if lang_code not in languages:
            languages[lang_code] = {"code": lang_code, "name": lang_name, "voices": []}
        languages[lang_code]["voices"].append({
            "id": v["ShortName"],
            "name": v["ShortName"].split("-")[-1].replace("Neural", ""),
            "locale": locale,
            "gender": v["Gender"],
            "gender_icon": "\u2640" if v["Gender"] == "Female" else "\u2642",
            "engine": "edge",
        })

    #  -  -  Merge voci Google Cloud TTS Chirp3-HD (se disponibili e budget non esaurito)  -  - 
    if google_tts is not None and google_tts.is_available():
        gcloud_voices = google_tts.get_voices()
        for lang_code, voice_list in gcloud_voices.items():
            lang_name = LANGUAGE_NAMES.get(lang_code, lang_code)
            if lang_code not in languages:
                languages[lang_code] = {"code": lang_code, "name": lang_name, "voices": []}
            languages[lang_code]["voices"].extend(voice_list)

    for lang in languages.values():
        lang["voices"].sort(key=lambda x: (x["gender"], x["name"]))

    priority = {"it": 0, "en": 1, "fr": 2, "de": 3, "es": 4, "pt": 5}
    sorted_langs = dict(sorted(
        languages.items(),
        key=lambda x: (priority.get(x[0], 99), x[1]["name"])
    ))

    with _voices_lock:
        _voices_cache = sorted_langs
    return sorted_langs


def _invalidate_voices_cache():
    """Invalida la cache voci (ricarica al prossimo get_voices())."""
    global _voices_cache
    with _voices_lock:
        _voices_cache = None
    if google_tts is not None:
        google_tts.invalidate_voices_cache()


# ----------------------------------------------------------------------
# AUDIO GENERATION
# ----------------------------------------------------------------------

# (Functions moved to tts_split.py - imported at top of file)


class _CancelledError(Exception):
    """Raised when a generation job is cancelled."""
    pass


class _SimpleChapter:
    """Lightweight chapter object compatible with BookInfo.chapters interface."""
    def __init__(self, index, title, text):
        self.index = index
        self.title = title
        self.text = text
        self.word_count = len(text.split())
        self.char_count = len(text)


class _SimpleBookInfo:
    """Lightweight book info for TXT files, duck-typed to match BookInfo."""
    def __init__(self, title, author, text):
        self.title = title
        self.author = author
        self.language = ""
        self.description = ""
        self.date = ""
        ch = _SimpleChapter(1, title, text)
        self.chapters = [ch]
        self.total_words = ch.word_count
        self.total_chars = ch.char_count
        self.estimated_duration_minutes = self.total_words / 150


def parse_txt(file_path):
    """Parse a plain text file into a _SimpleBookInfo."""
    path = Path(file_path)
    # Try UTF-8 first, fall back to latin-1
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = path.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    else:
        text = path.read_text(encoding="latin-1", errors="replace")

    text = text.strip()
    if not text:
        raise ValueError("Text file is empty")

    # Title = filename without extension
    title = path.stem.replace("_", " ").replace("-", " ").strip() or "Text"
    return _SimpleBookInfo(title=title, author="", text=text)


def parse_abm(file_path):
    """Parse an .abm project file (ZIP with manifest + chapter texts + optional cover).

    Returns (info, cover_info) where info is duck-typed BookInfo and
    cover_info is {"data": bytes, "filename": str} or None.
    """
    import zipfile

    path = Path(file_path)
    if not zipfile.is_zipfile(str(path)):
        raise ValueError("Invalid .abm file: not a valid ZIP archive")

    with zipfile.ZipFile(str(path), "r") as zf:
        # Read and validate manifest
        try:
            manifest_data = zf.read("manifest.json")
        except KeyError:
            raise ValueError("Invalid .abm file: manifest.json not found")

        try:
            manifest = json.loads(manifest_data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid .abm file: malformed manifest.json ({e})")

        if manifest.get("format") != "audiobook-maker-project":
            raise ValueError("Invalid .abm file: unrecognized format in manifest.json")

        title = manifest.get("title", path.stem)
        author = manifest.get("author", "")
        language = manifest.get("language", "")

        # Read chapters in manifest order
        chapters_meta = manifest.get("chapters", [])
        if not chapters_meta:
            raise ValueError("Invalid .abm file: no chapters listed in manifest")

        chapters = []
        for cm in chapters_meta:
            fname = cm.get("filename", "")
            ch_title = cm.get("title", f"Chapter {cm.get('index', '?')}")
            ch_index = cm.get("index", len(chapters) + 1)

            ch_path = f"chapters/{fname}" if not fname.startswith("chapters/") else fname
            try:
                ch_text = zf.read(ch_path).decode("utf-8").strip()
            except KeyError:
                print(f"[abm] WARNING: chapter file '{ch_path}' not found in archive, skipping")
                continue
            except UnicodeDecodeError:
                ch_text = zf.read(ch_path).decode("latin-1", errors="replace").strip()

            if not ch_text:
                continue

            chapters.append(_SimpleChapter(index=ch_index, title=ch_title, text=ch_text))

        if not chapters:
            raise ValueError("Invalid .abm file: no readable chapter content found")

        # Build BookInfo-compatible object
        info = _SimpleBookInfo.__new__(_SimpleBookInfo)
        info.title = title
        info.author = author
        info.language = language
        info.chapters = chapters
        info.total_words = sum(ch.word_count for ch in chapters)
        info.total_chars = sum(ch.char_count for ch in chapters)
        info.estimated_duration_minutes = info.total_words / 150

        # Extract cover if present
        cover_info = None
        if manifest.get("has_cover") and manifest.get("cover_file"):
            cover_file = manifest["cover_file"]
            try:
                cover_data = zf.read(cover_file)
                if len(cover_data) > 100:  # sanity check
                    cover_info = {"data": cover_data, "filename": cover_file}
            except KeyError:
                pass

    return info, cover_info



# ----------------------------------------------------------------------
# LLM TEXT OPTIMIZATION (DeepSeek)
# ----------------------------------------------------------------------

def _split_text_into_chunks(text, max_chars):
    """Split text into chunks respecting paragraph boundaries."""
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current_chunk = []
    current_size = 0

    for para in paragraphs:
        para_size = len(para)
        if para_size > max_chars:
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_size = 0
            sentences = re.split(r'(?<=[.!?…])\s+', para)
            sub_chunk = []
            sub_size = 0
            for sent in sentences:
                if sub_size + len(sent) > max_chars and sub_chunk:
                    chunks.append(" ".join(sub_chunk))
                    sub_chunk = []
                    sub_size = 0
                sub_chunk.append(sent)
                sub_size += len(sent)
            if sub_chunk:
                chunks.append(" ".join(sub_chunk))
            continue
        if current_size + para_size + 2 > max_chars and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = []
            current_size = 0
        current_chunk.append(para)
        current_size += para_size + 2
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
    return chunks


# Pattern di preamboli/postfazioni meta che il LLM a volte emette nonostante
# il prompt vieti commenti (Understood, Sure, Ecco il testo…, According to the
# rules…). Se presenti vengono scartati dal sanitizer: se finissero nell'audio,
# il TTS leggerebbe "Understood, according to the rule…" come se fosse testo
# del libro.
_LLM_PREAMBLE_PATTERNS = (
    # Inglese
    r"^(understood|sure|certainly|of\s+course|got\s+it|okay|ok|alright|"
    r"here(?:'s|\s+is)\s+(?:the\s+)?(?:optimized|cleaned|edited|revised)(?:\s+text|\s+version)?|"
    r"below\s+is\s+the|following\s+the\s+rules?|according\s+to\s+the\s+rules?|"
    r"as\s+requested|as\s+instructed|noted)\b",
    # Italiano
    r"^(capito|compreso|d['’]accordo|ho\s+capito|perfetto|va\s+bene|certo|"
    r"ecco\s+(?:il|la|una)?\s*(?:testo|versione)(?:\s+ottimizzata?|\s+rivista|\s+pulita|\s+corretta)?|"
    r"seguendo\s+le\s+regole|secondo\s+le\s+regole|come\s+richiesto)\b",
    # Francese / spagnolo / tedesco (difese minori ma utili)
    r"^(compris|d['’]accord|voici\s+le\s+texte|suivant\s+les\s+r[èe]gles|"
    r"entendido|de\s+acuerdo|aquí\s+está\s+el\s+texto|"
    r"verstanden|hier\s+ist\s+der\s+text)\b",
)
_LLM_PREAMBLE_RE = re.compile(
    "|".join(_LLM_PREAMBLE_PATTERNS), re.IGNORECASE | re.UNICODE
)


def _sanitize_llm_output(text: str) -> str:
    """Rimuove contaminazioni tipiche dell'output LLM prima di passarlo al TTS.

    Due categorie di problemi mitigati:
      1) Preamboli/postfazioni meta ("Understood, according to the rules…",
         "Ecco il testo ottimizzato:", "Here is the optimized version:"…)
         che il modello emette nonostante il prompt li vieti. Se raggiungono
         il TTS vengono letti come se fossero testo del libro.
      2) Paragrafi/righe duplicate consecutivamente  -  tipicamente il titolo
         del capitolo ripetuto sia in coda al chunk precedente sia in testa
         a quello successivo.

    Conservativo: rimuove SOLO righe/blocchi che iniziano con un pattern
    riconosciuto (o sono duplicati esatti). Il contenuto narrativo non è mai
    toccato.
    """
    if not text:
        return text

    #  -  -  1) Strip preamble: rimuovi, in testa, le prime righe che iniziano
    # con un marcatore meta (e l'eventuale riga che termina con ':').
    lines = text.splitlines()
    idx = 0
    # Salta righe vuote iniziali
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    # Se la prima riga non vuota sembra un preambolo, scartala (più le righe
    # immediatamente successive finché restano "meta": righe brevi che
    # terminano con ':' sono tipiche intestazioni ["Ecco il testo:"]).
    stripped_any = False
    while idx < len(lines):
        candidate = lines[idx].strip()
        if not candidate:
            if stripped_any:
                idx += 1  # consuma riga vuota separatrice dopo il preambolo
            break
        is_preamble = bool(_LLM_PREAMBLE_RE.match(candidate))
        # riga meta "corta" che termina con ':' (es. "Optimized text:")
        is_meta_header = (
            len(candidate) <= 80 and candidate.endswith(":")
            and not candidate[0].islower()
        )
        if is_preamble or (stripped_any and is_meta_header):
            idx += 1
            stripped_any = True
            continue
        break

    #  -  -  2) Strip trailing meta: ultime righe tipo "Note: …" o
    # "[End of optimized text]".
    end = len(lines)
    while end > idx:
        tail = lines[end - 1].strip()
        if not tail:
            end -= 1
            continue
        if tail.startswith(("Note:", "Nota:", "[Note", "[End", "[Fine",
                            " -  End", " - End")):
            end -= 1
            continue
        break

    cleaned = "\n".join(lines[idx:end]).strip("\n")

    #  -  -  3) Deduplica paragrafi consecutivi identici (titolo ripetuto a cavallo
    # di due chunk concatenati, o stesso blocco emesso due volte dal modello).
    paragraphs = re.split(r"\n{2,}", cleaned)
    deduped = []
    for p in paragraphs:
        p_norm = p.strip()
        if not p_norm:
            continue
        if deduped and deduped[-1].strip() == p_norm:
            continue
        deduped.append(p)

    #  -  -  4) Deduplica anche righe consecutive identiche *all'interno* di un
    # paragrafo (difesa in più contro doppie emissioni di singole righe).
    final_paragraphs = []
    for p in deduped:
        plines = p.split("\n")
        out_lines = []
        for ln in plines:
            if out_lines and out_lines[-1].strip() and out_lines[-1].strip() == ln.strip():
                continue
            out_lines.append(ln)
        final_paragraphs.append("\n".join(out_lines))

    return "\n\n".join(final_paragraphs).strip()


def _call_deepseek(user_content, job=None, max_retries=4):
    """Call DeepSeek API with streaming. Returns optimized text.
    If job is provided, updates opt_streamed_chars for real-time progress.
    Retries on transient network errors (connection reset, read timeout) with
    exponential backoff. The full chunk is re-sent on each retry since the
    LLM stream cannot be resumed mid-way."""
    messages = [
        {"role": "system", "content": _deepseek_prompt},
        {"role": "user", "content": user_content},
    ]
    last_exc = None
    for attempt in range(max_retries):
        result_parts = []
        partial_streamed = 0  # chars added to job during this attempt
        try:
            stream = _deepseek_client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=messages,
                max_tokens=DEEPSEEK_MAX_TOKENS,
                temperature=DEEPSEEK_TEMPERATURE,
                stream=True,
                timeout=120.0,
            )
            for event in stream:
                # Check cancellation during streaming to stop consuming tokens
                if job is not None and job.get("opt_cancelled"):
                    stream.close()
                    raise _CancelledError("Optimization cancelled during streaming")
                if event.choices and event.choices[0].delta.content:
                    chunk = event.choices[0].delta.content
                    result_parts.append(chunk)
                    if job is not None:
                        job["opt_streamed_chars"] = job.get("opt_streamed_chars", 0) + len(chunk)
                        partial_streamed += len(chunk)
            raw = "".join(result_parts)
            cleaned = _sanitize_llm_output(raw)
            if cleaned != raw:
                # Riallinea il contatore dello streaming se abbiamo scartato
                # preamboli/duplicati (evita numeratore gonfiato in progress bar).
                removed = len(raw) - len(cleaned)
                if job is not None and removed > 0:
                    job["opt_streamed_chars"] = max(
                        0, job.get("opt_streamed_chars", 0) - removed
                    )
                print(f"  [DeepSeek] sanitized output: removed {removed} chars of meta/duplicates")
            return cleaned
        except Exception as e:
            last_exc = e
            # Roll back partial progress so the next attempt's streaming
            # doesn't double-count chars
            if job is not None and partial_streamed > 0:
                job["opt_streamed_chars"] = max(0, job.get("opt_streamed_chars", 0) - partial_streamed)
            err_name = type(e).__name__
            # Only retry on transient network errors
            transient = any(s in err_name for s in (
                "ReadError", "ConnectError", "ConnectTimeout", "ReadTimeout",
                "RemoteProtocolError", "APIConnectionError", "APITimeoutError",
            ))
            if not transient or attempt >= max_retries - 1:
                raise
            wait = 2 ** attempt  # 1, 2, 4, 8 seconds
            print(f"  [DeepSeek] {err_name} (attempt {attempt+1}/{max_retries}), retry in {wait}s: {e}")
            time.sleep(wait)
    # Should not reach here, but just in case
    if last_exc:
        raise last_exc
    return "".join(result_parts)


def _optimize_chapter_text(text, chapter_num=None, total_chapters=None, job=None):
    """Optimize a single chapter's text, using chunking if needed."""
    label = f"[ch {chapter_num}/{total_chapters}]" if chapter_num else ""
    if len(text) <= DEEPSEEK_MAX_INPUT_CHARS:
        print(f"  {label} LLM single call ({len(text):,} chars)")
        return _call_deepseek(text, job=job)
    # Chunk the chapter
    chunks = _split_text_into_chunks(text, DEEPSEEK_MAX_INPUT_CHARS)
    print(f"  {label} LLM chunked: {len(chunks)} chunks")
    results = []
    for i, chunk in enumerate(chunks):
        if job is not None and job.get("opt_cancelled"):
            raise _CancelledError("Optimization cancelled between chunks")
        if len(chunks) > 1:
            if i == 0:
                user_content = f"[Parte {i+1} di {len(chunks)}  -  inizio del testo]\n\n{chunk}"
            elif i == len(chunks) - 1:
                user_content = f"[Parte {i+1} di {len(chunks)}  -  fine del testo]\n\n{chunk}"
            else:
                user_content = f"[Parte {i+1} di {len(chunks)}  -  continuazione]\n\n{chunk}"
        else:
            user_content = chunk
        results.append(_call_deepseek(user_content, job=job))
        if i < len(chunks) - 1:
            time.sleep(2)  # rate limiting tra chunk
    # Seconda passata di sanitizzazione sul testo ricomposto: se il chunk i
    # finisce con il titolo del capitolo e il chunk i+1 lo ripete in testa,
    # dopo il join diventano paragrafi consecutivi identici  →  deduplicati.
    return _sanitize_llm_output("\n\n".join(results))


def _generate_optimized_abm(job_id):
    """Generate an .abm file with AI-optimized text for email download."""
    import zipfile
    import io
    from datetime import datetime, timezone

    job = jobs[job_id]
    info = job.get("info")
    if not info:
        return None, None

    buf = io.BytesIO()
    safe_title = _safe_filename(info.title) or "project"

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        chapters_manifest = []
        for ch in info.chapters:
            ch_safe = _safe_filename(ch.title)[:50] or f"ch_{ch.index}"
            ch_filename = f"{ch.index:03d}_{ch_safe}.txt"
            zf.writestr(f"chapters/{ch_filename}", ch.text)
            chapters_manifest.append({
                "index": ch.index,
                "filename": ch_filename,
                "title": ch.title,
                "word_count": ch.word_count,
            })

        # Cover
        has_cover = False
        cover_file = ""
        cover_path = job.get("cover_thumb")
        if cover_path and os.path.exists(cover_path):
            cover_ext = ".png" if cover_path.endswith(".png") else ".jpg"
            cover_file = f"cover{cover_ext}"
            with open(cover_path, "rb") as cf:
                zf.writestr(cover_file, cf.read())
            has_cover = True

        manifest = {
            "format": "audiobook-maker-project",
            "format_version": "1.0",
            "title": info.title,
            "author": getattr(info, "author", ""),
            "language": getattr(info, "language", ""),
            "has_cover": has_cover,
            "cover_file": cover_file,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "original_filename": job.get("original_filename", ""),
            "ai_optimized": True,
            "ai_optimized_at": datetime.now(timezone.utc).isoformat(),
            "chapters": chapters_manifest,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    buf.seek(0)
    # Save .abm to disk for email download
    work_dir = UPLOAD_DIR / job_id
    work_dir.mkdir(exist_ok=True)
    abm_path = str(work_dir / f"{safe_title}_optimized.abm")
    with open(abm_path, "wb") as f:
        f.write(buf.getvalue())
    return abm_path, f"{safe_title}_optimized.abm"


def _send_optimization_email(job_id):
    """Send email with optimized .abm download link when LLM optimization completes."""
    job = jobs.get(job_id)
    if not job or not job.get("notify_email"):
        return
    email = job["notify_email"]
    info = job.get("info")
    book_title = info.title if info else "Audiobook"
    lang = job.get("notify_lang", "en")

    token = str(uuid.uuid4())
    abm_path = job.get("optimized_abm_path", "")
    abm_name = job.get("optimized_abm_name", "optimized.abm")

    _download_tokens[token] = {
        "job_id": job_id,
        "created_at": time.time(),
        "download_type": "optimized_abm",
        "book_title": book_title,
        "optimized_abm_path": abm_path,
        "optimized_abm_name": abm_name,
        "original_filename": job.get("original_filename", ""),
        "lang": lang,
    }
    _save_tokens()
    job["email_token"] = token
    job["email_sent_at"] = time.time()

    dl_url = f"{BASE_URL}/dl/{token}" if BASE_URL else f"/dl/{token}"

    _opt_email_i18n = {
        "it": {
            "subject": f"Audiobook Maker  -  \"{book_title}\" ottimizzazione testo completata",
            "heading": "&#x2728; Ottimizzazione testo completata!",
            "body": f"L'ottimizzazione AI del testo di <strong>{book_title}</strong> per la sintesi vocale &egrave; stata completata con successo.",
            "btn": "&#x2B07;&#xFE0F; Scarica il progetto ottimizzato (.abm)",
            "info": "Il file .abm scaricato contiene il testo ottimizzato per la sintesi vocale. Puoi caricarlo nuovamente su Audiobook Maker per procedere alla generazione dell'audiolibro.",
            "warn": "&#x23F0; Attenzione: il file sar&agrave; disponibile per il download soltanto per 24 ore.",
            "footer": "Questa email &egrave; stata generata automaticamente da Audiobook Maker.",
        },
        "en": {
            "subject": f"Audiobook Maker  -  \"{book_title}\" text optimization completed",
            "heading": "&#x2728; Text optimization completed!",
            "body": f"The AI text optimization of <strong>{book_title}</strong> for speech synthesis has been completed successfully.",
            "btn": "&#x2B07;&#xFE0F; Download optimized project (.abm)",
            "info": "The downloaded .abm file contains text optimized for speech synthesis. You can upload it back to Audiobook Maker to proceed with audiobook generation.",
            "warn": "&#x23F0; Please note: the file will be available for download for 24 hours only.",
            "footer": "This email was automatically generated by Audiobook Maker.",
        },
        "fr": {
            "subject": f"Audiobook Maker  -  \"{book_title}\" optimisation du texte termin&eacute;e",
            "heading": "&#x2728; Optimisation du texte termin&eacute;e !",
            "body": f"L'optimisation AI du texte de <strong>{book_title}</strong> pour la synth&egrave;se vocale a &eacute;t&eacute; compl&eacute;t&eacute;e avec succ&egrave;s.",
            "btn": "&#x2B07;&#xFE0F; T&eacute;l&eacute;charger le projet optimis&eacute; (.abm)",
            "info": "Le fichier .abm t&eacute;l&eacute;charg&eacute; contient le texte optimis&eacute; pour la synth&egrave;se vocale. Vous pouvez le recharger sur Audiobook Maker pour g&eacute;n&eacute;rer le livre audio.",
            "warn": "&#x23F0; Attention : le fichier sera disponible au t&eacute;l&eacute;chargement pendant 24 heures seulement.",
            "footer": "Cet email a &eacute;t&eacute; g&eacute;n&eacute;r&eacute; automatiquement par Audiobook Maker.",
        },
        "es": {
            "subject": f"Audiobook Maker  -  \"{book_title}\" optimizaci&oacute;n de texto completada",
            "heading": "&#x2728; &iexcl;Optimizaci&oacute;n de texto completada!",
            "body": f"La optimizaci&oacute;n AI del texto de <strong>{book_title}</strong> para la s&iacute;ntesis de voz se ha completado con &eacute;xito.",
            "btn": "&#x2B07;&#xFE0F; Descargar proyecto optimizado (.abm)",
            "info": "El archivo .abm descargado contiene el texto optimizado para la s&iacute;ntesis de voz. Puedes cargarlo nuevamente en Audiobook Maker para generar el audiolibro.",
            "warn": "&#x23F0; Atenci&oacute;n: el archivo estar&aacute; disponible para descargar solo durante 24 horas.",
            "footer": "Este email fue generado autom&aacute;ticamente por Audiobook Maker.",
        },
        "de": {
            "subject": f"Audiobook Maker  -  \"{book_title}\" Textoptimierung abgeschlossen",
            "heading": "&#x2728; Textoptimierung abgeschlossen!",
            "body": f"Die KI-Textoptimierung von <strong>{book_title}</strong> f&uuml;r die Sprachsynthese wurde erfolgreich abgeschlossen.",
            "btn": "&#x2B07;&#xFE0F; Optimiertes Projekt herunterladen (.abm)",
            "info": "Die heruntergeladene .abm-Datei enth&auml;lt den f&uuml;r die Sprachsynthese optimierten Text. Du kannst sie erneut in Audiobook Maker hochladen, um das H&ouml;rbuch zu generieren.",
            "warn": "&#x23F0; Hinweis: Die Datei steht nur 24 Stunden zum Download bereit.",
            "footer": "Diese E-Mail wurde automatisch von Audiobook Maker generiert.",
        },
        "zh": {
            "subject": f"Audiobook Maker  -  \"{book_title}\" \u6587\u672c\u4f18\u5316\u5df2\u5b8c\u6210",
            "heading": "&#x2728; \u6587\u672c\u4f18\u5316\u5df2\u5b8c\u6210\uff01",
            "body": f"<strong>{book_title}</strong> \u7684AI\u6587\u672c\u4f18\u5316\u5df2\u6210\u529f\u5b8c\u6210\u3002",
            "btn": "&#x2B07;&#xFE0F; \u4e0b\u8f7d\u4f18\u5316\u9879\u76ee (.abm)",
            "info": "\u4e0b\u8f7d\u7684.abm\u6587\u4ef6\u5305\u542b\u4e3a\u8bed\u97f3\u5408\u6210\u4f18\u5316\u7684\u6587\u672c\u3002\u60a8\u53ef\u4ee5\u5c06\u5176\u91cd\u65b0\u4e0a\u4f20\u5230Audiobook Maker\u4ee5\u7ee7\u7eed\u751f\u6210\u6709\u58f0\u8bfb\u7269\u3002",
            "warn": "&#x23F0; \u8bf7\u6ce8\u610f\uff1a\u6587\u4ef6\u4ec5\u572824\u5c0f\u65f6\u5185\u53ef\u4f9b\u4e0b\u8f7d\u3002",
            "footer": "\u6b64\u90ae\u4ef6\u7531 Audiobook Maker \u81ea\u52a8\u751f\u6210\u3002",
        },
    }

    t = _opt_email_i18n.get(lang, _opt_email_i18n["en"])
    subject = t["subject"]
    html_body = f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <h2 style="color:#2c3e50">{t['heading']}</h2>
      <p>{t['body']}</p>
      <p style="margin:24px 0">
        <a href="{dl_url}" style="display:inline-block;padding:14px 28px;background:#8b5cf6;color:white;
           text-decoration:none;border-radius:8px;font-weight:600;font-size:16px">
          {t['btn']}
        </a>
      </p>
      <div style="margin:16px 0;padding:12px 16px;background:#f0f5ff;border-left:4px solid #8b5cf6;border-radius:4px">
        <p style="margin:0;font-size:14px">{t['info']}</p>
      </div>
      <p style="color:#e74c3c;font-weight:600">{t['warn']}</p>
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
      <p style="color:#999;font-size:12px">
        {t['footer']}
        {('Visita ' + BASE_URL) if BASE_URL else ''}
      </p>
    </div>
    """
    success = _send_email(email, subject, html_body)
    if success:
        _log_activity(job_id, job.get("original_filename", ""), "OPT_EMAIL_SENT",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      "", job.get("browser_lang", ""))
    else:
        _log_activity(job_id, job.get("original_filename", ""), "OPT_EMAIL_FAILED",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      "", job.get("browser_lang", ""))


def _refund_job_payment(job_id, job, reason="error"):
    """Rimborsa il pagamento di un job di ottimizzazione fallito o annullato.
    - payment_type == "voucher": ri-accredita l'importo sul voucher originale.
    - payment_type == "paypal": emette un nuovo voucher di rimborso (con bonus).
    """
    if job.get("refund_done"):
        return  # già rimborsato
    paid_amount = float(job.get("payment_amount_eur", 0) or 0)
    if paid_amount <= 0:
        return
    payment_type = job.get("payment_type", "")
    payment_email = job.get("payment_email", "")
    payment_token = job.get("payment_token", "")
    book_title = getattr(job.get("info"), "title", "") if job.get("info") else ""

    try:
        if payment_type == "voucher" and payment_token:
            # Ri-accredita direttamente sul voucher originale
            _voucher_refund(
                payment_token, paid_amount, job_id=job_id,
                reason=f"Rimborso automatico ottimizzazione {reason}",
            )
            job["refund_done"] = True
            _log_activity(job_id, job.get("original_filename", ""), "VOUCHER_REFUND",
                          job.get("client_id", ""), "", "", "")
            print(f"[{job_id}] Voucher {payment_token} refunded {paid_amount:.2f} EUR (reason={reason})")
        elif payment_type == "paypal" and payment_email:
            # Emetti nuovo voucher con bonus per pagamenti PayPal
            code, bonus_amount = _create_voucher(
                payment_email, paid_amount,
                origin_order_id=payment_token,
                origin_job_id=job_id,
                kind="refund",
                created_by="auto_refund",
                note=f"Rimborso automatico ottimizzazione AI ({reason})",
            )
            _send_voucher_email(code, payment_email, bonus_amount, book_title)
            job["refund_voucher_code"] = code
            job["refund_done"] = True
            _log_activity(job_id, job.get("original_filename", ""), "VOUCHER_ISSUED",
                          job.get("client_id", ""), "", "", "")
            print(f"[{job_id}] Voucher issued: {code} ({bonus_amount:.2f} EUR)  →  {payment_email} (reason={reason})")
    except Exception as ve:
        print(f"[{job_id}] Failed to refund payment: {ve}")


def run_optimization(job_id, selected_chapters=None):
    job = jobs[job_id]; job["status"] = "optimizing"; job["opt_cancelled"] = False; job["last_poll"] = time.time(); start_time = time.time(); info = job["info"]
    selected_indices = _parse_selected_chapters(selected_chapters)
    if selected_indices:
        from copy import copy
        filtered = [ch for ch in info.chapters if ch.index in selected_indices]
        if filtered:
            new_info = copy(info); new_info.chapters = filtered; job["info"] = new_info; info = new_info
    chapters_to_opt = info.chapters; total_chapters = len(chapters_to_opt); total_chars = sum(ch.char_count for ch in chapters_to_opt)

    # Log per confermare che il prompt di ottimizzazione è caricato
    if _deepseek_prompt:
        prompt_len = len(_deepseek_prompt)
        print(f"[{job_id}] Ottimizzazione AI avviata su {total_chapters} capitoli (prompt caricato: {prompt_len} caratteri)")
    else:
        print(f"[{job_id}] Ottimizzazione AI avviata su {total_chapters} capitoli (prompt non caricato)")

    job["opt_progress_current"] = 0
    job["opt_progress_total"] = total_chapters
    job["opt_total_chars"] = total_chars
    job["opt_processed_chars"] = 0
    job["opt_streamed_chars"] = 0
    job["opt_start_time"] = start_time

    try:
        for i, ch in enumerate(chapters_to_opt):
            if job.get("opt_cancelled"):
                raise _CancelledError("Optimization cancelled")
            # Heartbeat check (skip if email registered  -  batch mode)
            if not job.get("email_registered"):
                last_poll = job.get("last_poll", start_time)
                if time.time() - last_poll > 60:
                    raise _CancelledError("Optimization cancelled (heartbeat lost)")

            job["opt_progress_current"] = i
            job["opt_current_chapter"] = ch.title
            job["opt_current_chapter_num"] = i + 1
            job["opt_elapsed_seconds"] = round(time.time() - start_time)
            job["opt_progress_message"] = (
                f"Optimizing chapter {i+1}/{total_chapters}: "
                f"{ch.title[:40]}..."
            )
            print(f"[{job_id}] LLM optimizing chapter {i+1}/{total_chapters}: {ch.title}")

            # Progress in unità di INPUT
            ch_input_chars = ch.char_count
            job["opt_current_chapter_chars"] = ch_input_chars
            job["opt_streamed_chars"] = 0

            optimized_text = _optimize_chapter_text(
                ch.text, chapter_num=i+1, total_chapters=total_chapters, job=job
            )
            # Update chapter text with optimized version
            ch.text = optimized_text
            ch.word_count = len(optimized_text.split())
            ch.char_count = len(optimized_text)
            job["opt_processed_chars"] += ch_input_chars
            job["opt_streamed_chars"] = 0
            job["opt_current_chapter_chars"] = 0

        # Recalculate BookInfo totals
        info.total_words = sum(ch.word_count for ch in info.chapters)
        info.total_chars = sum(ch.char_count for ch in info.chapters)
        info.estimated_duration_minutes = info.total_words / 150

        total_elapsed = time.time() - start_time
        job["opt_progress_current"] = total_chapters
        job["opt_elapsed_seconds"] = round(total_elapsed)
        job["opt_completed_at"] = time.time()
        job["opt_progress_message"] = "Optimization complete!"
        job["ai_optimized"] = True
        # Segna il job come completato per il recovery voucher all'avvio
        if job.get("payment_type"):
            _mark_paid_opt_done(job_id)

        print(f"[{job_id}] LLM optimization completed in {total_elapsed:.1f}s")
        _log_activity(job_id, job.get("original_filename", ""), "OPT_COMPLETE",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      "", job.get("browser_lang", ""))

        # Re-check auto_generate  -  may have been set mid-optimization via register_opt_email
        auto_generate = job.get("opt_auto_generate", False)
        if auto_generate and job.get("email_registered"):
            # Batch mode: generate .abm snapshot first (so it can be linked from the final email),
            # then proceed directly to TTS generation
            try:
                abm_path, abm_name = _generate_optimized_abm(job_id)
                job["optimized_abm_path"] = abm_path
                job["optimized_abm_name"] = abm_name
            except Exception as e:
                print(f"[{job_id}] Failed to generate .abm snapshot before auto-gen: {e}")
            job["status"] = "optimized"
            voice = job.get("opt_voice", "it-IT-IsabellaNeural")
            rate = job.get("opt_rate", "+0%")
            single_file = job.get("opt_single_file", True)
            print(f"[{job_id}] Auto-generating after optimization (voice: {voice})")
            
            # Filter info if only a subset was optimized
            if selected_chapters:
                from copy import copy
                selected_set = set(selected_chapters)
                filtered = [ch for ch in info.chapters if ch.index in selected_set]
                if filtered:
                    info = copy(info)
                    info.chapters = filtered
                    info.total_words = sum(ch.word_count for ch in filtered)
                    info.total_chars = sum(ch.char_count for ch in filtered)
                    info.estimated_duration_minutes = info.total_words / 150
            
            run_generation(job_id, info, voice, rate, single_file)
        elif job.get("email_registered"):
            # Batch mode, no auto-generate: create .abm and send email
            abm_path, abm_name = _generate_optimized_abm(job_id)
            job["optimized_abm_path"] = abm_path
            job["optimized_abm_name"] = abm_name
            job["status"] = "optimized"
            try:
                _send_optimization_email(job_id)
            except Exception as e:
                print(f"[{job_id}] Optimization email error: {e}")
        else:
            # Interactive mode: just mark as optimized
            job["status"] = "optimized"
            job["last_poll"] = time.time()

    except _CancelledError:
        job["status"] = "cancelled"
        job["opt_progress_message"] = "Optimization cancelled"
        print(f"[{job_id}] LLM optimization cancelled")
        _log_activity(job_id, job.get("original_filename", ""), "OPT_CANCEL",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      "", job.get("browser_lang", ""))
        _refund_job_payment(job_id, job, "cancel")
    except Exception as e:
        job["status"] = "error"
        job["error"] = f"LLM optimization error: {e}"
        import traceback
        traceback.print_exc()
        _refund_job_payment(job_id, job, "error")


def run_generation(job_id, info, voice, rate, single_file):
    job = jobs[job_id]
    job["status"] = "generating"
    job["cancelled"] = False
    job["last_poll"] = time.time()
    work_dir = UPLOAD_DIR / job_id
    work_dir.mkdir(exist_ok=True)
    output_dir = work_dir / "output"
    output_dir.mkdir(exist_ok=True)
    loop = asyncio.new_event_loop()
    start_time = time.time()

    # Determina il motore TTS
    use_google = google_tts is not None and google_tts.is_google_voice(voice)

    try:
        job["progress_message"] = "Preparing..."
        plan = _plan_chunks(info)
        total_chunks = len(plan)
        total_chars = sum(b["chars"] for b in plan)

        # Genera file di silenzio da preporre a ogni capitolo
        silence_path = str(work_dir / "_silence.mp3")
        _generate_silence_mp3(silence_path, CHAPTER_SILENCE_SEC)

        job["progress_current"] = 0
        job["progress_total"] = total_chunks
        job["total_chars"] = total_chars
        job["processed_chars"] = 0
        job["bytes_generated"] = 0
        job["start_time"] = start_time
        job["current_chapter"] = ""
        job["current_chapter_num"] = 0
        job["total_chapters"] = len(info.chapters)

        def _check_cancelled():
            """Controlla se il job è stato cancellato o il client disconnesso."""
            if job.get("cancelled"):
                return True
            # Se l'utente ha registrato email, non controllare heartbeat:
            # il processo deve continuare anche senza browser
            if job.get("email_registered"):
                return False
            # Heartbeat: se nessun client ha chiesto il progresso da 60+ sec,
            # il browser è stato probabilmente chiuso.
            # (60s anziché 15s per tollerare il throttling dei timer di Chrome
            #  quando la tab è in background)
            last_poll = job.get("last_poll", start_time)
            if time.time() - last_poll > 60:
                return True
            return False

        def _update_progress(i, block):
            elapsed = time.time() - start_time
            job["progress_current"] = i
            job["progress_message"] = (
                f"Cap. {block['chapter_index']}/{len(info.chapters)}: "
                f"{block['chapter_title'][:35]}... \u2014 "
                f"chunk {block['chunk_index']+1}/{block['chunks_in_chapter']}"
            )
            job["current_chapter"] = block["chapter_title"]
            job["current_chapter_num"] = block["chapter_index"]
            job["elapsed_seconds"] = round(elapsed)

        if single_file:
            all_parts = []
            m4b_chapters = []
            current_ms = 0
            silence_ms = _get_audio_duration_ms(silence_path) if os.path.exists(silence_path) else 0
            prev_chapter_idx = -1
            failed_chunks = 0
            for i, block in enumerate(plan):
                if _check_cancelled():
                    raise _CancelledError("Job cancelled")
                _update_progress(i, block)

                ch_idx = block["chapter_index"]
                ch_title = block["chapter_title"]

                # New chapter detected
                if ch_idx != prev_chapter_idx:
                    # Silence before chapter
                    if os.path.exists(silence_path):
                        all_parts.append(silence_path)
                        current_ms += silence_ms
                    
                    # Start of new chapter in M4B list
                    m4b_chapters.append({"title": ch_title, "start": current_ms, "end": current_ms})
                    prev_chapter_idx = ch_idx

                part_path = str(work_dir / f"chunk_{i:06d}.mp3")
                if use_google:
                    result = generate_chunk_mp3_google(block["text"], voice, rate, part_path)
                else:
                    result = loop.run_until_complete(generate_chunk_mp3(block["text"], voice, rate, part_path))
                
                if result is not False:
                    all_parts.append(part_path)
                    duration = _get_audio_duration_ms(part_path)
                    current_ms += duration
                    if m4b_chapters:
                        m4b_chapters[-1]["end"] = current_ms
                    if os.path.exists(part_path):
                        job["bytes_generated"] += os.path.getsize(part_path)
                else:
                    failed_chunks += 1

                job["processed_chars"] += block["chars"]

            if m4b_chapters:
                m4b_chapters[-1]["end"] = current_ms

            job["progress_message"] = "Merging audio..."
            safe_name = _safe_filename(info.title) or "audiolibro"
            final_mp3 = str(output_dir / f"{safe_name}.mp3")
            _concatenate_mp3(all_parts, final_mp3)
            
            job["output_files"] = [final_mp3]
            job["output_name"] = f"{safe_name}.mp3"

            # Generate M4B too
            final_m4b = str(output_dir / f"{safe_name}.m4b")
            job["progress_message"] = "Converting to M4B..."
            cover_path = _prepare_m4b_cover_path(job, info.title, info.author, work_dir)
            valid_m4b_ch = [c for c in m4b_chapters if c.get("end", 0) > c.get("start", 0)]
            
            # Retry logic: max 2 attempts
            for attempt in range(1, 3):
                try:
                    if _convert_mp3_to_m4b(final_mp3, final_m4b,
                                           chapters=valid_m4b_ch or None,
                                           title=getattr(info, "title", "Audiolibro"),
                                           author=getattr(info, "author", None),
                                           cover_path=cover_path,
                                           date=getattr(info, "date", None),
                                           language=getattr(info, "language", None),
                                           description=getattr(info, "description", None)):
                        job["output_m4b"] = final_m4b
                        job["m4b_failed"] = False
                        # If user requested M4B, this is the primary output name
                        if single_file:
                            job["output_name"] = f"{safe_name}.m4b"
                        break
                    else:
                        raise Exception("Conversion returned False")
                except Exception as e:
                    print(f"[{job_id}] M4B conversion attempt {attempt} failed: {e}")
                    if attempt == 2:
                        job["m4b_failed"] = True
                        if os.path.exists(final_m4b):
                            try: os.remove(final_m4b)
                            except OSError: pass

            for p in all_parts:
                if os.path.exists(p) and p != silence_path:
                    os.remove(p)
            
            if os.path.exists(final_mp3):
                job["bytes_generated"] = os.path.getsize(final_mp3)
        else:
            mp3_files = []
            m4b_chapters = []
            current_ms = 0
            current_chapter_parts = []
            current_chapter_idx = -1
            failed_chunks = 0
            # Dict for O(1) lookup  -  supports non-contiguous indices (filtered chapters)
            chapter_by_idx = {ch.index: ch for ch in info.chapters}
            # Rinumerazione sequenziale output: il ch.index può essere non
            # contiguo (capitoli deselezionati via UI, o capitoli rimossi
            # manualmente da un .abm). Gli MP3 finali devono comunque partire
            # da 001 e non avere buchi, altrimenti l'ordinamento lessicografico
            # nei player/podcast mostrerebbe "003, 007, 012" invece di 1,2,3.
            output_num_by_idx = {ch.index: pos + 1 for pos, ch in enumerate(info.chapters)}
            for i, block in enumerate(plan):
                if _check_cancelled():
                    raise _CancelledError("Job cancelled")
                _update_progress(i, block)
                if block["chapter_index"] != current_chapter_idx:
                    if current_chapter_parts and current_chapter_idx >= 0:
                        ch = chapter_by_idx[current_chapter_idx]
                        safe_title = _safe_filename(ch.title)[:50] or f"ch_{current_chapter_idx}"
                        out_num = output_num_by_idx.get(current_chapter_idx, current_chapter_idx)
                        mp3_path = str(output_dir / f"{out_num:03d}_{safe_title}.mp3")
                        _concatenate_mp3(current_chapter_parts, mp3_path)
                        mp3_files.append(mp3_path)

                        # Aggiorna timing per capitoli M4B
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

                part_path = str(work_dir / f"chunk_{i:06d}.mp3")
                if use_google:
                    result = generate_chunk_mp3_google(block["text"], voice, rate, part_path)
                else:
                    result = loop.run_until_complete(generate_chunk_mp3(block["text"], voice, rate, part_path))
                if result is False:
                    failed_chunks += 1
                current_chapter_parts.append(part_path)
                job["processed_chars"] += block["chars"]
                if os.path.exists(part_path):
                    job["bytes_generated"] += os.path.getsize(part_path)

            if current_chapter_parts and current_chapter_idx >= 0:
                ch = chapter_by_idx[current_chapter_idx]
                safe_title = _safe_filename(ch.title)[:50] or f"ch_{current_chapter_idx}"
                out_num = output_num_by_idx.get(current_chapter_idx, current_chapter_idx)
                mp3_path = str(output_dir / f"{out_num:03d}_{safe_title}.mp3")
                _concatenate_mp3(current_chapter_parts, mp3_path)
                mp3_files.append(mp3_path)

                # Aggiorna timing per ultimo capitolo M4B
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

            job["progress_message"] = "Creating ZIP..."
            safe_name = _safe_filename(info.title) or "audiolibro"

            # Include book cover in ZIP if available
            _include_cover_in_dir(job, output_dir)

            zip_path = shutil.make_archive(str(work_dir / safe_name), "zip", str(output_dir))
            job["output_files"] = mp3_files
            job["output_name"] = f"{safe_name}.zip"
            job["output_zip"] = zip_path

            # Flag: podcast available (will be built on-demand with user-provided base URL)
            job["podcast_ready"] = True
            job["podcast_info"] = info
            job["podcast_mp3s"] = mp3_files
            job["podcast_safe_name"] = safe_name

        # Cleanup silence file
        if os.path.exists(silence_path):
            os.remove(silence_path)

        # Caratteri Google TTS già pre-allocati in api_generate.
        # Se la prenotazione era leggermente più alta del consumato (raro,
        # solo per arrotondamenti), sistemiamo qui il delta.
        if use_google:
            reserved = job.get("google_tts_reserved", 0)
            consumed = job.get("processed_chars", 0)
            if reserved > consumed:
                google_tts.refund_chars(reserved - consumed)
                print(f"[{job_id}] Google TTS: refunded {reserved - consumed} chars "
                      f"(reserved {reserved}, consumed {consumed})")
            elif consumed > reserved:
                # Caso improbabile: consumato più del prenotato
                google_tts.deduct_chars(consumed - reserved)
                print(f"[{job_id}] Google TTS: extra deduction {consumed - reserved} chars")
            _invalidate_voices_cache()

        total_elapsed = time.time() - start_time
        job["progress_current"] = job["progress_total"]
        job["elapsed_seconds"] = round(total_elapsed)
        job["completed_at"] = time.time()
        job["last_poll"] = time.time()  # Reset heartbeat on completion
        job["failed_chunks"] = failed_chunks
        if failed_chunks > 0:
            job["progress_message"] = f"Done! ({failed_chunks} chunk(s) skipped due to TTS errors)"
            print(f"[{job_id}] Completed with {failed_chunks} failed chunk(s)")
        else:
            job["progress_message"] = "Done!"
        job["status"] = "done"
        _log_activity(job_id, job.get("original_filename", ""), "COMPLETE",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      job.get("voice", ""), job.get("browser_lang", ""))

        # Send email notification if user registered
        if job.get("notify_email"):
            try:
                _send_completion_email(job_id)
            except Exception as e:
                print(f"[{job_id}] Email notification error: {e}")

    except _CancelledError:
        job["status"] = "cancelled"
        job["progress_message"] = "Cancelled"
        # Refund caratteri Google TTS non consumati e forza riconciliazione
        if use_google:
            _google_tts_refund_unused(job_id, job)
        # Cleanup temp files
        try:
            if work_dir.exists():
                shutil.rmtree(str(work_dir), ignore_errors=True)
        except Exception:
            pass
        print(f"[{job_id}] Generation cancelled, resources freed.")
        _log_activity(job_id, job.get("original_filename", ""), "CANCEL",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      job.get("voice", ""), job.get("browser_lang", ""))

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        # Refund caratteri Google TTS non consumati anche in caso di errore
        if use_google:
            try:
                _google_tts_refund_unused(job_id, job)
            except Exception as ref_err:
                print(f"[{job_id}] Refund error: {ref_err}")
        import traceback
        traceback.print_exc()
    finally:
        loop.close()


def _google_tts_refund_unused(job_id, job):
    """Restituisce al budget i caratteri Google TTS prenotati ma non consumati,
    poi forza una riconciliazione con Cloud Monitoring per consolidare il valore reale."""
    if google_tts is None:
        return
    reserved = job.get("google_tts_reserved", 0)
    consumed = job.get("processed_chars", 0)
    if reserved > consumed:
        unused = reserved - consumed
        google_tts.refund_chars(unused)
        print(f"[{job_id}] Google TTS: refunded {unused:,} unused chars "
              f"(reserved {reserved:,}, consumed {consumed:,})")
        _invalidate_voices_cache()
    # Forza riconciliazione immediata (consolida con valore reale Cloud Monitoring,
    # se disponibile). Eseguita in thread separato per non bloccare il cleanup.
    def _do_reconcile():
        try:
            time.sleep(2)  # Piccolo delay per dare tempo all'API di registrare
            google_tts.reconcile_with_cloud_monitoring()
        except Exception as e:
            print(f"[{job_id}] Post-cancel reconcile error: {e}")
    threading.Thread(target=_do_reconcile, daemon=True).start()



CHAPTER_SILENCE_SEC = 3  # secondi di silenzio all'inizio di ogni capitolo


# ----------------------------------------------------------------------
# ROUTES
# ----------------------------------------------------------------------

#  -  -  -  Rotte per lingua (/it/, /en/, /fr/, /es/, /de/, /zh/)  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
# Ogni URL ha HTML pre-renderizzato con meta tag, title, hreflang e canonical
# corretti per quella lingua  -  indicizzabili da Google come pagine distinte.

@app.route("/")
def index():
    """Root: serve la lingua rilevata dall'Accept-Language, senza redirect.
    Il redirect 302 penalizzerebbe il PageRank; meglio rispondere con canonical.
    Usa HTML_ROOT_TEMPLATES: canonical punta a BASE_URL/ (non /{lang}/).
    Questo garantisce che l'URL x-default negli hreflang sia auto-canonicalizzante.
    """
    lang = _detect_lang_from_request()
    resp = app.make_response(HTML_ROOT_TEMPLATES.get(lang, HTML_ROOT_TEMPLATES["en"]))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Vary"] = "Accept-Language"
    return resp

@app.route("/it/")
def index_it():
    return HTML_TEMPLATES["it"], 200, {"Content-Type": "text/html; charset=utf-8"}

@app.route("/en/")
def index_en():
    return HTML_TEMPLATES["en"], 200, {"Content-Type": "text/html; charset=utf-8"}

@app.route("/fr/")
def index_fr():
    return HTML_TEMPLATES["fr"], 200, {"Content-Type": "text/html; charset=utf-8"}

@app.route("/es/")
def index_es():
    return HTML_TEMPLATES["es"], 200, {"Content-Type": "text/html; charset=utf-8"}

@app.route("/de/")
def index_de():
    return HTML_TEMPLATES["de"], 200, {"Content-Type": "text/html; charset=utf-8"}

@app.route("/zh/")
def index_zh():
    return HTML_TEMPLATES["zh"], 200, {"Content-Type": "text/html; charset=utf-8"}


#  -  -  -  sitemap.xml  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
@app.route("/sitemap.xml")
def sitemap():
    """Sitemap con tutte le varianti linguistiche.
    Richiede ABM_BASE_URL configurato per gli URL assoluti (obbligatorio per Google).
    """
    if not BASE_URL:
        return "<!-- sitemap non disponibile: impostare ABM_BASE_URL -->", 200, {
            "Content-Type": "text/xml; charset=utf-8"
        }

    from datetime import date
    today = date.today().isoformat()

    lang_hreflang_map = {
        "it": "it", "en": "en", "fr": "fr",
        "es": "es", "de": "de", "zh": "zh-Hans"
    }

    # Blocco alternates condiviso da tutti gli URL
    alt_lines = []
    for lc, hl in lang_hreflang_map.items():
        alt_lines.append(
            '      <xhtml:link rel="alternate" hreflang="' + hl + '" href="' + BASE_URL + '/' + lc + '/"/>'
        )
    alt_lines.append(
        '      <xhtml:link rel="alternate" hreflang="x-default" href="' + BASE_URL + '/"/>'
    )
    alternates = "\n".join(alt_lines)

    urls = []
    # Root (x-default)
    urls.append(f"""  <url>
    <loc>{BASE_URL}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>1.0</priority>
{alternates}
  </url>""")

    # Una URL per lingua
    for lc in lang_hreflang_map:
        urls.append(f"""  <url>
    <loc>{BASE_URL}/{lc}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
{alternates}
  </url>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
{chr(10).join(urls)}
</urlset>"""
    return xml, 200, {"Content-Type": "application/xml; charset=utf-8"}


#  -  -  -  robots.txt  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
@app.route("/robots.txt")
def robots():
    sitemap_line = f"Sitemap: {BASE_URL}/sitemap.xml" if BASE_URL else ""
    body = f"""User-agent: *
Allow: /
Disallow: /api/
Disallow: /data/
Disallow: /dl/
Disallow: /logs
Disallow: /admin/
{sitemap_line}
""".strip()
    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}


#  -  -  -  Favicon routes (URL-based for search engine compatibility)  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
# Google richiede che le favicon siano servite da URL reali e crawlabili,
# NON inline come data URI. Senza queste route, nei risultati di ricerca
# appare un'icona generica al posto della favicon del sito.

@app.route("/favicon.ico")
def favicon_ico():
    return send_file(get_favicon_ico(), mimetype="image/x-icon",
                     max_age=86400 * 30)

@app.route("/favicon-192.png")
def favicon_png_192():
    return send_file(get_favicon_png_192(), mimetype="image/png",
                     max_age=86400 * 30)

@app.route("/apple-touch-icon.png")
def apple_touch_icon():
    return send_file(get_apple_touch_icon(), mimetype="image/png",
                     max_age=86400 * 30)

@app.route("/favicon.svg")
def favicon_svg():
    return send_file(get_favicon_svg(), mimetype="image/svg+xml",
                     max_age=86400 * 30)


@app.route("/manifest.json")
def web_manifest():
    """Web App Manifest  -  Google lo usa come fonte primaria per le favicon nei risultati di ricerca."""
    manifest = {
        "name": "Audiobook Maker",
        "short_name": "Audiobook Maker",
        "icons": [
            {"src": "/favicon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
            {"src": "/favicon.svg", "type": "image/svg+xml", "sizes": "any"}
        ],
        "display": "standalone",
        "start_url": "/",
        "theme_color": "#c29a6c",
        "background_color": "#1a1a2e"
    }
    return json.dumps(manifest), 200, {
        "Content-Type": "application/manifest+json",
        "Cache-Control": "public, max-age=2592000"
    }


#  -  -  -  Admin log viewer (/logs)  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
# URL: /logs?2026-03  (parametro = anno-mese)
# Non indicizzato (Disallow: /logs in robots.txt consigliato)


def _parse_log_sessions(ym):
    """Parse log file for given YYYY-MM and return (sessions OrderedDict, client_session_count dict)."""
    from datetime import datetime
    from collections import OrderedDict

    log_path = SCRIPT_DIR / f"activity_{ym}.log"
    sessions = OrderedDict()

    if not log_path.exists():
        return sessions, {}

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("#")]
            if len(parts) < 4:
                continue
            sid = parts[0]
            dt_str = parts[1]
            filename = parts[2].strip().strip('"')
            operation = parts[3].strip()
            client_id = parts[4].strip() if len(parts) > 4 else ""
            client_ip = parts[5].strip() if len(parts) > 5 else ""
            voice = parts[6].strip() if len(parts) > 6 else ""
            browser_lang = parts[7].strip() if len(parts) > 7 else ""

            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

            if sid not in sessions:
                sessions[sid] = {
                    "first_dt": dt, "last_dt": dt,
                    "filename": filename, "last_op": operation,
                    "events": [operation],
                    "client_id": client_id, "client_ip": client_ip,
                    "voice": voice, "browser_lang": browser_lang,
                }
            else:
                s = sessions[sid]
                if dt < s["first_dt"]:
                    s["first_dt"] = dt
                if dt >= s["last_dt"]:
                    s["last_dt"] = dt
                    s["last_op"] = operation
                s["filename"] = filename
                s["events"].append(operation)
                if client_id:
                    s["client_id"] = client_id
                if client_ip:
                    s["client_ip"] = client_ip
                if voice:
                    s["voice"] = voice
                if browser_lang:
                    s["browser_lang"] = browser_lang

    client_session_count = {}
    for s in sessions.values():
        cid = s.get("client_id", "")
        if cid:
            client_session_count[cid] = client_session_count.get(cid, 0) + 1

    return sessions, client_session_count


def _session_completed(s):
    """Return True if session reached generation completion (includes download scenarios)."""
    _completed_ops = {"COMPLETE", "DOWNLOAD", "DOWNLOAD_EMAIL",
                      "DOWNLOAD_EMAIL_PODCAST", "DOWNLOAD_PODCAST"}
    return bool(set(s["events"]) & _completed_ops)


def _session_in_progress(s, sid):
    """Return True if session has an active AI optimization or TTS generation.

    Un'attività è considerata "in corso" se:
      - È stato avviato un evento di lavoro (GENERATE = TTS, OPTIMIZE = ottimizzazione AI),
      - Non risulta fra gli eventi una conclusione (COMPLETE / DOWNLOAD* / OPT_COMPLETE),
      - Non risulta un'annullamento (CANCEL / OPT_CANCEL),
      - Il job esiste ancora in memoria con stato attivo (`generating`, `optimizing`,
        `optimized` in attesa di auto-gen, ecc.).
    """
    events = set(s["events"])
    has_work_start = ("GENERATE" in events) or ("OPTIMIZE" in events)
    if not has_work_start:
        return False

    # Terminazioni TTS
    tts_done = bool(events & {"COMPLETE", "DOWNLOAD", "DOWNLOAD_EMAIL",
                              "DOWNLOAD_EMAIL_PODCAST", "DOWNLOAD_PODCAST"})
    tts_cancel = "CANCEL" in events
    # Terminazioni ottimizzazione
    opt_cancel = "OPT_CANCEL" in events

    tts_started = "GENERATE" in events
    opt_started = "OPTIMIZE" in events

    # Un'ottimizzazione ancora in corso: avviata e non cancellata/completata.
    # Nota: OPT_COMPLETE è seguito tipicamente da GENERATE se auto_generate è attivo,
    # quindi non lo consideriamo un terminatore definitivo a livello di sessione.
    opt_live = opt_started and not opt_cancel and "OPT_COMPLETE" not in events
    # Una generazione TTS ancora in corso: avviata e non cancellata/completata.
    tts_live = tts_started and not tts_done and not tts_cancel

    if not (opt_live or tts_live):
        return False

    # Cross-reference con lo stato runtime del job per evitare "zombie" da log.
    job = jobs.get(sid)
    if job:
        st = job.get("status", "")
        active_states = {"generating", "optimizing", "optimized"}
        if st in active_states:
            return True
        # job esistente ma in stato finale  →  non più in corso
        return False
    # Fallback (job non più in memoria): non considerare "in corso" le sessioni
    # storiche  -  ritorna False per evitare falsi positivi dopo un restart del server.
    return False


@app.route("/logs")
def admin_logs():
    if not ADMIN_TOKEN: return "Logs UI disabled.", 404
    token = _admin_auth_from_request()
    if not _admin_auth_ok(token): return _render_admin_gate("Logs Viewer", "/logs"), 200, {"Content-Type": "text/html; charset=utf-8"}
    _log_i18n = {
        "it": {
            "sessions": "Sessioni", "gen_completed": "Gen. completata",
            "in_progress": "In corso", "cancelled": "Cancellati",
            "email_sent": "Email inviate", "unique_clients": "Client unici",
            "recurring": "Ricorrenti", "months": "Mesi",
            "collapse": "Aggrega", "expand": "Mostra tutti",
            "no_activity": "Nessuna attività registrata per",
        },
        "en": {
            "sessions": "Sessions", "gen_completed": "Gen. completed",
            "in_progress": "In progress", "cancelled": "Cancelled",
            "email_sent": "Emails sent", "unique_clients": "Unique clients",
            "recurring": "Returning", "months": "Months",
            "collapse": "Collapse", "expand": "Show all",
            "no_activity": "No activity recorded for",
        },
        "fr": {
            "sessions": "Sessions", "gen_completed": "Gén. terminée",
            "in_progress": "En cours", "cancelled": "Annulées",
            "email_sent": "Emails envoyés", "unique_clients": "Clients uniques",
            "recurring": "Récurrents", "months": "Mois",
            "collapse": "Regrouper", "expand": "Tout afficher",
            "no_activity": "Aucune activité enregistrée pour",
        },
        "de": {
            "sessions": "Sitzungen", "gen_completed": "Gen. abgeschlossen",
            "in_progress": "Laufend", "cancelled": "Abgebrochen",
            "email_sent": "E-Mails gesendet", "unique_clients": "Einzelne Clients",
            "recurring": "Wiederkehrend", "months": "Monate",
            "collapse": "Zusammenklappen", "expand": "Alle anzeigen",
            "no_activity": "Keine Aktivitäten aufgezeichnet für",
        },
        "es": {
            "sessions": "Sesiones", "gen_completed": "Gen. completada",
            "in_progress": "En curso", "cancelled": "Canceladas",
            "email_sent": "Emails enviados", "unique_clients": "Clientes únicos",
            "recurring": "Recurrentes", "months": "Meses",
            "collapse": "Agrupar", "expand": "Mostrar todos",
            "no_activity": "No hay actividad registrada para",
        },
        "zh": {
            "sessions": "会话", "gen_completed": "生�完�",
            "in_progress": "进行中", "cancelled": "已取消",
            "email_sent": "邮件已发送", "unique_clients": "唯一客户",
            "recurring": "常客", "months": "月份",
            "collapse": "收起", "expand": "全部显示",
            "no_activity": "没有活动记录",
        },
    }
    _blang = _get_browser_lang()
    t = _log_i18n.get(_blang, _log_i18n["en"])

    ym = None
    for key in request.args:
        if re.match(r'^\d{4}-\d{2}$', key):
            ym = key
            break
    if not ym:
        ym = datetime.now().strftime("%Y-%m")

    try:
        sessions, client_session_count = _parse_log_sessions(ym)
    except Exception as e:
        return f"Errore lettura log: {e}", 500

    _client_colors = [
        "#38bdf8", "#a78bfa", "#f472b6", "#34d399", "#fbbf24",
        "#fb923c", "#22d3ee", "#c084fc", "#f87171", "#4ade80",
    ]
    _client_color_map = {}
    _color_idx = 0
    for cid, count in client_session_count.items():
        if count >= 2:
            _client_color_map[cid] = _client_colors[_color_idx % len(_client_colors)]
            _color_idx += 1

    total_sessions = len(sessions)
    gen_completed = sum(1 for s in sessions.values() if _session_completed(s))
    gen_in_progress = sum(1 for sid, s in sessions.items() if _session_in_progress(s, sid))
    gen_cancelled = total_sessions - gen_completed - gen_in_progress
    email_sent = sum(1 for s in sessions.values() if "EMAIL_SENT" in s["events"])
    unique_clients = len(set(s.get("client_id", "") for s in sessions.values() if s.get("client_id")))
    returning_clients = sum(1 for c in client_session_count.values() if c >= 2)

    days = defaultdict(list)
    for sid, s in reversed(list(sessions.items())):
        day_key = s["first_dt"].strftime("%Y-%m-%d")
        days[day_key].append((sid, s))

    event_icons = {
        "ANALYZE": "🔍", "GENERATE": "⚙️", "COMPLETE": "✅",
        "DOWNLOAD": "📥", "DOWNLOAD_EMAIL": "📧📥",
        "DOWNLOAD_EMAIL_PODCAST": "🎙️📥", "DOWNLOAD_PODCAST": "🎙️📥",
        "EMAIL_REGISTERED": "📧", "EMAIL_SENT": "📨",
        "EMAIL_FAILED": "❌", "CANCEL": "🚫",
        "RESET_CHAPTERS": "🔄", "EXPORT_ABM": "📦",
    }
    op_colors = {
        "ANALYZE": ("#6b7280", "#f3f4f6"), "GENERATE": ("#2563eb", "#eff6ff"),
        "COMPLETE": ("#16a34a", "#f0fdf4"), "DOWNLOAD": ("#7c3aed", "#f5f3ff"),
        "DOWNLOAD_EMAIL": ("#7c3aed", "#f5f3ff"),
        "DOWNLOAD_EMAIL_PODCAST": ("#7c3aed", "#f5f3ff"),
        "DOWNLOAD_PODCAST": ("#7c3aed", "#f5f3ff"),
        "EMAIL_REGISTERED": ("#0891b2", "#ecfeff"),
        "EMAIL_SENT": ("#0d9488", "#f0fdfa"),
        "EMAIL_FAILED": ("#dc2626", "#fef2f2"),
        "CANCEL": ("#dc2626", "#fef2f2"),
        "RESET_CHAPTERS": ("#f59e0b", "#fffbeb"),
        "EXPORT_ABM": ("#6366f1", "#eef2ff"),
    }

    cards_html = ""
    now = datetime.now()
    for day_key in sorted(days.keys(), reverse=True):
        day_sessions = days[day_key]
        day_count = len(day_sessions)
        try:
            day_dt = datetime.strptime(day_key, "%Y-%m-%d")
            day_label = day_dt.strftime("%d/%m/%Y")
        except ValueError:
            day_label = day_key

        cards_html += f"""<div class="day-group" data-day="{day_key}">
<div class="day-header" onclick="this.parentElement.classList.toggle('collapsed')">
<span class="day-label">{day_label}</span>
<span class="day-count">{day_count}</span>
<span class="day-chevron">›</span>
</div>
<div class="day-cards">
"""
        for sid, s in day_sessions:
            is_progress = _session_in_progress(s, sid)
            is_completed = _session_completed(s)
            has_email = "EMAIL_SENT" in s["events"]
            cid = s.get("client_id", "")
            cid_count = client_session_count.get(cid, 0) if cid else 0
            is_recurring = cid_count >= 2
            is_identified = bool(cid)

            # Determine card status for filtering
            if is_progress:
                card_status = "in_progress"
            elif is_completed:
                card_status = "completed"
            else:
                card_status = "cancelled"

            first = s["first_dt"].strftime("%H:%M")
            last = s["last_dt"].strftime("%H:%M")

            if is_progress:
                delta = now - s["first_dt"]
                total_sec = int(delta.total_seconds())
                elapsed = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}:{total_sec % 60:02d}"
                start_iso = s["first_dt"].strftime("%Y-%m-%dT%H:%M:%S")
                elapsed_html = f'<span class="live-timer" data-start="{start_iso}">{elapsed}</span> ⏱️'
                last = " - "
            else:
                delta = s["last_dt"] - s["first_dt"]
                total_sec = int(delta.total_seconds())
                elapsed = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"
                elapsed_html = elapsed

            title = s["filename"]
            for ext in (".epub", ".txt", ".pdf"):
                if title.lower().endswith(ext):
                    title = title[:-len(ext)]
            display_title = html_mod.escape(title[:80] + ("..." if len(title) > 80 else ""))

            op = s["last_op"]
            fg, bg = op_colors.get(op, ("#6b7280", "#f3f4f6"))
            timeline = "  →  ".join(event_icons.get(e, e) for e in s["events"])

            cip = s.get("client_ip", "")
            cid_short = cid[:8] if cid else " - "
            cid_color = _client_color_map.get(cid, "var(--text-dim)")
            cid_badge = f' <span class="cid-count" style="color:{cid_color}">({cid_count})</span>' if cid_count >= 2 else ""
            cid_style = f'color:{cid_color};font-weight:600' if cid in _client_color_map else 'color:var(--text-dim)'

            voice_raw = s.get("voice", "")
            voice_short = ""
            if voice_raw:
                parts_v = voice_raw.split("-")
                if len(parts_v) >= 3:
                    voice_short = parts_v[-1].replace("Neural", "").replace("Multilingual", "")
                    voice_lang = "-".join(parts_v[:2])
                    voice_short = f'{voice_short} <span class="voice-lang">{voice_lang}</span>'
                else:
                    voice_short = html_mod.escape(voice_raw)

            blang = html_mod.escape(s.get("browser_lang", "") or "")
            blang_display = f'<span class="card-blang">{blang}</span>' if blang else " - "

            card_cls = "card card-in-progress" if is_progress else "card"
            data_attrs = (
                f'data-status="{card_status}" '
                f'data-email="{1 if has_email else 0}" '
                f'data-recurring="{1 if is_recurring else 0}" '
                f'data-identified="{1 if is_identified else 0}"'
            )

            cards_html += f"""<div class="{card_cls}" {data_attrs}>
<div class="card-top">
<span class="card-title" title="{html_mod.escape(s['filename'])}">{display_title}</span>
<span class="badge" style="color:{fg};background:{bg}">{op}</span>
</div>
<div class="card-timeline">{timeline}</div>
<div class="card-meta">
<div class="meta-row"><span class="meta-label">⌚</span><span>{first}  →  {last} ({elapsed_html})</span></div>
<div class="meta-row"><span class="meta-label">🆔</span><code class="sid">{sid}</code></div>
<div class="meta-row"><span class="meta-label">👤</span><code style="{cid_style}">{cid_short}</code>{cid_badge}<span class="card-ip">{cip or ""}</span></div>
<div class="meta-row"><span class="meta-label">🎙️</span><span class="card-voice" title="{html_mod.escape(voice_raw)}">{voice_short or " - "}</span></div>
<div class="meta-row"><span class="meta-label">�</span>{blang_display}</div>
</div>
</div>
"""
        cards_html += "</div></div>\n"

    available_months = []
    try:
        for f in sorted(SCRIPT_DIR.glob("activity_*.log"), reverse=True):
            m = re.search(r'activity_(\d{4}-\d{2})\.log', f.name)
            if m:
                available_months.append(m.group(1))
    except Exception:
        pass

    months_nav = ""
    for m in available_months:
        active_cls = ' class="active"' if m == ym else ""
        months_nav += f'<a href="/logs?{m}"{active_cls}>{m}</a> '

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<link rel="icon" type="image/svg+xml" href="{FAVICON_B64}">
<title>Audiobook Maker  -  Activity Log ({ym})</title>
<style>
:root {{ --bg:#0f172a;--surface:#1e293b;--surface2:#334155;--border:#475569;--text:#e2e8f0;--text-dim:#94a3b8;--accent:#38bdf8;--accent2:#a78bfa;--green:#22c55e;--red:#ef4444;--orange:#f97316; }}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'JetBrains Mono','Fira Code','SF Mono',monospace;background:var(--bg);color:var(--text);line-height:1.5;min-height:100vh}}
.header{{background:var(--surface);border-bottom:1px solid var(--border);padding:16px 20px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
.header h1{{font-size:.9rem;font-weight:600;color:var(--accent);letter-spacing:.5px}}
.header .period{{font-size:1.3rem;font-weight:700;color:var(--text);font-variant-numeric:tabular-nums}}
.header-actions{{margin-left:auto;display:flex;gap:8px}}
.btn{{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:6px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-family:inherit;font-size:.75rem;font-weight:600;cursor:pointer;text-decoration:none;transition:all .15s}}
.btn:hover{{background:var(--border)}}
.btn-accent{{background:var(--accent);color:var(--bg);border-color:var(--accent)}}
.btn-accent:hover{{opacity:.85}}
.btn-toggle{{margin-left:auto;flex-shrink:0}}
.months-nav{{padding:10px 20px;background:var(--surface);border-bottom:1px solid var(--border);display:flex;gap:6px;flex-wrap:wrap;align-items:center}}
.months-nav .label{{color:var(--text-dim);font-size:.7rem;margin-right:6px;text-transform:uppercase;letter-spacing:1px}}
.months-nav a{{color:var(--text-dim);text-decoration:none;padding:4px 10px;border-radius:4px;font-size:.78rem;transition:all .15s}}
.months-nav a:hover{{background:var(--surface2);color:var(--text)}}
.months-nav a.active{{background:var(--accent);color:var(--bg);font-weight:600}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;padding:14px 20px}}
.stat{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 14px;text-align:center;cursor:pointer;transition:all .2s;user-select:none}}
.stat:hover{{background:var(--surface2);transform:translateY(-1px)}}
.stat.active{{border-color:var(--accent);box-shadow:0 0 0 2px rgba(56,189,248,.25)}}
.stat.stat-green.active{{border-color:var(--green);box-shadow:0 0 0 2px rgba(34,197,94,.25)}}
.stat.stat-red.active{{border-color:var(--red);box-shadow:0 0 0 2px rgba(239,68,68,.25)}}
.stat.stat-orange.active{{border-color:var(--orange);box-shadow:0 0 0 2px rgba(249,115,22,.25)}}
.stat .num{{font-size:1.5rem;font-weight:700;color:var(--accent);font-variant-numeric:tabular-nums}}
.stat.stat-green .num{{color:var(--green)}} .stat.stat-red .num{{color:var(--red)}} .stat.stat-orange .num{{color:var(--orange)}}
.stat .lbl{{font-size:.65rem;color:var(--text-dim);text-transform:uppercase;letter-spacing:.8px;margin-top:2px}}
.day-group{{margin:0 12px 6px}}
.day-header{{display:flex;align-items:center;gap:10px;padding:10px 12px;background:var(--surface);border:1px solid var(--border);border-radius:8px;cursor:pointer;user-select:none;margin-top:8px;transition:background .15s}}
.day-header:hover{{background:var(--surface2)}}
.day-label{{font-weight:700;font-size:.85rem;color:var(--accent);font-variant-numeric:tabular-nums}}
.day-count{{background:var(--accent);color:var(--bg);font-size:.68rem;font-weight:700;padding:2px 8px;border-radius:10px}}
.day-chevron{{margin-left:auto;color:var(--text-dim);font-size:.9rem;transition:transform .2s}}
.day-group.collapsed .day-chevron{{transform:rotate(-90deg)}}
.day-group.collapsed .day-cards{{display:none}}
.day-cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:10px;padding:10px 0 4px}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;transition:border-color .15s,box-shadow .15s}}
.card:hover{{border-color:var(--accent);box-shadow:0 0 0 1px rgba(56,189,248,.15)}}
.card-in-progress{{border-color:var(--orange);background:rgba(249,115,22,.06);animation:pulse-border 2s ease-in-out infinite}}
.card-in-progress:hover{{border-color:var(--orange);box-shadow:0 0 0 2px rgba(249,115,22,.3)}}
@keyframes pulse-border{{0%,100%{{border-color:var(--orange);box-shadow:0 0 0 0 rgba(249,115,22,.15)}}50%{{border-color:rgba(249,115,22,.5);box-shadow:0 0 8px 0 rgba(249,115,22,.2)}}}}
.card.card-hidden{{display:none}}
.day-group.day-hidden{{display:none}}
.card-top{{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;margin-bottom:6px}}
.card-title{{font-weight:600;font-size:.82rem;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.62rem;font-weight:700;letter-spacing:.5px;white-space:nowrap;flex-shrink:0}}
.card-timeline{{color:var(--text-dim);font-size:.7rem;margin-bottom:8px;overflow-x:auto;white-space:nowrap;padding-bottom:2px}}
.card-meta{{display:flex;flex-direction:column;gap:4px}}
.meta-row{{display:flex;align-items:center;gap:6px;font-size:.73rem;color:var(--text-dim);min-width:0}}
.meta-label{{flex-shrink:0;width:20px;text-align:center;font-size:.78rem}}
.sid{{color:var(--accent2);font-size:.7rem;background:rgba(167,139,250,.1);padding:1px 5px;border-radius:3px}}
.card-ip{{margin-left:auto;font-size:.68rem;color:var(--text-dim);font-variant-numeric:tabular-nums}}
.card-voice{{color:var(--text);font-size:.72rem}} .voice-lang{{opacity:.5;font-size:.62rem}}
.cid-count{{font-size:.62rem;opacity:.8}}
.card-blang{{font-size:.65rem;background:rgba(167,139,250,.12);color:var(--accent2);padding:1px 6px;border-radius:3px;font-weight:600;text-transform:uppercase}}
.empty{{text-align:center;padding:60px 20px;color:var(--text-dim)}} .empty .icon{{font-size:3rem;margin-bottom:12px}}
@media(max-width:600px){{
.header{{padding:12px 14px;gap:8px}} .header h1{{font-size:.78rem}} .header .period{{font-size:1.1rem}}
.stats{{grid-template-columns:repeat(4,1fr);gap:6px;padding:10px 12px}} .stat{{padding:8px 6px}} .stat .num{{font-size:1.2rem}} .stat .lbl{{font-size:.58rem}}
.months-nav{{padding:8px 12px;gap:4px}} .day-group{{margin:0 8px 4px}} .day-cards{{grid-template-columns:1fr;gap:8px;padding:8px 0 2px}} .card{{padding:12px}} .btn{{padding:6px 10px;font-size:.68rem}}
.header-actions{{margin-left:0;width:100%;justify-content:flex-end}}
}}
@media(max-width:380px){{ .stats{{grid-template-columns:repeat(2,1fr)}} }}
</style>
</head>
<body>

<div class="header">
    <h1>🎧 ACTIVITY LOG</h1>
    <span class="period">{ym}</span>
    <div class="header-actions">
        <a class="btn btn-accent" href="/logs/export?{ym}" title="Export Excel">📁 Excel</a>
    </div>
</div>

<div class='months-nav'>{"<span class='label'>" + t["months"] + ":</span>" + months_nav if months_nav else ""}<button class="btn btn-toggle" id="btnToggleDays" onclick="toggleAllDays()">{t["collapse"]}</button></div>

<div class="stats">
    <div class="stat active" data-filter="all" onclick="filterCards('all',this)"><div class="num">{total_sessions}</div><div class="lbl">{t["sessions"]}</div></div>
    <div class="stat stat-green" data-filter="completed" onclick="filterCards('completed',this)"><div class="num">{gen_completed}</div><div class="lbl">{t["gen_completed"]}</div></div>
    <div class="stat stat-orange" data-filter="in_progress" onclick="filterCards('in_progress',this)"><div class="num">{gen_in_progress}</div><div class="lbl">{t["in_progress"]}</div></div>
    <div class="stat stat-red" data-filter="cancelled" onclick="filterCards('cancelled',this)"><div class="num">{gen_cancelled}</div><div class="lbl">{t["cancelled"]}</div></div>
    <div class="stat" data-filter="email" onclick="filterCards('email',this)"><div class="num">{email_sent}</div><div class="lbl">{t["email_sent"]}</div></div>
    <div class="stat" data-filter="identified" onclick="filterCards('identified',this)"><div class="num">{unique_clients}</div><div class="lbl">{t["unique_clients"]}</div></div>
    <div class="stat" data-filter="recurring" onclick="filterCards('recurring',this)"><div class="num">{returning_clients}</div><div class="lbl">{t["recurring"]}</div></div>
</div>

<div class="cards-container">
{cards_html if cards_html else "<div class='empty'><div class='icon'>📮</div><p>" + t["no_activity"] + " <strong>" + ym + "</strong></p></div>"}
</div>

<script>
function toggleAllDays() {{
    const groups = document.querySelectorAll('.day-group');
    const btn = document.getElementById('btnToggleDays');
    const allCollapsed = [...groups].every(g => g.classList.contains('collapsed'));
    groups.forEach(g => {{
        if (allCollapsed) g.classList.remove('collapsed');
        else g.classList.add('collapsed');
    }});
    btn.textContent = allCollapsed ? '{t["collapse"]}' : '{t["expand"]}';
}}

function filterCards(filter, el) {{
    // Toggle active state on stat buttons
    document.querySelectorAll('.stat').forEach(s => s.classList.remove('active'));
    el.classList.add('active');

    const cards = document.querySelectorAll('.card');
    cards.forEach(card => {{
        let show = false;
        if (filter === 'all') {{
            show = true;
        }} else if (filter === 'completed' || filter === 'in_progress' || filter === 'cancelled') {{
            show = card.dataset.status === filter;
        }} else if (filter === 'email') {{
            show = card.dataset.email === '1';
        }} else if (filter === 'identified') {{
            show = card.dataset.identified === '1';
        }} else if (filter === 'recurring') {{
            show = card.dataset.recurring === '1';
        }}
        card.classList.toggle('card-hidden', !show);
    }});

    // Hide day groups with no visible cards
    document.querySelectorAll('.day-group').forEach(group => {{
        const visibleCards = group.querySelectorAll('.card:not(.card-hidden)');
        group.classList.toggle('day-hidden', visibleCards.length === 0);
        // Update day count badge
        const countBadge = group.querySelector('.day-count');
        if (countBadge) {{
            countBadge.textContent = visibleCards.length;
        }}
    }});
}}

// Live timer for in-progress sessions
function updateLiveTimers() {{
    const timers = document.querySelectorAll('.live-timer');
    const now = new Date();
    timers.forEach(timer => {{
        const startStr = timer.dataset.start;
        if (!startStr) return;
        const start = new Date(startStr);
        const diff = Math.max(0, Math.floor((now - start) / 1000));
        const h = String(Math.floor(diff / 3600)).padStart(2, '0');
        const m = String(Math.floor((diff % 3600) / 60)).padStart(2, '0');
        const s = String(diff % 60).padStart(2, '0');
        timer.textContent = h + ':' + m + ':' + s;
    }});
}}

// Update timers every second
if (document.querySelectorAll('.live-timer').length > 0) {{
    setInterval(updateLiveTimers, 1000);
}}
</script>

</body>
</html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/logs/export")
def admin_logs_export():
    """Export activity log as Excel (.xlsx) file."""
    from datetime import datetime
    import io, csv

    ym = None
    for key in request.args:
        if re.match(r'^\d{4}-\d{2}$', key):
            ym = key
            break
    if not ym:
        ym = datetime.now().strftime("%Y-%m")

    try:
        sessions, client_session_count = _parse_log_sessions(ym)
    except Exception as e:
        return f"Errore lettura log: {e}", 500

    output = io.StringIO()
    writer = csv.writer(output, delimiter="#")
    writer.writerow([
        "Session ID", "Date Start", "Date End", "Duration (min)",
        "Filename", "Last Status", "Events", "Client ID", "Client IP",
        "Voice", "Browser Lang", "Completed", "In Progress", "Recurring Client"
    ])
    for sid, s in sessions.items():
        delta = s["last_dt"] - s["first_dt"]
        duration_min = round(delta.total_seconds() / 60, 1)
        completed = "Yes" if _session_completed(s) else "No"
        in_progress = "Yes" if _session_in_progress(s, sid) else "No"
        cid = s.get("client_id", "")
        recurring = "Yes" if client_session_count.get(cid, 0) >= 2 else "No"
        writer.writerow([
            sid, s["first_dt"].strftime("%Y-%m-%d %H:%M:%S"),
            s["last_dt"].strftime("%Y-%m-%d %H:%M:%S"), duration_min,
            s["filename"], s["last_op"], "  →  ".join(s["events"]),
            cid, s.get("client_ip", ""), s.get("voice", ""),
            s.get("browser_lang", ""), completed, in_progress, recurring,
        ])

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = f"Log {ym}"

        total_s = len(sessions)
        gen_c = sum(1 for s_ in sessions.values() if _session_completed(s_))
        gen_p = sum(1 for sid_, s_ in sessions.items() if _session_in_progress(s_, sid_))
        gen_x = total_s - gen_c - gen_p
        em_s = sum(1 for s_ in sessions.values() if "EMAIL_SENT" in s_["events"])
        uniq = len(set(s_.get("client_id", "") for s_ in sessions.values() if s_.get("client_id")))
        ret = sum(1 for c in client_session_count.values() if c >= 2)

        ws.merge_cells("A1:B1")
        ws["A1"] = f"Audiobook Maker  -  Activity Log {ym}"
        ws["A1"].font = Font(name="Arial", bold=True, color="38bdf8", size=14)
        summary = [("Sessioni", total_s), ("Gen. completata", gen_c), ("In corso", gen_p),
                   ("Cancellati", gen_x), ("Email inviate", em_s), ("Client unici", uniq),
                   ("Ricorrenti", ret)]
        for i, (lbl, val) in enumerate(summary):
            ws.cell(row=2, column=1 + i * 2, value=lbl).font = Font(name="Arial", color="94a3b8", size=10)
            ws.cell(row=2, column=2 + i * 2, value=val).font = Font(name="Arial", bold=True, color="e2e8f0", size=12)

        headers = ["Session ID", "Data inizio", "Data fine", "Durata (min)", "Contenuto",
                   "Ultimo stato", "Timeline eventi", "Client ID", "IP", "Voce",
                   "Lingua browser", "Completato", "In corso", "Client ricorrente"]
        hdr_fill = PatternFill("solid", fgColor="334155")
        hdr_font = Font(name="Arial", bold=True, color="e2e8f0", size=10)
        for col_idx, h in enumerate(headers, 1):
            c = ws.cell(row=4, column=col_idx, value=h)
            c.font = hdr_font; c.fill = hdr_fill; c.alignment = Alignment(horizontal="center")

        data_font = Font(name="Arial", size=10, color="e2e8f0")
        for row_idx, (sid, s) in enumerate(reversed(list(sessions.items())), 5):
            delta = s["last_dt"] - s["first_dt"]
            row_data = [sid, s["first_dt"].strftime("%Y-%m-%d %H:%M:%S"),
                        s["last_dt"].strftime("%Y-%m-%d %H:%M:%S"),
                        round(delta.total_seconds() / 60, 1), s["filename"], s["last_op"],
                        "  →  ".join(s["events"]), s.get("client_id", ""), s.get("client_ip", ""),
                        s.get("voice", ""), s.get("browser_lang", ""),
                        "✅" if _session_completed(s) else "❌",
                        "✅" if _session_in_progress(s, sid) else "",
                        "✅" if client_session_count.get(s.get("client_id", ""), 0) >= 2 else ""]
            for col_idx, val in enumerate(row_data, 1):
                c = ws.cell(row=row_idx, column=col_idx, value=val)
                c.font = data_font
                if row_idx % 2 == 0:
                    c.fill = PatternFill("solid", fgColor="1e293b")

        col_widths = [12, 20, 20, 12, 45, 18, 50, 14, 16, 25, 10, 12, 10, 14]
        for i, w in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.auto_filter.ref = f"A4:N{4 + len(sessions)}"

        xlsx_io = io.BytesIO()
        wb.save(xlsx_io)
        xlsx_io.seek(0)
        return Response(xlsx_io.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="activity_log_{ym}.xlsx"'})
    except ImportError:
        csv_bytes = output.getvalue().encode("utf-8-sig")
        return Response(csv_bytes, mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="activity_log_{ym}.csv"'})


#  -  -  -  Admin voucher web UI (/admin/vouchers)  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
# Protetta da token ABM_ADMIN_TOKEN. Se il token non è configurato, endpoint 404.
# Il token viene inviato via header X-Admin-Token (dalle API) o nel form HTML.
# Confronto a tempo costante tramite hmac.compare_digest.

def _render_admin_gate(title, target_url):
    """Render a password gate for admin pages."""
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Auth - {title}</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f3f4f6;color:#1f2937}}
.card{{background:#fff;padding:2rem;border-radius:12px;box-shadow:0 10px 15px -3px rgba(0,0,0,0.1);width:100%;max-width:360px}}
h2{{margin:0 0 1.5rem;font-size:1.5rem;text-align:center}}
.field{{margin-bottom:1rem}}
label{{display:block;font-size:.875rem;font-weight:600;margin-bottom:.375rem}}
input[type=password]{{width:100%;padding:.625rem;border:1px solid #d1d5db;border-radius:.375rem;box-sizing:border-box}}
.btn{{width:100%;padding:.75rem;background:#2563eb;color:#fff;border:none;border-radius:.375rem;font-weight:600;cursor:pointer}}
.btn:hover{{background:#1d4ed8}}
.hint{{font-size:.75rem;color:#6b7280;margin-top:1rem;text-align:center}}
</style>
<script>
// Interceptor to add token to all fetches/XHR if we were not already in a reload loop
(function(){{
    const tok = sessionStorage.getItem('abm_admin_token') || localStorage.getItem('abm_admin_token');
    if(tok && !window.location.search.includes('token=')){{
        // If we have a token but the server still showed us this gate, 
        // it means the page load didn't include the token.
        // We redirect once adding the token to the URL as a fallback for the main page load.
        window.location.href = window.location.pathname + '?token=' + encodeURIComponent(tok);
    }}
}})();

function doLogin(){{
    const tok = document.getElementById('pw').value;
    const remember = document.getElementById('rem').checked;
    if(!tok) return;
    sessionStorage.setItem('abm_admin_token', tok);
    if(remember){{
        localStorage.setItem('abm_admin_token', tok);
        localStorage.setItem('abm_admin_expiry', (Date.now() + 30 * 86400000).toString());
    }}
    window.location.href = window.location.pathname + '?token=' + encodeURIComponent(tok);
}}
</script>
</head><body>
<div class="card">
    <h2>Admin Access</h2>
    <div class="field">
        <label for="pw">Admin Token</label>
        <input type="password" id="pw" placeholder="Enter token..." onkeydown="if(event.key==='Enter')doLogin()">
    </div>
    <div class="field" style="display:flex;align-items:center;gap:.5rem">
        <input type="checkbox" id="rem">
        <label for="rem" style="margin:0;font-weight:400">Rimani connesso (30 giorni)</label>
    </div>
    <button class="btn" onclick="doLogin()">Entra</button>
    <div class="hint">Autenticazione richiesta per accedere a questa risorsa.</div>
</div>
</body></html>"""


def _admin_auth_ok(provided):
    """Costante-time check del token admin."""
    import hmac
    if not ADMIN_TOKEN or not provided:
        return False
    return hmac.compare_digest(str(provided), ADMIN_TOKEN)


def _admin_auth_from_request():
    """Estrae il token da header X-Admin-Token, form 'token' o query 'token'."""
    tok = request.headers.get("X-Admin-Token", "")
    if not tok:
        tok = (request.form.get("token") if request.method == "POST" else "") or request.args.get("token", "")
    return tok


@app.route("/admin/vouchers", methods=["GET"])
def admin_vouchers_page():
    if not ADMIN_TOKEN: return ("Admin voucher UI disabled.", 404, {"Content-Type": "text/plain; charset=utf-8"})
    token = _admin_auth_from_request()
    if not _admin_auth_ok(token): return _render_admin_gate("Voucher Admin", "/admin/vouchers"), 200, {"Content-Type": "text/html; charset=utf-8"}
    html = r"""<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Admin  -  Voucher</title>
<style>
  :root{--bg:#0f172a;--panel:#1e293b;--ink:#e2e8f0;--muted:#94a3b8;--accent:#8b5cf6;--ok:#10b981;--err:#ef4444;--warn:#f59e0b;}
  *{box-sizing:border-box}
  body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--ink);padding:20px;max-width:1200px;margin:0 auto}
  h1{margin:0 0 20px;font-size:1.5rem;display:flex;align-items:center;gap:10px}
  h1 .lock{font-size:1.2rem}
  .panel{background:var(--panel);border-radius:10px;padding:20px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,.2)}
  .panel h2{margin:0 0 14px;font-size:1.1rem;color:var(--accent)}
  label{display:block;font-size:.85rem;color:var(--muted);margin:8px 0 4px}
  input,select,textarea{width:100%;padding:9px 12px;background:#0f172a;border:1px solid #334155;color:var(--ink);border-radius:6px;font-size:.95rem;font-family:inherit}
  input:focus,select:focus,textarea:focus{outline:none;border-color:var(--accent)}
  button{padding:10px 20px;background:var(--accent);color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:600;font-size:.95rem}
  button:hover{filter:brightness(1.1)}
  button.secondary{background:#334155}
  button.danger{background:var(--err)}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
  @media(max-width:600px){.row,.row3{grid-template-columns:1fr}}
  .msg{padding:10px 14px;border-radius:6px;margin:12px 0;font-size:.9rem}
  .msg.ok{background:rgba(16,185,129,.15);color:var(--ok);border:1px solid var(--ok)}
  .msg.err{background:rgba(239,68,68,.15);color:var(--err);border:1px solid var(--err)}
  table{width:100%;border-collapse:collapse;font-size:.85rem}
  th{text-align:left;padding:8px;border-bottom:2px solid #334155;color:var(--muted);font-weight:500}
  td{padding:8px;border-bottom:1px solid #1e293b;vertical-align:top}
  tr:hover{background:rgba(139,92,246,.05)}
  code{font-family:ui-monospace,monospace;background:#0f172a;padding:2px 6px;border-radius:3px;font-size:.85em}
  .badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.75rem;font-weight:600}
  .badge.promo{background:rgba(139,92,246,.2);color:#c4b5fd}
  .badge.gift{background:rgba(245,158,11,.2);color:#fbbf24}
  .badge.refund{background:rgba(148,163,184,.2);color:var(--muted)}
  .badge.ACTIVE{background:rgba(16,185,129,.2);color:var(--ok)}
  .badge.PARTIAL{background:rgba(245,158,11,.2);color:var(--warn)}
  .badge.USED{background:rgba(148,163,184,.2);color:var(--muted)}
  .badge.EXPIRED{background:rgba(239,68,68,.2);color:var(--err)}
  .btn-sm{padding:4px 10px;font-size:.8rem}
  .toolbar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;align-items:flex-end}
  .toolbar > div{flex:1;min-width:150px}
  #tokenGate{max-width:420px;margin:80px auto}
  .hint{font-size:.8rem;color:var(--muted);margin-top:4px}
</style>
</head><body>

<div id="tokenGate" class="panel" style="display:none">
  <h1><span class="lock">&#x1F512;</span> Admin Voucher</h1>
  <label>Admin token</label>
  <input id="tokenInput" type="password" autocomplete="off" placeholder="ABM_ADMIN_TOKEN">
  <div class="hint">Il token viene memorizzato solo in questa scheda del browser (sessionStorage).</div>
  <div style="margin-top:14px"><button onclick="saveToken()">Sblocca</button></div>
  <div id="tokenMsg"></div>
</div>

<div id="app" style="display:none">
  <h1><span class="lock">&#x1F512;</span> Admin Voucher <button class="secondary btn-sm" style="margin-left:auto" onclick="logout()">Logout</button></h1>

  <div class="panel">
    <h2>Crea nuovo voucher</h2>
    <div class="row">
      <div><label>Email destinatario *</label><input id="cEmail" type="email" placeholder="user@example.com"></div>
      <div><label>Tipo</label>
        <select id="cKind">
          <option value="promo">promo (promozionale)</option>
          <option value="gift">gift (regalo)</option>
          <option value="refund">refund (rimborso)</option>
        </select>
      </div>
    </div>
    <div class="row3">
      <div><label>Importo (EUR) *</label><input id="cAmount" type="number" step="0.01" min="0.01" placeholder="2.00"></div>
      <div><label>Validità (giorni)</label><input id="cDays" type="number" min="1" value="180"></div>
      <div><label>&nbsp;</label><button onclick="createVoucher()" style="width:100%">Crea voucher</button></div>
    </div>
    <label>Nota (causale interna)</label>
    <textarea id="cNote" rows="2" placeholder="Es: campagna lancio, influencer X, compenso collaboratore..."></textarea>
    <div id="createMsg"></div>
  </div>

  <div class="panel">
    <h2>Voucher esistenti</h2>
    <div class="toolbar">
      <div><label>Filtra email</label><input id="fEmail" placeholder="contiene..." oninput="renderList()"></div>
      <div><label>Filtra tipo</label>
        <select id="fKind" onchange="renderList()">
          <option value="">tutti</option><option value="promo">promo</option><option value="gift">gift</option><option value="refund">refund</option>
        </select>
      </div>
      <div><label>Stato</label>
        <select id="fStatus" onchange="renderList()">
          <option value="">tutti</option><option value="ACTIVE">attivi</option><option value="PARTIAL">parziali</option><option value="USED">usati</option><option value="EXPIRED">scaduti</option>
        </select>
      </div>
      <div style="flex:0"><button class="secondary" onclick="loadList()">&#x21BB; Ricarica</button></div>
    </div>
    <div style="overflow-x:auto">
      <table id="tbl">
        <thead><tr>
          <th>Codice</th><th>Tipo</th><th>Saldo / Iniziale</th><th>Email</th><th>Creato</th><th>Scade</th><th>Stato</th><th>Nota</th><th></th>
        </tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
    <div id="listMsg"></div>
  </div>
</div>

<script>
var TK=sessionStorage.getItem('abm_admin_tok')||'';
var VOUCHERS=[];

function show(el){document.getElementById(el).style.display=''}
function hide(el){document.getElementById(el).style.display='none'}
function msg(id,txt,cls){var e=document.getElementById(id);e.innerHTML='<div class="msg '+cls+'">'+txt+'</div>';setTimeout(function(){e.innerHTML=''},5000)}

async function api(path,opts){
  opts=opts||{};
  opts.headers=opts.headers||{};
  opts.headers['X-Admin-Token']=TK;
  if(opts.body&&typeof opts.body==='object'){opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(opts.body)}
  var r=await fetch(path,opts);
  var j=await r.json().catch(function(){return{}});
  if(!r.ok)throw new Error(j.error||('HTTP '+r.status));
  return j;
}

function saveToken(){
  var t=document.getElementById('tokenInput').value.trim();
  if(!t){document.getElementById('tokenMsg').innerHTML='<div class="msg err">Token richiesto</div>';return}
  TK=t;sessionStorage.setItem('abm_admin_tok',t);
  tryEnter();
}

function logout(){TK='';sessionStorage.removeItem('abm_admin_tok');location.reload()}

async function tryEnter(){
  try{
    await loadList();
    hide('tokenGate');show('app');
  }catch(e){
    TK='';sessionStorage.removeItem('abm_admin_tok');
    show('tokenGate');hide('app');
    document.getElementById('tokenMsg').innerHTML='<div class="msg err">Token non valido: '+e.message+'</div>';
  }
}

async function loadList(){
  var j=await api('/admin/api/vouchers');
  VOUCHERS=j.vouchers||[];
  renderList();
}

function fmtTs(ts){if(!ts)return'-';var d=new Date(ts*1000);return d.toLocaleString('it-IT',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}

function statusOf(v){
  var rem=(v.remaining_eur!=null)?v.remaining_eur:(v.used?0:v.amount_eur);
  if(rem<0.01)return'USED';
  if((v.expires_at||0)*1000<Date.now())return'EXPIRED';
  if(rem<(v.amount_eur||0)-0.01)return'PARTIAL';
  return'ACTIVE';
}

function escapeHtml(s){return(s||'').replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}

function renderList(){
  var fe=(document.getElementById('fEmail').value||'').toLowerCase();
  var fk=document.getElementById('fKind').value;
  var fs=document.getElementById('fStatus').value;
  var rows=VOUCHERS.filter(function(v){
    if(fe&&(v.email||'').toLowerCase().indexOf(fe)<0)return false;
    if(fk&&(v.kind||'refund')!==fk)return false;
    if(fs&&statusOf(v)!==fs)return false;
    return true;
  }).sort(function(a,b){return(b.created_at||0)-(a.created_at||0)});
  var tb=document.getElementById('tbody');
  if(!rows.length){tb.innerHTML='<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:20px">Nessun voucher</td></tr>';return}
  tb.innerHTML=rows.map(function(v){
    var st=statusOf(v);var k=v.kind||'refund';
    var rem=(v.remaining_eur!=null)?v.remaining_eur:(v.used?0:(v.amount_eur||0));
    var tot=v.amount_eur||0;
    var balCell='<strong>'+rem.toFixed(2)+'</strong> / '+tot.toFixed(2);
    if(v.uses&&v.uses.length){balCell+=' <span style="color:var(--muted);font-size:.8em">('+v.uses.length+' us'+(v.uses.length===1?'o':'i')+')</span>';}
    var btn=(rem<0.01)?'':('<button class="danger btn-sm" onclick="revokeVoucher(\''+v.code+'\')">Revoca</button>');
    return '<tr>'+
      '<td><code>'+escapeHtml(v.code)+'</code></td>'+
      '<td><span class="badge '+k+'">'+k+'</span></td>'+
      '<td>'+balCell+'</td>'+
      '<td>'+escapeHtml(v.email||'')+'</td>'+
      '<td>'+fmtTs(v.created_at)+'</td>'+
      '<td>'+fmtTs(v.expires_at)+'</td>'+
      '<td><span class="badge '+st+'">'+st+'</span></td>'+
      '<td style="max-width:240px;font-size:.8em;color:var(--muted)">'+escapeHtml(v.note||'')+'</td>'+
      '<td>'+btn+'</td>'+
    '</tr>';
  }).join('');
}

async function createVoucher(){
  var email=document.getElementById('cEmail').value.trim();
  var amount=parseFloat(document.getElementById('cAmount').value);
  var days=parseInt(document.getElementById('cDays').value||'180');
  var kind=document.getElementById('cKind').value;
  var note=document.getElementById('cNote').value.trim();
  if(!email||!amount||amount<=0){msg('createMsg','Email e importo > 0 obbligatori','err');return}
  try{
    var j=await api('/admin/api/vouchers',{method:'POST',body:{email:email,amount_eur:amount,days:days,kind:kind,note:note}});
    msg('createMsg','Creato <code>'+j.code+'</code> per '+escapeHtml(email)+' ('+j.amount_eur.toFixed(2)+' EUR)','ok');
    document.getElementById('cEmail').value='';document.getElementById('cAmount').value='';document.getElementById('cNote').value='';
    await loadList();
  }catch(e){msg('createMsg','Errore: '+e.message,'err')}
}

async function revokeVoucher(code){
  if(!confirm('Revocare il voucher '+code+' ?'))return;
  var reason=prompt('Motivo (opzionale):','')||'';
  try{
    await api('/admin/api/vouchers/'+encodeURIComponent(code)+'/revoke',{method:'POST',body:{reason:reason}});
    msg('listMsg','Voucher '+code+' revocato','ok');
    await loadList();
  }catch(e){msg('listMsg','Errore: '+e.message,'err')}
}

// bootstrap
if(TK){tryEnter()}else{show('tokenGate')}
</script>
</body></html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8",
                       "X-Robots-Tag": "noindex, nofollow"}


@app.route("/admin/api/vouchers", methods=["GET", "POST"])
def admin_api_vouchers():
    """GET: elenca voucher. POST: crea nuovo voucher.

    Autenticazione via header X-Admin-Token (confronto costante-time).
    """
    if not ADMIN_TOKEN:
        return jsonify({"error": "Admin UI disabled"}), 404
    if not _admin_auth_ok(_admin_auth_from_request()):
        time.sleep(0.5)  # rallenta brute-force
        return jsonify({"error": "Unauthorized"}), 401

    ip = _get_client_ip()

    if request.method == "GET":
        items = []
        for code, v in _vouchers.items():
            items.append({
                "code": code,
                "email": v.get("email", ""),
                "amount_eur": v.get("amount_eur", 0),
                "remaining_eur": _voucher_remaining(v),
                "base_amount_eur": v.get("base_amount_eur", 0),
                "created_at": v.get("created_at"),
                "expires_at": v.get("expires_at"),
                "used": bool(v.get("used")),
                "used_at": v.get("used_at"),
                "uses": v.get("uses", []),
                "kind": v.get("kind", "refund"),
                "note": v.get("note", ""),
                "created_by": v.get("created_by", ""),
                "origin_order_id": v.get("origin_order_id"),
                "revoked": bool(v.get("revoked")),
            })
        return jsonify({"vouchers": items, "count": len(items)})

    # POST  →  create
    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    try:
        amount = float(data.get("amount_eur") or 0)
    except (TypeError, ValueError):
        amount = 0
    try:
        days = int(data.get("days") or 180)
    except (TypeError, ValueError):
        days = 180
    kind = (data.get("kind") or "promo").strip().lower()
    note = (data.get("note") or "").strip()
    if not email or "@" not in email:
        return jsonify({"error": "email required"}), 400
    if amount <= 0:
        return jsonify({"error": "amount must be > 0"}), 400
    if days <= 0 or days > 3650:
        return jsonify({"error": "days out of range (1..3650)"}), 400
    if kind not in ("promo", "gift", "refund"):
        return jsonify({"error": "invalid kind"}), 400

    # Codice con prefisso a seconda del tipo
    prefix = "PROMO-" if kind == "promo" else ("GIFT-" if kind == "gift" else "")
    # _generate_voucher_code dà core XXXX-XXXX-XXXX; per prefisso lo componiamo manualmente
    import secrets as _sec
    _alpha = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    custom_code = None
    if prefix:
        for _ in range(20):
            core = "-".join("".join(_sec.choice(_alpha) for _ in range(4)) for _ in range(3))
            cand = prefix + core
            if cand not in _vouchers:
                custom_code = cand
                break
        if not custom_code:
            return jsonify({"error": "code generation failed"}), 500

    code, bonus_amount = _create_voucher(
        email, amount,
        kind=kind,
        note=note,
        created_by="admin",
        expiry_days=days,
        apply_bonus=False,       # promo/gift: importo nominale, niente +10%
        code=custom_code,
    )
    _log_activity("", "", f"ADMIN_VOUCHER_CREATE:{kind}", "", ip, code[:8] + "…", email)
    print(f"[admin] voucher created via UI: {code} kind={kind} email={email} amount={amount:.2f} days={days} ip={ip}")
    return jsonify({
        "code": code,
        "amount_eur": bonus_amount,
        "expires_at": _vouchers[code].get("expires_at"),
        "kind": kind,
    })


@app.route("/admin/api/vouchers/<code>/revoke", methods=["POST"])
def admin_api_voucher_revoke(code):
    """Revoca (marca usato) un voucher."""
    if not ADMIN_TOKEN:
        return jsonify({"error": "Admin UI disabled"}), 404
    if not _admin_auth_ok(_admin_auth_from_request()):
        time.sleep(0.5)
        return jsonify({"error": "Unauthorized"}), 401
    code = (code or "").strip().upper()
    if code not in _vouchers:
        return jsonify({"error": "Not found"}), 404
    v = _vouchers[code]
    reason = ((request.json or {}).get("reason") or "").strip()[:200]
    v["used"] = True
    v["used_at"] = time.time()
    v["remaining_eur"] = 0.0
    v["revoked"] = True
    v["revoke_reason"] = reason or "admin revoke"
    _save_vouchers()
    _log_activity("", "", "ADMIN_VOUCHER_REVOKE", "", _get_client_ip(), code[:8] + "…", reason[:40])
    print(f"[admin] voucher revoked via UI: {code} reason={reason!r}")
    return jsonify({"ok": True, "code": code})


@app.route("/api/voices")
def api_voices():
    try:
        voices = get_voices()
        # Includi info budget Google TTS come chiave speciale _google_tts
        if google_tts is not None and google_tts.is_available():
            used, remaining, limit = google_tts.get_usage()
            voices["_google_tts"] = {
                "available": remaining > 0,
                "chars_remaining": remaining,
                "chars_limit": limit,
            }
        return jsonify(voices)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/google_tts_status")
def api_admin_google_tts_status():
    """Endpoint admin: stato dettagliato Google TTS (consumo locale + cloud).
    Forza una riconciliazione on-demand se ?reconcile=1."""
    if google_tts is None:
        return jsonify({"error": "google_tts module not loaded"}), 503
    if not google_tts.is_available():
        return jsonify({"available": False, "reason": "credentials missing or SDK not installed"}), 200

    used, remaining, limit = google_tts.get_usage()
    response = {
        "available": True,
        "local": {
            "chars_used": used,
            "chars_remaining": remaining,
            "chars_limit": limit,
            "percent_used": round(100.0 * used / limit, 2) if limit else 0,
        },
        "monitoring": google_tts.get_reconcile_status(),
    }

    # Riconciliazione on-demand
    if request.args.get("reconcile") == "1":
        result = google_tts.reconcile_with_cloud_monitoring()
        response["reconcile_result"] = result

    # Diagnostica metriche Cloud Monitoring (per capire quale filtro usare)
    if request.args.get("diagnose") == "1":
        if hasattr(google_tts, "diagnose_monitoring"):
            response["diagnose"] = google_tts.diagnose_monitoring()
        else:
            response["diagnose"] = {"error": "diagnose_monitoring not available"}

    return jsonify(response)


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    if "epub" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["epub"]
    fname_lower = file.filename.lower()
    is_txt = fname_lower.endswith(".txt")
    is_epub = fname_lower.endswith(".epub")
    is_pdf = fname_lower.endswith(".pdf")
    is_abm = fname_lower.endswith(".abm")
    if not is_epub and not is_txt and not is_pdf and not is_abm:
        return jsonify({"error": "File must be .epub, .pdf, .txt or .abm"}), 400
    if is_pdf and parse_pdf is None:
        return jsonify({"error": "PDF support not available. Install pymupdf: pip install pymupdf"}), 400

    # Sanitize filename for disk storage (Security: prevent Path Traversal)
    from werkzeug.utils import secure_filename
    safe_name = secure_filename(file.filename)
    if not safe_name:
        # Fallback if secure_filename results in empty string (e.g. only non-ascii chars)
        safe_name = str(uuid.uuid4())[:8] + "_" + fname_lower

    job_id = str(uuid.uuid4())[:8]
    work_dir = UPLOAD_DIR / job_id
    work_dir.mkdir(exist_ok=True)
    file_path = work_dir / safe_name
    file.save(str(file_path))

    abm_cover_info = None  # cover data extracted from .abm file
    try:
        if is_abm:
            info, abm_cover_info = parse_abm(str(file_path))
        elif is_txt:
            info = parse_txt(str(file_path))
        elif is_pdf:
            info = parse_pdf(str(file_path))
        else:
            info = parse_epub(str(file_path))
    except Exception as e:
        label = "ABM" if is_abm else ("TXT" if is_txt else ("PDF" if is_pdf else "EPUB"))
        return jsonify({"error": f"{label} parse error: {e}"}), 400

    if not info.chapters:
        return jsonify({"error": "No content found."}), 400

    jobs[job_id] = {"status": "analyzed", "epub_path": str(file_path), "info": info,
                     "last_poll": time.time(), "original_filename": file.filename,
                     "client_id": _get_client_id(), "client_ip": _get_client_ip(),
                     "browser_lang": _get_browser_lang()}

    # Extract cover thumbnail for preview (EPUB or ABM; PDF/TXT have no embedded cover)
    has_cover = False
    if is_abm and abm_cover_info:
        # Cover from .abm archive
        cover_data = abm_cover_info["data"]
        cover_filename = abm_cover_info["filename"]
        is_png = cover_filename.lower().endswith(".png")
        ext = ".png" if is_png else ".jpg"
        mime = "image/png" if is_png else "image/jpeg"
        cover_out = str(work_dir / ("cover_thumb" + ext))
        with open(cover_out, "wb") as cf:
            cf.write(cover_data)
        has_cover = True
        jobs[job_id]["cover_thumb"] = cover_out
        jobs[job_id]["cover_mime"] = mime
    elif is_epub:
        cover_path, cover_mime = _extract_cover_for_preview(str(file_path), str(work_dir))
        if cover_path and os.path.exists(cover_path):
            has_cover = True
            jobs[job_id]["cover_thumb"] = cover_path
            jobs[job_id]["cover_mime"] = cover_mime

    _log_activity(job_id, file.filename, "ANALYZE",
                  jobs[job_id]["client_id"], jobs[job_id]["client_ip"],
                  browser_lang=jobs[job_id].get("browser_lang", ""))

    chapters = []
    for ch in info.chapters:
        chapters.append({
            "index": ch.index, "title": ch.title,
            "words": ch.word_count, "chars": ch.char_count,
            "estimated_minutes": round(ch.word_count / 150, 1),
        })

    #  -  -  Preview text  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
    # EPUB: salta il front matter e usa un capitolo interno con contenuto narrativo reale.
    # TXT:  usa il primo contenuto disponibile.
    # Lunghezza target: 200-300 caratteri, troncata a fine frase.
    def _pick_preview_text(chapters_list, is_txt_file):
        from epub_to_tts import is_content_chapter as _icc
        if not chapters_list:
            return ""
        if is_txt_file:
            for ch in chapters_list:
                raw = (ch.text or "").strip()
                if len(raw) >= 150:
                    return raw
            return ""
        # EPUB: filtra front matter con la stessa euristica usata in epub_to_tts
        valid = [ch for ch in chapters_list
                 if _icc(ch.text or "", ch.title or "") and (ch.word_count or 0) >= 80]
        if not valid:
            for ch in chapters_list:
                raw = (ch.text or "").strip()
                if len(raw) >= 150:
                    return raw
            return ""
        # Secondo capitolo valido (più probabile contenuto narrativo, non introduzione)
        target = valid[1] if len(valid) > 1 else valid[0]
        return (target.text or "").strip()

    def _trim_preview(text, min_chars=400, max_chars=600):
        """Tronca tra min e max caratteri a fine frase, oppure all'ultimo spazio."""
        import re as _re
        text = _re.sub(r'\s+', ' ', text).strip()
        if len(text) <= max_chars:
            return text
        window = text[min_chars:max_chars]
        m = _re.search(r'[.!?]["""»\)\s]', window)
        cut = (min_chars + m.start() + 1) if m else text.rfind(' ', min_chars, max_chars)
        if cut <= 0:
            cut = max_chars
        return text[:cut].rstrip()

    raw_preview = _pick_preview_text(info.chapters, is_txt or is_pdf or is_abm)
    preview_text = _trim_preview(raw_preview) if raw_preview else ""
    # Store for /api/preview_audio
    jobs[job_id]["preview_text"] = preview_text
    # ----------------------------------------------------------------------

    # Detect if .abm was already AI-optimized
    abm_ai_optimized = False
    if is_abm:
        try:
            import zipfile
            with zipfile.ZipFile(str(file_path), "r") as zf:
                m = json.loads(zf.read("manifest.json").decode("utf-8"))
                abm_ai_optimized = m.get("ai_optimized", False)
        except Exception:
            pass
    if abm_ai_optimized:
        jobs[job_id]["ai_optimized"] = True

    return jsonify({
        "job_id": job_id, "title": info.title, "author": info.author,
        "language": info.language,
        "file_type": "abm" if is_abm else ("txt" if is_txt else ("pdf" if is_pdf else "epub")),
        "has_cover": has_cover,
        "total_chapters": len(info.chapters), "total_words": info.total_words,
        "total_chars": info.total_chars,
        "estimated_minutes": round(info.estimated_duration_minutes, 1),
        "chapters": chapters,
        "preview_text": preview_text,
        "llm_available": _llm_available(),
        "ai_optimized": abm_ai_optimized,
    })


@app.route("/api/preview_audio/<job_id>")
def api_preview_audio(job_id):
    """Serve l'MP3 di anteprima come endpoint GET.
    Il browser può usare l'URL direttamente come audio.src  -  nessun problema di autoplay policy.
    Il timeout è gestito da concurrent.futures (funziona sempre, a differenza di asyncio.wait_for).
    """
    if not job_id or job_id not in jobs:
        return jsonify({"error": "Job non trovato"}), 404

    preview_text = jobs[job_id].get("preview_text", "")
    if not preview_text:
        return jsonify({"error": "Nessun testo di anteprima disponibile"}), 400

    voice = request.args.get("voice", "it-IT-IsabellaNeural")
    rate  = request.args.get("rate",  "+0%")

    work_dir = UPLOAD_DIR / job_id
    work_dir.mkdir(exist_ok=True)
    preview_path = work_dir / "preview.mp3"
    cache_key_path = work_dir / "preview.key"
    current_key = f"{voice}|{rate}"

    # Riusa il file se voce e velocità non sono cambiate
    if preview_path.exists() and cache_key_path.exists():
        if cache_key_path.read_text(encoding="utf-8").strip() == current_key:
            return send_file(str(preview_path), mimetype="audio/mpeg",
                             as_attachment=False, download_name="preview.mp3",
                             conditional=True)

    # Genera l'MP3 in un thread separato con timeout reale di 30 secondi.
    # concurrent.futures.Future.result(timeout=) interrompe l'attesa indipendentemente
    # da asyncio  -  risolve il caso in cui edge-tts si blocca sulla connessione TCP.
    use_google_preview = google_tts is not None and google_tts.is_google_voice(voice)

    def _generate():
        if use_google_preview:
            google_tts.synthesize(preview_text, voice, rate, str(preview_path))
            # Deduce i caratteri dell'anteprima dal budget
            google_tts.deduct_chars(len(preview_text))
        else:
            loop = asyncio.new_event_loop()
            try:
                async def _run():
                    communicate = edge_tts.Communicate(
                        text=preview_text, voice=voice, rate=rate
                    )
                    await communicate.save(str(preview_path))
                loop.run_until_complete(_run())
            finally:
                loop.close()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            ex.submit(_generate).result(timeout=30)
    except concurrent.futures.TimeoutError:
        return jsonify({"error": "Timeout: il servizio TTS non ha risposto in 30 secondi."}), 504
    except Exception as e:
        return jsonify({"error": f"Errore generazione anteprima: {e}"}), 500

    if not preview_path.exists():
        return jsonify({"error": "File MP3 non generato."}), 500

    try:
        cache_key_path.write_text(current_key, encoding="utf-8")
    except Exception:
        pass

    return send_file(str(preview_path), mimetype="audio/mpeg",
                     as_attachment=False, download_name="preview.mp3",
                     conditional=True)

@app.route("/api/cover/<job_id>")
def api_cover(job_id):
    """Serve the extracted cover thumbnail for preview."""
    if job_id not in jobs:
        return "", 404
    job = jobs[job_id]
    cover_path = job.get("cover_thumb")
    if not cover_path or not os.path.exists(cover_path):
        return "", 404
    mime = job.get("cover_mime", "image/jpeg")
    return send_file(cover_path, mimetype=mime)


@app.route("/api/export_abm/<job_id>")
def api_export_abm(job_id):
    """Export cleaned text as .abm project file (ZIP with manifest + chapters + cover)."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    info = job.get("info")
    if not info or not info.chapters:
        return jsonify({"error": "No book data available"}), 400

    import zipfile
    import io
    from datetime import datetime, timezone

    buf = io.BytesIO()
    safe_title = _safe_filename(info.title) or "project"

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Build chapter files and manifest entries
        chapters_manifest = []
        for ch in info.chapters:
            ch_safe = _safe_filename(ch.title)[:50] or f"ch_{ch.index}"
            ch_filename = f"{ch.index:03d}_{ch_safe}.txt"
            zf.writestr(f"chapters/{ch_filename}", ch.text)
            chapters_manifest.append({
                "index": ch.index,
                "filename": ch_filename,
                "title": ch.title,
                "word_count": ch.word_count,
            })

        # Cover
        has_cover = False
        cover_file = ""
        cover_path = job.get("cover_thumb")
        if cover_path and os.path.exists(cover_path):
            cover_ext = ".png" if cover_path.endswith(".png") else ".jpg"
            cover_file = f"cover{cover_ext}"
            with open(cover_path, "rb") as cf:
                zf.writestr(cover_file, cf.read())
            has_cover = True

        # Manifest
        manifest = {
            "format": "audiobook-maker-project",
            "format_version": "1.0",
            "title": info.title,
            "author": getattr(info, "author", ""),
            "language": getattr(info, "language", ""),
            "has_cover": has_cover,
            "cover_file": cover_file,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "original_filename": job.get("original_filename", ""),
            "ai_optimized": bool(job.get("ai_optimized")),
            "chapters": chapters_manifest,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    buf.seek(0)
    suffix = "_optimized" if job.get("ai_optimized") else ""
    download_name = f"{safe_title}{suffix}.abm"

    _log_activity(job_id, job.get("original_filename", ""), "EXPORT_ABM",
                  job.get("client_id", ""), job.get("client_ip", ""),
                  browser_lang=job.get("browser_lang", ""))

    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=download_name)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.json
    job_id = data.get("job_id")
    voice = data.get("voice", "it-IT-IsabellaNeural")
    rate = data.get("rate", "+0%")
    single_file = data.get("single_file", True)
    selected_chapters = data.get("selected_chapters")  # list of chapter indices, or None

    if job_id not in jobs:
        return jsonify({"error": "Session expired. Re-upload file."}), 400
    job = jobs[job_id]
    if job["status"] not in ("analyzed", "optimized"):
        return jsonify({"error": "Generation already running or completed."}), 400

    #  -  -  Concurrent generation limit per client  -  - 
    client_id = job.get("client_id", "")
    client_ip = job.get("client_ip", "")
    if client_id and MAX_CONCURRENT_PER_CLIENT > 0:
        active = _active_generating_for_client(client_id)
        if active >= MAX_CONCURRENT_PER_CLIENT:
            return jsonify({
                "error": f"Concurrent generation limit reached ({MAX_CONCURRENT_PER_CLIENT}).",
                "error_code": "concurrent_limit",
                "max": MAX_CONCURRENT_PER_CLIENT,
                "active": active,
            }), 429

    # Save voice in job for logging
    job["voice"] = voice

    info = job["info"]

    # Filter chapters if a subset was selected
    if selected_chapters:
        selected_set = set(selected_chapters)
        filtered = [ch for ch in info.chapters if ch.index in selected_set]
        if not filtered:
            return jsonify({"error": "No chapters selected."}), 400
        # Create a lightweight copy of info with filtered chapters
        info = copy(info)
        info.chapters = filtered
        info.total_words = sum(ch.word_count for ch in filtered)
        info.estimated_duration_minutes = info.total_words / 150

    #  -  -  Pre-allocazione atomica budget Google Cloud TTS  -  - 
    # Verifica E deduce immediatamente i caratteri richiesti, così conversioni
    # parallele non possono passare lo stesso check. Il refund della parte
    # non consumata avviene in run_generation in caso di errore/cancellazione.
    if google_tts is not None and google_tts.is_google_voice(voice):
        total_chars_needed = sum(ch.char_count for ch in info.chapters)
        ok, remaining_after = google_tts.reserve_chars(total_chars_needed)
        if not ok:
            return jsonify({
                "error": f"Google TTS monthly limit: {remaining_after:,} chars remaining, "
                         f"but this book needs {total_chars_needed:,} chars.",
                "error_code": "google_tts_budget",
                "chars_needed": total_chars_needed,
                "chars_remaining": remaining_after,
            }), 429
        # Memorizza i caratteri prenotati nel job per il refund
        job["google_tts_reserved"] = total_chars_needed
        print(f"[{job_id}] Google TTS: reserved {total_chars_needed:,} chars "
              f"(remaining: {remaining_after:,})")
        # Invalida la cache voci: se il budget si avvicina allo zero, le voci
        # potrebbero scomparire al prossimo /api/voices
        _invalidate_voices_cache()

    thread = threading.Thread(
        target=run_generation, args=(job_id, info, voice, rate, single_file), daemon=True
    )
    thread.start()
    _log_activity(job_id, job.get("original_filename", ""), "GENERATE",
                  client_id, client_ip, voice,
                  browser_lang=job.get("browser_lang", ""))
    _admin_notify_generation(job_id, info, voice, job.get("original_filename", ""))
    return jsonify({"status": "started"})


@app.route("/api/progress/<job_id>")
def api_progress(job_id):
    def stream():
        while True:
            if job_id not in jobs:
                yield f"data: {json.dumps({'status': 'error', 'error': 'Job not found'})}\n\n"
                break
            job = jobs[job_id]
            # Heartbeat: segna che un client sta ascoltando
            job["last_poll"] = time.time()
            payload = {
                "status": job.get("status", "unknown"),
                "progress_current": job.get("progress_current", 0),
                "progress_total": job.get("progress_total", 0),
                "progress_message": job.get("progress_message", ""),
                "current_chapter": job.get("current_chapter", ""),
                "current_chapter_num": job.get("current_chapter_num", 0),
                "total_chapters": job.get("total_chapters", 0),
                "elapsed_seconds": job.get("elapsed_seconds", 0),
                "bytes_generated": job.get("bytes_generated", 0),
                "processed_chars": job.get("processed_chars", 0),
                "total_chars": job.get("total_chars", 0),
            }
            if job.get("status") == "error":
                payload["error"] = job.get("error", "Unknown error")
                yield f"data: {json.dumps(payload)}\n\n"
                break
            if job.get("status") == "cancelled":
                payload["status"] = "cancelled"
                yield f"data: {json.dumps(payload)}\n\n"
                break
            if job.get("status") == "done":
                payload["output_name"] = job.get("output_name", "output")
                payload["has_podcast"] = job.get("podcast_ready", False)
                # Se output_m4b non è impostato, prova a trovare il file su disco
                # (può succedere se il client riconnette dopo che la generazione è già terminata)
                if not job.get("output_m4b"):
                    _work = UPLOAD_DIR / job_id
                    _m4bs = list(_work.glob("*.m4b")) + list((_work / "output").glob("*.m4b"))
                    if _m4bs:
                        job["output_m4b"] = str(_m4bs[0])
                payload["output_m4b"] = bool(job.get("output_m4b"))
                payload["failed_chunks"] = job.get("failed_chunks", 0)
                yield f"data: {json.dumps(payload)}\n\n"
                break
            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(1)

    return Response(
        stream_with_context(stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/cancel/<job_id>", methods=["POST"])
def api_cancel(job_id):
    """Cancella un job in corso."""
    if job_id in jobs:
        job = jobs[job_id]
        force = request.args.get("force") == "1"
        # Se l'utente ha registrato email per notifica, ignora cancel da beforeunload
        # ma permetti cancel esplicito (pulsante con force=1)
        if job.get("email_registered") and not force:
            print(f"[{job_id}] Cancel ignored  -  email registered for background processing")
            return jsonify({"status": "ignored_email_registered"})
        job["cancelled"] = True
        return jsonify({"status": "cancelling"})
    return jsonify({"status": "not_found"}), 404


@app.route("/api/heartbeat/<job_id>", methods=["POST"])
def api_heartbeat(job_id):
    """Keep-alive: il client segnala che è ancora sulla pagina."""
    if job_id in jobs:
        jobs[job_id]["last_poll"] = time.time()
        return "", 204
    return "", 404


@app.route("/api/reset_to_chapters/<job_id>", methods=["POST"])
def api_reset_to_chapters(job_id):
    """Reset a completed job back to 'analyzed' so the user can select different chapters."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    if job.get("status") != "done":
        return jsonify({"error": "Job is not in completed state"}), 400

    # Verify that the original book info is still available
    if not job.get("info") or not job["info"].chapters:
        return jsonify({"error": "Book data no longer available. Please re-upload the file."}), 400

    # Clean up generated output files to free disk space
    work_dir = UPLOAD_DIR / job_id
    output_dir = work_dir / "output"
    if output_dir.exists():
        shutil.rmtree(str(output_dir), ignore_errors=True)
    # Remove zip if present
    for key in ("output_zip",):
        fpath = job.get(key, "")
        if fpath and os.path.exists(fpath):
            try:
                os.remove(fpath)
            except OSError:
                pass

    # Reset job state
    job["status"] = "analyzed"
    job["last_poll"] = time.time()
    # Clear output-related keys (incluso output_m4b per evitare bottone M4B obsoleto)
    for key in ("output_files", "output_name", "output_zip", "output_file",
                "output_m4b",
                "podcast_ready", "podcast_safe_name", "podcast_mp3s",
                "progress_current", "progress_total", "progress_message",
                "processed_chars", "total_chars", "bytes_generated",
                "start_time", "elapsed_seconds", "current_chapter",
                "current_chapter_num", "total_chapters",
                "downloaded_at", "email_sent_at", "email_registered",
                "failed_chunks", "cancelled"):
        job.pop(key, None)
    # Keep: info, epub_path, cover_thumb, cover_mime, original_filename, preview_text,
    #        client_id, client_ip, voice (so preview still works)

    _log_activity(job_id, job.get("original_filename", ""), "RESET_CHAPTERS",
                  job.get("client_id", ""), job.get("client_ip", ""),
                  job.get("voice", ""), job.get("browser_lang", ""))

    return jsonify({"status": "ok"})


@app.route("/api/register_email", methods=["POST"])
def api_register_email():
    """Register email for job completion notification."""
    import re
    data = request.json or {}
    job_id = data.get("job_id", "")
    email = (data.get("email") or "").strip().lower()
    download_type = data.get("download_type", "audio")  # "audio" or "podcast"
    base_url = (data.get("base_url") or "").strip()

    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    if not email or not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email):
        return jsonify({"error": "Invalid email address"}), 400

    if download_type == "podcast" and not base_url:
        return jsonify({"error": "base_url required for podcast"}), 400

    if not _smtp_available():
        return jsonify({"error": "Email service not configured on this server"}), 503

    job = jobs[job_id]
    job["notify_email"] = email
    job["notify_download_type"] = download_type
    job["notify_base_url"] = base_url
    job["notify_lang"] = data.get("lang", "en")
    # Keep job alive indefinitely while generating (disable heartbeat-based cleanup)
    job["email_registered"] = True

    print(f"[{job_id}] Email notification registered: {email} (type: {download_type})")
    _log_activity(job_id, job.get("original_filename", ""), "EMAIL_REGISTERED",
                  job.get("client_id", ""), job.get("client_ip", ""),
                  job.get("voice", ""), job.get("browser_lang", ""))

    return jsonify({"status": "registered", "email": email})


@app.route("/api/email_available")
def api_email_available():
    """Check if email notification is available (SMTP configured)."""
    return jsonify({"available": _smtp_available()})


# ----------------------------------------------------------------------
# LLM TEXT OPTIMIZATION API
# ----------------------------------------------------------------------

@app.route("/api/llm_available")
def api_llm_available():
    """Check if LLM text optimization is available (DeepSeek configured)."""
    return jsonify({
        "available": _llm_available(),
        "paypal_available": _paypal_available(),
        "paypal_client_id": PAYPAL_CLIENT_ID if _paypal_available() else "",
        "paypal_mode": PAYPAL_MODE,
        "rate_eur_per_mchar": LLM_RATE_EUR_PER_MCHAR,
        "free_threshold_eur": LLM_FREE_THRESHOLD_EUR,
        "voucher_bonus_percent": VOUCHER_BONUS_PERCENT,
        "voucher_expiry_days": VOUCHER_EXPIRY_DAYS,
    })


def _parse_selected_chapters(raw_data):
    """Utility ultra-robusta per estrarre indici interi da qualsiasi input."""
    if raw_data is None: return []
    indices = []
    if isinstance(raw_data, str) and "," in raw_data:
        items = raw_data.split(",")
    elif isinstance(raw_data, list):
        items = raw_data
    else:
        items = [raw_data]
    for item in items:
        if item is None: continue
        if isinstance(item, (int, float)):
            indices.append(int(item))
        elif isinstance(item, str):
            parts = item.replace("[", "").replace("]", "").split(",")
            for p in parts:
                p = p.strip()
                if p.isdigit(): indices.append(int(p))
    return sorted(list(set(indices)))

@app.route("/api/optimize_estimate/<job_id>")
def api_optimize_estimate(job_id):
    if job_id not in jobs: return jsonify({"error": "Job not found"}), 404
    job = jobs[job_id]; info = job.get("info")
    if not info or not info.chapters: return jsonify({"error": "No book data"}), 400
    raw_sel = request.args.getlist("selected_chapters") + request.args.getlist("selected_chapters[]")
    selected_indices = _parse_selected_chapters(raw_sel)
    if raw_sel:
        total_chars = sum(ch.char_count for ch in info.chapters if ch.index in selected_indices)
    else:
        total_chars = sum(ch.char_count for ch in info.chapters)
    cost = _estimate_llm_cost_eur(total_chars)
    return jsonify({
        "chars": total_chars, "cost_eur": cost,
        "requires_payment": cost > LLM_FREE_THRESHOLD_EUR,
        "free_threshold_eur": LLM_FREE_THRESHOLD_EUR,
        "rate_eur_per_mchar": LLM_RATE_EUR_PER_MCHAR,
    })


@app.route("/api/paypal_create_order", methods=["POST"])
def api_paypal_create_order():
    if not _paypal_available(): return jsonify({"error": "PayPal not configured"}), 503
    data = request.json or {}; job_id = data.get("job_id", "")
    if job_id not in jobs: return jsonify({"error": "Job not found"}), 404
    job = jobs[job_id]; info = job.get("info")
    if not info: return jsonify({"error": "No book data"}), 400
    selected_chapters = _parse_selected_chapters(data.get("selected_chapters"))
    if selected_chapters:
        total_chars = sum(ch.char_count for ch in info.chapters if ch.index in selected_chapters)
    else:
        total_chars = sum(ch.char_count for ch in info.chapters)
    cost = _estimate_llm_cost_eur(total_chars)
    if cost <= LLM_FREE_THRESHOLD_EUR:
        return jsonify({"error": "Payment not required for this job"}), 400

    book_title = getattr(info, "title", "") or "Audiobook"
    description = f"AI text optimization  -  {book_title[:60]}"
    try:
        order = _paypal_create_order(cost, description, custom_id=job_id)
    except Exception as e:
        print(f"[paypal] create_order failed: {e}")
        return jsonify({"error": f"PayPal error: {e}"}), 500

    # Diagnostic: log links/payee info to help troubleshoot sandbox issues
    try:
        pu = (order.get("purchase_units") or [{}])[0]
        payee = pu.get("payee", {})
        print(f"[paypal] order created: id={order.get('id')} status={order.get('status')} "
              f"amount={pu.get('amount',{}).get('value')} {pu.get('amount',{}).get('currency_code')} "
              f"payee_email={payee.get('email_address')} payee_id={payee.get('merchant_id')}")
    except Exception:
        pass

    return jsonify({
        "order_id": order.get("id"),
        "amount_eur": cost,
        "status": order.get("status"),
    })


@app.route("/api/paypal_debug_order/<order_id>", methods=["GET"])
def api_paypal_debug_order(order_id):
    """Diagnostic: fetch order from PayPal to inspect payee/status/etc."""
    import requests
    if not _paypal_available():
        return jsonify({"error": "PayPal not configured"}), 503
    try:
        token = _paypal_get_access_token()
        r = requests.get(
            f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        return jsonify({"status_code": r.status_code, "body": r.json()}), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/paypal_capture_order", methods=["POST"])
def api_paypal_capture_order():
    """Capture an approved PayPal order. Returns payment_token on success."""
    if not _paypal_available():
        return jsonify({"error": "PayPal not configured"}), 503
    data = request.json or {}
    order_id = (data.get("order_id") or "").strip()
    job_id = (data.get("job_id") or "").strip()
    if not order_id:
        return jsonify({"error": "Missing order_id"}), 400

    # Idempotency: if already captured, return existing token
    if order_id in _payments:
        pay = _payments[order_id]
        return jsonify({
            "payment_token": order_id,
            "amount_eur": pay.get("amount_eur", 0),
            "email": pay.get("email", ""),
            "already_captured": True,
        })

    try:
        captured = _paypal_capture_order(order_id)
    except Exception as e:
        print(f"[paypal] capture_order failed: {e}")
        return jsonify({"error": f"PayPal capture error: {e}"}), 500

    # Extract payment details from capture response
    purchase_units = captured.get("purchase_units", [])
    if not purchase_units:
        return jsonify({"error": "Invalid capture response"}), 500
    pu = purchase_units[0]
    captures = pu.get("payments", {}).get("captures", [])
    if not captures or captures[0].get("status") not in ("COMPLETED", "PENDING"):
        return jsonify({"error": "Payment not completed"}), 400
    cap = captures[0]
    amount_eur = float(cap.get("amount", {}).get("value", "0"))
    payer = captured.get("payer", {})
    email = (payer.get("email_address") or "").lower().strip()

    _payments[order_id] = {
        "order_id": order_id,
        "amount_eur": amount_eur,
        "email": email,
        "job_id": job_id,
        "captured_at": time.time(),
        "used": False,
        "used_at": None,
        "capture_id": cap.get("id", ""),
    }
    _save_payments()

    _log_activity(job_id, jobs.get(job_id, {}).get("original_filename", ""),
                  "PAYMENT_CAPTURED", "", "", "", "")

    # Send receipt email (non-blocking best-effort)
    if email and _smtp_available():
        try:
            _send_payment_receipt_email(order_id, email, amount_eur, jobs.get(job_id, {}))
        except Exception as e:
            print(f"[paypal] receipt email failed: {e}")

    return jsonify({
        "payment_token": order_id,
        "amount_eur": amount_eur,
        "email": email,
    })


@app.route("/api/voucher_validate", methods=["POST"])
def api_voucher_validate():
    """Validate a voucher code + email. Returns payment_token if valid.

    Protetto da rate limit per IP (5/min, 30/ora) e lockout per email dopo N fallimenti.
    Ogni tentativo viene loggato come VOUCHER_ATTEMPT.
    """
    data = request.json or {}
    code = (data.get("code") or "").strip().upper()
    email = (data.get("email") or "").strip().lower()
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()

    #  -  Rate limit check  - 
    allowed, retry_after, reason = _voucher_rl_check(ip, email)
    if not allowed:
        _log_activity("", "", f"VOUCHER_ATTEMPT_BLOCKED:{reason}", "", ip, "", "")
        resp = jsonify({"error": "Too many attempts. Please try later.", "retry_after": retry_after})
        resp.status_code = 429
        resp.headers["Retry-After"] = str(retry_after)
        return resp

    #  -  Validation logic  - 
    outcome = "OK"
    status = 200
    body = None
    if not code or not email:
        outcome, status, body = "MISSING_FIELDS", 400, {"error": "Code and email required"}
    elif code not in _vouchers:
        outcome, status, body = "NOT_FOUND", 404, {"error": "Voucher not found"}
    else:
        v = _vouchers[code]
        remaining = _voucher_remaining(v)
        if v.get("expires_at", 0) < time.time():
            outcome, status, body = "EXPIRED", 400, {"error": "Voucher expired"}
        elif v.get("email", "").lower() != email:
            outcome, status, body = "EMAIL_MISMATCH", 400, {"error": "Email does not match voucher"}
        elif remaining < 0.01:
            outcome, status, body = "USED", 400, {"error": "Voucher fully used"}
        else:
            # Saldo residuo: l'UI lo usa come "amount_eur" spendibile.
            body = {
                "payment_token": code,
                "amount_eur": remaining,
                "remaining_eur": remaining,
                "original_amount_eur": round(float(v.get("amount_eur", 0) or 0), 2),
                "expires_at": v.get("expires_at"),
            }

    success = (outcome == "OK")
    _voucher_rl_record_result(email, success)
    # Log in forma strutturata (usiamo i campi esistenti: voice=code masked, browser_lang=outcome)
    code_masked = (code[:4] + "…") if code else ""
    _log_activity("", "", "VOUCHER_ATTEMPT", "", ip, code_masked, outcome)
    return jsonify(body), status


def _send_payment_receipt_email(order_id, email, amount_eur, job):
    """Send payment receipt email to buyer."""
    book_title = ""
    info = job.get("info")
    if info:
        book_title = getattr(info, "title", "") or ""
    lang = job.get("browser_lang", "en")[:2] if job else "en"
    subj_map = {
        "it": f"Ricevuta pagamento Audiobook Maker  -  {amount_eur:.2f} EUR",
        "en": f"Audiobook Maker payment receipt  -  EUR {amount_eur:.2f}",
        "fr": f"Reçu de paiement Audiobook Maker  -  {amount_eur:.2f} EUR",
        "es": f"Recibo de pago Audiobook Maker  -  {amount_eur:.2f} EUR",
        "de": f"Zahlungsbeleg Audiobook Maker  -  {amount_eur:.2f} EUR",
        "zh": f"Audiobook Maker 支付收据  -  {amount_eur:.2f} EUR",
    }
    subject = subj_map.get(lang, subj_map["en"])
    body_map = {
        "it": ("Grazie per il tuo pagamento.",
               f"Importo: <strong>{amount_eur:.2f} EUR</strong><br>ID transazione: <code>{order_id}</code>"
               f"<br>Progetto: <strong>{book_title}</strong>",
               "Il pagamento copre l'ottimizzazione AI del testo per la sintesi vocale. "
               "Conserva questa email come ricevuta. Per fatturazione contattaci.",
               "In caso di fallimento dell'ottimizzazione riceverai un buono di valore maggiorato del "
               f"{VOUCHER_BONUS_PERCENT}% riutilizzabile entro {VOUCHER_EXPIRY_DAYS} giorni."),
        "en": ("Thank you for your payment.",
               f"Amount: <strong>EUR {amount_eur:.2f}</strong><br>Transaction ID: <code>{order_id}</code>"
               f"<br>Project: <strong>{book_title}</strong>",
               "This payment covers AI text optimization for speech synthesis. "
               "Keep this email as receipt. Contact us for invoicing.",
               f"If optimization fails, you will receive a voucher worth {VOUCHER_BONUS_PERCENT}% more, "
               f"valid for {VOUCHER_EXPIRY_DAYS} days."),
    }
    heading, details, info_txt, refund = body_map.get(lang, body_map["en"])
    html_body = f"""<div style="font-family:system-ui,-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <h2 style="color:#2c3e50">&#x1F4B3; {heading}</h2>
      <div style="padding:16px;background:#f0f5ff;border-radius:8px;margin:16px 0">
        <p style="margin:0">{details}</p>
      </div>
      <p>{info_txt}</p>
      <p style="font-size:.9em;color:#666">{refund}</p>
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
      <p style="color:#999;font-size:12px">Audiobook Maker  -  {BASE_URL or ''}</p>
    </div>"""
    _send_email(email, subject, html_body)


def _send_voucher_email(code, email, amount_eur, book_title):
    """Send voucher email after optimization failure."""
    if not (email and _smtp_available()):
        return
    from datetime import datetime, timedelta
    expiry = (datetime.now() + timedelta(days=VOUCHER_EXPIRY_DAYS)).strftime("%d/%m/%Y")
    subject = f"Audiobook Maker  -  Buono {amount_eur:.2f} EUR (ottimizzazione non riuscita)"
    html_body = f"""<div style="font-family:system-ui,-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <h2 style="color:#2c3e50">&#x1F381; Il tuo buono</h2>
      <p>L'ottimizzazione AI del testo di <strong>{book_title}</strong> non &egrave; andata a buon fine.</p>
      <p>Come convenuto, ti inviamo un buono di valore maggiorato del {VOUCHER_BONUS_PERCENT}%:</p>
      <div style="padding:20px;background:#f0f5ff;border:2px dashed #8b5cf6;border-radius:8px;margin:20px 0;text-align:center">
        <div style="font-size:.85em;color:#666;margin-bottom:8px">Codice buono:</div>
        <div style="font-family:monospace;font-size:1.6em;font-weight:700;letter-spacing:2px;color:#8b5cf6">{code}</div>
        <div style="margin-top:12px">Valore: <strong>{amount_eur:.2f} EUR</strong></div>
        <div style="margin-top:4px;font-size:.9em;color:#666">Scadenza: {expiry}</div>
      </div>
      <p>Per utilizzarlo, avvia una nuova ottimizzazione AI e inserisci questo codice insieme all'email <strong>{email}</strong>.</p>
      <p style="font-size:.85em;color:#666">Il buono &egrave; nominativo e riutilizzabile: se l'operazione costa meno del valore del buono, il saldo residuo rimane disponibile per usi successivi fino alla scadenza.</p>
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
      <p style="color:#999;font-size:12px">Audiobook Maker  -  {BASE_URL or ''}</p>
    </div>"""
    _send_email(email, subject, html_body)


@app.route("/api/optimize", methods=["POST"])
def api_optimize():
    if not _llm_available(): return jsonify({"error": "LLM optimization not available"}), 503
    data = request.json or {}; job_id = data.get("job_id"); batch = data.get("batch", False); auto_generate = data.get("auto_generate", False); email = (data.get("email") or "").strip().lower()
    if job_id not in jobs: return jsonify({"error": "Session expired"}), 400
    job = jobs[job_id]; info = job.get("info")
    client_id = job.get("client_id", "")
    if job["status"] not in ("analyzed",): return jsonify({"error": "Invalid state"}), 400
    selected_chapters = _parse_selected_chapters(data.get("selected_chapters"))
    if selected_chapters:
        total_chars = sum(ch.char_count for ch in info.chapters if ch.index in selected_chapters)
    else:
        total_chars = sum(ch.char_count for ch in info.chapters) if info else 0
    estimated_cost = _estimate_llm_cost_eur(total_chars)
    if estimated_cost > LLM_FREE_THRESHOLD_EUR:
        payment_token = (data.get("payment_token") or "").strip()
        if not payment_token:
            return jsonify({
                "error": "Payment required for this optimization.",
                "error_code": "payment_required",
                "estimated_cost_eur": estimated_cost,
                "chars": total_chars,
            }), 402
        # Validate payment_token (PayPal order_id or voucher code)
        valid = False
        if payment_token in _payments:
            pay = _payments[payment_token]
            if not pay.get("used") and pay.get("amount_eur", 0) >= estimated_cost:
                pay["used"] = True
                pay["used_at"] = time.time()
                pay["used_job_id"] = job_id
                _save_payments()
                job["payment_token"] = payment_token
                job["payment_type"] = "paypal"
                job["payment_email"] = pay.get("email", "")
                job["payment_amount_eur"] = pay.get("amount_eur", 0)
                valid = True
        elif payment_token in _vouchers:
            v = _vouchers[payment_token]
            remaining = _voucher_remaining(v)
            if v.get("expires_at", 0) > time.time() and remaining >= estimated_cost - 0.01:
                try:
                    new_remaining = _voucher_consume(payment_token, estimated_cost, job_id=job_id)
                except ValueError as _ve:
                    return jsonify({
                        "error": f"Voucher not spendable: {_ve}",
                        "error_code": "invalid_payment",
                    }), 402
                job["payment_token"] = payment_token
                job["payment_type"] = "voucher"
                job["payment_email"] = v.get("email", "")
                job["payment_amount_eur"] = round(float(estimated_cost), 2)
                job["voucher_remaining_after"] = new_remaining
                valid = True
        if not valid:
            return jsonify({
                "error": "Invalid or already-used payment token.",
                "error_code": "invalid_payment",
            }), 402

    # Batch mode requires email
    if batch:
        import re as _re
        if not email or not _re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email):
            return jsonify({"error": "Valid email required for batch mode"}), 400
        if not _smtp_available():
            return jsonify({"error": "Email service not configured on this server"}), 503
        job["notify_email"] = email
        job["notify_lang"] = data.get("lang", "en")
        job["email_registered"] = True

    # Store auto-generate params for batch mode
    if auto_generate:
        job["opt_auto_generate"] = True
        job["opt_voice"] = data.get("voice", "it-IT-IsabellaNeural")
        job["opt_rate"] = data.get("rate", "+0%")
        job["opt_single_file"] = data.get("single_file", True)
        job["notify_download_type"] = data.get("download_type", "audio")
        job["notify_base_url"] = (data.get("base_url") or "").strip()
    else:
        job["opt_auto_generate"] = False

    thread = threading.Thread(
        target=run_optimization, args=(job_id, selected_chapters), daemon=True
    )
    thread.start()

    _log_activity(job_id, job.get("original_filename", ""), "OPTIMIZE",
                  client_id, job.get("client_ip", ""), "",
                  browser_lang=job.get("browser_lang", ""))

    return jsonify({"status": "started", "batch": batch, "auto_generate": auto_generate})


@app.route("/api/optimize_progress/<job_id>")
def api_optimize_progress(job_id):
    """SSE endpoint for LLM optimization progress."""
    def stream():
        while True:
            if job_id not in jobs:
                yield f"data: {json.dumps({'status': 'error', 'error': 'Job not found'})}\n\n"
                break
            job = jobs[job_id]
            job["last_poll"] = time.time()
            status = job.get("status", "unknown")
            payload = {
                "status": status,
                "opt_progress_current": job.get("opt_progress_current", 0),
                "opt_progress_total": job.get("opt_progress_total", 0),
                "opt_progress_message": job.get("opt_progress_message", ""),
                "opt_current_chapter": job.get("opt_current_chapter", ""),
                "opt_current_chapter_num": job.get("opt_current_chapter_num", 0),
                "opt_processed_chars": job.get("opt_processed_chars", 0),
                "opt_streamed_chars": job.get("opt_streamed_chars", 0),
                "opt_current_chapter_chars": job.get("opt_current_chapter_chars", 0),
                "opt_total_chars": job.get("opt_total_chars", 0),
                "opt_elapsed_seconds": round(time.time() - job["opt_start_time"]) if job.get("opt_start_time") else job.get("opt_elapsed_seconds", 0),
            }
            if status == "error":
                payload["error"] = job.get("error", "Unknown error")
                yield f"data: {json.dumps(payload)}\n\n"
                break
            if status == "cancelled":
                yield f"data: {json.dumps(payload)}\n\n"
                break
            if status == "optimized":
                payload["ai_optimized"] = True
                yield f"data: {json.dumps(payload)}\n\n"
                break
            # If auto_generate kicked in, status is now "generating" or "done"
            if status in ("generating", "done"):
                payload["ai_optimized"] = True
                payload["auto_generate_started"] = True
                yield f"data: {json.dumps(payload)}\n\n"
                break
            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(2)

    return Response(
        stream_with_context(stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/cancel_optimize/<job_id>", methods=["POST"])
def api_cancel_optimize(job_id):
    """Cancel an LLM optimization in progress."""
    if job_id in jobs:
        job = jobs[job_id]
        if job.get("status") == "optimizing":
            job["opt_cancelled"] = True
            return jsonify({"status": "cancelling"})
    return jsonify({"status": "not_found"}), 404


@app.route("/api/register_opt_email", methods=["POST"])
def api_register_opt_email():
    """Register email on an already-running optimization (background mode)."""
    import re as _re
    data = request.json or {}
    job_id = data.get("job_id", "")
    email = (data.get("email") or "").strip().lower()
    auto_generate = data.get("auto_generate", False)

    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    job = jobs[job_id]

    if job.get("status") != "optimizing":
        return jsonify({"error": "Optimization not in progress"}), 400

    if not email or not _re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email):
        return jsonify({"error": "Invalid email address"}), 400

    if not _smtp_available():
        return jsonify({"error": "Email service not configured on this server"}), 503

    job["notify_email"] = email
    job["notify_lang"] = data.get("lang", "en")
    job["notify_download_type"] = data.get("download_type", "audio")
    job["notify_base_url"] = (data.get("base_url") or "").strip()
    job["email_registered"] = True

    if auto_generate:
        job["opt_auto_generate"] = True
        job["opt_voice"] = data.get("voice", "it-IT-IsabellaNeural")
        job["opt_rate"] = data.get("rate", "+0%")
        job["opt_single_file"] = data.get("single_file", True)

    print(f"[{job_id}] Optimization email registered: {email} (auto_generate: {auto_generate})")
    _log_activity(job_id, job.get("original_filename", ""), "OPT_EMAIL_REGISTERED",
                  job.get("client_id", ""), job.get("client_ip", ""),
                  "", browser_lang=job.get("browser_lang", ""))

    return jsonify({"status": "registered", "email": email})


@app.route("/api/active_jobs")
def api_active_jobs():
    """Return list of currently generating jobs (for admin monitor).
    Protected by admin token.
    """
    if not ADMIN_TOKEN:
        return jsonify({"error": "Admin monitor disabled"}), 404
    if not _admin_auth_ok(_admin_auth_from_request()):
        return jsonify({"error": "Unauthorized"}), 401

    from datetime import datetime
    active = []
    for jid, job in list(jobs.items()):
        if job.get("status") in ("generating", "analyzed", "optimizing", "optimized"):
            info = job.get("info")
            title = ""
            if info:
                title = getattr(info, "title", "") or ""
            if not title:
                title = job.get("original_filename", jid)
            start_ts = job.get("start_time", 0)
            active.append({
                "title": title,
                "started": datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d %H:%M:%S") if start_ts else " - ",
                "status": job.get("status", ""),
                "progress": job.get("progress_current", 0),
                "total": job.get("progress_total", 0),
                "chapter": job.get("current_chapter", ""),
            })
    return jsonify({"jobs": active, "count": len(active)})


@app.route("/dl/<token>")
def token_download_page(token):
    """Serve download page for email-linked token."""
    token_info = _download_tokens.get(token)
    if not token_info:
        return _render_dl_expired_page(), 410

    lang = token_info.get("lang", "en")
    created_at = token_info["created_at"]
    elapsed = time.time() - created_at

    # Check 24h expiration
    if elapsed > EMAIL_FILE_RETENTION_SEC:
        _download_tokens.pop(token, None)
        _save_tokens()
        return _render_dl_expired_page(lang), 410

    # Check job exists in memory OR files still on disk
    job_id = token_info["job_id"]
    job_dir = UPLOAD_DIR / job_id
    dl_type = token_info.get("download_type", "audio")
    job_in_memory = job_id in jobs and jobs[job_id].get("status") in ("done", "optimized")
    files_on_disk = job_dir.exists()

    if not job_in_memory and not files_on_disk:
        _download_tokens.pop(token, None)
        _save_tokens()
        return _render_dl_expired_page(lang), 410

    remaining_sec = max(60, int(EMAIL_FILE_RETENTION_SEC - elapsed))
    remaining_h = remaining_sec // 3600
    remaining_m = (remaining_sec % 3600) // 60
    if remaining_h > 0:
        remaining_str = f"~{remaining_h}h {remaining_m}min" if remaining_m > 0 else f"~{remaining_h}h"
    else:
        remaining_str = f"~{remaining_m} min"

    # Book title: from job in memory or from token snapshot
    if job_in_memory and jobs[job_id].get("info"):
        book_title = jobs[job_id]["info"].title or ""
    else:
        book_title = token_info.get("book_title", "")

    # M4B availability: da job in memoria, da token snapshot oppure scan filesystem.
    # Il fallback su filesystem è importante perché il job potrebbe avere output_m4b
    # non impostato (es. se il token è stato creato prima che M4B completasse).
    m4b_available = False
    if job_in_memory:
        m4b_path_mem = jobs[job_id].get("output_m4b", "")
        if m4b_path_mem and os.path.exists(m4b_path_mem):
            m4b_available = True
        else:
            # Fallback filesystem anche con job in memoria
            m4bs = list(job_dir.glob("*.m4b")) + list((job_dir / "output").glob("*.m4b"))
            if m4bs:
                m4b_available = True
                # Aggiorna anche il job in memoria per coerenza
                jobs[job_id]["output_m4b"] = str(m4bs[0])
    else:
        m4b_path = token_info.get("output_m4b", "")
        if m4b_path and os.path.exists(m4b_path):
            m4b_available = True
        else:
            # Check common locations (job dir or output subdir)
            m4bs = list(job_dir.glob("*.m4b")) + list((job_dir / "output").glob("*.m4b"))
            m4b_available = len(m4bs) > 0

    return _render_dl_page(token, book_title, remaining_str,
                           token_info["download_type"], lang, m4b_available=m4b_available)


@app.route("/dl/<token>/abm")
def token_do_download_abm(token):
    """Serve the optimized .abm file for a token (when available)."""
    token_info = _download_tokens.get(token)
    if not token_info:
        return "Link scaduto", 410
    if time.time() - token_info["created_at"] > EMAIL_FILE_RETENTION_SEC:
        _download_tokens.pop(token, None)
        _save_tokens()
        return "Link scaduto  -  i file sono stati cancellati dopo 24 ore", 410
    abm_path = token_info.get("optimized_abm_path", "")
    abm_name = token_info.get("optimized_abm_name", "optimized.abm")
    if not abm_path or not os.path.exists(abm_path):
        # Try reconstruction inside job dir
        job_id = token_info.get("job_id", "")
        if job_id and abm_path:
            alt = UPLOAD_DIR / job_id / os.path.basename(abm_path)
            if alt.exists():
                abm_path = str(alt)
    if not abm_path or not os.path.exists(abm_path):
        return "File not available", 404
    _log_activity(token_info.get("job_id", ""), token_info.get("original_filename", ""),
                  "DOWNLOAD_OPT_ABM", "", "", "", "")
    return send_file(abm_path, as_attachment=True, download_name=abm_name)


@app.route("/dl/<token>/m4b")
def token_do_download_m4b(token):
    """Execute the actual M4B file download via token."""
    token_info = _download_tokens.get(token)
    if not token_info:
        return "Link scaduto", 410

    job_id = token_info["job_id"]
    if time.time() - token_info["created_at"] > EMAIL_FILE_RETENTION_SEC:
        _download_tokens.pop(token, None)
        _save_tokens()
        return "Link scaduto  -  i file sono stati cancellati dopo 24 ore", 410

    # Try to get data from job in memory, otherwise use token snapshot
    job = jobs.get(job_id)
    m4b_path = ""
    if job:
        m4b_path = job.get("output_m4b", "")
        job["last_poll"] = time.time()
        job["downloaded_at"] = time.time()
    
    if not m4b_path or not os.path.exists(m4b_path):
        m4b_path = token_info.get("output_m4b", "")
    
    # Path reconstruction
    if not m4b_path or not os.path.exists(m4b_path):
        job_dir = UPLOAD_DIR / job_id
        m4b_path = str(job_dir / "output" / f"{_safe_filename(token_info.get('book_title','audiolibro'))}.m4b")
        if not os.path.exists(m4b_path):
             m4bs = list(job_dir.glob("*.m4b")) + list((job_dir/"output").glob("*.m4b"))
             if m4bs: m4b_path = str(m4bs[0])

    if not m4b_path or not os.path.exists(m4b_path):
        return "M4B file not available", 404

    _log_activity(job_id, token_info.get("original_filename", ""), "DOWNLOAD_M4B_TOKEN",
                  "", "", "", "")
    
    safe_name = _safe_filename(token_info.get("book_title", "audiolibro"))
    return send_file(m4b_path, as_attachment=True, download_name=f"{safe_name}.m4b")


@app.route("/dl/<token>/download")
def token_do_download(token):
    """Execute the actual file download via token."""
    token_info = _download_tokens.get(token)
    if not token_info:
        return "Link scaduto", 410

    job_id = token_info["job_id"]
    if time.time() - token_info["created_at"] > EMAIL_FILE_RETENTION_SEC:
        _download_tokens.pop(token, None)
        _save_tokens()
        return "Link scaduto  -  i file sono stati cancellati dopo 24 ore", 410

    # Try to get data from job in memory, otherwise use token snapshot
    job = jobs.get(job_id)
    if job:
        job["last_poll"] = time.time()
        job["downloaded_at"] = time.time()

    dl_type = token_info.get("download_type", "audio")

    # Diagnostic logging
    job_dir = UPLOAD_DIR / job_id
    print(f"[dl] Token download: job={job_id}, type={dl_type}, "
          f"job_in_memory={job is not None}, "
          f"job_dir_exists={job_dir.exists()}, "
          f"stored_zip={token_info.get('output_zip', '')[:80]}, "
          f"UPLOAD_DIR={UPLOAD_DIR}")

    try:
        #  -  -  OPTIMIZED ABM download  -  - 
        if dl_type == "optimized_abm":
            abm_path = token_info.get("optimized_abm_path", "")
            abm_name = token_info.get("optimized_abm_name", "optimized.abm")
            if not abm_path or not os.path.exists(abm_path):
                # Try path reconstruction
                abm_path = str(job_dir / os.path.basename(abm_path)) if abm_path else ""
            if abm_path and os.path.exists(abm_path):
                if job:
                    job["downloaded_at"] = time.time()
                _log_activity(job_id, token_info.get("original_filename", ""),
                              "DOWNLOAD_OPT_ABM", "", "", "", "")
                return send_file(abm_path, as_attachment=True, download_name=abm_name)
            return "File not found", 404

        #  -  -  PODCAST download  -  - 
        is_podcast = dl_type == "podcast" and (
            (job and job.get("podcast_ready")) or token_info.get("podcast_ready"))

        if is_podcast:
            return _serve_podcast_download(token_info, job, job_id)

        #  -  -  AUDIO download  -  - 
        return _serve_audio_download(token_info, job, job_id)

    except Exception as e:
        print(f"[dl/{token}] ERROR in download: {e}")
        import traceback
        traceback.print_exc()
        return f"Errore durante il download. Riprova tra qualche istante.", 500


def _serve_audio_download(token_info, job, job_id):
    """Serve audio download from job in memory or token snapshot on disk."""
    output_name = token_info.get("output_name", "audiobook.zip")
    orig = token_info.get("original_filename", "")
    job_dir = UPLOAD_DIR / job_id

    # 1. Try job in memory
    if job:
        orig = job.get("original_filename", orig)
        if "output_zip" in job and os.path.exists(job["output_zip"]):
            _log_activity(job_id, orig, "DOWNLOAD_EMAIL", job.get("client_id", "") if job else "", job.get("client_ip", "") if job else "", job.get("voice", "") if job else "", job.get("browser_lang", "") if job else "")
            return send_file(job["output_zip"], as_attachment=True,
                             download_name=job.get("output_name", output_name))
        if job.get("output_files") and os.path.exists(job["output_files"][0]):
            _log_activity(job_id, orig, "DOWNLOAD_EMAIL", job.get("client_id", "") if job else "", job.get("client_ip", "") if job else "", job.get("voice", "") if job else "", job.get("browser_lang", "") if job else "")
            return send_file(job["output_files"][0], as_attachment=True,
                             download_name=job.get("output_name", output_name))
        print(f"[dl] Job {job_id} in memory but files missing on disk")

    # 2. Try exact paths from token snapshot
    output_zip = token_info.get("output_zip", "")
    output_file = token_info.get("output_file", "")

    if output_zip and os.path.exists(output_zip):
        _log_activity(job_id, orig, "DOWNLOAD_EMAIL", job.get("client_id", "") if job else "", job.get("client_ip", "") if job else "", job.get("voice", "") if job else "", job.get("browser_lang", "") if job else "")
        return send_file(output_zip, as_attachment=True, download_name=output_name)
    if output_file and os.path.exists(output_file):
        _log_activity(job_id, orig, "DOWNLOAD_EMAIL", job.get("client_id", "") if job else "", job.get("client_ip", "") if job else "", job.get("voice", "") if job else "", job.get("browser_lang", "") if job else "")
        return send_file(output_file, as_attachment=True, download_name=output_name)

    # 3. Path reconstruction: stored paths may be from a different DATA_DIR
    #    Try to find files using just the filename under current job_dir
    if output_zip and not os.path.exists(output_zip):
        reconstructed = str(job_dir / os.path.basename(output_zip))
        if os.path.exists(reconstructed):
            print(f"[dl] Path reconstructed: {output_zip} -> {reconstructed}")
            _log_activity(job_id, orig, "DOWNLOAD_EMAIL", job.get("client_id", "") if job else "", job.get("client_ip", "") if job else "", job.get("voice", "") if job else "", job.get("browser_lang", "") if job else "")
            return send_file(reconstructed, as_attachment=True, download_name=output_name)
    if output_file and not os.path.exists(output_file):
        reconstructed = str(job_dir / "output" / os.path.basename(output_file))
        if os.path.exists(reconstructed):
            print(f"[dl] Path reconstructed: {output_file} -> {reconstructed}")
            _log_activity(job_id, orig, "DOWNLOAD_EMAIL", job.get("client_id", "") if job else "", job.get("client_ip", "") if job else "", job.get("voice", "") if job else "", job.get("browser_lang", "") if job else "")
            return send_file(reconstructed, as_attachment=True, download_name=output_name)

    # 4. Fallback: scan job directory for downloadable files
    if job_dir.exists():
        print(f"[dl] Scanning {job_dir} for downloadable files...")
        # Look for ZIP first (root of job dir)
        zips = sorted(job_dir.glob("*.zip"))
        # Exclude podcast zips
        zips = [z for z in zips if "_podcast" not in z.name]
        if zips:
            found = str(zips[0])
            print(f"[dl] Fallback: found ZIP {found}")
            _log_activity(job_id, orig, "DOWNLOAD_EMAIL", job.get("client_id", "") if job else "", job.get("client_ip", "") if job else "", job.get("voice", "") if job else "", job.get("browser_lang", "") if job else "")
            return send_file(found, as_attachment=True,
                             download_name=output_name or os.path.basename(found))
        # Look for MP3 in output/ subdirectory, then root
        output_subdir = job_dir / "output"
        mp3s = sorted(output_subdir.glob("*.mp3")) if output_subdir.exists() else []
        if not mp3s:
            mp3s = sorted(job_dir.glob("*.mp3"))
        if len(mp3s) == 1:
            found = str(mp3s[0])
            print(f"[dl] Fallback: found single MP3 {found}")
            _log_activity(job_id, orig, "DOWNLOAD_EMAIL", job.get("client_id", "") if job else "", job.get("client_ip", "") if job else "", job.get("voice", "") if job else "", job.get("browser_lang", "") if job else "")
            return send_file(found, as_attachment=True,
                             download_name=output_name or os.path.basename(found))
        elif len(mp3s) > 1:
            # Multiple MP3s: create a ZIP on the fly
            src_dir = str(mp3s[0].parent)
            zip_file = shutil.make_archive(str(job_dir / "download"), "zip", src_dir)
            print(f"[dl] Fallback: created ZIP from {len(mp3s)} MP3s -> {zip_file}")
            _log_activity(job_id, orig, "DOWNLOAD_EMAIL", job.get("client_id", "") if job else "", job.get("client_ip", "") if job else "", job.get("voice", "") if job else "", job.get("browser_lang", "") if job else "")
            return send_file(zip_file, as_attachment=True,
                             download_name=output_name or "audiobook.zip")

    print(f"[dl] No files found for job {job_id} (job_dir exists: {job_dir.exists()})")
    print(f"[dl]   stored output_zip: {output_zip}")
    print(f"[dl]   stored output_file: {output_file}")
    print(f"[dl]   UPLOAD_DIR: {UPLOAD_DIR}")
    return "File non più disponibili", 410

    print(f"[dl] No files found for job {job_id}")
    return "File non più disponibili", 410


def _generate_podcast_index_html(podcast_dir, title, author, cover_file, rss_fname, mp3_files, language="en"):
    """Generate an index.html landing page for the podcast folder (required by Netlify)."""
    lang = language[:2] if language else "en"
    _labels = {
        "it": {"heading": "Podcast", "by": "di", "subscribe": "Iscriviti al Podcast",
               "copy": "Copia URL feed", "copied": "Copiato!",
               "episodes": "Episodi", "listen": "Ascolta",
               "instructions": "Copia l'URL del feed RSS e incollalo nella tua app podcast preferita (Pocket Casts, Apple Podcasts, AntennaPod, Overcast...).",
               "footer": "Generato con Audiobook Maker"},
        "en": {"heading": "Podcast", "by": "by", "subscribe": "Subscribe to Podcast",
               "copy": "Copy feed URL", "copied": "Copied!",
               "episodes": "Episodes", "listen": "Listen",
               "instructions": "Copy the RSS feed URL and paste it in your favorite podcast app (Pocket Casts, Apple Podcasts, AntennaPod, Overcast...).",
               "footer": "Generated with Audiobook Maker"},
        "fr": {"heading": "Podcast", "by": "de", "subscribe": "S'abonner au Podcast",
               "copy": "Copier l'URL du flux", "copied": "Copié !",
               "episodes": "Épisodes", "listen": "Écouter",
               "instructions": "Copiez l'URL du flux RSS et collez-la dans votre app podcast (Pocket Casts, Apple Podcasts, AntennaPod, Overcast...).",
               "footer": "Généré avec Audiobook Maker"},
        "es": {"heading": "Podcast", "by": "de", "subscribe": "Suscríbete al Podcast",
               "copy": "Copiar URL del feed", "copied": "¡Copiado!",
               "episodes": "Episodios", "listen": "Escuchar",
               "instructions": "Copia la URL del feed RSS y pégala en tu app de podcast favorita (Pocket Casts, Apple Podcasts, AntennaPod, Overcast...).",
               "footer": "Generado con Audiobook Maker"},
        "de": {"heading": "Podcast", "by": "von", "subscribe": "Podcast abonnieren",
               "copy": "Feed-URL kopieren", "copied": "Kopiert!",
               "episodes": "Episoden", "listen": "Anhören",
               "instructions": "Kopieren Sie die RSS-Feed-URL und fügen Sie sie in Ihre Podcast-App ein (Pocket Casts, Apple Podcasts, AntennaPod, Overcast...).",
               "footer": "Erstellt mit Audiobook Maker"},
        "zh": {"heading": "播客", "by": "作者", "subscribe": "订阅播客",
               "copy": "复制订阅�URL", "copied": "已复制！",
               "episodes": "章节", "listen": "收�",
               "instructions": "复制RSS订阅�URL并将其粘贴到您的播客应用程序中（Pocket Casts，Apple Podcasts，AntennaPod，Overcast...）。",
               "footer": "由Audiobook Maker生�"},
    }
    lb = _labels.get(lang, _labels["en"])

    # Build episode list
    sorted_mp3 = sorted([os.path.basename(f) for f in mp3_files if os.path.exists(f)])
    episodes_html = ""
    for i, mp3 in enumerate(sorted_mp3, 1):
        display_name = mp3.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
        episodes_html += f'<tr><td style="padding:10px 12px;border-bottom:1px solid #eee;color:#666;width:40px;text-align:center">{i}</td><td style="padding:10px 12px;border-bottom:1px solid #eee">{display_name}</td><td style="padding:10px 12px;border-bottom:1px solid #eee;text-align:right"><a href="{mp3}" style="color:#2c7bb6;text-decoration:none">&#9654; {lb["listen"]}</a></td></tr>'

    cover_tag = ""
    if cover_file:
        cover_tag = f'<img src="{cover_file}" alt="Cover" style="width:200px;height:200px;object-fit:cover;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.15)">'

    safe_title = (title or "Audiobook").replace('"', '&quot;').replace('<', '&lt;')
    safe_author = (author or "").replace('"', '&quot;').replace('<', '&lt;')

    html = f'''<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title} - {lb["heading"]}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f7fa;color:#333;line-height:1.6}}
.hero{{background:linear-gradient(135deg,#1a3c5e 0%,#2c7bb6 100%);color:#fff;padding:50px 20px 40px;text-align:center}}
.hero h1{{font-size:1.8rem;margin:16px 0 4px}}
.hero .author{{opacity:.8;font-size:1rem}}
.container{{max-width:680px;margin:0 auto;padding:20px}}
.feed-box{{background:#fff;border-radius:12px;padding:24px;margin:-30px auto 24px;box-shadow:0 2px 12px rgba(0,0,0,.08);position:relative;z-index:1}}
.feed-box h2{{font-size:1.1rem;margin-bottom:8px;color:#1a3c5e}}
.feed-url{{display:flex;gap:8px;margin:12px 0}}
.feed-url input{{flex:1;padding:10px 14px;border:1px solid #ddd;border-radius:8px;font-family:monospace;font-size:.85rem;background:#f8f8f8;color:#333}}
.feed-url button{{padding:10px 20px;background:#2c7bb6;color:#fff;border:none;border-radius:8px;cursor:pointer;font-weight:600;font-size:.85rem;white-space:nowrap;transition:background .2s}}
.feed-url button:hover{{background:#1a5a8a}}
.instructions{{font-size:.88rem;color:#666;margin-top:8px}}
.episodes{{background:#fff;border-radius:12px;padding:24px;box-shadow:0 2px 12px rgba(0,0,0,.08);margin-bottom:24px}}
.episodes h2{{font-size:1.1rem;margin-bottom:16px;color:#1a3c5e}}
.episodes table{{width:100%;border-collapse:collapse}}
.footer{{text-align:center;color:#aaa;font-size:.8rem;padding:20px}}
</style>
</head>
<body>
<div class="hero">
{cover_tag}
<h1>{safe_title}</h1>
{f'<div class="author">{lb["by"]} {safe_author}</div>' if safe_author else ''}
</div>
<div class="container">
<div class="feed-box">
<h2>&#x1F399;&#xFE0F; {lb["subscribe"]}</h2>
<div class="feed-url">
<input type="text" id="feedUrl" value="{rss_fname}" readonly onclick="this.select()">
<button onclick="copyFeed()">{lb["copy"]}</button>
</div>
<div class="instructions">{lb["instructions"]}</div>
</div>
<div class="episodes">
<h2>{lb["episodes"]} ({len(sorted_mp3)})</h2>
<table>{episodes_html}</table>
</div>
<div class="footer">{lb["footer"]}</div>
</div>
<script>
function copyFeed(){{
  const inp=document.getElementById('feedUrl');
  navigator.clipboard.writeText(inp.value).then(()=>{{
    const btn=document.querySelector('.feed-url button');
    btn.textContent='{lb["copied"]}';
    setTimeout(()=>btn.textContent='{lb["copy"]}',2000);
  }});
}}
// Update feed URL with full path on load
window.addEventListener('load',()=>{{
  const inp=document.getElementById('feedUrl');
  const base=window.location.href.replace(/\\/[^\\/]*$/,'/');
  inp.value=base+'{rss_fname}';
}});
</script>
</body>
</html>'''

    index_path = os.path.join(str(podcast_dir), "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)
    return index_path


def _serve_podcast_download(token_info, job, job_id):
    """Serve podcast download from job in memory or token snapshot on disk."""
    base_url = token_info.get("base_url", "")

    # Get podcast data from job (memory) or token snapshot (disk)
    if job:
        mp3_files = job.get("podcast_mp3s", [])
        safe_name = job.get("podcast_safe_name", "audiolibro")
        epub_path = job.get("epub_path", "")
        p_info_title = job["podcast_info"].title if job.get("podcast_info") else ""
        p_info_author = job["podcast_info"].author if job.get("podcast_info") else ""
        p_info_lang = job["podcast_info"].language if job.get("podcast_info") else ""
    else:
        mp3_files = token_info.get("podcast_mp3s", [])
        safe_name = token_info.get("podcast_safe_name", "audiolibro")
        epub_path = token_info.get("epub_path", "")
        p_info_title = token_info.get("podcast_info_title", "")
        p_info_author = token_info.get("podcast_info_author", "")
        p_info_lang = token_info.get("podcast_info_language", "")

    # Reconstruct epub_path if stored path doesn't exist (data dir may have changed)
    if epub_path and not os.path.exists(epub_path):
        reconstructed = str(UPLOAD_DIR / job_id / os.path.basename(epub_path))
        if os.path.exists(reconstructed):
            print(f"[dl] epub_path reconstructed: {epub_path} -> {reconstructed}")
            epub_path = reconstructed

    # Verify MP3 files exist; fallback: reconstruct paths from current data dir
    mp3_files = [f for f in mp3_files if os.path.exists(f)]
    if not mp3_files:
        # Reconstruct paths: try current UPLOAD_DIR / job_id / output / basename
        raw_mp3s = token_info.get("podcast_mp3s", [])
        output_dir = UPLOAD_DIR / job_id / "output"
        if output_dir.exists():
            for old_path in raw_mp3s:
                reconstructed = str(output_dir / os.path.basename(old_path))
                if os.path.exists(reconstructed):
                    mp3_files.append(reconstructed)
            if mp3_files:
                print(f"[dl] Podcast path reconstruction: {len(mp3_files)} MP3s found in {output_dir}")
    if not mp3_files:
        # Final fallback: scan output/ directory
        job_dir = UPLOAD_DIR / job_id
        output_dir = job_dir / "output"
        if output_dir.exists():
            mp3_files = sorted([str(f) for f in output_dir.glob("*.mp3")])
            if mp3_files:
                print(f"[dl] Podcast scan fallback: found {len(mp3_files)} MP3s in {output_dir}")
    if not mp3_files:
        return "File non più disponibili", 410

    # Create a minimal info object for RSS generation
    # Use real info object when job is in memory (has chapters for RSS titles),
    # otherwise create minimal stub for token-based downloads
    if job and job.get("podcast_info"):
        info = job["podcast_info"]
    else:
        class _MiniInfo:
            pass
        info = _MiniInfo()
        info.title = p_info_title
        info.author = p_info_author
        info.language = p_info_lang
        info.chapters = []  # No chapter objects available; RSS will use "Episode N" fallback

    work_dir = Path(mp3_files[0]).parent.parent if mp3_files else UPLOAD_DIR / job_id

    # If a podcast zip was already built for this job, serve it directly
    cached_zip = work_dir / f"{safe_name}_podcast.zip"
    if cached_zip.exists() and cached_zip.stat().st_size > 0:
        print(f"[dl] Serving cached podcast zip: {cached_zip}")
        return send_file(str(cached_zip), as_attachment=True,
                         download_name=f"{safe_name}_podcast.zip")

    # Build podcast package in a unique temp dir to avoid race conditions
    import uuid as _uuid
    podcast_dir = work_dir / f"podcast_{_uuid.uuid4().hex[:8]}"
    podcast_dir.mkdir(parents=True, exist_ok=True)
    try:
        for mp3 in mp3_files:
            if os.path.exists(mp3):
                shutil.copy2(mp3, str(podcast_dir / os.path.basename(mp3)))
        cover_file = ""
        cover_path = str(podcast_dir / "cover.jpg")
        if epub_path and os.path.exists(epub_path):
            if _extract_cover_from_epub(epub_path, cover_path, target_size=1400):
                cover_file = "cover.jpg"
            else:
                raw_path, raw_mime = _extract_cover_for_preview(epub_path, str(podcast_dir))
                if raw_path and os.path.exists(raw_path):
                    ext = ".png" if raw_mime == "image/png" else ".jpg"
                    final_cover = str(podcast_dir / ("cover" + ext))
                    if raw_path != final_cover:
                        shutil.move(raw_path, final_cover)
                    cover_file = "cover" + ext
                else:
                    _generate_fallback_cover(cover_path, title=info.title or "", author=info.author or "")
                    if os.path.exists(cover_path) and os.path.getsize(cover_path) > 0:
                        cover_file = "cover.jpg"
        rss_fname = f"{safe_name}_podcast.xml"
        rss_path = str(podcast_dir / rss_fname)
        _generate_podcast_rss(info, mp3_files, rss_path,
                              base_url=base_url, cover_filename=cover_file,
                              rss_filename=rss_fname)
        _generate_podcast_index_html(podcast_dir, info.title, info.author,
                                     cover_file, rss_fname, mp3_files,
                                     language=getattr(info, 'language', '') or token_info.get('language', 'en'))
        podcast_zip = shutil.make_archive(
            str(work_dir / f"{safe_name}_podcast"), "zip", str(podcast_dir))
    finally:
        shutil.rmtree(str(podcast_dir), ignore_errors=True)
    orig = token_info.get("original_filename", job.get("original_filename", "") if job else "")
    _log_activity(job_id, orig, "DOWNLOAD_EMAIL_PODCAST",
                  job.get("client_id", "") if job else "",
                  job.get("client_ip", "") if job else "",
                  job.get("voice", "") if job else "", job.get("browser_lang", "") if job else "")
    return send_file(podcast_zip, as_attachment=True,
                     download_name=f"{safe_name}_podcast.zip")


def _render_dl_expired_page(lang="en"):
    expired_t = _DL_PAGES_I18N.get("expired", {})
    t = expired_t.get(lang, expired_t.get("en", {}))
    return f"""<!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/svg+xml" href="{FAVICON_B64}">
<title>Audiobook Maker  -  {t['title']}</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;display:flex;justify-content:center;
align-items:center;min-height:100vh;margin:0;background:#f8f9fa;color:#333}}
.box{{text-align:center;padding:48px;max-width:500px;background:white;border-radius:16px;
box-shadow:0 4px 24px rgba(0,0,0,.08)}}
h1{{font-size:3rem;margin:0 0 16px}}
h2{{color:#e74c3c;margin:0 0 16px}}
p{{color:#666;line-height:1.6}}
a{{color:#3b82f6;text-decoration:none;font-weight:600}}
a:hover{{text-decoration:underline}}
</style></head><body>
<div class="box">
<h1>&#x23F0;</h1>
<h2>{t['h2']}</h2>
<p>{t['p1']}</p>
<p>{t['p2']}</p>
<p><a href="/">&#x1F3A7; Audiobook Maker</a></p>
</div></body></html>"""


def _render_dl_page(token, book_title, remaining_str, dl_type, lang="en", m4b_available=False):
    download_t = _DL_PAGES_I18N.get("download", {})
    t = dict(download_t.get(lang, download_t.get("en", {})))
    
    # If M4B is available and it was the requested type, use M4B button label
    # or if it's the only thing we have (fallback/auto).
    # However, if user chose ZIP, we might have both.
    
    is_m4b_primary = (dl_type == "audio" and m4b_available)
    
    if is_m4b_primary:
        primary_btn_label = t.get("btn_m4b", "Download M4B")
        primary_url = f"/dl/{token}/m4b"
        secondary_btn_html = "" # Don't show MP3/ZIP if M4B is primary unless requested
    else:
        primary_btn_label = t.get("btn_no_m4b", t.get("btn", "Download ZIP"))
        primary_url = f"/dl/{token}/download"
        secondary_btn_html = ""
        # If M4B is available but NOT primary, show it as secondary
        if m4b_available:
            secondary_btn_html = f'<p><a href="/dl/{token}/m4b" class="btn btn-m4b">{t.get("btn_m4b", "Download M4B")}</a></p>'

    if dl_type == "optimized_abm":
        type_label = "Optimized Project (.abm)"
    elif dl_type == "podcast":
        type_label = "Podcast ZIP"
    elif is_m4b_primary:
        type_label = "Audiobook (M4B)"
    else:
        type_label = "Audio ZIP"

    warn_text = t["warn"].replace("{r}", remaining_str)

    share_url = BASE_URL or "https://audiobook-maker.com"
    share_text_js = t.get("share_text", "").replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')

    return f"""<!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/svg+xml" href="{FAVICON_B64}">
<title>Audiobook Maker - {t['title']}</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;display:flex;justify-content:center;
align-items:center;min-height:100vh;margin:0;background:#f8f9fa;color:#333}}
.box{{text-align:center;padding:48px;max-width:500px;background:white;border-radius:16px;
box-shadow:0 4px 24px rgba(0,0,0,.08)}}
h1{{font-size:3rem;margin:0 0 16px}}
h2{{color:#2c3e50;margin:0 0 8px}}
.title{{color:#666;font-style:italic;margin:0 0 24px}}
.btn{{display:inline-block;padding:16px 32px;background:#3b82f6;color:white;
text-decoration:none;border-radius:8px;font-weight:600;font-size:18px;
transition:background .2s;border:none;cursor:pointer}}
.btn:hover{{background:#2563eb}}
.btn-m4b{{background:#8b5cf6;margin-top:12px}}
.btn-m4b:hover{{background:#7c3aed}}
.warn{{color:#e74c3c;font-weight:600;margin-top:24px;font-size:.9rem}}
.type{{display:inline-block;padding:4px 12px;background:#e8f4f8;border-radius:12px;
font-size:.85rem;color:#2980b9;margin-bottom:16px}}
.share-row{{margin-top:28px;padding-top:20px;border-top:1px solid #eee;text-align:center}}
.share-label{{font-size:.85rem;color:#999;margin-bottom:12px}}
.share-icons{{display:flex;justify-content:center;gap:12px;flex-wrap:wrap}}
.share-icons a,.share-icons button{{width:40px;height:40px;border-radius:50%;display:inline-flex;
align-items:center;justify-content:center;border:1px solid #ddd;background:#f8f9fa;color:#666;
cursor:pointer;transition:all .2s;text-decoration:none;padding:0}}
.share-icons a:hover,.share-icons button:hover{{border-color:#3b82f6;color:#3b82f6;
transform:translateY(-2px);box-shadow:0 3px 10px rgba(0,0,0,.08)}}
.share-icons svg{{width:20px;height:20px;fill:currentColor}}
.copy-wrap{{position:relative;display:inline-flex}}
.copy-tip{{position:absolute;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%);
background:#333;color:#fff;font-size:.72rem;padding:3px 8px;border-radius:4px;
white-space:nowrap;pointer-events:none;opacity:0;transition:opacity .2s}}
.copy-tip.show{{opacity:1}}
.donate-panel{{margin-top:20px;padding:18px 20px;background:linear-gradient(135deg,#fffaf4,#fff3e0);
border:1px solid #e8c99a;border-radius:12px;text-align:center}}
.donate-title{{font-size:.97rem;font-weight:700;color:#2c2a26;margin-bottom:6px}}
.donate-body{{font-size:.82rem;color:#6b6760;line-height:1.5;margin-bottom:14px}}
.donate-btns{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.donate-btn{{display:flex;align-items:center;justify-content:center;gap:6px;padding:10px;border-radius:8px;
font-size:.85rem;font-weight:600;text-decoration:none;transition:all .2s;border:1.5px solid transparent}}
.donate-coffee{{background:#ffdd00;color:#1a1400;border-color:#e5c800}}
.donate-coffee:hover{{background:#ffd000;transform:translateY(-2px);box-shadow:0 4px 12px rgba(255,208,0,.4)}}
.donate-paypal{{background:#003087;color:#fff;border-color:#002070}}
.donate-paypal:hover{{background:#002070;transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,48,135,.35)}}
</style></head><body>
<div class="box">
<h1>&#x1F3A7;</h1>
<h2>{t['h2']}</h2>
<p class="title">{book_title}</p>
<p class="type">{type_label}</p>
<p><a href="{primary_url}" class="btn">{primary_btn_label}</a></p>
{secondary_btn_html}
<div class="warn">{warn_text}</div>
<div class="donate-panel">
  <div class="donate-title" id="donTitle"></div>
  <div class="donate-body" id="donBody"></div>
  <div class="donate-btns">
    <a href="https://buymeacoffee.com/audiobookmaker" target="_blank" rel="noopener" class="donate-btn donate-coffee">☕ <span id="donCoffee"></span></a>
    <a href="https://www.paypal.com/paypalme/gfrangiamone" target="_blank" rel="noopener" class="donate-btn donate-paypal">💙 <span id="donPaypal"></span></a>
  </div>
</div>
<div class="share-row">
<div class="share-label">{t['share']}</div>
<div class="share-icons">
  <a id="shWa" href="#" target="_blank" title="WhatsApp"><svg viewBox="0 0 24 24"><path d="M12.031 6.172c-3.181 0-5.767 2.586-5.768 5.766-.001 1.298.38 2.27 1.019 3.287l-.582 2.128 2.182-.573c.978.58 1.911.928 3.145.929 3.178 0 5.767-2.587 5.768-5.766.001-3.187-2.575-5.771-5.764-5.771zm3.392 8.244c-.144.405-.837.774-1.17.824-.299.045-.677.063-1.092-.069-.252-.08-.575-.187-.988-.365-1.739-.751-2.874-2.512-2.961-2.628-.086-.117-.718-.953-.718-1.816 0-.862.448-1.289.607-1.453.159-.164.346-.205.462-.205.115 0 .23 0 .33.006.107.006.252-.04.394.303.144.35.494 1.205.536 1.291.041.086.068.187.011.3-.058.113-.086.184-.173.283-.086.1-.184.223-.263.303-.098.098-.198.205-.086.398.111.193.494.814 1.059 1.315.728.645 1.341.844 1.53.938.189.094.301.078.414-.05.113-.129.482-.562.61-.754.128-.193.256-.164.431-.098.175.066 1.111.523 1.303.62.193.097.322.144.368.225.047.08.047.462-.097.867zM12.211 20C6.605 20 2 15.395 2 9.789 2 4.184 6.605-0.375 12.211-0.375 17.816-0.375 22 4.184 22 9.789c0 5.605-4.605 10.211-10.211 10.211z"/></svg></a>
  <a id="shFb" href="#" target="_blank" title="Facebook"><svg viewBox="0 0 24 24"><path d="M22 12c0-5.52-4.48-10-10-10S2 6.48 2 12c0 4.84 3.44 8.87 8 9.8V15H8v-3h2V9.5C10 7.57 11.57 6 13.5 6H16v3h-2c-.55 0-1 .45-1 1v2h3v3h-3v6.95c5.05-.5 9-4.76 9-9.95z"/></svg></a>
  <a id="shTw" href="#" target="_blank" title="X"><svg viewBox="0 0 24 24"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg></a>
  <a id="shTg" href="#" target="_blank" title="Telegram"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.35-.01-1.02-.2-1.52-.37-.61-.21-1.1-.33-1.06-.69.02-.19.29-.39.81-.6.32-.14 1.89-.78 4.69-1.93 1.03-.43 1.73-.71 2.1-.84.37-.13.86-.33 1.18-.33.22 0 .44.06.63.15.22.12.33.29.35.5.02.13.01.26.01.39z"/></svg></a>
  <div class="copy-wrap">
    <button id="btnCopy" title="Copy link"><svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg></button>
    <span class="copy-tip" id="copyTip">{t['copied']}</span>
  </div>
</div>
</div>
</div>
<script>
(function(){{
  /* ── Donate i18n (browser language) ── */
  var DL={{
    it:{{title:'\u2764\ufe0f Ti \u00e8 stato utile questo strumento?',body:'AudiobookMaker \u00e8 gratuito, senza pubblicit\u00e0 e vorrei poterlo mantenere cos\u00ec! Aiutami a coprire i costi del server e della manutenzione. Anche una piccola donazione di \u20ac1 o \u20ac2 \u00e8 gi\u00e0 un grande contributo:',coffee:'Offrimi un caff\u00e8',paypal:'Donazione PayPal'}},
    fr:{{title:'\u2764\ufe0f Cet outil vous a \u00e9t\u00e9 utile\u00a0?',body:'AudiobookMaker est gratuit, sans publicit\u00e9 et j\u2019aimerais pouvoir le maintenir ainsi\u00a0! Aidez-moi \u00e0 couvrir les co\u00fbts du serveur et de la maintenance. Un petit don de 1 o 2\u00a0\u20ac est d\u00e9j\u00e0 una grande contribution\u00a0:',coffee:'Offrez-moi un caf\u00e9',paypal:'Don PayPal'}},
    es:{{title:'\u2764\ufe0f \u00bfTe ha resultado \u00fatil esta herramienta?',body:'AudiobookMaker es gratuito, sin publicidad y me gustar\u00eda poder mantenerlo as\u00ed. Ay\u00fadame a cubrir los costes del servidor y mantenimiento. \u00a1Una peque\u00f1a donaci\u00f3n de 1 o 2\u00a0\u20ac ya es una gran contribuci\u00f3n!:',coffee:'Inv\u00edtame a un caf\u00e9',paypal:'Donaci\u00f3n PayPal'}},
    de:{{title:'\u2764\ufe0f War dieses Tool n\u00fctzlich f\u00fcr dich?',body:'AudiobookMaker ist kostenlos, werbefrei \u2013 und ich m\u00f6chte es gerne so beibehalten! Hilf mir, die Server- und Wartungskosten zu decken. Eine kleine Spende von 1 oder 2\u00a0\u20ac ist schon ein gro\u00dfere Beitrag:',coffee:'Kauf mir einen Kaffee',paypal:'PayPal-Spende'}},
    zh:{{title:'\u2764\ufe0f \u8fd9\u4e2a\u5de5\u5177\u5bf9\u60a8\u6709\u5e2e\u52a9\u5417\uff1f',body:'AudiobookMaker \u514d\u8d39\u3001\u65e0\u5e7f\u544a\uff0c\u6211\u5e0c\u671b\u80fd\u7ee7\u7eed\u4fdd\u6301\u4e0b\u53bb\uff01\u8bf7\u5e2e\u52a9\u6211\u652f\u4ed8\u670d\u52a1\u5668\u548c\u7ef4\u62a4\u8D39\u7528\u3002\u54ea\u6015 1 \u6216 2 \u6b27\u5143\u7684\u5c0f\u989d\u6350\u8d60\uff0c\u4e5f\u662f\u5de8\u5927\u7684\u8d21\u732e\uff1a',coffee:'\u8bf7\u6211\u559D\u5496\u5561',paypal:'PayPal \u6350\u6b3e'}},
    en:{{title:'\u2764\ufe0f Did you find this tool useful?',body:'AudiobookMaker is free, ad-free, and I\u2019d like to keep it that way! Help me cover server and maintenance costs. A small donation of \u20ac1 or \u20ac2 is already a great contribution:',coffee:'Buy me a coffee',paypal:'PayPal donation'}}
  }};
  var bl=(navigator.language||navigator.userLanguage||'en').toLowerCase().split('-')[0];
  var d=DL[bl]||DL['en'];
  document.getElementById('donTitle').textContent=d.title;
  document.getElementById('donBody').textContent=d.body;
  document.getElementById('donCoffee').textContent=d.coffee;
  document.getElementById('donPaypal').textContent=d.paypal;
  /* ── Share links ── */
  var S='{share_url}';
  var T='{share_text_js}';
  var u=encodeURIComponent(S);
  var tx=encodeURIComponent(T);
  var f=encodeURIComponent(T+' '+S);
  document.getElementById('shWa').href='https://wa.me/?text='+f;
  document.getElementById('shFb').href='https://www.facebook.com/sharer/sharer.php?u='+u;
  document.getElementById('shTw').href='https://twitter.com/intent/tweet?text='+tx+'&url='+u;
  document.getElementById('shTg').href='https://t.me/share/url?url='+u+'&text='+tx;
  document.getElementById('btnCopy').onclick=function(){{
    navigator.clipboard.writeText(S).then(function(){{
      var tip=document.getElementById('copyTip');
      tip.classList.add('show');
      setTimeout(function(){{tip.classList.remove('show')}},2000);
    }});
  }};
}})();
</script></body></html>"""


@app.route("/api/download/<job_id>")
def api_download(job_id):
    if job_id not in jobs:
        return "Job not found", 404
    job = jobs[job_id]
    if job.get("status") != "done":
        return "Not ready", 400
    
    download_type = request.args.get("type", "").lower()
    
    # Refresh heartbeat  -  evita che il cleanup rimuova il job durante il download
    job["last_poll"] = time.time()
    job["downloaded_at"] = time.time()
    
    log_type = "DOWNLOAD"
    if download_type == "m4b":
        log_type = "DOWNLOAD_M4B"
    elif download_type == "zip":
        log_type = "DOWNLOAD_ZIP"
        
    _log_activity(job_id, job.get("original_filename", ""), log_type,
                  job.get("client_id", ""), job.get("client_ip", ""),
                  job.get("voice", ""), job.get("browser_lang", ""))

    if download_type == "m4b":
        if job.get("output_m4b") and os.path.exists(job["output_m4b"]):
            safe_name = _safe_filename(job["info"].title) or "audiolibro"
            return send_file(job["output_m4b"], as_attachment=True, download_name=f"{safe_name}.m4b")
        else:
            # Fallback to single MP3
            return send_file(job["output_files"][0], as_attachment=True, download_name=job["output_name"])
            
    if download_type == "zip" and "output_zip" in job:
        return send_file(job["output_zip"], as_attachment=True, download_name=job["output_name"])

    # Default logic (compatibility with old links)
    if "output_zip" in job:
        return send_file(job["output_zip"], as_attachment=True, download_name=job["output_name"])
    else:
        return send_file(job["output_files"][0], as_attachment=True, download_name=job["output_name"])


@app.route("/api/download_podcast/<job_id>")
def api_download_podcast(job_id):
    if job_id not in jobs:
        return "Job not found", 404
    job = jobs[job_id]
    if job.get("status") != "done":
        return "Not ready", 400
    if not job.get("podcast_ready"):
        return "Podcast not available for this job", 400

    base_url = request.args.get("base_url", "").strip()
    if not base_url:
        return "base_url parameter is required", 400

    job["last_poll"] = time.time()
    job["downloaded_at"] = time.time()

    info = job["podcast_info"]
    mp3_files = job["podcast_mp3s"]
    safe_name = job["podcast_safe_name"]
    work_dir = Path(job["epub_path"]).parent

    # Build podcast ZIP on-the-fly with the user-provided base URL
    podcast_dir = work_dir / "podcast"
    podcast_dir.mkdir(exist_ok=True)
    try:
        for mp3 in mp3_files:
            if os.path.exists(mp3):
                shutil.copy2(mp3, str(podcast_dir / os.path.basename(mp3)))

        # Cover art: extract from EPUB (try Pillow for 1400px square, fallback to raw)
        cover_file = ""
        cover_path = str(podcast_dir / "cover.jpg")
        epub_path = job["epub_path"]

        # Strategy 1: Pillow resize to 1400px square (iTunes compliant)
        if _extract_cover_from_epub(epub_path, cover_path, target_size=1400):
            cover_file = "cover.jpg"
            print(f"[{job_id}] Podcast cover: Pillow 1400px ({os.path.getsize(cover_path)} bytes)")
        else:
            # Strategy 2: raw extraction via _extract_cover_for_preview (works without Pillow)
            print(f"[{job_id}] Podcast cover: _extract_cover_from_epub failed, trying raw extraction")
            raw_path, raw_mime = _extract_cover_for_preview(epub_path, str(podcast_dir))
            if raw_path and os.path.exists(raw_path):
                cover_file = os.path.basename(raw_path)
                # Rename to cover.jpg/cover.png for consistency
                ext = ".png" if raw_mime == "image/png" else ".jpg"
                final_cover = str(podcast_dir / ("cover" + ext))
                if raw_path != final_cover:
                    shutil.move(raw_path, final_cover)
                cover_file = "cover" + ext
                print(f"[{job_id}] Podcast cover: raw extraction OK ({os.path.getsize(final_cover)} bytes)")
            else:
                # Strategy 3: generate fallback cover
                print(f"[{job_id}] Podcast cover: raw extraction failed, generating fallback")
                _generate_fallback_cover(cover_path,
                                         title=info.title or "",
                                         author=info.author or "")
                if os.path.exists(cover_path) and os.path.getsize(cover_path) > 0:
                    cover_file = "cover.jpg"
                    print(f"[{job_id}] Podcast cover: fallback generated ({os.path.getsize(cover_path)} bytes)")
                else:
                    print(f"[{job_id}] Podcast cover: all strategies failed, no cover in podcast")

        rss_fname = f"{safe_name}_podcast.xml"
        rss_path = str(podcast_dir / rss_fname)
        _generate_podcast_rss(info, mp3_files, rss_path,
                              base_url=base_url, cover_filename=cover_file,
                              rss_filename=rss_fname)

        _generate_podcast_index_html(podcast_dir, info.title, info.author,
                                     cover_file, rss_fname, mp3_files,
                                     language=getattr(info, 'language', 'en'))

        # Verify ZIP contents before creating archive
        zip_contents = list(podcast_dir.iterdir())
        print(f"[{job_id}] Podcast ZIP contents: {[f.name for f in zip_contents]}")

        podcast_zip = shutil.make_archive(
            str(work_dir / f"{safe_name}_podcast"), "zip", str(podcast_dir)
        )
    finally:
        shutil.rmtree(str(podcast_dir), ignore_errors=True)

    _log_activity(job_id, job.get("original_filename", ""), "DOWNLOAD_PODCAST",
                  job.get("client_id", ""), job.get("client_ip", ""),
                  job.get("voice", ""), job.get("browser_lang", ""))
    return send_file(podcast_zip, as_attachment=True,
                     download_name=f"{safe_name}_podcast.zip")


# ----------------------------------------------------------------------
# HTML TEMPLATE (i18n, upload lock, ETA)
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# HTML TEMPLATE (assembled from modular components)
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# SEO DATA  -  usato sia per il pre-rendering server-side che per sitemap.xml
# Mantienilo allineato con seo_data.js (che gestisce il cambio lingua client-side)
# ----------------------------------------------------------------------

_SEO_DATA = {
    "it": {
        "title":   "Audiobook Maker - EPUB/PDF a Audiolibro Gratis | MP3 e M4B con Capitoli",
        "tagline": "Convertitore Gratuito da EPUB e PDF in Audiolibro",
        "subtitle":"Converti i tuoi EPUB e PDF in audiolibri con voci neurali di alta qualità",
        "desc":    "Converti i tuoi ebook EPUB e PDF in audiolibri MP3 e M4B (con capitoli incorporati) gratis con voci AI naturali. Convertitore online gratuito text-to-speech: carica il tuo libro, scegli la voce e scarica l'audiolibro professionale. Nessuna installazione, funziona dal browser.",
        "kw":      "convertitore epub m4b, creare m4b con capitoli, convertitore epub audiolibro, epub in audiolibro gratis, pdf in audiolibro, convertire pdf in audiolibro online, convertire ebook in audiolibro online, creare audiolibro da epub, creare audiolibro da pdf, text to speech italiano, da libro a audiolibro gratis, convertitore audiolibro online gratuito, epub to m4b, pdf to m4b, trasformare ebook in audio, sintesi vocale libro, audiolibro maker, convertire libro in audio gratis, ebook to audiobook italiano, tts italiano gratis, creare audiolibro gratis online, convertitore testo in voce, epub reader audio, da testo ad audiolibro, ascoltare ebook, libro parlato gratis",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Convertitore online gratuito per trasformare ebook EPUB e PDF in audiolibri MP3 e M4B con capitoli e voci neurali TTS AI. Supporta 6 lingue, selezione capitoli e generazione feed podcast RSS.",
    },
    "en": {
        "title":   "Audiobook Maker: Free EPUB/PDF to MP3 & M4B | Chapters & AI Voices",
        "tagline": "Free EPUB & PDF to Audiobook Converter",
        "subtitle":"Convert your EPUBs and PDFs into audiobooks with high-quality neural voices",
        "desc":    "Convert your EPUB and PDF ebooks to MP3 or M4B audiobooks (with embedded chapters) for free with natural AI voices. Free online text-to-speech converter: upload your book, choose a voice, and download your professional audiobook. No installation needed, works in your browser.",
        "kw":      "epub to m4b converter, create m4b with chapters, pdf to m4b, epub to audiobook converter, pdf to audiobook converter, free epub to audiobook, free pdf to audiobook, convert ebook to audiobook online free, epub to mp3 converter, pdf to mp3 converter, text to speech audiobook, free audiobook maker online, ebook to audiobook converter, epub to audio, pdf to audio, online audiobook creator free, turn ebook into audiobook, tts audiobook generator, convert epub to mp3 free, convert pdf to mp3 free, free text to speech book reader, ai audiobook maker, epub audiobook converter online, ebook to mp3, listen to epub, epub reader with audio, book to audiobook converter free, create audiobook from epub, create audiobook from pdf",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Free online tool to convert EPUB and PDF ebooks into MP3 and M4B audiobooks (with chapters) using neural AI TTS voices. Supports 6 languages, chapter selection, and podcast RSS feed generation.",
    },
    "fr": {
        "title":   "Audiobook Maker - EPUB/PDF en Livre Audio Gratuit | MP3 et M4B",
        "tagline": "Convertisseur Gratuit EPUB & PDF en Livre Audio",
        "subtitle":"Convertissez vos EPUB et PDF en livres audio avec des voix neurali",
        "desc":    "Convertissez vos ebooks EPUB et PDF en livres audio MP3 et M4B (avec chapitres) gratuitement avec des voix IA naturelles. Convertisseur en ligne gratuit text-to-speech : téléchargez votre livre, choisissez une voix et téléchargez votre livre audio professionnel. Aucune installation, fonctionne dans le navigateur.",
        "kw":      "convertisseur epub m4b, créer m4b avec chapitres, convertisseur epub livre audio, convertisseur pdf livre audio, epub en livre audio gratuit, pdf en livre audio gratuit, convertir ebook en livre audio en ligne, créer livre audio gratuit, text to speech français, convertisseur livre audio en ligne gratuit, epub vers m4b, pdf vers m4b, transformer ebook en audio, synthèse vocale livre, audiobook maker, convertir livre en audio gratuit, ebook to audiobook français, tts français gratuit, créer livre audio en ligne, convertisseur texte en voix, epub lecteur audio, de texte à livre audio, écouter ebook, livre parlé gratuit, epub en audio gratuit, pdf en audio gratuit",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Outil en ligne gratuit pour convertir des ebooks EPUB e PDF en livres audio MP3 avec des voix neuronales TTS IA. Prend en charge 6 langues et la génération de flux RSS podcast.",
    },
    "es": {
        "title":   "Audiobook Maker - EPUB/PDF a Audiolibro Gratis | MP3 y M4B con Capítulos",
        "tagline": "Convertidor Gratuito de EPUB y PDF a Audiolibro",
        "subtitle":"Convierte tus EPUB y PDF en audiolibros con voces neurales de alta calidad",
        "desc":    "Convierte tus ebooks EPUB y PDF en audiolibros MP3 y M4B (con capítulos incorporados) gratis con voces IA naturales. Convertidor online gratuito text-to-speech: sube tu libro, elige una voz y descarga tu audiolibro profesional. Sin instalación, funciona desde el navegador.",
        "kw":      "convertidor epub m4b, crear m4b con capítulos, convertidor epub audiolibro, convertidor pdf audiolibro, epub a audiolibro gratis, pdf a audiolibro gratis, convertir ebook a audiolibro online, crear audiolibro gratis, text to speech español, convertidor audiolibro online gratuito, epub a m4b, pdf a m4b, transformar ebook en audio, síntesis de voz libro, audiobook maker, convertir libro a audio gratis, ebook to audiobook español, tts español gratis, crear audiolibro en línea gratis, convertidor texto a voz, lector epub con audio, de texto a audiolibro, escuchar ebook, libro hablado gratis, epub a audio gratis, pdf a audio gratis",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Herramienta online gratuita para convertir ebooks EPUB y PDF en audiolibros MP3 con voces neuronales TTS IA. Soporta 6 idiomas y generación de feed podcast RSS.",
    },
    "de": {
        "title":   "Audiobook Maker: EPUB/PDF zu Hörbuch Gratis | MP3 & M4B mit Kapiteln",
        "tagline": "Kostenloser EPUB- & PDF-zu-Hörbuch-Konverter",
        "subtitle":"Konvertieren Sie EPUBs und PDFs in Hörbücher mit neuronalen Stimmen",
        "desc":    "Konvertieren Sie Ihre EPUB- und PDF-E-Books kostenlos in MP3- und M4B-Hörbücher (mit eingebetteten Kapiteln) mit natürlichen KI-Stimmen. Kostenloser Online Text-to-Speech Konverter: Laden Sie Ihr Buch hoch, wählen Sie eine Stimme und laden Sie Ihr professionelles Hörbuch herunter. Keine Installation nötig, funktioniert im Browser.",
        "kw":      "epub zu m4b konverter, m4b mit kapiteln erstellen, epub zu hörbuch konverter, pdf zu hörbuch konverter, epub in hörbuch umwandeln kostenlos, pdf in hörbuch umwandeln kostenlos, ebook in hörbuch umwandeln online, hörbuch erstellen kostenlos, text to speech deutsch, hörbuch konverter online kostenlos, epub zu m4b, pdf zu m4b, ebook in audio umwandeln, sprachsynthese buch, audiobook maker, buch in hörbuch umwandeln kostenlos, ebook to audiobook deutsch, tts deutsch kostenlos, hörbuch erstellen online gratis, text in sprache konverter, epub vorlesen lassen, text zu hörbuch, ebook anhören, hörbuch maker kostenlos, epub zu audio kostenlos, pdf zu audio kostenlos",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Kostenloses Online-Tool zum Konvertieren von EPUB- und PDF-E-Books in MP3-Hörbücher mit neuronalen KI-TTS-Stimmen. Unterstützt 6 Sprachen und Podcast-RSS-Feed-Generierung.",
    },
    "zh": {
        "title":   "Audiobook Maker - 免费 EPUB/PDF 转 MP3 及 M4B 有声书 | 支持章节和AI语音",
        "tagline": "免费EPUB和PDF转有声书转换器",
        "subtitle":"使用高品质神经语音将EPUB和PDF转换为有声读物",
        "desc":    "在您的浏览器中免费、安全、快速地将 EPUB 和 PDF 电�书转换为高质量 MP3 或 M4B（�章节）有声读物。由 AI 神经语音驱动。无需安装，支持章节选择和专业 M4B 格式输出。",
        "kw":      "epub转m4b, m4b有声书制作, epub转有声书, pdf转有声书, 免费epub转有声书, 免费pdf转有声书, 在线电�书转有声书, epub转mp3, pdf转mp3, 文字转语音有声书, 在线有声书制作, 电�书转有声书转换器, epub音频, pdf音频, 在线有声书制作工具, 将电�书转换为有声书, tts有声书生�器, 免费epub转mp3, 免费pdf转mp3, 免费文字转语音阅读器, ai有声书制作, epub有声书转换器, 电�书转mp3, �epub, 带音频的epub阅读器, 免费图书转有声书转换器",
        "ld_name": "Audiobook Maker",
        "ld_desc": "免费在线工具，利用神经网络AI文字转语音技术将EPUB和PDF电�书转换为MP3有声书。支持6种语言、章节选择和播客RSS订阅�生�。",
    },
}

_SUPPORTED_LANGS = list(_SEO_DATA.keys())  # ['it', 'en', 'fr', 'es', 'de', 'zh']

# Pre-rendering: una copia HTML per lingua, pronta a startup.
# Nessun costo a request-time; ogni risposta è un semplice return di stringa.
HTML_TEMPLATES: dict[str, str] = {
    lang: build_html_template(
        lang=lang,
        seo=seo,
        base_url=BASE_URL,
        version=__version__,
    )
    for lang, seo in _SEO_DATA.items()
}
# Fallback generico per URL sconosciuti
HTML_TEMPLATE = HTML_TEMPLATES["en"]

# Template dedicati per la root (/): canonical punta a BASE_URL/ (se stesso),
# non a /{lang}/. Risolve l'errore SEO "hreflang URL non usa il proprio canonical".
# Google crawla / e vede canonical=/, che corrisponde all'x-default negli hreflang.
HTML_ROOT_TEMPLATES: dict[str, str] = {
    lang: build_html_template(
        lang=lang,
        seo=seo,
        base_url=BASE_URL,
        version=__version__,
        canonical_url=f"{BASE_URL}/" if BASE_URL else "",
    )
    for lang, seo in _SEO_DATA.items()
}


def _detect_lang_from_request() -> str:
    """Rileva la lingua preferita dall'header Accept-Language del browser.

    Scorre i tag di qualità q= e restituisce la prima lingua supportata.
    Fallback: 'en'.
    """
    accept = request.headers.get("Accept-Language", "en")
    # Formato: "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
    tags = re.findall(r'([a-zA-Z]{2,3})(?:-[a-zA-Z0-9]+)*(?:;q=([0-9.]+))?', accept)
    # Ordina per q (default 1.0)
    ranked = sorted(tags, key=lambda t: float(t[1]) if t[1] else 1.0, reverse=True)
    for lang_tag, _ in ranked:
        lang = lang_tag.lower()
        if lang in _SUPPORTED_LANGS:
            return lang
    return "en"


@app.after_request
def _set_client_cookie(response):
    """Ensure every response carries the abm_cid cookie for client tracking."""
    if _CLIENT_COOKIE_NAME not in request.cookies:
        cid = str(uuid.uuid4())[:12]
        response.set_cookie(
            _CLIENT_COOKIE_NAME, cid,
            max_age=_CLIENT_COOKIE_MAX_AGE,
            httponly=True, samesite="Lax",
        )
    return response




# ----------------------------------------------------------------------
# AUTO-CLEANUP (deletes EPUB/PDF/TXT + MP3 files)
# ----------------------------------------------------------------------

# Regole di cancellazione:
# 1. Browser chiuso senza email registrata  →  cancella (heartbeat perso per 60s)
# 2. Utente scarica direttamente dall'UI web  →  cancella subito dopo download
# 3. Email di notifica inviata  →  mantieni 24h dall'invio, poi cancella
# 4. Job in errore o cancellato  →  cancella subito
# 5. Cartelle orfane su disco (non in jobs né in tokens)  →  cancella

CLEANUP_GRACE_AFTER_DOWNLOAD_SEC = 5 * 60  # 5 min grazia dopo download diretto
CLEANUP_HEARTBEAT_TIMEOUT_SEC = 60          # heartbeat perso per 60s = browser chiuso
CLEANUP_INTERVAL_SEC = 60                   # check every 60 seconds
CLEANUP_ORPHAN_DIR_AGE_SEC = 2 * 60 * 60   # cartelle orfane > 2h vengono rimosse


def _cleanup_job(job_id, reason=""):
    """Remove all files for a job and delete the job entry."""
    work_dir = UPLOAD_DIR / job_id
    if work_dir.exists():
        shutil.rmtree(str(work_dir), ignore_errors=True)
    jobs.pop(job_id, None)
    print(f"[cleanup] {job_id} removed ({reason})")


def _cleanup_loop():
    """Background thread: periodically clean up finished/abandoned jobs."""
    while True:
        time.sleep(CLEANUP_INTERVAL_SEC)
        now = time.time()
        to_remove = []

        for jid, job in list(jobs.items()):
            status = job.get("status", "")
            has_email = job.get("email_registered", False)

            #  -  -  Cancelled jobs: immediate cleanup  -  - 
            if status == "cancelled":
                to_remove.append((jid, "cancelled"))
                continue

            #  -  -  Error jobs: immediate cleanup  -  - 
            if status == "error":
                start = job.get("start_time", now)
                if (now - start) > 120:  # grazia di 2 min per leggere l'errore
                    to_remove.append((jid, "error"))
                continue

            #  -  -  Analyzed but never started: cleanup if heartbeat lost  -  - 
            if status == "analyzed":
                last_poll = job.get("last_poll", job.get("start_time", now))
                if (now - last_poll) > CLEANUP_HEARTBEAT_TIMEOUT_SEC * 3:  # 3 min per analyzed
                    to_remove.append((jid, "stale analyzed"))
                continue

            #  -  -  Optimizing jobs (LLM)  -  - 
            if status == "optimizing":
                if has_email:
                    continue  # batch mode: keep alive
                last_poll = job.get("last_poll", job.get("opt_start_time", now))
                if (now - last_poll) > CLEANUP_HEARTBEAT_TIMEOUT_SEC:
                    job["opt_cancelled"] = True
                    to_remove.append((jid, f"heartbeat lost during optimization ({int(now - last_poll)}s)"))
                continue

            #  -  -  Optimized jobs: ottimizzazione completata, in attesa di export/download  -  - 
            # Il progetto .abm va mantenuto per EMAIL_FILE_RETENTION_SEC (24h) dal termine
            # dell'ottimizzazione in qualunque caso  -  sia che l'utente abbia lasciato il
            # browser aperto, sia che sia stata registrata l'email per notifica batch.
            # La regola unifica lo scenario "no email" con quello email-batch: entrambi
            # hanno 24h dal completamento per scaricare il .abm tramite il bottone UI o
            # (se applicabile) il link email.
            if status == "optimized":
                opt_done = job.get("opt_completed_at") or job.get("email_sent_at") or now
                if (now - opt_done) > EMAIL_FILE_RETENTION_SEC:
                    reason = ("optimization email retention expired" if has_email
                              else "optimized project retention expired (24h)")
                    to_remove.append((jid, reason))
                continue

            #  -  -  Generating jobs  -  - 
            if status == "generating":
                # Con email registrata: non cancellare mai (continua in background)
                if has_email:
                    continue
                # Senza email: controlla heartbeat (browser chiuso = cancella)
                last_poll = job.get("last_poll", job.get("start_time", now))
                if (now - last_poll) > CLEANUP_HEARTBEAT_TIMEOUT_SEC:
                    job["cancelled"] = True  # segnala al thread di generazione
                    to_remove.append((jid, f"heartbeat lost during generation ({int(now - last_poll)}s)"))
                continue

            #  -  -  Done jobs  -  - 
            if status == "done":
                dl_at = job.get("downloaded_at")
                email_sent_at = job.get("email_sent_at")
                last_poll = job.get("last_poll", 0)

                # REGOLA 3: Email inviata  →  mantieni 24h dall'invio
                if has_email and email_sent_at:
                    if (now - email_sent_at) > EMAIL_FILE_RETENTION_SEC:
                        to_remove.append((jid, f"email retention expired ({int(now - email_sent_at)}s)"))
                    continue

                # Email registrata ma non ancora inviata  →  mantieni
                if has_email and not email_sent_at:
                    continue

                # REGOLA 2: Download diretto dall'UI  →  cancella dopo breve grazia
                if dl_at:
                    if (now - dl_at) > CLEANUP_GRACE_AFTER_DOWNLOAD_SEC:
                        to_remove.append((jid, f"downloaded {int(now - dl_at)}s ago"))
                    continue

                # REGOLA 1: Nessun download, nessuna email, heartbeat perso  →  browser chiuso
                if last_poll and (now - last_poll) > CLEANUP_HEARTBEAT_TIMEOUT_SEC:
                    to_remove.append((jid, f"abandoned (heartbeat lost {int(now - last_poll)}s)"))
                    continue

        for jid, reason in to_remove:
            try:
                _cleanup_job(jid, reason)
            except Exception as e:
                print(f"[cleanup] error removing {jid}: {e}")

        #  -  -  Cleanup expired download tokens  -  - 
        expired_tokens = [(t, info) for t, info in _download_tokens.items()
                          if (now - info["created_at"]) > EMAIL_FILE_RETENTION_SEC + 300]
        for t, t_info in expired_tokens:
            _download_tokens.pop(t, None)
            # Also cleanup job directory if job not in memory
            jid = t_info.get("job_id", "")
            if jid and jid not in jobs:
                job_dir = UPLOAD_DIR / jid
                if job_dir.exists():
                    shutil.rmtree(str(job_dir), ignore_errors=True)
                    print(f"[cleanup] Token-orphan dir removed: {jid}")
        if expired_tokens:
            _save_tokens()

        #  -  -  Cleanup cartelle orfane su disco  -  - 
        # Cartelle in UPLOAD_DIR non associate a nessun job né token attivo
        _known_job_ids = set(jobs.keys())
        _known_token_jobs = set(info.get("job_id", "") for info in _download_tokens.values())
        _all_known = _known_job_ids | _known_token_jobs
        try:
            for entry in UPLOAD_DIR.iterdir():
                if not entry.is_dir():
                    continue
                if entry.name.startswith("_"):
                    continue  # skip _download_tokens.json etc.
                if entry.name in _all_known:
                    continue  # still referenced
                # Check age: only remove if old enough
                try:
                    dir_age = now - entry.stat().st_mtime
                except OSError:
                    continue
                if dir_age > CLEANUP_ORPHAN_DIR_AGE_SEC:
                    shutil.rmtree(str(entry), ignore_errors=True)
                    print(f"[cleanup] Orphan dir removed: {entry.name} (age: {int(dir_age)}s)")
        except OSError:
            pass

        # Flush pending admin digest (rate-limited: max 1/hour)
        _try_send_admin_digest()


# ----------------------------------------------------------------------
# ENTRY POINT
# ----------------------------------------------------------------------

# Startup: load persisted download tokens, init DeepSeek, start background threads
# (works both under __main__ and Gunicorn)
_load_tokens()
_load_payments()
_load_vouchers()
_load_paid_opt_done()
_recover_orphaned_voucher_charges()
_init_deepseek()
if _paypal_available():
    print(f"[startup] PayPal payment enabled (mode: {PAYPAL_MODE}, "
          f"rate: {LLM_RATE_EUR_PER_MCHAR} EUR/Mchar, threshold: {LLM_FREE_THRESHOLD_EUR} EUR)")
else:
    print(f"[startup] PayPal payment disabled (ABM_PAYPAL_CLIENT_ID/SECRET not set)")
_cleanup_started = False

def _google_tts_reconcile_loop():
    """Thread di background: riconcilia il contatore Google TTS con Cloud Monitoring
    ogni GOOGLE_TTS_RECONCILE_INTERVAL_SEC secondi (default 30 minuti).
    Le metriche di Cloud Monitoring hanno latenza ~5 min, quindi un intervallo
    inferiore non porta beneficio."""
    if google_tts is None:
        return
    # Attesa iniziale per non sovraccaricare lo startup
    time.sleep(60)
    while True:
        try:
            if google_tts.is_available():
                result = google_tts.reconcile_with_cloud_monitoring()
                if result is None:
                    # Monitoring non disponibile: smettiamo di provarci
                    print("[google-tts] Reconcile loop: monitoring unavailable, stopping")
                    return
        except Exception as e:
            print(f"[google-tts] Reconcile loop error: {e}")
        time.sleep(GOOGLE_TTS_RECONCILE_INTERVAL_SEC)


GOOGLE_TTS_RECONCILE_INTERVAL_SEC = int(os.environ.get("ABM_GOOGLE_TTS_RECONCILE_INTERVAL", "1800"))


def _ensure_background_threads():
    global _cleanup_started
    if _cleanup_started:
        return
    _cleanup_started = True
    threading.Thread(target=get_voices, daemon=True).start()
    threading.Thread(target=_cleanup_loop, daemon=True).start()
    if google_tts is not None:
        threading.Thread(target=_google_tts_reconcile_loop, daemon=True).start()
    
    # Verifica dipendenze audio (ffmpeg/ffprobe) per formato M4B
    ffmpeg_ok, ffprobe_ok = _check_audio_dependencies()
    if not ffmpeg_ok or not ffprobe_ok:
        missing = []
        if not ffmpeg_ok: missing.append("ffmpeg")
        if not ffprobe_ok: missing.append("ffprobe")
        print(f"WARNING: Missing critical audio dependencies: {', '.join(missing)}. "
              "M4B generation and audio duration detection will be disabled.", file=sys.stderr)
    else:
        print("[startup] Audio dependencies (ffmpeg/ffprobe) found.")

    print(f"[startup] Background threads started (data dir: {UPLOAD_DIR})")
    print(f"[startup] Max concurrent per client: {MAX_CONCURRENT_PER_CLIENT}")
    print(f"[startup] Max concurrent LLM per client: {MAX_CONCURRENT_LLM_PER_CLIENT}")
    if _llm_available():
        print(f"[startup] LLM text optimization enabled (DeepSeek {DEEPSEEK_MODEL})")
    if ADMIN_EMAIL:
        print(f"[startup] Admin digest enabled  →  {ADMIN_EMAIL} (interval: {ADMIN_DIGEST_INTERVAL_SEC}s)")
    else:
        print("[startup] Admin digest disabled (ABM_ADMIN_EMAIL not set)")

_ensure_background_threads()

if __name__ == "__main__":
    PORT = 5601
    print(f"\n{'='*50}")
    print(f"  Audiobook Maker v{__version__}")
    print(f"  http://localhost:{PORT}")
    print(f"{'='*50}")
    print(f"  Script folder: {SCRIPT_DIR}")
    print(f"  Data folder:   {UPLOAD_DIR}")
    print(f"  Activity log:  {SCRIPT_DIR / 'activity_YYYY-MM.log'}")
    print(f"{'='*50}\n")
    app.run(host="127.0.0.1", port=PORT, debug=False)
