"""env_utils — lettura unica delle variabili d'ambiente `ABM_*`.

Modulo foglia (solo stdlib). Sostituisce le ~20 copie locali di
`_env_int`/`_env_float`/`_env_bool`/`_f`/`_i`/`_b` che si erano accumulate nei
moduli, ognuna con una semantica un po' diversa (virgola decimale accettata o
no, stringa vuota = default o = errore, floor applicato o no).

Semantica unica:
- stringa assente o vuota (dopo strip)  -> default;
- numeri: virgola decimale accettata ("0,5"), `_` ignorato ("1_000");
  `env_int` accetta anche "3.0" (int(float(...)));
- valore malformato -> default, con un avviso su stderr UNA volta per nome
  (prima alcune copie crashavano all'import, altre tacevano);
- `floor`/`ceil` opzionali clampano il risultato (anche il default);
- `env_bool`: 1/true/yes/on -> True, 0/false/no/off -> False, altro -> default.

Le variabili si leggono A OGNI CHIAMATA: niente costanti di modulo congelate
all'import, salvo dove il chiamante lo decide esplicitamente.
"""
import os
import sys

_TRUE = frozenset({"1", "true", "yes", "on", "y", "t"})
_FALSE = frozenset({"0", "false", "no", "off", "n", "f"})
_warned = set()


def _raw(name, fallback=None):
    v = (os.environ.get(name) or "").strip()
    if not v and fallback:
        v = (os.environ.get(fallback) or "").strip()
    return v


def _warn(name, raw, default):
    if name in _warned:
        return
    _warned.add(name)
    print(f"[env_utils] WARNING: {name}={raw!r} non valido, uso il default {default!r}",
          file=sys.stderr, flush=True)


def _clamp(v, floor, ceil):
    if floor is not None and v < floor:
        v = floor
    if ceil is not None and v > ceil:
        v = ceil
    return v


def env_str(name, default="", *, fallback=None):
    """Stringa senza spazi ai bordi; vuota -> `default`. `fallback` e' un
    secondo nome di variabile da provare se il primo e' vuoto."""
    return _raw(name, fallback) or default


def env_float(name, default, *, floor=None, ceil=None, fallback=None):
    raw = _raw(name, fallback)
    if not raw:
        return _clamp(float(default), floor, ceil)
    try:
        return _clamp(float(raw.replace(",", ".").replace("_", "")), floor, ceil)
    except (TypeError, ValueError):
        _warn(name, raw, default)
        return _clamp(float(default), floor, ceil)


def env_int(name, default, *, floor=None, ceil=None, fallback=None):
    raw = _raw(name, fallback)
    if not raw:
        return _clamp(int(default), floor, ceil)
    try:
        return _clamp(int(float(raw.replace(",", ".").replace("_", ""))), floor, ceil)
    except (TypeError, ValueError, OverflowError):
        _warn(name, raw, default)
        return _clamp(int(default), floor, ceil)


def env_bool(name, default=False, *, fallback=None):
    raw = _raw(name, fallback).lower()
    if not raw:
        return bool(default)
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    _warn(name, raw, default)
    return bool(default)
