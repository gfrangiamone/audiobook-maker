"""ffmpeg_tools — l'unico punto che lancia ffmpeg e ffprobe (F2, 2026-10-10).

Modulo foglia (solo stdlib). Prima: flag di subprocess e decodifica leniente
definiti due volte (`audio_utils`, `voice_clone_audio`) e presi in prestito da
`voice_denoise`; tre lettori di durata via ffprobe; quattro lanci «nudi» di
ffmpeg senza timeout ne' flag (`tts_split._mp3_to_pcm_24k`,
`voxcpm_tts.apply_rate`, `voice_clone_demo.pcm_to_wav48`, il silenzio MP3).

- `SUBPROCESS_FLAGS`: su Windows evita la finestra console di ffmpeg/ffprobe.
- `TEXT_LENIENT`: l'output dei processi esterni e' materiale di log e non
  deve mai far fallire una conversione (ffmpeg tronca i nomi file nei log e
  su un titolo CJK il taglio cade a meta' carattere: incidente 23/08/2026).
- `tool(name)`: il binario nel PATH, `RuntimeError` se manca.
- `run(cmd, timeout)`: `subprocess.run` con flag, testo leniente e output
  catturato; `TimeoutExpired` e `OSError` escono al chiamante.
- `run_ffmpeg(args, timeout)`: `run(["ffmpeg", "-hide_banner", "-loglevel",
  "error", "-y", *args])`.
- `ffprobe_field(path, field, timeout)`: un campo di `format=` come stringa
  ("" se ffprobe manca, fallisce o scade); `probe_duration` (secondi, 0.0)
  e `probe_bitrate_kbps` (kbps, None) ci stanno sopra.
- `pcm_transcode(src, dst, *, out_rate, in_rate=None, channels=1,
  filters=None, timeout)`: qualunque ingresso (o PCM grezzo se `in_rate`)
  -> PCM s16le; False se ffmpeg manca, fallisce o scade (log, niente
  eccezione): i chiamanti degradano (silenzio, velocita' normale).
- `write_pcm_silence(path, seconds, rate, channels, width)`: zeri, senza
  ffmpeg. Costanti `PCM_SAMPLE_RATE` (24 kHz, il formato dei chunk Gemini),
  `PCM_CHANNELS`, `PCM_SAMPLE_WIDTH`.
- `temp_wav()`: context manager su un `.wav` temporaneo rimosso all'uscita.

I timeout sono generosi (>= 10x la durata attesa) e la scadenza finisce nel
log: aggiungerli dove mancavano e' un cambio di comportamento voluto dal
piano (F2), per non lasciare un thread di job appeso a un ffmpeg bloccato.
"""
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile

SUBPROCESS_FLAGS = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
TEXT_LENIENT = {"text": True, "encoding": "utf-8", "errors": "replace"}

PCM_SAMPLE_RATE = 24000
PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH = 2        # byte per campione (s16le)

DEFAULT_TIMEOUT = 600       # secondi: una transcodifica o un concat di un libro intero


def tool(name):
    """Percorso del binario `name` nel PATH; `RuntimeError` se manca."""
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} non trovato nel PATH")
    return path


def run(cmd, timeout=DEFAULT_TIMEOUT, **kw):
    """`subprocess.run` con flag Windows, testo leniente e output catturato.
    `TimeoutExpired`/`OSError` escono: chi chiama decide come degradare."""
    kw.setdefault("capture_output", True)
    return subprocess.run(list(cmd), timeout=timeout, **TEXT_LENIENT, **SUBPROCESS_FLAGS, **kw)


def run_ffmpeg(args, timeout=DEFAULT_TIMEOUT, **kw):
    """ffmpeg silenzioso (`-hide_banner -loglevel error -y`) con `args`."""
    return run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], timeout=timeout, **kw)


def ffprobe_field(path, field, timeout=10):
    """Il campo `field` della sezione `format` di ffprobe, come stringa
    ("" se ffprobe manca, fallisce, scade o non lo riporta)."""
    try:
        r = run(["ffprobe", "-v", "error", "-show_entries", f"format={field}",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)], timeout=timeout)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"[ffprobe] {field} di {os.path.basename(str(path))}: {e}")
        return ""
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def probe_duration(path, timeout=10):
    """Durata in secondi (float), 0.0 se non misurabile."""
    raw = ffprobe_field(path, "duration", timeout=timeout)
    try:
        return float(raw) if raw else 0.0
    except ValueError:
        return 0.0


def probe_bitrate_kbps(path, timeout=10):
    """Bitrate in kbps clampato a [32, 320], None se non misurabile."""
    raw = ffprobe_field(path, "bit_rate", timeout=timeout)
    try:
        bps = int(float(raw)) if raw else 0
    except ValueError:
        return None
    return max(32, min(320, round(bps / 1000))) if bps > 0 else None


def pcm_transcode(src, dst, *, out_rate, in_rate=None, channels=PCM_CHANNELS, filters=None,
                  timeout=DEFAULT_TIMEOUT, tag="ffmpeg"):
    """`src` -> `dst` PCM s16le mono/`channels` a `out_rate` Hz. `in_rate`
    dice che `src` e' PCM grezzo (s16le) a quel rate; `filters` e' un filtro
    audio (`-filter:a`). True se il file risulta non vuoto; su ffmpeg assente,
    errore o timeout stampa e ritorna False (il parziale viene rimosso)."""
    args = []
    if in_rate:
        args += ["-f", "s16le", "-ar", str(int(in_rate)), "-ac", str(channels)]
    args += ["-i", str(src)]
    if filters:
        args += ["-filter:a", filters]
    args += ["-f", "s16le", "-ar", str(int(out_rate)), "-ac", str(channels), str(dst)]
    try:
        r = run_ffmpeg(args, timeout=timeout)
        ok = r.returncode == 0
        detail = (r.stderr or "").strip()[-300:]
    except subprocess.TimeoutExpired:
        ok, detail = False, f"timeout dopo {timeout}s"
    except (subprocess.SubprocessError, OSError) as e:
        ok, detail = False, str(e)
    if ok and os.path.exists(dst) and os.path.getsize(dst) > 0:
        return True
    print(f"[{tag}] transcodifica PCM fallita: {detail or 'output vuoto'}")
    try:
        os.remove(dst)
    except OSError:
        pass
    return False


def write_pcm_silence(path, seconds, rate=PCM_SAMPLE_RATE, channels=PCM_CHANNELS,
                      width=PCM_SAMPLE_WIDTH):
    """`seconds` di silenzio PCM (zeri) in `path`; nessun processo esterno."""
    n_bytes = int(seconds * rate * channels * width)
    with open(path, "wb") as f:
        if n_bytes > 0:
            f.write(b"\x00" * n_bytes)


@contextlib.contextmanager
def temp_wav(suffix=".wav"):
    """Percorso di un file temporaneo, rimosso all'uscita (anche su errore)."""
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        yield tmp
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
