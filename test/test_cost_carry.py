"""Il costo TTS gia' speso deve sopravvivere a un riavvio del processo.

Il caso reale: un job premium viene interrotto a meta' libro da un riavvio,
riparte riusando i chunk gia' su disco e contabilizza solo cio' che sintetizza
DOPO il riavvio. In console il costo TTS crolla a pochi centesimi su un
audiolibro pagato decine di euro, e il record d'audit eredita lo stesso buco.
"""
from unittest.mock import patch

import cost_carry
import generation_engine


def test_the_carry_survives_a_write_and_read_round_trip(tmp_path):
    cost_carry.write(tmp_path, "gemini", {"chars": 120, "google_cost_eur": 0.5})
    assert cost_carry.read(tmp_path, "gemini") == {
        "chars": 120, "google_cost_eur": 0.5}


def test_an_absent_carry_reads_as_empty(tmp_path):
    assert cost_carry.read(tmp_path, "gemini") == {}
    assert cost_carry.read_all(tmp_path) == {}


def test_an_unreadable_carry_reads_as_empty_instead_of_raising(tmp_path):
    (tmp_path / cost_carry.CARRY_NAME).write_text("{ non e' json",
                                                  encoding="utf-8")
    assert cost_carry.read(tmp_path, "gemini") == {}


def test_one_engine_does_not_erase_another(tmp_path):
    cost_carry.write(tmp_path, "gemini", {"chars": 10})
    cost_carry.write(tmp_path, "voxcpm", {"chars": 20})
    assert cost_carry.read(tmp_path, "gemini") == {"chars": 10}
    assert cost_carry.read(tmp_path, "voxcpm") == {"chars": 20}


def test_the_restarted_run_resumes_from_what_was_already_spent(tmp_path):
    cost_carry.write(tmp_path, "gemini", {
        "input_tokens": 900, "output_tokens": 1800, "chars": 400_000,
        "audio_seconds": 7200.0, "google_cost_eur": 9.5,
        "pricing_cost_eur": 11.0, "model_key": "flash31"})
    fresh = {"input_tokens": 0, "output_tokens": 0, "chars": 0,
             "audio_seconds": 0.0, "google_cost_eur": 0.0,
             "pricing_cost_eur": 0.0, "model_key": None}
    cost_carry.resume(tmp_path, "gemini", fresh)
    assert fresh["chars"] == 400_000
    assert fresh["google_cost_eur"] == 9.5
    assert fresh["model_key"] == "flash31"


def test_the_current_run_adds_on_top_of_the_carry(tmp_path):
    cost_carry.write(tmp_path, "gemini", {"chars": 1000, "google_cost_eur": 2.0})
    actual = {"chars": 250, "google_cost_eur": 0.5}
    cost_carry.resume(tmp_path, "gemini", actual)
    assert actual == {"chars": 1250, "google_cost_eur": 2.5}


def test_the_model_key_of_the_current_run_wins_over_the_carried_one():
    actual = {"model_key": "flash31"}
    cost_carry.merge(actual, {"model_key": "flash25"})
    assert actual["model_key"] == "flash31"


def test_a_histogram_is_summed_position_by_position():
    """`verifica_rientri`: il secondo giro di ieri e quello di oggi sono lo
    stesso giro, non due voci in coda."""
    actual = {"verifica_rientri": [3, 1]}
    cost_carry.merge(actual, {"verifica_rientri": [10, 4, 2]})
    assert actual["verifica_rientri"] == [13, 5, 2]


def test_an_event_list_is_concatenated_with_the_older_entries_first():
    actual = {"runpod": [{"sec": 2}]}
    cost_carry.merge(actual, {"runpod": [{"sec": 9}]})
    assert actual["runpod"] == [{"sec": 9}, {"sec": 2}]


def test_resuming_twice_would_double_the_spend_so_it_is_done_once(tmp_path):
    """Guardia di documentazione: `merge` e' una somma, non un idempotente.
    Vale come promemoria per chi spostasse la chiamata dentro un loop."""
    cost_carry.write(tmp_path, "gemini", {"chars": 100})
    actual = {"chars": 0}
    cost_carry.resume(tmp_path, "gemini", actual)
    cost_carry.resume(tmp_path, "gemini", actual)
    assert actual["chars"] == 200


def test_clearing_one_engine_leaves_the_others(tmp_path):
    cost_carry.write(tmp_path, "gemini", {"chars": 10})
    cost_carry.write(tmp_path, "voxcpm", {"chars": 20})
    cost_carry.clear(tmp_path, "gemini")
    assert cost_carry.read(tmp_path, "gemini") == {}
    assert cost_carry.read(tmp_path, "voxcpm") == {"chars": 20}


def test_clearing_the_last_engine_takes_the_file_away(tmp_path):
    cost_carry.write(tmp_path, "gemini", {"chars": 10})
    cost_carry.clear(tmp_path, "gemini")
    assert not (tmp_path / cost_carry.CARRY_NAME).exists()


def test_clearing_an_absent_carry_is_not_an_error(tmp_path):
    assert cost_carry.clear(tmp_path) is True
    assert cost_carry.clear(tmp_path, "gemini") is True


def test_the_flush_interval_is_configurable(monkeypatch):
    monkeypatch.setenv("ABM_COST_CARRY_EVERY", "5")
    assert cost_carry.flush_every() == 5
    monkeypatch.setenv("ABM_COST_CARRY_EVERY", "non un numero")
    assert cost_carry.flush_every() == cost_carry.DEFAULT_FLUSH_EVERY
    monkeypatch.setenv("ABM_COST_CARRY_EVERY", "0")
    assert cost_carry.flush_every() == 1


def _job_with_carry(tmp_path, job_id):
    (tmp_path / job_id).mkdir()
    cost_carry.write(tmp_path / job_id, "gemini",
                     {"chars": 400_000, "google_cost_eur": 9.5})
    return {
        "payment": {"token": "X", "total_eur": 30.16, "method": "paypal"},
        "gemini_actual": {"google_cost_eur": 9.5, "chars": 400_000,
                          "input_tokens": 900, "output_tokens": 1800,
                          "audio_seconds": 7200.0},
        "rate": "+0%",
    }


def test_the_audit_record_absorbs_the_carry_and_the_file_goes_away(tmp_path):
    """Dopo il record il riporto non serve piu': la spesa e' nel JSONL, e
    lasciarlo sul disco la farebbe contare due volte al tentativo dopo."""
    job = _job_with_carry(tmp_path, "job1")
    captured = {}
    with patch.object(generation_engine, "_upload_dir", tmp_path), \
            patch("generation_engine.gemini_cost_audit.append_record",
                  side_effect=lambda r: captured.update(r)):
        generation_engine._write_gemini_audit(
            "job1", job, "gemini:flash31:Zephyr", "it", "completed")
    assert captured["chars_total"] == 400_000
    assert captured["google_cost_eur_actual"] == 9.5
    assert not (tmp_path / "job1" / cost_carry.CARRY_NAME).exists()


def test_a_non_premium_voice_leaves_the_carry_alone(tmp_path):
    """`_write_gemini_audit` esce subito su voce non Gemini: non deve toccare
    il riporto di un motore che non e' il suo."""
    job = _job_with_carry(tmp_path, "job2")
    with patch.object(generation_engine, "_upload_dir", tmp_path):
        generation_engine._write_gemini_audit(
            "job2", job, "it-IT-ElsaNeural", "it", "completed")
    assert (tmp_path / "job2" / cost_carry.CARRY_NAME).exists()
