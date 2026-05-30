# Gemini TTS Premium Tab + Payment Integration — Design

> **Stato:** brainstorming completato, in attesa di approvazione utente prima di passare a `superpowers:writing-plans`.
>
> **Scope:** trasformare il Panel 3 del wizard ("Impostazioni audio") in un tab-panel con sotto-pannello "Voci PREMIUM" per Gemini TTS, calcolare e mostrare la stima costo combinata (Gemini + ottimizzazione testo AI), gestire pagamento upfront (voucher o PayPal) prima dell'avvio della generazione, registrare audit log dei costi stimati vs reali per consentire all'admin di tarare i parametri.
>
> **Out of scope:** modifiche al pipeline di sintesi Gemini (già completato in Plan B), riattivazione PayPal per il flusso LLM (resta solo-voucher), modifiche ai provider Standard (edge-tts, Google Cloud TTS).

---

## 1. Contesto e motivazione

Il modulo `gemini_tts.py` (Plan A) e l'integrazione nel pipeline (Plan B) sono già completati: l'utente può scegliere una voce Gemini dal select unico del Panel 3 e generare un audiolibro. Manca però:

1. **Una UI dedicata** che permetta di scegliere il modello (Flash 2.5 / Flash 3.1), inserire istruzioni di stile, e vedere la stima costo prima di procedere.
2. **Un gating di pagamento** che impedisca all'utente di avviare una generazione Gemini sopra soglia gratuità senza aver coperto il costo tramite voucher o PayPal.
3. **Un meccanismo di audit** per verificare la qualità delle stime e tarare progressivamente i parametri di pricing.

Questo design copre il "Plan C" già menzionato nel piano Plan B come out-of-scope.

## 2. Decisioni di design

### 2.1 Mutua esclusione tab Standard ↔ Premium

Un audiolibro usa una sola voce, quindi una sola engine (edge | google | gemini). I due tab si comportano come due modalità: scegliere una voce in un tab azzera la selezione dell'altro. Lo stato del tab attivo (`wizardState.audioTab`) viene passato al backend in `/api/generate` come fonte di verità per la voce da usare. Le voci Gemini vengono rimosse dal select del tab Standard.

### 2.2 Selettore modello come filtro

Le 60 voci Gemini (30 × 2 modelli) sono divise per modello. Il selettore Modello filtra il select voce mostrando 30 voci alla volta. Vantaggio: l'utente non è sovraccaricato e il prezzo €/minuto può essere mostrato accanto al selettore modello (è una proprietà del modello, non della voce).

### 2.3 Istruzioni di stile come prefisso a ogni chunk

Gemini TTS accetta direttive testuali nel contenuto. Il prefisso `[style: ...]` viene applicato **a ogni chunk** della sintesi (max 300 caratteri). Scelta cambiata rispetto al design iniziale "solo primo chunk di ogni capitolo": l'ottimizzazione costo era trascurabile (~0.003 USD per libro tipico) e produceva uno scollamento percepibile fra preview (sempre con stile) e job finale (stile attivo solo sul ~5% dell'audio, poi sparisce). Applicare lo stile a ogni chunk restituisce un'esperienza coerente con la preview.

### 2.4 Soglia gratuità unica sul totale

Costo Gemini + costo "Ottimizzazione testo AI" sommati; se il totale ≤ `ABM_GEMINI_FREE_THRESHOLD_EUR` (default 0.50€), nessun pagamento richiesto. Sopra soglia, pagamento unico per la somma. Vantaggio: una sola decisione UX (pagare/non pagare), un solo modal, un solo token.

### 2.5 PayPal riattivato solo nel modal Gemini

Il flusso LLM (ottimizzazione testo AI) resta solo-voucher. PayPal viene riattivato esclusivamente nel modal di pagamento Gemini, affiancato al voucher come secondo metodo. Riusa gli endpoint backend esistenti.

### 2.6 Niente riserva, addebito esatto sulla stima

Addebito = stima. In caso di delta (reale vs stimato), l'operatore assorbe (margine 25-35% configurato dà cuscinetto). Per controllo qualità, ogni job Gemini scrive un record audit con `est` vs `actual`. L'admin consulta i log periodicamente e aggiorna i parametri di pricing.

### 2.7 Refund integrale solo su fallimento/cancellazione/crash

Job completato → nessun refund; audit con delta. Errore/cancel → refund integrale del pagato (riusa `_voucher_refund` esistente, emette nuovo voucher con bonus se origine PayPal). Crash/riavvio → recovery startup esteso a Gemini.

### 2.8 Re-estimate triggerata solo su variabili che cambiano il costo

A parità di testo e modello, voci diverse hanno lo stesso costo. Trigger frontend: change tab, change modello, toggle AI optimization, change selezione capitoli. **NON** change voce.

### 2.9 UI utente mai cita provider commerciali

Etichette generiche: "Voci PREMIUM" (mai "Gemini"), "Voci Standard" (mai "edge-tts"/"Google"), "Ottimizzazione testo AI" (mai "DeepSeek"). Eccezione tollerata: nel selettore modello del tab Premium, "Gemini 2.5 Flash TTS" / "Gemini 3.1 Flash TTS" sono mostrati perché ineliminabili come differenziatore tecnico. Nei log admin i nomi provider sono ammessi (UI tecnica per operatore).

### 2.10 Voucher cross-purpose (pool €)

Un voucher è un pool €; nessuna distinzione tra "voucher per LLM" e "voucher per Gemini". Il campo `purpose` viene introdotto solo per tracciabilità nei log, ma il `remaining_eur` è consumabile per qualsiasi purpose. Semplifica UX (un solo tipo di voucher) e contabilità.

## 3. Architettura

### 3.1 UI — Panel 3 ristrutturato

```
<section class="panel" id="panel3">
  <h2 data-t="s2_title"></h2>
  <p class="subtitle" data-t="p3_subtitle"></p>

  <div class="tab-bar" role="tablist">
    <button class="tab active" data-tab="standard" role="tab"
            data-t="tab_voices_standard">Voci Standard (gratis)</button>
    <button class="tab" data-tab="premium" role="tab"
            data-t="tab_voices_premium">★ Voci PREMIUM</button>
  </div>

  <div class="tab-panel active" id="tabStandard" role="tabpanel">
    <!-- form-row lingua/voce (Gemini rimosse), slider velocità, formato, preview -->
  </div>

  <div class="tab-panel" id="tabPremium" role="tabpanel" hidden>
    <div class="form-row">
      <div class="form-group"><label data-t="lbl_lang"></label>
        <select id="vlPremium"></select></div>
      <div class="form-group"><label data-t="lbl_model"></label>
        <select id="vmPremium">
          <option value="flash25">Gemini 2.5 Flash TTS</option>
          <option value="flash31">Gemini 3.1 Flash TTS</option>
        </select>
        <div class="model-rate-hint" id="modelRateHint"></div>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group"><label data-t="lbl_voice"></label>
        <select id="vvPremium"></select></div>
    </div>
    <!-- slider velocità, select formato (riusano markup) -->
    <div class="form-row">
      <div class="form-group" style="flex:1 1 100%">
        <label data-t="lbl_style_instruction"></label>
        <textarea id="geminiStyle" maxlength="300"
                  placeholder="…es. tono calmo, ritmo narrativo lento"></textarea>
        <div class="char-counter"><span id="styleCounter">0</span>/300</div>
      </div>
    </div>
    <div class="cost-preview-box" id="costPreviewBox">
      <div class="cost-label" data-t="cost_estimate_label">Stima costo audiolibro</div>
      <div class="cost-value" id="costPreviewValue">—</div>
      <div class="cost-detail" id="costPreviewDetail"></div>
    </div>
    <!-- preview section (riusa) -->
  </div>

  <div class="panel-footer">
    <!-- back/next condiviso -->
  </div>
</section>
```

### 3.2 Flusso stima costo (frontend)

```
[user action] ──┐
                ├── change tab Standard↔Premium ──┐
                ├── change modello Gemini  ───────┤
                ├── toggle AI optimization ───────┼─► fetch /api/combined_estimate
                └── change selezione capitoli ────┤   (debounced 300ms)
                                                  │   payload: {voice_id, ai_opt, chapters[], style?}
                                                  │   response: {gemini_eur, llm_eur, total_eur,
                                                  │              is_free, breakdown}
                                                  ▼
                                           cache lato JS: {key, total_eur}
                                                  ▼
                                           render costPreviewBox (tab Premium)
                                           render costEstimate (Panel 4, se ai_opt)
```

Cache key = hash di `(model_key, ai_opt, chapter_selection_set)`. Cambio voce → no re-fetch.

### 3.3 Flusso pagamento (al click "Avvia generazione")

```
[btnGenerate click]
   ▼
goToStep(4)? → calcolaTotale()
   ▼
   ├── total ≤ 0.50€ ──► /api/generate (no token) ──► start
   │
   └── total > 0.50€ ──► apri payment modal
                        ├── tab Voucher
                        │   └── /api/voucher_validate {code, email, purpose}
                        │       ├── valid + remaining ≥ total ──► token = code
                        │       └── insufficient ──► error msg
                        │
                        └── tab PayPal
                            └── PayPal SDK → /api/paypal_create_order_gemini
                                └── on-approve → /api/paypal_capture_order
                                    └── token = order_id
   ▼
   token ottenuto ──► /api/generate {payment_token, gemini_style, model_key}
                     ├── backend valida token + consuma importo
                     └── start thread generation
```

### 3.4 Refund flow

```
generation_engine.run_generation:
   try:
       ... synth loop, accumula gemini_actual ...
   except Exception as e:
       _voucher_refund(token, total_eur) or _emit_refund_voucher_for_paypal()
       audit_log(outcome="failed_refunded", ...)
       raise
   on_cancel:
       _voucher_refund(token, total_eur)
       audit_log(outcome="cancelled_refunded", ...)
   on_success:
       audit_log(outcome="completed", est_vs_actual, ...)

audiobook_app startup:
   _recover_orphaned_voucher_charges()  # esteso per gemini
   ├── scan _paid_jobs_done.json (unificato llm+gemini, con migration da _paid_opt_done.json)
   ├── voucher transactions ultime 2h senza done record
   └── refund automatico + audit_log(outcome="recovered_refunded")
```

### 3.5 Audit log file format

File: `<ABM_DATA_DIR>/gemini_cost_audit_<YYYY-MM>.jsonl` (rotation mensile, append-only).

Record:
```json
{
  "ts": "2026-05-14T10:23:11Z",
  "job_id": "abc123",
  "model_key": "flash25",
  "language": "it",
  "chars_total": 287000,
  "input_tokens_est": 71750,
  "input_tokens_actual": 72184,
  "output_tokens_est": 478333,
  "output_tokens_actual": 489210,
  "audio_seconds_est": 19133,
  "audio_seconds_actual": 19580,
  "google_cost_eur_est": 0.5246,
  "google_cost_eur_actual": 0.5371,
  "user_price_eur_charged": 0.84,
  "user_price_eur_should_have_been": 0.86,
  "delta_eur": 0.02,
  "delta_pct": 2.4,
  "margin_eur_actual": 0.303,
  "outcome": "completed"
}
```

Outcome enum: `completed | failed_refunded | cancelled_refunded | recovered_refunded`.

### 3.6 Admin UI `/logs` — tab Gemini Audit

- Tabella con colonne: data, job_id (link), modello, lingua, char, durata, costo stimato €, costo reale €, delta €, delta %, esito
- Filtri: modello (flash25/flash31/all), lingua (it/en/.../all), date range, outcome
- Aggregati footer:
  - Numero job mese corrente
  - Ricavo totale netto
  - Costo Google totale
  - Margine effettivo €
  - Delta medio % per (modello, lingua)
- Bottone "Calcola parametri suggeriti" → mostra raccomandazioni testuali, es.:
  ```
  Per modello flash25 / lingua it:
    chars_per_token osservato:    3.87 (configurato: 4.0)  → -3.4%
    output_tokens/s osservato:    24.1 (configurato: 25)   → -3.7%
  Suggerimento env var:
    ABM_GEMINI_25FLASH_INPUT_USD_PER_MTOK: +3.4% (da 0.50 a 0.517)
    -- oppure aggiornare CHARS_PER_TOKEN_BY_LANG['it'] a 3.87 in gemini_tts.py
  ```

L'admin applica le modifiche manualmente sul server (env var) — nessuna scrittura automatica.

## 4. API contracts

### 4.1 `POST /api/gemini_estimate`

Request:
```json
{
  "job_id": "abc",
  "voice_id": "gemini:flash25:Zephyr",
  "selected_chapters": [0, 1, 2, 5],
  "style_instruction": "tono calmo"
}
```
Response:
```json
{
  "chars_total": 287000,
  "audio_seconds_est": 19133,
  "estimated_audio_minutes": 318.9,
  "user_price_eur": 0.84,
  "is_free": false,
  "model_key": "flash25",
  "model_label": "Gemini 2.5 Flash TTS",
  "language": "it",
  "breakdown": {
    "input_tokens_est": 71750,
    "output_tokens_est": 478333,
    "google_cost_eur": 0.5246,
    "margin_percent": 35.0
  }
}
```

### 4.2 `POST /api/combined_estimate`

Request:
```json
{
  "job_id": "abc",
  "voice_id": "gemini:flash25:Zephyr",
  "selected_chapters": [0, 1, 2, 5],
  "ai_opt_enabled": true,
  "style_instruction": "tono calmo"
}
```
Response:
```json
{
  "gemini_eur": 0.84,
  "llm_eur": 0.32,
  "total_eur": 1.16,
  "is_free": false,
  "threshold_eur": 0.50,
  "gemini_breakdown": { ... },
  "llm_breakdown": { "chars": 287000, "rate_eur_per_mchar": 1.10 }
}
```

Se `voice_id` non Gemini → `gemini_eur=0`. Se `ai_opt_enabled=false` → `llm_eur=0`.

### 4.3 `POST /api/paypal_create_order_gemini`

Request:
```json
{
  "job_id": "abc",
  "amount_eur": 1.16,
  "purpose": "gemini"
}
```
Backend valida: `amount_eur` deve coincidere con `combined_estimate(job_id, ...)`. Risposta come `/api/paypal_create_order` (order_id + amount + status).

### 4.4 Estensione `POST /api/voucher_validate`

Aggiunge campo opzionale `purpose: "llm" | "gemini" | "combined"` (default "any"). Validazione invariata; `purpose` è solo annotazione del consumo successivo. Restituisce `payment_token` (= voucher code) ma **non consuma ancora**.

### 4.5 Estensione `POST /api/generate`

Nuovi campi accettati:
- `payment_token`: stringa (voucher code o PayPal order_id)
- `gemini_style_instruction`: stringa (max 300 char)
- `gemini_model_key`: stringa ("flash25" | "flash31") — ridondante con voice_id ma esplicito

Backend:
1. Se voce = Gemini E `combined_estimate(...) > 0.50` → richiede `payment_token` (400 se mancante)
2. Validazione token: `_voucher_validate_and_consume(token, amount=total_eur, purpose="gemini")` (sia voucher che paypal order)
3. Salvataggio `job["payment"] = {token, total_eur, ...}` per refund eventuale
4. Avvio thread come oggi

### 4.6 `GET /admin/api/gemini_cost_audit`

Query params: `model`, `language`, `outcome`, `date_from`, `date_to`, `limit`, `offset`.
Risposta: `{records: [...], aggregates: {...}, count: N}`.

### 4.7 `GET /admin/api/gemini_cost_audit/recalc-params`

Calcola, per ogni (modello, lingua), il delta medio storico e propone aggiustamenti dei parametri. Risposta strutturata che il frontend rende come testo leggibile.

## 5. File structure

| File | Modifica | Ruolo |
|---|---|---|
| `templates/_fragments/html_head.html` | Modify | Tab-bar Panel 3, modal pagamento Gemini |
| `templates/_fragments/i18n_data.js` | Modify | Nuove chiavi i18n (7 lingue) |
| `static/css/style.css` | Modify | Stili tab-bar, payment-modal, cost-preview-box |
| `static/js/app.js` | Modify | Tab-switching, listener stima, modal, PayPal SDK; rimozione Gemini dal tab Standard |
| `gemini_tts.py` | Modify | Param `style_instruction` in `synthesize()` |
| `generation_engine.py` | Modify | Accumulo `gemini_actual`, refund triggers, scrittura audit, passaggio style |
| `payment.py` | Modify | Campo `purpose` voucher, estensione recovery |
| `audiobook_app.py` | Modify | Nuovi endpoint, modifica `/api/generate`, admin tab `/logs`, unificazione `_paid_opt_done.json` → `_paid_jobs_done.json` con migration one-shot allo startup |
| `gemini_cost_audit.py` | **NEW** | Writer/reader/aggregator dell'audit log |
| `test/test_gemini_premium_tab.py` | **NEW** | Test integrazione UI flow |
| `test/test_gemini_cost_audit.py` | **NEW** | Test audit log + aggregator |
| `PARAMETRI_CONFIGURAZIONE.md` | Modify | Documentazione nuovi parametri |

## 6. Sequenza implementativa (per writing-plans)

**Fase A — UI base (no logica costo)**: tab-bar, tab Premium statico, rimozione Gemini dal Standard, persistenza stato.
**Fase B — Stima costo**: endpoint estimate + combined_estimate, listener frontend.
**Fase C — Modal pagamento + voucher**: markup modal, estensione voucher_validate, flow voucher.
**Fase D — PayPal**: endpoint create_order_gemini, SDK riattivato nel modal.
**Fase E — Generation engine**: style_instruction al primo chunk, accumulo gemini_actual.
**Fase F — Audit log + refund**: modulo `gemini_cost_audit`, scrittura record, refund automatico, unificazione `_paid_opt_done.json` → `_paid_jobs_done.json` con migration one-shot allo startup, recovery startup esteso per coprire entrambi i purpose (`llm`, `gemini`).
**Fase G — Admin UI**: endpoint audit, tab in `/logs`, "parametri suggeriti".
**Fase H — Cleanup + test estesi**: docs, i18n audit 7 lingue, smoke test end-to-end, **test stress concorrenza voucher / migration / refund idempotency** (vedi sez. 7.2 per il dettaglio dei test obbligatori).

Stima: 25 task TDD totali, 8 fasi committabili autonomamente. La Fase H è ampliata rispetto al baseline del progetto per la natura money-critical dell'intervento.

## 7. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| Stima costo molto inferiore al reale → margine eroso | Audit log + tuning periodico parametri; margine 25-35% iniziale è cuscinetto |
| Utente paga, crash server prima dell'avvio thread → soldi senza servizio | Recovery startup (`_recover_orphaned_voucher_charges`) esteso a Gemini |
| Utente paga, poi cambia modello o selezione capitoli, totale diverso | Modal mostra costo congelato al momento dell'apertura; cambio modello/capitoli dopo apertura modal → invalida token e richiede ri-validazione. Cambio voce dentro lo stesso modello NON invalida (costo invariato). |
| Istruzione di stile fa drift della lingua / risultato strano | Avviso UI: "Le istruzioni di stile possono influenzare la qualità della lettura. Testa con la preview prima di procedere." |
| Voucher esaurito a metà generazione (su batch lunghi) | Pagamento è upfront full-amount, non consumo a chunk; nessun esaurimento in corsa |
| Admin dimentica di aggiornare parametri → margine si erode silenzioso | Alert nel tab admin: "Delta medio del mese > 10% per modello X — considera aggiornare i parametri" |
| Migration `_paid_opt_done.json` → `_paid_jobs_done.json` perde record | Backup obbligatorio (`.pre_unify_bak`) + scrittura atomic + abort startup su errore. Procedura idempotente. Dettagli in sez. 7.1 |
| Race condition su scritture concorrenti `_paid_jobs_done.json` | Lock dedicato (`_paid_jobs_lock`) come già fatto per `_payments.json` / `_vouchers.json`. Coperto da test stress (sez. 7.2) |

## 7.1 Strategia di migration `_paid_opt_done.json` → `_paid_jobs_done.json`

Il file unificato è preferito per coerenza architetturale (un solo file da ispezionare per la recovery, un solo schema). La migration runtime è considerata accettabile dato che in produzione attualmente esiste solo il flusso voucher per LLM, quindi il dataset legacy è limitato.

**Algoritmo migration one-shot, eseguito allo startup dopo `_load_payments` / `_load_vouchers`:**

1. Se esiste `_paid_jobs_done.json` → migration già avvenuta, skip.
2. Se esiste `_paid_opt_done.json`:
   a. Backup: copia atomic in `_paid_opt_done.json.pre_unify_bak`
   b. Lettura record legacy → per ciascuno aggiungi campo `purpose: "llm"` se assente
   c. Scrittura atomic (tmp + rename) in `_paid_jobs_done.json`
   d. Mantieni `_paid_opt_done.json` sul disco (NON cancellare) per audit ex-post; il file diventa read-only di fatto.
3. Se non esiste nessun file → crea `_paid_jobs_done.json` vuoto.

**Rollback safety:** se uno step fallisce, lo startup deve abortire con errore esplicito e log critico. Niente fallback silenzioso che potrebbe perdere record di pagamento.

**Idempotenza:** la procedura deve essere safe-to-rerun (re-startup non duplica record, non altera `_paid_jobs_done.json` esistente).

## 7.2 Requisiti di test (sistema money-critical)

Dato che il flusso tocca pagamenti reali, il test coverage richiesto è più severo del baseline del progetto. La fase H del piano implementativo deve includere:

**Unit test obbligatori:**
- Migration `_paid_opt_done.json` → `_paid_jobs_done.json`: con file presente / assente / corrotto / parzialmente migrato (re-run)
- `_voucher_consume(token, amount, purpose)` su tutti i path: voucher valido, esaurito, scaduto, revocato, importo > saldo
- `_voucher_refund(token, amount)` su tutti i path: success, refund su voucher già consumato totalmente, refund che porta `remaining_eur` oltre `amount_eur` originale (deve essere idempotente / clamp)
- `compute_user_price_eur` con google_cost = 0, google_cost ≈ threshold, google_cost >> threshold (verifica boundary free/paid)
- `combined_estimate` con tutte le combinazioni: gemini only / llm only / both / neither / sotto soglia / sopra soglia
- Audit log: append concorrente da thread multipli (job paralleli), rotazione mese, lettura aggregata con filtri
- Recovery startup: voucher addebitato senza job in `_paid_jobs_done.json` né in `jobs` → refund automatico

**Integration test obbligatori (smoke E2E):**
- Free path Gemini (totale ≤ 0.50€): no modal, generazione parte
- Paid voucher path: validate → consume → generate → completed → audit log scritto
- Paid PayPal path: create_order → capture → generate → completed → audit log scritto
- Refund su errore synth: voucher consumed → exception → voucher remaining_eur ripristinato → audit log `failed_refunded`
- Refund su cancel utente: voucher remaining_eur ripristinato → audit log `cancelled_refunded`
- Recovery dopo simulated crash: voucher consumed, jobs dict azzerato, restart → refund + audit log `recovered_refunded`
- Modifica selezione capitoli dopo apertura modal: token invalidato, ri-validazione richiesta
- Doppio click "Avvia generazione" rapido: il consumo voucher deve essere idempotente (no doppio addebito)

**Test manuali pre-release:**
- Flusso completo con voucher reale generato da CLI admin
- Flusso completo con PayPal sandbox (sandbox.paypal.com)
- Audit log inspection dopo 3-5 generazioni, verifica delta % medio < 15%
- Stress: 5 generazioni concorrenti con voci/modelli diversi, verifica nessun race condition su `_paid_jobs_done.json`

**Audit dei log activity:**
- Verifica che ogni transazione voucher generi log `VOUCHER_CONSUME` con purpose, amount, job_id
- Verifica che ogni refund generi log `VOUCHER_REFUND` con motivo (failed/cancelled/recovered)

## 8. Out-of-scope esplicito

- Refund parziale (non c'è "reserve", quindi non c'è differenza non consumata)
- Voucher tipizzati (LLM-only / Gemini-only) — restano cross-purpose
- Sconti volume / prezzi promozionali — non richiesti
- Pagamento Gemini per LLM solo (cioè usare voce Standard ma pagare per ottimizzazione) — il flusso LLM resta come oggi (solo voucher)
- Riattivazione PayPal nel flusso LLM puro
- Modifiche al pipeline di sintesi (Plan B già completo)
- Streaming preview Gemini con istruzione di stile (la preview attuale è chunk singolo, non applica style)

## 9. Note operative

- I parametri di pricing (`ABM_GEMINI_*`) restano env var; nessuna modifica del modello di configurazione.
- L'audit log JSONL è in `ABM_DATA_DIR` con rotation mensile; nessun limite di dimensione esplicito (file naturalmente piccoli: ~200 byte/record).
- Le nuove chiavi i18n devono essere aggiunte in tutte e 7 le lingue UI (it, en, fr, es, de, zh, hi).
