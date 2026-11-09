"""Inserto iniziale dei libri gratuiti letti con edge-tts (free_intro)."""
import os
import zipfile
from types import SimpleNamespace

import pytest

import audiobook_app
import free_intro
import generation_engine
import i18n
import podcast_rss
import recovery
from test.test_failed_chunk_retry import _setup


@pytest.fixture
def acceso(monkeypatch, tmp_path):
    """Inserto acceso, cartella dati in tmp, sintesi finta che registra le voci."""
    monkeypatch.setenv("ABM_FREE_INTRO_ENABLE", "1")
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(free_intro, "most_used_voice", lambda lang: None)
    sintesi = []

    def finta(text, voice, out_path):
        sintesi.append(voice)
        with open(out_path, "wb") as f:
            f.write(b"\x02" * 500)
        return True
    monkeypatch.setattr(free_intro, "_synth", finta)
    return sintesi


def _cache(tmp_path):
    return tmp_path / "data" / free_intro.CACHE_DIRNAME


def _righe(*voci):
    return [SimpleNamespace(voice=v) for v in voci]


def test_lingua_dalla_voce_o_dal_job_per_le_multilingual():
    assert free_intro.intro_lang("it-IT-DiegoNeural", "en") == "it"
    assert free_intro.intro_lang("en-US-AvaMultilingualNeural", "it") == "it"
    assert free_intro.intro_lang("en-US-AvaMultilingualNeural", "") == "en"


def test_testi_e_voci_del_json():
    tabella = i18n.load("free_intro")
    assert len(tabella) >= 25
    for lang, e in tabella.items():
        assert e["text"].strip() and "audiobook maker" in e["text"]
        assert free_intro._is_standard_voice_of(e["voice"], lang), (lang, e["voice"])


def test_voce_piu_usata_solo_standard_della_lingua(monkeypatch):
    righe = _righe("it-IT-DiegoNeural", "it-IT-ElsaNeural", "it-IT-DiegoNeural",
                   "it-IT-GiuseppeMultilingualNeural", "it-IT-GiuseppeMultilingualNeural",
                   "it-IT-GiuseppeMultilingualNeural", "en-US-JennyNeural", "en-US-JennyNeural",
                   "gemini:flash38:Sulafat", "Select a language first", "")
    visti = {}

    def iter_rows(since, until=None, ops=None):
        visti["ops"] = ops
        return iter(righe)
    monkeypatch.setattr(free_intro.activity_log, "iter_rows", iter_rows)
    assert free_intro.most_used_voice("it") == "it-IT-DiegoNeural"
    assert visti["ops"] == {"GENERATE"}
    assert free_intro.most_used_voice("fr") is None


def test_voce_piu_usata_a_parita_la_prima_in_ordine(monkeypatch):
    monkeypatch.setattr(free_intro.activity_log, "iter_rows",
                        lambda *a, **k: iter(_righe("it-IT-ElsaNeural", "it-IT-DiegoNeural")))
    assert free_intro.most_used_voice("it") == "it-IT-DiegoNeural"


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
    monkeypatch.setattr(free_intro, "most_used_voice", lambda lang: "it-IT-DiegoNeural")
    primo = free_intro.prepare({}, "it-IT-IsabellaNeural", "it", tmp_path / "a.mp3")
    assert primo == {"path": str(tmp_path / "a.mp3"), "lang": "it",
                     "voice": "it-IT-DiegoNeural", "cached": False}
    secondo = free_intro.prepare({}, "it-IT-ElsaNeural", "it", tmp_path / "b.mp3")
    assert secondo["cached"] is True and secondo["voice"] == "it-IT-DiegoNeural"
    assert acceso == ["it-IT-DiegoNeural"]
    assert (tmp_path / "b.mp3").read_bytes() == b"\x02" * 500
    assert sorted(f.suffix for f in _cache(tmp_path).iterdir()) == [".json", ".mp3"]


def test_voce_del_json_se_la_piu_usata_non_da_audio(acceso, monkeypatch, tmp_path):
    monkeypatch.setattr(free_intro, "most_used_voice", lambda lang: "it-IT-DiegoNeural")
    finta = free_intro._synth

    def diego_muto(text, voice, out_path):
        if voice == "it-IT-DiegoNeural":
            acceso.append(voice)
            return False
        return finta(text, voice, out_path)
    monkeypatch.setattr(free_intro, "_synth", diego_muto)
    out = free_intro.prepare({}, "it-IT-IsabellaNeural", "it", tmp_path / "a.mp3")
    assert out["voice"] == "it-IT-ElsaNeural"
    assert acceso == ["it-IT-DiegoNeural", "it-IT-ElsaNeural"]


def test_log_illeggibile_voce_del_json(acceso, monkeypatch, tmp_path):
    def rotto(lang):
        raise OSError("log assente")
    monkeypatch.setattr(free_intro, "most_used_voice", rotto)
    assert free_intro.prepare({}, "de-DE-ConradNeural", "de", tmp_path / "a.mp3")["voice"] \
        == "de-DE-KatjaNeural"


def test_nessun_audio_niente_in_cache(acceso, monkeypatch, tmp_path):
    monkeypatch.setattr(free_intro, "_synth", lambda *a: False)
    assert free_intro.prepare({}, "it-IT-ElsaNeural", "it", tmp_path / "a.mp3") is None
    assert not any(_cache(tmp_path).iterdir())
    assert not (tmp_path / "a.mp3").exists()


def test_testo_cambiato_rigenera_e_toglie_il_vecchio(acceso, monkeypatch, tmp_path):
    free_intro.prepare({}, "it-IT-ElsaNeural", "it", tmp_path / "a.mp3")
    free_intro.prepare({}, "en-US-JennyNeural", "en", tmp_path / "b.mp3")
    tabella = dict(i18n.load("free_intro"))
    tabella["it"] = {"text": "Testo nuovo. Buon ascolto!", "voice": "it-IT-ElsaNeural"}
    monkeypatch.setattr(free_intro.i18n, "load", lambda name: tabella)
    assert free_intro.prepare({}, "it-IT-ElsaNeural", "it", tmp_path / "c.mp3")["cached"] is False
    nomi = sorted(f.name for f in _cache(tmp_path).glob("*.mp3"))
    assert len(nomi) == 2 and nomi[0].startswith("en-") and nomi[1].startswith("it-")
    assert nomi[1] == free_intro._cache_file("it", "Testo nuovo. Buon ascolto!").name


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
    assert job["free_intro"] == {"lang": "en", "voice": "en-US-JennyNeural", "cached": False}
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
