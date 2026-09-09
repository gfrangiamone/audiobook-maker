"""Conversione, misure, gate e verifica ASR dei campioni vocali (spec §5).

Le misure sono il porting di `tools/voice_prompts/audio.py` del worker
VoxCPM, ridotto a numpy: dove il worker usa scipy (highpass, K-weighting
del loudness) o librosa (STFT) qui lavorano ffmpeg (`highpass`, `ebur128`)
o un framing rfft esplicito. Le soglie sono quelle del worker, cosi' un
campione che passa qui e' dello stesso ordine di qualita' delle voci di
catalogo.
"""
from __future__ import annotations

import math
import os
import wave
from dataclasses import dataclass, field, asdict

import numpy as np

EPS = 1e-12
SAMPLE_RATE = 24000          # il wav che VoxCPM riceve (spec §5.1)
TARGET_LUFS = -23.0          # come `normalize()` del worker
PEAK_DBFS = -1.0
CLARITY_HI_HZ = 4000.0
CLARITY_W = 0.40


# ---------------------------------------------------------------------------
# wav s16 mono
# ---------------------------------------------------------------------------
def read_wav(path):
    """wav PCM s16 mono -> (float32 in [-1, 1], sample rate)."""
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError(f"atteso wav s16 mono: {path}")
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return x, sr


def write_wav(path, x, sr):
    y = np.clip(np.asarray(x, dtype=np.float32), -1.0, 1.0)
    pcm = (y * 32767.0).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm)


# ---------------------------------------------------------------------------
# VAD energetico e metriche (porting numpy del worker)
# ---------------------------------------------------------------------------
def frame_db(x, sr, win_ms=25.0, hop_ms=10.0):
    win = max(64, int(sr * win_ms / 1000))
    hop = max(16, int(sr * hop_ms / 1000))
    if len(x) < win:
        return np.array([-120.0]), hop
    n = 1 + (len(x) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    frames = x[idx]
    rms = np.sqrt(np.mean(frames * frames, axis=1) + EPS)
    return 20.0 * np.log10(rms + EPS), hop


def speech_mask(db):
    """Maschera di parlato: soglia adattiva sul rumore di fondo."""
    floor = float(np.percentile(db, 10))
    peak = float(np.percentile(db, 95))
    thr = max(floor + 8.0, peak - 35.0)
    m = db > thr
    if m.any():
        idx = np.flatnonzero(m)
        for a, b in zip(idx[:-1], idx[1:]):
            if 1 < b - a <= 4:          # occlusive, non pause
                m[a:b] = True
    return m, floor, thr


def speech_segments(m, hop, sr):
    out, start = [], None
    for i, v in enumerate(m):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start * hop / sr, i * hop / sr))
            start = None
    if start is not None:
        out.append((start * hop / sr, len(m) * hop / sr))
    return out


def _power_frames(x, n_fft, hop):
    """|rfft|^2 dei fotogrammi con finestra di Hann; (frames, bins)."""
    x = np.asarray(x, dtype=np.float64)
    if len(x) < n_fft + hop:
        return None
    n = 1 + (len(x) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    return np.abs(np.fft.rfft(x[idx] * np.hanning(n_fft), axis=1)) ** 2


def speech_bandwidth(x, sr, m, hop):
    """Frequenza oltre la quale lo spettro medio del parlato crolla.

    Come nel worker (n_fft 2048, media sui fotogrammi di parlato, media
    mobile su 5 bin, riferimento = massimo nei primi n_fft/8 bin, banda =
    ultimo bin sopra ref-50 dB), ma con framing rfft senza `librosa.stft`:
    i fotogrammi non sono centrati, quindi si allineano alla maschera per
    indice fino al piu' corto dei due.
    """
    n_fft = 2048
    S = _power_frames(x, n_fft, hop)
    if S is None:
        return 0.0
    frames = min(S.shape[0], len(m))
    sel = m[:frames]
    if sel.sum() < 3:
        sel = np.ones(frames, dtype=bool)
    spec = S[:frames][sel].mean(axis=0)
    spec_db = 10.0 * np.log10(spec + EPS)
    spec_db = np.convolve(spec_db, np.ones(5) / 5.0, mode="same")
    ref = float(spec_db[: n_fft // 8].max())
    above = np.flatnonzero(spec_db > ref - 50.0)
    if len(above) == 0:
        return 0.0
    return float(above[-1] * sr / n_fft)


def band_snr(x, sr, f_lo=0.0, n_fft=1024, hop=256):
    """SNR in dB dentro una banda: 40% di fotogrammi piu' forti contro il
    20% piu' deboli, stessa selezione per ogni banda (vedi worker)."""
    S = _power_frames(x, n_fft, hop)
    if S is None:
        return 0.0
    freq = np.fft.rfftfreq(n_fft, 1.0 / sr)
    tot = S.sum(axis=1)
    voice = tot > np.percentile(tot, 60)
    floor = tot <= np.percentile(tot, 20)
    if not voice.any() or not floor.any():
        return 0.0
    band = S[:, freq >= f_lo].sum(axis=1)
    return float(10.0 * np.log10(band[voice].mean() / max(band[floor].mean(), EPS)))


def clipping_runs(x, thr=0.999, run=3):
    hot = np.abs(x) >= thr
    if not hot.any():
        return 0
    d = np.diff(hot.astype(np.int8))
    starts = np.flatnonzero(d == 1) + 1
    ends = np.flatnonzero(d == -1) + 1
    if hot[0]:
        starts = np.r_[0, starts]
    if hot[-1]:
        ends = np.r_[ends, len(hot)]
    return int(np.sum((ends - starts) >= run))


def trim_edges(x, sr, pad_ms=300.0):
    """Toglie i silenzi ai due estremi lasciando `pad_ms` di margine."""
    db, hop = frame_db(x, sr)
    m, _, _ = speech_mask(db)
    if not m.any():
        return x
    idx = np.flatnonzero(m)
    pad = int(sr * pad_ms / 1000)
    a = max(0, idx[0] * hop - pad)
    b = min(len(x), idx[-1] * hop + hop + pad)
    return x[a:b]


@dataclass
class Metrics:
    duration: float
    snr_db: float
    snr_hi_db: float
    clarity: float
    speech_ratio: float
    bandwidth_hz: float
    clip_runs: int
    longest_gap: float
    peak_dbfs: float
    dc_offset: float
    lufs: float = float("nan")      # la misura ffmpeg (Task 3); nan = non misurata
    reasons: list = field(default_factory=list)

    def as_dict(self):
        d = asdict(self)
        if not math.isfinite(d["lufs"]):
            d["lufs"] = None
        return d


def measure(x, sr):
    x = np.asarray(x, dtype=np.float32)
    db, hop = frame_db(x, sr)
    m, floor, _ = speech_mask(db)
    spd = db[m]
    snr = float(np.median(spd) - floor) if spd.size else 0.0
    segs = speech_segments(m, hop, sr)
    gap = 0.0
    for (_, e), (s2, _) in zip(segs[:-1], segs[1:]):
        gap = max(gap, s2 - e)
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    snr_lo = band_snr(x, sr, 0.0)
    snr_hi = band_snr(x, sr, CLARITY_HI_HZ)
    return Metrics(
        duration=round(len(x) / sr, 3),
        snr_db=round(snr, 2),
        snr_hi_db=round(snr_hi, 2),
        clarity=round(snr_lo + CLARITY_W * snr_hi, 2),
        speech_ratio=round(float(m.mean()), 4),
        bandwidth_hz=round(speech_bandwidth(x, sr, m, hop), 1),
        clip_runs=clipping_runs(x),
        longest_gap=round(gap, 3),
        peak_dbfs=round(20.0 * math.log10(peak + EPS), 2),
        dc_offset=round(float(np.mean(x)), 6) if x.size else 0.0,
    )


@dataclass
class Gate:
    """Soglie del worker (`Gate` di audio.py) piu' la finestra di durata D7."""
    min_sec: float = 12.0
    max_sec: float = 20.0
    min_snr_db: float = 22.0
    min_clarity: float = 36.0
    min_speech_ratio: float = 0.55
    max_speech_ratio: float = 0.98
    min_bandwidth_ratio: float = 0.78   # rispetto a Nyquist
    max_clip_runs: int = 4
    max_gap: float = 1.0


def _env_float(name, default):
    raw = (os.environ.get(name) or "").strip().replace(",", ".")
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def gate_from_env():
    return Gate(min_sec=_env_float("ABM_VOICE_CLONE_MIN_SEC", 12.0),
                max_sec=_env_float("ABM_VOICE_CLONE_MAX_SEC", 20.0))


def apply_gate(mt, sr, g=None):
    """Riempie `mt.reasons` con le chiavi i18n della spec §5.3, nell'ordine
    in cui l'utente le deve sentire: prima la durata (si vede a occhio),
    poi il rumore, le pause, la banda, la distorsione."""
    g = g or gate_from_env()
    nyq = sr / 2.0
    why = []
    if mt.duration < g.min_sec:
        why.append("vc_gate_short")
    elif mt.duration > g.max_sec:
        why.append("vc_gate_long")
    if mt.snr_db < g.min_snr_db or mt.clarity < g.min_clarity:
        why.append("vc_gate_noise")
    if mt.speech_ratio < g.min_speech_ratio or mt.longest_gap > g.max_gap:
        why.append("vc_gate_pauses")
    if mt.speech_ratio > g.max_speech_ratio:
        why.append("vc_gate_nopause")
    if mt.bandwidth_hz < g.min_bandwidth_ratio * nyq:
        why.append("vc_gate_band")
    if mt.clip_runs > g.max_clip_runs:
        why.append("vc_gate_clip")
    mt.reasons = why
    return mt
