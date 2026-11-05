"""Stile e accento Gemini ed emozione Speechify arrivano alla generazione
anche dal wizard (/api/optimize con auto_generate): prima andavano persi e il
libro usciva con l'accento di default della lingua."""
import inspect
import re
from pathlib import Path

import audiobook_app

APP = Path("static/js/app.js").read_text(encoding="utf-8")


def test_stash_normalizza_e_scrive_nel_job():
    job = {}
    out = audiobook_app._stash_voice_options(job, {
        "gemini_style_instruction": "x" * 300, "gemini_accent": " gb ",
        "speechify_emotion": "INVENTATA"})
    assert out == ("x" * 200, "gb", "")
    assert job == {"gemini_style_instruction": "x" * 200, "gemini_accent": "gb"}


def test_stash_senza_opzioni_non_tocca_il_job():
    job = {"gemini_accent": "419"}
    audiobook_app._stash_voice_options(job, {})
    assert job == {"gemini_accent": "419"}


def test_generate_e_optimize_auto_generate_usano_lo_stesso_stash():
    gen = inspect.getsource(audiobook_app.api_generate)
    opt = inspect.getsource(audiobook_app.api_optimize)
    assert "_stash_voice_options(job, data)" in gen
    auto = opt[opt.index('job["opt_auto_generate"] = True'):]
    assert "_stash_voice_options(job, data)" in auto[:auto.index("else:")]


def test_spa_manda_le_opzioni_voce_in_tutti_i_payload():
    assert "function getVoiceOptions()" in APP
    assert "Object.assign(payload,getParenFlags(),getVoiceOptions())" in APP   # optimize
    assert APP.count("getVoiceOptions()") == 4      # definizione + optimize + 2 generate
    assert not re.search(r"payload\.gemini_accent\s*=", APP, flags=re.I)
