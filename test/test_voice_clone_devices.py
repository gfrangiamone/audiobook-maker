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


def _claim(*a, **kw):
    """Una richiesta completa: nome del dispositivo e presentazione."""
    kw.setdefault("device_name", "Telefono di Anna")
    kw.setdefault("identity", "Sono Anna, tua sorella")
    return vc.claim(*a, **kw)


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
    esito, got, code = _claim(rec["voice_code"], "cid-owner")
    assert esito == "ok" and got["id"] == rec["id"] and code is None


def test_claim_da_cid_nuovo_crea_il_codice_hashato(tmp_path):
    rec = _pronta(tmp_path)
    esito, got, code = _claim(rec["voice_code"].lower(), "cid-nuovo", now=1000)
    assert esito == "pending" and len(code) == 6 and code.isdigit()
    pc = vc.get(rec["id"])["pending_confirm"]
    assert pc["cid"] == "cid-nuovo" and pc["tries"] == 0
    assert pc["expires_at"] == 1000 + vc.CONFIRM_TTL_SEC
    assert pc["code_hash"] == hashlib.sha256(code.encode()).hexdigest()
    assert code not in str(vc.get(rec["id"]))


def test_claim_sconosciuto_o_terminale(tmp_path):
    with pytest.raises(vc.VoiceGone):
        _claim("AAAA-BBBB-CCCC", "cid-x")
    rec = _pronta(tmp_path)
    vc.transition(rec["id"], "deleted")
    with pytest.raises(vc.VoiceGone):
        _claim(rec["voice_code"], "cid-x")


def test_una_nuova_richiesta_sostituisce_la_precedente(tmp_path):
    rec = _pronta(tmp_path)
    _, _, c1 = _claim(rec["voice_code"], "cid-a", now=1000)
    _, _, c2 = _claim(rec["voice_code"], "cid-b", now=1001)
    assert vc.confirm(rec["voice_code"], "cid-a", c1, now=1002) == "none"
    assert vc.confirm(rec["voice_code"], "cid-b", c2, now=1002) == "ok"


def test_confirm_ok_aggiunge_il_dispositivo(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = _claim(rec["voice_code"], "cid-nuovo", now=1000)
    assert vc.confirm(rec["voice_code"], "cid-nuovo", code, now=1100) == "ok"
    got = vc.get(rec["id"])
    assert got["pending_confirm"] is None
    assert {"cid": "cid-nuovo", "added_at": 1100, "via": "code", "name": "Telefono di Anna",
            "identity": "Sono Anna, tua sorella"} in got["devices"]
    assert vc.authorized(vc.voice_id_of(got), "cid-nuovo")
    assert _claim(rec["voice_code"], "cid-nuovo")[0] == "ok"


def test_confirm_scaduto(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = _claim(rec["voice_code"], "cid-nuovo", now=1000)
    assert vc.confirm(rec["voice_code"], "cid-nuovo", code, now=1000 + vc.CONFIRM_TTL_SEC + 1) == "expired"
    assert vc.get(rec["id"])["pending_confirm"] is None


def test_cinque_tentativi_poi_blocco(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = _claim(rec["voice_code"], "cid-nuovo", now=1000)
    for _ in range(4):
        assert vc.confirm(rec["voice_code"], "cid-nuovo", "000000", now=1001) == "wrong"
    assert vc.confirm(rec["voice_code"], "cid-nuovo", "000000", now=1001) == "locked"
    got = vc.get(rec["id"])
    assert got["pending_confirm"] is None
    assert got["confirm_locks"]["cid-nuovo"] == 1001 + vc.CONFIRM_LOCK_SEC
    # il codice giusto ormai non vale, e un nuovo claim e' bloccato
    assert vc.confirm(rec["voice_code"], "cid-nuovo", code, now=1002) == "none"
    with pytest.raises(ValueError, match="locked"):
        _claim(rec["voice_code"], "cid-nuovo", now=1002)
    assert _claim(rec["voice_code"], "cid-nuovo", now=1001 + vc.CONFIRM_LOCK_SEC + 1)[0] == "pending"


def test_forget_e_revoke(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = _claim(rec["voice_code"], "cid-b", now=1000)
    vc.confirm(rec["voice_code"], "cid-b", code, now=1001)
    assert vc.forget(rec["id"], "cid-b") is True
    assert vc.forget(rec["id"], "cid-b") is False
    assert not vc.authorized(vc.voice_id_of(rec), "cid-b")
    assert vc.revoke_device(rec["manage_token"], "cid-owner") is True
    assert vc.revoke_device("token-sbagliato", "cid-owner") is False
    assert vc.get(rec["id"])["devices"] == []
    assert vc.get(rec["id"])["state"] == "ready"        # la voce sopravvive


def test_is_owner_solo_il_dispositivo_creatore(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = _claim(rec["voice_code"], "cid-b", now=1000)
    vc.confirm(rec["voice_code"], "cid-b", code, now=1001)
    got = vc.get(rec["id"])
    assert vc.is_owner(got, "cid-owner") is True
    assert vc.is_owner(got, "cid-b") is False
    assert vc.is_owner(got, "cid-sconosciuto") is False


def test_forget_rifiuta_il_dispositivo_proprietario(tmp_path):
    """m1: il creatore non puo' essere dimenticato (perderebbe per sempre il
    voice_code). Deve usare "Cancella" (delete_by_owner)."""
    rec = _pronta(tmp_path)
    with pytest.raises(vc.BadTransition):
        vc.forget(rec["id"], "cid-owner")
    assert vc.authorized(vc.voice_id_of(rec), "cid-owner")
    got = vc.get(rec["id"])
    assert any(d.get("cid") == "cid-owner" for d in got["devices"])


def test_confirm_locks_scaduti_vengono_potati(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = _claim(rec["voice_code"], "cid-nuovo", now=1000)
    for _ in range(5):
        vc.confirm(rec["voice_code"], "cid-nuovo", "000000", now=1001)
    assert vc.get(rec["id"])["confirm_locks"]["cid-nuovo"] == 1001 + vc.CONFIRM_LOCK_SEC

    dopo_scadenza = 1001 + vc.CONFIRM_LOCK_SEC + 1
    # claim (lettura) pota il lock scaduto per un cid diverso
    _claim(rec["voice_code"], "cid-altro", now=dopo_scadenza)
    assert "cid-nuovo" not in (vc.get(rec["id"])["confirm_locks"] or {})


def test_confirm_locks_scaduti_potati_alla_scrittura_di_un_nuovo_blocco(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code_a = _claim(rec["voice_code"], "cid-a", now=1000)
    for _ in range(5):
        vc.confirm(rec["voice_code"], "cid-a", "000000", now=1001)
    assert vc.get(rec["id"])["confirm_locks"]["cid-a"] == 1001 + vc.CONFIRM_LOCK_SEC

    dopo_scadenza = 1001 + vc.CONFIRM_LOCK_SEC + 1
    _, _, code_b = _claim(rec["voice_code"], "cid-b", now=dopo_scadenza)
    for _ in range(5):
        vc.confirm(rec["voice_code"], "cid-b", "000000", now=dopo_scadenza)
    locks = vc.get(rec["id"])["confirm_locks"]
    assert "cid-a" not in locks and locks["cid-b"] == dopo_scadenza + vc.CONFIRM_LOCK_SEC


def test_check_and_record_resend_finestra_24h(tmp_path):
    """I3: 3 invii passano nella finestra di 24h, il quarto no; dopo 24h dal
    primo la finestra scorre e un nuovo invio torna a passare."""
    rec = _pronta(tmp_path)
    t0 = 1_000_000
    for i in range(3):
        ok, retry = vc.check_and_record_resend(rec["id"], now=t0 + i)
        assert ok is True and retry is None
    ok, retry = vc.check_and_record_resend(rec["id"], now=t0 + 3)
    assert ok is False and retry > 0
    ok, retry = vc.check_and_record_resend(rec["id"], now=t0 + vc.RESEND_WINDOW_SEC + 1)
    assert ok is True and retry is None


def test_check_and_record_resend_voce_sparita(tmp_path):
    with pytest.raises(vc.VoiceGone):
        vc.check_and_record_resend("vc_nope")


def test_devices_view_mostra_solo_la_coda_del_cid(tmp_path):
    rec = _pronta(tmp_path, cid="abcd1234efgh")
    view = vc.devices_view(vc.get(rec["id"]))
    assert view == [{"cid_tail": "efgh", "added_at": rec["created_at"], "via": "creator"}]


# ---------------------------------------------------------------------------
# nome dei dispositivi: serve a riconoscerli nella pagina di gestione
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ua, atteso", [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/128.0.0.0 Safari/537.36", "Chrome · Windows"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0", "Edge · Windows"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
     "Version/17.5 Safari/605.1.15", "Safari · Mac"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
     "Version/17.5 Mobile/15E148 Safari/604.1", "Safari · iPhone"),
    ("Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
     "CriOS/128.0 Mobile/15E148 Safari/604.1", "Chrome · iPad"),
    ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/128.0.0.0 Mobile Safari/537.36", "Chrome · Android"),
    ("Mozilla/5.0 (X11; Linux x86_64; rv:129.0) Gecko/20100101 Firefox/129.0", "Firefox · Linux"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/128.0.0.0 Safari/537.36 OPR/113.0", "Opera · Windows"),
    ("curl/8.0", ""),
    ("", ""),
])
def test_nome_proposto_dallo_user_agent(ua, atteso):
    assert vc.device_name_from_ua(ua) == atteso


def test_normalize_device_name():
    assert vc.normalize_device_name("  PC\u0000 ufficio \u202e ") == "PC ufficio"
    assert len(vc.normalize_device_name("x" * 200)) == vc.DEVICE_NAME_MAX
    assert vc.normalize_device_name(None) == ""


def test_il_nome_del_dispositivo_si_salva_in_creazione_e_in_conferma(tmp_path):
    s = tmp_path / "s.wav"; s.write_bytes(b"RIFF")
    o = tmp_path / "o.webm"; o.write_bytes(b"webm")
    rec = vc.create_draft("cid-owner", lang="it", locale="it-IT", gender="m", prompt_text="frase",
                          sample_wav=str(s), original_path=str(o), original_ext="webm",
                          metrics={}, ui_lang="it", device_name=" PC di casa ")
    assert rec["devices"][0]["name"] == "PC di casa"
    _, _, code = _claim(rec["voice_code"], "cid-b", now=1000, device_name=" Telefono ")
    # alla conferma vale il nome della richiesta, quello letto dal proprietario
    assert vc.confirm(rec["voice_code"], "cid-b", code, now=1001, device_name="Altro") == "ok"
    assert vc.device_of(vc.get(rec["id"]), "cid-b")["name"] == "Telefono"


def test_confirm_di_una_richiesta_aperta_prima_dei_nomi_usa_il_nome_dato_in_conferma(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = _claim(rec["voice_code"], "cid-b", now=1000)
    pc = vc.get(rec["id"])["pending_confirm"]
    pc.pop("device_name"); pc.pop("identity")
    vc.store().update(rec["id"], {"pending_confirm": pc})
    assert vc.confirm(rec["voice_code"], "cid-b", code, now=1001, device_name="Telefono") == "ok"
    d = vc.device_of(vc.get(rec["id"]), "cid-b")
    assert d["name"] == "Telefono" and d["identity"] == ""


@pytest.mark.parametrize("campi, manca", [
    ({"device_name": ""}, "device_name"),
    ({"device_name": " \u200b\t "}, "device_name"),
    ({"identity": ""}, "identity"),
    ({"identity": "Sono  io\n"}, "identity"),
])
def test_claim_senza_nome_o_presentazione_non_parte(tmp_path, campi, manca):
    rec = _pronta(tmp_path)
    with pytest.raises(vc.ClaimIncomplete) as e:
        _claim(rec["voice_code"], "cid-nuovo", now=1000, **campi)
    assert e.value.field == manca
    assert vc.get(rec["id"])["pending_confirm"] is None


def test_claim_di_un_dispositivo_gia_autorizzato_non_chiede_nulla(tmp_path):
    rec = _pronta(tmp_path)
    assert vc.claim(rec["voice_code"], "cid-owner")[0] == "ok"


def test_la_richiesta_porta_nome_e_presentazione_ripuliti(tmp_path):
    rec = _pronta(tmp_path)
    lunga = "Ciao,\n\tsono\u202e Anna " + "x" * 400
    _claim(rec["voice_code"], "cid-nuovo", now=1000, device_name="Tel\x00 Anna", identity=lunga)
    pc = vc.get(rec["id"])["pending_confirm"]
    assert pc["device_name"] == "Tel Anna"
    assert pc["identity"].startswith("Ciao, sono Anna xxx") and len(pc["identity"]) == vc.IDENTITY_MAX


def test_il_codice_vale_24_ore_dalla_richiesta(tmp_path):
    assert vc.CONFIRM_TTL_SEC == 24 * 3600
    rec = _pronta(tmp_path)
    _, _, code = _claim(rec["voice_code"], "cid-nuovo", now=1000)
    assert vc.confirm(rec["voice_code"], "cid-nuovo", code, now=1000 + 24 * 3600 - 60) == "ok"
    rec2 = _pronta(tmp_path, cid="cid-altro")
    _, _, code = _claim(rec2["voice_code"], "cid-nuovo", now=1000)
    assert vc.confirm(rec2["voice_code"], "cid-nuovo", code, now=1000 + 24 * 3600 + 1) == "expired"


def test_add_resume_device_con_nome(tmp_path):
    rec = _pronta(tmp_path)
    assert vc.add_resume_device(rec["id"], "cid-r", "Tablet", now=5) is True
    assert vc.device_of(vc.get(rec["id"]), "cid-r") == {
        "cid": "cid-r", "added_at": 5, "via": "resume", "name": "Tablet"}
    # gia' dentro: nessun duplicato
    assert vc.add_resume_device(rec["id"], "cid-r", "Altro", now=6) is False
    assert len(vc.get(rec["id"])["devices"]) == 2


def test_rename_device_dal_link_di_gestione(tmp_path):
    rec = _pronta(tmp_path)
    assert vc.rename_device(rec["manage_token"], "cid-owner", "  Portatile ") is True
    assert vc.device_of(vc.get(rec["id"]), "cid-owner")["name"] == "Portatile"
    assert vc.rename_device(rec["manage_token"], "cid-ignoto", "x") is False
    assert vc.rename_device("token-sbagliato", "cid-owner", "x") is False


def test_revocato_il_creatore_nessuno_e_piu_proprietario(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = _claim(rec["voice_code"], "cid-b", now=1000)
    vc.confirm(rec["voice_code"], "cid-b", code, now=1001)
    assert vc.revoke_device(rec["manage_token"], "cid-owner") is True
    got = vc.get(rec["id"])
    assert got["state"] == "ready"
    assert not any(vc.is_owner(got, c) for c in ("cid-owner", "cid-b"))
    assert vc.authorized(vc.voice_id_of(got), "cid-b")


def test_mine_riporta_il_nome_con_cui_questo_dispositivo_e_registrato(tmp_path):
    rec = _pronta(tmp_path)
    vc.rename_device(rec["manage_token"], "cid-owner", "PC di casa")
    assert vc.mine("cid-owner")[0]["device_name"] == "PC di casa"
