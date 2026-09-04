"""Contratto backend delle app mobile GIA' PUBBLICATE.

Il client Flutter (repo audiobook-maker-mobile) filtra le voci gratuite con
`engine: (j['engine'] ?? 'edge')`: quando il campo manca assume 'edge'. Nella
stessa risposta viaggiano oltre 1.600 voci a pagamento. Se `engine` sparisse,
il mobile non fallirebbe: le mostrerebbe come gratuite.

Questi test non descrivono un comportamento nuovo. Fissano quello attuale,
perche' l'aggiornamento delle app mobile non ha tempi certi e il backend deve
restare compatibile con le versioni gia' sugli store.
"""
import pathlib

import pytest

import audiobook_app

RADICE = pathlib.Path(__file__).resolve().parents[1]


def _sorgente_app():
    """Il sorgente di audiobook_app.py, ancorato al FILE di test.

    Con un percorso relativo alla cwd i test che lo leggono falliscono con
    FileNotFoundError appena pytest viene lanciato da un'altra directory: un
    rosso che non dice niente, in un file che esiste per segnalare rotture vere
    verso app che non possiamo aggiornare.
    """
    return (RADICE / "audiobook_app.py").read_text(encoding="utf-8")


def _catalogo_dalla_rotta():
    """Il catalogo COSI` COME LO RICEVE IL MOBILE: da GET /api/voices.

    Non `get_voices()`, che e' la cache interna: fra le due c'e' `api_voices()`,
    la funzione che questo lavoro ha davvero modificato. Un refactoring che
    avvolgesse o filtrasse la risposta dentro la rotta lascerebbe verdi dei test
    fatti sulla cache, mentre in produzione il client gia' pubblicato
    mostrerebbe come gratuite le voci a pagamento.

    /api/voices e' di sola lettura: nessun job, nessun pagamento, nessun invio.
    """
    risposta = audiobook_app.app.test_client().get("/api/voices")
    assert risposta.status_code == 200, (
        f"/api/voices ha risposto {risposta.status_code}: il mobile non ha "
        "nessun altro modo di ottenere il catalogo"
    )
    corpo = risposta.get_json()
    assert isinstance(corpo, dict), "/api/voices non ha risposto con un oggetto JSON"
    assert "error" not in corpo, f"/api/voices ha risposto con un errore: {corpo}"
    return corpo


def _lingue(catalogo):
    """Solo le chiavi-lingua: le `_*` sono metadati, non lingue."""
    return {k: v for k, v in catalogo.items() if not k.startswith("_")}


def test_ogni_voce_espone_engine():
    catalogo = _catalogo_dalla_rotta()
    senza_engine = []
    for codice, dati in _lingue(catalogo).items():
        for voce in dati.get("voices", []):
            if not voce.get("engine"):
                senza_engine.append(f"{codice}/{voce.get('id', '?')}")
    assert not senza_engine, (
        "voci senza 'engine' (il mobile le mostrerebbe come gratuite): "
        + ", ".join(senza_engine[:20])
    )


# Le tre famiglie a pagamento, per PREFISSO DELL'ID: e' il prefisso, non il
# campo `engine`, a decidere la cassa in /api/generate.
FAMIGLIE_A_PAGAMENTO = ("gemini:", "voxcpm:", "speechify:")


def _travestite_da_gratuite(catalogo):
    """Id a pagamento che si presentano al mobile con engine='edge'."""
    fuori = []
    for dati in _lingue(catalogo).values():
        for voce in dati.get("voices", []):
            vid = str(voce.get("id", ""))
            if vid.startswith(FAMIGLIE_A_PAGAMENTO) and voce.get("engine") == "edge":
                fuori.append(vid)
    return fuori


def test_engine_edge_non_copre_le_voci_a_pagamento():
    """Le voci a pagamento devono avere un engine DIVERSO da 'edge'.

    Catalogo COSTRUITO A MANO, non quello della macchina: qui le tre famiglie
    ci sono tutte e tre, mentre il catalogo reale di questo albero non contiene
    nessuna voce `voxcpm:` ne' `speechify:` — due prefissi su tre non verrebbero
    mai esercitati, e il test passerebbe identico con `engine` sbagliato.
    """
    travestito = {
        "_premium_status": {"capability_ok": True, "admin_disabled": False},
        "it": {"name": "Italian", "voices": [
            {"id": "it-IT-IsabellaNeural", "engine": "edge"},
            {"id": "gemini:flash25:Achernar", "engine": "edge"},
            {"id": "voxcpm:v2:it-IT/Bianca", "engine": "edge"},
            {"id": "speechify:simba-3.2:beatrice_32", "engine": "edge"},
        ]},
    }
    assert sorted(_travestite_da_gratuite(travestito)) == [
        "gemini:flash25:Achernar",
        "speechify:simba-3.2:beatrice_32",
        "voxcpm:v2:it-IT/Bianca",
    ], "il controllo non riconosce tutte e tre le famiglie a pagamento"

    sano = {
        "_premium_status": {"capability_ok": True, "admin_disabled": False},
        "it": {"name": "Italian", "voices": [
            {"id": "it-IT-IsabellaNeural", "engine": "edge"},
            {"id": "gemini:flash25:Achernar", "engine": "gemini"},
            {"id": "voxcpm:v2:it-IT/Bianca", "engine": "voxcpm"},
            {"id": "speechify:simba-3.2:beatrice_32", "engine": "speechify"},
        ]},
    }
    assert _travestite_da_gratuite(sano) == [], (
        "un catalogo corretto non deve produrre nessuna segnalazione"
    )


@pytest.mark.parametrize("prefisso", FAMIGLIE_A_PAGAMENTO)
def test_il_catalogo_vero_non_traveste_le_voci_a_pagamento(prefisso):
    """Lo stesso invariante sul catalogo di QUESTA macchina, via /api/voices,
    una famiglia per volta. Quando un motore non e' configurato il test si salta
    dicendolo, cosi' l'assenza di copertura si vede invece di travestirsi da
    verde."""
    catalogo = _catalogo_dalla_rotta()
    della_famiglia = [
        voce
        for dati in _lingue(catalogo).values()
        for voce in dati.get("voices", [])
        if str(voce.get("id", "")).startswith(prefisso)
    ]
    if not della_famiglia:
        pytest.skip(
            f"nessuna voce {prefisso} nel catalogo di questa macchina: "
            "invariante non esercitato per questa famiglia"
        )
    travestite = [str(v.get("id", "")) for v in della_famiglia
                  if v.get("engine") == "edge"]
    assert not travestite, (
        "voci a pagamento marcate engine='edge': " + ", ".join(travestite[:20])
    )


def test_forma_del_catalogo_invariata():
    """I3: chiavi di primo livello = lingue con name/voices, `_*` = metadati."""
    catalogo = _catalogo_dalla_rotta()
    lingue = _lingue(catalogo)
    assert lingue, "nessuna lingua nel catalogo"
    for codice, dati in lingue.items():
        assert isinstance(dati, dict), f"{codice} non e' un oggetto"
        assert "name" in dati, f"{codice} senza 'name'"
        assert isinstance(dati.get("voices"), list), f"{codice} senza 'voices'"
    campione = lingue[sorted(lingue)[0]]["voices"][0]
    for chiave in ("id", "name", "gender", "locale", "engine"):
        assert chiave in campione, f"voce senza '{chiave}'"


def test_il_cancello_del_pagamento_non_guarda_il_catalogo():
    """Il premium si riconosce dal PREFISSO DELL'ID, mai dal campo `engine`.

    `engine` e' materiale da vetrina: lo legge il client per raggruppare le
    voci. La cassa e' altrove — /api/generate riclassifica la voce dall'id che
    riceve (voice_utils.is_gemini_voice e sorelle, tre startswith) e pretende
    un payment_token o la quota gratuita, altrimenti 402.

    Questo test esiste perche' quella separazione non si perda in un
    refactoring: se un domani la classificazione premium passasse dal catalogo,
    un catalogo sbagliato diventerebbe un varco. Oggi non lo e', e non deve
    diventarlo.
    """
    import voice_utils

    assert voice_utils.is_gemini_voice("gemini:flash25:Achernar")
    assert voice_utils.is_speechify_voice("speechify:simba-3.2:beatrice_32")
    assert voice_utils.is_voxcpm_voice("voxcpm:v2:it-IT/Bianca")
    assert not voice_utils.is_gemini_voice("it-IT-IsabellaNeural")

    # Nessuno dei tre predicati accetta un dizionario-voce: lavorano su
    # stringhe. Se qualcuno li cambiasse per leggere `engine`, questo cade.
    for predicato in (voice_utils.is_gemini_voice,
                      voice_utils.is_speechify_voice,
                      voice_utils.is_voxcpm_voice):
        assert predicato({"engine": "gemini", "id": "it-IT-IsabellaNeural"}) is False


def test_generate_pretende_il_pagamento_sulle_voci_premium():
    """Il ramo 402 vive nel route, keyed sull'id della voce."""
    sorgente = _sorgente_app()
    assert 'if _is_speechify_voice(voice) or _is_voxcpm_voice(voice):' in sorgente
    assert '"error": "payment_required"' in sorgente


def test_generate_ha_il_ripiego_su_lang_assente():
    """I2: il mobile non manda `lang`. Il server deve ripiegare, non rifiutare.

    Variante statica, non la simulazione della richiesta HTTP: per arrivare
    davvero al ripiego bisognerebbe attraversare l'intero preflight di
    pagamento premium (quota gratuita, budget Google, RPD, invio email di
    notifica) — provato con una richiesta vera fatta collaborare con mock a
    catena, arriva a destinazione ma innesca effetti collaterali reali fuori
    dal controllo del test (un invio email effettivo osservato durante la
    verifica). Per una voce standard (non premium, come quella che manda il
    client Flutter) il ramo che legge `lang` non viene nemmeno attraversato:
    non e' un varco, e' semplicemente irraggiungibile da quella richiesta.

    Verifica quindi la proprieta' strutturale invece del comportamento a
    runtime: dentro il corpo di `api_generate` (da `def api_generate():`
    alla prossima `def ` a colonna 0, cosi' un `data["lang"]` diretto altrove
    nel modulo non fa fallire questo test) deve esistere il ripiego
    `data.get("lang")` e non deve esistere nessun accesso diretto
    `data["lang"]` (che solleverebbe KeyError quando il campo manca).
    """
    sorgente = _sorgente_app()
    righe = sorgente.splitlines()
    inizio = next(i for i, r in enumerate(righe) if r.startswith("def api_generate("))
    fine = next(i for i in range(inizio + 1, len(righe)) if righe[i].startswith("def "))
    corpo = "\n".join(righe[inizio:fine])

    assert 'data.get("lang")' in corpo, (
        "sparito il ripiego su `lang` assente in api_generate: il mobile "
        "non manda quel campo e la richiesta verrebbe rifiutata"
    )
    assert 'data["lang"]' not in corpo, (
        'api_generate legge data["lang"] senza ripiego: KeyError quando il '
        "mobile non lo manda"
    )
