# Audit Traduzioni — Design

Data: 2026-07-16 · Feature: pannello admin "Audit Traduzioni" analogo a "Audit TTS", ristretto ai soli job di traduzione libro.

## Obiettivo

Da `/admin/log-activity`, un bottone **"🌍 Audit Traduzioni"** apre un pannello economico speculare all'Audit TTS (`/admin/audit-tts`): per **tutti e soli** i job di traduzione mostra costo provider (LLM), prezzo/ricavo, margine lordo e netto, margine %, con filtri, aggregati, righe live per i job in corso e un tab "Eventi & Rimborsi".

## Contesto e vincoli

- I job di traduzione (`run_translation` in `generation_engine.py`) oggi persistono **solo** eventi `_log_activity` (`TRANSLATE` / `TR_COMPLETE` / `TR_CANCEL`): nessun dato economico durevole.
- Non esiste alcun modello di **costo provider** per la traduzione: `payment.TRANSLATE_RATE_EUR_PER_MCHAR` (default 3.0) e `TRANSLATE_MIN_COST_EUR` (default 1.5) sono il **prezzo di vendita**, non il costo.
- L'Audit TTS si nutre di un JSONL persistito (`gemini_cost_audit.py`) scritto a fine job da `_write_gemini_audit` / `_write_speechify_audit`, arricchito a lettura da `_apply_cancel_effective` + righe live da `_synth_running_gemini_audit_records`. Questo design ne è il gemello per le traduzioni.
- I token reali della traduzione sono già disponibili da `translation_core.UsageTracker.report()` → `{prompt_tokens, completion_tokens, estimated}`.

## Decisioni (approvate)

1. **Costo = reale a token**: `costo = in/1M × RATE_IN + out/1M × RATE_OUT`, da token reali dell'`UsageTracker`.
2. **Tariffe = coppia unica in/out** (2 env var), valida a prescindere dal backend. Il record salva comunque `backend`/`model` per riferimento.
3. **Parità piena** con l'Audit TTS: record + aggregati + filtri + righe live + tab "Eventi & Rimborsi".
4. **Default tariffe = Gemini 2.5 Flash** (backend Vertex di prod), documentati come base costo da verificare.

## Architettura

### 1. Persistenza — nuovo modulo `translation_cost_audit.py`

Clone di `gemini_cost_audit.py`:

- JSONL append-only mensile `translation_cost_audit_YYYY-MM.jsonl` in `ABM_DATA_DIR`, scrittura atomica (append-mode + lock).
- `append_record(record: dict)` — setta `ts` UTC se assente.
- `iter_records(model=None, source_lang=None, target_lang=None, outcome=None, date_from=None, date_to=None)` — itera tutti i file glob, applica filtri; `date_from/to` confrontano `ts[:10]`.
- File **separato** dai record TTS → garantisce "tutti e soli i job di traduzione".
- **Forward-only**: le traduzioni concluse prima del deploy non hanno record (stesso limite dell'Audit TTS, accettabile).

### 2. Calcolo costo — helper in `payment.py`

Accanto a `_estimate_translation_cost_eur`:

```python
TRANSLATE_COST_IN_EUR_PER_MTOK = float(os.environ.get(
    "ABM_TRANSLATE_COST_IN_EUR_PER_MTOK", "0.28").replace(",", "."))
TRANSLATE_COST_OUT_EUR_PER_MTOK = float(os.environ.get(
    "ABM_TRANSLATE_COST_OUT_EUR_PER_MTOK", "2.30").replace(",", "."))

def _translation_provider_cost_eur(prompt_tokens, completion_tokens):
    """Costo LLM stimato (EUR) dai token reali. Coppia unica in/out,
    default listino Gemini 2.5 Flash (base da verificare)."""
    ci = (prompt_tokens or 0) / 1_000_000.0 * TRANSLATE_COST_IN_EUR_PER_MTOK
    co = (completion_tokens or 0) / 1_000_000.0 * TRANSLATE_COST_OUT_EUR_PER_MTOK
    return round(ci + co, 6)
```

Parsing robusto virgola-decimale come le altre costanti di `payment.py`.

### 3. Scrittura record — `_write_translation_audit` in `generation_engine.py`

Best-effort/non-fatale (come gli audit TTS). Chiamato in `run_translation` ai tre esiti terminali:

| Esito `run_translation` | `outcome` | Ricavo effettivo (via `_apply_cancel_effective`) |
|---|---|---|
| status `translated` (ok) | `completed` | `user_price_eur_charged` |
| `TranslationCancelled` | `cancelled_refunded` | 0 (refund pieno) |
| `Exception` | `failed_refunded` | 0 (refund pieno) |

Il set di outcome è volutamente più semplice del TTS: la traduzione rimborsa **sempre** l'intero su cancel/error (`_refund_job_payment`), quindi niente preflight/quota/budget/quality/partial.

Il costo viene salvato sotto la chiave **`google_cost_eur_actual`** — convenzione già adottata da `_write_speechify_audit` ("costo provider agnostico") per riusare senza duplicazione `_apply_cancel_effective`, `_compute_paypal_fee_eur` e gli aggregati. In UI l'etichetta è **"Costo LLM"**.

Schema record:

```
ts, job_id,
backend,                      # "vertex" | "apikey"
model_key,                    # nome modello (es. "gemini-2.5-flash"); filtro `model`
source_lang, target_lang,     # ISO due lettere
optimize,                     # bool (ottimizzazione AI integrata)
chars_total,                  # caratteri sorgente tradotti (capitoli selezionati)
prompt_tokens, completion_tokens, tokens_estimated,
google_cost_eur_actual,       # costo LLM (chiave provider-agnostica)
user_price_eur_charged,       # incassato (job["payment"].total_eur, fallback payment_amount_eur)
user_price_eur_should_have_been,  # _estimate_translation_cost_eur(chars_total, optimize).due_eur
delta_eur,                    # should - charged
margin_eur_actual,            # charged - cost
payment_method, payment_token_short, payment_source,
outcome
```

Recupero pagamento con lo stesso fallback legacy di `_write_gemini_audit` (`job["payment"]` → `job["payment_amount_eur"]`/`payment_token`), token mascherato (`[:8]+"..."`).

### 4. Righe live — `_synth_running_translation_audit_records()`

- `run_translation` stasha a fine di ogni capitolo `job["tr_usage"] = usage.report()` (costo trascurabile).
- Nuovo synth: snapshot job in stato `translating` → riga `outcome="running"`, `_live=True`, con costo parziale dai token in `job["tr_usage"]`, `chars_total = job["tr_total_chars"]`, prezzo `should_have_been` da `_estimate_translation_cost_eur`, `user_price_eur_charged` dal payment. Speculare a `_synth_running_gemini_audit_records`.

### 5. Endpoint API (admin-gated)

Gate identico agli endpoint TTS (`ADMIN_TOKEN` → 404 se disabilitato; `_admin_auth_ok` → 401 con `sleep(0.5)`).

- `GET /admin/api/translation_cost_audit` — mirror di `admin_api_gemini_cost_audit`:
  - `persisted = translation_cost_audit.iter_records(...)` + `live = _synth_running_translation_audit_records()` (rispetta filtri model/lang, iniettato solo se `outcome ∈ {None, "running"}`; marca `_rerun` se job_id già persistito).
  - `_apply_cancel_effective(r)` su ogni record.
  - Aggregati su `completed` + `running`: `count, revenue_eur, google_cost_eur, margin_eur, paypal_fees_eur, net_margin_eur, delta_pct_avg`.
  - Filtri query: `model`, `source_lang`, `target_lang`, `outcome`, `date_from`, `date_to`, `limit`/`offset`.
- `GET /admin/api/translation_cost_audit/languages` — `{ "source_langs": [...], "target_langs": [...] }` con i codici distinti realmente presenti nei record.

Riuso invariato di `_apply_cancel_effective`, `_compute_paypal_fee_eur`, `_FULL_REFUND_OUTCOMES` (già provider-agnostici; `cancelled_refunded`/`failed_refunded` sono già in `_FULL_REFUND_OUTCOMES`).

### 6. Pagina `/admin/audit-translations`

Clone di `/admin/audit-tts` (stesso CSS, gate `_render_admin_gate`, header `X-Admin-Token` da session/localStorage). Niente pannello kill-switch (non pertinente). Due tab:

- **Audit Traduzioni**: filtri (Backend/Modello, Lingua origine, Lingua destinazione, Esito, date) · aggregati (Job, Ricavo, Costo LLM, Margine, Margine netto, Margine % medio) · tabella record.
  - Colonne: Data · Job · Backend/Modello · Origine→Destinazione · AI · Char · Token (in/out) · Costo LLM · Prezzo · Margine · Margine netto · Margine % · Esito.
  - Righe `running` sempre in cima (`row-live`), badge `re-run` se `_rerun`.
- **Eventi & Rimborsi**: stesso endpoint, filtro client-side sugli outcome di rimborso (`failed_refunded`, `cancelled_refunded`), evidenza rossa. Aggregati: Totale eventi, Completati, Rimborsi, Annullati.

Filtro Esito (dropdown): `all` / `running` (In corso) / `completed` (Completato) / `failed_refunded` (Fallito, rimborsato) / `cancelled_refunded` (Annullato, rimborsato).

Bottone in `/admin/log-activity` accanto a "🎙️ Audit TTS":
```html
<a class="btn btn-accent" href="/admin/audit-translations?{ym}" title="Audit Traduzioni: costi/margini LLM">🌍 Audit Traduzioni</a>
```

## Gestione errori

- Scrittura audit best-effort: `try/except` con print non-fatale; un fallimento non compromette il job né il refund.
- Costo 0 se token assenti/`estimated` (record comunque scritto, margine calcolato su costo 0).
- Endpoint tolleranti a record malformati (skip riga JSON invalida, come `gemini_cost_audit.iter_records`).

## Test

- `test_translation_cost_audit.py`: append/iter/filtri (model, source_lang, target_lang, outcome, date), skip righe malformate, file mensile.
- `test/test_translation_pricing.py` (estendere) o nuovo: `_translation_provider_cost_eur` — math in/out, override env, virgola decimale, token None/0.
- `test_translation_audit_write.py`: `_write_translation_audit` per i 3 esiti → campi ricavo/costo/delta/outcome corretti; fallback pagamento legacy.
- `test_admin_translation_audit_endpoint.py`: auth 404 (no token) / 401 (token errato); records+aggregati; filtri; iniezione riga live; languages endpoint.

## Configurazione (env var nuove)

| Variabile | Descrizione | Default |
|---|---|---|
| `ABM_TRANSLATE_COST_IN_EUR_PER_MTOK` | Costo LLM input EUR per 1M token (base costo audit traduzioni) | `0.28` |
| `ABM_TRANSLATE_COST_OUT_EUR_PER_MTOK` | Costo LLM output EUR per 1M token | `2.30` |

Documentare in `PARAMETRI_CONFIGURAZIONE.md` (§3.6.2 traduzione) e nota audit in `md_files/TRADUZIONE_LIBRI.md`.

## Fuori scope (YAGNI)

- Recalc-params / kill-switch (non pertinenti alla traduzione).
- Tariffe token per-backend (scelta: coppia unica).
- Backfill retroattivo dei job pre-deploy.
- Cancel parziale con quota trattenuta (la traduzione rimborsa sempre l'intero).
