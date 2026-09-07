"""La CLI voucher non deve scrivere mentre il servizio e' vivo.

audiobook_app tiene i voucher in RAM e riscrive _vouchers.json a ogni
salvataggio: un voucher creato da CLI a servizio acceso e' invisibile al
pannello, rifiutato al cliente e perso al primo save dell'app
(incidente 07/09/2026).
"""
import importlib.util
import pathlib
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "admin_voucher_cli",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "admin_voucher.py")
cli = importlib.util.module_from_spec(_SPEC)
sys.modules["admin_voucher_cli"] = cli
_SPEC.loader.exec_module(cli)


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_guard_allows_when_no_app_detected(monkeypatch):
    monkeypatch.setattr(cli, "_detect_running_app", lambda: None)
    assert cli._guard_running_app(False) == 0


def test_guard_blocks_when_app_running(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_detect_running_app", lambda: "unita systemd attiva")
    assert cli._guard_running_app(False) != 0
    err = capsys.readouterr().err
    assert "/admin/vouchers" in err, "l'errore deve indicare la via corretta"


def test_force_overrides_with_warning(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_detect_running_app", lambda: "processo vivo")
    monkeypatch.setattr(cli, "_log", lambda *a, **k: None)
    assert cli._guard_running_app(True) == 0
    assert "--force" in capsys.readouterr().err


def test_create_refuses_and_writes_nothing(monkeypatch, tmp_path):
    """Il rifiuto deve avvenire PRIMA di toccare il file."""
    vfile = tmp_path / "_vouchers.json"
    monkeypatch.setattr(cli, "VOUCHERS_FILE", vfile)
    monkeypatch.setattr(cli, "_detect_running_app", lambda: "servizio attivo")
    rc = cli.cmd_create(_Args(email="a@b.com", amount=4.03, days=180,
                              kind="refund", note="", force=False))
    assert rc != 0
    assert not vfile.exists(), "la CLI ha scritto nonostante il servizio acceso"


def test_revoke_refuses_when_app_running(monkeypatch, tmp_path):
    vfile = tmp_path / "_vouchers.json"
    vfile.write_text('{"AAAA-BBBB-CCCC": {"code": "AAAA-BBBB-CCCC"}}', encoding="utf-8")
    monkeypatch.setattr(cli, "VOUCHERS_FILE", vfile)
    monkeypatch.setattr(cli, "_detect_running_app", lambda: "servizio attivo")
    rc = cli.cmd_revoke(_Args(code="AAAA-BBBB-CCCC", reason="", force=False))
    assert rc != 0
    assert "used" not in vfile.read_text(encoding="utf-8")


def test_detection_is_best_effort_without_system_tools(monkeypatch):
    """Senza systemctl/pgrep (sviluppo su Windows) non si inventa un rilevamento."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert cli._detect_running_app() is None


@pytest.mark.parametrize("cmd", ["create", "revoke"])
def test_write_commands_expose_force_flag(cmd):
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "scripts" / "admin_voucher.py").read_text(encoding="utf-8")
    i = src.index(f'sub.add_parser("{cmd}"')
    assert "--force" in src[i:i + 700], f"comando {cmd} senza via d'uscita --force"
