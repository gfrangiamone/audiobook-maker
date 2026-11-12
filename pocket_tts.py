"""Pocket TTS (Kyutai) — motore a chunk diretto sul worker abm-pocket-worker.

Il worker gira su un VPS a canone fisso (repo gfrangiamone/abm-pocket-worker):
una chiamata `POST /v1/synthesize` per chunk, risposta PCM 16-bit mono a
24 kHz quando il chunk e' pronto. Il worker normalizza il testo italiano
(numeri, date, sigle) e tiene le voci di riferimento di ABM
(`voxcpm2/voci_inventate`) come stati gia' calcolati: la voce
`pocket:v1:it-IT/Chiara` diventa `it-IT/Chiara` sul worker.

Per ora serve solo al catalogo dei libri gratuiti: il motore si accende con
`ABM_POCKET_URL` + `ABM_POCKET_TOKEN` e non ha listino (costo marginale zero),
quindi non va acceso nell'unit di produzione finche' non ha un prezzo.
Velocita' ed emozione non si applicano: Pocket legge sempre al ritmo della voce.
"""
import requests

from env_utils import env_int, env_str
import pricing_common as _pricing
import retry_util as _retry
from slot_gate import SlotGate
from text_reflow import spoken_title_prefix
from voice_utils import POCKET_VOICE_PREFIX, is_pocket_voice

MODEL_ID = "v1"
MODEL_LABEL = "Pocket TTS"
SAMPLE_RATE = 24000                 # nativo del worker, fisso
CHUNK_MAX_CHARS = 280               # come VoxCPM: frasi brevi, meno parole saltate
_CHUNK_MIN_CHARS = 80
_CHUNK_CEIL_CHARS = 1000            # POCKET_MAX_CHUNK_CHARS del worker
# Sotto il centesimo: il prezzo Pocket (sempre 0) e' gratuito per `free_result`.
FREE_THRESHOLD_EUR = 0.01
# Il worker tiene il chunk in coda finche' non tocca a lui (POCKET_SYNC_TIMEOUT_S,
# 900 s): l'attesa HTTP la supera di poco.
_HTTP_TIMEOUT_S = 960

_gate = SlotGate(lambda: max_concurrency())


def base_url():
    return env_str("ABM_POCKET_URL").rstrip("/")


def api_token():
    return env_str("ABM_POCKET_TOKEN")


def is_available():
    """True sse indirizzo e token del worker sono configurati."""
    return bool(base_url() and api_token())


def max_concurrency():
    """Chunk in volo verso il worker su tutto il processo. Floor a 1."""
    return max(1, env_int("ABM_POCKET_MAX_CONCURRENCY", 32))


def per_job_concurrency():
    """Chunk in volo per singolo job: il worker ha un processo per vCPU (16)."""
    return max(1, env_int("ABM_POCKET_PER_JOB_CONCURRENCY", 16))


def attempts():
    """Tentativi per chunk: coprono un riavvio del worker (deploy, ~60 s)."""
    return max(1, env_int("ABM_POCKET_ATTEMPTS", 5))


def free_slots():
    return _gate.free()


def slot(timeout=None):
    return _gate.slot(timeout=timeout, what="Pocket concurrency slot")


def chunk_max_chars():
    """Cap caratteri/chunk (ABM_POCKET_CHUNK_CHARS), entro il limite del worker."""
    val = env_int("ABM_POCKET_CHUNK_CHARS", CHUNK_MAX_CHARS)
    return max(_CHUNK_MIN_CHARS, min(_CHUNK_CEIL_CHARS, val))


def free_threshold_eur():
    return FREE_THRESHOLD_EUR


def parse_voice_id(voice_id):
    """('v1', 'it-IT', 'Chiara') da 'pocket:v1:it-IT/Chiara'; ValueError altrimenti."""
    if not is_pocket_voice(voice_id):
        raise ValueError(f"Invalid Pocket voice ID: {voice_id!r}")
    model_key, _, ref = voice_id[len(POCKET_VOICE_PREFIX):].partition(":")
    locale, _, name = ref.partition("/")
    if model_key != MODEL_ID or len(locale) != 5 or locale[2] != "-" or not name:
        raise ValueError(f"Invalid Pocket voice ID: {voice_id!r} "
                         f"(expected 'pocket:{MODEL_ID}:<ll-CC>/<Nome>')")
    return model_key, locale, name


def compute_user_price_eur(chars, language=None):
    """Prezzo per `chars` caratteri: zero (VPS a canone fisso, nessun costo a
    carattere). Stessa forma degli altri motori per stime e audit."""
    chars = max(0, int(chars or 0))
    return {
        "chars": chars,
        "cost_usd": 0.0,
        "base_price_eur": 0.0,
        "margin_percent": 0.0,
        **_pricing.free_result(0.0, free_threshold_eur()),
    }


def estimate_book_cost(chapters, language="it", strip_round=True, strip_square=True):
    """Stima sui caratteri letti (corpo + titolo parlato), prezzo zero."""
    chars_per_chapter, chars_total, _ = _pricing.billable_chars(
        chapters, spoken_title_prefix, strip_round=strip_round, strip_square=strip_square)
    price = compute_user_price_eur(chars_total)
    return {
        "chars_total": chars_total,
        "chars_per_chapter": chars_per_chapter,
        "cost_usd": price["cost_usd"],
        "user_price_eur": price["user_price_eur"],
        "list_price_eur": price["list_price_eur"],
        "is_free": price["is_free"],
        "margin_percent": price["margin_percent"],
        "language": language,
        "model_key": MODEL_ID,
        "model_label": MODEL_LABEL,
    }


class PocketUnavailable(RuntimeError):
    """Worker non configurato (ABM_POCKET_URL / ABM_POCKET_TOKEN)."""


class PocketFatalError(RuntimeError):
    """Errore non ritentabile: voce assente sul worker, lingua o testo rifiutati (4xx)."""


class _PocketRetry(Exception):
    """Tentativo da rifare: 429/5xx (chunk fallito sul worker, riavvio, coda
    lunga) o errore di rete."""


_NET_ERRORS = (requests.RequestException, TimeoutError, ConnectionError)


def synthesize(text, voice_id, output_path, emotion=None, rate="+0%", max_attempts=None,
               session=None, sleep=None):
    """Sintetizza `text` sul worker e scrive il PCM in `output_path`.

    Ritorna dict success/bytes_written/sample_rate/channels/billable_chars/
    voice_name. `emotion` e `rate` sono accettati per simmetria con Speechify
    e ignorati. Raises PocketUnavailable, PocketFatalError, ValueError (voce),
    RuntimeError a tentativi esauriti.
    """
    if not is_available():
        raise PocketUnavailable("Pocket TTS not available (check ABM_POCKET_URL / ABM_POCKET_TOKEN)")
    _, locale, name = parse_voice_id(voice_id)
    if session is None:
        session = requests.Session()
    payload = {"text": text, "voice": f"{locale}/{name}", "lang": locale[:2], "normalize": True}
    headers = {"Authorization": f"Bearer {api_token()}"}
    url = base_url() + "/v1/synthesize"
    tries = max_attempts or attempts()

    def _once(_attempt):
        try:
            with slot():
                resp = session.post(url, json=payload, headers=headers, timeout=_HTTP_TIMEOUT_S)
        except _NET_ERRORS as e:
            raise _PocketRetry(f"{type(e).__name__}: {e}") from e
        if resp.status_code == 200:
            pcm = resp.content
            if not pcm:
                raise _PocketRetry("risposta senza audio")
            with open(output_path, "wb") as fp:
                fp.write(pcm)
            return {
                "success": True,
                "bytes_written": len(pcm),
                "sample_rate": SAMPLE_RATE,
                "channels": 1,
                "billable_chars": len(text),
                "voice_name": name,
            }
        detail = (getattr(resp, "text", "") or "")[:200]
        if _retry.is_transient_http(resp.status_code, none_is_transient=False):
            raise _PocketRetry(f"HTTP {resp.status_code}: {detail}")
        raise PocketFatalError(f"Pocket HTTP {resp.status_code} (fatal): {detail}")

    kw = {} if sleep is None else {"sleep": sleep}
    try:
        return _retry.retry_call(
            _once, attempts=tries, is_retryable=lambda e: isinstance(e, _PocketRetry),
            wait=lambda attempt, _e: _retry.backoff(attempt, base=5.0, cap=60.0), **kw)
    except _PocketRetry as e:
        raise RuntimeError(f"Pocket synthesis failed after {tries} attempts: {e}") from e
