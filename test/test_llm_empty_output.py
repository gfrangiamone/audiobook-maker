"""Una risposta LLM vuota non deve cancellare il capitolo.

Il 3 settembre 2026 il capitolo piu' lungo di «Fuga dalla liberta'» (68.473
char) e' tornato vuoto dallo stream: `_call_llm` restituiva la stringa vuota,
il chiamante la prendeva per un'ottimizzazione riuscita, il capitolo spariva
dal libro e finiva vuoto nella cache `.abm`, da dove non sarebbe mai piu'
ripassato dal modello. Nessun controllo a valle se ne accorgeva, perche' a
valle un capitolo vuoto e' solo un capitolo corto.
"""
import generation_engine as ge


class _FakeDelta:
    def __init__(self, content):
        self.content = content
    reasoning_content = None


class _FakeChoice:
    def __init__(self, content):
        self.delta = _FakeDelta(content)


class _FakeEvent:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeStream:
    def __init__(self, payload):
        self._payload = payload

    def __iter__(self):
        yield _FakeEvent(self._payload)

    def close(self):
        pass


class _FakeCompletions:
    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.chiamate = 0

    def create(self, **kwargs):
        self.chiamate += 1
        i = min(self.chiamate - 1, len(self._payloads) - 1)
        return _FakeStream(self._payloads[i])


class _FakeChat:
    def __init__(self, payloads):
        self.completions = _FakeCompletions(payloads)


class _FakeClient:
    def __init__(self, payloads):
        self.chat = _FakeChat(payloads)


INPUT = "Prosa di prova, abbastanza lunga da non essere triviale. " * 4


def test_call_llm_ritenta_sulla_risposta_vuota(monkeypatch):
    """Primo giro muto, secondo con testo: si tiene il testo."""
    client = _FakeClient(["", "Testo ottimizzato al secondo tentativo."])
    monkeypatch.setattr(ge, "_llm_client", client)
    monkeypatch.setattr(ge.time, "sleep", lambda s: None)

    out = ge._call_llm(INPUT, job={"opt_lang": "it"}, max_retries=1)

    assert out == "Testo ottimizzato al secondo tentativo."
    assert client.chat.completions.chiamate == 2


def test_call_llm_alza_leccezione_se_tace_sempre(monkeypatch):
    """Esaurito il budget, il vuoto diventa un errore, non un risultato."""
    client = _FakeClient([""])
    monkeypatch.setattr(ge, "_llm_client", client)
    monkeypatch.setattr(ge.time, "sleep", lambda s: None)
    monkeypatch.setattr(ge, "LLM_EMPTY_MAX_RETRIES", 2)

    try:
        ge._call_llm(INPUT, job={"opt_lang": "it"}, max_retries=1)
    except ge._EmptyOutputError:
        pass
    else:
        raise AssertionError("una risposta sempre vuota deve alzare "
                             "_EmptyOutputError")
    # Il tentativo buono piu' i due di riserva.
    assert client.chat.completions.chiamate == 3


def test_solo_spazi_vale_come_vuoto(monkeypatch):
    """Uno stream che emette whitespace e' muto quanto uno che tace."""
    client = _FakeClient(["   \n\n  ", "Testo vero."])
    monkeypatch.setattr(ge, "_llm_client", client)
    monkeypatch.setattr(ge.time, "sleep", lambda s: None)

    assert ge._call_llm(INPUT, job={"opt_lang": "it"},
                        max_retries=1) == "Testo vero."


def test_il_capitolo_torna_originale_invece_che_sparire(monkeypatch):
    """Chiamata singola: vuoto persistente -> testo di partenza."""
    def _muto(user_content, job=None, max_retries=None):
        raise ge._EmptyOutputError("test")

    monkeypatch.setattr(ge, "_call_llm", _muto)
    monkeypatch.setattr(ge, "_write_llm_audit", lambda **kw: None)

    job = {"opt_lang": "it"}
    out = ge._optimize_chapter_text(INPUT, chapter_num=8, total_chapters=16,
                                    job=job)

    assert out == INPUT
    assert len(job.get("opt_empty_chapters", [])) == 1
    assert job["opt_empty_chapters"][0]["chapter_num"] == 8


def test_a_chunk_solo_il_chunk_muto_torna_originale(monkeypatch):
    """Chunked: il vuoto su una parte non porta via le altre."""
    monkeypatch.setattr(ge, "LLM_SAFE_OUTPUT_CHUNK", 200)
    monkeypatch.setattr(ge, "LLM_INTER_CHUNK_SLEEP_SEC", 0)
    monkeypatch.setattr(ge, "_write_llm_audit", lambda **kw: None)

    a = "Paragrafo uno. " * 20
    b = "Paragrafo due. " * 20
    c = "Paragrafo tre. " * 20
    text = f"{a}\n\n{b}\n\n{c}"

    def _finto(user_content, job=None, max_retries=None):
        if "due" in user_content:
            raise ge._EmptyOutputError("muto sul secondo")
        return "OPT[" + user_content[:20] + "]"

    monkeypatch.setattr(ge, "_call_llm", _finto)
    job = {"opt_lang": "it"}
    out = ge._optimize_chapter_text(text, chapter_num=1, total_chapters=1,
                                    job=job)

    assert "Paragrafo due" in out
    assert "OPT[" in out, "le parti sane devono restare ottimizzate"
    # Il paragrafo di mezzo cade su piu' di un chunk: se ne conta almeno uno.
    assert len(job.get("opt_empty_chapters", [])) >= 1


def test_input_vuoto_non_e_una_risposta_vuota(monkeypatch):
    """Il pre-filtro dei trivial resta intatto: niente LLM, niente errore."""
    chiamate = []
    monkeypatch.setattr(
        ge, "_call_llm",
        lambda *a, **kw: chiamate.append(a) or "MAI CHIAMATO")

    assert ge._optimize_chapter_text("   ") == "   "
    assert chiamate == []
