# -*- coding: utf-8 -*-
"""
Lingua del libro contro lingua della voce (`voice_language_guard.py`).

Il controllo sta prima del pagamento e non e' un divieto: avvisa, l'utente
conferma. Qui si verifica il campionamento (dal centro, non dal frontespizio),
la soglia, i tre modi, e che senza giudizio la generazione parta come prima.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import semantic_judge as sj
import voice_language_guard as vg


requires_sdk = pytest.mark.skipif(
    sj.Noul is None, reason="typesafe-sdk non installato")


# --------------------------------------------------------------------------
# helper
# --------------------------------------------------------------------------

def response(matches=0.9, language="it", confidence=0.9):
    return SimpleNamespace(
        nouls={"matches": SimpleNamespace(noul=matches)},
        choices={"language": SimpleNamespace(choice=language,
                                             confidence=confidence)},
        scores={})


def text(chars, word="parola "):
    return (word * (chars // len(word) + 1))[:chars]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_TYPESAFE_API_KEY", "k-test")
    monkeypatch.setenv("ABM_VOICELANG_MODE", "on")
    monkeypatch.delenv("ABM_TYPESAFE_ENABLE", raising=False)
    for v in ("ABM_VOICELANG_MAX_MATCH", "ABM_VOICELANG_MIN_CHARS",
              "ABM_VOICELANG_SAMPLE"):
        monkeypatch.delenv(v, raising=False)
    sj.reset()
    yield tmp_path
    sj.reset()


def audit_lines(tmp_path):
    files = list(tmp_path.glob("voice_language_audit_*.jsonl"))
    if not files:
        return []
    return [l for l in files[0].read_text(encoding="utf-8").splitlines() if l]


# --------------------------------------------------------------------------
# modi
# --------------------------------------------------------------------------

def test_default_mode_is_observe(monkeypatch):
    monkeypatch.delenv("ABM_VOICELANG_MODE", raising=False)
    assert vg.mode() == "observe"
    assert vg.applies() is False


def test_unknown_mode_does_not_switch_on(monkeypatch):
    monkeypatch.setenv("ABM_VOICELANG_MODE", "si")
    assert vg.mode() == "observe"


def test_off_asks_nothing(env, monkeypatch):
    monkeypatch.setenv("ABM_VOICELANG_MODE", "off")
    with patch.object(sj, "ask") as ask:
        assert vg.check([text(3000)], "it") is None
    ask.assert_not_called()


def test_no_key_no_check(env, monkeypatch):
    monkeypatch.delenv("ABM_TYPESAFE_API_KEY", raising=False)
    sj.reset()
    with patch.object(sj, "ask") as ask:
        assert vg.check([text(3000)], "it") is None
    ask.assert_not_called()


# --------------------------------------------------------------------------
# campione
# --------------------------------------------------------------------------

def test_the_sample_comes_from_the_middle(env):
    """In testa stanno dedica, esergo e citazione d'apertura, spesso in
    un'altra lingua: campionare l'inizio farebbe suonare l'allarme sul libro
    giusto."""
    chapters = ["DEDICA " * 300, "CORPO " * 300, "CODA " * 300]
    assert "CORPO" in vg.sample_text(chapters)
    assert "DEDICA" not in vg.sample_text(chapters)


def test_a_short_middle_chapter_borrows_from_the_next(env):
    chapters = ["a" * 100, "b" * 100, "c" * 5000]
    out = vg.sample_text(chapters)
    assert "b" in out and "c" in out


def test_the_sample_is_capped(env):
    assert len(vg.sample_text([text(50_000)])) == vg.sample_chars()


def test_empty_book_no_sample(env):
    assert vg.sample_text([]) == ""
    assert vg.sample_text(["", "   "]) == ""


def test_a_too_short_book_is_not_judged(env):
    """Su poche righe la lingua non si stabilisce: meglio tacere."""
    with patch.object(sj, "ask") as ask:
        assert vg.review("due parole", "it") == {}
    ask.assert_not_called()


# --------------------------------------------------------------------------
# domande
# --------------------------------------------------------------------------

@requires_sdk
def test_one_request_with_both_questions(env):
    with patch.object(sj, "ask", return_value=response()) as ask:
        vg.review(text(3000), "it")
    assert ask.call_count == 1
    assert set(ask.call_args[0][1]) == {"matches", "language"}


@requires_sdk
def test_the_declared_language_is_offered_as_a_choice(env):
    """Serve a nominare la lingua vera quando i metadati dicono un'altra cosa
    dalla voce."""
    with patch.object(sj, "ask", return_value=response()) as ask:
        vg.review(text(3000), "it", "es")
    options = ask.call_args[0][1]["language"].criteria
    assert set(options) == {"it", "es", "other"}


@requires_sdk
def test_without_a_declared_language_there_are_two_options(env):
    with patch.object(sj, "ask", return_value=response()) as ask:
        vg.review(text(3000), "it", "it")
    assert set(ask.call_args[0][1]["language"].criteria) == {"it", "other"}


def test_a_voice_without_a_language_is_not_checked(env):
    """Gemini, Speechify e le voci campionate non portano la lingua nell'id:
    senza il selector del client non si tira a indovinare."""
    with patch.object(sj, "ask") as ask:
        assert vg.check([text(3000)], "") is None
    ask.assert_not_called()


# --------------------------------------------------------------------------
# soglia
# --------------------------------------------------------------------------

@requires_sdk
def test_a_clear_mismatch_warns(env):
    with patch.object(sj, "ask", return_value=response(matches=0.02,
                                                       language="es")):
        hit = vg.check([text(3000)], "it-IT", "es")
    assert hit["voice_language"] == "it"
    assert hit["book_language"] == "es"


@requires_sdk
def test_a_book_full_of_quotations_passes(env):
    """Un saggio italiano pieno di citazioni inglesi resta un libro italiano:
    l'avviso di troppo ferma qualcuno che aveva ragione."""
    with patch.object(sj, "ask", return_value=response(matches=0.4)):
        assert vg.check([text(3000)], "it") is None


@requires_sdk
def test_the_threshold_comes_from_env(env, monkeypatch):
    monkeypatch.setenv("ABM_VOICELANG_MAX_MATCH", "0.50")
    with patch.object(sj, "ask", return_value=response(matches=0.4,
                                                       language="other")):
        assert vg.check([text(3000)], "it") is not None


@requires_sdk
def test_an_unnamed_language_still_warns(env):
    """Sapere che non e' la lingua della voce basta per avvisare, anche se la
    lingua vera resta senza nome."""
    with patch.object(sj, "ask", return_value=response(matches=0.01,
                                                       language="other")):
        hit = vg.check([text(3000)], "it")
    assert hit["book_language"] == ""


# --------------------------------------------------------------------------
# modi e audit
# --------------------------------------------------------------------------

@requires_sdk
def test_observe_records_and_lets_it_through(env, monkeypatch):
    monkeypatch.setenv("ABM_VOICELANG_MODE", "observe")
    with patch.object(sj, "ask", return_value=response(matches=0.01,
                                                       language="es")):
        assert vg.check([text(3000)], "it") is None
    rows = audit_lines(env)
    assert len(rows) == 1
    assert '"mismatch": true' in rows[0]
    assert '"applied": false' in rows[0]


@requires_sdk
def test_on_warns_and_records(env):
    with patch.object(sj, "ask", return_value=response(matches=0.01,
                                                       language="es")):
        vg.check([text(3000)], "it", job_id="J7", voice="it-IT-IsabellaNeural")
    rows = audit_lines(env)
    assert '"applied": true' in rows[0]
    assert "J7" in rows[0]


@requires_sdk
def test_a_match_is_recorded_too(env):
    """Anche i controlli passati servono: senza, l'audit direbbe solo quanto
    spesso il modulo sbaglia, mai quanto spesso ha ragione a tacere."""
    with patch.object(sj, "ask", return_value=response(matches=0.98)):
        assert vg.check([text(3000)], "it") is None
    assert '"mismatch": false' in audit_lines(env)[0]


def test_audit_survives_a_missing_data_dir(env, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(env / "non-esiste"))
    vg.write_audit({"matches": 0.1, "language": "es"}, "it", "es", True)


# --------------------------------------------------------------------------
# fail-open
# --------------------------------------------------------------------------

@requires_sdk
def test_a_silent_service_lets_it_through(env):
    with patch.object(sj, "ask", return_value=None):
        assert vg.check([text(3000)], "it") is None


@requires_sdk
def test_a_partial_answer_decides_nothing(env):
    partial = SimpleNamespace(nouls={}, choices={}, scores={})
    with patch.object(sj, "ask", return_value=partial):
        assert vg.check([text(3000)], "it") is None


@requires_sdk
def test_a_broken_judgement_lets_it_through(env):
    with patch.object(sj, "ask", side_effect=RuntimeError("boom")):
        assert vg.check([text(3000)], "it") is None
