"""E3, seam admin parte 1 (2026-10-10): pagine e API dell'audit premium nel
blueprint `routes_admin_audit`; la guardia e le policy restano della app e
si risolvono a ogni richiesta."""
import inspect
import re

import pytest

import audiobook_app
import routes_admin_audit as ra

ROUTES = ("/admin/audit-premium", "/admin/audit-tts", "/admin/audit-translations",
          "/admin/api/gemini_cost_audit", "/admin/api/gemini_kill_switch", "/admin/api/tts_backend",
          "/admin/api/gemini_model_availability", "/admin/api/gemini_cost_audit/languages",
          "/admin/api/translation_cost_audit", "/admin/api/translation_cost_audit/languages",
          "/admin/api/optimization_cost_audit", "/admin/api/voice_clone_audit", "/admin/api/accounts_audit",
          "/admin/api/optimization_cost_audit/languages", "/admin/api/gemini_cost_audit/recalc-params")


def test_routes_live_in_the_blueprint_and_nowhere_else():
    rules = {r.rule: r.endpoint for r in audiobook_app.app.url_map.iter_rules()}
    for route in ROUTES:
        assert rules[route].startswith("admin_audit."), route
    src = inspect.getsource(audiobook_app)
    for route in ROUTES:
        assert f'@app.route("{route}"' not in src, route
    for name in ("def _synth_running_gemini_audit_records(", "def _apply_cancel_effective(", "def _manual_probe_start(",
                 "def _tts_backend_payload(", "_FULL_REFUND_OUTCOMES = "):
        assert name not in src and name in inspect.getsource(ra), name
    assert "app.register_blueprint(routes_admin_audit.bp)" in src
    # Nessun import dell'entry point ne' del motore (ricevuto da configure).
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine)\b", inspect.getsource(ra), flags=re.M)


def test_guard_and_policies_resolve_on_the_app_at_request_time(monkeypatch):
    audiobook_app.app.config["TESTING"] = True
    monkeypatch.setattr(audiobook_app.time, "sleep", lambda s: None)
    c = audiobook_app.app.test_client()
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "")
    r = c.get("/admin/api/gemini_cost_audit")
    assert r.status_code == 404 and r.get_json() == {"error": "Admin UI disabled"}
    r = c.get("/admin/audit-premium")
    assert r.status_code == 404 and "disabled" in r.get_data(as_text=True)
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-seam")
    assert c.get("/admin/api/gemini_cost_audit").status_code == 401
    monkeypatch.setattr(audiobook_app, "_admin_auth_ok", lambda provided: True)        # patch sulla app, vista dal blueprint
    monkeypatch.setattr(audiobook_app, "_render_admin_gate", lambda title, url: "GATE")
    assert c.get("/admin/api/gemini_cost_audit/languages").status_code == 200
    monkeypatch.setattr(audiobook_app, "_admin_auth_ok", lambda provided: False)
    r = c.get("/admin/audit-premium")
    assert r.status_code == 200 and r.get_data(as_text=True) == "GATE"
    r = c.get("/admin/audit-tts")
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/audit-premium#tab-tts")


def test_shared_state_is_the_same_object(monkeypatch):
    assert ra._jobs() is audiobook_app.jobs and ra._jobs_lock is audiobook_app._jobs_lock
    import generation_engine
    assert ra.generation_engine is generation_engine
    assert audiobook_app._ACTIVE_JOB_STATUSES is ra._ACTIVE_JOB_STATUSES
    logged = []
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: logged.append(a))
    ra._log_activity("J", "x")
    assert logged == [("J", "x")]
