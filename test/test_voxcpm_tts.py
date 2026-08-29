"""Configurazione, disponibilita' e listino del motore VoxCPM.

Nessuna rete: il ponte verso RunPod si prova col doppio in
test_voxcpm_tts_runpod.py.
"""
import os

import pytest

import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")


@pytest.fixture
def configurato(monkeypatch):
    """Motore pienamente configurato: endpoint, chiave, catalogo, tariffa."""
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "abc123endpoint")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "rp-chiave-finta")
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "4.00")
    voxcpm_catalog.invalidate_cache()
    yield
    voxcpm_catalog.invalidate_cache()


def test_disponibile_quando_tutto_c_e(configurato):
    assert voxcpm_tts.is_available() is True


def test_senza_endpoint_non_disponibile(configurato, monkeypatch):
    monkeypatch.delenv("ABM_VOXCPM_ENDPOINT_ID")
    assert voxcpm_tts.is_available() is False


def test_senza_chiave_non_disponibile(configurato, monkeypatch):
    monkeypatch.delenv("ABM_VOXCPM_API_KEY")
    assert voxcpm_tts.is_available() is False


def test_senza_tariffa_non_disponibile(configurato, monkeypatch):
    # §15.3: il listino si fissa prima del deploy. Meglio il motore nascosto
    # che libri generati a un prezzo che nessuno ha deciso.
    monkeypatch.delenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR")
    assert voxcpm_tts.is_available() is False


def test_tariffa_zero_non_disponibile(configurato, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "0")
    assert voxcpm_tts.is_available() is False


def test_catalogo_vuoto_non_disponibile(configurato, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", os.path.join(FIXTURE, "nonesiste"))
    voxcpm_catalog.invalidate_cache()
    assert voxcpm_tts.is_available() is False


def test_concorrenza_default_e_override(configurato, monkeypatch):
    assert voxcpm_tts.concurrency() == 32
    monkeypatch.setenv("ABM_VOXCPM_CONCURRENCY", "8")
    assert voxcpm_tts.concurrency() == 8
    monkeypatch.setenv("ABM_VOXCPM_CONCURRENCY", "0")
    assert voxcpm_tts.concurrency() == 1      # floor
    monkeypatch.setenv("ABM_VOXCPM_CONCURRENCY", "cavallo")
    assert voxcpm_tts.concurrency() == 32     # valore illeggibile -> default


def test_listino_e_tariffa_diretta(configurato):
    # 250.000 caratteri a 4,00 EUR/Mchar = 1,00 EUR.
    p = voxcpm_tts.compute_user_price_eur(250_000)
    assert p["chars"] == 250_000
    assert p["list_price_eur"] == 1.00
    assert p["user_price_eur"] == 1.00
    assert p["is_free"] is False


def test_sotto_soglia_e_gratis(configurato):
    # 25.000 caratteri = 0,10 EUR, sotto ABM_VOXCPM_FREE_THRESHOLD_EUR (0,50).
    p = voxcpm_tts.compute_user_price_eur(25_000)
    assert p["list_price_eur"] == 0.10
    assert p["user_price_eur"] == 0.0
    assert p["is_free"] is True


def test_caratteri_assurdi_non_sollevano(configurato):
    assert voxcpm_tts.compute_user_price_eur(0)["list_price_eur"] == 0.0
    assert voxcpm_tts.compute_user_price_eur(-5)["chars"] == 0
    assert voxcpm_tts.compute_user_price_eur(None)["chars"] == 0


def test_costo_gpu_misurato_e_separato_dal_listino(configurato):
    # §8.3: base di costo misurata su RTX 4090, serve all'audit, non al prezzo.
    assert voxcpm_tts.cost_usd_per_mchar() == 0.91
    p = voxcpm_tts.compute_user_price_eur(1_000_000)
    assert p["list_price_eur"] == 4.00      # dalla tariffa, non dal costo
    assert p["cost_usd"] == 0.91


def test_stima_libro_somma_i_capitoli(configurato):
    class Cap:
        def __init__(self, text):
            self.text = text
    capitoli = [Cap("a" * 100_000), Cap("b" * 150_000)]
    s = voxcpm_tts.estimate_book_cost(capitoli, language="it")
    assert s["chars_total"] == 250_000
    assert s["chars_per_chapter"] == [100_000, 150_000]
    assert s["list_price_eur"] == 1.00
    assert s["language"] == "it"
    assert s["model_key"] == "v2"
