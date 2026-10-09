"""retry_util — ritentativi con backoff per le chiamate di rete.

Modulo foglia (solo stdlib). Prima: nove loop `for attempt in range(n)` +
`time.sleep(2 ** attempt)` nei motori TTS, nell'offload cloud e nelle push,
tre predicati «status HTTP transitorio» e due parser di `Retry-After`.

- `retry_call(fn, attempts=, is_retryable=, wait=, sleep=, on_retry=)`:
  chiama `fn(attempt)` fino a `attempts` volte; un'eccezione non ritentabile
  o l'ultima esce cosi' com'e'. `retry_call_async` per le coroutine.
- `backoff(attempt, base=1, factor=2, cap=None)`: `base * factor**attempt`.
- `is_transient_http(status)`: 429 o 5xx (e `None` = errore di rete).
- `parse_retry_after(value)`: secondi da un header `Retry-After` o da un
  messaggio ("retryDelay: 22s", "retry in 6h12m51.7s"), `None` se assente.
- `retry_after_from_error(err)`: come sopra, leggendo anche i `details`
  strutturati dell'SDK Google.
"""
import asyncio
import re
import time

# Le stesse espressioni che gemini_tts usava da solo: 'retryDelay: 22371s'
# (SDK Google) e 'retry in 6h12m51.7s' / 'retry in 5s' (messaggi 429).
_RE_RETRY_SECS = re.compile(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", re.IGNORECASE)
_RE_RETRY_HMS = re.compile(r"retry\s+in\s+(?:(\d+)h)?(?:(\d+)m)?([\d.]+)?s", re.IGNORECASE)


class GiveUp(Exception):
    """Da sollevare dentro `fn` per fermare i ritentativi senza un errore
    proprio: `retry_call` la rilancia subito. Non usata dai motori, che hanno
    le loro eccezioni fatali: resta per i chiamanti senza una gerarchia."""


def backoff(attempt, base=1.0, factor=2.0, cap=None):
    """Attesa esponenziale per il tentativo `attempt` (0 = primo)."""
    wait = float(base) * (float(factor) ** attempt)
    return min(wait, cap) if cap is not None else wait


def is_transient_http(status, *, none_is_transient=True):
    """429 o 5xx: il server respira, si riprova. `None` (nessuno status: la
    connessione e' caduta) conta come transitorio salvo diversa richiesta."""
    if status is None:
        return none_is_transient
    try:
        s = int(status)
    except (TypeError, ValueError):
        return False
    return s == 429 or 500 <= s <= 599


def parse_retry_after(value):
    """Secondi da aspettare da un valore `Retry-After` (numero) o da un
    messaggio di errore con `retryDelay: 22s` / `retry in 6h12m51.7s`.
    `None` se non c'e' niente di leggibile; mai negativo."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    s = str(value).strip()
    if not s:
        return None
    try:
        return max(0.0, float(s))
    except ValueError:
        pass
    m = _RE_RETRY_SECS.search(s)
    if m:
        return float(m.group(1))
    m = _RE_RETRY_HMS.search(s)
    if m:
        h, mn, sc = int(m.group(1) or 0), int(m.group(2) or 0), float(m.group(3) or 0)
        return h * 3600 + mn * 60 + sc
    return None


def retry_after_from_error(err):
    """`retry_after` di un errore dell'SDK Google: prima `details[*].retry_delay`
    (oggetto o dict, `seconds` o stringa "22s"), poi il testo del messaggio."""
    try:
        details = getattr(err, "details", None) or []
        for d in details:
            rd = getattr(d, "retry_delay", None) or (d.get("retryDelay") if isinstance(d, dict) else None)
            if rd is None:
                continue
            if isinstance(rd, str) and rd.endswith("s"):
                return float(rd[:-1])
            secs = rd.get("seconds") if isinstance(rd, dict) else getattr(rd, "seconds", None)
            if secs is not None:
                return float(secs)
    except Exception:  # noqa: BLE001 - un dettaglio malformato non e' un retry_after
        pass
    return parse_retry_after(str(err))


def _wait_for(wait, attempt, exc):
    if callable(wait):
        return float(wait(attempt, exc))
    return backoff(attempt, base=float(wait))


def retry_call(fn, *, attempts, is_retryable=None, wait=1.0, sleep=time.sleep,
               on_retry=None):
    """Chiama `fn(attempt)` (attempt da 0) fino a `attempts` volte.

    - `is_retryable(exc)` False, o `GiveUp`: l'eccezione esce subito;
    - `wait`: base dell'esponenziale (1 -> 1, 2, 4...) oppure
      `wait(attempt, exc) -> secondi`;
    - `on_retry(attempt, exc, seconds)` e' chiamata prima di ogni attesa;
    - esauriti i tentativi, rilancia l'ultima eccezione.
    """
    attempts = max(1, int(attempts))
    for attempt in range(attempts):
        try:
            return fn(attempt)
        except GiveUp:
            raise
        except Exception as e:  # noqa: BLE001 - e' il punto: decidere se ritentare
            if attempt >= attempts - 1 or (is_retryable is not None and not is_retryable(e)):
                raise
            seconds = _wait_for(wait, attempt, e)
            if on_retry is not None:
                on_retry(attempt, e, seconds)
            if seconds > 0:
                sleep(seconds)
    raise RuntimeError("unreachable")


async def retry_call_async(fn, *, attempts, is_retryable=None, wait=1.0,
                           sleep=asyncio.sleep, on_retry=None):
    """Come `retry_call` per una coroutine `fn(attempt)`."""
    attempts = max(1, int(attempts))
    for attempt in range(attempts):
        try:
            return await fn(attempt)
        except GiveUp:
            raise
        except Exception as e:  # noqa: BLE001
            if attempt >= attempts - 1 or (is_retryable is not None and not is_retryable(e)):
                raise
            seconds = _wait_for(wait, attempt, e)
            if on_retry is not None:
                on_retry(attempt, e, seconds)
            if seconds > 0:
                await sleep(seconds)
    raise RuntimeError("unreachable")
