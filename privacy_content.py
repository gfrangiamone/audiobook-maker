"""privacy_content.py — Informativa privacy (pagina /privacy).

Pagina statica multilingua (IT/EN) richiesta dal Play Store e dal GDPR.
Nessun dato dinamico: testo approvato dal titolare. Pattern self-contained
come le altre pagine HTML servite dall'app.
"""

_LAST_UPDATED = {"it": "17 luglio 2026", "en": "July 17, 2026"}

_TXT = {
    "it": {
        "lang": "it",
        "title": "Informativa sulla privacy — Audiobook Maker & Player",
        "updated_label": "Ultimo aggiornamento",
        "switch_label": "English",
        "switch_href": "/privacy?lang=en",
        "crumb": "Privacy",
        "footer": "Audiobook Maker — convertitore gratuito e open source da EPUB/PDF ad audiolibri.",
        "cookie_h": "9. Cookie e consenso",
        "cookie_p": "Il sito web usa cookie analitici (Google Analytics) solo previo tuo consenso, per misurare il traffico in forma aggregata; nessun cookie analitico viene impostato senza il tuo consenso. Puoi rivedere o modificare la tua scelta in qualsiasi momento.",
        "cookie_p2": "L'app mobile non usa cookie né analytics di terze parti.",
        "cookie_btn": "Gestisci preferenze cookie",
        "changes_h": "10. Modifiche",
        "changes_p": "Eventuali modifiche a questa informativa saranno pubblicate in questa pagina con l'indicazione della data di aggiornamento.",
        "body": """
<h1>Informativa sulla privacy — Audiobook Maker &amp; Player</h1>

<h2>1. Titolare del trattamento</h2>
<p>Il titolare del trattamento è <strong>Luigi Frangiamone</strong> (Italia). Per
qualsiasi richiesta relativa ai tuoi dati personali puoi scrivere a
<a href="mailto:support@audiobook-maker.com">support@audiobook-maker.com</a>.</p>

<h2>2. In breve: app e sito web sono trattati diversamente</h2>
<p>Audiobook Maker &amp; Player esiste come app mobile e come sito web. I due
canali trattano dati in modo diverso: se usi solo l'app, molti dei trattamenti
descritti in questa informativa non ti riguardano affatto.</p>
<div class="tablewrap"><table>
<thead><tr><th></th><th>Se usi solo l'app</th><th>Se usi anche il sito web</th></tr></thead>
<tbody>
<tr><td><strong>Registrazione o account</strong></td><td>Mai</td><td>Mai</td></tr>
<tr><td><strong>Indirizzo email</strong></td><td>Mai richiesto</td><td>Facoltativo (notifiche)</td></tr>
<tr><td><strong>Voci di sintesi vocale</strong></td><td>Solo Microsoft (Edge TTS)</td><td>Anche Google Gemini e Speechify (premium)</td></tr>
<tr><td><strong>Ottimizzazione del testo con IA</strong></td><td>No</td><td>Sì, con DeepSeek (premium)</td></tr>
<tr><td><strong>Pagamenti</strong></td><td>Nessuno</td><td>PayPal (solo servizi premium)</td></tr>
<tr><td><strong>Cookie analitici</strong></td><td>Nessuno</td><td>Google Analytics, previo consenso</td></tr>
<tr><td><strong>Notifiche push</strong></td><td>Sì (Firebase), se le attivi</td><td>—</td></tr>
</tbody>
</table></div>

<h2>3. Se usi solo l'app mobile</h2>

<h3>3.1 Cosa resta sul tuo dispositivo</h3>
<p>L'app è prima di tutto un lettore offline. Gli audiolibri che ascolti, la tua
libreria, la posizione di ascolto, i segnalibri e le impostazioni restano sul tuo
dispositivo e non ci vengono mai trasmessi. Se usi l'app solo per ascoltare file
che hai già, nessun dato lascia il tuo dispositivo.</p>

<h3>3.2 Cosa viene inviato ai nostri server</h3>
<p>L'app non richiede registrazione né login. Per le funzioni che dialogano con il
server invia:</p>
<ul>
<li><strong>Identificativo pseudonimo del dispositivo</strong>: un codice casuale
generato al primo avvio e conservato sul dispositivo. Accompagna ogni richiesta e
serve ad associarti i tuoi lavori di conversione — è l'unico modo per riconoscere i
tuoi lavori senza chiederti un account. Base giuridica: legittimo interesse
(gestione del servizio, sicurezza, prevenzione abusi).</li>
<li><strong>Piattaforma e versione dell'app</strong>, e un segnale di avvio a fini
statistici. Base giuridica: legittimo interesse.</li>
<li><strong>Indirizzo IP</strong>, tecnicamente necessario a ogni connessione. Base
giuridica: legittimo interesse.</li>
<li><strong>Token di notifica push (Firebase Cloud Messaging)</strong>, solo se
attivi le notifiche, per avvisarti quando un audiolibro è pronto. Base giuridica:
esecuzione del servizio.</li>
<li><strong>File che carichi tu</strong>, solo se usi le funzioni che li richiedono
(vedi 3.3).</li>
</ul>
<p>L'app non usa strumenti di analytics di terze parti, non contiene pubblicità e
non usa l'identificativo pubblicitario. Tutte le comunicazioni avvengono su
connessione cifrata (HTTPS).</p>

<h3>3.3 I file che carichi dall'app</h3>
<ul>
<li><strong>Documenti (EPUB, PDF, TXT)</strong> — funzione «Crea audiolibro»:
caricati ed elaborati per generare l'audiolibro. Base giuridica: esecuzione del
servizio richiesto.</li>
<li><strong>File audio (M4B, MP3)</strong> — funzione «Condividi audiolibro»:
caricati per generare il link di condivisione, che decidi tu con chi usare. Non
vengono trasmessi a nessun altro. Base giuridica: esecuzione del servizio
richiesto.</li>
</ul>
<p><strong>Importante:</strong> i documenti caricati dall'app vengono elaborati
esclusivamente con le voci standard di Microsoft (Edge TTS). Le voci premium
(Google Gemini, Speechify) e l'ottimizzazione del testo tramite IA (DeepSeek) sono
disponibili solo sul sito web e non vengono mai attivate dall'app.</p>

<h2>4. Se usi anche il sito web</h2>
<p>Oltre a quanto sopra, il sito tratta:</p>
<ul>
<li><strong>Indirizzo email (facoltativo)</strong>: per inviarti la notifica di
completamento e il link di download. Base giuridica: esecuzione del servizio.</li>
<li><strong>Voci premium</strong>: se le scegli, il testo viene elaborato da Google
(Gemini) o Speechify. Base giuridica: esecuzione del servizio richiesto.</li>
<li><strong>Ottimizzazione del testo tramite IA</strong>: se la scegli, il testo
viene elaborato da DeepSeek. Base giuridica: esecuzione del servizio richiesto.</li>
<li><strong>Dati di pagamento (servizi premium)</strong>: gestiti direttamente da
PayPal; non trattiamo né conserviamo i dati della tua carta.</li>
<li><strong>Cookie analitici</strong>: vedi §9.</li>
</ul>

<h2>5. Fornitori e destinatari dei dati</h2>
<p>Per erogare il servizio i dati possono essere trasmessi ai seguenti soggetti. La
colonna indica da quale canale possono riceverli:</p>
<div class="tablewrap"><table>
<thead><tr><th>Soggetto</th><th>Finalità</th><th>Canale</th></tr></thead>
<tbody>
<tr><td>Microsoft Corporation</td><td>Sintesi vocale, voci standard (Edge TTS)</td><td>App e sito web</td></tr>
<tr><td>Cloudflare, Inc.</td><td>Archiviazione temporanea dei file</td><td>App e sito web</td></tr>
<tr><td>Google LLC / Google Ireland</td><td>Notifiche push (Firebase Cloud Messaging)</td><td>App</td></tr>
<tr><td>Google LLC / Google Ireland</td><td>Voci premium ed elaborazione del testo</td><td>Solo sito web</td></tr>
<tr><td>Speechify</td><td>Voci premium</td><td>Solo sito web</td></tr>
<tr><td>DeepSeek</td><td>Ottimizzazione del testo tramite IA</td><td>Solo sito web</td></tr>
<tr><td>PayPal (Europe)</td><td>Pagamenti dei servizi premium</td><td>Solo sito web</td></tr>
<tr><td>serverSMTP</td><td>Invio delle email di notifica</td><td>Solo sito web</td></tr>
</tbody>
</table></div>

<h2>6. Trasferimenti extra-UE</h2>
<p>Alcuni fornitori possono trattare i dati al di fuori dell'Unione Europea. In tali
casi il trasferimento avviene sulla base delle garanzie previste dal GDPR (es.
Clausole Contrattuali Standard).</p>

<h2>7. Conservazione</h2>
<ul>
<li><strong>File caricati e audiolibri generati</strong>: conservati
temporaneamente (di norma fino a circa 24 ore di disponibilità online, più
un'eventuale copia di backup a breve termine), poi eliminati.</li>
<li><strong>Log tecnici delle attività</strong> (data e ora, identificativo
pseudonimo, esito dell'elaborazione), per finalità di sicurezza, diagnostica e
prevenzione degli abusi: 12 mesi (365 giorni). Non contengono il contenuto dei file
caricati.</li>
<li><strong>Token di notifica push</strong>: finché l'app resta installata e
registrata.</li>
<li><strong>Indirizzo email (solo sito web)</strong>: per il tempo necessario alla
consegna della notifica.</li>
</ul>

<h2>8. I tuoi diritti</h2>
<p>Hai diritto di accesso, rettifica, cancellazione, limitazione, opposizione e
portabilità dei dati, oltre al diritto di reclamo all'Autorità Garante per la
protezione dei dati personali.</p>
<p>Poiché l'app non prevede account, non possiamo collegare autonomamente i dati a
una persona: per esercitare i tuoi diritti scrivi a
<a href="mailto:support@audiobook-maker.com">support@audiobook-maker.com</a>. I file che carichi si
cancellano comunque da soli entro circa 24 ore senza alcuna richiesta.</p>
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
        "cookie_h": "9. Cookies and consent",
        "cookie_p": "The website uses analytics cookies (Google Analytics) only with your consent, to measure aggregate traffic; no analytics cookie is set without your consent. You can review or change your choice at any time.",
        "cookie_p2": "The mobile app uses no cookies and no third-party analytics.",
        "cookie_btn": "Manage cookie preferences",
        "changes_h": "10. Changes",
        "changes_p": "Any changes to this policy will be published on this page together with the update date.",
        "body": """
<h1>Privacy Policy — Audiobook Maker &amp; Player</h1>

<h2>1. Data controller</h2>
<p>The data controller is <strong>Luigi Frangiamone</strong> (Italy). For any
request regarding your personal data, please write to
<a href="mailto:support@audiobook-maker.com">support@audiobook-maker.com</a>.</p>

<h2>2. In short: the app and the website are handled differently</h2>
<p>Audiobook Maker &amp; Player exists as a mobile app and as a website. The two
channels process data differently: if you use only the app, many of the
processing activities described in this policy do not concern you at all.</p>
<div class="tablewrap"><table>
<thead><tr><th></th><th>If you use only the app</th><th>If you also use the website</th></tr></thead>
<tbody>
<tr><td><strong>Registration or account</strong></td><td>Never</td><td>Never</td></tr>
<tr><td><strong>Email address</strong></td><td>Never required</td><td>Optional (notifications)</td></tr>
<tr><td><strong>Speech synthesis voices</strong></td><td>Microsoft only (Edge TTS)</td><td>Also Google Gemini and Speechify (premium)</td></tr>
<tr><td><strong>AI text optimization</strong></td><td>No</td><td>Yes, with DeepSeek (premium)</td></tr>
<tr><td><strong>Payments</strong></td><td>None</td><td>PayPal (premium services only)</td></tr>
<tr><td><strong>Analytics cookies</strong></td><td>None</td><td>Google Analytics, with consent</td></tr>
<tr><td><strong>Push notifications</strong></td><td>Yes (Firebase), if you enable them</td><td>—</td></tr>
</tbody>
</table></div>

<h2>3. If you use only the mobile app</h2>

<h3>3.1 What stays on your device</h3>
<p>The app is first of all an offline player. The audiobooks you listen to, your
library, your listening position, bookmarks and settings stay on your device and
are never transmitted to us. If you use the app only to listen to files you
already have, no data leaves your device.</p>

<h3>3.2 What is sent to our servers</h3>
<p>The app requires no registration or login. For the features that talk to the
server, it sends:</p>
<ul>
<li><strong>Pseudonymous device identifier</strong>: a random code generated at
first launch and stored on the device. It accompanies every request and is used to
associate your conversion jobs with you — it is the only way to recognise your jobs
without asking you for an account. Legal basis: legitimate interest (service
management, security, abuse prevention).</li>
<li><strong>Platform and app version</strong>, and an app-open signal for
statistical purposes. Legal basis: legitimate interest.</li>
<li><strong>IP address</strong>, technically necessary for every connection. Legal
basis: legitimate interest.</li>
<li><strong>Push notification token (Firebase Cloud Messaging)</strong>, only if you
enable notifications, to alert you when an audiobook is ready. Legal basis:
performance of the service.</li>
<li><strong>Files you upload</strong>, only if you use the features that require
them (see 3.3).</li>
</ul>
<p>The app uses no third-party analytics tools, contains no advertising and does not
use the advertising identifier. All communications take place over an encrypted
connection (HTTPS).</p>

<h3>3.3 The files you upload from the app</h3>
<ul>
<li><strong>Documents (EPUB, PDF, TXT)</strong> — «Create audiobook» feature:
uploaded and processed to generate the audiobook. Legal basis: performance of the
requested service.</li>
<li><strong>Audio files (M4B, MP3)</strong> — «Share audiobook» feature: uploaded to
generate the sharing link, which you decide whom to use it with. They are not
transmitted to anyone else. Legal basis: performance of the requested service.</li>
</ul>
<p><strong>Important:</strong> documents uploaded from the app are processed
exclusively with Microsoft's standard voices (Edge TTS). Premium voices (Google
Gemini, Speechify) and AI text optimization (DeepSeek) are available only on the
website and are never activated by the app.</p>

<h2>4. If you also use the website</h2>
<p>In addition to the above, the website processes:</p>
<ul>
<li><strong>Email address (optional)</strong>: to send you the completion
notification and the download link. Legal basis: performance of the service.</li>
<li><strong>Premium voices</strong>: if you choose them, the text is processed by
Google (Gemini) or Speechify. Legal basis: performance of the requested service.</li>
<li><strong>AI text optimization</strong>: if you choose it, the text is processed
by DeepSeek. Legal basis: performance of the requested service.</li>
<li><strong>Payment data (premium services)</strong>: handled directly by PayPal; we
do not process or store your card details.</li>
<li><strong>Analytics cookies</strong>: see §9.</li>
</ul>

<h2>5. Providers and recipients of the data</h2>
<p>To deliver the service, data may be transmitted to the following parties. The
column indicates from which channel they may receive it:</p>
<div class="tablewrap"><table>
<thead><tr><th>Recipient</th><th>Purpose</th><th>Channel</th></tr></thead>
<tbody>
<tr><td>Microsoft Corporation</td><td>Speech synthesis, standard voices (Edge TTS)</td><td>App &amp; website</td></tr>
<tr><td>Cloudflare, Inc.</td><td>Temporary file storage</td><td>App &amp; website</td></tr>
<tr><td>Google LLC / Google Ireland</td><td>Push notifications (Firebase Cloud Messaging)</td><td>App</td></tr>
<tr><td>Google LLC / Google Ireland</td><td>Premium voices and text processing</td><td>Website only</td></tr>
<tr><td>Speechify</td><td>Premium voices</td><td>Website only</td></tr>
<tr><td>DeepSeek</td><td>AI text optimization</td><td>Website only</td></tr>
<tr><td>PayPal (Europe)</td><td>Premium services payment</td><td>Website only</td></tr>
<tr><td>serverSMTP</td><td>Sending notification emails</td><td>Website only</td></tr>
</tbody>
</table></div>

<h2>6. Transfers outside the EU</h2>
<p>Some providers may process data outside the European Union. In such cases the
transfer is based on the safeguards required by the GDPR (e.g. Standard Contractual
Clauses).</p>

<h2>7. Retention</h2>
<ul>
<li><strong>Uploaded files and generated audiobooks</strong>: stored temporarily
(typically up to about 24 hours of online availability, plus a possible short-term
backup copy), then deleted.</li>
<li><strong>Technical activity logs</strong> (date and time, pseudonymous
identifier, processing outcome), for security, diagnostics and abuse prevention: 12
months (365 days). They do not contain the content of the uploaded files.</li>
<li><strong>Push notification token</strong>: as long as the app stays installed and
registered.</li>
<li><strong>Email address (website only)</strong>: for the time needed to deliver
the notification.</li>
</ul>

<h2>8. Your rights</h2>
<p>You have the right to access, rectify, erase, restrict, object to and port your
data, as well as the right to lodge a complaint with the data protection supervisory
authority.</p>
<p>Since the app has no accounts, we cannot link the data to a person on our own: to
exercise your rights, write to
<a href="mailto:support@audiobook-maker.com">support@audiobook-maker.com</a>. The files you upload
delete themselves anyway within about 24 hours without any request.</p>
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
h3{{font-family:'DM Sans',system-ui,sans-serif;font-size:1.1rem;font-weight:600;margin:20px 0 8px;color:var(--tx)}}
p,li{{margin-bottom:10px;color:var(--txd)}}
ul{{padding-left:22px;margin-bottom:10px}}
strong{{color:var(--tx)}}
a{{color:var(--ac);text-decoration:none}}
a:hover{{color:var(--ach);text-decoration:underline}}
.tablewrap{{overflow-x:auto;margin:12px 0}}
table{{width:100%;border-collapse:collapse;font-size:.9rem}}
th,td{{border:1px solid var(--brd);padding:8px 10px;text-align:left;vertical-align:top;color:var(--txd)}}
th{{background:#efe9e0;color:var(--tx);font-weight:600}}
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
<p>{t['cookie_p2']}</p>
<p><a class="cookiebtn" href="{home}?cookies=1">{t['cookie_btn']}</a></p>
<h2>{t['changes_h']}</h2>
<p>{t['changes_p']}</p>
</article>
<footer><p>{t['footer']}</p></footer>
</body></html>"""
