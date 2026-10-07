"""content_store — lettura dei contenuti editoriali da `content/`.

Modulo foglia (solo stdlib). Testi SEO, guide, privacy, supporto e la guida
sulle voci campionate stavano come dict e stringhe HTML dentro i moduli
Python (550 KB di letterali): ora sono file JSON/HTML in `content/`, e i
moduli tengono solo il codice che li assembla. Ogni file viene letto una
volta per processo.

    content/seo/content.json, tables.json
    content/guides/meta.json, <guide_id>/<lang>.html
    content/guides/voice-cloning-audiobook/{meta,sample_langs,texts}.json
    content/privacy/<lang>.json + <lang>.html, content/support/texts.json
"""
import copy
import json
from pathlib import Path

CONTENT_DIR = Path(__file__).resolve().parent / "content"
_cache: dict = {}


def content_path(*parts):
    return CONTENT_DIR.joinpath(*parts)


def content_text(*parts):
    key = ("text",) + parts
    if key not in _cache:
        _cache[key] = content_path(*parts).read_text(encoding="utf-8")
    return _cache[key]


def content_json(*parts):
    """Oggetto JSON del file, come COPIA: il chiamante puo' mutarlo (es.
    guide_content aggiunge la guida sulle voci campionate ai metadati)
    senza toccare la cache condivisa."""
    key = ("json",) + parts
    if key not in _cache:
        _cache[key] = json.loads(content_path(*parts).read_text(encoding="utf-8"))
    return copy.deepcopy(_cache[key])


def content_exists(*parts):
    return content_path(*parts).exists()
