"""Immagine Open Graph (1200x630) di Audiobook Maker, servita da /og-image.png.

Il file vive in static/img/og-image.png (prima: ~480 righe di base64 qui).
"""
from io import BytesIO
from pathlib import Path

_IMG = Path(__file__).resolve().parent / "static" / "img" / "og-image.png"
_cache: dict = {}


def get_og_image() -> BytesIO:
    data = _cache.get("og")
    if data is None:
        data = _IMG.read_bytes()
        _cache["og"] = data
    return BytesIO(data)
