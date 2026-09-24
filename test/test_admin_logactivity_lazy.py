"""/admin/log-activity: schede solo per gli ultimi giorni (e quelli con sessioni
in corso), gli altri giorni caricati da /admin/log-activity/day; cache delle
sessioni per mese; timestamp letti con fromisoformat."""
import html
import json
import re
from unittest.mock import patch

import pytest

import activity_log
import audiobook_app

YM = "2026-08"


def _line(job, ts, op="COMPLETE", cid="cidA", plat="web", voice="it-IT-DiegoNeural"):
    return f'{job} # {ts} # "{job}.epub" # {op} # {cid} # 1.1.1.1 # {voice} # it # {plat}'


LINES = [
    _line("D1a", "2026-08-01 09:00:00"),
    _line("D1b", "2026-08-01 10:00:00", op="GENERATE", cid="cidB", plat="android"),
    _line("D1c", "2026-08-01 11:00:00", op="TRANSLATE", cid="", voice="it>en +AI"),
    _line("D2a", "2026-08-02 09:00:00"),
    _line("D3a", "2026-08-03 09:00:00", cid="cidB"),
]


@pytest.fixture
def logdir(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "off")
    monkeypatch.delenv("ABM_ACTIVITY_LOG_DIR", raising=False)
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", tmp_path)
    activity_log.reset()
    audiobook_app._LOG_SESSIONS_CACHE.clear()
    (tmp_path / f"activity_{YM}.log").write_text("\n".join(LINES) + "\n", encoding="utf-8")
    yield tmp_path
    activity_log.reset()
    audiobook_app._LOG_SESSIONS_CACHE.clear()


def _get(url, auth=True):
    with patch.object(audiobook_app, "ADMIN_TOKEN", "tok-test"), \
         patch("audiobook_app._admin_auth_ok", return_value=auth):
        return audiobook_app.app.test_client().get(url)


def _page():
    r = _get(f"/admin/log-activity?{YM}")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def _group(page, day):
    m = re.search(r'<div class="day-group collapsed" data-day="' + day + r'"([^>]*)>', page)
    assert m, day
    return m.group(1)


def _card_filters(fragment):
    """Filtri di filterCards() che mostrano ciascuna scheda del frammento."""
    out = []
    for attrs in re.findall(r'<div class="card[^"]*" (data-status[^>]*)>', fragment):
        d = dict(re.findall(r'data-(\w+)="([^"]*)"', attrs))
        names = ["all", d["status"]]
        names += [k for k in ("identified", "recurring", "translation", "gemini",
                              "transferred") if d[k] == "1"]
        if d["platform"] in ("android", "ios"):
            names.append("mobile")
        out.append(names)
    return out


# ---------------------------------------------------------------- pagina

def test_solo_gli_ultimi_due_giorni_hanno_le_schede(logdir):
    page = _page()
    assert "data-lazy" not in _group(page, "2026-08-03")
    assert "data-lazy" not in _group(page, "2026-08-02")
    assert 'data-lazy="1"' in _group(page, "2026-08-01")
    assert "D3a" in page and "D2a" in page
    assert "D1a" not in page and "D1b" not in page


def test_giorno_con_sessione_in_corso_sempre_renderizzato(logdir):
    with patch.dict(audiobook_app.jobs, {"D1b": {"status": "optimizing"}}):
        page = _page()
    assert "data-lazy" not in _group(page, "2026-08-01")
    assert "D1b" in page and "card-in-progress" in page


def test_conteggi_del_giorno_pigro_uguali_alle_schede(logdir):
    page = _page()
    m = re.search(r'data-counts="([^"]*)"', _group(page, "2026-08-01"))
    assert m
    counts = json.loads(html.unescape(m.group(1)))
    frag = _get(f"/admin/log-activity/day?ym={YM}&day=2026-08-01").get_data(as_text=True)
    expected = {}
    for names in _card_filters(frag):
        for n in names:
            expected[n] = expected.get(n, 0) + 1
    assert counts == expected
    assert counts["all"] == 3 and counts["mobile"] == 1 and counts["translation"] == 1
    # cidA e cidB hanno un'altra sessione il 2 e il 3: ricorrenti anche se il
    # giorno e' pigro (il conteggio per client e' sull'intero mese)
    assert counts["recurring"] == 2


def test_js_carica_i_giorni_pigri(logdir):
    page = _page()
    assert "toggleDay(this.parentElement)" in page
    assert "/admin/log-activity/day?ym=" in page
    assert f"const LOG_YM = '{YM}';" in page


# ---------------------------------------------------------------- endpoint giorno

def test_giorno_restituisce_le_sue_schede_uguali_alla_pagina(logdir):
    frag = _get(f"/admin/log-activity/day?ym={YM}&day=2026-08-02").get_data(as_text=True)
    page = _page()
    start = page.index('<div class="day-cards">\n', page.index('data-day="2026-08-02"'))
    start += len('<div class="day-cards">\n')
    assert page[start:page.index("</div></div>\n", start)] == frag
    assert "D2a" in frag and "D1a" not in frag and "D3a" not in frag


def test_giorno_in_ordine_dal_piu_recente(logdir):
    frag = _get(f"/admin/log-activity/day?ym={YM}&day=2026-08-01").get_data(as_text=True)
    assert frag.index("D1c") < frag.index("D1b") < frag.index("D1a")


def test_giorno_senza_sessioni_vuoto(logdir):
    r = _get(f"/admin/log-activity/day?ym={YM}&day=2026-08-20")
    assert r.status_code == 200 and r.get_data(as_text=True) == ""


def test_giorno_richiede_admin(logdir):
    assert _get(f"/admin/log-activity/day?ym={YM}&day=2026-08-01", auth=False).status_code == 403


@pytest.mark.parametrize("qs", [
    "ym=2026-08&day=2026-07-31",          # giorno fuori dal mese
    "ym=2026-08&day=2026-08-1",
    "ym=2026-8&day=2026-08-01",
    "ym=2026-08&day=2026-08-01x",
    "ym=../x&day=2026-08-01",
    "day=2026-08-01",
    "ym=2026-08",
])
def test_giorno_parametri_non_validi(logdir, qs):
    assert _get(f"/admin/log-activity/day?{qs}").status_code == 400


def test_giorno_ui_disattivata_senza_token(logdir):
    with patch.object(audiobook_app, "ADMIN_TOKEN", ""):
        r = audiobook_app.app.test_client().get(f"/admin/log-activity/day?ym={YM}&day=2026-08-01")
    assert r.status_code == 404


# ---------------------------------------------------------------- cache e parse

def test_cache_riusata_finche_il_log_non_cambia(logdir):
    first = audiobook_app._log_sessions_cached(YM)
    assert audiobook_app._log_sessions_cached(YM) is first
    with open(logdir / f"activity_{YM}.log", "a", encoding="utf-8") as f:
        f.write(_line("D4a", "2026-08-04 09:00:00") + "\n")
    second = audiobook_app._log_sessions_cached(YM)
    assert second is not first and "D4a" in second[0]
    assert len([k for k in audiobook_app._LOG_SESSIONS_CACHE if k[0] == YM]) == 1


def test_cache_distingue_le_cartelle(logdir, tmp_path_factory, monkeypatch):
    audiobook_app._log_sessions_cached(YM)
    other = tmp_path_factory.mktemp("other")
    (other / f"activity_{YM}.log").write_text(_line("X1", "2026-08-05 09:00:00") + "\n",
                                              encoding="utf-8")
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", other)
    assert list(audiobook_app._log_sessions_cached(YM)[0]) == ["X1"]


def test_parse_scarta_timestamp_non_canonici(logdir):
    (logdir / f"activity_{YM}.log").write_text("\n".join([
        _line("OK1", "2026-08-01 09:00:00"),
        _line("T1", "2026-08-01T09:00:00"),
        _line("F1", "2026-08-01 09:00:00.5"),
        _line("S1", "2026-08-01 9:00:00"),
        _line("B1", "2026-08-32 09:00:00"),
    ]) + "\n", encoding="utf-8")
    sessions, _ = audiobook_app._parse_log_sessions(YM)
    assert list(sessions) == ["OK1"]
    assert sessions["OK1"]["first_dt"] == audiobook_app.datetime(2026, 8, 1, 9, 0, 0)
