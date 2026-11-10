"""Copertine generate: fascia in alto col colore della lingua del libro
(06/11/2026), cosi' i libri di lingue diverse si riconoscono a colpo d'occhio."""
import pytest

import cover_utils

PIL = pytest.importorskip("PIL")


def _band(path):
    from PIL import Image
    with Image.open(path) as im:
        return im.convert("RGB").getpixel((im.width // 2, im.height // 10))


def _near(a, b, tol=6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))       # JPEG non e' esatto


def test_ogni_lingua_ha_la_sua_fascia(tmp_path):
    seen = set()
    for lang in ("it", "en", "de", "es", "pt", "nl", "fr"):
        p = tmp_path / f"{lang}.jpg"
        assert cover_utils._generate_fallback_cover(str(p), title="Libro", author="Autore",
                                                    target_size=200, lang=lang)
        assert _near(_band(p), cover_utils.COVER_BAND_COLORS[lang]), lang
        seen.add(cover_utils.COVER_BAND_COLORS[lang])
    assert len(seen) == 7


def test_indirizzo_del_sito_in_fondo(tmp_path, monkeypatch):
    from PIL import ImageDraw
    scritti = []
    originale = ImageDraw.ImageDraw.text

    def registra(self, xy, text, *a, **k):
        scritti.append((xy[1], text))
        return originale(self, xy, text, *a, **k)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", registra)
    assert cover_utils._generate_fallback_cover(str(tmp_path / "c.jpg"), title="Libro",
                                                author="Autore", target_size=1400)
    assert max(scritti)[1] == "https://audiobook-maker.com"
    assert max(scritti)[0] < 1400 - 80                           # dentro la copertina


def test_lingua_con_variante_o_sconosciuta():
    assert cover_utils.cover_band_color("pt-BR") == cover_utils.COVER_BAND_COLORS["pt"]
    assert cover_utils.cover_band_color("EN") == cover_utils.COVER_BAND_COLORS["en"]
    assert cover_utils.cover_band_color("") == cover_utils.COVER_BAND_DEFAULT
    assert cover_utils.cover_band_color("ja") == cover_utils.COVER_BAND_DEFAULT
    assert cover_utils.COVER_BAND_COLORS["it"] == cover_utils.COVER_BAND_DEFAULT   # l'ocra di sempre
