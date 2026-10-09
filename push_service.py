"""push_service.py — Notifiche push FCM (HTTP v1) per l'app mobile.

Pattern email_service: configurazione da env, nessun import di audiobook_app.
Disabilitato se ABM_FCM_CREDENTIALS_FILE non e' impostata. I fallimenti non
sono mai bloccanti: send_push ritorna 'ok' | 'unregistered' | 'error'.
"""
from gcp_auth import ServiceAccount
import os
import threading
import time

import requests

_FCM_CREDENTIALS_FILE = os.environ.get("ABM_FCM_CREDENTIALS_FILE", "")
_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_SEND_RETRIES = 3

_creds = None
_project_id = ""
_creds_lock = threading.Lock()


def is_available():
    """True se le credenziali FCM sono configurate e il file esiste."""
    return bool(_FCM_CREDENTIALS_FILE) and os.path.isfile(_FCM_CREDENTIALS_FILE)


def _sa():
    """Service account FCM (cache e refresh in gcp_auth), creato alla prima
    chiamata cosi' il file manca solo quando serve davvero."""
    global _creds
    with _creds_lock:
        if _creds is None:
            _creds = ServiceAccount(_FCM_CREDENTIALS_FILE, [_FCM_SCOPE])
        return _creds


def _load_project_id():
    return _sa().project_id()


def _get_credentials():
    """Credenziali google-auth con cache e refresh. Caller gestisce le eccezioni."""
    return _sa().credentials()


def send_push(fcm_token, title, body, data=None):
    """Invia una notifica a un singolo device. Mai eccezioni verso il caller.

    Ritorna: 'ok' | 'unregistered' (token da rimuovere, solo 404) | 'error'.
    400 e' un errore deterministico di payload: nessun retry, niente purge del token.
    """
    if not is_available():
        return "error"
    try:
        creds = _get_credentials()
        project_id = _load_project_id()
    except Exception as e:
        print(f"[push] FCM auth failed: {e}", flush=True)
        return "error"
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    payload = {
        "message": {
            "token": fcm_token,
            "notification": {"title": title, "body": body},
            "data": {str(k): str(v) for k, v in (data or {}).items()},
        }
    }
    headers = {"Authorization": f"Bearer {creds.token}"}
    tok_prefix = fcm_token[:12]
    for attempt in range(_SEND_RETRIES):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
        except Exception as e:
            print(f"[push] FCM request failed (attempt {attempt + 1}): {e}", flush=True)
            if attempt < _SEND_RETRIES - 1:
                time.sleep(2 ** attempt)
            continue
        if resp.status_code == 200:
            return "ok"
        if resp.status_code == 404:
            # Token non registrato: rimuovere dal DB.
            print(f"[push] FCM token unregistered (404) tok={tok_prefix}", flush=True)
            return "unregistered"
        if resp.status_code == 400:
            # Payload deterministicamente invalido: nessun retry, NON rimuovere il token.
            print(f"[push] FCM bad request (400) tok={tok_prefix}: "
                  f"{resp.text[:200]}", flush=True)
            return "error"
        print(f"[push] FCM error {resp.status_code} (attempt {attempt + 1}) "
              f"tok={tok_prefix}: {resp.text[:200]}", flush=True)
        if attempt < _SEND_RETRIES - 1:
            time.sleep(2 ** attempt)
    return "error"
