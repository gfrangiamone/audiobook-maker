# Preselezione Lingua Target Traduzione — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alla prima apertura del pannello Traduci, `trDstLang` viene preselezionata con l'ultima lingua usata (avvio generazione audio o traduzione, persistita in `localStorage('abm_last_lang')`) con fallback sulla lingua UI corrente, mai uguale alla lingua di origine.

**Architecture:** Tutto in `static/js/app.js`: helper `_rememberLastLang(code)` (normalizza e salva in localStorage); registrazione nei 4 punti di avvio reale (startTranslation + i 3 percorsi di generazione audio dove la lingua attiva è già calcolata); preselezione in `_trFillLangSelects()` tramite flag `_trRestored` (la preselezione scatta solo quando il select non ha un valore di sessione ripristinato) con catena `abm_last_lang` → `cl` ed esclusione della lingua origine.

**Tech Stack:** vanilla JS, localStorage, pytest (test statici sul source).

**Spec:** `docs/superpowers/specs/2026-06-07-last-lang-target-preselect-design.md`

**Branch:** `TRADUZ` (lavorare e committare qui; mai push senza conferma esplicita).

**Convenzioni vincolanti:**
- Shell di sviluppo: PowerShell. Niente `&&` per concatenare; comandi singoli.
- Test in `test/`. Eseguire con: `$env:PYTHONPATH='.'; pytest test/<file> -v --tb=short`
- Non riformattare il JS circostante; stile compatto esistente.

---

## File Structure

| File | Azione | Responsabilità |
|---|---|---|
| `static/js/app.js` | **Modify** | Helper `_rememberLastLang`; 4 chiamate di registrazione; preselezione + flag `_trRestored` in `_trFillLangSelects`. |
| `test/test_app_js_last_lang.py` | **Create** | Test statici sul source (pattern `test_app_js_tr_title.py`). |

**Riferimenti verificati (HEAD `79fda86`; i numeri possono slittare — fidarsi del testo):**
- `_trFillLangSelects`: `app.js:1858-1884`; dentro il `forEach(['trSrcLang','trDstLang'])` il ripristino sessione è `if(old&&voices[old])sel.value=old;` (`:1875`); in coda il blocco «Origine precompilata dalla lingua del libro» (`:1878-1883`).
- `startTranslation`: `app.js:~1960`; contiene `const src=document.getElementById('trSrcLang').value;` `const dst=document.getElementById('trDstLang').value;` e il check `if(src===dst){showErr('trErr',t('tr_err_same_lang'));return}`.
- `startCombinedGeneration`: ramo optimize+autogen calcola `const selLang=(selLangEl&&selLangEl.value)||cl;` (`:2525`); ramo TTS diretto calcola `var _genLang=(wizardState.audioTab==='premium')?...` (`:2570-2572`).
- `startGen`: calcola `const _genLang2=(wizardState.audioTab==='premium')?...` (`:3005-3007`).
- ATTENZIONE: in `startCombinedGeneration` c'è un ALTRO `selLang` nel blocco stima (`:2485-2487`) — NON registrare lì (è solo una stima, non un avvio).
- Pattern persistenza esistente: `setLang` (`:216`) usa `try{localStorage.setItem('abm_l',l)}catch(e){}`.
- `cl` = lingua UI corrente (`:163`).

---

### Task 1: `app.js` — helper, registrazione, preselezione + test statici

**Files:**
- Modify: `static/js/app.js`
- Create: `test/test_app_js_last_lang.py`

- [ ] **Step 1.1: Crea i test falliti**

```python
# test/test_app_js_last_lang.py
"""Test statici su app.js: preselezione lingua target da ultima usata
(spec 2026-06-07-last-lang-target-preselect)."""
from pathlib import Path

APP = Path("static/js/app.js").read_text(encoding="utf-8")


def test_helper_present_with_storage_key():
    assert "function _rememberLastLang" in APP
    assert "abm_last_lang" in APP


def test_helper_normalizes_and_validates():
    fn = APP.split("function _rememberLastLang", 1)[1][:400]
    assert "toLowerCase" in fn
    assert "split('-')" in fn
    assert "[a-z]{2,3}" in fn


def test_recorded_on_translation_start():
    fn = APP.split("async function startTranslation", 1)[1][:1500]
    assert "_rememberLastLang(dst)" in fn


def test_recorded_on_audio_starts():
    # ramo combined optimize+autogen, ramo TTS diretto, startGen
    assert "_rememberLastLang(selLang)" in APP
    assert "_rememberLastLang(_genLang)" in APP
    assert "_rememberLastLang(_genLang2)" in APP


def test_estimate_block_does_not_record():
    # Il selLang del blocco stima (optimize_estimate) NON deve registrare:
    # la registrazione avviene una sola volta nel ramo optimize, dopo il
    # calcolo del selLang del payload.
    assert APP.count("_rememberLastLang(selLang)") == 1


def test_preselect_in_fill_lang_selects():
    fn = APP.split("function _trFillLangSelects", 1)[1]
    fn = fn.split("function _trPrefillOutName", 1)[0]
    assert "abm_last_lang" in fn
    assert "_trRestored" in fn
    assert "[saved,cl]" in fn  # catena di fallback: ultima usata, poi lingua UI


def test_preselect_skips_source_lang():
    fn = APP.split("function _trFillLangSelects", 1)[1]
    fn = fn.split("function _trPrefillOutName", 1)[0]
    assert "cand!==srcLang" in fn
```

- [ ] **Step 1.2: Esegui — verifica fallimento**

Run: `$env:PYTHONPATH='.'; pytest test/test_app_js_last_lang.py -v --tb=short`
Expected: FAIL su tutti (helper assente)

- [ ] **Step 1.3: Implementa in `app.js` — 5 edit**

**(a) Helper** — inserire subito prima di `function goToTranslate(){` (sezione TRANSLATE WIZARD, `:1846`):

```javascript
function _rememberLastLang(code){
  // Memorizza l'ultima lingua usata (avvio generazione audio o traduzione)
  // per la preselezione del target traduzione (spec 2026-06-07).
  const c=String(code||'').toLowerCase().split('-')[0];
  if(!/^[a-z]{2,3}$/.test(c))return;
  try{localStorage.setItem('abm_last_lang',c)}catch(e){}
}
```

**(b) Registrazione in `startTranslation`** — subito dopo il check stessa-lingua:

```javascript
  if(src===dst){showErr('trErr',t('tr_err_same_lang'));return}
  _rememberLastLang(dst);
```

(Nota: in `startTranslation` la riga del check può avere intorno la gestione
`window._trStarting`; l'inserimento è comunque immediatamente dopo il `return`
del check `src===dst`.)

**(c) Registrazione nel ramo optimize+autogen di `startCombinedGeneration`** — subito dopo il calcolo del `selLang` del payload (`:2522-2525`, quello nel blocco `try` che costruisce `var payload={job_id:jobId,batch:false,lang:selLang};`, NON quello del blocco stima):

```javascript
      const selLang=(selLangEl&&selLangEl.value)||cl;
      _rememberLastLang(selLang);
```

**(d) Registrazione nel ramo TTS diretto di `startCombinedGeneration`** — subito dopo il calcolo (`:2570-2572`):

```javascript
      var _genLang=(wizardState.audioTab==='premium')
        ?(document.getElementById('vlPremium')?.value||cl)
        :(document.getElementById('vl')?.value||cl);
      _rememberLastLang(_genLang);
```

**(e) Registrazione in `startGen`** — subito dopo il calcolo (`:3005-3007`):

```javascript
    const _genLang2=(wizardState.audioTab==='premium')
      ?(document.getElementById('vlPremium')?.value||cl)
      :(document.getElementById('vl')?.value||cl);
    _rememberLastLang(_genLang2);
```

**(f) Preselezione in `_trFillLangSelects`** — due modifiche:

1. Nel `forEach`, sostituire la riga di ripristino sessione:

```javascript
    if(old&&voices[old])sel.value=old;
```

con (flag che distingue «valore di sessione ripristinato» da «default»):

```javascript
    if(old&&voices[old]){sel.value=old;sel._trRestored=true;}else{sel._trRestored=false;}
```

2. In coda alla funzione, DOPO il blocco «Origine precompilata dalla lingua del libro» (così `trSrcLang.value` è già definitivo), aggiungere:

```javascript
  // Preselezione destinazione: ultima lingua usata (abm_last_lang) o lingua
  // UI, solo alla prima apertura (nessun valore di sessione ripristinato) e
  // mai uguale all'origine (spec 2026-06-07-last-lang-target-preselect).
  const dstSel=document.getElementById('trDstLang');
  if(dstSel&&!dstSel._trRestored){
    let srcLang=(src&&src.value)||'';
    if(!srcLang&&bookData&&bookData.language)srcLang=bookData.language.split('-')[0].toLowerCase();
    let saved='';
    try{saved=(localStorage.getItem('abm_last_lang')||'').toLowerCase()}catch(e){}
    for(const cand of [saved,cl]){
      if(cand&&cand!==srcLang&&dstSel.querySelector('option[value="'+cand+'"]')){dstSel.value=cand;break}
    }
  }
```

(`src` è la variabile già dichiarata nel blocco origine, `const src=document.getElementById('trSrcLang');` — riusarla, non ridichiararla.)

- [ ] **Step 1.4: Esegui i test**

Run: `$env:PYTHONPATH='.'; pytest test/test_app_js_last_lang.py -v --tb=short`
Expected: PASS (7 test)

Regressione JS:
Run: `$env:PYTHONPATH='.'; pytest test/test_app_js_tr_title.py test/test_app_js_estimate.py test/test_app_js_payment_modal.py test/test_app_js_tab_logic.py -q`
Expected: PASS (tutti)

- [ ] **Step 1.5: Commit**

```
git add static/js/app.js
git add -f test/test_app_js_last_lang.py
git commit -m "feat(translate): preselezione lingua target da ultima usata (abm_last_lang) con fallback lingua UI"
```

---

### Task 2: Regressione completa e chiusura

**Files:**
- Modify: `docs/superpowers/specs/2026-06-07-last-lang-target-preselect-design.md` (stato)

- [ ] **Step 2.1: Suite completa**

Run: `$env:PYTHONPATH='.'; pytest test/ --tb=short -q`
Expected: nessuna nuova failure (note pre-esistenti: 4 in `test_paypal_create_gemini` da ordering/reload, passano in isolamento).

- [ ] **Step 2.2: Verifica manuale rapida (opzionale)**

Run: `python audiobook_app.py` — caricare un txt, avviare una generazione audio in una lingua X, ricaricare la pagina, caricare di nuovo il file, aprire «Traduci».
Expected: `trDstLang` preselezionata su X (se X ≠ origine). Fermare il server.

- [ ] **Step 2.3: Aggiorna stato spec, marca checkbox piano, committa**

Nella spec: `**Stato:** approvato (brainstorming concluso)` → `**Stato:** implementato (2026-06-07)`. Nel piano: tutti i `- [ ]` → `- [x]`.

```
git add -f docs/superpowers/specs/2026-06-07-last-lang-target-preselect-design.md docs/superpowers/plans/2026-06-07-last-lang-target-preselect.md
git commit -m "docs(translate): chiusura spec + piano preselezione lingua target"
```

**NON pushare:** il push si fa solo su conferma esplicita dell'utente.

---

## Note trasversali per l'esecutore

1. I numeri di riga sono riferiti a HEAD `79fda86` e slittano: cercare gli ancoraggi testuali (`var payload={job_id:jobId,batch:false,lang:selLang}`, `_genLang`, `_genLang2`, `if(old&&voices[old])sel.value=old;`).
2. NON toccare la preselezione del selettore voci audio (`fillLangs`, `:810-869`): fuori scope.
3. NON registrare nel blocco stima di `startCombinedGeneration` (`:2485-2487`): è una stima, non un avvio (il test `test_estimate_block_does_not_record` lo verifica contando le occorrenze).
4. `cl` è una variabile globale già esistente (`let cl='en'`, `:163`).
