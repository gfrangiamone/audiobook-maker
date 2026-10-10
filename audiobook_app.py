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
import logging
import re
import json
import os
import i18n as _i18n
import seo_ld
from ratelimit import cooldown_counter as _cooldown_counter, sliding_check as _sliding_check
from client_identity import EMAIL_RE as _ACCT_EMAIL_RE, ip_salt as _ip_salt, mask_email as _mask_email_ci, salted_hash as _salted_hash
from fileio import atomic_write_json, data_dir, load_json
from env_utils import env_bool, env_float, env_int
import shutil
import sys

# Difesa: quando l'app gira come `python audiobook_app.py`, questo modulo e'
# registrato in sys.modules come '__main__', NON come 'audiobook_app'. Un
# qualsiasi `import audiobook_app` da un sub-modulo (vietato dalla convenzione
# #1, ma per sicurezza) lo ri-eseguirebbe da zero come secondo modulo,
# ri-spawnando cleanup/recover e ri-eseguendo configure(). L'alias fa puntare
# 'audiobook_app' a questo stesso modulo gia' caricato -> nessuna ri-esecuzione.
if __name__ == "__main__":
    sys.modules.setdefault("audiobook_app", sys.modules[__name__])

import threading
import time
import uuid
import hashlib
import hmac
import secrets
import html as html_mod
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from copy import copy
from pathlib import Path

from flask import (
    Flask, request, jsonify, g,
    send_file, Response, stream_with_context, redirect, after_this_request, abort
)
from werkzeug.middleware.proxy_fix import ProxyFix
import storage_backend
import storage_tiering

#  -  -  Import epub_to_tts (must be in the same folder)  -  -
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))


# --- Pagine HTML/testo servite da file (templates/pages/*) -------------------
# Le pagine admin, le pagine di download e i testi SEO stavano in stringhe
# Python di migliaia di righe (REGOLE_CODICE.md §7.1). Ora sono file:
# `_page_template` li legge una volta, `_render_page` sostituisce i segnaposto
# `__Pn__` nell'ordine dato (nessuna interpretazione di graffe o `%`).
from page_brand import page_template as _page_template, render_page as _render_page

# Startup timestamp for Last-Modified / Cache-Control on pre-rendered HTML pages
_STARTUP_TIME = datetime.now(timezone.utc)

try:
    from epub_to_tts import parse_epub
except ImportError:
    print("ERROR: epub_to_tts.py not found in the same folder.", file=sys.stderr)
    print(f"  Script folder: {SCRIPT_DIR}", file=sys.stderr)
    sys.exit(1)

try:
    from pdf_to_tts import parse_pdf
except ImportError:
    parse_pdf = None
    print("WARNING: pdf_to_tts.py not found  -  PDF support disabled.", file=sys.stderr)

#  -  -  Gemini TTS (Flash 2.5 / 3.1)  -  opzionale  -  -
try:
    import gemini_tts
except ImportError:
    gemini_tts = None
    print("[startup] gemini_tts module not available (google-genai not installed)")

#  -  -  Speechify Simba-3.2 (PREMIUM, solo inglese)  -  opzionale  -  -
import speechify_tts

#  -  -  VoxCPM2 (voci inventate via RunPod, catalogo importato)  -  opzionale  -  -
try:
    import voxcpm_catalog
    import voxcpm_tts
except Exception as _voxcpm_err:      # noqa: BLE001
    # Il catalogo e' un dato importato e il motore e' opzionale: se manca,
    # l'app parte lo stesso con tre motori invece di quattro.
    print(f"VoxCPM non disponibile: {_voxcpm_err}")
    voxcpm_catalog = None
    voxcpm_tts = None
# La classifica d'uso delle voci VoxCPM: modulo foglia (json + voice_utils),
# quindi importato senza rete di protezione.
import voxcpm_ranking
import voice_clone
import voice_clone_audio
import voice_clone_demo
import voice_clone_prompts
import voice_denoise

from audio_utils import (
    _extract_cover_from_epub, _generate_fallback_cover,
    _extract_cover_for_preview, _generate_podcast_rss,
    _safe_filename, _check_audio_dependencies, pcm_to_mp3,
    _generate_silence_mp3,
)


def _harden_console_encoding(out, err):
    """Console Windows cp1252: una print con caratteri non mappabili (es. '→')
    solleva UnicodeEncodeError e uccide il thread che logga (incidente locale
    2026-06-06: run di generazione morto in _prepare_m4b_cover_path).
    Con errors='replace' ogni print diventa innocua. No-op se lo stream non
    supporta reconfigure (pytest capture, pipe esotiche)."""
    for _stream in (out, err):
        try:
            _stream.reconfigure(errors="replace")
        except Exception:
            pass


if os.name == "nt":
    _harden_console_encoding(sys.stdout, sys.stderr)


def _preview_ffmpeg_ok():
    """Preflight ffmpeg per la preview PREMIUM (indirezione testabile)."""
    _ok, _ = _check_audio_dependencies()
    return bool(_ok)
from tts_split import (
    _plan_chunks, _pick_chunk_max_chars, _pick_chunk_max_bytes,
    prepare_tts_text,
)

import assembly_queue
import load_metrics
import token_store as _tkstore
import routes_tokens
import routes_admin_audit
import routes_admin_logs
import routes_admin_vouchers
import routes_admin_jobs
import routes_admin_community
import routes_dl
import routes_voice_clone
import recovery
import routes_community
import routes_mobile
import cleanup
import tts_engines
import jsonl_audit
import email_service
import push_service
import metrics_store
import free_quota
import free_tts_quota
import abuse_watch
import output_reuse
import privacy_content
import support_content
import payment
import generation_engine
import translation_core
import community_store
import community_translator
import community_moderator
import semantic_judge
import voice_language_guard
import transcript_judge
import pending_jobs
import db
import accounts
import account_page
import page_brand
import tts_backend_state
import user_stats
import activity_log

# Il business log vive in ABM_ACTIVITY_LOG_DIR se impostata (in prod la data
# dir, dopo lo spostamento della fase 2), altrimenti in SCRIPT_DIR. La
# callable e' risolta a ogni scrittura/lettura: patchare SCRIPT_DIR nei test
# basta a spostarlo. activity.db (ABM_ACTIVITY_DB=dual|db) sta accanto ai file.
def _activity_log_dir():
    return Path(os.environ.get("ABM_ACTIVITY_LOG_DIR") or SCRIPT_DIR)


activity_log.configure(log_dir=_activity_log_dir)

# Traduzioni delle pagine di download (i18n/download_pages.json, pagina -> lingua)
_DL_PAGES_I18N = _i18n.load("download_pages")

# Le pagine dei link dell'email (ripresa, dispositivi, cancellazione) nelle
# lingue dell'interfaccia: chi riceve l'email non passa dal sito e non ha modo
# di cambiare lingua da li'.
_VC_PAGES_I18N = _i18n.load("voice_clone_pages")
_ACCT_PAGES_I18N = _i18n.load("account_pages")

#  -  -  LLM per ottimizzazione testo TTS  -  opzionale  -  -
# (Configurati e gestiti in generation_engine.py; LLM_MODEL letto qui solo per startup log)
LLM_MODEL = os.environ.get("ABM_LLM_MODEL", "deepseek-chat")

def _llm_available():
    """True se l'ottimizzazione LLM è disponibile."""
    return generation_engine._llm_available()


def _estimate_chapter_seconds(ch, language):
    """Stima durata audio di un capitolo in secondi.

    Usa la stessa funzione di stima del pannello "Voci PREMIUM"
    (gemini_tts.estimate_audio_seconds con rate empirico) per allineare
    il dato mostrato nel pannello selezione capitoli con quello del
    pannello Premium. Fallback a 150 WPM se gemini_tts non disponibile.
    """
    try:
        if gemini_tts is not None:
            secs = gemini_tts.estimate_audio_seconds(
                getattr(ch, "text", "") or "",
                language=language,
                model_key="flash31",
                rate_pct=0,
            )
            if secs and secs > 0:
                return float(secs)
    except Exception:
        pass
    # Fallback: 150 WPM (storica)
    return (getattr(ch, "word_count", 0) or 0) * 60.0 / 150.0


# Payment / voucher state and operations live in payment.py.
# Re-exported names below keep the rest of audiobook_app.py working unchanged.
# Mutable state dicts (payment._payments, payment._vouchers, payment._paid_opt_done) are accessed via
# `payment.<name>` because _load_*() rebinds the module globals at startup.
from payment import (
    PAYPAL_CLIENT_ID, PAYPAL_MODE, PAYPAL_API_BASE,
    LLM_RATE_EUR_PER_MCHAR, LLM_FREE_THRESHOLD_EUR,
    VOUCHER_EXPIRY_DAYS, VOUCHER_BONUS_PERCENT,
    _paypal_available, _estimate_llm_cost_eur, _llm_apply_min_cost,
    _paypal_get_access_token, _paypal_create_order,
    _voucher_rl_check, _voucher_rl_record_result,
    _save_payments, _load_payments,
    _save_vouchers, _load_vouchers,
    _create_voucher,
    _voucher_remaining, _voucher_consume,
)


#  -  -  Import version and template builder  -  -
from version import __version__, get_formatted_date
from templates.index_page import build_html_template
from guide_content import build_guide_html, _guide_path
import seo_reviews
import seo_content

#  -  -  Import favicon data (embedded, served via Flask routes for SEO)  -  - 
from favicon_data import (
    get_favicon_ico, get_favicon_png_192,
    get_apple_touch_icon, get_favicon_svg,
)
from og_image_data import get_og_image



# ----------------------------------------------------------------------
# LOGGING CONFIG
# ----------------------------------------------------------------------

class HeartbeatFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return "/api/heartbeat" not in msg and "/api/job_status/" not in msg

logging.getLogger("werkzeug").addFilter(HeartbeatFilter())

# ----------------------------------------------------------------------
# APP CONFIG
# ----------------------------------------------------------------------

app = Flask(__name__)
# Reverse proxy (nginx) sits in front: trust one hop of X-Forwarded-* so request.remote_addr
# reflects the real client IP instead of 127.0.0.1 (needed for logs, rate limiting, fail2ban).
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["MAX_CONTENT_LENGTH"] = env_int("ABM_MAX_UPLOAD_MB", 50) * 1024 * 1024
# Static assets are cache-busted via ?v=__APP_VERSION__ so a 1-year max-age is safe.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 31536000  # 1 year

# Compressione gzip/brotli a livello applicativo. nginx in prod *potrebbe* già
# comprimere, ma la sua config non è garantita (gzip_proxied/gzip_types vanno
# impostati esplicitamente): flask-compress assicura la compressione di
# HTML/JSON/CSS/JS dinamici (~70% di transfer in meno, TTFB/LCP migliori su
# mobile). Import difensivo: se il pacchetto non è installato l'app parte uguale.
try:
    from flask_compress import Compress as _Compress
    _Compress(app)
except ImportError:
    pass

# Endpoint esenti da CSRF check (whitelist esplicita).
# Da aggiungere SOLO endpoint che ricevono webhook server-to-server (es. PayPal
# webhook firmato): attualmente nessuno.
_CSRF_EXEMPT_PATHS: set[str] = set()


@app.before_request
def _csrf_protect():
    """CSRF protection: verifica Origin/Referer su metodi mutating.

    - GET/HEAD/OPTIONS: nessun check (operazioni read-only).
    - POST/PUT/PATCH/DELETE: se ``Origin`` presente, deve matchare ``host_url``;
      altrimenti se ``Referer`` presente, stesso check. Se entrambi assenti
      (client non-browser come curl/script), passa.
    - I cookie ``SameSite=Strict`` (admin) e ``SameSite=Lax`` (abm_cid) gia'
      offrono difesa parziale; questo check chiude il gap residuo per browser
      vecchi e per ``SameSite=Lax`` su navigazioni top-level.
    """
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    if request.path in _CSRF_EXEMPT_PATHS:
        return None
    origin = request.headers.get("Origin", "")
    referer = request.headers.get("Referer", "")
    expected = request.host_url.rstrip("/")
    if origin:
        if not (origin == expected or origin.startswith(expected + "/")):
            return jsonify({"error": "CSRF: origin mismatch"}), 403
    elif referer:
        if not referer.startswith(expected + "/") and referer != expected:
            return jsonify({"error": "CSRF: referer mismatch"}), 403
    return None


@app.errorhandler(413)
def _handle_request_too_large(e):
    """Upload oltre MAX_CONTENT_LENGTH: risposta JSON invece della pagina HTML
    standard di Werkzeug. Il frontend fa r.json() sulla risposta di /api/analyze:
    senza questo handler l'utente vede un criptico "JSON.parse: unexpected
    character" invece di un messaggio sensato (bug riprodotto in prod)."""
    max_mb = app.config.get("MAX_CONTENT_LENGTH", 0) // (1024 * 1024)
    return jsonify({"error": "file_too_large", "max_mb": max_mb}), 413


@app.after_request
def add_security_headers(response):
    """Aggiunge header di sicurezza alle risposte HTTP."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # HSTS: forza HTTPS sui browser per 1 anno (incl. subdomain).
    # Nginx in produzione probabilmente lo aggiunge gia'; lo settiamo qui per
    # defense-in-depth ed evitare regressioni se la config nginx cambia.
    # Solo su HTTPS per non bloccare dev locale HTTP.
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    # Content Security Policy (base)
    # Permettiamo script inline per la nostra app (SPA-like) ma blocchiamo fonti esterne non autorizzate.
    # Nota: per una configurazione più rigida, bisognerebbe usare i nonce.
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://www.paypal.com https://www.googletagmanager.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://api.producthunt.com; "
        "media-src 'self' blob:; "
        "connect-src 'self' https://api-m.sandbox.paypal.com https://api-m.paypal.com https://*.google-analytics.com; "
        "frame-src https://www.paypal.com;"
    )
    # Cache-Control:
    #  - HTML: 1h cache + 1d stale-while-revalidate (lets CDN serve stale while
    #    refreshing in the background; reduces TTFB on Google crawls)
    #  - sitemap.xml / robots.txt / llms.txt: 1h cache (short — they may change
    #    when guides/translations are added)
    ct = response.content_type or ''
    path = (request.path or '') if request else ''
    if 'Cache-Control' not in response.headers:
        # Admin/API non devono mai essere cachati (cambi di stato real-time).
        if path.startswith('/admin') or path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
        elif 'text/html' in ct:
            # 5-min cache + 1h stale-while-revalidate: lets new approved
            # reviews surface in the embedded JSON-LD/visible block within a
            # few minutes while keeping repeat-visit perf high.
            response.headers['Cache-Control'] = (
                'public, max-age=300, stale-while-revalidate=3600'
            )
            response.headers['Last-Modified'] = _STARTUP_TIME.strftime('%a, %d %b %Y %H:%M:%S GMT')
        elif path in ('/sitemap.xml', '/robots.txt', '/llms.txt'):
            response.headers['Cache-Control'] = 'public, max-age=3600'
    # /dl/<token>: pagine e file di download fuori dall'indice. Difesa in
    # profondità: sono già in Disallow nel robots.txt, ma alcuni crawler lo
    # ignorano e potrebbero indicizzare l'URL token (thin/duplicate content).
    if path.startswith('/dl/') or path.startswith('/vc/'):
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response

# Directory di lavoro persistente (sopravvive ai restart del servizio)
# Configurabile via ABM_DATA_DIR (default in fileio.DEFAULT_DATA_DIR).
_DATA_DIR = str(data_dir())
UPLOAD_DIR = Path(_DATA_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Inizializza Gemini TTS (Flash 2.5/3.1)
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

# Inizializza JSON store community (news, feedback)
community_store.init(_DATA_DIR)
pending_jobs.init()  # richiede community_store.init() già chiamato
tts_backend_state.init(_DATA_DIR)
voice_clone.init(_DATA_DIR)
voice_clone_audio.init(_DATA_DIR)
voice_denoise.init(_DATA_DIR)

# Account opzionali (SQLite): il DB apre sempre, l'interruttore e' ABM_ACCOUNT_ENABLE.
try:
    db.init(_DATA_DIR)
    accounts.init_schema()
    accounts.configure(
        payments_path=Path(_DATA_DIR) / "_payments.json",
        voice_clone_ids_for_email_fn=voice_clone.ids_for_email,
        link_voice_fn=voice_clone.link_account,
        unlink_voice_fn=voice_clone.unlink_account,
        log_fn=lambda m: print(m, flush=True),
    )
    print(f"[startup] accounts: {'enabled' if accounts.enabled() else 'disabled'} ({db.DB_FILENAME})")
except Exception as e:
    print(f"[startup] accounts init failed (feature disabled): {e}", flush=True)

if gemini_tts is not None:
    def _on_tts_backend_switch(model_key, reason, detail, job_id):
        # Notifica IMMEDIATA (non nel digest): il margine in failover su
        # Vertex e' quasi nullo, ogni ora di ritardo costa margine su ogni
        # job servito nel frattempo.
        #
        # Due cose distinte, che una versione precedente confondeva:
        #  - `claim_credit_alert()` serve SOLO a sopprimere l'email di
        #    pre-allarme separata quando questo switch la anticipa. E' a
        #    consumo unico e resta l'unica via da cui quell'email parte: qui
        #    il suo valore di ritorno non decide piu' nulla di visibile.
        #  - il residuo mostrato nell'email si legge da `credit_left_usd()`,
        #    che e' PURA, ogni volta che c'e' un saldo dichiarato. Legarlo
        #    all'esito della claim lo faceva sparire proprio nel caso in cui
        #    serve di piu': credito gia' sotto soglia (pre-allarme gia'
        #    partito) significa claim `False`, cioe' email di failover senza
        #    il numero che ne spiega la causa.
        #  - a controllo spento (`ABM_CF_CREDIT_CHECK=0`) il residuo non
        #    viene allegato affatto: un numero calcolato su un saldo che
        #    nessuno aggiorna piu' - perche' la ricarica automatica lo
        #    rialza da sola - manderebbe l'admin a cercare un credito
        #    esaurito che non e' la causa del failover.
        credit = None
        try:
            tts_backend_state.claim_credit_alert()
            if (tts_backend_state.credit_check_enabled()
                    and tts_backend_state.credit_balance_usd() > 0):
                credit = tts_backend_state.credit_left_usd()
        except Exception:
            credit = None
        # Quando cadra' la prima sonda di rientro. Si legge dallo stato
        # persistito invece di ricalcolare `ABM_CF_PROBE_FIRST_SEC`: e'
        # gemini_tts a decidere se armarla (la causa del trip puo' non
        # essere sondabile), e leggere l'appuntamento vero e' l'unico modo
        # perche' l'email non prometta una sonda che nessuno ha fissato.
        probe_in = None
        try:
            nxt = tts_backend_state.probe_info(model_key).get("next_at")
            if nxt:
                probe_in = max(0, int(nxt - time.time()))
        except Exception:
            probe_in = None
        email_service.admin_notify_tts_backend_switch(
            model_key, reason, detail, job_id, credit_left_usd=credit,
            probe_first_sec=probe_in)
        # epoch=time.time() rende la chiave di dedup sempre nuova: a
        # differenza degli eventi di download (spam da prefetch, dedup
        # voluto), ogni switch di backend e' un fatto distinto anche a
        # parita' di session_id (qui sempre vuota) e operation. Senza epoch
        # la chiave (session_id, operation) resterebbe costante e il primo
        # switch del mese soffocherebbe in silenzio tutti quelli successivi
        # (modello diverso, o riarmo manuale seguito da nuova ricaduta) —
        # proprio l'evento che un'indagine forense va a cercare.
        _log_activity("", "", "TTS_BACKEND_SWITCH", "", "",
                      model_key, f"{reason}: {str(detail)[:80]}",
                      epoch=time.time())

    def _on_cf_credit_alert(model_key, credit_left_usd):
        # PRE-allarme, non allarme: arriva mentre Cloudflare e' ancora sano,
        # dopo l'addebito sul ledger che ha portato il residuo stimato sotto
        # ABM_CF_CREDIT_ALERT_USD. Email DEDICATA, mai quella di switch:
        # quella annuncia un failover gia' avvenuto e dice il contrario.
        # L'unicita' dell'invio e' garantita a monte da claim_credit_alert(),
        # che consuma atomicamente l'allarme: qui non serve (ne' esiste) un
        # secondo meccanismo di deduplica.
        email_service.admin_notify_cf_credit_low(
            model_key, credit_left_usd,
            tts_backend_state.credit_alert_threshold_usd())
        # epoch=time.time() per lo stesso motivo dello switch: ogni
        # pre-allarme e' un fatto distinto, non va soffocato dal dedup su
        # (session_id, operation).
        _log_activity("", "", "TTS_CF_CREDIT_LOW", "", "",
                      model_key, f"residuo stimato {credit_left_usd:.2f} USD",
                      epoch=time.time())

    def _on_tts_backend_return(model_key, probe_attempts, down_seconds):
        # Chiusura esplicita del failover aperto da `_on_tts_backend_switch`.
        # Immediata e non nel digest per la stessa simmetria: finche' non
        # arriva questa email l'admin deve assumere che il servizio giri su
        # Vertex, e un rientro annunciato il giorno dopo lo farebbe
        # intervenire a mano su un guasto gia' passato.
        credit = None
        try:
            if (tts_backend_state.credit_check_enabled()
                    and tts_backend_state.credit_balance_usd() > 0):
                credit = tts_backend_state.credit_left_usd()
        except Exception:
            credit = None
        email_service.admin_notify_tts_backend_return(
            model_key, probe_attempts=probe_attempts,
            down_seconds=down_seconds, credit_left_usd=credit)
        # epoch=time.time() per la stessa ragione dello switch: ogni rientro
        # e' un fatto distinto e non va soffocato dal dedup su
        # (session_id, operation), proprio nel caso - failover ripetuti sullo
        # stesso modello - che una forense va a cercare.
        _log_activity("", "", "TTS_BACKEND_RETURN", "", "",
                      model_key,
                      f"sonda riuscita dopo {probe_attempts} tentativi",
                      epoch=time.time())

    def _on_gemini_model_unavailable(model_key, detail, job_id):
        import gemini_availability
        email_service.admin_notify_gemini_model_unavailable(
            model_key, detail, job_id, gemini_availability.cooldown_sec())
        _log_activity("", "", "TTS_MODEL_UNAVAILABLE", "", "",
                      model_key, str(detail)[:80], epoch=time.time())

    gemini_tts.set_backend_switch_notifier(_on_tts_backend_switch)
    gemini_tts.set_credit_alert_notifier(_on_cf_credit_alert)
    gemini_tts.set_backend_return_notifier(_on_tts_backend_return)
    gemini_tts.set_model_unavailable_notifier(_on_gemini_model_unavailable)

jobs = {}
_jobs_lock = threading.Lock()  # Protects all reads/writes of `jobs` dict


from email_service import (
    _smtp_available, _send_email, _admin_notify_generation,
    _try_send_admin_digest, _send_payment_receipt_email, ADMIN_EMAIL,
    BASE_URL, ADMIN_DIGEST_INTERVAL_SEC, _try_send_voxcpm_digest,
    VOXCPM_DIGEST
)

EMAIL_FILE_RETENTION_SEC = env_int("ABM_JOB_RETENTION_SEC", 64800)  # 18h default
# Override per job con voce PREMIUM (Gemini): retention piu' lunga perche'
# i pagamenti Premium meritano una finestra di download/email piu' ampia.
GEMINI_FILE_RETENTION_SEC = env_int("ABM_GEMINI_JOB_RETENTION_SEC", 172800)  # 48h default
# Condivisione audiolibro app->app: la risorsa share scade dopo questo TTL
# (default 24 h). Il file upload (caso senza job) ha un tetto di dimensione.
ABM_SHARE_TTL_SEC = env_int("ABM_SHARE_TTL_SEC", 86400)
ABM_SHARE_MAX_BYTES = env_int("ABM_SHARE_MAX_BYTES", 500 * 1024 * 1024)
ABM_SHARE_UPLOAD_TTL_SEC = env_int("ABM_SHARE_UPLOAD_TTL_SEC", 3600)
# Hard cap caratteri per audiolibro completo (taglia output audio):
# - standard (edge-tts/Google): ABM_MAX_TEXT_CHARS
# - PREMIUM (gemini:): ABM_MAX_GEMINI_TEXT_CHARS, tipicamente piu' basso perche'
#   le voci Gemini hanno cost-per-char piu' alto e RPM/RPD piu' restrittive.
MAX_TEXT_CHARS = env_int("ABM_MAX_TEXT_CHARS", 1500000)
MAX_GEMINI_TEXT_CHARS = env_int("ABM_MAX_GEMINI_TEXT_CHARS", 800000)
# Voci Speechify (PREMIUM, solo inglese): stesso cap di Gemini per default,
# override indipendente disponibile.
MAX_SPEECHIFY_TEXT_CHARS = env_int("ABM_MAX_SPEECHIFY_TEXT_CHARS", MAX_GEMINI_TEXT_CHARS)
# Cap caratteri VoxCPM. Allineato a quello Speechify: il limite non e' del
# motore ma del portafoglio dell'utente e del tempo di attesa.
MAX_VOXCPM_TEXT_CHARS = env_int("ABM_MAX_VOXCPM_TEXT_CHARS", MAX_SPEECHIFY_TEXT_CHARS)

# Whitelist charset per gli id voce ricevuti dal client (edge
# "it-IT-IsabellaNeural", google "it-IT-Chirp3-HD-Zephyr", gemini
# "gemini:flash31:Zephyr", voxcpm "voxcpm:v2:it-IT/Stefano" — "/" separa
# locale e nome nel catalogo di voci inventate). Difesa in profondita' contro
# stored XSS nelle pagine admin e injection nel formato "#"-separato
# dell'Activity Log.
# Id voce ammessi: lettere e cifre di qualunque alfabeto (\w), segni
# combinanti (forma NFD di "Chloé" mandata da qualche browser), ':' '.' '-'
# '/' e lo spazio. L'id VoxCPM e' `voxcpm:v2:<locale>/<Nome>` e 27 voci del
# catalogo portano il nome accentato (Chloé, Álvaro, João), 4 cinesi lo
# portano con uno spazio (Peiyu 3): la vecchia classe ASCII le rifiutava con
# "Invalid voice id." a generazione gia' avviata. Restano fuori < > " ' # e
# a capo: e' la difesa anti-XSS sul log admin, non un vincolo di alfabeto.
_VOICE_ID_RE = re.compile(r"^[\w\u0300-\u036f:.\-/ ]{1,80}$")
# Mese del business log (activity_YYYY-MM.log): vincola il nome file
# costruito dal parametro utente.
_YM_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Tolleranza di crescita del testo dovuta all'ottimizzazione AI. Un libro che
# era ENTRO il cap prima dell'ottimizzazione (precondizione garantita dal cap
# enforced in /api/optimize e /api/optimize_estimate sul testo originale) puo'
# superare il cap fino a questa frazione DOPO l'espansione LLM ed essere
# comunque generato, invece di essere rifiutato a valle. Default 5%.
LLM_OPT_GROWTH_TOLERANCE = env_float("ABM_LLM_OPT_GROWTH_TOLERANCE", 0.05, floor=0.0)


# Predicato voce PREMIUM Gemini: definizione unica in voice_utils (modulo foglia).
from voice_utils import is_gemini_voice as _is_gemini_voice
from voice_utils import is_premium_voice as _is_premium_voice
from voice_utils import is_speechify_voice as _is_speechify_voice
# Interruttore per modello PREMIUM (ABM_<MODELLO>_ENABLE, default abilitato).
from voice_utils import voice_model_enabled as _voice_model_enabled
from voice_utils import voice_model_key as _voice_model_key
from voice_utils import parse_rate_pct as _parse_rate_pct


def _premium_model_gate(voice):
    """Risposta 400 se la voce appartiene a un modello PREMIUM disattivato.

    Il modello si spegne con `ABM_<MODELLO>_ENABLE=false` (default abilitato):
    ABM_FLASH31_ENABLE, ABM_FLASH38_ENABLE, ABM_SIMBA32_ENABLE. Il gate copre
    solo gli ingressi HTTP (anteprima, stime, ordine PayPal, generazione,
    ottimizzazione con auto-generate): i job gia' registrati o pagati
    proseguono, cosi' spegnere un modello non trasforma un lavoro in corso in
    un rimborso. Ritorna None quando la voce e' ammessa.
    """
    # Voce Gemini di un modello non piu' in catalogo (flash25 ritirato il
    # 27/09/2026): stesso esito di un modello spento, mai un 500 da
    # parse_voice_id piu' a valle.
    if _is_gemini_voice(voice) and gemini_tts is not None:
        mk = _voice_model_key(voice)
        if mk and mk not in gemini_tts.GEMINI_MODELS:
            return jsonify({"error": "voice_model_disabled",
                            "error_code": "voice_model_disabled",
                            "model_key": mk}), 400
        # Modello a canale unico acceso ma senza backend risolvibile (es.
        # ABM_FLASH38_ENABLE senza ABM_GEMINI_API_KEY): il catalogo lo
        # nasconde gia', ma una pagina vecchia o una richiesta diretta farebbe
        # pagare un job che fallisce al primo chunk. Stesso esito del modello
        # non disponibile. Limitato ai modelli `mark_unavailable_on_fatal`:
        # flash31 ha il suo percorso (is_available/kill-switch + failover).
        _single = bool((gemini_tts.GEMINI_MODELS.get(mk) or {}).get(
            "mark_unavailable_on_fatal")) if mk else False
        if mk and (gemini_tts.model_unavailable(mk)
                   or (_single and _voice_model_enabled(voice)
                       and gemini_tts._resolve_backend(mk) is None)):
            return jsonify({"error": "voice_model_unavailable",
                            "error_code": "voice_model_unavailable",
                            "model_key": mk}), 503
    if _voice_model_enabled(voice):
        return None
    return jsonify({"error": "voice_model_disabled",
                    "error_code": "voice_model_disabled",
                    "model_key": _voice_model_key(voice)}), 400
from voice_utils import is_voxcpm_voice as _is_voxcpm_voice


def _max_text_chars_for_voice(voice):
    """Cap caratteri appropriato per la voce: Gemini -> MAX_GEMINI_TEXT_CHARS,
    Speechify -> MAX_SPEECHIFY_TEXT_CHARS, VoxCPM -> MAX_VOXCPM_TEXT_CHARS,
    altrimenti MAX_TEXT_CHARS."""
    if _is_gemini_voice(voice):
        return MAX_GEMINI_TEXT_CHARS
    if _is_voxcpm_voice(voice):
        return MAX_VOXCPM_TEXT_CHARS
    if _is_speechify_voice(voice):
        return MAX_SPEECHIFY_TEXT_CHARS
    return MAX_TEXT_CHARS


def _effective_max_text_chars(voice, job=None):
    """Cap caratteri EFFETTIVO per la generazione/pagamento.

    Identico a _max_text_chars_for_voice per i job non ottimizzati. Per i job
    gia' ottimizzati con AI (`job["ai_optimized"]`) concede la tolleranza
    LLM_OPT_GROWTH_TOLERANCE (default 5%) sul cap base: un libro che era entro i
    limiti prima dell'ottimizzazione e che l'espansione LLM ha portato di poco
    oltre viene comunque elaborato. NON usare questo helper per il cap PRE-
    ottimizzazione (/api/optimize, /api/optimize_estimate): li' va applicato il
    cap base sul testo originale, che e' la precondizione di questa tolleranza."""
    base = _max_text_chars_for_voice(voice)
    if isinstance(job, dict) and job.get("ai_optimized"):
        return int(base * (1.0 + LLM_OPT_GROWTH_TOLERANCE))
    return base


def _retention_for_job(job):
    """Retention sec applicabile al job: GEMINI_FILE_RETENTION_SEC se voce PREMIUM (Gemini, Speechify, VoxCPM), altrimenti EMAIL_FILE_RETENTION_SEC.
    La finestra di disponibilità per l'utente NON dipende dal cold storage: il
    cold determina solo DOVE si serve il file (locale durante la finestra calda,
    presigned URL dopo), non QUANTO a lungo resta disponibile.
    Fallback su `opt_voice` per il flusso optimize-only/batch dove `voice` non e' ancora settato."""
    if not isinstance(job, dict):
        return EMAIL_FILE_RETENTION_SEC
    v = job.get("voice", "") or job.get("opt_voice", "")
    return GEMINI_FILE_RETENTION_SEC if _is_premium_voice(v) else EMAIL_FILE_RETENTION_SEC


def _retention_for_token_info(info):
    """Retention sec applicabile a un download token: usa is_gemini se salvato sul token.
    Indipendente dal cold storage (vedi _retention_for_job)."""
    return GEMINI_FILE_RETENTION_SEC if (isinstance(info, dict) and info.get("is_gemini")) else EMAIL_FILE_RETENTION_SEC


# Protezione no-download per voci PREMIUM (costose): se il job/token Gemini
# non ha mai registrato un download, raddoppiamo la retention base prima di
# cancellare gli output. Salvaguardia per utenti che ricevono l'email tardi
# o non aprono subito il link. E' l'UNICA eccezione che estende la finestra
# di disponibilità oltre la retention base; non si applica alle voci standard
# ne' ai job PREMIUM gia' scaricati. Indipendente dal cold storage.
GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER = 2


def _effective_retention_for_job(job):
    """Retention con protezione no-download per job PREMIUM/Gemini.
    Se il job e' Gemini e non risulta alcun download (job["downloaded_at"] vuoto),
    raddoppia la retention base. Per voci standard: identica a _retention_for_job."""
    base = _retention_for_job(job)
    if not isinstance(job, dict):
        return base
    v = job.get("voice", "") or job.get("opt_voice", "")
    if _is_premium_voice(v) and not job.get("downloaded_at"):
        return base * GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER
    return base


def _effective_retention_for_token_info(info):
    """Retention con protezione no-download per token PREMIUM/Gemini.
    Se il token e' is_gemini e nessun /dl/<token>/* ha mai servito il file
    (downloaded_at vuoto), raddoppia la retention base."""
    base = _retention_for_token_info(info)
    if isinstance(info, dict) and info.get("is_gemini") and not info.get("downloaded_at"):
        return base * GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER
    return base


def _mark_token_downloaded(token_info):
    """Registra che il file del token e' stato servito (download reale, non
    probe/HEAD/Range). Aggiorna token_info in-place e persiste su disco per
    sopravvivere ai restart, disattivando la protezione no-download
    (_effective_retention_for_token_info). Idempotente: skip su probe/HEAD/
    Range e se gia' marcato."""
    try:
        if _is_resume_or_probe_request():
            return
    except Exception:
        pass
    if not isinstance(token_info, dict):
        return
    if token_info.get("downloaded_at"):
        return
    token_info["downloaded_at"] = time.time()
    try:
        _tkstore.save_tokens()
    except Exception as e:
        print(f"[tokens] _mark_token_downloaded persist failed: {e}")


def _mark_token_redirected(token_info):
    """Registra che il file del token e' stato INSTRADATO al cold storage (302
    verso presigned URL), non consegnato: i byte vanno da R2 all'utente senza
    passare da noi e non sappiamo se il download sia riuscito.

    NON tocca `downloaded_at`, quindi NON disattiva la protezione no-download
    di _effective_retention_for_token_info: un presigned rifiutato (incidente
    2026-08-25, filtro IP client sul token R2) non deve costare all'utente
    PREMIUM meta' della finestra di disponibilita'. Il campo serve solo a
    lasciare traccia del tentativo per la diagnostica."""
    try:
        if _is_resume_or_probe_request():
            return
    except Exception:
        pass
    if not isinstance(token_info, dict):
        return
    if token_info.get("redirected_at"):
        return
    token_info["redirected_at"] = time.time()
    try:
        _tkstore.save_tokens()
    except Exception as e:
        print(f"[tokens] _mark_token_redirected persist failed: {e}")


#  -  -  Admin activity digest (email log)  -  -
# Set ABM_ADMIN_EMAIL to enable. Leave empty to disable.
#   export ABM_ADMIN_EMAIL=gfrangiamone@gmail.com
# Rate limited: max 1 digest email per hour, batches all pending events.
# Token admin per UI web /admin/vouchers. Se vuoto, l'endpoint è disabilitato.
ADMIN_TOKEN = os.environ.get("ABM_ADMIN_TOKEN", "").strip()


ADMIN_DISABLED_MSG = "Admin UI disabled"
ADMIN_UNAUTHORIZED_MSG = "Unauthorized"


def admin_required(fn=None, *, as_json=True):
    """Guardia admin per una route, sotto `@app.route`. Una forma sola (E2a,
    2026-10-09): ADMIN_TOKEN vuoto (UI spenta) -> 404 "Admin UI disabled";
    token assente o sbagliato -> 0,5 s di attesa (anti brute-force) e 401
    "Unauthorized". JSON `{"error": ...}` per le API, testo per le route che
    rispondono HTML/testo (`as_json=False`). Fino alla 3.99 le stesse 32
    route avevano sei forme (401/403, `forbidden`, con/senza sleep e 404).
    Si usa come `@admin_required` o `@admin_required(as_json=False)`."""
    import functools

    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not ADMIN_TOKEN:
                return (jsonify({"error": ADMIN_DISABLED_MSG}), 404) if as_json else (ADMIN_DISABLED_MSG, 404)
            if not _admin_auth_ok(_admin_auth_from_request()):
                time.sleep(0.5)  # rallenta brute-force
                return ((jsonify({"error": ADMIN_UNAUTHORIZED_MSG}), 401) if as_json
                        else (ADMIN_UNAUTHORIZED_MSG, 401))
            return f(*args, **kwargs)
        return wrapper
    return deco(fn) if fn is not None else deco

#  -  -  Client tracking & rate limiting  -  - 
# Max concurrent generating jobs per client device (cookie-based).
# Set via ABM_MAX_CONCURRENT_PER_CLIENT env var; default 2.
MAX_CONCURRENT_PER_CLIENT = env_int("ABM_MAX_CONCURRENT_PER_CLIENT", 2)

# Max concurrent LLM optimization jobs per client device.
# Set via ABM_MAX_CONCURRENT_LLM_PER_CLIENT env var; default 1.
MAX_CONCURRENT_LLM_PER_CLIENT = env_int("ABM_MAX_CONCURRENT_LLM_PER_CLIENT", 1)

# Tetto GLOBALE di generazioni simultanee sull'istanza (tutti i client).
# Incidente 2026-08-21: il solo cap per-client non limita nulla lato server —
# 19 generazioni contemporanee (77 avviate in 3 ore) da client diversi hanno
# saturato RAM+swap fino al thrash livelock. Set via ABM_MAX_CONCURRENT_GLOBAL;
# 0 = illimitato (comportamento pre-fix).
MAX_CONCURRENT_GLOBAL = env_int("ABM_MAX_CONCURRENT_GLOBAL", 6)

# Cookie name and max-age for client identification
_CLIENT_COOKIE_NAME = "abm_cid"
_CLIENT_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # 1 year
_MOBILE_CID_HEADER = "X-ABM-Cid"
_MOBILE_CID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _get_client_id():
    """Return the client_id from mobile header or cookie, or empty string."""
    hdr = (request.headers.get(_MOBILE_CID_HEADER) or "").strip()
    if hdr and _MOBILE_CID_RE.match(hdr):
        return hdr
    return request.cookies.get(_CLIENT_COOKIE_NAME, "")


# Quota gratuita cumulativa per client sui TTS premium: unico punto di
# decisione, condiviso da /api/combined_estimate, /api/paypal_create_order_gemini,
# /api/generate e /api/optimize. Divergenze fra questi punti producono il
# guasto gia' visto nell'incidente "402 Speechify" (UI dice gratis, backend 402).
_premium_quota_decision = free_quota.decision


def _quota_client_id(job=None):
    """Sorgente UNICA del client_id per la quota premium.

    Priorita': (1) `job["client_id"]`, fissato all'analyze; (2) cookie/header
    della richiesta corrente. Il fallback e' obbligatorio perche' il cookie
    `abm_cid` viene emesso solo dall'after_request: un job nato da una prima
    richiesta diretta a /api/analyze (pagina da cache, cookie scaduto a tab
    aperta, client API) ha `client_id=""` e finirebbe nel bucket condiviso
    `_anon`, mentre stima e ordine PayPal leggerebbero il cookie nuovo e
    vedrebbero quota piena -> UI "Gratis" + backend 402 (incidente "402
    Speechify"). Tutti i punti di enforcement devono usare questa funzione.
    """
    cid = ""
    if isinstance(job, dict):
        cid = (job.get("client_id") or "").strip()
    return cid or _get_client_id()


def _pricing_chapters(job_id, job, chapters):
    """Capitoli con TESTO GARANTITO, da usare in ogni calcolo di prezzo.

    Su un job gia' passato da uno stato terminale (done/partial/error/
    cancelled) i testi capitolo sono serializzati su disco e svuotati dalla RAM
    (`generation_engine.spill_job_texts`): `ch.text` e' "" mentre `ch.char_count`
    conserva la lunghezza reale. Stimare su quei capitoli produce un prezzo di
    listino ~0 -> la decisione quota lo dichiara sotto soglia -> la voce PREMIUM
    parte SENZA pagamento, e subito dopo `run_generation` reidrata i testi e
    sintetizza il libro intero (incidente Q9lQN3RrapCvGLSonVnzmA: job da 50k+
    caratteri quotato 0,35€ di listino, costo reale a doppia cifra).

    Ritorna copie superficiali dei capitoli con il testo riletto dallo spill:
    il job NON viene reidratato (nessun ritorno dei testi in RAM) e gli oggetti
    originali non vengono mutati.
    """
    if not isinstance(job, dict) or not job.get("_texts_spilled"):
        return chapters
    try:
        texts = generation_engine.chapter_texts(job_id, job)
    except Exception as e:
        print(f"[{job_id}] _pricing_chapters: rilettura spill fallita: {e}", flush=True)
        return chapters
    out = []
    for ch in chapters:
        txt = texts.get(getattr(ch, "index", None)) or getattr(ch, "text", "") or ""
        if txt == (getattr(ch, "text", "") or ""):
            out.append(ch)
            continue
        ch2 = copy(ch)
        try:
            ch2.text = txt
        except Exception:
            out.append(ch)
            continue
        out.append(ch2)
    return out


def _assert_priced_on_real_text(job_id, chapters, chars_priced):
    """Fail-closed: il prezzo non deve MAI essere calcolato su testo mancante.

    Difesa in profondita' dietro `_pricing_chapters`: se i capitoli dichiarano
    caratteri (`char_count`, che sopravvive allo spill) ma il testo effettivamente
    quotato e' vuoto, la stima e' priva di significato e regalerebbe un job
    PREMIUM. Meglio un errore esplicito che una generazione gratuita.
    """
    declared = sum(getattr(ch, "char_count", 0) or 0 for ch in chapters)
    if declared > 0 and (chars_priced or 0) <= 0:
        print(f"[{job_id}] PREZZO SU TESTO VUOTO: {declared} char dichiarati, "
              f"0 quotati -> richiesta rifiutata (fail-closed)", flush=True)
        return False
    return True


def _free_quota_log(job_id, decision, charged=False):
    """Traccia la decisione di quota su stdout (best-effort)."""
    try:
        verdict = ("charge(%.2f)" % decision["due_eur"]) if not decision["is_free"] else "free"
        if decision.get("free_cap_exceeded"):
            verdict += (f" [libro {int(decision.get('book_chars') or 0):,} chars > cap "
                        f"gratuito {int(decision.get('free_cap_chars') or 0):,}]")
        print(f"[{job_id}] free quota: used={decision['quota_used_eur']:.2f}/"
              f"{decision['quota_limit_eur']:.2f}€ list={decision['list_total_eur']:.2f}€ "
              f"-> {verdict}{' consumed' if charged else ''}", flush=True)
    except Exception:
        pass


def _free_quota_key(job_id, voice, chs_sel, all_chs):
    """Chiave di addebito della quota gratuita per QUESTA generazione.

    Incidente 21/09/2026 (Zur1gsLrTEaQjtdTPa7LLg): con la chiave = job_id un
    libro da 5 EUR e' stato letto gratis un capitolo per volta sullo stesso
    job. La chiave porta voce e capitoli (free_quota.charge_key); una selezione
    esplicita di tutti i capitoli e' normalizzata a "libro intero", cosi'
    `selected_chapters=[]` e `[0..n-1]` non valgono come due generazioni.
    """
    try:
        idx = [getattr(ch, "index", None) for ch in (chs_sel or [])]
        idx = [i for i in idx if i is not None]
        all_idx = [getattr(ch, "index", None) for ch in (all_chs or [])]
        all_idx = [i for i in all_idx if i is not None]
        if not idx or set(idx) == set(all_idx):
            idx = None
        return free_quota.charge_key(job_id, voice, idx)
    except Exception:
        return job_id


def _free_quota_book_chars(info, all_chs=None):
    """Caratteri del libro INTERO per il cap gratuito (free_quota.decision).
    `info.total_chars` sopravvive allo spill dei testi su disco; il fallback
    somma i char_count dei capitoli."""
    try:
        tc = int(getattr(info, "total_chars", 0) or 0)
        if tc > 0:
            return tc
        chs = all_chs if all_chs is not None else list(getattr(info, "chapters", []) or [])
        return int(sum(int(getattr(ch, "char_count", 0) or 0) for ch in chs))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Price lock (D1): il prezzo quotato al create dell'ordine PayPal e' il prezzo
# dovuto alla conferma.
# ---------------------------------------------------------------------------
# La stima TTS PREMIUM non e' deterministica nel tempo: estimate_audio_seconds
# divide i caratteri per una media mobile empirica (gemini_tts_rate_log.json)
# alimentata in tempo reale dalle generazioni di TUTTI i client. Fra il momento
# in cui l'utente paga e il momento in cui conferma passano secondi o minuti, e
# in quella finestra il prezzo si muove da solo. Il consumo del token confronta
# `pagato + 0.05 >= dovuto_ricalcolato_ora`: quando la deriva supera i 5 cent il
# token viene rifiutato con 402, il job non parte e la capture PayPal resta
# orfana (nessun path pre-consumo emette refund) finche' il job non viene
# purgato come "stale analyzed" -> alert di rimborso manuale.
#
# Incidente 21/08/2026, job N-RUN2qrc2blK82lRX_NdA: ordine creato alle 08:45:51
# per 5,86€, capture alle 08:46:26, conferma alle 08:46:31 con dovuto
# ricalcolato a 6,00€ (+2,4%: tre campioni nuovi nel rate log, due molto lenti,
# avevano abbassato la media mobile del 2,34%). Stessa firma sull'orfano del
# 14/08 (4,08€ pagati vs 4,17€ pretesi, +2,2%).
#
# Il lock e' registrato per order_id (non per job): con piu' ordini creati sullo
# stesso job — succede col doppio click sul bottone di pagamento — ognuno porta
# l'importo effettivamente quotato per quell'ordine. La firma degli input di
# prezzo (voce, capitoli, velocita', lingua, AI on/off) e' registrata insieme
# all'importo: se l'utente cambia qualcosa fra pagamento e conferma la firma non
# combacia, il lock non si applica e il ricalcolo torna a essere quello vivo.
_PRICE_LOCK_TTL_SEC = env_int("ABM_PRICE_LOCK_TTL_SEC", 1800)
_PRICE_LOCK_MAX_PER_JOB = 8


def _pricing_signature(voice_id, chapter_indexes, rate, lang, ai_opt):
    """Firma canonica degli input che determinano il prezzo combinato.

    `chapter_indexes` sono gli indici dei capitoli EFFETTIVI su cui e' calcolata
    la stima (non la lista grezza del client): "nessuna selezione" e "tutti i
    capitoli selezionati" devono produrre la stessa firma, altrimenti il lock
    non si applicherebbe mai nel caso piu' comune.
    """
    try:
        _sel = ",".join(str(int(i)) for i in sorted(chapter_indexes or []))
    except (TypeError, ValueError):
        _sel = ""
    return "|".join([
        (voice_id or "").strip(),
        _sel,
        str(rate or "+0%").strip(),
        (lang or "").strip().lower(),
        "1" if ai_opt else "0",
    ])


def _price_lock_store(job, order_id, sig, total_eur):
    """Congela l'importo quotato per `order_id` sul job (in memoria)."""
    if not isinstance(job, dict) or not order_id:
        return
    now = time.time()
    locks = job.get("price_locks")
    if not isinstance(locks, dict):
        locks = {}
    for _oid in [k for k, v in locks.items()
                 if now - float((v or {}).get("ts", 0) or 0) > _PRICE_LOCK_TTL_SEC]:
        locks.pop(_oid, None)
    while len(locks) >= _PRICE_LOCK_MAX_PER_JOB:
        locks.pop(next(iter(locks)), None)  # dict ordinato: esce il piu' vecchio
    locks[order_id] = {"sig": sig, "total_eur": round(float(total_eur), 2), "ts": now}
    job["price_locks"] = locks


def _price_lock_lookup(job, token, sig):
    """Importo lockato al create per questo token, o None se non applicabile.

    None (-> si usa il ricalcolo vivo) quando: il token non e' un ordine creato
    per questo job, gli input di prezzo sono cambiati, oppure il lock e' oltre
    TTL (a quel punto il prezzo di ore prima non e' piu' difendibile).
    """
    if not isinstance(job, dict) or not token:
        return None
    rec = (job.get("price_locks") or {}).get(token)
    if not isinstance(rec, dict) or rec.get("sig") != sig:
        return None
    try:
        if time.time() - float(rec.get("ts", 0) or 0) > _PRICE_LOCK_TTL_SEC:
            return None
        _tot = round(float(rec.get("total_eur", 0) or 0), 2)
        # Un lock a zero non esiste (nessun ordine PayPal viene creato per un
        # importo nullo): trattalo come assente invece di azzerare il dovuto.
        return _tot if _tot > 0 else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Quote lock (D2): il prezzo MOSTRATO all'utente e' il prezzo con cui si crea
# l'ordine PayPal / si scala il voucher.
# ---------------------------------------------------------------------------
# Il price lock sopra copre l'anello create-ordine -> conferma. Restava scoperto
# quello a monte: /api/combined_estimate quota l'importo che finisce nel modale
# di pagamento, /api/paypal_create_order_gemini lo ricalcola da zero e rifiuta
# con "amount mismatch" appena i due divergono di piu' di un centesimo. In mezzo
# la media mobile del rate log si muove — e si muove per colpa dell'utente
# stesso: ogni anteprima audio registra un campione (record_rate_sample in
# /api/preview_audio), e ascoltare le voci prima di pagare e' il comportamento
# normale su una voce PREMIUM.
#
# Dal 20/08/2026 (commit 933caa6) il rate empirico e' raggruppato per
# (lingua, voce, rate_step) con almeno 40 campioni per gruppo: sulle lingue con
# pochi dati un singolo campione nuovo puo' far attraversare la soglia e
# cambiare il tier di fallback, spostando il prezzo di punti percentuali interi.
# Con la tolleranza a 0,01€ ASSOLUTI, su un libro da ~25€ (0,04%) il pagamento
# diventa impossibile: segnalazione utente 30/08/2026, voce tedesca,
# server=24,58 vs client=24,10, riproducibile a ogni tentativo.
#
# Il lock e' chiavizzato sulla firma degli input di prezzo (non su un token:
# alla stima nessun token esiste ancora). Se l'utente cambia voce, capitoli,
# velocita', lingua o AI on/off la firma non combacia piu' e il ricalcolo torna
# a essere quello vivo. TTL breve: oltre la finestra il prezzo di mezz'ora fa
# non e' piu' difendibile e si riparte dalla stima corrente.
_QUOTE_LOCK_TTL_SEC = env_int("ABM_QUOTE_LOCK_TTL_SEC", 1800)
_QUOTE_LOCK_MAX_PER_JOB = 8


def _quote_lock_store(job, sig, total_eur):
    """Congela l'importo quotato da /api/combined_estimate per la firma `sig`.

    Store separato da `price_locks`: le firme si accumulano mentre l'utente
    prova voci e selezioni diverse, e non devono sfrattare i lock d'ordine
    PayPal, che valgono soldi gia' incassati.
    """
    if not isinstance(job, dict) or not sig:
        return
    try:
        total = round(float(total_eur), 2)
    except (TypeError, ValueError):
        return
    if total <= 0:
        return  # niente da congelare: sotto soglia non si paga
    now = time.time()
    locks = job.get("quote_locks")
    if not isinstance(locks, dict):
        locks = {}
    for _sig in [k for k, v in locks.items()
                 if now - float((v or {}).get("ts", 0) or 0) > _QUOTE_LOCK_TTL_SEC]:
        locks.pop(_sig, None)
    locks.pop(sig, None)  # ri-quotazione: la firma torna in coda, non resta vecchia
    while len(locks) >= _QUOTE_LOCK_MAX_PER_JOB:
        locks.pop(next(iter(locks)), None)  # dict ordinato: esce il piu' vecchio
    locks[sig] = {"total_eur": total, "ts": now}
    job["quote_locks"] = locks


def _quote_lock_lookup(job, sig):
    """Importo quotato all'ultima stima per questa firma, o None se assente,
    scaduto o non piu' applicabile."""
    if not isinstance(job, dict) or not sig:
        return None
    rec = (job.get("quote_locks") or {}).get(sig)
    if not isinstance(rec, dict):
        return None
    try:
        if time.time() - float(rec.get("ts", 0) or 0) > _QUOTE_LOCK_TTL_SEC:
            return None
        _tot = round(float(rec.get("total_eur", 0) or 0), 2)
        return _tot if _tot > 0 else None
    except (TypeError, ValueError):
        return None


_PLATFORM_HEADER = "X-ABM-Platform"
_PLATFORM_RE = re.compile(r"^(android|ios)$")


def _client_platform():
    """Provenienza della richiesta: 'android'/'ios' se app (header X-ABM-Platform
    valido + X-ABM-Cid valido), 'web' se solo cookie abm_cid, '' altrimenti."""
    plat = (request.headers.get(_PLATFORM_HEADER) or "").strip().lower()
    hdr_cid = (request.headers.get(_MOBILE_CID_HEADER) or "").strip()
    if _PLATFORM_RE.match(plat) and hdr_cid and _MOBILE_CID_RE.match(hdr_cid):
        return plat
    if request.cookies.get(_CLIENT_COOKIE_NAME, ""):
        return "web"
    return ""


def _acquisition_from_request():
    """(acquisition_source, acquisition_platform) dal cookie abm_acq."""
    v = (request.cookies.get("abm_acq") or "").strip().lower()
    if not v:
        return "", ""
    plat = v if v in ("android", "ios") else ""
    return "app", plat


def _apply_app_attribution(resp):
    """Se la home è aperta con utm_source=app, conta l'arrivo e imposta il cookie
    di attribuzione abm_acq (30gg, first-touch). resp deve essere una Response."""
    if (request.args.get("utm_source") or "").strip().lower() != "app":
        return resp
    plat = (request.args.get("app_platform") or "").strip().lower()
    plat = plat if plat in ("android", "ios") else "app"
    try:
        metrics_store.incr("web_visit_from_app", plat)
    except Exception:
        pass
    existing = request.cookies.get("abm_acq")
    value = existing if existing else plat  # first-touch: non sovrascrive
    resp.set_cookie("abm_acq", value, max_age=2592000, samesite="Lax",
                    secure=bool((BASE_URL or "").startswith("https")), httponly=False)
    return resp


def _new_job_id():
    """Generate a high-entropy job identifier (128 bit, URL-safe).
    Never starts with ``_`` — the ``_`` prefix is the protected system
    namespace (``_payments.json``, ``_vouchers.json``, …) and the cleanup
    loop skips all dirs starting with it.  ``_`` occurs in 1/64
    url-safe-base64 IDs; this loop keeps rolling until we get one
    without it."""
    while True:
        jid = secrets.token_urlsafe(16)
        if not jid.startswith("_"):
            return jid


def _check_job_owner(job_id):
    """Validate that the calling client owns the requested job.

    Returns (job, error_response, status_code). On success error_response is None
    and the caller may use `job`. On failure caller must `return error_response, status_code`.

    Ownership rule: the cookie-stored client_id must match jobs[job_id]['client_id'].
    Jobs predating this enforcement (no client_id stored) are allowed through to preserve
    backward compatibility, but new jobs always store it at creation.

    Admin bypass: una richiesta autenticata come admin (header X-Admin-Token o cookie
    abm_admin_session valido) passa il controllo. Necessario per la pagina /admin/log-activity che
    fa polling di /api/job_status/<job_id> per mostrare la % delle conversioni in corso.
    """
    if job_id not in jobs:
        return None, jsonify({"error": "Job not found"}), 404
    job = jobs[job_id]
    owner = job.get("client_id", "")
    if owner:
        caller = _get_client_id()
        # `prior_client_ids`: owner precedenti a un transfer verso l'app mobile
        # (api_transfer_claim), che restano autorizzati sul job.
        if caller and caller in (job.get("prior_client_ids") or ()):
            return job, None, 0
        if not caller or caller != owner:
            # Admin bypass: l'admin puo' osservare lo stato di qualunque job.
            if _admin_auth_ok(_admin_auth_from_request()):
                return job, None, 0
            return None, jsonify({"error": "Forbidden"}), 403
    else:
        # Legacy job senza client_id (creato prima dell'enforcement). Lascia
        # passare per compat ma logga warning: l'admin puo' monitorare e
        # decidere di rimuovere il bypass dopo che la coorte legacy e' esaurita.
        print(f"[SECURITY-WARN] Legacy job senza client_id: {job_id} "
              f"(status={job.get('status', '?')}) - bypass ownership check")
    return job, None, 0


def _mask_email(email):
    """Maschera un'email per display: 'john.doe@x.com' -> 'j***@x.com'.

    Mostra solo la prima lettera della parte locale + il dominio. Best-effort:
    su input malformato ritorna l'input invariato.
    """
    return _mask_email_ci(email, invalid=None)


def client_ip() -> str:
    """IP del client: `request.remote_addr`, gia' risolto da ProxyFix(x_for=1)
    sull'ULTIMO hop di X-Forwarded-For (quello scritto da nginx).

    Mai rileggere X-Forwarded-For a mano: nginx fa append
    ($proxy_add_x_forwarded_for) e non ha trusted proxy a monte
    (docs/FORENSICS_PLAYBOOK.md), quindi il primo elemento dell'header e'
    scritto dal client e con esso si aggiravano rate limit per IP, limiti
    voucher e hash IP dei dossier abuso. Unica funzione per tutto il modulo
    (REGOLE_CODICE.md §8.1).
    """
    return request.remote_addr or ""


# Cookie posato dalla SPA (setLang e boot) con la lingua scelta nell'app:
# le pagine rese dal server (/account, /auth/<token>, /vc/...) lo leggono
# per seguirla invece di Accept-Language.
_LANG_COOKIE = "abm_lang"


def _get_browser_lang():
    """Return primary browser language from Accept-Language header (e.g. 'it', 'en', 'fr')."""
    return _i18n.browser_lang(request.headers.get("Accept-Language", ""))


def _gen_owner_cid(j):
    """Client a cui e' imputata la generazione in corso.

    `gen_owner_cid` viene fissato quando il job rivendica lo slot e NON cambia
    piu': `client_id` invece si sposta quando l'app mobile adotta il job
    (`/api/transfer` -> `job["client_id"] = cid`). Contare su `client_id`
    liberava lo slot del client web a meta' generazione, e bastava trasferire
    ogni job all'app subito dopo l'avvio per aggirare del tutto il tetto
    (agosto 2026: un client con 8 generazioni contemporanee, tutte trasferite
    ~2 minuti dopo il GENERATE).
    """
    return j.get("gen_owner_cid") or j.get("client_id") or ""


def _active_generating_for_client_unlocked(client_id, exclude_job_id=None):
    """Generazioni FREE in corso imputate a questo client.

    Internal: caller MUST hold _jobs_lock.

    I job PREMIUM sono esclusi dal conteggio: chi paga (voce Gemini/Speechify
    o pagamento incassato) non ha tetto e non consuma gli slot della corsia
    gratuita. Criterio unico `generation_engine.is_premium_job`, lo stesso di
    coda di assembly e telemetria.
    """
    if not client_id:
        return 0
    return sum(
        1 for jid, j in jobs.items()
        if j.get("status") == "generating"
        and jid != exclude_job_id
        and _gen_owner_cid(j) == client_id
        and not generation_engine.is_premium_job(j)
    )


def _client_gen_cap_reached(client_id, exclude_job_id=None):
    """True se il client ha saturato il tetto di generazioni FREE contemporanee.

    Prende _jobs_lock internamente: chiamarla SOLO fuori dal blocco atomico di
    claim (che usa _active_generating_for_client_unlocked). Iniettata in
    generation_engine per il ramo auto-gen post-ottimizzazione, che chiama
    run_generation direttamente senza passare da /api/generate.
    """
    if not client_id or MAX_CONCURRENT_PER_CLIENT <= 0:
        return False, 0, MAX_CONCURRENT_PER_CLIENT
    with _jobs_lock:
        active = _active_generating_for_client_unlocked(client_id, exclude_job_id)
    return active >= MAX_CONCURRENT_PER_CLIENT, active, MAX_CONCURRENT_PER_CLIENT


def _active_generating_total_unlocked():
    """Internal: caller MUST hold _jobs_lock. Generazioni attive sull'istanza."""
    return sum(1 for j in jobs.values() if j.get("status") == "generating")


def _server_at_capacity():
    """(at_capacity, active, cap) sul tetto globale di generazioni.

    Prende _jobs_lock internamente: chiamarla SOLO fuori dal blocco atomico
    di claim dello slot (che usa _active_generating_total_unlocked).
    """
    cap = MAX_CONCURRENT_GLOBAL
    if cap <= 0:
        return False, 0, cap
    with _jobs_lock:
        active = _active_generating_total_unlocked()
    return active >= cap, active, cap


def _server_busy_response(job_id="", where="", premium=False):
    """429 server_busy se l'istanza e' al tetto globale, altrimenti None.

    Va invocata PRIMA di chiedere un pagamento: l'utente deve sapere che il
    server e' sovraccarico prima di pagare, non dopo (incidente 2026-08-21).
    Il controllo dentro il blocco atomico di /api/generate resta come guardia
    finale sulla race fra il gate anticipato e il claim dello slot.
    """
    at_capacity, active, cap = _server_at_capacity()
    if not at_capacity:
        return None
    load_metrics.incr("rej_busy_p" if premium else "rej_busy")
    print(f"[{job_id or '-'}] {where or 'richiesta'} rifiutata: tetto globale "
          f"raggiunto ({active}/{cap})", flush=True)
    return jsonify({
        "error": "The server is at capacity right now. "
                 "Please try again in a few minutes.",
        "error_code": "server_busy",
        "max": cap,
        "active": active,
    }), 429


def _refund_payment_on_orphan(job_id, job, reason):
    """Refund Gemini payment if /api/generate rejected after the token was consumed.

    Mirrors generation_engine._refund_gemini_payment: voucher → _voucher_refund
    (riaccredito silenzioso sull'originale, ritorna None), paypal → emette voucher
    di rimborso (ritorna il codice, per inserirlo nella mail). Best-effort;
    non-fatal on errors. Clears job['payment'] so a retry doesn't see stale state.
    """
    payment_meta = job.get("payment") or {}
    tok = payment_meta.get("token")
    # total_eur e' la sola quota TTS: nel pagamento combinato la quota AI sta
    # in llm_eur e va resa anch'essa, il testo ottimizzato senza audio non
    # serve (stessa regola di generation_engine._refund_gemini_payment).
    amt = round(float(payment_meta.get("total_eur", 0) or 0)
                + float(payment_meta.get("llm_eur", 0) or 0), 2)
    method = payment_meta.get("method", "")
    refund_code = None
    if not tok or amt <= 0:
        return None
    try:
        # Guard persistente anti-doppio-refund (specchio di
        # generation_engine._refund_gemini_payment): il pop di job["payment"]
        # sotto previene il doppio refund nello stesso processo, ma non
        # sopravvive a un restart. Nel recovery (_orphan_fallback) un job_like
        # viene ricostruito dal descrittore: senza questo controllo un re-run
        # dopo crash duplicherebbe il rimborso (incidente classe B1).
        if payment.has_refund_for_job(job_id, tok):
            print(f"[{job_id}] orphan refund skipped: persistent refund trace "
                  f"already exists (reason={reason})")
            return None
        if method == "voucher":
            payment._voucher_refund(tok, amt, job_id=job_id, reason=reason)
        elif method == "paypal":
            pay = payment._payments.get(tok, {})
            email = pay.get("email", "") or ""
            if email:
                refund_code, _ = payment._create_voucher(
                    email, amt, origin_order_id=tok, origin_job_id=job_id,
                    kind="refund", note=f"refund {reason} job {job_id}",
                )
            else:
                print(
                    f"[{job_id}] WARNING: orphan refund voucher not emitted — "
                    f"PayPal order {tok} has no buyer email "
                    f"(amount {amt:.2f} EUR, reason {reason})"
                )
            # Free up the PayPal order to be re-spent (or leave used=True and let
            # the refund voucher carry the value forward; we choose refund voucher
            # to keep idempotency simple)
    except Exception as e:
        print(f"[{job_id}] orphan refund failed ({reason}, non-fatal): {e}")
    finally:
        job.pop("payment", None)
    return refund_code


def _build_job_descriptor(job, phase):
    """Snapshot scalare del job sufficiente a ricostruirlo dopo un restart.
    `phase`: 'optimize' (job in ottimizzazione) o 'generate' (job in/verso TTS).
    L'input originale e l'eventuale .abm ottimizzato vivono su disco; qui si
    salvano solo path + parametri."""
    from pathlib import Path
    fname = job.get("original_filename", "") or ""
    kind = (Path(fname).suffix.lower().lstrip(".") or "epub")
    return {
        "input_path": job.get("epub_path", ""),       # path file caricato (qualsiasi tipo)
        "input_kind": kind,
        "abm_path": job.get("optimized_abm_path", ""), # presente solo se LLM completato
        # Libro tradotto adottato (/api/translate_adopt): sostituisce input_path
        # come sorgente del recovery, ma non implica ottimizzazione AI.
        "adopted_abm_path": job.get("adopted_abm_path", ""),
        "ai_optimized": bool(job.get("ai_optimized")),
        # Per i job optimize-batch con auto-generate i parametri TTS vivono sotto
        # prefisso opt_* (non ancora promossi a job["voice"] ecc.): fallback su quelli.
        "voice": job.get("voice") or job.get("opt_voice", ""),
        "rate": job.get("rate") or job.get("opt_rate", "+0%"),
        "single_file": bool(job.get("single_file", job.get("opt_single_file", True))),
        "output_format": job.get("output_format") or job.get("opt_output_format", "m4b"),
        "podcast_base_url": (job.get("notify_base_url", "") or job.get("podcast_base_url", "")
                             or job.get("opt_podcast_base_url", "")),
        "gemini_style_instruction": job.get("gemini_style_instruction"),
        "selected_chapters": job.get("opt_selected_chapters") or job.get("selected_chapters"),
        # Chiave di addebito della quota gratuita gia' consumata da questo job
        # (free_quota.charge_key): il recovery la riusa, cosi' la stessa
        # generazione non viene contata due volte. Assente nei descrittori
        # scritti prima del 21/09/2026 -> il recovery ripiega sul job_id nudo,
        # che e' la chiave con cui quei job hanno addebitato.
        "free_quota_key": job.get("free_quota_key"),
        "opt_auto_generate": bool(job.get("opt_auto_generate")),
        # Lettura opzionale testo tra parentesi: preserva la scelta utente attraverso
        # un restart (altrimenti il recovery batch rigenererebbe col default rimozione).
        "read_round_parens": bool(job.get("read_round_parens", False)),
        "read_square_brackets": bool(job.get("read_square_brackets", False)),
        # Copie amministrative (indagine) agganciate a un job ancora in corso:
        # sopravvivono a un restart così il COMPLETE post-recovery le materializza.
        "admin_copy_cids": list(job.get("admin_copy_cids", []) or []),
        "notify_email": job.get("notify_email", ""),
        "notify_download_type": job.get("notify_download_type", "audio"),
        "notify_base_url": job.get("notify_base_url", ""),
        "notify_lang": job.get("notify_lang", "en"),
        # Lingua di lettura TTS/ottimizzazione: senza questi campi il recovery
        # post-restart ricostruiva il job senza lingua e run_optimization
        # cadeva sul default hardcoded "it", caricando il prompt italiano su un
        # libro di altra lingua (es. incidente kd8XQj6WWdrZJt1_z0VMPQ: prompt it
        # su libro es). _audit_language e run_optimization leggono opt_lang/
        # gen_lang/lang, quindi vanno persistiti.
        "lang": job.get("lang", ""),
        "opt_lang": job.get("opt_lang", ""),
        "gen_lang": job.get("gen_lang", ""),
        "browser_lang": job.get("browser_lang", ""),
        "platform": job.get("platform", ""),
        "gemini_accent": job.get("gemini_accent"),
        "speechify_emotion": job.get("speechify_emotion", ""),
        # Passo VoxCPM congelato al primo avvio (velocita' della voce
        # campionata): il recovery non deve rileggere quella corrente.
        "voxcpm_voice_pace": job.get("voxcpm_voice_pace"),
        "original_filename": fname,
        "client_id": job.get("client_id", ""),
        "client_ip": job.get("client_ip", ""),
        "payment": job.get("payment"),
    }


def _job_paid_eur(job):
    """Importo incassato per il job: pocket `payment.total_eur` (price lock D1)
    o, in sua assenza, `payment_amount_eur`."""
    try:
        pocket = job.get("payment") or {}
        v = pocket.get("total_eur")
        if v is None:
            v = job.get("payment_amount_eur")
        return float(v or 0)
    except Exception:
        return 0.0


def _job_book_title(job):
    info = job.get("info")
    return (getattr(info, "title", "") or job.get("original_filename", "") or "")[:200]


def _arm_email_delivery(job, job_id, email, *, lang="en", output_format=None,
                        podcast_base_url="", pending_kind="", engine="", force=False):
    """Porta il job in modalita' email sull'indirizzo dato: notifica a fine
    lavoro, esenzione dall'heartbeat (`email_registered`), marker pending e
    descrittore di recupero. Idempotente per default: se un'email e' gia'
    registrata non tocca nulla. `force=True` scavalca il guard e sovrascrive
    un'email gia' armata (es. quella del pagamento) — usato SOLO da
    _apply_account_to_job: l'account, quando c'e' una sessione, ha sempre
    precedenza sull'email del pagamento (PayPal/voucher), qualunque cosa sia
    gia' stata armata da _register_paid_job_batch o dai blocchi batch di
    /api/optimize e /api/translate. Usata dal batch implicito dei job pagati e
    dalla notifica forzata degli utenti con account."""
    if job.get("email_registered") and not force:
        return False
    email = (email or "").strip()
    if not email:
        return False
    job["notify_email"] = email
    if output_format is not None:
        job.setdefault("notify_download_type",
                       "podcast" if output_format == "zip_rss" else "audio")
        job.setdefault("notify_base_url", podcast_base_url or "")
    job["notify_lang"] = lang or "en"
    job["email_registered"] = True
    job["_auto_batch_notify"] = True
    cleanup._write_email_pending_marker(UPLOAD_DIR / job_id)
    if pending_kind:
        try:
            pending_jobs.register(job_id, pending_kind,
                                  _build_job_descriptor(job, pending_kind))
        except Exception as _e:
            print(f"[{job_id}] pending_jobs.register ({engine or 'batch'}) "
                  f"failed (non-fatal): {_e}", flush=True)
    print(f"[{job_id}] {engine or 'batch'} -> email mode (notify {_mask_email(email)}, "
          f"heartbeat disabilitato)", flush=True)
    return True


def _acct_forced_batch(batch, email):
    """Notifica forzata: con sessione attiva il job e' sempre batch
    sull'email dell'account, qualunque cosa dica il body."""
    try:
        if accounts.enabled() and _smtp_available():
            acct = _current_account()
            if acct:
                return True, acct["email"]
    except Exception as _e:
        print(f"WARNING _acct_forced_batch: {_e}", flush=True)
    return batch, email


def _apply_account_to_job(job, job_id, kind, *, output_format=None, podcast_base_url="",
                          voice="", lang=""):
    """Se la richiesta ha una sessione: consegna via email all'account (senza
    descrittore: lo scrive la partenza) e riga nello storico. `force=True`
    sull'arming: l'account ha sempre la precedenza sull'email del pagamento,
    anche se un pagamento (PayPal/voucher) l'ha gia' armata su un altro
    indirizzo prima di questa chiamata. `voice` e' l'id grezzo del provider
    (es. 'it-IT-IsabellaNeural'): viene convertito in etichetta presentabile
    via _voice_public_label prima di finire nello storico, mai passato cosi'
    com'e'. La riga di storico di un ALTRO account non viene mai riassegnata
    (record_job e' un upsert su job_id): la notifica resta forzata all'account
    della sessione, lo storico resta di chi ce l'ha. Best-effort."""
    try:
        if not accounts.enabled() or not _smtp_available():
            return None
        acct = _current_account()
        if not acct:
            return None
        _arm_email_delivery(job, job_id, acct["email"], lang=acct.get("lang") or lang or "en",
                            output_format=output_format, podcast_base_url=podcast_base_url,
                            pending_kind="", engine="account", force=True)
        # Stessa guardia di /api/register_email: senza, un secondo account che
        # rigenera lo stesso job_id (browser condiviso, job ripreso da un'altra
        # sessione) si porterebbe via lo storico del primo.
        _owner = accounts.job_owner(job_id)
        if _owner is not None and _owner != acct["id"]:
            print(f"WARNING [{job_id}] storico: riga gia' dell'account {_owner}, "
                  f"non riassegnata a {acct['id']}", flush=True)
        else:
            _engine, _model = _voice_plan_info(voice)
            accounts.record_job(acct["id"], job_id, kind=kind, book_title=_job_book_title(job),
                                output_format=output_format or "", voice=_voice_public_label(voice),
                                lang=lang or "", paid_eur=_job_paid_eur(job),
                                source="forced", status="running",
                                engine=_engine, model=_model)
        return acct
    except Exception as _e:
        print(f"[{job_id}] _apply_account_to_job failed (non-fatal): {_e}", flush=True)
        return None


def _register_paid_job_batch(job_id, job, payment_token, *, engine="",
                             lang="", email="", output_format=None,
                             podcast_base_url="", pending_kind="generate"):
    """Batch implicito per job PAGATO: un job per cui l'utente ha pagato NON
    deve morire per heartbeat alla chiusura del browser. Registra l'email del
    pagamento come notifica -> email_registered=True esenta il job
    dall'heartbeat (generation_engine `_check_cancelled`) e fa consegnare il
    risultato via email (o solo il rimborso su errore reale),
    indipendentemente dalla sessione del client. Idempotente se l'utente aveva
    gia' registrato un'email via /api/register_email.

    Vale sia per PayPal (email del pagatore) sia per VOUCHER (email associata
    al buono): in entrambi i casi la consegna e' garantita e il frontend mostra
    il box di notifica precompilato e disabilitato, senza l'avviso "se chiudi
    la pagina viene annullato" (non veritiero).

    Chiamata da /api/generate (preflight pagamento premium) e da /api/optimize
    (pagamento combinato LLM+TTS del wizard, che chiama run_generation diretto
    bypassando /api/generate). Senza la chiamata dal wizard il job pagato resta
    esposto all'auto-cancel a 60s — incidente 89eGMA9eVVgUxxVOA-fpuA
    (12/09/2026: job da 22,40 EUR ucciso al 20%).

    `email`: email gia' risolta dal chiamante (record pagamento/voucher); se
    vuota si interroga payment.email_for_token.
    `output_format`: se None i campi notify_download_type/notify_base_url non
    vengono toccati (il ramo /api/optimize li imposta a valle sui parametri
    opt_*).
    `pending_kind`: fase del descrittore di recupero, o "" per non registrarlo
    (in /api/optimize la registrazione avviene a valle, dopo i parametri opt_*).

    Ritorna True se ha attivato il batch adesso.
    """
    if job.get("email_registered"):
        return False
    _pay_email = (email or "").strip()
    if not _pay_email:
        try:
            _pay_email = payment.email_for_token(payment_token)
        except Exception as _e:
            print(f"[{job_id}] email_for_token failed (non-fatal): {_e}", flush=True)
            _pay_email = ""
    if not _pay_email:
        return False
    armed = _arm_email_delivery(job, job_id, _pay_email, lang=lang,
                                output_format=output_format,
                                podcast_base_url=podcast_base_url,
                                pending_kind=pending_kind, engine=engine)
    # Storico account: un pagamento con email nota aggancia il job all'account
    # (se esiste) anche senza sessione; e' l'adozione "in corso d'opera".
    try:
        _engine, _model = _voice_plan_info(job.get("voice") or "")
        if accounts.enabled() and accounts.attach_if_known(
                job_id, _pay_email, kind=pending_kind or "generate",
                book_title=_job_book_title(job), output_format=output_format or "",
                voice=_voice_public_label(job.get("voice") or ""),
                engine=_engine, model=_model,
                lang=lang or "", paid_eur=_job_paid_eur(job)):
            _acct_log("ACCOUNT_ADOPT", _pay_email, job_id)
    except Exception as _e:
        print(f"[{job_id}] accounts.attach_if_known failed (non-fatal): {_e}", flush=True)
    return armed


def _sniff_input_kind(path):
    """Tipo del file dai magic bytes: 'pdf' | 'epub' | 'abm' | 'txt'.
    Serve ai descrittori legacy con input_path privo di estensione (upload con
    nome interamente non-ASCII salvati come '<jobdir>/pdf'): senza sniffing il
    dispatch per suffisso li mandava tutti a parse_txt e il recovery falliva."""
    import zipfile
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
    except OSError:
        return "txt"
    if head[:4] == b"%PDF":
        return "pdf"
    if head[:2] == b"PK" and zipfile.is_zipfile(str(path)):
        try:
            with zipfile.ZipFile(str(path), "r") as zf:
                names = set(zf.namelist())
        except Exception:
            return "txt"
        if "manifest.json" in names:
            return "abm"
        if "mimetype" in names or any(n.lower().endswith(".opf") for n in names):
            return "epub"
    return "txt"


def _parse_book(path):
    """Ri-parsa un file su disco nello stesso modo di /api/analyze, ritornando
    il BookInfo. Dispatch per estensione, con fallback sui magic bytes quando
    l'estensione manca. Usato dal recupero job orfani.
    parse_abm ritorna (info, cover_info): qui si scarta la cover."""
    import os
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext not in ("epub", "pdf", "abm", "txt"):
        ext = _sniff_input_kind(path)
    if ext == "epub":
        return parse_epub(path)
    if ext == "pdf":
        if parse_pdf is None:
            raise RuntimeError("PDF parser non disponibile (PyMuPDF mancante)")
        return parse_pdf(path)
    if ext == "abm":
        info, _cover = parse_abm(path)
        return info
    return parse_txt(path)


# E3 (seam recovery orfani, 2026-10-10): gate, ri-accodatura, ripiego e giro
# di recupero in recovery.py. Helper della app passati come lambda (risolti a
# ogni chiamata: i test li sostituiscono su questo modulo).
recovery.configure(
    _jobs_lock=_jobs_lock,
    jobs=lambda: jobs,
    _abuse_reset_recovery_markers=lambda *a, **k: _abuse_reset_recovery_markers(*a, **k),
    _assert_priced_on_real_text=lambda *a, **k: _assert_priced_on_real_text(*a, **k),
    _effective_max_text_chars=lambda *a, **k: _effective_max_text_chars(*a, **k),
    _free_quota_book_chars=lambda *a, **k: _free_quota_book_chars(*a, **k),
    _free_quota_log=lambda *a, **k: _free_quota_log(*a, **k),
    _log_activity=lambda *a, **k: _log_activity(*a, **k),
    _parse_book=lambda *a, **k: _parse_book(*a, **k),
    _premium_quota_decision=lambda *a, **k: _premium_quota_decision(*a, **k),
    _refund_payment_on_orphan=lambda *a, **k: _refund_payment_on_orphan(*a, **k),
    _smtp_available=lambda *a, **k: _smtp_available(*a, **k),
    _voice_for_log=lambda *a, **k: _voice_for_log(*a, **k),
    _voice_model_key=lambda *a, **k: _voice_model_key(*a, **k),
    run_generation=lambda *a, **k: run_generation(*a, **k),
    run_optimization=lambda *a, **k: run_optimization(*a, **k))



def _active_optimizing_for_client_unlocked(client_id):
    """Internal: caller MUST hold _jobs_lock. Conta i job LLM attivi
    (ottimizzazione O traduzione) del client."""
    if not client_id:
        return 0
    return sum(
        1 for j in jobs.values()
        if j.get("client_id") == client_id
        and j.get("status") in ("optimizing", "translating")
    )


FAVICON_B64 = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCI+CiAgPGRlZnM+CiAgICA8bGluZWFyR3JhZGllbnQgaWQ9ImJnIiB4MT0iMCUiIHkxPSIwJSIgeDI9IjEwMCUiIHkyPSIxMDAlIj4KICAgICAgPHN0b3Agb2Zmc2V0PSIwJSIgc3R5bGU9InN0b3AtY29sb3I6I2MyOWE2YyIvPgogICAgICA8c3RvcCBvZmZzZXQ9IjEwMCUiIHN0eWxlPSJzdG9wLWNvbG9yOiNhMDc4NTAiLz4KICAgIDwvbGluZWFyR3JhZGllbnQ+CiAgPC9kZWZzPgogIDxyZWN0IHdpZHRoPSI2NCIgaGVpZ2h0PSI2NCIgcng9IjE0IiBmaWxsPSJ1cmwoI2JnKSIvPgogIDxwYXRoIGQ9Ik0xNiA0NFYyMGMwLTIgMS41LTMuNSAzLjUtMy41QzIzIDE2LjUgMjggMTcgMzIgMTljNC0yIDktMi41IDEyLjUtMi41IDIgMCAzLjUgMS41IDMuNSAzLjV2MjQiIGZpbGw9Im5vbmUiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMi41IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz4KICA8cGF0aCBkPSJNMzIgMTl2MjUiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+CiAgPHBhdGggZD0iTTE3IDM2YzAtOSA2LjctMTUgMTUtMTVzMTUgNiAxNSAxNSIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJ3aGl0ZSIgc3Ryb2tlLXdpZHRoPSIyLjgiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgogIDxyZWN0IHg9IjEzIiB5PSIzNCIgd2lkdGg9IjciIGhlaWdodD0iMTAiIHJ4PSIzIiBmaWxsPSJ3aGl0ZSIvPgogIDxyZWN0IHg9IjQ0IiB5PSIzNCIgd2lkdGg9IjciIGhlaWdodD0iMTAiIHJ4PSIzIiBmaWxsPSJ3aGl0ZSIvPgogIDxwYXRoIGQ9Ik0yMiAzNy41YzEuMi0xIDEuMi0zIDAtNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjYzI5YTZjIiBzdHJva2Utd2lkdGg9IjEuMyIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+CiAgPHBhdGggZD0iTTQyIDM3LjVjLTEuMi0xLTEuMi0zIDAtNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjYzI5YTZjIiBzdHJva2Utd2lkdGg9IjEuMyIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+Cjwvc3ZnPg=="

# E3 (primo seam, 2026-10-09): download, transfer e share token vivono in
# token_store (stesso dict mutato in place; `_tkstore.configure` piu' sotto).


def _qr_data_uri(text):
    """PNG data-URI di un QR che codifica `text`. '' se qrcode non disponibile."""
    try:
        import qrcode
        import io as _io
        import base64 as _b64
        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:
        print(f"[transfer] qr generation failed: {e}")
        return ""


def _transfer_payload_for(job_id):
    """Stringa codificata nel QR: URL claim assoluto. L'app ne estrae base+token."""
    base = (os.environ.get("ABM_BASE_URL", "") or "").rstrip("/")
    if not base:
        try:
            base = request.url_root.rstrip("/")
        except Exception:
            base = ""
    tok = _tkstore.ensure_transfer_token(job_id)
    # Path /t/<token>: deep link "App Link" verso l'app mobile. Con l'app
    # installata e il dominio verificato (assetlinks.json), la fotocamera di
    # sistema apre direttamente l'app; altrimenti la pagina /t/<token> fa da
    # fallback (apri/scarica l'app). Il claim vero resta su POST /api/transfer/claim.
    return f"{base}/t/{tok}", tok


def _ua_is_mobile():
    """True se lo User-Agent della request corrente è uno smartphone/tablet.
    Limite noto: iPad in modalità desktop-UA (default iPadOS 13+) NON è
    rilevabile server-side (nessun segnale touch) → classificato desktop e vede
    il QR; il bottone /t/ funziona comunque se toccato manualmente."""
    try:
        ua = (request.headers.get("User-Agent") or "")
    except Exception:
        return False
    return bool(re.search(r"Android|iPhone|iPad|iPod|Mobile|Tablet", ua, re.I))


# Custom scheme dell'app (Android + iOS): gancio alternativo agli App Links.
_APP_SCHEME = "abm"


def _ua_is_android():
    """True se lo User-Agent della request corrente è Android."""
    try:
        ua = (request.headers.get("User-Agent") or "")
    except Exception:
        return False
    return "android" in ua.lower()


def _ua_is_ios():
    """True se lo User-Agent della request corrente è iOS (iPhone/iPad/iPod).
    Nota: l'iPad in UA-desktop non è distinguibile server-side (nessun segnale
    touch) → classificato non-iOS; vede solo la CTA https (nessun errore)."""
    try:
        ua = (request.headers.get("User-Agent") or "")
    except Exception:
        return False
    return bool(re.search(r"iPhone|iPad|iPod", ua, re.I))


def _android_intent_url(https_url):
    """Converte un URL https `{host}/t/{token}` nell'intent:// URL per Chrome
    Android (scheme=abm, il custom scheme dell'app). Serve perché Chrome NON
    devia all'app una navigazione https SAME-ORIGIN (regola App Links a tutela
    della navigazione web): dal sito stesso il link https resterebbe nel browser.
    L'intent:// bypassa la soppressione; se l'app non è installata, Chrome apre
    `browser_fallback_url` (la stessa pagina /t/ con lo store). Funzione pura."""
    from urllib.parse import urlsplit, quote
    parts = urlsplit(https_url)
    host_path = parts.netloc + parts.path
    fallback = quote(https_url, safe="")
    return (f"intent://{host_path}#Intent;scheme={_APP_SCHEME};"
            f"package={_APP_PACKAGE};S.browser_fallback_url={fallback};end")


def _app_scheme_url(https_url):
    """Converte un URL https `{host}/t/{token}` nel custom scheme `abm://{host}/t/{token}`.
    Su iOS bypassa la soppressione same-origin di Safari (apre l'app anche da
    dentro la webapp sullo stesso dominio); se l'app manca, Safari erra → offerto
    come link secondario, non come CTA. Funzione pura."""
    from urllib.parse import urlsplit
    parts = urlsplit(https_url)
    return f"{_APP_SCHEME}://{parts.netloc}{parts.path}"


def _safe_share_filename(name):
    """Nome file sicuro per la key S3 e il Content-Disposition: solo basename,
    caratteri non sicuri -> '_', max 120 char, default se vuoto."""
    base = os.path.basename(str(name or "")).strip()
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    base = base[:120].strip("_.")
    return base or "audiolibro.m4b"


def _share_link_for(token):
    """URL pubblico della share: {base}/s/{token} (App Link verso l'app)."""
    base = (os.environ.get("ABM_BASE_URL", "") or "").rstrip("/")
    if not base:
        try:
            base = request.url_root.rstrip("/")
        except Exception:
            base = ""
    return f"{base}/s/{token}"


_download_tracking = {}  # file_path -> {"count": int, "last_download": float}
_DL_THROTTLE_SEC = 30
_DL_MAX_DOWNLOADS = 5


def _check_download_throttle(file_path):
    """Check and update download throttle for a file path.
    Returns (status, info):
      ('ok', remaining)        -> allowed; remaining = additional downloads still permitted after this one
      ('last', 0)              -> allowed but this is the last permitted download (file will be removed on next attempt)
      ('cooldown', seconds_left) -> too soon, wait
      ('deleted', None)        -> file deleted after max downloads
    """
    if not file_path or not os.path.exists(file_path):
        return ("ok", None)
    status, info = _cooldown_counter(_download_tracking, file_path,
                                     cooldown_sec=_DL_THROTTLE_SEC,
                                     max_count=_DL_MAX_DOWNLOADS, now=time.time())
    if status == "exhausted":
        try:
            os.remove(file_path)
            print(f"[throttle] Deleted {file_path} after {_DL_MAX_DOWNLOADS} downloads")
        except Exception as e:
            print(f"[throttle] Error deleting {file_path}: {e}")
        _download_tracking.pop(file_path, None)
        return ("deleted", None)
    return (status, info)


def _check_cold_throttle(key):
    """Come _check_download_throttle ma keyed sulla chiave S3 (il file locale
    non esiste più). Su max download ritorna 'deleted' (cap per-worker) ma NON
    cancella l'oggetto cold condiviso: la rimozione cold è di competenza solo
    della retention cleanup. Mantiene la semantica anti-redistribuzione per-worker."""
    status, info = _cooldown_counter(_download_tracking, key,
                                     cooldown_sec=_DL_THROTTLE_SEC,
                                     max_count=_DL_MAX_DOWNLOADS, now=time.time())
    if status == "exhausted":
        # cap per-worker raggiunto; NON cancellare l'oggetto cold condiviso
        # (lo fa solo la retention cleanup _delete_cold_for_job). Il counter è
        # per-worker (Gunicorn multi-process): cancellare qui distruggerebbe lo
        # stato durevole condiviso sotto gli altri worker. Mantieni il record
        # così le richieste successive continuano a ritornare 'deleted'.
        return ("deleted", None)
    return (status, info)


def _apply_no_cache(response):
    """Disabilita la cache HTTP sulla risposta (per contenuti rigenerati on-demand con URL stabile).
    SEND_FILE_MAX_AGE_DEFAULT è 1 anno: senza questa override il browser servirebbe la
    prima versione scaricata anche dopo che il server ha rigenerato il file con contenuto
    aggiornato (es. .abm cumulativo dopo successive ottimizzazioni)."""
    try:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    except Exception:
        pass
    return response


def _iter_output_dirs(job_dir):
    """Yield all output directories for a job, newest first.

    Convention: each /api/generate call creates `output_{gen_epoch}/` inside the
    job_dir. Earlier epochs are preserved so active email tokens keep working.
    Legacy names (`output/`, `output_archive_*`) are included for backwards
    compatibility with files created before this layout.
    """
    if not job_dir.exists():
        return
    epoch_dirs = []
    legacy = []
    for d in job_dir.iterdir():
        if not d.is_dir():
            continue
        n = d.name
        if n == "output" or n.startswith("output_archive_"):
            legacy.append(d)
        elif n.startswith("output_"):
            try:
                epoch_dirs.append((int(n.split("_", 1)[1]), d))
            except (ValueError, IndexError):
                legacy.append(d)
    epoch_dirs.sort(key=lambda t: t[0], reverse=True)
    for _, d in epoch_dirs:
        yield d
    for d in legacy:
        yield d


def _find_files_in_outputs(job_dir, pattern):
    """Glob `pattern` across all output dirs (recursive). Returns list of Paths."""
    results = []
    for d in _iter_output_dirs(job_dir):
        results.extend(d.rglob(pattern))
    return results


def _send_file_throttled(file_path, as_attachment=True, download_name=None, mimetype=None, no_cache=False, bypass_throttle=False, conditional=True, **kwargs):
    # --- Cold storage tier ---
    # Se il file locale è stato evacuato (finestra calda scaduta) ma esiste su
    # cold storage, applica il throttle sulla chiave e fai redirect 302 al
    # presigned URL. I byte vanno storage->utente, off il server.
    if storage_backend.is_enabled() and not os.path.exists(file_path):
        key = storage_tiering.key_for_path(file_path)
        if key and storage_backend.object_exists(key):
            is_probe_cold = False
            try:
                is_probe_cold = request.method == "HEAD" or bool(request.headers.get("Range"))
            except Exception:
                pass
            cold_status, cold_info = "ok", None
            if not (is_probe_cold or bypass_throttle):
                cold_status, cold_info = _check_cold_throttle(key)
                if cold_status == "cooldown":
                    lang = _get_browser_lang() or "en"
                    return routes_dl._render_dl_cooldown_page(lang, cold_info), 429
                if cold_status == "deleted":
                    lang = _get_browser_lang() or "en"
                    return routes_dl._render_dl_deleted_page(lang), 410
            url = storage_backend.presigned_get_url(key, download_name=download_name)
            resp = redirect(url, code=302)
            try:
                if cold_status == "last":
                    resp.headers["X-Download-Last"] = "1"
                    resp.headers["X-Download-Remaining"] = "0"
                elif cold_status == "ok" and cold_info is not None:
                    resp.headers["X-Download-Remaining"] = str(cold_info)
                resp.headers["Access-Control-Expose-Headers"] = "X-Download-Last, X-Download-Remaining, Content-Disposition"
            except Exception:
                pass
            return resp
    # HEAD e Range request (anteprima/resume del browser o client email) non devono
    # consumare il quota di 5 download: serviamo il file senza toccare il counter.
    is_probe = False
    try:
        is_probe = request.method == "HEAD" or bool(request.headers.get("Range"))
    except Exception:
        pass
    # bypass_throttle: per le rotte UI autenticate (cookie owner via
    # _check_job_owner). Il throttle è disegnato per i link email pubblici via
    # token, non per il proprietario del job. Senza bypass, un download via
    # email link 30s prima blocca quello via UI sullo stesso file.
    if is_probe or bypass_throttle:
        response = send_file(file_path, as_attachment=as_attachment, download_name=download_name, mimetype=mimetype, conditional=conditional, **kwargs)
        if no_cache:
            _apply_no_cache(response)
        return response

    status, info = _check_download_throttle(file_path)
    if status == "cooldown":
        lang = _get_browser_lang() or "en"
        return routes_dl._render_dl_cooldown_page(lang, info), 429
    if status == "deleted":
        lang = _get_browser_lang() or "en"
        return routes_dl._render_dl_deleted_page(lang), 410
    response = send_file(file_path, as_attachment=as_attachment, download_name=download_name, mimetype=mimetype, conditional=conditional, **kwargs)
    try:
        if status == "last":
            response.headers["X-Download-Last"] = "1"
            response.headers["X-Download-Remaining"] = "0"
        elif status == "ok" and info is not None:
            response.headers["X-Download-Remaining"] = str(info)
        response.headers["Access-Control-Expose-Headers"] = "X-Download-Last, X-Download-Remaining, Content-Disposition"
    except Exception:
        pass
    if no_cache:
        _apply_no_cache(response)
    return response


def _try_cold_serve(local_path, download_name=None):
    """Se il file locale è assente ma esiste una copia cold confermata, ritorna
    la Response di redirect 302 (via _send_file_throttled). Altrimenti None, così
    il chiamante prosegue col suo comportamento originale (404/410).
    Usa bypass_throttle=True: il throttle dei link email è già gestito a livello
    di route/token; qui vogliamo solo il redirect alla copia cold."""
    if not storage_backend.is_enabled() or not local_path:
        return None
    if os.path.exists(local_path):
        return None
    key = storage_tiering.key_for_path(local_path)
    if not key or not storage_backend.object_exists(key):
        return None
    return _send_file_throttled(local_path, as_attachment=True,
                                download_name=download_name, no_cache=True,
                                bypass_throttle=True)


def _cold_object_available(local_path):
    """True se esiste una copia cold confermata per il path locale snapshottato.
    Serve a NON dichiarare 'scaduto' un download il cui file vive ancora su cold
    (locale evacuato o rimosso). Tollerante agli errori: False su qualunque
    problema di rete/credenziali."""
    if not storage_backend.is_enabled() or not local_path:
        return False
    key = storage_tiering.key_for_path(local_path)
    if not key:
        return False
    try:
        return storage_backend.object_exists(key)
    except Exception:
        return False


def _cold_m4b_valid(local_path):
    """True se la copia cold del m4b snapshottato esiste ed è FINALIZZATA (atom
    'moov' presente). Evita di servire da cold un m4b TRONCATO (legacy, caricato
    mid-write da un vecchio offload) preferendogli il fallback. Bandwidth minima:
    pochi range GET da 16 byte camminando i top-level atom MP4."""
    if not storage_backend.is_enabled() or not local_path:
        return False
    key = storage_tiering.key_for_path(local_path)
    if not key:
        return False
    try:
        size = storage_backend.object_size(key)
        if not size:
            return False
        offset = 0
        guard = 0
        while offset < size:
            guard += 1
            if guard > 64:
                return False
            hdr = storage_backend.get_range(key, offset, offset + 15)
            if len(hdr) < 8:
                return False
            boxsize = int.from_bytes(hdr[0:4], "big")
            boxtype = hdr[4:8]
            header = 8
            if boxsize == 1:
                if len(hdr) < 16:
                    return False
                boxsize = int.from_bytes(hdr[8:16], "big")
                header = 16
            elif boxsize == 0:
                boxsize = size - offset
            if boxtype == b"moov":
                return True
            if boxsize < header:
                return False
            offset += boxsize
        return False
    except Exception:
        return False


# Policy che restano qui (retention effettiva di un token, disponibilita' su
# cold): il token store le riceve, non le conosce.
# Risolte a ogni chiamata (lambda), non catturate: i test le sostituiscono su
# questo modulo e devono valere anche dentro il token store.
_tkstore.configure(lambda: UPLOAD_DIR,
                   lambda info: _effective_retention_for_token_info(info),
                   lambda path: _cold_object_available(path))


# ---------------------------------------------------------------------------
# Device tokens (app mobile): cid -> lista device FCM. Persistenza atomica.
_DEVICE_TOKENS_FILE = UPLOAD_DIR / "_device_tokens.json"
_MAX_DEVICES_PER_CLIENT = 5
_FCM_TOKEN_RE = re.compile(r"^[A-Za-z0-9_:\-\.~%]{10,4096}$")
_device_tokens = {}
_device_tokens_lock = threading.Lock()


def _load_device_tokens():
    global _device_tokens
    data = load_json(_DEVICE_TOKENS_FILE, None,
                     on_error=lambda e: print(f"[device] Failed to load device tokens: {e}"))
    if data is not None:
        _device_tokens = data
        print(f"[device] Loaded FCM tokens for {len(_device_tokens)} clients")


def _save_device_tokens():
    """Caller MUST hold _device_tokens_lock."""
    try:
        atomic_write_json(_DEVICE_TOKENS_FILE,
                                          _device_tokens, indent=2)
    except Exception as e:
        print(f"[device] Failed to save device tokens: {e}")


def _device_hash(fcm_token):
    """Impronta dell'installazione: il token push non finisce mai nei file di
    quota, solo il suo digest."""
    return hashlib.sha256((fcm_token or "").encode("utf-8")).hexdigest()[:16]


def _has_fresh_device(cid):
    """True se `cid` ha almeno un device push registrato di recente.

    Finestra `ABM_QUOTA_DEVICE_MAX_AGE_DAYS` (0 = nessun limite di eta'): un
    token registrato mesi fa non garantisce piu' la consegna della notifica.
    """
    if not cid:
        return False
    days = env_int("ABM_QUOTA_DEVICE_MAX_AGE_DAYS", 90)
    cutoff = (time.time() - days * 86400) if days > 0 else 0
    with _device_tokens_lock:
        entries = list(_device_tokens.get(cid) or [])
    for e in entries:
        try:
            if float(e.get("registered_at") or 0) >= cutoff:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _push_ack_possible(job):
    """True se un job oltre quota voci standard puo' partire in batch SENZA email.

    L'email del gate non e' un'identita' (non e' verificata): il suo ruolo e'
    garantire la consegna di un job che l'utente non attende a schermo. Nell'app
    quel ruolo lo copre la notifica push, che in piu' e' emessa da un device
    registrato presso il provider — piu' solido di un indirizzo digitato. Serve
    tutto insieme: richiesta dall'app, push configurata sul server, device
    registrato di recente per questo client. `ABM_FREE_TTS_QUOTA_APP_PUSH_ACK=0`
    spegne la deroga e riporta tutti al gate email.
    """
    if not env_bool("ABM_FREE_TTS_QUOTA_APP_PUSH_ACK", True):
        return False
    plat = (job or {}).get("platform") or _client_platform()
    if plat not in ("android", "ios"):
        return False
    try:
        if not push_service.is_available():
            return False
    except Exception:
        return False
    return _has_fresh_device(_quota_client_id(job))


# Testi notifica push localizzati per lingua del job (`notify_lang`), fallback
# inglese. Coerente con la localizzazione delle email; chiavi: event -> lang ->
# (subject, body). Per l'evento 'done' il titolo del libro, se noto, prevale
# come subject (vedi _push_job_event).
_PUSH_TEXTS = {
    "done": {
        "en": ("Audiobook ready", "Generation complete: download the file from your library."),
        "it": ("Audiolibro pronto", "La generazione è completata: scarica il file nella libreria."),
        "fr": ("Livre audio prêt", "La génération est terminée : téléchargez le fichier dans votre bibliothèque."),
        "es": ("Audiolibro listo", "La generación ha finalizado: descarga el archivo en tu biblioteca."),
        "de": ("Hörbuch fertig", "Die Erstellung ist abgeschlossen: Lade die Datei in deiner Bibliothek herunter."),
        "zh": ("有声书已就绪", "生成完成：在你的图书馆中下载文件。"),
        "hi": ("ऑडियोबुक तैयार", "जनरेशन पूरा हुआ: अपनी लाइब्रेरी से फ़ाइल डाउनलोड करें।"),
    },
    "error": {
        "en": ("Generation failed", "The job stopped: open the app for details."),
        "it": ("Generazione non riuscita", "Il lavoro si è interrotto: apri l'app per i dettagli."),
        "fr": ("Échec de la génération", "La tâche s'est interrompue : ouvrez l'application pour les détails."),
        "es": ("Generación fallida", "El trabajo se detuvo: abre la app para ver los detalles."),
        "de": ("Erstellung fehlgeschlagen", "Der Vorgang wurde unterbrochen: Öffne die App für Details."),
        "zh": ("生成失败", "任务已中断：打开应用查看详情。"),
        "hi": ("जनरेशन विफल", "कार्य रुक गया: विवरण के लिए ऐप खोलें।"),
    },
}


def _push_job_event(job_id, event, title=""):
    """Invia push FCM a tutti i device del client proprietario del job.

    event: 'done' | 'error'. Mai bloccante: ogni errore e' solo loggato.
    """
    try:
        if not push_service.is_available():
            return
        with _jobs_lock:
            job = jobs.get(job_id) or {}
            cid = job.get("client_id", "")
            lang = _i18n.norm_lang((job.get("notify_lang") or "en"))
        if not cid:
            return
        with _device_tokens_lock:
            devices = list(_device_tokens.get(cid, []))
        if not devices:
            return
        # Localizza in base alla lingua del job (fallback inglese). Per 'done' il
        # titolo del libro, se noto, resta il subject più informativo.
        _texts = _PUSH_TEXTS.get(event, _PUSH_TEXTS["error"])
        loc_subject, body = _i18n.pick(_texts, lang, merge=False)
        subject = title or loc_subject
        dead = []
        for dev in devices:
            outcome = push_service.send_push(
                dev.get("fcm_token", ""), subject, body,
                data={"job_id": job_id, "event": event})
            if outcome == "unregistered":
                dead.append(dev.get("fcm_token"))
        if dead:
            with _device_tokens_lock:
                _device_tokens[cid] = [
                    e for e in _device_tokens.get(cid, [])
                    if e.get("fcm_token") not in dead]
                _save_device_tokens()
    except Exception as e:
        print(f"[push] _push_job_event failed (non-fatal): {e}")


# ----------------------------------------------------------------------
# CLIENT EMAILS — persistenza email di notifica per client_id (fallback UI)
# ----------------------------------------------------------------------

_CLIENT_EMAILS_FILE = UPLOAD_DIR / "_client_emails.json"
_client_emails = {}
_client_emails_lock = threading.Lock()


def _load_client_emails():
    """Carica la mappatura client_id → email, per fallback cross-job."""
    global _client_emails
    if not _CLIENT_EMAILS_FILE.exists():
        return
    data = load_json(_CLIENT_EMAILS_FILE, None,
                     on_error=lambda e: print(f"[client_emails] Failed to load: {e}"))
    if data is None:
        return
    _client_emails = {k: v for k, v in data.items() if k and v}
    print(f"[client_emails] Loaded {len(_client_emails)} entries")


def _save_client_emails():
    """Persiste la mappatura client_id → email in scrittura atomica."""
    try:
        with _client_emails_lock:
            atomic_write_json(_CLIENT_EMAILS_FILE,
                                              _client_emails, indent=2)
    except Exception as e:
        print(f"[client_emails] Failed to save: {e}")


def _lookup_client_email(client_id):
    """Cerca l'email associata a un client_id (thread-safe)."""
    if not client_id:
        return ""
    with _client_emails_lock:
        return _client_emails.get(client_id, "")


# ----------------------------------------------------------------------
# PAYMENTS & VOUCHERS (for LLM optimization) — state lives in payment.py
# ----------------------------------------------------------------------

# Sospensione avvio nuovi processi (attivabile da admin via /admin/log-activity)
_suspend_new_jobs = False
_suspend_lock = threading.Lock()


def _maintenance_gate():
    """Risposta 503 se l'admin ha sospeso i nuovi processi, altrimenti None.

    Va controllata anche su creazione ordine e capture PayPal: con la sola
    guardia su generate/optimize l'utente pagava (upload fatto prima della
    sospensione) e solo dopo trovava il 503 -> capture orfana rimborsata a
    voucher 30 minuti dopo invece del servizio.
    """
    if _suspend_new_jobs:
        return jsonify({"error": "System under maintenance. Please try again in a few minutes.",
                        "error_code": "maintenance"}), 503
    return None


#  -  -  Admin activity digest  -  - 

# (Functions imported from email_service)

LOCALE_NAMES = {
    "af": "Afrikaans", "am": "Amarico", "ar": "Arabo", "az": "Azero",
    "bg": "Bulgaro", "bn": "Bengalese", "bs": "Bosniaco", "ca": "Catalano",
    "cs": "Ceco", "cy": "Gallese", "da": "Danese", "de": "Tedesco",
    "el": "Greco", "en": "Inglese", "es": "Spagnolo", "et": "Estone",
    "fa": "Persiano", "fi": "Finlandese", "fil": "Filippino", "fr": "Francese",
    "ga": "Irlandese", "gu": "Gujarati", "he": "Ebraico", "hi": "Hindi",
    "hr": "Croato", "hu": "Ungherese", "id": "Indonesiano", "is": "Islandese",
    "it": "Italiano", "ja": "Giapponese", "jv": "Giavanese", "ka": "Georgiano",
    "kk": "Kazako", "km": "Khmer", "kn": "Kannada", "ko": "Coreano",
    "lo": "Lao", "lt": "Lituano", "lv": "Lettone", "mk": "Macedone",
    "ml": "Malayalam", "mr": "Marathi", "ms": "Malese", "mt": "Maltese",
    "my": "Birmano", "nb": "Norvegese", "ne": "Nepalese", "nl": "Olandese",
    "pl": "Polacco", "ps": "Pashto", "pt": "Portoghese", "ro": "Rumeno",
    "ru": "Russo", "si": "Singalese", "sk": "Slovacco", "sl": "Sloveno",
    "so": "Somalo", "sq": "Albanese", "sr": "Serbo", "sv": "Svedese",
    "sw": "Swahili", "ta": "Tamil", "te": "Telugu", "th": "Thailandese",
    "tr": "Turco", "uk": "Ucraino", "ur": "Urdu", "uz": "Uzbeco",
    "vi": "Vietnamita", "zh": "Cinese", "zu": "Zulu",
}

_voices_cache = None
_voices_lock = threading.Lock()

async def _fetch_voices():
    """Fetches and categorizes Edge TTS, Google TTS, and Gemini TTS voices."""
    try:
        import edge_tts
        vman = await edge_tts.VoicesManager.create()
        edge_list = vman.voices
    except Exception as e:
        print(f"Error fetching Edge voices: {e}")
        edge_list = []

    languages = {} # lang_code -> { "name": "...", "voices": [] }
    
    # 1. Edge TTS
    for v in edge_list:
        lc_full = v["Locale"]
        lc = _i18n.norm_lang(lc_full)
        region = lc_full.split("-")[-1].upper()
        
        if lc not in languages:
            languages[lc] = {
                "name": LOCALE_NAMES.get(lc, lc.upper()),
                "voices": []
            }
        
        # Pulizia nome: "Microsoft Isabella Online (Natural) - Italian (Italy)" -> "Isabella"
        raw_name = v["FriendlyName"]
        clean_name = raw_name.replace("Microsoft ", "").replace(" Online (Natural)", "")
        # Rimuove l'eventuale suffisso della lingua dopo il trattino
        if " - " in clean_name:
            clean_name = clean_name.split(" - ")[0].strip()
        
        gender_icon = "👨" if v["Gender"] == "Male" else "👩"
        languages[lc]["voices"].append({
            "id": v["ShortName"],
            "name": f"{clean_name} ({region})",
            "gender": v["Gender"],
            "gender_icon": gender_icon,
            "locale": lc_full,
            "engine": "edge"
        })

    # 2. Gemini TTS (Optional) — solo se effettivamente abilitato.
    # `gemini_tts is not None` significa solo che il modulo è importato;
    # senza ABM_GEMINI_API_KEY le voci non vanno comunque mostrate.
    # NB: il branch GEMINI espone le voci nel tab "PREMIUM" (la rimozione
    # fatta su main era temporanea per la release pre-feature).
    if gemini_tts is not None and gemini_tts.is_available():
        try:
            gem_dict = gemini_tts.get_voices()
            for lc_short, v_list in gem_dict.items():
                if lc_short not in languages:
                    languages[lc_short] = {
                        "name": LOCALE_NAMES.get(lc_short, lc_short.upper()),
                        "voices": []
                    }
                # Gemini voices are multilingual; gender è impostato in
                # gemini_tts.get_voices() da GEMINI_VOICE_GENDER (doc Google).
                # Lo shim resta come fallback per voci eventuali senza metadata.
                for v in v_list:
                    v.setdefault("gender", "Neutral")
                    v.setdefault("gender_icon", "★")
                languages[lc_short]["voices"].extend(v_list)
        except Exception as e:
            print(f"Error merging Gemini voices: {e}")

    # 3. Speechify Simba-3.2 (Optional, solo inglese) — gated su API key.
    if speechify_tts.is_available():
        try:
            spx_dict = speechify_tts.get_voices()  # -> {"en": [entry, ...]}
            for lc_short, v_list in spx_dict.items():
                if lc_short not in languages:
                    languages[lc_short] = {
                        "name": LOCALE_NAMES.get(lc_short, lc_short.upper()),
                        "voices": []
                    }
                languages[lc_short]["voices"].extend(v_list)
        except Exception as e:
            print(f"Error merging Speechify voices: {e}")

    # 4. VoxCPM2 (opzionale) — gated su endpoint, chiave, tariffa e catalogo.
    if voxcpm_tts is not None and voxcpm_tts.is_available():
        try:
            vox_dict = voxcpm_catalog.get_voices()  # -> {"it": [entry, ...]}
            for lc_short, v_list in vox_dict.items():
                if lc_short not in languages:
                    # Il catalogo e' una variabile (D10): una lingua nuova
                    # apre la sua sezione senza che nessuno rilasci codice.
                    languages[lc_short] = {
                        "name": LOCALE_NAMES.get(lc_short, lc_short.upper()),
                        "voices": []
                    }
                languages[lc_short]["voices"].extend(v_list)
        except Exception as e:
            # Un catalogo illeggibile toglie un motore, non l'applicazione.
            print(f"Error merging VoxCPM voices: {e}")

    # Sorting: Female prima di Male, poi per nome; fra le voci VoxCPM
    # decidono prima i punti d'uso (ultimi 30 giorni, poi assoluti).
    voxcpm_ranking.ordina(languages)

    # Priority sorting for languages
    priority = {"it": 0, "en": 1, "fr": 2, "de": 3, "es": 4, "pt": 5}
    sorted_langs = dict(sorted(languages.items(), key=lambda x: (priority.get(x[0], 99), x[1]["name"])))
    
    return sorted_langs

def get_voices():
    """Thread-safe access to the voices cache."""
    global _voices_cache
    with _voices_lock:
        if _voices_cache is not None:
            # La cache si costruisce una volta (le voci Edge arrivano dalla
            # rete), ma i punti VoxCPM cambiano a ogni generazione: il
            # riordino e' sul posto e costa quanto un sort di poche liste.
            voxcpm_ranking.ordina(_voices_cache)
            return _voices_cache

    import asyncio
    try:
        # Create new loop for this thread (or use existing if in main)
        loop = asyncio.new_event_loop()
        voices = loop.run_until_complete(_fetch_voices())
        loop.close()
        
        with _voices_lock:
            _voices_cache = voices
        return voices
    except Exception as e:
        print(f"Error in get_voices: {e}")
        return {}

def _invalidate_voices_cache():
    """Invalida la cache voci (ricarica al prossimo get_voices())."""
    global _voices_cache
    with _voices_lock:
        _voices_cache = None

# ----------------------------------------------------------------------
# HELPER CLASSES & PARSERS (Moved to generation_engine.py)
# ----------------------------------------------------------------------

def parse_txt(file_path):
    return generation_engine.parse_txt(file_path)

def parse_abm(path):
    return generation_engine.parse_abm(path)

# ----------------------------------------------------------------------
# GENERATION & OPTIMIZATION THREADS (Moved to generation_engine.py)
# ----------------------------------------------------------------------

def run_optimization(job_id, selected_chapters=None):
    return generation_engine.run_optimization(job_id, selected_chapters)

def run_translation(job_id):
    return generation_engine.run_translation(job_id)

def run_generation(job_id, info, voice, rate, single_file, output_format='m4b', podcast_base_url='', gemini_style_instruction=None, speechify_emotion=None):
    try:
        return generation_engine.run_generation(job_id, info, voice, rate, single_file,
                                                 output_format=output_format, podcast_base_url=podcast_base_url,
                                                 gemini_style_instruction=gemini_style_instruction,
                                                 speechify_emotion=speechify_emotion)
    except BaseException as e:
        # SystemExit/KeyboardInterrupt devono propagare — non sopprimerli.
        if isinstance(e, (SystemExit, KeyboardInterrupt)):
            raise
        print(f"[{job_id}] CRITICAL: run_generation wrapper crashed: {e}")
        import traceback
        traceback.print_exc()
        job = jobs.get(job_id)
        if job:
            job["status"] = "error"
            job["progress_message"] = f"Internal error: {e}"
            job["last_poll"] = time.time()

#  -  -  Activity log  -  -

def _voice_for_log(voice):
    """C2: l'id di una voce campionata (voxcpm:mine:<token>) non deve mai
    finire scritto in un log/dossier/digest persistito - il token e' un
    segreto (vedi vincoli globali della feature voci campionate). Ogni
    chiamante che passa una voce a _log_activity/_abuse_note/
    _admin_notify_generation deve filtrarla da qui. Passthrough per ogni
    altra voce (edge-tts, gemini:, speechify:, voxcpm:v2:...)."""
    try:
        if voice and voice.startswith(voice_clone.VOICE_ID_PREFIX):
            return "user-voice"
    except Exception:
        pass
    return voice


def _voice_public_label(voice):
    """Nome voce presentabile all'utente (mai il nome del provider AI/TTS,
    regola UI): 'it-IT-IsabellaNeural' -> 'Isabella', 'gemini:flash31:Zephyr'
    -> 'Zephyr', 'voxcpm:v2:it-IT/Stefano' -> 'Stefano', 'speechify:...:harper_32'
    -> 'harper_32'. Una voce campionata (voxcpm:mine:<token>) diventa la
    generica 'your voice': il token e' un segreto, non un nome da mostrare.
    Usata dallo storico account (accounts.record_job/_apply_account_to_job),
    mai dal log (li' resta _voice_for_log). Non solleva mai."""
    try:
        v = (voice or "").strip()
        if not v:
            return ""
        if v.startswith(voice_clone.VOICE_ID_PREFIX):
            return "your voice"
        if _is_gemini_voice(v):
            try:
                _, _, voice_name = gemini_tts.parse_voice_id(v)
                return voice_name
            except Exception:
                return v.rsplit(":", 1)[-1]
        if _is_voxcpm_voice(v):
            return v.rsplit("/", 1)[-1] if "/" in v else v.rsplit(":", 1)[-1]
        if _is_speechify_voice(v):
            return v.rsplit(":", 1)[-1]
        if ":" in v:
            # Provider ignoto: ultimo segmento, mai il nome del modello/provider
            # che puo' comparire in un id a 3+ segmenti (es. 'foo:model:voice').
            return v.rsplit(":", 1)[-1]
        # edge-tts: '<locale>-<Name>Neural[Multilingual]'
        name = v.rsplit("-", 1)[-1]
        if name.endswith("Neural"):
            name = name[:-len("Neural")]
        if name.endswith("Multilingual"):
            name = name[:-len("Multilingual")]
        return name
    except Exception:
        return ""


def _voice_plan_info(voice):
    """(engine, model_key) per lo storico account: `engine` e' il piano
    ('standard' = voci gratuite, 'premium' = voci a pagamento), `model_key` e'
    la chiave del modello premium ('flash31', 'simba-3.2',
    'voxcpm'), vuota per le voci standard. E' un identificatore interno: la
    pagina account lo traduce nella stessa etichetta che il selettore voci
    mostra all'utente. Non solleva: su voce ignota torna ('', '')."""
    try:
        v = (voice or "").strip()
        if not v:
            return "", ""
        if _is_gemini_voice(v):
            parts = v.split(":")
            model = parts[1] if len(parts) >= 3 else ""
            return "premium", model
        if _is_speechify_voice(v):
            parts = v.split(":")
            return "premium", (parts[1] if len(parts) >= 3 else "")
        if _is_voxcpm_voice(v):
            # Catalogo e voce campionata girano sullo stesso modello: una sola
            # etichetta, il token della voce clonata non entra mai qui.
            return "premium", "voxcpm"
        return "standard", ""
    except Exception:  # noqa: BLE001
        return "", ""


def _log_activity(session_id, filename, operation, client_id='', client_ip='', voice='', browser_lang='', epoch=None, platform=''):
    """Scrive una riga nel business log mensile (vedi activity_log.log).

    Dedup per (job_id, operazione); con `epoch` (es. job["gen_epoch"]) la
    chiave include l'epoca, cosi' GENERATE/COMPLETE di una RI-generazione
    dello stesso job_id non vengono soppressi. Gli eventi senza job_id
    (voucher, admin, backend TTS) non si deduplicano mai.
    """
    activity_log.log(session_id, filename, operation, client_id=client_id,
                     ip=client_ip, voice=voice, lang=browser_lang,
                     platform=platform, epoch=epoch)


def _job_original_filename(job_id):
    """Nome del file originale di un job, per gli eventi di log che non lo hanno
    a portata di mano (TRANSFER, copie admin).

    Il job può non essere più in RAM (restart/cleanup): in quel caso ripiega sul
    download token, che porta con sé lo snapshot del nome. Stringa vuota se non
    ricostruibile: il parser del log conserva comunque il titolo già noto della
    sessione.
    """
    if not job_id:
        return ""
    with _jobs_lock:
        job = jobs.get(job_id)
        if job:
            name = job.get("original_filename", "")
            if name:
                return name
    for tinfo in list(_tkstore.download_tokens.values()):
        if isinstance(tinfo, dict) and tinfo.get("job_id") == job_id:
            name = tinfo.get("original_filename", "")
            if name:
                return name
    return ""


def _cold_op(operation):
    """Nome dell'evento per un download risolto con redirect 302 alla copia cold.

    Sul redirect i byte vanno storage->utente e non passano da noi: non sappiamo
    se la consegna sia avvenuta. Se il presigned viene rifiutato l'utente vede un
    403 che qui non lascia traccia, e un evento indistinguibile da una consegna
    reale rende il business log una fonte forense falsa (incidente 2026-08-25:
    filtro IP client sul token R2, ogni redirect finito in AccessDenied mentre il
    log registrava download riusciti). Suffisso `_COLD` = "instradato", non
    "consegnato"."""
    return f"{operation}_COLD"


def _is_resume_or_probe_request():
    """True se la richiesta corrente è HEAD o resume con Range header.

    Why: i browser e i client email aprono il link con HEAD/Range per
    prefetch/anteprima/resume. Senza filtro ogni link aperto genera N voci
    nel log anche se l'utente ha cliccato una sola volta.
    How to apply: chiamare prima di _log_activity nelle route di download
    per contare solo i download reali (GET completi).
    """
    try:
        return request.method == "HEAD" or bool(request.headers.get("Range"))
    except Exception:
        return False


# ----------------------------------------------------------------------
# COMMUNITY STATS — derivate dal business log (activity_log)
# ----------------------------------------------------------------------
# Conta operation=='COMPLETE' (audiolibri generati con successo) e aggrega
# per lingua TTS (voice.split('-')[0]). Cache in-memory: 60s today, 5min mese.

_stats_lock = threading.Lock()
_stats_today_cache = {"value": None, "expires": 0.0}
_stats_month_cache = {"value": None, "expires": 0.0}

_COMMUNITY_OPS = frozenset({"COMPLETE", "OPT_COMPLETE"})


def _stats_today_count() -> int:
    """Conta COMPLETE e OPT_COMPLETE odierni. Cache 60s."""
    now = time.time()
    with _stats_lock:
        if _stats_today_cache["value"] is not None and now < _stats_today_cache["expires"]:
            return _stats_today_cache["value"]
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    count = sum(1 for _ in activity_log.iter_rows(midnight, ops=_COMMUNITY_OPS))
    with _stats_lock:
        _stats_today_cache["value"] = count
        _stats_today_cache["expires"] = now + 60.0
    return count


def _stats_month_by_lang() -> dict:
    """Aggrega COMPLETE e OPT_COMPLETE del mese corrente per lingua TTS.
    Restituisce {monthly: int, top: [{lang, count}], other: int}.
    Cache 5min."""
    now = time.time()
    with _stats_lock:
        if _stats_month_cache["value"] is not None and now < _stats_month_cache["expires"]:
            return _stats_month_cache["value"]
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    by_lang: dict[str, int] = defaultdict(int)
    total = 0
    for row in activity_log.iter_rows(month_start, ops=_COMMUNITY_OPS):
        total += 1
        if not row.voice:
            continue
        lang = row.voice.split("-")[0].strip().lower()
        if lang:
            by_lang[lang] += 1
    sorted_langs = sorted(by_lang.items(), key=lambda kv: kv[1], reverse=True)
    top = [{"lang": k, "count": v} for k, v in sorted_langs[:4]]
    other = sum(v for _, v in sorted_langs[4:])
    result = {"monthly": total, "top": top, "other": other}
    with _stats_lock:
        _stats_month_cache["value"] = result
        _stats_month_cache["expires"] = now + 300.0
    return result


# ----------------------------------------------------------------------
# ROUTES
# ----------------------------------------------------------------------

#  -  -  -  Rotte per lingua (/it/, /en/, /fr/, /es/, /de/, /zh/, /hi/)  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -
# Ogni URL ha HTML pre-renderizzato con meta tag, title, hreflang e canonical
# corretti per quella lingua  -  indicizzabili da Google come pagine distinte.

def _inject_reviews(template_html: str, lang: str) -> str:
    """Swap __REVIEWS_LD__ placeholder with fresh AggregateRating + Review
    JSON-LD built from the live feedback store.

    Cost ≤ 1 ms per request. Falls back to empty replacement if the store
    is unavailable so the page still renders cleanly."""
    try:
        rev = seo_reviews.build_reviews(lang)
        ld = rev.get("ld_block", "") or ""
    except Exception as e:
        print(f"[seo_reviews] inject failed: {e!s}")
        ld = ""
    return template_html.replace("__REVIEWS_LD__", ld)


@app.route("/")
def index():
    """Root: serve la lingua rilevata dall'Accept-Language, senza redirect.
    Il redirect 302 penalizzerebbe il PageRank; meglio rispondere con canonical.
    Usa HTML_ROOT_TEMPLATES: canonical punta a BASE_URL/ (non /{lang}/).
    Questo garantisce che l'URL x-default negli hreflang sia auto-canonicalizzante.
    """
    lang = _detect_lang_from_request()
    base = _i18n.pick(HTML_ROOT_TEMPLATES, lang, merge=False)
    resp = app.make_response(_inject_reviews(base, lang))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Vary"] = "Accept-Language"
    return _apply_app_attribution(resp)

def _serve_lang(lang: str):
    return (
        _inject_reviews(HTML_TEMPLATES[lang], lang),
        200,
        {"Content-Type": "text/html; charset=utf-8"},
    )

@app.route("/it/")
def index_it():
    return _serve_lang("it")

@app.route("/en/")
def index_en():
    return _serve_lang("en")

@app.route("/fr/")
def index_fr():
    return _serve_lang("fr")

@app.route("/es/")
def index_es():
    return _serve_lang("es")

@app.route("/de/")
def index_de():
    return _serve_lang("de")

@app.route("/zh/")
def index_zh():
    return _serve_lang("zh")

@app.route("/hi/")
def index_hi():
    return _serve_lang("hi")


# ── FAQ Page (dedicated) ────────────────────────────────────────────

_FAQ_TITLES = {
    "it": "Domande Frequenti — Audiobook Maker",
    "en": "Frequently Asked Questions — Audiobook Maker",
    "fr": "Questions Fréquentes — Audiobook Maker",
    "es": "Preguntas Frecuentes — Audiobook Maker",
    "de": "Häufig Gestellte Fragen — Audiobook Maker",
    "zh": "常见问题 — Audiobook Maker",
    "hi": "अक्सर पूछे जाने वाले प्रश्न — Audiobook Maker",
}


@app.route("/faq/")
def faq_page_root():
    """Redirect root FAQ to the browser-language or English variant."""
    lang = _detect_lang_from_request()
    if not lang or lang not in _SUPPORTED_LANGS:
        lang = "en"
    base = BASE_URL or ""
    if base:
        return redirect(f"{base}/faq/{lang}/", code=301)
    return redirect(f"/faq/{lang}/", code=301)


@app.route("/faq/<lang>/")
def faq_page(lang):
    """Dedicated FAQ page per language. Crawler-facing minimal HTML with
    JSON-LD FAQPage schema and full hreflang alternates."""
    if lang not in _SUPPORTED_LANGS:
        return "Language not supported", 404

    html_lang = page_brand.html_lang(lang)
    c = seo_content.lang_content(lang)
    title = html_mod.escape(_i18n.pick(_FAQ_TITLES, lang, merge=False))
    desc = html_mod.escape(c.get("direct_answer", ""))
    base = BASE_URL or ""
    canonical = f"{base}/faq/{lang}/"
    hreflang_block = page_brand.hreflang_links(
        lambda lc: f"{base}/faq/{lc}/", f"{base}/faq/en/", sep="\n    ")

    # Build FAQ HTML
    faqs_html = ""
    for q, a in c.get("faqs", []):
        faqs_html += (
            f'  <details open><summary>{html_mod.escape(q)}</summary>\n'
            f'    <p>{html_mod.escape(a)}</p>\n'
            f'  </details>\n\n'
        )
    faq_ld_json = seo_ld.ld_json(seo_ld.faq_ld(c.get("faqs", [])))

    iso_modified = datetime.now().strftime("%Y-%m-%d")

    page = _render_page("faq", {"__P0__": (html_lang), "__P1__": (title), "__P2__": (desc), "__P3__": (canonical), "__P4__": (hreflang_block), "__P5__": (iso_modified), "__P6__": (faq_ld_json), "__P7__": (faqs_html)})
    return page, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/content/<lang>/")
def seo_content_page(lang):
    """Dedicated SEO content page per language. Minimal HTML wrapper around
    the rich SEO block generated by build_seo_content_html(). Crawler-facing,
    no app CSS/JS required — the block already carries inline styles."""
    if lang not in _i18n.LANGS:
        return "Language not supported", 404

    html_lang = page_brand.html_lang(lang)
    c = seo_content.lang_content(lang)
    title = html_mod.escape(c.get("heading", "Audiobook Maker"))
    desc = html_mod.escape(c.get("direct_answer", ""))
    base = BASE_URL or ""
    canonical = f'{base}/content/{lang}/' if base else ""

    seo_block = seo_content.build_seo_content_html(lang)

    head_extra = ""
    if canonical:
        head_extra += f'\n    <link rel="canonical" href="{canonical}" />'

    page = _render_page("seo_content", {"__P0__": (html_lang), "__P1__": (title), "__P2__": (desc), "__P3__": (head_extra), "__P4__": (seo_block)})
    return page, 200, {"Content-Type": "text/html; charset=utf-8"}


#  -  -  SEO Guide Pages  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -
_VALID_GUIDES = {"epub-to-audiobook", "m4b-format", "text-to-speech-audiobook", "podcast", "gemini-tts", "free-ebooks", "voice-cloning-audiobook"}
_GUIDE_LANGS = _i18n.LANGS

@app.route("/guide/<guide_id>/")
def guide_page(guide_id):
    if guide_id not in _VALID_GUIDES:
        return "Guide not found", 404
    # Back-compat: vecchio schema ?lang=xx → 301 al nuovo path /guide/<id>/<lang>/.
    qlang = request.args.get("lang", "").strip()
    if qlang:
        if qlang in _GUIDE_LANGS and qlang != "en":
            return redirect(f"/guide/{guide_id}/{qlang}/", code=301)
        return redirect(f"/guide/{guide_id}/", code=301)
    # Bare URL = x-default (inglese), canonical /guide/<id>/.
    html = build_guide_html(guide_id, "en", BASE_URL, __version__)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/guide/<guide_id>/<lang>/")
def guide_page_lang(guide_id, lang):
    if guide_id not in _VALID_GUIDES:
        return "Guide not found", 404
    lang = (lang or "").strip()
    if lang == "en":
        # EN canonico è senza suffisso → 301 alla forma x-default.
        return redirect(f"/guide/{guide_id}/", code=301)
    if lang not in _GUIDE_LANGS:
        return "Guide not found", 404
    html = build_guide_html(guide_id, lang, BASE_URL, __version__)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


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

    import os as _os
    from datetime import date, datetime as _dt

    def _file_lastmod(path: str) -> str:
        """Return ISO date of file mtime, or today as a safe fallback."""
        try:
            return _dt.utcfromtimestamp(_os.path.getmtime(path)).strftime("%Y-%m-%d")
        except OSError:
            return date.today().isoformat()

    _here = _os.path.dirname(_os.path.abspath(__file__))
    # The home page reflects content from app + visible SEO + live user
    # reviews; pick the most recent of all three so Google sees a real change
    # signal whenever new feedback is approved.
    candidates = [
        _file_lastmod(_os.path.join(_here, "audiobook_app.py")),
        _file_lastmod(_os.path.join(_here, "seo_content.py")),
    ]
    try:
        latest_review_ts = seo_reviews.build_reviews("en").get("latest_ts", 0)
        if latest_review_ts:
            candidates.append(
                _dt.utcfromtimestamp(latest_review_ts).strftime("%Y-%m-%d")
            )
    except Exception:
        pass
    home_lastmod = max(candidates)
    guide_lastmod = _file_lastmod(_os.path.join(_here, "guide_content.py"))

    # Blocco alternates condiviso da tutti gli URL (page_brand.hreflang_links)
    def _alts(path_fn, x_default):
        return page_brand.hreflang_links(path_fn, x_default, xhtml=True)

    alternates = _alts(lambda lc: f"{BASE_URL}/{lc}/", f"{BASE_URL}/")

    urls = []
    # Root (x-default)
    urls.append(f"""  <url>
    <loc>{BASE_URL}/</loc>
    <lastmod>{home_lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>1.0</priority>
{alternates}
  </url>""")

    # Una URL per lingua
    for lc in page_brand.SITE_LANGS:
        urls.append(f"""  <url>
    <loc>{BASE_URL}/{lc}/</loc>
    <lastmod>{home_lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
{alternates}
  </url>""")

    # Content SEO pages — 7 lingue
    content_alternates = _alts(lambda lc: f"{BASE_URL}/content/{lc}/", f"{BASE_URL}/content/en/")
    for lc in page_brand.SITE_LANGS:
        urls.append(f"""  <url>
    <loc>{BASE_URL}/content/{lc}/</loc>
    <lastmod>{home_lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
{content_alternates}
  </url>""")

    # FAQ pages — 7 lingue, priority 0.8 (high value for featured snippets)
    faq_alternates = _alts(lambda lc: f"{BASE_URL}/faq/{lc}/", f"{BASE_URL}/faq/en/")
    for lc in page_brand.SITE_LANGS:
        urls.append(f"""  <url>
    <loc>{BASE_URL}/faq/{lc}/</loc>
    <lastmod>{home_lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
{faq_alternates}
  </url>""")

    # Guide pages — schema path-based: EN su /guide/<id>/ (x-default, lc=="en"),
    # altre lingue su /guide/<id>/<lang>/. N guide × 7 lingue URL totali.
    for guide_id in sorted(_VALID_GUIDES):
        # Per-language alternates (hreflang) condivise da tutte le varianti.
        guide_alternates = _alts(lambda lc, g=guide_id: f"{BASE_URL}{_guide_path(g, lc)}",
                                 f"{BASE_URL}/guide/{guide_id}/")

        for lc in page_brand.SITE_LANGS:
            urls.append(f"""  <url>
    <loc>{BASE_URL}{_guide_path(guide_id, lc)}</loc>
    <lastmod>{guide_lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
{guide_alternates}
  </url>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
{chr(10).join(urls)}
</urlset>"""
    return xml, 200, {"Content-Type": "application/xml; charset=utf-8"}


#  -  -  -  robots.txt  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
# ── Deep link app mobile: QR /t/<token> + Android App Links ──
_APP_PACKAGE = "it.abm.audiobook_maker_mobile"
_APP_CERT_FINGERPRINTS = [
    # Upload key (APK di test / chiave di upload Play)
    "50:09:2D:2F:DD:99:FF:A7:F9:7E:40:39:04:C6:C3:DC:A1:3F:54:AE:0E:17:E1:6E:13:AD:07:20:83:8A:C4:BB",
    # App signing key di Google (Play Console) — copre le installazioni da Play
    "6A:77:8A:0E:75:60:E3:22:BB:AE:75:2C:03:1F:E4:C7:59:16:25:69:01:4B:C2:F6:89:75:46:BF:95:96:09:BB",
]
# iOS: appID = <Apple Team ID>.<Bundle ID>, usato nell'apple-app-site-association.
_IOS_APP_ID = "DXD84TM2T3.it.abm.audiobookMakerMobile"
# URL store da env (omogenei): se assenti, il bottone è mostrato ma disabilitato.
# Valore Play da impostare in ABM_PLAY_STORE_URL al rilascio: https://play.google.com/store/apps/details?id=it.nextsw.audiobook_maker_mobile
_PLAY_STORE_URL = (os.environ.get("ABM_PLAY_STORE_URL", "") or "").strip()
_APP_STORE_URL = (os.environ.get("ABM_APP_STORE_URL", "") or "").strip()

# ---------------------------------------------------------------------------
# Inline-SVG store badges (viewBox 0 0 135 40)
# ---------------------------------------------------------------------------
_PLAY_BADGE_SVG = (
    # Riproduzione fedele del badge ufficiale "Get it on Google Play":
    # icona a 4 facce con le sfumature del brand + lockup testuale.
    # Uso consentito senza oneri di licenza purche' l'artwork non venga
    # ricolorato/deformato (Google Play badge guidelines).
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 135 40" role="img">'
    '<defs><linearGradient id="abmgp1" x1="20.75" y1="8.71" x2="5.02" y2="24.44" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#00a0ff"/><stop offset=".26" stop-color="#00beff"/><stop offset=".51" stop-color="#00d2ff"/><stop offset=".76" stop-color="#00dfff"/><stop offset="1" stop-color="#00e3ff"/></linearGradient><linearGradient id="abmgp2" x1="29.34" y1="18.4" x2="9.64" y2="18.4" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#ffe000"/><stop offset=".41" stop-color="#ffbd00"/><stop offset=".78" stop-color="#ffa500"/><stop offset="1" stop-color="#ff9c00"/></linearGradient><linearGradient id="abmgp3" x1="26.56" y1="20.28" x2="2.26" y2="44.58" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#ff3a44"/><stop offset="1" stop-color="#c31162"/></linearGradient><linearGradient id="abmgp4" x1="7.3" y1="-3.36" x2="18.15" y2="7.5" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#32a071"/><stop offset=".07" stop-color="#2da771"/><stop offset=".48" stop-color="#15cf74"/><stop offset=".8" stop-color="#06b070"/><stop offset="1" stop-color="#00b16a"/></linearGradient></defs>'
    '<rect width="135" height="40" rx="6" fill="#000"/>'
    '<rect x=".5" y=".5" width="134" height="39" rx="5.5" fill="none" stroke="#a6a6a6"/>'
    '<path d="M10.44 7.32a1.51 1.51 0 0 0-.35 1.06v18.25c0 .42.13.78.36 1.04l.06.06 10.23-10.23v-.24L10.5 7.26l-.06.06z" fill="url(#abmgp1)"/>'
    '<path d="M24.1 21.93l-3.4-3.41v-.24l3.41-3.42.08.05 4.04 2.3c1.15.65 1.15 1.72 0 2.38l-4.03 2.29-.1.05z" fill="url(#abmgp2)"/>'
    '<path d="M24.19 21.88L20.7 18.4 10.44 28.67c.38.4 1 .45 1.71.05l12.04-6.84z" fill="url(#abmgp3)"/>'
    '<path d="M24.19 14.91L12.15 8.08c-.71-.4-1.33-.35-1.71.05L20.7 18.4l3.49-3.49z" fill="url(#abmgp4)"/>'
    '<text x="36.5" y="16" font-family="Roboto,Arial,Helvetica,sans-serif" font-size="7.4" fill="#d0d0d0" textLength="35" lengthAdjust="spacingAndGlyphs">GET IT ON'
    '</text>'
    '<text x="36" y="31" font-family="Roboto,Arial,Helvetica,sans-serif" font-size="13.5" font-weight="500" fill="#f2f2f2" textLength="80" lengthAdjust="spacingAndGlyphs">Google Play'
    '</text>'
    '</svg>'
)

_APPLE_BADGE_SVG = (
    # Riproduzione fedele del badge ufficiale "Download on the App Store"
    # (logo mela corretto + lockup testuale). Uso consentito senza oneri di
    # licenza purche' l'artwork non venga alterato (Apple marketing guidelines).
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 135 40" role="img">'
    '<rect width="135" height="40" rx="6" fill="#000"/>'
    '<rect x=".5" y=".5" width="134" height="39" rx="5.5" fill="none" stroke="#a6a6a6"/>'
    '<path transform="translate(6.2,6.4) scale(1.12)" d="M17.05 20.28c-.98.95-2.05.8-3.08.35-1.09-.46-2.09-.48-3.24 0-1.44.62-2.2.44-3.06-.35C2.79 15.25 3.51 7.59 9.05 7.31c1.35.07 2.29.74 3.08.8 1.18-.24 2.31-.93 3.57-.84 1.51.12 2.65.72 3.4 1.8-3.12 1.87-2.38 5.98.48 7.13-.57 1.5-1.31 2.99-2.54 4.09zM12.03 7.25c-.15-2.23 1.66-4.07 3.74-4.25.29 2.58-2.34 4.5-3.74 4.25z" fill="#fff"/>'
    '<text x="31" y="16" font-family="Helvetica,Arial,sans-serif" font-size="7.2" fill="#d0d0d0" textLength="44" lengthAdjust="spacingAndGlyphs">Download on the'
    '</text>'
    '<text x="31" y="31" font-family="Helvetica,Arial,sans-serif" font-size="13.5" font-weight="500" fill="#f2f2f2" textLength="72" lengthAdjust="spacingAndGlyphs">App Store'
    '</text>'
    '</svg>'
)


def _install_buttons_html(lang):
    """HTML dei due badge store inline-SVG (Play + Apple), sempre presenti.
    Attivo (link <a>) se l'env del rispettivo store è impostato, altrimenti
    disabilitato (<span aria-disabled>). Le etichette localizzate compaiono in
    aria-label e title per accessibilità e retrocompatibilità test."""
    labels = {
        "it": ("Scarica da Google Play", "Scarica da App Store"),
        "en": ("Get it on Google Play", "Download on the App Store"),
    }
    play_label, apple_label = _i18n.pick(labels, lang, merge=False)

    def _badge(url, label, svg):
        safe_label = html_mod.escape(label, quote=True)
        if url:
            safe_url = html_mod.escape(url, quote=True)
            return (
                f'<a class="store-badge" href="{safe_url}"'
                f' aria-label="{safe_label}" title="{safe_label}">'
                f'{svg}</a>'
            )
        return (
            f'<span class="store-badge btn-disabled" aria-disabled="true"'
            f' aria-label="{safe_label}" title="{safe_label}">'
            f'{svg}</span>'
        )

    return (
        '<div class="stores">'
        + _badge(_PLAY_STORE_URL, play_label, _PLAY_BADGE_SVG)
        + _badge(_APP_STORE_URL, apple_label, _APPLE_BADGE_SVG)
        + '</div>'
    )


@app.route("/.well-known/assetlinks.json")
def assetlinks_json():
    # Digital Asset Links: verifica il dominio per gli App Links dell'app, così la
    # fotocamera di sistema apre l'app sui link https://<dominio>/t/<token>.
    data = [{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {
            "namespace": "android_app",
            "package_name": _APP_PACKAGE,
            "sha256_cert_fingerprints": _APP_CERT_FINGERPRINTS,
        },
    }]
    return app.response_class(json.dumps(data), mimetype="application/json")


@app.route("/.well-known/apple-app-site-association")
def apple_app_site_association():
    # Apple App Site Association: verifica il dominio per gli Universal Links iOS,
    # così i link https://<dominio>/t/<token> (QR trasferimento), /s/<token>
    # (condivisione file) e /auth/<token> (magic link di accesso: l'app lo
    # verifica via POST /api/auth/verify, la GET HTML non consuma il token)
    # aprono direttamente l'app invece del browser.
    # Requisiti Apple: nessuna estensione nel path, Content-Type application/json,
    # nessun redirect (il file deve rispondere 200 direttamente).
    data = {
        "applinks": {
            "apps": [],
            "details": [{
                "appID": _IOS_APP_ID,
                "paths": ["/t/*", "/s/*", "/auth/*"],
            }],
        }
    }
    return app.response_class(json.dumps(data), mimetype="application/json")


def _render_install_page(lang, title, body):
    """Pagina install: stile della landing + bottoni store (Task 1) + ritorno al
    sito. Usata da /get-app e da _render_transfer_landing."""
    back = {"it": "Torna al sito", "en": "Back to website"}.get(lang, "Back to website")
    home = BASE_URL or "/"
    return _render_page("install", {"__P0__": (lang), "__P1__": (title), "__P2__": (body), "__P3__": (_install_buttons_html(lang)), "__P4__": (home), "__P5__": (back)})


@app.route("/get-app")
def get_app_page():
    """Pagina canonica 'scarica l'app' (link store). Stesso contenuto della
    landing no-app dei deep link."""
    try:
        al = (request.headers.get("Accept-Language") or "").strip().lower()
        lang = "it" if al.startswith("it") else "en"
    except Exception:
        lang = "en"
    T = {
        "it": ("Scarica l'app",
               "Installa AudioBook Maker &amp; Player per ascoltare i tuoi audiolibri sul telefono."),
        "en": ("Get the app",
               "Install AudioBook Maker &amp; Player to listen to your audiobooks on your phone."),
    }
    title, body = _i18n.pick(T, lang, merge=False)
    return (_render_install_page(lang, title, body), 200,
            {"Content-Type": "text/html; charset=utf-8"})


# E3 (primo seam, 2026-10-09): /t/<token> e /s/<token> nel blueprint
# routes_tokens, registrato dopo configure (riceve la pagina install).
routes_tokens.configure(_render_install_page)
app.register_blueprint(routes_tokens.bp)


@app.route("/privacy")
def privacy_page():
    # Informativa privacy (richiesta da Play Store e GDPR). IT default, EN via
    # ?lang=en o Accept-Language. Pagina statica self-contained.
    lang = (request.args.get("lang") or "").strip().lower()[:2]
    if lang not in ("it", "en"):
        al = (request.headers.get("Accept-Language") or "").strip().lower()
        lang = "en" if al.startswith("en") else "it"
    return privacy_content.render_privacy_page(lang, BASE_URL)


@app.route("/support")
def support_page():
    # Pagina di assistenza con FAQ sull'app. IT default, EN via ?lang=en o
    # Accept-Language. Pagina statica self-contained (come /privacy).
    lang = (request.args.get("lang") or "").strip().lower()[:2]
    if lang not in ("it", "en"):
        al = (request.headers.get("Accept-Language") or "").strip().lower()
        lang = "en" if al.startswith("en") else "it"
    return support_content.render_support_page(lang, BASE_URL)


@app.route("/robots.txt")
def robots():
    sitemap_line = f"Sitemap: {BASE_URL}/sitemap.xml" if BASE_URL else ""
    llms_line = f"# LLM/AI agents index: {BASE_URL}/llms.txt" if BASE_URL else ""
    body = _render_page("robots.txt", {"__P0__": (sitemap_line), "__P1__": (llms_line)}).strip()
    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}


#  -  -  -  llms.txt  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -
# Spec: https://llmstxt.org — Markdown index per agenti AI (ChatGPT,
# Perplexity, Claude, Gemini). Aiuta retrieval/citation espliciti.
@app.route("/llms.txt")
def llms_txt():
    base = BASE_URL or "https://audiobook-maker.com"
    # Live "User feedback" block — empty string when no approved reviews exist,
    # so the section silently degrades instead of emitting a stub. The block
    # itself is fully formed Markdown bullets (headline + up to 3 dated
    # excerpts) so AI assistants can cite specific reviews verbatim.
    try:
        _feedback_md = seo_reviews.llms_txt_block()
    except Exception:
        _feedback_md = ""
    rating_block = f"\n## User feedback\n\n{_feedback_md}\n" if _feedback_md else ""

    # Citations section — gives AI agents a stable list of canonical URLs
    # they can attribute when quoting facts from this site. Each citation
    # is a permanent endpoint (not an HTML page that may be redesigned).
    citations_block = f"""
## Citations

When quoting facts from this site, cite one of:

- [Audiobook Maker (canonical home)]({base}/): SoftwareApplication entity, primary URL.
- [JSON-LD structured data](https://schema.org/SoftwareApplication): @type SoftwareApplication, applicationCategory MultimediaApplication, isAccessibleForFree true, license AGPL-3.0-or-later.
- [Sitemap]({base}/sitemap.xml): Authoritative URL index with lastmod dates.
- [GitHub source](https://github.com/gfrangiamone/audiobook-maker): Verifiable source code under AGPL-3.0-or-later.
- [License (AGPL-3.0)](https://www.gnu.org/licenses/agpl-3.0.html): Full license text.
- [Reviews & ratings]({base}/#reviews): User-submitted reviews with AggregateRating schema (refreshes per request).
"""
    body = f"""# Audiobook Maker

> Free, open-source online converter that turns EPUB and PDF ebooks into MP3 and M4B audiobooks using 400+ neural AI voices (Microsoft Edge TTS) across 50+ languages. No signup, no usage limits, runs in the browser. Optional AI text optimization (DeepSeek LLM) for natural-sounding narration. AGPL-3.0 licensed.

## Key facts

- Pricing: 100% free, donor-supported. No ads.
- Voices: 400+ neural TTS voices via Microsoft Edge TTS.
- Output formats: MP3 (single or ZIP), M4B with embedded chapters, podcast RSS 2.0 feed.
- Input formats: EPUB, PDF, TXT, ABM (revisable project archive).
- UI languages: Italian, English, French, Spanish, German, Chinese.
- TTS supported languages: 50+ (Italian, English, French, Spanish, German, Chinese, Portuguese, Russian, Japanese, Korean, Arabic, Hindi, and more).
- Privacy: uploaded files and generated audio auto-deleted at session end. No personal data collected. GA4 with Consent Mode v2 (denied by default in EU).
- Accessibility: WAI-ARIA landmarks, keyboard navigation, screen-reader compatible. Designed for users with dyslexia, low vision, blindness.
- License: AGPL-3.0-or-later. Source on GitHub.
- Author: Giuseppe Frangiamone.
{rating_block}
## Features

""" + "\n".join(f"- {f}" for f in seo_content.lang_content("en").get("features", [])) + f"""

## Accessibility

""" + seo_content.lang_content("en").get("accessibility", "") + _render_page("llms.txt", {"__P0__": (base), "__P1__": (citations_block)})
    return body, 200, {
        "Content-Type": "text/markdown; charset=utf-8",
        "Cache-Control": "public, max-age=3600",
    }


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


@app.route("/og-image.png")
def og_image():
    return send_file(get_og_image(), mimetype="image/png",
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


#  -  -  -  Admin log viewer (/admin/log-activity)  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -
# URL: /admin/log-activity?2026-03  (parametro = anno-mese)
# Non indicizzato (gia` coperto da Disallow: /admin/ in robots.txt)


# Eventi che segnano l'avvio effettivo del libro (mai le anteprime): con
# voce PREMIUM sulla riga la sessione entra nel filtro "PREMIUM" del pannello.
_PREMIUM_START_OPS = frozenset({"GENERATE", "OPTIMIZE"})

# generation_engine._log_m4b_progress scrive il proprio payload libero
# (size_mb=... elapsed_s=... pct=... status=...) nella colonna voice delle
# righe M4B_START/M4B_PROGRESS/M4B_END. Queste righe non devono aggiornare
# voice/lang/ip della sessione ("ultimo valore non vuoto vince" altrimenti
# sovrascrive la voce reale con il payload): vedi item 1 del final-fix-brief.
_M4B_OP_PREFIX = "M4B_"


def _parse_log_sessions(ym):
    """Sessioni del business log del mese YYYY-MM.

    Ritorna (sessions OrderedDict job_id -> dict, client_session_count dict)."""
    from collections import OrderedDict

    sessions = OrderedDict()
    for fields in activity_log.month_rows(ym):
        (sid, dt_str, filename, operation, client_id, client_ip,
         voice, browser_lang, platform) = fields
        # Righe di sistema (voucher, admin, backend TTS) senza job: non sono
        # sessioni. Prima uscivano di fatto perche' lo strip() iniziale
        # sfasava i campi e la data non si leggeva piu'.
        if not sid:
            continue
        # Skip voucher audit entries — not conversion activity
        if operation.startswith("VOUCHER_ATTEMPT"):
            continue

        # fromisoformat e' in C: strptime su ~85k righe/mese era meta' del
        # tempo della pagina. Il controllo di forma tiene fuori quello che
        # strptime("%Y-%m-%d %H:%M:%S") rifiutava e fromisoformat accetterebbe
        # (solo data, "T", fuso, frazioni di secondo).
        if len(dt_str) != 19 or dt_str[10] != " ":
            continue
        try:
            dt = datetime.fromisoformat(dt_str)
        except ValueError:
            continue

        # Avvio reale del libro con voce PREMIUM: GENERATE, oppure
        # OPTIMIZE del wizard combinato (ottimizza + auto-gen), che porta
        # la voce di destinazione gia' in fase di ottimizzazione AI. Si
        # guarda la voce della RIGA, non l'ultima vista sulla sessione:
        # un'anteprima premium seguita da un OPTIMIZE senza voce non conta.
        premium_started = (
            operation in _PREMIUM_START_OPS
            and (_is_gemini_voice(voice) or _is_speechify_voice(voice)
                 or _is_voxcpm_voice(voice))
        )
        is_m4b = operation.startswith(_M4B_OP_PREFIX)
        if sid not in sessions:
            sessions[sid] = {
                "first_dt": dt, "last_dt": dt,
                "filename": filename, "last_op": operation,
                "events": [operation],
                "client_id": client_id,
                "client_ip": "" if is_m4b else client_ip,
                "voice": "" if is_m4b else voice,
                "browser_lang": "" if is_m4b else browser_lang,
                "platform": platform,
                "transferred": operation == "TRANSFER",
                "premium_started": premium_started,
            }
        else:
            s = sessions[sid]
            if premium_started:
                s["premium_started"] = True
            if dt < s["first_dt"]:
                s["first_dt"] = dt
            if dt >= s["last_dt"]:
                s["last_dt"] = dt
                s["last_op"] = operation
            # Solo se valorizzato: gli eventi di servizio (TRANSFER,
            # ADMIN_COPY*) loggano filename vuoto e altrimenti cancellavano
            # il titolo del libro dalla card della sessione.
            if filename:
                s["filename"] = filename
            s["events"].append(operation)
            if client_id:
                s["client_id"] = client_id
            # Le righe M4B_* portano il payload libero nel campo voice (e
            # ripetono client_ip/lang del job): non devono vincere su
            # "ultimo valore non vuoto" per voice/lang/ip.
            if client_ip and not is_m4b:
                s["client_ip"] = client_ip
            if voice and not is_m4b:
                s["voice"] = voice
            if browser_lang and not is_m4b:
                s["browser_lang"] = browser_lang
            if platform and not s["platform"]:
                s["platform"] = platform
            if operation == "TRANSFER":
                s["transferred"] = True

    client_session_count = {}
    for s in sessions.values():
        cid = s.get("client_id", "")
        if cid:
            client_session_count[cid] = client_session_count.get(cid, 0) + 1

    return sessions, client_session_count


# Sessioni gia' costruite per mese, chiave = (ym, impronta del mese in
# activity_log): un log che cresce cambia l'impronta e si ricostruisce da
# solo, un mese chiuso si costruisce una volta sola. I risultati sono
# condivisi fra richieste: chi li usa li legge e basta.
# E3 (seam admin, parte 2): cache sessioni, card, funnel e power user in routes_admin_logs.


# ---------------------------------------------------------------------------
# Moderazione anti-abuso della quota voci standard (abuse_watch)
# ---------------------------------------------------------------------------

# net:<hash> è sempre sha256(salt+ip)[:16] esadecimale; cid:<...> è invece
# l'abm_cid grezzo (uuid4[:12], contiene trattini) usato come fallback quando
# manca l'IP: niente whitespace/caratteri di controllo in entrambi i rami.
_ABUSE_GROUP_RE = re.compile(r"^(net:[0-9a-f]{16,64}|cid:[A-Za-z0-9._-]{1,64})$")


def _abuse_group_of(job):
    return abuse_watch.group_key(job.get("client_ip", ""), job.get("client_id", ""))


def _abuse_reset_recovery_markers(job):
    """Reset dei marcatori anti-abuso su un job ricostruito dal recovery, che
    bypassa /api/generate (unico altro punto che li resetta al claim). Senza
    questo, un job recuperato erediterebbe abuse_terminated/abuse_kept_until
    da un descrittore precedente e non avrebbe abuse_group per essere
    riconosciuto dal kill loop. Fail-open: mai bloccante per il recovery."""
    try:
        job.pop("abuse_terminated", None)
        job.pop("abuse_kept_until", None)
        job["abuse_group"] = _abuse_group_of(job)
    except Exception as e:
        print(f"[recover] abuse marker reset failed (non-fatal): {e}", flush=True)
    return job


def _abuse_note(job_id, job, kind, **data):
    """Aggiorna il dossier anti-abuso e, al secondo segnale, accoda il giudizio.
    Best-effort: mai bloccante per il chiamante."""
    try:
        cid = job.get("client_id", "")
        group = _abuse_group_of(job)
        data.setdefault("filename", job.get("original_filename", ""))
        data.setdefault("lang", getattr(job.get("info"), "language", "") or "")
        group_data = abuse_watch.record_event(group, cid, kind, data)
        if abuse_watch.needs_judgement(group, cid, group_data=group_data):
            abuse_watch.enqueue(group, cid)
    except Exception as e:
        print(f"[{job_id}] abuse_watch {kind} failed (non-fatal): {e}", flush=True)


def _abuse_apply_verdict(group, verdict):
    """Callback del worker di giudizio: su verdetto `abuse` sopra soglia uccide
    i job IN CORSO dei cid nello scope, non pagati e a voce standard, con la
    meccanica di cancel esistente (`cancelled` + marcatore `abuse_terminated`,
    letto da _check_cancelled e dal ramo _CancelledError). Ritorna il numero
    di job uccisi."""
    if not isinstance(verdict, dict) or verdict.get("verdict") != "abuse":
        return 0
    try:
        conf = float(verdict.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    if not abuse_watch.kill_enabled() or conf < abuse_watch.confidence_threshold():
        print(f"[abuse] verdetto abuse su {group} senza kill "
              f"(enable={abuse_watch.kill_enabled()}, conf={conf:.2f})", flush=True)
        return 0
    scope_cids = set(verdict.get("cids") or [])
    killed = []
    with _jobs_lock:
        for jid, job in list(jobs.items()):
            if job.get("status") != "generating" or job.get("abuse_terminated"):
                continue
            if job.get("abuse_group") != group or job.get("client_id") not in scope_cids:
                continue
            if generation_engine.is_premium_job(job):
                continue
            job["abuse_terminated"] = True
            job["cancelled"] = True
            killed.append((jid, job))
    for jid, job in killed:
        try:
            _log_activity(jid, job.get("original_filename", ""), "QUOTA_ABUSE_KILL",
                          job.get("client_id", ""), job.get("client_ip", ""),
                          _voice_for_log(job.get("voice", "")), browser_lang=job.get("browser_lang", ""))
        except Exception:
            pass
        try:
            abuse_watch.record_kill(group, job.get("client_id", ""), jid)
        except Exception:
            pass
        print(f"[{jid}] abuse kill (gruppo {group}, conf {conf:.2f})", flush=True)
    return len(killed)


def _abuse_keep_state(job, now):
    """'hold' finche' la work_dir del job ucciso va conservata, 'expired'
    oltre `abuse_kept_until`, None se il job non e' stato ucciso per abuso."""
    kept = job.get("abuse_kept_until")
    if not kept:
        return None
    try:
        kept = float(kept)
    except (TypeError, ValueError):
        return None
    return "hold" if now < kept else "expired"


def _abuse_cleanup_decision(job, now, has_active_token):
    """Decisione pura per il ramo 'analyzed' di cleanup._cleanup_loop su un job ucciso
    dalla moderazione anti-abuso (`_abuse_keep_state` non None): 'hold' finche'
    dentro la finestra di retention forense; 'remove' a finestra scaduta senza
    download token attivi; 'pass' a finestra scaduta con un token ancora
    attivo (si tiene la work_dir per non rompere un link valido)."""
    ak = _abuse_keep_state(job, now)
    if ak == "hold":
        return "hold"
    if ak == "expired":
        return "pass" if has_active_token else "remove"
    return "pass"


def _abuse_digest_data():
    """Righe per la sezione «Casi di abuso» del digest admin (24h)."""
    try:
        rows = abuse_watch.digest_data(ADMIN_DIGEST_INTERVAL_SEC)
    except Exception:
        return None
    if not rows:
        return None
    return {"rows": rows, "window_hours": max(1, int(ADMIN_DIGEST_INTERVAL_SEC // 3600)),
            "kill_enabled": abuse_watch.kill_enabled()}


# Register funnel + power user providers with email_service (injection — avoids circular import)
try:
    import email_service as _email_service
    _email_service.set_funnel_provider(lambda: routes_admin_logs._funnel_data(routes_admin_logs._last_n_days(30)))
    _email_service.set_power_users_provider(routes_admin_logs._power_users_data)
    _email_service.set_abuse_provider(_abuse_digest_data)
except Exception:
    pass


# E3 (seam admin, parte 2, 2026-10-10): console del log attivita' e funnel nel
# blueprint routes_admin_logs (vedi routes_admin_audit per il metodo).
routes_admin_logs.configure(
    admin_required=admin_required, admin_token=lambda: ADMIN_TOKEN,
    admin_auth_ok=lambda provided: _admin_auth_ok(provided),
    admin_auth_from_request=lambda: _admin_auth_from_request(),
    render_admin_gate=lambda title, url: _render_admin_gate(title, url),
    parse_log_sessions=lambda ym: _parse_log_sessions(ym),
    activity_log_dir=lambda: _activity_log_dir(),
    get_browser_lang=lambda: _get_browser_lang(),
    jobs=lambda: jobs, favicon=FAVICON_B64)
app.register_blueprint(routes_admin_logs.bp)



#  -  -  -  Admin voucher web UI (/admin/vouchers)  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
# Protetta da token ABM_ADMIN_TOKEN. Se il token non è configurato, endpoint 404.
# Il token viene inviato via header X-Admin-Token (dalle API) o nel form HTML.
# Confronto a tempo costante tramite hmac.compare_digest.

def _render_admin_gate(title, target_url):
    """Render a password gate for admin pages."""
    return _render_page("admin_gate", {"__P0__": (title)})


#  -  -  Admin API: sospensione nuovi processi  -  -

# E3 (seam admin, parte 4): suspend in routes_admin_jobs.




def _admin_auth_ok(provided):
    """Costante-time check del token admin."""
    if not ADMIN_TOKEN or not provided:
        return False
    return hmac.compare_digest(str(provided), ADMIN_TOKEN)


_ADMIN_COOKIE_NAME = "abm_admin_session"


def _admin_auth_from_request():
    """Estrae il token admin dall'header X-Admin-Token o dal cookie HttpOnly abm_admin_session.

    Sec: NON accettiamo più il token da query string (`?token=`) né da form GET/POST:
    il valore comparirebbe in access log nginx, history browser, Referer verso domini esterni.
    Il cookie è settato esclusivamente dall'endpoint POST /admin/login con HttpOnly+SameSite=Strict.
    """
    tok = request.headers.get("X-Admin-Token", "")
    if not tok:
        tok = request.cookies.get(_ADMIN_COOKIE_NAME, "")
    return tok




@app.route("/admin/login", methods=["POST"])
def admin_login():
    """Login admin: valida il token e lo deposita in cookie HttpOnly Secure SameSite=Strict.
    Il client JS POSTa qui invece di mettere il token nell'URL."""
    if not ADMIN_TOKEN:
        return jsonify({"error": "Admin disabled"}), 404
    data = request.json or {}
    tok = (data.get("token") or "").strip()
    remember = bool(data.get("remember", True))
    if not _admin_auth_ok(tok):
        return jsonify({"error": "Invalid token"}), 401
    resp = jsonify({"ok": True})
    is_https = (request.scheme == "https") or (request.headers.get("X-Forwarded-Proto", "") == "https")
    # 30 giorni con "remember" (default), 8 ore altrimenti. Il cookie è HttpOnly+Strict
    # quindi non può essere esfiltrato lato client; estendere la durata evita un round-trip
    # extra (gate → /admin/login → reload) a ogni navigazione successiva alla scadenza.
    max_age = 30 * 86400 if remember else 8 * 3600
    resp.set_cookie(
        _ADMIN_COOKIE_NAME, tok,
        max_age=max_age,
        httponly=True,
        secure=is_https,
        samesite="Strict",
        path="/",
    )
    return resp


@app.route("/admin/logout", methods=["POST", "GET"])
def admin_logout():
    """Logout admin: cancella il cookie di sessione."""
    resp = jsonify({"ok": True}) if request.method == "POST" else ("Logged out", 200)
    if isinstance(resp, tuple):
        from flask import make_response
        body, code = resp
        resp = make_response(body, code)
    resp.set_cookie(_ADMIN_COOKIE_NAME, "", max_age=0, httponly=True, samesite="Strict", path="/")
    return resp


# E3 (seam admin, parte 3, 2026-10-10): pagina e API dei voucher nel
# blueprint routes_admin_vouchers (vedi routes_admin_audit per il metodo).
routes_admin_vouchers.configure(
    admin_required=admin_required, admin_token=lambda: ADMIN_TOKEN,
    admin_auth_ok=lambda provided: _admin_auth_ok(provided),
    admin_auth_from_request=lambda: _admin_auth_from_request(),
    render_admin_gate=lambda title, url: _render_admin_gate(title, url),
    log_activity=lambda *a, **k: _log_activity(*a, **k),
    client_ip=lambda: client_ip())
app.register_blueprint(routes_admin_vouchers.bp)




# E3 (seam admin, parte 4): copyqr in routes_admin_jobs.


# E3 (seam admin, parte 1, 2026-10-10): pagine e API dell'audit premium nel
# blueprint routes_admin_audit. Funzioni passate come lambda (risolte a ogni
# richiesta: i test le sostituiscono su questo modulo), stato condiviso per
# riferimento.
routes_admin_audit.configure(
    admin_required=admin_required, admin_token=lambda: ADMIN_TOKEN,
    admin_auth_ok=lambda provided: _admin_auth_ok(provided),
    admin_auth_from_request=lambda: _admin_auth_from_request(),
    render_admin_gate=lambda title, url: _render_admin_gate(title, url),
    log_activity=lambda *a, **k: _log_activity(*a, **k),
    client_ip=lambda: client_ip(),
    invalidate_voices_cache=lambda: _invalidate_voices_cache(),
    vc_translate_reject_note=lambda clone_id: routes_voice_clone._vc_translate_reject_note(clone_id),
    jobs=lambda: jobs, jobs_lock=_jobs_lock, engine=generation_engine)
app.register_blueprint(routes_admin_audit.bp)
_ACTIVE_JOB_STATUSES = routes_admin_audit._ACTIVE_JOB_STATUSES   # usato da /api/my_jobs




@app.route("/api/voices")
def api_voices():
    try:
        voices = get_voices()
        # La cache voci vive per tutto il processo: un modello Gemini spento,
        # senza canale o indisponibile si toglie qui, a ogni richiesta, su una
        # copia (mai sulla cache condivisa).
        if gemini_tts is not None:
            try:
                offerti = set(gemini_tts.offered_model_keys())
                filtrate = {}
                for k, v in voices.items():
                    if isinstance(v, dict) and isinstance(v.get("voices"), list):
                        v = dict(v)
                        v["voices"] = [x for x in v["voices"]
                                       if not (isinstance(x, dict) and x.get("engine") == "gemini"
                                               and x.get("model_key") not in offerti)]
                    filtrate[k] = v
                voices = filtrate
            except Exception:
                pass
        # Stato voci PREMIUM: distingue "non configurato" (capability_ok=False)
        # da "spento per scelta admin" (admin_disabled=True). Serve alla UI per
        # mostrare il tab Premium con popup di manutenzione invece di nasconderlo,
        # cosi` l'utente non vede combo vuote che fanno sembrare l'app rotta.
        if gemini_tts is not None:
            try:
                cap_ok = bool(gemini_tts.is_capability_available())
                admin_state = gemini_tts.admin_disabled_state()
                voices["_premium_status"] = {
                    "capability_ok": cap_ok,
                    "admin_disabled": bool(admin_state.get("disabled", False)),
                }
            except Exception:
                pass
            try:
                voices["_gemini"] = {
                    "preview_timeout_ms": {
                        mk: (gemini_tts.preview_timeout_sec(mk) + 5) * 1000
                        for mk in gemini_tts.GEMINI_MODELS},
                }
            except Exception:
                pass
        # Stato VoxCPM per il tab premium: se il motore non e' disponibile la
        # UI non mostra il modello, invece di mostrarlo con la combo vuota.
        # `personas` e' l'elenco dei CARATTERI presenti nel catalogo di oggi:
        # arriva da li' e non da una costante, cosi' un carattere nuovo non
        # richiede un rilascio (D10).
        if voxcpm_tts is not None:
            try:
                disponibile = bool(voxcpm_tts.is_available())
                voices["_voxcpm"] = {
                    "available": disponibile,
                    "model_label": voxcpm_catalog.MODEL_LABEL,
                    "personas": voxcpm_catalog.personas() if disponibile else [],
                }
            except Exception:
                voices["_voxcpm"] = {"available": False, "model_label": "",
                                     "personas": []}
        # Voci campionate dell'utente (spec voci-campionate, piano 2): calcolo
        # per richiesta, mai dentro _fetch_voices (la cache e' condivisa fra
        # tutti gli utenti, "_mine" no).
        try:
            voices["_mine"] = (voice_clone.mine(_get_client_id())
                               if (voxcpm_tts is not None and voice_clone.enabled()) else [])
        except Exception as e:      # noqa: BLE001
            print(f"[voice_clone] mine failed: {type(e).__name__}", flush=True)
            voices["_mine"] = []
        # Disponibilita' traduzione libro: backend LLM configurato + modello di
        # traduzione esplicito (ABM_TRANSLATE_MODEL). Se False la UI nasconde il
        # bottone "Traduci" invece di farlo fallire dopo la selezione capitoli.
        try:
            voices["_translate_available"] = bool(translation_core.is_available())
        except Exception:
            voices["_translate_available"] = False
        return jsonify(voices)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/voice_sample")
def api_voice_sample():
    """Il `.wav` di riferimento di una voce di catalogo.

    Sostituisce l'anteprima di lettura per le voci VoxCPM (§5.2): l'anteprima
    costerebbe un'accensione del worker per pochi secondi di audio, mentre il
    campione e' un file che esiste gia' e che dice esattamente come suonera'
    la voce, perche' e' proprio quello che il modello clonera'.

    Non e' un file statico: il catalogo sta in una cartella importata e
    configurabile, e solo `voxcpm_catalog` sa quali voci sono valide.
    """
    voice_id = (request.args.get("voice") or "").strip()
    if voxcpm_catalog is None:
        return jsonify({"error": "voxcpm non disponibile"}), 404
    try:
        percorso = voxcpm_catalog.sample_path(voice_id)
    except ValueError as e:
        # Id malformato, motore sbagliato, o voce non piu' in catalogo dopo una
        # rigenerazione: dal punto di vista del browser sono la stessa cosa,
        # una richiesta a cui non si puo' rispondere.
        messaggio = str(e)
        codice = 404 if "non presente nel catalogo" in messaggio else 400
        return jsonify({"error": messaggio}), codice
    except FileNotFoundError:
        return jsonify({"error": "campione non disponibile"}), 404
    return send_file(percorso, mimetype="audio/wav", conditional=True)


@app.route("/api/voice_demo")
def api_voice_demo():
    """Una clip dimostrativa di una voce di catalogo (§17).

    Le due clip generate — la frase comune a tutte le voci e la frase nelle
    corde di questa — sono l'ascolto dell'utente in fase di scelta: prodotte
    esattamente come sara' prodotto il libro, sono la promessa commerciale
    della voce. Stesse regole del campione: il catalogo e' importato, i
    percorsi non sono fidati.
    """
    voice_id = (request.args.get("voice") or "").strip()
    clip_id = (request.args.get("clip") or "").strip()
    if voxcpm_catalog is None:
        return jsonify({"error": "voxcpm non disponibile"}), 404
    try:
        percorso = voxcpm_catalog.demo_path(voice_id, clip_id)
    except ValueError as e:
        # Id malformato -> 400; clip o voce che non ci sono (piu') -> 404,
        # stesso criterio di /api/voice_sample.
        messaggio = str(e)
        codice = 404 if "non presente" in messaggio else 400
        return jsonify({"error": messaggio}), codice
    except FileNotFoundError:
        return jsonify({"error": "clip non disponibile"}), 404
    return send_file(percorso, mimetype="audio/wav", conditional=True)


# E3 (seam voice clone, 2026-10-10): API e pagine della voce campionata nel
# blueprint routes_voice_clone. Helper della app passati come lambda (risolti
# a ogni richiesta: i test li sostituiscono su questo modulo).
routes_voice_clone.configure(
    vc_pages_i18n=_VC_PAGES_I18N, lang_cookie=_LANG_COOKIE,
    upload_dir=lambda: UPLOAD_DIR, base_url=lambda: BASE_URL,
    _get_client_id=lambda *a, **k: _get_client_id(*a, **k),
    _apply_no_cache=lambda *a, **k: _apply_no_cache(*a, **k),
    _ip_rl_check=lambda *a, **k: _ip_rl_check(*a, **k),
    client_ip=lambda *a, **k: client_ip(*a, **k),
    _get_browser_lang=lambda *a, **k: _get_browser_lang(*a, **k),
    _current_account=lambda *a, **k: _current_account(*a, **k),
    _log_activity=lambda *a, **k: _log_activity(*a, **k),
    _maintenance_gate=lambda *a, **k: _maintenance_gate(*a, **k),
    _paypal_available=lambda *a, **k: _paypal_available(*a, **k),
    _paypal_create_order=lambda *a, **k: _paypal_create_order(*a, **k),
    _sse_event=lambda *a, **k: _sse_event(*a, **k),
    _sse_response=lambda *a, **k: _sse_response(*a, **k))
app.register_blueprint(routes_voice_clone.bp)



# E3: blocco spostato in routes_community.

_IP_SALT = _ip_salt()


# ─── Rate limit generico IP-based (sliding window) ─────────────────
# Usato per endpoint costosi (upload, preview audio) per limitare DoS.
_ip_rl_lock = threading.Lock()
_ip_rl_buckets: dict[str, dict[str, list[float]]] = {}


def _ip_rl_check(bucket: str, ip: str, limit_per_min: int, limit_per_hour: int):
    """Sliding-window rate limit IP-based. Ritorna (allowed, retry_after_sec).
    bucket: identificativo logico (es. 'analyze', 'preview').
    """
    if not ip:
        return True, 0
    with _ip_rl_lock:
        ok, retry, _idx = _sliding_check(
            _ip_rl_buckets.setdefault(bucket, {}), ip,
            [(60, limit_per_min), (3600, limit_per_hour)], time.time())
    return ok, retry


# Default limits (override via env per ops emergency)
_ANALYZE_RL_PER_MIN = env_int("ABM_ANALYZE_RL_PER_MIN", 5)
_ANALYZE_RL_PER_HOUR = env_int("ABM_ANALYZE_RL_PER_HOUR", 30)
_PREVIEW_RL_PER_MIN = env_int("ABM_PREVIEW_RL_PER_MIN", 20)
_PREVIEW_RL_PER_HOUR = env_int("ABM_PREVIEW_RL_PER_HOUR", 200)


def _hash_ip(ip: str) -> str:
    # Forma storica: sha256(salt + ":" + ip)[:16] (chiavi di rate limit e log).
    return _salted_hash(ip or "", salt=_IP_SALT, sep=":")


# ===========================================================================
# Account: sessione, gate, pagine e route di autenticazione
# ===========================================================================

_ACCOUNT_SESSION_COOKIE = "abm_session"
# _ACCT_EMAIL_RE: client_identity.EMAIL_RE (import in testa).


def _acct_err(code, msg, status, **extra):
    return jsonify({"error": msg, "error_code": code, **extra}), status


def _acct_gate():
    """None se la feature e' usabile, altrimenti la risposta 404 da ritornare."""
    if not accounts.enabled() or not _smtp_available():
        return _acct_err("account_disabled", "Accounts are not available", 404)
    return None


def _acct_session_token():
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(_ACCOUNT_SESSION_COOKIE, "")


def _current_account():
    """Account della richiesta corrente o None. Cache in flask.g."""
    if hasattr(g, "_acct"):
        return g._acct
    acct = None
    try:
        if accounts.enabled():
            acct = accounts.resolve_session(_acct_session_token())
    except Exception as e:  # noqa: BLE001
        print(f"WARNING _current_account: {e}", flush=True)
    g._acct = acct
    return acct


def _acct_cookie_secure():
    if (BASE_URL or "").startswith("https"):
        return True
    return (request.headers.get("X-Forwarded-Proto") or "").lower() == "https"


def _acct_set_cookie(resp, token):
    resp.set_cookie(_ACCOUNT_SESSION_COOKIE, token, max_age=accounts.SESSION_DAYS * 86400,
                    httponly=True, samesite="Lax", secure=_acct_cookie_secure(), path="/")


def _acct_clear_cookie(resp):
    resp.set_cookie(_ACCOUNT_SESSION_COOKIE, "", max_age=0, expires=0, httponly=True,
                    samesite="Lax", secure=_acct_cookie_secure(), path="/")


# --- anti login-CSRF sul magic link ------------------------------------
# Il POST di /auth/<token> apre una sessione: senza guardia un sito terzo puo'
# auto-inviare un form verso /auth/<token_dell_attaccante> e il browser della
# vittima riceve Set-Cookie: abm_session (SameSite=Lax impedisce di INVIARE
# cookie cross-site, non di IMPOSTARLI). La vittima si ritrova loggata
# nell'account dell'attaccante e i suoi job successivi vengono notificati a
# quell'indirizzo. La guardia e' un double-submit cookie legato al BROWSER che
# ha aperto il link: un nonce derivato dal token non servirebbe, perche' il
# token e' dell'attaccante e il nonce sarebbe leggibile dal suo stesso GET.
_ACCT_CSRF_COOKIE = "abm_auth_csrf"


def _acct_set_csrf_cookie(resp, value):
    resp.set_cookie(_ACCT_CSRF_COOKIE, value, max_age=accounts.CODE_TTL_MIN * 60,
                    httponly=True, samesite="Strict", secure=_acct_cookie_secure(),
                    path="/auth")


def _acct_clear_csrf_cookie(resp):
    resp.set_cookie(_ACCT_CSRF_COOKIE, "", max_age=0, expires=0, httponly=True,
                    samesite="Strict", secure=_acct_cookie_secure(), path="/auth")


def _acct_origin_ok():
    """False se la richiesta arriva dichiaratamente da un'altra origine.

    Header assenti = consentito: su una navigazione diretta (click sul link
    dell'email) alcuni browser non mandano ne' Origin ne' Referer.
    Ammesse due origini: quella dichiarata in BASE_URL (se valorizzata) e
    quella della richiesta stessa (`host_url`), perche' l'host arriva dal
    browser e non e' scrivibile da una pagina terza — e' lo stesso criterio
    del guard globale `_csrf_protect`. Serve a non chiudere fuori un
    deployment raggiungibile anche su un hostname diverso da ABM_BASE_URL."""
    origin = (request.headers.get("Origin") or "").strip()
    if origin.lower() == "null":
        return False
    src = origin or (request.headers.get("Referer") or "").strip()
    if not src:
        return True
    from urllib.parse import urlsplit
    a = urlsplit(src)
    allowed = {(urlsplit(request.host_url).scheme, urlsplit(request.host_url).netloc)}
    base = (BASE_URL or "").strip()
    if base:
        b = urlsplit(base)
        allowed.add((b.scheme, b.netloc))
    return (a.scheme, a.netloc) in allowed


def _acct_csrf_ok():
    """Double-submit: il campo nascosto del form deve combaciare con il cookie
    posato dal GET sullo stesso browser."""
    sent = (request.form.get("csrf") or "").strip()
    cookie = (request.cookies.get(_ACCT_CSRF_COOKIE) or "").strip()
    if not sent or not cookie:
        return False
    return hmac.compare_digest(sent, cookie)


def _acct_log(op, email, extra=""):
    """Business log senza email in chiaro: sid = acct-<hash8>."""
    try:
        sid = "acct-" + accounts.email_hash(email)[:8]
        _log_activity(sid, extra, op, client_id=_get_client_id(), client_ip=client_ip())
    except Exception as e:  # noqa: BLE001
        print(f"WARNING _acct_log: {e}", flush=True)


def _acct_page_lang(*preferred):
    """Lingua delle pagine account: scelta nell'app (`?lang=`, poi cookie
    `abm_lang`), poi quelle passate dal chiamante (lingua dell'account o
    del codice), poi Accept-Language, poi inglese. I valori non tradotti
    sono saltati, non degradano a inglese."""
    return _i18n.choose_lang([request.args.get("lang"), request.cookies.get(_LANG_COOKIE),
                              *preferred, _get_browser_lang()], _ACCT_PAGES_I18N)


def _acct_txt(lang):
    return _i18n.pick(_ACCT_PAGES_I18N, lang)


def _acct_html(html_doc, status=200):
    resp = _apply_no_cache(Response(html_doc, status=status, mimetype="text/html"))
    resp.headers["Vary"] = "Accept-Language, Cookie"
    return resp


def _acct_send_code(email, purpose, lang):
    """Genera e spedisce il codice. Sempre silenzioso: risposta neutra a monte."""
    try:
        out = accounts.request_code(email, purpose, lang, ip_hash=_hash_ip(client_ip()),
                                    ua=request.headers.get("User-Agent", ""))
        if out is None:
            return
        token, code = out
        if accounts.is_review_login(email, purpose):
            # Account demo dei revisori store: codice fisso, niente email.
            _acct_log("ACCOUNT_REVIEW_CODE", email)
            return
        link = f"{BASE_URL}/auth/{token}" + ("?p=delete" if purpose == "delete" else "")
        email_service.send_account_code(
            email, lang, code=code, link_url=link,
            purpose=purpose, minutes=accounts.CODE_TTL_MIN)
    except Exception as e:  # noqa: BLE001
        print(f"WARNING _acct_send_code: {type(e).__name__}: {e}", flush=True)


def _acct_do_delete(acct, lang):
    """Cancellazione confermata: DB, log, email di cortesia (best-effort)."""
    accounts.delete_account(acct["id"])
    _acct_log("ACCOUNT_DELETE", acct["email"])
    try:
        email_service.send_account_deleted(acct["email"], acct.get("lang") or lang)
    except Exception as e:  # noqa: BLE001
        print(f"WARNING send_account_deleted: {e}", flush=True)


def _acct_device_name(raw=None):
    """Nome del dispositivo mostrato in «I tuoi dispositivi»: quello dichiarato
    dal client (app) o quello dedotto dallo User-Agent («Chrome · Windows»);
    se non si riconosce nulla resta lo User-Agent grezzo, troncato."""
    raw = str(raw or "").strip()[:80]
    if raw:
        return raw
    ua = request.headers.get("User-Agent") or ""
    return voice_clone.device_name_from_ua(ua) or ua[:80]


def _acct_login_response(acct, payload=None, device_name=None):
    """Apre la sessione, logga, imposta il cookie. `session_token` solo per
    l'app (header X-ABM-Cid), che non usa i cookie."""
    device_name = _acct_device_name(device_name)
    token = accounts.open_session(acct["id"],
                                  device_name=device_name,
                                  ip_hash=_hash_ip(client_ip()))
    _acct_log("ACCOUNT_LOGIN", acct["email"])
    body = {"ok": True, "email": acct["email"], "lang": acct.get("lang") or "en",
            "plan": acct.get("plan") or "free"}
    if payload is not None:
        body.update(payload)
    if (request.headers.get(_MOBILE_CID_HEADER) or "").strip():
        body["session_token"] = token
    resp = jsonify(body)
    _acct_set_cookie(resp, token)
    return resp


@app.route("/api/auth/request", methods=["POST"])
def api_auth_request():
    gate = _acct_gate()
    if gate:
        return gate
    ip = client_ip()
    allowed, retry = _ip_rl_check("auth_request", ip, 5, 30)
    if not allowed:
        return _acct_err("rate_limited", "Too many requests", 429, retry_after=retry)
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not _ACCT_EMAIL_RE.match(email):
        return _acct_err("invalid_email", "Invalid email address", 400)
    lang = (data.get("lang") or _get_browser_lang() or "en")[:8]
    _acct_send_code(email, "login", lang)
    return jsonify({"ok": True})


@app.route("/api/auth/verify", methods=["POST"])
def api_auth_verify():
    gate = _acct_gate()
    if gate:
        return gate
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    device_name = (data.get("device_name") or "").strip()[:80]
    if token:
        status, acct = accounts.verify(token=token, purpose="login")
    elif email and code:
        status, acct = accounts.verify(email=email, code=code, purpose="login")
    else:
        return _acct_err("bad_request", "token or email+code required", 400)
    if status != "ok":
        return _acct_err(status, "Verification failed", 401)
    return _acct_login_response(acct, device_name=device_name or None)


@app.route("/auth/<token>", methods=["GET", "POST"])
def auth_magic_link(token):
    lang = _acct_page_lang()
    t = _acct_txt(lang)
    if not accounts.enabled() or not _smtp_available():
        return _acct_html(account_page.render_error(t, lang=lang, status_key="none"), 404)
    purpose = "delete" if request.args.get("p") == "delete" else "login"
    if request.method == "GET":
        # Mai consumare al GET: i client di posta pre-aprono i link. Una
        # lettura innocua basta pero' a distinguere un link mai esistito
        # (410) da uno ancora valido in attesa di conferma (200). La lingua
        # segue quella scelta al momento della richiesta (auth_codes.lang,
        # la stessa con cui e' partita l'email), non quella del browser.
        status, info = accounts.peek(token, purpose)
        code_lang = info.get("lang") if info else None
        if code_lang in _ACCT_PAGES_I18N:
            lang = _acct_page_lang(code_lang)
            t = _acct_txt(lang)
        if status != "ok":
            return _acct_html(account_page.render_error(t, lang=lang, status_key=status), 410)
        csrf = secrets.token_urlsafe(16)
        resp = _acct_html(account_page.render_confirm(
            t, lang=lang, purpose=purpose, action_url=request.full_path.rstrip("?"),
            masked_email=account_page.mask_email(info["email"]), csrf=csrf))
        _acct_set_csrf_cookie(resp, csrf)
        return resp
    # Il token NON viene consumato se la conferma non proviene dal browser che
    # ha aperto il link: pagina d'errore generica (nessun indizio all'esterno
    # su validita' o stato del token) e nessun effetto collaterale.
    if not _acct_origin_ok() or not _acct_csrf_ok():
        return _acct_html(account_page.render_error(t, lang=lang, status_key="none"), 403)
    status, acct = accounts.verify(token=token, purpose=purpose)
    if acct and acct.get("lang") in _ACCT_PAGES_I18N:
        lang = _acct_page_lang(acct["lang"])
        t = _acct_txt(lang)
    if status != "ok":
        return _acct_html(account_page.render_error(t, lang=lang, status_key=status), 410)
    if purpose == "delete":
        _acct_do_delete(acct, lang)
        resp = _acct_html(account_page.render_deleted(t, lang=lang))
        _acct_clear_cookie(resp)
        _acct_clear_csrf_cookie(resp)
        return resp
    session_token = accounts.open_session(
        acct["id"], device_name=_acct_device_name(), ip_hash=_hash_ip(client_ip()))
    _acct_log("ACCOUNT_LOGIN", acct["email"])
    resp = redirect("/account", code=302)
    _acct_set_cookie(resp, session_token)
    _acct_clear_csrf_cookie(resp)
    return resp


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    gate = _acct_gate()
    if gate:
        return gate
    token = _acct_session_token()
    acct = _current_account()
    if token:
        try:
            accounts.revoke_session(token)
        except Exception as e:  # noqa: BLE001
            print(f"WARNING logout: {e}", flush=True)
    if acct:
        _acct_log("ACCOUNT_LOGOUT", acct["email"])
    resp = jsonify({"ok": True})
    _acct_clear_cookie(resp)
    return resp


@app.route("/api/auth/logout_all", methods=["POST"])
def api_auth_logout_all():
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    n = accounts.revoke_all(acct["id"])
    _acct_log("ACCOUNT_LOGOUT_ALL", acct["email"], str(n))
    resp = jsonify({"ok": True, "revoked": n})
    _acct_clear_cookie(resp)
    return resp


@app.route("/api/auth/logout_device", methods=["POST"])
def api_auth_logout_device():
    """Chiude una sola sessione dell'account (popup «I tuoi dispositivi»).
    L'id e' l'hash della sessione, non il token: mostrarlo non apre nulla.
    Se e' la sessione corrente il cookie viene tolto e il client torna alla
    home (`current: true`)."""
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    data = request.get_json(silent=True) or {}
    sid = str(data.get("id") or "").strip()
    if not sid:
        return _acct_err("bad_request", "id required", 400)
    ok = accounts.revoke_session_id(acct["id"], sid)
    _acct_log("ACCOUNT_LOGOUT_DEVICE", acct["email"], "ok" if ok else "none")
    if sid == (acct.get("session_id") or ""):
        resp = jsonify({"ok": True, "revoked": ok, "current": True})
        _acct_clear_cookie(resp)
        return resp
    return jsonify({"ok": True, "revoked": ok, "current": False})


@app.route("/api/auth/me", methods=["GET"])
def api_auth_me():
    if not accounts.enabled() or not _smtp_available():
        return jsonify({"logged_in": False, "enabled": False})
    acct = _current_account()
    if not acct:
        return jsonify({"logged_in": False, "enabled": True})
    return jsonify({
        "logged_in": True, "enabled": True, "email": acct["email"],
        "lang": acct.get("lang") or "en", "plan": acct.get("plan") or "free",
        "sessions_count": accounts.sessions_count(acct["id"]),
    })


_ACCT_PER_PAGE = 50


def _download_tokens_index():
    """Indice `job_id -> [(token, info)]` costruito UNA volta per richiesta da
    uno snapshot di _tkstore.download_tokens preso sotto _tkstore.tokens_lock.

    Due motivi, non uno: (a) _tkstore.download_tokens e' mutato dai thread di
    generazione (creazione token a fine job) e dal cleanup, quindi scorrerlo
    senza snapshot e' una `RuntimeError: dictionary changed size during
    iteration` in attesa del momento giusto — lo stesso schema che uccise il
    cleanup._cleanup_loop; (b) lo storico chiama _account_downloads_for per ogni riga
    mostrata, e una scansione lineare per riga costa O(righe x token)."""
    with _tkstore.tokens_lock:
        items = list(_tkstore.download_tokens.items())
    idx = {}
    for tok, ti in items:
        if not isinstance(ti, dict):
            continue
        jid = ti.get("job_id")
        if jid:
            idx.setdefault(jid, []).append((tok, ti))
    return idx


def _account_downloads_for(row, now=None, index=None):
    """Link ancora vivi per una riga dello storico. Il token arriva dalla
    riga (`download_token`) o, per i job adottati dai pagamenti, dalla
    ricerca per job_id nell'indice (`index`, vedi _download_tokens_index;
    se None viene costruito qui). `expires_at` usa la retention
    effettiva del token (protezione no-download compresa)."""
    now = now if now is not None else time.time()
    job_id = row.get("job_id") or ""
    token = row.get("download_token") or ""
    info = _tkstore.download_tokens.get(token) if token else None
    if info is None:
        if index is None:
            index = _download_tokens_index()
        candidates = index.get(job_id) or []
        if candidates:
            token, info = max(candidates, key=lambda kv: float(kv[1].get("created_at") or 0))
    if not isinstance(info, dict) or not token:
        return []
    try:
        expires_at = float(info.get("created_at") or 0) + float(_effective_retention_for_token_info(info))
    except Exception:  # noqa: BLE001
        return []
    if expires_at <= now:
        return []
    base = (BASE_URL or "").rstrip("/")
    exp = int(expires_at)
    out = [{"kind": "page", "url": f"{base}/dl/{token}", "expires_at": exp}]
    dl_type = info.get("download_type") or "audio"
    # File assenti su entrambi i tier -> nessun pulsante per quel formato
    # (ma la pagina /dl/<token> resta comunque linkata: puo' mostrare altri
    # formati ancora presenti dello stesso token).
    if dl_type == "optimized_abm":
        if routes_mobile._file_available(info.get("optimized_abm_path") or ""):
            out.append({"kind": "abm", "url": f"{base}/dl/{token}/abm", "expires_at": exp})
    elif dl_type == "translated":
        if routes_mobile._file_available(info.get("translated_path") or ""):
            out.append({"kind": "translated", "url": f"{base}/dl/{token}/translated", "expires_at": exp})
    elif info.get("output_m4b"):
        if routes_mobile._file_available(info.get("output_m4b") or ""):
            out.append({"kind": "m4b", "url": f"{base}/dl/{token}/m4b", "expires_at": exp})
    return out


# Una riga "running" il cui job non esiste piu' (ne' in memoria ne' come
# descrittore di recovery) oltre questa finestra e' persa: la si chiude.
_ACCT_STALE_RUNNING_SEC = 30 * 60
_ACCT_SETTLE_MAP = {"done": "done", "partial": "done", "error": "error",
                    "cancelled": "cancelled", "canceled": "cancelled"}


def _account_settled_status(job_id, row_updated_at, now):
    """Esito da scrivere su una riga di storico ancora "running", o None se il
    job e' (o puo' ancora essere) vivo. Rete di sicurezza per i path che
    escono dalla generazione senza passare da `_set_job_status` su un
    terminale (crash del thread, cancel riportato ad "analyzed", cleanup,
    riavvio senza recovery): senza, il job resterebbe "in corso" per sempre
    nell'area personale web e nell'app."""
    with _jobs_lock:
        job = jobs.get(job_id)
        st = job.get("status") if isinstance(job, dict) else None
        interrupted = bool(isinstance(job, dict) and job.get("server_interrupted"))
        cancelled = bool(isinstance(job, dict) and job.get("cancelled"))
    if job is not None:
        if st in _ACCT_SETTLE_MAP:
            return "error" if interrupted else _ACCT_SETTLE_MAP[st]
        # Cancel riportato ad "analyzed": il job non sta piu' generando.
        if st == "analyzed" and (cancelled or interrupted):
            return "error" if interrupted else "cancelled"
        return None
    if now - float(row_updated_at or 0) < _ACCT_STALE_RUNNING_SEC:
        return None
    try:
        if pending_jobs.is_active(job_id):
            return None
    except Exception:  # noqa: BLE001  store illeggibile: nel dubbio non chiudere
        return None
    return "error"


def _account_reconcile_running(rows, now):
    for r in rows:
        if r.get("status") != "running":
            continue
        try:
            st = _account_settled_status(r["job_id"], r.get("updated_at"), now)
            if st and accounts.settle_running(r["job_id"], st):
                print(f"[{r['job_id']}] storico account: running -> {st} (riconciliato)",
                      flush=True)
                r["status"] = st
        except Exception as e:  # noqa: BLE001
            print(f"WARNING [{r.get('job_id')}] riconciliazione storico: {e}", flush=True)


def _account_rows_for(acct, page):
    rows, total = accounts.list_jobs(acct["id"], page=page, per_page=_ACCT_PER_PAGE)
    _account_reconcile_running(rows, time.time())
    now = time.time()
    index = _download_tokens_index()
    out = []
    for r in rows:
        d = dict(r)
        d["downloads"] = _account_downloads_for(d, now, index)
        out.append(d)
    return out, total


def _account_voices_for(acct):
    """Voci campionate collegate, non terminali, con link alla gestione
    attuale (/vc/<manage_token>/devices). Best-effort: [] su qualunque errore."""
    try:
        out = []
        for vid in voice_clone.ids_for_email(acct["email"]):
            rec = voice_clone.store().get(vid)
            if rec is None or rec.get("state") in voice_clone._TERMINAL or not rec.get("manage_token"):
                continue
            out.append({"name": rec.get("name") or vid, "url": routes_voice_clone._vc_urls(rec)["manage_url"],
                        "state": rec.get("state") or ""})
        return out
    except Exception:  # noqa: BLE001
        return []


@app.route("/account", methods=["GET"])
def account_page_view():
    if not accounts.enabled() or not _smtp_available():
        abort(404)
    acct = _current_account()
    if not acct:
        return redirect("/?login=1", code=302)
    try:
        page = max(1, int(request.args.get("p") or 1))
    except ValueError:
        page = 1
    rows, total = _account_rows_for(acct, page)
    voices = _account_voices_for(acct)
    try:
        sessions = accounts.list_sessions(acct["id"])
    except Exception as e:  # noqa: BLE001
        print(f"WARNING list_sessions: {e}", flush=True)
        sessions = []
    for sd in sessions:
        # Sessioni aperte prima di questa versione hanno lo User-Agent grezzo.
        sd["device_name"] = voice_clone.device_name_from_ua(sd.get("device_name")) or sd.get("device_name") or ""
    tab = "voices" if request.args.get("tab") == "voices" else "books"
    lang = _acct_page_lang(acct.get("lang"))
    t = _acct_txt(lang)
    # Un ?lang= esplicito viaggia anche sui link di paginazione; il cookie
    # posato dalla SPA non ne ha bisogno.
    link_lang = lang if (request.args.get("lang") or "").strip().lower() == lang else ""
    # Il campionamento si offre solo se la funzione e' viva: con la feature
    # spenta o il motore premium assente il bottone porterebbe a un wizard
    # che non si apre.
    new_voice_url = "/?vc=new" if routes_voice_clone._vc_gate() is None else ""
    return _acct_html(account_page.render_history(
        t, lang=lang, account=acct, rows=rows, page=page, per_page=_ACCT_PER_PAGE,
        total=total, voices_count=len(voices), voices=voices,
        sessions=sessions, current_sid=acct.get("session_id") or "", tab=tab,
        link_lang=link_lang, new_voice_url=new_voice_url))


@app.route("/api/account/jobs", methods=["GET"])
def api_account_jobs():
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    try:
        page = max(1, int(request.args.get("p") or 1))
    except ValueError:
        page = 1
    rows, total = _account_rows_for(acct, page)
    # Ottimizzazione con audiolibro: per l'app e' un audiolibro ("generate",
    # importabile in libreria); `optimized` conserva il resto dell'informazione.
    jobs = [{
        "job_id": r["job_id"], "created_at": r.get("created_at"),
        "kind": "generate" if account_page.is_optimize_with_audio(r) else r.get("kind"),
        "optimized": r.get("kind") == "optimize",
        "book_title": r.get("book_title") or "", "output_format": r.get("output_format") or "",
        "status": r.get("status"), "paid_eur": float(r.get("paid_eur") or 0),
        "engine": r.get("engine") or "", "model": r.get("model") or "",
        "downloads": r["downloads"],
    } for r in rows]
    return jsonify({"jobs": jobs, "total": total, "page": page, "per_page": _ACCT_PER_PAGE})


@app.route("/api/account/jobs/delete", methods=["POST"])
def api_account_job_delete():
    """Elimina un job dall'area personale (web e app). Nasconde solo la riga
    di storico: file hot/cold e token restano, cosi' il link dell'email di
    notifica continua a funzionare fino alla scadenza."""
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    data = request.get_json(silent=True) or {}
    job_id = str(data.get("job_id") or "").strip()
    if not job_id:
        return _acct_err("bad_request", "job_id required", 400)
    res = accounts.hide_job(acct["id"], job_id)
    if res == "not_found":
        return _acct_err("not_found", "Job not found", 404)
    if res == "running":
        return _acct_err("job_running", "Job still in progress", 409)
    _acct_log("ACCOUNT_JOB_DELETE", acct["email"], job_id)
    return jsonify({"ok": True})


@app.route("/api/account/delete_request", methods=["POST"])
def api_account_delete_request():
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    ip = client_ip()
    allowed, retry = _ip_rl_check("auth_request", ip, 5, 30)
    if not allowed:
        return _acct_err("rate_limited", "Too many requests", 429, retry_after=retry)
    # L'email e' quella dell'account: il body viene ignorato (nessuna cancellazione per conto terzi).
    _acct_send_code(acct["email"], "delete", acct.get("lang") or "en")
    return jsonify({"ok": True})


@app.route("/api/account/delete_confirm", methods=["POST"])
def api_account_delete_confirm():
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    code = (data.get("code") or "").strip()
    if token:
        status, target = accounts.verify(token=token, purpose="delete")
    elif code:
        status, target = accounts.verify(email=acct["email"], code=code, purpose="delete")
    else:
        return _acct_err("bad_request", "token or code required", 400)
    if status != "ok" or not target or target["id"] != acct["id"]:
        return _acct_err(status if status != "ok" else "wrong", "Verification failed", 401)
    _acct_do_delete(acct, acct.get("lang") or "en")
    resp = jsonify({"ok": True})
    _acct_clear_cookie(resp)
    return resp


# E3: blocco spostato in routes_community.


# E3 (seam community pubblica, 2026-10-10): statistiche, news, feedback e
# supporto nel blueprint routes_community. Helper della app passati come
# lambda (risolti a ogni richiesta: i test li sostituiscono su questo modulo).
routes_community.configure(
    admin_email=lambda: ADMIN_EMAIL,
    _stats_today_count=lambda *a, **k: _stats_today_count(*a, **k),
    _stats_month_by_lang=lambda *a, **k: _stats_month_by_lang(*a, **k),
    _hash_ip=lambda *a, **k: _hash_ip(*a, **k),
    _ip_rl_check=lambda *a, **k: _ip_rl_check(*a, **k),
    client_ip=lambda *a, **k: client_ip(*a, **k))
app.register_blueprint(routes_community.bp)



# E3 (seam admin, parte 5, 2026-10-10): news, feedback, community e reset
# anti-abuso nel blueprint routes_admin_community (vedi routes_admin_audit).
routes_admin_community.configure(
    admin_required=admin_required, admin_token=lambda: ADMIN_TOKEN,
    admin_auth_ok=lambda provided: _admin_auth_ok(provided),
    admin_auth_from_request=lambda: _admin_auth_from_request(),
    render_admin_gate=lambda title, url: _render_admin_gate(title, url),
    sanitize_text=lambda *a, **k: routes_community._sanitize_text(*a, **k),
    news_langs=routes_community._NEWS_LANGS, news_tags=routes_community._NEWS_TAGS, abuse_group_re=_ABUSE_GROUP_RE)
app.register_blueprint(routes_admin_community.bp)



def _file_hash(path):
    """Return MD5 hex digest of a file, streaming in chunks."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _safe_upload_name(original_name, ext):
    """Nome sicuro per il salvataggio dell'upload, con l'estensione GARANTITA.

    secure_filename() su nomi interamente non-ASCII (es. '姑妄言.pdf') non
    restituisce stringa vuota ma la sola estensione senza punto ('pdf'): il
    vecchio fallback non scattava e il file finiva su disco come '<jobdir>/pdf'.
    Da lì, ogni descrittore di recovery nasceva con input_path troncato e
    _parse_book, che smista per suffisso, cadeva sul parser sbagliato.
    """
    from werkzeug.utils import secure_filename
    ext = (ext or "").lower().lstrip(".")
    safe = secure_filename(original_name or "")
    root, dot, suffix = safe.rpartition(".")
    if not dot:
        root, suffix = safe, ""
    if suffix.lower() != ext and root.lower() == ext:
        # secure_filename ha eroso tutto lo stem lasciando la sola estensione
        root = ""
    if not root:
        root = uuid.uuid4().hex[:8]
    return f"{root}.{ext}" if ext else root


def _derive_language_source(language, language_detected):
    """Provenienza della lingua del libro, per il client.

    `metadata` = scritta nel file (dc:language dell'EPUB, metadati del PDF).
    `detected` = dedotta dall'IA leggendo il testo.
    `unknown`  = nessuna delle due: il client ripieghera' sul locale
                 dell'interfaccia e marchera' la lingua come ipotizzata,
                 il che fa scattare l'avviso prima della generazione.
    """
    if not (language or "").strip():
        return "unknown"
    return "detected" if language_detected else "metadata"


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    # Rate-limit IP-based: previene spam upload / DoS.
    _allowed, _retry = _ip_rl_check(
        "analyze", client_ip(), _ANALYZE_RL_PER_MIN, _ANALYZE_RL_PER_HOUR
    )
    if not _allowed:
        return jsonify({"error": "rate_limit", "retry_after": _retry}), 429
    # Sospensione nuovi processi (admin toggle): blocca gia` al caricamento, non
    # solo a generate/optimize, cosi` l'utente non spreca upload + analisi per
    # poi trovarsi bloccato all'ultimo step. Guardia prima di salvare il file.
    if _suspend_new_jobs:
        return jsonify({"error": "System under maintenance. Please try again in a few minutes."}), 503
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
    ext = fname_lower.rsplit(".", 1)[-1]
    safe_name = _safe_upload_name(file.filename, ext)

    job_id = _new_job_id()
    work_dir = UPLOAD_DIR / job_id
    work_dir.mkdir(exist_ok=True)
    file_path = work_dir / safe_name
    file.save(str(file_path))

    # Magic-bytes validation: blocca file con estensione mentita (es. .exe rinominato .epub).
    # I parser a valle gia` rifiuterebbero, ma fail-fast evita storage waste + log inutili.
    try:
        with open(str(file_path), "rb") as _f:
            _head = _f.read(8)
    except Exception:
        _head = b""
    if (is_epub or is_abm) and not _head.startswith(b"PK"):
        try: file_path.unlink()
        except Exception: pass
        try: work_dir.rmdir()
        except Exception: pass
        return jsonify({"error": "Invalid file: not a valid ZIP-based archive"}), 400
    if is_pdf and not _head.startswith(b"%PDF-"):
        try: file_path.unlink()
        except Exception: pass
        try: work_dir.rmdir()
        except Exception: pass
        return jsonify({"error": "Invalid file: not a valid PDF"}), 400
    if is_txt:
        # TXT non ha magic; rifiuta solo se contiene byte chiaramente binari nel head
        # (NUL byte). Accetta UTF-8 BOM (\xef\xbb\xbf), UTF-16 BOM, ecc.
        if b"\x00" in _head and not (_head.startswith(b"\xff\xfe") or _head.startswith(b"\xfe\xff")):
            try: file_path.unlink()
            except Exception: pass
            try: work_dir.rmdir()
            except Exception: pass
            return jsonify({"error": "Invalid file: not a valid text file"}), 400

    client_id = _get_client_id()
    file_hash = _file_hash(str(file_path))

    # Duplicate upload detection: if this client already has an active job for the same file,
    # block if running; reuse if only analyzed/optimized.
    existing_jid = None
    existing_job = None
    with _jobs_lock:
        for jid, job in jobs.items():
            if job.get("client_id") == client_id and job.get("file_hash") == file_hash:
                existing_jid = jid
                existing_job = job
                break

    if existing_job:
        status = existing_job.get("status", "")
        if status in ("optimizing", "generating"):
            _info_run = existing_job.get("info")
            return jsonify({
                "existing_job_id": existing_jid,
                "status": status,
                "is_running": True,
                "progress_current": existing_job.get("progress_current", 0),
                "progress_total": existing_job.get("progress_total", 0),
                "opt_progress_current": existing_job.get("opt_progress_current", 0),
                "opt_progress_total": existing_job.get("opt_progress_total", 0),
                # Parametri del job in corso: il client si riaggancia allo
                # stream, ma il pannello finale lo costruisce con le proprie
                # variabili. Senza questi campi mostrava i bottoni del formato
                # di default (M4B) anche per un job che produce uno ZIP.
                "title": (getattr(_info_run, "title", "") or
                          existing_job.get("original_filename", "")),
                "output_format": existing_job.get("output_format", ""),
                "single_file": bool(existing_job.get(
                    "single_file", existing_job.get("opt_single_file", True))),
                "total_chapters": int(
                    existing_job.get("total_chapters")
                    or len(getattr(_info_run, "chapters", None) or [])),
                "email_registered": bool(existing_job.get("notify_email")),
            })
        if status in ("analyzed", "optimized"):
            # Reuse existing analyzed/optimized job
            info = existing_job["info"]
            _lang_re = (getattr(info, "language", None) or "it")[:2].lower()
            chapters = []
            _total_secs_re = 0.0
            for ch in info.chapters:
                _secs = _estimate_chapter_seconds(ch, _lang_re)
                _total_secs_re += _secs
                chapters.append({
                    "index": ch.index, "title": ch.title,
                    "words": ch.word_count, "chars": ch.char_count,
                    "estimated_minutes": round(_secs / 60.0, 1),
                })
            return jsonify({
                "job_id": existing_jid, "title": info.title, "author": info.author,
                "language": info.language,
                "language_detected": existing_job.get("language_detected", False),
                "language_source": existing_job.get("language_source", "unknown"),
                "file_type": "abm" if is_abm else ("txt" if is_txt else ("pdf" if is_pdf else "epub")),
                "has_cover": bool(existing_job.get("cover_thumb")),
                "total_chapters": len(info.chapters), "total_words": info.total_words,
                "total_chars": info.total_chars,
                "estimated_minutes": round(_total_secs_re / 60.0, 1),
                "chapters": chapters,
                "preview_text": existing_job.get("preview_text", ""),
                "llm_available": _llm_available(),
                "ai_optimized": existing_job.get("ai_optimized", False),
                "optimized_chapters": existing_job.get("optimized_chapters", []),
            })

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
        # PDF di sole immagini (scansione, foto convertite): non e' un guasto ma
        # un limite spiegabile. Codice stabile -> il frontend lo traduce nella
        # lingua dell'utente (err_pdf_no_text), invece di sbattergli in faccia il
        # messaggio grezzo dell'eccezione.
        if "pdf_no_text" in str(e):
            return jsonify({"error": "pdf_no_text"}), 400
        return jsonify({"error": f"{label} parse error: {e}"}), 400

    if not info.chapters:
        return jsonify({"error": "No content found."}), 400

    # Lingua assente nei metadati (txt sempre; pdf/epub/abm a volte):
    # rilevamento via LLM (stesso client dell'ottimizzazione AI) su 3
    # paragrafi consecutivi da meta' libro. Fallimento silenzioso: la
    # lingua resta vuota e l'analisi completa comunque (spec 2026-06-06).
    language_detected = False
    if not (getattr(info, "language", "") or "").strip() and _llm_available():
        _detected = generation_engine.detect_book_language(info)
        if _detected:
            info.language = _detected
            language_detected = True

    # NOTE: the ABM_MAX_TEXT_CHARS cap is no longer enforced here. We show the
    # book regardless of its total size so the user can browse chapters and
    # narrow the selection. The actual cap is applied at /api/generate and
    # /api/optimize on the *selected* chapters, where it matters for output
    # size and LLM cost.

    with _jobs_lock:
        jobs[job_id] = {"status": "analyzed", "epub_path": str(file_path), "info": info,
                         "last_poll": time.time(), "original_filename": file.filename,
                         "client_id": _get_client_id(), "client_ip": client_ip(),
                         "browser_lang": _get_browser_lang(),
                         "optimized_chapters": [], "file_hash": file_hash,
                         "language_detected": language_detected,
                         "language_source": _derive_language_source(
                             info.language, language_detected)}

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

    _lang_new = (getattr(info, "language", None) or "it")[:2].lower()
    chapters = []
    _total_secs_new = 0.0
    for ch in info.chapters:
        _secs = _estimate_chapter_seconds(ch, _lang_new)
        _total_secs_new += _secs
        chapters.append({
            "index": ch.index, "title": ch.title,
            "words": ch.word_count, "chars": ch.char_count,
            "estimated_minutes": round(_secs / 60.0, 1),
        })
    # Override total estimated minutes for response consistency with per-chapter values.
    _total_minutes_new = round(_total_secs_new / 60.0, 1)

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
        """Tronca tra min e max caratteri a fine frase, oppure all'ultimo spazio.

        Normalizza prima di troncare, non dopo: `prepare_tts_text` ragiona per
        riga, e questo testo esce di qui su una riga sola. Appiattirlo prima
        significherebbe spegnere la pausa dopo il titolo — e l'anteprima voce
        e` proprio il posto dove l'utente quella pausa la deve sentire.
        Le parentesi qui restano: i flag di lettura li sceglie l'utente dopo,
        e li applica l'endpoint dell'anteprima.
        """
        text = prepare_tts_text(text, strip_round=False, strip_square=False)
        if len(text) <= max_chars:
            return text
        window = text[min_chars:max_chars]
        m = re.search(r'[.!?]["""»\)\s]', window)
        cut = (min_chars + m.start() + 1) if m else text.rfind(' ', min_chars, max_chars)
        if cut <= 0:
            cut = max_chars
        return text[:cut].rstrip()

    # Solo TXT puro usa la logica "primo capitolo con >=150 char": PDF e ABM
    # hanno capitoli strutturati e beneficiano del filtro front-matter + scelta
    # del secondo capitolo valido (narrativa, non introduzione).
    raw_preview = _pick_preview_text(info.chapters, is_txt)
    preview_text = _trim_preview(raw_preview) if raw_preview else ""
    # Store for /api/preview_audio
    jobs[job_id]["preview_text"] = preview_text
    # ----------------------------------------------------------------------

    # Detect if .abm was already AI-optimized
    abm_ai_optimized = False
    abm_manifest = None
    if is_abm:
        try:
            import zipfile
            with zipfile.ZipFile(str(file_path), "r") as zf:
                m = json.loads(zf.read("manifest.json").decode("utf-8"))
                abm_ai_optimized = m.get("ai_optimized", False)
                abm_manifest = m
        except Exception:
            pass
    if abm_ai_optimized:
        jobs[job_id]["ai_optimized"] = True
        if abm_manifest:
            jobs[job_id]["optimized_chapters"] = [c["index"] for c in abm_manifest.get("chapters", [])]

    return jsonify({
        "job_id": job_id, "title": info.title, "author": info.author,
        "language": info.language,
        "language_detected": language_detected,
        "language_source": _derive_language_source(info.language, language_detected),
        "file_type": "abm" if is_abm else ("txt" if is_txt else ("pdf" if is_pdf else "epub")),
        "has_cover": has_cover,
        "total_chapters": len(info.chapters), "total_words": info.total_words,
        "total_chars": info.total_chars,
        "estimated_minutes": _total_minutes_new,
        "chapters": chapters,
        "preview_text": preview_text,
        "llm_available": _llm_available(),
        "ai_optimized": abm_ai_optimized,
        "optimized_chapters": jobs[job_id].get("optimized_chapters", []),
        "max_text_chars": MAX_TEXT_CHARS,
        "max_gemini_text_chars": MAX_GEMINI_TEXT_CHARS,
    })


@app.route("/api/preview_audio/<job_id>")
def api_preview_audio(job_id):
    """Serve l'MP3 di anteprima come endpoint GET.
    Il browser può usare l'URL direttamente come audio.src  -  nessun problema di autoplay policy.
    Il timeout è gestito da concurrent.futures (funziona sempre, a differenza di asyncio.wait_for).
    """
    if not job_id:
        return jsonify({"error": "Job non trovato"}), 404
    voice = request.args.get("voice", "it-IT-IsabellaNeural")
    if _is_voxcpm_voice(voice):
        # §5.2: per VoxCPM l'anteprima e' sostituita dall'ascolto del campione
        # (/api/voice_sample). Un'anteprima costerebbe l'accensione di un
        # worker — circa tre minuti e il prezzo di un capitolo — per pochi
        # secondi di audio. Il rifiuto esplicito serve anche a non far cadere
        # la voce nel ramo Edge, che la leggerebbe con un'altra voce. Il
        # controllo precede la verifica del job apposta: la sola voce VoxCPM
        # basta a rifiutare, anche se il job non esiste ancora.
        return jsonify({"error": "voxcpm_preview_unsupported"}), 400
    _job, _err, _sc = _check_job_owner(job_id)
    if _err is not None:
        return _err, _sc

    # Rate-limit IP-based: anteprime sono costose (genera TTS sample),
    # impedisce abuso e burst di generazione voci diverse.
    _allowed, _retry = _ip_rl_check(
        "preview", client_ip(), _PREVIEW_RL_PER_MIN, _PREVIEW_RL_PER_HOUR
    )
    if not _allowed:
        return jsonify({"error": "rate_limit", "retry_after": _retry}), 429

    _gate = _premium_model_gate(voice)
    if _gate is not None:
        return _gate
    rate  = request.args.get("rate",  "+0%")
    style = (request.args.get("style") or "").strip()[:200]
    accent = (request.args.get("accent") or "").strip()[:8]
    speechify_emotion = (request.args.get("speechify_emotion") or "").strip().lower()
    if speechify_emotion and speechify_emotion not in speechify_tts.EMOTIONS:
        speechify_emotion = ""  # valore ignoto -> neutro
    # Lettura opzionale del testo tra parentesi (default: rimosso). L'anteprima
    # applica lo stesso preprocessing della generazione finale, cosi` l'utente
    # sente esattamente cosa verra` letto.
    read_round_parens = request.args.get("read_round_parens") in ("1", "true", "True")
    read_square_brackets = request.args.get("read_square_brackets") in ("1", "true", "True")

    # Se il client passa selected_chapters, l'anteprima deve essere un estratto
    # dei capitoli selezionati (coerente con il pannello "Voci PREMIUM"). Altrimenti
    # usa il preview_text fallback memorizzato all'upload.
    try:
        sel_raw = request.args.getlist("selected_chapters")
        sel_idxs = [int(x) for x in sel_raw if str(x).strip()]
    except (TypeError, ValueError):
        sel_idxs = []
    preview_text = ""
    if sel_idxs:
        _job_pv = jobs[job_id]
        info_pv = _job_pv.get("info")
        all_chs_pv = list(getattr(info_pv, "chapters", []) or []) if info_pv else []
        by_idx_pv = {ch.index: ch for ch in all_chs_pv}
        sel_chs = [by_idx_pv[i] for i in sel_idxs if i in by_idx_pv]
        # Job gia' terminale: i testi sono spillati su disco (contenimento RAM).
        # Li rileggiamo in un mapping temporaneo invece di reidratare il job.
        _pv_spill = (generation_engine.chapter_texts(job_id, _job_pv)
                     if _job_pv.get("_texts_spilled") else {})
        def _pv_text(c):
            return (_pv_spill.get(c.index) if _pv_spill else None) or c.text or ""
        if sel_chs:
            try:
                from epub_to_tts import is_content_chapter as _icc_pv
                valid = [c for c in sel_chs
                         if _icc_pv(_pv_text(c), c.title or "")
                         and (c.word_count or 0) >= 80]
            except Exception:
                valid = [c for c in sel_chs if (c.word_count or 0) >= 80]
            if not valid:
                valid = [c for c in sel_chs if _pv_text(c).strip()]
            if valid:
                target = valid[1] if len(valid) > 1 else valid[0]
                # Prepara qui, sul testo con i suoi a-capo: il troncamento a
                # 600 char lavora poi su cio` che il motore leggera` davvero.
                raw = prepare_tts_text(
                    _pv_text(target),
                    strip_round=not read_round_parens,
                    strip_square=not read_square_brackets,
                )
                # Tronca tra 400 e 600 char a fine frase (riallinea a _trim_preview).
                if len(raw) > 600:
                    _win = raw[400:600]
                    _m = re.search(r'[.!?]["”“»\)\s]', _win)
                    _cut = (400 + _m.start() + 1) if _m else raw.rfind(" ", 400, 600)
                    if _cut <= 0:
                        _cut = 600
                    preview_text = raw[:_cut].rstrip()
                else:
                    preview_text = raw
    if not preview_text:
        preview_text = jobs[job_id].get("preview_text", "")
    if not preview_text:
        return jsonify({"error": "Nessun testo di anteprima disponibile"}), 400

    # Applica la stessa preparazione testo della generazione finale (stesso
    # ordine di `_plan_chunks`): stripping parentesi secondo i flag scelti
    # dall'utente (default: rimuove tonde e quadre), normalizzazione del
    # maiuscolo, pausa dopo gli heading, appiattimento. Senza parita' l'utente
    # sceglierebbe la voce su una clip che suona diversa dall'audiolibro.
    _prepared = prepare_tts_text(
        preview_text,
        strip_round=not read_round_parens,
        strip_square=not read_square_brackets,
    )
    preview_text = _prepared or preview_text

    # Per Gemini e Speechify riduciamo il testo a ~20-30 sec di audio (250-400
    # char) per contenere il costo per-token/per-carattere fatturato.
    if _is_gemini_voice(voice) or _is_speechify_voice(voice):
        _t = re.sub(r'\s+', ' ', preview_text).strip()
        if len(_t) > 400:
            _window = _t[250:400]
            _m = re.search(r'[.!?]["”“»\)\s]', _window)
            _cut = (250 + _m.start() + 1) if _m else _t.rfind(' ', 250, 400)
            if _cut <= 0:
                _cut = 400
            preview_text = _t[:_cut].rstrip()
        else:
            preview_text = _t

    work_dir = UPLOAD_DIR / job_id
    work_dir.mkdir(exist_ok=True)
    # Cache per (voice, rate, style, selezione): il nome del file è derivato da un
    # hash della chiave, così tornare a una combinazione già generata serve il
    # file cached invece di rigenerare (e per Gemini non consuma il preview cap).
    # La selezione capitoli entra nella chiave perché il testo varia con essa.
    sel_key = ",".join(str(i) for i in sorted(sel_idxs)) if sel_idxs else ""
    paren_key = f"{int(read_round_parens)}{int(read_square_brackets)}"
    cache_key = f"{voice}|{rate}|{style}|{accent}|{sel_key}|{paren_key}|{speechify_emotion}"
    key_hash = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()[:16]
    preview_path = work_dir / f"preview_{key_hash}.mp3"

    if preview_path.exists() and preview_path.stat().st_size > 0:
        return send_file(str(preview_path), mimetype="audio/mpeg",
                         as_attachment=False, download_name="preview.mp3",
                         conditional=True)

    # Genera l'MP3 in un thread separato con timeout reale di 30 secondi.
    # concurrent.futures.Future.result(timeout=) interrompe l'attesa indipendentemente
    # da asyncio  -  risolve il caso in cui edge-tts si blocca sulla connessione TCP.
    use_gemini_preview = gemini_tts is not None and _is_gemini_voice(voice)
    use_speechify_preview = _is_speechify_voice(voice) and speechify_tts.is_available()
    client_id = "anon"

    # Direttiva di accento per la preview (solo Gemini): deve allinearsi al job
    # finale, dove l'accento ancora tutti i chunk. Lingua per priorita`: query
    # `lang` -> opt_lang/gen_lang del job -> info.language (stessa logica del
    # sample empirico post-synth piu` sotto).
    accent_directive_pre = None
    if use_gemini_preview:
        _jp_acc = jobs.get(job_id) or {}
        _jinfo_acc = _jp_acc.get("info")
        _preview_lang_pre = (
            _i18n.norm_lang(request.args.get("lang"))
            or _i18n.norm_lang(_jp_acc.get("opt_lang"))
            or _i18n.norm_lang(_jp_acc.get("gen_lang"))
            or _i18n.norm_lang((getattr(_jinfo_acc, "language", None) or "it"))
        )[:2]
        try:
            accent_directive_pre = gemini_tts.build_accent_directive(
                _preview_lang_pre, accent) or None
        except Exception as _e_acc_pv:
            print(f"[preview] accent directive build failed (non-fatal): {_e_acc_pv}")
            accent_directive_pre = None

    # Preview cap per Gemini (rolling 24h per cookie)
    if use_gemini_preview:
        if not gemini_tts.is_available():
            return jsonify({"error": "gemini_tts_not_configured"}), 503
        # Preflight ffmpeg: il PCM nativo Gemini va convertito in MP3. Senza
        # ffmpeg falliremmo DOPO aver consumato token e cap preview (incidente
        # locale 2026-06-06: 500 "File MP3 non generato" a valle del synth).
        if not _preview_ffmpeg_ok():
            return jsonify({
                "error": ("Anteprima voci PREMIUM non disponibile: ffmpeg "
                          "non installato sul server."),
                "code": "ffmpeg_missing",
            }), 503
        client_id = _get_client_id() or "anon"
        used, remaining, reset_ts = gemini_tts.check_preview_cap(client_id)
        if remaining <= 0:
            reset_in = max(0, int(reset_ts - time.time()))
            return jsonify({
                "error": "preview_cap_exceeded",
                "used": used,
                "cap": gemini_tts.PREVIEW_CAP_PER_DAY,
                "reset_in_seconds": reset_in,
            }), 429
        # Preflight RPD: se il modello non ha quota per anche solo 1 chunk,
        # falliamo immediatamente con 503 invece di lasciare la call al
        # synthesize() che andrebbe in errore dopo aver consumato tempo.
        # Senza questo check, su flash31 con RPD esaurito l'utente vedeva
        # solo lo spinner per ~30s prima di un 504 generico.
        try:
            parts = voice.split(":")
            _model_key_pf = parts[1] if len(parts) >= 3 else "flash31"
            _pf = gemini_tts.preflight_can_run(_model_key_pf, 1)
            if not _pf.get("ok"):
                return jsonify({
                    "error": ("Il modello voci PREMIUM ha esaurito la quota "
                              "giornaliera. Riprova piu` tardi o seleziona "
                              "un modello differente."),
                    "code": "quota_exhausted",
                    "model_key": _model_key_pf,
                    "retry_after_sec": int(_pf.get("retry_after_sec") or 0),
                    "available": _pf.get("available"),
                }), 503
        except Exception as _pf_err:
            # Preflight non-fatal: log e prosegui. Meglio rischiare un 504
            # downstream che bloccare un preview legittimo.
            print(f"[preview] preflight check error (non-fatal): {_pf_err}")

    # Speechify: nessun preview cap ne' RPD (a differenza di Gemini). Serve
    # solo il preflight ffmpeg, perche' il PCM nativo va convertito in MP3.
    if use_speechify_preview:
        if not _preview_ffmpeg_ok():
            return jsonify({
                "error": ("Anteprima voci PREMIUM non disponibile: ffmpeg "
                          "non installato sul server."),
                "code": "ffmpeg_missing",
            }), 503

    def _generate():
        if use_gemini_preview:
            # Native output is PCM — convert to MP3 inline for browser playback.
            pcm_tmp = str(preview_path) + ".pcm"
            try:
                # max_attempts=1: il path preview ha timeout client 30s. Se
                # Gemini restituisce EMPTY-RESPONSE con finish_reason=OTHER
                # (modello fermato per ragioni non specificate, tipico su
                # combo voce/rate/lingua poco stabili come flash31), i 3
                # retry default + backoff saturano il timeout → 504 lato
                # browser. Falliamo veloce: il caller (preview_audio)
                # converte l'errore in 502 con messaggio utile e l'utente
                # puo` ritentare manualmente o cambiare voce/modello.
                result = gemini_tts.synthesize(preview_text, voice, output_path=pcm_tmp,
                                                style_instruction=style or None,
                                                rate=rate,
                                                accent_directive=accent_directive_pre,
                                                max_attempts=1)
                pcm_to_mp3([pcm_tmp], str(preview_path))
                # Costo Google REALE della preview (token reali x rate per MTok).
                _preview_cost_eur = 0.0
                try:
                    _bd = gemini_tts.actual_cost_breakdown(
                        result.get("input_tokens", 0),
                        result.get("output_tokens", 0),
                        result.get("model_key", "flash31"),
                        result.get("backend"),
                    )
                    _preview_cost_eur = float(_bd.get("total_eur", 0.0) or 0.0)
                except Exception as e:
                    print(f"[preview] actual_cost_breakdown failed (non-fatal): {e}")
                try:
                    gemini_tts.record_usage(
                        result.get("model_key", "flash31"),
                        len(preview_text),
                        result.get("input_tokens", 0),
                        result.get("output_tokens", 0),
                        _preview_cost_eur,
                        0.0,
                    )
                except Exception as e:
                    print(f"[preview] gemini_tts.record_usage failed (non-fatal): {e}")
                # Sample rate empirico: lingua TTS scelta (NON metadata libro).
                # Priorita`: query `lang` -> job.opt_lang/gen_lang -> info.language.
                # Senza questo, una preview con voce italiana su EPUB arabo
                # registrava sample "ar" inquinando l'empirical rate per "it".
                try:
                    _job_pv = jobs[job_id]
                    _job_info = _job_pv.get("info")
                    _q_lang = _i18n.norm_lang(request.args.get("lang"))
                    _preview_lang = (
                        _q_lang
                        or _i18n.norm_lang(_job_pv.get("opt_lang"))
                        or _i18n.norm_lang(_job_pv.get("gen_lang"))
                        or _i18n.norm_lang((getattr(_job_info, "language", None) or "it"))
                    )[:2]
                    _norm_chars = len(gemini_tts._normalize_text(preview_text))
                    gemini_tts.record_rate_sample(
                        _norm_chars,
                        result.get("audio_seconds_real", 0.0),
                        _preview_lang,
                        result.get("model_key", "flash31"),
                        rate_pct=rate,
                        voice=(voice or "").split(":")[-1],
                        job_id=job_id,
                    )
                except Exception as e:
                    print(f"[preview] gemini_tts.record_rate_sample failed (non-fatal): {e}")
                gemini_tts.increment_preview(client_id)
            finally:
                if os.path.exists(pcm_tmp):
                    try:
                        os.remove(pcm_tmp)
                    except OSError:
                        pass
        elif use_speechify_preview:
            pcm_tmp = str(preview_path) + ".pcm"
            try:
                res = speechify_tts.synthesize(
                    preview_text, voice, pcm_tmp,
                    emotion=(speechify_emotion or None), rate=rate, max_attempts=1)
                _sr = int(res.get("sample_rate", 48000) or 48000)
                # PCM raw -> MP3 con il sample rate REALE (Speechify = 48kHz
                # nativo, a differenza del default 24kHz di pcm_to_mp3 usato
                # per Gemini).
                pcm_to_mp3([pcm_tmp], str(preview_path), sample_rate=_sr, channels=1)
            except Exception as _e_spx:
                print(f"[preview] speechify failed, silence fallback: {_e_spx}")
                _generate_silence_mp3(str(preview_path), duration_sec=1)
            finally:
                if os.path.exists(pcm_tmp):
                    try:
                        os.remove(pcm_tmp)
                    except OSError:
                        pass
        else:
            import edge_tts
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

    # Wrapper timeout per modello dal catalogo (gemini_tts.preview_timeout_sec):
    # deve superare il timeout HTTP del modello, altrimenti strozza anteprime
    # che il provider sta completando (504 spuri). Il client aspetta +5 s.
    _wrapper_timeout = 30
    if use_gemini_preview:
        try:
            _mk = voice.split(":")[1] if _is_gemini_voice(voice) else ""
            if _mk in gemini_tts.GEMINI_MODELS:
                _wrapper_timeout = gemini_tts.preview_timeout_sec(_mk)
        except Exception:
            pass
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            ex.submit(_generate).result(timeout=_wrapper_timeout)
    except concurrent.futures.TimeoutError:
        return jsonify({"error": f"Timeout: il servizio TTS non ha risposto in {_wrapper_timeout} secondi."}), 504
    except Exception as e:
        # EMPTY-RESPONSE: Gemini ha risposto senza audio (finish_reason=OTHER
        # o simili). Tipicamente combo voce/rate/lingua poco stabile su un
        # modello specifico (es. flash31). Restituiamo 502 con messaggio
        # actionable invece di 500 generico.
        if gemini_tts is not None and isinstance(e, getattr(gemini_tts, "GeminiEmptyResponse", ())):
            _fr = getattr(e, "finish_reason", None) or "unknown"
            return jsonify({
                "error": (f"Il modello TTS non ha prodotto audio (motivo: {_fr}). "
                          f"Riprova, oppure cambia voce o modello (la stessa voce su "
                          f"un modello diverso spesso funziona)."),
                "code": "empty_response",
                "finish_reason": _fr,
            }), 502
        # Quota giornaliera RPD raggiunta server-wide per il modello. Diverso
        # dal preview_cap per-client (429): qui e` un limite Gemini globale.
        # Restituiamo 503 con code dedicato per messaggio actionable.
        if gemini_tts is not None and isinstance(e, getattr(gemini_tts, "GeminiQuotaExhausted", ())):
            _ra = getattr(e, "retry_after_sec", None)
            return jsonify({
                "error": ("Il modello voci PREMIUM ha raggiunto il limite "
                          "giornaliero. Riprova piu` tardi o seleziona un "
                          "modello differente."),
                "code": "quota_exhausted",
                "retry_after_sec": _ra,
            }), 503
        # Budget EUR daily/per-job superato (raro in preview, ma possibile se
        # il budget e` molto stretto). Stesso treatment di quota_exhausted ma
        # con code distinto per logging lato server.
        if gemini_tts is not None and isinstance(e, getattr(gemini_tts, "GeminiBudgetExceeded", ())):
            return jsonify({
                "error": ("Le voci PREMIUM hanno raggiunto il budget "
                          "giornaliero. Riprova piu` tardi o seleziona "
                          "una voce Standard."),
                "code": "budget_exceeded",
            }), 503
        # HTTP timeout: il client genai non ha ricevuto risposta entro il
        # timeout configurato (ABM_GEMINI_HTTP_TIMEOUT_MS, default 25s).
        # Distinguiamo dal ThreadPoolExecutor timeout (504) perche` qui
        # abbiamo info sulla causa (API lenta/irraggiungibile).
        _ctx = getattr(e, "__context__", None)
        _is_http_timeout = False
        try:
            import httpx
            _is_http_timeout = isinstance(e, httpx.TimeoutException) or isinstance(_ctx, httpx.TimeoutException)
        except ImportError:
            pass
        if _is_http_timeout:
            return jsonify({
                "error": ("Il servizio voci PREMIUM non risponde. Riprova "
                          "tra qualche secondo o seleziona un modello/voce "
                          "differente."),
                "code": "http_timeout",
            }), 504
        return jsonify({"error": f"Errore generazione anteprima: {e}"}), 500

    if not preview_path.exists():
        return jsonify({"error": "File MP3 non generato."}), 500

    return send_file(str(preview_path), mimetype="audio/mpeg",
                     as_attachment=False, download_name="preview.mp3",
                     conditional=True)

@app.route("/api/cover/<job_id>")
def api_cover(job_id):
    """Serve the extracted cover thumbnail for preview."""
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return "", sc if sc == 404 else 403
    cover_path = job.get("cover_thumb")
    if not cover_path or not os.path.exists(cover_path):
        return "", 404
    mime = job.get("cover_mime", "image/jpeg")
    return send_file(cover_path, mimetype=mime)


@app.route("/api/export_abm/<job_id>")
def api_export_abm(job_id):
    """Export cleaned text as .abm project file (ZIP with manifest + chapters + cover)."""
    _job, _err, _sc = _check_job_owner(job_id)
    if _err is not None:
        return _err, _sc
    with _jobs_lock:
        if job_id not in jobs:
            return jsonify({"error": "Job not found"}), 404
        job = jobs[job_id]
        info = job.get("info")
        if not info or not info.chapters:
            return jsonify({"error": "No book data available"}), 400
        # Snapshot data needed outside lock
        _job_data = {
            "optimized_chapters": job.get("optimized_chapters"),
            "selected_chapters": job.get("selected_chapters"),
            "cover_thumb": job.get("cover_thumb"),
            "original_filename": job.get("original_filename", ""),
        }
        _spilled = bool(job.get("_texts_spilled"))

    # Testi capitolo: dalla RAM, o dallo spill su disco se il job e' gia'
    # terminale (contenimento RAM). Mapping temporaneo, non reidrata il job.
    _texts = generation_engine.chapter_texts(job_id, job) if _spilled else None
    if _spilled and not any((t or "").strip() for t in _texts.values()):
        return jsonify({"error": "Book text is no longer available"}), 410

    import zipfile
    import io

    buf = io.BytesIO()
    safe_title = _safe_filename(info.title) or "project"

    # Align with _generate_optimized_abm: prefer cumulative optimized_chapters,
    # fall back to current selected_chapters, else include all.
    optimized = _job_data["optimized_chapters"]
    selected = _job_data["selected_chapters"]
    if optimized:
        chapter_set = set(optimized)
    elif selected:
        chapter_set = set(selected)
    else:
        chapter_set = None

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Build chapter files and manifest entries
        chapters_manifest = []
        for ch in info.chapters:
            if chapter_set and ch.index not in chapter_set:
                continue
            ch_safe = _safe_filename(ch.title)[:50] or f"ch_{ch.index}"
            ch_filename = f"{ch.index:03d}_{ch_safe}.txt"
            ch_text = _texts.get(ch.index, "") if _texts else ""
            zf.writestr(f"chapters/{ch_filename}", ch_text or ch.text)
            chapters_manifest.append({
                "index": ch.index,
                "filename": ch_filename,
                "title": ch.title,
                "word_count": ch.word_count,
            })

        # Cover
        has_cover = False
        cover_file = ""
        cover_path = _job_data["cover_thumb"]
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
            "original_filename": _job_data["original_filename"],
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

    return _apply_no_cache(send_file(buf, mimetype="application/zip", as_attachment=True,
                                      download_name=download_name))


def _voice_language_hint(voice_id):
    """Lingua della voce dedotta dal suo id, `""` se non si puo' dedurre.

    Vale per le voci il cui id nasce da un locale (`it-IT-...`,
    `en-US-Chirp3-HD-...`): per Gemini, Speechify e le voci campionate l'id non
    porta la lingua, e allora decide il selector del client. Non si tira a
    indovinare: senza lingua il controllo semplicemente non parte.
    """
    head = (voice_id or "").split("-")[0].strip().lower()
    if len(head) == 2 and head.isalpha():
        return head
    return ""


def _language_mismatch_hit(job, job_id, voice, lang, selected_chapters):
    """Esito del controllo lingua libro/voce, memorizzato sul job.

    La domanda costa una chiamata al giudice, e il wizard la pone prima del
    pagamento mentre le route la ripetono come rete di sicurezza: senza memo
    lo stesso libro la pagherebbe due o tre volte. La chiave e' la lingua
    della voce, perche' cambiarla e' l'unico motivo per ridomandare.
    """
    voice_lang = (lang or "") or _voice_language_hint(voice or "")
    key = _i18n.norm_lang(voice_lang)
    memo = job.get("_lang_check") or {}
    if key and key in memo:
        return memo[key]
    info = job.get("info")
    texts = []
    try:
        chapters = list(getattr(info, "chapters", None) or [])
        if selected_chapters:
            sel = set(selected_chapters)
            chapters = [c for c in chapters if c.index in sel] or chapters
        texts = [(c.text or "") for c in chapters]
    except Exception:      # noqa: BLE001 - mai fatale per il job
        texts = []
    declared = ""
    try:
        declared = getattr(info, "language", "") or ""
    except Exception:      # noqa: BLE001
        declared = ""
    hit = voice_language_guard.check(texts, voice_lang, declared,
                                     job_id=job_id, voice=voice or "")
    if key:
        memo[key] = hit
        job["_lang_check"] = memo
    return hit


def _language_mismatch_response(job, job_id, voice, lang, selected_chapters,
                                data):
    """La risposta 409 da restituire, o `None` se si puo' procedere.

    Non e' un divieto: `confirm_language` nel body vale «l'utente ha visto
    l'avviso e vuole procedere», ed e' l'unico modo di leggere comunque un
    libro bilingue. Chi chiama dopo un claim di stato lo rilascia da se'.
    """
    if bool((data or {}).get("confirm_language")):
        return None
    hit = _language_mismatch_hit(job, job_id, voice, lang, selected_chapters)
    if hit is None:
        return None
    _log_activity(job_id, job.get("original_filename", ""), "LANG_MISMATCH",
                  job.get("client_id", ""), job.get("client_ip", ""))
    return jsonify({
        "error": "The book does not look like it is written in the language "
                 "of the selected voice.",
        "error_code": "language_mismatch",
        "voice_language": hit["voice_language"],
        "book_language": hit["book_language"],
    }), 409


@app.route("/api/check_language", methods=["POST"])
def api_check_language():
    """Il controllo lingua chiesto dal client PRIMA di aprire il pagamento.

    Le guardie dentro /api/generate e /api/optimize restano, ma nel percorso
    del wizard il pagamento e' gia' catturato quando la richiesta parte: un
    409 lascerebbe la scelta fra proseguire e una cattura orfana. Qui la
    domanda arriva mentre non c'e' ancora niente da rimborsare.

    Non fallisce mai in modo visibile: qualunque inciampo vale
    `{"mismatch": false}`, cioe' il wizard procede come prima di questo
    controllo.
    """
    try:
        data = request.json or {}
        job, err, sc = _check_job_owner(data.get("job_id"))
        if err is not None:
            return jsonify({"mismatch": False})
        hit = _language_mismatch_hit(
            job, data.get("job_id"), data.get("voice") or "",
            data.get("lang"), _parse_selected_chapters(
                data.get("selected_chapters")))
        if hit is None:
            return jsonify({"mismatch": False})
        return jsonify({
            "mismatch": True,
            "voice_language": hit["voice_language"],
            "book_language": hit["book_language"],
        })
    except Exception as e:      # noqa: BLE001 - mai fatale per il wizard
        print(f"[voicelang] /api/check_language: {type(e).__name__}: {e}",
              flush=True)
        return jsonify({"mismatch": False})


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.json
    job_id = data.get("job_id")
    voice = data.get("voice", "it-IT-IsabellaNeural")
    if not _VOICE_ID_RE.match(voice or ""):
        return jsonify({"error": "Invalid voice id.",
                        "error_code": "invalid_voice"}), 400
    rate = data.get("rate", "+0%")
    single_file = data.get("single_file", True)
    output_format = data.get("output_format", "m4b")
    podcast_base_url = (data.get("podcast_base_url") or "").strip()
    selected_chapters = data.get("selected_chapters")  # list of chapter indices, or None
    # Lettura opzionale del testo tra parentesi (default: rimosso).
    read_round_parens = bool(data.get("read_round_parens", False))
    read_square_brackets = bool(data.get("read_square_brackets", False))

    # Modello PREMIUM spento via ABM_<MODELLO>_ENABLE=false. Valutato prima
    # dei check di configurazione: e' la ragione piu' specifica del rifiuto.
    _gate = _premium_model_gate(voice)
    if _gate is not None:
        return _gate
    # Refuse Gemini voices when the module is missing or the API key is not configured.
    if _is_gemini_voice(voice):
        if gemini_tts is None or not gemini_tts.is_available():
            return jsonify({"error": "gemini_tts_not_configured"}), 400
    if _is_speechify_voice(voice):
        if not speechify_tts.is_available():
            return jsonify({"error": "speechify_not_configured"}), 400
    if _is_voxcpm_voice(voice):
        if voxcpm_tts is None or not voxcpm_tts.is_available():
            return jsonify({"error": "voxcpm_not_configured"}), 400
    # Voce campione (spec §9 riga 479): cid autorizzato, voce ancora `ready`,
    # lingua/accento del libro compatibili. Il locale e' quello mandato dal
    # chiamante per QUESTO libro (non quello della voce: confrontare la voce
    # con se stessa sarebbe tautologico) - '' se assente, il confronto resta
    # allora solo sulla lingua.
    if voice.startswith(voice_clone.VOICE_ID_PREFIX):
        _vc_lang = _i18n.norm_lang(data.get("lang"))
        _vc_locale = (data.get("locale") or "").strip()
        _vc_err_code = voice_clone.check_use(voice, _get_client_id(), _vc_lang, _vc_locale)
        if _vc_err_code:
            _vc_status = {"voice_gone": 410, "voice_not_authorized": 403,
                          "voice_lang_mismatch": 400}.get(_vc_err_code, 400)
            return jsonify({"error": f"Voice sample not usable: {_vc_err_code}",
                            "error_code": _vc_err_code}), _vc_status

    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        if sc == 404:
            return jsonify({"error": "Session expired. Re-upload file."}), 400
        return err, sc

    # Store format and podcast URL for email/download handlers
    job["output_format"] = output_format
    # Snapshot dei parametri di generazione sul job: servono al recupero batch
    # (ricostruzione del descrittore in _build_job_descriptor) dopo un restart.
    # DEVE avvenire PRIMA di qualunque pending_jobs.register(): la promozione di
    # voice/selected_chapters avviene solo poco prima di thread.start(), quindi
    # il descrittore del ramo auto-batch a pagamento (registrato subito dopo la
    # capture) nasceva con voice="" -> al riavvio la guardia anti-audio-muto
    # dichiarava il job irrecuperabile e lo rimborsava a generazione quasi
    # completata (incidente tUV3YzoYMcde_euhIU6QCg, 89%).
    job["voice"] = voice
    job["rate"] = rate
    job["single_file"] = single_file
    job["selected_chapters"] = selected_chapters
    job["read_round_parens"] = read_round_parens
    job["read_square_brackets"] = read_square_brackets
    if podcast_base_url:
        job["podcast_base_url"] = podcast_base_url
    if output_format == "zip_rss":
        job["notify_download_type"] = "podcast"
        job["notify_base_url"] = podcast_base_url

    # Maintenance suspend check BEFORE payment preflight so we never consume
    # a payment token when the system can't accept the job anyway.
    if _suspend_new_jobs:
        return jsonify({"error": "System under maintenance. Please try again in a few minutes."}), 503

    # Tetto globale d'istanza valutato PRIMA del preflight di pagamento: se il
    # server e' saturo l'utente viene avvisato subito ("server sovraccarico"),
    # senza che gli venga chiesto alcun pagamento. La verifica dentro il blocco
    # atomico piu' sotto resta come guardia sulla race.
    _busy = _server_busy_response(
        job_id, "/api/generate",
        premium=generation_engine.is_premium_job(jobs.get(job_id) or {}))
    if _busy is not None:
        return _busy

    # Lingua del testo contro lingua della voce, PRIMA del preflight di
    # pagamento: il reclamo classico ("il libro spagnolo letto con voce
    # italiana") nasce da un <dc:language> sbagliato, frequentissimo sulle
    # traduzioni, e oggi nessuno lo verifica — detect_book_language interviene
    # solo quando il metadato manca del tutto. Non e' un divieto: l'utente
    # conferma e si procede (stesso pattern di `quota_ack`), perche' un libro
    # bilingue deve restare generabile.
    _vl = _language_mismatch_response(job, job_id, voice, data.get("lang"),
                                      selected_chapters, data)
    if _vl is not None:
        return _vl

    # ----- F3: Gemini payment preflight -----
    # Lo stash di quota vale SOLO per la richiesta corrente: azzeralo qui, in
    # testa al preflight premium e per qualunque voce. Fra i gate premium e la
    # pop che consuma (poco prima di thread.start()) restano uscite sincrone
    # (429 concurrent_limit, 400 no chapters, 413 selection_too_large):
    # senza questo reset un residuo sopravvivrebbe sul job
    # in memoria e la richiesta successiva sullo stesso job_id consumerebbe
    # quota anche con voce standard (nessun gate premium) o dopo un pagamento
    # regolare (il ramo `else` non scrive lo stash e ereditava il vecchio).
    job.pop("_free_quota_charge", None)
    payment_token = (data.get("payment_token") or "").strip()
    style_instruction = (data.get("gemini_style_instruction") or "")[:200]
    accent_variant = (data.get("gemini_accent") or "").strip()[:8]
    speechify_emotion = (data.get("speechify_emotion") or "").strip().lower()
    if speechify_emotion and speechify_emotion not in speechify_tts.EMOTIONS:
        speechify_emotion = ""  # valore ignoto -> neutro
    # Stessa ragione dello snapshot sopra: questi parametri finiscono nel
    # descrittore batch e vanno stashati prima della register post-capture.
    if style_instruction:
        job["gemini_style_instruction"] = style_instruction
    if accent_variant:
        job["gemini_accent"] = accent_variant
    if speechify_emotion:
        job["speechify_emotion"] = speechify_emotion
    if _is_gemini_voice(voice):
        # Recompute server-side total (mirror api_combined_estimate)
        info_pre = job.get("info")
        all_chs_pre = list(getattr(info_pre, "chapters", []) or [])
        sel = selected_chapters or []
        if sel:
            _by_index_pre = {ch.index: ch for ch in all_chs_pre}
            chs_pre = [_by_index_pre[i] for i in sel if i in _by_index_pre]
        else:
            chs_pre = all_chs_pre
        # Job gia' terminale: i testi sono spillati su disco e `ch.text` e' ""
        # in RAM. Senza questa rilettura la stima sotto vale ~0 e la voce
        # PREMIUM parte gratis (vedi _pricing_chapters).
        chs_pre = _pricing_chapters(job_id, job, chs_pre)
        # Cap caratteri PRIMA di qualsiasi prenotazione budget o consumo del
        # pagamento. Per le voci PREMIUM il cap (MAX_GEMINI_TEXT_CHARS) e` piu`
        # restrittivo: verificarlo qui garantisce che un libro troppo grande non
        # porti MAI a riservare budget o consumare il token PayPal/voucher per
        # poi essere rifiutato dal cap a valle (riga ~6448) senza rimborso.
        _max_chars_pre = _effective_max_text_chars(voice, job)
        _sel_chars_pre = sum(getattr(ch, "char_count", 0) for ch in chs_pre)
        if _sel_chars_pre > _max_chars_pre:
            return jsonify({
                "error": f"Selection too large: {_sel_chars_pre:,} characters "
                         f"(limit {_max_chars_pre:,}). Please reduce the chapter selection.",
                "error_code": "selection_too_large",
                "chars_selected": _sel_chars_pre,
                "chars_limit": _max_chars_pre,
            }), 413
        # Lingua: priorita` (1) override UI da body request > (2) metadata libro
        # > (3) "it". Stessa logica usata da /api/combined_estimate e
        # /api/paypal_create_order_gemini: indispensabile per evitare amount
        # mismatch fra preflight pagamento e stima frontend (file TXT senza
        # metadata e EPUB/PDF con dc:language errato producono altrimenti
        # stime divergenti -> total_eur_pre sotto soglia -> payment_token
        # ignorato -> job["payment"] mai impostato -> audit charged=0).
        _ui_lang_pre = _i18n.norm_lang(data.get("lang"))
        lang_pre = (_ui_lang_pre
                    or _i18n.norm_lang(getattr(info_pre, "language", ""))
                    or "it")
        # Persisti la lingua TTS effettivamente scelta dall'utente. Serve
        # all'audit Gemini (`_audit_language`) per non registrare la lingua
        # metadata del libro quando la voce TTS opera su una lingua diversa
        # (es. libro arabo con voce italiana -> audit deve mostrare "it").
        # Coesiste con `opt_lang` (settato da /api/optimize) come fallback.
        if _ui_lang_pre:
            job["gen_lang"] = _ui_lang_pre
        try:
            # Il rate scelto influisce sulla stima (estimate_audio_seconds scala
            # con rate_pct): il ricalcolo server-side deve usarlo per allinearsi
            # alla stima vista dall'utente e validare correttamente il pagamento.
            est_pre = tts_engines.estimate("gemini", chs_pre, voice, language=lang_pre, rate_pct=rate)
            gemini_eur_pre = round(est_pre["user_price_eur"], 2)
            # Persisti la stima sul job: serve all'audit Gemini per popolare
            # i campi *_est (input_tokens_est, output_tokens_est, audio_seconds_est,
            # google_cost_eur_est) altrimenti sempre 0 nel JSONL.
            job["gemini_estimate"] = est_pre
        except Exception as e:
            return jsonify({"error": f"estimate failed: {e}"}), 500
        # Fail-closed: se i capitoli dichiarano caratteri ma la stima ne ha
        # quotati zero, il prezzo e` finto e la voce PREMIUM partirebbe gratis.
        if not _assert_priced_on_real_text(job_id, chs_pre,
                                           est_pre.get("chars_total", 0)):
            return jsonify({"error": "Cost estimate unavailable, please retry.",
                            "error_code": "estimate_failed"}), 500
        llm_eur_pre = 0.0
        if data.get("ai_opt_enabled"):
            chars_pre = sum(len(getattr(c, "text", "") or "") for c in chs_pre)
            # Quota LLM combinata (nessun floor): fonte unica payment.llm_price_eur,
            # coerente con /api/combined_estimate e /api/paypal_create_order_gemini.
            llm_eur_pre = payment.llm_price_eur(chars_pre, is_combined=True)["due_eur"]
        total_eur_pre = round(gemini_eur_pre + llm_eur_pre, 2)

        # ----- Pre-flight budget guard (Google cost server-side) -----
        # Indipendente dal pagamento utente: questo è il cap interno sui costi
        # Google effettivi (per-job + daily). Se sforato, blocchiamo il job
        # PRIMA di chiamare l'API, così non spendiamo nulla.
        try:
            _google_cost_pre = float(est_pre.get("google_cost_eur", 0.0) or 0.0)
            # La riserva si fa sul caso PEGGIORE fra i backend abilitati dalla
            # config corrente, non sul listino: se il modello gira su
            # Cloudflare e il circuit breaker devia a meta' job su Vertex, il
            # costo reale puo' superare il listino misto (D1 tiene il listino
            # fisso, il costo reale no) e una riserva sul listino sforerebbe il
            # cap in silenzio. Il prezzo mostrato/addebitato all'utente resta
            # `gemini_eur_pre` (listino) sopra: qui cambia solo quanto si mette
            # da parte. Fallback sul listino se il calcolo peggiore fallisce
            # (degradazione graduale, coerente con il resto del blocco).
            try:
                _worst = gemini_tts.worst_case_cost_breakdown(
                    est_pre.get("input_tokens_est", 0),
                    est_pre.get("output_tokens_est", 0),
                    est_pre.get("model_key"))
                _reserve_pre = float(_worst.get("total_eur", _google_cost_pre) or _google_cost_pre)
            except Exception as _worst_err:
                print(f"[{job_id}] worst_case_cost_breakdown failed, falling "
                      f"back to listino for the reservation: {_worst_err}")
                _reserve_pre = _google_cost_pre
            preflight = gemini_tts.preflight_budget_check(_reserve_pre)
            if preflight.get("warning"):
                print(f"[{job_id}] Budget warning (preflight): {preflight['warning']}")
            # Atomic reservation: blocca race fra job concorrenti che vedrebbero
            # lo stesso `spent` (audit JSONL viene scritto solo a fine job).
            gemini_tts.reserve_budget(job_id, _reserve_pre)
        except gemini_tts.GeminiBudgetExceeded as _bex:
            return jsonify({
                "error": "budget_exceeded",
                "scope": getattr(_bex, "scope", "unknown"),
                "message": str(_bex),
                "estimated_eur": getattr(_bex, "estimated_eur", _google_cost_pre),
                "cap_eur": getattr(_bex, "cap_eur", None),
                "used_eur": getattr(_bex, "used_eur", None),
            }), 429
        except Exception as _bgenerr:
            # Errore non-budget: log e prosegui (graceful degradation).
            print(f"[{job_id}] preflight_budget_check raised non-budget error: "
                  f"{_bgenerr}")

        # ----- Pre-flight RPD check SINCRONO (prima di consumare il payment) -----
        # Eseguito qui per evitare la race condition fra il thread async di
        # run_generation (che setta status=error + marker) e lo stream SSE in
        # /api/progress (che a volte chiude il loop al primo tick prima che il
        # marker sia visibile). Bloccando qui rispondiamo a /api/generate
        # direttamente con error_code=gemini_overload e il frontend mostra il
        # popup senza fare affidamento sul polling SSE.
        try:
            _info_chs_for_plan = chs_pre
            _info_lang_for_plan = lang_pre
            _max_chars_pf = _pick_chunk_max_chars(voice, _info_lang_for_plan)
            _max_bytes_pf = _pick_chunk_max_bytes(voice)
            class _PlanInfo:
                pass
            _plan_info = _PlanInfo()
            _plan_info.chapters = _info_chs_for_plan
            _plan_for_pf = _plan_chunks(_plan_info, max_chars=_max_chars_pf, max_bytes=_max_bytes_pf,
                                        strip_round=not read_round_parens,
                                        strip_square=not read_square_brackets)
            _total_chunks_pf = len(_plan_for_pf)
            _parts_v_pf = (voice or "").split(":")
            _model_key_pf = _parts_v_pf[1] if len(_parts_v_pf) >= 3 else "flash31"
            _pf_sync = gemini_tts.preflight_can_run(_model_key_pf, _total_chunks_pf)
            # Log RPD status (richiesta utente) — sempre, anche se OK.
            _cap_v_pf = _pf_sync.get("cap", 0)
            if _cap_v_pf and _cap_v_pf > 0:
                print(f"[{job_id}] RPD status [{_model_key_pf}]: "
                      f"used={_pf_sync.get('used', 0)}/{_cap_v_pf}, "
                      f"reserve={_pf_sync.get('reserve', 0)}, "
                      f"available={_pf_sync.get('available', 0)}, "
                      f"needed={_pf_sync.get('needed', 0)} "
                      f"-> {'OK' if _pf_sync.get('ok') else 'BLOCK (shortfall=' + str(_pf_sync.get('shortfall', 0)) + ')'}")
            else:
                print(f"[{job_id}] RPD status [{_model_key_pf}]: no local cap "
                      f"(ABM_GEMINI_RPD_{_model_key_pf.upper()}=0), needed={_pf_sync.get('needed', 0)}")
        except Exception as _pf_sync_err:
            print(f"[{job_id}] Sync preflight check error (non-fatal, proceeding): {_pf_sync_err}")
            _pf_sync = {"ok": True}
        if not _pf_sync.get("ok"):
            _reason_sync = (f"preflight_block_sync: model={_model_key_pf} "
                            f"needed={_pf_sync.get('needed')} "
                            f"available={_pf_sync.get('available')} "
                            f"shortfall={_pf_sync.get('shortfall')} "
                            f"cap={_pf_sync.get('cap')} used={_pf_sync.get('used')} "
                            f"reserve={_pf_sync.get('reserve')}")
            print(f"[{job_id}] PREFLIGHT BLOCK (sync) -> {_reason_sync}")
            # Nessun payment consumato a questo punto: niente refund da emettere.
            # Admin alert (informativo) per parita' con il blocco async.
            try:
                _admin_alert_text = (
                    f"[ABM-ADMIN] Gemini TTS — BLOCCO PREVENTIVO RPD (sync)\n\n"
                    f"job_id={job_id} model={_model_key_pf}\n"
                    f"needed={_pf_sync.get('needed')} "
                    f"available={_pf_sync.get('available')} "
                    f"shortfall={_pf_sync.get('shortfall')}\n"
                    f"cap={_pf_sync.get('cap')} used={_pf_sync.get('used')} "
                    f"reserve={_pf_sync.get('reserve')}\n"
                    f"Nessun payment consumato (blocco prima del consume).\n"
                )
                _admin_email = os.environ.get("ABM_ADMIN_EMAIL", "")
                if _admin_email:
                    email_service.send_email(_admin_email,
                                             "[ABM-ADMIN] Preflight RPD block (sync)",
                                             _admin_alert_text)
            except Exception as _ae:
                print(f"[{job_id}] Admin alert (sync) failed: {_ae}")
            try: gemini_tts.release_reservation(job_id)
            except Exception: pass
            return jsonify({
                "error": "Generation not started: PREMIUM voices are temporarily overloaded.",
                "error_code": "gemini_overload",
                "retry_after_sec": int(_pf_sync.get("retry_after_sec") or 0),
                "model_key": _model_key_pf,
                "refund_method": "",
            }), 429

        # Quota gratuita cumulativa: si decide sul LISTINO (il prezzo pre-
        # azzeramento), altrimenti un job sotto soglia risulterebbe sempre a
        # costo zero e la quota non verrebbe mai intaccata.
        _list_total_pre = round(
            float(est_pre.get("list_price_eur", 0.0) or 0.0) + llm_eur_pre, 2
        )
        _fq_key_pre = _free_quota_key(job_id, voice, chs_pre, all_chs_pre)
        _quota_dec = _premium_quota_decision(
            _quota_client_id(job), voice, _list_total_pre, _fq_key_pre,
            book_chars=_free_quota_book_chars(info_pre, all_chs_pre),
            language=lang_pre,
        )
        total_eur_pre = _quota_dec["due_eur"]
        threshold_pre = _quota_dec["threshold_eur"]
        # Price lock (D1): stesso principio del flusso combinato in
        # /api/optimize. Qui passa il percorso "voce PREMIUM senza
        # ottimizzazione AI": paga -> conferma -> /api/generate ricalcola.
        if not _quota_dec["is_free"] and payment_token:
            _sig_pre = _pricing_signature(
                voice, [getattr(ch, "index", None) for ch in chs_pre],
                rate, lang_pre, bool(data.get("ai_opt_enabled")))
            _locked_pre = _price_lock_lookup(job, payment_token, _sig_pre)
            _lock_src_pre = "al create dell'ordine"
            if _locked_pre is None:
                # Nessun ordine PayPal creato per questo token — e' il caso del
                # pagamento con buono: vale comunque la quotazione mostrata
                # all'utente (quote lock D2), non il ricalcolo di adesso.
                _locked_pre = _quote_lock_lookup(job, _sig_pre)
                _lock_src_pre = "alla stima mostrata"
            if _locked_pre is not None and abs(_locked_pre - total_eur_pre) > 0.005:
                print(f"[{job_id}] price lock: dovuto {total_eur_pre:.2f}EUR -> "
                      f"{_locked_pre:.2f}EUR (quotato {_lock_src_pre}, "
                      f"token {payment_token[:12]}...)", flush=True)
                total_eur_pre = _locked_pre
            elif _locked_pre is None:
                # Un ordine esiste per questo token ma la firma degli input di
                # prezzo e' cambiata fra create e conferma: il lock non vale e il
                # ricalcolo vivo puo' produrre "paypal amount mismatch". Traccia
                # QUALE input e' cambiato (la firma e' leggibile: voce|capitoli|
                # rate|lingua|ai): senza questa riga l'incidente 1rDPmro8ROjYKcGLo8Outw
                # non era diagnosticabile dal log.
                _lk = (job.get("price_locks") or {}).get(payment_token)
                if isinstance(_lk, dict) and _lk.get("sig") != _sig_pre:
                    print(f"[{job_id}] price lock NON applicabile: input di prezzo "
                          f"cambiati fra ordine e conferma — ordine '{_lk.get('sig')}' "
                          f"vs conferma '{_sig_pre}'; ricalcolo vivo "
                          f"{total_eur_pre:.2f}EUR (ordine {float(_lk.get('total_eur') or 0):.2f}EUR)",
                          flush=True)
        _free_quota_log(job_id, _quota_dec)
        if _quota_dec["is_free"]:
            # Consumo differito al claim atomico dello stato (vedi sotto): un
            # job respinto dal limite di concorrenza non deve bruciare quota.
            # (importo, chiave di addebito per generazione)
            job["_free_quota_charge"] = (_list_total_pre, _fq_key_pre)
        else:
            if not payment_token:
                try: gemini_tts.release_reservation(job_id)
                except Exception: pass
                if _quota_dec["quota_exhausted"]:
                    try:
                        _log_activity(job_id, job.get("original_filename", ""),
                                      "FREE_QUOTA_EXCEEDED",
                                      client_id=job.get("client_id", ""),
                                      client_ip=job.get("client_ip", ""),
                                      voice=_voice_for_log(voice))
                    except Exception:
                        pass
                return jsonify({
                    "error": "payment_required",
                    "error_code": ("free_quota_exhausted"
                                   if _quota_dec["quota_exhausted"] else "payment_required"),
                    "total_eur": total_eur_pre,
                    "threshold_eur": threshold_pre,
                    "quota_used_eur": _quota_dec["quota_used_eur"],
                    "quota_limit_eur": _quota_dec["quota_limit_eur"],
                    "free_cap_exceeded": bool(_quota_dec.get("free_cap_exceeded")),
                }), 402
            try:
                _pay_method = payment.consume_payment_token(
                    payment_token, total_eur_pre, job_id, purpose="gemini"
                )
            except ValueError as _pay_err:
                try: gemini_tts.release_reservation(job_id)
                except Exception: pass
                return jsonify({"error": f"payment_invalid: {_pay_err}"}), 400
            # Stash payment info on job for refund + audit
            # total_eur_pre e' il pagato intero (TTS + LLM): in job["payment"]
            # va la sola quota TTS, come assumono i writer di audit e i
            # rimborsi, che sommano payment["llm_eur"] a parte.
            job["payment"] = {
                "token": payment_token,
                "total_eur": generation_engine._tts_share_eur(
                    total_eur_pre, llm_eur_pre),
                "method": _pay_method,
                "ts": time.time(),
                "gemini_est": est_pre,
                "llm_eur": llm_eur_pre,
            }
            _acq_src, _acq_plat = _acquisition_from_request()
            job["payment"]["acquisition_source"] = _acq_src
            job["payment"]["acquisition_platform"] = _acq_plat
            if _acq_src == "app":
                try:
                    metrics_store.incr("payment_from_app", _acq_plat)
                except Exception:
                    pass
            # Batch implicito per job PAGATO (vedi _register_paid_job_batch).
            _register_paid_job_batch(
                job_id, job, payment_token, engine="Gemini",
                lang=(data.get("lang") or "en"), output_format=output_format,
                podcast_base_url=podcast_base_url)
        # Stash style for run_generation
        if style_instruction:
            job["gemini_style_instruction"] = style_instruction
        # Stash accent variant (e.g. 'gb', '419'); run_generation lo risolve in
        # direttiva. Se assente, la direttiva usa il default lingua del catalogo.
        if accent_variant:
            job["gemini_accent"] = accent_variant

    # ----- F3bis: Speechify payment preflight -----
    # Specchio LEAN del ramo Gemini sopra: stesso pocket di pagamento
    # (job["payment"]), stesso gate soglia/consumo token, stesso audit di
    # acquisizione + batch email registration. NIENTE budget Google/RPD:
    # Speechify non ha prenotazione budget ne' preflight RPD, quindi non va
    # chiamato alcun gemini_tts.* qui (ne' reserve_budget ne'
    # release_reservation: nulla e' stato prenotato in questo ramo).
    # VoxCPM entra qui e non in un terzo ramo: il percorso e' identico —
    # stessa tasca job["payment"], stesso gate soglia/consumo token, nessun
    # budget Google e nessun preflight RPD da rilasciare. Duplicare le
    # novanta righe una terza volta darebbe tre copie da tenere allineate su
    # un percorso di pagamento.
    if _is_speechify_voice(voice) or _is_voxcpm_voice(voice):
        # TODO(refactor): estrarre un helper _consume_premium_payment condiviso col ramo gemini (duplicazione ~90 righe).
        _is_vox = _is_voxcpm_voice(voice)
        info_pre = job.get("info")
        all_chs_pre = list(getattr(info_pre, "chapters", []) or [])
        sel = selected_chapters or []
        if sel:
            _by_index_pre = {ch.index: ch for ch in all_chs_pre}
            chs_pre = [_by_index_pre[i] for i in sel if i in _by_index_pre]
        else:
            chs_pre = all_chs_pre
        # Vedi nota nel ramo Gemini: su job spillato `ch.text` e' vuoto in RAM.
        chs_pre = _pricing_chapters(job_id, job, chs_pre)
        # Cap caratteri PRIMA di consumare il pagamento (stessa motivazione del
        # ramo Gemini sopra: evita di trattenere denaro per un job che verra'
        # comunque rifiutato dal cap a valle).
        _max_chars_pre = _effective_max_text_chars(voice, job)
        _sel_chars_pre = sum(getattr(ch, "char_count", 0) for ch in chs_pre)
        if _sel_chars_pre > _max_chars_pre:
            return jsonify({
                "error": f"Selection too large: {_sel_chars_pre:,} characters "
                         f"(limit {_max_chars_pre:,}). Please reduce the chapter selection.",
                "error_code": "selection_too_large",
                "chars_selected": _sel_chars_pre,
                "chars_limit": _max_chars_pre,
            }), 413
        if _is_vox:
            # VoxCPM legge libri in piu' lingue (non solo inglese come
            # Speechify): stessa priorita' UI > metadata > "it" usata da
            # /api/combined_estimate, altrimenti la stima qui e quella vista
            # dal client divergerebbero.
            _ui_lang_pre = _i18n.norm_lang(data.get("lang"))
            lang_pre = (_ui_lang_pre
                        or _i18n.norm_lang(getattr(info_pre, "language", ""))
                        or "it")
            job["gen_lang"] = lang_pre
            try:
                est_pre = tts_engines.estimate("voxcpm", chs_pre, language=lang_pre)
                # Persisti la stima sul job: serve all'eventuale audit VoxCPM
                # (Task 11) per popolare i campi *_est.
                job["voxcpm_estimate"] = est_pre
            except Exception as e:
                return jsonify({"error": f"estimate failed: {e}"}), 500
        else:
            # Speechify e' solo inglese: nessuna selezione lingua come nel ramo
            # Gemini. Persisti comunque gen_lang="en" per coerenza con l'audit e
            # con /api/combined_estimate.
            job["gen_lang"] = "en"
            try:
                est_pre = tts_engines.estimate("speechify", chs_pre, language="en")
                # Persisti la stima sul job: serve all'eventuale audit Speechify
                # per popolare i campi *_est.
                job["speechify_estimate"] = est_pre
            except Exception as e:
                return jsonify({"error": f"estimate failed: {e}"}), 500
        # Fail-closed: vedi nota nel ramo Gemini.
        if not _assert_priced_on_real_text(job_id, chs_pre,
                                           est_pre.get("chars_total", 0)):
            return jsonify({"error": "Cost estimate unavailable, please retry.",
                            "error_code": "estimate_failed"}), 500
        speechify_eur_pre = round(est_pre["user_price_eur"], 2)
        llm_eur_pre = 0.0
        if data.get("ai_opt_enabled"):
            chars_pre = sum(len(getattr(c, "text", "") or "") for c in chs_pre)
            # Quota LLM combinata (nessun floor): fonte unica payment.llm_price_eur.
            llm_eur_pre = payment.llm_price_eur(chars_pre, is_combined=True)["due_eur"]
        total_eur_pre = round(speechify_eur_pre + llm_eur_pre, 2)

        # Quota gratuita cumulativa (stessa logica del ramo Gemini sopra).
        _list_total_pre = round(
            float(est_pre.get("list_price_eur", 0.0) or 0.0) + llm_eur_pre, 2
        )
        _fq_key_pre = _free_quota_key(job_id, voice, chs_pre, all_chs_pre)
        _quota_dec = _premium_quota_decision(
            _quota_client_id(job), voice, _list_total_pre, _fq_key_pre,
            book_chars=_free_quota_book_chars(info_pre, all_chs_pre),
            language=job.get("gen_lang"),
        )
        total_eur_pre = _quota_dec["due_eur"]
        threshold_pre = _quota_dec["threshold_eur"]
        _free_quota_log(job_id, _quota_dec)
        if _quota_dec["is_free"]:
            job["_free_quota_charge"] = (_list_total_pre, _fq_key_pre)
        else:
            if not payment_token:
                if _quota_dec["quota_exhausted"]:
                    try:
                        _log_activity(job_id, job.get("original_filename", ""),
                                      "FREE_QUOTA_EXCEEDED",
                                      client_id=job.get("client_id", ""),
                                      client_ip=job.get("client_ip", ""),
                                      voice=_voice_for_log(voice))
                    except Exception:
                        pass
                return jsonify({
                    "error": "payment_required",
                    "error_code": ("free_quota_exhausted"
                                   if _quota_dec["quota_exhausted"] else "payment_required"),
                    "total_eur": total_eur_pre,
                    "threshold_eur": threshold_pre,
                    "quota_used_eur": _quota_dec["quota_used_eur"],
                    "quota_limit_eur": _quota_dec["quota_limit_eur"],
                    "free_cap_exceeded": bool(_quota_dec.get("free_cap_exceeded")),
                }), 402
            try:
                _pay_method = payment.consume_payment_token(
                    payment_token, total_eur_pre, job_id,
                    purpose=("voxcpm" if _is_vox else "speechify")
                )
            except ValueError as _pay_err:
                return jsonify({"error": f"payment_invalid: {_pay_err}"}), 400
            # Stash payment info on job for refund + audit. Stesso pocket
            # (job["payment"]) usato dal ramo Gemini: i path di refund
            # a valle (_refund_payment_on_orphan, _refund_gemini_payment) sono
            # pocket-based, non purpose-based, quindi funzionano identici.
            job["payment"] = {
                "token": payment_token,
                "total_eur": generation_engine._tts_share_eur(
                    total_eur_pre, llm_eur_pre),
                "method": _pay_method,
                "ts": time.time(),
                "llm_eur": llm_eur_pre,
            }
            if _is_vox:
                job["payment"]["voxcpm_est"] = est_pre
            else:
                job["payment"]["speechify_est"] = est_pre
            _acq_src, _acq_plat = _acquisition_from_request()
            job["payment"]["acquisition_source"] = _acq_src
            job["payment"]["acquisition_platform"] = _acq_plat
            if _acq_src == "app":
                try:
                    metrics_store.incr("payment_from_app", _acq_plat)
                except Exception:
                    pass
            # Batch implicito per job PAGATO (stessa logica del ramo Gemini):
            # un job pagato non deve morire per heartbeat alla chiusura del
            # browser.
            _register_paid_job_batch(
                job_id, job, payment_token,
                engine=("VoxCPM" if _is_vox else "Speechify"),
                lang=(data.get("lang") or "en"), output_format=output_format,
                podcast_base_url=podcast_base_url)
        # Stash emotion for run_generation (outer indent: vale per speechify,
        # non annidato nel ramo gemini).
        if speechify_emotion:
            job["speechify_emotion"] = speechify_emotion

    #  -  -  Atomic concurrency check + status claim  -  -
    client_id = job.get("client_id", "")
    client_ip = job.get("client_ip", "")
    # `job["voice"]` viene scritto solo al claim (sotto), quindi la voce
    # richiesta va valutata qui a parte: is_premium_job() da sola vedrebbe
    # ancora il job senza voce e classificherebbe free una richiesta Gemini.
    _premium_req = (_is_gemini_voice(voice) or _is_speechify_voice(voice)
                    or _is_voxcpm_voice(voice)
                    or generation_engine.is_premium_job(job))
    # Moderazione anti-abuso: cid nello scope di un verdetto `abuse` valido
    # (abuse_watch). Mai su job premium/pagati. Il messaggio non spiega il
    # perche': spiegare le feature insegnerebbe al bot come aggirarle.
    _abuse_group = _abuse_group_of(job)
    if not _premium_req:
        try:
            _abuse_blocked = abuse_watch.is_blocked(_abuse_group, client_id)
        except Exception:
            _abuse_blocked = False
        if _abuse_blocked:
            try:
                abuse_watch.record_block(_abuse_group, client_id)
            except Exception:
                pass
            _log_activity(job_id, job.get("original_filename", ""), "QUOTA_ABUSE_BLOCK",
                          client_id, client_ip, _voice_for_log(voice),
                          browser_lang=job.get("browser_lang", ""))
            print(f"[{job_id}] abuse_watch: job rifiutato (gruppo {_abuse_group})", flush=True)
            return jsonify({"error": "Processing interrupted.",
                            "error_code": "job_terminated"}), 403
    with _jobs_lock:
        if job["status"] not in ("analyzed", "optimized"):
            _refund_payment_on_orphan(job_id, job, "status_conflict")
            try: gemini_tts.release_reservation(job_id)
            except Exception: pass
            return jsonify({"error": "Generation already running or completed."}), 400
        # Il tetto per-client vale solo per la corsia gratuita: chi paga (voce
        # premium o pagamento incassato) non viene ne' limitato ne' conteggiato.
        if client_id and MAX_CONCURRENT_PER_CLIENT > 0 and not _premium_req:
            if _active_generating_for_client_unlocked(client_id, job_id) >= MAX_CONCURRENT_PER_CLIENT:
                _refund_payment_on_orphan(job_id, job, "concurrent_limit")
                try: gemini_tts.release_reservation(job_id)
                except Exception: pass
                return jsonify({
                    "error": f"Concurrent generation limit reached ({MAX_CONCURRENT_PER_CLIENT}).",
                    "error_code": "concurrent_limit",
                    "max": MAX_CONCURRENT_PER_CLIENT,
                    "active": _active_generating_for_client_unlocked(client_id, job_id),
                }), 429
        # Tetto globale d'istanza: protegge RAM/CPU dal carico aggregato di
        # client diversi (incidente 2026-08-21). Va valutato DOPO il cap
        # per-client, così l'abuso di un singolo device resta attribuito a lui.
        if MAX_CONCURRENT_GLOBAL > 0:
            _active_total = _active_generating_total_unlocked()
            if _active_total >= MAX_CONCURRENT_GLOBAL:
                load_metrics.incr(
                    "rej_busy_p" if generation_engine.is_premium_job(job) else "rej_busy")
                _refund_payment_on_orphan(job_id, job, "server_busy")
                try: gemini_tts.release_reservation(job_id)
                except Exception: pass
                print(f"[{job_id}] /api/generate rifiutata: tetto globale "
                      f"raggiunto ({_active_total}/{MAX_CONCURRENT_GLOBAL})")
                return jsonify({
                    "error": "The server is at capacity right now. "
                             "Please try again in a few minutes.",
                    "error_code": "server_busy",
                    "max": MAX_CONCURRENT_GLOBAL,
                    "active": _active_total,
                }), 429
        # Atomically claim the slot
        job["status"] = "generating"
        # Save voice in job for logging
        job["voice"] = voice
        job["platform"] = _client_platform()
        # Proprietario dello slot: fissato qui e mai piu' riscritto (vedi
        # _gen_owner_cid), cosi' il transfer verso l'app mobile non libera
        # il posto occupato dalla generazione ancora in corso.
        job["gen_owner_cid"] = client_id
        job["abuse_group"] = _abuse_group
        job.pop("abuse_terminated", None)
        job.pop("abuse_kept_until", None)

    # Batch mobile: il job sopravvive a schermo bloccato (no auto-cancel per
    # heartbeat, la guardia salta se email_registered) e al COMPLETE crea il
    # download token anche senza email (push + my_jobs). Nessun SMTP richiesto.
    if data.get("batch_mode"):
        job["email_registered"] = True
        job.setdefault("notify_download_type", "audio")

    # Store format and podcast URL for email/download handlers
    job["output_format"] = output_format
    if output_format == "zip_rss":
        job["notify_download_type"] = "podcast"
        job["notify_base_url"] = podcast_base_url

    info = job["info"]

    # Filter chapters if a subset was selected
    job["selected_chapters"] = selected_chapters  # store for ABM export
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

    # Hard cap on TTS-bound text size for THIS run: applied solo alla selezione.
    # 1 char ~= 50-100 byte di MP3, quindi il limite mantiene l'output sotto
    # ~75-150 MB. Per voci PREMIUM (gemini:) usiamo MAX_GEMINI_TEXT_CHARS
    # (default 800k, piu' restrittivo) data la maggior pressione su cost/RPM.
    max_text_chars = _effective_max_text_chars(voice, job)
    selected_chars = sum(ch.char_count for ch in info.chapters)
    if selected_chars > max_text_chars:
        with _jobs_lock:
            if job["status"] == "generating":
                job["status"] = "optimized" if job.get("ai_optimized") else "analyzed"
        # Rete di sicurezza: i cap a monte (create_order_gemini + blocco
        # pre-consume) dovrebbero impedire di arrivare qui con un pagamento gia`
        # consumato. Resta pero` il caso del testo espanso dall'ottimizzazione
        # LLM oltre il cap DOPO il consume: in quel caso rimborsa il pagamento e
        # rilascia la prenotazione budget Gemini, cosi` non si trattiene denaro
        # per un job non generabile.
        _refund_payment_on_orphan(job_id, job, "selection_too_large")
        try: gemini_tts.release_reservation(job_id)
        except Exception: pass
        return jsonify({
            "error": f"Selection too large: {selected_chars:,} characters "
                     f"(limit {max_text_chars:,}). Please reduce the chapter selection.",
            "error_code": "selection_too_large",
            "chars_selected": selected_chars,
            "chars_limit": max_text_chars,
        }), 413

    #  -  -  Riuso di una generazione identica (voci standard, stesso client)  -  -
    # Impronta = testo dei capitoli selezionati + voce/rate/formato/parentesi.
    # Un hit serve i file del job sorgente (ancora in finestra calda) senza
    # sintesi: niente quota caratteri. Mai per job premium/pagati.
    _reuse_src = None
    job.pop("reuse_key", None)
    if not _premium_req and output_reuse.enabled():
        try:
            _rk = output_reuse.compute_key(
                info.chapters, voice, rate, output_format, single_file,
                strip_round=not bool(job.get("read_round_parens", False)),
                strip_square=not bool(job.get("read_square_brackets", False)))
            job["reuse_key"] = _rk
            _ent = output_reuse.lookup(_rk, client_id)
            if _ent and _ent.get("job_id") != job_id:
                _src_job = jobs.get(_ent.get("job_id"))
                if output_reuse.source_is_reusable(_src_job, client_id):
                    _reuse_src = _ent["job_id"]
                    print(f"[{job_id}] output reuse: hit su {_reuse_src}", flush=True)
                else:
                    output_reuse.forget(_rk)
        except Exception as _ru_err:
            print(f"[{job_id}] output reuse lookup failed (non-fatal): {_ru_err}", flush=True)
            _reuse_src = None

    #  -  -  Quota mensile caratteri voci STANDARD (gate email oltre quota)  -  -
    # Oltre `ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH` ogni libro a voce standard e'
    # accettato solo in modalita' batch con email registrata (`quota_ack` dal
    # frontend dopo /api/register_email). Il consumo e' rinviato al punto di
    # partenza certa (sotto), come per la quota premium. La chiave include
    # l'epoch: una ri-generazione dello stesso job e' una nuova sintesi.
    job.pop("_free_tts_quota_charge", None)
    if _reuse_src is None and not _premium_req and (
            free_tts_quota.limit_chars() > 0 or free_tts_quota.cap_chars() > 0):
        _ftq_cid = _quota_client_id(job)
        _ftq_key = f"{job_id}:{job.get('gen_epoch', 0) + 1}"
        _ftq_mail = job.get("notify_email") or ""
        _ftq_gated = False
        # Tetto duro (ABM_FREE_TTS_CAP_CHARS_PER_MONTH): qui, PRIMA del gate
        # email, perche' nessun ack lo supera. Contato sull'identita' di quota
        # e sull'hash dell'email del gate: cancellare il cookie non azzera il
        # contatore (caso 0e82f064, 42 Mchars in un mese con identita' stabile
        # e quindi nessun verdetto di abuso).
        _ftq_cap = free_tts_quota.cap_decision(_ftq_cid, selected_chars, _ftq_key,
                                               email=_ftq_mail)
        if not _ftq_cap["allowed"]:
            with _jobs_lock:
                if job["status"] == "generating":
                    job["status"] = "optimized" if job.get("ai_optimized") else "analyzed"
            _log_activity(job_id, job.get("original_filename", ""), "QUOTA_CAP",
                          client_id, client_ip, _voice_for_log(voice),
                          browser_lang=job.get("browser_lang", ""))
            _abuse_note(job_id, job, "quota_block", chars=selected_chars,
                        voice=_voice_for_log(voice))
            print(f"[{job_id}] free TTS cap: {_ftq_cap['used_chars']:,}+"
                  f"{selected_chars:,} > {_ftq_cap['cap_chars']:,} chars "
                  f"(chiave {_ftq_cap['key']}) -> rifiutato", flush=True)
            return jsonify({
                "error": "Monthly ceiling for the standard voices reached. The "
                         "counter resets next month; the premium voices stay "
                         "available now.",
                "error_code": "free_tts_cap_reached",
                "quota_used_chars": _ftq_cap["used_chars"],
                "quota_cap_chars": _ftq_cap["cap_chars"],
                "chars_selected": selected_chars,
            }), 402
        _ftq_dec = (free_tts_quota.decision(_ftq_cid, selected_chars, _ftq_key)
                    if free_tts_quota.limit_chars() > 0 else {"allowed": True})
        if not _ftq_dec["allowed"]:
            _ftq_ack = (bool(data.get("quota_ack")) and bool(job.get("notify_email"))
                        and bool(job.get("email_registered")))
            # Ack via push (app mobile): la consegna e' garantita dalla notifica,
            # nessuna email richiesta. Il batch va forzato qui: senza
            # `email_registered` l'heartbeat ucciderebbe il job a schermo spento,
            # e la push arriverebbe per un audiolibro mai prodotto.
            _ftq_push = _push_ack_possible(job)
            if not _ftq_ack and _ftq_push and bool(data.get("quota_ack")):
                _ftq_ack = True
                job["email_registered"] = True
                job.setdefault("notify_download_type", "audio")
                print(f"[{job_id}] free TTS quota: ack via push (app) -> batch "
                      f"senza email", flush=True)
            if not _ftq_ack and _smtp_available():
                with _jobs_lock:
                    if job["status"] == "generating":
                        job["status"] = "optimized" if job.get("ai_optimized") else "analyzed"
                _log_activity(job_id, job.get("original_filename", ""), "QUOTA_BLOCK",
                              client_id, client_ip, _voice_for_log(voice),
                              browser_lang=job.get("browser_lang", ""))
                _abuse_note(job_id, job, "quota_block", chars=selected_chars, voice=_voice_for_log(voice))
                print(f"[{job_id}] free TTS quota: {_ftq_dec['used_chars']:,}+"
                      f"{selected_chars:,} > {_ftq_dec['limit_chars']:,} chars "
                      f"-> email gate", flush=True)
                return jsonify({
                    "error": "Monthly free-voice quota exceeded. Register an email "
                             "address to receive this audiobook when it is ready.",
                    "error_code": "free_tts_quota_exhausted",
                    "quota_used_chars": _ftq_dec["used_chars"],
                    "quota_limit_chars": _ftq_dec["limit_chars"],
                    "chars_selected": selected_chars,
                    "email_required": True,
                    # Dice al client mobile quale schermata mostrare senza un
                    # secondo giro: `true` -> "ricevi con una notifica"
                    # (ritentare con quota_ack), `false` -> chiedi l'email.
                    "push_ack_possible": _ftq_push,
                }), 402
            # Gate superato (email registrata) oppure SMTP assente: il gate
            # sarebbe impassabile, quindi si lascia passare senza marcare.
            _ftq_gated = bool(_ftq_ack)
        job["_free_tts_quota_charge"] = (_ftq_cid, _ftq_key, selected_chars,
                                         _ftq_gated, _ftq_mail)

    # Consumo quota: qui, non prima. Fra il claim atomico e questo punto ci
    # sono ancora uscite sincrone che abortiscono il job senza avviarlo
    # (selezione capitoli vuota, cap selection_too_large con refund pagamento)
    # e nessuna prevede un rimborso quota equivalente (scelta di progetto:
    # si consuma tardi, non si restituisce mai). Da qui in poi non resta
    # alcun `return` prima di thread.start(): il job e' ormai certo di
    # partire. Idempotente per generazione (free_quota.charge_key).
    # Con quota disattivata (ABM_FREE_QUOTA_EUR_PER_MONTH=0) NON si consuma:
    # riempire il contatore in silenzio significa che, alzando il limite a mese
    # in corso, molti client risulterebbero gia' esauriti e verrebbero addebitati
    # subito. Il client_id e' lo stesso usato dal gate (`_quota_client_id`).
    _fq_charge = job.pop("_free_quota_charge", None)
    if isinstance(_fq_charge, (tuple, list)) and len(_fq_charge) == 2:
        _fq_charge, _fq_key = _fq_charge
    else:
        _fq_key = job_id
    if _fq_charge is not None and free_quota.limit_eur() > 0:
        try:
            _fq_total = free_quota.consume(_quota_client_id(job), _fq_charge, _fq_key)
            job["free_quota_key"] = _fq_key
            print(f"[{job_id}] free quota consumed: +{_fq_charge:.2f}€ -> "
                  f"{_fq_total:.2f}€/{free_quota.limit_eur():.2f}€ "
                  f"(chiave {_fq_key})", flush=True)
        except Exception as _fq_err:
            print(f"[{job_id}] free_quota consume failed (non-fatal): {_fq_err}", flush=True)

    # Quota caratteri voci standard: stesso punto di consumo (job certo di
    # partire). Il riferimento posato sul job serve a _set_job_status per lo
    # storno in caso di errore server.
    _ftq = job.pop("_free_tts_quota_charge", None)
    if _ftq is not None:
        _ftq_cid, _ftq_key, _ftq_chars, _ftq_gated, _ftq_mail = _ftq
        try:
            _ftq_total = free_tts_quota.consume(_ftq_cid, _ftq_chars, _ftq_key,
                                                gated=_ftq_gated, email=_ftq_mail)
            job["_free_tts_quota_ref"] = (_ftq_cid, _ftq_key, _ftq_mail)
            print(f"[{job_id}] free TTS quota consumed: +{_ftq_chars:,} -> "
                  f"{_ftq_total:,}/{free_tts_quota.limit_chars():,} chars "
                  f"(cap {free_tts_quota.cap_chars():,})"
                  f"{' (gated)' if _ftq_gated else ''}", flush=True)
            if _ftq_gated:
                _log_activity(job_id, job.get("original_filename", ""), "QUOTA_GATE",
                              client_id, client_ip, _voice_for_log(voice),
                              browser_lang=job.get("browser_lang", ""))
                _abuse_note(job_id, job, "quota_gate", chars=_ftq_chars, voice=_voice_for_log(voice))
        except Exception as _ftq_err:
            print(f"[{job_id}] free_tts_quota consume failed (non-fatal): {_ftq_err}",
                  flush=True)

    # Voce campione: da qui il job e' certo di partire (vedi commento sopra),
    # quindi e' il punto giusto per rinnovare la retention all'uso (D15).
    # L'etichetta amichevole per email/pannello di completamento e' gia'
    # risolta da generation_engine._friendly_voice_name(job["voice"]) ("Your
    # voice") - job["voice_label"] non aveva alcun lettore (C2, rimosso).
    if voice.startswith(voice_clone.VOICE_ID_PREFIX):
        _vc_rec2 = voice_clone.by_token(voice_clone.token_of(voice))
        if _vc_rec2 is not None:
            voice_clone.touch_used(_vc_rec2["id"])
            routes_voice_clone._vc_log(_vc_rec2, "VOICE_CLONE_USED", job_id)

    # Account: consegna forzata all'email dell'account + riga nello storico.
    # Prima del descrittore di partenza, cosi' lo cattura gia' in modalita' email.
    _apply_account_to_job(job, job_id, "generate", output_format=output_format,
                          podcast_base_url=podcast_base_url, voice=voice,
                          lang=(data.get("lang") or job.get("browser_lang") or "en"))

    # Descrittore di recovery (ri)scritto ALLA PARTENZA con i parametri di
    # questa generazione. Quello scritto da register_email puo' non esistere
    # (job allora in analyzed) o essere vecchio: voce/selezione/pagamento di un
    # tentativo precedente. Upsert idempotente; solo per i job batch.
    if job.get("email_registered") and job.get("notify_download_type") != "translated":
        try:
            pending_jobs.register(job_id, "generate", _build_job_descriptor(job, "generate"))
        except Exception as _e:
            print(f"[{job_id}] pending_jobs.register (start) failed (non-fatal): {_e}",
                  flush=True)

    # Increment generation epoch to invalidate any stale threads
    job["gen_epoch"] = job.get("gen_epoch", 0) + 1
    _gen_kwargs = {'output_format': output_format, 'podcast_base_url': podcast_base_url,
                   'gemini_style_instruction': job.get("gemini_style_instruction"),
                   'speechify_emotion': job.get("speechify_emotion")}
    if _reuse_src:
        _gen_kwargs['reuse_from'] = _reuse_src
    thread = threading.Thread(
        target=(generation_engine.run_reuse if _reuse_src else run_generation),
        args=(job_id, info, voice, rate, single_file),
        kwargs=_gen_kwargs,
        daemon=True
    )
    thread.start()
    _log_activity(job_id, job.get("original_filename", ""), "GENERATE",
                  client_id, client_ip, _voice_for_log(voice),
                  browser_lang=job.get("browser_lang", ""),
                  epoch=job.get("gen_epoch"),
                  platform=job.get("platform", ""))
    _abuse_note(job_id, job, "generate", chars=selected_chars, voice=_voice_for_log(voice))
    _admin_notify_generation(job_id, info, _voice_for_log(voice), job.get("original_filename", ""))
    _resp = {"status": "started"}
    # Job pagato portato in modalita' batch sull'email del pagamento: comunica
    # al frontend l'email (mascherata) cosi' l'utente sa dove ricevera' il file
    # anche se chiude la pagina. Solo per l'auto-batch implicito (non quando
    # l'utente ha gia' registrato manualmente un'email).
    if job.get("_auto_batch_notify") and job.get("notify_email"):
        _resp["auto_batch_email"] = _mask_email(job["notify_email"])
    return jsonify(_resp)


def _job_progress(job):
    """(status, current, total, pct) di un job in corso; zeri se non in corso.

    Unica aritmetica del pct per /api/job_status (singolo) e
    /api/admin/jobs_progress (bulk): due copie divergerebbero.
    """
    st = job.get("status", "")
    cur, tot = 0, 0
    pct = 0
    if st == "optimizing":
        total_chars = job.get("opt_total_chars", 1) or 1
        done_chars = job.get("opt_processed_chars", 0)
        cur_ch_chars = job.get("opt_current_chapter_chars", 0)
        streamed = min(job.get("opt_streamed_chars", 0), cur_ch_chars)
        worked = done_chars + streamed
        pct = min(99, int(worked / total_chars * 100))
        cur, tot = worked, total_chars
    elif st == "generating":
        cur = job.get("progress_current", 0)
        tot = job.get("progress_total", 0)
        pct = int(cur / tot * 100) if tot > 0 else 0
    elif st == "translating":
        cur = job.get("tr_progress_current", 0)
        tot = job.get("tr_progress_total", 0)
        pct = int(cur / tot * 100) if tot > 0 else 0
    return st, cur, tot, pct


@app.route("/api/job_status/<job_id>")
def api_job_status(job_id):
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return ({"error": "Not found"} if sc == 404 else {"error": "Forbidden"}), sc

    return _job_progress_info(job)


# E3 (seam admin, parte 4): progress in routes_admin_jobs.


def _job_progress_info(job):
    """Dict di avanzamento come lo mostra la SPA (stessa aritmetica di
    `_job_progress`). Usato da /api/job_status (cookie cid) e da
    /api/account/progress (sessione account): un solo calcolo, due
    autorizzazioni."""
    st, cur, tot, pct = _job_progress(job)
    return {
        "status": st,
        "current": cur,
        "total": tot,
        "pct": pct,
        "message": job.get("progress_message", "") or job.get("opt_progress_message", "")
    }


@app.route("/api/account/progress", methods=["GET"])
def api_account_progress():
    """Avanzamento dei job dell'account per la pagina /account (`?ids=a,b`).
    Autorizza la sessione account, non il cookie cid: il job puo' essere
    partito da un altro dispositivo. Job non piu' in memoria: assenti dalla
    risposta (la pagina lascia il badge com'e')."""
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    ids = [i.strip() for i in (request.args.get("ids") or "").split(",") if i.strip()][:50]
    out = {}
    for jid in ids:
        job = jobs.get(jid)
        if job is None or accounts.job_owner(jid) != acct["id"]:
            continue
        info = _job_progress_info(job)
        if job.get("server_interrupted"):
            info["status"] = "interrupted"
        elif job.get("status") == "analyzed" and job.get("cancelled"):
            # Cancel riportato ad "analyzed": per lo storico e' concluso.
            info["status"] = "cancelled"
        out[jid] = info
    resp = jsonify({"jobs": out})
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _sse_event(payload):
    return f"data: {json.dumps(payload)}\n\n"


def _sse_response(gen):
    """Risposta `text/event-stream` con gli header anti-buffering usati da
    tutte le SSE dell'app."""
    return Response(stream_with_context(gen), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse_stream(job_id, build, *, sleep_sec=2.0):
    """SSE di avanzamento di un job: a ogni giro rilegge `jobs[job_id]`
    (evento di errore e chiusura se e' sparito), segna `last_poll`
    (heartbeat: un client sta ascoltando), chiede a `build(job)` la coppia
    `(payload, terminale)` e chiude lo stream sul terminale. `request` non
    e' disponibile dentro il generator: il chiamante cattura prima quello
    che gli serve (owner check, lingua)."""
    def gen():
        while True:
            if job_id not in jobs:
                yield _sse_event({"status": "error", "error": "Job not found"})
                break
            job = jobs[job_id]
            job["last_poll"] = time.time()
            payload, terminal = build(job)
            yield _sse_event(payload)
            if terminal:
                break
            time.sleep(sleep_sec)
    return _sse_response(gen())



@app.route("/api/progress/<job_id>")
def api_progress(job_id):
    # Ownership check fuori dallo stream (la `request` non è disponibile dentro il generator).
    _job_pre, _err_pre, _sc_pre = _check_job_owner(job_id)
    if _err_pre is not None:
        return _err_pre, _sc_pre
    # Lingua UI per il blocco dettagli localizzato del payload done (catturata
    # qui: `request` non è disponibile dentro il generator).
    _ui_lang = _i18n.norm_lang(request.args.get("lang"))

    def _build(job):
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
        # M4B progress (visibile solo se la fase M4B è attiva)
        if job.get("m4b_progress_total"):
            payload["m4b_progress_current"] = job.get("m4b_progress_current", 0)
            payload["m4b_progress_total"] = job["m4b_progress_total"]
            payload["m4b_progress_message"] = job.get("m4b_progress_message", "")
        # Espone l'importo pagato (quota refundabile) e il metodo: serve
        # al frontend per reidratare _payState dopo un reload e mostrare
        # "Importo versato" corretto nel modal di cancel. Usa total_eur
        # (l'importo effettivamente consumato dal payment_token) perche'
        # e' la stessa base che _CancelledError handler in
        # generation_engine.py passa a cancel_policy.compute_cancel_retention.
        _paym_sse = job.get("payment") or {}
        if _paym_sse:
            try:
                payload["paid_eur"] = round(float(_paym_sse.get("total_eur", 0.0) or 0.0), 2)
            except (TypeError, ValueError):
                payload["paid_eur"] = 0.0
            payload["paid_method"] = _paym_sse.get("method", "")
        if job.get("status") == "error":
            # Errore generico verso il client: il dettaglio resta nei log server-side.
            payload["error"] = "generation_failed"
            # Eccezione: per il pre-flight block delle voci PREMIUM,
            # esponiamo un error_kind strutturato cosi' il frontend puo'
            # mostrare un popup specifico e riportare l'utente alla scelta
            # voce (invece di redirect generico alla home).
            _pf_block = job.get("gemini_preflight_block")
            if _pf_block:
                payload["error_kind"] = "gemini_overload"
                payload["retry_after_sec"] = int(_pf_block.get("retry_after_sec") or 0)
                _paym = job.get("payment") or {}
                payload["refund_method"] = _paym.get("method", "")
                # Codice voucher di rimborso solo se PayPal (per voucher
                # il riaccredito e' silenzioso sul codice originale).
                if _paym.get("method") == "paypal":
                    _vcode = job.get("refund_voucher_code")
                    if _vcode:
                        payload["refund_voucher_code"] = _vcode
            return payload, True
        if job.get("status") == "cancelled" or job.get("cancelled"):
            payload["status"] = "cancelled"
            if job.get("abuse_terminated"):
                # Kill della moderazione anti-abuso: il frontend mostra il
                # messaggio neutro invece di "Generazione annullata".
                payload["error_code"] = "job_terminated"
            # Espone metadati cancel volontario voci PREMIUM: refund summary
            # (paid/retained/refund/progress) + link al MP3 parziale se
            # generato. Vedi T7 generation_engine.py:_CancelledError branch.
            _cm = job.get("cancel_meta")
            if isinstance(_cm, dict):
                payload["cancel_meta"] = {
                    "paid_eur": _cm.get("paid_eur", 0),
                    "retained_eur": _cm.get("retained_eur", 0),
                    "refund_eur": _cm.get("refund_eur", 0),
                    "progress_pct": _cm.get("progress_pct", 0),
                    "partial_audio_delivered": bool(
                        _cm.get("partial_audio_delivered", False)),
                }
            _pdl = job.get("partial_download_url")
            if _pdl:
                payload["partial_download_url"] = _pdl
            return payload, True
        if job.get("status") in ("done", "partial"):
            # 'partial' (frazione chunk falliti oltre soglia) percorre lo
            # stesso path di completamento di 'done' — file, ABM, email e
            # offload sono gia' prodotti. E' uno stato TERMINALE: va emesso
            # il payload di completamento e chiuso lo stream, altrimenti il
            # frontend resta appeso sulla schermata di avanzamento.
            # payload["status"] conserva il valore reale ('partial'/'done').
            payload["output_name"] = job.get("output_name", "output")
            payload["has_podcast"] = job.get("podcast_ready", False)
            # Reconnection fallback: se output_m4b o optimized_abm_path non sono
            # impostati, cerca SOLO dentro la cartella della generazione corrente
            # (job["output_dir"] = output_{gen_epoch}/). Mai fare scan globale su
            # tutti gli output_*/ perché erediteresti file di run precedenti e li
            # mostreresti come scaricabili per la run corrente.
            _cur_output = job.get("output_dir")
            if _cur_output and os.path.isdir(_cur_output):
                _cur_path = Path(_cur_output)
                if not job.get("output_m4b"):
                    _m4bs = list(_cur_path.glob("*.m4b"))
                    if _m4bs:
                        job["output_m4b"] = str(_m4bs[0])
                if not job.get("optimized_abm_path"):
                    _abms = list(_cur_path.glob("*.abm"))
                    if _abms:
                        job["optimized_abm_path"] = str(_abms[0])

            payload["output_m4b"] = bool(job.get("output_m4b"))
            payload["has_abm"] = bool(job.get("ai_optimized")) or (bool(job.get("optimized_abm_path")) and os.path.exists(job.get("optimized_abm_path", "")))
            payload["failed_chunks"] = job.get("failed_chunks", 0)
            payload["m4b_failed"] = bool(job.get("m4b_failed", False))
            # Kit ZIP di ripiego (MP3 + capitoli + script) quando l'M4B è fallito.
            _kit_zip = job.get("output_m4b_fallback_zip")
            payload["m4b_fallback_zip"] = bool(_kit_zip and os.path.exists(_kit_zip))
            # Dettagli di generazione localizzati per il pannello
            # "Audiolibro pronto": stessi testi del blocco email di
            # completamento (fonte unica _generation_details_lines,
            # campi utente già HTML-escaped). Best-effort.
            try:
                _det = generation_engine._generation_details_lines(
                    job, _ui_lang or (job.get("notify_lang") or "en"))
                if _det:
                    payload["gen_details_html"] = "<br>".join(_det)
            except Exception as _det_err:
                print(f"[{job_id}] gen_details payload failed (non-fatal): {_det_err}")
            return payload, True
        return payload, False

    return _sse_stream(job_id, _build, sleep_sec=1)


def _log_admin_cancel(job_id, job, voice):
    """Riga ADMIN_CANCEL nel log attivita' (kill dalla console admin): stessa
    forma per generazione, ottimizzazione e traduzione."""
    _log_activity(job_id, job.get("original_filename", ""), "ADMIN_CANCEL",
                  job.get("client_id", ""), "", voice or "", "")


@app.route("/api/cancel/<job_id>", methods=["POST"])
def api_cancel(job_id):
    """Cancella un job in corso.

    Per voci Gemini, il cancel volontario e' bloccato oltre la soglia
    ABM_GEMINI_CANCEL_LOCK_PCT (default 70). Vedi
    docs/superpowers/specs/2026-05-25-cancel-gemini-floor-design.md.
    """
    _job, _err, _sc = _check_job_owner(job_id)
    if _err is not None:
        if _sc == 404:
            return jsonify({"status": "not_found"}), 404
        return _err, _sc
    with _jobs_lock:
        job = jobs[job_id]
        voice = job.get("voice", "") or job.get("opt_voice", "") or ""
        is_gemini = _is_gemini_voice(voice)
        force = request.args.get("force") == "1"
        # Kill amministrativo (force=1 + auth admin): bypassa il lock Gemini
        # anti-abuso (pensato per i cancel volontari utente) e il guard
        # email_registered. Usato da scripts/kill_job.sh.
        is_admin_kill = force and _admin_auth_ok(_admin_auth_from_request())
        if is_gemini and not is_admin_kill:
            lock_pct = env_int("ABM_GEMINI_CANCEL_LOCK_PCT", 70)
            if 0 < lock_pct < 100:
                from generation_engine import _progress_pct
                pct = _progress_pct(job)
                if pct > lock_pct:
                    return jsonify({
                        "error": "cancel_locked_progress",
                        "progress_pct": pct,
                        "lock_pct": lock_pct,
                    }), 409
        if job.get("email_registered") and not force:
            print(f"[{job_id}] Cancel ignored  -  email registered for background processing")
            return jsonify({"status": "ignored_email_registered"})
        job["cancelled"] = True
        # NB: non incrementiamo gen_epoch qui. Il bump epoch e' riservato
        # al riavvio della generazione (/api/generate linea ~5548) per
        # invalidare worker thread orfane. Bumparlo sul cancel volontario
        # farebbe finire run_generation nel ramo STALE del _CancelledError
        # handler, saltando refund + partial-audio email.
        job["status"] = "analyzed"
        if is_admin_kill:
            job["server_interrupted"] = True
    if is_admin_kill:
        _log_admin_cancel(job_id, job, job.get("voice", ""))
    return jsonify({"status": "cancelling"})


@app.route("/api/cancel_preview/<job_id>", methods=["GET"])
def api_cancel_preview(job_id):
    """Snapshot sincrono dei parametri di cancel per la modale di conferma.

    Il client legge da qui paid_eur/progress_pct invece di affidarsi a
    _payState (in-memory, perso al reload) o all'evento SSE (latenza: dopo
    F5 il primo evento puo' arrivare dopo il click su cancel, lasciando
    il modal con "Importo versato: 0.00 EUR"). Server e' single source of
    truth: legge payment.total_eur, identico a quanto consumato dal
    refund handler in generation_engine._handle_cancelled_error.
    """
    _job, _err, _sc = _check_job_owner(job_id)
    if _err is not None:
        if _sc == 404:
            return jsonify({"status": "not_found"}), 404
        return _err, _sc
    with _jobs_lock:
        if job_id not in jobs:
            return jsonify({"status": "not_found"}), 404
        job = jobs[job_id]
        paym = job.get("payment") or {}
        try:
            paid_eur = round(float(paym.get("total_eur", 0.0) or 0.0), 2)
        except (TypeError, ValueError):
            paid_eur = 0.0
        paid_method = paym.get("method", "") or ""
        # Fallback ai campi flat: i flussi traduzione/ottimizzazione registrano
        # il pagamento in payment_amount_eur/payment_type e NON nel dict
        # job["payment"] (riservato al TTS). Senza questo la modale ⛔ direbbe
        # "nessun rimborso" pur essendo il job rimborsabile integralmente.
        if paid_eur <= 0:
            try:
                paid_eur = round(float(job.get("payment_amount_eur", 0.0) or 0.0), 2)
            except (TypeError, ValueError):
                paid_eur = 0.0
        if not paid_method:
            paid_method = job.get("payment_type", "") or ""
        try:
            from generation_engine import _progress_pct
            pct = _progress_pct(job)
        except Exception:
            pct = 0
        # _progress_pct usa i campi TTS (progress_*); per la traduzione la
        # progressione vive nei campi tr_progress_*.
        if pct <= 0 and job.get("status") == "translating":
            _tt = job.get("tr_progress_total", 0) or 0
            if _tt > 0:
                pct = max(0, min(100, int(job.get("tr_progress_current", 0) / _tt * 100)))
        lock_pct = env_int("ABM_GEMINI_CANCEL_LOCK_PCT", 70)
        # Il lock anti-abuso è una soglia sul cancel volontario delle voci
        # PREMIUM (TTS Gemini): non si applica alla traduzione, il cui cancel
        # non ha alcun lock. Evita la nota fuorviante nella modale admin.
        _is_translation = job.get("status") == "translating"
    return jsonify({
        "paid_eur": paid_eur,
        "paid_method": paid_method,
        "progress_pct": pct,
        "lock_pct": lock_pct,
        "locked": (not _is_translation and 0 < lock_pct < 100 and pct > lock_pct),
    })


@app.route("/api/heartbeat/<job_id>", methods=["POST"])
def api_heartbeat(job_id):
    """Keep-alive: il client segnala che è ancora sulla pagina."""
    _job, _err, _sc = _check_job_owner(job_id)
    if _err is not None:
        return "", _sc
    with _jobs_lock:
        if job_id in jobs:
            jobs[job_id]["last_poll"] = time.time()
            return "", 204
    return "", 404


@app.route("/api/reset_to_chapters/<job_id>", methods=["POST"])
def api_reset_to_chapters(job_id):
    """Reset a completed job back to 'analyzed' so the user can select different chapters."""
    _job, _err, _sc = _check_job_owner(job_id)
    if _err is not None:
        return _err, _sc
    with _jobs_lock:
        if job_id not in jobs:
            return jsonify({"error": "Job not found"}), 404
        job = jobs[job_id]
        if job.get("status") != "done":
            return jsonify({"error": "Job is not in completed state"}), 400
        if not job.get("info") or not job["info"].chapters:
            return jsonify({"error": "Book data no longer available. Please re-upload the file."}), 400

    # Per-epoch layout: /api/generate writes into work_dir/output_{epoch}/,
    # including the .abm snapshot. Reset is fully non-destructive for outputs
    # — the next generation bumps gen_epoch and writes into a fresh dir,
    # leaving previous epochs (audio + .abm) intact for any active email
    # tokens. The cleanup loop purges orphan dirs after retention.
    #
    # The only .abm file we still delete here is a stray copy at work_dir
    # root left over from an optimization phase that never ran a generation
    # (the work_dir-root path is no longer in use once output_dir exists).
    work_dir = UPLOAD_DIR / job_id
    for abm in work_dir.glob("*.abm"):
        # La traduzione adottata resta il libro del job anche dopo il reset:
        # e' la sorgente del recovery per la prossima generazione.
        if abm.name == ADOPTED_TRANSLATION_ABM:
            continue
        try:
            abm.unlink()
            print(f"[reset] Removed work_dir-root ABM: {abm}")
        except OSError:
            pass

    # Reset job state (inside lock)
    with _jobs_lock:
        job["status"] = "analyzed"
        job["last_poll"] = time.time()
        for key in ("output_files", "output_name", "output_zip", "output_file",
                    "output_m4b",
                    "podcast_ready", "podcast_safe_name", "podcast_mp3s",
                    "progress_current", "progress_total", "progress_message",
                    "processed_chars", "total_chars", "bytes_generated",
                    "start_time", "elapsed_seconds", "current_chapter",
                    "current_chapter_num", "total_chapters",
                    "downloaded_at", "email_sent_at", "email_registered",
                    "failed_chunks", "cancelled",
                    "opt_cancelled", "opt_progress_current", "opt_progress_total",
                    "opt_progress_message", "opt_current_chapter", "opt_current_chapter_num",
                    "opt_processed_chars", "opt_total_chars", "opt_streamed_chars",
                    "opt_current_chapter_chars", "opt_elapsed_seconds", "opt_completed_at",
                    "optimized_abm_path", "optimized_abm_name",
                    "selected_chapters",
                    "opt_auto_generate", "opt_single_file", "opt_output_format",
                    "opt_podcast_base_url", "opt_voice", "opt_rate", "opt_lang",
                    "email_token"):
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
    download_type = data.get("download_type", "audio")  # audio | chapters | podcast | translated
    if download_type not in ("audio", "chapters", "podcast", "translated"):
        download_type = "audio"
    base_url = (data.get("base_url") or "").strip()

    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return err, sc

    if not email or not _ACCT_EMAIL_RE.match(email):
        return jsonify({"error": "Invalid email address"}), 400

    # Con sessione attiva la notifica e' vincolata all'email dell'account.
    try:
        _acct = _current_account() if accounts.enabled() else None
    except Exception:
        _acct = None
    if _acct and _acct["email"] != email:
        return jsonify({"error": "Notifications go to your account email",
                        "error_code": "logged_in_email_forced",
                        "email": _acct["email"]}), 409

    if not _smtp_available():
        return jsonify({"error": "Email service not configured on this server"}), 503

    job["notify_email"] = email
    job["notify_download_type"] = download_type
    job["notify_base_url"] = base_url
    job["notify_lang"] = data.get("lang", "en")
    # Keep job alive indefinitely while generating (disable heartbeat-based cleanup)
    job["email_registered"] = True
    _abuse_note(job_id, job, "email", email=email)
    # Marker 'pending' su disco: protegge la dir dal cleanup orfani di altri worker
    # per tutta la lavorazione, finché _send_completion_email lo sovrascriverà
    # con il timestamp.
    cleanup._write_email_pending_marker(UPLOAD_DIR / job_id)

    # Registra il descrittore di recupero: da qui il job è batch (email registrata).
    # ECCEZIONE (F1): i job di traduzione (download_type='translated') NON vanno
    # registrati. run_translation è per design NON recuperabile (vedi nota in
    # generation_engine.run_translation: nessuno snapshot per-chunk, riavvio
    # rischia di ri-eseguire job già rimborsati). Un descrittore qui verrebbe
    # salvato con phase='generate' e voice='' (job di traduzione, voce mai
    # impostata) e il recovery lo instraderebbe a run_generation -> audiolibro
    # completamente muto consegnato per una traduzione (spesso già fallita e
    # rimborsata). Quindi: non registrare alcun pending per i job translated.
    if job.get("notify_download_type") == "translated":
        print(f"[{job_id}] register_email: download_type=translated -> pending "
              f"NON registrato (traduzione non recuperabile by design).", flush=True)
    elif job.get("status") == "analyzed":
        # Job mai partito: lo snapshot di adesso (voce/selezione di un tentativo
        # che puo' essere stato rifiutato da /api/generate) non descrive alcuna
        # lavorazione da riprendere. Il descrittore lo scrive /api/generate o
        # /api/optimize alla partenza effettiva, con i parametri reali.
        print(f"[{job_id}] register_email: job mai partito (status=analyzed) -> "
              f"pending NON registrato; lo registra la partenza.", flush=True)
    else:
        # La fase NON è sempre 'generate': se register_email avviene mentre il job è
        # ancora in (o in attesa di) ottimizzazione AI, forzare 'generate' farebbe
        # saltare la ri-ottimizzazione al recovery → audio da testo grezzo e
        # ottimizzazione pagata non consegnata. Deriviamo quindi la fase dallo stato.
        _in_opt = (job.get("status") in ("optimizing", "optimized")
                   or (job.get("opt_auto_generate") and not job.get("ai_optimized")))
        _phase = "optimize" if _in_opt else "generate"
        try:
            pending_jobs.register(job_id, _phase, _build_job_descriptor(job, _phase))
        except Exception as _e:
            print(f"[{job_id}] pending_jobs.register failed (non-fatal): {_e}", flush=True)

    # Storico account: chi registra l'email da loggato sta dichiarando che quel
    # job e' suo, ma la riga di storico la scrive solo la partenza
    # (_apply_account_to_job). Un job avviato da sloggato e poi "adottato" qui
    # resterebbe invisibile nella pagina /account: lo registriamo adesso.
    # La riga di un ALTRO account non viene mai riassegnata (record_job e' un
    # upsert che sovrascriverebbe account_id): la guardia e' accounts.job_owner.
    # Job mai partito (status=analyzed): nessuna riga, come per il descrittore
    # pending — la scrivera' /api/generate|optimize|translate alla partenza,
    # con i parametri reali invece di uno snapshot che puo' non avverarsi mai.
    if _acct and job.get("status") != "analyzed":
        try:
            _owner = accounts.job_owner(job_id)
            if _owner in (None, _acct["id"]):
                _st = job.get("status") or ""
                _hist_status = (_st if _st in ("done", "error") else
                                "cancelled" if _st in ("cancelled", "canceled") else "running")
                if download_type == "translated":
                    _kind = "translate"
                elif (job.get("status") in ("optimizing", "optimized")
                      or (job.get("opt_auto_generate") and not job.get("ai_optimized"))):
                    _kind = "optimize"
                else:
                    _kind = "generate"
                _engine, _model = _voice_plan_info(job.get("voice") or "")
                accounts.record_job(
                    _acct["id"], job_id, kind=_kind, book_title=_job_book_title(job),
                    output_format=job.get("output_format") or "",
                    voice=_voice_public_label(job.get("voice") or ""),
                    lang=job.get("browser_lang") or "", paid_eur=_job_paid_eur(job),
                    source="forced", status=_hist_status,
                    engine=_engine, model=_model)
        except Exception as _e:
            print(f"WARNING [{job_id}] accounts.record_job (register_email): {_e}", flush=True)

    print(f"[{job_id}] Email notification registered: {_mask_email(email)} (type: {download_type})")
    _log_activity(job_id, job.get("original_filename", ""), "EMAIL_REGISTERED",
                  job.get("client_id", ""), job.get("client_ip", ""),
                  job.get("voice", ""), job.get("browser_lang", ""))

    # Persist client_id → email per fallback su job futuri (difesa da UI fallita)
    client_id = job.get("client_id", "")
    if client_id:
        _client_emails[client_id] = email
        _save_client_emails()

    return jsonify({"status": "registered", "email": email})


@app.route("/api/email_available")
def api_email_available():
    """Check if email notification is available (SMTP configured)."""
    return jsonify({"available": _smtp_available()})


@app.route("/api/device/register", methods=["POST"])
def api_device_register():
    """Registra/aggiorna il device FCM del client mobile per le notifiche push."""
    data = request.get_json(silent=True) or {}
    cid = _get_client_id()
    if not cid:
        return jsonify({"error": "Missing client id", "error_code": "no_cid"}), 400
    fcm_token = (data.get("fcm_token") or "").strip()
    platform_name = (data.get("platform") or "").strip().lower()
    app_version = (data.get("app_version") or "").strip()[:32]
    if not _FCM_TOKEN_RE.match(fcm_token):
        return jsonify({"error": "Invalid fcm_token", "error_code": "invalid_token"}), 400
    if platform_name not in ("android", "ios"):
        return jsonify({"error": "Invalid platform", "error_code": "invalid_platform"}), 400
    with _device_tokens_lock:
        entries = [e for e in _device_tokens.get(cid, [])
                   if e.get("fcm_token") != fcm_token]
        entries.append({
            "fcm_token": fcm_token,
            "platform": platform_name,
            "app_version": app_version,
            "registered_at": time.time(),
        })
        _device_tokens[cid] = entries[-_MAX_DEVICES_PER_CLIENT:]
        _save_device_tokens()
    # Lega l'installazione all'identita' di quota: l'app rigenera il proprio
    # identificativo a ogni pulizia dei dati, il token push no. Senza questo
    # legame la quota mensile voci standard ripartirebbe da zero a ogni reset.
    try:
        _canon = free_tts_quota.link_device(_device_hash(fcm_token), cid)
        if _canon and _canon != cid:
            print(f"[device] cid {cid} -> quota identity {_canon} "
                  f"(stessa installazione)", flush=True)
    except Exception as _link_err:
        print(f"[device] quota identity link failed (non-fatal): {_link_err}", flush=True)
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# MOBILE: JOB LIST
# ----------------------------------------------------------------------

# E3: blocco spostato in routes_mobile.


# E3 (seam admin, parte 4, 2026-10-10): strumenti admin sui job nel blueprint
# routes_admin_jobs (vedi routes_admin_audit per il metodo).
routes_admin_jobs.configure(
    admin_required=admin_required, admin_token=lambda: ADMIN_TOKEN,
    admin_auth_ok=lambda provided: _admin_auth_ok(provided),
    admin_auth_from_request=lambda: _admin_auth_from_request(),
    render_admin_gate=lambda title, url: _render_admin_gate(title, url),
    log_activity=lambda *a, **k: _log_activity(*a, **k),
    client_ip=lambda: client_ip(), qr_data_uri=lambda text: _qr_data_uri(text),
    upload_dir=lambda: UPLOAD_DIR, jobs=lambda: jobs, jobs_lock=_jobs_lock, suspend_lock=_suspend_lock,
    client_emails=lambda: _client_emails, max_concurrent_global=lambda: MAX_CONCURRENT_GLOBAL,
    job_progress=lambda *a, **k: _job_progress(*a, **k),
    effective_retention_for_token_info=lambda info: _effective_retention_for_token_info(info),
    reconstruct_admin_download_record=lambda *a, **k: routes_mobile._reconstruct_admin_download_record(*a, **k),
    paypal_api_base=lambda: PAYPAL_API_BASE, paypal_available=lambda: _paypal_available(),
    paypal_get_access_token=lambda: _paypal_get_access_token(), ym_re=_YM_RE)
app.register_blueprint(routes_admin_jobs.bp)



# E3 (seam mobile, 2026-10-10): i miei job, trasferimento e condivisione nel
# blueprint routes_mobile. Helper della app passati come lambda (risolti a
# ogni richiesta: i test li sostituiscono su questo modulo).
routes_mobile.configure(
    _jobs_lock=_jobs_lock,
    generation_engine=generation_engine,
    jobs=lambda: jobs,
    upload_dir=lambda: UPLOAD_DIR,
    share_ttl_sec=lambda: ABM_SHARE_TTL_SEC,
    share_max_bytes=lambda: ABM_SHARE_MAX_BYTES,
    share_upload_ttl_sec=lambda: ABM_SHARE_UPLOAD_TTL_SEC,
    client_emails_map=lambda: _client_emails,
    _get_client_id=lambda *a, **k: _get_client_id(*a, **k),
    _log_activity=lambda *a, **k: _log_activity(*a, **k),
    client_ip=lambda *a, **k: client_ip(*a, **k),
    _client_platform=lambda *a, **k: _client_platform(*a, **k),
    _share_link_for=lambda *a, **k: _share_link_for(*a, **k),
    _safe_share_filename=lambda *a, **k: _safe_share_filename(*a, **k),
    _effective_retention_for_token_info=lambda *a, **k: _effective_retention_for_token_info(*a, **k),
    _qr_data_uri=lambda *a, **k: _qr_data_uri(*a, **k),
    _transfer_payload_for=lambda *a, **k: _transfer_payload_for(*a, **k),
    _check_job_owner=lambda *a, **k: _check_job_owner(*a, **k),
    _find_files_in_outputs=lambda *a, **k: _find_files_in_outputs(*a, **k),
    _job_original_filename=lambda *a, **k: _job_original_filename(*a, **k),
    _send_file_throttled=lambda *a, **k: _send_file_throttled(*a, **k))
app.register_blueprint(routes_mobile.bp)



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
    job, err, sc = _check_job_owner(job_id)
    if err is not None: return err, sc
    info = job.get("info")
    if not info or not info.chapters: return jsonify({"error": "No book data"}), 400
    raw_sel = request.args.getlist("selected_chapters") + request.args.getlist("selected_chapters[]")
    selected_indices = _parse_selected_chapters(raw_sel)
    already = set(job.get("optimized_chapters", []))
    if raw_sel:
        total_chars = sum(ch.char_count for ch in info.chapters if ch.index in selected_indices and ch.index not in already)
    else:
        total_chars = sum(ch.char_count for ch in info.chapters if ch.index not in already)
    # Floor minimo parametrico (ABM_LLM_MIN_COST_EUR): sopra la soglia gratuita
    # l'importo dovuto e' alzato ad almeno il minimo. Sotto soglia resta free.
    # Unica fonte prezzo: payment.llm_price_eur (coerente con stima combinata,
    # ordine PayPal e addebito).
    _lp = payment.llm_price_eur(total_chars)
    cost = _lp["due_eur"]

    # Pre-validate the output-size cap against the full selected set so the
    # user is informed before being asked to pay. La voce influisce sul cap
    # (Gemini -> MAX_GEMINI_TEXT_CHARS, altrimenti MAX_TEXT_CHARS): il
    # frontend passa ?voice=... quando la conosce; in assenza si usa lo standard.
    voice_q = (request.args.get("voice") or "").strip()
    max_text_chars = _max_text_chars_for_voice(voice_q)
    if raw_sel:
        selected_set_cap = set(selected_indices)
    else:
        selected_set_cap = {ch.index for ch in info.chapters}
    selected_chars_total = sum(
        ch.char_count for ch in info.chapters if ch.index in selected_set_cap
    )
    if selected_chars_total > max_text_chars:
        return jsonify({
            "error": f"Selection too large: {selected_chars_total:,} characters "
                     f"(limit {max_text_chars:,}). Please reduce the chapter selection.",
            "error_code": "selection_too_large",
            "chars_selected": selected_chars_total,
            "chars_limit": max_text_chars,
        }), 413

    return jsonify({
        "chars": total_chars, "cost_eur": cost,
        "requires_payment": _lp["requires_payment"],
        "free_threshold_eur": _lp["free_threshold_eur"],
        "min_cost_eur": _lp["min_cost_eur"],
        "rate_eur_per_mchar": _lp["rate_eur_per_mchar"],
        "optimized_chapters": list(already),
    })


@app.route("/api/paypal_create_order", methods=["POST"])
def api_paypal_create_order():
    if not _paypal_available(): return jsonify({"error": "PayPal not configured"}), 503
    _maint = _maintenance_gate()
    if _maint is not None:
        return _maint
    data = request.json or {}; job_id = data.get("job_id", "")
    # Sec: solo il proprietario del job (o l'admin) puo' aprire un ordine su
    # di esso, come per ogni altra route che legge jobs[job_id].
    job, _err, _sc = _check_job_owner(job_id)
    if _err is not None:
        return _err, _sc
    info = job.get("info")
    if not info: return jsonify({"error": "No book data"}), 400
    selected_chapters = _parse_selected_chapters(data.get("selected_chapters"))
    # Allinea il calcolo a /api/optimize_estimate e /api/optimize: i capitoli
    # gia' ottimizzati non vengono rilavorati e non vanno addebitati, altrimenti
    # la capture PayPal supererebbe il costo reale del job.
    already = set(job.get("optimized_chapters", []))
    if selected_chapters:
        total_chars = sum(ch.char_count for ch in info.chapters
                          if ch.index in selected_chapters and ch.index not in already)
    else:
        total_chars = sum(ch.char_count for ch in info.chapters if ch.index not in already)
    # Floor minimo parametrico coerente con /api/optimize_estimate e /api/optimize:
    # l'importo addebitato non scende mai sotto ABM_LLM_MIN_COST_EUR quando si paga.
    # Unica fonte prezzo: payment.llm_price_eur.
    _lp = payment.llm_price_eur(total_chars)
    cost = _lp["due_eur"]
    if not _lp["requires_payment"]:
        return jsonify({"error": "Payment not required for this job"}), 400

    job["pay_receipt_kind"] = "optimization"
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


# E3 (seam admin, parte 4): paypaldebug in routes_admin_jobs.


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
    # Manutenzione attivata tra creazione ordine e approvazione: l'ordine
    # approvato non viene catturato (PayPal lo lascia scadere, nessun addebito).
    _maint = _maintenance_gate()
    if _maint is not None:
        return _maint

    # Atomic flow: idempotency + capture + amount reconciliation + store
    # serializzato da payment._capture_lock per prevenire double-capture race.
    try:
        result = payment.capture_and_store_order(order_id, job_id=job_id)
    except payment.CaptureAmountMismatchError as e:
        print(f"[paypal] AMOUNT MISMATCH order={order_id} job={job_id}: {e}")
        _log_activity(job_id, jobs.get(job_id, {}).get("original_filename", ""),
                      "PAYMENT_AMOUNT_MISMATCH", "", "", "", str(e))
        return jsonify({"error": "Payment amount mismatch (refused)"}), 400
    except payment.DuplicateJobCaptureError as e:
        # Il job ha gia' un capture incassato E consumato: il secondo ordine
        # (ri-click PayPal) non viene catturato -> si auto-annulla, nessun
        # doppio addebito. Il frontend mostra "gia' pagato".
        print(f"[paypal] DUPLICATE capture refused order={order_id} job={job_id}: {e}")
        _log_activity(job_id, jobs.get(job_id, {}).get("original_filename", ""),
                      "PAYMENT_DUPLICATE_REFUSED", "", "", "", str(e))
        # `paypal_issue`: chiave stabile per il frontend (il campo `error` e'
        # un codice grezzo, non un messaggio da mostrare all'utente).
        return jsonify({"error": "already_paid_for_job",
                        "paypal_issue": "ALREADY_PAID",
                        "detail": "This audiobook has already been paid."}), 409
    except payment.UnfundedCaptureError as e:
        # Capture PENDING non finanziata (tipicamente eCheck: addebito su conto
        # bancario che la banca del pagante puo' respingere giorni dopo). Il
        # denaro non e' sul conto e ABM eroga il servizio contestualmente al
        # pagamento: il token NON viene emesso. `retryable`: il frontend riapre
        # il checkout PayPal per far scegliere un altro strumento.
        print(f"[paypal] capture UNFUNDED order={order_id} job={job_id} "
              f"reason={e.reason or '-'} amount={e.amount_eur:.2f}")
        _log_activity(job_id, jobs.get(job_id, {}).get("original_filename", ""),
                      "PAYMENT_UNFUNDED_PENDING", "", "", "",
                      f"order={order_id} reason={e.reason or '-'} "
                      f"amount={e.amount_eur:.2f}")
        return jsonify({
            "error": "Payment not settled yet — please choose another payment "
                     "method (card or PayPal balance)",
            "paypal_issue": "UNFUNDED_PENDING",
            "paypal_pending_reason": e.reason,
            "retryable": True,
        }), 402
    except payment.PayPalCaptureRefusedError as e:
        # Ordine approvato ma capture rifiutata da PayPal (tipicamente rifiuto
        # dell'emittente della carta). L'issue e il debug_id finiscono nel log
        # attivita': senza di essi il 422 non e' diagnosticabile a posteriori.
        # `retryable`: il frontend riavvia il checkout PayPal (actions.restart)
        # per far scegliere all'utente un altro strumento di pagamento.
        print(f"[paypal] capture REFUSED order={order_id} job={job_id} "
              f"issue={e.issue or '-'} debug_id={e.debug_id or '-'} "
              f"http={e.status_code}")
        _log_activity(job_id, jobs.get(job_id, {}).get("original_filename", ""),
                      "PAYMENT_CAPTURE_REFUSED", "", "", "",
                      f"order={order_id} issue={e.issue or '-'} "
                      f"debug_id={e.debug_id or '-'} http={e.status_code}")
        return jsonify({
            "error": str(e),
            "paypal_issue": e.issue,
            "paypal_debug_id": e.debug_id,
            "retryable": e.issue in ("INSTRUMENT_DECLINED", "PAYER_ACTION_REQUIRED"),
        }), 402
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"[paypal] capture_order failed: {e}")
        return jsonify({"error": f"PayPal capture error: {e}"}), 500

    amount_eur = result["amount_eur"]
    email = result["email"]
    # Token effettivo: in caso di doppio ordine riusato (Layer A) è il capture
    # gia' incassato, non l'order_id appena approvato (mai catturato).
    effective_order_id = result.get("order_id") or order_id

    if not result.get("already_captured"):
        _log_activity(job_id, jobs.get(job_id, {}).get("original_filename", ""),
                      "PAYMENT_CAPTURED", "", "", "", "")
        # Send receipt email (non-blocking best-effort)
        if email and _smtp_available():
            try:
                _rjob = jobs.get(job_id, {})
                if job_id.startswith("vc:"):
                    _rkind = "voice_clone"
                    _rtitle = (voice_clone.get(job_id[3:]) or {}).get("name", "")
                else:
                    _rkind = _rjob.get("pay_receipt_kind") or "optimization"
                    _rtitle = getattr(_rjob.get("info"), "title", "") or _rjob.get("original_filename", "")
                _rlang = ((data.get("ui_lang") or "").strip()
                          or _rjob.get("notify_lang") or _rjob.get("browser_lang") or "en")
                _send_payment_receipt_email(effective_order_id, email, amount_eur,
                                            kind=_rkind, lang=_rlang, book_title=_rtitle,
                                            job=None if _rkind == "voice_clone" else _rjob)
            except Exception as e:
                print(f"[paypal] receipt email failed: {e}")

    return jsonify({
        "payment_token": effective_order_id,
        "amount_eur": amount_eur,
        "email": email,
        "already_captured": result.get("already_captured", False),
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
    ip = client_ip()
    purpose = (data.get("purpose") or "any")
    try:
        amount_required = float(data.get("amount_eur") or 0)
    except (ValueError, TypeError):
        amount_required = 0.0

    #  -  Rate limit check  -
    allowed, retry_after, reason = _voucher_rl_check(ip, email)
    if not allowed:
        _log_activity("", "", f"VOUCHER_ATTEMPT_BLOCKED:{reason}", "", ip, "", "")
        resp = jsonify({
            "valid": False,
            "reason": reason or "rate_limit",
            "error": "Too many attempts. Please try later.",
            "retry_after": retry_after,
        })
        resp.status_code = 429
        resp.headers["Retry-After"] = str(retry_after)
        return resp

    #  -  Validation logic  -
    outcome = "OK"
    status = 200
    body = None
    if not code or not email:
        outcome, status, body = "MISSING_FIELDS", 400, {"error": "Code and email required", "valid": False, "reason": "missing_fields"}
    elif code not in payment._vouchers:
        outcome, status, body = "NOT_FOUND", 404, {"error": "Voucher not found", "valid": False, "reason": "not_found"}
    else:
        v = payment._vouchers[code]
        remaining = _voucher_remaining(v)
        if v.get("expires_at", 0) < time.time():
            outcome, status, body = "EXPIRED", 400, {"error": "Voucher expired", "valid": False, "reason": "expired"}
        elif v.get("email", "").lower() != email:
            outcome, status, body = "EMAIL_MISMATCH", 400, {"error": "Email does not match voucher", "valid": False, "reason": "email_mismatch"}
        elif remaining < 0.01:
            outcome, status, body = "USED", 400, {"error": "Voucher fully used", "valid": False, "reason": "used"}
        elif amount_required > 0 and remaining < amount_required:
            outcome, status, body = "INSUFFICIENT", 400, {
                "valid": False,
                "reason": "insufficient",
                "error": "Voucher balance insufficient",
                "remaining_eur": remaining,
                "required_eur": amount_required,
            }
        else:
            # Saldo residuo: l'UI lo usa come "amount_eur" spendibile.
            body = {
                "valid": True,
                "payment_token": code,
                "amount_eur": remaining,
                "remaining_eur": remaining,
                "original_amount_eur": round(float(v.get("amount_eur", 0) or 0), 2),
                "expires_at": v.get("expires_at"),
                "purpose_requested": purpose,
            }

    success = (outcome == "OK")
    _voucher_rl_record_result(email, success)
    # Log in forma strutturata (usiamo i campi esistenti: voice=code masked, browser_lang=outcome)
    code_masked = (code[:4] + "...") if code else ""
    _log_activity("", "", "VOUCHER_ATTEMPT", "", ip, code_masked, outcome)
    return jsonify(body), status


@app.route("/api/gemini_estimate", methods=["POST"])
def api_gemini_estimate():
    """Stima costo Voci PREMIUM per il job corrente, capitoli selezionati."""
    import gemini_tts as _gemini_tts_mod
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id", "")
    voice_id = data.get("voice_id", "")
    selected = data.get("selected_chapters") or []
    rate = data.get("rate", "+0%")
    ui_lang = _i18n.norm_lang(data.get("lang"))

    if not _is_gemini_voice(voice_id):
        return jsonify({"error": "voice_id must be a Gemini voice"}), 400
    _gate = _premium_model_gate(voice_id)
    if _gate is not None:
        return _gate
    with _jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    info = job.get("info")
    if info is None or not getattr(info, "chapters", None):
        return jsonify({"error": "job has no chapters"}), 400

    all_chs = list(info.chapters)
    if selected:
        _by_index = {ch.index: ch for ch in all_chs}
        chs = [_by_index[i] for i in selected if i in _by_index]
    else:
        chs = all_chs
    if not chs:
        return jsonify({"error": "no chapters selected"}), 400
    # Job gia' terminale: testi spillati su disco, `ch.text` vuoto in RAM.
    # Senza rilettura la stima vale ~0 e la voce PREMIUM risulta gratis.
    chs = _pricing_chapters(job_id, job, chs)

    # Lingua: priorita` (1) override UI da "Impostazioni audio" > (2) metadata
    # libro > (3) "it". L'UI vince perche' governa anche cluster rate-log e
    # ratio chars/token: necessario per TXT (mai metadata) e per metadata errati.
    lang = ui_lang or _i18n.norm_lang(getattr(info, "language", "")) or "it"
    try:
        est = tts_engines.estimate("gemini", chs, voice_id, language=lang, rate_pct=rate)
    except Exception as e:
        return jsonify({"error": f"estimate failed: {e}"}), 500

    return jsonify({
        "chars_total": est["chars_total"],
        "audio_seconds_est": est["audio_seconds_est"],
        "estimated_audio_minutes": round(est["estimated_audio_minutes"], 1),
        "user_price_eur": est["user_price_eur"],
        "is_free": est["is_free"],
        "model_key": est["model_key"],
        "model_label": est["model_label"],
        "language": est["language"],
        "rate_step": est.get("rate_step", 0),
        "breakdown": {
            "input_tokens_est": est["input_tokens_est"],
            "output_tokens_est": est["output_tokens_est"],
            "google_cost_eur": est["google_cost_eur"],
            "margin_percent": est["margin_percent"],
        },
    })


@app.route("/api/combined_estimate", methods=["POST"])
def api_combined_estimate():
    """Stima combinata Voci PREMIUM + ottimizzazione testo AI."""
    import gemini_tts as _gemini_tts_mod
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id", "")
    voice_id = data.get("voice_id", "")
    selected = data.get("selected_chapters") or []
    ai_opt = bool(data.get("ai_opt_enabled", False))
    rate = data.get("rate", "+0%")
    ui_lang = _i18n.norm_lang(data.get("lang"))
    # Lettura opzionale del testo tra parentesi (default: rimosso): influenza il
    # conteggio chunk/caratteri e quindi la stima costo e il preflight PREMIUM.
    read_round_parens = bool(data.get("read_round_parens", False))
    read_square_brackets = bool(data.get("read_square_brackets", False))
    _gate = _premium_model_gate(voice_id)
    if _gate is not None:
        return _gate

    with _jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    info = job.get("info")
    if info is None or not getattr(info, "chapters", None):
        return jsonify({"error": "no chapters"}), 400

    all_chs = list(info.chapters)
    if selected:
        _by_index = {ch.index: ch for ch in all_chs}
        chs = [_by_index[i] for i in selected if i in _by_index]
    else:
        chs = all_chs
    if not chs:
        return jsonify({"error": "no chapters"}), 400
    # Job gia' terminale: testi spillati su disco, `ch.text` vuoto in RAM.
    # Senza rilettura la stima vale ~0 e la voce PREMIUM risulta gratis.
    chs = _pricing_chapters(job_id, job, chs)

    # Lingua: priorita` (1) override UI da "Impostazioni audio" > (2) metadata
    # libro > (3) "it". L'UI vince perche' governa anche cluster rate-log e
    # ratio chars/token: necessario per TXT (mai metadata) e per metadata errati.
    lang = ui_lang or _i18n.norm_lang(getattr(info, "language", "")) or "it"

    gemini_eur = 0.0
    gemini_breakdown = {}
    rate_step = 0
    _premium_list_eur = 0.0
    if _is_gemini_voice(voice_id):
        try:
            est = tts_engines.estimate("gemini", chs, voice_id, language=lang, rate_pct=rate)
        except Exception as e:
            return jsonify({"error": f"estimate failed: {e}"}), 500
        gemini_eur = round(est["user_price_eur"], 2)
        _premium_list_eur = round(est.get("list_price_eur", 0.0), 2)
        rate_step = est.get("rate_step", 0)
        gemini_breakdown = {
            "chars": est["chars_total"],
            "audio_minutes": round(est["estimated_audio_minutes"], 1),
            "google_cost_eur": est["google_cost_eur"],
            "model_label": est["model_label"],
            "rate_step": rate_step,
        }

    speechify_eur = 0.0
    speechify_breakdown = {}
    if _is_speechify_voice(voice_id):
        try:
            est_spx = tts_engines.estimate("speechify", chs, language="en")
        except Exception as e:
            return jsonify({"error": f"estimate failed: {e}"}), 500
        speechify_eur = round(est_spx["user_price_eur"], 2)
        _premium_list_eur = round(est_spx.get("list_price_eur", 0.0), 2)
        speechify_breakdown = {
            "chars": est_spx["chars_total"],
            "chars_total": est_spx["chars_total"],
            "user_price_eur": est_spx["user_price_eur"],
            "is_free": est_spx["is_free"],
            "model_label": est_spx["model_label"],
            "margin_percent": est_spx["margin_percent"],
        }

    voxcpm_eur = 0.0
    voxcpm_breakdown = {}
    if _is_voxcpm_voice(voice_id):
        try:
            est_vox = tts_engines.estimate("voxcpm", chs, language=lang)
        except Exception as e:
            return jsonify({"error": f"estimate failed: {e}"}), 500
        # list_price_eur, non user_price_eur: quest'ultimo e' gia' azzerato da
        # voxcpm_tts se sotto la SUA soglia interna (stesso env var letto due
        # volte). "voxcpm_eur" qui e' il prezzo di listino esposto in stima;
        # l'unico punto che decide se e' gratis o no e' free_quota piu' sotto
        # (is_free/total_eur), non questo campo.
        # ATTENZIONE UI: il frontend deve renderizzare da `total_eur`/`is_free`
        # nella risposta JSON, MAI da `voxcpm_eur` — qui e' listino grezzo, non
        # il dovuto (puo' restare > 0 anche quando il job e' gratuito).
        voxcpm_eur = round(est_vox.get("list_price_eur", 0.0), 2)
        _premium_list_eur = round(est_vox.get("list_price_eur", 0.0), 2)
        voxcpm_breakdown = {
            "chars": est_vox["chars_total"],
            "chars_total": est_vox["chars_total"],
            "user_price_eur": est_vox["user_price_eur"],
            "is_free": est_vox["is_free"],
            "model_label": est_vox["model_label"],
            # Il costo GPU misurato (§8.3) viaggia con la stima perche' e'
            # quello che l'audit del Task 11 confronta col listino.
            "cost_usd": est_vox["cost_usd"],
        }

    # Quota ottimizzazione AI: sul ramo STANDALONE (voce standard, nessun
    # PREMIUM) l'importo mostrato DEVE applicare il floor minimo, come fanno
    # ordine PayPal/voucher/addebito. Sul ramo PREMIUM combinato la quota LLM
    # resta grezza (si somma al TTS, il pagamento e' del totale). Unica fonte:
    # payment.llm_price_eur (incidente stima 0,48 vs addebito 1,00).
    _has_premium = (_is_gemini_voice(voice_id) or _is_speechify_voice(voice_id)
                    or _is_voxcpm_voice(voice_id))
    llm_eur = 0.0
    llm_breakdown = {}
    if ai_opt:
        chars = sum(len(getattr(c, "text", "") or "") for c in chs)
        _lp = payment.llm_price_eur(chars, is_combined=_has_premium)
        llm_eur = _lp["due_eur"]
        llm_breakdown = {
            "chars": chars,
            "rate_eur_per_mchar": _lp["rate_eur_per_mchar"],
            "raw_eur": _lp["raw_eur"],
            "floored": _lp["floored"],
        }

    total = round(gemini_eur + speechify_eur + voxcpm_eur + llm_eur, 2)
    # Quota gratuita cumulativa per client: sul listino (TTS premium + quota LLM
    # combinata), non sul prezzo gia' azzerato sotto soglia. Sola lettura: qui
    # non si consuma nulla.
    _quota_dec = None
    _quota_cid = _quota_client_id(job)
    if _has_premium:
        _quota_dec = _premium_quota_decision(
            _quota_cid, voice_id, round(_premium_list_eur + llm_eur, 2),
            _free_quota_key(job_id, voice_id, chs, getattr(info, "chapters", None)),
            book_chars=_free_quota_book_chars(info),
            language=lang,
        )
        total = _quota_dec["due_eur"]
        # Quote lock (D2): l'importo che l'utente sta per vedere nel modale e'
        # quello con cui verra' creato l'ordine PayPal, anche se nel frattempo
        # il rate empirico si muove (tipicamente per le anteprime audio che
        # l'utente ascolta proprio adesso). Vedi _quote_lock_store.
        _quote_lock_store(
            job,
            _pricing_signature(voice_id, [getattr(ch, "index", None) for ch in chs],
                               rate, lang, ai_opt),
            total,
        )
    # Soglia gratuita coerente con l'engine premium attivo: /api/generate applica
    # ABM_SPEECHIFY_FREE_THRESHOLD_EUR sul ramo Speechify e
    # ABM_GEMINI_FREE_THRESHOLD_EUR altrove. Se qui usassimo sempre quella Gemini,
    # un totale Speechify compreso tra le due soglie (soglia Speechify < Gemini)
    # risulterebbe is_free lato UI ma verrebbe respinto con 402 dal backend, con il
    # job bloccato a 0% (nessun payment token inviato). Vedi incidente 402 Speechify.
    if _is_voxcpm_voice(voice_id):
        threshold = free_quota._premium_threshold_eur(voice_id)
    elif _is_speechify_voice(voice_id):
        threshold = speechify_tts.free_threshold_eur()
    elif _is_gemini_voice(voice_id):
        threshold = gemini_tts.FREE_THRESHOLD_EUR if gemini_tts is not None else 0.50
    else:
        # Ottimizzazione AI standalone (voce standard): la gratuita' e' governata
        # dalla soglia LLM, non da quella PREMIUM, coerente con l'addebito reale
        # (/api/optimize usa LLM_FREE_THRESHOLD_EUR). Il floor rende due binario
        # (grezzo<=soglia oppure >=MIN_COST), quindi is_free riflette il pagamento.
        threshold = LLM_FREE_THRESHOLD_EUR

    # Pre-flight RPD check ANTICIPATO (prima ancora di proporre il pagamento).
    # Cosi' l'utente che ha selezionato una voce PREMIUM saturata vede subito
    # l'avviso "non disponibile" senza passare per il flusso pagamento/PayPal.
    overload_info = None
    if _is_gemini_voice(voice_id):
        try:
            _max_chars_cb = _pick_chunk_max_chars(voice_id, lang)
            _max_bytes_cb = _pick_chunk_max_bytes(voice_id)
            class _PlanInfoCB:
                pass
            _pi = _PlanInfoCB()
            _pi.chapters = chs
            _plan_cb = _plan_chunks(_pi, max_chars=_max_chars_cb, max_bytes=_max_bytes_cb,
                                    strip_round=not read_round_parens,
                                    strip_square=not read_square_brackets)
            _total_chunks_cb = len(_plan_cb)
            _parts_cb = voice_id.split(":")
            _model_key_cb = _parts_cb[1] if len(_parts_cb) >= 3 else "flash31"
            _pf_cb = _gemini_tts_mod.preflight_can_run(_model_key_cb, _total_chunks_cb)
            if not _pf_cb.get("ok"):
                overload_info = {
                    "model_key": _model_key_cb,
                    "retry_after_sec": int(_pf_cb.get("retry_after_sec") or 0),
                    "needed": _pf_cb.get("needed"),
                    "available": _pf_cb.get("available"),
                }
                print(f"[{job_id}] combined_estimate: gemini_overloaded "
                      f"[{_model_key_cb}] needed={_pf_cb.get('needed')} "
                      f"available={_pf_cb.get('available')}")
        except Exception as _ce_pf_err:
            print(f"[{job_id}] combined_estimate preflight error (non-fatal): {_ce_pf_err}")

    return jsonify({
        "gemini_eur": gemini_eur,
        "speechify_eur": speechify_eur,
        "voxcpm_eur": voxcpm_eur,
        "llm_eur": llm_eur,
        "total_eur": total,
        "is_free": _quota_dec["is_free"] if _quota_dec else (total <= threshold),
        "quota_exhausted": bool(_quota_dec and _quota_dec["quota_exhausted"]),
        # Libro sopra il cap della gratuita' (solo VoxCPM, vedi
        # free_quota._premium_free_max_chars): il totale e' il floor per
        # generazione, non il listino, e la quota mensile puo' essere ancora
        # capiente. Senza questo flag l'UI mostra un importo senza causa
        # (richiesta di assistenza del 21/09/2026).
        "free_cap_exceeded": bool(_quota_dec and _quota_dec.get("free_cap_exceeded")),
        "free_quota": free_quota.snapshot(_quota_cid) if _has_premium else None,
        "threshold_eur": threshold,
        "rate_step": rate_step,
        "gemini_breakdown": gemini_breakdown,
        "speechify_breakdown": speechify_breakdown,
        "voxcpm_breakdown": voxcpm_breakdown,
        "llm_breakdown": llm_breakdown,
        "gemini_overloaded": overload_info is not None,
        "gemini_overload_info": overload_info,
        "paypal_available": _paypal_available(),
        "paypal_client_id": PAYPAL_CLIENT_ID if _paypal_available() else "",
        "paypal_mode": PAYPAL_MODE,
    })


@app.route("/api/paypal_create_order_gemini", methods=["POST"])
def api_paypal_create_order_gemini():
    """Create a PayPal order for Voci PREMIUM (+ optional AI text optimization).

    Server-side amount check: recomputes the combined estimate
    (gemini_eur + llm_eur) and rejects the request if the client-supplied
    amount differs by more than 0.01 EUR. On match, calls
    payment._paypal_create_order and returns {order_id, amount, status}.
    """
    import payment as _payment_mod
    import gemini_tts as _gemini_tts_mod

    _maint = _maintenance_gate()
    if _maint is not None:
        return _maint
    data = request.get_json(silent=True) or {}
    job_id = (data.get("job_id") or "").strip()
    voice_id = (data.get("voice_id") or "").strip()
    selected = data.get("selected_chapters") or []
    ai_opt = bool(data.get("ai_opt_enabled", False))
    rate = data.get("rate", "+0%")
    ui_lang = _i18n.norm_lang(data.get("lang"))
    try:
        requested_amount = float(data.get("amount_eur") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid amount_eur"}), 400
    # Nessun ordine PayPal per un modello PREMIUM spento: il gate sta prima
    # della creazione dell'ordine, cosi' non si incassa per un servizio che
    # /api/generate rifiuterebbe.
    _gate = _premium_model_gate(voice_id)
    if _gate is not None:
        return _gate

    # Sec: solo il proprietario del job (o l'admin) puo' aprire un ordine su
    # di esso, come per ogni altra route che legge jobs[job_id].
    job, _err, _sc = _check_job_owner(job_id)
    if _err is not None:
        return _err, _sc

    # Server saturo: nessun ordine PayPal viene creato. Il gate esiste anche in
    # /api/generate prima del preflight, ma la capacita` puo` esaurirsi mentre
    # il modale di pagamento e` gia` aperto.
    _busy = _server_busy_response(job_id, "/api/paypal_create_order_gemini",
                                  premium=True)
    if _busy is not None:
        return _busy

    info = job.get("info")
    if info is None or not getattr(info, "chapters", None):
        return jsonify({"error": "no chapters"}), 400

    all_chs = list(info.chapters)
    if selected:
        _by_index = {ch.index: ch for ch in all_chs}
        chs = [_by_index[i] for i in selected if i in _by_index]
    else:
        chs = all_chs
    if not chs:
        return jsonify({"error": "no chapters"}), 400
    # Job gia' terminale: testi spillati su disco, `ch.text` vuoto in RAM.
    # Senza rilettura la stima vale ~0 e la voce PREMIUM risulta gratis.
    chs = _pricing_chapters(job_id, job, chs)

    # Cap caratteri PRIMA di creare l'ordine PayPal. Un libro che supera il cap
    # della voce PREMIUM (MAX_GEMINI_TEXT_CHARS, default 800k) non potra` mai
    # essere generato da /api/generate (cap a riga ~6448), quindi NON deve
    # nemmeno arrivare a creare/catturare un ordine: altrimenti l'utente paga
    # e il job viene poi rifiutato senza che il denaro sia stato consumato.
    _max_chars_voice = _effective_max_text_chars(voice_id, job)
    _sel_chars_voice = sum(getattr(ch, "char_count", 0) for ch in chs)
    if _sel_chars_voice > _max_chars_voice:
        return jsonify({
            "error": f"Selection too large: {_sel_chars_voice:,} characters "
                     f"(limit {_max_chars_voice:,}). Please reduce the chapter selection.",
            "error_code": "selection_too_large",
            "chars_selected": _sel_chars_voice,
            "chars_limit": _max_chars_voice,
        }), 413

    # Lingua: stessa priorita` di /api/combined_estimate (UI > metadata > "it").
    # Deve essere identica per evitare amount mismatch sul server-side check.
    lang = ui_lang or _i18n.norm_lang(getattr(info, "language", "")) or "it"

    gemini_eur = 0.0
    _premium_list_eur = 0.0
    if _is_gemini_voice(voice_id):
        try:
            # rate_pct: la stima dipende dalla velocità scelta, quindi va
            # passata anche qui per coerenza con /api/combined_estimate.
            est = tts_engines.estimate("gemini", chs, voice_id, language=lang, rate_pct=rate)
        except Exception as e:
            return jsonify({"error": f"estimate failed: {e}"}), 500
        gemini_eur = round(est["user_price_eur"], 2)
        _premium_list_eur = round(est.get("list_price_eur", 0.0), 2)

    speechify_eur = 0.0
    if _is_speechify_voice(voice_id):
        try:
            est = tts_engines.estimate("speechify", chs, language="en")
        except Exception as e:
            return jsonify({"error": f"estimate failed: {e}"}), 500
        speechify_eur = round(est["user_price_eur"], 2)
        _premium_list_eur = round(est.get("list_price_eur", 0.0), 2)

    voxcpm_eur = 0.0
    if _is_voxcpm_voice(voice_id):
        try:
            # `lang` gia' risolto sopra (UI > metadata > "it"), stessa
            # priorita' di /api/combined_estimate: necessario per non
            # produrre un amount mismatch server-side (Fix round 1).
            est = tts_engines.estimate("voxcpm", chs, language=lang)
        except Exception as e:
            return jsonify({"error": f"estimate failed: {e}"}), 500
        voxcpm_eur = round(est["user_price_eur"], 2)
        _premium_list_eur = round(est.get("list_price_eur", 0.0), 2)

    _has_premium = (_is_gemini_voice(voice_id) or _is_speechify_voice(voice_id)
                    or _is_voxcpm_voice(voice_id))
    llm_eur = 0.0
    if ai_opt:
        chars = sum(len(getattr(c, "text", "") or "") for c in chs)
        # is_combined solo se e' presente una voce PREMIUM (allineato a
        # /api/combined_estimate): con voce standard la quota LLM e' standalone
        # e applica il floor. Fonte unica payment.llm_price_eur, cosi' il
        # server-side amount check non produce falsi mismatch.
        llm_eur = payment.llm_price_eur(chars, is_combined=_has_premium)["due_eur"]

    server_total = round(gemini_eur + speechify_eur + voxcpm_eur + llm_eur, 2)
    # Stesso punto di decisione di /api/combined_estimate: l'ordine PayPal deve
    # valere esattamente l'importo che il client ha visto (e che /api/generate
    # pretendera'), quota gratuita inclusa.
    if _has_premium:
        server_total = _premium_quota_decision(
            _quota_client_id(job), voice_id,
            round(_premium_list_eur + llm_eur, 2),
            _free_quota_key(job_id, voice_id, chs, getattr(info, "chapters", None)),
            book_chars=_free_quota_book_chars(info),
            language=lang,
        )["due_eur"]

    # Quote lock (D2): se il client chiede esattamente l'importo che gli e'
    # stato quotato dall'ultima stima con gli stessi input di prezzo, quello e'
    # il dovuto. La deriva della media mobile empirica fra la stima e il click
    # su PayPal non e' un problema dell'utente — e in buona parte la provoca lui
    # stesso ascoltando le anteprime. Vedi _quote_lock_store.
    _sig_order = _pricing_signature(
        voice_id, [getattr(ch, "index", None) for ch in chs], rate, lang, ai_opt)
    _quoted = _quote_lock_lookup(job, _sig_order)
    if (_quoted is not None
            and abs(_quoted - requested_amount) <= 0.01
            and abs(server_total - requested_amount) > 0.01):
        print(f"[{job_id}] quote lock: dovuto {server_total:.2f}EUR -> "
              f"{_quoted:.2f}EUR (quotato alla stima, firma invariata)", flush=True)
        server_total = _quoted

    if abs(server_total - requested_amount) > 0.01:
        # Prezzo davvero cambiato: input diversi da quelli quotati, oppure lock
        # scaduto. 409 + importo aggiornato, cosi' il client rinfresca la stima e
        # ripropone il pagamento invece di mostrare un errore incomprensibile.
        return jsonify({
            "error": f"amount mismatch (server={server_total}, client={requested_amount})",
            "error_code": "price_changed",
            "server_amount_eur": server_total,
            "client_amount_eur": requested_amount,
        }), 409

    # Servizio pagato, per la ricevuta email inviata alla capture.
    job["pay_receipt_kind"] = (("premium_opt" if llm_eur > 0 else "premium")
                               if _has_premium else "optimization")
    book_title = getattr(info, "title", "") or "Audiobook"
    description = f"Audiobook Maker - Voci PREMIUM - {book_title[:60]}"
    try:
        order = _payment_mod._paypal_create_order(
            amount_eur=server_total,
            description=description,
            custom_id=f"gemini:{job_id}",
        )
    except Exception as e:
        print(f"[paypal] gemini create_order failed: {e}")
        return jsonify({"error": f"paypal create failed: {e}"}), 500

    # Price lock (D1): l'importo appena quotato resta il dovuto per questo
    # ordine anche se la stima empirica si muove prima della conferma. Vedi
    # _price_lock_store per il razionale completo.
    _order_id = (order.get("id") or "").strip()
    if _order_id:
        _price_lock_store(
            job, _order_id,
            _pricing_signature(voice_id, [getattr(ch, "index", None) for ch in chs],
                               rate, lang, ai_opt),
            server_total,
        )

    return jsonify({
        "order_id": order.get("id"),
        "amount": server_total,
        "status": order.get("status"),
    })


@app.route("/api/paypal_create_order_translate", methods=["POST"])
def api_paypal_create_order_translate():
    """Create a PayPal order for a book translation (+ optional AI optimization).

    Identica a /api/paypal_create_order salvo l'importo, calcolato sui caratteri
    selezionati via payment._estimate_translation_cost_eur. La cattura resta
    /api/paypal_capture_order.
    """
    if not _paypal_available():
        return jsonify({"error": "PayPal not configured"}), 503
    _maint = _maintenance_gate()
    if _maint is not None:
        return _maint
    data = request.json or {}
    job_id = data.get("job_id", "")
    # Sec: solo il proprietario del job (o l'admin) puo' aprire un ordine su
    # di esso, come per ogni altra route che legge jobs[job_id].
    job, _err, _sc = _check_job_owner(job_id)
    if _err is not None:
        return _err, _sc
    info = job.get("info")
    if not info:
        return jsonify({"error": "No book data"}), 400

    raw_sel = [str(x) for x in (data.get("selected_chapters") or [])]
    optimize = bool(data.get("optimize"))
    chars, _ = _translate_selected_chars(job, raw_sel)
    est = payment._estimate_translation_cost_eur(chars, optimize=optimize)
    amount_eur = est["due_eur"]
    if not amount_eur or amount_eur <= 0:
        return jsonify({"error": "No payment required"}), 400

    job["pay_receipt_kind"] = "translation_opt" if optimize else "translation"
    book_title = getattr(info, "title", "") or "Audiobook"
    description = f"Book translation  -  {book_title[:60]}"
    try:
        order = _paypal_create_order(amount_eur, description, custom_id=job_id)
    except Exception as e:
        print(f"[paypal] translate create_order failed: {e}")
        return jsonify({"error": f"PayPal error: {e}"}), 500

    return jsonify({
        "order_id": order.get("id"),
        "amount_eur": amount_eur,
        "status": order.get("status"),
    })


@app.route("/api/optimize", methods=["POST"])
def api_optimize():
    if not _llm_available(): return jsonify({"error": "LLM optimization not available"}), 503
    data = request.json or {}; job_id = data.get("job_id"); batch = data.get("batch", False); auto_generate = data.get("auto_generate", False); email = (data.get("email") or "").strip().lower()
    lang = data.get("lang")
    _voice_in = data.get("voice") or ""
    if _voice_in and not _VOICE_ID_RE.match(_voice_in):
        return jsonify({"error": "Invalid voice id.",
                        "error_code": "invalid_voice"}), 400
    # La voce arriva qui per il ramo auto-generate: se il modello PREMIUM e'
    # spento, meglio rifiutare subito che far pagare l'ottimizzazione e
    # inciampare poi in /api/generate.
    _gate = _premium_model_gate(_voice_in)
    if _gate is not None:
        return _gate
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        if sc == 404:
            return jsonify({"error": "Session expired"}), 400
        return err, sc
    info = job.get("info")

    # Check sospensione nuovi processi (admin toggle)
    if _suspend_new_jobs:
        return jsonify({"error": "System under maintenance. Please try again in a few minutes."}), 503

    # Lingua TTS selezionata in UI: e' la fonte autoritativa per scegliere
    # il prompt LLM (prompt_tts_<lang>.md), perche' l'ottimizzazione deve
    # produrre testo adatto alla voce TTS scelta, non alla lingua dell'input.
    # Es: input EN ottimizzato per voce IT -> serve prompt_tts_it.md.
    if lang:
        job["opt_lang"] = (lang.split("-")[0] or "").lower() or None

    client_id = job.get("client_id", "")
    # Atomic concurrency check + status claim for optimization
    with _jobs_lock:
        if job["status"] not in ("analyzed",):
            return jsonify({"error": "Optimization already running or completed."}), 400
        if client_id and MAX_CONCURRENT_LLM_PER_CLIENT > 0:
            if _active_optimizing_for_client_unlocked(client_id) >= MAX_CONCURRENT_LLM_PER_CLIENT:
                return jsonify({
                    "error": f"Concurrent optimization limit reached ({MAX_CONCURRENT_LLM_PER_CLIENT}).",
                    "error_code": "concurrent_optimize_limit",
                    "max": MAX_CONCURRENT_LLM_PER_CLIENT,
                    "active": _active_optimizing_for_client_unlocked(client_id),
                }), 429
        job["status"] = "optimizing"

    def _release_opt_claim():
        # Rilascia lo status claim "optimizing" sui return di errore PRIMA
        # dell'avvio del thread: senza release il job resta brickato (il
        # check atomico sopra respinge ogni retry con "already running"),
        # quindi l'utente non potrebbe ritentare dopo aver pagato.
        with _jobs_lock:
            if job.get("status") == "optimizing":
                job["status"] = "analyzed"

    # Tetto generazioni contemporanee, anticipato al wizard combinato.
    # Con auto_generate la generazione parte da run_optimization chiamando
    # run_generation direttamente, senza passare da /api/generate: senza
    # questo controllo il tetto per-client era semplicemente inesistente su
    # quel percorso. Va valutato PRIMA di incassare qualunque pagamento, e
    # solo per la corsia gratuita (chi paga non ha tetto).
    if auto_generate and client_id:
        _auto_voice = data.get("voice", "")
        _auto_premium = (_is_gemini_voice(_auto_voice)
                         or _is_speechify_voice(_auto_voice)
                         or generation_engine.is_premium_job(job))
        if not _auto_premium:
            _capped, _active_gen, _cap = _client_gen_cap_reached(client_id, job_id)
            if _capped:
                _release_opt_claim()
                return jsonify({
                    "error": f"Concurrent generation limit reached ({_cap}).",
                    "error_code": "concurrent_limit",
                    "max": _cap,
                    "active": _active_gen,
                }), 429

    raw_selected = data.get("selected_chapters")
    selected_chapters = _parse_selected_chapters(raw_selected)
    already = set(job.get("optimized_chapters", []))
    if selected_chapters:
        chapters_to_optimize = [idx for idx in selected_chapters if idx not in already]
    else:
        chapters_to_optimize = [ch.index for ch in info.chapters if ch.index not in already] if info else []
    total_chars = sum(ch.char_count for ch in info.chapters if ch.index in chapters_to_optimize)
    print(f"[{job_id}] OPTIMIZE raw selected_chapters: {raw_selected!r} -> parsed: {selected_chapters!r} -> to_optimize: {chapters_to_optimize!r}")
    if not chapters_to_optimize:
        # Nulla da ottimizzare (tutto gia' fatto): rilascia il claim
        # "optimizing" altrimenti il job resta brickato e i retry vengono
        # respinti con "already running" (stessa classe dei 402 sotto).
        _release_opt_claim()
        return jsonify({"status": "already_optimized", "optimized_chapters": list(already)})

    # Hard cap on text size for the final audio output, applied to the full
    # selected set (already-optimized + to-optimize). Blocks early so the
    # user doesn't pay for LLM optimization on a selection that cannot be
    # rendered to audio. Per auto_generate con voce PREMIUM si applica il
    # cap MAX_GEMINI_TEXT_CHARS (piu' restrittivo).
    max_text_chars = _max_text_chars_for_voice(data.get("voice", ""))
    if info is not None:
        if selected_chapters:
            selected_set_for_cap = set(selected_chapters)
        else:
            selected_set_for_cap = {ch.index for ch in info.chapters}
        selected_chars_total = sum(
            ch.char_count for ch in info.chapters if ch.index in selected_set_for_cap
        )
        if selected_chars_total > max_text_chars:
            # Release the "optimizing" status claimed above so the user can
            # retry with a smaller selection.
            with _jobs_lock:
                if job.get("status") == "optimizing":
                    job["status"] = "analyzed"
            return jsonify({
                "error": f"Selection too large: {selected_chars_total:,} characters "
                         f"(limit {max_text_chars:,}). Please reduce the chapter selection.",
                "error_code": "selection_too_large",
                "chars_selected": selected_chars_total,
                "chars_limit": max_text_chars,
            }), 413
    # Stessa guardia lingua di /api/generate, qui perche' il wizard combinato
    # paga QUESTA chiamata e poi genera da run_optimization, senza passare da
    # /api/generate: senza il controllo qui, il percorso piu' caro sarebbe
    # anche l'unico scoperto. Va prima di ogni consumo di pagamento, e deve
    # rilasciare il claim "optimizing" o il job resta brickato.
    _vl = _language_mismatch_response(job, job_id, _voice_in, lang,
                                      selected_chapters, data)
    if _vl is not None:
        _release_opt_claim()
        return _vl

    # Notifica forzata: con sessione attiva il job e' sempre batch sull'email
    # dell'account, qualunque cosa dica il body.
    batch, email = _acct_forced_batch(batch, email)
    # Batch mode validation (email + SMTP) — eseguita PRIMA di qualsiasi
    # consumo di pagamento (sia branch LLM standalone che combined-gemini):
    # un'email invalida o SMTP assente non deve mai lasciare un pagamento
    # consumato (stranded). L'assegnazione dei campi notify resta piu' sotto,
    # dopo il pagamento andato a buon fine.
    if batch:
        if not email or not _ACCT_EMAIL_RE.match(email):
            with _jobs_lock:
                if job.get("status") == "optimizing":
                    job["status"] = "analyzed"
            return jsonify({"error": "Valid email required for batch mode"}), 400
        if not _smtp_available():
            with _jobs_lock:
                if job.get("status") == "optimizing":
                    job["status"] = "analyzed"
            return jsonify({"error": "Email service not configured on this server"}), 503

    estimated_cost = _estimate_llm_cost_eur(total_chars)
    # Flusso combinato (auto_generate + voce Gemini): il payment_token
    # copre sia LLM che Gemini. Il branch standalone LLM sotto NON deve
    # consumarlo per la sola quota LLM — la gestione e` delegata al
    # blocco "Combined payment" piu` avanti.
    _is_combined_gemini = (auto_generate
                           and _is_gemini_voice(data.get("voice", ""))
                           and gemini_tts is not None)
    # Idem per le voci PREMIUM Speechify (Simba): il flusso auto_generate chiama
    # run_generation direttamente, bypassando il preflight pagamento di
    # /api/generate (dove il TTS Simba viene addebitato). Senza un enforcement
    # QUI, ogni audiolibro Speechify prodotto dal wizard con costo LLM sotto
    # soglia veniva erogato SENZA incassare la quota TTS (margine negativo).
    _is_combined_speechify = (auto_generate
                              and _is_speechify_voice(data.get("voice", ""))
                              and speechify_tts.is_available())
    # Stessa ragione del ramo Speechify sopra: il flusso auto_generate chiama
    # run_generation direttamente e salta il preflight di /api/generate. Questo
    # flag sopprime SOLO il gate standalone-LLM qui sotto: l'addebito vero e
    # proprio (TTS VoxCPM + LLM) avviene nel blocco "Combined payment (LLM +
    # VoxCPM in auto_generate flow)" piu' sotto (mirror del ramo Speechify).
    # Prima di quel blocco, `_is_combined_voxcpm=True` senza un charge a valle
    # lasciava passare un job VoxCPM gratis (ne' LLM ne' TTS incassati) — vedi
    # task-10-report.md "Fix round 1".
    _is_combined_voxcpm = (auto_generate
                           and _is_voxcpm_voice(data.get("voice", ""))
                           and voxcpm_tts is not None
                           and voxcpm_tts.is_available())
    if (estimated_cost > LLM_FREE_THRESHOLD_EUR
            and not _is_combined_gemini and not _is_combined_speechify
            and not _is_combined_voxcpm):
        # Importo effettivo dovuto per l'ottimizzazione standalone: floor minimo
        # parametrico (ABM_LLM_MIN_COST_EUR). `estimated_cost` resta grezzo perche'
        # il ramo combinato piu' sotto lo somma alla quota TTS senza floor.
        # Unica fonte prezzo: payment.llm_price_eur (coerente con stima/ordine).
        _due = payment.llm_price_eur(total_chars)["due_eur"]
        payment_token = (data.get("payment_token") or "").strip()
        if not payment_token:
            _release_opt_claim()
            return jsonify({
                "error": "Payment required for this optimization.",
                "error_code": "payment_required",
                "estimated_cost_eur": _due,
                "chars": total_chars,
            }), 402
        # Validate payment_token (PayPal order_id or voucher code).
        # Sec: check-and-set atomico sotto lock per impedire doppio uso del medesimo token
        # da parte di richieste concorrenti. La persistenza su disco avviene fuori dal lock
        # perché _save_payments() riacquisisce _payments_lock (non rientrante).
        valid = False
        if payment_token in payment._payments:
            _claimed_pay = None
            with payment._payments_lock:
                pay = payment._payments.get(payment_token)
                if pay and not pay.get("used") and pay.get("amount_eur", 0) >= _due:
                    pay["used"] = True
                    pay["used_at"] = time.time()
                    pay["used_job_id"] = job_id
                    _claimed_pay = pay
            if _claimed_pay is not None:
                _save_payments()
                job["payment_token"] = payment_token
                job["payment_type"] = "paypal"
                job["payment_email"] = _claimed_pay.get("email", "")
                job["payment_amount_eur"] = _claimed_pay.get("amount_eur", 0)
                valid = True
        elif payment_token in payment._vouchers:
            v = payment._vouchers[payment_token]
            remaining = _voucher_remaining(v)
            if v.get("expires_at", 0) > time.time() and remaining >= _due - 0.01:
                try:
                    new_remaining = _voucher_consume(payment_token, _due, job_id=job_id)
                except ValueError as _ve:
                    _release_opt_claim()
                    return jsonify({
                        "error": f"Voucher not spendable: {_ve}",
                        "error_code": "invalid_payment",
                    }), 402
                job["payment_token"] = payment_token
                job["payment_type"] = "voucher"
                job["payment_email"] = v.get("email", "")
                job["payment_amount_eur"] = round(float(_due), 2)
                job["voucher_remaining_after"] = new_remaining
                valid = True
        if not valid:
            _release_opt_claim()
            return jsonify({
                "error": "Invalid or already-used payment token.",
                "error_code": "invalid_payment",
            }), 402

    # ----- Combined payment (LLM + Gemini in auto_generate flow) -----
    # Il flusso combinato usa UN unico token (PayPal order o voucher) che
    # copre entrambe le quote LLM + Gemini. Il branch standalone LLM sopra
    # e` stato saltato (_is_combined_gemini=True), quindi gestiamo il
    # consumo qui per l'intero ammontare. Vedi md_files/ttsgemini.md.
    if _is_combined_gemini:
        _combined_token = (data.get("payment_token_combined")
                           or data.get("payment_token") or "").strip()
        # Ricalcolo quota Gemini server-side per validare l'importo.
        # Eseguito SEMPRE (anche senza token): l'enforcement del pagamento
        # combinato deve avvenire QUI perche' il flusso auto-gen chiama
        # run_generation direttamente, bypassando il preflight pagamento
        # di /api/generate. Storicamente questo blocco era annidato dentro
        # `if _combined_token:` -> una richiesta senza token partiva gratis.
        _voice_for_est = data.get("voice", "")
        _rate_for_est = data.get("rate", "+0%")
        _ui_lang_for_est = _i18n.norm_lang(lang) if lang else ""
        _lang_for_est = (_ui_lang_for_est
                         or _i18n.norm_lang(getattr(info, "language", ""))
                         or "it")
        # Capitoli selezionati per la generazione (stessa logica frontend
        # combined_estimate: subset se selected_chapters, altrimenti tutti).
        _all_chs = list(getattr(info, "chapters", []) or [])
        _sel_list = _parse_selected_chapters(data.get("selected_chapters"))
        if _sel_list:
            _by_idx = {ch.index: ch for ch in _all_chs}
            _chs_for_est = [_by_idx[i] for i in _sel_list if i in _by_idx]
        else:
            _chs_for_est = _all_chs
        # Job gia' terminale: testi spillati su disco, `ch.text` vuoto in
        # RAM. Senza rilettura la stima vale ~0 (voce PREMIUM gratis).
        _chs_for_est = _pricing_chapters(job_id, job, _chs_for_est)
        try:
            _est_gemini = tts_engines.estimate("gemini", 
                _chs_for_est, _voice_for_est,
                language=_lang_for_est, rate_pct=_rate_for_est,
            )
            _gemini_eur_quota = round(_est_gemini.get("user_price_eur", 0.0), 2)
            _gemini_list_quota = round(_est_gemini.get("list_price_eur", 0.0), 2)
        except Exception as _e_est:
            # FAIL-CLOSED. Azzerare la stima qui mandava il listino sotto
            # soglia -> la voce PREMIUM partiva GRATIS (stesso esito
            # dell'incidente Q9lQN3RrapCvGLSonVnzmA). /api/generate rifiuta
            # gia' in questo caso: qui allineato.
            print(f"[{job_id}] combined-payment estimate failed: {_e_est}", flush=True)
            _release_opt_claim()
            return jsonify({"error": "Cost estimate unavailable, please retry.",
                            "error_code": "estimate_failed"}), 500
        # Quota gratuita cumulativa sul LISTINO combinato (TTS + LLM).
        _quota_cid = _quota_client_id(job)
        _fq_key_gem = _free_quota_key(job_id, _voice_for_est, _chs_for_est, _all_chs)
        _quota_dec = _premium_quota_decision(
            _quota_cid, _voice_for_est,
            round(_gemini_list_quota + estimated_cost, 2), _fq_key_gem,
            book_chars=_free_quota_book_chars(info, _all_chs),
        )
        _expected_total = _quota_dec["due_eur"]
        _threshold_combined = _quota_dec["threshold_eur"]
        # Price lock (D1): se il token e' un ordine PayPal creato per QUESTO
        # job con gli stessi input di prezzo, il dovuto e' l'importo quotato al
        # create, non quello ricalcolato adesso. Senza lock la deriva della
        # media mobile empirica fra pagamento e conferma manda in 402 un utente
        # che ha gia' pagato, lasciando la capture orfana.
        if not _quota_dec["is_free"] and _combined_token:
            _sig_combined = _pricing_signature(
                _voice_for_est, [getattr(ch, "index", None) for ch in _chs_for_est],
                _rate_for_est, _lang_for_est, True)
            _locked = _price_lock_lookup(job, _combined_token, _sig_combined)
            _lock_src = "al create dell'ordine"
            if _locked is None:
                # Pagamento con buono: nessun ordine PayPal, ma la quotazione
                # mostrata all'utente resta vincolante (quote lock D2).
                _locked = _quote_lock_lookup(job, _sig_combined)
                _lock_src = "alla stima mostrata"
            if _locked is not None and abs(_locked - _expected_total) > 0.005:
                print(f"[{job_id}] price lock: dovuto {_expected_total:.2f}EUR -> "
                      f"{_locked:.2f}EUR (quotato {_lock_src}, "
                      f"token {_combined_token[:12]}...)", flush=True)
                _expected_total = _locked
        # Consumo immediato (qui il job parte davvero) e SOLO a quota attiva:
        # con ABM_FREE_QUOTA_EUR_PER_MONTH=0 riempire il contatore in silenzio
        # esaurirebbe i client il giorno in cui il limite viene alzato.
        _fq_consumed = False
        if _quota_dec["is_free"] and free_quota.limit_eur() > 0:
            try:
                free_quota.consume(_quota_cid, _quota_dec["list_total_eur"], _fq_key_gem)
                job["free_quota_key"] = _fq_key_gem
                _fq_consumed = True
            except Exception as _fq_err:
                print(f"[{job_id}] free_quota consume failed (non-fatal): {_fq_err}")
        # Log DOPO il consumo, con l'esito reale: e' l'unica traccia forense
        # del consumo nel flusso combinato.
        _free_quota_log(job_id, _quota_dec, charged=_fq_consumed)
        if not _quota_dec["is_free"]:
            if not _combined_token:
                if _quota_dec["quota_exhausted"]:
                    try:
                        _log_activity(job_id, job.get("original_filename", ""),
                                      "FREE_QUOTA_EXCEEDED",
                                      client_id=job.get("client_id", ""),
                                      client_ip=job.get("client_ip", ""),
                                      voice=_voice_for_log(_voice_for_est))
                    except Exception:
                        pass
                _release_opt_claim()
                return jsonify({
                    "error": "Payment required for generation.",
                    "error_code": ("free_quota_exhausted"
                                   if _quota_dec["quota_exhausted"] else "payment_required"),
                    "total_eur": _expected_total,
                    "gemini_eur": _gemini_eur_quota,
                    "llm_eur": estimated_cost,
                    "threshold_eur": _threshold_combined,
                    "quota_used_eur": _quota_dec["quota_used_eur"],
                    "quota_limit_eur": _quota_dec["quota_limit_eur"],
                    "free_cap_exceeded": bool(_quota_dec.get("free_cap_exceeded")),
                }), 402
            # Validazione + consume del token combinato.
            _consumed = False
            if _combined_token in payment._payments:
                with payment._payments_lock:
                    _pay = payment._payments.get(_combined_token)
                    if (_pay and not _pay.get("used")
                            and float(_pay.get("amount_eur", 0)) + 0.05
                            >= _expected_total):
                        _pay["used"] = True
                        _pay["used_at"] = time.time()
                        _pay["used_job_id"] = job_id
                        _consumed_method = "paypal"
                        _consumed_email = _pay.get("email", "") or ""
                        _consumed = True
                if _consumed:
                    _save_payments()
            elif _combined_token in payment._vouchers:
                try:
                    payment._voucher_consume(_combined_token, _expected_total,
                                             job_id=job_id)
                    _v = payment._vouchers.get(_combined_token, {})
                    _consumed_method = "voucher"
                    _consumed_email = _v.get("email", "") or ""
                    _consumed = True
                except ValueError as _vc_err:
                    print(f"[{job_id}] combined voucher consume failed: {_vc_err}")
            if not _consumed:
                # Token presente ma non consumabile (gia' usato, importo
                # insufficiente, voucher scaduto, token sconosciuto): il job
                # NON deve partire gratis. Release del claim + 402, allineato
                # al branch standalone LLM sopra.
                print(f"[{job_id}] combined payment token "
                      f"{_combined_token[:12]}... not consumable "
                      f"(expected_total={_expected_total:.2f}€) -> 402")
                _release_opt_claim()
                return jsonify({
                    "error": "Invalid or already-used payment token.",
                    "error_code": "invalid_payment",
                }), 402
            # Stash payment per:
            # - audit Gemini (_write_gemini_audit legge job["payment"])
            # - refund su cancel/error (_refund_gemini_payment)
            # total_eur = quota Gemini. La quota LLM e` in payment["llm_eur"];
            # l'audit Gemini legge solo la quota voce, non il combinato.
            job["payment"] = {
                "token": _combined_token,
                # Pagato meno quota AI: comprende il floor premium quando la
                # quota gratuita e' esaurita (la stima TTS sotto soglia e' 0).
                "total_eur": generation_engine._tts_share_eur(
                    _expected_total, estimated_cost),
                "method": _consumed_method,
                "ts": time.time(),
                "gemini_est": _est_gemini,
                "llm_eur": float(estimated_cost),
                "source": "combined_optimize_autogen",
            }
            _acq_src, _acq_plat = _acquisition_from_request()
            job["payment"]["acquisition_source"] = _acq_src
            job["payment"]["acquisition_platform"] = _acq_plat
            if _acq_src == "app":
                try:
                    metrics_store.incr("payment_from_app", _acq_plat)
                except Exception:
                    pass
            job["payment_token"] = _combined_token
            job["payment_type"] = _consumed_method
            job["payment_email"] = _consumed_email
            job["payment_amount_eur"] = _expected_total
            # Snapshot stima pre-LLM su job["gemini_estimate"]: serve
            # all'audit per allineare i campi *_est al prezzo lockato
            # in payment["total_eur"]. Senza questo snapshot,
            # _finalize_optimization_complete ricalcolerebbe la stima
            # su testo post-LLM (potenzialmente piu` lungo/corto),
            # distorcendo delta_pct/margin nell'audit JSONL.
            job["gemini_estimate"] = _est_gemini
            print(f"[{job_id}] combined payment consumed at /api/optimize: "
                  f"gemini={_gemini_eur_quota:.2f}€ + llm={estimated_cost:.2f}€ "
                  f"= {_expected_total:.2f}€ ({_consumed_method})")
            # Batch implicito per job PAGATO. Il wizard consuma qui il
            # pagamento combinato e poi chiama run_generation direttamente
            # (bypassa /api/generate): senza questa registrazione l'heartbeat
            # a 60s resta armato su un job pagato e lo uccide appena l'utente
            # lascia la scheda in background. Il descrittore di recupero viene
            # registrato a valle (fase "optimize", dopo i parametri opt_*).
            _register_paid_job_batch(
                job_id, job, _combined_token, engine="Gemini",
                lang=data.get("lang", "en"), email=_consumed_email,
                pending_kind="")

    # ----- Combined payment (LLM + Speechify in auto_generate flow) -----
    # Mirror LEAN del blocco Gemini sopra per le voci PREMIUM Simba. Un unico
    # token (PayPal order o voucher) copre LLM + TTS Simba. Enforcement SEMPRE
    # (anche senza token): il flusso auto-gen chiama run_generation diretto,
    # bypassando il preflight pagamento di /api/generate. Senza questo blocco il
    # TTS Simba veniva regalato (margine negativo) ogni volta che la sola quota
    # LLM cadeva sotto soglia. Speechify e' solo inglese: niente rate/lang nella
    # stima (compute su caratteri, come /api/combined_estimate).
    if _is_combined_speechify:
        _combined_token_spx = (data.get("payment_token_combined")
                               or data.get("payment_token") or "").strip()
        # Capitoli selezionati per la generazione (stessa logica frontend
        # combined_estimate: subset se selected_chapters, altrimenti tutti).
        _all_chs_spx = list(getattr(info, "chapters", []) or [])
        _sel_list_spx = _parse_selected_chapters(data.get("selected_chapters"))
        if _sel_list_spx:
            _by_idx_spx = {ch.index: ch for ch in _all_chs_spx}
            _chs_for_est_spx = [_by_idx_spx[i] for i in _sel_list_spx if i in _by_idx_spx]
        else:
            _chs_for_est_spx = _all_chs_spx
        # Job gia' terminale: testi spillati su disco, `ch.text` vuoto in
        # RAM. Senza rilettura la stima vale ~0 (voce PREMIUM gratis).
        _chs_for_est_spx = _pricing_chapters(job_id, job, _chs_for_est_spx)
        try:
            _est_spx = tts_engines.estimate("speechify", _chs_for_est_spx, language="en")
            _speechify_eur_quota = round(_est_spx.get("user_price_eur", 0.0), 2)
            _speechify_list_quota = round(_est_spx.get("list_price_eur", 0.0), 2)
        except Exception as _e_est_spx:
            # FAIL-CLOSED: vedi nota nel ramo Gemini.
            print(f"[{job_id}] combined-payment speechify estimate failed: {_e_est_spx}", flush=True)
            _release_opt_claim()
            return jsonify({"error": "Cost estimate unavailable, please retry.",
                            "error_code": "estimate_failed"}), 500
        # Quota gratuita cumulativa sul LISTINO combinato (TTS + LLM).
        _voice_spx = data.get("voice", "")
        _quota_cid_spx = _quota_client_id(job)
        _fq_key_spx = _free_quota_key(job_id, _voice_spx, _chs_for_est_spx, _all_chs_spx)
        _quota_dec_spx = _premium_quota_decision(
            _quota_cid_spx, _voice_spx,
            round(_speechify_list_quota + estimated_cost, 2), _fq_key_spx,
            book_chars=_free_quota_book_chars(info, _all_chs_spx),
        )
        _expected_total_spx = _quota_dec_spx["due_eur"]
        _threshold_spx = _quota_dec_spx["threshold_eur"]
        # Consumo immediato solo a quota attiva (vedi ramo Gemini sopra).
        _fq_consumed_spx = False
        if _quota_dec_spx["is_free"] and free_quota.limit_eur() > 0:
            try:
                free_quota.consume(_quota_cid_spx,
                                   _quota_dec_spx["list_total_eur"], _fq_key_spx)
                job["free_quota_key"] = _fq_key_spx
                _fq_consumed_spx = True
            except Exception as _fq_err_spx:
                print(f"[{job_id}] free_quota consume failed (non-fatal): {_fq_err_spx}")
        _free_quota_log(job_id, _quota_dec_spx, charged=_fq_consumed_spx)
        if not _quota_dec_spx["is_free"]:
            if not _combined_token_spx:
                if _quota_dec_spx["quota_exhausted"]:
                    try:
                        _log_activity(job_id, job.get("original_filename", ""),
                                      "FREE_QUOTA_EXCEEDED",
                                      client_id=job.get("client_id", ""),
                                      client_ip=job.get("client_ip", ""),
                                      voice=_voice_for_log(_voice_spx))
                    except Exception:
                        pass
                _release_opt_claim()
                return jsonify({
                    "error": "Payment required for generation.",
                    "error_code": ("free_quota_exhausted"
                                   if _quota_dec_spx["quota_exhausted"] else "payment_required"),
                    "total_eur": _expected_total_spx,
                    "speechify_eur": _speechify_eur_quota,
                    "llm_eur": estimated_cost,
                    "threshold_eur": _threshold_spx,
                    "quota_used_eur": _quota_dec_spx["quota_used_eur"],
                    "quota_limit_eur": _quota_dec_spx["quota_limit_eur"],
                    "free_cap_exceeded": bool(_quota_dec_spx.get("free_cap_exceeded")),
                }), 402
            # Validazione + consume del token combinato.
            _consumed_spx = False
            _consumed_method_spx = ""
            _consumed_email_spx = ""
            if _combined_token_spx in payment._payments:
                with payment._payments_lock:
                    _pay_spx = payment._payments.get(_combined_token_spx)
                    if (_pay_spx and not _pay_spx.get("used")
                            and float(_pay_spx.get("amount_eur", 0)) + 0.05
                            >= _expected_total_spx):
                        _pay_spx["used"] = True
                        _pay_spx["used_at"] = time.time()
                        _pay_spx["used_job_id"] = job_id
                        _consumed_method_spx = "paypal"
                        _consumed_email_spx = _pay_spx.get("email", "") or ""
                        _consumed_spx = True
                if _consumed_spx:
                    _save_payments()
            elif _combined_token_spx in payment._vouchers:
                try:
                    payment._voucher_consume(_combined_token_spx, _expected_total_spx,
                                             job_id=job_id)
                    _v_spx = payment._vouchers.get(_combined_token_spx, {})
                    _consumed_method_spx = "voucher"
                    _consumed_email_spx = _v_spx.get("email", "") or ""
                    _consumed_spx = True
                except ValueError as _vc_err_spx:
                    print(f"[{job_id}] combined voucher consume failed: {_vc_err_spx}")
            if not _consumed_spx:
                print(f"[{job_id}] combined payment token "
                      f"{_combined_token_spx[:12]}... not consumable "
                      f"(expected_total={_expected_total_spx:.2f}€) -> 402")
                _release_opt_claim()
                return jsonify({
                    "error": "Invalid or already-used payment token.",
                    "error_code": "invalid_payment",
                }), 402
            # Stash payment per audit Speechify (_write_speechify_audit legge
            # job["payment"]["total_eur"]) + refund su cancel/error. total_eur =
            # quota Simba (la quota LLM e' in payment["llm_eur"]).
            job["payment"] = {
                "token": _combined_token_spx,
                # Pagato meno quota AI: comprende il floor premium quando la
                # quota gratuita e' esaurita (la stima TTS sotto soglia e' 0).
                "total_eur": generation_engine._tts_share_eur(
                    _expected_total_spx, estimated_cost),
                "method": _consumed_method_spx,
                "ts": time.time(),
                "speechify_est": _est_spx,
                "llm_eur": float(estimated_cost),
                "source": "combined_optimize_autogen",
            }
            _acq_src_spx, _acq_plat_spx = _acquisition_from_request()
            job["payment"]["acquisition_source"] = _acq_src_spx
            job["payment"]["acquisition_platform"] = _acq_plat_spx
            if _acq_src_spx == "app":
                try:
                    metrics_store.incr("payment_from_app", _acq_plat_spx)
                except Exception:
                    pass
            job["payment_token"] = _combined_token_spx
            job["payment_type"] = _consumed_method_spx
            job["payment_email"] = _consumed_email_spx
            job["payment_amount_eur"] = _expected_total_spx
            # Snapshot stima pre-LLM: allinea i campi *_est dell'audit al prezzo
            # lockato in payment["total_eur"] (come per Gemini).
            job["speechify_estimate"] = _est_spx
            print(f"[{job_id}] combined payment consumed at /api/optimize: "
                  f"speechify={_speechify_eur_quota:.2f}€ + llm={estimated_cost:.2f}€ "
                  f"= {_expected_total_spx:.2f}€ ({_consumed_method_spx})")
            # Batch implicito per job PAGATO (vedi ramo Gemini sopra).
            _register_paid_job_batch(
                job_id, job, _combined_token_spx, engine="Speechify",
                lang=data.get("lang", "en"), email=_consumed_email_spx,
                pending_kind="")

    # ----- Combined payment (LLM + VoxCPM in auto_generate flow) -----
    # Mirror LEAN del blocco Speechify sopra per le voci VoxCPM. Un unico
    # token (PayPal order o voucher) copre LLM + TTS VoxCPM. Enforcement SEMPRE
    # (anche senza token): il flusso auto-gen chiama run_generation diretto,
    # bypassando il preflight pagamento di /api/generate. Senza questo blocco il
    # TTS VoxCPM veniva regalato (margine negativo) ogni volta che la sola quota
    # LLM cadeva sotto soglia — vedi task-10-report.md "Fix round 1". Lingua:
    # stessa priorita' di /api/combined_estimate e del ramo Gemini sopra
    # (UI > metadata libro > "it"), non fissa come per Speechify (solo inglese).
    if _is_combined_voxcpm:
        _combined_token_vox = (data.get("payment_token_combined")
                               or data.get("payment_token") or "").strip()
        _ui_lang_for_vox = _i18n.norm_lang(lang) if lang else ""
        _lang_for_vox = (_ui_lang_for_vox
                         or _i18n.norm_lang(getattr(info, "language", ""))
                         or "it")
        # Capitoli selezionati per la generazione (stessa logica frontend
        # combined_estimate: subset se selected_chapters, altrimenti tutti).
        _all_chs_vox = list(getattr(info, "chapters", []) or [])
        _sel_list_vox = _parse_selected_chapters(data.get("selected_chapters"))
        if _sel_list_vox:
            _by_idx_vox = {ch.index: ch for ch in _all_chs_vox}
            _chs_for_est_vox = [_by_idx_vox[i] for i in _sel_list_vox if i in _by_idx_vox]
        else:
            _chs_for_est_vox = _all_chs_vox
        try:
            _est_vox = tts_engines.estimate("voxcpm", _chs_for_est_vox, language=_lang_for_vox)
            _voxcpm_eur_quota = round(_est_vox.get("user_price_eur", 0.0), 2)
            _voxcpm_list_quota = round(_est_vox.get("list_price_eur", 0.0), 2)
        except Exception as _e_est_vox:
            print(f"[{job_id}] combined-payment voxcpm estimate failed: {_e_est_vox}")
            _est_vox = None
            _voxcpm_eur_quota = 0.0
            _voxcpm_list_quota = 0.0
        # Quota gratuita cumulativa sul LISTINO combinato (TTS + LLM).
        _voice_vox = data.get("voice", "")
        _quota_cid_vox = _quota_client_id(job)
        _fq_key_vox = _free_quota_key(job_id, _voice_vox, _chs_for_est_vox, _all_chs_vox)
        _quota_dec_vox = _premium_quota_decision(
            _quota_cid_vox, _voice_vox,
            round(_voxcpm_list_quota + estimated_cost, 2), _fq_key_vox,
            book_chars=_free_quota_book_chars(info, _all_chs_vox),
            language=_lang_for_vox,
        )
        _expected_total_vox = _quota_dec_vox["due_eur"]
        _threshold_vox = _quota_dec_vox["threshold_eur"]
        # Consumo immediato solo a quota attiva (vedi ramo Gemini sopra).
        _fq_consumed_vox = False
        if _quota_dec_vox["is_free"] and free_quota.limit_eur() > 0:
            try:
                free_quota.consume(_quota_cid_vox,
                                   _quota_dec_vox["list_total_eur"], _fq_key_vox)
                job["free_quota_key"] = _fq_key_vox
                _fq_consumed_vox = True
            except Exception as _fq_err_vox:
                print(f"[{job_id}] free_quota consume failed (non-fatal): {_fq_err_vox}")
        _free_quota_log(job_id, _quota_dec_vox, charged=_fq_consumed_vox)
        if not _quota_dec_vox["is_free"]:
            if not _combined_token_vox:
                if _quota_dec_vox["quota_exhausted"]:
                    try:
                        _log_activity(job_id, job.get("original_filename", ""),
                                      "FREE_QUOTA_EXCEEDED",
                                      client_id=job.get("client_id", ""),
                                      client_ip=job.get("client_ip", ""),
                                      voice=_voice_for_log(_voice_vox))
                    except Exception:
                        pass
                _release_opt_claim()
                return jsonify({
                    "error": "Payment required for generation.",
                    "error_code": ("free_quota_exhausted"
                                   if _quota_dec_vox["quota_exhausted"] else "payment_required"),
                    "total_eur": _expected_total_vox,
                    "voxcpm_eur": _voxcpm_eur_quota,
                    "llm_eur": estimated_cost,
                    "threshold_eur": _threshold_vox,
                    "quota_used_eur": _quota_dec_vox["quota_used_eur"],
                    "quota_limit_eur": _quota_dec_vox["quota_limit_eur"],
                    "free_cap_exceeded": bool(_quota_dec_vox.get("free_cap_exceeded")),
                }), 402
            # Validazione + consume del token combinato.
            _consumed_vox = False
            _consumed_method_vox = ""
            _consumed_email_vox = ""
            if _combined_token_vox in payment._payments:
                with payment._payments_lock:
                    _pay_vox = payment._payments.get(_combined_token_vox)
                    if (_pay_vox and not _pay_vox.get("used")
                            and float(_pay_vox.get("amount_eur", 0)) + 0.05
                            >= _expected_total_vox):
                        _pay_vox["used"] = True
                        _pay_vox["used_at"] = time.time()
                        _pay_vox["used_job_id"] = job_id
                        _consumed_method_vox = "paypal"
                        _consumed_email_vox = _pay_vox.get("email", "") or ""
                        _consumed_vox = True
                if _consumed_vox:
                    _save_payments()
            elif _combined_token_vox in payment._vouchers:
                try:
                    payment._voucher_consume(_combined_token_vox, _expected_total_vox,
                                             job_id=job_id)
                    _v_vox = payment._vouchers.get(_combined_token_vox, {})
                    _consumed_method_vox = "voucher"
                    _consumed_email_vox = _v_vox.get("email", "") or ""
                    _consumed_vox = True
                except ValueError as _vc_err_vox:
                    print(f"[{job_id}] combined voucher consume failed: {_vc_err_vox}")
            if not _consumed_vox:
                print(f"[{job_id}] combined payment token "
                      f"{_combined_token_vox[:12]}... not consumable "
                      f"(expected_total={_expected_total_vox:.2f}€) -> 402")
                _release_opt_claim()
                return jsonify({
                    "error": "Invalid or already-used payment token.",
                    "error_code": "invalid_payment",
                }), 402
            # Stash payment per audit VoxCPM (Task 11) + refund su cancel/error
            # (stessa "tasca" job["payment"] di Gemini/Speechify). total_eur =
            # quota VoxCPM (la quota LLM e' in payment["llm_eur"]).
            job["payment"] = {
                "token": _combined_token_vox,
                # Pagato meno quota AI: comprende il floor premium quando la
                # quota gratuita e' esaurita (la stima TTS sotto soglia e' 0).
                "total_eur": generation_engine._tts_share_eur(
                    _expected_total_vox, estimated_cost),
                "method": _consumed_method_vox,
                "ts": time.time(),
                "voxcpm_est": _est_vox,
                "llm_eur": float(estimated_cost),
                "source": "combined_optimize_autogen",
            }
            _acq_src_vox, _acq_plat_vox = _acquisition_from_request()
            job["payment"]["acquisition_source"] = _acq_src_vox
            job["payment"]["acquisition_platform"] = _acq_plat_vox
            if _acq_src_vox == "app":
                try:
                    metrics_store.incr("payment_from_app", _acq_plat_vox)
                except Exception:
                    pass
            job["payment_token"] = _combined_token_vox
            job["payment_type"] = _consumed_method_vox
            job["payment_email"] = _consumed_email_vox
            job["payment_amount_eur"] = _expected_total_vox
            # Snapshot stima pre-LLM: allinea i campi *_est dell'audit al prezzo
            # lockato in payment["total_eur"] (come per Gemini/Speechify).
            job["voxcpm_estimate"] = _est_vox
            print(f"[{job_id}] combined payment consumed at /api/optimize: "
                  f"voxcpm={_voxcpm_eur_quota:.2f}€ + llm={estimated_cost:.2f}€ "
                  f"= {_expected_total_vox:.2f}€ ({_consumed_method_vox})")
            # Batch implicito per job PAGATO (vedi ramo Gemini sopra).
            _register_paid_job_batch(
                job_id, job, _combined_token_vox, engine="VoxCPM",
                lang=data.get("lang", "en"), email=_consumed_email_vox,
                pending_kind="")

    # Batch mode: assegnazione campi notify (validazione email + SMTP gia'
    # eseguita sopra, prima del consumo del pagamento). force=True: come il
    # vecchio blocco (assegnazione incondizionata quando batch e' attivo),
    # anche se un pagamento ha gia' armato il job su un'altra email; il ramo
    # opt_* piu' sotto resta il proprietario di notify_download_type
    # (output_format=None qui).
    if batch:
        _arm_email_delivery(job, job_id, email, lang=data.get("lang", "en"),
                            output_format=None, pending_kind="", engine="", force=True)

    _apply_account_to_job(job, job_id, "optimize",
                          output_format=(data.get("output_format", "m4b") if auto_generate else None),
                          podcast_base_url=(data.get("podcast_base_url") or "").strip(),
                          voice=(data.get("voice", "") if auto_generate else ""),
                          lang=(lang or "en"))

    # Store auto-generate params for batch mode
    if auto_generate:
        job["opt_auto_generate"] = True
        job["opt_voice"] = data.get("voice", "it-IT-IsabellaNeural")
        job["opt_rate"] = data.get("rate", "+0%")
        job["opt_single_file"] = data.get("single_file", True)
        job["opt_output_format"] = data.get("output_format", "m4b")
        job["opt_podcast_base_url"] = (data.get("podcast_base_url") or "").strip()
        # Lettura opzionale del testo tra parentesi: l'auto-generazione post-LLM
        # legge questi flag direttamente da job (run_generation), non tramite
        # prefisso opt_*. Senza catturarli qui il ramo wizard (optimize+auto-gen)
        # userebbe sempre il default (rimozione), ignorando la scelta utente.
        job["read_round_parens"] = bool(data.get("read_round_parens", False))
        job["read_square_brackets"] = bool(data.get("read_square_brackets", False))
        if job["opt_output_format"] == "zip_rss":
            job["notify_download_type"] = "podcast"
            job["notify_base_url"] = job["opt_podcast_base_url"]
        else:
            job["notify_download_type"] = "audio"
            job["notify_base_url"] = ""
    else:
        job["opt_auto_generate"] = False

    # Registra il descrittore di recupero per i job optimize batch (email registrata).
    # Dopo l'impostazione dei parametri opt_* così il descrittore li cattura.
    if job.get("email_registered"):
        try:
            pending_jobs.register(job_id, "optimize", _build_job_descriptor(job, "optimize"))
        except Exception as _e:
            print(f"[{job_id}] pending_jobs.register (optimize) failed (non-fatal): {_e}", flush=True)

    thread = threading.Thread(
        target=run_optimization, args=(job_id, chapters_to_optimize), daemon=True
    )
    thread.start()

    # Con auto_generate la voce di destinazione viaggia sull'evento OPTIMIZE:
    # il pannello admin classifica la sessione PREMIUM da subito, senza
    # aspettare il GENERATE scritto a fine ottimizzazione.
    _log_activity(job_id, job.get("original_filename", ""), "OPTIMIZE",
                  client_id, job.get("client_ip", ""),
                  job.get("opt_voice", "") if auto_generate else "",
                  browser_lang=job.get("browser_lang", ""))

    return jsonify({"status": "started", "batch": batch, "auto_generate": auto_generate})


@app.route("/api/optimize_progress/<job_id>")
def api_optimize_progress(job_id):
    """SSE endpoint for LLM optimization progress."""
    _job_pre, _err_pre, _sc_pre = _check_job_owner(job_id)
    if _err_pre is not None:
        return _err_pre, _sc_pre
    def _build(job):
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
            "opt_total_chars_extended": job.get("opt_total_chars_extended", job.get("opt_total_chars", 0)),
            "opt_elapsed_seconds": round(time.time() - job["opt_start_time"]) if job.get("opt_start_time") else job.get("opt_elapsed_seconds", 0),
        }
        if status == "error":
            # Errore generico verso il client; il dettaglio resta nei log server-side.
            payload["error"] = "optimization_failed"
            return payload, True
        if status == "cancelled" or job.get("opt_cancelled"):
            payload["status"] = "cancelled"
            return payload, True
        if status == "optimized":
            payload["ai_optimized"] = True
            return payload, True
        # If auto_generate kicked in, status is now "generating" or "done"
        if status in ("generating", "done"):
            payload["ai_optimized"] = True
            payload["auto_generate_started"] = True
            return payload, True
        return payload, False

    return _sse_stream(job_id, _build, sleep_sec=2)


# ════════════════ TRADUZIONE LIBRO ════════════════

_TRANSLATE_FORMATS = ("abm", "epub", "txt")


def _translate_selected_chars(job, raw_sel):
    """(chars_totali, selected_indices) dei capitoli selezionati."""
    info = job.get("info")
    selected = _parse_selected_chapters(raw_sel) if raw_sel else \
        [ch.index for ch in info.chapters]
    sel = set(selected)
    chars = sum(ch.char_count for ch in info.chapters if ch.index in sel)
    return chars, selected


@app.route("/api/translate_estimate/<job_id>")
def api_translate_estimate(job_id):
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return err, sc
    info = job.get("info")
    if not info or not info.chapters:
        return jsonify({"error": "No book data"}), 400
    raw_sel = request.args.getlist("selected_chapters") \
        + request.args.getlist("selected_chapters[]")
    optimize = (request.args.get("optimize") or "").strip() in ("1", "true")
    chars, _ = _translate_selected_chars(job, raw_sel)
    est = payment._estimate_translation_cost_eur(chars, optimize=optimize)
    est["available"] = translation_core.is_available()
    return jsonify(est)


@app.route("/api/translate_title/<job_id>")
def api_translate_title(job_id):
    """Traduce il solo titolo del libro per la proposta del nome file nel
    wizard traduzione. Cortesia pre-acquisto: nessun pagamento, cache per
    lingua nel job, fallimento silenzioso (title vuoto, HTTP 200).
    Spec: docs/superpowers/specs/2026-06-06-translated-title-filename-design.md
    """
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return err, sc
    info = job.get("info")
    title = (getattr(info, "title", "") or "").strip()[:300]
    target = (request.args.get("target") or "").strip().lower().split("-")[0]
    source = (request.args.get("source") or "").strip().lower().split("-")[0]
    if not source:
        source = (getattr(info, "language", "") or "").strip().lower().split("-")[0]
    if not title or not re.fullmatch(r"[a-z]{2,3}", target or "") \
            or not re.fullmatch(r"[a-z]{2,3}", source or ""):
        return jsonify({"title": ""})
    if source == target:
        return jsonify({"title": title})
    cache = job.setdefault("tr_title_cache", {})
    if target in cache:
        return jsonify({"title": cache[target], "cached": True})
    if not translation_core.is_available():
        return jsonify({"title": ""})
    try:
        backend = translation_core.resolve_backend()
        provider, model, _base = translation_core.make_client_provider(backend)
        out = translation_core.translate_titles(
            provider, [title], source, target,
            model=model, usage=translation_core.UsageTracker())
        translated = (out[0] or "").strip() or title
    except Exception as e:
        print(f"[tr-title] {job_id}: traduzione titolo fallita (non-fatal): {e}")
        return jsonify({"title": ""})
    cache[target] = translated
    return jsonify({"title": translated})


@app.route("/api/translate", methods=["POST"])
def api_translate():
    data = request.get_json(silent=True) or {}
    job_id = (data.get("job_id") or "").strip()
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return err, sc
    info = job.get("info")
    if not info or not info.chapters:
        return jsonify({"error": "No book data"}), 400

    if not translation_core.is_available():
        return jsonify({"error": "Translation not configured on this server"}), 503
    # Prima del preflight di pagamento: in manutenzione il token non si consuma.
    _maint = _maintenance_gate()
    if _maint is not None:
        return _maint

    source = (data.get("source_lang") or "").strip().lower().split("-")[0]
    target = (data.get("target_lang") or "").strip().lower().split("-")[0]
    if not re.fullmatch(r"[a-z]{2,3}", source or "") \
            or not re.fullmatch(r"[a-z]{2,3}", target or ""):
        return jsonify({"error": "Invalid language code"}), 400
    if source == target:
        return jsonify({"error": "Source and target language are the same",
                        "error_code": "same_lang"}), 400
    # Destinazione tra le lingue delle voci standard edge-tts
    try:
        edge_langs = set(get_voices().keys())
    except Exception:
        edge_langs = set()
    if not edge_langs:
        edge_langs = translation_core.EDGE_LANGS_FALLBACK
    if target not in edge_langs:
        return jsonify({"error": f"Target language '{target}' not supported",
                        "error_code": "bad_target_lang"}), 400

    out_format = (data.get("output_format") or "abm").strip().lower()
    if out_format not in _TRANSLATE_FORMATS:
        return jsonify({"error": f"Invalid output format '{out_format}'"}), 400
    out_name = (data.get("output_name") or "").strip() or "translated"
    optimize = bool(data.get("optimize"))
    raw_sel = data.get("selected_chapters") or []
    chars, selected = _translate_selected_chars(
        job, [str(x) for x in raw_sel])
    if chars <= 0:
        return jsonify({"error": "No chapters selected"}), 400

    est = payment._estimate_translation_cost_eur(chars, optimize=optimize)
    client_id = job.get("client_id", "")

    # Slot LLM per client (stesso slot dell'ottimizzazione) + claim atomico
    with _jobs_lock:
        if job["status"] not in ("analyzed", "translated"):
            return jsonify({"error": "Job busy or not ready"}), 400
        if client_id and MAX_CONCURRENT_LLM_PER_CLIENT > 0:
            if _active_optimizing_for_client_unlocked(client_id) >= MAX_CONCURRENT_LLM_PER_CLIENT:
                return jsonify({
                    "error": f"Concurrent LLM job limit reached ({MAX_CONCURRENT_LLM_PER_CLIENT}).",
                    "error_code": "concurrent_optimize_limit",
                }), 429
        job["status"] = "translating"

    def _release_claim():
        with _jobs_lock:
            if job.get("status") == "translating":
                job["status"] = "analyzed"

    # Batch mode (email) — validazione PRIMA del pagamento: un'email invalida
    # o SMTP assente non deve mai lasciare un pagamento consumato (stranded).
    batch = bool(data.get("batch"))
    email = (data.get("email") or "").strip()
    batch, email = _acct_forced_batch(batch, email)
    if batch:
        if not email or not _ACCT_EMAIL_RE.match(email):
            _release_claim()
            return jsonify({"error": "Valid email required for batch mode"}), 400
        if not _smtp_available():
            _release_claim()
            return jsonify({"error": "Email service not configured"}), 503

    # Pagamento (stesso flusso di /api/optimize, importo = est["due_eur"])
    if est["requires_payment"]:
        payment_token = (data.get("payment_token") or "").strip()
        if not payment_token:
            _release_claim()
            return jsonify({"error": "Payment required",
                            "error_code": "payment_required",
                            "due_eur": est["due_eur"]}), 402
        valid = False
        if payment_token in payment._payments:
            _claimed_pay = None
            with payment._payments_lock:
                pay = payment._payments.get(payment_token)
                if pay and not pay.get("used") \
                        and pay.get("amount_eur", 0) + 0.01 >= est["due_eur"]:
                    pay["used"] = True
                    pay["used_at"] = time.time()
                    pay["used_job_id"] = job_id
                    _claimed_pay = pay
            if _claimed_pay is not None:
                _save_payments()
                job["payment_token"] = payment_token
                job["payment_type"] = "paypal"
                job["payment_email"] = _claimed_pay.get("email", "")
                job["payment_amount_eur"] = _claimed_pay.get("amount_eur", 0)
                valid = True
        elif payment_token in payment._vouchers:
            v = payment._vouchers[payment_token]
            remaining = _voucher_remaining(v)
            if v.get("expires_at", 0) > time.time() \
                    and remaining >= est["due_eur"] - 0.01:
                try:
                    new_remaining = _voucher_consume(
                        payment_token, est["due_eur"], job_id=job_id)
                except ValueError as _ve:
                    _release_claim()
                    return jsonify({"error": f"Voucher not spendable: {_ve}"}), 402
                job["payment_token"] = payment_token
                job["payment_type"] = "voucher"
                job["payment_email"] = v.get("email", "")
                job["payment_amount_eur"] = round(float(est["due_eur"]), 2)
                job["voucher_remaining_after"] = new_remaining
                valid = True
        if not valid:
            _release_claim()
            return jsonify({"error": "Invalid or insufficient payment",
                            "error_code": "payment_invalid"}), 402
    else:
        # Divergenza di stima: il frontend può aver ritenuto necessario il
        # pagamento e catturato l'ordine PayPal, mentre qui il backend stima
        # sotto soglia (nessun pagamento richiesto). In quel caso l'ordine resta
        # incassato ma `used=false` → a scadenza retention verrebbe visto come
        # capture orfano (falso positivo → alert/rimborso). Se il client ha
        # comunque passato un capture PayPal, lo marchiamo consumato ORA legandolo
        # al job: il servizio sta per essere erogato, il denaro è dovuto. I
        # voucher non richiedono azione (nulla è stato scalato). Vedi incidente
        # JM9_Vyd3UmB_J9GTfLNT7w.
        _tok = (data.get("payment_token") or "").strip()
        if _tok and _tok in payment._payments:
            try:
                _settled = payment.settle_capture_consumed(
                    _tok, job_id=job_id, reason="translate_free_settle")
                if _settled:
                    job["payment_token"] = _tok
                    job["payment_type"] = "paypal"
                    job["payment_email"] = _settled.get("email", "")
                    job["payment_amount_eur"] = _settled.get("amount_eur", 0)
                    print(f"[{job_id}] translate: capture PayPal {_tok} marcato "
                          f"consumato (stima backend sotto soglia, servizio erogato)")
            except Exception as _e:
                print(f"[{job_id}] translate settle capture non-fatal: {_e}")

    # Batch mode: assegnazione campi notify (validazione gia' eseguita sopra,
    # prima del pagamento). force=True: come il vecchio blocco (assegnazione
    # incondizionata quando batch e' attivo). notify_download_type resta
    # impostato qui esplicitamente (mai derivato da output_format: un job di
    # traduzione non e' "audio"/"podcast").
    if batch:
        _arm_email_delivery(job, job_id, email, lang=data.get("lang", "en"),
                            output_format=None, pending_kind="", engine="", force=True)
        job["notify_download_type"] = "translated"

    _apply_account_to_job(job, job_id, "translate", output_format=out_format,
                          lang=(data.get("lang") or "en"))

    job["tr_cancelled"] = False
    job["tr_params"] = {
        "source_lang": source, "target_lang": target,
        "output_format": out_format, "output_name": out_name,
        "optimize": optimize, "selected_chapters": selected,
    }
    job["last_poll"] = time.time()

    thread = threading.Thread(target=run_translation, args=(job_id,),
                              daemon=True)
    thread.start()
    _log_activity(job_id, job.get("original_filename", ""), "TRANSLATE",
                  client_id, job.get("client_ip", ""),
                  f"{source}>{target}" + (" +AI" if optimize else ""),
                  browser_lang=job.get("browser_lang", ""))
    return jsonify({"status": "started", "batch": batch,
                    "due_eur": est["due_eur"]})


@app.route("/api/translate_progress/<job_id>")
def api_translate_progress(job_id):
    # Clone di /api/optimize_progress con i campi tr_*
    _job_pre, _err_pre, _sc_pre = _check_job_owner(job_id)
    if _err_pre is not None:
        return _err_pre, _sc_pre

    def _build(job):
        status = job.get("status", "unknown")
        payload = {
            "status": status,
            "tr_progress_current": job.get("tr_progress_current", 0),
            "tr_progress_total": job.get("tr_progress_total", 0),
            "tr_progress_message": job.get("tr_progress_message", ""),
            "tr_current_chapter": job.get("tr_current_chapter", ""),
            "tr_current_chapter_num": job.get("tr_current_chapter_num", 0),
            "tr_processed_chars": job.get("tr_processed_chars", 0),
            "tr_streamed_chars": job.get("tr_streamed_chars", 0),
            "tr_total_chars": job.get("tr_total_chars", 0),
            "tr_elapsed_seconds": job.get("tr_elapsed_seconds", 0),
            "translated_name": job.get("translated_name", ""),
            "error": job.get("error", ""),
        }
        # Completamento ed errore (status autorevole) hanno PRECEDENZA su
        # tr_cancelled: un job arrivato a "translated"/"error" è terminato
        # e un eventuale flag di cancellazione stantio (lasciato da un
        # thread precedente in una race di riavvio) non deve mascherarlo,
        # altrimenti il pannello perde il bottone di download.
        if status == "translated":
            return payload, True
        if status == "error":
            return payload, True
        if job.get("tr_cancelled"):
            payload["status"] = "cancelled"
            return payload, True
        return payload, False

    return _sse_stream(job_id, _build, sleep_sec=2)


@app.route("/api/translate_cancel/<job_id>", methods=["POST"])
def api_translate_cancel(job_id):
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return err, sc
    # Imposta il flag: il thread run_translation lo rileva al prossimo chunk,
    # solleva TranslationCancelled e il suo handler emette il rimborso
    # (integrale) via _refund_job_payment(..., "cancel"). Vedi
    # generation_engine.run_translation.
    job["tr_cancelled"] = True
    # Kill amministrativo dalla pagina /admin/log-activity: traccia ADMIN_CANCEL
    # per coerenza con /api/cancel e /api/cancel_optimize (visibilità nel log).
    if _admin_auth_ok(_admin_auth_from_request()):
        _log_admin_cancel(job_id, job, "")
    return jsonify({"status": "cancelling"})


ADOPTED_TRANSLATION_ABM = "_adopted_translation.abm"


def _write_adopted_translation_abm(job_id, job, chapters):
    """Scrive nella job dir l'.abm dei capitoli tradotti adottati, con gli
    stessi indici della SPA: e' la sorgente del recovery (vedi
    recovery._reenqueue_orphan). Ritorna il path, o "" se la scrittura fallisce
    (non fatale: il job prosegue, solo il recovery resta sull'originale)."""
    try:
        info = job.get("info")
        out_path = UPLOAD_DIR / job_id / ADOPTED_TRANSLATION_ABM
        manifest_src = {
            "title": getattr(info, "title", "") or "",
            "author": getattr(info, "author", "") or "",
            "original_filename": job.get("original_filename", ""),
        }
        translation_core.write_abm(
            out_path, manifest_src,
            [{"index": c.index, "title": c.title, "text": c.text} for c in chapters],
            None, "", job.get("translated_lang", "") or getattr(info, "language", ""),
            bool(job.get("translated_optimized")))
        return str(out_path)
    except Exception as e:
        print(f"[{job_id}] snapshot traduzione adottata fallito (non-fatal): {e}",
              flush=True)
        return ""


@app.route("/api/translate_adopt/<job_id>", methods=["POST"])
def api_translate_adopt(job_id):
    """Adotta la traduzione come libro attivo: sostituisce i capitoli del
    job con quelli tradotti e torna in stato 'analyzed' per il percorso TTS."""
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return err, sc
    if job.get("status") != "translated" or not job.get("translated_chapters"):
        return jsonify({"error": "No completed translation to adopt"}), 400
    info = job.get("info")
    from epub_to_tts import Chapter
    new_chapters = []
    for i, ch in enumerate(job["translated_chapters"], 1):
        text = ch.get("text", "")
        new_chapters.append(Chapter(
            index=i,
            title=ch.get("title", f"Chapter {i}"),
            text=text,
            word_count=len(text.split()),
            char_count=len(text),
        ))
    info.chapters = new_chapters
    info.language = job.get("translated_lang", info.language)
    # La provenienza della lingua segue la lingua. Senza questo, riaprendo lo
    # stesso file il ramo del job gia' esistente risponderebbe con il
    # language_source del libro ORIGINALE: su un PDF senza metadati la riga
    # della lingua direbbe «non rilevata, ipotizzata» di una lingua che
    # l'utente ha scelto lui, e il modale di conferma tornerebbe a sbarrargli
    # la strada. 'forced' = scelta dall'utente; nulla e' stato rilevato
    # dall'IA sulla forma adottata, quindi language_detected torna False.
    job["language_source"] = "forced"
    job["language_detected"] = False
    # Titolo tradotto dal batch titoli del job (se prodotto): cosi' i
    # metadati M4B/MP3, la pagina download e le email del percorso audio
    # usano il titolo nella lingua di destinazione.
    # Nota: dopo l'adopt info.title E' il titolo nella nuova lingua; una
    # successiva traduzione (es. EN->DE) lo usera' come titolo sorgente,
    # coerente coi capitoli adottati che sono gia' nella nuova lingua.
    info.title = job.get("translated_title") or info.title
    # Se la traduzione includeva l'ottimizzazione TTS, i capitoli adottati
    # risultano già ottimizzati (niente doppio pagamento ottimizzazione).
    if job.get("translated_optimized"):
        job["ai_optimized"] = True
        job["optimized_chapters"] = [c.index for c in new_chapters]
    else:
        job["ai_optimized"] = False
        job["optimized_chapters"] = []
    job["status"] = "analyzed"
    job["tr_cancelled"] = False
    # Il testo adottato vive solo in RAM: senza una copia su disco il recovery
    # dopo un restart ri-parsava il libro ORIGINALE (input_path) e la voce
    # della lingua di destinazione leggeva il testo sorgente (job
    # LxRrADnUul50aFbWLM0rAg, 06/10/2026: voce greca su EPUB inglese).
    job["adopted_abm_path"] = _write_adopted_translation_abm(job_id, job, new_chapters)
    _log_activity(job_id, job.get("original_filename", ""), "TRANSLATE_ADOPT",
                  job.get("client_id", ""), job.get("client_ip", ""), "", "")
    return jsonify({
        "status": "analyzed",
        "language": info.language,
        "title": info.title,
        "ai_optimized": job["ai_optimized"],
        "chapters": [{"index": c.index, "title": c.title,
                      "words": c.word_count, "chars": c.char_count}
                     for c in new_chapters],
    })


# E3 (seam /dl): /api/download_translation in routes_dl.


@app.route("/api/cancel_optimize/<job_id>", methods=["POST"])
def api_cancel_optimize(job_id):
    """Cancel an LLM optimization in progress."""
    _job, _err, _sc = _check_job_owner(job_id)
    if _err is not None:
        if _sc == 404:
            return jsonify({"status": "not_found"}), 404
        return _err, _sc
    with _jobs_lock:
        if job_id in jobs:
            job = jobs[job_id]
            if job.get("status") == "optimizing":
                job["opt_cancelled"] = True
                if _admin_auth_ok(_admin_auth_from_request()):
                    _log_admin_cancel(job_id, job, job.get("opt_voice", ""))
                return jsonify({"status": "cancelling"})
    return jsonify({"status": "not_found"}), 404


# E3 (seam admin, parte 4): active in routes_admin_jobs.


# E3 (seam /dl + serving, 2026-10-10): pagina e download via token, serving,
# /api/download* nel blueprint routes_dl. Helper della app passati come lambda
# (risolti a ogni richiesta: i test li sostituiscono su questo modulo).
routes_dl.configure(
    favicon=FAVICON_B64, dl_pages_i18n=_DL_PAGES_I18N, engine=generation_engine,
    jobs=lambda: jobs, upload_dir=lambda: UPLOAD_DIR, base_url=lambda: BASE_URL,
    email_file_retention_sec=lambda: EMAIL_FILE_RETENTION_SEC,
    _send_file_throttled=lambda *a, **k: _send_file_throttled(*a, **k),
    _log_activity=lambda *a, **k: _log_activity(*a, **k),
    _is_resume_or_probe_request=lambda *a, **k: _is_resume_or_probe_request(*a, **k),
    _mark_token_downloaded=lambda *a, **k: _mark_token_downloaded(*a, **k),
    _mark_token_redirected=lambda *a, **k: _mark_token_redirected(*a, **k),
    _safe_filename=lambda *a, **k: _safe_filename(*a, **k),
    _try_cold_serve=lambda *a, **k: _try_cold_serve(*a, **k),
    _cold_op=lambda *a, **k: _cold_op(*a, **k),
    _cold_object_available=lambda *a, **k: _cold_object_available(*a, **k),
    _cold_m4b_valid=lambda *a, **k: _cold_m4b_valid(*a, **k),
    _iter_output_dirs=lambda *a, **k: _iter_output_dirs(*a, **k),
    _find_files_in_outputs=lambda *a, **k: _find_files_in_outputs(*a, **k),
    _check_job_owner=lambda *a, **k: _check_job_owner(*a, **k),
    _effective_retention_for_token_info=lambda *a, **k: _effective_retention_for_token_info(*a, **k),
    _android_intent_url=lambda *a, **k: _android_intent_url(*a, **k),
    _app_scheme_url=lambda *a, **k: _app_scheme_url(*a, **k),
    _extract_cover_for_preview=lambda *a, **k: _extract_cover_for_preview(*a, **k),
    _extract_cover_from_epub=lambda *a, **k: _extract_cover_from_epub(*a, **k),
    _generate_fallback_cover=lambda *a, **k: _generate_fallback_cover(*a, **k),
    _generate_podcast_rss=lambda *a, **k: _generate_podcast_rss(*a, **k),
    _qr_data_uri=lambda *a, **k: _qr_data_uri(*a, **k),
    _transfer_payload_for=lambda *a, **k: _transfer_payload_for(*a, **k),
    _ua_is_android=lambda *a, **k: _ua_is_android(*a, **k),
    _ua_is_ios=lambda *a, **k: _ua_is_ios(*a, **k),
    _ua_is_mobile=lambda *a, **k: _ua_is_mobile(*a, **k))
app.register_blueprint(routes_dl.bp)



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
        "title":   "EPUB/PDF in Audiolibro Gratis MP3/M4B | Audiobook Maker",
        "tagline": "Convertitore Gratuito da EPUB e PDF in Audiolibro",
        "subtitle":"Converti i tuoi EPUB e PDF in audiolibri con voci neurali di alta qualità",
        "desc":    "Converti i tuoi ebook EPUB e PDF in audiolibri MP3 e M4B (con capitoli incorporati) gratis con voci AI naturali. Convertitore online gratuito text-to-speech: carica il tuo libro, scegli la voce e scarica l'audiolibro professionale. Nessuna installazione, funziona dal browser.",
        "kw":      "convertitore epub audiolibro, pdf in audiolibro, creare m4b con capitoli, audiolibro gratis online, text to speech italiano, sintesi vocale libro, ebook in audio, audiolibri per dislessia, audiolibri per ipovedenti, alternativa elevenlabs gratis, generatore podcast rss, audiobook maker",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Convertitore online gratuito per trasformare ebook EPUB e PDF in audiolibri MP3 e M4B con capitoli e voci neurali TTS AI. Supporta 6 lingue, selezione capitoli e generazione feed podcast RSS.",
    },
    "en": {
        "title":   "Free EPUB/PDF to MP3 & M4B Audiobook | Audiobook Maker",
        "tagline": "Free EPUB & PDF to Audiobook Converter",
        "subtitle":"Convert your EPUBs and PDFs into audiobooks with high-quality neural voices",
        "desc":    "Convert your EPUB and PDF ebooks to MP3 or M4B audiobooks (with embedded chapters) for free with natural AI voices. Free online text-to-speech converter: upload your book, choose a voice, and download your professional audiobook. No installation needed, works in your browser.",
        "kw":      "epub to audiobook converter, pdf to audiobook, m4b with chapters, free audiobook maker, text to speech audiobook, ai audiobook generator, ebook to mp3, audiobook for dyslexia, accessible audiobook, listen to PDF, elevenlabs alternative free, podcast rss generator",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Free online tool to convert EPUB and PDF ebooks into MP3 and M4B audiobooks (with chapters) using neural AI TTS voices. Supports 6 languages, chapter selection, and podcast RSS feed generation.",
    },
    "fr": {
        "title":   "EPUB/PDF en Livre Audio Gratuit MP3/M4B | Audiobook Maker",
        "tagline": "Convertisseur Gratuit EPUB & PDF en Livre Audio",
        "subtitle":"Convertissez vos EPUB et PDF en livres audio avec des voix neurales",
        "crumb":   "Convertisseur en ligne",
        "desc":    "Convertissez vos ebooks EPUB et PDF en livres audio MP3 et M4B (avec chapitres) gratuitement avec des voix IA naturelles. Convertisseur en ligne gratuit text-to-speech : téléchargez votre livre, choisissez une voix et téléchargez votre livre audio professionnel. Aucune installation, fonctionne dans le navigateur.",
        "kw":      "convertisseur epub livre audio, pdf en livre audio, créer m4b avec chapitres, livre audio gratuit en ligne, text to speech français, synthèse vocale livre, ebook en audio, livre audio dyslexie, livre audio malvoyants, alternative elevenlabs gratuit, générateur podcast rss, audiobook maker",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Outil en ligne gratuit pour convertir des ebooks EPUB e PDF en livres audio MP3 avec des voix neuronales TTS IA. Prend en charge 6 langues et la génération de flux RSS podcast.",
    },
    "es": {
        "title":   "EPUB/PDF a Audiolibro Gratis MP3/M4B | Audiobook Maker",
        "tagline": "Convertidor Gratuito de EPUB y PDF a Audiolibro",
        "subtitle":"Convierte tus EPUB y PDF en audiolibros con voces neurales de alta calidad",
        "desc":    "Convierte tus ebooks EPUB y PDF en audiolibros MP3 y M4B (con capítulos incorporados) gratis con voces IA naturales. Convertidor online gratuito text-to-speech: sube tu libro, elige una voz y descarga tu audiolibro profesional. Sin instalación, funciona desde el navegador.",
        "kw":      "convertidor epub audiolibro, pdf a audiolibro, crear m4b con capítulos, audiolibro gratis online, text to speech español, síntesis de voz libro, ebook en audio, audiolibro para dislexia, audiolibro para ciegos, alternativa elevenlabs gratis, generador podcast rss, audiobook maker",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Herramienta online gratuita para convertir ebooks EPUB y PDF en audiolibros MP3 con voces neuronales TTS IA. Soporta 6 idiomas y generación de feed podcast RSS.",
        "crumb":   "Convertidor online",
    },
    "de": {
        "title":   "EPUB/PDF zu Hörbuch Gratis MP3/M4B | Audiobook Maker",
        "tagline": "Kostenloser EPUB- & PDF-zu-Hörbuch-Konverter",
        "subtitle":"Konvertieren Sie EPUBs und PDFs in Hörbücher mit neuronalen Stimmen",
        "desc":    "Konvertieren Sie Ihre EPUB- und PDF-E-Books kostenlos in MP3- und M4B-Hörbücher (mit eingebetteten Kapiteln) mit natürlichen KI-Stimmen. Kostenloser Online Text-to-Speech Konverter: Laden Sie Ihr Buch hoch, wählen Sie eine Stimme und laden Sie Ihr professionelles Hörbuch herunter. Keine Installation nötig, funktioniert im Browser.",
        "kw":      "epub zu hörbuch konverter, pdf zu hörbuch, m4b mit kapiteln erstellen, hörbuch erstellen kostenlos, text to speech deutsch, sprachsynthese buch, ebook in audio umwandeln, hörbuch für legasthenie, barrierefreies hörbuch, elevenlabs alternative kostenlos, podcast rss generator, audiobook maker",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Kostenloses Online-Tool zum Konvertieren von EPUB- und PDF-E-Books in MP3-Hörbücher mit neuronalen KI-TTS-Stimmen. Unterstützt 6 Sprachen und Podcast-RSS-Feed-Generierung.",
        "crumb":   "Online-Konverter",
    },
    "zh": {
        "title":   "免费在线EPUB/PDF转MP3/M4B有声书转换器 | Audiobook Maker",
        "tagline": "免费EPUB和PDF转有声书转换器",
        "subtitle":"使用高品质神经网络AI语音将EPUB和PDF电子书免费转换为有声读物",
        "desc":    "在您的浏览器中免费、安全、快速地将EPUB和PDF电子书转换为高质量MP3或M4B（含章节）有声读物。由AI神经网络语音驱动。无需安装，支持章节选择和专业M4B格式输出。免费在线文字转语音转换器，支持50多种语言。",
        "kw":      "epub转有声书, pdf转有声书, m4b章节制作, 免费有声书制作, 免费在线文字转语音, 文字转语音有声书, 电子书转mp3, 电子书转音频, ai语音朗读, 阅读障碍有声书, 无障碍有声书, 有声书转换器, elevenlabs替代品, 播客rss生成器, audiobook maker",
        "ld_name": "Audiobook Maker",
        "ld_desc": "免费在线工具，利用神经网络AI文字转语音技术将EPUB和PDF电子书转换为MP3有声书。支持6种语言、章节选择和播客RSS订阅生成。",
        "crumb":   "在线转换器",
    },
    "hi": {
        "title":   "मुफ़्त EPUB/PDF से MP3/M4B ऑडियोबुक कनवर्टर | Audiobook Maker",
        "tagline": "मुफ़्त EPUB और PDF से ऑडियोबुक कनवर्टर",
        "subtitle":"उच्च गुणवत्ता वाली न्यूरल आवाज़ों के साथ अपनी EPUB और PDF को ऑडियोबुक में बदलें",
        "desc":    "अपनी EPUB और PDF ईबुक को प्राकृतिक AI आवाज़ों के साथ मुफ़्त में MP3 या M4B ऑडियोबुक (अध्यायों के साथ) में बदलें. मुफ़्त ऑनलाइन टेक्स्ट-टू-स्पीच कनवर्टर: अपनी पुस्तक अपलोड करें, एक आवाज़ चुनें, और अपनी पेशेवर ऑडियोबुक डाउनलोड करें. कोई इंस्टॉलेशन नहीं, ब्राउज़र में काम करता है.",
        "kw":      "epub से ऑडियोबुक कनवर्टर, pdf से ऑडियोबुक, अध्यायों के साथ m4b, मुफ़्त ऑडियोबुक मेकर, टेक्स्ट टू स्पीच ऑडियोबुक, ai ऑडियोबुक जनरेटर, ebook से mp3, डिस्लेक्सिया के लिए ऑडियोबुक, सुलभ ऑडियोबुक, elevenlabs मुफ़्त विकल्प, पॉडकास्ट rss जनरेटर, audiobook maker",
        "ld_name": "Audiobook Maker",
        "ld_desc": "EPUB और PDF ईबुक को न्यूरल AI TTS आवाज़ों के साथ MP3 और M4B ऑडियोबुक (अध्यायों के साथ) में बदलने के लिए मुफ़्त ऑनलाइन टूल. 7 भाषाओं, अध्याय चयन और पॉडकास्ट RSS फ़ीड जनरेशन का समर्थन.",
        "crumb":   "ऑनलाइन कनवर्टर",
    },
}

_SUPPORTED_LANGS = list(_SEO_DATA.keys())  # ['it', 'en', 'fr', 'es', 'de', 'zh', 'hi']

# Pre-rendering: una copia HTML per lingua, pronta a startup.
# Nessun costo a request-time; ogni risposta è un semplice return di stringa.
HTML_TEMPLATES: dict[str, str] = {
    lang: build_html_template(
        lang=lang,
        seo=seo,
        base_url=BASE_URL,
        version=__version__,
        updated_date=get_formatted_date(),
    )
    for lang, seo in _SEO_DATA.items()
}

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
        updated_date=get_formatted_date(),
    )
    for lang, seo in _SEO_DATA.items()
}


def _detect_lang_from_request() -> str:
    """Rileva la lingua preferita dall'header Accept-Language del browser.

    Scorre i tag di qualità q= e restituisce la prima lingua supportata.
    Fallback: 'en'.
    """
    return _i18n.browser_lang(request.headers.get("Accept-Language", "en"),
                              supported=_SUPPORTED_LANGS, ranked=True, default="en")


@app.after_request
def _set_client_cookie(response):
    """Ensure every response carries the abm_cid cookie for client tracking.

    Sec: il cookie è il bearer di ownership su tutti gli endpoint job (vedi _check_job_owner).
    - secure=True quando la request è HTTPS (anche dietro reverse proxy) per impedire
      interception in chiaro su navigazioni HTTP plain verso lo stesso host.
    - samesite='Lax' mantenuto: il cookie deve essere inviato sui link cliccati dalle
      email di notifica (/dl/<token>) che possono provenire da altri domini.
    """
    if _CLIENT_COOKIE_NAME not in request.cookies:
        cid = str(uuid.uuid4())[:12]
        is_https = (request.scheme == "https") or (request.headers.get("X-Forwarded-Proto", "") == "https")
        response.set_cookie(
            _CLIENT_COOKIE_NAME, cid,
            max_age=_CLIENT_COOKIE_MAX_AGE,
            httponly=True,
            secure=is_https,
            samesite="Lax",
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

# E3 (seam cleanup/tiering/supervisor, 2026-10-10): cleanup loop, eviction,
# riconciliazione offload, marker, memoria e campionatore del carico in
# cleanup.py. Helper e valori della app passati come lambda (risolti a ogni
# chiamata: i test li sostituiscono su questo modulo).
cleanup.configure(
    jobs_lock=_jobs_lock, engine=generation_engine,
    jobs=lambda: jobs,
    upload_dir=lambda: UPLOAD_DIR,
    data_dir=lambda: _DATA_DIR,
    admin_email=lambda: ADMIN_EMAIL,
    email_file_retention_sec=lambda: EMAIL_FILE_RETENTION_SEC,
    gemini_file_retention_sec=lambda: GEMINI_FILE_RETENTION_SEC,
    gemini_no_download_retention_multiplier=lambda: GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER,
    share_ttl_sec=lambda: ABM_SHARE_TTL_SEC,
    acct_settle_map=lambda: _ACCT_SETTLE_MAP,
    _activity_log_dir=lambda *a, **k: _activity_log_dir(*a, **k),
    _log_activity=lambda *a, **k: _log_activity(*a, **k),
    _effective_retention_for_job=lambda *a, **k: _effective_retention_for_job(*a, **k),
    _effective_retention_for_token_info=lambda *a, **k: _effective_retention_for_token_info(*a, **k),
    _send_email=lambda *a, **k: _send_email(*a, **k),
    _smtp_available=lambda *a, **k: _smtp_available(*a, **k),
    _abuse_cleanup_decision=lambda *a, **k: _abuse_cleanup_decision(*a, **k),
    _abuse_keep_state=lambda *a, **k: _abuse_keep_state(*a, **k),
    _active_generating_total_unlocked=lambda *a, **k: _active_generating_total_unlocked(*a, **k),
    _try_send_admin_digest=lambda *a, **k: _try_send_admin_digest(*a, **k),
    _try_send_voxcpm_digest=lambda *a, **k: _try_send_voxcpm_digest(*a, **k))



# ----------------------------------------------------------------------
# ENTRY POINT
# ----------------------------------------------------------------------

# Startup: load persisted download tokens, init DeepSeek, start background threads
# (works both under __main__ and Gunicorn)
_tkstore.load_tokens()
_tkstore.load_transfer_tokens()
_tkstore.load_share_tokens()
_load_device_tokens()
_load_payments()
_load_vouchers()
payment._migrate_paid_opt_to_paid_jobs()
payment._load_paid_jobs_done()
payment._recover_orphaned_voucher_charges(jobs)

# Load persisted client_id → email mapping for cross-job notification fallback
_load_client_emails()

# Configura il motore di generazione (spostato in generation_engine.py)
generation_engine.configure(
    jobs=jobs,
    upload_dir=UPLOAD_DIR,
    download_tokens=_tkstore.download_tokens,
    save_tokens_fn=_tkstore.save_tokens,
    log_activity_fn=_log_activity,
    invalidate_voices_cache_fn=_invalidate_voices_cache,
    jobs_lock=_jobs_lock,
    retention_sec=EMAIL_FILE_RETENTION_SEC,
    gemini_retention_sec=GEMINI_FILE_RETENTION_SEC,
    write_email_marker_fn=cleanup._write_email_marker,
    lookup_client_email_fn=_lookup_client_email,
    build_descriptor_fn=_build_job_descriptor,
    send_push_fn=_push_job_event,
    client_gen_cap_fn=_client_gen_cap_reached,
    account_job_status_fn=accounts.update_status,
    account_token_fn=accounts.set_download_token,
)

if _paypal_available():
    print(f"[startup] PayPal payment enabled (mode: {PAYPAL_MODE}, "
          f"rate: {LLM_RATE_EUR_PER_MCHAR} EUR/Mchar, threshold: {LLM_FREE_THRESHOLD_EUR} EUR)")
else:
    print(f"[startup] PayPal payment disabled (ABM_PAYPAL_CLIENT_ID/SECRET not set)")
_cleanup_started = False

def _cf_probe_tick_sec():
    """Cadenza con cui il sorvegliante guarda l'orologio. Non e' l'intervallo
    fra una sonda e l'altra - quello lo tiene lo stato persistito e raddoppia
    da solo - ma solo la granularita' con cui l'appuntamento viene notato."""
    return env_int("ABM_CF_PROBE_TICK_SEC", 60, floor=10)


def _cf_probe_supervisor():
    """Fa scattare le sonde di rientro su Cloudflare quando sono scadute.

    Vive fuori dai job di proposito: il rientro avviene FRA un job e l'altro,
    mai dentro. Una sintesi che riprovasse Cloudflare da sola rischierebbe
    l'audiolibro dell'utente su un backend ancora guasto; questo thread
    rischia una richiesta HTTP.

    Il ciclo non tiene alcuno stato in memoria: l'appuntamento sta su disco
    (`tts_backend_state.probe_next_at`), quindi un riavvio del processo nel
    mezzo di un failover lungo riprende dal ritmo gia' raggiunto invece di
    ricominciare a bussare ogni mezz'ora.

    Non muore mai: come il sorvegliante del cleanup, un'eccezione qui
    lascerebbe un failover aperto per sempre senza che nulla lo segnali.
    """
    if gemini_tts is None:
        return
    tick = _cf_probe_tick_sec()
    while True:
        try:
            time.sleep(tick)
            for model_key in list(gemini_tts.GEMINI_MODELS):
                if tts_backend_state.probe_due(model_key):
                    gemini_tts.probe_cloudflare(model_key)
        except Exception as e:
            print(f"[cf-probe] giro fallito (non-fatale): "
                  f"{type(e).__name__}: {e}", flush=True)


def _start_activity_sync():
    """Allinea activity.db ai file in un thread, solo con ABM_ACTIVITY_DB
    dual|db. Finche' non ha finito il modo db legge dal file."""
    if activity_log.mode() == "off":
        return None
    t = threading.Thread(target=activity_log.sync_all, daemon=True,
                         name="activity-sync")
    t.start()
    return t


def _warn_stale_activity_logs(script_dir, log_dir, today=None):
    """ABM_ACTIVITY_LOG_DIR sposta i log fuori da SCRIPT_DIR (fase 2): se
    SCRIPT_DIR contiene ancora file degli ultimi 3 mesi (corrente + 2
    precedenti) nessuno li legge piu' ne' li scrive - restano li' morti.
    Avvisa una volta all'avvio; ritorna i nomi trovati (anche se log_dir
    coincide con script_dir, nel qual caso e' sempre vuoto)."""
    script_dir = Path(script_dir).resolve()
    log_dir = Path(log_dir).resolve()
    if log_dir == script_dir:
        return []
    when = today or datetime.now()
    months = set()
    y, m = when.year, when.month
    for _ in range(3):
        months.add(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    try:
        names = [p.name for p in script_dir.glob("activity_*.log")]
    except OSError:
        return []
    stale = sorted(n for n in names if n[len("activity_"):-len(".log")] in months)
    if stale:
        print(f"[activity_log] ATTENZIONE: log in SCRIPT_DIR non letti: "
              f"{', '.join(stale)}")
    return stale


def _ensure_background_threads():
    global _cleanup_started
    if _cleanup_started:
        return
    _cleanup_started = True
    load_metrics.configure(_DATA_DIR)
    load_metrics.incr("boot")
    assembly_queue.set_observer(cleanup._assembly_metrics_observer)
    if load_metrics.ENABLED:
        threading.Thread(target=cleanup._load_metrics_supervisor, daemon=True).start()
    threading.Thread(target=get_voices, daemon=True).start()
    threading.Thread(target=cleanup._cleanup_supervisor, daemon=True).start()
    _start_activity_sync()
    _warn_stale_activity_logs(SCRIPT_DIR, activity_log._dir())
    if db.is_ready():
        threading.Thread(target=cleanup._account_maintenance_supervisor, daemon=True).start()
    # Recupero job batch interrotti dal riavvio (eseguito una sola volta al boot).
    threading.Thread(target=recovery._recover_orphan_jobs, daemon=True).start()
    # Rientro automatico su Cloudflare: il sorvegliante delle sonde. Parte
    # sempre che gemini_tts sia caricato, anche senza failover in corso - e'
    # lui a notare quello che un riavvio ha trovato gia' aperto sul disco.
    if gemini_tts is not None:
        threading.Thread(target=_cf_probe_supervisor, daemon=True).start()
    # Moderazione anti-abuso: worker di giudizio a giudice singolo. All'avvio
    # con kill accesa i verdetti maturati in osservazione vengono azzerati.
    try:
        _cleared = abuse_watch.arm_on_startup()
        if _cleared:
            print(f"[startup] abuse_watch: kill armata, {_cleared} verdetti azzerati", flush=True)
        abuse_watch.start_worker(_abuse_apply_verdict)
    except Exception as _aw_err:
        print(f"[startup] abuse_watch init failed (non-fatal): {_aw_err}", flush=True)

    # Voci campionate (spec 2026-09-09, piano 2): notifier, hook di rilancio
    # e rimborso, provider del digest, recovery al boot, sweeper supervisionato.
    try:
        voice_clone_demo.configure(notifier=routes_voice_clone._voice_clone_notify)
        voice_clone.set_hooks(
            notify=routes_voice_clone._voice_clone_notify,
            relaunch=lambda cid: voice_clone_demo.start_demos(cid),
            refund=lambda cid, reason: voice_clone_demo.refund(
                cid, reason, bonus=(reason == "demo_failed_timeout")))
        email_service.set_voice_clone_provider(voice_clone.digest_data)
        if voxcpm_tts is not None and voice_clone.enabled():
            n = voice_clone_demo.recover()
            if n:
                print(f"[voice_clone] recover: {n} generazioni demo rilanciate", flush=True)
            voice_clone_demo.start_denoise_backfill()
        threading.Thread(target=cleanup._voice_clone_sweep_supervisor, daemon=True,
                         name="voice-clone-sweep").start()
    except Exception as e:      # noqa: BLE001
        print(f"[voice_clone] cablaggio non riuscito: {e}", flush=True)

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
    print(f"[startup] Max concurrent global: "
          f"{MAX_CONCURRENT_GLOBAL if MAX_CONCURRENT_GLOBAL > 0 else 'unlimited'}")
    print(f"[startup] Max concurrent LLM per client: {MAX_CONCURRENT_LLM_PER_CLIENT}")
    print(f"[startup] Max concurrent assembly (encode FFmpeg): "
          f"{assembly_queue.MAX_CONCURRENT_ASSEMBLY}")
    print(f"[startup] Load metrics: "
          f"{'on' if load_metrics.ENABLED else 'off'} "
          f"(sample {load_metrics.SAMPLE_SEC}s, bucket {load_metrics.BUCKET_SEC}s, "
          f"retention {load_metrics.RETENTION_MONTHS} mesi)")
    print(f"[startup] Audit JSONL retention: costi {jsonl_audit.cost_keep_months()} mesi, "
          f"judge/leak/code tagliate {jsonl_audit.audit_keep_months()} mesi (purge giornaliera)")
    if _llm_available():
        print(f"[startup] LLM text optimization enabled (Model: {LLM_MODEL})")
    if ADMIN_EMAIL:
        print(f"[startup] Admin digest enabled  ->  {ADMIN_EMAIL} (interval: {ADMIN_DIGEST_INTERVAL_SEC}s)")
        print(f"[startup] VoxCPM daily digest: "
              f"{'on' if VOXCPM_DIGEST else 'off (ABM_VOXCPM_DIGEST=0)'}")
    else:
        print("[startup] Admin digest disabled (ABM_ADMIN_EMAIL not set)")
    if gemini_tts is not None:
        print(f"[startup] Rientro TTS su Cloudflare: "
              f"{'sonda attiva' if gemini_tts._cf_probe_enabled() else 'off (ABM_CF_PROBE_ENABLE=0)'} "
              f"(prima sonda dopo {gemini_tts._cf_probe_first_sec()}s, "
              f"tetto {gemini_tts._cf_probe_max_sec()}s, "
              f"controllo ogni {_cf_probe_tick_sec()}s)")
    print(f"[startup] Abuse moderation: "
          f"{'kill ON' if abuse_watch.kill_enabled() else 'observation only'} "
          f"(confidence >= {abuse_watch.confidence_threshold():.2f}, "
          f"keep {abuse_watch.keep_hours()}h)")
    # Senza questa riga la caduta dei giudizi semantici e' invisibile nei
    # log: moderazione e traduzioni continuano a funzionare sul motore LLM
    # di ripiego, quindi nulla segnala che System One non sta girando.
    if semantic_judge.is_available():
        print("[startup] Giudizi semantici: on "
              f"(timeout {semantic_judge.timeout_sec():.0f}s)")
    else:
        _sj_why = (
            f"SDK non importato ({semantic_judge.sdk_import_error()})"
            if semantic_judge.sdk_import_error()
            else "ABM_TYPESAFE_ENABLE=0" if not semantic_judge.enabled()
            else "ABM_TYPESAFE_API_KEY assente"
        )
        print(f"[startup] Giudizi semantici: off ({_sj_why}); moderazione e "
              f"traduzioni community sul motore LLM di ripiego")
    # Il modo dei singoli punti non si deduce dalla riga sopra: con la chiave
    # presente e i modi al default `observe` il servizio viene interrogato e
    # l'audit si riempie, ma nessuno di questi controlli tocca quello che
    # l'utente riceve. In prod le ABM_* stanno nell'unit e la shell ssh non
    # le eredita, quindi il log e' l'unico posto dove leggerle davvero.
    _sj_punti = []
    for _sj_nome, _sj_mod in (("sezioni", "section_judge"),
                              ("output", "llm_output_judge"),
                              ("lingua-voce", "voice_language_guard"),
                              ("trascrizione", "transcript_judge"),
                              ("traduzione", "translation_judge")):
        try:
            _sj_m = __import__(_sj_mod)
            _sj_punti.append(f"{_sj_nome}={_sj_m.mode()}"
                             f"{'' if _sj_m.enabled() else '*'}")
        except Exception as _sj_e:      # noqa: BLE001 - mai bloccante
            _sj_punti.append(f"{_sj_nome}=?({type(_sj_e).__name__})")
    print(f"[startup] Modi dei giudizi: {', '.join(_sj_punti)} "
          f"(* = inerte, il canale e' spento; solo `on` agisce, "
          f"`observe` misura e basta)")

activity_log.init_dedup()
_ensure_background_threads()

if __name__ == "__main__":
    PORT = env_int("ABM_PORT", 5601)
    DEBUG = env_bool("ABM_DEBUG", False)
    print(f"\n{'='*50}")
    print(f"  Audiobook Maker v{__version__}")
    print(f"  http://localhost:{PORT}")
    print(f"{'='*50}")
    print(f"  Script folder: {SCRIPT_DIR}")
    print(f"  Data folder:   {UPLOAD_DIR}")
    print(f"  Activity log:  {_activity_log_dir() / 'activity_YYYY-MM.log'}")
    _max_text_chars_startup = os.environ.get("ABM_MAX_TEXT_CHARS", "1500000")
    print(f"  ABM_MAX_TEXT_CHARS: {_max_text_chars_startup} "
          f"({'env' if 'ABM_MAX_TEXT_CHARS' in os.environ else 'default'})")
    _max_gemini_text_chars_startup = os.environ.get("ABM_MAX_GEMINI_TEXT_CHARS", "800000")
    print(f"  ABM_MAX_GEMINI_TEXT_CHARS: {_max_gemini_text_chars_startup} "
          f"({'env' if 'ABM_MAX_GEMINI_TEXT_CHARS' in os.environ else 'default'})")
    _job_retention_startup = os.environ.get("ABM_JOB_RETENTION_SEC", "64800")
    print(f"  ABM_JOB_RETENTION_SEC: {_job_retention_startup}s "
          f"(~{int(_job_retention_startup)//3600}h) "
          f"({'env' if 'ABM_JOB_RETENTION_SEC' in os.environ else 'default'})")
    _gemini_retention_startup = os.environ.get("ABM_GEMINI_JOB_RETENTION_SEC", "172800")
    print(f"  ABM_GEMINI_JOB_RETENTION_SEC: {_gemini_retention_startup}s "
          f"(~{int(_gemini_retention_startup)//3600}h) "
          f"({'env' if 'ABM_GEMINI_JOB_RETENTION_SEC' in os.environ else 'default'})")
    print(f"  Debug mode: {DEBUG} "
          f"({'env ABM_DEBUG' if 'ABM_DEBUG' in os.environ else 'default off'})")
    print(f"{'='*50}\n")
    app.run(host="127.0.0.1", port=PORT, debug=DEBUG)
