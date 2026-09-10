"""Le voci VoxCPM su /api/voices e il campione su /api/voice_sample."""
import os

import pytest

import audiobook_app
import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")


@pytest.fixture(autouse=True)
def catalogo_di_prova(monkeypatch):
    # La cache delle voci di audiobook_app e' globale di modulo: senza
    # invalidarla prima E dopo, questo test vedrebbe (o lascerebbe) il
    # catalogo di un altro.
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "3.00")
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


def voci_voxcpm(catalogo):
    out = []
    for codice, dati in catalogo.items():
        if codice.startswith("_"):
            continue
        out.extend(v for v in dati.get("voices", []) if v.get("engine") == "voxcpm")
    return out


def test_le_voci_voxcpm_entrano_nel_catalogo():
    trovate = voci_voxcpm(audiobook_app.get_voices())
    assert trovate
    assert all(v["id"].startswith("voxcpm:v2:") for v in trovate)
    assert {v["model_label"] for v in trovate} == {"VoxCPM2"}


def test_le_voci_finiscono_sotto_la_lingua_giusta():
    catalogo = audiobook_app.get_voices()
    ita = [v for v in catalogo["it"]["voices"] if v.get("engine") == "voxcpm"]
    assert len(ita) == 3
    assert all(v["locale"].startswith("it-") for v in ita)


def test_una_lingua_nuova_del_catalogo_apre_la_sua_sezione():
    # D10: il catalogo e' una variabile. Se domani arriva una voce giapponese,
    # /api/voices deve aprire la sezione da solo, senza rilascio.
    catalogo = audiobook_app.get_voices()
    assert "en" in catalogo
    assert [v for v in catalogo["en"]["voices"] if v.get("engine") == "voxcpm"]


def test_senza_configurazione_le_voci_non_compaiono(monkeypatch):
    # Stessa regola del tab premium con Gemini (§9.4): un motore non
    # configurato non compare, invece di comparire e fallire alla generazione.
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "")
    audiobook_app._invalidate_voices_cache()
    assert voci_voxcpm(audiobook_app.get_voices()) == []


def test_un_catalogo_illeggibile_non_rompe_le_altre_voci(monkeypatch, tmp_path):
    # Il catalogo e' un dato importato: se arriva rotto, le voci Edge devono
    # continuare a funzionare. Un motore in meno, non un'app in meno.
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", str(tmp_path / "inesistente"))
    voxcpm_catalog.invalidate_cache()
    audiobook_app._invalidate_voices_cache()
    catalogo = audiobook_app.get_voices()
    assert voci_voxcpm(catalogo) == []
    assert any(not k.startswith("_") for k in catalogo)


def test_stato_del_motore_nella_risposta(client):
    dati = client.get("/api/voices").get_json()
    assert dati["_voxcpm"]["available"] is True
    assert dati["_voxcpm"]["model_label"] == "VoxCPM2"
    # I caratteri arrivano dal catalogo, mai da una costante: la UI ci
    # costruisce il filtro CARATTERE.
    # Nota: la fixture usa "warm-young" (non "warm-pro" come nel brief) —
    # verificato leggendo test/fixtures/voxcpm_catalog/voices.json e
    # test/test_voxcpm_catalog.py::test_personas_sono_quelle_del_file, che
    # attesta i caratteri della fixture come
    # ["audiobook-slow", "grave-narrator", "poised-dry", "warm-young"].
    assert "warm-young" in dati["_voxcpm"]["personas"]


def test_il_campione_si_scarica(client):
    r = client.get("/api/voice_sample?voice=voxcpm:v2:it-IT/Stefano")
    assert r.status_code == 200
    assert r.mimetype == "audio/wav"
    assert r.data[:4] == b"RIFF"


def test_campione_di_una_voce_inesistente(client):
    r = client.get("/api/voice_sample?voice=voxcpm:v2:it-IT/Fantasma")
    assert r.status_code == 404


def test_campione_con_id_malformato(client):
    for cattivo in ("", "gemini:flash25:Zephyr", "voxcpm:v2"):
        r = client.get(f"/api/voice_sample?voice={cattivo}")
        assert r.status_code == 400


def test_campione_non_serve_file_fuori_dal_catalogo(client, monkeypatch):
    # `voice` arriva dal browser e il percorso del file da un file di dati:
    # nessuno dei due e' fidato.
    r = client.get("/api/voice_sample?voice=voxcpm:v2:../../etc/passwd")
    assert r.status_code in (400, 404)


def test_campione_di_una_voce_scartata(client, monkeypatch, tmp_path):
    # `Senzacarattere` sta nel voices.json della fixture ma il Task 2 l'ha
    # scartata: la rotta non deve servirla piu' della lista.
    r = client.get("/api/voice_sample?voice=voxcpm:v2:it-IT/Senzacarattere")
    assert r.status_code == 404


# --- /api/voice_demo (§17) --------------------------------------------


def test_la_clip_dimostrativa_si_scarica(client):
    r = client.get("/api/voice_demo?voice=voxcpm:v2:it-IT/Stefano&clip=opening")
    assert r.status_code == 200
    assert r.mimetype == "audio/wav"
    assert r.data[:4] == b"RIFF"


def test_clip_inesistente_404(client):
    r = client.get("/api/voice_demo?voice=voxcpm:v2:it-IT/Stefano&clip=fantasma")
    assert r.status_code == 404


def test_clip_di_voce_senza_demo_404(client):
    # Chiara e' in catalogo ma il suo lotto non ha ancora le clip: la UI
    # ripiega sul campione, la rotta risponde che la clip non c'e'.
    r = client.get("/api/voice_demo?voice=voxcpm:v2:it-IT/Chiara&clip=opening")
    assert r.status_code == 404


def test_clip_con_voce_malformata_400(client):
    for cattivo in ("", "gemini:flash25:Zephyr", "voxcpm:v2"):
        r = client.get(f"/api/voice_demo?voice={cattivo}&clip=opening")
        assert r.status_code == 400, cattivo


def test_clip_non_evade_dal_catalogo(client):
    r = client.get("/api/voice_demo?voice=voxcpm:v2:../../etc/passwd&clip=opening")
    assert r.status_code in (400, 404)
