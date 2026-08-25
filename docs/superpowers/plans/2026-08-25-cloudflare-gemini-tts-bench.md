# Banco di prova Gemini 3.1 TTS su Cloudflare — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un banco di prova locale e parametrico che misuri costo reale, robustezza, throughput e parità di qualità di `google/gemini-3.1-flash-tts` su Cloudflare Workers AI, prima di decidere la migrazione della produzione.

**Architecture:** Un singolo modulo Python standalone in `scripts/`, pilotato da un wrapper PowerShell. Importa solo helper puri dal progetto (`gemini_tts`, `tts_split`, `audio_utils`), mai `audiobook_app` né `generation_engine`. Tre livelli di esecuzione (`smoke`, `matrix`, `book`) sopra lo stesso motore di chiamata, con gate anti-troncamento, cap di spesa e output in `metrics.jsonl` + `report.md`.

**Tech Stack:** Python 3, `requests`, `wave`/`argparse`/`concurrent.futures` da stdlib, FFmpeg via `audio_utils`, PowerShell 7 per il wrapper, pytest per i test.

**Spec:** `docs/superpowers/specs/2026-08-25-cloudflare-gemini-tts-bench-design.md`

## Global Constraints

- **Shell di sviluppo:** PowerShell su Windows. Mai concatenare comandi con `&&`: un comando per invocazione.
- **Nessuna modifica ai moduli dell'app.** `gemini_tts.py`, `tts_split.py`, `audio_utils.py` si importano, non si toccano. `audiobook_app` e `generation_engine` non si importano mai.
- **Tracciamento git:** `scripts/` è in `.gitignore` (riga 14). Il bench e il wrapper vanno aggiunti con `git add -f`, come i 12 file già tracciati sotto `scripts/`. `scripts/cf_tts_bench.env.ps1` non va **mai** aggiunto, nemmeno con `-f`.
- **Commit:** Conventional Commits (`type(scope): summary`), imperativo, minuscolo, senza punto finale. **Nessun trailer di attribuzione** (`Co-Authored-By`, `Generated with`, `Signed-off-by`).
- **Mai `git push`** senza conferma esplicita dell'utente nel turno corrente.
- **Segreti:** `CF_ACCOUNT_ID` e `CF_API_TOKEN` solo da variabili d'ambiente. Mai valori hardcoded, mai stampati in log, report o messaggi d'errore.
- **Nessuna chiamata di rete nei test.** `requests.Session` è sempre mockata.
- **Costanti fisse del bench** (valori esatti, da usare ovunque):
  - modello: `google/gemini-3.1-flash-tts`
  - tariffe Cloudflare: input `$0.75`/Mtok, output `$12.00`/Mtok
  - token audio per secondo: `25.0`
  - cambio USD→EUR: `0.86`
  - formato audio atteso: 24000 Hz, 1 canale, 2 byte/campione
  - banda del gate di durata: `0.6` – `1.6`
  - default: chunk 450 char, temperature 0.3, cap di spesa €2.00, timeout HTTP 60 s
- **Validazione sintassi obbligatoria** prima di ogni commit: `python -m py_compile scripts/tts_cloudflare_gemini_test.py`.

---

## File Structure

| File | Responsabilità |
|---|---|
| `scripts/tts_cloudflare_gemini_test.py` | Tutto il bench: credenziali, client HTTP, decodifica WAV, stima costi, cap di spesa, gate di durata, metriche, report, i tre livelli, CLI |
| `scripts/cf_tts_bench.ps1` | Wrapper parametrico: valida i parametri, carica l'env, invoca il Python |
| `scripts/cf_tts_bench.env.ps1.example` | Modello delle credenziali, committato; la copia reale `cf_tts_bench.env.ps1` resta locale |
| `test/test_cf_tts_bench.py` | Test unitari del bench, HTTP mockata |

Il bench è un solo modulo perché è uno strumento diagnostico monouso: spezzarlo in package aumenterebbe l'attrito senza dare confini riusabili. Le funzioni sono però pure e testabili una per una — è quello che i test verificano.

---

### Task 1: Fondamenta — credenziali e decodifica WAV

**Files:**
- Create: `scripts/tts_cloudflare_gemini_test.py`
- Create: `test/test_cf_tts_bench.py`

**Interfaces:**
- Consumes: nulla
- Produces:
  - `class WavFormatError(Exception)`
  - `resolve_credentials() -> tuple[str, str]` — legge `CF_ACCOUNT_ID`, `CF_API_TOKEN`; solleva `SystemExit` con messaggio che nomina la variabile mancante e **non** contiene il valore del token
  - `wav_bytes_to_pcm(wav_bytes: bytes, out_path: str) -> dict` — scrive il PCM grezzo (senza header) e ritorna `{"rate": int, "channels": int, "width": int, "bytes": int}`; solleva `WavFormatError` se il payload non è un WAV leggibile o se ne ricava 0 byte

- [ ] **Step 1: Scrivere il file di test con il caricamento del bench e i primi test**

Il bench sta in `scripts/`, che non è un package importabile: si carica per path con `importlib`.

```python
"""Test del banco di prova Cloudflare Gemini TTS (scripts/tts_cloudflare_gemini_test.py).

Nessuna chiamata di rete: la sessione HTTP e' sempre mockata.
"""
import importlib.util
import io
import os
import wave

import pytest

_BENCH_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "tts_cloudflare_gemini_test.py",
)

if not os.path.exists(_BENCH_PATH):
    pytest.skip("bench Cloudflare non presente in questa copia di lavoro",
                allow_module_level=True)

_spec = importlib.util.spec_from_file_location("cf_bench", _BENCH_PATH)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def make_wav(seconds=1.0, rate=24000, channels=1, width=2):
    """WAV in memoria, silenzio, formato parametrico."""
    frames = b"\x00" * int(rate * seconds) * channels * width
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(frames)
    return buf.getvalue()


def test_wav_bytes_to_pcm_estrae_formato_e_byte(tmp_path):
    out = str(tmp_path / "chunk.pcm")
    fmt = bench.wav_bytes_to_pcm(make_wav(seconds=2.0), out)
    assert fmt == {"rate": 24000, "channels": 1, "width": 2, "bytes": 96000}
    assert os.path.getsize(out) == 96000


def test_wav_bytes_to_pcm_rifiuta_payload_non_wav(tmp_path):
    with pytest.raises(bench.WavFormatError):
        bench.wav_bytes_to_pcm(b"non sono un wav", str(tmp_path / "x.pcm"))


def test_wav_bytes_to_pcm_rifiuta_wav_senza_frame(tmp_path):
    with pytest.raises(bench.WavFormatError):
        bench.wav_bytes_to_pcm(make_wav(seconds=0.0), str(tmp_path / "x.pcm"))


def test_resolve_credentials_ok(monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc123")
    monkeypatch.setenv("CF_API_TOKEN", "tok-super-segreto")
    assert bench.resolve_credentials() == ("acc123", "tok-super-segreto")


def test_resolve_credentials_manca_token_e_non_lo_stampa(monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc123")
    monkeypatch.delenv("CF_API_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        bench.resolve_credentials()
    msg = str(exc.value)
    assert "CF_API_TOKEN" in msg
    assert "tok-super-segreto" not in msg
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_cf_tts_bench.py -v`
Expected: SKIP dell'intero modulo (il bench non esiste ancora).

- [ ] **Step 3: Creare il bench con intestazione, costanti e le due funzioni**

```python
#!/usr/bin/env python3
"""tts_cloudflare_gemini_test.py — banco di prova Gemini 3.1 Flash TTS su Cloudflare Workers AI.

Misura costo reale, robustezza (troncamenti/risposte vuote), throughput e
parita' di qualita' rispetto al backend Vertex usato in produzione.

Riusa SOLO helper puri del progetto (gemini_tts, tts_split, audio_utils):
non importa mai audiobook_app ne' generation_engine, non tocca i job ne' i
database JSON.

Spec: docs/superpowers/specs/2026-08-25-cloudflare-gemini-tts-bench-design.md
"""
import io
import os
import sys
import wave

# Il bench vive in scripts/: la root del progetto va in sys.path per importare
# gli helper puri (gemini_tts, tts_split, audio_utils).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
```

- [ ] **Step 4: Verificare la sintassi**

Run: `python -m py_compile scripts/tts_cloudflare_gemini_test.py`
Expected: nessun output, exit 0.

- [ ] **Step 5: Eseguire i test e verificarne il successo**

Run: `python -m pytest test/test_cf_tts_bench.py -v`
Expected: 5 PASS.

- [ ] **Step 6: Commit**

```powershell
git add -f scripts/tts_cloudflare_gemini_test.py
git add test/test_cf_tts_bench.py
git commit -m "feat(bench): fondamenta del banco Cloudflare Gemini TTS"
```

---

### Task 2: Stima token, costo e cap di spesa

**Files:**
- Modify: `scripts/tts_cloudflare_gemini_test.py`
- Modify: `test/test_cf_tts_bench.py`

**Interfaces:**
- Consumes: costanti di Task 1
- Produces:
  - `estimate_tokens(chars: int, audio_seconds: float, language: str) -> dict` → `{"tokens_in": int, "tokens_out": int}`; input da `gemini_tts.estimate_input_tokens`, output = `round(audio_seconds * 25.0)`
  - `cost_usd(tokens_in: int, tokens_out: int) -> float`
  - `predict_call_usd(chars: int, language: str) -> float` — costo previsto **prima** della chiamata, con `audio_seconds = chars / gemini_tts.baseline_rate(language)`
  - `class SpendCapExceeded(Exception)`
  - `class SpendGuard` con `__init__(max_eur: float)`, attributo `spent_usd: float`, `spent_eur() -> float`, `check(projected_usd: float) -> None` (solleva `SpendCapExceeded`), `add(usd: float) -> None`

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in coda a `test/test_cf_tts_bench.py`:

```python
def test_estimate_tokens_usa_25_token_al_secondo():
    got = bench.estimate_tokens(chars=400, audio_seconds=40.0, language="it")
    # 400 char it / 4.0 char-per-token = 100 token input; 40 s * 25 = 1000 output
    assert got == {"tokens_in": 100, "tokens_out": 1000}


def test_cost_usd_tariffe_cloudflare():
    assert bench.cost_usd(1000, 100000) == pytest.approx(1.20075)


def test_predict_call_usd_da_baseline_lingua():
    # 1460 char it / 14.6 char-sec = 100 s -> 2500 token out; 365 token in
    atteso = 365 * 0.75 / 1e6 + 2500 * 12.0 / 1e6
    assert bench.predict_call_usd(1460, "it") == pytest.approx(atteso)


def test_spend_guard_accumula_e_converte_in_euro():
    guard = bench.SpendGuard(max_eur=1.0)
    guard.add(0.5)
    guard.add(0.25)
    assert guard.spent_usd == pytest.approx(0.75)
    assert guard.spent_eur() == pytest.approx(0.645)


def test_spend_guard_blocca_oltre_il_cap():
    guard = bench.SpendGuard(max_eur=1.0)
    guard.add(1.10)  # 0.946 EUR
    guard.check(0.05)  # 0.989 EUR: ancora sotto, non solleva
    guard.add(0.05)
    with pytest.raises(bench.SpendCapExceeded):
        guard.check(0.10)


def test_spend_guard_cap_zero_disattiva_il_controllo():
    guard = bench.SpendGuard(max_eur=0)
    guard.add(999.0)
    guard.check(999.0)  # nessuna eccezione
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_cf_tts_bench.py -v`
Expected: 6 FAIL con `AttributeError: module 'cf_bench' has no attribute 'estimate_tokens'` (e simili).

- [ ] **Step 3: Implementare**

Aggiungere l'import degli helper puri sotto il blocco `sys.path.insert` di Task 1:

```python
import gemini_tts
```

e in coda al modulo:

```python
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
```

- [ ] **Step 4: Verificare sintassi e test**

Run: `python -m py_compile scripts/tts_cloudflare_gemini_test.py`
Run: `python -m pytest test/test_cf_tts_bench.py -v`
Expected: 11 PASS.

- [ ] **Step 5: Commit**

```powershell
git add -f scripts/tts_cloudflare_gemini_test.py
git add test/test_cf_tts_bench.py
git commit -m "feat(bench): stima token, costo Cloudflare e cap di spesa"
```

---

### Task 3: Gate anti-troncamento

Sostituisce il `finish_reason` che l'API Cloudflare non restituisce. È il presidio contro l'incidente già occorso due volte in produzione: audio troncato consegnato all'utente senza che nulla lo segnalasse.

**Files:**
- Modify: `scripts/tts_cloudflare_gemini_test.py`
- Modify: `test/test_cf_tts_bench.py`

**Interfaces:**
- Consumes: `RATIO_LOW`, `RATIO_HIGH`, `EXPECTED_*` di Task 1
- Produces:
  - `evaluate_duration(chars: int, language: str, audio_seconds: float) -> dict` → `{"expected_seconds": float, "ratio": float, "anomaly": str|None}`, con `anomaly` in `None | "empty" | "truncated" | "overlong"`
  - `evaluate_format(fmt: dict) -> str|None` → `"format"` se rate/canali/width divergono dagli attesi, altrimenti `None`

- [ ] **Step 1: Scrivere i test che falliscono**

```python
def test_evaluate_duration_nella_banda_nessuna_anomalia():
    got = bench.evaluate_duration(chars=1460, language="it", audio_seconds=90.0)
    assert got["expected_seconds"] == pytest.approx(100.0)
    assert got["ratio"] == pytest.approx(0.9)
    assert got["anomaly"] is None


def test_evaluate_duration_troncato():
    got = bench.evaluate_duration(chars=1460, language="it", audio_seconds=55.0)
    assert got["anomaly"] == "truncated"


def test_evaluate_duration_troppo_lungo():
    got = bench.evaluate_duration(chars=1460, language="it", audio_seconds=170.0)
    assert got["anomaly"] == "overlong"


def test_evaluate_duration_audio_vuoto():
    got = bench.evaluate_duration(chars=1460, language="it", audio_seconds=0.0)
    assert got["anomaly"] == "empty"
    assert got["ratio"] == 0.0


def test_evaluate_duration_testo_vuoto_non_divide_per_zero():
    got = bench.evaluate_duration(chars=0, language="it", audio_seconds=0.0)
    assert got["anomaly"] == "empty"


def test_evaluate_duration_estremi_della_banda_sono_accettati():
    # ratio esattamente 0.6 e 1.6 non sono anomalie: la banda e' inclusiva
    assert bench.evaluate_duration(1460, "it", 60.0)["anomaly"] is None
    assert bench.evaluate_duration(1460, "it", 160.0)["anomaly"] is None


def test_evaluate_format_riconosce_il_formato_atteso():
    assert bench.evaluate_format({"rate": 24000, "channels": 1, "width": 2}) is None


def test_evaluate_format_segnala_divergenze():
    assert bench.evaluate_format({"rate": 16000, "channels": 1, "width": 2}) == "format"
    assert bench.evaluate_format({"rate": 24000, "channels": 2, "width": 2}) == "format"
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_cf_tts_bench.py -v -k "evaluate"`
Expected: 8 FAIL con `AttributeError`.

- [ ] **Step 3: Implementare**

```python
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
```

- [ ] **Step 4: Verificare sintassi e test**

Run: `python -m py_compile scripts/tts_cloudflare_gemini_test.py`
Run: `python -m pytest test/test_cf_tts_bench.py -v`
Expected: 19 PASS.

- [ ] **Step 5: Commit**

```powershell
git add -f scripts/tts_cloudflare_gemini_test.py
git add test/test_cf_tts_bench.py
git commit -m "feat(bench): gate anti-troncamento su durata e formato audio"
```

---

### Task 4: Client HTTP Cloudflare con retry

**Files:**
- Modify: `scripts/tts_cloudflare_gemini_test.py`
- Modify: `test/test_cf_tts_bench.py`

**Interfaces:**
- Consumes: `CF_MODEL`, `CF_API_BASE`, `HTTP_TIMEOUT_SEC`
- Produces:
  - `class CFAuthError(Exception)` — 401/403, nessun retry
  - `class CFCallError(Exception)` — esaurito il retry; espone `.status` (int|None) e `.attempts` (int)
  - `build_payload(text: str, voice: str, temperature: float) -> dict`
  - `call_cf(session, account_id, api_token, text, voice, temperature, max_attempts=4, sleep=time.sleep) -> dict` → `{"wav": bytes, "latency_ms": float, "status": int, "attempts": int, "retry_statuses": list[int]}`

Il parametro `sleep` è iniettabile perché i test non devono attendere il backoff.

- [ ] **Step 1: Scrivere i test che falliscono**

```python
class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = "corpo di risposta finto"

    def json(self):
        return self._payload


class FakeSession:
    """Sessione HTTP finta: restituisce le risposte in coda, una per chiamata."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers,
                           "timeout": timeout})
        return self._responses.pop(0)


def _ok_response(seconds=1.0):
    import base64
    return FakeResponse(200, {"result": {
        "audio": base64.b64encode(make_wav(seconds=seconds)).decode("ascii")}})


def test_build_payload_ha_modello_e_input():
    p = bench.build_payload("ciao", "Zephyr", 0.3)
    assert p["model"] == "google/gemini-3.1-flash-tts"
    assert p["input"]["text"] == "ciao"
    assert p["input"]["voice"] == "Zephyr"
    assert p["input"]["temperature"] == 0.3


def test_call_cf_successo_al_primo_tentativo():
    s = FakeSession([_ok_response()])
    got = bench.call_cf(s, "acc", "tok", "ciao", "Zephyr", 0.3, sleep=lambda _: None)
    assert got["status"] == 200
    assert got["attempts"] == 1
    assert got["wav"].startswith(b"RIFF")
    assert s.calls[0]["url"].endswith("/accounts/acc/ai/run")
    assert s.calls[0]["headers"]["Authorization"] == "Bearer tok"
    assert s.calls[0]["timeout"] == 60


def test_call_cf_ritenta_su_429_e_registra_gli_stati():
    s = FakeSession([FakeResponse(429, headers={"retry-after": "0"}), _ok_response()])
    got = bench.call_cf(s, "acc", "tok", "ciao", "Zephyr", 0.3, sleep=lambda _: None)
    assert got["attempts"] == 2
    assert got["retry_statuses"] == [429]


def test_call_cf_ritenta_su_5xx():
    s = FakeSession([FakeResponse(503), FakeResponse(500), _ok_response()])
    got = bench.call_cf(s, "acc", "tok", "ciao", "Zephyr", 0.3, sleep=lambda _: None)
    assert got["attempts"] == 3
    assert got["retry_statuses"] == [503, 500]


def test_call_cf_401_non_ritenta():
    s = FakeSession([FakeResponse(401)])
    with pytest.raises(bench.CFAuthError):
        bench.call_cf(s, "acc", "tok", "ciao", "Zephyr", 0.3, sleep=lambda _: None)
    assert len(s.calls) == 1


def test_call_cf_esaurisce_i_tentativi():
    s = FakeSession([FakeResponse(500)] * 4)
    with pytest.raises(bench.CFCallError) as exc:
        bench.call_cf(s, "acc", "tok", "ciao", "Zephyr", 0.3,
                      max_attempts=4, sleep=lambda _: None)
    assert exc.value.status == 500
    assert exc.value.attempts == 4


def test_call_cf_risposta_200_senza_audio_e_errore():
    s = FakeSession([FakeResponse(200, {"result": {}})])
    with pytest.raises(bench.CFCallError):
        bench.call_cf(s, "acc", "tok", "ciao", "Zephyr", 0.3,
                      max_attempts=1, sleep=lambda _: None)


def test_call_cf_non_stampa_il_token_negli_errori():
    s = FakeSession([FakeResponse(403)])
    with pytest.raises(bench.CFAuthError) as exc:
        bench.call_cf(s, "acc", "tok-super-segreto", "ciao", "Zephyr", 0.3,
                      sleep=lambda _: None)
    assert "tok-super-segreto" not in str(exc.value)
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_cf_tts_bench.py -v -k "call_cf or build_payload"`
Expected: 8 FAIL con `AttributeError`.

- [ ] **Step 3: Implementare**

Aggiungere agli import del modulo: `import base64`, `import time`, `import requests`.

```python
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
        return {
            "wav": base64.b64decode(audio_b64),
            "latency_ms": latency_ms,
            "status": resp.status_code,
            "attempts": attempt,
            "retry_statuses": retry_statuses,
        }
    raise CFCallError("tentativi esauriti", status=last_status,
                      attempts=int(max_attempts))
```

- [ ] **Step 4: Verificare sintassi e test**

Run: `python -m py_compile scripts/tts_cloudflare_gemini_test.py`
Run: `python -m pytest test/test_cf_tts_bench.py -v`
Expected: 27 PASS.

- [ ] **Step 5: Commit**

```powershell
git add -f scripts/tts_cloudflare_gemini_test.py
git add test/test_cf_tts_bench.py
git commit -m "feat(bench): client Cloudflare con retry su 429 e 5xx"
```

---

### Task 5: Record delle metriche e writer del run

**Files:**
- Modify: `scripts/tts_cloudflare_gemini_test.py`
- Modify: `test/test_cf_tts_bench.py`

**Interfaces:**
- Consumes: Task 2 e 3
- Produces:
  - `style_hash(style_instruction: str|None) -> str` — firma esadecimale di 8 caratteri
  - `make_record(**kwargs) -> dict` con esattamente le 21 chiavi dello schema di spec; solleva `ValueError` su chiavi fuori schema
  - `class MetricsWriter` con `__init__(run_dir: str)`, proprieta` `path -> str`, `write(record: dict) -> None`, `close() -> None`; scrive `metrics.jsonl`, una riga JSON per chiamata
  - `new_run_dir(out_root: str, level: str) -> str` — crea `out_root/<UTC ISO compatto>_<level>/` con le sottocartelle `audio/` e `prompts/`

- [ ] **Step 1: Scrivere i test che falliscono**

```python
SCHEMA_KEYS = {
    "ts", "run_id", "backend", "lang", "voice", "rate", "style_hash",
    "chunk_index", "chars", "prompt_bytes", "http_status", "latency_ms",
    "attempt", "audio_bytes", "audio_seconds", "expected_seconds", "ratio",
    "tokens_in_est", "tokens_out_est", "cost_usd_est", "anomaly",
}


def test_make_record_ha_esattamente_le_chiavi_di_schema():
    rec = bench.make_record(
        run_id="r1", backend="cloudflare", lang="it", voice="Zephyr",
        rate="+0%", style_hash="abc123", chunk_index=0, chars=450,
        prompt_bytes=460, http_status=200, latency_ms=1234.5, attempt=1,
        audio_bytes=96000, audio_seconds=2.0, expected_seconds=30.8,
        ratio=0.065, tokens_in_est=112, tokens_out_est=50,
        cost_usd_est=0.0007, anomaly="truncated",
    )
    assert set(rec) == SCHEMA_KEYS
    assert rec["ts"].endswith("Z")


def test_metrics_writer_scrive_una_riga_per_record(tmp_path):
    import json
    run_dir = str(tmp_path / "run")
    os.makedirs(run_dir)
    w = bench.MetricsWriter(run_dir)
    w.write({"a": 1})
    w.write({"a": 2})
    w.close()
    righe = open(os.path.join(run_dir, "metrics.jsonl"), encoding="utf-8").read().splitlines()
    assert [json.loads(r)["a"] for r in righe] == [1, 2]


def test_new_run_dir_crea_sottocartelle(tmp_path):
    run_dir = bench.new_run_dir(str(tmp_path), "smoke")
    assert os.path.isdir(os.path.join(run_dir, "audio"))
    assert os.path.isdir(os.path.join(run_dir, "prompts"))
    assert os.path.basename(run_dir).endswith("_smoke")
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_cf_tts_bench.py -v -k "record or writer or run_dir"`
Expected: 3 FAIL con `AttributeError`.

- [ ] **Step 3: Implementare**

Aggiungere agli import: `import json`, `import hashlib`, `from datetime import datetime, timezone`.

```python
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
```

- [ ] **Step 4: Verificare sintassi e test**

Run: `python -m py_compile scripts/tts_cloudflare_gemini_test.py`
Run: `python -m pytest test/test_cf_tts_bench.py -v`
Expected: 30 PASS.

- [ ] **Step 5: Commit**

```powershell
git add -f scripts/tts_cloudflare_gemini_test.py
git add test/test_cf_tts_bench.py
git commit -m "feat(bench): schema metriche e writer del run"
```

---

### Task 6: Sintesi di un chunk end-to-end e livello `smoke`

Unisce i pezzi precedenti in un'unica funzione riusabile da tutti e tre i livelli, e la espone dalla CLI al livello `smoke`.

**Files:**
- Modify: `scripts/tts_cloudflare_gemini_test.py`
- Modify: `test/test_cf_tts_bench.py`

**Interfaces:**
- Consumes: Task 1–5
- Produces:
  - `synth_chunk(ctx, text, chunk_index, lang, voice, rate, style, pcm_path) -> dict` — costruisce il prompt con `gemini_tts.build_final_text`, chiama `call_cf`, decodifica il WAV, valuta durata e formato, scrive il record; al primo `anomaly` non nullo ritenta **una** volta e riporta l'esito. Ritorna `{"record": dict, "retry_record": dict|None, "pcm_path": str|None, "audio_seconds": float, "anomaly": str|None}` dove `anomaly` è quella **residua** dopo il retry
  - `class BenchContext` — contenitore del run: `session`, `account_id`, `api_token`, `run_dir`, `writer`, `guard`, `run_id`, `temperature`, `backend` (`"cloudflare"` o `"vertex"`)
  - `run_smoke(ctx, lang, voice, rate, style, text) -> int` — ritorna il numero di anomalie residue

- [ ] **Step 1: Scrivere i test che falliscono**

```python
def _ctx(tmp_path, session, max_eur=10.0):
    run_dir = bench.new_run_dir(str(tmp_path), "test")
    return bench.BenchContext(
        session=session, account_id="acc", api_token="tok", run_dir=run_dir,
        writer=bench.MetricsWriter(run_dir), guard=bench.SpendGuard(max_eur),
        run_id="run-test", temperature=0.3, backend="cloudflare",
    )


def test_synth_chunk_scrive_pcm_e_record(tmp_path):
    # 146 char it -> 10 s attesi; il WAV finto dura 9 s: ratio 0.9, nessuna anomalia
    ctx = _ctx(tmp_path, FakeSession([_ok_response(seconds=9.0)]))
    got = bench.synth_chunk(ctx, "a" * 146, 0, "it", "Zephyr", "+0%", None,
                            os.path.join(ctx.run_dir, "audio", "000.pcm"))
    assert got["anomaly"] is None
    assert got["retry_record"] is None
    assert got["record"]["audio_seconds"] == pytest.approx(9.0)
    assert got["record"]["chunk_index"] == 0
    assert got["record"]["backend"] == "cloudflare"
    assert os.path.getsize(got["pcm_path"]) == 9 * 24000 * 2
    ctx.writer.close()


def test_synth_chunk_ritenta_una_volta_l_anomalia(tmp_path):
    # primo WAV 2 s (ratio 0.2 -> truncated), secondo 9 s: il retry corregge
    ctx = _ctx(tmp_path, FakeSession([_ok_response(seconds=2.0),
                                      _ok_response(seconds=9.0)]))
    got = bench.synth_chunk(ctx, "a" * 146, 0, "it", "Zephyr", "+0%", None,
                            os.path.join(ctx.run_dir, "audio", "000.pcm"))
    assert got["record"]["anomaly"] == "truncated"
    assert got["retry_record"]["anomaly"] is None
    assert got["anomaly"] is None
    ctx.writer.close()


def test_synth_chunk_anomalia_persistente_resta(tmp_path):
    ctx = _ctx(tmp_path, FakeSession([_ok_response(seconds=2.0),
                                      _ok_response(seconds=2.0)]))
    got = bench.synth_chunk(ctx, "a" * 146, 0, "it", "Zephyr", "+0%", None,
                            os.path.join(ctx.run_dir, "audio", "000.pcm"))
    assert got["anomaly"] == "truncated"
    ctx.writer.close()


def test_synth_chunk_usa_il_prompt_di_produzione(tmp_path):
    import gemini_tts
    s = FakeSession([_ok_response(seconds=9.0)])
    ctx = _ctx(tmp_path, s)
    bench.synth_chunk(ctx, "a" * 146, 0, "it", "Zephyr", "+20%", "tono calmo",
                      os.path.join(ctx.run_dir, "audio", "000.pcm"))
    atteso = gemini_tts.build_final_text("a" * 146, style_instruction="tono calmo",
                                         rate="+20%")
    assert s.calls[0]["json"]["input"]["text"] == atteso
    ctx.writer.close()


def test_synth_chunk_rispetta_il_cap_di_spesa(tmp_path):
    ctx = _ctx(tmp_path, FakeSession([_ok_response(seconds=9.0)]), max_eur=0.000001)
    with pytest.raises(bench.SpendCapExceeded):
        bench.synth_chunk(ctx, "a" * 146, 0, "it", "Zephyr", "+0%", None,
                          os.path.join(ctx.run_dir, "audio", "000.pcm"))
    ctx.writer.close()
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_cf_tts_bench.py -v -k "synth_chunk"`
Expected: 5 FAIL con `AttributeError`.

- [ ] **Step 3: Implementare**

```python
class BenchContext:
    """Stato condiviso di un run: connessione, cartelle, metriche, budget."""

    def __init__(self, session, account_id, api_token, run_dir, writer, guard,
                 run_id, temperature=DEFAULT_TEMPERATURE, backend="cloudflare"):
        self.session = session
        self.account_id = account_id
        self.api_token = api_token
        self.run_dir = run_dir
        self.writer = writer
        self.guard = guard
        self.run_id = run_id
        self.temperature = temperature
        self.backend = backend


def _one_call(ctx, final_text, chars, lang, voice, rate, style, pcm_path,
              chunk_index):
    """Una chiamata + decodifica + valutazione. Ritorna (record, seconds, path)."""
    ctx.guard.check(predict_call_usd(chars, lang))
    res = call_cf(ctx.session, ctx.account_id, ctx.api_token, final_text, voice,
                  ctx.temperature)
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
    if record["anomaly"]:
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
```

Aggiungere `import audio_utils` agli import degli helper puri.

- [ ] **Step 4: Verificare sintassi e test**

Run: `python -m py_compile scripts/tts_cloudflare_gemini_test.py`
Run: `python -m pytest test/test_cf_tts_bench.py -v`
Expected: 35 PASS.

- [ ] **Step 5: Commit**

```powershell
git add -f scripts/tts_cloudflare_gemini_test.py
git add test/test_cf_tts_bench.py
git commit -m "feat(bench): sintesi di un chunk con retry diagnostico e livello smoke"
```

---

### Task 7: Report, statistiche di latenza e blocco di riconciliazione

**Files:**
- Modify: `scripts/tts_cloudflare_gemini_test.py`
- Modify: `test/test_cf_tts_bench.py`

**Interfaces:**
- Consumes: record di Task 5
- Produces:
  - `percentiles(values: list[float]) -> dict` → `{"p50": float, "p95": float, "p99": float}` (lista vuota → tutti 0.0)
  - `summarize(records: list[dict]) -> dict` → `{"calls", "chars", "audio_seconds", "tokens_in", "tokens_out", "cost_usd", "cost_eur", "latency", "http_429", "http_5xx", "anomalies"}` dove `anomalies` è un dict `{tipo: conteggio}`
  - `reconciliation_block(records: list[dict]) -> str` — testo con finestra UTC, conteggi e costo atteso
  - `render_report(run_dir: str, records: list[dict], residual_anomalies: int, partial: bool, notes: list[str]) -> str` — scrive `report.md` e ne ritorna il path

- [ ] **Step 1: Scrivere i test che falliscono**

```python
def _rec(**kw):
    base = dict(run_id="r", backend="cloudflare", lang="it", voice="Zephyr",
                rate="+0%", style_hash="0" * 8, chunk_index=0, chars=450,
                prompt_bytes=460, http_status=200, latency_ms=1000.0, attempt=1,
                audio_bytes=96000, audio_seconds=30.0, expected_seconds=30.8,
                ratio=0.97, tokens_in_est=112, tokens_out_est=750,
                cost_usd_est=0.00909, anomaly=None)
    base.update(kw)
    return bench.make_record(**base)


def test_percentiles_su_lista_nota():
    vals = [float(n) for n in range(1, 101)]
    got = bench.percentiles(vals)
    assert got["p50"] == pytest.approx(50.0, abs=1.0)
    assert got["p95"] == pytest.approx(95.0, abs=1.0)
    assert got["p99"] == pytest.approx(99.0, abs=1.0)


def test_percentiles_lista_vuota():
    assert bench.percentiles([]) == {"p50": 0.0, "p95": 0.0, "p99": 0.0}


def test_summarize_aggrega_costi_e_anomalie():
    got = bench.summarize([_rec(), _rec(anomaly="truncated"),
                           _rec(http_status=429, attempt=2)])
    assert got["calls"] == 3
    assert got["chars"] == 1350
    assert got["audio_seconds"] == pytest.approx(90.0)
    assert got["tokens_out"] == 2250
    assert got["cost_usd"] == pytest.approx(0.02727)
    assert got["cost_eur"] == pytest.approx(0.02727 * 0.86)
    assert got["anomalies"] == {"truncated": 1}
    assert got["http_429"] == 1


def test_reconciliation_block_riporta_la_finestra_e_i_totali():
    txt = bench.reconciliation_block([_rec(), _rec()])
    assert "RICONCILIAZIONE" in txt
    assert "richieste" in txt and "2" in txt
    assert "EUR" in txt


def test_render_report_marca_il_run_parziale(tmp_path):
    run_dir = bench.new_run_dir(str(tmp_path), "matrix")
    path = bench.render_report(run_dir, [_rec()], residual_anomalies=0,
                               partial=True, notes=["cap di spesa raggiunto"])
    testo = open(path, encoding="utf-8").read()
    assert "PARZIALE" in testo
    assert "cap di spesa raggiunto" in testo


def test_render_report_dichiara_le_anomalie_residue(tmp_path):
    run_dir = bench.new_run_dir(str(tmp_path), "matrix")
    path = bench.render_report(run_dir, [_rec(anomaly="truncated")],
                               residual_anomalies=1, partial=False, notes=[])
    assert "anomalie residue: 1" in open(path, encoding="utf-8").read()
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_cf_tts_bench.py -v -k "percentiles or summarize or reconciliation or report"`
Expected: 6 FAIL con `AttributeError`.

- [ ] **Step 3: Implementare**

```python
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
```

- [ ] **Step 4: Verificare sintassi e test**

Run: `python -m py_compile scripts/tts_cloudflare_gemini_test.py`
Run: `python -m pytest test/test_cf_tts_bench.py -v`
Expected: 41 PASS.

- [ ] **Step 5: Commit**

```powershell
git add -f scripts/tts_cloudflare_gemini_test.py
git add test/test_cf_tts_bench.py
git commit -m "feat(bench): report, percentili di latenza e blocco di riconciliazione"
```

---

### Task 8: Livello `matrix` con concorrenza

**Files:**
- Modify: `scripts/tts_cloudflare_gemini_test.py`
- Modify: `test/test_cf_tts_bench.py`

**Interfaces:**
- Consumes: `synth_chunk` (Task 6), `summarize` (Task 7)
- Produces:
  - `matrix_combinations(langs: list[str], voices: list[str], rates: list[str], styles: list[str], runs: int) -> list[dict]` — prodotto cartesiano; ogni elemento `{"lang","voice","rate","style","run"}`; `styles` vuoto equivale a `[None]`
  - `FIXTURES: dict[str, str]` — un testo breve per lingua (it, en, fr, es, de) più `"default"`
  - `fixture_for(lang: str) -> str` — fixture della lingua, con fallback su `FIXTURES["default"]`
  - `run_matrix(ctx, combos: list[dict], concurrency: int) -> int` — ritorna le anomalie residue; usa `concurrent.futures.ThreadPoolExecutor`

- [ ] **Step 1: Scrivere i test che falliscono**

```python
def test_matrix_combinations_prodotto_cartesiano():
    combos = bench.matrix_combinations(["it", "en"], ["Zephyr", "Puck"],
                                       ["+0%"], [], runs=1)
    assert len(combos) == 4
    assert combos[0] == {"lang": "it", "voice": "Zephyr", "rate": "+0%",
                         "style": None, "run": 1}


def test_matrix_combinations_moltiplica_per_runs():
    combos = bench.matrix_combinations(["it"], ["Zephyr"], ["+0%"], ["calmo"],
                                       runs=3)
    assert len(combos) == 3
    assert [c["run"] for c in combos] == [1, 2, 3]


def test_fixtures_coprono_le_lingue_richieste():
    for lang in ("it", "en", "fr", "es", "de", "default"):
        assert bench.FIXTURES[lang].strip()


def test_run_matrix_esegue_tutte_le_combinazioni(tmp_path):
    combos = bench.matrix_combinations(["it", "en"], ["Zephyr"], ["+0%"], [],
                                       runs=1)
    s = FakeSession([_ok_response(seconds=9.0) for _ in combos])
    ctx = _ctx(tmp_path, s)
    residue = bench.run_matrix(ctx, combos, concurrency=1)
    assert residue == 0
    assert len(s.calls) == 2
    ctx.writer.close()


def test_run_matrix_conta_le_anomalie_residue(tmp_path):
    combos = bench.matrix_combinations(["it"], ["Zephyr"], ["+0%"], [], runs=1)
    # prima chiamata troncata, retry ancora troncato
    s = FakeSession([_ok_response(seconds=0.2), _ok_response(seconds=0.2)])
    ctx = _ctx(tmp_path, s)
    assert bench.run_matrix(ctx, combos, concurrency=1) == 1
    ctx.writer.close()
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_cf_tts_bench.py -v -k "matrix or FIXTURES or fixtures"`
Expected: 5 FAIL con `AttributeError`.

- [ ] **Step 3: Implementare**

Aggiungere `from concurrent.futures import ThreadPoolExecutor` agli import.

```python
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


def run_matrix(ctx, combos, concurrency=1):
    """Esegue tutte le combinazioni; ritorna il numero di anomalie residue.

    Il cap di spesa si applica all'intero run: se scatta, i task ancora in coda
    falliscono con SpendCapExceeded e il chiamante scrive un report parziale.
    """
    def _one(i_combo):
        i, combo = i_combo
        text = fixture_for(combo["lang"])
        pcm_path = os.path.join(ctx.run_dir, "audio", f"{i:04d}.pcm")
        return synth_chunk(ctx, text, i, combo["lang"], combo["voice"],
                           combo["rate"], combo["style"], pcm_path)

    residue = 0
    if int(concurrency) <= 1:
        for item in enumerate(combos):
            residue += 1 if _one(item)["anomaly"] else 0
        return residue
    with ThreadPoolExecutor(max_workers=int(concurrency)) as pool:
        for res in pool.map(_one, list(enumerate(combos))):
            residue += 1 if res["anomaly"] else 0
    return residue
```

- [ ] **Step 4: Verificare sintassi e test**

Run: `python -m py_compile scripts/tts_cloudflare_gemini_test.py`
Run: `python -m pytest test/test_cf_tts_bench.py -v`
Expected: 46 PASS.

- [ ] **Step 5: Commit**

```powershell
git add -f scripts/tts_cloudflare_gemini_test.py
git add test/test_cf_tts_bench.py
git commit -m "feat(bench): livello matrix con concorrenza configurabile"
```

---

### Task 9: Livello `book` — parsing, chunking e M4B

**Files:**
- Modify: `scripts/tts_cloudflare_gemini_test.py`
- Modify: `test/test_cf_tts_bench.py`

**Interfaces:**
- Consumes: `synth_chunk` (Task 6), `audio_utils.pcm_to_aac_m4b`
- Produces:
  - `parse_book(path: str) -> dict` → `{"title","author","language","chapters","cover_bytes"}` con `chapters = [(index, title, text), ...]`; supporta `.abm` (zip + `manifest.json`) e `.txt`
  - `chapter_markers(pcm_paths: list[str], titles: list[str]) -> list[dict]` → `[{"title","start","end"}]` in **millisecondi**
  - `run_book(ctx, book: dict, voice, rate, style, chunk_chars, concurrency, out_m4b) -> tuple[int, str|None]` → `(anomalie_residue, path_m4b_o_None)`

- [ ] **Step 1: Scrivere i test che falliscono**

```python
def test_parse_book_txt(tmp_path):
    p = tmp_path / "libro.txt"
    p.write_text("Prima riga.\n\nSeconda riga.", encoding="utf-8")
    book = bench.parse_book(str(p))
    assert book["title"] == "libro"
    assert len(book["chapters"]) == 1
    assert "Seconda riga." in book["chapters"][0][2]


def test_parse_book_abm(tmp_path):
    import json as _json
    import zipfile
    p = tmp_path / "libro.abm"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", _json.dumps({
            "format": "audiobook-maker-project",
            "title": "Titolo", "author": "Autore", "language": "it",
            "chapters": [{"index": 1, "title": "Cap 1", "file": "chapters/1.txt"}],
        }))
        zf.writestr("chapters/1.txt", "Testo del capitolo.")
    book = bench.parse_book(str(p))
    assert book["title"] == "Titolo"
    assert book["language"] == "it"
    assert book["chapters"] == [(1, "Cap 1", "Testo del capitolo.")]


def test_parse_book_abm_rifiuta_manifest_estraneo(tmp_path):
    import json as _json
    import zipfile
    p = tmp_path / "falso.abm"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", _json.dumps({"format": "altro"}))
    with pytest.raises(ValueError):
        bench.parse_book(str(p))


def test_chapter_markers_in_millisecondi(tmp_path):
    a = tmp_path / "a.pcm"
    b = tmp_path / "b.pcm"
    a.write_bytes(b"\x00" * (24000 * 2))       # 1 s
    b.write_bytes(b"\x00" * (24000 * 2 * 2))   # 2 s
    got = bench.chapter_markers([str(a), str(b)], ["Uno", "Due"])
    assert got == [
        {"title": "Uno", "start": 0.0, "end": 1000.0},
        {"title": "Due", "start": 1000.0, "end": 3000.0},
    ]


def test_run_book_sintetizza_ogni_chunk(tmp_path, monkeypatch):
    import tts_split
    testo = ("Questa e' una frase di prova. " * 40)  # ~1200 char, frasi complete
    book = {"title": "T", "author": "A", "language": "it",
            "chapters": [(1, "Cap 1", testo)], "cover_bytes": None}
    # Il numero di chunk lo decide lo splitter di produzione: non va indovinato.
    attesi = len(tts_split.split_text_into_chunks(testo, max_chars=450))
    assert attesi >= 2
    s = FakeSession([_ok_response(seconds=30.0) for _ in range(attesi)])
    ctx = _ctx(tmp_path, s)
    monkeypatch.setattr(bench.audio_utils, "pcm_to_aac_m4b",
                        lambda *a, **k: True)
    residue, m4b = bench.run_book(ctx, book, "Zephyr", "+0%", None,
                                  chunk_chars=450, concurrency=1,
                                  out_m4b=str(tmp_path / "out.m4b"))
    assert residue == 0
    assert len(s.calls) == attesi
    assert m4b == str(tmp_path / "out.m4b")
    ctx.writer.close()
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_cf_tts_bench.py -v -k "parse_book or chapter_markers or run_book"`
Expected: 5 FAIL con `AttributeError`.

- [ ] **Step 3: Implementare**

Aggiungere `import zipfile` agli import e `import tts_split` agli helper puri.

```python
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


def run_book(ctx, book, voice, rate, style, chunk_chars, concurrency, out_m4b):
    """Genera l'intero libro e ne assembla l'M4B. Ritorna (anomalie, path|None)."""
    lang = (book.get("language") or "en")[:2].lower()
    residue = 0
    chapter_pcms = []
    chapter_titles = []
    index = 0
    for ch_idx, ch_title, ch_text in book["chapters"]:
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

        if int(concurrency) <= 1:
            results = [_one(j) for j in jobs]
        else:
            with ThreadPoolExecutor(max_workers=int(concurrency)) as pool:
                results = list(pool.map(_one, jobs))
        for res in results:
            if res["anomaly"]:
                residue += 1
            if res["pcm_path"]:
                parts.append(res["pcm_path"])
        if not parts:
            continue
        ch_pcm = os.path.join(ctx.run_dir, "audio", f"cap{ch_idx:03d}.pcm")
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
```

- [ ] **Step 4: Verificare sintassi e test**

Run: `python -m py_compile scripts/tts_cloudflare_gemini_test.py`
Run: `python -m pytest test/test_cf_tts_bench.py -v`
Expected: 51 PASS.

- [ ] **Step 5: Commit**

```powershell
git add -f scripts/tts_cloudflare_gemini_test.py
git add test/test_cf_tts_bench.py
git commit -m "feat(bench): livello book con chunking di produzione e assembly M4B"
```

---

### Task 10: Ramo A/B contro Vertex

**Files:**
- Modify: `scripts/tts_cloudflare_gemini_test.py`
- Modify: `test/test_cf_tts_bench.py`

**Interfaces:**
- Consumes: `synth_chunk` (Task 6)
- Produces:
  - `vertex_available() -> bool` — wrapper su `gemini_tts._resolve_backend() == "vertex"`
  - `synth_chunk_vertex(ctx, text, chunk_index, lang, voice_name, rate, style, pcm_path) -> dict` — stessa forma di ritorno di `synth_chunk`, con `backend="vertex"` nel record; usa `gemini_tts.synthesize` con voice id `gemini:flash31:<voice_name>`
  - `compare_metrics(pcm_cf: str, pcm_vertex: str) -> dict` → `{"seconds_cf","seconds_vertex","delta_seconds","rms_cf","rms_vertex"}`

- [ ] **Step 1: Scrivere i test che falliscono**

```python
def test_compare_metrics_confronta_durate_e_rms(tmp_path):
    import struct
    cf = tmp_path / "cf.pcm"
    vx = tmp_path / "vx.pcm"
    cf.write_bytes(b"\x00" * (24000 * 2))                       # 1 s, silenzio
    vx.write_bytes(struct.pack("<h", 1000) * (24000 * 2))       # 2 s, tono
    got = bench.compare_metrics(str(cf), str(vx))
    assert got["seconds_cf"] == pytest.approx(1.0)
    assert got["seconds_vertex"] == pytest.approx(2.0)
    assert got["delta_seconds"] == pytest.approx(-1.0)
    assert got["rms_cf"] == pytest.approx(0.0)
    assert got["rms_vertex"] == pytest.approx(1000.0, rel=0.01)


def test_synth_chunk_vertex_usa_lo_stesso_prompt(tmp_path, monkeypatch):
    import gemini_tts
    visti = {}

    def fake_synthesize(text, voice_id, rate="+0%", output_path="output.pcm",
                        style_instruction=None, **kw):
        visti["text"] = text
        visti["voice_id"] = voice_id
        with open(output_path, "wb") as fh:
            fh.write(b"\x00" * (24000 * 2 * 9))  # 9 s
        return {"success": True, "bytes_written": 24000 * 2 * 9,
                "input_tokens": 10, "output_tokens": 225,
                "model_key": "flash31", "voice_name": "Zephyr",
                "attempts_used": 1}

    monkeypatch.setattr(gemini_tts, "synthesize", fake_synthesize)
    ctx = _ctx(tmp_path, FakeSession([]))
    res = bench.synth_chunk_vertex(ctx, "a" * 146, 0, "it", "Zephyr", "+0%",
                                   None, os.path.join(ctx.run_dir, "v.pcm"))
    # build_final_text riceve il testo grezzo: su Vertex lo applica synthesize
    assert visti["text"] == "a" * 146
    assert visti["voice_id"] == "gemini:flash31:Zephyr"
    assert res["record"]["backend"] == "vertex"
    assert res["anomaly"] is None
    ctx.writer.close()
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_cf_tts_bench.py -v -k "compare_metrics or vertex"`
Expected: 2 FAIL con `AttributeError`.

- [ ] **Step 3: Implementare**

Aggiungere `import array` agli import.

```python
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
    """
    os.makedirs(os.path.dirname(pcm_path), exist_ok=True)
    t0 = time.time()
    res = gemini_tts.synthesize(
        text, f"gemini:flash31:{voice_name}", rate=rate, output_path=pcm_path,
        style_instruction=style)
    latency_ms = (time.time() - t0) * 1000.0
    audio_bytes = int(res.get("bytes_written") or 0)
    seconds = audio_utils.pcm_size_to_seconds(
        audio_bytes, sample_rate=EXPECTED_RATE, channels=EXPECTED_CHANNELS,
        sample_width=EXPECTED_WIDTH)
    dur = evaluate_duration(len(text), lang, seconds)
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
        tokens_in_est=int(res.get("input_tokens") or 0),
        tokens_out_est=int(res.get("output_tokens") or 0),
        cost_usd_est=0.0,  # il costo Vertex non entra nel cap Cloudflare
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
```

- [ ] **Step 4: Verificare sintassi e test**

Run: `python -m py_compile scripts/tts_cloudflare_gemini_test.py`
Run: `python -m pytest test/test_cf_tts_bench.py -v`
Expected: 53 PASS.

- [ ] **Step 5: Commit**

```powershell
git add -f scripts/tts_cloudflare_gemini_test.py
git add test/test_cf_tts_bench.py
git commit -m "feat(bench): ramo A/B contro Vertex con metriche oggettive"
```

---

### Task 11: CLI e orchestrazione del run

**Files:**
- Modify: `scripts/tts_cloudflare_gemini_test.py`
- Modify: `test/test_cf_tts_bench.py`

**Interfaces:**
- Consumes: tutti i task precedenti
- Produces:
  - `build_arg_parser() -> argparse.ArgumentParser` con esattamente le opzioni: `--level`, `--book`, `--langs`, `--voices`, `--rates`, `--styles`, `--chunk-chars`, `--concurrency`, `--runs`, `--temperature`, `--max-spend-eur`, `--compare`, `--out-dir`, `--max-attempts`
  - `split_csv(value: str) -> list[str]`
  - `main(argv=None) -> int` — exit code 0 se nessuna anomalia residua e il run è completo, 1 altrimenti

- [ ] **Step 1: Scrivere i test che falliscono**

```python
def test_split_csv():
    assert bench.split_csv("it, en ,fr") == ["it", "en", "fr"]
    assert bench.split_csv("") == []
    assert bench.split_csv(None) == []


def test_arg_parser_default_allineati_a_produzione():
    ns = bench.build_arg_parser().parse_args([])
    assert ns.level == "smoke"
    assert ns.chunk_chars == 450
    assert ns.temperature == 0.3
    assert ns.max_spend_eur == 2.00
    assert ns.langs == "it,en"
    assert ns.voices == "Zephyr"
    assert ns.rates == "+0%"
    assert ns.concurrency == 1
    assert ns.runs == 1
    assert ns.compare is None


def test_main_book_richiede_il_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    rc = bench.main(["--level", "book", "--out-dir", str(tmp_path)])
    assert rc == 1


def test_main_compare_senza_vertex_esce_prima_di_spendere(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench, "vertex_available", lambda: False)
    chiamate = []
    monkeypatch.setattr(bench, "call_cf",
                        lambda *a, **k: chiamate.append(1))
    rc = bench.main(["--level", "smoke", "--compare", "vertex",
                     "--out-dir", str(tmp_path)])
    assert rc == 1
    assert chiamate == []


def test_main_smoke_scrive_report_e_metriche(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=14.0)]))
    rc = bench.main(["--level", "smoke", "--out-dir", str(tmp_path)])
    assert rc == 0
    run_dirs = [d for d in os.listdir(tmp_path) if d.endswith("_smoke")]
    assert len(run_dirs) == 1
    run_dir = os.path.join(str(tmp_path), run_dirs[0])
    assert os.path.exists(os.path.join(run_dir, "report.md"))
    assert os.path.exists(os.path.join(run_dir, "metrics.jsonl"))


def test_main_esce_1_su_anomalia_residua(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=0.2),
                                             _ok_response(seconds=0.2)]))
    assert bench.main(["--level", "smoke", "--out-dir", str(tmp_path)]) == 1


def test_main_cap_di_spesa_produce_report_parziale(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(bench.requests, "Session",
                        lambda: FakeSession([_ok_response(seconds=14.0)]))
    rc = bench.main(["--level", "smoke", "--max-spend-eur", "0.0000001",
                     "--out-dir", str(tmp_path)])
    assert rc == 1
    run_dir = os.path.join(str(tmp_path),
                           [d for d in os.listdir(tmp_path)][0])
    assert "PARZIALE" in open(os.path.join(run_dir, "report.md"),
                              encoding="utf-8").read()
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `python -m pytest test/test_cf_tts_bench.py -v -k "split_csv or arg_parser or main"`
Expected: 7 FAIL con `AttributeError`.

- [ ] **Step 3: Implementare**

Aggiungere `import argparse` agli import.

```python
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


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    if args.level == "book" and not args.book:
        print("[errore] --level book richiede --book <file.abm|file.txt>")
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
        session=requests.Session(), account_id=account_id, api_token=api_token,
        run_dir=run_dir, writer=writer, guard=SpendGuard(args.max_spend_eur),
        run_id=os.path.basename(run_dir), temperature=args.temperature,
        backend="cloudflare")

    langs = split_csv(args.langs) or ["en"]
    voices = split_csv(args.voices) or ["Zephyr"]
    rates = split_csv(args.rates) or ["+0%"]
    styles = split_csv(args.styles)
    notes = []
    partial = False
    residue = 0
    m4b_path = None
    try:
        if args.level == "smoke":
            residue = run_smoke(ctx, langs[0], voices[0], rates[0],
                                styles[0] if styles else None,
                                fixture_for(langs[0]))
        elif args.level == "matrix":
            combos = matrix_combinations(langs, voices, rates, styles, args.runs)
            print(f"[matrix] {len(combos)} combinazioni, "
                  f"concorrenza {args.concurrency}")
            residue = run_matrix(ctx, combos, args.concurrency)
        else:
            book = parse_book(args.book)
            out_m4b = os.path.join(run_dir, "audio", "cloudflare.m4b")
            residue, m4b_path = run_book(
                ctx, book, voices[0], rates[0],
                styles[0] if styles else None, args.chunk_chars,
                args.concurrency, out_m4b)
            if args.compare == "vertex":
                notes.append("A/B Vertex: confronta i PCM `*_vertex.pcm` con i "
                             "corrispondenti Cloudflare in audio/.")
    except SpendCapExceeded as exc:
        partial = True
        notes.append(f"cap di spesa raggiunto: {exc}")
        print(f"[stop] {exc}")
    except CFAuthError as exc:
        partial = True
        notes.append(str(exc))
        print(f"[stop] {exc}")
    except CFCallError as exc:
        # Tentativi esauriti: il run e' parziale, ma i record gia' scritti
        # restano validi e vanno comunque riepilogati nel report.
        partial = True
        notes.append(f"chiamata fallita definitivamente: {exc}")
        print(f"[stop] {exc}")
    finally:
        writer.close()

    records = []
    with open(writer.path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    report = render_report(run_dir, records, residue, partial, notes)
    print(reconciliation_block(records))
    print(f"[fine] report: {report}")
    if m4b_path:
        print(f"[fine] M4B: {m4b_path}")
    print(f"[fine] spesa stimata: EUR {ctx.guard.spent_eur():.4f}")
    return 1 if (residue or partial) else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Verificare sintassi e test**

Run: `python -m py_compile scripts/tts_cloudflare_gemini_test.py`
Run: `python -m pytest test/test_cf_tts_bench.py -v`
Expected: 60 PASS.

- [ ] **Step 5: Verificare che la CLI si presenti**

Run: `python scripts/tts_cloudflare_gemini_test.py --help`
Expected: elenco delle 14 opzioni, exit 0.

- [ ] **Step 6: Commit**

```powershell
git add -f scripts/tts_cloudflare_gemini_test.py
git add test/test_cf_tts_bench.py
git commit -m "feat(bench): CLI e orchestrazione dei tre livelli"
```

---

### Task 12: Wrapper PowerShell e modello delle credenziali

**Files:**
- Create: `scripts/cf_tts_bench.ps1`
- Create: `scripts/cf_tts_bench.env.ps1.example`

**Interfaces:**
- Consumes: la CLI di Task 11
- Produces: nessuna interfaccia Python

Il wrapper non contiene logica di misura: valida i parametri, carica l'env e delega.

- [ ] **Step 1: Scrivere il modello delle credenziali**

```powershell
# scripts/cf_tts_bench.env.ps1.example
# Copia questo file in scripts/cf_tts_bench.env.ps1 e compila i valori.
# Il file cf_tts_bench.env.ps1 NON va mai committato (contiene segreti).

$env:CF_ACCOUNT_ID = "<account id Cloudflare>"
$env:CF_API_TOKEN  = "<API token con permesso Workers AI>"

# Solo per il ramo A/B (-Compare vertex): credenziali Vertex di produzione.
# $env:ABM_GEMINI_BACKEND         = "vertex"
# $env:ABM_GCP_PROJECT_ID         = "<project id>"
# $env:ABM_GOOGLE_CREDENTIALS_FILE = "C:\percorso\service-account.json"
# $env:ABM_TRANSLATE_MODEL        = "gemini-2.5-flash"
```

- [ ] **Step 2: Scrivere il wrapper**

```powershell
<#
.SYNOPSIS
Banco di prova Gemini 3.1 Flash TTS su Cloudflare Workers AI.

.DESCRIPTION
Wrapper parametrico: carica le credenziali da cf_tts_bench.env.ps1 (se
presente) e invoca scripts/tts_cloudflare_gemini_test.py. Nessuna logica di
misura vive qui.

.EXAMPLE
.\scripts\cf_tts_bench.ps1 -Level smoke

.EXAMPLE
.\scripts\cf_tts_bench.ps1 -Level matrix -Langs it,en -Voices Zephyr,Puck -Runs 2

.EXAMPLE
.\scripts\cf_tts_bench.ps1 -Level book -Book .\test\books\esempio.abm -Compare vertex
#>
[CmdletBinding()]
param(
    [ValidateSet('smoke', 'matrix', 'book')]
    [string]$Level = 'smoke',

    [string]$Book,
    [string[]]$Langs = @('it', 'en'),
    [string[]]$Voices = @('Zephyr'),
    [string[]]$Rates = @('+0%'),
    [string[]]$Styles = @(),

    [int]$ChunkChars = 450,
    [int]$Concurrency = 1,
    [int]$Runs = 1,
    [double]$Temperature = 0.3,
    [double]$MaxSpendEur = 2.00,
    [int]$MaxAttempts = 4,

    [ValidateSet('vertex')]
    [string]$Compare,

    [string]$OutDir = './out'
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$envFile = Join-Path $scriptDir 'cf_tts_bench.env.ps1'
if (Test-Path $envFile) {
    Write-Host "[env] carico $envFile"
    . $envFile
}
else {
    Write-Host "[env] $envFile assente: uso le variabili gia' nell'ambiente"
}

if ($Level -eq 'book' -and -not $Book) {
    throw "-Level book richiede -Book <percorso .abm|.txt>"
}
if ($Book -and -not (Test-Path $Book)) {
    throw "File non trovato: $Book"
}

$py = Join-Path $scriptDir 'tts_cloudflare_gemini_test.py'
$cliArgs = @(
    $py,
    '--level', $Level,
    '--langs', ($Langs -join ','),
    '--voices', ($Voices -join ','),
    '--rates', ($Rates -join ','),
    '--chunk-chars', $ChunkChars,
    '--concurrency', $Concurrency,
    '--runs', $Runs,
    '--temperature', $Temperature,
    '--max-spend-eur', $MaxSpendEur,
    '--max-attempts', $MaxAttempts,
    '--out-dir', $OutDir
)
if ($Styles.Count -gt 0) { $cliArgs += @('--styles', ($Styles -join ',')) }
if ($Book) { $cliArgs += @('--book', $Book) }
if ($Compare) { $cliArgs += @('--compare', $Compare) }

Write-Host "[run] python $($cliArgs -join ' ')"
& python @cliArgs
exit $LASTEXITCODE
```

- [ ] **Step 3: Verificare che il wrapper si carichi e valli i parametri**

Run: `powershell -NoProfile -Command "& { .\scripts\cf_tts_bench.ps1 -Level book }"`
Expected: errore `-Level book richiede -Book <percorso .abm|.txt>`, exit ≠ 0.

Run: `powershell -NoProfile -Command "Get-Help .\scripts\cf_tts_bench.ps1"`
Expected: sinossi e i tre esempi.

- [ ] **Step 4: Verificare che il file dei segreti non sia tracciabile per errore**

Run: `git status --porcelain scripts/cf_tts_bench.env.ps1`
Expected: nessun output (il file reale non esiste ancora e comunque `scripts/` è ignorato).

- [ ] **Step 5: Commit**

```powershell
git add -f scripts/cf_tts_bench.ps1
git add -f scripts/cf_tts_bench.env.ps1.example
git commit -m "feat(bench): wrapper PowerShell parametrico e modello credenziali"
```

---

### Task 13: Primo run reale e taratura

Solo qui si spende denaro. Va eseguito dall'utente con credenziali vere, in questo ordine.

**Files:**
- Modify: `scripts/tts_cloudflare_gemini_test.py` (solo se il run reale scopre divergenze)
- Modify: `docs/superpowers/specs/2026-08-25-cloudflare-gemini-tts-bench-design.md` (soglie di go/no-go confermate)

- [ ] **Step 1: Preparare le credenziali**

Copiare `scripts/cf_tts_bench.env.ps1.example` in `scripts/cf_tts_bench.env.ps1` e compilarlo. Verificare che il token abbia il permesso **Workers AI: Read/Edit** e che l'account sia su piano Workers Paid.

- [ ] **Step 2: Eseguire lo smoke**

Run: `.\scripts\cf_tts_bench.ps1 -Level smoke`
Expected: exit 0, `report.md` con una chiamata, ratio nella banda, costo stimato di pochi millesimi di euro.

Se lo schema di risposta divergesse da `{"result": {"audio": ...}}`, correggere `call_cf` e aggiungere un test che fissi lo schema reale osservato.

- [ ] **Step 3: Verificare il formato audio reale**

Ispezionare la prima riga di `metrics.jsonl`: `audio_bytes`, `audio_seconds`, `ratio`. Se il WAV non fosse 24 kHz mono 16 bit, l'anomalia `format` lo segnala: aggiornare `EXPECTED_*` con i valori reali e i test corrispondenti.

- [ ] **Step 4: Eseguire la matrice**

Run: `.\scripts\cf_tts_bench.ps1 -Level matrix -Langs it,en -Voices Zephyr,Puck -Runs 2 -MaxSpendEur 0.50`
Expected: 8 chiamate, nessuna anomalia residua, p50/p95 registrati.

- [ ] **Step 5: Cercare il punto di saturazione**

Ripetere il comando dello Step 4 con `-Concurrency 2`, poi `4`, poi `8`, annotando 429 e p95 di ciascun run.

- [ ] **Step 6: Eseguire un libro reale**

Run: `.\scripts\cf_tts_bench.ps1 -Level book -Book <percorso.abm> -MaxSpendEur 2.00`
Expected: M4B riproducibile, capitoli corretti, nessuna anomalia residua.

- [ ] **Step 7: Riconciliare la spesa**

Confrontare il blocco `RICONCILIAZIONE` di ogni run con Cloudflare Dashboard → Workers & Pages → AI → Usage sulla finestra UTC indicata. Annotare lo scostamento percentuale fra costo stimato e costo fatturato.

- [ ] **Step 8: Aggiornare la spec con le soglie confermate**

Sostituire in `## 2. Obiettivo` la nota "da confermare a valle del primo run completo" con i valori osservati: scostamento di riconciliazione, concorrenza massima senza 429, p95 di Cloudflare contro Vertex.

- [ ] **Step 9: Commit**

```powershell
git add docs/superpowers/specs/2026-08-25-cloudflare-gemini-tts-bench-design.md
git commit -m "docs(spec): soglie go/no-go confermate dal primo run reale"
```

Se lo Step 2 o 3 hanno richiesto correzioni al bench, includerle in un commit separato con `git add -f scripts/tts_cloudflare_gemini_test.py`.

---

## Note per chi esegue

- **Nessun `git push`** in nessun task: la pubblicazione va sempre confermata dall'utente.
- **Artefatti temporanei:** `out/` non va committata. Se durante i test finiscono file `.png`, `.md` o `.txt` nella radice del repo, vanno cancellati prima di chiudere.
- **Se un test fallisce per un motivo diverso da quello atteso**, fermarsi: significa che un'assunzione del piano è sbagliata, e va corretta prima di proseguire, non aggirata.
- **Il gate anti-troncamento non va allentato** per far passare un run. Se produce falsi positivi sistematici, è la banda a dover essere ritarata sulla base dei dati, con un commit dedicato che spiega perché.
