"""Immagine Open Graph (1200x630) di Audiobook Maker, servita da /og-image.png.

Il file vive in static/img/og-image.png (prima: ~480 righe di base64 qui).
I meta tag la citano con og_image_url(): il ?v=<sha1> cambia a ogni nuova
immagine, cosi' Facebook/WhatsApp/LinkedIn non riusano l'anteprima in cache.
"""
import hashlib
from io import BytesIO
from pathlib import Path

_IMG = Path(__file__).resolve().parent / "static" / "img" / "og-image.png"
_cache: dict = {}


def _data() -> bytes:
    data = _cache.get("og")
    if data is None:
        data = _IMG.read_bytes()
        _cache["og"] = data
    return data


def get_og_image() -> BytesIO:
    return BytesIO(_data())


def og_image_url(base_url: str = "") -> str:
    """URL assoluto (o relativo se base_url vuoto) con impronta del file."""
    v = _cache.get("v")
    if v is None:
        v = hashlib.sha1(_data()).hexdigest()[:8]
        _cache["v"] = v
    return f"{base_url}/og-image.png?v={v}"
