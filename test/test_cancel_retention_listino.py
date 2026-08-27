"""F1: il trattenuto/rimborso di un cancel volontario Gemini deve dipendere
dal costo di LISTINO della quota di lavoro eseguita, non dal costo REALE
sostenuto dal backend che ha eseguito quel lavoro (D1 su un percorso di
denaro). Prima della correzione, generation_engine.py passava
`gemini_actual["google_cost_eur"]` (reale) a
`cancel_policy.compute_cancel_retention`: un cancel su un chunk servito da
Cloudflare e uno andato in failover su Vertex avrebbero trattenuto cifre
diverse a parita' di lavoro svolto, per una scelta di infrastruttura invisibile
all'utente.

Esercita il vero ramo _CancelledError di run_generation (non solo la funzione
pura cancel_policy.compute_cancel_retention) cancellando il job dopo il primo
di due chunk pianificati, con `actual_cost_breakdown` (reale) che varia per
backend ma `pricing_cost_breakdown` (listino) costante fra gli scenari — cosi'
come accade davvero quando lo stesso lavoro finisce eseguito su backend
diversi a parita' di configurazione/tariffa di listino.
"""
import cancel_policy
import gemini_cost_audit
import gemini_tts
import generation_engine


class _Info:
    title = "T"
    author = "A"
    language = "it"
    chapters = [type("C", (), {"index": 1, "title": "Cap 1", "text": "..."})()]


def _run_cancel_after_first_chunk(monkeypatch, tmp_path, job_id, backend_first_chunk,
                                  real_cost_eur, pricing_cost_eur):
    """Esegue run_generation su un piano di 2 chunk, cancellando il job subito
    dopo che il primo e' stato processato (side effect della fake TTS), e
    restituisce il job risultante."""
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: None)
    monkeypatch.setattr(generation_engine, "_refund_gemini_payment", lambda *a, **k: None)

    call_count = {"n": 0}

    def fake_chunk_gemini(text, voice_id, output_path, max_retries=3, style_instruction=None,
                          debug_prompt_path=None, rate="+0%", **kwargs):
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 1000)
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Cancellazione richiesta subito dopo il primo chunk: il prossimo
            # giro del loop la intercetta con _check_cancelled() PRIMA di
            # processare il secondo chunk.
            job["cancelled"] = True
        return {
            "success": True, "bytes_written": 1000,
            "input_tokens": 100, "output_tokens": 500,
            "model_key": "flash25", "voice_name": "Zephyr", "attempts_used": 1,
            "backend": backend_first_chunk,
        }
    monkeypatch.setattr(generation_engine, "generate_chunk_pcm_gemini", fake_chunk_gemini)

    def fake_actual_breakdown(in_t, out_t, model_key, backend):
        return {"total_eur": real_cost_eur}
    monkeypatch.setattr(generation_engine.gemini_tts, "actual_cost_breakdown",
                        fake_actual_breakdown, raising=False)

    def fake_pricing_breakdown(in_t, out_t, model_key):
        return {"total_eur": pricing_cost_eur}
    monkeypatch.setattr(generation_engine.gemini_tts, "pricing_cost_breakdown",
                        fake_pricing_breakdown, raising=False)

    plan = [
        {"chapter_index": 1, "chapter_title": "Cap 1", "chunk_index": 0,
         "chunks_in_chapter": 2, "text": "Hello world", "chars": 11},
        {"chapter_index": 1, "chapter_title": "Cap 1", "chunk_index": 1,
         "chunks_in_chapter": 2, "text": "Second chunk", "chars": 12},
    ]
    monkeypatch.setattr(generation_engine, "_plan_chunks",
                        lambda info, max_chars, max_bytes=None, **kw: plan)
    monkeypatch.setattr(generation_engine, "_pick_chunk_max_chars", lambda v, l: 4096)
    monkeypatch.setattr(generation_engine, "_engine_for_voice", lambda v: "gemini")
    monkeypatch.setattr(generation_engine, "_generate_silence_pcm",
                        lambda p, s=1, sample_rate=None: open(p, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "pcm_to_mp3",
                        lambda parts, out, **kw: open(out, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "pcm_to_aac_m4b", lambda *a, **k: True)
    monkeypatch.setattr(generation_engine, "_get_audio_duration_ms", lambda p: 1000)
    monkeypatch.setattr(generation_engine, "pcm_size_to_seconds", lambda b, **kw: 1.0)
    monkeypatch.setattr(generation_engine, "_prepare_m4b_cover_path", lambda *a, **k: None)

    job = {"gen_epoch": 0, "info": _Info(), "status": "queued",
           "last_poll": 9e18, "email_registered": True,
           "payment": {"total_eur": 5.0, "method": "paypal", "token": "ORD-1"}}
    monkeypatch.setattr(generation_engine, "_jobs", {job_id: job})
    monkeypatch.setattr(generation_engine, "_upload_dir", tmp_path)
    monkeypatch.setattr(generation_engine, "_jobs_lock", None, raising=False)

    generation_engine.run_generation(job_id, _Info(), "gemini:flash25:Zephyr", "+0%",
                                     single_file=True, output_format="mp3")
    return job


def test_cancel_retention_identical_across_backends_same_listino(monkeypatch, tmp_path):
    """Stesso listino (0.30), costo reale diverso (Cloudflare 0.10 vs Vertex
    dopo failover 0.50): il trattenuto/rimborso deve coincidere."""
    job_cf = _run_cancel_after_first_chunk(
        monkeypatch, tmp_path, "job-cf", backend_first_chunk="cloudflare",
        real_cost_eur=0.10, pricing_cost_eur=0.30)
    job_vertex = _run_cancel_after_first_chunk(
        monkeypatch, tmp_path, "job-vx", backend_first_chunk="vertex",
        real_cost_eur=0.50, pricing_cost_eur=0.30)

    assert job_cf["gemini_actual"]["google_cost_eur"] == 0.10
    assert job_vertex["gemini_actual"]["google_cost_eur"] == 0.50
    assert job_cf["gemini_actual"]["pricing_cost_eur"] == 0.30
    assert job_vertex["gemini_actual"]["pricing_cost_eur"] == 0.30

    cm_cf = job_cf["cancel_meta"]
    cm_vx = job_vertex["cancel_meta"]
    assert cm_cf["retained_eur"] == cm_vx["retained_eur"]
    assert cm_cf["refund_eur"] == cm_vx["refund_eur"]

    # Prova positiva: il trattenuto e' quello che darebbe cancel_policy sul
    # LISTINO (0.30), non sul costo reale di nessuno dei due scenari.
    margin_pct = gemini_tts.get_margin_percent("flash25")
    expected = cancel_policy.compute_cancel_retention(
        0.30, "paypal", 5.0, margin_percent=margin_pct)
    assert cm_cf["retained_eur"] == expected["retained_eur"]
    assert cm_cf["refund_eur"] == expected["refund_eur"]

    # Prova negativa: NON e' il valore che si otterrebbe usando il costo
    # reale (dimostra che il fix davvero cambia il comportamento pre-fix).
    wrong_cf = cancel_policy.compute_cancel_retention(
        0.10, "paypal", 5.0, margin_percent=margin_pct)
    wrong_vx = cancel_policy.compute_cancel_retention(
        0.50, "paypal", 5.0, margin_percent=margin_pct)
    assert cm_cf["retained_eur"] != wrong_cf["retained_eur"]
    assert cm_vx["retained_eur"] != wrong_vx["retained_eur"]
