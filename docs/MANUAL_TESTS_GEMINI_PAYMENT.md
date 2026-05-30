# Manual Smoke Tests — Voci PREMIUM + Pagamento

Checklist E2E da eseguire manualmente prima di un deploy che tocchi il flusso Premium + pagamento. Ogni voce va spuntata su una sessione reale (o sandbox PayPal).

> **Branding (regola dura, vale per tutta la UI utente):** nessuna stringa nella UI utente deve nominare provider AI (Gemini, DeepSeek, OpenAI, Google, Anthropic). Le label devono essere generiche ("★ Voci PREMIUM", "Ottimizzazione testo AI", ecc.). L'admin UI è esente.

---

## 1. Free path (totale ≤ 0.50 €)

- [ ] Job piccolo (testo ~10K char), voce Premium `flash25`, AI opt OFF → **nessun modal di pagamento**, generazione parte direttamente.
- [ ] A fine job: record audit log in `gemini_cost_audit_YYYY-MM.jsonl` con `outcome=completed`, `user_price_eur_charged=0`, `delta_pct` ragionevole (<20% in valore assoluto).
- [ ] Verifica: nessuna stringa "Gemini" / "DeepSeek" / "Google" / "OpenAI" visibile in UI utente (wizard, modal, banner).

## 2. Paid path — Voucher

- [ ] Job grande (~200K char), voce Premium `flash31`, AI opt ON → modal di pagamento si apre, totale `> 0.50 €` mostrato.
- [ ] Tab "Buono" attivo: inserisci codice valido + email corrispondente → label "Saldo disponibile: X.XX €" verde, bottone "Conferma" abilitato.
- [ ] Click "Conferma" → modal chiude, generazione parte, `remaining_eur` del voucher decrementato del totale.
- [ ] Audit log: `outcome=completed`, `delta_pct < 15%` in valore assoluto.

## 3. Paid path — PayPal (sandbox)

- [ ] Stesso job grande, tab "PayPal" → SDK PayPal renderizzato (button arancione).
- [ ] Approve in sandbox → label "Pagamento completato — clicca Conferma" → click Conferma → generazione parte.
- [ ] In `<ABM_DATA_DIR>/_payments.json` il record dell'order è marcato `used=true`, `used_for_job=<id>`.
- [ ] Audit log: `outcome=completed`.

## 4. Refund su errore TTS

- [ ] Lanciare job paid, **forzare un errore** durante synth (es. revoca temporanea della API key Gemini server-side).
- [ ] Job va in `error`. Per voucher: `remaining_eur` ripristinato al valore precedente. Per PayPal: viene generato un voucher rimborso emesso all'email dell'acquirente.
- [ ] Audit log: `outcome=failed_refunded`.

## 5. Refund su cancel utente

- [ ] Job paid lungo, premere "Cancel" nel wizard.
- [ ] Refund identico al caso 4. `outcome=cancelled_refunded`.

## 6. Recovery dopo crash server

- [ ] Lanciare generazione paid, **kill `-9`** del processo Python prima del completamento (es. dopo 2-3 chunk).
- [ ] Riavviare il server. Nel log di avvio deve comparire `[recovery] Recovered N orphaned voucher charge(s)` (oppure il messaggio equivalente per PayPal).
- [ ] Audit log per il job morto: `outcome=recovered_refunded` (o equivalente).
- [ ] Saldo voucher ripristinato.

## 7. Orphan refund su rifiuto post-payment

- [ ] Riempire il limite di concorrenza (`ABM_MAX_CONCURRENT_PER_CLIENT`) con altri job in corso.
- [ ] Tentare un nuovo job paid → preflight `consume_payment_token` riesce, ma `/api/generate` ritorna 429 (limite raggiunto).
- [ ] Verificare nel log applicativo `[refund]` riga, e nel voucher `remaining_eur` ripristinato (il pagamento NON deve essere consumato).
- [ ] Stesso check per il caso 503 (suspend_new_jobs) attivato durante un tentativo.

## 8. Token invalidation su cambio scopo

- [ ] Aprire modal pagamento con totale X (es. flash31 + AI opt). Validare un voucher.
- [ ] **Senza chiudere il modal**, cambiare la selezione capitoli (o disattivare AI opt) → ricaricare la pagina o riaprire il modal.
- [ ] Il totale ricalcolato deve essere diverso; il vecchio token pagamento non deve poter essere riusato (il `consume_payment_token` lato server controlla l'amount con tolleranza 0.05 €).

## 9. Stress concorrenza (5 generazioni)

- [ ] Avviare 5 generazioni paid simultanee con voucher e modelli/voci diversi.
- [ ] Verificare `<ABM_DATA_DIR>/_paid_jobs_done.json` contenga 5 record distinti, tutti con `purpose="gemini"`.
- [ ] Nessuna race: ogni voucher ha decremento `remaining_eur` corretto (= somma dei `user_price_eur_charged` dei suoi job).

## 10. Admin: pagina `/admin/logs`

- [ ] `/admin/logs` con `X-Admin-Token` valido si apre, tab "Audit Gemini" visibile.
- [ ] Filtri `Modello`, `Lingua`, `Outcome`, `Date from`/`to` funzionano e ricaricano tabella + aggregati.
- [ ] Pulsante "Calcola parametri suggeriti" emette stringhe di suggerimento se sono presenti almeno 3 record completed per (model_key, lingua).
- [ ] Senza token → pagina di gate ADMIN; token non deve essere mai presente nel sorgente HTML.

## 11. Branding sweep finale

- [ ] `grep -r -i "Gemini" templates/ static/` → nessuna occorrenza in stringhe utente-facing (admin escluso).
- [ ] `grep -r -i "DeepSeek" templates/ static/` → idem.
- [ ] In `templates/_fragments/i18n_data.js`, i valori delle chiavi `tab_voices_premium`, `pay_premium_voices`, `pay_text_ai_optimization` per tutte le 7 lingue NON devono contenere nomi di provider.

---

## Note sul flusso di pagamento

Il flusso è **payment-before-job**: l'utente paga, il server preflight valida e consuma il token tramite `consume_payment_token`, **poi** crea il job. Se il job slot viene rifiutato dopo il consume (rate-limit, suspend, race), il route esegue un **refund automatico** prima di rispondere 4xx. Se il server crasha tra consume e completamento job, il **recovery all'avvio** ricostruisce i refund mancanti scansionando i job non terminati.

Questa è la garanzia money-safety di base. I test di concorrenza (`test/test_money_critical_stress.py`) e i test di refund orfano (`test/test_orphan_refund.py`) coprono i casi automatici. Le voci di questa checklist coprono i casi che richiedono interazione UI o eventi server-side reali.
