#!/usr/bin/env python3
"""Generate complete guide_content.py with all 6 language translations + podcast guide."""
import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DEST = r'C:\Users\gfran\NEXT srl\Progetti - Documenti\AudioBook-Maker\guide_content.py'

HEAD = '''"""
SEO Guide Pages for Audiobook Maker.

Provides long-form guide content targeting informational keywords:
  - /guide/epub-to-audiobook/
  - /guide/m4b-format/
  - /guide/text-to-speech-audiobook/
  - /guide/podcast/

Each guide has full content in all 6 languages.
"""

from __future__ import annotations

_HREFLANG_MAP = {
    "it": "it", "en": "en", "fr": "fr",
    "es": "es", "de": "de", "zh": "zh-Hans",
}
_SUPPORTED_LANGS = list(_HREFLANG_MAP.keys())

'''

with open(DEST, 'w', encoding='utf-8') as f:
    f.write(HEAD)

# ── META DATA ──
META = '''# ── Guide metadata per language ──────────────────────────────────────────────

_GUIDE_META = {
    "epub-to-audiobook": {
        "en": {
            "title": "How to Convert EPUB to Audiobook Free — Complete Guide 2026 | Audiobook Maker",
            "desc": "Step-by-step guide: convert EPUB ebooks to MP3 or M4B audiobooks for free. Learn how to choose the best TTS voices, preserve chapters, and create professional audiobooks from any EPUB file. No software installation required.",
            "kw": "convert epub to audiobook, epub to mp3, epub to m4b, how to make audiobook from epub, epub audiobook converter free, best way to convert epub to audio, create audiobook from epub free, epub text to speech, turn ebook into audiobook",
            "h1": "How to Convert EPUB to Audiobook (Free & Online)",
        },
        "it": {"title":"Come Convertire EPUB in Audiolibro Gratis — Guida Completa | Audiobook Maker","desc":"Guida passo-passo per convertire ebook EPUB in audiolibri MP3 o M4B gratis. Scopri come scegliere le migliori voci TTS, preservare i capitoli e creare audiolibri professionali da qualsiasi file EPUB.","kw":"convertire epub in audiolibro, epub a mp3, epub a m4b, come creare audiolibro da epub, convertitore epub audiolibro gratis, epub text to speech italiano, trasformare ebook in audio","h1":"Come Convertire EPUB in Audiolibro (Gratis & Online)"},
        "fr": {"title":"Comment Convertir EPUB en Livre Audio Gratuit — Guide Complet | Audiobook Maker","desc":"Guide étape par étape pour convertir vos ebooks EPUB en livres audio MP3 ou M4B gratuitement. Apprenez à choisir les meilleures voix TTS et à créer des livres audio professionnels.","kw":"convertir epub en livre audio, epub vers mp3, epub vers m4b, convertisseur epub audio gratuit, comment créer un livre audio depuis epub","h1":"Comment Convertir EPUB en Livre Audio (Gratuit & en Ligne)"},
        "es": {"title":"Cómo Convertir EPUB a Audiolibro Gratis — Guía Completa | Audiobook Maker","desc":"Guía paso a paso para convertir ebooks EPUB en audiolibros MP3 o M4B gratis. Aprende a elegir las mejores voces TTS y crear audiolibros profesionales desde cualquier archivo EPUB.","kw":"convertir epub a audiolibro, epub a mp3, epub a m4b, convertidor epub audiolibro gratis, como crear audiolibro desde epub, epub texto a voz","h1":"Cómo Convertir EPUB a Audiolibro (Gratis & Online)"},
        "de": {"title":"EPUB in Hörbuch umwandeln — Kostenlose Anleitung | Audiobook Maker","desc":"Schritt-für-Schritt-Anleitung: EPUB eBooks kostenlos in MP3 oder M4B Hörbücher umwandeln. Erfahren Sie, wie Sie die besten TTS-Stimmen wählen und professionelle Hörbücher erstellen.","kw":"epub in hörbuch umwandeln, epub zu mp3, epub zu m4b, epub hörbuch konverter kostenlos, hörbuch aus epub erstellen, epub text to speech deutsch","h1":"EPUB in Hörbuch umwandeln (Kostenlos & Online)"},
        "zh": {"title":"如何免费将EPUB转换为有声书 — 完整指南 | Audiobook Maker","desc":"逐步指南：免费将EPUB电子书转换为MP3或M4B有声书。了解如何选择最佳TTS语音，保留章节，从任何EPUB文件创建专业有声书。无需安装软件。","kw":"epub转有声书, epub转mp3, epub转m4b, 免费epub有声书转换器, 如何从epub创建有声书, epub文字转语音","h1":"如何免费将EPUB转换为有声书（在线工具）"},
    },
    "m4b-format": {
        "en": {"title":"M4B Format Guide: Create Audiobooks with Chapters | Audiobook Maker","desc":"Everything about the M4B audiobook format: what it is, how it differs from MP3, how to create M4B files with embedded chapters and cover art, and why M4B is the best format for audiobooks. Free M4B creator tool included.","kw":"m4b format, what is m4b, m4b vs mp3, create m4b with chapters, m4b creator, m4b converter, how to make m4b file, m4b audiobook format, m4b chapter markers, convert to m4b free","h1":"M4B Format: The Ultimate Guide to Audiobook Files with Chapters"},
        "it": {"title":"Guida Formato M4B: Crea Audiolibri con Capitoli | Audiobook Maker","desc":"Tutto sul formato audiolibro M4B: cos'è, differenze con MP3, come creare file M4B con capitoli e copertina incorporati, e perché M4B è il formato migliore per gli audiolibri.","kw":"formato m4b, cos'è m4b, m4b vs mp3, creare m4b con capitoli, creatore m4b, convertitore m4b, come creare file m4b, formato audiolibro m4b","h1":"Formato M4B: Guida Completa ai File Audiolibro con Capitoli"},
        "fr": {"title":"Guide Format M4B: Créer des Livres Audio avec Chapitres | Audiobook Maker","desc":"Tout sur le format livre audio M4B: définition, différences avec MP3, comment créer des fichiers M4B avec chapitres et couverture intégrés, et pourquoi le M4B est le meilleur format.","kw":"format m4b, qu'est-ce que m4b, m4b vs mp3, créer m4b avec chapitres, créateur m4b, convertisseur m4b, format livre audio m4b","h1":"Format M4B: Guide Complet des Fichiers Livre Audio avec Chapitres"},
        "es": {"title":"Guía Formato M4B: Crea Audiolibros con Capítulos | Audiobook Maker","desc":"Todo sobre el formato audiolibro M4B: qué es, diferencias con MP3, cómo crear archivos M4B con capítulos y portada, y por qué M4B es el mejor formato para audiolibros.","kw":"formato m4b, qué es m4b, m4b vs mp3, crear m4b con capítulos, creador m4b, convertidor m4b, formato audiolibro m4b","h1":"Formato M4B: Guía Completa de Archivos Audiolibro con Capítulos"},
        "de": {"title":"M4B Format Guide: Hörbücher mit Kapiteln erstellen | Audiobook Maker","desc":"Alles über das M4B Hörbuchformat: Was es ist, Unterschiede zu MP3, wie man M4B-Dateien mit Kapiteln und Cover-Art erstellt, und warum M4B das beste Format für Hörbücher ist.","kw":"m4b format, was ist m4b, m4b vs mp3, m4b mit kapiteln erstellen, m4b creator, m4b konverter, hörbuchformat m4b","h1":"M4B Format: Der ultimative Guide für Hörbuchdateien mit Kapiteln"},
        "zh": {"title":"M4B格式指南：创建带章节的有声书 | Audiobook Maker","desc":"关于M4B有声书格式的一切：什么是M4B，与MP3的区别，如何创建带嵌入式章节和封面的M4B文件，以及为什么M4B是有声书的最佳格式。","kw":"m4b格式, 什么是m4b, m4b与mp3, 创建带章节的m4b, m4b制作工具, m4b转换器, m4b有声书格式","h1":"M4B格式：带章节有声书文件终极指南"},
    },
    "text-to-speech-audiobook": {
        "en": {"title":"Free Text to Speech Audiobook Maker — Best TTS Voices 2026 | Audiobook Maker","desc":"Create free audiobooks with natural AI text-to-speech voices. Compare the best TTS engines for audiobook creation (Edge TTS, Google TTS, Speechify alternatives). Convert text, EPUB and PDF to spoken audio online. No sign-up needed.","kw":"free text to speech audiobook, tts online free, ai voice audiobook maker, speechify alternative free, naturalreader alternative, best tts for audiobooks, text to speech mp3 download, ai narrator free, listen to books online, read aloud app, convert text to audio book","h1":"Free Text-to-Speech Audiobook Maker: Best TTS for 2026"},
        "it": {"title":"Text to Speech Audiolibri Gratis — Migliori Voci TTS 2026 | Audiobook Maker","desc":"Crea audiolibri gratis con voci AI text-to-speech naturali. Confronta i migliori motori TTS per creare audiolibri (Edge TTS, Google TTS, alternative a Speechify). Converti testo, EPUB e PDF in audio online.","kw":"text to speech audiolibri gratis, tts online gratis, creatore audiolibri con voce ai, alternativa a speechify gratis, alternativa naturalreader, miglior tts per audiolibri, text to speech mp3 download, narratore ai gratis","h1":"Text-to-Speech Audiolibri Gratis: Migliori Voci TTS 2026"},
        "fr": {"title":"Text to Speech Livre Audio Gratuit — Meilleures Voix TTS 2026 | Audiobook Maker","desc":"Créez des livres audio gratuits avec des voix IA text-to-speech naturelles. Comparez les meilleurs moteurs TTS pour la création de livres audio (Edge TTS, Google TTS, alternatives à Speechify).","kw":"text to speech livre audio gratuit, tts en ligne gratuit, créateur livre audio voix ia, alternative à speechify gratuit, meilleur tts pour livres audio, télécharger text to speech mp3","h1":"Text-to-Speech Livre Audio Gratuit: Meilleures Voix TTS 2026"},
        "es": {"title":"Text to Speech Audiolibros Gratis — Mejores Voces TTS 2026 | Audiobook Maker","desc":"Crea audiolibros gratis con voces AI text-to-speech naturales. Compara los mejores motores TTS para crear audiolibros (Edge TTS, Google TTS, alternativas a Speechify). Convierte texto, EPUB y PDF en audio online.","kw":"text to speech audiolibros gratis, tts en línea gratis, creador audiolibros voz ia, alternativa a speechify gratis, mejor tts para audiolibros, descargar text to speech mp3","h1":"Text-to-Speech Audiolibros Gratis: Mejores Voces TTS 2026"},
        "de": {"title":"Kostenloser Text-to-Speech Hörbuch Maker — Beste TTS 2026 | Audiobook Maker","desc":"Erstellen Sie kostenlose Hörbücher mit natürlichen KI-Text-to-Speech-Stimmen. Vergleichen Sie die besten TTS-Engines für Hörbücher (Edge TTS, Google TTS, Speechify-Alternativen). Text, EPUB und PDF online in Audio umwandeln.","kw":"kostenlos text to speech hörbuch, tts online kostenlos, ki hörbuch ersteller, speechify alternative kostenlos, bester tts für hörbücher, text to speech mp3 herunterladen","h1":"Kostenloser Text-to-Speech Hörbuch Maker: Beste TTS 2026"},
        "zh": {"title":"免费文字转语音有声书制作 — 最佳TTS语音 | Audiobook Maker","desc":"使用自然AI文字转语音免费创建有声书。比较最佳有声书TTS引擎（Edge TTS、Google TTS、Speechify替代品）。在线将文本、EPUB和PDF转换为语音。无需注册。","kw":"免费文字转语音有声书, 在线tts免费, ai语音有声书制作, speechify替代品, 最佳有声书tts, 文字转语音mp3下载, ai旁白免费","h1":"免费文字转语音有声书制作：最佳TTS引擎"},
    },
    "podcast": {
        "en": {"title":"How to Publish Your Audiobook as a Private Podcast — Free Guide | Audiobook Maker","desc":"Learn how to turn your M4B or MP3 audiobook chapters into a private podcast RSS feed. Free hosting with Netlify, step-by-step setup for Apple Podcasts, Pocket Casts, and more.","kw":"private podcast audiobook, podcast rss feed free, host audiobook as podcast, netlify podcast hosting, audiobook to podcast, free podcast hosting, apple podcasts private feed, personal podcast","h1":"How to Publish Your Audiobook as a Private Podcast (Free)"},
        "it": {"title":"Come Pubblicare il Tuo Audiolibro come Podcast Privato — Guida Gratis | Audiobook Maker","desc":"Scopri come trasformare i capitoli del tuo audiolibro M4B o MP3 in un feed podcast RSS privato. Hosting gratuito con Netlify, configurazione passo-passo per Apple Podcasts, Pocket Casts e altre app.","kw":"podcast privato audiolibro, feed rss podcast gratis, hosting podcast netlify, audiolibro come podcast, creare podcast da audiolibro, apple podcasts feed privato, ascoltare libro come podcast","h1":"Come Pubblicare il Tuo Audiolibro come Podcast Privato (Gratis)"},
        "fr": {"title":"Comment Publier Votre Livre Audio en Podcast Privé — Guide Gratuit | Audiobook Maker","desc":"Apprenez à transformer les chapitres de votre livre audio M4B ou MP3 en flux RSS podcast privé. Hébergement gratuit avec Netlify, configuration pas à pas pour Apple Podcasts, Pocket Casts et plus.","kw":"podcast privé livre audio, flux rss podcast gratuit, hébergement podcast netlify, livre audio en podcast, créer podcast depuis livre audio, apple podcasts flux privé","h1":"Comment Publier Votre Livre Audio en Podcast Privé (Gratuit)"},
        "es": {"title":"Cómo Publicar Tu Audiolibro como Podcast Privado — Guía Gratis | Audiobook Maker","desc":"Aprende a convertir los capítulos de tu audiolibro M4B o MP3 en un feed RSS de podcast privado. Hosting gratuito con Netlify, configuración paso a paso para Apple Podcasts, Pocket Casts y más.","kw":"podcast privado audiolibro, feed rss podcast gratis, hosting podcast netlify, audiolibro a podcast, crear podcast desde audiolibro, apple podcasts feed privado","h1":"Cómo Publicar Tu Audiolibro como Podcast Privado (Gratis)"},
        "de": {"title":"So veröffentlichen Sie Ihr Hörbuch als privaten Podcast — Kostenlose Anleitung | Audiobook Maker","desc":"Erfahren Sie, wie Sie Ihre Hörbuchkapitel (M4B oder MP3) in einen privaten Podcast-RSS-Feed verwandeln. Kostenloses Hosting mit Netlify, Schritt-für-Schritt für Apple Podcasts, Pocket Casts und mehr.","kw":"privater podcast hörbuch, rss feed podcast kostenlos, netlify podcast hosting, hörbuch als podcast, podcast aus hörbuch erstellen, apple podcasts privater feed","h1":"Hörbuch als privaten Podcast veröffentlichen (Kostenlos)"},
        "zh": {"title":"如何将有声书发布为私人播客 — 免费指南 | Audiobook Maker","desc":"了解如何将M4B或MP3有声书章节转换为私人播客RSS订阅源。通过Netlify免费托管，Apple Podcasts、Pocket Casts等应用的分步设置指南。","kw":"私人播客有声书, rss订阅源免费, netlify播客托管, 有声书转播客, 创建播客从有声书, apple podcasts私人订阅源","h1":"如何将有声书发布为私人播客（免费）"},
    },
}

'''

with open(DEST, 'a', encoding='utf-8') as f:
    f.write(META)

print("Meta written.")
