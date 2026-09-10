# La barra VoxCPM avanza per chunk — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** far avanzare la barra di una generazione VOXCPM al ritmo dei chunk che il worker chiude davvero — e dichiarare l'avvio del motore, che su worker freddo dura più della sintesi — invece di aspettare la fine di un capitolo intero.

**Architecture:** il worker RunPod pubblica un payload parziale (`phase`, `chunks_done`, `chunks_total`) da un thread suo, con la POST autenticata come quella dell'SDK; RunPod lo rimanda in `GET /status` sotto `output` mentre il job è `IN_PROGRESS`. Lato ABM `_attendi_esito` consegna quelle righe a una `on_progress`, che `synthesize_chapter` inoltra dal chiamante; `_voxcpm_pre_pass` le raccoglie sotto un lock in due strutture (capitoli consegnati, parziali in volo) e riscrive numero e messaggio insieme. Nessuna infrastruttura nuova: la catena SSE a valle non cambia.

**Tech Stack:** Python 3.11, `runpod` SDK (solo per `JOB_DONE_URL`), `urllib.request`, `threading`, `concurrent.futures`, pytest (ABM), script di prova senza GPU (worker), immagine Docker su GHCR costruita da GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-07-voxcpm-progresso-per-chunk-design.md`

## Global Constraints

- **Due repository.** `abm-voxcpm-worker` (Task 1-3) e `AudioBook-Maker` worktree `VOXCPM` (Task 4-8). Commit separati, mai incrociati.
- **Nel repo del worker si mettono in staging SOLO** `handler.py` e `tools/test_progress.py`: il worktree porta nove file sporchi di altri lavori sotto `data/voci_inventate/` e `tools/voice_design/`. Mai `git add -A`, mai `git add .`.
- **Nessun `git push` senza conferma esplicita dell'utente nel turno corrente**, in entrambi i repository. Vale anche dopo un «pusha subito» precedente. Idem per la release RunPod: la fa l'utente.
- **Mai una release RunPod mentre `inProgress > 0`**: terminerebbe i worker che stanno macinando job pagati.
- **Nessun segreto stampato**: `ABM_RUNPOD_KEY`, `ABM_VOXCPM_API_KEY`, `RUNPOD_AI_API_KEY`, id dell'endpoint e URL firmati non entrano né nei log né nelle risposte.
- **Un avanzamento non deve mai portarsi via un capitolo pagato in GPU.** Ogni percorso nuovo — lato worker e lato client — è avvolto in `try/except` che non rilancia. Stessa politica di `_riga_costo`.
- **Le due direzioni dello sfasamento di versione degradano al comportamento di oggi**: worker vecchio + ABM nuovo = nessun `output` parziale; worker nuovo + ABM vecchio = payload ignorato. Il deploy dell'immagine può precedere o seguire il rilascio di ABM.
- **Interruttori:** `ABM_VOXCPM_PROGRESS=0` (client: non passa mai `on_progress`), `VOXCPM_PROGRESS_MIN_S=0` (worker: non pubblica nulla).
- **`VOXCPM_PROGRESS_MIN_S` resta a 2,0** — default già nel codice e misurato in produzione il 2026-09-07 (60 giri regolari in 130 s). La spec §5 scriveva 1,0 prima della misura: le ondate di chunk distano ~1,5 s e a `concurrency=24` un capitolo ha comunque due o tre scatti, quindi il freno più stretto non aggiungerebbe informazione. Deviazione voluta, dichiarata qui.
- **Le stringhe della barra restano in italiano**, come quelle già presenti in `_voxcpm_pre_pass` e asserite dai test. Allineare all'inglese i messaggi della barra è un lavoro a sé.
- **Il peso complessivo del capitolo non cambia:** `9 * n` punti per un capitolo da `n` chunk (`_VOXCPM_PESO_BARRA = 9`), `progress_total = total_chunks * (9 + 1) + 2`. Cambia solo come si spendono: 90% ai chunk chiusi (8,1 punti l'uno), 10% alla consegna.

### Due precisazioni sui test della spec

- **Test 14** («l'ultimo evento di ogni fase passa sempre, freno o no»): il payload non è un flusso di eventi ma un contatore cumulativo, e la riga porta sempre il valore corrente. Una riga intermedia saltata dal freno non nasconde perciò nessun conteggio: la riga successiva lo contiene già. Il test verifica quel che conta davvero — che il freno regga, e che l'ultima riga pubblicata prima di `chiudi()` porti i numeri definitivi.
- **Test 12** («senza mai un avanzamento, barra e messaggio identici a oggi»): identici sono i valori di `progress_current`, capitolo per capitolo. Il messaggio guadagna la coda col conteggio delle frasi anche senza avanzamenti, perché §7.3 la vuole sempre, e i numeri sono onesti lo stesso (le frasi dei capitoli consegnati).

---

## File Structure

**`abm-voxcpm-worker`**

| File | Responsabilità |
|------|----------------|
| `handler.py` — `_posta` (nuova) | L'unico punto che tocca la rete per pubblicare: una funzione di modulo, sostituibile nei test |
| `handler.py` — `_Avanzamento` | Contatore, fase, thread a passo fisso, chiusura che aspetta |
| `handler.py` — `_action_generate` | Crea il pubblicatore prima del pool (`warmup`) e ne segna i passaggi di fase |
| `handler.py` — `_handle` | Chiude e aspetta il pubblicatore prima che la risposta parta |
| `tools/test_progress.py` (nuovo) | Prova senza GPU: fasi, ordine, freno, guasto, chiusura |

**`AudioBook-Maker`**

| File | Responsabilità |
|------|----------------|
| `voxcpm_tts.py` — `_riga_avanzamento` (nuova) | Filtra e consegna una riga parziale; non solleva mai |
| `voxcpm_tts.py` — `_attendi_esito` | Chiama `on_progress` sugli `IN_PROGRESS`, senza toccare le condizioni d'uscita |
| `voxcpm_tts.py` — `run_job`, `synthesize_chapter`, `progress_enabled` | Inoltro e interruttore |
| `generation_engine.py` — `_voxcpm_pre_pass` | Le due strutture, il lock, i punti e il messaggio |
| `test/test_voxcpm_runpod.py` | Test 1-4 della spec |
| `test/test_voxcpm_generation.py` | Test 5-12 della spec |
| `docs/MANUAL_TESTS_VOXCPM.md` | Il collaudo manuale della barra |

---

## Task 1: Il pubblicatore definitivo del worker e il suo banco di prova

Oggi `_Avanzamento` esiste ma è una sonda: si accende solo se il chiamante manda `input.progress`, porta un diario di strumentazione nella risposta, e fa la POST inline dentro il metodo. Questo task la trasforma nel pubblicatore vero — sempre acceso, senza strumentazione, con la rete isolata in una funzione sostituibile — e le costruisce il banco di prova senza GPU.

**Files:**
- Modify: `abm-voxcpm-worker/handler.py:830-1006` (`_senza_segreti`, `_Avanzamento`)
- Modify: `abm-voxcpm-worker/handler.py:1059-1061` (costruzione del pubblicatore)
- Modify: `abm-voxcpm-worker/handler.py:1413-1418` (fase `deliver` e diario nella risposta)
- Test: `abm-voxcpm-worker/tools/test_progress.py` (nuovo)

**Interfaces:**
- Produces: `handler._posta(url, riga, job_id) -> None` — la POST, sostituibile nei test.
- Produces: `handler._Avanzamento(job: dict | None, totale: int)` con `.chunk()`, `.fase_a(nome: str)`, `.chiudi()`, `.spento: bool`.
- Produces: il payload pubblicato, `{"phase": str, "chunks_done": int, "chunks_total": int}` — è il contratto che il Task 4 consuma.
- Consumes: `handler._pool()`, `handler._action_generate(inp, job_id="", job=None)`, `handler._handle(job)` — già esistenti, firme invariate.

- [ ] **Step 1: Scrivere il test che fallisce**

Creare `abm-voxcpm-worker/tools/test_progress.py`:

```python
# -*- coding: utf-8 -*-
"""L'avanzamento pubblicato dal worker, senza GPU e senza rete.

Il motore e' un pool finto che restituisce un'onda qualunque; la POST verso
RunPod e' sostituita da un registro che annota le righe. Quel che si prova e'
il codice vero del worker: quali fasi escono e in che ordine, che la riga di
`warmup` esca PRIMA che il pool sia pronto (su worker freddo e' il tratto piu'
lungo del job), che il freno regga, che un errore di pubblicazione non si
porti via il capitolo, e che `chiudi()` aspetti davvero il thread.

I tempi sono tarati su un passo di 20 ms: ogni ritardo del copione vale dieci
passi o piu', cosi' l'ordine delle fasi non dipende da come gira la macchina.
"""
import asyncio
import os
import sys
import threading
import time
import types

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Prima dell'import: `_PROGRESS_MIN_S` e' letto una volta sola, al caricamento.
os.environ["VOXCPM_PROGRESS_MIN_S"] = "0.02"
os.environ["ABM_VOXCPM_VERIFY"] = "1"

for name in ("runpod", "runpod.serverless", "runpod.serverless.modules",
             "runpod.serverless.modules.rp_http"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["runpod"].serverless = sys.modules["runpod.serverless"]
sys.modules["runpod.serverless"].start = lambda *a, **k: None
sys.modules["runpod.serverless"].modules = sys.modules[
    "runpod.serverless.modules"]
sys.modules["runpod.serverless.modules"].rp_http = sys.modules[
    "runpod.serverless.modules.rp_http"]
# La forma vera dell'URL dell'SDK: `$ID` sostituito dal job, `isStream`
# aggiunto in coda. Qui non ci va nessuna chiave: la POST e' finta.
sys.modules["runpod.serverless.modules.rp_http"].JOB_DONE_URL = (
    "https://api.runpod.ai/v2/ep-finto/job-done/worker-finto/$ID?x=1")

sys.path.insert(0, REPO)
import handler  # noqa: E402
import verifica  # noqa: E402

SR = handler._SAMPLE_RATE
ESITI = []

# La coda la detta il copione: qui si prova l'avanzamento, non l'ASR.
verifica.Verificatore.coda = lambda self, y, sr, testo: (0, "", 0, "")


def prova(nome, condizione, dettaglio=""):
    ESITI.append((nome, bool(condizione), dettaglio))
    print(f"  {'ok  ' if condizione else 'NO  '}{nome}"
          f"{'  ' + dettaglio if dettaglio and not condizione else ''}")


def onda(durata=0.3):
    """Un tono con dissolvenza e silenzio in coda: un chunk sano."""
    t = np.arange(int(SR * durata)) / SR
    y = (0.2 * np.sin(2 * np.pi * 200.0 * t)).astype(np.float32)
    n = int(SR * 0.02)
    y[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
    return np.concatenate([y, np.zeros(int(SR * 0.1), dtype=np.float32)])


class Registro:
    """Al posto della POST: annota riga e istante, non tocca la rete."""

    def __init__(self, esplode=False):
        self.righe = []
        self.esplode = esplode
        self._lock = threading.Lock()

    def __call__(self, url, riga, job_id):
        if self.esplode:
            raise RuntimeError("endpoint irraggiungibile")
        with self._lock:
            self.righe.append((time.time(), dict(riga)))

    def fasi(self):
        """Le fasi nell'ordine, senza le ripetizioni consecutive."""
        with self._lock:
            fasi = [r["phase"] for _, r in self.righe]
        uscita = []
        for f in fasi:
            if not uscita or uscita[-1] != f:
                uscita.append(f)
        return uscita

    def prima_di(self, fase, istante):
        with self._lock:
            return any(t < istante and r["phase"] == fase
                       for t, r in self.righe)

    def ultima(self):
        with self._lock:
            return dict(self.righe[-1][1]) if self.righe else None

    def quante(self):
        with self._lock:
            return len(self.righe)


class PoolFinto:
    """Il motore ridotto all'osso: un'onda breve per chunk.

    `ritardo` e' il caricamento del modello, che sul worker vero e' di due
    minuti: qui basta che sia misurabile. `per_chunk` e' il tempo di GPU.
    """

    def __init__(self, ritardo=0.0, per_chunk=0.2):
        self.ritardo = ritardo
        self.per_chunk = per_chunk
        self.pronto_a = None

    def carica(self):
        time.sleep(self.ritardo)
        self.pronto_a = time.time()
        return self

    async def generate(self, target_text, seed=None, **kw):
        await asyncio.sleep(self.per_chunk)
        yield onda()


def gira(chunks, registro, pool=None, job_id="job-di-prova", chiudi=True):
    """Un job `generate` completo, col pool finto e la POST registrata.

    `chiudi=True` passa da `_handle`, che chiude il pubblicatore nel suo
    `finally`; `chiudi=False` chiama direttamente l'azione e lascia il
    pubblicatore vivo, che e' quel che serve per provare la chiusura.
    """
    pool = pool or PoolFinto()
    job = {"id": job_id, "input": {"action": "generate",
                                   "chunks": list(chunks),
                                   "voice_latents": "AAAA",
                                   "language": "it",
                                   "concurrency": 2}}
    vecchio_pool, vecchia_posta = handler._pool, handler._posta
    handler._pool = pool.carica
    handler._posta = registro
    try:
        if chiudi:
            return handler._handle(job)
        return handler._action_generate(job["input"], job_id, job)
    finally:
        handler._pool, handler._posta = vecchio_pool, vecchia_posta


TESTI = [f"frase numero {i} da leggere fino in fondo" for i in range(6)]


# ---------------------------------------------------------------------------
# 1. Le fasi, nell'ordine
# ---------------------------------------------------------------------------
def prove_sequenza():
    print("sequenza delle fasi")
    reg = Registro()
    out = gira(TESTI, reg, pool=PoolFinto(ritardo=0.3, per_chunk=0.2))
    prova("il job consegna comunque i suoi chunk",
          out.get("chunks") == len(TESTI), f"out {out.get('chunks')}")
    prova("le fasi escono nell'ordine del job",
          reg.fasi() == ["warmup", "generate", "verify", "deliver"],
          f"fasi {reg.fasi()}")
    prova("l'ultima riga porta i numeri definitivi",
          reg.ultima() == {"phase": "deliver", "chunks_done": len(TESTI),
                           "chunks_total": len(TESTI)},
          f"ultima {reg.ultima()}")


# ---------------------------------------------------------------------------
# 2. Un guasto della pubblicazione non tocca il capitolo
# ---------------------------------------------------------------------------
def prove_guasto():
    print("guasto della pubblicazione")
    sano = Registro()
    atteso = gira(TESTI, sano)
    rotto = Registro(esplode=True)
    out = gira(TESTI, rotto)
    chiavi = ("chunks", "failed_indices", "chunk_samples", "bytes", "format")
    prova("il capitolo esce identico a quello senza pubblicazione",
          {k: out.get(k) for k in chiavi} == {k: atteso.get(k) for k in chiavi},
          f"out {[out.get(k) for k in chiavi]}")
    prova("nessun errore risale al chiamante", "error" not in out)


# ---------------------------------------------------------------------------
# 3. La chiusura aspetta il thread (runpod-python#250)
# ---------------------------------------------------------------------------
def prove_chiusura():
    print("chiusura del pubblicatore")
    reg = Registro()
    gira(TESTI, reg, chiudi=False)
    av = handler._AVANZAMENTO
    handler._chiudi_avanzamento()
    prova("il thread e' finito quando chiudi() ritorna",
          av is not None and av._thread is not None
          and not av._thread.is_alive())
    quante = reg.quante()
    time.sleep(0.2)
    prova("dopo la chiusura non parte piu' nessuna pubblicazione",
          reg.quante() == quante, f"{quante} -> {reg.quante()}")


def main():
    prove_sequenza()
    prove_guasto()
    prove_chiusura()
    falliti = [n for n, ok, _ in ESITI if not ok]
    print(f"\n{len(ESITI) - len(falliti)}/{len(ESITI)} prove passate")
    if falliti:
        for n in falliti:
            print(f"  fallita: {n}")
        sys.exit(1)


main()
```

- [ ] **Step 2: Eseguirlo per vederlo fallire**

Run: `cd "C:/Users/gfran/NEXT srl/Progetti - Documenti/abm-voxcpm-worker" && python tools/test_progress.py`
Expected: FAIL con `AttributeError: module 'handler' has no attribute '_posta'`.

- [ ] **Step 3: Isolare la POST in `_posta` e ripulire `_Avanzamento`**

In `handler.py`, cancellare per intero la funzione `_senza_segreti` (serviva solo al diario della sonda) e sostituire la classe `_Avanzamento` — dal suo `class` fino alla fine di `_nota` — con:

```python
def _posta(url, riga, job_id):
    """La POST di un avanzamento. E' l'unico punto che tocca la rete.

    Header identici a quelli dell'SDK. L'`Authorization` non e' un dettaglio:
    senza, l'endpoint risponde 401 e l'aggiornamento non arriva da nessuna
    parte — misurato il 2026-09-07, sei POST tutte rifiutate in silenzio. La
    chiave e' quella che RunPod mette nell'ambiente del worker, la stessa che
    l'SDK usa per mandare il risultato, e non esce mai dal container.

    Sta fuori dalla classe perche' i test la sostituiscono: e' la sola riga di
    codice che, in una prova senza rete, non si puo' eseguire.
    """
    corpo = json.dumps({"status": "IN_PROGRESS", "output": riga},
                       ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=corpo, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "charset": "utf-8",
                 "Authorization": os.environ.get("RUNPOD_AI_API_KEY", ""),
                 "X-Request-ID": str(job_id)})
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read(200)


class _Avanzamento:
    """Pubblica l'avanzamento del job. Non solleva mai, non blocca la GPU.

    La pubblicazione sta su un thread suo per due ragioni. La prima: il POST
    dura decine di millisecondi e il ciclo che alimenta la GPU non deve mai
    aspettarlo, quindi i chunk chiusi si limitano a incrementare un contatore.
    La seconda: durante il caricamento del motore nessuna coroutine di
    generazione e' ancora partita, e su worker freddo quello e' il tratto piu'
    lungo del job (~120 s misurati) — senza un thread indipendente la barra
    del chiamante resterebbe a zero proprio li'.

    Il thread e' a passo fisso (`VOXCPM_PROGRESS_MIN_S`) e pubblica solo
    quando la riga cambia. Con `ABM_VOXCPM_CONCURRENCY=24` i chunk chiudono a
    ondate: senza passo, una sola ondata farebbe due dozzine di POST identici
    nel giro di un istante.
    """

    def __init__(self, job, totale):
        self.job = job if isinstance(job, dict) else None
        self.totale = int(totale or 0)
        self.fatti = 0
        self.fase = "warmup"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._rotto = False
        self._url = _url_avanzamento(
            str(self.job.get("id") or "")) if self.job else ""
        self.spento = _PROGRESS_MIN_S <= 0 or not self._url
        if self.spento:
            return
        self._thread = threading.Thread(target=self._ciclo,
                                        name="avanzamento", daemon=True)
        self._thread.start()

    def chunk(self):
        """Un chunk ha smesso di occupare la GPU, riuscito o caduto.

        Anche il caduto conta: al suo posto il worker mette un secondo di
        silenzio e tira dritto, quindi per il capitolo e' lavoro finito come
        gli altri.
        """
        if self.spento:
            return
        with self._lock:
            # Solo nella prima passata: i rigenerati della verifica passano di
            # qui una seconda volta, e senza questo la barra del chiamante
            # sfonderebbe il suo totale.
            if self.fase == "generate" and self.fatti < self.totale:
                self.fatti += 1

    def fase_a(self, nome):
        if self.spento:
            return
        with self._lock:
            self.fase = nome

    def chiudi(self):
        """Ferma il pubblicatore e ASPETTA che l'ultimo POST sia partito.

        Nessun aggiornamento puo' sopravvivere alla risposta del job: uno che
        arrivasse dopo riporterebbe il job a IN_PROGRESS e ce lo lascerebbe
        (runpod-python#250), e per noi vorrebbe dire tetto d'esecuzione
        superato, capitolo rigenerato e GPU pagata due volte.

        Guarda il thread e non `spento`: la pubblicazione puo' essersi spenta
        da sola dopo un errore, e il thread andrebbe atteso lo stesso.
        """
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=15)

    def _riga(self):
        with self._lock:
            return {"phase": self.fase, "chunks_done": self.fatti,
                    "chunks_total": self.totale}

    def _ciclo(self):
        ultima = None
        while True:
            fine = self._stop.is_set()
            riga = self._riga()
            if riga != ultima:
                self._invia(riga)
                ultima = riga
            if fine or self._rotto:
                return
            # Sul `_stop` e non su uno sleep: la chiusura non deve aspettare
            # il resto del passo per far uscire l'ultima riga.
            self._stop.wait(_PROGRESS_MIN_S)

    def _invia(self, riga):
        """Un aggiornamento. Non solleva mai: e' un di piu' sopra un capitolo
        gia' pagato in GPU, e non deve poterselo portare via.

        Al primo errore la pubblicazione si spegne per il resto del job: se
        l'endpoint rifiuta una riga rifiutera' anche le altre, e continuare
        vorrebbe dire un messaggio di log ogni due secondi per tutto il
        capitolo.
        """
        try:
            _posta(self._url, riga, str(self.job.get("id") or ""))
        except Exception as e:      # noqa: BLE001 - best effort, per definizione
            self._rotto = True
            print(f"[worker] avanzamento spento dopo un errore: "
                  f"{type(e).__name__}: {e}", flush=True)
```

- [ ] **Step 4: Accendere il pubblicatore per ogni job e togliere il diario dalla risposta**

In `_action_generate`, sostituire

```python
    av = _Avanzamento(job, inp.get("progress"), len(chunks))
```

con

```python
    av = _Avanzamento(job, len(chunks))
```

e sostituire la coda della funzione

```python
    av.fase_a("deliver")
    _deliver_audio(out, payload, inp, job_id, ext, ctype)
    if not av.spento:
        # Solo con la sonda accesa: nel traffico vero questa chiave non esiste.
        out["progress_debug"] = av.diario()
    return out
```

con

```python
    av.fase_a("deliver")
    _deliver_audio(out, payload, inp, job_id, ext, ctype)
    return out
```

- [ ] **Step 5: Eseguire il test e vederlo passare**

Run: `cd "C:/Users/gfran/NEXT srl/Progetti - Documenti/abm-voxcpm-worker" && python tools/test_progress.py`
Expected: `6/6 prove passate`.

- [ ] **Step 6: Verificare che le prove esistenti del worker non si siano mosse**

Run: `cd "C:/Users/gfran/NEXT srl/Progetti - Documenti/abm-voxcpm-worker" && python tools/test_verifica.py && python tools/test_assemble.py`
Expected: entrambe passate. `_action_generate` chiamata con due argomenti (`job=None`) deve continuare a funzionare: il pubblicatore nasce `spento` e non pubblica nulla.

- [ ] **Step 7: Commit**

```bash
cd "C:/Users/gfran/NEXT srl/Progetti - Documenti/abm-voxcpm-worker"
git add handler.py tools/test_progress.py
git commit -m "$(cat <<'MSG'
feat(voxcpm): il worker dice a che punto e', invece di dirlo solo alla fine

La sonda diventa il pubblicatore vero: acceso per ogni job, senza il diario
di strumentazione nella risposta, con la POST isolata in `_posta` perche' sia
sostituibile da una prova senza rete.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3
MSG
)"
```

---

## Task 2: La fase `warmup` esce prima che il pool sia pronto

Il primo chunk di un job su worker freddo si chiude a t+123 s su 130 s totali: se il worker pubblicasse solo `chunks_done`, la barra resterebbe a zero per due minuti — lo stesso difetto di oggi, spostato di un livello. La riga `warmup` deve uscire prima del caricamento del motore, non dopo.

**Files:**
- Modify: `abm-voxcpm-worker/handler.py` (`_action_generate`, il passaggio a `generate`)
- Test: `abm-voxcpm-worker/tools/test_progress.py`

**Interfaces:**
- Consumes: `handler._Avanzamento(job, totale)` con `self.fase = "warmup"` alla nascita (Task 1).
- Produces: la garanzia d'ordine `warmup` prima di `_pool()`, su cui il messaggio «preparazione del motore vocale» del Task 7 si appoggia.

- [ ] **Step 1: Scrivere il test che fallisce**

Aggiungere in `tools/test_progress.py`, prima di `def main()`:

```python
# ---------------------------------------------------------------------------
# 4. Il warmup esce prima che il motore sia pronto
# ---------------------------------------------------------------------------
def prove_warmup_prima_del_pool():
    print("warmup e caricamento del motore")
    reg = Registro()
    pool = PoolFinto(ritardo=0.4, per_chunk=0.2)
    gira(TESTI, reg, pool=pool)
    prova("il pool ha registrato quando e' diventato pronto",
          pool.pronto_a is not None)
    # Un test sul solo ORDINE delle fasi non distinguerebbe una `warmup`
    # pubblicata tardi: qui si guarda l'istante, che e' la cosa che conta —
    # su worker freddo quei secondi sono la meta' del job.
    prova("una riga di warmup e' partita prima che il pool fosse pronto",
          reg.prima_di("warmup", pool.pronto_a),
          f"righe {[(round(t - pool.pronto_a, 3), r['phase']) for t, r in reg.righe]}")
    prova("il warmup non annuncia chunk che non esistono",
          all(r["chunks_done"] == 0 for _, r in reg.righe
              if r["phase"] == "warmup"))
    prova("ma il denominatore e' gia' noto",
          all(r["chunks_total"] == len(TESTI) for _, r in reg.righe))
```

e aggiungere la chiamata in `main()`, dopo `prove_sequenza()`:

```python
    prove_warmup_prima_del_pool()
```

- [ ] **Step 2: Eseguirlo per vederlo fallire**

Run: `cd "C:/Users/gfran/NEXT srl/Progetti - Documenti/abm-voxcpm-worker" && python tools/test_progress.py`
Expected: FAIL su «una riga di warmup è partita prima che il pool fosse pronto» — oggi la fase resta `warmup` fino alla verifica, quindi anche la sequenza del test 13 (`warmup` → `generate` → …) fallisce, perché `generate` non compare mai.

- [ ] **Step 3: Segnare il passaggio a `generate`**

In `_action_generate`, sostituire

```python
    t0 = time.time()
    chiuso = _genera(range(len(chunks)), seed, failed)
```

con

```python
    # Da qui il motore e' caricato e i chunk cominciano a chiudere: la fase
    # cambia PRIMA del giro, cosi' la riga che esce durante la generazione
    # non e' ancora marcata `warmup`.
    av.fase_a("generate")
    t0 = time.time()
    chiuso = _genera(range(len(chunks)), seed, failed)
```

- [ ] **Step 4: Eseguire il test e vederlo passare**

Run: `cd "C:/Users/gfran/NEXT srl/Progetti - Documenti/abm-voxcpm-worker" && python tools/test_progress.py`
Expected: `10/10 prove passate`.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/gfran/NEXT srl/Progetti - Documenti/abm-voxcpm-worker"
git add handler.py tools/test_progress.py
git commit -m "$(cat <<'MSG'
feat(voxcpm): il worker dichiara l'attesa del motore, che dura piu' di tutto

Su worker freddo il primo chunk si chiude a t+123s di un job da 130s: senza
una fase dichiarata prima del pool, la barra resterebbe a zero proprio nel
tratto piu' lungo.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3
MSG
)"
```

---

## Task 3: Il freno e l'interruttore del worker

**Files:**
- Modify: `abm-voxcpm-worker/handler.py:805` (commento su `_PROGRESS_MIN_S`)
- Test: `abm-voxcpm-worker/tools/test_progress.py`

**Interfaces:**
- Consumes: `handler._PROGRESS_MIN_S` (float, da `VOXCPM_PROGRESS_MIN_S`, default 2.0).
- Produces: la garanzia che `VOXCPM_PROGRESS_MIN_S=0` non pubblichi nulla — l'interruttore lato immagine citato nei Global Constraints.

- [ ] **Step 1: Scrivere il test**

Aggiungere in `tools/test_progress.py`, prima di `def main()`:

```python
# ---------------------------------------------------------------------------
# 5. Il freno e l'interruttore
# ---------------------------------------------------------------------------
def prove_freno():
    print("freno e interruttore")
    vecchio = handler._PROGRESS_MIN_S
    try:
        # Sei chunk che chiudono a ondate dentro un passo solo: senza freno
        # sarebbero sei POST indistinguibili nel giro di un istante.
        handler._PROGRESS_MIN_S = 0.5
        reg = Registro()
        gira(TESTI, reg, pool=PoolFinto(ritardo=0.0, per_chunk=0.05))
        prova("il freno tiene le pubblicazioni a poche righe",
              reg.quante() <= 3, f"pubblicate {reg.quante()}")
        # Il payload e' un contatore, non un flusso di eventi: una riga
        # saltata dal freno non nasconde nessun conteggio, perche' la
        # successiva porta gia' il valore aggiornato. Quel che non si puo'
        # perdere e' l'ultima.
        prova("l'ultima riga porta comunque i numeri definitivi",
              reg.ultima() == {"phase": "deliver", "chunks_done": len(TESTI),
                               "chunks_total": len(TESTI)},
              f"ultima {reg.ultima()}")

        handler._PROGRESS_MIN_S = 0
        spento = Registro()
        out = gira(TESTI, spento)
        prova("a zero non si pubblica niente", spento.quante() == 0,
              f"pubblicate {spento.quante()}")
        prova("e il capitolo esce lo stesso",
              out.get("chunks") == len(TESTI))
    finally:
        handler._PROGRESS_MIN_S = vecchio
```

e aggiungere la chiamata in `main()`, dopo `prove_chiusura()`:

```python
    prove_freno()
```

- [ ] **Step 2: Eseguirlo**

Run: `cd "C:/Users/gfran/NEXT srl/Progetti - Documenti/abm-voxcpm-worker" && python tools/test_progress.py`
Expected: PASS — il freno e l'interruttore sono già nel codice del Task 1; questo test li inchioda. Se una delle quattro prove fallisce, il difetto è nel Task 1 e va corretto lì (candidati: `_ciclo` che non rispetta `_PROGRESS_MIN_S`, oppure `spento` che non guarda il passo a zero).

- [ ] **Step 3: Scrivere il commento che spiega il valore**

In `handler.py`, sostituire

```python
_PROGRESS_MIN_S = float(os.environ.get("VOXCPM_PROGRESS_MIN_S", "2.0"))
```

con

```python
# Passo del pubblicatore d'avanzamento, in secondi. `0` lo spegne del tutto.
#
# 2,0 e' il valore misurato in produzione il 2026-09-07: 60 giri regolari in
# un job da 130 s, senza disturbare il ciclo che alimenta la GPU. Piu' stretto
# non aggiungerebbe informazione — i chunk chiudono a ondate di `concurrency`,
# e le ondate distano circa un secondo e mezzo l'una dall'altra, quindi un
# capitolo da 30 chunk a concorrenza 24 ha comunque due o tre scatti e non
# trenta.
_PROGRESS_MIN_S = float(os.environ.get("VOXCPM_PROGRESS_MIN_S", "2.0"))
```

- [ ] **Step 4: Rieseguire e committare**

Run: `cd "C:/Users/gfran/NEXT srl/Progetti - Documenti/abm-voxcpm-worker" && python tools/test_progress.py`
Expected: `14/14 prove passate`.

```bash
cd "C:/Users/gfran/NEXT srl/Progetti - Documenti/abm-voxcpm-worker"
git add handler.py tools/test_progress.py
git commit -m "$(cat <<'MSG'
test(voxcpm): il freno dell'avanzamento e il suo interruttore, inchiodati

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3
MSG
)"
```

---

## Task 4: ABM legge le righe parziali senza scambiarle per un esito

Da qui in avanti si lavora nel worktree `AudioBook-Maker/.worktrees/VOXCPM`.

**Files:**
- Modify: `voxcpm_tts.py:606-621` (accanto a `_riga_costo`)
- Modify: `voxcpm_tts.py:623-624` (firma di `_attendi_esito`) e la coda del ciclo (il ramo non terminale)
- Test: `test/test_voxcpm_runpod.py`

**Interfaces:**
- Produces: `voxcpm_tts._riga_avanzamento(on_progress, out, job_id) -> None`.
- Produces: `_attendi_esito(job_id, ses, sleep, attesa, tetto_exec, tetto_coda, clock, on_queue, cancelled=None, on_billing=None, on_progress=None)`.
- Produces: il contratto della callback — `on_progress({"phase": str, "chunks_done": int, "chunks_total": int})`, che il Task 6 consuma.

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in fondo a `test/test_voxcpm_runpod.py`:

```python
def test_un_parziale_muove_la_callback_e_il_polling_continua():
    # La regressione peggiore di tutta la modifica: un `output` parziale letto
    # come esito chiuderebbe il job a meta' e consegnerebbe un capitolo
    # inesistente. L'uscita resta governata dai soli stati terminali.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-1"})],
        get=[FintaRisposta(body={"status": "IN_PROGRESS",
                                 "output": {"phase": "generate",
                                            "chunks_done": 3,
                                            "chunks_total": 8}}),
             FintaRisposta(body={"status": "IN_PROGRESS",
                                 "output": {"phase": "deliver",
                                            "chunks_done": 8,
                                            "chunks_total": 8}}),
             FintaRisposta(body={"status": "COMPLETED",
                                 "output": {"audio_seconds": 42.0,
                                            "failed_indices": []}})],
    )
    viste = []
    out = voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto,
                             poll=0, on_progress=viste.append)
    assert out == {"audio_seconds": 42.0, "failed_indices": []}
    assert viste == [{"phase": "generate", "chunks_done": 3, "chunks_total": 8},
                     {"phase": "deliver", "chunks_done": 8, "chunks_total": 8}]


@pytest.mark.parametrize("parziale", [
    None,                                        # nessun output
    {"chunks_done": 3},                          # senza denominatore
    {"chunks_done": 3, "chunks_total": 0},       # denominatore vuoto
    {"chunks_done": -1, "chunks_total": 8},      # conteggio assurdo
    {"chunks_done": "3", "chunks_total": "8"},   # numeri che non lo sono
    [1, 2, 3],                                   # nemmeno un dizionario
])
def test_un_parziale_malformato_si_ignora_in_silenzio(parziale):
    # Un worker di un'altra versione non e' un errore da propagare: e' un
    # worker che non conosce questo canale, e la barra deve solo restare
    # ferma.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-1"})],
        get=[FintaRisposta(body={"status": "IN_PROGRESS",
                                 "output": parziale}),
             FintaRisposta(body={"status": "COMPLETED", "output": {}})],
    )
    viste = []
    voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0,
                       on_progress=viste.append)
    assert viste == []


def test_una_callback_che_esplode_non_si_porta_via_il_capitolo():
    # Politica di `_riga_costo`: un di piu' che si rompe non deve mai
    # sostituire l'esito vero, ne' cancellare una GPU gia' pagata.
    def scoppia(_riga):
        raise RuntimeError("la barra e' sparita")

    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-1"})],
        get=[FintaRisposta(body={"status": "IN_PROGRESS",
                                 "output": {"phase": "generate",
                                            "chunks_done": 1,
                                            "chunks_total": 4}}),
             FintaRisposta(body={"status": "COMPLETED",
                                 "output": {"audio_seconds": 1.0}})],
    )
    out = voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto,
                             poll=0, on_progress=scoppia)
    assert out == {"audio_seconds": 1.0}


def test_senza_callback_il_comportamento_non_cambia():
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-1"})],
        get=[FintaRisposta(body={"status": "IN_PROGRESS",
                                 "output": {"phase": "generate",
                                            "chunks_done": 1,
                                            "chunks_total": 4}}),
             FintaRisposta(body={"status": "COMPLETED",
                                 "output": {"audio_seconds": 1.0}})],
    )
    out = voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto,
                             poll=0)
    assert out == {"audio_seconds": 1.0}
```

- [ ] **Step 2: Eseguirli per vederli fallire**

Run: `python -m pytest test/test_voxcpm_runpod.py -k "parziale or callback" -v`
Expected: FAIL con `TypeError: run_job() got an unexpected keyword argument 'on_progress'`.

- [ ] **Step 3: Scrivere `_riga_avanzamento` e chiamarla**

In `voxcpm_tts.py`, subito dopo la fine di `_riga_costo`, aggiungere:

```python
def _riga_avanzamento(on_progress, out, job_id):
    """Consegna un avanzamento parziale al chiamante. Non solleva mai.

    Passano solo le righe complete. Un `output` assente, di forma diversa o
    con numeri assurdi non e' un errore da propagare: e' un worker di
    un'altra versione, che di questo canale non sa niente, e la barra deve
    solo restare ferma come faceva prima.

    I `bool` sono esclusi apposta: in Python `True` e' un `int`, e un
    `chunks_total` a `True` diventerebbe un denominatore di 1.
    """
    if not isinstance(out, dict):
        return
    fatti = out.get("chunks_done")
    totale = out.get("chunks_total")
    if not isinstance(totale, int) or isinstance(totale, bool) or totale <= 0:
        return
    if not isinstance(fatti, int) or isinstance(fatti, bool) or fatti < 0:
        return
    try:
        on_progress({"phase": str(out.get("phase") or ""),
                     "chunks_done": fatti, "chunks_total": totale})
    except Exception:      # noqa: BLE001 - best effort, per definizione
        _LOG.warning("avanzamento non registrato per il job %s", job_id)
```

Poi cambiare la firma di `_attendi_esito`:

```python
def _attendi_esito(job_id, ses, sleep, attesa, tetto_exec, tetto_coda, clock,
                    on_queue, cancelled=None, on_billing=None,
                    on_progress=None):
```

e, nel ramo non terminale, sostituire

```python
        if t_run is None and on_queue is not None:
            on_queue(trascorso)
        _dormi_annullabile(sleep, attesa, cancelled, job_id, ses)
```

con

```python
        # Dopo il blocco degli stati terminali, non prima: nessun parziale
        # puo' essere scambiato per un esito, e l'uscita dal ciclo resta
        # governata dai soli COMPLETED/FAILED/CANCELLED/TIMED_OUT.
        if on_progress is not None and stato == "IN_PROGRESS":
            _riga_avanzamento(on_progress, st.get("output"), job_id)
        if t_run is None and on_queue is not None:
            on_queue(trascorso)
        _dormi_annullabile(sleep, attesa, cancelled, job_id, ses)
```

- [ ] **Step 4: Inoltrare da `run_job`**

Nella firma di `run_job`, sostituire

```python
def run_job(payload, *, session=None, sleep=time.sleep, poll=None, timeout=None,
            queue_timeout=None, clock=time.time, on_queue=None, cancelled=None,
            on_billing=None):
```

con

```python
def run_job(payload, *, session=None, sleep=time.sleep, poll=None, timeout=None,
            queue_timeout=None, clock=time.time, on_queue=None, cancelled=None,
            on_billing=None, on_progress=None):
```

aggiungere in coda al docstring, dopo il paragrafo di `on_billing`:

```
        on_progress: callback opzionale `(riga)` chiamata a ogni sonda che
            trova un avanzamento parziale del worker: `{"phase",
            "chunks_done", "chunks_total"}`. Serve alla barra, che senza
            questo si muove solo a capitolo consegnato. Un worker che non lo
            pubblica non la fa chiamare mai.
```

e nella chiamata sostituire

```python
        return _attendi_esito(job_id, ses, sleep, attesa, tetto_exec,
                              tetto_coda, clock, on_queue, cancelled=cancelled,
                              on_billing=on_billing)
```

con

```python
        return _attendi_esito(job_id, ses, sleep, attesa, tetto_exec,
                              tetto_coda, clock, on_queue, cancelled=cancelled,
                              on_billing=on_billing, on_progress=on_progress)
```

- [ ] **Step 5: Eseguire i test e vederli passare**

Run: `python -m pytest test/test_voxcpm_runpod.py -v`
Expected: PASS, tutti — i vecchi compresi.

- [ ] **Step 6: Commit**

```bash
git add voxcpm_tts.py test/test_voxcpm_runpod.py
git commit -m "$(cat <<'MSG'
feat(voxcpm): il client ascolta gli avanzamenti del worker mentre il job gira

`/status` porta gia' il payload parziale sotto `output` durante IN_PROGRESS:
si consegna a una callback e si continua a sondare. L'uscita dal ciclo resta
governata dai soli stati terminali.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3
MSG
)"
```

---

## Task 5: L'inoltro fino a `synthesize_chapter` e l'interruttore

**Files:**
- Modify: `voxcpm_tts.py:445-447` (accanto a `poll_seconds`)
- Modify: `voxcpm_tts.py:832-833` (firma di `synthesize_chapter`) e `voxcpm_tts.py:947-949` (chiamata a `run_job`)
- Test: `test/test_voxcpm_runpod.py`

**Interfaces:**
- Produces: `voxcpm_tts.progress_enabled() -> bool`.
- Produces: `synthesize_chapter(chunks, voice_id, dest_path, *, key="", session=None, sleep=None, on_queue=None, cancelled=None, on_progress=None)` — la firma che il Task 6 chiama.

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in fondo a `test/test_voxcpm_runpod.py`:

```python
def _sessione_di_un_capitolo(parziali):
    """Un job che pubblica `parziali` e poi consegna un capitolo sano."""
    return FintaSessione(
        post=[FintaRisposta(body={"id": "job-1"})],
        get=[FintaRisposta(body={"status": "IN_PROGRESS", "output": p})
             for p in parziali]
            + [FintaRisposta(body={"status": "COMPLETED",
                                   "output": {"failed_indices": [],
                                              "sample_rate": 48000,
                                              "chars": 3,
                                              "audio_seconds": 1.0,
                                              "tts_seconds": 0.5,
                                              "audio_b64": ""}})],
    )


def test_il_capitolo_inoltra_gli_avanzamenti(tmp_path, monkeypatch):
    monkeypatch.setattr(voxcpm_tts, "clone_block",
                        lambda voice_id: {"voice_latents": "AAAA"})
    ses = _sessione_di_un_capitolo(
        [{"phase": "warmup", "chunks_done": 0, "chunks_total": 2},
         {"phase": "generate", "chunks_done": 2, "chunks_total": 2}])
    viste = []
    voxcpm_tts.synthesize_chapter(
        ["uno", "due"], "voxcpm:v2:it-IT/Elena",
        str(tmp_path / "ch.pcm"), session=ses, sleep=dormi_finto,
        on_progress=viste.append)
    assert [r["phase"] for r in viste] == ["warmup", "generate"]


def test_l_interruttore_spegne_l_inoltro(tmp_path, monkeypatch):
    # `ABM_VOXCPM_PROGRESS=0` riporta la barra al comportamento di prima
    # senza toccare l'immagine sulla GPU.
    monkeypatch.setenv("ABM_VOXCPM_PROGRESS", "0")
    monkeypatch.setattr(voxcpm_tts, "clone_block",
                        lambda voice_id: {"voice_latents": "AAAA"})
    ses = _sessione_di_un_capitolo(
        [{"phase": "generate", "chunks_done": 1, "chunks_total": 2}])
    viste = []
    voxcpm_tts.synthesize_chapter(
        ["uno", "due"], "voxcpm:v2:it-IT/Elena",
        str(tmp_path / "ch.pcm"), session=ses, sleep=dormi_finto,
        on_progress=viste.append)
    assert viste == []
```

- [ ] **Step 2: Eseguirli per vederli fallire**

Run: `python -m pytest test/test_voxcpm_runpod.py -k "inoltra or interruttore" -v`
Expected: FAIL con `TypeError: synthesize_chapter() got an unexpected keyword argument 'on_progress'`.

- [ ] **Step 3: Scrivere l'interruttore**

In `voxcpm_tts.py`, subito dopo `poll_seconds()`, aggiungere:

```python
def progress_enabled():
    """Se il client debba ascoltare gli avanzamenti parziali del worker.

    A zero la barra torna a muoversi solo a capitolo consegnato, come prima
    di questo canale: e' l'interruttore da girare se il polling di `/status`
    dovesse mai diventare un problema, e non richiede di ricostruire
    l'immagine sulla GPU.
    """
    return _i("ABM_VOXCPM_PROGRESS", 1) != 0
```

- [ ] **Step 4: Inoltrare da `synthesize_chapter`**

Sostituire la firma

```python
def synthesize_chapter(chunks, voice_id, dest_path, *, key="", session=None,
                       sleep=None, on_queue=None, cancelled=None):
```

con

```python
def synthesize_chapter(chunks, voice_id, dest_path, *, key="", session=None,
                       sleep=None, on_queue=None, cancelled=None,
                       on_progress=None):
```

nel docstring sostituire

```
        session, sleep, on_queue: inoltrati a `run_job`.
```

con

```
        session, sleep, on_queue: inoltrati a `run_job`.
        on_progress: callback opzionale degli avanzamenti parziali, inoltrata
            a `run_job` e spenta da `ABM_VOXCPM_PROGRESS=0`. Un capitolo
            rifatto ripubblica `chunks_done` da zero: la monotonia della
            barra e' responsabilita' del chiamante, non di qui.
```

e sostituire la chiamata

```python
            out = run_job(payload, session=session, sleep=riposa,
                          on_queue=on_queue, cancelled=cancelled,
                          on_billing=stats["runpod"].append)
```

con

```python
            out = run_job(payload, session=session, sleep=riposa,
                          on_queue=on_queue, cancelled=cancelled,
                          on_billing=stats["runpod"].append,
                          on_progress=(on_progress if progress_enabled()
                                       else None))
```

- [ ] **Step 5: Eseguire i test e vederli passare**

Run: `python -m pytest test/test_voxcpm_runpod.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add voxcpm_tts.py test/test_voxcpm_runpod.py
git commit -m "$(cat <<'MSG'
feat(voxcpm): il capitolo inoltra gli avanzamenti, e un interruttore li spegne

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3
MSG
)"
```

---

## Task 6: La barra si muove per chunk

**Files:**
- Modify: `generation_engine.py` — `_voxcpm_pre_pass`: le strutture prima di `_uno`, la chiamata a `synthesize_chapter` dentro `_uno`, e la scrittura della barra a capitolo consegnato (oggi `generation_engine.py:3546-3552`)
- Test: `test/test_voxcpm_generation.py`

**Interfaces:**
- Consumes: `voxcpm_tts.synthesize_chapter(..., on_progress=...)` (Task 5) e il payload `{"phase", "chunks_done", "chunks_total"}` (Task 4).
- Produces: dentro `_voxcpm_pre_pass` — `consegnati: dict[int, int]` (capitolo → numero di chunk), `parziali: dict[int, int]` (capitolo in volo → chunk chiusi, monotono), `fasi: dict[int, str]`, `_avanza(ci, n_chunk, riga) -> None`, `_scrivi_barra() -> None` (da chiamare col lock preso).

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in `test/test_voxcpm_generation.py`, dopo la classe `JobSpia`:

```python
class JobSpiaFine(dict):
    """Un job che ricorda numero E messaggio a ogni scrittura della barra.

    La coppia si osserva insieme perche' insieme viene scritta: un numero
    aggiornato accanto a un messaggio vecchio e' esattamente il difetto che
    il lock deve rendere impossibile.
    """

    def __init__(self):
        super().__init__(progress_current=2, progress_message="")
        self.storia = []

    def __setitem__(self, chiave, valore):
        super().__setitem__(chiave, valore)
        if chiave == "progress_current":
            self.storia.append((valore, self.get("progress_message")))


class SintesiConAvanzamento:
    """Come FintaSintesi, ma prima di consegnare pubblica un copione.

    E' il worker che parla: il doppio deve poterlo imitare riga per riga,
    fase per fase, perche' e' su quelle righe che la barra si muove.
    """

    def __init__(self, copione):
        self.copione = list(copione)
        self.chiamate = []

    def __call__(self, chunks, voice_id, dest_path, **kw):
        self.chiamate.append(list(chunks))
        on_progress = kw.get("on_progress")
        if on_progress is not None:
            for riga in self.copione:
                on_progress(dict(riga))
        with open(dest_path, "wb") as f:
            f.write(b"\x11\x22" * len(chunks))
        return {"sample_rate": 48000, "chars": sum(len(c) for c in chunks),
                "audio_seconds": 1.0 * len(chunks), "tts_seconds": 0.5,
                "jobs": 1, "redone": 0, "bounced": 0, "failed_chunks": 0,
                "bytes": 2 * len(chunks), "runpod": []}


def _con_copione(monkeypatch, copione):
    """Installa il doppio che pubblica `copione` e rende la corsa seriale."""
    f = SintesiConAvanzamento(copione)
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", f)
    monkeypatch.setattr(voxcpm_tts, "apply_rate", lambda *a, **k: False)
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "1")
    return f


def test_i_parziali_muovono_la_barra_prima_di_ogni_consegna(tmp_path, monkeypatch):
    # Il difetto da togliere: con un capitolo da minuti, la barra non dava
    # nessun segno di vita finche' il job non finiva.
    _con_copione(monkeypatch, [
        {"phase": "generate", "chunks_done": 1, "chunks_total": 2}])
    job = JobSpiaFine()
    generation_engine._voxcpm_pre_pass(
        PIANO, VOCE, "+0%", tmp_path, "job-1", set(), job=job,
        peso_barra=generation_engine._VOXCPM_PESO_BARRA)
    # Un chunk chiuso vale il 90% del suo peso: 9 * 0,9 = 8,1 punti.
    primo, messaggio = job.storia[0]
    assert primo == 2 + int(8.1)
    assert messaggio.startswith("Sintesi vocale: 0 di 3 capitoli")


def test_un_avanzamento_che_arretra_non_abbassa_la_barra(tmp_path, monkeypatch):
    # Due casi veri: un capitolo rifatto riparte da zero, e la fase `verify`
    # non porta un conteggio nuovo. Una barra che arretra e' il difetto
    # peggiore di una barra.
    _con_copione(monkeypatch, [
        {"phase": "generate", "chunks_done": 2, "chunks_total": 2},
        {"phase": "generate", "chunks_done": 0, "chunks_total": 2}])
    job = JobSpiaFine()
    generation_engine._voxcpm_pre_pass(
        PIANO, VOCE, "+0%", tmp_path, "job-1", set(), job=job,
        peso_barra=generation_engine._VOXCPM_PESO_BARRA)
    valori = [v for v, _ in job.storia]
    assert valori == sorted(valori)


def test_il_capitolo_consegnato_vale_esattamente_il_suo_peso(tmp_path, monkeypatch):
    _con_copione(monkeypatch, [
        {"phase": "generate", "chunks_done": 1, "chunks_total": 2}])
    job = JobSpiaFine()
    generation_engine._voxcpm_pre_pass(
        PIANO, VOCE, "+0%", tmp_path, "job-1", set(), job=job,
        peso_barra=generation_engine._VOXCPM_PESO_BARRA)
    # Capitoli da 2, 1 e 3 chunk: dopo ogni consegna il totale e' 9 * chunk
    # consegnati, senza residui dei parziali.
    valori = [v for v, _ in job.storia]
    assert 2 + 9 * 2 in valori and 2 + 9 * 3 in valori
    assert job["progress_current"] == 2 + 9 * 6


def test_un_worker_che_conta_piu_chunk_non_sfonda_il_capitolo(tmp_path, monkeypatch):
    # Il worker scarta i chunk vuoti prima di generare, quindi il suo
    # denominatore puo' essere diverso: la barra usa sempre il proprio.
    _con_copione(monkeypatch, [
        {"phase": "generate", "chunks_done": 99, "chunks_total": 99}])
    job = JobSpiaFine()
    generation_engine._voxcpm_pre_pass(
        PIANO, VOCE, "+0%", tmp_path, "job-1", set(), job=job,
        peso_barra=generation_engine._VOXCPM_PESO_BARRA)
    assert max(v for v, _ in job.storia) <= 2 + 9 * 6
    assert job["progress_current"] == 2 + 9 * 6


def test_senza_avanzamenti_la_barra_e_quella_di_prima(tmp_path, sintesi_finta):
    # Worker vecchio: nessuna riga parziale, nessuna callback. I valori
    # devono essere identici a quelli di prima di questo canale.
    job = JobSpia()
    generation_engine._voxcpm_pre_pass(
        PIANO, VOCE, "+0%", tmp_path, "job-1", set(), job=job,
        peso_barra=generation_engine._VOXCPM_PESO_BARRA)
    assert job.storia == [2 + 9 * 2, 2 + 9 * 3, 2 + 9 * 6]
```

E aggiornare i due test esistenti che asserivano il messaggio senza la coda delle frasi:

```python
    assert job["progress_message"] == "Sintesi vocale: 3 di 3 capitoli"
```
diventa
```python
    assert job["progress_message"] == "Sintesi vocale: 3 di 3 capitoli (6 di 6 frasi)"
```

e

```python
    assert job["progress_message"] == "Sintesi vocale: 1 di 1 capitolo"
```
diventa
```python
    assert job["progress_message"] == "Sintesi vocale: 1 di 1 capitolo (1 di 1 frase)"
```

- [ ] **Step 2: Eseguirli per vederli fallire**

Run: `python -m pytest test/test_voxcpm_generation.py -v`
Expected: FAIL — i nuovi su `job.storia[0]` (oggi la prima scrittura arriva solo a capitolo consegnato) e i due aggiornati sul messaggio.

- [ ] **Step 3: Le due strutture, il lock e la scrittura**

In `generation_engine.py`, dentro `_voxcpm_pre_pass`, subito prima di `def _uno(gruppo):`, inserire:

```python
    # Quanto vale un capitolo, e quanto ne vale la coda. I chunk generati non
    # sono il 100% del lavoro: dopo di loro restano i giri di rigenerazione
    # delle code tagliate, l'upload su R2 e il download qui. La barra non deve
    # inchiodarsi su un capitolo che sembra finito e non lo e'.
    _QUOTA_CHUNK = 0.9

    totale_frasi = sum(len(indici) for _, indici in gruppi)
    consegnati = {}    # ci -> numero di chunk, scritto a future completata
    parziali = {}      # ci -> chunk chiusi, scritto dalle callback
    fasi = {}          # ci -> ultima fase vista, scritto dalle callback
    # Le callback arrivano dai thread dell'executor, la consegna dal thread
    # del job: numero e messaggio si scrivono sotto lo stesso lock, cosi' la
    # coppia non puo' mai essere osservata mezza aggiornata.
    barra = threading.Lock()

    def _scrivi_barra():
        """Riscrive numero e messaggio. Il lock lo prende il chiamante.

        Il messaggio PRIMA del numero: chi osserva la barra reagisce al
        numero, e deve trovare accanto il messaggio nuovo, non quello di un
        istante fa.
        """
        in_volo = [ci for ci in fasi if ci not in consegnati]
        frasi = sum(consegnati.values()) + sum(parziali[ci] for ci in in_volo)
        punti = peso_barra * (sum(consegnati.values())
                              + _QUOTA_CHUNK * sum(parziali[ci]
                                                   for ci in in_volo))
        if in_volo and all(fasi[ci] == "warmup" for ci in in_volo):
            # Su worker freddo il motore ci mette due minuti a caricarsi, e
            # oggi quel tratto e' completamente muto. La precedenza, quando
            # le fasi si mescolano, e' al conteggio delle frasi: appena UN
            # capitolo genera, il messaggio torna a contarle.
            coda = "preparazione del motore vocale"
        elif in_volo and all(fasi[ci] in ("verify", "deliver")
                             for ci in in_volo):
            # «Tutti» e non «almeno uno»: con due job paralleli, uno in
            # rifinitura e uno in generazione, alternare i due messaggi
            # darebbe un lampeggio senza informazione.
            coda = "rifinitura e consegna"
        else:
            coda = (f"{frasi} di {totale_frasi} "
                    f"fras{'e' if totale_frasi == 1 else 'i'}")
        job["progress_message"] = (
            f"Sintesi vocale: {len(consegnati)} di {len(gruppi)} "
            f"capitol{'o' if len(gruppi) == 1 else 'i'} ({coda})")
        job["progress_current"] = 2 + int(punti)

    def _avanza(ci, n_chunk, riga):
        """Un avanzamento del capitolo `ci`. Gira sui thread dell'executor.

        Il denominatore e' quello di ABM: il worker scarta i chunk vuoti
        prima di generare, quindi il suo conteggio puo' essere piu' piccolo,
        e il peso del capitolo deve chiudere a `peso_barra * n` comunque.
        """
        fatti = min(int(riga.get("chunks_done") or 0), n_chunk)
        with barra:
            if ci in consegnati:
                # La future e' gia' tornata: il capitolo vale il suo peso
                # pieno, e una riga in ritardo non puo' rimetterlo in volo.
                return
            # Monotona: un capitolo rifatto riparte da `chunks_done = 0`, e
            # la fase `verify` non porta un conteggio nuovo.
            parziali[ci] = max(parziali.get(ci, 0), fatti)
            fasi[ci] = str(riga.get("phase") or "")
            _scrivi_barra()
```

- [ ] **Step 4: Costruire la chiusura in `_uno`**

Dentro `_uno`, sostituire

```python
            stats = voxcpm_tts.synthesize_chapter(
                [plan[i]["text"] for i in indici], voice, dest,
                # Un job = un capitolo: la chiave e' univoca e permette di
                # risalire dal file su R2 al job che l'ha prodotto.
                key=f"voxcpm/{job_id}/ch{ci:06d}.pcm",
                cancelled=cancelled)
```

con

```python
            stats = voxcpm_tts.synthesize_chapter(
                [plan[i]["text"] for i in indici], voice, dest,
                # Un job = un capitolo: la chiave e' univoca e permette di
                # risalire dal file su R2 al job che l'ha prodotto.
                key=f"voxcpm/{job_id}/ch{ci:06d}.pcm",
                cancelled=cancelled,
                # Il payload del worker non porta l'indice di capitolo, e non
                # deve: il capitolo e' un concetto di ABM. La callback lo sa
                # perche' e' stata costruita per quello.
                on_progress=((lambda riga: _avanza(ci, len(indici), riga))
                             if job is not None and peso_barra else None))
```

- [ ] **Step 5: Scrivere la consegna sulle stesse strutture**

Sostituire il blocco che oggi muove la barra a capitolo consegnato

```python
            if job is not None and peso_barra:
                fatti_capitoli += 1
                fatti_chunk += len(indici)
                job["progress_current"] = 2 + peso_barra * fatti_chunk
                job["progress_message"] = (
                    f"Sintesi vocale: {fatti_capitoli} di {len(gruppi)} "
                    f"capitol{'o' if len(gruppi) == 1 else 'i'}")
```

con

```python
            if job is not None and peso_barra:
                with barra:
                    # Il 10% che i chunk non coprivano scatta adesso: il PCM
                    # e' davvero su disco.
                    consegnati[ci] = len(indici)
                    parziali.pop(ci, None)
                    fasi.pop(ci, None)
                    _scrivi_barra()
```

e cancellare le due variabili che non servono più, dove sono inizializzate prima del `for fut in _cf.as_completed(...)`:

```python
        fatti_capitoli = 0
        fatti_chunk = 0
```

- [ ] **Step 6: Eseguire i test e vederli passare**

Run: `python -m pytest test/test_voxcpm_generation.py -v`
Expected: PASS, tutti.

- [ ] **Step 7: Commit**

```bash
git add generation_engine.py test/test_voxcpm_generation.py
git commit -m "$(cat <<'MSG'
feat(voxcpm): la barra si muove coi chunk, non aspetta il capitolo

Il 90% del peso del capitolo va ai chunk che il worker chiude, il 10% alla
consegna. Due strutture sotto un lock, e numero e messaggio scritti insieme.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3
MSG
)"
```

---

## Task 7: I messaggi delle fasi lunghe, e il collaudo manuale

Il codice dei messaggi è già nel Task 6: qui si inchioda con i suoi test, e si scrive il collaudo che una persona deve poter rifare.

**Files:**
- Test: `test/test_voxcpm_generation.py`
- Modify: `docs/MANUAL_TESTS_VOXCPM.md`

**Interfaces:**
- Consumes: `_scrivi_barra()`, `_avanza()` e le tre strutture del Task 6; `JobSpiaFine` e `_con_copione` dello stesso task.

- [ ] **Step 1: Scrivere i test**

Aggiungere in `test/test_voxcpm_generation.py`:

```python
def test_finche_tutti_aspettano_il_motore_il_messaggio_lo_dice(tmp_path, monkeypatch):
    # Su worker freddo questa fase dura piu' di due minuti, ed e' proprio il
    # tratto in cui oggi l'utente non ha alcun segno di vita.
    _con_copione(monkeypatch, [
        {"phase": "warmup", "chunks_done": 0, "chunks_total": 2}])
    job = JobSpiaFine()
    generation_engine._voxcpm_pre_pass(
        PIANO, VOCE, "+0%", tmp_path, "job-1", set(), job=job,
        peso_barra=generation_engine._VOXCPM_PESO_BARRA)
    assert job.storia[0] == (2, "Sintesi vocale: 0 di 3 capitoli "
                                "(preparazione del motore vocale)")


def test_appena_uno_genera_il_messaggio_torna_alle_frasi(tmp_path, monkeypatch):
    _con_copione(monkeypatch, [
        {"phase": "warmup", "chunks_done": 0, "chunks_total": 2},
        {"phase": "generate", "chunks_done": 1, "chunks_total": 2}])
    job = JobSpiaFine()
    generation_engine._voxcpm_pre_pass(
        PIANO, VOCE, "+0%", tmp_path, "job-1", set(), job=job,
        peso_barra=generation_engine._VOXCPM_PESO_BARRA)
    messaggi = [m for _, m in job.storia]
    assert "preparazione del motore vocale" in messaggi[0]
    assert messaggi[1] == "Sintesi vocale: 0 di 3 capitoli (1 di 6 frasi)"


def test_quando_tutti_hanno_smesso_di_generare_il_messaggio_lo_dice(tmp_path, monkeypatch):
    # I chunk sono finiti ma il capitolo no: restano i giri di rigenerazione
    # delle code tagliate e l'upload. La barra non deve inchiodarsi su un
    # capitolo che sembra finito.
    _con_copione(monkeypatch, [
        {"phase": "generate", "chunks_done": 2, "chunks_total": 2},
        {"phase": "verify", "chunks_done": 2, "chunks_total": 2},
        {"phase": "deliver", "chunks_done": 2, "chunks_total": 2}])
    job = JobSpiaFine()
    generation_engine._voxcpm_pre_pass(
        [blocco("a", 0), blocco("b", 0)], VOCE, "+0%", tmp_path, "job-1",
        set(), job=job, peso_barra=generation_engine._VOXCPM_PESO_BARRA)
    messaggi = [m for _, m in job.storia]
    assert messaggi[0] == "Sintesi vocale: 0 di 1 capitolo (2 di 2 frasi)"
    assert messaggi[1] == "Sintesi vocale: 0 di 1 capitolo (rifinitura e consegna)"
    assert messaggi[2] == messaggi[1]
    # A capitolo consegnato nessuno e' piu' in volo: tornano le frasi.
    assert messaggi[-1] == "Sintesi vocale: 1 di 1 capitolo (2 di 2 frasi)"
```

- [ ] **Step 2: Eseguirli**

Run: `python -m pytest test/test_voxcpm_generation.py -k "motore or frasi or generare" -v`
Expected: PASS — il comportamento è quello scritto nel Task 6. Se uno fallisce, il difetto è in `_scrivi_barra` (candidati: l'ordine dei rami `warmup`/rifinitura, oppure `in_volo` calcolato su `parziali` invece che su `fasi`).

- [ ] **Step 3: Scrivere il collaudo manuale**

In `docs/MANUAL_TESTS_VOXCPM.md`, aggiungere prima della sezione «## 8. Cosa fare se qualcosa non torna»:

```markdown
## 7bis. La barra si muove mentre il libro si legge

Serve un libro da almeno tre capitoli e un endpoint senza worker caldi (la
prima generazione della giornata va benissimo: l'avvio del motore è proprio
quel che si vuole vedere dichiarato).

1. Avvia una generazione con una voce PREMIUM e resta sulla pagina.
2. **Nei primi due minuti** il messaggio deve dire «Sintesi vocale: 0 di N
   capitoli (preparazione del motore vocale)». È il caricamento del motore
   sulla GPU: prima di questo lavoro la barra qui restava muta.
3. Poi il messaggio passa al conteggio delle frasi — «Sintesi vocale: 0 di N
   capitoli (12 di 210 frasi)» — e il primo numero **cresce a scatti**, non
   con continuità: il worker chiude i chunk a ondate, e ogni ondata è uno
   scatto. Due o tre scatti per capitolo sono il comportamento atteso.
4. Il numero delle frasi **non deve mai arretrare**, nemmeno quando un
   capitolo viene rifatto.
5. Verso la fine di ogni capitolo il messaggio diventa «(rifinitura e
   consegna)»: sono i giri di rigenerazione delle code tagliate e l'upload.
6. A sintesi finita la barra deve stare al 90% come nelle generazioni
   precedenti: questo lavoro cambia il ritmo, non il punto d'arrivo.

Se la barra resta ferma per l'intera sintesi e il libro esce comunque
completo, il canale è muto ma innocuo: guarda `ABM_VOXCPM_PROGRESS`
nell'unit systemd (a `0` è spento apposta) e la versione dell'immagine sul
worker, che deve essere almeno quella del 2026-09-07.
```

- [ ] **Step 4: Commit**

```bash
git add test/test_voxcpm_generation.py docs/MANUAL_TESTS_VOXCPM.md
git commit -m "$(cat <<'MSG'
test(voxcpm): i messaggi delle fasi lunghe, piu' il collaudo da rifare a mano

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3
MSG
)"
```

---

## Task 8: Verifica d'insieme e consegna

**Files:**
- Nessuna modifica prevista. Se la suite scopre una regressione, si corregge nel file che la causa e si committa a parte.

**Interfaces:**
- Consumes: tutto quel che i Task 1-7 hanno prodotto.

- [ ] **Step 1: La suite VoxCPM per intero**

Run: `python -m pytest test/test_voxcpm_runpod.py test/test_voxcpm_generation.py test/test_voxcpm_catalog.py -q`
Expected: PASS.

- [ ] **Step 2: La suite di ABM, per le regressioni fuori perimetro**

Run: `python -m pytest test/ -q -x`
Expected: PASS. `_voxcpm_pre_pass` è chiamata anche da percorsi che non passano `job`: quel ramo non deve essersi mosso.

- [ ] **Step 3: Le prove del worker**

Run: `cd "C:/Users/gfran/NEXT srl/Progetti - Documenti/abm-voxcpm-worker" && python tools/test_progress.py && python tools/test_verifica.py && python tools/test_assemble.py`
Expected: tutte passate.

- [ ] **Step 4: Rileggere il diff dei due repository**

```bash
cd "C:/Users/gfran/NEXT srl/Progetti - Documenti/AudioBook-Maker/.worktrees/VOXCPM" && git log --oneline main..HEAD && git diff main --stat
cd "C:/Users/gfran/NEXT srl/Progetti - Documenti/abm-voxcpm-worker" && git log --oneline -4 && git status --short
```

Da controllare: nel worker sono committati soltanto `handler.py` e `tools/test_progress.py`, e i nove file di altri lavori sotto `data/voci_inventate/` e `tools/voice_design/` sono ancora lì, non tracciati o modificati ma **non committati**.

- [ ] **Step 5: Consegnare all'utente, senza pushare**

Riferire: che cosa è stato fatto nei due repository, il numero dei test, e la sequenza di deploy da autorizzare — che l'utente esegue quando vuole, nell'ordine che preferisce (le due direzioni dello sfasamento degradano entrambe al comportamento di oggi):

1. `git push` del repo `abm-voxcpm-worker` (**su conferma esplicita**) → GitHub Actions costruisce `ghcr.io/gfrangiamone/abm-voxcpm:latest` più l'alias con lo sha, ~7 minuti.
2. Nuova release su RunPod puntata al **tag esplicito con lo sha**, non a `latest` — e **solo con `inProgress = 0`**, perché la release termina i worker che stanno macinando job pagati.
3. `git push` del branch `VOXCPM` (**su conferma esplicita**) → il deploy di ABM è automatico.
4. Il collaudo manuale §7bis su un libro vero, a worker freddo.

Nessuno di questi passi si esegue senza che l'utente lo chieda nel turno corrente.

---

## Note di autoverifica

**Copertura della spec.** §4.2 (forma del payload) → Task 1-2. §5 (worker: pubblicatore, tre regole, thread, punti di chiamata) → Task 1-3. §6 (client) → Task 4-5. §7.1-7.2 (peso e strutture) → Task 6. §7.3 (messaggio) → Task 6-7. §7.4 (`peso_barra = 0`) → Task 6, coperto dal test esistente `test_senza_peso_la_barra_resta_ferma`. §8: test 1-4 → Task 4; 5-7, 11-12 → Task 6; 8 e 8bis → Task 7; 9-10 → test esistenti aggiornati nel Task 6; 13 e 13bis → Task 1-2; 14-17 → Task 1 e 3; collaudo manuale → Task 7. §9 (compatibilità e interruttori) → Global Constraints e Task 5. §10 (file toccati) → File Structure, invariata.

**Fuori perimetro, come da spec §10:** `static/js/app.js` e il payload SSE di `audiobook_app.py` non si toccano — la catena a valle di `progress_current`/`progress_total`/`progress_message` funziona già, e questo lavoro le cambia solo il ritmo.
