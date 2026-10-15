"""Email immediata all'admin allo switch di backend TTS."""
import pytest

import email_service


@pytest.fixture
def _sent(monkeypatch):
    box = []
    monkeypatch.setattr(email_service, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)
    monkeypatch.setattr(
        email_service, "_send_email",
        lambda to, subject, html, **kw: box.append((to, subject, html)) or True)
    return box


def test_the_email_goes_to_the_admin(_sent):
    email_service.admin_notify_tts_backend_switch(
        "flash31", "cf_backend_down", "HTTP 402 code 2021", "job-1")
    assert len(_sent) == 1
    assert _sent[0][0] == "admin@example.com"


def test_the_subject_names_the_switch(_sent):
    email_service.admin_notify_tts_backend_switch(
        "flash31", "cf_backend_down", "HTTP 402 code 2021", "job-1")
    subject = _sent[0][1]
    assert "flash31" in subject
    assert "Vertex" in subject


def test_the_subject_uses_the_mapped_label_not_the_raw_reason(_sent):
    # Rilievo 4: "cf_backend_down" contiene gia' la sottostringa "backend",
    # quindi un assert generico su "backend" in subject passerebbe anche
    # cancellando il dict `reason_label` e usando la reason grezza. Con
    # "cf_consecutive_failures" (che non condivide sottostringhe con la sua
    # label) il test morde solo se la mappatura e' davvero applicata.
    email_service.admin_notify_tts_backend_switch(
        "flash31", "cf_consecutive_failures", "d", "j")
    subject = _sent[0][1]
    assert "fallimenti consecutivi oltre soglia" in subject
    assert "cf_consecutive_failures" not in subject


def test_the_body_carries_cause_job_and_margin_warning(_sent):
    email_service.admin_notify_tts_backend_switch(
        "flash31", "cf_backend_down", "HTTP 402 code 2021", "job-42")
    html = _sent[0][2]
    assert "HTTP 402 code 2021" in html
    assert "job-42" in html
    # Il testo deve dire perche' e' urgente, non solo che e' successo.
    assert "margine" in html.lower()


def test_the_body_explains_that_the_return_is_manual(_sent):
    email_service.admin_notify_tts_backend_switch(
        "flash31", "cf_backend_down", "d", "j")
    assert "manuale" in _sent[0][2].lower()


def test_the_credit_left_appears_when_known(_sent):
    email_service.admin_notify_tts_backend_switch(
        "flash31", "cf_backend_down", "d", "j", credit_left_usd=1.23)
    assert "1.23" in _sent[0][2] or "1,23" in _sent[0][2]


def test_nothing_is_sent_without_an_admin_address(monkeypatch):
    monkeypatch.setattr(email_service, "ADMIN_EMAIL", "")
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)
    sent = []
    monkeypatch.setattr(email_service, "_send_email",
                        lambda *a, **k: sent.append(a))
    email_service.admin_notify_tts_backend_switch("flash31", "r", "d", "j")
    assert sent == []


def test_nothing_is_sent_when_smtp_is_not_available(monkeypatch):
    # Rilievo 2: senza questo test la guardia `or not _smtp_available()` in
    # admin_notify_tts_backend_switch poteva sparire senza far arrossire
    # nulla, perche' la fixture `_sent` forza sempre _smtp_available a True.
    monkeypatch.setattr(email_service, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(email_service, "_smtp_available", lambda: False)
    sent = []
    monkeypatch.setattr(email_service, "_send_email",
                        lambda *a, **k: sent.append(a))
    email_service.admin_notify_tts_backend_switch(
        "flash31", "cf_backend_down", "d", "j")
    assert sent == []


def test_a_send_failure_does_not_propagate(monkeypatch):
    monkeypatch.setattr(email_service, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)

    def _boom(*a, **k):
        raise RuntimeError("SMTP giu'")

    monkeypatch.setattr(email_service, "_send_email", _boom)
    # Il failover e' gia' avvenuto: un guasto SMTP non deve fermare il job.
    email_service.admin_notify_tts_backend_switch("flash31", "r", "d", "j")


def test_openrouter_trip_names_the_real_backends_and_no_cf_credit(_sent):
    # Job 8db7VnSUuZTMnsMJPm_Byg: flash38 cade da OpenRouter su Gemini API.
    email_service.admin_notify_tts_backend_switch(
        "flash38", "or_consecutive_failures", "d", "j", credit_left_usd=31.19,
        probe_first_sec=900, primary="openrouter", fallback="apikey")
    subject, html = _sent[0][1], _sent[0][2]
    assert "Gemini API" in subject and "Vertex" not in subject
    assert "OpenRouter" in html and "Gemini API" in html
    assert "Cloudflare" not in html and "Vertex" not in html
    assert "ABM_CF_CREDIT_BALANCE_USD" not in html
    assert "31.19" not in html


def test_openrouter_return_names_openrouter(_sent):
    email_service.admin_notify_tts_backend_return(
        "flash38", probe_attempts=0, down_seconds=900, credit_left_usd=31.19,
        primary="openrouter", fallback=None)
    subject, html = _sent[0][1], _sent[0][2]
    assert "OpenRouter" in subject
    assert "Cloudflare" not in html and "Vertex" not in html
    assert "sul ripiego" in html
    assert "ABM_CF_CREDIT_BALANCE_USD" not in html
