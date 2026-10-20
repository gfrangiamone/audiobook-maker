// ═══════════════════ PODCAST GUIDE ═══════════════════
const PG_IMG_A='/static/img/podcast_guide_download.png?v=__APP_VERSION__';
const PG_IMG_B='/static/img/podcast_guide_email.png?v=__APP_VERSION__';
const PG={
it:{
 intro:'Audiobook Maker genera, oltre ai file audio, un <b>pacchetto podcast completo</b> con feed RSS 2.0. Per renderlo fruibile come podcast, i file vanno pubblicati su un server web accessibile da Internet. La soluzione ideale è un <b>proprio sito web</b> o spazio hosting. In alternativa, per uso personale o per condividere con pochi amici, si può usare una soluzione gratuita come <b>Netlify</b>, descritta in questa guida.',
 scope:'👤 <b>Uso consigliato:</b> questa soluzione è pensata per uso personale o per condividere con amici e familiari. Netlify offre 100 GB/mese di banda gratuita — più che sufficienti.',
 sections:[
  {icon:'🎧',title:'1. Genera l’audiolibro per capitoli',body:'Nell’app, carica il file EPUB o PDF, scegli lingua e voce, poi seleziona <b>📁 Per capitoli</b> nella sezione Output. Questo è fondamentale: il podcast richiede un file MP3 per ogni episodio.'},
  {icon:'🌐',title:'2. Crea un account Netlify (gratuito)',body:'Vai su <b>app.netlify.com</b> e registrati con email o GitHub. Non serve carta di credito. Il piano gratuito include 100 GB di banda, 10 GB di storage e HTTPS automatico.'},
  {icon:'📦',title:'3. Scarica il pacchetto podcast',body:'Prima di scaricare, dovrai inserire l’<b>URL Netlify</b> dove pubblicherai i file (es. <code>https://mio-libro.netlify.app/</code>). Questo URL viene incorporato nel feed RSS affinché le app podcast possano trovare gli episodi. Ci sono due modi per ottenere il pacchetto:<br><br><b>Opzione A — Attendi nella pagina:</b> a generazione completata, clicca <b>🎙️ Scarica podcast</b>. Ti verrà chiesto l’URL, poi il ZIP verrà scaricato.<br><img src="__IMG_A__" alt="Interfaccia di download del podcast" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br><b>Opzione B — Notifica email:</b> per audiolibri lunghi, l’app offre di avvisarti via email. Nella finestra di notifica, seleziona <b>Podcast (con RSS)</b>, inserisci l’URL Netlify nel campo <b>URL base pubblicazione podcast</b>, poi la tua email. A generazione completata, riceverai un’email con il link per scaricare lo ZIP.<br><img src="__IMG_B__" alt="Configurazione notifica email per podcast" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br>Lo ZIP contiene: file MP3, feed RSS (XML), copertina e una pagina di presentazione (index.html).'},
  {icon:'📤',title:'4. Carica su Netlify (drag-and-drop)',body:'Nella dashboard Netlify, sezione <b>Sites</b>, trascina l’intera cartella estratta dal ZIP nella zona tratteggiata. In pochi secondi il sito sarà online. Poi rinominalo da <i>Site configuration → Change site name</i>.'},
  {icon:'✅',title:'5. Verifica',body:'Apri nel browser l’URL del feed:<br><code>https://nome-scelto.netlify.app/nome_podcast.xml</code><br>Se vedi il contenuto XML, il podcast è online e pronto!'},
 ],
 apps_title:'Importa nelle app podcast',
 apps:[
  {name:'Apple Podcasts',platform:'iOS / Mac',steps:'<b>iPhone:</b> Libreria → ⋮ → Aggiungi tramite URL → incolla URL del feed XML<br><b>Mac:</b> File → Segui uno show tramite URL'},
  {name:'Pocket Casts',platform:'Android / iOS / Web',steps:'Cerca → icona link (🔗) → incolla URL del feed → Iscriviti'},
  {name:'AntennaPod',platform:'Android',steps:'+ → Aggiungi feed RSS tramite URL → incolla URL'},
  {name:'Overcast',platform:'iOS',steps:'+ → Add URL → incolla URL del feed'},
  {name:'Podcast Addict',platform:'Android',steps:'+ → Feed RSS → incolla URL'},
 ],
 spotify_note:'⚠️ <b>Spotify</b> non supporta l’aggiunta di feed RSS privati. Usa una delle app sopra.',
 tips_title:'Consigli',
 tips:['<b>Condividi:</b> invia l’URL del feed XML ad amici — non serve che abbiano Netlify.','<b>Aggiorna:</b> ricarica i file su Netlify per sostituire la versione precedente.','<b>Più libri:</b> crea un sito Netlify diverso per ogni audiolibro.','<b>Limiti:</b> 10 GB di storage (~12 audiolibri). Rimuovi quelli già ascoltati per fare spazio.'],
 benefits_title:'Perché ascoltare come podcast?',
 benefits:['Segnaposto automatico — riprendi da dove avevi lasciato','Ordine episodi e passaggio automatico al successivo','Copertina, titoli e metadati visibili nell’app','Velocità regolabile (1.5×, 2×…) e timer spegnimento','Streaming senza scaricare tutti i file'],
},
en:{
 intro:'Audiobook Maker generates, alongside audio files, a <b>complete podcast package</b> with an RSS 2.0 feed. To make it available as a podcast, the files need to be published on a web server accessible from the Internet. The ideal solution is your <b>own website</b> or hosting space. Alternatively, for personal use or sharing with a few friends, you can use a free solution like <b>Netlify</b>, described in this guide.',
 scope:'👤 <b>Recommended use:</b> this solution is designed for personal use or sharing with friends and family. Netlify offers 100 GB/month of free bandwidth — more than enough.',
 sections:[
  {icon:'🎧',title:'1. Generate audiobook by chapters',body:'In the app, upload your EPUB or PDF file, choose language and voice, then select <b>📁 By chapters</b> in the Output section. This is essential: podcasts need one MP3 per episode.'},
  {icon:'🌐',title:'2. Create a free Netlify account',body:'Go to <b>app.netlify.com</b> and sign up with email or GitHub. No credit card needed. The free plan includes 100 GB bandwidth, 10 GB storage, and automatic HTTPS.'},
  {icon:'📦',title:'3. Download the podcast package',body:'Before downloading, you’ll need to enter the <b>Netlify URL</b> where you plan to publish the files (e.g. <code>https://my-book.netlify.app/</code>). This URL is embedded into the RSS feed so podcast apps can find your episodes. There are two ways to get the package:<br><br><b>Option A — Wait on the page:</b> once generation completes, click <b>🎙️ Download podcast</b>. You’ll be prompted for the URL, then the ZIP will download.<br><img src="__IMG_A__" alt="Podcast download interface in Audiobook Maker" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br><b>Option B — Email notification:</b> for long audiobooks, the app offers to notify you by email. In the notification dialog, select <b>Podcast (with RSS)</b>, enter the Netlify URL in the <b>Podcast base URL</b> field, then your email. When generation finishes, you’ll receive an email with a download link for the podcast ZIP.<br><img src="__IMG_B__" alt="Email notification setup for podcast generation" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br>The ZIP contains: MP3 files, RSS feed (XML), cover art, and a landing page (index.html).'},
  {icon:'📤',title:'4. Upload to Netlify (drag & drop)',body:'In the Netlify dashboard, under <b>Sites</b>, drag the entire extracted folder onto the dashed drop zone. The site goes live in seconds. Then rename it from <i>Site configuration → Change site name</i>.'},
  {icon:'✅',title:'5. Verify',body:'Open the feed URL in your browser:<br><code>https://your-name.netlify.app/book_podcast.xml</code><br>If you see XML content, your podcast is live!'},
 ],
 apps_title:'Import into podcast apps',
 apps:[
  {name:'Apple Podcasts',platform:'iOS / Mac',steps:'<b>iPhone:</b> Library → ⋮ → Add Show by URL → paste feed URL<br><b>Mac:</b> File → Follow a Show by URL'},
  {name:'Pocket Casts',platform:'Android / iOS / Web',steps:'Search → link icon (🔗) → paste feed URL → Subscribe'},
  {name:'AntennaPod',platform:'Android',steps:'+ → Add RSS feed by URL → paste URL'},
  {name:'Overcast',platform:'iOS',steps:'+ → Add URL → paste feed URL'},
  {name:'Podcast Addict',platform:'Android',steps:'+ → RSS Feed → paste URL'},
 ],
 spotify_note:'⚠️ <b>Spotify</b> does not support adding private RSS feeds. Use one of the apps above.',
 tips_title:'Tips',
 tips:['<b>Share:</b> send the feed XML URL to friends — they don’t need a Netlify account.','<b>Update:</b> re-upload files to Netlify to replace the previous version.','<b>Multiple books:</b> create a separate Netlify site for each audiobook.','<b>Limits:</b> 10 GB storage (~12 audiobooks). Remove finished ones to free up space.'],
 benefits_title:'Why listen as a podcast?',
 benefits:['Auto bookmarks — resume where you left off','Episode ordering and auto-advance','Cover art, titles, and metadata in your app','Adjustable speed (1.5×, 2×…) and sleep timer','Streaming without downloading all files'],
},
fr:{
 intro:'Audiobook Maker génère, en plus des fichiers audio, un <b>package podcast complet</b> avec flux RSS 2.0. Pour le rendre accessible en podcast, les fichiers doivent être publiés sur un serveur web. La solution idéale est votre <b>propre site web</b> ou espace d’hébergement. En alternative, pour un usage personnel ou le partage avec quelques amis, vous pouvez utiliser une solution gratuite comme <b>Netlify</b>, décrite dans ce guide.',
 scope:'👤 <b>Usage recommandé :</b> cette solution est conçue pour un usage personnel ou le partage avec des proches. Netlify offre 100 Go/mois de bande passante gratuite.',
 sections:[
  {icon:'🎧',title:'1. Générez le livre audio par chapitres',body:'Chargez votre fichier EPUB ou PDF, choisissez la langue et la voix, puis sélectionnez <b>📁 Par chapitres</b>. Le podcast nécessite un fichier MP3 par épisode.'},
  {icon:'🌐',title:'2. Créez un compte Netlify gratuit',body:'Rendez-vous sur <b>app.netlify.com</b>. Inscription par email ou GitHub, sans carte bancaire. Plan gratuit : 100 Go de bande passante, 10 Go de stockage, HTTPS automatique.'},
  {icon:'📦',title:'3. Téléchargez le package podcast',body:'Avant de télécharger, vous devrez saisir l’<b>URL Netlify</b> où vous publierez les fichiers (ex: <code>https://mon-livre.netlify.app/</code>). Cette URL est intégrée dans le flux RSS pour que les apps podcast trouvent vos épisodes. Deux options pour obtenir le package :<br><br><b>Option A — Restez sur la page :</b> une fois la génération terminée, cliquez sur <b>🎙️ Télécharger podcast</b>. L’URL vous sera demandée, puis le ZIP sera téléchargé.<br><img src="__IMG_A__" alt="Interface de téléchargement du podcast dans Audiobook Maker" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br><b>Option B — Notification par email :</b> pour les longs livres audio, l’app propose de vous notifier par email. Dans la fenêtre, sélectionnez <b>Podcast (avec RSS)</b>, entrez l’URL Netlify dans le champ <b>URL de base du podcast</b>, puis votre email. À la fin, vous recevrez un email avec le lien de téléchargement.<br><img src="__IMG_B__" alt="Configuration de la notification e-mail pour le podcast" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br>Le ZIP contient : fichiers MP3, flux RSS (XML), couverture et page d’accueil (index.html).'},
  {icon:'📤',title:'4. Publiez sur Netlify (glisser-déposer)',body:'Dans le tableau de bord Netlify, section <b>Sites</b>, glissez le dossier extrait dans la zone en pointillés. Le site est en ligne en quelques secondes. Renommez-le ensuite.'},
  {icon:'✅',title:'5. Vérifiez',body:'Ouvrez l’URL du flux dans votre navigateur :<br><code>https://nom-choisi.netlify.app/nom_podcast.xml</code><br>Si vous voyez du XML, le podcast est en ligne !'},
 ],
 apps_title:'Importer dans les apps podcast',
 apps:[
  {name:'Apple Podcasts',platform:'iOS / Mac',steps:'<b>iPhone :</b> Bibliothèque → ⋮ → Ajouter via URL<br><b>Mac :</b> Fichier → Suivre une émission via URL'},
  {name:'Pocket Casts',platform:'Android / iOS / Web',steps:'Rechercher → icône lien (🔗) → coller l’URL → S’abonner'},
  {name:'AntennaPod',platform:'Android',steps:'+ → Ajouter un flux RSS par URL → coller l’URL'},
  {name:'Overcast',platform:'iOS',steps:'+ → Add URL → coller l’URL du flux'},
  {name:'Podcast Addict',platform:'Android',steps:'+ → Flux RSS → coller l’URL'},
 ],
 spotify_note:'⚠️ <b>Spotify</b> ne permet pas d’ajouter des flux RSS privés. Utilisez une app ci-dessus.',
 tips_title:'Conseils',
 tips:['<b>Partager :</b> envoyez l’URL du flux à vos proches.','<b>Mettre à jour :</b> rechargez les fichiers sur Netlify.','<b>Plusieurs livres :</b> créez un site par livre audio.','<b>Limites :</b> 10 Go de stockage (~12 livres audio).'],
 benefits_title:'Écouter en podcast : les avantages',
 benefits:['Signet automatique — reprenez où vous en étiez','Ordre des épisodes et passage automatique','Couverture et métadonnées dans l’app','Vitesse réglable et minuterie de sommeil','Streaming sans télécharger tous les fichiers'],
},
es:{
 intro:'Audiobook Maker genera, además de los archivos de audio, un <b>paquete podcast completo</b> con feed RSS 2.0. Para hacerlo accesible como podcast, los archivos deben publicarse en un servidor web. La solución ideal es tu <b>propio sitio web</b> o espacio de hosting. Como alternativa, para uso personal o para compartir con unos pocos amigos, puedes usar una solución gratuita como <b>Netlify</b>, descrita en esta guía.',
 scope:'👤 <b>Uso recomendado:</b> esta solución está pensada para uso personal o para compartir con amigos y familiares. Netlify ofrece 100 GB/mes de ancho de banda gratuito.',
 sections:[
  {icon:'🎧',title:'1. Genera el audiolibro por capítulos',body:'Sube tu archivo EPUB o PDF, elige idioma y voz, y selecciona <b>📁 Por capítulos</b>. El podcast necesita un archivo MP3 por episodio.'},
  {icon:'🌐',title:'2. Crea una cuenta gratuita en Netlify',body:'Ve a <b>app.netlify.com</b> y regístrate con email o GitHub. Sin tarjeta de crédito. Plan gratuito: 100 GB de ancho de banda, 10 GB de almacenamiento, HTTPS automático.'},
  {icon:'📦',title:'3. Descarga el paquete podcast',body:'Antes de descargar, deberás introducir la <b>URL de Netlify</b> donde publicarás los archivos (ej: <code>https://mi-libro.netlify.app/</code>). Esta URL se incorpora al feed RSS para que las apps de podcast encuentren tus episodios. Hay dos formas de obtener el paquete:<br><br><b>Opción A — Espera en la página:</b> cuando termine la generación, haz clic en <b>🎙️ Descargar podcast</b>. Se te pedirá la URL y luego se descargará el ZIP.<br><img src="__IMG_A__" alt="Interfaz de descarga del podcast en Audiobook Maker" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br><b>Opción B — Notificación por email:</b> para audiolibros largos, la app ofrece avisarte por email. En el diálogo de notificación, selecciona <b>Podcast (con RSS)</b>, introduce la URL de Netlify en el campo <b>URL base del podcast</b> y tu email. Al completarse, recibirás un email con el enlace de descarga.<br><img src="__IMG_B__" alt="Configuración de notificación por correo para el podcast" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br>El ZIP contiene: archivos MP3, feed RSS (XML), portada y página de presentación (index.html).'},
  {icon:'📤',title:'4. Sube a Netlify (arrastrar y soltar)',body:'En el panel de Netlify, sección <b>Sites</b>, arrastra la carpeta extraída a la zona punteada. El sitio estará en línea en segundos. Luego renombra desde <i>Site configuration → Change site name</i>.'},
  {icon:'✅',title:'5. Verifica',body:'Abre la URL del feed en tu navegador:<br><code>https://nombre-elegido.netlify.app/nombre_podcast.xml</code><br>¡Si ves contenido XML, el podcast está en línea!'},
 ],
 apps_title:'Importar en apps de podcast',
 apps:[
  {name:'Apple Podcasts',platform:'iOS / Mac',steps:'<b>iPhone:</b> Biblioteca → ⋮ → Añadir por URL<br><b>Mac:</b> Archivo → Seguir programa por URL'},
  {name:'Pocket Casts',platform:'Android / iOS / Web',steps:'Buscar → icono enlace (🔗) → pegar URL → Suscribirse'},
  {name:'AntennaPod',platform:'Android',steps:'+ → Añadir feed RSS por URL → pegar URL'},
  {name:'Overcast',platform:'iOS',steps:'+ → Add URL → pegar URL del feed'},
  {name:'Podcast Addict',platform:'Android',steps:'+ → Feed RSS → pegar URL'},
 ],
 spotify_note:'⚠️ <b>Spotify</b> no permite añadir feeds RSS privados. Usa una de las apps anteriores.',
 tips_title:'Consejos',
 tips:['<b>Comparte:</b> envía la URL del feed a tus amigos.','<b>Actualiza:</b> vuelve a subir los archivos a Netlify.','<b>Más libros:</b> crea un sitio Netlify por cada audiolibro.','<b>Límites:</b> 10 GB de almacenamiento (~12 audiolibros).'],
 benefits_title:'¿Por qué escuchar como podcast?',
 benefits:['Marcador automático — retoma donde lo dejaste','Orden de episodios y avance automático','Portada y metadatos visibles en la app','Velocidad ajustable y temporizador de sueño','Streaming sin descargar todos los archivos'],
},
de:{
 intro:'Audiobook Maker erzeugt neben den Audiodateien ein <b>komplettes Podcast-Paket</b> mit RSS 2.0-Feed. Um es als Podcast verfügbar zu machen, müssen die Dateien auf einem Webserver veröffentlicht werden. Die ideale Lösung ist eine <b>eigene Website</b> oder ein eigener Hosting-Bereich. Alternativ können Sie für den persönlichen Gebrauch oder zum Teilen mit wenigen Freunden eine kostenlose Lösung wie <b>Netlify</b> verwenden, die in dieser Anleitung beschrieben wird.',
 scope:'👤 <b>Empfohlene Nutzung:</b> Diese Lösung ist für den persönlichen Gebrauch oder zum Teilen mit Freunden und Familie gedacht. Netlify bietet 100 GB/Monat kostenlose Bandbreite.',
 sections:[
  {icon:'🎧',title:'1. Hörbuch nach Kapiteln generieren',body:'Laden Sie Ihre EPUB- oder PDF-Datei hoch, wählen Sie Sprache und Stimme, dann <b>📁 Nach Kapiteln</b> bei der Ausgabe. Podcasts benötigen eine MP3 pro Episode.'},
  {icon:'🌐',title:'2. Kostenloses Netlify-Konto erstellen',body:'Gehen Sie zu <b>app.netlify.com</b> und registrieren Sie sich. Keine Kreditkarte nötig. Kostenlos: 100 GB Bandbreite, 10 GB Speicher, automatisches HTTPS.'},
  {icon:'📦',title:'3. Podcast-Paket herunterladen',body:'Vor dem Download müssen Sie die <b>Netlify-URL</b> eingeben, unter der die Dateien veröffentlicht werden (z.B. <code>https://mein-buch.netlify.app/</code>). Diese URL wird in den RSS-Feed eingebettet, damit Podcast-Apps Ihre Episoden finden. Es gibt zwei Wege:<br><br><b>Option A — Auf der Seite warten:</b> nach Abschluss der Generierung klicken Sie auf <b>🎙️ Podcast herunterladen</b>. Sie werden nach der URL gefragt, dann wird das ZIP heruntergeladen.<br><img src="__IMG_A__" alt="Podcast-Download-Oberfläche in Audiobook Maker" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br><b>Option B — E-Mail-Benachrichtigung:</b> bei langen Hörbüchern bietet die App eine E-Mail-Benachrichtigung an. Wählen Sie <b>Podcast (mit RSS)</b>, geben Sie die Netlify-URL im Feld <b>Podcast-Basis-URL</b> ein und Ihre E-Mail. Nach Abschluss erhalten Sie eine E-Mail mit dem Download-Link.<br><img src="__IMG_B__" alt="E-Mail-Benachrichtigungseinrichtung für die Podcast-Generierung" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br>Das ZIP enthält: MP3-Dateien, RSS-Feed (XML), Cover und eine Startseite (index.html).'},
  {icon:'📤',title:'4. Auf Netlify hochladen (Drag & Drop)',body:'Im Netlify-Dashboard unter <b>Sites</b> den extrahierten Ordner in die gestrichelte Zone ziehen. Die Seite ist in Sekunden online. Dann unter <i>Site configuration → Change site name</i> umbenennen.'},
  {icon:'✅',title:'5. Überprüfen',body:'Öffnen Sie die Feed-URL im Browser:<br><code>https://name.netlify.app/buch_podcast.xml</code><br>Wenn Sie XML-Inhalt sehen, ist der Podcast online!'},
 ],
 apps_title:'In Podcast-Apps importieren',
 apps:[
  {name:'Apple Podcasts',platform:'iOS / Mac',steps:'<b>iPhone:</b> Mediathek → ⋮ → Über URL hinzufügen<br><b>Mac:</b> Ablage → Show per URL folgen'},
  {name:'Pocket Casts',platform:'Android / iOS / Web',steps:'Suche → Link-Symbol (🔗) → URL einfügen → Abonnieren'},
  {name:'AntennaPod',platform:'Android',steps:'+ → RSS-Feed per URL hinzufügen → URL einfügen'},
  {name:'Overcast',platform:'iOS',steps:'+ → Add URL → Feed-URL einfügen'},
  {name:'Podcast Addict',platform:'Android',steps:'+ → RSS-Feed → URL einfügen'},
 ],
 spotify_note:'⚠️ <b>Spotify</b> unterstützt keine privaten RSS-Feeds. Nutzen Sie eine der oben genannten Apps.',
 tips_title:'Tipps',
 tips:['<b>Teilen:</b> Senden Sie die Feed-URL an Freunde.','<b>Aktualisieren:</b> Laden Sie neue Dateien auf Netlify hoch.','<b>Mehrere Bücher:</b> Erstellen Sie eine separate Netlify-Site pro Hörbuch.','<b>Limits:</b> 10 GB Speicher (~12 Hörbücher).'],
 benefits_title:'Warum als Podcast hören?',
 benefits:['Automatisches Lesezeichen — dort weitermachen, wo Sie aufgehört haben','Episodenreihenfolge und automatischer Wechsel','Cover und Metadaten in der App sichtbar','Einstellbare Geschwindigkeit und Schlaf-Timer','Streaming ohne alle Dateien herunterzuladen'],
},
zh:{
 intro:'Audiobook Maker 除了生成音频文件外，还会生成一个包含RSS 2.0订阅源的<b>完整播客包</b>。要将其作为播客发布，需要将文件放在可访问的网络服务器上。理想的方案是使用<b>自己的网站</b>或托管空间。作为替代，如果仅供个人使用或与少数朋友分享，可以使用本指南介绍的免费方案<b>Netlify</b>。',
 scope:'👤 <b>建议用途：</b>此方案适合个人使用或与亲友分享。Netlify每月提供100 GB免费流量。',
 sections:[
  {icon:'🎧',title:'1. 按章节生成有声读物',body:'上传EPUB或PDF文件，选择语言和语音，然后在输出部分选择<b>📁 按章节</b>。播客需要每集一个MP3文件。'},
  {icon:'🌐',title:'2. 创建Nelify免费账户',body:'访问<b>app.netlify.com</b>，用邮箱或GitHub注册。无需信用卡。免费计划：100 GB流量、10 GB存储、自动HTTPS。'},
  {icon:'📦',title:'3. 下载播客包',body:'下载前需要输入您计划发布文件的<b>Netlify URL</b>（如 <code>https://my-book.netlify.app/</code>）。该URL会嵌入RSS订阅源，以便播客应用找到您的剧集。有两种获取方式：<br><br><b>方式A — 在页面等待：</b>生成完成后，点击<b>🎙️ 下载播客</b>。系统会要求您输入URL，然后ZIP将开始下载。<br><img src="__IMG_A__" alt="Audiobook Maker 中的播客下载界面" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br><b>方式B — 邮件通知：</b>对于较长的有声读物，应用提供邮件通知功能。在通知对话框中，选择<b>播客（含RSS）</b>，在<b>播客发布基础URL</b>字段中输入Netlify URL，然后输入邮箱。生成完成后，您将收到包含下载链接的邮件。<br><img src="__IMG_B__" alt="播客生成的电子邮件通知设置" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br>ZIP包含：MP3文件、RSS订阅源（XML）、封面和落地页（index.html）。'},
  {icon:'📤',title:'4. 上传到Netlify（拖放）',body:'在Netlify控制台的<b>Sites</b>部分，将解压的文件夹拖到虚线区域。网站即刻上线。然后在 <i>Site configuration → Change site name</i> 重命名。'},
  {icon:'✅',title:'5. 验证',body:'在浏览器中打开订阅源URL：<br><code>https://your-name.netlify.app/book_podcast.xml</code><br>如果看到XML内容，播客已上线！'},
 ],
 apps_title:'导入播客应用',
 apps:[
  {name:'Apple Podcasts',platform:'iOS / Mac',steps:'<b>iPhone:</b> 资料库 → ⋮ → 通过URL添加<br><b>Mac:</b> 文件 → 通过URL关注节目'},
  {name:'Pocket Casts',platform:'Android / iOS / Web',steps:'搜索 → 链接图标 (🔗) → 粘贴URL → 订阅'},
  {name:'AntennaPod',platform:'Android',steps:'+ → 通过URL添加RSS订阅源 → 粘贴URL'},
  {name:'Overcast',platform:'iOS',steps:'+ → Add URL → 粘贴订阅源URL'},
  {name:'Podcast Addict',platform:'Android',steps:'+ → RSS Feed → 粘贴URL'},
 ],
 spotify_note:'⚠️ <b>Spotify</b> 不支持添加私有RSS订阅源。请使用以上应用。',
 tips_title:'小贴士',
 tips:['<b>分享：</b>将订阅源URL发送给朋友。','<b>更新：</b>重新上传文件到Netlify。','<b>多本书：</b>每本书创建一个Nelify网站。','<b>限制：</b>10 GB存储（约12本有声读物）。'],
 benefits_title:'为什么以播客形式收听？',
 benefits:['自动书签 — 从上次停下的地方继续','剧集顺序和自动播放下一集','应用中显示封面和元数据','可调速度和睡眠定时器','流式播放无需下载所有文件'],
},
hi:{
 intro:'Audiobook Maker, ऑडियो फ़ाइलों के अलावा, RSS 2.0 फ़ीड के साथ एक <b>संपूर्ण पॉडकास्ट पैकेज</b> भी जनरेट करता है. इसे पॉडकास्ट के रूप में प्रकाशित करने के लिए, फ़ाइलों को एक्सेस योग्य वेब सर्वर पर रखना आवश्यक है. आदर्श समाधान <b>अपनी वेबसाइट</b> या होस्टिंग स्थान का उपयोग करना है. वैकल्पिक रूप से, यदि केवल व्यक्तिगत उपयोग के लिए या कुछ दोस्तों के साथ साझा करने के लिए, आप इस गाइड में वर्णित मुफ़्त समाधान <b>Netlify</b> का उपयोग कर सकते हैं.',
 scope:'👤 <b>अनुशंसित उपयोग:</b> यह समाधान व्यक्तिगत उपयोग या परिवार और दोस्तों के साथ साझा करने के लिए उपयुक्त है. Netlify प्रति माह 100 GB मुफ़्त बैंडविड्थ प्रदान करता है.',
 sections:[
  {icon:'🎧',title:'1. अध्याय द्वारा ऑडियोबुक जनरेट करें',body:'EPUB या PDF फ़ाइल अपलोड करें, भाषा और आवाज़ चुनें, और आउटपुट अनुभाग में <b>📁 अध्याय द्वारा</b> चुनें. पॉडकास्ट के लिए प्रति एपिसोड एक MP3 फ़ाइल की आवश्यकता होती है.'},
  {icon:'🌐',title:'2. मुफ़्त Netlify खाता बनाएँ',body:'<b>app.netlify.com</b> पर जाएँ, ईमेल या GitHub के साथ साइन अप करें. क्रेडिट कार्ड की आवश्यकता नहीं. मुफ़्त योजना: 100 GB बैंडविड्थ, 10 GB संग्रहण, स्वचालित HTTPS.'},
  {icon:'📦',title:'3. पॉडकास्ट पैकेज डाउनलोड करें',body:'डाउनलोड से पहले आपको वह <b>Netlify URL</b> दर्ज करना होगा जहाँ आप फ़ाइलें प्रकाशित करने की योजना बना रहे हैं (उदाहरण के लिए <code>https://my-book.netlify.app/</code>). यह URL RSS फ़ीड में एम्बेड किया जाता है ताकि पॉडकास्ट ऐप्स आपके एपिसोड पा सकें. इसे प्राप्त करने के दो तरीके हैं:<br><br><b>तरीका A — पेज पर प्रतीक्षा करें:</b> जनरेशन पूरा होने के बाद, <b>🎙️ पॉडकास्ट डाउनलोड करें</b> पर क्लिक करें. सिस्टम आपसे URL दर्ज करने के लिए कहेगा, और फिर ZIP डाउनलोड होना शुरू हो जाएगा.<br><img src="__IMG_A__" alt="Audiobook Maker में पॉडकास्ट डाउनलोड इंटरफ़ेस" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br><b>तरीका B — ईमेल अधिसूचना:</b> लंबी ऑडियोबुक्स के लिए, ऐप ईमेल अधिसूचना सुविधा प्रदान करता है. अधिसूचना डायलॉग में, <b>पॉडकास्ट (RSS के साथ)</b> चुनें, <b>पॉडकास्ट प्रकाशन बेस URL</b> फ़ील्ड में Netlify URL दर्ज करें, और फिर अपना ईमेल दर्ज करें. जनरेशन पूरा होने के बाद, आपको डाउनलोड लिंक के साथ एक ईमेल प्राप्त होगा.<br><img src="__IMG_B__" alt="पॉडकास्ट जनरेशन के लिए ईमेल अधिसूचना सेटअप" style="max-width:100%;border-radius:8px;margin:10px 0;border:1px solid var(--brd);box-shadow:0 2px 8px rgba(0,0,0,.08)"><br>ZIP में शामिल हैं: MP3 फ़ाइलें, RSS फ़ीड (XML), कवर और लैंडिंग पेज (index.html).'},
  {icon:'📤',title:'4. Netlify पर अपलोड करें (ड्रैग-एंड-ड्रॉप)',body:'Netlify डैशबोर्ड के <b>Sites</b> अनुभाग में, अनज़िप किए गए फ़ोल्डर को धराशायी क्षेत्र पर खींचें. साइट तुरंत लाइव हो जाती है. फिर <i>Site configuration → Change site name</i> में नाम बदलें.'},
  {icon:'✅',title:'5. सत्यापित करें',body:'ब्राउज़र में फ़ीड URL खोलें:<br><code>https://your-name.netlify.app/book_podcast.xml</code><br>यदि आप XML सामग्री देखते हैं, तो पॉडकास्ट लाइव है!'},
 ],
 apps_title:'पॉडकास्ट ऐप्स में आयात करें',
 apps:[
  {name:'Apple Podcasts',platform:'iOS / Mac',steps:'<b>iPhone:</b> लाइब्रेरी → ⋮ → URL द्वारा जोड़ें<br><b>Mac:</b> फ़ाइल → URL द्वारा शो का अनुसरण करें'},
  {name:'Pocket Casts',platform:'Android / iOS / Web',steps:'खोजें → लिंक आइकन (🔗) → URL पेस्ट करें → सदस्यता लें'},
  {name:'AntennaPod',platform:'Android',steps:'+ → URL द्वारा RSS फ़ीड जोड़ें → URL पेस्ट करें'},
  {name:'Overcast',platform:'iOS',steps:'+ → Add URL → फ़ीड URL पेस्ट करें'},
  {name:'Podcast Addict',platform:'Android',steps:'+ → RSS Feed → URL पेस्ट करें'},
 ],
 spotify_note:'⚠️ <b>Spotify</b> निजी RSS फ़ीड जोड़ने का समर्थन नहीं करता है. कृपया उपरोक्त ऐप्स का उपयोग करें.',
 tips_title:'युक्तियाँ',
 tips:['<b>साझा करें:</b> फ़ीड URL दोस्तों को भेजें.','<b>अपडेट करें:</b> फ़ाइलों को Netlify पर फिर से अपलोड करें.','<b>कई किताबें:</b> प्रत्येक पुस्तक के लिए एक Netlify साइट बनाएँ.','<b>सीमा:</b> 10 GB संग्रहण (लगभग 12 ऑडियोबुक्स).'],
 benefits_title:'पॉडकास्ट के रूप में क्यों सुनें?',
 benefits:['स्वचालित बुकमार्क — जहाँ छोड़ा था वहीं से जारी रखें','एपिसोड क्रम और अगले एपिसोड का स्वचालित प्लेबैक','ऐप में कवर और मेटाडेटा प्रदर्शन','समायोज्य गति और स्लीप टाइमर','सभी फ़ाइलें डाउनलोड किए बिना स्ट्रीमिंग'],
}
};

function buildPodcastGuide(){
  const g=PG[cl]||PG.en;
  let h='<style>.pg-guide code{background:var(--srf2);color:var(--ac);padding:2px 6px;border-radius:4px;font-size:.85em;word-break:break-all}.pg-guide a{color:var(--ac)}.pg-guide i{color:inherit;opacity:.85}</style>';
  h+='<div class="pg-guide" style="font-size:.93rem;line-height:1.6;color:var(--tx)">';
  // Intro
  h+='<p style="margin:0 0 10px;color:var(--tx)">'+g.intro+'</p>';
  h+='<div style="background:#fff3cd;border-left:4px solid #f0c040;padding:10px 14px;border-radius:6px;margin:0 0 18px;font-size:.88rem;color:#5a4510">'+g.scope+'</div>';
  // Steps
  g.sections.forEach(sec=>{
    h+='<div style="display:flex;gap:12px;margin-bottom:14px;align-items:flex-start">';
    h+='<div style="font-size:1.4rem;line-height:1;flex-shrink:0;margin-top:2px">'+sec.icon+'</div>';
    h+='<div><div style="font-weight:700;margin-bottom:4px;color:var(--tx)">'+sec.title+'</div>';
    h+='<div style="color:var(--txd)">'+sec.body.replace(/__IMG_A__/g,PG_IMG_A).replace(/__IMG_B__/g,PG_IMG_B)+'</div></div></div>';
  });
  // Divider
  h+='<hr style="border:none;border-top:1px solid var(--brd);margin:20px 0">';
  // Apps
  h+='<h3 style="margin:0 0 12px;font-size:1.05rem;color:var(--tx)">📱 '+g.apps_title+'</h3>';
  h+='<table style="width:100%;border-collapse:collapse;font-size:.88rem;margin-bottom:10px;color:var(--tx)">';
  h+='<thead><tr style="background:var(--srf2)"><th style="padding:8px 10px;text-align:left;border-bottom:2px solid var(--brd)">App</th><th style="padding:8px 10px;text-align:left;border-bottom:2px solid var(--brd)">Platform</th><th style="padding:8px 10px;text-align:left;border-bottom:2px solid var(--brd)">Steps</th></tr></thead><tbody>';
  g.apps.forEach(a=>{
    h+='<tr><td style="padding:7px 10px;border-bottom:1px solid var(--brd);font-weight:600;white-space:nowrap">'+a.name+'</td>';
    h+='<td style="padding:7px 10px;border-bottom:1px solid var(--brd);color:var(--txd);font-size:.82rem;white-space:nowrap">'+a.platform+'</td>';
    h+='<td style="padding:7px 10px;border-bottom:1px solid var(--brd)">'+a.steps+'</td></tr>';
  });
  h+='</tbody></table>';
  h+='<div style="background:#fff0f0;border-left:4px solid #e04040;padding:8px 14px;border-radius:6px;margin:0 0 18px;font-size:.85rem;color:#802020">'+g.spotify_note+'</div>';
  // Benefits
  h+='<h3 style="margin:0 0 10px;font-size:1.05rem;color:var(--tx)">🎧 '+g.benefits_title+'</h3>';
  h+='<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px">';
  g.benefits.forEach(b=>{
    h+='<div style="background:var(--srf2);color:var(--tx);padding:6px 12px;border-radius:16px;font-size:.84rem">✓ '+b+'</div>';
  });
  h+='</div>';
  // Tips
  h+='<h3 style="margin:0 0 10px;font-size:1.05rem;color:var(--tx)">💡 '+g.tips_title+'</h3>';
  g.tips.forEach(tip=>{
    h+='<div style="padding:4px 0;font-size:.88rem;color:var(--tx)">• '+tip+'</div>';
  });
  h+='</div>';
  document.getElementById('pgBody').innerHTML=h;
}
function openPodcastGuide(){buildPodcastGuide();document.getElementById('pgModal').classList.add('open')}
function closePodcastGuide(){document.getElementById('pgModal').classList.remove('open')}

// ═══════════════════ ABOUT PROJECT ═══════════════════
const ABOUT={
it:{link:"Informazioni sul progetto",title:"Informazioni sul progetto",paras:[
"Il progetto Audiobook Maker nasce per rispondere ad un mio personale desiderio di poter ascoltare, sfruttando i miei spostamenti di lavoro, alcuni libri che non ho tempo di “leggere con gli occhi”.",
"Mi sono messo al lavoro dopo aver constatato che non esistono strumenti pronti e semplici per tradurre un libro in audio con lettori di buona qualità.",
"Successivamente, parlandone con amici, mi sono reso conto che uno strumento del genere potrebbe essere di aiuto ad altre persone come me e, soprattutto, alle tante persone che, per vari motivi (ipovedenti, dislessia,...), hanno difficoltà di lettura.",
"Ho pensato dunque di mettere a disposizione di tutti questo strumento gratuitamente.",
"Il progetto è open source (licenza AGPL-3.0) e il codice sorgente è disponibile su <a href='https://github.com/gfrangiamone/audiobook-maker' target='_blank' rel='noopener'>GitHub</a>. Puoi anche trovare Audiobook Maker su <a href='https://alternativeto.net/software/audiobook-maker/' target='_blank' rel='noopener'>AlternativeTo</a> a confronto con strumenti simili.",
"Provatelo, usatelo e per segnalazione di errori o per suggerimenti su nuove funzionalità, scrivetemi a:"]},
en:{link:"About this project",title:"About this project",paras:[
"The Audiobook Maker project was born from my personal desire to listen to some books I don’t have time to “read with my eyes”, taking advantage of my work commute.",
"I started working on it after realizing that there are no ready-made, simple tools to convert a book into audio with good quality readers.",
"Later, talking about it with friends, I realized that such a tool could help other people like me and, above all, the many people who, for various reasons (visually impaired, dyslexia,...), have reading difficulties.",
"So I decided to make this tool available to everyone for free.",
"The project is open source (AGPL-3.0 license) and the source code is available on <a href='https://github.com/gfrangiamone/audiobook-maker' target='_blank' rel='noopener'>GitHub</a>. You can also find Audiobook Maker on <a href='https://alternativeto.net/software/audiobook-maker/' target='_blank' rel='noopener'>AlternativeTo</a> compared with similar tools.",
"Try it, use it, and for bug reports or suggestions for new features, write to me at:"]},
fr:{link:"À propos du projet",title:"À propos du projet",paras:[
"Le projet Audiobook Maker est né de mon désir personnel de pouvoir écouter, en profitant de mes trajets professionnels, certains livres que je n’ai pas le temps de « lire avec les yeux ».",
"Je me suis mis au travail après avoir constaté qu’il n’existe pas d’outils simples et prêts à l’emploi pour convertir un livre en audio avec des lecteurs de bonne qualité.",
"Par la suite, en en parlant avec des amis, j’ai réalisé qu’un tel outil pourrait aider d’autres personnes comme moi et, surtout, les nombreuses personnes qui, pour diverses raisons (malvoyants, dyslexie,...), ont des difficultés de lecture.",
"J’ai donc décidé de mettre cet outil à la disposition de tous gratuitement.",
"Le projet est open source (licence AGPL-3.0) et le code source est disponible sur <a href=’https://github.com/gfrangiamone/audiobook-maker’ target=’_blank’ rel=’noopener’>GitHub</a>. Vous pouvez aussi trouver Audiobook Maker sur <a href=’https://alternativeto.net/software/audiobook-maker/’ target=’_blank’ rel=’noopener’>AlternativeTo</a> comparé avec des outils similaires.",
"Essayez-le, utilisez-le et pour signaler des erreurs ou suggérer de nouvelles fonctionnalités, écrivez-moi à :"]},
es:{link:"Sobre el proyecto",title:"Sobre el proyecto",paras:[
"El proyecto Audiobook Maker nace de mi deseo personal de poder escuchar, aprovechando mis desplazamientos de trabajo, algunos libros que no tengo tiempo de “leer con los ojos”.",
"Me puse a trabajar tras constatar que no existen herramientas listas y sencillas para convertir un libro en audio con lectores de buena calidad.",
"Posteriormente, hablando con amigos, me di cuenta de que una herramienta así podría ayudar a otras personas como yo y, sobre todo, a las muchas personas que, por diversos motivos (discapacidad visual, dislexia,...), tienen dificultades de lectura.",
"Así que decidí poner esta herramienta a disposición de todos de forma gratuita.",
"El proyecto es open source (licencia AGPL-3.0) y el código fuente está disponible en <a href='https://github.com/gfrangiamone/audiobook-maker' target='_blank' rel='noopener'>GitHub</a>. También puedes encontrar Audiobook Maker en <a href='https://alternativeto.net/software/audiobook-maker/' target='_blank' rel='noopener'>AlternativeTo</a> comparado con herramientas similares.",
"Pruébenlo, úsenlo y para reportar errores o sugerir nuevas funcionalidades, escríbanme a:"]},
de:{link:"Über das Projekt",title:"Über das Projekt",paras:[
"Das Projekt Audiobook Maker entstand aus meinem persönlichen Wunsch, einige Bücher, für die ich keine Zeit habe sie „mit den Augen zu lesen“, während meiner Arbeitswege hören zu können.",
"Ich machte mich an die Arbeit, nachdem ich festgestellt hatte, dass es keine fertigen und einfachen Tools gibt, um ein Buch mit guten Vorlesestimmen in Audio umzuwandeln.",
"Später, im Gespräch mit Freunden, wurde mir klar, dass ein solches Tool auch anderen Menschen wie mir helfen könnte und vor allem den vielen Menschen, die aus verschiedenen Gründen (Sehbehinderung, Legasthenie,...) Leseschwierigkeiten haben.",
"Deshalb habe ich beschlossen, dieses Tool allen kostenlos zur Verfügung zu stellen.",
"Das Projekt ist Open Source (AGPL-3.0-Lizenz) und der Quellcode ist auf <a href='https://github.com/gfrangiamone/audiobook-maker' target='_blank' rel='noopener'>GitHub</a> verfügbar. Sie finden Audiobook Maker auch auf <a href='https://alternativeto.net/software/audiobook-maker/' target='_blank' rel='noopener'>AlternativeTo</a> im Vergleich mit ähnlichen Tools.",
"Probieren Sie es aus, nutzen Sie es und schreiben Sie mir für Fehlermeldungen oder Vorschläge für neue Funktionen an:"]},
zh:{link:"关于本项目",title:"关于本项目",paras:[
"Audiobook Maker项目源于我个人的愿望：利用工作通勤时间，收听一些我没有时间“用眼睛阅读”的书籍。",
"在发现市面上没有现成的、简单的工具可以用高质量的语音将书籍转换为音频后，我开始着手开发。",
"后来，与朋友交流后，我意识到这样的工具不仅能帮助像我这样的人，更重要的是能帮助许多因各种原因（视力障碍、读写困难等）而有阅读困难的人。",
"因此我决定将这个工具免费提供给所有人。",
"本项目是开源的（AGPL-3.0许可证），源代码可在 <a href='https://github.com/gfrangiamone/audiobook-maker' target='_blank' rel='noopener'>GitHub</a> 上获取。您也可以在 <a href='https://alternativeto.net/software/audiobook-maker/' target='_blank' rel='noopener'>AlternativeTo</a> 上找到Audiobook Maker与类似工具的对比。",
"试试看，用起来，如果您有错误报告或新功能建议，请写信给我："]},
hi:{link:"परियोजना के बारे में",title:"परियोजना के बारे में",paras:[
"Audiobook Maker परियोजना मेरी व्यक्तिगत इच्छा से जन्मी, कि मैं अपने काम के आने-जाने के समय का लाभ उठाते हुए कुछ ऐसी पुस्तकों को सुन सकूँ जिन्हें मेरे पास \"आँखों से पढ़ने\" का समय नहीं है.",
"मैंने यह पाया कि अच्छी गुणवत्ता वाले रीडर्स के साथ किसी पुस्तक को ऑडियो में बदलने के लिए कोई तैयार और सरल उपकरण उपलब्ध नहीं हैं, इसके बाद मैंने काम शुरू किया.",
"बाद में, दोस्तों के साथ इस बारे में बात करते हुए, मुझे एहसास हुआ कि ऐसा उपकरण मेरे जैसे अन्य लोगों की मदद कर सकता है और सबसे महत्वपूर्ण रूप से, उन कई लोगों की मदद कर सकता है जो विभिन्न कारणों (दृष्टिबाधित, डिस्लेक्सिया,...) से पढ़ने में कठिनाई का सामना करते हैं.",
"इसलिए मैंने यह उपकरण सभी को मुफ़्त में उपलब्ध कराने का निर्णय लिया.",
"यह परियोजना ओपन सोर्स है (AGPL-3.0 लाइसेंस) और सोर्स कोड <a href='https://github.com/gfrangiamone/audiobook-maker' target='_blank' rel='noopener'>GitHub</a> पर उपलब्ध है. आप Audiobook Maker को <a href='https://alternativeto.net/software/audiobook-maker/' target='_blank' rel='noopener'>AlternativeTo</a> पर समान उपकरणों के साथ तुलना में भी पा सकते हैं.",
"इसे आज़माएँ, इसका उपयोग करें, और बग रिपोर्ट या नई सुविधाओं के सुझावों के लिए, मुझे यहाँ लिखें:"]}
};
function buildAbout(){
  const a=ABOUT[cl]||ABOUT.en;
  document.getElementById('aboutBtn').textContent=a.link;
  document.getElementById('aboutTitle').textContent=a.title;
  const b=document.getElementById('aboutBody');
  b.innerHTML=a.paras.map(p=>'<p class="about-text">'+p+'</p>').join('')
    +'<p class="about-contact">&#x2709;&#xFE0F; <a href="mailto:gfrangiamone@gmail.com">gfrangiamone@gmail.com</a> (Giuseppe Frangiamone)</p>'
    +'<p class="about-contact" style="margin-top:8px"><a href="https://github.com/gfrangiamone/audiobook-maker" target="_blank" rel="noopener">GitHub</a> &middot; <a href="https://alternativeto.net/software/audiobook-maker/" target="_blank" rel="noopener">AlternativeTo</a></p>';
}
function openAbout(){buildAbout();document.getElementById('aboutModal').classList.add('open')}

