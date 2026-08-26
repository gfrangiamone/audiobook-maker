"""Verifica se Cloudflare espone via API il saldo del credito AI Gateway.

Non stampa mai il token. Nessuna chiamata di inferenza: solo endpoint di
lettura, quindi nessun addebito.

Uso:
    $env:CF_ACCOUNT_ID = "..."; $env:CF_API_TOKEN = "..."
    python scripts/cf_credit_probe.py
"""
import json
import os
import sys

import requests

ACCOUNT = os.environ.get("CF_ACCOUNT_ID", "").strip()
TOKEN = os.environ.get("CF_API_TOKEN", "").strip()
if not ACCOUNT or not TOKEN:
    sys.exit("CF_ACCOUNT_ID / CF_API_TOKEN assenti nell'ambiente")

BASE = "https://api.cloudflare.com/client/v4"
CANDIDATES = [
    f"/accounts/{ACCOUNT}/ai-gateway/credits",
    f"/accounts/{ACCOUNT}/ai/credits",
    f"/accounts/{ACCOUNT}/billing/profile",
    f"/accounts/{ACCOUNT}/ai-gateway/gateways",
]

session = requests.Session()
session.headers["Authorization"] = f"Bearer {TOKEN}"

for path in CANDIDATES:
    try:
        r = session.get(BASE + path, timeout=30)
    except requests.RequestException as e:
        print(f"{path}: errore di rete ({type(e).__name__})")
        continue
    print(f"\n=== {path} -> HTTP {r.status_code}")
    try:
        body = r.json()
    except ValueError:
        print(r.text[:400])
        continue
    # Stampa compatta: cerchiamo chiavi che somiglino a un saldo.
    print(json.dumps(body, indent=2)[:1500])
