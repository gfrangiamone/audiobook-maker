# Backend Cloudflare per Gemini TTS — economia, console e rollout (Fasi 5-7) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** portare in produzione il backend Cloudflare costruito dal piano gemello: prezzo all'utente calcolato sempre sulle tariffe Cloudflare, contabilità che registra il costo realmente sostenuto, email immediata all'admin allo scatto del failover, pulsante di rientro in console e procedura di switch con rollback.

**Architecture:** oggi `google_cost_breakdown()` serve due scopi che finora coincidevano — quanto far pagare all'utente e quanto è costato davvero. Con due backend a tariffe diverse i due numeri divergono, e il piano li separa: il **prezzo** usa sempre una tariffa mista Cloudflare/Google (decisione D1: il listino non oscilla quando il failover entra in gioco), la **contabilità** usa la tariffa del backend che ha effettivamente eseguito. Sopra questo, il gancio di notifica lasciato nudo dal piano gemello viene collegato a un'email admin, e il breaker riceve il suo pulsante di rientro nella console già esistente.

**Tech Stack:** Python 3.12, Flask, SMTP (TurboSMTP), vanilla JS, pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-cloudflare-tts-prod-backend-design.md` (§4.7 Margini, §6 Pricing, §7 Notifiche, §8 Console admin, §11 Fasi 5-7).

**Prerequisito obbligatorio:** `docs/superpowers/plans/2026-08-26-cloudflare-tts-backend-core.md` (Fasi 0 e 2-4) deve essere completato. Questo piano consuma `tts_backend_state`, `gemini_transport`, `_resolve_backend` per modello e `set_backend_switch_notifier`.

## Global Constraints

| Variabile | Significato | Default |
|---|---|---|
| `ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT` | Quota del risparmio Cloudflare ceduta al cliente | `50` |
| `ABM_GEMINI_31FLASH_CF_INPUT_USD_PER_MTOK` | Tariffa input Cloudflare | `0.75` |
| `ABM_GEMINI_31FLASH_CF_OUTPUT_USD_PER_MTOK` | Tariffa output Cloudflare | `12.00` |
| `ABM_CF_CREDIT_TOPUP_FEE` | Commissione di ricarica del credito | `0.05` |
| `ABM_CF_CREDIT_BALANCE_EUR` | Saldo credito dichiarato dall'admin | `0` |
| `ABM_CF_CREDIT_ALERT_EUR` | Soglia del pre-allarme credito | `5.00` |
| `ABM_GEMINI_31FLASH_MARGIN_PERCENT` | Margine netto operatore su flash31 (invariato) | `25.0` |
| `ABM_GEMINI_USD_EUR_RATE` | Cambio USD→EUR (invariato) | `0.86` |

Vincoli non negoziabili:

- **D1 — il prezzo si calcola sempre sulle tariffe Cloudflare**, anche mentre il failover sta eseguendo su Vertex. Lo switch è una condizione straordinaria: il listino non deve oscillare sotto gli occhi dell'utente. Conseguenza operativa: la funzione che sceglie le tariffe di prezzo guarda la **configurazione**, non il backend attivo in quel momento.
- **Il costo reale è un'altra cosa dal prezzo.** La contabilità registra quanto è costato davvero, con la tariffa del backend che ha eseguito. Confondere i due numeri falsa il margine e rende inutile ogni riconciliazione.
- **Mai nominare provider AI/TTS nel testo rivolto all'utente.** Le etichette utente restano generiche ("Voci PREMIUM"). Cloudflare, Google, Vertex e Gemini compaiono solo nella console admin, nelle email all'admin e nei log.
- **Il prezzo passa da una fonte unica.** Nessun calcolo `chars × rate` inline: si usano le funzioni del modulo, come già stabilito dopo l'incidente della stima €0,48 contro l'addebito a €1.
- **Il rientro su Cloudflare è solo manuale.** Nessun ripristino automatico, nessun timer.
- Commit in stile Conventional Commits, senza trailer di attribuzione.
- `docs/`, `*.md` e `scripts/` sono coperti da `.gitignore`: serve `git add -f`.
- Mai `git add -A` né `git add .`.
- **Chiedere sempre conferma prima del push.** Nessuna eccezione, nemmeno in auto-mode.

## La formula del prezzo

Sia `g` la tariffa di listino Google, `c` la tariffa Cloudflare, `f` la commissione di ricarica (5%), `s` la quota di risparmio ceduta al cliente (50%):

```
c_eff = c × (1 + f)                      tariffa Cloudflare effettiva
tariffa_prezzo = g − (g − c_eff) × s     tariffa usata per il listino
```

Su flash31, output: `g = 20.00`, `c = 12.00`, `c_eff = 12.60`, `s = 0.5` → `tariffa_prezzo = 16.30` USD/Mtok. L'output vale il 99,05% del costo di una chiamata, quindi è l'unica tariffa che sposta il conto in modo visibile.

Margini risultanti (spec §4.7): **+61,7%** quando esegue Cloudflare, **+1,9%** quando il failover esegue su Vertex. Il secondo numero è la ragione per cui l'email di trip esiste e per cui il pre-allarme sul credito esiste: un failover prolungato non fa perdere denaro, ma azzera il guadagno.

---

### Task 1: tariffe Cloudflare e tariffa di prezzo

**Files:**
- Modify: `gemini_tts.py` (`GEMINI_MODELS`, righe 144-163; nuove funzioni dopo `get_margin_percent`, riga 469)
- Test: `test/test_gemini_pricing_cloudflare.py` (nuovo)

**Interfaces:**
- Consumes: `GEMINI_MODELS[k]["id_cloudflare"]` (Task 5 del piano gemello).
- Produces:
  - `GEMINI_MODELS[k]["cf_input_usd_per_mtok"]` / `["cf_output_usd_per_mtok"]` (`None` per i modelli non su Cloudflare).
  - `cf_saving_share()` — quota di risparmio ceduta, in `[0, 1]`.
  - `pricing_rates(model_key) -> (input_usd_per_mtok, output_usd_per_mtok)` — le tariffe da usare **per il listino**.
  - `actual_rates(model_key, backend) -> (input_usd_per_mtok, output_usd_per_mtok)` — le tariffe **realmente sostenute** dal backend indicato.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_gemini_pricing_cloudflare.py`:

```python
"""Tariffe di prezzo (Cloudflare) e tariffe di costo reale (per backend)."""
import pytest

import gemini_tts


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    gemini_tts._BACKEND = {}
    yield
    gemini_tts._BACKEND = {}


def _cf_configured(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")


def test_flash31_carries_the_cloudflare_rates():
    m = gemini_tts.GEMINI_MODELS["flash31"]
    assert m["cf_input_usd_per_mtok"] == pytest.approx(0.75)
    assert m["cf_output_usd_per_mtok"] == pytest.approx(12.00)


def test_flash25_has_no_cloudflare_rates():
    m = gemini_tts.GEMINI_MODELS["flash25"]
    assert m["cf_input_usd_per_mtok"] is None
    assert m["cf_output_usd_per_mtok"] is None


def test_saving_share_defaults_to_half(monkeypatch):
    monkeypatch.delenv("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", raising=False)
    assert gemini_tts.cf_saving_share() == pytest.approx(0.5)


def test_saving_share_is_clamped(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", "170")
    assert gemini_tts.cf_saving_share() == pytest.approx(1.0)
    monkeypatch.setenv("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", "-3")
    assert gemini_tts.cf_saving_share() == pytest.approx(0.0)


def test_pricing_rates_blend_google_and_cloudflare(monkeypatch):
    _cf_configured(monkeypatch)
    monkeypatch.setenv("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", "50")
    monkeypatch.setenv("ABM_CF_CREDIT_TOPUP_FEE", "0.05")
    _, out_rate = gemini_tts.pricing_rates("flash31")
    # c_eff = 12.00 * 1.05 = 12.60 ; 20.00 - (20.00 - 12.60) * 0.5 = 16.30
    assert out_rate == pytest.approx(16.30)


def test_share_zero_keeps_the_google_list_price(monkeypatch):
    _cf_configured(monkeypatch)
    monkeypatch.setenv("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", "0")
    _, out_rate = gemini_tts.pricing_rates("flash31")
    assert out_rate == pytest.approx(20.00)


def test_share_hundred_passes_the_whole_saving_to_the_customer(monkeypatch):
    _cf_configured(monkeypatch)
    monkeypatch.setenv("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", "100")
    monkeypatch.setenv("ABM_CF_CREDIT_TOPUP_FEE", "0.05")
    _, out_rate = gemini_tts.pricing_rates("flash31")
    assert out_rate == pytest.approx(12.60)


def test_pricing_rates_ignore_a_trip_to_vertex(monkeypatch):
    # D1: lo switch e' una condizione straordinaria, il listino non oscilla.
    _cf_configured(monkeypatch)
    gemini_tts._set_backend("flash31", "vertex")
    _, out_rate = gemini_tts.pricing_rates("flash31")
    assert out_rate == pytest.approx(16.30)


def test_without_cloudflare_configured_pricing_is_pure_google(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "auto")
    inp, out = gemini_tts.pricing_rates("flash31")
    assert (inp, out) == pytest.approx((1.00, 20.00))


def test_a_model_not_on_cloudflare_is_priced_on_google(monkeypatch):
    _cf_configured(monkeypatch)
    inp, out = gemini_tts.pricing_rates("flash25")
    assert (inp, out) == pytest.approx((0.50, 10.00))


def test_actual_rates_follow_the_executing_backend(monkeypatch):
    monkeypatch.setenv("ABM_CF_CREDIT_TOPUP_FEE", "0.05")
    assert gemini_tts.actual_rates("flash31", "cloudflare") == \
        pytest.approx((0.7875, 12.60))
    assert gemini_tts.actual_rates("flash31", "vertex") == \
        pytest.approx((1.00, 20.00))
    assert gemini_tts.actual_rates("flash31", "apikey") == \
        pytest.approx((1.00, 20.00))


def test_actual_rates_on_a_model_without_cloudflare_fall_back_to_google():
    assert gemini_tts.actual_rates("flash25", "cloudflare") == \
        pytest.approx((0.50, 10.00))
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `python -m pytest test/test_gemini_pricing_cloudflare.py -v`
Expected: FAIL — `cf_input_usd_per_mtok` e `pricing_rates` non esistono.

- [ ] **Step 3: Aggiungi le tariffe a `GEMINI_MODELS`**

In `gemini_tts.py`, dentro `GEMINI_MODELS`, sotto `"id_cloudflare": None` di `flash25`:

```python
        "cf_input_usd_per_mtok": None,
        "cf_output_usd_per_mtok": None,
```

e sotto `"id_cloudflare": "google/gemini-3.1-flash-tts"` di `flash31`:

```python
        # Tariffe Cloudflare al lordo della commissione di ricarica, che viene
        # applicata a parte da `_cf_effective`: qui stanno i numeri di listino.
        "cf_input_usd_per_mtok": _f("ABM_GEMINI_31FLASH_CF_INPUT_USD_PER_MTOK", 0.75),
        "cf_output_usd_per_mtok": _f("ABM_GEMINI_31FLASH_CF_OUTPUT_USD_PER_MTOK", 12.00),
```

- [ ] **Step 4: Implementa le funzioni di tariffa**

Subito dopo `get_margin_percent` (riga 469):

```python
def _cf_topup_fee():
    """Commissione pagata per comprare il credito AI Gateway.

    Si paga comprando il credito, non spendendolo: il saldo cala dell'addebito
    nudo, il costo per noi e' l'addebito piu' questa commissione.
    """
    return _f("ABM_CF_CREDIT_TOPUP_FEE", 0.05)


def cf_saving_share():
    """Quota del risparmio Cloudflare ceduta al cliente, in [0, 1]."""
    pct = _f("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", 50.0)
    return max(0.0, min(1.0, pct / 100.0))


def _cf_effective(rate):
    """Tariffa Cloudflare comprensiva della commissione di ricarica."""
    return rate * (1.0 + _cf_topup_fee())


def _pricing_uses_cloudflare(model_key):
    """True se il LISTINO di questo modello si calcola su base Cloudflare.

    Guarda la CONFIGURAZIONE, non il backend attivo: dopo un trip il modello
    esegue su Vertex, ma il prezzo non deve oscillare sotto gli occhi
    dell'utente (decisione D1). Usare `_resolve_backend` qui sarebbe il bug
    piu' facile da introdurre e il piu' difficile da notare.
    """
    choice = (os.environ.get("ABM_GEMINI_BACKEND", "auto") or "auto").strip().lower()
    if choice != "cloudflare":
        return False
    m = GEMINI_MODELS.get(model_key) or {}
    return bool(m.get("id_cloudflare")) and m.get("cf_output_usd_per_mtok") is not None


def pricing_rates(model_key):
    """(input, output) USD/Mtok da usare per il PREZZO all'utente.

        tariffa = google - (google - cf_eff) * share

    Con share=0 il listino resta quello Google; con share=1 tutto il risparmio
    va al cliente. Se Cloudflare non e' configurato per questo modello, le
    tariffe sono quelle Google pure e il comportamento e' identico a oggi.
    """
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown model_key: {model_key}")
    m = GEMINI_MODELS[model_key]
    g_in, g_out = m["input_usd_per_mtok"], m["output_usd_per_mtok"]
    if not _pricing_uses_cloudflare(model_key):
        return g_in, g_out
    share = cf_saving_share()
    c_in = _cf_effective(m["cf_input_usd_per_mtok"])
    c_out = _cf_effective(m["cf_output_usd_per_mtok"])
    return (g_in - (g_in - c_in) * share,
            g_out - (g_out - c_out) * share)


def actual_rates(model_key, backend):
    """(input, output) USD/Mtok REALMENTE sostenute dal backend che ha eseguito.

    Serve alla contabilita', non al listino: e' l'unico numero con cui ha senso
    riconciliare la spesa e misurare il margine vero.
    """
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown model_key: {model_key}")
    m = GEMINI_MODELS[model_key]
    if backend == "cloudflare" and m.get("cf_output_usd_per_mtok") is not None:
        return (_cf_effective(m["cf_input_usd_per_mtok"]),
                _cf_effective(m["cf_output_usd_per_mtok"]))
    return m["input_usd_per_mtok"], m["output_usd_per_mtok"]
```

- [ ] **Step 5: Esegui i test**

Run: `python -m pytest test/test_gemini_pricing_cloudflare.py -v`
Expected: PASS (12 test)

- [ ] **Step 6: Commit**

```bash
git add gemini_tts.py test/test_gemini_pricing_cloudflare.py
git commit -m "feat(tts): tariffe Cloudflare e tariffa di listino mista parametrica"
```

---

### Task 2: separazione fra prezzo e costo reale

**Files:**
- Modify: `gemini_tts.py` (`google_cost_breakdown`, righe 739-753; `estimate_book_cost`, riga 835)
- Test: `test/test_gemini_cost_split.py` (nuovo)

**Interfaces:**
- Consumes: `pricing_rates`, `actual_rates` (Task 1).
- Produces:
  - `pricing_cost_breakdown(input_tokens, output_tokens, model_key) -> dict` — alimenta `compute_user_price_eur`.
  - `actual_cost_breakdown(input_tokens, output_tokens, model_key, backend) -> dict` — alimenta `record_usage`.
  - `google_cost_breakdown` resta come **alias di `pricing_cost_breakdown`**, per non rompere i chiamanti esistenti.

**Perché un alias e non una rimozione:** `google_cost_breakdown` è chiamata da `estimate_book_cost` e, con ogni probabilità, da altri punti. Rinominarla in un colpo solo espone a un chiamante dimenticato che smette di funzionare in silenzio. L'alias mantiene il comportamento storico — che è quello del prezzo — e i chiamanti della contabilità vengono spostati esplicitamente, uno per uno.

- [ ] **Step 1: Censisci i chiamanti**

Run: `grep -rn "google_cost_breakdown\|record_usage\|google_cost_eur" gemini_tts.py generation_engine.py audiobook_app.py`

Annota nel report ogni sito e classificalo: **prezzo** (va su `pricing_cost_breakdown`) o **contabilità** (va su `actual_cost_breakdown`). È questa classificazione, non il codice, la parte del task che richiede giudizio.

- [ ] **Step 2: Scrivi i test che falliscono**

Crea `test/test_gemini_cost_split.py`:

```python
"""Il prezzo e il costo reale sono due numeri distinti."""
import pytest

import gemini_tts


@pytest.fixture(autouse=True)
def _cf(monkeypatch):
    gemini_tts._BACKEND = {}
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    monkeypatch.setenv("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", "50")
    monkeypatch.setenv("ABM_CF_CREDIT_TOPUP_FEE", "0.05")
    yield
    gemini_tts._BACKEND = {}


def test_pricing_breakdown_uses_the_blended_rate():
    b = gemini_tts.pricing_cost_breakdown(1_000_000, 1_000_000, "flash31")
    # input misto: 1.00 - (1.00 - 0.7875) * 0.5 = 0.89375
    assert b["input_usd"] == pytest.approx(0.89375)
    assert b["output_usd"] == pytest.approx(16.30)


def test_actual_breakdown_on_cloudflare_uses_the_real_rate():
    b = gemini_tts.actual_cost_breakdown(1_000_000, 1_000_000, "flash31",
                                         "cloudflare")
    assert b["input_usd"] == pytest.approx(0.7875)
    assert b["output_usd"] == pytest.approx(12.60)


def test_actual_breakdown_on_vertex_uses_the_google_rate():
    b = gemini_tts.actual_cost_breakdown(1_000_000, 1_000_000, "flash31",
                                         "vertex")
    assert b["output_usd"] == pytest.approx(20.00)


def test_the_margin_between_price_and_real_cost_is_positive_on_cloudflare():
    price = gemini_tts.pricing_cost_breakdown(1000, 100_000, "flash31")
    real = gemini_tts.actual_cost_breakdown(1000, 100_000, "flash31",
                                            "cloudflare")
    assert price["total_eur"] > real["total_eur"]


def test_on_vertex_the_price_is_below_the_real_cost_before_margin():
    # E' la ragione per cui il failover va notificato: il margine lordo si
    # assottiglia fino a sfiorare il pareggio.
    price = gemini_tts.pricing_cost_breakdown(1000, 100_000, "flash31")
    real = gemini_tts.actual_cost_breakdown(1000, 100_000, "flash31", "vertex")
    assert price["total_eur"] < real["total_eur"]


def test_google_cost_breakdown_still_works_and_matches_the_price():
    legacy = gemini_tts.google_cost_breakdown(1000, 100_000, "flash31")
    price = gemini_tts.pricing_cost_breakdown(1000, 100_000, "flash31")
    assert legacy == price


def test_breakdown_keys_are_unchanged():
    b = gemini_tts.pricing_cost_breakdown(10, 10, "flash31")
    assert set(b) == {"input_usd", "output_usd", "total_usd", "total_eur"}
```

- [ ] **Step 3: Esegui i test e verifica che falliscano**

Run: `python -m pytest test/test_gemini_cost_split.py -v`
Expected: FAIL con `AttributeError: module 'gemini_tts' has no attribute 'pricing_cost_breakdown'`

- [ ] **Step 4: Implementa la separazione**

Sostituisci `google_cost_breakdown` (righe 739-753) con:

```python
def _breakdown(input_tokens, output_tokens, in_rate, out_rate):
    input_usd = input_tokens * in_rate / 1_000_000
    output_usd = output_tokens * out_rate / 1_000_000
    total_usd = input_usd + output_usd
    return {
        "input_usd": input_usd,
        "output_usd": output_usd,
        "total_usd": total_usd,
        "total_eur": total_usd * USD_EUR_RATE,
    }


def pricing_cost_breakdown(input_tokens, output_tokens, model_key):
    """Costo di RIFERIMENTO per il listino, dettagliato USD/EUR.

    Usa la tariffa mista (D1): non cambia quando il failover esegue su Vertex.
    E' l'ingresso di `compute_user_price_eur`.
    """
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown model_key: {model_key}")
    in_rate, out_rate = pricing_rates(model_key)
    return _breakdown(input_tokens, output_tokens, in_rate, out_rate)


def actual_cost_breakdown(input_tokens, output_tokens, model_key, backend):
    """Costo REALMENTE sostenuto dal backend che ha eseguito.

    E' l'ingresso della contabilita': con questo si misura il margine vero e si
    riconcilia la spesa. Non usarlo mai per il prezzo.
    """
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown model_key: {model_key}")
    in_rate, out_rate = actual_rates(model_key, backend)
    return _breakdown(input_tokens, output_tokens, in_rate, out_rate)


# Alias storico: i chiamanti che chiedevano "il costo" intendevano il prezzo.
# Mantenuto per non rompere in silenzio un chiamante dimenticato; i siti di
# contabilita' sono stati spostati esplicitamente su actual_cost_breakdown.
google_cost_breakdown = pricing_cost_breakdown
```

- [ ] **Step 5: Sposta i siti di contabilità**

Per ogni sito classificato come **contabilità** allo Step 1, sostituisci la chiamata con `actual_cost_breakdown(..., backend=_resolve_backend(model_key))`. Se un sito non ha accesso al `model_key` o al backend, propagalo dal chiamante invece di indovinarlo: un backend sbagliato qui produce una contabilità silenziosamente falsa, che è peggio di un errore.

- [ ] **Step 6: Esegui i test**

Run: `python -m pytest test/test_gemini_cost_split.py -v`
Expected: PASS (7 test)

- [ ] **Step 7: Verifica la suite**

Run: `python -m pytest test/ -q --tb=short`
Expected: nessun fallimento nuovo.

- [ ] **Step 8: Commit**

```bash
git add gemini_tts.py generation_engine.py test/test_gemini_cost_split.py
git commit -m "feat(tts): separa il costo di listino dal costo realmente sostenuto"
```

---

### Task 3: stima dei token mancanti e ledger della spesa

**Files:**
- Modify: `gemini_tts.py` (`synthesize`, blocco di successo del ciclo di retry)
- Test: `test/test_gemini_cf_usage.py` (nuovo)

**Interfaces:**
- Consumes: `estimate_input_tokens` (riga 664), `_audio_tokens_per_second` (riga 65), `actual_cost_breakdown` (Task 2), `tts_backend_state.add_spend` (Task 8 del piano gemello).
- Produces: `synthesize()` che restituisce `input_tokens` / `output_tokens` **sempre valorizzati**, anche quando il trasporto non li fornisce, più un campo `"tokens_estimated": bool` che dichiara se sono misurati o stimati.

**Il problema:** l'API Cloudflare non restituisce metadati di consumo. Vertex li restituisce. Senza una stima, un job servito da Cloudflare contabilizzerebbe zero token e zero costo — un margine apparente del 100%, che è esattamente il tipo di numero che fa prendere decisioni sbagliate.

**La stima:** `output_tokens = secondi_audio_reali × _audio_tokens_per_second(model_key)`, dove i secondi reali si ricavano dai byte PCM prodotti (s16le, 24 kHz mono → 48000 byte/s), non da un'euristica sul testo. `input_tokens = estimate_input_tokens(final_text)`. L'output vale il 99% del conto, quindi la precisione che conta è quella dell'output — ed è alta, perché deriva da una misura, non da una previsione.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_gemini_cf_usage.py`:

```python
"""Stima dei token quando il trasporto non li fornisce, e ledger di spesa."""
import pytest

import gemini_tts
import tts_backend_state as st


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    st.init(str(tmp_path))
    gemini_tts._BACKEND = {}
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_throttle_rpm", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_rpd_increment", lambda mk: None)
    yield
    gemini_tts._BACKEND = {}


def _install_cf(monkeypatch, seconds):
    # PCM s16le 24 kHz mono -> 48000 byte al secondo.
    pcm = b"\x00" * int(48000 * seconds)
    monkeypatch.setattr(
        gemini_tts._transport, "cloudflare_call",
        lambda **kw: {"pcm": pcm, "input_tokens": None, "output_tokens": None})


def test_output_tokens_are_estimated_from_the_real_audio(tmp_path, monkeypatch):
    _install_cf(monkeypatch, seconds=10)
    out = gemini_tts.synthesize("ciao", "gemini:flash31:Kore",
                                output_path=str(tmp_path / "o.pcm"))
    # 10 secondi x 25 tok/s
    assert out["output_tokens"] == 250
    assert out["tokens_estimated"] is True


def test_input_tokens_are_estimated_from_the_text(tmp_path, monkeypatch):
    _install_cf(monkeypatch, seconds=1)
    out = gemini_tts.synthesize("una frase di prova ragionevolmente lunga",
                                "gemini:flash31:Kore",
                                output_path=str(tmp_path / "o.pcm"))
    assert out["input_tokens"] > 0


def test_measured_tokens_are_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(
        gemini_tts._transport, "cloudflare_call",
        lambda **kw: {"pcm": b"\x00" * 48000, "input_tokens": 7,
                      "output_tokens": 99})
    out = gemini_tts.synthesize("ciao", "gemini:flash31:Kore",
                                output_path=str(tmp_path / "o.pcm"))
    assert (out["input_tokens"], out["output_tokens"]) == (7, 99)
    assert out["tokens_estimated"] is False


def test_the_cloudflare_spend_lands_on_the_ledger(tmp_path, monkeypatch):
    _install_cf(monkeypatch, seconds=60)
    before = st.credit_left_eur()
    gemini_tts.synthesize("ciao", "gemini:flash31:Kore",
                          output_path=str(tmp_path / "o.pcm"))
    assert st.credit_left_eur() < before


def test_a_vertex_call_does_not_touch_the_cloudflare_ledger(tmp_path, monkeypatch):
    gemini_tts._set_backend("flash31", "vertex")
    monkeypatch.setattr(
        gemini_tts, "_vertex_transport_call",
        lambda **kw: {"pcm": b"\x00" * 48000, "input_tokens": 5,
                      "output_tokens": 25})
    before = st.credit_left_eur()
    gemini_tts.synthesize("ciao", "gemini:flash31:Kore",
                          output_path=str(tmp_path / "o.pcm"))
    assert st.credit_left_eur() == pytest.approx(before)
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `python -m pytest test/test_gemini_cf_usage.py -v`
Expected: FAIL — `tokens_estimated` non è nel dict di ritorno.

- [ ] **Step 3: Implementa la stima e il ledger**

Nel blocco di successo del ciclo di retry di `synthesize`, sostituisci l'assegnazione dei token con:

```python
            pcm_data = out["pcm"]
            usage_input = out["input_tokens"]
            usage_output = out["output_tokens"]
            tokens_estimated = usage_input is None or usage_output is None
            if tokens_estimated:
                # Cloudflare non restituisce metadati di consumo. I secondi si
                # ricavano dai byte PCM prodotti (s16le 24 kHz mono), quindi
                # l'output — che vale il 99% del conto — e' una MISURA, non una
                # previsione sul testo.
                seconds = len(pcm_data) / float(_PCM_BYTES_PER_SEC)
                if usage_output is None:
                    usage_output = int(seconds * _audio_tokens_per_second(model_key))
                if usage_input is None:
                    usage_input = estimate_input_tokens(final_text)
            usage_input = usage_input or 0
            usage_output = usage_output or 0
            if backend == "cloudflare":
                _backend_state.record_success(model_key)
                spend = actual_cost_breakdown(usage_input, usage_output,
                                              model_key, "cloudflare")
                _backend_state.add_spend(model_key, spend["total_eur"])
            _rpd_increment(model_key)
            break
```

Aggiungi la costante accanto alle altre del modulo:

```python
# PCM s16le, 24 kHz, mono: 2 byte per campione.
_PCM_BYTES_PER_SEC = 24000 * 2
```

e includi `"tokens_estimated": tokens_estimated` nel dict di ritorno di `synthesize` (inizializza `tokens_estimated = False` prima del ciclo, così il valore esiste anche sui percorsi che non lo assegnano).

- [ ] **Step 4: Esegui i test**

Run: `python -m pytest test/test_gemini_cf_usage.py -v`
Expected: PASS (5 test)

- [ ] **Step 5: Verifica la suite**

Run: `python -m pytest test/ -q --tb=short`
Expected: nessun fallimento nuovo.

- [ ] **Step 6: Commit**

```bash
git add gemini_tts.py test/test_gemini_cf_usage.py
git commit -m "feat(tts): stima dei token per Cloudflare e ledger della spesa reale"
```

---

### Task 4: email immediata all'admin allo switch di backend

**Files:**
- Modify: `email_service.py` (nuova funzione dopo `_admin_notify_gemini_failure`, riga 494)
- Modify: `audiobook_app.py` (registrazione del notifier accanto a `tts_backend_state.init(_DATA_DIR)`)
- Test: `test/test_admin_notify_backend_switch.py` (nuovo)

**Interfaces:**
- Consumes: `ADMIN_EMAIL`, `_smtp_available()`, `_send_email(...)` da `email_service`; `gemini_tts.set_backend_switch_notifier` (Task 7 del piano gemello); `tts_backend_state.should_alert_credit` / `credit_left_eur` (Task 8 del piano gemello).
- Produces: `email_service.admin_notify_tts_backend_switch(model_key, reason, detail, job_id, credit_left_eur=None)`.

**Decisione D4:** l'email parte all'ingresso di Vertex, non a fine giornata nel digest. Il margine in failover è +1,9%: ogni ora di ritardo costa margine su ogni job servito nel frattempo.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_admin_notify_backend_switch.py`:

```python
"""Email immediata all'admin allo switch di backend TTS."""
import pytest

import email_service


@pytest.fixture
def _sent(monkeypatch):
    box = []
    monkeypatch.setattr(email_service, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)
    monkeypatch.setattr(
        email_service, "_send_email",
        lambda to, subject, html, **kw: box.append((to, subject, html)) or True)
    return box


def test_the_email_goes_to_the_admin(_sent):
    email_service.admin_notify_tts_backend_switch(
        "flash31", "cf_backend_down", "HTTP 402 code 2021", "job-1")
    assert len(_sent) == 1
    assert _sent[0][0] == "admin@example.com"


def test_the_subject_names_the_switch(_sent):
    email_service.admin_notify_tts_backend_switch(
        "flash31", "cf_backend_down", "HTTP 402 code 2021", "job-1")
    subject = _sent[0][1]
    assert "backend" in subject.lower()
    assert "flash31" in subject


def test_the_body_carries_cause_job_and_margin_warning(_sent):
    email_service.admin_notify_tts_backend_switch(
        "flash31", "cf_backend_down", "HTTP 402 code 2021", "job-42")
    html = _sent[0][2]
    assert "HTTP 402 code 2021" in html
    assert "job-42" in html
    # Il testo deve dire perche' e' urgente, non solo che e' successo.
    assert "margine" in html.lower()


def test_the_body_explains_that_the_return_is_manual(_sent):
    email_service.admin_notify_tts_backend_switch(
        "flash31", "cf_backend_down", "d", "j")
    assert "manuale" in _sent[0][2].lower()


def test_the_credit_left_appears_when_known(_sent):
    email_service.admin_notify_tts_backend_switch(
        "flash31", "cf_backend_down", "d", "j", credit_left_eur=1.23)
    assert "1.23" in _sent[0][2] or "1,23" in _sent[0][2]


def test_nothing_is_sent_without_an_admin_address(monkeypatch):
    monkeypatch.setattr(email_service, "ADMIN_EMAIL", "")
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)
    sent = []
    monkeypatch.setattr(email_service, "_send_email",
                        lambda *a, **k: sent.append(a))
    email_service.admin_notify_tts_backend_switch("flash31", "r", "d", "j")
    assert sent == []


def test_a_send_failure_does_not_propagate(monkeypatch):
    monkeypatch.setattr(email_service, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)

    def _boom(*a, **k):
        raise RuntimeError("SMTP giu'")

    monkeypatch.setattr(email_service, "_send_email", _boom)
    # Il failover e' gia' avvenuto: un guasto SMTP non deve fermare il job.
    email_service.admin_notify_tts_backend_switch("flash31", "r", "d", "j")
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `python -m pytest test/test_admin_notify_backend_switch.py -v`
Expected: FAIL con `AttributeError: module 'email_service' has no attribute 'admin_notify_tts_backend_switch'`

- [ ] **Step 3: Verifica la firma reale di `_send_email`**

Run: `grep -n "def _send_email" email_service.py`

Adatta la chiamata dello Step 4 alla firma effettiva. Se il modulo usa un helper diverso per le email admin, usa quello: la funzione nuova deve assomigliare alle sue vicine, non introdurre un secondo modo di mandare email.

- [ ] **Step 4: Implementa la notifica**

Subito dopo `_admin_notify_gemini_failure` in `email_service.py`:

```python
def admin_notify_tts_backend_switch(model_key, reason, detail, job_id,
                                    credit_left_eur=None):
    """Notifica IMMEDIATA all'admin: il backend TTS e' passato a Vertex.

    Non passa dal digest: il margine in failover e' quasi nullo, quindi ogni
    ora di ritardo costa margine su ogni job servito nel frattempo.

    Un guasto SMTP non deve propagare: il failover e' gia' avvenuto e il job
    sta proseguendo, l'email e' un di piu'.
    """
    if not ADMIN_EMAIL or not _smtp_available():
        return

    reason_label = {
        "cf_backend_down": "backend Cloudflare fuori uso",
        "cf_consecutive_failures": "fallimenti consecutivi oltre soglia",
    }.get(reason, reason)

    credit_row = ""
    if credit_left_eur is not None:
        credit_row = (f"<tr><td><strong>Credito residuo (stima)</strong></td>"
                      f"<td>{credit_left_eur:.2f} &euro;</td></tr>")

    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:640px">
      <h2 style="color:#c0392b;margin-bottom:.3em">
        TTS: passaggio automatico a Vertex</h2>
      <p>Il modello <strong>{model_key}</strong> non viene piu' servito da
         Cloudflare. I job in corso proseguono su Vertex dal chunk corrente,
         senza interruzione e senza differenza udibile.</p>
      <table cellpadding="6" style="border-collapse:collapse;font-size:.95em">
        <tr><td><strong>Causa</strong></td><td>{reason_label}</td></tr>
        <tr><td><strong>Dettaglio</strong></td><td>{detail}</td></tr>
        <tr><td><strong>Job che ha rilevato</strong></td><td>{job_id}</td></tr>
        {credit_row}
      </table>
      <p style="background:#fff4e5;padding:10px;border-left:4px solid #d97706">
        <strong>Perche' e' urgente:</strong> su Vertex il margine scende quasi
        al pareggio, mentre su Cloudflare resta ampio. Il servizio continua a
        funzionare, ma ogni ora in questo stato e' margine perso.</p>
      <p><strong>Il rientro e' manuale.</strong> Risolto il problema (di norma:
         ricaricare il credito), riattiva Cloudflare dal pannello
         <em>Backend TTS</em> della console admin. Non c'e' alcun ripristino
         automatico: un backend caduto per credito esaurito tornerebbe a
         cadere subito, e ogni caduta costa un job.</p>
    </div>
    """

    try:
        _send_email(ADMIN_EMAIL,
                    f"[ABM] TTS {model_key}: switch a Vertex ({reason_label})",
                    html)
    except Exception as e:
        print(f"[admin] invio notifica switch backend fallito: {e}")
```

- [ ] **Step 5: Registra il notifier all'avvio**

In `audiobook_app.py`, subito dopo `tts_backend_state.init(_DATA_DIR)`:

```python
if gemini_tts is not None:
    def _on_tts_backend_switch(model_key, reason, detail, job_id):
        credit = None
        try:
            if tts_backend_state.should_alert_credit():
                credit = tts_backend_state.credit_left_eur()
                tts_backend_state.mark_credit_alerted()
        except Exception:
            credit = None
        email_service.admin_notify_tts_backend_switch(
            model_key, reason, detail, job_id, credit_left_eur=credit)
        _log_activity("", "", "TTS_BACKEND_SWITCH", "", "",
                      model_key, f"{reason}: {str(detail)[:80]}")

    gemini_tts.set_backend_switch_notifier(_on_tts_backend_switch)
```

Verifica con `grep -n "def _log_activity" audiobook_app.py` che la firma corrisponda; adattala se differisce.

- [ ] **Step 6: Esegui i test**

Run: `python -m pytest test/test_admin_notify_backend_switch.py -v`
Expected: PASS (7 test)

- [ ] **Step 7: Verifica che l'app parta**

Run: `python -c "import audiobook_app"`
Expected: nessuna eccezione.

- [ ] **Step 8: Commit**

```bash
git add email_service.py audiobook_app.py test/test_admin_notify_backend_switch.py
git commit -m "feat(tts): email immediata all'admin allo switch di backend su Vertex"
```

---

### Task 5: endpoint admin e pannello di rientro

**Files:**
- Modify: `audiobook_app.py` (nuovo endpoint accanto a `/admin/api/gemini_kill_switch`, riga 7064; HTML accanto al pannello kill-switch, riga 5865; JS accanto a `ksRefresh`, riga 6296)
- Test: `test/test_admin_tts_backend_endpoint.py` (nuovo)

**Interfaces:**
- Consumes: `_admin_auth_ok`, `_admin_auth_from_request`, `ADMIN_TOKEN`, `_log_activity`; `tts_backend_state.state/reset`; `gemini_tts._set_backend`.
- Produces: `GET/POST /admin/api/tts_backend`.

**Contratto dell'endpoint:**

- `GET` → `{"model_key", "active", "tripped_at", "trip_reason", "trip_detail", "trip_job_id", "consecutive_failures", "credit_left_eur", "configured_backend"}`.
- `POST` con `{"action": "reset"}` → riattiva Cloudflare e restituisce lo stesso stato. Ogni altra `action` → 400.
- `POST` con `{"action": "reset", "topup": true}` → azzera anche il ledger della spesa, per il caso normale «ho ricaricato il credito».

**Decisione D5:** questo endpoint è l'unico modo di rientrare su Cloudflare. Nessun timer, nessun ripristino automatico.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_admin_tts_backend_endpoint.py`:

```python
"""Endpoint admin per lo stato del backend TTS e il rientro su Cloudflare."""
import pytest

import audiobook_app
import tts_backend_state as st


@pytest.fixture
def client(tmp_path, monkeypatch):
    st.init(str(tmp_path))
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "segreto")
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        yield c


AUTH = {"X-Admin-Token": "segreto"}


def test_unauthenticated_is_rejected(client):
    assert client.get("/admin/api/tts_backend").status_code == 401


def test_wrong_token_is_rejected(client):
    r = client.get("/admin/api/tts_backend", headers={"X-Admin-Token": "no"})
    assert r.status_code == 401


def test_get_returns_a_clean_state(client):
    r = client.get("/admin/api/tts_backend", headers=AUTH)
    assert r.status_code == 200
    body = r.get_json()
    assert body["tripped_at"] is None
    assert "credit_left_eur" in body


def test_get_reports_a_trip(client):
    st.trip("flash31", reason="cf_backend_down", detail="HTTP 402", job_id="j9")
    body = client.get("/admin/api/tts_backend", headers=AUTH).get_json()
    assert body["active"] == "vertex"
    assert body["trip_reason"] == "cf_backend_down"
    assert body["trip_job_id"] == "j9"


def test_reset_clears_the_trip(client):
    st.trip("flash31", reason="cf_backend_down", detail="d", job_id="j")
    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "reset"})
    assert r.status_code == 200
    assert r.get_json()["tripped_at"] is None
    assert st.is_tripped("flash31") is False


def test_reset_with_topup_clears_the_spend_ledger(client, monkeypatch):
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    st.add_spend("flash31", 30.0)
    st.trip("flash31", reason="cf_backend_down", detail="d", job_id="j")
    client.post("/admin/api/tts_backend", headers=AUTH,
                json={"action": "reset", "topup": True})
    assert st.credit_left_eur() == pytest.approx(50.0)


def test_reset_without_topup_keeps_the_ledger(client, monkeypatch):
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    st.add_spend("flash31", 30.0)
    client.post("/admin/api/tts_backend", headers=AUTH,
                json={"action": "reset"})
    assert st.credit_left_eur() == pytest.approx(20.0)


def test_an_unknown_action_is_rejected(client):
    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "esplodi"})
    assert r.status_code == 400


def test_the_endpoint_is_invisible_without_an_admin_token(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "")
    assert client.get("/admin/api/tts_backend").status_code == 404
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `python -m pytest test/test_admin_tts_backend_endpoint.py -v`
Expected: FAIL con 404 su tutte le rotte.

- [ ] **Step 3: Implementa l'endpoint**

Subito dopo `admin_api_gemini_kill_switch` in `audiobook_app.py`:

```python
@app.route("/admin/api/tts_backend", methods=["GET", "POST"])
def admin_api_tts_backend():
    """Stato del backend TTS e rientro manuale su Cloudflare.

    GET  -> stato corrente del modello (default flash31).
    POST -> {"action": "reset", "topup": bool?}: riattiva Cloudflare.
            Con topup=true azzera anche il ledger della spesa, che e' il caso
            normale dopo una ricarica del credito.

    Il rientro e' manuale per scelta (D5): un backend caduto per credito
    esaurito tornerebbe a cadere subito, e ogni caduta costa un job.
    """
    if not ADMIN_TOKEN:
        return jsonify({"error": "Admin UI disabled"}), 404
    if not _admin_auth_ok(_admin_auth_from_request()):
        time.sleep(0.5)
        return jsonify({"error": "Unauthorized"}), 401
    if gemini_tts is None:
        return jsonify({"error": "Gemini TTS module not loaded"}), 503

    model_key = (request.args.get("model_key")
                 or (request.get_json(silent=True) or {}).get("model_key")
                 or "flash31")

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        action = str(data.get("action", "") or "").strip().lower()
        if action != "reset":
            return jsonify({"error": f"Azione non riconosciuta: {action!r}"}), 400
        had_trip = tts_backend_state.reset(model_key)
        if data.get("topup"):
            tts_backend_state.reset_spend()
        gemini_tts._set_backend(model_key, "cloudflare")
        _log_activity("", "", "ADMIN_TTS_BACKEND_RESET", "", _get_client_ip(),
                      model_key, f"had_trip={had_trip} topup={bool(data.get('topup'))}")
        print(f"[admin] Backend TTS {model_key} riportato su Cloudflare "
              f"(aveva trip: {had_trip})")

    s = tts_backend_state.state(model_key)
    return jsonify({
        "model_key": model_key,
        "active": s.get("active") or "cloudflare",
        "tripped_at": s.get("tripped_at"),
        "trip_reason": s.get("trip_reason"),
        "trip_detail": s.get("trip_detail"),
        "trip_job_id": s.get("trip_job_id"),
        "consecutive_failures": s.get("consecutive_failures", 0),
        "credit_left_eur": round(tts_backend_state.credit_left_eur(), 2),
        "configured_backend": (os.environ.get("ABM_GEMINI_BACKEND", "auto")
                               or "auto").strip().lower(),
    })
```

- [ ] **Step 4: Aggiungi il pannello alla console**

Nell'HTML, dopo il blocco del kill-switch (riga 5871 circa, dopo `<button type="button" id="ksToggleBtn" disabled>...</button>` e la chiusura del suo contenitore), inserisci un pannello con la stessa struttura visiva dei vicini:

```html
  <h3>Backend TTS</h3>
  <div id="tbStatus" style="font-size:.9rem;color:var(--muted)">Caricamento stato...</div>
  <div id="tbDetail" style="font-size:.85rem;color:var(--muted);display:none;margin-top:4px"></div>
  <label style="display:block;margin:8px 0;font-size:.85rem">
    <input type="checkbox" id="tbTopup"> Ho ricaricato il credito (azzera il contatore di spesa)
  </label>
  <button type="button" id="tbResetBtn" disabled>...</button>
```

e il JS, accanto a `ksRefresh`:

```javascript
  // ---- Backend TTS: stato del failover e rientro su Cloudflare ----
  async function tbRefresh(){
    try {
      const r = await fetch("/admin/api/tts_backend",
                            {headers: {"X-Admin-Token": ADMIN_TOKEN}});
      if (!r.ok) { $("tbStatus").textContent = "Errore caricamento stato (" + r.status + ")"; return; }
      tbApply(await r.json());
    } catch (e) {
      $("tbStatus").textContent = "Errore: " + e;
    }
  }
  function tbApply(s){
    const btn = $("tbResetBtn");
    const status = $("tbStatus");
    const detail = $("tbDetail");
    if (s.configured_backend !== "cloudflare") {
      status.innerHTML = '<span style="color:var(--muted)">Cloudflare non configurato · il TTS gira su ' + s.active + '</span>';
      btn.disabled = true;
      btn.textContent = "Non applicabile";
      detail.style.display = "none";
      return;
    }
    if (s.tripped_at) {
      status.innerHTML = '<span style="color:var(--err);font-weight:600">SU VERTEX</span> · margine quasi azzerato';
      detail.innerHTML = "Causa: " + (s.trip_reason || "?") + " · " + (s.trip_detail || "") +
                         "<br>Dal " + s.tripped_at.slice(0,19).replace("T"," ") +
                         " · job " + (s.trip_job_id || "?") +
                         "<br>Credito residuo (stima): " + s.credit_left_eur + " €";
      detail.style.display = "block";
      btn.disabled = false;
      btn.textContent = "Riporta su Cloudflare";
      btn.style.background = "var(--ok)";
    } else {
      status.innerHTML = '<span style="color:var(--ok);font-weight:600">SU CLOUDFLARE</span> · credito residuo (stima): ' + s.credit_left_eur + ' €';
      detail.style.display = "none";
      btn.disabled = true;
      btn.textContent = "Nessun failover attivo";
    }
  }
  async function tbReset(){
    const btn = $("tbResetBtn");
    if (!confirm("Riportare il TTS su Cloudflare?\n\nFallo solo dopo aver risolto la causa del guasto: se il problema persiste il failover riscatta subito, e ogni ricaduta costa un job.")) return;
    btn.disabled = true;
    btn.textContent = "...";
    try {
      const r = await fetch("/admin/api/tts_backend", {
        method: "POST",
        headers: {"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"},
        body: JSON.stringify({action: "reset", topup: $("tbTopup").checked}),
      });
      if (!r.ok) { alert("Errore: " + r.status); await tbRefresh(); return; }
      tbApply(await r.json());
      $("tbTopup").checked = false;
    } catch (e) {
      alert("Errore: " + e);
      await tbRefresh();
    }
  }
  $("tbResetBtn").addEventListener("click", tbReset);
  tbRefresh();
```

Verifica che il punto in cui `ksRefresh()` viene invocata all'avvio della pagina esista e aggiungi `tbRefresh()` nello stesso posto se il pattern locale è quello.

- [ ] **Step 5: Esegui i test**

Run: `python -m pytest test/test_admin_tts_backend_endpoint.py -v`
Expected: PASS (9 test)

- [ ] **Step 6: Verifica la console a mano**

Run: `python audiobook_app.py`, apri `/admin/log-activity?token=<ABM_ADMIN_TOKEN>` e controlla che il pannello «Backend TTS» compaia, mostri lo stato e non generi errori in console del browser. Chiudi il server quando hai finito.

- [ ] **Step 7: Commit**

```bash
git add audiobook_app.py test/test_admin_tts_backend_endpoint.py
git commit -m "feat(admin): pannello Backend TTS con rientro manuale su Cloudflare"
```

---

### Task 6: documentazione e versione

**Files:**
- Modify: `PARAMETRI_CONFIGURAZIONE.md`
- Modify: `CLAUDE.md`
- Modify: `version.py`

**Interfaces:**
- Consumes: tutte le variabili introdotte dai due piani.
- Produces: la documentazione che rende il rollout eseguibile da qualcun altro.

- [ ] **Step 1: Documenta le variabili**

In `PARAMETRI_CONFIGURAZIONE.md`, aggiungi una sezione **Backend TTS Cloudflare** con una riga per ciascuna, valore corrente, file e riga sorgente:

`ABM_GEMINI_BACKEND` (valore nuovo `cloudflare`), `ABM_CF_ACCOUNT_ID`, `ABM_CF_API_TOKEN`, `ABM_CF_TIMEOUT_MS`, `ABM_CF_TRIP_FAILURES`, `ABM_CF_CREDIT_TOPUP_FEE`, `ABM_CF_CREDIT_BALANCE_EUR`, `ABM_CF_CREDIT_ALERT_EUR`, `ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT`, `ABM_GEMINI_31FLASH_CF_INPUT_USD_PER_MTOK`, `ABM_GEMINI_31FLASH_CF_OUTPUT_USD_PER_MTOK`, `ABM_TTS_MIN_CHUNK_CHARS` (dal piano Fase 1, se non già documentata lì).

Per `ABM_CF_API_TOKEN` scrivi esplicitamente che il valore non va mai riportato nella documentazione, nei log o negli export.

- [ ] **Step 2: Aggiorna la mappa dei moduli**

In `CLAUDE.md`, nella tabella **Backend Modules**, aggiungi due righe:

| Module | Role |
|--------|------|
| `gemini_transport.py` | Contratto di trasporto per la sintesi Gemini (`TransportError` + enum `kind`) e adapter Cloudflare Workers AI. Modulo foglia: solo stdlib e `requests`. L'adapter Vertex resta in `gemini_tts.py` perché dipende dal client SDK. |
| `tts_backend_state.py` | Stato persistito del backend TTS in `ABM_DATA_DIR/_tts_backend_state.json`: circuit breaker a senso unico Cloudflare→Vertex (trip idempotente sotto lock, reset solo manuale da console admin) e ledger della spesa Cloudflare per il pre-allarme sul credito. Modulo foglia. |

Aggiungi inoltre, nella sezione **Key Configuration**, una tabella «Backend TTS Cloudflare» con le variabili e i default, e in **Background Threads** una riga che spieghi il failover: «**Failover TTS Cloudflare→Vertex** — allo scatto del breaker il job in corso prosegue su Vertex dal chunk corrente (audio identico byte per byte); email immediata all'admin; rientro solo da console.»

- [ ] **Step 3: Bump di versione**

In `version.py`, alza la minor (è una feature nuova, non un fix). Run: `cat version.py` per leggere il valore corrente prima di modificarlo.

- [ ] **Step 4: Commit**

```bash
git add -f PARAMETRI_CONFIGURAZIONE.md version.py
git commit -m "docs(tts): documenta il backend Cloudflare e bump di versione"
```

`CLAUDE.md` non va mai tracciato da git: modificalo ma **non** aggiungerlo al commit.

---

### Task 7: rollout e rollback

**Files:**
- Create: `docs/RUNBOOK_CLOUDFLARE_TTS.md`

**Interfaces:**
- Consumes: tutto quanto sopra.
- Produces: la procedura che l'admin esegue sul server di produzione.

**Strategia scelta:** switch completo con rollback, non canary. Il codice arriva in produzione **dormiente** — nessun ambiente setta `ABM_GEMINI_BACKEND=cloudflare` e `auto` non seleziona mai Cloudflare — e resta lì finché non si decide di accendere. L'accensione è una variabile d'ambiente e un restart; il rollback è la stessa variabile riportata indietro.

- [ ] **Step 1: Verifica i criteri GO**

Prima di scrivere il runbook, controlla lo stato dei criteri nella spec (§10 e §10.2, scritta dal Task 1 del piano gemello):

- **G2** (parità voci): chiuso — 30/30 verificate.
- **G3** (qualità A/B): chiuso per giudizio dell'esercente.
- **G4** (latenza p95): stato da §10.2. Se non è chiuso, il runbook deve dirlo e indicare cosa osservare nelle prime ore.
- **G5** (nessun errore 2017 su un libro intero): richiede il piano Fase 1 implementato e provato su un libro reale.

Se G5 non è chiuso, il runbook deve dichiarare che l'accensione non è autorizzata: il 2017 è deterministico e colpirebbe ogni libro con la stessa struttura di titoli.

- [ ] **Step 2: Scrivi il runbook**

Crea `docs/RUNBOOK_CLOUDFLARE_TTS.md` con queste sezioni:

1. **Stato dei criteri GO** — la tabella G2-G5 con esito e data, e la riga netta «accensione autorizzata / non autorizzata».
2. **Prerequisiti** — credito AI Gateway caricato e il suo importo; il token generato con i soli permessi Workers AI; `ABM_CF_CREDIT_BALANCE_EUR` allineato all'importo caricato.
3. **Accensione** — le variabili da aggiungere all'unit systemd (`ABM_GEMINI_BACKEND=cloudflare`, `ABM_CF_ACCOUNT_ID`, `ABM_CF_API_TOKEN`, `ABM_CF_CREDIT_BALANCE_EUR`), `systemctl daemon-reload`, `systemctl restart audiobook-maker`. Ricorda che le `ABM_*` **non sono ereditate dalla shell SSH**: stanno nell'unit, e vanno lette da lì o da `/proc/<pid>/environ`.
4. **Verifica post-accensione** — la riga di log `[gemini-tts] Backend resolved (flash31): cloudflare`; il pannello «Backend TTS» che mostra SU CLOUDFLARE; un job di prova breve; il costo reale registrato confrontato col consumo mostrato nella dashboard Cloudflare (Workers & Pages → AI → Usage) sulla stessa finestra temporale. Nota che il saldo cala dell'**addebito**, non del costo: la commissione di ricarica si paga comprando il credito, e confrontare la riga sbagliata produce uno scarto sistematico del +5%.
5. **Cosa osservare nelle prime 24 ore** — email di switch; latenza percepita sui job lunghi (G4, se non chiuso); il credito residuo nel pannello; eventuali errori 2017 nei log.
6. **Rollback** — riportare `ABM_GEMINI_BACKEND=vertex` nell'unit, `daemon-reload`, `restart`. I job in corso al momento del restart seguono la sorte consueta di un restart: verifica il loro esito nell'activity log. Il rollback **non** richiede di toccare lo stato del breaker.
7. **Failover: cosa fare quando arriva l'email** — diagnosi (di norma credito esaurito), ricarica, aggiornamento di `ABM_CF_CREDIT_BALANCE_EUR`, rientro dal pannello con la casella «Ho ricaricato il credito» spuntata. Ribadisci che il rientro non va fatto prima di aver risolto la causa.
8. **flash25 resta su Vertex, in modo permanente.** Verificato il 26/08/2026: Cloudflare non ospita alcuna variante TTS di Gemini 2.5 — ogni candidato risponde `404 / "Model not found"`. Il modello economico del listino continua quindi a passare da Vertex, con le sue tariffe Google e il suo margine, e non è toccato né dal failover né dalla tariffa mista. Il runbook deve dirlo esplicitamente: accendere Cloudflare **non** sposta flash25 e non ne cambia il prezzo.

- [ ] **Step 3: Commit**

```bash
git add -f docs/RUNBOOK_CLOUDFLARE_TTS.md
git commit -m "docs(tts): runbook di accensione e rollback del backend Cloudflare"
```

- [ ] **Step 4: Chiedi conferma prima del push**

Il push su `main` è un deploy automatico in produzione. **Non pushare senza conferma esplicita dell'utente in questo turno.** Presenta cosa verrà deployato (codice dormiente: nessun cambiamento di comportamento finché non si settano le variabili) e attendi.

---

## Stato al termine

Il backend Cloudflare è completo, documentato e pronto all'accensione, ma **inattivo**: senza `ABM_GEMINI_BACKEND=cloudflare` il comportamento della produzione è identico a oggi. L'accensione è una decisione operativa separata, guidata dal runbook e subordinata ai criteri GO.
