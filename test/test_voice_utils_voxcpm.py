"""Predicato di voce PREMIUM VoxCPM.

`voice_utils` e' modulo foglia: nessun import di progetto. Il predicato deve
essere safe su input non-stringa come i due gemelli Gemini/Speechify, perche'
lo chiamano percorsi che ricevono il voice id grezzo dal client.
"""
import voice_utils


def test_prefix_value():
    assert voice_utils.VOXCPM_VOICE_PREFIX == "voxcpm:"


def test_catalog_voice_is_voxcpm():
    assert voice_utils.is_voxcpm_voice("voxcpm:v2:it-IT/Stefano") is True


def test_cloned_voice_is_voxcpm():
    # Formato del piano 2: deve gia' essere riconosciuto dal predicato.
    assert voice_utils.is_voxcpm_voice("voxcpm:mine:abc123") is True


def test_other_engines_are_not_voxcpm():
    assert voice_utils.is_voxcpm_voice("gemini:flash25:Zephyr") is False
    assert voice_utils.is_voxcpm_voice("speechify:simba-3.2:harper_32") is False
    assert voice_utils.is_voxcpm_voice("it-IT-IsabellaNeural") is False


def test_safe_on_junk():
    assert voice_utils.is_voxcpm_voice(None) is False
    assert voice_utils.is_voxcpm_voice("") is False
    assert voice_utils.is_voxcpm_voice(42) is False
    assert voice_utils.is_voxcpm_voice(["voxcpm:v2:it-IT/Stefano"]) is False
