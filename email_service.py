"""
email_service.py — Infrastruttura email per Audiobook Maker.

Funzioni:
  - _smtp_available: verifica configurazione SMTP
  - _send_email: invio HTML email via SMTP
  - _admin_notify_generation: accodamento evento per digest admin
  - _try_send_admin_digest: invio digest se rate limit permette
  - _try_send_voxcpm_digest: digest quotidiano dei ritentativi VoxCPM
  - _send_payment_receipt_email: ricevuta pagamento PayPal
  - _send_voucher_email: email buono rimborso (ottimizzazione testo AI)
  - _send_gemini_failed_refund_email: notifica fallimento generazione voci PREMIUM + rimborso

Dipende solo dalla stdlib e da os.environ — nessun import da audiobook_app.
"""

import html
import os
import i18n as _i18n
import email_layout as _layout
import email_layout as _layout
import email_layout as _layout
import email_layout as _layout
from ratelimit import throttle_ok as _throttle_ok
from client_identity import EMAIL_RE as _EMAIL_RE
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
# Casella di assistenza utenti (form "Contatta supporto" del sito).
# Inoltrata via MX esterno alla mailbox del titolare: qui serve solo l'indirizzo.
SUPPORT_EMAIL = os.environ.get("ABM_SUPPORT_EMAIL", "support@audiobook-maker.com")
BASE_URL = os.environ.get("ABM_BASE_URL", "").rstrip("/")

# ---------------------------------------------------------------------------
# Voce campionata: testi email in sette lingue (i18n/voice_clone_emails.json)
# ---------------------------------------------------------------------------

_VC_I18N = _i18n.load("voice_clone_emails")

# ---------------------------------------------------------------------------
# Admin digest config
# ---------------------------------------------------------------------------

ADMIN_EMAIL = os.environ.get("ABM_ADMIN_EMAIL", "")
ADMIN_DIGEST_INTERVAL_SEC = 24 * 60 * 60  # 24 ore tra un digest e il successivo

# Il digest quotidiano VoxCPM: acceso quando c'e' un admin a cui mandarlo,
# spegnibile senza toccare l'altro digest.
VOXCPM_DIGEST = os.environ.get("ABM_VOXCPM_DIGEST", "1").strip().lower() not in (
    "0", "false", "off", "no")

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
# Power user provider hook (iniettato da audiobook_app — nessun import circolare)
# ---------------------------------------------------------------------------

_power_users_provider = None  # callable() -> {"rows": [...], ...} | None


def set_power_users_provider(fn):
    global _power_users_provider
    _power_users_provider = fn


def _power_users_block_html():
    """Tabella dei client con molti avvii a voce standard nelle ultime 24h
    (agosto 2026: pochi client = ~40% del volume sintetizzato). '' se il
    provider manca, fallisce o non ha righe. Mai email o altri dati personali:
    solo client_id anonimo, contatori e IP distinti."""
    fn = _power_users_provider
    if not fn:
        return ""
    try:
        d = fn() or {}
    except Exception:
        return ""
    rows = d.get("rows") or []
    if not rows:
        return ""
    lim = int(d.get("quota_limit_chars") or 0)
    hours = int(d.get("window_hours") or 24)
    min_jobs = int(d.get("min_jobs") or 0)
    th = "padding:6px 8px;text-align:left;font-size:12px;color:#555;white-space:nowrap"
    td = "padding:6px 8px;border-bottom:1px solid #eee;font-size:12px;vertical-align:top"
    trs = ""
    for r in rows:
        jobs_txt = str(int(r.get("jobs_24h") or 0))
        if int(r.get("reuse_24h") or 0):
            jobs_txt += f" (riusi {int(r['reuse_24h'])})"
        gate_txt = f"{int(r.get('gate_24h') or 0)} / {int(r.get('block_24h') or 0)}"
        if int(r.get("abuse_24h") or 0):
            gate_txt += f" &middot; abuso {int(r['abuse_24h'])}"
        chars = int(r.get("chars_month") or 0)
        chars_txt = f"{chars:,}"
        if lim:
            chars_txt += f" ({chars * 100 // lim}%)"
        if int(r.get("gated_month") or 0):
            chars_txt += f" &middot; oltre quota: {int(r['gated_month'])}"
        srcs = r.get("sources") or {}
        src_txt = ", ".join(f"{k}:{v}" for k, v in sorted(srcs.items())) or "-"
        langs_txt = ", ".join(str(x) for x in (r.get("langs") or [])) or "-"
        trs += (
            f"<tr><td style='{td};font-family:monospace'>{_esc_html(r.get('client_id', ''), 24)}</td>"
            f"<td style='{td};text-align:center'>{jobs_txt}</td>"
            f"<td style='{td};text-align:center'>{int(r.get('premium_24h') or 0)}</td>"
            f"<td style='{td};text-align:center'>{gate_txt}</td>"
            f"<td style='{td};text-align:center'>{int(r.get('books_month') or 0)}</td>"
            f"<td style='{td};text-align:right;white-space:nowrap'>{chars_txt}</td>"
            f"<td style='{td};text-align:center'>{int(r.get('ips_24h') or 0)}</td>"
            f"<td style='{td}'>{_esc_html(r.get('platform', '') or '-', 20)}</td>"
            f"<td style='{td}'>{_esc_html(langs_txt, 30)}</td>"
            f"<td style='{td}'>{_esc_html(src_txt, 60)}</td></tr>"
        )
    return (
        f"<h3 style='margin:18px 0 6px'>Power user voci standard (ultime {hours}h, &ge; {min_jobs} avvii)</h3>"
        "<table style='width:100%;border-collapse:collapse;background:white;border:1px solid #ddd'>"
        f"<thead><tr style='background:#f0f5fa'><th style='{th}'>Client</th><th style='{th}'>Avvii 24h</th>"
        f"<th style='{th}'>Premium 24h</th><th style='{th}'>Gate / rifiuti 24h</th><th style='{th}'>Libri mese</th>"
        f"<th style='{th}'>Caratteri mese</th><th style='{th}'>IP 24h</th><th style='{th}'>Piattaforma</th>"
        f"<th style='{th}'>Lingue</th><th style='{th}'>Fonti</th></tr></thead>"
        f"<tbody>{trs}</tbody></table>"
        "<p style='color:#999;font-size:11px;margin:4px 0 0'>Avvii = GENERATE + REUSE a voce standard; "
        "gate = job accettati oltre quota con email, rifiuti = 402 senza email; fonti = indizio dal nome file.</p>"
    )


# ---------------------------------------------------------------------------
# Abuse digest provider hook (iniettato da audiobook_app — nessun import circolare)
# ---------------------------------------------------------------------------

_abuse_provider = None  # callable() -> {"rows": [...], "window_hours": int, "kill_enabled": bool} | None


def set_abuse_provider(fn):
    global _abuse_provider
    _abuse_provider = fn


def _abuse_provider_data():
    """Interroga il provider abuso una sola volta. Fail-open: `None` se il
    provider manca o fallisce (equivale a 'nessuna riga')."""
    fn = _abuse_provider
    if not fn:
        return None
    try:
        return fn() or {}
    except Exception:
        return None


def _abuse_block_html(data=None):
    """Sezione «Casi di abuso quota» del digest: gruppi con giudizio, kill o
    rifiuto 403 nella finestra (abuse_watch.digest_data). Solo hash di rete e
    contatori: mai IP, email o titoli nel canale email. '' se il provider
    manca, fallisce o non ha righe. `data`, se fornito, evita di richiamare
    il provider una seconda volta nello stesso invio del digest."""
    d = _abuse_provider_data() if data is None else data
    if not d:
        return ""
    rows = d.get("rows") or []
    if not rows:
        return ""
    hours = int(d.get("window_hours") or 24)
    mode = "kill attiva" if d.get("kill_enabled") else "solo osservazione"
    th = "padding:6px 8px;text-align:left;font-size:12px;color:#555;white-space:nowrap"
    td = "padding:6px 8px;border-bottom:1px solid #eee;font-size:12px;vertical-align:top"
    trs = ""
    for r in rows:
        sig = " ".join(k for k, v in sorted((r.get("signals") or {}).items()) if v) or "-"
        verd = str(r.get("verdict") or "")
        if verd:
            verd += f" ({float(r.get('confidence') or 0):.2f}, {r.get('scope') or '-'})"
        else:
            verd = "-"
        unj = int(r.get("unjudged") or 0)
        if unj:
            verd += f" &middot; non giudicato x{unj}"
        chars = int(r.get("chars_24h") or 0)
        trs += (
            f"<tr><td style='{td};font-family:monospace'>{_esc_html(r.get('group', ''), 40)}</td>"
            f"<td style='{td};text-align:center'>{int(r.get('cids_n') or 0)}</td>"
            f"<td style='{td};text-align:center'>{_esc_html(sig)}</td>"
            f"<td style='{td};text-align:center'>{int(r.get('generate_24h') or 0)} / {chars:,}</td>"
            f"<td style='{td}'>{_esc_html(verd)}</td>"
            f"<td style='{td};text-align:center'>{int(r.get('kills') or 0)}</td>"
            f"<td style='{td};text-align:center'>{int(r.get('blocks') or 0)}</td>"
            f"<td style='{td};color:#666'>{_esc_html(r.get('reason', ''), 160)}</td></tr>"
        )
    return f"""
<h3 style="margin:24px 0 8px;font-size:15px;color:#1a3c5e">Casi di abuso quota ({mode}, ultime {hours}h)</h3>
<table style="width:100%;border-collapse:collapse;background:white;border:1px solid #ddd">
<thead><tr style="background:#f0f5fa">
<th style="{th}">Gruppo</th><th style="{th};text-align:center">cid</th>
<th style="{th};text-align:center">Segnali</th><th style="{th};text-align:center">Avvii / caratteri 24h</th>
<th style="{th}">Verdetto</th><th style="{th};text-align:center">Kill</th>
<th style="{th};text-align:center">Rifiuti</th><th style="{th}">Motivazione</th>
</tr></thead><tbody>{trs}</tbody></table>
<p style="color:#888;font-size:11px;margin:6px 0 0">Solo hash di rete e contatori: nessun IP, email o titolo.
Ripristino di un gruppo: <code>POST /admin/api/abuse/clear/&lt;gruppo&gt;</code> con header X-Admin-Token.</p>"""


# ---------------------------------------------------------------------------
# Voce campionata digest provider hook (iniettato da audiobook_app — nessun
# import circolare)
# ---------------------------------------------------------------------------

_voice_clone_provider = None  # callable() -> {"rows": [...], "window_hours": int, "active_ready": int} | None


def set_voice_clone_provider(fn):
    global _voice_clone_provider
    _voice_clone_provider = fn


def _voice_clone_provider_data():
    if _voice_clone_provider is None:
        return None
    try:
        return _voice_clone_provider() or None
    except Exception as e:      # noqa: BLE001
        print(f"[email] voice clone provider fallito: {e}", flush=True)
        return None


def _voice_clone_block_html(data=None):
    """Sezione «Voci campionate» del digest: contatori per stato nella
    finestra e voci attive. Mai email, codici o token."""
    d = _voice_clone_provider_data() if data is None else data
    if not d or not (d.get("rows") or []):
        return ""
    hours = int(d.get("window_hours") or 24)
    righe = "".join(f"<tr><td>{html.escape(str(r.get('label')))}</td>"
                    f"<td style=\"text-align:right\">{int(r.get('count') or 0)}</td></tr>"
                    for r in d["rows"])
    return (f"<h3>Voci campionate (ultime {hours} h)</h3>"
            f"<table>{righe}</table>"
            f"<p>Voci attive: <strong>{int(d.get('active_ready') or 0)}</strong></p>")


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


def _send_email(to_addr, subject, html_body, reply_to=None, from_addr=None,
                from_name=None):
    """Send an HTML email via SMTP. Returns True on success.

    ``reply_to``: indirizzo opzionale per l'header Reply-To.
    ``from_name``: nome visualizzato del mittente (``Nome <indirizzo>``). Non
    tocca l'indirizzo, quindi SPF/DKIM/DMARC restano allineati al nostro
    dominio: e' il modo sicuro per far vedere in mailbox chi ha scritto.
    ``from_addr``: indirizzo opzionale per l'header From (RFC 5322). Il mittente
    di BUSTA (SMTP MAIL FROM) resta sempre ``SMTP_FROM``, unico indirizzo
    autenticato sul relay: cambia solo l'intestazione mostrata dal client di
    posta, e viene aggiunto ``Sender: SMTP_FROM`` come richiede l'RFC quando i
    due differiscono.
    ATTENZIONE: con un From di dominio terzo il messaggio non e' piu' allineato
    a SPF/DKIM del nostro dominio e i domini con DMARC ``p=quarantine/reject``
    finiscono in spam o vengono rifiutati; preferire ``from_name``. Se il relay
    lo rifiuta si ritenta una volta con ``SMTP_FROM``, cosi' l'email non va persa.
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.utils import formataddr

    if not _smtp_available():
        print(f"[email] SMTP not configured, cannot send to {to_addr}", flush=True)
        return False

    # Sec: validazione difensiva degli header (CRLF injection)
    to_addr_clean = _sanitize_header(to_addr, max_len=320)
    subject_clean = _sanitize_header(subject, max_len=200)
    # Validazione di base sull'indirizzo destinatario (i chiamanti già filtrano con regex,
    # ma applichiamo un check di sicurezza centrale).
    if not _EMAIL_RE.match(to_addr_clean):
        print(f"[email] Refused invalid recipient: {to_addr_clean!r}", flush=True)
        return False

    # From personalizzato: stessa validazione stretta del destinatario, altrimenti
    # si ricade sul mittente di default (mai fidarsi del valore che arriva dal client).
    from_header = SMTP_FROM
    if from_addr:
        from_clean = _sanitize_header(from_addr, max_len=320)
        if _EMAIL_RE.match(from_clean):
            from_header = from_clean
        else:
            print(f"[email] Ignored invalid From: {from_clean!r}", flush=True)
    # Il nome visualizzato puo' contenere testo dell'utente: via i CR/LF e poi
    # quoting/encoding RFC a carico di formataddr.
    from_name_clean = _sanitize_header(from_name, max_len=200) if from_name else ""

    def _build(sender_addr):
        msg = MIMEMultipart("alternative")
        msg["From"] = formataddr((from_name_clean, sender_addr)) if from_name_clean else sender_addr
        msg["To"] = to_addr_clean
        msg["Subject"] = subject_clean
        if sender_addr != SMTP_FROM:
            # RFC 5322 §3.6.2: quando From non e' chi trasmette davvero.
            msg["Sender"] = SMTP_FROM
        if reply_to:
            reply_clean = _sanitize_header(reply_to, max_len=320)
            if _EMAIL_RE.match(reply_clean):
                msg["Reply-To"] = reply_clean
            else:
                print(f"[email] Ignored invalid Reply-To: {reply_clean!r}", flush=True)
        # Disable TurboSMTP link/open tracking to avoid redirect issues
        msg["X-TurboSMTP-Tracking"] = "0"
        msg["X-SMTPAPI"] = '{"filters":{"clicktrack":{"settings":{"enable":0}},"opentrack":{"settings":{"enable":0}}}}'
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        return msg

    def _deliver(raw):
        """Apre la connessione, invia e chiude. Solleva l'eccezione al chiamante."""
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
                server.sendmail(SMTP_FROM, to_addr_clean, raw)
            else:
                server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
                server.ehlo()
                if SMTP_PORT != 25:
                    server.starttls()
                    server.ehlo()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_FROM, to_addr_clean, raw)
        finally:
            if server is not None:
                try:
                    server.close()
                except Exception:
                    pass

    print(f"[email] Connecting to {SMTP_HOST}:{SMTP_PORT} for {to_addr_clean}...", flush=True)
    t0 = time.time()
    try:
        _deliver(_build(from_header).as_string())
        print(f"[email] Sent to {to_addr_clean} in {time.time()-t0:.1f}s: {subject_clean}", flush=True)
        return True
    except (smtplib.SMTPSenderRefused, smtplib.SMTPDataError,
            smtplib.SMTPRecipientsRefused) as e:
        if from_header == SMTP_FROM:
            print(f"[email] Failed to send to {to_addr_clean} after {time.time()-t0:.1f}s: {type(e).__name__}: {e}", flush=True)
            return False
        # Il relay ha rifiutato il From di terze parti: riprova col mittente di default.
        print(f"[email] Relay refused From {from_header!r} ({type(e).__name__}: {e}); retry with {SMTP_FROM}", flush=True)
        try:
            _deliver(_build(SMTP_FROM).as_string())
            print(f"[email] Sent to {to_addr_clean} in {time.time()-t0:.1f}s (fallback From): {subject_clean}", flush=True)
            return True
        except Exception as e2:
            print(f"[email] Failed to send to {to_addr_clean} after {time.time()-t0:.1f}s: {type(e2).__name__}: {e2}", flush=True)
            return False
    except Exception as e:
        print(f"[email] Failed to send to {to_addr_clean} after {time.time()-t0:.1f}s: {type(e).__name__}: {e}", flush=True)
        return False


# ---------------------------------------------------------------------------
# Richieste di assistenza (form "Contatta supporto" del sito)
# ---------------------------------------------------------------------------

_PLAN_LABELS = {
    "free": "Libro FREE (voci standard)",
    "premium": "Libro PREMIUM (voci PREMIUM / ottimizzazione AI a pagamento)",
}


def send_support_request(user_email, plan, book_title, download_link, message,
                         ui_lang="", ip_hash=""):
    """Inoltra a ``SUPPORT_EMAIL`` una richiesta di assistenza dal sito.

    In mailbox il mittente mostrato e' l'email dell'utente (gia' obbligatoria e
    validata dall'endpoint), messa nel NOME visualizzato: ``utente@x.it (via
    Audiobook Maker) <noreply@audiobook-maker.com>``. L'indirizzo resta il
    nostro, quindi SPF/DKIM/DMARC restano allineati: settembre 2026 queste
    email finivano in spam perche' l'inoltro MX della casella di assistenza
    rompe SPF, e un ``From`` di dominio terzo avrebbe peggiorato la
    classificazione (o fatto rifiutare i mittenti con DMARC ``p=reject``).
    ``Reply-To`` porta la risposta all'utente.
    Ogni valore proveniente dal client viene HTML-escapato: il corpo finisce in
    una mailbox reale e non deve poter iniettare markup.
    Ritorna True se l'email e' stata accettata dal relay.
    """
    plan_label = _PLAN_LABELS.get(plan, plan or "-")
    title_txt = _esc_html(book_title, 300) or "<i>(non indicato)</i>"
    link_raw = (download_link or "").strip()
    if not link_raw:
        link_html = "<i>(non indicato)</i>"
    elif BASE_URL and link_raw.startswith(BASE_URL + "/"):
        # Solo i link del nostro dominio diventano cliccabili: un URL esterno
        # arbitrario resta testo, per non trasformare la mailbox di assistenza
        # in un vettore di phishing a un click.
        link_esc = _esc_html(link_raw, 500)
        link_html = f'<a href="{link_esc}">{link_esc}</a>'
    else:
        link_html = _esc_html(link_raw, 500)
    msg_html = _esc_html(message, 4000).replace(chr(10), "<br>")
    meta_bits = []
    if ui_lang:
        meta_bits.append(f"lingua UI: {_esc_html(ui_lang, 8)}")
    if ip_hash:
        meta_bits.append(f"ip_hash: {_esc_html(ip_hash, 32)}")
    meta = ("<p style='font-size:.85em;color:#888'>" + " &middot; ".join(meta_bits) + "</p>") if meta_bits else ""

    body = (
        f"<p><b>Nuova richiesta di assistenza dal sito.</b></p>"
        f"<p>Email utente: <a href=\"mailto:{_esc_html(user_email, 320)}\">"
        f"{_esc_html(user_email, 320)}</a></p>"
        f"<p>Tipo di libro: {_esc_html(plan_label, 120)}</p>"
        f"<p>Titolo: {title_txt}</p>"
        f"<p>Link di download: {link_html}</p>"
        f"<p>Problema riscontrato:</p>"
        f"<p style='border-left:3px solid #d9a441;padding-left:8px;white-space:pre-wrap'>"
        f"{msg_html or '<i>(vuoto)</i>'}</p>"
        f"{meta}"
    )
    short_title = (book_title or "senza titolo")[:60]
    subject = f"[ABM Support] {plan or '-'} - {short_title}"
    from_label = f"{_sanitize_header(user_email, 320)} (via Audiobook Maker)"
    return _send_email(SUPPORT_EMAIL, subject, body,
                       reply_to=user_email, from_name=from_label)


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
    # Calcolato una sola volta per invio: un gruppo solo bloccato (403, mai un
    # job in coda) non deve restare invisibile solo perche' _admin_queue e'
    # vuota (issue #8).
    _abuse_data = _abuse_provider_data()
    _abuse_rows = (_abuse_data or {}).get("rows") or []
    _vc_data = _voice_clone_provider_data()
    _vc_rows = (_vc_data or {}).get("rows") or []
    with _admin_queue_lock:
        if not _admin_queue and not _abuse_rows and not _vc_rows:
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
    n_abuse = len(_abuse_rows)
    abuse_tag = f"{n_abuse} cas{'o' if n_abuse == 1 else 'i'} di abuso"
    if count == 0:
        # Invio abuse-only: l'oggetto dice il motivo reale, non "0 nuovi libri".
        subject = f"\u26a0\ufe0f Audiobook Maker: {abuse_tag}"
        intro = f"Nessuna elaborazione avviata \u2014 {abuse_tag}"
    else:
        subject = f"\U0001f4da Audiobook Maker: {count} nuov{'o' if count == 1 else 'i'} libr{'o' if count == 1 else 'i'} in elaborazione"
        intro = f"{count} elaborazion{'e' if count == 1 else 'i'} avviat{'a' if count == 1 else 'e'}"
        if n_abuse:
            subject += f" \u00b7 {abuse_tag}"
            intro += f" \u00b7 {abuse_tag}"

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
    power_block = _power_users_block_html()
    abuse_block = _abuse_block_html(_abuse_data or {})
    voice_clone_block = _voice_clone_block_html(_vc_data or {})
    html = _layout.digest_page(
        "\U0001f3a7 Audiobook Maker \u2014 Activity Digest",
        f"{intro} \u2014 {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"""<table style="width:100%;border-collapse:collapse;background:white;border:1px solid #ddd;border-top:none">
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
{power_block}
{abuse_block}
{voice_clone_block}""",
        ["Questo messaggio è generato automaticamente da Audiobook Maker.\n"
         "Per disattivare, rimuovere la variabile ABM_ADMIN_EMAIL dalla configurazione del server."])

    try:
        _send_email(ADMIN_EMAIL, subject, html)
        print(f"[admin] Digest sent to {ADMIN_EMAIL}: {count} event(s)")
    except Exception as e:
        # Re-queue events so they're not lost
        with _admin_queue_lock:
            _admin_queue.extend(events)
        print(f"[admin] Digest send failed, {count} events re-queued: {e}")


# ---------------------------------------------------------------------------
# Digest quotidiano VoxCPM
# ---------------------------------------------------------------------------

def _try_send_voxcpm_digest():
    """Manda all'admin il riepilogo dei ritentativi VoxCPM di ieri.

    Chiamata a ogni giro del ciclo di pulizia: il giorno da spedire lo decide
    `voxcpm_digest.giorno_arretrato`, che legge un marker su disco. Quindi il
    ritmo non dipende da quando il server e' stato avviato, e un riavvio non
    salta ne' duplica una giornata.

    Un giorno senza job VoxCPM viene marcato come fatto senza spedire nulla:
    una mail che dice «niente da dire» ogni mattina si smette di leggerla, e
    con lei si smette di leggere quelle che qualcosa da dire ce l'hanno.
    """
    if not (VOXCPM_DIGEST and ADMIN_EMAIL and _smtp_available()):
        return
    try:
        import voxcpm_digest
    except ImportError:
        return
    try:
        giorno = voxcpm_digest.giorno_arretrato()
        if not giorno:
            return
        r = voxcpm_digest.riepilogo(giorno)
        if not r["job_totali"]:
            # Marcato comunque: domani si guarda domani, non di nuovo ieri.
            voxcpm_digest.segna_inviato(giorno)
            return
        _send_email(ADMIN_EMAIL, voxcpm_digest.oggetto(r), voxcpm_digest.html(r))
        # Solo dopo l'invio riuscito: se la mail non parte, il giorno resta
        # arretrato e il prossimo giro riprova.
        voxcpm_digest.segna_inviato(giorno)
        print(f"[voxcpm] Digest {giorno} inviato a {ADMIN_EMAIL}: "
              f"{r['necessari']} ritentativi necessari, {r['riusciti']} "
              f"riusciti, {r['falliti']} falliti, {r['non_tentati']} non "
              f"tentati")
    except Exception as e:
        # Il digest non deve mai fermare il ciclo di pulizia che lo chiama.
        print(f"[voxcpm] Digest non inviato (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Payment emails
# ---------------------------------------------------------------------------

# Ricevuta di pagamento in sette lingue (i18n/receipt_emails.json): testi
# piu' `service_names` = etichette del servizio pagato per `kind`, fissato dalla
# route di creazione dell'ordine in job["pay_receipt_kind"] (vedi
# api_paypal_capture_order); "voice_clone" per il campionamento di una voce.
_RECEIPT_I18N = _i18n.load("receipt_emails")
# Email delle generazioni PREMIUM (sovraccarico, annullata con audio parziale,
# fallita con rimborso): i18n/premium_emails.json, fallback inglese per chiave.
_PREMIUM_I18N = _i18n.load("premium_emails")


def _premium_refund_block(t, amount, voucher_code, email):
    """Blocco di rimborso delle email PREMIUM: box del nuovo buono (pagamento
    PayPal) o riga verde del riaccredito sul buono originale."""
    if voucher_code:
        return _layout.voucher_refund_block(voucher_code, amount, _voucher_expiry(),
                                            t["voucher_use"].format(email=_esc_html(email)), t)
    return _layout.refund_credited(t["refund_credited"].format(amount=amount))
_RECEIPT_SERVICE = {lg: t.get("service_names", {}) for lg, t in _RECEIPT_I18N.items()}


def _voucher_expiry():
    """Data di scadenza (gg/mm/aaaa) di un buono emesso adesso."""
    from datetime import datetime, timedelta
    return (datetime.now() + timedelta(days=VOUCHER_EXPIRY_DAYS)).strftime("%d/%m/%Y")


def _send_payment_receipt_email(order_id, email, amount_eur, kind="optimization",
                                lang="en", book_title="", job=None):
    """Ricevuta del pagamento PayPal, nella lingua UI di chi paga (fallback
    inglese). `kind`: servizio pagato (chiavi di `_RECEIPT_SERVICE`). `job`:
    se presente aggiunge il blocco su dove arrivera' il link di download."""
    t = _i18n.pick(_RECEIPT_I18N, lang)
    service = t["service_names"].get(kind) or t["service_names"]["optimization"]
    amount = f"{amount_eur:.2f}"
    subject = t["subject"].format(amount=amount)
    rows = (f"{t['amount']}: <strong>{amount} EUR</strong>"
            f"<br>{t['txid']}: <code>{html.escape(str(order_id))}</code>"
            f"<br>{t['service']}: <strong>{service}</strong>")
    if book_title:
        rows += f"<br>{t['project']}: <strong>{html.escape(book_title)}</strong>"
    refund = t["refund"].format(pct=VOUCHER_BONUS_PERCENT, days=VOUCHER_EXPIRY_DAYS)
    # Blocco consegna: rende esplicito SU QUALE indirizzo arrivera' il link di
    # download. Il job pagato passa in batch implicito sull'email del pagamento
    # (vedi api_paypal_capture -> job["notify_email"]), che puo' essere diversa
    # da quella che l'utente si aspetta di controllare: senza questa riga la
    # notifica finisce su una casella che non guarda ("email mai ricevuta").
    # Destinatario reale della notifica: l'email eventualmente gia' registrata
    # dall'utente ha la precedenza sull'email del pagamento (stessa priorita' di
    # api_paypal_capture / api_register_email).
    delivery_html = ""
    if job is not None:
        dest = (job.get("notify_email") or "").strip() or email
        delivery_html = f"""
  <div style="padding:14px 16px;background:#fff7ed;border-left:4px solid #f97316;border-radius:4px;margin:16px 0">
    <p style="margin:0">&#x1F4E7; {t["delivery"].format(dest=html.escape(dest))}</p>
  </div>"""
    html_body = _layout.layout(f"""  <h2 style="color:#2c3e50">&#x1F4B3; {t["heading"]}</h2>
  <div style="padding:16px;background:#f0f5ff;border-radius:8px;margin:16px 0">
    <p style="margin:0">{rows}</p>
  </div>{delivery_html}
  <p>{t["info"]}</p>
  <p style="font-size:.9em;color:#666">{refund}</p>""", BASE_URL)
    _send_email(email, subject, html_body)


# Email del buono di rimborso, in sette lingue (i18n/voucher_emails.json).
# `{what}` e' l'operazione fallita, presa da `what_names` secondo il `kind` del
# job; `{bonus}` vale "" quando il buono non e' maggiorato (annullamento
# volontario).
_VOUCHER_I18N = _i18n.load("voucher_emails")
_VOUCHER_WHAT = {lg: t.get("what_names", {}) for lg, t in _VOUCHER_I18N.items()}


def _send_voucher_email(code, email, amount_eur, book_title, kind="optimization",
                        lang="en", bonus_applied=True):
    """Email del buono di rimborso dopo un'ottimizzazione o una traduzione
    fallita/annullata. `kind`: "optimization" | "translation"; `lang`: lingua
    UI del job (fallback inglese)."""
    if not (email and _smtp_available()):
        return
    t = _i18n.pick(_VOUCHER_I18N, lang)
    what = t["what_names"].get(kind) or t["what_names"]["optimization"]
    expiry = _voucher_expiry()
    amount = f"{amount_eur:.2f}"
    title = html.escape(book_title or "") or "&mdash;"
    bonus = t["bonus"].format(pct=VOUCHER_BONUS_PERCENT) if bonus_applied else ""
    subject = t["subject"].format(amount=amount)
    failed = t["failed"].format(what=what, title=title, bonus=bonus)
    use = t["use"].format(email=html.escape(email))
    html_body = _layout.layout(f"""  <h2 style="color:#2c3e50">&#x1F381; {t["heading"]}</h2>
  <p>{failed}</p>
  {_layout.voucher_box(code, amount, expiry, code_label=t["code"] + ":", value_label=t["value"], expiry_label=t["expiry"])}
  <p>{use}</p>
  <p style="font-size:.85em;color:#666">{t["note"]}</p>""", BASE_URL)
    _send_email(email, subject, html_body)


# ---------------------------------------------------------------------------
# Voce campionata: email transazionali in sette lingue (spec \u00a78)
# ---------------------------------------------------------------------------

def _i18n_table(table, lang):
    """Testi della lingua con fallback PER CHIAVE su `en` (i18n.pick)."""
    return _i18n.pick(table, lang)


def _vc_t(lang):
    return _i18n_table(_VC_I18N, lang)


def _vc_num(value, kind="float"):
    """Converte un valore numerico per l'interpolazione email. `None` se non
    convertibile: il chiamante deve allora ritornare `False` senza inviare.
    Tiene le coercizioni fuori dal try/except di `_vc_send` (che scatta solo
    dopo il controllo lingua/email), cosi' un `amount_eur=None` o
    `stage=\"x\"` non solleva mai fuori dalle funzioni pubbliche."""
    try:
        return int(value) if kind == "int" else float(value)
    except (TypeError, ValueError):
        return None


def _i18n_send(table, tag, email, lang, subject_key, body_keys, **values):
    """Compone e manda una email dai testi `table` (lingua -> chiave, fallback
    per chiave su en). `body_keys`: chiavi da concatenare, piu' `footer` se
    c'e'. I valori vengono escapati tranne gli URL (chiavi *_url). Ritorna
    False su qualunque errore: chi chiama sta gia' nel flusso."""
    t = _i18n_table(table, lang)
    if not t or not email:
        return False
    safe = {k: (v if k.endswith("_url") else html.escape(str(v))) for k, v in values.items()}
    try:
        subject = t[subject_key].format(**safe)
        body = "".join(t[k].format(**safe) for k in body_keys) + t.get("footer", "")
        return bool(_send_email(email, subject, body))
    except Exception as e:      # noqa: BLE001
        print(f"[email] {tag} {subject_key} non inviata: {type(e).__name__}: {e}", flush=True)
        return False


def _vc_send(email, lang, subject_key, body_keys, **values):
    return _i18n_send(_VC_I18N, "voice clone", email, lang, subject_key, body_keys, **values)


def send_voice_clone_paid(email, lang, *, voice_code, amount_eur, resume_url, manage_url, delete_url):
    amount = _vc_num(amount_eur)
    if amount is None:
        return False
    return _vc_send(email, lang, "paid_subject", ("paid_body",), voice_code=voice_code,
                    amount=f"{amount:.2f}", resume_url=resume_url,
                    manage_url=manage_url, delete_url=delete_url)


def send_voice_clone_confirm(email, lang, *, confirm_code, device_name, identity, hours=24):
    """Il codice arriva al proprietario con quello che chi lo chiede ha
    dichiarato (nome del dispositivo e presentazione), escapato come ogni
    altro valore: e' testo libero di uno sconosciuto."""
    return _vc_send(email, lang, "confirm_subject", ("confirm_body",),
                    confirm_code=confirm_code, device_name=device_name,
                    identity=identity, hours=hours)


def send_voice_clone_device_added(email, lang, *, devices_url, device_name):
    return _vc_send(email, lang, "device_subject", ("device_body",), devices_url=devices_url,
                    device_name=device_name)


def send_voice_clone_ready(email, lang, *, voice_code, manage_url, delete_url, retention_days):
    return _vc_send(email, lang, "ready_subject", ("ready_body",), voice_code=voice_code,
                    manage_url=manage_url, delete_url=delete_url, retention_days=retention_days)


def send_voice_clone_expiring(email, lang, *, days, manage_url):
    return _vc_send(email, lang, "expiring_subject", ("expiring_body",), days=days,
                    manage_url=manage_url)


# ---------------------------------------------------------------------------
# Account: codice di accesso / cancellazione (i18n/account_emails.json)
# ---------------------------------------------------------------------------

_ACCT_I18N = _i18n.load("account_emails")


def _acct_t(lang):
    return _i18n_table(_ACCT_I18N, lang)


def _acct_send(email, lang, subject_key, body_key, **values):
    return _i18n_send(_ACCT_I18N, "account", email, lang, subject_key, (body_key,), **values)


def send_account_code(email, lang, *, code, link_url, purpose, minutes):
    """Codice a 6 cifre + magic link. `purpose`: login | delete."""
    if purpose not in ("login", "delete"):
        return False
    minutes_n = _vc_num(minutes, kind="int")
    if minutes_n is None:
        return False
    return _acct_send(email, lang, f"{purpose}_subject", f"{purpose}_body",
                      code=code, link_url=link_url, minutes=minutes_n)


def send_account_deleted(email, lang):
    return _acct_send(email, lang, "deleted_subject", "deleted_body")


def send_voice_clone_reminder(email, lang, *, resume_url, stage):
    stage_n = _vc_num(stage, kind="int")
    if stage_n is None:
        return False
    key = "reminder_body_2" if stage_n >= 2 else "reminder_body_1"
    return _vc_send(email, lang, "reminder_subject", (key,), resume_url=resume_url)


def send_voice_clone_refunded(email, lang, *, amount_eur, method, reason, voucher_code=None,
                              voucher_amount=None, expiry_days=None):
    if method not in ("paypal", "voucher"):
        return False
    amount = _vc_num(amount_eur)
    if amount is None:
        return False
    t = _vc_t(lang)
    reason_text = t.get("refund_reason_" + reason) or t.get("refund_reason_user_rejected") or ""
    if method == "paypal":
        if not voucher_code:
            return False
        v_amount = _vc_num(voucher_amount if voucher_amount is not None else amount)
        if v_amount is None:
            return False
        return _vc_send(email, lang, "refund_subject", ("refund_body_paypal",), reason=reason_text,
                        voucher_code=voucher_code,
                        voucher_amount=f"{v_amount:.2f}",
                        expiry_days=expiry_days if expiry_days is not None else VOUCHER_EXPIRY_DAYS,
                        amount=f"{amount:.2f}")
    return _vc_send(email, lang, "refund_subject", ("refund_body_voucher",), reason=reason_text,
                    amount=f"{amount:.2f}")


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
    html_body = _layout.layout(f"""  <h2 style="color:#2c3e50">&#x1F381; Your voucher</h2>
  <p>Here is your voucher worth <strong>EUR {amount_eur:.2f}</strong>, which you can use for premium services on audiobook-maker.com (premium voices, AI text optimisation or AI translations):</p>
  {_layout.voucher_box(code_safe, f"{amount_eur:.2f}", value_label="Value")}
  <p>Please use it within <strong>{days_int} days</strong> from <strong>{gen_date}</strong>.</p>
  <p>Thank you for your support!</p>""", BASE_URL, extra_style=";color:#333")
    return _send_email(email, subject, html_body)


def _send_gemini_overload_email(email, amount_eur, book_title, voucher_code=None,
                                 retry_after_sec=0, lang="it"):
    """Notifica all'utente che il job non e' stato avviato perche' il motore
    voci PREMIUM e' temporaneamente sovraccarico. Include il rimborso integrale.

    voucher_code valorizzato => pagamento PayPal, e' stato emesso un voucher.
    voucher_code None => pagamento via voucher, importo ri-accreditato.
    `lang`: lingua UI del job (fallback inglese per chiave).
    """
    if not (email and _smtp_available()):
        return
    t = _i18n.pick(_PREMIUM_I18N, lang)
    title_safe = _esc_html(_sanitize_header(book_title or t["default_title"], max_len=120))
    amount = f"{amount_eur:.2f}"
    subject = t["overload_subject"].format(amount=amount)
    refund_block = _premium_refund_block(t, amount, voucher_code, email)
    retry_hint = ""
    if retry_after_sec and retry_after_sec > 0:
        hours = max(1, retry_after_sec // 3600)
        retry_hint = "<p>" + (t["overload_retry_1"] if hours == 1
                              else t["overload_retry_n"].format(hours=hours)) + "</p>"
    html_body = _layout.layout(f"""  <h2 style="color:#c0392b">{t["overload_heading"]}</h2>
  <p>{t["hello"]}</p>
  <p>{t["overload_intro"].format(title=title_safe)}</p>
  <p>{t["overload_reason"]}</p>
  <p>{t["overload_refund"]}</p>
  {refund_block}
  {retry_hint}
  <p>{t["apology"]}</p>""", BASE_URL)
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
    with _admin_failure_lock:
        if not _throttle_ok(_admin_failure_last, key, 60.0):
            print(f"[admin] Failure alert throttled for {key}")
            return

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
            refund_line = _layout.row("Rimborso", f"{amount_eur:.2f} EUR — voucher PayPal "
                                                  f"<code>{voucher_code}</code>")
        else:
            refund_line = _layout.row("Rimborso", f"{amount_eur:.2f} EUR — riaccredito voucher originale")

    plan_line = ""
    if chunks_total is not None:
        if chunks_failed is not None:
            plan_line = _layout.row("Chunk", f"{chunks_failed}/{chunks_total} falliti")
        else:
            plan_line = _layout.row("Chunk previsti", f"{chunks_total}")
    chars_line = ""
    if chars_total is not None:
        chars_line = _layout.row("Caratteri", f"{chars_total:,}")

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
    rows = "".join([
        _layout.row("Outcome audit", f"<code>{audit_outcome}</code>", width="40%"),
        _layout.row("Utente", email_safe),
        _layout.row("Libro", title_safe),
        plan_line, chars_line, refund_line,
        _layout.row("Dettaglio", reason_safe or "—", last=True, mono=True),
    ])
    html_body = _layout.admin_alert(
        f"Gemini TTS — {kind_label}", color,
        subtitle_html=(f'Job <code style="background:rgba(255,255,255,.18);padding:2px 6px;'
                       f'border-radius:3px">{job_id}</code>'),
        rows_html=rows, after_html=forensic_block,
        note_html=("Alert generato automaticamente. Per disattivare rimuovere <code>ABM_ADMIN_EMAIL</code>. "
                   f"Console eventi: <code>{BASE_URL}/admin/#tab-gemini</code>"))
    try:
        _send_email(ADMIN_EMAIL, subject, html_body)
        print(f"[admin] Failure alert sent for {key} ({kind_label})")
    except Exception as e:
        print(f"[admin] Failed to send failure alert for {key}: {e}")


def admin_notify_margin_anomaly(job_id, kind, provider, book_title="",
                                revenue_eur=0.0, cost_est_eur=0.0,
                                cost_actual_eur=0.0, list_actual_eur=0.0,
                                threshold_eur=0.0, margin_expected_eur=0.0,
                                margin_actual_eur=0.0, chars_total=None,
                                outcome="", detail=""):
    """Notifica A POSTERIORI all'admin su anomalia di margine di un job PREMIUM.

    Non blocca e non influenza nulla: il job e' gia' terminato quando questa
    parte. E' un rilevatore contabile, non una barriera.

    kind:
      "free_over_threshold" -> URGENTE. Un job servito GRATIS (sotto la soglia
          di gratuita') e' costato piu' della soglia stessa: la decisione di non
          far pagare si e' rivelata sbagliata a consuntivo. E' la firma
          dell'incidente Q9lQN3RrapCvGLSonVnzmA (quotato 0,35 EUR, costo reale
          a doppia cifra).
      "margin_drop" -> il margine reale e' sceso a meno della meta' di quello
          atteso ex-ante. Segnala deriva del modello di stima costo.

    Throttle: 1 invio ogni 60s per job_id+kind (riusa il lock delle failure).
    """
    if not ADMIN_EMAIL or not _smtp_available():
        return
    key = f"{job_id}::margin::{kind}"
    with _admin_failure_lock:
        if not _throttle_ok(_admin_failure_last, key, 60.0):
            print(f"[admin] Margin alert throttled for {key}")
            return

    urgent = (kind == "free_over_threshold")
    if urgent:
        kind_label = "URGENTE — job GRATIS sopra la soglia di costo"
        color = "#b91c1c"
        lead = (f"Il job e' stato servito <strong>gratuitamente</strong> perche' "
                f"quotato sotto la soglia di {threshold_eur:.2f} EUR, ma a "
                f"consuntivo ne e' costati di piu'. Verificare che la stima "
                f"ex-ante non sia stata falsata.")
    else:
        kind_label = "Margine sotto le attese"
        color = "#d97706"
        lead = ("Il margine reale del job e' sceso sensibilmente sotto quello "
                "atteso al momento della quotazione. Nessun impatto sul "
                "cliente: segnala deriva del modello di stima del costo.")

    title_safe = _esc_html(_sanitize_header(book_title or "(senza titolo)", max_len=120))
    prov_safe = _esc_html(_sanitize_header(provider or "", max_len=40))
    detail_safe = _esc_html(_sanitize_header(detail or "", max_len=300))
    outcome_safe = _esc_html(_sanitize_header(outcome or "", max_len=60))
    subject = _sanitize_header(
        f"[ABM-ADMIN] {'URGENTE ' if urgent else ''}Margine {prov_safe} — "
        f"job {job_id[:8]}", max_len=180)

    chars_line = _layout.row("Caratteri", f"{chars_total:,}") if chars_total is not None else ""
    thr_line = _layout.row("Soglia gratuità", f"{threshold_eur:.2f} EUR") if urgent else ""

    rows = "".join([
        _layout.row("Libro", title_safe, width="46%"),
        _layout.row("Incassato", f"{revenue_eur:.2f} EUR"),
        thr_line,
        _layout.row("Costo provider stimato", f"{cost_est_eur:.4f} EUR"),
        _layout.row("Costo provider reale", f"<strong>{cost_actual_eur:.4f} EUR</strong>"),
        _layout.row("Listino sui consumi reali", f"{list_actual_eur:.2f} EUR"),
        _layout.row("Margine atteso", f"{margin_expected_eur:.4f} EUR"),
        _layout.row("Margine reale", f"<strong>{margin_actual_eur:.4f} EUR</strong>"),
        chars_line,
        _layout.row("Outcome audit", f"<code>{outcome_safe or '-'}</code>"),
        _layout.row("Dettaglio", detail_safe or "-", last=True, mono=True),
    ])
    html_body = _layout.admin_alert(
        kind_label, color,
        subtitle_html=(f'Job <code style="background:rgba(255,255,255,.18);padding:2px 6px;'
                       f'border-radius:3px">{job_id}</code> &middot; {prov_safe}'),
        lead_html=lead, rows_html=rows,
        note_html=("Alert automatico a consuntivo. Disattivabile con <code>ABM_MARGIN_ALERT=0</code>. "
                   f"Audit: <code>{BASE_URL}/admin/audit-premium</code>"))
    try:
        _send_email(ADMIN_EMAIL, subject, html_body)
        print(f"[admin] Margin alert sent for {key} ({kind})")
    except Exception as e:
        print(f"[admin] Failed to send margin alert for {key}: {e}")


def admin_notify_tts_backend_switch(model_key, reason, detail, job_id,
                                    credit_left_usd=None,
                                    probe_first_sec=None):
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

    # In USD: e' la valuta in cui Cloudflare denomina il credito AI
    # Gateway, quindi la cifra qui e quella sulla dashboard del fornitore si
    # confrontano a occhio. Un importo in euro costringerebbe chi legge di
    # notte a rifare il cambio a mente prima di decidere se ricaricare.
    credit_row = ""
    if credit_left_usd is not None:
        credit_row = _layout.kv("Credito residuo (stima)", f"{credit_left_usd:.2f} USD")

    # `probe_first_sec` assente significa "nessuna sonda armata": rientro
    # automatico spento per configurazione, oppure causa di trip non
    # sondabile (lo stato illeggibile del fail-safe non si riarma mai da
    # solo). In quel caso l'unica via di rientro resta la console, e l'email
    # non deve promettere un appuntamento che nessuno ha fissato.
    probe_label = _fmt_durata_it(probe_first_sec) if probe_first_sec else ""
    if probe_label:
        probe_row = _layout.kv("Prima sonda di rientro", f"fra {_esc_html(probe_label)}")
        probe_par = (
            "<p><strong>Il rientro si tenta da solo.</strong> Una sonda in "
            "background - poche parole di sintesi, nessun utente collegato - "
            f"riprova Cloudflare fra {_esc_html(probe_label)}, poi a "
            "intervalli doppi a ogni fallimento fino a un tetto; al primo "
            "esito buono il modello torna su Cloudflare e ricevi una seconda "
            "email. Nessun job viene mai usato per provare: un audiolibro "
            "rimandato su un backend ancora guasto costerebbe l'intera "
            "generazione, la sonda costa una richiesta rifiutata.</p>"
            "<p>Se la causa e' il credito esaurito la sonda non basta: "
            "ricarica e riallinea <code>ABM_CF_CREDIT_BALANCE_USD</code>, "
            "oppure riattiva subito Cloudflare dal pannello "
            "<em>Backend TTS</em> della console admin senza aspettare il "
            "prossimo appuntamento.</p>")
    else:
        probe_row = ""
        probe_par = (
            "<p><strong>Il rientro e' manuale.</strong> Per questo trip non "
            "e' stata armata alcuna sonda: risolta la causa (di norma: "
            "ricaricare il credito Cloudflare), riattiva Cloudflare dal "
            "pannello <em>Backend TTS</em> della console admin.</p>")

    html_body = _layout.admin_panel("TTS: passaggio automatico a Vertex", "#c0392b", f"""        <p>Il modello <strong>{model_safe}</strong> non viene piu' servito da
           Cloudflare. I job in corso proseguono su Vertex dal chunk
           corrente, senza interruzione e senza differenza udibile.</p>
        <table cellpadding="6" style="border-collapse:collapse;font-size:.95em">
          <tr><td><strong>Causa</strong></td><td>{reason_label_safe}</td></tr>
          <tr><td><strong>Dettaglio</strong></td><td style="font-family:monospace;font-size:12px">{detail_safe}</td></tr>
          <tr><td><strong>Job che ha rilevato</strong></td><td><code>{job_safe}</code></td></tr>
          {credit_row}
          {probe_row}
        </table>
        <p style="background:#fff4e5;padding:10px;border-left:4px solid #d97706;margin-top:14px">
          <strong>Perche' e' urgente:</strong> su Vertex il margine scende
          quasi al pareggio, mentre su Cloudflare resta ampio. Il servizio
          continua a funzionare, ma ogni ora in questo stato e' margine
          perso su ogni job servito.</p>
        {probe_par}""")

    try:
        _send_email(ADMIN_EMAIL, subject, html_body)
        print(f"[admin] Notifica switch backend TTS inviata per {model_key} "
              f"({reason})")
    except Exception as e:
        print(f"[admin] Invio notifica switch backend TTS fallito: {e}")


def _fmt_durata_it(secondi):
    """Durata in italiano leggibile a colpo d'occhio ("2 ore e 35 minuti").

    Le email di failover si leggono di notte e sul telefono: "9312 s"
    obbliga chi legge a fare una divisione prima di capire se il disservizio
    e' durato dieci minuti o tre ore. Restituisce "" per un valore assente o
    non numerico, cosi' il chiamante puo' semplicemente omettere la riga
    invece di stampare un segnaposto.
    """
    try:
        tot = int(max(0, float(secondi)))
    except (TypeError, ValueError):
        return ""
    if tot < 60:
        return f"{tot} second{'o' if tot == 1 else 'i'}"
    minuti, ore = (tot // 60) % 60, tot // 3600
    if not ore:
        return f"{minuti} minut{'o' if minuti == 1 else 'i'}"
    testa = f"{ore} or{'a' if ore == 1 else 'e'}"
    if not minuti:
        return testa
    return f"{testa} e {minuti} minut{'o' if minuti == 1 else 'i'}"


def admin_notify_tts_backend_return(model_key, probe_attempts=0,
                                    down_seconds=None, credit_left_usd=None):
    """Notifica all'admin: il modello e' RIENTRATO su Cloudflare da solo.

    Gemella speculare di `admin_notify_tts_backend_switch`, tenuta separata
    per la stessa ragione per cui lo e' il pre-allarme sul credito: dice il
    contrario, e chi legge l'oggetto di notte deve capire dalla prima riga
    se il servizio sta girando al margine ridotto oppure no.

    Non e' un'email di cortesia. Finche' non arriva, l'admin deve assumere
    che il servizio giri su Vertex: e' la chiusura esplicita dell'incidente
    aperto dall'email di switch, e senza di essa un failover risolto da solo
    resterebbe indistinguibile da uno ancora in corso.

    Immediata e non nel digest per simmetria con lo switch: un rientro
    annunciato il giorno dopo farebbe intervenire a mano su un guasto gia'
    passato.

    Un guasto SMTP non propaga: il rientro e' gia' avvenuto e persistito,
    l'email e' un di piu'.
    """
    if not ADMIN_EMAIL or not _smtp_available():
        return

    model_safe = _esc_html(_sanitize_header(model_key or "", max_len=80))
    subject = _sanitize_header(
        f"[ABM-ADMIN] TTS {model_key}: rientro automatico su Cloudflare",
        max_len=200)

    try:
        tentativi = max(0, int(probe_attempts or 0))
    except (TypeError, ValueError):
        tentativi = 0

    # `down_seconds=None` = durata non ricostruibile (marca di trip assente o
    # illeggibile). Meglio omettere la riga che stampare uno zero, che
    # significherebbe "nessun disservizio", cioe' il contrario del vero.
    durata = _fmt_durata_it(down_seconds)
    durata_row = _layout.kv("Durata del failover", _esc_html(durata)) if durata else ""
    credit_row = ""
    if credit_left_usd is not None:
        credit_row = _layout.kv("Credito residuo (stima)", f"{credit_left_usd:.2f} USD")

    html_body = _layout.admin_panel("TTS: rientro automatico su Cloudflare", "#1e8449", f"""        <p>Il modello <strong>{model_safe}</strong> e' tornato su Cloudflare:
           una sonda di rientro ha ottenuto audio valido e il breaker e'
           stato riarmato. I job che partono da ora usano di nuovo
           Cloudflare; quelli gia' in corso finiscono su Vertex, dove sono
           cominciati.</p>
        <table cellpadding="6" style="border-collapse:collapse;font-size:.95em">
          <tr><td><strong>Sonde fallite prima del rientro</strong></td><td>{tentativi}</td></tr>
          {durata_row}
          {credit_row}
        </table>
        <p style="background:#eafaf1;padding:10px;border-left:4px solid #1e8449;margin-top:14px">
          Il margine torna quello pieno di Cloudflare. Non serve alcun
          intervento: questa email chiude il failover annunciato dall'email
          di switch.</p>
        <p>Se il failover era dovuto al credito esaurito, il rientro
           significa che la ricarica e' andata a buon fine: controlla che
           <code>ABM_CF_CREDIT_BALANCE_USD</code> sia riallineato e che il
           ledger sia stato azzerato dal pannello <em>Backend TTS</em>,
           altrimenti il residuo stimato resta sbagliato per il ciclo
           successivo.</p>""")

    try:
        _send_email(ADMIN_EMAIL, subject, html_body)
        print(f"[admin] Notifica rientro backend TTS inviata per {model_key}")
    except Exception as e:
        print(f"[admin] Invio notifica rientro backend TTS fallito: {e}")


def admin_notify_cf_credit_low(model_key, credit_left_usd, threshold_usd):
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
    `ABM_CF_CREDIT_BALANCE_USD` dichiarato dall'admin meno la spesa
    accumulata dal ledger locale. Tutti gli importi sono in USD, la valuta
    in cui Cloudflare denomina il credito: chi riceve questa email deve
    poterli confrontare con la dashboard del fornitore senza cambio di
    mezzo. Per questo l'email chiede di riallineare
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
        left = float(credit_left_usd)
    except (TypeError, ValueError):
        left = 0.0
    try:
        threshold = float(threshold_usd)
    except (TypeError, ValueError):
        threshold = 0.0
    subject = _sanitize_header(
        f"[ABM-ADMIN] Credito Cloudflare basso: {left:.2f} USD residui "
        f"(soglia {threshold:.2f})", max_len=200)

    html_body = _layout.admin_panel("Credito Cloudflare in esaurimento", "#d97706", f"""        <p>Il credito Cloudflare stimato e' sceso sotto la soglia di
           pre-allarme. <strong>Il TTS gira ancora su Cloudflare</strong>: non
           e' avvenuto alcun failover, e non ci sono job in errore.</p>
        <table cellpadding="6" style="border-collapse:collapse;font-size:.95em">
          <tr><td><strong>Modello</strong></td><td><code>{model_safe}</code></td></tr>
          <tr><td><strong>Credito residuo (stima)</strong></td><td>{left:.2f} USD</td></tr>
          <tr><td><strong>Soglia di pre-allarme</strong></td><td>{threshold:.2f} USD</td></tr>
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
          <li>Aggiornare <code>ABM_CF_CREDIT_BALANCE_USD</code> nell'unit
              systemd col nuovo saldo dichiarato <strong>in USD</strong>, poi
              <code>daemon-reload</code>
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
        <p style="color:#888;font-size:12px;margin-top:16px">Il saldo Cloudflare non e' leggibile via API: questo importo e' una stima, in USD come il credito del fornitore. Per disattivare l'avviso: <code>ABM_CF_CREDIT_BALANCE_USD=0</code>. Console: <code>{BASE_URL}/admin/</code></p>""")

    try:
        _send_email(ADMIN_EMAIL, subject, html_body)
        print(f"[admin] Pre-allarme credito Cloudflare inviato per {model_key} "
              f"(residuo stimato {left:.2f} USD)")
    except Exception as e:
        print(f"[admin] Invio pre-allarme credito Cloudflare fallito: {e}")


def admin_notify_gemini_model_unavailable(model_key, detail, job_id, cooldown_sec):
    """Notifica IMMEDIATA: un modello Gemini senza failover e' fuori servizio.

    Il job che ha visto l'errore e' fallito con rimborso standard; il modello
    e' nascosto dal catalogo per `cooldown_sec` o fino al reset dal pannello
    «Backend TTS». Sec: `detail` e' solo HTML-escapato, mai interpretato.
    Un guasto SMTP non propaga.
    """
    if not ADMIN_EMAIL or not _smtp_available():
        return
    model_safe = _esc_html(_sanitize_header(model_key or "", max_len=80))
    detail_safe = _esc_html(_sanitize_header(detail or "", max_len=300))
    job_safe = _esc_html(_sanitize_header(job_id or "", max_len=120))
    minutes = int(cooldown_sec or 0) // 60
    subject = _sanitize_header(
        f"[ABM-ADMIN] TTS {model_key}: modello non disponibile", max_len=200)
    html_body = _layout.admin_panel("Modello TTS non disponibile", "#b91c1c", f"""        <p>Errore permanente sul canale del modello: il job e' stato fermato con
           rimborso standard e il modello e' nascosto agli utenti.</p>
        <table cellpadding="6" style="border-collapse:collapse;font-size:.95em">
          <tr><td><strong>Modello</strong></td><td><code>{model_safe}</code></td></tr>
          <tr><td><strong>Job</strong></td><td><code>{job_safe}</code></td></tr>
          <tr><td><strong>Errore</strong></td><td><code>{detail_safe}</code></td></tr>
        </table>
        <p>Rientro automatico fra {minutes} minuti, oppure con «Riattiva» nel
           pannello «Backend TTS» della console admin dopo aver risolto la causa
           (chiave API, credito, abilitazione del modello).</p>""")
    try:
        _send_email(ADMIN_EMAIL, subject, html_body)
    except Exception as e:
        print(f"[email] admin_notify_gemini_model_unavailable fallita: {e}")


def _send_gemini_cancelled_partial_email(email, paid_eur, retained_eur,
                                          refund_eur, voucher_code,
                                          book_title, download_url, lang="it",
                                          auto_cancel=False):
    """Notifica all'utente che un job voci PREMIUM in corso e' stato
    interrotto: l'MP3 parziale e' disponibile al download, il rimborso e'
    stato emesso al netto della quota gia' consumata (costo provider +
    commissioni non recuperabili).

    - voucher_code valorizzato => pagamento PayPal, nuovo voucher emesso per
      l'importo rimborsato (refund_eur).
    - voucher_code None => pagamento via voucher, refund_eur ri-accreditato
      silenziosamente sul voucher originale.
    - auto_cancel=True => l'interruzione NON e' stata chiesta dall'utente
      (heartbeat scaduto, job soppiantato): scrivergli "hai annullato tu"
      sarebbe falso e lo lascia senza spiegazione di cosa e' successo.
    """
    if not (email and _smtp_available()):
        return
    t = _i18n.pick(_PREMIUM_I18N, lang)
    title_safe = _esc_html(_sanitize_header(book_title or t["default_title"], max_len=120))
    refund = f"{refund_eur:.2f}"
    kind = "autocancel" if auto_cancel else "cancel"
    subject = t[f"{kind}_subject"].format(amount=refund)
    heading = t[f"{kind}_heading"]
    intro = t[f"{kind}_intro"].format(title=title_safe)
    note = f"<p>{t['autocancel_note']}</p>" if auto_cancel else ""
    dl_safe = (download_url or "").replace('"', "%22")
    if refund_eur > 0:
        refund_block = _premium_refund_block(t, refund, voucher_code, email)
    else:
        refund_block = _layout.notice(t["no_refund"].format(retained=f"{retained_eur:.2f}"))
    html_body = _layout.layout(f"""  <h2 style="color:#d97706">{heading}</h2>
  <p>{t["hello"]}</p>
  <p>{intro}</p>
  <p>{t["partial_saved"]}</p>
  <p style="text-align:center;margin:20px 0">
    <a href="{dl_safe}" style="display:inline-block;background:#8b5cf6;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600">{t["download_btn"]}</a>
  </p>
  <h3 style="margin-top:28px;color:#333">{t["refund_title"]}</h3>
  <table style="width:100%;border-collapse:collapse;font-size:14px;margin:12px 0">
    <tr><td style="padding:6px 0;color:#666">{t["paid_label"]}</td><td style="padding:6px 0;text-align:right"><strong>{paid_eur:.2f} EUR</strong></td></tr>
    <tr><td style="padding:6px 0;color:#666">{t["retained_label"]}</td><td style="padding:6px 0;text-align:right">{retained_eur:.2f} EUR</td></tr>
    <tr><td style="padding:6px 0;color:#666;border-top:1px solid #eee"><strong>{t["refund_label"]}</strong></td><td style="padding:6px 0;text-align:right;border-top:1px solid #eee"><strong style="color:#059669">{refund} EUR</strong></td></tr>
  </table>
  {refund_block}
  {note}
  <p style="font-size:.9em;color:#666">{t["retained_note"]}</p>""", BASE_URL)
    _send_email(email, subject, html_body)


def _send_gemini_failed_refund_email(email, amount_eur, book_title, reason_label, voucher_code=None,
                                     lang="it"):
    """Notifica all'utente che la generazione voci PREMIUM e' fallita (quota
    giornaliera del provider, limite di spesa, qualita', riavvio) e che il
    rimborso integrale e' stato emesso.

    `reason_label`: chiave di `reason_names` (quota | budget | quality |
    interrupted_restart), localizzata; un testo libero viene mostrato
    escapato cosi' com'e'.
    - voucher_code valorizzato => pagamento PayPal, e' stato emesso un nuovo
      voucher (con eventuale bonus) all'email.
    - voucher_code None => pagamento via voucher, l'importo e' stato
      ri-accreditato sul voucher originale.
    """
    if not (email and _smtp_available()):
        return
    t = _i18n.pick(_PREMIUM_I18N, lang)
    title_safe = _esc_html(_sanitize_header(book_title or t["default_title"], max_len=120))
    amount = f"{amount_eur:.2f}"
    subject = t["failed_subject"].format(amount=amount)
    reason_html = t["reason_names"].get(reason_label) or _esc_html(reason_label)
    refund_block = _premium_refund_block(t, amount, voucher_code, email)
    html_body = _layout.layout(f"""  <h2 style="color:#c0392b">{t["failed_heading"]}</h2>
  <p>{t["hello"]}</p>
  <p>{t["failed_intro"].format(title=title_safe)}</p>
  <p>{t["failed_reason"].format(reason=reason_html)}</p>
  <p>{t["failed_refund"]}</p>
  {refund_block}
  <p>{t["failed_retry"]}</p>""", BASE_URL)
    _send_email(email, subject, html_body)
