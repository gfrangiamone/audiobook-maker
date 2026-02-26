#!/usr/bin/env python3
"""
Audiobook Maker — Web app to convert EPUB into MP3 audiobooks.

Requirements:
    pip install flask edge-tts ebooklib beautifulsoup4 lxml Pillow

Usage:
    python audiobook_app.py
    Then open http://localhost:5601
"""

import asyncio
import concurrent.futures
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
        _log_activity(job_id, job.get("original_filename", ""), "EMAIL_SENT")
    else:
        _log_activity(job_id, job.get("original_filename", ""), "EMAIL_FAILED")

# ── Activity log ──
_log_lock = threading.Lock()


def _log_activity(session_id, filename, operation):
    """Append one line to the activity log file (one file per month).

    Format (# separated):
        session_id # datetime # "filename" # operation
    Operations: ANALYZE, GENERATE, COMPLETE, DOWNLOAD, DOWNLOAD_PODCAST
    """
    from datetime import datetime
    now = datetime.now()
    log_path = SCRIPT_DIR / f"activity_{now.strftime('%Y-%m')}.log"
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    line = f'{session_id} # {ts} # "{filename}" # {operation}\n'
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
        _log_activity(job_id, job.get("original_filename", ""), "COMPLETE")

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
        _log_activity(job_id, job.get("original_filename", ""), "CANCEL")

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

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


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
    if not is_epub and not is_txt:
        return jsonify({"error": "File must be .epub or .txt"}), 400

    job_id = str(uuid.uuid4())[:8]
    work_dir = UPLOAD_DIR / job_id
    work_dir.mkdir(exist_ok=True)
    file_path = work_dir / file.filename
    file.save(str(file_path))

    try:
        if is_txt:
            info = parse_txt(str(file_path))
        else:
            info = parse_epub(str(file_path))
    except Exception as e:
        label = "TXT" if is_txt else "EPUB"
        return jsonify({"error": f"{label} parse error: {e}"}), 400

    if not info.chapters:
        return jsonify({"error": "No content found."}), 400

    jobs[job_id] = {"status": "analyzed", "epub_path": str(file_path), "info": info,
                     "last_poll": time.time(), "original_filename": file.filename}

    # Extract cover thumbnail for preview (EPUB only)
    has_cover = False
    if is_epub:
        cover_path, cover_mime = _extract_cover_for_preview(str(file_path), str(work_dir))
        if cover_path and os.path.exists(cover_path):
            has_cover = True
            jobs[job_id]["cover_thumb"] = cover_path
            jobs[job_id]["cover_mime"] = cover_mime

    _log_activity(job_id, file.filename, "ANALYZE")

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

    raw_preview = _pick_preview_text(info.chapters, is_txt)
    preview_text = _trim_preview(raw_preview) if raw_preview else ""
    # Store for /api/preview_audio
    jobs[job_id]["preview_text"] = preview_text
    # ──────────────────────────────────────────────────────────────────────────

    return jsonify({
        "job_id": job_id, "title": info.title, "author": info.author,
        "language": info.language,
        "file_type": "txt" if is_txt else "epub",
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
    _log_activity(job_id, job.get("original_filename", ""), "GENERATE")
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
    _log_activity(job_id, job.get("original_filename", ""), "EMAIL_REGISTERED")

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
            _log_activity(job_id, orig, "DOWNLOAD_EMAIL")
            return send_file(job["output_zip"], as_attachment=True,
                             download_name=job.get("output_name", output_name))
        if job.get("output_files") and os.path.exists(job["output_files"][0]):
            _log_activity(job_id, orig, "DOWNLOAD_EMAIL")
            return send_file(job["output_files"][0], as_attachment=True,
                             download_name=job.get("output_name", output_name))
        print(f"[dl] Job {job_id} in memory but files missing on disk")

    # 2. Try exact paths from token snapshot
    output_zip = token_info.get("output_zip", "")
    output_file = token_info.get("output_file", "")

    if output_zip and os.path.exists(output_zip):
        _log_activity(job_id, orig, "DOWNLOAD_EMAIL")
        return send_file(output_zip, as_attachment=True, download_name=output_name)
    if output_file and os.path.exists(output_file):
        _log_activity(job_id, orig, "DOWNLOAD_EMAIL")
        return send_file(output_file, as_attachment=True, download_name=output_name)

    # 3. Path reconstruction: stored paths may be from a different DATA_DIR
    #    Try to find files using just the filename under current job_dir
    if output_zip and not os.path.exists(output_zip):
        reconstructed = str(job_dir / os.path.basename(output_zip))
        if os.path.exists(reconstructed):
            print(f"[dl] Path reconstructed: {output_zip} -> {reconstructed}")
            _log_activity(job_id, orig, "DOWNLOAD_EMAIL")
            return send_file(reconstructed, as_attachment=True, download_name=output_name)
    if output_file and not os.path.exists(output_file):
        reconstructed = str(job_dir / "output" / os.path.basename(output_file))
        if os.path.exists(reconstructed):
            print(f"[dl] Path reconstructed: {output_file} -> {reconstructed}")
            _log_activity(job_id, orig, "DOWNLOAD_EMAIL")
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
            _log_activity(job_id, orig, "DOWNLOAD_EMAIL")
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
            _log_activity(job_id, orig, "DOWNLOAD_EMAIL")
            return send_file(found, as_attachment=True,
                             download_name=output_name or os.path.basename(found))
        elif len(mp3s) > 1:
            # Multiple MP3s: create a ZIP on the fly
            src_dir = str(mp3s[0].parent)
            zip_file = shutil.make_archive(str(job_dir / "download"), "zip", src_dir)
            print(f"[dl] Fallback: created ZIP from {len(mp3s)} MP3s -> {zip_file}")
            _log_activity(job_id, orig, "DOWNLOAD_EMAIL")
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
    _log_activity(job_id, orig, "DOWNLOAD_EMAIL_PODCAST")
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
               "warn": "&#x23F0; Hai ancora {r} per scaricare i file.<br>Dopo 24 ore dall'invio dell'email verranno cancellati."},
        "en": {"title": "Download", "h2": "Your audiobook is ready!",
               "btn": "&#x2B07;&#xFE0F; Download",
               "warn": "&#x23F0; You have {r} left to download the files.<br>They will be deleted 24 hours after the email was sent."},
        "fr": {"title": "T&eacute;l&eacute;chargement", "h2": "Votre livre audio est pr&ecirc;t !",
               "btn": "&#x2B07;&#xFE0F; T&eacute;l&eacute;charger",
               "warn": "&#x23F0; Il vous reste {r} pour t&eacute;l&eacute;charger les fichiers.<br>Ils seront supprim&eacute;s 24 heures apr&egrave;s l'envoi de l'email."},
        "es": {"title": "Descarga", "h2": "&iexcl;Tu audiolibro est&aacute; listo!",
               "btn": "&#x2B07;&#xFE0F; Descargar",
               "warn": "&#x23F0; Te quedan {r} para descargar los archivos.<br>Se eliminar&aacute;n 24 horas despu&eacute;s del env&iacute;o del email."},
        "de": {"title": "Download", "h2": "Dein H&ouml;rbuch ist fertig!",
               "btn": "&#x2B07;&#xFE0F; Herunterladen",
               "warn": "&#x23F0; Du hast noch {r} zum Herunterladen.<br>Die Dateien werden 24 Stunden nach dem E-Mail-Versand gel&ouml;scht."},
        "zh": {"title": "\u4e0b\u8f7d", "h2": "\u60a8\u7684\u6709\u58f0\u8bfb\u7269\u5df2\u51c6\u5907\u597d\uff01",
               "btn": "&#x2B07;&#xFE0F; \u4e0b\u8f7d",
               "warn": "&#x23F0; \u60a8\u8fd8\u6709 {r} \u7684\u65f6\u95f4\u4e0b\u8f7d\u6587\u4ef6\u3002<br>\u6587\u4ef6\u5c06\u5728\u90ae\u4ef6\u53d1\u9001\u540e24\u5c0f\u65f6\u5220\u9664\u3002"},
    }
    t = _t.get(lang, _t["en"])
    type_label = "Podcast ZIP" if dl_type == "podcast" else "Audio ZIP"
    warn_text = t["warn"].replace("{r}", remaining_str)
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
</style></head><body>
<div class="box">
<h1>&#x1F3A7;</h1>
<h2>{t['h2']}</h2>
<p class="title">{book_title}</p>
<p class="type">{type_label}</p>
<p><a href="/dl/{token}/download" class="btn">{t['btn']}</a></p>
<p class="warn">{warn_text}</p>
</div></body></html>"""


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
    _log_activity(job_id, job.get("original_filename", ""), "DOWNLOAD")
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

    _log_activity(job_id, job.get("original_filename", ""), "DOWNLOAD_PODCAST")
    return send_file(podcast_zip, as_attachment=True,
                     download_name=f"{safe_name}_podcast.zip")


# ═══════════════════════════════════════════════════════════════════
# HTML TEMPLATE (i18n, upload lock, ETA)
# ═══════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════
# HTML TEMPLATE (assembled from modular components)
# ═══════════════════════════════════════════════════════════════════

HTML_TEMPLATE = build_html_template(version=__version__)



# ═══════════════════════════════════════════════════════════════════
# AUTO-CLEANUP (deletes EPUB + MP3 files)
# ═══════════════════════════════════════════════════════════════════

CLEANUP_AFTER_DOWNLOAD_SEC = 60 * 60   # 60 minutes after download
CLEANUP_AFTER_ABANDON_SEC = 60 * 60    # 60 minutes after client disappears
CLEANUP_INTERVAL_SEC = 60              # check every 60 seconds


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

            # Cancelled jobs: immediate cleanup (already done in thread,
            # but belt-and-suspenders)
            if status == "cancelled":
                to_remove.append((jid, "cancelled"))
                continue

            # Jobs still generating with email registered: keep alive indefinitely
            if has_email and status in ("generating", "analyzed"):
                continue

            # Done jobs: protected by grace period from completion time
            if status == "done":
                completed_at = job.get("completed_at", 0)
                dl_at = job.get("downloaded_at")
                last_poll = job.get("last_poll", 0)
                email_sent_at = job.get("email_sent_at")

                # Email-registered jobs: keep for 24h from email sent
                if has_email and email_sent_at:
                    if (now - email_sent_at) > EMAIL_FILE_RETENTION_SEC:
                        to_remove.append((jid, f"email retention expired {int(now - email_sent_at)}s"))
                    continue
                # Email registered but not yet sent (still completing): keep
                if has_email and not email_sent_at:
                    continue

                # GRACE PERIOD: mai rimuovere un job completato da meno di 10 minuti
                # Questo protegge da heartbeat mancanti (tab in background, ecc.)
                if completed_at and (now - completed_at) < CLEANUP_AFTER_ABANDON_SEC:
                    continue

                # Downloaded 10+ min ago → cleanup
                if dl_at and (now - dl_at) > CLEANUP_AFTER_DOWNLOAD_SEC:
                    to_remove.append((jid, f"downloaded {int(now - dl_at)}s ago"))
                    continue

                # Not downloaded AND heartbeat scaduto da 10+ min → cleanup
                if not dl_at and last_poll and (now - last_poll) > CLEANUP_AFTER_ABANDON_SEC:
                    to_remove.append((jid, f"abandoned {int(now - last_poll)}s ago"))
                    continue

            # Error jobs: cleanup after 60s
            if status == "error":
                err_time = job.get("elapsed_seconds", 0)
                start = job.get("start_time", now)
                if (now - start) > CLEANUP_AFTER_ABANDON_SEC:
                    to_remove.append((jid, "error"))
                    continue

            # Analyzed but never started: cleanup if no poll for 5 min
            if status == "analyzed":
                created = job.get("last_poll", job.get("start_time", now))
                if (now - created) > 5 * 60:
                    to_remove.append((jid, "stale analyzed"))

        for jid, reason in to_remove:
            try:
                _cleanup_job(jid, reason)
            except Exception as e:
                print(f"[cleanup] error removing {jid}: {e}")

        # Cleanup expired download tokens
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
        if expired_tokens:
            _save_tokens()

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
