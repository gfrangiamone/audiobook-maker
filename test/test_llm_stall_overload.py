"""Provider in coda: nessun evento, poi la rinuncia dopo 15 minuti.

Il 14 settembre 2026, dalle 20 alle 23:30, il provider LLM accettava le
richieste e poi mandava solo keep-alive SSE: il read timeout non scattava mai
e dopo 900 s arrivava `APIError("unable to start processing ... try again
later")`, senza status HTTP. `_call_llm` non lo riconosceva come transitorio:
19 ottimizzazioni fallite al primo tentativo, e chi aveva chiesto la notifica
non ha ricevuto nessuna email.
"""
import threading

import generation_engine as ge


class _Delta:
    def __init__(self, content):
        self.content = content
    reasoning_content = None


class _Choice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Event:
    usage = None

    def __init__(self, content):
        self.choices = [_Choice(content)]


class _TextStream:
    def __init__(self, text):
        self._text = text

    def __iter__(self):
        yield _Event(self._text)

    def close(self):
        pass


class _SilentStream:
    """Solo keep-alive: l'iterazione resta bloccata finche' qualcuno non
    chiude lo stream, poi fallisce come httpx su un socket chiuso (o, con
    `raise_on_close=False`, finisce senza eventi)."""

    def __init__(self, raise_on_close=True):
        self._closed = threading.Event()
        self._raise = raise_on_close

    def __iter__(self):
        if not self._closed.wait(5.0):
            raise AssertionError("il watchdog non ha chiuso lo stream")
        if self._raise:
            raise ConnectionResetError("stream closed")  # tipo non transitorio
        return
        yield  # pragma: no cover

    def close(self):
        self._closed.set()


class _Completions:
    def __init__(self, factories):
        self._factories = list(factories)
        self.chiamate = 0

    def create(self, **kwargs):
        self.chiamate += 1
        f = self._factories[min(self.chiamate - 1, len(self._factories) - 1)]
        return f()


class _Chat:
    def __init__(self, factories):
        self.completions = _Completions(factories)


class _Client:
    def __init__(self, factories):
        self.chat = _Chat(factories)


INPUT = "Prosa di prova, abbastanza lunga da non essere triviale. " * 4
OUT = "Testo ottimizzato dopo il nuovo tentativo."


def _setup(monkeypatch, factories, sleeps):
    client = _Client(factories)
    monkeypatch.setattr(ge, "_llm_client", client)
    monkeypatch.setattr(ge.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(ge, "LLM_FIRST_EVENT_TIMEOUT_SEC", 0.2)
    monkeypatch.setattr(ge, "LLM_OVERLOAD_BACKOFF_SEC", 20.0)
    return client


def test_stream_muto_viene_chiuso_e_ritentato(monkeypatch):
    sleeps = []
    client = _setup(monkeypatch, [_SilentStream, lambda: _TextStream(OUT)],
                    sleeps)

    out = ge._call_llm(INPUT, job={"opt_lang": "it"}, max_retries=4)

    assert out == OUT
    assert client.chat.completions.chiamate == 2
    assert sleeps == [20.0], "pausa da sovraccarico, non 1 s"


def test_stream_muto_che_finisce_senza_eccezione(monkeypatch):
    """La chiusura puo' anche terminare l'iterazione in silenzio: resta uno
    stallo, non una risposta vuota."""
    sleeps = []
    client = _setup(
        monkeypatch,
        [lambda: _SilentStream(raise_on_close=False),
         lambda: _TextStream(OUT)],
        sleeps)

    assert ge._call_llm(INPUT, job={"opt_lang": "it"}, max_retries=4) == OUT
    assert client.chat.completions.chiamate == 2
    assert sleeps == [20.0]


def test_stallo_persistente_esaurisce_il_budget(monkeypatch):
    sleeps = []
    client = _setup(monkeypatch, [_SilentStream], sleeps)

    try:
        ge._call_llm(INPUT, job={"opt_lang": "it"}, max_retries=3)
    except ge._LLMStallError:
        pass
    else:
        raise AssertionError("uno stallo persistente deve alzare _LLMStallError")
    assert client.chat.completions.chiamate == 3
    assert sleeps == [20.0, 40.0]


def test_rinuncia_del_provider_e_transitoria(monkeypatch):
    sleeps = []

    def _rinuncia():
        raise Exception("Server unable to start processing the request "
                        "after waiting, please try again later")

    client = _setup(monkeypatch, [_rinuncia, lambda: _TextStream(OUT)],
                    sleeps)

    assert ge._call_llm(INPUT, job={"opt_lang": "it"}, max_retries=4) == OUT
    assert client.chat.completions.chiamate == 2
    assert sleeps == [20.0]


def test_errore_non_transitorio_non_si_ritenta(monkeypatch):
    sleeps = []

    def _auth():
        raise ValueError("invalid api key")

    client = _setup(monkeypatch, [_auth], sleeps)
    try:
        ge._call_llm(INPUT, job={"opt_lang": "it"}, max_retries=4)
    except ValueError:
        pass
    else:
        raise AssertionError("errore non transitorio deve risalire subito")
    assert client.chat.completions.chiamate == 1
    assert sleeps == []


def test_annullamento_durante_lattesa(monkeypatch):
    """Chi annulla mentre il provider e' in coda non aspetta lo stallo."""
    sleeps = []
    job = {"opt_lang": "it", "opt_cancelled": False}
    client = _setup(monkeypatch, [_SilentStream], sleeps)
    monkeypatch.setattr(ge, "LLM_FIRST_EVENT_TIMEOUT_SEC", 30.0)
    threading.Timer(0.1, lambda: job.__setitem__("opt_cancelled", True)).start()

    try:
        ge._call_llm(INPUT, job=job, max_retries=4)
    except ge._CancelledError:
        pass
    else:
        raise AssertionError("annullamento in attesa deve alzare _CancelledError")
    assert client.chat.completions.chiamate == 1


def test_watchdog_disattivabile(monkeypatch):
    sleeps = []
    client = _setup(monkeypatch, [lambda: _TextStream(OUT)], sleeps)
    monkeypatch.setattr(ge, "LLM_FIRST_EVENT_TIMEOUT_SEC", 0)

    assert ge._call_llm(INPUT, job={"opt_lang": "it"}, max_retries=1) == OUT
    assert client.chat.completions.chiamate == 1


# ---------------------------------------------------------------------------
# Email di fallimento
# ---------------------------------------------------------------------------

class _Info:
    title = "Purple spirit"


def _mail_setup(monkeypatch):
    sent, acts = [], []
    monkeypatch.setattr(ge.email_service, "_send_email",
                        lambda to, subj, html: sent.append((to, subj, html)) or True)
    monkeypatch.setattr(ge, "_log_activity", lambda *a, **kw: acts.append(a[2]))
    return sent, acts


def test_email_fallimento_voucher(monkeypatch):
    sent, acts = _mail_setup(monkeypatch)
    job = {"notify_email": "u@example.com", "notify_lang": "en", "info": _Info(),
           "payment_amount_eur": 3.94, "payment_type": "voucher",
           "payment_token": "64VQ-XXXX-XXXX", "refund_done": True}

    assert ge._send_optimization_failed_email("j1", job) is True
    to, subj, html = sent[0]
    assert to == "u@example.com"
    assert "Purple spirit" in subj and "failed" in subj
    assert "credited back to the voucher" in html
    assert "64VQ" not in html, "mai il codice del buono nell'email"
    assert acts == ["OPT_FAIL_EMAIL_SENT"]

    # Nessun doppio invio sullo stesso job.
    assert ge._send_optimization_failed_email("j1", job) is False
    assert len(sent) == 1


def test_email_fallimento_paypal_e_gratuita(monkeypatch):
    sent, _ = _mail_setup(monkeypatch)
    paypal = {"notify_email": "a@example.com", "notify_lang": "it", "info": _Info(),
              "payment_amount_eur": 2.0, "payment_type": "paypal",
              "refund_done": True, "refund_voucher_code": "ABCD-EFGH-IJKL"}
    free = {"notify_email": "b@example.com", "notify_lang": "xx", "info": _Info()}

    ge._send_optimization_failed_email("j2", paypal)
    ge._send_optimization_failed_email("j3", free)

    assert "buono di rimborso" in sent[0][2]
    assert "ABCD" not in sent[0][2]
    assert "nothing has been charged" in sent[1][2], "lingua ignota -> inglese"


def test_email_fallimento_senza_indirizzo(monkeypatch):
    sent, acts = _mail_setup(monkeypatch)
    assert ge._send_optimization_failed_email("j4", {"info": _Info()}) is False
    assert sent == [] and acts == []


def test_testi_fallimento_senza_nomi_provider():
    texts = ge._opt_failed_email_texts("T", 1.0)
    assert set(texts) >= {"it", "en", "fr", "es", "de", "pt", "zh"}
    for lang, t in texts.items():
        blob = " ".join(t.values()).lower()
        for nome in ("deepseek", "gemini", "openai"):
            assert nome not in blob, (lang, nome)
