"""Il record di audit di un job VoxCPM.

Il costo qui e' tempo di GPU, non una fattura: si verifica che finisca nel
campo che l'aggregato legge come costo vivo, e che i secondi di GPU restino
scritti per poter ricalcolare domani.
"""
import json
import os

import pytest

import generation_engine
import gemini_cost_audit

VOCE = "voxcpm:v2:it-IT/Stefano"


@pytest.fixture
def audit_isolato(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "4.00")
    monkeypatch.setenv("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.50")
    return tmp_path


def leggi(dir_dati):
    righe = []
    for fp in sorted(dir_dati.glob("gemini_cost_audit_*.jsonl")):
        with open(fp, encoding="utf-8") as f:
            righe.extend(json.loads(r) for r in f if r.strip())
    return righe


def job_finito(charged=1.00):
    return {
        "voxcpm_actual": {"chars": 250_000, "audio_seconds": 9000.0,
                          "tts_seconds": 315.0, "jobs": 12, "redone": 1,
                          "bounced": 3, "failed_chunks": 0},
        "payment": {"total_eur": charged, "method": "paypal",
                    "source": "order", "token": "tok-1234567890"},
        "rate": "+0%",
    }


def test_il_record_dichiara_il_provider(audit_isolato):
    generation_engine._write_voxcpm_audit("job-1", job_finito(), VOCE, "it",
                                          "completed")
    r = leggi(audit_isolato)[0]
    assert r["provider"] == "voxcpm"
    assert r["model_key"] == "v2"
    assert r["outcome"] == "completed"
    assert r["language"] == "it"


def test_il_costo_gpu_va_nel_campo_del_costo_vivo(audit_isolato):
    # 250.000 caratteri a $0,91/Mchar = $0,2275, convertiti in EUR.
    r = generation_engine._write_voxcpm_audit("job-1", job_finito(), VOCE,
                                              "it", "completed") or leggi(audit_isolato)[0]
    r = leggi(audit_isolato)[0]
    assert 0.15 < r["google_cost_eur_actual"] < 0.25
    assert r["user_price_eur_charged"] == 1.00
    assert r["margin_eur_actual"] == round(1.00 - r["google_cost_eur_actual"], 4)


def test_i_secondi_di_gpu_restano_scritti(audit_isolato):
    # Il costo e' una stima ancorata a una misura: se il prezzo della scheda
    # cambia, l'audit storico si ricalcola solo se i secondi ci sono.
    generation_engine._write_voxcpm_audit("job-1", job_finito(), VOCE, "it",
                                          "completed")
    r = leggi(audit_isolato)[0]
    assert r["gpu_seconds"] == 315.0
    assert r["cost_usd_per_mchar"] == 0.91
    assert r["worker_jobs"] == 12
    assert r["worker_bounced"] == 3


def test_il_dovuto_si_ricalcola_dai_caratteri_reali(audit_isolato):
    generation_engine._write_voxcpm_audit("job-1", job_finito(charged=0.40),
                                          VOCE, "it", "completed")
    r = leggi(audit_isolato)[0]
    assert r["user_price_eur_should_have_been"] == 1.00
    assert r["delta_eur"] == 0.60      # 1,00 dovuto - 0,40 incassato


def test_una_voce_di_un_altro_motore_non_scrive_nulla(audit_isolato):
    generation_engine._write_voxcpm_audit("job-1", job_finito(),
                                          "speechify:simba-3.2:harper_32",
                                          "en", "completed")
    assert leggi(audit_isolato) == []


def test_un_job_senza_misure_non_solleva(audit_isolato):
    # Best-effort e non fatale, come i due omologhi: un audit che esplode non
    # deve portarsi via un audiolibro gia' consegnato.
    generation_engine._write_voxcpm_audit("job-1", {}, VOCE, "it",
                                          "failed_no_output_refunded")
    r = leggi(audit_isolato)[0]
    assert r["chars_total"] == 0
    assert r["google_cost_eur_actual"] == 0.0


def test_l_aggregato_vede_i_record_voxcpm(audit_isolato):
    generation_engine._write_voxcpm_audit("job-1", job_finito(), VOCE, "it",
                                          "completed")
    a = gemini_cost_audit.aggregate(model="v2")
    assert a["count"] == 1
    assert a["revenue_eur"] == 1.00
    assert a["margin_eur"] > 0.7


def test_un_job_gratis_sopra_soglia_lascia_traccia(audit_isolato, capsys):
    # Stessa vigilanza del ramo Speechify: un job completato sopra soglia con
    # zero incassato e' un margine negativo che qualcuno deve vedere.
    generation_engine._write_voxcpm_audit("job-1", job_finito(charged=0.0),
                                          VOCE, "it", "completed")
    assert "AUDIT WARNING" in capsys.readouterr().out
