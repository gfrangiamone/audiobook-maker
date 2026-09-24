"""CLI scripts/activity_db.py: parity, sync dei mesi chiusi, bench."""
import importlib.util
import os
from datetime import datetime
from pathlib import Path

import pytest

import activity_log

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "activity_db.py"
_spec = importlib.util.spec_from_file_location("activity_db_cli", _SCRIPT)
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def _line(job, ts, op):
    return f'{job} # {ts} # "a.epub" # {op} # c # 1.1.1.1 # v # it # web'


@pytest.fixture
def d(tmp_path, monkeypatch):
    monkeypatch.delenv("ABM_ACTIVITY_DB", raising=False)
    prev = activity_log._log_dir
    activity_log.reset()
    yield tmp_path
    activity_log.reset()
    activity_log.configure(prev)


def test_sync_salta_il_mese_corrente_e_parity(d, capsys):
    (d / "activity_2026-07.log").write_text(
        _line("J1", "2026-07-01 10:00:00", "COMPLETE") + "\n", encoding="utf-8")
    cur = datetime.now().strftime("%Y-%m")
    (d / f"activity_{cur}.log").write_text(
        _line("J2", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "COMPLETE") + "\n",
        encoding="utf-8")
    assert cli.main(["sync", "--dir", str(d)]) == 0
    out = capsys.readouterr().out
    assert "2026-07 ricostruito" in out and f"{cur} saltato" in out
    assert cli.main(["parity", "--dir", str(d), "--month", "2026-07"]) == 0
    assert cli.main(["parity", "--dir", str(d), "--month", cur]) == 1
    assert f"{cur} COMPLETE: file=1 db=0" in capsys.readouterr().out


def test_parity_mese_non_valido(d):
    with pytest.raises(SystemExit):
        cli.main(["parity", "--dir", str(d), "--month", "2026-7"])


def test_bench_stampa_i_due_modi_e_ripristina_env(d, capsys, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "db")
    assert cli.main(["bench", "--dir", str(d), "-n", "5"]) == 0
    out = capsys.readouterr().out
    assert "off: n=5" in out and "dual: n=5" in out
    assert os.environ["ABM_ACTIVITY_DB"] == "db"
    assert [p.name for p in d.iterdir()] == []        # cartella di lavoro rimossa


def test_sync_continua_dopo_errore_su_un_mese(d, capsys, monkeypatch):
    (d / "activity_2026-06.log").write_text(
        _line("J1", "2026-06-01 10:00:00", "COMPLETE") + "\n", encoding="utf-8")
    (d / "activity_2026-07.log").write_text(
        _line("J2", "2026-07-01 10:00:00", "COMPLETE") + "\n", encoding="utf-8")

    real_sync_month = activity_log.sync_month

    def _boom(ym, force=False):
        if ym == "2026-06":
            raise RuntimeError("db bloccato")
        return real_sync_month(ym, force=force)

    monkeypatch.setattr(activity_log, "sync_month", _boom)
    assert cli.main(["sync", "--dir", str(d)]) == 1
    out = capsys.readouterr().out
    assert "2026-06 errore: db bloccato" in out
    assert "2026-07 ricostruito" in out
