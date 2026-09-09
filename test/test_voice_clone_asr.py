"""Verifica ASR del campione (spec §5.4) con un modello finto: faster_whisper
non si importa mai qui."""
import threading
import time

import pytest

import voice_clone_audio as vca

# zhconv (dipendenza lazy di vca.flatten per il cinese) importa pkg_resources,
# deprecato a monte: non e' un warning nostro, va solo zittito qui.
pytestmark = pytest.mark.filterwarnings(
    "ignore:pkg_resources is deprecated as an API:DeprecationWarning"
)


class _Seg:
    def __init__(self, text):
        self.text = text
        self.words = [1]


class _Modello:
    """Doppio di WhisperModel: ritorna la frase che gli si dice, con ritardo."""

    def __init__(self, testo="", ritardo=0.0, errore=None):
        self.testo, self.ritardo, self.errore = testo, ritardo, errore
        self.chiamate = []

    def transcribe(self, path, **kw):
        self.chiamate.append((path, kw))
        if self.ritardo:
            time.sleep(self.ritardo)
        if self.errore:
            raise self.errore
        return iter([_Seg(self.testo)]), None


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    vca.init(str(tmp_path))
    vca.unload_asr()
    monkeypatch.delenv("ABM_VOICE_CLONE_ASR", raising=False)
    monkeypatch.delenv("ABM_VOICE_CLONE_MAX_CER", raising=False)
    yield
    vca.unload_asr()


def _usa(monkeypatch, **kw):
    """Sostituisce la fabbrica del modello; ritorna la lista delle istanze
    create, cosi' i test contano i caricamenti."""
    istanze = []

    def _fabbrica(name, root):
        istanze.append(_Modello(**kw))
        return istanze[-1]
    monkeypatch.setattr(vca, "_new_model", _fabbrica)
    return istanze


def test_cer_e_flatten_come_il_worker():
    assert vca.flatten("Ogni mattina, apro la finestra!") == "ognimattinaaprolafinestra"
    assert vca.cer("abc", "abc") == 0.0
    assert vca.cer("abcd", "abxd") == 0.25
    assert vca.cer("", "x") == 1.0
    # cinese: tradizionale e semplificato sono la stessa lettura
    assert vca.cer("心裡", "心里") == 0.0


def test_check_transcript_ok(monkeypatch, tmp_path):
    ist = _usa(monkeypatch, testo="Ogni mattina apro la finestra.")
    out = vca.check_transcript(str(tmp_path / "s.wav"), "it", "Ogni mattina apro la finestra")
    assert out["cer"] == 0.0 and out["heard"].startswith("Ogni")
    assert out["seconds"] >= 0.0
    assert ist[0].chiamate[0][1]["language"] == "it"
    assert ist[0].chiamate[0][1]["beam_size"] == 1


def test_modello_caricato_una_volta_sola(monkeypatch, tmp_path):
    ist = _usa(monkeypatch, testo="x")
    vca.check_transcript(str(tmp_path / "a.wav"), "it", "x")
    vca.check_transcript(str(tmp_path / "b.wav"), "it", "x")
    assert len(ist) == 1


def test_cer_alto_e_solo_un_numero(monkeypatch, tmp_path):
    _usa(monkeypatch, testo="tutta un'altra frase che non c'entra")
    out = vca.check_transcript(str(tmp_path / "s.wav"), "it", "Ogni mattina apro la finestra")
    assert out["cer"] > vca.max_cer()


def test_timeout_solleva_unavailable(monkeypatch, tmp_path):
    _usa(monkeypatch, testo="x", ritardo=1.0)
    with pytest.raises(vca.AsrUnavailable):
        vca.check_transcript(str(tmp_path / "s.wav"), "it", "x", timeout=0.2)


def test_errore_del_modello_solleva_unavailable(monkeypatch, tmp_path):
    _usa(monkeypatch, testo="x", errore=RuntimeError("ctranslate2 esploso"))
    with pytest.raises(vca.AsrUnavailable):
        vca.check_transcript(str(tmp_path / "s.wav"), "it", "x")


def test_caricamento_fallito_solleva_unavailable(monkeypatch, tmp_path):
    def _boom(name, root):
        raise OSError("download fallito")
    monkeypatch.setattr(vca, "_new_model", _boom)
    with pytest.raises(vca.AsrUnavailable):
        vca.check_transcript(str(tmp_path / "s.wav"), "it", "x")


def test_lock_occupato_solleva_unavailable(monkeypatch, tmp_path):
    _usa(monkeypatch, testo="x", ritardo=0.8)
    esiti = []

    def _prima():
        try:
            esiti.append(vca.check_transcript(str(tmp_path / "a.wav"), "it", "x", timeout=5))
        except Exception as e:
            esiti.append(e)
    t = threading.Thread(target=_prima, daemon=True)
    t.start()
    time.sleep(0.1)
    with pytest.raises(vca.AsrUnavailable):
        vca.check_transcript(str(tmp_path / "b.wav"), "it", "x", timeout=0.1)
    t.join(5)
    assert isinstance(esiti[0], dict)


def test_unload_dopo_inattivita(monkeypatch, tmp_path):
    ist = _usa(monkeypatch, testo="x")
    monkeypatch.setattr(vca, "ASR_IDLE_UNLOAD_SEC", 0.2)
    vca.check_transcript(str(tmp_path / "a.wav"), "it", "x")
    time.sleep(0.6)
    assert vca._asr_model is None
    vca.check_transcript(str(tmp_path / "b.wav"), "it", "x")
    assert len(ist) == 2


def test_env_interruttore_e_soglia(monkeypatch):
    assert vca.asr_enabled() is True
    monkeypatch.setenv("ABM_VOICE_CLONE_ASR", "0")
    assert vca.asr_enabled() is False
    monkeypatch.setenv("ABM_VOICE_CLONE_MAX_CER", "0,3")
    assert vca.max_cer() == 0.3
