# Chiusura dei difetti della revisione finale (F1–F6)

Riferimento: `final-review.md`. F7, F8, F9 sono state esaminate e parcheggiate
deliberatamente in fase di brief: **non sono state toccate**.

Criterio di accettazione applicato a ogni test aggiunto: la **prova di
mutazione**. Un test che resta verde quando si rompe cio' che dichiara di
proteggere non e' copertura, e' rumore. Per ogni difetto qui sotto e'
riportato: cosa e' stato mutato, quale test e' diventato rosso, e la conferma
del ripristino del sorgente.

---

## F1 [ALTA] — `POST /admin/api/tts_backend`, azione `reset`

**Difetto.** L'endpoint non validava `model_key` e chiudeva sempre con
`gemini_tts._set_backend(model_key, "cloudflare")`. Verificato in esecuzione:
con configurazione `auto` la chiamata rispondeva `200` e **inchiodava
`flash25` su Cloudflare**, dove `flash25` ha `id_cloudflare=None` e non
esiste. Accettava e persisteva anche `model_key` inventati, materializzando
su disco voci di stato per modelli inesistenti. In produzione ogni job
PREMIUM su quel modello finiva in `TransportError(fatal)` →
`GeminiUnavailable` → job in errore e **rimborso integrale**, e cosi' restava
fino al riavvio del processo.

**Fix** (`audiobook_app.py`, `admin_api_tts_backend`), tre pezzi:

- (a) `model_key` validato contro `gemini_tts.GEMINI_MODELS`; se ignoto,
  `400` con messaggio esplicito e l'elenco delle chiavi note. La guardia sta
  **prima** di `tts_backend_state.reset()`, che e' l'operazione che
  materializza la voce su disco.
- (b) reset rifiutato con `409` quando `ABM_GEMINI_BACKEND != "cloudflare"`,
  con il valore effettivo nel messaggio e nel campo `configured_backend`:
  altrimenti la console dice all'admin di aver riacceso un backend che
  nessuna sintesi usera' mai. Il messaggio spiega *perche'* e cosa fare
  (impostare la variabile nell'unit systemd e riavviare).
- (c) rimosso il `_set_backend(...)` forzato. Resta solo l'invalidazione
  della cache in-process (`pop` su tutti i `model_key` noti, target
  compreso): il backend viene ricalcolato da `_resolve_backend` alla
  sintesi successiva, rispettando configurazione dichiarata e presenza di
  `id_cloudflare`.

Il resto del contratto dell'endpoint e' invariato: body assente, JSON
malformato, `action` mancante e `topup` non booleano continuano a non
produrre `500` (test preesistenti, tutti verdi).

**Nota sui test preesistenti.** Tre di essi codificavano il comportamento
sbagliato (`assert gemini_tts._BACKEND.get("flash31") == "cloudflare"`),
esattamente come la revisione anticipava. Riscritti per asserire
l'invalidazione `pop`-only e la ri-risoluzione (`_resolve_backend("flash31")
== "cloudflare"` con configurazione e credenziali Cloudflare presenti). La
fixture ora esporta `ABM_GEMINI_BACKEND=cloudflare` e credenziali Cloudflare
**finte** (commentate come tali): senza di esse `_resolve_backend` non puo'
piu' arrivare a `"cloudflare"`, ora che il valore non e' piu' forzato.

**Test che lo dimostrano** (`test/test_admin_tts_backend_endpoint.py`, nuovi):

- `test_an_unknown_model_key_is_rejected`
- `test_an_unknown_model_key_from_the_query_string_is_rejected`
- `test_reset_is_refused_when_the_environment_does_not_select_cloudflare`
- `test_a_refused_reset_does_not_pin_any_model_on_cloudflare`
- `test_reset_never_pins_a_model_cloudflare_does_not_host`

**Prove di mutazione:**

| # | Mutazione | Esito |
|---|-----------|-------|
| 4 | guardia (a) neutralizzata (validazione `model_key` rimossa) | **2 failed** |
| 5 | guardia (b) neutralizzata (guardia su `ABM_GEMINI_BACKEND` rimossa) | **2 failed** |
| 6 | `_set_backend(model_key, "cloudflare")` rimesso dopo il `pop` | **3 failed**, fra cui `test_reset_never_pins_a_model_cloudflare_does_not_host` |

Sorgente ripristinato dopo ciascuna, suite del file di nuovo verde.

---

## F2 [ALTA] — Il pre-allarme sul credito non esisteva

**Difetto.** `tts_backend_state.claim_credit_alert()` aveva **un solo
chiamante**, dentro la closure `_on_tts_backend_switch`: veniva interrogata
solo **dopo** che il breaker era gia' scattato. Il residuo di credito
compariva come riga informativa nell'email che annunciava un failover gia'
avvenuto — un post-allarme. Spec §4.4/§11,
`md_files/PARAMETRI_CONFIGURAZIONE.md` §7.8 e runbook §2 promettevano invece
un avviso sotto `ABM_CF_CREDIT_ALERT_EUR` **mentre c'e' ancora tempo per
ricaricare**. Con il credito che finisce di notte, il servizio girava su
Vertex (margine 1,9% contro il 61,7% di Cloudflare) fino al mattino senza
che nessuno lo sapesse: e' precisamente il motivo per cui questi avvisi sono
immediati e non nel digest giornaliero.

**Fix**, quattro moduli:

- `tts_backend_state.py`: nuova `credit_alert_threshold_eur()`, lettura
  **pura** di `ABM_CF_CREDIT_ALERT_EUR` (nessun effetto sullo stato). Serve
  a chi manda l'email per dichiarare la soglia senza rileggersi l'env a mano.
- `gemini_tts.py`: slot notifier `_credit_alert_notifier` +
  `set_credit_alert_notifier(fn)` (stesso pattern di
  `set_backend_switch_notifier`: `gemini_tts` non deve dipendere da
  `email_service`), e `_maybe_alert_credit(model_key)` chiamata da
  `synthesize()` **subito dopo `add_spend()`** — l'unico istante in cui il
  residuo stimato puo' essere sceso sotto soglia, e con il backend ancora
  sano. La chiamata e' avvolta in try/except: un pre-allarme che fallisce
  non deve far fallire una sintesi riuscita.
  **Ordine delle guardie, non negoziabile:** il controllo
  `if _credit_alert_notifier is None: return` viene **prima** di
  `claim_credit_alert()`. Invertito, la prima sintesi in un processo senza
  notifier registrato consumerebbe atomicamente l'unico allarme disponibile
  e l'email non partirebbe mai piu'.
- `email_service.py`: nuova `admin_notify_cf_credit_low(model_key,
  credit_left_eur, threshold_eur)`, modellata su
  `admin_notify_tts_backend_switch` (early-return senza `ADMIN_EMAIL` o
  senza SMTP, `_send_email(dest, subject, html)` con **tre argomenti
  posizionali**, nessun kwarg). Email **dedicata**: riusare quella di switch
  direbbe il falso, perche' annuncia un failover che non e' avvenuto.
  Il corpo dichiara residuo stimato, soglia, e cosa fare (ricaricare,
  riallineare `ABM_CF_CREDIT_BALANCE_EUR`, spuntare il `topup` in console).
  **Nessuna credenziale compare da nessuna parte**: il nome
  `ABM_CF_API_TOKEN` non e' nemmeno citato.
- `audiobook_app.py`: closure `_on_cf_credit_alert` registrata all'avvio
  accanto a `_on_tts_backend_switch`; manda l'email e logga
  `TTS_CF_CREDIT_LOW` con `epoch=time.time()` (ogni pre-allarme e' un fatto
  distinto, non va soffocato dal dedup su `(session_id, operation)`).

L'unicita' dell'invio e' garantita a monte da `claim_credit_alert()`, che
consuma atomicamente il diritto ad allarmare: l'email parte **una volta
sola**, non a ogni job successivo.

**Test che lo dimostrano** (`test/test_cf_credit_prealert.py`, nuovo, 13
test): il pre-allarme parte sotto soglia senza alcun trip; parte **una sola
volta** su tre sintesi consecutive; non parte sopra soglia; non parte su una
chiamata Vertex; non parte con saldo dichiarato `0` (pre-allarme
disabilitato); l'allarme **non viene bruciato** quando nessun notifier e'
registrato; un notifier che solleva non rompe una sintesi riuscita; l'app
registra il notifier all'avvio; la closure cablata manda l'email dedicata e
**non** quella di switch, con la soglia letta da `tts_backend_state`; logga
`TTS_CF_CREDIT_LOW` con `epoch` fresco; il corpo dell'email dichiara
residuo/soglia/`ABM_CF_CREDIT_BALANCE_EUR` e **non nomina mai**
`ABM_CF_API_TOKEN`; silenzio senza `ADMIN_EMAIL`; sopravvive a un residuo
non numerico.

**Prove di mutazione:**

| # | Mutazione | Esito |
|---|-----------|-------|
| 2 | `_maybe_alert_credit(model_key)` in `synthesize()` → `pass` | **2 failed** (`..._fires_the_prealert`, `..._fires_only_once_across_repeated_calls`) |
| 3 | guardia notifier-`None` spostata **dopo** `claim_credit_alert()` | **1 failed** (`test_the_alert_is_not_burned_when_no_notifier_is_registered`) |
| 9 | `gemini_tts.set_credit_alert_notifier(_on_cf_credit_alert)` rimosso dall'avvio | **1 failed** (`test_the_app_registers_a_credit_alert_notifier_at_startup`) |

Sorgente ripristinato dopo ciascuna.

**Correzione emersa dalla suite completa (non in isolamento).**
`test_the_app_registers_a_credit_alert_notifier_at_startup` confrontava per
**identita' di oggetto** (`_NOTIFIER_AT_IMPORT is
audiobook_app._on_cf_credit_alert`). Verde da solo, rosso nella suite
completa: parecchi file (`test_cold_*.py`,
`test_admin_translation_audit_endpoint.py`, `test_hot_eviction.py`,
`test_recovery_input_kind.py`, ...) fanno `importlib.reload(audiobook_app)`,
che ricrea la closure e cambia l'oggetto pur lasciando la registrazione
perfettamente in piedi. Il confronto e' ora per **identita' logica**
(`__module__` + `__qualname__`, piu' `callable()` sull'attributo vivo): la
mutazione #9 resta rossa lo stesso, perche' togliere la registrazione lascia
lo slot a `None` e fa fallire la prima asserzione. Nessun
`importlib.reload(audiobook_app)` e' stato introdotto in questi test — la
memoria di progetto registra che ri-importare l'entry-point uccide i job.

---

## F3 [MEDIA] — Ottavo "specchio" prezzo-vs-costo nel banco A/B

**Difetto.** `scripts/tts_cloudflare_gemini_test.py` (ex riga 1974): il ramo
Vertex del banco calcolava la colonna di costo con `google_cost_breakdown`,
che e' un **alias del listino** (`pricing_cost_breakdown`). Girando in una
shell con `ABM_GEMINI_BACKEND=cloudflare` esportato — il caso naturale
mentre si prova Cloudflare — quel listino e' la tariffa mista, gia' scontata
della quota di risparmio ceduta al cliente: la colonna "costo reale Google"
scendeva esattamente di quella quota e il confronto economico A/B, cioe' il
numero per cui il banco esiste, **sottostimava Vertex**.

**Fix:** `gemini_tts.actual_cost_breakdown(tokens_in, tokens_out, "flash31",
"vertex")`, con commento sul call site che spiega perche'
`google_cost_breakdown` qui non va mai usata.

**Test che lo dimostra:**
`test/test_gemini_cost_split.py::test_the_ab_bench_measures_vertex_at_its_real_cost_not_at_the_listino`.
Verifica sul **sorgente** dello script: lo script non e' importabile a costo
ragionevole (argparse e I/O a livello di modulo) e nessun test lo tocca. Che
i due numeri non siano intercambiabili e' gia' fissato dal test di proprieta'
preesistente `test_on_vertex_the_price_is_below_the_real_cost_before_margin`;
quello che non era fissato da niente era il **call site**.

**Prova di mutazione #8:** call site riportato a
`gemini_tts.google_cost_breakdown(tokens_in, tokens_out, "flash31")` →
`1 failed, 7 passed`. Sorgente ripristinato.

### Giro di ricerca del nono specchio

Cercato su **tutto l'albero**, con:

```
grep -rn "google_cost_breakdown\|pricing_cost_breakdown\|actual_cost_breakdown\
\|worst_case_cost_breakdown\|pricing_rates\|actual_rates\|worst_case_rates\
\|_pricing_uses_cloudflare\|_budget_uses_cloudflare\|cf_saving_share\|_cf_effective\
\|estimate_book_cost\|compute_user_price_eur\|google_cost_eur" \
  --include=*.py --include=*.js --include=*.html --include=*.md .
```

Gli hit sotto `.claude/worktrees/abm_mobile`, `.claude/worktrees/litellm_test`
e `.worktrees/ABM_DB` sono branch separati e stantii, fuori dall'albero vivo.

Nell'albero vivo, tutti i call site dei simboli di costo:

| Sito | Funzione usata | Verdetto |
|------|----------------|----------|
| `gemini_tts.py:1120` | definizione dell'alias `google_cost_breakdown = pricing_cost_breakdown` | — |
| `gemini_tts.py:1203` | `google_cost_breakdown` in `estimate_book_cost` | **corretto**: alimenta `compute_user_price_eur`, e' un path di **prezzo** |
| `gemini_tts.py:2947` | `actual_cost_breakdown` per lo spend sul ledger Cloudflare | **corretto**: contabilita' |
| `audiobook_app.py:9370` | `actual_cost_breakdown` (contabilita' preview) | **corretto** |
| `audiobook_app.py:9828` | `worst_case_cost_breakdown` (riserva di budget in preflight) | **corretto** |
| `generation_engine.py:4571` | `actual_cost_breakdown` (costo reale a consuntivo) | **corretto** |
| `generation_engine.py:4585` | `pricing_cost_breakdown` (listino sui token reali) | **corretto** |
| `scripts/tts_cloudflare_gemini_test.py:1981` | `actual_cost_breakdown(..., "vertex")` | **corretto dopo F3** |

**Nessun nono specchio trovato.**

---

## F4 [BASSA] — Runbook: "la selezione dipende solo da `ABM_GEMINI_BACKEND`"

**Difetto.** `docs/RUNBOOK_CLOUDFLARE_TTS.md:219-221` affermava che la
selezione del backend dipende **solo** da `ABM_GEMINI_BACKEND`. Falso: il
breaker persistito ha precedenza (`gemini_tts._resolve_backend`), e chiusa
F1 il reset da console cambia davvero il backend effettivo.

**Fix.** §6 punto 4 riscritto limitando l'affermazione al **caso di
rollback**, dove e' vera: con `ABM_GEMINI_BACKEND=vertex` il reset e' inutile
perche' **entrambi i percorsi portano a Vertex**. Aggiunto l'avviso esplicito
a non generalizzare: il breaker ha precedenza, e con configurazione
`cloudflare` il reset da console cambia il backend effettivo (altrimenti
l'endpoint rifiuta con `409`).

Aggiunta inoltre la sezione **§6bis — Pre-allarme credito: l'email che arriva
*prima* del guasto**: oggetto dell'email, quando parte, che parte una volta
sola per soglia, e cosa fare quando arriva.

---

## F5 [BASSA] — Stato che si contraddice su installazione pulita

**Difetto.** `audiobook_app.py:7304`: `s.get("active") or "cloudflare"`. Su
installazione pulita `tts_backend_state.state()` ritorna `{}` e il pannello
scriveva «Cloudflare non configurato · il TTS gira su cloudflare» — una
contraddizione nella prima riga che un admin legge dopo il deploy.

**Fix.** Ripiego su `configured_backend` (la variabile ora calcolata una
volta sola e riusata anche dal campo omonimo della risposta).

**Test:**
`test/test_admin_tts_backend_endpoint.py::test_a_clean_install_does_not_report_a_self_contradictory_state`.

**Prova di mutazione #7:** ripiego riportato a `"cloudflare"` → **1 failed**.
Sorgente ripristinato.

---

## F6 [BASSA] — Nessuna rete sotto la proprieta' anti-burst

**Difetto.** La guardia `if first and _backend_switch_notifier is not None:`
in `gemini_tts._trip_to_vertex` (riga ~414) garantisce **una sola** email di
switch anche se il breaker viene sollecitato piu' volte. La revisione ha
rimosso quella guardia e **219 test** sugli 8 file rilevanti sono rimasti
verdi.

Perche' il test preesistente `test_the_notifier_fires_once_at_the_trip` non
poteva accorgersene: dopo il primo trip `_resolve_backend` ritorna
`"vertex"`, quindi la seconda `synthesize()` non arriva mai a
`_trip_to_vertex`. Il test misurava l'unicita' del *percorso*, non
l'idempotenza della *notifica*.

**Fix (solo test).**
`test/test_gemini_failover.py::test_a_second_trip_on_the_same_model_does_not_re_notify`:
chiama `gemini_tts._trip_to_vertex("flash31", ...)` **direttamente due
volte**, con `job_id` `j1` e `j2`, e asserisce `seen == ["j1"]` e
`st.state("flash31")["trip_job_id"] == "j1"`.

**Prova di mutazione #1:** rimosso `first and ` dalla guardia →
`1 failed, 11 passed`, con il test nuovo rosso. Sorgente ripristinato con
`git checkout -- gemini_tts.py`, suite del file di nuovo verde.

---

## Documentazione aggiornata

- `md_files/PARAMETRI_CONFIGURAZIONE.md` §7.8: `credit_alert_threshold_eur()`
  aggiunta all'API del modulo; nuovo paragrafo **"Dove scatta davvero il
  pre-allarme"** con `gemini_tts._maybe_alert_credit` e l'ordine obbligato
  delle guardie.
- `md_files/PARAMETRI_CONFIGURAZIONE.md` §7.9: nuovo paragrafo **"Contratto
  del rientro"** con l'invalidazione `pop`-only e le due guardie `400`/`409`.
- `docs/RUNBOOK_CLOUDFLARE_TTS.md`: §6 punto 4 riscritto (F4), nuova §6bis
  sul pre-allarme.

---

## Suite

```
python -m pytest test/ -q --tb=short
1 failed, 1903 passed, 4 skipped, 54 warnings in 266.77s
FAILED test/test_pcm_encode_truncation.py::test_run_ffmpeg_encode_aspetta_finche_output_cresce
```

Baseline dichiarata nel brief: **1883 passed, 4 skipped**. Delta: **+20 test
verdi** (13 in `test_cf_credit_prealert.py`, 5 in
`test_admin_tts_backend_endpoint.py`, 1 in `test_gemini_cost_split.py`, 1 in
`test_gemini_failover.py`).

L'unico rosso e' il test noto come sensibile ai tempi sotto carico, indicato
dal brief come non-regressione. Verificato in isolamento subito dopo:
`test/test_pcm_encode_truncation.py` → **22 passed in 3.75s**.

`python -m py_compile` pulito su `audiobook_app.py gemini_tts.py
email_service.py tts_backend_state.py scripts/tts_cloudflare_gemini_test.py`.

---

## Vincoli operativi rispettati

- Nessun `git add -A` / `git add .`. `audiobook_app.py` contiene anche
  modifiche di una sessione parallela (`_cold_op`, `_mark_token_redirected`,
  `redirected_at`, i rami cold di `token_do_download*` /
  `_serve_audio_download` / `api_download`, i badge SVG store): messi in
  staging **solo** i miei hunk, via patch filtrata, con `git diff --staged`
  verificato prima di ogni commit.
- Mai messi in staging: `.gitignore`, `templates/_fragments/html_head.html`,
  `test/test_cold_download_log.py`, gli hunk cold di `audiobook_app.py`.
  `CLAUDE.md` mai aggiunto all'indice.
- Nessun `git push`.
- Nessun sottoagente.
- Nessun valore reale di token o credenziale in codice, log, email, test o
  documentazione: solo i **nomi** delle variabili; nei test, valori
  palesemente fittizi e commentati come tali.
