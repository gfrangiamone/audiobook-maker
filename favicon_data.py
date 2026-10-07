"""Favicon di Audiobook Maker, serviti dalle route Flask (Google vuole URL
veri, non data URI, per mostrarli nei risultati).

I file vivono in static/img/ (prima erano blob base64 dentro questo modulo:
400 righe di stringhe). Le funzioni restano per le route storiche e
ritornano un BytesIO fresco a ogni chiamata.

  - favicon.ico (16/32/48)   -> /favicon.ico
  - favicon-192.png          -> /favicon-192.png
  - apple-touch-icon.png     -> /apple-touch-icon.png
  - favicon.svg              -> /favicon.svg
"""
from io import BytesIO
from pathlib import Path

_IMG_DIR = Path(__file__).resolve().parent / "static" / "img"
_cache: dict = {}


def _bytes(name):
    data = _cache.get(name)
    if data is None:
        data = (_IMG_DIR / name).read_bytes()
        _cache[name] = data
    return data


def get_favicon_ico() -> BytesIO:
    return BytesIO(_bytes("favicon.ico"))


def get_favicon_png_192() -> BytesIO:
    return BytesIO(_bytes("favicon-192.png"))


def get_apple_touch_icon() -> BytesIO:
    return BytesIO(_bytes("apple-touch-icon.png"))


def get_favicon_svg() -> BytesIO:
    return BytesIO(_bytes("favicon.svg"))
