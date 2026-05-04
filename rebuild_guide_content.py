# This script rebuilds guide_content.py with all 6 language translations
# Run: python rebuild_guide_content.py

import os

BASE = r'C:\Users\gfran\NEXT srl\Progetti - Documenti\AudioBook-Maker'

# Read current file
with open(os.path.join(BASE, 'guide_content.py'), 'r', encoding='utf-8') as f:
    content = f.read()

# ── Extract EN body HTML for each guide ──
import re

# Find the _GUIDE_BODY_EN block boundaries
en_start = content.find('_GUIDE_BODY_EN = {')
en_end = content.find('\ndef _build_article_ld')

# Extract the inner dict content (without the outer braces)
en_block = content[en_start:en_end]
dict_start = en_block.find('{')
en_inner = en_block[dict_start+1:]
# Remove trailing newline and closing brace
en_inner = en_inner.rstrip()
if en_inner.endswith('}'):
    en_inner = en_inner[:-1]

# ── Build translated body HTML for each language ──

# ITALIANO
body_it = {}
body_it['epub-to-audiobook'] = """
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
"""

body_it['m4b-format'] = """
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
"""

body_it['text-to-speech-audiobook'] = """
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
"""

# Add more languages here...

print('IT body content ready')
print(f'epub-to-audiobook: {len(body_it["epub-to-audiobook"])} chars')
print(f'm4b-format: {len(body_it["m4b-format"])} chars')
print(f'text-to-speech-audiobook: {len(body_it["text-to-speech-audiobook"])} chars')
