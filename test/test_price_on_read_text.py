"""Prezzo PREMIUM sul testo letto (incidente sLRx3imAutQ0nHWhuJTyuQ, 25/10/2026).

Fatturati 481 mila caratteri, il piano TTS ne leggeva 220 mila: gli incisi tra
parentesi, che la voce salta, entravano nel prezzo. Le stime dei tre motori
seguono ora le scelte `read_round_parens` / `read_square_brackets`; con
entrambe "leggi" il prezzo resta quello di prima. Testi sintetici.
"""
import types
from unittest.mock import patch

import pytest

import audiobook_app
import gemini_tts
import pricing_common
import speechify_tts
import voxcpm_tts
from epub_to_tts import BookInfo, Chapter
from text_reflow import _strip_parenthetical, drop_parenthetical, paren_strip_flags
from tts_split import _plan_chunks, spoken_title_prefix

GEMINI_VOICE = "gemini:flash31:Zephyr"
READ_BOTH = {"strip_round": False, "strip_square": False}


@pytest.fixture(autouse=True)
def soglia_di_default(monkeypatch):
    monkeypatch.delenv("ABM_PAREN_STRIP_MAX_CHARS", raising=False)


def _ch(title, text, index=0):
    return types.SimpleNamespace(index=index, title=title, text=text, synthetic_title=False)


# ── drop_parenthetical / paren_strip_flags ──

def test_drop_parenthetical_toglie_gli_incisi_e_lascia_gli_spazi():
    txt = "Alfa (uno (due) tre) beta [quadra]\n\ngamma."
    assert drop_parenthetical(txt) == "Alfa  beta \n\ngamma."
    assert drop_parenthetical(txt, strip_square=False) == "Alfa  beta [quadra]\n\ngamma."
    assert drop_parenthetical(txt, strip_round=False) == "Alfa (uno (due) tre) beta \n\ngamma."
    assert drop_parenthetical(txt, False, False) is txt
    assert drop_parenthetical("") == ""


def test_drop_parenthetical_rispetta_la_guardia_dello_strip(monkeypatch):
    monkeypatch.setenv("ABM_PAREN_STRIP_MAX_CHARS", "40")
    lungo = "Inizio (" + "parola " * 10 + ") fine (breve)."
    assert drop_parenthetical(lungo) == "Inizio (" + "parola " * 10 + ") fine ."
    vuota = "Inizio [uno\n\ndue] fine."
    assert drop_parenthetical(vuota) == vuota


@pytest.mark.parametrize("txt", [
    "Alfa (uno (due) tre) beta [quadra]\n\ngamma.",
    "Er sagte ([hr Brief\n\nkam) heute (kurz) an.",
    "Nessuna parentesi qui.",
])
@pytest.mark.parametrize("flags", [{}, {"strip_round": False}, {"strip_square": False}, READ_BOTH])
def test_lo_strip_della_voce_e_drop_piu_spazi(txt, flags):
    # La voce legge `_strip_parenthetical`: stesso testo di `drop_parenthetical`
    # a meno degli spazi, quindi il prezzo e il piano contano le stesse parole.
    assert _strip_parenthetical(txt, **flags) == " ".join(drop_parenthetical(txt, **flags).split())


def test_paren_strip_flags():
    strip = {"strip_round": True, "strip_square": True}
    assert paren_strip_flags(None) == strip and paren_strip_flags({}) == strip
    assert paren_strip_flags({"read_round_parens": True}) == {"strip_round": False, "strip_square": True}
    assert paren_strip_flags({"read_round_parens": 0, "read_square_brackets": 1}) == \
        {"strip_round": True, "strip_square": False}


# ── pricing_common ──

def test_billable_text_non_fattura_gli_incisi_tolti():
    ch = _ch("Capitolo uno", "Era (forse) una notte [nota 3] buia.")
    assert pricing_common.billable_text(ch) == "Era  una notte  buia."
    assert pricing_common.billable_text(ch, spoken_title_prefix, **READ_BOTH) == \
        "Capitolo uno.\n\nEra (forse) una notte [nota 3] buia."
    per, total, texts = pricing_common.billable_chars([ch], strip_round=False)
    assert texts == ["Era (forse) una notte  buia."] and per == [total] == [len(texts[0])]
    # Un capitolo fatto solo di un inciso non si legge e non si paga, titolo compreso.
    assert pricing_common.billable_text(_ch("Titolo", "(tutto tolto)"), spoken_title_prefix) == ""


# ── stime dei tre motori ──

def _book():
    frase = "Il treno partiva all'alba e nessuno lo aspettava piu' da tempo. "
    inciso = "(Un inciso che la voce non legge.) [Nota 12, p. 4] "
    return [_ch("Un incontro", (frase * 2 + inciso) * 400, 0),
            _ch("La lettera", "Il mattino dopo.\n\n" + (frase * 2 + inciso) * 300, 1)]


ESTIMATES = {
    "voxcpm": lambda c, **k: voxcpm_tts.estimate_book_cost(c, "it", **k),
    "speechify": lambda c, **k: speechify_tts.estimate_book_cost(c, "en", **k),
    "gemini": lambda c, **k: gemini_tts.estimate_book_cost(c, GEMINI_VOICE, language="it", **k),
}


@pytest.mark.parametrize("engine", ESTIMATES)
def test_leggendo_tutto_il_prezzo_e_quello_di_prima(engine):
    chs = _book()
    norm = gemini_tts._normalize_text if engine == "gemini" else (lambda s: s)
    # La regola prima del fix: titolo parlato + corpo intero, parentesi comprese.
    before = [len(norm(spoken_title_prefix(c, c.text) + c.text)) for c in chs]
    est = ESTIMATES[engine](chs, **READ_BOTH)
    assert est["chars_per_chapter"] == before and est["chars_total"] == sum(before)


@pytest.mark.parametrize("engine", ESTIMATES)
def test_col_default_si_paga_il_testo_che_il_piano_legge(engine, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "10")   # 0 = listino non configurato
    chs = _book()
    tutto = ESTIMATES[engine](chs, **READ_BOTH)
    letto = ESTIMATES[engine](chs)
    assert letto["chars_total"] < 0.8 * tutto["chars_total"]
    assert letto["list_price_eur"] < tutto["list_price_eur"]
    # Solo le tonde lette: in mezzo.
    tonde = ESTIMATES[engine](chs, strip_round=False)
    assert letto["chars_total"] < tonde["chars_total"] < tutto["chars_total"]
    # Copertura del piano (`_check_text_coverage`): ora ~100%, prima ~75%.
    plan_chars = sum(b["chars"] for b in _plan_chunks(types.SimpleNamespace(chapters=chs)))
    assert plan_chars >= 0.95 * letto["chars_total"]
    assert plan_chars < 0.8 * tutto["chars_total"]


# ── firma del prezzo ──

def test_firma_invariata_col_default_diversa_se_si_leggono_le_parentesi():
    sig = audiobook_app._pricing_signature
    base = sig(GEMINI_VOICE, [0, 1], "+0%", "it", True)
    assert base == "gemini:flash31:Zephyr|0,1|+0%|it|1"
    assert sig(GEMINI_VOICE, [0, 1], "+0%", "it", True, paren=paren_strip_flags({})) == base
    assert sig(GEMINI_VOICE, [0, 1], "+0%", "it", True,
               paren=paren_strip_flags({"read_round_parens": True})) == base + "|read=r"
    assert sig(GEMINI_VOICE, [0, 1], "+0%", "it", True,
               paren=paren_strip_flags({"read_square_brackets": True})) == base + "|read=s"
    assert sig(GEMINI_VOICE, [0, 1], "+0%", "it", True, paren=READ_BOTH) == base + "|read=rs"


# ── route: stima e ordine PayPal sullo stesso testo letto ──

@pytest.fixture
def client():
    audiobook_app.app.config['TESTING'] = True
    with audiobook_app.app.test_client() as c:
        yield c


@pytest.fixture
def job_incisi():
    frase = "Frase letta dalla voce, una dopo l'altra, fino in fondo. "
    txt = (frase + "(Inciso lungo che la voce non legge mai, per nessun motivo.) ") * 2500
    ch = Chapter(index=0, title="Cap0", text=txt)
    info = BookInfo(title="T", author="A", language="it", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["pr1"] = {"info": info, "status": "analyzed"}
    yield "pr1"
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop("pr1", None)


def _body(job_id, **extra):
    return {"job_id": job_id, "voice_id": GEMINI_VOICE, "selected_chapters": [0],
            "ai_opt_enabled": False, **extra}


def test_stima_e_ordine_seguono_le_parentesi_lette(client, job_incisi):
    letto = client.post("/api/combined_estimate", json=_body(job_incisi)).get_json()
    tutto = client.post("/api/combined_estimate",
                        json=_body(job_incisi, read_round_parens=True)).get_json()
    assert 0 < letto["total_eur"] < tutto["total_eur"]
    assert letto["gemini_breakdown"]["chars"] < 0.6 * tutto["gemini_breakdown"]["chars"]

    with patch("payment._paypal_create_order") as mock:
        mock.return_value = {"id": "ORD-READ", "status": "CREATED"}
        r = client.post("/api/paypal_create_order_gemini", json=_body(
            job_incisi, read_round_parens=True, amount_eur=tutto["total_eur"]))
        assert r.status_code == 200, r.get_data(as_text=True)
        assert mock.call_args.kwargs["scope"].endswith("|read=r")

        mock.return_value = {"id": "ORD-STRIP", "status": "CREATED"}
        r = client.post("/api/paypal_create_order_gemini",
                        json=_body(job_incisi, amount_eur=letto["total_eur"]))
        assert r.status_code == 200, r.get_data(as_text=True)
        assert "read=" not in mock.call_args.kwargs["scope"]

    # L'importo quotato leggendo le tonde non vale per un ordine che non le legge.
    r = client.post("/api/paypal_create_order_gemini",
                    json=_body(job_incisi, amount_eur=tutto["total_eur"]))
    assert r.status_code == 409 and r.get_json()["error_code"] == "price_changed"


def test_il_bottone_paypal_premium_manda_le_parentesi():
    from pathlib import Path
    app_js = Path("static/js/app.js").read_text(encoding="utf-8")
    start = app_js.index("endpoint: '/api/paypal_create_order_gemini'")
    body = app_js[start:app_js.index("onConfirm:", start)]
    assert "...getParenFlags()" in body
