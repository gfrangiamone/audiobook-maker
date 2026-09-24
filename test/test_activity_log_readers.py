"""Lettori del business log in audiobook_app dopo il passaggio ad activity_log."""
from datetime import datetime, timedelta

import pytest

import activity_log
import audiobook_app


def _line(job, ts, op, fn="a.epub", cid="c", ip="1.1.1.1", voice="it-IT-X",
          lang="it", plat="web"):
    return f'{job} # {ts} # "{fn}" # {op} # {cid} # {ip} # {voice} # {lang} # {plat}'


def _write_by_month(d, lines_with_ts):
    """lines_with_ts: [(datetime, riga)] -> un file per mese."""
    by_month = {}
    for when, line in lines_with_ts:
        by_month.setdefault(when.strftime("%Y-%m"), []).append(line)
    for ym, lines in by_month.items():
        with open(d / f"activity_{ym}.log", "a", encoding="utf-8") as f:
            f.write("".join(l + "\n" for l in lines))


@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", tmp_path)
    activity_log.reset()
    for c in (audiobook_app._stats_today_cache, audiobook_app._stats_month_cache):
        c["value"] = None
        c["expires"] = 0.0
    yield tmp_path
    activity_log.reset()
    for c in (audiobook_app._stats_today_cache, audiobook_app._stats_month_cache):
        c["value"] = None
        c["expires"] = 0.0


def test_statistiche_community_contano_anche_i_titoli_col_cancelletto(logs):
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    _write_by_month(logs, [
        (now, _line("J1", ts, "COMPLETE", voice="it-IT-DiegoNeural")),
        (now, _line("J2", ts, "OPT_COMPLETE", fn="Saga # 2.epub", voice="en-US-GuyNeural")),
        (now, _line("J3", ts, "GENERATE", voice="it-IT-DiegoNeural")),
        (now, _line("J4", ts, "COMPLETE", voice="")),
    ])
    assert audiobook_app._stats_today_count() == 3
    res = audiobook_app._stats_month_by_lang()
    assert res["monthly"] == 3
    assert {r["lang"]: r["count"] for r in res["top"]} == {"it": 1, "en": 1}
    assert res["other"] == 0


def test_statistiche_community_escludono_ieri_dal_conteggio_di_oggi(logs):
    now = datetime.now()
    ieri = now - timedelta(days=1)
    _write_by_month(logs, [
        (ieri, _line("OLD", ieri.strftime("%Y-%m-%d %H:%M:%S"), "COMPLETE")),
        (now, _line("NEW", now.strftime("%Y-%m-%d %H:%M:%S"), "COMPLETE")),
    ])
    assert audiobook_app._stats_today_count() == 1
