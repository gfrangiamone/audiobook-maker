"""Regressione: un job terminato 'partial' deve sbloccare il pannello di
completamento come un 'done'.

Contesto: quando la frazione di chunk falliti supera ABM_GEMINI_MAX_FAILED_RATIO
il job viene marcato status='partial' (generation_engine.py). L'output (M4B/MP3,
email, ABM) è comunque prodotto: differisce da 'done' solo nella stringa di stato.

Difetto: la SSE /api/progress e il completion handler frontend gestivano solo
status=='done'; per 'partial' la SSE non emetteva mai il payload di
completamento (nessun break → stream infinito) e il frontend restava appeso
sulla schermata di avanzamento. Esposto dall'engine Speechify (soglia refund
non a 0.0 come Gemini). Fix: trattare 'partial' come stato terminale di
completamento su entrambi i lati.
"""
import time
import json
import os
import pytest


def test_sse_partial_is_terminal_with_completion_payload(monkeypatch):
    """La SSE deve emettere un evento terminale con payload di completamento
    (output_name/has_abm) e status='partial' per un job parziale."""
    import audiobook_app

    job = {
        "job_id": "JP", "status": "partial",
        "output_name": "libro", "output_m4b": True,
        "failed_chunks": 1, "ai_optimized": False, "podcast_ready": False,
        "output_dir": "",
    }
    if not hasattr(audiobook_app, "jobs"):
        pytest.skip("audiobook_app.jobs non trovato")
    audiobook_app.jobs = {"JP": job}

    # Safety net: se il branch terminale mancasse (regressione), evita il loop
    # infinito forzando 'done' dopo alcuni poll.
    monkeypatch.setattr(audiobook_app.time, "sleep", lambda s: None, raising=False)
    _n = [0]
    _orig_time = time.time

    def fake_time():
        _n[0] += 1
        if _n[0] >= 6:
            job["status"] = "done"
        return _orig_time()

    monkeypatch.setattr(audiobook_app.time, "time", fake_time, raising=False)

    client = audiobook_app.app.test_client()
    resp = client.get("/api/progress/JP")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    first = None
    for line in body.splitlines():
        if line.startswith("data:"):
            first = json.loads(line[5:].strip())
            break
    assert first is not None, "nessun evento SSE ricevuto"
    assert first["status"] == "partial", f"primo evento non 'partial': {first.get('status')}"
    # Marker del payload di completamento (assenti negli eventi di avanzamento).
    assert "output_name" in first, "payload di completamento mancante per 'partial'"
    assert "has_abm" in first


def test_frontend_completion_handler_accepts_partial():
    """Il completion handler in app.js deve attivarsi anche per status 'partial'."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "static", "js", "app.js",
    )
    path = os.path.abspath(path)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    # La guardia del blocco di completamento deve includere 'partial'.
    assert "d.status==='partial'" in content, \
        "app.js: il completion handler non gestisce status 'partial'"
