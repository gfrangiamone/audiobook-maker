"""Test: l'assembly che esce dalla coda non scrive piu' in un job che non e' suo.

Incidente del 23/08/2026 (job Wne3EQMNT0f5tFLL5zHHKA): l'utente cancella una
generazione e ne lancia un'altra; l'assembly della epoch cancellata resta in
coda e ottiene lo slot 2 secondi DOPO il COMPLETE della epoch nuova. Muore su
ENOENT, marca il job `error` e l'utente riceve tre 404 sul download di un
audiolibro che era stato prodotto.

Difetti coperti qui:
  D1 - nessun ricontrollo dopo l'attesa in coda (fino a 618 s osservati);
  D2 - il purge per heartbeat perso cancella la job dir mentre il job e' in
       fila per uno slot;
  D3 - il fallimento dell'assembly stale declassa un job gia' completato.
"""
import time

import pytest

import assembly_queue
import audiobook_app
import generation_engine


@pytest.fixture
def jobs(monkeypatch):
    reg = {}
    monkeypatch.setattr(generation_engine, "_jobs", reg)
    return reg


@pytest.fixture(autouse=True)
def restore_slots():
    saved = assembly_queue.MAX_CONCURRENT_ASSEMBLY
    yield
    assembly_queue.configure(saved)


def _job(**over):
    j = {"gen_epoch": 2, "voice": "it-IT-DiegoNeural", "status": "generating"}
    j.update(over)
    return j


# --- D1: riconoscimento del thread obsoleto ---------------------------------

def test_epoch_superata_e_stale(jobs, tmp_path):
    j = _job(gen_epoch=3)
    jobs["J"] = j
    reason = generation_engine._assembly_stale_reason("J", j, 2, tmp_path)
    assert reason and "epoch superata" in reason


def test_entry_rimossa_e_stale(jobs, tmp_path):
    j = _job()
    # non registrato: il cleanup ha gia' tolto la entry
    reason = generation_engine._assembly_stale_reason("J", j, 2, tmp_path)
    assert reason and "registro" in reason


def test_workdir_sparita_e_stale_per_job_free(jobs, tmp_path):
    j = _job()
    jobs["J"] = j
    reason = generation_engine._assembly_stale_reason("J", j, 2, tmp_path / "sparita")
    assert reason and "work_dir" in reason


def test_workdir_sparita_non_e_stale_per_job_pagato(jobs, tmp_path):
    """Un job pagato deve percorrere il path d'errore, che rimborsa e notifica.

    Uscire in silenzio lascerebbe l'utente senza audiolibro E senza rimborso.
    """
    j = _job(payment_token="tok-123")
    jobs["J"] = j
    assert generation_engine._assembly_stale_reason("J", j, 2, tmp_path / "sparita") is None


def test_scenario_integro_non_e_stale(jobs, tmp_path):
    j = _job()
    jobs["J"] = j
    assert generation_engine._assembly_stale_reason("J", j, 2, tmp_path) is None


# --- D1/D3: l'acquire aborta e restituisce lo slot --------------------------

def test_acquire_solleva_e_libera_lo_slot_se_stale(jobs, tmp_path):
    j = _job(gen_epoch=9)
    jobs["J"] = j
    before = assembly_queue.stats()["free"]

    with pytest.raises(generation_engine._StaleAssemblyError):
        generation_engine._acquire_assembly_slot(
            "J", j, "single-file", my_epoch=2, work_dir=tmp_path)

    # Lo slot non resta occupato: la coda non deve degradare a ogni abort.
    assert assembly_queue.stats()["free"] == before
    # E il flag non resta appeso a sospendere il purge del job.
    assert "assembly_started_at" not in j


def test_acquire_normale_marca_la_fase_e_release_la_chiude(jobs, tmp_path):
    j = _job()
    jobs["J"] = j
    slot = generation_engine._acquire_assembly_slot(
        "J", j, "single-file", my_epoch=2, work_dir=tmp_path)
    assert j["assembly_started_at"] > 0
    generation_engine._release_assembly_slot(j, slot)
    assert "assembly_started_at" not in j


# --- D2: il purge per heartbeat resta sospeso durante l'assembly ------------

def test_purge_sospeso_durante_assembly():
    now = time.time()
    assert audiobook_app._assembly_purge_hold({"assembly_started_at": now - 300}, now)


def test_purge_riprende_oltre_la_finestra_di_grazia():
    now = time.time()
    old = now - audiobook_app.CLEANUP_ASSEMBLY_GRACE_SEC - 1
    assert not audiobook_app._assembly_purge_hold({"assembly_started_at": old}, now)


def test_purge_normale_senza_flag():
    assert not audiobook_app._assembly_purge_hold({}, time.time())


def test_flag_corrotto_non_rende_il_job_immortale():
    assert not audiobook_app._assembly_purge_hold(
        {"assembly_started_at": "boh"}, time.time())
