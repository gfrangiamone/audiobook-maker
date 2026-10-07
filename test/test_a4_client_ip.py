"""Blocco A4: un solo client_ip(), basato su request.remote_addr.

nginx fa append su X-Forwarded-For e non ha trusted proxy a monte: il primo
elemento dell'header e' scritto dal client. ProxyFix(x_for=1) mette in
remote_addr l'ultimo hop, l'unico fidato. Leggere l'header a mano (come
facevano quattro punti del modulo) permetteva di scegliersi l'IP e con esso
di aggirare rate limit, limiti voucher e dossier abuso.
"""
import re

import audiobook_app


def test_client_ip_ignores_forwarded_header_in_request_context():
    app = audiobook_app.app
    with app.test_request_context(
            "/", headers={"X-Forwarded-For": "6.6.6.6, 7.7.7.7"},
            environ_base={"REMOTE_ADDR": "10.0.0.9"}):
        assert audiobook_app.client_ip() == "10.0.0.9"
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": ""}):
        assert audiobook_app.client_ip() == ""


def test_proxyfix_trusts_exactly_one_hop():
    wsgi = audiobook_app.app.wsgi_app
    assert type(wsgi).__name__ == "ProxyFix"
    assert wsgi.x_for == 1


def test_proxyfix_resolves_last_hop_end_to_end():
    """Attraverso il WSGI completo: con due hop nell'header, remote_addr e'
    l'ULTIMO (quello aggiunto da nginx), non il primo (scritto dal client)."""
    seen = {}

    @audiobook_app.app.route("/__a4_ip_probe")
    def _probe():  # pragma: no cover - route di solo test
        seen["ip"] = audiobook_app.client_ip()
        return "ok"

    c = audiobook_app.app.test_client()
    r = c.get("/__a4_ip_probe", headers={"X-Forwarded-For": "6.6.6.6, 7.7.7.7"},
              environ_base={"REMOTE_ADDR": "10.0.0.9"})
    assert r.status_code == 200
    assert seen["ip"] == "7.7.7.7"


def test_no_manual_forwarded_for_reads_left():
    src = open(audiobook_app.__file__, encoding="utf-8").read()
    reads = [m.start() for m in re.finditer(r'headers\.get\("X-Forwarded-For"', src)]
    assert reads == [], "X-Forwarded-For va letto solo da ProxyFix"
    assert not re.search(r"def _get_client_ip\b|def _client_ip\b", src)
