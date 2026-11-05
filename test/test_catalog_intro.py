"""Inserto iniziale degli audiolibri del catalogo gratuito (catalog_intro)."""
import array
import json
import math
import os

import pytest

import catalog_intro
import ffmpeg_tools
import generation_engine
from fileio import file_sha256

pytestmark = pytest.mark.skipif(not ffmpeg_tools.tool("ffmpeg"), reason="ffmpeg assente")


def _tono(path, secondi, rate, ampiezza):
    n = int(secondi * rate)
    campioni = array.array("h", (int(ampiezza * math.sin(2 * math.pi * 220 * i / rate))
                                 for i in range(n)))
    with open(path, "wb") as f:
        f.write(campioni.tobytes())


@pytest.fixture
def cartella(tmp_path, monkeypatch):
    """Inserti it (f, m) e pt-br (f) a 24 kHz, con il loro manifest."""
    d = tmp_path / "intro"
    d.mkdir()
    manifest = {}
    for key, sesso in (("it", "f"), ("it", "m"), ("pt-br", "f")):
        p = d / f"{key}-{sesso}.pcm"
        _tono(p, 3.0, 24000, 3000)
        manifest.setdefault(key, {"chapter": "Introduzione" if key == "it" else "Introdução"})
        manifest[key][sesso] = {"file": p.name, "sha256": file_sha256(p),
                                "voice": "gemini:flash38:Sulafat",
                                "lufs": ffmpeg_tools.loudness_lufs(p, in_rate=24000)}
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("ABM_CATALOG_INTRO_DIR", str(d))
    monkeypatch.setenv("ABM_BASE_URL", "http://localhost:5621")
    return d


def test_spenta_senza_cartella_e_in_produzione(cartella, monkeypatch):
    assert catalog_intro.intro_dir() == str(cartella)
    monkeypatch.setenv("ABM_BASE_URL", "https://audiobook-maker.com")
    assert catalog_intro.intro_dir() is None
    monkeypatch.delenv("ABM_CATALOG_INTRO_DIR")
    monkeypatch.setenv("ABM_BASE_URL", "http://localhost:5621")
    assert catalog_intro.intro_dir() is None


def test_sesso_e_accento_della_voce(monkeypatch):
    assert catalog_intro.voice_traits("gemini:flash38:Sulafat", "it") == ("f", None)
    assert catalog_intro.voice_traits("gemini:flash38:Charon", "pt", "pt") == ("m", "pt")
    assert catalog_intro.voice_traits("gemini:flash38:Charon", "pt") == ("m", "br")
    locali = {"voxcpm:v2:pt-PT/A": ("pt-PT", "Female"), "voxcpm:v2:es-AR/B": ("es-AR", "Male"),
              "voxcpm:v2:it-IT/C": ("it-IT", "Male")}
    monkeypatch.setattr(catalog_intro.voxcpm_catalog, "parse_voice_id",
                        lambda v: {"locale": locali[v][0], "gender": locali[v][1]})
    assert catalog_intro.voice_traits("voxcpm:v2:pt-PT/A", "pt") == ("f", "pt")
    assert catalog_intro.voice_traits("voxcpm:v2:es-AR/B", "es") == ("m", "419")
    assert catalog_intro.voice_traits("voxcpm:v2:it-IT/C", "it") == ("m", None)
    assert catalog_intro.voice_traits("it-IT-ElsaNeural", "it") == (None, None)


def test_variante_con_accento_poi_lingua():
    m = {"pt-br": {"f": {}}, "it": {"f": {}, "m": {}}}
    assert catalog_intro.pick(m, "pt", "br", "f") == "pt-br"
    assert catalog_intro.pick(m, "pt", "pt", "f") is None
    assert catalog_intro.pick(m, "it", None, "m") == "it"
    assert catalog_intro.pick(m, "pt", "br", "m") is None


def test_inserto_al_rate_e_alla_loudness_del_libro(cartella, tmp_path):
    libro = tmp_path / "chunk.pcm"
    _tono(libro, 4.0, 48000, 12000)          # libro piu' forte dell'inserto
    out = catalog_intro.prepare("gemini:flash38:Sulafat", "it", sample_rate=48000,
                                book_parts=[str(libro)], work_dir=str(tmp_path))
    assert out["key"] == "it" and out["chapter"] == "Introduzione"
    assert out["gain_db"] == pytest.approx(12.04, abs=0.5)
    # 3 s a 48 kHz s16le mono
    assert os.path.getsize(out["path"]) == pytest.approx(3 * 48000 * 2, rel=0.01)
    misurato = ffmpeg_tools.loudness_lufs(out["path"], in_rate=48000)
    atteso = ffmpeg_tools.loudness_lufs(str(libro), in_rate=48000)
    assert misurato == pytest.approx(atteso, abs=1.0)
    assert not (tmp_path / "_intro_misura.pcm").exists()


def test_file_alterato_niente_inserto(cartella, tmp_path):
    with open(cartella / "it-f.pcm", "ab") as f:
        f.write(b"\x00\x00")
    libro = tmp_path / "chunk.pcm"
    _tono(libro, 2.0, 24000, 3000)
    assert catalog_intro.prepare("gemini:flash38:Sulafat", "it", sample_rate=24000,
                                 book_parts=[str(libro)], work_dir=str(tmp_path)) is None


def test_lingua_senza_inserto_niente_inserto(cartella, tmp_path):
    assert catalog_intro.prepare("gemini:flash38:Sulafat", "de", sample_rate=24000,
                                 book_parts=[], work_dir=str(tmp_path)) is None


def test_il_montaggio_mette_l_inserto_come_primo_capitolo(monkeypatch, tmp_path):
    intro = tmp_path / "_intro.pcm"
    intro.write_bytes(b"\x00" * 48000)       # 1 s a 24 kHz
    monkeypatch.setattr(generation_engine.catalog_intro, "prepare",
                        lambda *a, **k: {"path": str(intro), "chapter": "Introduzione",
                                         "key": "it", "voice": "gemini:flash38:Sulafat",
                                         "sha256": "x", "gain_db": 1.5})
    visti = {}

    def finto_m4b(parts, out, on_phase=None, status_out=None, chapters=None, **kw):
        visti["parts"], visti["chapters"] = list(parts), chapters
        open(out, "wb").write(b"\x00")
        return True

    def fake_chunk(text, voice_id, output_path, max_retries=3, **kwargs):
        open(output_path, "wb").write(b"\x00" * 24000)        # 0,5 s
        return {"success": True, "bytes_written": 24000, "input_tokens": 1,
                "output_tokens": 1, "model_key": "flash38", "backend": "openrouter"}

    monkeypatch.setattr(generation_engine, "generate_chunk_pcm_gemini", fake_chunk)
    monkeypatch.setattr(generation_engine, "pcm_to_aac_m4b_monitored", finto_m4b)
    monkeypatch.setattr(generation_engine.gemini_cost_audit, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(generation_engine.gemini_tts, "actual_cost_breakdown",
                        lambda i, o, mk, b: {"total_eur": 0.0}, raising=False)
    plan = [{"chapter_index": ci, "chapter_title": f"Cap {ci}", "chunk_index": 0,
             "chunks_in_chapter": 1, "text": "Ciao.", "chars": 5} for ci in (1, 2)]
    monkeypatch.setattr(generation_engine, "_plan_chunks", lambda info, max_chars, max_bytes=None, **kw: plan)
    monkeypatch.setattr(generation_engine, "_pick_chunk_max_chars", lambda v, l: 4096)
    monkeypatch.setattr(generation_engine, "_engine_for_voice", lambda v: "gemini")
    monkeypatch.setattr(generation_engine, "_prepare_m4b_cover_path", lambda *a, **k: None)

    class _Info:
        title = "T"
        author = "A"
        language = "it"
        chapters = [type("C", (), {"title": f"Cap {i}", "text": "..."})() for i in (1, 2)]
    job = {"gen_epoch": 0, "info": _Info(), "status": "queued", "last_poll": 9e18,
           "email_registered": True}
    monkeypatch.setattr(generation_engine, "_jobs", {"ji": job})
    monkeypatch.setattr(generation_engine, "_upload_dir", tmp_path)
    monkeypatch.setattr(generation_engine, "_jobs_lock", None, raising=False)
    try:
        generation_engine.run_generation("ji", _Info(), "gemini:flash38:Sulafat", "+0%",
                                         single_file=True, output_format="m4b")
    except Exception:
        pass

    assert visti["parts"][0] == str(intro)
    capitoli = visti["chapters"]
    assert capitoli[0]["title"] == "Introduzione" and capitoli[0]["start"] == 0
    assert capitoli[1]["title"] == "Cap 1" and capitoli[1]["start"] == capitoli[0]["end"] >= 1000
    assert job["catalog_intro"]["key"] == "it"
