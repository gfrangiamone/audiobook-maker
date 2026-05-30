"""Difese contro echo del system prompt nell'output LLM.

Vedi piano: docs/superpowers/plans/2026-05-29-llm-prompt-leak-defense.md
"""
import json
from pathlib import Path

import pytest

import generation_engine as ge


def test_optimize_chapter_skips_llm_on_trivial_input(monkeypatch):
    """Input < 80 char di prosa non-narrativa non deve chiamare l'LLM."""
    calls = []

    def _fake_call_llm(user_content, job=None, max_retries=None):
        calls.append(user_content)
        return "MAI CHIAMATO"

    monkeypatch.setattr(ge, "_call_llm", _fake_call_llm)

    # Title-like: corto, senza punto finale
    result = ge._optimize_chapter_text("Prima meditazione")
    assert result == "Prima meditazione"
    assert calls == []


def test_optimize_chapter_skips_llm_on_single_short_line(monkeypatch):
    """Una sola riga di < 80 char senza punteggiatura terminale → pass-through."""
    calls = []
    monkeypatch.setattr(
        ge, "_call_llm",
        lambda *a, **kw: calls.append(a) or "MAI CHIAMATO"
    )
    result = ge._optimize_chapter_text("Emmanuele Silanos")
    assert result == "Emmanuele Silanos"
    assert calls == []


def test_optimize_chapter_calls_llm_on_real_prose(monkeypatch):
    """Prosa con punto fermo e > 80 char → l'LLM viene chiamato normalmente."""
    calls = []

    def _fake_call_llm(user_content, job=None, max_retries=None):
        calls.append(user_content)
        return "ottimizzato"

    monkeypatch.setattr(ge, "_call_llm", _fake_call_llm)

    text = ("Era una giornata particolarmente piovosa. "
            "Il cielo era coperto da nuvole grigie. "
            "Camminava lentamente verso casa.")
    result = ge._optimize_chapter_text(text)
    assert result == "ottimizzato"
    assert len(calls) == 1


def test_optimize_chapter_calls_llm_on_long_single_line_no_punct(monkeypatch):
    """Single-line > 2*soglia senza punteggiatura terminale → NON trivial.
    Probabile prosa mal-estratta (PDF), va comunque ottimizzata."""
    calls = []

    def _fake_call_llm(user_content, job=None, max_retries=None):
        calls.append(user_content)
        return "ottimizzato"

    monkeypatch.setattr(ge, "_call_llm", _fake_call_llm)

    # 200 char, single line, niente punteggiatura terminale
    text = "Questo e' un caso limite di prosa molto lunga estratta male da un PDF senza il punto finale che potrebbe essere stata mal-tagliata ma resta comunque prosa da ottimizzare in TTS naturalmente"
    assert len(text) > 2 * ge.LLM_TRIVIAL_INPUT_MIN_CHARS
    assert "\n" not in text
    result = ge._optimize_chapter_text(text)
    assert result == "ottimizzato"
    assert len(calls) == 1


def test_is_trivial_input_short_single_line_no_punct():
    """Direct unit test: short single-line senza punct → trivial."""
    assert ge._is_trivial_input("Capitolo primo") is True


def test_is_trivial_input_empty_and_whitespace():
    """Direct unit test: vuoto e whitespace → trivial."""
    assert ge._is_trivial_input("") is True
    assert ge._is_trivial_input(None) is True
    assert ge._is_trivial_input("   \n\t  ") is True


def test_is_trivial_input_below_threshold_with_punct():
    """Sotto soglia anche con punct → trivial (lunghezza domina)."""
    assert ge._is_trivial_input("Frase breve.") is True


def test_is_trivial_input_above_threshold_with_punct():
    """Sopra soglia con punct → NON trivial."""
    text = ("Era una giornata particolarmente piovosa quando arrivai a casa "
            "e trovai il giardino in disordine totale, una scena inattesa.")
    assert len(text) > ge.LLM_TRIVIAL_INPUT_MIN_CHARS
    assert ge._is_trivial_input(text) is False


def test_is_prompt_leak_detects_full_echo():
    """Output che inizia con i primi 120 char del system prompt → leak."""
    prompt = ge._get_llm_prompt("it")
    assert prompt, "Test richiede prompt IT presente"
    # Echo: l'output coincide col prompt (anche se il primo heading e' rimosso)
    leaked = "\n".join(prompt.splitlines()[2:])
    assert ge._is_prompt_leak(leaked, prompt) is True


def test_is_prompt_leak_detects_partial_block_match():
    """Output che contiene un blocco di 200 char del system prompt → leak."""
    prompt = ge._get_llm_prompt("it")
    assert prompt
    block = prompt[400:700]
    assert len(block) >= 200
    mixed = f"Un po' di prosa narrativa qualsiasi.\n\n{block}\n\nAltra prosa."
    assert ge._is_prompt_leak(mixed, prompt) is True


def test_is_prompt_leak_no_false_positive_on_normal_text():
    """Output normale (prosa narrativa) → NON e' leak."""
    prompt = ge._get_llm_prompt("it")
    assert prompt
    normal = ("Era una giornata particolarmente piovosa quando lui arrivo' "
              "al cancello. Il giardino era in disordine, e dalle finestre "
              "filtrava una luce gialla. Premette il campanello due volte.")
    assert ge._is_prompt_leak(normal, prompt) is False


def test_is_prompt_leak_handles_empty_inputs():
    assert ge._is_prompt_leak("", "qualcosa") is False
    assert ge._is_prompt_leak("qualcosa", "") is False
    assert ge._is_prompt_leak("", "") is False


def test_call_llm_raises_prompt_leak_error_on_persistent_echo(monkeypatch):
    """Se l'LLM echeggia il prompt per N tentativi consecutivi, _call_llm raises."""
    prompt = ge._get_llm_prompt("it")
    assert prompt

    class _FakeDelta:
        def __init__(self, content): self.content = content
        reasoning_content = None

    class _FakeChoice:
        def __init__(self, content): self.delta = _FakeDelta(content)

    class _FakeEvent:
        def __init__(self, content): self.choices = [_FakeChoice(content)]

    class _FakeStream:
        def __init__(self, payload): self._payload = payload
        def __iter__(self):
            # Stream il prompt completo come "output"
            for chunk_size in range(0, len(self._payload), 500):
                yield _FakeEvent(self._payload[chunk_size:chunk_size + 500])
        def close(self): pass

    class _FakeCompletions:
        def __init__(self, payload): self._payload = payload
        def create(self, **kwargs): return _FakeStream(self._payload)

    class _FakeChat:
        def __init__(self, payload): self.completions = _FakeCompletions(payload)

    class _FakeClient:
        def __init__(self, payload): self.chat = _FakeChat(payload)

    monkeypatch.setattr(ge, "_llm_client", _FakeClient(prompt))

    job = {"opt_lang": "it"}
    with pytest.raises(ge._PromptLeakError):
        ge._call_llm("Prosa narrativa di test molto lunga per non triggerare il pre-filtro." * 5,
                     job=job, max_retries=1)


def test_call_llm_returns_normal_output(monkeypatch):
    """Sanity: output normale non triggera _PromptLeakError."""

    class _FakeDelta:
        def __init__(self, content): self.content = content
        reasoning_content = None
    class _FakeChoice:
        def __init__(self, content): self.delta = _FakeDelta(content)
    class _FakeEvent:
        def __init__(self, content): self.choices = [_FakeChoice(content)]
    class _FakeStream:
        def __init__(self, payload): self._payload = payload
        def __iter__(self):
            yield _FakeEvent(self._payload)
        def close(self): pass
    class _FakeCompletions:
        def __init__(self, payload): self._payload = payload
        def create(self, **kwargs): return _FakeStream(self._payload)
    class _FakeChat:
        def __init__(self, payload): self.completions = _FakeCompletions(payload)
    class _FakeClient:
        def __init__(self, payload): self.chat = _FakeChat(payload)

    payload = "Testo ottimizzato normalmente, niente di sospetto qui."
    monkeypatch.setattr(ge, "_llm_client", _FakeClient(payload))

    result = ge._call_llm("input lungo per superare pre-filtro " * 10, job={"opt_lang": "it"}, max_retries=1)
    assert result == payload


def test_optimize_chapter_falls_back_to_original_on_leak(monkeypatch):
    """Single-call: leak → restituisce text originale + flag in job."""
    original = "Prosa narrativa di test molto lunga, ben oltre la soglia di pre-filtro." * 3

    def _fake_call(user_content, job=None, max_retries=None):
        raise ge._PromptLeakError("test leak")

    monkeypatch.setattr(ge, "_call_llm", _fake_call)

    job = {"opt_lang": "it"}
    # Disabilita audit per questo test (sara' coperto in Task 6)
    monkeypatch.setattr(ge, "_write_llm_audit", lambda **kw: None)

    result = ge._optimize_chapter_text(original, chapter_num=15,
                                       total_chapters=38, job=job)
    assert result == original
    assert len(job.get("opt_leak_chapters", [])) == 1
    assert job["opt_leak_chapters"][0]["chapter_num"] == 15


def test_optimize_chapter_chunked_falls_back_per_chunk(monkeypatch):
    """Chunked: leak su un chunk usa l'originale di quel chunk."""
    # Forza chunking riducendo la soglia
    monkeypatch.setattr(ge, "LLM_SAFE_OUTPUT_CHUNK", 200)
    monkeypatch.setattr(ge, "LLM_INTER_CHUNK_SLEEP_SEC", 0)
    monkeypatch.setattr(ge, "_write_llm_audit", lambda **kw: None)

    para_a = "Paragrafo uno. " * 20
    para_b = "Paragrafo due. " * 20
    para_c = "Paragrafo tre. " * 20
    text = f"{para_a}\n\n{para_b}\n\n{para_c}"

    calls = []

    def _fake_call(user_content, job=None, max_retries=None):
        calls.append(user_content)
        if "due" in user_content:
            raise ge._PromptLeakError("leak on chunk 2")
        return "OPT[" + user_content[:20] + "]"

    monkeypatch.setattr(ge, "_call_llm", _fake_call)
    job = {"opt_lang": "it"}
    result = ge._optimize_chapter_text(text, chapter_num=1, total_chapters=1, job=job)

    # Il chunk 2 deve contenere il paragrafo originale "due", non il placeholder OPT[]
    assert "Paragrafo due" in result
    assert len(job.get("opt_leak_chapters", [])) >= 1


def test_optimize_chapter_all_chunks_leak_preserves_header(monkeypatch):
    """Tutti i chunk falliscono → ritorna testo originale senza sanitizzazione.

    Regressione: `_sanitize_llm_output` ha euristiche aggressive (preamble strip,
    header con ':' fino a 80 char) pensate per output LLM, non per prosa
    originale. Se applicate al fallback completo, possono mangiare un header
    del capitolo. Il fix usa il flag `any_llm_output` per saltare la
    sanitizzazione quando nessun chunk ha prodotto output LLM.
    """
    monkeypatch.setattr(ge, "LLM_SAFE_OUTPUT_CHUNK", 200)
    monkeypatch.setattr(ge, "LLM_INTER_CHUNK_SLEEP_SEC", 0)
    monkeypatch.setattr(ge, "_write_llm_audit", lambda **kw: None)

    header = "Capitolo Primo:"
    body_a = "Una mattina di marzo, il vento. " * 10
    body_b = "Continuazione del racconto. " * 10
    text = f"{header}\n\n{body_a}\n\n{body_b}"

    def _fake_call(user_content, job=None, max_retries=None):
        raise ge._PromptLeakError("everything leaks")

    monkeypatch.setattr(ge, "_call_llm", _fake_call)
    job = {"opt_lang": "it"}
    result = ge._optimize_chapter_text(text, chapter_num=1, total_chapters=1, job=job)

    assert header in result, "Header originale eroso dal sanitizer sul fallback"
    assert len(job.get("opt_leak_chapters", [])) >= 2


def test_write_llm_audit_creates_jsonl_record(tmp_path, monkeypatch):
    """Un evento di leak deve essere appended come riga JSONL valida."""
    monkeypatch.setattr(ge, "_upload_dir", tmp_path)
    ge._write_llm_audit(
        job=None,
        job_id="job-abc",
        chapter_num=15,
        chapter_title="«E voi chi dite che io sia»",
        chunk_index=None,
        outcome="prompt_leak_fallback",
        chars_input=18,
        chars_output=13328,
        leaked_preview="Sei un editor audio specializzato.",
    )

    files = list(tmp_path.glob("llm_leak_audit_*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["job_id"] == "job-abc"
    assert rec["chapter_num"] == 15
    assert rec["outcome"] == "prompt_leak_fallback"
    assert rec["chars_input"] == 18
    assert rec["leaked_preview"].startswith("Sei un editor")
    assert "ts" in rec


def test_write_llm_audit_appends_subsequent_events(tmp_path, monkeypatch):
    """Due eventi nello stesso mese -> due righe nello stesso file."""
    monkeypatch.setattr(ge, "_upload_dir", tmp_path)
    for n in (1, 2):
        ge._write_llm_audit(
            job=None, job_id=f"job-{n}", chapter_num=n,
            outcome="prompt_leak_fallback",
            chars_input=10, chars_output=0,
        )
    files = list(tmp_path.glob("llm_leak_audit_*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_write_llm_audit_is_safe_when_upload_dir_none(monkeypatch):
    """Se _upload_dir non e' inizializzato, l'audit e' no-op (non lancia)."""
    monkeypatch.setattr(ge, "_upload_dir", None)
    ge._write_llm_audit(job_id="x", outcome="prompt_leak_fallback")


def test_generate_optimized_abm_sanitizes_leaked_chapter(tmp_path, monkeypatch):
    """Se ch.text contiene il system prompt, lo zip ottiene un placeholder + flag."""
    import io, zipfile
    from dataclasses import dataclass, field

    monkeypatch.setattr(ge, "_upload_dir", tmp_path)

    @dataclass
    class _Ch:
        index: int
        title: str
        text: str
        word_count: int = 0
        char_count: int = 0

    @dataclass
    class _Info:
        title: str = "Test Book"
        author: str = "Anon"
        language: str = "it"
        chapters: list = field(default_factory=list)

    prompt = ge._get_llm_prompt("it")
    assert prompt
    info = _Info(chapters=[
        _Ch(index=1, title="Cap1", text="Prosa normale e tranquilla."),
        _Ch(index=2, title="Cap2 leaked", text=prompt),  # leak simulato
    ])

    job_id = "job-test"
    work_dir = tmp_path / job_id
    work_dir.mkdir()
    ge._jobs = {job_id: {"info": info, "opt_lang": "it",
                          "optimized_chapters": [1, 2],
                          "original_filename": "test.epub"}}

    abm_path, abm_name = ge._generate_optimized_abm(job_id)
    assert abm_path and Path(abm_path).exists()

    with zipfile.ZipFile(abm_path, "r") as zf:
        names = zf.namelist()
        leaked_file = [n for n in names if "Cap2" in n][0]
        leaked_content = zf.read(leaked_file).decode("utf-8")
        assert "Sei un editor audio specializzato" not in leaked_content
        assert "LINGUA DELL'OUTPUT" not in leaked_content
        # Manifest deve segnalare il problema
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        ch2 = [c for c in manifest["chapters"] if c["index"] == 2][0]
        assert ch2.get("prompt_leak") is True
