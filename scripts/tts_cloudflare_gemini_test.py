#!/usr/bin/env python3
"""tts_cloudflare_gemini_test.py — banco di prova Gemini 3.1 Flash TTS su Cloudflare Workers AI.

Misura costo reale, robustezza (troncamenti/risposte vuote), throughput e
parita' di qualita' rispetto al backend Vertex usato in produzione.

Riusa SOLO helper puri del progetto (gemini_tts, tts_split, audio_utils):
non importa mai audiobook_app ne' generation_engine, non tocca i job ne' i
database JSON.

Spec: docs/superpowers/specs/2026-08-25-cloudflare-gemini-tts-bench-design.md
"""
import base64
import binascii
import hashlib
import io
import json
import os
import sys
import time
import wave
from datetime import datetime, timezone

import requests

# Il bench vive in scripts/: la root del progetto va in sys.path per importare
# gli helper puri (gemini_tts, tts_split, audio_utils).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audio_utils
import gemini_tts

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
    """Accumulatore di spesa con tetto in euro. `max_eur=0` disattiva il tetto."""

    def __init__(self, max_eur=DEFAULT_MAX_SPEND_EUR):
        self.max_eur = float(max_eur or 0)
        self.spent_usd = 0.0

    def spent_eur(self):
        return self.spent_usd * USD_EUR_RATE

    def check(self, projected_usd):
        """Solleva SpendCapExceeded se aggiungere `projected_usd` sfonda il cap."""
        if self.max_eur <= 0:
            return
        proiettato = (self.spent_usd + float(projected_usd)) * USD_EUR_RATE
        if proiettato > self.max_eur:
            raise SpendCapExceeded(
                f"cap di spesa raggiunto: {proiettato:.4f} EUR previsti "
                f"contro un tetto di {self.max_eur:.2f} EUR"
            )

    def add(self, usd):
        self.spent_usd += float(usd)


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
            max_attempts=4, timeout=HTTP_TIMEOUT_SEC, sleep=time.sleep):
    """Una sintesi su Cloudflare, con retry su 429/5xx e su timeout di rete.

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
                 sleep=time.sleep):
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


def _one_call(ctx, final_text, chars, lang, voice, rate, style, pcm_path,
              chunk_index):
    """Una chiamata + decodifica + valutazione. Ritorna (record, seconds, path).

    Un `CFCallError` (tentativi HTTP esauriti, 4xx non ritentabile, audio non
    decodificabile) non interrompe il run: la spec impone che solo 401/403
    (CFAuthError, non catturata qui) provochi un abort immediato. Un chunk
    fallito dopo i retry di `call_cf` viene marcato "error" e riportato con
    una sola riga di metriche.
    """
    ctx.guard.check(predict_call_usd(chars, lang))
    try:
        res = call_cf(ctx.session, ctx.account_id, ctx.api_token, final_text,
                      voice, ctx.temperature, sleep=ctx.sleep)
    except CFCallError as exc:
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
    ctx.guard.add(usd)
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


def run_smoke(ctx, lang, voice, rate, style, text):
    """Un solo chunk: verifica auth, schema di risposta e decodifica WAV."""
    pcm_path = os.path.join(ctx.run_dir, "audio", "0000.pcm")
    res = synth_chunk(ctx, text, 0, lang, voice, rate, style, pcm_path)
    print(f"[smoke] {lang}/{voice}: {res['audio_seconds']:.1f}s audio, "
          f"ratio {res['record']['ratio']:.2f}, "
          f"anomalia {res['anomaly'] or 'nessuna'}")
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
    return {
        "calls": len(records),
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


def reconciliation_block(records):
    """Blocco da confrontare con la fattura Cloudflare.

    Senza questo confronto il run misura il funzionamento, non il prezzo: il
    costo qui e' stimato, perche' l'API non restituisce i token consumati.
    """
    if not records:
        return "RICONCILIAZIONE - nessuna chiamata effettuata."
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
    )


def render_report(run_dir, records, residual_anomalies, partial, notes):
    """Scrive `report.md` e ne ritorna il path."""
    agg = summarize(records)
    lines = []
    lines.append("# Report banco di prova Cloudflare Gemini TTS")
    lines.append("")
    lines.append(f"Run: `{os.path.basename(run_dir)}`")
    if partial:
        lines.append("")
        lines.append("**RUN PARZIALE** - interrotto prima del completamento.")
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
            lines.append(f"| {r.get('chunk_index')} | {r.get('http_status')} "
                         f"| {r.get('attempt')} |")
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
    lines.append(reconciliation_block(records))
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
