"""Verifica che il prompt LLM per l'ottimizzazione testo sia scelto in base
alla LINGUA TTS selezionata in UI (job["opt_lang"]), non dedotto dal voice id.

Motivazione: i voice id Gemini hanno formato "gemini:<model>:<name>" (nessun
prefisso lingua), quindi la vecchia logica (`voice.split("-")[0]`) cadeva
sempre su prompt_tts_generic.md anche se l'utente leggeva in italiano.
"""
import generation_engine


# Lo stream finto emette una riga di testo e non uno stream vuoto: da quando
# `_call_llm` tratta la risposta muta come una chiamata da rifare (vedi
# test_llm_empty_output.py), uno stream vuoto alzerebbe _EmptyOutputError
# prima che questi test possano guardare la lingua del prompt.
class _Delta:
    def __init__(self, content):
        self.content = content
    reasoning_content = None


class _Choice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Event:
    def __init__(self, content):
        self.choices = [_Choice(content)]
        self.usage = None


def _capture_prompt_lang(monkeypatch):
    """Intercetta _get_llm_prompt e ritorna la lista di lang richiesti."""
    requested = []
    real = generation_engine._get_llm_prompt

    def _wrap(lang_code="it"):
        requested.append(lang_code)
        return real(lang_code)

    monkeypatch.setattr(generation_engine, "_get_llm_prompt", _wrap)
    return requested


def test_opt_lang_used_for_gemini_voice(monkeypatch):
    """Voce Gemini: deve usare opt_lang, NON cadere su generic."""
    requested = _capture_prompt_lang(monkeypatch)

    class _FakeStream:
        def __iter__(self): return iter([_Event("testo ottimizzato")])
        def close(self): pass
    class _FakeChat:
        def create(self, **kw): return _FakeStream()
    class _FakeCompletions:
        chat = type("X", (), {"completions": _FakeChat()})()
    monkeypatch.setattr(generation_engine, "_llm_client",
                        type("C", (), {"chat": _FakeCompletions().chat})())

    job = {"opt_lang": "fr", "opt_voice": "gemini:flash25:Zephyr"}
    generation_engine._call_llm("testo", job=job, max_retries=1)

    assert requested[0] == "fr", f"atteso 'fr', ricevuto {requested[0]!r}"


def test_opt_lang_overrides_voice_extraction(monkeypatch):
    """Anche con voice id Edge contenente lingua diversa, vince opt_lang."""
    requested = _capture_prompt_lang(monkeypatch)

    class _FakeStream:
        def __iter__(self): return iter([_Event("testo ottimizzato")])
        def close(self): pass
    class _FakeChat:
        def create(self, **kw): return _FakeStream()
    monkeypatch.setattr(generation_engine, "_llm_client",
                        type("C", (), {"chat": type("X", (), {"completions": _FakeChat()})()})())

    # Utente ha caricato testo EN ma ha scelto voce IT per la lettura.
    job = {"opt_lang": "it", "voice": "en-US-AriaNeural"}
    generation_engine._call_llm("hello", job=job, max_retries=1)

    assert requested[0] == "it"


def test_fallback_to_voice_extraction_when_no_opt_lang(monkeypatch):
    """Backward compat: senza opt_lang, fallback all'estrazione dal voice id
    (utile per flussi che non passano lang esplicitamente)."""
    requested = _capture_prompt_lang(monkeypatch)

    class _FakeStream:
        def __iter__(self): return iter([_Event("testo ottimizzato")])
        def close(self): pass
    class _FakeChat:
        def create(self, **kw): return _FakeStream()
    monkeypatch.setattr(generation_engine, "_llm_client",
                        type("C", (), {"chat": type("X", (), {"completions": _FakeChat()})()})())

    job = {"voice": "de-DE-KatjaNeural"}
    generation_engine._call_llm("test", job=job, max_retries=1)

    assert requested[0] == "de"


def test_gemini_voice_without_opt_lang_does_not_corrupt_lang(monkeypatch):
    """Voice Gemini SENZA opt_lang: la stringa "gemini:flash25:zephyr" non deve
    essere usata come lingua. Meglio fallback a 'it' (default) che a una
    stringa nonsense che cerca un file inesistente."""
    requested = _capture_prompt_lang(monkeypatch)

    class _FakeStream:
        def __iter__(self): return iter([_Event("testo ottimizzato")])
        def close(self): pass
    class _FakeChat:
        def create(self, **kw): return _FakeStream()
    monkeypatch.setattr(generation_engine, "_llm_client",
                        type("C", (), {"chat": type("X", (), {"completions": _FakeChat()})()})())

    job = {"voice": "gemini:flash25:Zephyr"}
    generation_engine._call_llm("test", job=job, max_retries=1)

    # Default "it" mantenuto perche' la voice id Gemini non e` parsable.
    assert requested[0] == "it", f"atteso 'it' (default), ricevuto {requested[0]!r}"
