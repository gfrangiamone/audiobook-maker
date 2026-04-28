#!/usr/bin/env python3
"""
Google Cloud TTS (Chirp3-HD) integration for Audiobook Maker.

Provides voice listing, speech synthesis, and monthly usage tracking
within the free tier (1M chars/month).

Requires:
    pip install google-cloud-texttospeech

Configure:
    export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
    # or
    export ABM_GOOGLE_CREDENTIALS_FILE="/path/to/service-account.json"
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


# ── Lazy import del SDK Google (opzionale) ──
_gtts_client = None
_gtts_module = None
_gtts_available = None  # None = non ancora verificato
_gtts_lock = threading.Lock()

# Limite mensile caratteri (free tier Google Cloud TTS)
GOOGLE_TTS_MONTHLY_LIMIT = int(os.environ.get("ABM_GOOGLE_TTS_MONTHLY_LIMIT", "1000000"))

# File persistente per tracking utilizzo mensile
_usage_file_path = None  # set by init()
_usage_lock = threading.Lock()
_usage_cache = None  # {"month": "2026-04", "chars_used": 0}

# Cache voci Google
_google_voices_cache = None
_google_voices_lock = threading.Lock()
_google_voices_ts = 0  # timestamp ultimo fetch
VOICES_CACHE_TTL = 3600  # 1 ora

# Cloud Monitoring (riconciliazione consumo reale)
_monitoring_client = None
_monitoring_available = None  # None = non ancora verificato
_project_id = None  # Estratto dal file credenziali
_last_reconcile_ts = 0
_last_reconcile_value = None  # Ultimo valore letto da Cloud Monitoring (chars)


def init(data_dir):
    """Inizializza il modulo con la directory dati persistente."""
    global _usage_file_path
    _usage_file_path = Path(data_dir) / "google_tts_usage.json"


def is_available():
    """Verifica se Google Cloud TTS è configurato e disponibile."""
    global _gtts_available, _gtts_module, _gtts_client

    if _gtts_available is not None:
        return _gtts_available

    with _gtts_lock:
        if _gtts_available is not None:
            return _gtts_available

        # Check credenziali
        creds_file = os.environ.get("ABM_GOOGLE_CREDENTIALS_FILE", "") or \
                     os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        
        print(f"[google-tts] init check: creds_file='{creds_file}'")
        
        if not creds_file or not os.path.exists(creds_file):
            _gtts_available = False
            print(f"[google-tts] Disabled: no credentials file found at '{creds_file}'.")
            return False

        # Ensure GOOGLE_APPLICATION_CREDENTIALS is set (SDK lo richiede)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_file

        try:
            from google.cloud import texttospeech_v1beta1 as texttospeech
            _gtts_module = texttospeech
            _gtts_client = texttospeech.TextToSpeechClient()
            _gtts_available = True
            # Estrai project_id dal file credenziali (serve a Cloud Monitoring)
            global _project_id
            try:
                with open(creds_file, "r", encoding="utf-8") as f:
                    creds_data = json.load(f)
                    _project_id = creds_data.get("project_id")
            except Exception as e:
                print(f"[google-tts] Warning: could not read project_id from credentials: {e}")
            print(f"[google-tts] Enabled (credentials: {creds_file}, project: {_project_id})")
            return True
        except ImportError:
            _gtts_available = False
            print("[google-tts] Disabled: google-cloud-texttospeech not installed. "
                  "Run: pip install google-cloud-texttospeech")
            return False
        except Exception as e:
            _gtts_available = False
            print(f"[google-tts] Disabled: initialization error: {e}")
            return False


def _current_month():
    """Restituisce il mese corrente in formato YYYY-MM (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _load_usage():
    """Carica l'utilizzo mensile dal file persistente."""
    global _usage_cache
    if _usage_file_path is None:
        return {"month": _current_month(), "chars_used": 0}

    try:
        if _usage_file_path.exists():
            data = json.loads(_usage_file_path.read_text(encoding="utf-8"))
            if data.get("month") == _current_month():
                _usage_cache = data
                return data
    except Exception as e:
        print(f"[google-tts] Warning: could not read usage file: {e}")

    # Nuovo mese o file mancante/corrotto
    data = {"month": _current_month(), "chars_used": 0}
    _usage_cache = data
    return data


def _save_usage(data):
    """Salva l'utilizzo mensile su file."""
    global _usage_cache
    _usage_cache = data
    if _usage_file_path is None:
        return
    try:
        _usage_file_path.parent.mkdir(parents=True, exist_ok=True)
        _usage_file_path.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        print(f"[google-tts] Warning: could not save usage file: {e}")


def get_usage():
    """Restituisce (chars_used, chars_remaining, monthly_limit) per il mese corrente."""
    with _usage_lock:
        data = _load_usage()
    used = data.get("chars_used", 0)
    remaining = max(0, GOOGLE_TTS_MONTHLY_LIMIT - used)
    return used, remaining, GOOGLE_TTS_MONTHLY_LIMIT


def check_budget(chars_needed):
    """Verifica se ci sono abbastanza caratteri nel budget mensile.
    Restituisce (ok, remaining) dove ok=True se chars_needed <= remaining."""
    _, remaining, _ = get_usage()
    return chars_needed <= remaining, remaining


def reserve_chars(chars_needed):
    """Verifica e deduce atomicamente i caratteri richiesti dal budget mensile.
    Restituisce (ok, remaining_after) dove ok=True se la prenotazione è riuscita.
    Se ok=False non viene dedotto nulla."""
    with _usage_lock:
        data = _load_usage()
        used = data.get("chars_used", 0)
        remaining = max(0, GOOGLE_TTS_MONTHLY_LIMIT - used)
        if chars_needed > remaining:
            return False, remaining
        data["chars_used"] = used + chars_needed
        _save_usage(data)
        return True, remaining - chars_needed


def deduct_chars(chars):
    """Deduce caratteri dal budget mensile. Chiamare in pre-allocazione o dopo successo."""
    with _usage_lock:
        data = _load_usage()
        data["chars_used"] = data.get("chars_used", 0) + chars
        _save_usage(data)


def refund_chars(chars):
    """Restituisce caratteri al budget (per chunk non consumati dopo cancellazione/errore).
    Non scende mai sotto zero."""
    if chars <= 0:
        return
    with _usage_lock:
        data = _load_usage()
        data["chars_used"] = max(0, data.get("chars_used", 0) - chars)
        _save_usage(data)


def is_google_voice(voice_id):
    """Verifica se un voice ID è una voce Google Cloud TTS."""
    return voice_id.startswith("gcloud:")


def parse_voice_id(voice_id):
    """Estrae il nome voce reale Google dal voice ID prefissato.
    'gcloud:it-IT-Chirp3-HD-Achernar' -> ('it-IT', 'it-IT-Chirp3-HD-Achernar')
    """
    real_name = voice_id.removeprefix("gcloud:")
    # Il language_code è il prefisso locale (es. it-IT, en-US, cmn-CN)
    parts = real_name.split("-")
    # Gestisci locale a 3 parti come cmn-CN
    if len(parts) >= 2:
        # Prova con 2 parti prima (it-IT, en-US, fr-FR, de-DE, es-ES)
        lang_code = f"{parts[0]}-{parts[1]}"
    else:
        lang_code = parts[0]
    return lang_code, real_name


def _rate_to_speaking_rate(rate_str):
    """Converte rate in formato edge-tts ('+10%', '-20%') in float per Google TTS.
    Google TTS: 0.25 - 4.0, dove 1.0 = normale.
    Edge-tts: '-30%' a '+30%' dove '+0%' = normale.
    """
    try:
        pct = int(rate_str.replace("%", "").replace("+", ""))
        return 1.0 + (pct / 100.0)
    except (ValueError, AttributeError):
        return 1.0


def get_voices():
    """Restituisce le voci Google Cloud TTS Chirp3-HD disponibili.
    Formato compatibile con le voci edge-tts ma con prefisso 'gcloud:'.
    Restituisce {} se non disponibile o budget esaurito.
    """
    global _google_voices_cache, _google_voices_ts

    if not is_available():
        return {}

    # Check budget: se esaurito, non proporre le voci
    _, remaining, _ = get_usage()
    if remaining <= 0:
        return {}

    # Cache con TTL
    with _google_voices_lock:
        if _google_voices_cache is not None and (time.time() - _google_voices_ts) < VOICES_CACHE_TTL:
            return _google_voices_cache

    try:
        response = _gtts_client.list_voices()
    except Exception as e:
        print(f"[google-tts] Error fetching voices: {e}")
        return {}

    languages = {}
    voice_count = 0
    chirp_count = 0
    for v in response.voices:
        voice_count += 1
        name = v.name
        # Filtra solo voci Chirp3-HD
        if "Chirp3-HD" not in name:
            continue
        
        chirp_count += 1

        for lang_code_full in v.language_codes:
            lang_code_short = lang_code_full.split("-")[0]
            # Gestisci cmn -> zh per coerenza con edge-tts
            display_lang = "zh" if lang_code_short == "cmn" else lang_code_short

            if display_lang not in languages:
                languages[display_lang] = []

            # Estrai il nome della voce (ultima parte: Achernar, Leda, etc.)
            voice_name_parts = name.split("-")
            persona_name = voice_name_parts[-1] if voice_name_parts else name

            # Determina genere dal SSML gender
            gender_val = v.ssml_gender
            if hasattr(gender_val, 'name'):
                gender_str = gender_val.name  # MALE, FEMALE, NEUTRAL
            else:
                gender_str = str(gender_val)
            if gender_str == "FEMALE":
                gender = "Female"
                gender_icon = "\u2640"
            elif gender_str == "MALE":
                gender = "Male"
                gender_icon = "\u2642"
            else:
                gender = "Neutral"
                gender_icon = "\u26A5"

            voice_entry = {
                "id": f"gcloud:{name}",
                "name": f"{persona_name} HD",
                "locale": lang_code_full,
                "gender": gender,
                "gender_icon": gender_icon,
                "engine": "google",
            }
            # Evita duplicati (stessa voce, stessa lingua)
            if not any(ev["id"] == voice_entry["id"] for ev in languages[display_lang]):
                languages[display_lang].append(voice_entry)

    # Sort voci per genere poi nome
    for lang_voices in languages.values():
        lang_voices.sort(key=lambda x: (x["gender"], x["name"]))

    print(f"[google-tts] get_voices: total={voice_count}, chirp3={chirp_count}, languages={list(languages.keys())}")
    with _google_voices_lock:
        _google_voices_cache = languages
        _google_voices_ts = time.time()
    return languages



def synthesize(text, voice_id, rate="+0%", output_path="output.mp3"):
    """Sintetizza testo in MP3 usando Google Cloud TTS Chirp3-HD.
    voice_id: formato 'gcloud:it-IT-Chirp3-HD-Achernar'
    Restituisce True se successo, False se errore.
    NON deduce caratteri dal budget (il chiamante deve farlo).
    """
    if not is_available():
        raise RuntimeError("Google Cloud TTS not available")

    lang_code, real_voice_name = parse_voice_id(voice_id)
    speaking_rate = _rate_to_speaking_rate(rate)

    try:
        synthesis_input = _gtts_module.SynthesisInput(text=text)

        voice_params = _gtts_module.VoiceSelectionParams(
            language_code=lang_code,
            name=real_voice_name,
        )

        audio_config = _gtts_module.AudioConfig(
            audio_encoding=_gtts_module.AudioEncoding.MP3,
            speaking_rate=speaking_rate,
        )

        response = _gtts_client.synthesize_speech(
            input=synthesis_input,
            voice=voice_params,
            audio_config=audio_config,
        )

        with open(output_path, "wb") as out:
            out.write(response.audio_content)

        return True

    except Exception as e:
        print(f"[google-tts] Synthesis error for voice {real_voice_name}: {e}")
        raise


def invalidate_voices_cache():
    """Forza il refresh della cache voci al prossimo get_voices()."""
    global _google_voices_cache, _google_voices_ts
    with _google_voices_lock:
        _google_voices_cache = None
        _google_voices_ts = 0


# ═══════════════════════════════════════════════════════════════════
# CLOUD MONITORING — SANITY CHECK SUL CONTEGGIO RICHIESTE
# ═══════════════════════════════════════════════════════════════════
# IMPORTANTE: Google Cloud Monitoring NON espone i caratteri TTS consumati
# come metric (la quota da 1M char/mese del free tier è applicata server-side
# da Google al billing ma non è esportata in Cloud Monitoring). Le uniche
# metriche disponibili sono i conteggi di richieste:
#   - texttospeech.googleapis.com/requests          (SynthesizeSpeech, ListVoices)
#   - texttospeech.googleapis.com/requests_chirp3   (richieste contate sulla quota Chirp3)
#
# Quindi:
#   - Fonte di verità sui caratteri = contatore locale (reserve/refund atomico)
#   - Cloud Monitoring = sanity check: se local_chars è fuori dal range plausibile
#     dato il numero di richieste effettivamente viste, logga un warning
# Non c'è riconciliazione automatica del contatore caratteri (impossibile).

# Margine in secondi escluso dall'intervallo di query per usare solo metriche
# stabilizzate (la latenza di propagazione tipica è 3-7 minuti, qui usiamo
# 15 minuti per essere prudenti).
_MONITORING_STABILIZATION_LAG_SEC = 15 * 60

# Callback opzionale: deve restituire True se ci sono conversioni Google TTS
# attive (con caratteri prenotati ma non ancora riconciliati con Google).
# Impostato da audiobook_app via set_active_jobs_callback().
_active_jobs_callback = None


def set_active_jobs_callback(callback):
    """Registra una callback che indica se ci sono job Google TTS attivi.

    La callback deve essere `() -> bool`. Usata da reconcile_with_cloud_monitoring
    per decidere se è sicuro riconciliare al ribasso.
    """
    global _active_jobs_callback
    _active_jobs_callback = callback

def _init_monitoring():
    """Inizializza il client Cloud Monitoring (lazy)."""
    global _monitoring_client, _monitoring_available

    if _monitoring_available is not None:
        return _monitoring_available

    if not is_available() or not _project_id:
        _monitoring_available = False
        return False

    try:
        from google.cloud import monitoring_v3
        _monitoring_client = monitoring_v3.MetricServiceClient()
        _monitoring_available = True
        print(f"[google-tts] Cloud Monitoring enabled (project: {_project_id})")
        return True
    except ImportError:
        _monitoring_available = False
        print("[google-tts] Cloud Monitoring disabled: google-cloud-monitoring not installed. "
              "Run: pip install google-cloud-monitoring")
        return False
    except Exception as e:
        _monitoring_available = False
        print(f"[google-tts] Cloud Monitoring init error: {e}")
        return False


def query_cloud_monitoring_requests():
    """Interroga Cloud Monitoring per il numero di richieste TTS del mese corrente.

    Cloud Monitoring NON espone i caratteri consumati: solo i conteggi di
    richieste. Restituisce un dict:
        {
          "synthesize_requests": int,  # chiamate a SynthesizeSpeech
          "chirp3_requests": int,      # richieste contate sulla quota Chirp3
          "list_voices_requests": int,
          "interval_start_ts": int,
          "interval_end_ts": int,
        }
    o None in caso di errore.

    L'intervallo esclude gli ultimi `_MONITORING_STABILIZATION_LAG_SEC` secondi
    per usare solo aggregazioni stabilizzate.
    """
    if not _init_monitoring():
        return None

    try:
        from google.cloud import monitoring_v3
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        # Esclude gli ultimi N secondi per evitare metriche parziali
        end_ts = int(now.timestamp()) - _MONITORING_STABILIZATION_LAG_SEC
        # Inizio mese corrente UTC
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_ts = int(month_start.timestamp())

        # Se siamo nei primissimi minuti del mese, end_ts può essere < start_ts
        if end_ts <= start_ts:
            return 0

        interval = monitoring_v3.TimeInterval({
            "end_time": {"seconds": end_ts},
            "start_time": {"seconds": start_ts},
        })

        # IMPORTANTE: NON usare cross_series_reducer perché collasserebbe tutte
        # le serie in una sola, perdendo le label `method` e `quota_metric` che
        # ci servono per distinguere SynthesizeSpeech da ListVoices da chirp3.
        # Aggreghiamo solo lungo il tempo (per_series_aligner ALIGN_SUM).
        aggregation = monitoring_v3.Aggregation({
            "alignment_period": {"seconds": 86400},  # 1 giorno
            "per_series_aligner": monitoring_v3.Aggregation.Aligner.ALIGN_SUM,
        })

        # Filtro per metrica quota TTS — il filtro restituisce serie separate
        # per ogni combinazione di method/quota_metric
        filter_str = (
            'metric.type="serviceruntime.googleapis.com/quota/rate/net_usage" '
            'AND resource.labels.service="texttospeech.googleapis.com"'
        )

        results = _monitoring_client.list_time_series(
            request={
                "name": f"projects/{_project_id}",
                "filter": filter_str,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                "aggregation": aggregation,
            }
        )

        synth = 0
        chirp3 = 0
        list_voices = 0
        for ts in results:
            method = ts.metric.labels.get("method", "")
            quota_metric = ts.metric.labels.get("quota_metric", "")
            series_sum = 0
            for point in ts.points:
                series_sum += point.value.int64_value or int(point.value.double_value or 0)

            if "requests_chirp3" in quota_metric:
                chirp3 += series_sum
            elif "SynthesizeSpeech" in method:
                synth += series_sum
            elif "ListVoices" in method:
                list_voices += series_sum

        result = {
            "synthesize_requests": synth,
            "chirp3_requests": chirp3,
            "list_voices_requests": list_voices,
            "interval_start_ts": start_ts,
            "interval_end_ts": end_ts,
        }
        print(f"[google-tts] Cloud Monitoring requests: synth={synth}, chirp3={chirp3}, "
              f"list_voices={list_voices}")
        return result

    except Exception as e:
        print(f"[google-tts] Cloud Monitoring query error: {e}")
        return None


def diagnose_monitoring():
    """Diagnostica: elenca metriche TTS disponibili e serie temporali recenti.

    Restituisce un dict con:
      - metric_descriptors: lista di metriche tts/* o quota TTS disponibili
      - recent_series: serie temporali viste negli ultimi 24h con labels e somma valori

    Usato per capire QUALE metrica/filtro usare se la query principale non
    trova nulla. Da chiamare via endpoint admin.
    """
    if not _init_monitoring():
        return {"error": "Cloud Monitoring not initialized", "project_id": _project_id}

    try:
        from google.cloud import monitoring_v3
        from datetime import datetime, timezone, timedelta

        out = {
            "project_id": _project_id,
            "metric_descriptors": [],
            "queries": [],
        }

        # 1) Elenca metric descriptors relativi a TTS
        try:
            for md in _monitoring_client.list_metric_descriptors(
                request={"name": f"projects/{_project_id}"}
            ):
                mt = md.type
                if "texttospeech" in mt.lower() or (
                    "quota" in mt.lower() and "serviceruntime" in mt.lower()
                ):
                    out["metric_descriptors"].append({
                        "type": mt,
                        "kind": str(md.metric_kind),
                        "value_type": str(md.value_type),
                        "unit": md.unit,
                        "description": md.description[:200],
                    })
        except Exception as e:
            out["metric_descriptors_error"] = str(e)

        # 2) Prova diverse query e mostra cosa restituiscono
        now = datetime.now(timezone.utc)
        end_ts = int(now.timestamp())
        start_ts = int((now - timedelta(hours=24)).timestamp())
        interval = monitoring_v3.TimeInterval({
            "end_time": {"seconds": end_ts},
            "start_time": {"seconds": start_ts},
        })

        candidate_filters = [
            'metric.type="serviceruntime.googleapis.com/quota/rate/net_usage" '
            'AND resource.labels.service="texttospeech.googleapis.com"',
            'metric.type="serviceruntime.googleapis.com/quota/allocation/usage" '
            'AND resource.labels.service="texttospeech.googleapis.com"',
            'metric.type=starts_with("texttospeech.googleapis.com/")',
        ]

        for f in candidate_filters:
            q_result = {"filter": f, "series": []}
            try:
                results = _monitoring_client.list_time_series(
                    request={
                        "name": f"projects/{_project_id}",
                        "filter": f,
                        "interval": interval,
                        "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                    }
                )
                for ts in results:
                    series_sum = 0
                    n_points = 0
                    for point in ts.points:
                        val = point.value.int64_value or int(point.value.double_value or 0)
                        series_sum += val
                        n_points += 1
                    q_result["series"].append({
                        "metric_type": ts.metric.type,
                        "metric_labels": dict(ts.metric.labels),
                        "resource_labels": dict(ts.resource.labels),
                        "points": n_points,
                        "sum": series_sum,
                    })
            except Exception as e:
                q_result["error"] = str(e)
            out["queries"].append(q_result)

        return out

    except Exception as e:
        return {"error": str(e), "project_id": _project_id}


# Bound massimo plausibile di caratteri per richiesta SynthesizeSpeech.
# Allineato a CHUNK_MAX_CHARS in audiobook_app.py (2000), con 10% di tolleranza
# per piccole variazioni di chunking. Se viene superato → warning.
_MAX_CHARS_PER_REQUEST = 2200

# Stato ultima sanity check (per endpoint admin)
_last_sanity_check = None  # dict


def reconcile_with_cloud_monitoring():
    """Sanity-check del contatore locale contro il numero di richieste TTS
    realmente viste da Cloud Monitoring.

    Cloud Monitoring NON espone i caratteri consumati: solo i conteggi di
    richieste. Quindi il contatore locale resta la fonte di verità sui
    caratteri (gestito con reserve/refund atomico). Questa funzione verifica
    soltanto che il numero di caratteri locale sia coerente col numero di
    richieste effettivamente registrate da Google:

        local_chars  ≤  requests × MAX_CHARS_PER_REQUEST
        local_chars  ≥  requests × 1   (al netto di prenotazioni attive)

    Se i bound vengono violati, logga un warning. NON modifica mai il
    contatore locale.

    Restituisce un dict con lo stato della sanity check, o None se non eseguita.
    """
    global _last_reconcile_ts, _last_reconcile_value, _last_sanity_check

    if not _init_monitoring():
        return None

    cloud = query_cloud_monitoring_requests()
    if cloud is None:
        return None

    _last_reconcile_ts = time.time()
    _last_reconcile_value = cloud

    with _usage_lock:
        data = _load_usage()
        local_chars = data.get("chars_used", 0)

    # Numero di richieste rilevanti per i caratteri = SynthesizeSpeech
    # (chirp3_requests dovrebbe coincidere quando si usa Chirp3-HD)
    synth_requests = cloud.get("synthesize_requests", 0)
    chirp3_requests = cloud.get("chirp3_requests", 0)
    requests_used = max(synth_requests, chirp3_requests)

    expected_max = requests_used * _MAX_CHARS_PER_REQUEST
    expected_min = requests_used  # ≥1 char per richiesta

    warnings = []
    status = "ok"

    if requests_used == 0 and local_chars > 0:
        # Possibile: la latenza Cloud Monitoring non ha ancora propagato le
        # richieste. Non è un errore se il locale è recente.
        status = "info"
        warnings.append(
            f"local_chars={local_chars:,} but cloud reports 0 requests "
            f"(propagation lag possible, wait some minutes)"
        )
    elif local_chars > expected_max:
        status = "warn"
        warnings.append(
            f"local_chars={local_chars:,} > expected_max={expected_max:,} "
            f"({requests_used} requests × {_MAX_CHARS_PER_REQUEST} chars/req). "
            f"Local counter may be over-counting."
        )
    elif local_chars < expected_min:
        # Sospetto solo se locale è MOLTO sotto, perché un crash mid-deduct
        # può lasciare local sotto requests di poco.
        if expected_min - local_chars > 100:
            status = "warn"
            warnings.append(
                f"local_chars={local_chars:,} < expected_min={expected_min:,} "
                f"({requests_used} requests). Local counter may be under-counting "
                f"(chars consumed but not deducted)."
            )

    if warnings:
        for w in warnings:
            print(f"[google-tts] Sanity check {status.upper()}: {w}")
    else:
        avg = (local_chars / requests_used) if requests_used else 0
        print(f"[google-tts] Sanity check OK: local_chars={local_chars:,}, "
              f"requests={requests_used}, avg={avg:.0f} chars/req")

    _last_sanity_check = {
        "checked_at": _last_reconcile_ts,
        "local_chars": local_chars,
        "synthesize_requests": synth_requests,
        "chirp3_requests": chirp3_requests,
        "expected_max_chars": expected_max,
        "expected_min_chars": expected_min,
        "status": status,
        "warnings": warnings,
    }

    return {
        "local_chars": local_chars,
        "remaining": max(0, GOOGLE_TTS_MONTHLY_LIMIT - local_chars),
        "limit": GOOGLE_TTS_MONTHLY_LIMIT,
        "reconciled_at": _last_reconcile_ts,
        "sanity_check": _last_sanity_check,
        "note": "Cloud Monitoring exposes request counts only, not character counts. "
                "Local counter is the source of truth for chars.",
    }


def get_reconcile_status():
    """Restituisce lo stato dell'ultima sanity check (per endpoint admin)."""
    return {
        "monitoring_available": _monitoring_available,
        "project_id": _project_id,
        "last_check_ts": _last_reconcile_ts,
        "last_cloud_value": _last_reconcile_value,
        "last_sanity_check": _last_sanity_check,
    }
