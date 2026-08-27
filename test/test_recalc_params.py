"""Test /admin/api/gemini_cost_audit/recalc-params endpoint.

NB: l'endpoint calcola DELTA% = sum(delta_eur) / sum(pricing_cost_eur_actual) * 100
sul gruppo (model, lang), sempre sulla base di LISTINO (D1), mai sul costo
reale sostenuto dal backend che ha eseguito il job (google_cost_eur_actual è
usato solo come fallback per record legacy privi di pricing_cost_eur_actual,
dove i due numeri coincidevano comunque). Produce un report a sezioni con
header fissi ("=== Aggregato globale ===", "=== Per velocità ==="). I record
vengono valutati solo se il gruppo ha >=3 campioni.
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


def _add(model, lang, delta_eur, job_id, google_cost=0.5, pricing_cost=None):
    rec = {
        "job_id": job_id,
        "model_key": model,
        "language": lang,
        "outcome": "completed",
        "user_price_eur_charged": 1.0,
        "google_cost_eur_actual": google_cost,
        "delta_eur": delta_eur,
    }
    if pricing_cost is not None:
        rec["pricing_cost_eur_actual"] = pricing_cost
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
    # 3 record stesso gruppo, delta positivo => DELTA% = 0.3/1.5 = +20% => margine alto
    for i in range(3):
        _add("flash25", "it", 0.1, f"j{i}")
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    assert r.status_code == 200
    d = r.get_json()
    assert d["groups_evaluated"] == 1
    line = _global_line(d, "flash25", "it")
    assert line is not None
    assert "margine alto" in line


def test_recalc_params_skips_small_group(client, admin_headers):
    # solo 2 record => gruppo non valutato (servono >=3)
    for i in range(2):
        _add("flash25", "it", 0.1, f"j{i}")
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    assert r.status_code == 200
    d = r.get_json()
    assert d["groups_total"] == 1
    assert d["groups_evaluated"] == 0
    line = _global_line(d, "flash25", "it")
    assert line is not None
    assert "campioni insufficienti" in line


def test_recalc_params_loss_suggestion(client, admin_headers):
    # delta negativo => DELTA% = -0.3/1.5 = -20% => margine in perdita
    for i in range(3):
        _add("pro25", "en", -0.1, f"k{i}")
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    d = r.get_json()
    line = _global_line(d, "pro25", "en")
    assert line is not None
    assert "perdita" in line


def test_recalc_params_ok_suggestion(client, admin_headers):
    # delta piccolo => DELTA% = 0.03/1.5 = +2% (entro +-5%) => parametri OK
    for i in range(3):
        _add("flash25", "fr", 0.01, f"m{i}")
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    d = r.get_json()
    line = _global_line(d, "flash25", "fr")
    assert line is not None
    assert "parametri OK" in line


def test_recalc_params_uses_pricing_cost_not_actual(client, admin_headers):
    # D1: DELTA% deve dividere per il LISTINO (pricing_cost_eur_actual),
    # mai per il costo reale (google_cost_eur_actual). Qui i due differiscono
    # deliberatamente: se il denominatore fosse il costo reale, il segnale
    # sarebbe "margine alto" (falso allarme); sul listino resta "parametri OK".
    # sum(delta)=0.15, sum(pricing)=7.5 => +2% (OK)
    # sum(delta)=0.15, sum(google)=1.5  => +10% (margine alto) <- SBAGLIATO
    for i in range(3):
        _add("pro25", "de", 0.05, f"p{i}", google_cost=0.5, pricing_cost=2.5)
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    d = r.get_json()
    line = _global_line(d, "pro25", "de")
    assert line is not None
    assert "parametri OK" in line
    assert "margine alto" not in line
