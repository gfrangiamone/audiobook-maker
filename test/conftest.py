from datetime import datetime
from unittest.mock import patch

import pytest


@pytest.fixture
def reset_backend_cache():
    """Reset cache backend Gemini tra test (module-level state)."""
    import gemini_tts as gt
    gt._BACKEND = {}
    gt._available = None
    gt._clients_by_location = {}
    yield
    gt._BACKEND = {}
    gt._available = None
    gt._clients_by_location = {}


def _recent_months(n):
    """Mese corrente e i precedenti: /admin/log-activity apre su `now()`."""
    y, m = datetime.now().year, datetime.now().month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


@pytest.fixture(scope="session")
def admin_log_page(tmp_path_factory):
    """HTML di /admin/log-activity, reso una sola volta su una SCRIPT_DIR finta.

    La vista costruisce una card per ogni sessione del mese corrente: sul
    checkout di sviluppo, dove finiscono copie dei log di produzione (14 MB,
    17k sessioni), ogni render costa decine di secondi. I test guardano solo
    il markup e il JS della pagina, quindi bastano tre log minuscoli.
    """
    import audiobook_app

    d = tmp_path_factory.mktemp("adminlogs")
    for i, m in enumerate(_recent_months(3)):
        line = (f'j1 # {m}-01 10:00:00 # "a.epub" # COMPLETE # cidA # 1.1.1.1'
                ' # it-IT-DiegoNeural # it # web\n')
        (d / f"activity_{m}.log").write_text(line if i == 0 else "", encoding="utf-8")
    with patch.object(audiobook_app, "SCRIPT_DIR", d), \
         patch.object(audiobook_app, "ADMIN_TOKEN", "tok-test"), \
         patch("audiobook_app._admin_auth_ok", return_value=True):
        r = audiobook_app.app.test_client().get("/admin/log-activity")
    assert r.status_code == 200
    return r.get_data(as_text=True)
