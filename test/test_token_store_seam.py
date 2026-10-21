"""E3, primo seam (2026-10-09): token store in `token_store`, deep link /t e /s
nel blueprint `routes_tokens`; audiobook_app non tiene copie."""
import inspect
import re

import pytest

import audiobook_app
import routes_pages
import routes_tokens
import token_store


def test_app_has_no_copy_of_the_store():
    src = inspect.getsource(audiobook_app)
    for name in ("_download_tokens = {}", "def _save_tokens(", "def _load_tokens(", "def _merge_tokens_from_disk(",
                 "def _has_active_download_tokens(", "def _ensure_transfer_token(", "def _render_transfer_landing(",
                 '@app.route("/t/<token>")', '@app.route("/s/<token>")'):
        assert name not in src, name
    import routes_dl, routes_admin_jobs, cleanup, routes_mobile
    total = sum(inspect.getsource(m).count("_tkstore.") for m in (audiobook_app, routes_dl, routes_admin_jobs, cleanup, routes_mobile))
    assert total >= 80                                   # app + blueprint che servono i file (E3)
    assert "app.register_blueprint(routes_tokens.bp)" in src
    # nessuno dei due moduli nuovi importa l'entry point
    for mod in (token_store, routes_tokens):
        assert "audiobook_app" not in inspect.getsource(mod).replace("`audiobook_app`", "")


def test_blueprint_serves_the_landings(monkeypatch):
    audiobook_app.app.config["TESTING"] = True
    monkeypatch.setattr(routes_pages, "_render_install_page", lambda lang, title, body: f"<p>{lang}|{title}</p>")
    routes_tokens.configure(routes_pages._render_install_page)
    c = audiobook_app.app.test_client()
    r = c.get("/t/abc", headers={"Accept-Language": "it-IT"})
    assert r.status_code == 200 and r.get_data(as_text=True).startswith("<p>it|Apri in Audiobook Maker")
    r = c.get("/s/abc", headers={"Accept-Language": "de"})
    assert r.status_code == 200 and "<p>en|Open in Audiobook Maker" in r.get_data(as_text=True)
    rules = {r.rule: r.endpoint for r in audiobook_app.app.url_map.iter_rules()}
    assert rules["/t/<token>"] == "tokens.transfer_landing" and rules["/s/<token>"] == "tokens.share_landing"


def test_app_policies_are_resolved_at_call_time(monkeypatch, tmp_path):
    monkeypatch.setattr(audiobook_app, "_cold_object_available", lambda p: p == "/cold/x.m4b")
    assert token_store.token_cold_available({"output_m4b": "/cold/x.m4b"}) is True
    assert token_store.token_cold_available({"output_m4b": "/local/x.m4b"}) is False
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 10)
    monkeypatch.setattr(token_store, "download_tokens", {"T": {"job_id": "J", "created_at": 1000.0}})
    assert token_store.has_active_download_tokens("J", now=1000.0 + 10 + 300) is True
    assert token_store.has_active_download_tokens("J", now=1000.0 + 10 + 301) is False
    assert token_store.find_available_download_token("J", "", now=1005.0) is None     # client_id diverso
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    assert token_store.load_tokens() is None                                        # file assente: no-op


def test_jobs_with_active_download_tokens_one_pass(monkeypatch):
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 10)
    monkeypatch.setattr(token_store, "download_tokens", {
        "live": {"job_id": "A", "created_at": 1000.0},
        "live2": {"job_id": "A", "created_at": 1200.0},
        "other": {"job_id": "B", "created_at": 1000.0},
        "expired": {"job_id": "C", "created_at": 1000.0 - 311},
        "no_job": {"created_at": 1000.0},
        "no_created": {"job_id": "D"},
        "broken": "not-a-dict",
    })
    live = token_store.jobs_with_active_download_tokens(now=1000.0)
    assert live == {"A", "B"}                                   # scaduto, senza job_id, senza data, malformato: fuori
    assert token_store.jobs_with_active_download_tokens(now=1000.0 + 10 + 301) == {"A"}   # solo live2 resta vivo
    for jid in ("A", "B", "C", "D"):                            # stesso predicato di has_active_download_tokens
        assert (jid in live) == token_store.has_active_download_tokens(jid, now=1000.0), jid


def test_jobs_with_active_download_tokens_skips_a_corrupt_entry(monkeypatch, capsys):
    """Una voce con la data non numerica (o job_id non hashabile) non ferma il passaggio: le due
    buone tornano e l'anomalia finisce nel log."""
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 10)
    monkeypatch.setattr(token_store, "download_tokens", {
        "good1": {"job_id": "A", "created_at": 1000.0},
        "bad_date": {"job_id": "BAD", "created_at": "ieri"},
        "bad_id": {"job_id": ["X"], "created_at": 1000.0},
        "good2": {"job_id": "B", "created_at": 1000.0},
    })
    assert token_store.jobs_with_active_download_tokens(now=1000.0) == {"A", "B"}
    log = capsys.readouterr().out
    assert "BAD" in log and "TypeError" in log and log.count("[tokens]") == 2


def test_transfer_and_share_tables_are_mutated_in_place(monkeypatch, tmp_path):
    monkeypatch.setattr(token_store, "TRANSFER_TOKENS_FILE", tmp_path / "t.json")
    monkeypatch.setattr(token_store, "SHARE_TOKENS_FILE", tmp_path / "s.json")
    monkeypatch.setattr(token_store, "transfer_tokens", {})
    monkeypatch.setattr(token_store, "share_tokens", {"old": {"kind": "ready"}})
    table = token_store.transfer_tokens
    tok = token_store.ensure_transfer_token("J1")
    assert token_store.ensure_transfer_token("J1") == tok and table[tok]["job_id"] == "J1"
    adm = token_store.ensure_admin_copy_token("J1")
    assert adm != tok and table[adm]["admin_copy"] is True
    token_store.transfer_tokens.clear()
    token_store.load_transfer_tokens()
    assert token_store.transfer_tokens is table and set(table) == {tok, adm}
    token_store.save_share_tokens()
    share = token_store.share_tokens
    share["new"] = {"kind": "upload"}
    token_store.load_share_tokens()
    assert token_store.share_tokens is share and set(share) == {"old"}
