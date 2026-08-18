"""Regressione incidente 2026-08-16 (job 9dmJT_I3lHSeD2Vwz0Bu1A).

Un audiolibro di ~7h veniva consegnato troncato a 4h18m: ffmpeg era stato
ucciso dal timeout fisso di subprocess.run e il file parziale, rimasto sul
disco, era stato spedito all'utente come se fosse completo.

Invarianti coperti qui:
  - la durata attesa si ricava dai soli byte PCM (nessun header da leggere);
  - un output piu' corto della sorgente e' un fallimento, non un successo;
  - ogni path di fallimento cancella il file parziale;
  - l'encode viene sorvegliato per stallo, non per wall-clock.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audio_utils  # noqa: E402


def _write_pcm(path, seconds, sample_rate=24000, channels=1, sample_width=2):
    """Crea un PCM raw silenzioso della durata richiesta."""
    with open(path, "wb") as f:
        f.write(b"\0" * int(seconds * sample_rate * channels * sample_width))
    return path


# --- durata attesa dal PCM ---------------------------------------------------

def test_expected_duration_dai_byte(tmp_path):
    a = _write_pcm(str(tmp_path / "a.pcm"), 2.0)
    b = _write_pcm(str(tmp_path / "b.pcm"), 3.0)
    assert audio_utils._pcm_expected_duration_sec([a, b]) == pytest.approx(5.0)


def test_expected_duration_include_i_gap(tmp_path):
    a = _write_pcm(str(tmp_path / "a.pcm"), 1.0)
    b = _write_pcm(str(tmp_path / "b.pcm"), 1.0)
    c = _write_pcm(str(tmp_path / "c.pcm"), 1.0)
    # due gap da 500 ms tra tre file
    got = audio_utils._pcm_expected_duration_sec([a, b, c], gap_ms=500)
    assert got == pytest.approx(4.0)


def test_expected_duration_ignora_file_mancanti(tmp_path):
    a = _write_pcm(str(tmp_path / "a.pcm"), 1.0)
    got = audio_utils._pcm_expected_duration_sec([a, str(tmp_path / "manca.pcm")])
    assert got == pytest.approx(1.0)
    assert audio_utils._pcm_expected_duration_sec([]) == 0.0


# --- validazione della durata dell'encode ------------------------------------

def test_durata_troncata_rilevata(tmp_path, monkeypatch):
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    monkeypatch.setattr(audio_utils, "_check_audio_dependencies", lambda: (True, True))
    # 4h18m consegnate al posto di 7h: esattamente il caso dell'incidente
    monkeypatch.setattr(audio_utils, "_get_audio_duration_ms", lambda p: 15532 * 1000)
    assert audio_utils._encoded_duration_ok(str(out), 25200.0, "test") is False


def test_durata_completa_accettata(tmp_path, monkeypatch):
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    monkeypatch.setattr(audio_utils, "_check_audio_dependencies", lambda: (True, True))
    monkeypatch.setattr(audio_utils, "_get_audio_duration_ms", lambda p: 25200 * 1000)
    assert audio_utils._encoded_duration_ok(str(out), 25200.0, "test") is True


def test_durata_illeggibile_e_fallimento(tmp_path, monkeypatch):
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    monkeypatch.setattr(audio_utils, "_check_audio_dependencies", lambda: (True, True))
    monkeypatch.setattr(audio_utils, "_get_audio_duration_ms", lambda p: 0)
    assert audio_utils._encoded_duration_ok(str(out), 100.0, "test") is False


def test_verifica_saltata_senza_ffprobe(tmp_path, monkeypatch):
    """Senza ffprobe non possiamo misurare: non blocchiamo un output valido."""
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    monkeypatch.setattr(audio_utils, "_check_audio_dependencies", lambda: (True, False))
    assert audio_utils._encoded_duration_ok(str(out), 25200.0, "test") is True


def test_verifica_saltata_senza_durata_attesa(tmp_path):
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    assert audio_utils._encoded_duration_ok(str(out), 0.0, "test") is True


# --- rimozione dell'output parziale ------------------------------------------

def test_discard_rimuove_il_parziale(tmp_path):
    out = tmp_path / "out.mp3"
    out.write_bytes(b"parziale")
    audio_utils._discard_failed_output(str(out), "test")
    assert not out.exists()


def test_discard_tollera_file_assente(tmp_path):
    audio_utils._discard_failed_output(str(tmp_path / "mai_creato.mp3"), "test")
    audio_utils._discard_failed_output("", "test")


# --- i due encoder non consegnano mai un file troncato -----------------------

@pytest.mark.parametrize("encoder", ["pcm_to_mp3", "pcm_to_aac_m4b"])
def test_encode_fallito_non_lascia_output(tmp_path, monkeypatch, encoder):
    src = _write_pcm(str(tmp_path / "src.pcm"), 1.0)
    out = str(tmp_path / "out.bin")

    monkeypatch.setattr(audio_utils, "_check_audio_dependencies", lambda: (True, True))

    def fake_run(cmd, output_path, tag, **kwargs):
        # ffmpeg ucciso a meta': il file parziale resta sul disco
        with open(output_path, "wb") as f:
            f.write(b"\0" * 1024)
        return False, "killed", "stall"

    monkeypatch.setattr(audio_utils, "_run_ffmpeg_encode", fake_run)

    assert getattr(audio_utils, encoder)([src], out) is False
    assert not os.path.exists(out), "il file parziale non e' stato rimosso"


@pytest.mark.parametrize("encoder", ["pcm_to_mp3", "pcm_to_aac_m4b"])
def test_output_troncato_non_viene_consegnato(tmp_path, monkeypatch, encoder):
    """ffmpeg esce con rc=0 ma l'audio e' meta': va scartato lo stesso."""
    src = _write_pcm(str(tmp_path / "src.pcm"), 10.0)
    out = str(tmp_path / "out.bin")

    monkeypatch.setattr(audio_utils, "_check_audio_dependencies", lambda: (True, True))
    monkeypatch.setattr(audio_utils, "_run_ffmpeg_encode",
                        lambda cmd, output_path, tag, **kw: (
                            open(output_path, "wb").write(b"\0" * 4096), (True, "", ""))[1])
    monkeypatch.setattr(audio_utils, "_get_audio_duration_ms", lambda p: 5000)

    assert getattr(audio_utils, encoder)([src], out) is False
    assert not os.path.exists(out)


@pytest.mark.parametrize("encoder", ["pcm_to_mp3", "pcm_to_aac_m4b"])
def test_output_integro_viene_consegnato(tmp_path, monkeypatch, encoder):
    src = _write_pcm(str(tmp_path / "src.pcm"), 10.0)
    out = str(tmp_path / "out.bin")

    monkeypatch.setattr(audio_utils, "_check_audio_dependencies", lambda: (True, True))
    monkeypatch.setattr(audio_utils, "_run_ffmpeg_encode",
                        lambda cmd, output_path, tag, **kw: (
                            open(output_path, "wb").write(b"\0" * 4096), (True, "", ""))[1])
    monkeypatch.setattr(audio_utils, "_get_audio_duration_ms", lambda p: 10000)

    assert getattr(audio_utils, encoder)([src], out) is True
    assert os.path.exists(out)


# --- sorveglianza dell'encode -------------------------------------------------

def test_run_ffmpeg_encode_uccide_il_processo_bloccato(tmp_path):
    """Nessuna crescita dell'output oltre stall_timeout: il processo va terminato."""
    out = str(tmp_path / "out.bin")
    cmd = [sys.executable, "-c", "import time; time.sleep(60)"]
    ok, _tail, reason = audio_utils._run_ffmpeg_encode(
        cmd, out, "test", expected_sec=1.0, stall_timeout=1.0, poll_interval=0.2)
    assert ok is False
    assert reason == "stall"


def test_run_ffmpeg_encode_aspetta_finche_output_cresce(tmp_path):
    """Un encode lento ma vivo non viene ucciso, anche oltre stall_timeout."""
    out = str(tmp_path / "out.bin")
    script = (
        "import sys, time\n"
        "p = sys.argv[1]\n"
        "for _ in range(8):\n"
        "    with open(p, 'ab') as f:\n"
        "        f.write(b'x' * 128); f.flush()\n"
        "    time.sleep(0.25)\n"
    )
    ok, _tail, reason = audio_utils._run_ffmpeg_encode(
        [sys.executable, "-c", script, out], out, "test",
        expected_sec=1.0, stall_timeout=1.0, poll_interval=0.2)
    assert ok is True, f"processo vivo ucciso per errore: {reason}"


def test_run_ffmpeg_encode_riporta_il_returncode(tmp_path):
    out = str(tmp_path / "out.bin")
    ok, _tail, reason = audio_utils._run_ffmpeg_encode(
        [sys.executable, "-c", "import sys; sys.exit(3)"], out, "test",
        poll_interval=0.2)
    assert ok is False
    assert reason == "rc=3"


def test_run_ffmpeg_encode_cattura_lo_stderr(tmp_path):
    out = str(tmp_path / "out.bin")
    ok, tail, _reason = audio_utils._run_ffmpeg_encode(
        [sys.executable, "-c",
         "import sys; sys.stderr.write('Conversion failed!'); sys.exit(1)"],
        out, "test", poll_interval=0.2)
    assert ok is False
    assert "Conversion failed!" in tail


def test_run_ffmpeg_encode_comando_inesistente(tmp_path):
    """Eseguibile assente: errore gestito, non eccezione propagata."""
    out = str(tmp_path / "out.bin")
    ok, _tail, reason = audio_utils._run_ffmpeg_encode(
        ["binario_che_non_esiste_abm", "-x"], out, "test", poll_interval=0.2)
    assert ok is False
    assert reason


def test_kill_process_tree_termina(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    audio_utils._kill_process_tree(proc)
    assert proc.poll() is not None
