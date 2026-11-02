"""Guardia sulla cartella dati (incidente 2026-11-02): in produzione
(`ABM_BASE_URL` https pubblico) l'avvio si rifiuta se `ABM_DATA_DIR` manca,
non esiste o e' vuota; in locale e nei test il default resta lecito."""
import os
import pathlib
import subprocess
import sys

import pytest

import fileio
from env_utils import is_public_https_url

PROD = "https://audiobook-maker.com"


@pytest.mark.parametrize("base,ok", [
    ("https://audiobook-maker.com", True),
    ("https://audiobook-maker.com/", True),
    ("http://audiobook-maker.com", False),
    ("http://localhost:5601", False),
    ("https://localhost:5601", False),
    ("https://127.0.0.1", False),
    ("https://app.localhost", False),
    ("https://staging.test", False),
    ("", False),
    (None, False),
])
def test_is_public_https_url(base, ok):
    assert is_public_https_url(base) is ok


def test_not_production_never_complains(monkeypatch):
    monkeypatch.setenv("ABM_BASE_URL", "http://localhost:5601")
    monkeypatch.delenv("ABM_DATA_DIR", raising=False)
    assert fileio.data_dir_problem() is None


def test_production_without_data_dir(monkeypatch):
    monkeypatch.setenv("ABM_BASE_URL", PROD)
    monkeypatch.delenv("ABM_DATA_DIR", raising=False)
    assert "non impostata" in fileio.data_dir_problem()
    monkeypatch.setenv("ABM_DATA_DIR", "   ")
    assert "non impostata" in fileio.data_dir_problem()


def test_production_missing_empty_and_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_BASE_URL", PROD)
    monkeypatch.delenv("ABM_DATA_DIR_ALLOW_EMPTY", raising=False)
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path / "nope"))
    assert "non esiste" in fileio.data_dir_problem()
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    assert "vuota" in fileio.data_dir_problem()
    monkeypatch.setenv("ABM_DATA_DIR_ALLOW_EMPTY", "1")
    assert fileio.data_dir_problem() is None
    monkeypatch.delenv("ABM_DATA_DIR_ALLOW_EMPTY")
    (tmp_path / "_payments.json").write_text("{}", encoding="utf-8")
    assert fileio.data_dir_problem() is None


def test_app_refuses_to_start_in_production_without_data_dir(tmp_path):
    """Avvio vero in un processo separato: exit 1 e messaggio FATALE, prima di
    creare la cartella di default."""
    repo = pathlib.Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k != "ABM_DATA_DIR"}
    env.update(ABM_BASE_URL=PROD, ABM_ADMIN_TOKEN="x", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-c", "import audiobook_app"], cwd=repo, env=env,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 1, r.stderr[-2000:]
    assert "FATALE: ABM_DATA_DIR non impostata" in r.stderr
