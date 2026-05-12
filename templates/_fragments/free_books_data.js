// ═══════════════════ FREE BOOKS SITES ═══════════════════
const FB_SITES=[
{id:"gutenberg",name:"Project Gutenberg",url:"https://www.gutenberg.org",icon:"📚",desc:{
it:"La più grande raccolta di ebook gratuiti al mondo. Oltre 70.000 libri con diritti d'autore scaduti, disponibili in EPUB, Kindle e testo. Classici della letteratura universale.",
en:"The world's largest free ebook collection. Over 70,000 public domain books in EPUB, Kindle, and plain text. Classics of world literature.",
fr:"La plus grande collection d'ebooks gratuits au monde. Plus de 70 000 livres du domaine public en EPUB, Kindle et texte. Classiques de la littérature mondiale.",
es:"La mayor colección de ebooks gratuitos del mundo. Más de 70.000 libros de dominio público en EPUB, Kindle y texto. Clásicos de la literatura universal.",
de:"Die größte Sammlung kostenloser E-Books weltweit. Über 70.000 gemeinfreie Bücher in EPUB, Kindle und Text. Klassiker der Weltliteratur.",
zh:"全球最大的免费电子书馆。超过70,000本公版书籍，提供EPUB、Kindle和纯文本格式。世界文学经典。",
hi:"दुनिया का सबसे बड़ा मुफ़्त ईबुक संग्रह. 70,000 से अधिक सार्वजनिक डोमेन पुस्तकें EPUB, Kindle और सादा पाठ प्रारूप में. विश्व साहित्य के क्लासिक्स."}},
{id:"standard",name:"Standard Ebooks",url:"https://standardebooks.org",icon:"⭐",desc:{
it:"Edizioni curate e ben formattate di classici del pubblico dominio. EPUB di altissima qualità con copertine originali, tipografia moderna e metadati accurati.",
en:"Carefully curated, beautifully formatted editions of public domain classics. High-quality EPUBs with original covers, modern typography, and accurate metadata.",
fr:"Éditions soignées et magnifiquement formatées de classiques du domaine public. EPUB de haute qualité avec couvertures originales et typographie moderne.",
es:"Ediciones cuidadas y bellamente formateadas de clásicos de dominio público. EPUB de alta calidad con portadas originales y tipografía moderna.",
de:"Sorgfältig kuratierte, schön formatierte Ausgaben gemeinfreier Klassiker. Hochwertige EPUBs mit Originalcovern und moderner Typografie.",
zh:"精心编辑、美观排版的公版经典作品。高质量EPUB，带原创封面和现代排版。",
hi:"सार्वजनिक डोमेन क्लासिक्स के सावधानीपूर्वक संपादित और सुंदर ढंग से स्वरूपित संस्करण. मूल कवर, आधुनिक टाइपोग्राफी और सटीक मेटाडेटा वाले उच्च-गुणवत्ता EPUB."}},
{id:"archive",name:"Internet Archive",url:"https://archive.org/details/texts",icon:"🏦",desc:{
it:"Biblioteca digitale immensa con milioni di testi, libri, audiolibri e riviste. Include il servizio di prestito digitale Open Library e collezioni storiche uniche.",
en:"Massive digital library with millions of texts, books, audiobooks, and magazines. Includes the Open Library digital lending service and unique historical collections.",
fr:"Immense bibliothèque numérique avec des millions de textes, livres et magazines. Inclut le service de prêt numérique Open Library et des collections historiques.",
es:"Enorme biblioteca digital con millones de textos, libros y revistas. Incluye el servicio de préstamo digital Open Library y colecciones históricas únicas.",
de:"Riesige digitale Bibliothek mit Millionen von Texten, Büchern und Zeitschriften. Enthält den digitalen Ausleihdienst Open Library und historische Sammlungen.",
zh:"海量数字图书馆，拥有数百万册书籍、音频和杂志。包含Open Library数字借阅服务和独特的历史藏品。",
hi:"लाखों पाठ, पुस्तकें, ऑडियोबुक्स और पत्रिकाओं के साथ विशाल डिजिटल पुस्तकालय. Open Library डिजिटल उधार सेवा और अनूठे ऐतिहासिक संग्रह शामिल हैं."}},
{id:"manybooks",name:"ManyBooks",url:"https://manybooks.net",icon:"📖",desc:{
it:"Oltre 50.000 ebook gratuiti in vari formati. Interfaccia moderna con categorie, recensioni e consigli di lettura. Ottima selezione di classici e opere indipendenti.",
en:"Over 50,000 free ebooks in various formats. Modern interface with categories, reviews, and reading recommendations. Great selection of classics and indie works.",
fr:"Plus de 50 000 ebooks gratuits en divers formats. Interface moderne avec catégories, critiques et recommandations. Excellente sélection de classiques.",
es:"Más de 50.000 ebooks gratuitos en varios formatos. Interfaz moderna con categorías, reseñas y recomendaciones. Gran selección de clásicos e independientes.",
de:"Über 50.000 kostenlose E-Books in verschiedenen Formaten. Moderne Oberfläche mit Kategorien, Rezensionen und Leseempfehlungen. Klassiker und Indie-Werke.",
zh:"超过50,000本免费电子书，多种格式。现代界面，带分类、评论和阅读推荐。",
hi:"विभिन्न प्रारूपों में 50,000 से अधिक मुफ़्त ईबुक्स. श्रेणियों, समीक्षाओं और पठन अनुशंसाओं के साथ आधुनिक इंटरफ़ेस. क्लासिक्स और इंडी कार्यों का बेहतरीन चयन."}},
{id:"feedbooks",name:"Feedbooks",url:"https://www.feedbooks.com/publicdomain",icon:"🌐",desc:{
it:"Catalogo elegante di ebook del pubblico dominio con download diretto in EPUB. Sezione dedicata alla narrativa, alla saggistica e ai classici, con interfaccia pulita e veloce.",
en:"Elegant catalog of public domain ebooks with direct EPUB download. Dedicated sections for fiction, non-fiction, and classics, with a clean and fast interface.",
fr:"Catalogue élégant d'ebooks du domaine public avec téléchargement EPUB direct. Sections fiction, non-fiction et classiques, interface rapide.",
es:"Catálogo elegante de ebooks de dominio público con descarga directa en EPUB. Secciones de ficción, no ficción y clásicos, interfaz limpia.",
de:"Eleganter Katalog gemeinfreier E-Books mit direktem EPUB-Download. Bereiche für Belletristik, Sachbücher und Klassiker, schnelle Oberfläche.",
zh:"精美的公版电子书目录，支持直接下载EPUB。分为小说、非虚构和经典三个板块。",
hi:"सार्वजनिक डोमेन ईबुक्स का सुरुचिपूर्ण कैटलॉग सीधे EPUB डाउनलोड के साथ. कथा, गैर-कथा और क्लासिक्स के लिए समर्पित खंड, साफ़ और तेज़ इंटरफ़ेस के साथ."}},
{id:"google",name:"Google Books",url:"https://books.google.com/books?&as_ebook=on&as_brr=1",icon:"G",desc:{
it:"Milioni di libri digitalizzati da Google. Filtra per 'Ebook gratuiti' per trovare opere con diritti scaduti. Disponibili in EPUB e PDF per il download diretto.",
en:"Millions of books digitized by Google. Filter by 'Free Google eBooks' to find public domain works. Available in EPUB and PDF for direct download.",
fr:"Des millions de livres numérisés par Google. Filtrez par 'Ebooks gratuits' pour le domaine public. Disponibles en EPUB et PDF.",
es:"Millones de libros digitalizados por Google. Filtra por 'Ebooks gratuitos' para encontrar obras de dominio público. Disponibles en EPUB y PDF.",
de:"Millionen von Google digitalisierte Bücher. Nach 'Kostenlose E-Books' filtern für gemeinfreie Werke. Verfügbar als EPUB und PDF.",
zh:"谷歌数字化的数百万册书籍。筛选\u201c免费电子书\u201d查找公版作品。支持EPUB和PDF下载。",
hi:"गूगल द्वारा डिजिटाइज़ की गई लाखों पुस्तकें. सार्वजनिक डोमेन कार्यों को खोजने के लिए 'मुफ़्त Google ईबुक्स' द्वारा फ़िल्टर करें. सीधे डाउनलोड के लिए EPUB और PDF में उपलब्ध."}},
{id:"liberliber",name:"Liber Liber / Manuzio",url:"https://www.liberliber.it/online/opere/libri/",icon:"🇮🇹",desc:{
it:"Il progetto italiano più importante per la diffusione di ebook gratuiti. Ampia raccolta di classici della letteratura italiana: Dante, Manzoni, Pirandello, Verga e molti altri.",
en:"Italy's most important free ebook project. Extensive collection of Italian literature classics: Dante, Manzoni, Pirandello, Verga and many others.",
fr:"Le projet italien le plus important pour les ebooks gratuits. Vaste collection de classiques italiens: Dante, Manzoni, Pirandello, Verga et bien d'autres.",
es:"El proyecto italiano más importante de ebooks gratuitos. Amplia colección de clásicos italianos: Dante, Manzoni, Pirandello, Verga y muchos más.",
de:"Italiens wichtigstes Projekt für kostenlose E-Books. Umfangreiche Sammlung italienischer Klassiker: Dante, Manzoni, Pirandello, Verga und viele mehr.",
zh:"意大利最重要的免费电子书项目。丰富的意大利文学经典藏品：但丁、曼佐尼、皮兰德娄等。",
hi:"मुफ़्त ईबुक्स के प्रसार के लिए सबसे महत्वपूर्ण इतालवी परियोजना. इतालवी साहित्य के क्लासिक्स का विस्तृत संग्रह: डांटे, मांज़ोनी, पिरांडेलो, वेर्गा और कई अन्य."}},
{id:"openlibrary",name:"Open Library",url:"https://openlibrary.org/read",icon:"🏛️",desc:{
it:"Catalogo aperto con milioni di libri. Prestito digitale gratuito di ebook moderni e classici. Parte dell'Internet Archive, richiede registrazione gratuita per il prestito.",
en:"Open catalog with millions of books. Free digital lending of modern and classic ebooks. Part of Internet Archive, requires free registration for borrowing.",
fr:"Catalogue ouvert avec des millions de livres. Prêt numérique gratuit d'ebooks modernes et classiques. Inscription gratuite requise pour l'emprunt.",
es:"Catálogo abierto con millones de libros. Préstamo digital gratuito de ebooks modernos y clásicos. Requiere registro gratuito para el préstamo.",
de:"Offener Katalog mit Millionen Büchern. Kostenlose digitale Ausleihe moderner und klassischer E-Books. Kostenlose Registrierung für Ausleihe erforderlich.",
zh:"拥有数百万册书籍的开放目录。免费数字借阅现代和经典电子书。需免费注册。",
hi:"लाखों पुस्तकों के साथ खुला कैटलॉग. आधुनिक और क्लासिक ईबुक्स की मुफ़्त डिजिटल उधार सेवा. Internet Archive का हिस्सा, उधार लेने के लिए मुफ़्त पंजीकरण आवश्यक है."}}
];

function buildFreeBooks(){
  const body=document.getElementById('fbBody');
  body.innerHTML='';
  FB_SITES.forEach(s=>{
    const card=document.createElement('div');card.className='site-card';
    card.innerHTML='<div class="site-icon">'+s.icon+'</div>'
      +'<div class="site-info"><div class="site-name"><a href="'+s.url+'" target="_blank" rel="noopener">'+s.name+' ↗</a></div>'
      +'<div class="site-desc">'+(s.desc[cl]||s.desc.en)+'</div></div>';
    body.appendChild(card);
  });
}
function openFreeBooks(){buildFreeBooks();document.getElementById('fbModal').classList.add('open')}
function closeFreeBooks(){document.getElementById('fbModal').classList.remove('open')}
