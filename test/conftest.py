from datetime import datetime
from unittest.mock import patch

import importlib
import os
import sys
import routes_admin_logs

import pytest

# M6: ambiente della sessione PRIMA di ogni test. `fresh_app` lo rimette al
# momento del reload di ripristino, cosi' i moduli tornano ai default anche se
# un'altra fixture ha ancora le sue env attive.
_ENV_AT_START = dict(os.environ)

# Test che dipendono da risorse NON tracciate da git (il catalogo voci VoxCPM
# in `voxcpm2/`, 578 MB di wav; il wrapper PowerShell del banco di prova):
# in locale girano, nel gate CI (`deploy.yml`, O2) vengono saltati con la
# ragione esplicita invece di fallire. "*" = tutto il file.
_LOCAL_ASSET_TESTS = {
    "test_voice_clone_replica.py": {"*"},
    "test_voxcpm_runpod.py": {"test_il_capitolo_inoltra_gli_avanzamenti", "test_l_interruttore_spegne_l_inoltro"},
    "test_admin_voice_xss.py": {"test_voice_id_regex_accepts_every_voxcpm_catalog_id"},
    "test_audio_generation_tags.py": {"test_tags_voce_voxcpm_non_scambia_lid_per_la_lingua"},
    "test_free_quota_generate_enforcement.py": {"test_voxcpm_libro_oltre_cap_gratuito_richiede_pagamento"},
    "test_cf_tts_bench.py": {"test_wrapper_eseguito_davvero_non_inietta_langs"},
}


def _voxcpm_catalog_present():
    try:
        import os
        import voxcpm_catalog
        return os.path.exists(os.path.join(voxcpm_catalog.catalog_dir(), "voices.json"))
    except Exception:      # noqa: BLE001
        return False


def pytest_collection_modifyitems(config, items):
    if _voxcpm_catalog_present():
        return
    skip = pytest.mark.skip(reason="risorsa locale non tracciata assente (catalogo VoxCPM voxcpm2/ o wrapper PowerShell)")
    for item in items:
        names = _LOCAL_ASSET_TESTS.get(item.fspath.basename)
        if names and ("*" in names or item.originalname in names or item.name.split("[")[0] in names):
            item.add_marker(skip)


def _reload_chain(leaves=()):
    """Ordine fisso: prima le foglie chieste, poi generation_engine, poi
    audiobook_app (che riconfigura blueprint ed engine e rilega jobs). Un
    reload di una foglia o dell'engine SENZA l'app lasciava l'engine con lo
    stato di configure() azzerato: il 404 "job not found" che compariva
    solo nella suite completa."""
    for name in leaves:
        importlib.reload(importlib.import_module(name))
    import generation_engine
    importlib.reload(generation_engine)
    import audiobook_app
    importlib.reload(audiobook_app)
    return audiobook_app


@pytest.fixture
def fresh_app():
    """`fresh_app(env={...}, leaves=(...))` ricarica i moduli con le env date
    (valore None = variabile tolta) e ritorna il modulo `audiobook_app`.

    A fine test ricarica di nuovo con l'ambiente di inizio sessione: i test
    successivi trovano i default, non la ABM_DATA_DIR del tmp_path di un
    altro test. E' l'unico posto dove si fa `importlib.reload` dell'app o
    dell'engine (test_m6_test_hygiene)."""
    mp = pytest.MonkeyPatch()
    used = {"leaves": None}

    def _go(env=None, leaves=()):
        for k, v in (env or {}).items():
            if v is None:
                mp.delenv(k, raising=False)
            else:
                mp.setenv(k, str(v))
        used["leaves"] = tuple(leaves)
        return _reload_chain(used["leaves"])

    yield _go
    mp.undo()
    if used["leaves"] is not None:
        current = dict(os.environ)
        os.environ.clear()
        os.environ.update(_ENV_AT_START)
        try:
            _reload_chain(used["leaves"])
        finally:
            os.environ.clear()
            os.environ.update(current)


@pytest.fixture(autouse=True)
def _reset_log_sessions_cache():
    """Sessioni di /admin/log-activity in cache per (mese, cartella, firma):
    i test che sostituiscono _parse_log_sessions o scrivono log diversi non
    devono vedere il risultato di un test precedente."""
    app = sys.modules.get("audiobook_app")
    if app is not None:
        routes_admin_logs._LOG_SESSIONS_CACHE.clear()
    yield


@pytest.fixture(autouse=True)
def _no_live_typesafe(monkeypatch):
    """Nessuna chiamata reale ai giudizi tipizzati: con ABM_TYPESAFE_API_KEY
    nella shell di sviluppo, `semantic_judge.ask` interrogava il servizio vero
    e il verdetto live scavalcava il client LLM finto dei test. Chi prova il
    motore tipizzato imposta la sua chiave finta e stubba il client."""
    monkeypatch.delenv("ABM_TYPESAFE_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _no_live_denoise(monkeypatch):
    """Nessun ZipEnhancer vero: i campioni dei test sono byte finti, e il
    processo figlio caricherebbe torch a ogni demo. Chi prova la pulizia
    rimette la variabile e sostituisce `voice_denoise.clean`."""
    monkeypatch.setenv("ABM_VOICE_CLONE_DENOISE", "0")


@pytest.fixture
def reset_backend_cache():
    """Reset cache backend Gemini tra test (module-level state)."""
    import gemini_tts as gt
    gt._BACKEND = {}
    gt._available = None
    gt._clients_by_location = {}
    yield
    gt._BACKEND = {}
    gt._available = None
    gt._clients_by_location = {}


def _recent_months(n):
    """Mese corrente e i precedenti: /admin/log-activity apre su `now()`."""
    y, m = datetime.now().year, datetime.now().month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


@pytest.fixture(scope="session")
def admin_log_page(tmp_path_factory):
    """HTML di /admin/log-activity, reso una sola volta su una SCRIPT_DIR finta.

    La vista costruisce una card per ogni sessione del mese corrente: sul
    checkout di sviluppo, dove finiscono copie dei log di produzione (14 MB,
    17k sessioni), ogni render costa decine di secondi. I test guardano solo
    il markup e il JS della pagina, quindi bastano tre log minuscoli.
    """
    import audiobook_app

    d = tmp_path_factory.mktemp("adminlogs")
    for i, m in enumerate(_recent_months(3)):
        line = (f'j1 # {m}-01 10:00:00 # "a.epub" # COMPLETE # cidA # 1.1.1.1'
                ' # it-IT-DiegoNeural # it # web\n')
        (d / f"activity_{m}.log").write_text(line if i == 0 else "", encoding="utf-8")
    with patch.object(audiobook_app, "SCRIPT_DIR", d), \
         patch.object(audiobook_app, "ADMIN_TOKEN", "tok-test"), \
         patch("audiobook_app._admin_auth_ok", return_value=True):
        r = audiobook_app.app.test_client().get("/admin/log-activity")
    assert r.status_code == 200
    return r.get_data(as_text=True)
