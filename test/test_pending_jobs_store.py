import community_store
import pending_jobs


def _fresh(tmp_path):
    community_store.init(str(tmp_path))
    pending_jobs._store = None  # reset singleton between tests
    pending_jobs.init()


def test_register_then_orphans(tmp_path):
    _fresh(tmp_path)
    pending_jobs.register("J1", "generate", {"voice": "v", "notify_email": "a@x.it"})
    orph = pending_jobs.orphans()
    assert len(orph) == 1
    assert orph[0]["id"] == "J1"
    assert orph[0]["phase"] == "generate"
    assert orph[0]["attempts"] == 0
    assert orph[0]["state"] == "pending"


def test_bump_is_persisted_before_run(tmp_path):
    _fresh(tmp_path)
    pending_jobs.register("J1", "generate", {})
    assert pending_jobs.mark_running_bump("J1") == 1
    assert pending_jobs.mark_running_bump("J1") == 2
    # re-open store from disk: counter survived
    pending_jobs._store = None
    pending_jobs.init()
    assert pending_jobs.orphans()[0]["attempts"] == 2


def test_reset_attempts(tmp_path):
    _fresh(tmp_path)
    pending_jobs.register("J1", "generate", {})
    pending_jobs.mark_running_bump("J1")
    pending_jobs.reset_attempts("J1")
    assert pending_jobs.orphans()[0]["attempts"] == 0


def test_finalize_removes(tmp_path):
    _fresh(tmp_path)
    pending_jobs.register("J1", "generate", {})
    pending_jobs.finalize("J1")
    assert pending_jobs.orphans() == []


def test_mark_failed_excluded_from_orphans(tmp_path):
    _fresh(tmp_path)
    pending_jobs.register("J1", "generate", {})
    pending_jobs.mark_failed("J1")
    assert pending_jobs.orphans() == []


def test_register_same_id_upserts(tmp_path):
    _fresh(tmp_path)
    pending_jobs.register("J1", "generate", {"voice": "v1"})
    pending_jobs.register("J1", "generate", {"voice": "v2"})
    orph = pending_jobs.orphans()
    assert len(orph) == 1
    assert orph[0]["voice"] == "v2"
