// ═══════════════════ SEO i18n ═══════════════════
const SEO={
it:{
  title:"Audiobook Maker — Convertitore EPUB in Audiolibro TTS",
  desc:"Strumento online gratuito per convertire ebook EPUB in audiolibri di alta qualità con voci neurali text-to-speech (TTS). Supporta più lingue, selezione capitoli e generazione feed podcast RSS. Ideale per ipovedenti e persone con difficoltà di lettura.",
  kw:"audiolibro, ebook, epub, tts, text to speech, da epub ad audiolibro, convertitore ebook, audiobook maker, tts ebook, voci neurali, audiolibro gratis, accessibilità, ipovedenti, dislessia, podcast, rss, sintesi vocale, libro parlato",
  ld:"Strumento online gratuito per convertire ebook EPUB in audiolibri di alta qualità con voci neurali text-to-speech (TTS)."},
en:{
  title:"Audiobook Maker — EPUB to Audiobook TTS Converter",
  desc:"Free online tool to convert EPUB ebooks into high-quality audiobooks using neural text-to-speech (TTS) voices. Supports multiple languages, chapter selection, and podcast RSS feed generation. Great for visually impaired readers and people with reading difficulties.",
  kw:"audiobook, ebook, epub, tts, text to speech, epub to audiobook, ebook converter, audiobook maker, tts ebook, neural voices, free audiobook, accessibility, visually impaired, dyslexia, podcast, rss",
  ld:"Free online tool to convert EPUB ebooks into high-quality audiobooks using neural text-to-speech (TTS) voices."},
fr:{
  title:"Audiobook Maker — Convertisseur EPUB en Livre Audio TTS",
  desc:"Outil en ligne gratuit pour convertir des ebooks EPUB en livres audio de haute qualité avec des voix neuronales text-to-speech (TTS). Prend en charge plusieurs langues, la sélection de chapitres et la génération de flux RSS podcast. Idéal pour les malvoyants et les personnes ayant des difficultés de lecture.",
  kw:"livre audio, ebook, epub, tts, text to speech, epub en livre audio, convertisseur ebook, audiobook maker, tts ebook, voix neuronales, livre audio gratuit, accessibilité, malvoyants, dyslexie, podcast, rss, synthèse vocale",
  ld:"Outil en ligne gratuit pour convertir des ebooks EPUB en livres audio de haute qualité avec des voix neuronales text-to-speech (TTS)."},
es:{
  title:"Audiobook Maker — Conversor EPUB a Audiolibro TTS",
  desc:"Herramienta online gratuita para convertir ebooks EPUB en audiolibros de alta calidad con voces neuronales text-to-speech (TTS). Soporta múltiples idiomas, selección de capítulos y generación de feed podcast RSS. Ideal para personas con discapacidad visual y dificultades de lectura.",
  kw:"audiolibro, ebook, epub, tts, text to speech, epub a audiolibro, conversor ebook, audiobook maker, tts ebook, voces neuronales, audiolibro gratis, accesibilidad, discapacidad visual, dislexia, podcast, rss, síntesis de voz",
  ld:"Herramienta online gratuita para convertir ebooks EPUB en audiolibros de alta calidad con voces neuronales text-to-speech (TTS)."},
de:{
  title:"Audiobook Maker — EPUB zu Hörbuch TTS-Konverter",
  desc:"Kostenloses Online-Tool zum Konvertieren von EPUB-E-Books in hochwertige Hörbücher mit neuronalen Text-to-Speech (TTS) Stimmen. Unterstützt mehrere Sprachen, Kapitelauswahl und Podcast-RSS-Feed-Generierung. Ideal für Sehbehinderte und Menschen mit Leseschwierigkeiten.",
  kw:"Hörbuch, E-Book, EPUB, TTS, Text-to-Speech, EPUB zu Hörbuch, E-Book-Konverter, Audiobook Maker, TTS E-Book, neuronale Stimmen, kostenloses Hörbuch, Barrierefreiheit, Sehbehinderung, Legasthenie, Podcast, RSS, Sprachsynthese",
  ld:"Kostenloses Online-Tool zum Konvertieren von EPUB-E-Books in hochwertige Hörbücher mit neuronalen Text-to-Speech (TTS) Stimmen."},
zh:{
  title:"Audiobook Maker — EPUB转有声读物 TTS转换器",
  desc:"免费在线工具，使用神经网络TTS语音将EPUB电子书转换为高质量有声读物。支持多语言、章节选择和播客RSS订阅源生成。适合视力障碍者和有阅读困难的人群。",
  kw:"有声读物, 电子书, EPUB, TTS, 文本转语音, EPUB转有声读物, 电子书转换, Audiobook Maker, TTS电子书, 神经语音, 免费有声读物, 无障碍, 视力障碍, 读写困难, 播客, RSS",
  ld:"免费在线工具，使用神经网络TTS语音将EPUB电子书转换为高质量有声读物。"}
};
// applySEO è no-op al primo caricamento: il server ha già renderizzato
// tutti i meta tag correttamente. Si attiva solo quando l'utente cambia
// lingua manualmente via UI, aggiornando i meta in-place senza reload.
let _seoInitDone = false;
function applySEO(){
  if(!_seoInitDone){ _seoInitDone=true; return; }
  const s=SEO[cl]||SEO.en;
  document.title=s.title;
  // html[lang] viene aggiornato da applyI18n() — non serve ridefinirlo qui
  document.getElementById('metaDesc').setAttribute('content',s.desc);
  document.getElementById('metaKw').setAttribute('content',s.kw);
  document.getElementById('ogTitle').setAttribute('content',s.title);
  document.getElementById('ogDesc').setAttribute('content',s.desc);
  const ogUrl=document.getElementById('ogUrl');
  if(ogUrl)ogUrl.setAttribute('content',location.href);
  document.getElementById('twTitle').setAttribute('content',s.title);
  document.getElementById('twDesc').setAttribute('content',s.desc);
  try{
    const ld=JSON.parse(document.getElementById('jsonLd').textContent);
    ld.name=s.title.split('—')[0].trim();
    ld.description=s.ld;
    document.getElementById('jsonLd').textContent=JSON.stringify(ld);
  }catch(e){}
}

