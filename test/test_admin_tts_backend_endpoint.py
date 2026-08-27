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
    # Il rientro su Cloudflare e' rifiutato quando l'ambiente non seleziona
    # Cloudflare (409): il default di questa fixture e' quindi la
    # configurazione in cui il reset e' legittimo. I test che vogliono
    # provare il rifiuto sovrascrivono la variabile da soli.
    # Credenziali FINTE: servono solo a far risolvere _resolve_backend, non
    # viene mai aperta alcuna connessione.
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "account-di-test")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "token-di-test")
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


def test_reset_never_touches_the_spend_ledger(client, monkeypatch):
    # Il rientro dal breaker e l'azzeramento del ledger sono due decisioni
    # diverse: aver risolto il guasto non implica aver ricaricato il credito.
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    st.add_spend("flash31", 30.0)
    client.post("/admin/api/tts_backend", headers=AUTH,
                json={"action": "reset"})
    assert st.credit_left_eur() == pytest.approx(20.0)


def test_the_old_topup_field_on_reset_is_refused_not_ignored(client, monkeypatch):
    # La forma vecchia dell'API (topup come campo del rientro) non deve
    # essere accettata in silenzio lasciando il ledger intatto: chi la usa
    # crede di aver azzerato la spesa e leggerebbe un residuo sbagliato.
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    st.add_spend("flash31", 30.0)
    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "reset", "topup": True})
    assert r.status_code == 400
    assert "topup" in r.get_json()["error"]
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

    # Il reset deve aver invalidato la cache in-process: la voce sparisce
    # (una riscrittura del solo disco la lascerebbe congelata su "vertex"
    # fino al riavvio del processo) e la risoluzione successiva torna a
    # Cloudflare passando da _resolve_backend, non da un valore forzato.
    assert "flash31" not in gemini_tts._BACKEND
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

    # OGNI modello noto, target compreso, ha la voce di cache invalidata
    # (rimossa, non lasciata a "vertex" e non sovrascritta a mano): la
    # prossima sintesi la ririsolve da zero rispettando il proprio stato
    # reale, invece di restare congelata sul valore stantio letto prima del
    # reset.
    for key in gemini_tts.GEMINI_MODELS:
        assert key not in gemini_tts._BACKEND, (
            f"la cache di {key!r} non e' stata invalidata dal reset di flash31"
        )


# --- Guardie del rientro (F1) ---------------------------------------------
#
# `reset()` MATERIALIZZA la voce di stato su disco e il vecchio endpoint
# chiamava poi `_set_backend(model_key, "cloudflare")` senza validare nulla.
# Le conseguenze, entrambe verificate in esecuzione prima del fix:
#  - un reset su un modello che Cloudflare non ospita (flash25,
#    id_cloudflare=None) lo inchiodava su Cloudflare: da li' in poi ogni job
#    PREMIUM su quel modello finiva in TransportError(fatal) ->
#    GeminiUnavailable -> errore + rimborso integrale, fino al riavvio;
#  - con ABM_GEMINI_BACKEND diverso da "cloudflare" la console rispondeva
#    200 e accendeva Cloudflare in-process, cosa che l'ambiente non
#    autorizza. La guardia lato client (bottone disabilitato) e' scavalcata
#    da una chiamata diretta all'API.

def test_an_unknown_model_key_is_rejected(client):
    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "reset", "model_key": "modello-inesistente"})
    assert r.status_code == 400
    assert "modello-inesistente" in r.get_json()["error"]
    # E soprattutto: nessuna voce spuria e' finita nello stato persistito.
    assert st.state("modello-inesistente") == {}


def test_an_unknown_model_key_from_the_query_string_is_rejected(client):
    # model_key arriva sia da query sia dal corpo JSON: la guardia deve
    # valere per entrambe le vie, non solo per quella del corpo.
    r = client.post("/admin/api/tts_backend?model_key=fantasma", headers=AUTH,
                    json={"action": "reset"})
    assert r.status_code == 400
    assert st.state("fantasma") == {}


def test_reset_is_refused_when_the_environment_does_not_select_cloudflare(
        client, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "auto")
    st.trip("flash31", reason="cf_backend_down", detail="d", job_id="j")

    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "reset"})
    assert r.status_code == 409
    body = r.get_json()
    assert body["configured_backend"] == "auto"
    # Il messaggio deve dire PERCHE', non solo che e' vietato.
    assert "ABM_GEMINI_BACKEND" in body["error"]
    # Il trip non e' stato toccato: un rifiuto che azzerasse comunque lo
    # stato sarebbe peggio di un 200.
    assert st.is_tripped("flash31") is True


def test_a_refused_reset_does_not_pin_any_model_on_cloudflare(client, monkeypatch):
    # Il difetto vero: con configurazione "auto" il vecchio endpoint fissava
    # su Cloudflare il model_key passato, flash25 compreso — che su
    # Cloudflare non esiste (id_cloudflare=None).
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "auto")
    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "reset", "model_key": "flash25"})
    assert r.status_code == 409
    assert gemini_tts._BACKEND.get("flash25") != "cloudflare"
    assert gemini_tts._resolve_backend("flash25") != "cloudflare"


def test_reset_never_pins_a_model_cloudflare_does_not_host(client):
    # Anche con l'ambiente su "cloudflare" (reset legittimo), il rientro non
    # deve mai forzare su Cloudflare un modello privo di id_cloudflare: dopo
    # il pop, _resolve_backend lo rimanda su Vertex da solo.
    assert gemini_tts.GEMINI_MODELS["flash25"].get("id_cloudflare") is None
    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "reset", "model_key": "flash25"})
    assert r.status_code == 200
    assert gemini_tts._BACKEND.get("flash25") != "cloudflare"
    assert gemini_tts._resolve_backend("flash25") != "cloudflare"


def test_a_clean_install_does_not_report_a_self_contradictory_state(
        client, monkeypatch):
    # F5: su installazione pulita state() ritorna {} e il fallback fisso
    # "cloudflare" faceva scrivere al pannello «Cloudflare non configurato ·
    # il TTS gira su cloudflare».
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    body = client.get("/admin/api/tts_backend", headers=AUTH).get_json()
    assert body["configured_backend"] == "vertex"
    assert body["active"] == "vertex"


def test_the_fallback_of_active_is_the_declared_configuration_not_a_constant(
        client, monkeypatch):
    # N4: il test qui sopra passa anche mutando il ripiego in una costante
    # "vertex", perche' su quell'installazione la configurazione VALE
    # "vertex". Con `auto` — la configurazione della produzione di oggi, e
    # l'unica che nessun backend reale puo' pareggiare per caso — il ripiego
    # deve restare la configurazione dichiarata.
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "auto")
    body = client.get("/admin/api/tts_backend", headers=AUTH).get_json()
    assert body["configured_backend"] == "auto"
    assert body["active"] == "auto", (
        "su installazione pulita `active` deve ripiegare sulla "
        "configurazione dichiarata, non su una stringa fissa")


# --- N5: un model_key non stringa non deve produrre un 500 ----------------

def test_a_non_string_model_key_is_rejected_with_400_not_500(client):
    # `model_key` arriva anche dal corpo JSON, dove una lista e'
    # sintatticamente legittima: `model_key not in GEMINI_MODELS` su un
    # valore unhashable solleva TypeError -> 500. Deve seguire la stessa
    # strada di una chiave sconosciuta.
    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "reset", "model_key": ["flash31"]})
    assert r.status_code == 400
    assert "known_model_keys" in r.get_json()


def test_a_dict_model_key_on_get_is_not_a_500(client):
    r = client.get("/admin/api/tts_backend", headers=AUTH,
                   json={"model_key": {"a": 1}})
    assert r.status_code == 200
    assert r.get_json()["tripped_at"] is None


# --- N2: il topup e' un'azione a se', raggiungibile senza alcun trip -------
#
# `reset_spend()` e' l'unica cosa che riarma il pre-allarme sul credito
# (azzera `spent_eur` e `alerted`). Finche' il suo unico innesco era la
# casella accanto al pulsante di rientro — abilitato solo DOPO un trip —
# l'allarme partiva una volta sola nella vita dell'installazione: dal secondo
# ciclo di credito il servizio scivolava su Vertex di notte senza preavviso.

def test_topup_clears_the_ledger_without_any_trip(client, monkeypatch):
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    st.add_spend("flash31", 46.0)
    assert st.is_tripped("flash31") is False

    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "topup"})

    assert r.status_code == 200
    assert st.credit_left_eur() == pytest.approx(50.0)


def test_topup_does_not_touch_the_breaker(client):
    # Aver ricaricato il credito non dimostra che la causa del guasto sia
    # stata risolta: il rientro resta una decisione separata, con la sua
    # conferma.
    st.trip("flash31", reason="cf_backend_down", detail="d", job_id="j")
    gemini_tts._set_backend("flash31", "vertex")

    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "topup"})

    assert r.status_code == 200
    assert st.is_tripped("flash31") is True
    assert r.get_json()["tripped_at"] is not None
    assert gemini_tts._BACKEND.get("flash31") == "vertex", (
        "il topup non deve invalidare la cache in-process del backend")


def test_topup_is_refused_when_the_environment_does_not_select_cloudflare(
        client, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "auto")
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    st.add_spend("flash31", 46.0)

    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "topup"})

    assert r.status_code == 409
    assert "ABM_GEMINI_BACKEND" in r.get_json()["error"]
    # Un rifiuto che azzerasse comunque il ledger sarebbe peggio di un 200.
    assert st.credit_left_eur() == pytest.approx(4.0)


def test_topup_with_an_unknown_model_key_is_rejected(client):
    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "topup", "model_key": "fantasma"})
    assert r.status_code == 400
    assert st.state("fantasma") == {}


def test_the_refusal_explains_the_action_the_caller_asked_for(client):
    # Lo stesso 400 serve due azioni con effetti diversi: solo il reset
    # materializzerebbe una voce di stato. Motivare il topup con la frase del
    # reset manda l'admin a cercare una voce che quell'azione non crea mai.
    reset = client.post("/admin/api/tts_backend", headers=AUTH,
                        json={"action": "reset", "model_key": "fantasma"})
    topup = client.post("/admin/api/tts_backend", headers=AUTH,
                        json={"action": "topup", "model_key": "fantasma"})
    assert "voce di stato" in reset.get_json()["error"]
    assert "voce di stato" not in topup.get_json()["error"]


def test_the_topup_log_does_not_report_a_residual_nobody_declared(
        client, monkeypatch):
    # Senza ABM_CF_CREDIT_BALANCE_EUR il "residuo" e' la spesa cambiata di
    # segno: un negativo che il pre-allarme stesso ignora (con saldo <= 0 non
    # scatta mai). Stamparlo come misura fa leggere all'admin un numero che non
    # significa nulla proprio nella riga che documenta la ricarica.
    logged = []
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda *a, **kw: logged.append(a))
    monkeypatch.delenv("ABM_CF_CREDIT_BALANCE_EUR", raising=False)
    st.add_spend("flash31", 3.0)

    client.post("/admin/api/tts_backend", headers=AUTH, json={"action": "topup"})

    dettaglio = logged[0][6]
    assert "-3.00" not in dettaglio
    assert "non dichiarato" in dettaglio


def test_the_topup_log_reports_the_residual_when_a_balance_is_declared(
        client, monkeypatch):
    logged = []
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda *a, **kw: logged.append(a))
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    st.add_spend("flash31", 46.0)

    client.post("/admin/api/tts_backend", headers=AUTH, json={"action": "topup"})

    assert "4.00" in logged[0][6]


def test_topup_is_written_to_the_activity_log(client, monkeypatch):
    # Una forense sul credito deve poter ritrovare l'azzeramento: senza
    # questa riga la spesa cumulata sparisce senza traccia.
    logged = []
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda *a, **kw: logged.append(a))
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    st.add_spend("flash31", 46.0)

    client.post("/admin/api/tts_backend", headers=AUTH, json={"action": "topup"})

    assert logged, "il topup deve finire nell'activity log"
    assert logged[0][2] == "ADMIN_TTS_CREDIT_TOPUP"


def test_the_second_credit_cycle_alerts_again(client, monkeypatch):
    """Il ciclo completo, che prima si poteva percorrere una volta sola.

    Primo ciclo: la spesa porta il residuo sotto soglia, l'allarme viene
    consumato (una sola email). Ricarica: saldo dichiarato rialzato + topup
    dalla console. Secondo ciclo: la spesa riporta il residuo sotto soglia e
    l'allarme deve poter tornare a scattare.
    """
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    monkeypatch.setenv("ABM_CF_CREDIT_ALERT_EUR", "5")

    # --- ciclo 1: allarme consumato -------------------------------------
    st.add_spend("flash31", 46.0)          # residuo 4,00 < soglia 5,00
    assert st.claim_credit_alert() is True
    assert st.claim_credit_alert() is False, "l'allarme e' a consumo unico"

    # --- ricarica: nuovo saldo dichiarato + topup dalla console ----------
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "100")
    r = client.post("/admin/api/tts_backend", headers=AUTH,
                    json={"action": "topup"})
    assert r.status_code == 200
    assert st.credit_left_eur() == pytest.approx(100.0), (
        "senza azzerare il ledger il residuo del secondo ciclo nasce gia' "
        "decurtato della spesa del primo")
    assert st.claim_credit_alert() is False, (
        "subito dopo la ricarica il residuo e' sopra soglia: nessun allarme")

    # --- ciclo 2: la soglia viene riattraversata -------------------------
    st.add_spend("flash31", 96.0)          # residuo 4,00 < soglia 5,00
    assert st.credit_alert_pending() is True
    assert st.claim_credit_alert() is True, (
        "il pre-allarme deve poter scattare di nuovo dal secondo ciclo di "
        "credito in poi: senza un topup raggiungibile senza trip, "
        "l'installazione riceve una sola email nella sua vita")
