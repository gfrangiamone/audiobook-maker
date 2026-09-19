# test/test_job_restore_after_refresh.py
"""Ripresa del job dopo un refresh della pagina.

Caso d'origine (job I7F7xLX5iZVKkfe1RDRJDA, 18/09/2026): l'utente preme F5
durante la generazione, la SPA riparte dal form di upload, lui crede di aver
perso il libro pagato e lo rilancia dall'app. Il job era vivo e ha consegnato
regolarmente: il difetto e' che la pagina non si riaggancia al proprio job.

Il ripristino si appoggia a `/api/my_jobs`, che esisteva gia' per l'app mobile.
Qui si verificano i campi aggiunti per la SPA (`live`, `single_file`,
`total_chapters`, `email_registered`, normalizzazione `partial`->`done`), gli
stessi campi sul ramo "stesso file ricaricato mentre gira" di `/api/analyze`, e
il codice client che li consuma.
"""
import hashlib
import io
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import audiobook_app

CID = "restore-cid-12345"
HDR = {"X-ABM-Cid": CID}


class _FakeInfo:
    """Sostituto di BookInfo: al ripristino servono titolo e n. capitoli."""

    def __init__(self, title, n_chapters):
        self.title = title
        self.chapters = list(range(n_chapters))


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


@pytest.fixture
def seed_job(monkeypatch):
    monkeypatch.setattr(audiobook_app, "_download_tokens", {})
    seeded = []

    def _seed(jid, **fields):
        fields.setdefault("client_id", CID)
        with audiobook_app._jobs_lock:
            audiobook_app.jobs[jid] = fields
        seeded.append(jid)
        return jid

    yield _seed
    with audiobook_app._jobs_lock:
        for jid in seeded:
            audiobook_app.jobs.pop(jid, None)


def _jobs(client):
    r = client.get("/api/my_jobs", headers=HDR)
    assert r.status_code == 200
    return r.get_json()["jobs"]


# ------------------------------------------------------------ /api/my_jobs

def test_running_job_carries_everything_the_page_lost(client, seed_job):
    # Dopo un F5 il client non ha piu' ne' il formato ne' il libro: se il
    # descrittore non li riporta, il pannello finale offrira' i bottoni del
    # formato di default (M4B) anche a un job che produce uno ZIP.
    seed_job("rj1", status="generating", output_format="zip",
             single_file=False, notify_email="u@x.it",
             info=_FakeInfo("Hunting Adeline", 42),
             progress_current=7, progress_total=100,
             start_time=time.time())
    j = _jobs(client)[0]
    assert j["status"] == "generating"
    assert j["live"] is True
    assert j["output_format"] == "zip"
    assert j["single_file"] is False
    assert j["title"] == "Hunting Adeline"
    assert j["total_chapters"] == 42
    assert j["email_registered"] is True


def test_optimizing_job_is_restorable_with_its_char_progress(client, seed_job):
    seed_job("rj2", status="optimizing", output_format="m4b",
             info=_FakeInfo("Libro", 3), opt_processed_chars=1500,
             opt_total_chars=6000, start_time=time.time())
    j = _jobs(client)[0]
    assert j["live"] is True
    assert (j["opt_processed_chars"], j["opt_total_chars"]) == (1500, 6000)


def test_partial_is_presented_as_done(client, seed_job):
    # `partial` e' terminale e gia' consegnato (alcuni chunk saltati): per chi
    # riapre la pagina e' un job pronto al download, non uno stato a se'.
    seed_job("rj3", status="partial", output_format="mp3",
             info=_FakeInfo("Libro parziale", 5), start_time=time.time())
    j = _jobs(client)[0]
    assert j["status"] == "done"
    assert j["live"] is True


def test_single_file_defaults_true_when_the_job_never_recorded_it(
        client, seed_job):
    # Job vecchi / percorsi che non scrivono il flag: il default deve restare
    # quello storico, non un None che il client leggerebbe come "non booleano".
    seed_job("rj4", status="generating", output_format="m4b",
             info=_FakeInfo("Libro", 1), start_time=time.time())
    assert _jobs(client)[0]["single_file"] is True


def test_other_clients_jobs_are_not_restorable(client, seed_job):
    seed_job("rj5", status="generating", client_id="ALTRO-cid-99999",
             info=_FakeInfo("Non mio", 1), start_time=time.time())
    assert _jobs(client) == []


def test_error_job_is_listed_but_not_marked_done(client, seed_job):
    # Il client filtra su optimizing/generating/done: un job in errore resta
    # nella lista (serve all'app mobile) ma non deve travestirsi da completato.
    seed_job("rj6", status="error", output_format="m4b",
             info=_FakeInfo("Fallito", 2), start_time=time.time())
    j = _jobs(client)[0]
    assert j["status"] == "error"


def test_completed_job_known_only_from_its_token_is_not_live(client, seed_job):
    # Senza il job in memoria non c'e' stream SSE a cui riagganciarsi: il
    # descrittore non deve dichiararsi `live`, o la SPA aprirebbe uno stream
    # che risponde 410.
    now = time.time()
    audiobook_app._download_tokens["TOKRESTORE"] = {
        "job_id": "rj7",
        "client_id": CID,
        "created_at": now - 60,
        "book_title": "Solo token",
        "output_format": "m4b",
        "output_m4b": "/x/out.m4b",
        "is_gemini": False,
    }
    j = _jobs(client)[0]
    assert j["status"] == "done"
    assert j.get("live") is not True


def test_live_flag_survives_the_merge_with_the_download_token(
        client, seed_job):
    now = time.time()
    seed_job("rj8", status="done", output_format="m4b", single_file=True,
             info=_FakeInfo("Consegnato", 9), start_time=now - 120)
    audiobook_app._download_tokens["TOKMERGE"] = {
        "job_id": "rj8",
        "client_id": CID,
        "created_at": now - 60,
        "book_title": "Consegnato",
        "output_format": "m4b",
        "output_m4b": "/x/out.m4b",
        "is_gemini": False,
    }
    jobs = _jobs(client)
    assert len(jobs) == 1
    assert jobs[0]["live"] is True
    assert jobs[0]["download_token"] == "TOKMERGE"
    assert jobs[0]["total_chapters"] == 9


def test_newest_job_comes_first(client, seed_job):
    now = time.time()
    seed_job("rjold", status="generating", info=_FakeInfo("Vecchio", 1),
             start_time=now - 3600)
    seed_job("rjnew", status="generating", info=_FakeInfo("Nuovo", 1),
             start_time=now)
    assert [j["job_id"] for j in _jobs(client)][0] == "rjnew"


# ------------------------------------------------------------ /api/analyze

@pytest.fixture
def analyze_env(monkeypatch):
    monkeypatch.setattr(audiobook_app, "_suspend_new_jobs", False,
                        raising=False)
    monkeypatch.setattr(audiobook_app, "_ip_rl_check",
                        lambda *a, **k: (True, 0))


def test_reupload_of_a_running_job_returns_its_parameters(
        client, seed_job, analyze_env):
    # Stesso difetto del refresh, altro ingresso: si ricarica lo stesso file
    # mentre il job gira. Il client si riaggancia allo stream ma costruisce il
    # pannello finale con le proprie variabili, quindi il server deve mandargli
    # i parametri del job.
    payload = b"Testo del libro per il test di riaggancio.\n"
    file_hash = hashlib.md5(payload).hexdigest()
    seed_job("rjrun", status="generating", file_hash=file_hash,
             output_format="zip_rss", single_file=False,
             notify_email="u@x.it", info=_FakeInfo("Libro in corso", 12),
             progress_current=5, progress_total=50, start_time=time.time())
    r = client.post(
        "/api/analyze", headers=HDR,
        data={"epub": (io.BytesIO(payload), "libro.txt")},
        content_type="multipart/form-data")
    assert r.status_code == 200
    d = r.get_json()
    assert d["existing_job_id"] == "rjrun"
    assert d["is_running"] is True
    assert d["output_format"] == "zip_rss"
    assert d["single_file"] is False
    assert d["title"] == "Libro in corso"
    assert d["total_chapters"] == 12
    assert d["email_registered"] is True


# ------------------------------------------------------------ client (app.js)

APP = Path("static/js/app.js").read_text(encoding="utf-8")


def _extract_fn(name):
    marker = "function %s(" % name
    start = APP.find(marker)
    assert start >= 0, "%s non trovata" % name
    depth = 0
    i = APP.index("{", start)
    for j in range(i, len(APP)):
        if APP[j] == "{":
            depth += 1
        elif APP[j] == "}":
            depth -= 1
            if depth == 0:
                return APP[start:j + 1]
    raise AssertionError("parentesi non bilanciate in %s" % name)


def test_init_attempts_the_restore():
    assert "_restoreActiveJob()" in APP, \
        "il ripristino non e' agganciato all'avvio della pagina"


def test_restore_only_follows_jobs_still_in_memory():
    fn = _extract_fn("_restoreActiveJob")
    assert "e.live" in fn, \
        "senza il filtro su `live` la SPA apre uno stream su un job morto"


def test_restore_yields_to_the_user_who_already_started_something():
    # Il fetch e' asincrono: se nel frattempo l'utente ha caricato un file, la
    # sua azione vince, altrimenti il ripristino gli cancella il lavoro.
    fn = _extract_fn("_restoreActiveJob")
    assert "if(generating||jobDone||bookData||jobId)return;" in fn


def test_restore_reuses_the_existing_completion_path():
    # Nessuna seconda implementazione del pannello 5: il primo tick dello
    # stream e' gia' il payload di completamento.
    fn = _extract_fn("_restoreActiveJob")
    assert "listenProgress()" in fn
    assert "_listenOptProgressWiz()" in fn


def test_restore_unlocks_the_step_before_navigating_to_it():
    # goToStep rifiuta n > _wizMaxStep+1: senza _unlockStep il ripristino di un
    # job in corso lasciava la pagina al pannello 1 con la barra invisibile.
    fn = _extract_fn("_restoreActiveJob")
    assert fn.index("_unlockStep(4)") < fn.index("goToStep(4)")


def test_default_format_timer_does_not_clobber_the_restored_one():
    for riga in APP.splitlines():
        if "s.value='m4b';onOutputChange()" in riga:
            assert "_jobRestored" in riga, riga.strip()


def test_reupload_branch_uses_the_same_rehydration():
    # Un secondo punto di reidratazione divergerebbe in silenzio.
    assert APP.count("function _rehydrateJobFromServer(") == 1
    assert APP.count("_rehydrateJobFromServer(") >= 3


def test_restored_session_hides_the_way_back_to_the_chapter_list():
    # Dopo un F5 il client non ha l'elenco dei capitoli: il ritorno alla
    # selezione porterebbe a una pagina vuota.
    assert "!bookData._restored" in APP


def test_reset_clears_the_restore_notice():
    fn = _extract_fn("resetAll")
    assert "restoreNotice" in fn
    assert "_jobRestored=false" in fn


PCT_CASES = [
    ("generazione a meta'",
     {"status": "generating", "progress_current": 50, "progress_total": 200},
     25),
    ("ottimizzazione a meta'",
     {"status": "optimizing", "opt_processed_chars": 3000,
      "opt_total_chars": 6000}, 50),
    ("totale ancora sconosciuto",
     {"status": "generating", "progress_current": 5, "progress_total": 0}, 0),
    ("job completato", {"status": "done"}, 0),
    ("descrittore assente", None, 0),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
def test_restore_entry_pct_behavior(tmp_path):
    src = _extract_fn("_restoreEntryPct")
    script = tmp_path / "pct.js"
    script.write_text(
        src
        + "\nconst CASES=" + json.dumps([c for _d, c, _e in PCT_CASES]) + ";"
        + "\nconsole.log(JSON.stringify(CASES.map(_restoreEntryPct)));",
        encoding="utf-8")
    res = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    got = json.loads(res.stdout.strip())
    expected = [e for _d, _c, e in PCT_CASES]
    labels = [d for d, _c, _e in PCT_CASES]
    assert got == expected, "mismatch: %s" % list(zip(labels, got, expected))


# ------------------------------------------------------------ i18n

I18N = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("lang", ["it", "en", "fr", "es", "de", "zh", "hi"])
@pytest.mark.parametrize("key", ["restore_running", "restore_done",
                                 "restore_other", "restore_new"])
def test_restore_strings_exist_in_every_language(lang, key):
    start = I18N.find("\n%s:{" % lang)
    assert start >= 0, "blocco %s non trovato" % lang
    end = I18N.find("\n", start + 1)
    blocco = I18N[start:end if end > 0 else len(I18N)]
    assert "%s:" % key in blocco, "%s manca in %s" % (key, lang)
