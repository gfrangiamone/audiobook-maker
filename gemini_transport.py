"""Contratto di trasporto per la sintesi Gemini TTS e adapter Cloudflare.

Modulo foglia: importa solo stdlib e `requests`. Non importa mai `gemini_tts`
(convenzione di progetto n. 1 sugli import circolari).

Un adapter di trasporto ha questa firma:

    call(*, final_text, voice_name, model_key, model_id, timeout_ms,
         temperature) -> {"pcm": bytes,
                          "input_tokens": int | None,
                          "output_tokens": int | None}

e solleva `TransportError` e nient'altro. `input_tokens`/`output_tokens` valgono
None quando il provider non li restituisce: la stima spetta al chiamante, che
conosce il modello.
"""

import base64
import binascii
import os

import requests

TRANSPORT_KINDS = frozenset({
    # Riprovabile con lo stesso payload: glitch, 5xx, timeout, risposta vuota.
    "retryable",
    # 429 esplicito: riprovabile ma con attesa dettata dal provider.
    "rate_limited",
    # Quota giornaliera esaurita: riprovare oggi non serve.
    "quota_daily",
    # Il provider rifiuta il contenuto: riprovare lo stesso testo non serve.
    "content_rejected",
    # Il backend e' fuori uso (credito esaurito, indisponibilita' prolungata):
    # e' questo il kind che fa scattare il circuit breaker.
    "backend_down",
    # Errore deterministico di configurazione o di parametri: nessun retry,
    # nessun failover, va corretto dall'operatore.
    "fatal",
})


class TransportError(RuntimeError):
    """Sola eccezione che un adapter di trasporto puo' sollevare.

    Sottoclasse di RuntimeError per non peggiorare il comportamento di un
    eventuale caller storico che intercettava RuntimeError.

    Args:
        kind: uno di TRANSPORT_KINDS. Determina la reazione del chiamante.
        retry_after_sec: attesa suggerita dal provider, se dichiarata.
        billed: True se la chiamata e' stata comunque addebitata. Sul piano
            partner-model di Cloudflare una HTTP 200 e' addebitata anche quando
            il corpo non contiene audio; le 4xx/5xx non lo sono.
        http_status: status HTTP grezzo, per diagnostica.
        provider_code: codice di errore proprietario del provider.
    """

    def __init__(self, message, *, kind, retry_after_sec=None,
                 billed=False, http_status=None, provider_code=None):
        if kind not in TRANSPORT_KINDS:
            raise ValueError(f"kind sconosciuto: {kind!r}")
        super().__init__(message)
        self.kind = kind
        self.retry_after_sec = retry_after_sec
        self.billed = bool(billed)
        self.http_status = http_status
        self.provider_code = provider_code


CF_API_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run"
# Prefisso del data URI restituito da Cloudflare: PCM s16le 24 kHz mono, senza
# header RIFF. Identico al payload `inline_data` di Vertex: e' questa
# coincidenza che rende lecito il failover a meta' job.
_CF_AUDIO_PREFIX = "base64,"
# Distingue il 7003 deterministico (parametro rifiutato) da quello transitorio
# (modello sovraccarico). Se il formato del messaggio cambiasse, il degrado e'
# qualche retry sprecato, non un comportamento scorretto.
_CF_INVALID_VALUE_MARK = "Invalid value at "
# Esito standard per gli errori di audio nella risposta HTTP 200: riprovabile
# e fatturato (Cloudflare addebita le 200 comunque).
_CF_200_ERROR_KWARGS = {"kind": "retryable", "billed": True, "http_status": 200}


def _cf_first_error(body):
    """(codice, messaggio) del primo errore Cloudflare, o (None, "")."""
    try:
        errors = body.get("errors") or []
        if errors:
            first = errors[0]
            return first.get("code"), str(first.get("message") or "")
    except AttributeError:
        pass
    return None, ""


def _interpret_cloudflare_response(resp):
    """Traduce una risposta Cloudflare nel contratto di trasporto.

    Separata da `cloudflare_call` perche' e' la parte che merita test senza
    HTTP: la tabella di mappatura e' il cuore del comportamento in avaria.
    """
    status = resp.status_code
    try:
        body = resp.json()
    except (ValueError, AttributeError):
        body = None

    if status == 200:
        # Doctrine di fatturazione verificata sul campo: una 200 e' addebitata
        # comunque, anche se il corpo non contiene audio.
        audio = None
        if isinstance(body, dict):
            audio = (body.get("result") or {}).get("audio")
        if not audio:
            raise TransportError(
                "Cloudflare ha risposto 200 senza audio",
                **_CF_200_ERROR_KWARGS)
        idx = audio.find(_CF_AUDIO_PREFIX)
        raw = audio[idx + len(_CF_AUDIO_PREFIX):] if idx >= 0 else audio
        try:
            # validate=True: rifiuta silenziosamente i caratteri fuori dall'alfabeto
            # base64, invece di decodificare comunque un payload troncato/corrotto.
            # Incidenti passati: edge-tts troncato consegnato, PCM assembly troncato.
            pcm = base64.b64decode(raw, validate=True)
        except (ValueError, TypeError, binascii.Error) as e:
            raise TransportError(
                "audio Cloudflare non decodificabile",
                **_CF_200_ERROR_KWARGS) from e
        if not pcm:
            raise TransportError(
                "audio Cloudflare vuoto dopo la decodifica",
                **_CF_200_ERROR_KWARGS)
        # L'API non restituisce i token: la stima spetta al chiamante, che
        # conosce il modello e il rapporto token/secondo.
        return {"pcm": pcm, "input_tokens": None, "output_tokens": None}

    code, message = _cf_first_error(body or {})

    if status == 402 or code == 2021:
        raise TransportError(
            f"credito Cloudflare esaurito (codice {code}): {message}",
            kind="backend_down", http_status=status, provider_code=code)

    if status == 422 or code == 2017:
        raise TransportError(
            f"contenuto rifiutato da Cloudflare (codice {code}): {message}",
            kind="content_rejected", http_status=status, provider_code=code)

    if status == 429:
        raise TransportError(
            f"Cloudflare rate limit: {message}",
            kind="rate_limited", http_status=status, provider_code=code)

    if status == 404:
        # Modello inesistente lato Cloudflare: errore di configurazione, non
        # un guasto transitorio. Deve precedere il ramo 7003 perche' e' lo
        # stesso codice dell'overload.
        raise TransportError(
            f"modello Cloudflare inesistente: {message}",
            kind="fatal", http_status=status, provider_code=code)

    if status == 400 and code == 7003:
        if _CF_INVALID_VALUE_MARK in message:
            raise TransportError(
                f"parametro rifiutato da Cloudflare: {message}",
                kind="fatal", http_status=status, provider_code=code)
        raise TransportError(
            f"Cloudflare temporaneamente non disponibile: {message}",
            kind="retryable", http_status=status, provider_code=code)

    detail = message or (getattr(resp, "text", "") or "")[:200]
    raise TransportError(
        f"Cloudflare HTTP {status}: {detail}",
        kind="retryable", http_status=status, provider_code=code)


def cloudflare_call(*, final_text, voice_name, model_key, model_id,
                    timeout_ms, temperature):
    """Adapter di trasporto Cloudflare Workers AI.

    Una chiamata, nessun retry: la politica di retry resta al chiamante.
    Il token viene letto dall'ambiente e non compare mai in un messaggio di
    errore: gli header non vengono mai serializzati in un'eccezione.
    """
    account_id = os.environ.get("ABM_CF_ACCOUNT_ID", "").strip()
    token = os.environ.get("ABM_CF_API_TOKEN", "").strip()
    if not account_id or not token:
        raise TransportError(
            "backend Cloudflare non configurato "
            "(ABM_CF_ACCOUNT_ID / ABM_CF_API_TOKEN assenti)",
            kind="fatal")

    payload = {"model": model_id,
               "input": {"text": final_text, "voice": voice_name}}
    if temperature is not None:
        try:
            payload["input"]["temperature"] = float(temperature)
        except (ValueError, TypeError) as e:
            raise TransportError(
                f"temperatura non valida: {temperature!r}",
                kind="fatal") from e

    # model_key e' parte della firma uniforme dell'adapter (come definito dal brief
    # e usato nei task successivi), ma non e' usato qui: il modello viene sempre
    # identificato via model_id in Cloudflare. Il parametro e' presente per
    # coerenza con vertex_call, non deve essere rimosso.

    try:
        resp = requests.post(
            CF_API_URL.format(account_id=account_id),
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=timeout_ms / 1000.0,
        )
    except requests.Timeout as e:
        # Il timeout lato client lascia ambiguo l'addebito: la chiamata
        # potrebbe essere arrivata a destinazione. Non dichiariamo billed.
        raise TransportError("timeout verso Cloudflare",
                             kind="retryable") from e
    except requests.RequestException as e:
        raise TransportError(f"errore di rete verso Cloudflare: "
                             f"{type(e).__name__}", kind="retryable") from e

    return _interpret_cloudflare_response(resp)
