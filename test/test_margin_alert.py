"""Rilevatore a consuntivo sul margine dei job PREMIUM.

Due allarmi indipendenti, entrambi POST-MORTEM (il job e' gia' finito, non
viene mai interrotto):

1) `free_over_threshold` — un job servito GRATIS perche' quotato sotto la
   soglia di gratuita' e' costato piu' della soglia stessa. E' la firma
   dell'incidente Q9lQN3RrapCvGLSonVnzmA (stima falsata su testi spillati ->
   listino 0,35 EUR -> gratis -> costo reale a doppia cifra).
2) `margin_drop` — il margine reale e' sceso a meta' o meno dell'atteso.

L'anti-rumore (ABM_MARGIN_ALERT_MIN_EUR) e' parte del contratto: senza, ogni
job da pochi centesimi produrrebbe un allarme percentualmente vero e
operativamente inutile.
"""
import pytest

import generation_engine
from epub_to_tts import BookInfo, Chapter

THRESHOLD = 0.50


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def _fake(job_id, kind, provider, **kw):
        calls.append({"job_id": job_id, "kind": kind, "provider": provider, **kw})

    monkeypatch.setattr(generation_engine.email_service,
                        "admin_notify_margin_anomaly", _fake)
    for var in ("ABM_MARGIN_ALERT", "ABM_MARGIN_ALERT_MIN_EUR",
                "ABM_MARGIN_ALERT_DROP_PCT", "ABM_FREE_JOB_COST_ALERT_FACTOR"):
        monkeypatch.delenv(var, raising=False)
    return calls


def _job(title="Libro"):
    ch = Chapter(index=0, title="C0", text="x" * 100)
    return {"info": BookInfo(title=title, author="A", language="it", chapters=[ch],
                             total_words=1, total_chars=100,
                             estimated_duration_minutes=1.0)}


def _rec(charged=0.0, cost_est=0.0, cost_actual=0.0, list_actual=0.0):
    return {
        "user_price_eur_charged": charged,
        "google_cost_eur_est": cost_est,
        "google_cost_eur_actual": cost_actual,
        "user_price_eur_should_have_been": list_actual,
        "chars_total": 50000,
        "outcome": "completed",
    }


def _run(rec, est=None, provider="gemini"):
    generation_engine._check_margin_anomalies(
        "JOBTEST", _job(), rec, est or {}, provider, THRESHOLD)


# --- 1) Job gratuito sopra la soglia che lo ha reso gratuito ---------------

def test_job_gratis_costato_piu_della_soglia_notifica(sent):
    # Forma dell'incidente: quotato 0,35 EUR (sotto soglia -> gratis), stima
    # costo ~0 perche' calcolata su testo vuoto, costo reale a doppia cifra.
    _run(_rec(charged=0.0, cost_est=0.001, cost_actual=8.40, list_actual=11.20),
         est={"user_price_eur": 0.35})
    assert len(sent) == 1, "job gratuito costato 8,40 EUR deve allertare"
    assert sent[0]["kind"] == "free_over_threshold"
    assert sent[0]["cost_actual_eur"] == pytest.approx(8.40)
    assert sent[0]["threshold_eur"] == pytest.approx(THRESHOLD)


def test_job_gratis_sfonda_soglia_solo_sul_listino(sent):
    # Il listino sui consumi reali e' la grandezza omogenea alla soglia:
    # scatta anche se il costo vivo resta sotto.
    _run(_rec(charged=0.0, cost_est=0.10, cost_actual=0.30, list_actual=0.95),
         est={"user_price_eur": 0.40})
    assert [c["kind"] for c in sent] == ["free_over_threshold"]


def test_job_gratis_entro_soglia_non_notifica(sent):
    _run(_rec(charged=0.0, cost_est=0.12, cost_actual=0.14, list_actual=0.42),
         est={"user_price_eur": 0.40})
    assert sent == [], "job gratuito rimasto sotto soglia: nessun allarme"


def test_un_solo_allarme_per_job(sent):
    # Un gratuito sfondato soddisfa anche margin_drop: non deve arrivare
    # una seconda email sullo stesso evento.
    _run(_rec(charged=0.0, cost_est=0.0, cost_actual=9.00, list_actual=12.00),
         est={"user_price_eur": 0.35})
    assert len(sent) == 1


# --- 2) Margine crollato su job pagato ------------------------------------

def test_margine_dimezzato_su_job_pagato_notifica(sent):
    # Atteso 4,00 - 1,00 = 3,00; reale 4,00 - 3,20 = 0,80 -> 27% dell'atteso.
    _run(_rec(charged=4.00, cost_est=1.00, cost_actual=3.20, list_actual=4.10))
    assert [c["kind"] for c in sent] == ["margin_drop"]
    assert sent[0]["margin_expected_eur"] == pytest.approx(3.00)
    assert sent[0]["margin_actual_eur"] == pytest.approx(0.80)


def test_margine_nella_norma_non_notifica(sent):
    # Costo reale di poco sopra la stima: margine 2,90 su 3,00 attesi.
    _run(_rec(charged=4.00, cost_est=1.00, cost_actual=1.10, list_actual=4.05))
    assert sent == []


def test_costo_reale_sotto_stima_non_notifica(sent):
    _run(_rec(charged=4.00, cost_est=1.00, cost_actual=0.40, list_actual=3.80))
    assert sent == []


def test_scostamento_irrilevante_non_notifica(sent):
    # Margine atteso 0,04 -> reale 0,00: -100% ma appena 4 centesimi.
    # L'anti-rumore deve tenerlo fuori.
    _run(_rec(charged=0.60, cost_est=0.56, cost_actual=0.60, list_actual=0.61))
    assert sent == [], "scostamento sotto ABM_MARGIN_ALERT_MIN_EUR: nessun allarme"


def test_soglia_min_eur_configurabile(monkeypatch, sent):
    monkeypatch.setenv("ABM_MARGIN_ALERT_MIN_EUR", "0.01")
    _run(_rec(charged=0.60, cost_est=0.56, cost_actual=0.60, list_actual=0.61))
    assert [c["kind"] for c in sent] == ["margin_drop"]


def test_kill_switch(monkeypatch, sent):
    monkeypatch.setenv("ABM_MARGIN_ALERT", "0")
    _run(_rec(charged=0.0, cost_est=0.0, cost_actual=9.00, list_actual=12.00),
         est={"user_price_eur": 0.35})
    assert sent == []


def test_speechify_usa_lo_stesso_rilevatore(sent):
    _run(_rec(charged=0.0, cost_est=0.02, cost_actual=2.10, list_actual=3.00),
         est={"user_price_eur": 0.30}, provider="speechify")
    assert [c["provider"] for c in sent] == ["speechify"]


def test_errore_interno_non_propaga(sent):
    # Il rilevatore e' contabilita' accessoria: non deve mai far fallire
    # l'audit del job che lo ospita.
    generation_engine._check_margin_anomalies("JOBTEST", {}, None, {}, "gemini", 0.5)
    assert sent == []
