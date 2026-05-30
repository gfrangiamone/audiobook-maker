# Cancel Gemini TTS con floor + audio parziale — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementare la policy di cancel volontario per job Gemini TTS con floor sul costo piattaforma (Google + fee PayPal), consegna MP3 parziale, hard-cutoff al 70% di completamento. Spec di riferimento: `docs/superpowers/specs/2026-05-25-cancel-gemini-floor-design.md`.

**Architecture:** Helper engine-agnostic `compute_cancel_retention(provider_cost_eur, payment_method, paid_eur)` calcola trattenuto e refund. Branch `_CancelledError` in `generation_engine.py` ristrutturato: snapshot floor → encoding parziale MP3 → audit `cancelled_partial` → refund con `retained_eur` → token download + email. Endpoint `/api/cancel/<job_id>` gateato server-side sulla soglia `ABM_GEMINI_CANCEL_LOCK_PCT`. Frontend: modal di conferma statico in 7 lingue + disable bottone con tooltip oltre soglia.

**Tech Stack:** Python 3.x, Flask, pytest, vanilla JS (SPA), JSON i18n. Convenzione test esistente: `test/test_*.py` con pytest. Money-critical: arrotondamenti a 2 decimali, lock su voucher (esistenti in `payment.py`).

**Naming verificato dal codice (drift minore vs spec):**
- Il dict che contiene il costo Google cumulativo si chiama `job["gemini_actual"]` (non `gemini_usage` come nella spec §3.1). La chiave dentro è `google_cost_eur`. La spec verrà aggiornata nel Task 13.
- `payment._create_voucher` ha già un parametro `apply_bonus=True` (non da aggiungere ex-novo): basta passare `apply_bonus=False` per il cancel volontario.

---

## File Structure

### File da creare

| Path | Responsabilità |
|------|----------------|
| `cancel_policy.py` | Modulo top-level con il solo helper `compute_cancel_retention(provider_cost_eur, payment_method, paid_eur) -> dict`. Engine-agnostic, no import circolari. |
| `test/test_cancel_policy.py` | Test unitari della matrice §10.1 della spec. |
| `test/test_cancel_endpoint_lock.py` | Test del gate 70% in `/api/cancel/<job_id>` con Flask test client. |
| `test/test_refund_with_retained.py` | Test di `_refund_gemini_payment` con `retained_eur > 0`. |
| `test/test_audit_cancel_fields.py` | Test estensione `_write_gemini_audit` con campi `cancel_*`. |
| `test/test_progress_pct.py` | Test del helper `_progress_pct(job)`. |
| `test/test_email_cancel_partial.py` | Test del nuovo template email cancel parziale. |

### File da modificare

| Path | Cambio |
|------|--------|
| `generation_engine.py` | `_refund_gemini_payment`: aggiungere `retained_eur: float = 0.0` (default = comportamento attuale). `_write_gemini_audit`: estendere `rec` con `cancel_paid_eur`, `cancel_retained_eur`, `cancel_refund_eur`, `cancel_progress_pct`, `cancel_partial_audio_delivered`. Aggiungere helper top-level `_progress_pct(job)`. Branch `_CancelledError` (linea 2658): snapshot floor → encoding parziale MP3 → audit con outcome `cancelled_partial`/`cancelled_refunded` → refund con `retained_eur` → email + token download. |
| `audiobook_app.py` | `/api/cancel/<job_id>` (linea 5680): gate `ABM_GEMINI_CANCEL_LOCK_PCT`. Mapping audit outcome (linee 3221, 3457, 3466): aggiungere `cancelled_partial` con badge "Annullato (parz.)". Endpoint SSE progress: propagare `partial_download_url`, `cancel_meta`, `refund_voucher_code` quando status cancelled. Esporre `ABM_GEMINI_CANCEL_LOCK_PCT` al frontend. |
| `email_service.py` | Nuova funzione `_send_gemini_cancelled_partial_email(email, paid_eur, retained_eur, refund_eur, voucher_code, book_title, download_url, lang)`. |
| `static/js/app.js` | Modal conferma cancel (solo Gemini); listener SSE per disabilitare bottone oltre soglia con tooltip; gestione 409 `cancel_locked_progress`; rendering link MP3 parziale + riepilogo refund. |
| `templates/_fragments/i18n_data.js` | Aggiungere chiavi i18n. |
| `i18n/it.json` + `en.json` + `fr.json` + `es.json` + `de.json` + `zh.json` + `hi.json` | Traduzioni delle chiavi. |
| `md_files/PARAMETRI_CONFIGURAZIONE.md` | Aggiungere `ABM_GEMINI_CANCEL_LOCK_PCT`. |
| `md_files/ttsgemini.md` | Nuova sezione "Cancel policy con floor + audio parziale"; aggiornare §8.1, §14.1, §15.2. |

---

## Task 1: Helper `compute_cancel_retention` (TDD)

**Files:**
- Create: `cancel_policy.py`
- Test: `test/test_cancel_policy.py`

- [ ] **Step 1: Scrivere i test (matrice §10.1 della spec)**

`test/test_cancel_policy.py`:

```python
"""Test della funzione compute_cancel_retention (cancel_policy.py).

Matrice da spec docs/superpowers/specs/2026-05-25-cancel-gemini-floor-design.md §10.1.
"""
import os
import pytest

# Forza i default delle env PRIMA dell'import del modulo, in caso il modulo
# legga le env all'import-time (anche se in realta' deve leggerle a runtime).
os.environ.setdefault("ABM_GEMINI_PAYPAL_PERCENT_FEE", "3.4")
os.environ.setdefault("ABM_GEMINI_PAYPAL_FIXED_FEE_EUR", "0.34")

from cancel_policy import compute_cancel_retention


@pytest.mark.parametrize("paid,prov_cost,method,exp_retained,exp_refund,exp_fees", [
    (0.00, 0.00, "",        0.00, 0.00, 0.00),
    (0.00, 0.10, "",        0.00, 0.00, 0.00),
    (2.00, 0.00, "voucher", 0.00, 2.00, 0.00),
    (2.00, 0.00, "paypal",  0.41, 1.59, 0.41),
    (2.00, 0.30, "voucher", 0.30, 1.70, 0.00),
    (2.00, 0.30, "paypal",  0.71, 1.29, 0.41),
    (2.00, 1.80, "voucher", 1.80, 0.20, 0.00),
    (2.00, 1.80, "paypal",  2.00, 0.00, 0.41),
    (2.00, 5.00, "paypal",  2.00, 0.00, 0.41),
    (0.60, 0.30, "paypal",  0.60, 0.00, 0.36),
    (1.50, 0.20, "paypal",  0.59, 0.91, 0.39),
])
def test_compute_cancel_retention_matrix(paid, prov_cost, method,
                                          exp_retained, exp_refund, exp_fees):
    out = compute_cancel_retention(prov_cost, method, paid)
    assert out["retained_eur"] == pytest.approx(exp_retained, abs=0.01)
    assert out["refund_eur"] == pytest.approx(exp_refund, abs=0.01)
    assert out["paypal_fees_eur"] == pytest.approx(exp_fees, abs=0.01)


def test_compute_cancel_retention_returns_floats():
    out = compute_cancel_retention(0.30, "voucher", 2.00)
    assert isinstance(out["retained_eur"], float)
    assert isinstance(out["refund_eur"], float)
    assert isinstance(out["paypal_fees_eur"], float)


def test_compute_cancel_retention_keys():
    out = compute_cancel_retention(0.0, "", 0.0)
    assert set(out.keys()) == {"retained_eur", "refund_eur", "paypal_fees_eur"}


def test_compute_cancel_retention_unknown_method_treated_as_no_fees():
    out = compute_cancel_retention(0.30, "stripe", 2.00)
    assert out["paypal_fees_eur"] == 0.00
    assert out["retained_eur"] == pytest.approx(0.30, abs=0.01)
```

- [ ] **Step 2: Eseguire test per verificare che falliscano**

```
pytest test/test_cancel_policy.py -v
```

Atteso: `ModuleNotFoundError: No module named 'cancel_policy'`.

- [ ] **Step 3: Implementare il modulo**

`cancel_policy.py`:

```python
"""Helper engine-agnostic per il calcolo del trattenuto su cancel volontario.

Usato in Fase 1 da Gemini TTS (run_generation branch _CancelledError) e in
Fase 2 (futura, spec separata) dall'optimization LLM. La firma e' agnostica
rispetto al provider: il chiamante passa il costo reale del provider gia'
accumulato per la quota di lavoro eseguita.

Reference: docs/superpowers/specs/2026-05-25-cancel-gemini-floor-design.md
"""
from __future__ import annotations

import os
from typing import Dict


def _paypal_fee_pct() -> float:
    try:
        return float(os.environ.get("ABM_GEMINI_PAYPAL_PERCENT_FEE", "3.4")
                     .replace(",", "."))
    except (TypeError, ValueError):
        return 3.4


def _paypal_fee_fixed_eur() -> float:
    try:
        return float(os.environ.get("ABM_GEMINI_PAYPAL_FIXED_FEE_EUR", "0.34")
                     .replace(",", "."))
    except (TypeError, ValueError):
        return 0.34


def compute_cancel_retention(provider_cost_eur: float,
                              payment_method: str,
                              paid_eur: float) -> Dict[str, float]:
    """Calcola trattenuto e refund per un cancel volontario di un job pagato."""
    paid = max(0.0, float(paid_eur or 0.0))
    cost = max(0.0, float(provider_cost_eur or 0.0))
    if payment_method == "paypal" and paid > 0:
        fees = round(_paypal_fee_fixed_eur() + paid * _paypal_fee_pct() / 100.0, 2)
    else:
        fees = 0.0
    raw_retained = cost + fees
    retained = round(min(paid, max(0.0, raw_retained)), 2)
    refund = round(max(0.0, paid - retained), 2)
    return {
        "retained_eur": retained,
        "refund_eur": refund,
        "paypal_fees_eur": round(fees, 2),
    }
```

- [ ] **Step 4: Eseguire test per verificare che passino**

```
pytest test/test_cancel_policy.py -v
```

Atteso: 13 PASS (11 parametrize + 3 standalone).

- [ ] **Step 5: Commit**

```
git add cancel_policy.py test/test_cancel_policy.py
git commit -m "feat(cancel): add compute_cancel_retention helper for voluntary cancel floor"
```

---

## Task 2: Helper `_progress_pct(job)` (TDD)

**Files:**
- Modify: `generation_engine.py` (top-level, vicino agli altri helper job-utility)
- Test: `test/test_progress_pct.py`

- [ ] **Step 1: Scrivere test**

`test/test_progress_pct.py`:

```python
"""Test del helper _progress_pct(job)."""
from generation_engine import _progress_pct


def test_progress_pct_zero_when_total_missing():
    assert _progress_pct({}) == 0
    assert _progress_pct({"progress_current": 10}) == 0
    assert _progress_pct({"progress_total": 0}) == 0


def test_progress_pct_basic():
    assert _progress_pct({"progress_current": 50, "progress_total": 100}) == 50
    assert _progress_pct({"progress_current": 71, "progress_total": 100}) == 71


def test_progress_pct_clamped_high():
    assert _progress_pct({"progress_current": 200, "progress_total": 100}) == 100


def test_progress_pct_clamped_negative():
    assert _progress_pct({"progress_current": -5, "progress_total": 100}) == 0


def test_progress_pct_rounded():
    out = _progress_pct({"progress_current": 18, "progress_total": 63})
    assert out in (28, 29)
```

- [ ] **Step 2: Eseguire test (deve fallire)**

```
pytest test/test_progress_pct.py -v
```

Atteso: `ImportError: cannot import name '_progress_pct' from 'generation_engine'`.

- [ ] **Step 3: Implementare `_progress_pct` in `generation_engine.py`**

Aggiungere vicino agli altri helper top-level, prima di `_refund_gemini_payment`:

```python
def _progress_pct(job: dict) -> int:
    """Percentuale di completamento (0..100) di un job in corso.

    Robusta a campi mancanti o valori anomali: clamp 0..100, 0 se denominatore
    nullo/mancante.
    """
    try:
        total = float(job.get("progress_total", 0) or 0)
        if total <= 0:
            return 0
        current = float(job.get("progress_current", 0) or 0)
        pct = int(round(current / total * 100))
        return max(0, min(100, pct))
    except (TypeError, ValueError):
        return 0
```

- [ ] **Step 4: Eseguire test**

```
pytest test/test_progress_pct.py -v
```

Atteso: 5 PASS.

- [ ] **Step 5: Commit**

```
git add generation_engine.py test/test_progress_pct.py
git commit -m "feat(cancel): add _progress_pct helper for cancel lock gate"
```

---

## Task 3: `_refund_gemini_payment` con parametro `retained_eur` (TDD)

**Files:**
- Modify: `generation_engine.py:1158-1201`
- Test: `test/test_refund_with_retained.py`

- [ ] **Step 1: Scrivere test**

`test/test_refund_with_retained.py`:

```python
"""Test di _refund_gemini_payment con retained_eur > 0 (cancel volontario)."""
from unittest.mock import patch

import pytest

import generation_engine


@pytest.fixture
def voucher_job():
    return {
        "payment": {"token": "VCR-ABC", "total_eur": 2.00, "method": "voucher"},
    }


@pytest.fixture
def paypal_job():
    return {
        "payment": {"token": "PAY-XYZ", "total_eur": 2.00, "method": "paypal"},
    }


def test_refund_zero_retained_voucher_full_refund(voucher_job):
    with patch.object(generation_engine.payment, "_voucher_refund") as mock_refund, \
         patch.object(generation_engine.payment, "_vouchers",
                      {"VCR-ABC": {"email": "u@x.it"}}):
        out = generation_engine._refund_gemini_payment(
            "job1", voucher_job, "test", retained_eur=0.0)
        mock_refund.assert_called_once()
        assert mock_refund.call_args[0][1] == pytest.approx(2.00)
    assert out["amount_eur"] == pytest.approx(2.00)


def test_refund_partial_voucher(voucher_job):
    with patch.object(generation_engine.payment, "_voucher_refund") as mock_refund, \
         patch.object(generation_engine.payment, "_vouchers",
                      {"VCR-ABC": {"email": "u@x.it"}}):
        out = generation_engine._refund_gemini_payment(
            "job1", voucher_job, "cancelled", retained_eur=0.30)
        assert mock_refund.call_args[0][1] == pytest.approx(1.70)
    assert out["amount_eur"] == pytest.approx(1.70)


def test_refund_partial_paypal_no_bonus(paypal_job):
    with patch.object(generation_engine.payment, "_payments",
                      {"PAY-XYZ": {"email": "u@x.it"}}), \
         patch.object(generation_engine.payment, "_create_voucher",
                      return_value=("REF-001", 1.29)) as mock_create:
        out = generation_engine._refund_gemini_payment(
            "job1", paypal_job, "cancelled", retained_eur=0.71)
        kwargs = mock_create.call_args.kwargs
        amount_arg = kwargs.get("amount_eur")
        if amount_arg is None and len(mock_create.call_args.args) > 1:
            amount_arg = mock_create.call_args.args[1]
        assert amount_arg == pytest.approx(1.29)
        assert kwargs.get("apply_bonus") is False
    assert out["voucher_code"] == "REF-001"
    assert out["amount_eur"] == pytest.approx(1.29)


def test_refund_zero_when_retained_equals_paid(voucher_job):
    with patch.object(generation_engine.payment, "_voucher_refund") as mock_refund, \
         patch.object(generation_engine.payment, "_vouchers",
                      {"VCR-ABC": {"email": "u@x.it"}}):
        out = generation_engine._refund_gemini_payment(
            "job1", voucher_job, "cancelled", retained_eur=2.00)
        mock_refund.assert_not_called()
    assert out["amount_eur"] == pytest.approx(0.0)


def test_refund_zero_retained_default_paypal_keeps_bonus(paypal_job):
    """Comportamento legacy: senza retained_eur il refund e' 100% con apply_bonus default True."""
    with patch.object(generation_engine.payment, "_payments",
                      {"PAY-XYZ": {"email": "u@x.it"}}), \
         patch.object(generation_engine.payment, "_create_voucher",
                      return_value=("REF-002", 2.20)) as mock_create:
        generation_engine._refund_gemini_payment("job1", paypal_job, "error")
        assert mock_create.call_args.kwargs.get("apply_bonus", True) is True
```

- [ ] **Step 2: Eseguire test (devono fallire)**

```
pytest test/test_refund_with_retained.py -v
```

Atteso: i test `test_refund_partial_*` falliscono per TypeError su `retained_eur`.

- [ ] **Step 3: Modificare `_refund_gemini_payment` in `generation_engine.py:1158`**

Sostituire la signature e il corpo con:

```python
def _refund_gemini_payment(job_id, job, reason, retained_eur: float = 0.0):
    """F3: Refund Gemini payment on cancel/error.

    For voucher tokens, refunds the amount on the original voucher.
    For PayPal tokens, emits a refund voucher to the buyer's email.

    `retained_eur` (default 0.0) e' l'importo trattenuto dalla piattaforma
    per coprire i costi gia' sostenuti (Google + fee PayPal). Solo i cancel
    volontari (`reason == "cancelled"`) lo usano; quota/budget/errori
    continuano a passare 0.0 -> rimborso integrale.

    apply_bonus al voucher emesso: True per failure piattaforma (default),
    False per cancel volontario (retained_eur > 0 oppure reason=="cancelled").

    Non-fatal: any failure is logged and swallowed.

    Returns a dict with refund details (or None if no refund applied):
        {"method": "voucher"|"paypal", "amount_eur": float,
         "email": str, "voucher_code": str|None}
    """
    payment_meta = job.get("payment") or {}
    tok = payment_meta.get("token")
    paid = float(payment_meta.get("total_eur", 0) or 0)
    method = payment_meta.get("method", "")
    if not tok or paid <= 0:
        return None
    refund_amt = round(max(0.0, paid - float(retained_eur or 0.0)), 2)
    apply_bonus = not (reason == "cancelled" or float(retained_eur or 0.0) > 0)
    result = {"method": method, "amount_eur": refund_amt, "email": "", "voucher_code": None}
    if refund_amt <= 0:
        # E2: trattenuto >= pagato -> nessun rimborso, popoliamo email per audit
        try:
            if method == "voucher":
                v = payment._vouchers.get(tok, {}) if hasattr(payment, "_vouchers") else {}
                result["email"] = v.get("email", "") or ""
            elif method == "paypal":
                pay = payment._payments.get(tok, {})
                result["email"] = pay.get("email", "") or ""
        except Exception:
            pass
        return result
    try:
        if method == "voucher":
            payment._voucher_refund(tok, refund_amt, job_id=job_id, reason=reason)
            voucher = payment._vouchers.get(tok, {}) if hasattr(payment, "_vouchers") else {}
            result["email"] = voucher.get("email", "") or ""
        elif method == "paypal":
            pay = payment._payments.get(tok, {})
            email = pay.get("email", "") or ""
            result["email"] = email
            if email:
                code, _bonus = payment._create_voucher(
                    email, refund_amt, origin_order_id=tok, origin_job_id=job_id,
                    kind="refund", note=f"refund {reason} job {job_id}",
                    apply_bonus=apply_bonus,
                )
                result["voucher_code"] = code
                job["refund_voucher_code"] = code
            else:
                print(
                    f"[{job_id}] WARNING: cannot emit refund voucher  -  "
                    f"PayPal order {tok} has no buyer email "
                    f"(amount {refund_amt:.2f} EUR, reason {reason})"
                )
    except Exception as _ref_err:
        print(f"[{job_id}] refund failed ({reason}, non-fatal): {_ref_err}")
        return None
    return result
```

- [ ] **Step 4: Eseguire test**

```
pytest test/test_refund_with_retained.py -v
```

Atteso: 5 PASS.

- [ ] **Step 5: Verificare regressione**

```
pytest test/ -v -k "refund or gemini"
```

Atteso: tutti i test precedenti passano (`retained_eur=0.0` default retro-compatibile).

- [ ] **Step 6: Commit**

```
git add generation_engine.py test/test_refund_with_retained.py
git commit -m "feat(cancel): _refund_gemini_payment accepts retained_eur for voluntary cancel"
```

---

## Task 4: Estendere `_write_gemini_audit` con campi cancel_*

**Files:**
- Modify: `generation_engine.py:1590-1709` (funzione `_write_gemini_audit`)
- Test: `test/test_audit_cancel_fields.py`

- [ ] **Step 1: Scrivere test**

`test/test_audit_cancel_fields.py`:

```python
"""Verifica che _write_gemini_audit accetti e persista i campi cancel_*."""
from unittest.mock import patch

import generation_engine


def _make_job(cancel_meta=None):
    j = {
        "payment": {"token": "X", "total_eur": 2.00, "method": "paypal"},
        "gemini_actual": {"google_cost_eur": 0.30, "chars": 1000,
                          "input_tokens": 100, "output_tokens": 200,
                          "audio_seconds": 30.0},
        "rate": "+0%",
    }
    if cancel_meta is not None:
        j["cancel_meta"] = cancel_meta
    return j


def test_audit_includes_cancel_fields_when_present():
    job = _make_job(cancel_meta={
        "paid_eur": 2.00,
        "retained_eur": 0.71,
        "refund_eur": 1.29,
        "progress_pct": 28,
        "partial_audio_delivered": True,
    })
    captured = {}
    with patch("generation_engine.gemini_cost_audit.append_record",
               side_effect=lambda r: captured.update(r)):
        generation_engine._write_gemini_audit(
            "job1", job, "gemini:flash25:Zephyr", "it", "cancelled_partial")
    assert captured["outcome"] == "cancelled_partial"
    assert captured["cancel_paid_eur"] == 2.00
    assert captured["cancel_retained_eur"] == 0.71
    assert captured["cancel_refund_eur"] == 1.29
    assert captured["cancel_progress_pct"] == 28
    assert captured["cancel_partial_audio_delivered"] is True


def test_audit_no_cancel_fields_when_absent():
    job = _make_job(cancel_meta=None)
    captured = {}
    with patch("generation_engine.gemini_cost_audit.append_record",
               side_effect=lambda r: captured.update(r)):
        generation_engine._write_gemini_audit(
            "job1", job, "gemini:flash25:Zephyr", "it", "completed")
    assert captured["outcome"] == "completed"
    assert "cancel_paid_eur" not in captured
    assert "cancel_retained_eur" not in captured
```

- [ ] **Step 2: Eseguire test (devono fallire)**

```
pytest test/test_audit_cancel_fields.py -v
```

Atteso: il primo test fallisce, i campi non sono in `rec`.

- [ ] **Step 3: Estendere `_write_gemini_audit` in `generation_engine.py`**

Dopo la chiusura del dict `rec` (linea ~1677, prima di `gemini_cost_audit.append_record(rec)`):

```python
        # Cancel-specific fields (presenti solo quando job["cancel_meta"] e' popolato
        # dal branch _CancelledError). Per job non-cancel non aggiungiamo le chiavi
        # cosi' l'audit storico resta pulito.
        _cancel_meta = job.get("cancel_meta")
        if isinstance(_cancel_meta, dict):
            rec["cancel_paid_eur"] = round(float(_cancel_meta.get("paid_eur", 0) or 0), 2)
            rec["cancel_retained_eur"] = round(float(_cancel_meta.get("retained_eur", 0) or 0), 2)
            rec["cancel_refund_eur"] = round(float(_cancel_meta.get("refund_eur", 0) or 0), 2)
            rec["cancel_progress_pct"] = int(_cancel_meta.get("progress_pct", 0) or 0)
            rec["cancel_partial_audio_delivered"] = bool(
                _cancel_meta.get("partial_audio_delivered", False))
```

- [ ] **Step 4: Eseguire test**

```
pytest test/test_audit_cancel_fields.py -v
```

Atteso: 2 PASS.

- [ ] **Step 5: Verificare regressione**

```
pytest test/test_generation_writes_audit.py test/test_gemini_cost_audit.py -v
```

Atteso: tutti PASS.

- [ ] **Step 6: Commit**

```
git add generation_engine.py test/test_audit_cancel_fields.py
git commit -m "feat(cancel): extend _write_gemini_audit with cancel_* fields"
```

---

## Task 5: Aggiungere outcome `cancelled_partial` al pannello admin

**Files:**
- Modify: `audiobook_app.py:3221, 3457, 3466`

- [ ] **Step 1: Leggere `audiobook_app.py` linee 3200-3500**

```
Read audiobook_app.py offset=3200 limit=300
```

Identificare select dei filtri audit, array outcome consentiti, mapping badge.

- [ ] **Step 2: Aggiungere `<option value="cancelled_partial">` nella select**

Dopo `<option value="cancelled_refunded">Annullato (rimborsato)</option>` a linea 3221, aggiungere:

```html
<option value="cancelled_partial">Annullato (parziale)</option>
```

- [ ] **Step 3: Aggiungere `cancelled_partial` all'array outcome (linea ~3457)**

Trovare l'array literal Python che contiene `"cancelled_refunded"` e aggiungere `"cancelled_partial"` adiacente.

- [ ] **Step 4: Aggiungere il mapping badge (linea ~3466)**

```python
"cancelled_partial":           ["badge-muted","Annullato (parz.)"],
```

(Riga dopo `"cancelled_refunded": [...]`.)

- [ ] **Step 5: Verifica sintassi e visiva**

```
python -m py_compile audiobook_app.py
python audiobook_app.py
```

Aprire `http://localhost:5601/logs` con `ABM_ADMIN_TOKEN` settato. Verificare la nuova voce nella select. Stop server.

- [ ] **Step 6: Commit**

```
git add audiobook_app.py
git commit -m "feat(cancel): add cancelled_partial outcome to admin audit panel"
```

---

## Task 6: Gate `/api/cancel/<job_id>` con `ABM_GEMINI_CANCEL_LOCK_PCT` (TDD)

**Files:**
- Modify: `audiobook_app.py:5680-5697`
- Test: `test/test_cancel_endpoint_lock.py`

- [ ] **Step 1: Scrivere test**

`test/test_cancel_endpoint_lock.py`:

```python
"""Test del gate ABM_GEMINI_CANCEL_LOCK_PCT su /api/cancel/<job_id>."""
from unittest.mock import patch

import pytest

import audiobook_app


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


def _seed_job(job_id, voice, progress_current, progress_total):
    audiobook_app.jobs[job_id] = {
        "voice": voice,
        "progress_current": progress_current,
        "progress_total": progress_total,
        "client_id": "c1",
        "client_ip": "127.0.0.1",
    }


def test_cancel_gemini_below_threshold_allowed(client):
    _seed_job("J1", "gemini:flash25:Zephyr", 30, 100)
    with patch("audiobook_app._check_job_owner",
               return_value=(audiobook_app.jobs["J1"], None, None)):
        r = client.post("/api/cancel/J1")
    assert r.status_code == 200
    assert audiobook_app.jobs["J1"].get("cancelled") is True
    del audiobook_app.jobs["J1"]


def test_cancel_gemini_above_threshold_blocked(client, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_CANCEL_LOCK_PCT", "70")
    _seed_job("J2", "gemini:flash25:Zephyr", 80, 100)
    with patch("audiobook_app._check_job_owner",
               return_value=(audiobook_app.jobs["J2"], None, None)):
        r = client.post("/api/cancel/J2")
    assert r.status_code == 409
    body = r.get_json()
    assert body["error"] == "cancel_locked_progress"
    assert body["progress_pct"] == 80
    assert body["lock_pct"] == 70
    assert audiobook_app.jobs["J2"].get("cancelled") is not True
    del audiobook_app.jobs["J2"]


def test_cancel_non_gemini_above_threshold_allowed(client, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_CANCEL_LOCK_PCT", "70")
    _seed_job("J3", "it-IT-DiegoNeural", 95, 100)
    with patch("audiobook_app._check_job_owner",
               return_value=(audiobook_app.jobs["J3"], None, None)):
        r = client.post("/api/cancel/J3")
    assert r.status_code == 200
    assert audiobook_app.jobs["J3"].get("cancelled") is True
    del audiobook_app.jobs["J3"]


def test_cancel_lock_disabled_by_env_100(client, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_CANCEL_LOCK_PCT", "100")
    _seed_job("J4", "gemini:flash25:Zephyr", 99, 100)
    with patch("audiobook_app._check_job_owner",
               return_value=(audiobook_app.jobs["J4"], None, None)):
        r = client.post("/api/cancel/J4")
    assert r.status_code == 200
    del audiobook_app.jobs["J4"]


def test_cancel_lock_disabled_by_env_0(client, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_CANCEL_LOCK_PCT", "0")
    _seed_job("J5", "gemini:flash25:Zephyr", 99, 100)
    with patch("audiobook_app._check_job_owner",
               return_value=(audiobook_app.jobs["J5"], None, None)):
        r = client.post("/api/cancel/J5")
    assert r.status_code == 200
    del audiobook_app.jobs["J5"]
```

- [ ] **Step 2: Eseguire test (devono fallire)**

```
pytest test/test_cancel_endpoint_lock.py -v
```

Atteso: `test_cancel_gemini_above_threshold_blocked` fallisce con 200 anziche' 409.

- [ ] **Step 3: Modificare endpoint in `audiobook_app.py:5680`**

Sostituire il blocco con:

```python
@app.route("/api/cancel/<job_id>", methods=["POST"])
def api_cancel(job_id):
    """Cancella un job in corso.

    Per voci Gemini, il cancel volontario e' bloccato oltre la soglia
    ABM_GEMINI_CANCEL_LOCK_PCT (default 70). Vedi
    docs/superpowers/specs/2026-05-25-cancel-gemini-floor-design.md.
    """
    _job, _err, _sc = _check_job_owner(job_id)
    if _err is not None:
        if _sc == 404:
            return jsonify({"status": "not_found"}), 404
        return _err, _sc
    with _jobs_lock:
        job = jobs[job_id]
        voice = job.get("voice", "") or job.get("opt_voice", "") or ""
        is_gemini = voice.startswith("gemini:")
        if is_gemini:
            try:
                lock_pct = int(os.environ.get("ABM_GEMINI_CANCEL_LOCK_PCT", "70"))
            except (TypeError, ValueError):
                lock_pct = 70
            if 0 < lock_pct < 100:
                from generation_engine import _progress_pct
                pct = _progress_pct(job)
                if pct > lock_pct:
                    return jsonify({
                        "error": "cancel_locked_progress",
                        "progress_pct": pct,
                        "lock_pct": lock_pct,
                    }), 409
        force = request.args.get("force") == "1"
        if job.get("email_registered") and not force:
            print(f"[{job_id}] Cancel ignored  -  email registered for background processing")
            return jsonify({"status": "ignored_email_registered"})
        job["cancelled"] = True
        job["gen_epoch"] = job.get("gen_epoch", 0) + 1
        job["status"] = "analyzed"
    return jsonify({"status": "cancelling"})
```

- [ ] **Step 4: Eseguire test**

```
pytest test/test_cancel_endpoint_lock.py -v
```

Atteso: 5 PASS.

- [ ] **Step 5: Commit**

```
git add audiobook_app.py test/test_cancel_endpoint_lock.py
git commit -m "feat(cancel): add ABM_GEMINI_CANCEL_LOCK_PCT gate to /api/cancel"
```

---

## Task 7: Branch `_CancelledError` con encoding parziale + refund con floor

**Files:**
- Modify: `generation_engine.py:2658-2685` (branch `_CancelledError`)

**Importante**: questo task NON ha test unitari diretti (richiederebbe mock estensivo della pipeline FFmpeg). I test si applicano alle componenti (Task 1-6) e a uno smoke manuale (Task 14). Per ridurre rischio: la ristrutturazione mantiene gli stessi side-effect dell'attuale per il path "no audio yet" (E1) aggiungendo solo il path "audio iniziato".

- [ ] **Step 1: Leggere il branch attuale**

```
Read generation_engine.py offset=2620 limit=80
```

Identificare:
- Variabili in scope: `work_dir`, `voice`, `info`, `use_gemini`, `output_dir`, `job_id`, `job`, `my_epoch`.

- [ ] **Step 2: Identificare la pipeline PCM -> MP3 usata nel branch success**

```
Grep pattern: "pcm_concat|to_mp3|pcm_to_mp3|ffmpeg" path=generation_engine.py
```

Identificare la sequenza usata post-success. Annotare:
- Nome funzione concat (probabilmente in `audio_utils`).
- Nome funzione MP3 encode.
- Signature: input list o singolo PCM, output path, sample rate, channels.
- Pattern di creazione download token (cercare `_create_download_token`, `_tokens`, `_save_tokens`).

- [ ] **Step 3: Sostituire il branch `_CancelledError`**

Pseudo-template (sostituire i NOME_FUNZIONE_X con quelli reali identificati al Step 2):

```python
    except _CancelledError:
        still_current = job.get("gen_epoch", 0) == my_epoch

        partial_audio_delivered = False
        partial_download_url = None
        cancel_meta = None

        if still_current and use_gemini:
            try:
                actual = job.get("gemini_actual") or {}
                google_cost = float(actual.get("google_cost_eur", 0.0) or 0.0)
                payment_meta = job.get("payment") or {}
                paid = float(payment_meta.get("total_eur", 0) or 0)
                method = payment_meta.get("method", "")

                from cancel_policy import compute_cancel_retention
                cr = compute_cancel_retention(google_cost, method, paid)
                retained = cr["retained_eur"]
                refund = cr["refund_eur"]

                # Encoding MP3 parziale (best-effort)
                try:
                    pcm_files = []
                    if work_dir.exists():
                        pcm_files = sorted(work_dir.glob("*.pcm"))
                        pcm_files = [p for p in pcm_files if p.stat().st_size > 0]
                    if pcm_files:
                        partial_mp3 = output_dir / f"{job_id}_partial.mp3"
                        # NOME_FUNZIONE_CONCAT e NOME_FUNZIONE_MP3 ENCODE: usare quelli
                        # identificati al Step 2. Esempio plausibile:
                        partial_pcm = work_dir / "_partial_concat.pcm"
                        audio_utils.pcm_concat(pcm_files, partial_pcm,
                                               inter_gap_ms=gemini_tts.inter_chunk_gap_ms())
                        audio_utils.pcm_to_mp3(partial_pcm, partial_mp3,
                                               sample_rate=24000, channels=1)
                        if partial_mp3.exists() and partial_mp3.stat().st_size > 0:
                            partial_audio_delivered = True
                            # Creazione token download (riusa flow esistente)
                            partial_token = _create_partial_download_token(
                                job_id, partial_mp3, is_gemini=True)
                            partial_download_url = f"/dl/{partial_token}/download"
                            job["partial_download_url"] = partial_download_url
                except Exception as enc_err:
                    print(f"[{job_id}] Cancel partial encoding failed (non-fatal): {enc_err}")

                progress_pct = _progress_pct(job)
                cancel_meta = {
                    "paid_eur": paid,
                    "retained_eur": retained,
                    "refund_eur": refund,
                    "progress_pct": progress_pct,
                    "partial_audio_delivered": partial_audio_delivered,
                }
                job["cancel_meta"] = cancel_meta

                outcome = "cancelled_partial" if retained > 0 else "cancelled_refunded"
                _write_gemini_audit(job_id, job, voice,
                                    getattr(info, "language", None) or "", outcome)

                refund_result = _refund_gemini_payment(
                    job_id, job, "cancelled", retained_eur=retained)

                # Email cancel parziale
                if (refund_result and refund_result.get("email")
                        and partial_audio_delivered):
                    try:
                        email_service._send_gemini_cancelled_partial_email(
                            email=refund_result["email"],
                            paid_eur=paid,
                            retained_eur=retained,
                            refund_eur=refund,
                            voucher_code=refund_result.get("voucher_code"),
                            book_title=(getattr(info, "title", "") or
                                        job.get("original_filename", "")),
                            download_url=partial_download_url,
                            lang=job.get("browser_lang", "it"),
                        )
                    except Exception as e:
                        print(f"[{job_id}] cancel partial email failed: {e}")
            except Exception as cancel_err:
                # Fallback al comportamento legacy
                print(f"[{job_id}] Cancel partial flow error (fallback to legacy): {cancel_err}")
                _write_gemini_audit(job_id, job, voice,
                                    getattr(info, "language", None) or "", "cancelled_refunded")
                _refund_gemini_payment(job_id, job, "cancelled", retained_eur=0.0)
        elif use_gemini and not still_current:
            print(f"[{job_id}] Gemini cancel STALE - no refund/audit")

        if use_google:
            _google_tts_refund_unused(job_id, job)

        if still_current:
            try:
                if work_dir.exists():
                    shutil.rmtree(str(work_dir), ignore_errors=True)
            except Exception:
                pass
            _set_job_status(job, "analyzed")
            job["progress_message"] = "Cancelled"

        print(f"[{job_id}] Generation cancelled, resources freed"
              f"{' (stale)' if not still_current else ''}.")
        _log_activity(job_id, job.get("original_filename", ""), "CANCEL",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      job.get("voice", ""), job.get("browser_lang", ""))
```

**IMPORTANTE per questo step:**
- Sostituire `audio_utils.pcm_concat` / `audio_utils.pcm_to_mp3` / `_create_partial_download_token` con i nomi reali identificati al Step 2. Se la pipeline esistente concatena+encoda in un unico helper, usarlo. Se non esiste `_create_partial_download_token`, riusare la funzione esistente per creare token download (cercare `_tokens.setdefault` o `_create_download_token`).
- L'import di `compute_cancel_retention` puo' essere top-level per evitare lazy import.
- Aggiungere `from cancel_policy import compute_cancel_retention` in cima a `generation_engine.py` insieme agli altri import.

- [ ] **Step 4: Verifica sintattica**

```
python -m py_compile generation_engine.py
```

Atteso: nessun output.

- [ ] **Step 5: Suite test completa**

```
pytest test/ -v --tb=short -x
```

Atteso: tutti PASS. Se rotto: fixare prima di committare.

- [ ] **Step 6: Commit**

```
git add generation_engine.py
git commit -m "feat(cancel): restructure _CancelledError branch with floor + partial MP3"
```

---

## Task 8: Email `_send_gemini_cancelled_partial_email`

**Files:**
- Modify: `email_service.py`
- Test: `test/test_email_cancel_partial.py`

- [ ] **Step 1: Leggere pattern degli altri template Gemini**

```
Grep pattern: "_send_gemini" path=email_service.py output_mode=content -n=true
```

Identificare un template Gemini esistente (es. `_send_gemini_failed_refund_email`). Annotare:
- Signature
- Modo di costruire HTML/testo
- Helper SMTP usato (`_smtp_send`, `send_mail`, etc.)
- Pattern i18n (dict per lingua inline o helper)

- [ ] **Step 2: Scrivere test (adattare al pattern reale)**

`test/test_email_cancel_partial.py`:

```python
"""Verifica che _send_gemini_cancelled_partial_email sia invocabile e produca
un payload coerente. Non testa l'effettivo invio SMTP (mock).

Adattare il nome del wrapper SMTP al pattern reale di email_service.py.
"""
from unittest.mock import patch

import email_service


def test_send_cancel_partial_email_voucher():
    # Sostituire "_smtp_send" col nome reale identificato al Task 8 step 1
    with patch.object(email_service, "_smtp_send", create=True) as mock_send:
        email_service._send_gemini_cancelled_partial_email(
            email="user@example.com",
            paid_eur=2.00,
            retained_eur=0.71,
            refund_eur=1.29,
            voucher_code=None,
            book_title="Il mio libro",
            download_url="https://example.com/dl/abc/download",
            lang="it",
        )
        assert mock_send.called


def test_send_cancel_partial_email_paypal_includes_voucher_code():
    with patch.object(email_service, "_smtp_send", create=True) as mock_send:
        email_service._send_gemini_cancelled_partial_email(
            email="user@example.com",
            paid_eur=2.00,
            retained_eur=0.71,
            refund_eur=1.29,
            voucher_code="REF-XYZ123",
            book_title="Il mio libro",
            download_url="https://example.com/dl/abc/download",
            lang="en",
        )
        assert mock_send.called
        call_str = str(mock_send.call_args)
        assert "REF-XYZ123" in call_str
```

NOTE: la patch di `_smtp_send` potrebbe richiedere il nome reale del wrapper. Adattare.

- [ ] **Step 3: Implementare `_send_gemini_cancelled_partial_email`**

Pattern (adattare al codebase reale):

```python
def _send_gemini_cancelled_partial_email(email, paid_eur, retained_eur, refund_eur,
                                          voucher_code, book_title, download_url,
                                          lang="it"):
    """Notifica utente dopo cancel volontario di un job Gemini.

    Include link download MP3 parziale, riepilogo finanziario, codice voucher
    se metodo PayPal.
    """
    SUBJECTS = {
        "it": "La tua generazione audio e' stata annullata",
        "en": "Your audio generation was cancelled",
        "fr": "Votre generation audio a ete annulee",
        "es": "Tu generacion de audio fue cancelada",
        "de": "Deine Audio-Generierung wurde abgebrochen",
        "zh": "Your audio generation was cancelled",
        "hi": "Aapka audio generation rad kar diya gaya",
    }
    subject = SUBJECTS.get(lang, SUBJECTS["it"])

    # Mini i18n inline (pattern usato negli altri template del modulo).
    L = _CANCEL_PARTIAL_LABELS.get(lang, _CANCEL_PARTIAL_LABELS["it"])

    body_html = (
        f"<p>{L['intro'].format(book=book_title)}</p>"
        f"<p><a href=\"{download_url}\">{L['download_btn']}</a></p>"
        f"<p>{L['retention_warning']}</p>"
        f"<h3>{L['summary_title']}</h3>"
        f"<ul>"
        f"<li>{L['paid_label']}: {paid_eur:.2f}&euro;</li>"
        f"<li>{L['retained_label']}: {retained_eur:.2f}&euro;</li>"
        f"<li>{L['refund_label']}: {refund_eur:.2f}&euro;</li>"
    )
    if voucher_code:
        body_html += f"<li>{L['voucher_code_label']}: <code>{voucher_code}</code></li>"
    else:
        body_html += f"<li>{L['voucher_reaccredited']}</li>"
    body_html += "</ul>"

    # Sostituire _smtp_send con il nome reale identificato al Step 1.
    _smtp_send(to=email, subject=subject, body_html=body_html)
```

Aggiungere `_CANCEL_PARTIAL_LABELS = {...}` come modulo-level dict con chiavi per le 7 lingue. Pattern minimo:

```python
_CANCEL_PARTIAL_LABELS = {
    "it": {
        "intro": "Hai annullato la generazione di \"{book}\".",
        "download_btn": "Scarica audio parziale",
        "retention_warning": "Il file sara' disponibile per 48 ore.",
        "summary_title": "Riepilogo",
        "paid_label": "Importo pagato",
        "retained_label": "Trattenuto per costi gia' sostenuti",
        "refund_label": "Rimborso",
        "voucher_code_label": "Codice voucher",
        "voucher_reaccredited": "L'importo e' stato riaccreditato sul voucher originale.",
    },
    "en": {
        "intro": "You cancelled the generation of \"{book}\".",
        "download_btn": "Download partial audio",
        "retention_warning": "The file will be available for 48 hours.",
        "summary_title": "Summary",
        "paid_label": "Amount paid",
        "retained_label": "Retained for costs already incurred",
        "refund_label": "Refund",
        "voucher_code_label": "Voucher code",
        "voucher_reaccredited": "The amount was credited back to the original voucher.",
    },
    # Aggiungere fr, es, de, zh, hi seguendo lo stesso schema; usare le
    # traduzioni gia' presenti in i18n/*.json per coerenza terminologica.
}
```

- [ ] **Step 4: Verifica sintattica e test**

```
python -m py_compile email_service.py
pytest test/test_email_cancel_partial.py -v
```

Atteso: PASS.

- [ ] **Step 5: Commit**

```
git add email_service.py test/test_email_cancel_partial.py
git commit -m "feat(cancel): add cancelled-partial email template (7 langs)"
```

---

## Task 9: i18n keys per modal cancel e tooltip lock

**Files:**
- Modify: `templates/_fragments/i18n_data.js`
- Modify: `i18n/it.json`, `en.json`, `fr.json`, `es.json`, `de.json`, `zh.json`, `hi.json`

- [ ] **Step 1: Leggere `templates/_fragments/i18n_data.js`**

```
Read templates/_fragments/i18n_data.js limit=100
```

Identificare la sintassi esatta delle entry esistenti.

- [ ] **Step 2: Aggiungere le chiavi i18n**

Chiavi (in `i18n_data.js` e in ognuno dei 7 file `.json`):

| Chiave | IT | EN |
|--------|----|----|
| `cancel_confirm_title` | Annullare la generazione? | Cancel generation? |
| `cancel_confirm_msg` | Annullando ora perderai una parte dell'importo pagato proporzionale all'audio gia' generato. L'audio sintetizzato finora ti sara' comunque consegnato. Vuoi continuare? | If you cancel now, part of the amount paid will be retained to cover the audio already generated. The synthesized audio will still be delivered to you. Continue? |
| `cancel_confirm_keep` | Mantieni il job | Keep the job |
| `cancel_confirm_proceed` | Annulla e ricevi l'audio parziale | Cancel and get partial audio |
| `cancel_locked_progress` | Il job ha superato il {pct}%, non e' piu' possibile annullarlo. L'audio sara' consegnato al completamento. | The job has passed {pct}% and can no longer be cancelled. The audio will be delivered when complete. |
| `cancel_partial_paid_label` | Importo pagato | Amount paid |
| `cancel_partial_retained_label` | Trattenuto per costi gia' sostenuti | Retained for costs already incurred |
| `cancel_partial_refund_label` | Rimborso | Refund |
| `cancel_partial_download_label` | Scarica audio parziale | Download partial audio |
| `cancel_partial_voucher_code_label` | Codice voucher | Voucher code |
| `cancel_partial_audio_ready` | Il tuo audio parziale e' pronto per il download. | Your partial audio is ready for download. |

Traduzioni FR/ES/DE/ZH/HI: seguire lo stile delle altre chiavi gia' presenti in `i18n/`; in dubbio, chiedere all'utente prima del commit (in particolare termini "voucher"/"rimborso"/"trattenuto" possono avere convenzioni interne).

- [ ] **Step 3: Eseguire test di completezza i18n**

```
pytest test/test_i18n_completeness.py -v
```

Atteso: PASS. Se fallisce per chiavi mancanti in una lingua, completare prima del commit.

- [ ] **Step 4: Commit**

```
git add templates/_fragments/i18n_data.js i18n/
git commit -m "i18n(cancel): add keys for cancel modal + lock tooltip + partial summary"
```

---

## Task 10: Modal di conferma cancel (Gemini-only)

**Files:**
- Modify: `static/js/app.js`

- [ ] **Step 1: Trovare il listener attuale del bottone "Annulla"**

```
Grep pattern: "api/cancel|cancelBtn|btnCancel|onCancel" path=static/js/app.js
```

Identificare la funzione che chiama `POST /api/cancel/<job_id>`. Annotare:
- Nome del bottone/selector.
- Nome del helper SHowModal/Toast (potrebbero essere custom es. `showConfirm`, `Modal.open`, ecc.).
- Helper i18n usato (probabilmente `t(key)` o `i18n.t(key)`).

- [ ] **Step 2: Avvolgere la chiamata in `confirmCancelGemini`**

Modifica il listener esistente. Pattern:

```javascript
function onCancelClick(jobId, job) {
    const voice = (job && (job.voice || job.opt_voice)) || "";
    if (voice.indexOf("gemini:") === 0) {
        confirmCancelGeminiModal(jobId);
        return;
    }
    doCancel(jobId);
}

function confirmCancelGeminiModal(jobId) {
    showModal({
        title: t("cancel_confirm_title"),
        body: t("cancel_confirm_msg"),
        buttons: [
            { label: t("cancel_confirm_keep"), action: "dismiss", primary: false },
            { label: t("cancel_confirm_proceed"),
              action: function() { doCancel(jobId); },
              primary: true, danger: true },
        ],
    });
}

function doCancel(jobId) {
    fetch("/api/cancel/" + jobId, { method: "POST" })
        .then(function(r) {
            if (r.status === 409) {
                return r.json().then(function(body) {
                    var msg = t("cancel_locked_progress")
                        .replace("{pct}", body.progress_pct);
                    showToast(msg);
                });
            }
            return r.json();
        })
        .catch(function(err) { console.error("cancel error", err); });
}
```

NOTE: `showModal`/`showToast`/`t` vanno verificati. Se l'app non ha un sistema modal generico, riutilizzare il pattern dei modal esistenti (es. `geminiPayModal`, `geminiOverloadModal` — vedere markup nel template).

- [ ] **Step 3: Smoke test manuale dev**

```
python audiobook_app.py
```

1. Caricare libro, scegliere voce Premium (Gemini).
2. Avviare generazione.
3. Cliccare "Annulla" sotto 70%: appare modal di conferma.
4. "Mantieni il job": modal si chiude, job prosegue.
5. "Annulla e ricevi audio parziale": cancel POST inviata.
6. Caricare libro Standard (Edge): "Annulla" -> nessun modal, cancel diretto.

Stop server.

- [ ] **Step 4: Commit**

```
git add static/js/app.js
git commit -m "feat(cancel): show confirmation modal on Gemini cancel (text-only U1)"
```

---

## Task 11: Disable bottone cancel oltre 70% con tooltip

**Files:**
- Modify: `static/js/app.js`
- Modify: `audiobook_app.py` (espose env al frontend)

- [ ] **Step 1: Identificare il callback SSE di progress**

```
Grep pattern: "EventSource|api/progress|onmessage" path=static/js/app.js
```

Identificare il callback che processa il payload progress.

- [ ] **Step 2: Aggiungere logica disable**

Nel callback progress, dopo l'aggiornamento progress bar:

```javascript
function updateCancelButtonState(job, payload) {
    var btn = document.querySelector("#btnCancel"); // verificare selector reale
    if (!btn) return;
    var voice = (job.voice || job.opt_voice || "");
    if (voice.indexOf("gemini:") !== 0) {
        btn.disabled = false;
        btn.removeAttribute("title");
        return;
    }
    var lockPct = window.ABM_GEMINI_CANCEL_LOCK_PCT || 70;
    var total = payload.progress_total || 0;
    var current = payload.progress_current || 0;
    var pct = total > 0 ? Math.round(current / total * 100) : 0;
    if (lockPct > 0 && lockPct < 100 && pct > lockPct) {
        btn.disabled = true;
        btn.title = t("cancel_locked_progress").replace("{pct}", pct);
    } else {
        btn.disabled = false;
        btn.removeAttribute("title");
    }
}
```

Invocare `updateCancelButtonState(job, payload)` nel callback SSE.

- [ ] **Step 3: Esporre `ABM_GEMINI_CANCEL_LOCK_PCT` al frontend**

Cercare in `audiobook_app.py` come vengono settati altri `window.ABM_*` (es. `ABM_MAX_TEXT_CHARS`):

```
Grep pattern: "window.ABM_|ABM_MAX_TEXT_CHARS" path=audiobook_app.py
```

Aggiungere `ABM_GEMINI_CANCEL_LOCK_PCT` al dict/template renderer:

```python
"ABM_GEMINI_CANCEL_LOCK_PCT": int(os.environ.get("ABM_GEMINI_CANCEL_LOCK_PCT", "70")),
```

Se la convenzione e' inline `<script>` nel template index, aggiungere la riga in quel blocco. Fallback nel JS: `window.ABM_GEMINI_CANCEL_LOCK_PCT || 70`.

- [ ] **Step 4: Smoke test manuale**

```
python audiobook_app.py
```

1. Job Gemini breve.
2. Osservare bottone Cancel: a >70% diventa disabled, tooltip mostrato.
3. (Opzionale: DevTools console forzare `progress_current` e ricontrollare).

- [ ] **Step 5: Commit**

```
git add static/js/app.js audiobook_app.py
git commit -m "feat(cancel): disable cancel button + tooltip over ABM_GEMINI_CANCEL_LOCK_PCT"
```

---

## Task 12: Rendering link MP3 parziale + riepilogo refund

**Files:**
- Modify: `static/js/app.js`
- Modify: `audiobook_app.py` (propagare campi nel payload SSE)
- Modify: template (aggiungere container `#cancelSummaryBox`)

- [ ] **Step 1: Propagare campi nel payload SSE**

In `audiobook_app.py`, cercare la funzione che costruisce il payload SSE per `/api/progress/<job_id>`:

```
Grep pattern: "api/progress|sse_progress|progress_payload" path=audiobook_app.py
```

Aggiungere alla costruzione del payload, quando `status == "cancelled"`:

```python
if payload.get("status") == "cancelled":
    payload["partial_download_url"] = job.get("partial_download_url")
    payload["cancel_meta"] = job.get("cancel_meta")
    payload["refund_voucher_code"] = job.get("refund_voucher_code")
```

- [ ] **Step 2: Aggiungere container nel template**

In `templates/index.html` (o frammento panel3 dove vivono i risultati del job), aggiungere prima del footer del panel:

```html
<div id="cancelSummaryBox" class="cancel-summary" style="display:none">
    <h3 id="cancelSummaryTitle"></h3>
    <a id="cancelSummaryDownload" class="btn btn-primary" href="#" style="display:none"></a>
    <ul id="cancelSummaryList"></ul>
</div>
```

- [ ] **Step 3: Aggiungere rendering JS safe-DOM**

In `static/js/app.js`:

```javascript
function renderCancelPartialSummary(payload) {
    var meta = payload.cancel_meta || {};
    var url = payload.partial_download_url || "";
    var box = document.querySelector("#cancelSummaryBox");
    var title = document.querySelector("#cancelSummaryTitle");
    var dlBtn = document.querySelector("#cancelSummaryDownload");
    var list = document.querySelector("#cancelSummaryList");
    if (!box || !title || !dlBtn || !list) return;

    title.textContent = t("cancel_partial_audio_ready");

    if (url) {
        dlBtn.textContent = t("cancel_partial_download_label");
        dlBtn.setAttribute("href", url);
        dlBtn.style.display = "";
    } else {
        dlBtn.style.display = "none";
    }

    // Pulisci lista
    while (list.firstChild) list.removeChild(list.firstChild);

    function addRow(labelKey, value) {
        var li = document.createElement("li");
        li.textContent = t(labelKey) + ": " + value;
        list.appendChild(li);
    }

    var paid = (typeof meta.paid_eur === "number") ? meta.paid_eur.toFixed(2) + "€" : "-";
    var ret = (typeof meta.retained_eur === "number") ? meta.retained_eur.toFixed(2) + "€" : "-";
    var ref = (typeof meta.refund_eur === "number") ? meta.refund_eur.toFixed(2) + "€" : "-";
    addRow("cancel_partial_paid_label", paid);
    addRow("cancel_partial_retained_label", ret);
    addRow("cancel_partial_refund_label", ref);

    if (payload.refund_voucher_code) {
        var li = document.createElement("li");
        var lbl = document.createElement("span");
        lbl.textContent = t("cancel_partial_voucher_code_label") + ": ";
        var code = document.createElement("code");
        code.textContent = payload.refund_voucher_code;
        li.appendChild(lbl);
        li.appendChild(code);
        list.appendChild(li);
    }

    box.style.display = "block";
}
```

Aggiornare il handler SSE per chiamare `renderCancelPartialSummary(payload)` quando `payload.status === "cancelled"`.

- [ ] **Step 4: Smoke test manuale**

Riprodurre cancel parziale e verificare che la SPA mostri:
- Pulsante "Scarica audio parziale" funzionante (verificare download MP3).
- Righe "Importo pagato", "Trattenuto", "Rimborso" con valori coerenti.
- Codice voucher se metodo PayPal.

- [ ] **Step 5: Commit**

```
git add static/js/app.js audiobook_app.py templates/
git commit -m "feat(cancel): render partial MP3 link + refund summary on cancel"
```

---

## Task 13: Aggiornare documentazione (Documentation Sync Rule)

**Files:**
- Modify: `md_files/PARAMETRI_CONFIGURAZIONE.md`
- Modify: `md_files/ttsgemini.md`
- Modify: `docs/superpowers/specs/2026-05-25-cancel-gemini-floor-design.md`

- [ ] **Step 1: Aggiungere env in `PARAMETRI_CONFIGURAZIONE.md`**

Trovare la sezione "Caps PREMIUM" e aggiungere:

```markdown
| `ABM_GEMINI_CANCEL_LOCK_PCT` | `70` | Percentuale di completamento oltre cui il cancel volontario Gemini e' disabilitato (server: 409 `cancel_locked_progress`; client: bottone disabled + tooltip). `0` o `100` disattiva il lock. `audiobook_app.py:5680`. |
```

- [ ] **Step 2: Aggiungere sezione "Cancel policy con floor + audio parziale" in `ttsgemini.md`**

Posizione: dopo §8.1, prima di §9. Contenuto (~50 righe):

- Principio: utente paga almeno costi non recuperabili, riceve MP3 parziale.
- Formula: `retained = min(paid, google_cost_actual + paypal_fees)`, `refund = paid - retained`.
- `google_cost_actual` da `job["gemini_actual"].google_cost_eur` (snapshot al cancel).
- PayPal fees: 3.4% + 0.34€ su importo pagato; voucher 0.
- Hard-cutoff oltre `ABM_GEMINI_CANCEL_LOCK_PCT` (default 70).
- Pipeline `_CancelledError`: snapshot floor -> encoding MP3 parziale -> audit -> refund con `retained_eur` (+ `apply_bonus=False`) -> email + download token.
- Edge cases: tabella E1-E10 (link alla spec).
- Quota/budget exhausted: invariato (refund 100%).

- [ ] **Step 3: Aggiornare §14.1 "Audit file mensile" in `ttsgemini.md`**

Aggiungere outcome:

```markdown
| `cancelled_partial` | Cancel volontario con trattenuto applicato (introdotto 2026-05). Persiste anche 5 campi `cancel_*`. |
```

E menzionare campi `cancel_paid_eur`, `cancel_retained_eur`, `cancel_refund_eur`, `cancel_progress_pct`, `cancel_partial_audio_delivered`.

- [ ] **Step 4: Aggiornare §15.2 "Modali"**

Aggiungere:

```markdown
- **`cancelConfirmModal`**: modal di conferma cancel volontario per voci Gemini. Testo statico in 7 lingue (chiavi `cancel_confirm_*`). Mostrato solo se progress <= `ABM_GEMINI_CANCEL_LOCK_PCT`.
```

- [ ] **Step 5: Correggere drift nel design doc**

In `docs/superpowers/specs/2026-05-25-cancel-gemini-floor-design.md`:
- Sostituire ogni occorrenza di `gemini_usage` (riferito al dict job) con `gemini_actual`.
- Sostituire `apply_refund_bonus` con `apply_bonus` (parametro reale di `payment._create_voucher`).
- Aggiungere nota in alto: "**Aggiornato 2026-05-25 in implementazione**: il dict job si chiama `gemini_actual` (non `gemini_usage`). Il parametro reale di `payment._create_voucher` e' `apply_bonus` (non `apply_refund_bonus`)."

- [ ] **Step 6: Commit**

```
git add -f md_files/PARAMETRI_CONFIGURAZIONE.md md_files/ttsgemini.md docs/superpowers/specs/2026-05-25-cancel-gemini-floor-design.md
git commit -m "docs(cancel): document floor policy, lock pct env, audit fields"
```

Note: `md_files/` e `docs/` sono gitignored — `-f` necessario.

---

## Task 14: Smoke test end-to-end manuale

**Files:** nessuno (manuale).

- [ ] **Step 1: Test cancel pre-audio voucher**

1. `python audiobook_app.py`.
2. Caricare libro, scegliere voce Premium. Voucher di test (`scripts/admin_voucher.py`).
3. Pagare con voucher, **non** cliccare "Genera" — annullare.
4. Verificare `gemini_cost_audit_YYYY-MM.jsonl`: outcome `cancelled_refunded`, refund 100%, no `cancel_partial_audio_delivered`.
5. Voucher: `remaining_eur` torna al valore pre-pagamento.

- [ ] **Step 2: Test cancel a 30% PayPal**

1. Job Gemini con PayPal sandbox.
2. Attendere ~30%, cliccare "Annulla", confermare nel modal.
3. Attendere encoding parziale + email.
4. Verificare: email arrivata con voucher code; link MP3 ascoltabile; audit `cancelled_partial` con `cancel_retained_eur`, `cancel_refund_eur` coerenti.

- [ ] **Step 3: Test lock 70%**

1. Job Gemini breve.
2. Attendere >70%.
3. UI: bottone Cancel disabled + tooltip.
4. DevTools console: `fetch('/api/cancel/<id>', {method:'POST'})` -> 409 `cancel_locked_progress`.
5. Job completa normalmente.

- [ ] **Step 4: Test cancel non-Gemini invariato**

1. Job Edge TTS.
2. Cancel sotto/sopra 70%: no modal, no lock, comportamento legacy.

- [ ] **Step 5: Suite test completa**

```
pytest test/ -v --tb=short
```

Atteso: tutti PASS.

- [ ] **Step 6: Eventuali fix di smoke**

Se ci sono fix necessari, committarli. Altrimenti niente commit.

---

## Note finali

- **Push su remote**: NON eseguire push senza esplicita conferma utente (memoria `feedback_push_confirmation.md`, regola CLAUDE.md).
- **Version bump**: prima di eventuale merge su `main`, bumpare `version.py` (minor) per cambio policy economica.
- **Open question kill-switch**: in implementazione valutare `ABM_GEMINI_CANCEL_FLOOR_DISABLED=false`. Se introdotto, gate prima di `compute_cancel_retention` nel branch `_CancelledError`. Decisione non bloccante per Fase 1.
