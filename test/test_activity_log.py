"""Contratto dell'API pubblica di activity_log (fase 1: backend file di testo).

In fase 2 questi test verranno parametrizzati anche sul backend SQLite: vanno
scritti solo contro le funzioni pubbliche, mai contro il formato del file,
salvo dove il formato e' esso stesso il contratto (andata e ritorno).
"""
from datetime import datetime, timedelta

import pytest

import activity_log
from activity_log import Row


def _ym(d):
    return d.strftime("%Y-%m")


def _prev_ym(d):
    first = d.replace(day=1)
    return _ym(first - timedelta(days=1))


def _write(d, ym, lines, raw=None):
    p = d / f"activity_{ym}.log"
    if raw is not None:
        p.write_bytes(raw)
    else:
        p.write_text("".join(l + "\n" for l in lines), encoding="utf-8")
    return p


def _line(job, ts, op, fn="a.epub", cid="c", ip="1.1.1.1", voice="it-IT-X",
          lang="it", plat="web"):
    return f'{job} # {ts} # "{fn}" # {op} # {cid} # {ip} # {voice} # {lang} # {plat}'


@pytest.fixture
def log_dir(tmp_path):
    prev = activity_log._log_dir
    activity_log.configure(lambda: tmp_path)
    activity_log.reset()
    yield tmp_path
    activity_log.reset()
    activity_log.configure(prev)


def _ops_now():
    return [r.op for r in activity_log.month_rows(_ym(datetime.now()))]


# ---------------------------------------------------------------- scrittura

def test_andata_e_ritorno_con_cancelletto_e_platform_vuota(log_dir):
    activity_log.log("J1", "Saga # 2.epub", "GENERATE", client_id="c1",
                     ip="1.2.3.4", voice="it-IT-X", lang="it")
    rows = list(activity_log.month_rows(_ym(datetime.now())))
    assert len(rows) == 1
    assert rows[0] == Row("J1", rows[0].ts, "Saga # 2.epub", "GENERATE", "c1",
                          "1.2.3.4", "it-IT-X", "it", "")
    datetime.strptime(rows[0].ts, "%Y-%m-%d %H:%M:%S")


def test_stessa_chiave_scritta_una_volta(log_dir):
    activity_log.log("J1", "a.epub", "DOWNLOAD")
    activity_log.log("J1", "a.epub", "DOWNLOAD")
    assert _ops_now() == ["DOWNLOAD"]


def test_epoch_diverse_due_righe(log_dir):
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    activity_log.log("J1", "a.epub", "GENERATE", epoch=2)
    assert _ops_now() == ["GENERATE", "GENERATE"]


def test_c1_job_id_vuoto_mai_deduplicato(log_dir):
    activity_log.log("", "", "VOUCHER_ATTEMPT", ip="1.1.1.1", voice="AB12...", lang="invalid")
    activity_log.log("", "", "VOUCHER_ATTEMPT", ip="1.1.1.1", voice="CD34...", lang="invalid")
    rows = list(activity_log.month_rows(_ym(datetime.now())))
    assert [r.op for r in rows] == ["VOUCHER_ATTEMPT", "VOUCHER_ATTEMPT"]
    assert all(r.job_id == "" for r in rows)


def test_c2_init_dedup_ricostruisce_le_chiavi_giuste(log_dir):
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    _write(log_dir, _ym(now), [
        f' # {ts} # "" # VOUCHER_ATTEMPT #  # 1.1.1.1 # AB12... # ok # ',
        _line("J1", ts, "GENERATE", fn="a # b.epub"),
    ])
    activity_log.init_dedup()
    activity_log.log("J1", "a # b.epub", "GENERATE")          # gia' nel file
    activity_log.log("", "", "VOUCHER_ATTEMPT", ip="1.1.1.1")  # C1: si scrive
    assert _ops_now().count("GENERATE") == 1
    assert _ops_now().count("VOUCHER_ATTEMPT") == 2


def test_cambio_mese_azzera_il_dedup(log_dir):
    activity_log.log("J1", "a.epub", "GENERATE")
    # Simula un processo acceso dal mese precedente: il set appartiene a un
    # altro mese e va buttato alla prima scrittura del mese nuovo.
    activity_log._month = "2000-01"
    activity_log.log("J1", "a.epub", "GENERATE")
    assert _ops_now() == ["GENERATE", "GENERATE"]


def test_log_non_solleva_e_riprova_dopo_un_errore(log_dir, tmp_path):
    missing = tmp_path / "manca"
    activity_log.configure(lambda: missing)
    activity_log.log("J1", "a.epub", "COMPLETE")  # cartella assente: nessuna eccezione
    missing.mkdir()
    activity_log.log("J1", "a.epub", "COMPLETE")  # la chiave non era entrata nel set
    assert [r.op for r in activity_log.month_rows(_ym(datetime.now()))] == ["COMPLETE"]


def test_log_senza_configurazione_non_solleva(log_dir):
    activity_log.configure(None)
    activity_log.log("J1", "a.epub", "COMPLETE")
    assert list(activity_log.month_rows(_ym(datetime.now()))) == []


# ---------------------------------------------------------------- parsing

def test_split_line_tollera_il_cancelletto_nel_nome_file():
    r = activity_log.split_line(_line("j1", "2026-08-01 10:00:00", "COMPLETE",
                                      fn="Riftwar Saga # 2 Empire.epub"))
    assert r.filename == "Riftwar Saga # 2 Empire.epub" and r.op == "COMPLETE"
    assert r.platform == "web"


def test_split_line_riga_corta_completata_a_destra():
    r = activity_log.split_line('job1 # 2026-08-01 10:00:00 # "x.epub" # GENERATE')
    assert r.job_id == "job1" and r.op == "GENERATE"
    assert r.client_id == "" and r.platform == ""


def test_split_line_riga_incompleta_scartata():
    assert activity_log.split_line("solo testo") is None
    assert activity_log.split_line("") is None


def test_split_line_regge_il_campo_finale_vuoto():
    line = ('j1 # 2026-08-01 10:00:00 # "a.epub" # COMPLETE # cid1 # 1.2.3.4'
            ' # en-US-GuyNeural # en # ')
    assert activity_log.split_line(line.strip())[7:] == ("en", "")
    assert activity_log.split_line(line + "\n")[7:] == ("en", "")


def test_split_line_cancelletto_nel_titolo_e_platform_vuota():
    line = ('j1 # 2026-08-01 10:00:00 # "Riftwar # 2.epub" # GENERATE # cid1'
            ' # 1.2.3.4 # gemini:flash31:Despina # de # ')
    r = activity_log.split_line(line.strip())
    assert r.filename == "Riftwar # 2.epub" and r.op == "GENERATE"
    assert r.lang == "de" and r.platform == ""


def test_split_line_riga_di_sistema_a_job_vuoto():
    r = activity_log.split_line(' # 2026-08-01 10:00:00 # "" # ADMIN_TTS_PROBE #  # 9.9.9.9 # k # avviata=True # \n')
    assert r.job_id == "" and r.ts == "2026-08-01 10:00:00"
    assert r.op == "ADMIN_TTS_PROBE" and r.ip == "9.9.9.9"


# ---------------------------------------------------------------- lettura

def test_file_rows_file_assente(tmp_path):
    assert list(activity_log.file_rows(tmp_path / "manca.log")) == []


def test_month_rows_tollera_byte_non_utf8_e_righe_rotte(log_dir):
    raw = (b"\xff\xfe spazzatura\n\n"
           + _line("J1", "2026-08-01 10:00:00", "COMPLETE").encode("utf-8") + b"\n")
    _write(log_dir, "2026-08", None, raw=raw)
    rows = list(activity_log.month_rows("2026-08"))
    assert [r.job_id for r in rows if r.op == "COMPLETE"] == ["J1"]


@pytest.mark.parametrize("ym", ["", "2026-8", "../2026-08", "2026-08/../../x", "agosto"])
def test_ym_non_valido(log_dir, ym):
    _write(log_dir, "2026-08", [_line("J1", "2026-08-01 10:00:00", "COMPLETE")])
    assert list(activity_log.month_rows(ym)) == []
    assert activity_log.fingerprint(ym) is None


def test_iter_rows_attraversa_i_mesi_e_filtra(log_dir):
    _write(log_dir, "2026-07", [
        _line("A", "2026-07-30 10:00:00", "COMPLETE"),   # prima di since
        _line("B", "2026-07-31 13:00:00", "COMPLETE"),
        _line("C", "2026-07-31 14:00:00", "GENERATE"),   # op esclusa
    ])
    _write(log_dir, "2026-08", [
        _line("D", "2026-08-01 09:00:00", "OPT_COMPLETE"),
        _line("E", "2026-08-02 00:00:00", "COMPLETE"),   # == until: escluso
    ])
    got = [r.job_id for r in activity_log.iter_rows(
        datetime(2026, 7, 31, 12), until=datetime(2026, 8, 2),
        ops={"COMPLETE", "OPT_COMPLETE"})]
    assert got == ["B", "D"]


def test_iter_rows_senza_until_arriva_a_oggi(log_dir):
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    _write(log_dir, _ym(now), [_line("N", ts, "COMPLETE")])
    got = [r.job_id for r in activity_log.iter_rows(now.replace(day=1, hour=0, minute=0,
                                                                  second=0, microsecond=0))]
    assert got == ["N"]


def test_months_ordinati_e_solo_nomi_validi(log_dir):
    for name in ("activity_2026-07.log", "activity_2026-08.log", "activity_xx.log",
                 "altro.log", "activity_2026-08.log.bak"):
        (log_dir / name).write_text("", encoding="utf-8")
    assert activity_log.months() == ["2026-08", "2026-07"]


def test_months_senza_configurazione(log_dir):
    activity_log.configure(None)
    assert activity_log.months() == []


def test_fingerprint_cambia_dopo_una_scrittura(log_dir):
    ym = _ym(datetime.now())
    assert activity_log.fingerprint(ym) is None
    activity_log.log("J1", "a.epub", "GENERATE")
    fp1 = activity_log.fingerprint(ym)
    activity_log.log("J2", "a.epub", "GENERATE")
    fp2 = activity_log.fingerprint(ym)
    assert fp1 is not None and fp2 is not None and fp1 != fp2


def test_delivered_ids_su_piu_mesi_con_cache(log_dir):
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    _write(log_dir, _prev_ym(now), [_line("OLD", "2000-01-01 00:00:00", "COMPLETE")])
    _write(log_dir, _ym(now), [
        _line("J1", ts, "COMPLETE"),
        _line("J2", ts, "OPT_COMPLETE", fn="Saga # 2.epub"),  # '#' nel titolo
        _line("J3", ts, "GENERATE"),
    ])
    d = activity_log.delivered_ids(months=2)
    assert d["complete"] == {"OLD", "J1"}
    assert d["opt_complete"] == {"J2"}

    with open(log_dir / f"activity_{_ym(now)}.log", "a", encoding="utf-8") as f:
        f.write(_line("J4", ts, "COMPLETE") + "\n")
    assert "J4" not in activity_log.delivered_ids(months=2)["complete"]  # cache 300 s
    activity_log.reset()
    assert "J4" in activity_log.delivered_ids(months=2)["complete"]


def test_delivered_ids_un_mese_solo(log_dir):
    now = datetime.now()
    _write(log_dir, _prev_ym(now), [_line("OLD", "2000-01-01 00:00:00", "COMPLETE")])
    assert activity_log.delivered_ids(months=1)["complete"] == set()
