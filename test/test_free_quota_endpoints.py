"""Guardia di regressione: /api/combined_estimate e
/api/paypal_create_order_gemini devono concordare sull'importo dovuto quando
la quota gratuita cumulativa del client e' esaurita.

E' lo scenario dell'incidente "402 Speechify" letto al contrario: li' la UI
mostrava "gratis" mentre il backend pretendeva un pagamento (divergenza fra i
due punti di prezzo). Qui verifichiamo che la divergenza sia impossibile: lo
stesso importo post-quota che /api/combined_estimate mostra all'utente deve
essere l'unico importo che /api/paypal_create_order_gemini accetta.
"""
import pytest
from unittest.mock import patch

import audiobook_app
import free_quota
import gemini_tts
from epub_to_tts import BookInfo, Chapter

# NB: accesso a app/jobs/_jobs_lock via attributo a runtime, mai from-import
# (vedi commento in test_paypal_create_gemini.py): altri test nella suite
# completa fanno importlib.reload(audiobook_app)/reload(generation_engine) e
# ri-bindano audiobook_app.jobs; un from-import a collection time resterebbe
# legato agli oggetti pre-reload.

CID = "cid_quota_endpoint_test"
VOICE = "gemini:flash25:Zephyr"


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", CID)
        yield c


@pytest.fixture
def jb():
    # 5000 caratteri -> list_price_eur ~0.45 con la voce Zephyr/flash25
    # (verificato empiricamente): sotto il floor 0.50 usato nel test, cosi'
    # l'importo "quota esaurita" (floor) e quello "quota disponibile"
    # (grezzo) sono garantiti diversi.
    ch = Chapter(index=0, title="Cap0", text="A" * 5000)
    info = BookInfo(
        title="T", author="A", language="it", chapters=[ch],
        total_words=ch.word_count, total_chars=ch.char_count,
        estimated_duration_minutes=1.0,
    )
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["qej1"] = {"info": info, "status": "analyzed"}
    yield "qej1", [ch]
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop("qej1", None)


def test_estimate_and_order_agree_when_quota_exhausted(client, jb, tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_PREMIUM_MIN_COST_EUR", "0.50")
    # Soglia gratuita PREMIUM generosa: il job resta "sotto soglia" cosi' la
    # decisione passa dal ramo quota (non dal ramo "gia' a pagamento").
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "5.00")

    job_id, chs = jb

    # Prezzo di listino reale per questo libro/voce, calcolato con la stessa
    # funzione pubblica usata dal backend (gemini_tts.estimate_book_cost).
    # Serve solo a costruire uno scenario di quota esaurita deterministico,
    # non a duplicare la logica di prezzo dell'endpoint.
    est = gemini_tts.estimate_book_cost(chs, VOICE, language="it", rate_pct="+0%")
    list_price = round(est["list_price_eur"], 2)
    assert 0 < list_price < 0.50, (
        "precondizione test: il fixture deve produrre un listino sotto il "
        f"floor 0.50 per garantire divergenza dall'importo post-quota (got {list_price})"
    )

    # Consuma quasi tutta la quota del client: qualunque list_price positivo
    # la esaurisce (remaining=0.01), scattando il ramo floor.
    free_quota.consume(CID, 1.99, "preload_job")
    expected = free_quota.decision(CID, VOICE, list_price)
    assert expected["quota_exhausted"] is True
    assert expected["is_free"] is False
    assert expected["due_eur"] == pytest.approx(0.50)
    assert expected["due_eur"] != list_price  # garanzia di divergenza per il check finale

    # --- 1. /api/combined_estimate deve mostrare l'importo post-quota ---
    r = client.post("/api/combined_estimate", json={
        "job_id": job_id,
        "voice_id": VOICE,
        "selected_chapters": [0],
        "ai_opt_enabled": False,
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["total_eur"] == pytest.approx(expected["due_eur"])
    assert body["quota_exhausted"] is True
    assert body["is_free"] is False

    # --- 2. /api/paypal_create_order_gemini con LO STESSO importo: accettato ---
    with patch("payment._paypal_create_order") as mock:
        mock.return_value = {"id": "ORDERQ", "status": "CREATED"}
        r_ok = client.post("/api/paypal_create_order_gemini", json={
            "job_id": job_id,
            "voice_id": VOICE,
            "selected_chapters": [0],
            "ai_opt_enabled": False,
            "amount_eur": body["total_eur"],
        })
    assert r_ok.status_code == 200, r_ok.get_data(as_text=True)
    assert r_ok.get_json()["amount"] == pytest.approx(body["total_eur"])

    # --- 3. Importo "quota disponibile" (grezzo, non quota-aware): respinto ---
    # E' esattamente la divergenza dell'incidente "402 Speechify" letto al
    # contrario: qui deve essere impossibile che l'ordine accetti un importo
    # diverso da quello mostrato dalla stima.
    r_stale = client.post("/api/paypal_create_order_gemini", json={
        "job_id": job_id,
        "voice_id": VOICE,
        "selected_chapters": [0],
        "ai_opt_enabled": False,
        "amount_eur": list_price,
    })
    assert r_stale.status_code == 409, r_stale.get_data(as_text=True)
    assert "mismatch" in (r_stale.get_json().get("error") or "").lower()
