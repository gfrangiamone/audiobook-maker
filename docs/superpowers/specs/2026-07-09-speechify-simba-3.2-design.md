# Design — Integrazione TTS Speechify Simba-3.2 (voce PREMIUM inglese)

Data: 2026-07-09
Branch: `SPEECHIFY`
Stato: approvato (brainstorming) — in attesa di piano di implementazione

## 1. Obiettivo

Aggiungere il modello TTS **Speechify Simba-3.2** come nuova opzione "voce PREMIUM"
nella web app Audiobook Maker, **disponibile solo quando la lingua di lettura è
inglese**. Il modello affianca i modelli Gemini esistenti nel tab Premium, con una
lieve ristrutturazione dell'interfaccia. La concorrenza verso l'API Speechify è
governata da parametri di sistema (dipende dall'abbonamento), il costo/ricarico
sono parametrizzati, la API key è un env di sistema. Sviluppo su branch dedicato.

### Ambito (in scope)
- Solo modello `simba-3.2` (flagship English-only).
- Solo lingua di lettura **inglese** (locale `en-US` / `en-GB`).
- Solo engine **speech** (`POST /v1/audio/speech`): restituisce `billable_characters_count`
  reali e WAV, coerente col pattern per-chunk esistente.
- Emozioni di lettura via SSML `<speechify:style emotion="...">`.
- Pagamento premium riusando la pipeline Gemini (voucher + PayPal, soglia gratuità).

### Fuori ambito (YAGNI)
- Modelli `simba-multilingual` e `simba-english`.
- Lingue diverse dall'inglese.
- Engine **stream** (`/v1/audio/stream`).
- Denoise FFmpeg: il fruscio riscontrato riguardava **solo** il modello
  multilingue; `simba-3.2` ne è privo.
- Riconciliazione post-hoc del costo (il pagamento è upfront, fisso).

## 2. Riferimento API (verificato empiricamente)

- Endpoint sintesi: `POST https://api.speechify.ai/v1/audio/speech`
  (max ~2000 char/richiesta; risposta JSON base64 `audio_data` = WAV completo +
  `billable_characters_count`). Auth `Bearer`.
- Endpoint catalogo: `GET https://api.speechify.ai/v1/voices` (paginato via
  `next_cursor` / `has_more`).
- Voci `simba-3.2` disponibili: **8**, tutte con suffisso `_32`:
  - `en-US`: `dominic_32`, `geffen_32`, `harper_32`, `wyatt_32`
  - `en-GB`: `beatrice_32`, `edmund_32`, `hugh_32`, `imogen_32`
- WAV reale prodotto dalle voci `_32`: **48000 Hz, mono, 16-bit** (l'header va
  riletto dinamicamente, non assunto).
- Emozioni SSML accettate (HTTP 200) da `simba-3.2`: tutte e 13 documentate —
  `angry, cheerful, sad, terrified, relaxed, fearful, surprised, calm, assertive,
  energetic, warm, direct, bright`. Nota: l'API **non valida** l'enum (ignora
  valori ignoti restituendo comunque audio) → il set esposto è una scelta di
  prodotto, non un vincolo API.
- Rate limit: HTTP 429 con header `Retry-After` da onorare.

Riferimento implementativo di partenza: lo script standalone collaudato
`scripts/tts_speechify_test.py` (parsing WAV→PCM, retry 429/`Retry-After`,
preflight voce↔modello, assemblaggio M4B via helper "puri" del progetto).

## 3. Architettura

Speechify diventa un **4° engine TTS** accanto a `edge` (gratis, MP3), `google`
(Google Cloud Chirp3-HD, MP3), `gemini` (premium, PCM).

### 3.1 Nuovo modulo `speechify_tts.py`
Speculare a `gemini_tts.py`. Superficie pubblica:
- `is_available()` — abilitato sse `ABM_SPEECHIFY_API_KEY` è valorizzato.
- `get_voices(ui_lang)` — catalogo voci per l'UI (solo EN; id
  `speechify:simba-3.2:<voiceId>`, gender, locale, label modello "Simba (English)").
- `EMOTIONS` — lista ordinata delle 13 emozioni + concetto "nessuna (neutro)".
- `ACCENTS` — `en-US`, `en-GB` (locale che filtrano le voci e valorizzano `language`).
- `synthesize(text, voice_id, output_path, emotion=None, rate="+0%", accent=None, ...)`
  — engine speech, WAV→PCM, retry 429/`Retry-After`, aggiorna i char fatturabili.
- Pricing: `compute_user_price_eur(chars)`, `estimate_book_cost(chapters, ...)`.
- Concorrenza: gate globale + reader dinamici dei parametri (vedi §5).
- Reader di config dinamici (`os.environ.get` a ogni chiamata, come `gemini_tts`).

### 3.2 `voice_utils.py`
- `SPEECHIFY_VOICE_PREFIX = "speechify:"`
- `is_speechify_voice(voice_id)`

### 3.3 `generation_engine.py`
- `_engine_for_voice(voice)`: nuovo ramo → ritorna `"speechify"` per prefisso
  `speechify:`.
- `_synthesize_chunk(...)`: nuovo branch che invoca `generate_chunk_pcm_speechify(...)`;
  propaga eventuali errori "fatali" (auth/voce) senza silenziare, gestisce il gate
  di concorrenza (§5).
- Contabilizzazione char fatturabili per il consuntivo.

### 3.4 `tts_split.py`
- `generate_chunk_pcm_speechify(text, voice_id, output_path, emotion=None,
  rate="+0%", accent=None, max_retries=3)` — riusa la logica dello script standalone
  (speech endpoint, WAV→PCM, retry). Cap chunk ≤ ~1800 char.

### 3.5 Assemblaggio audio
Riusa il percorso **PCM** già esistente (come Gemini): estrazione PCM dal WAV
(header riletto dinamicamente → 48 kHz mono 16-bit), concat, singola passata
AAC/M4B. `loudness_normalization` lato Speechify **ON** (volume coerente tra
chunk). Il sample rate dell'encode segue quello reale del WAV. Un job usa una
sola voce/engine → nessun mix di sample rate nello stesso job.

## 4. Interfaccia utente (frontend)

Un solo tab Premium. Ordine elementi **generalizzato a tutti i premium**
(accento sopra la voce):

```
lingua di lettura → modello → accento → voce → (istruzioni di stile | emozioni)
```

### 4.1 Dropdown modello `#vmPremium`
- Le opzioni modello vengono ricostruite al cambio di lingua di lettura.
- Se lingua = **inglese**: compare l'opzione **"Simba (English)"**, che diventa il
  **modello PREMIUM di default** (preselezionato). Restano disponibili anche i
  modelli Gemini.
- Se lingua ≠ inglese: solo modelli Gemini (nessun Simba).

### 4.2 Modello = Simba
- **Accento** (`en-US` / `en-GB`): filtra le 8 voci `_32` per locale **e** viene
  inviato come `language`. L'accento è sopra la voce e ne condiziona l'elenco.
- **Voce**: le 4 voci del locale selezionato.
- Il box **"Istruzioni di stile"** (`#geminiStyle`) è sostituito da una combo
  **"Emozioni"** (`#speechifyEmotion`): `Nessuna (neutro)` + le 13 emozioni.

### 4.3 Modello = Gemini
- Comportamento attuale invariato, con l'unica differenza dell'accento ora **sopra**
  la voce (riordino uniforme). Textarea "Istruzioni di stile" visibile, combo
  emozioni nascosta.

### 4.4 Toggle stile/emozioni
- Simba → mostra combo Emozioni, nasconde textarea Stile.
- Gemini → mostra textarea Stile, nasconde combo Emozioni.

### 4.5 Payload verso `/api/generate` e `/api/preview_audio`
- `voice = speechify:simba-3.2:<voiceId>`
- nuovo campo `speechify_emotion` (stringa vuota = nessuna)
- `accent` = locale (`en-US` / `en-GB`)
- La preview usa lo stesso engine/pipeline con `max_attempts=1`.

## 5. Concorrenza (2 parametri + admission gating trasparente)

Due parametri distinti:
- **`ABM_SPEECHIFY_MAX_CONCURRENCY`** (globale, default **3**) = concorrenza
  consentita dall'abbonamento. Semaforo **globale** condiviso tra tutti i job e
  client.
- **`ABM_SPEECHIFY_PER_JOB_CONCURRENCY`** (default **1**) = numero massimo di
  chiamate API simultanee di un singolo job (dimensione del suo worker pool).

### 5.1 Admission gating
Quando un job Simba entra nella **fase di sintesi**, prenota `min(K, N)` permessi
dal pool globale (con `K` = per-job, `N` = globale). Se non ci sono slot liberi
**attende** in modo trasparente per l'utente (il job resta in stato "in attesa",
nessun errore) finché un altro job libera slot. I permessi sono rilasciati a fine
sintesi (prima dell'assemblaggio), così altri job in coda possono partire mentre
uno assembla/encoda.

### 5.2 Invariante
Somma dei `K` dei job attivi ≤ `N` → le richieste API simultanee verso Speechify
non superano mai il limite dell'abbonamento.

### 5.3 Dettagli
- Gate implementato con un contatore/condition variable modulo-level in
  `speechify_tts.py` che **rilegge i parametri a runtime** (admin può cambiarli
  senza restart), analogo al pattern `_active_reservations` di `gemini_tts.py`.
- `min(K, N)` protegge da misconfig `K > N` (il job prende al più `N`).
- `Retry-After` su 429 come rete di sicurezza aggiuntiva.
- Il gate è per-processo (l'app gira a processo singolo in produzione — coerente
  con l'attuale stato di deploy).

## 6. Pricing & pagamento

Riusa la pipeline premium Gemini (voucher + PayPal, soglia gratuità, fee PayPal,
conversione USD→EUR). Base di costo sui **caratteri**:

```
cost_usd  = chars / 1e6 × ABM_SPEECHIFY_COST_USD_PER_MCHAR
base_eur  = cost_usd × USD_EUR_RATE × (1 + ABM_SPEECHIFY_MARGIN_PERCENT / 100)
gross_eur = (base_eur + PAYPAL_FIXED_FEE_EUR) / (1 − PAYPAL_PERCENT_FEE / 100)
is_free   = gross_eur < ABM_SPEECHIFY_FREE_THRESHOLD_EUR   → user_price = 0
```

- **Stima e addebito su caratteri di input** (somma sui capitoli selezionati):
  deterministico e trasparente. Nessuna riconciliazione (pagamento upfront fisso).
- `USD_EUR_RATE`, `PAYPAL_FIXED_FEE_EUR`, `PAYPAL_PERCENT_FEE` riusano le costanti
  condivise esistenti (evita divergenze).
- Integrazione:
  - `/api/combined_estimate`: il branch premium riconosce l'engine (gemini vs
    speechify) e calcola di conseguenza; ritorna `premium_eur` + breakdown.
  - Create-order / refund premium esistenti riusati (stesso modale, etichetta
    "Voci PREMIUM").
  - Refund su errore/annullamento tramite il path premium esistente.

## 7. Parametri di sistema (env `ABM_*`)

| Variabile | Significato | Default |
|-----------|-------------|---------|
| `ABM_SPEECHIFY_API_KEY` | API key Speechify (abilita l'engine se presente) | *(vuoto)* |
| `ABM_SPEECHIFY_MAX_CONCURRENCY` | Concorrenza API globale (abbonamento) | `3` |
| `ABM_SPEECHIFY_PER_JOB_CONCURRENCY` | Chiamate API simultanee per job | `1` |
| `ABM_SPEECHIFY_COST_USD_PER_MCHAR` | Costo USD per 1M caratteri | `11.18` |
| `ABM_SPEECHIFY_MARGIN_PERCENT` | Ricarico % | `60` |
| `ABM_SPEECHIFY_FREE_THRESHOLD_EUR` | Soglia gratuità | `0.50` |

Costanti condivise riusate: USD→EUR e fee PayPal (già definite per Gemini).
Il modello è fisso a `simba-3.2` (costante interna, non env). Documentare tutto
in `PARAMETRI_CONFIGURAZIONE.md`.

## 8. `/api/voices`

Merge del catalogo Speechify quando `speechify_tts.is_available()`:
- Solo voci EN (locale `en-US` / `en-GB`).
- Espone id, gender, locale, label modello "Simba (English)".
- Stato/kill-switch coerente col pattern Gemini (`_speechify_status`).

## 9. Testing

Test con HTTP mockato (nessuna chiamata reale in CI):
- Pricing math (soglia gratuità, margine, fee, USD→EUR).
- Gate di concorrenza: rispetto di `N` con `K` per-job; job in eccesso attende e
  parte quando si libera uno slot; `min(K, N)` su misconfig.
- Gating English-only del modello (Simba assente per lingue non-EN; default Simba
  su EN).
- `_engine_for_voice` → `"speechify"`; parsing voice-id `speechify:simba-3.2:...`.
- Catalogo voci + filtro per accento/locale; set emozioni.
- Merge `/api/voices` quando disponibile / assente quando key mancante.

Seguire i pattern dei test esistenti in `test/`.

## 10. Branch & deploy

- Sviluppo sul branch **`SPEECHIFY`** (worktree dedicato), partito da `main`.
- Nessun push/merge senza conferma esplicita dell'utente.
- Aggiornare `PARAMETRI_CONFIGURAZIONE.md` e, se necessario, `CLAUDE.md`
  (quest'ultimo non tracciato) prima di un'eventuale pubblicazione.

## 11. Punti aperti / rischi

- Verificare empiricamente la **resa** delle emozioni su `simba-3.2` (l'API le
  accetta ma non le valida): scegliere in fase di test quali esporre se alcune
  risultassero inefficaci.
- Confermare il **costo reale** per 1M char sul piano Speechify in uso
  (`ABM_SPEECHIFY_COST_USD_PER_MCHAR` default 11.18 da verificare in fattura).
- La stima su caratteri di input può divergere leggermente dai
  `billable_characters_count` reali (SSML/normalizzazione): accettato, il prezzo
  mostrato all'utente è quello addebitato.
