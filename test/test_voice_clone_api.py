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


RICHIESTA = {"device_name": "Telefono di Anna", "identity": "Sono Anna, tua sorella"}


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
    assert "it" in d["languages"] and d["max_upload_mb"] == 20
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


def test_sample_wav_non_sovrascrive_loriginale(client, monkeypatch):
    """Regressione (500 sull'endpoint): con un caricamento gia' in .wav il
    percorso del campione normalizzato coincideva con quello dell'originale.
    prepare_sample scriveva sopra il file caricato e create_draft, dopo aver
    spostato sample.wav, non trovava piu' niente da mettere in original.wav."""
    def prepara(src, dst, **kw):
        assert os.path.abspath(src) != os.path.abspath(dst), "stesso file: l'originale si perde"
        open(dst, "wb").write(b"RIFF-normalizzato")
        return vca.Metrics(**{f: 0.0 for f in vca.Metrics.__dataclass_fields__})
    monkeypatch.setattr(vca, "prepare_sample", prepara)
    r = client.post("/api/voice_clone/sample", data={
        "file": (io.BytesIO(b"RIFF-originale"), "voce.wav"), "lang": "it", "locale": "it-IT",
        "gender": "f", "prompt_version": "x"}, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    d = vc.voice_dir(vc.get(r.get_json()["clone_id"])["token"])
    assert open(os.path.join(d, "original.wav"), "rb").read() == b"RIFF-originale"
    assert open(os.path.join(d, "sample.wav"), "rb").read() == b"RIFF-normalizzato"
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
    body = {"clone_id": rec["id"], "email": "U@example.com", "email2": "u@example.com ",
            "payment_token": ""}
    r = client.post("/api/voice_clone/commit", json=body)
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["created"] is True and d["voice_code"] == vc.get(rec["id"])["voice_code"]
    assert ambiente[-1][0] == "u@example.com" and "/vc/" in ambiente[-1][2]
    assert vc.get(rec["id"])["resume_token"]["value"] in ambiente[-1][2]
    r = client.post("/api/voice_clone/commit", json=body)
    assert r.status_code == 200 and r.get_json()["created"] is False
    assert len(ambiente) == 1


def test_il_secondo_brano_lo_sorteggia_il_server(client, tmp_path, monkeypatch):
    """La combo prima del pagamento faceva scegliere fra brani equivalenti: il
    commit non la vuole piu' e pesca da se' fra i candidati della lingua."""
    monkeypatch.setattr(payment, "EUR_CLONED_VOICE", 0.0)
    candidati = {e["text"] for e in
                 client.get("/api/voice_clone/demo_texts?locale=it-IT").get_json()["extra"]}
    rec = _draft(tmp_path)
    r = client.post("/api/voice_clone/commit", json={
        "clone_id": rec["id"], "email": "u@example.com", "email2": "u@example.com",
        "payment_token": ""})
    assert r.status_code == 200, r.get_json()
    demo = vc.get(rec["id"])["demo"]
    assert demo["extra_text"] in candidati and demo["extra_id"]


def test_check_email_dice_subito_se_l_indirizzo_e_occupato(client, tmp_path):
    """Senza questa rotta il conflitto si scopriva dentro commit, cioe' dopo
    aver pagato: il pagamento viene rilasciato, ma l'utente lo scopre a cose
    fatte. Serve la bozza del proprio dispositivo, o diventerebbe un modo per
    sondare gli indirizzi altrui."""
    _paid(tmp_path, cid="cid-due", email="presa@x.it")
    _cid(client, "cid-uno")
    rec = _draft(tmp_path)
    r = client.post("/api/voice_clone/check_email",
                    json={"clone_id": rec["id"], "email": "PRESA@x.it"})
    assert r.status_code == 200 and r.get_json()["taken"] is True
    r = client.post("/api/voice_clone/check_email",
                    json={"clone_id": rec["id"], "email": "libera@x.it"})
    assert r.status_code == 200 and r.get_json()["taken"] is False
    r = client.post("/api/voice_clone/check_email",
                    json={"clone_id": rec["id"], "email": "senza-chiocciola"})
    assert r.status_code == 400
    _cid(client, "cid-tre")
    r = client.post("/api/voice_clone/check_email",
                    json={"clone_id": rec["id"], "email": "libera@x.it"})
    assert r.status_code == 403 and r.get_json()["error_code"] == "not_authorized"


def test_rimanda_il_link_di_gestione_all_indirizzo_occupato(client, tmp_path, ambiente):
    """Per liberare l'indirizzo bisogna cancellare la vecchia voce dal link di
    gestione: se quell'email e' andata persa non c'e' via d'uscita. Il link
    riparte solo verso quell'indirizzo, e il limite di invii e' quello della
    voce che li subisce, condiviso col resend del proprietario."""
    occupante = _paid(tmp_path, cid="cid-due", email="presa@x.it")
    _cid(client, "cid-uno")
    rec = _draft(tmp_path)
    ambiente.clear()
    r = client.post("/api/voice_clone/resend_manage",
                    json={"clone_id": rec["id"], "email": "PRESA@x.it"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert len(ambiente) == 1 and ambiente[-1][0] == "presa@x.it"
    # a chi lo chiede non torna niente sulla voce che occupa l'indirizzo
    assert set(r.get_json()) == {"ok"}
    # indirizzo libero: nessun link da rimandare
    r = client.post("/api/voice_clone/resend_manage",
                    json={"clone_id": rec["id"], "email": "libera@x.it"})
    assert r.status_code == 404 and r.get_json()["error_code"] == "voice_not_found"
    r = client.post("/api/voice_clone/resend_manage",
                    json={"clone_id": rec["id"], "email": "senza-chiocciola"})
    assert r.status_code == 400
    # il tetto e' quello della voce bersagliata: nessuno puo' inondarla
    for _ in range(vc.RESEND_MAX - 1):
        assert client.post("/api/voice_clone/resend_manage",
                           json={"clone_id": rec["id"], "email": "presa@x.it"}).status_code == 200
    r = client.post("/api/voice_clone/resend_manage",
                    json={"clone_id": rec["id"], "email": "presa@x.it"})
    assert r.status_code == 429 and r.get_json()["error_code"] == "rate_limited"
    assert len(vc.get(occupante["id"])["resend_ts"]) == vc.RESEND_MAX
    # e serve comunque la bozza del proprio dispositivo
    _cid(client, "cid-tre")
    r = client.post("/api/voice_clone/resend_manage",
                    json={"clone_id": rec["id"], "email": "presa@x.it"})
    assert r.status_code == 403 and r.get_json()["error_code"] == "not_authorized"


def test_commit_errori(client, tmp_path, monkeypatch):
    rec = _draft(tmp_path)
    base = {"clone_id": rec["id"], "email": "a@x.it", "email2": "a@x.it",
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
    r = client.post("/api/voice_clone/commit", json={
        "clone_id": rec["id"], "email": "a@x.it", "email2": "a@x.it",
        "payment_token": "ORD-VC-1"})
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
    assert payload["state"] == "demos_ready"
    assert payload["demo_urls"]["common"].endswith("/demo/common")
    assert "token" not in payload and "owner_email" not in payload
    _cid(client, "altro")
    assert client.get(f"/api/voice_clone/progress/{rec['id']}").status_code == 403
    assert client.get("/api/voice_clone/progress/vc_nope").status_code == 404


def test_approve_e_rifiuto(client, tmp_path, monkeypatch, ambiente):
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready"):
        vc.transition(rec["id"], s)
    monkeypatch.setattr(vc, "upload_to_r2", lambda r, n: True)
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
    # il player della scheda fa sentire il campione registrato, non una prova
    assert d[0]["sample_url"] == f"/api/voice_clone/{rec['id']}/sample.wav"
    assert client.get(d[0]["sample_url"]).status_code == 200
    _cid(client, "cid-due")
    assert client.get("/api/voice_clone/mine").get_json()["voices"] == []
    r = client.post("/api/voice_clone/claim", json={"voice_code": "ZZZZ-ZZZZ-ZZZZ", **RICHIESTA})
    assert r.status_code == 404 and r.get_json()["error_code"] == "code_unknown"
    r = client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"].lower(), **RICHIESTA})
    assert r.status_code == 200 and r.get_json()["status"] == "pending"
    assert vc.pending_of(vc.get(rec["id"]), "cid-due")
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


def test_discard_butta_via_la_bozza_non_pagata(client, tmp_path):
    """Prima del pagamento non c'e' email, quindi nemmeno link di gestione:
    senza questa via d'uscita la bozza resta in piedi fino alla scadenza e il
    bottone del campionamento dice «riprendi» per sempre."""
    rec = _draft(tmp_path)
    d = vc.voice_dir(rec["token"])
    assert os.path.isdir(d)
    r = client.post(f"/api/voice_clone/{rec['id']}/discard")
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert vc.get(rec["id"])["state"] == "deleted"
    assert not os.path.isdir(d)
    assert client.get("/api/voice_clone/mine").get_json()["voices"] == []


def test_discard_solo_dal_creatore_e_solo_prima_del_pagamento(client, tmp_path):
    rec = _draft(tmp_path)
    _cid(client, "cid-due")
    r = client.post(f"/api/voice_clone/{rec['id']}/discard")
    assert r.status_code == 409 and r.get_json()["error_code"] == "bad_state"
    assert vc.get(rec["id"])["state"] == "sample_ok", "un altro dispositivo non la tocca"
    _cid(client, "cid-uno")
    pagata = _paid(tmp_path, cid="cid-uno", email="altra@example.com")
    r = client.post(f"/api/voice_clone/{pagata['id']}/discard")
    # dopo il pagamento la rinuncia passa da `reject`, che emette il voucher
    assert r.status_code == 409 and r.get_json()["error_code"] == "bad_state"
    assert vc.get(pagata["id"])["state"] != "deleted"


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


def test_resend_solo_proprietario_e_3_al_giorno(client, tmp_path, ambiente, monkeypatch):
    """I3: finestra scorrevole di 24h per voce (rec["resend_ts"]), non un
    bucket per-IP: 3 invii passano, il 4esimo e' 429 con retry_after, e dopo
    24h dal primo invio la finestra scorre e un nuovo invio torna a passare."""
    rec = _paid(tmp_path)
    ora = [1_000_000.0]
    monkeypatch.setattr(vc, "_now", lambda now=None: int(now if now is not None else ora[0]))
    codes = []
    for _ in range(4):
        codes.append(client.post(f"/api/voice_clone/{rec['id']}/resend").status_code)
        ora[0] += 1
    assert codes == [200, 200, 200, 429] and len(ambiente) == 3
    r = client.post(f"/api/voice_clone/{rec['id']}/resend")
    assert r.status_code == 429 and r.get_json()["retry_after"] > 0
    ora[0] = 1_000_000.0 + 86400 + 1
    r = client.post(f"/api/voice_clone/{rec['id']}/resend")
    assert r.status_code == 200 and len(ambiente) == 4


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
    # I4: GET mostra solo la pagina di conferma, non muta nulla.
    r = client.get(f"/vc/{rec['resume_token']['value']}/resume")
    assert r.status_code == 200 and b"Resume" in r.data
    assert r.headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert not any(d["cid"] == "cid-nuovo" for d in vc.get(rec["id"])["devices"])
    r = client.post(f"/vc/{rec['resume_token']['value']}/resume")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/?vc={rec['id']}")
    assert any(d["cid"] == "cid-nuovo" and d["via"] == "resume" for d in vc.get(rec["id"])["devices"])
    assert client.get("/vc/nope/resume").status_code == 404
    r = client.get(f"/vc/{rec['manage_token']}/devices")
    assert r.status_code == 200 and b"cid-nuovo" not in r.data and b"Email link" in r.data
    for h in (r, client.get(f"/vc/{rec['resume_token']['value']}/resume")):
        assert "no-store" in h.headers.get("Cache-Control", "")
    r = client.post(f"/vc/{rec['manage_token']}/devices/revoke", data={"cid": "cid-nuovo"})
    assert r.status_code in (200, 302) and "no-store" in r.headers.get("Cache-Control", "")
    assert not any(d["cid"] == "cid-nuovo" for d in vc.get(rec["id"])["devices"])
    assert client.get(f"/vc/{rec['manage_token']}/delete").status_code == 200
    r = client.post(f"/vc/{rec['manage_token']}/delete")
    assert r.status_code == 200 and vc.get(rec["id"])["state"] == "deleted"
    assert not os.path.isdir(vc.voice_dir(rec["token"]))
    # dopo la cancellazione i link dell'email restano nella casella per
    # sempre: 410 Gone con la spiegazione, non un «Not Found» nudo.
    assert client.get(f"/vc/{rec['manage_token']}/devices").status_code == 410


def test_i_link_email_di_una_voce_cancellata_spiegano_perche(client, tmp_path):
    """Un link dell'email vive nella posta per sempre: quando la voce non c'e'
    piu' deve atterrare su una pagina col marchio che dice cos'e' successo e
    che fine hanno fatto i soldi, non sull'errore nudo del server."""
    rec = _paid(tmp_path)
    tok, resume = rec["manage_token"], rec["resume_token"]["value"]
    client.post(f"/vc/{tok}/delete")
    for url in (f"/vc/{tok}/devices", f"/vc/{tok}/delete", f"/vc/{resume}/resume"):
        r = client.get(url, headers={"Accept-Language": "it"})
        corpo = r.data.decode("utf-8")
        assert r.status_code == 410, url
        assert "non &#232; pi&#249; disponibile" in corpo or "non è più disponibile" in corpo
        assert "<svg" in corpo and 'class="brand" href="/"' in corpo
        assert "voucher" in corpo and "audiolibri" in corpo.lower()
    # anche la revoca (POST) non deve finire su una pagina d'errore nuda
    r = client.post(f"/vc/{tok}/devices/revoke", data={"key": "x"})
    assert r.status_code == 410 and b"<svg" in r.data
    # token mai esistito: resta 404 (puo' essere un indirizzo copiato a meta')
    # ma con la stessa pagina, non col «Not Found» del server.
    r = client.get("/vc/nope/devices", headers={"Accept-Language": "it"})
    assert r.status_code == 404 and b"<svg" in r.data and "non apre" in r.data.decode("utf-8")


def test_le_pagine_dei_link_email_seguono_la_lingua_del_browser(client, tmp_path):
    """Chi arriva da un link dell'email non passa dal sito e non ha nessun
    modo di cambiare lingua: la pagina segue l'Accept-Language e ripiega
    sull'inglese, col marchio in alto per dire da dove arriva."""
    rec = _paid(tmp_path)
    tok = rec["manage_token"]
    r = client.get(f"/vc/{tok}/delete", headers={"Accept-Language": "it-IT,it;q=0.9"})
    corpo = r.data.decode("utf-8")
    assert r.status_code == 200
    assert 'lang="it"' in corpo and "Cancella il tuo campione vocale" in corpo
    assert "Audiobook Maker" in corpo and "<svg" in corpo and 'class="brand" href="/"' in corpo
    # la lingua dipende dall'header: senza Vary una cache la congelerebbe
    assert "Accept-Language" in r.headers.get("Vary", "")
    r = client.get(f"/vc/{tok}/delete", headers={"Accept-Language": "ja"})
    assert 'lang="en"' in r.data.decode("utf-8") and b"Delete your voice sample" in r.data
    # ?lang= non conta piu': decide solo il browser
    r = client.get(f"/vc/{tok}/delete?lang=de", headers={"Accept-Language": "it"})
    assert 'lang="it"' in r.data.decode("utf-8")
    r = client.get(f"/vc/{tok}/delete", headers={"Accept-Language": "de-DE"})
    assert 'lang="de"' in r.data.decode("utf-8") and "Sprachprobe l" in r.data.decode("utf-8")
    r = client.get(f"/vc/{rec['resume_token']['value']}/resume", headers={"Accept-Language": "fr"})
    assert "Reprendre" in r.data.decode("utf-8")
    r = client.get(f"/vc/{tok}/devices", headers={"Accept-Language": "it"})
    corpo = r.data.decode("utf-8")
    # «creator» e' un nome interno: a chi legge si dice da dove e' entrato
    assert "Dispositivo" in corpo and "Creazione" in corpo and "creator" not in corpo
    assert f'href="/vc/{tok}/delete"' in corpo
    # cancellazione: bottone (non link nudo) in basso a destra; revoca sulla
    # riga del nome del dispositivo, a destra; senza account nessuna «X»
    assert f'<div class="actions"><a class="btn danger end" href="/vc/{tok}/delete">Cancella questa voce</a></div>' in corpo
    riga = corpo.split('<div class="dev-head"')[1].split("</li>")[0]
    assert 'class="dev-revoke"' in riga.split("</div>")[0] and ">Revoca</button></form></div>" in riga
    assert "/account?tab=voices" not in corpo and '<div class="topbar">' not in corpo
    # «Annulla cancellazione» e' la scelta predefinita e torna alla gestione
    corpo = client.get(f"/vc/{tok}/delete", headers={"Accept-Language": "it"}).data.decode("utf-8")
    assert "Annulla cancellazione" in corpo and "autofocus" in corpo
    assert corpo.index("Annulla cancellazione") < corpo.index('class="danger"')
    assert f'action="/vc/{tok}/devices"' in corpo
    r = client.post(f"/vc/{tok}/delete", headers={"Accept-Language": "it"})
    assert "Voce cancellata" in r.data.decode("utf-8")


def test_le_traduzioni_delle_pagine_vc_coprono_tutte_le_lingue():
    percorso = os.path.join(os.path.dirname(__file__), "..", "i18n", "voice_clone_pages.json")
    with io.open(percorso, encoding="utf-8") as f:
        dati = json.load(f)
    assert set(dati) == {"it", "en", "fr", "es", "de", "zh", "hi"}
    atteso = set(dati["en"])
    # il ripiego cablato tiene in piedi le pagine se il file non si carica
    assert atteso >= set(audiobook_app._VC_PAGES_FALLBACK)
    for lang, voci in dati.items():
        assert set(voci) == atteso, lang
        assert all(str(v).strip() for v in voci.values()), lang


def test_resume_limita_i_dispositivi_diversi(client, tmp_path, monkeypatch):
    """I4: oltre RESUME_DEVICES_MAX dispositivi diversi autorizzati via
    resume, il link risponde 409 invece di continuare ad aggiungerne."""
    monkeypatch.setattr(audiobook_app, "RESUME_DEVICES_MAX", 2)
    rec = _paid(tmp_path)
    token = rec["resume_token"]["value"]
    _cid(client, "cid-a")
    assert client.post(f"/vc/{token}/resume").status_code == 302
    _cid(client, "cid-b")
    assert client.post(f"/vc/{token}/resume").status_code == 302
    _cid(client, "cid-c")
    r = client.post(f"/vc/{token}/resume")
    assert r.status_code == 409
    assert not any(d["cid"] == "cid-c" for d in vc.get(rec["id"])["devices"])


def test_voice_code_non_trapela_a_dispositivi_non_proprietari(client, tmp_path, ambiente):
    """Fix round 1 (CRITICAL): voice_code va restituito solo da commit() e da
    mine() al proprietario. progress/approve/reject (via _vc_view) non lo
    devono mai includere, nemmeno al proprietario stesso."""
    import re
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready"):
        vc.transition(rec["id"], s)
    _cid(client, "cid-due")
    r = client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"], **RICHIESTA})
    assert r.status_code == 200 and r.get_json()["status"] == "pending"
    codice = re.search(r"\b(\d{6})\b", ambiente[-1][2]).group(1)
    r = client.post("/api/voice_clone/confirm", json={"voice_code": rec["voice_code"], "confirm_code": codice})
    assert r.status_code == 200 and "voice_code" not in r.get_json()["voice"]
    r = client.get(f"/api/voice_clone/progress/{rec['id']}")
    payload = json.loads(r.get_data(as_text=True).strip().split("data: ")[-1])
    assert "voice_code" not in payload
    r = client.post(f"/api/voice_clone/{rec['id']}/reject", json={"reason": "Non mi somiglia per niente"})
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
    r = client.post("/api/voice_clone/claim", json={"voice_code": "ZZZZ-ZZZZ-ZZZZ", **RICHIESTA})
    assert r.status_code == 404 and r.get_json()["error_code"] == "code_unknown"


def test_claim_locked_dopo_troppi_tentativi_di_conferma(client, tmp_path, ambiente):
    """Fix round 1 (IMPORTANT): il solo ValueError residuo di claim() e' il
    lock (423 code_locked), esaurito qui per la via reale (5 conferme
    sbagliate di fila bloccano il cid, non il codice sconosciuto)."""
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready"):
        vc.transition(rec["id"], s)
    _cid(client, "cid-due")
    r = client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"], **RICHIESTA})
    assert r.status_code == 200 and r.get_json()["status"] == "pending"
    r = None
    for _ in range(vc.CONFIRM_MAX_TRIES):
        r = client.post("/api/voice_clone/confirm",
                        json={"voice_code": rec["voice_code"], "confirm_code": "000000"})
    assert r.status_code == 423 and r.get_json()["error_code"] == "code_locked"
    r = client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"], **RICHIESTA})
    assert r.status_code == 423 and r.get_json()["error_code"] == "code_locked"


def test_sample_troppo_grande(client, monkeypatch):
    """T6b: file salvato ma oltre max_upload_mb -> 413 too_large, nessuna
    bozza creata."""
    monkeypatch.setattr(vc, "max_upload_mb", lambda: 0)
    r = client.post("/api/voice_clone/sample", data={
        "file": (io.BytesIO(b"webm-bytes"), "rec.webm"), "lang": "it", "locale": "it-IT",
        "gender": "f", "prompt_version": "x"}, content_type="multipart/form-data")
    assert r.status_code == 413
    assert r.get_json()["error_code"] == "too_large"
    assert not [f for f in os.listdir(audiobook_app.UPLOAD_DIR) if f.startswith("vc_")]


def test_sample_asr_non_disponibile(client, monkeypatch):
    """T6b: verifica ASR abilitata ma il modello non risponde
    (voice_clone_audio.AsrUnavailable) -> 503 asr_unavailable, nessuna bozza
    creata."""
    monkeypatch.setenv("ABM_VOICE_CLONE_ASR", "1")

    def prepara(src, dst, **kw):
        open(dst, "wb").write(b"RIFF-wav")
        return vca.Metrics(**{f: 0.0 for f in vca.Metrics.__dataclass_fields__})
    monkeypatch.setattr(vca, "prepare_sample", prepara)

    def esplode(wav_path, language, expected_text, **kw):
        raise vca.AsrUnavailable("modello whisper non caricato")
    monkeypatch.setattr(vca, "check_transcript", esplode)
    r = client.post("/api/voice_clone/sample", data={
        "file": (io.BytesIO(b"webm-bytes"), "rec.webm"), "lang": "it", "locale": "it-IT",
        "gender": "f", "prompt_version": "x"}, content_type="multipart/form-data")
    assert r.status_code == 503
    assert r.get_json()["error_code"] == "asr_unavailable"
    assert not [f for f in os.listdir(audiobook_app.UPLOAD_DIR) if f.startswith("vc_")]


def test_approve_voce_sparita(client, tmp_path):
    """T6b: approve su una voce diventata terminale (es. rimborsata da un
    altro dispositivo) tra il caricamento della pagina e il click -> 410
    voice_gone, non 404/500."""
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready"):
        vc.transition(rec["id"], s)
    vc.transition(rec["id"], "refunded")
    r = client.post(f"/api/voice_clone/{rec['id']}/approve")
    assert r.status_code == 410 and r.get_json()["error_code"] == "voice_gone"


def test_la_rigenerazione_non_esiste_piu(client, tmp_path, ambiente):
    """La rigenerazione delle prove e' stata tolta: era lenta e poco utile.
    Chi restasse con una vecchia pagina aperta prende un 404/405, non una coda
    di sintesi avviata di nascosto."""
    rec = _paid(tmp_path)
    for st in ("demos_generating", "demos_ready"):
        vc.transition(rec["id"], st)
    r = client.post(f"/api/voice_clone/{rec['id']}/regenerate", json={"extra_id": "x"})
    assert r.status_code in (404, 405)
    assert "regen_max" not in client.get("/api/voice_clone/config").get_json()


def test_confirm_scaduto_via_api(client, tmp_path, monkeypatch, ambiente):
    """T6b: il codice di conferma scade (CONFIRM_TTL_SEC) prima che il nuovo
    dispositivo lo usi -> 410 confirm_expired (distinto da confirm_wrong)."""
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready", "ready"):
        vc.transition(rec["id"], s)
    ora = [1_000_000.0]
    monkeypatch.setattr(vc, "_now", lambda now=None: int(now if now is not None else ora[0]))
    _cid(client, "cid-due")
    r = client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"], **RICHIESTA})
    assert r.status_code == 200 and r.get_json()["status"] == "pending"
    ora[0] += vc.CONFIRM_TTL_SEC + 1
    r = client.post("/api/voice_clone/confirm",
                    json={"voice_code": rec["voice_code"], "confirm_code": "000000"})
    assert r.status_code == 410 and r.get_json()["error_code"] == "confirm_expired"


def test_il_nome_della_voce_arriva_col_campione_e_si_vede_in_mine(client, monkeypatch, tmp_path):
    def prepara(src, dst, **kw):
        open(dst, "wb").write(b"RIFF-wav")
        return vca.Metrics(**{f: 0.0 for f in vca.Metrics.__dataclass_fields__})
    monkeypatch.setattr(vca, "prepare_sample", prepara)
    r = client.post("/api/voice_clone/sample", data={
        "file": (io.BytesIO(b"webm-bytes"), "rec.webm"), "lang": "it", "locale": "it-IT",
        "gender": "f", "name": "  Voce\u202e  di\tNonna  "}, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    cid_ = r.get_json()["clone_id"]
    assert vc.get(cid_)["name"] == "Voce di Nonna"
    mine = client.get("/api/voice_clone/mine").get_json()["voices"]
    assert mine[0]["name"] == "Voce di Nonna"


def test_nome_facoltativo_e_troncato():
    assert vc.normalize_name(None) == ""
    assert vc.normalize_name("   ") == ""
    assert len(vc.normalize_name("x" * 100)) == vc.NAME_MAX
    # ZWJ resta: serve alle scritture indiane e alle emoji composte
    assert vc.normalize_name("\u0915\u094d\u200d\u0937") == "\u0915\u094d\u200d\u0937"


def test_rinomina_solo_proprietario_e_voce_viva(client, tmp_path, ambiente):
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready", "ready"):
        vc.transition(rec["id"], s)
    r = client.post(f"/api/voice_clone/{rec['id']}/rename", json={"name": " Narratore "})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "name": "Narratore"}
    assert vc.get(rec["id"])["name"] == "Narratore"
    # un nome vuoto toglie il nome: la combo torna all'etichetta generica
    r = client.post(f"/api/voice_clone/{rec['id']}/rename", json={"name": ""})
    assert r.status_code == 200 and vc.get(rec["id"])["name"] == ""
    # un dispositivo autorizzato ma non creatore non puo' rinominare
    vc.store().update(rec["id"], {"devices": rec["devices"] + [{"cid": "cid-due", "via": "confirm"}]})
    _cid(client, "cid-due")
    r = client.post(f"/api/voice_clone/{rec['id']}/rename", json={"name": "Mia"})
    assert r.status_code == 409 and r.get_json()["error_code"] == "bad_state"
    _cid(client, "cid-uno")
    assert client.post("/api/voice_clone/vc_000000000000/rename", json={"name": "x"}).status_code == 404
    vc.transition(rec["id"], "deleted")
    r = client.post(f"/api/voice_clone/{rec['id']}/rename", json={"name": "Tardi"})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# nome dei dispositivi e revoca singola dalla pagina di gestione
# ---------------------------------------------------------------------------
UA_CHROME_WIN = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                 "Chrome/128.0.0.0 Safari/537.36")


def test_config_propone_il_nome_del_dispositivo(client):
    r = client.get("/api/voice_clone/config", headers={"User-Agent": UA_CHROME_WIN})
    assert r.get_json()["device_name_guess"] == "Chrome · Windows"


def test_sample_salva_il_nome_del_dispositivo(client, monkeypatch):
    def prepara(src, dst, **kw):
        open(dst, "wb").write(b"RIFF-wav")
        return vca.Metrics(**{f: 0.0 for f in vca.Metrics.__dataclass_fields__})
    monkeypatch.setattr(vca, "prepare_sample", prepara)
    dati = {"lang": "it", "locale": "it-IT", "gender": "f"}
    r = client.post("/api/voice_clone/sample", content_type="multipart/form-data",
                    data=dict(dati, file=(io.BytesIO(b"w"), "rec.webm"), device_name="PC di casa"))
    assert vc.get(r.get_json()["clone_id"])["devices"][0]["name"] == "PC di casa"
    # campo vuoto: vale il nome proposto dal browser, mai un dispositivo anonimo
    r = client.post("/api/voice_clone/sample", content_type="multipart/form-data",
                    headers={"User-Agent": UA_CHROME_WIN},
                    data=dict(dati, file=(io.BytesIO(b"w"), "rec.webm")))
    assert vc.get(r.get_json()["clone_id"])["devices"][0]["name"] == "Chrome · Windows"


def test_confirm_salva_il_nome_e_lo_scrive_nellemail(client, tmp_path, ambiente):
    import re
    rec = _paid(tmp_path)
    _cid(client, "cid-due")
    r = client.post("/api/voice_clone/claim", json={
        "voice_code": rec["voice_code"], "device_name": "Telefono <b>",
        "identity": "Sono <i>Anna</i>, tua sorella"})
    assert r.status_code == 200 and r.get_json()["status"] == "pending"
    # l'email con il codice dice al proprietario chi chiede e da quale dispositivo
    to, _, corpo = ambiente[-1]
    assert to == "u@example.com"
    assert "Telefono &lt;b&gt;" in corpo and "Sono &lt;i&gt;Anna&lt;/i&gt;, tua sorella" in corpo
    assert "<i>Anna" not in corpo and "24" in corpo
    codice = re.search(r"\b(\d{6})\b", corpo).group(1)
    r = client.post("/api/voice_clone/confirm", json={
        "voice_code": rec["voice_code"], "confirm_code": codice, "device_name": "Altro"})
    assert r.status_code == 200
    d = vc.device_of(vc.get(rec["id"]), "cid-due")
    assert d["name"] == "Telefono <b>" and d["identity"] == "Sono <i>Anna</i>, tua sorella"
    corpo = ambiente[-1][2]
    assert "Telefono &lt;b&gt;" in corpo and "Telefono <b>" not in corpo


@pytest.mark.parametrize("campi, errore", [
    ({"identity": "Sono Anna, tua sorella"}, "device_name_required"),
    ({"device_name": "Telefono", "identity": "Anna"}, "identity_required"),
])
def test_claim_senza_nome_o_presentazione_non_manda_email(client, tmp_path, ambiente, campi, errore):
    rec = _paid(tmp_path)
    _cid(client, "cid-due")
    prima = len(ambiente)
    r = client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"], **campi})
    assert r.status_code == 400 and r.get_json()["error_code"] == errore
    assert r.get_json()["min_chars"] == vc.IDENTITY_MIN
    assert len(ambiente) == prima and vc.pending_of(vc.get(rec["id"]), "cid-due") is None


def test_resume_chiede_il_nome_e_lo_salva(client, tmp_path):
    rec = _paid(tmp_path)
    token = rec["resume_token"]["value"]
    _cid(client, "cid-r")
    r = client.get(f"/vc/{token}/resume", headers={"User-Agent": UA_CHROME_WIN})
    corpo = r.data.decode("utf-8")
    assert 'name="device_name"' in corpo and 'value="Chrome · Windows"' in corpo
    r = client.post(f"/vc/{token}/resume", data={"device_name": "Tablet cucina"})
    assert r.status_code == 302
    assert vc.device_of(vc.get(rec["id"]), "cid-r")["name"] == "Tablet cucina"


def test_pagina_voce_usa_stile_e_tema_dell_app(client, tmp_path):
    # Stessa resa dell'area personale (page_brand): tavolozza della SPA,
    # bottoni bianchi col testo accento, tema letto da localStorage `abm_th`
    # PRIMA del CSS. Nessun colore fisso della vecchia versione.
    rec = _paid(tmp_path)
    corpo = client.get(f"/vc/{rec['manage_token']}/devices").data.decode("utf-8")
    assert corpo.index("localStorage.getItem('abm_th')") < corpo.index("<style>")
    assert "[data-theme=dark]{" in corpo and "--ac:#c47a2a" in corpo
    assert "background:var(--srf);color:var(--ac)" in corpo
    assert "#f6f3ee" not in corpo and "color:#222" not in corpo and "#c29a6c;--acc-d" not in corpo


def test_pagina_voce_torna_all_area_personale_solo_al_proprietario(client, tmp_path, monkeypatch):
    rec = _pronta(tmp_path)
    tok = rec["manage_token"]
    # account con l'email della voce: «X» in testata verso l'area personale
    monkeypatch.setattr(audiobook_app, "_current_account", lambda: {"id": 1, "email": "U@example.com "})
    corpo = client.get(f"/vc/{tok}/devices", headers={"Accept-Language": "it"}).data.decode("utf-8")
    assert '<div class="topbar"><h1>' in corpo
    x = corpo.split('<div class="tools">')[1].split("</div>")[0]
    assert 'class="btn icon-x" href="/account?tab=voices"' in x and 'aria-label="Torna all&#x27;area personale"' in x
    # account di un altro: niente
    monkeypatch.setattr(audiobook_app, "_current_account", lambda: {"id": 2, "email": "altro@example.com"})
    corpo = client.get(f"/vc/{tok}/devices", headers={"Accept-Language": "it"}).data.decode("utf-8")
    assert "/account?tab=voices" not in corpo


def test_pagina_dispositivi_mostra_i_nomi_e_rinomina(client, tmp_path):
    rec = _paid(tmp_path)
    tok = rec["manage_token"]
    vc.add_resume_device(rec["id"], "cid-r", "Tablet <cucina>")
    vc.store().update(rec["id"], {"devices": [dict(d, identity="Sono <b>Rita</b>") if d["cid"] == "cid-r" else d
                                              for d in vc.get(rec["id"])["devices"]]})
    vc.store().update(rec["id"], {"devices": [dict(d, name="") if d["cid"] == "cid-uno" else d
                                              for d in vc.get(rec["id"])["devices"]]})
    chiave = audiobook_app._vc_device_key("cid-uno")
    r = client.get(f"/vc/{tok}/devices", headers={"Accept-Language": "it"})
    corpo = r.data.decode("utf-8")
    assert "Tablet &lt;cucina&gt;" in corpo and "<cucina>" not in corpo
    # la presentazione di chi e' entrato con il codice resta leggibile
    assert "Presentazione: «Sono &lt;b&gt;Rita&lt;/b&gt;»" in corpo
    assert corpo.count("Presentazione:") == 1
    # un dispositivo registrato prima dei nomi resta riconoscibile dalla chiave
    assert chiave in corpo
    # chi apre la pagina riconosce il dispositivo che sta usando
    assert "questo dispositivo" in corpo.lower()
    assert corpo.count("/devices/revoke") == 2          # anche il creatore
    r = client.post(f"/vc/{tok}/devices/rename",
                    data={"key": audiobook_app._vc_device_key("cid-r"), "name": "Tablet salotto"})
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/vc/{tok}/devices")
    assert vc.device_of(vc.get(rec["id"]), "cid-r")["name"] == "Tablet salotto"


def test_revoca_del_creatore_chiede_conferma(client, tmp_path):
    rec = _paid(tmp_path)
    tok = rec["manage_token"]
    chiave = audiobook_app._vc_device_key("cid-uno")
    r = client.post(f"/vc/{tok}/devices/revoke", data={"key": chiave},
                    headers={"Accept-Language": "it"})
    corpo = r.data.decode("utf-8")
    assert r.status_code == 200 and 'name="confirm"' in corpo
    assert vc.device_of(vc.get(rec["id"]), "cid-uno") is not None       # non ancora
    r = client.post(f"/vc/{tok}/devices/revoke", data={"key": chiave, "confirm": "1"})
    assert r.status_code == 302
    got = vc.get(rec["id"])
    assert vc.device_of(got, "cid-uno") is None and got["state"] != "deleted"
    assert not vc.is_owner(got, "cid-uno")


def test_claim_ripetuto_dallo_stesso_dispositivo_non_rimanda_email(client, tmp_path, ambiente):
    rec = _paid(tmp_path)
    _cid(client, "cid-due")
    r = client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"], **RICHIESTA})
    assert r.status_code == 200 and r.get_json()["status"] == "pending"
    inviate = len(ambiente)
    r = client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"], **RICHIESTA})
    assert r.status_code == 200 and r.get_json() == {"status": "pending", "already_sent": True}
    assert len(ambiente) == inviate


def test_claim_da_due_dispositivi_ognuno_con_la_sua_email_e_il_suo_codice(client, tmp_path, ambiente):
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready", "ready"):
        vc.transition(rec["id"], s)
    import re
    codici = {}
    for cid, nome in (("cid-due", "PC di Anna"), ("cid-tre", "Tablet di Bruno")):
        _cid(client, cid)
        r = client.post("/api/voice_clone/claim", json={
            "voice_code": rec["voice_code"], "device_name": nome, "identity": "Sono io, ti scrivo ora"})
        assert r.status_code == 200 and r.get_json()["status"] == "pending"
        corpo = ambiente[-1][2]
        assert nome in corpo
        codici[cid] = re.search(r"\b(\d{6})\b", corpo).group(1)
    for cid in ("cid-tre", "cid-due"):
        _cid(client, cid)
        r = client.post("/api/voice_clone/confirm", json={"voice_code": rec["voice_code"],
                                                          "confirm_code": codici[cid]})
        assert r.status_code == 200, (cid, r.get_json())
    assert {"cid-due", "cid-tre"} <= {d["cid"] for d in vc.get(rec["id"])["devices"]}


def test_claim_oltre_le_richieste_parallele_ammesse(client, tmp_path, ambiente, monkeypatch):
    rec = _paid(tmp_path)
    monkeypatch.setattr(vc, "CONFIRM_MAX_PENDING", 1)
    _cid(client, "cid-due")
    assert client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"], **RICHIESTA}).status_code == 200
    _cid(client, "cid-tre")
    prima = len(ambiente)
    r = client.post("/api/voice_clone/claim", json={"voice_code": rec["voice_code"], **RICHIESTA})
    assert r.status_code == 429 and r.get_json()["error_code"] == "claim_busy"
    assert len(ambiente) == prima


def _thread_sincrono(monkeypatch):
    """La traduzione del motivo parte in un thread: qui gira subito."""
    class T:
        def __init__(self, target=None, **kw):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(audiobook_app.threading, "Thread", T)


def test_rifiuto_delle_demo_pronte_chiede_il_motivo(client, tmp_path, monkeypatch):
    import community_translator
    _thread_sincrono(monkeypatch)
    chiamate = []
    monkeypatch.setattr(community_translator, "translate_to_italian",
                        lambda t, **kw: chiamate.append(t) or {"source_lang": "en", "it": "Non mi somiglia"})
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready"):
        vc.transition(rec["id"], s)
    for corpo in (None, {}, {"reason": "   no  "}):
        r = client.post(f"/api/voice_clone/{rec['id']}/reject", json=corpo)
        assert r.status_code == 400, corpo
        d = r.get_json()
        assert d["error_code"] == "reject_reason_required" and d["min_chars"] == vc.REJECT_NOTE_MIN
    assert vc.get(rec["id"])["state"] == "demos_ready"
    # un altro dispositivo non scopre lo stato: 403, non 400
    _cid(client, "cid-estraneo")
    assert client.post(f"/api/voice_clone/{rec['id']}/reject", json={}).status_code == 403
    _cid(client, "cid-uno")
    r = client.post(f"/api/voice_clone/{rec['id']}/reject",
                    json={"reason": "It doesn't\n sound\x07 like me at all"})
    assert r.status_code == 200 and r.get_json()["state"] == "refunded"
    assert "reject_note" not in r.get_json()
    note = vc.get(rec["id"])["reject_note"]
    assert note["text"] == "It doesn't sound like me at all" and note["at"]
    assert chiamate == ["It doesn't sound like me at all"]
    assert note["it"] == "Non mi somiglia" and note["lang"] == "en"
    assert "reject_note" not in vc.public_view(vc.get(rec["id"]))


def test_rifiuto_dopo_demo_fallite_non_chiede_il_motivo(client, tmp_path, monkeypatch):
    import community_translator
    monkeypatch.setattr(community_translator, "translate_to_italian",
                        lambda t, **kw: pytest.fail("niente da tradurre"))
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demo_failed"):
        vc.transition(rec["id"], s)
    r = client.post(f"/api/voice_clone/{rec['id']}/reject", json={})
    assert r.status_code == 200 and r.get_json()["state"] == "refunded"
    assert "reject_note" not in vc.get(rec["id"])


def test_audit_admin_ritenta_la_traduzione_mancante(client, tmp_path, monkeypatch):
    import community_translator
    _thread_sincrono(monkeypatch)
    monkeypatch.setattr(community_translator, "translate_to_italian", lambda t, **kw: None)
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready"):
        vc.transition(rec["id"], s)
    r = client.post(f"/api/voice_clone/{rec['id']}/reject", json={"reason": "La voce è troppo robotica"})
    assert r.status_code == 200
    assert "it" not in vc.get(rec["id"])["reject_note"]
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-admin")
    monkeypatch.setattr(community_translator, "translate_to_italian",
                        lambda t, **kw: {"source_lang": "it", "it": t})
    r = client.get("/admin/api/voice_clone_audit?state=all", headers={"X-Admin-Token": "tok-admin"})
    assert r.status_code == 200
    riga = next(x for x in r.get_json()["records"] if x["id"] == rec["id"])
    assert riga["reject_note_original"] == "La voce è troppo robotica"
    assert vc.get(rec["id"])["reject_note"]["it"] == "La voce è troppo robotica"


# ---------------------------------------------------------------------------
# velocita' della voce: pannello e pagina di gestione
# ---------------------------------------------------------------------------
def _pronta(tmp_path):
    rec = _paid(tmp_path)
    for s in ("demos_generating", "demos_ready", "ready"):
        vc.transition(rec["id"], s)
    return vc.get(rec["id"])


def test_api_velocita_solo_proprietario(client, tmp_path):
    rec = _pronta(tmp_path)
    r = client.post(f"/api/voice_clone/{rec['id']}/speed", json={"speed": "1,1"})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "speed": 1.1}
    r = client.post(f"/api/voice_clone/{rec['id']}/speed", json={"speed": 3})
    assert r.status_code == 400 and r.get_json()["error_code"] == "bad_speed"
    assert client.get("/api/voice_clone/mine").get_json()["voices"][0]["speed"] == 1.1
    vc.store().update(rec["id"], {"devices": rec["devices"] + [{"cid": "cid-due", "via": "confirm"}]})
    _cid(client, "cid-due")
    r = client.post(f"/api/voice_clone/{rec['id']}/speed", json={"speed": 0.9})
    assert r.status_code == 409 and r.get_json()["error_code"] == "bad_state"
    assert vc.speed_of(vc.get(rec["id"])) == 1.1


def test_pagina_gestione_imposta_la_velocita(client, tmp_path):
    rec = _pronta(tmp_path)
    tok = rec["manage_token"]
    corpo = client.get(f"/vc/{tok}/devices", headers={"Accept-Language": "it"}).data.decode("utf-8")
    assert 'name="speed"' in corpo and '<option value="1.00" selected>' in corpo
    assert f"/vc/{tok}/demo.wav" in corpo
    r = client.post(f"/vc/{tok}/speed", data={"speed": "1.10"})
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/vc/{tok}/devices?saved=speed")
    assert vc.speed_of(vc.get(rec["id"])) == 1.1
    corpo = client.get(r.headers["Location"]).data.decode("utf-8")
    assert '<option value="1.10" selected>' in corpo
    # valore fuori scala: nessun salvataggio, nessun badge
    r = client.post(f"/vc/{tok}/speed", data={"speed": "5"})
    assert r.status_code == 302 and "saved=speed" not in r.headers["Location"]
    assert vc.speed_of(vc.get(rec["id"])) == 1.1


def test_prova_della_pagina_di_gestione(client, tmp_path):
    rec = _pronta(tmp_path)
    tok = rec["manage_token"]
    assert client.get(f"/vc/{tok}/demo.wav").status_code == 404      # file assente
    with open(os.path.join(vc.voice_dir(rec["token"]), "demo_common.wav"), "wb") as f:
        f.write(b"RIFF-prova")
    client.set_cookie(audiobook_app._CLIENT_COOKIE_NAME, "cid-estraneo")
    r = client.get(f"/vc/{tok}/demo.wav")
    assert r.status_code == 200 and r.data == b"RIFF-prova"
    assert client.get("/vc/nope/demo.wav").status_code == 404
    vc.transition(rec["id"], "deleted")
    assert client.get(f"/vc/{tok}/demo.wav").status_code == 404
    assert client.post(f"/vc/{tok}/speed", data={"speed": "1.2"}).status_code in (302, 410)
    assert vc.speed_of(vc.get(rec["id"])) == 1.0
