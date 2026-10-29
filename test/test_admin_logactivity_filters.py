"""Filtri/bottoni stats in /admin/log-activity:
- rimosso il filtro "Email inviate"
- aggiunto il filtro "Traduzioni" a sinistra di "PREMIUM"
- "GEN. GEMINI" rinominato "PREMIUM"
- aggiunto filtro "Da mobile" (platform=android|ios) e "Spostati su mobile" (TRANSFER)
"""
import pathlib
import tempfile
from unittest.mock import patch

import pytest

import audiobook_app


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


def _page():
    with patch.object(audiobook_app, "ADMIN_TOKEN", "tok-test"), \
         patch("audiobook_app._admin_auth_ok", return_value=True):
        r = audiobook_app.app.test_client().get("/admin/log-activity")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_email_filter_removed():
    html = _page()
    assert 'data-filter="email"' not in html
    assert "filterCards('email'" not in html


def test_translation_filter_added():
    html = _page()
    assert 'data-filter="translation"' in html
    assert "filterCards('translation'" in html
    # La logica JS deve gestire il nuovo filtro
    assert "card.dataset.translation" in html


def test_premium_label_replaces_gemini():
    html = _page()
    assert "PREMIUM" in html
    # Il vecchio testo del bottone non deve comparire
    assert "Gen. Gemini" not in html
    assert "Gemini runs" not in html


def test_translation_stat_left_of_premium():
    html = _page()
    tr_idx = html.index('data-filter="translation"')
    gem_idx = html.index('data-filter="gemini"')
    assert tr_idx < gem_idx


# ---------------------------------------------------------------------------
# Nuovi test: filtri "Da mobile" e "Spostati su mobile"
# ---------------------------------------------------------------------------

def _page_with_log(monkeypatch, log_lines):
    """Scrive un log temporaneo, esegue GET /admin/log-activity e ritorna l'HTML."""
    import datetime
    ym = datetime.datetime.now().strftime("%Y-%m")
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    log_path = tmpdir / f"activity_{ym}.log"
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", tmpdir)
    with patch.object(audiobook_app, "ADMIN_TOKEN", "tok-test"), \
         patch("audiobook_app._admin_auth_ok", return_value=True):
        r = audiobook_app.app.test_client().get(f"/admin/log-activity?{ym}")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_mobile_platform_card_attr(monkeypatch):
    """Una sessione con platform=android deve produrre data-platform="android" e data-transferred="0"."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f'SID_ANDROID # {ts} # "book.epub" # GENERATE # cid1 # 1.2.3.4 # en-US-JennyNeural # en # android',
    ]
    html = _page_with_log(monkeypatch, lines)
    assert 'data-platform="android"' in html
    assert 'data-transferred="0"' in html


def test_transferred_card_attr(monkeypatch):
    """Una sessione con evento TRANSFER deve produrre data-transferred="1"."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f'SID_WEB # {ts} # "book.epub" # GENERATE # cid2 # 1.2.3.5 # en-US-JennyNeural # en # ',
        f'SID_WEB # {ts} # "book.epub" # TRANSFER # cid2 # 1.2.3.5 # # en # ',
    ]
    html = _page_with_log(monkeypatch, lines)
    assert 'data-transferred="1"' in html


def test_mobile_and_transferred_filter_labels_in_html(monkeypatch):
    """L'HTML deve contenere i due nuovi stat-box con data-filter="mobile" e data-filter="transferred"."""
    html = _page_with_log(monkeypatch, [])
    assert 'data-filter="mobile"' in html
    assert 'data-filter="transferred"' in html
    assert "Da mobile" in html
    assert "Spostati su mobile" in html


def test_mobile_filter_js_logic(monkeypatch):
    """Il JS filterCards deve gestire i nuovi filtri mobile e transferred."""
    html = _page_with_log(monkeypatch, [])
    assert "card.dataset.platform" in html
    assert "card.dataset.transferred" in html


def test_transfer_keeps_book_title(monkeypatch):
    """Il TRANSFER logga filename vuoto: il titolo del libro deve restare nella card."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f'SID_KEEP # {ts} # "Il Nome della Rosa.epub" # GENERATE # cid3 # 1.2.3.6 # en-US-JennyNeural # en # ',
        f'SID_KEEP # {ts} # "" # TRANSFER # cid3 # 1.2.3.6 # # en # ',
    ]
    html = _page_with_log(monkeypatch, lines)
    assert "Il Nome della Rosa" in html
    assert 'data-transferred="1"' in html


# ---------------------------------------------------------------------------
# Filtro PREMIUM: un job del wizard combinato (ottimizzazione AI + auto-gen
# con voce premium) deve rientrare nel filtro gia' in fase di ottimizzazione,
# prima che l'evento GENERATE venga scritto.
# ---------------------------------------------------------------------------

def test_premium_filter_counts_optimize_with_premium_voice(monkeypatch):
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f'SID_OPT # {ts} # "book.epub" # OPTIMIZE # cid9 # 1.2.3.9 # gemini:flash31:Kore # it # ',
    ]
    html = _page_with_log(monkeypatch, lines)
    assert 'data-gemini="1"' in html
    stat = html[html.index('data-filter="gemini"'):]
    assert '<div class="num">1</div>' in stat[:400]


def test_premium_filter_ignores_optimize_without_voice(monkeypatch):
    """Ottimizzazione senza auto-gen (voce vuota): non e' un avvio premium."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f'SID_OPT2 # {ts} # "book.epub" # OPTIMIZE # cid8 # 1.2.3.8 # # it # ',
    ]
    html = _page_with_log(monkeypatch, lines)
    assert 'data-gemini="0"' in html


def test_premium_filter_not_fooled_by_earlier_premium_voice(monkeypatch):
    """La voce premium su un evento non di avvio (es. anteprima) non basta:
    conta solo la voce portata da GENERATE/OPTIMIZE."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f'SID_PRE # {ts} # "book.epub" # PREVIEW # cid7 # 1.2.3.7 # gemini:flash31:Kore # it # ',
        f'SID_PRE # {ts} # "book.epub" # OPTIMIZE # cid7 # 1.2.3.7 # # it # ',
    ]
    html = _page_with_log(monkeypatch, lines)
    assert 'data-gemini="0"' in html


def _premium_stat_count(html):
    stat = html[html.index('data-filter="gemini"'):]
    return stat[stat.index('<div class="num">') + len('<div class="num">'):stat.index('</div>')]


def test_premium_filter_counts_cloned_voice_log_label(monkeypatch):
    """La voce campionata finisce nel log come etichetta neutra (il token e'
    un segreto): il GENERATE con quell'etichetta e' un avvio PREMIUM."""
    import datetime
    import voice_utils
    logged = audiobook_app._voice_for_log(voice_utils.VOXCPM_MINE_PREFIX + "ab" * 16)
    assert not voice_utils.is_premium_voice(logged)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f'SID_CLONE # {ts} # "book.epub" # GENERATE # cid6 # 1.2.3.6 # {logged} # it # ',
    ]
    html = _page_with_log(monkeypatch, lines)
    assert 'data-gemini="1"' in html
    assert _premium_stat_count(html) == "1"


def _running_job(voice, paid_eur):
    return {"status": "generating", "voice": voice, "progress_current": 1,
            "progress_total": 10,
            "payment": {"token": "t", "total_eur": paid_eur, "method": "paypal"}}


def test_premium_filter_counts_running_premium_job(monkeypatch):
    """Regressione be7udP_BVEdRTGZBGlEULw: job premium pagato in corso (scheda
    gialla) senza una riga di avvio premium nel log. Il filtro e il contatore
    PREMIUM devono seguire il job in memoria, come lo stato in corso."""
    import datetime
    import voice_utils
    sid = "be7udP_BVEdRTGZBGlEULw"
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f'{sid} # {ts} # "book.epub" # ANALYZE # cid5 # 1.2.3.5 # # it # ']
    monkeypatch.setitem(audiobook_app.jobs, sid,
                        _running_job(voice_utils.VOXCPM_MINE_PREFIX + "cd" * 16, 4.5))
    html = _page_with_log(monkeypatch, lines)
    assert 'class="card card-in-progress card-paid" data-status="in_progress"' in html
    assert 'data-gemini="1"' in html
    assert _premium_stat_count(html) == "1"


def test_premium_filter_ignores_running_standard_voice_job(monkeypatch):
    import datetime
    sid = "RUN_STD"
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f'{sid} # {ts} # "book.epub" # GENERATE # cid4 # 1.2.3.4 # it-IT-DiegoNeural # it # ']
    monkeypatch.setitem(audiobook_app.jobs, sid, _running_job("it-IT-DiegoNeural", 0))
    html = _page_with_log(monkeypatch, lines)
    assert 'data-status="in_progress"' in html
    assert 'data-gemini="0"' in html
    assert _premium_stat_count(html) == "0"


def test_api_optimize_logs_auto_generate_voice():
    """/api/optimize con auto_generate scrive la voce di destinazione
    sull'evento OPTIMIZE, cosi' il pannello admin la vede subito."""
    import inspect
    src = inspect.getsource(audiobook_app.api_optimize)
    assert '"OPTIMIZE"' in src
    idx = src.index('"OPTIMIZE"')
    assert 'opt_voice' in src[idx:idx + 400]
