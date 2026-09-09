"""`clone_block` e lingua del job per le voci campionate (spec §9)."""
import base64
import os

import pytest

import community_store
import storage_backend
import voice_clone as vc
import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    yield
    voxcpm_catalog.invalidate_cache()


def _voce(tmp_path, wav=b"RIFF-mio-campione"):
    s = tmp_path / "s.wav"; s.write_bytes(wav)
    o = tmp_path / "o.webm"; o.write_bytes(b"webm")
    return vc.create_draft("cid-x", lang="it", locale="it-IT", gender="f",
                           prompt_text="Ogni mattina apro la finestra",
                           sample_wav=str(s), original_path=str(o), original_ext="webm",
                           metrics={}, ui_lang="it")


def test_clone_block_per_voce_mine(tmp_path):
    rec = _voce(tmp_path)
    blocco = voxcpm_tts.clone_block(vc.voice_id_of(rec))
    assert base64.b64decode(blocco["prompt_wav_b64"]) == b"RIFF-mio-campione"
    assert blocco["prompt_text"] == "Ogni mattina apro la finestra"
    assert blocco["reference_wav_b64"] == blocco["prompt_wav_b64"]
    assert blocco["prompt_format"] == blocco["reference_format"] == "wav"


def test_clone_block_mine_e_in_cache(tmp_path):
    rec = _voce(tmp_path)
    vid = vc.voice_id_of(rec)
    a = voxcpm_tts.clone_block(vid)
    os.remove(os.path.join(vc.voice_dir(rec["token"]), "sample.wav"))
    assert voxcpm_tts.clone_block(vid) == a          # servito dalla cache
    voxcpm_tts.invalidate_clone_cache()
    with pytest.raises(FileNotFoundError):
        voxcpm_tts.clone_block(vid)


def test_clone_block_mine_sconosciuta_solleva_value_error():
    token = "a" * 32
    with pytest.raises(ValueError) as ei:
        voxcpm_tts.clone_block("voxcpm:mine:" + token)
    assert token not in str(ei.value)      # mai il token nel messaggio d'errore


def test_clone_block_catalogo_invariato():
    blocco = voxcpm_tts.clone_block("voxcpm:v2:it-IT/Stefano")
    assert blocco["prompt_text"].startswith("Quando il treno")


def test_lingua_voce(tmp_path):
    rec = _voce(tmp_path)
    assert voxcpm_tts._lingua_voce(vc.voice_id_of(rec)) == "it"
    assert voxcpm_tts._lingua_voce("voxcpm:v2:it-IT/Stefano") == "it"
    token = "b" * 32
    with pytest.raises(ValueError) as ei:
        voxcpm_tts._lingua_voce("voxcpm:mine:" + token)
    assert token not in str(ei.value)      # mai il token nel messaggio d'errore
