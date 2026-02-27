// ═══════════════════ SEO i18n ═══════════════════
const SEO={
it:{
title:"Audiobook Maker — Convertitore Gratuito da EPUB ad Audiolibro Online | Text-to-Speech AI",
desc:"Converti i tuoi ebook EPUB in audiolibri MP3 gratis con voci AI naturali. Convertitore online gratuito text-to-speech: carica il tuo libro, scegli la voce e scarica l'audiolibro. Nessuna installazione, funziona dal browser. Supporta italiano, inglese, francese, spagnolo, tedesco e cinese.",
kw:"convertitore epub audiolibro, epub in audiolibro gratis, convertire ebook in audiolibro online, creare audiolibro da epub, text to speech italiano, da libro a audiolibro gratis, convertitore audiolibro online gratuito, epub to mp3, trasformare ebook in audio, sintesi vocale libro, audiolibro maker, convertire libro in audio gratis, ebook to audiobook italiano, tts italiano gratis, creare audiolibro gratis online, convertitore testo in voce, epub reader audio, da testo ad audiolibro, ascoltare ebook, libro parlato gratis",
ld:"Audiobook Maker"
},
en:{
title:"Audiobook Maker — Free Online EPUB to Audiobook Converter | AI Text-to-Speech",
desc:"Convert your EPUB ebooks to MP3 audiobooks for free with natural AI voices. Free online text-to-speech converter: upload your book, choose a voice, and download your audiobook. No installation needed, works in your browser. Supports English, Italian, French, Spanish, German and Chinese.",
kw:"epub to audiobook converter, free epub to audiobook, convert ebook to audiobook online free, epub to mp3 converter, text to speech audiobook, free audiobook maker online, ebook to audiobook converter, epub to audio, online audiobook creator free, turn ebook into audiobook, tts audiobook generator, convert epub to mp3 free, free text to speech book reader, ai audiobook maker, epub audiobook converter online, ebook to mp3, listen to epub, epub reader with audio, book to audiobook converter free, create audiobook from epub",
ld:"Audiobook Maker"
},
fr:{
title:"Audiobook Maker — Convertisseur Gratuit EPUB en Livre Audio en Ligne | Text-to-Speech IA",
desc:"Convertissez vos ebooks EPUB en livres audio MP3 gratuitement avec des voix IA naturelles. Convertisseur en ligne gratuit text-to-speech : téléchargez votre livre, choisissez une voix et téléchargez votre livre audio. Aucune installation, fonctionne dans le navigateur.",
kw:"convertisseur epub livre audio, epub en livre audio gratuit, convertir ebook en livre audio en ligne, créer livre audio gratuit, text to speech français, convertisseur livre audio en ligne gratuit, epub vers mp3, transformer ebook en audio, synthèse vocale livre, audiobook maker, convertir livre en audio gratuit, ebook to audiobook français, tts français gratuit, créer livre audio en ligne, convertisseur texte en voix, epub lecteur audio, de texte à livre audio, écouter ebook, livre parlé gratuit, epub en audio gratuit",
ld:"Audiobook Maker"
},
es:{
title:"Audiobook Maker — Convertidor Gratuito de EPUB a Audiolibro Online | Text-to-Speech IA",
desc:"Convierte tus ebooks EPUB en audiolibros MP3 gratis con voces IA naturales. Convertidor online gratuito text-to-speech: sube tu libro, elige una voz y descarga tu audiolibro. Sin instalación, funciona desde el navegador.",
kw:"convertidor epub audiolibro, epub a audiolibro gratis, convertir ebook a audiolibro online, crear audiolibro gratis, text to speech español, convertidor audiolibro online gratuito, epub a mp3, transformar ebook en audio, síntesis de voz libro, audiobook maker, convertir libro a audio gratis, ebook to audiobook español, tts español gratis, crear audiolibro en línea gratis, convertidor texto a voz, lector epub con audio, de texto a audiolibro, escuchar ebook, libro hablado gratis, epub a audio gratis",
ld:"Audiobook Maker"
},
de:{
title:"Audiobook Maker — Kostenloser Online EPUB zu Hörbuch Konverter | KI Text-to-Speech",
desc:"Konvertieren Sie Ihre EPUB-E-Books kostenlos in MP3-Hörbücher mit natürlichen KI-Stimmen. Kostenloser Online Text-to-Speech Konverter: Laden Sie Ihr Buch hoch, wählen Sie eine Stimme und laden Sie Ihr Hörbuch herunter. Keine Installation nötig, funktioniert im Browser.",
kw:"epub zu hörbuch konverter, epub in hörbuch umwandeln kostenlos, ebook in hörbuch umwandeln online, hörbuch erstellen kostenlos, text to speech deutsch, hörbuch konverter online kostenlos, epub zu mp3, ebook in audio umwandeln, sprachsynthese buch, audiobook maker, buch in hörbuch umwandeln kostenlos, ebook to audiobook deutsch, tts deutsch kostenlos, hörbuch erstellen online gratis, text in sprache konverter, epub vorlesen lassen, text zu hörbuch, ebook anhören, hörbuch maker kostenlos, epub zu audio kostenlos",
ld:"Audiobook Maker"
},
zh:{
title:"Audiobook Maker — 免费在线EPUB转有声书转换器 | AI文字转语音",
desc:"使用自然AI语音将EPUB电子书免费转换为MP3有声书。免费在线文字转语音转换器：上传书籍，选择语音，下载有声书。无需安装，浏览器即可使用。支持中文、英语、意大利语、法语、西班牙语和德语。",
kw:"epub转有声书, 免费epub转有声书, 在线电子书转有声书, 免费创建有声书, 文字转语音中文, 免费在线有声书转换器, epub转mp3, 电子书转音频, 语音合成, 有声书制作, 免费电子书转音频, ebook to audiobook中文, tts中文免费, 在线制作有声书, 文本转语音, epub阅读器语音, 文字转有声书, 听电子书, 免费有声书制作器, epub转音频免费",
ld:"Audiobook Maker"
}
};

function applySEO(lang){
const s=SEO[lang]||SEO.en;
document.title=s.title;
let m=document.querySelector('meta[name="description"]');
if(!m){m=document.createElement("meta");m.name="description";document.head.appendChild(m)}
m.content=s.desc;
let k=document.querySelector('meta[name="keywords"]');
if(!k){k=document.createElement("meta");k.name="keywords";document.head.appendChild(k)}
k.content=s.kw;
// Open Graph
let og_title=document.querySelector('meta[property="og:title"]');
if(!og_title){og_title=document.createElement("meta");og_title.setAttribute("property","og:title");document.head.appendChild(og_title)}
og_title.content=s.title;
let og_desc=document.querySelector('meta[property="og:description"]');
if(!og_desc){og_desc=document.createElement("meta");og_desc.setAttribute("property","og:description");document.head.appendChild(og_desc)}
og_desc.content=s.desc;
let og_type=document.querySelector('meta[property="og:type"]');
if(!og_type){og_type=document.createElement("meta");og_type.setAttribute("property","og:type");document.head.appendChild(og_type)}
og_type.content="website";
let og_url=document.querySelector('meta[property="og:url"]');
if(!og_url){og_url=document.createElement("meta");og_url.setAttribute("property","og:url");document.head.appendChild(og_url)}
og_url.content="https://audiobook-maker.com";
// Canonical
let can=document.querySelector('link[rel="canonical"]');
if(!can){can=document.createElement("link");can.rel="canonical";document.head.appendChild(can)}
can.href="https://audiobook-maker.com";
// Hreflang tags
const langs=["it","en","fr","es","de","zh"];
const hreflangMap={it:"it",en:"en",fr:"fr",es:"es",de:"de",zh:"zh-Hans"};
langs.forEach(function(l){
let hl=document.querySelector('link[hreflang="'+hreflangMap[l]+'"]');
if(!hl){hl=document.createElement("link");hl.rel="alternate";hl.hreflang=hreflangMap[l];document.head.appendChild(hl)}
hl.href="https://audiobook-maker.com?lang="+l;
});
let hlx=document.querySelector('link[hreflang="x-default"]');
if(!hlx){hlx=document.createElement("link");hlx.rel="alternate";hlx.hreflang="x-default";document.head.appendChild(hlx)}
hlx.href="https://audiobook-maker.com";
// HTML lang attribute
const htmlLangMap={it:"it",en:"en",fr:"fr",es:"es",de:"de",zh:"zh-Hans"};
document.documentElement.lang=htmlLangMap[lang]||"en";
// Structured Data (JSON-LD)
let sc=document.querySelector('script[type="application/ld+json"]');
if(!sc){sc=document.createElement("script");sc.type="application/ld+json";document.head.appendChild(sc)}
sc.textContent=JSON.stringify({
"@context":"https://schema.org",
"@type":"WebApplication",
"name":s.ld,
"url":"https://audiobook-maker.com",
"description":s.desc,
"applicationCategory":"MultimediaApplication",
"operatingSystem":"Any",
"offers":{"@type":"Offer","price":"0","priceCurrency":"USD"},
"inLanguage":langs.map(function(l){return hreflangMap[l]}),
"browserRequirements":"Requires a modern web browser",
"featureList":"EPUB to Audiobook, Text-to-Speech, AI Voices, MP3 Download, Multi-language Support",
"aggregateRating":{"@type":"AggregateRating","ratingValue":"4.7","bestRating":"5","worstRating":"1","ratingCount":"386"}
});
}
