#!/usr/bin/env python3
"""
Audiobook Maker — SMTP Test Script

Verifica che la configurazione SMTP sia corretta e che l'invio email funzioni.
Usa le stesse variabili d'ambiente dell'app (ABM_SMTP_*).

Uso:
    python3 test_smtp.py                          # test con email del mittente
    python3 test_smtp.py destinatario@email.com   # test con destinatario specifico

Variabili d'ambiente richieste:
    ABM_SMTP_HOST   — server SMTP (es. smtp.gmail.com)
    ABM_SMTP_PORT   — porta (default: 587)
    ABM_SMTP_USER   — username/email per login
    ABM_SMTP_PASS   — password o app-password
    ABM_SMTP_FROM   — mittente (default: ABM_SMTP_USER)
    ABM_BASE_URL    — URL base del sito (opzionale, per il test)
"""

import os
import sys
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ── Colori terminale ──
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def ok(msg):   print(f"  {GREEN}✔{RESET} {msg}")
def fail(msg): print(f"  {RED}✘{RESET} {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET} {msg}")
def info(msg): print(f"  {CYAN}ℹ{RESET} {msg}")


def main():
    print(f"\n{BOLD}══════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Audiobook Maker — Test configurazione SMTP{RESET}")
    print(f"{BOLD}══════════════════════════════════════════════{RESET}\n")

    # ── 1. Verifica variabili d'ambiente ──
    print(f"{BOLD}1. Variabili d'ambiente{RESET}")

    host = os.environ.get("ABM_SMTP_HOST", "")
    port = os.environ.get("ABM_SMTP_PORT", "587")
    user = os.environ.get("ABM_SMTP_USER", "")
    pwd  = os.environ.get("ABM_SMTP_PASS", "")
    frm  = os.environ.get("ABM_SMTP_FROM", user or "noreply@audiobook-maker.com")
    base = os.environ.get("ABM_BASE_URL", "")

    errors = 0

    if host:
        ok(f"ABM_SMTP_HOST = {host}")
    else:
        fail("ABM_SMTP_HOST non impostata")
        errors += 1

    try:
        port_int = int(port)
        ok(f"ABM_SMTP_PORT = {port_int}")
    except ValueError:
        fail(f"ABM_SMTP_PORT = '{port}' (non è un numero valido)")
        errors += 1
        port_int = 587

    if user:
        ok(f"ABM_SMTP_USER = {user}")
    else:
        fail("ABM_SMTP_USER non impostata")
        errors += 1

    if pwd:
        masked = pwd[:2] + "*" * (len(pwd) - 4) + pwd[-2:] if len(pwd) > 5 else "***"
        ok(f"ABM_SMTP_PASS = {masked} ({len(pwd)} caratteri)")
    else:
        fail("ABM_SMTP_PASS non impostata")
        errors += 1

    ok(f"ABM_SMTP_FROM = {frm}")

    if base:
        ok(f"ABM_BASE_URL  = {base}")
    else:
        warn("ABM_BASE_URL non impostata (i link nelle email non saranno completi)")

    if errors > 0:
        print(f"\n{RED}{BOLD}  ✘ {errors} variabili mancanti. Configura e riprova.{RESET}")
        print(f"\n  Esempio (aggiungi a /etc/environment o al file .env del servizio):")
        print(f"    export ABM_SMTP_HOST=smtp.gmail.com")
        print(f"    export ABM_SMTP_PORT=587")
        print(f"    export ABM_SMTP_USER=tuo@email.com")
        print(f"    export ABM_SMTP_PASS=xxxx-xxxx-xxxx-xxxx")
        print(f"    export ABM_BASE_URL=https://audiobook-maker.com\n")
        sys.exit(1)

    # ── 2. Test connessione SMTP ──
    print(f"\n{BOLD}2. Connessione SMTP{RESET}")

    info(f"Connessione a {host}:{port_int}...")
    t0 = time.time()

    try:
        if port_int == 465:
            server = smtplib.SMTP_SSL(host, port_int, timeout=15)
        else:
            server = smtplib.SMTP(host, port_int, timeout=15)
        elapsed = round((time.time() - t0) * 1000)
        ok(f"Connessione stabilita ({elapsed}ms)" + (" [SSL diretto]" if port_int == 465 else ""))
    except Exception as e:
        fail(f"Connessione fallita: {e}")
        print(f"\n  Possibili cause:")
        print(f"    - Firewall blocca la porta {port_int}")
        print(f"    - Host '{host}' non raggiungibile")
        print(f"    - Porta errata (prova 465 per SSL o 587 per STARTTLS)\n")
        sys.exit(1)

    # EHLO
    if port_int != 465:
        try:
            code, msg = server.ehlo()
            ok(f"EHLO → {code}")
        except Exception as e:
            fail(f"EHLO fallito: {e}")
            server.quit()
            sys.exit(1)
    else:
        ok("SSL diretto — EHLO gestito automaticamente")

    # STARTTLS (se non porta 25 e non porta 465)
    if port_int not in (25, 465):
        try:
            server.starttls()
            server.ehlo()
            ok("STARTTLS attivato")
        except Exception as e:
            fail(f"STARTTLS fallito: {e}")
            print(f"  Se il server usa SSL diretto (porta 465), imposta ABM_SMTP_PORT=465")
            server.quit()
            sys.exit(1)

    # Login
    info(f"Login come {user}...")
    try:
        server.login(user, pwd)
        ok("Login riuscito")
    except smtplib.SMTPAuthenticationError as e:
        fail(f"Autenticazione fallita: {e}")
        print(f"\n  Possibili cause:")
        print(f"    - Password errata o scaduta")
        print(f"    - Per Gmail: usa una App Password (non la password dell'account)")
        print(f"      → https://myaccount.google.com/apppasswords")
        print(f"    - Verifica che l'accesso alle app meno sicure sia abilitato\n")
        server.quit()
        sys.exit(1)
    except Exception as e:
        fail(f"Login fallito: {e}")
        server.quit()
        sys.exit(1)

    # ── 3. Invio email di test ──
    print(f"\n{BOLD}3. Invio email di test{RESET}")

    # Destinatario
    to_addr = sys.argv[1] if len(sys.argv) > 1 else user
    info(f"Destinatario: {to_addr}")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dl_url = f"{base}/dl/test-token-12345" if base else "https://audiobook-maker.com/dl/test-token-12345"

    subject = "Audiobook Maker — Test SMTP"
    html_body = f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <h2 style="color:#2c3e50">🎧 Test configurazione SMTP</h2>
      <p>Questa è un'email di test inviata da <strong>Audiobook Maker</strong>.</p>
      <p>Se la ricevi, la configurazione SMTP è corretta e le notifiche email funzioneranno.</p>

      <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;padding:16px;margin:20px 0">
        <strong>Dettagli configurazione:</strong><br>
        Server: {host}:{port_int}<br>
        Mittente: {frm}<br>
        Base URL: {base or '(non configurata)'}<br>
        Data test: {now}
      </div>

      <p>Ecco come apparirà l'email di notifica reale:</p>
      <hr style="border:none;border-top:1px solid #eee;margin:20px 0">

      <h2 style="color:#2c3e50">🎧 Il tuo audiolibro è pronto!</h2>
      <p>La generazione di <strong>Il Racconto dell'Anticristo</strong> è stata completata con successo.</p>
      <p style="margin:24px 0">
        <a href="{dl_url}" style="display:inline-block;padding:14px 28px;background:#3b82f6;color:white;
           text-decoration:none;border-radius:8px;font-weight:600;font-size:16px">
          ⬇️ Scarica i tuoi file
        </a>
      </p>
      <p style="color:#e74c3c;font-weight:600">
        ⏰ Attenzione: i file saranno disponibili per il download soltanto per 60 minuti
        a partire dalla ricezione di questa email. Dopo tale periodo verranno cancellati
        automaticamente.
      </p>

      <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
      <p style="color:#22c55e;font-weight:600;font-size:.9rem">
        ✅ Questo è un messaggio di test — la configurazione è corretta!
      </p>
      <p style="color:#999;font-size:12px">
        Generato automaticamente da test_smtp.py il {now}
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["From"] = frm
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        server.sendmail(frm, to_addr, msg.as_string())
        ok(f"Email inviata a {to_addr}")
    except Exception as e:
        fail(f"Invio fallito: {e}")
        server.quit()
        sys.exit(1)

    server.quit()
    ok("Connessione chiusa")

    # ── Riepilogo ──
    print(f"\n{GREEN}{BOLD}══════════════════════════════════════════════{RESET}")
    print(f"{GREEN}{BOLD}  ✔ Tutti i test superati!{RESET}")
    print(f"{GREEN}{BOLD}══════════════════════════════════════════════{RESET}")
    print(f"\n  Controlla la casella di {BOLD}{to_addr}{RESET}")
    print(f"  (anche nella cartella spam/junk).\n")
    print(f"  Se l'email è arrivata correttamente, la configurazione")
    print(f"  è pronta per l'uso con Audiobook Maker.\n")


if __name__ == "__main__":
    main()
