"""Test degli interruttori per modello PREMIUM (ABM_<MODELLO>_ENABLE).

Default: ogni modello premium e' abilitato. Serve un valore esplicitamente
falso per toglierlo dal catalogo voci e dagli ingressi HTTP.
"""
import pytest

import voice_utils
import gemini_tts
import speechify_tts
import audiobook_app
from epub_to_tts import BookInfo, Chapter


# --- voice_utils ----------------------------------------------------------

def test_env_name_normalizza_il_model_key():
    assert voice_utils.premium_model_env_name("flash25") == "ABM_FLASH25_ENABLE"
    assert voice_utils.premium_model_env_name("flash31") == "ABM_FLASH31_ENABLE"
    assert voice_utils.premium_model_env_name("simba-3.2") == "ABM_SIMBA32_ENABLE"


def test_default_abilitato_senza_env(monkeypatch):
    monkeypatch.delenv("ABM_FLASH25_ENABLE", raising=False)
    assert voice_utils.premium_model_enabled("flash25") is True


@pytest.mark.parametrize("val", ["0", "false", "FALSE", "No", " off "])
def test_valori_falsi_disabilitano(monkeypatch, val):
    monkeypatch.setenv("ABM_FLASH25_ENABLE", val)
    assert voice_utils.premium_model_enabled("flash25") is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "on", "", "   "])
def test_altri_valori_lasciano_abilitato(monkeypatch, val):
    monkeypatch.setenv("ABM_FLASH25_ENABLE", val)
    assert voice_utils.premium_model_enabled("flash25") is True


def test_voice_model_key():
    assert voice_utils.voice_model_key("gemini:flash25:Zephyr") == "flash25"
    assert voice_utils.voice_model_key("speechify:simba-3.2:harper_32") == "simba-3.2"
    assert voice_utils.voice_model_key("it-IT-IsabellaNeural") == ""
    assert voice_utils.voice_model_key("gemini:flash25") == ""
    assert voice_utils.voice_model_key(None) == ""


def test_voce_standard_mai_bloccata(monkeypatch):
    monkeypatch.setenv("ABM_FLASH25_ENABLE", "false")
    assert voice_utils.voice_model_enabled("it-IT-IsabellaNeural") is True


def test_solo_il_modello_spento_e_bloccato(monkeypatch):
    monkeypatch.setenv("ABM_FLASH25_ENABLE", "false")
    assert voice_utils.voice_model_enabled("gemini:flash25:Zephyr") is False
    assert voice_utils.voice_model_enabled("gemini:flash31:Zephyr") is True


# --- cataloghi voci -------------------------------------------------------

def test_catalogo_gemini_esclude_il_modello_spento(monkeypatch):
    monkeypatch.setenv("ABM_FLASH25_ENABLE", "false")
    assert gemini_tts.enabled_model_keys() == ["flash31"]
    voices = gemini_tts.get_voices()
    keys = {v["model_key"] for lst in voices.values() for v in lst}
    assert keys == {"flash31"}


def test_catalogo_gemini_completo_di_default(monkeypatch):
    monkeypatch.delenv("ABM_FLASH25_ENABLE", raising=False)
    monkeypatch.delenv("ABM_FLASH31_ENABLE", raising=False)
    keys = {v["model_key"] for lst in gemini_tts.get_voices().values() for v in lst}
    assert keys == set(gemini_tts.GEMINI_MODELS)


def test_catalogo_gemini_vuoto_con_tutti_i_modelli_spenti(monkeypatch):
    monkeypatch.setenv("ABM_FLASH25_ENABLE", "0")
    monkeypatch.setenv("ABM_FLASH31_ENABLE", "0")
    assert gemini_tts.enabled_model_keys() == []
    assert all(not lst for lst in gemini_tts.get_voices().values())


def test_catalogo_speechify_gated(monkeypatch):
    monkeypatch.setenv("ABM_SIMBA32_ENABLE", "false")
    assert speechify_tts.model_enabled() is False
    assert speechify_tts.get_voices() == {}
    monkeypatch.setenv("ABM_SIMBA32_ENABLE", "true")
    assert speechify_tts.get_voices().get("en")


def test_sintesi_non_gated_dal_flag(monkeypatch):
    """Il gate vale su catalogo e ingressi HTTP, non sui path interni: un job
    gia' avviato o in recovery deve poter finire anche a modello spento."""
    monkeypatch.setenv("ABM_FLASH25_ENABLE", "false")
    # parse_voice_id resta valido: accounting, audit e ripresa job lo usano.
    assert gemini_tts.parse_voice_id("gemini:flash25:Zephyr")[0] == "flash25"
    assert speechify_tts.parse_voice_id(
        "speechify:simba-3.2:harper_32")[0] == "simba-3.2"


# --- ingressi HTTP --------------------------------------------------------

@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        yield c


@pytest.fixture
def job_with_text():
    ch = Chapter(index=0, title="Cap0", text="Lorem ipsum dolor sit amet. " * 80)
    info = BookInfo(
        title="Test", author="A", language="it", chapters=[ch],
        total_words=ch.word_count, total_chars=ch.char_count,
        estimated_duration_minutes=1.0,
    )
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["pmjob1"] = {"info": info, "status": "analyzed"}
    yield
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop("pmjob1", None)


def test_gemini_estimate_rifiuta_modello_spento(client, job_with_text, monkeypatch):
    monkeypatch.setenv("ABM_FLASH25_ENABLE", "false")
    r = client.post("/api/gemini_estimate", json={
        "job_id": "pmjob1",
        "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0],
    })
    assert r.status_code == 400
    body = r.get_json()
    assert body["error_code"] == "voice_model_disabled"
    assert body["model_key"] == "flash25"


def test_gemini_estimate_accetta_modello_acceso(client, job_with_text, monkeypatch):
    monkeypatch.setenv("ABM_FLASH25_ENABLE", "false")
    r = client.post("/api/gemini_estimate", json={
        "job_id": "pmjob1",
        "voice_id": "gemini:flash31:Zephyr",
        "selected_chapters": [0],
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["model_key"] == "flash31"


def test_combined_estimate_rifiuta_modello_spento(client, job_with_text, monkeypatch):
    monkeypatch.setenv("ABM_FLASH25_ENABLE", "false")
    r = client.post("/api/combined_estimate", json={
        "job_id": "pmjob1",
        "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0],
    })
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "voice_model_disabled"


def test_paypal_order_gemini_rifiuta_modello_spento(client, job_with_text, monkeypatch):
    monkeypatch.setenv("ABM_FLASH25_ENABLE", "false")
    r = client.post("/api/paypal_create_order_gemini", json={
        "job_id": "pmjob1",
        "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0],
        "amount_eur": 1.0,
    })
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "voice_model_disabled"


def test_generate_rifiuta_modello_spento(client, monkeypatch):
    monkeypatch.setenv("ABM_SIMBA32_ENABLE", "false")
    r = client.post("/api/generate", json={
        "job_id": "pmjob-inesistente",
        "voice": "speechify:simba-3.2:harper_32",
    })
    # Il gate scatta prima della lookup del job: 400 voice_model_disabled,
    # non "Session expired".
    assert r.status_code == 400
    assert r.get_json().get("error_code") == "voice_model_disabled"
