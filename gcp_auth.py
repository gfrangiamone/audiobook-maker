"""gcp_auth — credenziali Google service-account con cache e refresh.

Modulo foglia (stdlib; `google-auth` importato solo quando serve). Prima:
lo stesso giro «carica il file, refresh se scaduto o vicino alla scadenza,
tieni il token» in `translation_core.make_client_provider` (Vertex) e in
`push_service._get_credentials` (FCM).

    sa = ServiceAccount(path, ["https://www.googleapis.com/auth/cloud-platform"])
    sa.token()        # bearer valido, rinnovato se manca meno di `margin_sec`
    sa.project_id()   # dal file JSON
"""
import json
import threading
from datetime import datetime, timezone


class ServiceAccount:
    def __init__(self, creds_file, scopes, *, margin_sec=300):
        self.creds_file = creds_file
        self.scopes = list(scopes)
        self.margin_sec = margin_sec
        self._creds = None
        self._project_id = ""
        self._lock = threading.Lock()

    def project_id(self):
        """`project_id` del file di credenziali (letto una volta)."""
        if not self._project_id:
            with open(self.creds_file, "r", encoding="utf-8") as f:
                self._project_id = json.load(f).get("project_id", "")
        return self._project_id

    def _near_expiry(self):
        expiry = getattr(self._creds, "expiry", None)
        if expiry is None:
            return False
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return (expiry - now).total_seconds() < self.margin_sec

    def credentials(self, *, force_refresh=False):
        """Credenziali google-auth valide. Le eccezioni (file assente, rete)
        passano al chiamante."""
        from google.auth.transport.requests import Request as _GAuthRequest
        from google.oauth2 import service_account
        with self._lock:
            if self._creds is None:
                self._creds = service_account.Credentials.from_service_account_file(
                    self.creds_file, scopes=self.scopes)
            if force_refresh or not self._creds.valid or self._near_expiry():
                self._creds.refresh(_GAuthRequest())
            return self._creds

    def token(self, *, force_refresh=False):
        return self.credentials(force_refresh=force_refresh).token
