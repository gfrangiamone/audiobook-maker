"""migration_recover_prep: consegne lette dai log in SCRIPT_DIR e nella data dir."""
import importlib.util
from pathlib import Path

_SCRIPT = (Path(__file__).resolve().parent.parent / "scripts" / "migration"
           / "migration_recover_prep.py")
_spec = importlib.util.spec_from_file_location("migration_recover_prep", _SCRIPT)
mrp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mrp)


def _line(job, op):
    return f'{job} # 2026-08-01 10:00:00 # "a # b.epub" # {op} # c # 1.1.1.1 # v # it # web\n'


def test_unione_delle_due_cartelle(tmp_path):
    old, new = tmp_path / "app", tmp_path / "data"
    old.mkdir()
    new.mkdir()
    (old / "activity_2026-07.log").write_text(_line("J1", "EMAIL_SENT"), encoding="utf-8")
    (new / "activity_2026-08.log").write_text(
        _line("J2", "TR_EMAIL_SENT") + _line("J3", "GENERATE"), encoding="utf-8")
    assert mrp.delivered_job_ids(str(new), str(old)) == {"J1", "J2"}


def test_una_cartella_assente_non_avvisa(tmp_path, capsys):
    new = tmp_path / "data"
    new.mkdir()
    (new / "activity_2026-08.log").write_text(_line("J2", "EMAIL_SENT"), encoding="utf-8")
    assert mrp.delivered_job_ids(str(new), str(tmp_path / "manca")) == {"J2"}
    assert "ATTENZIONE" not in capsys.readouterr().err


def test_tutte_assenti_avvisa(tmp_path, capsys):
    assert mrp.delivered_job_ids(str(tmp_path / "a"), str(tmp_path / "b")) == set()
    assert "ATTENZIONE" in capsys.readouterr().err
