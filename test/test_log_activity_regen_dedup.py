"""Regressione: il dedup di _log_activity non deve sopprimere gli eventi di
ciclo (GENERATE/COMPLETE) di una RI-generazione dello stesso job_id.

Scenario reale (incidente job -wMf9vKGCM3qh6CLszaDeQ, 2026-06-12): l'utente
cancella un job gia' "done" e ri-genera con lo stesso job_id nello stesso mese.
La 2a generazione produceva un run TTS completo (output_2) ma non compariva nel
business log perche' _log_activity deduplicava per (job_id, operazione).
Fix: l'`epoch` (job["gen_epoch"], bumpato a ogni /api/generate) entra nella
chiave di dedup per gli eventi di ciclo; gli eventi spam-prone (download da
prefetch HEAD/Range, chiamati senza epoch) restano col dedup secco a 2-tuple.
"""
import pathlib
import tempfile

import audiobook_app


def _read_ops(script_dir, month):
    logf = script_dir / f"activity_{month}.log"
    lines = logf.read_text(encoding="utf-8").splitlines()
    return [l.split(" # ")[3] for l in lines]


def _reset_log(monkeypatch):
    script_dir = pathlib.Path(tempfile.mkdtemp())
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", script_dir)
    monkeypatch.setattr(audiobook_app, "_logged_month", "")
    monkeypatch.setattr(audiobook_app, "_logged_sids_ops", set())
    return script_dir


def test_regeneration_logs_distinct_lifecycle_events(monkeypatch):
    """Cancel + re-generate (stesso job_id, epoch incrementato) -> 2 GENERATE + 2 COMPLETE."""
    script_dir = _reset_log(monkeypatch)

    # 1o run (epoch=1)
    audiobook_app._log_activity("JOB", "f.epub", "GENERATE", "c", "ip", "zh-CN-XiaoyiNeural", "zh", epoch=1)
    audiobook_app._log_activity("JOB", "f.epub", "COMPLETE", "c", "ip", "zh-CN-XiaoyiNeural", "zh", epoch=1)
    # 2o run dopo cancel (epoch=2)
    audiobook_app._log_activity("JOB", "f.epub", "GENERATE", "c", "ip", "zh-CN-XiaoyiNeural", "zh", epoch=2)
    audiobook_app._log_activity("JOB", "f.epub", "COMPLETE", "c", "ip", "zh-CN-XiaoyiNeural", "zh", epoch=2)

    ops = _read_ops(script_dir, audiobook_app._logged_month)
    assert ops.count("GENERATE") == 2
    assert ops.count("COMPLETE") == 2


def test_same_epoch_repeats_are_deduped(monkeypatch):
    """Idempotenza entro lo stesso run: stesso (job_id, op, epoch) -> 1 sola riga."""
    script_dir = _reset_log(monkeypatch)

    audiobook_app._log_activity("JOB", "f.epub", "GENERATE", "c", "ip", "v", "zh", epoch=5)
    audiobook_app._log_activity("JOB", "f.epub", "GENERATE", "c", "ip", "v", "zh", epoch=5)

    assert _read_ops(script_dir, audiobook_app._logged_month).count("GENERATE") == 1


def test_no_epoch_events_keep_strict_dedup(monkeypatch):
    """Eventi senza epoch (es. DOWNLOAD da prefetch) restano deduplicati a 2-tuple."""
    script_dir = _reset_log(monkeypatch)

    audiobook_app._log_activity("JOB", "f.epub", "DOWNLOAD", "c", "ip", "v", "zh")
    audiobook_app._log_activity("JOB", "f.epub", "DOWNLOAD", "c", "ip", "v", "zh")

    assert _read_ops(script_dir, audiobook_app._logged_month).count("DOWNLOAD") == 1
