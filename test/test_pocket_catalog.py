"""Voci del modello batch (pocket_catalog): le voci inventate di VoxCPM che
hanno la clip dimostrativa Pocket, in /api/voices e su /api/voice_demo."""
import json
import os

import pytest

import audiobook_app
import pocket_catalog
import voxcpm_catalog

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
STEFANO = "pocket:v1:it-IT/Stefano"


def _wav(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")


@pytest.fixture
def demo_dir(monkeypatch, tmp_path):
    """Clip Pocket per Stefano (opening) e Federica (opening); una riga di
    demos.json con una clip che VoxCPM non ha, una che esce dalla cartella."""
    _wav(tmp_path / "it-IT" / "Stefano-opening.wav")
    _wav(tmp_path / "it-IT" / "Federica-opening.wav")
    rows = [
        {"voice": "it-IT/Stefano", "demo": "opening", "file": "it-IT/Stefano-opening.wav"},
        {"voice": "it-IT/Federica", "demo": "opening", "file": "it-IT/Federica-opening.wav"},
        {"voice": "it-IT/Stefano", "demo": "memory", "file": "../fuori.wav"},
        {"voice": "it-IT/Chiara", "demo": "opening", "file": "it-IT/Chiara-opening.wav"},
        {"voice": "it-IT/Stefano"},
        "spazzatura",
    ]
    (tmp_path / "demos.json").write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_POCKET_DEMO_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_POCKET_URL", "https://pocket.example")
    monkeypatch.setenv("ABM_POCKET_TOKEN", "tok")
    monkeypatch.delenv("ABM_POCKET_LANGUAGES", raising=False)
    monkeypatch.delenv("ABM_POCKET_RATE_EUR_PER_MCHAR", raising=False)
    voxcpm_catalog.invalidate_cache()
    audiobook_app._invalidate_voices_cache()
    yield tmp_path
    voxcpm_catalog.invalidate_cache()
    audiobook_app._invalidate_voices_cache()


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        yield c


def _pocket_voices(catalog):
    return [v for code, data in catalog.items() if not code.startswith("_")
            for v in data.get("voices", []) if v.get("engine") == "pocket"]


def test_only_voices_with_pocket_clips(demo_dir):
    by_id = {r["id"]: r for r in pocket_catalog.voices()}
    # Chiara ha la riga in demos.json ma VoxCPM non ha la clip «opening»: fuori.
    assert sorted(by_id) == ["pocket:v1:it-IT/Federica", STEFANO]
    # Ordine e carattere delle clip dal catalogo VoxCPM.
    (vox,) = [v for v in voxcpm_catalog.voices() if v["name"] == "Stefano"]
    assert [d["id"] for d in by_id[STEFANO]["demos"]] == [d["id"] for d in vox["demos"]]
    assert by_id[STEFANO]["persona"] == vox["persona"]


def test_clip_with_problem_is_not_offered(demo_dir):
    # Testo saltato anche all'ultimo tentativo: la clip non si ascolta, e una
    # voce senza altre clip non si offre.
    rows = [{"voice": "it-IT/Stefano", "demo": "opening", "file": "it-IT/Stefano-opening.wav",
             "problem": "9.6s per 233 car: testo saltato"},
            {"voice": "it-IT/Federica", "demo": "opening", "file": "it-IT/Federica-opening.wav"}]
    (demo_dir / "demos.json").write_text(json.dumps(rows), encoding="utf-8")
    assert [r["id"] for r in pocket_catalog.voices()] == ["pocket:v1:it-IT/Federica"]


def test_ui_entries_have_demo_urls_and_no_sample(demo_dir):
    (entry,) = [e for e in pocket_catalog.get_voices()["it"] if e["id"] == STEFANO]
    assert entry["engine"] == "pocket" and entry["model_label"] == "Audiobook Maker (batch)"
    assert entry["name"] == "Stefano (IT)" and "sample_url" not in entry
    assert entry["demos"][0]["url"].startswith("/api/voice_demo?voice=pocket%3Av1%3Ait-IT%2FStefano")


def test_languages_filter_and_missing_demos(demo_dir, monkeypatch):
    monkeypatch.setenv("ABM_POCKET_LANGUAGES", "en, xx")
    assert pocket_catalog.languages() == ("en",) and pocket_catalog.voices() == []
    monkeypatch.delenv("ABM_POCKET_LANGUAGES")
    (demo_dir / "demos.json").unlink()
    assert pocket_catalog.voices() == []


def test_demo_path(demo_dir):
    assert pocket_catalog.demo_path(STEFANO, "opening").endswith("Stefano-opening.wav")
    with pytest.raises(ValueError, match="fuori"):
        pocket_catalog.demo_path(STEFANO, "memory")
    with pytest.raises(ValueError, match="non presente"):
        pocket_catalog.demo_path(STEFANO, "fantasma")
    with pytest.raises(ValueError, match="non presente"):
        pocket_catalog.demo_path("pocket:v1:it-IT/Chiara", "opening")
    (demo_dir / "it-IT" / "Federica-opening.wav").unlink()
    with pytest.raises(FileNotFoundError):
        pocket_catalog.demo_path("pocket:v1:it-IT/Federica", "opening")


def test_api_voices_offers_batch_model(demo_dir, client):
    data = client.get("/api/voices").get_json()
    assert data["_pocket"] == {"available": True, "model_label": "Audiobook Maker (batch)",
                               "rate_eur_per_mchar": 11.0, "min_price_eur": 0.5}
    assert STEFANO in {v["id"] for v in _pocket_voices(data)}


def test_api_voices_hides_batch_model_in_catalog_mode(demo_dir, client, monkeypatch):
    monkeypatch.setenv("ABM_POCKET_RATE_EUR_PER_MCHAR", "0")
    audiobook_app._invalidate_voices_cache()
    data = client.get("/api/voices").get_json()
    assert data["_pocket"]["available"] is False and _pocket_voices(data) == []


def test_api_voice_demo_serves_pocket_clip(demo_dir, client):
    r = client.get("/api/voice_demo?voice=pocket:v1:it-IT/Stefano&clip=opening")
    assert r.status_code == 200 and r.mimetype == "audio/wav" and r.data[:4] == b"RIFF"
    assert client.get("/api/voice_demo?voice=pocket:v1:it-IT/Stefano&clip=memory").status_code == 400
    assert client.get("/api/voice_demo?voice=pocket:v1:it-IT/Stefano&clip=x").status_code == 404
    assert client.get("/api/voice_demo?voice=pocket:v1:../../etc/passwd&clip=opening").status_code == 404
