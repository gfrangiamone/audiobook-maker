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
