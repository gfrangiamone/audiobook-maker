"""/admin/api/job/<id>/generation: dati di generazione per la scheda del
catalogo gratuito (spec catalogo §8.2), solo campi ammessi e solo admin."""
import audiobook_app


def test_generation_solo_admin_e_solo_campi_ammessi(monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "segreto")
    jid = "gen-job-1"
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[jid] = {
            "status": "done", "voice": "gemini:flash38:Sulafat", "ai_optimized": True,
            "gemini_resplit_chunks": 9, "gemini_edge_fallback_chunks": 0,
            "catalog_intro": {"key": "it", "voice": "gemini:flash38:Sulafat",
                              "sha256": "a" * 64, "gain_db": 0.2},
            "gemini_actual": {"backends": {"apikey-batch": 271, "apikey": 9}},
            "email": "lettore@example.com", "client_id": "cid-1", "payment_token": "PAY-1",
        }
    try:
        c = audiobook_app.app.test_client()
        assert c.get(f"/admin/api/job/{jid}/generation").status_code == 401
        r = c.get(f"/admin/api/job/{jid}/generation", headers={"X-Admin-Token": "segreto"})
        assert r.status_code == 200
        d = r.get_json()
        assert d["gemini_resplit_chunks"] == 9 and d["catalog_intro"]["key"] == "it"
        assert d["gemini_actual"]["backends"]["apikey"] == 9
        assert not {"email", "client_id", "payment_token"} & set(d)
        assert c.get("/admin/api/job/nessuno/generation",
                     headers={"X-Admin-Token": "segreto"}).status_code == 404
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(jid, None)
