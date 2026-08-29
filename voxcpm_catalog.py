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
    """Svuota la cache: il prossimo `voices()` rilegge il file.

    Svuota anche la cache dei campioni codificati in `voxcpm_tts`: un
    catalogo cambiato (voci rigenerate, cartella spostata) puo' spostare o
    sostituire il .wav di una voce, e quella cache altrimenti continuerebbe
    a servire il campione vecchio. Import interno per non creare un ciclo:
    `voxcpm_tts` importa questo modulo al livello del modulo.
    """
    global _cache
    with _lock:
        _cache = None
    try:
        import voxcpm_tts
    except ImportError:
        return
    voxcpm_tts.invalidate_clone_cache()


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


MODEL_ID = CATALOG_SCHEMA          # "v2": la chiave modello nel voice id
MODEL_LABEL = "VoxCPM2"            # etichetta del selettore MODELLO


def _display_name(rec):
    """`Nolan` -> `Nolan (US)`.

    Dentro una stessa lingua convivono piu' varianti (`en-US`, `en-GB`, i nove
    `zh-*`): senza la regione nel nome, chi non usa il filtro ACCENTO non sa
    cosa sta scegliendo. Stessa convenzione delle voci Edge.
    """
    region = rec["locale"].split("-")[-1].upper()
    return f"{rec['name']} ({region})"


def _sample_url(voice_id):
    from urllib.parse import quote
    return "/api/voice_sample?voice=" + quote(voice_id, safe="")


def get_voices():
    """Catalogo per l'UI: {codice lingua: [entry, ...]}.

    Stessa forma delle entry di `speechify_tts.get_voices()` e delle voci Edge,
    cosi' `_fetch_voices()` in audiobook_app le fonde senza casi speciali. In
    piu' porta `persona` (il CARATTERE, filtro del pannello) e `sample_url`
    (il player del campione di riferimento, che sostituisce l'anteprima).
    """
    out = {}
    for rec in voices():
        out.setdefault(rec["lang"], []).append({
            "id": rec["id"],
            "name": _display_name(rec),
            "locale": rec["locale"],
            "engine": "voxcpm",
            "model_key": MODEL_ID,
            "model_label": MODEL_LABEL,
            "gender": rec["gender"],
            "gender_icon": "\U0001f469" if rec["gender"] == "Female" else "\U0001f468",
            "persona": rec["persona"],
            # Il `role` del catalogo viaggia con l'entry: e' l'anello di mezzo
            # della catena di ricadute con cui il Task 13 traduce i caratteri,
            # quando la chiave non e' ancora nel dizionario.
            "persona_role": rec["role"],
            "sample_url": _sample_url(rec["id"]),
        })
    for entries in out.values():
        entries.sort(key=lambda e: (e["gender"], e["name"]))
    return out


def parse_voice_id(voice_id):
    """Da `voxcpm:v2:<locale>/<Nome>` al record del catalogo.

    Solleva ValueError su qualunque altra forma, voce clonata compresa: le
    `voxcpm:mine:<token>` le risolve `voice_clone`, non questo modulo. Anche
    una voce sparita dal catalogo dopo una rigenerazione finisce qui, ed e' un
    caso normale (§9.4): chi chiama lo tratta come voce non piu' disponibile,
    non come errore di programmazione.
    """
    if not isinstance(voice_id, str) or not voice_id:
        raise ValueError(f"voice id VoxCPM non valido: {voice_id!r}")
    parts = voice_id.split(":", 2)
    if len(parts) != 3 or parts[0] != "voxcpm":
        raise ValueError(f"voice id VoxCPM non valido: {voice_id!r}")
    schema, rest = parts[1], parts[2]
    if schema != CATALOG_SCHEMA:
        raise ValueError(
            f"schema {schema!r} non e' di catalogo (atteso {CATALOG_SCHEMA!r}): {voice_id!r}")
    for rec in voices():
        if rec["id"] == voice_id:
            return rec
    raise ValueError(f"voce non presente nel catalogo: {rest!r}")


def sample_path(voice_id):
    """Percorso assoluto del `.wav` di riferimento della voce.

    Il percorso relativo arriva da un file di dati importato: si verifica che
    resti dentro `catalog_dir()` prima di aprirlo.
    """
    rec = parse_voice_id(voice_id)
    base = catalog_dir()
    path = os.path.abspath(os.path.join(base, rec["sample_rel"].replace("/", os.sep)))
    if os.path.commonpath([base, path]) != base:
        raise ValueError(f"campione fuori dal catalogo: {rec['sample_rel']!r}")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return path
