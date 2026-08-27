"""Adapter Cloudflare: decodifica dell'audio e mappatura degli errori."""
import base64
import json

import pytest

from gemini_transport import TransportError, _interpret_cloudflare_response


class _Resp:
    """Doppio minimale di requests.Response."""

    def __init__(self, status_code, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("corpo non JSON")
        return self._payload


def _ok(pcm=b"\x01\x02\x03"):
    b64 = base64.b64encode(pcm).decode("ascii")
    return _Resp(200, {"result": {"audio": f"data:audio/l16;base64,{b64}"},
                       "success": True})


def test_decodes_the_data_uri_into_raw_pcm():
    out = _interpret_cloudflare_response(_ok(b"\x00" * 32))
    assert out["pcm"] == b"\x00" * 32


def test_tokens_are_unknown_because_the_api_does_not_return_them():
    out = _interpret_cloudflare_response(_ok())
    assert out["input_tokens"] is None
    assert out["output_tokens"] is None


def test_200_without_audio_is_retryable_but_billed():
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(200, {"result": {}, "success": True}))
    assert ei.value.kind == "retryable"
    assert ei.value.billed is True


def test_400_7003_invalid_value_is_fatal():
    body = {"success": False, "errors": [
        {"code": 7003,
         "message": "Invalid value at voice: Invalid option: expected one of Achernar, Achird"}]}
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(400, body))
    assert ei.value.kind == "fatal"
    assert ei.value.provider_code == 7003
    assert ei.value.billed is False


def test_400_7003_overloaded_is_retryable():
    body = {"success": False,
            "errors": [{"code": 7003, "message": "Model is overloaded"}]}
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(400, body))
    assert ei.value.kind == "retryable"


def test_404_model_not_found_is_fatal():
    # Cloudflare usa il codice 7003 anche qui: e' l'HTTP status a distinguere
    # l'errore di configurazione dall'overload.
    body = {"success": False, "errors": [
        {"code": 7003, "message": "Model not found: google/gemini-2.5-flash-tts"}]}
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(404, body))
    assert ei.value.kind == "fatal"
    assert ei.value.billed is False


def test_422_2017_is_content_rejected():
    body = {"success": False,
            "errors": [{"code": 2017, "message": "content moderation"}]}
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(422, body))
    assert ei.value.kind == "content_rejected"


def test_402_2021_is_backend_down():
    body = {"success": False,
            "errors": [{"code": 2021, "message": "insufficient balance"}]}
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(402, body))
    assert ei.value.kind == "backend_down"


def test_429_is_rate_limited():
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(429, {"success": False, "errors": []}))
    assert ei.value.kind == "rate_limited"


def test_5xx_is_retryable():
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(503, None, text="upstream down"))
    assert ei.value.kind == "retryable"


def test_unparseable_body_does_not_crash():
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(200, None, text="<html>nope"))
    assert ei.value.kind == "retryable"
    assert ei.value.billed is True


def test_missing_credentials_are_fatal(monkeypatch):
    import gemini_transport

    monkeypatch.delenv("ABM_CF_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("ABM_CF_API_TOKEN", raising=False)
    with pytest.raises(TransportError) as ei:
        gemini_transport.cloudflare_call(
            final_text="ciao", voice_name="Kore", model_key="flash31",
            model_id="google/gemini-3.1-flash-tts", timeout_ms=1000,
            temperature=None)
    assert ei.value.kind == "fatal"


def test_the_token_never_appears_in_an_error_message(monkeypatch):
    """L'eccezione finta PORTA il token nel proprio messaggio.

    Con una RequestException innocua ("rete giu'") l'asserzione passava anche
    se l'adapter avesse serializzato `str(e)` senza alcuna redazione: il test
    non mordeva. Qui l'unica ragione per cui il segreto non esce e' che
    l'adapter mette nel messaggio solo `type(e).__name__`.
    """
    import gemini_transport

    secret = "cf-token-che-non-deve-trapelare"
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", secret)

    def _fake_post(url, **kw):
        raise gemini_transport.requests.RequestException(
            f"connessione fallita con header Authorization: Bearer {secret}")

    monkeypatch.setattr(gemini_transport.requests, "post", _fake_post)
    with pytest.raises(TransportError) as ei:
        gemini_transport.cloudflare_call(
            final_text="ciao", voice_name="Kore", model_key="flash31",
            model_id="google/gemini-3.1-flash-tts", timeout_ms=1000,
            temperature=None)
    assert secret in str(ei.value.__cause__)   # la causa lo contiene davvero
    assert secret not in str(ei.value)         # il messaggio redatto no


def test_the_token_never_reaches_a_synthesize_log_or_error(monkeypatch, tmp_path, capsys):
    """Chiusura del sospetto S1: nemmeno i log di retry di synthesize()
    possono stampare l'eccezione grezza del provider.

    `synthesize()` logga e interpola `str(te)` — il messaggio gia' redatto
    dall'adapter — non `te.__cause__`, che e' l'eccezione originale di
    `requests` e potrebbe (dipende dalla libreria, non da noi) portarsi
    dietro l'header Authorization.
    """
    import gemini_tts
    import tts_backend_state as st

    secret = "cf-token-che-non-deve-trapelare"
    st.init(str(tmp_path))
    gemini_tts._BACKEND = {}
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", secret)
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_throttle_rpm", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_rpd_increment", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_synth_max_attempts", lambda: 2)
    monkeypatch.setattr(gemini_tts.time, "sleep", lambda s: None)

    def _cf(**kw):
        try:
            raise RuntimeError(f"Authorization: Bearer {secret}")
        except RuntimeError as e:
            raise TransportError("errore di rete verso Cloudflare: RuntimeError",
                                 kind="retryable") from e

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf)
    try:
        with pytest.raises(RuntimeError) as ei:
            gemini_tts.synthesize("ciao mondo", "gemini:flash31:Kore",
                                  output_path=str(tmp_path / "o.pcm"))
        assert secret not in str(ei.value)
        assert secret not in capsys.readouterr().out
        assert secret not in (st.state("flash31").get("trip_detail") or "")
    finally:
        gemini_tts._BACKEND = {}
        st.reset("flash31")


def test_payload_carries_text_voice_and_temperature(monkeypatch):
    import gemini_transport

    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    seen = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        seen["url"] = url
        seen["json"] = json
        seen["timeout"] = timeout
        return _ok()

    monkeypatch.setattr(gemini_transport.requests, "post", _fake_post)
    gemini_transport.cloudflare_call(
        final_text="ciao", voice_name="Zephyr", model_key="flash31",
        model_id="google/gemini-3.1-flash-tts", timeout_ms=45000,
        temperature=0.75)

    assert "acc" in seen["url"]
    # Il campo si chiama "text", non "prompt": verificato sul banco.
    assert seen["json"]["input"]["text"] == "ciao"
    assert seen["json"]["input"]["voice"] == "Zephyr"
    assert seen["json"]["input"]["temperature"] == 0.75
    assert seen["json"]["model"] == "google/gemini-3.1-flash-tts"
    assert seen["timeout"] == 45.0


def test_malformed_base64_is_retryable_and_billed():
    # Un payload base64 con caratteri non-validi (con validate=True) deve
    # solleva TransportError, non restituire PCM troncato/corrotto in silenzio.
    # Incidenti passati nel progetto: audio troncato consegnato come completo.
    b64_good = base64.b64encode(b"\x00" * 32).decode("ascii")
    b64_bad = b64_good[:20] + "~~~!!!" + b64_good[26:]
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(
            200, {"result": {"audio": f"data:audio/l16;base64,{b64_bad}"},
                  "success": True}))
    assert ei.value.kind == "retryable"
    assert ei.value.billed is True


def test_invalid_temperature_is_fatal(monkeypatch):
    import gemini_transport

    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")

    def _fake_post(url, **kw):
        return _ok()

    monkeypatch.setattr(gemini_transport.requests, "post", _fake_post)
    # Temperature non convertibile: il contratto dichiara che solo
    # TransportError esce dal trasporto.
    with pytest.raises(TransportError) as ei:
        gemini_transport.cloudflare_call(
            final_text="ciao", voice_name="Kore", model_key="flash31",
            model_id="google/gemini-3.1-flash-tts", timeout_ms=1000,
            temperature="not-a-number")
    assert ei.value.kind == "fatal"


# ---------------------------------------------------------------------------
# Robustezza del parsing della risposta d'errore (rilievo M1 della review
# finale). Un adapter di trasporto ha UN solo modo di fallire: TransportError
# con un kind dell'enum. Qualunque forma rimandi il server — o un proxy
# davanti al server — non puo' far uscire altro. Prima del fix un `errors`
# oggetto invece che array produceva un `KeyError: 0` grezzo, che il
# chiamante non intercetta e che nei log sostituisce la causa vera.
# ---------------------------------------------------------------------------

_MALFORMED_BODIES = [
    pytest.param({"errors": {"code": 2021, "message": "credito finito"}},
                 id="errors-oggetto"),
    pytest.param({"errors": {"0": {"code": 7003, "message": "boom"}}},
                 id="errors-mappa-indicizzata"),
    pytest.param({"errors": "qualcosa e' andato storto"}, id="errors-stringa"),
    pytest.param({"errors": None}, id="errors-null"),
    pytest.param({"errors": []}, id="errors-array-vuoto"),
    pytest.param({"errors": [None]}, id="errors-array-di-null"),
    pytest.param({"errors": ["stringa nuda"]}, id="errors-array-di-stringhe"),
    pytest.param({"errors": 42}, id="errors-numero"),
    pytest.param({"success": False}, id="errors-assente"),
    pytest.param({"code": 2017, "message": "moderazione"}, id="code-al-primo-livello"),
    pytest.param({"error": {"code": 7003, "message": "boom"}}, id="chiave-error-singolare"),
    pytest.param(["lista", "invece", "di", "oggetto"], id="body-lista"),
    pytest.param("errore in testo semplice", id="body-stringa"),
    pytest.param(None, id="body-json-non-parsabile"),
]


@pytest.mark.parametrize("payload", _MALFORMED_BODIES)
@pytest.mark.parametrize("status", [400, 402, 404, 422, 429, 500, 503])
def test_any_error_body_shape_still_produces_a_transport_error(payload, status):
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(status, payload))
    from gemini_transport import TRANSPORT_KINDS
    assert ei.value.kind in TRANSPORT_KINDS


def test_an_empty_body_still_produces_a_transport_error():
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(500, None, text=""))
    assert ei.value.kind == "retryable"


def test_a_numeric_string_code_is_still_classified():
    """Un proxy che rimanda i codici come stringa non deve disarmare il
    breaker: "2021" e' credito esaurito esattamente come 2021."""
    body = {"errors": [{"code": "2021", "message": "out of credits"}]}
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(500, body))
    assert ei.value.kind == "backend_down"
    assert ei.value.provider_code == 2021


def test_the_error_message_is_never_lost():
    """La forma inattesa non deve costare la diagnosi."""
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(
            _Resp(500, {"errors": {"code": 1234, "message": "dettaglio utile"}}))
    assert "dettaglio utile" in str(ei.value)
    assert ei.value.provider_code == 1234


def test_a_non_string_audio_field_is_not_an_attribute_error():
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(
            _Resp(200, {"result": {"audio": {"inatteso": True}}}))
    assert ei.value.kind == "retryable"
    assert ei.value.billed is True


def test_a_non_dict_result_is_not_an_attribute_error():
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(200, {"result": ["lista"]}))
    assert ei.value.kind == "retryable"


def test_a_json_decoder_that_explodes_does_not_escape(monkeypatch):
    class _Exploding(_Resp):
        def json(self):
            raise KeyError("decoder proprietario")

    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Exploding(503, None, text="giu'"))
    assert ei.value.kind == "retryable"


def test_the_adapter_never_lets_a_foreign_exception_escape(monkeypatch):
    """Rete di sicurezza del contratto: se l'interpretazione sollevasse
    comunque qualcosa di estraneo, cloudflare_call lo riconfeziona."""
    import gemini_transport

    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    monkeypatch.setattr(gemini_transport.requests, "post",
                        lambda url, **kw: _Resp(200, {"result": {}}))
    monkeypatch.setattr(gemini_transport, "_interpret_cloudflare_response",
                        lambda resp: (_ for _ in ()).throw(KeyError(0)))

    with pytest.raises(TransportError) as ei:
        gemini_transport.cloudflare_call(
            final_text="ciao", voice_name="Kore", model_key="flash31",
            model_id="google/gemini-3.1-flash-tts", timeout_ms=1000,
            temperature=None)
    assert ei.value.kind == "retryable"
    assert "KeyError" in str(ei.value)
