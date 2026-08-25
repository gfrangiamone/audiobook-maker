# Banco di prova Gemini 3.1 Flash TTS su Cloudflare Workers AI

Data: 2026-08-25
Stato: design approvato, pronto per il piano di implementazione
Ambito: tooling locale (`scripts/`), nessuna modifica ai moduli dell'app

## 1. Problema

Cloudflare Workers AI espone `google/gemini-3.1-flash-tts` — lo stesso modello
usato oggi in produzione via Vertex — a tariffe più basse:

| Voce (per 1M token) | Google listino | Cloudflare | Δ |
|---|---|---|---|
| Input text | $1,00 | $0,75 | −25 % |
| Output audio | $20,00 | $12,00 | −40 % |

Sul TTS il costo è per oltre il 99 % output audio, quindi il risparmio teorico
è ~40 %. Ricalcolando i **148 job premium completati** fra il 25/07 e il
25/08/2026 (fonte: `gemini_cost_audit`, token reali `*_tokens_actual`, cambio
`ABM_GEMINI_USD_EUR_RATE=0.86`):

| | flash31 (127 job) | flash25 (21 job) |
|---|---|---|
| Token output | 28,03 M | 2,85 M |
| Ore audio | 308,5 h | 31,7 h |
| Costo @listino Google | € 486,05 | € 24,72 |
| Costo @Cloudflare | € 292,21 | € 29,72 |

Migrare il solo traffico flash31 varrebbe **−€ 194/mese (−39,9 %)**; flash25
resterebbe su Google, perché Cloudflare offre solo il 3.1 e a quelle tariffe i
job 2.5 costerebbero il 20 % in più.

Il risparmio è però **calcolato, non osservato**. Tre incognite lo rendono non
azionabile così com'è:

1. Cloudflare **non restituisce i token consumati** nella risposta. Il costo per
   chiamata non è leggibile: la tariffa reale va riconciliata a posteriori.
2. La risposta non ha `finish_reason` né metadati di completamento, quindi il
   presidio anti-troncamento oggi attivo in `gemini_tts` non ha equivalente. Il
   progetto ha già subito due incidenti di troncamento silenzioso consegnato
   all'utente (edge-tts, assembly PCM).
3. Il modello è marcato "third-party" da Cloudflare, senza SLA né quote
   pubblicate, a fronte di ~35.000 chiamate/mese di traffico attuale.

Serve un banco di prova che risponda a queste tre incognite prima di qualunque
decisione di migrazione.

## 2. Obiettivo

Un harness locale, parametrico ed eseguibile a costo controllato, che produca un
verdetto go/no-go documentato su quattro assi: **costo reale**, **robustezza**,
**throughput**, **parità di qualità**.

Criteri di go/no-go proposti (da confermare a valle del primo run completo):

| Asse | Soglia di GO |
|---|---|
| Costo | costo osservato entro il +10 % del costo stimato dal modello token; risparmio effettivo ≥ 30 % vs listino Google |
| Robustezza | zero chunk troncati/vuoti non rilevati; ogni anomalia rilevata deve essere corretta dal retry |
| Throughput | nessun 429 a concorrenza pari a quella di prod; p95 di latenza per chunk non oltre 1,5× Vertex |
| Qualità | parità di giudizio all'ascolto sull'A/B, nessuna deriva di voce fra chunk |

## 3. Vincoli accertati dell'API Cloudflare

Verificati su `developers.cloudflare.com/ai/models/google/gemini-3.1-flash-tts`:

- Endpoint: `POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run`,
  header `Authorization: Bearer {token}`.
- Input: `{"model": "google/gemini-3.1-flash-tts", "input": {"text", "voice",
  "temperature", "topP", "topK", "maxOutputTokens", "stopSequences"}}`.
- `text`: massimo 10.000 caratteri (prod usa chunk da 450, ampiamente sotto).
- `voice`: enum di 30 nomi, coincidente con il catalogo Gemini (Zephyr, Puck,
  Kore, Fenrir, …).
- Output: `{"audio": "<base64 WAV>", "gatewayMetadata": {...}}`. **Nessun campo
  di usage/token, nessun `finish_reason`.**
- Zero data retention dichiarata.
- Fatturazione: piano Workers Paid; i modelli partner sono fatturati a parte
  rispetto ai Neuron ($0,011/1000, 10.000/giorno gratuiti).

Conseguenze di design:

- Nessun parametro API per stile o velocità. Non è un problema: prod usa già
  `ABM_GEMINI_RATE_MODE=prompt`, cioè inietta stile, accento e velocità come
  blocco `[style: ...]` **dentro il testo** (`gemini_tts.build_final_text`). Il
  bench riusa quella funzione, quindi il prompt è byte-per-byte quello di prod.
- Output WAV invece di PCM raw: il bench deve rimuovere l'header WAV e
  verificare sample rate, canali e sample width reali prima di concatenare.

## 4. Architettura

### 4.1 File

```
scripts/tts_cloudflare_gemini_test.py   # bench standalone, unico modulo Python
scripts/cf_tts_bench.ps1                # wrapper PowerShell parametrico
scripts/cf_tts_bench.env.ps1            # credenziali locali (mai committato)
test/test_cf_tts_bench.py               # test del bench, HTTP mockata
```

`scripts/` è escluso in blocco da `.gitignore` (riga 14), ma 12 file al suo
interno sono tracciati con `git add -f`. Il bench rientra in questa eccezione,
a differenza degli altri banchi provider (`tts_speechify_test.py`,
`tts_qwen_test.py`, `tts_supertonic_test.py`) che restano locali: qui il gate
anti-troncamento è l'implementazione di riferimento di un controllo destinato
alla produzione, e ha un test tracciato in `test/` che senza il modulo non
avrebbe nulla da importare. `cf_tts_bench.env.ps1` resta invece non tracciato
in ogni caso.

### 4.2 Riuso

Il bench è autonomo e importa **solo helper puri**, nessun modulo di stato:

| Funzione | Modulo | Ruolo nel bench |
|---|---|---|
| `split_text_into_chunks(text, max_chars, max_bytes)` | `tts_split` (233) | chunking identico a prod |
| `build_final_text(text, style_instruction, rate, accent_directive)` | `gemini_tts` (2070) | prompt identico a prod |
| `build_accent_directive(language, accent_code)` | `gemini_tts` (589) | direttiva di accento |
| `baseline_rate(language)`, `LANG_BASELINE_RATE` | `gemini_tts` (60, 37) | durata attesa per il gate anti-troncamento |
| `pcm_size_to_seconds(byte_size, ...)` | `audio_utils` (1411) | durata reale dai byte PCM |
| `trim_pcm_trailing_silence(...)` | `audio_utils` (1422) | parità con il trim di prod |
| `pcm_concat(paths, out, gap_ms=...)` | `audio_utils` (1479) | giunzione chunk |
| `pcm_to_aac_m4b(paths, out, chapters=..., ...)` | `audio_utils` (1769) | M4B in una sola encode AAC |
| `synthesize(text, voice_id, ...)` | `gemini_tts` (2136) | **solo** per il ramo A/B su Vertex |

`audiobook_app`, `generation_engine`, i job e i database JSON non vengono mai
toccati né importati.

### 4.3 Non-obiettivi

- Nessuna modifica a `gemini_tts.py`. L'aggiunta di un backend `cloudflare` in
  `_resolve_backend()` è lavoro successivo, subordinato all'esito del test.
- Nessuna misura automatica della qualità percepita: l'A/B produce materiale per
  l'ascolto, non un punteggio.
- Nessuna integrazione con l'audit di prod (`gemini_cost_audit`): il bench
  scrive un proprio `metrics.jsonl` indipendente.

## 5. Parametrizzazione

### 5.1 Livelli (`-Level`)

| Livello | Contenuto | Costo indicativo |
|---|---|---|
| `smoke` | un chunk, una voce: auth, schema di risposta, decodifica WAV | trascurabile |
| `matrix` | prodotto cartesiano `Langs × Voices × Rates × Styles` su fixture corte | pochi € |
| `book` | libro reale end-to-end fino all'M4B, con gemello Vertex opzionale | 1–3 € per libro |

### 5.2 Parametri

| Parametro PS | Default | Note |
|---|---|---|
| `-Level` | `smoke` | `smoke` \| `matrix` \| `book` |
| `-Book` | — | `.abm`, `.txt` o `.epub`; obbligatorio con `-Level book` |
| `-Langs` | `it,en` | codici ISO a due lettere |
| `-Voices` | `Zephyr` | uno o più nomi dall'enum Cloudflare |
| `-Rates` | `+0%` | come il parametro `rate` di prod |
| `-Styles` | *(vuoto)* | istruzioni di stile, cap a 200 char come in prod |
| `-ChunkChars` | `450` | pari a `ABM_GEMINI_CHUNK_CHARS` di prod |
| `-Temperature` | `0.3` | pari a `ABM_GEMINI_TEMPERATURE` di prod |
| `-Concurrency` | `1` | chiamate parallele |
| `-Runs` | `1` | ripetizioni della stessa combinazione (varianza) |
| `-Compare` | *(vuoto)* | `vertex` attiva il ramo A/B |
| `-MaxSpendEur` | `2.00` | tetto di spesa stimata del run |
| `-OutDir` | `./out` | radice degli artefatti |

Il `.ps1` valida i parametri, carica l'env da `cf_tts_bench.env.ps1` se presente
e invoca lo script Python con gli argomenti corrispondenti. Nessuna logica di
misura vive in PowerShell.

## 6. Le quattro misure

### 6.1 Costo e riconciliazione

Poiché la risposta non espone i token, il bench li **stima** con lo stesso
modello di prod — `token_output = secondi_audio × 25`, `token_input =
caratteri / CHARS_PER_TOKEN_BY_LANG[lang]` — usando i secondi audio **reali**
ricavati dai byte PCM, non una previsione. Il costo stimato è quindi affetto da
un solo errore: il rapporto token/secondo dichiarato da Google, che sull'audit
di produzione risulta costantemente 25,0.

A fine run il bench emette un blocco di riconciliazione:

```
RICONCILIAZIONE — finestra UTC 2026-08-25T14:02:11Z → 2026-08-25T14:39:48Z
  richieste           1.284
  caratteri inviati   577.800
  secondi audio       41.554
  token input (stima)   144.450
  token output (stima)  1.038.850
  costo atteso        USD 12,58   EUR 10,82
```

Il confronto con il fatturato reale è tentato in automatico via GraphQL
Analytics; la documentazione non conferma un dataset che copra i modelli
partner, quindi il fallimento è previsto e non è un errore. In quel caso il
bench stampa la query pronta e le istruzioni per la lettura manuale dalla
dashboard, con la finestra temporale esatta da selezionare. La riconciliazione,
automatica o manuale, è ciò che valida o smonta il −40 %: senza di essa il run
è solo un test funzionale e il report lo dichiara esplicitamente.

### 6.2 Robustezza: troncamenti e risposte vuote

Per ogni chunk il bench calcola la durata attesa come
`len(testo) / baseline_rate(lang)` e la confronta con la durata reale del WAV.

| Condizione | Esito |
|---|---|
| `audio` assente o vuoto | anomalia `empty` |
| rapporto reale/atteso < 0,6 | anomalia `truncated` |
| rapporto reale/atteso > 1,6 | anomalia `overlong` |
| sample rate/canali/width ≠ attesi | anomalia `format` |

Ogni anomalia viene rigenerata una volta e il report registra se il retry ha
corretto. La banda 0,6–1,6 è deliberatamente più larga di quella dei rate
empirici di prod (`RATE_CLAMP_LOW/HIGH` = 0,75/1,35): qui serve a intercettare
troncamenti grossolani, non a calibrare un preventivo, e falsi positivi su testi
atipici renderebbero il gate inutilizzabile.

Il run esce con codice ≠ 0 se resta anche una sola anomalia non corretta dal
retry. È il presidio che sostituisce il `finish_reason` mancante e la ragione
per cui questo asse non è negoziabile: i due incidenti di troncamento già
occorsi sono arrivati fino all'utente proprio perché nessun controllo di durata
esisteva a valle della sintesi.

### 6.3 Throughput, rate limit, latenza

Per ogni chiamata il bench registra latenza, codice HTTP ed eventuale header di
retry. Il report aggrega p50/p95/p99, tasso di 429 e di 5xx per livello di
concorrenza, e proietta:

- tempo di generazione di un libro medio (chunk × latenza / concorrenza);
- sostenibilità del carico mensile attuale (~35.000 chiamate).

`-Concurrency` va fatto variare in run successivi per trovare il punto di
saturazione: il bench non lo cerca da solo.

### 6.4 A/B di qualità contro Vertex

Con `-Compare vertex` ogni chunk è generato su entrambi i backend a partire
dallo **stesso prompt esatto** prodotto da `build_final_text`. Il ramo Vertex
usa `gemini_tts.synthesize()` con le env di prod (`ABM_GEMINI_BACKEND=vertex`,
`ABM_GCP_PROJECT_ID`, `ABM_GOOGLE_CREDENTIALS_FILE`).

Output: coppie `NNN_cf.wav` / `NNN_vertex.wav` più due M4B affiancati. Il report
riporta per chunk durata, RMS e silenzio di coda dei due backend, utili a far
emergere deriva sistematica; il giudizio sulla resa resta l'ascolto umano.

Nota sulla riproducibilità: `temperature=0.3` non è determinismo. Due chiamate
identiche allo stesso backend differiscono, quindi differenze puntuali fra CF e
Vertex non sono di per sé un segnale. `-Runs > 1` serve a distinguere la
varianza intrinseca da una differenza sistematica fra i due backend.

## 7. Output

```
out/<run_id>/
  metrics.jsonl     una riga per chiamata
  report.md         riepilogo leggibile
  audio/            WAV per chunk, PCM intermedi, M4B finali
  prompts/          testo finale inviato, per ispezione
```

`run_id` = `<timestamp UTC>_<level>`. Schema di una riga di `metrics.jsonl`:

```json
{"ts","run_id","backend","lang","voice","rate","style_hash","chunk_index",
 "chars","prompt_bytes","http_status","latency_ms","attempt",
 "audio_bytes","audio_seconds","expected_seconds","ratio",
 "tokens_in_est","tokens_out_est","cost_usd_est","anomaly"}
```

Schema stabile: le analisi successive (confronto fra run, grafici) leggono
questo file e non il report.

## 8. Cap di spesa e sicurezza

Prima di ogni chiamata il bench somma il costo stimato del chunk al totale del
run; superato `-MaxSpendEur` interrompe, scrive comunque `report.md` con i dati
raccolti fino a quel punto e lo marca come parziale. Il cap governa la sola
spesa Cloudflare: con `-Compare` attivo la spesa Vertex del gemello A/B è
calcolata e riportata a parte, ma non consuma il tetto. Footer e report
espongono sempre le due cifre separate ed etichettate.

Credenziali: `CF_ACCOUNT_ID` e `CF_API_TOKEN` solo da variabili d'ambiente,
mai valori hardcoded nello script (a differenza di `tts_speechify_test.py`, che
contiene una chiave in chiaro). Il token non compare mai in log, report o
messaggi d'errore. `cf_tts_bench.env.ps1` resta locale e non è committabile:
`scripts/` è già in `.gitignore`.

## 9. Gestione errori

| Situazione | Comportamento |
|---|---|
| 401/403 | abort immediato, messaggio esplicito su account id/token, nessun retry |
| 429 | retry con backoff esponenziale (max 3), header di retry onorato se presente, conteggiato nelle metriche |
| 5xx | retry con backoff esponenziale (max 3) |
| Timeout | come 5xx; timeout per chiamata a 60 s, pari al default di `ABM_GEMINI_HTTP_TIMEOUT_MS_FLASH31` |
| WAV non decodificabile | anomalia `format`, chunk marcato, run prosegue |
| Cap di spesa superato | abort pulito, report parziale |
| Vertex non disponibile con `-Compare` | abort in fase di validazione, prima di spendere su CF |

Un chunk fallito dopo i retry non interrompe il run: viene marcato e il report lo
elenca. Solo le anomalie di durata non corrette determinano l'exit code ≠ 0.

## 10. Test del bench

`test/test_cf_tts_bench.py`, con `requests` mockata e nessuna chiamata reale:

- decodifica WAV: header corretto, sample rate/canali/width inattesi, payload
  troncato;
- stima token e costo: valori noti in ingresso, cifra attesa in uscita;
- gate di troncamento: durata sotto banda, sopra banda, audio vuoto, e verifica
  che il retry riuscito azzeri l'anomalia;
- accumulo del cap di spesa: il run si interrompe alla chiamata giusta e il
  report parziale viene scritto;
- costruzione del prompt: il testo inviato coincide con
  `gemini_tts.build_final_text` a parità di input.

## 11. Percorso di migrazione (fuori scope, per contesto)

A esito positivo, la migrazione consiste in: un backend `cloudflare` in
`gemini_tts._resolve_backend()`, un ramo in `synthesize()` che parla l'API CF e
riusa il gate di durata sviluppato qui al posto del `finish_reason` mancante,
nuove env per credenziali e tariffe, e roll-out graduale (prima le preview, poi
una quota di job, poi tutto) con `flash25` che resta su Vertex. Nulla di questo
è coperto dalla presente spec.
