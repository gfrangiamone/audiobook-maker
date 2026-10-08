"""i18n — lingue dell'interfaccia e testi server-side.

Modulo foglia (solo stdlib). Prima: cinque loader identici dei file
`i18n/*.json`, quattro lookup con tre fallback diversi, cinque funzioni di
rilevamento lingua e ~55 copie di `.split("-")[0].lower()`.

- `LANGS`: le sette lingue dell'interfaccia (SPA, pagine, email).
- `norm_lang(code)`: 'it-IT' -> 'it', None -> '' (o `default`).
- `load(name)`: `i18n/<name>.json`, letto una volta; assente o corrotto -> {}
  con avviso, mai un'eccezione all'import.
- `pick(table, lang)`: testi della lingua con fallback PER CHIAVE su `en`
  (una chiave non tradotta esce in inglese, non vuota ne' con KeyError);
  `merge=False` restituisce il valore intero della lingua o del fallback.
- `browser_lang(accept_language)`: primo tag di Accept-Language, o con
  `ranked=True` il primo tag supportato in ordine di q.
- `choose_lang(candidates, supported)`: il primo candidato tradotto.
"""
import json
import re
import sys
from pathlib import Path

LANGS = ("it", "en", "fr", "es", "de", "zh", "hi")
I18N_DIR = Path(__file__).resolve().parent / "i18n"
_cache: dict = {}
_ACCEPT_RE = re.compile(r"([a-zA-Z]{2,3})(?:-[a-zA-Z0-9]+)*(?:;q=([0-9.]+))?")


def norm_lang(code, default=""):
    """Codice lingua a due lettere, minuscolo, senza regione: 'it-IT' -> 'it'."""
    s = (str(code) if code is not None else "").strip()
    if not s:
        return default
    return s.split("-")[0].strip().lower() or default


def load(name):
    """`i18n/<name>.json` come dict (cache per processo). Un file assente o
    illeggibile da' {} e un avviso: le pagine degradano in inglese/chiavi
    vuote invece di impedire l'avvio."""
    if name not in _cache:
        path = I18N_DIR / f"{name}.json"
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            _cache[name] = data if isinstance(data, dict) else {}
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: Could not load i18n/{name}.json: {e}", file=sys.stderr, flush=True)
            _cache[name] = {}
    return _cache[name]


def pick(table, lang, *, fallback="en", merge=True, base=None):
    """Testi della lingua `lang` da `table` (lingua -> dict).

    `merge=True`: dict nuovo = `base` (se dato) + fallback + lingua, chiave
    per chiave. `merge=False`: `table[lang]` se la lingua esiste, altrimenti
    `table[fallback]` (il valore intero, qualunque tipo sia).
    """
    code = norm_lang(lang)
    if not merge:
        if code in table:
            return table[code]
        return table[fallback] if fallback in table else None
    out = dict(base or {})
    out.update(table.get(fallback) or {})
    if code and code != fallback:
        out.update(table.get(code) or {})
    return out


def browser_lang(accept_language, supported=None, *, ranked=False, default=""):
    """Lingua dall'header Accept-Language.

    `ranked=False`: il primo tag cosi' com'e' ('it-IT,en;q=0.8' -> 'it'),
    `default` se vuoto. `ranked=True`: i tag ordinati per q, il primo
    presente in `supported`; `default` se nessuno lo e'.
    """
    accept = accept_language or ""
    if not ranked:
        first = accept.split(",")[0].split(";")[0].strip()
        return norm_lang(first) if first else default
    tags = _ACCEPT_RE.findall(accept)
    tags.sort(key=lambda t: float(t[1]) if t[1] else 1.0, reverse=True)
    for tag, _q in tags:
        code = tag.lower()
        if supported is None or code in supported:
            return code
    return default


def choose_lang(candidates, supported, default="en"):
    """Il primo candidato non vuoto presente in `supported` (dict o insieme
    delle lingue tradotte), altrimenti `default`."""
    for cand in candidates:
        c = (cand or "").strip().lower()
        if c and c in supported:
            return c
    return default
