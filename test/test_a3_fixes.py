"""Guardie dei fix puntuali del blocco A3 (md_files/PIANO_RAZIONALIZZAZIONE.md).

Ogni test fissa un comportamento che la razionalizzazione ha corretto: se
torna indietro, qui si vede.
"""
import json
from datetime import datetime
from unittest.mock import patch

import pytest


# --- A3.1: le email premium escapano titolo, email e motivo -----------------

def _capture_refund_email(**kw):
    import email_service
    captured = {}

    def fake_send(to_addr, subject, html_body):
        captured["subject"] = subject
        captured["html"] = html_body

    with patch.object(email_service, "_send_email", side_effect=fake_send), \
         patch.object(email_service, "_smtp_available", return_value=True):
        email_service._send_gemini_failed_refund_email(**kw)
    return captured


def test_refund_email_escapes_user_controlled_values():
    cap = _capture_refund_email(
        email='u@x.it"><img src=x>', amount_eur=1.0,
        book_title='<script>alert(1)</script> & "Libro"',
        reason_label="<b>overload</b>", voucher_code="REF-1")
    html = cap["html"]
    assert "<script>" not in html and "<img" not in html and "<b>overload" not in html
    assert "&lt;script&gt;" in html and "&lt;b&gt;overload" in html
    assert "&amp; &quot;Libro&quot;" in html
    assert "REF-1" in html


# --- A3.2: VoxCPM e' una voce PREMIUM anche per le statistiche utente --------

def test_user_stats_counts_voxcpm_as_premium():
    import user_stats
    import voice_utils
    assert user_stats.is_premium_voice("voxcpm:v2:it-IT/Marco") is True
    assert user_stats.is_premium_voice("gemini:flash31:Zephyr") is True
    assert user_stats.is_premium_voice("it-IT-ElsaNeural") is False
    assert user_stats.is_premium_voice is voice_utils.is_premium_voice


# --- A3.3/4: soglie free degli audit uguali a quelle del listino -------------

def test_audit_free_thresholds_come_from_engines():
    import inspect
    import generation_engine as ge
    src = inspect.getsource(ge._write_speechify_audit)
    assert "speechify_tts.free_threshold_eur()" in src
    assert 'ABM_SPEECHIFY_FREE_THRESHOLD_EUR' not in src
    src = inspect.getsource(ge._write_gemini_audit)
    assert "gemini_tts.FREE_THRESHOLD_EUR" in src
    assert 'ABM_GEMINI_FREE_THRESHOLD_EUR' not in src


# --- A3.8: canonical dell'Article per lingua ----------------------------------

def test_article_ld_canonical_follows_language():
    import guide_content
    meta = guide_content._GUIDE_META["free-ebooks"]["it"]
    ld = json.loads(guide_content._build_article_ld("free-ebooks", "it", "https://x.test", meta))
    assert ld["url"] == "https://x.test/guide/free-ebooks/it/"
    meta_en = guide_content._GUIDE_META["free-ebooks"]["en"]
    ld = json.loads(guide_content._build_article_ld("free-ebooks", "en", "https://x.test", meta_en))
    assert ld["url"] == "https://x.test/guide/free-ebooks/"


# --- A3.9: email i18n con fallback per chiave ----------------------------------

def test_email_i18n_table_falls_back_per_key():
    import email_service
    table = {"en": {"a": "A-en", "b": "B-en"}, "fr": {"a": "A-fr"}}
    assert email_service._i18n_table(table, "fr-FR") == {"a": "A-fr", "b": "B-en"}
    assert email_service._i18n_table(table, "zz") == {"a": "A-en", "b": "B-en"}
    assert email_service._i18n_table(table, None) == {"a": "A-en", "b": "B-en"}


# --- A3.10: JsonStore.upsert/modify e pending_jobs sotto un solo lock -------

def test_jsonstore_upsert_and_modify(tmp_path):
    import community_store
    community_store.init(tmp_path)
    s = community_store.JsonStore("t.json")
    s.upsert({"id": "x", "v": 1})
    s.upsert({"id": "x", "v": 2, "w": 3})
    assert [it["id"] for it in s.all()] == ["x"]
    assert s.get("x")["v"] == 2 and s.get("x")["w"] == 3
    assert s.modify("x", lambda it: it.update(v=it["v"] + 1))["v"] == 3
    assert s.modify("missing", lambda it: None) is None


def test_pending_jobs_bump_is_atomic(tmp_path):
    import community_store
    import pending_jobs
    community_store.init(tmp_path)
    pending_jobs.init()
    pending_jobs.register("j1", "generate", {"k": 1})
    assert pending_jobs.mark_running_bump("j1") == 1
    assert pending_jobs.mark_running_bump("j1") == 2
    pending_jobs.register("j1", "generate", {"k": 2})   # upsert: azzera
    assert pending_jobs.mark_running_bump("j1") == 1
    assert pending_jobs.mark_running_bump("nope") == 1


# --- A3.11: cost_carry ha un lock e resta coerente ------------------------------

def test_cost_carry_roundtrip_under_lock(tmp_path):
    import cost_carry
    assert hasattr(cost_carry, "_lock")
    assert cost_carry.write(tmp_path, "gemini", {"cost": 1.0}) is True
    assert cost_carry.write(tmp_path, "voxcpm", {"cost": 2.0}) is True
    assert cost_carry.read(tmp_path, "gemini") == {"cost": 1.0}
    assert cost_carry.clear(tmp_path, "gemini") is True
    assert cost_carry.read(tmp_path, "gemini") == {}
    assert cost_carry.read(tmp_path, "voxcpm") == {"cost": 2.0}
    assert cost_carry.clear(tmp_path, "voxcpm") is True
    assert not (tmp_path / cost_carry.CARRY_NAME).exists()


# --- A3.12: kill-switch Gemini persistito in modo atomico -----------------------

def test_gemini_kill_switch_persists_valid_json(tmp_path, monkeypatch):
    gemini_tts = pytest.importorskip("gemini_tts")
    path = tmp_path / "state" / "kill.json"
    monkeypatch.setattr(gemini_tts, "_admin_state_path", path)
    monkeypatch.setattr(gemini_tts, "_admin_disabled", False)
    try:
        state = gemini_tts.set_admin_disabled(True, "test")
        assert state["persisted"] is True
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk["disabled"] is True and on_disk["reason"] == "test"
        assert not list(path.parent.glob("*.tmp"))
    finally:
        gemini_tts.set_admin_disabled(False, "")


# --- A3.13: metrics_store pota i giorni vecchi ------------------------------------

def test_metrics_store_prunes_old_days():
    import metrics_store
    d = {"2024-01-01": {"app_open": {"ios": 1}},
         "2026-10-01": {"app_open": {"ios": 1}},
         "legacy": {"x": 1}}
    metrics_store._prune(d, today=datetime(2026, 10, 7))
    assert "2024-01-01" not in d
    assert "2026-10-01" in d and "legacy" in d


# --- A3.14: la quota premium segue gli alias device -----------------------------

def test_free_quota_resolves_device_alias(monkeypatch):
    import free_quota
    import free_tts_quota
    monkeypatch.setattr(free_tts_quota, "canonical",
                        lambda cid: "canon" if cid == "alias" else cid)
    assert free_quota._norm_client("alias") == "canon"
    assert free_quota._norm_client("other") == "other"
    assert free_quota._norm_client("") == free_quota._ANON
