"""Inserto iniziale dei libri gratuiti letti con edge-tts (free_intro)."""
import hashlib
import os
import threading
import zipfile
from types import SimpleNamespace

import pytest

import audiobook_app
import ffmpeg_tools
import free_intro
import generation_engine
import i18n
import podcast_rss
import recovery
from test.test_failed_chunk_retry import _setup

_RIPIEGO = f"gemini:flash38:{free_intro.VOCE_RIPIEGO}"


@pytest.fixture
def acceso(monkeypatch, tmp_path):
    """Inserto acceso, cartella dati in tmp, sintesi finta che registra
    (lingua, voce)."""
    monkeypatch.setenv("ABM_FREE_INTRO_ENABLE", "1")
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(free_intro, "most_used_voice", lambda lang: None)
    monkeypatch.setattr(free_intro, "_pausa_fino", {})
    sintesi = []

    def finta(text, lang, voice, out_path):
        sintesi.append((lang, voice))
        with open(out_path, "wb") as f:
            f.write(b"\x02" * 500)
        return True
    monkeypatch.setattr(free_intro, "_synth", finta)
    return sintesi


def _cache(tmp_path):
    return tmp_path / "data" / free_intro.CACHE_DIRNAME


def _righe(*coppie):
    return [SimpleNamespace(voice=v, lang=lang) for v, lang in coppie]


def test_lingua_dalla_voce_o_dal_job_per_le_multilingual():
    assert free_intro.intro_lang("it-IT-DiegoNeural", "en") == "it"
    assert free_intro.intro_lang("en-US-AvaMultilingualNeural", "it") == "it"
    assert free_intro.intro_lang("en-US-AvaMultilingualNeural", "") == "en"


def test_testi_del_json():
    tabella = i18n.load("free_intro")
    assert len(tabella) >= 25
    for lang, e in tabella.items():
        assert set(e) == {"text"}, lang
        assert e["text"].strip() and "audiobook maker" in e["text"]


def test_voce_piu_usata_gemini_del_browser_nella_lingua(monkeypatch):
    righe = _righe(("gemini:flash38:Kore", "it"), ("gemini:flash31:Kore", "it-IT"),
                   ("gemini:flash38:Puck", "it"), ("gemini:flash38:Sulafat", "en"),
                   ("gemini:flash38:Sulafat", "en"), ("it-IT-ElsaNeural", "it"),
                   ("it-IT-ElsaNeural", "it"), ("it-IT-ElsaNeural", "it"),
                   ("gemini:flash38:Nessuna", "it"), ("gemini:flash38:Nessuna", "it"),
                   ("gemini:flash38:Nessuna", "it"), ("", None))
    visti = {}

    def iter_rows(since, until=None, ops=None):
        visti["ops"] = ops
        return iter(righe)
    monkeypatch.setattr(free_intro.activity_log, "iter_rows", iter_rows)
    assert free_intro.most_used_voice("it") == "Kore"
    assert visti["ops"] == {"GENERATE"}
    assert free_intro.most_used_voice("fr") is None


def test_voce_piu_usata_a_parita_la_prima_in_ordine(monkeypatch):
    monkeypatch.setattr(free_intro.activity_log, "iter_rows", lambda *a, **k: iter(
        _righe(("gemini:flash38:Puck", "it"), ("gemini:flash38:Kore", "it"))))
    assert free_intro.most_used_voice("it") == "Kore"


@pytest.mark.parametrize("voce, job", [
    ("gemini:flash38:Sulafat", {}),
    ("it-IT-ElsaNeural", {free_intro.SUBSCRIBER_KEY: True}),
    ("sw-KE-ZuriNeural", {}),
])
def test_niente_inserto(acceso, tmp_path, voce, job):
    assert free_intro.prepare(job, voce, "", tmp_path / "x.mp3") is None
    assert acceso == []


def test_spento_da_env(acceso, monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_FREE_INTRO_ENABLE", "0")
    assert free_intro.prepare({}, "it-IT-ElsaNeural", "it", tmp_path / "x.mp3") is None
    assert acceso == []


def test_pagamento_di_ottimizzazione_non_toglie_l_inserto(acceso, tmp_path):
    job = {"payment_token": "tok", "payment_amount_eur": 3.5, "ai_optimized": True}
    assert free_intro.prepare(job, "it-IT-ElsaNeural", "it", tmp_path / "x.mp3")


def test_prima_sintesi_poi_cache(acceso, monkeypatch, tmp_path):
    monkeypatch.setattr(free_intro, "most_used_voice", lambda lang: "Kore")
    primo = free_intro.prepare({}, "it-IT-IsabellaNeural", "it", tmp_path / "a.mp3")
    assert primo == {"path": str(tmp_path / "a.mp3"), "lang": "it",
                     "voice": "gemini:flash38:Kore", "cached": False}
    secondo = free_intro.prepare({}, "it-IT-ElsaNeural", "it", tmp_path / "b.mp3")
    assert secondo["cached"] is True and secondo["voice"] == "gemini:flash38:Kore"
    assert acceso == [("it", "Kore")]
    assert (tmp_path / "b.mp3").read_bytes() == b"\x02" * 500
    assert sorted(f.suffix for f in _cache(tmp_path).iterdir()) == [".json", ".mp3"]


def test_senza_dati_d_uso_voce_di_ripiego(acceso, tmp_path):
    assert free_intro.prepare({}, "de-DE-ConradNeural", "de", tmp_path / "a.mp3")["voice"] \
        == _RIPIEGO


def test_log_illeggibile_voce_di_ripiego(acceso, monkeypatch, tmp_path):
    def rotto(lang):
        raise OSError("log assente")
    monkeypatch.setattr(free_intro, "most_used_voice", rotto)
    assert free_intro.prepare({}, "de-DE-ConradNeural", "de", tmp_path / "a.mp3")["voice"] \
        == _RIPIEGO


@pytest.mark.parametrize("guasto", [lambda *a: False, lambda *a: 1 / 0])
def test_nessun_audio_niente_in_cache_e_lingua_in_pausa(acceso, monkeypatch, tmp_path, guasto):
    chiamate = []

    def sintesi(*a):
        chiamate.append(a[1])
        return guasto(*a)
    monkeypatch.setattr(free_intro, "_synth", sintesi)
    orologio = [1000.0]
    monkeypatch.setattr(free_intro.time, "monotonic", lambda: orologio[0])
    assert free_intro.prepare({}, "it-IT-ElsaNeural", "it", tmp_path / "a.mp3") is None
    assert not any(_cache(tmp_path).iterdir())
    assert not (tmp_path / "a.mp3").exists()

    # In pausa la lingua non chiama Gemini; le altre si'.
    orologio[0] += free_intro._PAUSA_S - 1
    assert free_intro.prepare({}, "it-IT-ElsaNeural", "it", tmp_path / "b.mp3") is None
    assert free_intro.prepare({}, "en-US-JennyNeural", "en", tmp_path / "c.mp3") is None
    assert chiamate == ["it", "en"]
    orologio[0] += 2
    free_intro.prepare({}, "it-IT-ElsaNeural", "it", tmp_path / "d.mp3")
    assert chiamate == ["it", "en", "it"]


def test_testo_cambiato_rigenera_e_toglie_il_vecchio(acceso, monkeypatch, tmp_path):
    free_intro.prepare({}, "it-IT-ElsaNeural", "it", tmp_path / "a.mp3")
    free_intro.prepare({}, "en-US-JennyNeural", "en", tmp_path / "b.mp3")
    tabella = dict(i18n.load("free_intro"))
    tabella["it"] = {"text": "Testo nuovo. Buon ascolto!"}
    monkeypatch.setattr(free_intro.i18n, "load", lambda name: tabella)
    assert free_intro.prepare({}, "it-IT-ElsaNeural", "it", tmp_path / "c.mp3")["cached"] is False
    nomi = sorted(f.name for f in _cache(tmp_path).glob("*.mp3"))
    assert len(nomi) == 2 and nomi[0].startswith("en-") and nomi[1].startswith("it-")
    assert nomi[1] == free_intro._cache_file("it", "Testo nuovo. Buon ascolto!").name


def _vecchio_edge(tmp_path, lang):
    """File in cache come li scriveva la versione edge: chiave dal solo testo."""
    testo = i18n.load("free_intro")[lang]["text"]
    nome = f"{lang}-{hashlib.sha1(testo.encode('utf-8')).hexdigest()[:12]}"
    _cache(tmp_path).mkdir(parents=True, exist_ok=True)
    (_cache(tmp_path) / f"{nome}.mp3").write_bytes(b"\x01" * 300)
    (_cache(tmp_path) / f"{nome}.json").write_text('{"voice": "it-IT-ElsaNeural"}')
    return _cache(tmp_path) / f"{nome}.mp3"


def test_l_inserto_edge_in_cache_non_si_usa_piu(acceso, tmp_path):
    vecchio = _vecchio_edge(tmp_path, "it")
    out = free_intro.prepare({}, "it-IT-ElsaNeural", "it", tmp_path / "a.mp3")
    assert out["cached"] is False and out["voice"] == _RIPIEGO
    assert (tmp_path / "a.mp3").read_bytes() == b"\x02" * 500
    assert not vecchio.exists() and not vecchio.with_suffix(".json").exists()


def test_refresh_rifa_solo_gli_inserti_superati(acceso, tmp_path):
    free_intro.prepare({}, "en-US-JennyNeural", "en", tmp_path / "a.mp3")
    vecchi = [_vecchio_edge(tmp_path, lang) for lang in ("it", "fr")]
    (_cache(tmp_path) / "sw-0123456789ab.mp3").write_bytes(b"\x01")    # lingua senza testo
    del acceso[:]
    assert free_intro.refresh_cached() == ["fr", "it"]
    assert acceso == [("fr", "Sulafat"), ("it", "Sulafat")]
    assert not any(v.exists() for v in vecchi)
    for lang in ("en", "fr", "it"):
        testo = i18n.load("free_intro")[lang]["text"]
        assert free_intro._cache_file(lang, testo).is_file()
    assert free_intro.refresh_cached() == [] and len(acceso) == 2


def test_refresh_fallito_lascia_il_vecchio(acceso, monkeypatch, tmp_path):
    vecchio = _vecchio_edge(tmp_path, "it")
    monkeypatch.setattr(free_intro, "_synth", lambda *a: False)
    assert free_intro.refresh_cached() == []
    assert vecchio.exists()


def test_refresh_spento_da_env(acceso, monkeypatch, tmp_path):
    _vecchio_edge(tmp_path, "it")
    monkeypatch.setenv("ABM_FREE_INTRO_ENABLE", "0")
    assert free_intro.refresh_cached() == [] and acceso == []


def test_start_refresh_in_un_thread(monkeypatch):
    fatto = threading.Event()
    monkeypatch.setattr(free_intro, "refresh_cached", lambda: fatto.set() or ["it"])
    free_intro.start_refresh()
    assert fatto.wait(5)


def test_l_avvio_lancia_il_refresh():
    import inspect
    assert "free_intro.start_refresh()" in inspect.getsource(
        audiobook_app._ensure_background_threads)


def test_synth_senza_gemini_non_chiama(monkeypatch, tmp_path):
    monkeypatch.setattr(free_intro.gemini_tts, "is_available", lambda: False)
    monkeypatch.setattr(free_intro.gemini_tts, "synthesize",
                        lambda *a, **k: pytest.fail("chiamata a Gemini"))
    assert free_intro._synth("Ciao.", "it", "Kore", str(tmp_path / "a.mp3")) is False


@pytest.mark.parametrize("misura, guadagno", [(-16.0, -4.0), (-40.0, 12.0), (None, 0.0)])
def test_guadagno_verso_la_loudness_di_edge(monkeypatch, misura, guadagno):
    monkeypatch.setattr(free_intro.ffmpeg_tools, "loudness_lufs", lambda *a, **k: misura)
    assert free_intro._gain_db("x.pcm") == guadagno


@pytest.mark.skipif(not ffmpeg_tools.tool("ffmpeg"), reason="ffmpeg assente")
def test_synth_mp3_come_quelli_di_edge(monkeypatch, tmp_path):
    visti = {}

    def finto(text, voice_id, output_path, accent_directive=None, max_attempts=None):
        visti.update(voice=voice_id, accent=accent_directive, tentativi=max_attempts)
        ffmpeg_tools.write_pcm_silence(output_path, 1.0)
        return {"success": True}
    monkeypatch.setattr(free_intro.gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(free_intro.gemini_tts, "model_unavailable", lambda key: False)
    monkeypatch.setattr(free_intro.gemini_tts, "synthesize", finto)
    out = tmp_path / "a.mp3"
    assert free_intro._synth("Ciao.", "it", "Kore", str(out))
    assert visti == {"voice": "gemini:flash38:Kore", "tentativi": free_intro._TENTATIVI,
                     "accent": "Read in Italian, keeping one consistent accent throughout."}
    r = ffmpeg_tools.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_name,sample_rate,channels",
                          "-of", "default=noprint_wrappers=1", str(out)])
    assert set(r.stdout.split()) == {"codec_name=mp3", "sample_rate=24000", "channels=1"}
    assert os.listdir(tmp_path) == ["a.mp3"]


def test_cartella_cache_non_e_una_job_dir(acceso, tmp_path):
    import cleanup
    free_intro.prepare({}, "it-IT-ElsaNeural", "it", tmp_path / "a.mp3")
    entry = next(e for e in os.scandir(tmp_path / "data") if e.name == free_intro.CACHE_DIRNAME)
    assert not cleanup._is_job_dir(entry)


def test_rss_file_000_fuori_dai_capitoli(tmp_path):
    files = []
    for nome in (free_intro.FILE_NAME, "001_Cap 1.mp3", "002_Cap 2.mp3"):
        p = tmp_path / nome
        p.write_bytes(b"\x01" * 6000)
        files.append(str(p))
    info = SimpleNamespace(title="T", author="A", language="it",
                           chapters=[SimpleNamespace(index=i, title=f"Cap {i}") for i in (0, 1)])
    out = tmp_path / "podcast.xml"
    podcast_rss._generate_podcast_rss(info, files, str(out))
    xml = out.read_text(encoding="utf-8")
    titoli = xml.split("<item>")[1:]
    assert "<title>audiobook-maker.com</title>" in titoli[0]
    assert "<title>Cap 0</title>" in titoli[1] and "<title>Cap 1</title>" in titoli[2]


def test_lo_stash_della_richiesta_segna_solo_gli_abbonati(monkeypatch):
    abbonato = [True]
    monkeypatch.setattr(audiobook_app.routes_account, "current_account_is_subscriber",
                        lambda: abbonato[0])
    job = {}
    audiobook_app._stash_voice_options(job, {})
    assert job == {free_intro.SUBSCRIBER_KEY: True}
    abbonato[0] = False      # abbonamento scaduto prima di rigenerare
    audiobook_app._stash_voice_options(job, {})
    assert job == {}


def test_descrittore_e_recovery_portano_l_abbonamento(tmp_path, monkeypatch):
    d = audiobook_app._build_job_descriptor({free_intro.SUBSCRIBER_KEY: True}, "generate")
    assert d[free_intro.SUBSCRIBER_KEY] is True
    assert audiobook_app._build_job_descriptor({}, "generate")[free_intro.SUBSCRIBER_KEY] is False

    epub = tmp_path / "book.epub"
    epub.write_bytes(b"fake-epub")
    monkeypatch.setattr(audiobook_app, "_parse_book", lambda src: object())
    monkeypatch.setattr(audiobook_app.threading, "Thread",
                        type("T", (), {"__init__": lambda s, *a, **k: None,
                                       "start": lambda s: None}))
    rec = {"id": "Jsub", "phase": "generate", "voice": "it-IT-ElsaNeural",
           "input_path": str(epub), free_intro.SUBSCRIBER_KEY: True}
    try:
        recovery._reenqueue_orphan("Jsub", rec)
        assert audiobook_app.jobs["Jsub"][free_intro.SUBSCRIBER_KEY] is True
    finally:
        audiobook_app.jobs.pop("Jsub", None)


def _run(info, fmt):
    try:
        generation_engine.run_generation("jr", info(), "en-US-AndrewMultilingualNeural", "+0%",
                                         single_file=fmt in ("mp3", "m4b"), output_format=fmt)
    except Exception:
        pass


def test_m4b_inserto_primo_capitolo(acceso, monkeypatch, tmp_path):
    job, _calls, encoded, info = _setup(monkeypatch, tmp_path, fail_times=0)
    visti = {}

    def finto_m4b(mp3, out, on_phase=None, status_out=None, chapters=None, **kw):
        visti["chapters"] = chapters
        open(out, "wb").write(b"\x01")
        return True
    monkeypatch.setattr(generation_engine, "_convert_mp3_to_m4b_monitored", finto_m4b)
    monkeypatch.setattr(generation_engine, "_prepare_m4b_cover_path", lambda *a, **k: None)
    _run(info, "m4b")

    _out, heads = encoded[-1]
    assert list(heads)[0] == "_free_intro.mp3" and heads["_free_intro.mp3"] == b"\x02"
    capitoli = visti["chapters"]
    assert capitoli[0] == {"title": "audiobook-maker.com", "start": 0, "end": 1000}
    assert capitoli[1]["title"] == "Cap 1" and capitoli[1]["start"] == 1000
    assert job["free_intro"] == {"lang": "en", "voice": _RIPIEGO, "cached": False}
    assert not (tmp_path / "jr" / "_free_intro.mp3").exists()


def test_abbonato_senza_inserto(acceso, monkeypatch, tmp_path):
    job, _calls, encoded, info = _setup(monkeypatch, tmp_path, fail_times=0)
    job[free_intro.SUBSCRIBER_KEY] = True
    _run(info, "mp3")
    assert "_free_intro.mp3" not in encoded[-1][1]
    assert "free_intro" not in job and acceso == []


def test_zip_inserto_primo_file(acceso, monkeypatch, tmp_path):
    job, _calls, encoded, info = _setup(monkeypatch, tmp_path, fail_times=0)
    _run(info, "zip")

    intro = [(out, heads) for out, heads in encoded if out.endswith(free_intro.FILE_NAME)]
    assert intro and list(intro[0][1]) == ["_free_intro.mp3"]
    names = [os.path.basename(p) for p in job["output_files"]]
    assert names[0] == free_intro.FILE_NAME and [n[:4] for n in names[1:]] == ["001_", "002_"]
    with zipfile.ZipFile(job["output_zip"]) as z:
        assert sorted(n for n in z.namelist() if n.endswith(".mp3")) == names
    assert job["status"] == "done"
