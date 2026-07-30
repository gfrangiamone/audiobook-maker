"""Capture PayPal rifiutata: diagnostica (issue + debug_id) e recovery UI.

Caso reale: ordine 36M6852033504281N (2026-07). Un utente con account PayPal
indiano e carta Visa ha ricevuto `422 Client Error: Unprocessable Entity` alla
capture. Il body della risposta PayPal — che contiene l'`issue` vero
(INSTRUMENT_DECLINED, TRANSACTION_REFUSED, ...) — veniva scartato da
`raise_for_status()`, quindi in log restava solo "HTTP 422" e la causa non era
ricostruibile.

Copre:
  - `_paypal_capture_order` solleva `PayPalCaptureRefusedError` con issue,
    debug_id e status_code estratti dalla risposta.
  - `_paypal_error_details` tollera body non-JSON.
  - il frontend riavvia il checkout (`actions.restart`) su INSTRUMENT_DECLINED.
  - la chiave i18n `pay_paypal_declined` esiste in tutte le lingue.
"""
from pathlib import Path
import re

import pytest

import payment


class _FakeResponse:
    def __init__(self, status_code, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text else ("" if payload is None else str(payload))
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


_DECLINED_BODY = {
    "name": "UNPROCESSABLE_ENTITY",
    "message": "The requested action could not be performed.",
    "details": [{
        "issue": "INSTRUMENT_DECLINED",
        "description": "The instrument presented was either declined by the "
                       "processor or bank, or it can't be used for this payment.",
    }],
}


def _patch_capture(monkeypatch, response):
    monkeypatch.setattr(payment, "_paypal_get_access_token", lambda: "tok")
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: response)


def test_capture_refused_exposes_issue_and_debug_id(monkeypatch, capsys):
    _patch_capture(monkeypatch, _FakeResponse(
        422, _DECLINED_BODY, text='{"name":"UNPROCESSABLE_ENTITY"}',
        headers={"PayPal-Debug-Id": "d3adb33f01"}))

    with pytest.raises(payment.PayPalCaptureRefusedError) as ei:
        payment._paypal_capture_order("36M6852033504281N")

    err = ei.value
    assert err.issue == "INSTRUMENT_DECLINED"
    assert err.name == "UNPROCESSABLE_ENTITY"
    assert err.debug_id == "d3adb33f01"
    assert err.status_code == 422
    assert "INSTRUMENT_DECLINED" in str(err)
    # e' una ValueError: gli handler generici esistenti continuano a coprirla
    assert isinstance(err, ValueError)
    # il body finisce in log (senza di esso il 422 e' cieco)
    out = capsys.readouterr().out
    assert "capture refused" in out
    assert "36M6852033504281N" in out
    assert "d3adb33f01" in out


def test_capture_refused_non_json_body(monkeypatch):
    _patch_capture(monkeypatch, _FakeResponse(500, None, text="<html>oops</html>"))

    with pytest.raises(payment.PayPalCaptureRefusedError) as ei:
        payment._paypal_capture_order("ORD-X")

    assert ei.value.issue == ""
    assert ei.value.status_code == 500
    assert "HTTP 500" in str(ei.value)


def test_capture_ok_returns_payload(monkeypatch):
    payload = {"id": "ORD-OK", "status": "COMPLETED"}
    _patch_capture(monkeypatch, _FakeResponse(201, payload))
    assert payment._paypal_capture_order("ORD-OK") == payload


def test_frontend_restarts_checkout_on_instrument_declined():
    js = Path("static/js/app.js").read_text(encoding="utf-8")
    assert "onApprove:async function(data,actions)" in js
    assert "INSTRUMENT_DECLINED" in js
    assert "actions.restart()" in js
    # il restart deve precedere il messaggio di errore terminale
    idx_restart = js.index("actions.restart()")
    idx_fail = js.index("pay_paypal_capture_failed")
    assert idx_restart < idx_fail


def test_declined_i18n_key_in_all_languages():
    text = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
    found = re.findall(r'pay_paypal_declined:"([^"]+)"', text)
    assert len(found) == 7, f"expected 7 languages, found {len(found)}"
    assert all(v.strip() for v in found)
