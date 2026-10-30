"""Throttle dei link email (/dl/<token>/m4b): tetto e cooldown contano i
richiedenti distinti, non le GET.

Ticket 30/10/2026 (job Tb_iwIaa): un telefono apre il link nella webview di QQ
Mail, interrompe dopo pochi KB e ripassa al download manager pochi secondi
dopo. Contato a ogni GET, il download manager prendeva 429 e alla sesta GET
l'M4B locale veniva cancellato. Qui si riproduce la sequenza dei log."""
import time

import pytest
import token_store

PHONE = "183.226.26.37"
PHONE_MOBILE_DATA = "106.83.133.247"


@pytest.fixture
def dl(fresh_app, tmp_path, monkeypatch):
    audiobook_app = fresh_app(env={"ABM_DATA_DIR": str(tmp_path)})
    audiobook_app.app.config["TESTING"] = True
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    m4b = tmp_path / "jobT" / "output_1" / "book.m4b"
    m4b.parent.mkdir(parents=True)
    m4b.write_bytes(b"\0" * 4096)
    token_store.download_tokens.clear()
    token_store.download_tokens["tokT"] = {
        "job_id": "jobT",
        "created_at": time.time(),
        "output_m4b": str(m4b),
        "book_title": "Libro",
        "original_filename": "book.epub",
    }
    audiobook_app._download_tracking.clear()
    client = audiobook_app.app.test_client()

    def get(ip):
        return client.get("/dl/tokT/m4b", environ_base={"REMOTE_ADDR": ip})

    def age_last_download(sec):
        audiobook_app._download_tracking[str(m4b)]["last_download"] -= sec

    return get, age_last_download, m4b


def test_phone_handoff_never_429_nor_deleted(dl):
    """Webview + download manager dallo stesso telefono, dodici GET in pochi
    secondi (la sequenza dei log aveva cinque 200 e nove 429): tutte 200,
    il file resta su disco."""
    get, age, m4b = dl
    for _ in range(12):
        assert get(PHONE).status_code == 200
    assert m4b.exists()


def test_phone_changing_network_counts_once_more(dl):
    """Il download manager passa ai dati mobili (IP diverso) dopo due minuti:
    conta come secondo richiedente, poi ripassa libero anche lui."""
    get, age, m4b = dl
    assert get(PHONE).status_code == 200
    age(145)
    for _ in range(3):
        assert get(PHONE_MOBILE_DATA).status_code == 200
        assert get(PHONE).status_code == 200
    assert m4b.exists()


def test_distinct_requesters_still_capped_and_cooled_down(dl):
    """Il link girato ad altri resta limitato: un richiedente nuovo entro 30 s
    prende 429, e il sesto richiedente distinto trova il file cancellato."""
    get, age, m4b = dl
    assert get("10.0.0.1").status_code == 200
    assert get("10.0.0.2").status_code == 429
    for n in range(2, 6):
        age(31)
        assert get(f"10.0.0.{n}").status_code == 200
    age(31)
    assert get("10.0.0.6").status_code == 410
    assert not m4b.exists()
