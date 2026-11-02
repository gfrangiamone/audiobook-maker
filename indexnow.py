"""indexnow.py — notifica IndexNow (Bing, Yandex, Seznam, Naver) degli URL
della sitemap cambiati dall'ultimo invio.

Protocollo: https://www.indexnow.org/documentation. La chiave
(`ABM_INDEXNOW_KEY`, vuota = spento) e' pubblica per costruzione: il motore la
verifica scaricando `<base>/<chiave>.txt`, servito da `routes_pages`.

Al boot un thread aspetta `_BOOT_DELAY_SEC` (il deploy verifica /healthz per
60 s e fa rollback se fallisce: si notifica solo una versione rimasta su),
legge la sitemap e invia in un solo POST gli URL il cui `lastmod` differisce
da quello dell'ultimo invio riuscito. `lastmod` ha la grana del giorno, quindi
un URL parte al massimo una volta al giorno anche con piu' deploy.

Stato: `<data dir>/_indexnow_sent.json` = {url: lastmod inviato}; contiene
solo gli URL della sitemap corrente (retention = la sitemap stessa).
"""

import re
import threading
import time
from urllib.parse import urlparse

import requests

import retry_util
from env_utils import env_str
from fileio import data_path
from monthly_ledger import JsonDoc

ENDPOINT = "https://api.indexnow.org/indexnow"
_BOOT_DELAY_SEC = 120
_ATTEMPTS = 3
_TIMEOUT_SEC = 20
_KEY_RE = re.compile(r"[A-Za-z0-9-]{8,128}")
_ENTRY_RE = re.compile(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

_DOC = JsonDoc(lambda: data_path("_indexnow_sent.json"))
_warned_bad_key = False


class _HttpStatus(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status = status


def key() -> str:
    """Chiave IndexNow valida (8-128 fra lettere, cifre e '-'), '' se spento."""
    global _warned_bad_key
    k = env_str("ABM_INDEXNOW_KEY", "").strip()
    if not k:
        return ""
    if not _KEY_RE.fullmatch(k):
        if not _warned_bad_key:
            _warned_bad_key = True
            print("[indexnow] ABM_INDEXNOW_KEY non valida (8-128 caratteri a-z A-Z 0-9 -): spento",
                  flush=True)
        return ""
    return k


def is_public_base(base_url: str) -> bool:
    """Solo un https pubblico: in locale e in CI (http://localhost) non si invia nulla."""
    u = urlparse(base_url or "")
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host:
        return False
    return host not in _LOCAL_HOSTS and not host.endswith((".localhost", ".test"))


def sitemap_entries(xml: str) -> dict:
    """{url: lastmod} dalla sitemap (le `xhtml:link` alternate non contano)."""
    return {loc.strip(): lm.strip() for loc, lm in _ENTRY_RE.findall(xml or "")}


def changed_urls(entries: dict, sent: dict) -> list:
    return sorted(u for u, lm in entries.items() if sent.get(u) != lm)


def submit(urls, base_url: str, k: str, *, post=None, sleep=time.sleep) -> int:
    """POST unico a IndexNow; 429/5xx ritentati. Ritorna lo status finale
    (200/202 = accettato) o solleva sull'ultimo errore di rete."""
    post = post or requests.post
    base = base_url.rstrip("/")
    payload = {"host": urlparse(base).hostname, "key": k,
               "keyLocation": f"{base}/{k}.txt", "urlList": list(urls)}

    def _once(_attempt):
        resp = post(ENDPOINT, json=payload, timeout=_TIMEOUT_SEC,
                    headers={"Content-Type": "application/json; charset=utf-8"})
        if retry_util.is_transient_http(resp.status_code):
            raise _HttpStatus(resp.status_code)
        return resp.status_code

    def _retryable(exc):
        return not isinstance(exc, _HttpStatus) or retry_util.is_transient_http(exc.status)

    try:
        return retry_util.retry_call(_once, attempts=_ATTEMPTS, is_retryable=_retryable,
                                     wait=5.0, sleep=sleep)
    except _HttpStatus as e:
        return e.status


def sync(sitemap_fn, base_url_fn, *, post=None, sleep=time.sleep) -> int:
    """Invia gli URL cambiati; ritorna quanti ne sono stati accettati."""
    k = key()
    base = base_url_fn() or ""
    if not k or not is_public_base(base):
        return 0
    entries = sitemap_entries(sitemap_fn() or "")
    if not entries:
        return 0
    urls = changed_urls(entries, _DOC.read())
    if not urls:
        print("[indexnow] nessun URL cambiato", flush=True)
        return 0
    status = submit(urls, base, k, post=post, sleep=sleep)
    if status not in (200, 202):
        print(f"[indexnow] invio di {len(urls)} URL rifiutato: HTTP {status}", flush=True)
        return 0
    with _DOC.mutate() as d:
        d.clear()
        d.update(entries)
    print(f"[indexnow] {len(urls)} URL notificati (HTTP {status})", flush=True)
    return len(urls)


def _run(sitemap_fn, base_url_fn):
    time.sleep(_BOOT_DELAY_SEC)
    try:
        sync(sitemap_fn, base_url_fn)
    except Exception as e:  # noqa: BLE001 - mai far cadere il processo per un ping SEO
        print(f"[indexnow] invio fallito: {e}", flush=True)


def start(sitemap_fn, base_url_fn):
    """Thread daemon di boot; non parte senza chiave o senza base https pubblica."""
    if not key() or not is_public_base(base_url_fn() or ""):
        return None
    t = threading.Thread(target=_run, args=(sitemap_fn, base_url_fn), daemon=True,
                         name="indexnow")
    t.start()
    return t
