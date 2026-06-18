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
<p>L'app mobile <strong>non</strong> utilizza strumenti di analisi statistica
(analytics) né pubblicità.</p>

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
<p>The mobile app does <strong>not</strong> use analytics tools or advertising.</p>

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


def render_privacy_page(lang="it"):
    """Ritorna l'HTML completo della pagina /privacy nella lingua richiesta.

    Lingue supportate: it (default), en. Qualsiasi altro valore -> it.
    """
    t = _TXT.get(lang, _TXT["it"])
    updated = _LAST_UPDATED.get(t["lang"], _LAST_UPDATED["it"])
    return f"""<!DOCTYPE html><html lang="{t['lang']}"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="index,follow">
<title>{t['title']}</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;max-width:760px;margin:0 auto;
padding:40px 20px 80px;color:#222;line-height:1.6;background:#fff}}
h1{{font-size:1.7rem;margin:0 0 4px}}
h2{{font-size:1.15rem;margin:28px 0 8px;color:#1a1a1a}}
a{{color:#2563eb}}
.updated{{color:#777;font-size:.9rem;margin-bottom:24px}}
.switch{{font-size:.9rem;margin-bottom:24px}}
ul{{padding-left:20px}}
li{{margin:6px 0}}
</style></head><body>
<div class="switch"><a href="{t['switch_href']}">{t['switch_label']}</a></div>
<p class="updated">{t['updated_label']}: {updated}</p>
{t['body']}
</body></html>"""
