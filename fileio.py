"""fileio — primitive di persistenza su file condivise da tutto il progetto.

Modulo foglia (solo stdlib). Qui vivono le poche operazioni che prima erano
copiate in una decina di moduli con piccole differenze (tmp senza fsync, tmp
non rimosso, `json.load` senza controllo di tipo, default di `ABM_DATA_DIR`
ripetuto in nove file):

- `data_dir()` / `data_path(name)`: la cartella dati (`ABM_DATA_DIR`), letta
  a ogni chiamata perche' i test la cambiano per isolare lo stato;
- `atomic_write_json` / `atomic_write_text`: tmp + fsync opzionale +
  `os.replace`, mai un file osservabile troncato; propagano le eccezioni;
- `write_json_safe`: come sopra ma non solleva mai (True/False) e non lascia
  il `.tmp` in giro, per gli store best-effort;
- `load_json`: file assente o illeggibile -> default, con controllo del tipo
  atteso e un hook `on_error` per chi vuole loggare;
- `write_json_verified`: scrive e rilegge con retry, per gli interruttori a
  senso unico che non devono mai restare solo in memoria.

Nessuna di queste funzioni prende lock: la disciplina resta nel chiamante.
`community_store.atomic_write_json` e' un alias di quello qui dentro.
"""
import json
import os
import threading
import time
from pathlib import Path

from env_utils import env_str

DEFAULT_DATA_DIR = "/var/lib/audiobook-maker/data"


def data_dir():
    """Cartella dati persistente (`ABM_DATA_DIR`), letta a ogni chiamata."""
    return Path(env_str("ABM_DATA_DIR", DEFAULT_DATA_DIR))


def data_path(name):
    return data_dir() / name


def atomic_write_text(path, text, *, fsync=True, encoding="utf-8"):
    """Scrive `text` su `path` in modo atomico (tmp + fsync opzionale +
    os.replace). Propaga le eccezioni; il `.tmp` viene rimosso su errore."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Nome del tmp unico per processo e thread: due scrittori concorrenti
    # sullo stesso file (store senza lock esterno, last-writer-wins) non
    # devono mai condividere il file temporaneo, altrimenti il rename o la
    # pulizia dell'uno cancella quello dell'altro.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding=encoding) as f:
            f.write(text)
            if fsync:
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass  # filesystem senza fsync (rari edge case)
        os.replace(str(tmp), str(path))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def atomic_write_json(path, data, *, fsync=True, ensure_ascii=False, indent=None):
    """Scrive `data` come JSON su `path` in modo atomico: tmp + fsync opzionale
    + os.replace. Un crash a meta' write lascia intatto il file precedente; il
    rename atomico garantisce che il file non sia mai osservabile troncato.

    NON e' thread-safe di per se': la disciplina di lock resta a carico del
    chiamante. Propaga le eccezioni. I parametri di formato replicano quelli
    dei writer originali per mantenere byte-stabile il contenuto su disco.
    """
    atomic_write_text(path, json.dumps(data, ensure_ascii=ensure_ascii, indent=indent),
                      fsync=fsync)


def write_json_safe(path, data, *, fsync=False, ensure_ascii=False, indent=None,
                    on_error=None) -> bool:
    """`atomic_write_json` che non solleva: True se scritto, False altrimenti
    (con `on_error(exc)` se dato). Per gli store best-effort (manifest di
    riuso, riporto costi, contatori) dove un disco che dice di no non deve
    fermare il job."""
    try:
        atomic_write_json(path, data, fsync=fsync, ensure_ascii=ensure_ascii, indent=indent)
        return True
    except Exception as e:  # noqa: BLE001
        if on_error is not None:
            try:
                on_error(e)
            except Exception:  # noqa: BLE001
                pass
        return False


_MISSING = object()


def load_json(path, default=_MISSING, *, expect=dict, on_error=None):
    """Legge un JSON da `path`. File assente -> `default` (in silenzio);
    illeggibile o di tipo diverso da `expect` -> `default`, dopo
    `on_error(exc)` se dato. `default` puo' essere un valore o una factory
    (es. `dict`); con `expect=None` nessun controllo di tipo."""
    def _default():
        if default is _MISSING:
            return {} if expect is dict else None
        return default() if callable(default) else default

    path = Path(path)
    if not path.exists():
        return _default()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if expect is not None and not isinstance(data, expect):
            raise TypeError(f"{path.name}: atteso {expect.__name__}, trovato "
                            f"{type(data).__name__}")
        return data
    except Exception as e:  # noqa: BLE001
        if on_error is not None:
            try:
                on_error(e)
            except Exception:  # noqa: BLE001
                pass
        return _default()


def write_json_verified(path, data, *, attempts=3, backoff=0.2, fsync=True,
                        ensure_ascii=False, indent=None):
    """Scrive e rilegge finche' il contenuto su disco combacia (max
    `attempts`, pausa crescente). Ritorna (ok, ultimo_errore). Per gli stati
    a senso unico (kill-switch, breaker) che un riavvio ricaricherebbe
    stantii se la write fosse andata a vuoto."""
    last_err = None
    for i in range(max(1, attempts)):
        try:
            atomic_write_json(path, data, fsync=fsync, ensure_ascii=ensure_ascii, indent=indent)
            with open(path, "r", encoding="utf-8") as f:
                check = json.load(f)
            if check == data:
                return True, None
            last_err = ValueError("rilettura post-scrittura non combacia")
        except (OSError, ValueError, TypeError) as e:
            last_err = e
        if i < attempts - 1:
            time.sleep(backoff * (i + 1))
    return False, last_err


# ---------------------------------------------------------------------------
# Filename sanitization
# ---------------------------------------------------------------------------

# Limite di lunghezza dei nomi file generati, in BYTE UTF-8. I filesystem
# (ext4: 255 byte per componente del path) contano byte, non caratteri: un
# titolo CJK (3 byte/carattere) o con emoji (4 byte) supera i 255 byte molto
# prima dei 255 caratteri e fa fallire l'apertura del file con
# OSError [Errno 36] File name too long, uccidendo il thread del job. Il
# margine rispetto ai 255 byte copre estensione e suffissi aggiunti dai
# chiamanti (numerazione capitoli, _podcast.xml, ...).
MAX_FILENAME_BYTES = 150


def truncate_filename(name, max_bytes=MAX_FILENAME_BYTES):
    """Tronca un nome file a max_bytes in UTF-8 senza spezzare i caratteri."""
    if not name:
        return name
    raw = name.encode("utf-8")
    if len(raw) <= max_bytes:
        return name
    # errors='ignore' scarta l'eventuale carattere multibyte tagliato a meta'.
    return raw[:max_bytes].decode("utf-8", "ignore")


def safe_filename(name, *, replacement="", keep_dots=False, collapse_spaces=True,
                  guard_dash=True, max_chars=100, max_bytes=MAX_FILENAME_BYTES):
    """Nome file sicuro (F2b: unica regola, prima due copie in `audio_utils` e
    `translation_core`). Default = regola storica degli output audio: via i
    caratteri di controllo, i caratteri vietati dai filesystem e i punti
    (rompono il riconoscimento dell'estensione nei download), spazi -> `_`,
    niente `-` iniziale (iniezione di argomenti CLI), 100 caratteri e
    `MAX_FILENAME_BYTES` byte UTF-8. `translation_core` usa i parametri per
    la sua forma (sostituzione con `_`, punti conservati, nessun limite).

    I caratteri di controllo (NUL in testa) vanno via per primi: open() rifiuta
    un path con un byte NUL alzando ValueError, che non e' un OSError e quindi
    sfugge ai try/except dei chiamanti, uccidendo il thread del job a sintesi
    gia' completata. I PDF de-DRM-ati portano spesso un NUL nel titolo dei
    metadati (04/09/2026: sei generazioni identiche fallite in assembly)."""
    import re
    name = re.sub(r'[\x00-\x1f\x7f]', replacement, name or "")
    name = re.sub(r'[<>:"/\\|?*' + ("" if keep_dots else ".") + "]", replacement, name)
    if collapse_spaces:
        name = re.sub(r'\s+', '_', name.strip())
    if guard_dash and name.startswith('-'):
        name = '_' + name
    if max_chars is not None:
        name = name[:max_chars]
    return truncate_filename(name, max_bytes) if max_bytes else name
