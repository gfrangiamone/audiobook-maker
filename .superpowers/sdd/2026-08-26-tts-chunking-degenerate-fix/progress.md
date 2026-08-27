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
