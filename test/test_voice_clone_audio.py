"""Gate acustico delle voci campionate (spec §5.2, §5.3), senza ffmpeg.

I segnali sono sintetici e deterministici: raffiche di rumore bianco a
-20 dBFS (il "parlato") separate da pause, sopra un fondo bianco a -80 dBFS.
Le misure del worker (`tools/voice_prompts/audio.py`) le trattano come
parlato pulito; ogni difetto e' costruito alterando una cosa sola.
"""
import numpy as np
import pytest

import voice_clone_audio as vca

SR = vca.SAMPLE_RATE


def _db(v):
    return 10.0 ** (v / 20.0)


def _parlato(seconds=15.0, burst=0.45, pause=0.15, level_db=-20.0,
             floor_db=-80.0, lowpass_hz=None, seed=7):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    x = rng.standard_normal(n).astype(np.float32) * _db(floor_db)
    t = 0.0
    while t < seconds:
        a, b = int(t * SR), min(n, int((t + burst) * SR))
        x[a:b] += rng.standard_normal(b - a).astype(np.float32) * _db(level_db)
        t += burst + pause
    if lowpass_hz:
        spec = np.fft.rfft(x.astype(np.float64))
        freq = np.fft.rfftfreq(n, 1.0 / SR)
        spec[freq > lowpass_hz] = 0.0
        x = np.fft.irfft(spec, n=n).astype(np.float32)
    return x


def test_parlato_pulito_passa():
    mt = vca.apply_gate(vca.measure(_parlato(), SR), SR)
    assert mt.reasons == [], mt
    assert 12.0 <= mt.duration <= 20.0
    assert mt.snr_db >= 22.0 and mt.clarity >= 36.0
    assert 0.55 <= mt.speech_ratio <= 0.98
    assert mt.bandwidth_hz >= 0.78 * SR / 2
    assert mt.clip_runs == 0


def test_troppo_breve():
    mt = vca.apply_gate(vca.measure(_parlato(seconds=6.0), SR), SR)
    assert mt.reasons[0] == "vc_gate_short"


def test_troppo_lunga():
    mt = vca.apply_gate(vca.measure(_parlato(seconds=24.0), SR), SR)
    assert mt.reasons[0] == "vc_gate_long"


def test_fondo_rumoroso():
    mt = vca.apply_gate(vca.measure(_parlato(floor_db=-32.0), SR), SR)
    assert "vc_gate_noise" in mt.reasons


def test_pausa_interna_lunga():
    x = _parlato(seconds=15.0)
    x[int(6.0 * SR):int(7.6 * SR)] = 0.0          # buco da 1,6 s
    mt = vca.apply_gate(vca.measure(x, SR), SR)
    assert "vc_gate_pauses" in mt.reasons
    assert mt.longest_gap > 1.0


def test_poco_parlato():
    mt = vca.apply_gate(vca.measure(_parlato(burst=0.3, pause=0.5), SR), SR)
    assert "vc_gate_pauses" in mt.reasons


def test_nessuna_pausa():
    """Micro-pause sotto i 40 ms: la maschera le chiude come occlusive,
    quindi per il VAD e' parlato continuo senza una pausa vera."""
    mt = vca.apply_gate(vca.measure(_parlato(burst=0.10, pause=0.035), SR), SR)
    assert "vc_gate_nopause" in mt.reasons
    assert mt.speech_ratio > 0.98


def test_banda_tagliata():
    mt = vca.apply_gate(vca.measure(_parlato(lowpass_hz=6000), SR), SR)
    assert "vc_gate_band" in mt.reasons
    assert mt.bandwidth_hz < 7000


def test_clipping():
    x = np.clip(_parlato(level_db=-2.0) * 4.0, -1.0, 1.0)
    mt = vca.apply_gate(vca.measure(x, SR), SR)
    assert "vc_gate_clip" in mt.reasons
    assert mt.clip_runs > 4


def test_gate_da_env(monkeypatch):
    monkeypatch.setenv("ABM_VOICE_CLONE_MIN_SEC", "3")
    monkeypatch.setenv("ABM_VOICE_CLONE_MAX_SEC", "8")
    g = vca.gate_from_env()
    assert (g.min_sec, g.max_sec) == (3.0, 8.0)
    mt = vca.apply_gate(vca.measure(_parlato(seconds=6.0), SR), SR, g)
    assert "vc_gate_short" not in mt.reasons


def test_trim_edges_taglia_i_silenzi_ma_lascia_il_margine():
    core = _parlato(seconds=4.0)
    x = np.concatenate([np.zeros(2 * SR, np.float32), core, np.zeros(3 * SR, np.float32)])
    y = vca.trim_edges(x, SR, pad_ms=300.0)
    assert abs(len(y) / SR - 4.6) < 0.15          # 4 s + 2 x 0,3 s


def test_wav_roundtrip(tmp_path):
    x = _parlato(seconds=2.0)
    p = tmp_path / "a.wav"
    vca.write_wav(str(p), x, SR)
    y, sr = vca.read_wav(str(p))
    assert sr == SR and len(y) == len(x)
    assert np.max(np.abs(y - x)) < 1e-3
