"""Test del banco di prova Cloudflare Gemini TTS (scripts/tts_cloudflare_gemini_test.py).

Nessuna chiamata di rete: la sessione HTTP e' sempre mockata.
"""
import importlib.util
import io
import os
import wave

import pytest

_BENCH_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "tts_cloudflare_gemini_test.py",
)

if not os.path.exists(_BENCH_PATH):
    pytest.skip("bench Cloudflare non presente in questa copia di lavoro",
                allow_module_level=True)

_spec = importlib.util.spec_from_file_location("cf_bench", _BENCH_PATH)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def make_wav(seconds=1.0, rate=24000, channels=1, width=2):
    """WAV in memoria, silenzio, formato parametrico."""
    frames = b"\x00" * int(rate * seconds) * channels * width
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(frames)
    return buf.getvalue()


def test_wav_bytes_to_pcm_estrae_formato_e_byte(tmp_path):
    out = str(tmp_path / "chunk.pcm")
    fmt = bench.wav_bytes_to_pcm(make_wav(seconds=2.0), out)
    assert fmt == {"rate": 24000, "channels": 1, "width": 2, "bytes": 96000}
    assert os.path.getsize(out) == 96000


def test_wav_bytes_to_pcm_rifiuta_payload_non_wav(tmp_path):
    with pytest.raises(bench.WavFormatError):
        bench.wav_bytes_to_pcm(b"non sono un wav", str(tmp_path / "x.pcm"))


def test_wav_bytes_to_pcm_rifiuta_wav_senza_frame(tmp_path):
    with pytest.raises(bench.WavFormatError):
        bench.wav_bytes_to_pcm(make_wav(seconds=0.0), str(tmp_path / "x.pcm"))


def test_resolve_credentials_ok(monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc123")
    monkeypatch.setenv("CF_API_TOKEN", "tok-super-segreto")
    assert bench.resolve_credentials() == ("acc123", "tok-super-segreto")


def test_resolve_credentials_manca_token_e_non_lo_stampa(monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc123")
    monkeypatch.delenv("CF_API_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        bench.resolve_credentials()
    msg = str(exc.value)
    assert "CF_API_TOKEN" in msg
    assert "tok-super-segreto" not in msg


def test_estimate_tokens_usa_25_token_al_secondo():
    got = bench.estimate_tokens(chars=400, audio_seconds=40.0, language="it")
    # 400 char it / 4.0 char-per-token = 100 token input; 40 s * 25 = 1000 output
    assert got == {"tokens_in": 100, "tokens_out": 1000}


def test_cost_usd_tariffe_cloudflare():
    assert bench.cost_usd(1000, 100000) == pytest.approx(1.20075)


def test_predict_call_usd_da_baseline_lingua():
    # 1460 char it / 14.6 char-sec = 100 s -> 2500 token out; 365 token in
    atteso = 365 * 0.75 / 1e6 + 2500 * 12.0 / 1e6
    assert bench.predict_call_usd(1460, "it") == pytest.approx(atteso)


def test_spend_guard_accumula_e_converte_in_euro():
    guard = bench.SpendGuard(max_eur=1.0)
    guard.add(0.5)
    guard.add(0.25)
    assert guard.spent_usd == pytest.approx(0.75)
    assert guard.spent_eur() == pytest.approx(0.645)


def test_spend_guard_blocca_oltre_il_cap():
    guard = bench.SpendGuard(max_eur=1.0)
    guard.add(1.10)  # 0.946 EUR
    guard.check(0.05)  # 0.989 EUR: ancora sotto, non solleva
    guard.add(0.05)
    with pytest.raises(bench.SpendCapExceeded):
        guard.check(0.10)


def test_spend_guard_cap_zero_disattiva_il_controllo():
    guard = bench.SpendGuard(max_eur=0)
    guard.add(999.0)
    guard.check(999.0)  # nessuna eccezione


def test_evaluate_duration_nella_banda_nessuna_anomalia():
    got = bench.evaluate_duration(chars=1460, language="it", audio_seconds=90.0)
    assert got["expected_seconds"] == pytest.approx(100.0)
    assert got["ratio"] == pytest.approx(0.9)
    assert got["anomaly"] is None


def test_evaluate_duration_troncato():
    got = bench.evaluate_duration(chars=1460, language="it", audio_seconds=55.0)
    assert got["anomaly"] == "truncated"


def test_evaluate_duration_troppo_lungo():
    got = bench.evaluate_duration(chars=1460, language="it", audio_seconds=170.0)
    assert got["anomaly"] == "overlong"


def test_evaluate_duration_audio_vuoto():
    got = bench.evaluate_duration(chars=1460, language="it", audio_seconds=0.0)
    assert got["anomaly"] == "empty"
    assert got["ratio"] == 0.0


def test_evaluate_duration_testo_vuoto_non_divide_per_zero():
    got = bench.evaluate_duration(chars=0, language="it", audio_seconds=0.0)
    assert got["anomaly"] == "empty"


def test_evaluate_duration_estremi_della_banda_sono_accettati():
    # ratio esattamente 0.6 e 1.6 non sono anomalie: la banda e' inclusiva
    assert bench.evaluate_duration(1460, "it", 60.0)["anomaly"] is None
    assert bench.evaluate_duration(1460, "it", 160.0)["anomaly"] is None


def test_evaluate_format_riconosce_il_formato_atteso():
    assert bench.evaluate_format({"rate": 24000, "channels": 1, "width": 2}) is None


def test_evaluate_format_segnala_divergenze():
    assert bench.evaluate_format({"rate": 16000, "channels": 1, "width": 2}) == "format"
    assert bench.evaluate_format({"rate": 24000, "channels": 2, "width": 2}) == "format"
