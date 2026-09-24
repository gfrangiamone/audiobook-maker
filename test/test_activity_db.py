"""Contratto di activity_db: schema, mappatura riga <-> colonne, dedup, query."""
import sqlite3

import pytest

import activity_db


def _r(job="J1", ts="2026-08-01 10:00:00", fn="a.epub", op="GENERATE", cid="c",
       ip="1.1.1.1", voice="it-IT-X", lang="it", plat="web"):
    return (job, ts, fn, op, cid, ip, voice, lang, plat)


@pytest.fixture
def conn(tmp_path):
    c = activity_db.connect(tmp_path / activity_db.DB_FILENAME)
    yield c
    c.close()


def _all(conn, ym_from="0000-00", ym_to="9999-99", **kw):
    return list(activity_db.select_rows(conn, ym_from, ym_to, **kw))


# ---------------------------------------------------------------- schema

def test_connect_due_volte_migrazioni_idempotenti(tmp_path):
    p = tmp_path / activity_db.DB_FILENAME
    activity_db.connect(p).close()
    c = activity_db.connect(p)
    try:
        names = [r[0] for r in c.execute("SELECT name FROM schema_migrations")]
        assert names == ["001_events"]
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        c.close()


def test_reader_non_crea_il_file(tmp_path):
    p = tmp_path / "manca.db"
    with pytest.raises(sqlite3.OperationalError):
        activity_db.reader(p)
    assert not p.exists()


def test_reader_non_scrive(conn, tmp_path):
    r = activity_db.reader(tmp_path / activity_db.DB_FILENAME)
    try:
        with pytest.raises(sqlite3.OperationalError):
            r.execute("DELETE FROM events")
    finally:
        r.close()


# ---------------------------------------------------------------- mappatura

ROUND_TRIP = [
    _r(),
    _r(fn="Saga # 2.epub"),
    _r(job="J2", op="M4B_PROGRESS", voice="size_mb=12.5 pct=40"),
    _r(job="", fn="", op="ADMIN_VOUCHER_CREATE:gift", cid="", voice="AB12...", lang="a@b.it", plat=""),
    _r(job="", fn="", op="ADMIN_VOUCHER_REVOKE", voice="AB12...", lang="doppione"),
    _r(job="", fn="", op="VOUCHER_ATTEMPT", voice="CD34...", lang="invalid"),
    _r(job="", fn="", op="VOUCHER_ATTEMPT_BLOCKED:rate", voice="", lang=""),
    _r(job="J3", op="PAYMENT_AMOUNT_MISMATCH", voice="", lang="atteso 5.00"),
    _r(job="vc1", fn="speed=1.1", op="VOICE_CLONE_SPEED", voice="", lang=""),
    _r(job="acct-1234abcd", fn="device=iPhone", op="ACCOUNT_LOGIN", voice="", lang=""),
    _r(job="", fn="", op="STRANA:", voice="", lang=""),        # ':' senza argomento
    _r(job="", fn="", op="TTS_BACKEND_SWITCH", voice="gemini", lang="cf"),
]


@pytest.mark.parametrize("row", ROUND_TRIP)
def test_andata_e_ritorno_identica(row):
    assert activity_db.from_columns(activity_db.to_columns(row)) == row


def test_payload_m4b_va_in_detail():
    rec = activity_db.to_columns(_r(op="M4B_END", voice="size_mb=1"))
    assert rec["voice"] == "" and rec["detail"] == "size_mb=1"


def test_suffisso_e_email_del_voucher_separati():
    rec = activity_db.to_columns(_r(job="", op="ADMIN_VOUCHER_CREATE:gift", lang="a@b.it"))
    assert (rec["op"], rec["op_arg"]) == ("ADMIN_VOUCHER_CREATE", "gift")
    assert rec["lang"] == "" and rec["detail"] == "a@b.it"


def test_op_senza_due_punti_ha_op_arg_null():
    rec = activity_db.to_columns(_r(op="COMPLETE"))
    assert rec["op_arg"] is None and rec["detail"] == ""


# ---------------------------------------------------------------- scrittura

def test_insert_new_dedup_per_chiave_ed_epoca(conn):
    assert activity_db.insert_new(conn, "2026-08", _r(op="DOWNLOAD")) is True
    assert activity_db.insert_new(conn, "2026-08", _r(op="DOWNLOAD")) is False
    assert activity_db.insert_new(conn, "2026-08", _r(), epoch=1) is True
    assert activity_db.insert_new(conn, "2026-08", _r(), epoch=1) is False
    assert activity_db.insert_new(conn, "2026-08", _r(), epoch=2) is True
    assert activity_db.count(conn, "2026-08") == 3


def test_insert_new_job_vuoto_mai_deduplicato(conn):
    row = _r(job="", op="VOUCHER_ATTEMPT", lang="invalid")
    assert activity_db.insert_new(conn, "2026-08", row) is True
    assert activity_db.insert_new(conn, "2026-08", row) is True
    assert activity_db.count(conn, "2026-08") == 2


def test_insert_new_dedup_per_mese(conn):
    assert activity_db.insert_new(conn, "2026-08", _r(op="DOWNLOAD")) is True
    assert activity_db.insert_new(conn, "2026-09", _r(op="DOWNLOAD")) is True


def test_insert_new_suffissi_diversi_non_collidono(conn):
    assert activity_db.insert_new(conn, "2026-08", _r(op="X:a")) is True
    assert activity_db.insert_new(conn, "2026-08", _r(op="X:b")) is True


def test_insert_mirror_entra_sempre_con_seq_crescente(conn):
    for _ in range(3):
        assert activity_db.insert_mirror(conn, "2026-08", _r(), epoch=1) is True
    seqs = [r[0] for r in conn.execute("SELECT seq FROM events ORDER BY id")]
    assert seqs == [0, 1, 2]
    # la chiave seq=0 e' occupata: il dedup del modo db la vede
    assert activity_db.insert_new(conn, "2026-08", _r(), epoch=1) is False


def test_rebuild_tiene_i_duplicati_del_file(conn):
    rows = [_r(ts="2026-08-01 10:00:00"), _r(ts="2026-08-01 11:00:00"),
            _r(job="", op="VOUCHER_ATTEMPT"), _r(job="J2", op="COMPLETE")]
    assert activity_db.rebuild_month(conn, "2026-08", rows, size=123) == 4
    assert _all(conn) == rows
    assert activity_db.synced_size(conn, "2026-08") == 123
    # di nuovo: sostituisce, non accoda
    assert activity_db.rebuild_month(conn, "2026-08", rows[:2], size=50) == 2
    assert _all(conn) == rows[:2]
    assert activity_db.synced_size(conn, "2026-08") == 50


def test_rebuild_non_tocca_gli_altri_mesi(conn):
    activity_db.insert_new(conn, "2026-07", _r(ts="2026-07-01 10:00:00"))
    activity_db.rebuild_month(conn, "2026-08", [_r()], size=1)
    assert activity_db.count(conn, "2026-07") == 1


# ---------------------------------------------------------------- lettura

def test_select_rows_ordine_mese_poi_scrittura_e_filtri(conn):
    activity_db.insert_new(conn, "2026-08", _r(job="D", ts="2026-08-01 09:00:00", op="OPT_COMPLETE"))
    activity_db.insert_new(conn, "2026-07", _r(job="A", ts="2026-07-30 10:00:00", op="COMPLETE"))
    activity_db.insert_new(conn, "2026-07", _r(job="B", ts="2026-07-31 13:00:00", op="COMPLETE"))
    activity_db.insert_new(conn, "2026-07", _r(job="C", ts="2026-07-31 14:00:00", op="GENERATE"))
    activity_db.insert_new(conn, "2026-08", _r(job="E", ts="2026-08-02 00:00:00", op="COMPLETE"))
    assert [r[0] for r in _all(conn)] == ["A", "B", "C", "D", "E"]
    got = _all(conn, "2026-07", "2026-08", since_ts="2026-07-31 12:00:00",
               until_ts="2026-08-02 00:00:00", ops={"COMPLETE", "OPT_COMPLETE"})
    assert [r[0] for r in got] == ["B", "D"]


def test_select_rows_filtra_le_op_col_suffisso(conn):
    activity_db.insert_new(conn, "2026-08", _r(job="", op="ADMIN_VOUCHER_CREATE:gift", lang="a@b.it"))
    activity_db.insert_new(conn, "2026-08", _r(job="", op="ADMIN_VOUCHER_CREATE:promo", lang="c@d.it"))
    got = _all(conn, ops={"ADMIN_VOUCHER_CREATE:gift"})
    assert [(r[3], r[7]) for r in got] == [("ADMIN_VOUCHER_CREATE:gift", "a@b.it")]


def test_select_rows_ops_vuoto_nessuna_riga(conn):
    activity_db.insert_new(conn, "2026-08", _r())
    assert _all(conn, ops=set()) == []


def test_select_rows_molte_righe_a_blocchi(conn):
    rows = [_r(job=f"J{i}") for i in range(4500)]
    activity_db.rebuild_month(conn, "2026-08", rows, size=1)
    assert _all(conn) == rows


def test_op_counts_con_op_completa(conn):
    activity_db.insert_new(conn, "2026-08", _r(job="", op="VOUCHER_ATTEMPT_BLOCKED:rate"))
    activity_db.insert_new(conn, "2026-08", _r(job="", op="VOUCHER_ATTEMPT_BLOCKED:rate"))
    activity_db.insert_new(conn, "2026-08", _r(op="COMPLETE"))
    assert activity_db.op_counts(conn, "2026-08") == {
        "VOUCHER_ATTEMPT_BLOCKED:rate": 2, "COMPLETE": 1}


def test_fingerprint_none_se_vuoto_e_cambia_dopo_una_scrittura(conn):
    assert activity_db.fingerprint(conn, "2026-08") is None
    activity_db.insert_new(conn, "2026-08", _r(job="J1"))
    fp1 = activity_db.fingerprint(conn, "2026-08")
    activity_db.insert_new(conn, "2026-08", _r(job="J2"))
    assert fp1 is not None and activity_db.fingerprint(conn, "2026-08") != fp1


def test_mark_synced_sovrascrive(conn):
    assert activity_db.synced_size(conn, "2026-08") is None
    activity_db.mark_synced(conn, "2026-08", 10, 1)
    activity_db.mark_synced(conn, "2026-08", 20, 2)
    assert activity_db.synced_size(conn, "2026-08") == 20
