"""
email_service.py — Infrastruttura email per Audiobook Maker.

Funzioni:
  - _smtp_available: verifica configurazione SMTP
  - _send_email: invio HTML email via SMTP
  - _admin_notify_generation: accodamento evento per digest admin
  - _try_send_admin_digest: invio digest se rate limit permette
  - _send_payment_receipt_email: ricevuta pagamento PayPal
  - _send_voucher_email: email buono rimborso

Dipende solo dalla stdlib e da os.environ — nessun import da audiobook_app.
"""

import os
import threading
import time

# ---------------------------------------------------------------------------
# SMTP config (letti da os.environ — stessa logica di audiobook_app.py)
# ---------------------------------------------------------------------------

SMTP_HOST = os.environ.get("ABM_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("ABM_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("ABM_SMTP_USER", "")
SMTP_PASS = os.environ.get("ABM_SMTP_PASS", "")
SMTP_FROM = os.environ.get("ABM_SMTP_FROM", os.environ.get("ABM_SMTP_USER", "") or "noreply@audiobook-maker.com")
BASE_URL = os.environ.get("ABM_BASE_URL", "").rstrip("/")

# ---------------------------------------------------------------------------
# Admin digest config
# ---------------------------------------------------------------------------

ADMIN_EMAIL = os.environ.get("ABM_ADMIN_EMAIL", "")
ADMIN_DIGEST_INTERVAL_SEC = 24 * 60 * 60  # 24 ore tra un digest e il successivo

_admin_queue = []          # list of dicts: {title, author, filename, voice, chapters, words, duration_est, timestamp}
_admin_queue_lock = threading.Lock()
_admin_last_sent = 0.0     # timestamp dell'ultimo digest inviato

# ---------------------------------------------------------------------------
# Payment email config — imported from payment.py (single source of truth)
# ---------------------------------------------------------------------------

from payment import VOUCHER_BONUS_PERCENT, VOUCHER_EXPIRY_DAYS


# ---------------------------------------------------------------------------
# Core SMTP functions
# ---------------------------------------------------------------------------

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
    # Disable TurboSMTP link/open tracking to avoid redirect issues
    msg["X-TurboSMTP-Tracking"] = "0"
    msg["X-SMTPAPI"] = '{"filters":{"clicktrack":{"settings":{"enable":0}},"opentrack":{"settings":{"enable":0}}}}'
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


# ---------------------------------------------------------------------------
# Admin activity digest
# ---------------------------------------------------------------------------

def _admin_notify_generation(job_id, info, voice, filename):
    """Queue a generation event for admin digest. Thread-safe."""
    if not ADMIN_EMAIL:
        return
    from datetime import datetime
    event = {
        "title": getattr(info, "title", "") or filename,
        "author": getattr(info, "author", "") or "\u2014",
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
    subject = f"\U0001f4da Audiobook Maker: {count} nuov{'o' if count == 1 else 'i'} libr{'o' if count == 1 else 'i'} in elaborazione"

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
<h2 style="margin:0">\U0001f3a7 Audiobook Maker \u2014 Activity Digest</h2>
<p style="margin:8px 0 0;opacity:.85">{count} elaborazion{'e' if count == 1 else 'i'} avviat{'a' if count == 1 else 'e'} \u2014 {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
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
<p style="color:#999;font-size:12px;margin-top:16px;padding:0 4px">Questo messaggio \u00e8 generato automaticamente da Audiobook Maker.
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


# ---------------------------------------------------------------------------
# Payment emails
# ---------------------------------------------------------------------------

def _send_payment_receipt_email(order_id, email, amount_eur, job):
    """Send payment receipt email to buyer."""
    book_title = ""
    info = job.get("info")
    if info:
        book_title = getattr(info, "title", "") or ""
    lang = job.get("browser_lang", "en")[:2] if job else "en"
    subj_map = {
        "it": f"Ricevuta pagamento Audiobook Maker \u2014 {amount_eur:.2f} EUR",
        "en": f"Audiobook Maker payment receipt \u2014 EUR {amount_eur:.2f}",
        "fr": f"Re\u00e7u de paiement Audiobook Maker \u2014 {amount_eur:.2f} EUR",
        "es": f"Recibo de pago Audiobook Maker \u2014 {amount_eur:.2f} EUR",
        "de": f"Zahlungsbeleg Audiobook Maker \u2014 {amount_eur:.2f} EUR",
        "zh": f"Audiobook Maker \u4ed8\u6b3e\u6536\u636e \u2014 {amount_eur:.2f} EUR",
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
  <p style="color:#999;font-size:12px">Audiobook Maker \u2014 {BASE_URL or ''}</p>
</div>"""
    _send_email(email, subject, html_body)


def _send_voucher_email(code, email, amount_eur, book_title):
    """Send voucher email after optimization failure."""
    if not (email and _smtp_available()):
        return
    from datetime import datetime, timedelta
    expiry = (datetime.now() + timedelta(days=VOUCHER_EXPIRY_DAYS)).strftime("%d/%m/%Y")
    subject = f"Audiobook Maker \u2014 Buono {amount_eur:.2f} EUR (ottimizzazione non riuscita)"
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
  <p style="font-size:.85em;color:#666">Il buono \u00e8 nominativo e riutilizzabile: se l'operazione costa meno del valore del buono, il saldo residuo rimane disponibile per usi successivi fino alla scadenza.</p>
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
  <p style="color:#999;font-size:12px">Audiobook Maker \u2014 {BASE_URL or ''}</p>
</div>"""
    _send_email(email, subject, html_body)
