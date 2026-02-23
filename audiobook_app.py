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

    return jsonify({
        "job_id": job_id, "title": info.title, "author": info.author,
        "language": info.language,
        "file_type": "txt" if is_txt else "epub",
        "has_cover": has_cover,
        "total_chapters": len(info.chapters), "total_words": info.total_words,
        "total_chars": info.total_chars,
        "estimated_minutes": round(info.estimated_duration_minutes, 1),
        "chapters": chapters,
    })


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

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-RBY3J76PDV"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-RBY3J76PDV');</script>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCI+PGRlZnM+PGxpbmVhckdyYWRpZW50IGlkPSJiZyIgeDE9IjAlIiB5MT0iMCUiIHgyPSIxMDAlIiB5Mj0iMTAwJSI+PHN0b3Agb2Zmc2V0PSIwJSIgc3R5bGU9InN0b3AtY29sb3I6I2MyOWE2YyIvPjxzdG9wIG9mZnNldD0iMTAwJSIgc3R5bGU9InN0b3AtY29sb3I6I2EwNzg1MCIvPjwvbGluZWFyR3JhZGllbnQ+PC9kZWZzPjxyZWN0IHdpZHRoPSI2NCIgaGVpZ2h0PSI2NCIgcng9IjE0IiBmaWxsPSJ1cmwoI2JnKSIvPjxwYXRoIGQ9Ik0xNiA0NFYyMGMwLTIgMS41LTMuNSAzLjUtMy41QzIzIDE2LjUgMjggMTcgMzIgMTljNC0yIDktMi41IDEyLjUtMi41IDIgMCAzLjUgMS41IDMuNSAzLjV2MjQiIGZpbGw9Im5vbmUiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIyLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPjxwYXRoIGQ9Ik0zMiAxOXYyNSIgc3Ryb2tlPSIjZmZmIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPjxwYXRoIGQ9Ik0xNyAzNmMwLTkgNi43LTE1IDE1LTE1czE1IDYgMTUgMTUiIGZpbGw9Im5vbmUiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIyLjgiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPjxyZWN0IHg9IjEzIiB5PSIzNCIgd2lkdGg9IjciIGhlaWdodD0iMTAiIHJ4PSIzIiBmaWxsPSIjZmZmIi8+PHJlY3QgeD0iNDQiIHk9IjM0IiB3aWR0aD0iNyIgaGVpZ2h0PSIxMCIgcng9IjMiIGZpbGw9IiNmZmYiLz48L3N2Zz4=">
<title>Audiobook Maker — EPUB to Audiobook TTS Converter</title>
<meta name="description" id="metaDesc" content="Free online tool to convert EPUB ebooks into high-quality audiobooks using neural text-to-speech (TTS) voices. Supports multiple languages, chapter selection, and podcast RSS feed generation.">
<meta name="keywords" id="metaKw" content="audiobook, ebook, epub, tts, text to speech, epub to audiobook, ebook converter, audiobook maker, tts ebook, neural voices, free audiobook, accessibility, podcast, rss">
<meta name="author" content="Audiobook Maker">
<meta name="robots" content="index, follow">
<meta name="theme-color" content="#c29a6c">
<!-- Open Graph -->
<meta property="og:type" content="website">
<meta property="og:title" id="ogTitle" content="Audiobook Maker — EPUB to Audiobook TTS Converter">
<meta property="og:description" id="ogDesc" content="Free online tool to convert EPUB ebooks into high-quality audiobooks using neural text-to-speech (TTS) voices.">
<meta property="og:site_name" content="Audiobook Maker">
<!-- Twitter Card -->
<meta name="twitter:card" content="summary">
<meta name="twitter:title" id="twTitle" content="Audiobook Maker — EPUB to Audiobook TTS Converter">
<meta name="twitter:description" id="twDesc" content="Free online tool to convert EPUB ebooks into high-quality audiobooks using neural text-to-speech (TTS) voices.">
<!-- JSON-LD Structured Data -->
<script type="application/ld+json" id="jsonLd">
{
  "@context":"https://schema.org",
  "@type":"WebApplication",
  "name":"Audiobook Maker",
  "applicationCategory":"MultimediaApplication",
  "operatingSystem":"Any",
  "offers":{"@type":"Offer","price":"0","priceCurrency":"USD"},
  "description":"Free online tool to convert EPUB ebooks into high-quality audiobooks using neural text-to-speech (TTS) voices.",
  "featureList":["EPUB to audiobook conversion","Neural TTS voices","Multiple languages","Chapter selection","Podcast RSS feed","Accessibility support"]
}
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,500;0,600;0,700&family=DM+Serif+Display&display=swap" rel="stylesheet">
<style>
/* ═══ LIGHT THEME (default) ═══ */
:root{
  --bg:#f5f3ef;--srf:#ffffff;--srf2:#f0ede8;--srf3:#e6e2dc;--brd:#d5d0c8;--brdh:#bfb8ae;
  --tx:#2c2a26;--txd:#6b6760;--txm:#9e9890;
  --ac:#c47a2a;--acs:rgba(196,122,42,.10);--ach:#d4903e;
  --ok:#3a9e5c;--oks:rgba(58,158,92,.10);
  --err:#c44040;--errs:rgba(196,64,64,.08);
  --r:12px;--rs:8px;
  --shadow:0 2px 12px rgba(0,0,0,.06);
  --deco-opacity:.045;
  --sel-arrow:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12'%3E%3Cpath fill='%239e9890' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
}
/* ═══ DARK THEME ═══ */
[data-theme="dark"]{
  --bg:#0e0e11;--srf:#18181d;--srf2:#222228;--srf3:#2c2c34;--brd:#333340;--brdh:#4a4a5a;
  --tx:#e8e8ed;--txd:#9090a0;--txm:#606070;
  --ac:#f0a050;--acs:rgba(240,160,80,.12);--ach:#f5b570;
  --ok:#50c878;--oks:rgba(80,200,120,.12);
  --err:#e05555;--errs:rgba(224,85,85,.12);
  --shadow:0 4px 24px rgba(0,0,0,.3);
  --deco-opacity:.04;
  --sel-arrow:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12'%3E%3Cpath fill='%239090a0' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'DM Sans',-apple-system,sans-serif;background:var(--bg);color:var(--tx);min-height:100vh;line-height:1.6;transition:background .4s,color .3s;position:relative;overflow-x:hidden}

/* ═══ BG DECORATIONS ═══ */
.bg-deco{position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;overflow:hidden}
.bg-deco svg{position:absolute;opacity:var(--deco-opacity);transition:opacity .4s}
.deco-book1{top:6%;left:-2%;width:180px;transform:rotate(-12deg)}
.deco-book2{top:28%;right:-3%;width:140px;transform:rotate(8deg)}
.deco-wave1{top:52%;left:-4%;width:240px;transform:rotate(-5deg)}
.deco-wave2{bottom:18%;right:-2%;width:200px;transform:rotate(10deg)}
.deco-phones{bottom:5%;left:8%;width:120px;transform:rotate(-18deg)}
.deco-note1{top:14%;right:12%;width:60px;transform:rotate(20deg)}
.deco-note2{bottom:35%;left:5%;width:50px;transform:rotate(-25deg)}
.deco-pages{top:70%;right:8%;width:100px;transform:rotate(15deg)}
@media(max-width:700px){.bg-deco svg{opacity:calc(var(--deco-opacity) * .5)}}

/* ═══ LAYOUT ═══ */
.app{max-width:800px;margin:0 auto;padding:40px 24px 80px;position:relative;z-index:1}
.hdr{text-align:center;margin-bottom:48px}
.hdr h1{font-family:'DM Serif Display',serif;font-size:2.2rem;font-weight:400;letter-spacing:-.02em;background:linear-gradient(135deg,var(--tx) 30%,var(--ac));-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px;display:inline-flex;align-items:center;gap:12px;justify-content:center}
.hdr-icon{width:42px;height:42px;flex-shrink:0}
.hdr-icon .ic-book{fill:var(--ac);opacity:.85}
.hdr-icon .ic-wave{stroke:var(--ac);fill:none;stroke-width:2;stroke-linecap:round;opacity:.7}
.hdr p{color:var(--txd);font-size:.95rem}

/* ═══ TOOLBAR: language + theme ═══ */
.toolbar{display:flex;justify-content:center;align-items:center;gap:12px;margin-top:16px;flex-wrap:wrap}
.lsw{display:flex;gap:4px;flex-wrap:wrap}
.lsw button{background:var(--srf2);border:1px solid var(--brd);color:var(--txd);padding:4px 10px;border-radius:6px;font-size:.78rem;cursor:pointer;font-family:inherit;transition:all .2s}
.lsw button:hover{border-color:var(--brdh);color:var(--tx)}
.lsw button.on{background:var(--acs);border-color:var(--ac);color:var(--ac);font-weight:600}
.theme-sep{width:1px;height:20px;background:var(--brd);flex-shrink:0}
.theme-btn{background:var(--srf2);border:1px solid var(--brd);color:var(--txd);width:36px;height:28px;border-radius:6px;cursor:pointer;font-size:1rem;display:flex;align-items:center;justify-content:center;transition:all .2s;flex-shrink:0}
.theme-btn:hover{border-color:var(--ac);color:var(--ac)}

/* ═══ FREE BOOKS BUTTON ═══ */
.fb-btn{background:var(--acs);border:1px solid var(--ac);color:var(--ac);padding:6px 16px;border-radius:20px;font-size:.82rem;font-weight:600;cursor:pointer;font-family:inherit;transition:all .2s;display:inline-flex;align-items:center;gap:6px;margin-top:14px}
.fb-btn:hover{background:var(--ac);color:#fff}
.fb-btn svg{width:16px;height:16px;fill:currentColor;flex-shrink:0}

/* ═══ MODAL ═══ */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:1000;justify-content:center;align-items:center;padding:20px}
.modal-overlay.open{display:flex}
.modal{background:var(--srf);border-radius:var(--r);max-width:640px;width:100%;max-height:85vh;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 8px 40px rgba(0,0,0,.25);border:1px solid var(--brd)}
.modal-head{display:flex;justify-content:space-between;align-items:center;padding:20px 24px 16px;border-bottom:1px solid var(--brd)}
.modal-head h2{font-family:'DM Serif Display',serif;font-size:1.3rem;font-weight:400;color:var(--tx);margin:0}
.modal-close{background:none;border:none;font-size:1.5rem;cursor:pointer;color:var(--txm);padding:0 4px;line-height:1;transition:color .2s}
.modal-close:hover{color:var(--tx)}
.modal-body{overflow-y:auto;padding:16px 24px 24px}
.site-card{display:flex;gap:14px;padding:14px 0;border-bottom:1px solid var(--srf3);align-items:flex-start}
.site-card:last-child{border-bottom:none}
.site-icon{width:36px;height:36px;border-radius:8px;background:var(--acs);display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:1.1rem}
.site-info{flex:1;min-width:0}
.site-name{font-weight:600;font-size:.95rem;margin-bottom:3px}
.site-name a{color:var(--ac);text-decoration:none;transition:color .2s}
.site-name a:hover{text-decoration:underline}
.site-desc{font-size:.82rem;color:var(--txd);line-height:1.45}
@media(max-width:500px){.modal{max-height:92vh}.modal-body{padding:12px 16px 20px}}

/* ═══ FOOTER ═══ */
.footer{text-align:center;padding:24px 0 8px;margin-top:8px}
.footer a{color:var(--txm);font-size:.82rem;text-decoration:none;transition:color .2s}
.footer a:hover{color:var(--ac);text-decoration:underline}
.about-text{font-size:.9rem;color:var(--txd);line-height:1.7;text-align:justify;margin:0 0 10px}
.about-contact{margin-top:16px;font-size:.88rem}
.about-contact a{color:var(--ac);text-decoration:none;font-weight:500}
.about-contact a:hover{text-decoration:underline}

/* ═══ STEPS ═══ */
.step{background:var(--srf);border:1px solid var(--brd);border-radius:var(--r);margin-bottom:16px;transition:all .3s;box-shadow:var(--shadow);overflow:hidden;border-left:3px solid transparent}
.step:not(.collapsed):not(.disabled){border-left-color:var(--ac)}
.step:hover{border-color:var(--brdh)}
.step.collapsed{opacity:.7}
.step.collapsed:hover{opacity:.85}
.step.disabled{opacity:.4;pointer-events:none}
.step.disabled .sh{cursor:default}
.step.disabled .sh:hover{background:transparent}
.step.locked{opacity:.35;pointer-events:none;position:relative}
.step.locked::after{content:'\\1F512';position:absolute;top:12px;right:16px;font-size:1.1rem}
.step-body{max-height:2000px;overflow:hidden;padding:0 28px 28px;transition:max-height .45s ease,padding .35s ease,opacity .3s ease;opacity:1}
.step.collapsed .step-body{max-height:0;padding:0 28px;opacity:0}
.sh{display:flex;align-items:center;gap:12px;padding:20px 28px;margin:0;cursor:pointer;user-select:none;transition:background .2s}
.sh:hover{background:var(--srf2);border-radius:var(--r) var(--r) 0 0}
.step.collapsed .sh{padding:16px 28px}
.step.collapsed .sh:hover{border-radius:var(--r)}
.sh-chev{margin-left:auto;font-size:.7rem;color:var(--txm);transition:transform .3s;flex-shrink:0}
.step.collapsed .sh-chev{transform:rotate(-90deg)}
.sh-sum{font-size:.78rem;color:var(--txm);font-weight:400;margin-left:auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:0;opacity:0;transition:max-width .3s,opacity .3s;padding-right:8px}
.step.collapsed .sh-sum{max-width:300px;opacity:1}
.sn{width:32px;height:32px;background:var(--acs);color:var(--ac);border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:.85rem;flex-shrink:0;transition:background .3s,color .3s}
.step.done .sn{background:var(--ok);color:#fff}
.st{font-weight:600;font-size:1.05rem}

/* ═══ UPLOAD ═══ */
.uz{border:2px dashed var(--brd);border-radius:var(--r);padding:48px 24px;text-align:center;cursor:pointer;transition:all .25s;background:var(--srf2)}
.uz:hover,.uz.dg{border-color:var(--ac);background:var(--acs)}
.uz.ok{border-style:solid;border-color:var(--ok);background:var(--oks)}
.uz input[type=file]{display:none}
.uz .ic{font-size:2.5rem;margin-bottom:12px}
.uz .tx{color:var(--txd);font-size:.9rem}
.uz .fn{color:var(--ok);font-weight:600;margin-top:8px}

/* ═══ FORMS ═══ */
.fr{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
@media(max-width:600px){.fr{grid-template-columns:1fr}}
.fg{margin-bottom:16px}.fg:last-child{margin-bottom:0}
label{display:block;font-size:.85rem;font-weight:500;color:var(--txd);margin-bottom:6px;text-transform:uppercase;letter-spacing:.05em}
select{width:100%;padding:10px 14px;background:var(--srf2);border:1px solid var(--brd);border-radius:var(--rs);color:var(--tx);font-family:inherit;font-size:.95rem;transition:border-color .2s;appearance:none;-webkit-appearance:none;background-image:var(--sel-arrow);background-repeat:no-repeat;background-position:right 12px center;padding-right:36px}
select:focus{outline:none;border-color:var(--ac)}
.tg{display:flex;background:var(--srf2);border-radius:var(--rs);border:1px solid var(--brd);overflow:hidden}
.tg button{flex:1;padding:10px 16px;text-align:center;font-size:.9rem;font-weight:500;cursor:pointer;color:var(--txd);transition:all .2s;border:none;background:transparent;font-family:inherit}
.tg button.on{background:var(--acs);color:var(--ac)}
.tg button:hover:not(.on){background:var(--srf3);color:var(--tx)}
.pod-hint{margin-top:8px;font-size:.8rem;color:var(--ac);opacity:.85}

/* ═══ TABLE ═══ */
.ct{width:100%;border-collapse:collapse;margin-top:16px;font-size:.88rem}
.ct thead th{text-align:left;padding:8px 12px;color:var(--txm);font-weight:500;font-size:.78rem;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid var(--brd)}
.ct thead th:last-child{text-align:right}
.ct tbody td{padding:10px 12px;border-bottom:1px solid var(--srf3);color:var(--txd)}
.ct tbody td:first-child{color:var(--tx);font-weight:500}
.ct tbody td:last-child{text-align:right;color:var(--ac);font-weight:600}
.ct tbody tr:hover td{background:var(--srf2)}
.ct .col-sel{width:36px;text-align:center!important;padding-left:6px;padding-right:2px}
.ct .col-sel input[type=checkbox]{width:16px;height:16px;accent-color:var(--ac);cursor:pointer;vertical-align:middle}
.ct tbody tr.unchecked td:not(.col-sel){opacity:.4;text-decoration:line-through;text-decoration-color:var(--txm)}
.sel-bar{display:none;align-items:center;gap:12px;margin-top:14px;padding:8px 12px;background:var(--srf2);border-radius:var(--rs);font-size:.82rem;flex-wrap:wrap}
.sel-bar.vis{display:flex}
.sel-bar .sel-info{color:var(--txd);margin-right:auto}
.sel-bar .sel-info b{color:var(--ac)}
.sel-bar a{color:var(--ac);cursor:pointer;font-weight:500;text-decoration:none;white-space:nowrap}
.sel-bar a:hover{text-decoration:underline}
.cn{color:var(--txm);margin-right:8px;font-size:.82rem}
.bk-info{display:flex;gap:16px;align-items:flex-start;margin-bottom:16px}
.bk-cover{width:90px;height:auto;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,.15);flex-shrink:0;object-fit:cover}
.bk-meta{flex:1;min-width:0}
@media(max-width:480px){.bk-cover{width:70px}}
.sb{display:flex;gap:24px;padding:16px 0;border-top:1px solid var(--brd);margin-top:16px;flex-wrap:wrap}
.si{display:flex;flex-direction:column;gap:2px}
.sl{font-size:.75rem;text-transform:uppercase;letter-spacing:.06em;color:var(--txm)}
.sv{font-size:1.1rem;font-weight:700;color:var(--ac)}

/* ═══ BUTTONS ═══ */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:14px 28px;border-radius:var(--rs);font-family:inherit;font-size:.95rem;font-weight:600;border:none;cursor:pointer;transition:all .2s;width:100%}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-p{background:var(--ac);color:#fff}
.btn-p:hover:not(:disabled){background:var(--ach);transform:translateY(-1px);box-shadow:0 4px 16px rgba(196,122,42,.25)}
.btn-ok{background:var(--ok);color:#fff}
.btn-ok:hover:not(:disabled){filter:brightness(1.1)}
.btn-g{background:var(--srf2);color:var(--txd);border:1px solid var(--brd);margin-top:10px}
.btn-g:hover{border-color:var(--ac);color:var(--ac)}

/* ═══ PROGRESS ═══ */
.pa{padding:20px 0}
.pb{width:100%;height:8px;background:var(--srf2);border-radius:4px;overflow:hidden;margin:16px 0 12px}
.pf{height:100%;background:linear-gradient(90deg,var(--ac),var(--ach));border-radius:4px;transition:width .5s ease;width:0}
.pt{display:flex;justify-content:space-between;align-items:baseline}
.pp{font-size:2rem;font-weight:700;color:var(--ac)}
.pc{font-size:.85rem;color:var(--txd);text-align:right;max-width:55%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pm{color:var(--txd);font-size:.88rem;margin-bottom:16px}
.ps{display:flex;gap:20px;flex-wrap:wrap;padding-top:12px;border-top:1px solid var(--srf3)}
.pi{display:flex;flex-direction:column;gap:1px}
.pl{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--txm)}
.pv{font-size:.95rem;font-weight:600;color:var(--tx)}

/* ═══ MISC ═══ */
.sp{display:inline-block;width:20px;height:20px;border:2px solid var(--txm);border-top-color:var(--ac);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.al{padding:14px 18px;border-radius:var(--rs);font-size:.9rem;margin-bottom:16px}
.al-e{background:var(--errs);color:var(--err);border:1px solid rgba(196,64,64,.15)}
.lo{display:none;padding:32px;text-align:center}.lo.vis{display:block}
.lo .tx{color:var(--txd);margin-top:12px;font-size:.9rem}
.fi{animation:fi .4s ease}
@keyframes fi{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.disc{background:var(--srf);border:1px solid var(--brd);border-radius:var(--rs);padding:14px 18px;margin-bottom:20px;font-size:.82rem;color:var(--txm);line-height:1.5;text-align:center;box-shadow:var(--shadow)}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:var(--srf2)}::-webkit-scrollbar-thumb{background:var(--brd);border-radius:3px}
</style>
</head>
<body>
<!-- Background decorative SVGs -->
<div class="bg-deco">
  <!-- Open book -->
  <svg class="deco-book1" viewBox="0 0 200 160" fill="currentColor"><path d="M100 20C80 10 40 5 10 8v120c30-3 70 0 90 12 20-12 60-15 90-12V8c-30-3-70 2-90 12z"/><line x1="100" y1="20" x2="100" y2="140" stroke="currentColor" stroke-width="2" fill="none"/><path d="M30 35h40M30 55h50M30 75h45M30 95h40" stroke="currentColor" stroke-width="1.5" opacity=".3" fill="none"/><path d="M120 35h40M120 55h50M120 75h45M120 95h40" stroke="currentColor" stroke-width="1.5" opacity=".3" fill="none"/></svg>
  <!-- Stacked books -->
  <svg class="deco-book2" viewBox="0 0 140 180" fill="currentColor"><rect x="15" y="120" width="110" height="22" rx="3" opacity=".7"/><rect x="10" y="95" width="115" height="22" rx="3" opacity=".55"/><rect x="20" y="70" width="100" height="22" rx="3" opacity=".4"/><rect x="25" y="45" width="90" height="22" rx="3" opacity=".3"/><path d="M60 10l30 30H30z" opacity=".2"/></svg>
  <!-- Audio wave -->
  <svg class="deco-wave1" viewBox="0 0 260 80" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M10 40h20M40 25v30M55 15v50M70 22v36M85 10v60M100 20v40M115 30v20M130 18v44M145 8v64M160 22v36M175 32v16M190 20v40M205 28v24M220 35v10M240 38v4"/></svg>
  <!-- Audio wave 2 -->
  <svg class="deco-wave2" viewBox="0 0 220 70" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M10 35h15M30 20v30M45 12v46M60 22v26M75 8v54M90 18v34M105 28v14M120 15v40M135 10v50M150 25v20M165 18v34M180 30v10M200 33v4"/></svg>
  <!-- Headphones -->
  <svg class="deco-phones" viewBox="0 0 120 120" fill="currentColor"><path d="M60 15C33 15 15 35 15 60v25c0 8 6 14 14 14h8V65h-8c-2 0-4 .4-6 1v-6c0-20 15-35 37-35s37 15 37 35v6c-2-.6-4-1-6-1h-8v34h8c8 0 14-6 14-14V60c0-25-18-45-45-45z" opacity=".6"/><rect x="19" y="68" width="14" height="28" rx="5" opacity=".4"/><rect x="87" y="68" width="14" height="28" rx="5" opacity=".4"/></svg>
  <!-- Music note -->
  <svg class="deco-note1" viewBox="0 0 60 80" fill="currentColor"><ellipse cx="18" cy="62" rx="14" ry="10" opacity=".5"/><rect x="30" y="12" width="3" height="52" opacity=".4"/><path d="M33 12c10-4 22-2 22 10-8-8-18-6-22-2z" opacity=".4"/></svg>
  <!-- Music note 2 -->
  <svg class="deco-note2" viewBox="0 0 50 70" fill="currentColor"><ellipse cx="15" cy="55" rx="12" ry="8" opacity=".5"/><rect x="25" y="10" width="2.5" height="47" opacity=".4"/><path d="M27.5 10c8-3 18-1 18 8-7-7-15-5-18-1z" opacity=".4"/></svg>
  <!-- Turning pages -->
  <svg class="deco-pages" viewBox="0 0 120 100" fill="currentColor"><path d="M10 90V15c25-5 45 0 50 10V90C50 80 35 77 10 80z" opacity=".25"/><path d="M60 25c5-10 25-15 50-10v75c-25-3-40 0-50 10z" opacity=".35"/><path d="M55 20Q70 5 90 10" stroke="currentColor" stroke-width="1.5" fill="none" opacity=".2"/></svg>
</div>

<div class="app">
  <div class="hdr">
    <h1><svg class="hdr-icon" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg"><path class="ic-book" d="M6 10c0-1.1.9-2 2-2h10c2.2 0 4 1.8 4 4v24a3 3 0 0 0-3-3H8a2 2 0 0 1-2-2V10z"/><path class="ic-book" d="M42 10c0-1.1-.9-2-2-2H30c-2.2 0-4 1.8-4 4v24a3 3 0 0 1 3-3h11a2 2 0 0 0 2-2V10z" opacity=".65"/><path class="ic-wave" d="M33 18c1.7 1.3 3 3.5 3 6s-1.3 4.7-3 6"/><path class="ic-wave" d="M37 14c2.8 2.3 5 6 5 10s-2.2 7.7-5 10"/></svg>Audiobook Maker</h1>
    <p data-t="subtitle"></p>
    <div class="toolbar">
      <div class="lsw" id="lsw">
        <button data-l="it">Italiano</button>
        <button data-l="en">English</button>
        <button data-l="fr">Fran&ccedil;ais</button>
        <button data-l="es">Espa&ntilde;ol</button>
        <button data-l="de">Deutsch</button>
        <button data-l="zh">&#x4E2D;&#x6587;</button>
      </div>
      <div class="theme-sep"></div>
      <button class="theme-btn" id="themeBtn" title="Toggle theme">&#x2600;&#xFE0F;</button>
    </div>
    <button class="fb-btn" id="fbBtn"><svg viewBox="0 0 24 24"><path d="M21 5c-1.1-.3-2.3-.5-3.5-.5-1.9 0-4 .4-5.5 1.5C10.6 4.9 8.5 4.5 6.5 4.5 5.3 4.5 4.1 4.7 3 5v14.7c0 .2.2.4.5.4.1 0 .2 0 .3-.1C5 19.3 6.7 19 8.5 19c1.9 0 4 .4 5.5 1.5 1.3-.8 3.2-1.5 5.5-1.5 1.7 0 3.4.3 4.7.8.1 0 .2.1.3.1.3 0 .5-.2.5-.4V5.3c-.5-.2-1-.3-1.5-.4zM21 18.5c-1.3-.4-2.7-.6-4-.6-1.9 0-4 .4-5.5 1.5V8c1.5-1.1 3.6-1.5 5.5-1.5 1.4 0 2.7.2 4 .6v11.4z"/></svg><span data-t="btn_free_books"></span></button>
    <button class="fb-btn" id="pgBtn"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg><span data-t="btn_podcast_guide"></span></button>
  </div>

  <!-- FREE BOOKS MODAL -->
  <div class="modal-overlay" id="fbModal">
    <div class="modal">
      <div class="modal-head">
        <h2 data-t="modal_free_title"></h2>
        <button class="modal-close" id="fbClose">&times;</button>
      </div>
      <div class="modal-body" id="fbBody"></div>
    </div>
  </div>

  <!-- PODCAST GUIDE MODAL -->
  <div class="modal-overlay" id="pgModal">
    <div class="modal" style="max-width:720px">
      <div class="modal-head">
        <h2 data-t="modal_guide_title"></h2>
        <button class="modal-close" id="pgClose">&times;</button>
      </div>
      <div class="modal-body" id="pgBody" style="max-height:70vh;overflow-y:auto"></div>
    </div>
  </div>

  <!-- DISCLAIMER -->
  <div class="disc" data-t="disclaimer"></div>

  <!-- STEP 1 -->
  <div class="step" id="s1">
    <div class="sh" onclick="toggleStep('s1')"><div class="sn">1</div><div class="st" data-t="s1_title"></div><span class="sh-sum" id="s1sum"></span><div class="sh-chev">&#x25BC;</div></div>
    <div class="step-body">
    <div class="uz" id="uz">
      <input type="file" id="fi" accept=".epub,.txt">
      <div class="ic">&#x1F4DA;</div>
      <div class="tx" id="utx" data-t="upload_text"></div>
      <div class="fn" id="ufn" style="display:none"></div>
    </div>
    <div class="lo" id="alo"><div class="sp"></div><div class="tx" data-t="analyzing"></div></div>
    <div id="aerr"></div>
    </div>
  </div>

  <!-- STEP 2 -->
  <div class="step collapsed disabled" id="s2">
    <div class="sh" onclick="toggleStep('s2')"><div class="sn">2</div><div class="st" data-t="s2_title"></div><span class="sh-sum" id="s2sum"></span><div class="sh-chev">&#x25BC;</div></div>
    <div class="step-body">
    <div class="fr">
      <div class="fg"><label data-t="lbl_lang"></label><select id="vl"><option>...</option></select></div>
      <div class="fg"><label data-t="lbl_voice"></label><select id="vv"><option data-t="voice_ph"></option></select></div>
    </div>
    <div class="fr">
      <div class="fg"><label data-t="lbl_speed"></label>
        <select id="vr">
          <option value="-30%" data-t="sp_vs"></option>
          <option value="-20%" data-t="sp_s"></option>
          <option value="-10%" data-t="sp_ss"></option>
          <option value="+0%" selected data-t="sp_n"></option>
          <option value="+10%" data-t="sp_sf"></option>
          <option value="+20%" data-t="sp_f"></option>
          <option value="+30%" data-t="sp_vf"></option>
        </select>
      </div>
      <div class="fg" id="fgOut"><label data-t="lbl_out"></label>
        <div class="tg">
          <button class="on" data-v="single" id="toS" data-t="out_single"></button>
          <button data-v="chapters" id="toC" data-t="out_ch"></button>
        </div>
        <div class="pod-hint" id="podHint" style="display:none">&#x1F399;&#xFE0F; <span data-t="podcast_hint"></span></div>
      </div>
    </div>
    </div>
  </div>

  <!-- STEP 3 -->
  <div class="step collapsed disabled" id="s3">
    <div class="sh" onclick="toggleStep('s3')"><div class="sn">3</div><div class="st" data-t="s3_title"></div><span class="sh-sum" id="s3sum"></span><div class="sh-chev">&#x25BC;</div></div>
    <div class="step-body">
    <div class="bk-info">
      <img id="bkCover" class="bk-cover" style="display:none" alt="">
      <div class="bk-meta">
        <div style="font-family:'DM Serif Display',serif;font-size:1.3rem" id="bkT"></div>
        <div style="color:var(--txd);font-size:.9rem" id="bkA"></div>
      </div>
    </div>
    <div class="sb">
      <div class="si"><span class="sl" data-t="sum_ch"></span><span class="sv" id="smC">-</span></div>
      <div class="si"><span class="sl" data-t="sum_w"></span><span class="sv" id="smW">-</span></div>
      <div class="si"><span class="sl" data-t="sum_chr"></span><span class="sv" id="smCh">-</span></div>
      <div class="si"><span class="sl" data-t="sum_d"></span><span class="sv" id="smD">-</span></div>
    </div>
    <div class="sel-bar" id="selBar">
      <span class="sel-info"><b id="selCnt">0</b> / <span id="selTot">0</span> <span data-t="sel_selected"></span></span>
      <a id="selAll" data-t="sel_all"></a>
      <a id="selNone" data-t="sel_none"></a>
      <a id="selInv" data-t="sel_invert"></a>
    </div>
    <div style="max-height:320px;overflow-y:auto;border-radius:var(--rs)">
      <table class="ct"><thead><tr><th class="col-sel" id="thSel" style="display:none"><input type="checkbox" id="chAll" checked></th><th data-t="col_ch"></th><th data-t="col_w"></th><th data-t="col_d"></th></tr></thead>
      <tbody id="chl"></tbody></table>
    </div>
    <div id="s3err"></div>
    <div style="margin-top:24px">
      <button class="btn btn-p" id="btnG">&#x1F3A7; <span data-t="btn_gen"></span></button>
    </div>
    </div>
  </div>

  <!-- STEP 4 -->
  <div class="step" id="s4" style="display:none">
    <div class="sh"><div class="sn">4</div><div class="st" id="s4t" data-t="s4_title"></div></div>
    <div class="step-body">
    <div class="bk-info" id="s4book" style="padding-bottom:12px;border-bottom:1px solid var(--brd)">
      <img id="s4bkCover" class="bk-cover" style="display:none" alt="">
      <div class="bk-meta">
        <div style="font-family:'DM Serif Display',serif;font-size:1.2rem" id="s4bkT"></div>
        <div style="color:var(--txd);font-size:.88rem" id="s4bkA"></div>
      </div>
    </div>
    <div class="pa" id="pra">
      <div class="pt"><div class="pp" id="pPct">0%</div><div class="pc" id="pCh"></div></div>
      <div class="pb"><div class="pf" id="pBar"></div></div>
      <div class="pm" id="pMsg"></div>
      <div class="ps">
        <div class="pi"><span class="pl" data-t="st_blk"></span><span class="pv" id="xBlk">-</span></div>
        <div class="pi"><span class="pl" data-t="st_ch"></span><span class="pv" id="xCh">-</span></div>
        <div class="pi"><span class="pl" data-t="st_el"></span><span class="pv" id="xEl">-</span></div>
        <div class="pi"><span class="pl" data-t="st_rem"></span><span class="pv" id="xEta">-</span></div>
        <div class="pi"><span class="pl" data-t="st_sz"></span><span class="pv" id="xSz">-</span></div>
        <div class="pi"><span class="pl" data-t="st_spd"></span><span class="pv" id="xSpd">-</span></div>
      </div>
    </div>
    <div id="cnA" style="margin-top:16px">
      <button class="btn btn-g" id="btnC" style="border-color:var(--err);color:var(--err)">&#x23F9;&#xFE0F; <span data-t="btn_cancel"></span></button>
    </div>
    <div id="emailStatus" style="display:none;margin-top:12px;padding:10px 16px;border-radius:8px;background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.2);font-size:.88rem;color:var(--ok)">
      &#x2709;&#xFE0F; <span id="emailStatusText"></span>
    </div>
    <div id="dlA" style="display:none;margin-top:20px">
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <button class="btn btn-ok" id="btnD">&#x2B07;&#xFE0F; <span data-t="btn_dl"></span></button>
        <button class="btn btn-ok" id="btnP" style="display:none;background:var(--ac);opacity:.85">&#x1F399;&#xFE0F; <span data-t="btn_dl_podcast"></span></button>
      </div>
      <div style="margin-top:10px">
        <button class="btn btn-g" id="btnN">&#x1F4DA; <span data-t="btn_new"></span></button>
      </div>
    </div>
    </div>
  </div>

  <!-- FOOTER -->
  <div class="footer"><a href="#" id="aboutBtn"></a></div>

  <!-- ABOUT MODAL -->
  <div class="modal-overlay" id="aboutModal">
    <div class="modal" style="max-width:560px">
      <div class="modal-head">
        <h2 id="aboutTitle"></h2>
        <button class="modal-close" id="aboutClose">&times;</button>
      </div>
      <div class="modal-body" id="aboutBody"></div>
    </div>
  </div>

  <!-- EMAIL NOTIFICATION MODAL -->
  <div class="modal-overlay" id="emailModal">
    <div class="modal" style="max-width:480px">
      <div class="modal-head">
        <h2 id="emTitle">&#x1F4E7;</h2>
        <button class="modal-close" id="emClose">&times;</button>
      </div>
      <div class="modal-body">
        <p id="emDesc" style="margin-bottom:16px"></p>
        <div id="emDlType" style="margin-bottom:14px">
          <label style="display:block;font-weight:600;margin-bottom:8px" id="emDlLabel"></label>
          <label style="display:block;cursor:pointer;margin-bottom:6px">
            <input type="radio" name="emDl" value="audio" checked> <span id="emDlAudioL"></span>
          </label>
          <label style="display:block;cursor:pointer;margin-bottom:6px">
            <input type="radio" name="emDl" value="podcast"> <span id="emDlPodcastL"></span>
          </label>
        </div>
        <div id="emBaseUrlWrap" style="display:none;margin-bottom:14px">
          <label style="display:block;font-weight:600;margin-bottom:4px" id="emBaseUrlLabel"></label>
          <input type="url" id="emBaseUrl" placeholder="https://example.com/podcast/" style="width:100%;padding:10px;border:1px solid var(--brd);border-radius:6px;font-size:.95rem;box-sizing:border-box">
        </div>
        <div style="margin-bottom:14px">
          <input type="email" id="emEmail" style="width:100%;padding:12px;border:1px solid var(--brd);border-radius:6px;font-size:1rem;box-sizing:border-box">
        </div>
        <div id="emErr" style="color:var(--err);font-size:.85rem;margin-bottom:10px;display:none"></div>
        <div id="emOk" style="color:var(--ok);font-size:.95rem;padding:12px;background:rgba(34,197,94,.08);border-radius:8px;display:none"></div>
        <div id="emBtns" style="display:flex;gap:10px;margin-top:12px">
          <button class="btn" id="emSubmit" style="flex:1;background:var(--ac);color:white;border:none;padding:12px;border-radius:8px;font-weight:600;cursor:pointer"></button>
          <button class="btn btn-g" id="emSkip" style="flex:1;padding:12px;border-radius:8px;cursor:pointer"></button>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Admin: active jobs monitor -->
<a href="#" id="monLink" onclick="openMonitor();return false" style="position:fixed;bottom:8px;right:12px;font-size:11px;color:rgba(150,150,150,.35);text-decoration:none;z-index:50;font-family:monospace;transition:color .3s" onmouseenter="this.style.color='rgba(150,150,150,.7)'" onmouseleave="this.style.color='rgba(150,150,150,.35)'">&bull;&bull;&bull;</a>
<div class="modal-overlay" id="monModal">
  <div class="modal" style="max-width:620px">
    <div class="modal-head">
      <span id="monTitle">Active Jobs</span>
      <button class="modal-close" id="monClose">&times;</button>
    </div>
    <div class="modal-body" id="monBody" style="min-height:80px">
      <div style="text-align:center;padding:20px;color:#999">Loading...</div>
    </div>
  </div>
</div>

<script>
// ═══════════════════ i18n ═══════════════════
const L={
it:{subtitle:"Converti i tuoi EPUB in audiolibri con voci neurali di alta qualit\\u00e0",disclaimer:"\\u26a0\\ufe0f Questo strumento \\u00e8 destinato esclusivamente all'uso personale su file EPUB di cui si \\u00e8 in legittimo possesso. I file EPUB caricati e gli audio generati non vengono conservati dal sistema e sono eliminati automaticamente al termine della sessione.",s1_title:"Carica il file",upload_text:"Trascina qui il file EPUB o TXT, o clicca per selezionarlo",upload_ok:"File caricato \\u2014 clicca per cambiare",analyzing:"Analisi del file in corso...",s2_title:"Impostazioni audio",lbl_lang:"Lingua",lbl_voice:"Voce",voice_ph:"Seleziona prima la lingua",lbl_speed:"Velocit\\u00e0 di lettura",sp_vs:"Molto lenta (-30%)",sp_s:"Lenta (-20%)",sp_ss:"Leggermente lenta (-10%)",sp_n:"Normale",sp_sf:"Leggermente veloce (+10%)",sp_f:"Veloce (+20%)",sp_vf:"Molto veloce (+30%)",lbl_out:"Output",out_single:"📄 File unico",out_ch:"📁 Per capitoli",s3_title:"Anteprima e conferma",sum_ch:"Capitoli",sum_w:"Parole",sum_chr:"Caratteri",sum_d:"Durata stimata",col_ch:"Capitolo",col_w:"Parole",col_d:"Durata",btn_gen:"Genera audiolibro",s4_title:"Generazione in corso",st_blk:"Blocco",st_ch:"Capitolo",st_el:"Trascorso",st_rem:"Rimanente",st_sz:"Generati",st_spd:"Velocit\\u00e0",btn_dl:"Scarica audiolibro",btn_new:"Converti un altro file",done_msg:"\\u2713 Audiolibro generato con successo!",done_t:"Completato \\u2713",starting:"Avvio...",by:"di",err_epub:"Seleziona un file .epub o .txt valido.",cps:"car/s",almost:"quasi...",btn_cancel:"Annulla generazione",cancelled_msg:"Generazione annullata.",dl_expired:"File non più disponibile. Riconverti il libro.",sel_selected:"selezionati",sel_all:"Seleziona tutti",sel_none:"Deseleziona tutti",sel_invert:"Inverti",sel_err_none:"Seleziona almeno un capitolo.",btn_dl_podcast:"Scarica podcast",podcast_hint:"Include anche la versione Podcast con feed RSS 2.0",btn_free_books:"Scarica libri gratuiti",modal_free_title:"Libri gratuiti online",podcast_url_prompt:"Inserisci l'URL della cartella dove saranno pubblicati i file MP3 degli episodi:",email_title:"Generazione lunga in corso",email_desc:"La generazione richieder\\u00e0 ancora diversi minuti. Puoi inserire la tua email per ricevere un avviso al termine e chiudere il browser.",email_dl_type:"Come vuoi scaricare il risultato?",email_dl_audio:"Solo file audio",email_dl_podcast:"Podcast (con RSS)",email_base_url:"URL base pubblicazione podcast:",email_placeholder:"La tua email",email_btn:"Avvisami al termine",email_skip:"No grazie, aspetto qui",email_ok:"Email registrata! Riceverai un messaggio al termine della generazione. Puoi chiudere questa pagina.",email_invalid:"Inserisci un indirizzo email valido.",email_unavail:"Il servizio email non \\u00e8 configurato su questo server.",btn_podcast_guide:"Guida podcast",modal_guide_title:"Come pubblicare il tuo podcast"},

en:{subtitle:"Convert your EPUBs into audiobooks with high-quality neural voices",disclaimer:"\\u26a0\\ufe0f This tool is intended solely for personal use on EPUB files you legitimately own. Uploaded EPUB files and generated audio are not stored by the system and are automatically deleted at the end of the session.",s1_title:"Upload file",upload_text:"Drag your EPUB or TXT file here, or click to select",upload_ok:"File loaded \\u2014 click to change",analyzing:"Analyzing file...",s2_title:"Audio settings",lbl_lang:"Language",lbl_voice:"Voice",voice_ph:"Select a language first",lbl_speed:"Reading speed",sp_vs:"Very slow (-30%)",sp_s:"Slow (-20%)",sp_ss:"Slightly slow (-10%)",sp_n:"Normal",sp_sf:"Slightly fast (+10%)",sp_f:"Fast (+20%)",sp_vf:"Very fast (+30%)",lbl_out:"Output",out_single:"📄 Single file",out_ch:"📁 By chapters",s3_title:"Preview and confirm",sum_ch:"Chapters",sum_w:"Words",sum_chr:"Characters",sum_d:"Estimated duration",col_ch:"Chapter",col_w:"Words",col_d:"Duration",btn_gen:"Generate audiobook",s4_title:"Generating",st_blk:"Block",st_ch:"Chapter",st_el:"Elapsed",st_rem:"Remaining",st_sz:"Generated",st_spd:"Speed",btn_dl:"Download audiobook",btn_new:"Convert another file",done_msg:"\\u2713 Audiobook generated successfully!",done_t:"Completed \\u2713",starting:"Starting...",by:"by",err_epub:"Please select a valid .epub or .txt file.",cps:"chars/s",almost:"almost...",btn_cancel:"Cancel generation",cancelled_msg:"Generation cancelled.",dl_expired:"File no longer available. Please reconvert the book.",sel_selected:"selected",sel_all:"Select all",sel_none:"Deselect all",sel_invert:"Invert",sel_err_none:"Select at least one chapter.",btn_dl_podcast:"Download podcast",podcast_hint:"Also includes Podcast version with RSS 2.0 feed",btn_free_books:"Download free books",modal_free_title:"Free books online",podcast_url_prompt:"Enter the base URL of the folder where episode MP3 files will be hosted:",email_title:"Long generation in progress",email_desc:"Generation will take several more minutes. You can enter your email to be notified when it\u2019s done and close the browser.",email_dl_type:"How do you want to download the result?",email_dl_audio:"Audio files only",email_dl_podcast:"Podcast (with RSS)",email_base_url:"Podcast base URL:",email_placeholder:"Your email",email_btn:"Notify me when done",email_skip:"No thanks, I'll wait",email_ok:"Email registered! You'll receive a message when generation is complete. You can close this page.",email_invalid:"Please enter a valid email address.",email_unavail:"Email service is not configured on this server.",btn_podcast_guide:"Podcast guide",modal_guide_title:"How to publish your podcast"},

fr:{subtitle:"Convertissez vos EPUB en livres audio avec des voix neuronales",disclaimer:"\\u26a0\\ufe0f Cet outil est destin\\u00e9 exclusivement \\u00e0 un usage personnel sur des fichiers EPUB dont vous \\u00eates l\\u00e9gitimement propri\\u00e9taire. Les fichiers EPUB et les fichiers audio g\\u00e9n\\u00e9r\\u00e9s ne sont pas conserv\\u00e9s par le syst\\u00e8me et sont automatiquement supprim\\u00e9s \\u00e0 la fin de la session.",s1_title:"Charger le fichier",upload_text:"Glissez votre EPUB ou TXT ici, ou cliquez pour s\\u00e9lectionner",upload_ok:"Fichier charg\\u00e9 \\u2014 cliquez pour changer",analyzing:"Analyse du fichier...",s2_title:"Param\\u00e8tres audio",lbl_lang:"Langue",lbl_voice:"Voix",voice_ph:"S\\u00e9lectionnez d'abord la langue",lbl_speed:"Vitesse de lecture",sp_vs:"Tr\\u00e8s lente (-30%)",sp_s:"Lente (-20%)",sp_ss:"L\\u00e9g\\u00e8rement lente (-10%)",sp_n:"Normale",sp_sf:"L\\u00e9g\\u00e8rement rapide (+10%)",sp_f:"Rapide (+20%)",sp_vf:"Tr\\u00e8s rapide (+30%)",lbl_out:"Sortie",out_single:"📄 Fichier unique",out_ch:"📁 Par chapitres",s3_title:"Aper\\u00e7u et confirmation",sum_ch:"Chapitres",sum_w:"Mots",sum_chr:"Caract\\u00e8res",sum_d:"Dur\\u00e9e estim\\u00e9e",col_ch:"Chapitre",col_w:"Mots",col_d:"Dur\\u00e9e",btn_gen:"G\\u00e9n\\u00e9rer le livre audio",s4_title:"G\\u00e9n\\u00e9ration en cours",st_blk:"Bloc",st_ch:"Chapitre",st_el:"\\u00c9coul\\u00e9",st_rem:"Restant",st_sz:"G\\u00e9n\\u00e9r\\u00e9s",st_spd:"Vitesse",btn_dl:"T\\u00e9l\\u00e9charger",btn_new:"Convertir un autre fichier",done_msg:"\\u2713 Livre audio g\\u00e9n\\u00e9r\\u00e9 !",done_t:"Termin\\u00e9 \\u2713",starting:"D\\u00e9marrage...",by:"de",err_epub:"Veuillez choisir un fichier .epub ou .txt.",cps:"car/s",almost:"presque...",btn_cancel:"Annuler la g\u00e9n\u00e9ration",cancelled_msg:"G\u00e9n\u00e9ration annul\u00e9e.",dl_expired:"Fichier indisponible. Reconvertissez le livre.",sel_selected:"s\\u00e9lectionn\\u00e9s",sel_all:"Tout s\\u00e9lectionner",sel_none:"Tout d\\u00e9s\\u00e9lectionner",sel_invert:"Inverser",sel_err_none:"S\\u00e9lectionnez au moins un chapitre.",btn_dl_podcast:"T\\u00e9l\\u00e9charger podcast",podcast_hint:"Inclut \\u00e9galement la version Podcast avec flux RSS 2.0",btn_free_books:"Livres gratuits",modal_free_title:"Livres gratuits en ligne",podcast_url_prompt:"Entrez l'URL du dossier o\\u00f9 les fichiers MP3 des \\u00e9pisodes seront h\\u00e9berg\\u00e9s :",email_title:"G\u00e9n\u00e9ration longue en cours",email_desc:"La g\u00e9n\u00e9ration prendra encore plusieurs minutes. Vous pouvez saisir votre email pour \u00eatre averti \u00e0 la fin et fermer le navigateur.",email_dl_type:"Comment souhaitez-vous t\u00e9l\u00e9charger le r\u00e9sultat ?",email_dl_audio:"Fichiers audio uniquement",email_dl_podcast:"Podcast (avec RSS)",email_base_url:"URL de base du podcast :",email_placeholder:"Votre email",email_btn:"Pr\u00e9venez-moi",email_skip:"Non merci, j'attends",email_ok:"Email enregistr\u00e9 ! Vous recevrez un message \u00e0 la fin de la g\u00e9n\u00e9ration. Vous pouvez fermer cette page.",email_invalid:"Veuillez saisir une adresse email valide.",email_unavail:"Le service email n'est pas configur\u00e9 sur ce serveur.",btn_podcast_guide:"Guide podcast",modal_guide_title:"Comment publier votre podcast"},

es:{subtitle:"Convierte tus EPUB en audiolibros con voces neuronales de alta calidad",disclaimer:"\\u26a0\\ufe0f Esta herramienta est\\u00e1 destinada exclusivamente al uso personal con archivos EPUB de los que se posee leg\\u00edtimamente. Los archivos EPUB cargados y el audio generado no son almacenados por el sistema y se eliminan autom\\u00e1ticamente al finalizar la sesi\\u00f3n.",s1_title:"Cargar archivo",upload_text:"Arrastra tu EPUB o TXT aqu\\u00ed o haz clic para seleccionar",upload_ok:"Archivo cargado \\u2014 clic para cambiar",analyzing:"Analizando archivo...",s2_title:"Ajustes de audio",lbl_lang:"Idioma",lbl_voice:"Voz",voice_ph:"Selecciona primero el idioma",lbl_speed:"Velocidad de lectura",sp_vs:"Muy lenta (-30%)",sp_s:"Lenta (-20%)",sp_ss:"Ligeramente lenta (-10%)",sp_n:"Normal",sp_sf:"Ligeramente r\\u00e1pida (+10%)",sp_f:"R\\u00e1pida (+20%)",sp_vf:"Muy r\\u00e1pida (+30%)",lbl_out:"Salida",out_single:"📄 Archivo \\u00fanico",out_ch:"📁 Por cap\\u00edtulos",s3_title:"Vista previa y confirmaci\\u00f3n",sum_ch:"Cap\\u00edtulos",sum_w:"Palabras",sum_chr:"Caracteres",sum_d:"Duraci\\u00f3n estimada",col_ch:"Cap\\u00edtulo",col_w:"Palabras",col_d:"Duraci\\u00f3n",btn_gen:"Generar audiolibro",s4_title:"Generando",st_blk:"Bloque",st_ch:"Cap\\u00edtulo",st_el:"Transcurrido",st_rem:"Restante",st_sz:"Generados",st_spd:"Velocidad",btn_dl:"Descargar audiolibro",btn_new:"Convertir otro archivo",done_msg:"\\u2713 \\u00a1Audiolibro generado!",done_t:"Completado \\u2713",starting:"Iniciando...",by:"de",err_epub:"Selecciona un archivo .epub o .txt v\\u00e1lido.",cps:"car/s",almost:"casi...",btn_cancel:"Cancelar generaci\u00f3n",cancelled_msg:"Generaci\u00f3n cancelada.",dl_expired:"Archivo no disponible. Reconvierta el libro.",sel_selected:"seleccionados",sel_all:"Seleccionar todos",sel_none:"Deseleccionar todos",sel_invert:"Invertir",sel_err_none:"Selecciona al menos un cap\\u00edtulo.",btn_dl_podcast:"Descargar podcast",podcast_hint:"Incluye tambi\\u00e9n la versi\\u00f3n Podcast con feed RSS 2.0",btn_free_books:"Libros gratuitos",modal_free_title:"Libros gratuitos en l\\u00ednea",podcast_url_prompt:"Introduce la URL de la carpeta donde estar\\u00e1n alojados los archivos MP3 de los episodios:",email_title:"Generaci\u00f3n larga en curso",email_desc:"La generaci\u00f3n tardar\u00e1 varios minutos m\u00e1s. Puedes introducir tu email para recibir un aviso al finalizar y cerrar el navegador.",email_dl_type:"\u00bfC\u00f3mo deseas descargar el resultado?",email_dl_audio:"Solo archivos de audio",email_dl_podcast:"Podcast (con RSS)",email_base_url:"URL base del podcast:",email_placeholder:"Tu email",email_btn:"Av\u00edsame al terminar",email_skip:"No gracias, espero aqu\u00ed",email_ok:"\u00a1Email registrado! Recibir\u00e1s un mensaje al finalizar. Puedes cerrar esta p\u00e1gina.",email_invalid:"Introduce una direcci\u00f3n de email v\u00e1lida.",email_unavail:"El servicio de email no est\u00e1 configurado en este servidor.",btn_podcast_guide:"Gu\u00eda podcast",modal_guide_title:"C\u00f3mo publicar tu podcast"},

de:{subtitle:"Konvertieren Sie EPUBs in H\\u00f6rb\\u00fccher mit neuronalen Stimmen",disclaimer:"\\u26a0\\ufe0f Dieses Tool ist ausschlie\\u00dflich f\\u00fcr den pers\\u00f6nlichen Gebrauch mit EPUB-Dateien bestimmt, die Sie rechtm\\u00e4\\u00dfig besitzen. Hochgeladene EPUB-Dateien und erzeugte Audiodateien werden vom System nicht gespeichert und am Ende der Sitzung automatisch gel\\u00f6scht.",s1_title:"Datei hochladen",upload_text:"EPUB oder TXT hierher ziehen, oder klicken",upload_ok:"Datei geladen \\u2014 klicken zum \\u00c4ndern",analyzing:"Datei wird analysiert...",s2_title:"Audio-Einstellungen",lbl_lang:"Sprache",lbl_voice:"Stimme",voice_ph:"Zuerst Sprache w\\u00e4hlen",lbl_speed:"Lesegeschwindigkeit",sp_vs:"Sehr langsam (-30%)",sp_s:"Langsam (-20%)",sp_ss:"Etwas langsam (-10%)",sp_n:"Normal",sp_sf:"Etwas schnell (+10%)",sp_f:"Schnell (+20%)",sp_vf:"Sehr schnell (+30%)",lbl_out:"Ausgabe",out_single:"📄 Einzelne Datei",out_ch:"📁 Nach Kapiteln",s3_title:"Vorschau und Best\\u00e4tigung",sum_ch:"Kapitel",sum_w:"W\\u00f6rter",sum_chr:"Zeichen",sum_d:"Gesch\\u00e4tzte Dauer",col_ch:"Kapitel",col_w:"W\\u00f6rter",col_d:"Dauer",btn_gen:"H\\u00f6rbuch generieren",s4_title:"Wird generiert",st_blk:"Block",st_ch:"Kapitel",st_el:"Vergangen",st_rem:"Verbleibend",st_sz:"Erzeugt",st_spd:"Tempo",btn_dl:"H\\u00f6rbuch herunterladen",btn_new:"Weitere Datei",done_msg:"\\u2713 H\\u00f6rbuch generiert!",done_t:"Abgeschlossen \\u2713",starting:"Starten...",by:"von",err_epub:"Bitte eine .epub- oder .txt-Datei w\\u00e4hlen.",cps:"Zch/s",almost:"fast...",btn_cancel:"Generierung abbrechen",cancelled_msg:"Generierung abgebrochen.",dl_expired:"Datei nicht mehr verf\u00fcgbar. Bitte erneut konvertieren.",sel_selected:"ausgew\\u00e4hlt",sel_all:"Alle ausw\\u00e4hlen",sel_none:"Alle abw\\u00e4hlen",sel_invert:"Umkehren",sel_err_none:"W\\u00e4hlen Sie mindestens ein Kapitel.",btn_dl_podcast:"Podcast herunterladen",podcast_hint:"Enth\\u00e4lt auch die Podcast-Version mit RSS 2.0 Feed",btn_free_books:"Kostenlose B\\u00fccher",modal_free_title:"Kostenlose B\\u00fccher online",podcast_url_prompt:"Geben Sie die URL des Ordners ein, in dem die MP3-Dateien der Episoden gehostet werden:",email_title:"Lange Generierung l\u00e4uft",email_desc:"Die Generierung wird noch einige Minuten dauern. Sie k\u00f6nnen Ihre E-Mail eingeben, um benachrichtigt zu werden, und den Browser schlie\u00dfen.",email_dl_type:"Wie m\u00f6chten Sie das Ergebnis herunterladen?",email_dl_audio:"Nur Audiodateien",email_dl_podcast:"Podcast (mit RSS)",email_base_url:"Podcast-Basis-URL:",email_placeholder:"Ihre E-Mail",email_btn:"Benachrichtigen",email_skip:"Nein danke, ich warte",email_ok:"E-Mail registriert! Sie erhalten eine Nachricht nach Abschluss. Sie k\u00f6nnen diese Seite schlie\u00dfen.",email_invalid:"Bitte geben Sie eine g\u00fcltige E-Mail-Adresse ein.",email_unavail:"Der E-Mail-Dienst ist auf diesem Server nicht konfiguriert.",btn_podcast_guide:"Podcast-Anleitung",modal_guide_title:"So ver\u00f6ffentlichen Sie Ihren Podcast"},

zh:{subtitle:"\\u4f7f\\u7528\\u9ad8\\u54c1\\u8d28\\u795e\\u7ecf\\u8bed\\u97f3\\u5c06EPUB\\u8f6c\\u6362\\u4e3a\\u6709\\u58f0\\u8bfb\\u7269",disclaimer:"\\u26a0\\ufe0f \\u672c\\u5de5\\u5177\\u4ec5\\u4f9b\\u4e2a\\u4eba\\u4f7f\\u7528\\uff0c\\u9002\\u7528\\u4e8e\\u60a8\\u5408\\u6cd5\\u62e5\\u6709\\u7684EPUB\\u6587\\u4ef6\\u3002\\u4e0a\\u4f20\\u7684EPUB\\u6587\\u4ef6\\u548c\\u751f\\u6210\\u7684\\u97f3\\u9891\\u4e0d\\u4f1a\\u88ab\\u7cfb\\u7edf\\u4fdd\\u5b58\\uff0c\\u5e76\\u5728\\u4f1a\\u8bdd\\u7ed3\\u675f\\u540e\\u81ea\\u52a8\\u5220\\u9664\\u3002",s1_title:"\\u4e0a\\u4f20\\u6587\\u4ef6",upload_text:"\\u62d6\\u62fdEPUB\\u6216TXT\\u6587\\u4ef6\\uff0c\\u6216\\u70b9\\u51fb\\u9009\\u62e9",upload_ok:"\\u6587\\u4ef6\\u5df2\\u52a0\\u8f7d \\u2014 \\u70b9\\u51fb\\u66f4\\u6362",analyzing:"\\u6b63\\u5728\\u5206\\u6790EPUB...",s2_title:"\\u97f3\\u9891\\u8bbe\\u7f6e",lbl_lang:"\\u8bed\\u8a00",lbl_voice:"\\u8bed\\u97f3",voice_ph:"\\u8bf7\\u5148\\u9009\\u62e9\\u8bed\\u8a00",lbl_speed:"\\u6717\\u8bfb\\u901f\\u5ea6",sp_vs:"\\u975e\\u5e38\\u6162 (-30%)",sp_s:"\\u6162 (-20%)",sp_ss:"\\u7a0d\\u6162 (-10%)",sp_n:"\\u6b63\\u5e38",sp_sf:"\\u7a0d\\u5feb (+10%)",sp_f:"\\u5feb (+20%)",sp_vf:"\\u975e\\u5e38\\u5feb (+30%)",lbl_out:"\\u8f93\\u51fa",out_single:"📄 \\u5355\\u4e2a\\u6587\\u4ef6",out_ch:"📁 \\u6309\\u7ae0\\u8282",s3_title:"\\u9884\\u89c8\\u548c\\u786e\\u8ba4",sum_ch:"\\u7ae0\\u8282",sum_w:"\\u5b57\\u6570",sum_chr:"\\u5b57\\u7b26",sum_d:"\\u9884\\u8ba1\\u65f6\\u957f",col_ch:"\\u7ae0\\u8282",col_w:"\\u5b57\\u6570",col_d:"\\u65f6\\u957f",btn_gen:"\\u751f\\u6210\\u6709\\u58f0\\u8bfb\\u7269",s4_title:"\\u6b63\\u5728\\u751f\\u6210",st_blk:"\\u5757",st_ch:"\\u7ae0\\u8282",st_el:"\\u5df2\\u7528\\u65f6",st_rem:"\\u5269\\u4f59",st_sz:"\\u5df2\\u751f\\u6210",st_spd:"\\u901f\\u5ea6",btn_dl:"\\u4e0b\\u8f7d\\u6709\\u58f0\\u8bfb\\u7269",btn_new:"\\u8f6c\\u6362\\u5176\\u4ed6\\u6587\\u4ef6",done_msg:"\\u2713 \\u6709\\u58f0\\u8bfb\\u7269\\u751f\\u6210\\u6210\\u529f\\uff01",done_t:"\\u5df2\\u5b8c\\u6210 \\u2713",starting:"\\u542f\\u52a8\\u4e2d...",by:"\\u4f5c\\u8005",err_epub:"\\u8bf7\\u9009\\u62e9\\u6709\\u6548\\u7684.epub\\u6587\\u4ef6",cps:"\\u5b57/\\u79d2",almost:"\\u5373\\u5c06...",btn_cancel:"\\u53d6\\u6d88\\u751f\\u6210",cancelled_msg:"\\u751f\\u6210\\u5df2\\u53d6\\u6d88\\u3002",dl_expired:"\\u6587\\u4ef6\\u5df2\\u4e0d\\u53ef\\u7528\\u3002\\u8bf7\\u91cd\\u65b0\\u8f6c\\u6362\\u3002",sel_selected:"\\u5df2\\u9009\\u62e9",sel_all:"\\u5168\\u9009",sel_none:"\\u5168\\u4e0d\\u9009",sel_invert:"\\u53cd\\u9009",sel_err_none:"\\u8bf7\\u81f3\\u5c11\\u9009\\u62e9\\u4e00\\u4e2a\\u7ae0\\u8282\\u3002",btn_dl_podcast:"\\u4e0b\\u8f7d\\u64ad\\u5ba2",podcast_hint:"\\u8fd8\\u5305\\u542b\\u5e26RSS 2.0\\u8ba2\\u9605\\u6e90\\u7684\\u64ad\\u5ba2\\u7248\\u672c",btn_free_books:"\\u514d\\u8d39\\u4e66\\u7c4d",modal_free_title:"\\u5728\\u7ebf\\u514d\\u8d39\\u4e66\\u7c4d",podcast_url_prompt:"\\u8bf7\\u8f93\\u5165\\u5b58\\u653eMP3\\u6587\\u4ef6\\u7684\\u6587\\u4ef6\\u5939URL\\uff1a",email_title:"\\u751f\\u6210\\u65f6\\u95f4\\u8f83\\u957f",email_desc:"\\u751f\\u6210\\u8fd8\\u9700\\u8981\\u51e0\\u5206\\u949f\\u3002\\u8f93\\u5165\\u90ae\\u7bb1\\uff0c\\u5b8c\\u6210\\u540e\\u6536\\u5230\\u4e0b\\u8f7d\\u94fe\\u63a5\\uff0c\\u53ef\\u5173\\u95ed\\u6d4f\\u89c8\\u5668\\u3002",email_dl_type:"\\u60a8\\u5e0c\\u671b\\u5982\\u4f55\\u4e0b\\u8f7d\\u7ed3\\u679c\\uff1f",email_dl_audio:"\\u4ec5\\u97f3\\u9891\\u6587\\u4ef6",email_dl_podcast:"\\u64ad\\u5ba2\\uff08\\u542bRSS\\uff09",email_base_url:"\\u64ad\\u5ba2\\u53d1\\u5e03\\u57fa\\u7840URL\\uff1a",email_placeholder:"\\u60a8\\u7684\\u7535\\u5b50\\u90ae\\u4ef6",email_btn:"\\u5b8c\\u6210\\u540e\\u901a\\u77e5\\u6211",email_skip:"\\u4e0d\\u7528\\u4e86\\uff0c\\u6211\\u5728\\u8fd9\\u91cc\\u7b49",email_ok:"\\u90ae\\u7bb1\\u5df2\\u6ce8\\u518c\\uff01\\u751f\\u6210\\u5b8c\\u6210\\u540e\\u60a8\\u5c06\\u6536\\u5230\\u901a\\u77e5\\u3002\\u53ef\\u4ee5\\u5173\\u95ed\\u6b64\\u9875\\u9762\\u3002",email_invalid:"\\u8bf7\\u8f93\\u5165\\u6709\\u6548\\u7684\\u7535\\u5b50\\u90ae\\u4ef6\\u5730\\u5740\\u3002",email_unavail:"\\u670d\\u52a1\\u5668\\u672a\\u914d\\u7f6e\\u90ae\\u4ef6\\u670d\\u52a1\\u3002",btn_podcast_guide:"\\u64ad\\u5ba2\\u6307\\u5357",modal_guide_title:"\\u5982\\u4f55\\u53d1\\u5e03\\u4f60\\u7684\\u64ad\\u5ba2"}

};

// ═══════════════════ FREE BOOKS SITES ═══════════════════
const FB_SITES=[
{id:"gutenberg",name:"Project Gutenberg",url:"https://www.gutenberg.org",icon:"\\ud83d\\udcda",desc:{
it:"La pi\\u00f9 grande raccolta di ebook gratuiti al mondo. Oltre 70.000 libri con diritti d'autore scaduti, disponibili in EPUB, Kindle e testo. Classici della letteratura universale.",
en:"The world's largest free ebook collection. Over 70,000 public domain books in EPUB, Kindle, and plain text. Classics of world literature.",
fr:"La plus grande collection d'ebooks gratuits au monde. Plus de 70 000 livres du domaine public en EPUB, Kindle et texte. Classiques de la litt\\u00e9rature mondiale.",
es:"La mayor colecci\\u00f3n de ebooks gratuitos del mundo. M\\u00e1s de 70.000 libros de dominio p\\u00fablico en EPUB, Kindle y texto. Cl\\u00e1sicos de la literatura universal.",
de:"Die gr\\u00f6\\u00dfte Sammlung kostenloser E-Books weltweit. \\u00dcber 70.000 gemeinfreie B\\u00fccher in EPUB, Kindle und Text. Klassiker der Weltliteratur.",
zh:"\\u5168\\u7403\\u6700\\u5927\\u7684\\u514d\\u8d39\\u7535\\u5b50\\u4e66\\u9986\\u3002\\u8d85\\u8fc770,000\\u672c\\u516c\\u7248\\u4e66\\u7c4d\\uff0c\\u63d0\\u4f9bEPUB\\u3001Kindle\\u548c\\u7eaf\\u6587\\u672c\\u683c\\u5f0f\\u3002\\u4e16\\u754c\\u6587\\u5b66\\u7ecf\\u5178\\u3002"}},
{id:"standard",name:"Standard Ebooks",url:"https://standardebooks.org",icon:"\\u2b50",desc:{
it:"Edizioni curate e ben formattate di classici del pubblico dominio. EPUB di altissima qualit\\u00e0 con copertine originali, tipografia moderna e metadati accurati.",
en:"Carefully curated, beautifully formatted editions of public domain classics. High-quality EPUBs with original covers, modern typography, and accurate metadata.",
fr:"\\u00c9ditions soign\\u00e9es et magnifiquement format\\u00e9es de classiques du domaine public. EPUB de haute qualit\\u00e9 avec couvertures originales et typographie moderne.",
es:"Ediciones cuidadas y bellamente formateadas de cl\\u00e1sicos de dominio p\\u00fablico. EPUB de alta calidad con portadas originales y tipograf\\u00eda moderna.",
de:"Sorgf\\u00e4ltig kuratierte, sch\\u00f6n formatierte Ausgaben gemeinfreier Klassiker. Hochwertige EPUBs mit Originalcovern und moderner Typografie.",
zh:"\\u7cbe\\u5fc3\\u7f16\\u8f91\\u3001\\u7f8e\\u89c2\\u6392\\u7248\\u7684\\u516c\\u7248\\u7ecf\\u5178\\u4f5c\\u54c1\\u3002\\u9ad8\\u8d28\\u91cfEPUB\\uff0c\\u5e26\\u539f\\u521b\\u5c01\\u9762\\u548c\\u73b0\\u4ee3\\u6392\\u7248\\u3002"}},
{id:"archive",name:"Internet Archive",url:"https://archive.org/details/texts",icon:"\\ud83c\\udfe6",desc:{
it:"Biblioteca digitale immensa con milioni di testi, libri, audiolibri e riviste. Include il servizio di prestito digitale Open Library e collezioni storiche uniche.",
en:"Massive digital library with millions of texts, books, audiobooks, and magazines. Includes the Open Library digital lending service and unique historical collections.",
fr:"Immense biblioth\\u00e8que num\\u00e9rique avec des millions de textes, livres et magazines. Inclut le service de pr\\u00eat num\\u00e9rique Open Library et des collections historiques.",
es:"Enorme biblioteca digital con millones de textos, libros y revistas. Incluye el servicio de pr\\u00e9stamo digital Open Library y colecciones hist\\u00f3ricas \\u00fanicas.",
de:"Riesige digitale Bibliothek mit Millionen von Texten, B\\u00fcchern und Zeitschriften. Enth\\u00e4lt den digitalen Ausleihdienst Open Library und historische Sammlungen.",
zh:"\\u6d77\\u91cf\\u6570\\u5b57\\u56fe\\u4e66\\u9986\\uff0c\\u62e5\\u6709\\u6570\\u767e\\u4e07\\u518c\\u4e66\\u7c4d\\u3001\\u97f3\\u9891\\u548c\\u6742\\u5fd7\\u3002\\u5305\\u542bOpen Library\\u6570\\u5b57\\u501f\\u9605\\u670d\\u52a1\\u548c\\u72ec\\u7279\\u7684\\u5386\\u53f2\\u85cf\\u54c1\\u3002"}},
{id:"manybooks",name:"ManyBooks",url:"https://manybooks.net",icon:"\\ud83d\\udcd6",desc:{
it:"Oltre 50.000 ebook gratuiti in vari formati. Interfaccia moderna con categorie, recensioni e consigli di lettura. Ottima selezione di classici e opere indipendenti.",
en:"Over 50,000 free ebooks in various formats. Modern interface with categories, reviews, and reading recommendations. Great selection of classics and indie works.",
fr:"Plus de 50 000 ebooks gratuits en divers formats. Interface moderne avec cat\\u00e9gories, critiques et recommandations. Excellente s\\u00e9lection de classiques.",
es:"M\\u00e1s de 50.000 ebooks gratuitos en varios formatos. Interfaz moderna con categor\\u00edas, rese\\u00f1as y recomendaciones. Gran selecci\\u00f3n de cl\\u00e1sicos e independientes.",
de:"\\u00dcber 50.000 kostenlose E-Books in verschiedenen Formaten. Moderne Oberfl\\u00e4che mit Kategorien, Rezensionen und Leseempfehlungen. Klassiker und Indie-Werke.",
zh:"\\u8d85\\u8fc750,000\\u672c\\u514d\\u8d39\\u7535\\u5b50\\u4e66\\uff0c\\u591a\\u79cd\\u683c\\u5f0f\\u3002\\u73b0\\u4ee3\\u754c\\u9762\\uff0c\\u5e26\\u5206\\u7c7b\\u3001\\u8bc4\\u8bba\\u548c\\u9605\\u8bfb\\u63a8\\u8350\\u3002"}},
{id:"feedbooks",name:"Feedbooks",url:"https://www.feedbooks.com/publicdomain",icon:"\\ud83c\\udf10",desc:{
it:"Catalogo elegante di ebook del pubblico dominio con download diretto in EPUB. Sezione dedicata alla narrativa, alla saggistica e ai classici, con interfaccia pulita e veloce.",
en:"Elegant catalog of public domain ebooks with direct EPUB download. Dedicated sections for fiction, non-fiction, and classics, with a clean and fast interface.",
fr:"Catalogue \\u00e9l\\u00e9gant d'ebooks du domaine public avec t\\u00e9l\\u00e9chargement EPUB direct. Sections fiction, non-fiction et classiques, interface rapide.",
es:"Cat\\u00e1logo elegante de ebooks de dominio p\\u00fablico con descarga directa en EPUB. Secciones de ficci\\u00f3n, no ficci\\u00f3n y cl\\u00e1sicos, interfaz limpia.",
de:"Eleganter Katalog gemeinfreier E-Books mit direktem EPUB-Download. Bereiche f\\u00fcr Belletristik, Sachb\\u00fccher und Klassiker, schnelle Oberfl\\u00e4che.",
zh:"\\u7cbe\\u7f8e\\u7684\\u516c\\u7248\\u7535\\u5b50\\u4e66\\u76ee\\u5f55\\uff0c\\u652f\\u6301\\u76f4\\u63a5\\u4e0b\\u8f7dEPUB\\u3002\\u5206\\u4e3a\\u5c0f\\u8bf4\\u3001\\u975e\\u865a\\u6784\\u548c\\u7ecf\\u5178\\u4e09\\u4e2a\\u677f\\u5757\\u3002"}},
{id:"google",name:"Google Books",url:"https://books.google.com/books?&as_ebook=on&as_brr=1",icon:"G",desc:{
it:"Milioni di libri digitalizzati da Google. Filtra per 'Ebook gratuiti' per trovare opere con diritti scaduti. Disponibili in EPUB e PDF per il download diretto.",
en:"Millions of books digitized by Google. Filter by 'Free Google eBooks' to find public domain works. Available in EPUB and PDF for direct download.",
fr:"Des millions de livres num\\u00e9ris\\u00e9s par Google. Filtrez par 'Ebooks gratuits' pour le domaine public. Disponibles en EPUB et PDF.",
es:"Millones de libros digitalizados por Google. Filtra por 'Ebooks gratuitos' para encontrar obras de dominio p\\u00fablico. Disponibles en EPUB y PDF.",
de:"Millionen von Google digitalisierte B\\u00fccher. Nach 'Kostenlose E-Books' filtern f\\u00fcr gemeinfreie Werke. Verf\\u00fcgbar als EPUB und PDF.",
zh:"\\u8c37\\u6b4c\\u6570\\u5b57\\u5316\\u7684\\u6570\\u767e\\u4e07\\u518c\\u4e66\\u7c4d\\u3002\\u7b5b\\u9009\\u201c\\u514d\\u8d39\\u7535\\u5b50\\u4e66\\u201d\\u67e5\\u627e\\u516c\\u7248\\u4f5c\\u54c1\\u3002\\u652f\\u6301EPUB\\u548cPDF\\u4e0b\\u8f7d\\u3002"}},
{id:"liberliber",name:"Liber Liber / Manuzio",url:"https://www.liberliber.it/online/opere/libri/",icon:"\\ud83c\\uddee\\ud83c\\uddf9",desc:{
it:"Il progetto italiano pi\\u00f9 importante per la diffusione di ebook gratuiti. Ampia raccolta di classici della letteratura italiana: Dante, Manzoni, Pirandello, Verga e molti altri.",
en:"Italy's most important free ebook project. Extensive collection of Italian literature classics: Dante, Manzoni, Pirandello, Verga and many others.",
fr:"Le projet italien le plus important pour les ebooks gratuits. Vaste collection de classiques italiens: Dante, Manzoni, Pirandello, Verga et bien d'autres.",
es:"El proyecto italiano m\\u00e1s importante de ebooks gratuitos. Amplia colecci\\u00f3n de cl\\u00e1sicos italianos: Dante, Manzoni, Pirandello, Verga y muchos m\\u00e1s.",
de:"Italiens wichtigstes Projekt f\\u00fcr kostenlose E-Books. Umfangreiche Sammlung italienischer Klassiker: Dante, Manzoni, Pirandello, Verga und viele mehr.",
zh:"\\u610f\\u5927\\u5229\\u6700\\u91cd\\u8981\\u7684\\u514d\\u8d39\\u7535\\u5b50\\u4e66\\u9879\\u76ee\\u3002\\u4e30\\u5bcc\\u7684\\u610f\\u5927\\u5229\\u6587\\u5b66\\u7ecf\\u5178\\u85cf\\u54c1\\uff1a\\u4f46\\u4e01\\u3001\\u66fc\\u4f50\\u5c3c\\u3001\\u76ae\\u5170\\u5fb7\\u5a04\\u7b49\\u3002"}},
{id:"openlibrary",name:"Open Library",url:"https://openlibrary.org/read",icon:"\\ud83c\\udfdb\\ufe0f",desc:{
it:"Catalogo aperto con milioni di libri. Prestito digitale gratuito di ebook moderni e classici. Parte dell'Internet Archive, richiede registrazione gratuita per il prestito.",
en:"Open catalog with millions of books. Free digital lending of modern and classic ebooks. Part of Internet Archive, requires free registration for borrowing.",
fr:"Catalogue ouvert avec des millions de livres. Pr\\u00eat num\\u00e9rique gratuit d'ebooks modernes et classiques. Inscription gratuite requise pour l'emprunt.",
es:"Cat\\u00e1logo abierto con millones de libros. Pr\\u00e9stamo digital gratuito de ebooks modernos y cl\\u00e1sicos. Requiere registro gratuito para el pr\\u00e9stamo.",
de:"Offener Katalog mit Millionen B\\u00fcchern. Kostenlose digitale Ausleihe moderner und klassischer E-Books. Kostenlose Registrierung f\\u00fcr Ausleihe erforderlich.",
zh:"\\u62e5\\u6709\\u6570\\u767e\\u4e07\\u518c\\u4e66\\u7c4d\\u7684\\u5f00\\u653e\\u76ee\\u5f55\\u3002\\u514d\\u8d39\\u6570\\u5b57\\u501f\\u9605\\u73b0\\u4ee3\\u548c\\u7ecf\\u5178\\u7535\\u5b50\\u4e66\\u3002\\u9700\\u514d\\u8d39\\u6ce8\\u518c\\u3002"}}
];

function buildFreeBooks(){
  const body=document.getElementById('fbBody');
  body.innerHTML='';
  FB_SITES.forEach(s=>{
    const card=document.createElement('div');card.className='site-card';
    card.innerHTML='<div class="site-icon">'+s.icon+'</div>'
      +'<div class="site-info"><div class="site-name"><a href="'+s.url+'" target="_blank" rel="noopener">'+s.name+' \\u2197</a></div>'
      +'<div class="site-desc">'+(s.desc[cl]||s.desc.en)+'</div></div>';
    body.appendChild(card);
  });
}
function openFreeBooks(){buildFreeBooks();document.getElementById('fbModal').classList.add('open')}
function closeFreeBooks(){document.getElementById('fbModal').classList.remove('open')}

// ═══════════════════ PODCAST GUIDE ═══════════════════
const PG_IMG_A='data:image/png;base64,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';
const PG_IMG_B='data:image/png;base64,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';
const PG={
it:{
 intro:'Audiobook Maker genera, oltre ai file audio, un <b>pacchetto podcast completo</b> con feed RSS 2.0. Per renderlo fruibile come podcast, i file vanno pubblicati su un server web accessibile da Internet. La soluzione ideale \u00e8 un <b>proprio sito web</b> o spazio hosting. In alternativa, per uso personale o per condividere con pochi amici, si pu\u00f2 usare una soluzione gratuita come <b>Netlify</b>, descritta in questa guida.',
 scope:'👤 <b>Uso consigliato:</b> questa soluzione \u00e8 pensata per uso personale o per condividere con amici e familiari. Netlify offre 100 GB/mese di banda gratuita \u2014 pi\u00f9 che sufficienti.',
 sections:[
  {icon:'🎧',title:'1. Genera l\u2019audiolibro per capitoli',body:'Nell\u2019app, carica il file EPUB, scegli lingua e voce, poi seleziona <b>📁 Per capitoli</b> nella sezione Output. Questo \u00e8 fondamentale: il podcast richiede un file MP3 per ogni episodio.'},
  {icon:'🌐',title:'2. Crea un account Netlify (gratuito)',body:'Vai su <b>app.netlify.com</b> e registrati con email o GitHub. Non serve carta di credito. Il piano gratuito include 100 GB di banda, 10 GB di storage e HTTPS automatico.'},
  {icon:'📦',title:'3. Scarica il pacchetto podcast',body:'Prima di scaricare, dovrai inserire l\u2019<b>URL Netlify</b> dove pubblicherai i file (es. <code>https://mio-libro.netlify.app/</code>). Questo URL viene incorporato nel feed RSS affinch\u00e9 le app podcast possano trovare gli episodi. Ci sono due modi per ottenere il pacchetto:<br><br><b>Opzione A \u2014 Attendi nella pagina:</b> a generazione completata, clicca <b>🎙️ Scarica podcast</b>. Ti verr\u00e0 chiesto l\u2019URL, poi il ZIP verr\u00e0 scaricato.<br><img src="__IMG_A__" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br><b>Opzione B \u2014 Notifica email:</b> per audiolibri lunghi, l\u2019app offre di avvisarti via email. Nella finestra di notifica, seleziona <b>Podcast (con RSS)</b>, inserisci l\u2019URL Netlify nel campo <b>URL base pubblicazione podcast</b>, poi la tua email. A generazione completata, riceverai un\u2019email con il link per scaricare lo ZIP.<br><img src="__IMG_B__" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br>Lo ZIP contiene: file MP3, feed RSS (XML), copertina e una pagina di presentazione (index.html).'},
  {icon:'📤',title:'4. Carica su Netlify (drag-and-drop)',body:'Nella dashboard Netlify, sezione <b>Sites</b>, trascina l\u2019intera cartella estratta dal ZIP nella zona tratteggiata. In pochi secondi il sito sar\u00e0 online. Poi rinominalo da <i>Site configuration \u2192 Change site name</i>.'},
  {icon:'\u2705',title:'5. Verifica',body:'Apri nel browser l\u2019URL del feed:<br><code>https://nome-scelto.netlify.app/nome_podcast.xml</code><br>Se vedi il contenuto XML, il podcast \u00e8 online e pronto!'},
 ],
 apps_title:'Importa nelle app podcast',
 apps:[
  {name:'Apple Podcasts',platform:'iOS / Mac',steps:'<b>iPhone:</b> Libreria \u2192 \u22EE \u2192 Aggiungi tramite URL \u2192 incolla URL del feed XML<br><b>Mac:</b> File \u2192 Segui uno show tramite URL'},
  {name:'Pocket Casts',platform:'Android / iOS / Web',steps:'Cerca \u2192 icona link (🔗) \u2192 incolla URL del feed \u2192 Iscriviti'},
  {name:'AntennaPod',platform:'Android',steps:'+ \u2192 Aggiungi feed RSS tramite URL \u2192 incolla URL'},
  {name:'Overcast',platform:'iOS',steps:'+ \u2192 Add URL \u2192 incolla URL del feed'},
  {name:'Podcast Addict',platform:'Android',steps:'+ \u2192 Feed RSS \u2192 incolla URL'},
 ],
 spotify_note:'\u26A0\uFE0F <b>Spotify</b> non supporta l\u2019aggiunta di feed RSS privati. Usa una delle app sopra.',
 tips_title:'Consigli',
 tips:['<b>Condividi:</b> invia l\u2019URL del feed XML ad amici \u2014 non serve che abbiano Netlify.','<b>Aggiorna:</b> ricarica i file su Netlify per sostituire la versione precedente.','<b>Pi\u00f9 libri:</b> crea un sito Netlify diverso per ogni audiolibro.','<b>Limiti:</b> 10 GB di storage (~12 audiolibri). Rimuovi quelli gi\u00e0 ascoltati per fare spazio.'],
 benefits_title:'Perch\u00e9 ascoltare come podcast?',
 benefits:['Segnaposto automatico \u2014 riprendi da dove avevi lasciato','Ordine episodi e passaggio automatico al successivo','Copertina, titoli e metadati visibili nell\u2019app','Velocit\u00e0 regolabile (1.5\u00d7, 2\u00d7\u2026) e timer spegnimento','Streaming senza scaricare tutti i file'],
},
en:{
 intro:'Audiobook Maker generates, alongside audio files, a <b>complete podcast package</b> with an RSS 2.0 feed. To make it available as a podcast, the files need to be published on a web server accessible from the Internet. The ideal solution is your <b>own website</b> or hosting space. Alternatively, for personal use or sharing with a few friends, you can use a free solution like <b>Netlify</b>, described in this guide.',
 scope:'👤 <b>Recommended use:</b> this solution is designed for personal use or sharing with friends and family. Netlify offers 100 GB/month of free bandwidth \u2014 more than enough.',
 sections:[
  {icon:'🎧',title:'1. Generate audiobook by chapters',body:'In the app, upload your EPUB file, choose language and voice, then select <b>📁 By chapters</b> in the Output section. This is essential: podcasts need one MP3 per episode.'},
  {icon:'🌐',title:'2. Create a free Netlify account',body:'Go to <b>app.netlify.com</b> and sign up with email or GitHub. No credit card needed. The free plan includes 100 GB bandwidth, 10 GB storage, and automatic HTTPS.'},
  {icon:'📦',title:'3. Download the podcast package',body:'Before downloading, you\u2019ll need to enter the <b>Netlify URL</b> where you plan to publish the files (e.g. <code>https://my-book.netlify.app/</code>). This URL is embedded into the RSS feed so podcast apps can find your episodes. There are two ways to get the package:<br><br><b>Option A \u2014 Wait on the page:</b> once generation completes, click <b>🎙️ Download podcast</b>. You\u2019ll be prompted for the URL, then the ZIP will download.<br><img src="__IMG_A__" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br><b>Option B \u2014 Email notification:</b> for long audiobooks, the app offers to notify you by email. In the notification dialog, select <b>Podcast (with RSS)</b>, enter the Netlify URL in the <b>Podcast base URL</b> field, then your email. When generation finishes, you\u2019ll receive an email with a download link for the podcast ZIP.<br><img src="__IMG_B__" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br>The ZIP contains: MP3 files, RSS feed (XML), cover art, and a landing page (index.html).'},
  {icon:'📤',title:'4. Upload to Netlify (drag & drop)',body:'In the Netlify dashboard, under <b>Sites</b>, drag the entire extracted folder onto the dashed drop zone. The site goes live in seconds. Then rename it from <i>Site configuration \u2192 Change site name</i>.'},
  {icon:'\u2705',title:'5. Verify',body:'Open the feed URL in your browser:<br><code>https://your-name.netlify.app/book_podcast.xml</code><br>If you see XML content, your podcast is live!'},
 ],
 apps_title:'Import into podcast apps',
 apps:[
  {name:'Apple Podcasts',platform:'iOS / Mac',steps:'<b>iPhone:</b> Library \u2192 \u22EE \u2192 Add Show by URL \u2192 paste feed URL<br><b>Mac:</b> File \u2192 Follow a Show by URL'},
  {name:'Pocket Casts',platform:'Android / iOS / Web',steps:'Search \u2192 link icon (🔗) \u2192 paste feed URL \u2192 Subscribe'},
  {name:'AntennaPod',platform:'Android',steps:'+ \u2192 Add RSS feed by URL \u2192 paste URL'},
  {name:'Overcast',platform:'iOS',steps:'+ \u2192 Add URL \u2192 paste feed URL'},
  {name:'Podcast Addict',platform:'Android',steps:'+ \u2192 RSS Feed \u2192 paste URL'},
 ],
 spotify_note:'\u26A0\uFE0F <b>Spotify</b> does not support adding private RSS feeds. Use one of the apps above.',
 tips_title:'Tips',
 tips:['<b>Share:</b> send the feed XML URL to friends \u2014 they don\u2019t need a Netlify account.','<b>Update:</b> re-upload files to Netlify to replace the previous version.','<b>Multiple books:</b> create a separate Netlify site for each audiobook.','<b>Limits:</b> 10 GB storage (~12 audiobooks). Remove finished ones to free up space.'],
 benefits_title:'Why listen as a podcast?',
 benefits:['Auto bookmarks \u2014 resume where you left off','Episode ordering and auto-advance','Cover art, titles, and metadata in your app','Adjustable speed (1.5\u00d7, 2\u00d7\u2026) and sleep timer','Streaming without downloading all files'],
},
fr:{
 intro:'Audiobook Maker g\u00e9n\u00e8re, en plus des fichiers audio, un <b>package podcast complet</b> avec flux RSS 2.0. Pour le rendre accessible en podcast, les fichiers doivent \u00eatre publi\u00e9s sur un serveur web. La solution id\u00e9ale est votre <b>propre site web</b> ou espace d\u2019h\u00e9bergement. En alternative, pour un usage personnel ou le partage avec quelques amis, vous pouvez utiliser une solution gratuite comme <b>Netlify</b>, d\u00e9crite dans ce guide.',
 scope:'👤 <b>Usage recommand\u00e9 :</b> cette solution est con\u00e7ue pour un usage personnel ou le partage avec des proches. Netlify offre 100 Go/mois de bande passante gratuite.',
 sections:[
  {icon:'🎧',title:'1. G\u00e9n\u00e9rez le livre audio par chapitres',body:'Chargez votre fichier EPUB, choisissez la langue et la voix, puis s\u00e9lectionnez <b>📁 Par chapitres</b>. Le podcast n\u00e9cessite un fichier MP3 par \u00e9pisode.'},
  {icon:'🌐',title:'2. Cr\u00e9ez un compte Netlify gratuit',body:'Rendez-vous sur <b>app.netlify.com</b>. Inscription par email ou GitHub, sans carte bancaire. Plan gratuit : 100 Go de bande passante, 10 Go de stockage, HTTPS automatique.'},
  {icon:'📦',title:'3. T\u00e9l\u00e9chargez le package podcast',body:'Avant de t\u00e9l\u00e9charger, vous devrez saisir l\u2019<b>URL Netlify</b> o\u00f9 vous publierez les fichiers (ex: <code>https://mon-livre.netlify.app/</code>). Cette URL est int\u00e9gr\u00e9e dans le flux RSS pour que les apps podcast trouvent vos \u00e9pisodes. Deux options pour obtenir le package :<br><br><b>Option A \u2014 Restez sur la page :</b> une fois la g\u00e9n\u00e9ration termin\u00e9e, cliquez sur <b>🎙️ T\u00e9l\u00e9charger podcast</b>. L\u2019URL vous sera demand\u00e9e, puis le ZIP sera t\u00e9l\u00e9charg\u00e9.<br><img src="__IMG_A__" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br><b>Option B \u2014 Notification par email :</b> pour les longs livres audio, l\u2019app propose de vous notifier par email. Dans la fen\u00eatre, s\u00e9lectionnez <b>Podcast (avec RSS)</b>, entrez l\u2019URL Netlify dans le champ <b>URL de base du podcast</b>, puis votre email. \u00c0 la fin, vous recevrez un email avec le lien de t\u00e9l\u00e9chargement.<br><img src="__IMG_B__" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br>Le ZIP contient : fichiers MP3, flux RSS (XML), couverture et page d\u2019accueil (index.html).'},
  {icon:'📤',title:'4. Publiez sur Netlify (glisser-d\u00e9poser)',body:'Dans le tableau de bord Netlify, section <b>Sites</b>, glissez le dossier extrait dans la zone en pointill\u00e9s. Le site est en ligne en quelques secondes. Renommez-le ensuite.'},
  {icon:'\u2705',title:'5. V\u00e9rifiez',body:'Ouvrez l\u2019URL du flux dans votre navigateur :<br><code>https://nom-choisi.netlify.app/nom_podcast.xml</code><br>Si vous voyez du XML, le podcast est en ligne !'},
 ],
 apps_title:'Importer dans les apps podcast',
 apps:[
  {name:'Apple Podcasts',platform:'iOS / Mac',steps:'<b>iPhone :</b> Biblioth\u00e8que \u2192 \u22EE \u2192 Ajouter via URL<br><b>Mac :</b> Fichier \u2192 Suivre une \u00e9mission via URL'},
  {name:'Pocket Casts',platform:'Android / iOS / Web',steps:'Rechercher \u2192 ic\u00f4ne lien (🔗) \u2192 coller l\u2019URL \u2192 S\u2019abonner'},
  {name:'AntennaPod',platform:'Android',steps:'+ \u2192 Ajouter un flux RSS par URL \u2192 coller l\u2019URL'},
  {name:'Overcast',platform:'iOS',steps:'+ \u2192 Add URL \u2192 coller l\u2019URL du flux'},
  {name:'Podcast Addict',platform:'Android',steps:'+ \u2192 Flux RSS \u2192 coller l\u2019URL'},
 ],
 spotify_note:'\u26A0\uFE0F <b>Spotify</b> ne permet pas d\u2019ajouter des flux RSS priv\u00e9s. Utilisez une app ci-dessus.',
 tips_title:'Conseils',
 tips:['<b>Partager :</b> envoyez l\u2019URL du flux \u00e0 vos proches.','<b>Mettre \u00e0 jour :</b> rechargez les fichiers sur Netlify.','<b>Plusieurs livres :</b> cr\u00e9ez un site par livre audio.','<b>Limites :</b> 10 Go de stockage (~12 livres audio).'],
 benefits_title:'\u00c9couter en podcast : les avantages',
 benefits:['Signet automatique \u2014 reprenez o\u00f9 vous en \u00e9tiez','Ordre des \u00e9pisodes et passage automatique','Couverture et m\u00e9tadonn\u00e9es dans l\u2019app','Vitesse r\u00e9glable et minuterie de sommeil','Streaming sans t\u00e9l\u00e9charger tous les fichiers'],
},
es:{
 intro:'Audiobook Maker genera, adem\u00e1s de los archivos de audio, un <b>paquete podcast completo</b> con feed RSS 2.0. Para hacerlo accesible como podcast, los archivos deben publicarse en un servidor web. La soluci\u00f3n ideal es tu <b>propio sitio web</b> o espacio de hosting. Como alternativa, para uso personal o para compartir con unos pocos amigos, puedes usar una soluci\u00f3n gratuita como <b>Netlify</b>, descrita en esta gu\u00eda.',
 scope:'👤 <b>Uso recomendado:</b> esta soluci\u00f3n est\u00e1 pensada para uso personal o para compartir con amigos y familiares. Netlify ofrece 100 GB/mes de ancho de banda gratuito.',
 sections:[
  {icon:'🎧',title:'1. Genera el audiolibro por cap\u00edtulos',body:'Sube tu archivo EPUB, elige idioma y voz, y selecciona <b>📁 Por cap\u00edtulos</b>. El podcast necesita un archivo MP3 por episodio.'},
  {icon:'🌐',title:'2. Crea una cuenta gratuita en Netlify',body:'Ve a <b>app.netlify.com</b> y reg\u00edstrate con email o GitHub. Sin tarjeta de cr\u00e9dito. Plan gratuito: 100 GB de ancho de banda, 10 GB de almacenamiento, HTTPS autom\u00e1tico.'},
  {icon:'📦',title:'3. Descarga el paquete podcast',body:'Antes de descargar, deber\u00e1s introducir la <b>URL de Netlify</b> donde publicar\u00e1s los archivos (ej: <code>https://mi-libro.netlify.app/</code>). Esta URL se incorpora al feed RSS para que las apps de podcast encuentren tus episodios. Hay dos formas de obtener el paquete:<br><br><b>Opci\u00f3n A \u2014 Espera en la p\u00e1gina:</b> cuando termine la generaci\u00f3n, haz clic en <b>🎙️ Descargar podcast</b>. Se te pedir\u00e1 la URL y luego se descargar\u00e1 el ZIP.<br><img src="__IMG_A__" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br><b>Opci\u00f3n B \u2014 Notificaci\u00f3n por email:</b> para audiolibros largos, la app ofrece avisarte por email. En el di\u00e1logo de notificaci\u00f3n, selecciona <b>Podcast (con RSS)</b>, introduce la URL de Netlify en el campo <b>URL base del podcast</b> y tu email. Al completarse, recibir\u00e1s un email con el enlace de descarga.<br><img src="__IMG_B__" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br>El ZIP contiene: archivos MP3, feed RSS (XML), portada y p\u00e1gina de presentaci\u00f3n (index.html).'},
  {icon:'📤',title:'4. Sube a Netlify (arrastrar y soltar)',body:'En el panel de Netlify, secci\u00f3n <b>Sites</b>, arrastra la carpeta extra\u00edda a la zona punteada. El sitio estar\u00e1 en l\u00ednea en segundos. Luego renombra desde <i>Site configuration \u2192 Change site name</i>.'},
  {icon:'\u2705',title:'5. Verifica',body:'Abre la URL del feed en tu navegador:<br><code>https://nombre-elegido.netlify.app/nombre_podcast.xml</code><br>\u00a1Si ves contenido XML, el podcast est\u00e1 en l\u00ednea!'},
 ],
 apps_title:'Importar en apps de podcast',
 apps:[
  {name:'Apple Podcasts',platform:'iOS / Mac',steps:'<b>iPhone:</b> Biblioteca \u2192 \u22EE \u2192 A\u00f1adir por URL<br><b>Mac:</b> Archivo \u2192 Seguir programa por URL'},
  {name:'Pocket Casts',platform:'Android / iOS / Web',steps:'Buscar \u2192 icono enlace (🔗) \u2192 pegar URL \u2192 Suscribirse'},
  {name:'AntennaPod',platform:'Android',steps:'+ \u2192 A\u00f1adir feed RSS por URL \u2192 pegar URL'},
  {name:'Overcast',platform:'iOS',steps:'+ \u2192 Add URL \u2192 pegar URL del feed'},
  {name:'Podcast Addict',platform:'Android',steps:'+ \u2192 Feed RSS \u2192 pegar URL'},
 ],
 spotify_note:'\u26A0\uFE0F <b>Spotify</b> no permite a\u00f1adir feeds RSS privados. Usa una de las apps anteriores.',
 tips_title:'Consejos',
 tips:['<b>Comparte:</b> env\u00eda la URL del feed a tus amigos.','<b>Actualiza:</b> vuelve a subir los archivos a Netlify.','<b>M\u00e1s libros:</b> crea un sitio Netlify por cada audiolibro.','<b>L\u00edmites:</b> 10 GB de almacenamiento (~12 audiolibros).'],
 benefits_title:'\u00bfPor qu\u00e9 escuchar como podcast?',
 benefits:['Marcador autom\u00e1tico \u2014 retoma donde lo dejaste','Orden de episodios y avance autom\u00e1tico','Portada y metadatos visibles en la app','Velocidad ajustable y temporizador de sue\u00f1o','Streaming sin descargar todos los archivos'],
},
de:{
 intro:'Audiobook Maker erzeugt neben den Audiodateien ein <b>komplettes Podcast-Paket</b> mit RSS 2.0-Feed. Um es als Podcast verf\u00fcgbar zu machen, m\u00fcssen die Dateien auf einem Webserver ver\u00f6ffentlicht werden. Die ideale L\u00f6sung ist eine <b>eigene Website</b> oder ein eigener Hosting-Bereich. Alternativ k\u00f6nnen Sie f\u00fcr den pers\u00f6nlichen Gebrauch oder zum Teilen mit wenigen Freunden eine kostenlose L\u00f6sung wie <b>Netlify</b> verwenden, die in dieser Anleitung beschrieben wird.',
 scope:'👤 <b>Empfohlene Nutzung:</b> Diese L\u00f6sung ist f\u00fcr den pers\u00f6nlichen Gebrauch oder zum Teilen mit Freunden und Familie gedacht. Netlify bietet 100 GB/Monat kostenlose Bandbreite.',
 sections:[
  {icon:'🎧',title:'1. H\u00f6rbuch nach Kapiteln generieren',body:'Laden Sie Ihre EPUB-Datei hoch, w\u00e4hlen Sie Sprache und Stimme, dann <b>📁 Nach Kapiteln</b> bei der Ausgabe. Podcasts ben\u00f6tigen eine MP3 pro Episode.'},
  {icon:'🌐',title:'2. Kostenloses Netlify-Konto erstellen',body:'Gehen Sie zu <b>app.netlify.com</b> und registrieren Sie sich. Keine Kreditkarte n\u00f6tig. Kostenlos: 100 GB Bandbreite, 10 GB Speicher, automatisches HTTPS.'},
  {icon:'📦',title:'3. Podcast-Paket herunterladen',body:'Vor dem Download m\u00fcssen Sie die <b>Netlify-URL</b> eingeben, unter der die Dateien ver\u00f6ffentlicht werden (z.B. <code>https://mein-buch.netlify.app/</code>). Diese URL wird in den RSS-Feed eingebettet, damit Podcast-Apps Ihre Episoden finden. Es gibt zwei Wege:<br><br><b>Option A \u2014 Auf der Seite warten:</b> nach Abschluss der Generierung klicken Sie auf <b>🎙️ Podcast herunterladen</b>. Sie werden nach der URL gefragt, dann wird das ZIP heruntergeladen.<br><img src="__IMG_A__" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br><b>Option B \u2014 E-Mail-Benachrichtigung:</b> bei langen H\u00f6rb\u00fcchern bietet die App eine E-Mail-Benachrichtigung an. W\u00e4hlen Sie <b>Podcast (mit RSS)</b>, geben Sie die Netlify-URL im Feld <b>Podcast-Basis-URL</b> ein und Ihre E-Mail. Nach Abschluss erhalten Sie eine E-Mail mit dem Download-Link.<br><img src="__IMG_B__" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br>Das ZIP enth\u00e4lt: MP3-Dateien, RSS-Feed (XML), Cover und eine Startseite (index.html).'},
  {icon:'📤',title:'4. Auf Netlify hochladen (Drag & Drop)',body:'Im Netlify-Dashboard unter <b>Sites</b> den extrahierten Ordner in die gestrichelte Zone ziehen. Die Seite ist in Sekunden online. Dann unter <i>Site configuration \u2192 Change site name</i> umbenennen.'},
  {icon:'\u2705',title:'5. \u00dcberpr\u00fcfen',body:'\u00d6ffnen Sie die Feed-URL im Browser:<br><code>https://name.netlify.app/buch_podcast.xml</code><br>Wenn Sie XML-Inhalt sehen, ist der Podcast online!'},
 ],
 apps_title:'In Podcast-Apps importieren',
 apps:[
  {name:'Apple Podcasts',platform:'iOS / Mac',steps:'<b>iPhone:</b> Mediathek \u2192 \u22EE \u2192 \u00dcber URL hinzuf\u00fcgen<br><b>Mac:</b> Ablage \u2192 Show per URL folgen'},
  {name:'Pocket Casts',platform:'Android / iOS / Web',steps:'Suche \u2192 Link-Symbol (🔗) \u2192 URL einf\u00fcgen \u2192 Abonnieren'},
  {name:'AntennaPod',platform:'Android',steps:'+ \u2192 RSS-Feed per URL hinzuf\u00fcgen \u2192 URL einf\u00fcgen'},
  {name:'Overcast',platform:'iOS',steps:'+ \u2192 Add URL \u2192 Feed-URL einf\u00fcgen'},
  {name:'Podcast Addict',platform:'Android',steps:'+ \u2192 RSS-Feed \u2192 URL einf\u00fcgen'},
 ],
 spotify_note:'\u26A0\uFE0F <b>Spotify</b> unterst\u00fctzt keine privaten RSS-Feeds. Nutzen Sie eine der oben genannten Apps.',
 tips_title:'Tipps',
 tips:['<b>Teilen:</b> Senden Sie die Feed-URL an Freunde.','<b>Aktualisieren:</b> Laden Sie neue Dateien auf Netlify hoch.','<b>Mehrere B\u00fccher:</b> Erstellen Sie eine separate Netlify-Site pro H\u00f6rbuch.','<b>Limits:</b> 10 GB Speicher (~12 H\u00f6rb\u00fccher).'],
 benefits_title:'Warum als Podcast h\u00f6ren?',
 benefits:['Automatisches Lesezeichen \u2014 dort weitermachen, wo Sie aufgeh\u00f6rt haben','Episodenreihenfolge und automatischer Wechsel','Cover und Metadaten in der App sichtbar','Einstellbare Geschwindigkeit und Schlaf-Timer','Streaming ohne alle Dateien herunterzuladen'],
},
zh:{
 intro:'Audiobook Maker \u9664\u4e86\u751f\u6210\u97f3\u9891\u6587\u4ef6\u5916\uff0c\u8fd8\u4f1a\u751f\u6210\u4e00\u4e2a\u5305\u542bRSS 2.0\u8ba2\u9605\u6e90\u7684<b>\u5b8c\u6574\u64ad\u5ba2\u5305</b>\u3002\u8981\u5c06\u5176\u4f5c\u4e3a\u64ad\u5ba2\u53d1\u5e03\uff0c\u9700\u8981\u5c06\u6587\u4ef6\u653e\u5728\u53ef\u8bbf\u95ee\u7684\u7f51\u7edc\u670d\u52a1\u5668\u4e0a\u3002\u7406\u60f3\u7684\u65b9\u6848\u662f\u4f7f\u7528<b>\u81ea\u5df1\u7684\u7f51\u7ad9</b>\u6216\u6258\u7ba1\u7a7a\u95f4\u3002\u4f5c\u4e3a\u66ff\u4ee3\uff0c\u5982\u679c\u4ec5\u4f9b\u4e2a\u4eba\u4f7f\u7528\u6216\u4e0e\u5c11\u6570\u670b\u53cb\u5206\u4eab\uff0c\u53ef\u4ee5\u4f7f\u7528\u672c\u6307\u5357\u4ecb\u7ecd\u7684\u514d\u8d39\u65b9\u6848<b>Netlify</b>\u3002',
 scope:'👤 <b>\u5efa\u8bae\u7528\u9014\uff1a</b>\u6b64\u65b9\u6848\u9002\u5408\u4e2a\u4eba\u4f7f\u7528\u6216\u4e0e\u4eb2\u53cb\u5206\u4eab\u3002Netlify\u6bcf\u6708\u63d0\u4f9b100 GB\u514d\u8d39\u6d41\u91cf\u3002',
 sections:[
  {icon:'🎧',title:'1. \u6309\u7ae0\u8282\u751f\u6210\u6709\u58f0\u8bfb\u7269',body:'\u4e0a\u4f20EPUB\u6587\u4ef6\uff0c\u9009\u62e9\u8bed\u8a00\u548c\u8bed\u97f3\uff0c\u7136\u540e\u5728\u8f93\u51fa\u90e8\u5206\u9009\u62e9<b>📁 \u6309\u7ae0\u8282</b>\u3002\u64ad\u5ba2\u9700\u8981\u6bcf\u96c6\u4e00\u4e2aMP3\u6587\u4ef6\u3002'},
  {icon:'🌐',title:'2. \u521b\u5efaNelify\u514d\u8d39\u8d26\u6237',body:'\u8bbf\u95ee<b>app.netlify.com</b>\uff0c\u7528\u90ae\u7bb1\u6216GitHub\u6ce8\u518c\u3002\u65e0\u9700\u4fe1\u7528\u5361\u3002\u514d\u8d39\u8ba1\u5212\uff1a100 GB\u6d41\u91cf\u300110 GB\u5b58\u50a8\u3001\u81ea\u52a8HTTPS\u3002'},
  {icon:'📦',title:'3. \u4e0b\u8f7d\u64ad\u5ba2\u5305',body:'\u4e0b\u8f7d\u524d\u9700\u8981\u8f93\u5165\u60a8\u8ba1\u5212\u53d1\u5e03\u6587\u4ef6\u7684<b>Netlify URL</b>\uff08\u5982 <code>https://my-book.netlify.app/</code>\uff09\u3002\u8be5URL\u4f1a\u5d4c\u5165RSS\u8ba2\u9605\u6e90\uff0c\u4ee5\u4fbf\u64ad\u5ba2\u5e94\u7528\u627e\u5230\u60a8\u7684\u5267\u96c6\u3002\u6709\u4e24\u79cd\u83b7\u53d6\u65b9\u5f0f\uff1a<br><br><b>\u65b9\u5f0fA \u2014 \u5728\u9875\u9762\u7b49\u5f85\uff1a</b>\u751f\u6210\u5b8c\u6210\u540e\uff0c\u70b9\u51fb<b>🎙️ \u4e0b\u8f7d\u64ad\u5ba2</b>\u3002\u7cfb\u7edf\u4f1a\u8981\u6c42\u60a8\u8f93\u5165URL\uff0c\u7136\u540eZIP\u5c06\u5f00\u59cb\u4e0b\u8f7d\u3002<br><img src="__IMG_A__" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br><b>\u65b9\u5f0fB \u2014 \u90ae\u4ef6\u901a\u77e5\uff1a</b>\u5bf9\u4e8e\u8f83\u957f\u7684\u6709\u58f0\u8bfb\u7269\uff0c\u5e94\u7528\u63d0\u4f9b\u90ae\u4ef6\u901a\u77e5\u529f\u80fd\u3002\u5728\u901a\u77e5\u5bf9\u8bdd\u6846\u4e2d\uff0c\u9009\u62e9<b>\u64ad\u5ba2\uff08\u542bRSS\uff09</b>\uff0c\u5728<b>\u64ad\u5ba2\u53d1\u5e03\u57fa\u7840URL</b>\u5b57\u6bb5\u4e2d\u8f93\u5165Netlify URL\uff0c\u7136\u540e\u8f93\u5165\u90ae\u7bb1\u3002\u751f\u6210\u5b8c\u6210\u540e\uff0c\u60a8\u5c06\u6536\u5230\u5305\u542b\u4e0b\u8f7d\u94fe\u63a5\u7684\u90ae\u4ef6\u3002<br><img src="__IMG_B__" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br>ZIP\u5305\u542b\uff1aMP3\u6587\u4ef6\u3001RSS\u8ba2\u9605\u6e90\uff08XML\uff09\u3001\u5c01\u9762\u548c\u843d\u5730\u9875\uff08index.html\uff09\u3002'},
  {icon:'📤',title:'4. \u4e0a\u4f20\u5230Netlify\uff08\u62d6\u653e\uff09',body:'\u5728Netlify\u63a7\u5236\u53f0\u7684<b>Sites</b>\u90e8\u5206\uff0c\u5c06\u89e3\u538b\u7684\u6587\u4ef6\u5939\u62d6\u5230\u865a\u7ebf\u533a\u57df\u3002\u7f51\u7ad9\u5373\u523b\u4e0a\u7ebf\u3002\u7136\u540e\u5728 <i>Site configuration \u2192 Change site name</i> \u91cd\u547d\u540d\u3002'},
  {icon:'\u2705',title:'5. \u9a8c\u8bc1',body:'\u5728\u6d4f\u89c8\u5668\u4e2d\u6253\u5f00\u8ba2\u9605\u6e90URL\uff1a<br><code>https://your-name.netlify.app/book_podcast.xml</code><br>\u5982\u679c\u770b\u5230XML\u5185\u5bb9\uff0c\u64ad\u5ba2\u5df2\u4e0a\u7ebf\uff01'},
 ],
 apps_title:'\u5bfc\u5165\u64ad\u5ba2\u5e94\u7528',
 apps:[
  {name:'Apple Podcasts',platform:'iOS / Mac',steps:'<b>iPhone:</b> \u8d44\u6599\u5e93 \u2192 \u22EE \u2192 \u901a\u8fc7URL\u6dfb\u52a0<br><b>Mac:</b> \u6587\u4ef6 \u2192 \u901a\u8fc7URL\u5173\u6ce8\u8282\u76ee'},
  {name:'Pocket Casts',platform:'Android / iOS / Web',steps:'\u641c\u7d22 \u2192 \u94fe\u63a5\u56fe\u6807 (🔗) \u2192 \u7c98\u8d34URL \u2192 \u8ba2\u9605'},
  {name:'AntennaPod',platform:'Android',steps:'+ \u2192 \u901a\u8fc7URL\u6dfb\u52a0RSS\u8ba2\u9605\u6e90 \u2192 \u7c98\u8d34URL'},
  {name:'Overcast',platform:'iOS',steps:'+ \u2192 Add URL \u2192 \u7c98\u8d34\u8ba2\u9605\u6e90URL'},
  {name:'Podcast Addict',platform:'Android',steps:'+ \u2192 RSS Feed \u2192 \u7c98\u8d34URL'},
 ],
 spotify_note:'\u26A0\uFE0F <b>Spotify</b> \u4e0d\u652f\u6301\u6dfb\u52a0\u79c1\u6709RSS\u8ba2\u9605\u6e90\u3002\u8bf7\u4f7f\u7528\u4ee5\u4e0a\u5e94\u7528\u3002',
 tips_title:'\u5c0f\u8d34\u58eb',
 tips:['<b>\u5206\u4eab\uff1a</b>\u5c06\u8ba2\u9605\u6e90URL\u53d1\u9001\u7ed9\u670b\u53cb\u3002','<b>\u66f4\u65b0\uff1a</b>\u91cd\u65b0\u4e0a\u4f20\u6587\u4ef6\u5230Netlify\u3002','<b>\u591a\u672c\u4e66\uff1a</b>\u6bcf\u672c\u4e66\u521b\u5efa\u4e00\u4e2aNelify\u7f51\u7ad9\u3002','<b>\u9650\u5236\uff1a</b>10 GB\u5b58\u50a8\uff08\u7ea612\u672c\u6709\u58f0\u8bfb\u7269\uff09\u3002'],
 benefits_title:'\u4e3a\u4ec0\u4e48\u4ee5\u64ad\u5ba2\u5f62\u5f0f\u6536\u542c\uff1f',
 benefits:['\u81ea\u52a8\u4e66\u7b7e \u2014 \u4ece\u4e0a\u6b21\u505c\u4e0b\u7684\u5730\u65b9\u7ee7\u7eed','\u5267\u96c6\u987a\u5e8f\u548c\u81ea\u52a8\u64ad\u653e\u4e0b\u4e00\u96c6','\u5e94\u7528\u4e2d\u663e\u793a\u5c01\u9762\u548c\u5143\u6570\u636e','\u53ef\u8c03\u901f\u5ea6\u548c\u7761\u7720\u5b9a\u65f6\u5668','\u6d41\u5f0f\u64ad\u653e\u65e0\u9700\u4e0b\u8f7d\u6240\u6709\u6587\u4ef6'],
}
};

function buildPodcastGuide(){
  const g=PG[cl]||PG.en;
  let h='<style>.pg-guide code{background:var(--srf2);color:var(--ac);padding:2px 6px;border-radius:4px;font-size:.85em;word-break:break-all}.pg-guide a{color:var(--ac)}.pg-guide i{color:inherit;opacity:.85}</style>';
  h+='<div class="pg-guide" style="font-size:.93rem;line-height:1.6;color:var(--tx)">';
  // Intro
  h+='<p style="margin:0 0 10px;color:var(--tx)">'+g.intro+'</p>';
  h+='<div style="background:#fff3cd;border-left:4px solid #f0c040;padding:10px 14px;border-radius:6px;margin:0 0 18px;font-size:.88rem;color:#5a4510">'+g.scope+'</div>';
  // Steps
  g.sections.forEach(sec=>{
    h+='<div style="display:flex;gap:12px;margin-bottom:14px;align-items:flex-start">';
    h+='<div style="font-size:1.4rem;line-height:1;flex-shrink:0;margin-top:2px">'+sec.icon+'</div>';
    h+='<div><div style="font-weight:700;margin-bottom:4px;color:var(--tx)">'+sec.title+'</div>';
    h+='<div style="color:var(--txd)">'+sec.body.replace(/__IMG_A__/g,PG_IMG_A).replace(/__IMG_B__/g,PG_IMG_B)+'</div></div></div>';
  });
  // Divider
  h+='<hr style="border:none;border-top:1px solid var(--brd);margin:20px 0">';
  // Apps
  h+='<h3 style="margin:0 0 12px;font-size:1.05rem;color:var(--tx)">📱 '+g.apps_title+'</h3>';
  h+='<table style="width:100%;border-collapse:collapse;font-size:.88rem;margin-bottom:10px;color:var(--tx)">';
  h+='<thead><tr style="background:var(--srf2)"><th style="padding:8px 10px;text-align:left;border-bottom:2px solid var(--brd)">App</th><th style="padding:8px 10px;text-align:left;border-bottom:2px solid var(--brd)">Platform</th><th style="padding:8px 10px;text-align:left;border-bottom:2px solid var(--brd)">Steps</th></tr></thead><tbody>';
  g.apps.forEach(a=>{
    h+='<tr><td style="padding:7px 10px;border-bottom:1px solid var(--brd);font-weight:600;white-space:nowrap">'+a.name+'</td>';
    h+='<td style="padding:7px 10px;border-bottom:1px solid var(--brd);color:var(--txd);font-size:.82rem;white-space:nowrap">'+a.platform+'</td>';
    h+='<td style="padding:7px 10px;border-bottom:1px solid var(--brd)">'+a.steps+'</td></tr>';
  });
  h+='</tbody></table>';
  h+='<div style="background:#fff0f0;border-left:4px solid #e04040;padding:8px 14px;border-radius:6px;margin:0 0 18px;font-size:.85rem;color:#802020">'+g.spotify_note+'</div>';
  // Benefits
  h+='<h3 style="margin:0 0 10px;font-size:1.05rem;color:var(--tx)">🎧 '+g.benefits_title+'</h3>';
  h+='<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px">';
  g.benefits.forEach(b=>{
    h+='<div style="background:var(--srf2);color:var(--tx);padding:6px 12px;border-radius:16px;font-size:.84rem">\u2713 '+b+'</div>';
  });
  h+='</div>';
  // Tips
  h+='<h3 style="margin:0 0 10px;font-size:1.05rem;color:var(--tx)">💡 '+g.tips_title+'</h3>';
  g.tips.forEach(tip=>{
    h+='<div style="padding:4px 0;font-size:.88rem;color:var(--tx)">\u2022 '+tip+'</div>';
  });
  h+='</div>';
  document.getElementById('pgBody').innerHTML=h;
}
function openPodcastGuide(){buildPodcastGuide();document.getElementById('pgModal').classList.add('open')}
function closePodcastGuide(){document.getElementById('pgModal').classList.remove('open')}

// ═══════════════════ ABOUT PROJECT ═══════════════════
const ABOUT={
it:{link:"Informazioni sul progetto",title:"Informazioni sul progetto",paras:[
"Il progetto Audiobook Maker nasce per rispondere ad un mio personale desiderio di poter ascoltare, sfruttando i miei spostamenti di lavoro, alcuni libri che non ho tempo di \u201cleggere con gli occhi\u201d.",
"Mi sono messo al lavoro dopo aver constatato che non esistono strumenti pronti e semplici per tradurre un libro in audio con lettori di buona qualit\u00e0.",
"Successivamente, parlandone con amici, mi sono reso conto che uno strumento del genere potrebbe essere di aiuto ad altre persone come me e, soprattutto, alle tante persone che, per vari motivi (ipovedenti, dislessia,...), hanno difficolt\u00e0 di lettura.",
"Ho pensato dunque di mettere a disposizione di tutti questo strumento gratuitamente.",
"Provatelo, usatelo e per segnalazione di errori o per suggerimenti su nuove funzionalit\u00e0, scrivetemi a:"]},
en:{link:"About this project",title:"About this project",paras:[
"The Audiobook Maker project was born from my personal desire to listen to some books I don\u2019t have time to \u201cread with my eyes\u201d, taking advantage of my work commute.",
"I started working on it after realizing that there are no ready-made, simple tools to convert a book into audio with good quality readers.",
"Later, talking about it with friends, I realized that such a tool could help other people like me and, above all, the many people who, for various reasons (visually impaired, dyslexia,...), have reading difficulties.",
"So I decided to make this tool available to everyone for free.",
"Try it, use it, and for bug reports or suggestions for new features, write to me at:"]},
fr:{link:"\u00c0 propos du projet",title:"\u00c0 propos du projet",paras:[
"Le projet Audiobook Maker est n\u00e9 de mon d\u00e9sir personnel de pouvoir \u00e9couter, en profitant de mes trajets professionnels, certains livres que je n\u2019ai pas le temps de \u00ab lire avec les yeux \u00bb.",
"Je me suis mis au travail apr\u00e8s avoir constat\u00e9 qu\u2019il n\u2019existe pas d\u2019outils simples et pr\u00eats \u00e0 l\u2019emploi pour convertir un livre en audio avec des lecteurs de bonne qualit\u00e9.",
"Par la suite, en en parlant avec des amis, j\u2019ai r\u00e9alis\u00e9 qu\u2019un tel outil pourrait aider d\u2019autres personnes comme moi et, surtout, les nombreuses personnes qui, pour diverses raisons (malvoyants, dyslexie,...), ont des difficult\u00e9s de lecture.",
"J\u2019ai donc d\u00e9cid\u00e9 de mettre cet outil \u00e0 la disposition de tous gratuitement.",
"Essayez-le, utilisez-le et pour signaler des erreurs ou sugg\u00e9rer de nouvelles fonctionnalit\u00e9s, \u00e9crivez-moi \u00e0 :"]},
es:{link:"Sobre el proyecto",title:"Sobre el proyecto",paras:[
"El proyecto Audiobook Maker nace de mi deseo personal de poder escuchar, aprovechando mis desplazamientos de trabajo, algunos libros que no tengo tiempo de \u201cleer con los ojos\u201d.",
"Me puse a trabajar tras constatar que no existen herramientas listas y sencillas para convertir un libro en audio con lectores de buena calidad.",
"Posteriormente, hablando con amigos, me di cuenta de que una herramienta as\u00ed podr\u00eda ayudar a otras personas como yo y, sobre todo, a las muchas personas que, por diversos motivos (discapacidad visual, dislexia,...), tienen dificultades de lectura.",
"As\u00ed que decid\u00ed poner esta herramienta a disposici\u00f3n de todos de forma gratuita.",
"Pru\u00e9benlo, \u00fasenlo y para reportar errores o sugerir nuevas funcionalidades, escr\u00edbanme a:"]},
de:{link:"\u00dcber das Projekt",title:"\u00dcber das Projekt",paras:[
"Das Projekt Audiobook Maker entstand aus meinem pers\u00f6nlichen Wunsch, einige B\u00fccher, f\u00fcr die ich keine Zeit habe sie \u201emit den Augen zu lesen\u201c, w\u00e4hrend meiner Arbeitswege h\u00f6ren zu k\u00f6nnen.",
"Ich machte mich an die Arbeit, nachdem ich festgestellt hatte, dass es keine fertigen und einfachen Tools gibt, um ein Buch mit guten Vorlesestimmen in Audio umzuwandeln.",
"Sp\u00e4ter, im Gespr\u00e4ch mit Freunden, wurde mir klar, dass ein solches Tool auch anderen Menschen wie mir helfen k\u00f6nnte und vor allem den vielen Menschen, die aus verschiedenen Gr\u00fcnden (Sehbehinderung, Legasthenie,...) Leseschwierigkeiten haben.",
"Deshalb habe ich beschlossen, dieses Tool allen kostenlos zur Verf\u00fcgung zu stellen.",
"Probieren Sie es aus, nutzen Sie es und schreiben Sie mir f\u00fcr Fehlermeldungen oder Vorschl\u00e4ge f\u00fcr neue Funktionen an:"]},
zh:{link:"\u5173\u4e8e\u672c\u9879\u76ee",title:"\u5173\u4e8e\u672c\u9879\u76ee",paras:[
"Audiobook Maker\u9879\u76ee\u6e90\u4e8e\u6211\u4e2a\u4eba\u7684\u613f\u671b\uff1a\u5229\u7528\u5de5\u4f5c\u901a\u52e4\u65f6\u95f4\uff0c\u6536\u542c\u4e00\u4e9b\u6211\u6ca1\u6709\u65f6\u95f4\u201c\u7528\u773c\u775b\u9605\u8bfb\u201d\u7684\u4e66\u7c4d\u3002",
"\u5728\u53d1\u73b0\u5e02\u9762\u4e0a\u6ca1\u6709\u73b0\u6210\u7684\u3001\u7b80\u5355\u7684\u5de5\u5177\u53ef\u4ee5\u7528\u9ad8\u8d28\u91cf\u7684\u8bed\u97f3\u5c06\u4e66\u7c4d\u8f6c\u6362\u4e3a\u97f3\u9891\u540e\uff0c\u6211\u5f00\u59cb\u7740\u624b\u5f00\u53d1\u3002",
"\u540e\u6765\uff0c\u4e0e\u670b\u53cb\u4ea4\u6d41\u540e\uff0c\u6211\u610f\u8bc6\u5230\u8fd9\u6837\u7684\u5de5\u5177\u4e0d\u4ec5\u80fd\u5e2e\u52a9\u50cf\u6211\u8fd9\u6837\u7684\u4eba\uff0c\u66f4\u91cd\u8981\u7684\u662f\u80fd\u5e2e\u52a9\u8bb8\u591a\u56e0\u5404\u79cd\u539f\u56e0\uff08\u89c6\u529b\u969c\u788d\u3001\u8bfb\u5199\u56f0\u96be\u7b49\uff09\u800c\u6709\u9605\u8bfb\u56f0\u96be\u7684\u4eba\u3002",
"\u56e0\u6b64\u6211\u51b3\u5b9a\u5c06\u8fd9\u4e2a\u5de5\u5177\u514d\u8d39\u63d0\u4f9b\u7ed9\u6240\u6709\u4eba\u3002",
"\u8bd5\u8bd5\u770b\uff0c\u7528\u8d77\u6765\uff0c\u5982\u679c\u60a8\u6709\u9519\u8bef\u62a5\u544a\u6216\u65b0\u529f\u80fd\u5efa\u8bae\uff0c\u8bf7\u5199\u4fe1\u7ed9\u6211\uff1a"]}
};
function buildAbout(){
  const a=ABOUT[cl]||ABOUT.en;
  document.getElementById('aboutBtn').textContent=a.link;
  document.getElementById('aboutTitle').textContent=a.title;
  const b=document.getElementById('aboutBody');
  b.innerHTML=a.paras.map(p=>'<p class="about-text">'+p+'</p>').join('')
    +'<p class="about-contact">&#x2709;&#xFE0F; <a href="mailto:gfrangiamone@gmail.com">gfrangiamone@gmail.com</a> (Giuseppe Frangiamone)</p>';
}
function openAbout(){buildAbout();document.getElementById('aboutModal').classList.add('open')}

// ═══════════════════ SEO i18n ═══════════════════
const SEO={
it:{
  title:"Audiobook Maker \u2014 Convertitore EPUB in Audiolibro TTS",
  desc:"Strumento online gratuito per convertire ebook EPUB in audiolibri di alta qualit\u00e0 con voci neurali text-to-speech (TTS). Supporta pi\u00f9 lingue, selezione capitoli e generazione feed podcast RSS. Ideale per ipovedenti e persone con difficolt\u00e0 di lettura.",
  kw:"audiolibro, ebook, epub, tts, text to speech, da epub ad audiolibro, convertitore ebook, audiobook maker, tts ebook, voci neurali, audiolibro gratis, accessibilit\u00e0, ipovedenti, dislessia, podcast, rss, sintesi vocale, libro parlato",
  ld:"Strumento online gratuito per convertire ebook EPUB in audiolibri di alta qualit\u00e0 con voci neurali text-to-speech (TTS)."},
en:{
  title:"Audiobook Maker \u2014 EPUB to Audiobook TTS Converter",
  desc:"Free online tool to convert EPUB ebooks into high-quality audiobooks using neural text-to-speech (TTS) voices. Supports multiple languages, chapter selection, and podcast RSS feed generation. Great for visually impaired readers and people with reading difficulties.",
  kw:"audiobook, ebook, epub, tts, text to speech, epub to audiobook, ebook converter, audiobook maker, tts ebook, neural voices, free audiobook, accessibility, visually impaired, dyslexia, podcast, rss",
  ld:"Free online tool to convert EPUB ebooks into high-quality audiobooks using neural text-to-speech (TTS) voices."},
fr:{
  title:"Audiobook Maker \u2014 Convertisseur EPUB en Livre Audio TTS",
  desc:"Outil en ligne gratuit pour convertir des ebooks EPUB en livres audio de haute qualit\u00e9 avec des voix neuronales text-to-speech (TTS). Prend en charge plusieurs langues, la s\u00e9lection de chapitres et la g\u00e9n\u00e9ration de flux RSS podcast. Id\u00e9al pour les malvoyants et les personnes ayant des difficult\u00e9s de lecture.",
  kw:"livre audio, ebook, epub, tts, text to speech, epub en livre audio, convertisseur ebook, audiobook maker, tts ebook, voix neuronales, livre audio gratuit, accessibilit\u00e9, malvoyants, dyslexie, podcast, rss, synth\u00e8se vocale",
  ld:"Outil en ligne gratuit pour convertir des ebooks EPUB en livres audio de haute qualit\u00e9 avec des voix neuronales text-to-speech (TTS)."},
es:{
  title:"Audiobook Maker \u2014 Conversor EPUB a Audiolibro TTS",
  desc:"Herramienta online gratuita para convertir ebooks EPUB en audiolibros de alta calidad con voces neuronales text-to-speech (TTS). Soporta m\u00faltiples idiomas, selecci\u00f3n de cap\u00edtulos y generaci\u00f3n de feed podcast RSS. Ideal para personas con discapacidad visual y dificultades de lectura.",
  kw:"audiolibro, ebook, epub, tts, text to speech, epub a audiolibro, conversor ebook, audiobook maker, tts ebook, voces neuronales, audiolibro gratis, accesibilidad, discapacidad visual, dislexia, podcast, rss, s\u00edntesis de voz",
  ld:"Herramienta online gratuita para convertir ebooks EPUB en audiolibros de alta calidad con voces neuronales text-to-speech (TTS)."},
de:{
  title:"Audiobook Maker \u2014 EPUB zu H\u00f6rbuch TTS-Konverter",
  desc:"Kostenloses Online-Tool zum Konvertieren von EPUB-E-Books in hochwertige H\u00f6rb\u00fccher mit neuronalen Text-to-Speech (TTS) Stimmen. Unterst\u00fctzt mehrere Sprachen, Kapitelauswahl und Podcast-RSS-Feed-Generierung. Ideal f\u00fcr Sehbehinderte und Menschen mit Leseschwierigkeiten.",
  kw:"H\u00f6rbuch, E-Book, EPUB, TTS, Text-to-Speech, EPUB zu H\u00f6rbuch, E-Book-Konverter, Audiobook Maker, TTS E-Book, neuronale Stimmen, kostenloses H\u00f6rbuch, Barrierefreiheit, Sehbehinderung, Legasthenie, Podcast, RSS, Sprachsynthese",
  ld:"Kostenloses Online-Tool zum Konvertieren von EPUB-E-Books in hochwertige H\u00f6rb\u00fccher mit neuronalen Text-to-Speech (TTS) Stimmen."},
zh:{
  title:"Audiobook Maker \u2014 EPUB\u8f6c\u6709\u58f0\u8bfb\u7269 TTS\u8f6c\u6362\u5668",
  desc:"\u514d\u8d39\u5728\u7ebf\u5de5\u5177\uff0c\u4f7f\u7528\u795e\u7ecf\u7f51\u7edcTTS\u8bed\u97f3\u5c06EPUB\u7535\u5b50\u4e66\u8f6c\u6362\u4e3a\u9ad8\u8d28\u91cf\u6709\u58f0\u8bfb\u7269\u3002\u652f\u6301\u591a\u8bed\u8a00\u3001\u7ae0\u8282\u9009\u62e9\u548c\u64ad\u5ba2RSS\u8ba2\u9605\u6e90\u751f\u6210\u3002\u9002\u5408\u89c6\u529b\u969c\u788d\u8005\u548c\u6709\u9605\u8bfb\u56f0\u96be\u7684\u4eba\u7fa4\u3002",
  kw:"\u6709\u58f0\u8bfb\u7269, \u7535\u5b50\u4e66, EPUB, TTS, \u6587\u672c\u8f6c\u8bed\u97f3, EPUB\u8f6c\u6709\u58f0\u8bfb\u7269, \u7535\u5b50\u4e66\u8f6c\u6362, Audiobook Maker, TTS\u7535\u5b50\u4e66, \u795e\u7ecf\u8bed\u97f3, \u514d\u8d39\u6709\u58f0\u8bfb\u7269, \u65e0\u969c\u788d, \u89c6\u529b\u969c\u788d, \u8bfb\u5199\u56f0\u96be, \u64ad\u5ba2, RSS",
  ld:"\u514d\u8d39\u5728\u7ebf\u5de5\u5177\uff0c\u4f7f\u7528\u795e\u7ecf\u7f51\u7edcTTS\u8bed\u97f3\u5c06EPUB\u7535\u5b50\u4e66\u8f6c\u6362\u4e3a\u9ad8\u8d28\u91cf\u6709\u58f0\u8bfb\u7269\u3002"}
};
function applySEO(){
  const s=SEO[cl]||SEO.en;
  document.title=s.title;
  document.documentElement.lang=cl==='zh'?'zh-CN':cl;
  document.getElementById('metaDesc').setAttribute('content',s.desc);
  document.getElementById('metaKw').setAttribute('content',s.kw);
  document.getElementById('ogTitle').setAttribute('content',s.title);
  document.getElementById('ogDesc').setAttribute('content',s.desc);
  document.getElementById('twTitle').setAttribute('content',s.title);
  document.getElementById('twDesc').setAttribute('content',s.desc);
  try{
    const ld=JSON.parse(document.getElementById('jsonLd').textContent);
    ld.name=s.title.split('\u2014')[0].trim();
    ld.description=s.ld;
    document.getElementById('jsonLd').textContent=JSON.stringify(ld);
  }catch(e){}
}

// ═══════════════════ ACTIVE JOBS MONITOR ═══════════════════
let _monTimer=null;
function openMonitor(){
  document.getElementById('monModal').classList.add('open');
  _fetchMonitor();
  _monTimer=setInterval(_fetchMonitor,5000);
}
function closeMonitor(){
  document.getElementById('monModal').classList.remove('open');
  if(_monTimer){clearInterval(_monTimer);_monTimer=null}
}
function _fetchMonitor(){
  fetch('/api/active_jobs').then(r=>r.json()).then(d=>{
    const body=document.getElementById('monBody');
    if(!d.jobs||d.jobs.length===0){
      body.innerHTML='<div style="text-align:center;padding:24px;color:#999;font-size:.95rem">Nessuna generazione in corso</div>';
      document.getElementById('monTitle').textContent='Active Jobs';
      return;
    }
    document.getElementById('monTitle').textContent='Active Jobs ('+d.count+')';
    let h='<table style="width:100%;border-collapse:collapse;font-size:.9rem">';
    h+='<thead><tr style="background:var(--s2,#f0f5fa)">';
    h+='<th style="padding:8px 10px;text-align:left;font-weight:600;border-bottom:2px solid var(--brd,#ddd)">Inizio</th>';
    h+='<th style="padding:8px 10px;text-align:left;font-weight:600;border-bottom:2px solid var(--brd,#ddd)">Titolo</th>';
    h+='<th style="padding:8px 10px;text-align:center;font-weight:600;border-bottom:2px solid var(--brd,#ddd)">Progresso</th>';
    h+='</tr></thead><tbody>';
    d.jobs.forEach(j=>{
      const pct=j.total>0?Math.round(j.progress/j.total*100):0;
      h+='<tr>';
      h+='<td style="padding:8px 10px;border-bottom:1px solid var(--brd,#eee);white-space:nowrap;font-family:monospace;font-size:.82rem;color:#888">'+esc(j.started)+'</td>';
      h+='<td style="padding:8px 10px;border-bottom:1px solid var(--brd,#eee)">';
      h+='<div style="font-weight:600">'+esc(j.title)+'</div>';
      if(j.chapter)h+='<div style="font-size:.8rem;color:#999;margin-top:2px">'+esc(j.chapter)+'</div>';
      h+='</td>';
      h+='<td style="padding:8px 10px;border-bottom:1px solid var(--brd,#eee);text-align:center">';
      if(j.status==='generating'){
        h+='<div style="background:var(--brd,#e5e7eb);border-radius:6px;height:8px;width:80px;display:inline-block;vertical-align:middle;overflow:hidden">';
        h+='<div style="background:var(--ac,#2563eb);height:100%;width:'+pct+'%;border-radius:6px;transition:width .5s"></div></div>';
        h+=' <span style="font-size:.8rem;color:#888;margin-left:4px">'+pct+'%</span>';
      } else {
        h+='<span style="font-size:.8rem;color:#aaa">'+esc(j.status)+'</span>';
      }
      h+='</td></tr>';
    });
    h+='</tbody></table>';
    body.innerHTML=h;
  }).catch(()=>{
    document.getElementById('monBody').innerHTML='<div style="text-align:center;padding:20px;color:#c00">Errore di connessione</div>';
  });
}

document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeFreeBooks();closePodcastGuide();closeMonitor();document.getElementById('aboutModal').classList.remove('open');document.getElementById('emailModal').classList.remove('open')}});

let cl='en';
function t(k){return(L[cl]||L.en)[k]||(L.en)[k]||k}
function applyI18n(){
  document.querySelectorAll('[data-t]').forEach(e=>{
    const k=e.getAttribute('data-t'),v=t(k);
    if(e.tagName==='OPTION')e.textContent=v;
    else e.textContent=v;
  });
  document.querySelectorAll('.lsw button').forEach(b=>b.classList.toggle('on',b.dataset.l===cl));
  document.documentElement.lang=cl;
}
function setLang(l){cl=l;applyI18n();buildAbout();applySEO();try{localStorage.setItem('abm_l',l)}catch(e){}}
function detectLang(){
  try{const s=localStorage.getItem('abm_l');if(s&&L[s])return s}catch(e){}
  const n=(navigator.language||navigator.userLanguage||'en').toLowerCase().split('-')[0];
  return L[n]?n:'en';
}

// ═══════════════════ STATE ═══════════════════
let voices={},bookData=null,jobId=null,singleFile=true,generating=false,jobDone=false,hbInterval=null,isTxtFile=false,emailPromptShown=false,emailRegistered=false,emailCheckTimer=null,smtpAvailable=false;

// ═══════════════════ THEME ═══════════════════
function detectTheme(){
  try{const s=localStorage.getItem('abm_th');if(s)return s}catch(e){}
  return window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';
}
function applyTheme(th){
  if(th==='dark'){document.documentElement.setAttribute('data-theme','dark');document.getElementById('themeBtn').textContent='\\u2600\\ufe0f'}
  else{document.documentElement.removeAttribute('data-theme');document.getElementById('themeBtn').textContent='\U0001F319'}
  try{localStorage.setItem('abm_th',th)}catch(e){}
}
function toggleTheme(){
  const cur=document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';
  applyTheme(cur);
}

// ═══════════════════ INIT ═══════════════════
document.addEventListener('DOMContentLoaded',()=>{
  applyTheme(detectTheme());
  cl=detectLang();applyI18n();buildAbout();applySEO();
  document.getElementById('lsw').onclick=e=>{if(e.target.dataset.l)setLang(e.target.dataset.l)};
  document.getElementById('themeBtn').onclick=toggleTheme;
  document.getElementById('fbBtn').onclick=openFreeBooks;
  document.getElementById('fbClose').onclick=closeFreeBooks;
  document.getElementById('fbModal').onclick=e=>{if(e.target===e.currentTarget)closeFreeBooks()};
  document.getElementById('pgBtn').onclick=openPodcastGuide;
  document.getElementById('pgClose').onclick=closePodcastGuide;
  document.getElementById('pgModal').onclick=e=>{if(e.target===e.currentTarget)closePodcastGuide()};
  document.getElementById('aboutBtn').onclick=e=>{e.preventDefault();openAbout()};
  document.getElementById('aboutClose').onclick=()=>document.getElementById('aboutModal').classList.remove('open');
  document.getElementById('aboutModal').onclick=e=>{if(e.target===e.currentTarget)e.target.classList.remove('open')};
  // Monitor modal handlers
  document.getElementById('monClose').onclick=closeMonitor;
  document.getElementById('monModal').onclick=e=>{if(e.target===e.currentTarget)closeMonitor()};
  // Email modal handlers
  document.getElementById('emSubmit').onclick=submitEmail;
  document.getElementById('emSkip').onclick=skipEmail;
  document.getElementById('emClose').onclick=skipEmail;
  document.getElementById('emailModal').onclick=e=>{if(e.target===e.currentTarget)skipEmail()};
  setupUpload();loadVoices();
  document.getElementById('btnG').onclick=startGen;
  document.getElementById('btnD').onclick=downloadFile;
  document.getElementById('btnP').onclick=downloadPodcast;
  document.getElementById('btnN').onclick=resetAll;
  document.getElementById('btnC').onclick=cancelJob;
  window.addEventListener('beforeunload',onBeforeUnload);
  document.getElementById('toS').onclick=function(){toggleOut(this)};
  document.getElementById('toC').onclick=function(){toggleOut(this)};
  // Chapter selection handlers
  document.getElementById('selAll').onclick=chSelAll;
  document.getElementById('selNone').onclick=chSelNone;
  document.getElementById('selInv').onclick=chSelInvert;
  document.getElementById('chAll').onchange=chMasterToggle;
});

function toggleOut(el){
  document.querySelectorAll('.tg button').forEach(b=>b.classList.remove('on'));
  el.classList.add('on');singleFile=el.dataset.v==='single';
  document.getElementById('podHint').style.display=singleFile?'none':'';
  // Show/hide chapter selection UI
  const show=!singleFile;
  document.getElementById('thSel').style.display=show?'':'none';
  document.querySelectorAll('#chl .col-sel').forEach(td=>td.style.display=show?'':'none');
  document.querySelectorAll('#chl tr').forEach(tr=>tr.style.cursor=show?'pointer':'');
  document.getElementById('selBar').classList.toggle('vis',show);
  if(show){updateSelection()}
  else if(bookData){
    // Restore full summary counts
    document.getElementById('smC').textContent=bookData.total_chapters;
    document.getElementById('smW').textContent=bookData.total_words.toLocaleString();
    document.getElementById('smD').textContent=fmtDur(bookData.estimated_minutes);
    document.getElementById('btnG').disabled=false;
  }
}

// ═══════════════════ UPLOAD + LOCK ═══════════════════
function setupUpload(){
  const z=document.getElementById('uz'),fi=document.getElementById('fi');
  z.onclick=()=>{if(!generating&&!jobDone)fi.click()};
  ['dragenter','dragover'].forEach(e=>z.addEventListener(e,ev=>{ev.preventDefault();if(!generating&&!jobDone)z.classList.add('dg')}));
  ['dragleave','drop'].forEach(e=>z.addEventListener(e,ev=>{ev.preventDefault();z.classList.remove('dg')}));
  z.addEventListener('drop',ev=>{if(generating||jobDone)return;const f=ev.dataTransfer.files;if(f.length)handleFile(f[0])});
  fi.addEventListener('change',()=>{if(!generating&&!jobDone&&fi.files.length)handleFile(fi.files[0])});
}

// ═══════════════════ ACCORDION ═══════════════════
function toggleStep(id){
  const el=document.getElementById(id);
  if(el.classList.contains('disabled')||el.classList.contains('locked'))return;
  el.classList.toggle('collapsed');
  if(!el.classList.contains('collapsed')){
    setTimeout(()=>el.scrollIntoView({behavior:'smooth',block:'nearest'}),100);
  }
}
function activateStep(id){
  const el=document.getElementById(id);
  el.classList.remove('collapsed','disabled');
  el.style.display='';
  setTimeout(()=>el.scrollIntoView({behavior:'smooth',block:'nearest'}),150);
}
function collapseStep(id){document.getElementById(id).classList.add('collapsed')}
function disableStep(id){const el=document.getElementById(id);el.classList.add('collapsed','disabled')}

function lockUI(){
  generating=true;
  ['s1','s2','s3'].forEach(id=>{const el=document.getElementById(id);el.classList.add('locked','collapsed','done')});
  document.getElementById('fi').disabled=true;
}
function unlockUI(){
  generating=false;
  ['s1','s2','s3'].forEach(id=>document.getElementById(id).classList.remove('locked'));
  document.getElementById('fi').disabled=false;
}

function handleFile(file){
  if(generating||jobDone)return;
  const fn=file.name.toLowerCase();
  if(!fn.endsWith('.epub')&&!fn.endsWith('.txt')){showErr('aerr',t('err_epub'));return}
  document.getElementById('uz').classList.add('ok');
  document.getElementById('ufn').textContent='\\u2713 '+file.name;
  document.getElementById('ufn').style.display='block';
  document.getElementById('s1sum').textContent='\\u2713 '+file.name;
  document.getElementById('utx').textContent=t('upload_ok');
  document.getElementById('aerr').innerHTML='';
  analyzeEpub(file);
}

async function analyzeEpub(file){
  const lo=document.getElementById('alo');lo.classList.add('vis');
  disableStep('s2');disableStep('s3');
  const fd=new FormData();fd.append('epub',file);
  try{
    const r=await fetch('/api/analyze',{method:'POST',body:fd});
    const d=await r.json();
    if(d.error){showErr('aerr',d.error);lo.classList.remove('vis');return}
    bookData=d;jobId=d.job_id;lo.classList.remove('vis');
    isTxtFile=(d.file_type==='txt');
    if(d.language){
      const lc=d.language.split('-')[0].toLowerCase();
      const sel=document.getElementById('vl');
      if(sel.querySelector('option[value="'+lc+'"]')){sel.value=lc;updVoices()}
    }
    // Set output mode based on file type
    if(isTxtFile){
      // TXT: force single file, hide output toggle and chapter table
      toggleOut(document.getElementById('toS'));
      document.getElementById('fgOut').style.display='none';
    }else{
      // EPUB: default to chapters mode
      document.getElementById('fgOut').style.display='';
      toggleOut(document.getElementById('toC'));
    }
    fillPreview(d);
    collapseStep('s1');document.getElementById('s1').classList.add('done');
    activateStep('s2');
    if(!isTxtFile)activateStep('s3');
    else{
      // TXT single chapter: skip step 3 preview, go straight to generate from s2
      activateStep('s3');
    }
  }catch(e){showErr('aerr','Error: '+e.message);lo.classList.remove('vis')}
}

// ═══════════════════ VOICES ═══════════════════
async function loadVoices(){
  try{const r=await fetch('/api/voices');voices=await r.json();fillLangs()}catch(e){console.error(e)}
}
function fillLangs(){
  const sel=document.getElementById('vl');sel.innerHTML='';
  for(const[c,l]of Object.entries(voices)){
    const o=document.createElement('option');o.value=c;o.textContent=l.name+' ('+l.voices.length+')';sel.appendChild(o);
  }
  sel.onchange=updVoices;
  if(voices.it)sel.value='it';
  updVoices();
}
function updVoices(){
  const lc=document.getElementById('vl').value,sel=document.getElementById('vv');sel.innerHTML='';
  if(!voices[lc])return;
  const lang=voices[lc];let lg='';
  for(const v of lang.voices){
    if(v.gender!==lg){const g=document.createElement('optgroup');g.label=v.gender==='Female'?'\\u2640':'\\u2642';sel.appendChild(g);lg=v.gender}
    const o=document.createElement('option');o.value=v.id;o.textContent=v.gender_icon+' '+v.name+' ('+v.locale+')';
    sel.lastElementChild.appendChild(o);
  }
  const dv=lang.voices.find(v=>v.id.includes('Giuseppe')||v.id.includes('Guy')||v.id.includes('Davis'))||lang.voices[0];
  if(dv)sel.value=dv.id;
}

// ═══════════════════ PREVIEW ═══════════════════
function fillPreview(d){
  document.getElementById('bkT').textContent=d.title;
  document.getElementById('bkA').textContent=d.author?(t('by')+' '+d.author):'';
  // Cover image
  const coverImg=document.getElementById('bkCover');
  console.log('[cover] has_cover='+d.has_cover+', job_id='+d.job_id);
  if(d.has_cover&&d.job_id){
    coverImg.src='/api/cover/'+d.job_id;
    coverImg.style.display='';
    coverImg.onload=function(){console.log('[cover] loaded OK: '+this.naturalWidth+'x'+this.naturalHeight)};
    coverImg.onerror=function(){console.log('[cover] load FAILED');this.style.display='none'};
  }else{coverImg.style.display='none';coverImg.src=''}
  document.getElementById('smC').textContent=d.total_chapters;
  document.getElementById('smW').textContent=d.total_words.toLocaleString();
  document.getElementById('smCh').textContent=d.total_chars.toLocaleString();
  document.getElementById('smD').textContent=fmtDur(d.estimated_minutes);
  document.getElementById('selTot').textContent=d.total_chapters;
  const tb=document.getElementById('chl');tb.innerHTML='';
  for(const ch of d.chapters){
    const tr=document.createElement('tr');
    tr.dataset.idx=ch.index;
    tr.dataset.words=ch.words;
    tr.dataset.chars=ch.chars;
    tr.dataset.mins=ch.estimated_minutes;
    const selTd=document.createElement('td');
    selTd.className='col-sel';
    selTd.style.display=singleFile?'none':'';
    const cb=document.createElement('input');
    cb.type='checkbox';cb.checked=true;cb.dataset.idx=ch.index;
    cb.addEventListener('change',()=>{tr.classList.toggle('unchecked',!cb.checked);updateSelection()});
    selTd.appendChild(cb);
    tr.innerHTML='<td><span class="cn">'+ch.index+'.</span>'+esc(ch.title.substring(0,60))+'</td><td>'+ch.words.toLocaleString()+'</td><td>'+fmtDur(ch.estimated_minutes)+'</td>';
    tr.insertBefore(selTd,tr.firstChild);
    tr.style.cursor=singleFile?'':'pointer';
    tr.addEventListener('click',e=>{if(singleFile||e.target.tagName==='INPUT')return;cb.checked=!cb.checked;tr.classList.toggle('unchecked',!cb.checked);updateSelection()});
    tb.appendChild(tr);
  }
  // Master checkbox
  document.getElementById('chAll').checked=true;
  updateSelection();
  document.getElementById('s3sum').textContent=d.title.substring(0,25)+(d.title.length>25?'..':'')+' \u2014 '+d.total_chapters+' cap., '+d.total_words.toLocaleString()+' '+t('sum_w').toLowerCase();
}

function updateSelection(){
  const boxes=document.querySelectorAll('#chl .col-sel input[type=checkbox]');
  let cnt=0,words=0,chars=0,mins=0;
  boxes.forEach(cb=>{
    if(cb.checked){cnt++;const tr=cb.closest('tr');words+=parseInt(tr.dataset.words||0);chars+=parseInt(tr.dataset.chars||0);mins+=parseFloat(tr.dataset.mins||0)}
  });
  document.getElementById('selCnt').textContent=cnt;
  // Update summary to reflect selection
  if(!singleFile){
    document.getElementById('smC').textContent=cnt+' / '+(bookData?bookData.total_chapters:boxes.length);
    document.getElementById('smW').textContent=words.toLocaleString();
    document.getElementById('smCh').textContent=chars.toLocaleString();
    document.getElementById('smD').textContent=fmtDur(mins);
  }
  // Master checkbox state
  const all=boxes.length;
  const master=document.getElementById('chAll');
  master.checked=cnt===all;
  master.indeterminate=cnt>0&&cnt<all;
  // Disable generate if none selected and in chapter mode
  document.getElementById('btnG').disabled=(!singleFile&&cnt===0);
}

function chSelAll(){document.querySelectorAll('#chl .col-sel input[type=checkbox]').forEach(cb=>{cb.checked=true;cb.closest('tr').classList.remove('unchecked')});updateSelection()}
function chSelNone(){document.querySelectorAll('#chl .col-sel input[type=checkbox]').forEach(cb=>{cb.checked=false;cb.closest('tr').classList.add('unchecked')});updateSelection()}
function chSelInvert(){document.querySelectorAll('#chl .col-sel input[type=checkbox]').forEach(cb=>{cb.checked=!cb.checked;cb.closest('tr').classList.toggle('unchecked',!cb.checked)});updateSelection()}
function chMasterToggle(){const v=document.getElementById('chAll').checked;document.querySelectorAll('#chl .col-sel input[type=checkbox]').forEach(cb=>{cb.checked=v;cb.closest('tr').classList.toggle('unchecked',!v)});updateSelection()}

// ═══════════════════ GENERATION ═══════════════════
async function startGen(){
  // Collect selected chapter indices when in chapter mode
  let selectedChapters=null;
  if(!singleFile){
    selectedChapters=[];
    document.querySelectorAll('#chl .col-sel input[type=checkbox]').forEach(cb=>{
      if(cb.checked)selectedChapters.push(parseInt(cb.dataset.idx));
    });
    if(selectedChapters.length===0){showErr('s3err',t('sel_err_none'));return}
  }
  document.getElementById('s3err').innerHTML='';
  document.getElementById('btnG').disabled=true;
  // Set s2 summary for collapsed state
  const vSel=document.getElementById('vv');
  const vName=vSel.options[vSel.selectedIndex]?vSel.options[vSel.selectedIndex].text:'';
  const rSel=document.getElementById('vr');
  const rName=rSel.options[rSel.selectedIndex]?rSel.options[rSel.selectedIndex].text:'';
  document.getElementById('s2sum').textContent=vName+' \u2014 '+rName;
  lockUI();
  const s4=document.getElementById('s4');s4.style.display='';s4.classList.remove('collapsed');s4.classList.add('fi');
  if(bookData){document.getElementById('s4bkT').textContent=bookData.title||'';document.getElementById('s4bkA').textContent=bookData.author?(t('by')+' '+bookData.author):'';var sc=document.getElementById('s4bkCover'),s3c=document.getElementById('bkCover');if(s3c.src&&s3c.style.display!=='none'){sc.src=s3c.src;sc.style.display='';sc.onerror=function(){this.style.display='none'}}else{sc.style.display='none';sc.src=''}}
  document.getElementById('pMsg').textContent=t('starting');
  setTimeout(()=>s4.scrollIntoView({behavior:'smooth',block:'nearest'}),200);
  try{
    const payload={job_id:jobId,voice:document.getElementById('vv').value,rate:document.getElementById('vr').value,single_file:singleFile};
    if(selectedChapters)payload.selected_chapters=selectedChapters;
    const r=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)});
    const d=await r.json();
    if(d.error){showPErr(d.error);unlockUI();return}
    listenProgress();
  }catch(e){showPErr('Error: '+e.message);unlockUI()}
}

function listenProgress(){
  let retries=0;
  const maxRetries=5;
  function connect(){
    const es=new EventSource('/api/progress/'+jobId);
    es.onmessage=ev=>{
      retries=0;  // Reset su messaggio ricevuto
      const d=JSON.parse(ev.data);
      if(d.status==='error'){es.close();showPErr(d.error);unlockUI();generating=false;document.getElementById('cnA').style.display='none';document.getElementById('emailModal').classList.remove('open');return}
      if(d.status==='cancelled'){es.close();document.getElementById('pMsg').textContent=t('cancelled_msg');document.getElementById('pMsg').style.color='var(--err)';document.getElementById('cnA').style.display='none';document.getElementById('emailModal').classList.remove('open');unlockUI();generating=false;return}

      const pct=d.progress_total>0?Math.round(d.progress_current/d.progress_total*100):0;
      document.getElementById('pPct').textContent=pct+'%';
      document.getElementById('pBar').style.width=pct+'%';
      document.getElementById('pMsg').textContent=d.progress_message||'';

      if(d.current_chapter)
        document.getElementById('pCh').textContent='Cap. '+d.current_chapter_num+'/'+d.total_chapters+': '+d.current_chapter.substring(0,40);
      if(d.progress_total>0)
        document.getElementById('xBlk').textContent=d.progress_current+' / '+d.progress_total;
      if(d.total_chapters>0)
        document.getElementById('xCh').textContent=d.current_chapter_num+' / '+d.total_chapters;
      if(d.elapsed_seconds>0)
        document.getElementById('xEl').textContent=fmtTime(d.elapsed_seconds);

      // ETA basata su chars/sec reale
      if(d.processed_chars>0&&d.elapsed_seconds>1&&d.total_chars>0){
        const cps=d.processed_chars/d.elapsed_seconds;
        const left=d.total_chars-d.processed_chars;
        const eta=Math.round(left/cps);
        document.getElementById('xEta').textContent=eta>0?'~'+fmtTime(eta):t('almost');
        document.getElementById('xSpd').textContent=Math.round(cps)+' '+t('cps');
        // Email prompt: after 60s elapsed, ETA > 10min, chapter mode, SMTP available
        if(!emailPromptShown&&!emailRegistered&&smtpAvailable&&d.elapsed_seconds>=30&&(d.elapsed_seconds+eta)>180){
          emailPromptShown=true;
          showEmailModal();
        }
      }
      if(d.bytes_generated>0)
        document.getElementById('xSz').textContent=fmtBytes(d.bytes_generated);

      if(d.status==='done'){
        es.close();
        generating=false;
        jobDone=true;
        document.getElementById('pPct').textContent='100%';
        document.getElementById('pBar').style.width='100%';
        document.getElementById('pMsg').textContent=t('done_msg');
        document.getElementById('pMsg').style.color='var(--ok)';
        if(d.failed_chunks>0){
          document.getElementById('pMsg').textContent=t('done_msg')+' (⚠ '+d.failed_chunks+' chunk skipped)';
          document.getElementById('pMsg').style.color='#d97706';
        }
        document.getElementById('xEta').textContent='-';
        document.getElementById('dlA').style.display='block';
        document.getElementById('dlA').classList.add('fi');
        document.getElementById('btnP').style.display=d.has_podcast?'':'none';
        document.getElementById('s4t').textContent=t('done_t');
        document.getElementById('cnA').style.display='none';
        document.getElementById('emailModal').classList.remove('open');
        // Heartbeat: segnala al server che il client è ancora sulla pagina
        hbInterval=setInterval(()=>{if(jobId)navigator.sendBeacon('/api/heartbeat/'+jobId)},10000);
        // Manda subito il primo heartbeat (evita gap iniziale)
        if(jobId)navigator.sendBeacon('/api/heartbeat/'+jobId);
        // Heartbeat extra quando la tab torna in primo piano
        // (Chrome throttla setInterval in background, ma visibilitychange NO)
        document._hbVis=()=>{if(!document.hidden&&jobId&&jobDone)navigator.sendBeacon('/api/heartbeat/'+jobId)};
        document.addEventListener('visibilitychange',document._hbVis);
        // UI resta locked fino a "nuovo"
      }
    };
    es.onerror=()=>{
      es.close();
      if(retries<maxRetries&&generating){
        retries++;
        // Riconnessione progressiva: 2s, 4s, 6s, 8s, 10s
        setTimeout(connect,retries*2000);
      }
    };
  }
  connect();
}

function cancelJob(){
  if(!jobId||!generating)return;
  navigator.sendBeacon('/api/cancel/'+jobId+'?force=1');
  location.reload();
}

// ═══════════════════ EMAIL NOTIFICATION ═══════════════════
function showEmailModal(){
  const m=document.getElementById('emailModal');
  document.getElementById('emTitle').textContent='📧 '+t('email_title');
  document.getElementById('emDesc').textContent=t('email_desc');
  document.getElementById('emDlLabel').textContent=t('email_dl_type');
  document.getElementById('emDlAudioL').textContent=t('email_dl_audio');
  document.getElementById('emDlPodcastL').textContent=t('email_dl_podcast');
  document.getElementById('emBaseUrlLabel').textContent=t('email_base_url');
  document.getElementById('emEmail').placeholder=t('email_placeholder');
  document.getElementById('emSubmit').textContent=t('email_btn');
  document.getElementById('emSkip').textContent=t('email_skip');
  document.getElementById('emErr').style.display='none';
  document.getElementById('emOk').style.display='none';
  document.getElementById('emBtns').style.display='flex';
  document.getElementById('emDlType').style.display=singleFile?'none':'';
  document.getElementById('emBaseUrlWrap').style.display='none';
  // Reset radio to "audio" every time modal opens
  document.querySelectorAll('input[name="emDl"]').forEach((r,i)=>{r.checked=i===0});
  // Radio change: show/hide base URL field
  document.querySelectorAll('input[name="emDl"]').forEach(r=>{
    r.onchange=()=>{
      document.getElementById('emBaseUrlWrap').style.display=
        document.querySelector('input[name="emDl"]:checked').value==='podcast'?'':'none';
    };
  });
  m.classList.add('open');
}

async function submitEmail(){
  const email=document.getElementById('emEmail').value.trim();
  const errEl=document.getElementById('emErr');
  errEl.style.display='none';
  // Validate email client-side
  if(!email||!/^[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}$/.test(email)){
    errEl.textContent=t('email_invalid');errEl.style.display='block';return;
  }
  const dlType=document.querySelector('input[name="emDl"]:checked').value;
  const baseUrl=document.getElementById('emBaseUrl').value.trim();
  if(dlType==='podcast'&&!baseUrl){
    errEl.textContent=t('email_base_url');errEl.style.display='block';return;
  }
  try{
    const r=await fetch('/api/register_email',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({job_id:jobId,email:email,download_type:dlType,base_url:baseUrl,lang:cl})});
    const d=await r.json();
    if(d.error){
      errEl.textContent=d.error==='Email service not configured on this server'?t('email_unavail'):d.error;
      errEl.style.display='block';return;
    }
    emailRegistered=true;
    document.getElementById('emBtns').style.display='none';
    document.getElementById('emDlType').style.display='none';
    document.getElementById('emBaseUrlWrap').style.display='none';
    document.getElementById('emEmail').style.display='none';
    document.getElementById('emDesc').style.display='none';
    document.getElementById('emOk').textContent=t('email_ok');
    document.getElementById('emOk').style.display='block';
    // Show inline status indicator in step 4
    document.getElementById('emailStatusText').textContent=t('email_ok');
    document.getElementById('emailStatus').style.display='block';
    // Auto-close after 5 seconds
    setTimeout(()=>{document.getElementById('emailModal').classList.remove('open')},5000);
  }catch(e){errEl.textContent='Error: '+e.message;errEl.style.display='block'}
}

function skipEmail(){
  document.getElementById('emailModal').classList.remove('open');
}

// Check SMTP availability on page load
async function checkSmtp(){
  try{
    const r=await fetch('/api/email_available');
    const d=await r.json();
    smtpAvailable=d.available===true;
  }catch(e){smtpAvailable=false}
}
checkSmtp();

async function downloadFile(){
  if(!jobId)return;
  const btn=document.getElementById('btnD');
  btn.disabled=true;btn.textContent='⏳...';
  const maxDlRetries=3;
  for(let attempt=1;attempt<=maxDlRetries;attempt++){
    try{
      // Heartbeat prima del download (assicura che il job sia ancora vivo)
      navigator.sendBeacon('/api/heartbeat/'+jobId);
      const r=await fetch('/api/download/'+jobId);
      if(r.status===404){
        if(attempt<maxDlRetries){await new Promise(ok=>setTimeout(ok,1500));continue}
        showPErr(t('dl_expired')||'File non più disponibile. Riconverti il libro.');
        btn.disabled=false;btn.innerHTML='\\u2B07\\uFE0F <span data-t="btn_dl">'+t('btn_dl')+'</span>';
        return;
      }
      if(!r.ok){
        const txt=await r.text();
        showPErr(txt||'Download failed');
        btn.disabled=false;btn.innerHTML='\\u2B07\\uFE0F <span data-t="btn_dl">'+t('btn_dl')+'</span>';
        return;
      }
      const blob=await r.blob();
      const cd=r.headers.get('Content-Disposition')||'';
      const m=cd.match(/filename[^;=\\n]*=['"]?([^'";\\n]*)/);
      const fname=m?m[1]:'audiobook.mp3';
      const a=document.createElement('a');
      a.href=URL.createObjectURL(blob);
      a.download=fname;
      document.body.appendChild(a);a.click();
      setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},1000);
      btn.innerHTML='\\u2705 <span data-t="btn_dl">'+t('btn_dl')+'</span>';
      btn.disabled=false;
      return;
    }catch(e){
      if(attempt<maxDlRetries){await new Promise(ok=>setTimeout(ok,1500));continue}
      showPErr('Download error: '+e.message);
      btn.disabled=false;btn.innerHTML='\\u2B07\\uFE0F <span data-t="btn_dl">'+t('btn_dl')+'</span>';
    }
  }
}

async function downloadPodcast(){
  if(!jobId)return;
  const baseUrl=prompt(t('podcast_url_prompt'),'https://example.com/podcast');
  if(!baseUrl)return;
  const btn=document.getElementById('btnP');
  btn.disabled=true;btn.textContent='\\u23F3...';
  try{
    navigator.sendBeacon('/api/heartbeat/'+jobId);
    const r=await fetch('/api/download_podcast/'+jobId+'?base_url='+encodeURIComponent(baseUrl));
    if(!r.ok){
      const txt=await r.text();
      showPErr(txt||'Download failed');
      btn.disabled=false;btn.innerHTML='\\uD83C\\uDF99\\uFE0F <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';
      return;
    }
    const blob=await r.blob();
    const cd=r.headers.get('Content-Disposition')||'';
    const m=cd.match(/filename[^;=\\n]*=['"]?([^'";\\n]*)/);
    const fname=m?m[1]:'podcast.zip';
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download=fname;
    document.body.appendChild(a);a.click();
    setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},1000);
    btn.innerHTML='\\u2705 <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';
    btn.disabled=false;
  }catch(e){
    showPErr('Download error: '+e.message);
    btn.disabled=false;btn.innerHTML='\\uD83C\\uDF99\\uFE0F <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';
  }
}

function onBeforeUnload(e){
  if(generating&&!jobDone&&jobId&&!emailRegistered){
    // Cancel solo se la generazione è in corso E l'utente NON ha registrato email
    navigator.sendBeacon('/api/cancel/'+jobId);
  }
}

function resetAll(){
  if(hbInterval){clearInterval(hbInterval);hbInterval=null}
  if(document._hbVis){document.removeEventListener('visibilitychange',document._hbVis);document._hbVis=null}
  generating=false;
  jobDone=false;
  unlockUI();
  document.getElementById('s4').style.display='none';
  // Accordion: s1 open, s2+s3 disabled collapsed
  document.getElementById('s1').classList.remove('collapsed','disabled','done');
  disableStep('s2');disableStep('s3');
  ['s2','s3'].forEach(id=>document.getElementById(id).classList.remove('done'));
  document.getElementById('dlA').style.display='none';
  document.getElementById('btnP').style.display='none';
  document.getElementById('podHint').style.display='none';
  document.getElementById('cnA').style.display='';
  document.getElementById('btnG').disabled=false;
  document.getElementById('pBar').style.width='0%';
  document.getElementById('pPct').textContent='0%';
  document.getElementById('pMsg').style.color='';
  ['xBlk','xCh','xEl','xEta','xSz','xSpd'].forEach(id=>document.getElementById(id).textContent='-');
  document.getElementById('uz').classList.remove('ok');
  document.getElementById('ufn').style.display='none';
  document.getElementById('fi').value='';
  document.getElementById('chl').innerHTML='';
  document.getElementById('s3err').innerHTML='';
  document.getElementById('selBar').classList.remove('vis');
  document.getElementById('thSel').style.display='none';
  singleFile=true;isTxtFile=false;
  document.getElementById('fgOut').style.display='';
  document.querySelectorAll('.tg button').forEach(b=>b.classList.remove('on'));
  document.getElementById('toS').classList.add('on');
  bookData=null;jobId=null;
  emailPromptShown=false;emailRegistered=false;
  document.getElementById('emailModal').classList.remove('open');
  // Reset email modal fields
  document.getElementById('emEmail').value='';document.getElementById('emEmail').style.display='';
  document.getElementById('emBaseUrl').value='';
  document.getElementById('emDesc').style.display='';
  document.querySelectorAll('input[name="emDl"]').forEach((r,i)=>{r.checked=i===0});
  ['bkCover','s4bkCover'].forEach(id=>{var el=document.getElementById(id);el.style.display='none';el.src=''});
  ['s1sum','s2sum','s3sum'].forEach(id=>document.getElementById(id).textContent='');
  applyI18n();
  window.scrollTo({top:0,behavior:'smooth'});
}

// ═══════════════════ HELPERS ═══════════════════
function fmtDur(m){if(m<1)return'< 1 min';if(m<60)return Math.round(m)+' min';const h=Math.floor(m/60);const r=Math.round(m%60);return h+'h '+(r>0?r+'min':'')}
function fmtTime(s){if(s<60)return s+'s';const m=Math.floor(s/60);const r=s%60;if(m<60)return m+'m'+(r>0?' '+r+'s':'');return Math.floor(m/60)+'h '+(m%60>0?(m%60)+'m':'')}
function fmtBytes(b){if(b<1024)return b+' B';if(b<1048576)return(b/1024).toFixed(0)+' KB';return(b/1048576).toFixed(1)+' MB'}
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function showErr(id,m){document.getElementById(id).innerHTML='<div class="al al-e fi">'+esc(m)+'</div>'}
function showPErr(m){document.getElementById('pra').innerHTML='<div class="al al-e fi">'+esc(m)+'</div>'}
</script>
</body>
</html>
"""


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
    print(f"  Audiobook Maker")
    print(f"  http://localhost:{PORT}")
    print(f"{'='*50}")
    print(f"  Script folder: {SCRIPT_DIR}")
    print(f"  Data folder:   {UPLOAD_DIR}")
    print(f"  Activity log:  {SCRIPT_DIR / 'activity_YYYY-MM.log'}")
    print(f"{'='*50}\n")
    app.run(host="127.0.0.1", port=PORT, debug=False)
