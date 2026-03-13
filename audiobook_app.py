#!/usr/bin/env python3
"""
Audiobook Maker — Web app to convert EPUB/PDF into MP3 audiobooks.

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
from copy import copy
from pathlib import Path

from flask import (
    Flask, render_template_string, request, jsonify,
    send_file, Response, stream_with_context
)

# ── Import epub_to_tts (must be in the same folder) ──
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
    print("WARNING: pdf_to_tts.py not found — PDF support disabled.", file=sys.stderr)

try:
    import edge_tts
except ImportError:
    print("ERROR: edge-tts not installed. Run: pip install edge-tts", file=sys.stderr)
    sys.exit(1)


# ── Import version and template builder ──
from version import __version__
from templates.index_page import build_html_template



# ═══════════════════════════════════════════════════════════════════
# APP CONFIG
# ═══════════════════════════════════════════════════════════════════

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB

# Directory di lavoro persistente (sopravvive ai restart del servizio)
# Configurabile via ABM_DATA_DIR, default: /var/lib/audiobook-maker/data
_DATA_DIR = os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data")
UPLOAD_DIR = Path(_DATA_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

jobs = {}

# ── Email notification config ──
# Configure via environment variables on the server:
#   export ABM_SMTP_HOST=smtp.gmail.com
#   export ABM_SMTP_PORT=587
#   export ABM_SMTP_USER=your@email.com
#   export ABM_SMTP_PASS=your-app-password
#   export ABM_SMTP_FROM=noreply@audiobook-maker.com
#   export ABM_BASE_URL=https://audiobook-maker.com
SMTP_HOST = os.environ.get("ABM_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("ABM_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("ABM_SMTP_USER", "")
SMTP_PASS = os.environ.get("ABM_SMTP_PASS", "")
SMTP_FROM = os.environ.get("ABM_SMTP_FROM", SMTP_USER or "noreply@audiobook-maker.com")
BASE_URL = os.environ.get("ABM_BASE_URL", "").rstrip("/")
EMAIL_FILE_RETENTION_SEC = 24 * 60 * 60  # 24 ore di retention dopo invio email

# ── Admin activity digest (email log) ──
# Set ABM_ADMIN_EMAIL to enable. Leave empty to disable.
#   export ABM_ADMIN_EMAIL=gfrangiamone@gmail.com
# Rate limited: max 1 digest email per hour, batches all pending events.
ADMIN_EMAIL = os.environ.get("ABM_ADMIN_EMAIL", "")
ADMIN_DIGEST_INTERVAL_SEC = 60 * 60  # 1 ora tra un digest e il successivo
_admin_queue = []          # list of dicts: {title, author, filename, voice, chapters, words, duration_est, timestamp}
_admin_queue_lock = threading.Lock()
_admin_last_sent = 0.0     # timestamp dell'ultimo digest inviato

# ── Client tracking & rate limiting ──
# Max concurrent generating jobs per client device (cookie-based).
# Set via ABM_MAX_CONCURRENT_PER_CLIENT env var; default 2.
MAX_CONCURRENT_PER_CLIENT = int(os.environ.get("ABM_MAX_CONCURRENT_PER_CLIENT", "2"))

# Cookie name and max-age for client identification
_CLIENT_COOKIE_NAME = "abm_cid"
_CLIENT_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # 1 year


def _get_client_id():
    """Return the client_id from cookie, or generate a new one (will be set later)."""
    return request.cookies.get(_CLIENT_COOKIE_NAME, "")


def _get_client_ip():
    """Return client IP address, respecting reverse proxy headers."""
    # X-Forwarded-For: client, proxy1, proxy2 → take the first
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def _get_browser_lang():
    """Return primary browser language from Accept-Language header (e.g. 'it', 'en', 'fr')."""
    accept = request.headers.get("Accept-Language", "")
    if not accept:
        return ""
    # Parse first language tag: "it-IT,it;q=0.9,en;q=0.8" → "it"
    first = accept.split(",")[0].split(";")[0].strip()
    # Return just the primary subtag (e.g. "it-IT" → "it")
    return first.split("-")[0].lower() if first else ""


def _active_generating_for_client(client_id):
    """Count how many jobs are currently generating for the given client_id."""
    if not client_id:
        return 0
    return sum(
        1 for j in jobs.values()
        if j.get("client_id") == client_id and j.get("status") == "generating"
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


def _smtp_available():
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS and BASE_URL)


def _send_email(to_addr, subject, html_body):
    """Send an HTML email via SMTP. Returns True on success."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    if not _smtp_available():
        print(f"[email] SMTP not configured, cannot send to {to_addr}")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_FROM
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if SMTP_PORT == 465:
            # SSL diretto (porta 465)
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_FROM, to_addr, msg.as_string())
        else:
            # STARTTLS (porta 587) o plain (porta 25)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.ehlo()
                if SMTP_PORT != 25:
                    server.starttls()
                    server.ehlo()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_FROM, to_addr, msg.as_string())
        print(f"[email] Sent to {to_addr}: {subject}")
        return True
    except Exception as e:
        print(f"[email] Failed to send to {to_addr}: {e}")
        return False


# ── Admin activity digest ──

def _admin_notify_generation(job_id, info, voice, filename):
    """Queue a generation event for admin digest. Thread-safe."""
    if not ADMIN_EMAIL:
        return
    from datetime import datetime
    event = {
        "title": getattr(info, "title", "") or filename,
        "author": getattr(info, "author", "") or "—",
        "filename": filename,
        "voice": voice,
        "chapters": len(info.chapters) if hasattr(info, "chapters") else 0,
        "words": getattr(info, "total_words", 0),
        "duration_est": f"{getattr(info, 'estimated_duration_minutes', 0):.0f} min",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with _admin_queue_lock:
        _admin_queue.append(event)
    print(f"[admin] Queued notification for '{event['title']}' ({len(_admin_queue)} pending)")
    # Try to send immediately (respects rate limit)
    _try_send_admin_digest()


def _try_send_admin_digest():
    """Send admin digest if rate limit allows. Called from generation and cleanup loop."""
    global _admin_last_sent
    if not ADMIN_EMAIL or not _smtp_available():
        return
    with _admin_queue_lock:
        if not _admin_queue:
            return
        now = time.time()
        if (now - _admin_last_sent) < ADMIN_DIGEST_INTERVAL_SEC:
            return  # Troppo presto, aspetta il prossimo ciclo
        # Prendi tutti gli eventi in coda e svuota
        events = list(_admin_queue)
        _admin_queue.clear()
        _admin_last_sent = now

    # Build and send digest email
    from datetime import datetime
    count = len(events)
    subject = f"📚 Audiobook Maker: {count} nuov{'o' if count == 1 else 'i'} libr{'o' if count == 1 else 'i'} in elaborazione"

    rows = ""
    for e in events:
        rows += f"""<tr>
<td style="padding:8px 12px;border-bottom:1px solid #eee">{e['timestamp']}</td>
<td style="padding:8px 12px;border-bottom:1px solid #eee"><strong>{e['title']}</strong><br>
<span style="color:#666;font-size:13px">{e['author']}</span></td>
<td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:13px">{e['filename']}</td>
<td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:center">{e['chapters']}</td>
<td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right">{e['words']:,}</td>
<td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:center">{e['duration_est']}</td>
<td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:12px;color:#888">{e['voice']}</td>
</tr>"""

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head><body style="font-family:system-ui,-apple-system,sans-serif;color:#333;max-width:900px;margin:0 auto;padding:20px">
<div style="background:linear-gradient(135deg,#1a3c5e,#2c5f8a);color:white;padding:20px 24px;border-radius:12px 12px 0 0">
<h2 style="margin:0">🎧 Audiobook Maker — Activity Digest</h2>
<p style="margin:8px 0 0;opacity:.85">{count} elaborazion{'e' if count == 1 else 'i'} avviat{'a' if count == 1 else 'e'} — {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
</div>
<table style="width:100%;border-collapse:collapse;background:white;border:1px solid #ddd;border-top:none">
<thead><tr style="background:#f0f5fa">
<th style="padding:10px 12px;text-align:left;font-size:13px;color:#555">Ora</th>
<th style="padding:10px 12px;text-align:left;font-size:13px;color:#555">Libro</th>
<th style="padding:10px 12px;text-align:left;font-size:13px;color:#555">File</th>
<th style="padding:10px 12px;text-align:center;font-size:13px;color:#555">Cap.</th>
<th style="padding:10px 12px;text-align:right;font-size:13px;color:#555">Parole</th>
<th style="padding:10px 12px;text-align:center;font-size:13px;color:#555">Durata</th>
<th style="padding:10px 12px;text-align:left;font-size:13px;color:#555">Voce</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
<p style="color:#999;font-size:12px;margin-top:16px;padding:0 4px">Questo messaggio è generato automaticamente da Audiobook Maker.
Per disattivare, rimuovere la variabile ABM_ADMIN_EMAIL dalla configurazione del server.</p>
</body></html>"""

    try:
        _send_email(ADMIN_EMAIL, subject, html)
        print(f"[admin] Digest sent to {ADMIN_EMAIL}: {count} event(s)")
    except Exception as e:
        # Re-queue events so they're not lost
        with _admin_queue_lock:
            _admin_queue.extend(events)
        print(f"[admin] Digest send failed, {count} events re-queued: {e}")


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
        "epub_path": job.get("epub_path", ""),
        "podcast_safe_name": job.get("podcast_safe_name", ""),
        "podcast_ready": job.get("podcast_ready", False),
        "podcast_mp3s": job.get("podcast_mp3s", []),
        "podcast_info_title": info.title if info else "",
        "podcast_info_author": info.author if info else "",
        "podcast_info_language": info.language if info else "",
        "original_filename": job.get("original_filename", ""),
        "lang": lang,
    }
    _save_tokens()
    job["email_token"] = token
    job["email_sent_at"] = time.time()

    dl_url = f"{BASE_URL}/dl/{token}" if BASE_URL else f"/dl/{token}"

    # RSS XML filename for podcast
    safe_name = job.get("podcast_safe_name", _safe_filename(book_title) or "audiolibro")
    rss_filename = f"{safe_name}_podcast.xml"
    rss_url = f"{base_url}/{rss_filename}" if base_url else rss_filename

    # ── i18n email content ──
    _email_i18n = {
        "it": {
            "subject": f"Audiobook Maker — \"{book_title}\" pronto per il download",
            "heading": "&#x1F3A7; Il tuo audiolibro &egrave; pronto!",
            "body": f"La generazione di <strong>{book_title}</strong> &egrave; stata completata con successo.",
            "btn": "&#x2B07;&#xFE0F; Scarica i tuoi file",
            "warn": "&#x23F0; Attenzione: i file saranno disponibili per il download soltanto per 24 ore a partire dalla ricezione di questa email. Dopo tale periodo verranno cancellati automaticamente.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Istruzioni per la pubblicazione del Podcast</strong>",
            "podcast_p1": f"Il file ZIP scaricato contiene tutti i file necessari per il tuo podcast. Per renderlo fruibile online, <strong>decomprimi il file ZIP</strong> e carica tutti i file contenuti sul tuo server web, in modo che siano raggiungibili all'indirizzo:",
            "podcast_p2": f"Il file XML del feed RSS del podcast sar&agrave;:",
            "podcast_p3": f"Per rendere il podcast disponibile su app come <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> o altri aggregatori, fornisci l'indirizzo del file XML come URL del feed.",
            "footer": "Questa email &egrave; stata generata automaticamente da Audiobook Maker.",
        },
        "en": {
            "subject": f"Audiobook Maker — \"{book_title}\" ready for download",
            "heading": "&#x1F3A7; Your audiobook is ready!",
            "body": f"The generation of <strong>{book_title}</strong> has been completed successfully.",
            "btn": "&#x2B07;&#xFE0F; Download your files",
            "warn": "&#x23F0; Please note: the files will be available for download for 24 hours only from the time you receive this email. After that, they will be automatically deleted.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Podcast Publishing Instructions</strong>",
            "podcast_p1": f"The downloaded ZIP file contains all the files needed for your podcast. To make it available online, <strong>extract the ZIP file</strong> and upload all files to your web server so they are reachable at:",
            "podcast_p2": f"The podcast RSS feed XML file will be:",
            "podcast_p3": f"To make the podcast available on apps like <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> or other aggregators, provide the XML file URL as the feed URL.",
            "footer": "This email was automatically generated by Audiobook Maker.",
        },
        "fr": {
            "subject": f"Audiobook Maker — \"{book_title}\" pr&ecirc;t au t&eacute;l&eacute;chargement",
            "heading": "&#x1F3A7; Votre livre audio est pr&ecirc;t !",
            "body": f"La g&eacute;n&eacute;ration de <strong>{book_title}</strong> a &eacute;t&eacute; compl&eacute;t&eacute;e avec succ&egrave;s.",
            "btn": "&#x2B07;&#xFE0F; T&eacute;l&eacute;charger vos fichiers",
            "warn": "&#x23F0; Attention : les fichiers seront disponibles au t&eacute;l&eacute;chargement pendant 24 heures seulement &agrave; compter de la r&eacute;ception de cet email. Pass&eacute; ce d&eacute;lai, ils seront automatiquement supprim&eacute;s.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Instructions de publication du podcast</strong>",
            "podcast_p1": f"Le fichier ZIP t&eacute;l&eacute;charg&eacute; contient tous les fichiers n&eacute;cessaires &agrave; votre podcast. Pour le rendre accessible en ligne, <strong>d&eacute;compressez le fichier ZIP</strong> et t&eacute;l&eacute;versez tous les fichiers sur votre serveur web, de sorte qu'ils soient accessibles &agrave; l'adresse :",
            "podcast_p2": f"Le fichier XML du flux RSS du podcast sera :",
            "podcast_p3": f"Pour rendre le podcast disponible sur des apps comme <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> ou d'autres agr&eacute;gateurs, fournissez l'URL du fichier XML comme URL du flux.",
            "footer": "Cet email a &eacute;t&eacute; g&eacute;n&eacute;r&eacute; automatiquement par Audiobook Maker.",
        },
        "es": {
            "subject": f"Audiobook Maker — \"{book_title}\" listo para descargar",
            "heading": "&#x1F3A7; &iexcl;Tu audiolibro est&aacute; listo!",
            "body": f"La generaci&oacute;n de <strong>{book_title}</strong> se ha completado con &eacute;xito.",
            "btn": "&#x2B07;&#xFE0F; Descarga tus archivos",
            "warn": "&#x23F0; Atenci&oacute;n: los archivos estar&aacute;n disponibles para descargar solo durante 24 horas desde la recepci&oacute;n de este email. Despu&eacute;s de ese periodo se eliminar&aacute;n autom&aacute;ticamente.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Instrucciones para publicar el podcast</strong>",
            "podcast_p1": f"El archivo ZIP descargado contiene todos los archivos necesarios para tu podcast. Para hacerlo accesible en l&iacute;nea, <strong>descomprime el archivo ZIP</strong> y sube todos los archivos a tu servidor web para que sean accesibles en:",
            "podcast_p2": f"El archivo XML del feed RSS del podcast ser&aacute;:",
            "podcast_p3": f"Para que el podcast est&eacute; disponible en apps como <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> u otros agregadores, proporciona la URL del archivo XML como URL del feed.",
            "footer": "Este email fue generado autom&aacute;ticamente por Audiobook Maker.",
        },
        "de": {
            "subject": f"Audiobook Maker — \"{book_title}\" bereit zum Download",
            "heading": "&#x1F3A7; Dein H&ouml;rbuch ist fertig!",
            "body": f"Die Generierung von <strong>{book_title}</strong> wurde erfolgreich abgeschlossen.",
            "btn": "&#x2B07;&#xFE0F; Dateien herunterladen",
            "warn": "&#x23F0; Hinweis: Die Dateien stehen nur 24 Stunden ab Erhalt dieser E-Mail zum Download bereit. Danach werden sie automatisch gel&ouml;scht.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Anleitung zur Podcast-Ver&ouml;ffentlichung</strong>",
            "podcast_p1": f"Die heruntergeladene ZIP-Datei enth&auml;lt alle Dateien f&uuml;r deinen Podcast. Um ihn online verf&uuml;gbar zu machen, <strong>entpacke die ZIP-Datei</strong> und lade alle Dateien auf deinen Webserver hoch, sodass sie unter folgender Adresse erreichbar sind:",
            "podcast_p2": f"Die XML-Datei des Podcast-RSS-Feeds lautet:",
            "podcast_p3": f"Um den Podcast in Apps wie <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> oder anderen Aggregatoren verf&uuml;gbar zu machen, gib die URL der XML-Datei als Feed-URL an.",
            "footer": "Diese E-Mail wurde automatisch von Audiobook Maker generiert.",
        },
        "zh": {
            "subject": f"Audiobook Maker — \"{book_title}\" \u5df2\u51c6\u5907\u597d\u4e0b\u8f7d",
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

    t = _email_i18n.get(lang, _email_i18n["en"])

    # ── Podcast section (only for podcast downloads) ──
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

# ── Activity log ──
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


# ═══════════════════════════════════════════════════════════════════
# VOICE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

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
        })

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


# ═══════════════════════════════════════════════════════════════════
# AUDIO GENERATION
# ═══════════════════════════════════════════════════════════════════

CHUNK_MAX_CHARS = 2000


def split_text_into_chunks(text, max_chars=CHUNK_MAX_CHARS):
    paragraphs = text.split("\n")
    chunks = []
    current = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            if current:
                current += "\n"
            continue
        if len(current) + len(para) + 1 > max_chars:
            if current.strip():
                chunks.append(current.strip())
            if len(para) > max_chars:
                sentences = []
                for sep in [". ", "! ", "? ", "; "]:
                    if sep in para:
                        parts = para.split(sep)
                        sentences = [p + sep.strip() for p in parts[:-1]] + [parts[-1]]
                        break
                if not sentences:
                    sentences = [para]
                temp = ""
                for s in sentences:
                    if len(temp) + len(s) + 1 > max_chars:
                        if temp.strip():
                            chunks.append(temp.strip())
                        temp = s
                    else:
                        temp = (temp + " " + s) if temp else s
                current = temp
            else:
                current = para
        else:
            current = (current + " " + para) if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [text]


async def generate_chunk_mp3(text, voice, rate, output_path, max_retries=3):
    """Generate MP3 from text via edge-tts with retry and fallback."""
    # Sanitize text: remove characters that commonly cause NoAudioReceived
    import re as _re
    clean = text.strip()
    if not clean:
        _generate_silence_mp3(output_path, duration_sec=1)
        return
    # Remove control characters (except newline/tab), zero-width chars, surrogates
    clean = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u2028-\u202f\ufeff\ufffe\uffff]', '', clean)
    # Collapse excessive whitespace
    clean = _re.sub(r'\n{3,}', '\n\n', clean)
    clean = _re.sub(r' {3,}', ' ', clean)
    if not clean.strip():
        _generate_silence_mp3(output_path, duration_sec=1)
        return

    last_error = None
    for attempt in range(max_retries):
        try:
            communicate = edge_tts.Communicate(text=clean, voice=voice, rate=rate)
            await communicate.save(output_path)
            return  # Success
        except Exception as e:
            last_error = e
            wait = 2 ** attempt  # 1s, 2s, 4s
            snippet = clean[:60].replace('\n', ' ')
            print(f"[tts] Attempt {attempt+1}/{max_retries} failed for chunk "
                  f"({len(clean)} chars: \"{snippet}...\"): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(wait)

    # All retries failed: generate silence as fallback so the book continues
    print(f"[tts] WARNING: All {max_retries} attempts failed, generating silence for chunk "
          f"({len(clean)} chars). Last error: {last_error}")
    _generate_silence_mp3(output_path, duration_sec=1)
    return False  # Signal failure (silence was generated instead)


def _strip_parenthetical(text):
    """Remove parenthetical content from text for cleaner TTS output.

    Strips text inside round () and square [] brackets, including nested ones.
    Cleans up resulting double spaces and leading punctuation after removal.
    """
    import re
    # Iteratively remove innermost brackets to handle nesting
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r'\([^()]*\)', '', text)
        text = re.sub(r'\[[^\[\]]*\]', '', text)
    # Clean up: collapse multiple spaces, fix orphan punctuation (e.g. " , " -> ", ")
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s+([,;:.!?])', r'\1', text)
    return text.strip()


def _plan_chunks(info):
    plan = []
    for ch in info.chapters:
        clean_text = _strip_parenthetical(ch.text)
        full_text = f"{ch.title}.\n\n{clean_text}"
        chunks = split_text_into_chunks(full_text)
        for ci, chunk_text in enumerate(chunks):
            plan.append({
                "chapter_index": ch.index,
                "chapter_title": ch.title,
                "chunk_index": ci,
                "chunks_in_chapter": len(chunks),
                "text": chunk_text,
                "chars": len(chunk_text),
            })
    return plan


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


def _include_cover_in_dir(job, target_dir):
    """Copy book cover image into target_dir so it gets included in the ZIP.

    Tries the cover_thumb extracted during analysis first; if not available,
    attempts extraction from the source EPUB/ABM file.
    """
    try:
        cover_src = job.get("cover_thumb", "")
        if cover_src and os.path.exists(cover_src):
            ext = os.path.splitext(cover_src)[1] or ".jpg"
            dest = os.path.join(str(target_dir), f"cover{ext}")
            shutil.copy2(cover_src, dest)
            print(f"[zip-cover] Included cover from thumb: {dest}")
            return True

        # Fallback: try to extract from source file
        epub_path = job.get("epub_path", "")
        if epub_path and os.path.exists(epub_path):
            dest = os.path.join(str(target_dir), "cover.jpg")
            if _extract_cover_from_epub(epub_path, dest, target_size=1400):
                print(f"[zip-cover] Included cover extracted from EPUB: {dest}")
                return True
            # Try raw extraction without Pillow
            raw_path, _ = _extract_cover_for_preview(epub_path, str(target_dir))
            if raw_path and os.path.exists(raw_path):
                raw_ext = os.path.splitext(raw_path)[1] or ".jpg"
                final = os.path.join(str(target_dir), f"cover{raw_ext}")
                if raw_path != final:
                    shutil.copy2(raw_path, final)
                    os.remove(raw_path)
                print(f"[zip-cover] Included cover (raw) from EPUB: {final}")
                return True
    except Exception as e:
        print(f"[zip-cover] Could not include cover: {e}")
    return False


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
            prev_chapter_idx = -1
            failed_chunks = 0
            for i, block in enumerate(plan):
                if _check_cancelled():
                    raise _CancelledError("Job cancelled")
                _update_progress(i, block)
                # Silenzio all'inizio di ogni capitolo
                if block["chapter_index"] != prev_chapter_idx:
                    if os.path.exists(silence_path):
                        all_parts.append(silence_path)
                    prev_chapter_idx = block["chapter_index"]
                part_path = str(work_dir / f"chunk_{i:06d}.mp3")
                result = loop.run_until_complete(generate_chunk_mp3(block["text"], voice, rate, part_path))
                if result is False:
                    failed_chunks += 1
                all_parts.append(part_path)
                job["processed_chars"] += block["chars"]
                if os.path.exists(part_path):
                    job["bytes_generated"] += os.path.getsize(part_path)

            job["progress_message"] = "Merging audio..."
            safe_name = _safe_filename(info.title) or "audiolibro"
            final_mp3 = str(output_dir / f"{safe_name}.mp3")
            _concatenate_mp3(all_parts, final_mp3)
            for p in all_parts:
                if os.path.exists(p) and p != silence_path:
                    os.remove(p)
            job["output_files"] = [final_mp3]
            job["output_name"] = f"{safe_name}.mp3"
            if os.path.exists(final_mp3):
                job["bytes_generated"] = os.path.getsize(final_mp3)
        else:
            mp3_files = []
            current_chapter_parts = []
            current_chapter_idx = -1
            failed_chunks = 0
            # Dict for O(1) lookup — supports non-contiguous indices (filtered chapters)
            chapter_by_idx = {ch.index: ch for ch in info.chapters}
            for i, block in enumerate(plan):
                if _check_cancelled():
                    raise _CancelledError("Job cancelled")
                _update_progress(i, block)
                if block["chapter_index"] != current_chapter_idx:
                    if current_chapter_parts and current_chapter_idx >= 0:
                        ch = chapter_by_idx[current_chapter_idx]
                        safe_title = _safe_filename(ch.title)[:50] or f"ch_{current_chapter_idx}"
                        mp3_path = str(output_dir / f"{current_chapter_idx:03d}_{safe_title}.mp3")
                        _concatenate_mp3(current_chapter_parts, mp3_path)
                        mp3_files.append(mp3_path)
                        for p in current_chapter_parts:
                            if os.path.exists(p) and p != silence_path:
                                os.remove(p)
                    current_chapter_parts = []
                    current_chapter_idx = block["chapter_index"]
                    # Silenzio all'inizio del capitolo
                    if os.path.exists(silence_path):
                        current_chapter_parts.append(silence_path)

                part_path = str(work_dir / f"chunk_{i:06d}.mp3")
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
                mp3_path = str(output_dir / f"{current_chapter_idx:03d}_{safe_title}.mp3")
                _concatenate_mp3(current_chapter_parts, mp3_path)
                mp3_files.append(mp3_path)
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
        import traceback
        traceback.print_exc()
    finally:
        loop.close()


def _zip_safe_read(zf, path):
    """Read a file from a ZipFile, handling path separator mismatches.

    ZIP entries always use forward slashes, but OPF href or os.path.join
    may produce backslashes on Windows. Tries: exact path → normalized →
    basename match.
    """
    # 1. Try exact path
    if path in zf.namelist():
        return zf.read(path)
    # 2. Normalize separators
    normalized = path.replace("\\", "/")
    if normalized in zf.namelist():
        return zf.read(normalized)
    # 3. Match by basename (last resort)
    target = os.path.basename(normalized).lower()
    for entry in zf.namelist():
        if os.path.basename(entry).lower() == target:
            return zf.read(entry)
    raise KeyError(f"No item matching '{path}' in archive")


def _extract_cover_from_epub(epub_path, output_path, target_size=1400):
    """Extract cover image from EPUB and resize to square for iTunes compliance.

    Tries: OPF metadata cover -> common filenames -> first large image.
    Returns output_path on success, None on failure.
    """
    import zipfile
    import io
    import xml.etree.ElementTree as ET

    try:
        from PIL import Image
    except ImportError:
        return None

    def _find_cover_in_opf(zf):
        """Parse OPF to find cover image href."""
        opf_path = None
        try:
            container = ET.fromstring(zf.read("META-INF/container.xml"))
            ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
            rootfile = container.find(".//c:rootfile", ns)
            if rootfile is not None:
                opf_path = rootfile.get("full-path")
        except (KeyError, ET.ParseError):
            pass
        if not opf_path:
            for n in zf.namelist():
                if n.endswith(".opf"):
                    opf_path = n
                    break
        if not opf_path:
            return None

        try:
            opf = ET.fromstring(zf.read(opf_path))
        except (KeyError, ET.ParseError):
            return None

        opf_dir = os.path.dirname(opf_path)

        # Method 1: <meta name="cover" content="item-id"/>
        cover_id = None
        for meta in opf.iter():
            if meta.tag.endswith("}meta") or meta.tag == "meta":
                if meta.get("name") == "cover":
                    cover_id = meta.get("content")
                    break

        # Collect manifest items
        manifest_items = {}
        for item in opf.iter():
            if item.tag.endswith("}item") or item.tag == "item":
                item_id = item.get("id", "")
                href = item.get("href", "")
                props = item.get("properties", "")
                mt = item.get("media-type", "")
                manifest_items[item_id] = (href, mt, props)

        # Check properties="cover-image"
        for item_id, (href, mt, props) in manifest_items.items():
            if "cover-image" in props and mt.startswith("image/"):
                return (opf_dir+'/'+href).replace('\\','/') if opf_dir else href

        # Check by cover_id from meta
        if cover_id and cover_id in manifest_items:
            href, mt, _ = manifest_items[cover_id]
            if mt.startswith("image/"):
                return (opf_dir+'/'+href).replace('\\','/') if opf_dir else href

        return None

    def _find_cover_by_name(zf):
        """Look for common cover filenames."""
        for n in zf.namelist():
            base = os.path.basename(n).lower()
            if base in ("cover.jpg", "cover.jpeg", "cover.png",
                        "cover-image.jpg", "cover-image.png"):
                return n
        return None

    def _find_largest_image(zf):
        """Fallback: pick the largest image file."""
        best, best_size = None, 0
        for n in zf.namelist():
            low = n.lower()
            if any(low.endswith(ext) for ext in (".jpg", ".jpeg", ".png")):
                sz = zf.getinfo(n).file_size
                if sz > best_size:
                    best, best_size = n, sz
        return best if best_size > 5000 else None

    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            img_path = (_find_cover_in_opf(zf)
                        or _find_cover_by_name(zf)
                        or _find_largest_image(zf))
            if not img_path:
                return None
            img_data = _zip_safe_read(zf, img_path)

        img = Image.open(io.BytesIO(img_data))
        img = img.convert("RGB")
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        img = img.resize((target_size, target_size), Image.LANCZOS)
        img.save(output_path, "JPEG", quality=85)
        return output_path
    except Exception:
        return None


def _generate_fallback_cover(output_path, title="", author="", target_size=1400):
    """Generate a simple branded cover when no EPUB cover is available."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    try:
        sz = target_size
        img = Image.new("RGB", (sz, sz), (245, 240, 232))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, sz, int(sz * 0.38)], fill=(194, 154, 108))

        font_title = font_author = font_small = None
        for fpath in ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                      "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
                      "C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/arial.ttf"]:
            if os.path.exists(fpath):
                font_title = ImageFont.truetype(fpath, sz // 14)
                font_author = ImageFont.truetype(fpath, sz // 22)
                font_small = ImageFont.truetype(fpath, sz // 32)
                break
        if not font_title:
            font_title = font_author = font_small = ImageFont.load_default()

        def _wrap(text, font, max_w):
            words, lines, cur = text.split(), [], ""
            for w in words:
                test = f"{cur} {w}".strip()
                if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
                    cur = test
                else:
                    if cur:
                        lines.append(cur)
                    cur = w
            if cur:
                lines.append(cur)
            return lines or [text]

        margin = int(sz * 0.1)
        max_w = sz - margin * 2
        y = int(sz * 0.42)
        for line in _wrap(title or "Audiobook", font_title, max_w):
            bbox = draw.textbbox((0, 0), line, font=font_title)
            draw.text(((sz - bbox[2] + bbox[0]) // 2, y), line,
                      fill=(60, 50, 40), font=font_title)
            y += int((bbox[3] - bbox[1]) * 1.3)

        if author:
            y += int(sz * 0.03)
            for line in _wrap(author, font_author, max_w):
                bbox = draw.textbbox((0, 0), line, font=font_author)
                draw.text(((sz - bbox[2] + bbox[0]) // 2, y), line,
                          fill=(120, 100, 80), font=font_author)
                y += int((bbox[3] - bbox[1]) * 1.3)

        label = "Audiobook Maker"
        bbox = draw.textbbox((0, 0), label, font=font_small)
        draw.text(((sz - bbox[2] + bbox[0]) // 2, sz - int(sz * 0.08)),
                  label, fill=(180, 165, 145), font=font_small)
        img.save(output_path, "JPEG", quality=85)
        return output_path
    except Exception:
        return None


def _extract_cover_for_preview(epub_path, output_dir):
    """Extract cover image from EPUB for UI preview. Works with or without Pillow.

    Returns (output_path, mime_type) on success, (None, None) on failure.
    Unlike _extract_cover_from_epub, this does NOT require Pillow:
    - With Pillow: resizes to 400px thumbnail JPEG
    - Without Pillow: extracts raw image bytes as-is
    """
    import zipfile
    import xml.etree.ElementTree as ET

    def _find_cover_path_in_zip(zf):
        """Find the internal path of the cover image inside the EPUB ZIP."""
        # 1. Try OPF metadata
        opf_path = None
        try:
            container = ET.fromstring(zf.read("META-INF/container.xml"))
            ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
            rootfile = container.find(".//c:rootfile", ns)
            if rootfile is not None:
                opf_path = rootfile.get("full-path")
        except (KeyError, ET.ParseError):
            pass
        if not opf_path:
            for n in zf.namelist():
                if n.endswith(".opf"):
                    opf_path = n
                    break
        if opf_path:
            try:
                opf = ET.fromstring(zf.read(opf_path))
                opf_dir = os.path.dirname(opf_path)
                cover_id = None
                for meta in opf.iter():
                    tag = meta.tag.split("}")[-1] if "}" in meta.tag else meta.tag
                    if tag == "meta" and meta.get("name") == "cover":
                        cover_id = meta.get("content")
                        break
                manifest = {}
                for item in opf.iter():
                    tag = item.tag.split("}")[-1] if "}" in item.tag else item.tag
                    if tag == "item":
                        manifest[item.get("id", "")] = (
                            item.get("href", ""), item.get("media-type", ""),
                            item.get("properties", ""))
                for iid, (href, mt, props) in manifest.items():
                    if "cover-image" in props and mt.startswith("image/"):
                        return (opf_dir+'/'+href).replace('\\','/') if opf_dir else href
                if cover_id and cover_id in manifest:
                    href, mt, _ = manifest[cover_id]
                    if mt.startswith("image/"):
                        return (opf_dir+'/'+href).replace('\\','/') if opf_dir else href
            except (KeyError, ET.ParseError):
                pass

        # 2. Try common filenames
        for n in zf.namelist():
            base = os.path.basename(n).lower()
            if base in ("cover.jpg", "cover.jpeg", "cover.png",
                        "cover-image.jpg", "cover-image.png"):
                return n

        # 3. Largest image file
        best, best_size = None, 0
        for n in zf.namelist():
            low = n.lower()
            if any(low.endswith(ext) for ext in (".jpg", ".jpeg", ".png")):
                sz = zf.getinfo(n).file_size
                if sz > best_size:
                    best, best_size = n, sz
        return best if best_size > 5000 else None

    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            img_zip_path = _find_cover_path_in_zip(zf)
            if not img_zip_path:
                print(f"[cover] No cover image found in {os.path.basename(epub_path)}")
                return None, None
            img_data = _zip_safe_read(zf, img_zip_path)
            print(f"[cover] Found: {img_zip_path} ({len(img_data)} bytes)")
    except Exception as e:
        print(f"[cover] ZIP read error: {e}")
        return None, None

    # Determine format from data header
    is_png = img_data[:8] == b'\x89PNG\r\n\x1a\n'
    mime = "image/png" if is_png else "image/jpeg"
    ext = ".png" if is_png else ".jpg"

    # Try Pillow for a clean resize
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(img_data))
        img = img.convert("RGB")
        # Fit within 400px preserving aspect ratio (no square crop)
        img.thumbnail((400, 600), Image.LANCZOS)
        out_path = os.path.join(output_dir, "cover_thumb.jpg")
        img.save(out_path, "JPEG", quality=85)
        print(f"[cover] Thumbnail saved with Pillow: {os.path.getsize(out_path)} bytes")
        return out_path, "image/jpeg"
    except ImportError:
        print("[cover] Pillow not available, using raw image")
    except Exception as e:
        print(f"[cover] Pillow resize failed: {e}, using raw image")

    # Fallback: write raw image bytes (browser will handle any size)
    out_path = os.path.join(output_dir, "cover_thumb" + ext)
    with open(out_path, "wb") as f:
        f.write(img_data)
    print(f"[cover] Raw image saved: {out_path} ({len(img_data)} bytes)")
    return out_path, mime


def _generate_podcast_rss(info, mp3_files, output_path, base_url="", cover_filename="", rss_filename="podcast.xml"):
    """Generate an RSS 2.0 podcast feed XML file compliant with iTunes specs."""
    from datetime import datetime, timezone, timedelta
    import xml.etree.ElementTree as ET
    import struct

    def _mp3_duration_seconds(path):
        """Estimate MP3 duration in seconds from file size and bitrate header."""
        try:
            import subprocess
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True
            )
            if r.returncode == 0 and r.stdout.strip():
                return int(float(r.stdout.strip()))
        except (FileNotFoundError, OSError, ValueError):
            pass
        # Fallback: assume ~48kbps average for edge-tts output
        try:
            return max(1, os.path.getsize(path) * 8 // 48000)
        except OSError:
            return 0

    def _fmt_duration(secs):
        h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _rfc2822(dt):
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return (f"{days[dt.weekday()]}, {dt.day:02d} {months[dt.month-1]} "
                f"{dt.year} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} +0000")

    # Namespaces (iTunes + Atom + Podcast 2.0 for PSP-1 compliance)
    itunes_ns = "http://www.itunes.com/dtds/podcast-1.0.dtd"
    atom_ns = "http://www.w3.org/2005/Atom"
    podcast_ns = "https://podcastindex.org/namespace/1.0"
    content_ns = "http://purl.org/rss/1.0/modules/content/"
    ET.register_namespace("itunes", itunes_ns)
    ET.register_namespace("atom", atom_ns)
    ET.register_namespace("podcast", podcast_ns)
    ET.register_namespace("content", content_ns)

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    # Channel metadata (RSS 2.0 required)
    ET.SubElement(channel, "title").text = info.title or "Audiobook"
    ET.SubElement(channel, "description").text = (
        f"Audiobook: {info.title}" + (f" — {info.author}" if info.author else "")
    )
    ET.SubElement(channel, "language").text = info.language or "en"
    channel_link = base_url or "https://example.com"
    ET.SubElement(channel, "link").text = channel_link
    ET.SubElement(channel, "generator").text = "Audiobook Maker"
    now = datetime.now(timezone.utc)
    ET.SubElement(channel, "pubDate").text = _rfc2822(now)
    ET.SubElement(channel, "lastBuildDate").text = _rfc2822(now)

    # Atom self-link (required for PSP-1)
    rss_url = (base_url.rstrip("/") + "/" + rss_filename) if base_url else rss_filename
    atom_link = ET.SubElement(channel, f"{{{atom_ns}}}link")
    atom_link.set("href", rss_url)
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    # iTunes channel tags (required for Apple Podcasts / PSP-1)
    author_name = info.author or "Unknown"
    ET.SubElement(channel, f"{{{itunes_ns}}}author").text = author_name
    ET.SubElement(channel, f"{{{itunes_ns}}}summary").text = (
        f"Audiobook: {info.title}" + (f" by {info.author}" if info.author else "")
    )
    cat = ET.SubElement(channel, f"{{{itunes_ns}}}category")
    cat.set("text", "Arts")
    sub = ET.SubElement(cat, f"{{{itunes_ns}}}category")
    sub.set("text", "Books")
    ET.SubElement(channel, f"{{{itunes_ns}}}explicit").text = "false"
    ET.SubElement(channel, f"{{{itunes_ns}}}type").text = "serial"

    # iTunes owner with email (required for PSP-1)
    owner = ET.SubElement(channel, f"{{{itunes_ns}}}owner")
    ET.SubElement(owner, f"{{{itunes_ns}}}name").text = author_name
    ET.SubElement(owner, f"{{{itunes_ns}}}email").text = "podcast@example.com"

    # Cover art (required: 1400-3000px square JPEG)
    cover_url = ""
    if cover_filename:
        cover_url = (base_url.rstrip("/") + "/" + cover_filename) if base_url else cover_filename
        img_el = ET.SubElement(channel, f"{{{itunes_ns}}}image")
        img_el.set("href", cover_url)
        # Podcast 2.0 image as well
        p_img = ET.SubElement(channel, f"{{{podcast_ns}}}image")
        p_img.set("href", cover_url)

    # Podcast 2.0 GUID (unique identifier)
    ET.SubElement(channel, f"{{{podcast_ns}}}guid").text = (
        str(uuid.uuid5(uuid.NAMESPACE_URL, channel_link + "/" + (info.title or "audiobook")))
    )

    # Build chapter-to-file mapping from info.chapters
    chapter_by_idx = {ch.index: ch for ch in info.chapters}

    # Items — one per MP3, in order
    for ep_num, mp3_path in enumerate(mp3_files, 1):
        fname = os.path.basename(mp3_path)
        file_size = os.path.getsize(mp3_path) if os.path.exists(mp3_path) else 0
        duration_secs = _mp3_duration_seconds(mp3_path)

        # Try to match chapter from filename pattern "NNN_title.mp3"
        ch_title = f"Episode {ep_num}"
        ch_desc = ""
        try:
            idx_str = fname.split("_")[0]
            idx = int(idx_str)
            if idx in chapter_by_idx:
                ch_title = chapter_by_idx[idx].title
                ch_desc = f"Chapter {idx}: {ch_title}"
        except (ValueError, IndexError):
            pass

        pub_date = now - timedelta(hours=len(mp3_files) - ep_num)
        file_url = (base_url.rstrip("/") + "/" + fname) if base_url else fname

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = ch_title
        ET.SubElement(item, "description").text = ch_desc or ch_title
        ET.SubElement(item, f"{{{itunes_ns}}}episode").text = str(ep_num)
        ET.SubElement(item, f"{{{itunes_ns}}}episodeType").text = "full"
        ET.SubElement(item, f"{{{itunes_ns}}}duration").text = _fmt_duration(duration_secs)
        ET.SubElement(item, f"{{{itunes_ns}}}author").text = info.author or "Unknown"
        ET.SubElement(item, f"{{{itunes_ns}}}summary").text = ch_desc or ch_title
        ET.SubElement(item, f"{{{itunes_ns}}}explicit").text = "false"
        if cover_url:
            item_img = ET.SubElement(item, f"{{{itunes_ns}}}image")
            item_img.set("href", cover_url)
        ET.SubElement(item, "pubDate").text = _rfc2822(pub_date)
        ET.SubElement(item, "link").text = file_url
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = str(
            uuid.uuid5(uuid.NAMESPACE_URL, channel_link + "/" + fname)
        )
        enc = ET.SubElement(item, "enclosure")
        enc.set("url", file_url)
        enc.set("length", str(file_size))
        enc.set("type", "audio/mpeg")

    # Write with XML declaration
    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)


CHAPTER_SILENCE_SEC = 3  # secondi di silenzio all'inizio di ogni capitolo


def _generate_silence_mp3(output_path, duration_sec=3):
    """Genera un file MP3 di silenzio della durata specificata."""
    try:
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"anullsrc=r=24000:cl=mono",
             "-t", str(duration_sec), "-c:a", "libmp3lame",
             "-b:a", "48k", "-q:a", "9", output_path],
            capture_output=True, text=True
        )
        if result.returncode == 0 and os.path.exists(output_path):
            return True
    except (FileNotFoundError, OSError):
        pass
    # Fallback: silenzio MP3 minimo (~3s, frame MPEG1 Layer3 128kbps mono)
    # Un frame MP3 = 1152 samples @ 24000Hz ≈ 48ms → ~63 frame per 3 secondi
    # Frame header: 0xFFF3 9004 (MPEG1, Layer3, 32kbps, 24000Hz, mono)
    # + 417 bytes di zeri per il corpo del frame
    import struct
    frame_header = b'\xff\xf3\x90\x04'
    frame_body = b'\x00' * 413  # padding per frame da 417 byte totali
    frame = frame_header + frame_body
    n_frames = int(duration_sec * 24000 / 1152) + 1
    with open(output_path, 'wb') as f:
        for _ in range(n_frames):
            f.write(frame)
    return os.path.exists(output_path)


def _concatenate_mp3(parts, output):
    try:
        import subprocess
        list_file = output + ".filelist.txt"
        with open(list_file, "w") as f:
            for p in parts:
                f.write(f"file '{p}'\n")
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", list_file, "-c", "copy", output],
            capture_output=True, text=True
        )
        os.remove(list_file)
        if result.returncode == 0:
            return
    except (FileNotFoundError, OSError):
        pass
    with open(output, "wb") as outf:
        for p in parts:
            with open(p, "rb") as inf:
                outf.write(inf.read())


def _safe_filename(name):
    import re
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    return name[:100]


# ═══════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════

# ─── Rotte per lingua (/it/, /en/, /fr/, /es/, /de/, /zh/) ───────────────────
# Ogni URL ha HTML pre-renderizzato con meta tag, title, hreflang e canonical
# corretti per quella lingua — indicizzabili da Google come pagine distinte.

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


# ─── sitemap.xml ─────────────────────────────────────────────────────────────
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


# ─── robots.txt ──────────────────────────────────────────────────────────────
@app.route("/robots.txt")
def robots():
    sitemap_line = f"Sitemap: {BASE_URL}/sitemap.xml" if BASE_URL else ""
    body = f"""User-agent: *
Allow: /
Disallow: /api/
Disallow: /data/
Disallow: /dl/
Disallow: /logs
{sitemap_line}
""".strip()
    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}



# ─── Admin log viewer (/logs) ────────────────────────────────────────────────
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


@app.route("/logs")
def admin_logs():
    """Admin log viewer: card-based, mobile-friendly, with day grouping and Excel export."""
    from datetime import datetime
    from collections import defaultdict
    import html as html_mod

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
    gen_cancelled = total_sessions - gen_completed
    email_sent = sum(1 for s in sessions.values() if "EMAIL_SENT" in s["events"])
    unique_clients = len(set(s.get("client_id", "") for s in sessions.values() if s.get("client_id")))
    returning_clients = sum(1 for c in client_session_count.values() if c >= 2)

    days = defaultdict(list)
    for sid, s in reversed(list(sessions.items())):
        day_key = s["first_dt"].strftime("%Y-%m-%d")
        days[day_key].append((sid, s))

    event_icons = {
        "ANALYZE": "🔍", "GENERATE": "⚙️", "COMPLETE": "✅",
        "DOWNLOAD": "⬇️", "DOWNLOAD_EMAIL": "📧⬇️",
        "DOWNLOAD_EMAIL_PODCAST": "🎙️⬇️", "DOWNLOAD_PODCAST": "🎙️⬇️",
        "EMAIL_REGISTERED": "📬", "EMAIL_SENT": "📤",
        "EMAIL_FAILED": "❌📧", "CANCEL": "🚫",
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
<span class="day-chevron">▾</span>
</div>
<div class="day-cards">
"""
        for sid, s in day_sessions:
            first = s["first_dt"].strftime("%H:%M")
            last = s["last_dt"].strftime("%H:%M")
            delta = s["last_dt"] - s["first_dt"]
            total_sec = int(delta.total_seconds())
            elapsed = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"

            title = s["filename"]
            for ext in (".epub", ".txt", ".pdf"):
                if title.lower().endswith(ext):
                    title = title[:-len(ext)]
            display_title = html_mod.escape(title[:80] + ("…" if len(title) > 80 else ""))

            op = s["last_op"]
            fg, bg = op_colors.get(op, ("#6b7280", "#f3f4f6"))
            timeline = " → ".join(event_icons.get(e, e) for e in s["events"])

            cid = s.get("client_id", "")
            cip = s.get("client_ip", "")
            cid_short = cid[:8] if cid else "—"
            cid_count = client_session_count.get(cid, 0) if cid else 0
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
            blang_display = f'<span class="card-blang">{blang}</span>' if blang else "—"

            cards_html += f"""<div class="card">
<div class="card-top">
<span class="card-title" title="{html_mod.escape(s['filename'])}">{display_title}</span>
<span class="badge" style="color:{fg};background:{bg}">{op}</span>
</div>
<div class="card-timeline">{timeline}</div>
<div class="card-meta">
<div class="meta-row"><span class="meta-label">⏱</span><span>{first} → {last} ({elapsed})</span></div>
<div class="meta-row"><span class="meta-label">🆔</span><code class="sid">{sid}</code></div>
<div class="meta-row"><span class="meta-label">👤</span><code style="{cid_style}">{cid_short}</code>{cid_badge}<span class="card-ip">{cip or ""}</span></div>
<div class="meta-row"><span class="meta-label">🎤</span><span class="card-voice" title="{html_mod.escape(voice_raw)}">{voice_short or "—"}</span></div>
<div class="meta-row"><span class="meta-label">🌐</span>{blang_display}</div>
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
<title>Audiobook Maker — Activity Log ({ym})</title>
<style>
:root {{ --bg:#0f172a;--surface:#1e293b;--surface2:#334155;--border:#475569;--text:#e2e8f0;--text-dim:#94a3b8;--accent:#38bdf8;--accent2:#a78bfa;--green:#22c55e;--red:#ef4444; }}
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
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;padding:14px 20px}}
.stat{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 14px;text-align:center}}
.stat .num{{font-size:1.5rem;font-weight:700;color:var(--accent);font-variant-numeric:tabular-nums}}
.stat.stat-green .num{{color:var(--green)}} .stat.stat-red .num{{color:var(--red)}}
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
.stats{{grid-template-columns:repeat(3,1fr);gap:6px;padding:10px 12px}} .stat{{padding:8px 6px}} .stat .num{{font-size:1.2rem}} .stat .lbl{{font-size:.58rem}}
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
        <a class="btn btn-accent" href="/logs/export?{ym}" title="Export Excel">📊 Excel</a>
    </div>
</div>

<div class='months-nav'>{"<span class='label'>Mesi:</span>" + months_nav if months_nav else ""}<button class="btn btn-toggle" id="btnToggleDays" onclick="toggleAllDays()">Aggrega</button></div>

<div class="stats">
    <div class="stat"><div class="num">{total_sessions}</div><div class="lbl">Sessioni</div></div>
    <div class="stat stat-green"><div class="num">{gen_completed}</div><div class="lbl">Gen. completata</div></div>
    <div class="stat stat-red"><div class="num">{gen_cancelled}</div><div class="lbl">Cancellati</div></div>
    <div class="stat"><div class="num">{email_sent}</div><div class="lbl">Email inviate</div></div>
    <div class="stat"><div class="num">{unique_clients}</div><div class="lbl">Client unici</div></div>
    <div class="stat"><div class="num">{returning_clients}</div><div class="lbl">Ricorrenti</div></div>
</div>

<div class="cards-container">
{cards_html if cards_html else "<div class='empty'><div class='icon'>📭</div><p>Nessuna attività registrata per <strong>" + ym + "</strong></p></div>"}
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
    btn.textContent = allCollapsed ? 'Aggrega' : 'Mostra tutti';
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
        "Voice", "Browser Lang", "Completed", "Recurring Client"
    ])
    for sid, s in sessions.items():
        delta = s["last_dt"] - s["first_dt"]
        duration_min = round(delta.total_seconds() / 60, 1)
        completed = "Yes" if _session_completed(s) else "No"
        cid = s.get("client_id", "")
        recurring = "Yes" if client_session_count.get(cid, 0) >= 2 else "No"
        writer.writerow([
            sid, s["first_dt"].strftime("%Y-%m-%d %H:%M:%S"),
            s["last_dt"].strftime("%Y-%m-%d %H:%M:%S"), duration_min,
            s["filename"], s["last_op"], " → ".join(s["events"]),
            cid, s.get("client_ip", ""), s.get("voice", ""),
            s.get("browser_lang", ""), completed, recurring,
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
        gen_x = total_s - gen_c
        em_s = sum(1 for s_ in sessions.values() if "EMAIL_SENT" in s_["events"])
        uniq = len(set(s_.get("client_id", "") for s_ in sessions.values() if s_.get("client_id")))
        ret = sum(1 for c in client_session_count.values() if c >= 2)

        ws.merge_cells("A1:B1")
        ws["A1"] = f"Audiobook Maker — Activity Log {ym}"
        ws["A1"].font = Font(name="Arial", bold=True, color="38bdf8", size=14)
        summary = [("Sessioni", total_s), ("Gen. completata", gen_c), ("Cancellati", gen_x),
                   ("Email inviate", em_s), ("Client unici", uniq), ("Ricorrenti", ret)]
        for i, (lbl, val) in enumerate(summary):
            ws.cell(row=2, column=1 + i * 2, value=lbl).font = Font(name="Arial", color="94a3b8", size=10)
            ws.cell(row=2, column=2 + i * 2, value=val).font = Font(name="Arial", bold=True, color="e2e8f0", size=12)

        headers = ["Session ID", "Data inizio", "Data fine", "Durata (min)", "Contenuto",
                   "Ultimo stato", "Timeline eventi", "Client ID", "IP", "Voce",
                   "Lingua browser", "Completato", "Client ricorrente"]
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
                        " → ".join(s["events"]), s.get("client_id", ""), s.get("client_ip", ""),
                        s.get("voice", ""), s.get("browser_lang", ""),
                        "✓" if _session_completed(s) else "✗",
                        "✓" if client_session_count.get(s.get("client_id", ""), 0) >= 2 else ""]
            for col_idx, val in enumerate(row_data, 1):
                c = ws.cell(row=row_idx, column=col_idx, value=val)
                c.font = data_font
                if row_idx % 2 == 0:
                    c.fill = PatternFill("solid", fgColor="1e293b")

        col_widths = [12, 20, 20, 12, 45, 18, 50, 14, 16, 25, 10, 12, 14]
        for i, w in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.auto_filter.ref = f"A4:M{4 + len(sessions)}"

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


@app.route("/api/voices")
def api_voices():
    try:
        voices = get_voices()
        return jsonify(voices)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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

    job_id = str(uuid.uuid4())[:8]
    work_dir = UPLOAD_DIR / job_id
    work_dir.mkdir(exist_ok=True)
    file_path = work_dir / file.filename
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

    # ── Preview text ──────────────────────────────────────────────────────────
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

    def _trim_preview(text, min_chars=200, max_chars=300):
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
    # ──────────────────────────────────────────────────────────────────────────

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
    })


@app.route("/api/preview_audio/<job_id>")
def api_preview_audio(job_id):
    """Serve l'MP3 di anteprima come endpoint GET.
    Il browser può usare l'URL direttamente come audio.src — nessun problema di autoplay policy.
    Il timeout è gestito da concurrent.futures (funziona sempre, a differenza di asyncio.wait_for).
    """
    if not job_id or job_id not in jobs:
        return jsonify({"error": "Job non trovato"}), 404

    preview_text = jobs[job_id].get("preview_text", "")
    if not preview_text:
        return jsonify({"error": "Nessun testo di anteprima disponibile"}), 400

    voice = request.args.get("voice", "it-IT-GiuseppeNeural")
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
    # da asyncio — risolve il caso in cui edge-tts si blocca sulla connessione TCP.
    def _generate():
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
            "chapters": chapters_manifest,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    buf.seek(0)
    download_name = f"{safe_title}.abm"

    _log_activity(job_id, job.get("original_filename", ""), "EXPORT_ABM",
                  job.get("client_id", ""), job.get("client_ip", ""),
                  browser_lang=job.get("browser_lang", ""))

    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=download_name)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.json
    job_id = data.get("job_id")
    voice = data.get("voice", "it-IT-GiuseppeNeural")
    rate = data.get("rate", "+0%")
    single_file = data.get("single_file", True)
    selected_chapters = data.get("selected_chapters")  # list of chapter indices, or None

    if job_id not in jobs:
        return jsonify({"error": "Session expired. Re-upload file."}), 400
    job = jobs[job_id]
    if job["status"] not in ("analyzed",):
        return jsonify({"error": "Generation already running or completed."}), 400

    # ── Concurrent generation limit per client ──
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

    # Filter chapters if a subset was selected (only in chapter mode)
    if selected_chapters and not single_file:
        selected_set = set(selected_chapters)
        filtered = [ch for ch in info.chapters if ch.index in selected_set]
        if not filtered:
            return jsonify({"error": "No chapters selected."}), 400
        # Create a lightweight copy of info with filtered chapters
        info = copy(info)
        info.chapters = filtered
        info.total_words = sum(ch.word_count for ch in filtered)
        info.estimated_duration_minutes = info.total_words / 150

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
            print(f"[{job_id}] Cancel ignored — email registered for background processing")
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
    # Clear output-related keys
    for key in ("output_files", "output_name", "output_zip", "output_file",
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


@app.route("/api/active_jobs")
def api_active_jobs():
    """Return list of currently generating jobs (for admin monitor)."""
    from datetime import datetime
    active = []
    for jid, job in list(jobs.items()):
        if job.get("status") in ("generating", "analyzed"):
            info = job.get("info")
            title = ""
            if info:
                title = getattr(info, "title", "") or ""
            if not title:
                title = job.get("original_filename", jid)
            start_ts = job.get("start_time", 0)
            active.append({
                "title": title,
                "started": datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d %H:%M:%S") if start_ts else "—",
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
    job_in_memory = job_id in jobs and jobs[job_id].get("status") == "done"
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

    return _render_dl_page(token, book_title, remaining_str,
                           token_info["download_type"], lang)


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
        return "Link scaduto — i file sono stati cancellati dopo 24 ore", 410

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
        # ── PODCAST download ──
        is_podcast = dl_type == "podcast" and (
            (job and job.get("podcast_ready")) or token_info.get("podcast_ready"))

        if is_podcast:
            return _serve_podcast_download(token_info, job, job_id)

        # ── AUDIO download ──
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
               "copy": "复制订阅源URL", "copied": "已复制！",
               "episodes": "剧集", "listen": "收听",
               "instructions": "复制RSS订阅源URL并粘贴到您喜爱的播客应用中（Pocket Casts、Apple Podcasts、AntennaPod、Overcast...）。",
               "footer": "由Audiobook Maker生成"},
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
    _t = {
        "it": {"title": "Link scaduto", "h2": "Link scaduto",
               "p1": "Sono trascorse pi&ugrave; di 24 ore dall'invio dell'email. I file generati sono stati cancellati automaticamente per liberare spazio sul server.",
               "p2": "Per generare nuovamente l'audiolibro, visita:"},
        "en": {"title": "Link expired", "h2": "Link expired",
               "p1": "More than 24 hours have passed since the email was sent. The generated files have been automatically deleted to free up server space.",
               "p2": "To generate the audiobook again, visit:"},
        "fr": {"title": "Lien expir&eacute;", "h2": "Lien expir&eacute;",
               "p1": "Plus de 24 heures se sont &eacute;coul&eacute;es depuis l'envoi de l'email. Les fichiers g&eacute;n&eacute;r&eacute;s ont &eacute;t&eacute; automatiquement supprim&eacute;s pour lib&eacute;rer de l'espace sur le serveur.",
               "p2": "Pour g&eacute;n&eacute;rer &agrave; nouveau le livre audio, visitez :"},
        "es": {"title": "Enlace caducado", "h2": "Enlace caducado",
               "p1": "Han pasado m&aacute;s de 24 horas desde el env&iacute;o del email. Los archivos generados se han eliminado autom&aacute;ticamente para liberar espacio en el servidor.",
               "p2": "Para generar nuevamente el audiolibro, visita:"},
        "de": {"title": "Link abgelaufen", "h2": "Link abgelaufen",
               "p1": "Es sind mehr als 24 Stunden seit dem Versand der E-Mail vergangen. Die erzeugten Dateien wurden automatisch gel&ouml;scht, um Speicherplatz auf dem Server freizugeben.",
               "p2": "Um das H&ouml;rbuch erneut zu erstellen, besuche:"},
        "zh": {"title": "\u94fe\u63a5\u5df2\u8fc7\u671f", "h2": "\u94fe\u63a5\u5df2\u8fc7\u671f",
               "p1": "\u90ae\u4ef6\u53d1\u9001\u5df2\u8d85\u8fc724\u5c0f\u65f6\u3002\u751f\u6210\u7684\u6587\u4ef6\u5df2\u81ea\u52a8\u5220\u9664\u4ee5\u91ca\u653e\u670d\u52a1\u5668\u7a7a\u95f4\u3002",
               "p2": "\u8981\u91cd\u65b0\u751f\u6210\u6709\u58f0\u8bfb\u7269\uff0c\u8bf7\u8bbf\u95ee\uff1a"},
    }
    t = _t.get(lang, _t["en"])
    return f"""<!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/svg+xml" href="{FAVICON_B64}">
<title>Audiobook Maker — {t['title']}</title>
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


def _render_dl_page(token, book_title, remaining_str, dl_type, lang="en"):
    _t = {
        "it": {"title": "Download", "h2": "Il tuo audiolibro &egrave; pronto!",
               "btn": "&#x2B07;&#xFE0F; Scarica",
               "warn": "&#x23F0; Hai ancora {r} per scaricare i file.<br>Dopo 24 ore dall'invio dell'email verranno cancellati.",
               "share": "Ti &egrave; piaciuto? Condividi con i tuoi amici!",
               "share_text": "Ho appena trasformato un ebook in audiolibro con Audiobook Maker — gratis e direttamente dal browser!",
               "copied": "Copiato!"},
        "en": {"title": "Download", "h2": "Your audiobook is ready!",
               "btn": "&#x2B07;&#xFE0F; Download",
               "warn": "&#x23F0; You have {r} left to download the files.<br>They will be deleted 24 hours after the email was sent.",
               "share": "Like it? Share with your friends!",
               "share_text": "I just turned an ebook into an audiobook with Audiobook Maker — free and right in the browser!",
               "copied": "Copied!"},
        "fr": {"title": "T&eacute;l&eacute;chargement", "h2": "Votre livre audio est pr&ecirc;t !",
               "btn": "&#x2B07;&#xFE0F; T&eacute;l&eacute;charger",
               "warn": "&#x23F0; Il vous reste {r} pour t&eacute;l&eacute;charger les fichiers.<br>Ils seront supprim&eacute;s 24 heures apr&egrave;s l'envoi de l'email.",
               "share": "Vous avez aim&eacute; ? Partagez avec vos amis !",
               "share_text": "Je viens de transformer un ebook en livre audio avec Audiobook Maker — gratuit et directement depuis le navigateur !",
               "copied": "Copi&eacute; !"},
        "es": {"title": "Descarga", "h2": "&iexcl;Tu audiolibro est&aacute; listo!",
               "btn": "&#x2B07;&#xFE0F; Descargar",
               "warn": "&#x23F0; Te quedan {r} para descargar los archivos.<br>Se eliminar&aacute;n 24 horas despu&eacute;s del env&iacute;o del email.",
               "share": "&iexcl;Te ha gustado? &iexcl;Comp&aacute;rtelo con tus amigos!",
               "share_text": "Acabo de convertir un ebook en audiolibro con Audiobook Maker — ¡gratis y desde el navegador!",
               "copied": "&iexcl;Copiado!"},
        "de": {"title": "Download", "h2": "Dein H&ouml;rbuch ist fertig!",
               "btn": "&#x2B07;&#xFE0F; Herunterladen",
               "warn": "&#x23F0; Du hast noch {r} zum Herunterladen.<br>Die Dateien werden 24 Stunden nach dem E-Mail-Versand gel&ouml;scht.",
               "share": "Hat es dir gefallen? Teile es mit deinen Freunden!",
               "share_text": "Ich habe gerade ein E-Book in ein Hörbuch verwandelt mit Audiobook Maker — kostenlos und direkt im Browser!",
               "copied": "Kopiert!"},
        "zh": {"title": "\u4e0b\u8f7d", "h2": "\u60a8\u7684\u6709\u58f0\u8bfb\u7269\u5df2\u51c6\u5907\u597d\uff01",
               "btn": "&#x2B07;&#xFE0F; \u4e0b\u8f7d",
               "warn": "&#x23F0; \u60a8\u8fd8\u6709 {r} \u7684\u65f6\u95f4\u4e0b\u8f7d\u6587\u4ef6\u3002<br>\u6587\u4ef6\u5c06\u5728\u90ae\u4ef6\u53d1\u9001\u540e24\u5c0f\u65f6\u5220\u9664\u3002",
               "share": "\u89c9\u5f97\u4e0d\u9519\uff1f\u5206\u4eab\u7ed9\u4f60\u7684\u670b\u53cb\uff01",
               "share_text": "\u6211\u521a\u7528 Audiobook Maker \u628a\u4e00\u672c\u7535\u5b50\u4e66\u8f6c\u6210\u4e86\u6709\u58f0\u4e66\u2014\u2014\u514d\u8d39\u4e14\u5728\u6d4f\u89c8\u5668\u4e2d\u5373\u53ef\u5b8c\u6210\uff01",
               "copied": "\u5df2\u590d\u5236\uff01"},
    }
    t = _t.get(lang, _t["en"])
    type_label = "Podcast ZIP" if dl_type == "podcast" else "Audio ZIP"
    warn_text = t["warn"].replace("{r}", remaining_str)

    share_url = BASE_URL or "https://audiobook-maker.com"
    # JS-safe share text (escape quotes for JS string)
    share_text_js = t.get("share_text", "").replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    copied_text_js = t.get("copied", "Copied!").replace("'", "\\'")

    return f"""<!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/svg+xml" href="{FAVICON_B64}">
<title>Audiobook Maker — {t['title']}</title>
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
transition:background .2s}}
.btn:hover{{background:#2563eb}}
.warn{{color:#e74c3c;font-weight:600;margin-top:24px;font-size:.9rem}}
.type{{display:inline-block;padding:4px 12px;background:#e8f4f8;border-radius:12px;
font-size:.85rem;color:#2980b9;margin-bottom:16px}}
.share-row{{margin-top:28px;padding-top:20px;border-top:1px solid #eee;text-align:center}}
.share-label{{font-size:.85rem;color:#999;margin-bottom:12px}}
.share-icons{{display:flex;justify-content:center;gap:8px;flex-wrap:wrap}}
.share-icons a,.share-icons button{{width:40px;height:40px;border-radius:50%;display:inline-flex;
align-items:center;justify-content:center;border:1px solid #ddd;background:#f8f9fa;color:#666;
cursor:pointer;transition:all .2s;text-decoration:none;font-size:0;padding:0}}
.share-icons a:hover,.share-icons button:hover{{border-color:#c47a2a;color:#c47a2a;
transform:translateY(-2px);box-shadow:0 3px 10px rgba(0,0,0,.08)}}
.share-icons svg{{width:18px;height:18px;fill:currentColor;flex-shrink:0}}
.copy-wrap{{position:relative;display:inline-flex}}
.copy-tip{{position:absolute;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%);
background:#333;color:#fff;font-size:.72rem;padding:3px 8px;border-radius:4px;
white-space:nowrap;pointer-events:none;opacity:0;transition:opacity .2s}}
.copy-tip.show{{opacity:1}}
.donate-panel{{margin-top:20px;padding:18px 20px;background:linear-gradient(135deg,#fffaf4,#fff3e0);
border:1px solid #e8c99a;border-radius:12px;text-align:center}}
.donate-title{{font-size:.97rem;font-weight:700;color:#2c2a26;margin-bottom:6px}}
.donate-body{{font-size:.82rem;color:#6b6760;line-height:1.5;margin-bottom:14px}}
.donate-btns{{display:flex;justify-content:center;gap:10px;flex-wrap:wrap}}
.donate-btn{{display:inline-flex;align-items:center;gap:6px;padding:9px 18px;border-radius:8px;
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
<p><a href="/dl/{token}/download" class="btn">{t['btn']}</a></p>
<p class="warn">{warn_text}</p>
<!-- Donate panel — text filled by JS based on browser language -->
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
    <a id="shX" target="_blank" rel="noopener" title="X / Twitter"><svg viewBox="0 0 24 24"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg></a>
    <a id="shFb" target="_blank" rel="noopener" title="Facebook"><svg viewBox="0 0 24 24"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg></a>
    <a id="shWa" target="_blank" rel="noopener" title="WhatsApp"><svg viewBox="0 0 24 24"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg></a>
    <a id="shTg" target="_blank" rel="noopener" title="Telegram"><svg viewBox="0 0 24 24"><path d="M11.944 0A12 12 0 000 12a12 12 0 0012 12 12 12 0 0012-12A12 12 0 0012 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 01.171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.479.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg></a>
    <a id="shLi" target="_blank" rel="noopener" title="LinkedIn"><svg viewBox="0 0 24 24"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg></a>
    <a id="shRd" target="_blank" rel="noopener" title="Reddit"><svg viewBox="0 0 24 24"><path d="M12 0C5.373 0 0 5.373 0 12c0 5.084 3.163 9.426 7.627 11.174-.105-.949-.2-2.405.042-3.441.218-.937 1.407-5.965 1.407-5.965s-.359-.719-.359-1.782c0-1.668.967-2.914 2.171-2.914 1.023 0 1.518.769 1.518 1.69 0 1.029-.655 2.568-.994 3.995-.283 1.194.599 2.169 1.777 2.169 2.133 0 3.772-2.249 3.772-5.495 0-2.873-2.064-4.882-5.012-4.882-3.414 0-5.418 2.561-5.418 5.207 0 1.031.397 2.138.893 2.738a.36.36 0 01.083.345l-.333 1.36c-.053.22-.174.267-.402.161-1.499-.698-2.436-2.889-2.436-4.649 0-3.785 2.75-7.262 7.929-7.262 4.163 0 7.398 2.967 7.398 6.931 0 4.136-2.607 7.464-6.227 7.464-1.216 0-2.359-.631-2.75-1.378l-.748 2.853c-.271 1.043-1.002 2.35-1.492 3.146C9.57 23.812 10.763 24 12 24c6.627 0 12-5.373 12-12 0-6.628-5.373-12-12-12z"/></svg></a>
    <div class="copy-wrap">
      <button id="shCopy" title="Copy link"><svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg></button>
      <span class="copy-tip" id="copyTip">{t['copied']}</span>
    </div>
  </div>
</div>
</div>
<script>
(function(){{
  /* ── Donate i18n (browser language) ── */
  var DL={{
    it:{{title:'\u2764\ufe0f Ti \u00e8 stato utile questo strumento?',body:'AudiobookMaker \u00e8 gratuito, senza pubblicit\u00e0 e rimarr\u00e0 gratuito! Aiutami a coprire i costi del server e della manutenzione. Anche una piccola donazione di \u20ac1 o \u20ac2 \u00e8 gi\u00e0 un grande contributo:',coffee:'Offrimi un caff\u00e8',paypal:'Donazione PayPal'}},
    fr:{{title:'\u2764\ufe0f Cet outil vous a \u00e9t\u00e9 utile\u00a0?',body:'AudiobookMaker est gratuit, sans publicit\u00e9 et le restera\u00a0! Aidez-moi \u00e0 couvrir les co\u00fbts du serveur et de la maintenance. Un petit don de 1 ou 2\u00a0\u20ac est d\u00e9j\u00e0 une grande contribution\u00a0:',coffee:'Offrez-moi un caf\u00e9',paypal:'Don PayPal'}},
    es:{{title:'\u2764\ufe0f \u00bfTe ha resultado \u00fatil esta herramienta?',body:'AudiobookMaker es gratuito, sin publicidad y seguir\u00e1 si\u00e9ndolo. Ay\u00fadame a cubrir los costes del servidor y mantenimiento. \u00a1Una peque\u00f1a donaci\u00f3n de 1 o 2\u00a0\u20ac ya es una gran contribuci\u00f3n!:',coffee:'Inv\u00edtame a un caf\u00e9',paypal:'Donaci\u00f3n PayPal'}},
    de:{{title:'\u2764\ufe0f War dieses Tool n\u00fctzlich f\u00fcr dich?',body:'AudiobookMaker ist kostenlos, werbefrei \u2013 und bleibt es auch! Hilf mir, die Server- und Wartungskosten zu decken. Eine kleine Spende von 1 oder 2\u00a0\u20ac ist schon ein gro\u00dfer Beitrag:',coffee:'Kauf mir einen Kaffee',paypal:'PayPal-Spende'}},
    zh:{{title:'\u2764\ufe0f \u8fd9\u4e2a\u5de5\u5177\u5bf9\u60a8\u6709\u5e2e\u52a9\u5417\uff1f',body:'AudiobookMaker \u514d\u8d39\u3001\u65e0\u5e7f\u544a\uff0c\u5c06\u6c38\u8fdc\u4fdd\u6301\u514d\u8d39\uff01\u8bf7\u5e2e\u52a9\u6211\u627f\u62c5\u670d\u52a1\u5668\u548c\u7ef4\u62a4\u8d39\u7528\u3002\u54ea\u6015\u6350\u8d60 1 \u6216 2 \u6b27\u5143\uff0c\u4e5f\u662f\u83ab\u5927\u7684\u652f\u6301\uff1a',coffee:'\u8bf7\u6211\u559d\u676f\u548f\u5561',paypal:'PayPal \u6350\u6b3e'}},
    en:{{title:'\u2764\ufe0f Did you find this tool useful?',body:'AudiobookMaker is free, ad-free, and will remain free! Help me cover server and maintenance costs. A small donation of \u20ac1 or \u20ac2 is already a great contribution:',coffee:'Buy me a coffee',paypal:'PayPal donation'}}
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
  document.getElementById('shX').href='https://x.com/intent/tweet?text='+tx+'&url='+u;
  document.getElementById('shFb').href='https://www.facebook.com/sharer/sharer.php?u='+u;
  document.getElementById('shWa').href='https://wa.me/?text='+f;
  document.getElementById('shTg').href='https://t.me/share/url?url='+u+'&text='+tx;
  document.getElementById('shLi').href='https://www.linkedin.com/sharing/share-offsite/?url='+u;
  document.getElementById('shRd').href='https://www.reddit.com/submit?url='+u+'&title='+tx;
  document.getElementById('shCopy').onclick=function(){{
    navigator.clipboard.writeText(S).then(function(){{
      var tip=document.getElementById('copyTip');
      tip.classList.add('show');
      setTimeout(function(){{tip.classList.remove('show')}},2000);
    }});
  }};
}})();
</script>
</body></html>"""


@app.route("/api/download/<job_id>")
def api_download(job_id):
    if job_id not in jobs:
        return "Job not found", 404
    job = jobs[job_id]
    if job.get("status") != "done":
        return "Not ready", 400
    # Refresh heartbeat — evita che il cleanup rimuova il job durante il download
    job["last_poll"] = time.time()
    job["downloaded_at"] = time.time()
    _log_activity(job_id, job.get("original_filename", ""), "DOWNLOAD",
                  job.get("client_id", ""), job.get("client_ip", ""),
                  job.get("voice", ""), job.get("browser_lang", ""))
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


# ═══════════════════════════════════════════════════════════════════
# HTML TEMPLATE (i18n, upload lock, ETA)
# ═══════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════
# HTML TEMPLATE (assembled from modular components)
# ═══════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════
# SEO DATA — usato sia per il pre-rendering server-side che per sitemap.xml
# Mantienilo allineato con seo_data.js (che gestisce il cambio lingua client-side)
# ═══════════════════════════════════════════════════════════════════
_SEO_DATA = {
    "it": {
        "title":   "Audiobook Maker — Convertitore Gratuito da EPUB/PDF ad Audiolibro Online | Text-to-Speech AI",
        "desc":    "Converti i tuoi ebook EPUB e PDF in audiolibri MP3 gratis con voci AI naturali. Convertitore online gratuito text-to-speech: carica il tuo libro, scegli la voce e scarica l'audiolibro. Nessuna installazione, funziona dal browser. Supporta italiano, inglese, francese, spagnolo, tedesco e cinese.",
        "kw":      "convertitore epub audiolibro, epub in audiolibro gratis, pdf in audiolibro, convertire pdf in audiolibro online, convertire ebook in audiolibro online, creare audiolibro da epub, creare audiolibro da pdf, text to speech italiano, da libro a audiolibro gratis, convertitore audiolibro online gratuito, epub to mp3, pdf to mp3, trasformare ebook in audio, sintesi vocale libro, audiolibro maker, convertire libro in audio gratis, ebook to audiobook italiano, tts italiano gratis, creare audiolibro gratis online, convertitore testo in voce, epub reader audio, da testo ad audiolibro, ascoltare ebook, libro parlato gratis",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Convertitore online gratuito per trasformare ebook EPUB e PDF in audiolibri MP3 con voci neurali TTS AI. Supporta 6 lingue, selezione capitoli e generazione feed podcast RSS.",
    },
    "en": {
        "title":   "Audiobook Maker — Free Online EPUB/PDF to Audiobook Converter | AI Text-to-Speech",
        "desc":    "Convert your EPUB and PDF ebooks to MP3 audiobooks for free with natural AI voices. Free online text-to-speech converter: upload your book, choose a voice, and download your audiobook. No installation needed, works in your browser. Supports English, Italian, French, Spanish, German and Chinese.",
        "kw":      "epub to audiobook converter, pdf to audiobook converter, free epub to audiobook, free pdf to audiobook, convert ebook to audiobook online free, epub to mp3 converter, pdf to mp3 converter, text to speech audiobook, free audiobook maker online, ebook to audiobook converter, epub to audio, pdf to audio, online audiobook creator free, turn ebook into audiobook, tts audiobook generator, convert epub to mp3 free, convert pdf to mp3 free, free text to speech book reader, ai audiobook maker, epub audiobook converter online, ebook to mp3, listen to epub, epub reader with audio, book to audiobook converter free, create audiobook from epub, create audiobook from pdf",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Free online tool to convert EPUB and PDF ebooks into MP3 audiobooks using neural AI TTS voices. Supports 6 languages, chapter selection, and podcast RSS feed generation.",
    },
    "fr": {
        "title":   "Audiobook Maker — Convertisseur Gratuit EPUB/PDF en Livre Audio en Ligne | Text-to-Speech IA",
        "desc":    "Convertissez vos ebooks EPUB et PDF en livres audio MP3 gratuitement avec des voix IA naturelles. Convertisseur en ligne gratuit text-to-speech : téléchargez votre livre, choisissez une voix et téléchargez votre livre audio. Aucune installation, fonctionne dans le navigateur.",
        "kw":      "convertisseur epub livre audio, convertisseur pdf livre audio, epub en livre audio gratuit, pdf en livre audio gratuit, convertir ebook en livre audio en ligne, créer livre audio gratuit, text to speech français, convertisseur livre audio en ligne gratuit, epub vers mp3, pdf vers mp3, transformer ebook en audio, synthèse vocale livre, audiobook maker, convertir livre en audio gratuit, ebook to audiobook français, tts français gratuit, créer livre audio en ligne, convertisseur texte en voix, epub lecteur audio, de texte à livre audio, écouter ebook, livre parlé gratuit, epub en audio gratuit, pdf en audio gratuit",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Outil en ligne gratuit pour convertir des ebooks EPUB et PDF en livres audio MP3 avec des voix neuronales TTS IA. Prend en charge 6 langues et la génération de flux RSS podcast.",
    },
    "es": {
        "title":   "Audiobook Maker — Convertidor Gratuito de EPUB/PDF a Audiolibro Online | Text-to-Speech IA",
        "desc":    "Convierte tus ebooks EPUB y PDF en audiolibros MP3 gratis con voces IA naturales. Convertidor online gratuito text-to-speech: sube tu libro, elige una voz y descarga tu audiolibro. Sin instalación, funciona desde el navegador.",
        "kw":      "convertidor epub audiolibro, convertidor pdf audiolibro, epub a audiolibro gratis, pdf a audiolibro gratis, convertir ebook a audiolibro online, crear audiolibro gratis, text to speech español, convertidor audiolibro online gratuito, epub a mp3, pdf a mp3, transformar ebook en audio, síntesis de voz libro, audiobook maker, convertir libro a audio gratis, ebook to audiobook español, tts español gratis, crear audiolibro en línea gratis, convertidor texto a voz, lector epub con audio, de texto a audiolibro, escuchar ebook, libro hablado gratis, epub a audio gratis, pdf a audio gratis",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Herramienta online gratuita para convertir ebooks EPUB y PDF en audiolibros MP3 con voces neuronales TTS IA. Soporta 6 idiomas y generación de feed podcast RSS.",
    },
    "de": {
        "title":   "Audiobook Maker — Kostenloser Online EPUB/PDF zu Hörbuch Konverter | KI Text-to-Speech",
        "desc":    "Konvertieren Sie Ihre EPUB- und PDF-E-Books kostenlos in MP3-Hörbücher mit natürlichen KI-Stimmen. Kostenloser Online Text-to-Speech Konverter: Laden Sie Ihr Buch hoch, wählen Sie eine Stimme und laden Sie Ihr Hörbuch herunter. Keine Installation nötig, funktioniert im Browser.",
        "kw":      "epub zu hörbuch konverter, pdf zu hörbuch konverter, epub in hörbuch umwandeln kostenlos, pdf in hörbuch umwandeln kostenlos, ebook in hörbuch umwandeln online, hörbuch erstellen kostenlos, text to speech deutsch, hörbuch konverter online kostenlos, epub zu mp3, pdf zu mp3, ebook in audio umwandeln, sprachsynthese buch, audiobook maker, buch in hörbuch umwandeln kostenlos, ebook to audiobook deutsch, tts deutsch kostenlos, hörbuch erstellen online gratis, text in sprache konverter, epub vorlesen lassen, text zu hörbuch, ebook anhören, hörbuch maker kostenlos, epub zu audio kostenlos, pdf zu audio kostenlos",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Kostenloses Online-Tool zum Konvertieren von EPUB- und PDF-E-Books in MP3-Hörbücher mit neuronalen KI-TTS-Stimmen. Unterstützt 6 Sprachen und Podcast-RSS-Feed-Generierung.",
    },
    "zh": {
        "title":   "Audiobook Maker — 免费在线EPUB/PDF转有声书转换器 | AI文字转语音",
        "desc":    "使用自然AI语音将EPUB和PDF电子书免费转换为MP3有声书。免费在线文字转语音转换器：上传书籍，选择语音，下载有声书。无需安装，浏览器即可使用。支持中文、英语、意大利语、法语、西班牙语和德语。",
        "kw":      "epub转有声书, pdf转有声书, 免费epub转有声书, 免费pdf转有声书, 在线电子书转有声书, 免费创建有声书, 文字转语音中文, 免费在线有声书转换器, epub转mp3, pdf转mp3, 电子书转音频, 语音合成, 有声书制作, 免费电子书转音频, ebook to audiobook中文, tts中文免费, 在线制作有声书, 文本转语音, epub阅读器语音, 文字转有声书, 听电子书, 免费有声书制作器, epub转音频免费, pdf转音频免费",
        "ld_name": "Audiobook Maker",
        "ld_desc": "免费在线工具，使用神经网络AI TTS语音将EPUB和PDF电子书转换为MP3有声书。支持6种语言和播客RSS订阅源生成。",
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




# ═══════════════════════════════════════════════════════════════════
# AUTO-CLEANUP (deletes EPUB/PDF/TXT + MP3 files)
# ═══════════════════════════════════════════════════════════════════

# Regole di cancellazione:
# 1. Browser chiuso senza email registrata → cancella (heartbeat perso per 60s)
# 2. Utente scarica direttamente dall'UI web → cancella subito dopo download
# 3. Email di notifica inviata → mantieni 24h dall'invio, poi cancella
# 4. Job in errore o cancellato → cancella subito
# 5. Cartelle orfane su disco (non in jobs né in tokens) → cancella

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

            # ── Cancelled jobs: immediate cleanup ──
            if status == "cancelled":
                to_remove.append((jid, "cancelled"))
                continue

            # ── Error jobs: immediate cleanup ──
            if status == "error":
                start = job.get("start_time", now)
                if (now - start) > 120:  # grazia di 2 min per leggere l'errore
                    to_remove.append((jid, "error"))
                continue

            # ── Analyzed but never started: cleanup if heartbeat lost ──
            if status == "analyzed":
                last_poll = job.get("last_poll", job.get("start_time", now))
                if (now - last_poll) > CLEANUP_HEARTBEAT_TIMEOUT_SEC * 3:  # 3 min per analyzed
                    to_remove.append((jid, "stale analyzed"))
                continue

            # ── Generating jobs ──
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

            # ── Done jobs ──
            if status == "done":
                dl_at = job.get("downloaded_at")
                email_sent_at = job.get("email_sent_at")
                last_poll = job.get("last_poll", 0)

                # REGOLA 3: Email inviata → mantieni 24h dall'invio
                if has_email and email_sent_at:
                    if (now - email_sent_at) > EMAIL_FILE_RETENTION_SEC:
                        to_remove.append((jid, f"email retention expired ({int(now - email_sent_at)}s)"))
                    continue

                # Email registrata ma non ancora inviata → mantieni
                if has_email and not email_sent_at:
                    continue

                # REGOLA 2: Download diretto dall'UI → cancella dopo breve grazia
                if dl_at:
                    if (now - dl_at) > CLEANUP_GRACE_AFTER_DOWNLOAD_SEC:
                        to_remove.append((jid, f"downloaded {int(now - dl_at)}s ago"))
                    continue

                # REGOLA 1: Nessun download, nessuna email, heartbeat perso → browser chiuso
                if last_poll and (now - last_poll) > CLEANUP_HEARTBEAT_TIMEOUT_SEC:
                    to_remove.append((jid, f"abandoned (heartbeat lost {int(now - last_poll)}s)"))
                    continue

        for jid, reason in to_remove:
            try:
                _cleanup_job(jid, reason)
            except Exception as e:
                print(f"[cleanup] error removing {jid}: {e}")

        # ── Cleanup expired download tokens ──
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

        # ── Cleanup cartelle orfane su disco ──
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


# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

# Startup: load persisted download tokens and start background threads
# (works both under __main__ and Gunicorn)
_load_tokens()
_cleanup_started = False

def _ensure_background_threads():
    global _cleanup_started
    if _cleanup_started:
        return
    _cleanup_started = True
    threading.Thread(target=get_voices, daemon=True).start()
    threading.Thread(target=_cleanup_loop, daemon=True).start()
    print(f"[startup] Background threads started (data dir: {UPLOAD_DIR})")
    print(f"[startup] Max concurrent per client: {MAX_CONCURRENT_PER_CLIENT}")
    if ADMIN_EMAIL:
        print(f"[startup] Admin digest enabled → {ADMIN_EMAIL} (interval: {ADMIN_DIGEST_INTERVAL_SEC}s)")
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
