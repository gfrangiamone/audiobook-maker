"""Store, identita', bozza e transizioni delle voci campionate (spec §6, §10)."""
import os
import threading

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


def test_create_draft_rifiuta_original_ext_non_ammessa(tmp_path):
    with pytest.raises(ValueError):
        bozza(tmp_path, original_ext="../evil")
    assert os.listdir(vc.voices_dir()) == []
    with pytest.raises(ValueError):
        bozza(tmp_path, original_ext="EXE")     # non nella whitelist, pur regex-valida
    assert os.listdir(vc.voices_dir()) == []


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


def test_purge_stale_drafts_record_cade_anche_se_i_file_falliscono(tmp_path, monkeypatch):
    a = bozza(tmp_path, cid="cid-a")
    b = bozza(tmp_path, cid="cid-b")
    scaduta = max(a["expires_at"], b["expires_at"]) + 1

    originale = vc.remove_files
    chiamate = []

    def _remove_files(rec):
        chiamate.append(rec["id"])
        if rec["id"] == a["id"]:
            raise OSError("permesso negato")
        return originale(rec)
    monkeypatch.setattr(vc, "remove_files", _remove_files)

    n = vc.purge_stale_drafts(now=scaduta)
    assert n == 2                              # entrambi i record cadono
    assert sorted(chiamate) == sorted([a["id"], b["id"]])
    assert vc.get(a["id"]) is None and vc.get(b["id"]) is None
    assert not os.path.exists(vc.voice_dir(b["token"]))    # b: file rimossi regolarmente


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


def test_bozza_precedente_sopravvive_se_lo_spostamento_fallisce(tmp_path, monkeypatch):
    prima = bozza(tmp_path)
    monkeypatch.setattr(vc.shutil, "move",
                         lambda *a, **kw: (_ for _ in ()).throw(OSError("disco pieno")))
    with pytest.raises(OSError):
        bozza(tmp_path)
    ancora = vc.draft_for_cid("cid-uno")
    assert ancora["id"] == prima["id"]
    assert os.path.exists(os.path.join(vc.voice_dir(prima["token"]), "sample.wav"))
    assert os.listdir(vc.voices_dir()) == [prima["token"]]


def _pronta(tmp_path, cid="cid-uno", **kw):
    rec = bozza(tmp_path, cid=cid, **kw)
    vc.transition(rec["id"], "paid"); vc.transition(rec["id"], "demos_generating")
    vc.transition(rec["id"], "demos_ready")
    return vc.transition(rec["id"], "ready")


def test_resolve_ritorna_wav_e_frase(tmp_path):
    rec = _pronta(tmp_path)
    out = vc.resolve(vc.voice_id_of(rec))
    assert out["wav_path"] == os.path.join(vc.voice_dir(rec["token"]), "sample.wav")
    assert out["prompt_text"] == PROMPT and out["lang"] == "it" and out["locale"] == "it-IT"
    assert vc.language_of(vc.voice_id_of(rec)) == "it"


def test_resolve_vale_anche_prima_di_ready_ma_non_dopo_la_fine(tmp_path):
    rec = bozza(tmp_path)
    vid = vc.voice_id_of(rec)
    assert vc.resolve(vid)["prompt_text"] == PROMPT       # sample_ok: le demo lo usano
    vc.transition(rec["id"], "paid"); vc.transition(rec["id"], "refunded")
    with pytest.raises(vc.VoiceGone):
        vc.resolve(vid)
    token_ignoto = "0" * 32
    with pytest.raises(vc.VoiceGone) as ei:
        vc.resolve("voxcpm:mine:" + token_ignoto)
    assert token_ignoto not in str(ei.value)       # mai il token nel messaggio
    with pytest.raises(vc.VoiceGone):
        vc.resolve("voxcpm:v2:it-IT/Valentina")


def test_resolve_scarica_da_r2_se_il_locale_manca(tmp_path, monkeypatch):
    rec = _pronta(tmp_path)
    wav = os.path.join(vc.voice_dir(rec["token"]), "sample.wav")
    os.remove(wav)
    richieste = []

    def _dl(key, path):
        richieste.append(key)
        with open(path, "wb") as fh:
            fh.write(b"RIFF-da-r2")
        return True
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "download_file", _dl)
    assert vc.resolve(vc.voice_id_of(rec))["wav_path"] == wav
    assert richieste == ["voices/" + rec["token"] + "/sample.wav"]
    assert open(wav, "rb").read() == b"RIFF-da-r2"


def test_resolve_senza_locale_ne_r2(tmp_path, monkeypatch):
    rec = _pronta(tmp_path)
    os.remove(os.path.join(vc.voice_dir(rec["token"]), "sample.wav"))
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "download_file", lambda k, p: False)
    with pytest.raises(vc.VoiceGone) as ei:
        vc.resolve(vc.voice_id_of(rec))
    assert rec["token"] not in str(ei.value)       # mai il token nel messaggio


def test_resolve_r2_in_errore_di_trasporto_da_sample_unavailable(tmp_path, monkeypatch):
    rec = _pronta(tmp_path)
    os.remove(os.path.join(vc.voice_dir(rec["token"]), "sample.wav"))
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)

    def _boom(k, p):
        raise ConnectionError("r2 irraggiungibile")
    monkeypatch.setattr(storage_backend, "download_file", _boom)
    with pytest.raises(vc.SampleUnavailable) as ei:
        vc.resolve(vc.voice_id_of(rec))
    assert rec["token"] not in str(ei.value)
    assert not issubclass(vc.SampleUnavailable, vc.VoiceGone)
    assert not issubclass(vc.SampleUnavailable, ValueError)


def test_ensure_local_concorrente_scarica_una_sola_volta(tmp_path, monkeypatch):
    rec = _pronta(tmp_path)
    wav = os.path.join(vc.voice_dir(rec["token"]), "sample.wav")
    os.remove(wav)
    chiamate = []
    lock = threading.Lock()

    def _dl(key, path):
        with lock:
            chiamate.append(key)
        import time as _t
        _t.sleep(0.15)
        with open(path, "wb") as fh:
            fh.write(b"RIFF-da-r2")
        return True
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "download_file", _dl)

    risultati = []

    def _worker():
        risultati.append(vc._ensure_local(rec, "sample.wav"))
    t1 = threading.Thread(target=_worker)
    t2 = threading.Thread(target=_worker)
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert len(chiamate) == 1
    assert risultati == [wav, wav]
    assert open(wav, "rb").read() == b"RIFF-da-r2"


def test_check_use_ordine_dei_rifiuti(tmp_path):
    rec = bozza(tmp_path)
    vid = vc.voice_id_of(rec)
    assert vc.check_use(vid, "cid-uno", "it", "it-IT") == "voice_gone"        # non ready
    _ = vc.transition(rec["id"], "paid"); vc.transition(rec["id"], "demos_generating")
    vc.transition(rec["id"], "demos_ready"); vc.transition(rec["id"], "ready")
    assert vc.check_use(vid, "cid-due", "it", "it-IT") == "voice_not_authorized"
    assert vc.check_use(vid, "cid-uno", "en", "en-US") == "voice_lang_mismatch"
    assert vc.check_use(vid, "cid-uno", "it", "it-CH") == "voice_lang_mismatch"
    assert vc.check_use(vid, "cid-uno", "it", "it-IT") == ""
    assert vc.check_use(vid, "cid-uno", "it", "") == ""
    assert vc.check_use("voxcpm:mine:zz", "cid-uno", "it", "it-IT") == "voice_gone"
    assert vc.authorized(vid, "cid-uno") and not vc.authorized(vid, "cid-due")


def test_mine_elenca_le_voci_del_dispositivo(tmp_path):
    a = _pronta(tmp_path, cid="cid-uno")
    b = bozza(tmp_path, cid="cid-uno", lang="en", locale="en-US")   # bozza in sospeso
    _pronta(tmp_path, cid="cid-altro")
    got = vc.mine("cid-uno")
    assert [g["id"] for g in got] == [a["id"], b["id"]]
    assert got[0]["owner"] is True and got[0]["pending"] is False
    assert got[0]["voice_id"] == vc.voice_id_of(a) and "voice_id" not in got[1]
    assert got[1]["pending"] is True
    assert "token" not in got[0] and "manage_token" not in got[0]


def test_mine_esclude_gli_stati_terminali(tmp_path):
    rec = _pronta(tmp_path)
    vc.transition(rec["id"], "deleted")
    assert vc.mine("cid-uno") == []


def test_touch_used_rinnova_la_scadenza(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOICE_CLONE_RETENTION_DAYS", "10")
    rec = _pronta(tmp_path)
    got = vc.touch_used(rec["id"], now=rec["created_at"] + 100)
    assert got["last_used_at"] == rec["created_at"] + 100
    assert got["expires_at"] == rec["created_at"] + 100 + 10 * 86400
    bozza_ = bozza(tmp_path, cid="cid-tre")
    assert vc.touch_used(bozza_["id"]) is None          # non ready: niente rinnovo


def test_storage_download_file_usa_il_client(monkeypatch, tmp_path):
    class _Client:
        def download_file(self, Bucket, Key, Filename):
            with open(Filename, "wb") as fh:
                fh.write(b"ok")
    monkeypatch.setattr(storage_backend, "_get_client", lambda: _Client())
    monkeypatch.setattr(storage_backend, "_BUCKET", "b")
    dest = tmp_path / "giu" / "x.wav"
    assert storage_backend.download_file("voices/t/sample.wav", str(dest)) is True
    assert dest.read_bytes() == b"ok"

    class _Manca:
        def download_file(self, **kw):
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "404"}}, "GetObject")
    monkeypatch.setattr(storage_backend, "_get_client", lambda: _Manca())
    assert storage_backend.download_file("voices/t/no.wav", str(tmp_path / "no.wav")) is False
