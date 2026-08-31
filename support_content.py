"""support_content.py — Pagina di assistenza (/support).

Pagina statica multilingua (IT/EN) con FAQ sull'app Audiobook Maker & Player.
Nessun dato dinamico: testo approvato dal titolare. Pattern self-contained
coerente con privacy_content.py (stesso tema, breadcrumb + footer + langswitch).
"""

_TXT = {
    "it": {
        "lang": "it",
        "title": "Assistenza — Audiobook Maker & Player",
        "switch_label": "English",
        "switch_href": "/support?lang=en",
        "crumb": "Assistenza",
        "footer": "Audiobook Maker — convertitore gratuito e open source da EPUB/PDF ad audiolibri.",
        "intro": "Hai bisogno di aiuto con Audiobook Maker &amp; Player? Qui trovi le risposte alle domande più frequenti. Se non risolvi, scrivici: rispondiamo il prima possibile.",
        "faq_h": "Domande frequenti",
        "faq": [
            ("Quali formati audio posso ascoltare?",
             "File MP3, M4B e M4A già presenti sul tuo dispositivo, con capitoli e copertina quando disponibili."),
            ("Come aggiungo un audiolibro all'app?",
             "Da un'altra app usa «Apri con» o «Condividi» e scegli Audiobook Maker &amp; Player: il file viene importato nella tua libreria. Puoi anche inquadrare il QR di trasferimento mostrato sul sito."),
            ("Gli audiolibri funzionano offline?",
             "Sì. Una volta nella libreria, i file restano sul dispositivo e si ascoltano senza connessione. La rete serve solo per creare e scaricare nuovi titoli."),
            ("Come creo un audiolibro da un testo?",
             "Avvia la creazione dall'app: il lavoro viene elaborato sul nostro server con voci sintetiche e prosegue anche a schermo bloccato. Segui l'avanzamento nella sezione Attività e scarica il risultato quando è pronto."),
            ("Dove sono sleep timer, velocità e segnalibri?",
             "Nella schermata del player: imposta lo sleep timer a tempo o «fine capitolo», regola la velocità da 0,7&times; a 2,0&times;, aggiungi segnalibri e naviga tra i capitoli. I controlli sono disponibili anche dalla schermata di blocco, dal Centro di Controllo e dalle cuffie."),
            ("L'app ricorda il punto in cui ero arrivato?",
             "Sì, la posizione di ascolto viene salvata automaticamente: riprendi sempre da dove avevi lasciato."),
            ("Come gestisco le notifiche?",
             "Le notifiche (es. audiolibro pronto) sono facoltative e puoi disattivarle dalle impostazioni di sistema di iOS in qualsiasi momento."),
            ("Come vengono trattati i miei dati?",
             "Gli audiolibri restano sul tuo dispositivo e non vengono caricati a meno che tu non li condivida esplicitamente. In questo caso rimangono per 24 ore in un'area raggiungibile soltanto con il link che ti viene comunicato. Trovi tutti i dettagli nella nostra <a href=\"/privacy?lang=it\">Informativa sulla privacy</a>."),
        ],
        "contact_h": "Contatto",
        "contact": "Non hai trovato quello che cercavi? Scrivi a <a href=\"mailto:support@audiobook-maker.com\">support@audiobook-maker.com</a> e ti aiuteremo.",
    },
    "en": {
        "lang": "en",
        "title": "Support — Audiobook Maker & Player",
        "switch_label": "Italiano",
        "switch_href": "/support?lang=it",
        "crumb": "Support",
        "footer": "Audiobook Maker — free &amp; open-source EPUB/PDF to audiobook converter.",
        "intro": "Need help with Audiobook Maker &amp; Player? Below are answers to the most common questions. If you can't find what you need, get in touch — we'll reply as soon as possible.",
        "faq_h": "FAQ",
        "faq": [
            ("Which audio formats can I play?",
             "MP3, M4B and M4A files already on your device, with chapters and cover art when available."),
            ("How do I add an audiobook to the app?",
             "From another app, use «Open with» or «Share» and pick Audiobook Maker &amp; Player — the file is imported into your library. You can also scan the transfer QR code shown on the website."),
            ("Do audiobooks work offline?",
             "Yes. Once in your library, files stay on your device and play without a connection. The network is only needed to create and download new titles."),
            ("How do I create an audiobook from text?",
             "Start the creation in the app: the job is processed on our server using synthetic voices and keeps running even with the screen locked. Track progress in the Activity section and download the result when it's ready."),
            ("Where are the sleep timer, speed and bookmarks?",
             "On the player screen: set the sleep timer by time or «end of chapter», adjust speed from 0.7&times; to 2.0&times;, add bookmarks and move between chapters. Controls are also available from the lock screen, Control Center and headphones."),
            ("Does the app remember where I stopped?",
             "Yes — your listening position is saved automatically, so you always pick up where you left off."),
            ("How do I manage notifications?",
             "Notifications (e.g. «audiobook ready») are optional and can be turned off anytime from iOS system settings."),
            ("How is my data handled?",
             "Your audiobooks stay on your device and are not uploaded unless you explicitly share them. In that case they remain for 24 hours in an area reachable only via the link you are given. Full details are in our <a href=\"/privacy?lang=en\">Privacy Policy</a>."),
        ],
        "contact_h": "Contact",
        "contact": "Didn't find what you were looking for? Email us at <a href=\"mailto:support@audiobook-maker.com\">support@audiobook-maker.com</a> and we'll help.",
    },
}


def render_support_page(lang="it", base_url=""):
    """Ritorna l'HTML completo della pagina /support nella lingua richiesta.

    Stile coerente con /privacy (font DM Sans/DM Serif Display, variabili
    tema, breadcrumb + footer). Lingue: it (default), en.
    """
    t = _TXT.get(lang, _TXT["it"])
    home = base_url or "/"
    faq_html = "\n".join(
        f'<h2>{q}</h2>\n<p>{a}</p>' for q, a in t["faq"]
    )
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
.intro,.contact{{background:var(--srf);border:1px solid var(--brd);border-left:4px solid var(--ac);border-radius:var(--r);padding:14px 18px;margin:18px 0}}
.intro p,.contact p{{margin-bottom:0}}
footer{{margin-top:48px;padding-top:24px;border-top:1px solid var(--brd);font-size:.85rem;color:var(--txm)}}
</style></head><body>
<nav class="breadcrumb"><a href="{home}">Audiobook Maker</a> &rsaquo; {t['crumb']}</nav>
<div class="langswitch"><a href="{t['switch_href']}">{t['switch_label']}</a></div>
<article>
<h1>{t['title']}</h1>
<div class="intro"><p>{t['intro']}</p></div>
{faq_html}
<h2>{t['contact_h']}</h2>
<div class="contact"><p>{t['contact']}</p></div>
</article>
<footer><p>{t['footer']}</p></footer>
</body></html>"""
