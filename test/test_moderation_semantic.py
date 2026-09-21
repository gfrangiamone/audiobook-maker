"""Moderazione commenti con giudizi tipizzati (System One).

Copre il modulo foglia `semantic_judge` (fail-open, accessor) e il nuovo
step 2 di `community_moderator.validate`, che sostituisce il prompt LLM +
parser JSON scritto a mano. Nessuna rete: la risposta del servizio e' finta.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import community_moderator as cm
import semantic_judge as sj


# --------------------------------------------------------------------------
# helper
# --------------------------------------------------------------------------

REASONS = ("spam", "profanity", "threat", "sexual", "gibberish")


def fake_response(**probs):
    """Risposta System One finta: solo cio' che gli accessor leggono."""
    return SimpleNamespace(
        nouls={k: SimpleNamespace(noul=v) for k, v in probs.items()},
        choices={},
        scores={},
    )


def clean_response(**overrides):
    """Tutte le noul a zero, salvo quelle indicate."""
    probs = dict.fromkeys(REASONS, 0.01)
    probs.update(overrides)
    return fake_response(**probs)


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("ABM_TYPESAFE_API_KEY", raising=False)
    sj.reset()
    yield
    sj.reset()


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("ABM_TYPESAFE_API_KEY", "k-test")
    monkeypatch.delenv("ABM_TYPESAFE_ENABLE", raising=False)
    sj.reset()
    yield
    sj.reset()


# --------------------------------------------------------------------------
# semantic_judge: disponibilita' e fail-open
# --------------------------------------------------------------------------

def test_not_available_without_key(no_key):
    assert sj.is_available() is False
    assert sj.ask({"x": "y"}, {"q": object()}) is None


def test_kill_switch_wins_over_key(with_key, monkeypatch):
    assert sj.is_available() is True
    monkeypatch.setenv("ABM_TYPESAFE_ENABLE", "0")
    assert sj.is_available() is False


def test_ask_returns_none_on_client_error(with_key):
    """Un servizio che solleva non deve propagare: None, e il chiamante
    ripiega. E' la stessa garanzia del client LLM in community_moderator."""
    boom = SimpleNamespace(
        system_one=lambda **kw: (_ for _ in ()).throw(RuntimeError("giu'")))
    with patch.object(sj, "_get_client", return_value=boom):
        assert sj.ask({"x": "y"}, {"q": object()}) is None
    ts, msg = sj.last_error()
    assert ts > 0 and "giu'" in msg


def test_ask_passes_state_and_questions(with_key):
    seen = {}

    def _capture(**kw):
        seen.update(kw)
        return clean_response()

    with patch.object(sj, "_get_client", return_value=SimpleNamespace(system_one=_capture)):
        r = sj.ask({"comment": "ciao"}, {"spam": "Q"}, timeout=3.0)
    assert r is not None
    assert seen["state"] == {"comment": "ciao"}
    assert seen["questions"] == {"spam": "Q"}
    assert seen["timeout"] == 3.0


def test_accessors_tolerate_missing_answer():
    assert sj.noul(None, "spam") is None
    assert sj.noul(None, "spam", 0.0) == 0.0
    assert sj.noul(clean_response(), "assente") is None
    assert sj.noul(clean_response(spam=0.9), "spam") == pytest.approx(0.9)
    assert sj.choice(None, "x") == (None, 0.0)
    assert sj.score(None, "x") == (None, 0.0)


# --------------------------------------------------------------------------
# community_moderator: ordine dei motori
# --------------------------------------------------------------------------

def test_url_rejected_before_any_judgement():
    """Lo step URL resta deterministico e gratuito: nessun giudizio semantico
    deve partire per un commento che contiene un link."""
    with patch.object(sj, "ask", side_effect=AssertionError("non va chiamato")):
        out = cm.validate("Mario", "visita www.spam.example per offerte")
    assert out == {"approved": False, "reason": "url", "unvalidated": False}


def test_clean_comment_approved_without_llm_fallback(with_key):
    """Giudizio ottenuto: il motore LLM di ripiego non viene sfiorato."""
    with patch.object(sj, "ask", return_value=clean_response()), \
         patch.object(cm.ge, "_llm_available", side_effect=AssertionError("ripiego")):
        out = cm.validate("Anna", "Ottimo, ho convertito due libri in un'ora")
    assert out == {"approved": True, "reason": "ok", "unvalidated": False}


def test_short_praise_is_approved(with_key):
    """«top!» e le recensioni brevissime alimentano i rich snippet di
    seo_reviews: la soglia alta su `gibberish` esiste per non perderle."""
    with patch.object(sj, "ask", return_value=clean_response(gibberish=0.55)):
        out = cm.validate("", "top!")
    assert out["approved"] is True


@pytest.mark.parametrize("reason", REASONS)
def test_each_reason_rejects_with_its_own_label(with_key, reason):
    """Il motivo del rifiuto non e' piu' sempre "spam": ogni dimensione ha la
    sua etichetta, quindi l'admin legge perche' un commento e' caduto."""
    with patch.object(sj, "ask", return_value=clean_response(**{reason: 0.99})):
        out = cm.validate("x", "y")
    assert out == {"approved": False, "reason": reason, "unvalidated": False}


def test_thresholds_are_per_reason(with_key):
    """0.65 supera la soglia delle minacce (0.60) ma non quella dello spam
    (0.70): la severita' vive in codice, non dentro un prompt."""
    with patch.object(sj, "ask", return_value=clean_response(spam=0.65)):
        assert cm.validate("x", "y")["approved"] is True
    with patch.object(sj, "ask", return_value=clean_response(threat=0.65)):
        out = cm.validate("x", "y")
    assert (out["approved"], out["reason"]) == (False, "threat")


def test_threshold_override_from_env(with_key, monkeypatch):
    monkeypatch.setenv("ABM_MODERATION_MIN_SPAM", "0.5")
    with patch.object(sj, "ask", return_value=clean_response(spam=0.65)):
        out = cm.validate("x", "y")
    assert (out["approved"], out["reason"]) == (False, "spam")


def test_strongest_violation_wins(with_key):
    """Con piu' dimensioni sopra soglia vince quella che la supera di piu':
    l'etichetta descrive il motivo principale, non il primo in ordine."""
    with patch.object(sj, "ask", return_value=clean_response(spam=0.75, sexual=0.99)):
        assert cm.validate("x", "y")["reason"] == "sexual"


# --------------------------------------------------------------------------
# community_moderator: ripiego sul motore LLM
# --------------------------------------------------------------------------

def test_partial_answer_falls_back_instead_of_approving(with_key):
    """Una risposta senza tutte le domande e' monca: non vale
    un'approvazione. Si passa al motore LLM."""
    partial = fake_response(spam=0.01, profanity=0.01)
    with patch.object(sj, "ask", return_value=partial), \
         patch.object(cm.ge, "_llm_available", return_value=True), \
         patch.object(cm, "_call_llm", return_value={"approved": False, "reason": "spam"}) as llm:
        out = cm.validate("x", "y")
    assert llm.called
    assert out["approved"] is False


def test_falls_back_to_llm_when_unconfigured(no_key):
    """Senza chiave il comportamento e' esattamente quello di prima."""
    with patch.object(cm.ge, "_llm_available", return_value=True), \
         patch.object(cm, "_call_llm", return_value={"approved": True, "reason": "ok"}) as llm:
        out = cm.validate("Anna", "Bel lavoro")
    assert llm.called
    assert out == {"approved": True, "reason": "ok", "unvalidated": False}


def test_both_engines_down_allows_unvalidated(no_key):
    """Fail-open invariato: il commento passa marcato, non viene perso."""
    with patch.object(cm.ge, "_llm_available", return_value=False):
        out = cm.validate("Anna", "Bel lavoro")
    assert out == {"approved": True, "reason": "llm_error", "unvalidated": True}


def test_empty_input_is_approved():
    assert cm.validate("", "")["approved"] is True


# --------------------------------------------------------------------------
# domande: costruzione reale con l'SDK installato
# --------------------------------------------------------------------------

def test_questions_build_with_real_sdk():
    """Le domande vengono costruite con i tipi dell'SDK: se cambiano nome o
    campi, questo test cade qui e non in produzione."""
    if sj.Noul is None:
        pytest.skip("typesafe_sdk non installato")
    qs = cm._questions()
    assert set(qs) == set(REASONS)
    for q in qs.values():
        assert isinstance(q, sj.Noul)
        assert q.instructions
    # Le soglie coprono esattamente le domande poste: una domanda senza
    # soglia non verrebbe mai valutata, una soglia senza domanda bloccherebbe
    # ogni verdetto sul ramo "risposta monca".
    assert set(cm._thresholds()) == set(qs)
