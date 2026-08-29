"""Lettura del catalogo di voci inventate VoxCPM.

Il catalogo reale (`data/voci_inventate/voices.json`, 361 voci al 2026-08-28)
e' una variabile indipendente: viene rigenerato mentre l'app evolve. Per D10 e
la §12.1 della spec questa suite non lo apre mai — legge una fixture con la
stessa forma e contenuto stabile.
"""
import os

import pytest

import voxcpm_catalog

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")


@pytest.fixture(autouse=True)
def catalogo_di_prova(monkeypatch):
    """Punta il modulo alla fixture e svuota la cache prima e dopo ogni test."""
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    yield
    voxcpm_catalog.invalidate_cache()


def test_catalog_dir_segue_la_variabile():
    assert voxcpm_catalog.catalog_dir() == os.path.abspath(FIXTURE)


def test_carica_solo_le_voci_con_persona():
    # Sette nel file, sei valide: "Senzacarattere" non ha description.persona.
    voci = voxcpm_catalog.voices()
    assert len(voci) == 6
    assert "Senzacarattere" not in [v["name"] for v in voci]


def test_scarto_loggato(capsys):
    voxcpm_catalog.voices()
    out = capsys.readouterr().out
    # Lo scarto e' silenzioso per l'utente, non per chi legge i log.
    assert "it-IT_m_senzacarattere" in out
    assert "persona" in out


def test_record_normalizzato():
    stefano = next(v for v in voxcpm_catalog.voices() if v["name"] == "Stefano")
    assert stefano["id"] == "voxcpm:v2:it-IT/Stefano"
    assert stefano["locale"] == "it-IT"
    assert stefano["lang"] == "it"
    assert stefano["gender"] == "Male"
    assert stefano["persona"] == "warm-young"
    assert stefano["role"] == "caldo, giovane"
    assert stefano["sample_rel"] == "it-IT/Stefano.wav"
    assert stefano["transcript"].startswith("Quando il treno")
    assert stefano["duration_s"] == 19.52


def test_genere_femminile_mappato():
    federica = next(v for v in voxcpm_catalog.voices() if v["name"] == "Federica")
    assert federica["gender"] == "Female"


def test_personas_sono_quelle_del_file():
    # Nessun elenco cablato: e' quello che la fixture contiene, ordinato.
    assert voxcpm_catalog.personas() == [
        "audiobook-slow", "grave-narrator", "poised-dry", "warm-young",
    ]


def test_cache_non_rilegge_il_file(monkeypatch):
    voxcpm_catalog.voices()
    # Sposta la variabile su una cartella inesistente: senza cache si svuoterebbe.
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", os.path.join(FIXTURE, "nonesiste"))
    assert len(voxcpm_catalog.voices()) == 6


def test_catalogo_assente_non_solleva(monkeypatch, capsys):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", os.path.join(FIXTURE, "nonesiste"))
    voxcpm_catalog.invalidate_cache()
    # Catalogo non installato: il motore sparisce, l'app non si rompe (§9.4).
    assert voxcpm_catalog.voices() == []
    assert "voices.json" in capsys.readouterr().out


def test_json_malformato_non_solleva(tmp_path, monkeypatch, capsys):
    (tmp_path / "voices.json").write_text("{ non e' json", encoding="utf-8")
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", str(tmp_path))
    voxcpm_catalog.invalidate_cache()
    assert voxcpm_catalog.voices() == []
    assert "voices.json" in capsys.readouterr().out


def test_json_array_top_level_non_solleva(tmp_path, monkeypatch, capsys):
    # voices.json è un array invece di un dict con chiave "voices"
    (tmp_path / "voices.json").write_text('[]', encoding="utf-8")
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", str(tmp_path))
    voxcpm_catalog.invalidate_cache()
    assert voxcpm_catalog.voices() == []
    out = capsys.readouterr().out
    assert "dict" in out


def test_record_malformato_tra_validi_non_solleva(tmp_path, monkeypatch, capsys):
    # Un record con duration_s invalido non deve abbattere il catalogo intero
    import json
    data = {
        "voices": [
            {
                "id": "it-IT_m_buono", "name": "Buono", "name_is_invented": True,
                "language": {"code": "it", "locale": "it-IT", "label": "italiano"},
                "gender": {"value": "m", "label": "maschile", "f0_median_hz": 118.4},
                "audio": {"file": "it-IT/Buono.wav", "transcript": "Test", "duration_s": 20.0, "sample_rate_hz": 24000},
                "quality": {"score": 0.88, "gate_passed": True},
                "description": {"persona": "warm-young", "role": "caldo", "axes": [], "lang": "it"}
            },
            {
                "id": "it-IT_m_malformato", "name": "Malformato", "name_is_invented": True,
                "language": {"code": "it", "locale": "it-IT", "label": "italiano"},
                "gender": {"value": "m", "label": "maschile", "f0_median_hz": 120.0},
                "audio": {"file": "it-IT/Malformato.wav", "transcript": "Test", "duration_s": "oops", "sample_rate_hz": 24000},
                "quality": {"score": 0.85, "gate_passed": True},
                "description": {"persona": "poised-dry", "role": "posato", "axes": [], "lang": "it"}
            }
        ]
    }
    (tmp_path / "voices.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", str(tmp_path))
    voxcpm_catalog.invalidate_cache()
    voci = voxcpm_catalog.voices()
    # Solo il record buono deve essere caricato
    assert len(voci) == 1
    assert voci[0]["name"] == "Buono"
    out = capsys.readouterr().out
    # Il record malformato deve essere loggato come scartato
    assert "it-IT_m_malformato" in out
    assert "errore normalizzazione" in out
