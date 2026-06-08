# Pagamento traduzione unificato nel popup premium

**Data:** 2026-06-08
**Branch:** TRADUZ
**Stato:** design approvato, pronto per il piano

## Problema

Nel percorso traduzione esiste oggi un pagamento separato dell'ottimizzazione
AI tramite voucher, gestito inline nel pannello T3:

- Una card "Ottimizzazione AI" con bottone **"Buono"** (`btnApplyCouponTr` →
  `showCouponTr`) e una coupon-row inline (`couponCodeTr`, `couponEmailTr`,
  `btnValidateCouponTr`) che valida il voucher e setta `trPaymentToken`.
- Il pagamento della traduzione vera e propria avviene poi al click "Avvia
  traduzione", con un secondo popup (`_showPaymentModal` → `payModal`) che è
  **voucher-only** (PayPal disattivato nel codice).

Questo è sbagliato per due motivi:

1. L'ottimizzazione AI, quando attiva, è già conteggiata nella stima traduzione
   (`payment._estimate_translation_cost_eur(optimize=True)` somma il rate LLM):
   non deve esistere un pagamento separato per essa.
2. Il popup usato dalla traduzione non offre PayPal, mentre quello delle voci
   premium sì.

## Obiettivo

Nel percorso traduzione deve esserci **un solo pagamento**, al click **"Avvia
traduzione"**, che copre traduzione + eventuale ottimizzazione AI integrata,
usando **lo stesso popup delle voci premium** (`geminiPayModal`, con tab Buono +
PayPal). Nessun pagamento dell'ottimizzazione separato.

## Decisioni di design

- **Stima costo (€) nel pannello T3:** esce dalla card AI e si sposta nel footer
  del pannello, accanto al bottone "Avvia traduzione", come informazione di sola
  lettura. La card AI mantiene solo il toggle `aiToggleTr`, che continua a
  chiamare `trUpdateEstimate()` per aggiornare l'importo mostrato nel footer.
- **Dettaglio importo nel popup:** una sola riga **"Traduzione"** col totale (il
  floor di 1,50 € sul totale rende ingannevole separare un addendo ottimizzazione,
  ed è comunque un'unica chiamata LLM che fa traduzione+ottimizzazione insieme).
- **Riuso tecnico del popup:** si parametrizza `geminiPayModal` con un oggetto
  contesto, anziché duplicare un popup gemello. Un solo popup, due chiamanti.

## Modifiche

### 1. Pannello T3 (`templates/_fragments/html_head.html`)

Rimuovere dalla card `aiOptCardTr`:

- Il blocco `cost-estimate` (`costEstimateTr`) col bottone "Buono"
  (`btnApplyCouponTr`).
- La coupon-row inline (`couponRowTr`, `couponCodeTr`, `couponEmailTr`,
  `btnValidateCouponTr`) e `couponResultTr`.

La card resta con il solo toggle `aiToggleTr`.

Spostare la stima costo nel footer del pannello (vicino a `btnStartTranslate`):
nuovi elementi `costAmountTr` / `costDetailTr` di sola lettura. `trUpdateEstimate()`
continua ad aggiornarli.

### 2. Markup popup (`geminiPayModal`)

Le due righe fisse `payLineGemini` ("Voci PREMIUM") e `payLineLlm`
("Ottimizzazione testo AI") diventano righe **generiche pilotate dal contesto**:

- Ogni riga ha un `<span>` etichetta (label, popolata da una chiave i18n del
  contesto) e un `<span>` importo.
- Le righe non usate dal contesto corrente vengono nascoste.

Per la traduzione si mostra **una sola riga "Traduzione"** col totale; la seconda
riga resta nascosta. Per Gemini, comportamento invariato (due righe).

Nuova chiave i18n: `tr_pay_line` ("Traduzione") in tutte le lingue presenti in
`i18n_data.js`.

### 3. JS popup parametrico (`static/js/app.js`)

Introdurre un oggetto contesto a livello di modulo:

```js
let _payCtx = {
  lines: [{ labelKey, amount }],   // 1+ righe; traduzione → 1 sola riga
  voucherPurpose: 'gemini' | 'translate',
  paypal: { endpoint, buildBody: () => ({...}) },
  onConfirm: (token) => { ... },
};
```

`_payState` resta lo stato runtime ({ total, token, method }) per non rompere il
flusso Gemini; `_payCtx` aggiunge il comportamento parametrico.

Generalizzare le funzioni esistenti a leggere dal contesto:

- **Nuovo `_openPayModalCtx(ctx)`**: imposta `_payCtx` per intero, popola le righe
  (label via chiave i18n, importo), nasconde le righe in eccesso, resetta errori,
  `switchPayTab('voucher')`, mostra il modal. Imposta `_payState.total` dal totale
  del contesto.
- **`openPaymentModal(estimate)`** (chiamante Gemini): costruisce il `_payCtx`
  Gemini (due righe, `voucherPurpose:'gemini'`, endpoint
  `/api/paypal_create_order_gemini`, `onConfirm: startCombinedGeneration`) e chiama
  `_openPayModalCtx`.
- **`renderPaypalGeminiButtons()`**: usa `_payCtx.paypal.endpoint` e
  `_payCtx.paypal.buildBody()` invece dell'endpoint/body Gemini cablati. Continua
  a fare `.close()` dell'istanza precedente prima di ri-renderizzare (anti-bleed).
- **`validateVoucherForPayment()`**: usa `_payCtx.voucherPurpose` e `_payState.total`.
- **`onPayConfirm()`**: chiama `_payCtx.onConfirm(_payState.token)` invece di
  `startCombinedGeneration` cablato. Chiude il modal **prima** di invocare
  `onConfirm` (token già marcato `used`/consumato a valle in modo atomico).

### 4. Flusso traduzione (`static/js/app.js`)

In `startTranslation()`, sostituire il blocco `_showPaymentModal(...)` con
l'apertura di `geminiPayModal` via `_openPayModalCtx`, quando `est.requires_payment`:

1. Caricare la config PayPal in `llmConfig` (fetch `/api/llm_available`, già usato
   altrove) così il tab PayPal funziona.
2. Aprire il popup con `_payCtx` traduzione:
   - `lines: [{ labelKey: 'tr_pay_line', amount: est.due_eur }]`
   - `voucherPurpose: 'translate'`
   - `paypal: { endpoint: '/api/paypal_create_order_translate',
     buildBody: () => ({ job_id: jobId, target_lang: dst, optimize: <toggle>,
     selected_chapters: _getSelectedChapterIndexes(), amount_eur: est.due_eur }) }`
   - `onConfirm: (token) => { trPaymentToken = token; <prosegue il POST
     /api/translate con payment_token, come fa oggi dopo aver ottenuto il token> }`

Rimuovere le funzioni `showCouponTr()` e `validateCouponTr()` e l'uso di
`trPaymentToken` come canale voucher anticipato. `trPaymentToken` resta solo come
slot per il token ottenuto dal popup (riarmato a `null` su cancel/errore, come
oggi).

Il vecchio `_showPaymentModal` (popup `payModal`) **non è più usato dalla
traduzione**; resta intatto per il flusso ottimizzazione delle voci Standard.

### 5. Reset UI (`resetWizard` / cambio job)

Aggiornare il reset che oggi tocca `aiToggleTr` (app.js:3907) e la coupon-row
traduzione: rimuovere i riferimenti agli elementi eliminati (`couponRowTr`,
`couponResultTr`, ecc.).

## Backend: nessuna modifica

Tutti gli endpoint coinvolti esistono e sono già corretti:

- `/api/paypal_create_order_translate` — ricalcola `chars`+`est` server-side, crea
  l'ordine con l'importo del server, ignora `amount_eur` dal client.
- `/api/paypal_capture_order` — riconcilia l'importo realmente catturato
  (`CaptureAmountMismatchError` se non combacia).
- `/api/translate` — ricalcola `est` dai capitoli della propria richiesta e
  consuma il token (PayPal con `used` atomico sotto `_payments_lock`, oppure
  voucher con `_voucher_consume`), esigendo `amount >= due_eur`.

## Sicurezza

Il refactoring è **solo client-side**. Gli importi e i token veicolati dal popup
non sono mai fidati: ogni addebito è ri-derivato e ri-validato server-side.

- `_payCtx.total` / `_payState.total` sono **cosmetici** (disegno del popup e
  anteprima "saldo insufficiente" del voucher). Il server ricalcola sempre `est`
  dai capitoli selezionati.
- Pagare per pochi capitoli e tradurne di più → il consumo in `/api/translate`
  fallisce (`payment_invalid`). Nessun under-charge possibile.
- `purpose` voucher è cosmetico (mai applicato nel consumo); i voucher sono saldo
  generico per design. Nessun indebolimento.
- Rimuovere `validateCouponTr` è un miglioramento: legava il voucher senza
  `amount_eur`; il popup valida con l'importo.

Accorgimenti di **correttezza client** da rispettare nel piano (al peggio causano
un pagamento *rifiutato*, mai un addebito errato):

1. Impostare `_payCtx` **per intero** prima di `_openPayModalCtx`; il bottone
   PayPal fa già `.close()` dell'istanza precedente prima di ri-renderizzare.
2. `onConfirm` cattura i parametri all'apertura del modal; cambi di selezione in
   corso → il server respinge se insufficiente (comportamento già esistente).
3. Mantenere le guardie anti doppio-submit (`window._trStarting`,
   `closePaymentModal()` prima di `onConfirm`).
4. Mantenere `_payState` come stato runtime Gemini e aggiungere `_payCtx` per il
   comportamento, senza rompere il flusso premium.

## Fuori scope

- Modifiche al backend (nessuna necessaria).
- Modifiche al flusso pagamento delle voci premium/standard (solo
  generalizzazione interna, comportamento invariato).
- Modifiche alla formula di pricing della traduzione.
