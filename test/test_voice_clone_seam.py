"""E3, seam voice clone (2026-10-10): API e pagine della voce campionata nel
blueprint `routes_voice_clone`; helper e valori della app risolti a ogni richiesta."""
import inspect
import re

import pytest

import audiobook_app
import routes_voice_clone as rv

ROUTES = ("/api/voice_clone/config", "/api/voice_clone/sample", "/api/voice_clone/commit",
          "/api/paypal_create_order_voice_clone", "/api/voice_clone/progress/<clone_id>",
          "/api/voice_clone/<clone_id>/approve", "/api/voice_clone/mine", "/api/voice_clone/claim",
          "/api/voice_clone/<clone_id>/sample.wav", "/vc/<token>/resume", "/vc/<token>/devices", "/vc/<token>/delete")


def test_routes_and_helpers_live_in_the_blueprint():
    rules = {r.rule: r.endpoint for r in audiobook_app.app.url_map.iter_rules()}
    for route in ROUTES:
        assert rules[route].startswith("vc."), route
    src = inspect.getsource(audiobook_app)
    assert not re.search(r'@app\.route\("/(api/voice_clone|vc)/', src)
    for name in ("def _vc_gate(", "def _vc_page(", "def _voice_clone_notify(", "def _vc_send_manage_email(",
                 "_VC_ID_RE = ", "RESUME_DEVICES_MAX = "):
        assert name not in src and name in inspect.getsource(rv), name
    assert "app.register_blueprint(routes_voice_clone.bp)" in src
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine)\b", inspect.getsource(rv), flags=re.M)
    assert "os.environ.get(" not in inspect.getsource(rv)
    for n in rv.FUNCS:
        assert callable(rv._cfg[n]), n                  # configurata dalla app (anche se vive in un altro seam)
    # App e seam account usano ancora gate, url, log e notifica della voce campionata: via blueprint.
    import routes_account
    both = src + inspect.getsource(routes_account)
    for n in ("routes_voice_clone._vc_gate(", "routes_voice_clone._vc_urls(", "routes_voice_clone._vc_log(",
              "routes_voice_clone._voice_clone_notify"):
        assert n in both, n


def test_helpers_and_values_resolve_on_the_app(monkeypatch, tmp_path):
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(audiobook_app, "BASE_URL", "https://seam.test")
    assert rv._upload_dir() == tmp_path and rv._base_url() == "https://seam.test"
    monkeypatch.setattr(audiobook_app, "_get_client_id", lambda: "cid-seam")
    monkeypatch.setattr(audiobook_app, "_paypal_available", lambda: "pp")
    monkeypatch.setattr(audiobook_app, "_ip_rl_check", lambda *a, **k: "rl")
    assert rv._get_client_id() == "cid-seam" and rv._paypal_available() == "pp" and rv._ip_rl_check("b", "1.1.1.1", 1, 1) == "rl"
    assert rv._VC_PAGES_I18N is audiobook_app._VC_PAGES_I18N and rv._LANG_COOKIE == audiobook_app._LANG_COOKIE


def test_config_endpoint_served_by_blueprint():
    audiobook_app.app.config["TESTING"] = True
    c = audiobook_app.app.test_client()
    r = c.get("/api/voice_clone/config")
    assert r.status_code in (200, 503)
    assert r.is_json
