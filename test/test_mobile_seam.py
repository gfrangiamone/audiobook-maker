"""E3, seam mobile (2026-10-10): i miei job, trasferimento e condivisione nel
blueprint `routes_mobile`; helper e valori della app risolti a ogni richiesta."""
import inspect
import re

import pytest

import audiobook_app
import routes_mobile as rm

ROUTES = ("/api/my_jobs", "/api/transfer/claim/<token>", "/api/share/create", "/api/share/finalize",
          "/api/share/claim/<token>", "/s/<token>/dl", "/api/transfer_qr/<job_id>", "/api/metrics/app_open")


def test_routes_and_helpers_live_in_the_blueprint():
    rules = {r.rule: r.endpoint for r in audiobook_app.app.url_map.iter_rules()}
    for route in ROUTES:
        assert rules[route].startswith("mobile."), route
    src = inspect.getsource(audiobook_app)
    for route in ROUTES:
        assert f'@app.route("{route}"' not in src, route
    for name in ("def _share_alive(", "def _find_reusable_share(", "def _file_available(",
                 "def _reconstruct_admin_download_record(", "def _resolve_ready_file(", "_MY_JOBS_LIVE_STATUSES = "):
        assert name not in src and name in inspect.getsource(rm), name
    assert "app.register_blueprint(routes_mobile.bp)" in src
    assert "routes_mobile._reconstruct_admin_download_record(" in src     # strumenti admin sui job
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine)\b", inspect.getsource(rm), flags=re.M)
    assert "os.environ.get(" not in inspect.getsource(rm)
    for n in rm.FUNCS:
        assert callable(rm._cfg[n]), n                  # configurata dalla app (anche se vive in un altro seam)


def test_values_and_helpers_resolve_on_the_app(monkeypatch, tmp_path):
    monkeypatch.setattr(audiobook_app, "jobs", {"J": {"status": "done"}})
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(audiobook_app, "ABM_SHARE_TTL_SEC", 123)
    assert rm._jobs() == {"J": {"status": "done"}} and rm._upload_dir() == tmp_path and rm._share_ttl_sec() == 123
    assert rm._jobs_lock is audiobook_app._jobs_lock
    import generation_engine
    assert rm.generation_engine is generation_engine
    monkeypatch.setattr(audiobook_app, "_get_client_id", lambda: "cid-seam")
    monkeypatch.setattr(audiobook_app, "_share_link_for", lambda tok: f"https://x/s/{tok}")
    assert rm._get_client_id() == "cid-seam" and rm._share_link_for("T") == "https://x/s/T"


def test_my_jobs_empty_for_unknown_client():
    audiobook_app.app.config["TESTING"] = True
    c = audiobook_app.app.test_client()
    c.set_cookie("abm_cid", "nobody-seam")
    r = c.get("/api/my_jobs")
    assert r.status_code == 200 and r.get_json()["jobs"] == []


@pytest.mark.parametrize("fmt,offered", [("zip", False), ("zip_rss", False), ("m4b", True), ("mp3", True)])
def test_transfer_qr_not_offered_for_zip(monkeypatch, fmt, offered):
    # L'app importa solo m4b/mp3: per gli zip niente QR, o l'utente si
    # ritrova in libreria un archivio che non suona.
    monkeypatch.setattr(audiobook_app, "_check_job_owner",
                        lambda jid: ({"output_format": fmt}, None, 200))
    monkeypatch.setattr(audiobook_app, "_transfer_payload_for", lambda jid: ("https://x/t/TOK", "TOK"))
    monkeypatch.setattr(audiobook_app, "_qr_data_uri", lambda p: "data:image/png;base64,QR")
    audiobook_app.app.config["TESTING"] = True
    d = audiobook_app.app.test_client().get("/api/transfer_qr/J").get_json()
    assert bool(d["qr"]) is offered
    assert d.get("unsupported", False) is (not offered)
