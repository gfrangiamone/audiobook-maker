"""client_identity — email, hash e mascheramento dell'identita' del client.

Modulo foglia (stdlib + env_utils). Raccoglie le primitive che prima erano
copiate in sette moduli con piccole differenze: tre varianti di hash salato
(salt e separatore diversi), due `email_hash` identici, due `mask_email`
quasi uguali, la regex dell'email scritta sette volte.

Gli hash salati sono CHIAVI su disco (quote per email, dossier abuso,
sessioni): `salted_hash` e' parametrizzato su salt e separatore apposta, cosi'
ogni chiamante conserva la propria forma storica byte per byte. Cambiare
salt o separatore e' una migrazione dei dati, non un refactor.
"""
import hashlib
import ipaddress
import re

from env_utils import env_str

# Regex storica dell'app (account, registrazione email, traduzione, SMTP).
# `/api/support/contact` ne usa volutamente una piu' lasca: vedi
# audiobook_app._SUPPORT_EMAIL_RE.
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

DEFAULT_IP_SALT = "abm-default-salt-v1"


def norm_email(email):
    """Forma canonica dell'email: senza spazi ai bordi, minuscola; '' se assente."""
    return (email or "").strip().lower()


def is_valid_email(email):
    """True se `email` (gia' o non ancora normalizzata) rispetta EMAIL_RE."""
    e = (email or "").strip()
    return bool(e) and EMAIL_RE.match(e) is not None


def sha256_hex(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def email_hash(email):
    """sha256 completo dell'email normalizzata (account, voci campionate)."""
    return sha256_hex(norm_email(email))


def salted_hash(value, *, salt, sep="", length=16):
    """sha256 di `salt + sep + value`, troncato a `length` esadecimali.

    Forme storiche: `_hash_ip` -> sep=":" con `ip_salt()`; dossier abuso ->
    sep="" con `ip_salt()`; chiave email della quota standard -> sep="" con
    `ip_salt(default="")`; rete della quota premium (`network_hash`) -> come
    `_hash_ip`.
    """
    h = hashlib.sha256((str(salt) + sep + str(value)).encode("utf-8")).hexdigest()
    return h[:length] if length else h


def ip_salt(default=DEFAULT_IP_SALT):
    """`ABM_IP_SALT`, letto a ogni chiamata; `default` se assente o vuoto."""
    return env_str("ABM_IP_SALT", default)


def network_of(ip):
    """Rete di un IP per le quote: l'IPv4 esatto, il /64 di un IPv6 (un
    dispositivo cambia il suffisso per privacy, il prefisso resta), un IPv4
    mappato in IPv6 come IPv4. Stringa vuota se `ip` non e' un indirizzo."""
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return ""
    if addr.version == 6 and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if addr.version == 4:
        return str(addr)
    return str(ipaddress.ip_network(f"{addr}/64", strict=False))


def network_hash(ip):
    """Hash salato della rete di `ip` (`network_of`), nella forma di
    `_hash_ip`: per un IPv4 coincide con l'hash dei log e dei rate limit.
    Stringa vuota se `ip` non e' un indirizzo."""
    net = network_of(ip)
    return salted_hash(net, salt=ip_salt(), sep=":") if net else ""


def mask_email(email, *, strip=True, invalid=""):
    """'john.doe@x.com' -> 'j***@x.com'. Con `invalid=None` un input senza
    `@` o senza parte locale torna com'e' (comportamento best-effort della
    SPA); altrimenti torna `invalid` (pagine account: stringa vuota)."""
    s = str(email or "")
    if strip:
        s = s.strip()
    local, at, domain = s.partition("@")
    if not at or not local:
        return s if invalid is None else invalid
    return f"{local[0]}***@{domain}"
