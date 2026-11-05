"""Unit test per storage_backend: tutte le primitive S3 con fake client."""
import importlib
import io
import os

import pytest


class _FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": str(code)}}


class FakeS3Client:
    """Registra le chiamate; simula head_object 404 per chiavi assenti."""
    def __init__(self):
        self.uploaded = {}      # key -> local_path
        self.deleted = []       # key
        self.existing = set()   # chiavi che esistono
        self.presigned_calls = []

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):
        self.uploaded[Key] = Filename
        self.existing.add(Key)

    def head_object(self, Bucket, Key):
        if Key not in self.existing:
            raise _FakeClientError(404)
        return {"ContentLength": 123}

    def generate_presigned_url(self, op, Params=None, ExpiresIn=None):
        self.presigned_calls.append((op, Params, ExpiresIn))
        return f"https://fake-s3/{Params['Key']}?sig=abc&exp={ExpiresIn}"

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)
        self.existing.discard(Key)

    def get_paginator(self, op):
        client = self
        class _Pag:
            def paginate(self, Bucket, Prefix):
                keys = [k for k in client.existing if k.startswith(Prefix)]
                yield {"Contents": [{"Key": k} for k in keys]} if keys else {}
        return _Pag()

    def delete_objects(self, Bucket, Delete):
        for obj in Delete["Objects"]:
            self.deleted.append(obj["Key"])
            self.existing.discard(obj["Key"])


@pytest.fixture
def sb(monkeypatch):
    monkeypatch.setenv("ABM_S3_ENDPOINT", "https://fake")
    monkeypatch.setenv("ABM_S3_ACCESS_KEY", "ak")
    monkeypatch.setenv("ABM_S3_SECRET_KEY", "sk")
    monkeypatch.setenv("ABM_S3_BUCKET", "bkt")
    import storage_backend
    importlib.reload(storage_backend)
    fake = FakeS3Client()
    monkeypatch.setattr(storage_backend, "_get_client", lambda: fake)
    monkeypatch.setattr(storage_backend, "ClientError", _FakeClientError)
    return storage_backend, fake


def test_is_enabled_true_when_all_env_present(sb):
    storage_backend, _ = sb
    assert storage_backend.is_enabled() is True


def test_is_enabled_false_when_missing(monkeypatch):
    monkeypatch.delenv("ABM_S3_BUCKET", raising=False)
    monkeypatch.setenv("ABM_S3_ENDPOINT", "https://fake")
    monkeypatch.setenv("ABM_S3_ACCESS_KEY", "ak")
    monkeypatch.setenv("ABM_S3_SECRET_KEY", "sk")
    import storage_backend
    importlib.reload(storage_backend)
    assert storage_backend.is_enabled() is False


def test_upload_and_exists(sb, tmp_path):
    storage_backend, fake = sb
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    storage_backend.upload_file(str(f), "job/out/a.mp3")
    assert fake.uploaded["job/out/a.mp3"] == str(f)
    assert storage_backend.object_exists("job/out/a.mp3") is True
    assert storage_backend.object_exists("nope/x.mp3") is False


def test_presigned_url_includes_filename(sb):
    storage_backend, fake = sb
    fake.existing.add("job/out/a.m4b")
    url = storage_backend.presigned_get_url("job/out/a.m4b", download_name="My Book.m4b", ttl=600)
    assert url.startswith("https://fake-s3/job/out/a.m4b")
    op, params, exp = fake.presigned_calls[-1]
    assert op == "get_object"
    assert exp == 600
    assert "My Book.m4b" in params["ResponseContentDisposition"]


def test_delete_object(sb):
    storage_backend, fake = sb
    fake.existing.add("job/out/a.mp3")
    storage_backend.delete_object("job/out/a.mp3")
    assert "job/out/a.mp3" in fake.deleted


def test_delete_prefix_removes_all_under_prefix(sb):
    storage_backend, fake = sb
    fake.existing.update({"job/out/a.mp3", "job/out/b.mp3", "other/c.mp3"})
    storage_backend.delete_prefix("job/")
    assert "job/out/a.mp3" in fake.deleted
    assert "job/out/b.mp3" in fake.deleted
    assert "other/c.mp3" not in fake.deleted


def test_download_file_part_filename_is_unique_per_call(sb, tmp_path):
    storage_backend, fake = sb
    seen = []

    def _download_file(Bucket, Key, Filename):
        seen.append(Filename)
        with open(Filename, "wb") as fh:
            fh.write(b"ok")
    fake.download_file = _download_file
    dest = tmp_path / "a.wav"
    assert storage_backend.download_file("k1", str(dest)) is True
    assert storage_backend.download_file("k2", str(dest)) is True
    assert len(seen) == 2 and seen[0] != seen[1]
    assert all(name.startswith(str(dest) + ".") and name.endswith(".part") for name in seen)
    assert not os.path.exists(seen[0]) and not os.path.exists(seen[1])   # rinominati/ripuliti


def test_download_file_removes_part_on_unexpected_error(sb, tmp_path):
    storage_backend, fake = sb
    catturato = {}

    def _download_file(Bucket, Key, Filename):
        catturato["tmp"] = Filename
        with open(Filename, "wb") as fh:
            fh.write(b"parziale")
        raise RuntimeError("connessione caduta")
    fake.download_file = _download_file
    dest = tmp_path / "b.wav"
    with pytest.raises(RuntimeError):
        storage_backend.download_file("k", str(dest))
    assert not os.path.exists(catturato["tmp"])
    assert not dest.exists()


def test_altro_bucket_senza_prefisso_e_lettura_di_oggetti_piccoli(sb, monkeypatch):
    # Il catalogo gratuito sta in un bucket a parte dello stesso account:
    # stesse credenziali, chiave senza il prefisso del tiering.
    storage_backend, fake = sb
    monkeypatch.setattr(storage_backend, "_KEY_PREFIX", "ns")
    objects = {("catalogo-abm", "catalog/it.json"): b"{}"}

    def get_object(Bucket, Key):
        if (Bucket, Key) not in objects:
            raise _FakeClientError("NoSuchKey")
        return {"Body": io.BytesIO(objects[(Bucket, Key)])}
    fake.get_object = get_object
    assert storage_backend.get_bytes("catalog/it.json", bucket="catalogo-abm") == b"{}"
    assert storage_backend.get_bytes("catalog/de.json", bucket="catalogo-abm") is None
    storage_backend.presigned_get_url("m4b/it/x.m4b", bucket="catalogo-abm")
    assert fake.presigned_calls[-1][1] == {"Bucket": "catalogo-abm", "Key": "m4b/it/x.m4b"}
    storage_backend.presigned_get_url("job/a.m4b")
    assert fake.presigned_calls[-1][1] == {"Bucket": "bkt", "Key": "ns/job/a.m4b"}
