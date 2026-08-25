"""Test del banco di prova Cloudflare Gemini TTS (scripts/tts_cloudflare_gemini_test.py).

Nessuna chiamata di rete: la sessione HTTP e' sempre mockata.
"""
import importlib.util
import io
import os
import threading
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


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = "corpo di risposta finto"

    def json(self):
        return self._payload


class FakeSession:
    """Sessione HTTP finta: restituisce le risposte in coda, una per chiamata.

    Thread-safe: un lock protegge l'avanzamento della coda di risposte e
    l'accodamento delle chiamate, cosi' i test di concorrenza del livello
    matrix non producono falsi fallimenti per interleaving fra thread.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self._lock = threading.Lock()

    def post(self, url, json=None, headers=None, timeout=None):
        with self._lock:
            self.calls.append({"url": url, "json": json, "headers": headers,
                               "timeout": timeout})
            return self._responses.pop(0)


def _ok_response(seconds=1.0):
    import base64
    return FakeResponse(200, {"result": {
        "audio": base64.b64encode(make_wav(seconds=seconds)).decode("ascii")}})


def test_build_payload_ha_modello_e_input():
    p = bench.build_payload("ciao", "Zephyr", 0.3)
    assert p["model"] == "google/gemini-3.1-flash-tts"
    assert p["input"]["text"] == "ciao"
    assert p["input"]["voice"] == "Zephyr"
    assert p["input"]["temperature"] == 0.3


def test_call_cf_successo_al_primo_tentativo():
    s = FakeSession([_ok_response()])
    got = bench.call_cf(s, "acc", "tok", "ciao", "Zephyr", 0.3, sleep=lambda _: None)
    assert got["status"] == 200
    assert got["attempts"] == 1
    assert got["wav"].startswith(b"RIFF")
    assert s.calls[0]["url"].endswith("/accounts/acc/ai/run")
    assert s.calls[0]["headers"]["Authorization"] == "Bearer tok"
    assert s.calls[0]["timeout"] == 60


def test_call_cf_ritenta_su_429_e_registra_gli_stati():
    s = FakeSession([FakeResponse(429, headers={"retry-after": "0"}), _ok_response()])
    got = bench.call_cf(s, "acc", "tok", "ciao", "Zephyr", 0.3, sleep=lambda _: None)
    assert got["attempts"] == 2
    assert got["retry_statuses"] == [429]


def test_call_cf_ritenta_su_5xx():
    s = FakeSession([FakeResponse(503), FakeResponse(500), _ok_response()])
    got = bench.call_cf(s, "acc", "tok", "ciao", "Zephyr", 0.3, sleep=lambda _: None)
    assert got["attempts"] == 3
    assert got["retry_statuses"] == [503, 500]


def test_call_cf_401_non_ritenta():
    s = FakeSession([FakeResponse(401)])
    with pytest.raises(bench.CFAuthError):
        bench.call_cf(s, "acc", "tok", "ciao", "Zephyr", 0.3, sleep=lambda _: None)
    assert len(s.calls) == 1


def test_call_cf_esaurisce_i_tentativi():
    s = FakeSession([FakeResponse(500)] * 4)
    with pytest.raises(bench.CFCallError) as exc:
        bench.call_cf(s, "acc", "tok", "ciao", "Zephyr", 0.3,
                      max_attempts=4, sleep=lambda _: None)
    assert exc.value.status == 500
    assert exc.value.attempts == 4


def test_call_cf_risposta_200_senza_audio_e_errore():
    s = FakeSession([FakeResponse(200, {"result": {}})])
    with pytest.raises(bench.CFCallError):
        bench.call_cf(s, "acc", "tok", "ciao", "Zephyr", 0.3,
                      max_attempts=1, sleep=lambda _: None)


def test_call_cf_non_stampa_il_token_negli_errori():
    s = FakeSession([FakeResponse(403)])
    with pytest.raises(bench.CFAuthError) as exc:
        bench.call_cf(s, "acc", "tok-super-segreto", "ciao", "Zephyr", 0.3,
                      sleep=lambda _: None)
    assert "tok-super-segreto" not in str(exc.value)


def test_call_cf_audio_non_base64_valido_e_errore():
    s = FakeSession([FakeResponse(200, {"result": {"audio": "not-valid-base64!!!"}})])
    with pytest.raises(bench.CFCallError):
        bench.call_cf(s, "acc", "tok", "ciao", "Zephyr", 0.3,
                      max_attempts=1, sleep=lambda _: None)


def test_call_cf_ritenta_su_errore_di_rete_poi_successo():
    class FlakySession:
        def __init__(self, fail_times, ok_response):
            self._fail_times = fail_times
            self._ok_response = ok_response
            self.calls = []

        def post(self, url, json=None, headers=None, timeout=None):
            self.calls.append({"url": url, "json": json, "headers": headers,
                               "timeout": timeout})
            if len(self.calls) <= self._fail_times:
                raise bench.requests.RequestException("errore di rete simulato")
            return self._ok_response

    s = FlakySession(fail_times=2, ok_response=_ok_response())
    got = bench.call_cf(s, "acc", "tok", "ciao", "Zephyr", 0.3, sleep=lambda _: None)
    assert got["attempts"] == 3
    assert got["retry_statuses"] == [0, 0]
    assert len(s.calls) == 3


SCHEMA_KEYS = {
    "ts", "run_id", "backend", "lang", "voice", "rate", "style_hash",
    "chunk_index", "chars", "prompt_bytes", "http_status", "latency_ms",
    "attempt", "audio_bytes", "audio_seconds", "expected_seconds", "ratio",
    "tokens_in_est", "tokens_out_est", "cost_usd_est", "anomaly",
}


def test_make_record_ha_esattamente_le_chiavi_di_schema():
    rec = bench.make_record(
        run_id="r1", backend="cloudflare", lang="it", voice="Zephyr",
        rate="+0%", style_hash="abc123", chunk_index=0, chars=450,
        prompt_bytes=460, http_status=200, latency_ms=1234.5, attempt=1,
        audio_bytes=96000, audio_seconds=2.0, expected_seconds=30.8,
        ratio=0.065, tokens_in_est=112, tokens_out_est=50,
        cost_usd_est=0.0007, anomaly="truncated",
    )
    assert set(rec) == SCHEMA_KEYS
    assert rec["ts"].endswith("Z")


def test_metrics_writer_scrive_una_riga_per_record(tmp_path):
    import json
    run_dir = str(tmp_path / "run")
    os.makedirs(run_dir)
    w = bench.MetricsWriter(run_dir)
    w.write({"a": 1})
    w.write({"a": 2})
    w.close()
    righe = open(os.path.join(run_dir, "metrics.jsonl"), encoding="utf-8").read().splitlines()
    assert [json.loads(r)["a"] for r in righe] == [1, 2]


def test_new_run_dir_crea_sottocartelle(tmp_path):
    run_dir = bench.new_run_dir(str(tmp_path), "smoke")
    assert os.path.isdir(os.path.join(run_dir, "audio"))
    assert os.path.isdir(os.path.join(run_dir, "prompts"))
    assert os.path.basename(run_dir).endswith("_smoke")


def _ctx(tmp_path, session, max_eur=10.0):
    run_dir = bench.new_run_dir(str(tmp_path), "test")
    return bench.BenchContext(
        session=session, account_id="acc", api_token="tok", run_dir=run_dir,
        writer=bench.MetricsWriter(run_dir), guard=bench.SpendGuard(max_eur),
        run_id="run-test", temperature=0.3, backend="cloudflare",
        sleep=lambda _: None,
    )


def test_synth_chunk_scrive_pcm_e_record(tmp_path):
    # 146 char it -> 10 s attesi; il WAV finto dura 9 s: ratio 0.9, nessuna anomalia
    ctx = _ctx(tmp_path, FakeSession([_ok_response(seconds=9.0)]))
    got = bench.synth_chunk(ctx, "a" * 146, 0, "it", "Zephyr", "+0%", None,
                            os.path.join(ctx.run_dir, "audio", "000.pcm"))
    assert got["anomaly"] is None
    assert got["retry_record"] is None
    assert got["record"]["audio_seconds"] == pytest.approx(9.0)
    assert got["record"]["chunk_index"] == 0
    assert got["record"]["backend"] == "cloudflare"
    assert os.path.getsize(got["pcm_path"]) == 9 * 24000 * 2
    ctx.writer.close()
    righe = open(ctx.writer.path, encoding="utf-8").read().splitlines()
    assert len(righe) == 1


def test_synth_chunk_ritenta_una_volta_l_anomalia(tmp_path):
    # primo WAV 2 s (ratio 0.2 -> truncated), secondo 9 s: il retry corregge
    ctx = _ctx(tmp_path, FakeSession([_ok_response(seconds=2.0),
                                      _ok_response(seconds=9.0)]))
    got = bench.synth_chunk(ctx, "a" * 146, 0, "it", "Zephyr", "+0%", None,
                            os.path.join(ctx.run_dir, "audio", "000.pcm"))
    assert got["record"]["anomaly"] == "truncated"
    assert got["retry_record"]["anomaly"] is None
    assert got["anomaly"] is None
    ctx.writer.close()
    righe = open(ctx.writer.path, encoding="utf-8").read().splitlines()
    assert len(righe) == 2


def test_synth_chunk_anomalia_persistente_resta(tmp_path):
    ctx = _ctx(tmp_path, FakeSession([_ok_response(seconds=2.0),
                                      _ok_response(seconds=2.0)]))
    got = bench.synth_chunk(ctx, "a" * 146, 0, "it", "Zephyr", "+0%", None,
                            os.path.join(ctx.run_dir, "audio", "000.pcm"))
    assert got["anomaly"] == "truncated"
    ctx.writer.close()


def test_synth_chunk_usa_il_prompt_di_produzione(tmp_path):
    import gemini_tts
    s = FakeSession([_ok_response(seconds=9.0)])
    ctx = _ctx(tmp_path, s)
    bench.synth_chunk(ctx, "a" * 146, 0, "it", "Zephyr", "+20%", "tono calmo",
                      os.path.join(ctx.run_dir, "audio", "000.pcm"))
    atteso = gemini_tts.build_final_text("a" * 146, style_instruction="tono calmo",
                                         rate="+20%")
    assert s.calls[0]["json"]["input"]["text"] == atteso
    ctx.writer.close()


def test_synth_chunk_rispetta_il_cap_di_spesa(tmp_path):
    ctx = _ctx(tmp_path, FakeSession([_ok_response(seconds=9.0)]), max_eur=0.000001)
    with pytest.raises(bench.SpendCapExceeded):
        bench.synth_chunk(ctx, "a" * 146, 0, "it", "Zephyr", "+0%", None,
                          os.path.join(ctx.run_dir, "audio", "000.pcm"))
    ctx.writer.close()


def test_synth_chunk_cf_call_error_non_interrompe_il_run(tmp_path):
    # 4x 500: call_cf esaurisce i propri tentativi e solleva CFCallError.
    # synth_chunk non deve propagarla: una riga "error", nessun secondo giro.
    import json
    s = FakeSession([FakeResponse(500)] * 4)
    ctx = _ctx(tmp_path, s)
    got = bench.synth_chunk(ctx, "a" * 146, 0, "it", "Zephyr", "+0%", None,
                            os.path.join(ctx.run_dir, "audio", "000.pcm"))
    assert got["anomaly"] == "error"
    assert got["retry_record"] is None
    assert got["pcm_path"] is None
    assert got["audio_seconds"] is None
    assert got["record"]["anomaly"] == "error"
    assert got["record"]["http_status"] == 500
    assert got["record"]["latency_ms"] is None
    assert got["record"]["audio_bytes"] is None
    assert got["record"]["ratio"] is None
    ctx.writer.close()
    righe = open(ctx.writer.path, encoding="utf-8").read().splitlines()
    assert len(righe) == 1
    assert json.loads(righe[0])["anomaly"] == "error"


def test_synth_chunk_cf_auth_error_si_propaga(tmp_path):
    # 401/403 e' abort immediato per spec: nessuna riga, l'eccezione esce.
    s = FakeSession([FakeResponse(403)])
    ctx = _ctx(tmp_path, s)
    with pytest.raises(bench.CFAuthError):
        bench.synth_chunk(ctx, "a" * 146, 0, "it", "Zephyr", "+0%", None,
                          os.path.join(ctx.run_dir, "audio", "000.pcm"))
    ctx.writer.close()
    righe = open(ctx.writer.path, encoding="utf-8").read().splitlines()
    assert len(righe) == 0


def _rec(**kw):
    base = dict(run_id="r", backend="cloudflare", lang="it", voice="Zephyr",
                rate="+0%", style_hash="0" * 8, chunk_index=0, chars=450,
                prompt_bytes=460, http_status=200, latency_ms=1000.0, attempt=1,
                audio_bytes=96000, audio_seconds=30.0, expected_seconds=30.8,
                ratio=0.97, tokens_in_est=112, tokens_out_est=750,
                cost_usd_est=0.00909, anomaly=None)
    base.update(kw)
    return bench.make_record(**base)


def test_percentiles_su_lista_nota():
    vals = [float(n) for n in range(1, 101)]
    got = bench.percentiles(vals)
    assert got["p50"] == pytest.approx(50.0, abs=1.0)
    assert got["p95"] == pytest.approx(95.0, abs=1.0)
    assert got["p99"] == pytest.approx(99.0, abs=1.0)


def test_percentiles_lista_vuota():
    assert bench.percentiles([]) == {"p50": 0.0, "p95": 0.0, "p99": 0.0}


def test_summarize_aggrega_costi_e_anomalie():
    got = bench.summarize([_rec(), _rec(anomaly="truncated"),
                           _rec(http_status=429, attempt=2)])
    assert got["calls"] == 3
    assert got["chars"] == 1350
    assert got["audio_seconds"] == pytest.approx(90.0)
    assert got["tokens_out"] == 2250
    assert got["cost_usd"] == pytest.approx(0.02727)
    assert got["cost_eur"] == pytest.approx(0.02727 * 0.86)
    assert got["anomalies"] == {"truncated": 1}
    assert got["http_429"] == 1


def test_reconciliation_block_riporta_la_finestra_e_i_totali():
    txt = bench.reconciliation_block([_rec(), _rec()])
    assert "RICONCILIAZIONE" in txt
    assert "richieste" in txt and "2" in txt
    assert "EUR" in txt


def test_render_report_marca_il_run_parziale(tmp_path):
    run_dir = bench.new_run_dir(str(tmp_path), "matrix")
    path = bench.render_report(run_dir, [_rec()], residual_anomalies=0,
                               partial=True, notes=["cap di spesa raggiunto"])
    testo = open(path, encoding="utf-8").read()
    assert "PARZIALE" in testo
    assert "cap di spesa raggiunto" in testo


def test_render_report_dichiara_le_anomalie_residue(tmp_path):
    run_dir = bench.new_run_dir(str(tmp_path), "matrix")
    path = bench.render_report(run_dir, [_rec(anomaly="truncated")],
                               residual_anomalies=1, partial=False, notes=[])
    assert "anomalie residue: 1" in open(path, encoding="utf-8").read()


def test_render_report_elenca_i_chunk_falliti(tmp_path):
    run_dir = bench.new_run_dir(str(tmp_path), "matrix")
    records = [
        _rec(chunk_index=0),
        _rec(chunk_index=1, anomaly="error", http_status=500, attempt=4,
             latency_ms=None, audio_bytes=None, audio_seconds=None, ratio=None),
        _rec(chunk_index=2, anomaly="error", http_status=None, attempt=None,
             latency_ms=None, audio_bytes=None, audio_seconds=None, ratio=None),
    ]
    path = bench.render_report(run_dir, records, residual_anomalies=2,
                               partial=False, notes=[])
    testo = open(path, encoding="utf-8").read()
    assert "chunk falliti (anomaly=error): 2" in testo
    assert "| 1 | 500 | 4 |" in testo
    assert "| 2 | - | - |" in testo


def test_render_report_senza_chunk_falliti_non_stampa_la_tabella(tmp_path):
    run_dir = bench.new_run_dir(str(tmp_path), "matrix")
    path = bench.render_report(run_dir, [_rec()], residual_anomalies=0,
                               partial=False, notes=[])
    testo = open(path, encoding="utf-8").read()
    assert "chunk falliti (anomaly=error): 0" in testo
    assert "| chunk_index | http_status | attempt |" not in testo


def test_summarize_tollera_i_record_error(tmp_path):
    records = [
        _rec(chunk_index=0),
        _rec(chunk_index=1, anomaly="error", http_status=None, attempt=None,
             latency_ms=None, audio_bytes=None, audio_seconds=None, ratio=None),
    ]
    agg = bench.summarize(records)
    assert agg["calls"] == 2
    assert agg["audio_seconds"] == pytest.approx(30.0)
    run_dir = bench.new_run_dir(str(tmp_path), "matrix")
    bench.render_report(run_dir, records, residual_anomalies=1, partial=False,
                        notes=[])


def test_matrix_combinations_prodotto_cartesiano():
    combos = bench.matrix_combinations(["it", "en"], ["Zephyr", "Puck"],
                                       ["+0%"], [], runs=1)
    assert len(combos) == 4
    assert combos[0] == {"lang": "it", "voice": "Zephyr", "rate": "+0%",
                         "style": None, "run": 1}


def test_matrix_combinations_moltiplica_per_runs():
    combos = bench.matrix_combinations(["it"], ["Zephyr"], ["+0%"], ["calmo"],
                                       runs=3)
    assert len(combos) == 3
    assert [c["run"] for c in combos] == [1, 2, 3]


def test_fixtures_coprono_le_lingue_richieste():
    for lang in ("it", "en", "fr", "es", "de", "default"):
        assert bench.FIXTURES[lang].strip()


def test_run_matrix_esegue_tutte_le_combinazioni(tmp_path):
    combos = bench.matrix_combinations(["it", "en"], ["Zephyr"], ["+0%"], [],
                                       runs=1)
    s = FakeSession([_ok_response(seconds=9.0) for _ in combos])
    ctx = _ctx(tmp_path, s)
    residue = bench.run_matrix(ctx, combos, concurrency=1)
    assert residue == 0
    assert len(s.calls) == 2
    ctx.writer.close()


def test_run_matrix_conta_le_anomalie_residue(tmp_path):
    combos = bench.matrix_combinations(["it"], ["Zephyr"], ["+0%"], [], runs=1)
    # prima chiamata troncata, retry ancora troncato
    s = FakeSession([_ok_response(seconds=0.2), _ok_response(seconds=0.2)])
    ctx = _ctx(tmp_path, s)
    assert bench.run_matrix(ctx, combos, concurrency=1) == 1
    ctx.writer.close()


# --- Fix round 1: cap di spesa atomico e arresto reale sotto concorrenza ----

def test_run_matrix_concorrenza_scrive_tutte_le_righe_e_conta_come_seriale(tmp_path):
    combos = bench.matrix_combinations(["it", "en"], ["Zephyr", "Puck"],
                                       ["+0%"], [], runs=1)
    s_serial = FakeSession([_ok_response(seconds=9.0) for _ in combos])
    ctx_serial = _ctx(tmp_path / "serial", s_serial)
    residue_serial = bench.run_matrix(ctx_serial, combos, concurrency=1)
    ctx_serial.writer.close()

    s_conc = FakeSession([_ok_response(seconds=9.0) for _ in combos])
    ctx_conc = _ctx(tmp_path / "conc", s_conc)
    residue_conc = bench.run_matrix(ctx_conc, combos, concurrency=4)
    ctx_conc.writer.close()

    assert residue_conc == residue_serial
    assert len(s_conc.calls) == len(combos)
    righe = open(ctx_conc.writer.path, encoding="utf-8").read().splitlines()
    assert len(righe) == len(combos)


def test_run_matrix_cap_di_spesa_ferma_il_run_sotto_concorrenza(tmp_path):
    combos = bench.matrix_combinations(["it", "en"], ["Zephyr", "Puck"],
                                       ["+0%"], [], runs=1)
    s = FakeSession([_ok_response(seconds=9.0) for _ in combos])
    # cap cosi' minuscolo che anche la prima prenotazione lo sfonda: nessuna
    # chiamata HTTP deve partire.
    ctx = _ctx(tmp_path, s, max_eur=1e-9)
    with pytest.raises(bench.SpendCapExceeded):
        bench.run_matrix(ctx, combos, concurrency=4)
    ctx.writer.close()
    assert len(s.calls) < len(combos)


def test_run_matrix_cf_auth_error_si_propaga_sotto_concorrenza(tmp_path):
    combos = bench.matrix_combinations(["it", "en"], ["Zephyr", "Puck"],
                                       ["+0%"], [], runs=1)
    s = FakeSession([FakeResponse(403) for _ in combos])
    ctx = _ctx(tmp_path, s)
    with pytest.raises(bench.CFAuthError):
        bench.run_matrix(ctx, combos, concurrency=4)
    ctx.writer.close()


def test_spend_guard_reserve_concorrenza_produce_esattamente_k_successi():
    k = 3
    n = 10
    usd = 1.0
    guard = bench.SpendGuard(max_eur=k * usd * bench.USD_EUR_RATE)
    barrier = threading.Barrier(n)
    successes = []
    lock = threading.Lock()

    def worker():
        barrier.wait()
        try:
            guard.reserve(usd)
        except bench.SpendCapExceeded:
            return
        with lock:
            successes.append(1)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(successes) == k
    assert guard.spent_usd == pytest.approx(k * usd)


# --- Livello book: parsing, chunking di produzione, assembly M4B -----------

def test_parse_book_txt(tmp_path):
    p = tmp_path / "libro.txt"
    p.write_text("Prima riga.\n\nSeconda riga.", encoding="utf-8")
    book = bench.parse_book(str(p))
    assert book["title"] == "libro"
    assert len(book["chapters"]) == 1
    assert "Seconda riga." in book["chapters"][0][2]


def test_parse_book_abm(tmp_path):
    import json as _json
    import zipfile
    p = tmp_path / "libro.abm"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", _json.dumps({
            "format": "audiobook-maker-project",
            "title": "Titolo", "author": "Autore", "language": "it",
            "chapters": [{"index": 1, "title": "Cap 1", "file": "chapters/1.txt"}],
        }))
        zf.writestr("chapters/1.txt", "Testo del capitolo.")
    book = bench.parse_book(str(p))
    assert book["title"] == "Titolo"
    assert book["language"] == "it"
    assert book["chapters"] == [(1, "Cap 1", "Testo del capitolo.")]


def test_parse_book_abm_rifiuta_manifest_estraneo(tmp_path):
    import json as _json
    import zipfile
    p = tmp_path / "falso.abm"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", _json.dumps({"format": "altro"}))
    with pytest.raises(ValueError):
        bench.parse_book(str(p))


def test_chapter_markers_in_millisecondi(tmp_path):
    a = tmp_path / "a.pcm"
    b = tmp_path / "b.pcm"
    a.write_bytes(b"\x00" * (24000 * 2))       # 1 s
    b.write_bytes(b"\x00" * (24000 * 2 * 2))   # 2 s
    got = bench.chapter_markers([str(a), str(b)], ["Uno", "Due"])
    assert got == [
        {"title": "Uno", "start": 0.0, "end": 1000.0},
        {"title": "Due", "start": 1000.0, "end": 3000.0},
    ]


def test_run_book_sintetizza_ogni_chunk(tmp_path, monkeypatch):
    import tts_split
    testo = ("Questa e' una frase di prova. " * 40)  # ~1200 char, frasi complete
    book = {"title": "T", "author": "A", "language": "it",
            "chapters": [(1, "Cap 1", testo)], "cover_bytes": None}
    # Il numero di chunk lo decide lo splitter di produzione: non va indovinato.
    attesi = len(tts_split.split_text_into_chunks(testo, max_chars=450))
    assert attesi >= 2
    s = FakeSession([_ok_response(seconds=30.0) for _ in range(attesi)])
    ctx = _ctx(tmp_path, s)
    monkeypatch.setattr(bench.audio_utils, "pcm_to_aac_m4b",
                        lambda *a, **k: True)
    residue, m4b = bench.run_book(ctx, book, "Zephyr", "+0%", None,
                                  chunk_chars=450, concurrency=1,
                                  out_m4b=str(tmp_path / "out.m4b"))
    assert residue == 0
    assert len(s.calls) == attesi
    assert m4b == str(tmp_path / "out.m4b")
    ctx.writer.close()


# --- Fix round 1: abort concorrenza, esiti misti, multi-capitolo, path -----

def test_run_book_esclude_chunk_falliti_dall_assembly(tmp_path, monkeypatch):
    import tts_split
    testo = ("Questa e' una frase di prova. " * 40)
    book = {"title": "T", "author": "A", "language": "it",
            "chapters": [(1, "Cap 1", testo)], "cover_bytes": None}
    attesi = len(tts_split.split_text_into_chunks(testo, max_chars=450))
    assert attesi >= 2
    # Il primo chunk esaurisce i 4 tentativi HTTP (anomaly="error", niente
    # retry applicativo: vedi synth_chunk); i restanti vanno a buon fine.
    responses = ([FakeResponse(500)] * 4
                + [_ok_response(seconds=30.0) for _ in range(attesi - 1)])
    s = FakeSession(responses)
    ctx = _ctx(tmp_path, s)

    concat_calls = []

    def _fake_concat(parts, out_path, **kw):
        concat_calls.append(list(parts))
        with open(out_path, "wb") as fh:
            fh.write(b"")

    monkeypatch.setattr(bench.audio_utils, "pcm_concat", _fake_concat)
    monkeypatch.setattr(bench.audio_utils, "pcm_to_aac_m4b", lambda *a, **k: True)

    residue, m4b = bench.run_book(ctx, book, "Zephyr", "+0%", None,
                                  chunk_chars=450, concurrency=1,
                                  out_m4b=str(tmp_path / "out.m4b"))
    assert residue == 1
    assert len(s.calls) == 4 + (attesi - 1)
    assert len(concat_calls) == 1
    parts = concat_calls[0]
    assert len(parts) == attesi - 1
    failed_pcm = os.path.join(ctx.run_dir, "audio", "0000.pcm")
    assert failed_pcm not in parts
    assert m4b == str(tmp_path / "out.m4b")
    ctx.writer.close()


def test_run_book_multi_capitolo_accumula_pcm_e_titoli(tmp_path, monkeypatch):
    # Testi dimensionati per restare nella banda di durata attesa (RATIO_LOW-
    # RATIO_HIGH) alle durate finte sotto: un testo troppo corto per l'audio
    # dichiarato farebbe scattare "overlong" e un retry imprevisto.
    c1 = "Il primo capitolo racconta una storia semplice e chiara per il test."
    c2 = "Il secondo capitolo prosegue la storia con qualche dettaglio in piu qui."
    book = {"title": "T", "author": "A", "language": "it",
            "chapters": [(1, "Cap 1", c1), (2, "Cap 2", c2)],
            "cover_bytes": None}
    s = FakeSession([_ok_response(seconds=5.0), _ok_response(seconds=7.0)])
    ctx = _ctx(tmp_path, s)

    captured = {}

    def _fake_m4b(pcm_paths, out_path, **kw):
        captured["pcm_paths"] = list(pcm_paths)
        captured["chapters"] = kw.get("chapters")
        return True

    monkeypatch.setattr(bench.audio_utils, "pcm_to_aac_m4b", _fake_m4b)

    residue, m4b = bench.run_book(ctx, book, "Zephyr", "+0%", None,
                                  chunk_chars=450, concurrency=1,
                                  out_m4b=str(tmp_path / "out.m4b"))
    assert residue == 0
    assert len(s.calls) == 2
    assert len(captured["pcm_paths"]) == 2
    assert captured["chapters"] == [
        {"title": "Cap 1", "start": 0.0, "end": 5000.0},
        {"title": "Cap 2", "start": 5000.0, "end": 12000.0},
    ]
    assert m4b == str(tmp_path / "out.m4b")
    ctx.writer.close()


def test_run_book_capitolo_completamente_fallito_viene_scartato(tmp_path, monkeypatch):
    # Cap 1: tutti i chunk falliscono -> parts vuoto -> capitolo scartato di
    # proposito (decisione esplicita), il libro prosegue con gli altri.
    ch2_text = "Il capitolo due va a buon fine con questo testo di prova qui."
    book = {"title": "T", "author": "A", "language": "it",
            "chapters": [(1, "Cap Vuoto", "Frase unica."),
                         (2, "Cap Ok", ch2_text)],
            "cover_bytes": None}
    s = FakeSession([FakeResponse(500)] * 4 + [_ok_response(seconds=3.0)])
    ctx = _ctx(tmp_path, s)

    captured = {}

    def _fake_m4b(pcm_paths, out_path, **kw):
        captured["pcm_paths"] = list(pcm_paths)
        captured["chapters"] = kw.get("chapters")
        return True

    monkeypatch.setattr(bench.audio_utils, "pcm_to_aac_m4b", _fake_m4b)

    residue, m4b = bench.run_book(ctx, book, "Zephyr", "+0%", None,
                                  chunk_chars=450, concurrency=1,
                                  out_m4b=str(tmp_path / "out.m4b"))
    assert residue == 1
    assert m4b == str(tmp_path / "out.m4b")
    assert len(captured["pcm_paths"]) == 1
    assert [c["title"] for c in captured["chapters"]] == ["Cap Ok"]
    ctx.writer.close()


def test_run_book_libro_interamente_fallito_ritorna_none(tmp_path):
    book = {"title": "T", "author": "A", "language": "it",
            "chapters": [(1, "Cap Vuoto", "Frase unica.")],
            "cover_bytes": None}
    s = FakeSession([FakeResponse(500)] * 4)
    ctx = _ctx(tmp_path, s)
    residue, m4b = bench.run_book(ctx, book, "Zephyr", "+0%", None,
                                  chunk_chars=450, concurrency=1,
                                  out_m4b=str(tmp_path / "out.m4b"))
    assert residue == 1
    assert m4b is None
    ctx.writer.close()


def test_run_book_indici_capitolo_duplicati_non_si_sovrascrivono(tmp_path, monkeypatch):
    # Manifest .abm malformato: index duplicato. Il path PCM di capitolo deve
    # restare univoco (usa la posizione nel ciclo, non l'index del manifest).
    d1 = "Prima frase di prova per il capitolo A."
    d2 = "Seconda frase di prova per il capitolo B."
    book = {"title": "T", "author": "A", "language": "it",
            "chapters": [(1, "Cap A", d1), (1, "Cap B", d2)],
            "cover_bytes": None}
    s = FakeSession([_ok_response(seconds=2.0), _ok_response(seconds=3.0)])
    ctx = _ctx(tmp_path, s)

    captured = {}

    def _fake_m4b(pcm_paths, out_path, **kw):
        captured["pcm_paths"] = list(pcm_paths)
        return True

    monkeypatch.setattr(bench.audio_utils, "pcm_to_aac_m4b", _fake_m4b)

    residue, m4b = bench.run_book(ctx, book, "Zephyr", "+0%", None,
                                  chunk_chars=450, concurrency=1,
                                  out_m4b=str(tmp_path / "out.m4b"))
    assert residue == 0
    assert len(captured["pcm_paths"]) == len(set(captured["pcm_paths"])) == 2
    for p in captured["pcm_paths"]:
        assert os.path.getsize(p) > 0
    ctx.writer.close()


def test_run_book_cap_di_spesa_ferma_il_run_sotto_concorrenza(tmp_path):
    import tts_split
    testo = ("Questa e' una frase di prova. " * 40)
    book = {"title": "T", "author": "A", "language": "it",
            "chapters": [(1, "Cap 1", testo)], "cover_bytes": None}
    attesi = len(tts_split.split_text_into_chunks(testo, max_chars=450))
    assert attesi >= 2
    s = FakeSession([_ok_response(seconds=30.0) for _ in range(attesi)])
    # cap cosi' minuscolo che anche la prima prenotazione lo sfonda: nessuna
    # chiamata HTTP deve partire.
    ctx = _ctx(tmp_path, s, max_eur=1e-9)
    with pytest.raises(bench.SpendCapExceeded):
        bench.run_book(ctx, book, "Zephyr", "+0%", None,
                       chunk_chars=450, concurrency=4,
                       out_m4b=str(tmp_path / "out.m4b"))
    ctx.writer.close()
    assert len(s.calls) < attesi


def test_run_book_cf_auth_error_si_propaga_sotto_concorrenza(tmp_path):
    import tts_split
    testo = ("Questa e' una frase di prova. " * 40)
    book = {"title": "T", "author": "A", "language": "it",
            "chapters": [(1, "Cap 1", testo)], "cover_bytes": None}
    attesi = len(tts_split.split_text_into_chunks(testo, max_chars=450))
    s = FakeSession([FakeResponse(403) for _ in range(attesi)])
    ctx = _ctx(tmp_path, s)
    with pytest.raises(bench.CFAuthError):
        bench.run_book(ctx, book, "Zephyr", "+0%", None,
                       chunk_chars=450, concurrency=4,
                       out_m4b=str(tmp_path / "out.m4b"))
    ctx.writer.close()
    # Nota: a differenza del cap di spesa (bloccato PRIMA della chiamata HTTP,
    # in modo sincrono), 401/403 arrivano solo DOPO la risposta: con
    # concurrency >= job totali tutti possono gia' essere partiti prima che
    # lo stop flag sia visibile agli altri thread. L'invariante verificato
    # qui e' la propagazione dell'eccezione, non un tetto sul numero di
    # chiamate (stesso comportamento di run_matrix, vedi
    # test_run_matrix_cf_auth_error_si_propaga_sotto_concorrenza).


def test_compare_metrics_confronta_durate_e_rms(tmp_path):
    import struct
    cf = tmp_path / "cf.pcm"
    vx = tmp_path / "vx.pcm"
    cf.write_bytes(b"\x00" * (24000 * 2))                       # 1 s, silenzio
    vx.write_bytes(struct.pack("<h", 1000) * (24000 * 2))       # 2 s, tono
    got = bench.compare_metrics(str(cf), str(vx))
    assert got["seconds_cf"] == pytest.approx(1.0)
    assert got["seconds_vertex"] == pytest.approx(2.0)
    assert got["delta_seconds"] == pytest.approx(-1.0)
    assert got["rms_cf"] == pytest.approx(0.0)
    assert got["rms_vertex"] == pytest.approx(1000.0, rel=0.01)


def test_synth_chunk_vertex_usa_lo_stesso_prompt(tmp_path, monkeypatch):
    import gemini_tts
    visti = {}

    def fake_synthesize(text, voice_id, rate="+0%", output_path="output.pcm",
                        style_instruction=None, **kw):
        visti["text"] = text
        visti["voice_id"] = voice_id
        with open(output_path, "wb") as fh:
            fh.write(b"\x00" * (24000 * 2 * 9))  # 9 s
        return {"success": True, "bytes_written": 24000 * 2 * 9,
                "input_tokens": 10, "output_tokens": 225,
                "model_key": "flash31", "voice_name": "Zephyr",
                "attempts_used": 1}

    monkeypatch.setattr(gemini_tts, "synthesize", fake_synthesize)
    ctx = _ctx(tmp_path, FakeSession([]))
    res = bench.synth_chunk_vertex(ctx, "a" * 146, 0, "it", "Zephyr", "+0%",
                                   None, os.path.join(ctx.run_dir, "v.pcm"))
    # build_final_text riceve il testo grezzo: su Vertex lo applica synthesize
    assert visti["text"] == "a" * 146
    assert visti["voice_id"] == "gemini:flash31:Zephyr"
    assert res["record"]["backend"] == "vertex"
    assert res["anomaly"] is None
    # Il costo Vertex deve riflettere i token reali, non restare a zero
    # (altrimenti il confronto A/B mostrerebbe sempre EUR 0.00 su Vertex).
    assert res["record"]["cost_usd_est"] > 0.0
    ctx.writer.close()


def test_synth_chunk_vertex_fallimento_marca_il_chunk_senza_propagare(tmp_path, monkeypatch):
    import gemini_tts

    def fake_synthesize_boom(text, voice_id, rate="+0%", output_path="output.pcm",
                             style_instruction=None, **kw):
        raise RuntimeError("Gemini TTS failed after 3 attempts: quota exceeded")

    monkeypatch.setattr(gemini_tts, "synthesize", fake_synthesize_boom)
    ctx = _ctx(tmp_path, FakeSession([]))
    res = bench.synth_chunk_vertex(ctx, "a" * 146, 0, "it", "Zephyr", "+0%",
                                   None, os.path.join(ctx.run_dir, "v.pcm"))
    assert res["anomaly"] == "error"
    assert res["pcm_path"] is None
    assert res["audio_seconds"] is None
    record = res["record"]
    assert record["http_status"] is None
    assert record["backend"] == "vertex"
    assert set(record.keys()) == set(bench._RECORD_KEYS)
    assert len(record) == 21
    ctx.writer.close()
