"""Il prezzo VoxCPM lungo i quattro punti dove i soldi si muovono.

La prova che conta e' l'ultima: stima e generazione devono dire la stessa
cosa. Quando divergono nasce l'incidente "402 Speechify" (UI gratis, backend
402, job fermo a 0%).
"""
import os

import pytest

import audiobook_app
import free_quota
import payment
import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
VOCE = "voxcpm:v2:it-IT/Stefano"


class Cap:
    def __init__(self, index, text):
        self.index = index
        self.text = text
        # Servono a /api/generate (selected_chars = sum(ch.char_count ...)),
        # non solo a /api/combined_estimate: senza questi i nuovi test sul
        # ramo di generazione vera (Fix round 1) esplodono con AttributeError.
        self.char_count = len(text)
        self.word_count = max(1, len(text.split()))


class Info:
    language = "it"

    def __init__(self, capitoli):
        self.chapters = capitoli


@pytest.fixture
def motore(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave")
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "4.00")
    monkeypatch.setenv("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.50")
    monkeypatch.setenv("ABM_VOXCPM_MIN_COST_EUR", "0.50")
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    voxcpm_catalog.invalidate_cache()
    audiobook_app._invalidate_voices_cache()
    yield
    voxcpm_catalog.invalidate_cache()
    audiobook_app._invalidate_voices_cache()


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        yield c


@pytest.fixture
def job_grande(motore):
    """Job con 250.000 caratteri: a 4,00 EUR/Mchar fa 1,00 EUR, sopra soglia."""
    jid = "job-vox-1"
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[jid] = {
            "info": Info([Cap(0, "a" * 100_000), Cap(1, "b" * 150_000)]),
            "client_id": "cid-vox", "status": "analyzed",
        }
    yield jid
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop(jid, None)


@pytest.fixture
def job_piccolo(motore):
    """25.000 caratteri: 0,10 EUR, sotto soglia."""
    jid = "job-vox-2"
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[jid] = {
            "info": Info([Cap(0, "a" * 25_000)]),
            "client_id": "cid-vox2", "status": "analyzed",
        }
    yield jid
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop(jid, None)


def stima(client, job_id, **extra):
    corpo = {"job_id": job_id, "voice_id": VOCE, "ai_opt_enabled": False}
    corpo.update(extra)
    return client.post("/api/combined_estimate", json=corpo).get_json()


def test_la_stima_espone_il_prezzo_voxcpm(client, job_grande):
    d = stima(client, job_grande)
    assert d["voxcpm_eur"] == 1.00
    assert d["total_eur"] == 1.00
    assert d["is_free"] is False
    assert d["gemini_eur"] == 0.0 and d["speechify_eur"] == 0.0


def test_il_dettaglio_dice_caratteri_e_modello(client, job_grande):
    b = stima(client, job_grande)["voxcpm_breakdown"]
    assert b["chars"] == 250_000
    assert b["chars_total"] == 250_000
    assert b["model_label"] == "VoxCPM2"
    assert b["is_free"] is False


def test_sotto_soglia_la_stima_dice_gratis(client, job_piccolo):
    d = stima(client, job_piccolo)
    assert d["is_free"] is True
    assert d["total_eur"] == 0.0
    assert d["threshold_eur"] == 0.50


def test_la_soglia_e_quella_di_voxcpm(client, job_grande, monkeypatch):
    # Il cuore dell'incidente "402 Speechify": se qui si leggesse la soglia
    # Gemini, un totale fra le due soglie sarebbe gratis per la UI e 402 per
    # il backend.
    monkeypatch.setenv("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.80")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.20")
    assert stima(client, job_grande)["threshold_eur"] == 0.80


def test_la_quota_gratuita_compare_nella_stima(client, job_piccolo):
    d = stima(client, job_piccolo)
    assert d["free_quota"] is not None
    assert d["quota_exhausted"] is False


def test_solo_i_selezionati_entrano_nel_conto(client, job_grande):
    d = stima(client, job_grande, selected_chapters=[0])
    assert d["voxcpm_breakdown"]["chars"] == 100_000
    assert d["voxcpm_eur"] == 0.40


def test_la_stima_non_e_confusa_dall_ottimizzazione(client, job_grande):
    d = stima(client, job_grande, ai_opt_enabled=True)
    # Sul ramo premium combinato la quota LLM resta grezza e si somma: e' la
    # regola gia' in vigore per Gemini e Speechify, non una nuova.
    assert d["llm_eur"] > 0
    assert d["voxcpm_eur"] == 1.00


def test_l_ordine_paypal_rifiuta_un_importo_diverso(client, job_grande):
    r = client.post("/api/paypal_create_order_gemini",
                    json={"job_id": job_grande, "voice_id": VOCE,
                          "amount_eur": 0.10})
    assert r.status_code == 400


def test_generate_rifiuta_voxcpm_non_configurato(client, job_grande, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "")
    r = client.post("/api/generate",
                    json={"job_id": job_grande, "voice": VOCE})
    assert r.status_code == 400
    assert r.get_json()["error"] == "voxcpm_not_configured"


def test_l_anteprima_non_esiste_per_voxcpm(client, motore):
    # §5.2: l'anteprima e' sostituita dall'ascolto del campione. Senza questo
    # rifiuto esplicito la voce cadrebbe nel ramo Edge e verrebbe letta da
    # un'altra voce, che e' peggio di un errore.
    r = client.get(f"/api/preview_audio/nessuno?voice={VOCE}")
    assert r.status_code == 400
    assert r.get_json()["error"] == "voxcpm_preview_unsupported"


def test_il_cap_caratteri_e_quello_di_voxcpm(motore, monkeypatch):
    monkeypatch.setenv("ABM_MAX_VOXCPM_TEXT_CHARS", "1234")
    import importlib
    importlib.reload(audiobook_app)
    assert audiobook_app._max_text_chars_for_voice(VOCE) == 1234
    # Il reload sotto va fatto SENZA la env var, non con essa ancora attiva:
    # monkeypatch la ripristina solo a fine test (dopo il return), quindi un
    # secondo reload qui dentro la vedrebbe di nuovo "1234" e il modulo
    # resterebbe con MAX_VOXCPM_TEXT_CHARS=1234 per il resto della sessione
    # di test (era un bug di isolamento: rotto ogni test successivo che
    # generasse con la voce VoxCPM senza aspettarsi quel cap).
    monkeypatch.delenv("ABM_MAX_VOXCPM_TEXT_CHARS", raising=False)
    importlib.reload(audiobook_app)


def test_stima_e_addebito_dicono_lo_stesso_numero(client, job_grande):
    # L'invariante che l'incidente ha prodotto: un solo punto di decisione.
    import free_quota
    d = stima(client, job_grande)
    dec = free_quota.decision("cid-vox", VOCE, 1.00, job_grande)
    assert d["total_eur"] == dec["due_eur"]
    assert d["is_free"] == dec["is_free"]


# ---------------------------------------------------------------------------
# /api/generate: stima e addebito devono dire lo stesso numero anche qui, non
# solo in /api/combined_estimate (Fix round 1, task-10-report.md).
# ---------------------------------------------------------------------------

class _SyncThread:
    """Thread sincrono: il pocket job["payment"] e il consumo di free_quota
    avvengono PRIMA di thread.start() nella route, quindi non serve per le
    asserzioni sotto — ma evita un thread daemon reale (rete VoxCPM finta)
    che sopravviverebbe al test."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


@pytest.fixture
def no_real_generation(monkeypatch, tmp_path):
    monkeypatch.setattr(audiobook_app, "run_generation", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_admin_notify_generation", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app.threading, "Thread", _SyncThread)
    # Isola gli store di pagamento reali: _PAYMENTS_FILE/_VOUCHERS_FILE/
    # _PAID_JOBS_DONE_FILE sono calcolati da payment.py all'import (prima che
    # ABM_DATA_DIR=tmp_path della fixture `motore` esista), quindi senza
    # questo i test scrivono/leggono i file veri di sviluppo e si sporcano a
    # vicenda fra run diversi (_paid_jobs_done in particolare e' una lista in
    # memoria mai svuotata fra test).
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")


def _post_generate(client, job_id, **extra):
    payload = {"job_id": job_id, "voice": VOCE, "rate": "+0%",
               "output_format": "m4b", "lang": "it"}
    payload.update(extra)
    return client.post("/api/generate", json=payload)


def test_generate_402_dice_lo_stesso_numero_della_stima(client, job_grande, no_real_generation):
    d = stima(client, job_grande)
    assert d["is_free"] is False

    client.set_cookie("abm_cid", "cid-vox")  # owner del job_grande
    r = client.post("/api/generate", json={
        "job_id": job_grande, "voice": VOCE, "rate": "+0%",
        "output_format": "m4b", "lang": "it",
    })
    assert r.status_code == 402, r.get_data(as_text=True)
    body = r.get_json()
    assert body["error_code"] in ("payment_required", "free_quota_exhausted")
    assert body["total_eur"] == pytest.approx(d["total_eur"])


def test_generate_sotto_soglia_parte_gratis_e_muove_la_quota(client, job_piccolo, no_real_generation):
    cid = "cid-vox2"  # client_id fissato da job_piccolo
    assert free_quota.used_eur(cid) == pytest.approx(0.0)
    d = stima(client, job_piccolo)
    assert d["is_free"] is True
    list_price = voxcpm_tts.estimate_book_cost(
        audiobook_app.jobs[job_piccolo]["info"].chapters, language="it"
    )["list_price_eur"]

    client.set_cookie("abm_cid", cid)
    r = client.post("/api/generate", json={
        "job_id": job_piccolo, "voice": VOCE, "rate": "+0%",
        "output_format": "m4b", "lang": "it",
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["status"] == "started"
    # La quota gratuita cumulativa si e' davvero mossa, non solo la stima.
    assert free_quota.used_eur(cid) == pytest.approx(list_price, abs=0.01)
    # Nessun pagamento: coerente col ramo free di Gemini/Speechify.
    assert "payment" not in audiobook_app.jobs[job_piccolo]


def test_generate_pagato_registra_voxcpm_est_e_purpose(client, job_grande, no_real_generation):
    """Caso a pagamento (voucher): job["payment"]["voxcpm_est"] deve essere
    popolato (serve all'audit Task 11) e purpose="voxcpm" deve arrivare a
    consume_payment_token, non "speechify" (sono due motori diversi che
    condividono lo stesso ramo di codice in /api/generate)."""
    code, _v = payment._create_voucher("u@x.it", 100.0, kind="test", note="t")
    client.set_cookie("abm_cid", "cid-vox")  # owner del job_grande
    r = client.post("/api/generate", json={
        "job_id": job_grande, "voice": VOCE, "rate": "+0%",
        "output_format": "m4b", "lang": "it",
        "payment_token": code,
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    job = audiobook_app.jobs[job_grande]
    assert job["payment"]["voxcpm_est"] is not None
    assert job["payment"]["voxcpm_est"]["user_price_eur"] == pytest.approx(1.00)
    purposes = [rec["purpose"] for rec in payment._paid_jobs_done
                if rec["job_id"] == job_grande]
    assert purposes == ["voxcpm"]
