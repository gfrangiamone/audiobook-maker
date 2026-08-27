"""
email_service.py — Infrastruttura email per Audiobook Maker.

Funzioni:
  - _smtp_available: verifica configurazione SMTP
  - _send_email: invio HTML email via SMTP
  - _admin_notify_generation: accodamento evento per digest admin
  - _try_send_admin_digest: invio digest se rate limit permette
  - _send_payment_receipt_email: ricevuta pagamento PayPal
  - _send_voucher_email: email buono rimborso (ottimizzazione testo AI)
  - _send_gemini_failed_refund_email: notifica fallimento generazione voci PREMIUM + rimborso

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

# Throttle anti-flood per admin failure alerts: chiave = f"{job_id}::{kind}"
_admin_failure_last = {}
_admin_failure_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Funnel provider hook (iniettato da audiobook_app — nessun import circolare)
# ---------------------------------------------------------------------------

_funnel_provider = None  # callable() -> dict | None, iniettato da audiobook_app


def set_funnel_provider(fn):
    global _funnel_provider
    _funnel_provider = fn


def _funnel_block_html():
    """Blocco HTML col funnel app->web->premium (ultimi 30gg). '' se non disponibile."""
    fn = _funnel_provider
    if not fn:
        return ""
    try:
        f = fn() or {}
    except Exception:
        return ""
    if not f:
        return ""
    ao = f.get("app_open", {}).get("total", 0)
    wv = f.get("web_visit_from_app", {}).get("total", 0)
    pay = f.get("payment_from_app", {}).get("total", 0)
    conv = round(f.get("conversion_rate", 0.0) * 100, 1)
    return (
        "<h3 style='margin:18px 0 6px'>Funnel app &rarr; web &rarr; premium (30gg)</h3>"
        f"<p style='margin:0'>App attive: <b>{ao}</b> &middot; Arrivi dall'app: <b>{wv}</b> "
        f"&middot; Pagamenti dall'app: <b>{pay}</b> &middot; Conversione: <b>{conv}%</b></p>"
    )


# ---------------------------------------------------------------------------
# Payment email config — imported from payment.py (single source of truth)
# ---------------------------------------------------------------------------

from payment import VOUCHER_BONUS_PERCENT, VOUCHER_EXPIRY_DAYS


# ---------------------------------------------------------------------------
# Core SMTP functions
# ---------------------------------------------------------------------------

def _smtp_available():
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS and BASE_URL)


def _sanitize_header(value, max_len=200):
    """Rimuove CR/LF da un valore di header per impedire SMTP header injection.

    Sec: alcuni chiamanti interpolano metadati controllati dall'utente
    (es. titolo EPUB nel Subject). Un newline non escapato consentirebbe di iniettare
    header come Bcc:, From:, ecc. usando il dominio mittente fidato (SPF/DKIM OK)
    per inviare phishing massivo.
    """
    if value is None:
        return ""
    s = str(value)
    # Rimuove ogni CR/LF e tabulazione iniziale (folding indicator)
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    # Tronca a una lunghezza ragionevole per evitare header gigante
    return s[:max_len].strip()


def _esc_html(value, max_len=None):
    """HTML-escape di un valore controllato dall'utente prima di interpolarlo nel
    CORPO HTML di un'email. `_sanitize_header` protegge solo gli header (CRLF) e
    NON escapa `<`/`>`: senza questo passaggio un titolo/autore/nome-file come
    `<a href="https://phish">…</a>` o `<img src="http://tracker">` verrebbe iniettato
    raw nella mailbox admin (content-spoofing/phishing, leak IP admin via img remota).
    Escapa `& < > " '`."""
    import html as _html
    if value is None:
        return ""
    s = str(value)
    if max_len is not None:
        s = s[:max_len]
    return _html.escape(s, quote=True)


def _send_email(to_addr, subject, html_body):
    """Send an HTML email via SMTP. Returns True on success."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    if not _smtp_available():
        print(f"[email] SMTP not configured, cannot send to {to_addr}", flush=True)
        return False

    # Sec: validazione difensiva degli header (CRLF injection)
    to_addr_clean = _sanitize_header(to_addr, max_len=320)
    subject_clean = _sanitize_header(subject, max_len=200)
    # Validazione di base sull'indirizzo destinatario (i chiamanti già filtrano con regex,
    # ma applichiamo un check di sicurezza centrale).
    import re as _re_email
    if not _re_email.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', to_addr_clean):
        print(f"[email] Refused invalid recipient: {to_addr_clean!r}", flush=True)
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_FROM
    msg["To"] = to_addr_clean
    msg["Subject"] = subject_clean
    # Disable TurboSMTP link/open tracking to avoid redirect issues
    msg["X-TurboSMTP-Tracking"] = "0"
    msg["X-SMTPAPI"] = '{"filters":{"clicktrack":{"settings":{"enable":0}},"opentrack":{"settings":{"enable":0}}}}'
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    print(f"[email] Connecting to {SMTP_HOST}:{SMTP_PORT} for {to_addr_clean}...", flush=True)
    t0 = time.time()
    # Non usiamo `with smtplib.SMTP(...) as server:` perché `__exit__` chiama
    # QUIT e ne attende la risposta: alcuni relay (TurboSMTP osservato 2026-05)
    # accettano il messaggio ma non rispondono al QUIT, lasciando il thread
    # bloccato senza che il timeout del socket scatti in modo affidabile.
    # Inviamo, poi chiudiamo il socket direttamente saltando QUIT.
    server = None
    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to_addr_clean, msg.as_string())
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
            server.ehlo()
            if SMTP_PORT != 25:
                server.starttls()
                server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to_addr_clean, msg.as_string())
        print(f"[email] Sent to {to_addr_clean} in {time.time()-t0:.1f}s: {subject_clean}", flush=True)
        return True
    except Exception as e:
        print(f"[email] Failed to send to {to_addr_clean} after {time.time()-t0:.1f}s: {type(e).__name__}: {e}", flush=True)
        return False
    finally:
        if server is not None:
            try:
                server.close()
            except Exception:
                pass


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
<td style="padding:8px 12px;border-bottom:1px solid #eee"><strong>{_esc_html(e['title'])}</strong><br>
<span style="color:#666;font-size:13px">{_esc_html(e['author'])}</span></td>
<td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:13px">{_esc_html(e['filename'])}</td>
<td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:center">{e['chapters']}</td>
<td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right">{e['words']:,}</td>
<td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:center">{e['duration_est']}</td>
<td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:12px;color:#888">{_esc_html(e['voice'])}</td>
</tr>"""

    funnel_block = _funnel_block_html()
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
{funnel_block}
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
        "hi": f"Audiobook Maker \u092d\u0941\u0917\u0924\u093e\u0928 \u0930\u0938\u0940\u0926 \u2014 {amount_eur:.2f} EUR",
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
        "hi": ("आपके भुगतान के लिए धन्यवाद.",
               f"राशि: <strong>EUR {amount_eur:.2f}</strong><br>लेन-देन ID: <code>{order_id}</code>"
               f"<br>परियोजना: <strong>{book_title}</strong>",
               "यह भुगतान वाक् संश्लेषण के लिए AI टेक्स्ट अनुकूलन को कवर करता है. "
               "इस ईमेल को रसीद के रूप में रखें. चालान के लिए हमसे संपर्क करें.",
               f"यदि अनुकूलन विफल हो जाता है, तो आपको {VOUCHER_BONUS_PERCENT}% अधिक मूल्य का कूपन मिलेगा, "
               f"जो {VOUCHER_EXPIRY_DAYS} दिनों के लिए मान्य है."),
    }
    heading, details, info_txt, refund = body_map.get(lang, body_map["en"])
    # Blocco consegna: rende esplicito SU QUALE indirizzo arrivera' il link di
    # download. Il job pagato passa in batch implicito sull'email del pagamento
    # (vedi api_paypal_capture -> job["notify_email"]), che puo' essere diversa
    # da quella che l'utente si aspetta di controllare: senza questa riga la
    # notifica finisce su una casella che non guarda ("email mai ricevuta").
    # Destinatario reale della notifica: l'email eventualmente gia' registrata
    # dall'utente ha la precedenza sull'email del pagamento (stessa priorita' di
    # api_paypal_capture / api_register_email).
    dest = ((job.get("notify_email") or "").strip() if job else "") or email
    delivery_map = {
        "it": (f"Il link per scaricare il risultato verr&agrave; inviato a "
               f"<strong>{dest}</strong> al termine della lavorazione. "
               f"Se preferisci riceverlo a un altro indirizzo, indicalo nella pagina di "
               f"generazione prima che il lavoro finisca."),
        "en": (f"The download link will be sent to <strong>{dest}</strong> "
               f"once processing is complete. "
               f"To receive it at a different address, enter it on the generation page "
               f"before the job finishes."),
        "fr": (f"Le lien de t&eacute;l&eacute;chargement sera envoy&eacute; &agrave; "
               f"<strong>{dest}</strong> &agrave; la fin du traitement. "
               f"Pour le recevoir &agrave; une autre adresse, indiquez-la sur la page de "
               f"g&eacute;n&eacute;ration avant la fin du travail."),
        "es": (f"El enlace de descarga se enviar&aacute; a <strong>{dest}</strong> "
               f"al finalizar el procesamiento. "
               f"Si prefieres otra direcci&oacute;n, ind&iacute;cala en la p&aacute;gina de "
               f"generaci&oacute;n antes de que termine el trabajo."),
        "de": (f"Der Download-Link wird nach Abschluss der Verarbeitung an "
               f"<strong>{dest}</strong> gesendet. "
               f"F&uuml;r eine andere Adresse gib sie vor Ende des Auftrags "
               f"auf der Generierungsseite an."),
        "zh": (f"处理完成后，下载链接将发送至 <strong>{dest}</strong>。"
               f"如需发送到其他邮箱，请在任务结束前"
               f"在生成页面填写另一个邮箱。"),
        "hi": (f"प्रसंस्करण पूरा होने पर डाउनलोड लिंक "
               f"<strong>{dest}</strong> पर भेजा जाएगा। "
               f"किसी दूसरे पते पर चाहिए तो जॉब खत्म होने से पहले "
               f"जेनरेशन पेज पर वह ईमेल दर्ज करें।"),
    }
    delivery = delivery_map.get(lang, delivery_map["en"])
    html_body = f"""<div style="font-family:system-ui,-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px">
  <h2 style="color:#2c3e50">&#x1F4B3; {heading}</h2>
  <div style="padding:16px;background:#f0f5ff;border-radius:8px;margin:16px 0">
    <p style="margin:0">{details}</p>
  </div>
  <div style="padding:14px 16px;background:#fff7ed;border-left:4px solid #f97316;border-radius:4px;margin:16px 0">
    <p style="margin:0">&#x1F4E7; {delivery}</p>
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


def _send_voucher_notification_email(code, email, amount_eur, valid_days, created_at):
    """Notifica al destinatario un voucher creato dall'admin.

    Testo sempre in inglese (destinatari internazionali). Include codice,
    valore, giorni di validita' e data di generazione. Ritorna True su invio ok.

    created_at: epoch seconds della creazione voucher.
    valid_days: numero di giorni di validita' dalla data di generazione.
    """
    if not (email and _smtp_available()):
        return False
    from datetime import datetime
    try:
        gen_date = datetime.fromtimestamp(float(created_at)).strftime("%d %B %Y")
    except (TypeError, ValueError, OSError):
        gen_date = datetime.now().strftime("%d %B %Y")
    try:
        days_int = int(valid_days)
    except (TypeError, ValueError):
        days_int = VOUCHER_EXPIRY_DAYS
    code_safe = _sanitize_header(code, max_len=64)
    subject = f"Your Audiobook Maker voucher — EUR {amount_eur:.2f}"
    html_body = f"""<div style="font-family:system-ui,-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#333">
  <h2 style="color:#2c3e50">&#x1F381; Your voucher</h2>
  <p>Here is your voucher worth <strong>EUR {amount_eur:.2f}</strong>, which you can use for premium services on audiobook-maker.com (premium voices, AI text optimisation or AI translations):</p>
  <div style="padding:20px;background:#f0f5ff;border:2px dashed #8b5cf6;border-radius:8px;margin:20px 0;text-align:center">
    <div style="font-family:monospace;font-size:1.6em;font-weight:700;letter-spacing:2px;color:#8b5cf6">{code_safe}</div>
    <div style="margin-top:12px">Value: <strong>EUR {amount_eur:.2f}</strong></div>
  </div>
  <p>Please use it within <strong>{days_int} days</strong> from <strong>{gen_date}</strong>.</p>
  <p>Thank you for your support!</p>
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
  <p style="color:#999;font-size:12px">Audiobook Maker — {BASE_URL or ''}</p>
</div>"""
    return _send_email(email, subject, html_body)


def _send_gemini_overload_email(email, amount_eur, book_title, voucher_code=None,
                                 retry_after_sec=0):
    """Notifica all'utente che il job non e' stato avviato perche' il motore
    voci PREMIUM e' temporaneamente sovraccarico. Include il rimborso integrale.

    voucher_code valorizzato => pagamento PayPal, e' stato emesso un voucher.
    voucher_code None => pagamento via voucher, importo ri-accreditato.
    """
    if not (email and _smtp_available()):
        return
    title_safe = _sanitize_header(book_title or "il tuo libro", max_len=120)
    subject = (f"Audiobook Maker — Generazione non avviata, rimborso emesso "
               f"({amount_eur:.2f} EUR)")
    if voucher_code:
        from datetime import datetime, timedelta
        expiry = (datetime.now() + timedelta(days=VOUCHER_EXPIRY_DAYS)).strftime("%d/%m/%Y")
        refund_block = f"""<div style="padding:20px;background:#f0f5ff;border:2px dashed #8b5cf6;border-radius:8px;margin:20px 0;text-align:center">
    <div style="font-size:.85em;color:#666;margin-bottom:8px">Codice buono di rimborso:</div>
    <div style="font-family:monospace;font-size:1.6em;font-weight:700;letter-spacing:2px;color:#8b5cf6">{voucher_code}</div>
    <div style="margin-top:12px">Valore: <strong>{amount_eur:.2f} EUR</strong></div>
    <div style="margin-top:4px;font-size:.9em;color:#666">Scadenza: {expiry}</div>
  </div>
  <p>Per utilizzarlo, avvia una nuova generazione PREMIUM e inserisci questo codice insieme all'email <strong>{email}</strong>.</p>"""
    else:
        refund_block = f"""<div style="padding:16px;background:#f0fff4;border:1px solid #c6f6d5;border-radius:8px;margin:20px 0">
    <p style="margin:0"><strong>Rimborso accreditato:</strong> {amount_eur:.2f} EUR sono stati ri-accreditati sul tuo buono di pagamento originale e sono disponibili da subito per un nuovo tentativo.</p>
  </div>"""
    retry_hint = ""
    if retry_after_sec and retry_after_sec > 0:
        hours = max(1, retry_after_sec // 3600)
        retry_hint = (f"<p>Il servizio si rinnova al massimo entro <strong>"
                      f"{hours} or{'a' if hours == 1 else 'e'}</strong>: puoi "
                      f"riprovare gi&agrave; da domani.</p>")
    html_body = f"""<div style="font-family:system-ui,-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px">
  <h2 style="color:#c0392b">&#x26A0;&#xFE0F; Generazione audio non avviata</h2>
  <p>Ciao,</p>
  <p>la generazione delle voci PREMIUM per <strong>{title_safe}</strong> non &egrave; stata avviata.</p>
  <p><strong>Motivo:</strong> il motore voci PREMIUM &egrave; temporaneamente sovraccarico e non avrebbe potuto completare il tuo libro senza interruzioni.</p>
  <p>Per non lasciarti con un audio parziale abbiamo emesso il <strong>rimborso integrale</strong> della cifra che avevi versato, senza nemmeno iniziare la sintesi.</p>
  {refund_block}
  {retry_hint}
  <p>Ti chiediamo scusa per il disagio.</p>
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
  <p style="color:#999;font-size:12px">Audiobook Maker — {BASE_URL or ''}</p>
</div>"""
    _send_email(email, subject, html_body)


def _admin_notify_gemini_failure(job_id, kind, amount_eur, email, book_title,
                                  audit_outcome, reason_detail="",
                                  voucher_code=None, chars_total=None,
                                  chunks_total=None, chunks_failed=None,
                                  forensic_until=None, work_dir_path=""):
    """Notifica IMMEDIATA all'admin di un fallimento job Gemini TTS che ha
    comportato rimborso (o di un blocco preventivo).

    kind:    "quota" | "budget" | "quality" | "preflight" | "generic"
    audit_outcome: stringa di outcome dell'audit (es. "failed_quota_refunded").

    Throttle: 1 invio max ogni 60 sec per stesso job_id+kind, per evitare flood
    in caso di crash a ripetizione su stesso job.
    """
    if not ADMIN_EMAIL or not _smtp_available():
        return
    # Throttle per job+kind
    key = f"{job_id}::{kind}"
    now = time.time()
    with _admin_failure_lock:
        last = _admin_failure_last.get(key, 0.0)
        if (now - last) < 60.0:
            print(f"[admin] Failure alert throttled for {key} "
                  f"(last sent {now - last:.0f}s ago)")
            return
        _admin_failure_last[key] = now

    kind_label = {
        "quota":     "QUOTA esaurita",
        "budget":    "BUDGET superato",
        "quality":   "QUALITA' insufficiente (chunk silenziati)",
        "preflight": "BLOCCO PREVENTIVO RPD",
        "generic":   "ERRORE generico",
    }.get(kind, kind.upper())

    color = {
        "quota":     "#c0392b",
        "budget":    "#c0392b",
        "quality":   "#d97706",
        "preflight": "#2563eb",
        "generic":   "#7c2d12",
    }.get(kind, "#444")

    refund_line = ""
    if amount_eur and amount_eur > 0:
        if voucher_code:
            refund_line = (f"<tr><td><strong>Rimborso</strong></td>"
                           f"<td>{amount_eur:.2f} EUR — voucher PayPal "
                           f"<code>{voucher_code}</code></td></tr>")
        else:
            refund_line = (f"<tr><td><strong>Rimborso</strong></td>"
                           f"<td>{amount_eur:.2f} EUR — riaccredito "
                           f"voucher originale</td></tr>")

    plan_line = ""
    if chunks_total is not None:
        if chunks_failed is not None:
            plan_line = (f"<tr><td><strong>Chunk</strong></td>"
                         f"<td>{chunks_failed}/{chunks_total} falliti</td></tr>")
        else:
            plan_line = (f"<tr><td><strong>Chunk previsti</strong></td>"
                         f"<td>{chunks_total}</td></tr>")
    chars_line = ""
    if chars_total is not None:
        chars_line = (f"<tr><td><strong>Caratteri</strong></td>"
                      f"<td>{chars_total:,}</td></tr>")

    # Sec: questi valori sono controllati dall'utente (titolo/metadata libro, email,
    # dettaglio errore) e finiscono nel corpo HTML dell'email admin → HTML-escape,
    # non solo _sanitize_header (che copre i soli header CRLF).
    title_safe = _esc_html(_sanitize_header(book_title or "(senza titolo)", max_len=120))
    email_safe = _esc_html(_sanitize_header(email or "(sconosciuta)", max_len=200))
    reason_safe = _esc_html(_sanitize_header(reason_detail or "", max_len=300))
    subject = (f"[ABM-ADMIN] Gemini TTS — {kind_label} "
               f"— job {job_id[:8]}")

    # Forensic retention block: dir preservata + link download ZIP
    forensic_block = ""
    if forensic_until and BASE_URL:
        import urllib.parse as _urlparse
        from datetime import datetime as _dt
        try:
            until_iso = _dt.fromtimestamp(float(forensic_until)).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            until_iso = "?"
        forensic_url = (BASE_URL.rstrip("/")
                        + f"/admin/job/{_urlparse.quote(job_id, safe='')}/forensic.zip")
        wd_safe = _sanitize_header(work_dir_path or "", max_len=300)
        forensic_block = f"""
  <div style="margin-top:16px;padding:14px;background:#f1f5f9;border:1px solid #cbd5e1;border-radius:6px">
    <div style="font-weight:600;color:#0f172a;margin-bottom:8px">Analisi forense</div>
    <div style="font-size:13px;color:#334155;margin-bottom:8px">
      Cartella di lavoro preservata per <strong>analisi post-mortem</strong> fino al <strong>{until_iso}</strong>.
      Dopo tale data il cleanup automatico la rimuoverà.
    </div>
    <div style="font-size:12px;color:#475569;margin-bottom:10px;font-family:monospace;word-break:break-all">
      {wd_safe or '(path non disponibile)'}
    </div>
    <a href="{forensic_url}" style="display:inline-block;padding:9px 14px;background:#2563eb;color:#fff;border-radius:5px;text-decoration:none;font-weight:600;font-size:13px">Scarica ZIP forense</a>
    <div style="margin-top:8px;font-size:11px;color:#64748b">
      Richiede login admin (cookie su /admin/audit-premium). Se ricevi 401, fai login e ritorna a questo link.
    </div>
  </div>"""
    html_body = f"""<div style="font-family:system-ui,-apple-system,sans-serif;max-width:680px;margin:0 auto;padding:20px">
  <div style="background:{color};color:#fff;padding:16px 20px;border-radius:8px 8px 0 0">
    <h2 style="margin:0;font-size:18px">Gemini TTS — {kind_label}</h2>
    <p style="margin:6px 0 0;opacity:.9;font-size:13px">Job <code style="background:rgba(255,255,255,.18);padding:2px 6px;border-radius:3px">{job_id}</code></p>
  </div>
  <table style="width:100%;border-collapse:collapse;background:#fff;border:1px solid #ddd;border-top:none;font-size:14px">
    <tr><td style="padding:8px 12px;border-bottom:1px solid #eee;width:40%"><strong>Outcome audit</strong></td><td style="padding:8px 12px;border-bottom:1px solid #eee"><code>{audit_outcome}</code></td></tr>
    <tr><td style="padding:8px 12px;border-bottom:1px solid #eee"><strong>Utente</strong></td><td style="padding:8px 12px;border-bottom:1px solid #eee">{email_safe}</td></tr>
    <tr><td style="padding:8px 12px;border-bottom:1px solid #eee"><strong>Libro</strong></td><td style="padding:8px 12px;border-bottom:1px solid #eee">{title_safe}</td></tr>
    {plan_line}
    {chars_line}
    {refund_line}
    <tr><td style="padding:8px 12px"><strong>Dettaglio</strong></td><td style="padding:8px 12px;font-family:monospace;font-size:12px;color:#555">{reason_safe or '—'}</td></tr>
  </table>
  {forensic_block}
  <p style="color:#888;font-size:12px;margin-top:16px">Alert generato automaticamente. Per disattivare rimuovere <code>ABM_ADMIN_EMAIL</code>. Console eventi: <code>{BASE_URL}/admin/#tab-gemini</code></p>
</div>"""
    try:
        _send_email(ADMIN_EMAIL, subject, html_body)
        print(f"[admin] Failure alert sent for {key} ({kind_label})")
    except Exception as e:
        print(f"[admin] Failed to send failure alert for {key}: {e}")


def admin_notify_tts_backend_switch(model_key, reason, detail, job_id,
                                    credit_left_eur=None):
    """Notifica IMMEDIATA all'admin: il backend TTS e' passato a Vertex.

    Non passa dal digest di fine giornata: il margine in failover (Vertex)
    e' quasi nullo rispetto a quello su Cloudflare, quindi ogni ora di
    ritardo nell'avviso costa margine su ogni job servito nel frattempo.

    Sec: `detail` arriva da `gemini_tts` (tipicamente un messaggio d'errore
    HTTP del provider) e viene solo HTML-escapato qui, mai interpretato.
    Il chiamante (gemini_tts/tts_backend_state) e' responsabile di non
    includervi mai token/credenziali: questa funzione si limita a stamparlo.

    Un guasto SMTP non deve propagare: il failover e' gia' avvenuto e il
    job sta proseguendo su Vertex, l'email e' un di piu'.
    """
    if not ADMIN_EMAIL or not _smtp_available():
        return

    reason_label = {
        "cf_backend_down": "backend Cloudflare fuori uso",
        "cf_consecutive_failures": "fallimenti consecutivi oltre soglia",
    }.get(reason, reason)

    model_safe = _esc_html(_sanitize_header(model_key or "", max_len=80))
    reason_label_safe = _esc_html(_sanitize_header(reason_label, max_len=120))
    detail_safe = _esc_html(_sanitize_header(detail or "", max_len=300))
    job_safe = _esc_html(_sanitize_header(job_id or "", max_len=120))
    subject = _sanitize_header(
        f"[ABM-ADMIN] TTS {model_key}: switch automatico a Vertex "
        f"({reason_label})", max_len=200)

    credit_row = ""
    if credit_left_eur is not None:
        credit_row = (f"<tr><td><strong>Credito residuo (stima)</strong></td>"
                      f"<td>{credit_left_eur:.2f} &euro;</td></tr>")

    html_body = f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;max-width:640px;margin:0 auto">
      <div style="background:#c0392b;color:#fff;padding:16px 20px;border-radius:8px 8px 0 0">
        <h2 style="margin:0;font-size:18px">TTS: passaggio automatico a Vertex</h2>
      </div>
      <div style="background:#fff;border:1px solid #ddd;border-top:none;padding:16px 20px;font-size:14px">
        <p>Il modello <strong>{model_safe}</strong> non viene piu' servito da
           Cloudflare. I job in corso proseguono su Vertex dal chunk
           corrente, senza interruzione e senza differenza udibile.</p>
        <table cellpadding="6" style="border-collapse:collapse;font-size:.95em">
          <tr><td><strong>Causa</strong></td><td>{reason_label_safe}</td></tr>
          <tr><td><strong>Dettaglio</strong></td><td style="font-family:monospace;font-size:12px">{detail_safe}</td></tr>
          <tr><td><strong>Job che ha rilevato</strong></td><td><code>{job_safe}</code></td></tr>
          {credit_row}
        </table>
        <p style="background:#fff4e5;padding:10px;border-left:4px solid #d97706;margin-top:14px">
          <strong>Perche' e' urgente:</strong> su Vertex il margine scende
          quasi al pareggio, mentre su Cloudflare resta ampio. Il servizio
          continua a funzionare, ma ogni ora in questo stato e' margine
          perso su ogni job servito.</p>
        <p><strong>Il rientro e' manuale.</strong> Risolto il problema (di
           norma: ricaricare il credito Cloudflare), riattiva Cloudflare
           dal pannello <em>Backend TTS</em> della console admin. Non c'e'
           alcun ripristino automatico: un backend caduto per credito
           esaurito tornerebbe a cadere subito, e ogni caduta costa un
           job.</p>
      </div>
    </div>"""

    try:
        _send_email(ADMIN_EMAIL, subject, html_body)
        print(f"[admin] Notifica switch backend TTS inviata per {model_key} "
              f"({reason})")
    except Exception as e:
        print(f"[admin] Invio notifica switch backend TTS fallito: {e}")


def admin_notify_cf_credit_low(model_key, credit_left_eur, threshold_eur):
    """PRE-allarme all'admin: il credito Cloudflare stimato e' sotto soglia.

    Gemella di `admin_notify_tts_backend_switch`, ma dice il contrario:
    quella annuncia un failover GIA' avvenuto, questa arriva mentre il
    backend e' ancora sano e c'e' ancora tempo per ricaricare. Le due non
    vanno mai fuse: chi legge l'oggetto deve capire subito se il servizio sta
    gia' girando al margine ridotto o no.

    Immediata e non nel digest per la stessa ragione dello switch: se il
    credito finisce di notte, il servizio passa su Vertex fino al mattino e
    ogni job servito nel frattempo costa margine.

    Il residuo e' una STIMA (l'API Cloudflare non espone il saldo): e'
    `ABM_CF_CREDIT_BALANCE_EUR` dichiarato dall'admin meno la spesa
    accumulata dal ledger locale. Per questo l'email chiede di riallineare
    la variabile insieme alla ricarica E di azzerare il ledger dal pannello
    «Backend TTS»: sono due passaggi distinti, e senza il secondo l'allarme
    non si riarma (`reset_spend()` e' l'unica cosa che rimette `alerted` a
    False) e il residuo stimato resta sbagliato per il ciclo successivo.

    Sec: nessun token, nessuna credenziale - solo importi e nomi di
    variabili d'ambiente.

    Un guasto SMTP non propaga: l'allarme e' gia' stato consumato a monte
    (`claim_credit_alert`), il job prosegue comunque.
    """
    if not ADMIN_EMAIL or not _smtp_available():
        return

    model_safe = _esc_html(_sanitize_header(model_key or "", max_len=80))
    try:
        left = float(credit_left_eur)
    except (TypeError, ValueError):
        left = 0.0
    try:
        threshold = float(threshold_eur)
    except (TypeError, ValueError):
        threshold = 0.0
    subject = _sanitize_header(
        f"[ABM-ADMIN] Credito Cloudflare basso: {left:.2f} EUR residui "
        f"(soglia {threshold:.2f})", max_len=200)

    html_body = f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;max-width:640px;margin:0 auto">
      <div style="background:#d97706;color:#fff;padding:16px 20px;border-radius:8px 8px 0 0">
        <h2 style="margin:0;font-size:18px">Credito Cloudflare in esaurimento</h2>
      </div>
      <div style="background:#fff;border:1px solid #ddd;border-top:none;padding:16px 20px;font-size:14px">
        <p>Il credito Cloudflare stimato e' sceso sotto la soglia di
           pre-allarme. <strong>Il TTS gira ancora su Cloudflare</strong>: non
           e' avvenuto alcun failover, e non ci sono job in errore.</p>
        <table cellpadding="6" style="border-collapse:collapse;font-size:.95em">
          <tr><td><strong>Modello</strong></td><td><code>{model_safe}</code></td></tr>
          <tr><td><strong>Credito residuo (stima)</strong></td><td>{left:.2f} &euro;</td></tr>
          <tr><td><strong>Soglia di pre-allarme</strong></td><td>{threshold:.2f} &euro;</td></tr>
        </table>
        <p style="background:#fff4e5;padding:10px;border-left:4px solid #d97706;margin-top:14px">
          <strong>Che cosa succede se non si interviene:</strong> a credito
          esaurito il circuit breaker scatta e il TTS passa su Vertex, dove il
          margine scende quasi al pareggio. Il rientro su Cloudflare e' poi
          <em>manuale</em>, dal pannello «Backend TTS» della console admin:
          se il credito finisce di notte, il servizio resta su Vertex fino al
          mattino.</p>
        <p><strong>Che cosa fare:</strong></p>
        <ol>
          <li>Ricaricare il credito Cloudflare AI Gateway.</li>
          <li>Aggiornare <code>ABM_CF_CREDIT_BALANCE_EUR</code> nell'unit
              systemd col nuovo saldo dichiarato, poi <code>daemon-reload</code>
              e <code>restart</code>: il residuo qui sopra e' una stima
              calcolata da quel valore meno la spesa accumulata, e senza il
              riallineamento resterebbe sotto soglia.</li>
          <li><strong>Premere <em>«Ho ricaricato il credito»</em> nel pannello
              «Backend TTS» della console admin</strong> (pulsante sempre
              disponibile quando il backend configurato e' Cloudflare, anche
              senza alcun failover in corso). Questo azzera il contatore di
              spesa e riarma questo pre-allarme per il ciclo successivo:
              <strong>senza questo passaggio l'avviso non arrivera' mai
              piu'</strong> e il residuo mostrato in console resta sbagliato,
              perche' il saldo dichiarato sale mentre la spesa continua ad
              accumularsi dal ciclo precedente. Il solo aggiornamento della
              variabile d'ambiente non basta.</li>
        </ol>
        <p style="color:#888;font-size:12px;margin-top:16px">Il saldo Cloudflare non e' leggibile via API: questo importo e' una stima. Per disattivare l'avviso: <code>ABM_CF_CREDIT_BALANCE_EUR=0</code>. Console: <code>{BASE_URL}/admin/</code></p>
      </div>
    </div>"""

    try:
        _send_email(ADMIN_EMAIL, subject, html_body)
        print(f"[admin] Pre-allarme credito Cloudflare inviato per {model_key} "
              f"(residuo stimato {left:.2f} EUR)")
    except Exception as e:
        print(f"[admin] Invio pre-allarme credito Cloudflare fallito: {e}")


def _send_gemini_cancelled_partial_email(email, paid_eur, retained_eur,
                                          refund_eur, voucher_code,
                                          book_title, download_url, lang="it"):
    """Notifica all'utente che ha annullato volontariamente un job voci PREMIUM
    in corso: l'MP3 parziale e' disponibile al download, il rimborso e' stato
    emesso al netto della quota gia' consumata (costo provider + commissioni
    non recuperabili).

    - voucher_code valorizzato => pagamento PayPal, nuovo voucher emesso per
      l'importo rimborsato (refund_eur).
    - voucher_code None => pagamento via voucher, refund_eur ri-accreditato
      silenziosamente sul voucher originale.
    """
    if not (email and _smtp_available()):
        return
    title_safe = _sanitize_header(book_title or "il tuo libro", max_len=120)
    subject = (f"Audiobook Maker — Generazione annullata, audio parziale "
               f"disponibile ({refund_eur:.2f} EUR rimborsati)")
    dl_safe = (download_url or "").replace('"', "%22")
    if voucher_code and refund_eur > 0:
        from datetime import datetime, timedelta
        expiry = (datetime.now() + timedelta(days=VOUCHER_EXPIRY_DAYS)).strftime("%d/%m/%Y")
        refund_block = f"""<div style="padding:20px;background:#f0f5ff;border:2px dashed #8b5cf6;border-radius:8px;margin:20px 0;text-align:center">
    <div style="font-size:.85em;color:#666;margin-bottom:8px">Codice buono di rimborso:</div>
    <div style="font-family:monospace;font-size:1.6em;font-weight:700;letter-spacing:2px;color:#8b5cf6">{voucher_code}</div>
    <div style="margin-top:12px">Valore: <strong>{refund_eur:.2f} EUR</strong></div>
    <div style="margin-top:4px;font-size:.9em;color:#666">Scadenza: {expiry}</div>
  </div>
  <p>Per utilizzarlo, avvia una nuova generazione PREMIUM e inserisci questo codice insieme all'email <strong>{email}</strong>.</p>"""
    elif refund_eur > 0:
        refund_block = f"""<div style="padding:16px;background:#f0fff4;border:1px solid #c6f6d5;border-radius:8px;margin:20px 0">
    <p style="margin:0"><strong>Rimborso accreditato:</strong> {refund_eur:.2f} EUR sono stati ri-accreditati sul tuo buono di pagamento originale e sono disponibili da subito per un nuovo tentativo.</p>
  </div>"""
    else:
        refund_block = f"""<div style="padding:16px;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;margin:20px 0">
    <p style="margin:0">La generazione era gi&agrave; in fase avanzata: l'importo trattenuto ({retained_eur:.2f} EUR) corrisponde al costo gi&agrave; sostenuto. <strong>Nessun rimborso residuo</strong>.</p>
  </div>"""
    html_body = f"""<div style="font-family:system-ui,-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px">
  <h2 style="color:#d97706">&#x26A0;&#xFE0F; Generazione annullata su tua richiesta</h2>
  <p>Ciao,</p>
  <p>hai annullato la generazione delle voci PREMIUM per <strong>{title_safe}</strong> mentre era in corso.</p>
  <p>Abbiamo salvato l'<strong>audio parziale</strong> gi&agrave; sintetizzato fino al momento dell'annullamento. Puoi scaricarlo dal link sottostante:</p>
  <p style="text-align:center;margin:20px 0">
    <a href="{dl_safe}" style="display:inline-block;background:#8b5cf6;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600">Scarica l'audio parziale (MP3)</a>
  </p>
  <h3 style="margin-top:28px;color:#333">Dettaglio rimborso</h3>
  <table style="width:100%;border-collapse:collapse;font-size:14px;margin:12px 0">
    <tr><td style="padding:6px 0;color:#666">Importo versato</td><td style="padding:6px 0;text-align:right"><strong>{paid_eur:.2f} EUR</strong></td></tr>
    <tr><td style="padding:6px 0;color:#666">Quota trattenuta (costo gi&agrave; sostenuto)</td><td style="padding:6px 0;text-align:right">{retained_eur:.2f} EUR</td></tr>
    <tr><td style="padding:6px 0;color:#666;border-top:1px solid #eee"><strong>Rimborso</strong></td><td style="padding:6px 0;text-align:right;border-top:1px solid #eee"><strong style="color:#059669">{refund_eur:.2f} EUR</strong></td></tr>
  </table>
  {refund_block}
  <p style="font-size:.9em;color:#666">La quota trattenuta copre il costo del servizio voci PREMIUM gi&agrave; consumato fino al punto di annullamento, pi&ugrave; eventuali commissioni di pagamento non recuperabili.</p>
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
  <p style="color:#999;font-size:12px">Audiobook Maker — {BASE_URL or ''}</p>
</div>"""
    _send_email(email, subject, html_body)


def _send_gemini_failed_refund_email(email, amount_eur, book_title, reason_label, voucher_code=None):
    """Notifica all'utente che la generazione voci PREMIUM e' fallita per
    esaurimento quota giornaliera del provider (o limite di spesa interno) e
    che il rimborso integrale e' stato emesso.

    - voucher_code valorizzato => pagamento PayPal, e' stato emesso un nuovo
      voucher (con eventuale bonus) all'email.
    - voucher_code None => pagamento via voucher, l'importo e' stato
      ri-accreditato sul voucher originale.
    """
    if not (email and _smtp_available()):
        return
    title_safe = _sanitize_header(book_title or "il tuo libro", max_len=120)
    subject = f"Audiobook Maker \u2014 Generazione interrotta, rimborso emesso ({amount_eur:.2f} EUR)"
    if voucher_code:
        from datetime import datetime, timedelta
        expiry = (datetime.now() + timedelta(days=VOUCHER_EXPIRY_DAYS)).strftime("%d/%m/%Y")
        refund_block = f"""<div style="padding:20px;background:#f0f5ff;border:2px dashed #8b5cf6;border-radius:8px;margin:20px 0;text-align:center">
    <div style="font-size:.85em;color:#666;margin-bottom:8px">Codice buono di rimborso:</div>
    <div style="font-family:monospace;font-size:1.6em;font-weight:700;letter-spacing:2px;color:#8b5cf6">{voucher_code}</div>
    <div style="margin-top:12px">Valore: <strong>{amount_eur:.2f} EUR</strong></div>
    <div style="margin-top:4px;font-size:.9em;color:#666">Scadenza: {expiry}</div>
  </div>
  <p>Per utilizzarlo, avvia una nuova generazione PREMIUM e inserisci questo codice insieme all'email <strong>{email}</strong>.</p>"""
    else:
        refund_block = f"""<div style="padding:16px;background:#f0fff4;border:1px solid #c6f6d5;border-radius:8px;margin:20px 0">
    <p style="margin:0"><strong>Rimborso accreditato:</strong> {amount_eur:.2f} EUR sono stati ri-accreditati sul tuo buono di pagamento originale e sono disponibili da subito per un nuovo tentativo.</p>
  </div>"""
    html_body = f"""<div style="font-family:system-ui,-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px">
  <h2 style="color:#c0392b">&#x26A0;&#xFE0F; Generazione audio interrotta</h2>
  <p>Ciao,</p>
  <p>la generazione delle voci PREMIUM per <strong>{title_safe}</strong> non &egrave; stata completata.</p>
  <p><strong>Motivo:</strong> {reason_label}</p>
  <p>L'operazione &egrave; considerata <strong>fallita</strong> e abbiamo emesso il <strong>rimborso integrale</strong> della cifra che avevi versato.</p>
  {refund_block}
  <p>Ti chiediamo scusa per il disagio. Puoi ritentare la generazione tra qualche ora, quando la quota del servizio si sar&agrave; rinnovata.</p>
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
  <p style="color:#999;font-size:12px">Audiobook Maker \u2014 {BASE_URL or ''}</p>
</div>"""
    _send_email(email, subject, html_body)
