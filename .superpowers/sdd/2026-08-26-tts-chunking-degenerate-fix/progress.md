# SDD ledger — plan: docs/superpowers/plans/2026-08-26-tts-chunking-degenerate-fix.md

Spec: docs/superpowers/specs/2026-08-26-cloudflare-tts-prod-backend-design.md (§5, §11 Fase 1) — autorita' vincolante.
Fase rilasciabile da sola: non dipende da Doc A ne' da Doc B. Chiude G5 (nessun errore 2017 su un libro intero), che e' il gate per l'accensione di Cloudflare in produzione.
Nota di percorso: `PARAMETRI_CONFIGURAZIONE.md` sta in `md_files/`, NON nella radice.

## Pre-flight — scansione conflitti

| Coppia / task | Cosa produce vs cosa consuma | Esito |
|---|---|---|
| T1 -> T2 | T1 produce `_is_degenerate_chunk`/`MIN_CHUNK_CHARS`; T2 li consuma in `_merge_degenerate_chunks` e `_plan_chunks` | coerente |
| T1 -> T3 | T3 consuma `_is_degenerate_chunk` in `generate_chunk_pcm_gemini` | coerente |
| T2 <- esistente | T2 consuma `_within(text, max_chars, max_bytes)` | da verificare in dispatch: la firma reale deve combaciare |
| T3 <- esistente | T3 consuma `_generate_silence_pcm(output_path, duration_sec=1, sample_rate=None)` | da verificare in dispatch |
| T2 / T3 | T2 aggiunge la chiave `"degenerate"` al piano, T3 decide da solo con il predicato | **ridondanza**: due decisioni indipendenti sullo stesso fatto. Vedi R1 |
| T3 vs `_synthesize_pcm_pieces_and_concat` (riga 769) | un chunk lungo viene spezzato in pezzi e ri-aggregato; T3 intercetta il degenere in `generate_chunk_pcm_gemini` (riga 860) **prima** dello split (riga 916) | nessun conflitto sul percorso nominale, ma l'aggregato ora trasporta `backend`/`tokens_measured` dal fix finale di Doc A. Vedi R2 |
| T4 | modifica `PARAMETRI_CONFIGURAZIONE.md` in radice | percorso reale `md_files/`. Vedi R3 |
| T4 | bump di `version.py` | coordinare con il bump di Doc B Task 6: un solo bump se le fasi escono insieme. Vedi R3 |
| Coerenza interna di ogni task | test specificati vs codice specificato | nessuna incoerenza oltre a quelle sopra |

Ruling R1 — la chiave `"degenerate"` nel piano e' informativa (diagnostica e test), non e' la condizione che governa il ramo di silenziamento: quella resta il predicato valutato in `generate_chunk_pcm_gemini`. Ragione: il wrapper riceve testo, non voci di piano, e nei percorsi che non passano da `_plan_chunks` (anteprima, ri-sintesi di un singolo chunk) la chiave non esisterebbe. Costo se sbagliato: basso — la chiave resta comunque utile ai test del merge.

Ruling R2 — il ramo degenere-irriducibile va intercettato PRIMA dello split in pezzi, dove il piano lo colloca. Un pezzo interno mai potra' essere degenere in modo irriducibile (viene da un testo lungo), quindi l'aggregato non deve imparare nulla di nuovo e `backend`/`tokens_measured` restano intatti. Se un implementatore fosse tentato di aggiungere il predicato anche dentro l'aggregazione, non lo faccia. Costo se sbagliato: medio — un pezzo silenziato dentro un chunk lungo produrrebbe un buco di audio invisibile ai contatori.

Ruling R3 — la documentazione dei parametri va in `md_files/PARAMETRI_CONFIGURAZIONE.md`. Il bump di versione di questo piano si esegue solo se la fase esce da sola; se esce insieme a Doc B, il bump e' uno solo e lo fa l'ultimo piano chiuso. Costo se sbagliato: nullo, e' cosmetico.

Task 1 — implementato in a81dcbb (predicato `_is_degenerate_chunk` + costanti + 13 test). Riportato DONE_WITH_CONCERNS: la mutazione che disattiva il criterio 2 (rapporto di numerali) lasciava la suite verde, perche' nessun caso del brief cadeva nella finestra 40-120 caratteri con maggioranza di token numerali.
Ruling R4: il buco di copertura si chiude subito, non piu' avanti. Un ramo che nessun test esercita in positivo e' un ramo che il prossimo giro puo' cancellare senza accorgersene — ed e' proprio il ramo che riconosce le intestazioni di capitolo, cioe' l'unica ragione per cui questa fase esiste. Chiuso in 4655151 con i due casi mancanti (dentro la finestra -> True, oltre il tetto -> False), entrambi verificati in mutazione: 1 failed / 14 passed per ciascuno, ripristino verificato (nessun diff su tts_split.py). — Costo se sbagliato: nullo, sono due asserzioni.

Task 1 — review: CONFORME (spec) + APPROVATO (qualita'). Mutazioni verificate dal revisore: criterio 1 annullato -> 2 failed; criterio 2 annullato -> 1 failed (uccisa da 4655151); tetto rimosso -> 1 failed. Rilievi R1 (MEDIO, regex numerali con IGNORECASE) e R2 (env var non documentata).
Ruling R5 — R1 accolto e chiuso subito, prima del Task 2: `_NUMERAL_TOKEN_RE` perde `re.IGNORECASE`, i romani si riconoscono solo maiuscoli. Ragione: la classe [IVXLCDM] senza distinzione di caso promuove a "numerale" parole italiane correnti (mi, ci, di, dici, vivi, lidi) e inglesi (civil, vivid, mimic); una frase breve che ne contenga abbastanza cade nella finestra 40-120 e verrebbe marcata degenere. L'asimmetria del danno decide: un falso negativo lascia l'errore 2017 che il codice gia' subisce oggi, un falso positivo fa sparire testo dall'audiolibro senza traccia nei contatori — e il Task 3 silenzia proprio in base a questo predicato, quindi il difetto va chiuso prima che qualcuno lo consumi. Due test di regressione (una frase italiana e una inglese, entrambe in finestra) verificati in mutazione: rimettere IGNORECASE -> 2 failed / 15 passed, ripristino verificato. Costo se sbagliato: basso — un'intestazione romana scritta in minuscolo resta non riconosciuta dal criterio 2, ma sotto i 40 caratteri la prende comunque il criterio 1.
Ruling R6 — R2 (env var `ABM_TTS_MIN_CHUNK_CHARS` assente da `md_files/PARAMETRI_CONFIGURAZIONE.md`) non e' un rilievo aperto: e' esattamente il contenuto del Task 4, gia' in piano. Nessuna azione qui. Costo se sbagliato: nullo.
Task 1: complete.

Task 2 — implementato in f6c17e9 (`_merge_degenerate_chunks` + chiamata in `_plan_chunks` + chiave `degenerate` nelle voci di piano). Riportato DONE_WITH_CONCERNS: (1) due test numerici del brief erano incoerenti col suo stesso algoritmo (i valori facevano riuscire il merge invece di farlo fallire), corretti al confine esatto lasciando l'algoritmo prescritto; (2) col separatore di merge a 2 caratteri contro l'1 dello splitter, un chunk isolato per pressione di cap non puo' quasi mai essere rifuso.
Aggiunto 2782dfc: `target` inizializzato a -1 invece di None (Pyright segnalava tre errori `int | None` su codice corretto).

Misura eseguita da me sul percorso reale, non sui casi costruiti: prependendo il titolo al capitolo (`f"{ch.title}.\n\n{clean_text}"`) lo splitter **non isola mai** il titolo — su corpi da 355, 2840 e 5680 caratteri e titoli "XIV" / "Capitolo XIV" / "1793" il primo chunk esce sempre pieno (1930-1993 char) e nessun chunk degenere sopravvive. Il caso degenere reale e' un altro: il **capitolo interamente degenere** (testo vuoto, testo uguale al titolo, corpo di poche parole) che produce un solo chunk di 4-10 caratteri.
Ruling R7 — il merge resta, il gate G5 pero' non poggia su di lui. Il caso dominante e' un capitolo mono-chunk, e `_merge_degenerate_chunks` opera dentro il capitolo: con un solo chunk non ha vicini ed e' strutturalmente impotente. Chi chiude G5 e' il Task 3 (silenziamento senza chiamata API). Il merge conserva valore come difesa in profondita' sui casi minori (sezioni numerate isolate da doppi a capo dentro un capitolo grande) e costa poco, quindi non lo si toglie. Costo se sbagliato: basso — codice che scatta di rado, coperto da test.
Ruling R8 — conseguenza operativa sul Task 3: poiche' il silenziamento diventa il meccanismo principale e non piu' il ripiego raro, ogni chunk silenziato deve lasciare una riga di log con indice di capitolo, indice di chunk e testo troncato. Un buco di audio che nessun contatore registra e' il difetto peggiore di questa fase (lo stesso rischio segnalato dal revisore del Task 1 sui falsi positivi del predicato). Da imporre nel brief del Task 3. Costo se sbagliato: nullo, e' solo diagnostica.

Task 2 — review: CONFORME (spec) + BUONA (qualita'). Quattro mutazioni tutte uccise (cap ignorati -> 2 failed; mai fondere -> 3 failed; solo fusione in avanti -> 1 failed; separatore vuoto -> 4 failed); nessun buco di copertura; 55 passed di regressione; file ripristinati byte-identici. Il revisore ha verificato con prove proprie l'affermazione strutturale dell'implementatore (separatore di merge 2 char >= separatore dello splitter 1 char) e ha confermato indipendentemente il Ruling R7: l'innesco "titolo isolato per pressione di cap" e' patologico, il caso dominante e' il capitolo mono-chunk, per cui il merge e' fuori scope per costruzione corretta. Unico rilievo minore (commento del segnaposto poco autoesplicativo) chiuso in ad61efa.
Task 2: complete.

Task 3 — implementato in ccbdce4 (ramo di silenziamento in `generate_chunk_pcm_gemini` prima dell'emergency byte-split, dict di successo con `skipped_degenerate: True`, log obbligatorio con job_id e testo troncato). Riportato DONE_WITH_CONCERNS: `model_key` reale invece di None (altrimenti `actual_cost_breakdown` solleva ValueError), monkeypatch su `gemini_tts.synthesize` invece di `tts_split._gemini` (late import locale), e **sette test pre-esistenti "risolti" allungando le fixture**.
Ruling R9 — quel terzo punto non era una regressione dei test, era il difetto. Il ramo di silenziamento usava `_is_degenerate_chunk`, che marca degenere QUALUNQUE testo sotto i 40 caratteri: verificato che "A mia madre.", "Fine.", "Texto.", "hello" venivano tutti silenziati senza chiamata API, cioe' cancellati dall'audiolibro. Un capitolo-dedica arriva al backend come chunk unico (il merge non ha vicini con cui fonderlo), quindi il caso e' raggiungibile in produzione, e la perdita e' invisibile: il dict di ritorno dichiara `success: True`. Le fixture allungate mascheravano proprio questo.
Corretto in 18c9c56 con `_is_unspeakable_fragment`, predicato separato e deliberatamente NON intercambiabile: silenzia solo cio' che non contiene alcun token parlabile ("XIV.", "1793", "..."), che e' quanto fa scattare la moderazione; la brevita' da sola non basta piu'. Il criterio della lunghezza minima resta dov'e' innocuo, cioe' nel merge. Le fixture originali dei sette test sono state ripristinate da `ccbdce4~1` e tornano verdi: e' la prova che il predicato non invade piu' il testo legittimo. Mutazione verificata: rimettendo `_is_degenerate_chunk` nel ramo -> 11 failed (il test della dedica piu' i dieci pre-esistenti), ripristino verificato. Costo se sbagliato: basso — un frammento con una sola parola vera ("Cap. 12") viene ora inviato all'API invece che silenziato, e se la moderazione lo rifiuta interviene il fallback silenzio gia' esistente. Asimmetria voluta: tentare una chiamata costa una richiesta, cancellare costa testo.
Ruling R10 — la concern 4 (i chunk silenziati attraversano comunque `record_rate_sample`/`record_usage` in generation_engine, iniettando un campione "N caratteri -> 1s di silenzio") resta aperta e parcheggiata: tocca i loop di generazione, esplicitamente fuori scope del Task 3. Volume atteso bassissimo dopo R9 (solo frammenti senza parole). Da valutare quando si tocchera' la calibrazione delle stime di durata. Costo se sbagliato: basso — rumore su una media mobile.

## Task 3 — review: aggiudicazione dei rilievi sul mio fix (18c9c56)

Il reviewer ha trovato due difetti reali **nel mio fix**, non nel lavoro
dell'implementer. Entrambi accolti.

- **R11 (era R1 [ALTO]) — accolto.** `_is_unspeakable_fragment` non aveva
  tetto di lunghezza, a differenza del gemello `_is_degenerate_chunk`. La
  cronologia di 125 char gia' presente in suite
  (`test_enough_context_disarms_the_numeral_ratio`) veniva silenziata per
  intero con `success: True`. E' la stessa classe di difetto che avevo appena
  corretto nell'implementer, reintrodotta da me su un asse diverso.
  Ruling: portare il tetto `_DEGENERATE_MAX_CHARS` anche nel predicato di
  silenziamento — oltre la finestra il chunk porta informazione, e un elenco
  di date e' testo da leggere. Costo se sbagliato: un chunk lungo di soli
  numerali arriva all'API e, se la moderazione lo rifiuta, cade nel fallback
  di silenzio preesistente. Costa una richiesta, non del testo.
- **R12 (era R2 [MEDIO]) — accolto.** Qualunque sequenza maiuscola di
  {I,V,X,L,C,D,M} passava per numerale: `CIVIL`, `MILD`, `VIVID`, `DVD`,
  `CIVIC`, `IL`. Un titolo tipografato in maiuscolo sarebbe stato cancellato.
  Ruling: `_STRICT_NUMERAL_TOKEN_RE` (romani **ben formati**) usato solo dal
  predicato di silenziamento; `_NUMERAL_TOKEN_RE` resta invariato per il
  merge, dove una parola scambiata per numerale non fa danno. Stessa regola
  di asimmetria applicata la terza volta: si stringe, non si allarga.
  Residuo noto e accettato: `DI/VI/LI/CI/MI/CD/MIX` restano numerali validi —
  come chunk unico maiuscolo sono quasi certamente numeri romani.
- **R13 (era R3 [BASSO]) — accolto.** Stringa di log allineata:
  `reason=irreducible_degenerate_fragment` -> `reason=wordless_fragment`.
- **R14 (era R4 [COSMETICO]) — accolto.** Commento a `tts_split.py:~1056`
  riformattato.

Mutazioni verificate in esecuzione (una per difetto, mirate al predicato
giusto — la prima passata aveva colpito per errore il tetto di
`_is_degenerate_chunk`, che condivide il testo della riga):
- tetto rimosso dal solo `_is_unspeakable_fragment` -> 2 rossi
  (`test_a_long_chronology_is_never_silenced`,
  `test_a_long_chronology_still_reaches_the_api`);
- `_STRICT_NUMERAL_TOKEN_RE` -> `_NUMERAL_TOKEN_RE` -> 9 rossi.

Task 3: complete.

## Task 4 — documentazione e bump (eseguito dal controller)

Ruling: Task 4 non e' stato dispatchato. E' documentazione il cui contenuto
dipende interamente dalle rulling R5/R9/R11/R12, che vivono solo nel contesto
del controller; un brief che le trasporti tutte costa piu' del task. Costo se
sbagliato: una voce di doc da correggere.

Due correzioni al brief, entrambe necessarie:
- il brief indica `PARAMETRI_CONFIGURAZIONE.md` alla radice; il file reale e'
  `md_files/PARAMETRI_CONFIGURAZIONE.md` ed e' tracciato normalmente (non
  serve `-f`, ma resta innocuo);
- la descrizione prescritta dal brief («sotto la soglia... se irriducibile
  viene silenziato») era vera quando il piano e' stato scritto ed e' **falsa
  dopo R9**: `MIN_CHUNK_CHARS` governa solo la fusione, il silenziamento passa
  da `_is_unspeakable_fragment`. Documentata la separazione dei due predicati,
  non la soglia unica.

Commit: 075da12 (versione 3.47.0 -> 3.47.1).
Suite completa dopo il fix R11/R12: 1983 passed, 4 skipped.

Task 4: complete.

## Fase 1 — pronta per la review whole-branch
BASE Fase 1: 909735a (ultimo commit prima di a81dcbb).
HEAD: 075da12.

## Review finale whole-branch — aggiudicazione (verdetto: DA CORREGGERE)

Report: `final-review-report.md`. 16 mutazioni provate, 13 uccise, 3
sopravvissute (M4, M8, M9).

**R15 — il rilievo 1 [ALTO] e' fondato e capovolge la premessa della fase.
Il Task 3 va rimosso, non corretto.** Verificato a codice: `fallback_lang` e'
sempre valorizzato dal chiamante (`generation_engine.py:4203/4519` ->
`_audit_language`, che ripiega su `info.language`), quindi dal v3.35.0 un
chunk rifiutato da Gemini per moderazione **non lascia un buco muto**: viene
narrato con voce edge e non conta come `failed_chunks` (`tts_split.py:1144`).
Il guasto che il Task 3 doveva prevenire non esiste piu' da quella versione:
esiste una degradazione lieve (tre tentativi Gemini sprecati e uno stacco di
voce su un titolo). Il ramo di silenziamento, contro quel beneficio, mette sul
piatto la cancellazione di testo — ed e' peggio dello stato attuale, non
meglio: `1914.` oggi si sente, con il ramo sparisce.

Valutata e scartata la via di mezzo (instradare il frammento direttamente
all'edge-fallback, saltando i tentativi Gemini): risparmierebbe le chiamate,
ma su Vertex un `XIV.` che Gemini sintetizza correttamente verrebbe comunque
degradato a voce edge. Sostituisce un guasto ipotetico con una regressione
qualitativa certa.

Ruling: **rimuovere il ramo di silenziamento** e con esso
`_is_unspeakable_fragment` e `_STRICT_NUMERAL_TOKEN_RE`, che restano senza
consumatori. La catena esistente (tentativi Gemini -> edge fallback ->
silenzio) e' gia' la risposta giusta per i frammenti irriducibili. Resta il
merge del Task 2, che riduce il fenomeno all'origine senza cancellare nulla.
Costo se sbagliato: qualche tentativo Gemini sprecato sui rari chunk degeneri
isolati — cioe' esattamente il comportamento oggi in produzione, gia'
accettato. Nessun testo perso in nessun caso.

Chiude in un colpo anche i rilievi 3, 4, 6, 7, 8, 10 e 11, tutti interni al
ramo rimosso.

**R16 — rilievo 2 [ALTO]: G5 si chiude diversamente da come la spec lo
formula.** La spec §5 chiede che i chunk degeneri non raggiungano l'API. Dopo
R9 e R15 quel criterio non e' piu' quello giusto: bloccare l'invio significa
cancellare, e la cancellazione e' il danno peggiore dei due. Ruling: il
criterio di uscita della Fase 1 diventa **«nessun chunk viene perso e nessun
frammento lascia un buco muto»**, ottenuto per fusione all'origine (Task 2) e
per edge-fallback sui residui (preesistente). Deviazione consapevole dalla
spec, registrata qui. Costo se sbagliato: sui chunk degeneri residui si
spendono tre tentativi Gemini prima del fallback.

**R17 — rilievo 5 [MEDIO] accolto:** la chiamata al merge dentro
`_plan_chunks` non e' coperta (M4 sopravvissuta: rimuoverla lascia tutto
verde). Con R15 il merge diventa l'unico deliverable di codice della fase:
senza un test che lo ancori, l'intera fase e' cancellabile senza un rosso.
Test da aggiungere.

**R18 — rilievo 9 [BASSO] parcheggiato con nota di deploy:** il merge cambia
`plan_sha`, quindi i job in volo al momento del deploy perdono il riuso dei
chunk gia' pagati e li rigenerano. Non risolvibile senza versionare
l'impronta; il costo e' un rigenerato su una manciata di job. Nota da
riportare al momento del deploy, non un difetto da correggere.

## R19 — il merge non ha alcun effetto: rimosso anche il Task 2

Misura eseguita dopo R15, indagando la mutazione M4 sopravvissuta (rilievo 5):
`_merge_degenerate_chunks` **non cambia mai** l'output di
`split_text_into_chunks`. 6000 input casuali (italiano e cinese, cap 60-2000
char, byte-cap 200/400/900/1800): **zero** casi in cui la fusione modificava
l'esito. La ragione e' strutturale, non statistica: lo splitter fa gia' greedy
packing, quindi un frammento resta isolato **solo** quando il vicino non ha
spazio residuo — e in quel caso il merge, che rispetta gli stessi cap, non puo'
fondere. M4 e' sopravvissuta perche' non c'era alcun comportamento da ancorare.

Il caso dominante identificato in R7 (capitolo il cui corpo e' vuoto o coincide
col titolo) e' fuori portata per costruzione: il merge lavora **dentro** il
capitolo e li' non esiste un vicino. Fondere fra capitoli distruggerebbe i
marker M4B.

Ruling: rimuovere la chiamata al merge, `_merge_degenerate_chunks`,
`_is_degenerate_chunk`, `_NUMERAL_TOKEN_RE`, `MIN_CHUNK_CHARS`
(`ABM_TTS_MIN_CHUNK_CHARS`), `_DEGENERATE_MAX_CHARS` e la chiave informativa
`degenerate` del piano — verificato che **nessun** modulo fuori da `tts_split`
e dal file di test li usa. Beneficio nullo contro un costo certo: il merge
cambia `plan_sha` e fa rigenerare i chunk gia' pagati ai job in volo durante il
deploy (rilievo 9, che con questa ruling decade).

**Esito della Fase 1: nessun codice di rimedio.** Il problema che la fase
voleva chiudere risulta gia' coperto dal ripiego edge-tts introdotto in
v3.35.0, e il rimedio pianificato non funziona. Cio' che la fase consegna e'
conoscenza resa eseguibile: `test/test_chunk_degenerate.py` diventa
`test/test_chunk_fragments.py` (12 test) e fissa il comportamento reale —
ogni chunk raggiunge il backend, un frammento rifiutato viene narrato dalla
voce di ripiego, lo splitter assorbe i frammenti. Se un domani lo splitter
cominciasse a isolarli pur avendo spazio,
`test_the_splitter_absorbs_a_fragment_when_there_is_room` diventa rosso ed e'
il segnale per riaprire il tema.

Mutazioni sui nuovi test: ripiego edge disattivato -> 1 rosso; silenziamento
sotto i 40 char reintrodotto -> 6 rossi.

Versione 3.47.1 -> 3.47.2. Documentazione riscritta di conseguenza.

## Chiusura della Fase 1

Commit del revert: `d478566` — `revert(tts): rimuove il chunking degenere,
inefficace e a rischio di cancellare testo` (6 file, +178 / -561).

Consegnato: `test/test_chunk_fragments.py` (12 test), riga sostitutiva in
`md_files/PARAMETRI_CONFIGURAZIONE.md`, sezione G5 riscritta in
`docs/RUNBOOK_CLOUDFLARE_TTS.md` (accensione AUTORIZZATA dopo il controllo di
ascolto), `version.py` a 3.47.2. Suite completa: 1937 passed, 4 skipped.

Percorso di test locale allineato al revert (scenario 6 riscritto come
controllo di ascolto, nota sull'errore 2017 riscritta) e consegnato all'utente.

Nulla e' stato pushato: vincolo permanente dell'utente — nessun push prima dei
suoi test in locale.
