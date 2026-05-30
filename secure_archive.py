"""Helper di sicurezza per parsing archivi (ZIP/EPUB/ABM) e XML.

Centralizza tre controlli ricorrenti su input untrusted:
  1. zip-slip:        normalizza path e rifiuta `..` / path assoluti
  2. zip-bomb:        cap su single-entry uncompressed e totale
  3. XML XXE/bomb:    parser defusedxml con fallback safe se assente

Tutti i limiti sono override-abili via env var ABM_ZIP_*.
"""
import os
import posixpath
import zipfile
from typing import Iterable

# Limiti zip-bomb (override via env)
ZIP_MAX_ENTRY_UNCOMPRESSED = int(os.environ.get(
    "ABM_ZIP_MAX_ENTRY_MB", "200")) * 1024 * 1024     # 200 MB per entry
ZIP_MAX_TOTAL_UNCOMPRESSED = int(os.environ.get(
    "ABM_ZIP_MAX_TOTAL_MB", "500")) * 1024 * 1024     # 500 MB totale
ZIP_MAX_COMPRESSION_RATIO = float(os.environ.get(
    "ABM_ZIP_MAX_RATIO", "200"))                      # uncompressed/compressed


class ZipSafetyError(ValueError):
    """Violazione di una policy zip-safety (slip, bomb, ratio)."""


def safe_zip_path(name: str, *, base: str = "") -> str:
    """Normalizza e valida un path interno a uno ZIP archive.

    - Rifiuta path assoluti, drive-letter, NUL bytes.
    - Rifiuta path che, una volta normalizzati, escono dalla root virtuale
      dell'archivio (zip-slip).

    Ritorna il path normalizzato (slash-separated, no leading `/`).
    """
    if not name or "\x00" in name:
        raise ZipSafetyError(f"invalid zip entry name: {name!r}")
    # Normalizza separator e collassa '..' componenti
    raw = name.replace("\\", "/")
    if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        raise ZipSafetyError(f"absolute path not allowed in zip: {name!r}")
    norm = posixpath.normpath(raw)
    if norm.startswith("../") or norm == ".." or "/../" in ("/" + norm + "/"):
        raise ZipSafetyError(f"path traversal in zip: {name!r}")
    if base:
        base_n = posixpath.normpath(base).rstrip("/")
        # Verifica che il path resti dentro la base virtuale
        if not (norm == base_n or norm.startswith(base_n + "/")):
            raise ZipSafetyError(
                f"path {name!r} escapes base {base!r}"
            )
    return norm


def check_zip_bomb(zf: zipfile.ZipFile,
                   max_entry: int = ZIP_MAX_ENTRY_UNCOMPRESSED,
                   max_total: int = ZIP_MAX_TOTAL_UNCOMPRESSED,
                   max_ratio: float = ZIP_MAX_COMPRESSION_RATIO) -> None:
    """Valida un archivio contro decompression bomb.

    Solleva ``ZipSafetyError`` se:
      - una singola entry supera ``max_entry`` byte uncompressed
      - la somma uncompressed di tutte le entries supera ``max_total``
      - la compression ratio di una entry supera ``max_ratio`` (zip-bomb classico)
    """
    total = 0
    for info in zf.infolist():
        if info.file_size > max_entry:
            raise ZipSafetyError(
                f"zip entry too large: {info.filename!r} "
                f"({info.file_size} > {max_entry} bytes)"
            )
        # Compression ratio check (solo per entries compresse non triviali)
        if info.compress_size > 0 and info.file_size > 4096:
            ratio = info.file_size / info.compress_size
            if ratio > max_ratio:
                raise ZipSafetyError(
                    f"zip-bomb suspect: {info.filename!r} ratio "
                    f"{ratio:.0f}:1 (max {max_ratio:.0f}:1)"
                )
        total += info.file_size
        if total > max_total:
            raise ZipSafetyError(
                f"zip total uncompressed too large: {total} > {max_total} bytes"
            )


def safe_xml_fromstring(data: bytes):
    """Parsing XML con defusedxml (XXE/billion-laughs protection).

    Fallback a xml.etree.ElementTree se defusedxml non disponibile (con warning).
    Python 3.7.1+ ha gia' XXE disattivato di default in ElementTree, ma
    defusedxml protegge anche da entity expansion bomb.
    """
    try:
        from defusedxml import ElementTree as _DET
        return _DET.fromstring(data)
    except ImportError:
        import xml.etree.ElementTree as _ET
        print("[secure_archive] WARN defusedxml not available, "
              "falling back to stdlib XML parser")
        return _ET.fromstring(data)


def iter_safe_zip_names(zf: zipfile.ZipFile, *, base: str = "") -> Iterable[str]:
    """Itera le entries di un zip filtrando quelle che violano zip-safety.
    Le entries non-safe vengono saltate con warning (non solleva)."""
    for info in zf.infolist():
        try:
            yield safe_zip_path(info.filename, base=base)
        except ZipSafetyError as e:
            print(f"[secure_archive] skipping unsafe entry: {e}")
            continue
