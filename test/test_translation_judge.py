# -*- coding: utf-8 -*-
"""
Controllo a campione della traduzione (`translation_judge.py`).

Sulla community l'LLM ha gia' ricopiato il verbatim sorgente nello slot di
un'altra lingua. Qui lo stesso inciampo non lascia traccia: la risposta e'
piena, il chunk si concatena, l'epub si scrive. Si verifica il pre-filtro
gratuito sulla copia identica, le due domande, le soglie asimmetriche e che
senza giudizio la traduzione si comporti esattamente come prima.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import semantic_judge as sj
import translation_judge as tj


requires_sdk = pytest.mark.skipif(
    sj.Noul is None, reason="typesafe-sdk non installato")


def response(**probs):
    return SimpleNamespace(
        nouls={k: SimpleNamespace(noul=p) for k, p in probs.items()},
        choices={}, scores={})


def it(n=800):
    base = ("Nel mezzo del cammin di nostra vita mi ritrovai per una selva "
            "oscura, che' la diritta via era smarrita. ")
    return (base * (n // len(base) + 1))[:n]


def en(n=800):
    base = ("Midway upon the journey of our life I found myself within a "
            "forest dark, for the straightforward pathway had been lost. ")
    return (base * (n // len(base) + 1))[:n]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_TYPESAFE_API_KEY", "k-test")
    monkeypatch.setenv("ABM_TRJUDGE_MODE", "on")
    monkeypatch.delenv("ABM_TYPESAFE_ENABLE", raising=False)
    for v in ("ABM_TRJUDGE_MIN_TRANSLATED", "ABM_TRJUDGE_MIN_COMPLETE",
              "ABM_TRJUDGE_MIN_CHARS"):
        monkeypatch.delenv(v, raising=False)
    sj.reset()
    yield tmp_path
    sj.reset()


def audit(tmp_path):
    files = list(tmp_path.glob("translation_judge_audit_*.jsonl"))
    if not files:
        return []
    return [json.loads(l) for l in
            files[0].read_text(encoding="utf-8").splitlines() if l]


# --------------------------------------------------------------------------
# modi
# --------------------------------------------------------------------------

def test_default_mode_is_observe(monkeypatch):
    monkeypatch.delenv("ABM_TRJUDGE_MODE", raising=False)
    assert tj.mode() == "observe"
    assert tj.applies() is False


def test_unknown_mode_does_not_switch_on(monkeypatch):
    monkeypatch.setenv("ABM_TRJUDGE_MODE", "si")
    assert tj.mode() == "observe"


def test_off_asks_nothing(env, monkeypatch):
    monkeypatch.setenv("ABM_TRJUDGE_MODE", "off")
    with patch.object(sj, "ask") as ask:
        assert tj.check(it(), en(), "it", "en") == ""
    ask.assert_not_called()


def test_no_key_no_judgement(env, monkeypatch):
    monkeypatch.delenv("ABM_TYPESAFE_API_KEY", raising=False)
    sj.reset()
    with patch.object(sj, "ask") as ask:
        assert tj.check(it(), en(), "it", "en") == ""
    ask.assert_not_called()


# --------------------------------------------------------------------------
# pre-filtro: la copia identica non si chiede
# --------------------------------------------------------------------------

def test_an_identical_copy_costs_nothing(env):
    """E' una certezza, non una probabilita': chiederlo sarebbe una chiamata
    pagata per sentirsi confermare un confronto di stringhe."""
    with patch.object(sj, "ask") as ask:
        assert tj.check(it(), it(), "it", "en") == "untranslated"
    ask.assert_not_called()


def test_a_copy_with_the_tail_cut_is_still_a_copy(env):
    with patch.object(sj, "ask") as ask:
        assert tj.check(it(900), it(900)[:500], "it", "en") == "untranslated"
    ask.assert_not_called()


def test_whitespace_does_not_make_a_translation(env):
    assert tj.looks_copied(it(), it().replace(" ", "\n")) is True


def test_a_real_translation_is_not_a_copy(env):
    assert tj.looks_copied(it(), en()) is False


def test_without_a_key_even_a_copy_is_left_alone(env, monkeypatch):
    """Il pre-filtro non passa dal servizio, ma non deve per questo
    sopravvivergli: senza chiave la traduzione si comporta come prima di
    questo modulo, copia compresa."""
    monkeypatch.delenv("ABM_TYPESAFE_API_KEY", raising=False)
    sj.reset()
    assert tj.check(it(), it(), "it", "en") == ""
    assert audit(env) == []


def test_off_does_not_reject_a_copy_either(env, monkeypatch):
    monkeypatch.setenv("ABM_TRJUDGE_MODE", "off")
    assert tj.check(it(), it(), "it", "en") == ""


def test_short_chunks_are_left_alone(env):
    """Un titolo di sezione o una dedica: la domanda sulla completezza non
    significa nulla e due nomi propri possono coincidere fra due lingue."""
    with patch.object(sj, "ask") as ask:
        assert tj.check("Prefazione", "Prefazione", "it", "en") == ""
    ask.assert_not_called()


# --------------------------------------------------------------------------
# domande
# --------------------------------------------------------------------------

@requires_sdk
def test_one_request_two_questions(env):
    with patch.object(sj, "ask",
                      return_value=response(translated=0.9, complete=0.9)) as ask:
        tj.check(it(), en(), "it", "en")
    assert ask.call_count == 1
    assert set(ask.call_args[0][1]) == {"translated", "complete"}


@requires_sdk
def test_both_languages_travel_with_the_texts(env):
    """Senza la lingua di destinazione la domanda non ha un riferimento, e
    senza quella di partenza la copia lecita (un nome, una citazione) non si
    distingue dallo sbaglio."""
    with patch.object(sj, "ask",
                      return_value=response(translated=0.9, complete=0.9)) as ask:
        tj.check(it(), en(), "it", "en")
    state = ask.call_args[0][0]
    assert state["source_language"] == "it"
    assert state["target_language"] == "en"
    assert state["source"]["chars"] == 800


# --------------------------------------------------------------------------
# soglie
# --------------------------------------------------------------------------

@requires_sdk
def test_a_good_translation_passes(env):
    with patch.object(sj, "ask",
                      return_value=response(translated=0.97, complete=0.9)):
        assert tj.check(it(), en(), "it", "en") == ""


@requires_sdk
def test_the_wrong_language_is_caught(env):
    with patch.object(sj, "ask",
                      return_value=response(translated=0.05, complete=0.9)):
        assert tj.check(it(), en(), "it", "en") == "untranslated"


@requires_sdk
def test_a_summary_is_caught(env):
    """Il caso peggiore: risposta piena, file scritto, meta' capitolo sparito
    in un riassunto che nessun controllo deterministico vede."""
    with patch.object(sj, "ask",
                      return_value=response(translated=0.98, complete=0.1)):
        assert tj.check(it(), en(), "it", "en") == "incomplete"


@requires_sdk
def test_a_rearranged_translation_is_not_incomplete(env):
    """Tradurre accorpa frasi e sposta incisi: la soglia sulla completezza e'
    bassa apposta, o ogni capitolo verrebbe ritentato."""
    with patch.object(sj, "ask",
                      return_value=response(translated=0.95, complete=0.45)):
        assert tj.check(it(), en(), "it", "en") == ""


@requires_sdk
def test_a_missing_answer_does_not_reject(env):
    with patch.object(sj, "ask", return_value=response(complete=0.9)):
        assert tj.check(it(), en(), "it", "en") == ""


@requires_sdk
def test_the_thresholds_come_from_env(env, monkeypatch):
    monkeypatch.setenv("ABM_TRJUDGE_MIN_COMPLETE", "0.60")
    with patch.object(sj, "ask",
                      return_value=response(translated=0.95, complete=0.45)):
        assert tj.check(it(), en(), "it", "en") == "incomplete"


# --------------------------------------------------------------------------
# observe / on e audit
# --------------------------------------------------------------------------

@requires_sdk
def test_observe_asks_but_does_not_reject(env, monkeypatch):
    monkeypatch.setenv("ABM_TRJUDGE_MODE", "observe")
    with patch.object(sj, "ask",
                      return_value=response(translated=0.02, complete=0.9)) as ask:
        assert tj.check(it(), en(), "it", "en") == ""
    assert ask.call_count == 1
    rows = audit(env)
    assert len(rows) == 1
    assert rows[0]["reason"] == "untranslated" and rows[0]["applied"] is False


def test_observe_does_not_reject_a_copy_either(env, monkeypatch):
    monkeypatch.setenv("ABM_TRJUDGE_MODE", "observe")
    assert tj.check(it(), it(), "it", "en") == ""
    assert audit(env)[0]["copied"] is True


@requires_sdk
def test_a_good_chunk_is_logged_too(env):
    """Con le sole segnalazioni si saprebbe quanto spesso il modulo sbaglia,
    mai quanto spesso ha ragione a tacere."""
    with patch.object(sj, "ask",
                      return_value=response(translated=0.97, complete=0.9)):
        tj.check(it(), en(), "it", "en", job_id="J1", chapter="cap 3")
    rec = audit(env)[0]
    assert rec["reason"] == "" and rec["job_id"] == "J1"
    assert rec["chapter"] == "cap 3" and rec["attempt"] == 1


@requires_sdk
def test_the_retry_is_marked_in_the_audit(env):
    """Serve a distinguere il chunk ritentato dal primo giro: due righe con
    lo stesso capitolo e lo stesso esito sono un modello che insiste."""
    with patch.object(sj, "ask",
                      return_value=response(translated=0.9, complete=0.9)):
        tj.check(it(), en(), "it", "en", chapter="cap 3", attempt=2)
    assert audit(env)[0]["attempt"] == 2


@requires_sdk
def test_a_missing_data_dir_does_not_break_the_translation(env, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", "/non/esiste/affatto")
    with patch.object(sj, "ask",
                      return_value=response(translated=0.02, complete=0.9)):
        assert tj.check(it(), en(), "it", "en") == "untranslated"


# --------------------------------------------------------------------------
# fail-open
# --------------------------------------------------------------------------

def test_a_silent_service_keeps_the_chunk(env):
    with patch.object(sj, "ask", return_value=None):
        assert tj.check(it(), en(), "it", "en") == ""


def test_an_exception_keeps_the_chunk(env):
    with patch.object(sj, "ask", side_effect=RuntimeError("boom")):
        assert tj.check(it(), en(), "it", "en") == ""


def test_a_broken_audit_never_reaches_the_caller(env, monkeypatch):
    def _boom(*a, **k):
        raise OSError("no space left on device")
    monkeypatch.setattr(tj, "open", _boom, raising=False)
    tj.write_audit(it(), en(), {"translated": 0.9}, "")
