"""Test /admin/api/gemini_cost_audit/recalc-params endpoint.

L'endpoint calcola DELTA% = sum(delta_eur) / sum(user_price_eur_should_have_been)
* 100 sul gruppo (model, lang): scostamento fra incasso e listino dovuto sui
secondi reali, mai sul costo del backend. Un delta sistematico e' un errore
della tabella car/s della lingua, e il suggerimento e' sull'env
ABM_GEMINI_CHARS_PER_SEC_<LANG>. Report a sezioni con header fissi
("=== Aggregato globale ===", "=== Per velocità ==="); i gruppi si valutano
solo con >=3 campioni.
"""
import pytest
import gemini_cost_audit


@pytest.fixture
def client(monkeypatch, tmp_path):
    import audiobook_app
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    audiobook_app.app.testing = True
    return audiobook_app.app.test_client()


@pytest.fixture
def admin_headers():
    return {"X-Admin-Token": "test-admin-token"}


def _add(model, lang, delta_eur, job_id, google_cost=0.5, should=1.0,
         chars=None, audio_seconds=None):
    rec = {
        "job_id": job_id,
        "model_key": model,
        "language": lang,
        "outcome": "completed",
        "user_price_eur_charged": 1.0,
        "user_price_eur_should_have_been": should,
        "google_cost_eur_actual": google_cost,
        "delta_eur": delta_eur,
    }
    if chars is not None:
        rec["chars_total"] = chars
        rec["audio_seconds_actual"] = audio_seconds
    gemini_cost_audit.append_record(rec)


def _global_line(d, model, lang):
    """Ritorna la riga del report 'Aggregato globale' per il gruppo dato."""
    for s in d["suggestions"]:
        if s.strip().startswith(f"[{model} / {lang}]"):
            return s
    return None


def test_recalc_params_requires_auth(client):
    r = client.get("/admin/api/gemini_cost_audit/recalc-params")
    assert r.status_code in (401, 403, 404)


def test_recalc_params_empty_returns_no_groups(client, admin_headers):
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d["groups_total"] == 0
    assert d["groups_evaluated"] == 0
    assert any("nessun record disponibile" in s for s in d["suggestions"])


def test_recalc_params_emits_suggestion_for_full_group(client, admin_headers):
    # 3 record, delta positivo => DELTA% = 0.3/3.0 = +10% => audio reale piu'
    # lungo del quotato => stima durata bassa, ridurre car/s.
    for i in range(3):
        _add("flash31", "it", 0.1, f"j{i}")
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    assert r.status_code == 200
    d = r.get_json()
    assert d["groups_evaluated"] == 1
    line = _global_line(d, "flash31", "it")
    assert line is not None
    assert "stima durata bassa" in line
    assert "riduci ABM_GEMINI_CHARS_PER_SEC_IT" in line


def test_recalc_params_skips_small_group(client, admin_headers):
    # solo 2 record => gruppo non valutato (servono >=3)
    for i in range(2):
        _add("flash31", "it", 0.1, f"j{i}")
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    assert r.status_code == 200
    d = r.get_json()
    assert d["groups_total"] == 1
    assert d["groups_evaluated"] == 0
    line = _global_line(d, "flash31", "it")
    assert line is not None
    assert "campioni insufficienti" in line


def test_recalc_params_high_estimate_suggestion(client, admin_headers):
    # delta negativo => DELTA% = -0.3/3.0 = -10% => audio piu' corto del
    # quotato => stima durata alta, alzare car/s.
    for i in range(3):
        _add("pro25", "en", -0.1, f"k{i}")
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    d = r.get_json()
    line = _global_line(d, "pro25", "en")
    assert line is not None
    assert "stima durata alta" in line
    assert "alza ABM_GEMINI_CHARS_PER_SEC_EN" in line


def test_recalc_params_ok_suggestion(client, admin_headers):
    # delta piccolo => DELTA% = 0.03/3.0 = +1% (entro +-5%) => parametri OK
    for i in range(3):
        _add("flash31", "fr", 0.01, f"m{i}")
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    d = r.get_json()
    line = _global_line(d, "flash31", "fr")
    assert line is not None
    assert "parametri OK" in line


def test_recalc_params_uses_listino_not_actual_cost(client, admin_headers):
    # DELTA% divide per il listino dovuto, mai per il costo del backend. Qui i
    # due differiscono deliberatamente: sul costo (0.5*3) il segnale sarebbe
    # +10% (falso allarme); sul listino (2.5*3) resta +2% (OK).
    for i in range(3):
        _add("pro25", "de", 0.05, f"p{i}", google_cost=0.5, should=2.5)
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    d = r.get_json()
    line = _global_line(d, "pro25", "de")
    assert line is not None
    assert "parametri OK" in line
    assert "stima durata" not in line


def test_recalc_params_reports_measured_chars_per_second(client, admin_headers):
    # Per velocita' normale la riga riporta i car/s reali del gruppo accanto
    # alla tabella di listino, per aggiornarla a colpo d'occhio.
    for i in range(3):
        _add("flash31", "it", 0.0, f"c{i}", chars=1200, audio_seconds=100.0)
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    d = r.get_json()
    rate_line = next(s for s in d["suggestions"]
                     if s.strip().startswith("[flash31 / it / step=+0"))
    assert "car/s reali 12.00" in rate_line
    assert "tabella 14.60" in rate_line
