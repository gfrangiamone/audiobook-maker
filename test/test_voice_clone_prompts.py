"""Frasi guidate delle voci campionate (spec §4)."""
import json
import os
import time
import warnings

import pytest

import voice_clone_prompts as vcp

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _pulizia():
    vcp.invalidate_cache()
    yield
    vcp.invalidate_cache()


def _scrivi(path, prompts):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"schema": "abm-voice-clone-prompts/1", "prompts": prompts}, fh)


def test_file_reale_ha_le_nove_lingue():
    assert vcp.languages() == ["de", "en", "es", "fr", "hi", "it", "nl", "pt", "zh"]


def test_prompt_for_testo_unico_ignora_il_genere():
    assert vcp.prompt_for("it", "m") == vcp.prompt_for("it", "f")
    assert vcp.prompt_for("it", "f").startswith("Ogni mattina")


def test_prompt_for_hindi_cambia_col_genere():
    m, f = vcp.prompt_for("hi", "m"), vcp.prompt_for("hi", "f")
    assert m != f
    assert "खोलता" in m and "खोलती" in f


def test_lingua_sconosciuta_o_genere_sconosciuto():
    assert vcp.prompt_for("xx", "m") is None
    assert vcp.prompt_for("it", "x") is None


def test_text_by_gender_ripiega_su_text(tmp_path, monkeypatch):
    p = tmp_path / "p.json"
    _scrivi(p, {"aa": {"text": "base", "text_by_gender": {"m": "maschile"}},
                "bb": {"text_by_gender": {"m": "solo m"}},
                "cc": {"text": "   "}})
    monkeypatch.setattr(vcp, "PROMPTS_PATH", str(p))
    vcp.invalidate_cache()
    assert vcp.prompt_for("aa", "m") == "maschile"
    assert vcp.prompt_for("aa", "f") == "base"
    assert vcp.prompt_for("bb", "f") is None
    # bb ha solo il maschile, cc e' vuota: nessuna delle due e' offerta
    assert vcp.languages() == ["aa"]


def test_ricarica_quando_cambia_mtime(tmp_path, monkeypatch):
    p = tmp_path / "p.json"
    _scrivi(p, {"aa": {"text": "uno"}})
    monkeypatch.setattr(vcp, "PROMPTS_PATH", str(p))
    vcp.invalidate_cache()
    assert vcp.prompt_for("aa", "m") == "uno"
    _scrivi(p, {"aa": {"text": "due"}})
    os.utime(p, (time.time() + 5, time.time() + 5))   # mtime diverso anche su fs a 1 s
    assert vcp.prompt_for("aa", "m") == "due"


def test_file_illeggibile_vale_nessuna_lingua(tmp_path, monkeypatch):
    p = tmp_path / "p.json"
    p.write_text("{non json", encoding="utf-8")
    monkeypatch.setattr(vcp, "PROMPTS_PATH", str(p))
    vcp.invalidate_cache()
    assert vcp.languages() == []
    assert vcp.prompt_for("it", "m") is None


def test_prompt_version_stabile_e_corta():
    v = vcp.prompt_version("Ogni mattina")
    assert v == vcp.prompt_version("Ogni mattina")
    assert v.startswith("sha1:") and len(v) == 5 + 16
    assert v != vcp.prompt_version("Ogni sera")


def test_lingue_attive_del_catalogo_senza_frase_sono_un_warning():
    """Spec §4: una lingua accesa nel catalogo VoxCPM senza frase non rompe
    nulla, non compare nel wizard. Il test lo segnala, non fallisce."""
    path = os.path.join(REPO, "voxcpm2", "voci_inventate", "voices.json")
    if not os.path.exists(path):
        pytest.skip("catalogo VoxCPM non presente in questa working copy")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    attive = {e["code"] for e in data.get("languages") or [] if e.get("enabled")}
    senza = sorted(attive - set(vcp.languages()))
    if senza:
        warnings.warn(f"lingue VoxCPM attive senza frase guidata: {senza}")
    assert True
