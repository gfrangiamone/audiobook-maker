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
            "Audiobook Maker è un convertitore gratuito da EPUB e PDF a audiolibro MP3 "
            "con oltre 400 voci AI neurali in decine di lingue (tecnologia Microsoft Edge TTS). "
            "Non richiede registrazione, non ha limiti di utilizzo e funziona interamente nel browser."
        ),
        "key_takeaways": {
            "title": "Punti Chiave",
            "items": [
                "✅ <strong>Gratis al 100%</strong> — Nessuna registrazione, nessun limite",
                "✅ <strong>400+ voci neurali AI</strong> — Microsoft Edge TTS di alta qualità",
                "✅ <strong>50+ lingue</strong> — Italiano, Inglese, Francese, Spagnolo, Tedesco, Cinese e altre",
                "✅ <strong>Nessuna installazione</strong> — Funziona direttamente nel browser",
                "✅ <strong>Podcast RSS</strong> — Genera feed per ascoltare capitoli nella tua app preferita",
                "✅ <strong>Open source</strong> — Progetto trasparente con licenza AGPL-3.0",
            ],
        },
        "heading": "Converti i tuoi Ebook EPUB e PDF in Audiolibri MP3 — Gratis Online",
        "text": (
            "Audiobook Maker è un convertitore online gratuito che trasforma i tuoi ebook EPUB e PDF "
            "in audiolibri MP3 utilizzando voci AI naturali con tecnologia neural text-to-speech "
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
            "Avvia la conversione text-to-speech con un clic e attendi l'elaborazione",
            "Per conversioni lunghe, inserisci la tua email per ricevere una notifica al termine con il link per il download — puoi chiudere il browser e tornare quando l'audiolibro è pronto",
            "Scarica l'audiolibro in formato MP3 pronto per l'ascolto su qualsiasi dispositivo",
            "Genera un feed RSS podcast per ascoltare i capitoli nella tua app preferita",
        ],
        "faq_heading": "Domande Frequenti — Convertitore EPUB/PDF Audiolibro",
        "faqs": [
            ("Come convertire un EPUB in audiolibro gratis?",
             "Carica il tuo file EPUB su Audiobook Maker, seleziona una voce AI e la lingua desiderata, "
             "poi clicca su Converti. Il convertitore text-to-speech gratuito genererà l'audiolibro "
             "in formato MP3 che potrai scaricare e ascoltare ovunque. Non serve registrazione."),
            ("Come convertire un PDF in audiolibro?",
             "Audiobook Maker supporta la conversione diretta di file PDF in audiolibri MP3. "
             "Carica il tuo PDF, scegli una voce AI, e il convertitore estrarrà il testo e lo trasformerà "
             "in audio con sintesi vocale neurale."),
            ("Quali formati di ebook sono supportati?",
             "Audiobook Maker supporta i formati EPUB, PDF e TXT. "
             "L'EPUB è il formato consigliato per risultati ottimali. "
             "Se il tuo libro è in un altro formato (MOBI, AZW), puoi convertirlo prima in EPUB "
             "usando strumenti gratuiti come Calibre."),
            ("Quante voci AI sono disponibili e in quali lingue?",
             "Audiobook Maker offre oltre 400 voci neurali AI di alta qualità basate su Microsoft Edge TTS, "
             "con supporto per decine di lingue tra cui italiano, inglese, francese, spagnolo, tedesco, "
             "cinese, portoghese, russo, giapponese, coreano, arabo, hindi e molte altre. "
             "L'interfaccia dell'app è disponibile in 6 lingue, ma il motore di sintesi vocale "
             "supporta tutte le lingue offerte dalla libreria Edge TTS. "
             "Ogni lingua dispone di voci maschili e femminili con diversi stili di narrazione."),
            ("Le voci AI sono naturali?",
             "Sì, il convertitore utilizza voci neurali TTS di alta qualità (Edge TTS) con sintesi "
             "vocale AI che produce voci naturali e piacevoli da ascoltare."),
            ("Devo installare qualcosa?",
             "No, Audiobook Maker è un convertitore online che funziona completamente nel browser. "
             "Non serve scaricare né installare alcun software."),
            ("Posso generare un podcast dai capitoli del libro?",
             "Sì, Audiobook Maker può generare un feed RSS podcast con tutti i capitoli del tuo "
             "audiolibro. Puoi copiare il link e aggiungerlo alla tua app podcast preferita per "
             "ascoltare i capitoli in streaming."),
            ("Il servizio è davvero gratuito?",
             "Sì, Audiobook Maker è completamente gratuito. Non richiede registrazione, "
             "non ha limiti di utilizzo e non inserisce pubblicità nei file audio generati. "
             "Il progetto è supportato da donazioni volontarie."),
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
        ],
        "privacy_heading": "Privacy e Sicurezza",
        "privacy": (
            "Audiobook Maker rispetta la tua privacy. I file caricati e gli audio generati "
            "vengono eliminati automaticamente al termine della sessione. Non è necessaria "
            "alcuna registrazione, non vengono raccolti dati personali e non viene utilizzato "
            "alcun sistema di tracciamento oltre alle statistiche anonime di utilizzo. "
            "Il progetto è open source con licenza AGPL-3.0."
        ),
        "updated_label": "Ultimo aggiornamento",
        "share_label": "Condividi",
        "donate_text": "Sostieni il progetto:",
        "donate_btn": "Dona con Ko-fi",
    },
    # ─── ENGLISH ────────────────────────────────────────────────────
    "en": {
        "direct_answer": (
            "Audiobook Maker is a free, no-signup EPUB and PDF to MP3 audiobook converter "
            "with 400+ neural AI voices in dozens of languages (Microsoft Edge TTS). "
            "It runs entirely in your browser with no usage limits."
        ),
        "key_takeaways": {
            "title": "Quick Summary",
            "items": [
                "✅ <strong>100% Free</strong> — No signup, no limits",
                "✅ <strong>400+ neural AI voices</strong> — High-quality Microsoft Edge TTS",
                "✅ <strong>50+ languages</strong> — English, Italian, French, Spanish, German, Chinese and more",
                "✅ <strong>No installation</strong> — Works directly in your browser",
                "✅ <strong>Podcast RSS</strong> — Generate feed to listen in your favorite app",
                "✅ <strong>Open source</strong> — Transparent project with AGPL-3.0 license",
            ],
        },
        "heading": "Convert Your EPUB and PDF Ebooks to MP3 Audiobooks — Free Online",
        "text": (
            "Audiobook Maker is a free online converter that transforms your EPUB and PDF ebooks into MP3 audiobooks "
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
            "Start the text-to-speech conversion with one click and wait for processing",
            "For long conversions, enter your email to receive a notification when the audiobook is ready with a download link — you can close the browser and come back later",
            "Download your audiobook in MP3 format ready to listen on any device",
            "Generate a podcast RSS feed to listen to chapters in your favorite app",
        ],
        "faq_heading": "Frequently Asked Questions — EPUB/PDF to Audiobook Converter",
        "faqs": [
            ("How to convert an EPUB to audiobook for free?",
             "Upload your EPUB file to Audiobook Maker, select an AI voice and your desired language, "
             "then click Convert. The free text-to-speech converter will generate the audiobook "
             "in MP3 format that you can download and listen to anywhere. No signup required."),
            ("How to convert a PDF to audiobook?",
             "Audiobook Maker supports direct PDF to audiobook conversion. "
             "Upload your PDF file, choose an AI voice, and the converter will extract the text "
             "and transform it into audio using neural text-to-speech synthesis."),
            ("What ebook formats are supported?",
             "Audiobook Maker supports EPUB, PDF, and TXT formats. "
             "EPUB is recommended for best results. "
             "If your book is in another format (MOBI, AZW), you can convert it to EPUB first "
             "using free tools like Calibre."),
            ("How many AI voices are available and in which languages?",
             "Audiobook Maker offers 400+ high-quality neural AI voices powered by Microsoft Edge TTS, "
             "supporting dozens of languages including English, Italian, French, Spanish, German, "
             "Chinese, Portuguese, Russian, Japanese, Korean, Arabic, Hindi, and many more. "
             "The app interface is available in 6 languages, but the text-to-speech engine "
             "supports all languages offered by the Edge TTS library. "
             "Each language includes male and female voices with different narration styles."),
            ("Are the AI voices natural-sounding?",
             "Yes, the converter uses high-quality neural TTS voices (Edge TTS) with AI voice synthesis "
             "that produces natural and pleasant voices."),
            ("Do I need to install anything?",
             "No, Audiobook Maker is an online converter that works entirely in your browser. "
             "No software download or installation is required."),
            ("Can I generate a podcast from the book chapters?",
             "Yes, Audiobook Maker can generate a podcast RSS feed with all your audiobook chapters. "
             "Copy the link and add it to your favorite podcast app to stream chapters."),
            ("Is the service really free?",
             "Yes, Audiobook Maker is completely free. No registration required, "
             "no usage limits, and no ads inserted in the generated audio files. "
             "The project is supported by voluntary donations."),
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
        ],
        "privacy_heading": "Privacy & Security",
        "privacy": (
            "Audiobook Maker respects your privacy. Uploaded files and generated audio "
            "are automatically deleted at the end of each session. No registration is required, "
            "no personal data is collected, and no tracking is used beyond anonymous usage statistics. "
            "The project is open source under the AGPL-3.0 license."
        ),
        "updated_label": "Last updated",
        "share_label": "Share",
        "donate_text": "Support the project:",
        "donate_btn": "Donate with Ko-fi",
    },
    # ─── FRANÇAIS ───────────────────────────────────────────────────
    "fr": {
        "direct_answer": (
            "Audiobook Maker est un convertisseur gratuit d'EPUB et PDF en livres audio MP3 "
            "avec plus de 400 voix IA neuronales dans des dizaines de langues (Microsoft Edge TTS). "
            "Sans inscription, sans limites, directement dans votre navigateur."
        ),
        "key_takeaways": {
            "title": "Points Clés",
            "items": [
                "✅ <strong>100% Gratuit</strong> — Sans inscription, sans limites",
                "✅ <strong>400+ voix IA neuronales</strong> — Microsoft Edge TTS de haute qualité",
                "✅ <strong>50+ langues</strong> — Français, Anglais, Italien, Espagnol, Allemand, Chinois et plus",
                "✅ <strong>Sans installation</strong> — Fonctionne directement dans votre navigateur",
                "✅ <strong>Podcast RSS</strong> — Générez un flux pour écouter dans votre app préférée",
                "✅ <strong>Open source</strong> — Projet transparent sous licence AGPL-3.0",
            ],
        },
        "heading": "Convertissez vos Ebooks EPUB et PDF en Livres Audio MP3 — Gratuit en Ligne",
        "text": (
            "Audiobook Maker est un convertisseur en ligne gratuit qui transforme vos ebooks EPUB et PDF en livres "
            "audio MP3 en utilisant des voix IA naturelles (technologie neuronale Microsoft Edge TTS). "
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
            "Lancez la conversion text-to-speech en un clic et attendez le traitement",
            "Pour les conversions longues, entrez votre email pour recevoir une notification avec un lien de téléchargement quand le livre audio est prêt — vous pouvez fermer le navigateur et revenir plus tard",
            "Téléchargez votre livre audio au format MP3 prêt à écouter sur tout appareil",
            "Générez un flux RSS podcast pour écouter les chapitres dans votre app préférée",
        ],
        "faq_heading": "Questions Fréquentes — Convertisseur EPUB/PDF Livre Audio",
        "faqs": [
            ("Comment convertir un EPUB en livre audio gratuitement ?",
             "Téléchargez votre fichier EPUB sur Audiobook Maker, sélectionnez une voix IA et la langue, "
             "puis cliquez sur Convertir. Le convertisseur text-to-speech gratuit générera le livre audio "
             "au format MP3 que vous pourrez télécharger et écouter partout. Aucune inscription requise."),
            ("Comment convertir un PDF en livre audio ?",
             "Audiobook Maker prend en charge la conversion directe de PDF en livres audio MP3. "
             "Téléchargez votre fichier PDF, choisissez une voix IA, et le convertisseur extraira le texte "
             "pour le transformer en audio avec synthèse vocale neuronale."),
            ("Quels formats d'ebook sont supportés ?",
             "Audiobook Maker prend en charge les formats EPUB, PDF et TXT. "
             "L'EPUB est recommandé pour de meilleurs résultats. "
             "Vous pouvez convertir d'autres formats en EPUB avec Calibre."),
            ("Combien de voix IA sont disponibles et dans quelles langues ?",
             "Audiobook Maker propose plus de 400 voix IA neuronales de haute qualité basées sur Microsoft Edge TTS, "
             "avec prise en charge de dizaines de langues dont le français, l'anglais, l'italien, l'espagnol, "
             "l'allemand, le chinois, le portugais, le russe, le japonais, le coréen, l'arabe, le hindi et bien d'autres. "
             "L'interface de l'application est disponible en 6 langues, mais le moteur de synthèse vocale "
             "prend en charge toutes les langues offertes par la bibliothèque Edge TTS."),
            ("Les voix IA sont-elles naturelles ?",
             "Oui, le convertisseur utilise des voix neuronales TTS de haute qualité avec synthèse vocale "
             "IA qui produit des voix naturelles et agréables."),
            ("Dois-je installer quelque chose ?",
             "Non, Audiobook Maker fonctionne entièrement dans votre navigateur, sans installation."),
            ("Le service est-il vraiment gratuit ?",
             "Oui, Audiobook Maker est entièrement gratuit. Pas d'inscription requise, "
             "pas de limites d'utilisation et pas de publicité dans les fichiers audio générés. "
             "Le projet est soutenu par des dons volontaires."),
            ("Quels outils utiliser pour écouter un livre audio généré par Audiobook Maker ?",
             "Les fichiers MP3 générés par Audiobook Maker peuvent être lus avec n'importe quel lecteur audio. "
             "Pour une expérience optimale sur Android, nous recommandons Smart AudioBook Player, "
             "une application conçue spécialement pour les livres audio qui mémorise votre position d'écoute, "
             "permet de régler la vitesse et organise automatiquement les chapitres. "
             "Sur iPhone, vous pouvez utiliser l'application Livres d'Apple ou tout lecteur MP3. "
             "Vous pouvez aussi utiliser le flux RSS podcast généré par l'app pour écouter "
             "les chapitres directement dans votre application podcast préférée."),
        ],
        "privacy_heading": "Confidentialité et Sécurité",
        "privacy": (
            "Audiobook Maker respecte votre vie privée. Les fichiers téléchargés et les audios générés "
            "sont automatiquement supprimés à la fin de chaque session. Aucune inscription requise, "
            "aucune donnée personnelle collectée. Projet open source sous licence AGPL-3.0."
        ),
        "updated_label": "Dernière mise à jour",
        "share_label": "Partager",
        "donate_text": "Soutenez le projet:",
        "donate_btn": "Donner avec Ko-fi",
    },
    # ─── ESPAÑOL ────────────────────────────────────────────────────
    "es": {
        "direct_answer": (
            "Audiobook Maker es un convertidor gratuito de EPUB y PDF a audiolibro MP3 "
            "con más de 400 voces IA neuronales en decenas de idiomas (Microsoft Edge TTS). "
            "Sin registro, sin límites, directamente en tu navegador."
        ),
        "key_takeaways": {
            "title": "Puntos Clave",
            "items": [
                "✅ <strong>100% Gratis</strong> — Sin registro, sin límites",
                "✅ <strong>400+ voces IA neuronales</strong> — Microsoft Edge TTS de alta calidad",
                "✅ <strong>50+ idiomas</strong> — Español, Inglés, Italiano, Francés, Alemán, Chino y más",
                "✅ <strong>Sin instalación</strong> — Funciona directamente en tu navegador",
                "✅ <strong>Podcast RSS</strong> — Genera feed para escuchar en tu app favorita",
                "✅ <strong>Open source</strong> — Proyecto transparente con licencia AGPL-3.0",
            ],
        },
        "heading": "Convierte tus Ebooks EPUB y PDF en Audiolibros MP3 — Gratis Online",
        "text": (
            "Audiobook Maker es un convertidor en línea gratuito que transforma tus ebooks EPUB y PDF en "
            "audiolibros MP3 utilizando voces IA naturales (tecnología neuronal Microsoft Edge TTS). "
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
            "Inicia la conversión text-to-speech con un clic y espera el procesamiento",
            "Para conversiones largas, introduce tu email para recibir una notificación con un enlace de descarga cuando el audiolibro esté listo — puedes cerrar el navegador y volver más tarde",
            "Descarga tu audiolibro en formato MP3 listo para escuchar en cualquier dispositivo",
            "Genera un feed RSS podcast para escuchar los capítulos en tu app favorita",
        ],
        "faq_heading": "Preguntas Frecuentes — Convertidor EPUB/PDF a Audiolibro",
        "faqs": [
            ("¿Cómo convertir un EPUB a audiolibro gratis?",
             "Sube tu archivo EPUB a Audiobook Maker, selecciona una voz IA y el idioma deseado, "
             "luego haz clic en Convertir. El convertidor text-to-speech gratuito generará el audiolibro "
             "en formato MP3 que podrás descargar y escuchar en cualquier lugar. Sin registro."),
            ("¿Cómo convertir un PDF a audiolibro?",
             "Audiobook Maker admite la conversión directa de PDF a audiolibros MP3. "
             "Sube tu archivo PDF, elige una voz IA, y el convertidor extraerá el texto "
             "para transformarlo en audio con síntesis de voz neuronal."),
            ("¿Qué formatos de ebook son compatibles?",
             "Audiobook Maker admite los formatos EPUB, PDF y TXT. "
             "Se recomienda EPUB para mejores resultados. "
             "Puedes convertir otros formatos a EPUB usando herramientas gratuitas como Calibre."),
            ("¿Cuántas voces IA hay disponibles y en qué idiomas?",
             "Audiobook Maker ofrece más de 400 voces IA neuronales de alta calidad basadas en Microsoft Edge TTS, "
             "con soporte para decenas de idiomas incluyendo español, inglés, italiano, francés, alemán, "
             "chino, portugués, ruso, japonés, coreano, árabe, hindi y muchos más. "
             "La interfaz de la app está disponible en 6 idiomas, pero el motor de síntesis de voz "
             "soporta todos los idiomas ofrecidos por la librería Edge TTS."),
            ("¿Las voces IA suenan naturales?",
             "Sí, el convertidor utiliza voces neuronales TTS de alta calidad con síntesis de voz IA "
             "que produce voces naturales y agradables."),
            ("¿Necesito instalar algo?",
             "No, Audiobook Maker funciona completamente en tu navegador, sin instalación."),
            ("¿El servicio es realmente gratuito?",
             "Sí, Audiobook Maker es completamente gratuito. Sin registro, "
             "sin límites de uso y sin publicidad en los archivos de audio generados. "
             "El proyecto se sostiene con donaciones voluntarias."),
            ("¿Qué herramientas puedo usar para escuchar un audiolibro generado por Audiobook Maker?",
             "Los archivos MP3 generados por Audiobook Maker se pueden reproducir con cualquier reproductor de audio. "
             "Para la mejor experiencia en Android, recomendamos Smart AudioBook Player, "
             "una app diseñada específicamente para audiolibros que recuerda tu posición de escucha, "
             "permite ajustar la velocidad y organiza automáticamente los capítulos. "
             "En iPhone, puedes usar la app Libros de Apple o cualquier reproductor MP3. "
             "También puedes usar el feed RSS podcast generado por la app para escuchar "
             "los capítulos directamente en tu app de podcast favorita."),
        ],
        "privacy_heading": "Privacidad y Seguridad",
        "privacy": (
            "Audiobook Maker respeta tu privacidad. Los archivos subidos y los audios generados "
            "se eliminan automáticamente al final de cada sesión. Sin registro, "
            "sin recopilación de datos personales. Proyecto open source bajo licencia AGPL-3.0."
        ),
        "updated_label": "Última actualización",
        "share_label": "Compartir",
        "donate_text": "Apoya el proyecto:",
        "donate_btn": "Donar con Ko-fi",
    },
    # ─── DEUTSCH ────────────────────────────────────────────────────
    "de": {
        "direct_answer": (
            "Audiobook Maker ist ein kostenloser EPUB- und PDF-zu-MP3-Hörbuch-Konverter "
            "mit über 400 neuronalen KI-Stimmen in Dutzenden von Sprachen (Microsoft Edge TTS). "
            "Ohne Registrierung, ohne Limits, direkt im Browser."
        ),
        "key_takeaways": {
            "title": "Kurzübersicht",
            "items": [
                "✅ <strong>100% Kostenlos</strong> — Keine Anmeldung, keine Limits",
                "✅ <strong>400+ neuronale KI-Stimmen</strong> — Microsoft Edge TTS hoher Qualität",
                "✅ <strong>50+ Sprachen</strong> — Deutsch, Englisch, Italienisch, Französisch, Spanisch, Chinesisch und mehr",
                "✅ <strong>Keine Installation</strong> — Funktioniert direkt in Ihrem Browser",
                "✅ <strong>Podcast RSS</strong> — Feed generieren für Ihre Lieblings-App",
                "✅ <strong>Open source</strong> — Transparentes Projekt mit AGPL-3.0 Lizenz",
            ],
        },
        "heading": "Konvertieren Sie Ihre EPUB- und PDF-E-Books in MP3-Hörbücher — Kostenlos Online",
        "text": (
            "Audiobook Maker ist ein kostenloser Online-Konverter, der Ihre EPUB- und PDF-E-Books in MP3-Hörbücher "
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
            "Starten Sie die Text-to-Speech-Konvertierung mit einem Klick",
            "Bei langen Konvertierungen geben Sie Ihre E-Mail ein, um eine Benachrichtigung mit Download-Link zu erhalten, wenn das Hörbuch fertig ist — Sie können den Browser schließen und später zurückkehren",
            "Laden Sie Ihr Hörbuch im MP3-Format herunter, bereit zum Anhören auf jedem Gerät",
            "Erstellen Sie einen Podcast-RSS-Feed, um Kapitel in Ihrer Lieblings-App zu hören",
        ],
        "faq_heading": "Häufig Gestellte Fragen — EPUB/PDF-zu-Hörbuch-Konverter",
        "faqs": [
            ("Wie wandelt man ein EPUB kostenlos in ein Hörbuch um?",
             "Laden Sie Ihre EPUB-Datei auf Audiobook Maker hoch, wählen Sie eine KI-Stimme und die "
             "gewünschte Sprache, dann klicken Sie auf Konvertieren. Der kostenlose Text-to-Speech-Konverter "
             "erstellt das Hörbuch im MP3-Format zum Herunterladen. Keine Registrierung nötig."),
            ("Wie konvertiert man ein PDF in ein Hörbuch?",
             "Audiobook Maker unterstützt die direkte Konvertierung von PDF zu MP3-Hörbüchern. "
             "Laden Sie Ihre PDF-Datei hoch, wählen Sie eine KI-Stimme, und der Konverter extrahiert "
             "den Text und wandelt ihn mit neuronaler Sprachsynthese in Audio um."),
            ("Welche E-Book-Formate werden unterstützt?",
             "Audiobook Maker unterstützt EPUB-, PDF- und TXT-Formate. "
             "EPUB wird für beste Ergebnisse empfohlen. "
             "Andere Formate können Sie mit Calibre zuerst in EPUB konvertieren."),
            ("Wie viele KI-Stimmen sind verfügbar und in welchen Sprachen?",
             "Audiobook Maker bietet über 400 hochwertige neuronale KI-Stimmen basierend auf Microsoft Edge TTS, "
             "mit Unterstützung für Dutzende von Sprachen darunter Deutsch, Englisch, Italienisch, Französisch, "
             "Spanisch, Chinesisch, Portugiesisch, Russisch, Japanisch, Koreanisch, Arabisch, Hindi und viele mehr. "
             "Die App-Oberfläche ist in 6 Sprachen verfügbar, aber die Sprachsynthese-Engine "
             "unterstützt alle Sprachen der Edge TTS-Bibliothek."),
            ("Klingen die KI-Stimmen natürlich?",
             "Ja, der Konverter nutzt hochwertige neuronale TTS-Stimmen mit KI-Sprachsynthese, "
             "die natürliche Stimmen erzeugt."),
            ("Muss ich etwas installieren?",
             "Nein, Audiobook Maker funktioniert vollständig in Ihrem Browser, ohne Installation."),
            ("Ist der Dienst wirklich kostenlos?",
             "Ja, Audiobook Maker ist völlig kostenlos. Keine Registrierung erforderlich, "
             "keine Nutzungsbeschränkungen und keine Werbung in den erzeugten Audiodateien. "
             "Das Projekt wird durch freiwillige Spenden unterstützt."),
            ("Welche Tools kann ich verwenden, um ein von Audiobook Maker erstelltes Hörbuch zu hören?",
             "Die von Audiobook Maker erzeugten MP3-Dateien können mit jedem Audioplayer abgespielt werden. "
             "Für das beste Erlebnis auf Android empfehlen wir Smart AudioBook Player, "
             "eine App speziell für Hörbücher, die sich Ihre Hörposition merkt, "
             "Geschwindigkeitsanpassung unterstützt und Kapitel automatisch organisiert. "
             "Auf dem iPhone können Sie Apples Bücher-App oder jeden MP3-Player verwenden. "
             "Alternativ können Sie den von der App generierten Podcast-RSS-Feed nutzen, um "
             "Kapitel direkt in Ihrer Lieblings-Podcast-App zu hören."),
        ],
        "privacy_heading": "Datenschutz und Sicherheit",
        "privacy": (
            "Audiobook Maker respektiert Ihre Privatsphäre. Hochgeladene Dateien und erzeugte Audios "
            "werden am Ende jeder Sitzung automatisch gelöscht. Keine Registrierung erforderlich, "
            "keine personenbezogenen Daten werden erhoben. Open-Source-Projekt unter AGPL-3.0-Lizenz."
        ),
        "updated_label": "Zuletzt aktualisiert",
        "share_label": "Teilen",
        "donate_text": "Projekt unterstützen:",
        "donate_btn": "Mit Ko-fi spenden",
    },
    # ─── 中文 ───────────────────────────────────────────────────────
    "zh": {
        "direct_answer": (
            "Audiobook Maker是一款免费的EPUB和PDF转MP3有声书转换器，"
            "拥有超过400种神经网络AI语音，支持数十种语言（Microsoft Edge TTS）。"
            "无需注册，无使用限制，直接在浏览器中运行。"
        ),
        "key_takeaways": {
            "title": "快速总结",
            "items": [
                "✅ <strong>100% 免费</strong> — 无需注册，无使用限制",
                "✅ <strong>400+ 神经网络AI语音</strong> — 高质量 Microsoft Edge TTS",
                "✅ <strong>50+ 语言</strong> — 中文、英语、意大利语、法语、西班牙语、德语等",
                "✅ <strong>无需安装</strong> — 直接在浏览器中运行",
                "✅ <strong>播客 RSS</strong> — 生成订阅源在您喜爱的应用中收听",
                "✅ <strong>开源</strong> — 透明项目，采用 AGPL-3.0 许可证",
            ],
        },
        "heading": "免费在线将EPUB和PDF电子书转换为MP3有声书",
        "text": (
            "Audiobook Maker是一款免费在线转换器，利用神经网络AI文字转语音技术"
            "（Microsoft Edge TTS），将您的EPUB和PDF电子书转换为MP3有声书。"
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
            "一键启动文字转语音转换，等待处理完成",
            "对于较长的转换，输入您的电子邮件以便在有声书准备就绪时收到带有下载链接的通知——您可以关闭浏览器，稍后再回来",
            "下载MP3格式的有声书，可在任何设备上收听",
            "生成播客RSS订阅源，在您喜爱的应用中收听章节",
        ],
        "faq_heading": "常见问题 — EPUB/PDF转有声书转换器",
        "faqs": [
            ("如何免费将EPUB转换为有声书？",
             "将EPUB文件上传到Audiobook Maker，选择AI语音和所需语言，"
             "然后点击转换。免费文字转语音转换器将生成MP3格式的有声书，可随时随地收听。无需注册。"),
            ("如何将PDF转换为有声书？",
             "Audiobook Maker支持PDF直接转换为MP3有声书。"
             "上传PDF文件，选择AI语音，转换器将提取文本并使用神经网络语音合成技术将其转换为音频。"),
            ("支持哪些电子书格式？",
             "Audiobook Maker支持EPUB、PDF和TXT格式。"
             "推荐使用EPUB以获得最佳效果。"
             "其他格式可以先使用Calibre等免费工具转换为EPUB。"),
            ("有多少种AI语音可用？支持哪些语言？",
             "Audiobook Maker提供超过400种高质量神经网络AI语音（基于Microsoft Edge TTS），"
             "支持数十种语言，包括中文、英语、意大利语、法语、西班牙语、德语、"
             "葡萄牙语、俄语、日语、韩语、阿拉伯语、印地语等。"
             "应用界面提供6种语言，但语音合成引擎支持Edge TTS库提供的所有语言。"),
            ("AI语音听起来自然吗？",
             "是的，转换器使用高质量的神经网络TTS语音和AI语音合成，"
             "能够产生自然悦耳的声音。"),
            ("需要安装什么吗？",
             "不需要，Audiobook Maker完全在浏览器中运行，无需下载或安装。"),
            ("服务真的免费吗？",
             "是的，Audiobook Maker完全免费。无需注册，无使用限制，生成的音频文件中也没有广告。"
             "项目由自愿捐赠支持。"),
            ("可以用什么工具收听Audiobook Maker生成的有声书？",
             "Audiobook Maker生成的MP3文件可以用任何音频播放器播放。"
             "在Android上，我们推荐Smart AudioBook Player，"
             "这是一款专为有声书设计的应用，能记住您的收听位置、"
             "支持速度调节并自动整理章节。"
             "在iPhone上，您可以使用Apple图书应用或任何MP3播放器。"
             "您也可以使用应用生成的播客RSS订阅源，"
             "直接在您喜爱的播客应用中收听章节。"),
        ],
        "privacy_heading": "隐私与安全",
        "privacy": (
            "Audiobook Maker尊重您的隐私。上传的文件和生成的音频在每次会话结束时自动删除。"
            "无需注册，不收集个人数据。项目以AGPL-3.0许可证开源。"
        ),
        "updated_label": "最后更新",
        "share_label": "分享",
        "donate_text": "支持项目：",
        "donate_btn": "用 Ko-fi 捐赠",
    },
}


# ─── Tabella comparativa voci/lingue (condivisa, labels per lingua) ───

_VOICE_TABLE = [
    # (language_code, label_per_lang, approx_voice_count)
    ("en", {"it": "Inglese", "en": "English", "fr": "Anglais", "es": "Inglés", "de": "Englisch", "zh": "英语"}, "14+"),
    ("it", {"it": "Italiano", "en": "Italian", "fr": "Italien", "es": "Italiano", "de": "Italienisch", "zh": "意大利语"}, "8+"),
    ("fr", {"it": "Francese", "en": "French", "fr": "Français", "es": "Francés", "de": "Französisch", "zh": "法语"}, "8+"),
    ("es", {"it": "Spagnolo", "en": "Spanish", "fr": "Espagnol", "es": "Español", "de": "Spanisch", "zh": "西班牙语"}, "7+"),
    ("de", {"it": "Tedesco", "en": "German", "fr": "Allemand", "es": "Alemán", "de": "Deutsch", "zh": "德语"}, "7+"),
    ("zh", {"it": "Cinese", "en": "Chinese", "fr": "Chinois", "es": "Chino", "de": "Chinesisch", "zh": "中文"}, "10+"),
    ("other", {
        "it": "Altre lingue (portoghese, russo, giapponese, coreano, arabo, hindi, ecc.)",
        "en": "Other languages (Portuguese, Russian, Japanese, Korean, Arabic, Hindi, etc.)",
        "fr": "Autres langues (portugais, russe, japonais, coréen, arabe, hindi, etc.)",
        "es": "Otros idiomas (portugués, ruso, japonés, coreano, árabe, hindi, etc.)",
        "de": "Weitere Sprachen (Portugiesisch, Russisch, Japanisch, Koreanisch, Arabisch, Hindi, usw.)",
        "zh": "其他语言（葡萄牙语、俄语、日语、韩语、阿拉伯语、印地语等）",
    }, "350+"),
]

_TABLE_HEADERS = {
    "it": ("Lingua", "Voci AI", "Tecnologia"),
    "en": ("Language", "AI Voices", "Technology"),
    "fr": ("Langue", "Voix IA", "Technologie"),
    "es": ("Idioma", "Voces IA", "Tecnología"),
    "de": ("Sprache", "KI-Stimmen", "Technologie"),
    "zh": ("语言", "AI语音", "技术"),
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
            f'            <details><summary>{escape(q)}</summary>\n'
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
        {kt_box_html}

        <details class="seo-section">
            <summary><h2>{escape(c["heading"])}</h2></summary>
            <p>{escape(c["text"])}</p>
        </details>

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

        <div class="seo-share-donate">
            <div class="share-btns">
                <span class="share-label">{escape(c.get("share_label", "Condividi"))}</span>
                <a href="https://twitter.com/intent/tweet?text=Audiobook+Maker+-+Converti+EPUB+e+PDF+in+audiolibri+MP3+gratis&url=https://audiobookmaker.app" target="_blank" rel="noopener" class="share-btn share-twitter">𝕏</a>
                <a href="https://www.facebook.com/sharer/sharer.php?u=https://audiobookmaker.app" target="_blank" rel="noopener" class="share-btn share-facebook">f</a>
                <a href="https://www.linkedin.com/shareArticle?mini=true&url=https://audiobookmaker.app" target="_blank" rel="noopener" class="share-btn share-linkedin">in</a>
            </div>
            <div class="donate-section">
                <span class="donate-text">{escape(c.get("donate_text", "Sostieni il progetto:"))}</span>
                <a href="https://ko-fi.com/audiobookmaker" target="_blank" rel="noopener" class="donate-btn">☕ {escape(c.get("donate_btn", "Dona con Ko-fi"))}</a>
            </div>
        </div>

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
#seoContent { max-width:800px; margin:2.5rem auto 1rem; padding:0 1.5rem;
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
/* ── Share & Donate banner ── */
#seoContent .seo-share-donate { margin:1.5rem 0; padding:1rem; background:linear-gradient(135deg,var(--srf,#fff) 0%,#fef9f3 100%);
  border:1.5px solid var(--ac,#c47a2a); border-radius:10px; display:flex; flex-wrap:wrap; gap:1rem; align-items:center; justify-content:space-between }
#seoContent .share-btns { display:flex; align-items:center; gap:0.5rem }
#seoContent .share-label { font-weight:600; color:var(--tx,#2c2a26); font-size:0.9rem }
#seoContent .share-btn { display:inline-flex; align-items:center; justify-content:center; width:32px; height:32px; border-radius:50%;
  font-weight:700; font-size:0.85rem; text-decoration:none; transition:transform 0.2s,opacity 0.2s }
#seoContent .share-btn:hover { transform:scale(1.1) }
#seoContent .share-twitter { background:#000; color:#fff }
#seoContent .share-facebook { background:#1877f2; color:#fff }
#seoContent .share-linkedin { background:#0a66c2; color:#fff }
#seoContent .donate-section { display:flex; align-items:center; gap:0.6rem; flex-wrap:wrap }
#seoContent .donate-text { font-size:0.85rem; color:var(--txd,#6b6760) }
#seoContent .donate-btn { display:inline-flex; align-items:center; gap:0.4rem; padding:0.5rem 1rem; background:var(--ac,#c47a2a);
  color:#fff; border-radius:20px; font-weight:600; font-size:0.85rem; text-decoration:none; transition:background 0.2s,transform 0.2s }
#seoContent .donate-btn:hover { background:#b36d22; transform:scale(1.03) }
@media (max-width:500px) {
  #seoContent .seo-share-donate { flex-direction:column; align-items:flex-start }
  #seoContent .donate-section { width:100% }
  #seoContent .donate-btn { width:100%; justify-content:center }
}
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

    return f"""
<!-- ═══════════════════ SEO CONTENT (server-rendered, visible to crawlers) ═══════════════════ -->
{css}
{switch_js}
<section id="seoContent">
{articles_html}
</section>
<!-- ═══════════════════ /SEO CONTENT ═══════════════════ -->
"""


def get_schema_ld(lang: str) -> tuple[str, str]:
    """Restituisce (faq_ld_json, howto_ld_json) per la lingua data.

    Questi JSON-LD vanno iniettati nel <head> per massima visibilità
    ai validatori Schema.org e ai crawler AI.
    """
    _article, faq_ld, howto_ld = _build_seo_block(lang)
    return faq_ld, howto_ld
