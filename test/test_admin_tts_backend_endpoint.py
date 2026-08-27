"""Endpoint admin per lo stato del backend TTS e il rientro su Cloudflare."""
import pytest

import audiobook_app
import gemini_tts
import tts_backend_state as st


@pytest.fixture(autouse=True)
def _reset_gemini_backend_cache():
    # gemini_tts._BACKEND e' una cache in-process globale, condivisa con altri
    # file di test nello stesso processo pytest: isolarla evita che uno stato
    # lasciato da un test precedente (o da questo) contamini un altro modulo.
    gemini_tts._BACKEND = {}
    yield
    gemini_tts._BACKEND = {}


@pytest.fixture
def client(tmp_path, monkeypatch):
    st.init(str(tmp_path))
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "segreto")
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        yield c


AUTH = {"X-Admin-Token": "segreto"}


def test_unauthenticated_is_rejected(client):
    assert client.get("/admin/api/tts_backend").status_code == 401


def test_wrong_token_is_rejected(client):
    r = client.get("/admin/api/tts_backend", headers={"X-Admin-Token": "no"})
    assert r.status_code == 401


def test_get_returns_a_clean_state(client):
    r = client.get("/admin/api/tts_backend", headers=AUTH)
    assert r.status_code == 200
    body = r.get_json()
    assert body["tripped_at"] is None
    assert "credit_left_eur" in body


def test_get_reports_a_trip(client):
    st.trip("flash31", reason="cf_backend_down", detail="HTTP 402", job_id="j9")
    body = client.get("/admin/api/tts_backend", headers=AUTH).get_json()
    assert body["active"] == "vertex"
    assert body["trip_reason"] == "cf_backend_down"
    assert body["trip_job_id"] == "j9"


def test_reset_clears_the_trip(client):
    st.trip("flash31", reason="cf_backend_down", detail="d", job_id="j")
    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "reset"})
    assert r.status_code == 200
    assert r.get_json()["tripped_at"] is None
    assert st.is_tripped("flash31") is False


def test_reset_with_topup_clears_the_spend_ledger(client, monkeypatch):
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    st.add_spend("flash31", 30.0)
    st.trip("flash31", reason="cf_backend_down", detail="d", job_id="j")
    client.post("/admin/api/tts_backend", headers=AUTH,
                json={"action": "reset", "topup": True})
    assert st.credit_left_eur() == pytest.approx(50.0)


def test_reset_without_topup_keeps_the_ledger(client, monkeypatch):
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    st.add_spend("flash31", 30.0)
    client.post("/admin/api/tts_backend", headers=AUTH,
                json={"action": "reset"})
    assert st.credit_left_eur() == pytest.approx(20.0)


def test_an_unknown_action_is_rejected(client):
    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "esplodi"})
    assert r.status_code == 400


def test_the_endpoint_is_invisible_without_an_admin_token(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "")
    assert client.get("/admin/api/tts_backend").status_code == 404


# --- Invalidazione della cache in-process (il punto facile da sbagliare) ---
#
# tts_backend_state e' solo lo stato persistito su disco. gemini_tts._BACKEND
# e' la cache in-process consultata a ogni sintesi (gemini_tts._resolve_backend):
# un reset che scrive solo su disco risponde 200/OK ma, se _BACKEND ha gia' una
# voce per quel model_key, _resolve_backend la ritorna per sempre (fino al
# riavvio del processo) ignorando il reset appena fatto. Questi test falliscono
# se l'endpoint smette di invalidare quella cache.

def test_reset_reactivates_cloudflare_in_the_in_process_cache(client):
    # Simula lo stato post-trip: sia il disco (tts_backend_state) sia la
    # cache in-process (gemini_tts._BACKEND) dicono "vertex" per flash31.
    st.trip("flash31", reason="cf_backend_down", detail="d", job_id="j")
    gemini_tts._set_backend("flash31", "vertex")
    assert gemini_tts._resolve_backend("flash31") == "vertex"

    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "reset"})
    assert r.status_code == 200

    # Il reset deve aver riportato la cache in-process su "cloudflare": una
    # riscrittura solo del disco non cambierebbe questo valore, congelato
    # nella cache fino al prossimo cache-miss.
    assert gemini_tts._BACKEND.get("flash31") == "cloudflare"
    assert gemini_tts._resolve_backend("flash31") == "cloudflare"


def test_reset_invalidates_the_cache_of_every_known_model_not_only_the_target(client):
    # Precondizione: OGNI modello noto ha gia' una voce "vertex" in cache
    # (es. perche' era stato risolto prima di un trip, o perche' un trip
    # precedente lo aveva forzato su vertex). Un reset che tocchi solo il
    # model_key passato lascerebbe le altre voci intonse.
    for key in gemini_tts.GEMINI_MODELS:
        gemini_tts._set_backend(key, "vertex")

    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "reset", "model_key": "flash31"})
    assert r.status_code == 200

    # Il modello target e' esplicitamente riportato su cloudflare...
    assert gemini_tts._BACKEND.get("flash31") == "cloudflare"
    # ...e OGNI altro modello noto ha la voce di cache invalidata (rimossa,
    # non lasciata a "vertex"): la prossima sintesi la ririsolve da zero
    # rispettando il proprio stato reale, invece di restare congelata sul
    # valore stantio letto prima del reset.
    for key in gemini_tts.GEMINI_MODELS:
        if key == "flash31":
            continue
        assert gemini_tts._BACKEND.get(key) != "vertex", (
            f"la cache di {key!r} non e' stata invalidata dal reset di flash31"
        )
