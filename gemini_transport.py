"""Contratto di trasporto per la sintesi Gemini TTS e adapter Cloudflare / OpenRouter.

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
from env_utils import env_str

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


def _cf_error_code(value):
    """Normalizza il codice d'errore a int quando possibile.

    Cloudflare documenta codici numerici, ma un proxy davanti all'API puo'
    rimandarli come stringa ("2021"): senza normalizzazione il confronto
    `code == 2021` fallirebbe e un credito esaurito verrebbe classificato
    `retryable`, cioe' ritentato all'infinito invece di far scattare il
    breaker. La classificazione non deve dipendere dal tipo JSON.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return value or None


def _cf_error_pair(item):
    """(codice, messaggio) da un singolo elemento di errore, in qualunque forma."""
    if isinstance(item, dict):
        message = item.get("message")
        if message is None:
            message = item.get("error") or item.get("detail") or ""
        return _cf_error_code(item.get("code")), str(message or "")
    if item is None:
        return None, ""
    return None, str(item)


def _cf_first_error(body):
    """(codice, messaggio) del primo errore Cloudflare, o (None, "").

    Non solleva mai: il contratto di trasporto ammette una sola eccezione
    (`TransportError`) e questa funzione e' chiamata sul percorso d'avaria,
    cioe' proprio quando il corpo della risposta ha la forma meno prevedibile.
    Regge `errors` come array, oggetto singolo, mappa indicizzata, stringa,
    null o assente, e un `body` che non sia affatto un dizionario.
    """
    try:
        if not isinstance(body, dict):
            # Corpo non-oggetto (stringa, lista, null): niente codice, ma il
            # testo e' comunque diagnostica utile e non va perso.
            if body is None:
                return None, ""
            if isinstance(body, (list, tuple)):
                return _cf_error_pair(body[0]) if body else (None, "")
            return None, str(body)

        errors = body.get("errors")
        if errors is None:
            errors = body.get("error")
        if errors is None:
            # Alcune risposte mettono code/message al primo livello.
            if "code" in body or "message" in body:
                return _cf_error_pair(body)
            return None, ""

        if isinstance(errors, (list, tuple)):
            return _cf_error_pair(errors[0]) if errors else (None, "")
        if isinstance(errors, dict):
            if "code" in errors or "message" in errors:
                return _cf_error_pair(errors)
            # Mappa indicizzata ({"0": {...}}): si prende il primo valore.
            for value in errors.values():
                return _cf_error_pair(value)
            return None, ""
        return _cf_error_pair(errors)
    except Exception:
        # Nessuna forma di risposta puo' far uscire dall'adapter
        # un'eccezione diversa da TransportError.
        return None, ""


def _interpret_cloudflare_response(resp):
    """Traduce una risposta Cloudflare nel contratto di trasporto.

    Separata da `cloudflare_call` perche' e' la parte che merita test senza
    HTTP: la tabella di mappatura e' il cuore del comportamento in avaria.
    """
    status = resp.status_code
    try:
        body = resp.json()
    except Exception:
        # Corpo vuoto, non-JSON, o decoder che solleva un'eccezione
        # proprietaria: nessuna di queste e' una TransportError, quindi
        # nessuna puo' uscire da qui. Si prosegue con body=None e la
        # classificazione ricade sullo status HTTP.
        body = None

    if status == 200:
        # Dottrina di fatturazione verificata sul campo: una 200 e' addebitata
        # comunque, anche se il corpo non contiene audio.
        audio = None
        if isinstance(body, dict):
            result = body.get("result")
            if isinstance(result, dict):
                audio = result.get("audio")
        # Un `audio` che non sia una stringa non e' decodificabile: va trattato
        # come "200 senza audio" (retryable e fatturato), non fatto esplodere
        # su `.find` con un AttributeError fuori contratto.
        if not audio or not isinstance(audio, str):
            raise TransportError(
                "Cloudflare ha risposto 200 senza audio",
                **_CF_200_ERROR_KWARGS)
        idx = audio.find(_CF_AUDIO_PREFIX)
        raw = audio[idx + len(_CF_AUDIO_PREFIX):] if idx >= 0 else audio
        try:
            # validate=True: solleva sui caratteri fuori dall'alfabeto base64 invece
            # di scartarli in silenzio decodificando un payload troncato/corrotto.
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

    code, message = _cf_first_error(body)

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
    account_id = env_str("ABM_CF_ACCOUNT_ID")
    token = env_str("ABM_CF_API_TOKEN")
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

    try:
        return _interpret_cloudflare_response(resp)
    except TransportError:
        raise
    except Exception as e:
        # Rete di sicurezza del contratto: qualunque forma inattesa della
        # risposta deve uscire come TransportError classificata, mai come
        # eccezione grezza (che il chiamante non intercetta e che nasconde la
        # causa vera dietro un `KeyError: 0` nei log). Solo il nome del tipo,
        # mai `str(e)`: la stessa disciplina di redazione del ramo di rete.
        raise TransportError(
            f"risposta Cloudflare non interpretabile: {type(e).__name__}",
            kind="retryable",
            http_status=getattr(resp, "status_code", None)) from e


# === Adapter OpenRouter ======================================================
# OpenRouter rivende i modelli Gemini TTS (AI Studio + Vertex global dietro un
# solo endpoint, fallback automatico fra i due) a listino Google senza IVA,
# con una commissione sull'acquisto del credito. Probe 08-12/10/2026: PCM
# s16le 24 kHz mono grezzo (stesso formato interno di Vertex e Cloudflare, da
# cui il failover a meta' job), nessun usage nella risposta (i token li
# stima il chiamante), `instructions` = stile per il 3.8 (il 3.1 lo ignora e
# legge lo stile dal blocco inline del testo). `provider.order/only` sono
# ignorati su questo endpoint: non si puo' scegliere fra AI Studio e Vertex.
OR_API_URL = "https://openrouter.ai/api/v1/audio/speech"
# Il generation id viaggia nell'header: `GET /generation?id=` lo risolve dopo
# ~20 s con i token nativi e il costo esatto. Non e' sul percorso caldo.
OR_GENERATION_HEADER = "X-Generation-Id"
# Esito standard per una 200 senza audio: riprovabile; l'addebito non e'
# certo (OpenRouter fattura a token di output) e non lo dichiariamo.
_OR_200_ERROR_KWARGS = {"kind": "retryable", "billed": False, "http_status": 200}
# Marcatori di errore deterministico nel messaggio 400 di OpenRouter.
_OR_FATAL_MARKS = ("does not exist", "not a valid model", "is not a text-to-speech",
                   "invalid_value", "ZodError", "Unrecognized key")
# Un 400 opaco del provider ("Provider returned 400"): voce fuori enum, testo
# vuoto, ma anche un rifiuto transitorio a monte. Non e' distinguibile dal
# messaggio: riprovabile (3 tentativi, poi il fallback di chunk), mai fatale
# e mai un trip. La voce e' comunque validata a monte (parse_voice_id).
_OR_PROVIDER_400_MARK = "Provider returned"
# Rifiuto di moderazione del provider (job 8db7VnSUuZTMnsMJPm_Byg, 15/10/2026:
# "Provider blocked this request through content moderation (provider finish
# reason: PROHIBITED_CONTENT)"). E' un difetto del testo, non del backend:
# come il 422/2017 di Cloudflare non va ritentato e non deve contare nel
# breaker, altrimenti un solo chunk esplicito sposta il modello sul ripiego.
_OR_CONTENT_REJECTED_MARKS = ("content moderation", "PROHIBITED_CONTENT",
                              "SAFETY", "BLOCKLIST")


def _or_error_message(body, text):
    """Messaggio d'errore OpenRouter in qualunque forma, mai un'eccezione."""
    try:
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err.get("name") or "")
            if err:
                return str(err)
            if "message" in body:
                return str(body.get("message") or "")
        return (text or "")[:200]
    except Exception:
        return ""


def _or_retry_after(resp):
    try:
        val = resp.headers.get("Retry-After")
        return float(val) if val not in (None, "") else None
    except (TypeError, ValueError, AttributeError):
        return None


def _interpret_openrouter_response(resp):
    """Traduce una risposta OpenRouter nel contratto di trasporto.

    Separata da `openrouter_call` per lo stesso motivo dell'omologa
    Cloudflare: la tabella di mappatura si testa senza HTTP.
    """
    status = resp.status_code
    try:
        ctype = str(resp.headers.get("Content-Type") or "").lower()
    except Exception:
        ctype = ""

    if status == 200:
        pcm = getattr(resp, "content", b"") or b""
        if not isinstance(pcm, (bytes, bytearray)) or not pcm:
            raise TransportError("OpenRouter ha risposto 200 senza audio",
                                 **_OR_200_ERROR_KWARGS)
        if "audio" not in ctype:
            # Un JSON con status 200 e' un errore mascherato (es. moderazione
            # a monte), non audio: non va scritto in un file PCM.
            raise TransportError(
                f"OpenRouter ha risposto 200 con contenuto {ctype or 'ignoto'}",
                **_OR_200_ERROR_KWARGS)
        if pcm[:4] == b"RIFF":
            # Difesa: oggi arriva PCM grezzo; se il formato cambiasse in WAV
            # si scarta l'header (44 byte canonici) invece di consegnarlo
            # come audio.
            pcm = bytes(pcm[44:])
            if not pcm:
                raise TransportError("audio OpenRouter vuoto dopo l'header WAV",
                                     **_OR_200_ERROR_KWARGS)
        try:
            gen_id = resp.headers.get(OR_GENERATION_HEADER)
        except Exception:
            gen_id = None
        # Nessun usage nella risposta: la stima dei token spetta al chiamante.
        return {"pcm": bytes(pcm), "input_tokens": None, "output_tokens": None,
                "generation_id": gen_id}

    try:
        body = resp.json()
    except Exception:
        body = None
    message = _or_error_message(body, getattr(resp, "text", ""))

    if status == 402:
        raise TransportError(
            f"credito OpenRouter esaurito: {message}",
            kind="backend_down", http_status=status)
    if status == 429:
        raise TransportError(
            f"OpenRouter rate limit: {message}",
            kind="rate_limited", http_status=status,
            retry_after_sec=_or_retry_after(resp))
    if status in (401, 403):
        raise TransportError(
            f"OpenRouter rifiuta la chiave (HTTP {status}): {message}",
            kind="fatal", http_status=status)
    if status == 404:
        raise TransportError(
            f"endpoint o modello OpenRouter inesistente: {message}",
            kind="fatal", http_status=status)
    if status == 400:
        # Prima del ramo "Provider returned": la moderazione puo' arrivare
        # anche con quel prefisso, e resta comunque un rifiuto del contenuto.
        if any(m in message for m in _OR_CONTENT_REJECTED_MARKS):
            raise TransportError(
                f"contenuto rifiutato da OpenRouter: {message}",
                kind="content_rejected", http_status=status)
        if _OR_PROVIDER_400_MARK in message:
            raise TransportError(
                f"il provider dietro OpenRouter ha rifiutato la richiesta: {message}",
                kind="retryable", http_status=status)
        if any(m in message for m in _OR_FATAL_MARKS):
            raise TransportError(
                f"richiesta OpenRouter non valida: {message}",
                kind="fatal", http_status=status)
        raise TransportError(
            f"OpenRouter HTTP 400: {message}", kind="retryable", http_status=status)
    detail = message or (getattr(resp, "text", "") or "")[:200]
    raise TransportError(
        f"OpenRouter HTTP {status}: {detail}", kind="retryable", http_status=status)


def openrouter_call(*, final_text, voice_name, model_key, model_id,
                    timeout_ms, temperature, instructions=None):
    """Adapter di trasporto OpenRouter (/audio/speech).

    Una chiamata, nessun retry. `instructions` e' lo stile fuori dal testo
    (il chiamante lo estrae dal blocco "[style: ...]" per i modelli che lo
    vogliono cosi'; per gli altri resta inline in `final_text`).
    `temperature` non e' esposta dall'endpoint e viene ignorata. La chiave
    viene letta dall'ambiente e non compare mai in un messaggio di errore.
    """
    key = env_str("ABM_OPENROUTER_API_KEY")
    if not key:
        raise TransportError(
            "backend OpenRouter non configurato (ABM_OPENROUTER_API_KEY assente)",
            kind="fatal")
    payload = {"model": model_id, "input": final_text, "voice": voice_name,
               "response_format": "pcm"}
    if instructions:
        payload["instructions"] = str(instructions)
    headers = {"Authorization": f"Bearer {key}",
               "HTTP-Referer": "https://audiobook-maker.com",
               "X-Title": "AudioBook Maker"}
    try:
        resp = requests.post(OR_API_URL, headers=headers, json=payload,
                             timeout=timeout_ms / 1000.0)
    except requests.Timeout as e:
        raise TransportError("timeout verso OpenRouter", kind="retryable") from e
    except requests.RequestException as e:
        raise TransportError(f"errore di rete verso OpenRouter: "
                             f"{type(e).__name__}", kind="retryable") from e
    try:
        return _interpret_openrouter_response(resp)
    except TransportError:
        raise
    except Exception as e:
        raise TransportError(
            f"risposta OpenRouter non interpretabile: {type(e).__name__}",
            kind="retryable",
            http_status=getattr(resp, "status_code", None)) from e
