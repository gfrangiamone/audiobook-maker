#!/usr/bin/env python3
"""tts_cloudflare_gemini_test.py — banco di prova Gemini 3.1 Flash TTS su Cloudflare Workers AI.

Misura costo reale, robustezza (troncamenti/risposte vuote), throughput e
parita' di qualita' rispetto al backend Vertex usato in produzione.

Riusa SOLO helper puri del progetto (gemini_tts, tts_split, audio_utils):
non importa mai audiobook_app ne' generation_engine, non tocca i job ne' i
database JSON.

Spec: docs/superpowers/specs/2026-08-25-cloudflare-gemini-tts-bench-design.md
"""
import argparse
import array
import base64
import binascii
import hashlib
import io
import json
import os
import sys
import threading
import time
import wave
import zipfile
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

# Il bench vive in scripts/: la root del progetto va in sys.path per importare
# gli helper puri (gemini_tts, tts_split, audio_utils).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audio_utils
import gemini_tts
import tts_split

# --- Costanti del banco di prova -------------------------------------------
CF_MODEL = "google/gemini-3.1-flash-tts"
CF_API_BASE = "https://api.cloudflare.com/client/v4/accounts"

# Tariffe Cloudflare per il modello (USD per milione di token).
CF_INPUT_USD_PER_MTOK = 0.75
CF_OUTPUT_USD_PER_MTOK = 12.00
USD_EUR_RATE = 0.86

# Token audio output per secondo. Sull'audit di produzione vale costantemente 25.
AUDIO_TOKENS_PER_SECOND = 25.0

# Formato PCM atteso da Gemini TTS: 24 kHz mono 16 bit.
EXPECTED_RATE = 24000
EXPECTED_CHANNELS = 1
EXPECTED_WIDTH = 2

# Banda del gate di durata (reale/attesa). Volutamente piu' larga della banda
# empirica di prod (0.75-1.35): qui serve a intercettare troncamenti
# grossolani, non a calibrare un preventivo.
RATIO_LOW = 0.6
RATIO_HIGH = 1.6

DEFAULT_CHUNK_CHARS = 450
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_SPEND_EUR = 2.00
HTTP_TIMEOUT_SEC = 60


class WavFormatError(Exception):
    """Il payload audio non e' un WAV leggibile o e' vuoto."""


def resolve_credentials():
    """Ritorna (account_id, api_token) dalle env. Esce con errore se mancano.

    Il valore del token non compare mai nel messaggio d'errore.
    """
    account_id = (os.environ.get("CF_ACCOUNT_ID") or "").strip()
    token = (os.environ.get("CF_API_TOKEN") or "").strip()
    missing = [n for n, v in (("CF_ACCOUNT_ID", account_id),
                              ("CF_API_TOKEN", token)) if not v]
    if missing:
        raise SystemExit(
            "Credenziali Cloudflare mancanti: " + ", ".join(missing) +
            ". Impostale nell'ambiente (vedi scripts/cf_tts_bench.env.ps1.example)."
        )
    return account_id, token


def wav_bytes_to_pcm(wav_bytes, out_path):
    """Scrive in `out_path` il PCM grezzo estratto dal WAV e ne ritorna il formato.

    Returns:
        {"rate": int, "channels": int, "width": int, "bytes": int}
    Raises:
        WavFormatError: payload non decodificabile o senza frame.
    """
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            rate = wf.getframerate()
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())
    except Exception as exc:
        raise WavFormatError(f"payload audio non decodificabile: {exc}") from exc
    if not frames:
        raise WavFormatError("WAV senza frame audio")
    with open(out_path, "wb") as fh:
        fh.write(frames)
    return {"rate": rate, "channels": channels, "width": width,
            "bytes": len(frames)}


class SpendCapExceeded(Exception):
    """Il cap di spesa del run e' stato raggiunto."""


def estimate_tokens(chars, audio_seconds, language):
    """Token input/output stimati per una chiamata.

    L'output usa i secondi audio REALI quando disponibili (dai byte PCM), non
    una previsione: l'unica approssimazione residua e' il rapporto
    token/secondo, che Cloudflare non espone in risposta.
    """
    return {
        "tokens_in": int(gemini_tts.estimate_input_tokens("x" * int(chars), language)),
        "tokens_out": int(round(float(audio_seconds) * AUDIO_TOKENS_PER_SECOND)),
    }


def cost_usd(tokens_in, tokens_out):
    """Costo USD di una chiamata alle tariffe Cloudflare."""
    return (tokens_in * CF_INPUT_USD_PER_MTOK / 1e6
            + tokens_out * CF_OUTPUT_USD_PER_MTOK / 1e6)


def predict_call_usd(chars, language):
    """Costo previsto PRIMA della chiamata, dal baseline char/sec della lingua."""
    seconds = float(chars) / gemini_tts.baseline_rate(language)
    tok = estimate_tokens(chars, seconds, language)
    return cost_usd(tok["tokens_in"], tok["tokens_out"])


class SpendGuard:
    """Accumulatore di spesa con tetto in euro. `max_eur=0` disattiva il tetto.

    Thread-safe: `reserve`/`settle` sono l'idioma di prenotazione atomica
    (lo stesso di `google_tts.reserve_chars`) usato dal livello matrix per
    evitare lo sforamento del cap sotto concorrenza. Il pattern check-poi-add
    non e' atomico: fra il controllo e la contabilizzazione la chiamata HTTP
    rilascia il GIL, e piu' thread vicini al cap possono superarlo tutti
    insieme. `check`/`add` restano disponibili per i chiamanti non
    concorrenti e sono anch'essi protetti dallo stesso lock.
    """

    def __init__(self, max_eur=DEFAULT_MAX_SPEND_EUR):
        self.max_eur = float(max_eur or 0)
        self.spent_usd = 0.0
        self._lock = threading.Lock()

    def spent_eur(self):
        return self.spent_usd * USD_EUR_RATE

    def check(self, projected_usd):
        """Solleva SpendCapExceeded se aggiungere `projected_usd` sfonda il cap."""
        with self._lock:
            self._check_locked(projected_usd)

    def _check_locked(self, projected_usd):
        if self.max_eur <= 0:
            return
        proiettato = (self.spent_usd + float(projected_usd)) * USD_EUR_RATE
        if proiettato > self.max_eur:
            raise SpendCapExceeded(
                f"cap di spesa raggiunto: {proiettato:.4f} EUR previsti "
                f"contro un tetto di {self.max_eur:.2f} EUR"
            )

    def add(self, usd):
        with self._lock:
            self.spent_usd += float(usd)

    def reserve(self, usd):
        """Prenota atomicamente `usd`: solleva SpendCapExceeded se sfonda il cap.

        Sotto lock il controllo e la contabilizzazione avvengono insieme,
        cosi' due thread non possono superare entrambi il controllo prima
        che uno dei due abbia gia' sommato la propria prenotazione.
        """
        with self._lock:
            self._check_locked(usd)
            self.spent_usd += float(usd)
            return float(usd)

    def settle(self, reserved, actual):
        """Corregge una prenotazione precedente con il costo effettivo."""
        with self._lock:
            self.spent_usd += float(actual) - float(reserved)


def evaluate_duration(chars, language, audio_seconds):
    """Confronta la durata reale dell'audio con quella attesa per il testo.

    Sostituisce il finish_reason che l'API Cloudflare non restituisce: senza
    questo controllo un chunk troncato e' indistinguibile da uno completo.
    """
    seconds = float(audio_seconds or 0.0)
    expected = float(chars or 0) / gemini_tts.baseline_rate(language)
    if seconds <= 0.0 or expected <= 0.0:
        return {"expected_seconds": expected, "ratio": 0.0, "anomaly": "empty"}
    ratio = seconds / expected
    anomaly = None
    if ratio < RATIO_LOW:
        anomaly = "truncated"
    elif ratio > RATIO_HIGH:
        anomaly = "overlong"
    return {"expected_seconds": expected, "ratio": ratio, "anomaly": anomaly}


def evaluate_format(fmt):
    """Ritorna "format" se il PCM decodificato non e' 24 kHz mono 16 bit."""
    if (fmt.get("rate") != EXPECTED_RATE
            or fmt.get("channels") != EXPECTED_CHANNELS
            or fmt.get("width") != EXPECTED_WIDTH):
        return "format"
    return None


class PaidCallCounter:
    """Conta i POST che hanno gia' ricevuto un HTTP 200, cioe' quelli che
    Cloudflare ha fatturato, in modo INDIPENDENTE da `metrics.jsonl`.

    Fra la risposta 200 e la scrittura del record c'e' una finestra (decodifica
    del WAV, valutazione del gate): un'interruzione li' dentro fa sparire dal
    conteggio una chiamata gia' pagata, e la riconciliazione finisce per
    dichiarare "nessuna chiamata" su un run che invece ha speso (fix round 4,
    difetto 1). Il contatore vive in memoria e serve solo a contraddire i
    totali calcolati sui record, mai a sostituirli.

    Thread-safe: il livello matrix incrementa da piu' worker.
    """

    def __init__(self):
        self._n = 0
        self._lock = threading.Lock()

    def bump(self):
        with self._lock:
            self._n += 1

    @property
    def count(self):
        with self._lock:
            return self._n


class CFAuthError(Exception):
    """Credenziali rifiutate da Cloudflare (401/403): nessun retry ha senso."""


class CFCallError(Exception):
    """Chiamata fallita dopo tutti i tentativi."""

    def __init__(self, message, status=None, attempts=0):
        super().__init__(message)
        self.status = status
        self.attempts = attempts


def build_payload(text, voice, temperature):
    """Corpo della richiesta /ai/run per il modello TTS."""
    return {
        "model": CF_MODEL,
        "input": {
            "text": text,
            "voice": voice,
            "temperature": float(temperature),
        },
    }


def _retry_after_seconds(resp, attempt):
    """Attesa prima del prossimo tentativo: header se presente, altrimenti 2^n."""
    raw = (resp.headers or {}).get("retry-after") if resp is not None else None
    if raw:
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
    return float(2 ** attempt)


def call_cf(session, account_id, api_token, text, voice, temperature,
            max_attempts=4, timeout=HTTP_TIMEOUT_SEC, sleep=time.sleep,
            on_billed=None):
    """Una sintesi su Cloudflare, con retry su 429/5xx e su timeout di rete.

    `on_billed` (opzionale) viene chiamata non appena la risposta e' un 200,
    PRIMA di qualunque parsing: da quel momento il POST e' fatturato e non
    deve poter sparire dai conteggi, qualunque cosa accada dopo (fix round 4,
    difetto 1).

    Returns:
        {"wav": bytes, "latency_ms": float, "status": int, "attempts": int,
         "retry_statuses": [int, ...]}
    Raises:
        CFAuthError: 401/403.
        CFCallError: tentativi esauriti o risposta 200 senza audio.
    """
    url = f"{CF_API_BASE}/{account_id}/ai/run"
    headers = {"Authorization": f"Bearer {api_token}",
               "Content-Type": "application/json"}
    payload = build_payload(text, voice, temperature)
    retry_statuses = []
    last_status = None
    for attempt in range(1, int(max_attempts) + 1):
        t0 = time.time()
        try:
            resp = session.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            latency_ms = (time.time() - t0) * 1000.0
            last_status = None
            retry_statuses.append(0)
            if attempt >= max_attempts:
                raise CFCallError(f"errore di rete dopo {attempt} tentativi: {exc}",
                                  status=None, attempts=attempt) from exc
            sleep(float(2 ** attempt))
            continue
        latency_ms = (time.time() - t0) * 1000.0
        last_status = resp.status_code
        if resp.status_code in (401, 403):
            # Il token non entra mai nel messaggio.
            raise CFAuthError(
                f"Cloudflare ha rifiutato le credenziali (HTTP {resp.status_code}): "
                f"verifica CF_ACCOUNT_ID e CF_API_TOKEN."
            )
        if resp.status_code == 429 or resp.status_code >= 500:
            retry_statuses.append(resp.status_code)
            if attempt >= max_attempts:
                raise CFCallError(
                    f"HTTP {resp.status_code} dopo {attempt} tentativi",
                    status=resp.status_code, attempts=attempt)
            sleep(_retry_after_seconds(resp, attempt))
            continue
        if resp.status_code != 200:
            raise CFCallError(f"HTTP {resp.status_code} non gestibile con retry",
                              status=resp.status_code, attempts=attempt)
        if callable(on_billed):
            # Da qui in poi la chiamata e' andata a buon fine lato Cloudflare:
            # e' fatturata anche se il corpo risultera' inutilizzabile o se il
            # processo viene interrotto durante la decodifica.
            on_billed()
        try:
            body = resp.json()
        except Exception as exc:
            raise CFCallError(f"risposta non JSON: {exc}",
                              status=resp.status_code, attempts=attempt) from exc
        audio_b64 = ((body.get("result") or {}).get("audio")
                     if isinstance(body, dict) else None)
        if not audio_b64:
            raise CFCallError("risposta 200 senza campo audio",
                              status=resp.status_code, attempts=attempt)
        try:
            wav_bytes = base64.b64decode(audio_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise CFCallError("campo audio non decodificabile da base64",
                              status=resp.status_code, attempts=attempt) from exc
        return {
            "wav": wav_bytes,
            "latency_ms": latency_ms,
            "status": resp.status_code,
            "attempts": attempt,
            "retry_statuses": retry_statuses,
        }
    raise CFCallError("tentativi esauriti", status=last_status,
                      attempts=int(max_attempts))


# --- Metriche: record, writer, run dir --------------------------------------
_RECORD_KEYS = (
    "ts", "run_id", "backend", "lang", "voice", "rate", "style_hash",
    "chunk_index", "chars", "prompt_bytes", "http_status", "latency_ms",
    "attempt", "audio_bytes", "audio_seconds", "expected_seconds", "ratio",
    "tokens_in_est", "tokens_out_est", "cost_usd_est", "anomaly",
)


def _utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def style_hash(style_instruction):
    """Firma corta dello stile: tiene le righe di metrica leggibili."""
    raw = (style_instruction or "").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:8]


def make_record(**kwargs):
    """Riga di `metrics.jsonl`. Schema fisso: le analisi leggono questo file."""
    rec = {"ts": _utc_now_iso()}
    for key in _RECORD_KEYS:
        if key == "ts":
            continue
        rec[key] = kwargs.get(key)
    extra = set(kwargs) - set(_RECORD_KEYS)
    if extra:
        raise ValueError(f"chiavi fuori schema in make_record: {sorted(extra)}")
    return rec


class MetricsWriter:
    """Append su `metrics.jsonl`, una riga JSON per chiamata."""

    def __init__(self, run_dir):
        self._path = os.path.join(run_dir, "metrics.jsonl")
        self._fh = open(self._path, "a", encoding="utf-8")

    @property
    def path(self):
        return self._path

    def write(self, record):
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass


def new_run_dir(out_root, level):
    """Crea e ritorna `out_root/<timestamp UTC>_<level>/` con audio/ e prompts/."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = os.path.join(out_root, f"{stamp}_{level}")
    for sub in ("audio", "prompts"):
        os.makedirs(os.path.join(run_dir, sub), exist_ok=True)
    return run_dir


# --- Sintesi di un chunk end-to-end + livello smoke -------------------------
class BenchContext:
    """Stato condiviso di un run: connessione, cartelle, metriche, budget."""

    def __init__(self, session, account_id, api_token, run_dir, writer, guard,
                 run_id, temperature=DEFAULT_TEMPERATURE, backend="cloudflare",
                 sleep=time.sleep, max_attempts=4):
        self.session = session
        self.account_id = account_id
        self.api_token = api_token
        self.run_dir = run_dir
        self.writer = writer
        self.guard = guard
        self.run_id = run_id
        self.temperature = temperature
        self.backend = backend
        self.sleep = sleep
        # Tentativi per chiamata su 429/5xx, passati a call_cf da _one_call.
        # Default 4, identico al default di call_cf: senza wiring esplicito
        # --max-attempts della CLI non avrebbe alcun effetto (fix round 1).
        self.max_attempts = max_attempts
        # POST andati a 200 (quindi fatturati), contati fuori da metrics.jsonl:
        # e' l'unico dato che sopravvive a un'interruzione fra la risposta e la
        # scrittura del record (fix round 4, difetto 1).
        self.paid_calls = PaidCallCounter()


def _one_call(ctx, final_text, chars, lang, voice, rate, style, pcm_path,
              chunk_index):
    """Una chiamata + decodifica + valutazione. Ritorna (record, seconds, path).

    Un `CFCallError` (tentativi HTTP esauriti, 4xx non ritentabile, audio non
    decodificabile) non interrompe il run: la spec impone che solo 401/403
    (CFAuthError, non catturata qui) provochi un abort immediato. Un chunk
    fallito dopo i retry di `call_cf` viene marcato "error" e riportato con
    una sola riga di metriche.
    """
    reserved = ctx.guard.reserve(predict_call_usd(chars, lang))
    settled = False
    billed = {"hit": False}

    def _on_billed():
        # Chiamata da call_cf appena arriva un 200: da quel momento il POST e'
        # fatturato, e nessuna uscita successiva puo' farlo sparire dai
        # conteggi (fix round 4, difetto 1).
        billed["hit"] = True
        ctx.paid_calls.bump()

    try:
        try:
            res = call_cf(ctx.session, ctx.account_id, ctx.api_token, final_text,
                          voice, ctx.temperature, max_attempts=ctx.max_attempts,
                          sleep=ctx.sleep, on_billed=_on_billed)
        except CFAuthError:
            # 401/403: nessun audio prodotto, la prenotazione va liberata prima
            # che l'eccezione risalga e interrompa il run (fix round 1).
            ctx.guard.settle(reserved, 0.0)
            settled = True
            raise
        except CFCallError as exc:
            # Un tentativo fallito non produce audio: la prenotazione va
            # liberata, non contabilizzata (decisione del Task 6).
            ctx.guard.settle(reserved, 0.0)
            settled = True
            expected_seconds = float(chars or 0) / gemini_tts.baseline_rate(lang)
            tok = estimate_tokens(chars, expected_seconds, lang)
            usd = cost_usd(tok["tokens_in"], tok["tokens_out"])
            record = make_record(
                run_id=ctx.run_id, backend=ctx.backend, lang=lang, voice=voice,
                rate=rate, style_hash=style_hash(style), chunk_index=chunk_index,
                chars=chars, prompt_bytes=len(final_text.encode("utf-8")),
                http_status=exc.status, latency_ms=None,
                attempt=exc.attempts, audio_bytes=None,
                audio_seconds=None, expected_seconds=expected_seconds,
                ratio=None, tokens_in_est=tok["tokens_in"],
                tokens_out_est=tok["tokens_out"], cost_usd_est=usd,
                anomaly="error",
            )
            ctx.writer.write(record)
            return record, None, None
        anomaly = None
        seconds = 0.0
        audio_bytes = 0
        try:
            fmt = wav_bytes_to_pcm(res["wav"], pcm_path)
            audio_bytes = fmt["bytes"]
            anomaly = evaluate_format(fmt)
            seconds = audio_utils.pcm_size_to_seconds(
                audio_bytes, sample_rate=fmt["rate"], channels=fmt["channels"],
                sample_width=fmt["width"])
        except WavFormatError:
            anomaly = "format"
            pcm_path = None
        dur = evaluate_duration(chars, lang, seconds)
        if anomaly is None:
            anomaly = dur["anomaly"]
        tok = estimate_tokens(chars, seconds, lang)
        usd = cost_usd(tok["tokens_in"], tok["tokens_out"])
        ctx.guard.settle(reserved, usd)
        settled = True
        record = make_record(
            run_id=ctx.run_id, backend=ctx.backend, lang=lang, voice=voice,
            rate=rate, style_hash=style_hash(style), chunk_index=chunk_index,
            chars=chars, prompt_bytes=len(final_text.encode("utf-8")),
            http_status=res["status"], latency_ms=res["latency_ms"],
            attempt=res["attempts"], audio_bytes=audio_bytes,
            audio_seconds=seconds, expected_seconds=dur["expected_seconds"],
            ratio=dur["ratio"], tokens_in_est=tok["tokens_in"],
            tokens_out_est=tok["tokens_out"], cost_usd_est=usd, anomaly=anomaly,
        )
        ctx.writer.write(record)
        return record, seconds, pcm_path
    finally:
        # Finding C (fix round 3): qualunque uscita non ancora liquidata sopra
        # (KeyboardInterrupt o un'eccezione imprevista fra reserve() e uno dei
        # settle() espliciti, es. durante la decodifica del WAV) non deve
        # lasciare la prenotazione agganciata a SpendGuard per sempre. Un
        # settle() gia' eseguito e' idempotente-safe da non ripetere: la
        # guardia `settled` lo garantisce.
        if not settled:
            # Direzione conservativa (fix round 4, difetto 1): se il 200 e'
            # gia' arrivato la chiamata e' fatturata, quindi la prenotazione
            # resta contabilizzata al costo previsto invece di essere
            # azzerata. Solo un'uscita PRIMA del 200 libera tutto: meglio
            # dichiarare una spesa in piu' di quante ne siano fatturate.
            ctx.guard.settle(reserved, reserved if billed["hit"] else 0.0)


def synth_chunk(ctx, text, chunk_index, lang, voice, rate, style, pcm_path):
    """Sintetizza un chunk; se il gate segnala un'anomalia, ritenta una volta.

    Il retry non e' un meccanismo di resilienza: serve a distinguere un guasto
    occasionale da un difetto sistematico del modello, e il report riporta
    entrambi gli esiti.
    """
    final_text = gemini_tts.build_final_text(text, style_instruction=style,
                                             rate=rate)
    os.makedirs(os.path.dirname(pcm_path), exist_ok=True)
    prompt_path = os.path.join(ctx.run_dir, "prompts", f"{chunk_index:04d}.txt")
    with open(prompt_path, "w", encoding="utf-8") as fh:
        fh.write(final_text)
    chars = len(text)
    record, seconds, path = _one_call(ctx, final_text, chars, lang, voice, rate,
                                      style, pcm_path, chunk_index)
    retry_record = None
    if record["anomaly"] and record["anomaly"] != "error":
        # "error" e' gia' l'esito di call_cf dopo i suoi tentativi HTTP
        # interni: non ha senso richiamare l'API una seconda volta qui.
        retry_path = pcm_path + ".retry.pcm"
        retry_record, r_seconds, r_path = _one_call(
            ctx, final_text, chars, lang, voice, rate, style, retry_path,
            chunk_index)
        if not retry_record["anomaly"]:
            path, seconds = r_path, r_seconds
    anomaly = retry_record["anomaly"] if retry_record else record["anomaly"]
    return {"record": record, "retry_record": retry_record, "pcm_path": path,
            "audio_seconds": seconds, "anomaly": anomaly}


def run_smoke(ctx, lang, voice, rate, style, text, compare_vertex=False):
    """Un solo chunk: verifica auth, schema di risposta e decodifica WAV.

    Se il chunk finisce con anomaly == "error" (CFCallError esaurita dentro
    call_cf), `audio_seconds`/`record['ratio']` sono None: la formattazione
    deve tollerarlo invece di sollevare TypeError (fix round 1, regressione
    critica: un run che ha gia' speso denaro deve comunque produrre un
    report).
    """
    pcm_path = os.path.join(ctx.run_dir, "audio", "0000.pcm")
    res = synth_chunk(ctx, text, 0, lang, voice, rate, style, pcm_path)
    seconds_txt = f"{res['audio_seconds']:.1f}s" if res["audio_seconds"] is not None else "n/d"
    ratio_txt = f"{res['record']['ratio']:.2f}" if res["record"]["ratio"] is not None else "n/d"
    print(f"[smoke] {lang}/{voice}: {seconds_txt} audio, "
          f"ratio {ratio_txt}, "
          f"anomalia {res['anomaly'] or 'nessuna'}")
    if compare_vertex and res["pcm_path"]:
        # Il confronto A/B e' un side-effect informativo: non altera
        # l'anomalia/residuo Cloudflare restituito da questa funzione.
        vertex_path = os.path.join(ctx.run_dir, "audio", "0000_vertex.pcm")
        try:
            v_res = synth_chunk_vertex(ctx, text, 0, lang, voice, rate, style,
                                       vertex_path)
            if v_res.get("pcm_path"):
                cmp = compare_metrics(res["pcm_path"], v_res["pcm_path"])
                print(f"[smoke][vertex] delta_seconds={cmp['delta_seconds']:.2f} "
                      f"rms_cf={cmp['rms_cf']:.1f} rms_vertex={cmp['rms_vertex']:.1f}")
        except Exception as exc:  # noqa: BLE001 - side-effect diagnostico
            print(f"[smoke][vertex] confronto non disponibile: {exc}")
    return 1 if res["anomaly"] else 0


# --- Aggregazione e report ----------------------------------------------------
def percentiles(values):
    """p50/p95/p99 per interpolazione lineare. Lista vuota -> zeri."""
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    def _p(q):
        if len(vals) == 1:
            return vals[0]
        pos = q * (len(vals) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(vals) - 1)
        return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)
    return {"p50": _p(0.50), "p95": _p(0.95), "p99": _p(0.99)}


def summarize(records):
    """Aggregati del run: volumi, costi, latenze, esiti HTTP, anomalie."""
    anomalies = {}
    for r in records:
        if r.get("anomaly"):
            anomalies[r["anomaly"]] = anomalies.get(r["anomaly"], 0) + 1
    cost_usd_tot = sum(float(r.get("cost_usd_est") or 0) for r in records)
    # Costo dei soli chunk falliti: e' incluso in cost_usd (lo schema dei
    # record non cambia) ma NON viene fatturato da Cloudflare, perche' una
    # chiamata fallita non produce audio. Tenerlo separato permette di
    # spiegare la divergenza fra report e footer invece di lasciarla
    # indovinare (fix round 4, difetto 3).
    falliti = [r for r in records if r.get("anomaly") == "error"]
    cost_usd_failed = sum(float(r.get("cost_usd_est") or 0) for r in falliti)
    return {
        "calls": len(records),
        "calls_failed": len(falliti),
        "cost_usd_failed": cost_usd_failed,
        "cost_eur_failed": cost_usd_failed * USD_EUR_RATE,
        "chars": sum(int(r.get("chars") or 0) for r in records),
        "audio_seconds": sum(float(r.get("audio_seconds") or 0) for r in records),
        "tokens_in": sum(int(r.get("tokens_in_est") or 0) for r in records),
        "tokens_out": sum(int(r.get("tokens_out_est") or 0) for r in records),
        "cost_usd": cost_usd_tot,
        "cost_eur": cost_usd_tot * USD_EUR_RATE,
        "latency": percentiles([r.get("latency_ms") for r in records]),
        "http_429": sum(1 for r in records if r.get("http_status") == 429),
        "http_5xx": sum(1 for r in records
                        if (r.get("http_status") or 0) >= 500),
        "anomalies": anomalies,
    }


def unrecorded_calls_note(n):
    """Testo unico (riconciliazione, report, stdout) per le chiamate pagate ma
    non registrate: un 200 gia' fatturato non deve sparire dai conteggi.
    """
    return (f"{int(n)} chiamata/e ha ricevuto HTTP 200 da Cloudflare (quindi "
            f"risulta fatturata) ma non compare in metrics.jsonl: il run e' "
            f"stato interrotto fra la risposta e la scrittura del record. "
            f"Ogni totale calcolato sui record e' sottostimato di altrettanto.")


def not_billed_note(agg):
    """Testo unico che spiega la divergenza fra il costo stimato dei chunk
    falliti e la spesa del footer (fix round 4, difetto 3).

    Non cambia alcun numero: dichiara solo che il footer, piu' basso, e' la
    cifra corretta, perche' una chiamata fallita non viene fatturata.
    """
    return (f"chunk con anomaly=error: {agg['calls_failed']}. Il loro costo "
            f"stimato (USD {agg['cost_usd_failed']:.4f} / "
            f"EUR {agg['cost_eur_failed']:.4f}) e' compreso nei totali qui "
            f"sopra, ma e' un costo NON fatturato da Cloudflare: una chiamata "
            f"fallita non produce audio. La spesa del footer ([fine] spesa "
            f"stimata Cloudflare) e' piu' bassa proprio per questo, ed e' la "
            f"sola spesa effettivamente addebitata.")


def reconciliation_block(records, unrecorded_paid_calls=0):
    """Blocco da confrontare con la fattura Cloudflare.

    Senza questo confronto il run misura il funzionamento, non il prezzo: il
    costo qui e' stimato, perche' l'API non restituisce i token consumati.

    `unrecorded_paid_calls` sono i 200 gia' fatturati che non hanno lasciato un
    record: se ce ne sono, il blocco lo dichiara invece di presentare i totali
    dei record come completi (fix round 4, difetto 1).
    """
    extra = ""
    if int(unrecorded_paid_calls or 0) > 0:
        extra = "\n  ATTENZIONE: " + unrecorded_calls_note(unrecorded_paid_calls)
    if not records:
        return ("RICONCILIAZIONE - nessuna chiamata registrata in "
                "metrics.jsonl." + extra)
    agg = summarize(records)
    ts = sorted(r["ts"] for r in records)
    return (
        f"RICONCILIAZIONE - finestra UTC {ts[0]} -> {ts[-1]}\n"
        f"  richieste           {agg['calls']}\n"
        f"  caratteri inviati   {agg['chars']}\n"
        f"  secondi audio       {agg['audio_seconds']:.0f}\n"
        f"  token input (stima)   {agg['tokens_in']}\n"
        f"  token output (stima)  {agg['tokens_out']}\n"
        f"  costo atteso        USD {agg['cost_usd']:.4f}   "
        f"EUR {agg['cost_eur']:.4f}\n"
        "  Confronta questi numeri con Cloudflare Dashboard -> Workers & Pages\n"
        "  -> AI -> Usage, selezionando esattamente la finestra qui sopra.\n"
        "  Nota: il costo e' STIMATO (l'API non restituisce i token). Finche'\n"
        "  non e' riconciliato, il risparmio atteso non e' dimostrato."
        + (("\n  Nota: " + not_billed_note(agg)) if agg["calls_failed"] else "")
        + extra
    )


def render_report(run_dir, records, residual_anomalies, partial, notes,
                  unrecorded_paid_calls=0):
    """Scrive `report.md` e ne ritorna il path.

    `unrecorded_paid_calls` sono i POST gia' andati a 200 (quindi fatturati)
    che non hanno lasciato un record: senza dichiararli, un report con
    "Chiamate 0" mentirebbe su un run che ha speso (fix round 4, difetto 1).
    """
    agg = summarize(records)
    lines = []
    lines.append("# Report banco di prova Cloudflare Gemini TTS")
    lines.append("")
    lines.append(f"Run: `{os.path.basename(run_dir)}`")
    if partial:
        lines.append("")
        lines.append("**RUN PARZIALE** - interrotto prima del completamento.")
    if int(unrecorded_paid_calls or 0) > 0:
        lines.append("")
        lines.append("**ATTENZIONE** - "
                     + unrecorded_calls_note(unrecorded_paid_calls))
    lines.append("")
    lines.append("## Volumi e costo")
    lines.append("")
    lines.append("| Metrica | Valore |")
    lines.append("|---|---|")
    lines.append(f"| Chiamate | {agg['calls']} |")
    lines.append(f"| Caratteri | {agg['chars']} |")
    lines.append(f"| Audio (s) | {agg['audio_seconds']:.1f} |")
    lines.append(f"| Token input (stima) | {agg['tokens_in']} |")
    lines.append(f"| Token output (stima) | {agg['tokens_out']} |")
    lines.append(f"| Costo stimato | USD {agg['cost_usd']:.4f} / "
                 f"EUR {agg['cost_eur']:.4f} |")
    if agg["calls_failed"]:
        # Difetto 3 (round 4): la riga sopra include il costo dei chunk
        # falliti, il footer del run no. Le due cifre restano quelle che
        # sono; qui si dichiara quale parte non e' fatturata e perche'.
        lines.append(f"| di cui costo stimato NON fatturato (chunk falliti) | "
                     f"USD {agg['cost_usd_failed']:.4f} / "
                     f"EUR {agg['cost_eur_failed']:.4f} |")
    lines.append("")
    if agg["calls_failed"]:
        lines.append(not_billed_note(agg))
        lines.append("")
    lines.append("## Latenza e affidabilita'")
    lines.append("")
    lines.append("| Metrica | Valore |")
    lines.append("|---|---|")
    lines.append(f"| Latenza p50 (ms) | {agg['latency']['p50']:.0f} |")
    lines.append(f"| Latenza p95 (ms) | {agg['latency']['p95']:.0f} |")
    lines.append(f"| Latenza p99 (ms) | {agg['latency']['p99']:.0f} |")
    lines.append(f"| Risposte 429 | {agg['http_429']} |")
    lines.append(f"| Risposte 5xx | {agg['http_5xx']} |")
    lines.append("")
    lines.append("## Anomalie")
    lines.append("")
    lines.append(f"anomalie residue: {residual_anomalies}")
    lines.append("")
    failed = [r for r in records if r.get("anomaly") == "error"]
    lines.append(f"chunk falliti (anomaly=error): {len(failed)}")
    if failed:
        lines.append("")
        lines.append("| chunk_index | http_status | attempt |")
        lines.append("|---|---|---|")
        for r in sorted(failed, key=lambda r: (r.get("chunk_index") is None,
                                                r.get("chunk_index"))):
            status = r.get("http_status")
            attempt = r.get("attempt")
            lines.append(f"| {r.get('chunk_index')} "
                         f"| {'-' if status is None else status} "
                         f"| {'-' if attempt is None else attempt} |")
    lines.append("")
    if agg["anomalies"]:
        lines.append("| Tipo | Occorrenze (incluse quelle corrette dal retry) |")
        lines.append("|---|---|")
        for tipo, n in sorted(agg["anomalies"].items()):
            lines.append(f"| {tipo} | {n} |")
    else:
        lines.append("Nessuna anomalia rilevata.")
    lines.append("")
    lines.append("## Riconciliazione")
    lines.append("")
    lines.append("```")
    lines.append(reconciliation_block(
        records, unrecorded_paid_calls=unrecorded_paid_calls))
    lines.append("```")
    if notes:
        lines.append("")
        lines.append("## Note")
        lines.append("")
        for n in notes:
            lines.append(f"- {n}")
    path = os.path.join(run_dir, "report.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


# --- Livello matrix: lingua x voce x velocita' x stile -----------------------
# Fixture brevi per il livello matrix: ~200 char, frasi complete, punteggiatura
# varia. Servono a confrontare voci e stili a parita' di testo, non a misurare
# la resa su testo lungo (per quello c'e' il livello book).
FIXTURES = {
    "it": ("Il vento della sera attraversava la valle, e con esso arrivava "
           "l'odore della pioggia. Nessuno parlava. In fondo al sentiero, "
           "una luce si accese: qualcuno stava ancora aspettando."),
    "en": ("The evening wind moved across the valley, carrying the smell of "
           "rain with it. Nobody spoke. At the end of the path a light came "
           "on: someone was still waiting."),
    "fr": ("Le vent du soir traversait la vallee, apportant avec lui l'odeur "
           "de la pluie. Personne ne parlait. Au bout du sentier, une lumiere "
           "s'alluma: quelqu'un attendait encore."),
    "es": ("El viento de la tarde cruzaba el valle, y con el llegaba el olor "
           "de la lluvia. Nadie hablaba. Al final del sendero se encendio una "
           "luz: alguien seguia esperando."),
    "de": ("Der Abendwind zog durch das Tal und brachte den Geruch von Regen "
           "mit sich. Niemand sprach. Am Ende des Weges ging ein Licht an: "
           "jemand wartete noch."),
}
FIXTURES["default"] = FIXTURES["en"]


def matrix_combinations(langs, voices, rates, styles, runs=1):
    """Prodotto cartesiano delle dimensioni del livello matrix."""
    styles = list(styles) if styles else [None]
    combos = []
    for lang in langs:
        for voice in voices:
            for rate in rates:
                for style in styles:
                    for n in range(1, int(runs) + 1):
                        combos.append({"lang": lang, "voice": voice,
                                       "rate": rate, "style": style, "run": n})
    return combos


def fixture_for(lang):
    return FIXTURES.get((lang or "")[:2].lower(), FIXTURES["default"])


def run_matrix(ctx, combos, concurrency=1, compare_vertex=False):
    """Esegue tutte le combinazioni; ritorna il numero di anomalie residue.

    Il cap di spesa si applica all'intero run: se scatta (SpendCapExceeded) o
    se le credenziali vengono rifiutate (CFAuthError), il run si ferma e
    l'eccezione si propaga al chiamante, che scrive un report parziale.
    Sotto concorrenza l'arresto non e' istantaneo: i task gia' avviati (al
    massimo `concurrency`) arrivano comunque a completamento, i task non
    ancora avviati vengono saltati o cancellati.

    `compare_vertex` e' un side-effect informativo (righe extra backend
    "vertex" in metrics.jsonl): non tocca ne' il cap di spesa Cloudflare ne'
    il conteggio di anomalie residue ritornato da questa funzione.
    """
    def _one(i_combo):
        i, combo = i_combo
        text = fixture_for(combo["lang"])
        pcm_path = os.path.join(ctx.run_dir, "audio", f"{i:04d}.pcm")
        res = synth_chunk(ctx, text, i, combo["lang"], combo["voice"],
                          combo["rate"], combo["style"], pcm_path)
        if compare_vertex and res["pcm_path"]:
            vertex_path = os.path.join(ctx.run_dir, "audio", f"{i:04d}_vertex.pcm")
            try:
                v_res = synth_chunk_vertex(ctx, text, i, combo["lang"],
                                           combo["voice"], combo["rate"],
                                           combo["style"], vertex_path)
                if v_res.get("pcm_path"):
                    # Stessa disciplina di run_smoke (fix round 2): il
                    # confronto A/B a matrix scriveva solo le righe "vertex"
                    # in metrics.jsonl, senza mai calcolare le metriche di
                    # confronto (delta_seconds/RMS) richieste dalla
                    # decisione vincolante del coordinatore.
                    cmp = compare_metrics(res["pcm_path"], v_res["pcm_path"])
                    print(f"[matrix][vertex] chunk {i}: "
                          f"delta_seconds={cmp['delta_seconds']:.2f} "
                          f"rms_cf={cmp['rms_cf']:.1f} "
                          f"rms_vertex={cmp['rms_vertex']:.1f}")
            except Exception as exc:  # noqa: BLE001 - side-effect diagnostico
                print(f"[matrix][vertex] chunk {i} confronto non disponibile: {exc}")
        return res

    if int(concurrency) <= 1:
        residue = 0
        for item in enumerate(combos):
            residue += 1 if _one(item)["anomaly"] else 0
        return residue

    stop = threading.Event()

    def _guarded(i_combo):
        if stop.is_set():
            return None
        try:
            return _one(i_combo)
        except (SpendCapExceeded, CFAuthError):
            stop.set()
            raise

    residue = 0
    fatal = None
    with ThreadPoolExecutor(max_workers=int(concurrency)) as pool:
        futures = [pool.submit(_guarded, item) for item in enumerate(combos)]
        for fut in as_completed(futures):
            try:
                res = fut.result()
            except (SpendCapExceeded, CFAuthError) as exc:
                if fatal is None:
                    fatal = exc
                stop.set()
                for f in futures:
                    f.cancel()
                continue
            except CancelledError:
                continue
            if res is not None and res["anomaly"]:
                residue += 1
    if fatal is not None:
        raise fatal
    return residue


# --- Livello book: parsing, chunking di produzione e assembly M4B -----------
def _abm_safe_name(name):
    """Guardia zip-slip minimale sui nomi interni all'archivio."""
    norm = os.path.normpath(name).replace("\\", "/")
    if norm.startswith("/") or norm.startswith(".."):
        raise ValueError(f"nome di archivio non sicuro: {name!r}")
    return norm


def parse_book(path):
    """Legge un .abm o un .txt.

    Returns:
        {"title", "author", "language", "chapters": [(idx, titolo, testo)],
         "cover_bytes": bytes|None}
    """
    if path.lower().endswith(".abm"):
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())
            if "manifest.json" not in names:
                raise ValueError("File .abm non valido: manifest.json assente")
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            if manifest.get("format") != "audiobook-maker-project":
                raise ValueError("File .abm non valido: formato sconosciuto")
            chapters = []
            for cm in manifest.get("chapters", []):
                fname = cm.get("file") or ""
                raw = fname if fname.startswith("chapters/") else f"chapters/{fname}"
                raw = _abm_safe_name(raw)
                if raw not in names:
                    continue
                text = zf.read(raw).decode("utf-8", errors="replace")
                chapters.append((cm.get("index", len(chapters) + 1),
                                 cm.get("title") or f"Capitolo {len(chapters) + 1}",
                                 text))
            if not chapters:
                raise ValueError("File .abm senza capitoli leggibili")
            cover = None
            if manifest.get("has_cover") and manifest.get("cover_file"):
                cf = _abm_safe_name(manifest["cover_file"])
                if cf in names:
                    cover = zf.read(cf)
            return {
                "title": manifest.get("title")
                         or os.path.splitext(os.path.basename(path))[0],
                "author": manifest.get("author", ""),
                "language": manifest.get("language", ""),
                "chapters": chapters,
                "cover_bytes": cover,
            }
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    title = os.path.splitext(os.path.basename(path))[0]
    return {"title": title, "author": "", "language": "",
            "chapters": [(1, title, text)], "cover_bytes": None}


def chapter_markers(pcm_paths, titles):
    """Marker capitoli in millisecondi, dalla dimensione dei PCM."""
    out = []
    cursor = 0.0
    for path, title in zip(pcm_paths, titles):
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        dur_ms = audio_utils.pcm_size_to_seconds(
            size, sample_rate=EXPECTED_RATE, channels=EXPECTED_CHANNELS,
            sample_width=EXPECTED_WIDTH) * 1000.0
        out.append({"title": title, "start": cursor, "end": cursor + dur_ms})
        cursor += dur_ms
    return out


def _run_chunk_jobs(jobs, worker, concurrency):
    """Esegue `jobs` con `worker`, in ordine di sottomissione (non di completamento).

    Stesso pattern anti-spreco di `run_matrix` (Task 8): un `threading.Event`
    di stop controllato PRIMA di ogni chiamata pagata, e la cancellazione dei
    future non ancora partiti appena scatta un errore fatale
    (`SpendCapExceeded`/`CFAuthError`). `Executor.map` da solo non basta,
    perche' mette in coda tutti i job subito: un chunk fallito a meta' lista
    lascerebbe comunque partire (e pagare) tutti quelli gia' accodati prima
    che l'eccezione risalga da `shutdown(wait=True)`.

    A differenza di `run_matrix`, qui l'ordine dei risultati conta: `run_book`
    concatena il PCM in sequenza, quindi i risultati sono indicizzati sulla
    posizione di sottomissione e non sull'ordine di `as_completed`. Se scatta
    un errore fatale la funzione non ritorna mai una lista parziale: rilancia
    l'eccezione, quindi eventuali `None` residui nello slot non sono mai
    osservati dal chiamante.
    """
    if int(concurrency) <= 1:
        return [worker(job) for job in jobs]

    stop = threading.Event()

    def _guarded(job):
        if stop.is_set():
            return None
        try:
            return worker(job)
        except (SpendCapExceeded, CFAuthError):
            stop.set()
            raise

    results = [None] * len(jobs)
    fatal = None
    with ThreadPoolExecutor(max_workers=int(concurrency)) as pool:
        futures = {pool.submit(_guarded, job): i for i, job in enumerate(jobs)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except (SpendCapExceeded, CFAuthError) as exc:
                if fatal is None:
                    fatal = exc
                stop.set()
                for f in futures:
                    f.cancel()
                continue
            except CancelledError:
                continue
    if fatal is not None:
        raise fatal
    return results


def run_book(ctx, book, voice, rate, style, chunk_chars, concurrency, out_m4b,
             lang=None):
    """Genera l'intero libro e ne assembla l'M4B. Ritorna (anomalie, path|None).

    Un chunk fallito (anomaly="error", vedi synth_chunk/_one_call) non ha
    pcm_path: viene contato fra le anomalie residue ma escluso dall'assembly,
    cosi' un singolo guasto HTTP non ferma la generazione dell'intero libro.

    `lang`, se passato esplicitamente (es. da --langs sulla CLI), sovrascrive
    la lingua dichiarata nei metadati del libro; altrimenti i metadati del
    libro restano il fallback (fix round 1: prima il parametro non esisteva e
    --langs veniva ignorato a livello book).
    """
    lang = (lang or book.get("language") or "en")[:2].lower()
    residue = 0
    chapter_pcms = []
    chapter_titles = []
    index = 0
    for ch_pos, (ch_idx, ch_title, ch_text) in enumerate(book["chapters"]):
        chunks = tts_split.split_text_into_chunks(ch_text, max_chars=int(chunk_chars))
        parts = []
        jobs = []
        for chunk in chunks:
            pcm_path = os.path.join(ctx.run_dir, "audio", f"{index:04d}.pcm")
            jobs.append((index, chunk, pcm_path))
            index += 1

        def _one(job):
            i, chunk, pcm_path = job
            return synth_chunk(ctx, chunk, i, lang, voice, rate, style, pcm_path)

        results = _run_chunk_jobs(jobs, _one, concurrency)
        for res in results:
            if res is None:
                # Job saltato o cancellato da un abort fatale: _run_chunk_jobs
                # rilancia comunque l'eccezione, ma la guardia tiene la
                # lettura difensiva come in run_matrix.
                continue
            if res["anomaly"]:
                residue += 1
            if res["pcm_path"]:
                parts.append(res["pcm_path"])
        if not parts:
            # Capitolo interamente fallito (tutti i chunk in errore): niente
            # PCM da concatenare. Decisione esplicita: il capitolo viene
            # scartato dall'M4B finale, il libro prosegue con gli altri.
            continue
        # Il nome file usa la posizione nel ciclo (ch_pos), MAI l'indice del
        # manifest (ch_idx): un .abm malformato con index duplicati o
        # mancanti farebbe collidere due capitoli sullo stesso path PCM,
        # sovrascrivendo silenziosamente l'audio del primo.
        ch_pcm = os.path.join(ctx.run_dir, "audio", f"cap{ch_pos:03d}.pcm")
        audio_utils.pcm_concat(parts, ch_pcm, skip_missing=True,
                               sample_rate=EXPECTED_RATE,
                               channels=EXPECTED_CHANNELS,
                               sample_width=EXPECTED_WIDTH)
        chapter_pcms.append(ch_pcm)
        chapter_titles.append(ch_title)

    if not chapter_pcms:
        return residue, None
    cover_path = None
    if book.get("cover_bytes"):
        cover_path = os.path.join(ctx.run_dir, "cover.jpg")
        with open(cover_path, "wb") as fh:
            fh.write(book["cover_bytes"])
    ok = audio_utils.pcm_to_aac_m4b(
        chapter_pcms, out_m4b, sample_rate=EXPECTED_RATE,
        channels=EXPECTED_CHANNELS, sample_width=EXPECTED_WIDTH,
        chapters=chapter_markers(chapter_pcms, chapter_titles),
        title=book.get("title"), author=book.get("author"),
        cover_path=cover_path, language=book.get("language"))
    return residue, (out_m4b if ok else None)


# --- Ramo A/B contro Vertex --------------------------------------------------
def vertex_available():
    """True se le credenziali Vertex di produzione sono configurate."""
    try:
        return gemini_tts._resolve_backend() == "vertex"
    except Exception:
        return False


def synth_chunk_vertex(ctx, text, chunk_index, lang, voice_name, rate, style,
                       pcm_path):
    """Gemello Vertex di `synth_chunk`, per l'A/B.

    `gemini_tts.synthesize` costruisce internamente il prompt con
    build_final_text: qui va passato il testo grezzo, non quello gia' composto,
    altrimenti il blocco [style: ...] verrebbe applicato due volte.

    Un guasto Vertex marca il chunk (anomaly="error") senza interrompere il
    confronto: stessa disciplina del ramo Cloudflare (_one_call).
    """
    os.makedirs(os.path.dirname(pcm_path), exist_ok=True)
    t0 = time.time()
    try:
        res = gemini_tts.synthesize(
            text, f"gemini:flash31:{voice_name}", rate=rate,
            output_path=pcm_path, style_instruction=style)
    except Exception as exc:
        # Diagnostica limitata: e' un messaggio d'eccezione, mai il payload
        # della richiesta ne' un header, quindi non puo' contenere credenziali.
        # Il record resta a schema fisso (21 chiavi): la distinzione fra
        # GeminiUnavailable/quota/payload-cap/RuntimeError vive solo nel log,
        # stessa convenzione di gemini_tts.py (retry loop di `synthesize`).
        print(f"[bench-vertex] chunk {chunk_index} fallito: {str(exc)[:200]}")
        latency_ms = (time.time() - t0) * 1000.0
        expected_seconds = float(len(text) or 0) / gemini_tts.baseline_rate(lang)
        record = make_record(
            run_id=ctx.run_id, backend="vertex", lang=lang, voice=voice_name,
            rate=rate, style_hash=style_hash(style), chunk_index=chunk_index,
            chars=len(text),
            prompt_bytes=len(gemini_tts.build_final_text(
                text, style_instruction=style, rate=rate).encode("utf-8")),
            http_status=None, latency_ms=latency_ms, attempt=1,
            audio_bytes=None, audio_seconds=None,
            expected_seconds=expected_seconds, ratio=None,
            # Nessun token disponibile: la chiamata e' fallita prima di
            # ritornare bytes_written/input_tokens/output_tokens.
            tokens_in_est=0, tokens_out_est=0, cost_usd_est=0.0,
            anomaly="error",
        )
        ctx.writer.write(record)
        return {"record": record, "retry_record": None, "pcm_path": None,
                "audio_seconds": None, "anomaly": "error"}
    latency_ms = (time.time() - t0) * 1000.0
    audio_bytes = int(res.get("bytes_written") or 0)
    seconds = audio_utils.pcm_size_to_seconds(
        audio_bytes, sample_rate=EXPECTED_RATE, channels=EXPECTED_CHANNELS,
        sample_width=EXPECTED_WIDTH)
    dur = evaluate_duration(len(text), lang, seconds)
    tokens_in = int(res.get("input_tokens") or 0)
    tokens_out = int(res.get("output_tokens") or 0)
    # Costo Google reale, solo per la colonna del record: il ramo Vertex non
    # tocca mai ctx.guard (SpendGuard resta il cap sulla sola spesa
    # Cloudflare). Senza questo calcolo il confronto A/B mostrerebbe sempre
    # EUR 0.00 su Vertex, vanificando lo scopo del bench.
    cost_usd_est = gemini_tts.google_cost_breakdown(
        tokens_in, tokens_out, "flash31")["total_usd"]
    record = make_record(
        run_id=ctx.run_id, backend="vertex", lang=lang, voice=voice_name,
        rate=rate, style_hash=style_hash(style), chunk_index=chunk_index,
        chars=len(text),
        prompt_bytes=len(gemini_tts.build_final_text(
            text, style_instruction=style, rate=rate).encode("utf-8")),
        http_status=200, latency_ms=latency_ms,
        attempt=int(res.get("attempts_used") or 1), audio_bytes=audio_bytes,
        audio_seconds=seconds, expected_seconds=dur["expected_seconds"],
        ratio=dur["ratio"],
        tokens_in_est=tokens_in, tokens_out_est=tokens_out,
        cost_usd_est=cost_usd_est,
        anomaly=dur["anomaly"],
    )
    ctx.writer.write(record)
    return {"record": record, "retry_record": None, "pcm_path": pcm_path,
            "audio_seconds": seconds, "anomaly": dur["anomaly"]}


def _pcm_rms(path):
    """RMS dei campioni 16 bit di un PCM. 0.0 se il file non e' leggibile."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return 0.0
    if len(raw) < 2:
        return 0.0
    samples = array.array("h")
    samples.frombytes(raw[:len(raw) - (len(raw) % 2)])
    if not samples:
        return 0.0
    return (sum(float(s) * float(s) for s in samples) / len(samples)) ** 0.5


def compare_metrics(pcm_cf, pcm_vertex):
    """Metriche oggettive dell'A/B. Il giudizio sulla resa resta l'ascolto."""
    def _sec(p):
        try:
            size = os.path.getsize(p)
        except OSError:
            return 0.0
        return audio_utils.pcm_size_to_seconds(
            size, sample_rate=EXPECTED_RATE, channels=EXPECTED_CHANNELS,
            sample_width=EXPECTED_WIDTH)
    s_cf, s_vx = _sec(pcm_cf), _sec(pcm_vertex)
    return {"seconds_cf": s_cf, "seconds_vertex": s_vx,
            "delta_seconds": s_cf - s_vx,
            "rms_cf": _pcm_rms(pcm_cf), "rms_vertex": _pcm_rms(pcm_vertex)}


# --- CLI e orchestrazione del run --------------------------------------------
def split_csv(value):
    """'it, en ,fr' -> ['it','en','fr']. Vuoto o None -> []."""
    if not value:
        return []
    return [p.strip() for p in str(value).split(",") if p.strip()]


def build_arg_parser():
    ap = argparse.ArgumentParser(
        description="Banco di prova Gemini 3.1 Flash TTS su Cloudflare Workers AI")
    ap.add_argument("--level", choices=("smoke", "matrix", "book"),
                    default="smoke",
                    help="smoke: un chunk. matrix: prodotto cartesiano su "
                         "fixture corte. book: libro reale fino all'M4B.")
    ap.add_argument("--book", default=None,
                    help="File .abm o .txt (obbligatorio con --level book)")
    ap.add_argument("--langs", default="it,en", help="Lingue separate da virgola")
    ap.add_argument("--voices", default="Zephyr", help="Voci separate da virgola")
    ap.add_argument("--rates", default="+0%", help="Velocita' separate da virgola")
    ap.add_argument("--styles", default="",
                    help="Istruzioni di stile separate da virgola (max 200 char)")
    ap.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS,
                    help=f"Caratteri per chunk (default {DEFAULT_CHUNK_CHARS}, "
                         "pari a ABM_GEMINI_CHUNK_CHARS di produzione)")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="Chiamate parallele")
    ap.add_argument("--runs", type=int, default=1,
                    help="Ripetizioni della stessa combinazione (varianza)")
    ap.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE,
                    help=f"Temperature (default {DEFAULT_TEMPERATURE})")
    ap.add_argument("--max-spend-eur", type=float, default=DEFAULT_MAX_SPEND_EUR,
                    help=f"Tetto di spesa stimata (default "
                         f"{DEFAULT_MAX_SPEND_EUR:.2f}; 0 disattiva)")
    ap.add_argument("--compare", choices=("vertex",), default=None,
                    help="Genera anche il gemello Vertex per l'A/B")
    ap.add_argument("--out-dir", default="./out", help="Radice degli artefatti")
    ap.add_argument("--max-attempts", type=int, default=4,
                    help="Tentativi per chiamata su 429/5xx")
    return ap


def _build_session(concurrency):
    """Crea la Session HTTP con il pool dimensionato sulla concorrenza.

    Con `pool_maxsize` di default (10 in requests) e --concurrency oltre 10
    il pool di connessioni va in thrashing: connessioni scartate e riaperte
    di continuo (Minor rimandato dal Task 8). L'adapter viene dimensionato
    sulla concorrenza effettiva del run, con un minimo di 10 per non ridurre
    la size di default quando la concorrenza e' bassa.
    """
    session = requests.Session()
    pool_size = max(10, int(concurrency))
    adapter = requests.adapters.HTTPAdapter(pool_connections=pool_size,
                                            pool_maxsize=pool_size)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _flag_present(argv_list, flag):
    """True se `flag` (es. "--langs") compare esplicitamente in argv.

    argparse non distingue da solo un default implicito da un valore passato
    apposta dall'utente (il default di --langs e' una stringa non-None, non
    un sentinel): per sapere se l'utente ha davvero chiesto una lingua a
    livello book bisogna guardare gli argomenti grezzi. Riconosce sia la
    forma "--flag valore" sia "--flag=valore".
    """
    prefix = flag + "="
    return any(a == flag or a.startswith(prefix) for a in argv_list)


def _residual_anomalies(records):
    """Conta le anomalie residue, un chunk = una riga, dedup per chunk_index.

    Un chunk ritentato (`synth_chunk`) scrive due righe con lo stesso
    chunk_index: contare le righe grezze conterebbe due volte un'anomalia
    gia' corretta dal retry. `MetricsWriter` scrive in append rigorosamente
    in ordine di produzione, quindi l'ultima riga vista per un dato
    chunk_index e' sempre l'esito finale di quel chunk (fix round 1).
    """
    last_by_index = {}
    senza_indice = []
    for r in records:
        idx = r.get("chunk_index")
        if idx is None:
            senza_indice.append(r)
        else:
            last_by_index[idx] = r
    finali = list(last_by_index.values()) + senza_indice
    return sum(1 for r in finali if r.get("anomaly"))


def main(argv=None):
    """Punto d'ingresso della CLI.

    Le credenziali (CF_ACCOUNT_ID/CF_API_TOKEN, e per Vertex quelle lette da
    gemini_tts) arrivano SOLO dall'ambiente: mai un argomento CLI, mai un
    valore stampato in output (help, header di run, report o messaggi
    d'errore compresi).
    """
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    args = build_arg_parser().parse_args(argv_list)
    if args.level == "book" and not args.book:
        print("[errore] --level book richiede --book <file.abm|file.txt>")
        return 1
    if args.level == "book" and args.compare == "vertex":
        # Un libro intero puo' gia' costare parecchio: raddoppiarlo con il
        # gemello Vertex per errore non e' accettabile. Il confronto A/B va
        # fatto a --level matrix, dove il costo resta contenuto e la
        # combinazione lingua/voce/stile e' comunque confrontabile.
        print("[errore] --compare vertex non e' supportato a --level book "
              "(raddoppierebbe il costo di un run lungo). Usa --level "
              "matrix per il confronto A/B.")
        return 1
    if args.compare == "vertex" and not vertex_available():
        # Fallire qui, prima di spendere su Cloudflare, e' il punto: un A/B
        # a meta' non serve a nulla ma costa comunque.
        print("[errore] --compare vertex richiede le credenziali Vertex "
              "(ABM_GEMINI_BACKEND, ABM_GCP_PROJECT_ID, "
              "ABM_GOOGLE_CREDENTIALS_FILE). Nessuna chiamata effettuata.")
        return 1
    account_id, api_token = resolve_credentials()

    run_dir = new_run_dir(args.out_dir, args.level)
    writer = MetricsWriter(run_dir)
    ctx = BenchContext(
        session=_build_session(args.concurrency), account_id=account_id,
        api_token=api_token, run_dir=run_dir, writer=writer,
        guard=SpendGuard(args.max_spend_eur),
        run_id=os.path.basename(run_dir), temperature=args.temperature,
        backend="cloudflare", max_attempts=args.max_attempts)

    langs = split_csv(args.langs) or ["en"]
    voices = split_csv(args.voices) or ["Zephyr"]
    rates = split_csv(args.rates) or ["+0%"]
    styles = split_csv(args.styles)
    compare_vertex = (args.compare == "vertex")
    notes = []
    partial = False
    m4b_path = None
    try:
        if args.level == "smoke":
            run_smoke(ctx, langs[0], voices[0], rates[0],
                     styles[0] if styles else None, fixture_for(langs[0]),
                     compare_vertex=compare_vertex)
        elif args.level == "matrix":
            combos = matrix_combinations(langs, voices, rates, styles, args.runs)
            print(f"[matrix] {len(combos)} combinazioni, "
                  f"concorrenza {args.concurrency}")
            run_matrix(ctx, combos, args.concurrency,
                      compare_vertex=compare_vertex)
        else:
            book = parse_book(args.book)
            out_m4b = os.path.join(run_dir, "audio", "cloudflare.m4b")
            # --langs esplicito sovrascrive la lingua del libro; altrimenti
            # i metadati del libro restano il fallback (vedi run_book).
            book_lang = langs[0] if _flag_present(argv_list, "--langs") else None
            _, m4b_path = run_book(
                ctx, book, voices[0], rates[0],
                styles[0] if styles else None, args.chunk_chars,
                args.concurrency, out_m4b, lang=book_lang)
    except SpendCapExceeded as exc:
        partial = True
        notes.append(f"cap di spesa raggiunto: {exc}")
        print(f"[stop] {exc}")
    except CFAuthError as exc:
        partial = True
        notes.append(str(exc))
        print(f"[stop] {exc}")
    except SystemExit as exc:
        # Nessun percorso interno solleva SystemExit dopo che si e' gia'
        # speso (solo resolve_credentials(), pre-spesa, e' fuori da questo
        # try): ma se una dipendenza terza lo facesse, non deve lasciare un
        # run pagato senza report.md ne' un traceback grezzo su stderr
        # (fix round 3, Finding A: stessa disciplina di KeyboardInterrupt).
        partial = True
        notes.append(f"uscita anticipata (SystemExit codice {exc.code!r}) "
                     "durante il run.")
        print(f"[stop] SystemExit codice {exc.code!r} durante il run")
    except KeyboardInterrupt:
        # Ctrl-C su un run lungo (--level book) dopo che si e' gia' speso:
        # non va inghiottito in silenzio, ma nemmeno lasciato propagare senza
        # lasciare traccia. Il run e' marcato parziale, il report viene
        # comunque scritto sotto, e l'uscita resta non-zero (fix round 2).
        partial = True
        notes.append("run interrotto manualmente (Ctrl-C) prima del "
                     "completamento.")
        print("[stop] interrotto manualmente (Ctrl-C)")
    except Exception as exc:  # noqa: BLE001 - garantisce sempre un report
        # Qualunque altro errore non gia' assorbito a monte (CFCallError
        # residua, bug non previsto) non deve lasciare un run che ha gia'
        # speso denaro senza un report.md: il run e' marcato parziale e
        # l'eccezione viene solo annotata, mai rilanciata (fix round 1,
        # regressione critica: prima un chunk anomaly="error" a --level
        # smoke faceva sollevare TypeError qui sopra, senza alcun report).
        partial = True
        notes.append(f"errore non gestito: {exc}")
        print(f"[stop] {exc}")
    finally:
        writer.close()

    # Dal primo momento in cui una chiamata pagata puo' essere partita (sopra)
    # fino a qui, NESSUN percorso d'uscita deve lasciare il run senza un
    # report.md: fix round 2 estende la stessa regola vincolante del round 1
    # al blocco di post-elaborazione, che prima viveva fuori da qualunque
    # protezione (una riga corrotta in metrics.jsonl o un OSError dentro
    # render_report facevano morire main() con un traceback e nessun report).
    records = []
    cf_records = []
    vertex_records = []
    cf_residue = 0
    vertex_cost_eur = 0.0
    report = None
    # Difetto 1 (round 4): i POST gia' andati a 200 sono fatturati anche se il
    # record corrispondente non e' mai stato scritto. Il contatore e' l'unica
    # fonte che sopravvive a un'interruzione dentro quella finestra.
    paid_calls = ctx.paid_calls.count
    unrecorded_paid = 0
    # Difetto 4 (round 4): distingue "metrics.jsonl non letto" da "render_report
    # fallito", due cause con conseguenze opposte sulla riconciliazione.
    records_read = False
    post_error = None
    try:
        malformed = 0
        with open(writer.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    # Riga corrotta (es. scrittura interrotta a meta' da un
                    # crash): scartata, non fatale. Il conteggio finisce nel
                    # report invece di sparire in silenzio.
                    malformed += 1
        # Carry-forward A (Task 10 review): summarize()/render_report() non
        # separano le righe per backend. Con --compare vertex
        # synth_chunk_vertex scrive anche righe "vertex" sullo stesso
        # metrics.jsonl: il filtro qui garantisce che report e
        # riconciliazione (che cita esplicitamente la Cloudflare Dashboard)
        # restino scoped alla sola spesa Cloudflare, senza sommare costi di
        # provider diversi in un totale senza senso.
        cf_records = [r for r in records if r.get("backend") == ctx.backend]
        vertex_records = [r for r in records if r.get("backend") == "vertex"]
        cf_residue = _residual_anomalies(cf_records)
        records_read = True
        # Difetto 1 (round 4): confronto fra i 200 osservati dal processo e i
        # 200 finiti in metrics.jsonl. Un record in piu' non e' possibile (il
        # contatore scatta prima di qualunque scrittura), uno in meno si': e'
        # una chiamata fatturata che i totali dei record non vedono.
        recorded_paid = sum(1 for r in cf_records
                            if r.get("http_status") == 200)
        unrecorded_paid = max(0, paid_calls - recorded_paid)
        if unrecorded_paid:
            partial = True
            notes.append(unrecorded_calls_note(unrecorded_paid))
        if malformed:
            notes.append(f"{malformed} riga/e di metrics.jsonl scartate "
                         f"perche' malformate (JSON non valido).")
        notes.append(
            f"report e riconciliazione sopra coprono solo il backend "
            f"'{ctx.backend}'; eventuali righe di altri backend in "
            f"metrics.jsonl (es. 'vertex' con --compare) non sono incluse "
            f"nei totali.")
        vertex_cost_usd = sum(float(r.get("cost_usd_est") or 0)
                              for r in vertex_records)
        vertex_cost_eur = vertex_cost_usd * USD_EUR_RATE
        if vertex_records:
            # Il gemello Vertex non tocca mai ctx.guard (--max-spend-eur e'
            # il cap della sola spesa Cloudflare by design): senza questa
            # nota un operatore che lancia --compare vertex vede solo meta'
            # della spesa reale, e con --runs N il divario raddoppia in
            # silenzio (fix round 2).
            notes.append(
                f"spesa Vertex stimata (fuori dal cap --max-spend-eur, che "
                f"copre solo Cloudflare): USD {vertex_cost_usd:.4f} / "
                f"EUR {vertex_cost_eur:.4f}.")
        report = render_report(run_dir, cf_records, cf_residue, partial, notes,
                               unrecorded_paid_calls=unrecorded_paid)
        report_ok = True
        records_reliable = True
    except (Exception, KeyboardInterrupt, SystemExit) as exc:  # noqa: BLE001
        # Qualunque cedimento qui sotto (metrics.jsonl illeggibile,
        # render_report che solleva, un secondo Ctrl-C, un SystemExit) non
        # deve far sparire un run che ha gia' speso denaro: si scrive un
        # report minimo con quel che si sa, invece di non scrivere nulla
        # (fix round 3, Finding A: SystemExit aggiunto a Exception/
        # KeyboardInterrupt del round 2).
        partial = True
        notes.append(f"generazione del report normale fallita: {exc}")
        report = os.path.join(run_dir, "report.md")
        report_ok = False
        post_error = exc
        # Finding D (fix round 3) + difetto 4 (round 4): i record restano
        # affidabili se il cedimento e' avvenuto DOPO averli letti (tipico:
        # render_report che solleva). Solo un cedimento precedente alla
        # lettura li rende inutilizzabili per la riconciliazione.
        records_reliable = records_read
        try:
            righe = ["# Report banco di prova Cloudflare Gemini TTS", "",
                     "**RUN PARZIALE** - report minimo, generazione "
                     f"normale fallita: {exc}", ""]
            if records_read:
                righe.append(f"Chiamate Cloudflare registrate: {len(cf_records)}")
                righe.append(f"Anomalie residue: {cf_residue}")
            else:
                # Difetto 4 (round 4): senza lettura non si conosce il numero
                # di record; scrivere "0" sarebbe una dichiarazione falsa.
                righe.append("Chiamate Cloudflare registrate: n/d "
                             "(metrics.jsonl non letto in modo affidabile)")
                righe.append("Anomalie residue: n/d")
            if paid_calls:
                # Difetto 1 (round 4): dato indipendente dai record, l'unico
                # che resta valido anche qui.
                righe.append(f"Risposte HTTP 200 osservate dal processo "
                             f"(quindi fatturate): {paid_calls}")
            righe += ["", "## Note", ""]
            righe += [f"- {n}" for n in notes]
            # Una sola write: riduce al minimo la finestra in cui un secondo
            # Ctrl-C puo' lasciare un report troncato a meta'.
            with open(report, "w", encoding="utf-8") as fh:
                fh.write("\n".join(righe) + "\n")
            report_ok = True
        except (Exception, KeyboardInterrupt, SystemExit) as write_exc:  # noqa: BLE001
            # Finding B (fix round 3): anche il report minimo non e'
            # scrivibile (es. disco pieno). Prima questo era un
            # `except OSError: pass` silenzioso e il footer sotto annunciava
            # comunque "[fine] report: <path>" per un file inesistente,
            # mentendo all'operatore. Ora il fallimento e' esplicito su
            # stdout e nessun percorso inesistente viene presentato come
            # valido.
            # Difetto 2 (round 4): la clausola era `except OSError`, quindi
            # un Ctrl-C proprio su questa open (il "secondo Ctrl-C" che il
            # commento del blocco esterno prometteva di coprire) usciva con
            # traceback grezzo e senza alcun report, su un run gia' pagato.
            report_ok = False
            resto = (" - un file parziale potrebbe essere rimasto su disco"
                     if os.path.exists(report) else "")
            print(f"[errore] impossibile scrivere anche il report minimo "
                  f"({report}{resto}): {write_exc!r}")

    if records_reliable:
        # Difetto 4 (round 4): i record letti restano validi anche se e' stato
        # render_report a cedere. Nasconderli attribuiva una causa falsa
        # ("fallita prima di poter leggere metrics.jsonl") mentre il report
        # minimo dello stesso run ne dichiarava il numero.
        print(reconciliation_block(cf_records,
                                   unrecorded_paid_calls=unrecorded_paid))
    else:
        # Finding D (fix round 3): quando metrics.jsonl e' illeggibile,
        # stampare la riconciliazione calcolata su una lista vuota direbbe
        # "nessuna chiamata registrata" anche se una chiamata pagata e'
        # effettivamente partita. Il report (minimo o di fallback) resta
        # comunque su disco quando possibile (regola vincolante rispettata);
        # qui si evita solo di mentire su stdout dichiarando i dati non
        # disponibili, con la causa reale.
        print(f"[riconciliazione] non disponibile: metrics.jsonl non e' stato "
              f"letto in modo affidabile (la post-elaborazione e' fallita "
              f"prima della lettura: {post_error!r}).")
        if paid_calls:
            print(f"[riconciliazione] questo processo ha comunque ricevuto "
                  f"{paid_calls} risposta/e HTTP 200 da Cloudflare, quindi "
                  f"fatturate: il run NON e' a costo zero.")
    if report_ok:
        print(f"[fine] report: {report}")
    else:
        print(f"[fine] nessun report scritto su disco (tentativo fallito: "
              f"{report})")
    if m4b_path:
        print(f"[fine] M4B: {m4b_path}")
    print(f"[fine] spesa stimata Cloudflare (soggetta al cap --max-spend-eur): "
          f"EUR {ctx.guard.spent_eur():.4f}")
    if vertex_records:
        print(f"[fine] spesa stimata Vertex (fuori dal cap, solo A/B): "
              f"EUR {vertex_cost_eur:.4f}")
    return 1 if (cf_residue or partial or not report_ok) else 0


if __name__ == "__main__":
    sys.exit(main())
