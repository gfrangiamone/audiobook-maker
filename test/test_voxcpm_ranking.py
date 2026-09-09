"""La classifica d'uso delle voci VoxCPM: punti per voce e mese, ordine.

Ogni generazione VoxCPM che parte davvero da' un punto alla voce, nel mese
in corso. Il catalogo ordina, dentro i blocchi Female/Male, per punti del
mese, poi per punti assoluti, poi per nome. Un job conta una volta sola.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import voxcpm_ranking  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")

CHIARA = "voxcpm:v2:it-IT/Chiara"
FEDERICA = "voxcpm:v2:it-IT/Federica"
STEFANO = "voxcpm:v2:it-IT/Stefano"
EDGE = "it-IT-ElsaNeural"


@pytest.fixture(autouse=True)
def _dati_isolati(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    voxcpm_ranking.invalidate_cache()
    yield tmp_path
    voxcpm_ranking.invalidate_cache()


def _mese():
    return voxcpm_ranking._month()


def _catalogo():
    """Il catalogo unito nella forma di `_fetch_voices`, gia' in ordine base."""
    return {
        "it": {"name": "Italiano", "voices": [
            {"id": CHIARA, "name": "Chiara (IT)", "gender": "Female"},
            {"id": FEDERICA, "name": "Federica (IT)", "gender": "Female"},
            {"id": EDGE, "name": "Elsa (IT)", "gender": "Female"},
            {"id": STEFANO, "name": "Stefano (IT)", "gender": "Male"},
            {"id": "it-IT-DiegoNeural", "name": "Diego (IT)", "gender": "Male"},
        ]},
        "_premium_status": {"available": True},
    }


def _nomi(cat, lang="it"):
    return [v["name"] for v in cat[lang]["voices"]]


# -- punto / punti ---------------------------------------------------------

def test_un_punto_per_job_e_una_volta_sola(_dati_isolati):
    assert voxcpm_ranking.punto(FEDERICA, "job1") == 1
    assert voxcpm_ranking.punto(FEDERICA, "job1") == 1
    assert voxcpm_ranking.punto(FEDERICA, "job1") == 1
    assert voxcpm_ranking.punti(FEDERICA) == (1, 1)
    assert voxcpm_ranking.punto(FEDERICA, "job2") == 2
    assert voxcpm_ranking.punti(FEDERICA) == (2, 2)


def test_le_voci_degli_altri_motori_non_contano(_dati_isolati):
    assert voxcpm_ranking.punto(EDGE, "job1") == 0
    assert voxcpm_ranking.punto("", "job1") == 0
    assert voxcpm_ranking.punto(None, "job1") == 0
    assert voxcpm_ranking.punti(EDGE) == (0, 0)
    assert not (_dati_isolati / "_voxcpm_voice_points.json").exists()


def test_il_punto_finisce_su_disco(_dati_isolati):
    voxcpm_ranking.punto(STEFANO, "jobA")
    d = json.loads((_dati_isolati / "_voxcpm_voice_points.json").read_text("utf-8"))
    assert d["mesi"][_mese()][STEFANO] == 1
    assert d["jobs"]["jobA"] == _mese()
    # Riletto da zero, il dato e' lo stesso e il job resta gia' contato.
    voxcpm_ranking.invalidate_cache()
    assert voxcpm_ranking.punti(STEFANO) == (1, 1)
    assert voxcpm_ranking.punto(STEFANO, "jobA") == 1


def test_mese_e_totale_sono_due_numeri(_dati_isolati):
    (_dati_isolati / "_voxcpm_voice_points.json").write_text(json.dumps({
        "mesi": {"2024-01": {CHIARA: 7, STEFANO: 2},
                 _mese(): {CHIARA: 1}},
        "jobs": {},
    }), "utf-8")
    assert voxcpm_ranking.punti(CHIARA) == (1, 8)
    assert voxcpm_ranking.punti(STEFANO) == (0, 2)
    assert voxcpm_ranking.punti(FEDERICA) == (0, 0)
    assert voxcpm_ranking.classifica() == {
        CHIARA: {"mese": 1, "totale": 8},
        STEFANO: {"mese": 0, "totale": 2},
    }


def test_i_job_vecchi_si_potano_i_mesi_no(_dati_isolati):
    (_dati_isolati / "_voxcpm_voice_points.json").write_text(json.dumps({
        "mesi": {"2024-01": {CHIARA: 7}, "2024-02": {CHIARA: 1}},
        "jobs": {"antico": "2024-01", "vecchio": "2024-02"},
    }), "utf-8")
    voxcpm_ranking.punto(CHIARA, "nuovo")
    d = json.loads((_dati_isolati / "_voxcpm_voice_points.json").read_text("utf-8"))
    # Tenuti i due mesi piu' recenti fra quelli dei job: il mese corrente e 2024-02.
    assert set(d["jobs"]) == {"vecchio", "nuovo"}
    # I mesi restano tutti: sono il totale assoluto.
    assert set(d["mesi"]) == {"2024-01", "2024-02", _mese()}
    assert voxcpm_ranking.punti(CHIARA) == (1, 9)


@pytest.mark.parametrize("contenuto", [
    "", "non json", "[]", "42", '{"mesi": [], "jobs": "x"}',
    '{"mesi": {"2024-01": "rotto", "2024-02": {"voxcpm:v2:it-IT/Chiara": "tre"}}}',
])
def test_un_file_rotto_non_ferma_nessuno(_dati_isolati, contenuto):
    (_dati_isolati / "_voxcpm_voice_points.json").write_text(contenuto, "utf-8")
    assert voxcpm_ranking.punti(CHIARA) == (0, 0)
    assert voxcpm_ranking.punto(CHIARA, "j1") == 1
    assert voxcpm_ranking.punti(CHIARA) == (1, 1)


def test_senza_job_id_il_punto_vale_lo_stesso(_dati_isolati):
    assert voxcpm_ranking.punto(CHIARA, "") == 1
    assert voxcpm_ranking.punto(CHIARA, None) == 2


# -- ordina ----------------------------------------------------------------

def test_senza_punti_l_ordine_base_non_cambia():
    cat = voxcpm_ranking.ordina(_catalogo())
    assert _nomi(cat) == ["Chiara (IT)", "Elsa (IT)", "Federica (IT)",
                          "Diego (IT)", "Stefano (IT)"]
    assert cat["_premium_status"] == {"available": True}


def test_la_voce_usata_sale_in_testa_al_suo_blocco():
    voxcpm_ranking.punto(FEDERICA, "j1")
    cat = voxcpm_ranking.ordina(_catalogo())
    assert _nomi(cat) == ["Federica (IT)", "Chiara (IT)", "Elsa (IT)",
                          "Diego (IT)", "Stefano (IT)"]


def test_i_blocchi_non_si_mescolano():
    for i in range(5):
        voxcpm_ranking.punto(STEFANO, f"j{i}")
    cat = voxcpm_ranking.ordina(_catalogo())
    # Stefano ha piu' punti di tutte, ma resta nel blocco maschile: passa
    # davanti a Diego, non alle donne.
    assert _nomi(cat) == ["Chiara (IT)", "Elsa (IT)", "Federica (IT)",
                          "Stefano (IT)", "Diego (IT)"]


def test_a_pari_mese_decide_il_totale(_dati_isolati):
    (_dati_isolati / "_voxcpm_voice_points.json").write_text(json.dumps({
        "mesi": {"2024-01": {FEDERICA: 3}, _mese(): {CHIARA: 1, FEDERICA: 1}},
        "jobs": {},
    }), "utf-8")
    assert _nomi(voxcpm_ranking.ordina(_catalogo()))[:2] == \
        ["Federica (IT)", "Chiara (IT)"]


def test_il_mese_corrente_batte_la_storia(_dati_isolati):
    (_dati_isolati / "_voxcpm_voice_points.json").write_text(json.dumps({
        "mesi": {"2024-01": {CHIARA: 40}, _mese(): {FEDERICA: 1}},
        "jobs": {},
    }), "utf-8")
    assert _nomi(voxcpm_ranking.ordina(_catalogo()))[:2] == \
        ["Federica (IT)", "Chiara (IT)"]


def test_ordina_tollera_forme_strane():
    assert voxcpm_ranking.ordina(None) is None
    assert voxcpm_ranking.ordina({"it": "x", "en": {"voices": None}, "_k": 1}) \
        == {"it": "x", "en": {"voices": None}, "_k": 1}


# -- il catalogo dell'app ---------------------------------------------------

def test_get_voices_riordina_anche_la_cache(monkeypatch):
    import audiobook_app
    cat = _catalogo()
    monkeypatch.setattr(audiobook_app, "_voices_cache", cat)
    try:
        assert _nomi(audiobook_app.get_voices())[0] == "Chiara (IT)"
        voxcpm_ranking.punto(FEDERICA, "jX")
        assert _nomi(audiobook_app.get_voices())[0] == "Federica (IT)"
    finally:
        audiobook_app._invalidate_voices_cache()


def test_il_catalogo_reale_parte_in_ordine_di_nome(monkeypatch):
    import voxcpm_catalog
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    try:
        voxcpm_ranking.punto(STEFANO, "j1")
        voxcpm_ranking.punto(FEDERICA, "j2")
        cat = {k: {"voices": list(v)} for k, v in voxcpm_catalog.get_voices().items()}
        voxcpm_ranking.ordina(cat)
        assert [(v["gender"], v["name"]) for v in cat["it"]["voices"]] == [
            ("Female", "Federica (IT)"), ("Female", "Chiara (IT)"),
            ("Male", "Stefano (IT)")]
    finally:
        voxcpm_catalog.invalidate_cache()
