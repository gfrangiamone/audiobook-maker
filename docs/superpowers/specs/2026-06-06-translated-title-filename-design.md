# Nome file proposto e titolo libro tradotti — Design

**Data:** 2026-06-06
**Branch:** `TRADUZ`
**Stato:** implementato (2026-06-07)

## Problema

Nel wizard traduzione:

- il campo nome file output (`trOutName`) è precompilato da `_trPrefillOutName`
  (`app.js:1886`) col nome file/titolo **in lingua originale**;
- `run_translation` (`generation_engine.py:2501-2507`) traduce i titoli dei
  capitoli ma il **titolo del libro** resta in originale nei metadati
  dell'output (`manifest_src["title"] = info.title`, riga ~2516).

## Requisito

1. Il nome del file di output deve essere **proposto all'utente già tradotto**
   nella lingua di destinazione.
2. Anche il **titolo del libro** deve essere tradotto (nei metadati del file
   prodotto e, dopo l'adozione, nel percorso audio).

## Decisioni prese (brainstorming)

| Decisione | Scelta |
|---|---|
| Trigger proposta UI | All'ingresso nel pannello Traduci + a ogni cambio lingua destinazione, con cache per lingua |
| Fallimento proposta | Silenzioso: resta il prefill attuale (nome originale), solo log server |
| Scope titolo tradotto | Output .abm/.epub/.txt **e** percorso audio dopo adopt (metadati M4B/MP3, pagina download, email) |
| Architettura | Endpoint dedicato `/api/translate_title` che riusa `translation_core.translate_titles` |

Approcci scartati: piggyback su `/api/translate_estimate` (mescola pricing e
contenuti, rallenta un endpoint oggi istantaneo e scatta anche per modifiche
che non cambiano lingua); nessuna proposta upfront (non soddisfa il requisito).

## Architettura

### 1. Endpoint `GET /api/translate_title/<job_id>?target=xx&source=yy` — `audiobook_app.py`

- Controlli come gli altri endpoint translate: `_check_job_owner`, validazione
  codici lingua `[a-z]{2,3}` (normalizzati lowercase, `split('-')[0]`),
  `translation_core.is_available()`.
- Titolo sorgente = `info.title` strip, troncato a **300 caratteri**.
- Casi rapidi senza LLM:
  - titolo vuoto o lingue invalide o translation non configurata →
    `{"title": ""}` (HTTP 200, fallback silenzioso lato client);
  - `source == target` → `{"title": <titolo originale>}`.
- **Cache per lingua nel job**: `job["tr_title_cache"] = {target: titolo}`.
  Hit → risposta immediata senza chiamata LLM.
- Chiamata LLM: `translation_core.resolve_backend()` +
  `make_client_provider` + `translate_titles(provider, [titolo], source,
  target, model=model, usage=UsageTracker())` (tracker usa-e-getta, non
  contabilizzato). Qualsiasi eccezione → log `[tr-title]` e `{"title": ""}`.
  Nota: su risposta LLM non valida `translate_titles` ritorna già il titolo
  originale — fallback coerente con la decisione "silenzioso".
- Nessun pagamento richiesto (cortesia pre-acquisto, costo irrisorio).

### 2. Frontend — `static/js/app.js`

- Nuova variabile di stato `trAutoOutName` (ultimo valore auto-impostato nel
  campo `trOutName`).
- `_trPrefillOutName()` resta sincrona (prefill immediato col nome originale,
  comportamento attuale) e in più salva il valore in `trAutoOutName`.
- Nuova `_trFetchTranslatedName()`:
  - fetch di `/api/translate_title/<jobId>?target=<trDstLang>&source=<trSrcLang>`
    con `AbortController` e timeout client ~12 s;
  - se `title` non vuoto **e** il valore attuale del campo è uguale a
    `trAutoOutName` (l'utente non ha editato a mano) → aggiorna campo e
    `trAutoOutName`;
  - ogni errore/timeout viene ignorato (resta il prefill).
- Trigger: all'apertura del pannello Traduci (subito dopo `_trPrefillOutName()`
  in `openTranslatePanel`, `app.js:1853`) e nell'handler `change` di
  `trDstLang` (stesso punto dove già si aggiorna la stima).
- `resetAll()`: azzera `trAutoOutName`.

### 3. Job di traduzione — `generation_engine.run_translation`

- Il titolo del libro viene **accodato al batch già esistente** dei titoli
  capitoli: `titles = [c["title"] for c in out_chapters] + [book_title]`
  (solo se `book_title` non vuoto); dopo `translate_titles` l'ultimo elemento
  viene estratto come `translated_title`. Zero chiamate LLM aggiuntive.
- Il job traduce **sempre** il titolo nel batch (non riusa `tr_title_cache`:
  il valore UI può essere stato editato come nome file e il manifest vuole il
  titolo vero, con maiuscole/spazi propri).
- `manifest_src["title"] = translated_title or <originale>` → manifest .abm,
  metadati epub, intestazione txt.
- `job["translated_title"] = translated_title` (per l'adopt).

### 4. Adozione percorso audio — `/api/translate_adopt` + `adoptTranslation()`

- L'endpoint (oggi imposta già `info.language = translated_lang`,
  `audiobook_app.py:~8853`) imposta anche
  `info.title = job.get("translated_title") or info.title` e include
  `"title"` nella risposta JSON.
- `adoptTranslation()` in `app.js` aggiorna `bookData.title = d.title` (se
  presente), così i metadati M4B/MP3, la pagina download e le email di
  completamento usano il titolo nella lingua di destinazione.

## Errori e casi limite

- LLM non configurato / errore / timeout / risposta invalida → la proposta
  resta il nome originale; l'utente può sempre digitare il nome che vuole.
- L'utente edita il campo e poi cambia lingua → il valore editato NON viene
  sovrascritto (guardia `trAutoOutName`).
- Job non in stato utile o non di proprietà → stessi errori degli altri
  endpoint translate (`_check_job_owner`).
- Titoli molto lunghi → cap 300 caratteri prima della chiamata.
- Adopt senza `translated_title` (job vecchi o batch titoli fallito) →
  `info.title` resta invariato, campo `title` nella risposta = titolo attuale.

## Test

- **Endpoint** (`test/test_translate_endpoints.py`, append): owner/validazioni;
  translation non configurata → `{"title": ""}`; successo con
  `translate_titles` mockata; cache hit (seconda richiesta NON re-invoca il
  mock); `source == target` → originale senza chiamata.
- **`run_translation`** (`test/test_run_translation.py`, append): il batch
  titoli contiene il titolo libro come ultimo elemento; manifest output con
  titolo tradotto; `job["translated_title"]` valorizzato; batch titoli fallito
  → titolo originale nel manifest.
- **Adopt** (`test/test_translate_endpoints.py`, append): `info.title`
  aggiornato e campo `title` nella risposta; senza `translated_title` →
  titolo invariato.

## Fuori scope

- Nessuna nuova variabile d'ambiente.
- Nessun avviso UI su fallimento della proposta.
- Nessuna modifica al CLI `scripts/translate_abm.py` (il CLI continua a non
  tradurre il titolo del libro).
- Nessuna traslitterazione/sanificazione aggiuntiva del nome file (resta la
  `_safe_filename` esistente applicata alla scrittura).
