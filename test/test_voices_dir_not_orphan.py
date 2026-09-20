"""La cartella dei campioni vocali non e' una job dir orfana.

Incidente del 12/09/2026: la cartella delle voci (oggi `user_voices/`, allora
`voices/`) vive nel data dir accanto alle cartelle dei job e su R2 sotto il prefisso omonimo. Lo sweep delle cartelle orfane del
cleanup la vedeva come una job dir abbandonata da piu' di due ore e la
cancellava da disco, poi chiamava `_delete_cold_for_job("voices")` che
spazzava via anche l'intero prefisso su cold: campioni e demo di TUTTE le voci
distrutti, con i record ancora in stato `ready` e i file spariti (404 sui
`/api/voice_clone/<id>/demo/...`).
"""
import importlib
import inspect
import re


def _app(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    import audiobook_app
    importlib.reload(audiobook_app)
    return audiobook_app


def test_la_cartella_delle_voci_non_e_una_job_dir(monkeypatch, tmp_path):
    import voice_clone
    app = _app(monkeypatch, tmp_path)
    # l'avvio dell'app la crea gia': e' proprio la cartella incriminata
    (tmp_path / voice_clone.VOICES_DIRNAME).mkdir(exist_ok=True)
    (tmp_path / "jobABC").mkdir()
    (tmp_path / "_interno").mkdir()
    per_nome = {p.name: app._is_job_dir(p) for p in tmp_path.iterdir() if p.is_dir()}
    assert per_nome == {voice_clone.VOICES_DIRNAME: False,
                        "jobABC": True, "_interno": False}


def test_il_cold_delete_rifiuta_il_prefisso_delle_voci(monkeypatch, tmp_path):
    import storage_backend, voice_clone
    app = _app(monkeypatch, tmp_path)
    cancellati = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: cancellati.append(p))
    app._delete_cold_for_job(voice_clone.VOICES_DIRNAME)
    assert cancellati == []
    app._delete_cold_for_job("jobABC")
    assert cancellati == ["jobABC/"]


def test_ogni_scansione_del_data_dir_passa_da_is_job_dir(monkeypatch, tmp_path):
    """Guardia di regressione: chi aggiunge una scansione del data dir non deve
    tornare al vecchio filtro (solo `startswith('_')`), o la cartella delle voci
    ridiventa cancellabile."""
    app = _app(monkeypatch, tmp_path)
    src = inspect.getsource(app)
    for riga in re.findall(r"^.*UPLOAD_DIR\.iterdir\(\).*$", src, re.M):
        assert "for " in riga, riga
    # subito dopo ogni iterdir deve comparire il filtro condiviso
    for blocco in re.findall(r"UPLOAD_DIR\.iterdir\(\):\n(.{0,120})", src):
        assert "_is_job_dir" in blocco, blocco


def test_il_prefisso_r2_delle_voci_e_quello_della_cartella():
    import voice_clone
    assert voice_clone.R2_PREFIX == voice_clone.VOICES_DIRNAME + "/"
    assert voice_clone.VOICES_DIRNAME in _RISERVATE()


def _RISERVATE():
    import audiobook_app
    return audiobook_app._RESERVED_DATA_DIRS


def test_anche_il_nome_storico_della_cartella_resta_protetto(monkeypatch, tmp_path):
    """Una `voices/` rimasta da prima del rename non deve essere cancellata."""
    import storage_backend
    app = _app(monkeypatch, tmp_path)
    (tmp_path / "voices").mkdir(exist_ok=True)
    assert app._is_job_dir(tmp_path / "voices") is False
    cancellati = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: cancellati.append(p))
    app._delete_cold_for_job("voices")
    assert cancellati == []


def test_la_cartella_delle_voci_ha_un_nome_suo():
    """Nel data dir ogni altra cartella e' di un job: il nome deve essere
    inequivocabile, non il generico 'voices' che sembrava un job id."""
    import voice_clone
    assert voice_clone.VOICES_DIRNAME == "user_voices"


def test_il_prefisso_cold_degli_account_e_riservato(monkeypatch, tmp_path):
    """I backup di abm.db vivono su cold sotto `accounts/`: oggi nessuno sweep
    ci arriva (sono file, non cartelle nel data dir), ma il prefisso va
    riservato lo stesso — un `delete_prefix("accounts/")` cancellerebbe le
    copie del database degli account."""
    import storage_backend
    app = _app(monkeypatch, tmp_path)
    assert "accounts" in _RISERVATE()
    (tmp_path / "accounts").mkdir(exist_ok=True)
    assert app._is_job_dir(tmp_path / "accounts") is False
    cancellati = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: cancellati.append(p))
    app._delete_cold_for_job("accounts")
    assert cancellati == []
