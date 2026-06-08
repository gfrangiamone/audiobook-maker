# Pagamento traduzione unificato nel popup premium — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nel percorso traduzione un solo pagamento al click "Avvia traduzione", che copre traduzione + eventuale ottimizzazione AI, tramite lo stesso popup delle voci premium (`geminiPayModal`, voucher + PayPal).

**Architecture:** Refactoring solo client-side. Si parametrizza il popup premium con un oggetto contesto `_payCtx` (righe, scopo voucher, endpoint PayPal create-order, callback di conferma). Il flusso Gemini costruisce il suo contesto come oggi; il flusso traduzione costruisce il proprio. Si rimuove dal pannello T3 il pagamento ottimizzazione inline (bottone "Buono" + coupon-row) e la stima € si sposta nel footer. Nessuna modifica al backend: `/api/translate`, `/api/paypal_create_order_translate`, `/api/paypal_capture_order` esistono e ri-validano ogni importo/token server-side.

**Tech Stack:** Flask (Python) backend immutato; vanilla JS (`static/js/app.js`); markup in `templates/_fragments/html_head.html`; i18n in `templates/_fragments/i18n_data.js`; test statici Python (string-assertion su sorgenti JS/HTML) in `test/` eseguiti con pytest.

**Spec di riferimento:** `docs/superpowers/specs/2026-06-08-translate-payment-unified-modal-design.md`

**Nota i18n:** la chiave `tr_pay_label` ("Traduzione libro") esiste già in tutte le 7 lingue di `i18n_data.js` — si riusa quella per la riga del popup. Nessuna modifica i18n necessaria.

---

## File Structure

- **`templates/_fragments/html_head.html`** — markup. Due cambi: (a) aggiungere id alle etichette delle due `pay-line` del `geminiPayModal` per pilotarle dal contesto; (b) pannello T3: rimuovere `cost-estimate` inline col bottone "Buono" e la coupon-row, spostare la stima € nel footer.
- **`static/js/app.js`** — logica. `_payCtx` + `_openPayModalCtx`; generalizzazione di `openPaymentModal`, `renderPaypalGeminiButtons`, `validateVoucherForPayment`, `onPayConfirm`; refactor `startTranslation` + nuovi helper `_loadLlmPaymentConfig` e `_submitTranslation`; rimozione `showCouponTr`/`validateCouponTr`; pulizia `resetWizard`.
- **`test/test_app_js_payment_modal.py`** — aggiornare i test che verificano stringhe hardcoded ora spostate nel contesto.
- **`test/test_app_js_translate_payment.py`** (nuovo) — test sul flusso traduzione che usa il popup parametrico.
- **`test/test_payment_modal_html.py`** — aggiungere check sugli id delle etichette riga; verificare rimozione coupon-row da T3.

---

## Task 1: Markup popup — righe pilotabili dal contesto

**Files:**
- Modify: `templates/_fragments/html_head.html:976-979`
- Test: `test/test_payment_modal_html.py`

- [ ] **Step 1: Aggiungere il test (red)**

In `test/test_payment_modal_html.py`, in fondo al file, aggiungere:

```python
def test_pay_line_labels_have_ids():
    """Le etichette delle pay-line devono avere id per il rendering dal contesto."""
    assert 'id="payLineGeminiLabel"' in HTML
    assert 'id="payLineLlmLabel"' in HTML
```

- [ ] **Step 2: Eseguire il test e verificarne il fallimento**

Run: `python -m pytest test/test_payment_modal_html.py::test_pay_line_labels_have_ids -v`
Expected: FAIL (id non presenti)

- [ ] **Step 3: Modificare il markup**

In `templates/_fragments/html_head.html`, sostituire le righe 976-979:

```html
          <div class="pay-line"><span data-t="pay_premium_voices">Voci PREMIUM</span>
               <span id="payLineGemini">&mdash;</span></div>
          <div class="pay-line"><span data-t="pay_text_ai_optimization">Ottimizzazione testo AI</span>
               <span id="payLineLlm">&mdash;</span></div>
```

con (aggiunta dei soli id alle etichette, testo e data-t invariati):

```html
          <div class="pay-line"><span id="payLineGeminiLabel" data-t="pay_premium_voices">Voci PREMIUM</span>
               <span id="payLineGemini">&mdash;</span></div>
          <div class="pay-line"><span id="payLineLlmLabel" data-t="pay_text_ai_optimization">Ottimizzazione testo AI</span>
               <span id="payLineLlm">&mdash;</span></div>
```

- [ ] **Step 4: Eseguire il test e verificarne il successo**

Run: `python -m pytest test/test_payment_modal_html.py -v`
Expected: PASS (tutti i test del file, inclusi quelli esistenti)

- [ ] **Step 5: Commit**

```bash
git add templates/_fragments/html_head.html test/test_payment_modal_html.py
git commit -m "feat(pay-modal): id sulle etichette pay-line per rendering dal contesto"
```

---

## Task 2: `_payCtx` + `_openPayModalCtx`, e Gemini come primo chiamante

**Files:**
- Modify: `static/js/app.js:1253-1319` (blocco `_payState` + `openPaymentModal`)
- Test: `test/test_app_js_payment_modal.py`

- [ ] **Step 1: Aggiungere i test (red)**

In `test/test_app_js_payment_modal.py`, in fondo al file, aggiungere:

```python
def test_pay_ctx_object_present():
    assert "_payCtx" in APP


def test_open_pay_modal_ctx_function():
    assert "function _openPayModalCtx" in APP


def test_gemini_builder_sets_endpoint_and_purpose():
    """openPaymentModal costruisce il contesto Gemini con endpoint e purpose."""
    start = APP.find("function openPaymentModal")
    assert start >= 0
    snippet = APP[start:start + 1500]
    assert "/api/paypal_create_order_gemini" in snippet
    assert "voucherPurpose:'gemini'" in snippet or 'voucherPurpose: "gemini"' in snippet \
        or "voucherPurpose: 'gemini'" in snippet
    assert "_openPayModalCtx" in snippet
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_app_js_payment_modal.py::test_open_pay_modal_ctx_function test/test_app_js_payment_modal.py::test_gemini_builder_sets_endpoint_and_purpose -v`
Expected: FAIL

- [ ] **Step 3: Implementare `_payCtx` e `_openPayModalCtx`, riscrivere `openPaymentModal`**

In `static/js/app.js`, sostituire il blocco da riga 1253 (`// ═══ PAYMENT MODAL (combined cost) ═══`) fino alla fine di `openPaymentModal` (riga 1319), ovvero:

```js
// ═══════════════════ PAYMENT MODAL (combined cost) ═══════════════════
let _payState = { total: 0, gemini: 0, llm: 0, token: null, method: null };
let _generatingModal = false;
```
… e la funzione `openPaymentModal(estimate)` (1299-1319), con:

```js
// ═══════════════════ PAYMENT MODAL (parametrico) ═══════════════════
// _payState: stato runtime del popup. _payCtx: comportamento del flusso corrente.
// Il campo `gemini` è letto dal flusso di generazione premium (stima rimborso):
// va preservato — vale 0 per i flussi non-premium (es. traduzione).
let _payState = { total: 0, gemini: 0, token: null, method: null };
let _payCtx = null;
let _generatingModal = false;

// Apre il popup geminiPayModal parametrizzato da un contesto:
//   lines: [{labelKey, amount}]  (1 o 2 righe; le righe in eccesso vengono nascoste)
//   total: number
//   geminiAmount?: number  (importo premium per la stima rimborso; default 0)
//   voucherPurpose: string  (passato a /api/voucher_validate, solo audit)
//   paypal: { endpoint, buildBody:()=>({...}) }
//   onConfirm: (token)=>void
function _openPayModalCtx(ctx) {
  _payCtx = ctx;
  _payState = { total: ctx.total, gemini: ctx.geminiAmount || 0, token: null, method: null };
  // Mappa fissa ctx.lines[i] -> (etichetta, importo) nel markup.
  const rowMap = [
    { labelId: 'payLineGeminiLabel', amountId: 'payLineGemini' },
    { labelId: 'payLineLlmLabel', amountId: 'payLineLlm' },
  ];
  rowMap.forEach((ids, i) => {
    const line = ctx.lines[i];
    const amtEl = document.getElementById(ids.amountId);
    const labEl = document.getElementById(ids.labelId);
    const rowEl = amtEl ? amtEl.closest('.pay-line') : null;
    if (line) {
      if (labEl) {
        labEl.setAttribute('data-t', line.labelKey);
        labEl.textContent = (typeof t === 'function') ? t(line.labelKey) : line.labelKey;
      }
      if (amtEl) amtEl.textContent = (line.amount > 0) ? `€${line.amount.toFixed(2)}` : '—';
      if (rowEl) rowEl.style.display = '';
    } else {
      if (rowEl) rowEl.style.display = 'none';
    }
  });
  const tot = document.getElementById('payModalTotal');
  if (tot) tot.textContent = `€${ctx.total.toFixed(2)}`;
  const vErr = document.getElementById('payVoucherError');
  if (vErr) { vErr.textContent = ''; vErr.style.color = ''; }
  const pErr = document.getElementById('payPaypalError');
  if (pErr) pErr.textContent = '';
  const btn = document.getElementById('btnPayConfirm');
  if (btn) btn.disabled = true;
  const vc = document.getElementById('geminiPayVoucherCode'); if (vc) vc.value = '';
  const ve = document.getElementById('geminiPayVoucherEmail');
  if (ve && typeof lastVoucherEmail === 'string') ve.value = lastVoucherEmail;
  switchPayTab('voucher');
  const modal = document.getElementById('geminiPayModal');
  if (modal) modal.hidden = false;
}

// Chiamante Gemini: costruisce il contesto e apre il popup.
function openPaymentModal(estimate) {
  _openPayModalCtx({
    lines: [
      { labelKey: 'pay_premium_voices', amount: estimate.gemini_eur },
      { labelKey: 'pay_text_ai_optimization', amount: estimate.llm_eur },
    ],
    total: estimate.total_eur,
    geminiAmount: estimate.gemini_eur,
    voucherPurpose: 'gemini',
    paypal: {
      endpoint: '/api/paypal_create_order_gemini',
      buildBody: () => {
        const _selLangEl = (wizardState.audioTab === 'premium') ? document.getElementById('vlPremium') : document.getElementById('vl');
        const _selLang = (_selLangEl && _selLangEl.value) || cl || '';
        return { job_id: jobId, voice_id: (typeof getCurrentVoiceId === 'function') ? getCurrentVoiceId() : '', selected_chapters: (typeof _getSelectedChapterIndexes === 'function') ? _getSelectedChapterIndexes() : [], ai_opt_enabled: !!document.getElementById('aiToggle')?.checked, rate: document.getElementById('vr')?.value || '+0%', lang: _selLang, amount_eur: _payState.total };
      },
    },
    onConfirm: (token) => startCombinedGeneration(token),
  });
}
```

- [ ] **Step 4: Eseguire i test e verificarne il successo**

Run: `python -m pytest test/test_app_js_payment_modal.py::test_open_pay_modal_ctx_function test/test_app_js_payment_modal.py::test_gemini_builder_sets_endpoint_and_purpose test/test_app_js_payment_modal.py::test_pay_ctx_object_present -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js test/test_app_js_payment_modal.py
git commit -m "refactor(pay-modal): contesto _payCtx + _openPayModalCtx, Gemini come chiamante"
```

---

## Task 3: Generalizzare PayPal, voucher e conferma per leggere dal contesto

**Files:**
- Modify: `static/js/app.js:1329-1361` (`renderPaypalGeminiButtons`), `1377-1417` (`validateVoucherForPayment`), `1419-1423` (`onPayConfirm`)
- Test: `test/test_app_js_payment_modal.py`

- [ ] **Step 1: Aggiornare i test che verificano stringhe ora spostate nel contesto (red)**

In `test/test_app_js_payment_modal.py`:

Sostituire `test_voucher_validate_called_with_purpose_gemini` (righe 28-30) con:

```python
def test_voucher_validate_uses_context_purpose():
    """validateVoucherForPayment passa il purpose dal contesto, non hardcoded."""
    start = APP.find("function validateVoucherForPayment")
    assert start >= 0
    snippet = APP[start:start + 2000]
    assert "_payCtx.voucherPurpose" in snippet
```

Sostituire `test_paypal_gemini_uses_dedicated_endpoint` (righe 56-62) con:

```python
def test_paypal_create_order_endpoint_from_context():
    """renderPaypalGeminiButtons usa l'endpoint dal contesto; la capture resta condivisa."""
    start = APP.find("function renderPaypalGeminiButtons")
    assert start >= 0
    snippet = APP[start:start + 4000]
    assert "_payCtx.paypal.endpoint" in snippet
    assert "_payCtx.paypal.buildBody" in snippet
    assert "/api/paypal_capture_order" in snippet


def test_gemini_create_endpoint_lives_in_builder():
    """L'endpoint create-order Gemini resta referenziato in openPaymentModal."""
    start = APP.find("function openPaymentModal")
    snippet = APP[start:start + 1500]
    assert "/api/paypal_create_order_gemini" in snippet
```

Aggiornare `test_paypal_capture_token_no_orderid_fallback` (righe 89-99): resta valido (controlla `renderPaypalGeminiButtons`), nessuna modifica.

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_app_js_payment_modal.py -v`
Expected: FAIL su `test_voucher_validate_uses_context_purpose` e `test_paypal_create_order_endpoint_from_context`

- [ ] **Step 3: Generalizzare `renderPaypalGeminiButtons` (createOrder)**

In `static/js/app.js`, dentro `renderPaypalGeminiButtons`, sostituire la `createOrder` (righe 1339-1347):

```js
    createOrder:async function(){
      // Lingua UI: deve combaciare con quella usata in /api/combined_estimate
      // altrimenti il server-side amount check rifiuta l'ordine.
      const _selLangEl=(wizardState.audioTab==='premium')?document.getElementById('vlPremium'):document.getElementById('vl');
      const _selLang=(_selLangEl&&_selLangEl.value)||cl||'';
      const body={job_id:jobId,voice_id:(typeof getCurrentVoiceId==='function')?getCurrentVoiceId():'',selected_chapters:(typeof _getSelectedChapterIndexes==='function')?_getSelectedChapterIndexes():[],ai_opt_enabled:!!document.getElementById('aiToggle')?.checked,rate:document.getElementById('vr')?.value||'+0%',lang:_selLang,amount_eur:_payState.total};
      const r=await fetch('/api/paypal_create_order_gemini',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const d=await r.json();if(!r.ok)throw new Error(d.error||'create failed');return d.order_id;
    },
```

con:

```js
    createOrder:async function(){
      // Endpoint e body dal contesto del flusso corrente (_payCtx). Il server
      // ricalcola l'importo: il body è autoritativo solo per i parametri, non
      // per l'importo da addebitare.
      const _ep=(_payCtx&&_payCtx.paypal&&_payCtx.paypal.endpoint)||'/api/paypal_create_order_gemini';
      const _body=(_payCtx&&_payCtx.paypal&&typeof _payCtx.paypal.buildBody==='function')?_payCtx.paypal.buildBody():{job_id:jobId};
      const r=await fetch(_ep,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(_body)});
      const d=await r.json();if(!r.ok)throw new Error(d.error||'create failed');return d.order_id;
    },
```

- [ ] **Step 4: Generalizzare `validateVoucherForPayment` (purpose)**

In `static/js/app.js`, dentro `validateVoucherForPayment`, sostituire il body della fetch (riga 1392):

```js
      body: JSON.stringify({ code, email, purpose: 'gemini', amount_eur: _payState.total }),
```

con:

```js
      body: JSON.stringify({ code, email, purpose: (_payCtx && _payCtx.voucherPurpose) || 'gemini', amount_eur: _payState.total }),
```

- [ ] **Step 5: Generalizzare `onPayConfirm` (callback dal contesto)**

In `static/js/app.js`, sostituire `onPayConfirm` (righe 1419-1423):

```js
function onPayConfirm() {
  if (!_payState.token) return;
  closePaymentModal();
  startCombinedGeneration(_payState.token);
}
```

con:

```js
function onPayConfirm() {
  if (!_payState.token) return;
  const _cb = _payCtx && _payCtx.onConfirm;
  const _tok = _payState.token;
  closePaymentModal();
  if (typeof _cb === 'function') _cb(_tok);
}
```

- [ ] **Step 6: Eseguire i test e verificarne il successo**

Run: `python -m pytest test/test_app_js_payment_modal.py -v`
Expected: PASS (tutti)

- [ ] **Step 7: Commit**

```bash
git add static/js/app.js test/test_app_js_payment_modal.py
git commit -m "refactor(pay-modal): PayPal/voucher/conferma leggono dal contesto _payCtx"
```

---

## Task 4: Flusso traduzione usa il popup parametrico

**Files:**
- Modify: `static/js/app.js:1982-2028` (`startTranslation`), rimozione `showCouponTr`/`validateCouponTr` (1961-1980)
- Test: `test/test_app_js_translate_payment.py` (nuovo)

- [ ] **Step 1: Scrivere i test (red)**

Creare `test/test_app_js_translate_payment.py`:

```python
from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "static" / "js" / "app.js").read_text(encoding="utf-8")


def test_start_translation_opens_param_modal():
    """startTranslation apre il popup parametrico con il contesto traduzione."""
    start = APP.find("function startTranslation")
    assert start >= 0
    snippet = APP[start:start + 2500]
    assert "_openPayModalCtx" in snippet
    assert "/api/paypal_create_order_translate" in snippet
    assert "voucherPurpose:'translate'" in snippet or "voucherPurpose: 'translate'" in snippet


def test_translate_modal_uses_translation_label():
    start = APP.find("function startTranslation")
    snippet = APP[start:start + 2500]
    assert "tr_pay_label" in snippet


def test_translate_submit_helper_present():
    assert "function _submitTranslation" in APP


def test_translate_no_longer_uses_legacy_show_payment_modal():
    """Il flusso traduzione non deve più usare _showPaymentModal (popup voucher-only)."""
    start = APP.find("function startTranslation")
    end = APP.find("function _trAutofillEmailLate")
    assert start >= 0 and end > start
    assert "_showPaymentModal" not in APP[start:end]


def test_inline_translate_coupon_functions_removed():
    assert "function validateCouponTr" not in APP
    assert "function showCouponTr" not in APP


def test_translate_loads_paypal_config():
    """Prima di aprire il popup, il flusso traduzione carica la config PayPal."""
    assert "function _loadLlmPaymentConfig" in APP
    start = APP.find("function startTranslation")
    snippet = APP[start:start + 2500]
    assert "_loadLlmPaymentConfig" in snippet
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_app_js_translate_payment.py -v`
Expected: FAIL

- [ ] **Step 3: Aggiungere l'helper `_loadLlmPaymentConfig`**

In `static/js/app.js`, subito dopo la definizione di `_loadPaypalSdk` (cioè dopo riga 2376, prima di `_showPaymentModal`), inserire:

```js
// Carica in llmConfig i parametri di pagamento (rate, soglia, PayPal) da
// /api/llm_available. Idempotente, best-effort: usato dai flussi che non
// passano da /api/combined_estimate (es. traduzione). Fallimento silenzioso.
async function _loadLlmPaymentConfig(){
  try{
    const cfg=await fetch('/api/llm_available').then(r=>r.json());
    llmConfig.rate=cfg.rate_eur_per_mchar||1.1;
    llmConfig.threshold=cfg.free_threshold_eur||0.5;
    llmConfig.bonus=cfg.voucher_bonus_percent||10;
    llmConfig.expiry=cfg.voucher_expiry_days||180;
    llmConfig.paypalClientId=cfg.paypal_client_id||"";
    llmConfig.paypalMode=cfg.paypal_mode||"sandbox";
    llmConfig.paypalAvailable=!!cfg.paypal_available;
  }catch(e){/* best-effort */}
}
```

- [ ] **Step 4: Riscrivere `startTranslation` e aggiungere `_submitTranslation`**

In `static/js/app.js`, sostituire l'intera funzione `startTranslation` (righe 1982-2028) con:

```js
async function startTranslation(){
  if(!jobId||generating||window._trStarting)return;
  window._trStarting=true;
  try{
    const src=document.getElementById('trSrcLang').value;
    const dst=document.getElementById('trDstLang').value;
    if(src===dst){showErr('trErr',t('tr_err_same_lang'));return}
    _rememberLastLang(dst);
    const est=await trUpdateEstimate();
    if(!est)return;
    if(est.requires_payment&&!trPaymentToken){
      // Pagamento unico (traduzione + eventuale ottimizzazione) col popup
      // premium parametrico: voucher + PayPal. Caricare prima la config PayPal.
      await _loadLlmPaymentConfig();
      _openPayModalCtx({
        lines:[{labelKey:'tr_pay_label',amount:est.due_eur}],
        total:est.due_eur,
        voucherPurpose:'translate',
        paypal:{
          endpoint:'/api/paypal_create_order_translate',
          buildBody:()=>({job_id:jobId,target_lang:dst,
            optimize:document.getElementById('aiToggleTr').checked,
            selected_chapters:_getSelectedChapterIndexes(),
            amount_eur:est.due_eur}),
        },
        onConfirm:(token)=>{trPaymentToken=token;_submitTranslation(token,src,dst);},
      });
      return; // l'invio prosegue in onConfirm dopo la conferma del popup
    }
    _submitTranslation(trPaymentToken,src,dst);
  }finally{window._trStarting=false}
}

// Invia POST /api/translate e avvia l'ascolto del progress. payToken può essere
// null (traduzione gratis sotto soglia). Guardia anti doppio-avvio su generating.
async function _submitTranslation(payToken,src,dst){
  if(generating)return;
  const payload={
    job_id:jobId,
    source_lang:src,target_lang:dst,
    output_format:document.getElementById('trFormat').value,
    output_name:(document.getElementById('trOutName').value||'').trim(),
    optimize:document.getElementById('aiToggleTr').checked,
    selected_chapters:_getSelectedChapterIndexes(),
    batch:false,lang:cl
  };
  if(payToken)payload.payment_token=payToken;
  try{
    const r=await fetch('/api/translate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    if(d.error){showErr('trErr',d.error);return}
    document.getElementById('trErr').innerHTML='';
    const _bcR=document.getElementById('btnCancelTr');
    if(_bcR){const _spR=_bcR.querySelector('span');if(_spR)_spR.textContent=t('tr_btn_cancel')||'Cancel';_bcR.onclick=cancelTranslation;}
    generating=true;
    lockUI();
    goToStep(4);
    const area=document.getElementById('emailLateAreaTr');if(area)area.classList.add('visible');
    _trAutofillEmailLate();
    _listenTranslateProgress();
  }catch(e){showErr('trErr','Error: '+e.message)}
}
```

- [ ] **Step 5: Rimuovere `showCouponTr` e `validateCouponTr`**

In `static/js/app.js`, eliminare le due funzioni (righe 1961-1980):

```js
function showCouponTr(){
  const row=document.getElementById('couponRowTr');
  if(row)row.classList.toggle('visible');
}

async function validateCouponTr(){
  const code=(document.getElementById('couponCodeTr').value||'').trim().toUpperCase();
  const email=(document.getElementById('couponEmailTr').value||'').trim();
  if(!code||!email)return;
  const result=document.getElementById('couponResultTr');
  if(result){result.innerHTML='<div class="sp"></div>';result.className='coupon-result'}
  try{
    const r=await fetch('/api/voucher_validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:code,email:email})});
    const d=await r.json();
    if(d.error){if(result){result.textContent=d.error;result.className='coupon-result error'}return}
    lastVoucherEmail=email;try{localStorage.setItem('abm_v_email',email)}catch(e){}
    if(result){result.textContent='✅ '+(t('pay_voucher_valid')||'Voucher valid!');result.className='coupon-result success'}
    trPaymentToken=d.payment_token;
  }catch(e){if(result){result.textContent='Error: '+e.message;result.className='coupon-result error'}}
}
```

Eliminarle completamente (non lasciare stub).

- [ ] **Step 6: Eseguire i test e verificarne il successo**

Run: `python -m pytest test/test_app_js_translate_payment.py test/test_app_js_payment_modal.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add static/js/app.js test/test_app_js_translate_payment.py
git commit -m "feat(translate): pagamento unico col popup premium parametrico (voucher+PayPal)"
```

---

## Task 5: Pannello T3 — rimuovere coupon inline, spostare la stima nel footer

**Files:**
- Modify: `templates/_fragments/html_head.html:307-356` (card AI + footer T3)
- Modify: `static/js/app.js:3900-3917` (reset wizard traduzione)
- Test: `test/test_payment_modal_html.py`, `test/test_app_js_translate_payment.py`

- [ ] **Step 1: Aggiungere i test (red)**

In `test/test_payment_modal_html.py`, in fondo:

```python
def test_t3_coupon_inline_removed():
    """Il pannello T3 non deve più contenere il pagamento ottimizzazione inline."""
    assert 'id="btnApplyCouponTr"' not in HTML
    assert 'id="couponRowTr"' not in HTML
    assert 'id="couponCodeTr"' not in HTML
    assert 'id="couponEmailTr"' not in HTML
    assert 'id="btnValidateCouponTr"' not in HTML


def test_t3_cost_estimate_in_footer():
    """La stima costo resta presente (spostata vicino ad Avvia traduzione)."""
    assert 'id="costAmountTr"' in HTML
    assert 'id="costDetailTr"' in HTML
    assert 'id="btnStartTranslate"' in HTML
```

In `test/test_app_js_translate_payment.py`, in fondo:

```python
def test_reset_wizard_no_dangling_coupon_refs():
    """Il reset traduzione non deve più referenziare gli elementi coupon rimossi."""
    assert "couponCodeTr" not in APP
    assert "couponEmailTr" not in APP
    assert "couponResultTr" not in APP
    assert "couponRowTr" not in APP
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_payment_modal_html.py::test_t3_coupon_inline_removed test/test_app_js_translate_payment.py::test_reset_wizard_no_dangling_coupon_refs -v`
Expected: FAIL

- [ ] **Step 3: Modificare il markup della card AI in T3**

In `templates/_fragments/html_head.html`, sostituire il blocco righe 307-340 (da `<div class="ai-opt-card" id="aiOptCardTr">` fino a `</div>` di chiusura card, inclusi `cost-estimate`, coupon-row e `couponResultTr`):

```html
      <div class="ai-opt-card" id="aiOptCardTr">
        <div class="toggle-row">
          <div>
            <div class="toggle-label">
              <svg class="ai-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l2.4 7.2h7.6l-6 4.8 2.4 7.2-6.4-4.8-6.4 4.8 2.4-7.2-6-4.8h7.6z"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" opacity="0.3"/></svg>
              <span data-t="lbl_ai_opt"></span>
            </div>
            <div class="toggle-desc" data-t="ai_opt_desc"></div>
          </div>
          <label class="toggle-switch" aria-label="Attiva ottimizzazione AI">
            <input type="checkbox" id="aiToggleTr" onchange="trUpdateEstimate()">
            <span class="toggle-slider"></span>
          </label>
        </div>
        <div class="cost-estimate visible" id="costEstimateTr">
          <div style="flex:1">
            <div class="cost-amount" id="costAmountTr">—</div>
            <div class="cost-detail" id="costDetailTr"></div>
          </div>
          <button class="btn btn-outline btn-sm" id="btnApplyCouponTr" onclick="showCouponTr()">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><circle cx="8" cy="11.5" r="1.5"/><circle cx="16" cy="11.5" r="1.5"/></svg>
            <span data-t="pay_tab_voucher"></span>
          </button>
        </div>
        <div class="coupon-row" id="couponRowTr">
          <input type="text" id="couponCodeTr" placeholder="XXXX-XXXX-XXXX" aria-label="Codice coupon">
          <input type="email" id="couponEmailTr" placeholder="Email associata" aria-label="Email buono">
          <button class="btn btn-p btn-sm" id="btnValidateCouponTr" onclick="validateCouponTr()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
            <span data-t="pay_voucher_submit"></span>
          </button>
        </div>
        <div class="coupon-result" id="couponResultTr"></div>
      </div>
```

con (card con solo toggle, niente più costo/coupon inline):

```html
      <div class="ai-opt-card" id="aiOptCardTr">
        <div class="toggle-row">
          <div>
            <div class="toggle-label">
              <svg class="ai-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l2.4 7.2h7.6l-6 4.8 2.4 7.2-6.4-4.8-6.4 4.8 2.4-7.2-6-4.8h7.6z"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" opacity="0.3"/></svg>
              <span data-t="lbl_ai_opt"></span>
            </div>
            <div class="toggle-desc" data-t="ai_opt_desc"></div>
          </div>
          <label class="toggle-switch" aria-label="Attiva ottimizzazione AI">
            <input type="checkbox" id="aiToggleTr" onchange="trUpdateEstimate()">
            <span class="toggle-slider"></span>
          </label>
        </div>
      </div>
```

- [ ] **Step 4: Spostare la stima costo nel footer T3**

In `templates/_fragments/html_head.html`, sostituire il `panel-footer` di T3 (righe 344-356):

```html
      <div class="panel-footer">
        <div class="left">
          <button class="btn btn-g" id="btnBackT3" onclick="goToStep(2)">
            <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="18" height="18"><polyline points="15 18 9 12 15 6"/></svg>
            <span data-t="btn_back"></span>
          </button>
        </div>
        <div class="right">
          <button class="btn btn-p btn-lg" id="btnStartTranslate" onclick="startTranslation()">
            <span data-t="tr_btn_start"></span>
          </button>
        </div>
      </div>
```

con (aggiunta della stima costo a sinistra del bottone di avvio):

```html
      <div class="panel-footer">
        <div class="left">
          <button class="btn btn-g" id="btnBackT3" onclick="goToStep(2)">
            <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="18" height="18"><polyline points="15 18 9 12 15 6"/></svg>
            <span data-t="btn_back"></span>
          </button>
        </div>
        <div class="right">
          <div class="cost-estimate visible" id="costEstimateTr" style="margin:0 12px 0 0">
            <div style="flex:1">
              <div class="cost-amount" id="costAmountTr">—</div>
              <div class="cost-detail" id="costDetailTr"></div>
            </div>
          </div>
          <button class="btn btn-p btn-lg" id="btnStartTranslate" onclick="startTranslation()">
            <span data-t="tr_btn_start"></span>
          </button>
        </div>
      </div>
```

- [ ] **Step 5: Pulire il reset wizard traduzione**

In `static/js/app.js`, sostituire le righe 3903-3906:

```js
  const couponCodeTr=document.getElementById('couponCodeTr');if(couponCodeTr)couponCodeTr.value='';
  const couponEmailTr=document.getElementById('couponEmailTr');if(couponEmailTr)couponEmailTr.value='';
  const couponResultTr=document.getElementById('couponResultTr');if(couponResultTr){couponResultTr.innerHTML='';couponResultTr.className='coupon-result';}
  const couponRowTr=document.getElementById('couponRowTr');if(couponRowTr)couponRowTr.classList.remove('visible');
```

con:

```js
  trPaymentToken=null;
```

- [ ] **Step 6: Eseguire i test e verificarne il successo**

Run: `python -m pytest test/test_payment_modal_html.py test/test_app_js_translate_payment.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add templates/_fragments/html_head.html static/js/app.js test/test_payment_modal_html.py test/test_app_js_translate_payment.py
git commit -m "feat(translate): rimuove coupon inline da T3, sposta la stima nel footer"
```

---

## Task 6: Verifica completa (regressione + manuale)

**Files:** nessuna modifica (solo verifica)

- [ ] **Step 1: Eseguire l'intera suite test**

Run: `python -m pytest test/ -q`
Expected: PASS (nessuna regressione). In particolare verde su: `test_app_js_payment_modal.py`, `test_app_js_translate_payment.py`, `test_payment_modal_html.py`, `test_translate_endpoints.py`, `test_payment_token_consumption.py`, `test_paypal_create_gemini.py`, `test_voucher_validate_purpose.py`.

- [ ] **Step 2: Grep di sicurezza per riferimenti orfani**

Run: `grep -nE "showCouponTr|validateCouponTr|couponRowTr|couponCodeTr|couponEmailTr|couponResultTr|btnApplyCouponTr|btnValidateCouponTr" static/js/app.js templates/_fragments/html_head.html`
Expected: nessun output (tutti i riferimenti rimossi).

- [ ] **Step 3: Verifica manuale nel browser**

Avviare l'app come da skill `run` del progetto. Con un libro caricato e capitoli selezionati che superano la soglia (es. selezione ampia):

1. Andare in "Traduci" → pannello T3. Verificare: nessun bottone "Buono" nella card AI; la stima € è nel footer accanto ad "Avvia traduzione"; il toggle ottimizzazione AI aggiorna la cifra.
2. Click "Avvia traduzione" → si apre il popup premium con una sola riga "Traduzione libro" e il totale; tab Buono e PayPal presenti.
3. Tab Buono: inserire un voucher valido → "Conferma" si abilita → conferma → la traduzione parte (step T4 progress).
4. (Se PayPal configurato) Tab PayPal: l'ordine viene creato via `/api/paypal_create_order_translate`; dopo l'approvazione "Conferma" si abilita.
5. Regressione voci premium: generare un audiolibro con voce premium a pagamento → il popup mostra ancora le due righe "Voci PREMIUM" / "Ottimizzazione testo AI" e funziona come prima.

- [ ] **Step 4: Commit finale (se servono fix dalla verifica)**

Solo se la verifica manuale ha richiesto correzioni:

```bash
git add -A
git commit -m "fix(translate): correzioni da verifica manuale popup pagamento"
```

---

## Self-Review (eseguita)

**Spec coverage:**
- Rimozione pagamento ottimizzazione inline + bottone Buono da T3 → Task 5. ✓
- Stima € spostata nel footer → Task 5. ✓
- Card AI con solo toggle → Task 5. ✓
- Popup unico al click "Avvia traduzione" (voucher + PayPal) → Task 4. ✓
- Una sola riga "Traduzione" nel popup → Task 4 (labelKey `tr_pay_label`) + Task 1/2 (rendering righe dal contesto). ✓
- Parametrizzazione `geminiPayModal` con contesto → Task 2-3. ✓
- `voucherPurpose:'translate'`, endpoint `/api/paypal_create_order_translate` → Task 4. ✓
- Caricamento config PayPal prima del popup → Task 4 (`_loadLlmPaymentConfig`). ✓
- `_showPaymentModal` non più usato dalla traduzione, resta per le Standard → Task 4 (test dedicato) — la funzione `_showPaymentModal` NON viene rimossa. ✓
- Backend invariato → nessun task backend. ✓
- Accorgimenti sicurezza: `_payCtx` impostato per intero in `_openPayModalCtx` prima di mostrare il modal; PayPal `.close()` su re-render preservato (Task 3 non lo tocca); guardie `window._trStarting` + `if(generating)return` in `_submitTranslation`; `closePaymentModal()` prima di `onConfirm`. ✓

**Placeholder scan:** nessun TODO/TBD; ogni step di codice mostra il codice completo. ✓

**Type/naming consistency:** `_payCtx`, `_openPayModalCtx`, `_loadLlmPaymentConfig`, `_submitTranslation(payToken,src,dst)`, `renderPaypalGeminiButtons` (nome invariato), `onPayConfirm`, `validateVoucherForPayment` coerenti tra i task. Gli id markup `payLineGeminiLabel`/`payLineLlmLabel` introdotti in Task 1 e usati in Task 2. ✓
