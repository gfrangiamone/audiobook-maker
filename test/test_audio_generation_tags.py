"""Parametri di generazione incisi nei metadati degli audio consegnati.

Invarianti verificate:
 - `_generation_tags` descrive motore, voce, lingua, accento, velocita' e stile
   per i tre motori (Edge standard, Gemini premium, Speechify premium);
 - i tag arrivano davvero nel file: MP3 da PCM, MP3 da concat, M4B da PCM
   (che senza `-movflags +use_metadata_tags` li scarterebbe in silenzio);
 - i tag standard del libro (titolo/autore/capitoli) restano intatti;
 - valori multilinea o troppo lunghi non rompono il comando ffmpeg.
"""
import os
import shutil
import subprocess

import pytest

import audio_utils
import generation_engine


HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
requires_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe non disponibili")


class _Info:
    def __init__(self, title="Libro", author="Autore", language="it"):
        self.title = title
        self.author = author
        self.language = language


def _format_tags(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags",
         "-of", "default=noprint_wrappers=1", path],
        capture_output=True, text=True,
    ).stdout
    tags = {}
    for line in out.splitlines():
        if line.startswith("TAG:") and "=" in line:
            k, v = line[4:].split("=", 1)
            tags[k] = v
    return tags


def _silence_pcm(tmp_path, seconds=1, sample_rate=24000):
    p = tmp_path / "chunk.pcm"
    p.write_bytes(b"\x00\x00" * (sample_rate * seconds))
    return str(p)


# --- sanitizzazione ---------------------------------------------------------

def test_sanitize_scarta_vuoti_e_normalizza_chiavi():
    tags = audio_utils._sanitize_extra_tags(
        {"ABM Voice": "Achernar", "vuoto": "", "none": None, "": "x"})
    assert tags == [("abmvoice", "Achernar")]


def test_sanitize_appiattisce_multilinea_e_tronca():
    lungo = "a" * 500
    tags = dict(audio_utils._sanitize_extra_tags(
        {"abm_style": "prima riga\nseconda\r\nterza", "abm_long": lungo}))
    assert tags["abm_style"] == "prima riga seconda terza"
    assert len(tags["abm_long"]) == audio_utils._EXTRA_TAG_MAX_CHARS


def test_extra_tag_args_vuoto_senza_tag():
    assert audio_utils._extra_tag_args(None) == []
    assert audio_utils._extra_tag_args({}) == []


# --- costruzione dei tag ----------------------------------------------------

def test_tags_voce_standard_edge():
    job = {}
    tags = generation_engine._generation_tags(job, _Info(), "it-IT-DiegoNeural", "+10%")
    assert tags["abm_model"] == "Microsoft Edge Neural TTS"
    assert tags["abm_voice"] == "it-IT-DiegoNeural"
    assert tags["abm_language"] == "it-IT"
    assert tags["abm_speed"].startswith("1.10x")
    assert tags["encoded_by"].startswith("Audiobook Maker")
    # Nessuna emozione/stile su una voce standard.
    assert "abm_style" not in tags and "abm_emotion" not in tags


def test_tags_voce_gemini_con_accento_esplicito():
    job = {"gen_lang": "en", "gemini_accent": "gb"}
    tags = generation_engine._generation_tags(
        job, _Info(language="en"), "gemini:flash31:Achernar", "+0%",
        style_instruction="tono calmo")
    assert tags["abm_voice"] == "Achernar"
    assert "Gemini 3.1" in tags["abm_model"]
    assert tags["abm_accent"].startswith("gb (")
    assert tags["abm_style"] == "tono calmo"
    assert tags["abm_speed"].startswith("1.00x")
    assert tags["abm_voice_id"] == "gemini:flash31:Achernar"


def test_tags_gemini_accento_implicito_e_quello_applicato():
    # Senza scelta esplicita la direttiva usa il default della lingua: il tag
    # deve dire quale accento e' stato davvero letto, non "nessuno".
    job = {"gen_lang": "en"}
    tags = generation_engine._generation_tags(
        job, _Info(language="en"), "gemini:flash31:Achernar", "+0%")
    assert tags["abm_accent"].startswith("us (")


def test_tags_gemini_lingua_senza_varianti_non_ha_accento():
    job = {"gen_lang": "it"}
    tags = generation_engine._generation_tags(
        job, _Info(), "gemini:flash31:Achernar", "+0%")
    assert "abm_accent" not in tags


def test_tags_voce_speechify_usa_locale_come_accento():
    import speechify_tts
    voice_id = speechify_tts.get_voices()["en"][0]["id"]
    _mk, _vn, locale = speechify_tts.parse_voice_id(voice_id)
    tags = generation_engine._generation_tags(
        {}, _Info(language="en"), voice_id, "-5%", emotion="calm")
    assert tags["abm_model"] == speechify_tts.MODEL_LABEL
    assert tags["abm_language"] == locale
    assert tags["abm_accent"] == locale
    assert tags["abm_emotion"] == "calm"
    assert tags["abm_speed"].startswith("0.95x")


def test_tags_segnalano_testo_ottimizzato():
    tags = generation_engine._generation_tags(
        {"ai_optimized": True}, _Info(), "it-IT-DiegoNeural", "+0%")
    assert tags["abm_text_optimized"] == "yes"


def test_tags_mai_esplosivi_su_job_degenere():
    # Il tagging e' best-effort: non deve mai far fallire una consegna.
    tags = generation_engine._generation_tags({}, _Info(), None, None)
    assert tags["abm_app"].startswith("Audiobook Maker")


# --- scrittura effettiva nei file ------------------------------------------

@requires_ffmpeg
def test_mp3_da_pcm_porta_i_tag(tmp_path):
    pcm = _silence_pcm(tmp_path)
    out = str(tmp_path / "out.mp3")
    assert audio_utils.pcm_to_mp3(
        [pcm], out, extra_tags={"abm_voice": "Achernar", "abm_speed": "1.10x"})
    tags = _format_tags(out)
    assert tags["abm_voice"] == "Achernar"
    assert tags["abm_speed"] == "1.10x"


@requires_ffmpeg
def test_mp3_concatenato_porta_i_tag(tmp_path):
    pcm = _silence_pcm(tmp_path)
    part = str(tmp_path / "part.mp3")
    assert audio_utils.pcm_to_mp3([pcm], part)
    out = str(tmp_path / "full.mp3")
    audio_utils._concatenate_mp3([part, part], out, extra_tags={"abm_voice": "Diego"})
    assert _format_tags(out)["abm_voice"] == "Diego"


@requires_ffmpeg
def test_m4b_porta_i_tag_senza_perdere_quelli_del_libro(tmp_path):
    pcm = _silence_pcm(tmp_path, seconds=2)
    out = str(tmp_path / "out.m4b")
    assert audio_utils.pcm_to_aac_m4b(
        [pcm], out, title="Il Libro", author="Autore X",
        chapters=[{"title": "Cap 1", "start": 0, "end": 1000}],
        extra_tags={"abm_model": "Gemini 3.1 Flash TTS", "abm_accent": "gb (British)"})
    tags = _format_tags(out)
    assert tags["abm_model"] == "Gemini 3.1 Flash TTS"
    assert tags["abm_accent"] == "gb (British)"
    # I metadati del libro non devono essere stati sostituiti dai custom.
    assert tags["title"] == "Il Libro"
    assert tags["artist"] == "Autore X"
    assert tags["media_type"] == "2"


@requires_ffmpeg
def test_m4b_da_mp3_porta_i_tag(tmp_path):
    pcm = _silence_pcm(tmp_path, seconds=2)
    mp3 = str(tmp_path / "src.mp3")
    assert audio_utils.pcm_to_mp3([pcm], mp3)
    out = str(tmp_path / "out.m4b")
    assert audio_utils._convert_mp3_to_m4b(
        mp3, out, title="Il Libro", extra_tags={"abm_voice": "Achernar"})
    tags = _format_tags(out)
    assert tags["abm_voice"] == "Achernar"
    assert tags["title"] == "Il Libro"


@requires_ffmpeg
def test_valore_con_apici_e_uguale_non_rompe_lencode(tmp_path):
    pcm = _silence_pcm(tmp_path)
    out = str(tmp_path / "out.mp3")
    assert audio_utils.pcm_to_mp3(
        [pcm], out, extra_tags={"abm_style": 'voce "calma" = lenta; ritmo lento'})
    assert "calma" in _format_tags(out)["abm_style"]


@requires_ffmpeg
def test_encode_invariato_senza_tag(tmp_path):
    # Nessun extra_tags: il comando non deve cambiare comportamento.
    pcm = _silence_pcm(tmp_path)
    out = str(tmp_path / "out.mp3")
    assert audio_utils.pcm_to_mp3([pcm], out)
    assert os.path.getsize(out) > 0
    assert "abm_voice" not in _format_tags(out)
