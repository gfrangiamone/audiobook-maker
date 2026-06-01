#!/usr/bin/env python3
"""Verifica manuale connettività + S3-compatibility del cold storage (Cloudflare R2 o altro).

Esercita il modulo reale `storage_backend` contro il bucket configurato:
  1. is_enabled()            -> credenziali presenti
  2. upload_file (~10 MB)    -> forza il MULTIPLART upload (soglia boto3 ~8 MB)
  3. object_exists           -> True dopo upload
  4. presigned_get_url       -> con download_name accentato (test RFC 6266)
  5. GET del presigned URL   -> 200 + byte identici + Content-Disposition
  6. delete_object           -> rimozione
  7. object_exists           -> False dopo delete

I segreti NON vanno messi qui né in chat: crea un file `.env.r2` nella root del
repo (è gitignored via `.env*`) con queste righe (valori tuoi):

    ABM_S3_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
    ABM_S3_ACCESS_KEY=<access key id>
    ABM_S3_SECRET_KEY=<secret access key>
    ABM_S3_BUCKET=<nome bucket>
    ABM_S3_REGION=auto

Poi esegui:  python scripts/verify_r2.py
"""
import os
import sys
import hashlib
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """Carica KEY=VALUE da un file .env semplice in os.environ (no dipendenze)."""
    if not path.exists():
        return False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ[key] = val
    return True


def main():
    # Le credenziali DEVONO essere in env prima di importare storage_backend
    # (legge le costanti S3 al momento dell'import).
    env_file = REPO_ROOT / ".env.r2"
    if _load_env_file(env_file):
        print(f"[info] credenziali caricate da {env_file}")
    else:
        print(f"[info] {env_file} assente: uso le variabili d'ambiente correnti")

    # storage_backend è nella root del repo
    sys.path.insert(0, str(REPO_ROOT))
    import storage_backend

    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and bool(cond)
        return bool(cond)

    print("\n== 1. is_enabled ==")
    if not check("credenziali S3 presenti (endpoint/key/secret/bucket)", storage_backend.is_enabled()):
        print("\nAbort: configura .env.r2 o le env ABM_S3_*.")
        sys.exit(1)

    # Intercetta placeholder non sostituiti (es. "<nome bucket>") prima di
    # chiamare S3 con valori palesemente segnaposto.
    _placeholders = [k for k in ("ABM_S3_ENDPOINT", "ABM_S3_ACCESS_KEY",
                                 "ABM_S3_SECRET_KEY", "ABM_S3_BUCKET")
                     if "<" in os.environ.get(k, "") or ">" in os.environ.get(k, "")]
    if _placeholders:
        print(f"\nAbort: valori segnaposto non sostituiti in .env.r2: {', '.join(_placeholders)}")
        sys.exit(1)

    key = "abm-verify/test-multipart.bin"
    payload = os.urandom(10 * 1024 * 1024)  # 10 MB -> innesca multipart
    digest = hashlib.sha256(payload).hexdigest()
    tmp = REPO_ROOT / "_r2_verify_tmp.bin"
    tmp.write_bytes(payload)

    try:
        print("\n== 2. upload_file (~10 MB, multipart) ==")
        try:
            storage_backend.upload_file(str(tmp), key)
            check("upload completato senza eccezioni", True)
        except Exception as e:
            check(f"upload fallito: {e}", False)

        print("\n== 3. object_exists (post-upload) ==")
        check("oggetto presente su S3", storage_backend.object_exists(key))

        print("\n== 4. presigned_get_url (nome accentato) ==")
        url = None
        try:
            url = storage_backend.presigned_get_url(key, download_name="Tèst Bòòk àccénti.m4b", ttl=300)
            check("URL presigned generato", bool(url and url.startswith("http")))
        except Exception as e:
            check(f"generazione presigned fallita: {e}", False)

        print("\n== 5. GET del presigned URL ==")
        if url:
            try:
                with urllib.request.urlopen(url, timeout=60) as resp:
                    body = resp.read()
                    status = resp.status
                    cdisp = resp.headers.get("Content-Disposition", "")
                check(f"HTTP 200 (ricevuto {status})", status == 200)
                check("byte scaricati identici (sha256)", hashlib.sha256(body).hexdigest() == digest)
                check(f"Content-Disposition presente [{cdisp[:60]}...]", "attachment" in cdisp.lower())
            except Exception as e:
                check(f"fetch presigned fallito: {e}", False)
        else:
            check("skip GET (nessun URL)", False)

        print("\n== 6. delete_object ==")
        try:
            storage_backend.delete_object(key)
            check("delete senza eccezioni", True)
        except Exception as e:
            check(f"delete fallito: {e}", False)

        print("\n== 7. object_exists (post-delete) ==")
        check("oggetto rimosso", not storage_backend.object_exists(key))

    finally:
        try:
            tmp.unlink()
        except OSError:
            pass

    print("\n" + ("=" * 50))
    print("RISULTATO:", "TUTTO OK" if ok else "ALCUNI STEP FALLITI")
    print("=" * 50)
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
