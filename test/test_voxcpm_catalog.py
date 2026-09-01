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


def test_get_voices_raggruppa_per_lingua():
    d = voxcpm_catalog.get_voices()
    assert sorted(d.keys()) == ["en", "it"]
    assert len(d["it"]) == 3   # Stefano, Federica, Chiara
    assert len(d["en"]) == 3   # Nolan, Ivy (en-US), Rufus (en-GB)


def test_entry_ha_la_forma_delle_altre_premium():
    ivy = next(v for v in voxcpm_catalog.get_voices()["en"] if v["name"].startswith("Ivy"))
    assert ivy["id"] == "voxcpm:v2:en-US/Ivy"
    assert ivy["engine"] == "voxcpm"
    assert ivy["model_key"] == "v2"
    assert ivy["model_label"] == "VoxCPM2"
    assert ivy["locale"] == "en-US"
    assert ivy["gender"] == "Female"
    assert ivy["gender_icon"] == "\U0001f469"
    assert ivy["persona"] == "poised-dry"
    assert ivy["persona_role"] == "poised, dry"


def test_nome_porta_la_regione():
    # Dentro la stessa lingua due varianti convivono: senza la regione nel nome
    # l'utente che non filtra per accento non sa cosa sta scegliendo.
    nomi = sorted(v["name"] for v in voxcpm_catalog.get_voices()["en"])
    assert nomi == ["Ivy (US)", "Nolan (US)", "Rufus (GB)"]


def test_sample_url_punta_alla_rotta():
    stefano = next(v for v in voxcpm_catalog.get_voices()["it"] if v["name"].startswith("Stefano"))
    assert stefano["sample_url"] == "/api/voice_sample?voice=voxcpm%3Av2%3Ait-IT%2FStefano"


def test_parse_voice_id_ritorna_il_record():
    rec = voxcpm_catalog.parse_voice_id("voxcpm:v2:it-IT/Stefano")
    assert rec["name"] == "Stefano"
    assert rec["transcript"].startswith("Quando il treno")


def test_parse_voice_id_rifiuta_input_estranei():
    for cattivo in (None, "", 7, "gemini:flash25:Zephyr", "voxcpm:v2", "voxcpm:v9:it-IT/Stefano"):
        with pytest.raises(ValueError):
            voxcpm_catalog.parse_voice_id(cattivo)


def test_parse_voice_id_voce_sparita_dal_catalogo():
    # Caso normale, non errore di programmazione (§9.4): un job vecchio cita
    # una voce che una rigenerazione del catalogo ha rimosso.
    with pytest.raises(ValueError) as e:
        voxcpm_catalog.parse_voice_id("voxcpm:v2:it-IT/Fantasma")
    assert "Fantasma" in str(e.value)


def test_parse_voce_clonata_non_e_di_catalogo():
    # `voxcpm:mine:<token>` e' del piano 2: questo modulo la riconosce come
    # non sua e lo dice, invece di cercarla fra le voci inventate.
    with pytest.raises(ValueError) as e:
        voxcpm_catalog.parse_voice_id("voxcpm:mine:abc123")
    assert "mine" in str(e.value)


def test_sample_path_esiste():
    p = voxcpm_catalog.sample_path("voxcpm:v2:it-IT/Stefano")
    assert p == os.path.join(FIXTURE, "it-IT", "Stefano.wav")
    assert os.path.exists(p)


def test_sample_path_file_mancante():
    # Federica e' nel JSON ma il suo .wav non e' nella fixture.
    with pytest.raises(FileNotFoundError):
        voxcpm_catalog.sample_path("voxcpm:v2:it-IT/Federica")


def test_sample_path_non_evade_dalla_cartella(tmp_path, monkeypatch):
    # `audio.file` arriva da un file di dati: un percorso con .. non deve
    # poter servire file fuori dal catalogo.
    import json as _json
    cattivo = {
        "voices": [{
            "id": "x_m_evasione", "name": "Evasione",
            "language": {"code": "it", "locale": "it-IT"},
            "gender": {"value": "m"},
            "audio": {"file": "../../../etc/passwd", "transcript": "testo", "duration_s": 1.0},
            "description": {"persona": "warm-young"},
        }]
    }
    (tmp_path / "voices.json").write_text(_json.dumps(cattivo), encoding="utf-8")
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", str(tmp_path))
    voxcpm_catalog.invalidate_cache()
    with pytest.raises(ValueError):
        voxcpm_catalog.sample_path("voxcpm:v2:it-IT/Evasione")


# --- Le clip dimostrative (§17) ---------------------------------------


def test_demos_normalizzate_comune_per_prima():
    # La fixture elenca la clip su misura per prima: l'ordine d'ascolto
    # (comune, poi su misura) lo garantisce la normalizzazione, non il dato.
    stefano = next(v for v in voxcpm_catalog.voices() if v["name"] == "Stefano")
    assert [d["id"] for d in stefano["demos"]] == ["opening", "memory"]
    assert stefano["demos"][0]["common"] is True
    assert stefano["demos"][0]["file"] == "_demo/it-IT/Stefano-opening.wav"
    assert stefano["demos"][0]["text"].startswith("La casa")


def test_demo_malformata_ignorata_voce_valida():
    # Una clip senza file o testo si ignora: la voce resta in catalogo,
    # perche' le clip servono all'ascolto, non alla generazione del libro.
    federica = next(v for v in voxcpm_catalog.voices() if v["name"] == "Federica")
    assert [d["id"] for d in federica["demos"]] == ["opening"]


def test_voce_senza_demos_resta_valida():
    chiara = next(v for v in voxcpm_catalog.voices() if v["name"] == "Chiara")
    assert chiara["demos"] == []


def test_entry_porta_le_demo_url():
    stefano = next(v for v in voxcpm_catalog.get_voices()["it"] if v["name"].startswith("Stefano"))
    assert [d["id"] for d in stefano["demos"]] == ["opening", "memory"]
    assert stefano["demos"][0]["common"] is True
    assert stefano["demos"][0]["url"] == (
        "/api/voice_demo?voice=voxcpm%3Av2%3Ait-IT%2FStefano&clip=opening")


def test_entry_senza_demo_ha_lista_vuota():
    # Il ripiego della UI sul campione si decide su questa lista vuota.
    ivy = next(v for v in voxcpm_catalog.get_voices()["en"] if v["name"].startswith("Ivy"))
    assert ivy["demos"] == []


def test_demo_path_esiste():
    p = voxcpm_catalog.demo_path("voxcpm:v2:it-IT/Stefano", "opening")
    assert p == os.path.join(FIXTURE, "_demo", "it-IT", "Stefano-opening.wav")
    assert os.path.exists(p)


def test_demo_path_clip_inesistente():
    with pytest.raises(ValueError) as e:
        voxcpm_catalog.demo_path("voxcpm:v2:it-IT/Stefano", "fantasma")
    assert "non presente" in str(e.value)


def test_demo_path_voce_senza_clip():
    with pytest.raises(ValueError):
        voxcpm_catalog.demo_path("voxcpm:v2:it-IT/Chiara", "opening")


def test_demo_path_non_evade_dalla_cartella(tmp_path, monkeypatch):
    # `demos[].file` arriva dallo stesso file di dati di `audio.file`: un
    # percorso con .. non deve poter servire file fuori dal catalogo.
    import json as _json
    cattivo = {
        "voices": [{
            "id": "x_m_evasione", "name": "Evasione",
            "language": {"code": "it", "locale": "it-IT"},
            "gender": {"value": "m"},
            "audio": {"file": "it-IT/Evasione.wav", "transcript": "testo", "duration_s": 1.0},
            "description": {"persona": "warm-young"},
            "demos": [{"id": "opening", "common": True,
                       "file": "../../segreto.wav", "text": "testo"}],
        }]
    }
    (tmp_path / "voices.json").write_text(_json.dumps(cattivo), encoding="utf-8")
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", str(tmp_path))
    voxcpm_catalog.invalidate_cache()
    with pytest.raises(ValueError):
        voxcpm_catalog.demo_path("voxcpm:v2:it-IT/Evasione", "opening")
