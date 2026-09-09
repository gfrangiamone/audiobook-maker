"""Claim, conferma, forget e revoca dei dispositivi (spec §6.3, §6.4)."""
import hashlib
import os

import pytest

import community_store
import storage_backend
import voice_clone as vc
import voxcpm_catalog

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    yield
    voxcpm_catalog.invalidate_cache()


def _pronta(tmp_path, cid="cid-owner"):
    s = tmp_path / f"{cid}-s.wav"; s.write_bytes(b"RIFF")
    o = tmp_path / f"{cid}-o.webm"; o.write_bytes(b"webm")
    rec = vc.create_draft(cid, lang="it", locale="it-IT", gender="m", prompt_text="frase",
                          sample_wav=str(s), original_path=str(o), original_ext="webm",
                          metrics={}, ui_lang="it")
    vc.transition(rec["id"], "paid"); vc.transition(rec["id"], "demos_generating")
    vc.transition(rec["id"], "demos_ready")
    return vc.transition(rec["id"], "ready")


def test_claim_da_cid_gia_autorizzato(tmp_path):
    rec = _pronta(tmp_path)
    esito, got, code = vc.claim(rec["voice_code"], "cid-owner")
    assert esito == "ok" and got["id"] == rec["id"] and code is None


def test_claim_da_cid_nuovo_crea_il_codice_hashato(tmp_path):
    rec = _pronta(tmp_path)
    esito, got, code = vc.claim(rec["voice_code"].lower(), "cid-nuovo", now=1000)
    assert esito == "pending" and len(code) == 6 and code.isdigit()
    pc = vc.get(rec["id"])["pending_confirm"]
    assert pc["cid"] == "cid-nuovo" and pc["tries"] == 0
    assert pc["expires_at"] == 1000 + vc.CONFIRM_TTL_SEC
    assert pc["code_hash"] == hashlib.sha256(code.encode()).hexdigest()
    assert code not in str(vc.get(rec["id"]))


def test_claim_sconosciuto_o_terminale(tmp_path):
    with pytest.raises(vc.VoiceGone):
        vc.claim("AAAA-BBBB-CCCC", "cid-x")
    rec = _pronta(tmp_path)
    vc.transition(rec["id"], "deleted")
    with pytest.raises(vc.VoiceGone):
        vc.claim(rec["voice_code"], "cid-x")


def test_una_nuova_richiesta_sostituisce_la_precedente(tmp_path):
    rec = _pronta(tmp_path)
    _, _, c1 = vc.claim(rec["voice_code"], "cid-a", now=1000)
    _, _, c2 = vc.claim(rec["voice_code"], "cid-b", now=1001)
    assert vc.confirm(rec["voice_code"], "cid-a", c1, now=1002) == "none"
    assert vc.confirm(rec["voice_code"], "cid-b", c2, now=1002) == "ok"


def test_confirm_ok_aggiunge_il_dispositivo(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = vc.claim(rec["voice_code"], "cid-nuovo", now=1000)
    assert vc.confirm(rec["voice_code"], "cid-nuovo", code, now=1100) == "ok"
    got = vc.get(rec["id"])
    assert got["pending_confirm"] is None
    assert {"cid": "cid-nuovo", "added_at": 1100, "via": "code"} in got["devices"]
    assert vc.authorized(vc.voice_id_of(got), "cid-nuovo")
    assert vc.claim(rec["voice_code"], "cid-nuovo")[0] == "ok"


def test_confirm_scaduto(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = vc.claim(rec["voice_code"], "cid-nuovo", now=1000)
    assert vc.confirm(rec["voice_code"], "cid-nuovo", code, now=1000 + vc.CONFIRM_TTL_SEC + 1) == "expired"
    assert vc.get(rec["id"])["pending_confirm"] is None


def test_cinque_tentativi_poi_blocco(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = vc.claim(rec["voice_code"], "cid-nuovo", now=1000)
    for _ in range(4):
        assert vc.confirm(rec["voice_code"], "cid-nuovo", "000000", now=1001) == "wrong"
    assert vc.confirm(rec["voice_code"], "cid-nuovo", "000000", now=1001) == "locked"
    got = vc.get(rec["id"])
    assert got["pending_confirm"] is None
    assert got["confirm_locks"]["cid-nuovo"] == 1001 + vc.CONFIRM_LOCK_SEC
    # il codice giusto ormai non vale, e un nuovo claim e' bloccato
    assert vc.confirm(rec["voice_code"], "cid-nuovo", code, now=1002) == "none"
    with pytest.raises(ValueError, match="locked"):
        vc.claim(rec["voice_code"], "cid-nuovo", now=1002)
    assert vc.claim(rec["voice_code"], "cid-nuovo", now=1001 + vc.CONFIRM_LOCK_SEC + 1)[0] == "pending"


def test_forget_e_revoke(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = vc.claim(rec["voice_code"], "cid-b", now=1000)
    vc.confirm(rec["voice_code"], "cid-b", code, now=1001)
    assert vc.forget(rec["id"], "cid-b") is True
    assert vc.forget(rec["id"], "cid-b") is False
    assert not vc.authorized(vc.voice_id_of(rec), "cid-b")
    assert vc.revoke_device(rec["manage_token"], "cid-owner") is True
    assert vc.revoke_device("token-sbagliato", "cid-owner") is False
    assert vc.get(rec["id"])["devices"] == []
    assert vc.get(rec["id"])["state"] == "ready"        # la voce sopravvive


def test_confirm_locks_scaduti_vengono_potati(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = vc.claim(rec["voice_code"], "cid-nuovo", now=1000)
    for _ in range(5):
        vc.confirm(rec["voice_code"], "cid-nuovo", "000000", now=1001)
    assert vc.get(rec["id"])["confirm_locks"]["cid-nuovo"] == 1001 + vc.CONFIRM_LOCK_SEC

    dopo_scadenza = 1001 + vc.CONFIRM_LOCK_SEC + 1
    # claim (lettura) pota il lock scaduto per un cid diverso
    vc.claim(rec["voice_code"], "cid-altro", now=dopo_scadenza)
    assert "cid-nuovo" not in (vc.get(rec["id"])["confirm_locks"] or {})


def test_confirm_locks_scaduti_potati_alla_scrittura_di_un_nuovo_blocco(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code_a = vc.claim(rec["voice_code"], "cid-a", now=1000)
    for _ in range(5):
        vc.confirm(rec["voice_code"], "cid-a", "000000", now=1001)
    assert vc.get(rec["id"])["confirm_locks"]["cid-a"] == 1001 + vc.CONFIRM_LOCK_SEC

    dopo_scadenza = 1001 + vc.CONFIRM_LOCK_SEC + 1
    _, _, code_b = vc.claim(rec["voice_code"], "cid-b", now=dopo_scadenza)
    for _ in range(5):
        vc.confirm(rec["voice_code"], "cid-b", "000000", now=dopo_scadenza)
    locks = vc.get(rec["id"])["confirm_locks"]
    assert "cid-a" not in locks and locks["cid-b"] == dopo_scadenza + vc.CONFIRM_LOCK_SEC


def test_devices_view_mostra_solo_la_coda_del_cid(tmp_path):
    rec = _pronta(tmp_path, cid="abcd1234efgh")
    view = vc.devices_view(vc.get(rec["id"]))
    assert view == [{"cid_tail": "efgh", "added_at": rec["created_at"], "via": "creator"}]
