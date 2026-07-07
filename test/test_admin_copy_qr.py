"""Copia amministrativa job sull'app via QR (indagine).

Invarianti verificate:
 - il claim di un token admin_copy NON riassegna il job dell'utente originale
   né i suoi download token (flusso utente invariato);
 - viene creato un download token CLONE di proprietà del cid chiamante (app admin);
 - per un job done senza alcun token, il token base creato per lo snapshot viene
   rimosso: nessun token di proprietà dell'utente originale resta esposto;
 - l'endpoint /admin/api/job/<id>/copy-qr richiede auth admin e ritorna url+qr.
"""
import time

import audiobook_app
import generation_engine


def _align_ge(monkeypatch):
    monkeypatch.setattr(audiobook_app, "_save_tokens", lambda: None)
    monkeypatch.setattr(audiobook_app, "_save_transfer_tokens", lambda: None)
    monkeypatch.setattr(generation_engine, "_save_tokens", lambda: None)
    monkeypatch.setattr(generation_engine, "_jobs", audiobook_app.jobs)
    monkeypatch.setattr(generation_engine, "_download_tokens", audiobook_app._download_tokens)


def test_admin_copy_claim_preserves_original_owner(monkeypatch, tmp_path):
    jid = "acp-job-1"
    out = tmp_path / "out.m4b"; out.write_bytes(b"x")
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[jid] = {
            "status": "done", "client_id": "web-cid-xyz", "info": None,
            "output_m4b": str(out), "output_format": "m4b",
            "start_time": time.time(),
        }
    audiobook_app._download_tokens["WTOK1"] = {
        "job_id": jid, "client_id": "web-cid-xyz", "created_at": time.time(),
        "is_gemini": False, "output_m4b": str(out), "output_format": "m4b",
    }
    _align_ge(monkeypatch)
    created = []
    tok = None
    try:
        tok = audiobook_app._ensure_admin_copy_token(jid)
        assert audiobook_app._transfer_tokens[tok].get("admin_copy") is True
        c = audiobook_app.app.test_client()
        r = c.post(f"/api/transfer/claim/{tok}", headers={"X-ABM-Cid": "admin-app-1"})
        assert r.status_code == 200
        body = r.get_json()
        assert body["job_id"] == jid and body.get("admin_copy") is True

        # Flusso utente invariato: job e token originale immutati
        assert audiobook_app.jobs[jid]["client_id"] == "web-cid-xyz"
        assert audiobook_app.jobs[jid].get("transferred_to_mobile") is not True
        assert audiobook_app._download_tokens["WTOK1"]["client_id"] == "web-cid-xyz"

        # Clone di proprietà dell'app admin
        created = [t for t, v in audiobook_app._download_tokens.items()
                   if isinstance(v, dict) and v.get("job_id") == jid
                   and v.get("admin_copy")]
        assert len(created) == 1
        clone = audiobook_app._download_tokens[created[0]]
        assert clone["client_id"] == "admin-app-1"
        assert clone["output_m4b"] == str(out)

        # my_jobs dell'app admin: job scaricabile
        r2 = c.get("/api/my_jobs", headers={"X-ABM-Cid": "admin-app-1"})
        entry = next(j for j in r2.get_json()["jobs"] if j["job_id"] == jid)
        assert entry["formats"]["m4b"] is True
        assert entry.get("download_token")
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(jid, None)
        audiobook_app._download_tokens.pop("WTOK1", None)
        for t in created:
            audiobook_app._download_tokens.pop(t, None)
        audiobook_app._transfer_tokens.pop(tok, None)


def test_admin_copy_done_job_without_token_does_not_expose_user(monkeypatch, tmp_path):
    """Job done SENZA alcun token: la copia admin non deve lasciare token di
    proprietà dell'utente originale (solo il clone admin)."""
    jid = "acp-job-2"
    out = tmp_path / "out.m4b"; out.write_bytes(b"x")
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[jid] = {
            "status": "done", "client_id": "web-cid-2", "info": None,
            "output_m4b": str(out), "output_format": "m4b",
            "original_filename": "libro.epub", "start_time": time.time(),
        }
    _align_ge(monkeypatch)
    created = []
    tok = None
    try:
        tok = audiobook_app._ensure_admin_copy_token(jid)
        c = audiobook_app.app.test_client()
        r = c.post(f"/api/transfer/claim/{tok}", headers={"X-ABM-Cid": "admin-app-2"})
        assert r.status_code == 200

        toks = [(t, v) for t, v in audiobook_app._download_tokens.items()
                if isinstance(v, dict) and v.get("job_id") == jid]
        created = [t for t, _ in toks]
        # Esattamente un token: il clone admin. Nessun token utente residuo.
        assert len(toks) == 1
        assert toks[0][1]["client_id"] == "admin-app-2"
        assert toks[0][1].get("admin_copy") is True
        # L'utente originale vede il proprio job in-memory (invariato) ma NON
        # riceve alcun download_token dalla copia admin: nessun token gli è
        # stato attribuito (il token base temporaneo è stato rimosso).
        r_user = c.get("/api/my_jobs", headers={"X-ABM-Cid": "web-cid-2"})
        user_entry = next(
            (j for j in r_user.get_json()["jobs"] if j["job_id"] == jid), None)
        assert user_entry is None or "download_token" not in user_entry
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(jid, None)
        for t in created:
            audiobook_app._download_tokens.pop(t, None)
        audiobook_app._transfer_tokens.pop(tok, None)


def test_copy_qr_endpoint_requires_admin(monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    c = audiobook_app.app.test_client()
    r = c.get("/admin/api/job/some-job/copy-qr")
    assert r.status_code == 401


def test_copy_qr_endpoint_returns_url(monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setattr(audiobook_app, "_save_transfer_tokens", lambda: None)
    tok_ref = {}
    try:
        c = audiobook_app.app.test_client()
        r = c.get("/admin/api/job/qr-job-1/copy-qr",
                  headers={"X-Admin-Token": "test-admin-token"})
        assert r.status_code == 200
        d = r.get_json()
        assert d["job_id"] == "qr-job-1"
        assert "/t/" in d["url"]
        assert isinstance(d["qr"], str)  # data-URI PNG o '' se qrcode assente
        # token admin_copy creato
        tok_ref["t"] = [t for t, v in audiobook_app._transfer_tokens.items()
                        if isinstance(v, dict) and v.get("job_id") == "qr-job-1"
                        and v.get("admin_copy")]
        assert len(tok_ref["t"]) == 1
    finally:
        for t in tok_ref.get("t", []):
            audiobook_app._transfer_tokens.pop(t, None)
