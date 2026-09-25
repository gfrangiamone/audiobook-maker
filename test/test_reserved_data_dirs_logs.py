"""Log attivita' e campioni vocali non finiscono mai nelle pulizie automatiche.

In prod il business log si sposta in `data/logs` (ABM_ACTIVITY_LOG_DIR): file
mensili + activity.db dentro il data dir, accanto alle cartelle dei job. Lo
sweep delle cartelle orfane la scambierebbe per una job dir abbandonata e la
cancellerebbe da disco e da cold, come successo alle voci il 12/09/2026.
"""
import importlib

import pytest


def _app(monkeypatch, tmp_path, log_dir=None):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    if log_dir is None:
        monkeypatch.delenv("ABM_ACTIVITY_LOG_DIR", raising=False)
    else:
        monkeypatch.setenv("ABM_ACTIVITY_LOG_DIR", str(log_dir))
    import audiobook_app
    importlib.reload(audiobook_app)
    return audiobook_app


def test_data_logs_non_e_una_job_dir(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path, tmp_path / "logs")
    (tmp_path / "logs").mkdir()
    (tmp_path / "jobABC").mkdir()
    assert app._is_job_dir(tmp_path / "logs") is False
    assert app._is_job_dir(tmp_path / "jobABC") is True


def test_logs_resta_riservata_anche_senza_env(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    (tmp_path / "logs").mkdir()
    assert app._is_job_dir(tmp_path / "logs") is False


def test_log_dir_con_nome_qualsiasi_nel_data_dir_e_riservata(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path, tmp_path / "business_log")
    (tmp_path / "business_log").mkdir()
    assert app._is_job_dir(tmp_path / "business_log") is False


def test_il_cold_delete_rifiuta_il_prefisso_dei_log(monkeypatch, tmp_path):
    import storage_backend
    app = _app(monkeypatch, tmp_path, tmp_path / "business_log")
    cancellati = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: cancellati.append(p))
    app._delete_cold_for_job("logs")
    app._delete_cold_for_job("business_log")
    assert cancellati == []


def test_sweep_orfane_non_tocca_i_log(monkeypatch, tmp_path):
    """Simula il ciclo: tutte le scansioni del data dir passano da _is_job_dir,
    quindi basta che nessuna voce riservata sia considerata job dir."""
    app = _app(monkeypatch, tmp_path, tmp_path / "logs")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "activity_2026-09.log").write_text("x", encoding="utf-8")
    (logs / "activity.db").write_bytes(b"x")
    job_dirs = [e.name for e in tmp_path.iterdir() if app._is_job_dir(e)]
    assert "logs" not in job_dirs


@pytest.mark.parametrize("prefisso", ["", "/", "user_voices/", "user_voices",
                                      "voices/", "accounts/", "logs/", "/logs/"])
def test_delete_prefix_rifiuta_radici_protette(monkeypatch, prefisso):
    import storage_backend
    chiamato = []
    monkeypatch.setattr(storage_backend, "_get_client", lambda: chiamato.append(1))
    with pytest.raises(ValueError):
        storage_backend.delete_prefix(prefisso)
    assert chiamato == []


def test_delete_prefix_ammette_le_sottocartelle(monkeypatch):
    import storage_backend

    class _Pag:
        def paginate(self, **kw):
            return [{"Contents": [{"Key": kw["Prefix"] + "a"}]}]

    class _Client:
        def __init__(self):
            self.cancellati = []

        def get_paginator(self, _):
            return _Pag()

        def delete_objects(self, Bucket, Delete):
            self.cancellati += [o["Key"] for o in Delete["Objects"]]

    client = _Client()
    monkeypatch.setattr(storage_backend, "_get_client", lambda: client)
    storage_backend.delete_prefix("user_voices/abc123/")
    storage_backend.delete_prefix("jobXYZ/")
    assert len(client.cancellati) == 2
    assert client.cancellati[0].endswith("user_voices/abc123/a")
    assert client.cancellati[1].endswith("jobXYZ/a")


@pytest.mark.parametrize("token", ["", None, ".", "..", "../x", "a/b", "a\\b"])
def test_remove_files_rifiuta_token_che_punta_alla_radice(monkeypatch, token):
    import shutil
    import storage_backend
    import voice_clone
    rimossi, cancellati = [], []
    monkeypatch.setattr(shutil, "rmtree", lambda p, **kw: rimossi.append(p))
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: cancellati.append(p))
    voice_clone.remove_files({"id": "vc_x", "token": token})
    assert rimossi == [] and cancellati == []


def test_remove_files_con_token_valido_cancella_solo_la_voce(monkeypatch):
    import shutil
    import storage_backend
    import voice_clone
    rimossi, cancellati = [], []
    monkeypatch.setattr(shutil, "rmtree", lambda p, **kw: rimossi.append(p))
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: cancellati.append(p))
    voice_clone.remove_files({"id": "vc_x", "token": "ab" * 16})
    assert len(rimossi) == 1 and rimossi[0].endswith("ab" * 16)
    assert cancellati == [f"user_voices/{'ab' * 16}/"]
