"""Store, identita', bozza e transizioni delle voci campionate (spec §6, §10)."""
import os
import time

import pytest

import community_store
import storage_backend
import voice_clone as vc
import voxcpm_catalog

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
PROMPT = "Ogni mattina apro la finestra prima di fare il caffe."


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    yield
    voxcpm_catalog.invalidate_cache()


def _file(tmp_path, name, content=b"RIFF-finto"):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def bozza(tmp_path, cid="cid-uno", **kw):
    args = dict(lang="it", locale="it-IT", gender="f", prompt_text=PROMPT,
                sample_wav=_file(tmp_path, f"{cid}-s.wav"),
                original_path=_file(tmp_path, f"{cid}-o.webm", b"webm"),
                original_ext="webm", metrics={"duration": 16.4, "snr_db": 31.2},
                ui_lang="it")
    args.update(kw)
    return vc.create_draft(cid, **args)


def test_codici_e_token():
    tok = vc.new_token()
    assert len(tok) == 32 and int(tok, 16) >= 0
    code = vc.new_voice_code()
    assert len(code) == 14 and code.count("-") == 2
    assert not set(code.replace("-", "")) & set("01ILO")
    assert vc.normalize_voice_code(" ab7k q2md-4h9x ") == "AB7K-Q2MD-4H9X"
    assert vc.token_of("voxcpm:mine:" + tok) == tok
    assert vc.token_of("voxcpm:v2:it-IT/Valentina") is None
    assert vc.token_of("voxcpm:mine:") is None


def test_create_draft_sposta_i_file_e_salva_il_record(tmp_path):
    rec = bozza(tmp_path)
    assert rec["state"] == "sample_ok" and rec["id"].startswith("vc_")
    assert rec["prompt_text"] == PROMPT and rec["prompt_version"].startswith("sha1:")
    d = vc.voice_dir(rec["token"])
    assert os.path.exists(os.path.join(d, "sample.wav"))
    assert os.path.exists(os.path.join(d, "original.webm"))
    assert rec["sample"]["original_ext"] == "webm" and rec["sample"]["snr_db"] == 31.2
    assert rec["devices"] == [{"cid": "cid-uno", "added_at": rec["created_at"], "via": "creator"}]
    assert rec["expires_at"] == rec["created_at"] + 24 * 3600
    assert vc.get(rec["id"])["token"] == rec["token"]
    assert vc.by_token(rec["token"])["id"] == rec["id"]
    assert vc.by_voice_code(rec["voice_code"].lower().replace("-", ""))["id"] == rec["id"]
    assert vc.by_manage_token(rec["manage_token"])["id"] == rec["id"]


def test_create_draft_rifiuta_lingua_o_genere_fuori_offerta(tmp_path):
    with pytest.raises(ValueError):
        bozza(tmp_path, lang="xx", locale="xx-XX")
    with pytest.raises(ValueError):
        bozza(tmp_path, gender="x")
    with pytest.raises(ValueError):
        bozza(tmp_path, locale="it-CH")       # locale non attivo nel catalogo


def test_nuova_bozza_dello_stesso_cid_sostituisce_la_precedente(tmp_path):
    a = bozza(tmp_path)
    b = bozza(tmp_path)
    assert vc.get(a["id"]) is None
    assert not os.path.exists(vc.voice_dir(a["token"]))
    assert vc.draft_for_cid("cid-uno")["id"] == b["id"]


def test_draft_for_cid_ignora_le_scadute(tmp_path):
    rec = bozza(tmp_path)
    assert vc.draft_for_cid("cid-uno", now=rec["expires_at"] + 1) is None
    assert vc.purge_stale_drafts(now=rec["expires_at"] + 1) == 1
    assert vc.get(rec["id"]) is None
    assert not os.path.exists(vc.voice_dir(rec["token"]))


def test_transizioni_ammesse_e_vietate(tmp_path):
    rec = bozza(tmp_path)
    vc.transition(rec["id"], "paid", {"payment": {"type": "voucher", "amount_eur": 5.0}})
    vc.transition(rec["id"], "demos_generating")
    vc.transition(rec["id"], "demos_ready")
    with pytest.raises(vc.BadTransition):
        vc.transition(rec["id"], "sample_ok")
    got = vc.transition(rec["id"], "ready")
    assert got["state"] == "ready" and got["state_changed_at"] >= rec["created_at"]
    assert got["ready_at"] == got["state_changed_at"]
    with pytest.raises(vc.BadTransition):
        vc.transition(rec["id"], "paid")
    with pytest.raises(vc.VoiceGone):
        vc.transition("vc_inesistente", "paid")


def test_public_view_non_espone_segreti(tmp_path):
    rec = bozza(tmp_path)
    pub = vc.public_view(rec)
    for k in ("token", "manage_token", "resume_token", "owner_email", "pending_confirm", "confirm_locks"):
        assert k not in pub
    assert "voice_id" not in pub            # non e' ready
    assert pub["voice_code"] == rec["voice_code"]
    vc.transition(rec["id"], "paid"); vc.transition(rec["id"], "demos_generating")
    vc.transition(rec["id"], "demos_ready"); ready = vc.transition(rec["id"], "ready")
    assert vc.public_view(ready)["voice_id"] == "voxcpm:mine:" + rec["token"]


def test_resume_token_scade(tmp_path):
    rec = bozza(tmp_path)
    t = rec["resume_token"]["value"]
    assert vc.by_resume_token(t, now=rec["created_at"] + 10)["id"] == rec["id"]
    assert vc.by_resume_token(t, now=rec["resume_token"]["expires_at"] + 1) is None
    assert vc.by_resume_token("sconosciuto") is None


def test_offered_languages_interseca_catalogo_e_frasi():
    off = vc.offered_languages()
    assert off == {"it": ["it-IT"], "en": ["en-GB", "en-US"]} or off == {"it": ["it-IT"], "en": ["en-US"]}


def test_remove_files_chiama_r2_se_attivo(tmp_path, monkeypatch):
    rec = bozza(tmp_path)
    cancellati = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: cancellati.append(p))
    vc.remove_files(rec)
    assert cancellati == ["voices/" + rec["token"] + "/"]
    assert not os.path.exists(vc.voice_dir(rec["token"]))
