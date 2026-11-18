"""Prefisso corto VoxCPM: il campione tagliato alla fine di una frase.

Il taglio (`voice_clone_audio.choose_cut`), il wav troncato e l'uso che ne
fa `voxcpm_tts.clone_block`, con la memoria su disco del taglio per voce.
"""
import base64
import io
import json
import os
import wave

import numpy as np
import pytest

import community_store
import storage_backend
import voice_clone as vc
import voice_clone_audio as vca
import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
SR = 24000
TESTO = ("Ogni mattina cammino lungo il fiume. Vi siete mai fermati a guardare "
         "il cielo? Mi aiuta a pensare.")


def _campione(tratti):
    """Rumore dove si parla, silenzio nelle pause: `[(inizio, fine)]`. La
    coda muta serve al rilevatore di pause, che misura il fondo sul 10% piu'
    quieto del campione."""
    fine = max(b for _, b in tratti) + 2.5
    x = np.zeros(int(fine * SR), dtype=np.float32)
    rng = np.random.default_rng(7)
    for a, b in tratti:
        x[int(a * SR):int(b * SR)] = rng.uniform(-0.3, 0.3, int(b * SR) - int(a * SR))
    return x


def _parole(testo, a, b):
    ps = testo.split()
    passo = (b - a) / len(ps)
    return [(p, a + i * passo, a + (i + 1) * passo) for i, p in enumerate(ps)]


# tre frasi: 0-7 s, 7.6-13 s, 13.5-17 s
TRATTI = [(0.0, 7.0), (7.6, 13.0), (13.5, 17.0)]
FRASI = ["Ogni mattina cammino lungo il fiume.",
         "Vi siete mai fermati a guardare il cielo?", "Mi aiuta a pensare."]
PAROLE = sum((_parole(f, a, b) for f, (a, b) in zip(FRASI, TRATTI)), [])


def test_taglio_alla_fine_della_frase_piu_vicina_al_bersaglio():
    x = _campione(TRATTI)
    t = vca.choose_cut(PAROLE, TESTO, x, SR, 8.0)
    assert t["text"] == FRASI[0]
    assert 7.0 < t["cut_s"] <= 7.0 + vca.PREFIX_TAIL_SEC + 0.05
    # con un bersaglio piu' lungo si tiene anche la seconda frase
    t = vca.choose_cut(PAROLE, TESTO, x, SR, 13.0)
    assert t["text"] == FRASI[0] + " " + FRASI[1] and 13.0 < t["cut_s"] < 13.5


def test_niente_taglio_se_whisper_ha_sentito_altro_intorno_al_punto():
    x = _campione(TRATTI)
    altre = [("tutt'altro", a, b) for _, a, b in PAROLE]
    assert vca.choose_cut(altre, TESTO, x, SR, 8.0) is None


def test_niente_taglio_con_una_frase_sola_o_troppo_corto():
    x = _campione([(0.0, 17.0)])
    una = "Ogni mattina cammino lungo il fiume senza fermarmi mai."
    assert vca.choose_cut(_parole(una, 0.0, 17.0), una, x, SR, 8.0) is None
    # la prima frase finisce prima di PREFIX_MIN_SEC e l'ultima pausa lascia
    # meno di PREFIX_KEEP_SEC da togliere
    tratti = [(0.0, 3.0), (3.5, 9.0), (9.5, 9.6)]
    parole = sum((_parole(f, a, b) for f, (a, b) in zip(FRASI, tratti)), [])
    assert vca.choose_cut(parole, TESTO, _campione(tratti), SR, 8.0) is None
    assert vca.choose_cut([], TESTO, x, SR, 8.0) is None
    assert vca.choose_cut(PAROLE, TESTO, _campione(TRATTI), SR, 0.0) is None


def test_fine_frase_latina_cinese_e_hindi():
    trova = lambda s: [s[:m.end()] for m in vca._FINE_FRASE_RE.finditer(s)]
    assert trova("Costa 12.5 euro. Davvero? Si.") == [
        "Costa 12.5 euro.", "Costa 12.5 euro. Davvero?", "Costa 12.5 euro. Davvero? Si."]
    assert trova("Les arbres ? Oui.")[0] == "Les arbres ?"
    assert trova("用不了。我在查地址。")[0] == "用不了。"
    assert trova("रहा था। जब मैं")[0] == "रहा था।"


def test_cut_wav_bytes_tronca_e_sfuma(tmp_path):
    p = str(tmp_path / "s.wav")
    vca.write_wav(p, np.full(SR * 4, 0.5, dtype=np.float32), SR)
    with wave.open(io.BytesIO(vca.cut_wav_bytes(p, 1.5)), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (SR, 1, 2)
        assert w.getnframes() == int(1.5 * SR)
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    assert pcm[0] > 16000 and abs(int(pcm[-1])) < 200
    stereo = str(tmp_path / "st.wav")
    with wave.open(stereo, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(b"\0" * 400)
    with pytest.raises(ValueError):
        vca.cut_wav_bytes(stereo, 1.0)


def test_transcribe_riporta_le_parole_coi_tempi(monkeypatch, tmp_path):
    class _W:
        def __init__(self, w, a, b):
            self.word, self.start, self.end = w, a, b

    class _S:
        text = " ciao mondo"
        words = [_W(" ciao", 0.0, 0.4), _W(" mondo", 0.5, 0.9)]

    class _M:
        def transcribe(self, path, **kw):
            return iter([_S()]), None
    vca.init(str(tmp_path))
    vca.unload_asr()
    monkeypatch.setattr(vca, "_new_model", lambda name, root: _M())
    out = vca.check_transcript("x.wav", "it", "ciao mondo")
    vca.unload_asr()
    assert out["heard"] == "ciao mondo" and out["cer"] == 0.0
    assert out["words"] == [("ciao", 0.0, 0.4), ("mondo", 0.5, 0.9)]


# --- clone_block ----------------------------------------------------------
@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_PREFIX_TARGET_SEC", "8")
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    monkeypatch.setattr(voxcpm_tts, "_prefissi_riprova", {})
    voxcpm_catalog.invalidate_cache()
    yield tmp_path
    voxcpm_catalog.invalidate_cache()


def _voce(tmp_path):
    s = tmp_path / "s.wav"
    vca.write_wav(str(s), _campione(TRATTI), SR)
    o = tmp_path / "o.webm"; o.write_bytes(b"webm")
    return vc.create_draft("cid-x", lang="it", locale="it-IT", gender="f", prompt_text=TESTO,
                           sample_wav=str(s), original_path=str(o), original_ext="webm",
                           metrics={}, ui_lang="it")


def _secondi(blocco):
    with wave.open(io.BytesIO(base64.b64decode(blocco["prompt_wav_b64"])), "rb") as w:
        return w.getnframes() / w.getframerate()


def _finto_asr(monkeypatch, esito):
    chiamate = []

    def _short(wav_path, language, transcript, *, target=None, timeout=None):
        chiamate.append((language, transcript, target))
        if isinstance(esito, Exception):
            raise esito
        return esito
    monkeypatch.setattr(vca, "short_prefix", _short)
    return chiamate


def test_clone_block_manda_il_prefisso_corto_e_lo_ricorda(ambiente, monkeypatch):
    rec = _voce(ambiente)
    vid = vc.voice_id_of(rec)
    chiamate = _finto_asr(monkeypatch, {"cut_s": 7.25, "text": FRASI[0]})
    blocco = voxcpm_tts.clone_block(vid)
    assert blocco["prompt_text"] == FRASI[0]
    assert _secondi(blocco) == pytest.approx(7.25, abs=0.01)
    assert blocco["reference_wav_b64"] == blocco["prompt_wav_b64"]
    assert chiamate == [("it", TESTO, 8.0)]
    # su disco sotto l'id del record, mai sotto il token
    scritto = (ambiente / "voxcpm_prefissi.json").read_text(encoding="utf-8")
    assert f"mine:{rec['id']}" in json.loads(scritto) and rec["token"] not in scritto
    # dopo un riavvio (cache in memoria vuota) non si ritrascrive
    voxcpm_tts.invalidate_clone_cache()
    assert voxcpm_tts.clone_block(vid) == blocco and len(chiamate) == 1


def test_clone_block_spento_o_senza_taglio_manda_il_campione_intero(ambiente, monkeypatch):
    rec = _voce(ambiente)
    vid = vc.voice_id_of(rec)
    chiamate = _finto_asr(monkeypatch, None)
    blocco = voxcpm_tts.clone_block(vid)
    assert blocco["prompt_text"] == TESTO and _secondi(blocco) > 17.0
    # il «nessun taglio» resta scritto: niente trascrizione a ogni capitolo
    voxcpm_tts.invalidate_clone_cache()
    voxcpm_tts.clone_block(vid)
    assert len(chiamate) == 1
    monkeypatch.setenv("ABM_VOXCPM_PREFIX_TARGET_SEC", "0")
    voxcpm_tts.invalidate_clone_cache()
    assert voxcpm_tts.clone_block(vid)["prompt_text"] == TESTO and len(chiamate) == 1


def test_clone_block_whisper_occupato_non_si_scrive_e_si_riprova_dopo(ambiente, monkeypatch):
    rec = _voce(ambiente)
    vid = vc.voice_id_of(rec)
    chiamate = _finto_asr(monkeypatch, vca.AsrUnavailable("occupato"))
    assert voxcpm_tts.clone_block(vid)["prompt_text"] == TESTO
    assert not (ambiente / "voxcpm_prefissi.json").exists()
    voxcpm_tts.invalidate_clone_cache()
    voxcpm_tts.clone_block(vid)
    assert len(chiamate) == 1                     # dentro la pausa non si insiste
    monkeypatch.setattr(voxcpm_tts, "_prefissi_riprova", {})
    chiamate = _finto_asr(monkeypatch, {"cut_s": 7.25, "text": FRASI[0]})
    assert voxcpm_tts.clone_block(vid)["prompt_text"] == FRASI[0] and len(chiamate) == 1


def test_clone_block_cambio_di_bersaglio_rifa_il_taglio(ambiente, monkeypatch):
    vid = vc.voice_id_of(_voce(ambiente))
    chiamate = _finto_asr(monkeypatch, {"cut_s": 7.25, "text": FRASI[0]})
    voxcpm_tts.clone_block(vid)
    monkeypatch.setenv("ABM_VOXCPM_PREFIX_TARGET_SEC", "12")
    voxcpm_tts.clone_block(vid)
    assert [c[2] for c in chiamate] == [8.0, 12.0]


def test_clone_block_di_catalogo_taglia_con_la_lingua_della_voce(ambiente, monkeypatch):
    rec = voxcpm_catalog.voices()[0]
    frase = rec["transcript"].split(".")[0] + "."
    chiamate = _finto_asr(monkeypatch, {"cut_s": 7.0, "text": frase})
    blocco = voxcpm_tts.clone_block(rec["id"])
    assert chiamate == [(rec["lang"], rec["transcript"], 8.0)]
    assert blocco["prompt_text"] == frase
    assert rec["id"] in voxcpm_tts._prefissi.read()


def test_prefissi_vecchi_escono(ambiente, monkeypatch):
    with voxcpm_tts._prefissi.mutate() as d:
        d["vecchia"] = {"sig": "x", "ts": 1, "cut_s": 7.0, "text": "a"}
        d["nuova"] = {"sig": "y", "ts": 4102444800, "cut_s": 7.0, "text": "a"}
    assert list(voxcpm_tts._prefissi.read()) == ["nuova"]


# --- durata minima (stop_min_cps) -------------------------------------------
def test_stop_min_cps_segue_il_passo_del_campione_intero(ambiente, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_PREFIX_TARGET_SEC", "0")
    rec = voxcpm_catalog.voices()[0]
    atteso = round(len(rec["transcript"]) / rec["duration_s"] * 1.6, 1)
    assert voxcpm_tts.clone_block(rec["id"])["stop_min_cps"] == atteso
    # voce campionata: i secondi si leggono dal wav
    mia = vc.voice_id_of(_voce(ambiente))
    secondi = (max(b for _, b in TRATTI) + 2.5)
    assert voxcpm_tts.clone_block(mia)["stop_min_cps"] == round(len(TESTO) / secondi * 1.6, 1)
    # la leva si spegne dall'ambiente, e vale dal job dopo senza riavvio
    monkeypatch.setenv("ABM_VOXCPM_STOP_MIN_FACTOR", "0")
    assert "stop_min_cps" not in voxcpm_tts.clone_block(rec["id"])
    assert "stop_min_cps" not in voxcpm_tts.clone_block(mia)
    monkeypatch.setenv("ABM_VOXCPM_STOP_MIN_FACTOR", "2")
    assert voxcpm_tts.clone_block(rec["id"])["stop_min_cps"] == round(atteso / 1.6 * 2, 1)


def test_stop_min_cps_resta_quello_del_campione_intero_col_prefisso_corto(ambiente, monkeypatch):
    mia = vc.voice_id_of(_voce(ambiente))
    _finto_asr(monkeypatch, {"cut_s": 7.25, "text": FRASI[0]})
    blocco = voxcpm_tts.clone_block(mia)
    assert blocco["prompt_text"] == FRASI[0]
    assert blocco["stop_min_cps"] == round(len(TESTO) / 19.5 * 1.6, 1)


def test_passo_minimo_senza_misura_niente_leva():
    assert voxcpm_tts._passo_minimo("abc", None) is None
    assert voxcpm_tts._passo_minimo("abc", 0) is None
    assert voxcpm_tts._passo_minimo("", 10.0) is None
    assert voxcpm_tts._secondi_wav("non-esiste.wav") is None


# --- parentesi --------------------------------------------------------------
@pytest.mark.parametrize("prima, dopo", [
    ("spostabili (con sedie e tavoli di plastica) per agevolare",
     "spostabili, con sedie e tavoli di plastica, per agevolare"),
    ("terapeutica (TH), regalando", "terapeutica, TH, regalando"),
    ('mentale" (Barbiero e Berto, 2016, ).', 'mentale", Barbiero e Berto, 2016.'),
    ("Boccaccio (1313-1375).", "Boccaccio, 1313-1375."),
    ("costa 1,5 euro (circa)", "costa 1,5 euro, circa"),
    ("delle api..) e l'attenzione.", "delle api.. e l'attenzione."),
    ("ciao (uno (due) tre) fine", "ciao, uno, due, tre, fine"),
    ("vedi [12] poi", "vedi, 12, poi"),
    # un inciso dopo un punto fermo, o in testa prima di una maiuscola, e' una frase
    ('naturale." (Carta dei servizi) Si potrebbe', 'naturale." Carta dei servizi. Si potrebbe'),
    ("(Carta dei Servizi, 2020) Nel 1986", "Carta dei Servizi, 2020. Nel 1986"),
    ("fine frase. (Nota a parte.) Poi", "fine frase. Nota a parte. Poi"),
    # parentesi spaiate: il segno sparisce, il testo resta
    ("com) Parallelamente", "com, Parallelamente"),
    ("della sua specie (Arendt, cit.", "della sua specie, Arendt, cit."),
    ("(solo)", "solo"),
    ("senza parentesi, 1,5.", "senza parentesi, 1,5."),
    ("", ""),
])
def test_sciogli_parentesi(prima, dopo):
    assert voxcpm_tts.sciogli_parentesi(prima) == dopo


def test_chunk_pronti_non_manda_parentesi_al_modello():
    pronti = voxcpm_tts._chunk_pronti(["Uno (due) tre.", "Quattro."], "cap")
    assert pronti == ["Uno, due, tre.", "Quattro."]
