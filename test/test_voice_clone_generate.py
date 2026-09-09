"""Uso della voce campione nei libri (spec §9)."""
import os

import pytest

import audiobook_app
import community_store
import generation_engine as ge
import storage_backend
import voice_clone as vc
import voxcpm_catalog
import voxcpm_ranking

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave-di-prova")
    # voxcpm_tts.is_available() richiede anche una tariffa di listino > 0
    # (§9.4): senza questa env /api/generate rifiuterebbe con
    # voxcpm_not_configured prima ancora di raggiungere il guard sotto test.
    # Stesso valore usato da test/test_voxcpm_tts.py e simili.
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "4.00")
    voxcpm_catalog.invalidate_cache()
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    audiobook_app._invalidate_voices_cache()
    yield
    voxcpm_catalog.invalidate_cache()


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie(audiobook_app._CLIENT_COOKIE_NAME, "cid-uno")
        yield c


def _ready(tmp_path, cid="cid-uno"):
    import voice_clone_prompts
    s = tmp_path / f"{cid}-s.wav"
    s.write_bytes(b"RIFF")
    o = tmp_path / f"{cid}-o.webm"
    o.write_bytes(b"x")
    rec = vc.create_draft(cid, lang="it", locale="it-IT", gender="f",
                          prompt_text=voice_clone_prompts.prompt_for("it", "f"), sample_wav=str(s),
                          original_path=str(o), original_ext="webm", metrics={}, ui_lang="it")
    rec, _ = vc.commit(rec["id"], cid, email=cid + "@x.it", extra_id="m", extra_text="e",
                       common_text="c", payment_token="", price_eur=0.0)
    for st in ("demos_generating", "demos_ready", "ready"):
        rec = vc.transition(rec["id"], st)
    return rec


def _job(monkeypatch, job_id="JOBVC1"):
    class Ch:
        def __init__(self, i):
            self.index, self.title, self.text, self.char_count, self.word_count = i, f"c{i}", "Testo.", 6, 1

    class Info:
        title, author, language = "Libro", "A", "it"
        chapters = [Ch(0)]
    monkeypatch.setitem(audiobook_app.jobs, job_id, {
        "status": "analyzed", "info": Info(), "client_id": "cid-uno", "created": 0})
    return job_id


def _generate(client, job_id, voice, lang="it", locale=None):
    payload = {"job_id": job_id, "voice": voice, "lang": lang,
              "output_format": "mp3", "rate": "+0%"}
    if locale is not None:
        payload["locale"] = locale
    return client.post("/api/generate", json=payload)


def test_generate_rifiuta_cid_non_autorizzato(client, tmp_path, monkeypatch):
    rec = _ready(tmp_path, cid="cid-altro")
    jid = _job(monkeypatch)
    r = _generate(client, jid, vc.voice_id_of(rec))
    assert r.status_code == 403 and r.get_json()["error_code"] == "voice_not_authorized"


def test_generate_rifiuta_lingua_diversa(client, tmp_path, monkeypatch):
    rec = _ready(tmp_path)
    jid = _job(monkeypatch)
    r = _generate(client, jid, vc.voice_id_of(rec), lang="en")
    assert r.status_code == 400 and r.get_json()["error_code"] == "voice_lang_mismatch"


def test_generate_rifiuta_locale_diverso(client, tmp_path, monkeypatch):
    # Voce it-IT ma libro dichiarato it-CH: stessa lingua, accento diverso ->
    # mismatch (spec §9 riga 479). Il locale qui e' quello del LIBRO/chiamata,
    # non quello della voce: un confronto della voce con se stessa sarebbe
    # tautologico e non intercetterebbe mai nulla.
    rec = _ready(tmp_path)
    jid = _job(monkeypatch)
    r = _generate(client, jid, vc.voice_id_of(rec), lang="it", locale="it-CH")
    assert r.status_code == 400 and r.get_json()["error_code"] == "voice_lang_mismatch"


def test_generate_rifiuta_voce_sparita(client, tmp_path, monkeypatch):
    rec = _ready(tmp_path)
    vc.transition(rec["id"], "expired")
    jid = _job(monkeypatch)
    r = _generate(client, jid, vc.voice_id_of(rec))
    assert r.status_code == 410 and r.get_json()["error_code"] == "voice_gone"


def test_generate_accetta_e_rinnova_la_retention(client, tmp_path, monkeypatch):
    rec = _ready(tmp_path)
    vc.store().update(rec["id"], {"last_used_at": 1, "expires_at": 2})
    jid = _job(monkeypatch)
    avviati = []
    monkeypatch.setattr(audiobook_app, "run_generation", lambda *a, **k: avviati.append(a), raising=False)
    monkeypatch.setattr(audiobook_app.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda self: avviati.append(k.get("args"))})())
    r = _generate(client, jid, vc.voice_id_of(rec))
    assert r.status_code == 200, r.get_json()
    cur = vc.get(rec["id"])
    assert cur["last_used_at"] > 1 and cur["expires_at"] > 2


def test_preview_non_supportata_per_la_voce_personale(client, tmp_path, monkeypatch):
    # /api/preview_audio e' GET-only e legge la voce da query string, non dal
    # body: il rifiuto vale gia' prima di controllare il job (basta il prefisso
    # VoxCPM sulla voce), quindi il job_id nell'URL puo' anche non esistere.
    rec = _ready(tmp_path)
    jid = _job(monkeypatch)
    r = client.get(f"/api/preview_audio/{jid}", query_string={"voice": vc.voice_id_of(rec)})
    assert r.status_code == 400 and r.get_json()["error"] == "voxcpm_preview_unsupported"


def test_recovery_gate_rifiuta_voce_non_usabile(tmp_path, monkeypatch):
    rec = _ready(tmp_path)
    vc.transition(rec["id"], "expired")

    class Ch:
        index, title, text, char_count = 0, "c", "Testo.", 6

    class Info:
        title, language = "Libro", "it"
        chapters = [Ch()]
    with pytest.raises(audiobook_app._RecoveryRejected):
        audiobook_app._recovery_generate_gate("J1", {"voice": vc.voice_id_of(rec), "client_id": "cid-uno",
                                                     "lang": "it"}, Info())


def test_recovery_gate_stima_voxcpm(tmp_path, monkeypatch):
    rec = _ready(tmp_path)

    class Ch:
        index, title, text, char_count = 0, "c", "Testo.", 6

    class Info:
        title, language = "Libro", "it"
        chapters = [Ch()]
    monkeypatch.setattr(audiobook_app, "_assert_priced_on_real_text", lambda *a: True)
    monkeypatch.setattr(audiobook_app, "_premium_quota_decision",
                        lambda cid, voice, price, jid: {"is_free": True, "charge_eur": 0.0})
    monkeypatch.setattr(audiobook_app, "_free_quota_log", lambda *a: None, raising=False)
    out = audiobook_app._recovery_generate_gate("J1", {"voice": vc.voice_id_of(rec), "client_id": "cid-uno",
                                                       "lang": "it"}, Info())
    assert out["estimate_key"] == "voxcpm_estimate" and "list_price_eur" in out["estimate"]


def test_tag_e_etichette_della_voce_personale(tmp_path, monkeypatch):
    rec = _ready(tmp_path)
    vid = vc.voice_id_of(rec)
    assert ge._friendly_voice_name(vid) == "Your voice"
    assert ge._friendly_voice_name("voxcpm:v2:it-IT/Stefano") == "Stefano"

    class Info:
        language = "it"
    tags = ge._generation_tags({"voice": vid}, Info(), vid, "+0%")
    # Il token e' un segreto (voice_clone.py): nei metadati del file
    # consegnato (ri-condivisibile dall'utente) puo' finire solo il prefisso
    # 'voxcpm:mine', mai l'id completo col token.
    assert tags["abm_voice"] == "user-voice" and tags["abm_voice_id"] == "voxcpm:mine"
    assert tags["abm_model"] == voxcpm_catalog.MODEL_LABEL and tags["abm_language"] == "it"
    tok = vc.token_of(vid)
    assert not any(tok in str(v) for v in tags.values())
    # Voce di catalogo (non personale): l'id completo resta nei metadati,
    # non e' un segreto.
    tags = ge._generation_tags({"voice": "voxcpm:v2:it-IT/Stefano"}, Info(), "voxcpm:v2:it-IT/Stefano", "+0%")
    assert tags["abm_voice"] == "Stefano" and tags["abm_language"] == "it-IT"
    assert tags["abm_voice_id"] == "voxcpm:v2:it-IT/Stefano"


def test_righe_email_considerano_voxcpm_premium(tmp_path):
    rec = _ready(tmp_path)
    # gen_lang (non solo "lang"): e' il campo che _generation_details_lines
    # legge per popolare la riga "lingua + tipo voce" nel ramo premium (senza
    # non emetterebbe affatto quella riga, rendendo il test un falso negativo).
    righe = ge._generation_details_lines(
        {"voice": vc.voice_id_of(rec), "lang": "it", "gen_lang": "it"}, "it")
    testo = "\n".join(righe) if isinstance(righe, list) else str(righe)
    # La riga "tipo voce" deve usare la chiave PREMIUM (la stessa di
    # Gemini/Speechify), non quella standard: verifica diretta sul dizionario
    # i18n usato dalla funzione, non su una sottostringa fragile del testo
    # gia' HTML-escaped.
    premium_label = ge._email_details_i18n["it"]["voice_type_premium"]
    standard_label = ge._email_details_i18n["it"]["voice_type_standard"]
    assert premium_label in testo
    assert standard_label not in testo
    assert "Your voice" in testo


def test_classifica_ignora_le_voci_personali(tmp_path, monkeypatch):
    chiamate = []
    monkeypatch.setattr(voxcpm_ranking, "punto", lambda voice, jid: chiamate.append(voice))
    assert ge._ranking_point_allowed("voxcpm:v2:it-IT/Stefano") is True
    assert ge._ranking_point_allowed("voxcpm:mine:abcdef") is False
