"""Timestamp della console admin: UTC sul filo, ora locale a video.

Il server persiste SEMPRE ISO in UTC (`tts_backend_state._now()` chiude con
"Z", `gemini_cost_audit` con "+00:00"). La console li stampava grezzi, con un
`.slice(0,19).replace("T"," ")` che toglieva il designatore di fuso senza
convertire: il 21/09/2026 il pannello Backend TTS ha mostrato «Dal 11:07:58»
per un failover delle 13:07:58 CEST, facendolo sembrare vecchio di due ore e
contraddicendo i log dell'AI Gateway, che mostravano richieste riuscite fino
alle 13:05. Due ore di differenza sono esattamente l'offset CEST: un bug di
sola visualizzazione, ma che ha portato a diagnosticare un failover fantasma.

Come i test del pannello Backend TTS, questi guardano il JS servito dalla
pagina: non c'e' un runtime JS nella suite. Cio' che possono garantire e' che
la conversione ci sia, che sia UNA sola (un secondo formatter diverge), e che
nessuna delle colonne temporali sia tornata alla stampa grezza.

Mutazioni verificate a mano, una per test:
- rimettere `.slice(0,19).replace("T"," ")` su uno qualunque dei tre campi
  rende rosso `test_no_iso_timestamp_is_printed_raw`;
- togliere l'aggiunta di "Z" in `fmtIso` rende rosso
  `test_fmtiso_treats_a_naive_timestamp_as_utc`.
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


def _fmtiso_body(page):
    start = page.index("function fmtIso(s){")
    end = page.index("\n  }", start)
    return page[start:end]


def test_the_console_has_exactly_one_timestamp_formatter(page):
    # Due formatter divergono: quello dimenticato e' il prossimo a stampare UTC.
    assert page.count("function fmtIso(s){") == 1


def test_no_iso_timestamp_is_printed_raw(page):
    # La firma della stampa grezza: togliere il fuso da un ISO senza convertire.
    raw = re.findall(r'\.slice\(0,\s*19\)\.replace\("T",\s*" "\)', page)
    # L'unica occorrenza ammessa e' il ripiego DENTRO fmtIso, per un valore che
    # `new Date` non sa parsare: li' e' meglio di una stringa vuota.
    assert len(raw) == 1, f"{len(raw)} stampe grezze di ISO: {raw}"
    assert re.search(r'\.slice\(0,\s*19\)\.replace\("T",\s*" "\)',
                     _fmtiso_body(page))


def test_every_timestamp_column_goes_through_the_formatter(page):
    # I tre campi ISO della console: audit (ts), kill-switch (updated_at),
    # pannello backend (tripped_at).
    assert page.count("esc(fmtIso(r.ts))") == 3
    assert "fmtIso(s.updated_at)" in page
    assert "esc(fmtIso(s.tripped_at))" in page


def test_fmtiso_treats_a_naive_timestamp_as_utc(page):
    # Un ISO senza designatore di fuso e' interpretato da JS come ora LOCALE:
    # senza questa aggiunta un record vecchio scritto naive verrebbe spostato
    # nella direzione opposta a quella che il fix vuole correggere.
    body = _fmtiso_body(page)
    assert 'raw + "Z"' in body
    # Il ramo "ha gia' un fuso" deve riconoscere sia "Z" sia "+hh:mm"/"-hh:mm"
    # (isoformat() di Python scrive la seconda forma), altrimenti la "Z" verrebbe
    # appiccicata a un timestamp che un fuso ce l'ha gia' e `new Date` fallirebbe.
    assert "[+-]" in body
    assert "(Z|" in body


def test_fmtiso_is_defined_before_its_first_use(page):
    first_use = min(page.index("esc(fmtIso(r.ts))"),
                    page.index("fmtIso(s.updated_at)"))
    assert page.index("function fmtIso(s){") < first_use


def test_the_output_shape_of_the_columns_is_unchanged(page):
    # Il valore cambia, la forma no: le colonne restano «YYYY-MM-DD HH:MM:SS».
    # toLocaleString('it-IT') darebbe «21/09/2026, 13:07:58» e cambierebbe la
    # larghezza di ogni tabella dell'audit.
    body = _fmtiso_body(page)
    assert "toLocaleString" not in body
    assert 'd.getFullYear() + "-"' in body
