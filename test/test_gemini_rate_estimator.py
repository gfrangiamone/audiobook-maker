"""Regressioni sull'estimatore empirico char/sec di Gemini TTS.

Copre i difetti trovati nell'analisi dell'audit reale (giu-ago 2026) dopo
l'incidente del preventivo salito da 69,26 a 82,82 EUR sullo stesso libro:

  * finestra troppo stretta (20 campioni) -> un solo job decideva il prezzo;
  * nessun clamp -> deriva libera del rate;
  * chiave con il modello (irrilevante) e senza la voce (rilevante);
  * mescolanza di campioni presi a velocita` diverse;
  * campioni cinesi (~4 char/sec) scartati dal filtro outlier;
  * token audio/secondo di flash31 a 29-30 contro i 25 misurati.
"""
import importlib
import pytest

gemini_tts = importlib.import_module("gemini_tts")


@pytest.fixture
def rate_log(tmp_path, monkeypatch):
    """Isola il log dei rate su file temporaneo e lo svuota."""
    monkeypatch.setattr(gemini_tts, "_data_dir", tmp_path, raising=False)
    monkeypatch.setattr(gemini_tts, "_rate_log_path", None, raising=False)
    monkeypatch.setattr(gemini_tts, "_rate_log_cache", {"samples": []}, raising=False)
    return tmp_path


def _feed(n, chars, secs, lang="en", model="flash31", voice="Algenib",
          job="job1", rate_pct=0):
    for i in range(n):
        gemini_tts.record_rate_sample(chars, secs, lang, model,
                                      rate_pct=rate_pct, voice=voice,
                                      job_id=f"{job}-{i // 1000}")


# ── tok/s: il difetto piu` costoso ──────────────────────────────────────────

def test_audio_tokens_per_second_default_e_25_per_entrambi_i_modelli(monkeypatch):
    monkeypatch.delenv("ABM_GEMINI_AUDIO_TOKENS_PER_SECOND", raising=False)
    monkeypatch.delenv("ABM_GEMINI_AUDIO_TOKENS_PER_SECOND_FLASH31", raising=False)
    monkeypatch.delenv("ABM_GEMINI_AUDIO_TOKENS_PER_SECOND_FLASH25", raising=False)
    assert gemini_tts._audio_tokens_per_second("flash25") == 25.0
    assert gemini_tts._audio_tokens_per_second("flash31") == 25.0


# ── baseline per lingua ─────────────────────────────────────────────────────

def test_baseline_rate_per_lingua_e_default():
    assert gemini_tts.baseline_rate("zh") == pytest.approx(4.0)
    assert gemini_tts.baseline_rate("en") == pytest.approx(13.4)
    assert gemini_tts.baseline_rate("it") == pytest.approx(14.6)
    # lingua senza dati -> mediana globale, non la vecchia costante 15
    assert gemini_tts.baseline_rate("hi") == pytest.approx(gemini_tts.CHARS_PER_AUDIO_SECOND)
    assert gemini_tts.baseline_rate(None) == pytest.approx(gemini_tts.CHARS_PER_AUDIO_SECOND)


def test_stima_senza_campioni_usa_baseline_di_lingua(rate_log):
    testo = "a" * 10000
    sec_zh = gemini_tts.estimate_audio_seconds(testo, language="zh", model_key="flash31")
    sec_en = gemini_tts.estimate_audio_seconds(testo, language="en", model_key="flash31")
    # il cinese e` ~3.4x piu` lento: prima entrambi usavano 15 char/sec
    assert sec_zh > sec_en * 3
    assert sec_en == pytest.approx(10000 / 13.4, rel=0.01)


# ── finestra e dominanza di un singolo job ──────────────────────────────────

def test_finestra_ha_un_pavimento_non_aggirabile_da_env():
    assert gemini_tts.RATE_LOG_WINDOW >= gemini_tts.RATE_LOG_WINDOW_FLOOR
    assert gemini_tts.RATE_LOG_MIN_SAMPLES >= gemini_tts.RATE_LOG_MIN_SAMPLES_FLOOR


def test_un_singolo_job_non_riscrive_il_rate_della_lingua(rate_log):
    # storia lunga a 14.0 char/sec da molti job diversi
    for j in range(20):
        _feed(30, 420, 30.0, voice="Algenib", job=f"storico{j}")
    prima = gemini_tts.get_empirical_rate("en", "flash31", voice="Algenib")
    assert prima == pytest.approx(14.0, rel=0.02)
    # un solo job lento (11 char/sec) con 500 chunk: prima bastavano 20 campioni
    _feed(500, 330, 30.0, voice="Algenib", job="lento")
    dopo = gemini_tts.get_empirical_rate("en", "flash31", voice="Algenib")
    assert dopo > 12.5, f"un solo job ha spostato il rate a {dopo:.2f}"


# ── clamp ───────────────────────────────────────────────────────────────────

def test_rate_clampato_alla_banda_della_lingua(rate_log):
    _feed(300, 200, 40.0, lang="en", voice="Lento")   # 5 char/sec
    r = gemini_tts.get_empirical_rate("en", "flash31", voice="Lento")
    assert r == pytest.approx(13.4 * gemini_tts.RATE_CLAMP_LOW, rel=0.01)
    _feed(300, 400, 10.0, lang="en", voice="Veloce")  # 40 char/sec
    r = gemini_tts.get_empirical_rate("en", "flash31", voice="Veloce")
    assert r == pytest.approx(13.4 * gemini_tts.RATE_CLAMP_HIGH, rel=0.01)


# ── chiave: voce si`, modello no, velocita` non mescolata ───────────────────

def test_voci_diverse_hanno_rate_diversi(rate_log):
    _feed(300, 450, 30.0, voice="Veloce", job="a")    # 15.0
    _feed(300, 360, 30.0, voice="Lenta", job="b")     # 12.0
    assert gemini_tts.get_empirical_rate("en", "flash31", voice="Veloce") == pytest.approx(15.0, rel=0.02)
    assert gemini_tts.get_empirical_rate("en", "flash31", voice="Lenta") == pytest.approx(12.0, rel=0.02)


def test_modello_non_partiziona_i_campioni(rate_log):
    _feed(300, 420, 30.0, model="flash25", voice="Algenib", job="a")
    # nessun campione flash31, ma il rate deve esserci lo stesso: il modello
    # non entra nella chiave
    assert gemini_tts.get_empirical_rate("en", "flash31", voice="Algenib") == pytest.approx(14.0, rel=0.02)


def test_campioni_a_velocita_diversa_non_vengono_mescolati(rate_log):
    _feed(300, 450, 30.0, voice="Algenib", job="fast", rate_pct=20)   # step +2
    r = gemini_tts.get_empirical_rate("en", "flash31", rate_step=0, voice="Algenib")
    assert r is None, f"campioni a +20% usati per una stima a velocita` normale ({r})"


# ── outlier filter ──────────────────────────────────────────────────────────

def test_campioni_cinesi_non_vengono_scartati(rate_log):
    _feed(300, 160, 40.0, lang="zh", voice="Algenib", job="zh")       # 4 char/sec
    r = gemini_tts.get_empirical_rate("zh", "flash31", voice="Algenib")
    assert r is not None and r == pytest.approx(4.0, rel=0.05)


def test_outlier_estremi_restano_scartati(rate_log):
    gemini_tts.record_rate_sample(1000, 1.0, "en", "flash31", voice="X", job_id="j")
    gemini_tts.record_rate_sample(1, 100.0, "en", "flash31", voice="X", job_id="j")
    assert gemini_tts._load_rate_log()["samples"] == []


# ── integrazione: la voce arriva fino a estimate_book_cost ──────────────────

def test_estimate_book_cost_usa_la_voce(rate_log):
    class Ch:
        def __init__(self, t): self.text = t
    chs = [Ch("Questo e' un capitolo di prova. " * 200)]
    _feed(300, 450, 30.0, voice="Algenib", job="a")   # 15.0
    _feed(300, 360, 30.0, voice="Enceladus", job="b")  # 12.0
    veloce = gemini_tts.estimate_book_cost(chs, "gemini:flash31:Algenib", language="en")
    lenta = gemini_tts.estimate_book_cost(chs, "gemini:flash31:Enceladus", language="en")
    assert veloce["voice"] == "Algenib"
    assert lenta["audio_seconds_est"] > veloce["audio_seconds_est"] * 1.15
