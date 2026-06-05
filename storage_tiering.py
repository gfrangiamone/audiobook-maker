"""Logica caldo/freddo del tiering storage (pura, no Flask, no boto3).

- key_for_path: path locale -> chiave S3 (relativa a ABM_DATA_DIR, posix).
- hot_window_sec: durata finestra calda per il job (standard vs PREMIUM).
- marker .cloud_uploaded: traccia su disco quando un output_dir è stato
  caricato su cold storage (sopravvive a restart del worker).
- is_offloadable: estensioni dei file di output da spostare su cold.
"""
import os
from pathlib import Path

_DATA_DIR = Path(os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data")).resolve()
_HOT_SEC = int(os.environ.get("ABM_HOT_WINDOW_SEC", "64800"))
_HOT_GEMINI_SEC = int(os.environ.get("ABM_HOT_WINDOW_GEMINI_SEC", "172800"))

_OFFLOADABLE_EXT = (".mp3", ".m4b", ".zip", ".abm", ".epub", ".txt")
# File .txt transitori che possono comparire in output_*/ ma NON sono output
# finali (es. "<output>.mp3.filelist.txt" creato/rimosso da _concatenate_mp3;
# "<output>.m4b.metadata.txt" scritto da FFmpeg e orfanato su errore).
# Esclusi per nome per non offloadarli come se fossero traduzioni .txt.
_NON_OFFLOADABLE_SUFFIX = (".filelist.txt", ".metadata.txt")
_MARKER_NAME = ".cloud_uploaded"
_GEN_COMPLETE_NAME = ".generation_complete"


def _is_gemini_voice(voice):
    return bool(voice) and isinstance(voice, str) and voice.startswith("gemini:")


def key_for_path(local_path):
    """Chiave S3 = path relativo a ABM_DATA_DIR in formato posix.
    None se il path è fuori dalla data dir (sicurezza)."""
    try:
        rel = Path(local_path).resolve().relative_to(_DATA_DIR)
    except (ValueError, OSError):
        return None
    return rel.as_posix()


def hot_window_sec(job):
    """Durata finestra calda locale per il job. PREMIUM/Gemini -> finestra estesa."""
    v = ""
    if isinstance(job, dict):
        v = job.get("voice", "") or job.get("opt_voice", "")
    return _HOT_GEMINI_SEC if _is_gemini_voice(v) else _HOT_SEC


def is_offloadable(filename):
    """True se il file è un output da spostare su cold (per estensione).
    Esclude i .txt transitori (es. *.filelist.txt) che non sono output finali."""
    name = str(filename).lower()
    if name.endswith(_NON_OFFLOADABLE_SUFFIX):
        return False
    return name.endswith(_OFFLOADABLE_EXT)


def mark_cloud_uploaded(output_dir, when):
    """Scrive il marker con il timestamp di completamento upload."""
    try:
        (Path(output_dir) / _MARKER_NAME).write_text(str(float(when)), encoding="utf-8")
    except OSError:
        pass


def cloud_uploaded_at(output_dir):
    """Timestamp dal marker, o None se assente/illeggibile."""
    m = Path(output_dir) / _MARKER_NAME
    if not m.exists():
        return None
    try:
        return float(m.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def mark_generation_complete(output_dir, when):
    """Marca un output_dir come 'generazione + assemblaggio M4B/MP3 conclusi'.
    Scritto a COMPLETE, DOPO la conversione: la presenza del marker garantisce
    che i file (in particolare l'.m4b col suo atom moov finale) sono finalizzati
    e quindi offloadabili su cold senza rischio di copiare un file mid-write."""
    try:
        (Path(output_dir) / _GEN_COMPLETE_NAME).write_text(str(float(when)), encoding="utf-8")
    except OSError:
        pass


def generation_complete_at(output_dir):
    """Timestamp dal marker .generation_complete, o None se assente/illeggibile."""
    m = Path(output_dir) / _GEN_COMPLETE_NAME
    if not m.exists():
        return None
    try:
        return float(m.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
