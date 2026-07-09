"""Test del primitivo condiviso community_store.atomic_write_json.

Copre le garanzie su cui si appoggiano tutte le persistenze snapshot
(token, pagamenti, voucher, usage): roundtrip, atomicita' su crash
mid-write (file precedente intatto), robustezza sotto scritture
concorrenti (il file non e' mai osservabile corrotto).
"""
import json
import threading

import pytest

import community_store


def test_roundtrip_basic(tmp_path):
    p = tmp_path / "store.json"
    data = {"tok1": {"job_id": "J1", "created_at": 123.5},
            "tok2": {"job_id": "J2", "n": None, "unicode": "città 中文"}}
    community_store.atomic_write_json(p, data)
    assert json.loads(p.read_text(encoding="utf-8")) == data
    # Nessun file temporaneo residuo
    assert list(tmp_path.glob("*.tmp")) == []


def test_format_params_preserved(tmp_path):
    """indent/ensure_ascii replicano il formato del writer originale."""
    p = tmp_path / "fmt.json"
    community_store.atomic_write_json(p, {"k": "è"}, ensure_ascii=True, indent=None)
    raw = p.read_text(encoding="utf-8")
    assert "\\u00e8" in raw and "\n" not in raw
    community_store.atomic_write_json(p, {"k": "è"}, ensure_ascii=False, indent=2)
    raw = p.read_text(encoding="utf-8")
    assert "è" in raw and "\n" in raw


def test_creates_parent_dirs(tmp_path):
    p = tmp_path / "sub" / "dir" / "store.json"
    community_store.atomic_write_json(p, {"a": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}


def test_crash_mid_write_keeps_previous_file(tmp_path, monkeypatch):
    """Se la serializzazione fallisce a meta' write, il file precedente
    resta intatto e leggibile (garanzia anti-corruzione)."""
    p = tmp_path / "store.json"
    community_store.atomic_write_json(p, {"stato": "buono"})

    class _Boom:
        """Oggetto non serializzabile che esplode a meta' dump."""

    with pytest.raises(TypeError):
        community_store.atomic_write_json(p, {"a": 1, "b": _Boom()})
    # Il file valido precedente non e' stato toccato
    assert json.loads(p.read_text(encoding="utf-8")) == {"stato": "buono"}


def test_concurrent_writers_never_corrupt(tmp_path):
    """Hammer multi-thread senza lock esterno: last-writer-wins, ma il file
    deve restare SEMPRE un JSON valido e completo (rename atomico)."""
    p = tmp_path / "hammer.json"
    n_threads, n_writes = 6, 30
    errors = []

    def writer(tid):
        try:
            for i in range(n_writes):
                payload = {"tid": tid, "i": i, "fill": "x" * 512}
                community_store.atomic_write_json(p, payload, fsync=False)
        except Exception as e:  # os.replace può collidere solo su Windows edge
            errors.append(e)

    def reader():
        for _ in range(200):
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except json.JSONDecodeError as e:
                    errors.append(e)
                    return
                assert set(data) == {"tid", "i", "fill"}

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
    threads.append(threading.Thread(target=reader))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Su Windows os.replace concorrente sullo stesso target può alzare
    # PermissionError transitoria (in prod ogni store scrive sotto lock):
    # qui pretendiamo solo che il CONTENUTO non risulti mai corrotto.
    assert not [e for e in errors if isinstance(e, json.JSONDecodeError)]
    final = json.loads(p.read_text(encoding="utf-8"))
    assert set(final) == {"tid", "i", "fill"}


def test_google_tts_usage_roundtrip_atomic(tmp_path, monkeypatch):
    """_save_usage di google_tts (contatore budget free-tier) scrive in modo
    atomico e _load_usage rilegge lo stesso stato — nessun .tmp residuo."""
    import google_tts
    monkeypatch.setattr(google_tts, "_usage_file_path",
                        tmp_path / "google_tts_usage.json")
    monkeypatch.setattr(google_tts, "_usage_cache", None)
    data = {"month": google_tts._current_month(), "chars_used": 12345}
    google_tts._save_usage(data)
    monkeypatch.setattr(google_tts, "_usage_cache", None)  # forza rilettura da disco
    loaded = google_tts._load_usage()
    assert loaded == data
    assert list(tmp_path.glob("*.tmp")) == []


def test_jsonstore_write_still_atomic_with_bak(tmp_path):
    """JsonStore (news/feedback) continua a scrivere via primitivo condiviso
    mantenendo il backup .bak."""
    community_store.init(tmp_path)
    store = community_store.JsonStore("unit_test_store.json")
    first = store.add({"msg": "uno"})
    store.add({"msg": "due"})
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert [it["msg"] for it in data["items"]] == ["due", "uno"]
    # Il .bak contiene lo stato precedente all'ultima scrittura
    bak = json.loads(store.bak.read_text(encoding="utf-8"))
    assert [it["msg"] for it in bak["items"]] == ["uno"]
    assert store.get(first["id"])["msg"] == "uno"
