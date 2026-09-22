# -*- coding: utf-8 -*-
"""
Recupero semantico del campione voce (`transcript_judge.py`).

Il CER sopra soglia mette nello stesso mucchio chi legge un altro testo e chi
legge la frase giusta con un accento che whisper non trascrive. Qui si
verifica che il giudizio possa **solo recuperare** — nel dubbio, nel silenzio
e nel guasto resta il rifiuto che il gate aveva gia' deciso — e che sotto
soglia non costi niente, perche' li' non c'e' niente da salvare.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import semantic_judge as sj
import transcript_judge as tj


requires_sdk = pytest.mark.skipif(
    sj.Noul is None, reason="typesafe-sdk non installato")

FRASE = ("La nebbia agli irti colli piovigginando sale, e sotto il maestrale "
         "urla e biancheggia il mar.")
SENTITO = "La nebia agli irti coli piovigginando sale e sotto il maestrale "\
          "urla e bianchegia il mare"
ALTRO = "Allora ragazzi proviamo un secondo, uno due tre, prova microfono"


def response(**probs):
    return SimpleNamespace(
        nouls={k: SimpleNamespace(noul=p) for k, p in probs.items()},
        choices={}, scores={})


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_TYPESAFE_API_KEY", "k-test")
    monkeypatch.setenv("ABM_TRANSCRIPT_JUDGE_MODE", "on")
    monkeypatch.delenv("ABM_TYPESAFE_ENABLE", raising=False)
    for v in ("ABM_TRANSCRIPT_MIN_SAME", "ABM_TRANSCRIPT_MIN_WHOLE",
              "ABM_TRANSCRIPT_MAX_CER", "ABM_TRANSCRIPT_MIN_CHARS"):
        monkeypatch.delenv(v, raising=False)
    sj.reset()
    yield tmp_path
    sj.reset()


def audit_lines(tmp_path):
    files = list(tmp_path.glob("transcript_judge_audit_*.jsonl"))
    if not files:
        return []
    return [l for l in files[0].read_text(encoding="utf-8").splitlines() if l]


# --------------------------------------------------------------------------
# modi
# --------------------------------------------------------------------------

def test_default_mode_is_observe(monkeypatch):
    monkeypatch.delenv("ABM_TRANSCRIPT_JUDGE_MODE", raising=False)
    assert tj.mode() == "observe"
    assert tj.applies() is False


def test_unknown_mode_does_not_switch_on(monkeypatch):
    """Un refuso nell'unit non deve mettersi ad allentare un gate anti-abuso."""
    monkeypatch.setenv("ABM_TRANSCRIPT_JUDGE_MODE", "ON!")
    assert tj.mode() == "observe"


def test_off_asks_nothing(env, monkeypatch):
    monkeypatch.setenv("ABM_TRANSCRIPT_JUDGE_MODE", "off")
    with patch.object(sj, "ask") as ask:
        assert tj.rescues(FRASE, SENTITO, 0.30) is False
    ask.assert_not_called()


def test_no_key_no_judgement(env, monkeypatch):
    monkeypatch.delenv("ABM_TYPESAFE_API_KEY", raising=False)
    sj.reset()
    with patch.object(sj, "ask") as ask:
        assert tj.rescues(FRASE, SENTITO, 0.30) is False
    ask.assert_not_called()


# --------------------------------------------------------------------------
# quando non vale la pena chiedere
# --------------------------------------------------------------------------

def test_a_wildly_different_reading_is_not_questioned(env):
    """Oltre il tetto non c'e' accento che tenga: e' un altro testo, e la
    domanda sarebbe solo una chiamata pagata per sentirsi dire di no."""
    with patch.object(sj, "ask") as ask:
        assert tj.rescues(FRASE, ALTRO, 0.92) is False
    ask.assert_not_called()


def test_silence_is_not_questioned(env):
    """Trascrizione vuota: non c'e' niente da riconoscere, e il campione e'
    inutilizzabile comunque."""
    with patch.object(sj, "ask") as ask:
        assert tj.rescues(FRASE, "   ", 1.0) is False
    ask.assert_not_called()


def test_a_very_short_prompt_is_left_to_the_cer(env):
    """Su due parole il CER e' gia' una misura secca: meta' frase sbagliata."""
    with patch.object(sj, "ask") as ask:
        assert tj.rescues("Ciao a tutti", "Ciao a tanti", 0.30) is False
    ask.assert_not_called()


def test_the_ceiling_comes_from_env(env, monkeypatch):
    monkeypatch.setenv("ABM_TRANSCRIPT_MAX_CER", "0.35")
    with patch.object(sj, "ask") as ask:
        assert tj.rescues(FRASE, SENTITO, 0.40) is False
    ask.assert_not_called()


# --------------------------------------------------------------------------
# domande
# --------------------------------------------------------------------------

@requires_sdk
def test_one_request_two_questions(env):
    with patch.object(sj, "ask", return_value=response(same=0.9, whole=0.9)) as ask:
        tj.rescues(FRASE, SENTITO, 0.30)
    assert ask.call_count == 1
    assert set(ask.call_args[0][1]) == {"same", "whole"}


@requires_sdk
def test_the_state_carries_what_the_judge_needs(env):
    """Senza il CER e la lingua il giudice non sa quanto e' lontana la
    trascrizione ne' che alfabeto aspettarsi."""
    with patch.object(sj, "ask", return_value=response(same=0.9, whole=0.9)) as ask:
        tj.rescues(FRASE, SENTITO, 0.31, lang="it")
    state = ask.call_args[0][0]
    assert state["expected"] == FRASE
    assert state["transcript"] == SENTITO
    assert state["character_error_rate"] == 0.31
    assert state["language"] == "it"


# --------------------------------------------------------------------------
# soglie
# --------------------------------------------------------------------------

@requires_sdk
def test_a_marked_accent_is_recovered(env):
    with patch.object(sj, "ask", return_value=response(same=0.93, whole=0.88)):
        assert tj.rescues(FRASE, SENTITO, 0.30) is True


@requires_sdk
def test_another_text_is_not_recovered(env):
    with patch.object(sj, "ask", return_value=response(same=0.05, whole=0.4)):
        assert tj.rescues(FRASE, ALTRO, 0.55) is False


@requires_sdk
def test_a_doubtful_reading_stays_rejected(env):
    """Il gate ha gia' deciso: al giudice serve una risposta netta per
    ribaltarlo, non un forse."""
    with patch.object(sj, "ask", return_value=response(same=0.7, whole=0.95)):
        assert tj.rescues(FRASE, SENTITO, 0.30) is False


@requires_sdk
def test_a_truncated_reading_is_not_recovered(env):
    """Mezza frase letta bene resta mezza frase: il campione non copre la
    prova del consenso."""
    with patch.object(sj, "ask", return_value=response(same=0.95, whole=0.2)):
        assert tj.rescues(FRASE, SENTITO, 0.30) is False


@requires_sdk
def test_a_missing_answer_does_not_recover(env):
    """Una domanda senza risposta non e' un si': il rifiuto resta."""
    with patch.object(sj, "ask", return_value=response(same=0.99)):
        assert tj.rescues(FRASE, SENTITO, 0.30) is False


@requires_sdk
def test_the_thresholds_come_from_env(env, monkeypatch):
    monkeypatch.setenv("ABM_TRANSCRIPT_MIN_SAME", "0.99")
    with patch.object(sj, "ask", return_value=response(same=0.95, whole=0.95)):
        assert tj.rescues(FRASE, SENTITO, 0.30) is False


# --------------------------------------------------------------------------
# observe / on e audit
# --------------------------------------------------------------------------

@requires_sdk
def test_observe_asks_but_does_not_recover(env, monkeypatch):
    monkeypatch.setenv("ABM_TRANSCRIPT_JUDGE_MODE", "observe")
    with patch.object(sj, "ask", return_value=response(same=0.99, whole=0.99)) as ask:
        assert tj.rescues(FRASE, SENTITO, 0.30) is False
    assert ask.call_count == 1
    rows = audit_lines(env)
    assert len(rows) == 1
    assert '"rescued": true' in rows[0] and '"applied": false' in rows[0]


@requires_sdk
def test_the_audit_carries_both_texts(env):
    """Serve a rileggere i casi a mano: senza la frase e la trascrizione, la
    riga dice solo che il giudice ha detto qualcosa."""
    with patch.object(sj, "ask", return_value=response(same=0.93, whole=0.9)):
        tj.rescues(FRASE, SENTITO, 0.30, lang="it", client_id="cid-1")
    import json
    rec = json.loads(audit_lines(env)[0])
    assert rec["expected"].startswith("La nebbia")
    assert rec["heard"].startswith("La nebia")
    assert rec["cer"] == 0.3 and rec["language"] == "it"
    assert rec["client_id"] == "cid-1"
    assert rec["applied"] is True


@requires_sdk
def test_a_rejection_is_logged_too(env):
    """Con il solo log dei recuperi si saprebbe quante volte il giudice ha
    allentato il gate, mai quante volte ha avuto ragione a tenerlo."""
    with patch.object(sj, "ask", return_value=response(same=0.1, whole=0.9)):
        tj.rescues(FRASE, ALTRO, 0.50)
    assert len(audit_lines(env)) == 1


@requires_sdk
def test_a_missing_data_dir_does_not_break_the_upload(env, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", "/non/esiste/affatto")
    with patch.object(sj, "ask", return_value=response(same=0.93, whole=0.9)):
        assert tj.rescues(FRASE, SENTITO, 0.30) is True


# --------------------------------------------------------------------------
# fail-close: il dubbio non recupera mai
# --------------------------------------------------------------------------

def test_a_silent_service_does_not_recover(env):
    with patch.object(sj, "ask", return_value=None):
        assert tj.rescues(FRASE, SENTITO, 0.30) is False


def test_an_exception_does_not_recover(env):
    with patch.object(sj, "ask", side_effect=RuntimeError("boom")):
        assert tj.rescues(FRASE, SENTITO, 0.30) is False


def test_a_broken_audit_never_reaches_the_caller(env, monkeypatch):
    """L'audit e' diagnostica: un disco pieno non deve arrivare a chi sta
    rispondendo a un upload."""
    def _boom(*a, **k):
        raise OSError("no space left on device")
    monkeypatch.setattr(tj, "open", _boom, raising=False)
    tj.write_audit(FRASE, SENTITO, 0.3, {"same": 0.9, "whole": 0.9}, True)
