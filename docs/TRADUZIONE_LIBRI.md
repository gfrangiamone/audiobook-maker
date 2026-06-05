# Traduzione Libri — Architettura e Riferimento Implementativo

Feature introdotta sul branch TRADUZ (2026-06). Percorso wizard alternativo al TTS:
traduce il libro caricato (epub/pdf/txt/abm) in un'altra lingua via LLM, con
ottimizzazione AI opzionale **integrata nella stessa chiamata LLM**, pagamento
voucher/PayPal, consegna interattiva (SSE) o batch (email + token), output
`.epub`/`.abm`/`.txt`, e "adopt" del risultato come libro attivo per proseguire al TTS.

Spec: `docs/superpowers/specs/2026-06-05-translate-book-design.md` ·
Piano: `docs/superpowers/plans/2026-06-05-translate-book.md` ·
Parametri: `PARAMETRI_CONFIGURAZIONE.md` §3.6.2.

## Mappa dei moduli

| Componente | File | Ruolo |
|---|---|---|
| Core condiviso | `translation_core.py` | Libreria pura (no import app/Flask): config env, backend LLM, chunking, prompt, `call_llm` streaming con retry, titoli, writer abm/epub/txt, `UsageTracker` |
| CLI | `scripts/translate_abm.py` | Thin wrapper sul core: `parse_abm` locale, validazione lingue edge-tts, report costi. `--dry-run` per test senza LLM |
| Thread di traduzione | `generation_engine.py` → `run_translation(job_id)` | Pattern speculare a `run_optimization`: progress `tr_*`, heartbeat, refund, email batch, offload cold |
| Email batch | `generation_engine.py` → `_send_translation_email` + `_tr_email_texts` (7 lingue) | Token `download_type: "translated"`, link `/dl/{token}` |
| Endpoint API | `audiobook_app.py` (sezione "TRADUZIONE LIBRO") | estimate / translate / progress SSE / cancel / download / adopt / paypal order |
| Pricing | `payment.py` → `_estimate_translation_cost_eur(chars, optimize)` | + costanti `TRANSLATE_RATE_EUR_PER_MCHAR`, `TRANSLATE_MIN_COST_EUR` |
| Frontend | `static/js/app.js` (funzioni `tr*`/`_tr*`, `wizMode`) + `templates/_fragments/html_head.html` (`panelT3`, `panelT4`, `btnTranslate`, `btnTrAdopt`) | Wizard mode-aware |
| i18n | `templates/_fragments/i18n_data.js` (chiavi `tr_*`, 7 lingue) + `i18n/download_pages.json` (blocco `translated`) | |
| Storage | `storage_tiering.py` | `.epub`/`.txt` offloadabili; esclusi per suffisso `.filelist.txt`, `.metadata.txt` |

## translation_core.py — contratti chiave

- Config letta a ogni chiamata via funzioni (`api_key()`, `model_name()`, `chunk_chars()`…):
  env `ABM_TRANSLATE_*` con fallback `ABM_LLM_*`; numerici robusti (`_env_num`: virgola
  decimale ok, malformato → default + warning).
- Backend: `resolve_backend()` → `"vertex" | "apikey"` (auto: Vertex se `ABM_GCP_PROJECT_ID`
  + `ABM_GOOGLE_CREDENTIALS_FILE`, stessa auth di Gemini TTS; altrimenti API key DeepSeek).
  Solleva `TranslationConfigError`; `is_available()` per gating UI/endpoint.
- `call_llm(provider, system, user, *, model, usage, label, progress_cb, cancel_cb, log)`:
  streaming, retry esponenziale (`ABM_TRANSLATE_MAX_RETRIES`, default 4), fallback
  `stream_options` senza consumare tentativi, **completion vuota = errore ritentabile**
  (mai successo silenzioso). `cancel_cb()` → `TranslationCancelled` anche mid-stream.
- `UsageTracker`: stato usage PER-ESECUZIONE (mai globali di modulo — thread-safety con
  traduzioni concorrenti). `report()` → token reali o stima da caratteri.
- Ottimizzazione AI: `build_system_prompt(src, dst, optimize=True)` appende le regole TTS
  per-lingua (`prompt_opt_AI/`) al prompt di traduzione → **un solo passaggio LLM**.
- `translate_titles`: batch JSON, non-fatale (titoli originali su risposta invalida).
- Writer: `writer_for_format(fmt)` → `write_abm | write_epub | write_txt`, firma comune
  `(out_path, manifest_src, chapters, cover, source, target, optimize)`. Il manifest .abm
  porta `translated_from`/`translated_at`.

## Flusso operativo

1. **Entrata** (panel2): bottone «Traduci» (`goToTranslate()`) — richiede capitoli
   selezionati; si traducono (e pagano) **solo i selezionati**.
2. **Config** (`panelT3`, step 3 con `wizMode='translate'`): lingua origine (precompilata
   da `bookData.language`), destinazione (entrambe da lingue voci edge-tts), formato,
   nome file (precompilato dal titolo), toggle ottimizzazione AI, stima costo, voucher.
3. **Stima** — `GET /api/translate_estimate/<job_id>?target&optimize&selected_chapters`:
   ```
   raw = chars/1M × ABM_TRANSLATE_COST (+ chars/1M × ABM_LLM_RATE_EUR_PER_MCHAR se optimize)
   raw ≤ ABM_LLM_FREE_THRESHOLD_EUR → gratis ; altrimenti dovuto = max(raw, ABM_TRANSLATE_MIN_COST)
   ```
   Risposta include `available` (gating: bottone Avvia disabilitato se backend assente).
4. **Avvio** — `POST /api/translate`: validazioni (formato, lingue ISO, origine≠destinazione,
   destinazione ∈ lingue edge-tts), claim atomico stato `analyzed|translated → translating`
   sotto `_jobs_lock`, slot LLM **condiviso con l'ottimizzazione**
   (`_active_optimizing_for_client_unlocked` conta `optimizing` + `translating`),
   **validazione batch email PRIMA del consumo pagamento** (invariante anti-stranding,
   applicata anche a `/api/optimize`), consumo voucher/PayPal (importo = `due_eur`),
   spawn thread. Activity log: `TRANSLATE`.
5. **Esecuzione** (`run_translation`): per capitolo selezionato → chunk 20k paragraph-aware
   → `call_llm`; titoli in coda; scrittura in `<job_dir>/output_<epoch>/<nome>.<fmt>`;
   campi job `translated_path/name/chapters/lang/optimized`. Heartbeat 60s via `last_poll`
   (SSE lo aggiorna; **bypass se `email_registered`**); annullo via `tr_cancelled`
   (endpoint `POST /api/translate_cancel`).
6. **Progress** — `GET /api/translate_progress/<job_id>` (SSE): campi `tr_*`
   (`tr_streamed_chars` per la barra), stati terminali `error | cancelled | translated`.
7. **Consegna interattiva** (panel5 riusato): `GET /api/download_translation/<job_id>`
   (fallback cold) + bottone «Genera audio da questa traduzione».
8. **Consegna batch**: `_send_translation_email` → token con `download_type:"translated"`
   + snapshot `translated_path/name` → pagina `/dl/<token>` (ramo `translated`,
   availability locale+cold) → `GET /dl/<token>/translated` (ricostruzione per-epoch,
   `_try_cold_serve`, log `DOWNLOAD_TRANSLATION_TOKEN`). Email tardiva:
   `/api/register_email` con kind `translated` (allowlist).
9. **Adopt** — `POST /api/translate_adopt/<job_id>`: sostituisce `info.chapters` con i
   capitoli tradotti (rinumerati 1..n, `Chapter` di `epub_to_tts`), `info.language` =
   destinazione, stato → `analyzed`; se la traduzione era ottimizzata →
   `ai_optimized=True` + `optimized_chapters` (niente doppio pagamento ottimizzazione).
   One-shot (un secondo adopt → 400); il download della traduzione resta possibile.
   Frontend: `adoptTranslation()` aggiorna `bookData`, `wizMode='audio'`, re-render
   capitoli (`fillPreview`), → pannello voci con lingua preselezionata.

## Gestione errori, pagamenti, retention

- Chunk fallito dopo i retry → job `error` + **refund completo** (`_refund_job_payment`,
  label "traduzione"); annullo/heartbeat perso → stato torna `analyzed` + refund `cancel`
  (lato JS `trPaymentToken` viene azzerato: il voucher riaccreditato va ri-validato).
- **Email di completamento non-fatale**: se fallisce, il job resta `translated` e NON
  rimborsa (il file è consegnabile — niente double-give file+rimborso).
- Titoli falliti → originali (non fatale). Traduzione **non registrata in
  `pending_jobs`**: il recovery non può riprendere una traduzione a metà (evita la
  classe di incidenti B1 sui job rimborsati).
- Retention/cold: standard (token 24h); output tradotti offloadati su R2 come gli
  output audio (`.epub`/`.txt` ora offloadabili); `_token_cold_available` considera
  `translated_path`.

## Frontend — punti di aggancio

- `wizMode = 'audio' | 'translate'`: `goToStep()` risolve step 3→`panelT3` e
  4→`panelT4` in translate mode; etichette pallini 3/4 swappate da
  `_applyWizModeLabels()` (`wiz_step3_tr`/`wiz_step4_tr`).
- `_showPaymentModal(cost, chars, orderOpts?)`: terzo parametro opzionale
  `{endpoint, body}` per creare l'ordine su `/api/paypal_create_order_translate`
  (importo server-side; ri-validato al consumo). NB: il blocco PayPal SDK del modal è
  attualmente commentato a livello app — il percorso vivo è il voucher.
- `resetAll()` azzera tutto lo stato `tr*` e i campi di panelT3/T4.
- Errore in panelT4: il bottone Annulla diventa «Indietro» (no dead-end);
  `startTranslation` ha guard anti double-submit (`window._trStarting`).

## Test

`test/test_translation_core.py` (25: core, retry, cancel, writer) ·
`test_translation_pricing.py` (6: soglie/floor/virgola) ·
`test_run_translation.py` (7: successo/selezione/refund/heartbeat/batch/email-non-fatale) ·
`test_translate_endpoints.py` (19: estimate/validazioni/pagamento/concorrenza/dl/adopt/paypal).
Smoke CLI: `python scripts/translate_abm.py libro.abm it en --dry-run`.

## Modifiche a flussi pre-esistenti (introdotte da questa feature)

1. `/api/optimize`: validazione batch email spostata PRIMA del consumo pagamento.
2. Slot LLM per client conta anche lo stato `translating`.
3. `storage_tiering`: `.epub`/`.txt` offloadabili (con esclusioni per suffisso).
4. `/api/register_email`: allowlist `download_type` (prima passthrough).
5. `_generate_optimized_abm`: logica cover estratta in `_job_cover_bytes` (condivisa).
6. `_refund_job_payment`: label rimborso per tipo job (traduzione vs ottimizzazione).
7. Label UI `btn_export_abm`: «Esporta .ABM» → «.ABM».
