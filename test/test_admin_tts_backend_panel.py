"""Pannello «Backend TTS» della console admin: controlli e testo di stato.

Questi test guardano il JS servito dalla pagina, non un DOM eseguito: non c'e'
un runtime JS nella suite. Sono comunque i soli che possono cogliere il
difetto N2 lato client, che e' una condizione di abilitazione sbagliata:

- il controllo di **topup** (azzeramento del ledger di spesa) e' l'unica via
  che riarma il pre-allarme sul credito, e il ciclo normale del credito
  (residuo sotto soglia -> ricarica -> topup) avviene con Cloudflare ancora
  sano, cioe' **senza alcun trip**. Abilitarlo solo dopo un failover — com'era
  la casella accanto al pulsante di rientro — faceva partire l'allarme una
  volta sola nella vita dell'installazione;
- nel ramo «Cloudflare non configurato» il pannello non deve mai stampare
  `active` come se fosse il backend in esecuzione (N1): dopo un rollback lo
  stato su disco contiene `active: "cloudflare"` e la riga si contraddiceva da
  sola, e con la configurazione di default stampava «gira su auto», che e' un
  selettore, non un backend.

Mutazioni verificate in esecuzione (vedi final-fix-round-2-report.md):
`topupBtn.disabled = !cfConfigured || !s.tripped_at;` rende rossi
`test_the_topup_control_does_not_depend_on_a_trip` e
`test_only_one_place_decides_whether_topup_is_enabled`.
"""
import re

import pytest

import audiobook_app as app


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setattr(app, "ADMIN_TOKEN", "secret", raising=False)
    monkeypatch.setattr(app, "_admin_auth_ok", lambda tok: tok == "secret")
    app.app.config["TESTING"] = True
    c = app.app.test_client()
    r = c.get("/admin/audit-premium", headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    return r.get_data(as_text=True)


def _tb_apply_body(page):
    """Corpo della funzione JS `tbApply` (dalla firma alla riga che chiude la
    funzione, riconosciuta dall'indentazione a due spazi del sorgente)."""
    start = page.index("function tbApply(s){")
    end = page.index("\n  }", start)
    return page[start:end]


# --- N2 lato client: il topup deve essere raggiungibile senza trip ---------

def test_the_panel_has_a_dedicated_topup_control(page):
    assert 'id="tbTopupBtn"' in page
    # La vecchia casella legata al rientro non deve sopravvivere accanto al
    # nuovo controllo: due vie per la stessa azione divergono.
    assert 'id="tbTopup"' not in page


def test_the_topup_control_does_not_depend_on_a_trip(page):
    body = _tb_apply_body(page)
    assignments = re.findall(r"topupBtn\.disabled\s*=\s*([^;]+);", body)
    assert assignments, "tbApply deve decidere lo stato del controllo di topup"
    for expr in assignments:
        assert "tripped" not in expr, (
            f"l'abilitazione del topup non deve dipendere dal trip: {expr!r}. "
            f"Il credito quasi esaurito con Cloudflare ancora sano e' "
            f"esattamente il caso in cui il riarmo dell'allarme serve.")
        assert ("cfConfigured" in expr or "configured_backend" in expr), (
            f"il topup deve dipendere dalla configurazione dichiarata: {expr!r}")


def test_only_one_place_decides_whether_topup_is_enabled(page):
    # Una seconda assegnazione dentro il ramo del trip riporterebbe il
    # difetto per una via diversa, lasciando verde il test qui sopra se la
    # prima assegnazione restasse corretta.
    assert len(re.findall(r"topupBtn\.disabled\s*=", _tb_apply_body(page))) == 1


def test_topup_is_decided_before_the_unconfigured_branch_returns(page):
    body = _tb_apply_body(page)
    assert body.index("topupBtn.disabled") < body.index("if (!cfConfigured)"), (
        "lo stato del controllo di topup va deciso prima del ritorno "
        "anticipato del ramo «non configurato», altrimenti resta quello "
        "lasciato dal render precedente")


def test_the_topup_action_asks_confirmation_and_posts_its_own_action(page):
    start = page.index("async function tbTopup()")
    fn = page[start:page.index("\n  }", start)]
    assert "confirm(" in fn, (
        "azzerare il ledger e' irreversibile e falsa la stima se premuto per "
        "sbaglio: serve una conferma, come per il rientro")
    assert '"topup"' in fn or "'topup'" in fn
    # Il topup non deve passare dal rientro: quello tocca il breaker.
    assert '"reset"' not in fn


def test_the_reset_action_no_longer_carries_a_topup_field(page):
    start = page.index("async function tbReset()")
    fn = page[start:page.index("\n  }", start)]
    assert "topup" not in fn, (
        "il topup non e' piu' un campo del rientro: l'endpoint rifiuta la "
        "forma vecchia con 400 invece di ignorarla")


# --- N1: il ramo «non configurato» non annuncia un backend inesistente ----

def test_the_unconfigured_branch_never_prints_active_as_the_backend(page):
    body = _tb_apply_body(page)
    assert "esc(s.active)" not in body, (
        "`active` non e' il backend in esecuzione: e' il ripiego sulla "
        "configurazione dichiarata, e `auto` e' un selettore, non un backend")


def test_the_unconfigured_branch_names_the_selector_variable(page):
    body = _tb_apply_body(page)
    branch = body[body.index("if (!cfConfigured)"):]
    assert "ABM_GEMINI_BACKEND" in branch
    assert "esc(s.configured_backend)" in branch
