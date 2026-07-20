# web_to_epub — da sito web a EPUB con capitoli e sottocapitoli

**Data:** 2026-07-20
**Stato:** design approvato
**Caso d'uso di riferimento:** `https://www.vatican.va/content/leo-xiv/it/encyclicals/documents/20260515-magnifica-humanitas.html`

## Obiettivo

Script da riga di comando che converte una pagina web (o un documento
distribuito su più pagine collegate) in un file `.epub` con TOC a **due
livelli**: capitoli e sottocapitoli, non oltre.

Deve funzionare sia su siti con heading semantici `h1/h2/h3`, sia su HTML
"sporco" privo di semantica (vatican.va usa `<p>` con `<b>` e maiuscolo),
sia su lingue e sistemi di scrittura diversi.

## Non-obiettivi

- Non è un crawler generico di siti: il crawl è limitato ai link interni
  del documento (vedi *Crawl*).
- Non preserva la formattazione ricca (tabelle, immagini inline, stili):
  l'output è testo strutturato in paragrafi.
- Non gestisce contenuti dietro autenticazione o paywall.
- Non produce più di due livelli di gerarchia.

## Collocazione dei file

Tutto in `scripts/`, directory **ignorata da git** (`.gitignore` riga 14):
i file restano locali, non versionati e non deployati.

```
scripts/web_to_epub.ps1              wrapper CLI PowerShell
scripts/web_to_epub.py               engine
scripts/test_web_to_epub.py          test pytest (fuori da test/, quindi fuori dalla CI)
scripts/fixtures_web_to_epub/        fixture HTML offline per i test
```

Conseguenza accettata: i test **non** girano nella CI di deploy
(`pytest test/`). Vanno eseguiti a mano:
`pytest scripts/test_web_to_epub.py -v`.

## Architettura

Il `.ps1` è un wrapper sottile: valida i parametri, individua l'interprete
Python, invoca l'engine, propaga l'exit code. Tutta la logica è nel `.py`.

### Riuso dal progetto

L'engine importa `translation_core` (modulo già standalone, non importa
`audiobook_app`, nessun rischio di re-import dell'entry point):

- `make_client_provider()`, `call_llm()`, `is_available()` — LLM opzionale
- `_safe_filename()` — normalizzazione nomi file

**Non** riusa `translation_core.write_epub()`: quella produce una TOC
piatta. Serve una `write_epub_nested()` locale, modellata su di essa, con
TOC a due livelli. La feature traduzione resta intatta.

Dipendenze: `requests`, `beautifulsoup4`, `ebooklib`, `openai` — tutte già
presenti in `requirements.txt`.

## Interfaccia CLI

| Parametro | Default | Descrizione |
|---|---|---|
| `-Url` | *(obbligatorio)* | URL della pagina di partenza |
| `-Out` | `<titolo>.epub` | percorso del file di output |
| `-FollowLinks` | `$false` | segue i link interni al documento |
| `-MaxPages` | `50` | limite hard sul numero di pagine scaricate |
| `-UseLLM` | `$false` | attiva l'assistenza LLM (outline + lingua) |
| `-Lang` | auto | override del codice lingua, salta il rilevamento |
| `-Title` | auto | override del titolo |
| `-Author` | auto | override dell'autore |
| `-Cover` | auto | percorso immagine di copertina |
| `-KeepNotes` | `$false` | conserva le note come capitolo finale |
| `-IgnoreRobots` | `$false` | ignora `robots.txt` (solo su siti propri) |
| `-DryRun` | `$false` | stampa l'outline rilevato, non scrive nulla |
| `-Verbose` | `$false` | dettaglio delle feature per ogni candidato-titolo |

## Pipeline

### 1. Fetch

`requests` con UA desktop identificativo, timeout 20s, 2 retry con backoff.
L'encoding è forzato da `apparent_encoding` quando il charset dichiarato è
incoerente con il contenuto (vatican.va dichiara charset errati).

### 2. De-boilerplate

Rimozione di `script`, `style`, `nav`, `header`, `footer`, `aside`, `form`.
Selezione del contenitore con maggiore densità di testo tra `main`,
`article`, `[role=main]`, `#content`, `.container`; fallback `body`.

### 3. Crawl (`-FollowLinks`)

Raccoglie gli `<a>` interni al contenitore che puntano:
- allo **stesso host**, e
- sotto la **stessa directory** dell'URL di partenza.

Esclude àncore `#`, varianti di lingua, duplicati. Visita BFS nell'ordine di
apparizione dei link, con pausa di 1s tra le pagine, fino a `-MaxPages`.
Il contenuto delle pagine viene concatenato in sequenza.

`robots.txt` è rispettato: le URL negate vengono saltate con avviso, salvo
`-IgnoreRobots`.

### 4. Flusso di blocchi

Il contenitore viene linearizzato in nodi ordinati `(tag, testo, features)`.
Feature calcolate per ogni nodo candidato a titolo:

- tag `h1`–`h6`
- testo interamente racchiuso in `<b>`/`<strong>`
- testo tutto maiuscolo
- lunghezza entro la soglia del profilo lingua
- assenza di punteggiatura finale
- match di numerazione (romana, araba, arabo-indiana, CJK)
- match del lessico titoli del profilo lingua
- `font-size` inline superiore al corpo
- allineamento centrato

### 5. Rilevamento lingua

Cascata, senza nuove dipendenze (il progetto non ha `langdetect`):

1. `<html lang>` / `og:locale` / `meta[http-equiv=content-language]`
2. **classe di script** dai blocchi Unicode del testo estratto: latino,
   cirillico, greco, CJK, arabo, ebraico, devanagari
3. **frequenza di stopword** su mini-tabella interna per le lingue a script
   latino (it/en/fr/es/de/pt/nl/pl), quando i metadati mancano o mentono
4. con `-UseLLM`, se i passi 1–3 restano incerti: ~500 caratteri all'LLM,
   risposta come codice BCP-47
5. `-Lang` salta l'intera cascata

### 6. Profili lingua

`LANG_PROFILES`, dizionario in cima al modulo, estendibile senza toccare la
logica:

| Feature | Adattamento |
|---|---|
| lessico titoli | `CAPITOLO/PARTE`, `CHAPTER/PART`, `CHAPITRE`, `KAPITEL`, `CAPÍTULO`, `ГЛАВА`, `第…章`, `الفصل`, `अध्याय` |
| maiuscolo | usato solo per script bicamerali; ignorato in CJK/arabo/ebraico/devanagari |
| lunghezza max titolo | 120 caratteri per latino/cirillico/greco, 40 per CJK |
| numerazione | romana, araba, arabo-indiana `٠-٩`, CJK `第一章` / `一、` |
| punteggiatura finale | `.` / `。` / `۔` / `।` secondo lo script |

**Profilo `generic`** (lingua non identificata): solo le feature indipendenti
dallo script — tag `h1-h3`, bold, lunghezza, assenza di punteggiatura finale,
numerazione. Degradazione controllata, mai errore fatale.

### 7. Outline

Due strade:

- **semantica** — se esistono almeno 2 heading `h1`–`h3`: il livello più alto
  presente diventa capitolo, il successivo sottocapitolo, gli `h3+` residui
  vengono degradati a corpo (limite di due livelli).
- **euristica** — punteggio sulle feature, pesato dal profilo lingua. Regola
  di calibrazione sui documenti tipo vatican.va: bold + maiuscolo + breve +
  senza punto finale = capitolo; bold in stile misto o corsivo =
  sottocapitolo.

### 8. LLM opzionale (`-UseLLM`)

Riceve **solo la lista compatta dei candidati**, mai il testo integrale:

```json
[{"i": 0, "text": "CAPITOLO 1", "tag": "p", "bold": true,
  "upper": true, "len": 10, "numbered": true}]
```

Risponde con `{i: livello}` dove livello è `1` (capitolo), `2`
(sottocapitolo), `0` (corpo). Batch da 200 candidati.

Su errore, timeout o LLM non configurato: fallback silenzioso
sull'euristica, nessuna interruzione.

### 9. Assemblaggio

- Il testo compreso tra due titoli è il corpo del nodo precedente.
- Il testo che precede il primo titolo diventa un capitolo `Introduzione`.
- Un sottocapitolo che precede qualsiasi capitolo viene promosso a capitolo.
- **Note**: marker `[n]` e blocco note finali vengono **rimossi** di default
  (l'EPUB è destinato plausibilmente al TTS, dove i marker sono rumore).
  Con `-KeepNotes` le note diventano un capitolo finale.

## Output EPUB

### Struttura

Un file `.xhtml` per nodo:

```
ch_001.xhtml       capitolo 1      <h1> + <p>...
ch_001_01.xhtml    sottocapitolo   <h2> + <p>...
ch_001_02.xhtml    sottocapitolo
ch_002.xhtml       capitolo 2
```

### TOC a due livelli

Costruita con `epub.Section`:

```
Capitolo 1 ─┬─ Sottocapitolo 1.1
            └─ Sottocapitolo 1.2
Capitolo 2
```

`spine = ['nav'] + tutti gli item in ordine di lettura`.
`EpubNcx` + `EpubNav` per compatibilità EPUB2/EPUB3.

### Metadati

| Campo | Cascata |
|---|---|
| title | `-Title` → `og:title` → `<h1>` → `<title>` ripulito dal suffisso del sito |
| author | `-Author` → `meta[name=author]` → `og:site_name` → host |
| language | esito del rilevamento lingua |
| identifier | `urn:uuid` derivato da hash dell'URL: rigenerare lo stesso sito produce lo stesso ID |
| DC:source | URL di partenza |

### Cover

`og:image` se presente e scaricabile; altrimenti nessuna cover. `-Cover`
sovrascrive.

### Compatibilità a valle

Ogni `.xhtml` diventa un capitolo per `parse_epub()` dell'app: capitoli e
sottocapitoli risultano voci distinte e navigabili anche in fase TTS.

## Errori

| Exit code | Caso | Comportamento |
|---|---|---|
| 0 | successo, anche con avvisi | EPUB scritto |
| 2 | rete: DNS/timeout/4xx/5xx dopo i retry | messaggio con URL e status, nessun file |
| 3 | contenuto vuoto dopo il de-boilerplate | suggerisce `-DryRun` per ispezione |
| 4 | scrittura EPUB fallita (I/O, permessi) | file parziale rimosso |

Degradazioni non fatali:

- nessun titolo rilevato → EPUB a capitolo unico, con avviso
- LLM non configurato o in errore → euristica
- cover non scaricabile → EPUB senza cover
- pagina del crawl irraggiungibile → saltata con avviso, le altre proseguono

## Logging

Progresso su stdout: `[1/12] fetch …`, `outline: 8 capitoli, 23 sottocapitoli`.

`-DryRun` stampa l'albero rilevato e la lingua senza scrivere il file.
`-Verbose` aggiunge il dettaglio delle feature per candidato, utile per
calibrare l'euristica su un sito nuovo.

## Test

`scripts/test_web_to_epub.py`, pytest, **interamente offline** su fixture
HTML in `scripts/fixtures_web_to_epub/`. Nessuna chiamata di rete né LLM:
il client è mockato.

1. outline semantico `h1/h2` → due livelli corretti
2. outline euristico stile vatican.va (bold + maiuscolo, zero heading semantici)
3. rilevamento lingua: `<html lang>` corretto; metadato mendace corretto
   dalle stopword; CJK riconosciuto dai blocchi Unicode
4. soglia di lunghezza titolo CJK (40) vs latino (120)
5. sottocapitolo orfano promosso a capitolo
6. rimozione dei marker `[n]` e del blocco note; `-KeepNotes` li conserva
7. filtro link del crawl: stessa directory, esclusione cambi lingua,
   dedupe, rispetto di `-MaxPages`
8. `write_epub_nested` → riletto con `ebooklib`: TOC annidata corretta,
   ordine dello spine corretto
9. fallback: zero titoli → capitolo unico, exit 0

## Addendum realizzativo (2026-07-21)

Implementazione completata. Quanto segue documenta le differenze fra questo
design e il codice finale: sono tutte reazioni a difetti emersi provando lo
strumento su documenti reali, non cambi di rotta.

### Requisito sopravvenuto: copertina da file locale

`-Cover` accetta **solo** `.jpg`, `.jpeg`, `.png`. Un'estensione diversa e un
errore esplicito, mai un'accettazione silenziosa: il design originale avrebbe
incorporato qualunque file dichiarandolo JPEG, producendo un EPUB malformato.
Nuovo exit code **5** (uso errato). La validazione e doppia, nel wrapper
PowerShell (prima di avviare Python) e nell'engine.

### Euristiche aggiunte

| Regola | Perche |
|---|---|
| Contenitori misti (`<div>testo<p>figlio</p></div>`) producono un blocco anche per il testo diretto | Il design scartava l'intero contenitore, perdendo il testo diretto: frequente fuori dai siti ben formati |
| `_is_navigation`: si scartano i blocchi il cui testo sta per l'80% in due o piu `<a>` e che non chiudono con punteggiatura | Gli indici interni al documento venivano scambiati per titoli. Le due guardie (due link, punteggiatura) evitano di cancellare prosa fatta di nomi linkati |
| Fusione dei titoli consecutivi dello stesso livello senza corpo in mezzo, massimo 3 righe | `CAPITOLO 1` e il nome del capitolo sono due righe dello stesso titolo; senza fusione il secondo apriva un capitolo vuoto che rubava i sottocapitoli. Il tetto di 3 righe impedisce di inghiottire un indice |
| Ramo semantico solo con >= 2 heading di testo distinto che introducono contenuto | Due `<h2>La Santa Sede</h2>` di template attivavano il ramo semantico e producevano un libro intitolato al sito |
| `_normalize_outline`: nei documenti sopra i 20k caratteri si potano i capitoli sotto i 200 caratteri, escluso l'introduttivo, dichiarando sempre cosa si scarta | Il sommario in cima al documento veniva preso per struttura. La soglia e **assoluta**: una soglia proporzionale al totale cancellerebbe capitoli brevi ma veri accanto a un capitolo dominante |
| Promozione dei sottocapitoli quando resta un solo capitolo | Un capitolo unico con N sottocapitoli e in realta un documento di N capitoli |

### Principio guida emerso

Perdere testo in silenzio e il modo peggiore di sbagliare per uno strumento
di conversione: un EPUB amputato ma dall'aspetto sano non da all'utente
alcun segnale. Ogni potatura, ogni troncamento del crawl e ogni pagina
saltata vengono percio dichiarati su stdout.

### Collocazione finale e test

`scripts/web_to_epub.py`, `scripts/web_to_epub.ps1`,
`scripts/test_web_to_epub.py`, `scripts/fixtures_web_to_epub/` — 86 test
offline. La directory `scripts/` e ignorata da git: i file restano locali e
non deployati, per scelta esplicita. I test non girano nella CI; si eseguono
con `pytest scripts/test_web_to_epub.py -v`.

### Difetto di produzione trovato per strada (non corretto)

Validando l'EPUB con `epub_to_tts.parse_epub()` e emerso un bug dell'app,
indipendente da questo strumento: `epub_to_tts.py` in `roman_to_readable`
usa `m.group(1)` (il prefisso) al posto di `m.group(2)` (il numero romano) e
li scambia; il match e inoltre case-insensitive, cosi una `i` minuscola
interna a una parola comune viene presa per numero romano. `"capitolo
intendo"` diventa `"i capitolontendo"`. Corrompe il testo TTS di qualunque
libro italiano contenente `"capitolo i..."` o `"parte i..."`.
