"""
SEO Guide Pages for Audiobook Maker.

Provides long-form guide content targeting informational keywords:
  - /guide/epub-to-audiobook/
  - /guide/m4b-format/
  - /guide/text-to-speech-audiobook/

Each guide has full EN content + metadata for all 6 languages.
"""

from __future__ import annotations

_HREFLANG_MAP = {
    "it": "it", "en": "en", "fr": "fr",
    "es": "es", "de": "de", "zh": "zh-Hans",
    "hi": "hi",
}
_OG_LOCALE_MAP = {
    "it": "it_IT", "en": "en_US", "fr": "fr_FR",
    "es": "es_ES", "de": "de_DE", "zh": "zh_CN",
    "hi": "hi_IN",
}
_SUPPORTED_LANGS = list(_HREFLANG_MAP.keys())

# ── Guide metadata per language ──────────────────────────────────────────────

_GUIDE_META = {
    "free-ebooks": {
        "en": {
            "title": "Where to Find Free Ebooks to Download (8 Best Sites) | Audiobook Maker",
            "desc": "The 8 best sites to download free ebooks legally: Project Gutenberg, Standard Ebooks, Internet Archive and more. Learn what's public domain and how to turn any free EPUB into an audiobook for free.",
            "kw": "free ebooks, download free ebooks, free epub, public domain books, project gutenberg, standard ebooks, free books online, where to find free ebooks, free audiobooks from ebooks",
            "h1": "Where to Find Free Ebooks to Download",
        },
        "it": {
            "title": "Dove Trovare Ebook Gratuiti da Scaricare (8 Siti Migliori) | Audiobook Maker",
            "desc": "I 8 migliori siti per scaricare ebook gratuiti legalmente: Project Gutenberg, Standard Ebooks, Internet Archive e altri. Scopri cosa è di pubblico dominio e come trasformare qualsiasi EPUB gratuito in audiolibro gratis.",
            "kw": "ebook gratuiti, scaricare ebook gratis, epub gratis, libri pubblico dominio, project gutenberg, standard ebooks, libri gratis online, dove trovare ebook gratuiti, audiolibri gratis da ebook",
            "h1": "Dove Trovare Ebook Gratuiti da Scaricare",
        },
        "fr": {
            "title": "Où Trouver des Ebooks Gratuits à Télécharger (8 Meilleurs Sites) | Audiobook Maker",
            "desc": "Les 8 meilleurs sites pour télécharger des ebooks gratuits légalement : Project Gutenberg, Standard Ebooks, Internet Archive et plus. Découvrez le domaine public et comment transformer un EPUB gratuit en livre audio gratuitement.",
            "kw": "ebooks gratuits, télécharger ebooks gratuits, epub gratuit, livres domaine public, project gutenberg, standard ebooks, livres gratuits en ligne, où trouver des ebooks gratuits",
            "h1": "Où Trouver des Ebooks Gratuits à Télécharger",
        },
        "es": {
            "title": "Dónde Encontrar Ebooks Gratis para Descargar (8 Mejores Sitios) | Audiobook Maker",
            "desc": "Los 8 mejores sitios para descargar ebooks gratis legalmente: Project Gutenberg, Standard Ebooks, Internet Archive y más. Descubre el dominio público y cómo convertir cualquier EPUB gratis en audiolibro gratis.",
            "kw": "ebooks gratis, descargar ebooks gratis, epub gratis, libros dominio público, project gutenberg, standard ebooks, libros gratis online, dónde encontrar ebooks gratis",
            "h1": "Dónde Encontrar Ebooks Gratis para Descargar",
        },
        "de": {
            "title": "Wo Sie kostenlose E-Books herunterladen (8 beste Seiten) | Audiobook Maker",
            "desc": "Die 8 besten Seiten zum legalen Download kostenloser E-Books: Project Gutenberg, Standard Ebooks, Internet Archive und mehr. Erfahren Sie, was gemeinfrei ist und wie Sie jedes kostenlose EPUB kostenlos in ein Hörbuch verwandeln.",
            "kw": "kostenlose ebooks, kostenlose ebooks herunterladen, kostenloses epub, gemeinfreie bücher, project gutenberg, standard ebooks, kostenlose bücher online, wo kostenlose ebooks finden",
            "h1": "Wo Sie kostenlose E-Books herunterladen",
        },
        "zh": {
            "title": "在哪里下载免费电子书（8个最佳网站）| Audiobook Maker",
            "desc": "合法下载免费电子书的8个最佳网站：Project Gutenberg、Standard Ebooks、Internet Archive 等。了解什么是公共领域，以及如何将任何免费EPUB免费转换为有声书。",
            "kw": "免费电子书, 下载免费电子书, 免费epub, 公共领域图书, project gutenberg, standard ebooks, 在线免费图书, 哪里找免费电子书",
            "h1": "在哪里下载免费电子书",
        },
        "hi": {
            "title": "मुफ़्त ईबुक कहाँ से डाउनलोड करें (8 सर्वश्रेष्ठ साइटें) | Audiobook Maker",
            "desc": "मुफ़्त ईबुक कानूनी रूप से डाउनलोड करने की 8 सर्वश्रेष्ठ साइटें: Project Gutenberg, Standard Ebooks, Internet Archive और अधिक. जानें कि सार्वजनिक डोमेन क्या है और किसी भी मुफ़्त EPUB को मुफ़्त में ऑडियोबुक में कैसे बदलें.",
            "kw": "मुफ़्त ईबुक, मुफ़्त ईबुक डाउनलोड, मुफ़्त epub, सार्वजनिक डोमेन पुस्तकें, project gutenberg, standard ebooks, मुफ़्त ऑनलाइन किताबें, मुफ़्त ईबुक कहाँ मिलेंगी",
            "h1": "मुफ़्त ईबुक कहाँ से डाउनलोड करें",
        },
    },
    "epub-to-audiobook": {
        "en": {
            "title": "How to Convert EPUB to Audiobook Free — Complete Guide 2026 | Audiobook Maker",
            "desc": "Step-by-step guide: convert EPUB ebooks to MP3 or M4B audiobooks for free. Learn how to choose the best TTS voices, preserve chapters, and create professional audiobooks from any EPUB file. No software installation required.",
            "kw": "convert epub to audiobook, epub to mp3, epub to m4b, how to make audiobook from epub, epub audiobook converter free, best way to convert epub to audio, create audiobook from epub free, epub text to speech, turn ebook into audiobook",
            "h1": "How to Convert EPUB to Audiobook (Free & Online)",
        },
        "it": {
            "title": "Come Convertire EPUB in Audiolibro Gratis — Guida Completa | Audiobook Maker",
            "desc": "Guida passo-passo per convertire ebook EPUB in audiolibri MP3 o M4B gratis. Scopri come scegliere le migliori voci TTS, preservare i capitoli e creare audiolibri professionali da qualsiasi file EPUB.",
            "kw": "convertire epub in audiolibro, epub a mp3, epub a m4b, come creare audiolibro da epub, convertitore epub audiolibro gratis, epub text to speech italiano, trasformare ebook in audio",
            "h1": "Come Convertire EPUB in Audiolibro (Gratis & Online)",
        },
        "fr": {
            "title": "Comment Convertir EPUB en Livre Audio Gratuit — Guide Complet | Audiobook Maker",
            "desc": "Guide étape par étape pour convertir vos ebooks EPUB en livres audio MP3 ou M4B gratuitement. Apprenez à choisir les meilleures voix TTS et à créer des livres audio professionnels.",
            "kw": "convertir epub en livre audio, epub vers mp3, epub vers m4b, convertisseur epub audio gratuit, comment créer un livre audio depuis epub",
            "h1": "Comment Convertir EPUB en Livre Audio (Gratuit & en Ligne)",
        },
        "es": {
            "title": "Cómo Convertir EPUB a Audiolibro Gratis — Guía Completa | Audiobook Maker",
            "desc": "Guía paso a paso para convertir ebooks EPUB en audiolibros MP3 o M4B gratis. Aprende a elegir las mejores voces TTS y crear audiolibros profesionales desde cualquier archivo EPUB.",
            "kw": "convertir epub a audiolibro, epub a mp3, epub a m4b, convertidor epub audiolibro gratis, como crear audiolibro desde epub, epub texto a voz",
            "h1": "Cómo Convertir EPUB a Audiolibro (Gratis & Online)",
        },
        "de": {
            "title": "EPUB in Hörbuch umwandeln — Kostenlose Anleitung | Audiobook Maker",
            "desc": "Schritt-für-Schritt-Anleitung: EPUB eBooks kostenlos in MP3 oder M4B Hörbücher umwandeln. Erfahren Sie, wie Sie die besten TTS-Stimmen wählen und professionelle Hörbücher erstellen.",
            "kw": "epub in hörbuch umwandeln, epub zu mp3, epub zu m4b, epub hörbuch konverter kostenlos, hörbuch aus epub erstellen, epub text to speech deutsch",
            "h1": "EPUB in Hörbuch umwandeln (Kostenlos & Online)",
        },
        "zh": {
            "title": "如何免费将EPUB转换为有声书 — 完整指南 | Audiobook Maker",
            "desc": "逐步指南：免费将EPUB电子书转换为MP3或M4B有声书。了解如何选择最佳TTS语音，保留章节，从任何EPUB文件创建专业有声书。无需安装软件。",
            "kw": "epub转有声书, epub转mp3, epub转m4b, 免费epub有声书转换器, 如何从epub创建有声书, epub文字转语音",
            "h1": "如何免费将EPUB转换为有声书（在线工具）",
        },
        "hi": {
            "title": "EPUB को ऑडियोबुक में मुफ़्त बदलें — पूरी गाइड | Audiobook Maker",
            "desc": "EPUB ईबुक को मुफ़्त में MP3 या M4B ऑडियोबुक में बदलने की चरण-दर-चरण मार्गदर्शिका. सर्वोत्तम TTS आवाज़ें चुनना, अध्याय संरक्षित करना, और किसी भी EPUB फ़ाइल से पेशेवर ऑडियोबुक बनाना सीखें. कोई सॉफ़्टवेयर इंस्टॉलेशन आवश्यक नहीं.",
            "kw": "epub से ऑडियोबुक बदलें, epub से mp3, epub से m4b, मुफ़्त epub ऑडियोबुक कनवर्टर, epub से ऑडियोबुक कैसे बनाएं, epub टेक्स्ट टू स्पीच",
            "h1": "EPUB को ऑडियोबुक में कैसे बदलें (मुफ़्त और ऑनलाइन)",
        },
    },
    "m4b-format": {
        "en": {
            "title": "M4B Format Guide: Create Audiobooks with Chapters | Audiobook Maker",
            "desc": "Everything about the M4B audiobook format: what it is, how it differs from MP3, how to create M4B files with embedded chapters and cover art, and why M4B is the best format for audiobooks. Free M4B creator tool included.",
            "kw": "m4b format, what is m4b, m4b vs mp3, create m4b with chapters, m4b creator, m4b converter, how to make m4b file, m4b audiobook format, m4b chapter markers, convert to m4b free",
            "h1": "M4B Format: The Ultimate Guide to Audiobook Files with Chapters",
        },
        "it": {
            "title": "Guida Formato M4B: Crea Audiolibri con Capitoli | Audiobook Maker",
            "desc": "Tutto sul formato audiolibro M4B: cos'è, differenze con MP3, come creare file M4B con capitoli e copertina incorporati, e perché M4B è il formato migliore per gli audiolibri.",
            "kw": "formato m4b, cos'è m4b, m4b vs mp3, creare m4b con capitoli, creatore m4b, convertitore m4b, come creare file m4b, formato audiolibro m4b",
            "h1": "Formato M4B: Guida Completa ai File Audiolibro con Capitoli",
        },
        "fr": {
            "title": "Guide Format M4B: Créer des Livres Audio avec Chapitres | Audiobook Maker",
            "desc": "Tout sur le format livre audio M4B: définition, différences avec MP3, comment créer des fichiers M4B avec chapitres et couverture intégrés, et pourquoi le M4B est le meilleur format.",
            "kw": "format m4b, qu'est-ce que m4b, m4b vs mp3, créer m4b avec chapitres, créateur m4b, convertisseur m4b, format livre audio m4b",
            "h1": "Format M4B: Guide Complet des Fichiers Livre Audio avec Chapitres",
        },
        "es": {
            "title": "Guía Formato M4B: Crea Audiolibros con Capítulos | Audiobook Maker",
            "desc": "Todo sobre el formato audiolibro M4B: qué es, diferencias con MP3, cómo crear archivos M4B con capítulos y portada, y por qué M4B es el mejor formato para audiolibros.",
            "kw": "formato m4b, qué es m4b, m4b vs mp3, crear m4b con capítulos, creador m4b, convertidor m4b, formato audiolibro m4b",
            "h1": "Formato M4B: Guía Completa de Archivos Audiolibro con Capítulos",
        },
        "de": {
            "title": "M4B Format Guide: Hörbücher mit Kapiteln erstellen | Audiobook Maker",
            "desc": "Alles über das M4B Hörbuchformat: Was es ist, Unterschiede zu MP3, wie man M4B-Dateien mit Kapiteln und Cover-Art erstellt, und warum M4B das beste Format für Hörbücher ist.",
            "kw": "m4b format, was ist m4b, m4b vs mp3, m4b mit kapiteln erstellen, m4b creator, m4b konverter, hörbuchformat m4b",
            "h1": "M4B Format: Der ultimative Guide für Hörbuchdateien mit Kapiteln",
        },
        "zh": {
            "title": "M4B格式指南：创建带章节的有声书 | Audiobook Maker",
            "desc": "关于M4B有声书格式的一切：什么是M4B，与MP3的区别，如何创建带嵌入式章节和封面的M4B文件，以及为什么M4B是有声书的最佳格式。",
            "kw": "m4b格式, 什么是m4b, m4b与mp3, 创建带章节的m4b, m4b制作工具, m4b转换器, m4b有声书格式",
            "h1": "M4B格式：带章节有声书文件终极指南",
        },
        "hi": {
            "title": "M4B प्रारूप मार्गदर्शिका: अध्यायों के साथ ऑडियोबुक बनाएं | Audiobook Maker",
            "desc": "M4B ऑडियोबुक प्रारूप के बारे में सब कुछ: यह क्या है, MP3 से अंतर, अंतर्निहित अध्यायों और कवर के साथ M4B फ़ाइलें कैसे बनाएं, और क्यों M4B ऑडियोबुक के लिए सर्वोत्तम प्रारूप है.",
            "kw": "m4b प्रारूप, m4b क्या है, m4b बनाम mp3, अध्यायों के साथ m4b बनाएं, m4b मेकर, m4b कनवर्टर, m4b ऑडियोबुक प्रारूप",
            "h1": "M4B प्रारूप: अध्यायों वाली ऑडियोबुक फ़ाइलों की पूरी मार्गदर्शिका",
        },
    },
    "text-to-speech-audiobook": {
        "en": {
            "title": "Free Text to Speech Audiobook Maker — Best TTS Voices 2026 | Audiobook Maker",
            "desc": "Create free audiobooks with natural AI text-to-speech voices. Compare the best TTS engines for audiobook creation (Edge TTS, Google TTS, Speechify alternatives). Convert text, EPUB and PDF to spoken audio online. No sign-up needed.",
            "kw": "free text to speech audiobook, tts online free, ai voice audiobook maker, speechify alternative free, naturalreader alternative, elevenlabs alternative free, play.ht alternative free, best tts for audiobooks, text to speech mp3 download, ai narrator free, listen to books online, read aloud app, convert text to audio book, audiobook for dyslexia, text to speech for visually impaired, tts for learning disabilities, audio books for blind, screen reader alternative, dyslexia reading tool, adhd reading help, accessible audiobook maker",
            "h1": "Free Text-to-Speech Audiobook Maker: Best TTS for 2026",
        },
        "it": {
            "title": "Text to Speech Audiolibri Gratis — Migliori Voci TTS 2026 | Audiobook Maker",
            "desc": "Crea audiolibri gratis con voci AI text-to-speech naturali. Confronta i migliori motori TTS per creare audiolibri (Edge TTS, Google TTS, alternative a Speechify). Converti testo, EPUB e PDF in audio online.",
            "kw": "text to speech audiolibri gratis, tts online gratis, creatore audiolibri con voce ai, alternativa a speechify gratis, alternativa naturalreader, alternativa elevenlabs gratis, alternativa play.ht gratis, miglior tts per audiolibri, text to speech mp3 download, narratore ai gratis, audiolibri per dislessia, audiolibri per ipovedenti, sintesi vocale per non vedenti, strumento lettura dislessia, tts accessibilità",
            "h1": "Text-to-Speech Audiolibri Gratis: Migliori Voci TTS 2026",
        },
        "fr": {
            "title": "Text to Speech Livre Audio Gratuit — Meilleures Voix TTS 2026 | Audiobook Maker",
            "desc": "Créez des livres audio gratuits avec des voix IA text-to-speech naturelles. Comparez les meilleurs moteurs TTS pour la création de livres audio (Edge TTS, Google TTS, alternatives à Speechify).",
            "kw": "text to speech livre audio gratuit, tts en ligne gratuit, créateur livre audio voix ia, alternative à speechify gratuit, alternative elevenlabs gratuit, alternative play.ht gratuit, meilleur tts pour livres audio, télécharger text to speech mp3, livre audio dyslexie, livre audio malvoyants, texte à parole handicap visuel, outil lecture dyslexie, tts accessibilité",
            "h1": "Text-to-Speech Livre Audio Gratuit: Meilleures Voix TTS 2026",
        },
        "es": {
            "title": "Text to Speech Audiolibros Gratis — Mejores Voces TTS 2026 | Audiobook Maker",
            "desc": "Crea audiolibros gratis con voces AI text-to-speech naturales. Compara los mejores motores TTS para crear audiolibros (Edge TTS, Google TTS, alternativas a Speechify). Convierte texto, EPUB y PDF en audio online.",
            "kw": "text to speech audiolibros gratis, tts en línea gratis, creador audiolibros voz ia, alternativa a speechify gratis, alternativa elevenlabs gratis, alternativa play.ht gratis, mejor tts para audiolibros, descargar text to speech mp3, audiolibro para dislexia, audiolibro para discapacidad visual, texto a voz para ciegos, tts accesibilidad",
            "h1": "Text-to-Speech Audiolibros Gratis: Mejores Voces TTS 2026",
        },
        "de": {
            "title": "Kostenloser Text-to-Speech Hörbuch Maker — Beste TTS 2026 | Audiobook Maker",
            "desc": "Erstellen Sie kostenlose Hörbücher mit natürlichen KI-Text-to-Speech-Stimmen. Vergleichen Sie die besten TTS-Engines für Hörbücher (Edge TTS, Google TTS, Speechify-Alternativen). Text, EPUB und PDF online in Audio umwandeln.",
            "kw": "kostenlos text to speech hörbuch, tts online kostenlos, ki hörbuch ersteller, speechify alternative kostenlos, elevenlabs alternative kostenlos, play.ht alternative kostenlos, bester tts für hörbücher, text to speech mp3 herunterladen, hörbuch für legasthenie, hörbuch für sehbehinderte, text zu sprache behinderung, barrierefreies hörbuch",
            "h1": "Kostenloser Text-to-Speech Hörbuch Maker: Beste TTS 2026",
        },
        "zh": {
            "title": "免费文字转语音有声书制作 — 最佳TTS语音 | Audiobook Maker",
            "desc": "使用自然AI文字转语音免费创建有声书。比较最佳有声书TTS引擎（Edge TTS、Google TTS、Speechify替代品）。在线将文本、EPUB和PDF转换为语音。无需注册。",
            "kw": "免费文字转语音有声书, 在线tts免费, ai语音有声书制作, speechify替代品, elevenlabs替代品, play.ht替代品, 最佳有声书tts, 文字转语音mp3下载, ai旁白免费, 阅读障碍有声书, 盲人有声书, 视障文字转语音, 无障碍有声书制作",
            "h1": "免费文字转语音有声书制作：最佳TTS引擎",
        },
        "hi": {
            "title": "मुफ़्त टेक्स्ट टू स्पीच ऑडियोबुक मेकर — सर्वश्रेष्ठ TTS आवाज़ें 2026 | Audiobook Maker",
            "desc": "प्राकृतिक AI टेक्स्ट-टू-स्पीच आवाज़ों के साथ मुफ़्त ऑडियोबुक बनाएं. ऑडियोबुक निर्माण के लिए सर्वश्रेष्ठ TTS इंजनों की तुलना करें (Edge TTS, Google TTS, Speechify विकल्प). टेक्स्ट, EPUB और PDF को ऑनलाइन ऑडियो में बदलें. कोई साइन-अप आवश्यक नहीं.",
            "kw": "मुफ़्त टेक्स्ट टू स्पीच ऑडियोबुक, ऑनलाइन tts मुफ़्त, ai आवाज़ ऑडियोबुक मेकर, speechify मुफ़्त विकल्प, elevenlabs मुफ़्त विकल्प, ऑडियोबुक के लिए सर्वश्रेष्ठ tts, टेक्स्ट टू स्पीच mp3 डाउनलोड, मुफ़्त ai कथावाचक, डिस्लेक्सिया के लिए ऑडियोबुक, सुलभ ऑडियोबुक मेकर",
            "h1": "मुफ़्त टेक्स्ट-टू-स्पीच ऑडियोबुक मेकर: 2026 के सर्वश्रेष्ठ TTS",
        },
    },
    "gemini-tts": {
        "en": {
            "title": "Gemini TTS Voices, Languages & Prompting Guide | Audiobook Maker",
            "h1": "Gemini TTS: Voices, Languages & Prompting Guide",
            "kw": "gemini tts, gemini tts voices, gemini text to speech, gemini tts languages, gemini tts prompting, ai audiobook voices",
            "desc": "Complete guide to Gemini TTS: all 30 voices, 70+ supported languages, and how to control delivery with prompts. The PREMIUM neural voices in Audiobook Maker.",
        },
        "it": {
            "title": "Voci Gemini TTS, Lingue e Guida al Prompting | Audiobook Maker",
            "h1": "Gemini TTS: voci, lingue e guida al prompting",
            "kw": "gemini tts, voci gemini tts, gemini text to speech, lingue gemini tts, prompting gemini tts, voci ai audiolibro",
            "desc": "Guida completa a Gemini TTS: tutte le 30 voci, oltre 70 lingue supportate e come controllare la lettura con i prompt. Le voci neurali PREMIUM di Audiobook Maker.",
        },
        "fr": {
            "title": "Voix Gemini TTS, Langues et Guide de Prompting | Audiobook Maker",
            "h1": "Gemini TTS : voix, langues et guide de prompting",
            "kw": "gemini tts, voix gemini tts, gemini text to speech, langues gemini tts, prompting gemini tts, voix ia livre audio",
            "desc": "Guide complet sur Gemini TTS : les 30 voix disponibles, plus de 70 langues supportées et comment contrôler la narration avec des prompts. Les voix neurales PREMIUM d'Audiobook Maker.",
        },
        "es": {
            "title": "Voces Gemini TTS, Idiomas y Guía de Prompting | Audiobook Maker",
            "h1": "Gemini TTS: voces, idiomas y guía de prompting",
            "kw": "gemini tts, voces gemini tts, gemini text to speech, idiomas gemini tts, prompting gemini tts, voces ia audiolibro",
            "desc": "Guía completa de Gemini TTS: las 30 voces disponibles, más de 70 idiomas compatibles y cómo controlar la narración con prompts. Las voces neurales PREMIUM de Audiobook Maker.",
        },
        "de": {
            "title": "Gemini TTS Stimmen, Sprachen & Prompting-Leitfaden | Audiobook Maker",
            "h1": "Gemini TTS: Stimmen, Sprachen und Prompting-Leitfaden",
            "kw": "gemini tts, gemini tts stimmen, gemini text to speech, gemini tts sprachen, gemini tts prompting, ki hörbuch stimmen",
            "desc": "Vollständiger Leitfaden zu Gemini TTS: alle 30 Stimmen, über 70 unterstützte Sprachen und wie Sie die Wiedergabe mit Prompts steuern. Die neuronalen PREMIUM-Stimmen in Audiobook Maker.",
        },
        "zh": {
            "title": "Gemini TTS 语音、语言与提示词指南 | Audiobook Maker",
            "h1": "Gemini TTS：语音、语言与提示词指南",
            "kw": "gemini tts, gemini tts语音, gemini文字转语音, gemini tts语言, gemini tts提示词, ai有声书语音",
            "desc": "Gemini TTS 完整指南：全部30种语音、70多种支持语言，以及如何通过提示词控制朗读效果。Audiobook Maker 的 PREMIUM 神经语音。",
        },
        "hi": {
            "title": "Gemini TTS आवाज़ें, भाषाएँ और प्रॉम्प्टिंग गाइड | Audiobook Maker",
            "h1": "Gemini TTS: आवाज़ें, भाषाएँ और प्रॉम्प्टिंग गाइड",
            "kw": "gemini tts, gemini tts आवाज़ें, gemini text to speech, gemini tts भाषाएँ, gemini tts prompting, ai ऑडियोबुक आवाज़ें",
            "desc": "Gemini TTS की पूरी गाइड: सभी 30 आवाज़ें, 70+ समर्थित भाषाएँ, और प्रॉम्प्ट से पाठ-शैली कैसे नियंत्रित करें. Audiobook Maker की PREMIUM न्यूरल आवाज़ें.",
        },
    },
    "podcast": {
        "en": {
            "title": "How to Publish Your Audiobook as a Private Podcast — Free Guide | Audiobook Maker",
            "desc": "Learn how to turn your M4B or MP3 audiobook chapters into a private podcast RSS feed. Free hosting with Netlify, step-by-step setup for Apple Podcasts, Pocket Casts, and more.",
            "kw": "private podcast audiobook, podcast rss feed free, host audiobook as podcast, netlify podcast hosting, audiobook to podcast, free podcast hosting, apple podcasts private feed, personal podcast",
            "h1": "How to Publish Your Audiobook as a Private Podcast (Free)",
        },
        "it": {
            "title": "Come Pubblicare il Tuo Audiolibro come Podcast Privato — Guida Gratis | Audiobook Maker",
            "desc": "Scopri come trasformare i capitoli del tuo audiolibro M4B o MP3 in un feed podcast RSS privato. Hosting gratuito con Netlify, configurazione passo-passo per Apple Podcasts, Pocket Casts e altre app.",
            "kw": "podcast privato audiolibro, feed rss podcast gratis, hosting podcast netlify, audiolibro come podcast, creare podcast da audiolibro, apple podcasts feed privato, ascoltare libro come podcast",
            "h1": "Come Pubblicare il Tuo Audiolibro come Podcast Privato (Gratis)",
        },
        "fr": {
            "title": "Comment Publier Votre Livre Audio en Podcast Privé — Guide Gratuit | Audiobook Maker",
            "desc": "Apprenez à transformer les chapitres de votre livre audio M4B ou MP3 en flux RSS podcast privé. Hébergement gratuit avec Netlify, configuration pas à pas pour Apple Podcasts, Pocket Casts et plus.",
            "kw": "podcast privé livre audio, flux rss podcast gratuit, hébergement podcast netlify, livre audio en podcast, créer podcast depuis livre audio, apple podcasts flux privé",
            "h1": "Comment Publier Votre Livre Audio en Podcast Privé (Gratuit)",
        },
        "es": {
            "title": "Cómo Publicar Tu Audiolibro como Podcast Privado — Guía Gratis | Audiobook Maker",
            "desc": "Aprende a convertir los capítulos de tu audiolibro M4B o MP3 en un feed RSS de podcast privado. Hosting gratuito con Netlify, configuración paso a paso para Apple Podcasts, Pocket Casts y más.",
            "kw": "podcast privado audiolibro, feed rss podcast gratis, hosting podcast netlify, audiolibro a podcast, crear podcast desde audiolibro, apple podcasts feed privado",
            "h1": "Cómo Publicar Tu Audiolibro como Podcast Privado (Gratis)",
        },
        "de": {
            "title": "So veröffentlichen Sie Ihr Hörbuch als privaten Podcast — Kostenlose Anleitung | Audiobook Maker",
            "desc": "Erfahren Sie, wie Sie Ihre Hörbuchkapitel (M4B oder MP3) in einen privaten Podcast-RSS-Feed verwandeln. Kostenloses Hosting mit Netlify, Schritt-für-Schritt für Apple Podcasts, Pocket Casts und mehr.",
            "kw": "privater podcast hörbuch, rss feed podcast kostenlos, netlify podcast hosting, hörbuch als podcast, podcast aus hörbuch erstellen, apple podcasts privater feed",
            "h1": "Hörbuch als privaten Podcast veröffentlichen (Kostenlos)",
        },
        "zh": {
            "title": "如何将有声书发布为私人播客 — 免费指南 | Audiobook Maker",
            "desc": "了解如何将M4B或MP3有声书章节转换为私人播客RSS订阅源。通过Netlify免费托管，Apple Podcasts、Pocket Casts等应用的分步设置指南。",
            "kw": "私人播客有声书, rss订阅源免费, netlify播客托管, 有声书转播客, 创建播客从有声书, apple podcasts私人订阅源",
            "h1": "如何将有声书发布为私人播客（免费）",
        },
        "hi": {
            "title": "अपनी ऑडियोबुक को निजी पॉडकास्ट के रूप में कैसे प्रकाशित करें — मुफ़्त गाइड | Audiobook Maker",
            "desc": "जानें कि अपने M4B या MP3 ऑडियोबुक अध्यायों को एक निजी पॉडकास्ट RSS फ़ीड में कैसे बदलें. Netlify के साथ मुफ़्त होस्टिंग, Apple Podcasts, Pocket Casts और अन्य के लिए चरण-दर-चरण सेटअप.",
            "kw": "निजी पॉडकास्ट ऑडियोबुक, मुफ़्त पॉडकास्ट rss फ़ीड, ऑडियोबुक को पॉडकास्ट के रूप में होस्ट करें, netlify पॉडकास्ट होस्टिंग, ऑडियोबुक से पॉडकास्ट, मुफ़्त पॉडकास्ट होस्टिंग, apple podcasts निजी फ़ीड",
            "h1": "अपनी ऑडियोबुक को निजी पॉडकास्ट के रूप में कैसे प्रकाशित करें (मुफ़्त)",
        },
    },
}

# ── Guide body content (English only; other languages use EN as fallback) ─────

_GUIDE_BODY_EN = {
    "free-ebooks": """
<section>
<h2>Where to Find Free Ebooks to Download</h2>
<p>Thousands of great books are completely free and legal to download — classics in the public domain, modern titles released under open licenses, and community projects. Once you have a free EPUB, you can turn it into an audiobook in minutes with <a href="/">Audiobook Maker</a>. This guide lists the best sources for free ebooks and shows you how to listen to them.</p>
</section>

<section>
<h2>The 8 Best Sites for Free Ebooks</h2>
<ul>
<li><a href="https://www.gutenberg.org" target="_blank" rel="noopener">Project Gutenberg</a> — Over 70,000 free public domain books. The world's largest and oldest collection, with reliable EPUB downloads.</li>
<li><a href="https://standardebooks.org" target="_blank" rel="noopener">Standard Ebooks</a> — Carefully curated, beautifully formatted editions of classics with modern typography and original covers.</li>
<li><a href="https://archive.org/details/texts" target="_blank" rel="noopener">Internet Archive</a> — A massive digital library with millions of texts, audiobooks, and historical periodicals.</li>
<li><a href="https://manybooks.net" target="_blank" rel="noopener">ManyBooks</a> — Over 50,000 free ebooks with a modern interface and personalized reading recommendations.</li>
<li><a href="https://www.feedbooks.com/publicdomain" target="_blank" rel="noopener">Feedbooks</a> — An elegant catalog of public domain ebooks with direct, no-fuss downloads.</li>
<li><a href="https://books.google.com/books?&as_ebook=on&as_brr=1" target="_blank" rel="noopener">Google Books</a> — Millions of digitized books; filter by "Free Google eBooks" to find free titles.</li>
<li><a href="https://www.liberliber.it/online/opere/libri/" target="_blank" rel="noopener">Liber Liber</a> — The reference for Italian literature classics: Dante, Manzoni, Pirandello and many more.</li>
<li><a href="https://openlibrary.org/read" target="_blank" rel="noopener">Open Library</a> — Free digital lending of modern and classic ebooks, run by the Internet Archive.</li>
</ul>
</section>

<section>
<h2>Public Domain vs. Copyrighted Books</h2>
<p><strong>Public domain</strong> books — typically works whose author died more than 70 years ago — are free to download, share, and convert without restriction. Project Gutenberg, Standard Ebooks, and Liber Liber specialize in these.</p>
<p><strong>Copyrighted</strong> books are protected even when offered for free. Many authors and publishers release modern titles under <a href="https://creativecommons.org" target="_blank" rel="noopener">Creative Commons</a> licenses or as free promotions — these are perfectly legal to download. Avoid pirate sites that share commercial ebooks without permission: they are illegal and often bundle malware.</p>
</section>

<section>
<h2>How to Turn a Free Ebook Into an Audiobook</h2>
<ol>
<li><strong>Download the EPUB</strong> from any of the sites above (EPUB is preferred over PDF for cleaner chapter detection).</li>
<li><strong>Open <a href="/">Audiobook Maker</a></strong> and upload the file — chapters, title, author, and cover are extracted automatically.</li>
<li><strong>Choose a neural AI voice</strong> from 400+ options across 50+ languages and preview a free sample.</li>
<li><strong>Pick your format</strong> — MP3 for maximum compatibility, or <a href="/guide/m4b-format/">M4B</a> with embedded chapters and cover art.</li>
<li><strong>Generate and download</strong> — listen on your phone, tablet, or any audiobook player.</li>
</ol>
<p>See the full <a href="/guide/epub-to-audiobook/">EPUB to audiobook guide →</a> for details.</p>
</section>

<section>
<h2>Tips for Choosing the Right Free Ebook</h2>
<ul>
<li><strong>Prefer EPUB over PDF</strong>: EPUB has a clean chapter structure, while PDFs can include headers, page numbers, and layout artifacts that need cleanup.</li>
<li><strong>Check the edition</strong>: Standard Ebooks and Liber Liber offer the best-formatted versions of classics — fewer typos and OCR errors.</li>
<li><strong>Use AI text optimization</strong>: For PDFs or rough scans, Audiobook Maker's optional AI cleanup removes footnotes, hyphenation, and artifacts before narration.</li>
<li><strong>Mind the language</strong>: Pick a voice that matches the book's language for natural pronunciation.</li>
</ul>
</section>

<section>
<h2>Frequently Asked Questions</h2>
<details><summary>Is it legal to download free ebooks?</summary>
<p>Yes, when the book is in the public domain or offered for free by the author or publisher. All sites listed in this guide distribute books legally. Avoid pirate sites that share copyrighted commercial titles without permission.</p>
</details>
<details><summary>What's the best format to download for making an audiobook?</summary>
<p>EPUB is best — it has a clean chapter structure that converts reliably. PDF also works but may need AI text optimization to remove layout artifacts. TXT is fine for plain text without chapters.</p>
</details>
<details><summary>Can I convert these free ebooks to audiobooks for free?</summary>
<p>Yes. Audiobook Maker converts EPUB, PDF, and TXT to MP3 or M4B audiobooks for free using neural TTS voices, with no signup and no usage limits.</p>
</details>
<details><summary>Where can I find free ebooks in languages other than English?</summary>
<p>Project Gutenberg and Internet Archive host books in dozens of languages. Liber Liber specializes in Italian, and Google Books lets you filter free titles by language. Audiobook Maker then narrates them in 50+ languages.</p>
</details>
</section>
""",

    "epub-to-audiobook": """
<section>
<h2>Why Convert EPUB to Audiobook?</h2>
<p>EPUB is the most popular ebook format, used by Apple Books, Google Play Books, Kobo, and most digital libraries. Converting EPUB to audiobook lets you <strong>listen to your ebooks</strong> while commuting, exercising, or doing chores. Modern AI text-to-speech voices sound remarkably natural — far better than robotic screen readers.</p>
<p>With <a href="/">Audiobook Maker</a>, you can convert any DRM-free EPUB to MP3 or M4B audiobook for free, directly in your browser. No software to install, no account required.</p>
</section>

<section>
<h2>How to Convert EPUB to Audiobook — Step by Step</h2>
<ol>
<li><strong>Upload your EPUB file</strong> — Drag and drop or click to select. The tool automatically extracts chapters and metadata (title, author, cover).</li>
<li><strong>Choose your TTS voice</strong> — Select from 400+ neural AI voices across 50+ languages. Preview a short sample before committing to the full conversion.</li>
<li><strong>Select chapters</strong> — Pick which chapters to include. Skip the table of contents, copyright pages, or any sections you don't want narrated.</li>
<li><strong>Pick output format</strong> — Choose <strong>MP3</strong> (single file or ZIP per chapter), <strong>M4B</strong> (single file with embedded chapters and cover art — ideal for Apple Books and audiobook players), or <strong>Podcast RSS</strong> (private podcast feed).</li>
<li><strong>Click "Generate"</strong> — The TTS engine narrates each chapter. You'll get a progress bar and optional email notification when done.</li>
<li><strong>Download and listen</strong> — Download your audiobook and start listening on any device.</li>
</ol>
</section>

<section>
<h2>Best Voices for EPUB to Audiobook Conversion</h2>
<p>Audiobook Maker uses <strong>Microsoft Edge neural TTS</strong> (the same engine behind Azure Cognitive Services). These are the most natural-sounding free voices available:</p>
<ul>
<li><strong>English (US)</strong>: Aria, Jenny, Guy, Davis, Jane — warm, expressive narration</li>
<li><strong>English (UK)</strong>: Sonia, Ryan, Libby — excellent for British literature</li>
<li><strong>Italian</strong>: Isabella, Diego, Elsa — natural Italian narration</li>
<li><strong>French</strong>: Denise, Henri — clear French pronunciation</li>
<li><strong>German</strong>: Katja, Conrad — crisp German speech</li>
<li><strong>Spanish</strong>: Elvira, Alvaro — fluent Spanish narration</li>
<li><strong>Chinese</strong>: Xiaoxiao, Yunyang — natural Mandarin speech</li>
</ul>
<p>Google Cloud TTS Chirp3-HD is also available for even higher quality (first 1 million characters free per month).</p>
</section>

<section>
<h2>EPUB to MP3 vs EPUB to M4B: Which Format Should You Choose?</h2>
<p><strong>MP3</strong> is universally compatible — every phone, tablet, and computer plays MP3 files. Choose MP3 if you want maximum compatibility or plan to listen on multiple devices.</p>
<p><strong>M4B</strong> is the professional audiobook format. It's a single file that contains all chapters as navigation markers, plus embedded cover art and metadata (author, title, genre). M4B files are supported by Apple Books, Audible, and most dedicated audiobook apps. <a href="/guide/m4b-format/">Learn more about the M4B format →</a></p>
</section>

<section>
<h2>Tips for the Best EPUB to Audiobook Experience</h2>
<ul>
<li><strong>Remove DRM first</strong>: Commercial ebooks from Kindle, Apple Books, or Kobo often have DRM protection. You'll need to remove it before conversion (for personal use only, where legally permitted).</li>
<li><strong>Clean the text</strong>: Some EPUBs have formatting artifacts (page numbers, headers, footnotes). Audiobook Maker's optional AI text optimization can clean these up automatically.</li>
<li><strong>Preview before full generation</strong>: Always generate the free preview first to check voice quality and pacing.</li>
<li><strong>Use the chapter selector</strong>: Skip front matter (TOC, preface) and back matter (index, ads) for a cleaner listening experience.</li>
<li><strong>Choose M4B for long books</strong>: The M4B format keeps everything organized in one file with chapter navigation — much better than juggling multiple MP3 files.</li>
</ul>
</section>

<section>
<h2>Frequently Asked Questions</h2>
<details><summary>Is it really free to convert EPUB to audiobook?</summary>
<p>Yes. Audiobook Maker is open-source software (AGPL-3.0). TTS conversion uses Microsoft Edge TTS which is free with no usage limits. The optional AI text optimization (DeepSeek LLM) has a small cost above a free threshold.</p>
</details>
<details><summary>Can I convert Kindle books to audiobooks?</summary>
<p>Kindle books use Amazon's proprietary AZW/KFX format with DRM. You'll need to remove the DRM and convert to EPUB first using a tool like Calibre, then upload the EPUB to Audiobook Maker.</p>
</details>
<details><summary>How long does EPUB to audiobook conversion take?</summary>
<p>Approximately 2-3 minutes per chapter (varies by chapter length and server load). A typical 300-page book (~20 chapters) takes about 40-60 minutes. You'll receive an email notification when it's done.</p>
</details>
<details><summary>What languages are supported?</summary>
<p>50+ languages including English, Italian, French, Spanish, German, Chinese, Japanese, Korean, Portuguese, Russian, Arabic, Hindi, and many more. Each language has multiple voice options.</p>
</details>
<details><summary>Does Audiobook Maker work on mobile?</summary>
<p>Yes. The web app works in any modern browser on desktop, tablet, or phone. However, for large EPUB files, a desktop browser is recommended for faster upload and processing.</p>
</details>
</section>
""",

    "m4b-format": """
<section>
<h2>What is the M4B Format?</h2>
<p><strong>M4B</strong> (MPEG-4 Audiobook) is the standard file format for audiobooks. Based on the MPEG-4 container (same family as MP4 video), M4B is essentially an AAC audio file with special features designed specifically for audiobooks:</p>
<ul>
<li><strong>Chapter markers</strong>: Embedded navigation points let you jump between chapters</li>
<li><strong>Cover art</strong>: The book cover is embedded in the file metadata</li>
<li><strong>Bookmarks</strong>: Audiobook players remember your listening position (even across devices with iCloud)</li>
<li><strong>Metadata</strong>: Title, author, narrator, genre, and publication date are all stored in the file</li>
<li><strong>Variable speed</strong>: Players can speed up or slow down playback without changing pitch</li>
</ul>
<p>M4B is the format used by <strong>Apple Books</strong>, <strong>Audible</strong> (Aax is a DRM-protected M4B variant), and most dedicated audiobook apps on iOS and Android.</p>
</section>

<section>
<h2>M4B vs MP3 for Audiobooks: Full Comparison</h2>
<table>
<thead><tr><th>Feature</th><th>M4B</th><th>MP3</th></tr></thead>
<tbody>
<tr><td>Chapter navigation</td><td>Built-in chapter markers</td><td>No built-in chapters</td></tr>
<tr><td>Cover art</td><td>Embedded in file</td><td>Can be embedded (ID3) but not universally supported</td></tr>
<tr><td>Position saving</td><td>Yes (all M4B players)</td><td>Depends on player</td></tr>
<tr><td>File size (same quality)</td><td>~30-40% smaller (AAC codec)</td><td>Larger at same quality</td></tr>
<tr><td>Compatibility</td><td>Apple Books, Audible, BookPlayer, Listen, most audiobook apps</td><td>Universal — every device</td></tr>
<tr><td>Single file</td><td>Yes — entire book in one file</td><td>Usually one file per chapter or one combined file</td></tr>
<tr><td>Bookmarks sync</td><td>Yes (Apple ecosystem)</td><td>No</td></tr>
<tr><td>Best for</td><td>iOS/Mac users, audiobook collectors, long books</td><td>Maximum compatibility, sharing, simple players</td></tr>
</tbody>
</table>
<p><strong>Bottom line:</strong> Choose M4B if you use Apple Books or a dedicated audiobook app. Choose MP3 if you need to play the file on a basic MP3 player or car stereo that doesn't support M4B.</p>
</section>

<section>
<h2>How to Create M4B Files with Chapters — Free</h2>
<p>Creating M4B files used to require complex ffmpeg commands or paid software. <a href="/">Audiobook Maker</a> automates the entire process:</p>
<ol>
<li><strong>Upload your ebook</strong> (EPUB, PDF, or TXT) — chapters are extracted automatically</li>
<li><strong>Select M4B as output format</strong> — the tool handles everything: TTS narration, AAC encoding, chapter markers, cover art embedding</li>
<li><strong>Download the M4B file</strong> — ready to import into Apple Books or any M4B-compatible player</li>
</ol>
<p>The generated M4B uses <strong>AAC audio at 64 kbps</strong> (optimized for speech), includes <strong>1400×1400 cover art</strong>, and has proper iTunes-compatible metadata tags. Each chapter appears as a navigation point in your audiobook player.</p>
</section>

<section>
<h2>How to Play M4B Files</h2>
<p><strong>iOS / Mac:</strong> Apple Books (built-in) — drag the M4B into Books or sync via Finder/iCloud.</p>
<p><strong>Android:</strong> Listen Audiobook Player, Smart Audiobook Player, Sirin — all support M4B with chapters.</p>
<p><strong>Windows:</strong> Apple Books (via iTunes), VLC media player, BookPlayer (Microsoft Store).</p>
<p><strong>Linux:</strong> VLC, Cozy (GTK audiobook player).</p>
<p><strong>Car / Basic MP3 player:</strong> Convert to MP3 instead — most car stereos don't read M4B files.</p>
</section>

<section>
<h2>Frequently Asked Questions</h2>
<details><summary>Can I convert M4B to MP3?</summary>
<p>Yes. You can use Audiobook Maker to generate MP3 output instead, or use ffmpeg to convert an existing M4B: <code>ffmpeg -i book.m4b -acodec libmp3lame -b:a 128k book.mp3</code>. Note that chapter markers are lost in the conversion.</p>
</details>
<details><summary>Can I split an M4B into chapters?</summary>
<p>Yes. Tools like <code>m4b-tool</code> or ffmpeg can split M4B files at chapter markers. Audiobook Maker can also output individual MP3 files per chapter if you prefer separate files.</p>
</details>
<details><summary>What audiobook apps support M4B?</summary>
<p>Apple Books (iOS/Mac), BookPlayer (iOS), Listen Audiobook Player (Android), Smart Audiobook Player (Android), Bound (iOS), Sirin (Android), VLC (all platforms), and Plex with the Audnexus plugin.</p>
</details>
<details><summary>What bitrate should I use for M4B audiobooks?</summary>
<p>Audiobook Maker uses 64 kbps AAC, which is the standard for spoken-word content. Speech doesn't need high bitrates — 64 kbps AAC sounds identical to 128 kbps MP3 for narration, but uses half the file size.</p>
</details>
</section>
""",

    "text-to-speech-audiobook": """
<section>
<h2>What is Text-to-Speech Audiobook Creation?</h2>
<p>Text-to-speech (TTS) audiobook creation uses AI neural voices to narrate written text into spoken audio. Unlike old robotic TTS, modern neural voices sound remarkably natural — with proper intonation, pacing, and emotion. You can now <strong>turn any text, ebook, or document into a professional-sounding audiobook</strong> without hiring a human narrator.</p>
<p><a href="/">Audiobook Maker</a> combines the best free TTS engines with an easy-to-use web interface. Upload EPUB, PDF, or TXT files and get MP3, M4B, or Podcast RSS output — all for free.</p>
</section>

<section>
<h2>Best Free TTS Engines for Audiobook Creation (2026)</h2>
<table>
<thead><tr><th>TTS Engine</th><th>Voices</th><th>Languages</th><th>Cost</th><th>Best For</th></tr></thead>
<tbody>
<tr><td><strong>Microsoft Edge TTS</strong></td><td>400+</td><td>50+</td><td>Free</td><td>General audiobook creation, most natural free voices</td></tr>
<tr><td><strong>Google Cloud TTS (Chirp3-HD)</strong></td><td>50+</td><td>30+</td><td>1M chars free/month, then paid</td><td>Premium quality, expressive narration</td></tr>
<tr><td><strong>Speechify</strong></td><td>30+</td><td>20+</td><td>Freemium (limited)</td><td>Quick article reading, mobile use</td></tr>
<tr><td><strong>NaturalReader</strong></td><td>100+</td><td>20+</td><td>Freemium (limited)</td><td>Dyslexia support, education</td></tr>
<tr><td><strong>ElevenLabs</strong></td><td>Custom</td><td>30+</td><td>10K chars free/month</td><td>Ultra-realistic voice cloning</td></tr>
<tr><td><strong>Play.ht</strong></td><td>800+</td><td>140+</td><td>5K chars free/month</td><td>Multi-language, voice variety</td></tr>
</tbody>
</table>
<p><strong>Audiobook Maker uses Microsoft Edge TTS by default</strong> — it's completely free, has no usage limits, and offers 400+ voices. Google TTS Chirp3-HD is available for users who want premium quality. Unlike Speechify or NaturalReader, Audiobook Maker has <strong>no paywalls, no registration, and no usage caps</strong>.</p>
</section>

<section>
<h2>PREMIUM Voices: Gemini TTS Model Comparison (Flash 2.5 vs 3.1)</h2>
<p>For those seeking the highest audio quality, Audiobook Maker offers <strong>PREMIUM Voices</strong> powered by two state-of-the-art Google Gemini Text-to-Speech models. Both models produce audio with highly expressive neural voices, support <strong>30 multilingual voices</strong> (each voice speaks 24 languages fluently), and allow customization of <strong>narration style</strong> and <strong>reading speed</strong> (±30%).</p>

<table>
<thead><tr><th>Feature</th><th>Gemini 2.5 Flash</th><th>Gemini 3.1 Flash</th></tr></thead>
<tbody>
<tr><td><strong>Generation</strong></td><td>Second generation</td><td>Third generation (newer)</td></tr>
<tr><td><strong>Audio quality</strong></td><td>Very good — natural, clean narration</td><td>Excellent — richer expressiveness, superior intonation and prosody</td></tr>
<tr><td><strong>Synthesis speed</strong></td><td>Faster — suitable for long books</td><td>Slower — prioritizes quality over speed</td></tr>
<tr><td><strong>Approximate cost per minute</strong></td><td>~€0.025/min (more affordable)</td><td>~€0.036/min (premium quality)</td></tr>
<tr><td><strong>Narration style</strong></td><td>Customizable with text instructions (up to 200 characters)</td><td>Customizable with text instructions (up to 200 characters)</td></tr>
<tr><td><strong>Reading speed</strong></td><td>Adjustable from -30% to +30%</td><td>Adjustable from -30% to +30%</td></tr>
<tr><td><strong>Best for</strong></td><td>Non-fiction, manuals, simple fiction, very long books, tight budget</td><td>Complex fiction, dialogue-heavy books, audiobooks requiring maximum emotional expressiveness</td></tr>
</tbody>
</table>

<p><strong>Which one to choose?</strong> If budget or book length is your priority, <strong>Gemini 2.5 Flash</strong> offers excellent value with faster generation times. If you want the highest possible audio quality, with richer intonation and more engaging narration — especially for novels with dialogue and characters — <strong>Gemini 3.1 Flash</strong> represents the state of the art in neural speech synthesis.</p>

<p>Both models are available in the <strong>"PREMIUM Voices"</strong> tab of the generation panel. The exact cost, calculated based on your book's character count and the selected model, is shown in real time before payment. You can pay via PayPal or use a voucher code.</p>
</section>

<section>
<h2>Speechify Alternative: Why Choose Audiobook Maker?</h2>
<p>Speechify is a popular TTS app, but its free tier is very limited. Here's how Audiobook Maker compares:</p>
<ul>
<li><strong>100% free</strong> vs Speechify's $139/year premium</li>
<li><strong>No usage limits</strong> — convert entire books, not just short texts</li>
<li><strong>M4B output with chapters</strong> — Speechify only exports plain audio</li>
<li><strong>Podcast RSS feeds</strong> — listen in any podcast app</li>
<li><strong>Open source</strong> — AGPL-3.0 licensed, you can inspect and modify the code</li>
<li><strong>Self-hosted option</strong> — run it on your own server for complete privacy</li>
<li><strong>AI text optimization</strong> — automatically cleans and improves text for better narration</li>
</ul>
<p>If you need a <strong>free Speechify alternative</strong> for full-length books, Audiobook Maker is the best option available.</p>
</section>

<section>
<h2>How to Create an Audiobook with AI Voices — Step by Step</h2>
<ol>
<li><strong>Upload your file</strong> — EPUB, PDF, or plain text (TXT). The tool auto-detects chapters and extracts metadata.</li>
<li><strong>Choose a voice</strong> — Browse 400+ neural voices. Each voice has a short preview so you can hear it before converting.</li>
<li><strong>Select output format</strong> — MP3 for universal compatibility, M4B for Apple Books with chapters, or Podcast RSS for streaming.</li>
<li><strong>Generate</strong> — The AI narrates your book chapter by chapter. Progress is shown in real-time.</li>
<li><strong>Download & listen</strong> — Get your audiobook as a single file, ZIP of chapters, or subscribe to the private podcast feed.</li>
</ol>
</section>

<section>
<h2>Free TTS Audiobook vs Hiring a Human Narrator</h2>
<table>
<thead><tr><th>Aspect</th><th>AI TTS (Audiobook Maker)</th><th>Human Narrator</th></tr></thead>
<tbody>
<tr><td>Cost</td><td>Free</td><td>$500-$5,000+ per book</td></tr>
<tr><td>Time</td><td>~1 hour</td><td>2-6 weeks</td></tr>
<tr><td>Quality</td><td>Very good (neural, natural)</td><td>Excellent (human expression)</td></tr>
<tr><td>Languages</td><td>50+ instantly</td><td>One language per narrator</td></tr>
<tr><td>Revisions</td><td>Instant re-generation</td><td>Re-recording needed</td></tr>
<tr><td>Best for</td><td>Personal use, proofs, indie authors on a budget</td><td>Commercial audiobooks for sale (Audible, etc.)</td></tr>
</tbody>
</table>
<p>For personal listening, proofreading your own writing, or creating audiobook versions of public domain books, AI TTS is the clear winner. For commercial audiobooks intended for sale on Audible, a human narrator is still preferred (and required by ACX).</p>
</section>

<section>
<h2>Frequently Asked Questions</h2>
<details><summary>Is AI text-to-speech good enough for audiobooks?</summary>
<p>Yes. Modern neural TTS (like Microsoft Edge TTS and Google Chirp3-HD) is remarkably natural. Most listeners can't tell the difference from a human narrator for non-fiction. For fiction with multiple characters and emotional range, human narration is still superior — but the gap is closing fast.</p>
</details>
<details><summary>Can I use AI-generated audiobooks commercially?</summary>
<p>Yes, with caveats. Microsoft Edge TTS and Google TTS allow commercial use of generated audio. However, platforms like Audible (ACX) currently require human narration for new submissions. AI audiobooks can be sold on other platforms or used for personal projects, YouTube videos, and educational content.</p>
</details>
<details><summary>How many characters can I convert for free?</summary>
<p>With Microsoft Edge TTS: unlimited. There are no usage caps or quotas. With Google Cloud TTS Chirp3-HD: 1 million characters per month free, then standard Google Cloud pricing applies.</p>
</details>
<details><summary>Does Audiobook Maker work offline?</summary>
<p>The hosted version at audiobook-maker.com requires an internet connection. However, the software is open source — you can install it on your own computer or server and run it locally with full offline capability.</p>
</details>
<details><summary>What's the best TTS voice for audiobooks?</summary>
<p>For English, the top Edge TTS voices are <strong>Aria</strong> (warm female), <strong>Davis</strong> (deep male), and <strong>Jenny</strong> (friendly female). For premium quality, Google Chirp3-HD offers the most expressive neural voices. <a href="/">Try the free preview on Audiobook Maker</a> to find your favorite.</p>
</details>
</section>
""",

    "gemini-tts": """
<p>Gemini TTS is the neural engine behind Audiobook Maker's PREMIUM voices. This guide covers the available voices, supported languages, and how to steer delivery with prompts.</p>

<h2 id="voices">Voice options</h2>
<p>30 distinct voices, each with its own character. The voice name is fixed; the descriptor summarises its natural tone.</p>
<table>
  <thead><tr><th>Voice</th><th>Character</th></tr></thead>
  <tbody>
    <tr><td>Zephyr</td><td>Bright</td></tr>
    <tr><td>Puck</td><td>Upbeat</td></tr>
    <tr><td>Charon</td><td>Informative</td></tr>
    <tr><td>Kore</td><td>Firm</td></tr>
    <tr><td>Fenrir</td><td>Excitable</td></tr>
    <tr><td>Leda</td><td>Youthful</td></tr>
    <tr><td>Orus</td><td>Firm</td></tr>
    <tr><td>Aoede</td><td>Breezy</td></tr>
    <tr><td>Callirrhoe</td><td>Easy-going</td></tr>
    <tr><td>Autonoe</td><td>Bright</td></tr>
    <tr><td>Enceladus</td><td>Breathy</td></tr>
    <tr><td>Iapetus</td><td>Clear</td></tr>
    <tr><td>Umbriel</td><td>Easy-going</td></tr>
    <tr><td>Algieba</td><td>Smooth</td></tr>
    <tr><td>Despina</td><td>Smooth</td></tr>
    <tr><td>Erinome</td><td>Clear</td></tr>
    <tr><td>Algenib</td><td>Gravelly</td></tr>
    <tr><td>Rasalgethi</td><td>Informative</td></tr>
    <tr><td>Laomedeia</td><td>Upbeat</td></tr>
    <tr><td>Achernar</td><td>Soft</td></tr>
    <tr><td>Alnilam</td><td>Firm</td></tr>
    <tr><td>Schedar</td><td>Even</td></tr>
    <tr><td>Gacrux</td><td>Mature</td></tr>
    <tr><td>Pulcherrima</td><td>Forward</td></tr>
    <tr><td>Achird</td><td>Friendly</td></tr>
    <tr><td>Zubenelgenubi</td><td>Casual</td></tr>
    <tr><td>Vindemiatrix</td><td>Gentle</td></tr>
    <tr><td>Sadachbia</td><td>Lively</td></tr>
    <tr><td>Sadaltager</td><td>Knowledgeable</td></tr>
    <tr><td>Sulafat</td><td>Warm</td></tr>
  </tbody>
</table>

<h2 id="languages">Supported languages</h2>
<p>Gemini TTS supports the following languages (BCP-47 code in parentheses):</p>
<p>Arabic (ar), Filipino (fil), Bangla (bn), Finnish (fi), Dutch (nl), Galician (gl), English (en), Georgian (ka), French (fr), Greek (el), German (de), Gujarati (gu), Hindi (hi), Haitian Creole (ht), Indonesian (id), Hebrew (he), Italian (it), Hungarian (hu), Japanese (ja), Icelandic (is), Korean (ko), Javanese (jv), Marathi (mr), Kannada (kn), Polish (pl), Konkani (kok), Portuguese (pt), Romanian (ro), Russian (ru), Spanish (es), Tamil (ta), Telugu (te), Thai (th), Turkish (tr), Ukrainian (uk), Vietnamese (vi), Afrikaans (af), Albanian (sq), Amharic (am), Armenian (hy), Azerbaijani (az), Basque (eu), Belarusian (be), Bulgarian (bg), Burmese (my), Catalan (ca), Cebuano (ceb), Chinese Mandarin (cmn), Croatian (hr), Czech (cs), Danish (da), Estonian (et), Latvian (lv), Lithuanian (lt), Luxembourgish (lb), Macedonian (mk), Maithili (mai), Malagasy (mg), Malay (ms), Malayalam (ml), Mongolian (mn), Nepali (ne), Norwegian Bokm&aring;l (nb), Norwegian Nynorsk (nn), Odia (or), Pashto (ps), Persian (fa), Punjabi (pa), Serbian (sr), Sindhi (sd), Sinhala (si), Slovak (sk), Slovenian (sl), Swahili (sw), Swedish (sv), Urdu (ur).</p>

<h2 id="prompting">Prompting guide</h2>
<p>The model infers delivery from the transcript automatically. You can steer it further with inline tags and structured directions.</p>
<h3>Inline audio tags</h3>
<p>Inline modifiers such as <code>[whispers]</code>, <code>[laughs]</code>, <code>[excitedly]</code>, <code>[bored]</code> and <code>[shouting]</code> change tone, pace and emotional quality. Be creative and experiment with delivery variations.</p>
<h3>Advanced prompting elements</h3>
<ul>
  <li><strong>Audio Profile</strong> &mdash; character name and role definition.</li>
  <li><strong>Scene</strong> &mdash; environmental context that sets mood and physical setting.</li>
  <li><strong>Director&rsquo;s Notes</strong> &mdash; performance guidance: style, pacing, accent.</li>
  <li><strong>Sample Context</strong> &mdash; contextual grounding for a natural entry into the performance.</li>
  <li><strong>Transcript</strong> &mdash; the exact spoken words, paired with audio tags.</li>
</ul>
<h3>Key guidance</h3>
<p>Don't feel you have to describe everything &mdash; giving the model space to fill the gaps often helps naturalness. Balance specificity with creative freedom, and prefer industry terminology and layered characteristics over plain emotional labels.</p>
<h3>How to use prompts in Audiobook Maker</h3>
<p>Audiobook Maker narrates the chapter text directly, so you add prompt cues inside the text itself, in one of two ways:</p>
<ul>
  <li>Edit the input <strong>TXT</strong> file before uploading, inserting tags/cues directly in the text.</li>
  <li>Or download the generated <strong>.ABM</strong> file, edit the chapter texts, and re-upload the modified <strong>.ABM</strong> to Audiobook Maker.</li>
</ul>
<p style="font-size:.85rem;color:var(--txm)">Source: <a href="https://ai.google.dev/gemini-api/docs/speech-generation" rel="nofollow noopener" target="_blank">Google AI &mdash; Speech generation</a></p>
""",

    "podcast": '''
<section>
<h2>Turn Your Audiobook into a Private Podcast</h2>
<p>Audiobook Maker generates, alongside audio files, a <strong>complete podcast package</strong> with an RSS 2.0 feed. To make it available as a podcast, the files need to be published on a web server accessible from the Internet. The ideal solution is your <strong>own website</strong> or hosting space. Alternatively, for personal use or sharing with a few friends, you can use a free solution like <strong>Netlify</strong>, described in this guide.</p>
<div style="background:#fff3cd;border-left:4px solid #f0c040;padding:10px 14px;border-radius:6px;margin:0 0 18px;font-size:.92rem;color:#5a4510"><strong>Recommended use:</strong> this solution is designed for personal use or sharing with friends and family. Netlify offers 100 GB/month of free bandwidth — more than enough. For public distribution, consider using your own web hosting.</div>
</section>

<section>
<h2>Step by Step: Publish Your Audiobook as a Podcast</h2>
<ol>
<li><strong>Generate the audiobook in M4B format</strong> — In Audiobook Maker, upload your EPUB or PDF file, choose language and voice, then select <strong>M4B</strong> as output format. The tool creates a single M4B file with embedded chapters and cover art — the professional standard for audiobooks.</li>
<li><strong>Also generate the Podcast RSS package</strong> — After generating the M4B, run the generation again in <strong>Podcast RSS</strong> mode to get a ZIP containing the RSS feed XML file and individual MP3 chapter files (podcasts require one audio file per episode).</li>
<li><strong>Create a free Netlify account</strong> — Go to <strong>app.netlify.com</strong> and sign up with email or GitHub. No credit card required. The free plan includes 100 GB bandwidth, 10 GB storage, and automatic HTTPS.</li>
<li><strong>Upload to Netlify</strong> — In the Netlify dashboard, under <strong>Sites</strong>, drag the entire extracted folder onto the dashed drop zone. The site goes live in seconds. Then rename it from <em>Site configuration → Change site name</em> (e.g. <code>my-audiobook.netlify.app</code>).</li>
<li><strong>Verify the feed</strong> — Open the feed URL in your browser: <br><code>https://your-site-name.netlify.app/podcast.xml</code><br>If you see XML content with your chapter titles, your podcast is live and ready!</li>
</ol>
</section>

<section>
<h2>Import Your Podcast into Listening Apps</h2>
<table>
<thead><tr><th>App</th><th>Platform</th><th>How to Add</th></tr></thead>
<tbody>
<tr><td><strong>Apple Podcasts</strong></td><td>iOS / Mac</td><td><strong>iPhone:</strong> Library → More → Add Show by URL → paste feed URL<br><strong>Mac:</strong> File → Follow a Show by URL</td></tr>
<tr><td><strong>Pocket Casts</strong></td><td>Android / iOS / Web</td><td>Search → paste feed URL → Subscribe</td></tr>
<tr><td><strong>AntennaPod</strong></td><td>Android</td><td>+ → Add Podcast by URL → paste URL</td></tr>
<tr><td><strong>Overcast</strong></td><td>iOS</td><td>+ → Add URL → paste feed URL</td></tr>
<tr><td><strong>Podcast Addict</strong></td><td>Android</td><td>+ → RSS Feed → paste URL</td></tr>
</tbody>
</table>
<div style="background:#fff0f0;border-left:4px solid #e04040;padding:8px 14px;border-radius:6px;margin:12px 0;font-size:.9rem;color:#802020"><strong>Note:</strong> Spotify does not support adding private RSS feeds. Use one of the apps listed above.</div>
</section>

<section>
<h2>Why Listen to Your Audiobook as a Podcast?</h2>
<ul>
<li><strong>Auto bookmarks</strong> — Resume exactly where you left off, even across devices</li>
<li><strong>Episode ordering</strong> — Chapters play in order with automatic advance to the next</li>
<li><strong>Full metadata</strong> — Cover art, chapter titles, and book info visible in your podcast app</li>
<li><strong>Adjustable speed</strong> — Listen at 1.5x, 2x, or any speed you prefer, with sleep timer</li>
<li><strong>Streaming</strong> — No need to download all files; stream each chapter as you listen</li>
<li><strong>Share with family</strong> — Send the feed URL to family members; they do not need a Netlify account</li>
</ul>
</section>

<section>
<h2>Tips for Podcast Publishing</h2>
<ul>
<li><strong>Update episodes:</strong> Re-upload the files to Netlify to replace the previous version. Your podcast app will pick up changes on the next refresh.</li>
<li><strong>Multiple books:</strong> Create a separate Netlify site for each audiobook to keep feeds organized.</li>
<li><strong>Storage limits:</strong> Netlify free tier includes 10 GB storage (~12 full-length audiobooks). Remove finished books to free up space.</li>
<li><strong>Privacy:</strong> The podcast URL is technically public (anyone with the link can subscribe), but it will not appear in podcast directories or search engines. It is "private" in the sense that it is unlisted.</li>
<li><strong>Custom domain:</strong> Netlify supports custom domains on the free plan if you want a personalized URL.</li>
</ul>
</section>

<section>
<h2>Frequently Asked Questions</h2>
<details><summary>Is Netlify really free for hosting my podcast?</summary>
<p>Yes. Netlify's free Starter plan includes 100 GB/month bandwidth and 10 GB storage. For a typical audiobook podcast (10-20 episodes, ~5 MB each), this is more than enough for personal use. If you exceed the limits, you can upgrade to Netlify Pro ($19/month) or move to your own hosting.</p>
</details>
<details><summary>Why use M4B format instead of MP3 for the audiobook?</summary>
<p>M4B is the professional standard for audiobooks. A single M4B file contains all chapters as navigation markers, embedded cover art, and metadata. It is supported by Apple Books, Audible, and all major audiobook apps. MP3 is great for maximum compatibility, but M4B provides a much better listening experience with chapter navigation.</p>
</details>
<details><summary>Can I submit my podcast to Apple Podcasts or Spotify directories?</summary>
<p>Not with a private Netlify feed. Apple Podcasts Connect and Spotify for Podcasters require feeds hosted on approved platforms with specific requirements (artwork size, categories, etc.). The Netlify approach is for <strong>personal private podcasts only</strong> — ideal for listening to your own books or sharing with close friends and family.</p>
</details>
<details><summary>What if I do not want to use Netlify?</summary>
<p>Any static web hosting works: GitHub Pages, Cloudflare Pages, Vercel, or your own web server. Simply upload the extracted podcast folder to any web-accessible location and the RSS feed URL will work in podcast apps. Netlify is recommended because it is free, fast, and requires zero configuration.</p>
</details>
<details><summary>Can podcast apps download episodes for offline listening?</summary>
<p>Yes. Once you subscribe to the feed in a podcast app, you can download individual episodes for offline listening, just like any other podcast. The app handles download management, playback position, and deletion automatically.</p>
</details>
</section>
''',
}

_GUIDE_BODY_IT = {
    "free-ebooks": """
<section>
<h2>Dove Trovare Ebook Gratuiti da Scaricare</h2>
<p>Migliaia di ottimi libri sono completamente gratuiti e legali da scaricare — classici di pubblico dominio, titoli moderni rilasciati con licenze aperte e progetti della community. Una volta ottenuto un EPUB gratuito, puoi trasformarlo in audiolibro in pochi minuti con <a href="/">Audiobook Maker</a>. Questa guida elenca le migliori fonti di ebook gratuiti e ti mostra come ascoltarli.</p>
</section>

<section>
<h2>I 8 Migliori Siti per Ebook Gratuiti</h2>
<ul>
<li><a href="https://www.gutenberg.org" target="_blank" rel="noopener">Project Gutenberg</a> — Oltre 70.000 libri gratuiti di pubblico dominio. La più grande e antica raccolta al mondo, con download EPUB affidabili.</li>
<li><a href="https://standardebooks.org" target="_blank" rel="noopener">Standard Ebooks</a> — Edizioni curate e ben formattate di classici, con tipografia moderna e copertine originali.</li>
<li><a href="https://archive.org/details/texts" target="_blank" rel="noopener">Internet Archive</a> — Un'enorme biblioteca digitale con milioni di testi, audiolibri e riviste storiche.</li>
<li><a href="https://manybooks.net" target="_blank" rel="noopener">ManyBooks</a> — Oltre 50.000 ebook gratuiti con interfaccia moderna e consigli di lettura personalizzati.</li>
<li><a href="https://www.feedbooks.com/publicdomain" target="_blank" rel="noopener">Feedbooks</a> — Un catalogo elegante di ebook di pubblico dominio con download diretto e immediato.</li>
<li><a href="https://books.google.com/books?&as_ebook=on&as_brr=1" target="_blank" rel="noopener">Google Books</a> — Milioni di libri digitalizzati; filtra per "Ebook gratuiti" per trovare i titoli gratis.</li>
<li><a href="https://www.liberliber.it/online/opere/libri/" target="_blank" rel="noopener">Liber Liber</a> — Il riferimento per i classici della letteratura italiana: Dante, Manzoni, Pirandello e molti altri.</li>
<li><a href="https://openlibrary.org/read" target="_blank" rel="noopener">Open Library</a> — Prestito digitale gratuito di ebook moderni e classici, gestito da Internet Archive.</li>
</ul>
</section>

<section>
<h2>Pubblico Dominio vs. Libri Sotto Copyright</h2>
<p>I libri di <strong>pubblico dominio</strong> — tipicamente le opere il cui autore è morto da più di 70 anni — sono liberi da scaricare, condividere e convertire senza restrizioni. Project Gutenberg, Standard Ebooks e Liber Liber sono specializzati in questi.</p>
<p>I libri <strong>sotto copyright</strong> sono protetti anche quando offerti gratuitamente. Molti autori ed editori rilasciano titoli moderni con licenze <a href="https://creativecommons.org" target="_blank" rel="noopener">Creative Commons</a> o come promozioni gratuite: sono perfettamente legali da scaricare. Evita i siti pirata che condividono ebook commerciali senza autorizzazione: sono illegali e spesso contengono malware.</p>
</section>

<section>
<h2>Come Trasformare un Ebook Gratuito in Audiolibro</h2>
<ol>
<li><strong>Scarica l'EPUB</strong> da uno dei siti sopra (l'EPUB è preferibile al PDF per un riconoscimento dei capitoli più pulito).</li>
<li><strong>Apri <a href="/">Audiobook Maker</a></strong> e carica il file — capitoli, titolo, autore e copertina vengono estratti automaticamente.</li>
<li><strong>Scegli una voce AI neurale</strong> tra oltre 400 opzioni in più di 50 lingue e ascolta un'anteprima gratuita.</li>
<li><strong>Scegli il formato</strong> — MP3 per la massima compatibilità, oppure <a href="/guide/m4b-format/">M4B</a> con capitoli e copertina incorporati.</li>
<li><strong>Genera e scarica</strong> — ascolta su smartphone, tablet o qualsiasi lettore di audiolibri.</li>
</ol>
<p>Consulta la guida completa <a href="/guide/epub-to-audiobook/">EPUB in audiolibro →</a> per i dettagli.</p>
</section>

<section>
<h2>Consigli per Scegliere l'Ebook Gratuito Giusto</h2>
<ul>
<li><strong>Preferisci l'EPUB al PDF</strong>: l'EPUB ha una struttura dei capitoli pulita, mentre i PDF possono contenere intestazioni, numeri di pagina e artefatti di impaginazione da ripulire.</li>
<li><strong>Controlla l'edizione</strong>: Standard Ebooks e Liber Liber offrono le versioni meglio formattate dei classici, con meno refusi ed errori OCR.</li>
<li><strong>Usa l'ottimizzazione AI del testo</strong>: per PDF o scansioni grezze, la pulizia AI opzionale di Audiobook Maker rimuove note a piè di pagina, sillabazione e artefatti prima della narrazione.</li>
<li><strong>Attenzione alla lingua</strong>: scegli una voce che corrisponda alla lingua del libro per una pronuncia naturale.</li>
</ul>
</section>

<section>
<h2>Domande Frequenti</h2>
<details><summary>È legale scaricare ebook gratuiti?</summary>
<p>Sì, quando il libro è di pubblico dominio o offerto gratuitamente dall'autore o dall'editore. Tutti i siti elencati in questa guida distribuiscono libri legalmente. Evita i siti pirata che condividono titoli commerciali protetti da copyright senza autorizzazione.</p>
</details>
<details><summary>Qual è il formato migliore da scaricare per creare un audiolibro?</summary>
<p>L'EPUB è il migliore: ha una struttura dei capitoli pulita che si converte in modo affidabile. Anche il PDF funziona, ma può richiedere l'ottimizzazione AI del testo per rimuovere gli artefatti di impaginazione. Il TXT va bene per testo semplice senza capitoli.</p>
</details>
<details><summary>Posso convertire questi ebook gratuiti in audiolibri gratis?</summary>
<p>Sì. Audiobook Maker converte EPUB, PDF e TXT in audiolibri MP3 o M4B gratuitamente usando voci TTS neurali, senza registrazione e senza limiti di utilizzo.</p>
</details>
<details><summary>Dove trovo ebook gratuiti in lingue diverse dall'inglese?</summary>
<p>Project Gutenberg e Internet Archive ospitano libri in decine di lingue. Liber Liber è specializzato in italiano e Google Books permette di filtrare i titoli gratuiti per lingua. Audiobook Maker li narra poi in oltre 50 lingue.</p>
</details>
</section>
""",

    "epub-to-audiobook": """
<section>
<h2>Perché Convertire EPUB in Audiolibro?</h2>
<p>L'EPUB è il formato ebook più diffuso, utilizzato da Apple Books, Google Play Books, Kobo e dalla maggior parte delle biblioteche digitali. Convertire EPUB in audiolibro ti permette di <strong>ascoltare i tuoi ebook</strong> mentre sei in viaggio, fai sport o svolgi le faccende domestiche. Le moderne voci AI text-to-speech suonano sorprendentemente naturali, ben lontane dai robotici lettori di schermo del passato.</p>
<p>Con <a href="/">Audiobook Maker</a> puoi convertire qualsiasi EPUB senza DRM in audiolibro MP3 o M4B gratuitamente, direttamente nel tuo browser. Nessun software da installare, nessun account richiesto.</p>
</section>

<section>
<h2>Come Convertire EPUB in Audiolibro — Passo Dopo Passo</h2>
<ol>
<li><strong>Carica il tuo file EPUB</strong> — Trascina e rilascia o clicca per selezionare. Lo strumento estrae automaticamente capitoli e metadati (titolo, autore, copertina).</li>
<li><strong>Scegli la voce TTS</strong> — Seleziona tra oltre 400 voci AI neurali in più di 50 lingue. Ascolta un'anteprima prima di avviare la conversione completa.</li>
<li><strong>Seleziona i capitoli</strong> — Scegli quali capitoli includere. Salta l'indice, le pagine di copyright o qualsiasi sezione che non vuoi venga narrata.</li>
<li><strong>Scegli il formato di output</strong> — <strong>MP3</strong> (file singolo o ZIP per capitolo), <strong>M4B</strong> (file unico con capitoli e copertina incorporati — ideale per Apple Books e app audiolibri), o <strong>Podcast RSS</strong> (feed podcast privato).</li>
<li><strong>Clicca "Genera"</strong> — Il motore TTS narra ogni capitolo. Vedrai una barra di avanzamento e riceverai una notifica email quando il processo è completato.</li>
<li><strong>Scarica e ascolta</strong> — Scarica il tuo audiolibro e inizia ad ascoltarlo su qualsiasi dispositivo.</li>
</ol>
</section>

<section>
<h2>Migliori Voci per la Conversione EPUB in Audiolibro</h2>
<p>Audiobook Maker utilizza <strong>Microsoft Edge neural TTS</strong> (lo stesso motore di Azure Cognitive Services). Queste sono le voci gratuite più naturali disponibili:</p>
<ul>
<li><strong>Italiano</strong>: Isabella, Diego, Elsa — narrazione italiana naturale</li>
<li><strong>Inglese (US)</strong>: Aria, Jenny, Guy, Davis — narrazione calda ed espressiva</li>
<li><strong>Inglese (UK)</strong>: Sonia, Ryan, Libby — eccellente per letteratura britannica</li>
<li><strong>Francese</strong>: Denise, Henri — pronuncia francese chiara</li>
<li><strong>Tedesco</strong>: Katja, Conrad — parlato tedesco nitido</li>
<li><strong>Spagnolo</strong>: Elvira, Alvaro — narrazione spagnola fluente</li>
<li><strong>Cinese</strong>: Xiaoxiao, Yunyang — parlato mandarino naturale</li>
</ul>
<p>Google Cloud TTS Chirp3-HD è disponibile per qualità ancora superiore (primo milione di caratteri gratuito al mese).</p>
</section>

<section>
<h2>EPUB in MP3 vs EPUB in M4B: Quale Formato Scegliere?</h2>
<p><strong>MP3</strong> è universalmente compatibile — ogni telefono, tablet e computer riproduce file MP3. Scegli MP3 se vuoi la massima compatibilità o prevedi di ascoltare su più dispositivi.</p>
<p><strong>M4B</strong> è il formato audiolibro professionale. È un unico file che contiene tutti i capitoli come marcatori di navigazione, più copertina e metadati incorporati (autore, titolo, genere). I file M4B sono supportati da Apple Books, Audible e dalla maggior parte delle app audiolibro dedicate. <a href="/guide/m4b-format/">Scopri di più sul formato M4B →</a></p>
</section>

<section>
<h2>Consigli per la Migliore Conversione EPUB in Audiolibro</h2>
<ul>
<li><strong>Rimuovi prima il DRM</strong>: Gli ebook commerciali di Kindle, Apple Books o Kobo hanno spesso protezione DRM. Dovrai rimuoverla prima della conversione (solo per uso personale, dove legalmente consentito).</li>
<li><strong>Pulisci il testo</strong>: Alcuni EPUB hanno artefatti di formattazione (numeri di pagina, intestazioni, note a piè di pagina). L'ottimizzazione AI opzionale di Audiobook Maker può ripulirli automaticamente.</li>
<li><strong>Anteprima prima della generazione</strong>: Genera sempre l'anteprima gratuita per verificare la qualità della voce e il ritmo.</li>
<li><strong>Usa il selettore capitoli</strong>: Salta i contenuti preliminari (indice, prefazione) e finali (indice analitico, pubblicità) per un'esperienza di ascolto più pulita.</li>
<li><strong>Scegli M4B per libri lunghi</strong>: Il formato M4B mantiene tutto organizzato in un unico file con navigazione per capitolo — molto meglio che gestire decine di file MP3 separati.</li>
</ul>
</section>

<section>
<h2>Domande Frequenti</h2>
<details><summary>È davvero gratis convertire EPUB in audiolibro?</summary>
<p>Sì. Audiobook Maker è un software open source (AGPL-3.0). La conversione TTS utilizza Microsoft Edge TTS che è gratuito e senza limiti di utilizzo. L'ottimizzazione AI opzionale del testo (DeepSeek LLM) ha un piccolo costo sopra una soglia gratuita.</p>
</details>
<details><summary>Posso convertire i libri Kindle in audiolibri?</summary>
<p>I libri Kindle usano il formato proprietario AZW/KFX di Amazon con DRM. Devi rimuovere il DRM e convertire in EPUB usando uno strumento come Calibre, poi caricare l'EPUB su Audiobook Maker.</p>
</details>
<details><summary>Quanto tempo richiede la conversione EPUB in audiolibro?</summary>
<p>Circa 2-3 minuti per capitolo (varia in base alla lunghezza del capitolo e al carico del server). Un tipico libro di 300 pagine (~20 capitoli) richiede circa 40-60 minuti. Riceverai una notifica email al completamento.</p>
</details>
<details><summary>Quali lingue sono supportate?</summary>
<p>Oltre 50 lingue incluse italiano, inglese, francese, spagnolo, tedesco, cinese, giapponese, coreano, portoghese, russo, arabo, hindi e molte altre. Ogni lingua ha diverse opzioni di voce.</p>
</details>
<details><summary>Audiobook Maker funziona su mobile?</summary>
<p>Sì. L'app web funziona in qualsiasi browser moderno su desktop, tablet o telefono. Tuttavia, per file EPUB di grandi dimensioni, si consiglia un browser desktop per caricamento ed elaborazione più veloci.</p>
</details>
</section>
""",

    "m4b-format": """
<section>
<h2>Cos'è il Formato M4B?</h2>
<p><strong>M4B</strong> (MPEG-4 Audiobook) è il formato standard per gli audiolibri. Basato sul contenitore MPEG-4 (la stessa famiglia dei video MP4), M4B è essenzialmente un file audio AAC con funzionalità speciali progettate specificamente per gli audiolibri:</p>
<ul>
<li><strong>Marcatori di capitolo</strong>: Punti di navigazione incorporati per saltare tra i capitoli</li>
<li><strong>Copertina</strong>: La copertina del libro è incorporata nei metadati del file</li>
<li><strong>Segnalibri</strong>: I lettori audiolibri ricordano la posizione di ascolto (anche tra dispositivi con iCloud)</li>
<li><strong>Metadati</strong>: Titolo, autore, narratore, genere e data di pubblicazione sono tutti memorizzati nel file</li>
<li><strong>Velocità variabile</strong>: I lettori possono accelerare o rallentare la riproduzione senza cambiare tonalità</li>
</ul>
<p>M4B è il formato utilizzato da <strong>Apple Books</strong>, <strong>Audible</strong> (AAX è una variante M4B con DRM) e dalla maggior parte delle app audiolibro dedicate su iOS e Android.</p>
</section>

<section>
<h2>M4B vs MP3 per Audiolibri: Confronto Completo</h2>
<table>
<thead><tr><th>Caratteristica</th><th>M4B</th><th>MP3</th></tr></thead>
<tbody>
<tr><td>Navigazione capitoli</td><td>Marcatori capitolo incorporati</td><td>Nessun capitolo incorporato</td></tr>
<tr><td>Copertina</td><td>Incorporata nel file</td><td>Incorporabile (ID3) ma non universalmente supportata</td></tr>
<tr><td>Salvataggio posizione</td><td>Sì (tutti i lettori M4B)</td><td>Dipende dal lettore</td></tr>
<tr><td>Dimensione file (stessa qualità)</td><td>~30-40% più piccolo (codec AAC)</td><td>Più grande a parità di qualità</td></tr>
<tr><td>Compatibilità</td><td>Apple Books, Audible, BookPlayer, Listen, la maggior parte delle app audiolibro</td><td>Universale — ogni dispositivo</td></tr>
<tr><td>File singolo</td><td>Sì — intero libro in un file</td><td>Solitamente un file per capitolo o un file combinato</td></tr>
<tr><td>Sincronizzazione segnalibri</td><td>Sì (ecosistema Apple)</td><td>No</td></tr>
<tr><td>Ideale per</td><td>Utenti iOS/Mac, collezionisti audiolibri, libri lunghi</td><td>Massima compatibilità, condivisione, lettori semplici</td></tr>
</tbody>
</table>
<p><strong>In conclusione:</strong> Scegli M4B se usi Apple Books o un'app audiolibro dedicata. Scegli MP3 se devi riprodurre il file su un lettore MP3 base o un'autoradio che non supporta M4B.</p>
</section>

<section>
<h2>Come Creare File M4B con Capitoli — Gratis</h2>
<p>Creare file M4B richiedeva complessi comandi ffmpeg o software a pagamento. <a href="/">Audiobook Maker</a> automatizza l'intero processo:</p>
<ol>
<li><strong>Carica il tuo ebook</strong> (EPUB, PDF o TXT) — i capitoli vengono estratti automaticamente</li>
<li><strong>Seleziona M4B come formato di output</strong> — lo strumento gestisce tutto: narrazione TTS, codifica AAC, marcatori capitolo, incorporamento copertina</li>
<li><strong>Scarica il file M4B</strong> — pronto per essere importato in Apple Books o qualsiasi lettore compatibile M4B</li>
</ol>
<p>L'M4B generato utilizza <strong>audio AAC a 64 kbps</strong> (ottimizzato per il parlato), include <strong>copertina 1400×1400</strong> e ha tag metadati compatibili con iTunes. Ogni capitolo appare come punto di navigazione nel tuo lettore audiolibri.</p>
</section>

<section>
<h2>Come Riprodurre File M4B</h2>
<p><strong>iOS / Mac:</strong> Apple Books (integrato) — trascina l'M4B in Libri o sincronizza via Finder/iCloud.</p>
<p><strong>Android:</strong> Listen Audiobook Player, Smart Audiobook Player, Sirin — tutti supportano M4B con capitoli.</p>
<p><strong>Windows:</strong> Apple Books (via iTunes), VLC media player, BookPlayer (Microsoft Store).</p>
<p><strong>Linux:</strong> VLC, Cozy (lettore audiolibri GTK).</p>
<p><strong>Auto / Lettore MP3 base:</strong> Converti in MP3 — la maggior parte delle autoradio non legge file M4B.</p>
</section>

<section>
<h2>Domande Frequenti</h2>
<details><summary>Posso convertire M4B in MP3?</summary>
<p>Sì. Puoi usare Audiobook Maker per generare output MP3, oppure usare ffmpeg: <code>ffmpeg -i libro.m4b -acodec libmp3lame -b:a 128k libro.mp3</code>. Nota che i marcatori di capitolo vengono persi nella conversione.</p>
</details>
<details><summary>Posso dividere un M4B in capitoli?</summary>
<p>Sì. Strumenti come <code>m4b-tool</code> o ffmpeg possono dividere file M4B in corrispondenza dei marcatori di capitolo. Audiobook Maker può anche generare file MP3 individuali per capitolo.</p>
</details>
<details><summary>Quali app audiolibro supportano M4B?</summary>
<p>Apple Books (iOS/Mac), BookPlayer (iOS), Listen Audiobook Player (Android), Smart Audiobook Player (Android), Bound (iOS), Sirin (Android), VLC (tutte le piattaforme) e Plex con il plugin Audnexus.</p>
</details>
<details><summary>Quale bitrate usare per audiolibri M4B?</summary>
<p>Audiobook Maker utilizza 64 kbps AAC, lo standard per contenuti parlati. Il parlato non ha bisogno di bitrate elevati — 64 kbps AAC suona identico a 128 kbps MP3 per la narrazione, ma occupa metà dello spazio.</p>
</details>
</section>
""",

    "text-to-speech-audiobook": """
<section>
<h2>Cos'è la Creazione di Audiolibri Text-to-Speech?</h2>
<p>La creazione di audiolibri text-to-speech (TTS) utilizza voci AI neurali per narrare testo scritto in audio parlato. A differenza dei vecchi TTS robotici, le moderne voci neurali suonano sorprendentemente naturali — con intonazione, ritmo ed emozione adeguati. Ora puoi <strong>trasformare qualsiasi testo, ebook o documento in un audiolibro dal suono professionale</strong> senza assumere un narratore umano.</p>
<p><a href="/">Audiobook Maker</a> combina i migliori motori TTS gratuiti con un'interfaccia web facile da usare. Carica file EPUB, PDF o TXT e ottieni output MP3, M4B o Podcast RSS — tutto gratuitamente.</p>
</section>

<section>
<h2>Migliori Motori TTS Gratuiti per Creare Audiolibri (2026)</h2>
<table>
<thead><tr><th>Motore TTS</th><th>Voci</th><th>Lingue</th><th>Costo</th><th>Ideale Per</th></tr></thead>
<tbody>
<tr><td><strong>Microsoft Edge TTS</strong></td><td>400+</td><td>50+</td><td>Gratis</td><td>Creazione audiolibri generale, migliori voci gratuite</td></tr>
<tr><td><strong>Google Cloud TTS (Chirp3-HD)</strong></td><td>50+</td><td>30+</td><td>1M caratteri gratis/mese, poi a pagamento</td><td>Qualità premium, narrazione espressiva</td></tr>
<tr><td><strong>Speechify</strong></td><td>30+</td><td>20+</td><td>Freemium (limitato)</td><td>Lettura rapida articoli, uso mobile</td></tr>
<tr><td><strong>NaturalReader</strong></td><td>100+</td><td>20+</td><td>Freemium (limitato)</td><td>Supporto dislessia, istruzione</td></tr>
<tr><td><strong>ElevenLabs</strong></td><td>Personalizzate</td><td>30+</td><td>10K caratteri gratis/mese</td><td>Clonazione voce ultra-realistica</td></tr>
<tr><td><strong>Play.ht</strong></td><td>800+</td><td>140+</td><td>5K caratteri gratis/mese</td><td>Multi-lingua, varietà voci</td></tr>
</tbody>
</table>
<p><strong>Audiobook Maker utilizza Microsoft Edge TTS come predefinito</strong> — è completamente gratuito, non ha limiti di utilizzo e offre oltre 400 voci. Google TTS Chirp3-HD è disponibile per chi desidera qualità premium. A differenza di Speechify o NaturalReader, Audiobook Maker <strong>non ha paywall, non richiede registrazione e non ha limiti di utilizzo</strong>.</p>
</section>

<section>
<h2>Voci PREMIUM: Confronto tra i Modelli Gemini TTS (Flash 2.5 vs 3.1)</h2>
<p>Per chi desidera la massima qualità audio, Audiobook Maker offre <strong>Voci PREMIUM</strong> basate su due modelli Google Gemini Text-to-Speech di ultima generazione. Entrambi i modelli producono audio con voci neurali altamente espressive, supportano <strong>30 voci multilingue</strong> (ogni voce è in grado di parlare fluentemente 24 lingue) e permettono di personalizzare lo <strong>stile narrativo</strong> e la <strong>velocità di lettura</strong> (±30%).</p>

<table>
<thead><tr><th>Caratteristica</th><th>Gemini 2.5 Flash</th><th>Gemini 3.1 Flash</th></tr></thead>
<tbody>
<tr><td><strong>Generazione</strong></td><td>Seconda generazione</td><td>Terza generazione (più recente)</td></tr>
<tr><td><strong>Qualità audio</strong></td><td>Molto buona — narrazione naturale e pulita</td><td>Eccellente — maggiore espressività, intonazione più ricca, prosodia superiore</td></tr>
<tr><td><strong>Velocità di sintesi</strong></td><td>Più rapida — adatta a libri lunghi</td><td>Più lenta — privilegia la qualità sulla velocità</td></tr>
<tr><td><strong>Costo indicativo al minuto</strong></td><td>~€0,025/min (più economico)</td><td>~€0,036/min (qualità premium)</td></tr>
<tr><td><strong>Stile narrativo</strong></td><td>Personalizzabile con istruzioni testuali (fino a 200 caratteri)</td><td>Personalizzabile con istruzioni testuali (fino a 200 caratteri)</td></tr>
<tr><td><strong>Velocità lettura</strong></td><td>Regolabile da -30% a +30%</td><td>Regolabile da -30% a +30%</td></tr>
<tr><td><strong>Ideale per</strong></td><td>Saggistica, manuali, narrativa semplice, libri molto lunghi, budget contenuto</td><td>Narrativa complessa, dialoghi, audiolibri che richiedono massima espressività emotiva</td></tr>
</tbody>
</table>

<p><strong>Quale scegliere?</strong> Se il budget o la lunghezza del libro sono la tua priorità, <strong>Gemini 2.5 Flash</strong> offre un ottimo rapporto qualità/prezzo con tempi di generazione più rapidi. Se cerchi la massima qualità audio possibile, con intonazioni più ricche e una narrazione più coinvolgente — specialmente per romanzi con dialoghi e personaggi — <strong>Gemini 3.1 Flash</strong> rappresenta lo stato dell'arte della sintesi vocale neurale.</p>

<p>Entrambi i modelli sono disponibili nella scheda <strong>"Voci PREMIUM"</strong> del pannello di generazione. Il costo esatto, calcolato in base al numero di caratteri del tuo libro e al modello selezionato, viene mostrato in tempo reale prima di procedere al pagamento. È possibile utilizzare PayPal o un codice voucher per l'acquisto.</p>
</section>

<section>
<h2>Alternativa a Speechify: Perché Scegliere Audiobook Maker?</h2>
<p>Speechify è un'app TTS popolare, ma la sua versione gratuita è molto limitata. Ecco come si confronta Audiobook Maker:</p>
<ul>
<li><strong>100% gratuito</strong> contro l'abbonamento Speechify a $139/anno</li>
<li><strong>Nessun limite di utilizzo</strong> — converti interi libri, non solo testi brevi</li>
<li><strong>Output M4B con capitoli</strong> — Speechify esporta solo audio semplice</li>
<li><strong>Feed Podcast RSS</strong> — ascolta in qualsiasi app podcast</li>
<li><strong>Open source</strong> — licenza AGPL-3.0, puoi ispezionare e modificare il codice</li>
<li><strong>Opzione self-hosted</strong> — eseguilo sul tuo server per privacy completa</li>
<li><strong>Ottimizzazione AI del testo</strong> — pulisce e migliora automaticamente il testo per una migliore narrazione</li>
</ul>
<p>Se hai bisogno di un'<strong>alternativa gratuita a Speechify</strong> per libri completi, Audiobook Maker è la migliore opzione disponibile.</p>
</section>

<section>
<h2>Come Creare un Audiolibro con Voci AI — Passo Dopo Passo</h2>
<ol>
<li><strong>Carica il tuo file</strong> — EPUB, PDF o testo semplice (TXT). Lo strumento rileva automaticamente i capitoli ed estrae i metadati.</li>
<li><strong>Scegli una voce</strong> — Sfoglia oltre 400 voci neurali. Ogni voce ha un'anteprima per sentirla prima della conversione.</li>
<li><strong>Seleziona il formato di output</strong> — MP3 per compatibilità universale, M4B per Apple Books con capitoli, o Podcast RSS per lo streaming.</li>
<li><strong>Genera</strong> — L'AI narra il tuo libro capitolo per capitolo. L'avanzamento è mostrato in tempo reale.</li>
<li><strong>Scarica e ascolta</strong> — Ottieni il tuo audiolibro come file singolo, ZIP dei capitoli, o iscriviti al feed podcast privato.</li>
</ol>
</section>

<section>
<h2>Audiolibro TTS Gratuito vs Narratore Umano</h2>
<table>
<thead><tr><th>Aspetto</th><th>AI TTS (Audiobook Maker)</th><th>Narratore Umano</th></tr></thead>
<tbody>
<tr><td>Costo</td><td>Gratis</td><td>500-5.000€+ a libro</td></tr>
<tr><td>Tempo</td><td>~1 ora</td><td>2-6 settimane</td></tr>
<tr><td>Qualità</td><td>Molto buona (neurale, naturale)</td><td>Eccellente (espressività umana)</td></tr>
<tr><td>Lingue</td><td>50+ immediatamente</td><td>Una lingua per narratore</td></tr>
<tr><td>Revisioni</td><td>Ri-generazione immediata</td><td>Necessaria nuova registrazione</td></tr>
<tr><td>Ideale per</td><td>Uso personale, bozze, autori indipendenti</td><td>Audiolibri commerciali in vendita (Audible, ecc.)</td></tr>
</tbody>
</table>
<p>Per l'ascolto personale, la revisione dei propri testi o la creazione di versioni audiolibro di libri di pubblico dominio, l'AI TTS è la scelta vincente. Per audiolibri commerciali destinati alla vendita su Audible, un narratore umano è ancora preferibile (e richiesto da ACX).</p>
</section>

<section>
<h2>Domande Frequenti</h2>
<details><summary>Il text-to-speech AI è abbastanza buono per gli audiolibri?</summary>
<p>Sì. I moderni TTS neurali (come Microsoft Edge TTS e Google Chirp3-HD) sono notevolmente naturali. La maggior parte degli ascoltatori non distingue la differenza da un narratore umano per la saggistica. Per la narrativa con più personaggi e gamma emotiva, la narrazione umana è ancora superiore — ma il divario si sta rapidamente colmando.</p>
</details>
<details><summary>Posso usare audiolibri generati con AI a fini commerciali?</summary>
<p>Sì, con alcune precisazioni. Microsoft Edge TTS e Google TTS consentono l'uso commerciale dell'audio generato. Tuttavia, piattaforme come Audible (ACX) richiedono attualmente la narrazione umana per i nuovi invii. Gli audiolibri AI possono essere venduti su altre piattaforme o utilizzati per progetti personali, video YouTube e contenuti educativi.</p>
</details>
<details><summary>Quanti caratteri posso convertire gratuitamente?</summary>
<p>Con Microsoft Edge TTS: illimitati. Non ci sono limiti o quote di utilizzo. Con Google Cloud TTS Chirp3-HD: 1 milione di caratteri al mese gratuiti, poi si applicano le tariffe standard di Google Cloud.</p>
</details>
<details><summary>Audiobook Maker funziona offline?</summary>
<p>La versione ospitata su audiobook-maker.com richiede una connessione internet. Tuttavia, il software è open source — puoi installarlo sul tuo computer o server ed eseguirlo localmente con piena capacità offline.</p>
</details>
<details><summary>Qual è la migliore voce TTS per audiolibri in italiano?</summary>
<p>Le migliori voci Edge TTS per l'italiano sono <strong>Isabella</strong> (femminile calda), <strong>Diego</strong> (maschile profondo) ed <strong>Elsa</strong> (femminile chiara). Per qualità premium, Google Chirp3-HD offre le voci neurali più espressive. <a href="/">Prova l'anteprima gratuita su Audiobook Maker</a> per trovare la tua preferita.</p>
</details>
</section>
""",

    "gemini-tts": """
<p>Gemini TTS è il motore neurale dietro le Voci PREMIUM di Audiobook Maker. Questa guida illustra le voci disponibili, le lingue supportate e come guidare la lettura con i prompt.</p>

<h2 id="voices">Opzioni voce</h2>
<p>30 voci distinte, ognuna con un proprio carattere. Il nome della voce è fisso; il descrittore ne riassume il tono naturale.</p>
<table>
  <thead><tr><th>Voce</th><th>Carattere</th></tr></thead>
  <tbody>
    <tr><td>Zephyr</td><td>Brillante</td></tr>
    <tr><td>Puck</td><td>Vivace</td></tr>
    <tr><td>Charon</td><td>Informativo</td></tr>
    <tr><td>Kore</td><td>Deciso</td></tr>
    <tr><td>Fenrir</td><td>Entusiasta</td></tr>
    <tr><td>Leda</td><td>Giovanile</td></tr>
    <tr><td>Orus</td><td>Deciso</td></tr>
    <tr><td>Aoede</td><td>Disinvolto</td></tr>
    <tr><td>Callirrhoe</td><td>Rilassato</td></tr>
    <tr><td>Autonoe</td><td>Brillante</td></tr>
    <tr><td>Enceladus</td><td>Sussurrato</td></tr>
    <tr><td>Iapetus</td><td>Chiaro</td></tr>
    <tr><td>Umbriel</td><td>Rilassato</td></tr>
    <tr><td>Algieba</td><td>Morbido</td></tr>
    <tr><td>Despina</td><td>Morbido</td></tr>
    <tr><td>Erinome</td><td>Chiaro</td></tr>
    <tr><td>Algenib</td><td>Roco</td></tr>
    <tr><td>Rasalgethi</td><td>Informativo</td></tr>
    <tr><td>Laomedeia</td><td>Vivace</td></tr>
    <tr><td>Achernar</td><td>Delicato</td></tr>
    <tr><td>Alnilam</td><td>Deciso</td></tr>
    <tr><td>Schedar</td><td>Equilibrato</td></tr>
    <tr><td>Gacrux</td><td>Maturo</td></tr>
    <tr><td>Pulcherrima</td><td>Diretto</td></tr>
    <tr><td>Achird</td><td>Amichevole</td></tr>
    <tr><td>Zubenelgenubi</td><td>Informale</td></tr>
    <tr><td>Vindemiatrix</td><td>Gentile</td></tr>
    <tr><td>Sadachbia</td><td>Brioso</td></tr>
    <tr><td>Sadaltager</td><td>Competente</td></tr>
    <tr><td>Sulafat</td><td>Caldo</td></tr>
  </tbody>
</table>

<h2 id="languages">Lingue supportate</h2>
<p>Gemini TTS supporta le seguenti lingue (codice BCP-47 fra parentesi):</p>
<p>Arabic (ar), Filipino (fil), Bangla (bn), Finnish (fi), Dutch (nl), Galician (gl), English (en), Georgian (ka), French (fr), Greek (el), German (de), Gujarati (gu), Hindi (hi), Haitian Creole (ht), Indonesian (id), Hebrew (he), Italian (it), Hungarian (hu), Japanese (ja), Icelandic (is), Korean (ko), Javanese (jv), Marathi (mr), Kannada (kn), Polish (pl), Konkani (kok), Portuguese (pt), Romanian (ro), Russian (ru), Spanish (es), Tamil (ta), Telugu (te), Thai (th), Turkish (tr), Ukrainian (uk), Vietnamese (vi), Afrikaans (af), Albanian (sq), Amharic (am), Armenian (hy), Azerbaijani (az), Basque (eu), Belarusian (be), Bulgarian (bg), Burmese (my), Catalan (ca), Cebuano (ceb), Chinese Mandarin (cmn), Croatian (hr), Czech (cs), Danish (da), Estonian (et), Latvian (lv), Lithuanian (lt), Luxembourgish (lb), Macedonian (mk), Maithili (mai), Malagasy (mg), Malay (ms), Malayalam (ml), Mongolian (mn), Nepali (ne), Norwegian Bokm&aring;l (nb), Norwegian Nynorsk (nn), Odia (or), Pashto (ps), Persian (fa), Punjabi (pa), Serbian (sr), Sindhi (sd), Sinhala (si), Slovak (sk), Slovenian (sl), Swahili (sw), Swedish (sv), Urdu (ur).</p>

<h2 id="prompting">Guida al prompting</h2>
<p>Il modello deduce la lettura dal testo automaticamente. Puoi guidarla ulteriormente con tag inline e indicazioni strutturate.</p>
<h3>Tag audio inline</h3>
<p>Modificatori inline come <code>[whispers]</code>, <code>[laughs]</code>, <code>[excitedly]</code>, <code>[bored]</code> e <code>[shouting]</code> cambiano tono, ritmo e qualità emotiva. Sii creativo e sperimenta variazioni di resa.</p>
<h3>Elementi di prompting avanzato</h3>
<ul>
  <li><strong>Audio Profile</strong> &mdash; nome e ruolo del personaggio.</li>
  <li><strong>Scene</strong> &mdash; contesto ambientale che definisce atmosfera e ambientazione.</li>
  <li><strong>Director&rsquo;s Notes</strong> &mdash; indicazioni di resa: stile, ritmo, accento.</li>
  <li><strong>Sample Context</strong> &mdash; aggancio contestuale per un ingresso naturale nella lettura.</li>
  <li><strong>Transcript</strong> &mdash; le parole esatte da pronunciare, insieme ai tag audio.</li>
</ul>
<h3>Linee guida chiave</h3>
<p>Non serve descrivere tutto: lasciare spazio al modello favorisce spesso la naturalezza. Bilancia specificità e libertà creativa e preferisci la terminologia di settore e caratteristiche stratificate alle semplici etichette emotive.</p>
<h3>Come usare i prompt in Audiobook Maker</h3>
<p>Audiobook Maker legge direttamente il testo dei capitoli, quindi i prompt si inseriscono nel testo stesso, in due modi:</p>
<ul>
  <li>Modifica il file <strong>TXT</strong> in input prima del caricamento, inserendo tag/indicazioni direttamente nel testo.</li>
  <li>Oppure scarica il file <strong>.ABM</strong> generato, modifica i testi dei capitoli e ricarica l'<strong>.ABM</strong> modificato su Audiobook Maker.</li>
</ul>
<p style="font-size:.85rem;color:var(--txm)">Fonte: <a href="https://ai.google.dev/gemini-api/docs/speech-generation" rel="nofollow noopener" target="_blank">Google AI &mdash; Speech generation</a></p>
""",

    "podcast": """
	<section>
	<h2>Trasforma il Tuo Audiolibro in un Podcast Privato</h2>
	<p>Audiobook Maker genera, insieme ai file audio, un <strong>pacchetto podcast completo</strong> con feed RSS 2.0. Per renderlo disponibile come podcast, i file devono essere pubblicati su un server web accessibile da Internet. La soluzione ideale è il <strong>tuo sito web</strong> o spazio hosting. In alternativa, per uso personale o condivisione con pochi amici, puoi usare una soluzione gratuita come <strong>Netlify</strong>, descritta in questa guida.</p>
	<div style="background:#fff3cd;border-left:4px solid #f0c040;padding:10px 14px;border-radius:6px;margin:0 0 18px;font-size:.92rem;color:#5a4510"><strong>Uso consigliato:</strong> questa soluzione è pensata per uso personale o condivisione con amici e familiari. Netlify offre 100 GB/mese di banda gratuita — più che sufficiente. Per distribuzione pubblica, considera l'uso di un hosting web proprio.</div>
	</section>

	<section>
	<h2>Passo Dopo Passo: Pubblica il Tuo Audiolibro come Podcast</h2>
	<ol>
	<li><strong>Genera l'audiolibro in formato M4B</strong> — In Audiobook Maker, carica il tuo file EPUB o PDF, scegli lingua e voce, poi seleziona <strong>M4B</strong> come formato di output. Lo strumento crea un singolo file M4B con capitoli incorporati e copertina — lo standard professionale per gli audiolibri.</li>
	<li><strong>Genera anche il pacchetto Podcast RSS</strong> — Dopo aver generato l'M4B, esegui nuovamente la generazione in modalità <strong>Podcast RSS</strong> per ottenere un ZIP contenente il file XML del feed RSS e i singoli file MP3 dei capitoli (i podcast richiedono un file audio per episodio).</li>
	<li><strong>Crea un account Netlify gratuito</strong> — Vai su <strong>app.netlify.com</strong> e registrati con email o GitHub. Nessuna carta di credito richiesta. Il piano gratuito include 100 GB di banda, 10 GB di storage e HTTPS automatico.</li>
	<li><strong>Carica su Netlify</strong> — Nella dashboard di Netlify, sotto <strong>Sites</strong>, trascina l'intera cartella estratta sulla zona di rilascio tratteggiata. Il sito sarà online in pochi secondi. Poi rinominalo da <em>Site configuration → Change site name</em> (es. <code>mio-audiolibro.netlify.app</code>).</li>
	<li><strong>Verifica il feed</strong> — Apri l'URL del feed nel browser: <br><code>https://tuo-nome-sito.netlify.app/podcast.xml</code><br>Se vedi contenuto XML con i titoli dei tuoi capitoli, il tuo podcast è online e pronto!</li>
	</ol>
	</section>

	<section>
	<h2>Importa il Tuo Podcast nelle App di Ascolto</h2>
	<table>
	<thead><tr><th>App</th><th>Piattaforma</th><th>Come Aggiungerlo</th></tr></thead>
	<tbody>
	<tr><td><strong>Apple Podcasts</strong></td><td>iOS / Mac</td><td><strong>iPhone:</strong> Libreria → Altro → Aggiungi show tramite URL → incolla URL feed<br><strong>Mac:</strong> File → Segui uno show per URL</td></tr>
	<tr><td><strong>Pocket Casts</strong></td><td>Android / iOS / Web</td><td>Cerca → incolla URL feed → Iscriviti</td></tr>
	<tr><td><strong>AntennaPod</strong></td><td>Android</td><td>+ → Aggiungi Podcast per URL → incolla URL</td></tr>
	<tr><td><strong>Overcast</strong></td><td>iOS</td><td>+ → Aggiungi URL → incolla URL feed</td></tr>
	<tr><td><strong>Podcast Addict</strong></td><td>Android</td><td>+ → Feed RSS → incolla URL</td></tr>
	</tbody>
	</table>
	<div style="background:#fff0f0;border-left:4px solid #e04040;padding:8px 14px;border-radius:6px;margin:12px 0;font-size:.9rem;color:#802020"><strong>Nota:</strong> Spotify non supporta l'aggiunta di feed RSS privati. Usa una delle app elencate sopra.</div>
	</section>

	<section>
	<h2>Perché Ascoltare il Tuo Audiolibro come Podcast?</h2>
	<ul>
	<li><strong>Segnalibri automatici</strong> — Riprendi esattamente dove avevi lasciato, anche tra dispositivi diversi</li>
	<li><strong>Ordinamento episodi</strong> — I capitoli vengono riprodotti in ordine con avanzamento automatico</li>
	<li><strong>Metadati completi</strong> — Copertina, titoli dei capitoli e info sul libro visibili nell'app podcast</li>
	<li><strong>Velocità regolabile</strong> — Ascolta a 1,5x, 2x o qualsiasi velocità preferisci, con timer di spegnimento</li>
	<li><strong>Streaming</strong> — Nessun bisogno di scaricare tutti i file; ascolta ogni capitolo in streaming</li>
	<li><strong>Condividi con la famiglia</strong> — Invia l'URL del feed ai familiari; non serve un account Netlify</li>
	</ul>
	</section>

	<section>
	<h2>Consigli per la Pubblicazione del Podcast</h2>
	<ul>
	<li><strong>Aggiorna gli episodi:</strong> Ricarica i file su Netlify per sostituire la versione precedente. L'app podcast rileverà le modifiche al prossimo aggiornamento.</li>
	<li><strong>Più libri:</strong> Crea un sito Netlify separato per ogni audiolibro per mantenere i feed organizzati.</li>
	<li><strong>Limiti di storage:</strong> Il piano gratuito Netlify include 10 GB di storage (~12 audiolibri completi). Rimuovi i libri finiti per liberare spazio.</li>
	<li><strong>Privacy:</strong> L'URL del podcast è tecnicamente pubblico (chiunque abbia il link può iscriversi), ma non apparirà nelle directory podcast o nei motori di ricerca. È "privato" nel senso che non è indicizzato.</li>
	<li><strong>Dominio personalizzato:</strong> Netlify supporta domini personalizzati nel piano gratuito se desideri un URL personalizzato.</li>
	</ul>
	</section>

	<section>
	<h2>Domande Frequenti</h2>
	<details><summary>Netlify è davvero gratuito per ospitare il mio podcast?</summary>
	<p>Sì. Il piano Starter gratuito di Netlify include 100 GB/mese di banda e 10 GB di storage. Per un tipico podcast audiolibro (10-20 episodi, ~5 MB ciascuno), è più che sufficiente per uso personale. Se superi i limiti, puoi passare a Netlify Pro ($19/mese) o usare un hosting proprio.</p>
	</details>
	<details><summary>Perché usare il formato M4B invece di MP3 per l'audiolibro?</summary>
	<p>M4B è lo standard professionale per gli audiolibri. Un singolo file M4B contiene tutti i capitoli come marcatori di navigazione, copertina incorporata e metadati. È supportato da Apple Books, Audible e tutte le principali app audiolibri. MP3 è ottimo per la massima compatibilità, ma M4B offre un'esperienza di ascolto molto migliore con la navigazione tra i capitoli.</p>
	</details>
	<details><summary>Posso inviare il mio podcast alle directory di Apple Podcasts o Spotify?</summary>
	<p>Non con un feed Netlify privato. Apple Podcasts Connect e Spotify for Podcasters richiedono feed ospitati su piattaforme approvate con requisiti specifici (dimensioni copertina, categorie, ecc.). L'approccio Netlify è per <strong>podcast privati personali</strong> — ideale per ascoltare i propri libri o condividerli con amici e familiari stretti.</p>
	</details>
	<details><summary>Cosa posso usare se non voglio Netlify?</summary>
	<p>Qualsiasi hosting web statico funziona: GitHub Pages, Cloudflare Pages, Vercel o il tuo server web. Carica semplicemente la cartella del podcast estratta in qualsiasi posizione accessibile via web e l'URL del feed RSS funzionerà nelle app podcast. Netlify è consigliato perché è gratuito, veloce e non richiede configurazione.</p>
	</details>
	<details><summary>Le app podcast possono scaricare episodi per l'ascolto offline?</summary>
	<p>Sì. Una volta iscritto al feed in un'app podcast, puoi scaricare singoli episodi per l'ascolto offline, come qualsiasi altro podcast. L'app gestisce automaticamente download, posizione di riproduzione ed eliminazione.</p>
	</details>
	</section>
	""",


}

# Map language code to body dict for per-language guide content.
# Each language dict has the same keys as _GUIDE_BODY_EN.

_GUIDE_BODY_FR = {
    "free-ebooks": """
<section>
<h2>Où Trouver des Ebooks Gratuits à Télécharger</h2>
<p>Des milliers d'excellents livres sont totalement gratuits et légaux à télécharger — classiques du domaine public, titres modernes publiés sous licences ouvertes et projets communautaires. Une fois votre EPUB gratuit obtenu, vous pouvez le transformer en livre audio en quelques minutes avec <a href="/">Audiobook Maker</a>. Ce guide répertorie les meilleures sources d'ebooks gratuits et vous montre comment les écouter.</p>
</section>

<section>
<h2>Les 8 Meilleurs Sites d'Ebooks Gratuits</h2>
<ul>
<li><a href="https://www.gutenberg.org" target="_blank" rel="noopener">Project Gutenberg</a> — Plus de 70 000 livres gratuits du domaine public. La plus grande et la plus ancienne collection au monde, avec des téléchargements EPUB fiables.</li>
<li><a href="https://standardebooks.org" target="_blank" rel="noopener">Standard Ebooks</a> — Des éditions soignées et magnifiquement formatées de classiques, avec une typographie moderne et des couvertures originales.</li>
<li><a href="https://archive.org/details/texts" target="_blank" rel="noopener">Internet Archive</a> — Une immense bibliothèque numérique avec des millions de textes, livres audio et périodiques historiques.</li>
<li><a href="https://manybooks.net" target="_blank" rel="noopener">ManyBooks</a> — Plus de 50 000 ebooks gratuits avec une interface moderne et des recommandations de lecture personnalisées.</li>
<li><a href="https://www.feedbooks.com/publicdomain" target="_blank" rel="noopener">Feedbooks</a> — Un catalogue élégant d'ebooks du domaine public avec téléchargement direct et sans tracas.</li>
<li><a href="https://books.google.com/books?&as_ebook=on&as_brr=1" target="_blank" rel="noopener">Google Books</a> — Des millions de livres numérisés ; filtrez par « Ebooks gratuits » pour trouver les titres gratuits.</li>
<li><a href="https://www.liberliber.it/online/opere/libri/" target="_blank" rel="noopener">Liber Liber</a> — La référence pour les classiques de la littérature italienne : Dante, Manzoni, Pirandello et bien d'autres.</li>
<li><a href="https://openlibrary.org/read" target="_blank" rel="noopener">Open Library</a> — Prêt numérique gratuit d'ebooks modernes et classiques, géré par Internet Archive.</li>
</ul>
</section>

<section>
<h2>Domaine Public vs. Livres sous Copyright</h2>
<p>Les livres du <strong>domaine public</strong> — généralement les œuvres dont l'auteur est décédé depuis plus de 70 ans — sont libres de télécharger, partager et convertir sans restriction. Project Gutenberg, Standard Ebooks et Liber Liber sont spécialisés dans ces ouvrages.</p>
<p>Les livres <strong>sous copyright</strong> sont protégés même lorsqu'ils sont offerts gratuitement. De nombreux auteurs et éditeurs publient des titres modernes sous licences <a href="https://creativecommons.org" target="_blank" rel="noopener">Creative Commons</a> ou en promotions gratuites : ils sont parfaitement légaux à télécharger. Évitez les sites pirates qui partagent des ebooks commerciaux sans autorisation : ils sont illégaux et contiennent souvent des logiciels malveillants.</p>
</section>

<section>
<h2>Comment Transformer un Ebook Gratuit en Livre Audio</h2>
<ol>
<li><strong>Téléchargez l'EPUB</strong> depuis l'un des sites ci-dessus (l'EPUB est préférable au PDF pour une détection des chapitres plus propre).</li>
<li><strong>Ouvrez <a href="/">Audiobook Maker</a></strong> et importez le fichier — chapitres, titre, auteur et couverture sont extraits automatiquement.</li>
<li><strong>Choisissez une voix IA neuronale</strong> parmi plus de 400 options dans plus de 50 langues et écoutez un aperçu gratuit.</li>
<li><strong>Choisissez votre format</strong> — MP3 pour une compatibilité maximale, ou <a href="/guide/m4b-format/">M4B</a> avec chapitres et couverture intégrés.</li>
<li><strong>Générez et téléchargez</strong> — écoutez sur votre téléphone, tablette ou tout lecteur de livres audio.</li>
</ol>
<p>Consultez le guide complet <a href="/guide/epub-to-audiobook/">EPUB en livre audio →</a> pour les détails.</p>
</section>

<section>
<h2>Conseils pour Choisir le Bon Ebook Gratuit</h2>
<ul>
<li><strong>Préférez l'EPUB au PDF</strong> : l'EPUB possède une structure de chapitres propre, tandis que les PDF peuvent inclure des en-têtes, numéros de page et artefacts de mise en page à nettoyer.</li>
<li><strong>Vérifiez l'édition</strong> : Standard Ebooks et Liber Liber proposent les versions les mieux formatées des classiques, avec moins de fautes et d'erreurs OCR.</li>
<li><strong>Utilisez l'optimisation IA du texte</strong> : pour les PDF ou scans bruts, le nettoyage IA optionnel d'Audiobook Maker supprime notes de bas de page, césures et artefacts avant la narration.</li>
<li><strong>Attention à la langue</strong> : choisissez une voix qui correspond à la langue du livre pour une prononciation naturelle.</li>
</ul>
</section>

<section>
<h2>Questions Fréquentes</h2>
<details><summary>Est-il légal de télécharger des ebooks gratuits ?</summary>
<p>Oui, lorsque le livre est dans le domaine public ou offert gratuitement par l'auteur ou l'éditeur. Tous les sites listés dans ce guide distribuent des livres légalement. Évitez les sites pirates qui partagent des titres commerciaux protégés sans autorisation.</p>
</details>
<details><summary>Quel est le meilleur format à télécharger pour créer un livre audio ?</summary>
<p>L'EPUB est le meilleur : il possède une structure de chapitres propre qui se convertit de manière fiable. Le PDF fonctionne aussi, mais peut nécessiter l'optimisation IA du texte pour supprimer les artefacts de mise en page. Le TXT convient au texte brut sans chapitres.</p>
</details>
<details><summary>Puis-je convertir ces ebooks gratuits en livres audio gratuitement ?</summary>
<p>Oui. Audiobook Maker convertit EPUB, PDF et TXT en livres audio MP3 ou M4B gratuitement grâce à des voix TTS neuronales, sans inscription et sans limite d'utilisation.</p>
</details>
<details><summary>Où trouver des ebooks gratuits dans d'autres langues que l'anglais ?</summary>
<p>Project Gutenberg et Internet Archive hébergent des livres dans des dizaines de langues. Liber Liber est spécialisé en italien, et Google Books permet de filtrer les titres gratuits par langue. Audiobook Maker les narre ensuite dans plus de 50 langues.</p>
</details>
</section>
""",

    "epub-to-audiobook": """
<section>
<h2>Pourquoi Convertir un EPUB en Livre Audio ?</h2>
<p>L'EPUB est le format d'ebook le plus répandu, utilisé par Apple Books, Google Play Books, Kobo et la plupart des bibliothèques numériques. Convertir un EPUB en livre audio vous permet d'<strong>écouter vos ebooks</strong> pendant vos trajets, vos séances de sport ou vos tâches ménagères. Les voix modernes de synthèse vocale IA sont étonnamment naturelles, bien loin des lecteurs d'écran robotiques du passé.</p>
<p>Avec <a href="/">Audiobook Maker</a>, vous pouvez convertir gratuitement tout EPUB sans DRM en livre audio MP3 ou M4B, directement dans votre navigateur. Aucun logiciel à installer, aucun compte requis.</p>
</section>

<section>
<h2>Comment Convertir un EPUB en Livre Audio — Pas à Pas</h2>
<ol>
<li><strong>Téléchargez votre fichier EPUB</strong> — Glissez-déposez ou cliquez pour sélectionner. L'outil extrait automatiquement les chapitres et les métadonnées (titre, auteur, couverture).</li>
<li><strong>Choisissez votre voix TTS</strong> — Sélectionnez parmi plus de 400 voix IA neuronales dans plus de 50 langues. Écoutez un extrait avant de lancer la conversion complète.</li>
<li><strong>Sélectionnez les chapitres</strong> — Choisissez les chapitres à inclure. Ignorez la table des matières, les pages de droits d'auteur ou toute section que vous ne souhaitez pas faire narrer.</li>
<li><strong>Choisissez le format de sortie</strong> — <strong>MP3</strong> (fichier unique ou ZIP par chapitre), <strong>M4B</strong> (fichier unique avec chapitres et couverture intégrés — idéal pour Apple Books et les applications de livres audio), ou <strong>Podcast RSS</strong> (flux podcast privé).</li>
<li><strong>Cliquez sur "Générer"</strong> — Le moteur TTS narre chaque chapitre. Vous verrez une barre de progression et recevrez une notification par email une fois terminé.</li>
<li><strong>Téléchargez et écoutez</strong> — Téléchargez votre livre audio et commencez à écouter sur n'importe quel appareil.</li>
</ol>
</section>

<section>
<h2>Meilleures Voix pour la Conversion EPUB en Livre Audio</h2>
<p>Audiobook Maker utilise <strong>Microsoft Edge neural TTS</strong> (le même moteur qu'Azure Cognitive Services). Voici les voix gratuites les plus naturelles disponibles :</p>
<ul>
<li><strong>Anglais (US)</strong> : Aria, Jenny, Guy, Davis, Jane — narration chaleureuse et expressive</li>
<li><strong>Anglais (UK)</strong> : Sonia, Ryan, Libby — excellent pour la littérature britannique</li>
<li><strong>Italien</strong> : Isabella, Diego, Elsa — narration italienne naturelle</li>
<li><strong>Français</strong> : Denise, Henri — prononciation française claire</li>
<li><strong>Allemand</strong> : Katja, Conrad — discours allemand net</li>
<li><strong>Espagnol</strong> : Elvira, Alvaro — narration espagnole fluide</li>
<li><strong>Chinois</strong> : Xiaoxiao, Yunyang — discours mandarin naturel</li>
</ul>
<p>Google Cloud TTS Chirp3-HD est également disponible pour une qualité encore supérieure (premier million de caractères gratuit par mois).</p>
</section>

<section>
<h2>EPUB vers MP3 vs EPUB vers M4B : Quel Format Choisir ?</h2>
<p><strong>MP3</strong> est universellement compatible — chaque téléphone, tablette et ordinateur lit les fichiers MP3. Choisissez MP3 si vous voulez une compatibilité maximale ou prévoyez d'écouter sur plusieurs appareils.</p>
<p><strong>M4B</strong> est le format professionnel des livres audio. C'est un fichier unique qui contient tous les chapitres comme marqueurs de navigation, plus la couverture et les métadonnées intégrées (auteur, titre, genre). Les fichiers M4B sont pris en charge par Apple Books, Audible et la plupart des applications de livres audio. <a href="/guide/m4b-format/">En savoir plus sur le format M4B →</a></p>
</section>

<section>
<h2>Conseils pour une Meilleure Expérience EPUB vers Livre Audio</h2>
<ul>
<li><strong>Supprimez d'abord les DRM</strong> : Les ebooks commerciaux de Kindle, Apple Books ou Kobo ont souvent une protection DRM. Vous devrez la supprimer avant conversion (pour usage personnel uniquement, là où c'est légalement autorisé).</li>
<li><strong>Nettoyez le texte</strong> : Certains EPUB contiennent des artefacts de formatage (numéros de page, en-têtes, notes de bas de page). L'optimisation IA optionnelle d'Audiobook Maker peut les nettoyer automatiquement.</li>
<li><strong>Prévisualisez avant la génération complète</strong> : Générez toujours l'aperçu gratuit d'abord pour vérifier la qualité de la voix et le rythme.</li>
<li><strong>Utilisez le sélecteur de chapitres</strong> : Ignorez les pages liminaires (TOC, préface) et les annexes (index, publicités) pour une expérience d'écoute plus fluide.</li>
<li><strong>Choisissez M4B pour les longs livres</strong> : Le format M4B garde tout organisé dans un seul fichier avec navigation par chapitres — bien mieux que de jongler avec plusieurs fichiers MP3.</li>
</ul>
</section>

<section>
<h2>Questions Fréquentes</h2>
<details><summary>Est-ce vraiment gratuit de convertir un EPUB en livre audio ?</summary>
<p>Oui. Audiobook Maker est un logiciel open-source (AGPL-3.0). La conversion TTS utilise Microsoft Edge TTS qui est gratuit et sans limite d'utilisation. L'optimisation IA optionnelle du texte (DeepSeek LLM) a un petit coût au-dessus d'un seuil gratuit.</p>
</details>
<details><summary>Puis-je convertir des livres Kindle en livres audio ?</summary>
<p>Les livres Kindle utilisent le format propriétaire AZW/KFX d'Amazon avec DRM. Vous devrez d'abord supprimer les DRM et convertir en EPUB avec un outil comme Calibre, puis télécharger l'EPUB sur Audiobook Maker.</p>
</details>
<details><summary>Combien de temps prend la conversion EPUB en livre audio ?</summary>
<p>Environ 2-3 minutes par chapitre (variable selon la longueur du chapitre et la charge du serveur). Un livre typique de 300 pages (~20 chapitres) prend environ 40-60 minutes. Vous recevrez une notification par email quand c'est terminé.</p>
</details>
<details><summary>Quelles langues sont prises en charge ?</summary>
<p>Plus de 50 langues, dont l'anglais, l'italien, le français, l'espagnol, l'allemand, le chinois, le japonais, le coréen, le portugais, le russe, l'arabe, l'hindi et bien d'autres. Chaque langue propose plusieurs options de voix.</p>
</details>
<details><summary>Audiobook Maker fonctionne-t-il sur mobile ?</summary>
<p>Oui. L'application web fonctionne dans tout navigateur moderne sur ordinateur, tablette ou téléphone. Cependant, pour les fichiers EPUB volumineux, un navigateur de bureau est recommandé pour un téléchargement et un traitement plus rapides.</p>
</details>
</section>
""",

    "m4b-format": """
<section>
<h2>Qu'est-ce que le Format M4B ?</h2>
<p><strong>M4B</strong> (MPEG-4 Audiobook) est le format standard pour les livres audio. Basé sur le conteneur MPEG-4 (même famille que la vidéo MP4), le M4B est essentiellement un fichier audio AAC avec des fonctionnalités spéciales conçues spécifiquement pour les livres audio :</p>
<ul>
<li><strong>Marqueurs de chapitres</strong> : Des points de navigation intégrés vous permettent de sauter entre les chapitres</li>
<li><strong>Couverture</strong> : La couverture du livre est intégrée dans les métadonnées du fichier</li>
<li><strong>Signets</strong> : Les lecteurs de livres audio mémorisent votre position d'écoute (même entre appareils avec iCloud)</li>
<li><strong>Métadonnées</strong> : Titre, auteur, narrateur, genre et date de publication sont tous stockés dans le fichier</li>
<li><strong>Vitesse variable</strong> : Les lecteurs peuvent accélérer ou ralentir la lecture sans changer la tonalité</li>
</ul>
<p>Le M4B est le format utilisé par <strong>Apple Books</strong>, <strong>Audible</strong> (Aax est une variante M4B protégée par DRM) et la plupart des applications de livres audio sur iOS et Android.</p>
</section>

<section>
<h2>M4B vs MP3 pour les Livres Audio : Comparaison Complète</h2>
<table>
<thead><tr><th>Fonctionnalité</th><th>M4B</th><th>MP3</th></tr></thead>
<tbody>
<tr><td>Navigation par chapitres</td><td>Marqueurs de chapitres intégrés</td><td>Pas de chapitres intégrés</td></tr>
<tr><td>Couverture</td><td>Intégrée dans le fichier</td><td>Peut être intégrée (ID3) mais pas universellement supportée</td></tr>
<tr><td>Sauvegarde de position</td><td>Oui (tous les lecteurs M4B)</td><td>Dépend du lecteur</td></tr>
<tr><td>Taille du fichier (même qualité)</td><td>~30-40% plus petit (codec AAC)</td><td>Plus grand à qualité égale</td></tr>
<tr><td>Compatibilité</td><td>Apple Books, Audible, BookPlayer, Listen, la plupart des applis de livres audio</td><td>Universelle — tous les appareils</td></tr>
<tr><td>Fichier unique</td><td>Oui — livre entier dans un seul fichier</td><td>Généralement un fichier par chapitre ou un fichier combiné</td></tr>
<tr><td>Synchro des signets</td><td>Oui (écosystème Apple)</td><td>Non</td></tr>
<tr><td>Idéal pour</td><td>Utilisateurs iOS/Mac, collectionneurs de livres audio, longs livres</td><td>Compatibilité maximale, partage, lecteurs simples</td></tr>
</tbody>
</table>
<p><strong>En résumé :</strong> Choisissez M4B si vous utilisez Apple Books ou une application dédiée aux livres audio. Choisissez MP3 si vous devez lire le fichier sur un lecteur MP3 basique ou un autoradio qui ne supporte pas le M4B.</p>
</section>

<section>
<h2>Comment Créer des Fichiers M4B avec Chapitres — Gratuitement</h2>
<p>Créer des fichiers M4B nécessitait auparavant des commandes ffmpeg complexes ou des logiciels payants. <a href="/">Audiobook Maker</a> automatise tout le processus :</p>
<ol>
<li><strong>Téléchargez votre ebook</strong> (EPUB, PDF ou TXT) — les chapitres sont extraits automatiquement</li>
<li><strong>Sélectionnez M4B comme format de sortie</strong> — l'outil gère tout : narration TTS, encodage AAC, marqueurs de chapitres, intégration de la couverture</li>
<li><strong>Téléchargez le fichier M4B</strong> — prêt à être importé dans Apple Books ou tout lecteur compatible M4B</li>
</ol>
<p>Le M4B généré utilise <strong>l'audio AAC à 64 kbps</strong> (optimisé pour la parole), inclut une <strong>couverture 1400×1400</strong> et possède des balises de métadonnées compatibles iTunes. Chaque chapitre apparaît comme un point de navigation dans votre lecteur de livres audio.</p>
</section>

<section>
<h2>Comment Lire les Fichiers M4B</h2>
<p><strong>iOS / Mac :</strong> Apple Books (intégré) — glissez le M4B dans Books ou synchronisez via Finder/iCloud.</p>
<p><strong>Android :</strong> Listen Audiobook Player, Smart Audiobook Player, Sirin — tous prennent en charge le M4B avec chapitres.</p>
<p><strong>Windows :</strong> Apple Books (via iTunes), VLC media player, BookPlayer (Microsoft Store).</p>
<p><strong>Linux :</strong> VLC, Cozy (lecteur de livres audio GTK).</p>
<p><strong>Voiture / Lecteur MP3 basique :</strong> Convertissez en MP3 — la plupart des autoradios ne lisent pas les fichiers M4B.</p>
</section>

<section>
<h2>Questions Fréquentes</h2>
<details><summary>Puis-je convertir un M4B en MP3 ?</summary>
<p>Oui. Vous pouvez utiliser Audiobook Maker pour générer une sortie MP3, ou utiliser ffmpeg pour convertir un M4B existant : <code>ffmpeg -i livre.m4b -acodec libmp3lame -b:a 128k livre.mp3</code>. Notez que les marqueurs de chapitres sont perdus lors de la conversion.</p>
</details>
<details><summary>Puis-je diviser un M4B en chapitres ?</summary>
<p>Oui. Des outils comme <code>m4b-tool</code> ou ffmpeg peuvent diviser les fichiers M4B aux marqueurs de chapitres. Audiobook Maker peut également produire des fichiers MP3 individuels par chapitre si vous préférez des fichiers séparés.</p>
</details>
<details><summary>Quelles applications de livres audio prennent en charge le M4B ?</summary>
<p>Apple Books (iOS/Mac), BookPlayer (iOS), Listen Audiobook Player (Android), Smart Audiobook Player (Android), Bound (iOS), Sirin (Android), VLC (toutes plateformes) et Plex avec le plugin Audnexus.</p>
</details>
<details><summary>Quel débit binaire utiliser pour les livres audio M4B ?</summary>
<p>Audiobook Maker utilise 64 kbps AAC, ce qui est le standard pour le contenu parlé. La parole n'a pas besoin de débits élevés — 64 kbps AAC sonne identique à 128 kbps MP3 pour la narration, mais utilise la moitié de la taille du fichier.</p>
</details>
</section>
""",

    "text-to-speech-audiobook": """
<section>
<h2>Qu'est-ce que la Création de Livres Audio par Synthèse Vocale ?</h2>
<p>La création de livres audio par synthèse vocale (TTS) utilise des voix IA neuronales pour transformer du texte écrit en audio parlé. Contrairement aux anciennes TTS robotiques, les voix neuronales modernes sont étonnamment naturelles — avec une intonation, un rythme et une émotion appropriés. Vous pouvez désormais <strong>transformer n'importe quel texte, ebook ou document en un livre audio au son professionnel</strong> sans engager de narrateur humain.</p>
<p><a href="/">Audiobook Maker</a> combine les meilleurs moteurs TTS gratuits avec une interface web facile à utiliser. Téléchargez des fichiers EPUB, PDF ou TXT et obtenez une sortie MP3, M4B ou Podcast RSS — entièrement gratuitement.</p>
</section>

<section>
<h2>Meilleurs Moteurs TTS Gratuits pour Créer des Livres Audio (2026)</h2>
<table>
<thead><tr><th>Moteur TTS</th><th>Voix</th><th>Langues</th><th>Coût</th><th>Idéal Pour</th></tr></thead>
<tbody>
<tr><td><strong>Microsoft Edge TTS</strong></td><td>400+</td><td>50+</td><td>Gratuit</td><td>Création générale de livres audio, meilleures voix gratuites</td></tr>
<tr><td><strong>Google Cloud TTS (Chirp3-HD)</strong></td><td>50+</td><td>30+</td><td>1M caractères gratuits/mois, puis payant</td><td>Qualité premium, narration expressive</td></tr>
<tr><td><strong>Speechify</strong></td><td>30+</td><td>20+</td><td>Freemium (limité)</td><td>Lecture rapide d'articles, usage mobile</td></tr>
<tr><td><strong>NaturalReader</strong></td><td>100+</td><td>20+</td><td>Freemium (limité)</td><td>Soutien à la dyslexie, éducation</td></tr>
<tr><td><strong>ElevenLabs</strong></td><td>Personnalisées</td><td>30+</td><td>10K caractères gratuits/mois</td><td>Clonage vocal ultra-réaliste</td></tr>
<tr><td><strong>Play.ht</strong></td><td>800+</td><td>140+</td><td>5K caractères gratuits/mois</td><td>Multi-langue, variété de voix</td></tr>
</tbody>
</table>
<p><strong>Audiobook Maker utilise Microsoft Edge TTS par défaut</strong> — il est entièrement gratuit, n'a pas de limites d'utilisation et offre plus de 400 voix. Google TTS Chirp3-HD est disponible pour ceux qui souhaitent une qualité premium. Contrairement à Speechify ou NaturalReader, Audiobook Maker <strong>n'a pas de paywall, ne nécessite pas d'inscription et n'a pas de limites d'utilisation</strong>.</p>
</section>

<section>
<h2>Alternative à Speechify : Pourquoi Choisir Audiobook Maker ?</h2>
<p>Speechify est une application TTS populaire, mais sa version gratuite est très limitée. Voici comment Audiobook Maker se compare :</p>
<ul>
<li><strong>100% gratuit</strong> contre l'abonnement Speechify à 139$/an</li>
<li><strong>Aucune limite d'utilisation</strong> — convertissez des livres entiers, pas seulement des textes courts</li>
<li><strong>Sortie M4B avec chapitres</strong> — Speechify exporte uniquement de l'audio simple</li>
<li><strong>Flux Podcast RSS</strong> — écoutez dans n'importe quelle application de podcast</li>
<li><strong>Open source</strong> — licence AGPL-3.0, vous pouvez inspecter et modifier le code</li>
<li><strong>Option auto-hébergée</strong> — exécutez-le sur votre propre serveur pour une confidentialité totale</li>
<li><strong>Optimisation IA du texte</strong> — nettoie et améliore automatiquement le texte pour une meilleure narration</li>
</ul>
<p>Si vous avez besoin d'une <strong>alternative gratuite à Speechify</strong> pour des livres complets, Audiobook Maker est la meilleure option disponible.</p>
</section>

<section>
<h2>Comment Créer un Livre Audio avec des Voix IA — Pas à Pas</h2>
<ol>
<li><strong>Téléchargez votre fichier</strong> — EPUB, PDF ou texte brut (TXT). L'outil détecte automatiquement les chapitres et extrait les métadonnées.</li>
<li><strong>Choisissez une voix</strong> — Parcourez plus de 400 voix neuronales. Chaque voix a un aperçu pour l'écouter avant la conversion.</li>
<li><strong>Sélectionnez le format de sortie</strong> — MP3 pour une compatibilité universelle, M4B pour Apple Books avec chapitres, ou Podcast RSS pour le streaming.</li>
<li><strong>Générez</strong> — L'IA narre votre livre chapitre par chapitre. La progression est affichée en temps réel.</li>
<li><strong>Téléchargez et écoutez</strong> — Obtenez votre livre audio en fichier unique, ZIP des chapitres, ou abonnez-vous au flux podcast privé.</li>
</ol>
</section>

<section>
<h2>Livre Audio TTS Gratuit vs Narrateur Humain</h2>
<table>
<thead><tr><th>Aspect</th><th>IA TTS (Audiobook Maker)</th><th>Narrateur Humain</th></tr></thead>
<tbody>
<tr><td>Coût</td><td>Gratuit</td><td>500-5.000€+ par livre</td></tr>
<tr><td>Temps</td><td>~1 heure</td><td>2-6 semaines</td></tr>
<tr><td>Qualité</td><td>Très bonne (neuronale, naturelle)</td><td>Excellente (expressivité humaine)</td></tr>
<tr><td>Langues</td><td>50+ immédiatement</td><td>Une langue par narrateur</td></tr>
<tr><td>Révisions</td><td>Régénération immédiate</td><td>Nouvel enregistrement nécessaire</td></tr>
<tr><td>Idéal pour</td><td>Usage personnel, brouillons, auteurs indépendants</td><td>Livres audio commerciaux destinés à la vente (Audible, etc.)</td></tr>
</tbody>
</table>
<p>Pour l'écoute personnelle, la révision de vos propres textes ou la création de versions audio de livres du domaine public, la TTS IA est le choix gagnant. Pour les livres audio commerciaux destinés à la vente sur Audible, un narrateur humain est encore préférable (et requis par ACX).</p>
</section>

<section>
<h2>Questions Fréquentes</h2>
<details><summary>La synthèse vocale IA est-elle assez bonne pour les livres audio ?</summary>
<p>Oui. Les TTS neuronales modernes (comme Microsoft Edge TTS et Google Chirp3-HD) sont remarquablement naturelles. La plupart des auditeurs ne font pas la différence avec un narrateur humain pour les ouvrages non fictionnels. Pour la fiction avec plusieurs personnages et une gamme émotionnelle, la narration humaine reste supérieure — mais l'écart se comble rapidement.</p>
</details>
<details><summary>Puis-je utiliser des livres audio générés par IA à des fins commerciales ?</summary>
<p>Oui, avec quelques précisions. Microsoft Edge TTS et Google TTS autorisent l'utilisation commerciale de l'audio généré. Cependant, des plateformes comme Audible (ACX) exigent actuellement une narration humaine pour les nouvelles soumissions. Les livres audio IA peuvent être vendus sur d'autres plateformes ou utilisés pour des projets personnels, des vidéos YouTube et du contenu éducatif.</p>
</details>
<details><summary>Combien de caractères puis-je convertir gratuitement ?</summary>
<p>Avec Microsoft Edge TTS : illimité. Il n'y a pas de limites ni de quotas d'utilisation. Avec Google Cloud TTS Chirp3-HD : 1 million de caractères par mois gratuits, puis les tarifs standard de Google Cloud s'appliquent.</p>
</details>
<details><summary>Audiobook Maker fonctionne-t-il hors ligne ?</summary>
<p>La version hébergée sur audiobook-maker.com nécessite une connexion internet. Cependant, le logiciel est open source — vous pouvez l'installer sur votre ordinateur ou serveur et l'exécuter localement avec toutes les capacités hors ligne.</p>
</details>
<details><summary>Quelle est la meilleure voix TTS pour les livres audio en français ?</summary>
<p>Les meilleures voix Edge TTS pour le français sont <strong>Denise</strong> (féminine chaleureuse) et <strong>Henri</strong> (masculin clair). Pour une qualité premium, Google Chirp3-HD offre les voix neuronales les plus expressives. <a href="/">Essayez l'aperçu gratuit sur Audiobook Maker</a> pour trouver votre préférée.</p>
</details>
</section>
""",

    "podcast": """
<section>
<h2>Transformez Votre Livre Audio en Podcast Privé</h2>
<p>Audiobook Maker génère, avec les fichiers audio, un <strong>package podcast complet</strong> avec un flux RSS 2.0. Pour le rendre disponible comme podcast, les fichiers doivent être publiés sur un serveur web accessible depuis Internet. La solution idéale est votre <strong>propre site web</strong> ou espace d'hébergement. Alternativement, pour un usage personnel ou le partage avec quelques amis, vous pouvez utiliser une solution gratuite comme <strong>Netlify</strong>, décrite dans ce guide.</p>
<div style="background:#fff3cd;border-left:4px solid #f0c040;padding:10px 14px;border-radius:6px;margin:0 0 18px;font-size:.92rem;color:#5a4510"><strong>Usage recommandé :</strong> cette solution est conçue pour un usage personnel ou le partage avec la famille et les amis. Netlify offre 100 Go/mois de bande passante gratuite — largement suffisant. Pour une distribution publique, envisagez d'utiliser votre propre hébergement web.</div>
</section>

<section>
<h2>Pas à Pas : Publiez Votre Livre Audio comme Podcast</h2>
<ol>
<li><strong>Générez le livre audio au format M4B</strong> — Dans Audiobook Maker, téléchargez votre fichier EPUB ou PDF, choisissez la langue et la voix, puis sélectionnez <strong>M4B</strong> comme format de sortie. L'outil crée un fichier M4B unique avec chapitres intégrés et couverture — le standard professionnel pour les livres audio.</li>
<li><strong>Générez aussi le package Podcast RSS</strong> — Après avoir généré le M4B, relancez la génération en mode <strong>Podcast RSS</strong> pour obtenir un ZIP contenant le fichier XML du flux RSS et les fichiers MP3 individuels des chapitres (les podcasts nécessitent un fichier audio par épisode).</li>
<li><strong>Créez un compte Netlify gratuit</strong> — Allez sur <strong>app.netlify.com</strong> et inscrivez-vous avec email ou GitHub. Aucune carte de crédit requise. Le forfait gratuit inclut 100 Go de bande passante, 10 Go de stockage et HTTPS automatique.</li>
<li><strong>Téléchargez sur Netlify</strong> — Dans le tableau de bord Netlify, sous <strong>Sites</strong>, faites glisser le dossier extrait entier sur la zone de dépôt en pointillés. Le site sera en ligne en quelques secondes. Renommez-le depuis <em>Site configuration → Change site name</em> (ex. <code>mon-livre-audio.netlify.app</code>).</li>
<li><strong>Vérifiez le flux</strong> — Ouvrez l'URL du flux dans votre navigateur : <br><code>https://votre-nom-site.netlify.app/podcast.xml</code><br>Si vous voyez du contenu XML avec les titres de vos chapitres, votre podcast est en ligne et prêt !</li>
</ol>
</section>

<section>
<h2>Importez Votre Podcast dans les Applications d'Écoute</h2>
<table>
<thead><tr><th>App</th><th>Plateforme</th><th>Comment l'Ajouter</th></tr></thead>
<tbody>
<tr><td><strong>Apple Podcasts</strong></td><td>iOS / Mac</td><td><strong>iPhone :</strong> Bibliothèque → Plus → Ajouter une émission par URL → collez l'URL du flux<br><strong>Mac :</strong> Fichier → Suivre une émission par URL</td></tr>
<tr><td><strong>Pocket Casts</strong></td><td>Android / iOS / Web</td><td>Rechercher → collez l'URL du flux → S'abonner</td></tr>
<tr><td><strong>AntennaPod</strong></td><td>Android</td><td>+ → Ajouter un Podcast par URL → collez l'URL</td></tr>
<tr><td><strong>Overcast</strong></td><td>iOS</td><td>+ → Ajouter une URL → collez l'URL du flux</td></tr>
<tr><td><strong>Podcast Addict</strong></td><td>Android</td><td>+ → Flux RSS → collez l'URL</td></tr>
</tbody>
</table>
<div style="background:#fff0f0;border-left:4px solid #e04040;padding:8px 14px;border-radius:6px;margin:12px 0;font-size:.9rem;color:#802020"><strong>Note :</strong> Spotify ne prend pas en charge l'ajout de flux RSS privés. Utilisez l'une des applications listées ci-dessus.</div>
</section>

<section>
<h2>Pourquoi Écouter Votre Livre Audio comme Podcast ?</h2>
<ul>
<li><strong>Signets automatiques</strong> — Reprenez exactement là où vous vous étiez arrêté, même entre différents appareils</li>
<li><strong>Ordre des épisodes</strong> — Les chapitres sont lus dans l'ordre avec passage automatique au suivant</li>
<li><strong>Métadonnées complètes</strong> — Couverture, titres des chapitres et infos sur le livre visibles dans votre app podcast</li>
<li><strong>Vitesse réglable</strong> — Écoutez à 1,5x, 2x ou toute vitesse de votre choix, avec minuteur d'arrêt</li>
<li><strong>Streaming</strong> — Pas besoin de télécharger tous les fichiers ; écoutez chaque chapitre en streaming</li>
<li><strong>Partagez avec la famille</strong> — Envoyez l'URL du flux aux membres de la famille ; ils n'ont pas besoin d'un compte Netlify</li>
</ul>
</section>

<section>
<h2>Conseils pour la Publication de Podcast</h2>
<ul>
<li><strong>Mettre à jour les épisodes :</strong> Re-téléchargez les fichiers sur Netlify pour remplacer la version précédente. Votre app podcast détectera les changements à la prochaine actualisation.</li>
<li><strong>Plusieurs livres :</strong> Créez un site Netlify séparé pour chaque livre audio afin de garder les flux organisés.</li>
<li><strong>Limites de stockage :</strong> Le forfait gratuit Netlify inclut 10 Go de stockage (~12 livres audio complets). Supprimez les livres terminés pour libérer de l'espace.</li>
<li><strong>Confidentialité :</strong> L'URL du podcast est techniquement publique (toute personne ayant le lien peut s'abonner), mais n'apparaîtra pas dans les annuaires de podcasts ou les moteurs de recherche. C'est "privé" dans le sens où il n'est pas indexé.</li>
<li><strong>Domaine personnalisé :</strong> Netlify prend en charge les domaines personnalisés dans le forfait gratuit si vous souhaitez une URL personnalisée.</li>
</ul>
</section>

<section>
<h2>Questions Fréquentes</h2>
<details><summary>Netlify est-il vraiment gratuit pour héberger mon podcast ?</summary>
<p>Oui. Le forfait Starter gratuit de Netlify inclut 100 Go/mois de bande passante et 10 Go de stockage. Pour un podcast de livre audio typique (10-20 épisodes, ~5 Mo chacun), c'est plus que suffisant pour un usage personnel. Si vous dépassez les limites, vous pouvez passer à Netlify Pro (19$/mois) ou utiliser votre propre hébergement.</p>
</details>
<details><summary>Pourquoi utiliser le format M4B plutôt que MP3 pour le livre audio ?</summary>
<p>Le M4B est le standard professionnel pour les livres audio. Un seul fichier M4B contient tous les chapitres comme marqueurs de navigation, la couverture intégrée et les métadonnées. Il est pris en charge par Apple Books, Audible et toutes les principales applications de livres audio. Le MP3 est excellent pour une compatibilité maximale, mais le M4B offre une bien meilleure expérience d'écoute avec la navigation par chapitres.</p>
</details>
<details><summary>Puis-je soumettre mon podcast aux annuaires Apple Podcasts ou Spotify ?</summary>
<p>Pas avec un flux Netlify privé. Apple Podcasts Connect et Spotify for Podcasters exigent des flux hébergés sur des plateformes approuvées avec des exigences spécifiques (taille de la pochette, catégories, etc.). L'approche Netlify est pour des <strong>podcasts privés personnels</strong> — idéale pour écouter vos propres livres ou partager avec des amis proches et la famille.</p>
</details>
<details><summary>Que puis-je utiliser si je ne veux pas Netlify ?</summary>
<p>Tout hébergement web statique fonctionne : GitHub Pages, Cloudflare Pages, Vercel ou votre propre serveur web. Téléchargez simplement le dossier du podcast extrait à n'importe quel emplacement accessible via le web et l'URL du flux RSS fonctionnera dans les applications de podcast. Netlify est recommandé car il est gratuit, rapide et ne nécessite aucune configuration.</p>
</details>
<details><summary>Les applications de podcast peuvent-elles télécharger des épisodes pour l'écoute hors ligne ?</summary>
<p>Oui. Une fois abonné au flux dans une application de podcast, vous pouvez télécharger des épisodes individuels pour l'écoute hors ligne, comme n'importe quel autre podcast. L'application gère automatiquement le téléchargement, la position de lecture et la suppression.</p>
</details>
</section>
""",

    "gemini-tts": """
<p>Gemini TTS est le moteur neuronal des voix PREMIUM d'Audiobook Maker. Ce guide présente les voix disponibles, les langues prises en charge et comment orienter la lecture à l'aide de prompts.</p>

<h2 id="voices">Options de voix</h2>
<p>30 voix distinctes, chacune avec son propre caractère. Le nom de la voix est fixe ; le descripteur résume son ton naturel.</p>
<table>
  <thead><tr><th>Voix</th><th>Caractère</th></tr></thead>
  <tbody>
    <tr><td>Zephyr</td><td>Lumineux</td></tr>
    <tr><td>Puck</td><td>Enjoué</td></tr>
    <tr><td>Charon</td><td>Informatif</td></tr>
    <tr><td>Kore</td><td>Ferme</td></tr>
    <tr><td>Fenrir</td><td>Exalté</td></tr>
    <tr><td>Leda</td><td>Jeune</td></tr>
    <tr><td>Orus</td><td>Ferme</td></tr>
    <tr><td>Aoede</td><td>Désinvolte</td></tr>
    <tr><td>Callirrhoe</td><td>Décontracté</td></tr>
    <tr><td>Autonoe</td><td>Lumineux</td></tr>
    <tr><td>Enceladus</td><td>Soufflé</td></tr>
    <tr><td>Iapetus</td><td>Clair</td></tr>
    <tr><td>Umbriel</td><td>Décontracté</td></tr>
    <tr><td>Algieba</td><td>Doux</td></tr>
    <tr><td>Despina</td><td>Doux</td></tr>
    <tr><td>Erinome</td><td>Clair</td></tr>
    <tr><td>Algenib</td><td>Rocailleux</td></tr>
    <tr><td>Rasalgethi</td><td>Informatif</td></tr>
    <tr><td>Laomedeia</td><td>Enjoué</td></tr>
    <tr><td>Achernar</td><td>Tendre</td></tr>
    <tr><td>Alnilam</td><td>Ferme</td></tr>
    <tr><td>Schedar</td><td>Égal</td></tr>
    <tr><td>Gacrux</td><td>Mûr</td></tr>
    <tr><td>Pulcherrima</td><td>Direct</td></tr>
    <tr><td>Achird</td><td>Amical</td></tr>
    <tr><td>Zubenelgenubi</td><td>Détendu</td></tr>
    <tr><td>Vindemiatrix</td><td>Délicat</td></tr>
    <tr><td>Sadachbia</td><td>Vif</td></tr>
    <tr><td>Sadaltager</td><td>Savant</td></tr>
    <tr><td>Sulafat</td><td>Chaleureux</td></tr>
  </tbody>
</table>

<h2 id="languages">Langues prises en charge</h2>
<p>Gemini TTS prend en charge les langues suivantes (code BCP-47 entre parenthèses) :</p>
<p>Arabic (ar), Filipino (fil), Bangla (bn), Finnish (fi), Dutch (nl), Galician (gl), English (en), Georgian (ka), French (fr), Greek (el), German (de), Gujarati (gu), Hindi (hi), Haitian Creole (ht), Indonesian (id), Hebrew (he), Italian (it), Hungarian (hu), Japanese (ja), Icelandic (is), Korean (ko), Javanese (jv), Marathi (mr), Kannada (kn), Polish (pl), Konkani (kok), Portuguese (pt), Romanian (ro), Russian (ru), Spanish (es), Tamil (ta), Telugu (te), Thai (th), Turkish (tr), Ukrainian (uk), Vietnamese (vi), Afrikaans (af), Albanian (sq), Amharic (am), Armenian (hy), Azerbaijani (az), Basque (eu), Belarusian (be), Bulgarian (bg), Burmese (my), Catalan (ca), Cebuano (ceb), Chinese Mandarin (cmn), Croatian (hr), Czech (cs), Danish (da), Estonian (et), Latvian (lv), Lithuanian (lt), Luxembourgish (lb), Macedonian (mk), Maithili (mai), Malagasy (mg), Malay (ms), Malayalam (ml), Mongolian (mn), Nepali (ne), Norwegian Bokm&aring;l (nb), Norwegian Nynorsk (nn), Odia (or), Pashto (ps), Persian (fa), Punjabi (pa), Serbian (sr), Sindhi (sd), Sinhala (si), Slovak (sk), Slovenian (sl), Swahili (sw), Swedish (sv), Urdu (ur).</p>

<h2 id="prompting">Guide de prompting</h2>
<p>Le modèle déduit automatiquement la lecture à partir du texte. Vous pouvez l'orienter davantage avec des balises en ligne et des indications structurées.</p>
<h3>Balises audio en ligne</h3>
<p>Des modificateurs en ligne comme <code>[whispers]</code>, <code>[laughs]</code>, <code>[excitedly]</code>, <code>[bored]</code> et <code>[shouting]</code> modifient le ton, le rythme et la qualité émotionnelle. Soyez créatif et expérimentez différentes interprétations.</p>
<h3>Éléments de prompting avancés</h3>
<ul>
  <li><strong>Audio Profile</strong> &mdash; nom et rôle du personnage.</li>
  <li><strong>Scene</strong> &mdash; contexte environnemental qui définit l'ambiance et le décor.</li>
  <li><strong>Director&rsquo;s Notes</strong> &mdash; indications de jeu : style, rythme, accent.</li>
  <li><strong>Sample Context</strong> &mdash; ancrage contextuel pour une entrée naturelle dans l'interprétation.</li>
  <li><strong>Transcript</strong> &mdash; les mots exacts à prononcer, accompagnés des balises audio.</li>
</ul>
<h3>Conseils clés</h3>
<p>Inutile de tout décrire : laisser de la marge au modèle favorise souvent le naturel. Équilibrez précision et liberté créative, et préférez la terminologie du métier et des caractéristiques nuancées aux simples étiquettes émotionnelles.</p>
<h3>Comment utiliser les prompts dans Audiobook Maker</h3>
<p>Audiobook Maker lit directement le texte des chapitres ; vous insérez donc les indications de prompt dans le texte lui-même, de deux façons :</p>
<ul>
  <li>Modifiez le fichier <strong>TXT</strong> d'entrée avant le téléversement, en insérant les balises/indications directement dans le texte.</li>
  <li>Ou téléchargez le fichier <strong>.ABM</strong> généré, modifiez les textes des chapitres et téléversez à nouveau le <strong>.ABM</strong> modifié sur Audiobook Maker.</li>
</ul>
<p style="font-size:.85rem;color:var(--txm)">Source: <a href="https://ai.google.dev/gemini-api/docs/speech-generation" rel="nofollow noopener" target="_blank">Google AI &mdash; Speech generation</a></p>
""",
}


_GUIDE_BODY_ES = {
    "free-ebooks": """
<section>
<h2>Dónde Encontrar Ebooks Gratis para Descargar</h2>
<p>Miles de grandes libros son totalmente gratuitos y legales de descargar — clásicos de dominio público, títulos modernos publicados con licencias abiertas y proyectos comunitarios. Una vez que tengas un EPUB gratuito, puedes convertirlo en audiolibro en minutos con <a href="/">Audiobook Maker</a>. Esta guía enumera las mejores fuentes de ebooks gratuitos y te muestra cómo escucharlos.</p>
</section>

<section>
<h2>Los 8 Mejores Sitios de Ebooks Gratis</h2>
<ul>
<li><a href="https://www.gutenberg.org" target="_blank" rel="noopener">Project Gutenberg</a> — Más de 70.000 libros gratuitos de dominio público. La colección más grande y antigua del mundo, con descargas EPUB fiables.</li>
<li><a href="https://standardebooks.org" target="_blank" rel="noopener">Standard Ebooks</a> — Ediciones cuidadas y bellamente formateadas de clásicos, con tipografía moderna y portadas originales.</li>
<li><a href="https://archive.org/details/texts" target="_blank" rel="noopener">Internet Archive</a> — Una enorme biblioteca digital con millones de textos, audiolibros y publicaciones históricas.</li>
<li><a href="https://manybooks.net" target="_blank" rel="noopener">ManyBooks</a> — Más de 50.000 ebooks gratuitos con una interfaz moderna y recomendaciones de lectura personalizadas.</li>
<li><a href="https://www.feedbooks.com/publicdomain" target="_blank" rel="noopener">Feedbooks</a> — Un catálogo elegante de ebooks de dominio público con descarga directa y sin complicaciones.</li>
<li><a href="https://books.google.com/books?&as_ebook=on&as_brr=1" target="_blank" rel="noopener">Google Books</a> — Millones de libros digitalizados; filtra por "Ebooks gratuitos" para encontrar los títulos gratis.</li>
<li><a href="https://www.liberliber.it/online/opere/libri/" target="_blank" rel="noopener">Liber Liber</a> — La referencia para los clásicos de la literatura italiana: Dante, Manzoni, Pirandello y muchos más.</li>
<li><a href="https://openlibrary.org/read" target="_blank" rel="noopener">Open Library</a> — Préstamo digital gratuito de ebooks modernos y clásicos, gestionado por Internet Archive.</li>
</ul>
</section>

<section>
<h2>Dominio Público vs. Libros con Derechos de Autor</h2>
<p>Los libros de <strong>dominio público</strong> — normalmente obras cuyo autor falleció hace más de 70 años — son libres de descargar, compartir y convertir sin restricciones. Project Gutenberg, Standard Ebooks y Liber Liber están especializados en estos.</p>
<p>Los libros <strong>con derechos de autor</strong> están protegidos incluso cuando se ofrecen gratis. Muchos autores y editoriales publican títulos modernos con licencias <a href="https://creativecommons.org" target="_blank" rel="noopener">Creative Commons</a> o como promociones gratuitas: son perfectamente legales de descargar. Evita los sitios piratas que comparten ebooks comerciales sin autorización: son ilegales y a menudo incluyen malware.</p>
</section>

<section>
<h2>Cómo Convertir un Ebook Gratis en Audiolibro</h2>
<ol>
<li><strong>Descarga el EPUB</strong> desde cualquiera de los sitios anteriores (el EPUB es preferible al PDF para una detección de capítulos más limpia).</li>
<li><strong>Abre <a href="/">Audiobook Maker</a></strong> y sube el archivo — capítulos, título, autor y portada se extraen automáticamente.</li>
<li><strong>Elige una voz IA neuronal</strong> entre más de 400 opciones en más de 50 idiomas y escucha una vista previa gratuita.</li>
<li><strong>Elige tu formato</strong> — MP3 para máxima compatibilidad, o <a href="/guide/m4b-format/">M4B</a> con capítulos y portada integrados.</li>
<li><strong>Genera y descarga</strong> — escucha en tu móvil, tablet o cualquier reproductor de audiolibros.</li>
</ol>
<p>Consulta la guía completa <a href="/guide/epub-to-audiobook/">EPUB a audiolibro →</a> para más detalles.</p>
</section>

<section>
<h2>Consejos para Elegir el Ebook Gratis Adecuado</h2>
<ul>
<li><strong>Prefiere EPUB antes que PDF</strong>: el EPUB tiene una estructura de capítulos limpia, mientras que los PDF pueden incluir encabezados, números de página y artefactos de maquetación que requieren limpieza.</li>
<li><strong>Comprueba la edición</strong>: Standard Ebooks y Liber Liber ofrecen las versiones mejor formateadas de los clásicos, con menos erratas y errores de OCR.</li>
<li><strong>Usa la optimización IA del texto</strong>: para PDF o escaneos en bruto, la limpieza IA opcional de Audiobook Maker elimina notas al pie, guiones de sílaba y artefactos antes de la narración.</li>
<li><strong>Atención al idioma</strong>: elige una voz que coincida con el idioma del libro para una pronunciación natural.</li>
</ul>
</section>

<section>
<h2>Preguntas Frecuentes</h2>
<details><summary>¿Es legal descargar ebooks gratis?</summary>
<p>Sí, cuando el libro es de dominio público o lo ofrece gratis el autor o la editorial. Todos los sitios listados en esta guía distribuyen libros legalmente. Evita los sitios piratas que comparten títulos comerciales con derechos de autor sin autorización.</p>
</details>
<details><summary>¿Cuál es el mejor formato para descargar y crear un audiolibro?</summary>
<p>El EPUB es el mejor: tiene una estructura de capítulos limpia que se convierte de forma fiable. El PDF también funciona, pero puede necesitar la optimización IA del texto para eliminar artefactos de maquetación. El TXT sirve para texto plano sin capítulos.</p>
</details>
<details><summary>¿Puedo convertir estos ebooks gratis en audiolibros gratis?</summary>
<p>Sí. Audiobook Maker convierte EPUB, PDF y TXT en audiolibros MP3 o M4B gratis usando voces TTS neuronales, sin registro y sin límites de uso.</p>
</details>
<details><summary>¿Dónde encuentro ebooks gratis en idiomas distintos del inglés?</summary>
<p>Project Gutenberg e Internet Archive alojan libros en decenas de idiomas. Liber Liber está especializado en italiano, y Google Books permite filtrar los títulos gratis por idioma. Audiobook Maker luego los narra en más de 50 idiomas.</p>
</details>
</section>
""",

    "epub-to-audiobook": """
<section>
<h2>¿Por Qué Convertir EPUB a Audiolibro?</h2>
<p>EPUB es el formato de ebook más popular, utilizado por Apple Books, Google Play Books, Kobo y la mayoría de las bibliotecas digitales. Convertir EPUB a audiolibro te permite <strong>escuchar tus ebooks</strong> mientras viajas, haces ejercicio o realizas tareas domésticas. Las voces modernas de texto a voz con IA suenan sorprendentemente naturales, muy superiores a los lectores de pantalla robóticos del pasado.</p>
<p>Con <a href="/">Audiobook Maker</a>, puedes convertir cualquier EPUB sin DRM a audiolibro MP3 o M4B gratis, directamente en tu navegador. Sin software que instalar, sin necesidad de cuenta.</p>
</section>

<section>
<h2>Cómo Convertir EPUB a Audiolibro — Paso a Paso</h2>
<ol>
<li><strong>Sube tu archivo EPUB</strong> — Arrastra y suelta o haz clic para seleccionar. La herramienta extrae automáticamente capítulos y metadatos (título, autor, portada).</li>
<li><strong>Elige tu voz TTS</strong> — Selecciona entre más de 400 voces neuronales de IA en más de 50 idiomas. Escucha una muestra antes de iniciar la conversión completa.</li>
<li><strong>Selecciona los capítulos</strong> — Elige qué capítulos incluir. Omite el índice, las páginas de derechos de autor o cualquier sección que no quieras que se narre.</li>
<li><strong>Elige el formato de salida</strong> — <strong>MP3</strong> (archivo único o ZIP por capítulo), <strong>M4B</strong> (archivo único con capítulos y portada integrados — ideal para Apple Books y reproductores de audiolibros), o <strong>Podcast RSS</strong> (feed de podcast privado).</li>
<li><strong>Haz clic en "Generar"</strong> — El motor TTS narra cada capítulo. Verás una barra de progreso y recibirás una notificación por email cuando termine.</li>
<li><strong>Descarga y escucha</strong> — Descarga tu audiolibro y empieza a escuchar en cualquier dispositivo.</li>
</ol>
</section>

<section>
<h2>Mejores Voces para la Conversión de EPUB a Audiolibro</h2>
<p>Audiobook Maker utiliza <strong>Microsoft Edge neural TTS</strong> (el mismo motor detrás de Azure Cognitive Services). Estas son las voces gratuitas más naturales disponibles:</p>
<ul>
<li><strong>Inglés (US)</strong>: Aria, Jenny, Guy, Davis, Jane — narración cálida y expresiva</li>
<li><strong>Inglés (UK)</strong>: Sonia, Ryan, Libby — excelente para literatura británica</li>
<li><strong>Italiano</strong>: Isabella, Diego, Elsa — narración italiana natural</li>
<li><strong>Francés</strong>: Denise, Henri — pronunciación francesa clara</li>
<li><strong>Alemán</strong>: Katja, Conrad — habla alemana nítida</li>
<li><strong>Español</strong>: Elvira, Álvaro — narración fluida en español</li>
<li><strong>Chino</strong>: Xiaoxiao, Yunyang — habla mandarín natural</li>
</ul>
<p>Google Cloud TTS Chirp3-HD también está disponible para una calidad aún mayor (primer millón de caracteres gratis al mes).</p>
</section>

<section>
<h2>EPUB a MP3 vs EPUB a M4B: ¿Qué Formato Elegir?</h2>
<p><strong>MP3</strong> es universalmente compatible — todos los teléfonos, tabletas y ordenadores reproducen archivos MP3. Elige MP3 si buscas máxima compatibilidad o planeas escuchar en múltiples dispositivos.</p>
<p><strong>M4B</strong> es el formato profesional de audiolibros. Es un archivo único que contiene todos los capítulos como marcadores de navegación, además de portada y metadatos integrados (autor, título, género). Los archivos M4B son compatibles con Apple Books, Audible y la mayoría de las aplicaciones de audiolibros. <a href="/guide/m4b-format/">Más información sobre el formato M4B →</a></p>
</section>

<section>
<h2>Consejos para la Mejor Experiencia de EPUB a Audiolibro</h2>
<ul>
<li><strong>Elimina primero el DRM</strong>: Los ebooks comerciales de Kindle, Apple Books o Kobo suelen tener protección DRM. Deberás eliminarla antes de la conversión (solo para uso personal, donde sea legalmente permitido).</li>
<li><strong>Limpia el texto</strong>: Algunos EPUB tienen artefactos de formato (números de página, encabezados, notas al pie). La optimización de texto con IA opcional de Audiobook Maker puede limpiarlos automáticamente.</li>
<li><strong>Previsualiza antes de la generación completa</strong>: Genera siempre primero la vista previa gratuita para comprobar la calidad de la voz y el ritmo.</li>
<li><strong>Usa el selector de capítulos</strong>: Omite las páginas preliminares (índice, prefacio) y finales (índice alfabético, anuncios) para una experiencia de escucha más limpia.</li>
<li><strong>Elige M4B para libros largos</strong>: El formato M4B mantiene todo organizado en un solo archivo con navegación por capítulos — mucho mejor que manejar múltiples archivos MP3.</li>
</ul>
</section>

<section>
<h2>Preguntas Frecuentes</h2>
<details><summary>¿Es realmente gratis convertir EPUB a audiolibro?</summary>
<p>Sí. Audiobook Maker es software de código abierto (AGPL-3.0). La conversión TTS utiliza Microsoft Edge TTS, que es gratuito y sin límites de uso. La optimización de texto con IA opcional (DeepSeek LLM) tiene un pequeño costo por encima de un umbral gratuito.</p>
</details>
<details><summary>¿Puedo convertir libros Kindle a audiolibros?</summary>
<p>Los libros Kindle usan el formato propietario AZW/KFX de Amazon con DRM. Primero deberás eliminar el DRM y convertir a EPUB usando una herramienta como Calibre, luego subir el EPUB a Audiobook Maker.</p>
</details>
<details><summary>¿Cuánto tarda la conversión de EPUB a audiolibro?</summary>
<p>Aproximadamente 2-3 minutos por capítulo (varía según la longitud del capítulo y la carga del servidor). Un libro típico de 300 páginas (~20 capítulos) tarda unos 40-60 minutos. Recibirás una notificación por email cuando esté listo.</p>
</details>
<details><summary>¿Qué idiomas son compatibles?</summary>
<p>Más de 50 idiomas, incluyendo inglés, italiano, francés, español, alemán, chino, japonés, coreano, portugués, ruso, árabe, hindi y muchos más. Cada idioma tiene múltiples opciones de voz.</p>
</details>
<details><summary>¿Funciona Audiobook Maker en el móvil?</summary>
<p>Sí. La aplicación web funciona en cualquier navegador moderno en ordenador, tableta o teléfono. Sin embargo, para archivos EPUB grandes, se recomienda un navegador de escritorio para una carga y procesamiento más rápidos.</p>
</details>
</section>
""",

    "m4b-format": """
<section>
<h2>¿Qué es el Formato M4B?</h2>
<p><strong>M4B</strong> (MPEG-4 Audiobook) es el formato estándar para audiolibros. Basado en el contenedor MPEG-4 (misma familia que el video MP4), M4B es esencialmente un archivo de audio AAC con funciones especiales diseñadas específicamente para audiolibros:</p>
<ul>
<li><strong>Marcadores de capítulos</strong>: Puntos de navegación integrados que permiten saltar entre capítulos</li>
<li><strong>Portada</strong>: La portada del libro se incrusta en los metadatos del archivo</li>
<li><strong>Marcadores</strong>: Los reproductores de audiolibros recuerdan tu posición de escucha (incluso entre dispositivos con iCloud)</li>
<li><strong>Metadatos</strong>: Título, autor, narrador, género y fecha de publicación se almacenan en el archivo</li>
<li><strong>Velocidad variable</strong>: Los reproductores pueden acelerar o ralentizar la reproducción sin cambiar el tono</li>
</ul>
<p>M4B es el formato utilizado por <strong>Apple Books</strong>, <strong>Audible</strong> (Aax es una variante M4B con DRM) y la mayoría de las aplicaciones de audiolibros en iOS y Android.</p>
</section>

<section>
<h2>M4B vs MP3 para Audiolibros: Comparación Completa</h2>
<table>
<thead><tr><th>Característica</th><th>M4B</th><th>MP3</th></tr></thead>
<tbody>
<tr><td>Navegación por capítulos</td><td>Marcadores de capítulos integrados</td><td>Sin capítulos integrados</td></tr>
<tr><td>Portada</td><td>Incrustada en el archivo</td><td>Se puede incrustar (ID3) pero no es universalmente compatible</td></tr>
<tr><td>Guardado de posición</td><td>Sí (todos los reproductores M4B)</td><td>Depende del reproductor</td></tr>
<tr><td>Tamaño del archivo (misma calidad)</td><td>~30-40% más pequeño (códec AAC)</td><td>Más grande a igual calidad</td></tr>
<tr><td>Compatibilidad</td><td>Apple Books, Audible, BookPlayer, Listen, la mayoría de apps de audiolibros</td><td>Universal — todos los dispositivos</td></tr>
<tr><td>Archivo único</td><td>Sí — libro completo en un solo archivo</td><td>Generalmente un archivo por capítulo o uno combinado</td></tr>
<tr><td>Sincronización de marcadores</td><td>Sí (ecosistema Apple)</td><td>No</td></tr>
<tr><td>Ideal para</td><td>Usuarios de iOS/Mac, coleccionistas de audiolibros, libros largos</td><td>Máxima compatibilidad, compartir, reproductores simples</td></tr>
</tbody>
</table>
<p><strong>En resumen:</strong> Elige M4B si usas Apple Books o una aplicación dedicada de audiolibros. Elige MP3 si necesitas reproducir el archivo en un reproductor MP3 básico o en el estéreo del coche que no soporta M4B.</p>
</section>

<section>
<h2>Cómo Crear Archivos M4B con Capítulos — Gratis</h2>
<p>Crear archivos M4B solía requerir comandos ffmpeg complejos o software de pago. <a href="/">Audiobook Maker</a> automatiza todo el proceso:</p>
<ol>
<li><strong>Sube tu ebook</strong> (EPUB, PDF o TXT) — los capítulos se extraen automáticamente</li>
<li><strong>Selecciona M4B como formato de salida</strong> — la herramienta se encarga de todo: narración TTS, codificación AAC, marcadores de capítulos, incrustación de portada</li>
<li><strong>Descarga el archivo M4B</strong> — listo para importar en Apple Books o cualquier reproductor compatible con M4B</li>
</ol>
<p>El M4B generado utiliza <strong>audio AAC a 64 kbps</strong> (optimizado para voz), incluye <strong>portada de 1400×1400</strong> y tiene etiquetas de metadatos compatibles con iTunes. Cada capítulo aparece como un punto de navegación en tu reproductor de audiolibros.</p>
</section>

<section>
<h2>Cómo Reproducir Archivos M4B</h2>
<p><strong>iOS / Mac:</strong> Apple Books (integrado) — arrastra el M4B a Books o sincroniza vía Finder/iCloud.</p>
<p><strong>Android:</strong> Listen Audiobook Player, Smart Audiobook Player, Sirin — todos soportan M4B con capítulos.</p>
<p><strong>Windows:</strong> Apple Books (vía iTunes), VLC media player, BookPlayer (Microsoft Store).</p>
<p><strong>Linux:</strong> VLC, Cozy (reproductor de audiolibros GTK).</p>
<p><strong>Coche / Reproductor MP3 básico:</strong> Convierte a MP3 — la mayoría de los estéreos de coche no leen archivos M4B.</p>
</section>

<section>
<h2>Preguntas Frecuentes</h2>
<details><summary>¿Puedo convertir M4B a MP3?</summary>
<p>Sí. Puedes usar Audiobook Maker para generar salida MP3, o usar ffmpeg para convertir un M4B existente: <code>ffmpeg -i libro.m4b -acodec libmp3lame -b:a 128k libro.mp3</code>. Ten en cuenta que los marcadores de capítulos se pierden en la conversión.</p>
</details>
<details><summary>¿Puedo dividir un M4B en capítulos?</summary>
<p>Sí. Herramientas como <code>m4b-tool</code> o ffmpeg pueden dividir archivos M4B en los marcadores de capítulos. Audiobook Maker también puede generar archivos MP3 individuales por capítulo si prefieres archivos separados.</p>
</details>
<details><summary>¿Qué aplicaciones de audiolibros soportan M4B?</summary>
<p>Apple Books (iOS/Mac), BookPlayer (iOS), Listen Audiobook Player (Android), Smart Audiobook Player (Android), Bound (iOS), Sirin (Android), VLC (todas las plataformas) y Plex con el plugin Audnexus.</p>
</details>
<details><summary>¿Qué bitrate debo usar para audiolibros M4B?</summary>
<p>Audiobook Maker utiliza 64 kbps AAC, que es el estándar para contenido de voz. La voz no necesita bitrates altos — 64 kbps AAC suena idéntico a 128 kbps MP3 para narración, pero usa la mitad del tamaño de archivo.</p>
</details>
</section>
""",

    "text-to-speech-audiobook": """
<section>
<h2>¿Qué es la Creación de Audiolibros por Texto a Voz?</h2>
<p>La creación de audiolibros por texto a voz (TTS) utiliza voces de IA neuronal para convertir texto escrito en audio hablado. A diferencia de los antiguos TTS robóticos, las voces neuronales modernas suenan sorprendentemente naturales — con entonación, ritmo y emoción apropiados. Ahora puedes <strong>convertir cualquier texto, ebook o documento en un audiolibro con sonido profesional</strong> sin contratar a un narrador humano.</p>
<p><a href="/">Audiobook Maker</a> combina los mejores motores TTS gratuitos con una interfaz web fácil de usar. Sube archivos EPUB, PDF o TXT y obtén salida MP3, M4B o Podcast RSS — completamente gratis.</p>
</section>

<section>
<h2>Mejores Motores TTS Gratuitos para Crear Audiolibros (2026)</h2>
<table>
<thead><tr><th>Motor TTS</th><th>Voces</th><th>Idiomas</th><th>Coste</th><th>Ideal Para</th></tr></thead>
<tbody>
<tr><td><strong>Microsoft Edge TTS</strong></td><td>400+</td><td>50+</td><td>Gratis</td><td>Creación general de audiolibros, mejores voces gratuitas</td></tr>
<tr><td><strong>Google Cloud TTS (Chirp3-HD)</strong></td><td>50+</td><td>30+</td><td>1M caracteres gratis/mes, luego de pago</td><td>Calidad premium, narración expresiva</td></tr>
<tr><td><strong>Speechify</strong></td><td>30+</td><td>20+</td><td>Freemium (limitado)</td><td>Lectura rápida de artículos, uso móvil</td></tr>
<tr><td><strong>NaturalReader</strong></td><td>100+</td><td>20+</td><td>Freemium (limitado)</td><td>Apoyo a la dislexia, educación</td></tr>
<tr><td><strong>ElevenLabs</strong></td><td>Personalizadas</td><td>30+</td><td>10K caracteres gratis/mes</td><td>Clonación de voz ultra-realista</td></tr>
<tr><td><strong>Play.ht</strong></td><td>800+</td><td>140+</td><td>5K caracteres gratis/mes</td><td>Multi-idioma, variedad de voces</td></tr>
</tbody>
</table>
<p><strong>Audiobook Maker utiliza Microsoft Edge TTS por defecto</strong> — es completamente gratuito, no tiene límites de uso y ofrece más de 400 voces. Google TTS Chirp3-HD está disponible para quienes desean calidad premium. A diferencia de Speechify o NaturalReader, Audiobook Maker <strong>no tiene paywall, no requiere registro y no tiene límites de uso</strong>.</p>
</section>

<section>
<h2>Alternativa a Speechify: ¿Por Qué Elegir Audiobook Maker?</h2>
<p>Speechify es una aplicación TTS popular, pero su versión gratuita es muy limitada. Así se compara Audiobook Maker:</p>
<ul>
<li><strong>100% gratis</strong> frente a la suscripción de Speechify de $139/año</li>
<li><strong>Sin límites de uso</strong> — convierte libros completos, no solo textos cortos</li>
<li><strong>Salida M4B con capítulos</strong> — Speechify solo exporta audio simple</li>
<li><strong>Feed Podcast RSS</strong> — escucha en cualquier aplicación de podcast</li>
<li><strong>Código abierto</strong> — licencia AGPL-3.0, puedes inspeccionar y modificar el código</li>
<li><strong>Opción auto-hospedada</strong> — ejecútalo en tu propio servidor para privacidad total</li>
<li><strong>Optimización de texto con IA</strong> — limpia y mejora automáticamente el texto para una mejor narración</li>
</ul>
<p>Si necesitas una <strong>alternativa gratuita a Speechify</strong> para libros completos, Audiobook Maker es la mejor opción disponible.</p>
</section>

<section>
<h2>Cómo Crear un Audiolibro con Voces IA — Paso a Paso</h2>
<ol>
<li><strong>Sube tu archivo</strong> — EPUB, PDF o texto plano (TXT). La herramienta detecta automáticamente los capítulos y extrae los metadatos.</li>
<li><strong>Elige una voz</strong> — Explora más de 400 voces neuronales. Cada voz tiene una vista previa para escucharla antes de la conversión.</li>
<li><strong>Selecciona el formato de salida</strong> — MP3 para compatibilidad universal, M4B para Apple Books con capítulos, o Podcast RSS para streaming.</li>
<li><strong>Genera</strong> — La IA narra tu libro capítulo por capítulo. El progreso se muestra en tiempo real.</li>
<li><strong>Descarga y escucha</strong> — Obtén tu audiolibro como archivo único, ZIP de capítulos o suscríbete al feed de podcast privado.</li>
</ol>
</section>

<section>
<h2>Audiolibro TTS Gratis vs Narrador Humano</h2>
<table>
<thead><tr><th>Aspecto</th><th>IA TTS (Audiobook Maker)</th><th>Narrador Humano</th></tr></thead>
<tbody>
<tr><td>Coste</td><td>Gratis</td><td>500-5.000€+ por libro</td></tr>
<tr><td>Tiempo</td><td>~1 hora</td><td>2-6 semanas</td></tr>
<tr><td>Calidad</td><td>Muy buena (neuronal, natural)</td><td>Excelente (expresividad humana)</td></tr>
<tr><td>Idiomas</td><td>50+ inmediatamente</td><td>Un idioma por narrador</td></tr>
<tr><td>Revisiones</td><td>Regeneración inmediata</td><td>Requiere nueva grabación</td></tr>
<tr><td>Ideal para</td><td>Uso personal, borradores, autores independientes</td><td>Audiolibros comerciales para venta (Audible, etc.)</td></tr>
</tbody>
</table>
<p>Para escucha personal, revisión de tus propios textos o creación de versiones en audio de libros de dominio público, el TTS con IA es la mejor opción. Para audiolibros comerciales destinados a la venta en Audible, un narrador humano sigue siendo preferible (y requerido por ACX).</p>
</section>

<section>
<h2>Preguntas Frecuentes</h2>
<details><summary>¿Es el texto a voz con IA suficientemente bueno para audiolibros?</summary>
<p>Sí. Los TTS neuronales modernos (como Microsoft Edge TTS y Google Chirp3-HD) son notablemente naturales. La mayoría de los oyentes no distingue la diferencia con un narrador humano para no ficción. Para ficción con múltiples personajes y rango emocional, la narración humana sigue siendo superior — pero la brecha se está cerrando rápidamente.</p>
</details>
<details><summary>¿Puedo usar audiolibros generados con IA con fines comerciales?</summary>
<p>Sí, con algunas precisiones. Microsoft Edge TTS y Google TTS permiten el uso comercial del audio generado. Sin embargo, plataformas como Audible (ACX) requieren actualmente narración humana para nuevos envíos. Los audiolibros con IA pueden venderse en otras plataformas o usarse para proyectos personales, videos de YouTube y contenido educativo.</p>
</details>
<details><summary>¿Cuántos caracteres puedo convertir gratis?</summary>
<p>Con Microsoft Edge TTS: ilimitados. No hay límites ni cuotas de uso. Con Google Cloud TTS Chirp3-HD: 1 millón de caracteres al mes gratis, luego se aplican las tarifas estándar de Google Cloud.</p>
</details>
<details><summary>¿Funciona Audiobook Maker sin conexión?</summary>
<p>La versión alojada en audiobook-maker.com requiere conexión a internet. Sin embargo, el software es de código abierto — puedes instalarlo en tu ordenador o servidor y ejecutarlo localmente con plena capacidad sin conexión.</p>
</details>
<details><summary>¿Cuál es la mejor voz TTS para audiolibros en español?</summary>
<p>Las mejores voces Edge TTS para español son <strong>Elvira</strong> (femenina clara) y <strong>Álvaro</strong> (masculino fluido). Para calidad premium, Google Chirp3-HD ofrece las voces neuronales más expresivas. <a href="/">Prueba la vista previa gratuita en Audiobook Maker</a> para encontrar tu favorita.</p>
</details>
</section>
""",

    "gemini-tts": """
<p>Gemini TTS es el motor neuronal de las voces PREMIUM de Audiobook Maker. Esta guía presenta las voces disponibles, los idiomas compatibles y cómo dirigir la lectura mediante prompts.</p>

<h2 id="voices">Opciones de voz</h2>
<p>30 voces distintas, cada una con su propio carácter. El nombre de la voz es fijo; el descriptor resume su tono natural.</p>
<table>
  <thead><tr><th>Voz</th><th>Carácter</th></tr></thead>
  <tbody>
    <tr><td>Zephyr</td><td>Brillante</td></tr>
    <tr><td>Puck</td><td>Animado</td></tr>
    <tr><td>Charon</td><td>Informativo</td></tr>
    <tr><td>Kore</td><td>Firme</td></tr>
    <tr><td>Fenrir</td><td>Entusiasta</td></tr>
    <tr><td>Leda</td><td>Juvenil</td></tr>
    <tr><td>Orus</td><td>Firme</td></tr>
    <tr><td>Aoede</td><td>Desenfadado</td></tr>
    <tr><td>Callirrhoe</td><td>Relajado</td></tr>
    <tr><td>Autonoe</td><td>Brillante</td></tr>
    <tr><td>Enceladus</td><td>Susurrante</td></tr>
    <tr><td>Iapetus</td><td>Claro</td></tr>
    <tr><td>Umbriel</td><td>Relajado</td></tr>
    <tr><td>Algieba</td><td>Suave</td></tr>
    <tr><td>Despina</td><td>Suave</td></tr>
    <tr><td>Erinome</td><td>Claro</td></tr>
    <tr><td>Algenib</td><td>Áspero</td></tr>
    <tr><td>Rasalgethi</td><td>Informativo</td></tr>
    <tr><td>Laomedeia</td><td>Animado</td></tr>
    <tr><td>Achernar</td><td>Tenue</td></tr>
    <tr><td>Alnilam</td><td>Firme</td></tr>
    <tr><td>Schedar</td><td>Equilibrado</td></tr>
    <tr><td>Gacrux</td><td>Maduro</td></tr>
    <tr><td>Pulcherrima</td><td>Directo</td></tr>
    <tr><td>Achird</td><td>Amistoso</td></tr>
    <tr><td>Zubenelgenubi</td><td>Informal</td></tr>
    <tr><td>Vindemiatrix</td><td>Gentil</td></tr>
    <tr><td>Sadachbia</td><td>Vivaz</td></tr>
    <tr><td>Sadaltager</td><td>Experto</td></tr>
    <tr><td>Sulafat</td><td>Cálido</td></tr>
  </tbody>
</table>

<h2 id="languages">Idiomas compatibles</h2>
<p>Gemini TTS admite los siguientes idiomas (código BCP-47 entre paréntesis):</p>
<p>Arabic (ar), Filipino (fil), Bangla (bn), Finnish (fi), Dutch (nl), Galician (gl), English (en), Georgian (ka), French (fr), Greek (el), German (de), Gujarati (gu), Hindi (hi), Haitian Creole (ht), Indonesian (id), Hebrew (he), Italian (it), Hungarian (hu), Japanese (ja), Icelandic (is), Korean (ko), Javanese (jv), Marathi (mr), Kannada (kn), Polish (pl), Konkani (kok), Portuguese (pt), Romanian (ro), Russian (ru), Spanish (es), Tamil (ta), Telugu (te), Thai (th), Turkish (tr), Ukrainian (uk), Vietnamese (vi), Afrikaans (af), Albanian (sq), Amharic (am), Armenian (hy), Azerbaijani (az), Basque (eu), Belarusian (be), Bulgarian (bg), Burmese (my), Catalan (ca), Cebuano (ceb), Chinese Mandarin (cmn), Croatian (hr), Czech (cs), Danish (da), Estonian (et), Latvian (lv), Lithuanian (lt), Luxembourgish (lb), Macedonian (mk), Maithili (mai), Malagasy (mg), Malay (ms), Malayalam (ml), Mongolian (mn), Nepali (ne), Norwegian Bokm&aring;l (nb), Norwegian Nynorsk (nn), Odia (or), Pashto (ps), Persian (fa), Punjabi (pa), Serbian (sr), Sindhi (sd), Sinhala (si), Slovak (sk), Slovenian (sl), Swahili (sw), Swedish (sv), Urdu (ur).</p>

<h2 id="prompting">Guía de prompting</h2>
<p>El modelo deduce la lectura del texto automáticamente. Puedes dirigirla aún más con etiquetas en línea e indicaciones estructuradas.</p>
<h3>Etiquetas de audio en línea</h3>
<p>Modificadores en línea como <code>[whispers]</code>, <code>[laughs]</code>, <code>[excitedly]</code>, <code>[bored]</code> y <code>[shouting]</code> cambian el tono, el ritmo y la cualidad emocional. Sé creativo y experimenta con distintas interpretaciones.</p>
<h3>Elementos de prompting avanzado</h3>
<ul>
  <li><strong>Audio Profile</strong> &mdash; nombre y rol del personaje.</li>
  <li><strong>Scene</strong> &mdash; contexto ambiental que define el ambiente y el escenario.</li>
  <li><strong>Director&rsquo;s Notes</strong> &mdash; indicaciones de interpretación: estilo, ritmo, acento.</li>
  <li><strong>Sample Context</strong> &mdash; anclaje contextual para una entrada natural en la interpretación.</li>
  <li><strong>Transcript</strong> &mdash; las palabras exactas que se pronuncian, junto con las etiquetas de audio.</li>
</ul>
<h3>Pautas clave</h3>
<p>No es necesario describirlo todo: dar espacio al modelo suele favorecer la naturalidad. Equilibra especificidad y libertad creativa, y prefiere la terminología del sector y características matizadas a las simples etiquetas emocionales.</p>
<h3>Cómo usar los prompts en Audiobook Maker</h3>
<p>Audiobook Maker narra directamente el texto de los capítulos, así que las indicaciones de prompt se insertan en el propio texto, de dos formas:</p>
<ul>
  <li>Edita el archivo <strong>TXT</strong> de entrada antes de subirlo, insertando etiquetas/indicaciones directamente en el texto.</li>
  <li>O descarga el archivo <strong>.ABM</strong> generado, edita los textos de los capítulos y vuelve a subir el <strong>.ABM</strong> modificado a Audiobook Maker.</li>
</ul>
<p style="font-size:.85rem;color:var(--txm)">Fuente: <a href="https://ai.google.dev/gemini-api/docs/speech-generation" rel="nofollow noopener" target="_blank">Google AI &mdash; Speech generation</a></p>
""",

    "podcast": """
<section>
<h2>Convierte Tu Audiolibro en un Podcast Privado</h2>
<p>Audiobook Maker genera, junto con los archivos de audio, un <strong>paquete de podcast completo</strong> con un feed RSS 2.0. Para hacerlo disponible como podcast, los archivos deben publicarse en un servidor web accesible desde Internet. La solución ideal es tu <strong>propio sitio web</strong> o espacio de hosting. Alternativamente, para uso personal o compartir con algunos amigos, puedes usar una solución gratuita como <strong>Netlify</strong>, descrita en esta guía.</p>
<div style="background:#fff3cd;border-left:4px solid #f0c040;padding:10px 14px;border-radius:6px;margin:0 0 18px;font-size:.92rem;color:#5a4510"><strong>Uso recomendado:</strong> esta solución está diseñada para uso personal o compartir con familiares y amigos. Netlify ofrece 100 GB/mes de ancho de banda gratuito — más que suficiente. Para distribución pública, considera usar tu propio hosting web.</div>
</section>

<section>
<h2>Paso a Paso: Publica Tu Audiolibro como Podcast</h2>
<ol>
<li><strong>Genera el audiolibro en formato M4B</strong> — En Audiobook Maker, sube tu archivo EPUB o PDF, elige idioma y voz, luego selecciona <strong>M4B</strong> como formato de salida. La herramienta crea un único archivo M4B con capítulos integrados y portada — el estándar profesional para audiolibros.</li>
<li><strong>Genera también el paquete Podcast RSS</strong> — Después de generar el M4B, ejecuta la generación nuevamente en modo <strong>Podcast RSS</strong> para obtener un ZIP con el archivo XML del feed RSS y los archivos MP3 individuales de los capítulos (los podcasts requieren un archivo de audio por episodio).</li>
<li><strong>Crea una cuenta gratuita de Netlify</strong> — Ve a <strong>app.netlify.com</strong> y regístrate con email o GitHub. No se requiere tarjeta de crédito. El plan gratuito incluye 100 GB de ancho de banda, 10 GB de almacenamiento y HTTPS automático.</li>
<li><strong>Sube a Netlify</strong> — En el panel de Netlify, bajo <strong>Sites</strong>, arrastra toda la carpeta extraída a la zona de colocación punteada. El sitio estará en línea en segundos. Luego renómbralo desde <em>Site configuration → Change site name</em> (ej. <code>mi-audiolibro.netlify.app</code>).</li>
<li><strong>Verifica el feed</strong> — Abre la URL del feed en tu navegador: <br><code>https://tu-nombre-sitio.netlify.app/podcast.xml</code><br>Si ves contenido XML con los títulos de tus capítulos, ¡tu podcast está en línea y listo!</li>
</ol>
</section>

<section>
<h2>Importa Tu Podcast en las Aplicaciones de Escucha</h2>
<table>
<thead><tr><th>App</th><th>Plataforma</th><th>Cómo Añadirlo</th></tr></thead>
<tbody>
<tr><td><strong>Apple Podcasts</strong></td><td>iOS / Mac</td><td><strong>iPhone:</strong> Biblioteca → Más → Añadir programa por URL → pega la URL del feed<br><strong>Mac:</strong> Archivo → Seguir un programa por URL</td></tr>
<tr><td><strong>Pocket Casts</strong></td><td>Android / iOS / Web</td><td>Buscar → pega la URL del feed → Suscribirse</td></tr>
<tr><td><strong>AntennaPod</strong></td><td>Android</td><td>+ → Añadir Podcast por URL → pega la URL</td></tr>
<tr><td><strong>Overcast</strong></td><td>iOS</td><td>+ → Añadir URL → pega la URL del feed</td></tr>
<tr><td><strong>Podcast Addict</strong></td><td>Android</td><td>+ → Feed RSS → pega la URL</td></tr>
</tbody>
</table>
<div style="background:#fff0f0;border-left:4px solid #e04040;padding:8px 14px;border-radius:6px;margin:12px 0;font-size:.9rem;color:#802020"><strong>Nota:</strong> Spotify no permite añadir feeds RSS privados. Usa una de las aplicaciones listadas arriba.</div>
</section>

<section>
<h2>¿Por Qué Escuchar Tu Audiolibro como Podcast?</h2>
<ul>
<li><strong>Marcadores automáticos</strong> — Retoma exactamente donde lo dejaste, incluso entre dispositivos</li>
<li><strong>Orden de episodios</strong> — Los capítulos se reproducen en orden con avance automático al siguiente</li>
<li><strong>Metadatos completos</strong> — Portada, títulos de capítulos e información del libro visibles en tu app de podcast</li>
<li><strong>Velocidad ajustable</strong> — Escucha a 1,5x, 2x o cualquier velocidad que prefieras, con temporizador de apagado</li>
<li><strong>Streaming</strong> — Sin necesidad de descargar todos los archivos; escucha cada capítulo en streaming</li>
<li><strong>Comparte con la familia</strong> — Envía la URL del feed a tus familiares; no necesitan una cuenta de Netlify</li>
</ul>
</section>

<section>
<h2>Consejos para la Publicación de Podcasts</h2>
<ul>
<li><strong>Actualizar episodios:</strong> Vuelve a subir los archivos a Netlify para reemplazar la versión anterior. Tu app de podcast detectará los cambios en la próxima actualización.</li>
<li><strong>Varios libros:</strong> Crea un sitio Netlify separado para cada audiolibro y mantén los feeds organizados.</li>
<li><strong>Límites de almacenamiento:</strong> El plan gratuito de Netlify incluye 10 GB de almacenamiento (~12 audiolibros completos). Elimina los libros terminados para liberar espacio.</li>
<li><strong>Privacidad:</strong> La URL del podcast es técnicamente pública (cualquiera con el enlace puede suscribirse), pero no aparecerá en directorios de podcasts ni motores de búsqueda. Es "privada" en el sentido de que no está indexada.</li>
<li><strong>Dominio personalizado:</strong> Netlify admite dominios personalizados en el plan gratuito si deseas una URL personalizada.</li>
</ul>
</section>

<section>
<h2>Preguntas Frecuentes</h2>
<details><summary>¿Es Netlify realmente gratis para alojar mi podcast?</summary>
<p>Sí. El plan Starter gratuito de Netlify incluye 100 GB/mes de ancho de banda y 10 GB de almacenamiento. Para un podcast de audiolibro típico (10-20 episodios, ~5 MB cada uno), es más que suficiente para uso personal. Si superas los límites, puedes pasar a Netlify Pro ($19/mes) o usar tu propio hosting.</p>
</details>
<details><summary>¿Por qué usar formato M4B en lugar de MP3 para el audiolibro?</summary>
<p>M4B es el estándar profesional para audiolibros. Un solo archivo M4B contiene todos los capítulos como marcadores de navegación, portada integrada y metadatos. Es compatible con Apple Books, Audible y todas las principales aplicaciones de audiolibros. MP3 es excelente para máxima compatibilidad, pero M4B ofrece una experiencia de escucha mucho mejor con navegación por capítulos.</p>
</details>
<details><summary>¿Puedo enviar mi podcast a los directorios de Apple Podcasts o Spotify?</summary>
<p>No con un feed privado de Netlify. Apple Podcasts Connect y Spotify for Podcasters requieren feeds alojados en plataformas aprobadas con requisitos específicos (tamaño de portada, categorías, etc.). El enfoque de Netlify es para <strong>podcasts privados personales</strong> — ideal para escuchar tus propios libros o compartir con amigos cercanos y familiares.</p>
</details>
<details><summary>¿Qué puedo usar si no quiero Netlify?</summary>
<p>Cualquier hosting web estático funciona: GitHub Pages, Cloudflare Pages, Vercel o tu propio servidor web. Simplemente sube la carpeta del podcast extraída a cualquier ubicación accesible vía web y la URL del feed RSS funcionará en las aplicaciones de podcast. Netlify se recomienda porque es gratuito, rápido y no requiere configuración.</p>
</details>
<details><summary>¿Pueden las aplicaciones de podcast descargar episodios para escuchar sin conexión?</summary>
<p>Sí. Una vez suscrito al feed en una aplicación de podcast, puedes descargar episodios individuales para escuchar sin conexión, como cualquier otro podcast. La aplicación gestiona automáticamente la descarga, la posición de reproducción y la eliminación.</p>
</details>
</section>
""",
}


_GUIDE_BODY_DE = {
    "free-ebooks": """
<section>
<h2>Wo Sie kostenlose E-Books zum Herunterladen finden</h2>
<p>Tausende großartiger Bücher sind völlig kostenlos und legal herunterladbar — gemeinfreie Klassiker, moderne Titel unter offenen Lizenzen und Community-Projekte. Sobald Sie ein kostenloses EPUB haben, können Sie es mit <a href="/">Audiobook Maker</a> in wenigen Minuten in ein Hörbuch verwandeln. Diese Anleitung listet die besten Quellen für kostenlose E-Books auf und zeigt Ihnen, wie Sie sie anhören.</p>
</section>

<section>
<h2>Die 8 besten Seiten für kostenlose E-Books</h2>
<ul>
<li><a href="https://www.gutenberg.org" target="_blank" rel="noopener">Project Gutenberg</a> — Über 70.000 kostenlose gemeinfreie Bücher. Die größte und älteste Sammlung der Welt, mit zuverlässigen EPUB-Downloads.</li>
<li><a href="https://standardebooks.org" target="_blank" rel="noopener">Standard Ebooks</a> — Sorgfältig kuratierte, wunderschön formatierte Ausgaben von Klassikern, mit moderner Typografie und originellen Covern.</li>
<li><a href="https://archive.org/details/texts" target="_blank" rel="noopener">Internet Archive</a> — Eine riesige digitale Bibliothek mit Millionen von Texten, Hörbüchern und historischen Zeitschriften.</li>
<li><a href="https://manybooks.net" target="_blank" rel="noopener">ManyBooks</a> — Über 50.000 kostenlose E-Books mit moderner Oberfläche und personalisierten Leseempfehlungen.</li>
<li><a href="https://www.feedbooks.com/publicdomain" target="_blank" rel="noopener">Feedbooks</a> — Ein eleganter Katalog gemeinfreier E-Books mit direktem, unkompliziertem Download.</li>
<li><a href="https://books.google.com/books?&as_ebook=on&as_brr=1" target="_blank" rel="noopener">Google Books</a> — Millionen digitalisierter Bücher; filtern Sie nach „Kostenlose E-Books", um kostenlose Titel zu finden.</li>
<li><a href="https://www.liberliber.it/online/opere/libri/" target="_blank" rel="noopener">Liber Liber</a> — Die Referenz für Klassiker der italienischen Literatur: Dante, Manzoni, Pirandello und viele mehr.</li>
<li><a href="https://openlibrary.org/read" target="_blank" rel="noopener">Open Library</a> — Kostenlose digitale Ausleihe moderner und klassischer E-Books, betrieben vom Internet Archive.</li>
</ul>
</section>

<section>
<h2>Gemeinfrei vs. urheberrechtlich geschützte Bücher</h2>
<p><strong>Gemeinfreie</strong> Bücher — in der Regel Werke, deren Autor vor mehr als 70 Jahren verstorben ist — dürfen ohne Einschränkung heruntergeladen, geteilt und konvertiert werden. Project Gutenberg, Standard Ebooks und Liber Liber sind darauf spezialisiert.</p>
<p><strong>Urheberrechtlich geschützte</strong> Bücher sind auch dann geschützt, wenn sie kostenlos angeboten werden. Viele Autoren und Verlage veröffentlichen moderne Titel unter <a href="https://creativecommons.org" target="_blank" rel="noopener">Creative-Commons</a>-Lizenzen oder als kostenlose Aktionen — diese sind völlig legal herunterladbar. Meiden Sie Piraten-Seiten, die kommerzielle E-Books ohne Erlaubnis teilen: Sie sind illegal und enthalten oft Schadsoftware.</p>
</section>

<section>
<h2>So verwandeln Sie ein kostenloses E-Book in ein Hörbuch</h2>
<ol>
<li><strong>Laden Sie das EPUB herunter</strong> von einer der oben genannten Seiten (EPUB ist dem PDF für eine saubere Kapitelerkennung vorzuziehen).</li>
<li><strong>Öffnen Sie <a href="/">Audiobook Maker</a></strong> und laden Sie die Datei hoch — Kapitel, Titel, Autor und Cover werden automatisch extrahiert.</li>
<li><strong>Wählen Sie eine neuronale KI-Stimme</strong> aus über 400 Optionen in mehr als 50 Sprachen und hören Sie eine kostenlose Vorschau.</li>
<li><strong>Wählen Sie Ihr Format</strong> — MP3 für maximale Kompatibilität oder <a href="/guide/m4b-format/">M4B</a> mit eingebetteten Kapiteln und Cover.</li>
<li><strong>Generieren und herunterladen</strong> — hören Sie auf Ihrem Smartphone, Tablet oder jedem Hörbuch-Player.</li>
</ol>
<p>Siehe die vollständige Anleitung <a href="/guide/epub-to-audiobook/">EPUB in Hörbuch →</a> für Details.</p>
</section>

<section>
<h2>Tipps zur Auswahl des richtigen kostenlosen E-Books</h2>
<ul>
<li><strong>EPUB statt PDF bevorzugen</strong>: EPUB hat eine saubere Kapitelstruktur, während PDFs Kopfzeilen, Seitenzahlen und Layout-Artefakte enthalten können, die bereinigt werden müssen.</li>
<li><strong>Ausgabe prüfen</strong>: Standard Ebooks und Liber Liber bieten die am besten formatierten Versionen der Klassiker — weniger Tippfehler und OCR-Fehler.</li>
<li><strong>KI-Textoptimierung nutzen</strong>: Bei PDFs oder groben Scans entfernt die optionale KI-Bereinigung von Audiobook Maker Fußnoten, Silbentrennung und Artefakte vor der Narration.</li>
<li><strong>Auf die Sprache achten</strong>: Wählen Sie eine Stimme, die zur Sprache des Buches passt, für eine natürliche Aussprache.</li>
</ul>
</section>

<section>
<h2>Häufig gestellte Fragen</h2>
<details><summary>Ist es legal, kostenlose E-Books herunterzuladen?</summary>
<p>Ja, wenn das Buch gemeinfrei ist oder vom Autor oder Verlag kostenlos angeboten wird. Alle in dieser Anleitung aufgeführten Seiten verbreiten Bücher legal. Meiden Sie Piraten-Seiten, die urheberrechtlich geschützte kommerzielle Titel ohne Erlaubnis teilen.</p>
</details>
<details><summary>Welches Format sollte ich für die Hörbuch-Erstellung herunterladen?</summary>
<p>EPUB ist am besten: Es hat eine saubere Kapitelstruktur, die zuverlässig konvertiert. PDF funktioniert ebenfalls, kann aber KI-Textoptimierung benötigen, um Layout-Artefakte zu entfernen. TXT eignet sich für reinen Text ohne Kapitel.</p>
</details>
<details><summary>Kann ich diese kostenlosen E-Books kostenlos in Hörbücher umwandeln?</summary>
<p>Ja. Audiobook Maker konvertiert EPUB, PDF und TXT kostenlos mit neuronalen TTS-Stimmen in MP3- oder M4B-Hörbücher, ohne Anmeldung und ohne Nutzungsbeschränkungen.</p>
</details>
<details><summary>Wo finde ich kostenlose E-Books in anderen Sprachen als Englisch?</summary>
<p>Project Gutenberg und Internet Archive beherbergen Bücher in Dutzenden von Sprachen. Liber Liber ist auf Italienisch spezialisiert, und Google Books erlaubt das Filtern kostenloser Titel nach Sprache. Audiobook Maker erzählt sie dann in über 50 Sprachen.</p>
</details>
</section>
""",

    "epub-to-audiobook": """
<section>
<h2>Warum EPUB in Hörbuch umwandeln?</h2>
<p>EPUB ist das beliebteste E-Book-Format, verwendet von Apple Books, Google Play Books, Kobo und den meisten digitalen Bibliotheken. Die Umwandlung von EPUB in Hörbuch ermöglicht es Ihnen, <strong>Ihre E-Books zu hören</strong> — beim Pendeln, beim Sport oder bei der Hausarbeit. Moderne KI-Text-to-Speech-Stimmen klingen bemerkenswert natürlich, weit entfernt von roboterhaften Bildschirmleseprogrammen.</p>
<p>Mit <a href="/">Audiobook Maker</a> können Sie jedes DRM-freie EPUB kostenlos in MP3 oder M4B Hörbuch umwandeln, direkt in Ihrem Browser. Keine Software-Installation, kein Konto erforderlich.</p>
</section>

<section>
<h2>EPUB in Hörbuch umwandeln — Schritt für Schritt</h2>
<ol>
<li><strong>Laden Sie Ihre EPUB-Datei hoch</strong> — Per Drag & Drop oder Klick zum Auswählen. Das Tool extrahiert automatisch Kapitel und Metadaten (Titel, Autor, Cover).</li>
<li><strong>Wählen Sie Ihre TTS-Stimme</strong> — Aus über 400 neuronalen KI-Stimmen in über 50 Sprachen. Hören Sie eine kurze Vorschau, bevor Sie die vollständige Konvertierung starten.</li>
<li><strong>Wählen Sie Kapitel aus</strong> — Entscheiden Sie, welche Kapitel enthalten sein sollen. Überspringen Sie das Inhaltsverzeichnis, Copyright-Seiten oder Abschnitte, die nicht vorgelesen werden sollen.</li>
<li><strong>Wählen Sie das Ausgabeformat</strong> — <strong>MP3</strong> (Einzeldatei oder ZIP pro Kapitel), <strong>M4B</strong> (Einzeldatei mit eingebetteten Kapiteln und Cover — ideal für Apple Books und Hörbuch-Player) oder <strong>Podcast RSS</strong> (privater Podcast-Feed).</li>
<li><strong>Klicken Sie auf "Generieren"</strong> — Die TTS-Engine erzählt jedes Kapitel. Sie sehen einen Fortschrittsbalken und erhalten eine optionale E-Mail-Benachrichtigung, wenn der Vorgang abgeschlossen ist.</li>
<li><strong>Herunterladen und anhören</strong> — Laden Sie Ihr Hörbuch herunter und hören Sie es auf jedem Gerät.</li>
</ol>
</section>

<section>
<h2>Beste Stimmen für EPUB-zu-Hörbuch-Konvertierung</h2>
<p>Audiobook Maker verwendet <strong>Microsoft Edge neural TTS</strong> (die gleiche Engine wie Azure Cognitive Services). Dies sind die natürlich klingenden kostenlosen Stimmen:</p>
<ul>
<li><strong>Englisch (US)</strong>: Aria, Jenny, Guy, Davis, Jane — warme, ausdrucksstarke Erzählung</li>
<li><strong>Englisch (UK)</strong>: Sonia, Ryan, Libby — ausgezeichnet für britische Literatur</li>
<li><strong>Italienisch</strong>: Isabella, Diego, Elsa — natürliche italienische Erzählung</li>
<li><strong>Französisch</strong>: Denise, Henri — klare französische Aussprache</li>
<li><strong>Deutsch</strong>: Katja, Conrad — klare deutsche Aussprache</li>
<li><strong>Spanisch</strong>: Elvira, Alvaro — fließende spanische Erzählung</li>
<li><strong>Chinesisch</strong>: Xiaoxiao, Yunyang — natürliches Mandarin</li>
</ul>
<p>Google Cloud TTS Chirp3-HD ist ebenfalls für noch höhere Qualität verfügbar (erste 1 Million Zeichen pro Monat kostenlos).</p>
</section>

<section>
<h2>EPUB zu MP3 vs EPUB zu M4B: Welches Format sollten Sie wählen?</h2>
<p><strong>MP3</strong> ist universell kompatibel — jedes Telefon, Tablet und jeder Computer spielt MP3-Dateien ab. Wählen Sie MP3, wenn Sie maximale Kompatibilität wünschen oder auf mehreren Geräten hören möchten.</p>
<p><strong>M4B</strong> ist das professionelle Hörbuchformat. Es ist eine einzelne Datei, die alle Kapitel als Navigationsmarker enthält, plus eingebettetes Cover und Metadaten (Autor, Titel, Genre). M4B-Dateien werden von Apple Books, Audible und den meisten Hörbuch-Apps unterstützt. <a href="/guide/m4b-format/">Erfahren Sie mehr über das M4B-Format →</a></p>
</section>

<section>
<h2>Tipps für die beste EPUB-zu-Hörbuch-Erfahrung</h2>
<ul>
<li><strong>Entfernen Sie zuerst DRM</strong>: Kommerzielle E-Books von Kindle, Apple Books oder Kobo haben oft DRM-Schutz. Dieser muss vor der Konvertierung entfernt werden (nur für den persönlichen Gebrauch, wo gesetzlich erlaubt).</li>
<li><strong>Text bereinigen</strong>: Einige EPUBs enthalten Formatierungsartefakte (Seitenzahlen, Kopfzeilen, Fußnoten). Die optionale KI-Textoptimierung von Audiobook Maker kann diese automatisch bereinigen.</li>
<li><strong>Vorschau vor der vollständigen Generierung</strong>: Erstellen Sie immer zuerst die kostenlose Vorschau, um Stimmqualität und Tempo zu prüfen.</li>
<li><strong>Kapitelauswahl nutzen</strong>: Überspringen Sie Frontmatter (Inhaltsverzeichnis, Vorwort) und Backmatter (Index, Werbung) für ein saubereres Hörerlebnis.</li>
<li><strong>Wählen Sie M4B für lange Bücher</strong>: Das M4B-Format hält alles in einer Datei mit Kapitelnavigation organisiert — viel besser als mehrere MP3-Dateien zu verwalten.</li>
</ul>
</section>

<section>
<h2>Häufig gestellte Fragen</h2>
<details><summary>Ist die Umwandlung von EPUB in Hörbuch wirklich kostenlos?</summary>
<p>Ja. Audiobook Maker ist Open-Source-Software (AGPL-3.0). Die TTS-Konvertierung verwendet Microsoft Edge TTS, das kostenlos und ohne Nutzungsbeschränkungen ist. Die optionale KI-Textoptimierung (DeepSeek LLM) verursacht geringe Kosten oberhalb einer kostenlosen Schwelle.</p>
</details>
<details><summary>Kann ich Kindle-Bücher in Hörbücher umwandeln?</summary>
<p>Kindle-Bücher verwenden Amazons proprietäres AZW/KFX-Format mit DRM. Sie müssen zuerst den DRM entfernen und mit einem Tool wie Calibre in EPUB konvertieren, dann das EPUB bei Audiobook Maker hochladen.</p>
</details>
<details><summary>Wie lange dauert die EPUB-zu-Hörbuch-Konvertierung?</summary>
<p>Etwa 2-3 Minuten pro Kapitel (variiert je nach Kapitellänge und Serverauslastung). Ein typisches 300-seitiges Buch (~20 Kapitel) dauert etwa 40-60 Minuten. Sie erhalten eine E-Mail-Benachrichtigung, wenn es fertig ist.</p>
</details>
<details><summary>Welche Sprachen werden unterstützt?</summary>
<p>Über 50 Sprachen, darunter Englisch, Italienisch, Französisch, Spanisch, Deutsch, Chinesisch, Japanisch, Koreanisch, Portugiesisch, Russisch, Arabisch, Hindi und viele mehr. Jede Sprache bietet mehrere Stimmoptionen.</p>
</details>
<details><summary>Funktioniert Audiobook Maker auf dem Handy?</summary>
<p>Ja. Die Web-App funktioniert in jedem modernen Browser auf Desktop, Tablet oder Telefon. Für große EPUB-Dateien wird jedoch ein Desktop-Browser für schnelleren Upload und Verarbeitung empfohlen.</p>
</details>
</section>
""",

    "m4b-format": """
<section>
<h2>Was ist das M4B-Format?</h2>
<p><strong>M4B</strong> (MPEG-4 Audiobook) ist das Standard-Dateiformat für Hörbücher. Basierend auf dem MPEG-4-Container (gleiche Familie wie MP4-Video) ist M4B im Wesentlichen eine AAC-Audiodatei mit speziellen Funktionen für Hörbücher:</p>
<ul>
<li><strong>Kapitelmarker</strong>: Eingebettete Navigationspunkte zum Springen zwischen Kapiteln</li>
<li><strong>Cover-Art</strong>: Das Buchcover ist in den Datei-Metadaten eingebettet</li>
<li><strong>Lesezeichen</strong>: Hörbuch-Player merken sich Ihre Hörposition (auch geräteübergreifend mit iCloud)</li>
<li><strong>Metadaten</strong>: Titel, Autor, Sprecher, Genre und Veröffentlichungsdatum sind in der Datei gespeichert</li>
<li><strong>Variable Geschwindigkeit</strong>: Player können die Wiedergabe beschleunigen oder verlangsamen, ohne die Tonhöhe zu ändern</li>
</ul>
<p>M4B ist das Format von <strong>Apple Books</strong>, <strong>Audible</strong> (Aax ist eine DRM-geschützte M4B-Variante) und den meisten Hörbuch-Apps auf iOS und Android.</p>
</section>

<section>
<h2>M4B vs MP3 für Hörbücher: Vollständiger Vergleich</h2>
<table>
<thead><tr><th>Funktion</th><th>M4B</th><th>MP3</th></tr></thead>
<tbody>
<tr><td>Kapitelnavigation</td><td>Integrierte Kapitelmarker</td><td>Keine integrierten Kapitel</td></tr>
<tr><td>Cover-Art</td><td>In Datei eingebettet</td><td>Kann eingebettet werden (ID3), aber nicht universell unterstützt</td></tr>
<tr><td>Positionsspeicherung</td><td>Ja (alle M4B-Player)</td><td>Abhängig vom Player</td></tr>
<tr><td>Dateigröße (gleiche Qualität)</td><td>~30-40% kleiner (AAC-Codec)</td><td>Größer bei gleicher Qualität</td></tr>
<tr><td>Kompatibilität</td><td>Apple Books, Audible, BookPlayer, Listen, die meisten Hörbuch-Apps</td><td>Universell — jedes Gerät</td></tr>
<tr><td>Einzeldatei</td><td>Ja — ganzes Buch in einer Datei</td><td>Normalerweise eine Datei pro Kapitel oder eine kombinierte Datei</td></tr>
<tr><td>Lesezeichen-Sync</td><td>Ja (Apple-Ökosystem)</td><td>Nein</td></tr>
<tr><td>Am besten für</td><td>iOS/Mac-Nutzer, Hörbuch-Sammler, lange Bücher</td><td>Maximale Kompatibilität, Teilen, einfache Player</td></tr>
</tbody>
</table>
<p><strong>Fazit:</strong> Wählen Sie M4B, wenn Sie Apple Books oder eine spezielle Hörbuch-App verwenden. Wählen Sie MP3, wenn Sie die Datei auf einem einfachen MP3-Player oder Autoradio abspielen müssen, das M4B nicht unterstützt.</p>
</section>

<section>
<h2>M4B-Dateien mit Kapiteln erstellen — Kostenlos</h2>
<p>Das Erstellen von M4B-Dateien erforderte früher komplexe ffmpeg-Befehle oder kostenpflichtige Software. <a href="/">Audiobook Maker</a> automatisiert den gesamten Prozess:</p>
<ol>
<li><strong>Laden Sie Ihr E-Book hoch</strong> (EPUB, PDF oder TXT) — Kapitel werden automatisch extrahiert</li>
<li><strong>Wählen Sie M4B als Ausgabeformat</strong> — das Tool erledigt alles: TTS-Erzählung, AAC-Kodierung, Kapitelmarker, Cover-Einbettung</li>
<li><strong>Laden Sie die M4B-Datei herunter</strong> — bereit zum Import in Apple Books oder jeden M4B-kompatiblen Player</li>
</ol>
<p>Die generierte M4B verwendet <strong>AAC-Audio mit 64 kbps</strong> (optimiert für Sprache), enthält <strong>1400×1400 Cover-Art</strong> und hat ordnungsgemäße iTunes-kompatible Metadaten-Tags. Jedes Kapitel erscheint als Navigationspunkt in Ihrem Hörbuch-Player.</p>
</section>

<section>
<h2>M4B-Dateien abspielen</h2>
<p><strong>iOS / Mac:</strong> Apple Books (integriert) — Ziehen Sie die M4B in Books oder synchronisieren Sie via Finder/iCloud.</p>
<p><strong>Android:</strong> Listen Audiobook Player, Smart Audiobook Player, Sirin — alle unterstützen M4B mit Kapiteln.</p>
<p><strong>Windows:</strong> Apple Books (via iTunes), VLC Media Player, BookPlayer (Microsoft Store).</p>
<p><strong>Linux:</strong> VLC, Cozy (GTK Hörbuch-Player).</p>
<p><strong>Auto / Einfacher MP3-Player:</strong> Konvertieren Sie in MP3 — die meisten Autoradios lesen keine M4B-Dateien.</p>
</section>

<section>
<h2>Häufig gestellte Fragen</h2>
<details><summary>Kann ich M4B in MP3 konvertieren?</summary>
<p>Ja. Verwenden Sie Audiobook Maker für MP3-Ausgabe oder ffmpeg für eine bestehende M4B: <code>ffmpeg -i buch.m4b -acodec libmp3lame -b:a 128k buch.mp3</code>. Beachten Sie, dass Kapitelmarker bei der Konvertierung verloren gehen.</p>
</details>
<details><summary>Kann ich eine M4B in Kapitel aufteilen?</summary>
<p>Ja. Tools wie <code>m4b-tool</code> oder ffmpeg können M4B-Dateien an Kapitelmarkern aufteilen. Audiobook Maker kann auch einzelne MP3-Dateien pro Kapitel ausgeben, wenn Sie separate Dateien bevorzugen.</p>
</details>
<details><summary>Welche Hörbuch-Apps unterstützen M4B?</summary>
<p>Apple Books (iOS/Mac), BookPlayer (iOS), Listen Audiobook Player (Android), Smart Audiobook Player (Android), Bound (iOS), Sirin (Android), VLC (alle Plattformen) und Plex mit dem Audnexus-Plugin.</p>
</details>
<details><summary>Welche Bitrate sollte ich für M4B-Hörbücher verwenden?</summary>
<p>Audiobook Maker verwendet 64 kbps AAC, den Standard für Sprachinhalte. Sprache benötigt keine hohen Bitraten — 64 kbps AAC klingt identisch mit 128 kbps MP3 für Erzählungen, benötigt aber nur die halbe Dateigröße.</p>
</details>
</section>
""",

    "text-to-speech-audiobook": """
<section>
<h2>Was ist KI-Text-to-Speech Hörbucherstellung?</h2>
<p>Die KI-Text-to-Speech (TTS) Hörbucherstellung verwendet neuronale KI-Stimmen, um geschriebenen Text in gesprochenes Audio umzuwandeln. Anders als ältere roboterhafte TTS klingen moderne neuronale Stimmen bemerkenswert natürlich — mit angemessener Intonation, Rhythmus und Emotion. Sie können jetzt <strong>jeden Text, jedes E-Book oder Dokument in ein professionell klingendes Hörbuch verwandeln</strong>, ohne einen menschlichen Sprecher zu engagieren.</p>
<p><a href="/">Audiobook Maker</a> kombiniert die besten kostenlosen TTS-Engines mit einer benutzerfreundlichen Weboberfläche. Laden Sie EPUB-, PDF- oder TXT-Dateien hoch und erhalten Sie MP3-, M4B- oder Podcast-RSS-Ausgabe — völlig kostenlos.</p>
</section>

<section>
<h2>Beste kostenlose TTS-Engines für Hörbücher (2026)</h2>
<table>
<thead><tr><th>TTS-Engine</th><th>Stimmen</th><th>Sprachen</th><th>Kosten</th><th>Ideal für</th></tr></thead>
<tbody>
<tr><td><strong>Microsoft Edge TTS</strong></td><td>400+</td><td>50+</td><td>Kostenlos</td><td>Allgemeine Hörbucherstellung, beste kostenlose Stimmen</td></tr>
<tr><td><strong>Google Cloud TTS (Chirp3-HD)</strong></td><td>50+</td><td>30+</td><td>1 Mio. Zeichen kostenlos/Monat, dann kostenpflichtig</td><td>Premium-Qualität, ausdrucksstarke Erzählung</td></tr>
<tr><td><strong>Speechify</strong></td><td>30+</td><td>20+</td><td>Freemium (begrenzt)</td><td>Schnelles Artikellesen, mobile Nutzung</td></tr>
<tr><td><strong>NaturalReader</strong></td><td>100+</td><td>20+</td><td>Freemium (begrenzt)</td><td>Legasthenie-Unterstützung, Bildung</td></tr>
<tr><td><strong>ElevenLabs</strong></td><td>Benutzerdefiniert</td><td>30+</td><td>10K Zeichen kostenlos/Monat</td><td>Ultra-realistisches Stimmklonen</td></tr>
<tr><td><strong>Play.ht</strong></td><td>800+</td><td>140+</td><td>5K Zeichen kostenlos/Monat</td><td>Mehrsprachig, Stimmenvielfalt</td></tr>
</tbody>
</table>
<p><strong>Audiobook Maker verwendet standardmäßig Microsoft Edge TTS</strong> — völlig kostenlos, keine Nutzungsbeschränkungen, über 400 Stimmen. Google TTS Chirp3-HD ist für Premium-Qualität verfügbar. Anders als Speechify oder NaturalReader hat Audiobook Maker <strong>keine Paywall, keine Anmeldepflicht und keine Nutzungsbeschränkungen</strong>.</p>
</section>

<section>
<h2>Speechify-Alternative: Warum Audiobook Maker wählen?</h2>
<p>Speechify ist eine beliebte TTS-App, aber die kostenlose Version ist stark eingeschränkt. So vergleicht sich Audiobook Maker:</p>
<ul>
<li><strong>100% kostenlos</strong> vs. Speechify-Abonnement für 139$/Jahr</li>
<li><strong>Keine Nutzungsbeschränkungen</strong> — ganze Bücher konvertieren, nicht nur kurze Texte</li>
<li><strong>M4B-Ausgabe mit Kapiteln</strong> — Speechify exportiert nur einfaches Audio</li>
<li><strong>Podcast-RSS-Feed</strong> — in jeder Podcast-App anhören</li>
<li><strong>Open Source</strong> — AGPL-3.0-Lizenz, Code einsehbar und veränderbar</li>
<li><strong>Self-Hosting-Option</strong> — auf eigenem Server für vollständige Privatsphäre</li>
<li><strong>KI-Textoptimierung</strong> — bereinigt und verbessert Text automatisch für bessere Erzählung</li>
</ul>
<p>Wenn Sie eine <strong>kostenlose Speechify-Alternative</strong> für vollständige Bücher benötigen, ist Audiobook Maker die beste verfügbare Option.</p>
</section>

<section>
<h2>Hörbuch mit KI-Stimmen erstellen — Schritt für Schritt</h2>
<ol>
<li><strong>Datei hochladen</strong> — EPUB, PDF oder Text (TXT). Das Tool erkennt automatisch Kapitel und extrahiert Metadaten.</li>
<li><strong>Stimme wählen</strong> — Durchsuchen Sie über 400 neuronale Stimmen. Jede Stimme hat eine Vorschau zum Anhören vor der Konvertierung.</li>
<li><strong>Ausgabeformat wählen</strong> — MP3 für universelle Kompatibilität, M4B für Apple Books mit Kapiteln oder Podcast RSS für Streaming.</li>
<li><strong>Generieren</strong> — Die KI erzählt Ihr Buch Kapitel für Kapitel. Der Fortschritt wird in Echtzeit angezeigt.</li>
<li><strong>Herunterladen und anhören</strong> — Erhalten Sie Ihr Hörbuch als Einzeldatei, Kapitel-ZIP oder abonnieren Sie den privaten Podcast-Feed.</li>
</ol>
</section>

<section>
<h2>Kostenloses TTS-Hörbuch vs. Menschlicher Sprecher</h2>
<table>
<thead><tr><th>Aspekt</th><th>KI TTS (Audiobook Maker)</th><th>Menschlicher Sprecher</th></tr></thead>
<tbody>
<tr><td>Kosten</td><td>Kostenlos</td><td>500-5.000€+ pro Buch</td></tr>
<tr><td>Zeit</td><td>~1 Stunde</td><td>2-6 Wochen</td></tr>
<tr><td>Qualität</td><td>Sehr gut (neuronal, natürlich)</td><td>Hervorragend (menschliche Ausdruckskraft)</td></tr>
<tr><td>Sprachen</td><td>50+ sofort</td><td>Eine Sprache pro Sprecher</td></tr>
<tr><td>Überarbeitungen</td><td>Sofortige Neugenerierung</td><td>Neue Aufnahme erforderlich</td></tr>
<tr><td>Ideal für</td><td>Persönliche Nutzung, Entwürfe, unabhängige Autoren</td><td>Kommerzielle Hörbücher für den Verkauf (Audible, etc.)</td></tr>
</tbody>
</table>
<p>Für persönliches Hören, Überprüfung eigener Texte oder Erstellung von Audioversionen gemeinfreier Bücher ist KI-TTS die beste Wahl. Für kommerzielle Hörbücher, die auf Audible verkauft werden sollen, ist ein menschlicher Sprecher weiterhin vorzuziehen (und von ACX gefordert).</p>
</section>

<section>
<h2>Häufig gestellte Fragen</h2>
<details><summary>Ist KI-Text-to-Speech gut genug für Hörbücher?</summary>
<p>Ja. Moderne neuronale TTS (wie Microsoft Edge TTS und Google Chirp3-HD) sind bemerkenswert natürlich. Die meisten Hörer können bei Sachbüchern keinen Unterschied zu einem menschlichen Sprecher feststellen. Für Belletristik mit mehreren Charakteren und emotionaler Bandbreite ist menschliche Erzählung noch überlegen — aber der Abstand schließt sich schnell.</p>
</details>
<details><summary>Kann ich KI-generierte Hörbücher kommerziell nutzen?</summary>
<p>Ja, mit einigen Einschränkungen. Microsoft Edge TTS und Google TTS erlauben die kommerzielle Nutzung des generierten Audios. Plattformen wie Audible (ACX) verlangen jedoch derzeit menschliche Erzählung für neue Einreichungen. KI-Hörbücher können auf anderen Plattformen verkauft oder für persönliche Projekte, YouTube-Videos und Bildungsinhalte verwendet werden.</p>
</details>
<details><summary>Wie viele Zeichen kann ich kostenlos konvertieren?</summary>
<p>Mit Microsoft Edge TTS: unbegrenzt. Es gibt keine Nutzungsbeschränkungen oder Kontingente. Mit Google Cloud TTS Chirp3-HD: 1 Million Zeichen pro Monat kostenlos, danach gelten die Standardpreise von Google Cloud.</p>
</details>
<details><summary>Funktioniert Audiobook Maker offline?</summary>
<p>Die gehostete Version auf audiobook-maker.com benötigt eine Internetverbindung. Die Software ist jedoch Open Source — Sie können sie auf Ihrem Computer oder Server installieren und lokal mit voller Offline-Fähigkeit ausführen.</p>
</details>
<details><summary>Was ist die beste TTS-Stimme für deutsche Hörbücher?</summary>
<p>Die besten Edge-TTS-Stimmen für Deutsch sind <strong>Katja</strong> (warm, weiblich) und <strong>Conrad</strong> (klar, männlich). Für Premium-Qualität bietet Google Chirp3-HD die ausdrucksstärksten neuronalen Stimmen. <a href="/">Testen Sie die kostenlose Vorschau auf Audiobook Maker</a>, um Ihre bevorzugte Stimme zu finden.</p>
</details>
</section>
""",

    "gemini-tts": """
<p>Gemini TTS ist die neuronale Engine hinter den PREMIUM-Stimmen von Audiobook Maker. Dieser Leitfaden zeigt die verfügbaren Stimmen, die unterstützten Sprachen und wie Sie die Sprechweise mit Prompts steuern.</p>

<h2 id="voices">Stimmoptionen</h2>
<p>30 unterschiedliche Stimmen, jede mit eigenem Charakter. Der Stimmname ist fest; der Deskriptor fasst den natürlichen Ton zusammen.</p>
<table>
  <thead><tr><th>Stimme</th><th>Charakter</th></tr></thead>
  <tbody>
    <tr><td>Zephyr</td><td>Hell</td></tr>
    <tr><td>Puck</td><td>Optimistisch</td></tr>
    <tr><td>Charon</td><td>Informativ</td></tr>
    <tr><td>Kore</td><td>Bestimmt</td></tr>
    <tr><td>Fenrir</td><td>Erregbar</td></tr>
    <tr><td>Leda</td><td>Jugendlich</td></tr>
    <tr><td>Orus</td><td>Bestimmt</td></tr>
    <tr><td>Aoede</td><td>Locker</td></tr>
    <tr><td>Callirrhoe</td><td>Entspannt</td></tr>
    <tr><td>Autonoe</td><td>Hell</td></tr>
    <tr><td>Enceladus</td><td>Hauchig</td></tr>
    <tr><td>Iapetus</td><td>Klar</td></tr>
    <tr><td>Umbriel</td><td>Entspannt</td></tr>
    <tr><td>Algieba</td><td>Geschmeidig</td></tr>
    <tr><td>Despina</td><td>Geschmeidig</td></tr>
    <tr><td>Erinome</td><td>Klar</td></tr>
    <tr><td>Algenib</td><td>Rau</td></tr>
    <tr><td>Rasalgethi</td><td>Informativ</td></tr>
    <tr><td>Laomedeia</td><td>Optimistisch</td></tr>
    <tr><td>Achernar</td><td>Sanft</td></tr>
    <tr><td>Alnilam</td><td>Bestimmt</td></tr>
    <tr><td>Schedar</td><td>Gleichmäßig</td></tr>
    <tr><td>Gacrux</td><td>Reif</td></tr>
    <tr><td>Pulcherrima</td><td>Direkt</td></tr>
    <tr><td>Achird</td><td>Freundlich</td></tr>
    <tr><td>Zubenelgenubi</td><td>Lässig</td></tr>
    <tr><td>Vindemiatrix</td><td>Zart</td></tr>
    <tr><td>Sadachbia</td><td>Lebhaft</td></tr>
    <tr><td>Sadaltager</td><td>Sachkundig</td></tr>
    <tr><td>Sulafat</td><td>Warm</td></tr>
  </tbody>
</table>

<h2 id="languages">Unterstützte Sprachen</h2>
<p>Gemini TTS unterstützt die folgenden Sprachen (BCP-47-Code in Klammern):</p>
<p>Arabic (ar), Filipino (fil), Bangla (bn), Finnish (fi), Dutch (nl), Galician (gl), English (en), Georgian (ka), French (fr), Greek (el), German (de), Gujarati (gu), Hindi (hi), Haitian Creole (ht), Indonesian (id), Hebrew (he), Italian (it), Hungarian (hu), Japanese (ja), Icelandic (is), Korean (ko), Javanese (jv), Marathi (mr), Kannada (kn), Polish (pl), Konkani (kok), Portuguese (pt), Romanian (ro), Russian (ru), Spanish (es), Tamil (ta), Telugu (te), Thai (th), Turkish (tr), Ukrainian (uk), Vietnamese (vi), Afrikaans (af), Albanian (sq), Amharic (am), Armenian (hy), Azerbaijani (az), Basque (eu), Belarusian (be), Bulgarian (bg), Burmese (my), Catalan (ca), Cebuano (ceb), Chinese Mandarin (cmn), Croatian (hr), Czech (cs), Danish (da), Estonian (et), Latvian (lv), Lithuanian (lt), Luxembourgish (lb), Macedonian (mk), Maithili (mai), Malagasy (mg), Malay (ms), Malayalam (ml), Mongolian (mn), Nepali (ne), Norwegian Bokm&aring;l (nb), Norwegian Nynorsk (nn), Odia (or), Pashto (ps), Persian (fa), Punjabi (pa), Serbian (sr), Sindhi (sd), Sinhala (si), Slovak (sk), Slovenian (sl), Swahili (sw), Swedish (sv), Urdu (ur).</p>

<h2 id="prompting">Prompting-Leitfaden</h2>
<p>Das Modell leitet die Sprechweise automatisch aus dem Text ab. Mit Inline-Tags und strukturierten Anweisungen können Sie sie weiter steuern.</p>
<h3>Inline-Audio-Tags</h3>
<p>Inline-Modifikatoren wie <code>[whispers]</code>, <code>[laughs]</code>, <code>[excitedly]</code>, <code>[bored]</code> und <code>[shouting]</code> verändern Ton, Tempo und emotionale Qualität. Seien Sie kreativ und experimentieren Sie mit verschiedenen Darbietungen.</p>
<h3>Erweiterte Prompting-Elemente</h3>
<ul>
  <li><strong>Audio Profile</strong> &mdash; Name und Rolle der Figur.</li>
  <li><strong>Scene</strong> &mdash; Umgebungskontext, der Stimmung und Schauplatz festlegt.</li>
  <li><strong>Director&rsquo;s Notes</strong> &mdash; Regieanweisungen: Stil, Tempo, Akzent.</li>
  <li><strong>Sample Context</strong> &mdash; kontextuelle Verankerung für einen natürlichen Einstieg in die Darbietung.</li>
  <li><strong>Transcript</strong> &mdash; die genau gesprochenen Worte, zusammen mit den Audio-Tags.</li>
</ul>
<h3>Wichtige Hinweise</h3>
<p>Sie müssen nicht alles beschreiben – dem Modell Spielraum zu lassen, fördert oft die Natürlichkeit. Wägen Sie Genauigkeit und kreative Freiheit ab und bevorzugen Sie Fachterminologie und nuancierte Eigenschaften gegenüber einfachen Gefühlsetiketten.</p>
<h3>So verwenden Sie Prompts in Audiobook Maker</h3>
<p>Audiobook Maker liest den Kapiteltext direkt vor, daher fügen Sie Prompt-Hinweise direkt in den Text ein – auf zwei Arten:</p>
<ul>
  <li>Bearbeiten Sie die <strong>TXT</strong>-Eingabedatei vor dem Hochladen und fügen Sie Tags/Hinweise direkt in den Text ein.</li>
  <li>Oder laden Sie die erzeugte <strong>.ABM</strong>-Datei herunter, bearbeiten Sie die Kapiteltexte und laden Sie die geänderte <strong>.ABM</strong> erneut in Audiobook Maker hoch.</li>
</ul>
<p style="font-size:.85rem;color:var(--txm)">Quelle: <a href="https://ai.google.dev/gemini-api/docs/speech-generation" rel="nofollow noopener" target="_blank">Google AI &mdash; Speech generation</a></p>
""",

    "podcast": """
<section>
<h2>Verwandeln Sie Ihr Hörbuch in einen privaten Podcast</h2>
<p>Audiobook Maker generiert zusammen mit den Audiodateien ein <strong>vollständiges Podcast-Paket</strong> mit einem RSS 2.0-Feed. Um es als Podcast verfügbar zu machen, müssen die Dateien auf einem Webserver veröffentlicht werden, der aus dem Internet erreichbar ist. Die ideale Lösung ist Ihre <strong>eigene Website</strong> oder Ihr Hosting-Speicherplatz. Alternativ, für den persönlichen Gebrauch oder zum Teilen mit wenigen Freunden, können Sie eine kostenlose Lösung wie <strong>Netlify</strong> nutzen, die in dieser Anleitung beschrieben wird.</p>
<div style="background:#fff3cd;border-left:4px solid #f0c040;padding:10px 14px;border-radius:6px;margin:0 0 18px;font-size:.92rem;color:#5a4510"><strong>Empfohlene Nutzung:</strong> Diese Lösung ist für den persönlichen Gebrauch oder zum Teilen mit Familie und Freunden gedacht. Netlify bietet 100 GB/Monat kostenlose Bandbreite — mehr als ausreichend. Für öffentliche Verbreitung sollten Sie eigenes Webhosting in Betracht ziehen.</div>
</section>

<section>
<h2>Schritt für Schritt: Veröffentlichen Sie Ihr Hörbuch als Podcast</h2>
<ol>
<li><strong>Generieren Sie das Hörbuch im M4B-Format</strong> — Laden Sie in Audiobook Maker Ihre EPUB- oder PDF-Datei hoch, wählen Sie Sprache und Stimme und dann <strong>M4B</strong> als Ausgabeformat. Das Tool erstellt eine einzelne M4B-Datei mit eingebetteten Kapiteln und Cover — der professionelle Standard für Hörbücher.</li>
<li><strong>Generieren Sie auch das Podcast-RSS-Paket</strong> — Führen Sie nach der M4B-Generierung die Generierung erneut im <strong>Podcast-RSS</strong>-Modus durch, um ein ZIP mit der RSS-Feed-XML-Datei und den einzelnen MP3-Kapiteldateien zu erhalten (Podcasts benötigen eine Audiodatei pro Episode).</li>
<li><strong>Erstellen Sie ein kostenloses Netlify-Konto</strong> — Gehen Sie zu <strong>app.netlify.com</strong> und melden Sie sich mit E-Mail oder GitHub an. Keine Kreditkarte erforderlich. Der kostenlose Plan umfasst 100 GB Bandbreite, 10 GB Speicher und automatisches HTTPS.</li>
<li><strong>Auf Netlify hochladen</strong> — Ziehen Sie im Netlify-Dashboard unter <strong>Sites</strong> den gesamten extrahierten Ordner auf die gestrichelte Ablagezone. Die Seite ist in Sekunden online. Benennen Sie sie dann unter <em>Site configuration → Change site name</em> um (z.B. <code>mein-hoerbuch.netlify.app</code>).</li>
<li><strong>Feed überprüfen</strong> — Öffnen Sie die Feed-URL in Ihrem Browser: <br><code>https://ihr-seitenname.netlify.app/podcast.xml</code><br>Wenn Sie XML-Inhalt mit Ihren Kapiteltiteln sehen, ist Ihr Podcast live und bereit!</li>
</ol>
</section>

<section>
<h2>Importieren Sie Ihren Podcast in Hör-Apps</h2>
<table>
<thead><tr><th>App</th><th>Plattform</th><th>So fügen Sie ihn hinzu</th></tr></thead>
<tbody>
<tr><td><strong>Apple Podcasts</strong></td><td>iOS / Mac</td><td><strong>iPhone:</strong> Mediathek → Mehr → Sendung per URL hinzufügen → Feed-URL einfügen<br><strong>Mac:</strong> Ablage → Sendung per URL folgen</td></tr>
<tr><td><strong>Pocket Casts</strong></td><td>Android / iOS / Web</td><td>Suchen → Feed-URL einfügen → Abonnieren</td></tr>
<tr><td><strong>AntennaPod</strong></td><td>Android</td><td>+ → Podcast per URL hinzufügen → URL einfügen</td></tr>
<tr><td><strong>Overcast</strong></td><td>iOS</td><td>+ → URL hinzufügen → Feed-URL einfügen</td></tr>
<tr><td><strong>Podcast Addict</strong></td><td>Android</td><td>+ → RSS-Feed → URL einfügen</td></tr>
</tbody>
</table>
<div style="background:#fff0f0;border-left:4px solid #e04040;padding:8px 14px;border-radius:6px;margin:12px 0;font-size:.9rem;color:#802020"><strong>Hinweis:</strong> Spotify unterstützt keine privaten RSS-Feeds. Verwenden Sie eine der oben aufgeführten Apps.</div>
</section>

<section>
<h2>Warum Ihr Hörbuch als Podcast hören?</h2>
<ul>
<li><strong>Automatische Lesezeichen</strong> — Genau dort weitermachen, wo Sie aufgehört haben, auch geräteübergreifend</li>
<li><strong>Episodenreihenfolge</strong> — Kapitel werden in Reihenfolge mit automatischem Weiterschalten abgespielt</li>
<li><strong>Vollständige Metadaten</strong> — Cover, Kapiteltitel und Buchinfo in Ihrer Podcast-App sichtbar</li>
<li><strong>Einstellbare Geschwindigkeit</strong> — Hören Sie mit 1,5x, 2x oder jeder bevorzugten Geschwindigkeit, mit Sleep-Timer</li>
<li><strong>Streaming</strong> — Kein Download aller Dateien nötig; streamen Sie jedes Kapitel beim Hören</li>
<li><strong>Mit Familie teilen</strong> — Senden Sie die Feed-URL an Familienmitglieder; sie benötigen kein Netlify-Konto</li>
</ul>
</section>

<section>
<h2>Tipps für Podcast-Veröffentlichung</h2>
<ul>
<li><strong>Episoden aktualisieren:</strong> Laden Sie die Dateien erneut auf Netlify hoch, um die vorherige Version zu ersetzen. Ihre Podcast-App erkennt Änderungen bei der nächsten Aktualisierung.</li>
<li><strong>Mehrere Bücher:</strong> Erstellen Sie eine separate Netlify-Site für jedes Hörbuch, um die Feeds organisiert zu halten.</li>
<li><strong>Speicherlimits:</strong> Der kostenlose Netlify-Plan umfasst 10 GB Speicher (~12 vollständige Hörbücher). Entfernen Sie fertige Bücher, um Speicherplatz freizugeben.</li>
<li><strong>Privatsphäre:</strong> Die Podcast-URL ist technisch öffentlich (jeder mit dem Link kann abonnieren), erscheint aber nicht in Podcast-Verzeichnissen oder Suchmaschinen. Sie ist "privat" in dem Sinne, dass sie nicht gelistet ist.</li>
<li><strong>Benutzerdefinierte Domain:</strong> Netlify unterstützt benutzerdefinierte Domains im kostenlosen Plan, wenn Sie eine personalisierte URL wünschen.</li>
</ul>
</section>

<section>
<h2>Häufig gestellte Fragen</h2>
<details><summary>Ist Netlify wirklich kostenlos für das Hosten meines Podcasts?</summary>
<p>Ja. Der kostenlose Starter-Plan von Netlify umfasst 100 GB/Monat Bandbreite und 10 GB Speicher. Für einen typischen Hörbuch-Podcast (10-20 Episoden, ~5 MB pro Stück) ist das mehr als ausreichend für den persönlichen Gebrauch. Bei Überschreitung können Sie auf Netlify Pro ($19/Monat) upgraden oder eigenes Hosting nutzen.</p>
</details>
<details><summary>Warum M4B-Format statt MP3 für das Hörbuch verwenden?</summary>
<p>M4B ist der professionelle Standard für Hörbücher. Eine einzelne M4B-Datei enthält alle Kapitel als Navigationsmarker, eingebettetes Cover und Metadaten. Sie wird von Apple Books, Audible und allen großen Hörbuch-Apps unterstützt. MP3 eignet sich gut für maximale Kompatibilität, aber M4B bietet ein viel besseres Hörerlebnis mit Kapitelnavigation.</p>
</details>
<details><summary>Kann ich meinen Podcast bei Apple Podcasts oder Spotify einreichen?</summary>
<p>Nicht mit einem privaten Netlify-Feed. Apple Podcasts Connect und Spotify for Podcasters erfordern Feeds, die auf zugelassenen Plattformen mit spezifischen Anforderungen gehostet werden (Cover-Größe, Kategorien usw.). Der Netlify-Ansatz ist für <strong>persönliche private Podcasts</strong> — ideal zum Hören eigener Bücher oder zum Teilen mit engen Freunden und Familie.</p>
</details>
<details><summary>Was kann ich verwenden, wenn ich Netlify nicht möchte?</summary>
<p>Jedes statische Webhosting funktioniert: GitHub Pages, Cloudflare Pages, Vercel oder Ihr eigener Webserver. Laden Sie einfach den extrahierten Podcast-Ordner an einen beliebigen über das Web zugänglichen Ort hoch und die RSS-Feed-URL funktioniert in Podcast-Apps. Netlify wird empfohlen, weil es kostenlos, schnell und konfigurationslos ist.</p>
</details>
<details><summary>Können Podcast-Apps Episoden für Offline-Hören herunterladen?</summary>
<p>Ja. Sobald Sie den Feed in einer Podcast-App abonniert haben, können Sie einzelne Episoden für Offline-Hören herunterladen, genau wie bei jedem anderen Podcast. Die App verwaltet Download, Wiedergabeposition und Löschung automatisch.</p>
</details>
</section>
""",
}


_GUIDE_BODY_ZH = {
    "free-ebooks": """
<section>
<h2>在哪里下载免费电子书</h2>
<p>数千本优秀图书完全免费且可合法下载——公共领域的经典、以开放许可发布的现代作品以及社区项目。获得免费EPUB后，您可以用 <a href="/">Audiobook Maker</a> 在几分钟内将其转换为有声书。本指南列出了最佳的免费电子书来源，并向您展示如何收听它们。</p>
</section>

<section>
<h2>8个最佳免费电子书网站</h2>
<ul>
<li><a href="https://www.gutenberg.org" target="_blank" rel="noopener">Project Gutenberg</a> — 超过70,000本免费的公共领域图书。世界上最大、最古老的藏书库，提供可靠的EPUB下载。</li>
<li><a href="https://standardebooks.org" target="_blank" rel="noopener">Standard Ebooks</a> — 精心整理、排版精美的经典版本，配有现代字体和原创封面。</li>
<li><a href="https://archive.org/details/texts" target="_blank" rel="noopener">Internet Archive</a> — 庞大的数字图书馆，拥有数百万种文本、有声书和历史期刊。</li>
<li><a href="https://manybooks.net" target="_blank" rel="noopener">ManyBooks</a> — 超过50,000本免费电子书，界面现代并提供个性化阅读推荐。</li>
<li><a href="https://www.feedbooks.com/publicdomain" target="_blank" rel="noopener">Feedbooks</a> — 优雅的公共领域电子书目录，可直接轻松下载。</li>
<li><a href="https://books.google.com/books?&as_ebook=on&as_brr=1" target="_blank" rel="noopener">Google Books</a> — 数百万本数字化图书；按"免费电子书"筛选可找到免费书目。</li>
<li><a href="https://www.liberliber.it/online/opere/libri/" target="_blank" rel="noopener">Liber Liber</a> — 意大利文学经典的参考来源：但丁、曼佐尼、皮兰德娄等众多作家。</li>
<li><a href="https://openlibrary.org/read" target="_blank" rel="noopener">Open Library</a> — 由Internet Archive运营，免费数字借阅现代和经典电子书。</li>
</ul>
</section>

<section>
<h2>公共领域 vs. 受版权保护的图书</h2>
<p><strong>公共领域</strong>图书——通常是作者去世超过70年的作品——可以自由下载、分享和转换，不受限制。Project Gutenberg、Standard Ebooks 和 Liber Liber 专门提供此类图书。</p>
<p><strong>受版权保护的</strong>图书即使免费提供也仍受保护。许多作者和出版商以 <a href="https://creativecommons.org" target="_blank" rel="noopener">Creative Commons</a> 许可或免费促销的形式发布现代作品——这些完全可以合法下载。请避开未经授权分享商业电子书的盗版网站：它们是非法的，且常常捆绑恶意软件。</p>
</section>

<section>
<h2>如何将免费电子书转换为有声书</h2>
<ol>
<li><strong>下载EPUB</strong>，从上述任一网站获取（EPUB优于PDF，章节识别更干净）。</li>
<li><strong>打开 <a href="/">Audiobook Maker</a></strong> 并上传文件——章节、标题、作者和封面会自动提取。</li>
<li><strong>选择神经网络AI语音</strong>，从超过50种语言的400多种选项中挑选，并免费试听预览。</li>
<li><strong>选择格式</strong>——MP3兼容性最佳，或 <a href="/guide/m4b-format/">M4B</a> 带嵌入式章节和封面。</li>
<li><strong>生成并下载</strong>——在手机、平板或任何有声书播放器上收听。</li>
</ol>
<p>详情请参阅完整指南 <a href="/guide/epub-to-audiobook/">EPUB转有声书 →</a>。</p>
</section>

<section>
<h2>选择合适免费电子书的技巧</h2>
<ul>
<li><strong>优先选择EPUB而非PDF</strong>：EPUB具有干净的章节结构，而PDF可能包含页眉、页码和需要清理的排版伪影。</li>
<li><strong>检查版本</strong>：Standard Ebooks 和 Liber Liber 提供格式最好的经典版本，错字和OCR错误更少。</li>
<li><strong>使用AI文本优化</strong>：对于PDF或粗糙扫描件，Audiobook Maker 可选的AI清理会在朗读前移除脚注、连字符和伪影。</li>
<li><strong>注意语言</strong>：选择与图书语言匹配的语音以获得自然发音。</li>
</ul>
</section>

<section>
<h2>常见问题</h2>
<details><summary>下载免费电子书合法吗？</summary>
<p>合法，前提是图书属于公共领域或由作者或出版商免费提供。本指南列出的所有网站都合法分发图书。请避开未经授权分享受版权保护商业书目的盗版网站。</p>
</details>
<details><summary>制作有声书时下载哪种格式最好？</summary>
<p>EPUB最好：它具有干净的章节结构，转换可靠。PDF也可以，但可能需要AI文本优化来移除排版伪影。TXT适合无章节的纯文本。</p>
</details>
<details><summary>我可以免费将这些免费电子书转换为有声书吗？</summary>
<p>可以。Audiobook Maker 使用神经网络TTS语音免费将EPUB、PDF和TXT转换为MP3或M4B有声书，无需注册，无使用限制。</p>
</details>
<details><summary>在哪里可以找到英语以外语言的免费电子书？</summary>
<p>Project Gutenberg 和 Internet Archive 托管数十种语言的图书。Liber Liber 专注于意大利语，Google Books 允许按语言筛选免费书目。然后 Audiobook Maker 可用超过50种语言进行朗读。</p>
</details>
</section>
""",

    "epub-to-audiobook": """
<section>
<h2>为什么要将EPUB转换为有声书？</h2>
<p>EPUB是最流行的电子书格式，被Apple Books、Google Play Books、Kobo和大多数数字图书馆使用。将EPUB转换为有声书让您可以<strong>在通勤、锻炼或做家务时听电子书</strong>。现代AI文字转语音听起来非常自然，远超过去的机器人朗读。</p>
<p>使用<a href="/">Audiobook Maker</a>，您可以直接在浏览器中免费将任何无DRM的EPUB转换为MP3或M4B有声书。无需安装软件，无需注册账户。</p>
</section>

<section>
<h2>如何将EPUB转换为有声书 — 分步指南</h2>
<ol>
<li><strong>上传您的EPUB文件</strong> — 拖放或点击选择。工具会自动提取章节和元数据（标题、作者、封面）。</li>
<li><strong>选择TTS语音</strong> — 从400多种AI神经语音中选择，覆盖50多种语言。在完整转换前可预览样本。</li>
<li><strong>选择章节</strong> — 选择要包含的章节。跳过目录、版权页或任何不想朗读的章节。</li>
<li><strong>选择输出格式</strong> — <strong>MP3</strong>（单文件或分章节ZIP）、<strong>M4B</strong>（带内嵌章节和封面的单文件 — 非常适合Apple Books和有声书播放器）或<strong>播客RSS</strong>（私人播客订阅源）。</li>
<li><strong>点击"生成"</strong> — TTS引擎为每个章节配音。您将看到进度条，完成后可选择接收邮件通知。</li>
<li><strong>下载并收听</strong> — 下载您的有声书并在任何设备上开始收听。</li>
</ol>
</section>

<section>
<h2>EPUB转有声书的最佳语音</h2>
<p>Audiobook Maker使用<strong>Microsoft Edge神经TTS</strong>（与Azure认知服务相同的引擎）。以下是可用的最自然免费语音：</p>
<ul>
<li><strong>英语（美国）</strong>：Aria, Jenny, Guy, Davis, Jane — 温暖富有表现力的朗读</li>
<li><strong>英语（英国）</strong>：Sonia, Ryan, Libby — 非常适合英国文学</li>
<li><strong>意大利语</strong>：Isabella, Diego, Elsa — 自然的意大利语朗读</li>
<li><strong>法语</strong>：Denise, Henri — 清晰的法语发音</li>
<li><strong>德语</strong>：Katja, Conrad — 清晰的德语语音</li>
<li><strong>西班牙语</strong>：Elvira, Alvaro — 流畅的西班牙语朗读</li>
<li><strong>中文</strong>：晓晓, 云扬 — 自然的普通话语音</li>
</ul>
<p>Google Cloud TTS Chirp3-HD也可提供更高质量（每月前100万字符免费）。</p>
</section>

<section>
<h2>EPUB转MP3 vs EPUB转M4B：应选择哪种格式？</h2>
<p><strong>MP3</strong>具有通用兼容性 — 所有手机、平板和电脑都能播放MP3文件。如果您需要最大兼容性或在多个设备上收听，请选择MP3。</p>
<p><strong>M4B</strong>是专业的有声书格式。它是一个包含所有章节作为导航标记的单一文件，还嵌入了封面和元数据（作者、标题、类型）。M4B文件支持Apple Books、Audible和大多数有声书应用。<a href="/guide/m4b-format/">了解更多关于M4B格式的信息 →</a></p>
</section>

<section>
<h2>最佳EPUB转有声书体验的技巧</h2>
<ul>
<li><strong>首先移除DRM</strong>：来自Kindle、Apple Books或Kobo的商业电子书通常有DRM保护。在转换前需要将其移除（仅限个人使用，在法律允许的情况下）。</li>
<li><strong>清理文本</strong>：某些EPUB包含格式残余（页码、页眉、脚注）。Audiobook Maker可选AI文本优化可以自动清理这些。</li>
<li><strong>在完整生成前预览</strong>：始终先生成免费预览以检查语音质量和节奏。</li>
<li><strong>使用章节选择器</strong>：跳过前言（目录、序言）和后记（索引、广告）以获得更清晰的收听体验。</li>
<li><strong>选择M4B用于长书</strong>：M4B格式将所有内容组织在一个文件中，包含章节导航 — 比管理多个MP3文件要好得多。</li>
</ul>
</section>

<section>
<h2>常见问题</h2>
<details><summary>将EPUB转换为有声书真的免费吗？</summary>
<p>是的。Audiobook Maker是开源软件（AGPL-3.0）。TTS转换使用Microsoft Edge TTS，完全免费且无使用限制。可选的AI文本优化（DeepSeek LLM）在超出免费阈值后有少量费用。</p>
</details>
<details><summary>我可以将Kindle书籍转换为有声书吗？</summary>
<p>Kindle书籍使用Amazon专有的AZW/KFX格式并带有DRM。您需要先使用Calibre等工具移除DRM并转换为EPUB，然后将EPUB上传到Audiobook Maker。</p>
</details>
<details><summary>EPUB转有声书需要多长时间？</summary>
<p>每章约2-3分钟（根据章节长度和服务器负载有所不同）。一本典型的300页书（约20章）大约需要40-60分钟。完成后您将收到邮件通知。</p>
</details>
<details><summary>支持哪些语言？</summary>
<p>50多种语言，包括英语、意大利语、法语、西班牙语、德语、中文、日语、韩语、葡萄牙语、俄语、阿拉伯语、印地语等。每种语言都有多种语音选项。</p>
</details>
<details><summary>Audiobook Maker可以在手机上使用吗？</summary>
<p>可以。该网络应用可在任何现代浏览器中运行，支持桌面、平板或手机。但对于大型EPUB文件，建议使用桌面浏览器以获得更快的上传和处理速度。</p>
</details>
</section>
""",

    "m4b-format": """
<section>
<h2>什么是M4B格式？</h2>
<p><strong>M4B</strong>（MPEG-4有声书）是有声书的标准文件格式。基于MPEG-4容器（与MP4视频同系列），M4B本质上是一个AAC音频文件，具有专为有声书设计的特殊功能：</p>
<ul>
<li><strong>章节标记</strong>：内嵌的导航点让您可以在章节之间跳转</li>
<li><strong>封面艺术</strong>：书籍封面嵌入文件元数据中</li>
<li><strong>书签</strong>：有声书播放器会记住您的收听位置（通过iCloud可在设备间同步）</li>
<li><strong>元数据</strong>：标题、作者、旁白者、类型和出版日期都存储在文件中</li>
<li><strong>变速播放</strong>：播放器可以加速或减速播放而不改变音调</li>
</ul>
<p>M4B是<strong>Apple Books</strong>、<strong>Audible</strong>（Aax是受DRM保护的M4B变体）以及iOS和Android上大多数有声书应用使用的格式。</p>
</section>

<section>
<h2>M4B vs MP3有声书：全面对比</h2>
<table>
<thead><tr><th>功能</th><th>M4B</th><th>MP3</th></tr></thead>
<tbody>
<tr><td>章节导航</td><td>内建章节标记</td><td>无内建章节</td></tr>
<tr><td>封面艺术</td><td>嵌入文件中</td><td>可嵌入（ID3）但非普遍支持</td></tr>
<tr><td>位置保存</td><td>是（所有M4B播放器）</td><td>取决于播放器</td></tr>
<tr><td>文件大小（相同质量）</td><td>约小30-40%（AAC编码）</td><td>同等质量下更大</td></tr>
<tr><td>兼容性</td><td>Apple Books, Audible, BookPlayer, Listen及大多数有声书应用</td><td>通用 — 所有设备</td></tr>
<tr><td>单一文件</td><td>是 — 整本书在一个文件中</td><td>通常每章一个文件或一个合并文件</td></tr>
<tr><td>书签同步</td><td>是（Apple生态系统）</td><td>否</td></tr>
<tr><td>最适合</td><td>iOS/Mac用户、有声书收藏者、长书</td><td>最大兼容性、分享、简单播放器</td></tr>
</tbody>
</table>
<p><strong>总结：</strong>如果您使用Apple Books或专用有声书应用，请选择M4B。如果您需要在基本MP3播放器或不支持M4B的车载音响上播放，请选择MP3。</p>
</section>

<section>
<h2>如何免费创建带章节的M4B文件</h2>
<p>创建M4B文件曾经需要复杂的ffmpeg命令或付费软件。<a href="/">Audiobook Maker</a>自动化了整个流程：</p>
<ol>
<li><strong>上传您的电子书</strong>（EPUB、PDF或TXT）— 自动提取章节</li>
<li><strong>选择M4B作为输出格式</strong> — 工具会处理一切：TTS配音、AAC编码、章节标记、封面嵌入</li>
<li><strong>下载M4B文件</strong> — 即可导入Apple Books或任何M4B兼容播放器</li>
</ol>
<p>生成的M4B使用<strong>64 kbps AAC音频</strong>（针对语音优化），包含<strong>1400×1400封面艺术</strong>，并具有适当的iTunes兼容元数据标签。每个章节都会在您的有声书播放器中显示为导航点。</p>
</section>

<section>
<h2>如何播放M4B文件</h2>
<p><strong>iOS / Mac：</strong>Apple Books（内置）— 将M4B拖入Books或通过Finder/iCloud同步。</p>
<p><strong>Android：</strong>Listen Audiobook Player、Smart Audiobook Player、Sirin — 均支持带章节的M4B。</p>
<p><strong>Windows：</strong>Apple Books（通过iTunes）、VLC媒体播放器、BookPlayer（Microsoft Store）。</p>
<p><strong>Linux：</strong>VLC、Cozy（GTK有声书播放器）。</p>
<p><strong>汽车 / 基本MP3播放器：</strong>请转换为MP3 — 大多数车载音响无法读取M4B文件。</p>
</section>

<section>
<h2>常见问题</h2>
<details><summary>我可以将M4B转换为MP3吗？</summary>
<p>可以。您可以使用Audiobook Maker生成MP3输出，或使用ffmpeg转换现有M4B：<code>ffmpeg -i book.m4b -acodec libmp3lame -b:a 128k book.mp3</code>。注意转换过程中章节标记会丢失。</p>
</details>
<details><summary>我可以将M4B按章节分割吗？</summary>
<p>可以。如<code>m4b-tool</code>或ffmpeg等工具可以按章节标记分割M4B文件。如果您更喜欢单独的文件，Audiobook Maker也可以按章节输出单独的MP3文件。</p>
</details>
<details><summary>哪些有声书应用支持M4B？</summary>
<p>Apple Books（iOS/Mac）、BookPlayer（iOS）、Listen Audiobook Player（Android）、Smart Audiobook Player（Android）、Bound（iOS）、Sirin（Android）、VLC（所有平台）以及带Audnexus插件的Plex。</p>
</details>
<details><summary>M4B有声书应使用什么比特率？</summary>
<p>Audiobook Maker使用64 kbps AAC，这是语音内容的标准。语音不需要高比特率 — 64 kbps AAC对于朗读来说听起来与128 kbps MP3相同，但文件大小只有一半。</p>
</details>
</section>
""",

    "text-to-speech-audiobook": """
<section>
<h2>什么是AI文字转语音有声书创作？</h2>
<p>AI文字转语音（TTS）有声书创作使用神经AI语音将书面文字转换为口语音频。与旧的机器人式TTS不同，现代神经语音听起来非常自然 — 具有适当的语调、节奏和情感。您现在可以<strong>将任何文本、电子书或文档转换为专业音质的有声书</strong>，无需聘请人类旁白者。</p>
<p><a href="/">Audiobook Maker</a>结合了最好的免费TTS引擎和易于使用的网页界面。上传EPUB、PDF或TXT文件，即可获得MP3、M4B或播客RSS输出 — 完全免费。</p>
</section>

<section>
<h2>2026年最佳免费TTS有声书引擎</h2>
<table>
<thead><tr><th>TTS引擎</th><th>语音数</th><th>语言数</th><th>费用</th><th>最适合</th></tr></thead>
<tbody>
<tr><td><strong>Microsoft Edge TTS</strong></td><td>400+</td><td>50+</td><td>免费</td><td>通用有声书创作，最佳免费语音</td></tr>
<tr><td><strong>Google Cloud TTS (Chirp3-HD)</strong></td><td>50+</td><td>30+</td><td>每月100万字符免费，超出后付费</td><td>高级品质，富有表现力的朗读</td></tr>
<tr><td><strong>Speechify</strong></td><td>30+</td><td>20+</td><td>免费增值（有限）</td><td>快速文章阅读，移动端使用</td></tr>
<tr><td><strong>NaturalReader</strong></td><td>100+</td><td>20+</td><td>免费增值（有限）</td><td>阅读障碍支持，教育用途</td></tr>
<tr><td><strong>ElevenLabs</strong></td><td>自定义</td><td>30+</td><td>每月1万字符免费</td><td>超逼真语音克隆</td></tr>
<tr><td><strong>Play.ht</strong></td><td>800+</td><td>140+</td><td>每月5千字符免费</td><td>多语言，语音多样性</td></tr>
</tbody>
</table>
<p><strong>Audiobook Maker默认使用Microsoft Edge TTS</strong> — 完全免费，无使用限制，提供400多种语音。Google TTS Chirp3-HD适用于需要高级品质的用户。与Speechify或NaturalReader不同，Audiobook Maker<strong>没有付费墙、无需注册、无使用限制</strong>。</p>
</section>

<section>
<h2>Speechify替代品：为什么选择Audiobook Maker？</h2>
<p>Speechify是一款流行的TTS应用，但其免费版本非常有限。以下是Audiobook Maker的对比：</p>
<ul>
<li><strong>100%免费</strong>对比Speechify的$139/年订阅</li>
<li><strong>无使用限制</strong> — 转换整本书，不仅是短文</li>
<li><strong>带章节的M4B输出</strong> — Speechify仅导出简单音频</li>
<li><strong>播客RSS订阅源</strong> — 在任何播客应用中收听</li>
<li><strong>开源</strong> — AGPL-3.0许可，可查看和修改代码</li>
<li><strong>自托管选项</strong> — 在您自己的服务器上运行以获得完全隐私</li>
<li><strong>AI文本优化</strong> — 自动清理和改进文本以获得更好的朗读效果</li>
</ul>
<p>如果您需要为完整书籍寻找<strong>免费的Speechify替代品</strong>，Audiobook Maker是最佳选择。</p>
</section>

<section>
<h2>如何使用AI语音创作有声书 — 分步指南</h2>
<ol>
<li><strong>上传文件</strong> — EPUB、PDF或纯文本（TXT）。工具自动检测章节并提取元数据。</li>
<li><strong>选择语音</strong> — 浏览400多种神经语音。每种语音都有预览可试听。</li>
<li><strong>选择输出格式</strong> — MP3适合通用兼容性，M4B适合带章节的Apple Books，播客RSS适合流媒体播放。</li>
<li><strong>生成</strong> — AI逐章为您的书籍配音。进度实时显示。</li>
<li><strong>下载并收听</strong> — 获取您的有声书为单文件、章节ZIP或订阅私人播客源。</li>
</ol>
</section>

<section>
<h2>免费TTS有声书 vs 人类旁白</h2>
<table>
<thead><tr><th>方面</th><th>AI TTS（Audiobook Maker）</th><th>人类旁白</th></tr></thead>
<tbody>
<tr><td>费用</td><td>免费</td><td>每本书500-5,000€+</td></tr>
<tr><td>时间</td><td>约1小时</td><td>2-6周</td></tr>
<tr><td>质量</td><td>非常好（神经、自然）</td><td>出色（人类表现力）</td></tr>
<tr><td>语言</td><td>50+ 即时可用</td><td>每位旁白一种语言</td></tr>
<tr><td>修改</td><td>即时重新生成</td><td>需重新录制</td></tr>
<tr><td>最适合</td><td>个人使用、草稿、独立作者</td><td>用于销售（Audible等）的商业有声书</td></tr>
</tbody>
</table>
<p>对于个人收听、审核自己的文本或为公共领域书籍创建音频版本，AI TTS是最佳选择。对于旨在Audible上销售的商业有声书，人类旁白仍然是更可取的（也是ACX要求的）。</p>
</section>

<section>
<h2>常见问题</h2>
<details><summary>AI文字转语音的音质足以制作有声书吗？</summary>
<p>是的。现代神经TTS（如Microsoft Edge TTS和Google Chirp3-HD）声音非常自然。对于非虚构作品，大多数听众无法分辨与人类旁白的区别。对于有多个角色和情感范围的小说，人类旁白仍然更优 — 但差距正在迅速缩小。</p>
</details>
<details><summary>我可以将AI生成的有声书用于商业用途吗？</summary>
<p>可以，但有一些限制。Microsoft Edge TTS和Google TTS允许将生成的音频用于商业用途。然而，像Audible（ACX）这样的平台目前要求新提交的作品使用人类旁白。AI有声书可以在其他平台上销售或用于个人项目、YouTube视频和教育内容。</p>
</details>
<details><summary>我可以免费转换多少个字符？</summary>
<p>使用Microsoft Edge TTS：无限。没有使用限制或配额。使用Google Cloud TTS Chirp3-HD：每月100万字符免费，超出后适用Google Cloud标准资费。</p>
</details>
<details><summary>Audiobook Maker可以离线使用吗？</summary>
<p>audiobook-maker.com上托管的版本需要互联网连接。但该软件是开源的 — 您可以将其安装在自己的计算机或服务器上，以完整的离线能力在本地运行。</p>
</details>
<details><summary>什么是最好的中文有声书TTS语音？</summary>
<p>最好的中文Edge TTS语音是<strong>晓晓</strong>（温暖女声）和<strong>云扬</strong>（清晰男声）。对于高级品质，Google Chirp3-HD提供最具表现力的神经语音。<a href="/">在Audiobook Maker上免费试听预览</a>，找到您最喜欢的语音。</p>
</details>
</section>
""",

    "gemini-tts": """
<p>Gemini TTS 是 Audiobook Maker PREMIUM 语音背后的神经网络引擎。本指南介绍可用的语音、支持的语言，以及如何通过提示来控制朗读效果。</p>

<h2 id="voices">语音选项</h2>
<p>30 种不同的语音，各具特色。语音名称固定不变；特征描述概括其自然音色。</p>
<table>
  <thead><tr><th>语音</th><th>特征</th></tr></thead>
  <tbody>
    <tr><td>Zephyr</td><td>明亮</td></tr>
    <tr><td>Puck</td><td>轻快</td></tr>
    <tr><td>Charon</td><td>信息丰富</td></tr>
    <tr><td>Kore</td><td>坚定</td></tr>
    <tr><td>Fenrir</td><td>易激动</td></tr>
    <tr><td>Leda</td><td>年轻</td></tr>
    <tr><td>Orus</td><td>坚定</td></tr>
    <tr><td>Aoede</td><td>轻松</td></tr>
    <tr><td>Callirrhoe</td><td>随和</td></tr>
    <tr><td>Autonoe</td><td>明亮</td></tr>
    <tr><td>Enceladus</td><td>气声</td></tr>
    <tr><td>Iapetus</td><td>清晰</td></tr>
    <tr><td>Umbriel</td><td>随和</td></tr>
    <tr><td>Algieba</td><td>流畅</td></tr>
    <tr><td>Despina</td><td>流畅</td></tr>
    <tr><td>Erinome</td><td>清晰</td></tr>
    <tr><td>Algenib</td><td>低沉沙哑</td></tr>
    <tr><td>Rasalgethi</td><td>信息丰富</td></tr>
    <tr><td>Laomedeia</td><td>轻快</td></tr>
    <tr><td>Achernar</td><td>柔和</td></tr>
    <tr><td>Alnilam</td><td>坚定</td></tr>
    <tr><td>Schedar</td><td>平稳</td></tr>
    <tr><td>Gacrux</td><td>成熟</td></tr>
    <tr><td>Pulcherrima</td><td>直接</td></tr>
    <tr><td>Achird</td><td>友好</td></tr>
    <tr><td>Zubenelgenubi</td><td>随意</td></tr>
    <tr><td>Vindemiatrix</td><td>温和</td></tr>
    <tr><td>Sadachbia</td><td>活泼</td></tr>
    <tr><td>Sadaltager</td><td>博学</td></tr>
    <tr><td>Sulafat</td><td>温暖</td></tr>
  </tbody>
</table>

<h2 id="languages">支持的语言</h2>
<p>Gemini TTS 支持以下语言（括号内为 BCP-47 代码）：</p>
<p>Arabic (ar), Filipino (fil), Bangla (bn), Finnish (fi), Dutch (nl), Galician (gl), English (en), Georgian (ka), French (fr), Greek (el), German (de), Gujarati (gu), Hindi (hi), Haitian Creole (ht), Indonesian (id), Hebrew (he), Italian (it), Hungarian (hu), Japanese (ja), Icelandic (is), Korean (ko), Javanese (jv), Marathi (mr), Kannada (kn), Polish (pl), Konkani (kok), Portuguese (pt), Romanian (ro), Russian (ru), Spanish (es), Tamil (ta), Telugu (te), Thai (th), Turkish (tr), Ukrainian (uk), Vietnamese (vi), Afrikaans (af), Albanian (sq), Amharic (am), Armenian (hy), Azerbaijani (az), Basque (eu), Belarusian (be), Bulgarian (bg), Burmese (my), Catalan (ca), Cebuano (ceb), Chinese Mandarin (cmn), Croatian (hr), Czech (cs), Danish (da), Estonian (et), Latvian (lv), Lithuanian (lt), Luxembourgish (lb), Macedonian (mk), Maithili (mai), Malagasy (mg), Malay (ms), Malayalam (ml), Mongolian (mn), Nepali (ne), Norwegian Bokm&aring;l (nb), Norwegian Nynorsk (nn), Odia (or), Pashto (ps), Persian (fa), Punjabi (pa), Serbian (sr), Sindhi (sd), Sinhala (si), Slovak (sk), Slovenian (sl), Swahili (sw), Swedish (sv), Urdu (ur).</p>

<h2 id="prompting">提示指南</h2>
<p>模型会自动根据文本推断朗读方式。你可以通过内联标签和结构化指示进一步加以引导。</p>
<h3>内联音频标签</h3>
<p>诸如 <code>[whispers]</code>、<code>[laughs]</code>、<code>[excitedly]</code>、<code>[bored]</code> 和 <code>[shouting]</code> 等内联修饰符可改变语气、节奏和情感质感。请发挥创意，尝试不同的演绎方式。</p>
<h3>高级提示要素</h3>
<ul>
  <li><strong>Audio Profile</strong> &mdash; 角色名称与身份设定。</li>
  <li><strong>Scene</strong> &mdash; 营造氛围和场景的环境背景。</li>
  <li><strong>Director&rsquo;s Notes</strong> &mdash; 表演指导：风格、节奏、口音。</li>
  <li><strong>Sample Context</strong> &mdash; 为自然进入表演提供的上下文铺垫。</li>
  <li><strong>Transcript</strong> &mdash; 需要朗读的确切文字，并配以音频标签。</li>
</ul>
<h3>关键建议</h3>
<p>不必事无巨细地描述——给模型留出发挥空间往往更显自然。在精确性与创作自由之间取得平衡，并优先使用行业术语和层次化的特征描述，而非简单的情绪标签。</p>
<h3>如何在 Audiobook Maker 中使用提示</h3>
<p>Audiobook Maker 会直接朗读章节文本，因此提示要写入文本本身，有两种方式：</p>
<ul>
  <li>在上传前编辑输入的 <strong>TXT</strong> 文件，直接在文本中插入标签/指示。</li>
  <li>或下载生成的 <strong>.ABM</strong> 文件，编辑各章节文本，再将修改后的 <strong>.ABM</strong> 重新上传到 Audiobook Maker。</li>
</ul>
<p style="font-size:.85rem;color:var(--txm)">来源：<a href="https://ai.google.dev/gemini-api/docs/speech-generation" rel="nofollow noopener" target="_blank">Google AI &mdash; Speech generation</a></p>
""",

    "podcast": """
<section>
<h2>将您的有声书转换为私人播客</h2>
<p>Audiobook Maker在生成音频文件的同时，还会生成一个包含RSS 2.0订阅源的<strong>完整播客包</strong>。要将其作为播客使用，文件需要发布到可从互联网访问的Web服务器上。理想的解决方案是您的<strong>自己的网站</strong>或托管空间。或者，对于个人使用或与几个朋友分享，您可以使用免费解决方案，如本指南中描述的<strong>Netlify</strong>。</p>
<div style="background:#fff3cd;border-left:4px solid #f0c040;padding:10px 14px;border-radius:6px;margin:0 0 18px;font-size:.92rem;color:#5a4510"><strong>推荐用途：</strong>此解决方案专为个人使用或与家人朋友分享而设计。Netlify提供每月100 GB的免费带宽 — 绰绰有余。对于公开发布，请考虑使用您自己的网站托管。</div>
</section>

<section>
<h2>分步指南：将您的有声书发布为播客</h2>
<ol>
<li><strong>以M4B格式生成有声书</strong> — 在Audiobook Maker中，上传您的EPUB或PDF文件，选择语言和语音，然后选择<strong>M4B</strong>作为输出格式。该工具会创建一个带有嵌入章节和封面的单个M4B文件 — 这是有声书的专业标准。</li>
<li><strong>同时生成播客RSS包</strong> — 生成M4B后，以<strong>播客RSS</strong>模式再次运行生成，获得包含RSS订阅源XML文件和各个章节MP3文件的ZIP（播客需要每集一个音频文件）。</li>
<li><strong>创建免费Netlify账户</strong> — 访问<strong>app.netlify.com</strong>，使用邮箱或GitHub注册。无需信用卡。免费计划包括100 GB带宽、10 GB存储和自动HTTPS。</li>
<li><strong>上传到Netlify</strong> — 在Netlify控制面板中，在<strong>Sites</strong>下，将整个解压后的文件夹拖到虚线放置区域。网站几秒钟内即可上线。然后从<em>Site configuration → Change site name</em>重命名（如<code>my-audiobook.netlify.app</code>）。</li>
<li><strong>验证订阅源</strong> — 在浏览器中打开订阅源URL：<br><code>https://your-site-name.netlify.app/podcast.xml</code><br>如果您看到包含章节标题的XML内容，您的播客已上线并准备就绪！</li>
</ol>
</section>

<section>
<h2>将您的播客导入收听应用</h2>
<table>
<thead><tr><th>应用</th><th>平台</th><th>如何添加</th></tr></thead>
<tbody>
<tr><td><strong>Apple Podcasts</strong></td><td>iOS / Mac</td><td><strong>iPhone：</strong>资料库 → 更多 → 通过URL添加节目 → 粘贴订阅源URL<br><strong>Mac：</strong>文件 → 通过URL关注节目</td></tr>
<tr><td><strong>Pocket Casts</strong></td><td>Android / iOS / Web</td><td>搜索 → 粘贴订阅源URL → 订阅</td></tr>
<tr><td><strong>AntennaPod</strong></td><td>Android</td><td>+ → 通过URL添加播客 → 粘贴URL</td></tr>
<tr><td><strong>Overcast</strong></td><td>iOS</td><td>+ → 添加URL → 粘贴订阅源URL</td></tr>
<tr><td><strong>Podcast Addict</strong></td><td>Android</td><td>+ → RSS订阅源 → 粘贴URL</td></tr>
</tbody>
</table>
<div style="background:#fff0f0;border-left:4px solid #e04040;padding:8px 14px;border-radius:6px;margin:12px 0;font-size:.9rem;color:#802020"><strong>注意：</strong>Spotify不支持添加私人RSS订阅源。请使用以上列出的应用。</div>
</section>

<section>
<h2>为什么要将有声书作为播客收听？</h2>
<ul>
<li><strong>自动书签</strong> — 精确从您停止的位置继续，甚至跨设备同步</li>
<li><strong>剧集排序</strong> — 章节按顺序播放，自动前进到下一集</li>
<li><strong>完整元数据</strong> — 播客应用中可看到封面、章节标题和书籍信息</li>
<li><strong>可调速度</strong> — 以1.5倍、2倍或任何您喜欢的速度收听，带睡眠定时器</li>
<li><strong>流媒体播放</strong> — 无需下载所有文件；收听时流式传输每个章节</li>
<li><strong>与家人分享</strong> — 将订阅源URL发送给家人；他们不需要Netlify账户</li>
</ul>
</section>

<section>
<h2>播客发布技巧</h2>
<ul>
<li><strong>更新剧集：</strong>将文件重新上传到Netlify以替换之前的版本。您的播客应用将在下次刷新时检测到更改。</li>
<li><strong>多本书：</strong>为每本有声书创建单独的Netlify站点以保持订阅源整洁。</li>
<li><strong>存储限制：</strong>Netlify免费计划包括10 GB存储（约12本完整有声书）。移除已完成的书籍以释放空间。</li>
<li><strong>隐私：</strong>播客URL在技术上是公开的（任何有链接的人都可以订阅），但不会出现在播客目录或搜索引擎中。它是"私密的"，因为不会被收录。</li>
<li><strong>自定义域名：</strong>如果您想要个性化URL，Netlify免费计划支持自定义域名。</li>
</ul>
</section>

<section>
<h2>常见问题</h2>
<details><summary>Netlify真的免费托管我的播客吗？</summary>
<p>是的。Netlify的免费Starter计划包括每月100 GB带宽和10 GB存储。对于典型的有声书播客（10-20集，每集约5 MB），这对个人使用绰绰有余。如果超出限制，您可以升级到Netlify Pro（$19/月）或使用自己的托管。</p>
</details>
<details><summary>为什么使用M4B格式而不是MP3？</summary>
<p>M4B是有声书的专业标准。单个M4B文件包含所有章节作为导航标记、嵌入的封面和元数据。它受Apple Books、Audible和所有主要有声书应用支持。MP3适合最大兼容性，但M4B提供更好的收听体验和章节导航。</p>
</details>
<details><summary>我可以将我的播客提交到Apple Podcasts或Spotify目录吗？</summary>
<p>使用私人Netlify订阅源是不行的。Apple Podcasts Connect和Spotify for Podcasters要求订阅源托管在具有特定要求（封面尺寸、类别等）的批准平台上。Netlify方法适用于<strong>个人私人播客</strong> — 非常适合收听自己的书籍或与亲密朋友和家人分享。</p>
</details>
<details><summary>如果我不想使用Netlify怎么办？</summary>
<p>任何静态Web托管都可以：GitHub Pages、Cloudflare Pages、Vercel或您自己的Web服务器。只需将解压后的播客文件夹上传到任何可通过Web访问的位置，RSS订阅源URL就可以在播客应用中工作。推荐Netlify因为它免费、快速且无需配置。</p>
</details>
<details><summary>播客应用可以下载剧集进行离线收听吗？</summary>
<p>可以。在播客应用中订阅订阅源后，您可以像下载任何其他播客一样下载单个剧集进行离线收听。应用会自动管理下载、播放位置和删除。</p>
</details>
</section>
""",
}

# Missing languages fall back to EN.
_GUIDE_BODY = {"it": _GUIDE_BODY_IT, "fr": _GUIDE_BODY_FR, "es": _GUIDE_BODY_ES, "de": _GUIDE_BODY_DE, "zh": _GUIDE_BODY_ZH}




# Date pubblicazione iniziale per guida (statica). dateModified = mtime del file sorgente.
_GUIDE_PUBLISHED = {
    "epub-to-audiobook": "2024-09-15",
    "m4b-format": "2024-10-01",
    "text-to-speech-audiobook": "2024-11-10",
    "podcast": "2025-01-20",
    "gemini-tts": "2026-06-09",
}

_GUIDE_SECTION = {
    "epub-to-audiobook": "Tutorials",
    "m4b-format": "File Formats",
    "text-to-speech-audiobook": "Text-to-Speech",
    "podcast": "Podcast Publishing",
    "gemini-tts": "Text-to-Speech",
}


def _build_article_ld(guide_id: str, lang: str, base_url: str, meta: dict) -> str:
    """Build Article JSON-LD schema for a guide page.

    Include datePublished/dateModified/image/keywords per AI citation engines
    (ChatGPT, Perplexity, Google AI Overview) e ranking E-E-A-T.
    """
    import json as _json
    import os as _os
    from datetime import datetime as _dt

    canonical = f"{base_url}/guide/{guide_id}/"
    base = base_url or "https://audiobook-maker.com"

    try:
        _mtime = _os.path.getmtime(__file__)
        date_modified = _dt.utcfromtimestamp(_mtime).strftime("%Y-%m-%d")
    except OSError:
        date_modified = _dt.utcnow().strftime("%Y-%m-%d")
    date_published = _GUIDE_PUBLISHED.get(guide_id, "2024-09-01")

    ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": meta.get("h1", meta["title"]),
        "description": meta["desc"],
        "url": canonical,
        "inLanguage": _HREFLANG_MAP.get(lang, "en"),
        "datePublished": date_published,
        "dateModified": date_modified,
        "image": {
            "@type": "ImageObject",
            "url": f"{base}/og-image.png",
            "width": 1200,
            "height": 630,
        },
        "author": {
            "@type": "Person",
            "name": "Giuseppe Frangiamone",
            "url": "https://github.com/gfrangiamone",
        },
        "publisher": {
            "@type": "Organization",
            "name": "Audiobook Maker",
            "url": base,
            "logo": {
                "@type": "ImageObject",
                "url": f"{base}/favicon-192.png",
                "width": 192,
                "height": 192,
            },
        },
        "isAccessibleForFree": True,
        "license": "https://www.gnu.org/licenses/agpl-3.0.html",
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": canonical,
        },
        "articleSection": _GUIDE_SECTION.get(guide_id, "Guide"),
        "keywords": meta.get("kw", ""),
    }
    return _json.dumps(ld, ensure_ascii=False)


def build_guide_html(
    guide_id: str,
    lang: str = "en",
    base_url: str = "",
    version: str = "",
) -> str:
    """Build complete HTML for a guide page.

    Args:
        guide_id: One of 'epub-to-audiobook', 'm4b-format', 'text-to-speech-audiobook'.
        lang: Language code (it, en, fr, es, de, zh).
        base_url: Base URL for canonical/hreflang (e.g. "https://audiobook-maker.com").
        version: App version string.

    Returns:
        Complete HTML string with SEO baked in.
    """
    import json as _json

    guide_meta_all = _GUIDE_META.get(guide_id)
    if not guide_meta_all:
        return f"<!-- Guide '{guide_id}' not found -->"

    meta = guide_meta_all.get(lang, guide_meta_all["en"])
    html_lang = _HREFLANG_MAP.get(lang, "en")
    # Self-canonical per language: matches the URL form indexed in sitemap.xml
    # (?lang={lang}) so each language version is treated as a distinct page.
    canonical = f"{base_url}/guide/{guide_id}/?lang={lang}" if base_url else ""

    # Hreflang tags
    hreflang_lines = []
    for lc, hl in _HREFLANG_MAP.items():
        href = f"{base_url}/guide/{guide_id}/?lang={lc}" if base_url else f"?lang={lc}"
        hreflang_lines.append(
            f'<link rel="alternate" hreflang="{hl}" href="{href}">'
        )
    x_default_href = f"{base_url}/guide/{guide_id}/" if base_url else "/"
    hreflang_lines.append(
        f'<link rel="alternate" hreflang="x-default" href="{x_default_href}">'
    )
    hreflang_block = "\n    ".join(hreflang_lines)

    # Article JSON-LD
    article_ld = _build_article_ld(guide_id, lang, base_url, meta)

    # Date visibili (datePublished/dateModified) per UX + AI scraping.
    import os as _os
    from datetime import datetime as _dt
    try:
        _mtime = _os.path.getmtime(__file__)
        _date_modified = _dt.utcfromtimestamp(_mtime).strftime("%Y-%m-%d")
    except OSError:
        _date_modified = _dt.utcnow().strftime("%Y-%m-%d")
    _date_published = _GUIDE_PUBLISHED.get(guide_id, "2024-09-01")
    _updated_label = {
        "it": "Ultimo aggiornamento", "en": "Last updated", "fr": "Dernière mise à jour",
        "es": "Última actualización", "de": "Zuletzt aktualisiert", "zh": "最后更新",
        "hi": "अंतिम बार अपडेट किया गया",
    }.get(lang, "Last updated")
    _published_label = {
        "it": "Pubblicato", "en": "Published", "fr": "Publié",
        "es": "Publicado", "de": "Veröffentlicht", "zh": "发布于",
        "hi": "प्रकाशित",
    }.get(lang, "Published")
    article_dates_html = (
        f'<p class="article-dates" style="font-size:.85rem;color:var(--txm);margin:8px 0 16px">'
        f'<time datetime="{_date_published}">{_published_label}: {_date_published}</time> &middot; '
        f'<time datetime="{_date_modified}">{_updated_label}: {_date_modified}</time>'
        f'</p>'
    )

    # BreadcrumbList JSON-LD
    crumb_names = {
        "it": "Guide", "en": "Guides", "fr": "Guides",
        "es": "Guías", "de": "Anleitungen", "zh": "指南",
        "hi": "गाइड",
    }
    crumb_name = crumb_names.get(lang, "Guides")
    breadcrumb_ld = _json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Audiobook Maker",
             "item": base_url or "https://audiobook-maker.com"},
            {"@type": "ListItem", "position": 2, "name": crumb_name,
             "item": canonical},
        ],
    }, ensure_ascii=False)

    # Body content — select by language, fall back to EN
    _body_dict = _GUIDE_BODY.get(lang, _GUIDE_BODY_EN)
    body = _body_dict.get(guide_id) or _GUIDE_BODY_EN.get(guide_id, "<p>Guide content not available.</p>")

    # App home URL for internal links
    app_home = f"{base_url}/{lang}/" if base_url else "/"

    # Open Graph locale + alternates
    og_locale = _OG_LOCALE_MAP.get(lang, "en_US")
    og_locale_alt_block = "\n".join(
        f'<meta property="og:locale:alternate" content="{loc}">'
        for loc in _OG_LOCALE_MAP.values() if loc != og_locale
    )

    return f"""<!DOCTYPE html>
<html lang="{html_lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="icon" type="image/png" sizes="192x192" href="/favicon-192.png">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/x-icon" href="/favicon.ico">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
<title>{meta["title"]}</title>
<meta name="description" content="{meta["desc"]}">
<meta name="keywords" content="{meta["kw"]}">
<meta name="robots" content="index, follow">
<meta name="theme-color" content="#c29a6c">
<link rel="canonical" href="{canonical}">
{hreflang_block}
<meta property="og:type" content="article">
<meta property="og:title" content="{meta["title"]}">
<meta property="og:description" content="{meta["desc"]}">
<meta property="og:site_name" content="Audiobook Maker">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{base_url}/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="{og_locale}">
{og_locale_alt_block}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{meta["title"]}">
<meta name="twitter:description" content="{meta["desc"]}">
<meta name="twitter:image" content="{base_url}/og-image.png">
<script type="application/ld+json">{article_ld}</script>
<script type="application/ld+json">{breadcrumb_ld}</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,500;0,600;0,700&family=DM+Serif+Display&display=swap" rel="stylesheet" media="print" onload="this.media='all'">
<noscript><link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,500;0,600;0,700&family=DM+Serif+Display&display=swap" rel="stylesheet"></noscript>
<style>
:root{{--bg:#f5f3ef;--srf:#ffffff;--srf2:#f0ede8;--brd:#d5d0c8;--tx:#2c2a26;--txd:#6b6760;--txm:#9e9890;--ac:#c47a2a;--ach:#d4903e;--r:12px}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'DM Sans','PingFang SC','Microsoft YaHei','Hiragino Sans GB','Noto Sans SC',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--tx);line-height:1.7;padding:20px;max-width:720px;margin:0 auto}}
h1{{font-family:'DM Serif Display',Georgia,serif;font-size:2rem;color:var(--ac);margin:24px 0 16px;line-height:1.25}}
h2{{font-family:'DM Serif Display',Georgia,serif;font-size:1.4rem;margin:32px 0 12px;color:var(--tx)}}
p,li{{margin-bottom:10px;color:var(--txd)}}
ol,ul{{padding-left:24px;margin-bottom:16px}}
li{{margin-bottom:6px}}
table{{width:100%;border-collapse:collapse;margin:16px 0;font-size:0.92rem}}
th,td{{border:1px solid var(--brd);padding:8px 12px;text-align:left}}
th{{background:var(--srf2);font-weight:600}}
details{{margin:12px 0;border:1px solid var(--brd);border-radius:var(--r);padding:12px 16px;background:var(--srf)}}
details summary{{cursor:pointer;font-weight:600;color:var(--tx)}}
details p{{margin-top:8px}}
a{{color:var(--ac);text-decoration:none}}
a:hover{{color:var(--ach);text-decoration:underline}}
code{{background:var(--srf2);padding:2px 6px;border-radius:4px;font-size:0.9em}}
.breadcrumb{{font-size:0.85rem;color:var(--txm);margin-bottom:20px}}
.breadcrumb a{{color:var(--txm)}}
.cta{{display:inline-block;margin:24px 0;padding:14px 32px;background:var(--ac);color:#fff;border-radius:var(--r);font-weight:600;text-decoration:none;font-size:1.05rem}}
.cta:hover{{background:var(--ach);color:#fff;text-decoration:none}}
footer{{margin-top:48px;padding-top:24px;border-top:1px solid var(--brd);font-size:0.85rem;color:var(--txm)}}
</style>
</head>
<body>
<nav class="breadcrumb">
<a href="{app_home}">Audiobook Maker</a> &rsaquo; {crumb_name} &rsaquo; {meta["h1"]}
</nav>
<article>
<h1>{meta["h1"]}</h1>
{article_dates_html}
{body}
<a class="cta" href="{app_home}">Try Audiobook Maker Free &rarr;</a>
</article>
<footer>
<p><strong>Audiobook Maker</strong> — Free & open-source EPUB/PDF to audiobook converter. 400+ AI voices, 50+ languages. <a href="{app_home}">Start converting</a>.</p>
</footer>
</body>
</html>"""
