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

    def mount(self, prefix, adapter):
        """No-op: _build_session monta un HTTPAdapter reale che qui non serve."""


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


def test_split_csv():
    assert bench.split_csv("it, en ,fr") == ["it", "en", "fr"]
    assert bench.split_csv("") == []
    assert bench.split_csv(None) == []


def test_arg_parser_default_allineati_a_produzione():
    ns = bench.build_arg_parser().parse_args([])
    assert ns.level == "smoke"
    assert ns.chunk_chars == 450
    assert ns.temperature == 0.3
    assert ns.max_spend_eur == 2.00
    assert ns.langs == "it,en"
    assert ns.voices == "Zephyr"
    assert ns.rates == "+0%"
    assert ns.concurrency == 1
    assert ns.runs == 1
    assert ns.compare is None


def test_main_book_richiede_il_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    rc = bench.main(["--level", "book", "--out-dir", str(tmp_path)])
    assert rc == 1


def test_main_compare_senza_vertex_esce_prima_di_spendere(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench, "vertex_available", lambda: False)
    chiamate = []
    monkeypatch.setattr(bench, "call_cf",
                        lambda *a, **k: chiamate.append(1))
    rc = bench.main(["--level", "smoke", "--compare", "vertex",
                     "--out-dir", str(tmp_path)])
    assert rc == 1
    assert chiamate == []


def test_main_smoke_scrive_report_e_metriche(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=14.0)]))
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 0
    run_dirs = [d for d in os.listdir(tmp_path) if d.endswith("_smoke")]
    assert len(run_dirs) == 1
    run_dir = os.path.join(str(tmp_path), run_dirs[0])
    assert os.path.exists(os.path.join(run_dir, "report.md"))
    assert os.path.exists(os.path.join(run_dir, "metrics.jsonl"))


def test_main_esce_1_su_anomalia_residua(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=0.2),
                                             _ok_response(seconds=0.2)]))
    assert bench.main(["--level", "smoke", "--out-dir", str(tmp_path)]) == 1


def test_main_cap_di_spesa_produce_report_parziale(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=14.0)]))
    rc = bench.main(["--level", "smoke", "--max-spend-eur", "0.0000001",
                     "--out-dir", str(tmp_path)])
    assert rc == 1
    run_dir = os.path.join(str(tmp_path),
                           [d for d in os.listdir(tmp_path)][0])
    assert "PARZIALE" in open(os.path.join(run_dir, "report.md"),
                              encoding="utf-8").read()


# --- Fix round 1: crash su anomaly="error", CFAuthError a main, --max-attempts,
# --compare vertex wired/rejected, niente credenziali in output -------------

def test_run_smoke_anomaly_error_non_solleva_typeerror(tmp_path):
    """Regressione critica: audio_seconds/ratio sono None quando call_cf
    esaurisce i tentativi (anomaly="error"). Prima del fix, la formattazione
    "{:.1f}"/"{:.2f}" sollevava TypeError e main() non arrivava mai a
    scrivere report.md, pur avendo gia' speso in tentativi HTTP falliti.
    """
    s = FakeSession([FakeResponse(500)] * 4)
    ctx = _ctx(tmp_path, s)
    res = bench.run_smoke(ctx, "it", "Zephyr", "+0%", None, "Testo di prova.")
    assert res == 1
    ctx.writer.close()


def test_main_cfautherror_produce_report_parziale_e_rc_1(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([FakeResponse(401)]))
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 1
    run_dir = os.path.join(str(tmp_path), [d for d in os.listdir(tmp_path)][0])
    report = open(os.path.join(run_dir, "report.md"), encoding="utf-8").read()
    assert "PARZIALE" in report


def test_main_eccezione_non_gestita_produce_comunque_un_report(tmp_path, monkeypatch):
    """Il catch-all di main() deve marcare il run parziale e scrivere il
    report anche per un'eccezione non prevista, senza rilanciarla."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session", lambda: FakeSession([]))

    def _boom(*a, **k):
        raise RuntimeError("bug non previsto")

    monkeypatch.setattr(bench, "run_smoke", _boom)
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 1
    run_dir = os.path.join(str(tmp_path), [d for d in os.listdir(tmp_path)][0])
    report = open(os.path.join(run_dir, "report.md"), encoding="utf-8").read()
    assert "PARZIALE" in report
    assert "bug non previsto" in report


def test_main_dispatch_matrix_report_parziale_su_cfautherror(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([FakeResponse(403)]))
    rc = bench.main(["--level", "matrix", "--langs", "it", "--voices", "Zephyr",
                     "--rates", "+0%", "--out-dir", str(tmp_path)])
    assert rc == 1
    run_dir = os.path.join(
        str(tmp_path),
        [d for d in os.listdir(tmp_path) if d.endswith("_matrix")][0])
    report = open(os.path.join(run_dir, "report.md"), encoding="utf-8").read()
    assert "PARZIALE" in report


def test_main_dispatch_book_report_parziale_su_cfautherror(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([FakeResponse(403)]))
    book_path = tmp_path / "libro.txt"
    book_path.write_text("Testo breve per il test del livello book.",
                         encoding="utf-8")
    rc = bench.main(["--level", "book", "--book", str(book_path),
                     "--out-dir", str(tmp_path)])
    assert rc == 1
    run_dir = os.path.join(
        str(tmp_path),
        [d for d in os.listdir(tmp_path) if d.endswith("_book")][0])
    report = open(os.path.join(run_dir, "report.md"), encoding="utf-8").read()
    assert "PARZIALE" in report


def test_ctx_max_attempts_arriva_a_call_cf(tmp_path):
    """Prova che BenchContext.max_attempts sia davvero letto da _one_call.

    Prima del fix round 1 il campo esisteva sulla CLI (--max-attempts) ma
    _one_call chiamava call_cf senza passarlo: il default interno di
    call_cf (4) restava sempre in vigore.
    """
    s = FakeSession([FakeResponse(500)])
    run_dir = bench.new_run_dir(str(tmp_path), "test")
    ctx = bench.BenchContext(
        session=s, account_id="acc", api_token="tok", run_dir=run_dir,
        writer=bench.MetricsWriter(run_dir), guard=bench.SpendGuard(10.0),
        run_id="run-test", temperature=0.3, backend="cloudflare",
        sleep=lambda _: None, max_attempts=1)
    record, seconds, path = bench._one_call(
        ctx, "testo finale", 20, "it", "Zephyr", "+0%", None,
        os.path.join(run_dir, "x.pcm"), 0)
    assert record["anomaly"] == "error"
    assert record["attempt"] == 1
    assert len(s.calls) == 1
    ctx.writer.close()


def test_main_max_attempts_limita_i_tentativi_http_end_to_end(tmp_path, monkeypatch):
    """Stessa prova end-to-end, dalla CLI: con --max-attempts 1 e una sola
    risposta 500 in coda, la sessione finta non deve mai ricevere una
    seconda POST (altrimenti FakeSession solleverebbe IndexError su una
    coda vuota, segno che il default di call_cf non e' stato sovrascritto).
    """
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    s = FakeSession([FakeResponse(500)])
    monkeypatch.setattr(bench.requests, "Session", lambda: s)
    rc = bench.main(["--level", "smoke", "--max-attempts", "1",
                     "--out-dir", str(tmp_path)])
    assert rc == 1
    assert len(s.calls) == 1


def _fake_vertex_synthesize_factory(seconds):
    def _fake(text, voice_ref, rate=None, output_path=None,
             style_instruction=None):
        audio_bytes = (int(seconds) * bench.EXPECTED_RATE
                      * bench.EXPECTED_CHANNELS * bench.EXPECTED_WIDTH)
        with open(output_path, "wb") as fh:
            fh.write(b"\x00" * audio_bytes)
        return {"bytes_written": audio_bytes, "input_tokens": 100,
                "output_tokens": 50, "attempts_used": 1}
    return _fake


def test_main_compare_vertex_wired_a_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench, "vertex_available", lambda: True)
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=14.0)]))
    monkeypatch.setattr(bench.gemini_tts, "synthesize",
                        _fake_vertex_synthesize_factory(14))
    rc = bench.main(["--level", "smoke", "--compare", "vertex",
                     "--out-dir", str(tmp_path)])
    assert rc == 0
    run_dir = os.path.join(
        str(tmp_path),
        [d for d in os.listdir(tmp_path) if d.endswith("_smoke")][0])
    righe = open(os.path.join(run_dir, "metrics.jsonl"),
                encoding="utf-8").read().splitlines()
    backends = {bench.json.loads(r)["backend"] for r in righe}
    assert backends == {"cloudflare", "vertex"}


def test_main_compare_vertex_wired_a_matrix(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench, "vertex_available", lambda: True)
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=9.0)]))
    monkeypatch.setattr(bench.gemini_tts, "synthesize",
                        _fake_vertex_synthesize_factory(9))
    rc = bench.main(["--level", "matrix", "--langs", "it", "--voices", "Zephyr",
                     "--rates", "+0%", "--compare", "vertex",
                     "--out-dir", str(tmp_path)])
    assert rc == 0
    run_dir = os.path.join(
        str(tmp_path),
        [d for d in os.listdir(tmp_path) if d.endswith("_matrix")][0])
    righe = open(os.path.join(run_dir, "metrics.jsonl"),
                encoding="utf-8").read().splitlines()
    backends = {bench.json.loads(r)["backend"] for r in righe}
    assert backends == {"cloudflare", "vertex"}


def test_main_compare_vertex_rifiutato_a_livello_book(tmp_path, monkeypatch):
    """Il raddoppio di costo del confronto A/B non e' accettabile su un
    libro intero: va rifiutato esplicitamente, anche se le credenziali
    Vertex sono disponibili, prima di qualunque spesa Cloudflare."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench, "vertex_available", lambda: True)
    chiamate = []
    monkeypatch.setattr(bench, "call_cf", lambda *a, **k: chiamate.append(1))
    book_path = tmp_path / "libro.txt"
    book_path.write_text("Testo di prova per il libro.", encoding="utf-8")
    rc = bench.main(["--level", "book", "--book", str(book_path),
                     "--compare", "vertex", "--out-dir", str(tmp_path)])
    assert rc == 1
    assert chiamate == []


def test_main_non_rivela_credenziali_in_stdout_ne_nel_report(tmp_path, monkeypatch,
                                                              capsys):
    monkeypatch.setenv("CF_ACCOUNT_ID", "SENTINELLA_ACCOUNT_ID_XYZ")
    monkeypatch.setenv("CF_API_TOKEN", "SENTINELLA_API_TOKEN_XYZ")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([FakeResponse(401)]))
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "SENTINELLA_ACCOUNT_ID_XYZ" not in captured.out
    assert "SENTINELLA_API_TOKEN_XYZ" not in captured.out
    run_dir = os.path.join(str(tmp_path), [d for d in os.listdir(tmp_path)][0])
    report = open(os.path.join(run_dir, "report.md"), encoding="utf-8").read()
    assert "SENTINELLA_ACCOUNT_ID_XYZ" not in report
    assert "SENTINELLA_API_TOKEN_XYZ" not in report


# --- Fix round 2: protezione del blocco di post-elaborazione, spesa Vertex
# mostrata separatamente, compare_metrics anche a matrix ------------------

def test_main_render_report_che_fallisce_lascia_comunque_un_report(tmp_path,
                                                                    monkeypatch):
    """Regressione Important del round 2: prima la lettura di metrics.jsonl,
    _residual_anomalies e render_report vivevano fuori da qualunque
    protezione. Un run che ha gia' pagato (chiamata HTTP riuscita) e che
    fallisce durante render_report non deve morire con un traceback senza
    lasciare report.md."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=9.0)]))

    def _boom(*a, **k):
        raise OSError("disco pieno (simulato)")

    monkeypatch.setattr(bench, "render_report", _boom)
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 1
    run_dir = os.path.join(str(tmp_path), [d for d in os.listdir(tmp_path)][0])
    report_path = os.path.join(run_dir, "report.md")
    assert os.path.exists(report_path)
    testo = open(report_path, encoding="utf-8").read()
    assert "PARZIALE" in testo
    assert "disco pieno (simulato)" in testo


def test_one_call_cfautherror_libera_la_prenotazione(tmp_path):
    """Mutation guard: senza `except CFAuthError` in _one_call, un 401
    lascia la prenotazione agganciata a SpendGuard per sempre invece di
    liberarla a zero."""
    s = FakeSession([FakeResponse(401)])
    ctx = _ctx(tmp_path, s)
    with pytest.raises(bench.CFAuthError):
        bench._one_call(ctx, "testo finale", 20, "it", "Zephyr", "+0%", None,
                        os.path.join(ctx.run_dir, "x.pcm"), 0)
    assert ctx.guard.spent_eur() == pytest.approx(0.0)
    ctx.writer.close()


def test_main_cf_residue_deduplica_i_retry_corretti(tmp_path, monkeypatch):
    """Mutation guard: se il residuo tornasse a contare le righe grezze di
    metrics.jsonl senza deduplicare per chunk_index (ultima riga vince), un
    chunk anomalo al primo tentativo ma corretto dal retry risulterebbe
    ancora anomalo nel report e nel codice di uscita."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=0.2),
                                             _ok_response(seconds=9.0)]))
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 0
    run_dir = os.path.join(str(tmp_path), [d for d in os.listdir(tmp_path)][0])
    report = open(os.path.join(run_dir, "report.md"), encoding="utf-8").read()
    assert "anomalie residue: 0" in report


def test_main_report_contiene_la_nota_di_scope_backend(tmp_path, monkeypatch):
    """Mutation guard: la nota che dichiara a quale backend si riferiscono
    report e riconciliazione deve comparire sempre nel report."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=9.0)]))
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 0
    run_dir = os.path.join(str(tmp_path), [d for d in os.listdir(tmp_path)][0])
    report = open(os.path.join(run_dir, "report.md"), encoding="utf-8").read()
    assert "coprono solo il backend" in report
    assert "'cloudflare'" in report


def test_run_book_lang_override_si_applica_a_ogni_chunk(tmp_path, monkeypatch):
    """Mutation guard: --langs a --level book deve raggiungere OGNI chunk
    del libro (non solo il primo, non nessuno): la lingua di ogni riga
    scritta in metrics.jsonl deve essere quella passata a run_book, mai
    quella (diversa) dei metadati del libro."""
    import tts_split
    testo = ("Questa e' una frase di prova. " * 40)
    book = {"title": "T", "author": "A", "language": "en",
            "chapters": [(1, "Cap 1", testo)], "cover_bytes": None}
    attesi = len(tts_split.split_text_into_chunks(testo, max_chars=450))
    assert attesi >= 2
    s = FakeSession([_ok_response(seconds=30.0) for _ in range(attesi)])
    ctx = _ctx(tmp_path, s)
    monkeypatch.setattr(bench.audio_utils, "pcm_to_aac_m4b", lambda *a, **k: True)
    bench.run_book(ctx, book, "Zephyr", "+0%", None, chunk_chars=450,
                   concurrency=1, out_m4b=str(tmp_path / "out.m4b"), lang="de")
    ctx.writer.close()
    righe = open(ctx.writer.path, encoding="utf-8").read().splitlines()
    assert len(righe) == attesi
    langs_usate = {bench.json.loads(r)["lang"] for r in righe}
    assert langs_usate == {"de"}


def test_build_session_dimensiona_il_pool_sulla_concorrenza():
    """Mutation guard: _build_session deve montare davvero un HTTPAdapter
    dimensionato su `concurrency`, non limitarsi a restituire una Session
    di default (pool_maxsize=10 sempre)."""
    session = bench._build_session(32)
    try:
        adapter = session.get_adapter("https://example.com")
        assert adapter._pool_maxsize == 32
        assert adapter._pool_connections == 32
    finally:
        session.close()


def test_main_mostra_spesa_cloudflare_e_vertex_separate(tmp_path, monkeypatch):
    """Con --compare vertex il footer/report devono riportare le due spese
    separate ed etichettate: la spesa Vertex non passa mai da ctx.guard, e
    presentare solo quella Cloudflare farebbe vedere a un operatore circa
    meta' di quanto ha davvero speso."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench, "vertex_available", lambda: True)
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=9.0)]))
    monkeypatch.setattr(bench.gemini_tts, "synthesize",
                        _fake_vertex_synthesize_factory(9))
    rc = bench.main(["--level", "smoke", "--compare", "vertex",
                     "--out-dir", str(tmp_path)])
    assert rc == 0
    run_dir = os.path.join(
        str(tmp_path),
        [d for d in os.listdir(tmp_path) if d.endswith("_smoke")][0])
    report = open(os.path.join(run_dir, "report.md"), encoding="utf-8").read()
    assert "spesa Vertex stimata" in report
    assert "fuori dal cap" in report


def test_run_matrix_compare_vertex_calcola_le_metriche_di_confronto(tmp_path,
                                                                     monkeypatch):
    """Il ramo A/B a --level matrix deve chiamare compare_metrics per ogni
    combinazione, non limitarsi a scrivere le righe backend='vertex'."""
    combos = bench.matrix_combinations(["it"], ["Zephyr"], ["+0%"], [], runs=1)
    s = FakeSession([_ok_response(seconds=9.0)])
    ctx = _ctx(tmp_path, s)
    monkeypatch.setattr(bench.gemini_tts, "synthesize",
                        _fake_vertex_synthesize_factory(9))
    chiamate = []
    originale = bench.compare_metrics

    def _spia(pcm_cf, pcm_vertex):
        chiamate.append((pcm_cf, pcm_vertex))
        return originale(pcm_cf, pcm_vertex)

    monkeypatch.setattr(bench, "compare_metrics", _spia)
    bench.run_matrix(ctx, combos, concurrency=1, compare_vertex=True)
    ctx.writer.close()
    assert len(chiamate) == 1


# --- Fix round 3 --------------------------------------------------------------

def test_main_book_langs_flag_cablato_correttamente(tmp_path, monkeypatch):
    """Mutation guard round 3 (Finding E.1): il cablaggio di --langs a
    --level book vive in main (`book_lang = langs[0] if _flag_present(...)
    else None`), non solo nella meta' interna a run_book gia' coperta da
    `test_run_book_lang_override_si_applica_a_ogni_chunk`. Due mutazioni
    lasciavano la suite verde: forzare `book_lang` sempre a None (--langs
    smette di avere effetto) o sempre a langs[0] (i metadati del libro,
    quando l'utente non ha chiesto un override, vengono ignorati lo stesso).
    Un solo scenario non basta a smascherare entrambe: servono due run."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    testo = "Testo breve per il test."
    book_path = tmp_path / "libro.txt"
    book_path.write_text(testo, encoding="utf-8")

    # I secondi finti devono centrare esattamente il rapporto atteso per la
    # lingua realmente usata (baseline_rate varia per lingua): altrimenti
    # evaluate_duration segnala un'anomalia e synth_chunk ritenta con una
    # seconda chiamata HTTP, un dettaglio del gate di qualita' indipendente
    # da cio' che questo test vuole verificare (il cablaggio di --langs).
    def _seconds_senza_anomalie(lang):
        return len(testo) / bench.gemini_tts.baseline_rate(lang)

    # Scenario 1: --langs esplicito -> deve raggiungere run_book (smaschera
    # la mutazione "forzato sempre a None").
    out1 = tmp_path / "out1"
    monkeypatch.setattr(
        bench.requests, "Session",
        lambda: FakeSession([_ok_response(seconds=_seconds_senza_anomalie("de"))]))
    rc1 = bench.main(["--level", "book", "--book", str(book_path),
                      "--langs", "de", "--out-dir", str(out1)])
    assert rc1 == 0
    run_dir1 = os.path.join(str(out1), [d for d in os.listdir(out1)][0])
    righe1 = open(os.path.join(run_dir1, "metrics.jsonl"),
                 encoding="utf-8").read().splitlines()
    assert {bench.json.loads(r)["lang"] for r in righe1} == {"de"}

    # Scenario 2: nessun --langs esplicito -> il default della CLI ("it,en")
    # NON deve sovrascrivere i metadati del libro (qui vuoti -> fallback
    # "en" in run_book): smaschera la mutazione "forzato sempre a langs[0]".
    out2 = tmp_path / "out2"
    monkeypatch.setattr(
        bench.requests, "Session",
        lambda: FakeSession([_ok_response(seconds=_seconds_senza_anomalie("en"))]))
    rc2 = bench.main(["--level", "book", "--book", str(book_path),
                      "--out-dir", str(out2)])
    assert rc2 == 0
    run_dir2 = os.path.join(str(out2), [d for d in os.listdir(out2)][0])
    righe2 = open(os.path.join(run_dir2, "metrics.jsonl"),
                 encoding="utf-8").read().splitlines()
    assert {bench.json.loads(r)["lang"] for r in righe2} == {"en"}


class _KeyboardInterruptSession:
    """Sessione finta che interrompe la chiamata HTTP come farebbe Ctrl-C."""

    def mount(self, prefix, adapter):
        pass

    def post(self, *a, **k):
        raise KeyboardInterrupt()


def test_main_intercetta_keyboardinterrupt_e_scrive_report(tmp_path, monkeypatch):
    """Mutation guard round 3 (Finding E.2): senza `except KeyboardInterrupt`
    nel dispatch di main, un Ctrl-C durante una chiamata pagata risale non
    gestito invece di produrre un report parziale con uscita non-zero."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: _KeyboardInterruptSession())
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 1
    run_dir = os.path.join(str(tmp_path), [d for d in os.listdir(tmp_path)][0])
    report = open(os.path.join(run_dir, "report.md"), encoding="utf-8").read()
    assert "interrotto" in report or "Ctrl-C" in report


def test_main_riga_malformata_in_metrics_non_e_fatale(tmp_path, monkeypatch):
    """Mutation guard round 3 (Finding E.3): senza il try/except attorno a
    `json.loads` nel blocco di post-elaborazione, una riga corrotta in
    metrics.jsonl fa cadere main() nel fallback generico (senza la nota
    dedicata "malformate") invece di essere scartata e disclosata."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=9.0)]))
    original_write = bench.MetricsWriter.write

    def _write_con_riga_corrotta(self, record):
        original_write(self, record)
        self._fh.write("questo non e' json valido\n")
        self._fh.flush()

    monkeypatch.setattr(bench.MetricsWriter, "write", _write_con_riga_corrotta)
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 0
    run_dir = os.path.join(str(tmp_path), [d for d in os.listdir(tmp_path)][0])
    report = open(os.path.join(run_dir, "report.md"), encoding="utf-8").read()
    assert "malformate" in report


def test_main_footer_stampa_spesa_cloudflare_e_vertex_separate(tmp_path,
                                                                monkeypatch,
                                                                capsys):
    """Mutation guard round 3 (Finding E.4): il test del round 2
    (`test_main_mostra_spesa_cloudflare_e_vertex_separate`) verifica solo il
    report.md; i due print separati del footer su stdout restavano senza
    copertura propria."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench, "vertex_available", lambda: True)
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=9.0)]))
    monkeypatch.setattr(bench.gemini_tts, "synthesize",
                        _fake_vertex_synthesize_factory(9))
    rc = bench.main(["--level", "smoke", "--compare", "vertex",
                     "--out-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "spesa stimata Cloudflare" in out
    assert "spesa stimata Vertex" in out


def test_main_systemexit_durante_il_run_produce_comunque_un_report(tmp_path,
                                                                    monkeypatch):
    """Copertura Finding A (fix round 3): un SystemExit sollevato durante il
    dispatch (es. da una dipendenza terza) non deve lasciare il run senza
    report.md ne' propagare un'uscita non gestita: va trattato come
    KeyboardInterrupt/Exception, run marcato parziale, uscita non-zero."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session", lambda: FakeSession([]))

    def _boom(*a, **k):
        raise SystemExit(3)

    monkeypatch.setattr(bench, "run_smoke", _boom)
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 1
    run_dir = os.path.join(str(tmp_path), [d for d in os.listdir(tmp_path)][0])
    report_path = os.path.join(run_dir, "report.md")
    assert os.path.exists(report_path)
    testo = open(report_path, encoding="utf-8").read()
    assert "PARZIALE" in testo


def test_main_systemexit_nel_post_run_produce_comunque_un_report(tmp_path,
                                                                  monkeypatch):
    """Copertura Finding A (fix round 3), seconda meta': SystemExit e'
    aggiunto anche alla tupla except del blocco di post-elaborazione (righe
    ~1422), un punto distinto dalla clausola di dispatch coperta dal test
    precedente. Qui il run va a buon fine (nessuna eccezione nel dispatch),
    ma render_report solleva SystemExit: senza SystemExit nella tupla del
    blocco protetto, l'eccezione risalirebbe non gestita nonostante la
    chiamata pagata sia gia' avvenuta."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=9.0)]))

    def _boom(*a, **k):
        raise SystemExit(2)

    monkeypatch.setattr(bench, "render_report", _boom)
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 1
    run_dir = os.path.join(str(tmp_path), [d for d in os.listdir(tmp_path)][0])
    report_path = os.path.join(run_dir, "report.md")
    assert os.path.exists(report_path)
    testo = open(report_path, encoding="utf-8").read()
    assert "PARZIALE" in testo


def test_main_fallback_report_non_scrivibile_lo_dichiara_e_non_mente(tmp_path,
                                                                      monkeypatch,
                                                                      capsys):
    """Copertura Finding B (fix round 3): se render_report fallisce E anche
    il tentativo di scrivere il report minimo fallisce, main() non deve piu'
    inghiottire il secondo errore in silenzio ne' annunciare
    "[fine] report: <path>" per un file che non esiste su disco."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=9.0)]))

    def _boom_render(*a, **k):
        raise OSError("disco pieno (simulato)")

    monkeypatch.setattr(bench, "render_report", _boom_render)

    real_open = open

    def _open_che_rifiuta_il_report(path, mode="r", *a, **k):
        if os.path.basename(str(path)) == "report.md" and "w" in mode:
            raise OSError("disco pieno anche per il fallback (simulato)")
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr(bench, "open", _open_che_rifiuta_il_report, raising=False)
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 1
    run_dir = os.path.join(str(tmp_path), [d for d in os.listdir(tmp_path)][0])
    assert not os.path.exists(os.path.join(run_dir, "report.md"))
    out = capsys.readouterr().out
    assert "impossibile scrivere anche il report minimo" in out
    assert "nessun report scritto su disco" in out
    assert "[fine] report:" not in out


def test_one_call_libera_la_prenotazione_su_keyboardinterrupt(tmp_path,
                                                               monkeypatch):
    """Copertura Finding C (fix round 3), aggiornata dal round 4 (difetto 1):
    un'interruzione fra reserve() e uno dei settle() espliciti non deve
    lasciare la prenotazione agganciata a SpendGuard per sempre. La
    liquidazione pero' e' conservativa: se il 200 e' gia' arrivato la chiamata
    e' fatturata, quindi la prenotazione resta contabilizzata al costo
    previsto (azzerarla dichiarerebbe gratis una chiamata pagata); solo
    un'interruzione PRIMA del 200 riporta la spesa a zero."""
    def _boom(*a, **k):
        raise KeyboardInterrupt()

    # Caso A: interruzione dopo il 200, durante la decodifica del WAV.
    ctx = _ctx(tmp_path / "a", FakeSession([_ok_response(seconds=9.0)]))
    monkeypatch.setattr(bench, "wav_bytes_to_pcm", _boom)
    with pytest.raises(KeyboardInterrupt):
        bench._one_call(ctx, "testo finale", 20, "it", "Zephyr", "+0%", None,
                        os.path.join(ctx.run_dir, "x.pcm"), 0)
    atteso = bench.predict_call_usd(20, "it") * bench.USD_EUR_RATE
    assert ctx.guard.spent_eur() == pytest.approx(atteso)
    assert atteso > 0.0
    assert ctx.paid_calls.count == 1
    ctx.writer.close()

    # Caso B: interruzione PRIMA del 200 (sulla POST): nulla di fatturato,
    # la prenotazione va liberata del tutto.
    ctx_b = _ctx(tmp_path / "b", _KeyboardInterruptSession())
    with pytest.raises(KeyboardInterrupt):
        bench._one_call(ctx_b, "testo finale", 20, "it", "Zephyr", "+0%", None,
                        os.path.join(ctx_b.run_dir, "x.pcm"), 0)
    assert ctx_b.guard.spent_eur() == pytest.approx(0.0)
    assert ctx_b.paid_calls.count == 0
    ctx_b.writer.close()


def test_main_riconciliazione_dichiarata_non_disponibile_se_metrics_illeggibile(
        tmp_path, monkeypatch, capsys):
    """Copertura Finding D (fix round 3): quando metrics.jsonl non e'
    leggibile in modo affidabile dopo che una chiamata e' gia' stata
    pagata, la riconciliazione non deve stampare un conteggio a zero
    presentato come reale ("nessuna chiamata effettuata"): deve dichiarare
    esplicitamente che i dati non sono disponibili."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=9.0)]))

    real_open = open

    def _open_che_rompe_metrics(path, mode="r", *a, **k):
        # Solo la lettura in modalita' "r" di default (in main, dopo la
        # chiamata pagata) deve fallire: la scrittura in "a" di
        # MetricsWriter deve restare intatta, altrimenti la chiamata pagata
        # non verrebbe nemmeno registrata su disco.
        if os.path.basename(str(path)) == "metrics.jsonl" and mode == "r":
            raise OSError("metrics.jsonl illeggibile (simulato)")
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr(bench, "open", _open_che_rompe_metrics, raising=False)
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "non disponibile" in out
    assert "RICONCILIAZIONE - finestra" not in out
    run_dir = os.path.join(str(tmp_path), [d for d in os.listdir(tmp_path)][0])
    assert os.path.exists(os.path.join(run_dir, "report.md"))


# --- Fix round 4: chiamate pagate invisibili, Ctrl-C sul report di fallback,
# costo non fatturato etichettato, causa reale della riconciliazione mancante --

def test_main_200_gia_fatturato_perso_prima_del_record_resta_visibile(
        tmp_path, monkeypatch, capsys):
    """Difetto 1 (round 4): fra la risposta HTTP 200 (gia' fatturata da
    Cloudflare) e la scrittura del record c'e' una finestra. Se il run viene
    interrotto li' dentro non esiste alcun record, e prima di questo fix
    l'output dichiarava il falso: "nessuna chiamata effettuata", spesa
    EUR 0.0000 e report con Chiamate 0. Un contatore dei POST andati a 200,
    indipendente dai record, deve contraddire quelle righe."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=9.0)]))

    def _boom(*a, **k):
        raise KeyboardInterrupt()

    monkeypatch.setattr(bench, "wav_bytes_to_pcm", _boom)
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "non compare in metrics.jsonl" in out
    assert "nessuna chiamata effettuata" not in out
    # La spesa non puo' essere azzerata: il POST e' stato fatturato.
    assert "spesa stimata Cloudflare (soggetta al cap --max-spend-eur): EUR 0.0000" not in out
    run_dir = os.path.join(str(tmp_path), [d for d in os.listdir(tmp_path)][0])
    report = open(os.path.join(run_dir, "report.md"), encoding="utf-8").read()
    assert "non compare in metrics.jsonl" in report


def test_main_ctrl_c_durante_il_report_di_fallback_non_esce_grezzo(
        tmp_path, monkeypatch, capsys):
    """Difetto 2 (round 4): l'unico handler attorno alla scrittura del report
    minimo era `except OSError`. Un Ctrl-C proprio su quella open faceva
    uscire main con traceback grezzo e senza alcun report, mentre
    metrics.jsonl provava la chiamata gia' pagata."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=9.0)]))

    def _boom_render(*a, **k):
        raise OSError("disco pieno (simulato)")

    monkeypatch.setattr(bench, "render_report", _boom_render)

    real_open = open

    def _open_interrotto_sul_report(path, mode="r", *a, **k):
        if os.path.basename(str(path)) == "report.md" and "w" in mode:
            raise KeyboardInterrupt()
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr(bench, "open", _open_interrotto_sul_report,
                        raising=False)
    try:
        rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    except BaseException as exc:  # noqa: BLE001 - il punto del test
        pytest.fail(f"main() non deve propagare {exc!r}: il run e' gia' stato "
                    f"pagato e l'uscita va dichiarata, non lasciata a un "
                    f"traceback grezzo")
    assert rc == 1
    out = capsys.readouterr().out
    assert "impossibile scrivere anche il report minimo" in out
    assert "nessun report scritto su disco" in out
    assert "[fine] report:" not in out


def test_report_e_riconciliazione_etichettano_il_costo_non_fatturato(tmp_path):
    """Difetto 3 (round 4): il record di un chunk fallito porta comunque
    cost_usd_est valorizzato, mentre il footer del run mostra spesa zero
    (una chiamata fallita non viene fatturata). Le due cifre divergenti
    devono essere spiegate, non lasciate indovinare."""
    records = [
        _rec(chunk_index=0),
        _rec(chunk_index=1, anomaly="error", http_status=500, attempt=4,
             latency_ms=None, audio_bytes=None, audio_seconds=None, ratio=None),
    ]
    blocco = bench.reconciliation_block(records)
    assert "NON fatturato" in blocco
    assert "0.0091" in blocco  # 0.00909 USD del solo record fallito
    run_dir = bench.new_run_dir(str(tmp_path), "matrix")
    path = bench.render_report(run_dir, records, residual_anomalies=1,
                               partial=False, notes=[])
    testo = open(path, encoding="utf-8").read()
    assert "NON fatturato" in testo
    assert "0.0091" in testo


def test_report_senza_chunk_falliti_non_parla_di_costo_non_fatturato(tmp_path):
    """Contro-prova del difetto 3: la nota deve comparire solo quando esiste
    davvero un record anomaly="error", altrimenti e' rumore."""
    assert "NON fatturato" not in bench.reconciliation_block([_rec()])
    run_dir = bench.new_run_dir(str(tmp_path), "matrix")
    path = bench.render_report(run_dir, [_rec()], residual_anomalies=0,
                               partial=False, notes=[])
    assert "NON fatturato" not in open(path, encoding="utf-8").read()


def test_main_render_report_fallito_non_nasconde_la_riconciliazione(
        tmp_path, monkeypatch, capsys):
    """Difetto 4 (round 4): quando a fallire e' render_report (non la lettura
    di metrics.jsonl), stdout attribuiva una causa falsa ("fallita prima di
    poter leggere metrics.jsonl") mentre i record erano stati letti benissimo
    — tanto che il report minimo dello stesso run ne dichiarava il numero.
    Con i record disponibili la riconciliazione va stampata, non nascosta."""
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=9.0)]))

    def _boom(*a, **k):
        raise OSError("disco pieno (simulato)")

    monkeypatch.setattr(bench, "render_report", _boom)
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "RICONCILIAZIONE - finestra" in out
    assert "prima di poter leggere metrics.jsonl" not in out
