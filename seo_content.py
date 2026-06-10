"""
seo_content.py — Testi SEO visibili iniettati server-side nel body HTML.

Questo modulo genera un blocco <section> con:
  - Direct answer quotabile (primi 150 caratteri)
  - H2 heading con keyword primaria
  - Paragrafo descrittivo denso di keyword
  - Tabella comparativa voci/lingue (dati citabili per GEO)
  - Audience targeting ("Ideale per...")
  - Lista "Come funziona" (features)
  - FAQ con <details>/<summary> (accessibili e SEO-friendly)
  - Privacy & disclosure
  - Timestamp ultimo aggiornamento
  - FAQPage + HowTo JSON-LD schema

Tutto questo HTML è presente nel sorgente statico della pagina, visibile
ai crawler dei motori di ricerca SENZA esecuzione di JavaScript.

Il blocco si adatta al tema della pagina usando le CSS custom properties
(--tx, --txd, --srf, ecc.) già definite nel tema light/dark.
"""

from datetime import datetime
from html import escape
import json
import re

from version import get_formatted_date

# Convert bare URLs in escaped text to clickable links
_URL_RE = re.compile(r'(https?://[^\s)<>&]+/?)(?=[)\s.,;]|$)')


def _linkify(text: str) -> str:
    """Turn plain URLs in already-escaped HTML text into <a> links."""
    return _URL_RE.sub(r"<a href='\1' target='_blank' rel='noopener'>\1</a>", text)


# ═══════════════════════════════════════════════════════════════════
# CONTENUTI SEO VISIBILI PER LINGUA
# ═══════════════════════════════════════════════════════════════════

_CONTENT = {
    # ─── ITALIANO ───────────────────────────────────────────────────
    "it": {
        "direct_answer": (
            "Audiobook Maker è un convertitore gratuito da EPUB e PDF a audiolibro MP3 e M4B "
            "con oltre 400 voci AI neurali in decine di lingue (tecnologia Microsoft Edge TTS). "
            "Non richiede registrazione, non ha limiti di utilizzo e funziona interamente nel browser."
        ),
        "key_takeaways": {
            "title": "Punti Chiave",
            "items": [
                "✅ <strong>Gratis al 100%</strong> — Nessuna registrazione, nessun limite",
                "✅ <strong>Formato M4B</strong> — Supporto per audiolibri universali con capitoli incorporati",
                "✅ <strong>400+ voci neurali AI</strong> — Microsoft Edge TTS di alta qualità",
                "✅ <strong>50+ lingue</strong> — Italiano, Inglese, Francese, Spagnolo, Tedesco, Cinese e altre",
                "✅ <strong>Nessuna installazione</strong> — Funziona direttamente nel browser",
                "✅ <strong>Podcast RSS</strong> — Genera feed per ascoltare capitoli nella tua app preferita",
                "✅ <strong>Open source</strong> — Progetto trasparente con licenza AGPL-3.0",
            ],
        },
        "heading": "Converti i tuoi Ebook EPUB e PDF in Audiolibri MP3 e M4B — Gratis Online",
        "text": (
            "Audiobook Maker è un convertitore online gratuito che trasforma i tuoi ebook EPUB e PDF "
            "in audiolibri MP3 e M4B utilizzando voci AI naturali con tecnologia neural text-to-speech "
            "(Microsoft Edge TTS). "
            "Carica il tuo libro in formato EPUB o PDF, scegli tra oltre 50 voci di sintesi vocale disponibili "
            "in italiano, inglese, francese, spagnolo, tedesco e cinese, e scarica il tuo audiolibro "
            "pronto per l'ascolto. Non è necessaria alcuna installazione né registrazione: il convertitore funziona "
            "direttamente dal browser. A differenza di servizi come Speechify o Play.ht, "
            "Audiobook Maker è completamente gratuito, senza limiti e senza pubblicità."
        ),
        "audience_heading": "A chi è rivolto",
        "audience": (
            "Ideale per pendolari che vogliono ascoltare libri durante il tragitto, "
            "studenti che preferiscono l'apprendimento uditivo, "
            "persone ipovedenti e lettori con difficoltà di lettura come la dislessia. "
            "Perfetto anche per chi vuole semplicemente rilassarsi ascoltando i propri libri preferiti."
        ),
        "table_heading": "Lingue e Voci Disponibili",
        "features_heading": "Come Funziona il Convertitore EPUB/PDF in Audiolibro",
        "features": [
            "Carica il tuo file EPUB, PDF o TXT — il convertitore supporta ebook di qualsiasi dimensione",
            "Scegli la voce AI e la lingua di narrazione tra oltre 50 opzioni disponibili",
            "Seleziona i capitoli da convertire o converti l'intero libro",
            "Opzionalmente, ottimizza il testo tramite AI per una lettura più naturale (espansione di acronimi, numeri, date, pause e rimozione di artefatti tipografici)",
            "Avvia la conversione text-to-speech con un clic e attendi l'elaborazione",
            "Per conversioni lunghe, inserisci la tua email per ricevere una notifica al termine con il link per il download — puoi chiudere il browser e tornare quando l'audiolibro è pronto",
            "Scarica l'audiolibro in formato MP3 o M4B (con capitoli) pronto per l'ascolto su qualsiasi dispositivo",
            "Genera un feed RSS podcast per ascoltare i capitoli nella tua app preferita",
        ],
        "faq_heading": "Domande Frequenti — Convertitore EPUB/PDF Audiolibro",
        "faqs": [
            ("Come convertire un EPUB o un PDF in audiolibro gratis?",
             "Carica il tuo file EPUB o PDF su Audiobook Maker, seleziona una voce AI neurale tra le oltre 400 disponibili "
             "e la lingua desiderata, poi clicca su Converti. Il convertitore text-to-speech gratuito estrae automaticamente "
             "il testo dal libro — preservando la struttura del documento e la suddivisione in capitoli — e genera un "
             "audiolibro in formato MP3 o M4B con capitoli incorporati, pronto per essere scaricato e ascoltato su qualsiasi "
             "dispositivo (smartphone, tablet o lettore MP3). Non è richiesta alcuna registrazione e non ci sono limiti di utilizzo."),
            ("Cosa sono le Voci PREMIUM?",
             "Le Voci PREMIUM sono un'opzione a pagamento che utilizza i modelli Gemini 2.5 Flash e 3.1 Flash TTS di ultima generazione per generare audiolibri di qualità superiore, con voci incredibilmente naturali ed espressive. La tecnologia Gemini TTS cattura sfumature, emozioni e intonazioni con una fedeltà nettamente superiore alle voci standard, offrendo un'esperienza di ascolto professionale paragonabile a una narrazione umana di alto livello. La generazione avviene con chunking ottimizzato per preservare l'integrità narrativa, e ogni voce PREMIUM è identificata con il prefisso 'gemini' nel selettore voci."),
            ("Posso tradurre un libro in un'altra lingua e crearne l'audiolibro?",
             "Sì. Audiobook Maker include una funzione integrata di traduzione libri: carica il file EPUB, PDF, TXT o ABM, scegli la lingua di origine e di destinazione e l'AI traduce i capitoli selezionati, con ottimizzazione AI opzionale per una narrazione naturale applicata nello stesso passaggio. Puoi scaricare il libro tradotto (EPUB, TXT o ABM) e poi generare l'audiolibro tradotto direttamente dal risultato, usando una qualsiasi delle voci neurali. La traduzione è gratuita sotto una piccola soglia; i libri più lunghi prevedono un piccolo costo, in base al numero di caratteri, pagabile con voucher o PayPal."),
             ("Supportate il formato M4B?",
              "Sì, Audiobook Maker può generare audiolibri professionali in formato M4B universale. "
              "A differenza dei semplici file MP3, il formato M4B permette di incorporare "
              "i capitoli direttamente nel file audio, mantenendo la suddivisione, i titoli e i metadati. "
              "È il formato standard per gli audiolibri su Apple Books, iTunes e molte app dedicate. "
              "Puoi anche generare un file MP3 o uno ZIP con i capitoli separati, a seconda delle tue esigenze."),
            ("Quali formati di ebook sono supportati?",
             "Audiobook Maker supporta i formati EPUB, PDF e TXT per la conversione in audiolibro. "
             "L'EPUB è il formato consigliato per risultati ottimali grazie alla sua struttura logica dei capitoli. "
             "I PDF sono perfettamente supportati con estrazione testo avanzata. "
             "Se il tuo libro è in un altro formato come MOBI o AZW, puoi convertirlo facilmente in EPUB "
             "usando strumenti gratuiti come Calibre prima di caricarlo. "
             "In output ottieni MP3, M4B con capitoli, o ZIP con i file separati."),
            ("Quante voci AI sono disponibili e in quali lingue?",
             "Audiobook Maker offre oltre 400 voci neurali AI di alta qualità basate su Microsoft Edge TTS, "
             "con supporto per decine di lingue tra cui italiano, inglese, francese, spagnolo, tedesco, "
             "cinese, portoghese, russo, giapponese, coreano, arabo, hindi e molte altre. "
             "L'interfaccia dell'app è disponibile in 6 lingue, ma il motore di sintesi vocale "
             "supporta tutte le lingue offerte dalla libreria Edge TTS. "
             "Ogni lingua dispone di voci maschili e femminili con diversi stili di narrazione."),
            ("Le voci AI sono naturali?",
             "Sì, il convertitore utilizza voci neurali TTS di alta qualità basate su Microsoft Edge TTS, "
             "con sintesi vocale AI avanzata che produce voci naturali, fluide e piacevoli da ascoltare. "
             "A differenza delle vecchie voci robotiche, le voci neuronali catturano prosodia, intonazione e ritmo, "
             "offrendo un'esperienza di ascolto professionale comparabile a una narrazione umana. "
             "Puoi ascoltare un'anteprima gratuita prima di avviare la conversione completa."),
            ("Devo installare qualcosa?",
             "No, Audiobook Maker è un convertitore online che funziona completamente nel browser web. "
             "Non serve scaricare, installare o configurare alcun software sul tuo computer, smartphone o tablet. "
             "Basta aprire il sito, caricare il libro e avviare la conversione. "
             "Tutto il processo di text-to-speech avviene sui nostri server in modo sicuro e veloce."),
            ("Il servizio è davvero gratuito?",
             "Sì, Audiobook Maker è completamente gratuito e senza limiti di utilizzo. "
             "Non richiede registrazione, non chiede carta di credito e non inserisce pubblicità nei file audio generati. "
             "Il progetto open source è sostenuto da donazioni volontarie della community. "
             "Tutte le funzioni principali, inclusa la conversione text-to-speech e la generazione M4B, "
             "sono disponibili gratuitamente per tutti gli utenti."),
            ("Audiobook Maker è un'alternativa gratuita a Speechify?",
             "Sì. A differenza di Speechify che richiede un abbonamento a pagamento, "
             "Audiobook Maker è 100% gratuito, non richiede registrazione e offre "
             "centinaia di voci AI neurali in decine di lingue senza alcun limite di utilizzo. "
             "Puoi trovare un confronto dettagliato con strumenti simili su "
             "AlternativeTo (https://alternativeto.net/software/audiobook-maker/about/)."),
            ("Quali strumenti posso usare per ascoltare un audiolibro generato da Audiobook Maker?",
             "I file MP3 generati da Audiobook Maker possono essere ascoltati con qualsiasi lettore "
             "audio. Per un'esperienza ottimale su Android consigliamo Smart AudioBook Player, "
             "un'app progettata specificamente per gli audiolibri che ricorda la posizione di ascolto, "
             "supporta la regolazione della velocità e organizza automaticamente i capitoli. "
             "Su iPhone puoi usare l'app Libri di Apple o qualsiasi lettore MP3. "
             "In alternativa, puoi usare il feed podcast RSS generato dall'app per ascoltare "
             "i capitoli direttamente nella tua app podcast preferita."),
            ("Cos'è l'ottimizzazione AI del testo e quali vantaggi offre?",
             "L'ottimizzazione AI è una fase opzionale, eseguita da un modello LLM, "
             "che riscrive il testo estratto dal libro per renderlo più naturale all'ascolto. "
             "Interviene prima della sintesi vocale su diversi aspetti: espande gli acronimi "
             '(es. "W3C" → "W-tre-C" per forzare la corretta pronuncia lettera-per-lettera), '
             "scrive per esteso numeri, date, unità di misura e simboli, inserisce pause naturali "             "dopo titoli e cambi di scena, rimuove artefatti tipografici (note a piè di pagina, "
             "riferimenti bibliografici inline, trattini di sillabazione, doppi spazi), corregge "
             "virgolette e punteggiatura per un ritmo di lettura scorrevole e previene la deriva "
             "linguistica delle voci Multilingual (che talvolta leggono frasi italiane in altre "
             "lingue). Il risultato è un audiolibro decisamente più piacevole e professionale, "
             "paragonabile a una narrazione curata. Puoi scaricare anche la versione ottimizzata "
             "del progetto in formato .abm per riutilizzarla, modificarla o generare nuove "
             "versioni audio con voci diverse senza ripetere l'ottimizzazione."),
            ("Posso generare un podcast dai capitoli del libro?",
             "Sì, Audiobook Maker può generare automaticamente un feed RSS podcast con tutti i capitoli "
             "del tuo audiolibro. Puoi copiare il link del feed e aggiungerlo a qualsiasi app podcast "
             "come Apple Podcasts, Spotify, Overcast o Pocket Casts per ascoltare i capitoli in streaming. "
             "Questa funzione è ideale per chi vuole ascoltare il libro durante la guida o in palestra, "
             "senza occupare spazio con file scaricati."),
],
        "privacy_heading": "Privacy e Sicurezza",
        "privacy": (
            "Audiobook Maker rispetta la tua privacy. I file caricati e gli audio generati "
            "vengono eliminati automaticamente al termine della sessione. Non è necessaria "
            "alcuna registrazione, non vengono raccolti dati personali e non viene utilizzato "
            "alcun sistema di tracciamento oltre alle statistiche anonime di utilizzo. "
            "Il progetto è open source con licenza AGPL-3.0."
        ),
        "accessibility_heading": "Accessibilità e Inclusione",
        "accessibility": (
            "Audiobook Maker è progettato per essere uno strumento inclusivo. "
            "La conversione text-to-speech offre un supporto concreto a persone con "
            "dislessia, ipovedenti e non vedenti, trasformando qualsiasi testo scritto "
            "in audio di alta qualità ascoltabile ovunque. L'interfaccia è compatibile "
            "con screen reader, supporta la navigazione completa da tastiera e utilizza "
            "landmark ARIA per orientarsi facilmente nella pagina. I file audio generati "
            "possono essere ascoltati su qualsiasi dispositivo, offrendo un'esperienza "
            "di lettura accessibile e senza barriere."
        ),
        "guides_heading": "Guide Gratuite",
        "guides_html": (
            '<ul>'
            '<li><a href="/guide/epub-to-audiobook/?lang=it">Come Convertire EPUB in Audiolibro — Guida Completa</a></li>'
            '<li><a href="/guide/m4b-format/?lang=it">Guida al Formato M4B — Crea Audiolibri con Capitoli</a></li>'
            '<li><a href="/guide/text-to-speech-audiobook/?lang=it">Text-to-Speech per Audiolibri Gratis — Migliori Voci TTS</a></li>'
            '<li><a href="/guide/podcast/?lang=it">Come Pubblicare il Tuo Audiolibro come Podcast Privato</a></li>'
            '</ul>'
        ),
        "updated_label": "Ultimo aggiornamento",
        "share_label": "Condividi",
    },
    # ─── ENGLISH ────────────────────────────────────────────────────
    "en": {
        "direct_answer": (
            "Audiobook Maker is a free, no-signup EPUB and PDF to MP3/M4B audiobook converter "
            "with 400+ neural AI voices in dozens of languages (Microsoft Edge TTS). "
            "It runs entirely in your browser with no usage limits."
        ),
        "key_takeaways": {
            "title": "Quick Summary",
            "items": [
                "✅ <strong>100% Free</strong> — No signup, no limits",
                "✅ <strong>M4B Format</strong> — Universal audiobook support with embedded chapters",
                "✅ <strong>400+ neural AI voices</strong> — High-quality Microsoft Edge TTS",
                "✅ <strong>50+ languages</strong> — English, Italian, French, Spanish, German, Chinese and more",
                "✅ <strong>No installation</strong> — Works directly in your browser",
                "✅ <strong>Podcast RSS</strong> — Generate feed to listen in your favorite app",
                "✅ <strong>Open source</strong> — Transparent project with AGPL-3.0 license",
            ],
        },
        "heading": "Convert Your EPUB and PDF Ebooks to MP3 and M4B Audiobooks — Free Online",
        "text": (
            "Audiobook Maker is a free online converter that transforms your EPUB and PDF ebooks into MP3 and M4B audiobooks "
            "using natural AI voices powered by neural text-to-speech technology (Microsoft Edge TTS). "
            "Upload your book in EPUB or PDF format, choose from 50+ AI voices available in English, "
            "Italian, French, Spanish, German, and Chinese, and download your audiobook ready to listen. "
            "No installation or signup required — the converter works directly in your browser. "
            "Unlike paid alternatives like Speechify or Play.ht, Audiobook Maker is completely free "
            "with no usage limits and no ads."
        ),
        "audience_heading": "Who Is It For",
        "audience": (
            "Ideal for commuters who want to listen to books during travel, "
            "students who prefer auditory learning, "
            "visually impaired readers, and people with reading difficulties like dyslexia. "
            "Also perfect for anyone who simply wants to enjoy their favorite books hands-free."
        ),
        "table_heading": "Available Languages and Voices",
        "features_heading": "How the EPUB/PDF to Audiobook Converter Works",
        "features": [
            "Upload your EPUB, PDF, or TXT file — the converter supports ebooks of any size",
            "Choose the AI voice and narration language from 50+ available options",
            "Select specific chapters to convert or convert the entire book",
            "Optionally, optimize the text with AI for more natural narration (expands acronyms, numbers, dates, inserts pauses and removes typographic artifacts)",
            "Start the text-to-speech conversion with one click and wait for processing",
            "For long conversions, enter your email to receive a notification when the audiobook is ready with a download link — you can close the browser and come back later",
            "Download your audiobook in MP3 or M4B format (with chapters) ready to listen on any device",
            "Generate a podcast RSS feed to listen to chapters in your favorite app",
        ],
        "faq_heading": "Frequently Asked Questions — EPUB/PDF to Audiobook Converter",
        "faqs": [
            ("How to convert an EPUB or PDF to audiobook for free?",
             "Upload your EPUB or PDF file to Audiobook Maker, select a neural AI voice from our collection of over 400 options "
             "and your desired language, then click Convert. The free text-to-speech converter automatically extracts the book "
             "text — preserving the document structure and chapter divisions — and generates an audiobook in MP3 or M4B format "
             "with embedded chapters, ready to download and listen on any device (smartphone, tablet, or MP3 player). "
             "No signup or credit card is required, and there are no usage limits."),
            ("What are PREMIUM Voices?",
             "PREMIUM Voices are a paid option that leverages cutting-edge Gemini 2.5 Flash and 3.1 Flash TTS models to generate superior-quality audiobooks with incredibly natural and expressive speech. Gemini TTS technology captures nuances, emotions and intonations with fidelity far exceeding standard voices, delivering a professional listening experience comparable to high-end human narration. Generation uses optimized chunking to preserve narrative integrity, and each PREMIUM voice is identified with the 'gemini' prefix in the voice selector."),
            ("Can I translate a book into another language and make an audiobook from it?",
             "Yes. Audiobook Maker includes an integrated book translation feature: upload your EPUB, PDF, TXT or ABM file, pick the source and target language, and the AI translates the selected chapters — with optional AI optimization for natural narration applied in the same step. You can download the translated book (EPUB, TXT or ABM) and then generate a translated audiobook directly from the result, using any of the neural voices. Translation is free below a small threshold; longer books carry a small fee, based on the number of characters, payable by voucher or PayPal."),
            ("Do you support the M4B format?",
             "Yes, Audiobook Maker can generate professional audiobooks in universal M4B format. "
             "Unlike standard MP3 files, M4B allows embedding chapters directly into the audio file, "
             "preserving structure, titles, and metadata. It is the standard audiobook format for Apple Books, iTunes, and many dedicated apps. "
             "You can also generate an MP3 file or a ZIP archive with separate chapters, depending on your needs."),
            ("What ebook formats are supported?",
             "Audiobook Maker supports EPUB, PDF, and TXT formats for audiobook conversion. "
             "EPUB is recommended for optimal results thanks to its logical chapter structure. "
             "PDFs are fully supported with advanced text extraction. "
             "If your book is in another format such as MOBI or AZW, you can easily convert it to EPUB "
             "using free tools like Calibre before uploading. "
             "Output options include MP3, M4B with chapters, or a ZIP file with separate chapter files."),
            ("How many AI voices are available and in which languages?",
             "Audiobook Maker offers 400+ high-quality neural AI voices powered by Microsoft Edge TTS, "
             "supporting dozens of languages including English, Italian, French, Spanish, German, "
             "Chinese, Portuguese, Russian, Japanese, Korean, Arabic, Hindi, and many more. "
             "The app interface is available in 6 languages, but the text-to-speech engine "
             "supports all languages offered by the Edge TTS library. "
             "Each language includes male and female voices with different narration styles."),
            ("Are the AI voices natural-sounding?",
             "Yes, the converter uses high-quality neural TTS voices powered by Microsoft Edge TTS, "
             "with advanced AI voice synthesis that produces natural, fluid, and pleasant voices. "
             "Unlike old robotic voices, neural voices capture prosody, intonation, and rhythm, "
             "delivering a professional listening experience comparable to human narration. "
             "You can listen to a free preview before starting the full conversion."),
            ("Do I need to install anything?",
             "No, Audiobook Maker is an online converter that works entirely in your web browser. "
             "There is no need to download, install, or configure any software on your computer, smartphone, or tablet. "
             "Simply open the website, upload your book, and start the conversion. "
             "The entire text-to-speech process runs on our servers securely and quickly."),
            ("Is the service really free?",
             "Yes, Audiobook Maker is completely free with no usage limits. "
             "No registration is required, no credit card is asked for, and no advertisements are inserted into generated audio files. "
             "The open-source project is supported by voluntary community donations. "
             "All core features, including text-to-speech conversion and M4B generation, are available free of charge to all users."),
            ("Is Audiobook Maker a free alternative to Speechify?",
             "Yes. Unlike Speechify which requires a paid subscription, "
             "Audiobook Maker is 100% free, requires no signup, and offers "
             "hundreds of neural AI voices in dozens of languages with no usage limits whatsoever. "
             "You can find a detailed comparison with similar tools on "
             "AlternativeTo (https://alternativeto.net/software/audiobook-maker/about/)."),
            ("What tools can I use to listen to an audiobook generated by Audiobook Maker?",
             "The MP3 files generated by Audiobook Maker can be played with any audio player. "
             "For the best experience on Android, we recommend Smart AudioBook Player, "
             "an app specifically designed for audiobooks that remembers your listening position, "
             "supports speed adjustment, and automatically organizes chapters. "
             "On iPhone, you can use Apple's Books app or any MP3 player. "
             "Alternatively, you can use the podcast RSS feed generated by the app to listen "
             "to chapters directly in your favorite podcast app."),
            ("What is AI text optimization and what benefits does it offer?",
             "AI text optimization is an optional step, powered by an LLM, that rewrites "
             "the text extracted from your book to make it sound natural when read aloud. It runs "
             "before speech synthesis and addresses several issues: it expands acronyms "
             '(e.g. "NASA" → "N.A.S.A." to force letter-by-letter pronunciation), spells out '
             "numbers, dates, units of measure and symbols, inserts natural pauses after titles "
             "and scene breaks, strips typographic artifacts (footnotes, inline bibliographic "
             "references, hyphenation dashes, double spaces), and fixes quotes and punctuation "
             "for smooth reading rhythm. It also prevents language drift in Multilingual voices, "
             "which sometimes pronounce sentences in the wrong language. The result is a "
             "noticeably more pleasant and professional audiobook, comparable to a curated "
             "narration. You can also download the optimized project in .abm format to reuse "
             "it, edit it, or generate new audio versions with different voices without re-running "
             "the optimization."),
            ("Can I generate a podcast from the book chapters?",
             "Yes, Audiobook Maker can automatically generate a podcast RSS feed containing all your audiobook chapters. "
             "You can copy the feed link and add it to any podcast app such as Apple Podcasts, Spotify, Overcast, or Pocket Casts "
             "to stream chapters on demand. This feature is ideal for listening while driving, exercising, or commuting, "
             "without needing to download files to your device."),
],
        "privacy_heading": "Privacy & Security",
        "privacy": (
            "Audiobook Maker respects your privacy. Uploaded files and generated audio "
            "are automatically deleted at the end of each session. No registration is required, "
            "no personal data is collected, and no tracking is used beyond anonymous usage statistics. "
            "The project is open source under the AGPL-3.0 license."
        ),
        "accessibility_heading": "Accessibility & Inclusion",
        "accessibility": (
            "Audiobook Maker is designed as an inclusive tool. "
            "The text-to-speech conversion provides concrete support for people with "
            "dyslexia, visual impairments, and blindness, transforming any written text "
            "into high-quality listenable audio. The interface is screen-reader compatible, "
            "supports full keyboard navigation, and uses ARIA landmarks for easy page "
            "orientation. Generated audio files can be played on any device, offering an "
            "accessible, barrier-free reading experience."
        ),
        "guides_heading": "Free Guides",
        "guides_html": (
            '<ul>'
            '<li><a href="/guide/epub-to-audiobook/?lang=en">How to Convert EPUB to Audiobook — Complete Guide</a></li>'
            '<li><a href="/guide/m4b-format/?lang=en">M4B Format Guide — Create Audiobooks with Chapters</a></li>'
            '<li><a href="/guide/text-to-speech-audiobook/?lang=en">Free Text-to-Speech Audiobook Maker — Best TTS Voices</a></li>'
            '<li><a href="/guide/podcast/?lang=en">How to Publish Your Audiobook as a Private Podcast</a></li>'
            '</ul>'
        ),
        "updated_label": "Last updated",
        "share_label": "Share",
    },
    # ─── FRANÇAIS ───────────────────────────────────────────────────
    "fr": {
        "direct_answer": (
            "Audiobook Maker est un convertisseur gratuit d'EPUB et PDF en livres audio MP3 et M4B "
            "avec plus de 400 voix IA neuronales dans des dizaines de langues (Microsoft Edge TTS). "
            "Sans inscription, sans limites, directement dans votre navigateur."
        ),
        "key_takeaways": {
            "title": "Points Clés",
            "items": [
                "✅ <strong>100% Gratuit</strong> — Sans inscription, sans limites",
                 "✅ <strong>Format M4B</strong> — Support des livres audio universels avec chapitres intégrés",
                "✅ <strong>400+ voix IA neuronales</strong> — Microsoft Edge TTS de haute qualité",
                "✅ <strong>50+ langues</strong> — Français, Anglais, Italien, Espagnol, Allemand, Chinois et plus",
                "✅ <strong>Sans installation</strong> — Fonctionne directement dans votre navigateur",
                "✅ <strong>Podcast RSS</strong> — Générez un flux pour écouter dans votre app préférée",
                "✅ <strong>Open source</strong> — Projet transparent sous licence AGPL-3.0",
            ],
        },
        "heading": "Convertissez vos Ebooks EPUB et PDF en Livres Audio MP3 et M4B — Gratuit en Ligne",
        "text": (
            "Audiobook Maker est un convertisseur en ligne gratuit qui transforme vos ebooks EPUB et PDF en livres "
            "audio MP3 et M4B en utilisant des voix IA naturelles (technologie neuronale Microsoft Edge TTS). "
            "Téléchargez votre livre au format EPUB ou PDF, choisissez parmi plus de 50 voix de synthèse vocale "
            "disponibles en français, anglais, italien, espagnol, allemand et chinois, "
            "et téléchargez votre livre audio prêt à écouter. "
            "Aucune installation ni inscription nécessaire. Contrairement à Speechify ou Play.ht, "
            "Audiobook Maker est entièrement gratuit, sans limites et sans publicité."
        ),
        "audience_heading": "À qui s'adresse cet outil",
        "audience": (
            "Idéal pour les pendulaires qui veulent écouter des livres en déplacement, "
            "les étudiants qui préfèrent l'apprentissage auditif, "
            "les malvoyants et les personnes ayant des difficultés de lecture comme la dyslexie. "
            "Parfait aussi pour quiconque souhaite profiter de ses livres préférés en mains libres."
        ),
        "table_heading": "Langues et Voix Disponibles",
        "features_heading": "Comment Fonctionne le Convertisseur EPUB/PDF en Livre Audio",
        "features": [
            "Téléchargez votre fichier EPUB, PDF ou TXT — le convertisseur prend en charge les ebooks de toute taille",
            "Choisissez la voix IA et la langue de narration parmi plus de 50 options",
            "Sélectionnez les chapitres à convertir ou convertissez le livre entier",
            "Optionnellement, optimisez le texte via IA pour une lecture plus naturelle (développement des acronymes, nombres, dates, ajout de pauses et suppression des artefacts typographiques)",
            "Lancez la conversion text-to-speech en un clic et attendez le traitement",
            "Pour les conversions longues, entrez votre email pour recevoir une notification avec un lien de téléchargement quand le livre audio est prêt — vous pouvez fermer le navigateur et revenir plus tard",
            "Téléchargez votre livre audio au format MP3 ou M4B (avec chapitres) prêt à écouter sur tout appareil",
            "Générez un flux RSS podcast pour écouter les chapitres dans votre app préférée",
        ],
        "faq_heading": "Questions Fréquentes — Convertisseur EPUB/PDF Livre Audio",
        "faqs": [
            ("Comment convertir un EPUB ou un PDF en livre audio gratuitement ?",
             "Téléchargez votre fichier EPUB ou PDF sur Audiobook Maker, sélectionnez une voix IA neuronale parmi plus de 400 options "
             "et la langue souhaitée, puis cliquez sur Convertir. Le convertisseur text-to-speech gratuit extrait automatiquement "
             "le texte du livre — en préservant la structure du document et la division en chapitres — et génère un livre audio "
             "en format MP3 ou M4B avec chapitres intégrés, prêt à être téléchargé et écouté sur n'importe quel appareil "
             "(smartphone, tablette ou lecteur MP3). Aucune inscription requise et aucune limite d'utilisation."),
            ("Que sont les Voix PREMIUM ?",
             "Les Voix PREMIUM sont une option payante qui exploite les modèles de pointe Gemini 2.5 Flash et 3.1 Flash TTS pour générer des livres audio de qualité supérieure, avec des voix incroyablement naturelles et expressives. La technologie Gemini TTS capture les nuances, les émotions et les intonations avec une fidélité nettement supérieure aux voix standard, offrant une expérience d'écoute professionnelle comparable à une narration humaine haut de gamme. La génération utilise un découpage optimisé pour préserver l'intégrité narrative, et chaque voix PREMIUM est identifiée par le préfixe 'gemini' dans le sélecteur de voix."),
            ("Puis-je traduire un livre dans une autre langue et en faire un livre audio ?",
             "Oui. Audiobook Maker intègre une fonction de traduction de livres : importez votre fichier EPUB, PDF, TXT ou ABM, choisissez la langue source et la langue cible, et l'IA traduit les chapitres sélectionnés — avec une optimisation IA facultative pour une narration naturelle appliquée lors de la même étape. Vous pouvez télécharger le livre traduit (EPUB, TXT ou ABM), puis générer un livre audio traduit directement à partir du résultat, avec n'importe quelle voix neuronale. La traduction est gratuite en dessous d'un petit seuil ; les livres plus longs entraînent un coût modique, calculé selon le nombre de caractères, payable par bon ou PayPal."),
            ("Prenez-vous en charge le format M4B ?",
             "Oui, Audiobook Maker peut générer des livres audio professionnels au format M4B universel. "
             "Contrairement aux fichiers MP3 classiques, le format M4B permet d'intégrer "
             "les chapitres directement dans le fichier audio, conservant les titres, la structure et les métadonnées. "
             "C'est le format standard pour les livres audio sur Apple Books, iTunes et de nombreuses applications dédiées. "
             "Vous pouvez également générer un fichier MP3 ou une archive ZIP avec les chapitres séparés selon vos besoins."),
            ("Quels formats d'ebook sont supportés ?",
             "Audiobook Maker prend en charge les formats EPUB, PDF et TXT pour la conversion en livre audio. "
             "L'EPUB est recommandé pour des résultats optimaux grâce à sa structure logique des chapitres. "
             "Les PDF sont parfaitement supportés avec une extraction de texte avancée. "
             "Si votre livre est dans un autre format comme MOBI ou AZW, vous pouvez facilement le convertir en EPUB "
             "avec des outils gratuits comme Calibre avant de le télécharger. "
             "En sortie, vous obtenez MP3, M4B avec chapitres, ou ZIP avec les fichiers séparés."),
            ("Combien de voix IA sont disponibles et dans quelles langues ?",
             "Audiobook Maker propose plus de 400 voix IA neuronales de haute qualité basées sur Microsoft Edge TTS, "
             "avec prise en charge de dizaines de langues dont le français, l'anglais, l'italien, l'espagnol, "
             "l'allemand, le chinois, le portugais, le russe, le japonais, le coréen, l'arabe, le hindi et bien d'autres. "
             "L'interface de l'application est disponible en 6 langues, mais le moteur de synthèse vocale "
             "prend en charge toutes les langues offertes par la bibliothèque Edge TTS."),
            ("Les voix IA sont-elles naturelles ?",
             "Oui, le convertisseur utilise des voix neuronales TTS de haute qualité basées sur Microsoft Edge TTS, "
             "avec une synthèse vocale IA avancée qui produit des voix naturelles, fluides et agréables. "
             "Contrairement aux anciennes voix robotiques, les voix neuronales capturent la prosodie, l'intonation et le rythme, "
             "offrant une expérience d'écoute professionnelle comparable à une narration humaine. "
             "Vous pouvez écouter un aperçu gratuit avant de lancer la conversion complète."),
            ("Dois-je installer quelque chose ?",
             "Non, Audiobook Maker fonctionne entièrement dans votre navigateur web, sans aucune installation. "
             "Il n'est pas nécessaire de télécharger, installer ou configurer de logiciel sur votre ordinateur, smartphone ou tablette. "
             "Il suffit d'ouvrir le site, télécharger le livre et lancer la conversion. "
             "Tout le processus text-to-speech s'exécute sur nos serveurs de manière sécurisée et rapide."),
            ("Le service est-il vraiment gratuit ?",
             "Oui, Audiobook Maker est entièrement gratuit et sans limites d'utilisation. "
             "Pas d'inscription requise, pas de carte de crédit demandée et pas de publicité dans les fichiers audio générés. "
             "Le projet open source est soutenu par des dons volontaires de la communauté. "
             "Toutes les fonctions principales, y compris la conversion text-to-speech et la génération M4B, "
             "sont disponibles gratuitement pour tous les utilisateurs."),
            ("Audiobook Maker est-il une alternative gratuite à Speechify ?",
             "Oui. Contrairement à Speechify qui nécessite un abonnement payant, "
             "Audiobook Maker est 100 % gratuit, ne nécessite pas d'inscription et propose "
             "des centaines de voix IA neuronales dans des dizaines de langues sans aucune limite d'utilisation. "
             "Vous pouvez trouver une comparaison détaillée avec des outils similaires sur "
             "AlternativeTo (https://alternativeto.net/software/audiobook-maker/about/)."),
            ("Quels outils utiliser pour écouter un livre audio généré par Audiobook Maker ?",
             "Les fichiers MP3 générés par Audiobook Maker peuvent être lus avec n'importe quel lecteur audio. "
             "Pour une expérience optimale sur Android, nous recommandons Smart AudioBook Player, "
             "une application conçue spécialement pour les livres audio qui mémorise votre position d'écoute, "
             "permet de régler la vitesse et organise automatiquement les chapitres. "
             "Sur iPhone, vous pouvez utiliser l'application Livres d'Apple ou tout lecteur MP3. "
             "Vous pouvez aussi utiliser le flux RSS podcast généré par l'app pour écouter "
             "les chapitres directement dans votre application podcast préférée."),
            ("Qu'est-ce que l'optimisation IA du texte et quels avantages offre-t-elle ?",
             "L'optimisation IA est une étape facultative, exécutée par un modèle LLM, "
             "qui réécrit le texte extrait de votre livre pour le rendre naturel à l'écoute. "
             "Elle intervient avant la synthèse vocale sur plusieurs aspects : elle développe les "
             'acronymes (ex. "ONU" → "O.N.U." pour forcer la prononciation lettre par lettre), '
             "écrit en toutes lettres les nombres, dates, unités de mesure et symboles, insère des "
             "pauses naturelles après les titres et les changements de scène, supprime les "
             "artefacts typographiques (notes de bas de page, références bibliographiques en "
             "ligne, tirets de césure, doubles espaces), corrige guillemets et ponctuation pour "
             "un rythme de lecture fluide, et prévient la dérive linguistique des voix "
             "Multilingual (qui lisent parfois des phrases dans une autre langue). Le résultat "
             "est un livre audio nettement plus agréable et professionnel, comparable à une "
             "narration soignée. Vous pouvez aussi télécharger le projet optimisé au format .abm "
             "pour le réutiliser, le modifier ou générer de nouvelles versions audio avec des "
             "voix différentes sans relancer l'optimisation."),
            ("Puis-je générer un podcast à partir des chapitres du livre ?",
             "Oui, Audiobook Maker peut générer automatiquement un flux RSS podcast contenant tous les chapitres "
             "de votre livre audio. Vous pouvez copier le lien du flux et l'ajouter à n'importe quelle application podcast "
             "comme Apple Podcasts, Spotify, Overcast ou Pocket Casts pour écouter les chapitres en streaming. "
             "Cette fonction est idéale pour écouter votre livre en conduisant ou à la salle de sport, "
             "sans occuper d'espace avec des fichiers téléchargés."),
],
        "privacy_heading": "Confidentialité et Sécurité",
        "privacy": (
            "Audiobook Maker respecte votre vie privée. Les fichiers téléchargés et les audios générés "
            "sont automatiquement supprimés à la fin de chaque session. Aucune inscription requise, "
            "aucune donnée personnelle collectée. Projet open source sous licence AGPL-3.0."
        ),
        "accessibility_heading": "Accessibilité et Inclusion",
        "accessibility": (
            "Audiobook Maker est conçu comme un outil inclusif. "
            "La conversion text-to-speech offre un soutien concret aux personnes "
            "dyslexiques, malvoyantes et non voyantes, en transformant tout texte écrit "
            "en audio de haute qualité écoutable partout. L'interface est compatible "
            "avec les lecteurs d'écran, prend en charge la navigation complète au clavier "
            "et utilise des repères ARIA pour s'orienter facilement dans la page. "
            "Les fichiers audio générés peuvent être lus sur n'importe quel appareil, "
            "offrant une expérience de lecture accessible et sans barrières."
        ),
        "guides_heading": "Guides Gratuits",
        "guides_html": (
            '<ul>'
            '<li><a href="/guide/epub-to-audiobook/?lang=fr">Comment Convertir EPUB en Livre Audio — Guide Complet</a></li>'
            '<li><a href="/guide/m4b-format/?lang=fr">Guide du Format M4B — Créer des Livres Audio avec Chapitres</a></li>'
            '<li><a href="/guide/text-to-speech-audiobook/?lang=fr">Text-to-Speech Livre Audio Gratuit — Meilleures Voix TTS</a></li>'
            '<li><a href="/guide/podcast/?lang=fr">Comment Publier Votre Livre Audio en Podcast Privé</a></li>'
            '</ul>'
        ),
        "updated_label": "Dernière mise à jour",
        "share_label": "Partager",
    },
    # ─── ESPAÑOL ────────────────────────────────────────────────────
    "es": {
        "direct_answer": (
            "Audiobook Maker es un convertidor gratuito de EPUB y PDF a audiolibro MP3 y M4B "
            "con más de 400 voces IA neuronales en decenas de idiomas (Microsoft Edge TTS). "
            "Sin registro, sin límites, directamente en tu navegador."
        ),
        "key_takeaways": {
            "title": "Puntos Clave",
            "items": [
                "✅ <strong>100% Gratis</strong> — Sin registro, sin límites",
                 "✅ <strong>Formato M4B</strong> — Soporte de audiolibros universales con capítulos integrados",
                "✅ <strong>400+ voces IA neuronales</strong> — Microsoft Edge TTS de alta calidad",
                "✅ <strong>50+ idiomas</strong> — Español, Inglés, Italiano, Francés, Alemán, Chino y más",
                "✅ <strong>Sin instalación</strong> — Funciona directamente en tu navegador",
                "✅ <strong>Podcast RSS</strong> — Genera feed para escuchar en tu app favorita",
                "✅ <strong>Open source</strong> — Proyecto transparente con licencia AGPL-3.0",
            ],
        },
        "heading": "Convierte tus Ebooks EPUB y PDF en Audiolibros MP3 y M4B — Gratis Online",
        "text": (
            "Audiobook Maker es un convertidor en línea gratuito que transforma tus ebooks EPUB y PDF en "
            "audiolibros MP3 y M4B utilizando voces IA naturales (tecnología neuronal Microsoft Edge TTS). "
            "Sube tu libro en formato EPUB o PDF, elige entre más de 50 voces de síntesis de voz "
            "disponibles en español, inglés, italiano, francés, alemán y chino, "
            "y descarga tu audiolibro listo para escuchar. "
            "No necesitas instalar nada ni registrarte. A diferencia de Speechify o Play.ht, "
            "Audiobook Maker es completamente gratuito, sin límites y sin publicidad."
        ),
        "audience_heading": "A quién está dirigido",
        "audience": (
            "Ideal para viajeros que quieren escuchar libros durante el trayecto, "
            "estudiantes que prefieren el aprendizaje auditivo, "
            "personas con discapacidad visual y lectores con dificultades como la dislexia. "
            "Perfecto también para cualquiera que quiera disfrutar de sus libros favoritos sin usar las manos."
        ),
        "table_heading": "Idiomas y Voces Disponibles",
        "features_heading": "Cómo Funciona el Convertidor EPUB/PDF a Audiolibro",
        "features": [
            "Sube tu archivo EPUB, PDF o TXT — el convertidor admite ebooks de cualquier tamaño",
            "Elige la voz IA y el idioma de narración entre más de 50 opciones",
            "Selecciona los capítulos a convertir o convierte el libro completo",
            "Opcionalmente, optimiza el texto mediante IA para una lectura más natural (expande acrónimos, números, fechas, inserta pausas y elimina artefactos tipográficos)",
            "Inicia la conversión text-to-speech con un clic y espera el procesamiento",
            "Para conversiones largas, introduce tu email para recibir una notificación con un enlace de descarga cuando el audiolibro esté listo — puedes cerrar el navegador y volver más tarde",
            "Descarga tu audiolibro en formato MP3 o M4B (con capítulos) listo para escuchar en cualquier dispositivo",
            "Genera un feed RSS podcast para escuchar los capítulos en tu app favorita",
        ],
        "faq_heading": "Preguntas Frecuentes — Convertidor EPUB/PDF a Audiolibro",
        "faqs": [
            ("¿Cómo convertir un EPUB o un PDF a audiolibro gratis?",
             "Sube tu archivo EPUB o PDF a Audiobook Maker, selecciona una voz IA neuronal de entre más de 400 opciones "
             "y el idioma deseado, luego haz clic en Convertir. El convertidor text-to-speech gratuito extrae automáticamente "
             "el texto del libro — preservando la estructura del documento y la división en capítulos — y genera un audiolibro "
             "en formato MP3 o M4B con capítulos integrados, listo para descargar y escuchar en cualquier dispositivo "
             "(smartphone, tablet o reproductor MP3). No se requiere registro y no hay límites de uso."),
            ("¿Qué son las Voces PREMIUM?",
             "Las Voces PREMIUM son una opción de pago que utiliza los modelos de vanguardia Gemini 2.5 Flash y 3.1 Flash TTS para generar audiolibros de calidad superior, con voces increíblemente naturales y expresivas. La tecnología Gemini TTS captura matices, emociones y entonaciones con una fidelidad muy superior a las voces estándar, ofreciendo una experiencia de escucha profesional comparable a una narración humana de alto nivel. La generación utiliza fragmentación optimizada para preservar la integridad narrativa, y cada voz PREMIUM se identifica con el prefijo 'gemini' en el selector de voces."),
            ("¿Puedo traducir un libro a otro idioma y crear un audiolibro a partir de él?",
             "Sí. Audiobook Maker incluye una función integrada de traducción de libros: sube tu archivo EPUB, PDF, TXT o ABM, elige el idioma de origen y de destino, y la IA traduce los capítulos seleccionados, con optimización de IA opcional para una narración natural aplicada en el mismo paso. Puedes descargar el libro traducido (EPUB, TXT o ABM) y luego generar un audiolibro traducido directamente a partir del resultado, usando cualquiera de las voces neuronales. La traducción es gratuita por debajo de un pequeño umbral; los libros más largos tienen un coste reducido, según el número de caracteres, pagadero con vale o PayPal."),
            ("¿Es compatible con el formato M4B?",
             "Sí, Audiobook Maker puede generar audiolibros profesionales en formato M4B universal. "
             "A diferencia de los archivos MP3 estándar, el formato M4B permite incrustar "
             "los capítulos directamente en el archivo de audio, manteniendo los títulos, la estructura y los metadatos. "
             "Es el formato estándar para audiolibros en Apple Books, iTunes y muchas aplicaciones dedicadas. "
             "También puedes generar un archivo MP3 o un ZIP con los capítulos separados, según tus necesidades."),
            ("¿Qué formatos de ebook son compatibles?",
             "Audiobook Maker admite los formatos EPUB, PDF y TXT para la conversión a audiolibro. "
             "Se recomienda EPUB para obtener resultados óptimos gracias a su estructura lógica de capítulos. "
             "Los PDF son totalmente compatibles con extracción de texto avanzada. "
             "Si tu libro está en otro formato como MOBI o AZW, puedes convertirlo fácilmente a EPUB "
             "usando herramientas gratuitas como Calibre antes de subirlo. "
             "Las opciones de salida incluyen MP3, M4B con capítulos, o ZIP con los archivos separados."),
            ("¿Cuántas voces IA hay disponibles y en qué idiomas?",
             "Audiobook Maker ofrece más de 400 voces IA neuronales de alta calidad basadas en Microsoft Edge TTS, "
             "con soporte para decenas de idiomas incluyendo español, inglés, italiano, francés, alemán, "
             "chino, portugués, ruso, japonés, coreano, árabe, hindi y muchos más. "
             "La interfaz de la app está disponible en 6 idiomas, pero el motor de síntesis de voz "
             "soporta todos los idiomas ofrecidos por la librería Edge TTS."),
            ("¿Las voces IA suenan naturales?",
             "Sí, el convertidor utiliza voces neuronales TTS de alta calidad basadas en Microsoft Edge TTS, "
             "con síntesis de voz IA avanzada que produce voces naturales, fluidas y agradables. "
             "A diferencia de las antiguas voces robóticas, las voces neuronales capturan prosodia, entonación y ritmo, "
             "ofreciendo una experiencia de escucha profesional comparable a una narración humana. "
             "Puedes escuchar una vista previa gratuita antes de iniciar la conversión completa."),
            ("¿Necesito instalar algo?",
             "No, Audiobook Maker funciona completamente en tu navegador web, sin necesidad de instalación. "
             "No es necesario descargar, instalar ni configurar ningún software en tu ordenador, smartphone o tablet. "
             "Simplemente abre el sitio, sube tu libro y inicia la conversión. "
             "Todo el proceso de text-to-speech se ejecuta en nuestros servidores de forma segura y rápida."),
            ("¿El servicio es realmente gratuito?",
             "Sí, Audiobook Maker es completamente gratuito y sin límites de uso. "
             "No se requiere registro, no se pide tarjeta de crédito y no hay publicidad en los archivos de audio generados. "
             "El proyecto de código abierto se sostiene con donaciones voluntarias de la comunidad. "
             "Todas las funcciones principales, incluida la conversión text-to-speech y la generación M4B, "
             "están disponibles gratuitamente para todos los usuarios."),
            ("¿Es Audiobook Maker una alternativa gratuita a Speechify?",
             "Sí. A diferencia de Speechify, que requiere una suscripción de pago, "
             "Audiobook Maker es 100 % gratuito, no requiere registro y ofrece "
             "cientos de voces IA neuronales en decenas de idiomas sin ningún límite de uso. "
             "Puedes encontrar una comparación detallada con herramientas similares en "
             "AlternativeTo (https://alternativeto.net/software/audiobook-maker/about/)."),
            ("¿Qué herramientas puedo usar para escuchar un audiolibro generado por Audiobook Maker?",
             "Los archivos MP3 generados por Audiobook Maker se pueden reproducir con cualquier reproductor de audio. "
             "Para la mejor experiencia en Android, recomendamos Smart AudioBook Player, "
             "una app diseñada específicamente para audiolibros que recuerda tu posición de escucha, "
             "permite ajustar la velocidad y organiza automáticamente los capítulos. "
             "En iPhone, puedes usar la app Apple Books o cualquier reproductor MP3. "
             "También puedes usar el feed RSS podcast generado por la app para escuchar "
             "los capítulos directamente en tu app de podcast favorita."),
            ("¿Qué es la optimización IA del texto y qué ventajas ofrece?",
             "La optimización IA es una fase opcional, ejecutada por un modelo LLM, "
             "que reescribe el texto extraído del libro para que suene natural al escucharlo. "
             "Interviene antes de la síntesis de voz en varios aspectos: expande acrónimos "
             '(ej. "ONU" → "O.N.U." para forzar la pronunciación letra por letra), escribe '
             "en palabras los números, fechas, unidades de medida y símbolos, inserta pausas "
             "naturales tras títulos y cambios de escena, elimina artefactos tipográficos "
             "(notas al pie, referencias bibliográficas en línea, guiones de silabación, dobles "
             "espacios), corrige comillas y puntuación para un ritmo de lectura fluido, y "
             "previene la deriva lingüística de las voces Multilingual (que a veces leen frases "
             "en otro idioma). El resultado es un audiolibro notablemente más agradable y "
             "profesional, comparable a una narración cuidada. También puedes descargar el "
             "proyecto optimizado en formato .abm para reutilizarlo, modificarlo o generar "
             "nuevas versiones de audio con voces distintas sin repetir la optimización."),
            ("¿Puedo generar un podcast con los capítulos del libro?",
             "Sí, Audiobook Maker puede generar automáticamente un feed RSS podcast con todos los capítulos "
             "de tu audiolibro. Puedes copiar el enlace del feed y añadirlo a cualquier app de podcast "
             "como Apple Podcasts, Spotify, Overcast o Pocket Casts para escuchar los capítulos en streaming. "
             "Esta función es ideal para escuchar el libro mientras conduces o haces ejercicio, "
             "sin ocupar espacio con archivos descargados."),
],
        "privacy_heading": "Privacidad y Seguridad",
        "privacy": (
            "Audiobook Maker respeta tu privacidad. Los archivos subidos y los audios generados "
            "se eliminan automáticamente al final de cada sesión. Sin registro, "
            "sin recopilación de datos personales. Proyecto open source bajo licencia AGPL-3.0."
        ),
        "accessibility_heading": "Accesibilidad e Inclusión",
        "accessibility": (
            "Audiobook Maker está diseñado como una herramienta inclusiva. "
            "La conversión de texto a voz ofrece un apoyo concreto para personas con "
            "dislexia, discapacidad visual y ceguera, transformando cualquier texto escrito "
            "en audio de alta calidad que se puede escuchar en cualquier lugar. La interfaz "
            "es compatible con lectores de pantalla, admite navegación completa por teclado "
            "y utiliza puntos de referencia ARIA para orientarse fácilmente en la página. "
            "Los archivos de audio generados se pueden reproducir en cualquier dispositivo, "
            "ofreciendo una experiencia de lectura accesible y sin barreras."
        ),
        "guides_heading": "Guías Gratuitas",
        "guides_html": (
            '<ul>'
            '<li><a href="/guide/epub-to-audiobook/?lang=es">Cómo Convertir EPUB a Audiolibro — Guía Completa</a></li>'
            '<li><a href="/guide/m4b-format/?lang=es">Guía del Formato M4B — Crear Audiolibros con Capítulos</a></li>'
            '<li><a href="/guide/text-to-speech-audiobook/?lang=es">Text-to-Speech para Audiolibros Gratis — Mejores Voces TTS</a></li>'
            '<li><a href="/guide/podcast/?lang=es">Cómo Publicar Tu Audiolibro como Podcast Privado</a></li>'
            '</ul>'
        ),
        "updated_label": "Última actualización",
        "share_label": "Compartir",
    },
    # ─── DEUTSCH ────────────────────────────────────────────────────
    "de": {
        "direct_answer": (
            "Audiobook Maker ist ein kostenloser EPUB- und PDF-zu-MP3/M4B-Hörbuch-Konverter "
            "mit über 400 neuronalen KI-Stimmen in Dutzenden von Sprachen (Microsoft Edge TTS). "
            "Ohne Registrierung, ohne Limits, direkt im Browser."
        ),
        "key_takeaways": {
            "title": "Kurzübersicht",
            "items": [
                "✅ <strong>100% Kostenlos</strong> — Keine Anmeldung, keine Limits",
                 "✅ <strong>M4B-Format</strong> — Universelle Hörbuch-Unterstützung mit eingebetteten Kapiteln",
                "✅ <strong>400+ neuronale KI-Stimmen</strong> — Microsoft Edge TTS hoher Qualität",
                "✅ <strong>50+ Sprachen</strong> — Deutsch, Englisch, Italienisch, Französisch, Spanisch, Chinesisch und mehr",
                "✅ <strong>Keine Installation</strong> — Funktioniert direkt in Ihrem Browser",
                "✅ <strong>Podcast RSS</strong> — Feed generieren für Ihre Lieblings-App",
                "✅ <strong>Open source</strong> — Transparentes Projekt mit AGPL-3.0 Lizenz",
            ],
        },
        "heading": "Konvertieren Sie Ihre EPUB- und PDF-E-Books in MP3- und M4B-Hörbücher — Kostenlos Online",
        "text": (
            "Audiobook Maker ist ein kostenloser Online-Konverter, der Ihre EPUB- und PDF-E-Books in MP3- und M4B-Hörbücher "
            "umwandelt — mit natürlichen KI-Stimmen (neuronale Microsoft Edge TTS-Technologie). "
            "Laden Sie Ihr Buch im EPUB- oder PDF-Format hoch, wählen Sie aus über 50 Sprachsynthese-Stimmen "
            "auf Deutsch, Englisch, Italienisch, Französisch, Spanisch und Chinesisch, "
            "und laden Sie Ihr fertiges Hörbuch herunter. "
            "Keine Installation und keine Registrierung erforderlich. Im Gegensatz zu Speechify oder Play.ht "
            "ist Audiobook Maker komplett kostenlos, ohne Limits und ohne Werbung."
        ),
        "audience_heading": "Für wen ist es gedacht",
        "audience": (
            "Ideal für Pendler, die unterwegs Bücher hören möchten, "
            "Studenten, die auditives Lernen bevorzugen, "
            "Sehbehinderte und Menschen mit Leseschwierigkeiten wie Legasthenie. "
            "Auch perfekt für alle, die ihre Lieblingsbücher einfach freihändig genießen möchten."
        ),
        "table_heading": "Verfügbare Sprachen und Stimmen",
        "features_heading": "So Funktioniert der EPUB/PDF-zu-Hörbuch-Konverter",
        "features": [
            "Laden Sie Ihre EPUB-, PDF- oder TXT-Datei hoch — der Konverter unterstützt E-Books jeder Größe",
            "Wählen Sie die KI-Stimme und Erzählsprache aus über 50 Optionen",
            "Wählen Sie bestimmte Kapitel oder konvertieren Sie das ganze Buch",
            "Optional können Sie den Text per KI optimieren lassen, für eine natürlichere Lesart (Akronyme, Zahlen und Datumsangaben werden ausgeschrieben, natürliche Pausen eingefügt und typografische Artefakte entfernt)",
            "Starten Sie die Text-to-Speech-Konvertierung mit einem Klick",
            "Bei langen Konvertierungen geben Sie Ihre E-Mail ein, um eine Benachrichtigung mit Download-Link zu erhalten, wenn das Hörbuch fertig ist — Sie können den Browser schließen und später zurückkehren",
            "Laden Sie Ihr Hörbuch im MP3- oder M4B-Format (mit Kapiteln) herunter, bereit zum Anhören auf jedem Gerät",
            "Erstellen Sie einen Podcast-RSS-Feed, um Kapitel in Ihrer Lieblings-App zu hören",
        ],
        "faq_heading": "Häufig Gestellte Fragen — EPUB/PDF-zu-Hörbuch-Konverter",
        "faqs": [
            ("Wie wandelt man ein EPUB oder PDF kostenlos in ein Hörbuch um?",
             "Laden Sie Ihre EPUB- oder PDF-Datei auf Audiobook Maker hoch, wählen Sie eine neuronale KI-Stimme aus über 400 Optionen "
             "und die gewünschte Sprache, dann klicken Sie auf Konvertieren. Der kostenlose Text-to-Speech-Konverter "
             "extrahiert automatisch den Text aus dem Buch — unter Beibehaltung der Dokumentenstruktur und der Kapitelaufteilung — "
             "und erstellt ein Hörbuch im MP3- oder M4B-Format mit eingebetteten Kapiteln, bereit zum Herunterladen und Anhören "
             "auf jedem Gerät (Smartphone, Tablet oder MP3-Player). Keine Registrierung nötig und keine Nutzungsbeschränkungen."),
            ("Was sind PREMIUM-Stimmen?",
             "PREMIUM-Stimmen sind eine kostenpflichtige Option, die modernste Gemini 2.5 Flash- und 3.1 Flash-TTS-Modelle nutzt, um Hörbücher höchster Qualität mit unglaublich natürlichen und ausdrucksstarken Stimmen zu erzeugen. Die Gemini-TTS-Technologie erfasst Nuancen, Emotionen und Intonationen mit einer Wiedergabetreue, die Standardstimmen deutlich übertrifft, und bietet ein professionelles Hörerlebnis, das einer hochwertigen menschlichen Erzählung vergleichbar ist. Die Generierung verwendet optimiertes Chunking, um die narrative Integrität zu bewahren, und jede PREMIUM-Stimme ist im Stimmenwähler mit dem Präfix 'gemini' gekennzeichnet."),
            ("Kann ich ein Buch in eine andere Sprache übersetzen und daraus ein Hörbuch erstellen?",
             "Ja. Audiobook Maker enthält eine integrierte Buchübersetzungsfunktion: Laden Sie Ihre EPUB-, PDF-, TXT- oder ABM-Datei hoch, wählen Sie Ausgangs- und Zielsprache, und die KI übersetzt die ausgewählten Kapitel – mit optionaler KI-Optimierung für eine natürliche Erzählung im selben Schritt. Sie können das übersetzte Buch (EPUB, TXT oder ABM) herunterladen und dann direkt aus dem Ergebnis ein übersetztes Hörbuch mit einer beliebigen neuronalen Stimme erzeugen. Die Übersetzung ist unterhalb einer kleinen Schwelle kostenlos; längere Bücher verursachen geringe Kosten, basierend auf der Zeichenzahl, zahlbar per Gutschein oder PayPal."),
            ("Wird das M4B-Format unterstützt?",
             "Ja, Audiobook Maker kann professionelle Hörbücher im universellen M4B-Format erstellen. "
             "Im Gegensatz zu einfachen MP3-Dateien ermöglicht das M4B-Format die Einbettung "
             "von Kapiteln direkt in die Audiodatei, sodass Titel, Struktur und Metadaten erhalten bleiben. "
             "Es ist das Standardformat für Hörbücher auf Apple Books, iTunes und vielen spezialisierten Apps. "
             "Sie können auch eine MP3-Datei oder ein ZIP-Archiv mit separaten Kapiteln erstellen."),
            ("Welche E-Book-Formate werden unterstützt?",
             "Audiobook Maker unterstützt EPUB-, PDF- und TXT-Formate für die Hörbuch-Konvertierung. "
             "EPUB wird für optimale Ergebnisse empfohlen dank seiner logischen Kapitelstruktur. "
             "PDFs werden vollständig mit erweiterter Textextraktion unterstützt. "
             "Wenn Ihr Buch in einem anderen Format wie MOBI oder AZW vorliegt, können Sie es mit kostenlosen Tools wie Calibre "
             "zunächst in EPUB umwandeln, bevor Sie es hochladen. "
             "Als Ausgabe erhalten Sie MP3, M4B mit Kapiteln oder eine ZIP-Datei mit separaten Kapiteln."),
            ("Wie viele KI-Stimmen sind verfügbar und in welchen Sprachen?",
             "Audiobook Maker bietet über 400 hochwertige neuronale KI-Stimmen basierend auf Microsoft Edge TTS, "
             "mit Unterstützung für Dutzende von Sprachen darunter Deutsch, Englisch, Italienisch, Französisch, "
             "Spanisch, Chinesisch, Portugiesisch, Russisch, Japanisch, Koreanisch, Arabisch, Hindi und viele mehr. "
             "Die App-Oberfläche ist in 6 Sprachen verfügbar, aber die Sprachsynthese-Engine "
             "unterstützt alle Sprachen der Edge TTS-Bibliothek."),
            ("Klingen die KI-Stimmen natürlich?",
             "Ja, der Konverter nutzt hochwertige neuronale TTS-Stimmen basierend auf Microsoft Edge TTS, "
             "mit fortschrittlicher KI-Sprachsynthese, die natürliche, flüssige und angenehme Stimmen erzeugt. "
             "Im Gegensatz zu alten roboterhaften Stimmen erfassen neuronale Stimmen Prosodie, Intonation und Rhythmus, "
             "und bieten ein professionelles Hörerlebnis vergleichbar mit menschlicher Erzählung. "
             "Sie können vor der vollständigen Konvertierung eine kostenlose Vorschau anhören."),
            ("Muss ich etwas installieren?",
             "Nein, Audiobook Maker funktioniert vollständig in Ihrem Webbrowser, ohne jegliche Installation. "
             "Sie müssen keine Software auf Ihrem Computer, Smartphone oder Tablet herunterladen, installieren oder konfigurieren. "
             "Öffnen Sie einfach die Website, laden Sie Ihr Buch hoch und starten Sie die Konvertierung. "
             "Der gesamte Text-to-Speech-Prozess läuft sicher und schnell auf unseren Servern."),
            ("Ist der Dienst wirklich kostenlos?",
             "Ja, Audiobook Maker ist völlig kostenlos und ohne Nutzungsbeschränkungen. "
             "Keine Registrierung erforderlich, keine Kreditkarte nötig und keine Werbung in den erzeugten Audiodateien. "
             "Das Open-Source-Projekt wird durch freiwillige Community-Spenden unterstützt. "
             "Alle Kernfunktionen, einschließlich Text-to-Speech-Konvertierung und M4B-Erzeugung, "
             "sind für alle Nutzer kostenlos verfügbar."),
            ("Ist Audiobook Maker eine kostenlose Alternative zu Speechify?",
             "Ja. Im Gegensatz zu Speechify, das ein kostenpflichtiges Abonnement erfordert, "
             "ist Audiobook Maker 100 % kostenlos, benötigt keine Registrierung und bietet "
             "Hunderte neuronale KI-Stimmen in Dutzenden von Sprachen ohne jegliche Nutzungsbegrenzung. "
             "Einen detaillierten Vergleich mit ähnlichen Tools finden Sie auf "
             "AlternativeTo (https://alternativeto.net/software/audiobook-maker/about/)."),
            ("Welche Tools kann ich verwenden, um ein von Audiobook Maker erstelltes Hörbuch zu hören?",
             "Die von Audiobook Maker erzeugten MP3-Dateien können mit jedem Audioplayer abgespielt werden. "
             "Für das beste Erlebnis auf Android empfehlen wir Smart AudioBook Player, "
             "eine App speziell für Hörbücher, die sich Ihre Hörposition merkt, "
             "Geschwindigkeitsanpassung unterstützt und Kapitel automatisch organisiert. "
             "Auf dem iPhone können Sie Apples Bücher-App oder jeden MP3-Player verwenden. "
             "Alternativ können Sie den von der App generierten Podcast-RSS-Feed nutzen, um "
             "Kapitel direkt in Ihrer Lieblings-Podcast-App zu hören."),
            ("Was ist die KI-Textoptimierung und welche Vorteile bietet sie?",
             "Die KI-Textoptimierung ist ein optionaler Schritt, der von einem LLM-Modell "
             "ausgeführt wird und den aus Ihrem Buch extrahierten Text so umschreibt, "
             "dass er beim Vorlesen natürlich klingt. Sie läuft vor der Sprachsynthese und greift "
             'bei mehreren Aspekten ein: sie dehnt Akronyme aus (z. B. "NASA" → "N.A.S.A.", um '
             "eine buchstabenweise Aussprache zu erzwingen), schreibt Zahlen, Datumsangaben, "
             "Maßeinheiten und Symbole aus, fügt nach Titeln und Szenenwechseln natürliche Pausen "
             "ein, entfernt typografische Artefakte (Fußnoten, eingebundene Literaturverweise, "
             "Silbentrennstriche, doppelte Leerzeichen), korrigiert Anführungszeichen und "
             "Interpunktion für einen flüssigen Leserhythmus und verhindert das Sprachabdriften "
             "der Multilingual-Stimmen, die Sätze manchmal in der falschen Sprache lesen. "
             "Das Ergebnis ist ein deutlich angenehmeres und professionelleres Hörbuch, "
             "vergleichbar mit einer kuratierten Erzählung. Sie können das optimierte Projekt "
             "auch als .abm-Datei herunterladen, um es wiederzuverwenden, zu bearbeiten oder "
             "neue Audiofassungen mit anderen Stimmen zu erstellen, ohne die Optimierung erneut "
             "durchlaufen zu müssen."),
            ("Kann ich einen Podcast aus den Buchkapiteln erstellen?",
             "Ja, Audiobook Maker kann automatisch einen Podcast-RSS-Feed mit allen Kapiteln "
             "Ihres Hörbuchs erstellen. Sie können den Feed-Link kopieren und in jede Podcast-App "
             "wie Apple Podcasts, Spotify, Overcast oder Pocket Casts einfügen, um die Kapitel zu streamen. "
             "Diese Funktion ist ideal zum Hören während der Fahrt oder im Fitnessstudio, "
             "ohne Speicherplatz mit heruntergeladenen Dateien zu belegen."),
],
        "privacy_heading": "Datenschutz und Sicherheit",
        "privacy": (
            "Audiobook Maker respektiert Ihre Privatsphäre. Hochgeladene Dateien und erzeugte Audios "
            "werden am Ende jeder Sitzung automatisch gelöscht. Keine Registrierung erforderlich, "
            "keine personenbezogenen Daten werden erhoben. Open-Source-Projekt unter AGPL-3.0-Lizenz."
        ),
        "accessibility_heading": "Barrierefreiheit und Inklusion",
        "accessibility": (
            "Audiobook Maker ist als inklusives Werkzeug konzipiert. "
            "Die Text-to-Speech-Konvertierung bietet konkrete Unterstützung für Menschen "
            "mit Legasthenie, Sehbehinderungen und Blindheit, indem sie jeden geschriebenen "
            "Text in hochwertiges, hörbares Audio verwandelt. Die Benutzeroberfläche ist "
            "mit Screenreadern kompatibel, unterstützt die vollständige Tastaturnavigation "
            "und verwendet ARIA-Landmarks zur einfachen Orientierung auf der Seite. "
            "Die generierten Audiodateien können auf jedem Gerät abgespielt werden und "
            "bieten ein barrierefreies Leseerlebnis."
        ),
        "guides_heading": "Kostenlose Anleitungen",
        "guides_html": (
            '<ul>'
            '<li><a href="/guide/epub-to-audiobook/?lang=de">EPUB in Hörbuch umwandeln — Vollständige Anleitung</a></li>'
            '<li><a href="/guide/m4b-format/?lang=de">M4B Format Guide — Hörbücher mit Kapiteln erstellen</a></li>'
            '<li><a href="/guide/text-to-speech-audiobook/?lang=de">Kostenloser Text-to-Speech Hörbuch Maker — Beste TTS</a></li>'
            '<li><a href="/guide/podcast/?lang=de">Hörbuch als privaten Podcast veröffentlichen — Kostenlose Anleitung</a></li>'
            '</ul>'
        ),
        "updated_label": "Zuletzt aktualisiert",
        "share_label": "Teilen",
    },
    # ─── 中文 ───────────────────────────────────────────────────────
    "zh": {
        "direct_answer": (
            "Audiobook Maker是一款免费的EPUB和PDF转MP3及M4B有声书转换器，"
            "拥有超过400种神经网络AI语音，支持数十种语言（Microsoft Edge TTS）。"
            "无需注册，无使用限制，直接在浏览器中运行。"
        ),
        "key_takeaways": {
            "title": "快速总结",
            "items": [
                "✅ <strong>100% 免费</strong> — 无需注册，无使用限制",
                 "✅ <strong>M4B 格式</strong> — 支持带嵌入章节的通用有声书格式",
                "✅ <strong>400+ 神经网络AI语音</strong> — 高质量 Microsoft Edge TTS",
                "✅ <strong>50+ 语言</strong> — 中文、英语、意大利语、法语、西班牙语、德语等",
                "✅ <strong>无需安装</strong> — 直接在浏览器中运行",
                "✅ <strong>播客 RSS</strong> — 生成订阅源在您喜爱的应用中收听",
                "✅ <strong>开源</strong> — 透明项目，采用 AGPL-3.0 许可证",
            ],
        },
        "heading": "免费在线将EPUB和PDF电子书转换为MP3及M4B有声书",
        "text": (
            "Audiobook Maker是一款免费在线转换器，利用神经网络AI文字转语音技术"
            "（Microsoft Edge TTS），将您的EPUB和PDF电子书转换为MP3及M4B有声书。"
            "上传EPUB或PDF格式的书籍，从中文、英语、意大利语、法语、西班牙语和德语中"
            "选择超过50种AI语音，然后下载即可收听的有声书。"
            "无需安装任何软件或注册。与Speechify或Play.ht不同，"
            "Audiobook Maker完全免费，无使用限制，无广告。"
        ),
        "audience_heading": "适用人群",
        "audience": (
            "非常适合想在通勤途中听书的上班族、"
            "偏好听觉学习的学生、"
            "视力障碍者以及有阅读困难（如读写困难症）的人群。"
            "也适合任何想要解放双手享受阅读的人。"
        ),
        "table_heading": "可用语言和语音",
        "features_heading": "EPUB/PDF转有声书转换器使用方法",
        "features": [
            "上传EPUB、PDF或TXT文件——转换器支持任意大小的电子书",
            "从超过50种可用选项中选择AI语音和朗读语言",
            "选择要转换的章节或转换整本书",
            "可选：通过AI优化文本以获得更自然的朗读效果（展开首字母缩略词、数字、日期，插入停顿并清除排版伪影）",
            "一键启动文字转语音转换，等待处理完成",
            "对于较长的转换，输入您的电子邮件以便在有声书准备就绪时收到带有下载链接的通知——您可以关闭浏览器，稍后再回来",
            "下载MP3或M4B（含章节）格式的有声书，可在任何设备上收听",
            "生成播客RSS订阅源，在您喜爱的应用中收听章节",
        ],
        "faq_heading": "常见问题 — EPUB/PDF转有声书转换器",
        "faqs": [
            ("如何免费将EPUB或PDF转换为有声书？",
             "将EPUB或PDF文件上传到Audiobook Maker，从400多种神经网络AI语音中选择合适的声音和语言，"
             "然后点击转换。免费文字转语音转换器会自动提取书中文本——保留文档结构和章节划分——"
             "并生成带有嵌入式章节的MP3或M4B格式有声书，可随时下载并在任何设备"
             "（智能手机、平板电脑或MP3播放器）上收听。无需注册，也没有使用限制。"),
            ("什么是 PREMIUM 语音？",
             "PREMIUM 语音是一项付费选项，利用尖端的 Gemini 2.5 Flash 和 3.1 Flash TTS 模型生成超高品质的有声书，语音极其自然且富有表现力。Gemini TTS 技术能够以远超标准语音的保真度捕捉细微差别、情感和语调，提供可与高端人工朗读相媚美的专业聆听体验。生成过程采用优化的分块技术以保持叙事完整性，每款 PREMIUM 语音在语音选择器中均以 'gemini' 前缀标识。"),
            ("我可以把一本书翻译成另一种语言并据此制作有声书吗？",
             "可以。Audiobook Maker 内置图书翻译功能：上传你的 EPUB、PDF、TXT 或 ABM 文件，选择源语言和目标语言，AI 即可翻译所选章节，并在同一步骤中可选地应用 AI 优化以获得自然的朗读效果。你可以下载翻译后的图书（EPUB、TXT 或 ABM），然后直接基于翻译结果生成译文有声书，并使用任意一种神经网络语音。翻译在小额阈值以下免费；篇幅较长的图书会按字符数收取少量费用，可通过抵用券或 PayPal 支付。"),
            ("你们支持 M4B 格式吗？",
             "支持。Audiobook Maker 可以生成专业级通用 M4B 格式有声书。"
             "与普通 MP3 文件不同，M4B 格式允许直接在音频文件中嵌入章节，"
             "保留章节标题、结构和元数据。它是 Apple Books、iTunes 及许多专业应用的标准有声书格式。"
             "您还可以生成 MP3 文件或包含独立章节的 ZIP 压缩包，以满足不同需求。"),
            ("支持哪些电子书格式？",
             "Audiobook Maker 支持 EPUB、PDF 和 TXT 格式用于有声书转换。"
             "推荐使用 EPUB 以获得最佳效果，因为它具有清晰的章节逻辑结构。"
             "PDF 也完全支持，并具备先进的文本提取功能。"
             "如果您的书籍是 MOBI 或 AZW 等其他格式，可以先用 Calibre 等免费工具轻松转换为 EPUB 后再上传。"
             "输出格式包括 MP3、带章节的 M4B 或分章节的 ZIP 压缩包。"),
            ("有多少种AI语音可用？支持哪些语言？",
             "Audiobook Maker提供超过400种高质量神经网络AI语音（基于Microsoft Edge TTS），"
             "支持数十种语言，包括中文、英语、意大利语、法语、西班牙语、德语、"
             "葡萄牙语、俄语、日语、韩语、阿拉伯语、印地语等。"
             "应用界面提供6种语言，但语音合成引擎支持Edge TTS库提供的所有语言。"),
            ("AI语音听起来自然吗？",
             "是的，转换器使用基于 Microsoft Edge TTS 的高质量神经网络 TTS 语音，"
             "结合先进的 AI 语音合成技术，能够产生自然、流畅且悦耳的声音。"
             "与旧式机械语音不同，神经网络语音能够捕捉语调、韵律和节奏，"
             "提供可与真人朗读相媲美的专业听觉体验。"
             "您可以在开始完整转换前免费试听预览。"),
            ("需要安装什么吗？",
             "不需要，Audiobook Maker 完全在网页浏览器中运行，无需任何安装。"
             "您无需在电脑、智能手机或平板电脑上下载、安装或配置任何软件。"
             "只需打开网站，上传书籍并启动转换即可。"
             "整个文字转语音过程在我们的服务器上安全快速地完成。"),
            ("服务真的免费吗？",
             "是的，Audiobook Maker 完全免费，没有使用限制。"
             "无需注册，无需信用卡，生成的音频文件中也没有任何广告。"
             "这个开源项目由社区自愿捐赠支持。"
             "所有核心功能，包括文字转语音转换和 M4B 生成，均对所有用户免费开放。"),
            ("Audiobook Maker 是 Speechify 的免费替代品吗？",
             "是的。与 Speechify 需要付费订阅不同，Audiobook Maker 100% 免费，"
             "无需注册，并提供数十种语言的数百种神经网络 AI 语音，没有任何使用限制。"
             "您可以在 AlternativeTo (https://alternativeto.net/software/audiobook-maker/about/) 上找到与类似工具的详细对比。"),
            ("可以用什么工具收听Audiobook Maker生成的有声书？",
             "Audiobook Maker生成的MP3文件可以用任何音频播放器播放。"
             "在Android上，我们推荐Smart AudioBook Player，"
             "这是一款专为有声书设计的应用，能记住您的收听位置、"
             "支持速度调节并自动整理章节。"
             "在iPhone上，您可以使用Apple图书应用或任何MP3播放器。"
             "您也可以使用应用生成的播客RSS订阅源，"
             "直接在您喜爱的播客应用中收听章节。"),
            ("什么是AI文本优化？它有哪些优势？",
             "AI文本优化是一个可选步骤，由大语言模型（LLM）执行，"
             "用于对从书籍中提取的文本进行改写，使其在朗读时更加自然。"
             "它在语音合成之前运行，处理多个方面："
             '展开首字母缩略词（例如"NASA" → "N.A.S.A."以强制逐字母发音）、'
             "将数字、日期、计量单位和符号以完整词形展开、"
             "在标题和场景切换后插入自然停顿、"
             "去除排版伪影（脚注、正文内参考文献、音节连字符、双空格）、"
             "修正引号和标点以获得流畅的阅读节奏，"
             "并防止多语言（Multilingual）语音出现语言漂移（即偶尔用错误语言朗读句子）。"
             "最终结果是一个明显更悦耳、更专业的有声书，堪比精心制作的叙述。"
             "您还可以下载.abm格式的优化后项目，"
             "以便复用、编辑或用不同声音生成新的音频版本，无需重新运行优化。"),
            ("可以从书籍章节生成播客吗？",
             "可以，Audiobook Maker 能自动生成包含所有章节的播客 RSS 订阅源。"
             "您可以复制订阅源链接并添加到 Apple 播客、Spotify、Overcast 或 Pocket Casts 等任何播客应用，"
             "以便流媒体收听各章节。此功能非常适合在驾驶或健身时听书，"
             "无需将文件下载到设备上占用空间。"),
],
        "privacy_heading": "隐私与安全",
        "privacy": (
            "Audiobook Maker尊重您的隐私。上传的文件和生成的音频在每次会话结束时自动删除。"
            "无需注册，不收集个人数据。项目以AGPL-3.0许可证开源。"
        ),
        "accessibility_heading": "无障碍与包容性",
        "accessibility": (
            "Audiobook Maker 是一个包容性工具。"
            "文字转语音功能为阅读障碍、视障和盲人用户提供切实支持，将任何书面文字转换为"
            "可随时随地收听的高品质音频。界面兼容屏幕阅读器，支持完整键盘导航，并使用"
            "ARIA地标帮助用户在页面中轻松定位。生成的音频文件可在任何设备上播放，"
            "提供无障碍、无壁垒的阅读体验。"
        ),
        "guides_heading": "免费指南",
        "guides_html": (
            '<ul>'
            '<li><a href="/guide/epub-to-audiobook/?lang=zh">如何将EPUB转换为有声书 — 完整指南</a></li>'
            '<li><a href="/guide/m4b-format/?lang=zh">M4B格式指南 — 创建带章节的有声书</a></li>'
            '<li><a href="/guide/text-to-speech-audiobook/?lang=zh">免费文字转语音有声书制作 — 最佳TTS语音</a></li>'
            '<li><a href="/guide/podcast/?lang=zh">如何将有声书发布为私人播客 — 免费指南</a></li>'
            '</ul>'
        ),
        "updated_label": "最后更新",
        "share_label": "分享",
    },
    "hi": {
        "direct_answer": (
            "Audiobook Maker एक मुफ़्त EPUB और PDF से MP3 तथा M4B ऑडियोबुक कनवर्टर है, "
            "जिसमें दर्जनों भाषाओं में 400 से अधिक न्यूरल AI आवाज़ें (Microsoft Edge TTS) उपलब्ध हैं. "
            "कोई पंजीकरण नहीं, कोई उपयोग सीमा नहीं, सीधे ब्राउज़र में चलता है."
        ),
        "key_takeaways": {
            "title": "त्वरित सारांश",
            "items": [
                "✅ <strong>100% मुफ़्त</strong> — कोई पंजीकरण नहीं, कोई उपयोग सीमा नहीं",
                "✅ <strong>M4B प्रारूप</strong> — एम्बेडेड अध्यायों के साथ सार्वभौमिक ऑडियोबुक प्रारूप",
                "✅ <strong>400+ न्यूरल AI आवाज़ें</strong> — उच्च-गुणवत्ता Microsoft Edge TTS",
                "✅ <strong>50+ भाषाएँ</strong> — हिंदी, अंग्रेज़ी, इतालवी, फ़्रांसीसी, स्पेनिश, जर्मन और कई और",
                "✅ <strong>कोई इंस्टॉलेशन नहीं</strong> — सीधे ब्राउज़र में चलता है",
                "✅ <strong>पॉडकास्ट RSS</strong> — अपने पसंदीदा ऐप में सुनने के लिए फ़ीड जनरेट करें",
                "✅ <strong>ओपन सोर्स</strong> — पारदर्शी परियोजना, AGPL-3.0 लाइसेंस",
            ],
        },
        "heading": "EPUB और PDF ईबुक्स को मुफ़्त में ऑनलाइन MP3 तथा M4B ऑडियोबुक में बदलें",
        "text": (
            "Audiobook Maker एक मुफ़्त ऑनलाइन कनवर्टर है जो न्यूरल AI टेक्स्ट-टू-स्पीच "
            "(Microsoft Edge TTS) का उपयोग करके आपकी EPUB और PDF ईबुक्स को MP3 तथा M4B "
            "ऑडियोबुक में बदल देता है. EPUB या PDF प्रारूप में अपनी पुस्तक अपलोड करें, "
            "हिंदी, अंग्रेज़ी, इतालवी, फ़्रांसीसी, स्पेनिश और जर्मन सहित 50 से अधिक AI आवाज़ों में से चुनें, "
            "और सुनने के लिए तैयार ऑडियोबुक डाउनलोड करें. कोई सॉफ़्टवेयर इंस्टॉल करने या पंजीकरण करने की आवश्यकता नहीं. "
            "Speechify या Play.ht के विपरीत, Audiobook Maker पूरी तरह से मुफ़्त है, "
            "बिना उपयोग सीमा और बिना विज्ञापन के."
        ),
        "audience_heading": "यह किसके लिए है",
        "audience": (
            "उन कामकाजी पेशेवरों के लिए आदर्श जो आने-जाने के दौरान पुस्तकें सुनना चाहते हैं, "
            "ऐसे छात्र जो श्रवण शिक्षण को प्राथमिकता देते हैं, "
            "दृष्टिबाधित व्यक्तियों के लिए और डिस्लेक्सिया जैसी पढ़ने की कठिनाइयों वाले लोगों के लिए. "
            "किसी के लिए भी उपयुक्त जो अपने हाथों को मुक्त रखते हुए पढ़ने का आनंद लेना चाहता है."
        ),
        "table_heading": "उपलब्ध भाषाएँ और आवाज़ें",
        "features_heading": "EPUB/PDF से ऑडियोबुक कनवर्टर का उपयोग कैसे करें",
        "features": [
            "EPUB, PDF या TXT फ़ाइल अपलोड करें — कनवर्टर किसी भी आकार की ईबुक्स को संभालता है",
            "50 से अधिक उपलब्ध विकल्पों में से AI आवाज़ और कथन भाषा चुनें",
            "वे अध्याय चुनें जिन्हें आप कनवर्ट करना चाहते हैं या पूरी पुस्तक को कनवर्ट करें",
            "वैकल्पिक: अधिक प्राकृतिक कथन के लिए AI के साथ टेक्स्ट को अनुकूलित करें (परिवर्णी शब्दों, संख्याओं, तिथियों का विस्तार, विराम सम्मिलित करना और टाइपोग्राफिक कलाकृतियों को साफ़ करना)",
            "एक क्लिक से टेक्स्ट-टू-स्पीच रूपांतरण शुरू करें और प्रसंस्करण समाप्त होने की प्रतीक्षा करें",
            "लंबे रूपांतरणों के लिए, अपना ईमेल दर्ज करें ताकि जब आपकी ऑडियोबुक तैयार हो तो आपको डाउनलोड लिंक के साथ सूचित किया जा सके — आप ब्राउज़र बंद कर सकते हैं और बाद में वापस आ सकते हैं",
            "MP3 या M4B (अध्यायों के साथ) प्रारूप में ऑडियोबुक डाउनलोड करें, किसी भी डिवाइस पर सुनने के लिए तैयार",
            "अपने पसंदीदा ऐप में अध्यायों को सुनने के लिए पॉडकास्ट RSS फ़ीड जनरेट करें",
        ],
        "faq_heading": "अक्सर पूछे जाने वाले प्रश्न — EPUB/PDF से ऑडियोबुक कनवर्टर",
        "faqs": [
            ("EPUB या PDF को मुफ़्त में ऑडियोबुक में कैसे बदलें?",
             "Audiobook Maker पर अपनी EPUB या PDF फ़ाइल अपलोड करें, 400 से अधिक न्यूरल AI आवाज़ों में से सही आवाज़ और भाषा चुनें, "
             "और कनवर्ट पर क्लिक करें. मुफ़्त टेक्स्ट-टू-स्पीच कनवर्टर पुस्तक का पाठ स्वचालित रूप से निकालता है "
             "— दस्तावेज़ संरचना और अध्याय विभाजन को संरक्षित करते हुए — और एम्बेडेड अध्यायों के साथ MP3 या M4B प्रारूप में ऑडियोबुक जनरेट करता है, "
             "जो डाउनलोड और किसी भी डिवाइस (स्मार्टफ़ोन, टैबलेट या MP3 प्लेयर) पर सुनने के लिए तैयार है. कोई पंजीकरण नहीं, कोई उपयोग सीमा नहीं."),
            ("प्रीमियम आवाज़ें क्या हैं?",
             "प्रीमियम आवाज़ें एक सशुल्क विकल्प हैं जो अत्याधुनिक Gemini 2.5 Flash और 3.1 Flash TTS मॉडल का उपयोग करके उत्कृष्ट गुणवत्ता वाली ऑडियोबुक उत्पन्न करती हैं। Gemini TTS तकनीक मानक आवाज़ों से कहीं अधिक निष्ठा के साथ बारीकियों, भावनाओं और स्वर-शैली को पकड़ती है, जो उच्च-स्तरीय मानव वर्णन के बराबर एक पेशेवर श्रवण अनुभव प्रदान करती है। उत्पादन में कथानक अखंडता बनाए रखने के लिए अनुकूलित चंकिंग का उपयोग किया जाता है, और प्रत्येक प्रीमियम आवाज़ आवाज़ चयनकर्ता में 'gemini' उपसर्ग से चिह्नित हैं।"),
            ("क्या मैं किसी पुस्तक का दूसरी भाषा में अनुवाद करके उससे ऑडियोबुक बना सकता हूँ?",
             "हाँ। Audiobook Maker में एकीकृत पुस्तक अनुवाद सुविधा शामिल है: अपनी EPUB, PDF, TXT या ABM फ़ाइल अपलोड करें, स्रोत और लक्ष्य भाषा चुनें, और AI चयनित अध्यायों का अनुवाद करता है — उसी चरण में स्वाभाविक वर्णन के लिए वैकल्पिक AI अनुकूलन के साथ। आप अनुवादित पुस्तक (EPUB, TXT या ABM) डाउनलोड कर सकते हैं और फिर परिणाम से सीधे किसी भी न्यूरल आवाज़ का उपयोग करके अनुवादित ऑडियोबुक बना सकते हैं। अनुवाद एक छोटी सीमा से नीचे मुफ़्त है; लंबी पुस्तकों पर वर्णों की संख्या के आधार पर थोड़ा शुल्क लगता है, जो वाउचर या PayPal से देय है।"),
            ("क्या आप M4B प्रारूप का समर्थन करते हैं?",
             "हाँ. Audiobook Maker पेशेवर-गुणवत्ता वाले सार्वभौमिक M4B प्रारूप में ऑडियोबुक जनरेट कर सकता है. "
             "साधारण MP3 फ़ाइलों के विपरीत, M4B प्रारूप ऑडियो फ़ाइल में सीधे अध्यायों को एम्बेड करने की अनुमति देता है, "
             "अध्याय शीर्षकों, संरचना और मेटाडेटा को संरक्षित करता है. यह Apple Books, iTunes और कई पेशेवर ऐप्स के लिए मानक ऑडियोबुक प्रारूप है. "
             "आप विभिन्न आवश्यकताओं के लिए MP3 फ़ाइलें या अलग-अलग अध्यायों के साथ ZIP संग्रह भी जनरेट कर सकते हैं."),
            ("कौन से ईबुक प्रारूप समर्थित हैं?",
             "Audiobook Maker ऑडियोबुक रूपांतरण के लिए EPUB, PDF और TXT प्रारूपों का समर्थन करता है. "
             "बेहतरीन परिणामों के लिए EPUB की अनुशंसा की जाती है क्योंकि इसमें स्पष्ट अध्याय तार्किक संरचना होती है. "
             "PDF भी पूरी तरह से समर्थित है उन्नत पाठ निष्कर्षण के साथ. "
             "यदि आपकी पुस्तक MOBI या AZW जैसे अन्य प्रारूप में है, तो आप पहले Calibre जैसे मुफ़्त उपकरणों के साथ इसे आसानी से EPUB में बदल सकते हैं और फिर अपलोड कर सकते हैं. "
             "आउटपुट प्रारूपों में MP3, अध्यायों के साथ M4B या अलग अध्यायों के साथ ZIP संग्रह शामिल हैं."),
            ("कितनी AI आवाज़ें उपलब्ध हैं और कौन सी भाषाएँ समर्थित हैं?",
             "Audiobook Maker 400 से अधिक उच्च-गुणवत्ता वाली न्यूरल AI आवाज़ें प्रदान करता है (Microsoft Edge TTS पर आधारित), "
             "जो हिंदी, अंग्रेज़ी, इतालवी, फ़्रांसीसी, स्पेनिश, जर्मन, पुर्तगाली, रूसी, जापानी, कोरियाई, अरबी, चीनी और कई अन्य सहित दर्जनों भाषाओं का समर्थन करती हैं. "
             "एप्लिकेशन इंटरफ़ेस 7 भाषाओं में उपलब्ध है, लेकिन वॉइस सिंथेसिस इंजन Edge TTS लाइब्रेरी द्वारा प्रदान की गई सभी भाषाओं का समर्थन करता है."),
            ("क्या AI आवाज़ें प्राकृतिक लगती हैं?",
             "हाँ, कनवर्टर Microsoft Edge TTS पर आधारित उच्च-गुणवत्ता वाली न्यूरल TTS आवाज़ों का उपयोग करता है, "
             "जो उन्नत AI वॉइस सिंथेसिस तकनीक के साथ मिलकर प्राकृतिक, धाराप्रवाह और सुखद ध्वनि उत्पन्न करती हैं. "
             "पुरानी यांत्रिक आवाज़ों के विपरीत, न्यूरल आवाज़ें स्वर, छंद और लय को पकड़ती हैं, "
             "जो मानव कथन के समान पेशेवर श्रवण अनुभव प्रदान करती हैं. "
             "आप पूर्ण रूपांतरण शुरू करने से पहले मुफ़्त पूर्वावलोकन सुन सकते हैं."),
            ("क्या मुझे कुछ इंस्टॉल करने की आवश्यकता है?",
             "नहीं, Audiobook Maker पूरी तरह से वेब ब्राउज़र में चलता है, बिना किसी इंस्टॉलेशन के. "
             "आपको अपने कंप्यूटर, स्मार्टफ़ोन या टैबलेट पर कुछ भी डाउनलोड, इंस्टॉल या कॉन्फ़िगर करने की आवश्यकता नहीं है. "
             "बस वेबसाइट खोलें, अपनी पुस्तक अपलोड करें और रूपांतरण शुरू करें. "
             "पूरी टेक्स्ट-टू-स्पीच प्रक्रिया हमारे सर्वर पर सुरक्षित और तेज़ी से होती है."),
            ("क्या सेवा वास्तव में मुफ़्त है?",
             "हाँ, Audiobook Maker पूरी तरह से मुफ़्त है, बिना उपयोग सीमा के. "
             "कोई पंजीकरण आवश्यक नहीं, कोई क्रेडिट कार्ड नहीं, और जनरेट की गई ऑडियो फ़ाइलों में कोई विज्ञापन नहीं. "
             "यह ओपन सोर्स परियोजना सामुदायिक स्वैच्छिक दान द्वारा समर्थित है. "
             "टेक्स्ट-टू-स्पीच रूपांतरण और M4B जनरेशन सहित सभी मुख्य सुविधाएँ सभी उपयोगकर्ताओं के लिए मुफ़्त रूप से उपलब्ध हैं."),
            ("क्या Audiobook Maker Speechify का मुफ़्त विकल्प है?",
             "हाँ. Speechify के विपरीत जिसे भुगतान सदस्यता की आवश्यकता होती है, Audiobook Maker 100% मुफ़्त है, "
             "बिना पंजीकरण के, और दर्जनों भाषाओं में सैकड़ों न्यूरल AI आवाज़ें प्रदान करता है, बिना किसी उपयोग सीमा के. "
             "आप समान उपकरणों के साथ विस्तृत तुलना AlternativeTo (https://alternativeto.net/software/audiobook-maker/about/) पर पा सकते हैं."),
            ("Audiobook Maker द्वारा जनरेट की गई ऑडियोबुक्स को मैं कैसे सुन सकता हूँ?",
             "Audiobook Maker द्वारा जनरेट की गई MP3 फ़ाइलें किसी भी ऑडियो प्लेयर के साथ चलाई जा सकती हैं. "
             "Android पर, हम Smart AudioBook Player की अनुशंसा करते हैं, "
             "जो ऑडियोबुक्स के लिए विशेष रूप से डिज़ाइन किया गया ऐप है जो आपकी सुनने की स्थिति याद रखता है, "
             "गति समायोजन का समर्थन करता है और अध्यायों को स्वचालित रूप से व्यवस्थित करता है. "
             "iPhone पर, आप Apple Books ऐप या किसी भी MP3 प्लेयर का उपयोग कर सकते हैं. "
             "आप ऐप द्वारा जनरेट किए गए पॉडकास्ट RSS फ़ीड का उपयोग भी कर सकते हैं, "
             "सीधे अपने पसंदीदा पॉडकास्ट ऐप में अध्यायों को सुनने के लिए."),
            ("AI टेक्स्ट ऑप्टिमाइज़ेशन क्या है और इसके क्या लाभ हैं?",
             "AI टेक्स्ट ऑप्टिमाइज़ेशन एक वैकल्पिक चरण है जो लार्ज लैंग्वेज मॉडल (LLM) द्वारा किया जाता है, "
             "जिसका उपयोग पुस्तकों से निकाले गए पाठ को फिर से लिखने के लिए किया जाता है ताकि कथन के समय अधिक प्राकृतिक हो. "
             "यह वॉइस सिंथेसिस से पहले चलता है और कई पहलुओं को संभालता है: "
             'परिवर्णी शब्दों का विस्तार (उदाहरण के लिए "NASA" → "एन.ए.एस.ए." अक्षर-दर-अक्षर उच्चारण को बाध्य करने के लिए), '
             "संख्याओं, तिथियों, माप की इकाइयों और प्रतीकों को पूर्ण शब्द रूप में विस्तारित करना, "
             "शीर्षकों और दृश्य परिवर्तन के बाद प्राकृतिक विराम सम्मिलित करना, "
             "टाइपोग्राफिक कलाकृतियों को हटाना (फ़ुटनोट, इन-टेक्स्ट संदर्भ, शब्दांश हाइफ़न, डबल स्पेस), "
             "धाराप्रवाह पठन लय के लिए उद्धरण चिह्नों और विराम चिह्नों को सही करना, "
             "और बहुभाषी (Multilingual) आवाज़ों को भाषा बहाव से रोकना (यानी कभी-कभी गलत भाषा में वाक्य पढ़ना). "
             "अंतिम परिणाम एक स्पष्ट रूप से अधिक सुखद और पेशेवर ऑडियोबुक है, जो सावधानीपूर्वक बनाई गई कथा के समतुल्य है. "
             "आप .abm प्रारूप में अनुकूलित परियोजना डाउनलोड भी कर सकते हैं, "
             "पुन: उपयोग, संपादन या अनुकूलन को फिर से चलाए बिना विभिन्न आवाज़ों के साथ नए ऑडियो संस्करण जनरेट करने के लिए."),
            ("क्या मैं पुस्तक के अध्यायों से पॉडकास्ट बना सकता हूँ?",
             "हाँ, Audiobook Maker स्वचालित रूप से सभी अध्यायों के साथ एक पॉडकास्ट RSS फ़ीड जनरेट कर सकता है. "
             "आप फ़ीड लिंक कॉपी कर सकते हैं और इसे Apple Podcasts, Spotify, Overcast या Pocket Casts जैसे किसी भी पॉडकास्ट ऐप में जोड़ सकते हैं "
             "ताकि अध्यायों को स्ट्रीम कर सकें. यह सुविधा ड्राइविंग या व्यायाम के दौरान पुस्तकें सुनने के लिए एकदम सही है, "
             "बिना डिवाइस पर स्थान घेरने वाली फ़ाइलें डाउनलोड किए."),
],
        "privacy_heading": "गोपनीयता और सुरक्षा",
        "privacy": (
            "Audiobook Maker आपकी गोपनीयता का सम्मान करता है. अपलोड की गई फ़ाइलें और जनरेट किए गए ऑडियो प्रत्येक सत्र के अंत में स्वचालित रूप से हटा दिए जाते हैं. "
            "कोई पंजीकरण आवश्यक नहीं, कोई व्यक्तिगत डेटा एकत्र नहीं किया जाता. परियोजना AGPL-3.0 लाइसेंस के तहत ओपन सोर्स है."
        ),
        "accessibility_heading": "अभिगम्यता और समावेशिता",
        "accessibility": (
            "Audiobook Maker एक समावेशी उपकरण है. "
            "टेक्स्ट-टू-स्पीच सुविधा डिस्लेक्सिया, दृष्टिबाधित और नेत्रहीन उपयोगकर्ताओं के लिए ठोस सहायता प्रदान करती है, "
            "किसी भी लिखित पाठ को कहीं भी, कभी भी सुनने योग्य उच्च-गुणवत्ता वाले ऑडियो में परिवर्तित करती है. "
            "इंटरफ़ेस स्क्रीन रीडर के साथ संगत है, पूर्ण कीबोर्ड नेविगेशन का समर्थन करता है, और उपयोगकर्ताओं को पृष्ठ में आसानी से अभिविन्यास में मदद करने के लिए "
            "ARIA लैंडमार्क का उपयोग करता है. जनरेट की गई ऑडियो फ़ाइलें किसी भी डिवाइस पर चलाई जा सकती हैं, "
            "एक सुलभ और बाधा-मुक्त पठन अनुभव प्रदान करती हैं."
        ),
        "guides_heading": "मुफ़्त गाइड",
        "guides_html": (
            '<ul>'
            '<li><a href="/guide/epub-to-audiobook/?lang=hi">EPUB को ऑडियोबुक में कैसे बदलें — पूरी गाइड</a></li>'
            '<li><a href="/guide/m4b-format/?lang=hi">M4B प्रारूप गाइड — अध्यायों के साथ ऑडियोबुक बनाएं</a></li>'
            '<li><a href="/guide/text-to-speech-audiobook/?lang=hi">मुफ़्त टेक्स्ट-टू-स्पीच ऑडियोबुक निर्माण — सर्वश्रेष्ठ TTS आवाज़ें</a></li>'
            '<li><a href="/guide/podcast/?lang=hi">ऑडियोबुक्स को निजी पॉडकास्ट के रूप में कैसे प्रकाशित करें — मुफ़्त गाइड</a></li>'
            '</ul>'
        ),
        "updated_label": "अंतिम अद्यतन",
        "share_label": "साझा करें",
    },
}


# ─── Tabella comparativa voci/lingue (condivisa, labels per lingua) ───

_VOICE_TABLE = [
    # (language_code, label_per_lang, approx_voice_count)
    ("en", {"it": "Inglese", "en": "English", "fr": "Anglais", "es": "Inglés", "de": "Englisch", "zh": "英语", "hi": "अंग्रेज़ी"}, "14+"),
    ("it", {"it": "Italiano", "en": "Italian", "fr": "Italien", "es": "Italiano", "de": "Italienisch", "zh": "意大利语", "hi": "इतालवी"}, "8+"),
    ("fr", {"it": "Francese", "en": "French", "fr": "Français", "es": "Francés", "de": "Französisch", "zh": "法语", "hi": "फ़्रांसीसी"}, "8+"),
    ("es", {"it": "Spagnolo", "en": "Spanish", "fr": "Espagnol", "es": "Español", "de": "Spanisch", "zh": "西班牙语", "hi": "स्पेनिश"}, "7+"),
    ("de", {"it": "Tedesco", "en": "German", "fr": "Allemand", "es": "Alemán", "de": "Deutsch", "zh": "德语", "hi": "जर्मन"}, "7+"),
    ("zh", {"it": "Cinese", "en": "Chinese", "fr": "Chinois", "es": "Chino", "de": "Chinesisch", "zh": "中文", "hi": "चीनी"}, "10+"),
    ("hi", {"it": "Hindi", "en": "Hindi", "fr": "Hindi", "es": "Hindi", "de": "Hindi", "zh": "印地语", "hi": "हिन्दी"}, "2+"),
    ("other", {
        "it": "Altre lingue (portoghese, russo, giapponese, coreano, arabo, ecc.)",
        "en": "Other languages (Portuguese, Russian, Japanese, Korean, Arabic, etc.)",
        "fr": "Autres langues (portugais, russe, japonais, coréen, arabe, etc.)",
        "es": "Otros idiomas (portugués, ruso, japonés, coreano, árabe, etc.)",
        "de": "Weitere Sprachen (Portugiesisch, Russisch, Japanisch, Koreanisch, Arabisch, usw.)",
        "zh": "其他语言（葡萄牙语、俄语、日语、韩语、阿拉伯语等）",
        "hi": "अन्य भाषाएं (पुर्तगाली, रूसी, जापानी, कोरियाई, अरबी, आदि)",
    }, "350+"),
]

_TABLE_HEADERS = {
    "it": ("Lingua", "Voci AI", "Tecnologia"),
    "en": ("Language", "AI Voices", "Technology"),
    "fr": ("Langue", "Voix IA", "Technologie"),
    "es": ("Idioma", "Voces IA", "Tecnología"),
    "de": ("Sprache", "KI-Stimmen", "Technologie"),
    "zh": ("语言", "AI语音", "技术"),
    "hi": ("भाषा", "AI आवाज़ें", "तकनीक"),
}


# ─── HowTo steps per lingua ───

_HOWTO_STEPS = {
    "it": [
        ("Carica il tuo ebook", "Carica il tuo file EPUB, PDF o TXT su Audiobook Maker"),
        ("Scegli la voce", "Seleziona una voce AI e la lingua di narrazione tra le opzioni disponibili"),
        ("Seleziona i capitoli", "Scegli i capitoli da convertire o seleziona l'intero libro"),
        ("Avvia la conversione", "Clicca su Genera e attendi l'elaborazione text-to-speech. Per conversioni lunghe puoi inserire la tua email per ricevere una notifica al termine"),
        ("Scarica l'audiolibro", "Scarica il tuo audiolibro in formato MP3 dal browser o dal link ricevuto via email, oppure genera un feed podcast RSS"),
    ],
    "en": [
        ("Upload your ebook", "Upload your EPUB, PDF, or TXT file to Audiobook Maker"),
        ("Choose a voice", "Select an AI voice and narration language from the available options"),
        ("Select chapters", "Pick the chapters to convert or select the entire book"),
        ("Start conversion", "Click Generate and wait for text-to-speech processing. For long conversions you can enter your email to be notified when it is ready"),
        ("Download audiobook", "Download your audiobook in MP3 format from the browser or via the email link, or generate a podcast RSS feed"),
    ],
    "fr": [
        ("Téléchargez votre ebook", "Téléchargez votre fichier EPUB, PDF ou TXT sur Audiobook Maker"),
        ("Choisissez une voix", "Sélectionnez une voix IA et la langue de narration parmi les options disponibles"),
        ("Sélectionnez les chapitres", "Choisissez les chapitres à convertir ou sélectionnez le livre entier"),
        ("Lancez la conversion", "Cliquez sur Générer et attendez le traitement text-to-speech. Pour les longues conversions, vous pouvez entrer votre email pour être notifié quand c'est prêt"),
        ("Téléchargez le livre audio", "Téléchargez votre livre audio en MP3 depuis le navigateur ou via le lien email, ou générez un flux RSS podcast"),
    ],
    "es": [
        ("Sube tu ebook", "Sube tu archivo EPUB, PDF o TXT a Audiobook Maker"),
        ("Elige una voz", "Selecciona una voz IA y el idioma de narración entre las opciones disponibles"),
        ("Selecciona los capítulos", "Elige los capítulos a convertir o selecciona el libro completo"),
        ("Inicia la conversión", "Haz clic en Generar y espera el procesamiento text-to-speech. Para conversiones largas puedes introducir tu email para recibir una notificación al terminar"),
        ("Descarga el audiolibro", "Descarga tu audiolibro en formato MP3 desde el navegador o mediante el enlace del email, o genera un feed podcast RSS"),
    ],
    "de": [
        ("E-Book hochladen", "Laden Sie Ihre EPUB-, PDF- oder TXT-Datei auf Audiobook Maker hoch"),
        ("Stimme wählen", "Wählen Sie eine KI-Stimme und Erzählsprache aus den verfügbaren Optionen"),
        ("Kapitel auswählen", "Wählen Sie bestimmte Kapitel oder das ganze Buch"),
        ("Konvertierung starten", "Klicken Sie auf Generieren und warten Sie auf die Text-to-Speech-Verarbeitung. Bei langen Konvertierungen können Sie Ihre E-Mail eingeben, um benachrichtigt zu werden"),
        ("Hörbuch herunterladen", "Laden Sie Ihr Hörbuch im MP3-Format vom Browser oder über den E-Mail-Link herunter, oder erstellen Sie einen Podcast-RSS-Feed"),
    ],
    "zh": [
        ("上传电子书", "将EPUB、PDF或TXT文件上传到Audiobook Maker"),
        ("选择语音", "从可用选项中选择AI语音和朗读语言"),
        ("选择章节", "选择要转换的章节或选择整本书"),
        ("开始转换", "点击生成，等待文字转语音处理完成。对于较长的转换，您可以输入电子邮件以便在完成时收到通知"),
        ("下载有声书", "从浏览器或通过电子邮件链接下载MP3格式的有声书，或生成播客RSS订阅源"),
    ],
    "hi": [
        ("अपनी ईबुक अपलोड करें", "अपनी EPUB, PDF या TXT फ़ाइल Audiobook Maker पर अपलोड करें"),
        ("एक आवाज़ चुनें", "उपलब्ध विकल्पों में से एक AI आवाज़ और कथन भाषा चुनें"),
        ("अध्याय चुनें", "बदलने के लिए अध्याय चुनें या पूरी पुस्तक का चयन करें"),
        ("रूपांतरण शुरू करें", "जनरेट पर क्लिक करें और टेक्स्ट-टू-स्पीच प्रोसेसिंग की प्रतीक्षा करें. लंबे रूपांतरणों के लिए आप अपना ईमेल दर्ज कर सकते हैं ताकि तैयार होने पर सूचित किया जाए"),
        ("ऑडियोबुक डाउनलोड करें", "ब्राउज़र से या ईमेल लिंक के माध्यम से MP3 प्रारूप में अपनी ऑडियोबुक डाउनलोड करें, या पॉडकास्ट RSS फ़ीड जनरेट करें"),
    ],
}


# ─── Feature lists per JSON-LD SoftwareApplication ───

_LD_FEATURES = {
    "it": [
        "Conversione da EPUB a audiolibro MP3/M4B (con capitoli)",
        "Conversione da PDF a audiolibro MP3/M4B (con capitoli)",
        "Conversione da TXT a audiolibro MP3/M4B",
        "Oltre 400 voci neurali AI (Microsoft Edge TTS)",
        "Supporto per oltre 50 lingue",
        "Selezione e anteprima dei capitoli",
        "Generazione di feed RSS per podcast",
        "Notifica via email per conversioni lunghe",
        "Elaborazione batch",
        "Nessuna registrazione richiesta",
        "Nessun limite di utilizzo",
        "Elaborazione basata su browser",
        "Supporto per l'accessibilità (utenti ipovedenti e dislessici)"
    ],
    "en": [
        "EPUB to MP3/M4B audiobook conversion (with chapters)",
        "PDF to MP3/M4B audiobook conversion (with chapters)",
        "TXT to MP3/M4B audiobook conversion",
        "400+ neural AI voices (Microsoft Edge TTS)",
        "50+ languages supported",
        "Chapter selection and preview",
        "Podcast RSS feed generation",
        "Email notification for long conversions",
        "Batch processing",
        "No registration required",
        "No usage limits",
        "Browser-based processing",
        "Accessibility support for visually impaired and dyslexic users"
    ],
    "fr": [
        "Conversion d'EPUB en livre audio MP3/M4B (avec chapitres)",
        "Conversion de PDF en livre audio MP3/M4B (avec chapitres)",
        "Conversion de TXT en livre audio MP3/M4B",
        "Plus de 400 voix IA neuronales (Microsoft Edge TTS)",
        "Plus de 50 langues supportées",
        "Sélection et aperçu des chapitres",
        "Génération de flux RSS podcast",
        "Notification par e-mail pour les conversions longues",
        "Traitement par lots",
        "Aucune inscription requise",
        "Aucune limite d'utilisation",
        "Traitement via le navigateur",
        "Support d'accessibilité pour les malvoyants et les dyslexiques"
    ],
    "es": [
        "Conversión de EPUB a audiolibro MP3/M4B (con capítulos)",
        "Conversión de PDF a audiolibro MP3/M4B (con capítulos)",
        "Conversión de TXT a audiolibro MP3/M4B",
        "Más de 400 voces neuronales de IA (Microsoft Edge TTS)",
        "Más de 50 idiomas compatibles",
        "Selección de capítulos y vista previa",
        "Generación de feed RSS de Podcast",
        "Notificación por correo electrónico para conversiones largas",
        "Procesamiento por lotes",
        "No se requiere registro",
        "Sin límites de uso",
        "Procesamiento basado en el navegador",
        "Soporte de accesibilidad para usuarios con discapacidad visual y dislexia"
    ],
    "de": [
        "EPUB-zu-MP3/M4B-Hörbuch-Konvertierung (mit Kapiteln)",
        "PDF-zu-MP3/M4B-Hörbuch-Konvertierung (mit Kapiteln)",
        "TXT-zu-MP3/M4B-Hörbuch-Konvertierung",
        "400+ neuronale KI-Stimmen (Microsoft Edge TTS)",
        "50+ unterstützte Sprachen",
        "Kapitelauswahl und Vorschau",
        "Podcast RSS-Feed Generierung",
        "E-Mail-Benachrichtigung bei langen Konvertierungen",
        "Stapelverarbeitung",
        "Keine Registrierung erforderlich",
        "Keine Nutzungsbeschränkungen",
        "Browser-basierte Verarbeitung",
        "Barrierefreiheitsunterstützung für sehbehinderte und legasthene Nutzer"
    ],
    "zh": [
        "EPUB 转 MP3/M4B 有声书转换（含章节）",
        "PDF 转 MP3/M4B 有声书转换（含章节）",
        "TXT 转 MP3/M4B 有声书转换",
        "400+ 神经网络 AI 语音 (Microsoft Edge TTS)",
        "支持 50 多种语言",
        "章节选择和预览功能",
        "生成播客 RSS 订阅源",
        "长时转换邮件通知",
        "批量处理",
        "无需注册",
        "无使用限制",
        "基于浏览器的处理",
        "为视障人士和阅读障碍用户提供辅助功能支持"
    ],
    "hi": [
        "EPUB से MP3/M4B ऑडियोबुक रूपांतरण (अध्यायों के साथ)",
        "PDF से MP3/M4B ऑडियोबुक रूपांतरण (अध्यायों के साथ)",
        "TXT से MP3/M4B ऑडियोबुक रूपांतरण",
        "400+ न्यूरल AI आवाज़ें (Microsoft Edge TTS)",
        "50+ भाषाओं का समर्थन",
        "अध्याय चयन और पूर्वावलोकन",
        "पॉडकास्ट RSS फ़ीड जनरेशन",
        "लंबे रूपांतरणों के लिए ईमेल सूचना",
        "बैच प्रोसेसिंग",
        "किसी पंजीकरण की आवश्यकता नहीं",
        "उपयोग की कोई सीमा नहीं",
        "ब्राउज़र-आधारित प्रोसेसिंग",
        "दृष्टिबाधित और डिस्लेक्सिक उपयोगकर्ताओं के लिए अभिगम्यता समर्थन"
    ],
}


def _build_seo_block(lang: str) -> tuple[str, str, str]:
    """Genera il contenuto HTML + JSON-LD per una singola lingua.

    Returns:
        (article_html, faq_ld_json, howto_ld_json)
    """
    c = _CONTENT.get(lang, _CONTENT["en"])

    # Key Takeaways box HTML
    kt = c.get("key_takeaways", {})
    kt_items_html = ""
    if kt:
        for item in kt.get("items", []):
            kt_items_html += f"            <li>{item}</li>\n"
        kt_box_html = f"""
        <div class="key-takeaways">
            <h3>{escape(kt.get("title", ""))}</h3>
            <ul>
{kt_items_html}            </ul>
        </div>"""
    else:
        kt_box_html = ""

    # Features <li> items
    features_li = "\n".join(
        f"            <li>{escape(f)}</li>" for f in c["features"]
    )

    # FAQ <details> items + JSON-LD data
    faqs_html = ""
    faq_ld_items = []
    for q, a in c["faqs"]:
        faqs_html += (
            f'            <details class="seo-section"><summary>{escape(q)}</summary>\n'
            f'                <p>{_linkify(escape(a))}</p>\n'
            f'            </details>\n'
        )
        faq_ld_items.append({
            "@type": "Question",
            "name": q,
            "acceptedAnswer": {"@type": "Answer", "text": a},
        })

    faq_ld_json = json.dumps(
        {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": faq_ld_items},
        ensure_ascii=False,
    )

    # HowTo JSON-LD
    steps = _HOWTO_STEPS.get(lang, _HOWTO_STEPS["en"])
    howto_ld_json = json.dumps({
        "@context": "https://schema.org",
        "@type": "HowTo",
        "name": escape(c["features_heading"]),
        "description": escape(c["direct_answer"]),
        "step": [
            {
                "@type": "HowToStep",
                "name": name,
                "text": text,
            }
            for name, text in steps
        ],
    }, ensure_ascii=False)

    # Voice/language table
    headers = _TABLE_HEADERS.get(lang, _TABLE_HEADERS["en"])
    table_rows = ""
    for _lc, labels, count in _VOICE_TABLE:
        label = labels.get(lang, labels["en"])
        table_rows += (
            f'            <tr><td>{escape(label)}</td>'
            f'<td>{escape(count)}</td>'
            f'<td>Microsoft Edge TTS (Neural)</td></tr>\n'
        )

    article_html = f"""
        <div class="seo-summary">
            {escape(c["direct_answer"])}
        </div>

        {kt_box_html}

        <div class="seo-section" style="border-bottom:1px solid var(--brd,#d5d0c8); padding:0.8rem 0">
            <h2 style="font-size:1.25rem; color:var(--tx,#2c2a26); font-weight:600; margin-bottom:0.5rem">{escape(c["heading"])}</h2>
            <p style="margin-left:0.5rem">{escape(c["text"])}</p>
        </div>

        <details class="seo-section">
            <summary><h3>{escape(c["audience_heading"])}</h3></summary>
            <p>{escape(c["audience"])}</p>
        </details>

        <details class="seo-section">
            <summary><h3>{escape(c["table_heading"])}</h3></summary>
            <table>
                <thead><tr><th>{escape(headers[0])}</th><th>{escape(headers[1])}</th><th>{escape(headers[2])}</th></tr></thead>
                <tbody>
{table_rows}                </tbody>
            </table>
        </details>

        <details class="seo-section">
            <summary><h3>{escape(c["features_heading"])}</h3></summary>
            <ol>
{features_li}
            </ol>
        </details>

        <details class="seo-section">
            <summary><h3>{escape(c["faq_heading"])}</h3></summary>
            <div>
{faqs_html}            </div>
        </details>

        <details class="seo-section">
            <summary><strong>{escape(c["privacy_heading"])}</strong></summary>
            <div class="seo-privacy-body">
                {escape(c["privacy"])}
            </div>
        </details>

        <details class="seo-section">
            <summary><strong>{escape(c.get("accessibility_heading", "Accessibility & Inclusion"))}</strong></summary>
            <div class="seo-privacy-body">
                {escape(c.get("accessibility", ""))}
            </div>
        </details>

        <details class="seo-section">
            <summary><h3>{escape(c.get("guides_heading", "Free Guides"))}</h3></summary>
            <div>
                {c.get("guides_html", "")}
            </div>
        </details>

        <div class="seo-updated">
            <time datetime="{datetime.now().strftime('%Y-%m')}">{escape(c["updated_label"])}: {get_formatted_date()}</time>
        </div>"""

    return article_html, faq_ld_json, howto_ld_json


_ALL_LANGS = list(_CONTENT.keys())


def build_seo_content_html(initial_lang: str) -> str:
    """Genera il blocco HTML SEO con tutte le lingue, mostrando solo quella iniziale.

    Ogni lingua è racchiusa in un <article data-seo-lang="xx"> che viene
    mostrato/nascosto via CSS inline + la funzione JS switchSeoLang().

    I JSON-LD (FAQPage + HowTo) vengono emessi solo per la lingua iniziale
    (quelli attivi per i crawler alla prima visita); il JS li aggiorna al
    cambio lingua.

    Questo blocco viene iniettato server-side nel body prima di </body>.
    I crawler lo vedono immediatamente senza eseguire JavaScript.
    """

    # CSS (emesso una sola volta)
    css = """
<style>
#seoContent { max-width:720px; margin:2.5rem auto 1rem; padding:0 1.5rem;
  font-family:'DM Sans',system-ui,sans-serif; font-size:0.92rem; line-height:1.7; color:var(--txd,#6b6760) }
#seoContent .seo-summary { background:var(--srf,#fff); border:1px solid var(--brd,#d5d0c8);
  border-radius:8px; padding:1rem 1.2rem; margin-bottom:1.2rem; font-weight:500; color:var(--tx,#2c2a26); line-height:1.6 }
/* ── Key Takeaways box ── */
#seoContent .key-takeaways { background:linear-gradient(135deg,var(--srf,#fff) 0%,#fef9f3 100%);
  border:1.5px solid var(--ac,#c47a2a); border-radius:10px; padding:1rem 1.2rem; margin-bottom:1.2rem;
  box-shadow:0 2px 12px rgba(196,122,42,.12) }
#seoContent .key-takeaways h3 { font-size:1rem; color:var(--ac,#c47a2a); margin:0 0 0.7rem 0; font-weight:700;
  display:flex; align-items:center; gap:0.4rem }
#seoContent .key-takeaways h3::before { content:'✓'; font-size:1rem; font-weight:700 }
#seoContent .key-takeaways ul { margin:0; padding:0 0 0 1.2rem; list-style:none }
#seoContent .key-takeaways li { margin-bottom:0.4rem; color:var(--tx,#2c2a26); line-height:1.5;
  padding-left:0.2rem }
#seoContent .key-takeaways li::marker { color:var(--ac,#c47a2a) }
/* ── Collapsible sections (details/summary) ── */
#seoContent .seo-section { margin-bottom:0.25rem; border-bottom:1px solid var(--brd,#d5d0c8);
  padding:0.4rem 0 }
#seoContent .seo-section > summary { cursor:pointer; list-style:none; display:flex; align-items:center; gap:0.5rem }
#seoContent .seo-section > summary::-webkit-details-marker { display:none }
#seoContent .seo-section > summary::before { content:'\\25B6'; font-size:0.6rem; color:var(--ac,#c47a2a);
  transition:transform 0.2s; flex-shrink:0 }
#seoContent .seo-section[open] > summary::before { transform:rotate(90deg) }
#seoContent .seo-section > summary:hover { color:var(--ac,#c47a2a) }
#seoContent .seo-section > summary h2,
#seoContent .seo-section > summary h3,
#seoContent .seo-section > summary strong { margin:0; display:inline }
#seoContent .seo-section h2 { font-size:1.25rem; color:var(--tx,#2c2a26); font-weight:600 }
#seoContent .seo-section h3 { font-size:1.1rem; color:var(--tx,#2c2a26); font-weight:600 }
#seoContent .seo-section > summary strong { font-size:1rem; color:var(--tx,#2c2a26) }
/* ── Inner content of collapsible sections ── */
#seoContent .seo-section p { margin:0.5rem 0 0.5rem 0.5rem }
#seoContent .seo-section ol { padding-left:1.8rem; margin:0.5rem 0 }
#seoContent .seo-section li { margin-bottom:0.3rem }
#seoContent .seo-section table { width:100%; border-collapse:collapse; margin:0.5rem 0 1rem; font-size:0.88rem }
#seoContent .seo-section th { text-align:left; padding:0.5rem 0.8rem; background:var(--srf2,#f0ede8); color:var(--tx,#2c2a26);
  font-weight:600; border-bottom:2px solid var(--brd,#d5d0c8) }
#seoContent .seo-section td { padding:0.45rem 0.8rem; border-bottom:1px solid var(--brd,#d5d0c8) }
/* ── Nested FAQ details inside a seo-section ── */
#seoContent .seo-section details { margin-bottom:0.3rem; padding:0.4rem 0; border-bottom:1px solid var(--brd,#d5d0c8) }
#seoContent .seo-section details:last-child { border-bottom:none }
#seoContent .seo-section details summary { cursor:pointer; font-weight:500; color:var(--tx,#2c2a26) }
#seoContent .seo-section details summary:hover { color:var(--ac,#c47a2a) }
#seoContent .seo-section details p { margin:0.5rem 0 0; padding-left:0.5rem }
/* ── Privacy body ── */
#seoContent .seo-privacy-body { margin:0.5rem 0 0.5rem 0.5rem; padding:0.8rem; background:var(--srf,#fff);
  border:1px solid var(--brd,#d5d0c8); border-radius:8px; font-size:0.85rem }
/* ── Updated timestamp ── */
#seoContent .seo-updated { margin-top:1rem; font-size:0.8rem; color:var(--txm,#9e9890) }
/* ── Share bar (below SEO content) ── */
#seoContent .share-icons a:hover, #seoContent .share-icons button:hover { border-color:currentColor; transform:translateY(-2px); box-shadow:0 3px 10px rgba(0,0,0,.08) }
#seoContent .share-copied.show { opacity:1!important }
</style>"""

    # Build all language blocks
    articles = []
    initial_faq_ld = ""
    initial_howto_ld = ""

    for lang in _ALL_LANGS:
        article_html, faq_ld, howto_ld = _build_seo_block(lang)
        display = "block" if lang == initial_lang else "none"
        articles.append(
            f'    <article data-seo-lang="{lang}" style="display:{display}">'
            f'{article_html}'
            f'\n    </article>'
        )
        if lang == initial_lang:
            initial_faq_ld = faq_ld
            initial_howto_ld = howto_ld

    articles_html = "\n".join(articles)

    # JS function to switch SEO content language (called from setLang)
    switch_js = """
<script>
function switchSeoLang(l){
  var sec=document.getElementById('seoContent');
  if(!sec)return;
  sec.querySelectorAll('article[data-seo-lang]').forEach(function(a){
    a.style.display=a.getAttribute('data-seo-lang')===l?'block':'none';
  });
}
</script>"""

    share_bar = """
    <div class="share-row" id="shareRow" style="margin-top:2rem;padding-top:1.2rem;border-top:1px solid var(--brd,#d5d0c8);text-align:center">
        <div class="share-label" data-t="share_label" style="font-size:.82rem;color:var(--txm,#767676);margin-bottom:10px"></div>
        <div class="share-icons" style="display:flex;justify-content:center;gap:8px;flex-wrap:wrap">
          <a id="shX" target="_blank" rel="noopener" title="X / Twitter" style="width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brd,#d5d0c8);background:var(--srf2,#f0ede8);color:#14171a;cursor:pointer;transition:all .2s;text-decoration:none;padding:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg></a>
          <a id="shFb" target="_blank" rel="noopener" title="Facebook" style="width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brd,#d5d0c8);background:var(--srf2,#f0ede8);color:#1877F2;cursor:pointer;transition:all .2s;text-decoration:none;padding:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg></a>
          <a id="shWa" target="_blank" rel="noopener" title="WhatsApp" style="width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brd,#d5d0c8);background:var(--srf2,#f0ede8);color:#25D366;cursor:pointer;transition:all .2s;text-decoration:none;padding:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg></a>
          <a id="shTg" target="_blank" rel="noopener" title="Telegram" style="width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brd,#d5d0c8);background:var(--srf2,#f0ede8);color:#26A5E4;cursor:pointer;transition:all .2s;text-decoration:none;padding:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M11.944 0A12 12 0 000 12a12 12 0 0012 12 12 12 0 0012-12A12 12 0 0012 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 01.171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.479.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg></a>
          <a id="shLi" target="_blank" rel="noopener" title="LinkedIn" style="width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brd,#d5d0c8);background:var(--srf2,#f0ede8);color:#0A66C2;cursor:pointer;transition:all .2s;text-decoration:none;padding:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg></a>
          <a id="shRd" target="_blank" rel="noopener" title="Reddit" style="width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brd,#d5d0c8);background:var(--srf2,#f0ede8);color:#FF4500;cursor:pointer;transition:all .2s;text-decoration:none;padding:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M12 0C5.373 0 0 5.373 0 12c0 5.084 3.163 9.426 7.627 11.174-.105-.949-.2-2.405.042-3.441.218-.937 1.407-5.965 1.407-5.965s-.359-.719-.359-1.782c0-1.668.967-2.914 2.171-2.914 1.023 0 1.518.769 1.518 1.69 0 1.029-.655 2.568-.994 3.995-.283 1.194.599 2.169 1.777 2.169 2.133 0 3.772-2.249 3.772-5.495 0-2.873-2.064-4.882-5.012-4.882-3.414 0-5.418 2.561-5.418 5.207 0 1.031.397 2.138.893 2.738a.36.36 0 01.083.345l-.333 1.36c-.053.22-.174.267-.402.161-1.499-.698-2.436-2.889-2.436-4.649 0-3.785 2.75-7.262 7.929-7.262 4.163 0 7.398 2.967 7.398 6.931 0 4.136-2.607 7.464-6.227 7.464-1.216 0-2.359-.631-2.75-1.378l-.748 2.853c-.271 1.043-1.002 2.35-1.492 3.146C9.57 23.812 10.763 24 12 24c6.627 0 12-5.373 12-12 0-6.628-5.373-12-12-12z"/></svg></a>
          <div class="share-copy-wrap" style="position:relative;display:inline-flex">
            <button id="shCopy" title="Copy link" style="width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brd,#d5d0c8);background:var(--srf2,#f0ede8);color:var(--txd,#6b6760);cursor:pointer;transition:all .2s;padding:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg></button>
            <span class="share-copied" id="shCopiedTip" data-t="share_copied" style="position:absolute;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%);background:var(--tx,#2c2a26);color:var(--bg,#f5f3ef);font-size:.72rem;padding:3px 8px;border-radius:4px;white-space:nowrap;pointer-events:none;opacity:0;transition:opacity .2s"></span>
          </div>
        </div>
    </div>"""

    return f"""
<!-- ═══════════════════ SEO CONTENT (server-rendered, visible to crawlers) ═══════════════════ -->
{css}
{switch_js}
<section id="seoContent">
{articles_html}
{share_bar}
</section>
<!-- ═══════════════════ /SEO CONTENT ═══════════════════ -->
"""


def get_schema_ld(lang: str) -> tuple[str, str, str]:
    """Restituisce (faq_ld_json, howto_ld_json, combined_ld_json) per la lingua data.

    combined_ld_json contiene SoftwareApplication + Organization + Review in un
    array JSON-LD (graph), iniettato nel <head>.
    """
    article_html, faq_ld_raw, howto_ld_raw = _build_seo_block(lang)

    features = _LD_FEATURES.get(lang, _LD_FEATURES["en"])
    c = _CONTENT.get(lang, _CONTENT["en"])

    base_url = "https://audiobook-maker.com"

    # ISO-8601 dateModified — refreshed at startup. Tells crawlers and AI
    # assistants when the page content was last revised, which boosts
    # freshness signals in Google AI Overview / Perplexity citations.
    iso_modified = datetime.now().strftime("%Y-%m-%d")

    # SoftwareApplication
    software_app_ld = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "Audiobook Maker",
        "alternateName": "Audiobook Maker Online",
        "url": f"{base_url}/{lang}/",
        "description": c["direct_answer"],
        "applicationCategory": "MultimediaApplication",
        "applicationSubCategory": "Text-to-Speech Converter",
        "operatingSystem": "Any (Web Browser)",
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
        "inLanguage": ["it", "en", "fr", "es", "de", "zh-Hans"],
        "featureList": features,
        "isAccessibleForFree": True,
        "screenshot": f"{base_url}/og-image.png",
        "dateModified": iso_modified,
        "author": {
            "@type": "Person",
            "name": "Giuseppe Frangiamone",
            "url": "https://github.com/gfrangiamone",
        },
        "license": "https://www.gnu.org/licenses/agpl-3.0.html",
        "sameAs": [
            "https://github.com/gfrangiamone/audiobook-maker",
            "https://alternativeto.net/software/audiobook-maker/",
        ],
    }

    # Organization
    organization_ld = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Audiobook Maker",
        "url": base_url,
        "logo": f"{base_url}/favicon-192.png",
        "description": c["direct_answer"],
        "foundingDate": "2024",
        "founder": {
            "@type": "Person",
            "name": "Giuseppe Frangiamone",
            "url": "https://github.com/gfrangiamone",
        },
        "sameAs": [
            "https://github.com/gfrangiamone/audiobook-maker",
            "https://alternativeto.net/software/audiobook-maker/",
        ],
    }

    # WebSite (Sitelinks Search Box). potentialAction points at the converter
    # itself — schema.org allows a `UseAction` to represent the primary
    # action a user takes on the page, which Google AI Overview uses to
    # surface "use" / "try" CTAs. We don't claim a SearchAction because the
    # site has no on-site search.
    website_ld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "Audiobook Maker",
        "alternateName": "Audiobook Maker Online",
        "url": base_url,
        "description": c["direct_answer"],
        "inLanguage": ["it", "en", "fr", "es", "de", "zh-Hans"],
        "publisher": {"@type": "Organization", "name": "Audiobook Maker", "url": base_url},
        "potentialAction": {
            "@type": "UseAction",
            "name": "Convert ebook to audiobook",
            "target": f"{base_url}/{lang}/",
        },
    }

    # WebPage — single canonical block for this page. Combines:
    #   • Speakable (voice-first surfaces)
    #   • Accessibility metadata (a11y rich-results)
    #   • Breadcrumb (avoids the second top-level BreadcrumbList block)
    #   • dateModified for freshness signals
    webpage_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "url": f"{base_url}/{lang}/",
        "name": c.get("heading", "Audiobook Maker"),
        "description": c["direct_answer"],
        "inLanguage": lang if lang != "zh" else "zh-Hans",
        "isPartOf": {"@type": "WebSite", "url": base_url, "name": "Audiobook Maker"},
        "primaryImageOfPage": f"{base_url}/og-image.png",
        "datePublished": "2022-06-01",
        "dateModified": iso_modified,
        "accessibilityFeature": ["displayTransformability", "audioDescription"],
        "accessMode": ["textual", "visual", "auditory"],
        "accessModeSufficient": ["auditory"],
        "breadcrumb": {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Audiobook Maker", "item": base_url},
                {"@type": "ListItem", "position": 2,
                 "name": c.get("crumb", "Online Converter"),
                 "item": f"{base_url}/{lang}/"},
            ],
        },
        "speakable": {
            "@type": "SpeakableSpecification",
            "cssSelector": ["h1", "h2", ".seo-summary"],
        },
    }

    # Inject dateModified into FAQPage + HowTo (parse the strings produced by
    # _build_seo_block, mutate, re-serialize). Cheap — these dicts are small.
    try:
        faq_obj = json.loads(faq_ld_raw)
        faq_obj["dateModified"] = iso_modified
        faq_ld = json.dumps(faq_obj, ensure_ascii=False)
    except Exception:
        faq_ld = faq_ld_raw
    try:
        howto_obj = json.loads(howto_ld_raw)
        howto_obj["dateModified"] = iso_modified
        howto_ld = json.dumps(howto_obj, ensure_ascii=False)
    except Exception:
        howto_ld = howto_ld_raw

    # Combine into a JSON-LD graph (array of objects)
    combined = [software_app_ld, organization_ld, website_ld, webpage_ld]
    combined_ld_json = json.dumps(combined, ensure_ascii=False)

    return faq_ld, howto_ld, combined_ld_json
