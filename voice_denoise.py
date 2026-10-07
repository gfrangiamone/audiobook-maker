"""Pulizia del campione delle voci utente con ZipEnhancer, sulla CPU del server.

Prima la faceva il worker VoxCPM (`denoise` nel payload), sulla stessa GPU del
motore: dal 25/09/2026 ogni worker che puliva un campione mandava in OOM il
motore (29 su 29), e ABM lo leggeva come «motore compromesso». Qui la pulizia
si fa una volta per voce, quando parte la generazione delle demo, e il
campione che arriva al worker e' gia' pulito.

La pipeline gira in un processo figlio: torch e modelscope pesano qualche
centinaio di MB e il processo web non deve tenerli in memoria per un lavoro
che capita una volta per voce. Il figlio e' questo stesso file
(`python voice_denoise.py <src> <dst>`), a priorita' bassa e con pochi thread,
cosi' le richieste web non ne risentono.

Stessa ricetta del worker (`_denoise_ref`, come la demo di VoxCPM2): pulizia a
16 kHz, poi qui il wav torna a 24 kHz e al volume dei campioni di ABM
(-23 LUFS, tetto -1 dBFS). La banda sopra gli 8 kHz si perde, ma l'encoder di
VoxCPM2 il campione lo sente comunque a 16 kHz.
"""
from __future__ import annotations

import contextlib
import io
import math
import os
from env_utils import env_float, env_int
import subprocess
import sys
import tempfile
import threading
import time

MODEL = "iic/speech_zipenhancer_ans_multiloss_16k_base"
DENOISE_RATE = 16000
_data_dir = None
# Una pulizia alla volta: ognuna occupa i thread che le si danno, e due voci
# pagate nello stesso minuto possono aspettare l'una l'altra.
_lock = threading.Lock()


class DenoiseFailed(Exception):
    """La pulizia non e' riuscita: il campione resta com'era."""


def init(data_dir):
    """I pesi del modello vanno in `<data_dir>/modelscope`."""
    global _data_dir
    _data_dir = str(data_dir)


def enabled():
    """`ABM_VOICE_CLONE_DENOISE=0` spegne la pulizia sul server."""
    return (os.environ.get("ABM_VOICE_CLONE_DENOISE") or "1").strip() != "0"


def _threads():
    return env_int("ABM_VOICE_CLONE_DENOISE_THREADS", 2, floor=1)


def _timeout():
    return env_float("ABM_VOICE_CLONE_DENOISE_TIMEOUT", 900)


def _cache_dir():
    return os.path.join(_data_dir, "modelscope") if _data_dir else None


def _child_env():
    env = dict(os.environ)
    n = str(_threads())
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        env[k] = n
    cache = _cache_dir()
    if cache:
        env["MODELSCOPE_CACHE"] = cache
    return env


def _nice():
    # Solo posix: sotto Windows (sviluppo) si gira a priorita' normale.
    if hasattr(os, "nice"):
        os.nice(10)


def clean(src_wav, dst_wav):
    """`src_wav` pulito in `dst_wav`, wav s16 mono a 24 kHz e -23 LUFS.

    Solleva DenoiseFailed. Ritorna i secondi impiegati.
    """
    import voice_clone_audio as vca     # import qui: il figlio non lo carica
    t0 = time.time()
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        with _lock:
            try:
                r = subprocess.run(
                    [sys.executable, os.path.abspath(__file__), src_wav, tmp],
                    capture_output=True, timeout=_timeout(), env=_child_env(),
                    preexec_fn=_nice if os.name == "posix" else None,
                    encoding="utf-8", errors="replace", **vca._SUBPROCESS_FLAGS)
            except subprocess.TimeoutExpired as e:
                raise DenoiseFailed(f"oltre {_timeout():.0f}s") from e
            except OSError as e:
                raise DenoiseFailed(str(e)) from e
        if r.returncode != 0:
            coda = (r.stderr or "").strip().splitlines()[-1:] or ["?"]
            raise DenoiseFailed(f"exit {r.returncode}: {coda[0][:300]}")
        x, sr = vca.read_wav(tmp)
        lu = vca.loudness_lufs(tmp)
        # Un campione tutto silenzio da' -inf: lo si lascia com'e'.
        if math.isfinite(lu):
            x = x * (10.0 ** ((vca.TARGET_LUFS - lu) / 20.0))
        picco = float(abs(x).max()) if x.size else 0.0
        tetto = 10.0 ** (vca.PEAK_DBFS / 20.0)
        if picco > tetto:
            x = x * (tetto / picco)
        vca.write_wav(dst_wav, x, sr)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return time.time() - t0


def _main(src, dst):
    """Nel figlio: ZipEnhancer su CPU, uscita ricampionata a 24 kHz."""
    import numpy as np
    from scipy.signal import resample_poly
    import torch
    from modelscope.outputs import OutputKeys
    from modelscope.pipelines import pipeline
    from modelscope.utils.constant import Tasks
    import voice_clone_audio as vca

    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS") or 2))
    with open(src, "rb") as f:
        raw = f.read()
    # La pipeline stampa un avanzamento per ogni finestra da 2 s.
    with contextlib.redirect_stdout(io.StringIO()):
        p = pipeline(Tasks.acoustic_noise_suppression, model=MODEL, device="cpu")
        pcm = p(raw)[OutputKeys.OUTPUT_PCM]
    y = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    g = math.gcd(vca.SAMPLE_RATE, DENOISE_RATE)
    y = resample_poly(y, vca.SAMPLE_RATE // g, DENOISE_RATE // g)
    vca.write_wav(dst, y, vca.SAMPLE_RATE)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("uso: voice_denoise.py <src.wav> <dst.wav>")
    _main(sys.argv[1], sys.argv[2])
