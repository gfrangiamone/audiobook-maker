# La lingua del libro smette di essere una scelta: cascata lingua → modello → accento → voce

Design del 2026-09-04. Branch `VOXCPM`, worktree `.worktrees/VOXCPM`.

## 1. Obiettivo

Nel pannello **Impostazioni audio** (step 3 del wizard) la combo delle lingue
non è coerente con il modello TTS selezionato: si legge «Italiano (30)» mentre
il modello attivo è VOXCPM2, che di quel conteggio non sa nulla.

L'osservazione di partenza era di riordinare i campi — prima il modello, poi la
lingua. L'esame del codice porta più in là: **la lingua non è una scelta
dell'utente, è una proprietà del libro**. L'app la conosce già (metadati EPUB,
metadati PDF, rilevamento LLM sul testo) e la tratta già come vincolo — la
generazione viene bloccata se la voce non le corrisponde. Ma la presenta come
una tendina libera, in due copie non sincronizzate, e ne fa il primo campo del
pannello.

Questo design la sposta **fuori dai tab**, come stato del libro con la sua
provenienza dichiarata e un modo esplicito di correggerla; dentro i tab resta
la sola catena di scelte reali: **modello → accento → voce**.

## 2. Il difetto vero

### 2.1 Due liste di lingue con due criteri diversi

`fillLangs()` (app.js:861) popola `#vl` con tutte le lingue del catalogo.
`syncLanguageOptions()` (app.js:940) popola `#vlPremium` con il sottoinsieme
che soddisfa un solo predicato:

```js
const hasPremium = voices[lc].voices.some(x => x.id.startsWith('gemini:'));
```

**Il tab PREMIUM elenca le lingue di Gemini**, e le etichetta con il numero di
voci Gemini (`geminiCount()`). VOXCPM2 e Speechify non entrano nel criterio pur
essendo modelli premium a tutti gli effetti. Da qui l'incoerenza vista a
schermo: il conteggio appartiene a un modello diverso da quello selezionato.

### 2.2 Un cambio di lingua silenzioso

Sempre in `syncLanguageOptions()`:

```js
if(ordered.some(o=>o.value===currentVal)) dst.value = currentVal;
else if(ordered.length > 0) dst.value = ordered[0].value;
```

Con un libro svedese, sfiorare il tab PREMIUM **cambia la lingua senza dirlo**:
lo svedese non è coperto da Gemini, si atterra sulla prima lingua della lista.
Nessun segnale finché la generazione non viene bloccata da `_validateLanguage()`
(app.js:3214).

### 2.3 La dipendenza esiste già, ma solo a valle

`updModelsPremium()` (app.js:1083) costruisce già i modelli **a partire dalla
lingua**: VOXCPM2 solo se il catalogo di quella lingua ha una voce VoxCPM,
Simba solo se `isEnglish`. La regola richiesta — «l'elenco dei modelli sia
guidato dalla lingua del testo» — è quindi già implementata. Ciò che manca è
che a monte ci sia **la lingua del libro** e non una tendina che l'utente può
spostare a caso.

### 2.4 Il client butta via ciò che il server ha rilevato

`audiobook_app.py:9277-9282` chiama `generation_engine.detect_book_language()`
quando i metadati sono vuoti, e la risposta di `/api/analyze` (riga 9407) porta
già `language_detected`. In `app.js`:

```
grep -c language_detected static/js/app.js  →  0
```

Il client riceve l'informazione e la scarta. Non può quindi distinguere «lingua
scritta nei metadati» da «lingua indovinata dall'IA» da «lingua ignota», e
tratta i tre casi allo stesso modo.

## 3. Decisioni prese

Confermate in sede di brainstorming, 2026-09-04.

| # | Decisione |
|---|---|
| D1 | **Stato unico sopra i tab**: `#vl` e `#vlPremium` spariscono, la lingua del libro è un solo stato mostrato una volta sola |
| D2 | Il selettore **MODELLO compare solo se offre almeno 2 opzioni**, generalizzando la regola già in uso per l'accento |
| D3 | Per le lingue senza voci premium il tab PREMIUM è **disabilitato con il motivo scritto**, più le due uscite «Traduci il libro» e «Forza lingua» |
| D4 | Forzare la lingua **preserva il preservabile**: ciò che resta valido non si tocca, il resto torna al default, con una nota inline di cosa è cambiato |
| D5 | Lingua ignota: **si rileva dal testo** (meccanismo già esistente), la forzatura è la correzione |
| D6 | Il rilevamento resta **server-side** (com'è oggi); la lingua forzata resta **client-side** e viaggia nel campo `lang` già presente nei payload. Nessun endpoint nuovo, nessun campo nuovo nel descrittore del job, il recovery la eredita gratis |
| D7 | Il modello **Google HD** viene rimosso completamente dall'app |
| D8 | La cascata viene estratta in una **funzione pura senza DOM**, per poterla collaudare davvero |
| D9 | Nessun push: solo commit locali finché il collaudo manuale non è stato fatto dall'utente |

## 4. Fuori perimetro

- Il rilevamento LLM della lingua: esiste, funziona, non si tocca (23 test in
  `test/test_lang_detect.py`).
- La traduzione del libro: il pulsante «Traduci» del §6.3 riusa il flusso
  esistente, non lo modifica.
- I campi di costo `google_cost_eur`, `google_cost_actual`,
  `pricing_cost_actual`, `margin_eur_actual` (`generation_engine.py:3663-3736`):
  sono campi di costo generici con fallback per i job storici e **restano**,
  malgrado il nome. La rimozione del §9.2 non li tocca.
- L'app mobile: vedi §10.

## 5. La lingua del libro e la sua provenienza

### 5.1 Le tre provenienze, dal server

`/api/analyze` guadagna un campo `language_source` accanto a `language`:

| valore | significato | origine nel codice |
|---|---|---|
| `metadata` | scritta nel file | `epub_to_tts.py:1147` (`dc:language`), `pdf_to_tts.py:994` |
| `detected` | dedotta dall'IA leggendo il testo | `detect_book_language()`, `audiobook_app.py:9282` |
| `unknown` | nessuna delle due: `info.language` è vuota | — |

Il campo si ricava da dati che la funzione ha già in mano: `language_detected`
è già calcolata e già serializzata, `metadata` è il caso «lingua presente e non
rilevata», `unknown` è «lingua assente». Nessuna logica nuova sul server oltre
alla derivazione dei tre valori, che va emessa **sia** nella risposta di
analyze (riga 9407) **sia** nel ramo del job già esistente (riga 9243), perché
un job ripreso non perda la provenienza.

### 5.2 Le altre due provenienze, dal client

Il client tiene due valori che il server non conosce:

| valore | significato |
|---|---|
| `forced` | l'utente ha corretto la lingua a mano |
| `assumed` | il server ha detto `unknown` e il client ha ripiegato sul locale dell'interfaccia |

Il ripiego su `assumed` è ciò che fa oggi `fillLangs()` e resta invariato come
comportamento visibile; cambia che ora è **marcato**, ed è la marcatura a far
scattare il primo ramo di `_validateLanguage()` alla generazione. `forced`
invece è affidabile e **spegne l'avviso**: l'utente ha dichiarato lui la lingua.

### 5.3 Come viaggia

Nessun campo nuovo lungo la pipeline. La lingua effettiva — forzata o no —
continua a essere scritta nel campo `lang` già presente nei payload di
`/api/optimize_estimate` (app.js:3266), `/api/optimize` (3292), `/api/generate`
(3352, 3781) e nell'URL dell'anteprima. Il server la persiste già come
`browser_lang` nei descrittori dei job pendenti (`audiobook_app.py:1119`,
`1220`, `2541`) e il recovery la rilegge (riga 1268): **la forzatura sopravvive
a un riavvio senza scrivere una riga di codice server**.

## 6. Struttura del pannello

### 6.1 Sopra i tab: la lingua del libro

Una riga sola, prima della barra dei tab, dove oggi sta `#voiceMismatch`:

```
Lingua del libro:  Italiano  (dai metadati)          [ ⚙ Forza la lingua del libro ]
```

- Il nome della lingua è **testo, non una tendina**. Non è una scelta.
- La provenienza è scritta accanto: *dai metadati* / *rilevata dal testo* /
  *non rilevata, ipotizzata*. Il terzo caso è visivamente un avviso, non
  un'informazione neutra.
- Il pulsante a fianco apre il modale di forzatura (§7). Tooltip: **«Forza la
  lingua del libro»**, come da richiesta.

### 6.2 Dentro i tab: solo scelte reali

Misure prese su questa istanza da `/api/voices` il 2026-09-04, con Speechify
attivo come in produzione: **75 lingue**, Edge 75, Gemini 24, VOXCPM2 9 (de,
en, es, fr, hi, it, nl, pt, zh), Speechify 1 (en). Meta esposti:
`_premium_status`, `_translate_available`, `_voxcpm` — **nessun `_google_tts`**.

**Voci Standard** — con Google HD rimosso resta il solo motore gratuito,
quindi per D2 la riga MODELLO **non compare**. Restano:

```
[ ACCENTO ▾ ]   ← solo se la lingua ha più di un locale
[ VOCE    ▾ ]
```

**13 lingue su 75 hanno più di un locale**, quindi nelle altre 62 la riga
accento resta nascosta e il tab si riduce alla sola voce. Le lingue con più
varianti sono spagnolo (22), arabo (16), inglese (14), francese (4), tamil (4),
tedesco (3), cinese (3).

La regola è la stessa già in `_updateAccentDropdown()` (app.js:2181,
`opts.length < 2` → nascosto), estesa al modello: **niente tendine con una sola
voce dentro**.

**Voci PREMIUM** — l'ordine chiesto, con la lingua tolta di mezzo:

```
[ MODELLO ▾ ]   ← prima scelta reale, filtrata dalla lingua del libro
[ ACCENTO ▾ ]   ← solo se il modello ha più di una variante per quella lingua
[ VOCE    ▾ ]
[ stile / emozione ]  ← invariati, condizionati al modello come oggi
```

Quanti modelli, per lingua: in **inglese** quattro (VOXCPM2, Standard,
Avanzato, Simba), nelle altre 8 lingue VoxCPM tre, nelle restanti 15 lingue
Gemini due. Mai uno solo, quindi in tutte le 24 lingue premium la riga MODELLO
è visibile — ma la regola D2 resta scritta nella cascata, perché è ciò che
tiene il pannello corretto se un giorno un motore viene spento.

L'accento premium continua a leggersi da `_ACCENT_CATALOG` — en(4), es(2),
pt(2), fr(2), zh(2), de(3), ar(3) — con la stessa regola «almeno due».

### 6.3 Le 51 lingue senza premium

51 lingue su 75 non hanno **nessuna** voce premium. Oggi il tab PREMIUM le
gestisce cambiando lingua di nascosto (§2.2). D'ora in poi il tab è
**disabilitato**, con il motivo scritto e due uscite:

```
Le voci PREMIUM non sono disponibili in svedese.
[ Traduci il libro ]   [ Forza la lingua del libro ]
```

«Traduci il libro» compare solo se `_translate_available` è vero nel meta di
`/api/voices`, come già oggi per il resto della UI di traduzione. Su questa
istanza locale è **`false`**: il pulsante non si vede, e il collaudo manuale
del §11.5 deve tenerne conto.

### 6.4 Nomi dei modelli

Vale la regola di prodotto: **nessun nome di fornitore nell'interfaccia
utente**. Il riordino tocca proprio le etichette interessate, quindi vengono
sistemate contestualmente:

| oggi | dopo |
|---|---|
| `Simba (English)` | etichetta generica, senza il nome del fornitore |
| optgroup `… Google HD` | eliminato con il §9.2 |
| «il modello Gemini 3.1 TTS» (testo news) | riformulato senza il nome |

Le etichette già conformi — «Standard», «Avanzato», «Audiobook Maker
(VOXCPM2)» — restano.

## 7. La forzatura della lingua

### 7.1 Il modale

Aperto dal pulsante del §6.1. Elenca **l'unione di tutte le lingue dei modelli
disponibili** — 75, perché il motore gratuito le copre tutte — indicando per
ciascuna se ha voci premium. La lingua corrente è preselezionata.

### 7.2 Cosa succede alla conferma (D4)

La conferma non azzera il pannello: chiama la cascata (§8) e **preserva ciò che
resta valido**.

- Modello ancora disponibile nella nuova lingua → **resta selezionato**.
- Modello non più disponibile → **torna al default** della nuova lingua.
- Accento e voce: stessa regola, valutata dopo il modello.
- Se il tab PREMIUM diventa indisponibile, si passa a Standard.

E in ogni caso una **nota inline** dice cosa è cambiato:

> *Lingua impostata su svedese. Modello e voce riportati a Standard: le voci
> PREMIUM non sono disponibili in svedese.*

L'elenco dei cambiamenti non si ricostruisce con confronti sparsi: è un output
della cascata stessa (`changes[]`, §8), che sa già cosa ha spostato.

### 7.3 Effetti collaterali

- `bookData.language` viene riscritto e la provenienza diventa `forced`.
- L'avviso di `_validateLanguage()` non scatta più: l'utente ha dichiarato la
  lingua.
- `_rememberLastLang()` (app.js:2640) continua a memorizzare la scelta in
  `abm_last_lang` come oggi.
- `adoptTranslation()` (app.js:2929) resta il secondo punto che riscrive
  `bookData.language`: dopo una traduzione la provenienza diventa `metadata`
  (la lingua di destinazione è nota per costruzione) e la cascata viene
  applicata con le stesse regole.

## 8. La cascata come funzione pura

Il cuore dell'intervento è una funzione **senza DOM**:

```js
resolveAudioSelection({ lang, catalog, current })
  → { premiumEnabled, premiumReason,
      models[], model,
      accents[], accent,
      voices[],  voice,
      changes[] }
```

- **`lang`** — la lingua del libro, qualunque sia la provenienza.
- **`catalog`** — la risposta di `/api/voices` così com'è.
- **`current`** — la selezione attuale (tab, modello, accento, voce), inclusa
  quella tenuta fuori dal DOM: `_speechifyAccentSel`, `_speechifyVoiceSel`,
  `_voxcpmAccentSel`, `_voxcpmVoiceSel`.
- **`changes[]`** — l'elenco di cosa è stato spostato e perché, che diventa
  letteralmente il testo della nota del §7.2.

Il DOM torna a essere un renderer sottile: `applyBookLanguage()` chiama la
funzione e riversa il risultato nei `<select>`. Tutta la logica che può
rompersi vive in un posto solo, testabile senza browser.

**Invariante:** la cascata è **idempotente**. Applicarla due volte sullo stesso
stato non produce cambiamenti — proprietà che il §11.3 verifica esplicitamente,
perché è la difesa contro i cicli di `onchange` reciproci che oggi legano `#vl`
e `#vlPremium`.

## 9. Codice che sparisce

### 9.1 Dal pannello

| elemento | sorte |
|---|---|
| `#vl`, `#vlPremium` (markup + `<label>`) | rimossi |
| `fillLangs()` (app.js:861, 71 righe) | rimossa; la preselezione passa alla cascata |
| `syncLanguageOptions()` (app.js:940, 53 righe) | rimossa **interamente**: è il difetto §2.1 e §2.2 |
| `checkVoiceMismatch()` (app.js:5266, 39 righe) | rimossa: con una lingua sola il mismatch non è più rappresentabile |
| `autoFixVoice()` (app.js:5306, 32 righe) | rimossa con la precedente |
| `#voiceMismatch` (markup + stili + 13 lingue × 7 locali di nomi cablati) | rimosso |

Il banner di mismatch e la sua auto-correzione esistono **solo** perché le due
tendine potevano divergere. Tolta la divergenza, sparisce la classe di
problemi: è la parte di questo intervento che toglie più codice di quanto ne
aggiunga.

### 9.2 Google HD (D7)

Rimozione completa. `google_tts.is_available()` restituisce già `False` in modo
incondizionato dal commit `63c1ef6`, e l'istanza locale lo conferma: il meta di
`/api/voices` **non contiene `_google_tts`**. È codice morto che continua a
costare comprensione ogni volta che si legge il pannello.

Perimetro, per file (occorrenze di `gcloud` / `google_tts` / `googleVoices` /
`Google HD`):

| file | occ. | nota |
|---|---|---|
| `google_tts.py` | 13 | il modulo intero (745 righe) va eliminato |
| `audiobook_app.py` | 47 | `/api/voices` (7939), `/api/admin/google_tts_status` (9034), `_google_tts_reconcile_loop` (16997), `_has_active_google_tts_jobs` (454), riserva budget (10633) e `error_code: "google_tts_budget"` |
| `generation_engine.py` | 16 | dispatch motore (3336), `_google_tts_refund_unused` (2653) — **esclusi** i campi di costo del §4 |
| `static/js/app.js` | 15 | `googleVoices`, `_googleTtsAffordable()`, optgroup `Google HD`, classe `gcloud-voice` |
| `templates/_fragments/i18n_data.js` | 7 | etichette nelle 7 lingue |
| `tts_split.py` | 3 | ramo di split dedicato |
| `gemini_tts.py` | 1 | riferimento residuo |
| test (4 file) | 16 | `test_engine_dispatch.py` e `test_atomic_json_store.py` vanno adeguati, non cancellati |

I job storici che hanno usato Google HD restano leggibili: il fallback dei
campi di costo (§4) è esattamente ciò che li protegge.

**Questa rimozione è un intervento a sé.** Va fatta **prima** del riordino,
perché è ciò che rende la riga MODELLO del tab Standard inutile per D2, e va
committata separatamente.

## 10. App mobile

L'app mobile monta **solo le voci gratuite**: nessun modello premium abilitato.
Non vede quindi il tab PREMIUM, né la riga MODELLO, né gli accenti premium. Di
questo intervento le arrivano due cose sole:

1. **`language_source` nella risposta di analyze** — campo aggiuntivo,
   retrocompatibile: un client che lo ignora si comporta come oggi.
2. **Le 13 lingue multi-locale** valgono anche per lei: se in futuro esporrà la
   scelta dell'accento, la regola «almeno due opzioni» è la stessa.

Nessuna modifica richiesta lato mobile per questo rilascio.

## 11. Collaudo

### 11.1 Il problema di partenza

I «test JavaScript» di questo repo non eseguono JavaScript:
`test/test_app_js_tab_logic.py` legge `app.js` come testo e verifica che
contenga certe stringhe (`assert "vlPremium" in body`). Verificano com'è
scritto il sorgente, non come si comporta. `package.json` ha una sola
dipendenza (`firebase`), nessuna `devDependencies`, nessuno script di test.

Per questa feature quella pratica non regge: `resolveAudioSelection()` **è**
logica pura, ed è tutto ciò che può rompersi. Un test a grep passerebbe con la
cascata rotta.

### 11.2 Il runner

Node è presente, **v24.14.1**: `node:test` e `node:assert` sono nella libreria
standard. `node --test test/js/` gira **senza aggiungere una sola dipendenza**.
Perché `pytest` resti l'unico comando d'ingresso, `test/test_js_cascade.py` fa
da wrapper: lancia `node --test` e fallisce riportando l'output di Node.

### 11.3 I casi, scritti prima del codice

| caso | atteso |
|---|---|
| `it` da metadati | PREMIUM attivo, 3 modelli, default VOXCPM2, accento nascosto (1 solo locale) |
| `en` da metadati, modello «Avanzato» | PREMIUM attivo, **4 modelli** incluso Simba, accento visibile: 4 varianti da `_ACCENT_CATALOG` |
| `sv` da metadati | PREMIUM **spento** col motivo, Standard, accento nascosto |
| `es` | accento **visibile** in Standard: 22 locali |
| Speechify non configurato nel catalogo | Simba **assente** dai modelli anche in inglese |
| forza `it` → `sv` con VOXCPM2 attivo | modello e voce scendono a Standard, `changes` li elenca entrambi |
| forza `it` → `fr` con «Avanzato» attivo | «Avanzato» **preservato**: esiste anche in francese |
| forza `en` → `it` con Simba attivo | modello **non** preservabile: torna al default italiano |
| metadati vuoti, LLM spento | provenienza `assumed`, `_validateLanguage()` mostra l'avviso |
| `language_detected: true` | provenienza `detected`, nessun avviso |
| provenienza `forced` | nessun avviso, qualunque sia la lingua |
| cascata applicata due volte | **idempotente**: nessun cambiamento al secondo giro |

### 11.4 Lato Python

- `language_source` presente e coerente nella risposta di `/api/analyze` nei
  tre casi (`metadata` / `detected` / `unknown`), e nel ramo del job ripreso
  (riga 9243).
- `test/test_lang_detect.py` (23 test) e `test/test_recover_lang_persist.py`
  (3 test) devono passare **intatti**: sono la prova che né il rilevamento né
  la persistenza — su cui poggia D6 — sono stati toccati.
- I test a grep che citano `vlPremium` o `fillLangs` vanno riscritti sui nuovi
  identificatori, non cancellati: `test_validateLanguage_uses_vlPremium` in
  particolare cambia oggetto, perché `_validateLanguage()` non leggerà più due
  tendine ma un solo stato.
- Adeguamento dei test toccati dal §9.2.

### 11.5 Collaudo manuale

`docs/MANUAL_TESTS_AUDIO_LANGUAGE.md`, nello stile di
`MANUAL_TESTS_VOXCPM.md`, per ciò che l'automazione non dice: un EPUB svedese
col tab premium spento (e senza il pulsante «Traduci», che in locale è
disattivato — §6.3), un EPUB inglese con quattro modelli premium, un PDF senza
metadati, una forzatura andata e tornata, e la verifica che dopo un recovery il
job riprenda con la lingua **forzata** e non con quella dei metadati.

## 12. Rilascio

Solo **commit locali** (D9). Su questo progetto un push su `main` è già un
deploy in produzione senza gate di test: il push avviene dopo che il collaudo
manuale del §11.5 è stato fatto dall'utente e confermato.

Ordine dei commit:

1. Rimozione Google HD (§9.2), con i test adeguati.
2. `language_source` nella risposta di analyze (§5.1), con i test.
3. `resolveAudioSelection()` e i suoi test (§8, §11.3) — la funzione prima del
   suo consumo.
4. Riordino del pannello: markup, cascata collegata al DOM, rimozione del
   codice del §9.1.
5. Modale di forzatura (§7).
6. Documento di collaudo manuale (§11.5).
