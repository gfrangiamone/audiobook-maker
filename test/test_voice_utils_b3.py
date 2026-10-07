"""voice_utils esteso (blocco B3): prefissi VoxCPM, token delle voci
campionate, motore per voce, parsing della velocita'.

I valori attesi dei parser sono quelli catturati dalle dodici copie
precedenti (golden del 2026-10-07) sugli input che il pannello produce
davvero: le copie divergevano solo su input degeneri (decimali, numeri
senza '%'), dove ora vale la semantica unica di `parse_rate_pct`.
"""
import pytest

import voice_utils as vu


def test_voxcpm_prefixes_and_predicates():
    assert vu.VOXCPM_MINE_PREFIX == "voxcpm:mine:"
    assert vu.VOXCPM_CATALOG_PREFIX == "voxcpm:v2:"
    assert vu.is_cloned_voice("voxcpm:mine:" + "a" * 32)
    assert not vu.is_cloned_voice("voxcpm:v2:it-IT/Marco")
    assert not vu.is_cloned_voice(None) and not vu.is_cloned_voice("")


@pytest.mark.parametrize("voice, strict, lax", [
    ("voxcpm:mine:" + "a" * 32, "a" * 32, "a" * 32),
    ("voxcpm:mine:short", None, "short"),
    ("voxcpm:mine:", None, None),
    ("voxcpm:mine:" + "A" * 32, None, "A" * 32),
    ("voxcpm:v2:it-IT/Marco", None, None),
    ("gemini:flash31:Zephyr", None, None),
    ("", None, None),
    (None, None, None),
])
def test_clone_token_matches_the_two_historical_parsers(voice, strict, lax):
    import voice_clone
    import voxcpm_tts
    assert vu.clone_token(voice) == strict
    assert vu.clone_token(voice, strict=False) == lax
    assert voice_clone.token_of(voice) == strict
    assert voxcpm_tts.voice_clone_token(voice) == lax


def test_engine_for_voice():
    assert vu.engine_for_voice("gemini:flash31:Zephyr") == "gemini"
    assert vu.engine_for_voice("speechify:simba-3.2:x") == "speechify"
    assert vu.engine_for_voice("voxcpm:v2:it-IT/Marco") == "voxcpm"
    assert vu.engine_for_voice("voxcpm:mine:" + "a" * 32) == "voxcpm"
    assert vu.engine_for_voice("it-IT-ElsaNeural") == "edge"
    assert vu.engine_for_voice("") == "edge" and vu.engine_for_voice(None) == "edge"


@pytest.mark.parametrize("rate, pct, step, factor", [
    ("+10%", 10.0, 1, 1.10), ("-10%", -10.0, -1, 0.90), ("+0%", 0.0, 0, 1.0),
    ("0%", 0.0, 0, 1.0), ("0", 0.0, 0, 1.0), ("", 0.0, 0, 1.0), (None, 0.0, 0, 1.0),
    ("+25%", 25.0, 2, 1.25), ("-35 %", -35.0, -3, 0.65), (" +7% ", 7.0, 1, 1.07),
    ("abc", 0.0, 0, 1.0), (10, 10.0, 1, 1.10), (-30, -30.0, -3, 0.70),
    ("+100%", 100.0, 3, 2.0), ("-100%", -100.0, -3, 0.0), ("+45%", 45.0, 3, 1.45),
    ("+12.5%", 12.5, 1, 1.125),
])
def test_rate_parsing(rate, pct, step, factor):
    assert vu.parse_rate_pct(rate) == pct
    assert vu.rate_step(rate) == step
    assert vu.rate_speed_factor(rate) == pytest.approx(factor)
    assert vu.rate_speed_factor(rate, floor=0.25) == pytest.approx(max(0.25, factor))


def test_parse_rate_pct_default_none_distinguishes_invalid():
    assert vu.parse_rate_pct("abc", default=None) is None
    assert vu.parse_rate_pct("", default=None) is None
    assert vu.parse_rate_pct("+5%", default=None) == 5.0


def test_engines_agree_with_the_golden_of_the_old_parsers():
    """Gli stessi input, attraverso i chiamanti migrati."""
    import gemini_tts
    import speechify_tts
    import tts_split
    import voxcpm_tts
    import generation_engine as ge
    golden = {
        "+10%": (1, "<speak><prosody rate=\"+10%\">t</prosody></speak>", 0.968, 1.1, "1.10x (+10%)"),
        "-35 %": (-3, "<speak><prosody rate=\"-35%\">t</prosody></speak>", 0.572, 0.65, "0.65x (-35 %)"),
        "+0%": (0, "<speak>t</speak>", 0.88, 1.0, "1.00x (+0%)"),
        "": (0, "<speak>t</speak>", 0.88, 1.0, ""),
        "abc": (0, "<speak>t</speak>", 0.88, 1.0, "abc"),
        "-100%": (-3, "<speak><prosody rate=\"-100%\">t</prosody></speak>", 0.5, 0.25, "0.00x (-100%)"),
        "+45%": (3, "<speak><prosody rate=\"+45%\">t</prosody></speak>", 1.276, 1.45, "1.45x (+45%)"),
    }
    for rate, (step, ssml, vox, factor, label) in golden.items():
        assert gemini_tts._rate_pct_to_step(rate) == step, rate
        assert speechify_tts.build_ssml("t", None, rate) == ssml, rate
        assert voxcpm_tts.speed_effettiva(0.88, rate) == vox, rate
        assert tts_split._rate_speed_factor(rate) == pytest.approx(factor), rate
        assert ge._speed_label(rate) == label, rate


def test_no_voice_prefix_literals_outside_voice_utils():
    import pathlib, re
    root = pathlib.Path(vu.__file__).parent
    hits = []
    for p in root.glob("*.py"):
        if p.name == "voice_utils.py":
            continue
        for m in re.finditer(r'"voxcpm:mine:"', p.read_text(encoding="utf-8", errors="replace")):
            hits.append(p.name)
    assert hits == []
