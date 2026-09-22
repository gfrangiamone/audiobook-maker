# -*- coding: utf-8 -*-
"""
Giudizio semantico dell'output LLM (`llm_output_judge.py`).

Il match letterale di `_is_prompt_leak` prende solo l'eco verbatim del system
prompt. Qui si verifica il secondo motore: il pre-filtro gratuito sul rapporto
dei caratteri, le due domande tipizzate, le soglie, i tre modi e — la parte
che conta davvero — che senza giudizio la generazione si comporti esattamente
come prima.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import generation_engine as ge
import llm_output_judge as oj
import semantic_judge as sj


requires_sdk = pytest.mark.skipif(
    sj.Noul is None, reason="typesafe-sdk non installato")


# --------------------------------------------------------------------------
# helper
# --------------------------------------------------------------------------

def response(**probs):
    return SimpleNamespace(
        nouls={k: SimpleNamespace(noul=p) for k, p in probs.items()},
        choices={}, scores={})


def text(chars, word="parola "):
    return (word * (chars // len(word) + 1))[:chars]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_TYPESAFE_API_KEY", "k-test")
    monkeypatch.setenv("ABM_OUTPUT_JUDGE_MODE", "on")
    monkeypatch.delenv("ABM_TYPESAFE_ENABLE", raising=False)
    for v in ("ABM_OUTPUT_MIN_META", "ABM_OUTPUT_MAX_FAITHFUL",
              "ABM_OUTPUT_RATIO_LOW", "ABM_OUTPUT_RATIO_HIGH",
              "ABM_OUTPUT_MIN_CHARS"):
        monkeypatch.delenv(v, raising=False)
    sj.reset()
    yield tmp_path
    sj.reset()


def audit_lines(tmp_path):
    files = list(tmp_path.glob("llm_output_judge_audit_*.jsonl"))
    if not files:
        return []
    return [l for l in files[0].read_text(encoding="utf-8").splitlines() if l]


# --------------------------------------------------------------------------
# modi
# --------------------------------------------------------------------------

def test_default_mode_is_observe(monkeypatch):
    monkeypatch.delenv("ABM_OUTPUT_JUDGE_MODE", raising=False)
    assert oj.mode() == "observe"
    assert oj.applies() is False


def test_unknown_mode_does_not_switch_on(monkeypatch):
    """Un errore di battitura nell'unit non deve mettersi a scartare output."""
    monkeypatch.setenv("ABM_OUTPUT_JUDGE_MODE", "ON!")
    assert oj.mode() == "observe"


def test_off_asks_nothing(env, monkeypatch):
    monkeypatch.setenv("ABM_OUTPUT_JUDGE_MODE", "off")
    with patch.object(sj, "ask") as ask:
        assert oj.review(text(2000), text(200)) == {}
    ask.assert_not_called()


def test_no_key_no_judgement(env, monkeypatch):
    monkeypatch.delenv("ABM_TYPESAFE_API_KEY", raising=False)
    sj.reset()
    with patch.object(sj, "ask") as ask:
        assert oj.check(text(2000), text(200)) == ""
    ask.assert_not_called()


# --------------------------------------------------------------------------
# pre-filtro: quando vale la pena chiedere
# --------------------------------------------------------------------------

def test_normal_output_is_never_questioned(env):
    """Il caso normale — l'ottimizzazione allunga di poco — non costa nulla."""
    with patch.object(sj, "ask") as ask:
        assert oj.check(text(3000), text(3300)) == ""
    ask.assert_not_called()


def test_halved_output_is_suspicious(env):
    assert oj.suspicious(text(3000), text(1200)) == "short"


def test_doubled_output_is_suspicious(env):
    assert oj.suspicious(text(3000), text(7000)) == "long"


def test_short_chunks_are_left_alone(env):
    """Su poche righe il rapporto oscilla da solo: ogni chunk finirebbe sotto
    giudizio senza che significhi niente."""
    assert oj.suspicious(text(120), "") == ""


def test_the_band_comes_from_env(env, monkeypatch):
    monkeypatch.setenv("ABM_OUTPUT_RATIO_LOW", "0.95")
    assert oj.suspicious(text(3000), text(2800)) == "short"


def test_ratio_of_empty_source_is_zero(env):
    assert oj.ratio("", "qualcosa") == 0.0
    assert oj.suspicious("", "qualcosa") == ""


# --------------------------------------------------------------------------
# domande
# --------------------------------------------------------------------------

@requires_sdk
def test_two_questions_in_one_request(env):
    with patch.object(sj, "ask", return_value=response(meta=0.1,
                                                       faithful=0.9)) as ask:
        oj.review(text(3000), text(1000))
    assert ask.call_count == 1
    assert set(ask.call_args[0][1]) == {"meta", "faithful"}


@requires_sdk
def test_head_and_tail_travel_not_the_whole_text(env):
    """Il centro non risponde a nessuna delle due domande e moltiplicherebbe
    il costo; la coda invece serve, perche' il troncamento sta li'."""
    src = text(400) + "MEZZO" * 2000 + "ultima frase del sorgente."
    with patch.object(sj, "ask", return_value=response(meta=0.1,
                                                       faithful=0.9)) as ask:
        oj.review(src, text(1000))
    state = ask.call_args[0][0]
    sent = state["source"]["text"]
    assert len(sent) < len(src)
    assert "ultima frase del sorgente." in sent
    assert state["source"]["chars"] == len(src)


@requires_sdk
def test_the_ratio_travels_with_the_texts(env):
    with patch.object(sj, "ask", return_value=response(meta=0.1,
                                                       faithful=0.9)) as ask:
        oj.review(text(2000), text(1000))
    assert ask.call_args[0][0]["length_ratio"] == 0.5


# --------------------------------------------------------------------------
# soglie
# --------------------------------------------------------------------------

def test_meta_above_threshold_rejects(env):
    assert oj.verdict({"meta": 0.9, "faithful": 0.9})[0] == "meta"


def test_summary_rejects(env):
    assert oj.verdict({"meta": 0.1, "faithful": 0.05})[0] == "unfaithful"


def test_the_middle_band_keeps_the_output(env):
    """Fra le due soglie non si tocca niente: il dubbio non basta a buttare un
    capitolo gia' pagato."""
    assert oj.verdict({"meta": 0.4, "faithful": 0.5})[0] == ""


def test_thresholds_come_from_env(env, monkeypatch):
    monkeypatch.setenv("ABM_OUTPUT_MAX_FAITHFUL", "0.60")
    assert oj.verdict({"faithful": 0.5})[0] == "unfaithful"


def test_a_missing_answer_decides_nothing(env):
    """Una domanda senza risposta non e' una risposta negativa."""
    assert oj.verdict({"meta": 0.2})[0] == ""
    assert oj.verdict({})[0] == ""


# --------------------------------------------------------------------------
# modi e audit
# --------------------------------------------------------------------------

@requires_sdk
def test_observe_records_and_keeps_the_output(env, monkeypatch):
    monkeypatch.setenv("ABM_OUTPUT_JUDGE_MODE", "observe")
    with patch.object(sj, "ask", return_value=response(meta=0.05,
                                                       faithful=0.02)):
        assert oj.check(text(3000), text(900)) == ""
    rows = audit_lines(env)
    assert len(rows) == 1
    assert '"reason": "unfaithful"' in rows[0]
    assert '"applied": false' in rows[0]


@requires_sdk
def test_on_rejects_and_records(env):
    with patch.object(sj, "ask", return_value=response(meta=0.05,
                                                       faithful=0.02)):
        assert oj.check(text(3000), text(900), job_id="J1",
                        chapter="Capitolo 3") == "unfaithful"
    rows = audit_lines(env)
    assert len(rows) == 1
    assert '"applied": true' in rows[0]
    assert '"J1"' in rows[0]
    assert "Capitolo 3" in rows[0]


@requires_sdk
def test_nothing_is_recorded_without_a_judgement(env):
    with patch.object(sj, "ask", return_value=None):
        assert oj.check(text(3000), text(900)) == ""
    assert audit_lines(env) == []


def test_audit_survives_a_missing_data_dir(env, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(env / "non-esiste"))
    oj.write_audit(text(100), text(50), {"meta": 0.9}, "meta")


# --------------------------------------------------------------------------
# fail-open
# --------------------------------------------------------------------------

@requires_sdk
def test_a_silent_service_keeps_the_output(env):
    with patch.object(sj, "ask", return_value=None):
        assert oj.check(text(3000), text(900)) == ""


@requires_sdk
def test_a_broken_judgement_keeps_the_output(env):
    with patch.object(sj, "ask", side_effect=RuntimeError("boom")):
        assert oj.check(text(3000), text(900)) == ""


# --------------------------------------------------------------------------
# innesto in generation_engine
# --------------------------------------------------------------------------

def _fake_client(text_out):
    """Stesso stampo di test_call_llm_usage: uno stream openai finto."""
    import types
    delta = types.SimpleNamespace(content=text_out, reasoning_content=None)
    chunk = types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)],
                                  usage=None)
    class _Stream:
        def __iter__(self):
            return iter([chunk])

        def close(self):
            pass

    class _Completions:
        def create(self, **kwargs):
            return _Stream()

    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=_Completions()))


def _prepare(monkeypatch, text_out):
    monkeypatch.setattr(ge, "_llm_client", _fake_client(text_out))
    monkeypatch.setattr(ge, "_get_llm_prompt", lambda lang: "SYS")
    monkeypatch.setattr(ge, "_sanitize_llm_output", lambda x: x)
    monkeypatch.setattr(ge, "LLM_LEAK_MAX_RETRIES", 0)


def test_the_judge_rejects_what_the_echo_check_accepts(env, monkeypatch):
    """Il riassunto non contiene una riga del system prompt: il primo motore
    lo lascia passare, ed e' esattamente il danno silenzioso da fermare."""
    _prepare(monkeypatch, "Riassunto brevissimo.")
    with patch.object(ge.llm_output_judge, "check", return_value="unfaithful"):
        with pytest.raises(ge._PromptLeakError) as err:
            ge._call_llm(text(3000))
    assert "unfaithful" in str(err.value)


def test_the_judge_sees_input_and_output(env, monkeypatch):
    _prepare(monkeypatch, "Riassunto brevissimo.")
    with patch.object(ge.llm_output_judge, "check", return_value="") as check:
        ge._call_llm("testo di partenza")
    source, output = check.call_args[0]
    assert source == "testo di partenza"
    assert output == "Riassunto brevissimo."


def test_no_judgement_no_change(env, monkeypatch):
    """Senza giudizio la generazione si comporta come prima del modulo."""
    _prepare(monkeypatch, "Testo ottimizzato.")
    with patch.object(ge.llm_output_judge, "check", return_value=""):
        assert ge._call_llm("testo") == "Testo ottimizzato."


def test_the_judge_is_not_asked_when_the_echo_already_matched(env, monkeypatch):
    """Su un eco verbatim la domanda non si pone nemmeno: niente costo."""
    _prepare(monkeypatch, "qualunque cosa")
    monkeypatch.setattr(ge, "_is_prompt_leak", lambda a, b: True)
    with patch.object(ge.llm_output_judge, "check") as check:
        with pytest.raises(ge._PromptLeakError):
            ge._call_llm("testo")
    check.assert_not_called()
