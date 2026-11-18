"""/api/download con il job uscito dalla memoria deve ripiegare sul download
token del chiamante.

Job 1h57HgHR (18/11/2026): restart 80 s dopo il COMPLETE. La pagina di
completamento rimasta aperta chiedeva /api/download/<job>?type=m4b, il job non
era piu' in `jobs` e la SPA diceva "File non piu' disponibile. Riconverti il
libro", mentre l'area personale scaricava lo stesso M4B via /dl/<token>."""
import time

import pytest

import token_store as _tkstore

CID = "cidOwner1234"


@pytest.fixture
def app_env(fresh_app, tmp_path):
    audiobook_app = fresh_app(env={"ABM_DATA_DIR": str(tmp_path / "data")})
    audiobook_app.app.config["TESTING"] = True
    added = []
    yield audiobook_app, tmp_path, added
    for tok in added:
        _tkstore.download_tokens.pop(tok, None)


def _token(added, tok, job_id, m4b="", **fields):
    rec = {"job_id": job_id, "created_at": time.time(), "download_type": "audio",
           "book_title": "Il Libro", "output_m4b": m4b, "client_id": CID, **fields}
    _tkstore.download_tokens[tok] = rec
    added.append(tok)
    return rec


def _get(audiobook_app, url, cid=CID):
    return audiobook_app.app.test_client().get(
        url, headers={"X-ABM-Cid": cid}, follow_redirects=False)


def test_job_gone_redirects_to_owned_token_and_serves_m4b(app_env):
    audiobook_app, tmp_path, added = app_env
    out = tmp_path / "data" / "jobGone" / "output_1"
    out.mkdir(parents=True)
    m4b = out / "Il_Libro.m4b"
    m4b.write_bytes(b"m4b-bytes")
    _token(added, "tokGone", "jobGone", m4b=str(m4b))
    assert "jobGone" not in audiobook_app.jobs

    resp = _get(audiobook_app, "/api/download/jobGone?type=m4b")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dl/tokGone/m4b")

    served = _get(audiobook_app, "/dl/tokGone/m4b")
    assert served.status_code == 200 and served.data == b"m4b-bytes"


def test_job_gone_untyped_download_goes_to_token_download(app_env):
    audiobook_app, _tmp, added = app_env
    _token(added, "tokZip", "jobZipGone")
    resp = _get(audiobook_app, "/api/download/jobZipGone?type=zip")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dl/tokZip/download")


def test_job_gone_token_of_another_client_stays_404(app_env):
    audiobook_app, _tmp, added = app_env
    _token(added, "tokOther", "jobOther")
    assert _get(audiobook_app, "/api/download/jobOther?type=m4b",
                cid="cidSomeoneElse").status_code == 404


def test_job_gone_expired_or_non_audio_token_stays_404(app_env):
    audiobook_app, _tmp, added = app_env
    _token(added, "tokOld", "jobOld", created_at=1.0)
    assert _get(audiobook_app, "/api/download/jobOld?type=m4b").status_code == 404
    _token(added, "tokTr", "jobTr", download_type="translated")
    assert _get(audiobook_app, "/api/download/jobTr?type=m4b").status_code == 404
    _token(added, "tokAdm", "jobAdm", admin_copy=True)
    assert _get(audiobook_app, "/api/download/jobAdm?type=m4b").status_code == 404
