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


def test_generate_accetta_body_senza_lang(monkeypatch, tmp_path):
    """I2: il mobile non manda `lang`. Il server deve ripiegare, non rifiutare.

    Body reale del client Flutter (abm_api_client.dart): job_id, voice,
    output_format, rate, selected_chapters, batch_mode.
    """
    import json

    app = audiobook_app.app
    app.config["TESTING"] = True

    avviati = {}

    def _finto_avvio(*args, **kwargs):
        avviati["chiamato"] = True

    monkeypatch.setattr(
        audiobook_app.threading, "Thread",
        lambda *a, **k: type("T", (), {"start": lambda self: _finto_avvio(),
                                       "daemon": True})(),
        raising=False,
    )

    with app.test_client() as client:
        resp = client.post(
            "/api/generate",
            data=json.dumps({
                "job_id": "job-inesistente",
                "voice": "it-IT-IsabellaNeural",
                "output_format": "mp3",
                "rate": "+0%",
                "selected_chapters": [0],
                "batch_mode": True,
            }),
            content_type="application/json",
        )

    # Il job non esiste: 404/400 sono risposte legittime. Cio' che NON deve
    # accadere e' un rifiuto per `lang` mancante (400 con quel messaggio) o un
    # 500 da KeyError.
    assert resp.status_code != 500, f"500 su body senza lang: {resp.data[:400]}"
    corpo = resp.get_data(as_text=True).lower()
    assert "lang" not in corpo or "missing" not in corpo, (
        f"/api/generate sembra pretendere `lang`: {corpo[:400]}"
    )
