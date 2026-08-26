# Backend Cloudflare per Gemini 3.1 Flash TTS in produzione — Design

**Data:** 2026-08-26
**Stato:** design approvato, in attesa di piano implementativo
**Banco di prova a monte:** [2026-08-25-cloudflare-gemini-tts-bench-design.md](2026-08-25-cloudflare-gemini-tts-bench-design.md)

## 1. Obiettivo

Portare in produzione la sintesi Gemini 3.1 Flash TTS su **Cloudflare Workers AI**
al posto di Vertex AI diretto, mantenendo Vertex come **backend di emergenza**
attivabile automaticamente quando Cloudflare risulta fuori uso, e rientrabile
manualmente da console admin.

Il banco di prova (738 chiamate su due libri interi, 1049 tentativi complessivi)
ha misurato una tariffa di **0,75 / 12,00 USD per Mtok** contro **1,00 / 20,00**
del listino Google per lo stesso modello: **−40% sull'output**, che pesa il
99,05% del costo di un audiolibro. Riconciliazione contro la dashboard
Cloudflare: **−0,39%** di scostamento aggregato.

### 1.1 Non-obiettivi

- Non si tocca `flash25` (Gemini 2.5): resta su Vertex. Vedi §4.3.
- Non si introduce canary o rollout percentuale: lo switch è totale (§7).
- Non si introduce fallback per-chunk verso Cloudflare quando il backend attivo
  è Vertex: il ritorno è sempre e solo manuale.
- Non si modifica il motore di retry, il budget per job, il kill-switch o la
  macchina di rimborso: il design li riusa senza duplicarli.

## 2. Decisioni vincolanti

Prese esplicitamente dal committente, sono l'asse portante del design.

| # | Decisione | Conseguenza progettuale |
|---|---|---|
| D1 | **Prezzo e stime sempre su base Cloudflare**, anche quando esegue Vertex | La base di prezzo è una costante: non esiste alcun caso in cui il prezzo si muove al variare del backend. Il maggior costo di Vertex lo assorbe il margine. |
| D2 | **Failover automatico su Vertex** quando Cloudflare è fuori uso | Serve un circuit breaker con stato persistito, non una semplice `except`. |
| D3 | **Il job in corso prosegue su Vertex dal chunk corrente** | Verificato dal committente che l'audio dei due backend è indistinguibile. Nessun job perso, nessun rimborso al trip. |
| D4 | **Email immediata all'admin** all'ingresso di Vertex | Non nel digest: lo stato è eccezionale e deve durare poco. |
| D5 | **Rientro su Cloudflare da pulsante in console admin** | Il rientro non è mai automatico: eviterebbe il flapping e toglierebbe all'operatore il controllo. |
| D6 | **Quota di risparmio ceduta al cliente parametrica**, per ora 50% | Cursore regolabile in produzione senza toccare codice. |
| D7 | **L'errore 2017 si previene nel chunking** | Il fix è indipendente dal backend e giova anche a Vertex. |

## 3. Vincoli e invarianti del sistema esistente

Il design è costruito su questi fatti, verificati nel codice.

1. **`gemini_tts._resolve_backend()` esiste già** e astrae `"vertex" | "apikey" | None`
   (`gemini_tts.py:173`). Cloudflare è un terzo valore, non un modulo parallelo.
2. **Solo `synthesize()` fa I/O di rete** (`gemini_tts.py:2136`). Le altre ~30
   funzioni pubbliche del modulo sono pure o toccano solo file locali. La
   superficie da astrarre è quindi una sola funzione.
3. **Il formato audio coincide**: Cloudflare restituisce
   `data:audio/l16;base64,…` che decodifica in PCM s16le 24 kHz mono, lo stesso
   payload che Vertex consegna in `inline_data`. Nessun resampling, nessuna
   conversione. È l'invariante che rende possibile D3.
4. **`_audio_tokens_per_second` vale già 25 per flash31** (`gemini_tts.py:65`),
   corretto in seguito a un audit su 256 job reali. Coincide con il tasso
   ufficiale Google e con la riconciliazione Cloudflare: la derivazione dei
   token dai byte PCM è valida per entrambi i backend, con una sola costante.
5. **Le eccezioni che attraversano il confine di `synthesize()`** sono
   `GeminiQuotaExhausted`, `GeminiBudgetExceeded`, `GeminiUnavailable` (catturate
   in `tts_split.py:827,924` e `generation_engine.py:5800,5872`) più
   `RuntimeError` generico. `GeminiEmptyResponse` esce come errore generico e
   viene contata come chunk fallito. **Questo vocabolario non cambia**: è ciò che
   consente di riusare la macchina di rimborso B1–B4 senza riscriverla.
6. **`_BACKEND` è una cache module-level congelata al primo uso**
   (`gemini_tts.py:169`). Il failover richiede uno stato mutabile: è la sola
   modifica invasiva prevista su `gemini_tts`.

## 4. Architettura

### 4.1 Estrazione del trasporto

Nuovo modulo foglia **`gemini_transport.py`**. Nessun import da `gemini_tts`
(che invece lo importa), nessuno stato globale: riceve tutto per argomento.

Contratto unico, identico per i due trasporti:

```python
def call(*, final_text, voice_name, model_key, model_id,
         timeout_ms, temperature):
    """Esegue una singola sintesi.

    Returns:
        {"pcm": bytes,
         "input_tokens": int | None,   # None se il backend non li espone
         "output_tokens": int | None}

    Raises:
        TransportError  (sempre e solo questa)
    """
```

Errore normalizzato:

```python
class TransportError(RuntimeError):
    def __init__(self, message, *, kind, retry_after_sec=None,
                 billed=False, http_status=None, provider_code=None):
        ...
```

`kind` appartiene a un insieme chiuso:

| `kind` | Significato | Chi lo gestisce |
|---|---|---|
| `retryable` | fallimento transitorio della singola chiamata | il loop di retry di `synthesize()` |
| `rate_limited` | throttling, con eventuale `retry_after_sec` | il loop, con attesa |
| `quota_daily` | quota giornaliera esaurita | `GeminiQuotaExhausted` |
| `content_rejected` | il testo è stato rifiutato, ritentarlo è inutile | `GeminiEmptyResponse(retryable=False)` |
| `backend_down` | **il backend è fuori uso**, non la singola chiamata | il circuit breaker (§4.4) |
| `fatal` | errore non classificabile, dopo i tentativi | `RuntimeError` |

`billed=True` marca le risposte che il provider fattura anche se inutilizzabili
(su Cloudflare: qualunque HTTP 200, anche senza campo `audio`). Serve alla
contabilità, non al controllo di flusso.

`synthesize()` conserva integralmente retry, backoff, budget, costruzione del
prompt, throttle, scrittura del PCM e forma del dizionario di ritorno. **Nessuna
politica viene duplicata nei trasporti.** Il criterio di accettazione della fase
di estrazione è che la suite di test Gemini esistente resti verde *senza una
sola modifica ai test*.

### 4.2 Trasporto Cloudflare

```
POST https://api.cloudflare.com/client/v4/accounts/{ABM_CF_ACCOUNT_ID}/ai/run
Authorization: Bearer {ABM_CF_API_TOKEN}
{"model": "google/gemini-3.1-flash-tts",
 "input": {"text": ..., "voice": ..., "temperature": ...}}
```

Il campo del testo è **`text`**, non `prompt` (verificato sul banco: `prompt`
produce un 400).

Mappatura degli esiti, tutta misurata sul campo:

| Esito Cloudflare | `kind` | `billed` | Note |
|---|---|---|---|
| 200 con `result.audio` | — successo | sì | data URI `audio/l16` → PCM |
| 200 senza `result.audio` | `retryable` | **sì** | 8 casi su 738 nel banco |
| 400 `code 7003` | `retryable` | no | "User Input Error" ma transitorio: ritentarlo è gratis |
| 422 `code 2017` | `content_rejected` | no | moderazione. Prevenuto dal §5 |
| 402 `code 2021` | **`backend_down`** | no | credito prepagato esaurito |
| 429 | `rate_limited` | no | 0 occorrenze nel banco fino a concorrenza 8 |
| 5xx, timeout, errore di rete | `retryable`, poi `backend_down` dopo N (§4.4) | no | |

**Doctrine di fatturazione verificata:** un HTTP 200 è fatturato a prescindere dal
contenuto del corpo; 4xx, 5xx e timeout non lo sono (il log di AI Gateway mostra
`- in`, `- out`, `$ -` sulle righe 400). Un timeout lato client resta ambiguo:
Cloudflare può avere generato e fatturato l'audio comunque.

Cloudflare **non restituisce metadati di uso**: il trasporto ritorna
`input_tokens=None, output_tokens=None` e `synthesize()` deriva (§4.6).

### 4.3 Risoluzione del backend, per modello

`_resolve_backend()` viene esteso a `"vertex" | "apikey" | "cloudflare" | None`
e diventa **per modello**: `_resolve_backend(model_key)`.

- `ABM_GEMINI_BACKEND=cloudflare` è **opt-in esplicito**. `auto` non seleziona
  mai Cloudflare: il rollback è togliere la variabile.
- Cloudflare richiede `ABM_CF_ACCOUNT_ID` e `ABM_CF_API_TOKEN`. Se mancano, il
  valore esplicito degrada a `vertex` se configurato, altrimenti `DISABLED`, e
  lo logga.
- `GEMINI_MODELS` guadagna `id_cloudflare`. Un modello **senza** `id_cloudflare`
  non è servibile da Cloudflare e va sempre su Vertex, anche con la variabile
  impostata. Oggi solo `flash31` ha l'id (`google/gemini-3.1-flash-tts`);
  `flash25` resta su Vertex finché non si verifica che Cloudflare lo ospiti.

`_BACKEND` diventa un dizionario per modello sotto `_BACKEND_LOCK`, mutabile
(serve al breaker), con reset esplicito per i test.

### 4.4 Circuit breaker e failover

Nuovo modulo foglia **`tts_backend_state.py`**: stato del breaker persistito in
`ABM_DATA_DIR/_tts_backend_state.json`, scrittura atomica (tmp+rename) come
`community_store`. Riceve il notificatore per iniezione (`configure(notifier=…)`)
seguendo la convenzione del progetto: nessun sotto-modulo importa
`audiobook_app`.

Stato:

```json
{"flash31": {"active": "vertex",
             "tripped_at": "2026-08-26T21:14:03Z",
             "trip_reason": "cf_credit_exhausted",
             "trip_detail": "HTTP 402 code 2021",
             "trip_job_id": "…",
             "consecutive_failures": 3,
             "notified": true}}
```

**Cosa fa scattare il trip:**

| Condizione | Scatta | Perché |
|---|---|---|
| `402 code 2021` credito esaurito | **subito, alla prima occorrenza** | nessun retry può risolverlo, è globale |
| 5xx / irraggiungibilità | dopo `ABM_CF_TRIP_FAILURES` (default 3) chiamate consecutive esaurite di tentativi | distingue un blip da un'indisponibilità |
| `429` | no | è throttling: lo assorbe il backoff |
| `400 code 7003` | no | transitorio e non fatturato |
| `422 code 2017` | **no** | è specifico del contenuto, non salute del backend |

Il contatore dei fallimenti consecutivi si azzera a ogni successo.

**Sequenza al trip**, tutta dentro il loop di `synthesize()`:

1. `tts_backend_state.trip(model_key, reason, detail, job_id)` — persiste e
   ritorna `True` solo al primo chiamante (idempotente sotto lock: con 8 thread
   concorrenti l'email parte una volta sola).
2. Se il trip è nuovo, invoca il notificatore → email immediata (§4.5).
3. **La stessa chiamata viene rieseguita subito su Vertex**, con il budget di
   tentativi residuo. Il chunk corrente non va perso: è esattamente D3.
4. Se Vertex non è configurato o non è pronto, solleva `GeminiUnavailable`: il
   job diventa fatale e la macchina di rimborso esistente fa il resto.

Dopo il trip, `_resolve_backend("flash31")` restituisce `"vertex"` per ogni
chiamata successiva, in ogni thread e attraverso i restart, finché non si
rientra.

**Preallarme sul credito.** Poiché il rientro è manuale, un esaurimento notturno
significa Vertex fino al mattino. Il breaker mantiene quindi un registro locale
della spesa Cloudflare, alimentato da ogni chiamata fatturata, e confronta con
il saldo dichiarato dall'operatore all'ultima ricarica
(`ABM_CF_CREDIT_BALANCE_EUR`, aggiornabile dalla console). Sotto
`ABM_CF_CREDIT_ALERT_EUR` (default 5,00) parte un'email di preallarme, una sola
volta per soglia. Se la ricognizione di Fase 0 individua un'API di saldo
Cloudflare, sostituisce il registro locale; il registro resta come fallback.

### 4.5 Notifica all'admin

Nuova `email_service._admin_notify_tts_backend_switch(...)`, sul modello di
`_admin_notify_gemini_failure` (`email_service.py:494`). Invio **immediato**,
fuori dal digest. Contenuto:

- backend ora attivo e backend precedente;
- causa del trip: codice provider, stato HTTP, messaggio troncato;
- job che ha scoperto il guasto e istante UTC;
- effetto economico corrente (§4.7): quanto margine si sta cedendo per ora di
  audio finché si resta su Vertex;
- istruzioni di rientro: ricarica il credito, poi il pulsante in `/admin`.

**Il token Cloudflare non compare mai** nell'email, nei log o nei messaggi di
errore. Vale per ogni artefatto prodotto da questo design.

### 4.6 Derivazione dei token

Quando il trasporto ritorna `None`, `synthesize()` deriva:

```
output_tokens = round(len(pcm) / (24000 * 2) * _audio_tokens_per_second(model_key))
input_tokens  = estimate_input_tokens(final_text, language)
```

Il dizionario di ritorno guadagna due campi:

- `"backend"`: `"cloudflare" | "vertex" | "apikey"` — quale ha eseguito;
- `"tokens_measured"`: `True` se dal provider, `False` se derivati.

`record_usage()` (`gemini_tts.py:1298`) li propaga negli aggregati. Senza questa
distinzione il consuntivo si autoconferma: riconcilierebbe una stima contro sé
stessa. Il modello di derivazione è affidabile (§3.4) ma resta un modello, e il
registro deve dire quale delle due cose sta guardando.

### 4.7 Modello di prezzo

Si separano due nozioni oggi coincidenti.

**Base di prezzo** — quanto paga il cliente. Costante, sempre Cloudflare (D1):

```
share    = ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT / 100            # default 0,50
cf_eff   = tariffa_cloudflare * (1 + ABM_CF_CREDIT_TOPUP_FEE)    # default 5%
tariffa_prezzo = google_listino − (google_listino − cf_eff) * share
```

Con i valori di default, per `flash31`:

| | Google listino | Cloudflare + 5% | Base di prezzo (share 50%) |
|---|---|---|---|
| input USD/Mtok | 1,00 | 0,7875 | **0,89375** |
| output USD/Mtok | 20,00 | 12,60 | **16,30** |

Effetto per il cliente: **−18,5% sulla tariffa output**, cioè sul 99% del prezzo.
`share = 0` restituisce esattamente il prezzo di oggi; `share = 1` cede tutto il
risparmio. Il cursore si muove in produzione senza rilasci.

`compute_user_price_eur()` resta invariata: margine `default_margin_percent`
(25% su flash31) più gross-up PayPal. Cambia solo la base su cui lavora.

**Base di contabilità** — quanto costa davvero. Sempre la tariffa del backend che
ha eseguito, con il 5% di ricarica incluso quando è Cloudflare. Nuova
`actual_cost_breakdown(input_tokens, output_tokens, model_key, backend)`
affiancata a `google_cost_breakdown()`, che conserva la semantica attuale di
"costo a listino Google".

Ne segue che il `default_margin_percent` dichiarato (25%) non è più il margine
effettivo: è il ricarico sulla *base di prezzo*, mentre il margine vero dipende da
chi esegue. Il ricavo netto per Mtok di output vale `16,30 × 1,25 = 20,375` USD in
entrambi i regimi, ma il costo no:

| Regime | Costo reale | Ricavo netto | Margine effettivo |
|---|---|---|---|
| Cloudflare (share 50%) | 12,60 | 20,375 | **+61,7%** |
| Failover su Vertex (share 50%) | 20,00 | 20,375 | **+1,9%** |

In failover l'operatore lavora quindi **quasi in pareggio**, non semplicemente con
meno margine. È il fatto economico che giustifica D4 e il preallarme sul credito:
lo stato eccezionale non è costoso, è a somma zero, e deve durare ore, non giorni.

Lo scarto in regime normale non è un errore da correggere ma la metà di risparmio
trattenuta, ed è visibile a consuntivo perché ricavo e costo reale sono registrati
separatamente.

Il parametro `share` ha quindi un secondo effetto, meno ovvio del primo: cedere
risparmio al cliente cede anche il cuscinetto che rende sopportabile il failover.
A `share = 0` il prezzo resta quello di oggi, il margine su Cloudflare sale a ~98%
e in failover torna esattamente al 25% attuale — cioè il failover diventa
economicamente indolore. A `share = 1` il failover andrebbe in perdita. Il 50%
scelto è un compromesso consapevole, non un default neutro.

**Due conseguenze da monitorare dopo lo switch:**

1. Più job scendono sotto `FREE_THRESHOLD_EUR` (0,50 €) e diventano gratuiti.
   Con share 50% l'effetto è contenuto ma va misurato, non stimato.
2. Il prezzo cambia per i clienti al momento dello switch. Non c'è deriva
   *durante* un preventivo — la base è costante e il price lock D1 del
   precedente incidente resta in vigore — ma il listino pubblico si abbassa da
   un rilascio all'altro.

## 5. Prevenzione dell'errore 2017 nel chunking

Il banco ha isolato la classe di testi che Cloudflare rifiuta con
`422 code 2017` (moderazione):

| Testo | Esito |
|---|---|
| `XIV. XV. XVI. XVII. …` | 422 |
| `14. 15. 16.` | 422 |
| `Capitolo XX.` | **422** |
| `AB. CD. EF.` | 200 |
| `Nel capitolo XX si racconta la partenza.` | 200 |

Il fattore comune non è l'assenza di lettere — `Capitolo XX.` ne ha otto — ma la
**densità di enumerazione in un frammento corto**.

`_plan_chunks()` (`tts_split.py:421`) può produrre esattamente questi frammenti:
antepone il titolo come `f"{ch.title}.\n\n{clean_text}"`, quindi un capitolo di
puro separatore (`XIV`, con testo vuoto o quasi) genera un chunk degenere.

**Regola.** Dopo `split_text_into_chunks`, un chunk è *degenere* se:

- è più corto di `ABM_TTS_MIN_CHUNK_CHARS` (default 40), **oppure**
- è più corto di 120 caratteri **e** almeno metà dei suoi token, tolta la
  punteggiatura, sono numeri arabi o numerali romani.

Un chunk degenere viene **fuso con il successivo**; se è l'ultimo, con il
precedente. La fusione è sempre sicura: un titolo di capitolo unito al primo
paragrafo si legge naturalmente, ed è ciò che il testo fa già nella maggioranza
dei casi.

Se dopo la fusione un capitolo resta con un unico chunk ancora degenere — il caso
del capitolo che è letteralmente `XIV.` — **la sintesi viene saltata** e si emette
un breve silenzio, contato come chunk saltato e non come fallito. Sintetizzare
`XIV.` non aggiunge nulla all'audiolibro e rischia di rendere fatale un job.

Il fix è indipendente dal backend, riduce anche su Vertex il numero di chiamate
inutili, e va in produzione **da solo, prima di tutto il resto**.

## 6. Quote, budget e throttle

`_check_rpd_cap()` e `_throttle_rpm()` codificano quote Google. Diventano
condizionali al backend effettivo:

- backend `vertex`/`apikey` → invariati;
- backend `cloudflare` → **saltati**. Non esiste RPD, e il banco non ha visto un
  solo 429 fino a concorrenza 8 su 1049 tentativi.

Il **budget per job e giornaliero** (`GeminiBudgetExceeded`) resta attivo su
entrambi: è una guardia sul denaro, non sulla quota. Calcola sulla base di
contabilità (§4.7), cioè sul costo reale del backend che sta eseguendo.

## 7. Rollout e rollback

Sequenza in due rilasci distinti:

1. **Rilascio con codice dormiente.** Tutto in produzione con
   `ABM_GEMINI_BACKEND` invariato: comportamento identico a oggi, byte per byte.
   Verificabile perché la suite esistente resta verde senza modifiche.
2. **Switch.** `ABM_GEMINI_BACKEND=cloudflare` + `ABM_CF_ACCOUNT_ID` +
   `ABM_CF_API_TOKEN` nell'unit systemd, restart. Nessun deploy di codice.

**Rollback:** rimuovere `ABM_GEMINI_BACKEND=cloudflare` e riavviare. Simmetrico
allo switch, non richiede un rilascio, non tocca il breaker.

Nota operativa: le variabili `ABM_*` di produzione vivono nell'unit systemd e
**non sono ereditate da una shell ssh**. Vanno esportate esplicitamente per
qualunque verifica manuale.

## 8. Console admin

Nuovo `GET/POST /api/admin/tts_backend`, guardato da `_admin_auth_ok()` come i
quattro endpoint admin esistenti.

- `GET` → per ogni modello: backend configurato, backend attivo, stato del
  breaker, istante e causa dell'ultimo trip, spesa Cloudflare del mese, saldo
  credito residuo stimato.
- `POST {"action": "reset", "model": "flash31"}` → azzera il breaker e riporta
  il traffico su Cloudflare. È il pulsante di D5. Registra l'operazione nel log
  attività.
- `POST {"action": "set_balance", "eur": …}` → aggiorna il saldo dichiarato dopo
  una ricarica, riarmando il preallarme.

Nel pannello `/admin/log-activity`, accanto a Stats, un riquadro con lo stato del
backend e il pulsante di rientro, abilitato solo quando il breaker è scattato.

## 9. Configurazione

| Variabile | Descrizione | Default |
|---|---|---|
| `ABM_GEMINI_BACKEND` | `auto` / `vertex` / `apikey` / `cloudflare`. Cloudflare solo esplicito | `auto` |
| `ABM_CF_ACCOUNT_ID` | Account Cloudflare per l'endpoint `/ai/run` | *(vuoto)* |
| `ABM_CF_API_TOKEN` | Token Workers AI. Mai loggato, mai in email | *(vuoto)* |
| `ABM_CF_TIMEOUT_MS` | Timeout per chiamata | `60000` |
| `ABM_CF_TRIP_FAILURES` | Fallimenti consecutivi che fanno scattare il breaker su 5xx | `3` |
| `ABM_CF_CREDIT_TOPUP_FEE` | Onere di ricarica del credito prepagato | `0.05` |
| `ABM_CF_CREDIT_BALANCE_EUR` | Saldo dichiarato all'ultima ricarica | `0` |
| `ABM_CF_CREDIT_ALERT_EUR` | Soglia di preallarme sul residuo | `5.00` |
| `ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT` | Quota del risparmio ceduta al cliente | `50` |
| `ABM_GEMINI_31FLASH_CF_INPUT_USD_PER_MTOK` | Tariffa input Cloudflare | `0.75` |
| `ABM_GEMINI_31FLASH_CF_OUTPUT_USD_PER_MTOK` | Tariffa output Cloudflare | `12.00` |
| `ABM_TTS_MIN_CHUNK_CHARS` | Sotto questa soglia un chunk viene fuso | `40` |

`PARAMETRI_CONFIGURAZIONE.md` va aggiornato con tutte, alla riga di codice.

## 10. Criteri di GO

Lo switch di §7 passo 2 non avviene finché tutti e cinque non sono soddisfatti.

| # | Criterio | Stato | Come si chiude |
|---|---|---|---|
| G1 | Costo Cloudflare riconciliato contro dashboard | **fatto** (−0,39%) | — |
| G2 | Tutte le voci di `GEMINI_VOICE_NAMES` (30) disponibili su Cloudflare | **aperto** | Fase 0: una chiamata per voce, testo minimo |
| G3 | Qualità indistinguibile da Vertex a parità di voce | **dichiarato dal committente**, non ancora documentato | Fase 0: A/B sullo stesso testo, allegato alla spec |
| G4 | Latenza p95 non peggiore di Vertex a parità di concorrenza | **aperto** | Fase 0: confronto diretto |
| G5 | Nessun `2017` su un libro intero dopo il fix chunking | **aperto** | Fase 1 + una rigenerazione di controllo |

G2 è bloccante in senso stretto: se Cloudflare ospitasse un sottoinsieme delle
voci, la selezione voce in produzione si romperebbe per gli utenti che hanno
scelto una voce mancante, e servirebbe una risoluzione backend **per voce** oltre
che per modello.

## 11. Fasi di lavoro

| Fase | Contenuto | Esito |
|---|---|---|
| 0 | Chiusura di G2, G3, G4; ricognizione API saldo Cloudflare | ~3 € di chiamate, nessun codice di produzione |
| 1 | Fix chunking dei frammenti degeneri (§5) | Rilasciabile da solo |
| 2 | `gemini_transport.py` + trasporto Vertex; `synthesize()` delega | Zero cambi di comportamento, suite verde intatta |
| 3 | Trasporto Cloudflare: REST, data URI, mappatura errori, derivazione token | |
| 4 | `_resolve_backend` per modello + breaker + failover + preallarme credito | |
| 5 | Base di prezzo parametrica + contabilità sul costo reale | |
| 6 | Email di trip, endpoint e pulsante admin, documentazione | |
| 7 | Rilascio dormiente, poi switch | |

Dopo la Fase 6 il codice Cloudflare è in produzione ma inattivo, e lo switch è una
variabile d'ambiente più un riavvio.

## 12. Rischi residui

| Rischio | Impatto | Mitigazione |
|---|---|---|
| Cloudflare non ospita tutte le voci | selezione voce rotta | G2 bloccante prima dello switch |
| Timeout lato client fatturato senza audio | costo invisibile | il registro spesa conta i timeout a parte; scostamento verificabile in dashboard |
| Failover prolungato non notato | erosione silenziosa del margine | email immediata + margine reale a consuntivo per backend |
| Credito esaurito di notte | Vertex fino al mattino | preallarme sotto soglia, non solo allarme a esaurimento |
| Cloudflare cambia tariffa o deprecates il modello | il prezzo ceduto al cliente non è più coperto | tariffe da env, `share` regolabile senza rilascio |
| Il modello su Cloudflare diverge da quello Vertex in un aggiornamento | deriva timbrica al failover | G3 ripetibile; il banco resta a disposizione |
