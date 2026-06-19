"""privacy_content.py — Informativa privacy (pagina /privacy).

Pagina statica multilingua (IT/EN) richiesta dal Play Store e dal GDPR.
Nessun dato dinamico: testo approvato dal titolare. Pattern self-contained
come le altre pagine HTML servite dall'app.
"""

_LAST_UPDATED = {"it": "18 giugno 2026", "en": "June 18, 2026"}

_TXT = {
    "it": {
        "lang": "it",
        "title": "Informativa sulla privacy — Audiobook Maker & Player",
        "updated_label": "Ultimo aggiornamento",
        "switch_label": "English",
        "switch_href": "/privacy?lang=en",
        "crumb": "Privacy",
        "footer": "Audiobook Maker — convertitore gratuito e open source da EPUB/PDF ad audiolibri.",
        "cookie_h": "8. Cookie e consenso",
        "cookie_p": "Il sito web usa cookie analitici (Google Analytics) solo previo tuo consenso, per misurare il traffico in forma aggregata; nessun cookie analitico viene impostato senza il tuo consenso. L'app mobile non usa cookie analitici. Puoi rivedere o modificare la tua scelta in qualsiasi momento.",
        "cookie_btn": "Gestisci preferenze cookie",
        "body": """
<h1>Informativa sulla privacy — Audiobook Maker &amp; Player</h1>

<h2>1. Titolare del trattamento</h2>
<p>Il titolare del trattamento è <strong>Luigi Frangiamone</strong> (Italia). Per
qualsiasi richiesta relativa ai tuoi dati personali puoi scrivere a
<a href="mailto:abm.luigi@gmail.com">abm.luigi@gmail.com</a>.</p>

<h2>2. Dati che trattiamo e finalità</h2>
<ul>
<li><strong>File che carichi</strong> (EPUB, PDF, TXT): elaborati per generare
l'audiolibro. Base giuridica: esecuzione del servizio richiesto.</li>
<li><strong>Indirizzo email</strong> (facoltativo): per inviarti la notifica di
completamento e il link di download. Base giuridica: esecuzione del servizio.</li>
<li><strong>Token di notifica push (Firebase Cloud Messaging)</strong> — solo
app: per avvisarti quando l'audiolibro è pronto. Base giuridica: esecuzione del
servizio.</li>
<li><strong>Identificativo pseudonimo del dispositivo/sessione e indirizzo
IP</strong>: per associare e gestire i lavori di conversione, sicurezza e
prevenzione abusi. Base giuridica: legittimo interesse.</li>
<li><strong>Dati di pagamento</strong> (per i servizi premium, lato web):
gestiti direttamente da <strong>PayPal</strong>; non trattiamo né conserviamo i
dati della tua carta.</li>
</ul>
<p>L'app raccoglie solo statistiche d'uso <strong>anonime e aggregate</strong> (un segnale di avvio, la piattaforma e la provenienza verso il sito), senza identificare l'utente né usare strumenti di terze parti; nessuna pubblicità.</p>

<h2>3. Fornitori che trattano i dati per nostro conto (sub-responsabili)</h2>
<p>Per erogare il servizio ci avvaliamo dei seguenti fornitori:</p>
<ul>
<li><strong>Google LLC / Google Ireland</strong> — sintesi vocale (Cloud
Text-to-Speech), elaborazione e traduzione testo (Vertex AI), notifiche push
(Firebase Cloud Messaging);</li>
<li><strong>Microsoft Corporation</strong> — sintesi vocale delle voci standard
(Edge TTS);</li>
<li><strong>DeepSeek</strong> — ottimizzazione ed elaborazione del testo tramite
intelligenza artificiale;</li>
<li><strong>Cloudflare, Inc.</strong> — archiviazione temporanea dei file
(storage);</li>
<li><strong>PayPal (Europe)</strong> — gestione dei pagamenti dei servizi
premium;</li>
<li><strong>serverSMTP (serversmtp.com)</strong> — invio delle email di
notifica.</li>
</ul>

<h2>4. Trasferimenti extra-UE</h2>
<p>Alcuni fornitori possono trattare i dati al di fuori dell'Unione Europea. In
tali casi il trasferimento avviene sulla base delle garanzie previste dal GDPR
(es. Clausole Contrattuali Standard).</p>

<h2>5. Conservazione</h2>
<p>I file caricati e gli audiolibri generati sono conservati
<strong>temporaneamente</strong> (di norma fino a circa 24 ore di disponibilità
online, più un'eventuale copia di backup a breve termine) e poi eliminati.
L'indirizzo email e il token di notifica sono conservati per il tempo necessario
alla consegna e, per il token, finché l'app resta installata/registrata.</p>

<h2>6. I tuoi diritti</h2>
<p>Hai diritto di accesso, rettifica, cancellazione, limitazione, opposizione e
portabilità dei dati, oltre al diritto di reclamo all'Autorità Garante. Per
esercitarli scrivi a <a href="mailto:abm.luigi@gmail.com">abm.luigi@gmail.com</a>.</p>

<h2>7. Modifiche</h2>
<p>Eventuali modifiche a questa informativa saranno pubblicate in questa pagina
con l'indicazione della data di aggiornamento.</p>
""",
    },
    "en": {
        "lang": "en",
        "title": "Privacy Policy — Audiobook Maker & Player",
        "updated_label": "Last updated",
        "switch_label": "Italiano",
        "switch_href": "/privacy?lang=it",
        "crumb": "Privacy",
        "footer": "Audiobook Maker — free &amp; open-source EPUB/PDF to audiobook converter.",
        "cookie_h": "8. Cookies and consent",
        "cookie_p": "The website uses analytics cookies (Google Analytics) only with your consent, to measure aggregate traffic; no analytics cookie is set without your consent. The mobile app uses no analytics cookies. You can review or change your choice at any time.",
        "cookie_btn": "Manage cookie preferences",
        "body": """
<h1>Privacy Policy — Audiobook Maker &amp; Player</h1>

<h2>1. Data controller</h2>
<p>The data controller is <strong>Luigi Frangiamone</strong> (Italy). For any
request regarding your personal data, please write to
<a href="mailto:abm.luigi@gmail.com">abm.luigi@gmail.com</a>.</p>

<h2>2. Data we process and purposes</h2>
<ul>
<li><strong>Files you upload</strong> (EPUB, PDF, TXT): processed to generate the
audiobook. Legal basis: performance of the requested service.</li>
<li><strong>Email address</strong> (optional): to send you the completion
notification and the download link. Legal basis: performance of the service.</li>
<li><strong>Push notification token (Firebase Cloud Messaging)</strong> — app
only: to notify you when the audiobook is ready. Legal basis: performance of the
service.</li>
<li><strong>Pseudonymous device/session identifier and IP address</strong>: to
associate and manage conversion jobs, security and abuse prevention. Legal basis:
legitimate interest.</li>
<li><strong>Payment data</strong> (for premium services, on the web): handled
directly by <strong>PayPal</strong>; we do not process or store your card
details.</li>
</ul>
<p>The app collects only <strong>anonymous, aggregate</strong> usage statistics (an app-open signal, the platform, and referral to the website), without identifying the user or using third-party tools; no advertising.</p>

<h2>3. Providers processing data on our behalf (sub-processors)</h2>
<p>To deliver the service we rely on the following providers:</p>
<ul>
<li><strong>Google LLC / Google Ireland</strong> — speech synthesis (Cloud
Text-to-Speech), text processing and translation (Vertex AI), push notifications
(Firebase Cloud Messaging);</li>
<li><strong>Microsoft Corporation</strong> — speech synthesis for standard voices
(Edge TTS);</li>
<li><strong>DeepSeek</strong> — AI-based text optimization and processing;</li>
<li><strong>Cloudflare, Inc.</strong> — temporary file storage;</li>
<li><strong>PayPal (Europe)</strong> — premium services payment handling;</li>
<li><strong>serverSMTP (serversmtp.com)</strong> — sending notification emails.</li>
</ul>

<h2>4. Transfers outside the EU</h2>
<p>Some providers may process data outside the European Union. In such cases the
transfer is based on the safeguards required by the GDPR (e.g. Standard
Contractual Clauses).</p>

<h2>5. Retention</h2>
<p>Uploaded files and generated audiobooks are stored <strong>temporarily</strong>
(typically up to about 24 hours of online availability, plus a possible
short-term backup copy) and then deleted. The email address and the notification
token are kept for the time needed for delivery and, for the token, as long as
the app stays installed/registered.</p>

<h2>6. Your rights</h2>
<p>You have the right to access, rectify, erase, restrict, object to and port your
data, as well as the right to lodge a complaint with the supervisory authority. To
exercise them, write to <a href="mailto:abm.luigi@gmail.com">abm.luigi@gmail.com</a>.</p>

<h2>7. Changes</h2>
<p>Any changes to this policy will be published on this page together with the
update date.</p>
""",
    },
}


def render_privacy_page(lang="it", base_url=""):
    """Ritorna l'HTML completo della pagina /privacy nella lingua richiesta.

    Stile coerente con le guide del sito (font DM Sans/DM Serif Display,
    variabili tema, breadcrumb + footer). Lingue: it (default), en.
    """
    t = _TXT.get(lang, _TXT["it"])
    updated = _LAST_UPDATED.get(t["lang"], _LAST_UPDATED["it"])
    home = base_url or "/"
    return f"""<!DOCTYPE html><html lang="{t['lang']}"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="index,follow">
<title>{t['title']}</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,500;0,600;0,700&amp;family=DM+Serif+Display&amp;display=swap" rel="stylesheet">
<style>
:root{{--bg:#f5f3ef;--srf:#fff;--brd:#d5d0c8;--tx:#2c2a26;--txd:#6b6760;--txm:#9e9890;--ac:#c47a2a;--ach:#d4903e;--r:12px}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'DM Sans','PingFang SC','Microsoft YaHei','Noto Sans SC',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--tx);line-height:1.7;padding:20px;max-width:720px;margin:0 auto}}
h1{{font-family:'DM Serif Display',Georgia,serif;font-size:2rem;color:var(--ac);margin:18px 0 4px;line-height:1.25}}
h2{{font-family:'DM Serif Display',Georgia,serif;font-size:1.4rem;margin:32px 0 12px;color:var(--tx)}}
p,li{{margin-bottom:10px;color:var(--txd)}}
ul{{padding-left:22px;margin-bottom:10px}}
strong{{color:var(--tx)}}
a{{color:var(--ac);text-decoration:none}}
a:hover{{color:var(--ach);text-decoration:underline}}
.breadcrumb{{font-size:.85rem;color:var(--txm);margin-bottom:16px}}
.langswitch{{font-size:.85rem;margin-bottom:18px}}
.updated{{font-size:.85rem;color:var(--txm);margin:6px 0 24px}}
footer{{margin-top:48px;padding-top:24px;border-top:1px solid var(--brd);font-size:.85rem;color:var(--txm)}}
.cookiebtn{{display:inline-block;margin-top:6px;padding:10px 22px;background:var(--ac);color:#fff;border-radius:8px;text-decoration:none;font-weight:600}}
.cookiebtn:hover{{background:var(--ach);color:#fff;text-decoration:none}}
</style></head><body>
<nav class="breadcrumb"><a href="{home}">Audiobook Maker</a> &rsaquo; {t['crumb']}</nav>
<div class="langswitch"><a href="{t['switch_href']}">{t['switch_label']}</a></div>
<p class="updated">{t['updated_label']}: {updated}</p>
<article>
{t['body']}
<h2>{t['cookie_h']}</h2>
<p>{t['cookie_p']}</p>
<p><a class="cookiebtn" href="{home}?cookies=1">{t['cookie_btn']}</a></p>
</article>
<footer><p>{t['footer']}</p></footer>
</body></html>"""
