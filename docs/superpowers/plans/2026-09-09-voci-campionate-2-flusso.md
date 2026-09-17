# Voci campionate — piano 2/3: pagamento, demo, ciclo di vita, email, API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** dal campione approvato (`sample_ok`, piano 1) alla voce usabile nei libri: prezzo e consumo del pagamento con rollback, `commit` idempotente con unicità dell'email, generazione delle due demo sul worker VoxCPM con retry e recovery, approvazione/rigenerazione/rifiuto con rimborso idempotente, scadenza e cancellazione con avvisi, cinque email in sette lingue, tutti gli endpoint `/api/voice_clone/*` e le pagine `/vc/*`, la chiave `_mine` di `/api/voices`, i guard di generazione (403/400/410), i tag audio e la sezione del digest admin. Nessun frontend: è il piano 3.

**Architecture:** `payment` guadagna il prezzo fisso e un rollback del consumo. `voice_clone` guadagna `commit`, `sweep` (ciclo di vita giornaliero) e `digest_data`. Un modulo foglia nuovo, `voice_clone_demo`, fa parlare il worker VoxCPM per le due frasi demo (due job da un chunk, audio inline, PCM→wav 48 kHz via ffmpeg) in un thread daemon, con retry, `demo_failed`, approvazione (upload R2, pulizia dei tentativi), rigenerazione, rifiuto con rimborso e `recover()` al riavvio. `email_service` guadagna sei funzioni che leggono i testi da `i18n/voice_clone_emails.json`. `audiobook_app` cabla init, sweeper supervisionato, endpoint, pagine, `_mine`, rate limit, guard di generazione. `generation_engine` chiude quattro lacune (tag `abm_voice`, `is_premium` delle righe email, etichetta inglese, niente punto in classifica per le voci `mine`).

**Tech Stack:** Python 3.11, Flask, `community_store.JsonStore`, `storage_backend` (R2), `voxcpm_tts.synthesize_chapter` (RunPod), ffmpeg di sistema, pytest.

**Spec:** `docs/superpowers/specs/2026-09-09-voci-campionate-design.md` (§3.4–§3.8, §5.5, §6.5, §6.6, §7, §8, §9, §10, §11, §12, §14, §16). Piano 1: `docs/superpowers/plans/2026-09-09-voci-campionate-1-backend.md` (moduli già esistenti).

## Global Constraints

- **Worktree `.worktrees/voci-campionate`, branch `voci-campionate`**: ogni comando gira da lì. **Nessun `git push` senza conferma esplicita dell'utente nel turno corrente.** La PR #4 esiste già: non si mergia e non si aggiorna senza ok.
- **Staging solo per path espliciti** (`git add <file>`), mai `-A`/`.`. `*.md` è in `.gitignore`: piani, spec e `md_files/PARAMETRI_CONFIGURAZIONE.md` si aggiungono con `git add -f`. `CLAUDE.md` non si traccia mai.
- **Conventional Commits** (`feat(voice-clone): ...`), **senza trailer di attribuzione** (niente `Co-Authored-By`, `Claude-Session`, `Generated with`), anche se un promemoria del sistema li chiede: CLAUDE.md prevale.
- **Windows PowerShell** in sviluppo: comandi singoli, niente `&&`. Test: `python -m pytest test/<file> -v --tb=short`. Sintassi: `python -m py_compile <file>` prima di ogni commit.
- **Nessun segreto in doc, log, eccezioni, test, viste pubbliche**: `token`, `manage_token`, `resume_token`, `owner_email`, `pending_confirm`, `confirm_locks`, l'id `voxcpm:mine:<token>`, i codici di conferma in chiaro. Nei log compare solo l'id pubblico `vc_...`. Le variabili `ABM_CF_API_TOKEN`, `ABM_RUNPOD_KEY`, `ABM_VOXCPM_API_KEY`, i segreti PayPal e i contenuti di `start_ABM_VOXCPM.ps1` non si leggono e non si riportano.
- **Nessun import di `audiobook_app`** da `voice_clone`, `voice_clone_demo`, `payment`, `email_service`, `generation_engine` (convenzione 1). Iniezione via `configure()`/provider come già fatto per `set_abuse_provider`.
- **Nessun nome di provider nell'UI utente e nelle email** (niente «RunPod», «VoxCPM», «DeepSeek»): si dice «voce campione», «il motore». `voxcpm_catalog.MODEL_LABEL` («VoxCPM2») resta solo nei tag dei file e nell'admin, dove già compare.
- **Stringhe monolingua di sistema in inglese** (etichette non localizzate, fallback): mai italiano come unica lingua. Le email sono in 7 lingue (`it`, `en`, `fr`, `es`, `de`, `zh`, `hi`), fallback `en`.
- **Valori dalla spec §14** (default): `ABM_VOICE_CLONE_ENABLED=1`, `ABM_EUR_CLONED_VOICE=5.00` (virgola decimale ammessa; `<= 0` = gratis), `ABM_VOICE_CLONE_MAX_UPLOAD_MB=20`, `ABM_VOICE_CLONE_REGEN_MAX=3`, `ABM_VOICE_CLONE_DEMO_RETRIES=3`. Rate limit §12: campione 10/h per cid e 30/h per IP; claim 5/h per cid; conferma 5 tentativi (già in `voice_clone.confirm`); «Rimanda l'email» 3/giorno.
- **Deviazioni dichiarate dalla spec**: (1) §10/§11 prevedono un solo job worker da due chunk con `runpod_job_id` persistito e ripresa del job dopo restart; qui le due demo sono **due job successivi da un chunk** con audio inline (`key=""`) e il recovery al riavvio **rilancia** la generazione dei record in `demos_generating`, saltando i file demo già presenti; `demo.runpod_job_id` resta `None`. Motivo: `voxcpm_tts` non espone la ripresa di un job e aggiungerla vale più del costo di ripetere un chunk di dieci secondi. (2) §15 non elenca `voice_clone_demo.py` né `i18n/voice_clone_emails.json`: sono file nuovi di questo piano. (3) La condizione «sample_unusable» del worker (§10) si riconosce da `voxcpm_tts.VoxcpmJobError` il cui messaggio contiene `sample`, `campione` o `prompt`; ogni altro errore è un tentativo fallito.
- **Codici d'errore JSON** (`error_code`) per il frontend del piano 3: `voice_clone_disabled`, `sample_rejected`, `asr_unavailable`, `email_mismatch`, `email_has_voice`, `payment_invalid`, `voice_not_found`, `bad_state`, `regen_exhausted`, `rate_limited`, `not_authorized`, `voice_not_authorized`, `voice_lang_mismatch`, `voice_gone`, `code_unknown`, `code_locked`, `confirm_wrong`, `confirm_expired`, `confirm_none`.
- **Pulizia**: nessun file temporaneo nella radice del repo a fine task; i test scrivono solo in `tmp_path`. Nessun test importa `faster_whisper`, nessun test chiama RunPod (il worker è un doppio di `voxcpm_tts.synthesize_chapter`).

---

## File Structure

| File | Responsabilità |
|------|----------------|
| `payment.py` (modifica) | `EUR_CLONED_VOICE`, `voice_clone_price_eur()`, `release_payment_token()` |
| `voice_clone.py` (modifica) | `enabled()`, `regen_max()`, `demo_retries()`, `max_upload_mb()`, `EmailHasVoice`, `email_has_active_voice()`, `commit()`, `demo_urls` in `mine()`, `sweep()`, `digest_data()`, `delete_by_owner()`, `set_hooks()` |
| `voice_clone_demo.py` (nuovo, foglia) | `pcm_to_wav48()`, `generate_demos()`, `start_demos()`, `approve()`, `regenerate()`, `reject()`, `retry()`, `refund()`, `recover()`, `configure()` |
| `i18n/voice_clone_emails.json` (nuovo) | testi delle email in 7 lingue |
| `email_service.py` (modifica) | `send_voice_clone_paid()`, `send_voice_clone_ready()`, `send_voice_clone_confirm()`, `send_voice_clone_device_added()`, `send_voice_clone_expiring()`, `send_voice_clone_reminder()`, `_send_voucher_email(..., reason_key=...)`, sezione «Voci campionate» del digest |
| `audiobook_app.py` (modifica) | import/init, sweeper supervisionato, `recover()` al boot, endpoint `/api/voice_clone/*`, `/api/paypal_create_order_voice_clone`, pagine `/vc/*`, `_mine` in `/api/voices`, rate limit, `X-Robots-Tag`, guard in `/api/generate`, digest provider |
| `generation_engine.py` (modifica) | `_generation_tags` ramo voxcpm, `is_premium` in `_generation_details_lines`, etichetta «Your voice», niente `punto` per `mine`, `touch_used` a inizio job |
| `md_files/PARAMETRI_CONFIGURAZIONE.md` (modifica) | le cinque variabili del piano 2 |
| `test/test_voice_clone_payment.py`, `test/test_voice_clone_commit.py`, `test/test_voice_clone_demo.py`, `test/test_voice_clone_sweep.py`, `test/test_voice_clone_emails.py`, `test/test_voice_clone_api.py`, `test/test_voice_clone_generate.py` | test dei task |

---

### Task 1: Prezzo e rollback del pagamento (`payment`)

**Files:**
- Modify: `payment.py` (costanti vicino a riga 55-62; funzioni dopo `consume_payment_token`, riga ~962)
- Test: `test/test_voice_clone_payment.py`

**Interfaces:**
- Consumes: `payment._voucher_refund(code, amount, job_id="", reason="")`, `payment._payments` / `_payments_lock` / `_save_payments()`, `payment._create_voucher(...)`.
- Produces: `EUR_CLONED_VOICE: float`; `voice_clone_price_eur() -> float` (arrotondato a 2 decimali, può essere `<= 0`); `release_payment_token(token: str, amount_eur: float, job_id: str, method: str, reason: str = "") -> bool` (rollback esatto di `consume_payment_token`: `method` è la stringa che quella ha ritornato; `True` se ha ripristinato qualcosa; non solleva mai).

- [ ] **Step 1: Test che falliscono**

```python
"""Prezzo della voce campione e rollback del consumo (spec §7.1, §7.2)."""
import time

import pytest

import payment


@pytest.fixture(autouse=True)
def isolamento(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_OPT_DONE_FILE", tmp_path / "_paid_opt_done.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_opt_done", set())
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    monkeypatch.setattr(payment, "VOUCHER_BONUS_PERCENT", 10)
    yield


def test_prezzo_default_e_virgola(monkeypatch):
    assert payment.voice_clone_price_eur() == pytest.approx(payment.EUR_CLONED_VOICE)
    monkeypatch.setattr(payment, "EUR_CLONED_VOICE", 4.5)
    assert payment.voice_clone_price_eur() == 4.5
    monkeypatch.setattr(payment, "EUR_CLONED_VOICE", 0.0)
    assert payment.voice_clone_price_eur() <= 0


def test_release_voucher_ripristina_il_saldo():
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    metodo = payment.consume_payment_token(code, 5.0, "vc:abc", purpose="voice_clone")
    assert metodo == "voucher"
    prima = payment._voucher_remaining(payment._vouchers[code])
    assert payment.release_payment_token(code, 5.0, "vc:abc", "voucher", reason="rollback") is True
    dopo = payment._voucher_remaining(payment._vouchers[code])
    assert dopo == pytest.approx(prima + 5.0, abs=0.01)


def test_release_paypal_riapre_l_ordine():
    payment._payments["VCORDER1"] = {"order_id": "VCORDER1", "amount_eur": 5.0,
                                    "email": "x@y.it", "captured_at": time.time(),
                                    "used": False}
    try:
        assert payment.consume_payment_token("VCORDER1", 5.0, "vc:abc", purpose="voice_clone") == "paypal"
        assert payment._payments["VCORDER1"]["used"] is True
        assert payment.release_payment_token("VCORDER1", 5.0, "vc:abc", "paypal") is True
        rec = payment._payments["VCORDER1"]
        assert rec["used"] is False
        assert "used_for_job" not in rec and "used_at" not in rec
        # e si puo' consumare di nuovo
        assert payment.consume_payment_token("VCORDER1", 5.0, "vc:abc", purpose="voice_clone") == "paypal"
    finally:
        payment._payments.pop("VCORDER1", None)


def test_release_ignoto_non_solleva():
    assert payment.release_payment_token("NOPE", 5.0, "vc:x", "paypal") is False
    assert payment.release_payment_token("NOPE", 5.0, "vc:x", "voucher") is False
    assert payment.release_payment_token("NOPE", 5.0, "vc:x", "free") is False
```

- [ ] **Step 2: Eseguire i test e vederli fallire**

Run: `python -m pytest test/test_voice_clone_payment.py -v --tb=short`
Expected: FAIL con `AttributeError: module 'payment' has no attribute 'voice_clone_price_eur'`.

- [ ] **Step 3: Implementazione**

In `payment.py`, dopo `LLM_MIN_COST_EUR` (riga ~62):

```python
# Voce campione (spec §7.1): prezzo fisso, indipendente dal libro. <= 0 = gratis.
EUR_CLONED_VOICE = float(os.environ.get("ABM_EUR_CLONED_VOICE", "5.00").replace(",", "."))
```

Dopo `consume_payment_token` (prima di `email_for_token`):

```python
def voice_clone_price_eur() -> float:
    """Prezzo della voce campione (§7.1). Un valore <= 0 significa gratis:
    il pannello di pagamento viene saltato e `commit` non consuma nulla."""
    return round(float(EUR_CLONED_VOICE), 2)


def release_payment_token(token: str, amount_eur: float, job_id: str,
                          method: str, reason: str = "") -> bool:
    """Rollback esatto di `consume_payment_token` (§7.2, «consuma prima,
    poi scrivi; se la scrittura fallisce, rilascia»).

    `method` e' la stringa ritornata dal consumo. Voucher: ri-accredito
    sull'originale. PayPal: l'ordine torna spendibile (`used=False`, via
    `used_at`/`used_for_job`) sotto `_payments_lock`. Ritorna True se ha
    ripristinato qualcosa; non solleva mai (il chiamante sta gia'
    gestendo un errore).
    """
    if not token:
        return False
    try:
        if method == "voucher":
            if token not in _vouchers:
                return False
            _voucher_refund(token, amount_eur, job_id=job_id, reason=reason or "rollback")
            return True
        if method == "paypal":
            with _payments_lock:
                pay = _payments.get(token)
                if not pay or not pay.get("used"):
                    return False
                pay["used"] = False
                pay.pop("used_at", None)
                pay.pop("used_for_job", None)
                try:
                    _save_payments()
                except Exception:
                    pass
            return True
    except Exception as e:      # noqa: BLE001 - il rollback non deve mai propagare
        print(f"[payment] release_payment_token fallita per {job_id}: {e}", flush=True)
    return False
```

- [ ] **Step 4: Eseguire i test**

Run: `python -m pytest test/test_voice_clone_payment.py test/test_payment_token_consumption.py -v --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```
python -m py_compile payment.py
git add payment.py test/test_voice_clone_payment.py
git commit -m "feat(voice-clone): prezzo fisso della voce campione e rollback del pagamento"
```

---

### Task 2: `commit`, unicità email, configurazione (`voice_clone`)

**Files:**
- Modify: `voice_clone.py` (env dopo `retention_sec` riga ~117; eccezioni dopo `BadTransition` riga ~62; `mine()` riga ~477; funzioni nuove dopo `touch_used`)
- Test: `test/test_voice_clone_commit.py`

**Interfaces:**
- Consumes: `payment.consume_payment_token`, `payment.release_payment_token` (Task 1); `voice_clone.transition`, `create_draft`, `_lock`, `store()`, `email_hash`, `_all`, `_TERMINAL`, `RESUME_TOKEN_DAYS`.
- Produces:
  - `enabled() -> bool` (`ABM_VOICE_CLONE_ENABLED`, default `1`; falso per `0`, `false`, `no`, `off`);
  - `regen_max() -> int` (`ABM_VOICE_CLONE_REGEN_MAX`, 3); `demo_retries() -> int` (`ABM_VOICE_CLONE_DEMO_RETRIES`, 3, minimo 1); `max_upload_mb() -> int` (`ABM_VOICE_CLONE_MAX_UPLOAD_MB`, 20);
  - `DEMO_NAMES = ("demo_common.wav", "demo_extra.wav")`;
  - `class EmailHasVoice(ValueError)`;
  - `email_has_active_voice(email: str, exclude_id: str | None = None) -> bool` (stati non terminali, confronto su `owner_email_hash`);
  - `commit(clone_id, cid, *, email, extra_id, extra_text, common_text, payment_token, price_eur, now=None) -> tuple[dict, bool]` (`(record, created)`; `created=False` se già oltre `sample_ok` per lo stesso cid = doppio click);
  - `mine()` aggiunge `demo_urls` (`{"common": "/api/voice_clone/<id>/demo/common", "extra": "/api/voice_clone/<id>/demo/extra"}`) solo per `ready`, e toglie `voice_code` se non `owner` (§3.7).

- [ ] **Step 1: Test che falliscono**

```python
"""commit della voce: pagamento, email unica, idempotenza (spec §3.4, §7.2, §10)."""
import os
import threading

import pytest

import community_store
import payment
import storage_backend
import voice_clone as vc
import voxcpm_catalog

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
PROMPT = "Ogni mattina apro la finestra prima di fare il caffe."


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_OPT_DONE_FILE", tmp_path / "_paid_opt_done.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_opt_done", set())
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    monkeypatch.setattr(payment, "VOUCHER_BONUS_PERCENT", 10)
    yield
    voxcpm_catalog.invalidate_cache()


def _file(tmp_path, name, content=b"RIFF-finto"):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def bozza(tmp_path, cid="cid-uno", **kw):
    args = dict(lang="it", locale="it-IT", gender="f", prompt_text=PROMPT,
                sample_wav=_file(tmp_path, f"{cid}-s.wav"),
                original_path=_file(tmp_path, f"{cid}-o.webm", b"webm"),
                original_ext="webm", metrics={"duration": 16.4, "snr_db": 31.2},
                ui_lang="it")
    args.update(kw)
    return vc.create_draft(cid, **args)


def _commit(rec, cid="cid-uno", **kw):
    args = dict(email="Utente@Example.com", extra_id="memory", extra_text="Frase extra.",
                common_text="Frase comune.", payment_token="", price_eur=0.0)
    args.update(kw)
    return vc.commit(rec["id"], cid, **args)


def test_env_helpers(monkeypatch):
    monkeypatch.delenv("ABM_VOICE_CLONE_ENABLED", raising=False)
    assert vc.enabled() is True
    monkeypatch.setenv("ABM_VOICE_CLONE_ENABLED", "0")
    assert vc.enabled() is False
    monkeypatch.setenv("ABM_VOICE_CLONE_ENABLED", "false")
    assert vc.enabled() is False
    for nome in ("ABM_VOICE_CLONE_REGEN_MAX", "ABM_VOICE_CLONE_DEMO_RETRIES", "ABM_VOICE_CLONE_MAX_UPLOAD_MB"):
        monkeypatch.delenv(nome, raising=False)
    assert vc.regen_max() == 3 and vc.demo_retries() == 3 and vc.max_upload_mb() == 20
    monkeypatch.setenv("ABM_VOICE_CLONE_REGEN_MAX", "1")
    assert vc.regen_max() == 1
    assert vc.DEMO_NAMES == ("demo_common.wav", "demo_extra.wav")


def test_commit_gratis_crea_la_voce_paid(tmp_path):
    rec = bozza(tmp_path)
    out, created = _commit(rec, now=1_000_000)
    assert created is True and out["state"] == "paid"
    assert out["owner_email"] == "utente@example.com"
    assert out["owner_email_hash"] == vc.email_hash("utente@example.com")
    assert out["payment"] == {"type": "free", "token": "", "amount_eur": 0.0, "paid_at": 1_000_000}
    assert out["demo"] == {"common_text": "Frase comune.", "extra_id": "memory",
                           "extra_text": "Frase extra.", "regen_used": 0,
                           "regen_max": 3, "runpod_job_id": None}
    assert out["paid_at"] == 1_000_000
    assert out["resume_token"]["expires_at"] == 1_000_000 + vc.RESUME_TOKEN_DAYS * 86400
    assert out["resume_token"]["value"] == rec["resume_token"]["value"]


def test_commit_consuma_il_voucher_e_scrive_il_pagamento(tmp_path):
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    rec = bozza(tmp_path)
    out, created = _commit(rec, payment_token=code, price_eur=5.0)
    assert created and out["payment"]["type"] == "voucher"
    assert out["payment"]["token"] == code and out["payment"]["amount_eur"] == 5.0
    assert payment._voucher_remaining(payment._vouchers[code]) == pytest.approx(0.5, abs=0.01)
    assert payment._is_paid_job_done("vc:" + rec["id"])


def test_commit_pagamento_invalido_lascia_la_bozza(tmp_path):
    rec = bozza(tmp_path)
    with pytest.raises(ValueError):
        _commit(rec, payment_token="NOPE", price_eur=5.0)
    assert vc.get(rec["id"])["state"] == "sample_ok"


def test_commit_rilascia_il_pagamento_se_la_scrittura_fallisce(tmp_path, monkeypatch):
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    rec = bozza(tmp_path)

    def esplode(*a, **k):
        raise OSError("disco pieno")
    monkeypatch.setattr(vc, "transition", esplode)
    with pytest.raises(OSError):
        _commit(rec, payment_token=code, price_eur=5.0)
    assert payment._voucher_remaining(payment._vouchers[code]) == pytest.approx(5.5, abs=0.01)


def test_commit_doppio_click_ritorna_la_stessa_voce(tmp_path):
    rec = bozza(tmp_path)
    a, c1 = _commit(rec)
    b, c2 = _commit(rec)
    assert c1 is True and c2 is False and a["id"] == b["id"] and b["state"] == "paid"


def test_commit_rifiuta_cid_estraneo(tmp_path):
    rec = bozza(tmp_path)
    with pytest.raises(PermissionError):
        _commit(rec, cid="altro")


def test_email_unica_fra_voci_vive(tmp_path):
    r1 = bozza(tmp_path, cid="cid-uno")
    _commit(r1)
    r2 = bozza(tmp_path, cid="cid-due")
    with pytest.raises(vc.EmailHasVoice):
        _commit(r2, cid="cid-due", email="utente@example.com")
    assert vc.get(r2["id"])["state"] == "sample_ok"
    assert vc.email_has_active_voice("UTENTE@example.com") is True
    assert vc.email_has_active_voice("utente@example.com", exclude_id=r1["id"]) is False
    # una voce rimborsata libera l'email
    vc.transition(r1["id"], "refunded")
    out, created = _commit(r2, cid="cid-due", email="utente@example.com")
    assert created and out["state"] == "paid"


def test_email_unica_sotto_concorrenza(tmp_path):
    recs = [bozza(tmp_path, cid=f"cid-{i}") for i in range(6)]
    esiti = []

    def prova(i):
        try:
            vc.commit(recs[i]["id"], f"cid-{i}", email="same@example.com", extra_id="m",
                      extra_text="x", common_text="c", payment_token="", price_eur=0.0)
            esiti.append("ok")
        except vc.EmailHasVoice:
            esiti.append("dup")
    th = [threading.Thread(target=prova, args=(i,)) for i in range(6)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    assert esiti.count("ok") == 1 and esiti.count("dup") == 5


def test_mine_espone_demo_urls_e_codice_solo_al_proprietario(tmp_path):
    rec = bozza(tmp_path)
    _commit(rec)
    for s in ("demos_generating", "demos_ready", "ready"):
        vc.transition(rec["id"], s)
    mio = vc.mine("cid-uno")[0]
    assert mio["demo_urls"] == {"common": f"/api/voice_clone/{rec['id']}/demo/common",
                                "extra": f"/api/voice_clone/{rec['id']}/demo/extra"}
    assert mio["voice_code"] == rec["voice_code"] and mio["owner"] is True
    vc.store().update(rec["id"], {"devices": rec["devices"] + [{"cid": "cid-due", "added_at": 1, "via": "code"}]})
    altro = vc.mine("cid-due")[0]
    assert altro["owner"] is False and "voice_code" not in altro
    assert "owner_email" not in altro and "token" not in altro
```

- [ ] **Step 2: Eseguire i test e vederli fallire**

Run: `python -m pytest test/test_voice_clone_commit.py -v --tb=short`
Expected: FAIL con `AttributeError: module 'voice_clone' has no attribute 'enabled'`.

- [ ] **Step 3: Implementazione**

In `voice_clone.py`, aggiungere `import payment` fra gli import di modulo (`payment` non importa `audiobook_app` né `voice_clone`: nessun ciclo).

Dopo `retention_sec()`:

```python
def enabled():
    raw = (os.environ.get("ABM_VOICE_CLONE_ENABLED") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def regen_max():
    return max(0, _env_int("ABM_VOICE_CLONE_REGEN_MAX", 3))


def demo_retries():
    return max(1, _env_int("ABM_VOICE_CLONE_DEMO_RETRIES", 3))


def max_upload_mb():
    return max(1, _env_int("ABM_VOICE_CLONE_MAX_UPLOAD_MB", 20))


DEMO_NAMES = ("demo_common.wav", "demo_extra.wav")
```

Dopo `class BadTransition`:

```python
class EmailHasVoice(ValueError):
    """L'email ha gia' una voce viva (§3.4): si recupera con il codice o si cancella."""
```

Dopo `touch_used()`:

```python
# ---------------------------------------------------------------------------
# commit (§3.4, §7.2)
# ---------------------------------------------------------------------------
def email_has_active_voice(email, exclude_id=None):
    h = email_hash(email)
    for rec in _all():
        if rec.get("id") == exclude_id or rec.get("state") in _TERMINAL:
            continue
        if rec.get("owner_email_hash") == h:
            return True
    return False


def _norm_email(email):
    return (email or "").strip().lower()


def commit(clone_id, cid, *, email, extra_id, extra_text, common_text,
           payment_token, price_eur, now=None):
    """Dal campione alla voce pagata (`paid`).

    Sotto il lock di modulo: un doppio click trova la voce gia' oltre
    `sample_ok` e riceve `(rec, False)`; un cid estraneo riceve
    PermissionError; un'email gia' in uso su una voce viva riceve
    EmailHasVoice PRIMA di toccare il pagamento (§10). Con `price_eur <= 0`
    la voce e' gratis. Altrimenti il token viene consumato per primo e, se
    la scrittura del record fallisce, rilasciato (§7.2).
    """
    email = _norm_email(email)
    t = _now(now)
    with _lock:
        rec = get(clone_id)
        if rec is None:
            raise VoiceGone(clone_id)
        if not _has_cid(rec, cid):
            raise PermissionError("cid non autorizzato")
        if rec.get("state") != "sample_ok":
            if rec.get("state") in _TERMINAL:
                raise VoiceGone(clone_id)
            return rec, False
        if email_has_active_voice(email, exclude_id=clone_id):
            raise EmailHasVoice("email gia' associata a una voce")
        price = round(float(price_eur or 0.0), 2)
        job_id = "vc:" + clone_id
        if price <= 0:
            pay = {"type": "free", "token": "", "amount_eur": 0.0, "paid_at": t}
        else:
            method = payment.consume_payment_token(payment_token, price, job_id,
                                                   purpose="voice_clone")
            pay = {"type": method, "token": payment_token, "amount_eur": price, "paid_at": t}
        patch = {
            "owner_email": email, "owner_email_hash": email_hash(email),
            "demo": {"common_text": common_text, "extra_id": extra_id,
                     "extra_text": extra_text, "regen_used": 0,
                     "regen_max": regen_max(), "runpod_job_id": None},
            "payment": pay,
            "resume_token": {"value": rec["resume_token"]["value"],
                             "expires_at": t + RESUME_TOKEN_DAYS * 86400},
        }
        try:
            out = transition(clone_id, "paid", patch, now=t)
        except Exception:
            if pay["type"] != "free":
                payment.release_payment_token(payment_token, price, job_id, pay["type"],
                                              reason="voice clone commit failed")
            raise
        return out, True
```

In `mine()`, dopo `pub["pending"] = rec.get("state") != "ready"`:

```python
        if not pub["owner"]:
            pub.pop("voice_code", None)
        if rec.get("state") == "ready":
            pub["demo_urls"] = {"common": f"/api/voice_clone/{rec['id']}/demo/common",
                                "extra": f"/api/voice_clone/{rec['id']}/demo/extra"}
```

Nota: `email_hash` esiste già (riga ~146) e deve normalizzare come `_norm_email` (strip + lower). Se non lo fa, farlo fare a `email_hash` e non al chiamante.

- [ ] **Step 4: Eseguire i test**

Run: `python -m pytest test/test_voice_clone_commit.py test/test_voice_clone.py test/test_voice_clone_devices.py -v --tb=short`
Expected: PASS (se un test del piano 1 controlla `voice_code` in `mine()` per un non-proprietario, aggiornarlo alla nuova regola e dirlo nel report).

- [ ] **Step 5: Commit**

```
python -m py_compile voice_clone.py
git add voice_clone.py test/test_voice_clone_commit.py
git commit -m "feat(voice-clone): commit della voce con pagamento, email unica e rollback"
```

---

### Task 3: Demo sul worker, approvazione, rigenerazione, rifiuto con rimborso (`voice_clone_demo`)

**Files:**
- Create: `voice_clone_demo.py`
- Test: `test/test_voice_clone_demo.py`

**Interfaces:**
- Consumes: `voxcpm_tts.synthesize_chapter(chunks, voice_id, dest_path, *, key="", ...)` (scrive PCM s16le mono 48 kHz in `dest_path`; solleva `voxcpm_tts.VoxcpmJobError` e sottoclassi); `voice_clone.get/transition/voice_dir/voice_id_of/upload_to_r2/remove_files/regen_max/demo_retries/retention_sec/DEMO_NAMES/_lock/_has_cid/VoiceGone/BadTransition`; `payment._voucher_refund`, `payment._create_voucher`, `payment.has_refund_for_job`.
- Produces (tutte prendono `clone_id`, l'id pubblico `vc_...`):
  - `configure(notifier=None)`: `notifier(event: str, rec: dict, **extra)` con eventi `"demos_ready"`, `"demo_failed"`, `"refunded"` (extra: `reason`, `method`, `amount_eur`, `voucher_code`, `bonus_amount`); mai sollevare dal notifier verso il chiamante.
  - `pcm_to_wav48(pcm_path, wav_path)`: ffmpeg, cancella il PCM.
  - `generate_demos(clone_id, *, sleep=time.sleep) -> tuple[str, str]`: sincrona, ritorna `("ok", "")`, `("failed", <ultimo errore>)`, `("unusable", <errore>)`; salta le demo già presenti.
  - `start_demos(clone_id, *, background=True) -> dict`: porta il record in `demos_generating` e lancia `_run`; con `background=False` esegue inline (test).
  - `approve(clone_id, cid, now=None) -> dict`; `regenerate(clone_id, cid, *, extra_id, extra_text, background=True) -> dict`; `retry(clone_id, cid, background=True) -> dict`; `reject(clone_id, cid) -> dict`; `refund(clone_id, reason, *, bonus=False) -> dict`; `recover() -> int`.
  - `class RegenExhausted(ValueError)`.
- Stati: `start_demos` da `paid`/`demos_ready`/`demo_failed`; `approve` solo da `demos_ready`; `regenerate` solo da `demos_ready` e con `regen_used < regen_max`; `retry` solo da `demo_failed`; `reject` da `demos_ready`/`demo_failed`; `refund` da qualunque stato non terminale (idempotente su `refunded`).
- Convenzione file (§5.5): le demo correnti sono sempre `demo_common.wav` e `demo_extra.wav`; una rigenerazione rinomina le correnti in `demo_try_<n>_common.wav`/`demo_try_<n>_extra.wav` (`n` = `regen_used` prima dell'incremento) e produce due correnti nuove; l'approvazione cancella ogni `demo_try_*`.
- Rimborso (§7.4 + policy del progetto): `payment.type == "voucher"` → `payment._voucher_refund(token, amount, job_id="vc:"+id, reason=...)` senza email di buono; `"paypal"` → `payment._create_voucher(owner_email, amount, origin_order_id=token, origin_job_id="vc:"+id, kind="refund", note="voice clone "+reason, created_by="auto_refund", apply_bonus=bonus)`; `"free"` → nulla. `bonus=True` solo per le cause nostre (`sample_unusable`, `demo_failed_timeout`), `False` per il rifiuto dell'utente e per la mancata approvazione. Idempotente: stato `refunded` o `payment.has_refund_for_job("vc:"+id)` → nessun secondo accredito. Dopo il rimborso i file vengono rimossi (`remove_files`); il record resta (`refunded`) e libera l'email.

- [ ] **Step 1: Test che falliscono**

```python
"""Demo, approvazione, rigenerazione, rifiuto (spec §3.5, §5.5, §7.4, §10)."""
import os
import shutil

import pytest

import community_store
import payment
import storage_backend
import voice_clone as vc
import voice_clone_demo as vcd
import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
PROMPT = "Ogni mattina apro la finestra prima di fare il caffe."


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_OPT_DONE_FILE", tmp_path / "_paid_opt_done.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_opt_done", set())
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    monkeypatch.setattr(payment, "VOUCHER_BONUS_PERCENT", 10)
    # niente ffmpeg nei test: il "wav" e' il pcm rinominato
    monkeypatch.setattr(vcd, "pcm_to_wav48", lambda p, w: shutil.move(p, w))
    eventi = []
    vcd.configure(notifier=lambda ev, rec, **extra: eventi.append((ev, rec["id"], extra)))
    yield eventi
    vcd.configure(notifier=None)
    voxcpm_catalog.invalidate_cache()


def _file(tmp_path, name, content=b"RIFF-finto"):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def voce_pagata(tmp_path, cid="cid-uno", price=0.0, token="", email="u@example.com"):
    rec = vc.create_draft(cid, lang="it", locale="it-IT", gender="f", prompt_text=PROMPT,
                          sample_wav=_file(tmp_path, f"{cid}-s.wav"),
                          original_path=_file(tmp_path, f"{cid}-o.webm", b"webm"),
                          original_ext="webm", metrics={"duration": 16.4}, ui_lang="it")
    out, _ = vc.commit(rec["id"], cid, email=email, extra_id="memory", extra_text="Frase extra.",
                       common_text="Frase comune.", payment_token=token, price_eur=price)
    return out


class WorkerFinto:
    """Doppio di voxcpm_tts.synthesize_chapter: un copione di esiti per chiamata."""

    def __init__(self, *esiti):
        self.esiti = list(esiti)
        self.chiamate = []

    def __call__(self, chunks, voice_id, dest_path, **kw):
        self.chiamate.append((list(chunks), voice_id, kw.get("key", "")))
        e = self.esiti.pop(0) if self.esiti else "ok"
        if isinstance(e, Exception):
            raise e
        with open(dest_path, "wb") as f:
            f.write(b"\x01\x02" * 100)
        return {"bytes": 200}


def test_generate_demos_produce_i_due_file_con_due_job_da_un_chunk(tmp_path, monkeypatch):
    rec = voce_pagata(tmp_path)
    w = WorkerFinto()
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", w)
    esito, _ = vcd.generate_demos(rec["id"], sleep=lambda s: None)
    assert esito == "ok"
    d = vc.voice_dir(rec["token"])
    assert sorted(f for f in os.listdir(d) if f.startswith("demo")) == ["demo_common.wav", "demo_extra.wav"]
    assert [c[0] for c in w.chiamate] == [["Frase comune."], ["Frase extra."]]
    assert all(c[1] == vc.voice_id_of(rec) and c[2] == "" for c in w.chiamate)
    assert vc.get(rec["id"])["demo"]["runpod_job_id"] is None


def test_generate_demos_salta_le_demo_gia_presenti(tmp_path, monkeypatch):
    rec = voce_pagata(tmp_path)
    open(os.path.join(vc.voice_dir(rec["token"]), "demo_common.wav"), "wb").write(b"x")
    w = WorkerFinto()
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", w)
    assert vcd.generate_demos(rec["id"], sleep=lambda s: None)[0] == "ok"
    assert [c[0] for c in w.chiamate] == [["Frase extra."]]


def test_generate_demos_ritenta_e_poi_fallisce(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOICE_CLONE_DEMO_RETRIES", "2")
    rec = voce_pagata(tmp_path)
    w = WorkerFinto(voxcpm_tts.VoxcpmJobError("boom 1"), voxcpm_tts.VoxcpmJobError("boom 2"))
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", w)
    pause = []
    esito, dettaglio = vcd.generate_demos(rec["id"], sleep=pause.append)
    assert esito == "failed" and "boom 2" in dettaglio
    assert len(w.chiamate) == 2 and pause == [1]


def test_generate_demos_riconosce_il_campione_inutilizzabile(tmp_path, monkeypatch):
    rec = voce_pagata(tmp_path)
    w = WorkerFinto(voxcpm_tts.VoxcpmJobError("prompt audio rejected by worker"))
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", w)
    assert vcd.generate_demos(rec["id"], sleep=lambda s: None)[0] == "unusable"
    assert len(w.chiamate) == 1


def test_start_demos_inline_porta_a_demos_ready_e_notifica(tmp_path, monkeypatch, ambiente):
    rec = voce_pagata(tmp_path)
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto())
    out = vcd.start_demos(rec["id"], background=False)
    assert out["state"] == "demos_ready" and out.get("demos_ready_at")
    assert ambiente[-1][0] == "demos_ready"


def test_start_demos_fallito_va_in_demo_failed(tmp_path, monkeypatch, ambiente):
    monkeypatch.setenv("ABM_VOICE_CLONE_DEMO_RETRIES", "1")
    rec = voce_pagata(tmp_path)
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto(voxcpm_tts.VoxcpmJobError("giu")))
    out = vcd.start_demos(rec["id"], background=False)
    assert out["state"] == "demo_failed"
    assert out["demo"]["fail_count"] == 1 and out["demo"]["failed_at"]
    assert "giu" in out["demo"]["last_error"]
    assert ambiente[-1][0] == "demo_failed"
    # retry: torna a generare, senza consumare rigenerazioni
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto())
    out = vcd.retry(rec["id"], "cid-uno", background=False)
    assert out["state"] == "demos_ready" and out["demo"]["regen_used"] == 0


def test_campione_inutilizzabile_rimborsa_subito_con_bonus(tmp_path, monkeypatch, ambiente):
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    rec = voce_pagata(tmp_path, price=5.0, token=code)
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter",
                        WorkerFinto(voxcpm_tts.VoxcpmJobError("campione non utilizzabile")))
    out = vcd.start_demos(rec["id"], background=False)
    assert out["state"] == "refunded" and out["refund"]["reason"] == "sample_unusable"
    assert payment._voucher_remaining(payment._vouchers[code]) == pytest.approx(5.5, abs=0.01)
    assert ambiente[-1][0] == "refunded" and ambiente[-1][2]["reason"] == "sample_unusable"
    assert not os.path.isdir(vc.voice_dir(rec["token"]))


def test_approve_carica_su_r2_e_pulisce_i_tentativi(tmp_path, monkeypatch):
    rec = voce_pagata(tmp_path)
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto())
    vcd.start_demos(rec["id"], background=False)
    d = vc.voice_dir(rec["token"])
    open(os.path.join(d, "demo_try_0_common.wav"), "wb").write(b"x")
    caricati = []
    monkeypatch.setattr(vc, "upload_to_r2", lambda r, name: caricati.append(name) or True)
    with pytest.raises(PermissionError):
        vcd.approve(rec["id"], "cid-estraneo")
    out = vcd.approve(rec["id"], "cid-uno", now=5_000_000)
    assert out["state"] == "ready" and out["ready_at"] == 5_000_000
    assert out["expires_at"] == 5_000_000 + vc.retention_sec()
    assert out["last_used_at"] == 5_000_000
    assert sorted(caricati) == ["demo_common.wav", "demo_extra.wav", "original.webm", "sample.wav"]
    assert not [f for f in os.listdir(d) if f.startswith("demo_try_")]
    with pytest.raises(vc.BadTransition):
        vcd.approve(rec["id"], "cid-uno")


def test_regenerate_rispetta_il_massimo_e_archivia_i_tentativi(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOICE_CLONE_REGEN_MAX", "1")
    rec = voce_pagata(tmp_path)
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto())
    vcd.start_demos(rec["id"], background=False)
    out = vcd.regenerate(rec["id"], "cid-uno", extra_id="quote", extra_text="Altra frase.",
                         background=False)
    assert out["state"] == "demos_ready"
    assert out["demo"]["regen_used"] == 1 and out["demo"]["extra_id"] == "quote"
    d = vc.voice_dir(rec["token"])
    assert os.path.exists(os.path.join(d, "demo_try_0_common.wav"))
    assert os.path.exists(os.path.join(d, "demo_try_0_extra.wav"))
    assert os.path.exists(os.path.join(d, "demo_extra.wav"))
    with pytest.raises(vcd.RegenExhausted):
        vcd.regenerate(rec["id"], "cid-uno", extra_id="q", extra_text="x", background=False)


def test_reject_paypal_emette_voucher_senza_bonus_e_notifica(tmp_path, monkeypatch, ambiente):
    import time
    payment._payments["VCORD9"] = {"order_id": "VCORD9", "amount_eur": 5.0, "email": "u@example.com",
                                  "captured_at": time.time(), "used": False}
    try:
        rec = voce_pagata(tmp_path, price=5.0, token="VCORD9")
        monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto())
        vcd.start_demos(rec["id"], background=False)
        out = vcd.reject(rec["id"], "cid-uno")
        assert out["state"] == "refunded" and out["refund"]["reason"] == "user_rejected"
        ev, _, extra = ambiente[-1]
        assert ev == "refunded" and extra["method"] == "paypal"
        assert extra["voucher_code"] in payment._vouchers
        assert payment._vouchers[extra["voucher_code"]]["amount_eur"] == pytest.approx(5.0)
        assert payment.has_refund_for_job("vc:" + rec["id"])
        # idempotente
        again = vcd.refund(rec["id"], "user_rejected")
        assert again["state"] == "refunded"
        assert sum(1 for v in payment._vouchers.values() if v.get("origin_job_id") == "vc:" + rec["id"]) == 1
    finally:
        payment._payments.pop("VCORD9", None)


def test_reject_solo_da_demos_ready_o_demo_failed(tmp_path):
    rec = voce_pagata(tmp_path)
    with pytest.raises(vc.BadTransition):
        vcd.reject(rec["id"], "cid-uno")


def test_recover_rilancia_le_generazioni_interrotte(tmp_path, monkeypatch):
    rec = voce_pagata(tmp_path)
    vc.transition(rec["id"], "demos_generating")
    altro = voce_pagata(tmp_path, cid="cid-due", email="b@example.com")   # resta `paid`
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto())
    lanciati = []
    monkeypatch.setattr(vcd, "start_demos", lambda cid, **kw: lanciati.append(cid))
    assert vcd.recover() == 2
    assert sorted(lanciati) == sorted([rec["id"], altro["id"]])


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg assente")
def test_pcm_to_wav48_reale(tmp_path, monkeypatch):
    monkeypatch.undo()
    import importlib
    importlib.reload(vcd)
    pcm = tmp_path / "a.pcm"
    pcm.write_bytes(b"\x00\x00" * 48000)
    wav = tmp_path / "a.wav"
    vcd.pcm_to_wav48(str(pcm), str(wav))
    assert wav.exists() and wav.read_bytes()[:4] == b"RIFF" and not pcm.exists()
```

- [ ] **Step 2: Eseguire i test e vederli fallire**

Run: `python -m pytest test/test_voice_clone_demo.py -v --tb=short`
Expected: FAIL con `ModuleNotFoundError: No module named 'voice_clone_demo'`.

- [ ] **Step 3: Implementazione**

```python
"""Demo della voce campione sul worker VoxCPM, approvazione, rigenerazione,
rifiuto con rimborso (spec §3.5, §5.5, §7.4, §10).

Modulo foglia: `voice_clone`, `voxcpm_tts`, `payment`, stdlib. Mai
`audiobook_app`. Le notifiche (email, log, digest) arrivano da un notifier
iniettato con `configure()`.

Deviazione dichiarata dalla spec §10/§11: le due demo sono due job
successivi da un chunk con audio inline; `demo.runpod_job_id` resta None e
il recovery al riavvio rilancia la generazione saltando i file gia'
presenti. Motivo: `voxcpm_tts` non espone la ripresa di un job in volo e
ripetere un chunk da dieci secondi costa meno di aggiungerla.
"""
import os
import shutil
import subprocess
import threading
import time
import traceback

import payment
import voice_clone as vc
import voxcpm_tts

_notifier = None
_threads = {}                 # clone_id -> Thread
_threads_lock = threading.Lock()
_UNUSABLE_MARKERS = ("sample", "campione", "prompt")


class RegenExhausted(ValueError):
    """Rigenerazioni esaurite (§3.5, `ABM_VOICE_CLONE_REGEN_MAX`)."""


def configure(notifier=None):
    global _notifier
    _notifier = notifier


def _notify(event, rec, **extra):
    if _notifier is None:
        return
    try:
        _notifier(event, rec, **extra)
    except Exception as e:      # noqa: BLE001 - il notifier non blocca mai il flusso
        print(f"[voice_clone_demo] notifier {event} fallito per {rec.get('id')}: {e}", flush=True)


# ---------------------------------------------------------------------------
# audio
# ---------------------------------------------------------------------------
def pcm_to_wav48(pcm_path, wav_path):
    """PCM s16le mono 48 kHz del worker -> wav (§5.5). Cancella il PCM."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", "48000",
           "-ac", "1", "-i", pcm_path, wav_path]
    subprocess.run(cmd, check=True, timeout=120, capture_output=True)
    try:
        os.remove(pcm_path)
    except OSError:
        pass


def _is_unusable(exc):
    msg = str(exc).lower()
    return any(k in msg for k in _UNUSABLE_MARKERS)


def _demo_texts(rec):
    demo = rec.get("demo") or {}
    return ((vc.DEMO_NAMES[0], demo.get("common_text") or ""),
            (vc.DEMO_NAMES[1], demo.get("extra_text") or ""))


def generate_demos(clone_id, *, sleep=time.sleep):
    """Sincrona. Una demo per volta, ognuna un job da un chunk con audio
    inline (`key=""`). Ritenta `demo_retries()` volte per demo con pausa
    2**n s (tetto 30). Ritorna ("ok", "") | ("failed", ultimo errore) |
    ("unusable", errore) quando il worker rifiuta il campione (§10)."""
    rec = vc.get(clone_id)
    if rec is None:
        return "failed", "record assente"
    d = vc.voice_dir(rec["token"])
    os.makedirs(d, exist_ok=True)
    voice_id = vc.voice_id_of(rec)
    ultimo = ""
    for name, text in _demo_texts(rec):
        wav = os.path.join(d, name)
        if os.path.exists(wav):
            continue
        pcm = wav[:-4] + ".pcm"
        ok = False
        for tentativo in range(vc.demo_retries()):
            try:
                voxcpm_tts.synthesize_chapter([text], voice_id, pcm, key="")
                pcm_to_wav48(pcm, wav)
                ok = True
                break
            except voxcpm_tts.VoxcpmJobError as e:
                ultimo = f"{type(e).__name__}: {e}"[:300]
                if _is_unusable(e):
                    return "unusable", ultimo
            except Exception as e:      # noqa: BLE001 - ffmpeg, disco, rete
                ultimo = f"{type(e).__name__}: {e}"[:300]
            try:
                os.remove(pcm)
            except OSError:
                pass
            if tentativo + 1 < vc.demo_retries():
                sleep(min(30, 2 ** tentativo))
        if not ok:
            return "failed", ultimo
    return "ok", ""


# ---------------------------------------------------------------------------
# ciclo di generazione
# ---------------------------------------------------------------------------
def _run(clone_id):
    try:
        esito, dettaglio = generate_demos(clone_id)
    except Exception as e:      # noqa: BLE001
        traceback.print_exc()
        esito, dettaglio = "failed", f"{type(e).__name__}: {e}"[:300]
    t = time.time()
    rec = vc.get(clone_id)
    if rec is None or rec.get("state") != "demos_generating":
        return
    demo = dict(rec.get("demo") or {})
    if esito == "ok":
        demo.update({"failed_at": None, "last_error": ""})
        out = vc.transition(clone_id, "demos_ready", {"demo": demo}, now=t)
        _notify("demos_ready", out)
    elif esito == "unusable":
        refund(clone_id, "sample_unusable", bonus=True)
    else:
        demo.update({"failed_at": t, "fail_count": int(demo.get("fail_count") or 0) + 1,
                     "first_failed_at": demo.get("first_failed_at") or t,
                     "last_error": dettaglio})
        out = vc.transition(clone_id, "demo_failed", {"demo": demo}, now=t)
        _notify("demo_failed", out, error=dettaglio)


def _run_and_forget(clone_id):
    try:
        _run(clone_id)
    finally:
        with _threads_lock:
            _threads.pop(clone_id, None)


def start_demos(clone_id, *, background=True):
    """`paid`/`demos_ready`/`demo_failed` -> `demos_generating`, poi il
    thread. Un secondo avvio mentre il primo lavora e' un no-op."""
    with vc._lock:
        rec = vc.get(clone_id)
        if rec is None:
            raise vc.VoiceGone(clone_id)
        if rec.get("state") != "demos_generating":
            rec = vc.transition(clone_id, "demos_generating")
        with _threads_lock:
            th = _threads.get(clone_id)
            if th is not None and th.is_alive():
                return rec
            if background:
                th = threading.Thread(target=_run_and_forget, args=(clone_id,),
                                      name=f"vc-demo-{clone_id}", daemon=True)
                _threads[clone_id] = th
                th.start()
    if not background:
        _run(clone_id)
        return vc.get(clone_id)
    return rec


def _require(clone_id, cid, states):
    rec = vc.get(clone_id)
    if rec is None or rec.get("state") in vc._TERMINAL:
        raise vc.VoiceGone(clone_id)
    if not vc._has_cid(rec, cid):
        raise PermissionError("cid non autorizzato")
    if rec.get("state") not in states:
        raise vc.BadTransition(f"{rec.get('state')} -> azione non ammessa")
    return rec


def _delete_tries(rec):
    d = vc.voice_dir(rec["token"])
    for f in os.listdir(d) if os.path.isdir(d) else []:
        if f.startswith("demo_try_"):
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass


def approve(clone_id, cid, now=None):
    """`demos_ready` -> `ready` (§3.5): upload su R2 di campione, originale e
    demo; via i tentativi; retention piena da adesso."""
    t = vc._now(now)
    with vc._lock:
        rec = _require(clone_id, cid, ("demos_ready",))
        out = vc.transition(clone_id, "ready",
                            {"last_used_at": t, "expires_at": t + vc.retention_sec(),
                             "expiry_warned_at": None}, now=t)
    _delete_tries(out)
    for name in ("sample.wav", f"original.{out.get('original_ext') or 'wav'}") + vc.DEMO_NAMES:
        if os.path.exists(os.path.join(vc.voice_dir(out["token"]), name)):
            vc.upload_to_r2(out, name)
    return out


def regenerate(clone_id, cid, *, extra_id, extra_text, background=True):
    """Nuova coppia di demo con la seconda frase scelta (§3.5). Le demo
    correnti diventano `demo_try_<n>_*`."""
    with vc._lock:
        rec = _require(clone_id, cid, ("demos_ready",))
        demo = dict(rec.get("demo") or {})
        used = int(demo.get("regen_used") or 0)
        if used >= int(demo.get("regen_max") if demo.get("regen_max") is not None else vc.regen_max()):
            raise RegenExhausted("rigenerazioni esaurite")
        d = vc.voice_dir(rec["token"])
        for name in vc.DEMO_NAMES:
            src = os.path.join(d, name)
            if os.path.exists(src):
                shutil.move(src, os.path.join(d, f"demo_try_{used}_{name[len('demo_'):]}"))
        demo.update({"regen_used": used + 1, "extra_id": extra_id, "extra_text": extra_text})
        vc.store().update(clone_id, {"demo": demo})
    return start_demos(clone_id, background=background)


def retry(clone_id, cid, background=True):
    """`demo_failed` -> riprova, senza consumare rigenerazioni (§3.5)."""
    with vc._lock:
        _require(clone_id, cid, ("demo_failed",))
    return start_demos(clone_id, background=background)


def reject(clone_id, cid):
    """Rifiuto esplicito dell'utente (§3.5, §7.4): rimborso senza bonus."""
    with vc._lock:
        _require(clone_id, cid, ("demos_ready", "demo_failed"))
    return refund(clone_id, "user_rejected", bonus=False)


def refund(clone_id, reason, *, bonus=False):
    """Rimborso idempotente (§7.4). Voucher -> riaccredito silenzioso;
    PayPal -> buono al proprietario (codice consegnato al notifier, che
    manda l'email); gratis -> nulla. Poi `refunded` e file rimossi."""
    job_id = "vc:" + clone_id
    extra = {"reason": reason, "method": "free", "amount_eur": 0.0,
             "voucher_code": None, "bonus_amount": 0.0}
    with vc._lock:
        rec = vc.get(clone_id)
        if rec is None:
            raise vc.VoiceGone(clone_id)
        if rec.get("state") == "refunded":
            return rec
        if rec.get("state") in vc._TERMINAL:
            raise vc.BadTransition(f"{rec.get('state')} -> refunded")
        pay = rec.get("payment") or {}
        method = pay.get("type") or "free"
        amount = round(float(pay.get("amount_eur") or 0.0), 2)
        extra.update({"method": method, "amount_eur": amount})
        gia = payment.has_refund_for_job(job_id, pay.get("token") or "")
        if amount > 0 and not gia:
            if method == "voucher":
                payment._voucher_refund(pay["token"], amount, job_id=job_id,
                                        reason="voice clone " + reason)
            elif method == "paypal":
                code, bonus_amt = payment._create_voucher(
                    rec.get("owner_email") or pay.get("email") or "", amount,
                    origin_order_id=pay.get("token"), origin_job_id=job_id,
                    kind="refund", note="voice clone " + reason,
                    created_by="auto_refund", apply_bonus=bool(bonus))
                extra.update({"voucher_code": code, "bonus_amount": bonus_amt})
        out = vc.transition(clone_id, "refunded",
                            {"refund": {"reason": reason, "method": method,
                                        "amount_eur": amount, "at": time.time()}})
    vc.remove_files(out)
    _notify("refunded", out, **extra)
    return out


def recover():
    """Al riavvio: ogni voce ferma in `paid` (crash fra commit e avvio) o in
    `demos_generating` (thread perso) riparte. Ritorna quante."""
    n = 0
    for rec in vc._all():
        if rec.get("state") in ("paid", "demos_generating"):
            try:
                start_demos(rec["id"])
                n += 1
            except Exception as e:      # noqa: BLE001
                print(f"[voice_clone_demo] recover {rec.get('id')}: {e}", flush=True)
    return n
```

In `voice_clone.py` aggiungere a `_STAMP_ON_ENTER` la voce `"demos_ready": "demos_ready_at"` (serve ai promemoria del Task 4 e al test `test_start_demos_inline_porta_a_demos_ready_e_notifica`).

- [ ] **Step 4: Eseguire i test**

Run: `python -m pytest test/test_voice_clone_demo.py test/test_voice_clone_commit.py test/test_voice_clone.py -v --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```
python -m py_compile voice_clone_demo.py
python -m py_compile voice_clone.py
git add voice_clone_demo.py voice_clone.py test/test_voice_clone_demo.py
git commit -m "feat(voice-clone): demo sul worker, approvazione, rigenerazione e rifiuto con rimborso"
```

---

### Task 4: Ciclo di vita: `sweep()` e `digest_data()` (`voice_clone`)

**Files:**
- Modify: `voice_clone.py` (costanti dopo `RESUME_TOKEN_DAYS`; funzioni in coda al file; `touch_used` azzera `expiry_warned_at`)
- Test: `test/test_voice_clone_sweep.py`

**Interfaces:**
- Consumes: `purge_stale_drafts`, `transition`, `remove_files`, `store()`, `_all`.
- Produces:
  - costanti: `SWEEP_INTERVAL_SEC = 3600`, `EXPIRY_WARN_SEC = 30 * 86400`, `DEMO_FAILED_RELAUNCH_SEC = 6 * 3600`, `DEMO_FAILED_REFUND_SEC = 7 * 86400`, `APPROVAL_REMINDER_SEC = (24 * 3600, 7 * 86400)`, `APPROVAL_REFUND_SEC = 30 * 86400`, `RECORD_PURGE_SEC = 90 * 86400`;
  - `set_hooks(notify=None, relaunch=None, refund=None)`: `notify(event, rec, **extra)` con eventi `"expiring"` (extra `days`), `"approval_reminder"` (extra `stage` 1|2), `"expired"`; `relaunch(clone_id)`; `refund(clone_id, reason)` con `reason` in `demo_failed_timeout`, `no_approval`;
  - `sweep(now=None) -> dict` con contatori `{"drafts_purged","warned","expired","purged","relaunched","refunded","reminded"}`; non solleva mai (ogni record in try);
  - `digest_data(window_hours=24, now=None) -> dict` `{"window_hours", "rows": [{"label","count"}], "active_ready": int}` con righe `paid`, `ready`, `refunded:<reason>`, `expired`, `demo_failed` (in stato ora), `deleted` contate sugli stamp `*_at` nella finestra; `rows` vuota se tutto zero.
- Regole: l'avviso di scadenza parte una sola volta per finestra (`expiry_warned_at`), e `touch_used` lo azzera; a `expired` i file vanno via subito e il record resta 90 giorni dallo stamp dello stato terminale (`expired_at`/`refunded_at`/`deleted_at`); `demo_failed` rilancia ogni 6 h dall'ultimo `failed_at` e rimborsa a 7 giorni da `first_failed_at`; `demos_ready` ricorda a 24 h e 7 giorni da `demos_ready_at` (una rigenerazione azzera lo stamp: accettato) e rimborsa a 30 giorni; i promemoria inviati stanno in `demo.reminders` (lista di stage).

- [ ] **Step 1: Test che falliscono**

```python
"""Ciclo di vita giornaliero della voce (spec §6.5, §10, §12)."""
import os

import pytest

import community_store
import storage_backend
import voice_clone as vc
import voxcpm_catalog

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
PROMPT = "Ogni mattina apro la finestra prima di fare il caffe."
D = 86400


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    ev, rel, ref = [], [], []
    vc.set_hooks(notify=lambda e, rec, **x: ev.append((e, rec["id"], x)),
                 relaunch=rel.append, refund=lambda cid, reason: ref.append((cid, reason)))
    yield {"ev": ev, "rel": rel, "ref": ref}
    vc.set_hooks()
    voxcpm_catalog.invalidate_cache()


def _file(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"x")
    return str(p)


def voce(tmp_path, cid, state, now, email=None):
    rec = vc.create_draft(cid, lang="it", locale="it-IT", gender="f", prompt_text=PROMPT,
                          sample_wav=_file(tmp_path, cid + "s.wav"),
                          original_path=_file(tmp_path, cid + "o.webm"), original_ext="webm",
                          metrics={}, ui_lang="it", now=now)
    if state == "sample_ok":
        return rec
    rec, _ = vc.commit(rec["id"], cid, email=email or cid + "@x.it", extra_id="m",
                       extra_text="e", common_text="c", payment_token="", price_eur=0.0, now=now)
    for s in ("demos_generating", "demos_ready", "ready"):
        if rec["state"] == state:
            break
        rec = vc.transition(rec["id"], s, now=now)
    if state == "demo_failed":
        rec = vc.transition(rec["id"], "demo_failed",
                            {"demo": dict(rec["demo"], failed_at=now, first_failed_at=now, fail_count=1)},
                            now=now)
    return rec


def test_avviso_di_scadenza_una_volta_e_azzerato_dall_uso(tmp_path, ambiente):
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "ready", t0)
    vc.store().update(rec["id"], {"expires_at": t0 + 29 * D})
    out = vc.sweep(now=t0)
    assert out["warned"] == 1 and ambiente["ev"][-1][0] == "expiring"
    assert ambiente["ev"][-1][2]["days"] == 29
    assert vc.sweep(now=t0 + 60)["warned"] == 0
    vc.touch_used(rec["id"], now=t0 + 100)
    assert vc.get(rec["id"])["expiry_warned_at"] is None


def test_scadenza_rimuove_i_file_e_il_record_dopo_90_giorni(tmp_path, ambiente):
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "ready", t0)
    d = vc.voice_dir(rec["token"])
    t1 = t0 + vc.retention_sec() + 1
    out = vc.sweep(now=t1)
    assert out["expired"] == 1 and not os.path.isdir(d)
    assert vc.get(rec["id"])["state"] == "expired" and ambiente["ev"][-1][0] == "expired"
    assert vc.sweep(now=t1 + 89 * D)["purged"] == 0
    assert vc.sweep(now=t1 + 91 * D)["purged"] == 1 and vc.get(rec["id"]) is None


def test_bozze_stantie_purgate_dal_sweep(tmp_path):
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "sample_ok", t0)
    assert vc.sweep(now=t0 + vc.sample_ttl_sec() + 1)["drafts_purged"] == 1
    assert vc.get(rec["id"]) is None


def test_demo_failed_rilancia_ogni_6h_e_rimborsa_a_7_giorni(tmp_path, ambiente):
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "demo_failed", t0)
    assert vc.sweep(now=t0 + 3600)["relaunched"] == 0
    assert vc.sweep(now=t0 + 6 * 3600 + 1)["relaunched"] == 1 and ambiente["rel"] == [rec["id"]]
    # il rilancio (finto) non ha cambiato stato: dopo altre 6 h rilancia di nuovo
    vc.store().update(rec["id"], {"demo": dict(vc.get(rec["id"])["demo"], failed_at=t0 + 6 * 3600 + 1)})
    assert vc.sweep(now=t0 + 12 * 3600 + 5)["relaunched"] == 1
    out = vc.sweep(now=t0 + 7 * D + 1)
    assert out["refunded"] == 1 and ambiente["ref"] == [(rec["id"], "demo_failed_timeout")]


def test_promemoria_di_approvazione_e_rimborso_a_30_giorni(tmp_path, ambiente):
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "demos_ready", t0)
    assert vc.sweep(now=t0 + 3600)["reminded"] == 0
    assert vc.sweep(now=t0 + D + 1)["reminded"] == 1
    assert ambiente["ev"][-1] == ("approval_reminder", rec["id"], {"stage": 1})
    assert vc.sweep(now=t0 + 2 * D)["reminded"] == 0
    assert vc.sweep(now=t0 + 7 * D + 1)["reminded"] == 1
    assert ambiente["ev"][-1][2]["stage"] == 2
    assert vc.get(rec["id"])["demo"]["reminders"] == [1, 2]
    assert vc.sweep(now=t0 + 30 * D + 1)["refunded"] == 1
    assert ambiente["ref"] == [(rec["id"], "no_approval")]


def test_sweep_non_si_ferma_su_un_record_rotto(tmp_path, monkeypatch):
    t0 = 1_000_000
    a = voce(tmp_path, "a", "ready", t0)
    b = voce(tmp_path, "b", "ready", t0)
    vc.store().update(a["id"], {"expires_at": "rotto"})
    t1 = t0 + vc.retention_sec() + 1
    out = vc.sweep(now=t1)
    assert out["expired"] == 1 and vc.get(b["id"])["state"] == "expired"


def test_digest_data_conta_nella_finestra(tmp_path):
    t0 = 1_000_000
    voce(tmp_path, "a", "ready", t0)
    voce(tmp_path, "b", "demo_failed", t0)
    c = voce(tmp_path, "c", "demos_ready", t0)
    vc.transition(c["id"], "refunded", {"refund": {"reason": "user_rejected"}}, now=t0)
    d = vc.digest_data(window_hours=24, now=t0 + 3600)
    labels = {r["label"]: r["count"] for r in d["rows"]}
    assert labels["paid"] == 3 and labels["ready"] == 1 and labels["demo_failed"] == 1
    assert labels["refunded:user_rejected"] == 1 and d["active_ready"] == 1
    assert vc.digest_data(window_hours=24, now=t0 + 3 * D)["rows"] == [
        {"label": "demo_failed", "count": 1}]
```

- [ ] **Step 2: Eseguire i test e vederli fallire**

Run: `python -m pytest test/test_voice_clone_sweep.py -v --tb=short`
Expected: FAIL con `AttributeError: module 'voice_clone' has no attribute 'set_hooks'`.

- [ ] **Step 3: Implementazione**

Dopo `RESUME_TOKEN_DAYS = 30`:

```python
SWEEP_INTERVAL_SEC = 3600
EXPIRY_WARN_SEC = 30 * 86400
DEMO_FAILED_RELAUNCH_SEC = 6 * 3600
DEMO_FAILED_REFUND_SEC = 7 * 86400
APPROVAL_REMINDER_SEC = (24 * 3600, 7 * 86400)
APPROVAL_REFUND_SEC = 30 * 86400
RECORD_PURGE_SEC = 90 * 86400
```

In `touch_used`, il patch diventa `{"last_used_at": t, "expires_at": t + retention_sec(), "expiry_warned_at": None}`.

In coda al file:

```python
# ---------------------------------------------------------------------------
# ciclo di vita (§6.5, §10)
# ---------------------------------------------------------------------------
_hooks = {"notify": None, "relaunch": None, "refund": None}


def set_hooks(notify=None, relaunch=None, refund=None):
    _hooks.update({"notify": notify, "relaunch": relaunch, "refund": refund})


def _hook(name, *args, **kw):
    fn = _hooks.get(name)
    if fn is None:
        return
    try:
        fn(*args, **kw)
    except Exception as e:      # noqa: BLE001
        print(f"[voice_clone] hook {name} fallito: {e}", flush=True)


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        raise ValueError(f"timestamp non numerico: {v!r}")


def _sweep_one(rec, t, out):
    state = rec.get("state")
    cid = rec["id"]
    if state == "ready":
        exp = _num(rec.get("expires_at"))
        if exp <= t:
            with _lock:
                cur = get(cid)
                if cur and cur.get("state") == "ready":
                    cur = transition(cid, "expired", now=t)
            remove_files(cur)
            out["expired"] += 1
            _hook("notify", "expired", cur)
        elif exp - t <= EXPIRY_WARN_SEC and not rec.get("expiry_warned_at"):
            store().update(cid, {"expiry_warned_at": t})
            out["warned"] += 1
            _hook("notify", "expiring", rec, days=max(0, int((exp - t) // 86400)))
        return
    if state in _TERMINAL:
        stamp = _num(rec.get(_STAMP_ON_ENTER.get(state) or "") or rec.get("created_at"))
        if t - stamp >= RECORD_PURGE_SEC:
            store().delete(cid)
            out["purged"] += 1
        return
    demo = rec.get("demo") or {}
    if state == "demo_failed":
        first = _num(demo.get("first_failed_at") or demo.get("failed_at") or rec.get("paid_at"))
        if t - first >= DEMO_FAILED_REFUND_SEC:
            out["refunded"] += 1
            _hook("refund", cid, "demo_failed_timeout")
        elif t - _num(demo.get("failed_at")) >= DEMO_FAILED_RELAUNCH_SEC:
            out["relaunched"] += 1
            _hook("relaunch", cid)
        return
    if state == "demos_ready":
        since = _num(rec.get("demos_ready_at") or rec.get("paid_at"))
        if t - since >= APPROVAL_REFUND_SEC:
            out["refunded"] += 1
            _hook("refund", cid, "no_approval")
            return
        sent = list(demo.get("reminders") or [])
        for stage, delay in enumerate(APPROVAL_REMINDER_SEC, start=1):
            if stage not in sent and t - since >= delay:
                sent.append(stage)
                store().update(cid, {"demo": dict(demo, reminders=sent)})
                out["reminded"] += 1
                _hook("notify", "approval_reminder", rec, stage=stage)
                break


def sweep(now=None):
    """Un giro del ciclo di vita. Ogni record e' isolato: un errore su uno
    non ferma gli altri (incidente cleanup loop 2026-06-15)."""
    t = _now(now)
    out = {"drafts_purged": 0, "warned": 0, "expired": 0, "purged": 0,
           "relaunched": 0, "refunded": 0, "reminded": 0}
    try:
        out["drafts_purged"] = len(purge_stale_drafts(now=t) or [])
    except Exception as e:      # noqa: BLE001
        print(f"[voice_clone] purge bozze fallita: {e}", flush=True)
    for rec in list(_all()):
        try:
            _sweep_one(rec, t, out)
        except Exception as e:      # noqa: BLE001
            print(f"[voice_clone] sweep {rec.get('id')}: {type(e).__name__}: {e}", flush=True)
    return out


def digest_data(window_hours=24, now=None):
    """Sezione «Voci campionate» del digest admin (§12): solo contatori."""
    t = _now(now)
    since = t - int(window_hours) * 3600
    counts = {}
    active = 0

    def bump(label):
        counts[label] = counts.get(label, 0) + 1

    for rec in _all():
        st = rec.get("state")
        if st == "ready":
            active += 1
        if st == "demo_failed":
            bump("demo_failed")
        if (rec.get("paid_at") or 0) >= since:
            bump("paid")
        if (rec.get("ready_at") or 0) >= since:
            bump("ready")
        if st == "refunded" and (rec.get("refunded_at") or 0) >= since:
            bump("refunded:" + ((rec.get("refund") or {}).get("reason") or "unknown"))
        if st == "expired" and (rec.get("expired_at") or 0) >= since:
            bump("expired")
        if st == "deleted" and (rec.get("deleted_at") or 0) >= since:
            bump("deleted")
    rows = [{"label": k, "count": v} for k, v in sorted(counts.items())]
    return {"window_hours": int(window_hours), "rows": rows, "active_ready": active}
```

Verificare che `purge_stale_drafts` ritorni la lista degli id purgati (piano 1); se ritorna un intero, usare quello.

- [ ] **Step 4: Eseguire i test**

Run: `python -m pytest test/test_voice_clone_sweep.py test/test_voice_clone.py test/test_voice_clone_demo.py -v --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```
python -m py_compile voice_clone.py
git add voice_clone.py test/test_voice_clone_sweep.py
git commit -m "feat(voice-clone): sweep del ciclo di vita e dati per il digest"
```

---

### Task 5: Email in sette lingue (`email_service`, `i18n/voice_clone_emails.json`)

**Files:**
- Create: `i18n/voice_clone_emails.json`
- Modify: `email_service.py` (caricamento accanto alle costanti di modulo; funzioni dopo `_send_voucher_email`; provider e blocco digest accanto a `_abuse_*`; `{voice_clone_block}` nell'HTML del digest accanto a `{abuse_block}`)
- Test: `test/test_voice_clone_emails.py`

**Interfaces:**
- Consumes: `_send_email(to_addr, subject, html_body)`, `VOUCHER_EXPIRY_DAYS` da `payment` (già importato in `email_service`? se no, importare `payment` è ammesso: non importa `audiobook_app`).
- Produces (tutte ritornano `bool`, mai sollevano; `lang` fuori dalle 7 → `en`):
  - `send_voice_clone_paid(email, lang, *, voice_code, amount_eur, resume_url, manage_url, delete_url)` (§8.1);
  - `send_voice_clone_confirm(email, lang, *, confirm_code, minutes=15)` (§8.2);
  - `send_voice_clone_device_added(email, lang, *, devices_url)` (§8.2);
  - `send_voice_clone_ready(email, lang, *, voice_code, manage_url, delete_url, retention_days)` (§8.3);
  - `send_voice_clone_expiring(email, lang, *, days, manage_url)` (§8.4);
  - `send_voice_clone_reminder(email, lang, *, resume_url, stage)` (§10);
  - `send_voice_clone_refunded(email, lang, *, amount_eur, method, reason, voucher_code=None, voucher_amount=None, expiry_days=None)` (§8.5: per `paypal` con `voucher_code` mostra il buono e la scadenza, per `voucher` dice che l'importo è tornato sul buono originale, per `free` non manda nulla e ritorna `False`);
  - `set_voice_clone_provider(fn)` e `_voice_clone_block_html(data=None)` sul modello di `set_abuse_provider`/`_abuse_block_html`; nel digest: `_vc_data = _voice_clone_provider_data()` accanto a `_abuse_data`, `voice_clone_block = _voice_clone_block_html(_vc_data or {})`, placeholder `{voice_clone_block}` subito dopo `{abuse_block}`.
- Chiavi JSON per lingua (identiche nelle 7 lingue): `brand`, `paid_subject`, `paid_body`, `confirm_subject`, `confirm_body`, `device_subject`, `device_body`, `ready_subject`, `ready_body`, `expiring_subject`, `expiring_body`, `reminder_subject`, `reminder_body_1`, `reminder_body_2`, `refund_subject`, `refund_body_paypal`, `refund_body_voucher`, `refund_reason_user_rejected`, `refund_reason_sample_unusable`, `refund_reason_demo_failed_timeout`, `refund_reason_no_approval`, `footer`. Placeholder in `str.format`: `{voice_code}`, `{amount}`, `{resume_url}`, `{manage_url}`, `{delete_url}`, `{devices_url}`, `{confirm_code}`, `{minutes}`, `{days}`, `{voucher_code}`, `{voucher_amount}`, `{expiry_days}`, `{reason}`. I corpi sono HTML semplice (`<p>`, `<strong>`, `<a href>`); i valori vengono `html.escape`-ati prima del `format`; gli URL no.
- Testi: nessun nome di provider; oggetto §8.1 «La tua voce campione: codice e ricevuta» (it) / «Your voice sample: code and receipt» (en) e così via; §8.3 «La tua voce campione è pronta»; §8.4 «La tua voce campione scade fra {days} giorni»; §8.2 conferma con «{confirm_code}» e «{minutes} minuti», dispositivo «Nuovo dispositivo autorizzato». Il testo tradotto nelle altre cinque lingue lo scrive l'implementer (fr/es/de/zh/hi), fedele all'italiano e all'inglese.

- [ ] **Step 1: Test che falliscono**

```python
"""Email della voce campione in sette lingue (spec §8)."""
import json
import os

import pytest

import email_service as es

LANGS = ("it", "en", "fr", "es", "de", "zh", "hi")
KEYS = ("brand", "paid_subject", "paid_body", "confirm_subject", "confirm_body",
        "device_subject", "device_body", "ready_subject", "ready_body",
        "expiring_subject", "expiring_body", "reminder_subject", "reminder_body_1",
        "reminder_body_2", "refund_subject", "refund_body_paypal", "refund_body_voucher",
        "refund_reason_user_rejected", "refund_reason_sample_unusable",
        "refund_reason_demo_failed_timeout", "refund_reason_no_approval", "footer")
PROVIDERS = ("runpod", "voxcpm", "deepseek", "gemini", "speechify")


@pytest.fixture
def inviate(monkeypatch):
    out = []
    monkeypatch.setattr(es, "_send_email", lambda to, subj, body, **kw: out.append((to, subj, body)) or True)
    return out


def test_il_json_ha_tutte_le_lingue_e_le_chiavi():
    path = os.path.join(os.path.dirname(es.__file__), "i18n", "voice_clone_emails.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for lang in LANGS:
        assert set(data[lang]) == set(KEYS), lang
        for k in KEYS:
            assert data[lang][k].strip(), (lang, k)
            assert not any(p in data[lang][k].lower() for p in PROVIDERS), (lang, k)


@pytest.mark.parametrize("lang", LANGS + ("xx",))
def test_paid_in_ogni_lingua_e_fallback(inviate, lang):
    assert es.send_voice_clone_paid("u@x.it", lang, voice_code="ABCD-EFGH-JKMN", amount_eur=5.0,
                                    resume_url="https://a/vc/r/resume", manage_url="https://a/vc/m/devices",
                                    delete_url="https://a/vc/m/delete") is True
    to, subj, body = inviate[-1]
    assert to == "u@x.it" and "ABCD-EFGH-JKMN" in body and "5.00" in body
    assert "https://a/vc/r/resume" in body and "https://a/vc/m/delete" in body
    if lang == "it":
        assert subj == "La tua voce campione: codice e ricevuta"
    if lang == "xx":
        assert subj == "Your voice sample: code and receipt"


def test_confirm_e_device(inviate):
    assert es.send_voice_clone_confirm("u@x.it", "it", confirm_code="123456")
    assert "123456" in inviate[-1][2] and "15" in inviate[-1][2]
    assert es.send_voice_clone_device_added("u@x.it", "en", devices_url="https://a/vc/m/devices")
    assert inviate[-1][1] == "New device authorized" and "https://a/vc/m/devices" in inviate[-1][2]


def test_ready_expiring_reminder(inviate):
    assert es.send_voice_clone_ready("u@x.it", "it", voice_code="AAAA-BBBB-CCCC", manage_url="https://m",
                                     delete_url="https://d", retention_days=180)
    assert inviate[-1][1] == "La tua voce campione è pronta" and "180" in inviate[-1][2]
    assert es.send_voice_clone_expiring("u@x.it", "it", days=30, manage_url="https://m")
    assert inviate[-1][1] == "La tua voce campione scade fra 30 giorni"
    assert es.send_voice_clone_reminder("u@x.it", "en", resume_url="https://r", stage=2)
    assert "https://r" in inviate[-1][2]


def test_refund_paypal_voucher_free(inviate):
    assert es.send_voice_clone_refunded("u@x.it", "it", amount_eur=5.0, method="paypal",
                                        reason="user_rejected", voucher_code="V-1", voucher_amount=5.0,
                                        expiry_days=180)
    assert "V-1" in inviate[-1][2] and "180" in inviate[-1][2]
    assert es.send_voice_clone_refunded("u@x.it", "en", amount_eur=5.0, method="voucher",
                                        reason="sample_unusable")
    assert "V-1" not in inviate[-1][2] and "5.00" in inviate[-1][2]
    n = len(inviate)
    assert es.send_voice_clone_refunded("u@x.it", "en", amount_eur=0.0, method="free",
                                        reason="user_rejected") is False
    assert len(inviate) == n


def test_i_valori_vengono_escapati(inviate):
    es.send_voice_clone_paid("u@x.it", "en", voice_code="<b>x</b>", amount_eur=5.0,
                             resume_url="https://r", manage_url="https://m", delete_url="https://d")
    assert "<b>x</b>" not in inviate[-1][2] and "&lt;b&gt;x&lt;/b&gt;" in inviate[-1][2]


def test_send_email_che_fallisce_non_solleva(monkeypatch):
    def esplode(*a, **k):
        raise RuntimeError("smtp giu")
    monkeypatch.setattr(es, "_send_email", esplode)
    assert es.send_voice_clone_confirm("u@x.it", "it", confirm_code="1") is False


def test_blocco_digest():
    assert es._voice_clone_block_html({}) == ""
    assert es._voice_clone_block_html({"window_hours": 24, "rows": [], "active_ready": 3}) == ""
    html = es._voice_clone_block_html({"window_hours": 24, "active_ready": 3,
                                       "rows": [{"label": "paid", "count": 2},
                                                {"label": "refunded:user_rejected", "count": 1}]})
    assert "paid" in html and "2" in html and "refunded:user_rejected" in html and "3" in html
    es.set_voice_clone_provider(lambda: {"window_hours": 24, "rows": [{"label": "ready", "count": 1}],
                                         "active_ready": 1})
    try:
        assert "ready" in es._voice_clone_block_html()
    finally:
        es.set_voice_clone_provider(None)
```

- [ ] **Step 2: Eseguire i test e vederli fallire**

Run: `python -m pytest test/test_voice_clone_emails.py -v --tb=short`
Expected: FAIL (file JSON assente / `AttributeError: send_voice_clone_paid`).

- [ ] **Step 3: Implementazione**

`i18n/voice_clone_emails.json`: oggetto `{"it": {...}, "en": {...}, "fr": {...}, "es": {...}, "de": {...}, "zh": {...}, "hi": {...}}`. Versione italiana di riferimento (le altre lingue seguono lo stesso schema e gli stessi placeholder):

```json
"it": {
  "brand": "Audiobook Maker",
  "paid_subject": "La tua voce campione: codice e ricevuta",
  "paid_body": "<p>Grazie: il tuo campione è stato accettato e stiamo preparando le due frasi di prova.</p><p>Il codice della tua voce è <strong style=\"font-size:1.2em\">{voice_code}</strong>. Serve per ritrovarla da un altro dispositivo: custodiscilo come una password.</p><p>Importo: <strong>{amount} EUR</strong>.</p><p>Per ascoltare le prove e approvare la voce: <a href=\"{resume_url}\">{resume_url}</a></p><p>Dispositivi autorizzati: <a href=\"{manage_url}\">{manage_url}</a><br>Cancellare la voce e i file: <a href=\"{delete_url}\">{delete_url}</a></p>",
  "confirm_subject": "Il tuo codice di conferma",
  "confirm_body": "<p>Qualcuno sta aggiungendo la tua voce campione su un nuovo dispositivo. Se sei tu, inserisci questo codice entro {minutes} minuti:</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{confirm_code}</strong></p><p>Se non sei stato tu, ignora questa email: senza il codice nessuno può usare la tua voce.</p>",
  "device_subject": "Nuovo dispositivo autorizzato",
  "device_body": "<p>Un nuovo dispositivo può ora usare la tua voce campione.</p><p>Se non lo riconosci, revocalo da qui: <a href=\"{devices_url}\">{devices_url}</a></p>",
  "ready_subject": "La tua voce campione è pronta",
  "ready_body": "<p>La tua voce campione è approvata e disponibile fra le voci dei tuoi audiolibri.</p><p>Codice: <strong>{voice_code}</strong>.</p><p>Resta attiva per {retention_days} giorni dall'ultimo uso; ti avviseremo prima della scadenza.</p><p>Dispositivi: <a href=\"{manage_url}\">{manage_url}</a><br>Cancellazione: <a href=\"{delete_url}\">{delete_url}</a></p>",
  "expiring_subject": "La tua voce campione scade fra {days} giorni",
  "expiring_body": "<p>Non usi la tua voce campione da un po': scadrà fra {days} giorni e i file verranno cancellati.</p><p>Per rinnovarla basta usarla in un audiolibro. Dispositivi: <a href=\"{manage_url}\">{manage_url}</a></p>",
  "reminder_subject": "Le prove della tua voce ti aspettano",
  "reminder_body_1": "<p>Le due frasi di prova della tua voce campione sono pronte da un giorno. Ascoltale e decidi: <a href=\"{resume_url}\">{resume_url}</a></p>",
  "reminder_body_2": "<p>Le prove della tua voce campione aspettano da una settimana. Senza una decisione entro 30 giorni dalla preparazione l'importo verrà rimborsato e i file cancellati: <a href=\"{resume_url}\">{resume_url}</a></p>",
  "refund_subject": "Rimborso della voce campione",
  "refund_body_paypal": "<p>{reason}</p><p>Ti abbiamo emesso un buono di <strong>{voucher_amount} EUR</strong>, valido {expiry_days} giorni, spendibile su qualunque servizio:</p><p style=\"font-size:1.3em\"><strong>{voucher_code}</strong></p>",
  "refund_body_voucher": "<p>{reason}</p><p>L'importo di <strong>{amount} EUR</strong> è tornato sul buono con cui avevi pagato.</p>",
  "refund_reason_user_rejected": "Hai rifiutato le prove della tua voce campione.",
  "refund_reason_sample_unusable": "Il motore non è riuscito a usare il tuo campione: ci dispiace.",
  "refund_reason_demo_failed_timeout": "Non siamo riusciti a preparare le prove della tua voce entro sette giorni: ci dispiace.",
  "refund_reason_no_approval": "Le prove della tua voce campione non sono state approvate entro 30 giorni.",
  "footer": "<p style=\"color:#777;font-size:.9em\">Audiobook Maker — email automatica, non rispondere.</p>"
}
```

In `email_service.py`, accanto alle altre costanti di modulo:

```python
_VC_I18N = {}
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n",
                           "voice_clone_emails.json"), encoding="utf-8") as _f:
        _VC_I18N = json.load(_f)
except Exception as _e:      # noqa: BLE001
    print(f"WARNING: i18n/voice_clone_emails.json non caricato: {_e}", flush=True)
```

Dopo `_send_voucher_email`:

```python
def _vc_t(lang):
    return _VC_I18N.get((lang or "").split("-")[0].lower()) or _VC_I18N.get("en") or {}


def _vc_send(email, lang, subject_key, body_keys, **values):
    """Compone e manda una email della voce campione. `body_keys`: chiavi da
    concatenare. I valori vengono escapati tranne gli URL (chiavi *_url).
    Ritorna False su qualunque errore: chi chiama sta gia' nel flusso."""
    t = _vc_t(lang)
    if not t or not email:
        return False
    safe = {k: (v if k.endswith("_url") else html.escape(str(v))) for k, v in values.items()}
    try:
        subject = t[subject_key].format(**safe)
        body = "".join(t[k].format(**safe) for k in body_keys) + t.get("footer", "")
        return bool(_send_email(email, subject, body))
    except Exception as e:      # noqa: BLE001
        print(f"[email] voice clone {subject_key} non inviata: {type(e).__name__}: {e}", flush=True)
        return False


def send_voice_clone_paid(email, lang, *, voice_code, amount_eur, resume_url, manage_url, delete_url):
    return _vc_send(email, lang, "paid_subject", ("paid_body",), voice_code=voice_code,
                    amount=f"{float(amount_eur):.2f}", resume_url=resume_url,
                    manage_url=manage_url, delete_url=delete_url)


def send_voice_clone_confirm(email, lang, *, confirm_code, minutes=15):
    return _vc_send(email, lang, "confirm_subject", ("confirm_body",),
                    confirm_code=confirm_code, minutes=minutes)


def send_voice_clone_device_added(email, lang, *, devices_url):
    return _vc_send(email, lang, "device_subject", ("device_body",), devices_url=devices_url)


def send_voice_clone_ready(email, lang, *, voice_code, manage_url, delete_url, retention_days):
    return _vc_send(email, lang, "ready_subject", ("ready_body",), voice_code=voice_code,
                    manage_url=manage_url, delete_url=delete_url, retention_days=retention_days)


def send_voice_clone_expiring(email, lang, *, days, manage_url):
    return _vc_send(email, lang, "expiring_subject", ("expiring_body",), days=days,
                    manage_url=manage_url)


def send_voice_clone_reminder(email, lang, *, resume_url, stage):
    key = "reminder_body_2" if int(stage) >= 2 else "reminder_body_1"
    return _vc_send(email, lang, "reminder_subject", (key,), resume_url=resume_url)


def send_voice_clone_refunded(email, lang, *, amount_eur, method, reason, voucher_code=None,
                              voucher_amount=None, expiry_days=None):
    if method not in ("paypal", "voucher"):
        return False
    t = _vc_t(lang)
    reason_text = t.get("refund_reason_" + reason) or t.get("refund_reason_user_rejected") or ""
    if method == "paypal":
        if not voucher_code:
            return False
        return _vc_send(email, lang, "refund_subject", ("refund_body_paypal",), reason=reason_text,
                        voucher_code=voucher_code,
                        voucher_amount=f"{float(voucher_amount if voucher_amount is not None else amount_eur):.2f}",
                        expiry_days=expiry_days if expiry_days is not None else VOUCHER_EXPIRY_DAYS,
                        amount=f"{float(amount_eur):.2f}")
    return _vc_send(email, lang, "refund_subject", ("refund_body_voucher",), reason=reason_text,
                    amount=f"{float(amount_eur):.2f}")
```

`VOUCHER_EXPIRY_DAYS`: usare quello già importato da `payment` in `email_service` (cercare `VOUCHER_BONUS_PERCENT` per vedere come arriva) e importare allo stesso modo `VOUCHER_EXPIRY_DAYS`. `html` e `json` vanno importati se mancano.

Provider e blocco del digest, accanto a `_abuse_*`:

```python
_voice_clone_provider = None


def set_voice_clone_provider(fn):
    global _voice_clone_provider
    _voice_clone_provider = fn


def _voice_clone_provider_data():
    if _voice_clone_provider is None:
        return None
    try:
        return _voice_clone_provider() or None
    except Exception as e:      # noqa: BLE001
        print(f"[email] voice clone provider fallito: {e}", flush=True)
        return None


def _voice_clone_block_html(data=None):
    """Sezione «Voci campionate» del digest: contatori per stato nella
    finestra e voci attive. Mai email, codici o token."""
    d = _voice_clone_provider_data() if data is None else data
    if not d or not (d.get("rows") or []):
        return ""
    hours = int(d.get("window_hours") or 24)
    righe = "".join(f"<tr><td>{html.escape(str(r.get('label')))}</td>"
                    f"<td style=\"text-align:right\">{int(r.get('count') or 0)}</td></tr>"
                    for r in d["rows"])
    return (f"<h3>Voci campionate (ultime {hours} h)</h3>"
            f"<table>{righe}</table>"
            f"<p>Voci attive: <strong>{int(d.get('active_ready') or 0)}</strong></p>")
```

Nel digest: dopo `_abuse_data = _abuse_provider_data()` aggiungere `_vc_data = _voice_clone_provider_data()`; dopo `abuse_block = _abuse_block_html(_abuse_data or {})` aggiungere `voice_clone_block = _voice_clone_block_html(_vc_data or {})`; nella f-string HTML mettere `{voice_clone_block}` subito dopo `{abuse_block}`.

- [ ] **Step 4: Eseguire i test**

Run: `python -m pytest test/test_voice_clone_emails.py test/test_email_service.py -v --tb=short` (se `test/test_email_service.py` non esiste, eseguire `python -m pytest test/ -k "email or digest" -v --tb=short`)
Expected: PASS.

- [ ] **Step 5: Commit**

```
python -m py_compile email_service.py
python -c "import json; json.load(open('i18n/voice_clone_emails.json', encoding='utf-8'))"
git add email_service.py i18n/voice_clone_emails.json test/test_voice_clone_emails.py
git commit -m "feat(voice-clone): email in sette lingue e sezione del digest"
```

---

### Task 6: Endpoint `/api/voice_clone/*`, PayPal, pagine `/vc/*`, `_mine`, cablaggio (`audiobook_app`)

**Files:**
- Modify: `audiobook_app.py`:
  - import dopo `import voxcpm_ranking` (riga ~92): `import voice_clone`, `import voice_clone_audio`, `import voice_clone_demo`, `import voice_clone_prompts`;
  - init dopo `tts_backend_state.init(_DATA_DIR)` (riga ~377);
  - `X-Robots-Tag` (riga ~349): `if path.startswith('/dl/') or path.startswith('/vc/')`;
  - `/api/voices` (riga ~8673): chiave `_mine`;
  - nuovi endpoint dopo `/api/voice_demo` (riga ~8748+);
  - `/api/paypal_create_order_voice_clone` dopo `/api/paypal_create_order_translate` (riga ~13673);
  - `_ensure_background_threads()` (riga ~18183): sweeper supervisionato + `voice_clone_demo.recover()` + provider digest.
- Test: `test/test_voice_clone_api.py`

**Interfaces:**
- Consumes: Task 1-5; `voice_clone_audio.prepare_sample/check_transcript/probe/SampleRejected/AsrUnavailable/asr_enabled/max_cer`; `voice_clone_prompts.prompt_for/prompt_version/languages`; `voice_clone.offered_languages/create_draft/claim/confirm/forget/revoke_device/devices_view/by_resume_token/by_manage_token/resolve/mine/get/authorized/public_view`; `_get_client_id`, `_get_browser_lang`, `_client_ip`, `_ip_rl_check`, `_paypal_available`, `_paypal_create_order`, `payment.voice_clone_price_eur`, `BASE_URL`, `_log_activity`.
- Produces (JSON; errori `{"error": <testo inglese>, "error_code": <codice>}`; ogni endpoint `/api/voice_clone/*` risponde 404 `voice_clone_disabled` se `voice_clone.enabled()` è falso o `voxcpm_tts` è `None`):
  - `GET /api/voice_clone/config` → `{"enabled", "price_eur", "free", "max_upload_mb", "regen_max", "languages": offered_languages(), "min_sec", "max_sec", "asr": asr_enabled()}` (min/max dal `Gate` di `voice_clone_audio.gate_from_env()`).
  - `GET /api/voice_clone/prompt?lang=&gender=` → `{"text", "version", "lang", "gender"}`; 400 `bad_request` se lingua non offerta o genere non in `m|f`.
  - `POST /api/voice_clone/sample` (multipart: `file`, `lang`, `locale`, `gender`, `prompt_version`): rate limit `_ip_rl_check("vc_sample", ip, 10, 30)` e per cid `_ip_rl_check("vc_sample_cid", cid, 10, 10)` → 429 `rate_limited` con `retry_after`; file oltre `max_upload_mb()` → 413 `too_large`; salva in `UPLOAD_DIR/vc_<uuid>.<ext>` (ext da `secure_filename`, default `webm`), `prepare_sample` → `SampleRejected` → 400 `sample_rejected` con `reason` (chiave `vc_gate_*`) e `metrics`; poi se `asr_enabled()`: `check_transcript(wav, lang, prompt_text)` → `AsrUnavailable` → 503 `asr_unavailable`; `cer > max_cer()` → 400 `sample_rejected` con `reason="vc_gate_transcript"`, `cer`, `heard`; infine `create_draft(cid, lang=, locale=, gender=, prompt_text=, sample_wav=, original_path=, original_ext=, metrics=, ui_lang=_get_browser_lang() or "en")` → 200 `{"clone_id", "state", "expires_at", "metrics", "cer"}`. I file temporanei vengono rimossi nel `finally` (il draft ha già copiato i suoi). Log `VOICE_CLONE_SAMPLE_OK`/`VOICE_CLONE_SAMPLE_REJECTED` via `_log_activity(clone_id, "", op, client_id=cid, client_ip=ip)`.
  - `GET /api/voice_clone/demo_texts?locale=` → `{"common": {"id","text"}, "extra": [{"id","text"}]}`: `common` = demo `common` della prima voce del catalogo con quel locale (`voxcpm_catalog.voices()`), `extra` = demo non comuni di tutte le voci del locale dedup per testo, ordinate per id; 400 `bad_request` se il locale non ha voci.
  - `POST /api/voice_clone/commit` JSON `{clone_id, email, email2, extra_id, payment_token}`: `email != email2` (normalizzate) → 400 `email_mismatch`; `extra_id` risolto contro `demo_texts` del locale del record (id ignoto → 400 `bad_request`); `price = payment.voice_clone_price_eur()`; `voice_clone.commit(...)` → `EmailHasVoice` → 409 `email_has_voice`; `ValueError` dal pagamento → 402 `payment_invalid`; `PermissionError` → 403 `not_authorized`; `VoiceGone` → 410 `voice_gone`; su `created` → `voice_clone_demo.start_demos(clone_id)` e `email_service.send_voice_clone_paid(...)` con `resume_url=f"{BASE_URL}/vc/{rec['resume_token']['value']}/resume"`, `manage_url=f"{BASE_URL}/vc/{rec['manage_token']}/devices"`, `delete_url=f"{BASE_URL}/vc/{rec['manage_token']}/delete"`; log `VOICE_CLONE_PAID`; risposta 200 `{"clone_id", "voice_code", "state", "created"}` (il `voice_code` qui è ammesso: è il proprietario appena pagante).
  - `GET /api/voice_clone/progress/<clone_id>`: SSE (`text/event-stream`) che ogni 2 s manda `data: {json della public_view}` finché lo stato non è `demos_ready`/`demo_failed`/`ready`/`refunded` o passano 30 min; richiede `voice_clone.authorized(voice_id_of(rec), cid)` → 403 `not_authorized`; sconosciuto → 404 `voice_not_found`. Nella public_view va aggiunto `regen_left = regen_max - regen_used` e `demo_urls` quando `demos_ready`/`ready`.
  - `POST /api/voice_clone/<id>/approve`, `/regenerate` (JSON `{extra_id}`), `/retry`, `/reject`: cid via `_get_client_id()`; `PermissionError` → 403 `not_authorized`; `voice_clone.BadTransition` → 409 `bad_state`; `RegenExhausted` → 409 `regen_exhausted`; `VoiceGone` → 410 `voice_gone`; `approve` manda `send_voice_clone_ready` (log `VOICE_CLONE_READY`) e invalida `_invalidate_voices_cache()` no (la `_mine` non è in cache); `reject` è idempotente e ritorna la public_view. Tutte 200 con la public_view arricchita.
  - `GET /api/voice_clone/mine` → `{"voices": voice_clone.mine(cid)}`.
  - `POST /api/voice_clone/claim` JSON `{voice_code}`: rate limit `_ip_rl_check("vc_claim_cid", cid, 5, 5)` → 429; `claim(code, cid)` → `("ok", rec, None)` → 200 `{"status":"ok","voice": public_view}`; `("pending", rec, code)` → `send_voice_clone_confirm(rec["owner_email"], rec["ui_lang"], confirm_code=code)` → 200 `{"status":"pending"}`; `ValueError("locked")` → 423 `code_locked`; codice ignoto (`None` da `claim`, o `LookupError`: seguire il contratto del piano 1) → 404 `code_unknown`. Log `VOICE_CLONE_CLAIM`.
  - `POST /api/voice_clone/confirm` JSON `{voice_code, confirm_code}`: `confirm(...)` → `"ok"` → 200 `{"status":"ok","voice"}` + `send_voice_clone_device_added(owner_email, ui_lang, devices_url)` + log `VOICE_CLONE_DEVICE_ADDED`; `"wrong"` → 400 `confirm_wrong`; `"expired"` → 410 `confirm_expired`; `"none"` → 404 `confirm_none`; `"locked"` → 423 `code_locked`.
  - `POST /api/voice_clone/<id>/forget` → `forget(id, cid)` → 200 `{"ok": true}`; 404 `voice_not_found` se non trovata.
  - `POST /api/voice_clone/<id>/resend`: solo proprietario (`rec["devices"][0]["cid"] == cid`, `via == "creator"`) → altrimenti 403 `not_authorized`; `_ip_rl_check("vc_resend", id, 3, 3)` → 429 `rate_limited`; rimanda `send_voice_clone_paid` (stato non `ready`) o `send_voice_clone_ready` (stato `ready`) → 200 `{"ok": true}`.
  - `GET /api/voice_clone/<id>/sample.wav` e `/demo/<which>` (`which` in `common|extra`): solo cid autorizzato → 403; file via `voice_clone._ensure_local(rec, name)` (riporta da R2 se evictato) e `send_file(path, mimetype="audio/wav", conditional=True)`; assente → 404 `voice_not_found`.
  - `POST /api/paypal_create_order_voice_clone` JSON `{clone_id}`: `_paypal_available()` → 503; record in `sample_ok` del cid → altrimenti 404/403; prezzo ≤ 0 → 400 `No payment required`; `_paypal_create_order(price, "Voice sample - Audiobook Maker", custom_id="vc:"+clone_id)` → `{"order_id","amount_eur","status"}`.
  - Pagine HTML (`/vc/<token>/resume`, `/vc/<manage_token>/devices`, `/vc/<manage_token>/delete` GET+POST): `resume` → record via `by_resume_token(token)`; se il cid corrente non è fra i `devices` viene aggiunto con `via="resume"`; poi redirect 302 a `/?vc=<clone_id>` (il piano 3 apre il wizard sul pannello 4); token ignoto/scaduto/terminale → 404. `devices` → pagina minimale in inglese (con `data-lang` = `ui_lang`) che elenca `devices_view(rec)` con un bottone `POST /vc/<manage_token>/devices/revoke` (`cid` nel form) → `revoke_device`. `delete` GET → pagina di conferma con form POST; POST → `voice_clone.delete_by_owner(manage_token)` (nuova, in `voice_clone`: `ready`/`demos_ready`/`demo_failed`/`paid`/`demos_generating` → `deleted` con `remove_files`; ritorna il record o `None`) → pagina «Voice deleted». Tutte le pagine sono `X-Robots-Tag: noindex` (già coperto dal prefisso `/vc/`), senza segreti nel corpo (mai il token in chiaro oltre l'URL stesso).
  - `/api/voices`: dopo il blocco `_voxcpm`, `voices["_mine"] = voice_clone.mine(_get_client_id()) if (voice_clone.enabled() and voxcpm_tts is not None) else []` in try/except (`[]` su errore). Calcolo per richiesta, mai dentro `_fetch_voices` (cache condivisa).
  - Cablaggio in `_ensure_background_threads()`: `voice_clone_demo.configure(notifier=_voice_clone_notify)`; `voice_clone.set_hooks(notify=_voice_clone_notify, relaunch=lambda cid: voice_clone_demo.start_demos(cid), refund=lambda cid, reason: voice_clone_demo.refund(cid, reason, bonus=(reason == "demo_failed_timeout")))`; thread `_voice_clone_sweep_supervisor` (loop `sweep()` ogni `SWEEP_INTERVAL_SEC`, riavvio su eccezione come `_cleanup_supervisor`); `voice_clone_demo.recover()` in try; `_email_service.set_voice_clone_provider(voice_clone.digest_data)` in try.
  - `_voice_clone_notify(event, rec, **extra)`: mappa eventi → email + log: `demos_ready` → nessuna email (l'utente è in SSE; i promemoria coprono l'assenza) + `VOICE_CLONE_DEMOS_READY`; `demo_failed` → `VOICE_CLONE_DEMO_FAILED` + `_email_service.send_admin_notice(...)` se esiste una funzione di avviso admin (altrimenti `print`); `refunded` → `send_voice_clone_refunded(rec["owner_email"], rec["ui_lang"], amount_eur=extra["amount_eur"], method=extra["method"], reason=extra["reason"], voucher_code=extra.get("voucher_code"), voucher_amount=extra.get("bonus_amount") or extra["amount_eur"])` + `VOICE_CLONE_REFUNDED`; `expiring` → `send_voice_clone_expiring` + `VOICE_CLONE_EXPIRING`; `expired` → `VOICE_CLONE_EXPIRED`; `approval_reminder` → `send_voice_clone_reminder` + `VOICE_CLONE_REMINDER`. Le email vanno solo se `rec.get("owner_email")`.
- Log: sempre e solo l'id pubblico (`rec["id"]`) nel campo job_id di `_log_activity`; mai token, email, codici.

- [ ] **Step 1: Test che falliscono**

```python
"""Endpoint della voce campione (spec §3.4-§3.8, §6.6, §7.2, §9, §12)."""
import io
import json
import os

import pytest

import audiobook_app
import community_store
import email_service
import payment
import storage_backend
import voice_clone as vc
import voice_clone_audio as vca
import voice_clone_demo as vcd
import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
PROMPT_IT = None   # letto dal modulo prompts nella fixture


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave-di-prova")
    monkeypatch.setenv("ABM_VOICE_CLONE_ENABLED", "1")
    monkeypatch.setenv("ABM_VOICE_CLONE_ASR", "0")
    monkeypatch.delenv("ABM_EUR_CLONED_VOICE", raising=False)
    voxcpm_catalog.invalidate_cache()
    community_store.init(tmp_path)
    vc.init(tmp_path)
    vca.init(tmp_path)
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path / "up")
    (tmp_path / "up").mkdir()
    monkeypatch.setattr(audiobook_app, "BASE_URL", "https://abm.test")
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_OPT_DONE_FILE", tmp_path / "_paid_opt_done.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_opt_done", set())
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    monkeypatch.setattr(payment, "EUR_CLONED_VOICE", 5.0)
    monkeypatch.setattr(audiobook_app, "_ip_rl_buckets", {})
    inviate = []
    monkeypatch.setattr(email_service, "_send_email",
                        lambda to, subj, body, **kw: inviate.append((to, subj, body)) or True)
    monkeypatch.setattr(vcd, "start_demos", lambda cid, **kw: vc.get(cid))
    audiobook_app._invalidate_voices_cache()
    yield inviate
    voxcpm_catalog.invalidate_cache()


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie(audiobook_app._CLIENT_COOKIE_NAME, "cid-uno")
        yield c


def _cid(client, cid):
    client.set_cookie(audiobook_app._CLIENT_COOKIE_NAME, cid)


def _prompt():
    import voice_clone_prompts
    return voice_clone_prompts.prompt_for("it", "f")


def _draft(tmp_path, cid="cid-uno"):
    s = tmp_path / f"{cid}-s.wav"
    s.write_bytes(b"RIFF")
    o = tmp_path / f"{cid}-o.webm"
    o.write_bytes(b"webm")
    return vc.create_draft(cid, lang="it", locale="it-IT", gender="f", prompt_text=_prompt(),
                           sample_wav=str(s), original_path=str(o), original_ext="webm",
                           metrics={"duration": 15.0}, ui_lang="it")


def _paid(tmp_path, cid="cid-uno", email="u@example.com"):
    rec = _draft(tmp_path, cid)
    out, _ = vc.commit(rec["id"], cid, email=email, extra_id="memory", extra_text="e",
                       common_text="c", payment_token="", price_eur=0.0)
    return out


def test_config_e_prompt(client):
    r = client.get("/api/voice_clone/config")
    assert r.status_code == 200
    d = r.get_json()
    assert d["enabled"] is True and d["price_eur"] == 5.0 and d["free"] is False
    assert "it" in d["languages"] and d["regen_max"] == 3 and d["max_upload_mb"] == 20
    r = client.get("/api/voice_clone/prompt?lang=it&gender=f")
    assert r.status_code == 200 and r.get_json()["text"] == _prompt()
    assert client.get("/api/voice_clone/prompt?lang=xx&gender=f").status_code == 400


def test_disabilitato_risponde_404(client, monkeypatch):
    monkeypatch.setenv("ABM_VOICE_CLONE_ENABLED", "0")
    r = client.get("/api/voice_clone/config")
    assert r.status_code == 404 and r.get_json()["error_code"] == "voice_clone_disabled"
    r = client.get("/api/voices")
    assert r.status_code == 200 and r.get_json()["_mine"] == []


def test_sample_rifiutato_dal_gate(client, monkeypatch):
    def rifiuta(src, dst, **kw):
        raise vca.SampleRejected("vc_gate_short", "3.0s")
    monkeypatch.setattr(vca, "prepare_sample", rifiuta)
    r = client.post("/api/voice_clone/sample", data={
        "file": (io.BytesIO(b"webm-bytes"), "rec.webm"), "lang": "it", "locale": "it-IT",
        "gender": "f", "prompt_version": "x"}, content_type="multipart/form-data")
    assert r.status_code == 400
    d = r.get_json()
    assert d["error_code"] == "sample_rejected" and d["reason"] == "vc_gate_short"
    assert not [f for f in os.listdir(audiobook_app.UPLOAD_DIR) if f.startswith("vc_")]


def test_sample_ok_crea_la_bozza(client, monkeypatch):
    def prepara(src, dst, **kw):
        open(dst, "wb").write(b"RIFF-wav")
        return vca.Metrics(**{f: 0.0 for f in vca.Metrics.__dataclass_fields__})
    monkeypatch.setattr(vca, "prepare_sample", prepara)
    r = client.post("/api/voice_clone/sample", data={
        "file": (io.BytesIO(b"webm-bytes"), "rec.webm"), "lang": "it", "locale": "it-IT",
        "gender": "f", "prompt_version": "x"}, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["state"] == "sample_ok" and vc.get(d["clone_id"])["devices"][0]["cid"] == "cid-uno"
    assert not [f for f in os.listdir(audiobook_app.UPLOAD_DIR) if f.startswith("vc_")]


def test_sample_rate_limit_per_cid(client, monkeypatch):
    def rifiuta(src, dst, **kw):
        raise vca.SampleRejected("vc_gate_short", "3.0s")
    monkeypatch.setattr(vca, "prepare_sample", rifiuta)
    codes = []
    for _ in range(11):
        r = client.post("/api/voice_clone/sample", data={
            "file": (io.BytesIO(b"x"), "rec.webm"), "lang": "it", "locale": "it-IT", "gender": "f"},
            content_type="multipart/form-data")
        codes.append(r.status_code)
    assert codes[-1] == 429 and codes[:10] == [400] * 10


def test_demo_texts(client):
    r = client.get("/api/voice_clone/demo_texts?locale=it-IT")
    assert r.status_code == 200
    d = r.get_json()
    assert d["common"]["text"] and d["extra"]
    testi = [e["text"] for e in d["extra"]]
    assert len(testi) == len(set(testi)) and d["common"]["text"] not in testi
    assert client.get("/api/voice_clone/demo_texts?locale=xx-XX").status_code == 400


def test_commit_gratis_e_doppio_click(client, tmp_path, monkeypatch, ambiente):
    monkeypatch.setattr(payment, "EUR_CLONED_VOICE", 0.0)
    rec = _draft(tmp_path)
    extra = client.get("/api/voice_clone/demo_texts?locale=it-IT").get_json()["extra"][0]["id"]
    body = {"clone_id": rec["id"], "email": "U@example.com", "email2": "u@example.com ",
            "extra_id": extra, "payment_token": ""}
    r = client.post("/api/voice_clone/commit", json=body)
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["created"] is True and d["voice_code"] == vc.get(rec["id"])["voice_code"]
    assert ambiente[-1][0] == "u@example.com" and "/vc/" in ambiente[-1][2]
    assert vc.get(rec["id"])["resume_token"]["value"] in ambiente[-1][2]
    r = client.post("/api/voice_clone/commit", json=body)
    assert r.status_code == 200 and r.get_json()["created"] is False
    assert len(ambiente) == 1


def test_commit_errori(client, tmp_path, monkeypatch):
    rec = _draft(tmp_path)
    extra = client.get("/api/voice_clone/demo_texts?locale=it-IT").get_json()["extra"][0]["id"]
    base = {"clone_id": rec["id"], "email": "a@x.it", "email2": "a@x.it", "extra_id": extra,
            "payment_token": "NOPE"}
    r = client.post("/api/voice_clone/commit", json=dict(base, email2="b@x.it"))
    assert r.status_code == 400 and r.get_json()["error_code"] == "email_mismatch"
    r = client.post("/api/voice_clone/commit", json=base)
    assert r.status_code == 402 and r.get_json()["error_code"] == "payment_invalid"
    _paid(tmp_path, cid="cid-due", email="a@x.it")
    monkeypatch.setattr(payment, "EUR_CLONED_VOICE", 0.0)
    r = client.post("/api/voice_clone/commit", json=base)
    assert r.status_code == 409 and r.get_json()["error_code"] == "email_has_voice"
    _cid(client, "cid-tre")
    r = client.post("/api/voice_clone/commit", json=dict(base, email="c@x.it", email2="c@x.it"))
    assert r.status_code == 403 and r.get_json()["error_code"] == "not_authorized"


def test_paypal_order(client, tmp_path, monkeypatch):
    rec = _draft(tmp_path)
    monkeypatch.setattr(audiobook_app, "_paypal_available", lambda: True)
    catturato = {}

    def crea(amount, description, custom_id=None):
        catturato.update(amount=amount, description=description, custom_id=custom_id)
        return {"id": "ORD-1", "status": "CREATED"}
    monkeypatch.setattr(audiobook_app, "_paypal_create_order", crea)
    r = client.post("/api/paypal_create_order_voice_clone", json={"clone_id": rec["id"]})
    assert r.status_code == 200 and r.get_json() == {"order_id": "ORD-1", "amount_eur": 5.0, "status": "CREATED"}
    assert catturato == {"amount": 5.0, "description": "Voice sample - Audiobook Maker",
                         "custom_id": "vc:" + rec["id"]}
    _cid(client, "altro")
    assert client.post("/api/paypal_create_order_voice_clone", json={"clone_id": rec["id"]}).status_code == 403


def test_progress_sse_termina_su_demos_ready(client, tmp_path):
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready"):
        vc.transition(rec["id"], s)
    r = client.get(f"/api/voice_clone/progress/{rec['id']}")
    assert r.status_code == 200 and r.mimetype == "text/event-stream"
    payload = json.loads(r.get_data(as_text=True).strip().split("data: ")[-1])
    assert payload["state"] == "demos_ready" and payload["regen_left"] == 3
    assert payload["demo_urls"]["common"].endswith("/demo/common")
    assert "token" not in payload and "owner_email" not in payload
    _cid(client, "altro")
    assert client.get(f"/api/voice_clone/progress/{rec['id']}").status_code == 403
    assert client.get("/api/voice_clone/progress/vc_nope").status_code == 404


def test_approve_regenerate_reject(client, tmp_path, monkeypatch, ambiente):
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready"):
        vc.transition(rec["id"], s)
    monkeypatch.setattr(vc, "upload_to_r2", lambda r, n: True)
    r = client.post(f"/api/voice_clone/{rec['id']}/regenerate", json={"extra_id": "nope"})
    assert r.status_code == 400
    extra = client.get("/api/voice_clone/demo_texts?locale=it-IT").get_json()["extra"][0]["id"]
    monkeypatch.setattr(vcd, "start_demos", lambda cid, **kw: vc.get(cid))
    r = client.post(f"/api/voice_clone/{rec['id']}/regenerate", json={"extra_id": extra})
    assert r.status_code == 200 and r.get_json()["regen_left"] == 2
    vc.transition(rec["id"], "demos_ready")
    r = client.post(f"/api/voice_clone/{rec['id']}/approve")
    assert r.status_code == 200 and r.get_json()["state"] == "ready"
    assert ambiente[-1][1] == "La tua voce campione è pronta"
    r = client.post(f"/api/voice_clone/{rec['id']}/approve")
    assert r.status_code == 409 and r.get_json()["error_code"] == "bad_state"
    r = client.post(f"/api/voice_clone/{rec['id']}/reject")
    assert r.status_code == 409
    altro = _paid(tmp_path, cid="cid-due", email="b@x.it")
    for s in ("demos_generating", "demo_failed"):
        vc.transition(altro["id"], s)
    _cid(client, "cid-due")
    r = client.post(f"/api/voice_clone/{altro['id']}/reject")
    assert r.status_code == 200 and r.get_json()["state"] == "refunded"
    assert client.post(f"/api/voice_clone/{altro['id']}/reject").status_code == 200


def test_mine_claim_confirm_forget(client, tmp_path, ambiente):
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready", "ready"):
        vc.transition(rec["id"], s)
    d = client.get("/api/voice_clone/mine").get_json()["voices"]
    assert d[0]["id"] == rec["id"] and d[0]["owner"] is True and d[0]["voice_code"]
    _cid(client, "cid-due")
    assert client.get("/api/voice_clone/mine").get_json()["voices"] == []
    r = client.post("/api/voice_clone/claim", json={"voice_code": "ZZZZ-ZZZZ-ZZZZ"})
    assert r.status_code == 404 and r.get_json()["error_code"] == "code_unknown"
    r = client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"].lower()})
    assert r.status_code == 200 and r.get_json()["status"] == "pending"
    codice = vc.get(rec["id"])["pending_confirm"]
    assert ambiente[-1][0] == "u@example.com"
    r = client.post("/api/voice_clone/confirm", json={"voice_code": rec["voice_code"], "confirm_code": "000000"})
    assert r.status_code == 400 and r.get_json()["error_code"] == "confirm_wrong"
    import re
    vero = re.search(r"\b(\d{6})\b", ambiente[-1][2]).group(1)
    r = client.post("/api/voice_clone/confirm", json={"voice_code": rec["voice_code"], "confirm_code": vero})
    assert r.status_code == 200 and r.get_json()["status"] == "ok"
    assert ambiente[-1][1] in ("Nuovo dispositivo autorizzato", "New device authorized")
    mine = client.get("/api/voice_clone/mine").get_json()["voices"]
    assert mine[0]["owner"] is False and "voice_code" not in mine[0]
    assert client.get("/api/voices").get_json()["_mine"][0]["id"] == rec["id"]
    assert client.post(f"/api/voice_clone/{rec['id']}/forget").status_code == 200
    assert client.get("/api/voice_clone/mine").get_json()["voices"] == []
    assert client.post(f"/api/voice_clone/{rec['id']}/resend").status_code == 403


def test_resend_solo_proprietario_e_3_al_giorno(client, tmp_path, ambiente):
    rec = _paid(tmp_path)
    codes = [client.post(f"/api/voice_clone/{rec['id']}/resend").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429] and len(ambiente) == 3


def test_file_audio_solo_autorizzati(client, tmp_path):
    rec = _paid(tmp_path)
    r = client.get(f"/api/voice_clone/{rec['id']}/sample.wav")
    assert r.status_code == 200 and r.mimetype == "audio/wav"
    assert client.get(f"/api/voice_clone/{rec['id']}/demo/common").status_code == 404
    _cid(client, "altro")
    assert client.get(f"/api/voice_clone/{rec['id']}/sample.wav").status_code == 403


def test_pagine_vc(client, tmp_path):
    rec = _paid(tmp_path)
    _cid(client, "cid-nuovo")
    r = client.get(f"/vc/{rec['resume_token']['value']}/resume")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/?vc={rec['id']}")
    assert r.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert any(d["cid"] == "cid-nuovo" and d["via"] == "resume" for d in vc.get(rec["id"])["devices"])
    assert client.get("/vc/nope/resume").status_code == 404
    r = client.get(f"/vc/{rec['manage_token']}/devices")
    assert r.status_code == 200 and b"cid-nuovo" not in r.data and b"resume" in r.data
    r = client.post(f"/vc/{rec['manage_token']}/devices/revoke", data={"cid": "cid-nuovo"})
    assert r.status_code in (200, 302)
    assert not any(d["cid"] == "cid-nuovo" for d in vc.get(rec["id"])["devices"])
    assert client.get(f"/vc/{rec['manage_token']}/delete").status_code == 200
    r = client.post(f"/vc/{rec['manage_token']}/delete")
    assert r.status_code == 200 and vc.get(rec["id"])["state"] == "deleted"
    assert not os.path.isdir(vc.voice_dir(rec["token"]))
    assert client.get(f"/vc/{rec['manage_token']}/devices").status_code == 404
```

Nota sul test `test_pagine_vc`: la pagina dei dispositivi mostra `via` e data, mai il `cid` in chiaro (è un identificativo del browser: si mostra un hash corto `sha256(cid)[:8]`, e il form di revoca usa quello: `revoke_device` va chiamata risolvendo l'hash sui `devices` del record). Se il piano 1 ha dato a `devices_view` un campo `key`/`hash`, usare quello.

- [ ] **Step 2: Eseguire i test e vederli fallire**

Run: `python -m pytest test/test_voice_clone_api.py -v --tb=short`
Expected: FAIL con 404 sugli endpoint / `AttributeError`.

- [ ] **Step 3: Implementazione**

Import (dopo `import voxcpm_ranking`):

```python
import voice_clone
import voice_clone_audio
import voice_clone_demo
import voice_clone_prompts
```

Init (dopo `tts_backend_state.init(_DATA_DIR)`):

```python
voice_clone.init(_DATA_DIR)
voice_clone_audio.init(_DATA_DIR)
```

Helper comuni (prima degli endpoint, dopo `/api/voice_demo`):

```python
# ---------------------------------------------------------------------------
# Voci campionate (spec 2026-09-09, piano 2)
# ---------------------------------------------------------------------------
_VC_ID_RE = re.compile(r"^vc_[A-Za-z0-9_\-]{4,64}$")


def _vc_err(code, msg, status, **extra):
    body = {"error": msg, "error_code": code}
    body.update(extra)
    return jsonify(body), status


def _vc_gate():
    """None se la feature e' attiva, altrimenti la risposta 404."""
    if voxcpm_tts is None or not voice_clone.enabled():
        return _vc_err("voice_clone_disabled", "Voice samples are not available", 404)
    return None


def _vc_rec_or_404(clone_id):
    if not _VC_ID_RE.match(clone_id or ""):
        return None
    return voice_clone.get(clone_id)


def _vc_urls(rec):
    base = BASE_URL or ""
    return {"resume_url": f"{base}/vc/{rec['resume_token']['value']}/resume",
            "manage_url": f"{base}/vc/{rec['manage_token']}/devices",
            "delete_url": f"{base}/vc/{rec['manage_token']}/delete"}


def _vc_view(rec):
    pub = voice_clone.public_view(rec)
    demo = rec.get("demo") or {}
    if demo:
        pub["regen_left"] = max(0, int(demo.get("regen_max") or 0) - int(demo.get("regen_used") or 0))
        pub["extra_id"] = demo.get("extra_id")
    if rec.get("state") in ("demos_ready", "ready"):
        pub["demo_urls"] = {"common": f"/api/voice_clone/{rec['id']}/demo/common",
                            "extra": f"/api/voice_clone/{rec['id']}/demo/extra"}
    return pub


def _vc_log(rec_or_id, op, extra=""):
    cid_pub = rec_or_id["id"] if isinstance(rec_or_id, dict) else rec_or_id
    try:
        _log_activity(cid_pub, extra, op, client_id=_get_client_id(), client_ip=_client_ip())
    except Exception:
        pass


def _vc_demo_texts(locale):
    """Frase comune + frasi extra dedup per testo, dal catalogo (§3.4)."""
    if voxcpm_catalog is None:
        return None
    comune, extra, visti = None, [], set()
    for rec in voxcpm_catalog.voices():
        if rec.get("locale") != locale:
            continue
        for d in rec.get("demos") or []:
            if d.get("common"):
                if comune is None:
                    comune = {"id": d["id"], "text": d.get("text") or ""}
                    visti.add(comune["text"])
                continue
            testo = d.get("text") or ""
            if testo and testo not in visti:
                visti.add(testo)
                extra.append({"id": d["id"], "text": testo})
    if comune is None:
        return None
    extra.sort(key=lambda e: e["id"])
    return {"common": comune, "extra": extra}


def _voice_clone_notify(event, rec, **extra):
    """Eventi da voice_clone_demo / voice_clone.sweep -> email + log."""
    email = rec.get("owner_email") or ""
    lang = rec.get("ui_lang") or "en"
    urls = _vc_urls(rec)
    if event == "demos_ready":
        _vc_log(rec, "VOICE_CLONE_DEMOS_READY")
    elif event == "demo_failed":
        _vc_log(rec, "VOICE_CLONE_DEMO_FAILED", (extra.get("error") or "")[:120])
        print(f"[voice_clone] demo fallita per {rec['id']}: {extra.get('error')}", flush=True)
    elif event == "refunded":
        _vc_log(rec, "VOICE_CLONE_REFUNDED", extra.get("reason") or "")
        if email:
            _email_service.send_voice_clone_refunded(
                email, lang, amount_eur=extra.get("amount_eur") or 0.0,
                method=extra.get("method") or "free", reason=extra.get("reason") or "user_rejected",
                voucher_code=extra.get("voucher_code"),
                voucher_amount=extra.get("bonus_amount") or extra.get("amount_eur"))
    elif event == "expiring":
        _vc_log(rec, "VOICE_CLONE_EXPIRING")
        if email:
            _email_service.send_voice_clone_expiring(email, lang, days=extra.get("days", 30),
                                                     manage_url=urls["manage_url"])
    elif event == "expired":
        _vc_log(rec, "VOICE_CLONE_EXPIRED")
    elif event == "approval_reminder":
        _vc_log(rec, "VOICE_CLONE_REMINDER", str(extra.get("stage")))
        if email:
            _email_service.send_voice_clone_reminder(email, lang, resume_url=urls["resume_url"],
                                                     stage=extra.get("stage", 1))
```

`_email_service` è il nome con cui `audiobook_app` importa `email_service` (riga ~4163: `_email_service.set_funnel_provider`); se il modulo è importato con un altro nome, usare quello. `_log_activity` richiede `request` attivo per `_get_client_id()`: nel notifier chiamato da thread di sfondo non c'è request → `_vc_log` deve catturare `RuntimeError` e loggare con `client_id=""` (il `try/except Exception` sopra lo copre, ma è meglio calcolare `cid`/`ip` dentro un `try` separato e passare stringhe vuote).

Endpoint:

```python
@app.route("/api/voice_clone/config")
def api_vc_config():
    gate = _vc_gate()
    if gate:
        return gate
    g = voice_clone_audio.gate_from_env()
    price = payment.voice_clone_price_eur()
    return jsonify({"enabled": True, "price_eur": price, "free": price <= 0,
                    "max_upload_mb": voice_clone.max_upload_mb(),
                    "regen_max": voice_clone.regen_max(),
                    "languages": voice_clone.offered_languages(),
                    "min_sec": g.min_sec, "max_sec": g.max_sec,
                    "asr": voice_clone_audio.asr_enabled()})


@app.route("/api/voice_clone/prompt")
def api_vc_prompt():
    gate = _vc_gate()
    if gate:
        return gate
    lang = (request.args.get("lang") or "").strip().lower()
    gender = (request.args.get("gender") or "").strip().lower()
    if lang not in voice_clone.offered_languages() or gender not in ("m", "f"):
        return _vc_err("bad_request", "Unknown language or gender", 400)
    text = voice_clone_prompts.prompt_for(lang, gender)
    return jsonify({"text": text, "version": voice_clone_prompts.prompt_version(text),
                    "lang": lang, "gender": gender})


@app.route("/api/voice_clone/sample", methods=["POST"])
def api_vc_sample():
    gate = _vc_gate()
    if gate:
        return gate
    cid = _get_client_id()
    ip = _client_ip()
    ok, retry = _ip_rl_check("vc_sample", ip, 10, 30)
    if ok:
        ok, retry = _ip_rl_check("vc_sample_cid", cid or ip, 10, 10)
    if not ok:
        return _vc_err("rate_limited", "Too many samples, try later", 429, retry_after=retry)
    f = request.files.get("file")
    lang = (request.form.get("lang") or "").strip().lower()
    locale = (request.form.get("locale") or "").strip()
    gender = (request.form.get("gender") or "").strip().lower()
    offerte = voice_clone.offered_languages()
    if f is None or lang not in offerte or locale not in offerte[lang] or gender not in ("m", "f"):
        return _vc_err("bad_request", "Missing file, language, locale or gender", 400)
    ext = (secure_filename(f.filename or "").rsplit(".", 1)[-1].lower() or "webm")[:5]
    if ext not in voice_clone._ACCEPTED_EXT:
        ext = "webm"
    tmp_id = uuid.uuid4().hex
    src = os.path.join(str(UPLOAD_DIR), f"vc_{tmp_id}.{ext}")
    wav = os.path.join(str(UPLOAD_DIR), f"vc_{tmp_id}.wav")
    prompt_text = voice_clone_prompts.prompt_for(lang, gender)
    max_bytes = voice_clone.max_upload_mb() * 1024 * 1024
    try:
        f.save(src)
        if os.path.getsize(src) > max_bytes:
            return _vc_err("too_large", f"Sample over {voice_clone.max_upload_mb()} MB", 413)
        try:
            mt = voice_clone_audio.prepare_sample(src, wav)
        except voice_clone_audio.SampleRejected as e:
            _vc_log("vc_sample", "VOICE_CLONE_SAMPLE_REJECTED", e.reason)
            metrics = getattr(e, "metrics", None)
            return _vc_err("sample_rejected", str(e), 400, reason=e.reason,
                           metrics=(metrics.__dict__ if metrics is not None else {}))
        cer = None
        if voice_clone_audio.asr_enabled():
            try:
                asr = voice_clone_audio.check_transcript(wav, lang, prompt_text)
            except voice_clone_audio.AsrUnavailable as e:
                return _vc_err("asr_unavailable", f"Transcript check unavailable: {e}", 503)
            cer = asr["cer"]
            if cer > voice_clone_audio.max_cer():
                _vc_log("vc_sample", "VOICE_CLONE_SAMPLE_REJECTED", "vc_gate_transcript")
                return _vc_err("sample_rejected", "Transcript does not match", 400,
                               reason="vc_gate_transcript", cer=cer, heard=asr.get("heard", ""))
        rec = voice_clone.create_draft(cid, lang=lang, locale=locale, gender=gender,
                                       prompt_text=prompt_text, sample_wav=wav, original_path=src,
                                       original_ext=ext, metrics=dict(mt.__dict__),
                                       ui_lang=_get_browser_lang() or "en")
        _vc_log(rec, "VOICE_CLONE_SAMPLE_OK")
        return jsonify({"clone_id": rec["id"], "state": rec["state"], "expires_at": rec["expires_at"],
                        "metrics": rec.get("metrics") or {}, "cer": cer})
    finally:
        for p in (src, wav):
            try:
                os.remove(p)
            except OSError:
                pass
```

`SampleRejected(reason, msg, metrics=...)`: usare gli attributi effettivi della classe del piano 1 (`e.reason`, `e.metrics`); `Metrics` è una dataclass → `dataclasses.asdict(mt)` è più corretto di `__dict__` se contiene liste. `create_draft` copia i file: verificare che copi e non sposti (`shutil.copy2`); se sposta, il `finally` è comunque innocuo.

```python
@app.route("/api/voice_clone/demo_texts")
def api_vc_demo_texts():
    gate = _vc_gate()
    if gate:
        return gate
    d = _vc_demo_texts((request.args.get("locale") or "").strip())
    if d is None:
        return _vc_err("bad_request", "No voices for this locale", 400)
    return jsonify(d)


@app.route("/api/voice_clone/commit", methods=["POST"])
def api_vc_commit():
    gate = _vc_gate()
    if gate:
        return gate
    data = request.get_json(silent=True) or {}
    cid = _get_client_id()
    rec = _vc_rec_or_404(str(data.get("clone_id") or ""))
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    e1 = (data.get("email") or "").strip().lower()
    e2 = (data.get("email2") or "").strip().lower()
    if not e1 or "@" not in e1 or e1 != e2:
        return _vc_err("email_mismatch", "The two email addresses differ", 400)
    testi = _vc_demo_texts(rec.get("locale") or "") or {"common": None, "extra": []}
    extra = next((e for e in testi["extra"] if e["id"] == data.get("extra_id")), None)
    if extra is None or testi["common"] is None:
        return _vc_err("bad_request", "Unknown demo phrase", 400)
    price = payment.voice_clone_price_eur()
    try:
        out, created = voice_clone.commit(
            rec["id"], cid, email=e1, extra_id=extra["id"], extra_text=extra["text"],
            common_text=testi["common"]["text"], payment_token=(data.get("payment_token") or "").strip(),
            price_eur=price)
    except voice_clone.EmailHasVoice:
        return _vc_err("email_has_voice", "This email already has a voice sample", 409)
    except voice_clone.VoiceGone:
        return _vc_err("voice_gone", "Voice no longer available", 410)
    except PermissionError:
        return _vc_err("not_authorized", "Not authorized", 403)
    except ValueError as e:
        return _vc_err("payment_invalid", f"Payment not valid: {e}", 402)
    if created:
        _vc_log(out, "VOICE_CLONE_PAID", (out.get("payment") or {}).get("type") or "")
        try:
            voice_clone_demo.start_demos(out["id"])
        except Exception as e:      # noqa: BLE001 - lo sweeper/recover riprendera'
            print(f"[voice_clone] start_demos {out['id']}: {e}", flush=True)
        _email_service.send_voice_clone_paid(
            out["owner_email"], out.get("ui_lang") or "en", voice_code=out["voice_code"],
            amount_eur=(out.get("payment") or {}).get("amount_eur") or 0.0, **_vc_urls(out))
    return jsonify({"clone_id": out["id"], "voice_code": out["voice_code"],
                    "state": out["state"], "created": created})


@app.route("/api/paypal_create_order_voice_clone", methods=["POST"])
def api_paypal_create_order_voice_clone():
    gate = _vc_gate()
    if gate:
        return gate
    if not _paypal_available():
        return jsonify({"error": "PayPal not configured"}), 503
    data = request.get_json(silent=True) or {}
    rec = _vc_rec_or_404(str(data.get("clone_id") or ""))
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    if not voice_clone._has_cid(rec, _get_client_id()):
        return _vc_err("not_authorized", "Not authorized", 403)
    if rec.get("state") != "sample_ok":
        return _vc_err("bad_state", "Voice already paid", 409)
    amount_eur = payment.voice_clone_price_eur()
    if amount_eur <= 0:
        return jsonify({"error": "No payment required"}), 400
    try:
        order = _paypal_create_order(amount_eur, "Voice sample - Audiobook Maker",
                                     custom_id="vc:" + rec["id"])
    except Exception as e:
        print(f"[paypal] voice clone create_order failed: {e}")
        return jsonify({"error": f"PayPal error: {e}"}), 500
    return jsonify({"order_id": order.get("id"), "amount_eur": amount_eur,
                    "status": order.get("status")})


_VC_SSE_END = ("demos_ready", "demo_failed", "ready", "refunded", "expired", "deleted")


@app.route("/api/voice_clone/progress/<clone_id>")
def api_vc_progress(clone_id):
    gate = _vc_gate()
    if gate:
        return gate
    rec = _vc_rec_or_404(clone_id)
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    if not voice_clone._has_cid(rec, _get_client_id()):
        return _vc_err("not_authorized", "Not authorized", 403)

    def stream():
        fine = time.time() + 1800
        while True:
            cur = voice_clone.get(clone_id) or rec
            yield "data: " + json.dumps(_vc_view(cur)) + "\n\n"
            if cur.get("state") in _VC_SSE_END or time.time() > fine:
                return
            time.sleep(2)
    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _vc_action(clone_id, fn):
    gate = _vc_gate()
    if gate:
        return gate
    rec = _vc_rec_or_404(clone_id)
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    try:
        out = fn(rec, _get_client_id())
    except voice_clone_demo.RegenExhausted:
        return _vc_err("regen_exhausted", "No regenerations left", 409)
    except voice_clone.BadTransition:
        return _vc_err("bad_state", "Action not allowed in this state", 409)
    except voice_clone.VoiceGone:
        return _vc_err("voice_gone", "Voice no longer available", 410)
    except PermissionError:
        return _vc_err("not_authorized", "Not authorized", 403)
    return jsonify(_vc_view(out))


@app.route("/api/voice_clone/<clone_id>/approve", methods=["POST"])
def api_vc_approve(clone_id):
    def go(rec, cid):
        out = voice_clone_demo.approve(rec["id"], cid)
        _vc_log(out, "VOICE_CLONE_READY")
        if out.get("owner_email"):
            _email_service.send_voice_clone_ready(
                out["owner_email"], out.get("ui_lang") or "en", voice_code=out["voice_code"],
                manage_url=_vc_urls(out)["manage_url"], delete_url=_vc_urls(out)["delete_url"],
                retention_days=int(voice_clone.retention_sec() // 86400))
        return out
    return _vc_action(clone_id, go)


@app.route("/api/voice_clone/<clone_id>/regenerate", methods=["POST"])
def api_vc_regenerate(clone_id):
    data = request.get_json(silent=True) or {}

    def go(rec, cid):
        testi = _vc_demo_texts(rec.get("locale") or "") or {"extra": []}
        extra = next((e for e in testi["extra"] if e["id"] == data.get("extra_id")), None)
        if extra is None:
            raise _VcBadRequest("Unknown demo phrase")
        out = voice_clone_demo.regenerate(rec["id"], cid, extra_id=extra["id"], extra_text=extra["text"])
        _vc_log(out, "VOICE_CLONE_REGENERATE")
        return out
    try:
        return _vc_action(clone_id, go)
    except _VcBadRequest as e:
        return _vc_err("bad_request", str(e), 400)


class _VcBadRequest(ValueError):
    pass


@app.route("/api/voice_clone/<clone_id>/retry", methods=["POST"])
def api_vc_retry(clone_id):
    return _vc_action(clone_id, lambda rec, cid: voice_clone_demo.retry(rec["id"], cid))


@app.route("/api/voice_clone/<clone_id>/reject", methods=["POST"])
def api_vc_reject(clone_id):
    def go(rec, cid):
        if rec.get("state") == "refunded":
            return rec
        out = voice_clone_demo.reject(rec["id"], cid)
        _vc_log(out, "VOICE_CLONE_REJECTED")
        return out
    return _vc_action(clone_id, go)


@app.route("/api/voice_clone/mine")
def api_vc_mine():
    gate = _vc_gate()
    if gate:
        return gate
    return jsonify({"voices": voice_clone.mine(_get_client_id())})


@app.route("/api/voice_clone/claim", methods=["POST"])
def api_vc_claim():
    gate = _vc_gate()
    if gate:
        return gate
    cid = _get_client_id()
    ok, retry = _ip_rl_check("vc_claim_cid", cid or _client_ip(), 5, 5)
    if not ok:
        return _vc_err("rate_limited", "Too many attempts, try later", 429, retry_after=retry)
    data = request.get_json(silent=True) or {}
    code = voice_clone.normalize_voice_code(str(data.get("voice_code") or ""))
    try:
        esito = voice_clone.claim(code, cid)
    except ValueError as e:
        if "locked" in str(e):
            return _vc_err("code_locked", "Too many wrong codes, try later", 423)
        return _vc_err("code_unknown", "Unknown voice code", 404)
    if esito is None:
        return _vc_err("code_unknown", "Unknown voice code", 404)
    status, rec, confirm_code = esito
    _vc_log(rec, "VOICE_CLONE_CLAIM", status)
    if status == "ok":
        return jsonify({"status": "ok", "voice": _vc_view(rec)})
    if rec.get("owner_email"):
        _email_service.send_voice_clone_confirm(rec["owner_email"], rec.get("ui_lang") or "en",
                                                confirm_code=confirm_code)
    return jsonify({"status": "pending"})


@app.route("/api/voice_clone/confirm", methods=["POST"])
def api_vc_confirm():
    gate = _vc_gate()
    if gate:
        return gate
    cid = _get_client_id()
    data = request.get_json(silent=True) or {}
    code = voice_clone.normalize_voice_code(str(data.get("voice_code") or ""))
    esito = voice_clone.confirm(code, cid, str(data.get("confirm_code") or "").strip())
    if esito == "ok":
        rec = voice_clone.by_voice_code(code)
        _vc_log(rec, "VOICE_CLONE_DEVICE_ADDED")
        if rec.get("owner_email"):
            _email_service.send_voice_clone_device_added(rec["owner_email"], rec.get("ui_lang") or "en",
                                                         devices_url=_vc_urls(rec)["manage_url"])
        return jsonify({"status": "ok", "voice": _vc_view(rec)})
    mappa = {"wrong": ("confirm_wrong", 400), "expired": ("confirm_expired", 410),
             "none": ("confirm_none", 404), "locked": ("code_locked", 423)}
    ec, sc = mappa.get(esito, ("confirm_none", 404))
    return _vc_err(ec, f"Confirmation {esito}", sc)


@app.route("/api/voice_clone/<clone_id>/forget", methods=["POST"])
def api_vc_forget(clone_id):
    gate = _vc_gate()
    if gate:
        return gate
    rec = _vc_rec_or_404(clone_id)
    if rec is None or not voice_clone.forget(clone_id, _get_client_id()):
        return _vc_err("voice_not_found", "Voice not found", 404)
    return jsonify({"ok": True})


def _vc_is_owner(rec, cid):
    dev = (rec.get("devices") or [{}])[0]
    return bool(cid) and dev.get("cid") == cid and dev.get("via") == "creator"


@app.route("/api/voice_clone/<clone_id>/resend", methods=["POST"])
def api_vc_resend(clone_id):
    gate = _vc_gate()
    if gate:
        return gate
    rec = _vc_rec_or_404(clone_id)
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    if not _vc_is_owner(rec, _get_client_id()) or rec.get("state") in voice_clone._TERMINAL:
        return _vc_err("not_authorized", "Only the owner can resend the email", 403)
    ok, retry = _ip_rl_check("vc_resend", clone_id, 3, 3)
    if not ok:
        return _vc_err("rate_limited", "Limit of 3 emails per day reached", 429, retry_after=retry)
    urls = _vc_urls(rec)
    lang = rec.get("ui_lang") or "en"
    if rec.get("state") == "ready":
        sent = _email_service.send_voice_clone_ready(rec["owner_email"], lang, voice_code=rec["voice_code"],
                                                     manage_url=urls["manage_url"], delete_url=urls["delete_url"],
                                                     retention_days=int(voice_clone.retention_sec() // 86400))
    else:
        sent = _email_service.send_voice_clone_paid(rec["owner_email"], lang, voice_code=rec["voice_code"],
                                                    amount_eur=(rec.get("payment") or {}).get("amount_eur") or 0.0,
                                                    **urls)
    _vc_log(rec, "VOICE_CLONE_RESEND")
    return jsonify({"ok": bool(sent)})


def _vc_send_audio(clone_id, name):
    gate = _vc_gate()
    if gate:
        return gate
    rec = _vc_rec_or_404(clone_id)
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    if not voice_clone._has_cid(rec, _get_client_id()):
        return _vc_err("not_authorized", "Not authorized", 403)
    try:
        path = voice_clone._ensure_local(rec, name)
    except Exception:
        path = None
    if not path or not os.path.exists(path):
        return _vc_err("voice_not_found", "File not available", 404)
    return send_file(path, mimetype="audio/wav", conditional=True)


@app.route("/api/voice_clone/<clone_id>/sample.wav")
def api_vc_sample_file(clone_id):
    return _vc_send_audio(clone_id, "sample.wav")


@app.route("/api/voice_clone/<clone_id>/demo/<which>")
def api_vc_demo_file(clone_id, which):
    if which not in ("common", "extra"):
        return _vc_err("voice_not_found", "File not available", 404)
    return _vc_send_audio(clone_id, f"demo_{which}.wav")
```

`_ensure_local(rec, name)` del piano 1: verificare la firma e il valore di ritorno (path o `None`; `SampleUnavailable` su fallimento) e adeguare `_vc_send_audio`. `Response`, `send_file`, `secure_filename`, `uuid`, `json`, `time` sono già importati in `audiobook_app` (verificare `secure_filename`).

Pagine `/vc/*` (HTML inline minimale, inglese, stile coerente con `/dl/<token>`; `data-lang` = `ui_lang`):

```python
def _vc_page(title, body_html, status=200):
    html_doc = (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
                f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                f"<meta name=\"robots\" content=\"noindex,nofollow\"><title>{html.escape(title)}</title>"
                f"<style>body{{font-family:system-ui,sans-serif;max-width:560px;margin:3em auto;padding:0 1em}}"
                f"button{{padding:.6em 1.2em}}table{{border-collapse:collapse}}td{{padding:.3em .8em}}</style>"
                f"</head><body><h1>{html.escape(title)}</h1>{body_html}</body></html>")
    return Response(html_doc, status=status, mimetype="text/html")


def _vc_rec_by_manage(token):
    rec = voice_clone.by_manage_token(token or "")
    if rec is None or rec.get("state") in voice_clone._TERMINAL:
        return None
    return rec


@app.route("/vc/<token>/resume")
def vc_resume(token):
    if _vc_gate():
        abort(404)
    rec = voice_clone.by_resume_token(token)
    if rec is None or rec.get("state") in voice_clone._TERMINAL:
        abort(404)
    cid = _get_client_id()
    if cid and not voice_clone._has_cid(rec, cid):
        with voice_clone._lock:
            devices = list(rec.get("devices") or []) + [{"cid": cid, "added_at": time.time(), "via": "resume"}]
            voice_clone.store().update(rec["id"], {"devices": devices})
        _vc_log(rec, "VOICE_CLONE_RESUME")
    return redirect(f"/?vc={rec['id']}", code=302)


def _vc_device_key(cid):
    return hashlib.sha256((cid or "").encode("utf-8")).hexdigest()[:8]


@app.route("/vc/<token>/devices")
def vc_devices(token):
    if _vc_gate():
        abort(404)
    rec = _vc_rec_by_manage(token)
    if rec is None:
        abort(404)
    righe = ""
    for d in rec.get("devices") or []:
        when = datetime.utcfromtimestamp(float(d.get("added_at") or 0)).strftime("%Y-%m-%d")
        chiave = _vc_device_key(d.get("cid"))
        azione = ("" if d.get("via") == "creator" else
                  f"<form method=\"post\" action=\"/vc/{html.escape(token)}/devices/revoke\" style=\"display:inline\">"
                  f"<input type=\"hidden\" name=\"key\" value=\"{chiave}\"><button>Revoke</button></form>")
        righe += (f"<tr><td>{chiave}</td><td>{html.escape(str(d.get('via') or ''))}</td>"
                  f"<td>{when}</td><td>{azione}</td></tr>")
    body = (f"<p>Devices allowed to use your voice sample.</p>"
            f"<table><tr><th>Device</th><th>Added via</th><th>Date</th><th></th></tr>{righe}</table>"
            f"<p><a href=\"/vc/{html.escape(token)}/delete\">Delete this voice</a></p>")
    return _vc_page("Your voice sample: devices", body)


@app.route("/vc/<token>/devices/revoke", methods=["POST"])
def vc_devices_revoke(token):
    if _vc_gate():
        abort(404)
    rec = _vc_rec_by_manage(token)
    if rec is None:
        abort(404)
    key = (request.form.get("key") or request.form.get("cid") or "").strip()
    for d in rec.get("devices") or []:
        if d.get("via") != "creator" and (d.get("cid") == key or _vc_device_key(d.get("cid")) == key):
            voice_clone.revoke_device(token, d.get("cid"))
            _vc_log(rec, "VOICE_CLONE_DEVICE_REVOKED")
            break
    return redirect(f"/vc/{token}/devices", code=302)


@app.route("/vc/<token>/delete", methods=["GET", "POST"])
def vc_delete(token):
    if _vc_gate():
        abort(404)
    rec = _vc_rec_by_manage(token)
    if rec is None:
        abort(404)
    if request.method == "GET":
        body = (f"<p>This removes your voice sample and every file derived from it. "
                f"Audiobooks already generated are not affected.</p>"
                f"<form method=\"post\"><button>Delete my voice</button></form>")
        return _vc_page("Delete your voice sample", body)
    out = voice_clone.delete_by_owner(token)
    if out is None:
        abort(404)
    _vc_log(out, "VOICE_CLONE_DELETED")
    return _vc_page("Voice deleted", "<p>Your voice sample and its files have been deleted.</p>")
```

In `voice_clone.py` (Task 6 la aggiunge, con test nel file API):

```python
def delete_by_owner(manage_token):
    """§6.6: cancellazione dal link di gestione. Da qualunque stato non
    terminale a `deleted`, file rimossi; None se il token e' ignoto."""
    with _lock:
        rec = by_manage_token(manage_token)
        if rec is None or rec.get("state") in _TERMINAL:
            return None
        if rec.get("state") not in TRANSITIONS or "deleted" not in TRANSITIONS[rec["state"]]:
            # gli stati intermedi non prevedono `deleted` in TRANSITIONS: il
            # proprietario puo' comunque cancellare (§6.6), rimborso escluso
            out = store().update(rec["id"], {"state": "deleted", "deleted_at": time.time()})
        else:
            out = transition(rec["id"], "deleted")
    remove_files(out)
    return out
```

Ruling: la spec §6.6 parla di cancellazione della voce; `TRANSITIONS` del piano 1 ammette `deleted` solo da `ready`. Cancellare da uno stato intermedio è ammesso senza rimborso automatico (l'utente sceglie «Rifiuta» se vuole il rimborso; la pagina di conferma lo dice: aggiungere alla pagina GET la frase «If you have not approved the voice yet and want a refund, reject it from the app instead.»).

`/api/voices`: dopo il blocco `if voxcpm_tts is not None:`:

```python
        try:
            voices["_mine"] = (voice_clone.mine(_get_client_id())
                               if (voxcpm_tts is not None and voice_clone.enabled()) else [])
        except Exception:
            voices["_mine"] = []
```

`X-Robots-Tag`: `if path.startswith('/dl/') or path.startswith('/vc/'):`.

`_ensure_background_threads()`, dopo il blocco `abuse_watch`:

```python
    try:
        voice_clone_demo.configure(notifier=_voice_clone_notify)
        voice_clone.set_hooks(
            notify=_voice_clone_notify,
            relaunch=lambda cid: voice_clone_demo.start_demos(cid),
            refund=lambda cid, reason: voice_clone_demo.refund(
                cid, reason, bonus=(reason == "demo_failed_timeout")))
        _email_service.set_voice_clone_provider(voice_clone.digest_data)
        if voxcpm_tts is not None and voice_clone.enabled():
            n = voice_clone_demo.recover()
            if n:
                print(f"[voice_clone] recover: {n} generazioni demo rilanciate", flush=True)
        threading.Thread(target=_voice_clone_sweep_supervisor, daemon=True,
                         name="voice-clone-sweep").start()
    except Exception as e:      # noqa: BLE001
        print(f"[voice_clone] cablaggio non riuscito: {e}", flush=True)
```

e, accanto a `_cleanup_supervisor`:

```python
def _voice_clone_sweep_supervisor():
    """Sweep del ciclo di vita delle voci campionate, riavviato su crash
    come _cleanup_supervisor (incidente 2026-06-15)."""
    import traceback
    while True:
        try:
            time.sleep(voice_clone.SWEEP_INTERVAL_SEC)
            if voxcpm_tts is None or not voice_clone.enabled():
                continue
            out = voice_clone.sweep()
            if any(out.values()):
                print(f"[voice_clone] sweep: {out}", flush=True)
        except Exception as e:      # noqa: BLE001
            traceback.print_exc()
            print(f"[voice_clone] sweep crashed, restarting: {type(e).__name__}: {e}", flush=True)
            time.sleep(60)
```

- [ ] **Step 4: Eseguire i test**

Run: `python -m pytest test/test_voice_clone_api.py test/test_voxcpm_api.py test/test_voice_clone_demo.py -v --tb=short`
Expected: PASS. Poi `python -m pytest test/ -x -q --tb=short` per la regressione completa (i test lenti che richiedono rete vengono già saltati dalla suite).

- [ ] **Step 5: Commit**

```
python -m py_compile audiobook_app.py
python -m py_compile voice_clone.py
git add audiobook_app.py voice_clone.py test/test_voice_clone_api.py
git commit -m "feat(voice-clone): endpoint del flusso, pagine di gestione, cablaggio dello sweeper"
```

---

### Task 7: Uso della voce nei libri: guard, tag, email, classifica (`audiobook_app`, `generation_engine`)

**Files:**
- Modify: `audiobook_app.py` (`/api/generate` dopo il blocco `voxcpm_not_configured` riga ~10831; `/api/preview_audio` riga ~10276; `_recovery_generate_gate` riga ~1395)
- Modify: `generation_engine.py` (`_friendly_voice_name` riga ~1713; `is_premium` riga ~1736; `_generation_tags` riga ~3903; hook classifica riga ~5524)
- Test: `test/test_voice_clone_generate.py`

**Interfaces:**
- Consumes: `voice_clone.check_use(voice_id, cid, lang, locale)` → `""` | `voice_gone` | `voice_not_authorized` | `voice_lang_mismatch`; `voice_clone.touch_used(clone_id)`; `voice_clone.token_of(voice_id)`; `voice_clone._record_for_voice_id(voice_id)` (o `by_token`); `voxcpm_catalog.MODEL_LABEL`; `voice_utils.is_voxcpm_voice`.
- Produces:
  - `/api/generate`: subito dopo il controllo `voxcpm_not_configured`, se `voice.startswith(voice_clone.VOICE_ID_PREFIX)`: `err = voice_clone.check_use(voice, _get_client_id(), lang, locale)` con `lang` = `(data.get("lang") or "").split("-")[0].lower()` e `locale` = `data.get("locale") or data.get("lang") or ""` (lasciar decidere a `check_use` cosa confrontare: la spec §9 richiede il match di lingua); `voice_gone` → 410, `voice_not_authorized` → 403, `voice_lang_mismatch` → 400, sempre `{"error", "error_code"}`. Poi `voice_clone.touch_used(rec["id"])` (rinnovo retention all'uso, D15) e `job["voice_label"] = "user-voice"`; log `VOICE_CLONE_USED` con l'id pubblico.
  - `/api/preview_audio`: già 400 `voxcpm_preview_unsupported` per ogni voce VoxCPM, incluse `mine` — nessuna modifica, ma un test lo fissa.
  - `_recovery_generate_gate`: `is_vox = _is_voxcpm_voice(voice)`; `if not (is_gem or is_spx or is_vox): return out`; per `is_vox`: `est = voxcpm_tts.estimate_book_cost(chs, language=lang)`, `key = "voxcpm_estimate"`; inoltre, se `voice.startswith(voice_clone.VOICE_ID_PREFIX)`: `err = voice_clone.check_use(voice, rec.get("client_id") or "", lang, rec.get("locale") or lang)` → `_RecoveryRejected(f"voce campione non usabile: {err}")` se non vuoto.
  - `generation_engine._friendly_voice_name`: `mine` → `"Your voice"` (etichetta monolingua in inglese; le email localizzate la traducono nel Task 8 del piano 3 se serve).
  - `generation_engine._generation_details_lines` (riga ~1736): `is_premium = _is_gemini_voice(voice) or _is_speechify_voice(voice) or _is_voxcpm_voice(voice)`.
  - `generation_engine._generation_tags`: nuovo ramo `elif engine == "voxcpm":` prima dell'`else`: `model_label = getattr(voxcpm_catalog, "MODEL_LABEL", "") or "VoxCPM2"`; se `voice_id.startswith("voxcpm:mine:")` → `voice_name = "user-voice"`, `language = voice_clone.language_of(voice_id)` in try (fallback `_audit_language`); altrimenti `voice_name = voxcpm_catalog.parse_voice_id(voice_id)["name"]`, `language = ...["locale"]`. Il modulo importa `voice_clone` e `voxcpm_catalog` (entrambi foglia, nessun ciclo; se `generation_engine` già importa `voxcpm_catalog`, riusarlo).
  - `run_generation`: `if use_voxcpm and not voice.startswith("voxcpm:mine:"): voxcpm_ranking.punto(...)` (le voci personali non entrano in classifica).

- [ ] **Step 1: Test che falliscono**

```python
"""Uso della voce campione nei libri (spec §9)."""
import os

import pytest

import audiobook_app
import community_store
import generation_engine as ge
import storage_backend
import voice_clone as vc
import voxcpm_catalog
import voxcpm_ranking

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave-di-prova")
    voxcpm_catalog.invalidate_cache()
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    audiobook_app._invalidate_voices_cache()
    yield
    voxcpm_catalog.invalidate_cache()


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie(audiobook_app._CLIENT_COOKIE_NAME, "cid-uno")
        yield c


def _ready(tmp_path, cid="cid-uno"):
    import voice_clone_prompts
    s = tmp_path / f"{cid}-s.wav"
    s.write_bytes(b"RIFF")
    o = tmp_path / f"{cid}-o.webm"
    o.write_bytes(b"x")
    rec = vc.create_draft(cid, lang="it", locale="it-IT", gender="f",
                          prompt_text=voice_clone_prompts.prompt_for("it", "f"), sample_wav=str(s),
                          original_path=str(o), original_ext="webm", metrics={}, ui_lang="it")
    rec, _ = vc.commit(rec["id"], cid, email=cid + "@x.it", extra_id="m", extra_text="e",
                       common_text="c", payment_token="", price_eur=0.0)
    for st in ("demos_generating", "demos_ready", "ready"):
        rec = vc.transition(rec["id"], st)
    return rec


def _job(monkeypatch, job_id="JOBVC1"):
    class Ch:
        def __init__(self, i):
            self.index, self.title, self.text, self.char_count, self.word_count = i, f"c{i}", "Testo.", 6, 1

    class Info:
        title, author, language = "Libro", "A", "it"
        chapters = [Ch(0)]
    monkeypatch.setitem(audiobook_app.jobs, job_id, {
        "status": "analyzed", "info": Info(), "client_id": "cid-uno", "created": 0})
    return job_id


def _generate(client, job_id, voice, lang="it"):
    return client.post("/api/generate", json={"job_id": job_id, "voice": voice, "lang": lang,
                                              "output_format": "mp3", "rate": "+0%"})


def test_generate_rifiuta_cid_non_autorizzato(client, tmp_path, monkeypatch):
    rec = _ready(tmp_path, cid="cid-altro")
    jid = _job(monkeypatch)
    r = _generate(client, jid, vc.voice_id_of(rec))
    assert r.status_code == 403 and r.get_json()["error_code"] == "voice_not_authorized"


def test_generate_rifiuta_lingua_diversa(client, tmp_path, monkeypatch):
    rec = _ready(tmp_path)
    jid = _job(monkeypatch)
    r = _generate(client, jid, vc.voice_id_of(rec), lang="en")
    assert r.status_code == 400 and r.get_json()["error_code"] == "voice_lang_mismatch"


def test_generate_rifiuta_voce_sparita(client, tmp_path, monkeypatch):
    rec = _ready(tmp_path)
    vc.transition(rec["id"], "expired")
    jid = _job(monkeypatch)
    r = _generate(client, jid, vc.voice_id_of(rec))
    assert r.status_code == 410 and r.get_json()["error_code"] == "voice_gone"


def test_generate_accetta_e_rinnova_la_retention(client, tmp_path, monkeypatch):
    rec = _ready(tmp_path)
    vc.store().update(rec["id"], {"last_used_at": 1, "expires_at": 2})
    jid = _job(monkeypatch)
    avviati = []
    monkeypatch.setattr(audiobook_app, "run_generation", lambda *a, **k: avviati.append(a), raising=False)
    monkeypatch.setattr(audiobook_app.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda self: avviati.append(k.get("args"))})())
    r = _generate(client, jid, vc.voice_id_of(rec))
    assert r.status_code == 200, r.get_json()
    cur = vc.get(rec["id"])
    assert cur["last_used_at"] > 1 and cur["expires_at"] > 2


def test_preview_non_supportata_per_la_voce_personale(client, tmp_path, monkeypatch):
    rec = _ready(tmp_path)
    jid = _job(monkeypatch)
    r = client.post(f"/api/preview_audio/{jid}", json={"voice": vc.voice_id_of(rec)})
    assert r.status_code == 400 and r.get_json()["error"] == "voxcpm_preview_unsupported"


def test_recovery_gate_rifiuta_voce_non_usabile(tmp_path, monkeypatch):
    rec = _ready(tmp_path)
    vc.transition(rec["id"], "expired")

    class Ch:
        index, title, text, char_count = 0, "c", "Testo.", 6

    class Info:
        title, language = "Libro", "it"
        chapters = [Ch()]
    with pytest.raises(audiobook_app._RecoveryRejected):
        audiobook_app._recovery_generate_gate("J1", {"voice": vc.voice_id_of(rec), "client_id": "cid-uno",
                                                     "lang": "it"}, Info())


def test_recovery_gate_stima_voxcpm(tmp_path, monkeypatch):
    rec = _ready(tmp_path)

    class Ch:
        index, title, text, char_count = 0, "c", "Testo.", 6

    class Info:
        title, language = "Libro", "it"
        chapters = [Ch()]
    monkeypatch.setattr(audiobook_app, "_assert_priced_on_real_text", lambda *a: True)
    monkeypatch.setattr(audiobook_app, "_premium_quota_decision",
                        lambda cid, voice, price, jid: {"is_free": True, "charge_eur": 0.0})
    monkeypatch.setattr(audiobook_app, "_free_quota_log", lambda *a: None, raising=False)
    out = audiobook_app._recovery_generate_gate("J1", {"voice": vc.voice_id_of(rec), "client_id": "cid-uno",
                                                       "lang": "it"}, Info())
    assert out["estimate_key"] == "voxcpm_estimate" and "list_price_eur" in out["estimate"]


def test_tag_e_etichette_della_voce_personale(tmp_path, monkeypatch):
    rec = _ready(tmp_path)
    vid = vc.voice_id_of(rec)
    assert ge._friendly_voice_name(vid) == "Your voice"
    assert ge._friendly_voice_name("voxcpm:v2:it-IT/Stefano") == "Stefano"

    class Info:
        language = "it"
    tags = ge._generation_tags({"voice": vid}, Info(), vid, "+0%")
    assert tags["abm_voice"] == "user-voice" and tags["abm_voice_id"] == vid
    assert tags["abm_model"] == voxcpm_catalog.MODEL_LABEL and tags["abm_language"] == "it"
    tags = ge._generation_tags({"voice": "voxcpm:v2:it-IT/Stefano"}, Info(), "voxcpm:v2:it-IT/Stefano", "+0%")
    assert tags["abm_voice"] == "Stefano" and tags["abm_language"] == "it-IT"


def test_righe_email_considerano_voxcpm_premium(tmp_path):
    rec = _ready(tmp_path)
    righe = ge._generation_details_lines({"voice": vc.voice_id_of(rec), "lang": "it"}, "it")
    testo = "\n".join(righe) if isinstance(righe, list) else str(righe)
    assert "Your voice" in testo or "voce" in testo.lower()


def test_classifica_ignora_le_voci_personali(tmp_path, monkeypatch):
    chiamate = []
    monkeypatch.setattr(voxcpm_ranking, "punto", lambda voice, jid: chiamate.append(voice))
    assert ge._ranking_point_allowed("voxcpm:v2:it-IT/Stefano") is True
    assert ge._ranking_point_allowed("voxcpm:mine:abcdef") is False
```

Il test `test_righe_email_considerano_voxcpm_premium` va adattato alla firma reale di `_generation_details_lines` (leggerla): deve verificare che con una voce VoxCPM la riga «tipo voce» dica premium (chiave i18n usata per Gemini/Speechify), non standard. `test_generate_accetta_e_rinnova_la_retention` deve neutralizzare l'avvio del thread di generazione nel modo che `/api/generate` usa davvero (leggere come lancia `run_generation`; se via `threading.Thread(target=...)`, il monkeypatch sopra basta) e potrebbe dover passare anche `_premium_quota_decision` finto come nel test del gate.

- [ ] **Step 2: Eseguire i test e vederli fallire**

Run: `python -m pytest test/test_voice_clone_generate.py -v --tb=short`
Expected: FAIL (200 invece di 403, `_ranking_point_allowed` assente, tag errati).

- [ ] **Step 3: Implementazione**

`/api/generate`, dopo il blocco `voxcpm_not_configured`:

```python
        if voice.startswith(voice_clone.VOICE_ID_PREFIX):
            _vc_lang = (data.get("lang") or "").strip().split("-")[0].lower()
            _vc_locale = (data.get("locale") or data.get("lang") or "").strip()
            _vc_err_code = voice_clone.check_use(voice, _get_client_id(), _vc_lang, _vc_locale)
            if _vc_err_code:
                _vc_status = {"voice_gone": 410, "voice_not_authorized": 403,
                              "voice_lang_mismatch": 400}.get(_vc_err_code, 400)
                return jsonify({"error": f"Voice sample not usable: {_vc_err_code}",
                                "error_code": _vc_err_code}), _vc_status
```

e, dopo `_check_job_owner` (quando `job` è noto), prima di avviare il thread:

```python
    if voice.startswith(voice_clone.VOICE_ID_PREFIX):
        _vc_rec = voice_clone._record_for_voice_id(voice)
        if _vc_rec is not None:
            voice_clone.touch_used(_vc_rec["id"])
            job["voice_label"] = "user-voice"
            _vc_log(_vc_rec, "VOICE_CLONE_USED", job_id)
```

Se `check_use` del piano 1 confronta `locale` con `rec["locale"]` in modo stretto e il frontend manda solo `lang`, passare `locale=rec_locale` (ricavato dal record) e lasciare il confronto sulla sola lingua: la spec §9 chiede `voice_lang_mismatch` sulla lingua del libro. Ruling: si confronta la lingua (`lang`), il locale è informativo.

`_recovery_generate_gate`:

```python
    is_gem = _is_gemini_voice(voice)
    is_spx = _is_speechify_voice(voice)
    is_vox = _is_voxcpm_voice(voice)
    if not (is_gem or is_spx or is_vox):
        return out
    ...
    if is_gem:
        ...
    elif is_spx:
        est = speechify_tts.estimate_book_cost(chs, language="en")
        key = "speechify_estimate"
    else:
        if voxcpm_tts is None:
            raise _RecoveryRejected("modulo voxcpm_tts non disponibile")
        if voice.startswith(voice_clone.VOICE_ID_PREFIX):
            _err = voice_clone.check_use(voice, (rec.get("client_id") or "").strip(), lang,
                                         rec.get("locale") or lang)
            if _err:
                raise _RecoveryRejected(f"voce campione non usabile: {_err}")
        est = voxcpm_tts.estimate_book_cost(chs, language=lang)
        key = "voxcpm_estimate"
```

`generation_engine.py`:

```python
# _friendly_voice_name, ramo mine:
        if len(parti) >= 2 and parti[1] == "mine":
            return "Your voice"

# _generation_details_lines:
    is_premium = _is_gemini_voice(voice) or _is_speechify_voice(voice) or _is_voxcpm_voice(voice)

# _generation_tags, prima dell'else Edge/Google:
        elif engine == "voxcpm":
            try:
                import voxcpm_catalog as _vcat
                model_label = getattr(_vcat, "MODEL_LABEL", "") or "VoxCPM2"
                if voice_id.startswith("voxcpm:mine:"):
                    import voice_clone as _vcl
                    voice_name = "user-voice"
                    language = _vcl.language_of(voice_id) or ""
                else:
                    _rec = _vcat.parse_voice_id(voice_id)
                    voice_name = _rec.get("name") or voice_id
                    language = _rec.get("locale") or ""
            except Exception:
                pass

# helper + hook classifica:
def _ranking_point_allowed(voice):
    """Le voci personali (voxcpm:mine:) non entrano nella classifica d'uso."""
    return _is_voxcpm_voice(voice) and not (voice or "").startswith("voxcpm:mine:")

    if use_voxcpm and _ranking_point_allowed(voice):
        try:
            voxcpm_ranking.punto(voice, job_id)
        ...
```

Gli import locali dentro `_generation_tags` evitano di toccare l'ordine degli import di modulo; se `generation_engine` importa già `voxcpm_catalog` a livello di modulo, usare quello.

- [ ] **Step 4: Eseguire i test**

Run: `python -m pytest test/test_voice_clone_generate.py test/test_voxcpm_api.py test/test_generation_tags.py -v --tb=short` (se `test_generation_tags.py` non esiste: `python -m pytest test/ -k "tags or voxcpm or recover" -q --tb=short`)
Expected: PASS.

- [ ] **Step 5: Commit**

```
python -m py_compile audiobook_app.py
python -m py_compile generation_engine.py
git add audiobook_app.py generation_engine.py test/test_voice_clone_generate.py
git commit -m "feat(voice-clone): guard di generazione, tag audio ed esclusione dalla classifica"
```

---

### Task 8: Documentazione della configurazione (`md_files/PARAMETRI_CONFIGURAZIONE.md`)

**Files:**
- Modify: `md_files/PARAMETRI_CONFIGURAZIONE.md` (sezione delle variabili VoxCPM / voci campionate del piano 1, se esiste; altrimenti nuova sottosezione «Voci campionate (piano 2)»)

**Interfaces:** nessuna.

- [ ] **Step 1: Leggere la sezione esistente**

Run: `Select-String -Path md_files/PARAMETRI_CONFIGURAZIONE.md -Pattern "VOICE_CLONE" | Select-Object -First 20`
Se il piano 1 ha già una sezione con `ABM_VOICE_CLONE_MIN_SEC`, `ABM_VOICE_CLONE_ASR`, `ABM_VOICE_CLONE_SAMPLE_TTL_*`, `ABM_VOICE_CLONE_RETENTION_*`, aggiungere in coda alla stessa tabella; altrimenti creare la tabella con lo stesso formato delle altre sezioni (variabile, descrizione, default, file:riga).

- [ ] **Step 2: Aggiungere le righe**

| Variabile | Descrizione | Default | Sorgente |
|-----------|-------------|---------|----------|
| `ABM_VOICE_CLONE_ENABLED` | Interruttore della feature voci campionate. `0`/`false`/`no`/`off` spengono gli endpoint `/api/voice_clone/*` (404 `voice_clone_disabled`), la chiave `_mine` di `/api/voices`, lo sweeper e il recovery. | `1` | `voice_clone.py` (`enabled()`) |
| `ABM_EUR_CLONED_VOICE` | Prezzo fisso in EUR della voce campione (§7.1); virgola decimale ammessa; `<= 0` = gratis (pannello pagamento saltato, `payment.type="free"`). | `5.00` | `payment.py` (`EUR_CLONED_VOICE`, `voice_clone_price_eur()`) |
| `ABM_VOICE_CLONE_MAX_UPLOAD_MB` | Dimensione massima del campione caricato (413 `too_large` oltre). Minimo 1. | `20` | `voice_clone.py` (`max_upload_mb()`) |
| `ABM_VOICE_CLONE_REGEN_MAX` | Rigenerazioni delle demo concesse per voce (409 `regen_exhausted` oltre). Minimo 0. | `3` | `voice_clone.py` (`regen_max()`) |
| `ABM_VOICE_CLONE_DEMO_RETRIES` | Tentativi per ogni frase demo sul worker prima di `demo_failed` (pausa 2^n s, tetto 30 s). Minimo 1. | `3` | `voice_clone.py` (`demo_retries()`) |

Aggiungere sotto la tabella un paragrafo «Costanti interne (non configurabili)» con: `SWEEP_INTERVAL_SEC` 3600, `EXPIRY_WARN_SEC` 30 giorni, `DEMO_FAILED_RELAUNCH_SEC` 6 h, `DEMO_FAILED_REFUND_SEC` 7 giorni, `APPROVAL_REMINDER_SEC` 24 h e 7 giorni, `APPROVAL_REFUND_SEC` 30 giorni, `RECORD_PURGE_SEC` 90 giorni, `RESUME_TOKEN_DAYS` 30, `CONFIRM_TTL_SEC` 900, `CONFIRM_MAX_TRIES` 5, `CONFIRM_LOCK_SEC` 900; rate limit `vc_sample` 10/h per cid e 30/h per IP, `vc_claim_cid` 5/h, `vc_resend` 3/giorno per voce (tutti in `audiobook_app.py`, `_ip_rl_check`); log `VOICE_CLONE_*` nell'activity log con il solo id pubblico.

- [ ] **Step 3: Commit**

```
git add -f md_files/PARAMETRI_CONFIGURAZIONE.md
git commit -m "docs(voice-clone): variabili e costanti del flusso della voce campione"
```

---

## Self-review

**Copertura spec:** §3.4 (Task 2, 6: email doppia, unicità, demo_texts, PayPal/voucher, commit, email §8.1); §3.5 (Task 3, 6: SSE, approva, rigenera con contatore, rifiuta con rimborso, demo_failed → retry/rifiuto); §3.6 (Task 6: `/api/voice_clone/mine`, resume link autorizza il cid); §3.7 (Task 6: claim/confirm, forget, resend 3/giorno solo proprietario); §3.8 (Task 6: `_mine` in `/api/voices`; l'optgroup è del piano 3); §5.5 (Task 3: nomi file, `demo_try_*` cancellati all'approvazione, R2); §6.5 (Task 4: avviso 30 giorni, scadenza, record 90 giorni); §6.6 (Task 6: `/vc/<manage_token>/delete` con conferma → `deleted`); §7.1 (Task 1); §7.2 (Task 1, 2, 6: consuma poi scrivi, rollback, doppio click 200, `custom_id="vc:"+id`); §7.4 (Task 3: rifiuto solo da `demos_ready`/`demo_failed`, voucher silenzioso vs PayPal con buono, idempotenza); §8 (Task 5, 6: cinque email + promemoria + rimborso; link resume/devices/delete; 404 su token ignoto/terminale); §9 (Task 2, 6, 7: `_mine` per richiesta, 403/400/410, `last_used_at`, tag «user-voice», log con id pubblico); §10 (Task 3, 4, 6: retry → `demo_failed` + admin print + rilancio 6 h + rimborso 7 giorni; `sample_unusable` → rimborso immediato; promemoria 24 h/7 d e rimborso 30 giorni; lock sui commit paralleli; 409 `email_has_voice` prima del consumo); §12 (Task 6: rate limit; Task 4-5: digest); §14 (Task 2, 8).
**Placeholder:** nessun «TBD»/«simile al task N»; ogni step di codice ha il codice. Le traduzioni fr/es/de/zh/hi delle email sono affidate all'implementer del Task 5 con testo italiano e inglese di riferimento: il test verifica presenza, chiavi e assenza di nomi di provider.
**Coerenza dei tipi:** `commit()` → `(rec, created)` usato uguale in Task 2/6; `start_demos(clone_id, *, background=True)` in Task 3/4-hook/6; `refund(clone_id, reason, *, bonus=False)` in Task 3/4-hook/6; notifier `(event, rec, **extra)` in Task 3/4/6; `send_voice_clone_*` firme identiche fra Task 5 e 6; `digest_data()` → `{"window_hours","rows","active_ready"}` fra Task 4 e 5; `check_use` → stringa vuota o codice in Task 7 come nel piano 1; `_STAMP_ON_ENTER["demos_ready"]` aggiunto nel Task 3 e usato nel Task 4.
