"""Token scaduto di un job la cui dir locale e' gia' sparita: il cold va purgato.

Incidente del 20/10/2026: un cron di sistema cancellava le job dir dopo 25 ore,
fuori dall'app. Dopo un restart il job non e' piu' in memoria e il ramo
token-orphan del cleanup agiva solo se `job_dir.exists()`: alla scadenza del
token gli oggetti su R2 restavano per sempre (707 prefissi, 103 GB).
"""
import time

import cleanup


def _setup(fresh_app, monkeypatch, tmp_path):
    import storage_backend
    import token_store
    fresh_app(env={"ABM_DATA_DIR": str(tmp_path)})
    deleted = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: deleted.append(p))
    monkeypatch.setattr(token_store, "download_tokens", {})
    monkeypatch.setattr(token_store, "save_tokens", lambda: None)
    return token_store, deleted


def _token(job_id, age_sec, now):
    return {"job_id": job_id, "created_at": now - age_sec}


def test_cold_purgato_quando_la_dir_locale_e_gia_assente(fresh_app, monkeypatch, tmp_path):
    tk, deleted = _setup(fresh_app, monkeypatch, tmp_path)
    now = time.time()
    tk.download_tokens["t1"] = _token("jobGone", 30 * 86400, now)
    assert cleanup._expire_download_tokens(now) == 1
    assert deleted == ["jobGone/"]
    assert tk.download_tokens == {}


def test_cold_preservato_se_un_token_fratello_e_vivo(fresh_app, monkeypatch, tmp_path):
    tk, deleted = _setup(fresh_app, monkeypatch, tmp_path)
    now = time.time()
    tk.download_tokens["old"] = _token("jobGone", 30 * 86400, now)
    tk.download_tokens["fresh"] = _token("jobGone", 60, now)
    cleanup._expire_download_tokens(now)
    assert deleted == []
    assert list(tk.download_tokens) == ["fresh"]


def test_job_in_memoria_non_tocca_il_cold(fresh_app, monkeypatch, tmp_path):
    import audiobook_app
    tk, deleted = _setup(fresh_app, monkeypatch, tmp_path)
    now = time.time()
    monkeypatch.setitem(audiobook_app.jobs, "jobLive", {"status": "done"})
    tk.download_tokens["t1"] = _token("jobLive", 30 * 86400, now)
    cleanup._expire_download_tokens(now)
    assert deleted == []


def test_job_archiviato_non_perde_il_cold(fresh_app, monkeypatch, tmp_path):
    import accounts
    tk, deleted = _setup(fresh_app, monkeypatch, tmp_path)
    now = time.time()
    monkeypatch.setattr(accounts, "archive_protects", lambda jid: jid == "jobArch")
    tk.download_tokens["t1"] = _token("jobArch", 30 * 86400, now)
    cleanup._expire_download_tokens(now)
    assert deleted == []


def test_dir_presente_resta_il_ramo_token_orphan(fresh_app, monkeypatch, tmp_path):
    tk, deleted = _setup(fresh_app, monkeypatch, tmp_path)
    now = time.time()
    (tmp_path / "jobHere").mkdir()
    tk.download_tokens["t1"] = _token("jobHere", 30 * 86400, now)
    cleanup._expire_download_tokens(now)
    assert deleted == ["jobHere/"]
    assert not (tmp_path / "jobHere").exists()
