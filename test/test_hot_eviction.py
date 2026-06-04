"""La finestra calda evacua i file di output locali se: marker presente,
età oltre la finestra, e oggetto confermato su cold storage."""
import importlib
import pytest


@pytest.fixture
def aa(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_HOT_WINDOW_SEC", "7200")
    import storage_tiering
    importlib.reload(storage_tiering)
    import audiobook_app
    importlib.reload(audiobook_app)
    return audiobook_app, storage_tiering


def test_evicts_local_after_hot_window(aa, monkeypatch, tmp_path):
    audiobook_app, storage_tiering = aa
    import storage_backend
    out = tmp_path / "job1" / "output_1"
    out.mkdir(parents=True)
    audio = out / "book.m4b"
    audio.write_bytes(b"x")
    storage_tiering.mark_cloud_uploaded(out, when=__import__("time").time() - 10800)

    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    # cold combacia per dimensione col locale (1 byte) → evict consentito
    monkeypatch.setattr(storage_backend, "object_size", lambda k: audio.stat().st_size)
    audiobook_app.jobs["job1"] = {"voice": "it-IT-IsabellaNeural"}

    audiobook_app._evict_hot_local()
    assert not audio.exists()
    assert (out / ".cloud_uploaded").exists()


def test_keeps_local_within_hot_window(aa, monkeypatch, tmp_path):
    audiobook_app, storage_tiering = aa
    import storage_backend
    out = tmp_path / "job2" / "output_1"
    out.mkdir(parents=True)
    audio = out / "book.mp3"
    audio.write_bytes(b"x")
    storage_tiering.mark_cloud_uploaded(out, when=__import__("time").time())

    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "object_size", lambda k: audio.stat().st_size)
    audiobook_app.jobs["job2"] = {"voice": "it-IT-IsabellaNeural"}

    audiobook_app._evict_hot_local()
    assert audio.exists()


def test_no_evict_if_object_not_confirmed(aa, monkeypatch, tmp_path):
    audiobook_app, storage_tiering = aa
    import storage_backend
    out = tmp_path / "job3" / "output_1"
    out.mkdir(parents=True)
    audio = out / "book.m4b"
    audio.write_bytes(b"x")
    storage_tiering.mark_cloud_uploaded(out, when=__import__("time").time() - 10800)

    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "object_size", lambda k: None)
    # La copia-prima-di-evict viene tentata ma non conferma (object_size resta
    # None) → il locale NON va cancellato.
    monkeypatch.setattr(storage_backend, "upload_file", lambda p, k: None)
    audiobook_app.jobs["job3"] = {"voice": "it-IT-IsabellaNeural"}

    audiobook_app._evict_hot_local()
    assert audio.exists()


def test_uploads_missing_cold_then_evicts(aa, monkeypatch, tmp_path):
    """Se la copia cold manca, l'eviction la CARICA, la conferma e SOLO allora
    cancella il locale (invariante: mai distruggere l'unica copia)."""
    audiobook_app, storage_tiering = aa
    import storage_backend
    out = tmp_path / "job5" / "output_1"
    out.mkdir(parents=True)
    audio = out / "book.m4b"
    audio.write_bytes(b"x")
    storage_tiering.mark_cloud_uploaded(out, when=__import__("time").time() - 10800)

    uploaded = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "upload_file", lambda p, k: uploaded.append(k))
    # Mancante (size None) prima dell'upload, dimensione locale dopo.
    monkeypatch.setattr(storage_backend, "object_size",
                        lambda k: audio.stat().st_size if k in uploaded else None)
    audiobook_app.jobs["job5"] = {"voice": "it-IT-IsabellaNeural"}

    audiobook_app._evict_hot_local()
    assert uploaded, "doveva caricare la copia mancante prima dell'eviction"
    assert not audio.exists()  # rimosso solo dopo copia cold confermata


def test_cold_m4b_valid_detects_moov(aa, monkeypatch):
    """F4: _cold_m4b_valid cammina gli atom del m4b cold e distingue un file
    finalizzato (moov presente) da uno troncato (solo ftyp+mdat oltre EOF)."""
    audiobook_app, storage_tiering = aa
    import storage_backend
    def box(typ, size): return size.to_bytes(4, "big") + typ
    valid = box(b"ftyp", 16) + b"\0"*8 + box(b"moov", 16) + b"\0"*8        # moov c'è
    trunc = box(b"ftyp", 16) + b"\0"*8 + (10**9).to_bytes(4, "big") + b"mdat" + b"\0"*8  # mdat oltre EOF
    store = {"b": valid}
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_tiering, "key_for_path", lambda p: "k")
    monkeypatch.setattr(storage_backend, "object_size", lambda k: len(store["b"]))
    monkeypatch.setattr(storage_backend, "get_range", lambda k, s, e: store["b"][s:e+1])

    assert audiobook_app._cold_m4b_valid("/x/book.m4b") is True
    store["b"] = trunc
    assert audiobook_app._cold_m4b_valid("/x/book.m4b") is False


def test_no_overwrite_when_cold_larger_than_local(aa, monkeypatch, tmp_path):
    """B3 guard B (incidente 2026-06): cold PIU' GRANDE del locale = locale
    sospetto (es. m4b silente da un run fallito). MAI sovrascrivere il cold
    col locale, MAI evictare: entrambe le copie restano per ispezione."""
    audiobook_app, storage_tiering = aa
    import storage_backend
    out = tmp_path / "jobB3" / "output_1"
    out.mkdir(parents=True)
    audio = out / "book.m4b"
    audio.write_bytes(b"x")  # 1 byte (garbage)
    storage_tiering.mark_cloud_uploaded(out, when=__import__("time").time() - 10800)

    uploaded = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "upload_file",
                        lambda p, k: uploaded.append(k))
    monkeypatch.setattr(storage_backend, "object_size", lambda k: 15394949)
    audiobook_app.jobs["jobB3"] = {"voice": "it-IT-IsabellaNeural"}

    audiobook_app._evict_hot_local()
    assert not uploaded, "il cold piu' grande NON va sovrascritto col locale"
    assert audio.exists(), "il locale NON va evictato su mismatch sospetto"


def test_no_evict_for_error_job(aa, monkeypatch, tmp_path):
    """B3 guard A: job in stato error -> output locale non autoritativo,
    niente eviction ne' upload per l'intera job dir."""
    audiobook_app, storage_tiering = aa
    import storage_backend
    out = tmp_path / "jobERR" / "output_1"
    out.mkdir(parents=True)
    audio = out / "book.m4b"
    audio.write_bytes(b"x")
    storage_tiering.mark_cloud_uploaded(out, when=__import__("time").time() - 10800)

    uploaded = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "upload_file",
                        lambda p, k: uploaded.append(k))
    monkeypatch.setattr(storage_backend, "object_size",
                        lambda k: audio.stat().st_size)
    audiobook_app.jobs["jobERR"] = {"voice": "gemini:flash25:Puck",
                                    "status": "error"}

    audiobook_app._evict_hot_local()
    assert audio.exists()
    assert not uploaded


def test_no_evict_with_forensic_marker(aa, monkeypatch, tmp_path):
    """B3 guard A: marker forense valido (job rimborsato in attesa di analisi)
    -> congelate entrambe le copie anche se il job non e' piu' in memoria."""
    import json as _json
    import time as _time
    audiobook_app, storage_tiering = aa
    import storage_backend
    jdir = tmp_path / "jobFOR"
    out = jdir / "output_1"
    out.mkdir(parents=True)
    audio = out / "book.m4b"
    audio.write_bytes(b"x")
    storage_tiering.mark_cloud_uploaded(out, when=_time.time() - 10800)
    (jdir / ".forensic_retain.json").write_text(_json.dumps({
        "retain_until": _time.time() + 3600,
        "outcome": "failed_quality_refunded",
    }), encoding="utf-8")

    uploaded = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "upload_file",
                        lambda p, k: uploaded.append(k))
    monkeypatch.setattr(storage_backend, "object_size",
                        lambda k: audio.stat().st_size)
    # job non in memoria (post-restart): protegge solo il marker su disco

    audiobook_app._evict_hot_local()
    assert audio.exists()
    assert not uploaded


def test_reuploads_when_cold_size_mismatch(aa, monkeypatch, tmp_path):
    """F3: se il cold ESISTE ma è più piccolo del locale (es. m4b troncato
    caricato mid-write), l'eviction NON si fida: ri-carica il locale completo,
    verifica che la size combaci, e solo allora cancella."""
    audiobook_app, storage_tiering = aa
    import storage_backend
    out = tmp_path / "job7" / "output_1"
    out.mkdir(parents=True)
    audio = out / "book.m4b"
    audio.write_bytes(b"complete-audio-bytes")  # 20 byte
    storage_tiering.mark_cloud_uploaded(out, when=__import__("time").time() - 10800)

    uploaded = []
    cold = {"size": 3}  # cold troncato (3 byte) presente da prima
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    def _upload(p, k):
        uploaded.append(k)
        cold["size"] = audio.stat().st_size  # il re-upload porta la size a quella locale
    monkeypatch.setattr(storage_backend, "upload_file", _upload)
    monkeypatch.setattr(storage_backend, "object_size", lambda k: cold["size"])
    audiobook_app.jobs["job7"] = {"voice": "it-IT-IsabellaNeural"}

    audiobook_app._evict_hot_local()
    assert uploaded, "il cold troncato doveva essere ri-caricato dal locale"
    assert not audio.exists()  # cancellato solo dopo che le size combaciano
