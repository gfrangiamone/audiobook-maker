// ═══════════════════ FREE BOOKS SITES ═══════════════════
const FB_SITES=[
{id:"gutenberg",name:"Project Gutenberg",url:"https://www.gutenberg.org",icon:"\\ud83d\\udcda",desc:{
it:"La pi\\u00f9 grande raccolta di ebook gratuiti al mondo. Oltre 70.000 libri con diritti d'autore scaduti, disponibili in EPUB, Kindle e testo. Classici della letteratura universale.",
en:"The world's largest free ebook collection. Over 70,000 public domain books in EPUB, Kindle, and plain text. Classics of world literature.",
fr:"La plus grande collection d'ebooks gratuits au monde. Plus de 70 000 livres du domaine public en EPUB, Kindle et texte. Classiques de la litt\\u00e9rature mondiale.",
es:"La mayor colecci\\u00f3n de ebooks gratuitos del mundo. M\\u00e1s de 70.000 libros de dominio p\\u00fablico en EPUB, Kindle y texto. Cl\\u00e1sicos de la literatura universal.",
de:"Die gr\\u00f6\\u00dfte Sammlung kostenloser E-Books weltweit. \\u00dcber 70.000 gemeinfreie B\\u00fccher in EPUB, Kindle und Text. Klassiker der Weltliteratur.",
zh:"\\u5168\\u7403\\u6700\\u5927\\u7684\\u514d\\u8d39\\u7535\\u5b50\\u4e66\\u9986\\u3002\\u8d85\\u8fc770,000\\u672c\\u516c\\u7248\\u4e66\\u7c4d\\uff0c\\u63d0\\u4f9bEPUB\\u3001Kindle\\u548c\\u7eaf\\u6587\\u672c\\u683c\\u5f0f\\u3002\\u4e16\\u754c\\u6587\\u5b66\\u7ecf\\u5178\\u3002"}},
{id:"standard",name:"Standard Ebooks",url:"https://standardebooks.org",icon:"\\u2b50",desc:{
it:"Edizioni curate e ben formattate di classici del pubblico dominio. EPUB di altissima qualit\\u00e0 con copertine originali, tipografia moderna e metadati accurati.",
en:"Carefully curated, beautifully formatted editions of public domain classics. High-quality EPUBs with original covers, modern typography, and accurate metadata.",
fr:"\\u00c9ditions soign\\u00e9es et magnifiquement format\\u00e9es de classiques du domaine public. EPUB de haute qualit\\u00e9 avec couvertures originales et typographie moderne.",
es:"Ediciones cuidadas y bellamente formateadas de cl\\u00e1sicos de dominio p\\u00fablico. EPUB de alta calidad con portadas originales y tipograf\\u00eda moderna.",
de:"Sorgf\\u00e4ltig kuratierte, sch\\u00f6n formatierte Ausgaben gemeinfreier Klassiker. Hochwertige EPUBs mit Originalcovern und moderner Typografie.",
zh:"\\u7cbe\\u5fc3\\u7f16\\u8f91\\u3001\\u7f8e\\u89c2\\u6392\\u7248\\u7684\\u516c\\u7248\\u7ecf\\u5178\\u4f5c\\u54c1\\u3002\\u9ad8\\u8d28\\u91cfEPUB\\uff0c\\u5e26\\u539f\\u521b\\u5c01\\u9762\\u548c\\u73b0\\u4ee3\\u6392\\u7248\\u3002"}},
{id:"archive",name:"Internet Archive",url:"https://archive.org/details/texts",icon:"\\ud83c\\udfe6",desc:{
it:"Biblioteca digitale immensa con milioni di testi, libri, audiolibri e riviste. Include il servizio di prestito digitale Open Library e collezioni storiche uniche.",
en:"Massive digital library with millions of texts, books, audiobooks, and magazines. Includes the Open Library digital lending service and unique historical collections.",
fr:"Immense biblioth\\u00e8que num\\u00e9rique avec des millions de textes, livres et magazines. Inclut le service de pr\\u00eat num\\u00e9rique Open Library et des collections historiques.",
es:"Enorme biblioteca digital con millones de textos, libros y revistas. Incluye el servicio de pr\\u00e9stamo digital Open Library y colecciones hist\\u00f3ricas \\u00fanicas.",
de:"Riesige digitale Bibliothek mit Millionen von Texten, B\\u00fcchern und Zeitschriften. Enth\\u00e4lt den digitalen Ausleihdienst Open Library und historische Sammlungen.",
zh:"\\u6d77\\u91cf\\u6570\\u5b57\\u56fe\\u4e66\\u9986\\uff0c\\u62e5\\u6709\\u6570\\u767e\\u4e07\\u518c\\u4e66\\u7c4d\\u3001\\u97f3\\u9891\\u548c\\u6742\\u5fd7\\u3002\\u5305\\u542bOpen Library\\u6570\\u5b57\\u501f\\u9605\\u670d\\u52a1\\u548c\\u72ec\\u7279\\u7684\\u5386\\u53f2\\u85cf\\u54c1\\u3002"}},
{id:"manybooks",name:"ManyBooks",url:"https://manybooks.net",icon:"\\ud83d\\udcd6",desc:{
it:"Oltre 50.000 ebook gratuiti in vari formati. Interfaccia moderna con categorie, recensioni e consigli di lettura. Ottima selezione di classici e opere indipendenti.",
en:"Over 50,000 free ebooks in various formats. Modern interface with categories, reviews, and reading recommendations. Great selection of classics and indie works.",
fr:"Plus de 50 000 ebooks gratuits en divers formats. Interface moderne avec cat\\u00e9gories, critiques et recommandations. Excellente s\\u00e9lection de classiques.",
es:"M\\u00e1s de 50.000 ebooks gratuitos en varios formatos. Interfaz moderna con categor\\u00edas, rese\\u00f1as y recomendaciones. Gran selecci\\u00f3n de cl\\u00e1sicos e independientes.",
de:"\\u00dcber 50.000 kostenlose E-Books in verschiedenen Formaten. Moderne Oberfl\\u00e4che mit Kategorien, Rezensionen und Leseempfehlungen. Klassiker und Indie-Werke.",
zh:"\\u8d85\\u8fc750,000\\u672c\\u514d\\u8d39\\u7535\\u5b50\\u4e66\\uff0c\\u591a\\u79cd\\u683c\\u5f0f\\u3002\\u73b0\\u4ee3\\u754c\\u9762\\uff0c\\u5e26\\u5206\\u7c7b\\u3001\\u8bc4\\u8bba\\u548c\\u9605\\u8bfb\\u63a8\\u8350\\u3002"}},
{id:"feedbooks",name:"Feedbooks",url:"https://www.feedbooks.com/publicdomain",icon:"\\ud83c\\udf10",desc:{
it:"Catalogo elegante di ebook del pubblico dominio con download diretto in EPUB. Sezione dedicata alla narrativa, alla saggistica e ai classici, con interfaccia pulita e veloce.",
en:"Elegant catalog of public domain ebooks with direct EPUB download. Dedicated sections for fiction, non-fiction, and classics, with a clean and fast interface.",
fr:"Catalogue \\u00e9l\\u00e9gant d'ebooks du domaine public avec t\\u00e9l\\u00e9chargement EPUB direct. Sections fiction, non-fiction et classiques, interface rapide.",
es:"Cat\\u00e1logo elegante de ebooks de dominio p\\u00fablico con descarga directa en EPUB. Secciones de ficci\\u00f3n, no ficci\\u00f3n y cl\\u00e1sicos, interfaz limpia.",
de:"Eleganter Katalog gemeinfreier E-Books mit direktem EPUB-Download. Bereiche f\\u00fcr Belletristik, Sachb\\u00fccher und Klassiker, schnelle Oberfl\\u00e4che.",
zh:"\\u7cbe\\u7f8e\\u7684\\u516c\\u7248\\u7535\\u5b50\\u4e66\\u76ee\\u5f55\\uff0c\\u652f\\u6301\\u76f4\\u63a5\\u4e0b\\u8f7dEPUB\\u3002\\u5206\\u4e3a\\u5c0f\\u8bf4\\u3001\\u975e\\u865a\\u6784\\u548c\\u7ecf\\u5178\\u4e09\\u4e2a\\u677f\\u5757\\u3002"}},
{id:"google",name:"Google Books",url:"https://books.google.com/books?&as_ebook=on&as_brr=1",icon:"G",desc:{
it:"Milioni di libri digitalizzati da Google. Filtra per 'Ebook gratuiti' per trovare opere con diritti scaduti. Disponibili in EPUB e PDF per il download diretto.",
en:"Millions of books digitized by Google. Filter by 'Free Google eBooks' to find public domain works. Available in EPUB and PDF for direct download.",
fr:"Des millions de livres num\\u00e9ris\\u00e9s par Google. Filtrez par 'Ebooks gratuits' pour le domaine public. Disponibles en EPUB et PDF.",
es:"Millones de libros digitalizados por Google. Filtra por 'Ebooks gratuitos' para encontrar obras de dominio p\\u00fablico. Disponibles en EPUB y PDF.",
de:"Millionen von Google digitalisierte B\\u00fccher. Nach 'Kostenlose E-Books' filtern f\\u00fcr gemeinfreie Werke. Verf\\u00fcgbar als EPUB und PDF.",
zh:"\\u8c37\\u6b4c\\u6570\\u5b57\\u5316\\u7684\\u6570\\u767e\\u4e07\\u518c\\u4e66\\u7c4d\\u3002\\u7b5b\\u9009\\u201c\\u514d\\u8d39\\u7535\\u5b50\\u4e66\\u201d\\u67e5\\u627e\\u516c\\u7248\\u4f5c\\u54c1\\u3002\\u652f\\u6301EPUB\\u548cPDF\\u4e0b\\u8f7d\\u3002"}},
{id:"liberliber",name:"Liber Liber / Manuzio",url:"https://www.liberliber.it/online/opere/libri/",icon:"\\ud83c\\uddee\\ud83c\\uddf9",desc:{
it:"Il progetto italiano pi\\u00f9 importante per la diffusione di ebook gratuiti. Ampia raccolta di classici della letteratura italiana: Dante, Manzoni, Pirandello, Verga e molti altri.",
en:"Italy's most important free ebook project. Extensive collection of Italian literature classics: Dante, Manzoni, Pirandello, Verga and many others.",
fr:"Le projet italien le plus important pour les ebooks gratuits. Vaste collection de classiques italiens: Dante, Manzoni, Pirandello, Verga et bien d'autres.",
es:"El proyecto italiano m\\u00e1s importante de ebooks gratuitos. Amplia colecci\\u00f3n de cl\\u00e1sicos italianos: Dante, Manzoni, Pirandello, Verga y muchos m\\u00e1s.",
de:"Italiens wichtigstes Projekt f\\u00fcr kostenlose E-Books. Umfangreiche Sammlung italienischer Klassiker: Dante, Manzoni, Pirandello, Verga und viele mehr.",
zh:"\\u610f\\u5927\\u5229\\u6700\\u91cd\\u8981\\u7684\\u514d\\u8d39\\u7535\\u5b50\\u4e66\\u9879\\u76ee\\u3002\\u4e30\\u5bcc\\u7684\\u610f\\u5927\\u5229\\u6587\\u5b66\\u7ecf\\u5178\\u85cf\\u54c1\\uff1a\\u4f46\\u4e01\\u3001\\u66fc\\u4f50\\u5c3c\\u3001\\u76ae\\u5170\\u5fb7\\u5a04\\u7b49\\u3002"}},
{id:"openlibrary",name:"Open Library",url:"https://openlibrary.org/read",icon:"\\ud83c\\udfdb\\ufe0f",desc:{
it:"Catalogo aperto con milioni di libri. Prestito digitale gratuito di ebook moderni e classici. Parte dell'Internet Archive, richiede registrazione gratuita per il prestito.",
en:"Open catalog with millions of books. Free digital lending of modern and classic ebooks. Part of Internet Archive, requires free registration for borrowing.",
fr:"Catalogue ouvert avec des millions de livres. Pr\\u00eat num\\u00e9rique gratuit d'ebooks modernes et classiques. Inscription gratuite requise pour l'emprunt.",
es:"Cat\\u00e1logo abierto con millones de libros. Pr\\u00e9stamo digital gratuito de ebooks modernos y cl\\u00e1sicos. Requiere registro gratuito para el pr\\u00e9stamo.",
de:"Offener Katalog mit Millionen B\\u00fcchern. Kostenlose digitale Ausleihe moderner und klassischer E-Books. Kostenlose Registrierung f\\u00fcr Ausleihe erforderlich.",
zh:"\\u62e5\\u6709\\u6570\\u767e\\u4e07\\u518c\\u4e66\\u7c4d\\u7684\\u5f00\\u653e\\u76ee\\u5f55\\u3002\\u514d\\u8d39\\u6570\\u5b57\\u501f\\u9605\\u73b0\\u4ee3\\u548c\\u7ecf\\u5178\\u7535\\u5b50\\u4e66\\u3002\\u9700\\u514d\\u8d39\\u6ce8\\u518c\\u3002"}}
];

function buildFreeBooks(){
  const body=document.getElementById('fbBody');
  body.innerHTML='';
  FB_SITES.forEach(s=>{
    const card=document.createElement('div');card.className='site-card';
    card.innerHTML='<div class="site-icon">'+s.icon+'</div>'
      +'<div class="site-info"><div class="site-name"><a href="'+s.url+'" target="_blank" rel="noopener">'+s.name+' \\u2197</a></div>'
      +'<div class="site-desc">'+(s.desc[cl]||s.desc.en)+'</div></div>';
    body.appendChild(card);
  });
}
function openFreeBooks(){buildFreeBooks();document.getElementById('fbModal').classList.add('open')}
function closeFreeBooks(){document.getElementById('fbModal').classList.remove('open')}

