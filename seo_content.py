"""
seo_content.py — Testi SEO visibili iniettati server-side nel body HTML.

Questo modulo genera un blocco <section> con:
  - H2 heading con keyword primaria
  - Paragrafo descrittivo denso di keyword
  - Lista "Come funziona" (features)
  - FAQ con <details>/<summary> (accessibili e SEO-friendly)
  - FAQPage JSON-LD schema (separato dal WebApplication nel <head>)

Tutto questo HTML è presente nel sorgente statico della pagina, visibile
ai crawler dei motori di ricerca SENZA esecuzione di JavaScript.

Il blocco si adatta al tema della pagina usando le CSS custom properties
(--tx, --txd, --srf, ecc.) già definite nel tema light/dark.
"""

from html import escape
import json


# ═══════════════════════════════════════════════════════════════════
# CONTENUTI SEO VISIBILI PER LINGUA
# ═══════════════════════════════════════════════════════════════════

_CONTENT = {
    # ─── ITALIANO ───────────────────────────────────────────────────
    "it": {
        "heading": "Converti i tuoi Ebook EPUB in Audiolibri MP3 — Gratis Online",
        "text": (
            "Audiobook Maker è un convertitore online gratuito che trasforma i tuoi ebook EPUB "
            "in audiolibri MP3 utilizzando voci AI naturali con tecnologia text-to-speech avanzata. "
            "Carica il tuo libro in formato EPUB, scegli tra diverse voci di sintesi vocale disponibili "
            "in italiano, inglese, francese, spagnolo, tedesco e cinese, e scarica il tuo audiolibro "
            "pronto per l'ascolto. Non è necessaria alcuna installazione: il convertitore funziona "
            "direttamente dal browser. Perfetto per chi vuole ascoltare i propri libri preferiti "
            "in movimento, durante il tragitto casa-lavoro o mentre si rilassa. "
            "Ideale per ipovedenti e persone con difficoltà di lettura come la dislessia. "
            "Trasforma qualsiasi ebook in un libro parlato con pochi clic."
        ),
        "features_heading": "Come Funziona il Convertitore EPUB in Audiolibro",
        "features": [
            "Carica il tuo file EPUB — il convertitore supporta ebook di qualsiasi dimensione",
            "Scegli la voce AI e la lingua di narrazione tra le opzioni disponibili",
            "Seleziona i capitoli da convertire o converti l'intero libro",
            "Avvia la conversione text-to-speech con un clic e attendi l'elaborazione",
            "Scarica l'audiolibro in formato MP3 pronto per l'ascolto su qualsiasi dispositivo",
            "Genera un feed RSS podcast per ascoltare i capitoli nella tua app preferita",
        ],
        "faq_heading": "Domande Frequenti — Convertitore EPUB Audiolibro",
        "faqs": [
            ("Come convertire un EPUB in audiolibro gratis?",
             "Carica il tuo file EPUB su Audiobook Maker, seleziona una voce AI e la lingua desiderata, "
             "poi clicca su Converti. Il convertitore text-to-speech gratuito genererà l'audiolibro "
             "in formato MP3 che potrai scaricare e ascoltare ovunque."),
            ("Quali formati di ebook sono supportati?",
             "Audiobook Maker supporta il formato EPUB, lo standard più diffuso per gli ebook digitali. "
             "Se il tuo libro è in un altro formato (PDF, MOBI, AZW), puoi convertirlo prima in EPUB "
             "usando strumenti gratuiti come Calibre."),
            ("Le voci AI sono naturali?",
             "Sì, il convertitore utilizza voci neurali TTS di alta qualità (Edge TTS) con sintesi "
             "vocale AI che produce voci naturali e piacevoli da ascoltare in 6 lingue diverse."),
            ("Devo installare qualcosa?",
             "No, Audiobook Maker è un convertitore online che funziona completamente nel browser. "
             "Non serve scaricare né installare alcun software."),
            ("Posso generare un podcast dai capitoli del libro?",
             "Sì, Audiobook Maker può generare un feed RSS podcast con tutti i capitoli del tuo "
             "audiolibro. Puoi copiare il link e aggiungerlo alla tua app podcast preferita per "
             "ascoltare i capitoli in streaming."),
            ("Il servizio è davvero gratuito?",
             "Sì, Audiobook Maker è completamente gratuito. Non richiede registrazione, "
             "non ha limiti di utilizzo e non inserisce pubblicità nei file audio generati."),
        ],
    },
    # ─── ENGLISH ────────────────────────────────────────────────────
    "en": {
        "heading": "Convert Your EPUB Ebooks to MP3 Audiobooks — Free Online",
        "text": (
            "Audiobook Maker is a free online converter that transforms your EPUB ebooks into MP3 audiobooks "
            "using natural AI voices powered by advanced text-to-speech technology. "
            "Upload your book in EPUB format, choose from multiple AI voices available in English, "
            "Italian, French, Spanish, German, and Chinese, and download your audiobook ready to listen. "
            "No installation required — the converter works directly in your browser. "
            "Perfect for anyone who wants to listen to their favorite books on the go, during commutes, "
            "or while relaxing. Great for visually impaired readers and people with reading difficulties "
            "like dyslexia. Turn any ebook into a spoken book with just a few clicks."
        ),
        "features_heading": "How the EPUB to Audiobook Converter Works",
        "features": [
            "Upload your EPUB file — the converter supports ebooks of any size",
            "Choose the AI voice and narration language from available options",
            "Select specific chapters to convert or convert the entire book",
            "Start the text-to-speech conversion with one click and wait for processing",
            "Download your audiobook in MP3 format ready to listen on any device",
            "Generate a podcast RSS feed to listen to chapters in your favorite app",
        ],
        "faq_heading": "Frequently Asked Questions — EPUB to Audiobook Converter",
        "faqs": [
            ("How to convert an EPUB to audiobook for free?",
             "Upload your EPUB file to Audiobook Maker, select an AI voice and your desired language, "
             "then click Convert. The free text-to-speech converter will generate the audiobook "
             "in MP3 format that you can download and listen to anywhere."),
            ("What ebook formats are supported?",
             "Audiobook Maker supports the EPUB format, the most widely used standard for digital ebooks. "
             "If your book is in another format (PDF, MOBI, AZW), you can convert it to EPUB first "
             "using free tools like Calibre."),
            ("Are the AI voices natural-sounding?",
             "Yes, the converter uses high-quality neural TTS voices (Edge TTS) with AI voice synthesis "
             "that produces natural and pleasant voices in 6 different languages."),
            ("Do I need to install anything?",
             "No, Audiobook Maker is an online converter that works entirely in your browser. "
             "No software download or installation is required."),
            ("Can I generate a podcast from the book chapters?",
             "Yes, Audiobook Maker can generate a podcast RSS feed with all your audiobook chapters. "
             "Copy the link and add it to your favorite podcast app to stream chapters."),
            ("Is the service really free?",
             "Yes, Audiobook Maker is completely free. No registration required, "
             "no usage limits, and no ads inserted in the generated audio files."),
        ],
    },
    # ─── FRANÇAIS ───────────────────────────────────────────────────
    "fr": {
        "heading": "Convertissez vos Ebooks EPUB en Livres Audio MP3 — Gratuit en Ligne",
        "text": (
            "Audiobook Maker est un convertisseur en ligne gratuit qui transforme vos ebooks EPUB en livres "
            "audio MP3 en utilisant des voix IA naturelles grâce à une technologie text-to-speech avancée. "
            "Téléchargez votre livre au format EPUB, choisissez parmi plusieurs voix de synthèse vocale "
            "disponibles en français, anglais, italien, espagnol, allemand et chinois, "
            "et téléchargez votre livre audio prêt à écouter. "
            "Aucune installation nécessaire : le convertisseur fonctionne directement dans votre navigateur. "
            "Idéal pour les malvoyants et les personnes ayant des difficultés de lecture comme la dyslexie. "
            "Parfait pour écouter vos livres préférés en déplacement."
        ),
        "features_heading": "Comment Fonctionne le Convertisseur EPUB en Livre Audio",
        "features": [
            "Téléchargez votre fichier EPUB — le convertisseur prend en charge les ebooks de toute taille",
            "Choisissez la voix IA et la langue de narration parmi les options disponibles",
            "Sélectionnez les chapitres à convertir ou convertissez le livre entier",
            "Lancez la conversion text-to-speech en un clic et attendez le traitement",
            "Téléchargez votre livre audio au format MP3 prêt à écouter sur tout appareil",
            "Générez un flux RSS podcast pour écouter les chapitres dans votre app préférée",
        ],
        "faq_heading": "Questions Fréquentes — Convertisseur EPUB Livre Audio",
        "faqs": [
            ("Comment convertir un EPUB en livre audio gratuitement ?",
             "Téléchargez votre fichier EPUB sur Audiobook Maker, sélectionnez une voix IA et la langue, "
             "puis cliquez sur Convertir. Le convertisseur text-to-speech gratuit générera le livre audio "
             "au format MP3 que vous pourrez télécharger et écouter partout."),
            ("Quels formats d'ebook sont supportés ?",
             "Audiobook Maker prend en charge le format EPUB, le standard le plus répandu pour les ebooks "
             "numériques. Vous pouvez convertir d'autres formats en EPUB avec Calibre."),
            ("Les voix IA sont-elles naturelles ?",
             "Oui, le convertisseur utilise des voix neuronales TTS de haute qualité avec synthèse vocale "
             "IA qui produit des voix naturelles et agréables dans 6 langues différentes."),
            ("Dois-je installer quelque chose ?",
             "Non, Audiobook Maker fonctionne entièrement dans votre navigateur, sans installation."),
            ("Le service est-il vraiment gratuit ?",
             "Oui, Audiobook Maker est entièrement gratuit. Pas d'inscription requise, "
             "pas de limites d'utilisation et pas de publicité dans les fichiers audio générés."),
        ],
    },
    # ─── ESPAÑOL ────────────────────────────────────────────────────
    "es": {
        "heading": "Convierte tus Ebooks EPUB en Audiolibros MP3 — Gratis Online",
        "text": (
            "Audiobook Maker es un convertidor en línea gratuito que transforma tus ebooks EPUB en "
            "audiolibros MP3 utilizando voces IA naturales con tecnología text-to-speech avanzada. "
            "Sube tu libro en formato EPUB, elige entre diversas voces de síntesis de voz "
            "disponibles en español, inglés, italiano, francés, alemán y chino, "
            "y descarga tu audiolibro listo para escuchar. "
            "No necesitas instalar nada: el convertidor funciona directamente desde tu navegador. "
            "Ideal para personas con discapacidad visual y dificultades de lectura como la dislexia. "
            "Perfecto para escuchar tus libros favoritos en movimiento."
        ),
        "features_heading": "Cómo Funciona el Convertidor EPUB a Audiolibro",
        "features": [
            "Sube tu archivo EPUB — el convertidor admite ebooks de cualquier tamaño",
            "Elige la voz IA y el idioma de narración entre las opciones disponibles",
            "Selecciona los capítulos a convertir o convierte el libro completo",
            "Inicia la conversión text-to-speech con un clic y espera el procesamiento",
            "Descarga tu audiolibro en formato MP3 listo para escuchar en cualquier dispositivo",
            "Genera un feed RSS podcast para escuchar los capítulos en tu app favorita",
        ],
        "faq_heading": "Preguntas Frecuentes — Convertidor EPUB a Audiolibro",
        "faqs": [
            ("¿Cómo convertir un EPUB a audiolibro gratis?",
             "Sube tu archivo EPUB a Audiobook Maker, selecciona una voz IA y el idioma deseado, "
             "luego haz clic en Convertir. El convertidor text-to-speech gratuito generará el audiolibro "
             "en formato MP3 que podrás descargar y escuchar en cualquier lugar."),
            ("¿Qué formatos de ebook son compatibles?",
             "Audiobook Maker admite el formato EPUB, el estándar más utilizado para ebooks digitales. "
             "Puedes convertir otros formatos a EPUB usando herramientas gratuitas como Calibre."),
            ("¿Las voces IA suenan naturales?",
             "Sí, el convertidor utiliza voces neuronales TTS de alta calidad con síntesis de voz IA "
             "que produce voces naturales y agradables en 6 idiomas diferentes."),
            ("¿Necesito instalar algo?",
             "No, Audiobook Maker funciona completamente en tu navegador, sin instalación."),
            ("¿El servicio es realmente gratuito?",
             "Sí, Audiobook Maker es completamente gratuito. Sin registro, "
             "sin límites de uso y sin publicidad en los archivos de audio generados."),
        ],
    },
    # ─── DEUTSCH ────────────────────────────────────────────────────
    "de": {
        "heading": "Konvertieren Sie Ihre EPUB E-Books in MP3-Hörbücher — Kostenlos Online",
        "text": (
            "Audiobook Maker ist ein kostenloser Online-Konverter, der Ihre EPUB-E-Books in MP3-Hörbücher "
            "umwandelt — mit natürlichen KI-Stimmen und fortschrittlicher Text-to-Speech-Technologie. "
            "Laden Sie Ihr Buch im EPUB-Format hoch, wählen Sie aus verschiedenen Sprachsynthese-Stimmen "
            "auf Deutsch, Englisch, Italienisch, Französisch, Spanisch und Chinesisch, "
            "und laden Sie Ihr fertiges Hörbuch herunter. "
            "Keine Installation erforderlich — der Konverter funktioniert direkt im Browser. "
            "Ideal für Sehbehinderte und Menschen mit Leseschwierigkeiten wie Legasthenie. "
            "Perfekt für alle, die ihre Lieblingsbücher unterwegs hören möchten."
        ),
        "features_heading": "So Funktioniert der EPUB-zu-Hörbuch-Konverter",
        "features": [
            "Laden Sie Ihre EPUB-Datei hoch — der Konverter unterstützt E-Books jeder Größe",
            "Wählen Sie die KI-Stimme und die Erzählsprache aus den verfügbaren Optionen",
            "Wählen Sie bestimmte Kapitel oder konvertieren Sie das ganze Buch",
            "Starten Sie die Text-to-Speech-Konvertierung mit einem Klick",
            "Laden Sie Ihr Hörbuch im MP3-Format herunter, bereit zum Anhören auf jedem Gerät",
            "Erstellen Sie einen Podcast-RSS-Feed, um Kapitel in Ihrer Lieblings-App zu hören",
        ],
        "faq_heading": "Häufig Gestellte Fragen — EPUB-zu-Hörbuch-Konverter",
        "faqs": [
            ("Wie wandelt man ein EPUB kostenlos in ein Hörbuch um?",
             "Laden Sie Ihre EPUB-Datei auf Audiobook Maker hoch, wählen Sie eine KI-Stimme und die "
             "gewünschte Sprache, dann klicken Sie auf Konvertieren. Der kostenlose Text-to-Speech-Konverter "
             "erstellt das Hörbuch im MP3-Format zum Herunterladen."),
            ("Welche E-Book-Formate werden unterstützt?",
             "Audiobook Maker unterstützt das EPUB-Format, den verbreitetsten Standard für digitale E-Books. "
             "Andere Formate können Sie mit Calibre zuerst in EPUB konvertieren."),
            ("Klingen die KI-Stimmen natürlich?",
             "Ja, der Konverter nutzt hochwertige neuronale TTS-Stimmen mit KI-Sprachsynthese, "
             "die natürliche Stimmen in 6 verschiedenen Sprachen erzeugt."),
            ("Muss ich etwas installieren?",
             "Nein, Audiobook Maker funktioniert vollständig in Ihrem Browser, ohne Installation."),
            ("Ist der Dienst wirklich kostenlos?",
             "Ja, Audiobook Maker ist völlig kostenlos. Keine Registrierung erforderlich, "
             "keine Nutzungsbeschränkungen und keine Werbung in den erzeugten Audiodateien."),
        ],
    },
    # ─── 中文 ───────────────────────────────────────────────────────
    "zh": {
        "heading": "免费在线将EPUB电子书转换为MP3有声书",
        "text": (
            "Audiobook Maker是一款免费在线转换器，利用先进的AI文字转语音技术，"
            "将您的EPUB电子书转换为MP3有声书，声音自然逼真。"
            "上传EPUB格式的书籍，从中文、英语、意大利语、法语、西班牙语和德语中选择AI语音，"
            "然后下载即可收听的有声书。"
            "无需安装任何软件——转换器直接在浏览器中运行。"
            "非常适合视力障碍者和有阅读困难（如读写困难症）的人群。"
            "在通勤途中或休闲时刻收听您喜爱的书籍，只需几次点击。"
        ),
        "features_heading": "EPUB转有声书转换器使用方法",
        "features": [
            "上传EPUB文件——转换器支持任意大小的电子书",
            "从可用选项中选择AI语音和朗读语言",
            "选择要转换的章节或转换整本书",
            "一键启动文字转语音转换，等待处理完成",
            "下载MP3格式的有声书，可在任何设备上收听",
            "生成播客RSS订阅源，在您喜爱的应用中收听章节",
        ],
        "faq_heading": "常见问题 — EPUB转有声书转换器",
        "faqs": [
            ("如何免费将EPUB转换为有声书？",
             "将EPUB文件上传到Audiobook Maker，选择AI语音和所需语言，"
             "然后点击转换。免费文字转语音转换器将生成MP3格式的有声书，可随时随地收听。"),
            ("支持哪些电子书格式？",
             "Audiobook Maker支持EPUB格式，这是数字电子书最广泛使用的标准。"
             "其他格式可以先使用Calibre等免费工具转换为EPUB。"),
            ("AI语音听起来自然吗？",
             "是的，转换器使用高质量的神经网络TTS语音和AI语音合成，"
             "能够在6种不同语言中产生自然悦耳的声音。"),
            ("需要安装什么吗？",
             "不需要，Audiobook Maker完全在浏览器中运行，无需下载或安装。"),
            ("服务真的免费吗？",
             "是的，Audiobook Maker完全免费。无需注册，无使用限制，生成的音频文件中也没有广告。"),
        ],
    },
}


def build_seo_content_html(lang: str) -> str:
    """Genera il blocco HTML SEO visibile per una data lingua.

    Questo blocco viene iniettato server-side nel body prima di </body>.
    I crawler lo vedono immediatamente senza eseguire JavaScript.

    Include:
      - H2 heading ricco di keyword
      - Paragrafo descrittivo denso di keyword
      - Lista ordinata "Come funziona"
      - FAQ con <details>/<summary>
      - FAQPage JSON-LD structured data

    Il contenuto è stilizzato con le CSS custom properties del tema
    e integrato in modo armonioso con il design della pagina.
    """
    c = _CONTENT.get(lang, _CONTENT["en"])

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
            f'                <p>{escape(a)}</p>\n'
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

    return f"""
<!-- ═══════════════════ SEO CONTENT (server-rendered, visible to crawlers) ═══════════════════ -->
<style>
#seoContent {{ max-width:800px; margin:2.5rem auto 1rem; padding:0 1.5rem;
  font-family:'DM Sans',system-ui,sans-serif; font-size:0.92rem; line-height:1.7; color:var(--txd,#6b6760) }}
#seoContent h2 {{ font-size:1.25rem; color:var(--tx,#2c2a26); margin-bottom:0.8rem; font-weight:600 }}
#seoContent h3 {{ font-size:1.1rem; color:var(--tx,#2c2a26); margin:1.5rem 0 0.5rem; font-weight:600 }}
#seoContent ol {{ padding-left:1.3rem; margin:0.5rem 0 }}
#seoContent li {{ margin-bottom:0.3rem }}
#seoContent details {{ margin-bottom:0.5rem; padding:0.5rem 0; border-bottom:1px solid var(--brd,#d5d0c8) }}
#seoContent summary {{ cursor:pointer; font-weight:500; color:var(--tx,#2c2a26) }}
#seoContent summary:hover {{ color:var(--ac,#c47a2a) }}
#seoContent details p {{ margin:0.5rem 0 0; padding-left:0.5rem }}
</style>
<section id="seoContent" data-lang="{lang}">
    <article>
        <h2>{escape(c["heading"])}</h2>
        <p>{escape(c["text"])}</p>

        <h3>{escape(c["features_heading"])}</h3>
        <ol>
{features_li}
        </ol>

        <h3>{escape(c["faq_heading"])}</h3>
        <div>
{faqs_html}        </div>
    </article>
    <script type="application/ld+json">{faq_ld_json}</script>
</section>
<!-- ═══════════════════ /SEO CONTENT ═══════════════════ -->
"""
