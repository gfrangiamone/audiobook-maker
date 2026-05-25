# Cancel volontario job Gemini TTS: floor su costo piattaforma + audio parziale

**Data**: 2026-05-25
**Stato**: Design approvato — pronto per writing-plans
**Scope**: TTS Gemini (Fase 1). Fase 2 (LLM optimization) in spec separata.
**Provenienza**: brainstorming session con utente, 2026-05-25.

---

## 1. Contesto e motivazione

### 1.1 Policy attuale (snapshot)

Quando l'utente annulla un job Gemini TTS già pagato (PayPal o voucher) tramite il bottone "Annulla" della SPA, il backend (`generation_engine.py:2658-2685`, branch `_CancelledError`):

1. Imposta job status `analyzed`, message `"Cancelled"`.
2. Scrive audit `outcome="cancelled_refunded"` via `_write_gemini_audit`.
3. Chiama `_refund_gemini_payment(reason="cancelled")` che rimborsa il **100%** dell'importo pagato (voucher: riaccredito silenzioso sul voucher originale; PayPal: emissione di un nuovo voucher con codice in email — rif. memoria `feedback_refund_voucher_policy.md`).
4. Cancella `work_dir` con tutti i PCM/MP3 parziali, perdendo l'audio già sintetizzato.

Nel frattempo la piattaforma ha già pagato Google per i chunk effettivamente generati (`record_usage` chunk-per-chunk in `generation_engine.py:2067`, aggregato in `jobs[job_id]["gemini_usage"].google_cost_eur`).

### 1.2 Problemi identificati

1. **Asimmetria economica**: la piattaforma rimborsa il 100% mentre assorbe il costo Google reale per i chunk sintetizzati. Su un job lungo cancellato al 90% questo è perdita secca, e abilita un pattern di abuso ("genero il 95% poi cancello e rifaccio") oltre a normalizzare perdite incrementali su uso non malevolo.
2. **Nessun consenso informato**: l'utente preme "Annulla" senza warning e oggi nemmeno percepisce di "perdere qualcosa" — il rimborso è integrale. Cambiando policy, il warning diventa obbligatorio.
3. **All-or-nothing sull'audio**: il `work_dir` viene cancellato, l'utente non riceve nulla in cambio del costo accumulato sulla piattaforma.
4. **Fee PayPal non recuperabili**: la fee di processing PayPal (3.4% + 0.34€) viene addebitata al capture dell'ordine ed è già persa dalla piattaforma al momento del cancel. Il refund attuale è emissione di voucher locale, non chiamata a PayPal Refund API: le fee restano un costo netto.

### 1.3 Obiettivi del nuovo design

- Garantire che il cancel volontario lasci la piattaforma almeno a break-even sui costi non recuperabili (Google + fee PayPal).
- Informare l'utente dell'impatto economico prima del cancel.
- Dare contropartita tangibile (MP3 parziale) al trattenuto.
- Limitare la finestra di cancel ai primi 70% del job per ridurre lo scenario "cancel in extremis".
- Non penalizzare l'utente nei casi in cui il fallimento è responsabilità della piattaforma (quota/budget Gemini exhausted) — quei path restano a rimborso integrale.

---

## 2. Principio guida

> L'utente paga **almeno** i costi non recuperabili che il suo job ha già generato sulla piattaforma, riceve l'audio sintetizzato fino al cancel come contropartita, e viene rimborsato per la differenza.

---

## 3. Formula del trattenuto

### 3.1 Definizione

```
retained = min(paid, google_cost_eur_actual + paypal_fees_if_method_paypal)
refund   = paid - retained
```

dove:

- `paid` = importo pagato dall'utente per il job Gemini (`job["payment"].total_eur`).
- `google_cost_eur_actual` = somma del costo Google reale per i chunk già completati al momento del cancel, letto da `jobs[job_id]["gemini_usage"].google_cost_eur` (aggiornato chunk-per-chunk in `generation_engine.py:2067`). Snapshot del valore al momento del `_set_job_status(job, "cancelled")` o equivalente. Chunk in-flight quando arriva il cancel: se completa con successo prima dell'abort viene contato (record_usage già chiamato), se abortisce non viene contato.
- `paypal_fees_if_method_paypal` = `paid × (ABM_GEMINI_PAYPAL_PERCENT_FEE / 100) + ABM_GEMINI_PAYPAL_FIXED_FEE_EUR` calcolato sull'**importo pagato originale** se `job["payment"].method == "paypal"`. Zero se metodo `voucher`. Default attuali: `3.4%` + `0.34€` (vedi `md_files/PARAMETRI_CONFIGURAZIONE.md`).

### 3.2 Helper engine-agnostic

Nuova funzione in `generation_engine.py` (o modulo dedicato `cancel_policy.py` se preferito in implementazione):

```python
def compute_cancel_retention(provider_cost_eur: float,
                              payment_method: str,
                              paid_eur: float) -> dict:
    """Calcola trattenuto e refund per un cancel volontario job pagato.

    Engine-agnostic: usato per Gemini TTS in fase 1 e LLM optimization in fase 2.

    Args:
        provider_cost_eur: costo reale provider per la quota di lavoro già
            eseguita (Google TTS per Gemini, DeepSeek/altro LLM per fase 2).
        payment_method: "paypal" | "voucher" | "" (free).
        paid_eur: importo pagato dall'utente per questo job.

    Returns:
        {"retained_eur": float, "refund_eur": float, "paypal_fees_eur": float}
        Tutti gli importi arrotondati a 2 decimali; mai negativi.
    """
```

Test unitari (vedi §10.1) coprono la matrice (`paypal`/`voucher`/`free`) × (`provider_cost ∈ {0, low, mid, ≥paid}`) × (`paid ∈ {0, low, high}`).

### 3.3 Sub-formula PayPal fees

Le fee PayPal sono lette dalle env già esistenti documentate in `ttsgemini.md §11.1`:

| Env | Default |
|-----|---------|
| `ABM_GEMINI_PAYPAL_PERCENT_FEE` | `3.4` |
| `ABM_GEMINI_PAYPAL_FIXED_FEE_EUR` | `0.34` |

Nessuna nuova env per la formula (`ABM_GEMINI_CANCEL_LOCK_PCT` introdotta solo per il cutoff 70%, vedi §6).

---

## 4. Scope del cambiamento

### 4.1 Fase 1 (questa spec)

Solo **TTS Gemini**. La policy si applica esclusivamente quando `job["voice"]` (o `job["opt_voice"]` per il path auto-generate) inizia con `gemini:`.

### 4.2 Fase 2 (spec separata, da scrivere dopo rilascio Fase 1)

LLM optimization (`run_optimization` in `generation_engine.py`). Riusa lo stesso `compute_cancel_retention`, sostituendo `provider_cost_eur` con il costo DeepSeek/LLM accumulato durante lo streaming (`_call_deepseek` traccia già token chunk-per-chunk; va aggregato in un campo simile a `gemini_usage`). Decisioni residue per Fase 2:

- Contropartita: consegnare il testo parziale ottimizzato (in equivalente a MP3 parziale)?
- Modal U1 separato per LLM cancel?

Queste decisioni saranno prese nella spec Fase 2; questa Fase 1 deve solo garantire che `compute_cancel_retention` sia engine-agnostic.

---

## 5. UX cancel

### 5.1 Modal di conferma (U1: testo statico)

Quando l'utente clicca il bottone "Annulla" durante una generazione Gemini in corso:

- **Trigger**: solo se `progress_current/progress_total ≤ 70%` (vedi §6).
- **Contenuto modal** (i18n 7 lingue, chiavi `cancel_confirm_title`, `cancel_confirm_msg`, `cancel_confirm_keep`, `cancel_confirm_proceed`):
  - Titolo: "Annullare la generazione?"
  - Messaggio: "Annullando ora perderai una parte dell'importo pagato proporzionale all'audio già generato. L'audio sintetizzato finora ti sarà comunque consegnato. Vuoi continuare?"
  - Pulsanti: `Mantieni il job` (default, dismiss modal) / `Annulla e ricevi l'audio parziale` (conferma → POST `/api/cancel/<job_id>`).
- **Nessuna stima live**: scelta U1 — nessun nuovo endpoint `/api/cancel_estimate`. Il calcolo del trattenuto è server-side al momento dell'invocazione di `/api/cancel`. Disclaimer non necessario in UI: il valore mostrato dopo il cancel (in pagina di conferma + email) è esatto.

### 5.2 Casi non-Gemini

Per job con voce Edge / Google (`tts_split.py` async / `google_tts.py`) il modal **non viene mostrato**: cancel come oggi, no warning, refund standard del rispettivo flow (per Google c'è già `_google_tts_refund_unused` in `generation_engine.py:2666`). Il modal e la policy floor si applicano esclusivamente a Gemini.

---

## 6. Hard-cutoff cancel oltre 70%

### 6.1 Regola

Quando un job Gemini supera il 70% di completamento, il cancel volontario **non è più consentito**. Il job procede inevitabilmente al completamento.

### 6.2 Metrica

`progress_current / progress_total` letto da `jobs[job_id]` — la stessa metrica già esposta in SPA tramite SSE `/api/progress/<job_id>` per la progress bar. Coerente con ciò che l'utente vede.

### 6.3 Enforcement (doppio gate)

**Client** (`static/js/app.js`):

- Listener SSE su progress aggiorna il bottone Cancel.
- Quando `pct > ABM_GEMINI_CANCEL_LOCK_PCT` (default 70), bottone diventa `disabled` con tooltip i18n `cancel_locked_progress`.
- Tooltip suggerito: "Il job ha superato il {pct}%, non è più possibile annullarlo. L'audio sarà consegnato al completamento."

**Server** (`audiobook_app.py:5680-5694`, endpoint `/api/cancel/<job_id>`):

- Aggiunta gate prima di `job["cancelled"] = True`:
  ```python
  if _is_gemini_voice(job.get("voice", "") or job.get("opt_voice", "")):
      pct = _progress_pct(job)  # 0..100
      lock_pct = int(os.environ.get("ABM_GEMINI_CANCEL_LOCK_PCT", "70"))
      if 0 < lock_pct < 100 and pct > lock_pct:
          return jsonify({"error": "cancel_locked_progress",
                          "progress_pct": pct,
                          "lock_pct": lock_pct}), 409
  ```
- Frontend gestisce `409` mostrando messaggio coerente.

### 6.4 Configurazione

Nuova env `ABM_GEMINI_CANCEL_LOCK_PCT`:

| Env | Default | Significato |
|-----|---------|-------------|
| `ABM_GEMINI_CANCEL_LOCK_PCT` | `70` | Percentuale oltre cui il cancel volontario Gemini è disabilitato. `0` o `100` disattiva il lock (consente cancel sempre). |

### 6.5 Casi limite del lock

- **`progress_total` non ancora calcolato** (fase analisi/setup pre-loop chunk): bottone abilitato (non si raggiunge 70% senza denominatore noto).
- **Quota/budget exhausted oltre 70%**: il path automatico in `generation_engine.py:2690` (`except Exception`) è indipendente dal lock e applica refund integrale come oggi.
- **Job non-Gemini**: lock non si applica, cancel sempre disponibile.

---

## 7. Audio parziale (Opzione 2 + Consegna D3)

### 7.1 Cosa viene prodotto

- Singolo file **MP3** con i chunk Gemini sintetizzati fino al momento del cancel, concatenati tramite la pipeline esistente `pcm_concat` + MP3 encode (riuso del codice già presente in `run_generation` post-success).
- **Nessun M4B** (no cover/chapters), **nessun ZIP per capitoli**, **nessun RSS**: questi formati richiedono metadati di completezza non garantibili in stato cancel parziale.
- Nome file: stesso schema del job completo ma con suffisso `_partial.mp3`.

### 7.2 Pipeline

Branch `_CancelledError` in `generation_engine.py:2658` ristrutturato in questo ordine:

1. **Snapshot floor**: leggi `gemini_usage.google_cost_eur`, calcola `retained` via `compute_cancel_retention`.
2. **Encoding parziale**: se ci sono PCM chunk già scritti (`work_dir` non vuoto), invoca pipeline esistente per produrre `<output_dir>/<filename>_partial.mp3`. In caso di errore di encoding, log + skip (fallback a "nessun MP3 parziale", refund procede comunque).
3. **Audit**: `_write_gemini_audit` con `outcome="cancelled_partial"` se `retained > 0`, altrimenti `cancelled_refunded` (vedi §8).
4. **Refund finanziario**: `_refund_gemini_payment(reason="cancelled", retained_eur=retained)` (vedi §9 per la modifica della funzione).
5. **Token download**: se MP3 prodotto, crea download token come per job completati. Retention standard 48h Gemini. **No estensione 96h** "mai scaricato" (è cancel esplicito, non flusso passivo).
6. **Notifica email + SSE**: se email registrata invia `_send_gemini_cancelled_partial_email`; in ogni caso aggiorna SSE/job state con `download_url` parziale per la SPA.
7. **Cleanup**: cancella `work_dir` solo dopo che MP3 parziale è stato spostato in `output_dir` (o dopo skip se non c'erano PCM).

### 7.3 Branch SSE/UI

Frontend riceve il link al MP3 parziale via lo stesso meccanismo dei job completati (campo `download_url` nel payload SSE di `/api/progress`). La SPA mostra link "Scarica audio parziale" + riassunto: importo pagato, trattenuto, refund (e codice voucher se PayPal).

---

## 8. Audit outcome

Nuovo valore consentito in `gemini_cost_audit_YYYY-MM.jsonl`:

| `outcome` | Significato | Quando |
|-----------|-------------|--------|
| `cancelled_refunded` (esistente) | Rimborso 100% senza trattenuto | Cancel pre-audio voucher (E1.voucher); cancel automatico per quota/budget (E9); job free (E1.free) |
| `cancelled_partial` (NUOVO) | Cancel volontario con `retained > 0` | Tutti gli altri cancel volontari Gemini con `gemini_usage.google_cost_eur > 0` o con `paypal_fees > 0` |

Aggiungere al filter dropdown del pannello `/admin` (`audiobook_app.py:3221` e mapping badge `audiobook_app.py:3457`):

```python
"cancelled_partial": ["badge-muted", "Annullato (parz.)"]
```

I campi audit `user_price_eur_charged` e `should_have_been` continuano la convenzione esistente, ma per `cancelled_partial` `user_price_eur_charged` rappresenta il **trattenuto** (non il pagato originale). Aggiungere nuovi campi facoltativi per chiarezza ex-post:

```json
{
  "cancel_paid_eur": 2.00,
  "cancel_retained_eur": 0.65,
  "cancel_refund_eur": 1.35,
  "cancel_progress_pct": 28,
  "cancel_partial_audio_delivered": true
}
```

---

## 9. Refund finanziario

### 9.1 Modifica a `_refund_gemini_payment`

Funzione attuale (`generation_engine.py:1158-1201`) rimborsa l'importo intero (`amt = payment_meta["total_eur"]`). Modifica:

```python
def _refund_gemini_payment(job_id, job, reason="error", retained_eur: float = 0.0):
    payment_meta = job.get("payment") or {}
    tok = payment_meta.get("token")
    amt_paid = float(payment_meta.get("total_eur", 0) or 0)
    method = payment_meta.get("method", "")
    if not tok or amt_paid <= 0:
        return None
    refund_amt = max(0.0, round(amt_paid - retained_eur, 2))
    if refund_amt <= 0:
        return {"method": method, "amount_eur": 0.0, "email": "", "voucher_code": None,
                "retained_eur": amt_paid}
    # … resto invariato, ma `amt` diventa `refund_amt`
```

Default `retained_eur=0.0` preserva il comportamento attuale (chiamato da quota/budget exhausted, errori → rimborso 100%).

### 9.2 Bonus +10% solo per failure piattaforma

Verifica in `payment._create_voucher`: oggi il refund PayPal in caso di failure piattaforma riceve bonus +10% (rif. `ottimizzazione_testo_AI.md`, refund asimmetrico). Per cancel **volontario** il bonus va **disattivato**.

Strategia:

- Aggiungere parametro `apply_refund_bonus: bool = True` a `payment._create_voucher` (o equivalente meccanismo già esistente).
- Path `_refund_gemini_payment` invocato da `_CancelledError` (cancel volontario): passa `apply_refund_bonus=False`.
- Path invocato da `except Exception` (quota/budget/altri errori): mantiene `apply_refund_bonus=True` (comportamento attuale).

Da verificare in implementazione: la funzione `payment._create_voucher` ha già un flag analogo o il bonus +10% è applicato implicitamente in base a `kind="refund"`. In quel caso introdurre un nuovo `kind="cancel_partial"` o un parametro esplicito.

### 9.3 Voucher

`payment._voucher_refund(token, refund_amt)` riaccredita silenzioso. Nessun cambio di comportamento per voucher (era già silenzioso, ora l'importo è ridotto del trattenuto).

### 9.4 PayPal

`payment._create_voucher(email, refund_amt, origin_order_id=tok, origin_job_id=job_id, kind="refund", note=f"user_cancel {job_id}", apply_refund_bonus=False)`. Codice voucher emesso in email tramite `_send_gemini_cancelled_partial_email` (vedi §11).

---

## 10. Edge case consolidati

Sotto la formula §3 si decompongono così:

| # | Scenario | Floor | Refund | MP3 parziale | Audit outcome |
|---|----------|-------|--------|--------------|---------------|
| E1.PP | Pre-audio (`gemini_usage=0`), metodo PayPal | `paypal_fees(paid)` | `paid − fees` (voucher) | No (no PCM) | `cancelled_partial` |
| E1.V | Pre-audio, metodo voucher | 0 | 100% riaccredito | No | `cancelled_refunded` |
| E1.Free | Pre-audio, job free (`paid=0`) | n/a | n/a | No | `cancelled_refunded` |
| E2 | Floor ≥ paid (job lungo cancellato sotto 70%) | `paid` | 0 | Sì | `cancelled_partial` |
| E3 | Job free, audio già iniziato | n/a | n/a | Sì (gratis) | `cancelled_refunded` |
| E4 | Cancel tentato durante post-processing post-chunk (M4B mux, ecc.) | n/a — `_check_cancelled` è solo nel loop chunk; non viene invocato in concat/mux | Charge full | Full audio | `completed` (job completa normalmente) |
| E5 | Voucher con saldo bonus residuo | come PayPal/voucher in base a metodo originale | Refund accreditato sul voucher originale | Sì se audio iniziato | `cancelled_partial` o `cancelled_refunded` |
| E6 | PayPal, audio iniziato | `google_cost + paypal_fees` | `paid − retained` (voucher emesso) | Sì | `cancelled_partial` |
| E7 | Chunk in-flight al cancel | snapshot `gemini_usage` al `_set_status("cancelled")`; chunk completo conta, abortito no | derivato | — | — |
| E8 | Audit `outcome` | nuovo valore `cancelled_partial` per `retained > 0`; `cancelled_refunded` per `retained = 0` | — | — | — |
| E9 | Cancel automatico (quota/budget Gemini, errori) | **non cambia**: refund integrale, no MP3 parziale | 100% | No | `cancelled_refunded` / `gemini_overload` / `budget_exceeded` (esistenti) |
| E10 | Tentativo cancel oltre 70% | non applicabile — `/api/cancel` ritorna `409 cancel_locked_progress` | — | — | — |

### 10.1 Test matrix unitaria per `compute_cancel_retention`

| paid_eur | provider_cost_eur | payment_method | expected retained | expected refund |
|----------|-------------------|----------------|-------------------|-----------------|
| 0.00 | 0.00 | "" | 0.00 | 0.00 |
| 0.00 | 0.10 | "" | 0.00 | 0.00 |
| 2.00 | 0.00 | "voucher" | 0.00 | 2.00 |
| 2.00 | 0.00 | "paypal" | 0.41 (0.34 + 3.4% × 2.00) | 1.59 |
| 2.00 | 0.30 | "voucher" | 0.30 | 1.70 |
| 2.00 | 0.30 | "paypal" | 0.71 (0.30 + 0.41) | 1.29 |
| 2.00 | 1.80 | "voucher" | 1.80 | 0.20 |
| 2.00 | 1.80 | "paypal" | 2.00 (clamped a paid) | 0.00 |
| 2.00 | 5.00 | "paypal" | 2.00 (clamped) | 0.00 |
| 0.60 | 0.30 | "paypal" | 0.60 (raw 0.30 + 0.34 + 3.4%×0.60 = 0.6604 → clamped a paid) | 0.00 |
| 1.50 | 0.20 | "paypal" | 0.59 (0.20 + 0.34 + 3.4%×1.50 = 0.591 ≈ 0.59) | 0.91 |

Valori sopra calcolati con `ABM_GEMINI_PAYPAL_PERCENT_FEE=3.4`, `ABM_GEMINI_PAYPAL_FIXED_FEE_EUR=0.34`. I test devono usare gli stessi default e validare arrotondamento a 2 decimali.

---

## 11. Email di notifica

### 11.1 Nuovo template

`email_service._send_gemini_cancelled_partial_email(email, paid_eur, retained_eur, refund_eur, voucher_code, book_title, download_url)`:

- Asset: usa lo stesso layout HTML degli altri template Gemini (header brand, footer, retention reminder).
- Soggetto i18n (chiave `cancel_partial_email_subject`): "La tua generazione audio è stata annullata"
- Corpo (chiave `cancel_partial_email_body` con placeholder):
  - Spiegazione: il job è stato annullato su richiesta dell'utente.
  - Audio parziale: link download (warning retention 48h).
  - Riepilogo finanziario:
    - Importo pagato: `{paid_eur}€`
    - Trattenuto per costi già sostenuti: `{retained_eur}€`
    - Rimborso: `{refund_eur}€`
    - Se voucher: "riaccreditato sul voucher originale"
    - Se PayPal: "Codice voucher: `{voucher_code}`" + istruzioni per riutilizzo

### 11.2 Quando viene inviata

Solo se `email_registered` (stesso gate dei job completati). Altrimenti l'utente vede comunque il link MP3 parziale nella SPA via SSE.

### 11.3 Casi senza email

- PayPal senza email buyer (raro): voucher emesso, codice loggato come WARNING in stdout (allineato a `_refund_gemini_payment` esistente per quel caso).
- Voucher senza email associata: refund silenzioso comunque applicato, nessuna email.

---

## 12. File impattati (preview implementazione)

### 12.1 Backend

| File | Linee approssimative | Cambio |
|------|----------------------|--------|
| `generation_engine.py` | nuovo helper (top-level o modulo dedicato) | Aggiungere `compute_cancel_retention(provider_cost_eur, payment_method, paid_eur)` |
| `generation_engine.py:1158-1201` | `_refund_gemini_payment` | Aggiungere parametro `retained_eur: float = 0.0`; calcolare `refund_amt = paid - retained_eur` |
| `generation_engine.py:2658-2685` | Branch `_CancelledError` | Ristrutturare ordine: snapshot floor → encoding parziale → audit `cancelled_partial`/`cancelled_refunded` → refund con retained → token download → email + SSE → cleanup |
| `generation_engine.py:~1509` | `_write_gemini_audit` | Accettare e persistere nuovi campi `cancel_paid_eur`, `cancel_retained_eur`, `cancel_refund_eur`, `cancel_progress_pct`, `cancel_partial_audio_delivered` |
| `audiobook_app.py:5680-5694` | Endpoint `/api/cancel/<job_id>` | Aggiungere gate `ABM_GEMINI_CANCEL_LOCK_PCT` per voci Gemini; ritorno `409 cancel_locked_progress` |
| `audiobook_app.py:3221, 3457, 3466` | Mapping audit outcome | Aggiungere `cancelled_partial` con badge `Annullato (parz.)` |
| `email_service.py` | nuova funzione | `_send_gemini_cancelled_partial_email(...)` |
| `payment.py` | `_create_voucher` o equivalente | Aggiungere `apply_refund_bonus: bool = True`; cancel volontario passa `False` |

### 12.2 Frontend

| File | Cambio |
|------|--------|
| `static/js/app.js` | Modal di conferma cancel (mostrato solo per Gemini); listener SSE per disable bottone oltre soglia; tooltip i18n; gestione `409 cancel_locked_progress` (toast); rendering link MP3 parziale + riepilogo refund |
| `templates/_fragments/i18n_data.js` | Chiavi: `cancel_confirm_title`, `cancel_confirm_msg`, `cancel_confirm_keep`, `cancel_confirm_proceed`, `cancel_locked_progress`, `cancel_partial_email_subject`, `cancel_partial_email_body`, `cancel_partial_paid_label`, `cancel_partial_retained_label`, `cancel_partial_refund_label`, `cancel_partial_download_label`, `cancel_partial_voucher_code_label` |
| `i18n/*.json` (7 file: it/en/fr/es/de/zh/hi) | Traduzioni delle chiavi sopra |

### 12.3 Documentazione

| File | Cambio |
|------|--------|
| `md_files/PARAMETRI_CONFIGURAZIONE.md` | Aggiungere `ABM_GEMINI_CANCEL_LOCK_PCT` (default 70, sezione "Caps PREMIUM") |
| `md_files/ttsgemini.md` | Nuova sezione "Cancel policy con floor + audio parziale" (collocata dopo §8 Retry, prima di §9 Budget); aggiornare §8.1 per chiarire che il path quota/budget continua a fare rimborso 100% mentre il cancel volontario applica floor; aggiornare §14.1 audit con nuovo outcome `cancelled_partial` e nuovi campi cancel_*; aggiornare §15.2 modali con `cancelConfirmModal` (modal U1) |
| `CLAUDE.md` | Nessun cambio strutturale; eventualmente menzione in Development Conventions §6 "Error Handling" che il cancel volontario Gemini ha policy floor |

---

## 13. Test plan

### 13.1 Unit

- `compute_cancel_retention`: matrice completa §10.1.
- `_progress_pct(job)` helper: copertura casi `progress_total=0`, `None`, valori >100 (sanitize).

### 13.2 Integration (pytest fixtures su flow simulato)

- Cancel a 5% Gemini PayPal → refund ≈ paid − google_cost − fees, MP3 parziale presente, audit `cancelled_partial`, email inviata, voucher emesso.
- Cancel a 5% Gemini voucher → refund ≈ paid − google_cost, MP3 parziale presente, voucher riaccreditato silenzioso.
- Cancel a 50% Gemini → idem.
- Cancel a 71% Gemini → `/api/cancel` risponde `409 cancel_locked_progress`, job continua, alla fine consegna normale.
- Cancel pre-audio Gemini PayPal → refund = paid − fees, no MP3, audit `cancelled_partial`.
- Cancel pre-audio Gemini voucher → refund = 100%, no MP3, audit `cancelled_refunded`.
- Cancel pre-audio Gemini free → nulla da rimborsare, no MP3, audit `cancelled_refunded`.
- Quota Gemini exhausted a 80% → path `except Exception` invariato, refund integrale, no MP3, no impatto del lock 70% (path automatico).
- Cancel job non-Gemini (Edge) → modal non mostrato, flow attuale invariato.

### 13.3 Manuale

- Cancel reale a 30% con PayPal sandbox: verifica voucher arriva via email, MP3 parziale ascoltabile, somma `retained + refund = paid`.
- Cancel oltre 70% in UI: bottone disabled, tooltip visibile, click su POST diretto via DevTools → `409`.
- Cancel pre-audio (subito dopo capture): refund su voucher (per PayPal) coerente con paid − fees.

### 13.4 Regression

- Cancel automatico quota: nessuna regressione, refund 100%.
- Job completato normalmente: nessun cambio.
- Job non-Gemini: cancel come oggi.

---

## 14. Rollout

### 14.1 Strategia

Fase 1 (questa spec) rilasciata in singolo deploy. Nessun feature flag dedicato proposto (la policy è binaria e l'env `ABM_GEMINI_CANCEL_LOCK_PCT=100` consente di disattivare il cutoff senza ricompilare).

### 14.2 Open question: kill-switch globale

Da decidere prima dell'implementazione: vogliamo un `ABM_GEMINI_CANCEL_FLOOR_DISABLED=false` (default) che, se `true`, fa tornare il flow a "rimborso 100% sempre" come oggi? Utile per rollback rapido senza redeploy se la policy ha effetti collaterali imprevisti in produzione. **Non bloccante per la spec**: può essere aggiunto in implementazione se ritenuto utile dal plan.

### 14.3 Version bump

Cambio di policy economica visibile → bump **minor** in `version.py` al push su `main`.

---

## 15. Vincoli e non-goal

### 15.1 Non goal di questa spec

- **Non** si modifica il flusso refund di errori non-cancel (quota/budget/errori di rete): restano a refund integrale.
- **Non** si introduce PayPal Refund API: il rimborso PayPal continua a essere emissione di voucher locale.
- **Non** si modifica la policy refund per Edge / Google TTS (engine senza costo per-chunk persistito allo stesso modo).
- **Non** si modifica il flow LLM optimization (Fase 2 in spec separata).
- **Non** si introduce stima live del trattenuto (scelta U1).
- **Non** si consegnano M4B/ZIP/RSS parziali (solo MP3 singolo file).

### 15.2 Vincoli da rispettare in implementazione

- **Convenzione UI provider naming**: nessuna stringa user-facing menziona "Gemini" o "Google" — usare "Voci PREMIUM" / "servizio TTS Premium" (rif. memoria `feedback_ui_provider_naming.md`).
- **Documentation Sync Rule**: aggiornare `ttsgemini.md` e `PARAMETRI_CONFIGURAZIONE.md` nella stessa change dell'implementazione (rif. CLAUDE.md).
- **Validazione sintassi**: ogni modifica Python passa `python -m py_compile`; test rilevanti devono passare.
- **Bilingue UI**: 7 lingue obbligatorie per ogni nuova chiave i18n.

---

## 16. Riferimenti

- Memoria utente: `feedback_refund_voucher_policy.md`, `feedback_ui_provider_naming.md`, `feedback_voice_preview_no_cache.md`.
- Doc tecnici: `md_files/ttsgemini.md` (§8.1 Retry, §11 Pricing, §14 Audit), `md_files/architettura.md` (ciclo vita job), `md_files/PARAMETRI_CONFIGURAZIONE.md`.
- Codice attuale: `generation_engine.py:2658-2685` (cancel branch), `generation_engine.py:1158-1201` (`_refund_gemini_payment`), `audiobook_app.py:5680-5694` (`/api/cancel`).
