# Rilevamento lingua via LLM all'analisi — Design

**Data:** 2026-06-06
**Branch:** `TRADUZ`
**Stato:** approvato (brainstorming concluso)

## Problema

`info.language` arriva solo dai metadati del file: epub (`dc:language`), pdf
(metadata), abm (manifest). I `.txt` non hanno mai lingua; pdf/epub spesso ne
sono privi. Quando manca:

- le stime di durata (`_estimate_chapter_seconds`) ricadono su `"it"`;
- nel wizard traduzione `trSrcLang` non viene precompilato e resta sulla prima
  opzione alfabetica — origine sbagliata = traduzione spazzatura pagata;
- la preselezione lingua/voci del percorso audio non avviene.

## Requisito

Se il file in input non ha metadato lingua, il sistema esamina **tramite lo
stesso LLM dell'ottimizzazione AI** (`_llm_client`, config `ABM_LLM_*`) una
serie di **tre paragrafi consecutivi** del libro e ne determina la lingua.

## Decisioni prese (brainstorming)

| Decisione | Scelta |
|---|---|
| Trigger | All'analisi del file (`/api/analyze`), inline e sincrono |
| Campione | Da metà libro, 3 paragrafi consecutivi "sostanziosi" (≥ 80 char) |
| Fallimento | Silenzioso: lingua resta vuota, solo log server, 1 tentativo |
| Collocazione | Helper in `generation_engine.py`, usa direttamente `_llm_client` |

Approcci scartati: logica in `translation_core.py` (userebbe il backend
`ABM_TRANSLATE_*`, non lo stesso LLM dell'ottimizzazione); rilevamento
asincrono post-analyze (complessità endpoint/polling non giustificata per una
chiamata da ~2 s).

## Architettura

### 1. `_pick_language_sample(chapters)` — funzione pura, `generation_engine.py`

- Concatena i paragrafi di tutti i capitoli in ordine (split del testo dei
  capitoli su righe vuote, regex `\n\s*\n`).
- Parte dall'**indice centrale** della lista paragrafi e scorre in avanti
  cercando la prima terna di **3 paragrafi consecutivi, ognuno ≥ 80
  caratteri**; se non la trova dal centro in poi, riprova dall'inizio.
- Fallback (poesia, paragrafi corti): 3 paragrafi consecutivi non vuoti
  qualsiasi a partire dal centro; se anche questo fallisce, primi 1500
  caratteri del testo complessivo.
- Ogni paragrafo troncato a **600 caratteri** → campione massimo ~1800
  caratteri. Ritorna `""` se non c'è testo.

### 2. `detect_book_language(info)` — `generation_engine.py`

- Se `_llm_client is None` → ritorna `""` subito.
- Campione da `_pick_language_sample(info.chapters)`; vuoto → `""`.
- Chiamata **non-streaming** a `_llm_client.chat.completions.create`:
  `model=LLM_MODEL`, `temperature=0`, `max_tokens=8`, `timeout=20` (costante,
  nessuna nuova env var), **un solo tentativo**, niente retry.
- System prompt dedicato (inglese, come gli altri prompt interni): l'utente
  invia un estratto di libro, rispondere SOLO con il codice ISO 639-1 della
  lingua dell'estratto (es. `it`, `en`, `de`), nessun altro testo.
- Parsing risposta: strip, lowercase, primo token, `split('-')[0]`; valida con
  regex `[a-z]{2}` (ISO 639-1 = sempre 2 lettere; una regex più lasca farebbe
  passare token inglesi tipo "the" da risposte verbose). Risposta non valida o
  eccezione → log `[lang-detect]` e ritorno `""`.

### 3. Integrazione in `audiobook_app.py` — `/api/analyze`

Subito dopo il parse del file (dopo il check `if not info.chapters`), prima
della creazione del job e del calcolo `_lang_new` (stime durata):

```python
language_detected = False
if not (getattr(info, "language", "") or "").strip() and _llm_available():
    code = detect_book_language(info)
    if code:
        info.language = code
        language_detected = True
```

- `jobs[job_id]["language_detected"] = True` quando rilevata (tracciabilità).
- Campo `"language_detected"` nella risposta JSON di `/api/analyze`.
- Vale per **tutti i formati** (txt sempre; pdf/epub/abm quando il metadato
  manca). Downstream automatico: stime minuti, preselezione voci audio,
  prefill `trSrcLang` nel wizard traduzione, manifest `.abm` esportato.
- **Zero modifiche frontend.**

## Errori e casi limite

- LLM non configurato / errore rete / timeout / risposta invalida → lingua
  resta `""`, l'analisi completa normalmente, solo log server.
- Job riusato (duplicate upload detection): nessuna nuova chiamata LLM,
  `info.language` è già memorizzata nel job esistente.
- Latenza aggiunta all'upload: ~1-3 s, solo per file senza metadato lingua e
  con LLM configurato.
- Costo LLM: ≤ ~1800 char input + 8 token output per upload → irrisorio.

## Test — `test/test_lang_detect.py`

- **Campionamento:** partenza da metà, filtro ≥ 80 char, fallback paragrafi
  corti, fallback primi 1500 char, troncamento a 600, lista vuota → `""`.
- **`detect_book_language`:** client fake che risponde `"it"`, `" EN "`,
  `"en-US"`, spazzatura, eccezione; client `None` → `""`.
- **Integrazione `/api/analyze`:** upload txt con detect mockato → `language`
  valorizzata nella risposta + `language_detected: true`; con detect che
  fallisce → `language` vuota e analisi completa.

## Fuori scope

- Nessuna nuova variabile d'ambiente.
- Nessun avviso UI quando il rilevamento fallisce.
- Nessun retry/backoff.
- Nessuna modifica al CLI `scripts/translate_abm.py`.
