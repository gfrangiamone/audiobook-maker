"""
gemini_tts.py — Gemini 2.5/3.1 Flash TTS integration.

Parallel to google_tts.py for Chirp3-HD. Uses google-genai SDK with separate
API key (or Vertex AI service account). Native output is PCM 24kHz mono 16-bit.

Plan A scope: standalone module — synthesis + pricing + usage tracking + preview cap.
Integration with tts_split / generation_engine / audiobook_app is Plan B.
"""

import os
import re
import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

# Predicato voce PREMIUM Gemini: definizione unica in voice_utils (modulo foglia).
from voice_utils import is_gemini_voice as _is_gemini_voice
# Primitivo condiviso di scrittura JSON atomica (tmp + fsync + os.replace).
# NB: set_admin_disabled (kill-switch) NON lo usa di proposito: ha un proprio
# protocollo write+verifica+retry (hardening incidente 2026-06).
from community_store import atomic_write_json as _atomic_write_json
from gemini_transport import TransportError
import gemini_transport as _transport
import tts_backend_state as _backend_state

# Audio output constants
#
# Rate baseline char/sec per lingua. Ricavati dall'audit reale
# (`gemini_cost_audit_2026-{06,07,08}.jsonl`, 256 job completati): mediana di
# `chars_total / audio_seconds_actual` per lingua. Servono a due cose:
#   1. fallback quando il log empirico non ha abbastanza campioni;
#   2. ancora per il clamp di `get_empirical_rate` (vedi RATE_CLAMP_*).
# La velocita` di lettura dipende molto dalla lingua (zh ~4 char/sec contro
# ~14 delle lingue latine): un unico numero globale sbagliava di 3.5x sul
# cinese. Il modello (flash25/flash31) invece e` irrilevante: sui 256 job
# spiega lo 0.4% della varianza del rate, quindi non entra in nessuna chiave.
LANG_BASELINE_RATE = {
    "it": 14.6,   # n=54
    "de": 14.4,   # n=75
    "es": 14.3,   # n=19
    "fr": 13.9,   # n=3
    "en": 13.4,   # n=93
    "tr": 13.0,   # n=4
    "zh": 4.0,    # n=3
}

# Mediana globale su tutte le lingue: default per quelle senza dati propri.
# NB: era 15 fino ad agosto 2026, valore mai misurato; i job reali danno 13.9.
CHARS_PER_AUDIO_SECOND = 13.9

# Il rate empirico non puo` allontanarsi dal baseline della lingua oltre questi
# fattori. Sui job reali il rapporto rate/baseline sta fra 0.85 e 1.34 (p10/p90),
# quindi la banda copre la variabilita` legittima e taglia solo le derive.
# Incidente 2026-08: con finestra di 20 campioni il rate en/flash31 era sceso a
# 12.53 (0.94x) senza clamp, gonfiando del 20% il preventivo di un audiolibro.
RATE_CLAMP_LOW = 0.75
RATE_CLAMP_HIGH = 1.35


def baseline_rate(language=None):
    """Rate char/sec di riferimento per la lingua (mai None, mai <=0)."""
    lang = (language or "")[:2].lower()
    return LANG_BASELINE_RATE.get(lang, CHARS_PER_AUDIO_SECOND)

def _audio_tokens_per_second(model_key=None):
    """Token audio output per secondo, per modello.

    Cerca ABM_GEMINI_AUDIO_TOKENS_PER_SECOND_<MODEL>; fallback a
    ABM_GEMINI_AUDIO_TOKENS_PER_SECOND; default hardcoded per modello.
    Default flash25=25 (conservativo, da verificare), flash31=29 (calibrato).
    """
    if model_key and model_key in GEMINI_MODELS:
        suffix = model_key.upper().replace("-", "")
        per_model = os.environ.get(f"ABM_GEMINI_AUDIO_TOKENS_PER_SECOND_{suffix}")
        if per_model:
            try:
                return float(per_model.replace(",", "."))
            except (ValueError, TypeError):
                pass
    global_val = os.environ.get("ABM_GEMINI_AUDIO_TOKENS_PER_SECOND")
    if global_val:
        try:
            return float(global_val.replace(",", "."))
        except (ValueError, TypeError):
            pass
    # Misurati sull'audit reale (giu-ago 2026, 256 job): output_tokens_actual /
    # audio_seconds_actual vale esattamente 25.0 per entrambi i modelli
    # (flash25: 92 job, cv 0.0%; flash31: 122 job su 168 esattamente a 25.0,
    # gli altri sopra solo per token bruciati dai chunk ritentati).
    # Il vecchio default flash31=29 sovrastimava il costo Google del 16%: e`
    # la causa principale del margine realizzato al 37% contro il 15% a target.
    defaults = {"flash25": 25.0, "flash31": 25.0}
    return defaults.get(model_key, 25.0) if model_key else 25.0
AUDIO_SAMPLE_RATE = 24000
AUDIO_CHANNELS = 1
AUDIO_SAMPLE_WIDTH_BYTES = 2

# Per-language token ratios (chars per token).
# Copre tutte le lingue ufficialmente supportate da Gemini TTS (vedi
# SUPPORTED_UI_LANGUAGES) + zh legacy. Latin ~4.0, Cyrillic ~3.0, CJK ~1.5,
# Indic/Arabic/Thai ~2.0.
CHARS_PER_TOKEN_BY_LANG = {
    "it": 4.0, "en": 4.0, "fr": 4.0, "es": 4.0, "de": 4.0, "pt": 4.0,
    "nl": 4.0, "pl": 4.0, "ro": 4.0, "tr": 4.0, "id": 4.0, "vi": 4.0,
    "ru": 3.0, "uk": 3.0,
    "zh": 1.5, "ja": 1.5, "ko": 1.5,
    "hi": 2.0, "ar": 2.0, "bn": 2.0, "mr": 2.0, "ta": 2.0, "te": 2.0, "th": 2.0,
    "default": 4.0,
}

# Chunk piccoli (default 700 char) per stabilita` acustica e prosodia uniforme.
# Lo strumento richiede Gemini Tier 2/3 (RPD elevato), quindi il costo aggiuntivo
# in numero di richieste e` accettabile in cambio di un audio piu` naturale.
# Override globale: ABM_GEMINI_CHUNK_CHARS. Override per-lingua:
# ABM_GEMINI_MAX_CHUNK_CHARS_<LANG_UPPER> (vince sempre).
DEFAULT_CHUNK_CHARS = int(os.environ.get("ABM_GEMINI_CHUNK_CHARS", "700"))

# Target QUALITA` (soft) sui byte UTF-8 del TESTO PURO da sintetizzare
# (esclusi i prefissi style/rate, che sono direttive di prompt e non audio).
# Sopra questa soglia Gemini TTS tende a degradare acusticamente, ma la
# chiamata API non fallisce -- synthesize() logga solo un warning.
MAX_BYTES_PER_CALL = int(os.environ.get("ABM_GEMINI_MAX_BYTES_PER_CALL", "8000"))

# Hard cap API sul PAYLOAD TOTALE (testo + prefissi style + prefix rate).
# E` il limite tecnico oltre il quale Gemini TTS rifiuta la chiamata. Distinto
# da MAX_BYTES_PER_CALL: quest'ultimo e` un target qualita` sul solo testo,
# mentre API_HARD_BYTES_CAP protegge dall'overshoot complessivo della call.
API_HARD_BYTES_CAP = int(os.environ.get("ABM_GEMINI_API_HARD_BYTES_CAP", "8000"))


def _f(env, default):
    try:
        return float(os.environ.get(env, str(default)).replace(",", "."))
    except (ValueError, TypeError):
        return float(default)


# Default region Vertex per modello (override via env in _resolve_location).
# flash25 GA disponibile su global con latenza inferiore.
# flash31 preview solo su us-central1.
_DEFAULT_VERTEX_LOCATION_FLASH25 = "global"
_DEFAULT_VERTEX_LOCATION_FLASH31 = "us-central1"

GEMINI_MODELS = {
    "flash25": {
        "id": "gemini-2.5-flash-preview-tts",
        "id_vertex": "gemini-2.5-flash-tts",
        # Nessuna verifica che Cloudflare ospiti questo modello: finche' non
        # c'e', flash25 resta su Vertex anche con backend=cloudflare.
        # Cloudflare non ospita alcuna variante TTS di Gemini 2.5
        # (verificato 26/08/2026): questo modello vive su Vertex.
        "id_cloudflare": None,
        "location_vertex": _DEFAULT_VERTEX_LOCATION_FLASH25,
        "label": "Gemini 2.5 Flash TTS",
        "input_usd_per_mtok": _f("ABM_GEMINI_25FLASH_INPUT_USD_PER_MTOK", 0.50),
        "output_usd_per_mtok": _f("ABM_GEMINI_25FLASH_OUTPUT_USD_PER_MTOK", 10.00),
        "default_margin_percent": _f("ABM_GEMINI_25FLASH_MARGIN_PERCENT", 35.0),
    },
    "flash31": {
        "id": "gemini-3.1-flash-tts-preview",
        "id_vertex": "gemini-3.1-flash-tts-preview",
        # Verificato il 26/08/2026: 30/30 voci sintetizzate, enum voci
        # coincidente con GEMINI_VOICE_NAMES (spec §10.1).
        "id_cloudflare": "google/gemini-3.1-flash-tts",
        "location_vertex": _DEFAULT_VERTEX_LOCATION_FLASH31,
        "label": "Gemini 3.1 Flash TTS",
        "input_usd_per_mtok": _f("ABM_GEMINI_31FLASH_INPUT_USD_PER_MTOK", 1.00),
        "output_usd_per_mtok": _f("ABM_GEMINI_31FLASH_OUTPUT_USD_PER_MTOK", 20.00),
        "default_margin_percent": _f("ABM_GEMINI_31FLASH_MARGIN_PERCENT", 25.0),
    },
}

# === Backend resolver (Vertex vs API key vs Cloudflare) ======================
# Cache per modello: il backend viene risolto al primo uso di quel modello e
# congelato, per evitare flip-flop se un task cambia env fra due chiamate.
# Muta solo per via esplicita, tramite `_set_backend` (failover del breaker).
# Reset esplicito (per test): `gemini_tts._BACKEND = {}`.
# Valori: "vertex" | "apikey" | "cloudflare" | False (DISABLED).
# Chiave usata quando il chiamante non specifica il modello: quel percorso
# non puo' selezionare Cloudflare, che e' sempre una scelta per modello.
_BACKEND_DEFAULT_KEY = "_default"
_BACKEND = {}
_BACKEND_LOCK = threading.Lock()

_VALID_BACKENDS = ("vertex", "apikey", "cloudflare")


def _set_backend(model_key, backend):
    """Forza il backend attivo di un modello. Usato dal failover.

    Non tocca l'ambiente: e' una decisione di runtime, e sopravvive solo per la
    vita del processo. La persistenza dello stato di trip e' responsabilita' di
    `tts_backend_state`.
    """
    if backend not in _VALID_BACKENDS and backend is not False:
        raise ValueError(f"backend sconosciuto: {backend!r}")
    with _BACKEND_LOCK:
        _BACKEND[model_key or _BACKEND_DEFAULT_KEY] = backend
    print(f"[gemini-tts] Backend di {model_key} impostato su {backend}")


def _vertex_ready():
    """True se il backend Vertex e' configurato e utilizzabile.

    Unico posto in cui si decide la prontezza di Vertex (rilievo M2, fix
    finale): `_resolve_backend` e `_trip_to_vertex` la interrogano entrambi.
    Prima erano due copie della stessa regola e sono divergite — il failover
    forzava Vertex senza controllo e finiva in `KeyError` dentro `_get_client`
    dove la spec §4.4 p.4 chiede `GeminiUnavailable`.
    """
    project = os.environ.get("ABM_GCP_PROJECT_ID", "").strip()
    creds = os.environ.get("ABM_GOOGLE_CREDENTIALS_FILE", "").strip()
    return bool(project) and bool(creds) and os.path.isfile(creds)


def _resolve_backend(model_key=None):
    """Risolve quale backend Gemini usare per un modello.

    Returns:
        "vertex" | "apikey" | "cloudflare" | None (None = TTS disabilitato).

    Logica:
    - ABM_GEMINI_BACKEND=vertex: richiede ABM_GCP_PROJECT_ID +
      ABM_GOOGLE_CREDENTIALS_FILE leggibile. Se mancano -> DISABLED.
    - ABM_GEMINI_BACKEND=apikey: richiede ABM_GEMINI_API_KEY.
    - ABM_GEMINI_BACKEND=cloudflare: richiede ABM_CF_ACCOUNT_ID +
      ABM_CF_API_TOKEN, E che il modello abbia un `id_cloudflare`. Un modello
      non ospitato su Cloudflare ricade su Vertex, non va in errore.
    - ABM_GEMINI_BACKEND unset o "auto": Vertex se la config e' completa,
      altrimenti API key se presente, altrimenti DISABLED. **auto non seleziona
      mai Cloudflare**: quel backend e' solo opt-in esplicito.

    Precedenza sul breaker: se `tts_backend_state.is_tripped(model_key)` e'
    True, tutto quanto sopra viene bypassato e si forza "vertex" (None se
    Vertex non e' pronto) — anche subito dopo un riavvio del processo, quando
    `_BACKEND` e' vuoto ma lo stato del breaker e' sopravvissuto su disco.
    """
    key = model_key or _BACKEND_DEFAULT_KEY
    cached = _BACKEND.get(key)
    if cached is not None:
        return cached if cached else None
    with _BACKEND_LOCK:
        cached = _BACKEND.get(key)
        if cached is not None:
            return cached if cached else None

        choice = (os.environ.get("ABM_GEMINI_BACKEND", "auto") or "auto").strip().lower()
        api_key = os.environ.get("ABM_GEMINI_API_KEY", "").strip()
        cf_account = os.environ.get("ABM_CF_ACCOUNT_ID", "").strip()
        cf_token = os.environ.get("ABM_CF_API_TOKEN", "").strip()

        vertex_ready = _vertex_ready()
        apikey_ready = bool(api_key)
        model_on_cf = bool((GEMINI_MODELS.get(key) or {}).get("id_cloudflare"))
        cf_ready = bool(cf_account) and bool(cf_token) and model_on_cf

        # Rilievo B1 (fix-1): il breaker persiste su disco (tts_backend_state)
        # precisamente perche' un riavvio del processo non possa rimettere un
        # modello scattato su Cloudflare. _BACKEND invece e' solo in-process e
        # riparte vuoto ad OGNI avvio (deploy, crash-restart, systemctl
        # restart: eventi di routine, non rari) - senza questo controllo la
        # prima risoluzione post-riavvio rivalutava da zero ABM_GEMINI_BACKEND
        # e un modello gia' marcato scattato tornava silenziosamente su
        # Cloudflare. is_tripped() legge la cache in-memory di
        # tts_backend_state (popolata da init() all'avvio, non dal disco ad
        # ogni chiamata): sicuro da interrogare per ogni chunk sul percorso
        # caldo. Bypassa la scelta ABM_GEMINI_BACKEND di proposito: un trip
        # vale per QUALSIASI configurazione finche' non arriva un reset
        # esplicito (rientro manuale, mai automatico).
        if model_key is not None and _backend_state.is_tripped(model_key):
            resolved = "vertex" if vertex_ready else False
            _BACKEND[key] = resolved
            if resolved:
                print(f"[gemini-tts] Backend di {key} forzato su vertex "
                      f"(breaker gia' scattato, stato persistito)")
            return resolved if resolved else None

        if choice == "vertex":
            resolved = "vertex" if vertex_ready else False
        elif choice == "apikey":
            resolved = "apikey" if apikey_ready else False
        elif choice == "cloudflare":
            if cf_ready:
                resolved = "cloudflare"
            elif model_on_cf:
                # Credenziali Cloudflare assenti: e' un errore di
                # configurazione, non un motivo per usare Vertex di nascosto.
                resolved = False
            elif vertex_ready:
                # Il modello non e' ospitato su Cloudflare: Vertex e' la scelta
                # corretta, non un ripiego.
                resolved = "vertex"
            else:
                resolved = False
        else:  # auto / sconosciuto
            if vertex_ready:
                resolved = "vertex"
            elif apikey_ready:
                resolved = "apikey"
            else:
                resolved = False

        _BACKEND[key] = resolved
        if resolved:
            print(f"[gemini-tts] Backend resolved ({key}): {resolved}")
        return resolved if resolved else None


def _vertex_project():
    return os.environ.get("ABM_GCP_PROJECT_ID", "").strip()


def _resolve_model_id(model_key):
    """Restituisce il model ID giusto per il backend corrente.

    Vertex usa nomi GA (`gemini-2.5-flash-tts`) mentre API key usa i nomi
    legacy `-preview-tts`. Per `flash31` il nome combacia (preview su entrambi).
    """
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown Gemini model: {model_key!r}")
    m = GEMINI_MODELS[model_key]
    # model_key deve viaggiare fino a _resolve_backend: la cache e la logica
    # cloudflare sono per-modello (id_cloudflare, model_on_cf). Risolvere qui
    # senza model_key congelerebbe la decisione sotto _BACKEND_DEFAULT_KEY,
    # che non puo' mai vedere Cloudflare (rilievo task-7).
    backend = _resolve_backend(model_key)
    if backend == "vertex":
        return m["id_vertex"]
    return m["id"]


def _resolve_location(model_key):
    """Restituisce la region Vertex configurata per il modello.

    Non controlla il backend attivo: il chiamante deve usare questo valore solo
    quando _resolve_backend() == "vertex" (per il backend apikey la region non
    si applica).

    Override env per-modello: ABM_VERTEX_LOCATION_FLASH25 / _FLASH31.
    Default: vedi GEMINI_MODELS[...]['location_vertex'].
    """
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown Gemini model: {model_key!r}")
    env_key = f"ABM_VERTEX_LOCATION_{model_key.upper()}"
    override = os.environ.get(env_key, "").strip()
    if override:
        return override
    return GEMINI_MODELS[model_key]["location_vertex"]


# === Failover automatico Cloudflare -> Vertex (circuit breaker) ============

# Callback invocata una sola volta, al primo scatto del breaker. Il piano
# gemello (Fase 6) ci aggancia l'email all'admin; qui resta un gancio nudo per
# non far dipendere gemini_tts da email_service.
_backend_switch_notifier = None


def set_backend_switch_notifier(fn):
    """Registra la callback di trip: fn(model_key, reason, detail, job_id)."""
    global _backend_switch_notifier
    _backend_switch_notifier = fn


def _cf_trip_failures():
    try:
        return max(1, int(os.environ.get("ABM_CF_TRIP_FAILURES", "3") or 3))
    except (TypeError, ValueError):
        return 3


def _transport_for(backend):
    """Adapter di trasporto corrispondente al backend risolto."""
    if backend == "cloudflare":
        return _transport.cloudflare_call
    return _vertex_transport_call


def _trip_to_vertex(model_key, *, reason, detail, job_id):
    """Fa scattare il breaker e sposta il modello su Vertex.

    L'email parte solo al primo chiamante: con piu' job in corso N thread
    scoprono l'avaria insieme, e `trip()` e' idempotente sotto lock.

    Raises:
        GeminiUnavailable: se Vertex non e' pronto (spec §4.4 p.4). Il trip e'
            comunque persistito e la notifica comunque inviata PRIMA di
            sollevare: e' proprio il caso in cui l'admin deve sapere che
            Cloudflare e' caduto e che non c'e' rete di sicurezza sotto.
    """
    first = _backend_state.trip(model_key, reason=reason, detail=detail,
                                job_id=job_id)
    # Prontezza decisa in un solo posto, la stessa che usa _resolve_backend:
    # il percorso di emergenza e' il momento peggiore per divergere.
    ready = _vertex_ready()
    if ready:
        _set_backend(model_key, "vertex")
    else:
        # Nessuna destinazione valida: il modello resta disabilitato invece di
        # essere marcato "vertex" e finire in un KeyError dentro _get_client.
        with _BACKEND_LOCK:
            _BACKEND[model_key or _BACKEND_DEFAULT_KEY] = False
        print(f"[gemini-tts] Backend di {model_key} DISABILITATO: breaker "
              f"scattato e Vertex non e' pronto (credenziali/progetto assenti)")
    if first and _backend_switch_notifier is not None:
        # `notified` deve riflettere che il tentativo c'e' stato, non che sia
        # andato a buon fine (rilievo minor, fix-1): un notifier che fallisce
        # non deve lasciare lo stato persistito com se nessuno avesse mai
        # provato ad avvisare l'admin. Per questo mark_notified() e' fuori
        # dal try che protegge la sola chiamata al notifier.
        try:
            _backend_switch_notifier(model_key, reason, detail, job_id)
        except Exception as e:
            # Un guasto nella notifica non deve fermare il job: il failover
            # e' gia' avvenuto, l'email e' un di piu'. Ma va loggato in modo
            # visibile: un'email admin che fallisce silenziosamente e'
            # proprio il caso in cui l'osservabilita' conta di piu'.
            print(f"[gemini-tts] ATTENZIONE: notifica di switch backend "
                  f"fallita per model_key={model_key}: {e}")
        _backend_state.mark_notified(model_key)

    if not ready:
        raise GeminiUnavailable(
            f"Backend Cloudflare fuori uso per {model_key} ({reason}) e Vertex "
            f"non e' configurato: nessun backend Gemini disponibile")


USD_EUR_RATE = _f("ABM_GEMINI_USD_EUR_RATE", 0.86)
PAYPAL_FIXED_FEE_EUR = _f("ABM_GEMINI_PAYPAL_FIXED_FEE_EUR", 0.34)
PAYPAL_PERCENT_FEE = _f("ABM_GEMINI_PAYPAL_PERCENT_FEE", 3.4)
FREE_THRESHOLD_EUR = _f("ABM_GEMINI_FREE_THRESHOLD_EUR", 0.50)
PREVIEW_CAP_PER_DAY = int(_f("ABM_GEMINI_PREVIEW_CAP_PER_DAY", 3))
PREVIEW_WINDOW_SECONDS = int(_f("ABM_GEMINI_PREVIEW_WINDOW_SEC", 300))

# === Rate limiting & retry tuning (Tier 1 friendly) =========================
# Free tier defaults qui sotto sono prudenti; alza i valori se hai billing
# attivo (vedi .env.gemini.tier1.example). I valori vengono letti a ogni call
# (no caching) per supportare reload a runtime durante test.
def _i(env, default):
    try:
        return int(os.environ.get(env, str(default)))
    except (ValueError, TypeError):
        return int(default)


def _b(env, default):
    v = os.environ.get(env)
    if v is None:
        return bool(default)
    return v.strip().lower() in ("1", "true", "yes", "on")


# Max attempts e backoff
SYNTH_MAX_ATTEMPTS_DEFAULT = 3

# Throttle RPM (millisecondi minimi tra due chiamate consecutive per modello).
# 0 = nessun throttle. Free tier: 6500 (flash25, 10 RPM) / 21000 (flash31, 3 RPM).
# Tier 1: 80 (flash25, ~750 RPM) / 200 (flash31, ~300 RPM).
def _min_interval_ms(model_key):
    if model_key == "flash25":
        return _i("ABM_GEMINI_MIN_INTERVAL_FLASH25_MS", 0)
    return _i("ABM_GEMINI_MIN_INTERVAL_FLASH31_MS", 0)


# RPD safety cap per modello (numero massimo di richieste/giorno).
# 0 = nessun cap locale (l'API Google fa da unica barriera).
def _rpd_cap(model_key):
    if model_key == "flash25":
        return _i("ABM_GEMINI_RPD_FLASH25", 0)
    return _i("ABM_GEMINI_RPD_FLASH31", 0)


def _rpd_safety_reserve():
    return _i("ABM_GEMINI_RPD_SAFETY_RESERVE", 0)


# Retry policy
def _synth_max_attempts():
    return _i("ABM_GEMINI_SYNTH_MAX_ATTEMPTS", SYNTH_MAX_ATTEMPTS_DEFAULT)


def _retry_honor_delay():
    return _b("ABM_GEMINI_RETRY_HONOR_DELAY", True)


def _retry_max_wait_sec():
    return _i("ABM_GEMINI_RETRY_MAX_WAIT_SEC", 60)


def _abort_on_daily_quota():
    # Free tier: True (inutile riprovare se retry è ore). Tier 1: False.
    return _b("ABM_GEMINI_ABORT_ON_QUOTA", True)


# === Quality tuning =========================================================
# Lo strumento e` pensato per Gemini Tier 2/3 (RPD elevato): privilegiamo
# stabilita` acustica e prosodia uniforme rispetto al numero di richieste.
# Defaults: temperature 0.75 (riduce deriva metallica sui chunk lunghi),
# gap 250 ms tra chunk consecutivi (respiro naturale al confine). Ogni
# parametro e` override-abile via env dedicata.
def _temperature():
    """Temperature passata al GenerateContentConfig. Default 0.75.
    Override: ABM_GEMINI_TEMPERATURE (float, accetta virgola decimale)."""
    val = os.environ.get("ABM_GEMINI_TEMPERATURE")
    if val is not None and val.strip() != "":
        try:
            return float(val.replace(",", "."))
        except ValueError:
            pass
    return 0.75


def inter_chunk_gap_ms():
    """Silenzio (ms) inserito tra chunk PCM consecutivi in concatenazione.
    Default 100. Override: ABM_GEMINI_INTER_CHUNK_GAP_MS (intero >= 0).

    NB: i chunk Gemini hanno trailing silence naturale variabile (50-1500 ms).
    Il trim trailing-silence (vedi trim_tail_ms()) li normalizza prima della
    concat, quindi un gap basso (100 ms) e' sufficiente come respiro acustico.
    Storicamente era 250 ms: causava pause percepibili di "qualche secondo"
    quando si sommava al trailing residuo non trimmato."""
    val = os.environ.get("ABM_GEMINI_INTER_CHUNK_GAP_MS")
    if val is not None and val.strip() != "":
        try:
            return max(0, int(val))
        except ValueError:
            pass
    return 100


def trim_tail_ms():
    """Cap massimo (ms) di silenzio finale da rimuovere a ogni PCM chunk Gemini.
    Default 800. Override: ABM_GEMINI_TRIM_TAIL_MS (intero >= 0). 0 = disabilita."""
    val = os.environ.get("ABM_GEMINI_TRIM_TAIL_MS")
    if val is not None and val.strip() != "":
        try:
            return max(0, int(val))
        except ValueError:
            pass
    return 800


def trim_tail_threshold():
    """Soglia ampiezza (0-32767) sotto cui un sample int16 e' considerato silenzio.
    Default 200 (≈ -44 dB). Override: ABM_GEMINI_TRIM_TAIL_THRESHOLD."""
    val = os.environ.get("ABM_GEMINI_TRIM_TAIL_THRESHOLD")
    if val is not None and val.strip() != "":
        try:
            return max(0, min(32767, int(val)))
        except ValueError:
            pass
    return 200


class GeminiQuotaExhausted(RuntimeError):
    """Sollevata quando l'errore 429 è daily-quota e ABORT_ON_QUOTA è True,
    oppure quando il cap RPD locale è raggiunto. Il chiamante può intercettare
    per sospendere il job invece di silenziare il chunk."""

    def __init__(self, message, retry_after_sec=None, reason="quota"):
        super().__init__(message)
        self.retry_after_sec = retry_after_sec
        self.reason = reason


class GeminiUnavailable(RuntimeError):
    """Sollevata da synthesize() quando is_available() è False (kill-switch
    attivo o capability assente). È un errore locale, istantaneo e permanente
    per il processo: il chiamante NON deve silenziare il chunk e proseguire
    (incidente 2026-06: 1905/1905 chunk silenziati in 1s su un job recuperato
    al boot con kill-switch stantio), deve abortire il job (failed + refund).
    Sottoclasse di RuntimeError per retro-compatibilità con i caller che
    intercettavano il vecchio RuntimeError."""

# Direttive di velocita` in linguaggio naturale (Gemini comprende molto meglio
# linguaggio naturale di tag come [slow]/[fast]). 7 step coprono la corsa del
# slider UI (-30% .. +30% a passi di 10%).
_GEMINI_RATE_DIRECTIVES = {
    -3: "Read this text very slowly, with deliberate, measured pacing and long pauses between sentences.",
    -2: "Read this text slowly, taking your time and articulating clearly.",
    -1: "Read this text at a slightly relaxed, slower than normal pace.",
     0: "",
     1: "Read this text at a slightly brisk pace, a bit faster than normal.",
     2: "Read this text at a quick, energetic pace.",
     3: "Read this text very quickly, with rapid pacing and minimal pauses.",
}

GEMINI_VOICE_NAMES = [
    "Achernar", "Achird", "Algenib", "Algieba", "Alnilam",
    "Aoede", "Autonoe", "Callirrhoe", "Charon", "Despina",
    "Enceladus", "Erinome", "Fenrir", "Gacrux", "Iapetus",
    "Kore", "Laomedeia", "Leda", "Orus", "Pulcherrima",
    "Puck", "Rasalgethi", "Sadachbia", "Sadaltager", "Schedar",
    "Sulafat", "Umbriel", "Vindemiatrix", "Zephyr", "Zubenelgenubi",
]

# Gender ufficiale Google per le voci Gemini TTS (Female / Male).
# Fonte: doc Google AI Studio - elenco voci Gemini 2.5/3.1 Flash TTS.
GEMINI_VOICE_GENDER = {
    "Achernar":     "Female",
    "Achird":       "Male",
    "Algenib":      "Male",
    "Algieba":      "Male",
    "Alnilam":      "Male",
    "Aoede":        "Female",
    "Autonoe":      "Female",
    "Callirrhoe":   "Female",
    "Charon":       "Male",
    "Despina":      "Female",
    "Enceladus":    "Male",
    "Erinome":      "Female",
    "Fenrir":       "Male",
    "Gacrux":       "Female",
    "Iapetus":      "Male",
    "Kore":         "Female",
    "Laomedeia":    "Female",
    "Leda":         "Female",
    "Orus":         "Male",
    "Pulcherrima":  "Female",
    "Puck":         "Male",
    "Rasalgethi":   "Male",
    "Sadachbia":    "Male",
    "Sadaltager":   "Male",
    "Schedar":      "Male",
    "Sulafat":      "Female",
    "Umbriel":      "Male",
    "Vindemiatrix": "Female",
    "Zephyr":       "Female",
    "Zubenelgenubi": "Male",
}


def _gender_icon(gender):
    """Icona unicode per gender (allineata con catalogo Edge)."""
    if gender == "Female":
        return "♀"  # ♀
    if gender == "Male":
        return "♂"  # ♂
    return ""


def get_margin_percent(model_key):
    """Margine corrente per il modello (legge env var aggiornata)."""
    if model_key == "flash25":
        return _f("ABM_GEMINI_25FLASH_MARGIN_PERCENT", 35.0)
    if model_key == "flash31":
        return _f("ABM_GEMINI_31FLASH_MARGIN_PERCENT", 25.0)
    raise ValueError(f"Unknown model_key: {model_key}")


def parse_voice_id(voice_id):
    """Estrae (model_key, model_full_id, voice_name) da 'gemini:flash25:Zephyr'.

    Raises ValueError se formato non valido, modello sconosciuto o voce sconosciuta.
    """
    if not _is_gemini_voice(voice_id):
        raise ValueError(f"Invalid Gemini voice ID format: {voice_id!r}")
    parts = voice_id.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid Gemini voice ID format: {voice_id!r} (expected 'gemini:<model>:<voice>')")
    _, model_key, voice_name = parts
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown Gemini model: {model_key!r} (allowed: {list(GEMINI_MODELS.keys())})")
    if voice_name not in GEMINI_VOICE_NAMES:
        raise ValueError(f"Unknown Gemini voice: {voice_name!r}")
    return model_key, _resolve_model_id(model_key), voice_name


# Lingue ufficialmente supportate da Gemini TTS (Google AI Studio docs):
# 24 locali ufficiali + zh-CN legacy (presente da prima della formalizzazione
# del catalogo Google; mantenuto perche` empiricamente funziona).
# Fonte: https://ai.google.dev/gemini-api/docs/speech-generation#languages
SUPPORTED_UI_LANGUAGES = [
    "it", "en", "fr", "es", "de", "pt", "nl", "pl", "ro", "tr",
    "ru", "uk", "ja", "ko", "zh",
    "hi", "ar", "bn", "mr", "ta", "te", "th", "id", "vi",
]
_LANG_LOCALE = {
    "it": "it-IT", "en": "en-US", "fr": "fr-FR", "es": "es-ES",
    "de": "de-DE", "pt": "pt-BR", "nl": "nl-NL", "pl": "pl-PL",
    "ro": "ro-RO", "tr": "tr-TR",
    "ru": "ru-RU", "uk": "uk-UA",
    "ja": "ja-JP", "ko": "ko-KR", "zh": "zh-CN",
    "hi": "hi-IN", "ar": "ar-EG", "bn": "bn-BD", "mr": "mr-IN",
    "ta": "ta-IN", "te": "te-IN", "th": "th-TH",
    "id": "id-ID", "vi": "vi-VN",
}

# Nome lingua leggibile (in inglese) per la direttiva di accento. Gemini TTS
# comprende meglio direttive in linguaggio naturale: indicare la lingua per nome
# ancora l'accento ed evita che chunk diversi (ogni chiamata e' stateless) vengano
# letti con varianti regionali differenti.
LANG_DISPLAY_NAME = {
    "it": "Italian", "en": "English", "fr": "French", "es": "Spanish",
    "de": "German", "pt": "Portuguese", "nl": "Dutch", "pl": "Polish",
    "ro": "Romanian", "tr": "Turkish", "ru": "Russian", "uk": "Ukrainian",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "hi": "Hindi",
    "ar": "Arabic", "bn": "Bengali", "mr": "Marathi", "ta": "Tamil",
    "te": "Telugu", "th": "Thai", "id": "Indonesian", "vi": "Vietnamese",
}

# Catalogo varianti di accento per lingua. Solo le lingue con varianti regionali
# rilevanti hanno piu` di una voce qui (e quindi il selettore UI). Tutte le altre
# vengono comunque ancorate al loro nome lingua (vedi build_accent_directive) per
# eliminare la deriva di accento tra chunk. Ogni entry: (code, descrizione naturale
# inglese per il prompt). Il PRIMO elemento e' il default della lingua.
#
# NB: il frontend (static/js/app.js, _ACCENT_CATALOG) replica le coppie
# lingua->codici per popolare il dropdown. Mantenere i due elenchi allineati.
ACCENT_VARIANTS = {
    "en": [
        ("us", "American English (United States accent)"),
        ("gb", "British English (United Kingdom accent)"),
        ("au", "Australian English"),
        ("in", "Indian English"),
    ],
    "es": [
        ("es", "European Spanish (Castilian, from Spain)"),
        ("419", "Latin American Spanish"),
    ],
    "pt": [
        ("br", "Brazilian Portuguese"),
        ("pt", "European Portuguese (from Portugal)"),
    ],
    "fr": [
        ("fr", "French from France (Metropolitan French)"),
        ("ca", "Canadian French"),
    ],
    "zh": [
        ("cn", "Mandarin Chinese with a Mainland China accent"),
        ("tw", "Mandarin Chinese with a Taiwan accent"),
    ],
    "de": [
        ("de", "Standard German (Hochdeutsch, from Germany)"),
        ("at", "Austrian German"),
        ("ch", "Swiss German accent"),
    ],
    "ar": [
        ("eg", "Egyptian Arabic"),
        ("sa", "Modern Standard Arabic"),
        ("ae", "Gulf Arabic"),
    ],
}


def accent_options(language):
    """Lista [(code, descrizione)] delle varianti di accento per la lingua.

    Restituisce [] per lingue mono-variante (nessun selettore UI). Usato dal
    frontend/diagnostica per sapere se mostrare il dropdown accento.
    """
    lang = (language or "").split("-")[0].lower()
    return list(ACCENT_VARIANTS.get(lang, []))


def default_accent_code(language):
    """Codice accento di default per la lingua (primo del catalogo), o None."""
    opts = accent_options(language)
    return opts[0][0] if opts else None


def build_accent_directive(language, accent_code=None):
    """Direttiva naturale che ancora l'accento di lettura per la lingua data.

    Prefissata (in synthesize) dentro il blocco [style: ...] a OGNI chunk, cosi`
    tutti i chunk condividono lo stesso accento (senza, ogni chiamata stateless
    sceglie una variante regionale diversa -> deriva udibile tra i chunk).

    Per le lingue del catalogo ACCENT_VARIANTS usa la variante richiesta (o il
    default se `accent_code` e' assente/non valido). Per le lingue mono-variante
    note ancora al nome lingua. Restituisce '' per lingue sconosciute (nessun
    ancoraggio possibile).
    """
    lang = (language or "").split("-")[0].lower()
    opts = ACCENT_VARIANTS.get(lang)
    if opts:
        valid = {c: d for c, d in opts}
        code = (accent_code or "").strip().lower()
        if code not in valid:
            code = opts[0][0]  # default lingua
        return f"Read in {valid[code]}, keeping one consistent accent throughout."
    name = LANG_DISPLAY_NAME.get(lang)
    if name:
        return f"Read in {name}, keeping one consistent accent throughout."
    return ""


def get_voices():
    """Catalogo voci Gemini per lingua.

    Le voci Gemini sono multilingue: ogni voce appare sotto ogni lingua UI
    supportata. 30 voci x 2 modelli = 60 entry per lingua.

    Returns:
        dict {lang_code: [voice_entry, ...]}
    """
    out = {}
    # Ordina: prima tutte le Female, poi tutte le Male (per coerenza con
    # l'optgroup label="♀|♂" del combo Edge).
    sorted_names = sorted(
        GEMINI_VOICE_NAMES,
        key=lambda n: (0 if GEMINI_VOICE_GENDER.get(n) == "Female" else 1, n),
    )
    for lang in SUPPORTED_UI_LANGUAGES:
        locale = _LANG_LOCALE.get(lang, lang)
        lang_voices = []
        for model_key, model_info in GEMINI_MODELS.items():
            for voice_name in sorted_names:
                gender = GEMINI_VOICE_GENDER.get(voice_name, "")
                lang_voices.append({
                    "id": f"gemini:{model_key}:{voice_name}",
                    "name": f"{voice_name} ({model_info['label']})",
                    "locale": locale,
                    "engine": "gemini",
                    "model_key": model_key,
                    "model_label": model_info["label"],
                    "gender": gender,
                    "gender_icon": _gender_icon(gender),
                })
        out[lang] = lang_voices
    return out


def _normalize_text(text):
    """Collassa whitespace/newline a singolo spazio e fa strip.

    Necessario perche` len(text) viene usato come proxy del numero di caratteri
    "parlati": senza questa normalizzazione, formattazione (newline tra paragrafi,
    indentazione) gonfia il conteggio e disallinea le stime durata/costo dalle
    stime word-count.
    """
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()


def estimate_input_tokens(text, language="it"):
    """Stima token input dal testo. Usa CHARS_PER_TOKEN_BY_LANG."""
    norm = _normalize_text(text)
    if not norm:
        return 0
    ratio = CHARS_PER_TOKEN_BY_LANG.get(language, CHARS_PER_TOKEN_BY_LANG["default"])
    return int(len(norm) / ratio)


def _rate_pct_to_step(rate_pct):
    """Converte percentuale (-30..+30) o stringa ('+10%') a step intero [-3, +3]."""
    if rate_pct is None or rate_pct == "":
        return 0
    if isinstance(rate_pct, str):
        try:
            rate_pct = int(rate_pct.replace("%", "").replace("+", ""))
        except ValueError:
            return 0
    try:
        n = int(rate_pct)
    except (TypeError, ValueError):
        return 0
    return max(-3, min(3, round(n / 10)))


def estimate_audio_seconds(text, language=None, model_key=None, rate_pct=0, voice=None):
    """Stima durata audio in secondi a una data velocita`.

    Strategia:
      1. Recupera un rate empirico "baseline" (rate_step=0) per (lang, model)
         con fallback a tier-2/3. Questo evita che il rate-step richiesto
         non abbia campioni e produca un risultato invariato rispetto al
         cursore velocità.
      2. Applica un fattore esplicito di velocità ricavato da rate_pct:
            speed_factor = max(0.5, 1 + rate_pct/100)
            audio_seconds = baseline_seconds / speed_factor
         Così la stima è monotonica rispetto allo slider velocità.
    Fallback finale: baseline_rate(language) — il rate mediano misurato per
    quella lingua, non piu` una costante unica.
    Il testo viene normalizzato per coerenza con il conteggio dei sample.
    """
    norm = _normalize_text(text)
    if not norm:
        return 0.0
    rate = None
    if language is not None:
        try:
            # rate_step=0 (baseline): la scalatura su rate_pct la applichiamo
            # esplicitamente sotto per garantire monotonia con lo slider.
            rate = get_empirical_rate(language, model_key, rate_step=0, voice=voice)
        except Exception:
            rate = None
    if not rate or rate <= 0:
        rate = baseline_rate(language)
    base_seconds = len(norm) / rate
    # Converti rate_pct ("+10%", 10, "+0%", ecc.) a fattore moltiplicativo.
    try:
        if isinstance(rate_pct, str):
            rp = int(rate_pct.replace("%", "").replace("+", ""))
        else:
            rp = int(rate_pct) if rate_pct is not None else 0
    except (TypeError, ValueError):
        rp = 0
    rp = max(-50, min(50, rp))
    speed_factor = max(0.5, 1.0 + (rp / 100.0))
    return base_seconds / speed_factor


def estimate_output_tokens(text, language=None, model_key=None, rate_pct=0, voice=None):
    """Stima token audio output. tok/s per-model x secondi stimati."""
    tok_per_sec = _audio_tokens_per_second(model_key)
    return int(estimate_audio_seconds(text, language=language, model_key=model_key,
                                      rate_pct=rate_pct, voice=voice) * tok_per_sec)


def google_cost_breakdown(input_tokens, output_tokens, model_key):
    """Costo Google netto, dettagliato USD/EUR."""
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown model_key: {model_key}")
    m = GEMINI_MODELS[model_key]
    input_usd = input_tokens * m["input_usd_per_mtok"] / 1_000_000
    output_usd = output_tokens * m["output_usd_per_mtok"] / 1_000_000
    total_usd = input_usd + output_usd
    return {
        "input_usd": input_usd,
        "output_usd": output_usd,
        "total_usd": total_usd,
        "total_eur": total_usd * USD_EUR_RATE,
    }


def compute_user_price_eur(google_cost_eur, model_key):
    """Calcola prezzo finale all'utente da costo Google netto.

    Formula:
        base   = google_cost x (1 + margin/100)
        gross  = (base + PAYPAL_FIXED_FEE) / (1 - PAYPAL_PERCENT_FEE/100)
        user_price = round(gross, 2)

    IMPORTANTE - semantica di `margin/100`:
        E` il margine NETTO operatore (cio` che intaschi DOPO la quota PayPal),
        non il ricarico apparente che vede l'utente. Il prezzo finale e` gonfiato
        ulteriormente dalle fee PayPal (gross-up percentuale + fee fissa) che
        ricadono sul cliente. Conseguenza: con `margin=30`, l'utente vede un
        ricarico effettivo di ~39-40% rispetto al costo Google netto (su libri
        lunghi dove la fee fissa e` diluita). Asintoto: user_price/google_cost
        -> (1 + margin/100) / (1 - PAYPAL_PERCENT_FEE/100). Dettagli e tabella
        in md_files/ttsgemini.md §11.1.1.

    Sotto FREE_THRESHOLD_EUR: user_price = 0.0, is_free = True.
    """
    if google_cost_eur < 0:
        raise ValueError("google_cost_eur must be >= 0")
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown model_key: {model_key}")

    margin_pct = get_margin_percent(model_key)
    base_eur = google_cost_eur * (1.0 + margin_pct / 100.0)
    paypal_factor = 1.0 - (PAYPAL_PERCENT_FEE / 100.0)
    if paypal_factor <= 0:
        raise ValueError("PAYPAL_PERCENT_FEE >= 100, invalid config")
    gross = (base_eur + PAYPAL_FIXED_FEE_EUR) / paypal_factor
    user_price = round(gross, 2)
    is_free = user_price < FREE_THRESHOLD_EUR
    return {
        "google_cost_eur": round(google_cost_eur, 4),
        "margin_percent": margin_pct,
        "base_price_eur": round(base_eur, 4),
        "user_price_eur": 0.0 if is_free else user_price,
        "list_price_eur": user_price,
        "is_free": is_free,
        "paypal_fixed_fee_eur": PAYPAL_FIXED_FEE_EUR,
        "paypal_percent_fee": PAYPAL_PERCENT_FEE,
        "free_threshold_eur": FREE_THRESHOLD_EUR,
    }


def estimate_book_cost(chapters, voice_id, language="it", rate_pct=0):
    """Stima costo end-to-end della generazione audio di un libro.

    Args:
        chapters: lista di oggetti con attributo `.text` (es. Chapter dataclass).
        voice_id: deve iniziare con 'gemini:'.
        language: ISO 639-1 (it/en/fr/es/de/zh/hi/...). Default 'it'.

    Returns:
        dict con chars_total, input_tokens_est, audio_seconds_est,
        output_tokens_est, google_cost_eur, user_price_eur, is_free,
        estimated_audio_minutes, model_key, language, model_label.
    """
    model_key, _, voice_name = parse_voice_id(voice_id)

    # Normalizziamo ogni capitolo separatamente per evitare che whitespace/newline
    # gonfino il conteggio caratteri rispetto a word_count*split() usato altrove.
    chars_per_chapter = []
    chars_total = 0
    normalized_parts = []
    for ch in chapters:
        txt = getattr(ch, "text", "") or ""
        norm = _normalize_text(txt)
        chars_per_chapter.append(len(norm))
        chars_total += len(norm)
        normalized_parts.append(norm)

    combined = " ".join(normalized_parts)
    input_tokens = estimate_input_tokens(combined, language)
    audio_seconds = estimate_audio_seconds(combined, language=language, model_key=model_key,
                                           rate_pct=rate_pct, voice=voice_name)
    output_tokens = estimate_output_tokens(combined, language=language, model_key=model_key,
                                           rate_pct=rate_pct, voice=voice_name)

    breakdown = google_cost_breakdown(input_tokens, output_tokens, model_key)
    price = compute_user_price_eur(breakdown["total_eur"], model_key)

    return {
        "chars_total": chars_total,
        "chars_per_chapter": chars_per_chapter,
        "input_tokens_est": input_tokens,
        "audio_seconds_est": audio_seconds,
        "output_tokens_est": output_tokens,
        "google_cost_eur": breakdown["total_eur"],
        "google_cost_breakdown": breakdown,
        "user_price_eur": price["user_price_eur"],
        "list_price_eur": price["list_price_eur"],
        "is_free": price["is_free"],
        "margin_percent": price["margin_percent"],
        "estimated_audio_minutes": audio_seconds / 60.0,
        "model_key": model_key,
        "model_label": GEMINI_MODELS[model_key]["label"],
        "language": language,
        "voice": voice_name,
        "rate_pct": rate_pct,
        "rate_step": _rate_pct_to_step(rate_pct),
    }


# ===========================================================================
# Budget guard — pre-flight job vs cap di spesa (€/giorno e €/job).
# Pensato per Tier 1: in free tier il guard primario è RPD (vedi _check_rpd_cap).
# ===========================================================================

class GeminiBudgetExceeded(RuntimeError):
    """Sollevata quando un nuovo job supererebbe il budget. Il chiamante deve
    intercettare e restituire un messaggio "riprova al reset di mezzanotte UTC"
    o "supera budget per-job, riduci selezione capitoli"."""

    def __init__(self, message, scope, estimated_eur, cap_eur, used_eur=None):
        super().__init__(message)
        self.scope = scope          # 'per_job' | 'daily'
        self.estimated_eur = estimated_eur
        self.cap_eur = cap_eur
        self.used_eur = used_eur


def _daily_budget_eur():
    return _f("ABM_GEMINI_DAILY_BUDGET_EUR", 0.0)  # 0 = disabilitato


def _per_job_budget_eur():
    return _f("ABM_GEMINI_PER_JOB_BUDGET_EUR", 0.0)  # 0 = disabilitato


def _budget_alert_pct():
    return _i("ABM_GEMINI_BUDGET_ALERT_PCT", 80)


def _budget_hard_stop():
    return _b("ABM_GEMINI_BUDGET_HARD_STOP", True)


# -- Atomic budget reservation -----------------------------------------------
# Concurrency: preflight_budget_check legge get_daily_spent_eur() dal JSONL
# audit, ma il cost viene scritto solo a fine job. Due job concorrenti vedono
# lo stesso "spent" e possono entrambi passare preflight superando il cap
# combinato. La reservation in-memory chiude la finestra di race.
import threading as _threading_budget
_active_reservations: dict = {}            # job_id -> reserved_eur
_reservations_lock = _threading_budget.Lock()


def reserve_budget(job_id, estimated_cost_eur):
    """Atomicamente verifica + riserva budget per un job. Solleva
    GeminiBudgetExceeded se il cap verrebbe sforato considerando lo speso
    odierno + le reservation attive di altri job.

    Idempotente per job_id: chiamata ripetuta aggiorna senza sommare.
    """
    if estimated_cost_eur is None or estimated_cost_eur < 0:
        return
    daily = _daily_budget_eur()
    if daily <= 0:
        return  # cap disabilitato, niente da riservare
    hard = _budget_hard_stop()
    with _reservations_lock:
        spent = get_daily_spent_eur()
        # Escludi la reservation di questo stesso job (idempotenza)
        other_reserved = sum(
            float(v or 0) for k, v in _active_reservations.items() if k != job_id
        )
        projected = spent + other_reserved + estimated_cost_eur
        if projected > daily:
            if hard:
                raise GeminiBudgetExceeded(
                    f"Job would push daily spend to {projected:.2f} EUR "
                    f"(cap {daily:.2f} EUR, spent {spent:.2f} EUR, "
                    f"reserved by others {other_reserved:.2f} EUR)",
                    scope="daily",
                    estimated_eur=estimated_cost_eur,
                    cap_eur=daily,
                    used_eur=spent,
                )
            # soft mode: registra comunque per visibilità
        _active_reservations[job_id] = float(estimated_cost_eur)


def release_reservation(job_id):
    """Rilascia la reservation di un job (chiamare a fine job, dopo che il
    cost è stato scritto nel JSONL audit, oppure su cancel/refund)."""
    with _reservations_lock:
        _active_reservations.pop(job_id, None)


def get_daily_spent_eur():
    """Spesa Google del giorno corrente in EUR (UTC). Aggrega l'audit log
    gemini_cost_audit_YYYY-MM.jsonl filtrando per data odierna. Cade su 0
    se il file non esiste / non leggibile (graceful)."""
    if _data_dir is None:
        return 0.0
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month = _current_month()
    audit_file = _data_dir / f"gemini_cost_audit_{month}.jsonl"
    if not audit_file.exists():
        return 0.0
    spent = 0.0
    try:
        with audit_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = rec.get("ts", "")
                if not ts.startswith(today_iso):
                    continue
                spent += float(rec.get("google_cost_eur_actual", 0.0) or 0.0)
    except Exception as e:
        print(f"[gemini-tts] get_daily_spent_eur failed: {e}")
        return 0.0
    return spent


def preflight_budget_check(estimated_cost_eur):
    """Verifica che un job da `estimated_cost_eur` EUR possa partire.

    Solleva GeminiBudgetExceeded(scope='per_job') se sopra il cap singolo,
    GeminiBudgetExceeded(scope='daily') se sommato allo speso di oggi supera
    il cap giornaliero. Se `BUDGET_HARD_STOP` è False, fa solo un log warning
    e NON blocca (utile in dev/admin con cap conservativi per allarmi).
    """
    if estimated_cost_eur is None or estimated_cost_eur < 0:
        return {"ok": True, "warning": None}
    per_job = _per_job_budget_eur()
    daily = _daily_budget_eur()
    spent = get_daily_spent_eur() if daily > 0 else 0.0
    alert_pct = _budget_alert_pct()
    hard = _budget_hard_stop()
    warning = None

    # Per-job
    if per_job > 0 and estimated_cost_eur > per_job:
        msg = (f"Job estimated cost {estimated_cost_eur:.2f} € exceeds "
               f"per-job cap {per_job:.2f} €")
        if hard:
            raise GeminiBudgetExceeded(msg, scope="per_job",
                                       estimated_eur=estimated_cost_eur,
                                       cap_eur=per_job)
        warning = msg

    # Daily
    if daily > 0:
        projected = spent + estimated_cost_eur
        if projected > daily:
            msg = (f"Job would push daily spend to {projected:.2f} € (cap {daily:.2f} €, "
                   f"already spent {spent:.2f} €)")
            if hard:
                raise GeminiBudgetExceeded(msg, scope="daily",
                                           estimated_eur=estimated_cost_eur,
                                           cap_eur=daily, used_eur=spent)
            warning = msg
        elif projected > daily * alert_pct / 100.0:
            warning = (f"[alert] Daily spend will reach "
                       f"{projected:.2f}/{daily:.2f} € ({projected/daily*100:.0f}%)")
            print(f"[gemini-tts] {warning}")

    return {"ok": True, "warning": warning, "spent_eur": spent,
            "estimated_eur": estimated_cost_eur,
            "daily_cap_eur": daily, "per_job_cap_eur": per_job}


def check_text_byte_size(text):
    """Verifica che il testo stia nel target QUALITA` MAX_BYTES_PER_CALL (UTF-8).

    NB: MAX_BYTES_PER_CALL e` un target QUALITA` soft sul TESTO PURO (oltre
    quella soglia Gemini TTS degrada acusticamente), NON un hard cap API.
    L'hard cap API sul payload completo (testo + prefissi) e` API_HARD_BYTES_CAP.
    Chi chiama decide se trattare ok=False come errore o solo come warning.

    Returns:
        (ok: bool, size_bytes: int)
    """
    if not text:
        return True, 0
    size = len(text.encode("utf-8"))
    return size <= MAX_BYTES_PER_CALL, size


def get_max_chunk_chars(language):
    """Max chars per chunk per la lingua data.

    Default: DEFAULT_CHUNK_CHARS (700) — chunk piccoli per stabilita` acustica.
    Override per-lingua ABM_GEMINI_MAX_CHUNK_CHARS_<LANG_UPPER> ha precedenza
    sull'override globale ABM_GEMINI_CHUNK_CHARS.
    """
    if language:
        env_specific = os.environ.get(f"ABM_GEMINI_MAX_CHUNK_CHARS_{language.upper()}")
        if env_specific:
            try:
                return int(env_specific)
            except ValueError:
                pass
    return DEFAULT_CHUNK_CHARS


_data_dir = None
_usage_file_path = None
_usage_lock = threading.Lock()
_usage_cache = None


def init(data_dir):
    """Inizializza il modulo con la directory dati persistente."""
    global _data_dir, _usage_file_path, _usage_cache, _preview_file_path, _preview_cache
    global _rpd_file_path, _rpd_cache, _admin_state_path
    _data_dir = Path(data_dir)
    _data_dir.mkdir(parents=True, exist_ok=True)
    _usage_file_path = _data_dir / "gemini_tts_usage.json"
    _usage_cache = None
    _preview_file_path = None
    _preview_cache = None
    _rpd_file_path = _data_dir / "gemini_tts_rpd.json"
    _rpd_cache = None
    _admin_state_path = _data_dir / "gemini_admin_state.json"
    _load_admin_state()


# ---------------------------------------------------------------------------
# Kill-switch amministrativo (disattivazione runtime delle voci PREMIUM)
# ---------------------------------------------------------------------------
# Persistito in ABM_DATA_DIR/gemini_admin_state.json + mirror in-memory.
# Controllato in cima a is_available(): se disabled=True, le voci PREMIUM
# non vengono offerte agli utenti (UI /api/voices non le include, endpoint
# di stima e pagamento Premium rispondono 503).

_admin_state_path = None  # type: ignore[assignment]
_admin_disabled = False
_admin_disabled_reason = ""
_admin_disabled_at = ""
_admin_state_lock = threading.Lock()


def _load_admin_state():
    """Legge lo stato kill-switch da disco al boot/init."""
    global _admin_disabled, _admin_disabled_reason, _admin_disabled_at
    if _admin_state_path is None:
        return
    try:
        with open(_admin_state_path, "r", encoding="utf-8") as f:
            d = json.load(f)
        _admin_disabled = bool(d.get("disabled", False))
        _admin_disabled_reason = str(d.get("reason", "") or "")
        _admin_disabled_at = str(d.get("updated_at", "") or "")
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        _admin_disabled = False
        _admin_disabled_reason = ""
        _admin_disabled_at = ""
    # Log LOUD a boot quando il kill-switch risulta attivo da disco: se lo
    # stato e' stantio (write fallita in passato, es. disco pieno — incidente
    # 2026-06) questo e' l'unico segnale visibile del perche' le voci PREMIUM
    # sono spente e ogni synthesize() fallira' istantaneamente.
    if _admin_disabled:
        print(f"[gemini-tts] BOOT: kill-switch ATTIVO da disco — voci PREMIUM "
              f"DISABILITATE (reason={_admin_disabled_reason!r}, "
              f"updated_at={_admin_disabled_at}). Se non atteso, riattivare "
              f"da /admin/audit-premium.", flush=True)


def is_capability_available():
    """True se Gemini TTS e' tecnicamente configurato, ignorando il
    kill-switch admin. Usato dalla diagnostica admin per distinguere
    'spento per scelta' da 'non configurato'.
    """
    global _available
    if _available is not None:
        return _available
    with _available_lock:
        if _available is not None:
            return _available
        # Scelta deliberata (non una dimenticanza): questo e' un check GLOBALE
        # "Gemini TTS e' configurato per almeno un modello?", non legato a una
        # voce specifica. Risolve percio' sotto _BACKEND_DEFAULT_KEY, che non
        # puo' mai selezionare Cloudflare (opt-in solo per modello). Un setup
        # Cloudflare-only senza Vertex/API-key configurati risulta qui "non
        # disponibile" e NON puo' sintetizzare: synthesize() apre con
        # `if not is_available(): raise GeminiUnavailable`, quindi la
        # risoluzione per-modello piu' avanti non viene mai raggiunta.
        # (La versione precedente di questo commento affermava il contrario:
        # era falsa e induceva a credere supportata una configurazione che non
        # lo e' — rilievo m2 della review finale.) Cloudflare richiede quindi
        # Vertex o una API key configurati, che servono comunque come
        # destinazione del failover del breaker.
        # _BACKEND_DEFAULT_KEY passato ESPLICITO (non omesso): la scelta deve
        # essere grep-abile nel codice, non solo spiegata in un commento
        # (rilievo M2, fix-1) — cosi' un futuro terzo chiamante model-unaware
        # non puo' "dimenticarsi" di essere implicito.
        backend = _resolve_backend(_BACKEND_DEFAULT_KEY)
        if backend is None:
            _available = False
            return False
        try:
            from google import genai  # noqa: F401
            _available = True
            return True
        except ImportError:
            _available = False
            return False


def admin_disabled_state():
    """Snapshot dello stato kill-switch (disabled/reason/updated_at)."""
    return {
        "disabled": bool(_admin_disabled),
        "reason": _admin_disabled_reason,
        "updated_at": _admin_disabled_at,
    }


def set_admin_disabled(disabled, reason=""):
    """Imposta il kill-switch e lo persiste. Thread-safe.

    Non resetta la cache di capability detection: la cache governa solo
    "Gemini e' tecnicamente configurabile?"; il kill-switch e' un livello
    sopra e viene controllato in cima a is_available().
    """
    global _admin_disabled, _admin_disabled_reason, _admin_disabled_at
    persisted = False
    with _admin_state_lock:
        _admin_disabled = bool(disabled)
        _admin_disabled_reason = (reason or "")[:200]
        _admin_disabled_at = datetime.now(timezone.utc).isoformat()
        if _admin_state_path is not None:
            # Retry con backoff + verifica: una write fallita (es. disco pieno)
            # lascia su disco lo stato PRECEDENTE, che un restart ricarica
            # silenziosamente (incidente 2026-06: 'enabled' non persistito →
            # boot con kill-switch stantio → job silenziato al 100%).
            _last_err = None
            for _attempt in range(3):
                try:
                    _admin_state_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(_admin_state_path, "w", encoding="utf-8") as f:
                        json.dump({
                            "disabled": _admin_disabled,
                            "reason": _admin_disabled_reason,
                            "updated_at": _admin_disabled_at,
                        }, f, ensure_ascii=False, indent=2)
                    # Verifica re-leggendo: write su disco pieno puo' troncare.
                    with open(_admin_state_path, "r", encoding="utf-8") as f:
                        _check = json.load(f)
                    if bool(_check.get("disabled")) == _admin_disabled:
                        persisted = True
                        break
                    _last_err = ValueError("re-read mismatch after write")
                except (OSError, json.JSONDecodeError, ValueError) as e:
                    _last_err = e
                if _attempt < 2:
                    time.sleep(0.2 * (_attempt + 1))
            if not persisted:
                print(f"[gemini-tts] ERROR: kill-switch state NOT persisted "
                      f"after 3 attempts ({_last_err}) — lo stato in memoria "
                      f"e' {'DISABLED' if _admin_disabled else 'ENABLED'} ma "
                      f"su disco resta quello precedente: un restart lo "
                      f"ripristinera'. Liberare spazio disco e ripetere "
                      f"l'operazione dal pannello admin.", flush=True)
    state = admin_disabled_state()
    state["persisted"] = persisted
    return state


def _current_month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _empty_usage():
    return {
        "month": _current_month(),
        "chars_total": 0,
        "input_tokens_total": 0,
        "output_tokens_total": 0,
        # google_cost_eur: somma costi REALI calcolati da usage_metadata.token_count
        # (input+output) x rate per MTok del modello. Aggregato chunk-per-chunk.
        "google_cost_eur": 0.0,
        "user_revenue_eur_net": 0.0,
        "margin_eur": 0.0,
        "previews_count": 0,
        "previews_cost_eur": 0.0,
        # Reconciliation ex-ante (estimate_book_cost) vs ex-post (usage_metadata
        # reale). Aggiornata a fine job da record_job_completion().
        "jobs_completed": 0,
        "estimated_cost_eur_total": 0.0,
        "actual_cost_eur_total": 0.0,
        "cost_delta_eur_total": 0.0,    # actual - estimated (positivo = sottostima)
        "cost_delta_pct_sum": 0.0,      # somma dei delta% per calcolo media
        "by_model": {
            "flash25": {"chars": 0, "input_tok": 0, "output_tok": 0,
                        "google_cost": 0.0, "revenue_net": 0.0, "jobs_count": 0,
                        "estimated_eur": 0.0, "actual_eur": 0.0},
            "flash31": {"chars": 0, "input_tok": 0, "output_tok": 0,
                        "google_cost": 0.0, "revenue_net": 0.0, "jobs_count": 0,
                        "estimated_eur": 0.0, "actual_eur": 0.0},
        },
    }


def _ensure_reconciliation_fields(data):
    """Migra usage data legacy aggiungendo i campi reconciliation se mancanti.

    Permette di leggere file gemini_tts_usage.json scritti prima dell'introduzione
    della reconciliation senza perdere i totali storici (chars/tokens/cost).
    """
    data.setdefault("jobs_completed", 0)
    data.setdefault("estimated_cost_eur_total", 0.0)
    data.setdefault("actual_cost_eur_total", 0.0)
    data.setdefault("cost_delta_eur_total", 0.0)
    data.setdefault("cost_delta_pct_sum", 0.0)
    by_model = data.get("by_model") or {}
    for mk in ("flash25", "flash31"):
        m = by_model.setdefault(mk, {})
        m.setdefault("chars", 0)
        m.setdefault("input_tok", 0)
        m.setdefault("output_tok", 0)
        m.setdefault("google_cost", 0.0)
        m.setdefault("revenue_net", 0.0)
        m.setdefault("jobs_count", 0)
        m.setdefault("estimated_eur", 0.0)
        m.setdefault("actual_eur", 0.0)
    return data


def _load_usage():
    global _usage_cache
    if _usage_cache is not None:
        return _usage_cache
    if _usage_file_path is None:
        return _empty_usage()
    if _usage_file_path.exists():
        try:
            data = json.loads(_usage_file_path.read_text(encoding="utf-8"))
            if data.get("month") == _current_month():
                data = _ensure_reconciliation_fields(data)
                _usage_cache = data
                return data
        except Exception as e:
            print(f"[gemini-tts] Warning: could not read usage file: {e}")
    data = _empty_usage()
    _usage_cache = data
    return data


def _save_usage(data):
    global _usage_cache
    _usage_cache = data
    if _usage_file_path is None:
        return
    try:
        _atomic_write_json(_usage_file_path, data, ensure_ascii=True, indent=2)
    except Exception as e:
        print(f"[gemini-tts] Warning: could not save usage file: {e}")


def record_usage(model_key, chars, input_tokens, output_tokens, google_cost_eur, revenue_eur):
    """Registra l'utilizzo di un job completato. Aggiorna anche aggregati globali."""
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown model_key: {model_key}")
    with _usage_lock:
        data = _load_usage()
        data["chars_total"] += chars
        data["input_tokens_total"] += input_tokens
        data["output_tokens_total"] += output_tokens
        data["google_cost_eur"] += google_cost_eur
        data["user_revenue_eur_net"] += revenue_eur
        data["margin_eur"] = data["user_revenue_eur_net"] - data["google_cost_eur"]
        m = data["by_model"][model_key]
        m["chars"] += chars
        m["input_tok"] += input_tokens
        m["output_tok"] += output_tokens
        m["google_cost"] += google_cost_eur
        m["revenue_net"] += revenue_eur
        m["jobs_count"] += 1
        _save_usage(data)


def record_job_completion(model_key, estimated_eur, actual_eur, user_price_eur=0.0):
    """Registra la chiusura di un job: stima ex-ante vs costo reale ex-post.

    Da chiamare una sola volta a fine job (success o cancel parziale), DOPO che
    tutti i chunk hanno gia` chiamato record_usage(). Tiene traccia dell'errore
    sistematico di estimate_book_cost rispetto ai token reali di usage_metadata.

    Args:
        model_key: 'flash25' | 'flash31'
        estimated_eur: costo Google stimato pre-job (da estimate_book_cost)
        actual_eur: costo Google REALE (somma chunk usage_metadata x rate)
        user_price_eur: prezzo pagato dall'utente (se 0 = job gratuito o ignoto)
    """
    if model_key not in GEMINI_MODELS:
        raise ValueError(f"Unknown model_key: {model_key}")
    try:
        est = float(estimated_eur or 0.0)
        act = float(actual_eur or 0.0)
        rev = float(user_price_eur or 0.0)
    except (TypeError, ValueError):
        return
    delta_eur = act - est
    delta_pct = (delta_eur / est * 100.0) if est > 0 else 0.0
    with _usage_lock:
        data = _load_usage()
        data["jobs_completed"] += 1
        data["estimated_cost_eur_total"] += est
        data["actual_cost_eur_total"] += act
        data["cost_delta_eur_total"] += delta_eur
        data["cost_delta_pct_sum"] += delta_pct
        if rev > 0:
            data["user_revenue_eur_net"] += rev
            data["margin_eur"] = data["user_revenue_eur_net"] - data["google_cost_eur"]
        m = data["by_model"][model_key]
        m["estimated_eur"] += est
        m["actual_eur"] += act
        if rev > 0:
            m["revenue_net"] += rev
        _save_usage(data)


def get_usage():
    """Restituisce lo snapshot di utilizzo del mese corrente."""
    with _usage_lock:
        data = dict(_load_usage())
        # Campo derivato: media percentuale errore stima.
        jobs = data.get("jobs_completed", 0) or 0
        data["cost_delta_pct_avg"] = (
            round(data.get("cost_delta_pct_sum", 0.0) / jobs, 2) if jobs > 0 else 0.0
        )
        return data


_preview_file_path = None
_preview_lock = threading.Lock()
_preview_cache = None


def _preview_path():
    global _preview_file_path
    if _preview_file_path is None and _data_dir is not None:
        _preview_file_path = _data_dir / "gemini_tts_previews.json"
    return _preview_file_path


def _load_previews():
    global _preview_cache
    if _preview_cache is not None:
        return _preview_cache
    p = _preview_path()
    if p and p.exists():
        try:
            _preview_cache = json.loads(p.read_text(encoding="utf-8"))
            return _preview_cache
        except Exception:
            pass
    _preview_cache = {}
    return _preview_cache


def _save_previews(data):
    global _preview_cache
    _preview_cache = data
    p = _preview_path()
    if p is None:
        return
    try:
        _atomic_write_json(p, data, ensure_ascii=True)
    except Exception as e:
        print(f"[gemini-tts] Warning: could not save previews file: {e}")


def _maybe_reset_cookie(entry, now):
    """Resetta il counter se il primo timestamp ha superato la finestra rolling."""
    window_start = entry.get("window_start_ts", 0)
    if now - window_start >= PREVIEW_WINDOW_SECONDS:
        entry["count"] = 0
        entry["window_start_ts"] = now
    return entry


def check_preview_cap(cookie_id):
    """Stato corrente del cap preview per il cookie. Non incrementa.

    Returns: (count_in_window, remaining, window_reset_ts)
    """
    cap = PREVIEW_CAP_PER_DAY
    now = time.time()
    with _preview_lock:
        data = _load_previews()
        entry = dict(data.get(cookie_id, {"count": 0, "window_start_ts": now}))
        entry = _maybe_reset_cookie(entry, now)
        count = entry["count"]
        remaining = max(0, cap - count)
        reset_ts = entry["window_start_ts"] + PREVIEW_WINDOW_SECONDS
        return count, remaining, int(reset_ts)


def increment_preview(cookie_id):
    """Incrementa il counter se sotto cap. Restituisce True se ok, False se cap raggiunto."""
    cap = PREVIEW_CAP_PER_DAY
    now = time.time()
    with _preview_lock:
        data = _load_previews()
        entry = data.get(cookie_id, {"count": 0, "window_start_ts": now})
        entry = _maybe_reset_cookie(entry, now)
        if entry["count"] >= cap:
            data[cookie_id] = entry
            _save_previews(data)
            return False
        entry["count"] += 1
        data[cookie_id] = entry
        _save_previews(data)
        return True


# ───────────────── Empirical rate log (chars/sec per lang+model) ─────────────────
#
# Ad ogni sintesi reale registriamo (chars_normalizzati, audio_secs_reali, lang,
# model). La media mobile sugli ultimi N campioni per (lang, model) diventa il
# rate usato dalle stime. Cosi` le stime ex-ante migliorano automaticamente man
# mano che l'app viene usata e si tarano per ogni lingua.

_rate_log_path = None
_rate_log_lock = threading.Lock()
_rate_log_cache = None

RATE_LOG_MAX_SAMPLES = int(_f("ABM_GEMINI_RATE_LOG_MAX_SAMPLES", 6000))

# Finestra e soglia minima hanno un PAVIMENTO non aggirabile da env. Con la
# vecchia finestra di 20 campioni il prezzo di un'intera lingua era deciso dagli
# ultimi 20 chunk dell'ultimo libro generato: il 2026-08-19 quei 20 campioni
# venivano tutti dallo stesso job (voce Algieba, 6 minuti di generazione) e
# hanno spostato il preventivo di un altro libro da 69,26 a 82,82 EUR.
RATE_LOG_WINDOW_FLOOR = 200
RATE_LOG_MIN_SAMPLES_FLOOR = 20
RATE_LOG_WINDOW = max(RATE_LOG_WINDOW_FLOOR, int(_f("ABM_GEMINI_RATE_LOG_WINDOW", 800)))
RATE_LOG_MIN_SAMPLES = max(RATE_LOG_MIN_SAMPLES_FLOOR, int(_f("ABM_GEMINI_RATE_LOG_MIN_SAMPLES", 40)))

# Nessun singolo job puo` occupare piu` di questa quota della finestra: un
# audiolibro lungo produce migliaia di chunk e da solo riscriverebbe il rate
# di tutta la lingua.
RATE_LOG_MAX_PER_JOB = int(_f("ABM_GEMINI_RATE_LOG_MAX_PER_JOB", 60))

# Frazione di code scartata prima di calcolare il rate (outlier bidirezionale).
RATE_LOG_TRIM_FRACTION = 0.10


def _rate_log_file():
    global _rate_log_path
    if _rate_log_path is None and _data_dir is not None:
        _rate_log_path = _data_dir / "gemini_tts_rate_log.json"
    return _rate_log_path


def _load_rate_log():
    global _rate_log_cache
    if _rate_log_cache is not None:
        return _rate_log_cache
    p = _rate_log_file()
    if p and p.exists():
        try:
            _rate_log_cache = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(_rate_log_cache, dict) or "samples" not in _rate_log_cache:
                _rate_log_cache = {"samples": []}
            return _rate_log_cache
        except Exception:
            pass
    _rate_log_cache = {"samples": []}
    return _rate_log_cache


def _save_rate_log(data):
    global _rate_log_cache
    _rate_log_cache = data
    p = _rate_log_file()
    if p is None:
        return
    try:
        _atomic_write_json(p, data, ensure_ascii=True)
    except Exception as e:
        print(f"[gemini-tts] Warning: could not save rate log: {e}")


def record_rate_sample(chars, audio_seconds, lang, model_key, rate_pct=0,
                       voice=None, job_id=None):
    """Registra un campione (chars_normalizzati, audio_seconds, lang, voce, rate).

    `voice` e `job_id` sono opzionali per retrocompatibilita`, ma vanno passati
    sempre dai call site reali: la voce e` la chiave di raggruppamento piu`
    fine usata da `get_empirical_rate`, il job serve a impedire che un singolo
    audiolibro monopolizzi la finestra (vedi RATE_LOG_MAX_PER_JOB).

    Scarta campioni degeneri (chars<=0, audio_seconds<=0.5, rate fuori range
    plausibile 2-40 char/sec) per non avvelenare la media empirica con outlier
    derivati da chunk troppo corti o da errori di misurazione. Il minimo e` 2 e
    non 5 perche` il cinese viaggia a ~4 char/sec: con la soglia precedente
    tutti i campioni zh venivano buttati e la lingua restava senza dati.
    """
    try:
        chars = int(chars)
        audio_seconds = float(audio_seconds)
    except (TypeError, ValueError):
        return
    if chars <= 0 or audio_seconds <= 0.5:
        return
    inst_rate = chars / audio_seconds
    if inst_rate < 2.0 or inst_rate > 40.0:
        return
    sample = {
        "chars": chars,
        "secs": round(audio_seconds, 3),
        "lang": (lang or "default")[:8],
        "model": model_key or "unknown",
        "voice": (voice or "")[:32],
        "job": (job_id or "")[:24],
        "rate_step": _rate_pct_to_step(rate_pct),
        "ts": int(time.time()),
    }
    with _rate_log_lock:
        data = _load_rate_log()
        samples = data.get("samples", [])
        samples.append(sample)
        if len(samples) > RATE_LOG_MAX_SAMPLES:
            samples = samples[-RATE_LOG_MAX_SAMPLES:]
        data["samples"] = samples
        _save_rate_log(data)


def _rate_from_samples(filtered, win, minN):
    """Rate char/sec robusto da una lista di campioni gia` filtrata.

    1. prende gli ultimi `win` campioni;
    2. limita a RATE_LOG_MAX_PER_JOB i campioni provenienti dallo stesso job
       (i piu` recenti), cosi` un audiolibro da 4000 chunk non riscrive da solo
       il rate della lingua;
    3. scarta le code (RATE_LOG_TRIM_FRACTION per lato) sul rate istantaneo;
    4. ritorna il rapporto pesato sui caratteri, che e` lo stesso estimando
       usato per calibrare LANG_BASELINE_RATE (chars_totali/secondi_totali).

    Ritorna None se restano meno di `minN` campioni.
    """
    last = filtered[-win:] if win and win > 0 else list(filtered)
    if len(last) < minN:
        return None

    # Cap per job, conservando i campioni piu` recenti di ciascuno.
    per_job = {}
    kept = []
    for s in reversed(last):
        jid = s.get("job") or ""
        if jid:
            n = per_job.get(jid, 0)
            if n >= RATE_LOG_MAX_PER_JOB:
                continue
            per_job[jid] = n + 1
        kept.append(s)
    if len(kept) < minN:
        # Il cap ha svuotato troppo la finestra (tipico quando quasi tutti i
        # campioni vengono da un job solo): meglio usarli tutti che ripiegare
        # su un tier piu` largo e meno pertinente.
        kept = list(last)

    rates = []
    for s in kept:
        c = s.get("chars", 0)
        sec = s.get("secs", 0.0)
        if c > 0 and sec > 0:
            rates.append((c / sec, c, sec))
    if len(rates) < minN:
        return None
    rates.sort(key=lambda t: t[0])
    cut = int(len(rates) * RATE_LOG_TRIM_FRACTION)
    core = rates[cut:len(rates) - cut] if cut and len(rates) - 2 * cut >= minN // 2 else rates
    total_chars = sum(t[1] for t in core)
    total_secs = sum(t[2] for t in core)
    if total_secs <= 0:
        return None
    return total_chars / total_secs


def get_empirical_rate(lang, model_key=None, rate_step=0, window=None,
                       min_samples=None, voice=None):
    """Rate empirico char/sec per (lingua, voce, velocita`), con clamp.

    Tier di fallback, dal piu` specifico al piu` largo:
      1. (lang, voice, rate_step) — la combinazione che conta davvero
      2. (lang, rate_step)        — qualsiasi voce, stessa velocita`
      3. (lang, rate_step=0)      — baseline della lingua a velocita` normale

    Due differenze sostanziali rispetto alla versione precedente:

    * **il modello non entra nella chiave**. Sui 256 job reali di giu-ago 2026
      flash25 e flash31 hanno la stessa mediana (13.96 vs 14.03) e il modello
      spiega lo 0.4% della varianza del rate: raggruppare per modello dimezzava
      la numerosita` dei gruppi senza guadagno predittivo. Contano lingua (36%
      della varianza), velocita` (24%) e voce (11%).
    * **campioni con rate_step diverso non vengono mai mescolati**. Il vecchio
      tier 2 ignorava rate_step, quindi un preventivo a velocita` normale poteva
      finire calcolato su campioni presi a +10% (15.8 char/sec contro 13.8).

    Il risultato e` sempre limitato alla banda
    [RATE_CLAMP_LOW, RATE_CLAMP_HIGH] x baseline_rate(lang).
    Ritorna None se nemmeno il tier piu` largo ha `min_samples` campioni.
    """
    if not lang:
        return None
    win = window if window is not None else RATE_LOG_WINDOW
    minN = min_samples if min_samples is not None else RATE_LOG_MIN_SAMPLES
    with _rate_log_lock:
        samples = list(_load_rate_log().get("samples", []))
    if not samples:
        return None

    def _step(s):
        return s.get("rate_step", 0)

    same_lang_step = [s for s in samples
                      if s.get("lang") == lang and _step(s) == rate_step]

    rate = None
    if voice:
        rate = _rate_from_samples([s for s in same_lang_step
                                   if s.get("voice") == voice], win, minN)
    if rate is None:
        rate = _rate_from_samples(same_lang_step, win, minN)
    if rate is None and rate_step != 0:
        rate = _rate_from_samples([s for s in samples
                                   if s.get("lang") == lang and _step(s) == 0],
                                  win, minN)
    if rate is None or rate <= 0:
        return None

    base = baseline_rate(lang)
    lo, hi = base * RATE_CLAMP_LOW, base * RATE_CLAMP_HIGH
    if rate < lo or rate > hi:
        clamped = min(hi, max(lo, rate))
        print(f"[gemini-tts] rate empirico {rate:.2f} fuori banda per "
              f"lang={lang} voice={voice or '-'} step={rate_step} "
              f"(baseline {base:.2f}) -> uso {clamped:.2f}")
        return clamped
    return rate


_available = None
_available_lock = threading.Lock()
_clients_by_location = {}


def is_available():
    """True se un backend Gemini TTS valido e' configurato e google-genai e' installato.

    Backend ammessi:
    - Vertex AI:  ABM_GCP_PROJECT_ID + ABM_GOOGLE_CREDENTIALS_FILE (file leggibile).
    - API key:    ABM_GEMINI_API_KEY non vuota.
    - Cloudflare: ABM_CF_ACCOUNT_ID + ABM_CF_API_TOKEN, solo opt-in esplicito e
      solo per i modelli con `id_cloudflare` (auto non lo seleziona mai).
    Selettore esplicito:
    ABM_GEMINI_BACKEND=vertex|apikey|cloudflare|auto (default: auto).

    ATTENZIONE — Cloudflare non e' usabile da solo. Questo check e' globale e
    risolve sotto _BACKEND_DEFAULT_KEY, che non puo' mai selezionare Cloudflare
    (opt-in solo per modello): una macchina con le sole credenziali Cloudflare
    ritorna False e synthesize() solleva GeminiUnavailable. Servono comunque
    Vertex o una API key configurati — Vertex e' anche l'unica destinazione del
    failover del breaker, quindi la dipendenza non e' eliminabile. Da tenere
    presente nella procedura di accensione di Cloudflare.

    Override admin: se il kill-switch e' attivo (vedi set_admin_disabled),
    ritorna sempre False indipendentemente dalla capability detection,
    cosi` le voci PREMIUM non vengono offerte agli utenti.
    """
    if _admin_disabled:
        return False
    global _available
    if _available is not None:
        return _available
    with _available_lock:
        if _available is not None:
            return _available

        # Stesso limite deliberato di is_capability_available(): check globale
        # non legato a un modello, quindi risolto sotto _BACKEND_DEFAULT_KEY e
        # incapace di vedere Cloudflare. synthesize() risolve il backend vero
        # per modello piu' avanti (_resolve_backend(model_key)); qui basta
        # sapere se ESISTE un modo di parlare con Gemini.
        # _BACKEND_DEFAULT_KEY esplicito, non omesso (rilievo M2, fix-1): vedi
        # commento gemello in is_capability_available().
        backend = _resolve_backend(_BACKEND_DEFAULT_KEY)
        if backend is None:
            _available = False
            print("[gemini-tts] Disabled: no backend configured "
                  "(set ABM_GEMINI_BACKEND + relative env)")
            return False

        try:
            from google import genai  # noqa: F401
            _available = True
            print(f"[gemini-tts] Enabled (backend={backend})")
            return True
        except ImportError:
            _available = False
            print("[gemini-tts] Disabled: google-genai not installed. Run: pip install google-genai")
            return False


def _http_timeout_ms(model_key=None):
    """Timeout HTTP per le call al Gemini API (millisecondi).

    `flash31` (gemini-3.1-flash-tts-preview) e` strutturalmente piu` lento
    di `flash25`: RPM cap inferiore (3/300 vs 10/750) + audio gen piu`
    lenta lato Google. Con il default 25s i chunk normali finiscono in
    504 DEADLINE_EXCEEDED, saturano i 3 retry e producono silenzio. Per
    flash31 il default sale a 60s; flash25 resta a 25s per preservare il
    fast-fail su stall reali. Override via env per-modello.
    """
    if model_key == "flash31":
        return _i("ABM_GEMINI_HTTP_TIMEOUT_MS_FLASH31", 60000)
    return _i("ABM_GEMINI_HTTP_TIMEOUT_MS", 25000)


def _cf_timeout_ms():
    """Timeout HTTP (ms) per le call al backend Cloudflare Workers AI."""
    try:
        return max(1000, int(os.environ.get("ABM_CF_TIMEOUT_MS", "60000") or 60000))
    except (TypeError, ValueError):
        return 60000


def _make_genai_client(**kwargs):
    """Wrapper attorno a genai.Client() — seam isolato per i test.

    Tutti i kwargs vengono passati al costruttore reale del client.
    """
    from google import genai
    return genai.Client(**kwargs)


def _get_client(model_key=None):
    """Lazy init del client google-genai, cached per location.

    Vertex: il client e' tied a (project, location); flash25 e flash31
    possono finire su region diverse, quindi servono client distinti.
    API key: location e' ignorato, una sola entry "_apikey" nella cache.
    """
    from google.genai import types as _gt
    # model_key propagato (rilievo task-7): _get_client e' sempre chiamato con
    # un modello noto (da _vertex_transport_call o dai test), quindi risolvere
    # sotto _BACKEND_DEFAULT_KEY qui sarebbe un difetto silenzioso, non una
    # scelta - il client Vertex creato dipende dalla location per-modello.
    backend = _resolve_backend(model_key)
    if backend is None:
        raise RuntimeError("Gemini TTS not available (no backend configured)")

    if backend == "apikey":
        cache_key = "_apikey"
    else:
        # Vertex: cache per location (model_key obbligatorio per risolverla).
        if model_key is None:
            raise ValueError("_get_client(): model_key richiesto su backend Vertex")
        cache_key = ("vertex", _resolve_location(model_key))

    cached = _clients_by_location.get(cache_key)
    if cached is not None:
        return cached

    http_opts = _gt.HttpOptions(timeout=_http_timeout_ms(model_key))

    if backend == "vertex":
        creds_file = os.environ["ABM_GOOGLE_CREDENTIALS_FILE"]
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", creds_file)
        client = _make_genai_client(
            vertexai=True,
            project=_vertex_project(),
            location=_resolve_location(model_key),
            http_options=http_opts,
        )
    else:
        api_key = os.environ["ABM_GEMINI_API_KEY"].strip()
        client = _make_genai_client(api_key=api_key, http_options=http_opts)

    _clients_by_location[cache_key] = client
    return client


# ---------------------------------------------------------------------------
# Request guard: RPM throttle + RPD daily counter
# ---------------------------------------------------------------------------

_last_call_ts_by_model = {}
_throttle_lock = threading.Lock()

_rpd_file_path = None
_rpd_lock = threading.Lock()
_rpd_cache = None  # {"date": "YYYY-MM-DD", "flash25": N, "flash31": M}


def _today_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _rpd_load():
    """Carica contatore RPD per modello dal file su disco. Rolla a mezzanotte UTC."""
    global _rpd_cache
    if _rpd_cache is not None and _rpd_cache.get("date") == _today_utc_str():
        return _rpd_cache
    if _rpd_file_path is None:
        # Fallback in-memory only
        _rpd_cache = {"date": _today_utc_str(), "flash25": 0, "flash31": 0}
        return _rpd_cache
    if _rpd_file_path.exists():
        try:
            data = json.loads(_rpd_file_path.read_text(encoding="utf-8"))
            if data.get("date") == _today_utc_str():
                data.setdefault("flash25", 0)
                data.setdefault("flash31", 0)
                _rpd_cache = data
                return data
        except Exception as e:
            print(f"[gemini-tts] RPD load failed: {e}")
    _rpd_cache = {"date": _today_utc_str(), "flash25": 0, "flash31": 0}
    return _rpd_cache


def _rpd_save():
    if _rpd_file_path is None or _rpd_cache is None:
        return
    try:
        _rpd_file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = _rpd_file_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_rpd_cache), encoding="utf-8")
        tmp.replace(_rpd_file_path)
    except Exception as e:
        print(f"[gemini-tts] RPD save failed: {e}")


def _rpd_increment(model_key):
    with _rpd_lock:
        data = _rpd_load()
        data[model_key] = data.get(model_key, 0) + 1
        _rpd_save()


def preflight_can_run(model_key, chunks_needed):
    """Verifica preventiva: il job puo' partire senza saturare la quota?

    Ritorna dict:
        {"ok": bool, "available": int, "needed": int, "shortfall": int,
         "cap": int, "used": int, "reserve": int, "retry_after_sec": int}

    retry_after_sec e' calcolato come secondi residui fino a mezzanotte UTC
    (quando il counter rolla). Per cap non configurato (cap<=0) ritorna sempre ok=True.
    """
    cap = _rpd_cap(model_key)
    if cap <= 0:
        return {"ok": True, "available": 10**9, "needed": int(chunks_needed),
                "shortfall": 0, "cap": 0, "used": 0, "reserve": 0,
                "retry_after_sec": 0}
    with _rpd_lock:
        used = _rpd_load().get(model_key, 0)
    reserve = _rpd_safety_reserve()
    available = max(0, cap - used - reserve)
    shortfall = max(0, int(chunks_needed) - available)
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=23, minute=59, second=59).timestamp()
    retry_after = max(60, int(midnight - now.timestamp()))
    return {
        "ok": shortfall == 0,
        "available": available,
        "needed": int(chunks_needed),
        "shortfall": shortfall,
        "cap": cap,
        "used": used,
        "reserve": reserve,
        "retry_after_sec": retry_after,
    }


def _check_rpd_cap(model_key):
    """Solleva GeminiQuotaExhausted se il cap locale è stato raggiunto."""
    cap = _rpd_cap(model_key)
    if cap <= 0:
        return  # nessun cap configurato
    with _rpd_lock:
        used = _rpd_load().get(model_key, 0)
    reserve = _rpd_safety_reserve()
    available = cap - used - reserve
    if available <= 0:
        # retry teorico: a mezzanotte UTC
        now = datetime.now(timezone.utc)
        midnight = now.replace(hour=23, minute=59, second=59).timestamp()
        wait_sec = max(60, int(midnight - now.timestamp()))
        raise GeminiQuotaExhausted(
            f"Local RPD cap reached for {model_key}: used={used} cap={cap} reserve={reserve}",
            retry_after_sec=wait_sec,
            reason="rpd_local_cap",
        )


def _throttle_rpm(model_key):
    """Rispetta l'intervallo minimo tra due call (RPM floor)."""
    min_ms = _min_interval_ms(model_key)
    if min_ms <= 0:
        return
    with _throttle_lock:
        last = _last_call_ts_by_model.get(model_key, 0.0)
        elapsed_ms = (time.time() - last) * 1000.0
        wait_ms = min_ms - elapsed_ms
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)
        _last_call_ts_by_model[model_key] = time.time()


# ---------------------------------------------------------------------------
# 429 / retry parsing
# ---------------------------------------------------------------------------

# Match `retry in 6h12m51.7s`, `retryDelay: '22371s'`, `Please retry in 5.4s`,
# o numeri puri di secondi nei messaggi di errore Google API.
_RE_RETRY_HMS = re.compile(r"retry\s+in\s+(?:(\d+)h)?(?:(\d+)m)?([\d.]+)?s", re.IGNORECASE)
_RE_RETRY_SECS = re.compile(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", re.IGNORECASE)


def _parse_retry_after(err):
    """Estrae retry-after in secondi dall'errore. Restituisce None se non trovato.

    Tentativi (ordinati):
      1. attributo `error.retry_delay` / `error.details[*].retry_delay.seconds`
         (se l'SDK lo espone come oggetto strutturato)
      2. parsing della stringa: 'retryDelay: 22371s'
      3. parsing della stringa: 'retry in 6h12m51.7s' / 'retry in 5s'
    """
    # 1) Structured access via SDK
    try:
        details = getattr(err, "details", None) or []
        for d in details:
            rd = getattr(d, "retry_delay", None) or (d.get("retryDelay") if isinstance(d, dict) else None)
            if rd is not None:
                if isinstance(rd, str) and rd.endswith("s"):
                    return float(rd[:-1])
                secs = getattr(rd, "seconds", None) if not isinstance(rd, dict) else rd.get("seconds")
                if secs is not None:
                    return float(secs)
    except Exception:
        pass

    # 2/3) String parsing
    s = str(err)
    m = _RE_RETRY_SECS.search(s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    m = _RE_RETRY_HMS.search(s)
    if m:
        try:
            h = int(m.group(1) or 0)
            mn = int(m.group(2) or 0)
            sc = float(m.group(3) or 0)
            return h * 3600 + mn * 60 + sc
        except ValueError:
            pass
    return None


def _is_daily_quota_error(err):
    """Heuristica per distinguere quota daily da rate-limit transient."""
    s = str(err).lower()
    return ("per_day" in s) or ("per_model_per_day" in s) or ("perdayper" in s.replace("-", ""))


def _is_429(err):
    s = str(err)
    return ("429" in s) or ("RESOURCE_EXHAUSTED" in s) or ("ResourceExhausted" in s)


class GeminiEmptyResponse(RuntimeError):
    """Sollevata quando la response Gemini non contiene payload audio.
    Causa tipica: safety filter, prompt block, finish_reason!=STOP, o modello
    preview instabile. Il caller puo' decidere se considerarla non-retryable
    (block_reason=SAFETY/PROHIBITED_CONTENT) o transient (OTHER/MAX_TOKENS).
    """

    def __init__(self, message, block_reason=None, finish_reason=None,
                 safety_ratings=None, retryable=True):
        super().__init__(message)
        self.block_reason = block_reason
        self.finish_reason = finish_reason
        self.safety_ratings = safety_ratings
        self.retryable = retryable


def _extract_audio_pcm(response, model_key):
    """Estrae il payload PCM da una response Gemini. Se mancano candidates,
    content, parts, o inline_data, solleva GeminiEmptyResponse con tutti i
    metadati diagnostici (prompt_feedback.block_reason, finish_reason,
    safety_ratings) loggati per chiarire il motivo del rifiuto."""
    # 1) prompt_feedback.block_reason: il prompt e' stato bloccato prima
    #    dell'inferenza (es. safety filter sul testo di input).
    pf = getattr(response, "prompt_feedback", None)
    block_reason = None
    if pf is not None:
        br = getattr(pf, "block_reason", None)
        if br:
            block_reason = getattr(br, "name", str(br))
    # 2) candidates: lista delle risposte; se vuota -> nessun output prodotto.
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        msg = (f"Gemini returned no candidates (model={model_key}, "
               f"block_reason={block_reason or 'unknown'})")
        print(f"[gemini-tts] EMPTY-RESPONSE: {msg}")
        raise GeminiEmptyResponse(
            msg, block_reason=block_reason,
            retryable=(block_reason not in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST")),
        )
    cand = candidates[0]
    finish_reason = getattr(cand, "finish_reason", None)
    finish_label = getattr(finish_reason, "name", str(finish_reason)) if finish_reason else None
    safety_ratings = getattr(cand, "safety_ratings", None)
    content = getattr(cand, "content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    if not parts:
        # Logga safety_ratings in modo leggibile per capire quale categoria
        # ha triggerato il block (HARM_CATEGORY_DANGEROUS_CONTENT, ecc).
        ratings_str = "n/a"
        if safety_ratings:
            try:
                ratings_str = ", ".join(
                    f"{getattr(r.category, 'name', r.category)}={getattr(r.probability, 'name', r.probability)}"
                    for r in safety_ratings
                )
            except Exception:
                ratings_str = str(safety_ratings)[:200]
        msg = (f"Gemini response has no audio parts "
               f"(model={model_key}, finish_reason={finish_label}, "
               f"block_reason={block_reason or 'none'}, safety=[{ratings_str}])")
        print(f"[gemini-tts] EMPTY-RESPONSE: {msg}")
        # Retryable solo se NON e' un block content-based.
        non_retryable_finish = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "RECITATION"}
        retryable = (finish_label not in non_retryable_finish
                     and block_reason not in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"))
        raise GeminiEmptyResponse(
            msg, block_reason=block_reason,
            finish_reason=finish_label,
            safety_ratings=ratings_str,
            retryable=retryable,
        )
    inline = getattr(parts[0], "inline_data", None)
    data = getattr(inline, "data", None) if inline is not None else None
    if not data:
        msg = (f"Gemini response part has no inline_data "
               f"(model={model_key}, finish_reason={finish_label})")
        print(f"[gemini-tts] EMPTY-RESPONSE: {msg}")
        raise GeminiEmptyResponse(
            msg, finish_reason=finish_label, retryable=True,
        )
    return data


def build_final_text(text, style_instruction=None, rate=None,
                     accent_directive=None):
    """Assembla il prompt finale: blocco "[style: ...] " + testo.

    Estratta da `synthesize` per avere UNA sola definizione del prompt:
    la ricostruzione offline (backfill del manifest di riuso chunk, che
    confronta i prompt*.txt di un run interrotto) deve produrre byte per
    byte lo stesso testo, altrimenti il confronto e' privo di valore.
    """
    # Kill-switch del rate prompt-directive. Default "prompt" = directive attiva.
    # Qualsiasi altro valore (incluso il legacy "token"/"estimate") disattiva
    # l'iniezione. Nessun altro effetto: non e` usato per cost calc o altro.
    rate_mode = os.environ.get("ABM_GEMINI_RATE_MODE", "prompt")
    # Costruiamo un singolo blocco "[style: ... ]" che combina lo stile utente
    # con la direttiva di velocita`. Il rate non e` esposto dall'API Gemini come
    # parametro audio, quindi va comunicato in linguaggio naturale. Inserirlo
    # DENTRO il blocco style (anziche` come prefisso separato in fila al testo)
    # ha due vantaggi:
    #   1. Semanticamente piu` corretto: "come leggere" = stile, non testo.
    #   2. Aderenza maggiore: Gemini ignora spesso istruzioni in linguaggio
    #      diverso da quello del testo se non sono incapsulate.
    # Lo style utente viene capato a 300 char (qualita` UI); la directive rate
    # e` costante e si appende dopo senza re-cap (max ~110 char system-added).
    style_parts = []
    # Accento per primo: e' l'ancora piu` importante per la coerenza tra chunk.
    if accent_directive:
        ad = str(accent_directive).strip()[:160]
        if ad:
            style_parts.append(ad)
    if style_instruction:
        # Cap a 200 char (non 300): la directive rate piu` lunga e` ~95 char e
        # va a sommarsi nello stesso blocco [style: ...]. 200 + 95 + 1 (sep) =
        # 296, sotto il budget storico di 300 char "comprensibili" dal modello.
        s = str(style_instruction).strip()[:200]
        if s:
            style_parts.append(s)
    # Iniezione della rate directive nel blocco [style:...]. Silenziosa su
    # successo (per non spammare il log con N chunk * stesso messaggio). Loud
    # solo quando il rate non-default viene scartato: utile per diagnosi rapida
    # ("ho chiesto +30% ma l'audio e` a velocita` normale").
    if rate and rate != "+0%":
        if rate_mode != "prompt":
            print(f"[gemini-tts] WARN: rate={rate!r} richiesto ma "
                  f"ABM_GEMINI_RATE_MODE={rate_mode!r} disattiva la directive. "
                  f"Setta ABM_GEMINI_RATE_MODE=prompt (o unset) per attivarla.")
        else:
            pct = str(rate).replace("%", "").replace("+", "")
            try:
                n = int(pct)
                step = max(-3, min(3, round(n / 10)))
                directive = _GEMINI_RATE_DIRECTIVES.get(step, "")
                if directive:
                    style_parts.append(directive)
                # step 0 = directive vuota = niente da appendere (silenzioso).
            except ValueError as _ve:
                print(f"[gemini-tts] WARN: rate={rate!r} parse failed ({_ve}). "
                      f"Directive non aggiunta.")

    if style_parts:
        final_text = f"[style: {' '.join(style_parts)}] {text}"
    else:
        final_text = text

    return final_text


def _vertex_transport_call(*, final_text, voice_name, model_key, model_id,
                           timeout_ms, temperature):
    """Adapter di trasporto Vertex / API key.

    Estratto dal corpo del ciclo di retry di `synthesize()`: qui c'e' UNA
    chiamata, senza retry e senza sleep. La politica di retry resta nel
    chiamante, che e' l'unico a sapere quanti tentativi restano e se puo'
    dirottare su un altro backend.

    Conforme al contratto di `gemini_transport`: ritorna pcm + token, solleva
    solo TransportError.
    """
    from google.genai import types as genai_types

    # Client isolato dal try dell'API call (rilievo task-7): _get_client puo'
    # sollevare per credenziali/progetto/location mancanti o illeggibili, cioe'
    # un errore di CONFIGURAZIONE che ritentare non risolve mai. Prima di questo
    # fix finiva nell'except-all sotto e usciva come kind="retryable",
    # sprecando tutti i tentativi del job su un guasto che serve un operatore
    # per essere risolto.
    try:
        client = _get_client(model_key)
    except Exception as e:
        raise TransportError(str(e), kind="fatal") from e

    try:
        # Dentro il try come prima del refactor (rilievo m8): se la
        # costruzione della config sollevasse, l'errore deve uscire
        # classificato come TransportError e non grezzo al primo giro.
        config_kwargs = {
            "response_modalities": ["AUDIO"],
            "speech_config": genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                        voice_name=voice_name,
                    )
                )
            ),
        }
        if temperature is not None:
            config_kwargs["temperature"] = temperature

        response = client.models.generate_content(
            model=model_id,
            contents=final_text,
            config=genai_types.GenerateContentConfig(
                **config_kwargs,
                http_options=genai_types.HttpOptions(timeout=timeout_ms),
            ),
        )
        pcm_data = _extract_audio_pcm(response, model_key)
    except GeminiEmptyResponse as e:
        # Il caller storico distingueva retryable da non-retryable: la
        # distinzione sopravvive nel kind.
        raise TransportError(
            str(e),
            kind="retryable" if e.retryable else "content_rejected",
        ) from e
    except Exception as e:
        if _is_429(e):
            retry_after = _parse_retry_after(e)
            kind = "quota_daily" if _is_daily_quota_error(e) else "rate_limited"
            raise TransportError(str(e), kind=kind,
                                 retry_after_sec=retry_after) from e
        raise TransportError(str(e), kind="retryable") from e

    um = getattr(response, "usage_metadata", None)
    return {
        "pcm": pcm_data,
        "input_tokens": (getattr(um, "prompt_token_count", 0) or 0) if um else 0,
        "output_tokens": (getattr(um, "candidates_token_count", 0) or 0) if um else 0,
    }


def synthesize(text, voice_id, rate="+0%", output_path="output.pcm", style_instruction=None,
               debug_prompt_path=None, max_attempts=None, accent_directive=None,
               job_id=None):
    """Sintetizza testo in PCM raw 24kHz mono 16-bit usando Gemini TTS.

    Args:
        text: testo da sintetizzare. MAX_BYTES_PER_CALL e` un TARGET QUALITA`
            (soft) che si applica SOLO a questo testo (esclusi i prefissi
            style/rate aggiunti internamente): se sforato, warning ma si procede.
        voice_id: 'gemini:<model_key>:<voice_name>'.
        rate: parametro di compatibilita' — Gemini TTS non ha speaking_rate API,
              quando rate != '+0%' viene aggiunta come direttiva in linguaggio
              naturale DENTRO il blocco [style: ...] (es. "Read this text quickly...").
        output_path: percorso file PCM in output.
        style_instruction: opzionale, istruzione di stile/tono (max 200 char dopo
            strip). Viene fusa con l'eventuale rate directive in un singolo
            blocco "[style: <user_style> <rate_directive>] " prefissato al testo.
            Cap a 200 (non 300): la directive rate piu` lunga e` ~95 char, la
            somma resta <= 296 sotto il budget storico di 300 char prompt.
            Non concorre al target qualita`: e` un prompt, non testo audio.
        max_attempts: opzionale, override del numero massimo di tentativi.
            Default None = usa `_synth_max_attempts()` (3 in prod). Per il
            path preview si passa 1 per fallire velocemente su EMPTY-RESPONSE
            finish_reason=OTHER (retry di stesso payload di solito non aiuta)
            ed evitare il timeout 30s lato client.
        accent_directive: opzionale, direttiva di accento (system-generated da
            build_accent_directive) prefissata PER PRIMA dentro lo stesso blocco
            [style: ...], prima dello stile utente e della directive rate. Ancora
            l'accento a tutti i chunk (vedi build_accent_directive). Capata a 160
            char: e' un prompt costante e bounded, non concorre al target qualita`.
        job_id: opzionale, id del job in corso; viene registrato nello stato
            di trip per rendere tracciabile quale job ha visto l'avaria del
            backend (vedi tts_backend_state). Se assente lo stato registra
            None e il failover funziona comunque: la tracciabilita' e' un
            di piu', non una precondizione.

    Returns:
        dict con success, bytes_written, audio_seconds_real, input_tokens,
        output_tokens, model_key, voice_name, attempts_used, backend,
        tokens_measured.

        `backend` e' il backend che ha eseguito la chiamata riuscita
        ("vertex" | "apikey" | "cloudflare"): dopo un failover a meta' job non
        coincide con quello risolto all'inizio. `tokens_measured` e' True solo
        se i token arrivano dal provider; su Cloudflare, che non li espone,
        sono derivati (spec §4.6) e il flag e' False.

    Raises:
        ValueError se il payload totale (testo + prefissi) supera API_HARD_BYTES_CAP
            o voice_id e' invalido.
        RuntimeError se tutti i retry falliscono.
    """
    if not is_available():
        raise GeminiUnavailable(
            "Gemini TTS not available "
            f"(admin_disabled={bool(_admin_disabled)}, "
            "check ABM_GEMINI_API_KEY/kill-switch)")

    # Il model_id qui e' solo per validare voice_id: quello usato per la call
    # API viene ricalcolato dentro il loop di retry (vedi call_model_id) per
    # restare coerente col backend del tentativo corrente, non con quello
    # visto al parsing (rilievo M1, fix-1).
    model_key, _parsed_model_id, voice_name = parse_voice_id(voice_id)

    # Check 1: target QUALITA` sul TESTO PURO (escluso prefissi). Se lo splitter
    # ha lavorato correttamente questo non scatta; e` un warning di sicurezza che
    # non blocca la sintesi (l'API regge il payload, e` solo l'acustica a degradare).
    text_ok, text_size = check_text_byte_size(text)
    if not text_ok:
        print(f"[gemini-tts] WARN: testo {text_size}b oltre soglia qualita` "
              f"{MAX_BYTES_PER_CALL}b -- possibile lieve degrado acustico")

    final_text = build_final_text(text, style_instruction, rate,
                                  accent_directive)

    # Check 2: hard cap API sul PAYLOAD COMPLETO (testo + prefissi). E` il vero
    # limite tecnico oltre il quale Gemini TTS rifiuta la chiamata.
    payload_size = len(final_text.encode("utf-8"))
    if payload_size > API_HARD_BYTES_CAP:
        raise ValueError(
            f"Payload exceeds API hard cap ({payload_size} > {API_HARD_BYTES_CAP} bytes; "
            f"testo {text_size}b + prefissi {payload_size - text_size}b)"
        )

    # Debug: dump del prompt finale (testo + prefissi style/rate) per ispezione.
    if debug_prompt_path:
        try:
            Path(debug_prompt_path).parent.mkdir(parents=True, exist_ok=True)
            with open(debug_prompt_path, "w", encoding="utf-8") as fp:
                fp.write(final_text)
        except Exception as e:
            print(f"[gemini-tts] could not write debug prompt to {debug_prompt_path}: {e}")

    # Guard pre-call: cap RPD locale + throttle RPM. Il cap RPD può sollevare
    # GeminiQuotaExhausted; il throttle invece blocca (sleep) finché c'è budget.
    # Spec §6: sono quote GOOGLE (RPD/RPM del progetto Vertex), quindi non si
    # applicano quando la chiamata parte verso Cloudflare — autolimitarsi su un
    # limite che non ti riguarda significa strozzare il traffico e, con un cap
    # RPD configurato, sollevare GeminiQuotaExhausted per una quota altrui.
    # Restano PRIMA del loop (una volta per chiamata) come da comportamento
    # storico del percorso Vertex: spostarli dentro il loop introdurrebbe un
    # throttle fra i retry che oggi non c'e'.
    if _resolve_backend(model_key) != "cloudflare":
        _check_rpd_cap(model_key)
        _throttle_rpm(model_key)

    last_err = None
    pcm_data = None
    # None = il trasporto non ha riportato la misura (Cloudflare non espone i
    # token): si distingue da uno 0 misurato, e la derivazione §4.6 avviene
    # dopo il loop, quando la lunghezza del PCM e' nota.
    usage_input = None
    usage_output = None
    backend_used = None
    attempt = 0
    # max_attempts: il parametro funzione vince sull'env. Permette al caller
    # (es. preview_audio) di abbassare il numero di retry per non saturare il
    # timeout client su EMPTY-RESPONSE retryable ma di fatto deterministica.
    if max_attempts is None or int(max_attempts) <= 0:
        max_attempts = _synth_max_attempts()
    else:
        max_attempts = int(max_attempts)
    honor_delay = _retry_honor_delay()
    max_wait = _retry_max_wait_sec()
    abort_daily = _abort_on_daily_quota()

    while attempt < max_attempts:
        attempt += 1
        backend = _resolve_backend(model_key)
        transport = _transport_for(backend)
        # model_id risolto AD OGNI TENTATIVO in base al backend corrente di
        # QUESTO giro (rilievo M1, fix-1): il valore risolto da parse_voice_id
        # prima del loop e' congelato sul backend visto all'inizio della
        # chiamata. Se un failover scatta a meta' (Cloudflare -> Vertex), quel
        # valore resta quello di Cloudflare (m["id"], nome legacy) invece di
        # m["id_vertex"] (nome GA): oggi e' inerte solo perche' flash31 ha gli
        # id coincidenti sui due backend, ma diverge appena un modello con
        # id_cloudflare != id_vertex viene abilitato (es. un futuro flash25 su
        # Cloudflare). _resolve_model_id rifa' la stessa risoluzione backend
        # (cache, quindi a costo zero) e resta corretta per vertex/apikey.
        call_model_id = (GEMINI_MODELS[model_key].get("id_cloudflare")
                         if backend == "cloudflare" else _resolve_model_id(model_key))
        try:
            out = transport(
                final_text=final_text,
                voice_name=voice_name,
                model_key=model_key,
                model_id=call_model_id,
                timeout_ms=(_cf_timeout_ms() if backend == "cloudflare"
                            else _http_timeout_ms(model_key)),
                temperature=_temperature(),
            )
            pcm_data = out["pcm"]
            usage_input = out.get("input_tokens")
            usage_output = out.get("output_tokens")
            backend_used = backend
            if backend == "cloudflare":
                _backend_state.record_success(model_key)
            else:
                # Spec §6: il contatore RPD e' quello del progetto Google. Una
                # chiamata servita da Cloudflare non lo consuma.
                _rpd_increment(model_key)
            break
        except TransportError as te:
            # Messaggio REDATTO dell'adapter: e' l'unico che finisce nei log e
            # nei messaggi delle eccezioni. L'eccezione grezza del provider
            # resta raggiungibile solo come `__cause__` della catena (`from
            # te`), mai serializzata da noi: su Cloudflare gli header — e
            # quindi il bearer token — non passano di qui per nessuna strada
            # (sospetto S1 della review finale, chiuso).
            last_err = str(te)

            # --- Circuit breaker: solo per Cloudflare, solo per guasti del
            # backend. Un contenuto rifiutato o un parametro sbagliato sono
            # difetti del payload: farebbero cadere il backend per colpa di un
            # chunk (spec §4.4 punto 4).
            if backend == "cloudflare" and te.kind in ("backend_down",
                                                       "retryable",
                                                       "rate_limited"):
                if te.kind == "backend_down":
                    _trip_to_vertex(model_key,
                                    reason="cf_backend_down",
                                    detail=f"HTTP {te.http_status} "
                                           f"code {te.provider_code}",
                                    job_id=job_id)
                    # La stessa chiamata prosegue su Vertex con i tentativi
                    # rimanenti: l'audio e' identico byte per byte, il job in
                    # corso non si accorge del cambio.
                    attempt -= 1
                    continue
                failures = _backend_state.record_failure(model_key)
                if failures >= _cf_trip_failures():
                    _trip_to_vertex(model_key,
                                    reason="cf_consecutive_failures",
                                    detail=f"{failures} fallimenti consecutivi; "
                                           f"ultimo: {str(te)[:120]}",
                                    job_id=job_id)
                    attempt -= 1
                    continue

            # Contenuto rifiutato: riprovare lo stesso testo non aiuta.
            # `TransportError` e' interna al trasporto e non deve MAI uscire da
            # synthesize(): il chiamante conosce solo il vocabolario di dominio
            # (GeminiEmptyResponse / GeminiUnavailable / GeminiQuotaExhausted /
            # RuntimeError), su cui e' costruita la macchina di rimborso.
            if te.kind == "content_rejected":
                cause = te.__cause__
                print(f"[gemini-tts] Empty response non-retryable: "
                      f"finish_reason={getattr(cause, 'finish_reason', None)} "
                      f"block={getattr(cause, 'block_reason', None)}. "
                      f"Aborting attempts.")
                if isinstance(cause, GeminiEmptyResponse):
                    # Percorso Vertex: la causa E' gia' l'eccezione di dominio
                    # e porta con se' block_reason/finish_reason/safety_ratings.
                    # Si rilancia identica, come prima di questo fix.
                    raise cause
                # Percorso Cloudflare (422 / codice 2017, spec §4.2): non c'e'
                # causa da preservare, si costruisce l'equivalente di dominio.
                raise GeminiEmptyResponse(str(te), retryable=False) from te

            # Errore fatale (config/parametro invalido, es. credenziali Vertex
            # mancanti o voce inesistente su Cloudflare): ritentare lo stesso
            # backend con lo stesso payload non risolve mai nulla, va solo a
            # sprecare tutto il budget di retry del job (rilievo task-7 su
            # _vertex_transport_call). Non fa scattare il breaker (punto 4):
            # non e' un guasto del backend.
            if te.kind == "fatal":
                print(f"[gemini-tts] Fatal error ({model_key}, backend={backend}): "
                      f"{te}. Aborting attempts.")
                # Un guasto di configurazione e' permanente per il processo
                # finche' non interviene un operatore: e' esattamente il
                # contratto di GeminiUnavailable, l'unica eccezione che
                # tts_split propaga come job-fatale invece di degradare a
                # silenzio. Vale sia per Cloudflare (voce fuori enum, token
                # assente) sia per Vertex (credenziali illeggibili), dove
                # prima usciva la causa grezza — un KeyError che il chiamante
                # scambiava per un guasto di chunk (spec §4.4 p.4).
                # `from te`: str(te) e' il messaggio gia' redatto dall'adapter.
                raise GeminiUnavailable(str(te)) from te

            # Quota giornaliera: sospendere invece di dormire per ore.
            if te.kind == "quota_daily" and abort_daily:
                print(f"[gemini-tts] Daily quota exhausted ({model_key}). "
                      f"retry_after={te.retry_after_sec}s. "
                      f"Aborting (ABM_GEMINI_ABORT_ON_QUOTA=true).")
                raise GeminiQuotaExhausted(
                    f"Gemini daily quota exhausted: {last_err}",
                    retry_after_sec=te.retry_after_sec,
                    reason="api_daily_quota",
                ) from te

            is_429 = te.kind in ("rate_limited", "quota_daily")
            retry_after = te.retry_after_sec
            if honor_delay and retry_after is not None:
                if retry_after > max_wait:
                    print(f"[gemini-tts] 429 retry_after={retry_after}s > "
                          f"max_wait={max_wait}s. Suspending instead of "
                          f"sleeping ({model_key}).")
                    raise GeminiQuotaExhausted(
                        f"Gemini 429 with long retry: {last_err}",
                        retry_after_sec=retry_after,
                        reason="retry_too_long",
                    ) from te
                wait = max(1.0, retry_after)
            else:
                wait = min(30.0, 2 ** attempt)

            if attempt < max_attempts:
                print(f"[gemini-tts] Attempt {attempt}/{max_attempts} failed "
                      f"({'429' if is_429 else 'other'}). Sleeping {wait:.1f}s. "
                      f"Err: {last_err[:200]}")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"Gemini TTS failed after {max_attempts} attempts: "
                    f"{last_err}") from te

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(pcm_data)

    audio_seconds_real = len(pcm_data) / float(AUDIO_SAMPLE_RATE * AUDIO_SAMPLE_WIDTH_BYTES * AUDIO_CHANNELS)

    # --- Derivazione dei token (spec §4.6) --------------------------------
    # Cloudflare non restituisce metadati d'uso: il trasporto lo dichiara
    # onestamente con None e la stima spetta a noi, che conosciamo il modello.
    # Senza questa derivazione il costo calcolato a valle sarebbe zero e il cap
    # di spesa giornaliero (get_daily_spent_eur -> preflight_budget_check) si
    # disarmerebbe: ogni job leggerebbe "speso oggi = 0 EUR" e partirebbe.
    # `tokens_measured` distingue una misura del provider da una nostra stima:
    # senza quel flag il consuntivo riconcilierebbe una stima contro se' stessa.
    tokens_measured = usage_input is not None and usage_output is not None
    if usage_output is None:
        usage_output = int(round(audio_seconds_real
                                 * _audio_tokens_per_second(model_key)))
    if usage_input is None:
        # synthesize() non riceve la lingua: si usa il default di
        # estimate_input_tokens. L'input pesa ~1% del costo (0,89 contro 16,30
        # USD/Mtok, spec §4.7), quindi l'errore di lingua e' trascurabile
        # rispetto all'alternativa, che e' contare zero.
        usage_input = estimate_input_tokens(final_text)

    return {
        "success": True,
        "bytes_written": len(pcm_data),
        "audio_seconds_real": audio_seconds_real,
        "input_tokens": usage_input,
        "output_tokens": usage_output,
        "model_key": model_key,
        "voice_name": voice_name,
        "attempts_used": attempt,
        # Quale backend ha effettivamente eseguito la chiamata riuscita: dopo
        # un failover a meta' job non coincide con quello iniziale.
        "backend": backend_used,
        "tokens_measured": tokens_measured,
    }
