"""Contabilita' del costo TTS che sopravvive al riavvio del processo.

Il costo provider di un job premium si accumula in memoria: `gemini_actual`,
`speechify_actual`, `voxcpm_actual` dentro il dict del job. Un riavvio
dell'applicazione azzera quei contatori, ma NON il lavoro gia' fatto: i chunk
sintetizzati restano su disco e `chunk_reuse` li riconsegna al tentativo
successivo senza ri-sintetizzarli. Il risultato e' un job che riparte con un
libro quasi finito e una contabilita' a zero: la console admin mostra poche
migliaia di caratteri e qualche centesimo di costo TTS su un audiolibro pagato
decine di euro, con un margine percentuale assurdo, e il record finale
nell'audit JSONL eredita lo stesso buco — il costo speso prima del riavvio non
e' rimandato a dopo, e' perso.

Qui il totale corrente si deposita in un file dentro la work_dir del job, che
sopravvive al riavvio esattamente come i chunk gia' sintetizzati, e il
tentativo successivo riparte da quel totale invece che da zero.

Il file si cancella subito dopo che il record d'audit lo ha assorbito: da quel
momento il costo vive nel JSONL, e un ulteriore tentativo sullo stesso job non
deve sommarlo una seconda volta (i due record si sommano gia' da soli).

Tutto best-effort: un errore di I/O qui non deve mai fermare una generazione.
La contabilita' e' importante, l'audiolibro di piu'.
"""
from __future__ import annotations

import json
import os

CARRY_NAME = ".cost_carry.json"

# Ogni quanti chunk si riscrive il file. Non a ogni chunk: e' I/O inutile su
# job da migliaia di chunk. Non troppo di rado: un `kill -9` perde quello che
# e' successo dall'ultima scrittura, e 25 chunk sono meno di un minuto di TTS.
DEFAULT_FLUSH_EVERY = 25


def flush_every() -> int:
    try:
        return max(1, int(os.environ.get("ABM_COST_CARRY_EVERY", "") or
                          DEFAULT_FLUSH_EVERY))
    except (TypeError, ValueError):
        return DEFAULT_FLUSH_EVERY


def carry_path(work_dir) -> str:
    return os.path.join(str(work_dir), CARRY_NAME)


def read_all(work_dir) -> dict:
    """Tutti i riporti del job, per motore. `{}` se non c'e' o e' illeggibile."""
    try:
        with open(carry_path(work_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def read(work_dir, engine: str) -> dict:
    """Il riporto del motore `engine` ("gemini"/"speechify"/"voxcpm")."""
    entry = read_all(work_dir).get(str(engine))
    return entry if isinstance(entry, dict) else {}


def write(work_dir, engine: str, actual) -> bool:
    """Deposita il totale corrente del motore (tmp+rename). Non solleva.

    Gli altri motori presenti nel file restano al loro posto: un job che
    cambiasse motore fra due tentativi non deve cancellare la spesa del primo.
    """
    if not isinstance(actual, dict):
        return False
    data = read_all(work_dir)
    data[str(engine)] = actual
    path = carry_path(work_dir)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        return False


def clear(work_dir, engine=None) -> bool:
    """Butta il riporto: il record d'audit lo ha appena assorbito.

    Senza `engine` cancella l'intero file. Con `engine`, toglie solo quel
    motore e riscrive il resto (l'ultimo motore rimasto porta via il file).
    """
    path = carry_path(work_dir)
    if engine is None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except Exception:
            return False
        return True
    data = read_all(work_dir)
    if str(engine) not in data:
        return True
    data.pop(str(engine), None)
    if not data:
        return clear(work_dir)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        return False


def _combine(vecchio, nuovo):
    """Un campo del riporto fuso con quello del tentativo in corso.

    `vecchio` e' il riporto (cio' che e' stato speso prima del riavvio),
    `nuovo` quello che il tentativo corrente ha gia' accumulato — di norma
    zero, perche' la fusione avviene appena dopo l'inizializzazione.

    Numeri: si sommano, sono contatori di spesa.
    Stringhe: vince quella gia' presente (il `model_key` del tentativo in
        corso e' quello vero); il riporto la copre solo se manca.
    Liste di numeri: somma posizione per posizione (`verifica_rientri` e' un
        istogramma: il secondo giro di ieri e il secondo giro di oggi sono lo
        stesso giro).
    Liste di altro: concatenazione col riporto davanti, in ordine di tempo
        (`runpod`, `code_tagliate_dettaglio` sono elenchi di eventi).
    """
    if nuovo is None:
        return vecchio
    if isinstance(vecchio, bool) or isinstance(nuovo, bool):
        return bool(vecchio) or bool(nuovo)
    if isinstance(vecchio, (int, float)) and isinstance(nuovo, (int, float)):
        return vecchio + nuovo
    if isinstance(vecchio, str) and isinstance(nuovo, str):
        return nuovo or vecchio
    if isinstance(vecchio, list) and isinstance(nuovo, list):
        if all(isinstance(x, (int, float)) and not isinstance(x, bool)
               for x in vecchio + nuovo):
            lungo = max(len(vecchio), len(nuovo))
            return [(vecchio[i] if i < len(vecchio) else 0) +
                    (nuovo[i] if i < len(nuovo) else 0) for i in range(lungo)]
        return list(vecchio) + list(nuovo)
    return nuovo


def merge(actual, carry) -> dict:
    """Somma il riporto dentro `actual`, sul posto. Ritorna `actual`.

    Chiamata una sola volta per tentativo, subito dopo l'inizializzazione dei
    contatori: chiamarla due volte raddoppierebbe la spesa riportata.
    """
    if not isinstance(actual, dict) or not isinstance(carry, dict):
        return actual
    for k, v in carry.items():
        actual[k] = _combine(v, actual.get(k))
    return actual


def resume(work_dir, engine: str, actual) -> dict:
    """`merge` col riporto su disco. Non solleva: contabilita' best-effort."""
    try:
        return merge(actual, read(work_dir, engine))
    except Exception:
        return actual
