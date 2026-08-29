"""Ordine quota -> soglia -> floor per le voci VoxCPM.

Verifica soprattutto il caso che la spec (§8.1) chiama fuori per nome: il
floor NON deve scattare quando la quota copre. Un utente con quota capiente
che si vedesse chiedere il minimo pagherebbe per qualcosa che ha gia'.
"""
import pytest

import free_quota

VOCE = "voxcpm:v2:it-IT/Stefano"


@pytest.fixture
def quota_pulita(tmp_path, monkeypatch):
    """Stato quota isolato, limite 2,00 EUR, soglia e floor VoxCPM a 0,50."""
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.50")
    monkeypatch.setenv("ABM_VOXCPM_MIN_COST_EUR", "0.50")
    return "cid-di-prova"


def test_soglia_voxcpm_e_la_sua(quota_pulita, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.80")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.50")
    assert free_quota._premium_threshold_eur(VOCE) == 0.80
    assert free_quota._premium_threshold_eur("gemini:flash25:Zephyr") == 0.50


def test_floor_voxcpm_e_il_suo(quota_pulita, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_MIN_COST_EUR", "1.20")
    monkeypatch.setenv("ABM_PREMIUM_MIN_COST_EUR", "0.50")
    assert free_quota._premium_floor_eur(VOCE) == 1.20
    # Gli altri due motori restano sulla costante di prima: nulla cambia.
    assert free_quota._premium_floor_eur("gemini:flash25:Zephyr") == 0.50
    assert free_quota._premium_floor_eur("speechify:simba-3.2:harper_32") == 0.50


def test_sopra_soglia_si_paga_e_la_quota_non_entra(quota_pulita):
    d = free_quota.decision(quota_pulita, VOCE, 3.00)
    assert d["due_eur"] == 3.00
    assert d["is_free"] is False
    assert d["quota_exhausted"] is False


def test_quota_capiente_il_floor_non_scatta(quota_pulita):
    # IL caso della spec: 0,40 sotto soglia, quota intatta -> gratis.
    # Se il floor si applicasse al lordo l'utente vedrebbe 0,50 da pagare.
    d = free_quota.decision(quota_pulita, VOCE, 0.40)
    assert d["due_eur"] == 0.0
    assert d["is_free"] is True


def test_quota_esaurita_sotto_soglia_scatta_il_floor(quota_pulita):
    free_quota.consume(quota_pulita, 1.90, job_id="job-vecchio")
    d = free_quota.decision(quota_pulita, VOCE, 0.30)
    # 1,90 + 0,30 supera il limite di 2,00: si paga, ma almeno il floor.
    assert d["quota_exhausted"] is True
    assert d["due_eur"] == 0.50


def test_floor_non_abbassa_un_importo_maggiore(quota_pulita):
    free_quota.consume(quota_pulita, 1.95, job_id="job-vecchio")
    d = free_quota.decision(quota_pulita, VOCE, 0.49)
    assert d["due_eur"] == 0.50   # max(0.49, floor 0.50)
    free_quota.consume(quota_pulita, 0.0, job_id="ignoto")


def test_retry_dello_stesso_job_resta_gratis(quota_pulita):
    d1 = free_quota.decision(quota_pulita, VOCE, 0.40, job_id="job-A")
    assert d1["is_free"] is True
    free_quota.consume(quota_pulita, 0.40, job_id="job-A")
    free_quota.consume(quota_pulita, 1.70, job_id="job-B")
    # Quota ora esaurita, ma job-A ha gia' addebitato: il suo retry non ripaga.
    d2 = free_quota.decision(quota_pulita, VOCE, 0.40, job_id="job-A")
    assert d2["due_eur"] == 0.0
    assert d2["is_free"] is True
