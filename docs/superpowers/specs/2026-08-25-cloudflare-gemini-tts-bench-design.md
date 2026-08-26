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

Criteri di go/no-go, con l'esito misurato sui run del 26/08/2026:

| Asse | Soglia di GO | Misurato | Esito |
|---|---|---|---|
| Costo | costo osservato entro il +10 % del costo stimato dal modello token; risparmio effettivo ≥ 30 % vs listino Google | scarto aggregato stima/addebito **−0,39 %**; € 17,83/Mchar (€ 18,72 con la commissione crediti del 5 %) | **GO** |
| Robustezza | zero chunk troncati/vuoti non rilevati; ogni anomalia rilevata deve essere corretta dal retry | ogni anomalia è stata **rilevata** (nessun troncamento silenzioso), ma 8 chunk su 738 sono andati persi come buchi muti prima dei ritentativi; una classe di rifiuto resta non recuperabile | **NO-GO condizionato** |
| Throughput | nessun 429 a concorrenza pari a quella di prod; p95 di latenza per chunk non oltre 1,5× Vertex | **0 × 429 e 0 × 5xx** su 1049 tentativi fino a concorrenza 8; p95 20.612 ms sotto carico sostenuto | GO sui 429; **p95 da confrontare con Vertex** (confronto non ancora eseguito) |
| Qualità | parità di giudizio all'ascolto sull'A/B, nessuna deriva di voce fra chunk | giudizio all'ascolto: "qualità ottima"; A/B contro Vertex **non ancora eseguito** | **da completare** |

### 2.1 Misure osservate (26/08/2026)

Base: 4 sweep di saturazione, un libro da 738 chiamate (`L'Avversario`,
273.397 char) e uno da 297 (`Volo di notte`, 112.734 char), tutti su
`google/gemini-3.1-flash-tts` con voce Zephyr.

**Costo.** $ 20,75 per 1M caratteri, cioè € 17,83 al cambio 0,86 usato dal
banco. I crediti prepagati Cloudflare scontano una commissione d'acquisto del
5 %, quindi il costo da portare a conto economico è **€ 18,72/Mchar**. La
riconciliazione col saldo reale ($ 10,00 → $ 4,14) dà uno scarto di **−0,39 %**
contro la stima del banco: il modello di costo è accurato entro l'1 % e
conservativo per difetto. Il residuo non spiegato ($ 0,023) corrisponde a sonde
manuali non registrate in `metrics.jsonl`.

**Dottrina di fatturazione: verificata sul campo.** I registri AI Gateway
mostrano token e costo **assenti** (`- in`, `- out`, `$ -`) su ogni risposta
4xx, e presenti su ogni 200 — compresi i 200 con `result` privo di `audio`, che
Cloudflare conta come successi. Regola confermata: **si paga il 200, non la
sintesi**. Ne segue che ritentare un 4xx è gratuito e ritentare un
200-senza-audio costa una seconda chiamata piena.

**Latenza.** Piatta e dominata dalla sintesi, non dalla coda: p50 ~7,4 s sui run
brevi a qualunque concorrenza fra 1 e 8. Sotto carico sostenuto sale a p50
12,7-15,1 s e p95 17,7-20,6 s. Il throughput scala quasi linearmente (8 chiamate
in 52 s a concorrenza 1, in 2 s a concorrenza 8). **Nessun punto di saturazione
raggiunto fino a concorrenza 8**: il tetto va cercato più in alto.

**Modalità di guasto osservate.** Tre classi distinte, da non confondere:

| Guasto | Frequenza | Natura | Ritentabile |
|---|---|---|---|
| HTTP 200 con `result` privo di `audio` | 6 / 738, concentrate in una singola finestra | transitoria (stesso payload → 200 con audio) | sì, ma **ogni tentativo è fatturato** |
| HTTP 400 `code 7003` "Model execution failed" | 1 / 738 | transitoria, malgrado l'etichetta "User Input Error" | sì, **gratis** |
| HTTP 422 `code 2017` "Content moderation error" | 1 / 297 | **deterministica** | no |

Il 422 è il guasto più insidioso perché l'etichetta è fuorviante. Il trigger
non è contenuto sensibile: è **testo breve fatto in prevalenza di numerazione**.
Isolato con sonde mirate:

| Testo | Esito |
|---|---|
| `XIV. XV. XVI. XVII. …` | 422 |
| `14. 15. 16.` | 422 |
| `Capitolo XX.` | **422** |
| `AB. CD. EF.` | 200 |
| `Nel capitolo XX si racconta la partenza.` | 200 |

`Capitolo XX.` è un titolo di capitolo legittimo: in produzione il titolo viene
anteposto al primo chunk, quindi un capitolo corto può finire in un chunk
degenere e prendere 422 senza possibilità di recupero. **Prerequisito alla
migrazione**: fondere i chunk privi di contenuto linguistico col testo adiacente,
o saltarli senza contarli come guasto.

**Perdita di testo.** Prima dei ritentativi, gli 8 chunk falliti del run su
`L'Avversario` (1,08 % del libro) non hanno prodotto alcun PCM: il montaggio li
salta e l'M4B non riporta nulla. È la stessa classe di guasto degli incidenti
edge-tts e assembly PCM già subiti dal progetto. Il banco la rileva; la
produzione, con questi tassi, la consegnerebbe all'utente.

## 3. Vincoli accertati dell'API Cloudflare

Verificati su `developers.cloudflare.com/ai/models/google/gemini-3.1-flash-tts`:

- Endpoint: `POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run`,
  header `Authorization: Bearer {token}`.
- Input: `{"model": "google/gemini-3.1-flash-tts", "input": {"text", "voice",
  "temperature", "topP", "topK", "maxOutputTokens", "stopSequences"}}`.
- `text`: massimo 10.000 caratteri (prod usa chunk da 450, ampiamente sotto).
- `voice`: enum di 30 nomi, coincidente con il catalogo Gemini (Zephyr, Puck,
  Kore, Fenrir, …).
- Output **documentato**: `{"audio": "<base64 WAV>", "gatewayMetadata": {...}}`.
  **Reale, verificato al primo run a pagamento**: `audio` è un *data URI*
  `data:audio/l16;base64,…` il cui payload è **PCM grezzo s16le 24 kHz mono,
  senza intestazione RIFF** — non un WAV. Endianness confermata per misura
  (delta medio fra campioni consecutivi: 645,6 in little-endian contro 15.187,0
  in big-endian). **Nessun campo di usage/token, nessun `finish_reason`**:
  `gatewayMetadata` porta solo `keySource`. Il costo resta quindi stimato e la
  riconciliazione a dashboard resta obbligatoria.
- Zero data retention dichiarata.
- Fatturazione **reale, verificata**: il modello partner non è coperto
  dall'allocazione Workers AI del piano Workers Paid. Senza saldo prepagato
  risponde `HTTP 402 code 2021 "Insufficient balance; add money to your gateway
  or use BYOK"`, **anche con Workers Paid attivo**. L'accesso è sbloccato dai
  **crediti prepagati AI Gateway** (commissione d'acquisto 5 %); BYOK
  instraderebbe sulla fatturazione Google, annullando il vantaggio di costo.
  Il piano Workers Paid non è quindi un prerequisito per questo modello.

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
 "tokens_in_est","tokens_out_est","cost_usd_est","anomaly",
 "retry_statuses"}
```

`retry_statuses` elenca gli status di **tutti** i tentativi della chiamata, non
solo dell'ultimo. Senza, i 429 e i 5xx assorbiti dal retry sono invisibili: lo
stato finale di una chiamata riuscita non e' mai 429, quindi il criterio di GO
sul throughput (§6.3, "nessun 429 a concorrenza pari a quella di prod") non
sarebbe misurabile. `latency_ms` e' la latenza **cumulativa** dei tentativi,
per la stessa ragione.

Schema in sola aggiunta: i campi nuovi vanno in coda, i vecchi non cambiano
significato. Le analisi successive (confronto fra run, grafici) leggono questo
file e non il report, e devono restare capaci di leggere i run precedenti.

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
