"""Unit test per storage_backend: tutte le primitive S3 con fake client."""
import importlib
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
