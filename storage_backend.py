"""S3-compatible object storage backend (Aruba / Cloudflare R2 / Backblaze B2 / ...).

Unico punto provider-specifico del tiering. boto3 gestisce multipart upload
automatico (file grandi resumabili) e presigned URL temporanei per il redirect.
Cambiare provider = cambiare le env var ABM_S3_*, nessuna modifica al codice.
"""
import os
import threading
from urllib.parse import quote

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:  # boto3 assente: il backend resta semplicemente disabilitato
    boto3 = None
    Config = None
    ClientError = Exception

_ENDPOINT = os.environ.get("ABM_S3_ENDPOINT", "").strip()
_ACCESS_KEY = os.environ.get("ABM_S3_ACCESS_KEY", "").strip()
_SECRET_KEY = os.environ.get("ABM_S3_SECRET_KEY", "").strip()
_BUCKET = os.environ.get("ABM_S3_BUCKET", "").strip()
_REGION = os.environ.get("ABM_S3_REGION", "us-east-1").strip() or "us-east-1"
_KEY_PREFIX = os.environ.get("ABM_S3_KEY_PREFIX", "").strip().strip("/")
_PRESIGN_TTL = int(os.environ.get("ABM_S3_PRESIGN_TTL_SEC", "21600"))  # 6h default

_client = None
_client_lock = threading.Lock()


def is_enabled():
    """True se boto3 è installato e tutte le credenziali essenziali sono presenti.
    Legge l'ambiente a runtime per non dipendere dal momento dell'import."""
    return bool(
        boto3
        and os.environ.get("ABM_S3_ENDPOINT", "").strip()
        and os.environ.get("ABM_S3_ACCESS_KEY", "").strip()
        and os.environ.get("ABM_S3_SECRET_KEY", "").strip()
        and os.environ.get("ABM_S3_BUCKET", "").strip()
    )


def _full_key(key):
    """Antepone l'eventuale prefisso di namespacing del bucket."""
    k = key.lstrip("/")
    return f"{_KEY_PREFIX}/{k}" if _KEY_PREFIX else k


def _get_client():
    """Client boto3 S3 lazy + cached, thread-safe. signature_version s3v4 per
    compat presigned (upload concorrenti da più thread di offload)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = boto3.client(
                    "s3",
                    endpoint_url=_ENDPOINT,
                    aws_access_key_id=_ACCESS_KEY,
                    aws_secret_access_key=_SECRET_KEY,
                    region_name=_REGION,
                    config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
                )
    return _client


def upload_file(local_path, key):
    """Carica local_path su S3 sotto `key`. boto3 usa multipart automatico
    sopra ~8MB (resumabile, checksum). Solleva su errore."""
    _get_client().upload_file(Filename=str(local_path), Bucket=_BUCKET, Key=_full_key(key))


def object_exists(key):
    """True se l'oggetto esiste (head_object). False su 404."""
    try:
        _get_client().head_object(Bucket=_BUCKET, Key=_full_key(key))
        return True
    except ClientError as e:
        code = str(getattr(e, "response", {}).get("Error", {}).get("Code", ""))
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def object_size(key):
    """Dimensione in byte dell'oggetto su cold (head_object), o None se assente.
    Usato per verificare che la copia cold combaci col locale prima di evictare:
    un cold troncato (es. m4b senza moov caricato mid-write) ha dimensione
    diversa dal locale completo e NON deve autorizzare la cancellazione."""
    try:
        r = _get_client().head_object(Bucket=_BUCKET, Key=_full_key(key))
        return int(r["ContentLength"])
    except ClientError as e:
        code = str(getattr(e, "response", {}).get("Error", {}).get("Code", ""))
        if code in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def get_range(key, start, end):
    """Legge i byte [start, end] inclusivi dell'oggetto (Range GET). Ritorna i
    byte letti, o b'' su errore/assenza. Usato per validazioni leggere (es.
    camminare gli atom MP4 di un m4b cold senza scaricarlo tutto)."""
    try:
        r = _get_client().get_object(Bucket=_BUCKET, Key=_full_key(key),
                                     Range=f"bytes={start}-{end}")
        return r["Body"].read()
    except Exception:
        return b""


def presigned_get_url(key, download_name=None, ttl=None):
    """URL GET temporaneo per redirect 302. download_name forza il filename
    via Content-Disposition (preservato attraverso il redirect)."""
    params = {"Bucket": _BUCKET, "Key": _full_key(key)}
    if download_name:
        ascii_name = (download_name.encode("ascii", "ignore").decode("ascii").replace('"', "")) or "download"
        utf8_name = quote(download_name)
        params["ResponseContentDisposition"] = (
            f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"
        )
    return _get_client().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=int(ttl or _PRESIGN_TTL)
    )


def presigned_put_url(key, ttl=None):
    """URL PUT temporaneo per upload diretto del client su S3/R2. Nessun
    vincolo di Content-Type (il client carica i byte così come sono)."""
    return _get_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": _BUCKET, "Key": _full_key(key)},
        ExpiresIn=int(ttl or _PRESIGN_TTL),
    )


def delete_object(key):
    """Cancella un singolo oggetto. Idempotente lato S3."""
    _get_client().delete_object(Bucket=_BUCKET, Key=_full_key(key))


def list_prefix(prefix):
    """Elenca le chiavi degli oggetti cold sotto `prefix`, ritornate nello stesso
    namespace di `storage_tiering.key_for_path` (relative a DATA_DIR, senza
    l'eventuale ABM_S3_KEY_PREFIX di bucket). Usato per ricostruire i download di
    un job finalizzato non più in RAM localizzando gli output su cold. [] se il
    backend non è configurato o su errore."""
    if not is_enabled():
        return []
    client = _get_client()
    full = _full_key(prefix)
    strip = f"{_KEY_PREFIX}/" if _KEY_PREFIX else ""
    out = []
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=_BUCKET, Prefix=full):
            for obj in page.get("Contents", []):
                k = obj["Key"]
                if strip and k.startswith(strip):
                    k = k[len(strip):]
                out.append(k)
    except Exception as e:
        print(f"[storage] list_prefix failed for {prefix}: {e}")
        return []
    return out


def delete_prefix(prefix):
    """Cancella tutti gli oggetti sotto `prefix` (cold cleanup di un job dir).
    Pagina e cancella a batch di 1000."""
    client = _get_client()
    full = _full_key(prefix)
    paginator = client.get_paginator("list_objects_v2")
    batch = []
    for page in paginator.paginate(Bucket=_BUCKET, Prefix=full):
        for obj in page.get("Contents", []):
            batch.append({"Key": obj["Key"]})
            if len(batch) == 1000:
                client.delete_objects(Bucket=_BUCKET, Delete={"Objects": batch})
                batch = []
    if batch:
        client.delete_objects(Bucket=_BUCKET, Delete={"Objects": batch})
