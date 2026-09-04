"""Contratto backend delle app mobile GIA' PUBBLICATE.

Il client Flutter (repo audiobook-maker-mobile) filtra le voci gratuite con
`engine: (j['engine'] ?? 'edge')`: quando il campo manca assume 'edge'. Nella
stessa risposta viaggiano oltre 1.600 voci a pagamento. Se `engine` sparisse,
il mobile non fallirebbe: le mostrerebbe come gratuite.

Questi test non descrivono un comportamento nuovo. Fissano quello attuale,
perche' l'aggiornamento delle app mobile non ha tempi certi e il backend deve
restare compatibile con le versioni gia' sugli store.
"""
import pytest

import audiobook_app


def test_ogni_voce_espone_engine():
    catalogo = audiobook_app.get_voices()
    senza_engine = []
    for codice, dati in catalogo.items():
        if codice.startswith("_"):
            continue
        for voce in dati.get("voices", []):
            if not voce.get("engine"):
                senza_engine.append(f"{codice}/{voce.get('id', '?')}")
    assert not senza_engine, (
        "voci senza 'engine' (il mobile le mostrerebbe come gratuite): "
        + ", ".join(senza_engine[:20])
    )


def test_engine_edge_non_copre_le_voci_a_pagamento():
    """Le voci a pagamento devono avere un engine DIVERSO da 'edge'."""
    catalogo = audiobook_app.get_voices()
    travestite = []
    for codice, dati in catalogo.items():
        if codice.startswith("_"):
            continue
        for voce in dati.get("voices", []):
            vid = str(voce.get("id", ""))
            a_pagamento = vid.startswith(("gemini:", "voxcpm:", "speechify:"))
            if a_pagamento and voce.get("engine") == "edge":
                travestite.append(vid)
    assert not travestite, (
        "voci a pagamento marcate engine='edge': " + ", ".join(travestite[:20])
    )


def test_forma_del_catalogo_invariata():
    """I3: chiavi di primo livello = lingue con name/voices, `_*` = metadati."""
    catalogo = audiobook_app.get_voices()
    lingue = [k for k in catalogo if not k.startswith("_")]
    assert lingue, "nessuna lingua nel catalogo"
    for codice in lingue:
        dati = catalogo[codice]
        assert isinstance(dati, dict), f"{codice} non e' un oggetto"
        assert "name" in dati, f"{codice} senza 'name'"
        assert isinstance(dati.get("voices"), list), f"{codice} senza 'voices'"
    campione = catalogo[lingue[0]]["voices"][0]
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
    import pathlib
    sorgente = pathlib.Path("audiobook_app.py").read_text(encoding="utf-8")
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
    import pathlib

    sorgente = pathlib.Path("audiobook_app.py").read_text(encoding="utf-8")
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
