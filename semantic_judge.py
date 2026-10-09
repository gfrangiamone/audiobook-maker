"""Giudizi semantici tipizzati (TypeSafe System One).

Modulo foglia: stdlib + `typesafe_sdk`, nessun import dal progetto. Il
chiamante costruisce lo `state` e le domande, questo modulo si occupa solo
del client, dei timeout e del **fail-open**: un servizio irraggiungibile non
deve mai diventare un errore per l'utente, esattamente come il client LLM
riusato da `community_moderator`.

Perche' non un altro prompt LLM: qui la risposta e' gia' tipizzata (nessun
parser JSON da scrivere a mano) e le probabilita' sono calibrate, quindi la
soglia di decisione vive nel codice del chiamante e si cambia senza
riscrivere un prompt.

Configurazione (env, come tutto il resto dell'app):
  ABM_TYPESAFE_API_KEY   chiave; assente -> modulo disattivo (is_available False)
  ABM_TYPESAFE_ENABLE    "0" spegne tutto anche con la chiave presente
  ABM_TYPESAFE_MODEL     override del modello (default: quello dell'SDK)
  ABM_TYPESAFE_TIMEOUT   secondi per richiesta (default 15)
  ABM_TYPESAFE_RETRIES   ritentativi su 429/529/errori di rete (default 1)
"""
from __future__ import annotations

import os
from env_utils import env_float as _env_float, env_int as _env_int, env_str
import threading
import time

from jsonl_audit import MonthlyJsonl as _MonthlyJsonl

# L'SDK e' opzionale: in produzione arriva da requirements.txt, ma l'app deve
# avviarsi anche senza (installazione parziale, ambiente di test minimale).
try:
    from typesafe_sdk import (  # noqa: F401  (riesportati per i chiamanti)
        Choice,
        Noul,
        NoulCriteria,
        RetryPolicy,
        Score,
        TypeSafeClient,
        TypeSafeError,
    )
    _SDK_IMPORT_ERROR = ""
except Exception as e:  # noqa: BLE001 - qualunque problema di import = modulo off
    Choice = Noul = NoulCriteria = Score = None  # type: ignore[assignment]
    RetryPolicy = TypeSafeClient = None  # type: ignore[assignment]
    TypeSafeError = Exception  # type: ignore[misc,assignment]
    _SDK_IMPORT_ERROR = f"{type(e).__name__}: {e}"


_DEFAULT_TIMEOUT = 15.0
_DEFAULT_RETRIES = 1

_lock = threading.Lock()
_client = None
_client_key = ""          # chiave con cui e' stato creato il client in cache
_last_error_ts = 0.0
_last_error_msg = ""


def _env(name, default=""):
    return env_str(name, default)


def api_key():
    return _env("ABM_TYPESAFE_API_KEY")


def enabled():
    """False con ABM_TYPESAFE_ENABLE=0: kill-switch per spegnere i giudizi
    semantici in produzione senza toccare la chiave ne' il codice."""
    return _env("ABM_TYPESAFE_ENABLE", "1") not in ("0", "false", "no", "off")


def is_available():
    """True se SDK importato, kill-switch acceso e chiave presente."""
    return bool(TypeSafeClient is not None and enabled() and api_key())


def timeout_sec():
    return _env_float("ABM_TYPESAFE_TIMEOUT", _DEFAULT_TIMEOUT)


def _get_client():
    """Client condiviso, ricreato solo se la chiave cambia (rotazione)."""
    global _client, _client_key
    key = api_key()
    if not key or TypeSafeClient is None:
        return None
    with _lock:
        if _client is not None and _client_key == key:
            return _client
        retries = max(0, _env_int("ABM_TYPESAFE_RETRIES", _DEFAULT_RETRIES))
        kwargs = {
            "api_key": key,
            "timeout": timeout_sec(),
            # La RetryPolicy dell'SDK copre gia' 429/529 e gli errori di rete
            # con backoff: non si riscrive il ciclo a mano come in
            # community_moderator/abuse_watch.
        }
        if RetryPolicy is not None:
            kwargs["retry"] = RetryPolicy(max_retries=retries)
        model = _env("ABM_TYPESAFE_MODEL")
        if model:
            kwargs["model"] = model
        try:
            _client = TypeSafeClient(**kwargs)
            _client_key = key
        except Exception as e:  # noqa: BLE001
            _note_error(f"init fallita: {type(e).__name__}: {e}")
            _client, _client_key = None, ""
        return _client


def _note_error(msg):
    global _last_error_ts, _last_error_msg
    _last_error_ts = time.time()
    _last_error_msg = msg
    print(f"[semantic_judge] {msg}", flush=True)


def last_error():
    """(timestamp, messaggio) dell'ultimo errore: per la console admin."""
    return (_last_error_ts, _last_error_msg)


def ask(state, questions, *, timeout=None):
    """Una richiesta System One. Ritorna la risposta oppure None.

    Non solleva mai: il chiamante distingue "nessun giudizio" da "giudizio
    negativo" sul None e ripiega sull'euristica che aveva prima.

    `questions` e' un dict {id: Noul|Choice|Score}; le domande indipendenti
    sullo stesso stato vanno passate INSIEME, girano in parallelo lato
    servizio e costano una sola andata e ritorno.
    """
    if not is_available():
        return None
    if not questions:
        return None
    client = _get_client()
    if client is None:
        return None
    try:
        return client.system_one(
            state=state,
            questions=questions,
            timeout=timeout if timeout is not None else timeout_sec(),
        )
    except TypeSafeError as e:
        status = getattr(e, "status", "") or getattr(e, "status_code", "")
        rid = getattr(e, "request_id", "") or ""
        _note_error(f"{type(e).__name__} status={status} request_id={rid}: {e}")
        return None
    except Exception as e:  # noqa: BLE001 - mai bloccante per il chiamante
        _note_error(f"errore inatteso: {type(e).__name__}: {e}")
        return None


def noul(response, key, default=None):
    """Probabilita' 0..1 di una Noul, oppure `default` se manca.

    Manca legittimamente quando `ask` ha ritornato None: il chiamante che usa
    una soglia deve poter scrivere `noul(r, "spam", 0.0) >= soglia` senza
    controllare prima il None.
    """
    if response is None:
        return default
    try:
        ans = response.nouls.get(key)
    except Exception:  # noqa: BLE001
        return default
    if ans is None:
        return default
    try:
        return float(ans.noul)
    except (TypeError, ValueError):
        return default


def choice(response, key):
    """(valore, confidence) di una Choice, oppure (None, 0.0)."""
    if response is None:
        return (None, 0.0)
    try:
        ans = response.choices.get(key)
    except Exception:  # noqa: BLE001
        return (None, 0.0)
    if ans is None:
        return (None, 0.0)
    try:
        conf = float(getattr(ans, "confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return (getattr(ans, "choice", None), conf)


def score(response, key):
    """(livello, confidence) di uno Score, oppure (None, 0.0)."""
    if response is None:
        return (None, 0.0)
    try:
        ans = response.scores.get(key)
    except Exception:  # noqa: BLE001
        return (None, 0.0)
    if ans is None:
        return (None, 0.0)
    try:
        conf = float(getattr(ans, "confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return (getattr(ans, "score", None), conf)


def reset():
    """Scarta il client in cache (test, rotazione chiave da console admin)."""
    global _client, _client_key
    with _lock:
        _client, _client_key = None, ""


def sdk_import_error():
    """Messaggio dell'import fallito dell'SDK, vuoto se e' andato a buon fine."""
    return _SDK_IMPORT_ERROR


# ---------------------------------------------------------------------------
# Scheletro comune dei judge (section, translation, transcript, llm_output,
# voice_language_guard): modo da env, probabilita' per domanda, ritaglio dei
# testi, audit mensile. Prima ogni modulo ne aveva una copia.
# ---------------------------------------------------------------------------

def mode_from_env(var, modes, default):
    """Modo di un judge da `var`: un valore ignoto vale `default`, mai `on`
    (un errore di battitura nell'unit systemd non deve accendere niente)."""
    m = _env(var, default).lower()
    return m if m in modes else default


def probs(response, keys):
    """`{chiave: probabilita'}` per le Noul che hanno risposto; `{}` se la
    risposta manca. Una domanda senza risposta non compare: il chiamante
    la tratta come «nessun giudizio», mai come zero."""
    out = {}
    if response is None:
        return out
    for key in keys:
        p = noul(response, key)
        if p is not None:
            out[key] = float(p)
    return out


def clip(text, head, tail=0, marker=None):
    """Testo ridotto a `head` caratteri iniziali (+ `tail` finali). Con `tail`
    il segno di taglio e' su riga propria (`\n[...]\n`), altrimenti in coda
    (` [...]` o `marker`)."""
    t = (text or "").strip()
    if len(t) <= head + tail:
        return t
    if tail:
        return t[:head].rstrip() + (marker or "\n[...]\n") + t[-tail:].lstrip()
    return t[:head].rstrip() + (" [...]" if marker is None else marker)


_audit_stores: dict = {}


def append_monthly_audit(prefix, rec, tag=""):
    """Una riga in `ABM_DATA_DIR/<prefix>_YYYY-MM.jsonl`, solo se la cartella
    esiste (mai creata). Best-effort: un errore si stampa con `tag` e non
    si propaga, l'audit non ferma mai un job. Ritorna True se scritto."""
    try:
        store = _audit_stores.get(prefix)
        if store is None:
            store = _audit_stores[prefix] = _MonthlyJsonl(
                prefix, lambda: _env("ABM_DATA_DIR") or ".", compact=False, require_dir=True)
        if not _env("ABM_DATA_DIR"):
            return False
        return store.append(rec)
    except Exception as e:      # noqa: BLE001
        print(f"[{tag or prefix}] audit non scritto: {type(e).__name__}: {e}", flush=True)
        return False
