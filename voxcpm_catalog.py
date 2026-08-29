"""Catalogo delle voci inventate VoxCPM: lettura, validazione, indice.

Il catalogo e' un DATO IMPORTATO dal repo `abm-voxcpm-worker`, non una
sorgente mantenuta qui (D10, §12.1 della spec). La generazione delle voci
prosegue in parallelo all'app: numero di voci, nomi, lingue e caratteri
cambiano. Nessuna costante di questo modulo elenca voci, lingue o caratteri:
tutto si ricava leggendo `voices.json` a runtime.

Il modulo non conosce RunPod e non fa rete: e' lettura di un file piu' un
indice in memoria. Il dialogo col worker sta in `voxcpm_tts.py`.
"""
import json
import os
import threading

# Schema degli id di catalogo: `voxcpm:v2:<locale>/<Nome>` (§12.2).
CATALOG_SCHEMA = "v2"
_ID_PREFIX = "voxcpm:" + CATALOG_SCHEMA + ":"

_DEFAULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "voci_inventate")

_lock = threading.Lock()
_cache = None  # list[dict] | None


def catalog_dir():
    """Cartella del catalogo importato, assoluta.

    `ABM_VOXCPM_CATALOG_DIR` la sposta: aggiornare il catalogo e' sostituire
    una cartella, non toccare il codice.
    """
    raw = (os.environ.get("ABM_VOXCPM_CATALOG_DIR") or "").strip()
    return os.path.abspath(raw) if raw else _DEFAULT_DIR


def invalidate_cache():
    """Svuota la cache: il prossimo `voices()` rilegge il file."""
    global _cache
    with _lock:
        _cache = None


def _normalize(raw):
    """Un elemento di `voices.json` -> record piatto, o None se inutilizzabile.

    Requisito duro (§5.2): senza `description.persona` la voce non e'
    mostrabile, perche' il carattere e' la colonna con cui la si filtra. Si
    scarta con una riga di log invece di comparire senza carattere.
    """
    if not isinstance(raw, dict):
        return None
    src_id = raw.get("id") or "<senza id>"
    name = (raw.get("name") or "").strip()
    lang_block = raw.get("language") or {}
    locale = (lang_block.get("locale") or "").strip()
    desc = raw.get("description") or {}
    persona = (desc.get("persona") or "").strip()
    if not persona:
        print(f"[voxcpm_catalog] voce scartata: {src_id} non ha description.persona")
        return None
    if not name or not locale:
        print(f"[voxcpm_catalog] voce scartata: {src_id} senza name o locale")
        return None
    audio = raw.get("audio") or {}
    sample_rel = (audio.get("file") or "").strip()
    transcript = (audio.get("transcript") or "").strip()
    if not sample_rel or not transcript:
        # `hifi` richiede prompt_wav E prompt_text (§7.4): un campione senza la
        # sua trascrizione non e' clonabile, la voce non va offerta.
        print(f"[voxcpm_catalog] voce scartata: {src_id} senza campione o trascrizione")
        return None
    gender_value = ((raw.get("gender") or {}).get("value") or "").strip().lower()
    return {
        "id": f"{_ID_PREFIX}{locale}/{name}",
        "name": name,
        "locale": locale,
        "lang": (lang_block.get("code") or locale.split("-")[0]).strip(),
        "gender": "Female" if gender_value == "f" else "Male",
        "persona": persona,
        "role": (desc.get("role") or "").strip(),
        "axes": [str(a) for a in (desc.get("axes") or [])],
        "sample_rel": sample_rel,
        "transcript": transcript,
        "duration_s": float(audio.get("duration_s") or 0.0),
    }


def _load():
    """Legge e normalizza `voices.json`.

    Non solleva mai: catalogo assente o illeggibile significa motore non
    disponibile, non app rotta (§9.4).
    """
    path = os.path.join(catalog_dir(), "voices.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as e:
        print(f"[voxcpm_catalog] voices.json non leggibile ({path}): {e}")
        return []
    if not isinstance(data, dict):
        print(f"[voxcpm_catalog] voices.json è un {type(data).__name__}, atteso dict ({path})")
        return []
    out = []
    for raw in (data.get("voices") or []):
        try:
            rec = _normalize(raw)
            if rec is not None:
                out.append(rec)
        except Exception as e:
            src_id = raw.get("id") if isinstance(raw, dict) else "<non-dict>"
            print(f"[voxcpm_catalog] voce scartata: {src_id} errore normalizzazione: {e}")
    print(f"[voxcpm_catalog] {len(out)} voci caricate da {path}")
    return out


def voices():
    """I record validi del catalogo, in cache. Lista vuota se non c'e' nulla."""
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
    loaded = _load()
    with _lock:
        _cache = loaded
    return loaded


def personas():
    """Caratteri presenti nel catalogo, ordinati. Chiavi tecniche, non label."""
    return sorted({v["persona"] for v in voices()})
