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
    """Job recuperabile (in RAM): l'endpoint emette url+qr e crea il token."""
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setattr(audiobook_app, "_save_transfer_tokens", lambda: None)
    jid = "qr-job-1"
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[jid] = {"status": "generating", "client_id": "web-x",
                                   "info": None, "start_time": time.time()}
    tok_ref = {}
    try:
        c = audiobook_app.app.test_client()
        r = c.get(f"/admin/api/job/{jid}/copy-qr",
                  headers={"X-Admin-Token": "test-admin-token"})
        assert r.status_code == 200
        d = r.get_json()
        assert d["job_id"] == jid
        assert d.get("available") is True
        assert "/t/" in d["url"]
        assert isinstance(d["qr"], str)  # data-URI PNG o '' se qrcode assente
        tok_ref["t"] = [t for t, v in audiobook_app._transfer_tokens.items()
                        if isinstance(v, dict) and v.get("job_id") == jid
                        and v.get("admin_copy")]
        assert len(tok_ref["t"]) == 1
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(jid, None)
        for t in tok_ref.get("t", []):
            audiobook_app._transfer_tokens.pop(t, None)


def test_copy_qr_endpoint_unavailable_when_gone(monkeypatch):
    """Job definitivamente sparito (non in RAM, nessun token, nessun file): il QR
    non deve essere proposto → available:false, nessun url/token."""
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setattr(audiobook_app, "_save_transfer_tokens", lambda: None)
    jid = "qr-gone-1"
    c = audiobook_app.app.test_client()
    r = c.get(f"/admin/api/job/{jid}/copy-qr",
              headers={"X-Admin-Token": "test-admin-token"})
    assert r.status_code == 200
    d = r.get_json()
    assert d.get("available") is False
    assert "url" not in d
    residui = [t for t, v in audiobook_app._transfer_tokens.items()
               if isinstance(v, dict) and v.get("job_id") == jid]
    assert residui == []


def test_admin_copy_claim_gone_job_returns_410(monkeypatch):
    """Claim su job sparito (né RAM, né token, né file) → 410 job_unavailable."""
    _align_ge(monkeypatch)
    monkeypatch.setattr(audiobook_app, "_save_transfer_tokens", lambda: None)
    jid = "acp-gone"
    tok = None
    try:
        tok = audiobook_app._ensure_admin_copy_token(jid)
        c = audiobook_app.app.test_client()
        r = c.post(f"/api/transfer/claim/{tok}", headers={"X-ABM-Cid": "admin-gone"})
        assert r.status_code == 410
        assert r.get_json().get("error_code") == "job_unavailable"
    finally:
        audiobook_app._transfer_tokens.pop(tok, None)


def test_admin_copy_inprogress_hooks_and_delivers(monkeypatch, tmp_path):
    """Job IN CORSO: il claim aggancia (pending) senza toccare l'utente; al COMPLETE
    la copia admin è materializzata come token admin-owned scaricabile."""
    _align_ge(monkeypatch)
    monkeypatch.setattr(audiobook_app, "_save_transfer_tokens", lambda: None)
    jid = "acp-inprog"
    out = tmp_path / "out.m4b"; out.write_bytes(b"x")
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[jid] = {
            "status": "generating", "client_id": "web-ip", "info": None,
            "output_m4b": str(out), "output_files": [str(out)],
            "output_format": "m4b", "start_time": time.time(),
        }
    created = []
    tok = None
    try:
        tok = audiobook_app._ensure_admin_copy_token(jid)
        c = audiobook_app.app.test_client()
        r = c.post(f"/api/transfer/claim/{tok}", headers={"X-ABM-Cid": "admin-ip"})
        assert r.status_code == 200
        body = r.get_json()
        assert body.get("pending") is True and body.get("admin_copy") is True
        # cid agganciato al job, nessun token ancora creato, utente invariato
        assert "admin-ip" in audiobook_app.jobs[jid]["admin_copy_cids"]
        assert audiobook_app.jobs[jid]["client_id"] == "web-ip"
        assert [v for v in audiobook_app._download_tokens.values()
                if isinstance(v, dict) and v.get("job_id") == jid] == []

        # Simula il COMPLETE: materializza le copie admin
        audiobook_app.jobs[jid]["status"] = "done"
        generation_engine._materialize_admin_copies(jid)

        created = [t for t, v in audiobook_app._download_tokens.items()
                   if isinstance(v, dict) and v.get("job_id") == jid]
        assert len(created) == 1
        clone = audiobook_app._download_tokens[created[0]]
        assert clone["client_id"] == "admin-ip" and clone.get("admin_copy") is True
        # lista svuotata (idempotenza) e nessun token utente residuo
        assert not audiobook_app.jobs[jid].get("admin_copy_cids")
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(jid, None)
        for t in created:
            audiobook_app._download_tokens.pop(t, None)
        audiobook_app._transfer_tokens.pop(tok, None)


def test_admin_copy_pending_visible_in_my_jobs(monkeypatch, tmp_path):
    """Regressione: dopo il claim di un job IN CORSO l'app mostrava
    "job aggiunto" ma /api/my_jobs dell'admin restava vuoto fino al COMPLETE.
    Il job pending deve comparire subito nella tab Attivita' (flag admin_copy),
    e al COMPLETE trasformarsi nell'entry done col download token clonato."""
    _align_ge(monkeypatch)
    monkeypatch.setattr(audiobook_app, "_save_transfer_tokens", lambda: None)
    jid = "acp-myjobs"
    out = tmp_path / "out.m4b"; out.write_bytes(b"x")
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[jid] = {
            "status": "generating", "client_id": "web-owner", "info": None,
            "original_filename": "libro.epub", "output_m4b": str(out),
            "output_files": [str(out)], "output_format": "m4b",
            "start_time": time.time(), "progress_current": 3,
            "progress_total": 10,
        }
    created = []
    tok = None
    try:
        tok = audiobook_app._ensure_admin_copy_token(jid)
        c = audiobook_app.app.test_client()
        r = c.post(f"/api/transfer/claim/{tok}", headers={"X-ABM-Cid": "admin-mj"})
        assert r.status_code == 200 and r.get_json().get("pending") is True

        # PENDING: il job in corso compare subito tra i my_jobs dell'admin
        mj = c.get("/api/my_jobs", headers={"X-ABM-Cid": "admin-mj"}).get_json()
        entry = next((e for e in mj["jobs"] if e["job_id"] == jid), None)
        assert entry is not None, "job pending assente da my_jobs admin"
        assert entry["status"] == "generating"
        assert entry.get("admin_copy") is True
        # ...e NON compare per un cid terzo qualunque
        mj3 = c.get("/api/my_jobs", headers={"X-ABM-Cid": "cid-terzo-000"}).get_json()
        assert all(e["job_id"] != jid for e in mj3["jobs"])

        # COMPLETE: materializzazione -> entry done col token clonato
        audiobook_app.jobs[jid]["status"] = "done"
        generation_engine._materialize_admin_copies(jid)
        created = [t for t, v in audiobook_app._download_tokens.items()
                   if isinstance(v, dict) and v.get("job_id") == jid]
        mj2 = c.get("/api/my_jobs", headers={"X-ABM-Cid": "admin-mj"}).get_json()
        entry2 = next((e for e in mj2["jobs"] if e["job_id"] == jid), None)
        assert entry2 is not None and entry2["status"] == "done"
        assert entry2.get("download_token") in created
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(jid, None)
        for t in created:
            audiobook_app._download_tokens.pop(t, None)
        audiobook_app._transfer_tokens.pop(tok, None)


def test_admin_copy_finalized_not_in_ram_reconstructs_from_disk(monkeypatch, tmp_path):
    """Job finalizzato NON più in RAM ma con output ancora su disco: il claim
    ricostruisce lo snapshot e consegna la copia admin (nessun 410)."""
    _align_ge(monkeypatch)
    monkeypatch.setattr(audiobook_app, "_save_transfer_tokens", lambda: None)
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    jid = "acp-cold"
    outdir = tmp_path / jid / "output_1"
    outdir.mkdir(parents=True)
    m4b = outdir / "Libro.m4b"; m4b.write_bytes(b"x")
    created = []
    tok = None
    try:
        tok = audiobook_app._ensure_admin_copy_token(jid)
        c = audiobook_app.app.test_client()
        r = c.post(f"/api/transfer/claim/{tok}", headers={"X-ABM-Cid": "admin-cold"})
        assert r.status_code == 200
        body = r.get_json()
        assert body.get("admin_copy") is True and body.get("job_id") == jid
        created = [t for t, v in audiobook_app._download_tokens.items()
                   if isinstance(v, dict) and v.get("job_id") == jid]
        assert len(created) == 1
        clone = audiobook_app._download_tokens[created[0]]
        assert clone["client_id"] == "admin-cold" and clone.get("admin_copy") is True
        assert clone["output_m4b"] == str(m4b)
        assert clone["book_title"] == "Libro"
    finally:
        for t in created:
            audiobook_app._download_tokens.pop(t, None)
        audiobook_app._transfer_tokens.pop(tok, None)
