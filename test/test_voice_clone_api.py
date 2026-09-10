"""Endpoint della voce campione (spec §3.4-§3.8, §6.6, §7.2, §9, §12)."""
import io
import json
import os

import pytest

import audiobook_app
import community_store
import email_service
import payment
import storage_backend
import voice_clone as vc
import voice_clone_audio as vca
import voice_clone_demo as vcd
import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
PROMPT_IT = None   # letto dal modulo prompts nella fixture


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave-di-prova")
    monkeypatch.setenv("ABM_VOICE_CLONE_ENABLED", "1")
    monkeypatch.setenv("ABM_VOICE_CLONE_ASR", "0")
    monkeypatch.delenv("ABM_EUR_CLONED_VOICE", raising=False)
    voxcpm_catalog.invalidate_cache()
    community_store.init(tmp_path)
    vc.init(tmp_path)
    vca.init(tmp_path)
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path / "up")
    (tmp_path / "up").mkdir()
    monkeypatch.setattr(audiobook_app, "BASE_URL", "https://abm.test")
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_OPT_DONE_FILE", tmp_path / "_paid_opt_done.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_opt_done", set())
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    monkeypatch.setattr(payment, "EUR_CLONED_VOICE", 5.0)
    monkeypatch.setattr(audiobook_app, "_ip_rl_buckets", {})
    inviate = []
    monkeypatch.setattr(email_service, "_send_email",
                        lambda to, subj, body, **kw: inviate.append((to, subj, body)) or True)
    monkeypatch.setattr(vcd, "start_demos", lambda cid, **kw: vc.get(cid))
    audiobook_app._invalidate_voices_cache()
    yield inviate
    voxcpm_catalog.invalidate_cache()


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie(audiobook_app._CLIENT_COOKIE_NAME, "cid-uno")
        yield c


def _cid(client, cid):
    client.set_cookie(audiobook_app._CLIENT_COOKIE_NAME, cid)


def _prompt():
    import voice_clone_prompts
    return voice_clone_prompts.prompt_for("it", "f")


def _draft(tmp_path, cid="cid-uno"):
    s = tmp_path / f"{cid}-s.wav"
    s.write_bytes(b"RIFF")
    o = tmp_path / f"{cid}-o.webm"
    o.write_bytes(b"webm")
    return vc.create_draft(cid, lang="it", locale="it-IT", gender="f", prompt_text=_prompt(),
                           sample_wav=str(s), original_path=str(o), original_ext="webm",
                           metrics={"duration": 15.0}, ui_lang="it")


def _paid(tmp_path, cid="cid-uno", email="u@example.com"):
    rec = _draft(tmp_path, cid)
    out, _ = vc.commit(rec["id"], cid, email=email, extra_id="memory", extra_text="e",
                       common_text="c", payment_token="", price_eur=0.0)
    return out


def test_config_e_prompt(client):
    r = client.get("/api/voice_clone/config")
    assert r.status_code == 200
    d = r.get_json()
    assert d["enabled"] is True and d["price_eur"] == 5.0 and d["free"] is False
    assert "it" in d["languages"] and d["regen_max"] == 3 and d["max_upload_mb"] == 20
    r = client.get("/api/voice_clone/prompt?lang=it&gender=f")
    assert r.status_code == 200 and r.get_json()["text"] == _prompt()
    assert client.get("/api/voice_clone/prompt?lang=xx&gender=f").status_code == 400


def test_disabilitato_risponde_404(client, monkeypatch):
    monkeypatch.setenv("ABM_VOICE_CLONE_ENABLED", "0")
    r = client.get("/api/voice_clone/config")
    assert r.status_code == 404 and r.get_json()["error_code"] == "voice_clone_disabled"
    r = client.get("/api/voices")
    assert r.status_code == 200 and r.get_json()["_mine"] == []


def test_sample_rifiutato_dal_gate(client, monkeypatch):
    def rifiuta(src, dst, **kw):
        raise vca.SampleRejected("vc_gate_short", "3.0s")
    monkeypatch.setattr(vca, "prepare_sample", rifiuta)
    r = client.post("/api/voice_clone/sample", data={
        "file": (io.BytesIO(b"webm-bytes"), "rec.webm"), "lang": "it", "locale": "it-IT",
        "gender": "f", "prompt_version": "x"}, content_type="multipart/form-data")
    assert r.status_code == 400
    d = r.get_json()
    assert d["error_code"] == "sample_rejected" and d["reason"] == "vc_gate_short"
    assert not [f for f in os.listdir(audiobook_app.UPLOAD_DIR) if f.startswith("vc_")]


def test_sample_ok_crea_la_bozza(client, monkeypatch):
    def prepara(src, dst, **kw):
        open(dst, "wb").write(b"RIFF-wav")
        return vca.Metrics(**{f: 0.0 for f in vca.Metrics.__dataclass_fields__})
    monkeypatch.setattr(vca, "prepare_sample", prepara)
    r = client.post("/api/voice_clone/sample", data={
        "file": (io.BytesIO(b"webm-bytes"), "rec.webm"), "lang": "it", "locale": "it-IT",
        "gender": "f", "prompt_version": "x"}, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["state"] == "sample_ok" and vc.get(d["clone_id"])["devices"][0]["cid"] == "cid-uno"
    assert not [f for f in os.listdir(audiobook_app.UPLOAD_DIR) if f.startswith("vc_")]


def test_sample_rate_limit_per_cid(client, monkeypatch):
    def rifiuta(src, dst, **kw):
        raise vca.SampleRejected("vc_gate_short", "3.0s")
    monkeypatch.setattr(vca, "prepare_sample", rifiuta)
    codes = []
    for _ in range(11):
        r = client.post("/api/voice_clone/sample", data={
            "file": (io.BytesIO(b"x"), "rec.webm"), "lang": "it", "locale": "it-IT", "gender": "f"},
            content_type="multipart/form-data")
        codes.append(r.status_code)
    assert codes[-1] == 429 and codes[:10] == [400] * 10


def test_demo_texts(client):
    r = client.get("/api/voice_clone/demo_texts?locale=it-IT")
    assert r.status_code == 200
    d = r.get_json()
    assert d["common"]["text"] and d["extra"]
    testi = [e["text"] for e in d["extra"]]
    assert len(testi) == len(set(testi)) and d["common"]["text"] not in testi
    assert client.get("/api/voice_clone/demo_texts?locale=xx-XX").status_code == 400


def test_commit_gratis_e_doppio_click(client, tmp_path, monkeypatch, ambiente):
    monkeypatch.setattr(payment, "EUR_CLONED_VOICE", 0.0)
    rec = _draft(tmp_path)
    extra = client.get("/api/voice_clone/demo_texts?locale=it-IT").get_json()["extra"][0]["id"]
    body = {"clone_id": rec["id"], "email": "U@example.com", "email2": "u@example.com ",
            "extra_id": extra, "payment_token": ""}
    r = client.post("/api/voice_clone/commit", json=body)
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["created"] is True and d["voice_code"] == vc.get(rec["id"])["voice_code"]
    assert ambiente[-1][0] == "u@example.com" and "/vc/" in ambiente[-1][2]
    assert vc.get(rec["id"])["resume_token"]["value"] in ambiente[-1][2]
    r = client.post("/api/voice_clone/commit", json=body)
    assert r.status_code == 200 and r.get_json()["created"] is False
    assert len(ambiente) == 1


def test_commit_errori(client, tmp_path, monkeypatch):
    rec = _draft(tmp_path)
    extra = client.get("/api/voice_clone/demo_texts?locale=it-IT").get_json()["extra"][0]["id"]
    base = {"clone_id": rec["id"], "email": "a@x.it", "email2": "a@x.it", "extra_id": extra,
            "payment_token": "NOPE"}
    r = client.post("/api/voice_clone/commit", json=dict(base, email2="b@x.it"))
    assert r.status_code == 400 and r.get_json()["error_code"] == "email_mismatch"
    r = client.post("/api/voice_clone/commit", json=base)
    assert r.status_code == 402 and r.get_json()["error_code"] == "payment_invalid"
    _paid(tmp_path, cid="cid-due", email="a@x.it")
    monkeypatch.setattr(payment, "EUR_CLONED_VOICE", 0.0)
    r = client.post("/api/voice_clone/commit", json=base)
    assert r.status_code == 409 and r.get_json()["error_code"] == "email_has_voice"
    _cid(client, "cid-tre")
    r = client.post("/api/voice_clone/commit", json=dict(base, email="c@x.it", email2="c@x.it"))
    assert r.status_code == 403 and r.get_json()["error_code"] == "not_authorized"


def test_commit_su_voce_terminale_rimborsa_la_capture_orfana(client, tmp_path):
    """C1 item 1: se la voce diventa terminale (qui: scaduta) prima che una
    capture PayPal per essa venga incassata, e l'utente prova comunque a
    confermare il pagamento, l'uscita 410 voice_gone deve rimborsare subito
    la capture invece di lasciarla orfana fino al prossimo giro di sweep."""
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready", "ready", "expired"):
        vc.transition(rec["id"], s)
    payment._payments["ORD-VC-1"] = {"order_id": "ORD-VC-1", "amount_eur": 5.0, "email": "a@x.it",
                                     "captured_at": 1_000_000, "used": False, "job_id": "vc:" + rec["id"]}
    extra = client.get("/api/voice_clone/demo_texts?locale=it-IT").get_json()["extra"][0]["id"]
    r = client.post("/api/voice_clone/commit", json={
        "clone_id": rec["id"], "email": "a@x.it", "email2": "a@x.it",
        "extra_id": extra, "payment_token": "ORD-VC-1"})
    assert r.status_code == 410 and r.get_json()["error_code"] == "voice_gone"
    assert payment._payments["ORD-VC-1"]["used"] is True


def test_paypal_order(client, tmp_path, monkeypatch):
    rec = _draft(tmp_path)
    monkeypatch.setattr(audiobook_app, "_paypal_available", lambda: True)
    catturato = {}

    def crea(amount, description, custom_id=None):
        catturato.update(amount=amount, description=description, custom_id=custom_id)
        return {"id": "ORD-1", "status": "CREATED"}
    monkeypatch.setattr(audiobook_app, "_paypal_create_order", crea)
    r = client.post("/api/paypal_create_order_voice_clone", json={"clone_id": rec["id"]})
    assert r.status_code == 200 and r.get_json() == {"order_id": "ORD-1", "amount_eur": 5.0, "status": "CREATED"}
    assert catturato == {"amount": 5.0, "description": "Voice sample - Audiobook Maker",
                         "custom_id": "vc:" + rec["id"]}
    _cid(client, "altro")
    assert client.post("/api/paypal_create_order_voice_clone", json={"clone_id": rec["id"]}).status_code == 403


def test_progress_sse_termina_su_demos_ready(client, tmp_path):
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready"):
        vc.transition(rec["id"], s)
    r = client.get(f"/api/voice_clone/progress/{rec['id']}")
    assert r.status_code == 200 and r.mimetype == "text/event-stream"
    payload = json.loads(r.get_data(as_text=True).strip().split("data: ")[-1])
    assert payload["state"] == "demos_ready" and payload["regen_left"] == 3
    assert payload["demo_urls"]["common"].endswith("/demo/common")
    assert "token" not in payload and "owner_email" not in payload
    _cid(client, "altro")
    assert client.get(f"/api/voice_clone/progress/{rec['id']}").status_code == 403
    assert client.get("/api/voice_clone/progress/vc_nope").status_code == 404


def test_approve_regenerate_reject(client, tmp_path, monkeypatch, ambiente):
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready"):
        vc.transition(rec["id"], s)
    monkeypatch.setattr(vc, "upload_to_r2", lambda r, n: True)
    r = client.post(f"/api/voice_clone/{rec['id']}/regenerate", json={"extra_id": "nope"})
    assert r.status_code == 400
    extra = client.get("/api/voice_clone/demo_texts?locale=it-IT").get_json()["extra"][0]["id"]
    monkeypatch.setattr(vcd, "start_demos", lambda cid, **kw: vc.get(cid))
    r = client.post(f"/api/voice_clone/{rec['id']}/regenerate", json={"extra_id": extra})
    assert r.status_code == 200 and r.get_json()["regen_left"] == 2
    # start_demos e' mockato no-op (fixture ambiente): regenerate() resta in
    # demos_ready, non demos_generating. Nessuna transizione manuale serve.
    r = client.post(f"/api/voice_clone/{rec['id']}/approve")
    assert r.status_code == 200 and r.get_json()["state"] == "ready"
    assert ambiente[-1][1] == "La tua voce campione è pronta"
    r = client.post(f"/api/voice_clone/{rec['id']}/approve")
    assert r.status_code == 409 and r.get_json()["error_code"] == "bad_state"
    r = client.post(f"/api/voice_clone/{rec['id']}/reject")
    assert r.status_code == 409
    altro = _paid(tmp_path, cid="cid-due", email="b@x.it")
    for s in ("demos_generating", "demo_failed"):
        vc.transition(altro["id"], s)
    _cid(client, "cid-due")
    r = client.post(f"/api/voice_clone/{altro['id']}/reject")
    assert r.status_code == 200 and r.get_json()["state"] == "refunded"
    assert client.post(f"/api/voice_clone/{altro['id']}/reject").status_code == 200


def test_mine_claim_confirm_forget(client, tmp_path, ambiente):
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready", "ready"):
        vc.transition(rec["id"], s)
    d = client.get("/api/voice_clone/mine").get_json()["voices"]
    assert d[0]["id"] == rec["id"] and d[0]["owner"] is True and d[0]["voice_code"]
    _cid(client, "cid-due")
    assert client.get("/api/voice_clone/mine").get_json()["voices"] == []
    r = client.post("/api/voice_clone/claim", json={"voice_code": "ZZZZ-ZZZZ-ZZZZ"})
    assert r.status_code == 404 and r.get_json()["error_code"] == "code_unknown"
    r = client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"].lower()})
    assert r.status_code == 200 and r.get_json()["status"] == "pending"
    codice = vc.get(rec["id"])["pending_confirm"]
    assert ambiente[-1][0] == "u@example.com"
    r = client.post("/api/voice_clone/confirm", json={"voice_code": rec["voice_code"], "confirm_code": "000000"})
    assert r.status_code == 400 and r.get_json()["error_code"] == "confirm_wrong"
    import re
    vero = re.search(r"\b(\d{6})\b", ambiente[-1][2]).group(1)
    r = client.post("/api/voice_clone/confirm", json={"voice_code": rec["voice_code"], "confirm_code": vero})
    assert r.status_code == 200 and r.get_json()["status"] == "ok"
    assert ambiente[-1][1] in ("Nuovo dispositivo autorizzato", "New device authorized")
    mine = client.get("/api/voice_clone/mine").get_json()["voices"]
    assert mine[0]["owner"] is False and "voice_code" not in mine[0]
    assert client.get("/api/voices").get_json()["_mine"][0]["id"] == rec["id"]
    assert client.post(f"/api/voice_clone/{rec['id']}/forget").status_code == 200
    assert client.get("/api/voice_clone/mine").get_json()["voices"] == []
    assert client.post(f"/api/voice_clone/{rec['id']}/resend").status_code == 403


def test_forget_rifiuta_il_dispositivo_proprietario(client, tmp_path):
    """m1: il dispositivo creatore non puo' essere dimenticato via API (409
    bad_state); solo "Cancella" (delete_by_owner, /vc/<token>/delete)."""
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready", "ready"):
        vc.transition(rec["id"], s)
    r = client.post(f"/api/voice_clone/{rec['id']}/forget")
    assert r.status_code == 409 and r.get_json()["error_code"] == "bad_state"
    assert vc.authorized(vc.voice_id_of(rec), "cid-uno")


def test_notify_rimborso_non_logga_l_email_se_l_invio_fallisce(client, tmp_path, monkeypatch, capsys):
    """m3: se l'invio dell'email di rimborso fallisce, lo stdout deve
    riportare solo type(e).__name__, mai il messaggio d'eccezione (puo'
    contenere l'indirizzo email del destinatario)."""
    rec = _paid(tmp_path, email="segreto@example.com")
    vc.transition(rec["id"], "demos_generating")
    vc.transition(rec["id"], "demo_failed")

    def esplode(*a, **kw):
        raise RuntimeError("SMTP rifiutato per segreto@example.com")
    monkeypatch.setattr(email_service, "send_voice_clone_refunded", esplode)
    r = client.post(f"/api/voice_clone/{rec['id']}/reject")
    assert r.status_code == 200 and r.get_json()["state"] == "refunded"
    out = capsys.readouterr().out
    assert "segreto@example.com" not in out
    assert "RuntimeError" in out


def test_resend_solo_proprietario_e_3_al_giorno(client, tmp_path, ambiente):
    rec = _paid(tmp_path)
    codes = [client.post(f"/api/voice_clone/{rec['id']}/resend").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429] and len(ambiente) == 3


def test_file_audio_solo_autorizzati(client, tmp_path):
    rec = _paid(tmp_path)
    r = client.get(f"/api/voice_clone/{rec['id']}/sample.wav")
    assert r.status_code == 200 and r.mimetype == "audio/wav"
    assert client.get(f"/api/voice_clone/{rec['id']}/demo/common").status_code == 404
    _cid(client, "altro")
    assert client.get(f"/api/voice_clone/{rec['id']}/sample.wav").status_code == 403


def test_pagine_vc(client, tmp_path):
    rec = _paid(tmp_path)
    _cid(client, "cid-nuovo")
    r = client.get(f"/vc/{rec['resume_token']['value']}/resume")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/?vc={rec['id']}")
    assert r.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert any(d["cid"] == "cid-nuovo" and d["via"] == "resume" for d in vc.get(rec["id"])["devices"])
    assert client.get("/vc/nope/resume").status_code == 404
    r = client.get(f"/vc/{rec['manage_token']}/devices")
    assert r.status_code == 200 and b"cid-nuovo" not in r.data and b"resume" in r.data
    r = client.post(f"/vc/{rec['manage_token']}/devices/revoke", data={"cid": "cid-nuovo"})
    assert r.status_code in (200, 302)
    assert not any(d["cid"] == "cid-nuovo" for d in vc.get(rec["id"])["devices"])
    assert client.get(f"/vc/{rec['manage_token']}/delete").status_code == 200
    r = client.post(f"/vc/{rec['manage_token']}/delete")
    assert r.status_code == 200 and vc.get(rec["id"])["state"] == "deleted"
    assert not os.path.isdir(vc.voice_dir(rec["token"]))
    assert client.get(f"/vc/{rec['manage_token']}/devices").status_code == 404


def test_voice_code_non_trapela_a_dispositivi_non_proprietari(client, tmp_path, ambiente):
    """Fix round 1 (CRITICAL): voice_code va restituito solo da commit() e da
    mine() al proprietario. progress/approve/reject (via _vc_view) non lo
    devono mai includere, nemmeno al proprietario stesso."""
    import re
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready"):
        vc.transition(rec["id"], s)
    _cid(client, "cid-due")
    r = client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"]})
    assert r.status_code == 200 and r.get_json()["status"] == "pending"
    codice = re.search(r"\b(\d{6})\b", ambiente[-1][2]).group(1)
    r = client.post("/api/voice_clone/confirm", json={"voice_code": rec["voice_code"], "confirm_code": codice})
    assert r.status_code == 200 and "voice_code" not in r.get_json()["voice"]
    r = client.get(f"/api/voice_clone/progress/{rec['id']}")
    payload = json.loads(r.get_data(as_text=True).strip().split("data: ")[-1])
    assert "voice_code" not in payload
    r = client.post(f"/api/voice_clone/{rec['id']}/reject")
    assert r.status_code == 200 and "voice_code" not in r.get_json()
    altro = _paid(tmp_path, cid="cid-tre", email="c@x.it")
    for s in ("demos_generating", "demos_ready"):
        vc.transition(altro["id"], s)
    _cid(client, "cid-tre")
    r = client.post(f"/api/voice_clone/{altro['id']}/approve")
    assert r.status_code == 200 and "voice_code" not in r.get_json()


def test_confirm_codice_sconosciuto(client):
    """Fix round 1 (IMPORTANT): confirm() con voice_code sconosciuto/terminale
    solleva VoiceGone; l'endpoint deve tornare 404 code_unknown, non 500."""
    r = client.post("/api/voice_clone/confirm", json={"voice_code": "ZZZZ-ZZZZ-ZZZZ", "confirm_code": "123456"})
    assert r.status_code == 404 and r.get_json()["error_code"] == "code_unknown"


def test_claim_codice_sconosciuto(client):
    """Fix round 1 (IMPORTANT): claim() su codice sconosciuto deve dare
    404 code_unknown via except VoiceGone, senza sniffing sul messaggio."""
    r = client.post("/api/voice_clone/claim", json={"voice_code": "ZZZZ-ZZZZ-ZZZZ"})
    assert r.status_code == 404 and r.get_json()["error_code"] == "code_unknown"


def test_claim_locked_dopo_troppi_tentativi_di_conferma(client, tmp_path, ambiente):
    """Fix round 1 (IMPORTANT): il solo ValueError residuo di claim() e' il
    lock (423 code_locked), esaurito qui per la via reale (5 conferme
    sbagliate di fila bloccano il cid, non il codice sconosciuto)."""
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready"):
        vc.transition(rec["id"], s)
    _cid(client, "cid-due")
    r = client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"]})
    assert r.status_code == 200 and r.get_json()["status"] == "pending"
    r = None
    for _ in range(vc.CONFIRM_MAX_TRIES):
        r = client.post("/api/voice_clone/confirm",
                        json={"voice_code": rec["voice_code"], "confirm_code": "000000"})
    assert r.status_code == 423 and r.get_json()["error_code"] == "code_locked"
    r = client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"]})
    assert r.status_code == 423 and r.get_json()["error_code"] == "code_locked"
