"""O2 (2026-10-13): /healthz per deploy e monitoraggio; deploy.yml con gate
(py_compile + pytest), un deploy alla volta, health check dopo il riavvio e
rollback al commit precedente. O1: requirements.txt completo, ruff fuori
dalla produzione."""
import re
from pathlib import Path

import audiobook_app
import routes_health
import version

ROOT = Path(audiobook_app.__file__).resolve().parent


def test_healthz_reports_version_uptime_and_writable_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    audiobook_app.app.config["TESTING"] = True
    c = audiobook_app.app.test_client()
    r = c.get("/healthz")
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] is True
    assert body["version"] == version.__version__ and body["uptime_s"] >= 0
    assert body["data_dir_writable"] is True and body["jobs_generating"] >= 0
    assert r.headers["Cache-Control"] == "no-store"


def test_healthz_is_503_when_the_data_dir_is_not_writable(monkeypatch):
    monkeypatch.setattr(routes_health, "_data_dir_writable", lambda: False)
    c = audiobook_app.app.test_client()
    r = c.get("/healthz")
    assert r.status_code == 503 and r.get_json()["ok"] is False


def test_deploy_workflow_has_gate_concurrency_healthcheck_and_rollback():
    wf = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    assert "concurrency:" in wf and "group: deploy-production" in wf
    assert re.search(r"^\s+check:\s*$", wf, flags=re.M) and "needs: check" in wf
    assert "py_compile" in wf and "pytest" in wf
    assert "curl -fsS http://127.0.0.1:5601/healthz" in wf
    assert 'git reset --hard "$PREV"' in wf
    assert "actions/checkout@" in wf and "@v4" not in wf          # azioni fissate a SHA


def test_requirements_declare_every_runtime_package():
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for pkg in ("flask", "edge-tts", "ebooklib", "beautifulsoup4", "lxml", "pymupdf", "openai", "pillow", "requests", "defusedxml"):
        assert re.search(rf"^{re.escape(pkg)}\b", req, flags=re.M), pkg
    assert not re.search(r"^ruff\b", req, flags=re.M)             # dev-only
    dev = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "ruff" in dev and "pytest" in dev
    ci = "\n".join(l for l in (ROOT / "requirements-ci.txt").read_text(encoding="utf-8").splitlines()
                   if l.strip() and not l.lstrip().startswith("#"))
    assert "torch" not in ci and "modelscope" not in ci and "flask" in ci
