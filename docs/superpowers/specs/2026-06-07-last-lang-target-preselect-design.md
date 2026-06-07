# Preselezione lingua target traduzione (ultima usata) — Design

**Data:** 2026-06-07
**Branch:** `TRADUZ`
**Stato:** approvato (brainstorming concluso)

## Problema

Alla prima apertura del pannello Traduci, `trDstLang` resta sulla **prima
lingua in ordine alfabetico** (`_trFillLangSelects`, `app.js` — il valore
viene mantenuto solo entro la sessione del wizard tramite `old`). L'utente
deve cercare ogni volta la lingua di destinazione che usa abitualmente.

## Requisito

La prima lingua proposta come target di traduzione deve essere:
1. l'**ultima lingua utilizzata** (in generazione audio o in traduzione),
   persistita lato client;
2. in mancanza, la **lingua dell'interfaccia utente corrente** (`cl`).

## Decisioni prese (brainstorming)

| Decisione | Scelta |
|---|---|
| Registrazione | All'**avvio effettivo**: avvio generazione audio (lingua del selettore voci del tab attivo) e avvio traduzione (lingua destinazione). Mai su click esplorativi dei select. |
| Scope | Solo preselezione del **target traduzione**; il selettore voci audio mantiene la logica attuale (lingua libro → lingua UI). La generazione audio però CONTRIBUISCE ad aggiornare il valore salvato. |
| Collisione con origine | Fallback a catena: ultima usata == origine → prova lingua UI; anche quella == origine → comportamento attuale (alfabetico). |
| Persistenza | `localStorage` chiave `abm_last_lang` (pattern esistente: `abm_l`, `abm_th`, `abm_v_email`). Cookie scartato (overhead richieste, nessun uso server); store server per client_id scartato (sproporzionato). |

## Architettura — tutte le modifiche in `static/js/app.js`

### 1. Helper `_rememberLastLang(code)`

- Normalizza: `String(code).toLowerCase().split('-')[0]`; scarta valori vuoti
  o non `[a-z]{2,3}`.
- Salva in `localStorage.setItem('abm_last_lang', code)` dentro try/catch
  silenzioso (come `setLang` per `abm_l`).

### 2. Punti di registrazione (avvio effettivo)

- **`startTranslation()`**: dopo le validazioni iniziali (src ≠ dst), salva
  `dst` (la lingua destinazione effettivamente avviata).
- **Avvio generazione audio**: salva la lingua del selettore voci del tab
  attivo (`#vlPremium` se `wizardState.audioTab === 'premium'`, altrimenti
  `#vl`). Entry point: `startGen()` (calcola già `_genLang2` con esattamente
  questa logica, `app.js:3005-3007`) e, se il flusso combinato
  `startCombinedGeneration()` (`app.js:2452`) invia una generazione senza
  passare da `startGen` (percorso optimize+auto-gen), anche nel punto di
  invio di quel flusso dove la lingua attiva è già calcolata. L'esecutore
  verifica i percorsi reali e copre tutti quelli che avviano una generazione.

### 3. Preselezione in `_trFillLangSelects()`

Dopo il blocco esistente che ripristina `old` e prima della precompilazione
origine, SOLO per `trDstLang` e SOLO se il select non ha un valore di
sessione (cioè `old` non è stato ripristinato):

- Lingua origine di riferimento: valore corrente di `trSrcLang` se presente,
  altrimenti `bookData.language` normalizzata.
- Candidati in ordine: `localStorage.getItem('abm_last_lang')`, poi `cl`.
- Il primo candidato che (a) esiste tra le opzioni del select e (b) è diverso
  dalla lingua origine viene applicato a `sel.value`. Nessun candidato valido
  → nessuna modifica (comportamento attuale).
- L'applicazione è programmatica (nessun evento `change` artificiale):
  `goToTranslate` chiama già `trUpdateEstimate()` e `_trFetchTranslatedName()`
  dopo `_trFillLangSelects()`, quindi stima e nome file proposti usano già la
  lingua preselezionata senza trigger aggiuntivi.

## Errori e casi limite

- `localStorage` non disponibile (private mode) → try/catch, si passa al
  fallback `cl`.
- Valore salvato corrotto/non più tra le lingue disponibili → scartato dal
  check "esiste tra le opzioni".
- L'utente cambia lingua a mano e riapre il pannello nella stessa sessione →
  `old` vince, nessuna preselezione (comportamento attuale preservato).
- La registrazione avviene solo se l'avvio supera le validazioni client (per
  la traduzione: dopo il check src ≠ dst).

## Test — `test/test_app_js_last_lang.py` (statici sul source, pattern esistente)

- Helper `_rememberLastLang` presente e usa la chiave `abm_last_lang`.
- Chiamata in `startTranslation` e nel/nei punti di avvio generazione audio.
- In `_trFillLangSelects`: lettura di `abm_last_lang`, fallback `cl`,
  esclusione della lingua origine, applicazione solo in assenza di valore di
  sessione.

## Fuori scope

- Nessuna modifica alla preselezione del selettore voci audio (`fillLangs`).
- Nessun cookie, nessun endpoint, nessuna variabile d'ambiente.
- Nessuna migrazione: chi non ha il valore salvato cade sul fallback UI.
