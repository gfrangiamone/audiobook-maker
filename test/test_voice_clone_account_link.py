# test/test_voice_clone_account_link.py
"""voice_clone: collegamento delle voci campionate a un account."""
import pytest

import community_store
import storage_backend
import voice_clone as vc


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    yield


def _voice(vid, email, state="ready"):
    rec = {"id": vid, "state": state, "owner_email": email,
           "owner_email_hash": vc.email_hash(email) if email else None}
    vc.store().add(rec)
    return rec


def test_ids_for_email_matches_hash_case_insensitive():
    _voice("vc_a", "A@B.it")
    _voice("vc_b", "a@b.it", state="deleted")
    _voice("vc_c", "other@b.it")
    _voice("vc_d", None)
    assert sorted(vc.ids_for_email("a@b.it")) == ["vc_a", "vc_b"]
    assert vc.ids_for_email("nobody@b.it") == []


def test_link_account_is_idempotent_and_persists():
    _voice("vc_a", "a@b.it")
    assert vc.link_account("vc_a", "ac_1") is True
    assert vc.store().get("vc_a")["account_id"] == "ac_1"
    assert vc.link_account("vc_a", "ac_1") is False
    assert vc.link_account("vc_missing", "ac_1") is False
