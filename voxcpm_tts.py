"""Motore TTS VoxCPM2 servito dal worker RunPod serverless.

Porting del cuore di `voxcpm_book.py` (repo `abm-voxcpm-worker`), non una
riscrittura: pianificazione dei chunk, sottomissione `/run`, polling
`/status`, tassonomia degli errori.

Il modulo non legge file di catalogo: le voci le risolve `voxcpm_catalog`.
Qui c'e' il dialogo con RunPod e il listino.

Economia del motore, che spiega scelte che altrove sembrerebbero strane
(§2 e §9.2 della spec): il costo sta nell'accensione del worker (~180 s a
freddo), non nei caratteri. Un job da 1 chunk e uno da 8 costano uguale.
Da qui l'unita' di lavoro per capitolo e il retry a caldo dentro lo stesso
job invece del rilancio a freddo.
"""
import os

import voxcpm_catalog

MODEL_ID = voxcpm_catalog.MODEL_ID
MODEL_LABEL = voxcpm_catalog.MODEL_LABEL

# Costo GPU misurato il 2026-08-04 su RTX 4090 a $1,10/h: 28,5x realtime su
# 11.919 caratteri e 51 chunk a concorrenza 16 (§8.3). Alimenta SOLO l'audit
# del margine reale: il prezzo all'utente e' la tariffa, non questo numero.
_COST_USD_PER_MCHAR = 0.91


def _f(env, default):
    try:
        return float(str(os.environ.get(env, default)).replace(",", "."))
    except (ValueError, TypeError):
        return float(default)


def _i(env, default):
    try:
        return int(os.environ.get(env, str(default)))
    except (ValueError, TypeError):
        return int(default)


def endpoint_id():
    return os.environ.get("ABM_VOXCPM_ENDPOINT_ID", "").strip()


def api_key():
    return os.environ.get("ABM_VOXCPM_API_KEY", "").strip()


def rate_eur_per_mchar():
    """Tariffa di listino all'utente. 0 = non configurata (motore nascosto)."""
    return _f("ABM_VOXCPM_RATE_EUR_PER_MCHAR", 0.0)


def cost_usd_per_mchar():
    return _f("ABM_VOXCPM_COST_USD_PER_MCHAR", _COST_USD_PER_MCHAR)


def free_threshold_eur():
    return _f("ABM_VOXCPM_FREE_THRESHOLD_EUR", 0.50)


def concurrency():
    """Chunk in volo dentro un singolo job del worker. Floor a 1."""
    return max(1, _i("ABM_VOXCPM_CONCURRENCY", 32))


def is_available():
    """True sse il motore e' completamente configurato.

    Servono tutte e quattro le condizioni: endpoint, chiave, un catalogo con
    almeno una voce valida e una tariffa di listino. Se manca qualcosa VoxCPM
    non compare fra i modelli (§9.4), come gia' fa Gemini senza API key.

    La tariffa e' parte del requisito e non un dettaglio: §15.3 la lascia da
    fissare prima del deploy, e generare libri a prezzo non deciso e' peggio
    che non offrire il motore.
    """
    if not endpoint_id() or not api_key():
        return False
    if rate_eur_per_mchar() <= 0:
        return False
    return bool(voxcpm_catalog.voices())


def compute_user_price_eur(chars):
    """Prezzo di listino per `chars` caratteri.

    Tariffa diretta EUR/Mchar (D4), non la catena costo-USD + margine +
    fee PayPal di Gemini e Speechify: li' il costo provider e' una fattura,
    qui e' tempo di GPU, e il listino e' una decisione commerciale a se'.
    Le fee sono percio' gia' dentro la tariffa.

    Chiavi di ritorno allineate a `speechify_tts.compute_user_price_eur`,
    cosi' i chiamanti a valle non distinguono i due motori.
    """
    try:
        chars = int(chars or 0)
    except (TypeError, ValueError):
        chars = 0
    if chars < 0:
        chars = 0
    list_price = round(chars / 1_000_000.0 * rate_eur_per_mchar(), 2)
    threshold = free_threshold_eur()
    is_free = list_price < threshold
    return {
        "chars": chars,
        "cost_usd": round(chars / 1_000_000.0 * cost_usd_per_mchar(), 6),
        "list_price_eur": list_price,
        "user_price_eur": 0.0 if is_free else list_price,
        "is_free": is_free,
        "free_threshold_eur": threshold,
    }


def estimate_book_cost(chapters, language="it"):
    """Stima end-to-end sui caratteri di input, capitolo per capitolo.

    Args:
        chapters: lista di oggetti con attributo `.text`.
        language: ISO 639-1 della voce scelta (informativo).
    """
    chars_per_chapter = []
    chars_total = 0
    for ch in chapters:
        n = len(getattr(ch, "text", "") or "")
        chars_per_chapter.append(n)
        chars_total += n
    price = compute_user_price_eur(chars_total)
    return {
        "chars_total": chars_total,
        "chars_per_chapter": chars_per_chapter,
        "cost_usd": price["cost_usd"],
        "list_price_eur": price["list_price_eur"],
        "user_price_eur": price["user_price_eur"],
        "is_free": price["is_free"],
        "language": language,
        "model_key": MODEL_ID,
        "model_label": MODEL_LABEL,
    }
