"""activity_log con activity.db: modi, doppia scrittura, dedup sul DB, sync."""
from datetime import datetime

import pytest

import activity_db
import activity_log


@pytest.fixture
def ddir(tmp_path, monkeypatch):
    monkeypatch.delenv("ABM_ACTIVITY_DB", raising=False)
    prev = activity_log._log_dir
    activity_log.configure(lambda: tmp_path)
    activity_log.reset()
    yield tmp_path
    activity_log.reset()
    activity_log.configure(prev)


def _ym():
    return datetime.now().strftime("%Y-%m")


def _file(d, ym):
    return [tuple(r) for r in activity_log.file_rows(d / f"activity_{ym}.log")]


def _db(d, ym):
    c = activity_db.connect(d / activity_db.DB_FILENAME)
    try:
        return list(activity_db.select_rows(c, ym, ym))
    finally:
        c.close()


def _line(job, ts, op, fn="a.epub", voice="it-IT-X", lang="it"):
    return f'{job} # {ts} # "{fn}" # {op} # c # 1.1.1.1 # {voice} # {lang} # web'


def test_mode_letto_a_ogni_chiamata(ddir, monkeypatch):
    assert activity_log.mode() == "off"
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    assert activity_log.mode() == "dual"
    monkeypatch.setenv("ABM_ACTIVITY_DB", " DB ")
    assert activity_log.mode() == "db"
    monkeypatch.setenv("ABM_ACTIVITY_DB", "boh")
    assert activity_log.mode() == "off"


def test_off_non_crea_il_db(ddir):
    activity_log.log("J1", "a.epub", "GENERATE")
    assert not (ddir / activity_db.DB_FILENAME).exists()
    assert activity_log.sync_all() == 0


def test_dual_file_e_db_identici(ddir, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    activity_log.log("J1", "Saga # 2.epub", "GENERATE", client_id="c1", ip="1.2.3.4",
                     voice="it-IT-X", lang="it", epoch=1)
    activity_log.log("J1", "Saga # 2.epub", "M4B_PROGRESS", voice="size_mb=3 pct=50")
    activity_log.log("", "", "ADMIN_VOUCHER_CREATE:gift", ip="9.9.9.9",
                     voice="AB12...", lang="a@b.it")
    activity_log.log("J1", "a.epub", "DOWNLOAD")
    activity_log.log("J1", "a.epub", "DOWNLOAD")                     # dedup
    ym = _ym()
    assert len(_file(ddir, ym)) == 4
    assert _db(ddir, ym) == _file(ddir, ym)
    assert activity_log.parity(ym) == {}


def test_dual_ripetizione_dopo_riavvio_entra_anche_nel_db(ddir, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    activity_log.reset()          # riavvio: il set in RAM riparte dal file,
    activity_log.init_dedup()     # senza epoca -> la riga si riscrive
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    ym = _ym()
    assert [r[3] for r in _file(ddir, ym)] == ["GENERATE", "GENERATE"]
    assert _db(ddir, ym) == _file(ddir, ym)


def test_dual_db_rotto_non_ferma_il_file(ddir, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    (ddir / activity_db.DB_FILENAME).mkdir()     # connect fallisce
    activity_log.log("J1", "a.epub", "COMPLETE")
    assert [r[3] for r in _file(ddir, _ym())] == ["COMPLETE"]
    assert activity_log.db_stats()["writes"] == 0


def test_db_dedup_sul_db_e_file_solo_per_le_righe_nuove(ddir, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "db")
    activity_log.log("J1", "a.epub", "DOWNLOAD")
    activity_log.log("J1", "a.epub", "DOWNLOAD")
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    activity_log.log("J1", "a.epub", "GENERATE", epoch=2)
    activity_log.log("", "", "VOUCHER_ATTEMPT", lang="invalid")
    activity_log.log("", "", "VOUCHER_ATTEMPT", lang="invalid")
    ym = _ym()
    expected = ["DOWNLOAD", "GENERATE", "GENERATE", "VOUCHER_ATTEMPT", "VOUCHER_ATTEMPT"]
    assert [r[3] for r in _file(ddir, ym)] == expected
    assert _db(ddir, ym) == _file(ddir, ym)


def test_db_ricorda_l_epoca_dopo_il_riavvio(ddir, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "db")
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    activity_log.reset()
    activity_log.init_dedup()
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    assert [r[3] for r in _file(ddir, _ym())] == ["GENERATE"]


def test_db_irraggiungibile_scrive_comunque_il_file(ddir, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "db")
    (ddir / activity_db.DB_FILENAME).mkdir()
    activity_log.log("J1", "a.epub", "COMPLETE")
    activity_log.log("J1", "a.epub", "COMPLETE")   # senza DB nessun dedup
    assert [r[3] for r in _file(ddir, _ym())] == ["COMPLETE", "COMPLETE"]


def test_sync_month_ricostruisce_e_poi_salta(ddir):
    p = ddir / "activity_2026-07.log"
    lines = [_line("J1", "2026-07-01 10:00:00", "GENERATE"),
             _line("J1", "2026-07-01 11:00:00", "GENERATE"),     # ripetizione storica
             _line("J2", "2026-07-02 10:00:00", "M4B_END", voice="size_mb=1"),
             _line("", "2026-07-03 10:00:00", "VOUCHER_ATTEMPT", fn="", lang="ok")]
    p.write_text("".join(l + "\n" for l in lines), encoding="utf-8")
    assert activity_log.sync_month("2026-07") is True
    assert _db(ddir, "2026-07") == _file(ddir, "2026-07")
    assert activity_log.sync_month("2026-07") is False           # stessa dimensione
    with open(p, "a", encoding="utf-8") as f:
        f.write(_line("J3", "2026-07-04 10:00:00", "COMPLETE") + "\n")
    assert activity_log.sync_month("2026-07") is True
    assert activity_log.parity("2026-07") == {}


def test_sync_month_conteggi_uguali_non_ricostruisce(ddir):
    p = ddir / "activity_2026-07.log"
    p.write_text(_line("J1", "2026-07-01 10:00:00", "COMPLETE") + "\n", encoding="utf-8")
    assert activity_log.sync_month("2026-07") is True
    c = activity_db.connect(ddir / activity_db.DB_FILENAME)
    try:
        c.execute("DELETE FROM sync_state")          # dimensione dimenticata
        first_id = c.execute("SELECT id FROM events").fetchone()[0]
    finally:
        c.close()
    assert activity_log.sync_month("2026-07") is False   # conta e ritrova 1 = 1
    c = activity_db.connect(ddir / activity_db.DB_FILENAME)
    try:
        assert c.execute("SELECT id FROM events").fetchone()[0] == first_id
    finally:
        c.close()


def test_sync_month_forzato_e_mese_non_valido(ddir):
    p = ddir / "activity_2026-07.log"
    p.write_text(_line("J1", "2026-07-01 10:00:00", "COMPLETE") + "\n", encoding="utf-8")
    activity_log.sync_month("2026-07")
    assert activity_log.sync_month("2026-07", force=True) is True
    assert activity_log.sync_month("../2026-07") is False
    assert activity_log.sync_month("2026-06") is False            # file assente


def test_sync_all_dal_vecchio_al_corrente_e_pronto(ddir, monkeypatch):
    (ddir / "activity_2026-06.log").write_text(
        _line("A", "2026-06-01 10:00:00", "COMPLETE") + "\n", encoding="utf-8")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    (ddir / f"activity_{_ym()}.log").write_text(
        _line("B", ts, "COMPLETE") + "\n", encoding="utf-8")
    assert activity_log.sync_all() == 0 and not activity_log._db_ready.is_set()  # off
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    assert activity_log.sync_all() == 2
    assert activity_log._db_ready.is_set()
    assert activity_log.sync_all() == 0


def test_parity_segnala_le_differenze(ddir, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    activity_log.log("J1", "a.epub", "GENERATE")
    ym = _ym()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ddir / f"activity_{ym}.log", "a", encoding="utf-8") as f:
        f.write(_line("J2", ts, "COMPLETE") + "\n")
    assert activity_log.parity(ym) == {"COMPLETE": (1, 0)}
    with pytest.raises(ValueError):
        activity_log.parity("2026-8")


def test_parity_senza_db(ddir):
    (ddir / "activity_2026-07.log").write_text(
        _line("J1", "2026-07-01 10:00:00", "COMPLETE") + "\n", encoding="utf-8")
    assert activity_log.parity("2026-07") == {"COMPLETE": (1, 0)}
    assert not (ddir / activity_db.DB_FILENAME).exists()


def test_scrittura_lenta_segnalata(ddir, monkeypatch, capsys):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    monkeypatch.setattr(activity_log, "_SLOW_DB_MS", -1.0)
    activity_log.log("J1", "a.epub", "GENERATE")
    assert "scrittura DB lenta: GENERATE" in capsys.readouterr().out
    st = activity_log.db_stats()
    assert st["writes"] == 1 and st["max_ms"] >= st["avg_ms"] >= 0.0
