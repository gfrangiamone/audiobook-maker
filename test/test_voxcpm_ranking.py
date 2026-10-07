"""La classifica d'uso delle voci VoxCPM: punti per voce e giorno, ordine.

Ogni generazione VoxCPM che parte davvero da' un punto alla voce, nel giorno
in corso. Il catalogo ordina, dentro i blocchi Female/Male, per punti degli
ultimi 30 giorni, poi per punti assoluti, poi per nome. Un job conta una
volta sola.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import voxcpm_ranking  # noqa: E402

# Il lettore vero del business log, prima che il fixture lo spenga.
_RIGHE_VERE = voxcpm_ranking._righe_generate

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")

CHIARA = "voxcpm:v2:it-IT/Chiara"
FEDERICA = "voxcpm:v2:it-IT/Federica"
STEFANO = "voxcpm:v2:it-IT/Stefano"
EDGE = "it-IT-ElsaNeural"


@pytest.fixture(autouse=True)
def _dati_isolati(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    # Nessun business log: i file senza `giorni` partono con la finestra vuota.
    monkeypatch.setattr(voxcpm_ranking, "_righe_generate", lambda: [])
    voxcpm_ranking.invalidate_cache()
    yield tmp_path
    voxcpm_ranking.invalidate_cache()


def _mese():
    return voxcpm_ranking._month()


def _fa(n):
    return voxcpm_ranking._giorni_fa(n)


def _scrivi(cartella, d):
    (cartella / "_voxcpm_voice_points.json").write_text(json.dumps(d), "utf-8")


def _leggi(cartella):
    return json.loads((cartella / "_voxcpm_voice_points.json").read_text("utf-8"))


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
    d = _leggi(_dati_isolati)
    assert d["mesi"][_mese()][STEFANO] == 1
    assert d["giorni"][_fa(0)][STEFANO] == 1
    assert d["jobs"]["jobA"] == _fa(0)
    # Riletto da zero, il dato e' lo stesso e il job resta gia' contato.
    voxcpm_ranking.invalidate_cache()
    assert voxcpm_ranking.punti(STEFANO) == (1, 1)
    assert voxcpm_ranking.punto(STEFANO, "jobA") == 1


def test_finestra_e_totale_sono_due_numeri(_dati_isolati):
    _scrivi(_dati_isolati, {
        "mesi": {"2024-01": {CHIARA: 7, STEFANO: 2}, _mese(): {CHIARA: 1}},
        "giorni": {_fa(0): {CHIARA: 1}},
        "jobs": {},
    })
    assert voxcpm_ranking.punti(CHIARA) == (1, 8)
    assert voxcpm_ranking.punti(STEFANO) == (0, 2)
    assert voxcpm_ranking.punti(FEDERICA) == (0, 0)
    assert voxcpm_ranking.classifica() == {
        CHIARA: {"finestra": 1, "totale": 8},
        STEFANO: {"finestra": 0, "totale": 2},
    }


def test_la_finestra_e_di_trenta_giorni_non_il_mese(_dati_isolati):
    # Oggi e i 29 giorni prima contano, il trentesimo no: il cambio di mese
    # non azzera niente.
    _scrivi(_dati_isolati, {
        "mesi": {},
        "giorni": {_fa(29): {CHIARA: 2}, _fa(30): {STEFANO: 5}},
        "jobs": {},
    })
    assert voxcpm_ranking.punti(CHIARA)[0] == 2
    assert voxcpm_ranking.punti(STEFANO)[0] == 0


def test_i_giorni_fuori_finestra_e_i_job_vecchi_si_potano(_dati_isolati):
    _scrivi(_dati_isolati, {
        "mesi": {"2024-01": {CHIARA: 7}, _mese(): {CHIARA: 1}},
        "giorni": {_fa(45): {CHIARA: 1}, _fa(3): {CHIARA: 1}},
        "jobs": {"antico": "2024-01", "vecchio": _fa(61), "recente": _fa(59),
                 "di_questo_mese": _mese()},
    })
    voxcpm_ranking.punto(CHIARA, "nuovo")
    d = _leggi(_dati_isolati)
    assert set(d["giorni"]) == {_fa(3), _fa(0)}
    assert set(d["jobs"]) == {"recente", "di_questo_mese", "nuovo"}
    # I mesi restano tutti: sono il totale assoluto.
    assert "2024-01" in d["mesi"]
    assert voxcpm_ranking.punti(CHIARA) == (2, 9)


def test_il_job_gia_contato_ritorna_i_punti_della_finestra(_dati_isolati):
    _scrivi(_dati_isolati, {
        "mesi": {_mese(): {CHIARA: 3}},
        "giorni": {_fa(2): {CHIARA: 2}},
        "jobs": {"j1": _fa(2)},
    })
    assert voxcpm_ranking.punto(CHIARA, "j1") == 2
    assert voxcpm_ranking.punti(CHIARA) == (2, 3)


def test_senza_giorni_la_finestra_si_ricostruisce_dal_business_log(
        _dati_isolati, monkeypatch):
    monkeypatch.setattr(voxcpm_ranking, "_righe_generate", lambda: [
        ("j1", CHIARA, _fa(1) + " 10:00:00"),
        ("j2", CHIARA, _fa(40) + " 10:00:00"),     # fuori finestra
        ("j3", STEFANO, _fa(5) + " 09:00:00"),
        ("j4", FEDERICA, _fa(1) + " 08:00:00"),    # mai contato: non c'e' in jobs
        ("j5", EDGE, _fa(1) + " 08:00:00"),
    ])
    _scrivi(_dati_isolati, {
        "mesi": {"2026-09": {CHIARA: 2, STEFANO: 1}},
        "jobs": {"j1": "2026-09", "j2": "2026-09", "j3": "2026-09", "j5": "2026-09"},
    })
    assert voxcpm_ranking.punti(CHIARA) == (1, 2)
    assert voxcpm_ranking.punti(STEFANO) == (1, 1)
    assert voxcpm_ranking.punti(FEDERICA) == (0, 0)
    voxcpm_ranking.punto(FEDERICA, "j9")
    assert _leggi(_dati_isolati)["giorni"][_fa(1)] == {CHIARA: 1}


def test_il_seme_non_si_rifa_se_giorni_c_e(_dati_isolati, monkeypatch):
    monkeypatch.setattr(voxcpm_ranking, "_righe_generate", lambda: [
        ("j1", CHIARA, _fa(1) + " 10:00:00")])
    _scrivi(_dati_isolati, {"mesi": {}, "giorni": {}, "jobs": {"j1": _fa(1)}})
    assert voxcpm_ranking.punti(CHIARA) == (0, 0)


def test_il_seme_legge_le_generate_da_activity_db(monkeypatch, tmp_path):
    import activity_db
    import activity_log
    db = tmp_path / "activity.db"
    conn = activity_db.connect(db)
    # Il rilancio di j1 e' una ripetizione della stessa chiave di dedup
    # (ym, job_id, op, op_arg, epoch): va distinto con seq, come fa il writer.
    for ts, jid, op, voce, seq in [
        (_fa(1) + " 10:00:00", "j1", "GENERATE", CHIARA, 0),
        (_fa(0) + " 10:00:00", "j1", "GENERATE", CHIARA, 1),    # rilancio: conta il primo
        (_fa(1) + " 11:00:00", "j1", "COMPLETE", CHIARA, 0),
        (_fa(2) + " 10:00:00", "j2", "GENERATE", STEFANO, 0),
    ]:
        conn.execute(
            "INSERT INTO events (ym, ts, job_id, op, filename, client_id, ip,"
            " voice, detail, lang, platform, seq) VALUES (?,?,?,?,'','','',?,'','','',?)",
            (ts[:7], ts, jid, op, voce, seq))
    conn.close()
    monkeypatch.setattr(activity_log, "mode", lambda: "dual")
    monkeypatch.setattr(activity_log, "db_path", lambda: db)
    assert sorted(_RIGHE_VERE()) == [
        ("j1", CHIARA, _fa(1) + " 10:00:00"), ("j2", STEFANO, _fa(2) + " 10:00:00")]
    monkeypatch.setattr(activity_log, "db_path", lambda: tmp_path / "manca.db")
    assert _RIGHE_VERE() == []
    monkeypatch.setattr(activity_log, "mode", lambda: "off")
    assert _RIGHE_VERE() == []


@pytest.mark.parametrize("contenuto", [
    "", "non json", "[]", "42", '{"mesi": [], "jobs": "x", "giorni": 5}',
    '{"mesi": {"2024-01": "rotto", "2024-02": {"voxcpm:v2:it-IT/Chiara": "tre"}}}',
    '{"giorni": {"2099-01-01": "rotto"}}',
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


def test_a_pari_finestra_decide_il_totale(_dati_isolati):
    _scrivi(_dati_isolati, {
        "mesi": {"2024-01": {FEDERICA: 3}, _mese(): {CHIARA: 1, FEDERICA: 1}},
        "giorni": {_fa(0): {CHIARA: 1, FEDERICA: 1}},
        "jobs": {},
    })
    assert _nomi(voxcpm_ranking.ordina(_catalogo()))[:2] ==         ["Federica (IT)", "Chiara (IT)"]


def test_la_finestra_batte_la_storia(_dati_isolati):
    _scrivi(_dati_isolati, {
        "mesi": {"2024-01": {CHIARA: 40}, _mese(): {FEDERICA: 1}},
        "giorni": {_fa(0): {FEDERICA: 1}},
        "jobs": {},
    })
    assert _nomi(voxcpm_ranking.ordina(_catalogo()))[:2] ==         ["Federica (IT)", "Chiara (IT)"]


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
