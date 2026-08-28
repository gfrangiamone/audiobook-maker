# VoxCPM2 come quarto motore TTS — Piano di implementazione (1 di 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere selezionabile nel tab Voci PREMIUM un quarto motore, VoxCPM2, che legge un libro intero con una voce del catalogo di voci inventate, servito dal worker RunPod serverless.

**Architecture:** Due moduli nuovi con responsabilità disgiunte — `voxcpm_catalog.py` legge `data/voci_inventate/voices.json` e non sa cosa sia RunPod; `voxcpm_tts.py` parla con RunPod e non sa cosa sia un file di catalogo. Il motore si innesta nella catena esistente esattamente dove si innesta Speechify: un pre-pass che riempie un dizionario di risultati per chunk, letto poi dall'assemblaggio sequenziale già in produzione. Nessun formato di uscita, nessuna coda di assemblaggio e nessun percorso di pagamento vengono riscritti.

**Tech Stack:** Python 3, Flask, `requests`, `pytest`. Nessuna dipendenza nuova: il ponte verso RunPod è HTTP JSON con `requests`, già in `requirements.txt`.

**Spec:** `docs/superpowers/specs/2026-08-28-voxcpm-integrazione-design.md`

**Perimetro di questo piano:** il catalogo di voci inventate, dalla selezione
nel wizard all'M4B finito, con il prezzo corretto. **Fuori:** tutto il
sottosistema «La mia voce» (§6 della spec) — consenso, frase guidata,
registrazione, gate di qualità, storage del campione, email di recupero e
cancellazione. Quello è il piano 2, e dipende da questo: riusa
`voxcpm_tts.synthesize_chapter` senza modificarla, aggiungendo solo una
seconda sorgente di campione accanto al catalogo.

Restano fuori da entrambi i piani, per D1 e §4 della spec: qualunque
modifica al repo `abm-voxcpm-worker`, l'azione `assemble` del worker, e le
50 voci reali eliminate dal progetto.

## Global Constraints

Valori copiati dalla spec. Valgono per ogni task senza essere ripetuti.

- **Il catalogo è una variabile indipendente (D10, §12.1).** Nessun elenco di
  voci, lingue, accenti o caratteri può comparire in una costante Python, in
  una stringa di traduzione o in un test. Tutto si ricava leggendo
  `voices.json` a runtime. I test usano una fixture, **mai** il catalogo reale.
- **Un carattere sconosciuto non è un errore.** Il dizionario di traduzione dei
  caratteri ricade su `description.role`, poi su `description.axes`, poi sulla
  chiave tecnica stessa. Un carattere nuovo nel catalogo non deve richiedere un
  rilascio.
- **Una voce priva di `description.persona` si scarta al caricamento** con una
  riga di log, non si mostra senza carattere.
- **Modalità di cloning: `hifi`, sempre** (§7.4). Richiede `prompt_wav` **e**
  `prompt_text`. Il canale che porta l'identità è `prompt_wav`, non
  `reference_wav`: misurato il 2026-08-28 (§15.1). Un campione senza la sua
  trascrizione esatta non è utilizzabile.
- **Unità di lavoro: un job RunPod per capitolo** (§7.3).
- **Non si usa `/runsync`** (§7.1): risponde 200 senza `output` quando il job
  supera il tempo della richiesta. Si usa `/run` più polling su `/status`.
- **Il worker sintetizza, l'app assembla** (D9, §7.2). L'audio dei chunk torna
  all'app e prosegue nella catena esistente: `assembly_queue.py`,
  `chunk_reuse.py`, copertina, capitoli, i quattro formati di uscita.
- **Il retry costa un boot, non caratteri** (§9.2): si ritenta dentro lo stesso
  job finché il worker è caldo; il retry a freddo è l'ultima risorsa.
- **Ordine di prezzo invariante** (§8.1): listino sopra soglia → si paga e la
  quota non entra; altrimenti quota mensile; se la quota non copre, dovuto =
  `max(listino, floor)`. **Il floor si applica al residuo, mai al lordo.**
- **Formato degli identificatori** (§12.2): `voxcpm:v2:<locale>/<Nome>`, per
  esempio `voxcpm:v2:it-IT/Stefano`. Il piano 2 aggiungerà
  `voxcpm:mine:<token>`, che questo piano non implementa ma non deve rendere
  impossibile.
- **Endpoint non configurato = motore invisibile** (§9.4): `is_available()`
  falso e VoxCPM non compare fra i modelli, come già fa Gemini.
- **Convenzioni del repo:** ambiente Windows PowerShell; non concatenare
  comandi con `&&`. Il `.gitignore` alla riga 6 è `*.md`, quindi ogni file
  markdown si committa con `git add -f`. Ogni variabile d'ambiente nuova va
  riportata in `md_files/PARAMETRI_CONFIGURAZIONE.md` nello stesso commit che
  la introduce.
- **Baseline della suite** (§14), da `ac1ba45`: **1964 passati, 16 saltati**,
  nessun fallimento, ~180 s. Si lancia con `python -m pytest test/ -q` dalla
  radice del worktree (l'opzione `--timeout` non è disponibile: `pytest-timeout`
  non è installato). Ogni fallimento nuovo è imputabile a questo lavoro.

---

## Struttura dei file

**Nuovi:**

| File | Responsabilità |
|---|---|
| `voxcpm_catalog.py` | Legge `voices.json`, scarta le voci non valide, indicizza per lingua e carattere, risolve un id in campione + trascrizione. Nessuna rete. |
| `voxcpm_tts.py` | Listino e stima costo, disponibilità, sottomissione job a RunPod, polling, tassonomia degli errori, sintesi di un capitolo. Nessuna lettura di file di catalogo. |
| `test/fixtures/voxcpm_catalog/voices.json` | Catalogo finto, sei voci, due lingue, tre caratteri. La suite non tocca mai il catalogo reale. |
| `test/fixtures/voxcpm_catalog/it-IT/Stefano.wav` | Campione finto (44 byte di header WAV). Serve solo a far esistere il percorso. |
| `test/test_voxcpm_catalog.py` | Caricamento, scarto, indice, risoluzione. |
| `test/test_voxcpm_tts.py` | Listino, disponibilità, client RunPod col doppio. |
| `test/test_voxcpm_quota.py` | Ordine quota → soglia → floor per le voci VoxCPM. |
| `test/test_voxcpm_api.py` | `/api/voices` e `/api/voice_sample`. |
| `test/test_voxcpm_generation.py` | Il pre-pass per capitolo dentro `generation_engine`. |
| `test/test_voxcpm_pricing_api.py` | Stima, ordine PayPal, guardie di `/api/generate` e `/api/preview`. |
| `test/test_voxcpm_audit.py` | Il record di costo reale, job per job. |
| `test/test_voxcpm_frontend_assets.py` | Markup e funzioni del pannello, ad asserzioni statiche. |
| `test/test_voxcpm_i18n.py` | Le etichette nelle sei lingue. |
| `docs/MANUAL_TESTS_VOXCPM.md` | Il collaudo su GPU vera, da eseguire prima del rilascio. |

**Modificati:**

| File | Modifica |
|---|---|
| `voice_utils.py` | `VOXCPM_VOICE_PREFIX` e `is_voxcpm_voice`. Modulo foglia: resta senza import di progetto. |
| `free_quota.py` | Ramo VoxCPM in `_premium_threshold_eur`; nuovo `_premium_floor_eur` usato da `decision()`. |
| `audiobook_app.py` | `_fetch_voices()` fonde le voci VoxCPM; nuova rotta `/api/voice_sample`. |
| `generation_engine.py` | `_engine_for_voice` riconosce VoxCPM; pre-pass per capitolo; `_friendly_voice_name`. |
| `static/js/app.js` | VoxCPM nel selettore modello, CARATTERE come filtro, player del campione. |
| `templates/_fragments/i18n_data.js` | Etichette dei caratteri e del pannello nelle sei lingue, con ricadute. |
| `templates/_fragments/html_head.html` | La riga CARATTERE e il player del campione nel tab premium. |
| `md_files/PARAMETRI_CONFIGURAZIONE.md` | Le variabili nuove, man mano che nascono. |

---
### Task 1: Il predicato di voce VoxCPM

`voice_utils.py` è il modulo foglia dove vivono le definizioni uniche dei
prefissi voce. Ogni altro modulo importa da qui invece di ripetere lo
`startswith`. Questo task aggiunge il terzo prefisso premium.

**Files:**
- Modify: `voice_utils.py` (in coda, dopo `is_speechify_voice`)
- Test: `test/test_voice_utils_voxcpm.py`

**Interfaces:**
- Consumes: niente (primo task).
- Produces: `voice_utils.VOXCPM_VOICE_PREFIX` (str, `"voxcpm:"`) e
  `voice_utils.is_voxcpm_voice(voice) -> bool`. Usati da `free_quota.py`
  (Task 5), `generation_engine.py` (Task 9) e `audiobook_app.py` (Task 8).

- [ ] **Step 1: Scrivi il test che fallisce**

Crea `test/test_voice_utils_voxcpm.py`:

```python
"""Predicato di voce PREMIUM VoxCPM.

`voice_utils` e' modulo foglia: nessun import di progetto. Il predicato deve
essere safe su input non-stringa come i due gemelli Gemini/Speechify, perche'
lo chiamano percorsi che ricevono il voice id grezzo dal client.
"""
import voice_utils


def test_prefix_value():
    assert voice_utils.VOXCPM_VOICE_PREFIX == "voxcpm:"


def test_catalog_voice_is_voxcpm():
    assert voice_utils.is_voxcpm_voice("voxcpm:v2:it-IT/Stefano") is True


def test_cloned_voice_is_voxcpm():
    # Formato del piano 2: deve gia' essere riconosciuto dal predicato.
    assert voice_utils.is_voxcpm_voice("voxcpm:mine:abc123") is True


def test_other_engines_are_not_voxcpm():
    assert voice_utils.is_voxcpm_voice("gemini:flash25:Zephyr") is False
    assert voice_utils.is_voxcpm_voice("speechify:simba-3.2:harper_32") is False
    assert voice_utils.is_voxcpm_voice("it-IT-IsabellaNeural") is False


def test_safe_on_junk():
    assert voice_utils.is_voxcpm_voice(None) is False
    assert voice_utils.is_voxcpm_voice("") is False
    assert voice_utils.is_voxcpm_voice(42) is False
    assert voice_utils.is_voxcpm_voice(["voxcpm:v2:it-IT/Stefano"]) is False
```

- [ ] **Step 2: Lancia il test e verifica che fallisca**

```
python -m pytest test/test_voice_utils_voxcpm.py -q
```

Atteso: FAIL — `AttributeError: module 'voice_utils' has no attribute 'VOXCPM_VOICE_PREFIX'`.

- [ ] **Step 3: Implementa**

In coda a `voice_utils.py`:

```python
VOXCPM_VOICE_PREFIX = "voxcpm:"


def is_voxcpm_voice(voice):
    """True se la voce e' una voce PREMIUM VoxCPM.

    Due formati sotto lo stesso prefisso: `voxcpm:v2:<locale>/<Nome>` per il
    catalogo di voci inventate, `voxcpm:mine:<token>` per la voce clonata
    dell'utente. Il predicato copre entrambi: la distinzione fra i due la fa
    `voxcpm_catalog.parse_voice_id`, non questo modulo.

    Safe su input non-stringa/None/"": ritorna False senza sollevare.
    """
    return bool(voice) and isinstance(voice, str) and voice.startswith(VOXCPM_VOICE_PREFIX)
```

- [ ] **Step 4: Lancia il test e verifica che passi**

```
python -m pytest test/test_voice_utils_voxcpm.py -q
```

Atteso: PASS, 5 test.

- [ ] **Step 5: Commit**

```
git add voice_utils.py test/test_voice_utils_voxcpm.py
git commit -m "feat(voxcpm): il prefisso della quarta voce, accanto agli altri tre"
```

---

### Task 2: Leggere il catalogo, e scartare quello che non si può mostrare

Il cuore di D10. Questo task porta in vita `voxcpm_catalog.py` limitatamente
alla lettura: apre `voices.json`, normalizza ogni voce in un record piatto,
scarta chi non ha `description.persona` e mette il risultato in cache. Non
espone ancora nulla alla UI — quello è il Task 3.

**Files:**
- Create: `voxcpm_catalog.py`
- Create: `test/fixtures/voxcpm_catalog/voices.json`
- Create: `test/fixtures/voxcpm_catalog/it-IT/Stefano.wav`
- Test: `test/test_voxcpm_catalog.py`

**Interfaces:**
- Consumes: niente.
- Produces:
  - `voxcpm_catalog.catalog_dir() -> str` — percorso assoluto della cartella,
    da `ABM_VOXCPM_CATALOG_DIR` (default `data/voci_inventate` accanto al
    modulo).
  - `voxcpm_catalog.voices() -> list[dict]` — i record validi, in cache.
    Ogni record: `{"id", "name", "locale", "lang", "gender", "persona",
    "role", "axes", "sample_rel", "transcript", "duration_s"}` con `gender` in
    `("Female", "Male")` e `id` nel formato `voxcpm:v2:<locale>/<Nome>`.
  - `voxcpm_catalog.invalidate_cache() -> None`.
  - `voxcpm_catalog.personas() -> list[str]` — chiavi tecniche presenti,
    ordinate alfabeticamente.
  - `voxcpm_catalog.CATALOG_SCHEMA` (str, `"v2"`).
  - Usati dal Task 3 (indice UI), dal Task 8 (`/api/voices`) e dal Task 12
    (filtro carattere).

- [ ] **Step 1: Crea la fixture del catalogo**

Il catalogo reale ha 361 voci e cambia da sé: la suite non lo tocca mai
(§12.1). Questa fixture ne riproduce la **forma**, non il contenuto — sette
voci, due lingue, tre varianti, quattro caratteri, e una voce deliberatamente
priva di `persona` che deve essere scartata.

Crea `test/fixtures/voxcpm_catalog/voices.json`:

```json
{
  "schema": "abm-voices/1",
  "catalog": "voci_inventate",
  "voice_count": 7,
  "languages": [
    {"code": "it", "label": "italiano", "voices": 4, "locales": ["it-IT"]},
    {"code": "en", "label": "inglese", "voices": 3, "locales": ["en-US", "en-GB"]}
  ],
  "voices": [
    {
      "id": "it-IT_m_stefano", "name": "Stefano", "name_is_invented": true,
      "language": {"code": "it", "locale": "it-IT", "label": "italiano"},
      "gender": {"value": "m", "label": "maschile", "f0_median_hz": 118.4},
      "audio": {"file": "it-IT/Stefano.wav", "transcript": "Quando il treno delle sette e quarantacinque arrivo con dodici minuti di ritardo, tirai fuori il telefono per controllare la posta.", "duration_s": 19.52, "sample_rate_hz": 24000},
      "quality": {"score": 0.88, "gate_passed": true},
      "description": {"persona": "warm-young", "role": "caldo, giovane", "axes": ["giovane", "tono medio"], "lang": "it"}
    },
    {
      "id": "it-IT_f_federica", "name": "Federica", "name_is_invented": true,
      "language": {"code": "it", "locale": "it-IT", "label": "italiano"},
      "gender": {"value": "f", "label": "femminile", "f0_median_hz": 201.7},
      "audio": {"file": "it-IT/Federica.wav", "transcript": "Quando il treno delle sette e quarantacinque arrivo con dodici minuti di ritardo, tirai fuori il telefono per controllare la posta.", "duration_s": 21.03, "sample_rate_hz": 24000},
      "quality": {"score": 0.91, "gate_passed": true},
      "description": {"persona": "audiobook-slow", "role": "narrativo, lento", "axes": ["ritmo lento"], "lang": "it"}
    },
    {
      "id": "it-IT_f_chiara", "name": "Chiara", "name_is_invented": true,
      "language": {"code": "it", "locale": "it-IT", "label": "italiano"},
      "gender": {"value": "f", "label": "femminile", "f0_median_hz": 214.9},
      "audio": {"file": "it-IT/Chiara.wav", "transcript": "Quando il treno delle sette e quarantacinque arrivo con dodici minuti di ritardo, tirai fuori il telefono per controllare la posta.", "duration_s": 20.11, "sample_rate_hz": 24000},
      "quality": {"score": 0.86, "gate_passed": true},
      "description": {"persona": "poised-dry", "role": "posato, asciutto", "axes": ["registro sobrio"], "lang": "it"}
    },
    {
      "id": "it-IT_m_senzacarattere", "name": "Senzacarattere", "name_is_invented": true,
      "language": {"code": "it", "locale": "it-IT", "label": "italiano"},
      "gender": {"value": "m", "label": "maschile", "f0_median_hz": 130.0},
      "audio": {"file": "it-IT/Senzacarattere.wav", "transcript": "Quando il treno delle sette e quarantacinque arrivo con dodici minuti di ritardo, tirai fuori il telefono per controllare la posta.", "duration_s": 20.0, "sample_rate_hz": 24000},
      "quality": {"score": 0.80, "gate_passed": true},
      "description": {"role": "senza persona", "axes": [], "lang": "it"}
    },
    {
      "id": "en-US_m_nolan", "name": "Nolan", "name_is_invented": true,
      "language": {"code": "en", "locale": "en-US", "label": "inglese"},
      "gender": {"value": "m", "label": "maschile", "f0_median_hz": 112.2},
      "audio": {"file": "en-US/Nolan.wav", "transcript": "When the seven forty-five train pulled in twelve minutes late, I took out my phone to check the mail.", "duration_s": 18.74, "sample_rate_hz": 24000},
      "quality": {"score": 0.89, "gate_passed": true},
      "description": {"persona": "warm-young", "role": "warm, young", "axes": ["young"], "lang": "en"}
    },
    {
      "id": "en-US_f_ivy", "name": "Ivy", "name_is_invented": true,
      "language": {"code": "en", "locale": "en-US", "label": "inglese"},
      "gender": {"value": "f", "label": "femminile", "f0_median_hz": 198.3},
      "audio": {"file": "en-US/Ivy.wav", "transcript": "When the seven forty-five train pulled in twelve minutes late, I took out my phone to check the mail.", "duration_s": 19.90, "sample_rate_hz": 24000},
      "quality": {"score": 0.87, "gate_passed": true},
      "description": {"persona": "poised-dry", "role": "poised, dry", "axes": ["measured"], "lang": "en"}
    },
    {
      "id": "en-GB_m_rufus", "name": "Rufus", "name_is_invented": true,
      "language": {"code": "en", "locale": "en-GB", "label": "inglese"},
      "gender": {"value": "m", "label": "maschile", "f0_median_hz": 104.6},
      "audio": {"file": "en-GB/Rufus.wav", "transcript": "When the seven forty-five train pulled in twelve minutes late, I took out my phone to check the mail.", "duration_s": 22.40, "sample_rate_hz": 24000},
      "quality": {"score": 0.90, "gate_passed": true},
      "description": {"persona": "grave-narrator", "role": "grave, narrator", "axes": ["deep"], "lang": "en"}
    }
  ]
}
```

Crea anche un `.wav` minimo, che serve solo a far esistere un percorso
verificabile nel Task 3 (44 byte: il solo header RIFF, zero campioni):

```
python -c "import pathlib,struct; p=pathlib.Path('test/fixtures/voxcpm_catalog/it-IT'); p.mkdir(parents=True, exist_ok=True); h=b'RIFF'+struct.pack('<I',36)+b'WAVEfmt '+struct.pack('<IHHIIHH',16,1,1,24000,48000,2,16)+b'data'+struct.pack('<I',0); (p/'Stefano.wav').write_bytes(h)"
```

- [ ] **Step 2: Scrivi il test che fallisce**

Crea `test/test_voxcpm_catalog.py`:

```python
"""Lettura del catalogo di voci inventate VoxCPM.

Il catalogo reale (`data/voci_inventate/voices.json`, 361 voci al 2026-08-28)
e' una variabile indipendente: viene rigenerato mentre l'app evolve. Per D10 e
la §12.1 della spec questa suite non lo apre mai — legge una fixture con la
stessa forma e contenuto stabile.
"""
import os

import pytest

import voxcpm_catalog

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")


@pytest.fixture(autouse=True)
def catalogo_di_prova(monkeypatch):
    """Punta il modulo alla fixture e svuota la cache prima e dopo ogni test."""
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    yield
    voxcpm_catalog.invalidate_cache()


def test_catalog_dir_segue_la_variabile():
    assert voxcpm_catalog.catalog_dir() == os.path.abspath(FIXTURE)


def test_carica_solo_le_voci_con_persona():
    # Sette nel file, sei valide: "Senzacarattere" non ha description.persona.
    voci = voxcpm_catalog.voices()
    assert len(voci) == 6
    assert "Senzacarattere" not in [v["name"] for v in voci]


def test_scarto_loggato(capsys):
    voxcpm_catalog.voices()
    out = capsys.readouterr().out
    # Lo scarto e' silenzioso per l'utente, non per chi legge i log.
    assert "it-IT_m_senzacarattere" in out
    assert "persona" in out


def test_record_normalizzato():
    stefano = next(v for v in voxcpm_catalog.voices() if v["name"] == "Stefano")
    assert stefano["id"] == "voxcpm:v2:it-IT/Stefano"
    assert stefano["locale"] == "it-IT"
    assert stefano["lang"] == "it"
    assert stefano["gender"] == "Male"
    assert stefano["persona"] == "warm-young"
    assert stefano["role"] == "caldo, giovane"
    assert stefano["sample_rel"] == "it-IT/Stefano.wav"
    assert stefano["transcript"].startswith("Quando il treno")
    assert stefano["duration_s"] == 19.52


def test_genere_femminile_mappato():
    federica = next(v for v in voxcpm_catalog.voices() if v["name"] == "Federica")
    assert federica["gender"] == "Female"


def test_personas_sono_quelle_del_file():
    # Nessun elenco cablato: e' quello che la fixture contiene, ordinato.
    assert voxcpm_catalog.personas() == [
        "audiobook-slow", "grave-narrator", "poised-dry", "warm-young",
    ]


def test_cache_non_rilegge_il_file(monkeypatch):
    voxcpm_catalog.voices()
    # Sposta la variabile su una cartella inesistente: senza cache si svuoterebbe.
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", os.path.join(FIXTURE, "nonesiste"))
    assert len(voxcpm_catalog.voices()) == 6


def test_catalogo_assente_non_solleva(monkeypatch, capsys):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", os.path.join(FIXTURE, "nonesiste"))
    voxcpm_catalog.invalidate_cache()
    # Catalogo non installato: il motore sparisce, l'app non si rompe (§9.4).
    assert voxcpm_catalog.voices() == []
    assert "voices.json" in capsys.readouterr().out


def test_json_malformato_non_solleva(tmp_path, monkeypatch, capsys):
    (tmp_path / "voices.json").write_text("{ non e' json", encoding="utf-8")
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", str(tmp_path))
    voxcpm_catalog.invalidate_cache()
    assert voxcpm_catalog.voices() == []
    assert "voices.json" in capsys.readouterr().out
```

- [ ] **Step 3: Lancia il test e verifica che fallisca**

```
python -m pytest test/test_voxcpm_catalog.py -q
```

Atteso: FAIL alla raccolta — `ModuleNotFoundError: No module named 'voxcpm_catalog'`.

- [ ] **Step 4: Implementa il caricamento**

Crea `voxcpm_catalog.py`:

```python
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
    out = []
    for raw in (data.get("voices") or []):
        rec = _normalize(raw)
        if rec is not None:
            out.append(rec)
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
```

- [ ] **Step 5: Lancia il test e verifica che passi**

```
python -m pytest test/test_voxcpm_catalog.py -q
```

Atteso: PASS, 9 test.

- [ ] **Step 6: Documenta la variabile**

In `md_files/PARAMETRI_CONFIGURAZIONE.md`, nella sezione delle voci PREMIUM,
aggiungi la riga:

```
| `ABM_VOXCPM_CATALOG_DIR` | `data/voci_inventate` | Cartella del catalogo di voci inventate VoxCPM (`voices.json` piu' i `.wav` dei campioni). E' un dato importato dal repo `abm-voxcpm-worker`: aggiornarlo significa sostituire la cartella, non toccare il codice. |
```

- [ ] **Step 7: Commit**

```
git add voxcpm_catalog.py test/test_voxcpm_catalog.py test/fixtures/voxcpm_catalog
git add -f md_files/PARAMETRI_CONFIGURAZIONE.md
git commit -m "feat(voxcpm): il catalogo si legge, e chi non ha carattere resta fuori"
```

---
### Task 3: Dal catalogo all'indice che la UI consuma

Il Task 2 ha prodotto record grezzi. Questo li trasforma in ciò che
`/api/voices` si aspetta — la stessa forma di entry che `speechify_tts.get_voices()`
restituisce, così `_fetch_voices()` potrà fonderli senza casi speciali — e
aggiunge le due funzioni inverse: da id a record, da id a percorso del
campione sul disco.

**Files:**
- Modify: `voxcpm_catalog.py` (in coda)
- Test: `test/test_voxcpm_catalog.py` (in coda)

**Interfaces:**
- Consumes: dal Task 2 — `voices()`, `catalog_dir()`, `CATALOG_SCHEMA`,
  `_ID_PREFIX`, e i campi del record normalizzato.
- Produces:
  - `voxcpm_catalog.MODEL_ID` (str, `"v2"`) e `voxcpm_catalog.MODEL_LABEL`
    (str, `"VoxCPM2"`).
  - `voxcpm_catalog.get_voices() -> dict[str, list[dict]]` — chiave = codice
    lingua a due lettere, valore = lista di entry UI. Ogni entry:
    `{"id", "name", "locale", "engine": "voxcpm", "model_key", "model_label",
    "gender", "gender_icon", "persona", "persona_role", "sample_url"}`.
  - `voxcpm_catalog.parse_voice_id(voice_id) -> dict` — il record normalizzato.
    Solleva `ValueError` su prefisso sbagliato, schema sconosciuto o voce
    assente dal catalogo.
  - `voxcpm_catalog.sample_path(voice_id) -> str` — percorso assoluto del
    `.wav`. Solleva `ValueError` come sopra; solleva `FileNotFoundError` se il
    record c'è ma il file no.
  - Usati dal Task 7 (`prompt_wav` e `prompt_text` del payload), dal Task 8
    (`/api/voices`, `/api/voice_sample`) e dal Task 9 (nome amichevole).

Nota sul `MODEL_LABEL`: qui è `"VoxCPM2"` e basta. La spec (§5.2) prevede a
regime `VoxCPM2 · La tua voce`, ma quel suffisso promette la clonazione, che
in questo piano non esiste ancora: lo aggiunge il piano 2, insieme alla cosa
che nomina.

- [ ] **Step 1: Scrivi i test che falliscono**

In coda a `test/test_voxcpm_catalog.py` (la fixture `catalogo_di_prova` è
`autouse`, vale anche qui):

```python
def test_get_voices_raggruppa_per_lingua():
    d = voxcpm_catalog.get_voices()
    assert sorted(d.keys()) == ["en", "it"]
    assert len(d["it"]) == 3   # Stefano, Federica, Chiara
    assert len(d["en"]) == 3   # Nolan, Ivy (en-US), Rufus (en-GB)


def test_entry_ha_la_forma_delle_altre_premium():
    ivy = next(v for v in voxcpm_catalog.get_voices()["en"] if v["name"].startswith("Ivy"))
    assert ivy["id"] == "voxcpm:v2:en-US/Ivy"
    assert ivy["engine"] == "voxcpm"
    assert ivy["model_key"] == "v2"
    assert ivy["model_label"] == "VoxCPM2"
    assert ivy["locale"] == "en-US"
    assert ivy["gender"] == "Female"
    assert ivy["gender_icon"] == "\U0001f469"
    assert ivy["persona"] == "poised-dry"
    assert ivy["persona_role"] == "poised, dry"


def test_nome_porta_la_regione():
    # Dentro la stessa lingua due varianti convivono: senza la regione nel nome
    # l'utente che non filtra per accento non sa cosa sta scegliendo.
    nomi = sorted(v["name"] for v in voxcpm_catalog.get_voices()["en"])
    assert nomi == ["Ivy (US)", "Nolan (US)", "Rufus (GB)"]


def test_sample_url_punta_alla_rotta():
    stefano = next(v for v in voxcpm_catalog.get_voices()["it"] if v["name"].startswith("Stefano"))
    assert stefano["sample_url"] == "/api/voice_sample?voice=voxcpm%3Av2%3Ait-IT%2FStefano"


def test_parse_voice_id_ritorna_il_record():
    rec = voxcpm_catalog.parse_voice_id("voxcpm:v2:it-IT/Stefano")
    assert rec["name"] == "Stefano"
    assert rec["transcript"].startswith("Quando il treno")


def test_parse_voice_id_rifiuta_input_estranei():
    for cattivo in (None, "", 7, "gemini:flash25:Zephyr", "voxcpm:v2", "voxcpm:v9:it-IT/Stefano"):
        with pytest.raises(ValueError):
            voxcpm_catalog.parse_voice_id(cattivo)


def test_parse_voice_id_voce_sparita_dal_catalogo():
    # Caso normale, non errore di programmazione (§9.4): un job vecchio cita
    # una voce che una rigenerazione del catalogo ha rimosso.
    with pytest.raises(ValueError) as e:
        voxcpm_catalog.parse_voice_id("voxcpm:v2:it-IT/Fantasma")
    assert "Fantasma" in str(e.value)


def test_parse_voce_clonata_non_e_di_catalogo():
    # `voxcpm:mine:<token>` e' del piano 2: questo modulo la riconosce come
    # non sua e lo dice, invece di cercarla fra le voci inventate.
    with pytest.raises(ValueError) as e:
        voxcpm_catalog.parse_voice_id("voxcpm:mine:abc123")
    assert "mine" in str(e.value)


def test_sample_path_esiste():
    p = voxcpm_catalog.sample_path("voxcpm:v2:it-IT/Stefano")
    assert p == os.path.join(FIXTURE, "it-IT", "Stefano.wav")
    assert os.path.exists(p)


def test_sample_path_file_mancante():
    # Federica e' nel JSON ma il suo .wav non e' nella fixture.
    with pytest.raises(FileNotFoundError):
        voxcpm_catalog.sample_path("voxcpm:v2:it-IT/Federica")


def test_sample_path_non_evade_dalla_cartella(tmp_path, monkeypatch):
    # `audio.file` arriva da un file di dati: un percorso con .. non deve
    # poter servire file fuori dal catalogo.
    import json as _json
    cattivo = {
        "voices": [{
            "id": "x_m_evasione", "name": "Evasione",
            "language": {"code": "it", "locale": "it-IT"},
            "gender": {"value": "m"},
            "audio": {"file": "../../../etc/passwd", "transcript": "testo", "duration_s": 1.0},
            "description": {"persona": "warm-young"},
        }]
    }
    (tmp_path / "voices.json").write_text(_json.dumps(cattivo), encoding="utf-8")
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", str(tmp_path))
    voxcpm_catalog.invalidate_cache()
    with pytest.raises(ValueError):
        voxcpm_catalog.sample_path("voxcpm:v2:it-IT/Evasione")
```

- [ ] **Step 2: Lancia i test e verifica che falliscano**

```
python -m pytest test/test_voxcpm_catalog.py -q
```

Atteso: FAIL, 11 nuovi test —
`AttributeError: module 'voxcpm_catalog' has no attribute 'get_voices'`.

- [ ] **Step 3: Implementa l'indice e le due inverse**

In coda a `voxcpm_catalog.py`:

```python
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
```

- [ ] **Step 4: Lancia i test e verifica che passino**

```
python -m pytest test/test_voxcpm_catalog.py -q
```

Atteso: PASS, 20 test.

- [ ] **Step 5: Commit**

```
git add voxcpm_catalog.py test/test_voxcpm_catalog.py
git commit -m "feat(voxcpm): il catalogo diventa un indice, e ogni voce sa dov'e' il suo campione"
```

---
### Task 4: Disponibilità e listino del motore

Nasce `voxcpm_tts.py`, per ora senza rete: le variabili d'ambiente, il
predicato di disponibilità che decide se il motore compare nel wizard, e il
prezzo di listino. Il ponte HTTP arriva col Task 6.

Due scelte da tenere presenti mentre si implementa:

1. **Il listino è una tariffa diretta €/Mchar** (D4, §8.2), non la catena
   `costo USD → margine → fee PayPal` di Gemini e Speechify. Per quei due
   motori il costo provider è una fattura che arriva; qui il costo è tempo di
   GPU misurato (§8.3: ~$0,91 per milione di caratteri su RTX 4090), e la
   tariffa all'utente è una decisione commerciale indipendente. Il costo
   misurato resta nel modulo, ma serve solo all'audit del margine (Task 10).

2. **Senza tariffa configurata il motore non esiste.** `§15.3` lascia il
   valore di listino da fissare prima del deploy. Un default inventato
   significherebbe generare libri a un prezzo che nessuno ha deciso: meglio
   che `is_available()` sia falso, esattamente come quando manca l'endpoint.

**Files:**
- Create: `voxcpm_tts.py`
- Test: `test/test_voxcpm_tts.py`

**Interfaces:**
- Consumes: dal Task 2/3 — `voxcpm_catalog.voices()`.
- Produces:
  - `voxcpm_tts.MODEL_ID` / `MODEL_LABEL` (rimandati a `voxcpm_catalog`).
  - `voxcpm_tts.endpoint_id() -> str`, `api_key() -> str`.
  - `voxcpm_tts.is_available() -> bool`.
  - `voxcpm_tts.concurrency() -> int` — chunk in volo per job, default 32.
  - `voxcpm_tts.rate_eur_per_mchar() -> float`, `cost_usd_per_mchar() -> float`.
  - `voxcpm_tts.compute_user_price_eur(chars) -> dict` con le chiavi
    `{"chars", "list_price_eur", "user_price_eur", "is_free",
    "free_threshold_eur", "cost_usd"}` — stesse chiavi che
    `speechify_tts.compute_user_price_eur` espone ai chiamanti.
  - `voxcpm_tts.estimate_book_cost(chapters, language="it") -> dict`.
  - Usati dal Task 8 (`/api/voices`), dal Task 10 (stima), dal Task 11
    (audit) e dal Task 12 (UI).

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_voxcpm_tts.py`:

```python
"""Configurazione, disponibilita' e listino del motore VoxCPM.

Nessuna rete: il ponte verso RunPod si prova col doppio in
test_voxcpm_tts_runpod.py.
"""
import os

import pytest

import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")


@pytest.fixture
def configurato(monkeypatch):
    """Motore pienamente configurato: endpoint, chiave, catalogo, tariffa."""
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "abc123endpoint")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "rp-chiave-finta")
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "4.00")
    voxcpm_catalog.invalidate_cache()
    yield
    voxcpm_catalog.invalidate_cache()


def test_disponibile_quando_tutto_c_e(configurato):
    assert voxcpm_tts.is_available() is True


def test_senza_endpoint_non_disponibile(configurato, monkeypatch):
    monkeypatch.delenv("ABM_VOXCPM_ENDPOINT_ID")
    assert voxcpm_tts.is_available() is False


def test_senza_chiave_non_disponibile(configurato, monkeypatch):
    monkeypatch.delenv("ABM_VOXCPM_API_KEY")
    assert voxcpm_tts.is_available() is False


def test_senza_tariffa_non_disponibile(configurato, monkeypatch):
    # §15.3: il listino si fissa prima del deploy. Meglio il motore nascosto
    # che libri generati a un prezzo che nessuno ha deciso.
    monkeypatch.delenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR")
    assert voxcpm_tts.is_available() is False


def test_tariffa_zero_non_disponibile(configurato, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "0")
    assert voxcpm_tts.is_available() is False


def test_catalogo_vuoto_non_disponibile(configurato, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", os.path.join(FIXTURE, "nonesiste"))
    voxcpm_catalog.invalidate_cache()
    assert voxcpm_tts.is_available() is False


def test_concorrenza_default_e_override(configurato, monkeypatch):
    assert voxcpm_tts.concurrency() == 32
    monkeypatch.setenv("ABM_VOXCPM_CONCURRENCY", "8")
    assert voxcpm_tts.concurrency() == 8
    monkeypatch.setenv("ABM_VOXCPM_CONCURRENCY", "0")
    assert voxcpm_tts.concurrency() == 1      # floor
    monkeypatch.setenv("ABM_VOXCPM_CONCURRENCY", "cavallo")
    assert voxcpm_tts.concurrency() == 32     # valore illeggibile -> default


def test_listino_e_tariffa_diretta(configurato):
    # 250.000 caratteri a 4,00 EUR/Mchar = 1,00 EUR.
    p = voxcpm_tts.compute_user_price_eur(250_000)
    assert p["chars"] == 250_000
    assert p["list_price_eur"] == 1.00
    assert p["user_price_eur"] == 1.00
    assert p["is_free"] is False


def test_sotto_soglia_e_gratis(configurato):
    # 25.000 caratteri = 0,10 EUR, sotto ABM_VOXCPM_FREE_THRESHOLD_EUR (0,50).
    p = voxcpm_tts.compute_user_price_eur(25_000)
    assert p["list_price_eur"] == 0.10
    assert p["user_price_eur"] == 0.0
    assert p["is_free"] is True


def test_caratteri_assurdi_non_sollevano(configurato):
    assert voxcpm_tts.compute_user_price_eur(0)["list_price_eur"] == 0.0
    assert voxcpm_tts.compute_user_price_eur(-5)["chars"] == 0
    assert voxcpm_tts.compute_user_price_eur(None)["chars"] == 0


def test_costo_gpu_misurato_e_separato_dal_listino(configurato):
    # §8.3: base di costo misurata su RTX 4090, serve all'audit, non al prezzo.
    assert voxcpm_tts.cost_usd_per_mchar() == 0.91
    p = voxcpm_tts.compute_user_price_eur(1_000_000)
    assert p["list_price_eur"] == 4.00      # dalla tariffa, non dal costo
    assert p["cost_usd"] == 0.91


def test_stima_libro_somma_i_capitoli(configurato):
    class Cap:
        def __init__(self, text):
            self.text = text
    capitoli = [Cap("a" * 100_000), Cap("b" * 150_000)]
    s = voxcpm_tts.estimate_book_cost(capitoli, language="it")
    assert s["chars_total"] == 250_000
    assert s["chars_per_chapter"] == [100_000, 150_000]
    assert s["list_price_eur"] == 1.00
    assert s["language"] == "it"
    assert s["model_key"] == "v2"
```

- [ ] **Step 2: Lancia i test e verifica che falliscano**

```
python -m pytest test/test_voxcpm_tts.py -q
```

Atteso: FAIL alla raccolta — `ModuleNotFoundError: No module named 'voxcpm_tts'`.

- [ ] **Step 3: Implementa**

Crea `voxcpm_tts.py`:

```python
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
```

- [ ] **Step 4: Lancia i test e verifica che passino**

```
python -m pytest test/test_voxcpm_tts.py -q
```

Atteso: PASS, 13 test.

- [ ] **Step 5: Documenta le variabili**

In `md_files/PARAMETRI_CONFIGURAZIONE.md`, accanto alla riga già aggiunta nel
Task 2:

```
| `ABM_VOXCPM_ENDPOINT_ID` | — | Endpoint RunPod serverless del worker VoxCPM. Assente: il motore non compare fra i modelli. |
| `ABM_VOXCPM_API_KEY` | — | Chiave API RunPod. Assente: il motore non compare fra i modelli. |
| `ABM_VOXCPM_RATE_EUR_PER_MCHAR` | — | Tariffa di listino all'utente, EUR per milione di caratteri, fee di pagamento incluse. Assente o 0: il motore non compare (meglio nascosto che venduto a un prezzo non deciso). |
| `ABM_VOXCPM_FREE_THRESHOLD_EUR` | `0.50` | Sotto questo importo il job e' gratuito, come per Gemini e Speechify. |
| `ABM_VOXCPM_COST_USD_PER_MCHAR` | `0.91` | Costo GPU misurato (RTX 4090, 2026-08-04). Alimenta solo l'audit del margine, mai il prezzo all'utente. |
| `ABM_VOXCPM_CONCURRENCY` | `32` | Chunk in volo dentro un singolo job del worker. |
```

- [ ] **Step 6: Commit**

```
git add voxcpm_tts.py test/test_voxcpm_tts.py
git add -f md_files/PARAMETRI_CONFIGURAZIONE.md
git commit -m "feat(voxcpm): il motore si presenta solo se sa quanto costa"
```

---
### Task 5: Il prezzo di un job VoxCPM

L'invariante di prezzo del §8.1 — quota, poi soglia, poi floor sul residuo —
non va scritto: esiste già dentro `free_quota.decision()` e regge Gemini e
Speechify. Questo task rende quel percorso consapevole del terzo motore
toccando due punti soli, e lascia `payment.py` completamente fuori: lì vive la
coppia soglia/floor dell'**ottimizzazione AI** (`_llm_apply_min_cost`), che
governa il testo, non le voci.

Il secondo punto è un piccolo raffinamento: oggi il floor è la costante
`ABM_PREMIUM_MIN_COST_EUR` letta inline dentro `decision()`. Diventa
`_premium_floor_eur(voice_id)`, gemella di `_premium_threshold_eur`. Gemini e
Speechify continuano a leggere la stessa variabile di prima — il loro
comportamento non cambia di un centesimo — e VoxCPM legge la sua.

**Files:**
- Modify: `free_quota.py:14` (import), `free_quota.py:155-159`
  (`_premium_threshold_eur`), `free_quota.py:~205` (il floor dentro `decision`)
- Test: `test/test_voxcpm_quota.py`

**Interfaces:**
- Consumes: dal Task 1 — `voice_utils.is_voxcpm_voice`.
- Produces: `free_quota._premium_floor_eur(voice_id) -> float`. `decision()`
  mantiene firma e chiavi di ritorno invariate.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_voxcpm_quota.py`:

```python
"""Ordine quota -> soglia -> floor per le voci VoxCPM.

Verifica soprattutto il caso che la spec (§8.1) chiama fuori per nome: il
floor NON deve scattare quando la quota copre. Un utente con quota capiente
che si vedesse chiedere il minimo pagherebbe per qualcosa che ha gia'.
"""
import pytest

import free_quota

VOCE = "voxcpm:v2:it-IT/Stefano"


@pytest.fixture
def quota_pulita(tmp_path, monkeypatch):
    """Stato quota isolato, limite 2,00 EUR, soglia e floor VoxCPM a 0,50."""
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.50")
    monkeypatch.setenv("ABM_VOXCPM_MIN_COST_EUR", "0.50")
    return "cid-di-prova"


def test_soglia_voxcpm_e_la_sua(quota_pulita, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.80")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.50")
    assert free_quota._premium_threshold_eur(VOCE) == 0.80
    assert free_quota._premium_threshold_eur("gemini:flash25:Zephyr") == 0.50


def test_floor_voxcpm_e_il_suo(quota_pulita, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_MIN_COST_EUR", "1.20")
    monkeypatch.setenv("ABM_PREMIUM_MIN_COST_EUR", "0.50")
    assert free_quota._premium_floor_eur(VOCE) == 1.20
    # Gli altri due motori restano sulla costante di prima: nulla cambia.
    assert free_quota._premium_floor_eur("gemini:flash25:Zephyr") == 0.50
    assert free_quota._premium_floor_eur("speechify:simba-3.2:harper_32") == 0.50


def test_sopra_soglia_si_paga_e_la_quota_non_entra(quota_pulita):
    d = free_quota.decision(quota_pulita, VOCE, 3.00)
    assert d["due_eur"] == 3.00
    assert d["is_free"] is False
    assert d["quota_exhausted"] is False


def test_quota_capiente_il_floor_non_scatta(quota_pulita):
    # IL caso della spec: 0,40 sotto soglia, quota intatta -> gratis.
    # Se il floor si applicasse al lordo l'utente vedrebbe 0,50 da pagare.
    d = free_quota.decision(quota_pulita, VOCE, 0.40)
    assert d["due_eur"] == 0.0
    assert d["is_free"] is True


def test_quota_esaurita_sotto_soglia_scatta_il_floor(quota_pulita):
    free_quota.consume(quota_pulita, 1.90, job_id="job-vecchio")
    d = free_quota.decision(quota_pulita, VOCE, 0.30)
    # 1,90 + 0,30 supera il limite di 2,00: si paga, ma almeno il floor.
    assert d["quota_exhausted"] is True
    assert d["due_eur"] == 0.50


def test_floor_non_abbassa_un_importo_maggiore(quota_pulita):
    free_quota.consume(quota_pulita, 1.95, job_id="job-vecchio")
    d = free_quota.decision(quota_pulita, VOCE, 0.49)
    assert d["due_eur"] == 0.50   # max(0.49, floor 0.50)
    free_quota.consume(quota_pulita, 0.0, job_id="ignoto")


def test_retry_dello_stesso_job_resta_gratis(quota_pulita):
    d1 = free_quota.decision(quota_pulita, VOCE, 0.40, job_id="job-A")
    assert d1["is_free"] is True
    free_quota.consume(quota_pulita, 0.40, job_id="job-A")
    free_quota.consume(quota_pulita, 1.70, job_id="job-B")
    # Quota ora esaurita, ma job-A ha gia' addebitato: il suo retry non ripaga.
    d2 = free_quota.decision(quota_pulita, VOCE, 0.40, job_id="job-A")
    assert d2["due_eur"] == 0.0
    assert d2["is_free"] is True
```

- [ ] **Step 2: Lancia i test e verifica che falliscano**

```
python -m pytest test/test_voxcpm_quota.py -q
```

Atteso: FAIL — `AttributeError: module 'free_quota' has no attribute '_premium_floor_eur'`,
e `test_soglia_voxcpm_e_la_sua` che trova 0.50 invece di 0.80 (la voce VoxCPM
cade oggi nel ramo di default Gemini).

- [ ] **Step 3: Estendi l'import**

`free_quota.py`, riga 14:

```python
from voice_utils import is_speechify_voice
```

diventa:

```python
from voice_utils import is_speechify_voice, is_voxcpm_voice
```

- [ ] **Step 4: Aggiungi il ramo alla soglia e scorpora il floor**

Sostituisci `_premium_threshold_eur` con questa coppia:

```python
def _premium_threshold_eur(voice_id):
    """Soglia sotto la quale il job premium e' gratuito, per motore."""
    if is_voxcpm_voice(voice_id):
        return _env_float("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.50")
    if is_speechify_voice(voice_id):
        return _env_float("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "0.50")
    return _env_float("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.50")


def _premium_floor_eur(voice_id):
    """Importo minimo fatturato quando la quota non copre, per motore.

    Gemini e Speechify restano sulla costante storica `ABM_PREMIUM_MIN_COST_EUR`:
    scorporare la lettura dal corpo di `decision()` non cambia il loro prezzo.
    VoxCPM ha la sua perche' il suo costo non sta nei caratteri ma
    nell'accensione del worker (§8.3), e il minimo esiste proprio per quello.
    """
    if is_voxcpm_voice(voice_id):
        return _env_float("ABM_VOXCPM_MIN_COST_EUR", "0.50")
    return _env_float("ABM_PREMIUM_MIN_COST_EUR", "0.50")
```

Poi, in fondo a `decision()`, sostituisci

```python
    floor = _env_float("ABM_PREMIUM_MIN_COST_EUR", "0.50")
```

con

```python
    floor = _premium_floor_eur(voice_id)
```

- [ ] **Step 5: Lancia i test e verifica che passino**

```
python -m pytest test/test_voxcpm_quota.py -q
```

Atteso: PASS, 7 test.

- [ ] **Step 6: Verifica che Gemini e Speechify non si siano mossi**

Questo task tocca un percorso di pagamento condiviso: la prova che non sia
cambiato nulla per gli altri due motori è la suite di quota esistente.

```
python -m pytest test/test_free_quota.py test/test_free_quota_endpoints.py test/test_free_quota_generate_enforcement.py test/test_free_quota_optimize_enforcement.py -q
```

Atteso: PASS, nessun test rotto.

- [ ] **Step 7: Documenta la variabile**

In `md_files/PARAMETRI_CONFIGURAZIONE.md`:

```
| `ABM_VOXCPM_MIN_COST_EUR` | `0.50` | Importo minimo fatturato per un job VoxCPM quando la quota gratuita mensile non copre. Si applica al residuo dopo la quota, mai al lordo. |
```

- [ ] **Step 8: Commit**

```
git add free_quota.py test/test_voxcpm_quota.py
git add -f md_files/PARAMETRI_CONFIGURAZIONE.md
git commit -m "feat(voxcpm): il minimo si chiede sul residuo, e ogni motore ha il suo"
```

---
### Task 6: Il ponte verso RunPod, e la tassonomia degli errori

Qui `voxcpm_tts.py` impara a parlare con l'endpoint: `POST /run`, polling su
`GET /status/{id}`, `POST /cancel/{id}`. È il porting del cuore della classe
`Runpod` di `voxcpm_book.py` (repo `abm-voxcpm-worker`, righe 1095-1412), non
una riscrittura: le decisioni là dentro sono già costate GPU vera.

Tre cose vanno portate insieme al codice, perché senza di loro il codice è
sbagliato in modo silenzioso:

1. **Mai `/runsync`.** Risponde 200 senza `output` quando il job supera la
   finestra della richiesta: il job continua a girare, continua a essere
   fatturato, e nessuno ne raccoglie il risultato. Il primo job di una
   sessione quella finestra la supera sempre, per via del cold start.
2. **Un job FAILED non è tutto uguale.** Sotto la stessa bandiera
   `engine_dead` stanno due cose diverse: «motore compromesso» viene dal job
   che il motore l'ha rotto davvero, «in spegnimento» dal controllo
   all'ingresso che respinge chi arriva dopo. Sul libro *L'arte di amare*
   furono zero contro diciotto, e trattarli allo stesso modo costò dieci job
   su tredici (§9.3). Il rimbalzo si rifà identico e subito; il motore
   compromesso si rifà stringendo il batch.
3. **Un job mai partito non si ritenta.** Se l'endpoint è saturo, rimettersi
   in fila non aiuta nessuno: è l'unico caso della tabella §9.4 che non è
   ritentabile.

Il modulo non fa retry da solo. Espone gli errori tipizzati e lascia la
politica a chi orchestra (Task 7): qui c'è un job, non un capitolo.

**Files:**
- Modify: `voxcpm_tts.py` (in coda a quanto scritto nel Task 4)
- Test: `test/test_voxcpm_runpod.py`

**Interfaces:**
- Consumes: dal Task 4 — `voxcpm_tts.endpoint_id()`, `api_key()`.
- Produces:
  - `voxcpm_tts.VoxcpmJobError(RuntimeError)` con attributo di classe
    `ritentabile: bool` e attributo d'istanza `job_id: str`.
  - Le quattro sottoclassi: `VoxcpmRimbalzato`, `VoxcpmBloccato`,
    `VoxcpmMotoreCompromesso`, `VoxcpmCodaSatura`.
  - `voxcpm_tts.run_job(payload, *, session=None, sleep=time.sleep, poll=None,
    timeout=None, on_queue=None) -> dict` — l'`output` del job completato.
  - `voxcpm_tts.cancel_job(job_id, *, session=None) -> None`.
  - `voxcpm_tts.SILENCE_RETRIES` (2), `BOUNCE_RETRIES` (6).
  - Usati dal Task 7 (`synthesize_chapter`).

Nota sull'iniezione: `session` e `sleep` sono parametri e non variabili
globali. Servono al doppio di prova — senza `sleep` iniettabile un test del
backoff aspetterebbe davvero trenta secondi — e in produzione restano ai
default (`requests` e `time.sleep`). Nessun mock di libreria, nessuna
patch di modulo: il test passa un oggetto e legge cosa gli è arrivato.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_voxcpm_runpod.py`:

```python
"""Il ponte HTTP verso l'endpoint RunPod, con un doppio al posto della rete.

Il doppio e' una sessione finta che risponde da un copione: `post` e `get`
tirano fuori la prossima risposta preparata e annotano com'erano state
chiamate. Niente monkeypatch di `requests`, cosi' il test verifica il
contratto (che URL, che header, che corpo) e non l'implementazione.
"""
import json

import pytest

import voxcpm_tts


class FintaRisposta:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = text or json.dumps(self._body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise voxcpm_tts.requests.RequestException(f"HTTP {self.status_code}")


class FintaSessione:
    """Risponde dal copione e tiene il registro delle chiamate."""

    def __init__(self, post=None, get=None):
        self.copione_post = list(post or [])
        self.copione_get = list(get or [])
        self.post_fatte = []
        self.get_fatte = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.post_fatte.append({"url": url, "headers": headers, "json": json})
        if not self.copione_post:
            raise AssertionError(f"POST non previsto: {url}")
        r = self.copione_post.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def get(self, url, headers=None, timeout=None):
        self.get_fatte.append({"url": url, "headers": headers})
        if not self.copione_get:
            raise AssertionError(f"GET non previsto: {url}")
        r = self.copione_get.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(autouse=True)
def endpoint_configurato(monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave-di-prova")


def dormi_finto(_secondi):
    """Sostituisce time.sleep: i test del backoff non devono durare come lui."""
    return None


def test_run_job_sottomette_e_raccoglie():
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-1"})],
        get=[FintaRisposta(body={"status": "IN_QUEUE"}),
             FintaRisposta(body={"status": "IN_PROGRESS"}),
             FintaRisposta(body={"status": "COMPLETED",
                                 "output": {"audio_seconds": 12.0}})],
    )
    out = voxcpm_tts.run_job({"input": {"action": "generate"}},
                             session=ses, sleep=dormi_finto, poll=0)
    assert out == {"audio_seconds": 12.0}
    assert ses.post_fatte[0]["url"] == "https://api.runpod.ai/v2/ep-di-prova/run"
    assert ses.get_fatte[0]["url"] == "https://api.runpod.ai/v2/ep-di-prova/status/job-1"


def test_non_usa_mai_runsync():
    # /runsync risponde 200 senza output quando il job supera la finestra
    # della richiesta, e il job continua a essere fatturato senza che nessuno
    # ne raccolga il risultato. Il primo job di una sessione la supera sempre.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-1"})],
        get=[FintaRisposta(body={"status": "COMPLETED", "output": {}})],
    )
    voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert all("runsync" not in c["url"] for c in ses.post_fatte)


def test_la_chiave_viaggia_nell_header_e_non_nel_corpo():
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-1"})],
        get=[FintaRisposta(body={"status": "COMPLETED", "output": {}})],
    )
    voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    head = ses.post_fatte[0]["headers"]
    assert head["Authorization"] == "Bearer chiave-di-prova"
    assert "chiave-di-prova" not in json.dumps(ses.post_fatte[0]["json"])


def test_submit_ritenta_sui_transitori():
    ses = FintaSessione(
        post=[FintaRisposta(status_code=503, text="scaling"),
              FintaRisposta(body={"id": "job-2"})],
        get=[FintaRisposta(body={"status": "COMPLETED", "output": {"ok": 1}})],
    )
    out = voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert out == {"ok": 1}
    assert len(ses.post_fatte) == 2


def test_submit_non_ritenta_sugli_errori_definitivi():
    # 401 non migliora riprovando: la chiave sbagliata resta sbagliata.
    ses = FintaSessione(post=[FintaRisposta(status_code=401, text="unauthorized")])
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert "401" in str(e.value)
    assert len(ses.post_fatte) == 1


def test_rimbalzo_riconosciuto_dal_job_fallito():
    # Il worker che respinge risponde con `error`, quindi RunPod marca FAILED:
    # il rimbalzo va riconosciuto QUI, non dove si legge un output riuscito.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-3"})],
        get=[FintaRisposta(body={
            "status": "FAILED",
            "output": {"error": "worker in spegnimento, rilanciare il job",
                       "engine_dead": True, "bounced": True}})],
    )
    with pytest.raises(voxcpm_tts.VoxcpmRimbalzato) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert e.value.ritentabile is True
    assert e.value.job_id == "job-3"


def test_rimbalzo_riconosciuto_anche_senza_il_campo_bounced():
    # `bounced` esiste solo dalle immagini nuove: il testo resta il criterio
    # di riserva, se no un endpoint vecchio scambia i rimbalzi per guasti.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-4"})],
        get=[FintaRisposta(body={
            "status": "FAILED",
            "output": {"error": "worker in spegnimento", "engine_dead": True}})],
    )
    with pytest.raises(voxcpm_tts.VoxcpmRimbalzato):
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)


def test_motore_compromesso_non_e_un_rimbalzo():
    # Il guasto vero: si ritenta, ma stringendo il batch. Confonderlo col
    # rimbalzo e' l'errore che costo' dieci job su tredici (§9.3).
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-5"})],
        get=[FintaRisposta(body={
            "status": "FAILED",
            "output": {"error": "motore compromesso: il worker si spegne",
                       "engine_dead": True, "failed_indices": [2, 3]}})],
    )
    with pytest.raises(voxcpm_tts.VoxcpmMotoreCompromesso) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert not isinstance(e.value, voxcpm_tts.VoxcpmRimbalzato)
    assert e.value.ritentabile is True


def test_errore_nell_output_di_un_job_completato():
    # Il worker puo' consegnare COMPLETED con `error` dentro: e' il caso
    # dell'upload fallito. Non e' audio, quindi non e' un successo.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-6"})],
        get=[FintaRisposta(body={"status": "COMPLETED",
                                 "output": {"error": "upload su presigned PUT fallito"}})],
    )
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert "upload" in str(e.value)


def test_coda_satura_non_e_ritentabile():
    # Mai passato per IN_PROGRESS entro il tetto di coda: l'endpoint e' saturo,
    # non lento. Rimettersi in fila non aiuta nessuno.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-7"})],
        get=[FintaRisposta(body={"status": "IN_QUEUE"}) for _ in range(50)],
        # il cancel a fine attesa
    )
    ses.copione_post.append(FintaRisposta(body={"status": "CANCELLED"}))
    orologio = iter([0.0] + [float(i) for i in range(1, 200)])
    with pytest.raises(voxcpm_tts.VoxcpmCodaSatura) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto,
                           poll=0, queue_timeout=10, clock=lambda: next(orologio))
    assert e.value.ritentabile is False


def test_job_partito_e_mai_finito_si_cancella():
    # Un job che avanza ma non chiude entro il tetto: si cancella (RunPod
    # fattura a secondi finche' gira) e si segnala come ritentabile.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-8"})],
        get=[FintaRisposta(body={"status": "IN_PROGRESS"}) for _ in range(50)],
    )
    ses.copione_post.append(FintaRisposta(body={"status": "CANCELLED"}))
    orologio = iter([0.0] + [float(i) for i in range(1, 200)])
    with pytest.raises(voxcpm_tts.VoxcpmBloccato) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto,
                           poll=0, timeout=10, clock=lambda: next(orologio))
    assert e.value.ritentabile is True
    assert ses.post_fatte[-1]["url"].endswith("/cancel/job-8")


def test_un_transitorio_di_rete_sul_polling_non_uccide_il_job():
    # Il job sull'endpoint vive per conto suo: una GET che non passa e' un
    # problema nostro, e abbandonarlo lascerebbe una GPU accesa e pagata.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-9"})],
        get=[voxcpm_tts.requests.RequestException("connessione persa"),
             FintaRisposta(body={"status": "COMPLETED", "output": {"ok": 2}})],
    )
    out = voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert out == {"ok": 2}


def test_endpoint_non_configurato():
    import os
    os.environ["ABM_VOXCPM_ENDPOINT_ID"] = ""
    try:
        with pytest.raises(voxcpm_tts.VoxcpmJobError):
            voxcpm_tts.run_job({"input": {}}, session=FintaSessione(),
                               sleep=dormi_finto, poll=0)
    finally:
        os.environ["ABM_VOXCPM_ENDPOINT_ID"] = "ep-di-prova"


def test_cancel_job_non_esplode_se_la_rete_cade():
    # Si cancella nel `finally` di percorsi che stanno gia' fallendo: farlo
    # esplodere sostituirebbe l'errore vero con uno di rete.
    ses = FintaSessione(post=[voxcpm_tts.requests.RequestException("giu'")])
    voxcpm_tts.cancel_job("job-x", session=ses)   # non solleva
```

- [ ] **Step 2: Lancia i test e verifica che falliscano**

```
python -m pytest test/test_voxcpm_runpod.py -q
```

Atteso: FAIL, 14 test —
`AttributeError: module 'voxcpm_tts' has no attribute 'VoxcpmJobError'`.

- [ ] **Step 3: Implementa il ponte**

In coda a `voxcpm_tts.py`. Aggiungi `import time` e `import requests` in cima
al modulo, accanto a `import os`:

```python
# --------------------------------------------------------------------------
# Errori
# --------------------------------------------------------------------------
class VoxcpmJobError(RuntimeError):
    """Un job VoxCPM non ha consegnato l'audio.

    `ritentabile` dice se rifare il job ha una speranza. E' la tabella §9.4
    della spec messa nel tipo: chi orchestra decide la politica, ma non deve
    ridedurre da un messaggio se quel fallimento si rifa' o no.
    """

    ritentabile = False

    def __init__(self, messaggio, job_id=""):
        super().__init__(messaggio)
        self.job_id = job_id


class VoxcpmRimbalzato(VoxcpmJobError):
    """Respinto da un worker gia' in spegnimento: non e' un guasto nostro.

    Il controllo all'ingresso di `handler.py` rifiuta i job che arrivano su un
    worker dichiarato morto, e lo fa PRIMA di toccare la GPU. Si rifa'
    identico: stessa concorrenza, e senza spendere i tentativi riservati alla
    GPU che non regge.
    """

    ritentabile = True


class VoxcpmMotoreCompromesso(VoxcpmJobError):
    """Il processo nanovllm e' caduto (tipicamente un OOM) e il worker si spegne.

    Ritentabile, ma stringendo il batch: la causa comune e' la VRAM al limite.
    Distinto dal rimbalzo apposta — vedi §9.3.
    """

    ritentabile = True


class VoxcpmBloccato(VoxcpmJobError):
    """Partito e mai arrivato: cancellato per non pagarlo a vuoto.

    E' il caso in cui ritentare conviene di piu', perche' il tentativo nuovo
    quasi sempre finisce su un altro worker.
    """

    ritentabile = True


class VoxcpmCodaSatura(VoxcpmJobError):
    """Mai partito: l'endpoint e' saturo, non lento.

    L'unica riga non ritentabile della tabella §9.4: rimettersi in fila
    dietro se stessi non libera nessun worker.
    """

    ritentabile = False


# Quante volte si rifa' un job i cui chunk sono usciti a silenzio, e quante
# se n'e' rimbalzato uno. Budget separati perche' misurano cose diverse: il
# primo il carico sulla GPU, il secondo la sfortuna nell'instradamento.
SILENCE_RETRIES = 2
BOUNCE_RETRIES = 6

# Sottostringhe che, nel messaggio d'errore, dicono "la GPU non ce l'ha
# fatta". Sono i casi in cui rifare piu' stretti ha senso: una firma scaduta
# o un testo malformato non migliorano certo a concorrenza 4.
_GPU_PRESSURE = ("out of memory", "cuda", "nvml", "cublas", "device-side",
                 "motore compromesso")

_RUNPOD_BASE = "https://api.runpod.ai/v2"
_SUBMIT_RETRIES = 4
_HTTP_TRANSIENT = (429, 500, 502, 503, 504)


def _base():
    ep = endpoint_id()
    if not ep or not api_key():
        raise VoxcpmJobError(
            "endpoint VoxCPM non configurato: servono ABM_VOXCPM_ENDPOINT_ID "
            "e ABM_VOXCPM_API_KEY")
    return f"{_RUNPOD_BASE}/{ep}"


def _headers():
    return {"Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json"}


def queue_timeout_s():
    return _f("ABM_VOXCPM_QUEUE_TIMEOUT_S", 900.0)


def job_timeout_s():
    return _f("ABM_VOXCPM_JOB_TIMEOUT_S", 1800.0)


def poll_seconds():
    return _f("ABM_VOXCPM_POLL_S", 2.0)


def _rimbalzo(out, testo):
    """Il rimbalzo si riconosce dal campo o, sulle immagini vecchie, dal testo."""
    return bool(out.get("bounced")) or "in spegnimento" in testo


def _errore_del_job(out, testo, job_id):
    """Da una risposta fallita all'eccezione giusta."""
    if _rimbalzo(out, testo):
        return VoxcpmRimbalzato(testo, job_id)
    basso = testo.lower()
    if out.get("engine_dead") or any(k in basso for k in _GPU_PRESSURE):
        return VoxcpmMotoreCompromesso(testo, job_id)
    return VoxcpmJobError(testo, job_id)


def _submit(payload, session, sleep):
    ultimo = ""
    for tentativo in range(_SUBMIT_RETRIES):
        try:
            r = session.post(f"{_base()}/run", headers=_headers(),
                             json=payload, timeout=60)
        except requests.RequestException as e:
            ultimo = str(e)
        else:
            if r.status_code < 400:
                return r.json()["id"]
            if r.status_code not in _HTTP_TRANSIENT:
                raise VoxcpmJobError(f"HTTP {r.status_code}: {r.text[:200]}")
            ultimo = f"HTTP {r.status_code}"
        sleep(min(30, 2 ** tentativo))
    raise VoxcpmJobError(f"esauriti i tentativi di sottomissione ({ultimo})")


def cancel_job(job_id, *, session=None):
    """Cancella un job in volo. Non solleva mai.

    Si chiama nei percorsi che stanno gia' fallendo: farla esplodere
    sostituirebbe l'errore vero con uno di rete. Un job abbandonato pero' va
    cancellato davvero, perche' continua a occupare la GPU e si paga a secondi.
    """
    ses = session or requests
    try:
        ses.post(f"{_base()}/cancel/{job_id}", headers=_headers(),
                 json=None, timeout=30)
    except Exception:      # noqa: BLE001 - best effort, per definizione
        pass


def run_job(payload, *, session=None, sleep=time.sleep, poll=None, timeout=None,
            queue_timeout=None, clock=time.time, on_queue=None):
    """Sottomette il job e ne aspetta l'esito. Ritorna l'`output`.

    `/run` piu' polling su `/status`, mai `/runsync`: quello risponde 200 e
    senza `output` quando il job supera la finestra della richiesta, e il job
    continua a girare — e a essere pagato — senza che nessuno ne raccolga il
    risultato. Il primo job di una sessione quella finestra la supera sempre,
    per via del cold start di ~180 s (§9.1).

    Args:
        payload: il corpo completo, `{"input": {...}}`.
        session: oggetto con `post`/`get` alla `requests`. Il default e'
            `requests` stesso; nei test e' il doppio.
        sleep: funzione d'attesa. Iniettabile perche' un test del backoff non
            deve durare quanto il backoff.
        poll: secondi fra due sonde. `None` = da ambiente.
        timeout: tetto sull'esecuzione, in secondi. `None` = da ambiente.
        queue_timeout: tetto sull'attesa in coda. `None` = da ambiente.
        clock: sorgente del tempo, iniettabile come `sleep`.
        on_queue: callback opzionale `(secondi_in_coda)` chiamata mentre il
            job e' ancora in fila. Serve alla UI per dichiarare l'attesa
            invece di fingere un progresso che non c'e' (§9.1).

    Raises:
        VoxcpmRimbalzato, VoxcpmMotoreCompromesso, VoxcpmBloccato,
        VoxcpmCodaSatura, VoxcpmJobError: vedi la tabella §9.4.
    """
    ses = session or requests
    attesa = poll_seconds() if poll is None else float(poll)
    tetto_exec = job_timeout_s() if timeout is None else float(timeout)
    tetto_coda = queue_timeout_s() if queue_timeout is None else float(queue_timeout)

    job_id = _submit(payload, ses, sleep)
    t0 = clock()
    t_run = None
    while True:
        trascorso = clock() - t0
        if t_run is None:
            if trascorso > tetto_coda:
                cancel_job(job_id, session=ses)
                raise VoxcpmCodaSatura(
                    f"job {job_id} mai partito: {trascorso / 60:.0f} min in "
                    f"coda, oltre i {tetto_coda / 60:.0f} concessi. "
                    f"L'endpoint e' saturo, non lento", job_id)
        elif clock() - t_run > tetto_exec:
            # Cancellare non restituisce i secondi gia' consumati, ma ferma
            # quelli che verrebbero dopo.
            cancel_job(job_id, session=ses)
            raise VoxcpmBloccato(
                f"job {job_id} oltre {tetto_exec:.0f}s di esecuzione: il "
                f"worker non sta avanzando, si cancella e si rifa", job_id)

        try:
            r = ses.get(f"{_base()}/status/{job_id}", headers=_headers(),
                        timeout=60)
            r.raise_for_status()
            st = r.json()
        except requests.RequestException:
            # Il job sull'endpoint vive per conto suo: una sonda che non passa
            # e' un problema nostro, e abbandonarlo qui lascerebbe una GPU
            # accesa e pagata.
            sleep(attesa)
            continue

        stato = st.get("status")
        if t_run is None and stato == "IN_PROGRESS":
            t_run = clock()
        if stato in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            out = st.get("output")
            out = out if isinstance(out, dict) else {}
            if stato == "COMPLETED" and not out.get("error"):
                return out
            # L'`output` per primo, quando c'e': il worker che rifiuta o che
            # muore risponde con un dizionario — `engine_dead`, `bounced`, la
            # scheda, la VRAM libera — mentre `error` di RunPod e' la sola
            # stringa. Leggere prima quella butterebbe via proprio i campi
            # messi li' per diagnosticare il guasto.
            dettaglio = json.dumps(out) if out else json.dumps(
                st.get("error") or st)
            testo = f"job {job_id} {stato}: {dettaglio[:400]}"
            raise _errore_del_job(out, testo, job_id)

        if t_run is None and on_queue is not None:
            on_queue(trascorso)
        sleep(attesa)
```

Aggiungi anche `import json` fra gli import del modulo: serve a comporre il
dettaglio dell'errore.

- [ ] **Step 4: Lancia i test e verifica che passino**

```
python -m pytest test/test_voxcpm_runpod.py -q
```

Atteso: PASS, 14 test.

- [ ] **Step 5: Documenta le variabili di tempo**

In `md_files/PARAMETRI_CONFIGURAZIONE.md`:

```
| `ABM_VOXCPM_QUEUE_TIMEOUT_S` | `900` | Quanto si aspetta in coda un job VoxCPM prima di dichiarare l'endpoint saturo. Scaduto, il job si cancella e non si ritenta. |
| `ABM_VOXCPM_JOB_TIMEOUT_S` | `1800` | Quanto puo' durare l'esecuzione di un job VoxCPM. Scaduto, il job si cancella (RunPod fattura a secondi) e si ritenta. |
| `ABM_VOXCPM_POLL_S` | `2` | Intervallo fra due sonde su `/status`. |
```

- [ ] **Step 6: Commit**

```
git add voxcpm_tts.py test/test_voxcpm_runpod.py
git add -f md_files/PARAMETRI_CONFIGURAZIONE.md
git commit -m "feat(voxcpm): il ponte con RunPod, e un rimbalzo non e' un guasto"
```

---

### Task 7: Un capitolo, un job

Il Task 6 sa fare *un* job. Questo sa fare *un capitolo*: compone il payload
con la voce, decide il canale di trasporto dell'audio, e applica la politica
di ritentativo. È l'unità di lavoro decisa in §7.3 — un job per capitolo — e
la ragione è economica: il costo sta nell'accensione del worker (~180 s a
freddo), non nei caratteri, quindi un job da un chunk e uno da otto costano
uguale, e l'accensione si ammortizza sui capitoli successivi finché il worker
resta caldo.

Quattro decisioni entrano nel codice, tutte già prese altrove:

1. **`hifi` sempre** (§7.4). `prompt_wav_b64` più `prompt_text`, e in più
   `reference_wav_b64`. Le tre modalità costano uguale: il divario dei primi
   riepiloghi era l'accensione, non la modalità.
2. **`prompt_text` è un requisito duro, non un accessorio.** Misurato il
   2026-08-28: incrociando i due canali, il risultato segue il prefisso e
   ignora il riferimento. Un campione senza la sua trascrizione esatta resta
   fuori dal canale che porta l'identità, e la resa crolla a quella di
   `reference`, già giudicata inaccettabile. Perciò una voce senza
   trascrizione il Task 2 l'ha già scartata dal catalogo: qui non può arrivare.
3. **Il ritentativo sta dentro lo stesso job finché il worker è caldo**
   (§9.2). È l'inversione esatta rispetto agli altri tre motori: con Edge,
   Google e Gemini un chunk fallito si ritenta e si pagano i caratteri; qui un
   capitolo ritentato a freddo paga un'accensione intera.
4. **I chunk a silenzio non si tengono.** Il worker, quando un chunk cade, ci
   mette un secondo di silenzio e tira dritto, così il capitolo resta
   allineato. Per un audiolibro quel silenzio è una frase persa, e passerebbe
   ogni verifica a valle: l'M4B corrisponderebbe esattamente ai frammenti,
   silenzi compresi. Si rifà il capitolo a concorrenza ridotta — i chunk
   cadono quando la VRAM è al limite, e a batch più stretto lo stesso capitolo
   in genere passa.

Sul trasporto: l'audio grezzo di un capitolo a 48 kHz supera il limite inline
di RunPod, quindi passa da R2 con una PUT firmata, esattamente come fa
`voxcpm_book.py` (§15.4: R2 è già nel percorso). Se R2 non è configurato si
ripiega sull'inline, che regge i capitoli corti ed è ciò che rende collaudabile
il percorso senza credenziali.

**Files:**
- Modify: `voxcpm_tts.py` (in coda)
- Test: `test/test_voxcpm_chapter.py`

**Interfaces:**
- Consumes: dal Task 3 — `voxcpm_catalog.parse_voice_id`, `sample_path`;
  dal Task 4 — `concurrency()`; dal Task 6 — `run_job`, le eccezioni,
  `SILENCE_RETRIES`, `BOUNCE_RETRIES`.
- Produces:
  - `voxcpm_tts.CFG_READ` (float, `2.0`) — aderenza al testo e al riferimento.
  - `voxcpm_tts.clone_block(voice_id) -> dict` — i campi del payload che
    determinano la voce, in modalità `hifi`. Il risultato è memorizzato per
    `voice_id`: rileggere e ricodificare il wav a ogni capitolo è lavoro
    ripetuto su un file che non cambia.
  - `voxcpm_tts.synthesize_chapter(chunks, voice_id, dest_path, *, key="",
    session=None, sleep=time.sleep, on_queue=None, cancelled=None) -> dict`
    con chiavi `{"sample_rate", "chars", "audio_seconds", "tts_seconds",
    "jobs", "redone", "bounced", "failed_chunks", "bytes"}`. Scrive il PCM grezzo in
    `dest_path`.
  - Usati dal Task 9 (pre-pass in `generation_engine`) e dal Task 11 (audit).

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_voxcpm_chapter.py`:

```python
"""Un capitolo intero: payload, trasporto dell'audio, politica di ritentativo.

`run_job` e' sostituito da un doppio che segue un copione di esiti. Cosi' il
test verifica LA POLITICA — quante volte si rifa', con che concorrenza, quando
si arrende — senza rifare le prove del ponte HTTP, che sono nel Task 6.
"""
import base64
import os

import pytest

import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
VOCE = "voxcpm:v2:it-IT/Stefano"
CHUNKS = ["Prima frase.", "Seconda frase.", "Terza frase."]


@pytest.fixture(autouse=True)
def catalogo_e_endpoint(monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_CONCURRENCY", "32")
    # R2 spento: il percorso inline e' quello collaudabile senza credenziali.
    monkeypatch.delenv("ABM_S3_BUCKET", raising=False)
    voxcpm_catalog.invalidate_cache()
    voxcpm_tts.invalidate_clone_cache()


def esito_ok(pcm=b"\x01\x02" * 100, **extra):
    d = {"audio_b64": base64.b64encode(pcm).decode("ascii"),
         "sample_rate": 48000, "chars": 42, "audio_seconds": 3.0,
         "tts_seconds": 1.0, "failed_indices": []}
    d.update(extra)
    return d


class FintoRunJob:
    """Segue un copione di esiti; annota i payload che ha ricevuto."""

    def __init__(self, *esiti):
        self.esiti = list(esiti)
        self.payload = []
        self.attese = []

    def __call__(self, payload, **kw):
        self.payload.append(payload)
        if not self.esiti:
            raise AssertionError("job non previsto dal copione")
        e = self.esiti.pop(0)
        if isinstance(e, Exception):
            raise e
        return e


def sintetizza(finto, tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(voxcpm_tts, "run_job", finto)
    monkeypatch.setattr(voxcpm_tts, "_dormi", lambda _s: None)
    dest = str(tmp_path / "cap.pcm")
    return voxcpm_tts.synthesize_chapter(CHUNKS, VOCE, dest, **kw), dest


def test_il_payload_e_in_hifi_con_prefisso_e_trascrizione(tmp_path, monkeypatch):
    finto = FintoRunJob(esito_ok())
    sintetizza(finto, tmp_path, monkeypatch)
    inp = finto.payload[0]["input"]
    assert inp["action"] == "generate"
    assert inp["chunks"] == CHUNKS
    assert inp["output_format"] == "pcm"
    assert inp["concurrency"] == 32
    assert inp["cfg"] == voxcpm_tts.CFG_READ
    # hifi: il prefisso porta l'identita', il riferimento l'accompagna.
    assert inp["prompt_format"] == "wav"
    assert inp["reference_format"] == "wav"
    assert base64.b64decode(inp["prompt_wav_b64"])[:4] == b"RIFF"
    assert base64.b64decode(inp["reference_wav_b64"])[:4] == b"RIFF"


def test_prompt_text_e_la_trascrizione_esatta(tmp_path, monkeypatch):
    finto = FintoRunJob(esito_ok())
    sintetizza(finto, tmp_path, monkeypatch)
    atteso = voxcpm_catalog.parse_voice_id(VOCE)["transcript"]
    assert finto.payload[0]["input"]["prompt_text"] == atteso
    assert atteso    # senza, il canale che porta l'identita' resterebbe vuoto


def test_l_audio_finisce_nel_file(tmp_path, monkeypatch):
    finto = FintoRunJob(esito_ok(pcm=b"\xaa\xbb" * 50))
    stats, dest = sintetizza(finto, tmp_path, monkeypatch)
    with open(dest, "rb") as f:
        assert f.read() == b"\xaa\xbb" * 50
    assert stats["sample_rate"] == 48000
    assert stats["jobs"] == 1
    assert stats["redone"] == 0


def test_il_wav_della_voce_si_codifica_una_volta_sola(tmp_path, monkeypatch):
    # Rileggere e ricodificare in base64 lo stesso file a ogni capitolo e'
    # lavoro ripetuto su un dato che non cambia: su un libro da 40 capitoli
    # sono 40 letture identiche.
    finto = FintoRunJob(esito_ok(), esito_ok())
    monkeypatch.setattr(voxcpm_tts, "run_job", finto)
    monkeypatch.setattr(voxcpm_tts, "_dormi", lambda _s: None)
    letture = {"n": 0}
    vero = voxcpm_catalog.sample_path

    def conta(vid):
        letture["n"] += 1
        return vero(vid)

    monkeypatch.setattr(voxcpm_catalog, "sample_path", conta)
    voxcpm_tts.synthesize_chapter(CHUNKS, VOCE, str(tmp_path / "a.pcm"))
    voxcpm_tts.synthesize_chapter(CHUNKS, VOCE, str(tmp_path / "b.pcm"))
    assert letture["n"] == 1


def test_rimbalzo_si_rifa_uguale(tmp_path, monkeypatch):
    # Il worker non ha nemmeno acceso la GPU: stringere il batch curerebbe una
    # malattia che non c'e'. Stessa concorrenza, e i tentativi veri non si
    # consumano.
    finto = FintoRunJob(
        voxcpm_tts.VoxcpmRimbalzato("worker in spegnimento", "j1"),
        esito_ok())
    stats, _ = sintetizza(finto, tmp_path, monkeypatch)
    assert [p["input"]["concurrency"] for p in finto.payload] == [32, 32]
    assert stats["bounced"] == 1
    assert stats["redone"] == 0


def test_rimbalzi_a_oltranza_si_arrendono(tmp_path, monkeypatch):
    troppi = [voxcpm_tts.VoxcpmRimbalzato("in spegnimento", "j")
              for _ in range(voxcpm_tts.BOUNCE_RETRIES + 2)]
    finto = FintoRunJob(*troppi)
    with pytest.raises(voxcpm_tts.VoxcpmRimbalzato):
        sintetizza(finto, tmp_path, monkeypatch)


def test_motore_compromesso_si_rifa_a_batch_stretto(tmp_path, monkeypatch):
    finto = FintoRunJob(
        voxcpm_tts.VoxcpmMotoreCompromesso("motore compromesso", "j2"),
        esito_ok())
    stats, _ = sintetizza(finto, tmp_path, monkeypatch)
    assert [p["input"]["concurrency"] for p in finto.payload] == [32, 8]
    assert stats["redone"] == 1


def test_chunk_a_silenzio_buttano_il_capitolo(tmp_path, monkeypatch):
    # Il worker consegna audio "buono": e' proprio il caso pericoloso, perche'
    # a valle passerebbe ogni verifica. Il silenzio va riconosciuto qui.
    finto = FintoRunJob(esito_ok(failed_indices=[1]), esito_ok())
    stats, _ = sintetizza(finto, tmp_path, monkeypatch)
    assert [p["input"]["concurrency"] for p in finto.payload] == [32, 8]
    assert stats["redone"] == 1
    assert stats["failed_chunks"] == 0


def test_silenzio_ostinato_e_un_fallimento(tmp_path, monkeypatch):
    finto = FintoRunJob(*[esito_ok(failed_indices=[1])
                          for _ in range(voxcpm_tts.SILENCE_RETRIES + 1)])
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        sintetizza(finto, tmp_path, monkeypatch)
    assert "silenzio" in str(e.value)


def test_la_concorrenza_non_scende_sotto_quattro(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_CONCURRENCY", "8")
    finto = FintoRunJob(esito_ok(failed_indices=[0]),
                        esito_ok(failed_indices=[0]),
                        esito_ok())
    sintetizza(finto, tmp_path, monkeypatch)
    assert [p["input"]["concurrency"] for p in finto.payload] == [8, 4, 4]


def test_coda_satura_non_si_ritenta(tmp_path, monkeypatch):
    # L'unica riga non ritentabile della tabella §9.4: un secondo tentativo
    # sarebbe un'altra accensione pagata per rimettersi nella stessa fila.
    finto = FintoRunJob(voxcpm_tts.VoxcpmCodaSatura("endpoint saturo", "j3"))
    with pytest.raises(voxcpm_tts.VoxcpmCodaSatura):
        sintetizza(finto, tmp_path, monkeypatch)
    assert len(finto.payload) == 1


def test_con_r2_acceso_l_audio_passa_dalla_put_firmata(tmp_path, monkeypatch):
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "presigned_put_url",
                        lambda key, ttl=None: f"https://r2.esempio/{key}?firma")
    monkeypatch.setattr(storage_backend, "presigned_get_url",
                        lambda key, download_name=None, ttl=None: f"https://r2.esempio/{key}?get")
    cancellate = []
    monkeypatch.setattr(storage_backend, "delete_object", cancellate.append)
    monkeypatch.setattr(voxcpm_tts, "_scarica",
                        lambda url, dest: open(dest, "wb").write(b"\x07" * 64) and None)
    finto = FintoRunJob({"s3": {"bytes": 64}, "sample_rate": 48000, "chars": 9,
                         "audio_seconds": 1.0, "tts_seconds": 0.5,
                         "failed_indices": []})
    stats, dest = sintetizza(finto, tmp_path, monkeypatch, key="voxcpm/j/ch1.pcm")
    inp = finto.payload[0]["input"]
    assert inp["s3"]["put_url"].startswith("https://r2.esempio/")
    assert inp["s3"]["key"] == "voxcpm/j/ch1.pcm"
    assert os.path.getsize(dest) == 64
    # L'oggetto su R2 e' un intermedio: tenerlo sarebbe pagare storage per un
    # file che il server ha gia' scaricato.
    assert cancellate == ["voxcpm/j/ch1.pcm"]


def test_r2_acceso_ma_il_worker_non_carica_niente(tmp_path, monkeypatch):
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "presigned_put_url",
                        lambda key, ttl=None: "https://r2.esempio/x?firma")
    monkeypatch.setattr(storage_backend, "delete_object", lambda k: None)
    finto = FintoRunJob({"s3": {"bytes": 0}, "sample_rate": 48000},
                        {"s3": {"bytes": 0}, "sample_rate": 48000},
                        {"s3": {"bytes": 0}, "sample_rate": 48000})
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        sintetizza(finto, tmp_path, monkeypatch, key="voxcpm/j/ch1.pcm")
    assert "non ha caricato" in str(e.value)


def test_annullamento_prima_di_accendere(tmp_path, monkeypatch):
    # Un job cancellato dall'utente non deve accendere altra GPU: si controlla
    # PRIMA di sottomettere, che e' il momento in cui la spesa comincia.
    finto = FintoRunJob()
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        sintetizza(finto, tmp_path, monkeypatch, cancelled=lambda: True)
    assert finto.payload == []
    assert "annullato" in str(e.value)


def test_voce_sparita_dal_catalogo(tmp_path, monkeypatch):
    finto = FintoRunJob()
    monkeypatch.setattr(voxcpm_tts, "run_job", finto)
    with pytest.raises(ValueError):
        voxcpm_tts.synthesize_chapter(CHUNKS, "voxcpm:v2:it-IT/Fantasma",
                                      str(tmp_path / "x.pcm"))
    assert finto.payload == []
```

- [ ] **Step 2: Lancia i test e verifica che falliscano**

```
python -m pytest test/test_voxcpm_chapter.py -q
```

Atteso: FAIL, 15 test —
`AttributeError: module 'voxcpm_tts' has no attribute 'invalidate_clone_cache'`.

- [ ] **Step 3: Implementa**

In coda a `voxcpm_tts.py`. Aggiungi `import base64` e `import threading` fra
gli import del modulo:

```python
# Aderenza al testo e al riferimento. E' il default di lettura del client
# (`voxcpm_book.py`, CFG_READ): alzarlo irrigidisce la dizione, abbassarlo
# fa divagare la voce dal campione.
CFG_READ = 2.0

# Concorrenza minima: sotto i 4 chunk in volo il worker paga piu' overhead di
# quanto guadagni in stabilita', e il capitolo che non passa a 4 non passa.
_CONCURRENCY_FLOOR = 4

_clone_cache = {}
_clone_lock = threading.Lock()

# Indirezione sul sonno, cosi' i test della politica di ritentativo non
# durano quanto le pause che verificano.
_dormi = time.sleep


def invalidate_clone_cache():
    """Svuota la cache dei campioni codificati. La chiamano i test."""
    with _clone_lock:
        _clone_cache.clear()


def clone_block(voice_id):
    """I campi del payload che determinano la voce, in modalita' `hifi`.

    `hifi` per tutte le voci (§7.4): prefisso piu' riferimento. Il canale che
    porta l'identita' e' `prompt_wav_b64`, misurato il 2026-08-28 incrociando
    i due canali — il risultato segue il prefisso e ignora il riferimento.
    Per questo `prompt_text` e' un requisito duro: senza la trascrizione
    esatta il prefisso non entra nel canale che conta e la resa crolla a
    quella di `reference`, gia' giudicata inaccettabile.

    Il risultato e' memorizzato per `voice_id`: il wav non cambia, e su un
    libro da quaranta capitoli sarebbero quaranta letture identiche.
    """
    with _clone_lock:
        pronto = _clone_cache.get(voice_id)
    if pronto is not None:
        return dict(pronto)

    rec = voxcpm_catalog.parse_voice_id(voice_id)
    with open(voxcpm_catalog.sample_path(voice_id), "rb") as f:
        wav = base64.b64encode(f.read()).decode("ascii")
    blocco = {
        "prompt_wav_b64": wav,
        "prompt_format": "wav",
        "prompt_text": rec["transcript"],
        "reference_wav_b64": wav,
        "reference_format": "wav",
    }
    with _clone_lock:
        _clone_cache[voice_id] = blocco
    return dict(blocco)


def _scarica(url, dest):
    """Scrive in `dest` il corpo di `url`, senza tenerlo tutto in memoria.

    Il PCM di un capitolo a 48 kHz sta sulle decine di megabyte: leggerlo in
    una stringa moltiplicherebbe la memoria del server per il numero di
    capitoli in volo.
    """
    tmp = dest + ".part"
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for pezzo in r.iter_content(chunk_size=1 << 20):
                if pezzo:
                    f.write(pezzo)
    os.replace(tmp, dest)


def synthesize_chapter(chunks, voice_id, dest_path, *, key="", session=None,
                       sleep=None, on_queue=None, cancelled=None):
    """Sintetizza un capitolo intero come un solo job. Scrive il PCM grezzo.

    Un job per capitolo (§7.3): il costo sta nell'accensione del worker, non
    nei caratteri, quindi un job da un chunk e uno da otto costano uguale, e
    l'accensione si ammortizza sui capitoli successivi finche' il worker resta
    caldo.

    Il ritentativo sta qui e non piu' in alto per la stessa ragione (§9.2):
    rifare il capitolo mentre il worker e' caldo costa secondi di GPU, rifarlo
    a freddo costa un'accensione intera.

    Args:
        chunks: i testi del capitolo, gia' spezzati da `tts_split`.
        voice_id: `voxcpm:v2:<locale>/<Nome>`.
        dest_path: dove scrivere il PCM 16 bit mono.
        key: chiave R2 dell'intermedio. Vuota o R2 spento = audio inline.
        session, sleep, on_queue: inoltrati a `run_job`.
        cancelled: predicato senza argomenti. Se vero prima di sottomettere,
            il job non parte: e' il momento in cui la spesa comincia.

    Returns:
        dict con `sample_rate`, `chars`, `audio_seconds`, `tts_seconds`,
        `jobs`, `redone`, `bounced`, `failed_chunks`, `bytes`.

    Raises:
        ValueError: la voce non e' nel catalogo (§9.4, caso normale).
        VoxcpmJobError e sottoclassi: vedi la tabella §9.4.
    """
    import storage_backend

    clone = clone_block(voice_id)      # prima di tutto: se la voce non c'e',
                                       # si scopre senza aver acceso nulla
    riposa = sleep or _dormi
    su_r2 = bool(key) and storage_backend.is_enabled()
    stats = {"sample_rate": 0, "chars": 0, "audio_seconds": 0.0,
             "tts_seconds": 0.0, "jobs": 0, "redone": 0, "bounced": 0,
             "failed_chunks": 0, "bytes": 0}

    conc = concurrency()
    tentativo, rimbalzi = 0, 0
    while True:
        if cancelled is not None and cancelled():
            raise VoxcpmJobError("job annullato: nessun altro worker acceso")
        ultimo = tentativo >= SILENCE_RETRIES

        payload = {"input": {
            "action": "generate",
            "chunks": list(chunks),
            **clone,
            "cfg": CFG_READ,
            "concurrency": conc,
            # PCM grezzo, non WAV: i capitoli vengono concatenati byte a byte
            # da `pcm_concat`, e un header WAV in mezzo finirebbe dentro
            # l'audio come rumore.
            "output_format": "pcm",
        }}
        if su_r2:
            payload["input"]["s3"] = {
                "put_url": storage_backend.presigned_put_url(key),
                "key": key,
            }

        try:
            out = run_job(payload, session=session, sleep=riposa,
                          on_queue=on_queue)
        except VoxcpmRimbalzato:
            # Respinto senza essere partito: si rifa' uguale. La concorrenza
            # resta quella e il contatore dei tentativi veri non si muove,
            # perche' questo non e' un sintomo di carico ma di instradamento.
            rimbalzi += 1
            stats["bounced"] += 1
            if rimbalzi > BOUNCE_RETRIES:
                raise
            # Una pausa che cresce, non un ritentativo immediato: il worker
            # guasto impiega ancora una decina di secondi a uscire, e finche'
            # e' li' respinge tutto.
            riposa(min(30, 10 * rimbalzi))
            continue
        except (VoxcpmBloccato, VoxcpmMotoreCompromesso):
            # Stesso rimedio, due sintomi: il worker che si e' fermato e la
            # GPU che non ha retto vogliono entrambi un batch piu' stretto.
            if ultimo:
                raise
        else:
            stats["jobs"] += 1
            stats["sample_rate"] = stats["sample_rate"] or int(
                out.get("sample_rate") or 48000)
            stats["chars"] += int(out.get("chars") or 0)
            stats["audio_seconds"] += float(out.get("audio_seconds") or 0.0)
            stats["tts_seconds"] += float(out.get("tts_seconds") or 0.0)

            bad = out.get("failed_indices") or []
            if bad:
                # Il worker mette un secondo di silenzio al posto della frase
                # caduta e tira dritto, cosi' il capitolo resta allineato. Per
                # un audiolibro pero' quel silenzio e' una frase persa, e a
                # valle passerebbe ogni verifica: l'M4B corrisponderebbe
                # esattamente ai frammenti, silenzi compresi.
                if su_r2:
                    storage_backend.delete_object(key)
                if ultimo:
                    raise VoxcpmJobError(
                        f"{len(bad)} chunk su {len(chunks)} a silenzio anche a "
                        f"concorrenza {conc}: il capitolo sarebbe bucato, non "
                        f"lo si tiene")
            else:
                scritti = _consegna(out, dest_path, key, su_r2, conc, len(chunks))
                stats["bytes"] = scritti
                return stats

        conc = max(_CONCURRENCY_FLOOR, conc // 4)
        tentativo += 1
        stats["redone"] += 1


def _consegna(out, dest_path, key, su_r2, conc, n_chunk):
    """Porta l'audio del job in `dest_path`. Ritorna i byte scritti."""
    import storage_backend

    if su_r2:
        caricati = int((out.get("s3") or {}).get("bytes") or 0)
        if not caricati:
            raise VoxcpmJobError(
                "il job non ha caricato niente su R2: " + json.dumps(out)[:300])
        _scarica(storage_backend.presigned_get_url(key), dest_path)
        # L'oggetto su R2 e' un intermedio: il server ha gia' i byte, tenerlo
        # sarebbe pagare storage per una copia che nessuno rilegge.
        storage_backend.delete_object(key)
        return os.path.getsize(dest_path)

    audio = out.get("audio_b64")
    if not audio:
        raise VoxcpmJobError(
            f"risposta senza audio per {n_chunk} chunk a concorrenza {conc}: "
            + json.dumps(out)[:300])
    dati = base64.b64decode(audio)
    tmp = dest_path + ".part"
    with open(tmp, "wb") as f:
        f.write(dati)
    os.replace(tmp, dest_path)
    return len(dati)
```

- [ ] **Step 4: Lancia i test e verifica che passino**

```
python -m pytest test/test_voxcpm_chapter.py -q
```

Atteso: PASS, 15 test.

- [ ] **Step 5: Commit**

```
git add voxcpm_tts.py test/test_voxcpm_chapter.py
git commit -m "feat(voxcpm): un capitolo e' un job, e il silenzio non si tiene"
```

---

### Task 8: Le voci arrivano al browser, e il campione si può ascoltare

Il catalogo esiste ma nessuno lo vede. Questo task lo pubblica su `/api/voices`
accanto a Edge, Google, Gemini e Speechify, e apre la rotta che serve il file
`.wav` del campione — quella che in §5.2 sostituisce l'anteprima di lettura.

Perché il campione non è un file statico servito da `/static`: i `.wav` stanno
in `data/voci_inventate/`, una cartella *importata* e configurabile
(`ABM_VOXCPM_CATALOG_DIR`, D10). Metterla sotto `/static` legherebbe
l'aggiornamento del catalogo a un layout di cartelle invece che a una
variabile, e servirebbe anche i file che il Task 2 ha scartato perché non
validi. La rotta passa invece da `voxcpm_catalog.sample_path()`, che è l'unico
punto che sa quali voci esistono davvero.

**Files:**
- Modify: `audiobook_app.py:2318-2330` (blocco Speechify di `_fetch_voices`,
  il nuovo blocco VoxCPM va subito dopo), `audiobook_app.py:7872`
  (`api_voices`, per la chiave di stato)
- Test: `test/test_voxcpm_api.py`

**Interfaces:**
- Consumes: dal Task 3 — `voxcpm_catalog.get_voices()`, `sample_path()`;
  dal Task 2 — `personas()`; dal Task 4 — `voxcpm_tts.is_available()`.
- Produces:
  - In `/api/voices`, entry con `engine == "voxcpm"` dentro
    `languages[<lingua>]["voices"]`, e la chiave di stato
    `_voxcpm = {"available": bool, "model_label": str, "personas": [str, ...]}`.
  - La rotta `GET /api/voice_sample?voice=<voice_id>` che risponde
    `audio/wav`, `404` se la voce non c'è, `400` se l'id è malformato.
  - Usati dal Task 12 (UI) e dal Task 13 (traduzione dei caratteri).

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_voxcpm_api.py`:

```python
"""Le voci VoxCPM su /api/voices e il campione su /api/voice_sample."""
import os

import pytest

import audiobook_app
import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")


@pytest.fixture(autouse=True)
def catalogo_di_prova(monkeypatch):
    # La cache delle voci di audiobook_app e' globale di modulo: senza
    # invalidarla prima E dopo, questo test vedrebbe (o lascerebbe) il
    # catalogo di un altro.
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "3.00")
    voxcpm_catalog.invalidate_cache()
    audiobook_app._invalidate_voices_cache()
    yield
    voxcpm_catalog.invalidate_cache()
    audiobook_app._invalidate_voices_cache()


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        yield c


def voci_voxcpm(catalogo):
    out = []
    for codice, dati in catalogo.items():
        if codice.startswith("_"):
            continue
        out.extend(v for v in dati.get("voices", []) if v.get("engine") == "voxcpm")
    return out


def test_le_voci_voxcpm_entrano_nel_catalogo():
    trovate = voci_voxcpm(audiobook_app.get_voices())
    assert trovate
    assert all(v["id"].startswith("voxcpm:v2:") for v in trovate)
    assert {v["model_label"] for v in trovate} == {"VoxCPM2"}


def test_le_voci_finiscono_sotto_la_lingua_giusta():
    catalogo = audiobook_app.get_voices()
    ita = [v for v in catalogo["it"]["voices"] if v.get("engine") == "voxcpm"]
    assert len(ita) == 3
    assert all(v["locale"].startswith("it-") for v in ita)


def test_una_lingua_nuova_del_catalogo_apre_la_sua_sezione():
    # D10: il catalogo e' una variabile. Se domani arriva una voce giapponese,
    # /api/voices deve aprire la sezione da solo, senza rilascio.
    catalogo = audiobook_app.get_voices()
    assert "en" in catalogo
    assert [v for v in catalogo["en"]["voices"] if v.get("engine") == "voxcpm"]


def test_senza_configurazione_le_voci_non_compaiono(monkeypatch):
    # Stessa regola del tab premium con Gemini (§9.4): un motore non
    # configurato non compare, invece di comparire e fallire alla generazione.
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "")
    audiobook_app._invalidate_voices_cache()
    assert voci_voxcpm(audiobook_app.get_voices()) == []


def test_un_catalogo_illeggibile_non_rompe_le_altre_voci(monkeypatch, tmp_path):
    # Il catalogo e' un dato importato: se arriva rotto, le voci Edge devono
    # continuare a funzionare. Un motore in meno, non un'app in meno.
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", str(tmp_path / "inesistente"))
    voxcpm_catalog.invalidate_cache()
    audiobook_app._invalidate_voices_cache()
    catalogo = audiobook_app.get_voices()
    assert voci_voxcpm(catalogo) == []
    assert any(not k.startswith("_") for k in catalogo)


def test_stato_del_motore_nella_risposta(client):
    dati = client.get("/api/voices").get_json()
    assert dati["_voxcpm"]["available"] is True
    assert dati["_voxcpm"]["model_label"] == "VoxCPM2"
    # I caratteri arrivano dal catalogo, mai da una costante: la UI ci
    # costruisce il filtro CARATTERE.
    assert "warm-pro" in dati["_voxcpm"]["personas"]


def test_il_campione_si_scarica(client):
    r = client.get("/api/voice_sample?voice=voxcpm:v2:it-IT/Stefano")
    assert r.status_code == 200
    assert r.mimetype == "audio/wav"
    assert r.data[:4] == b"RIFF"


def test_campione_di_una_voce_inesistente(client):
    r = client.get("/api/voice_sample?voice=voxcpm:v2:it-IT/Fantasma")
    assert r.status_code == 404


def test_campione_con_id_malformato(client):
    for cattivo in ("", "gemini:flash25:Zephyr", "voxcpm:v2"):
        r = client.get(f"/api/voice_sample?voice={cattivo}")
        assert r.status_code == 400


def test_campione_non_serve_file_fuori_dal_catalogo(client, monkeypatch):
    # `voice` arriva dal browser e il percorso del file da un file di dati:
    # nessuno dei due e' fidato.
    r = client.get("/api/voice_sample?voice=voxcpm:v2:../../etc/passwd")
    assert r.status_code in (400, 404)


def test_campione_di_una_voce_scartata(client, monkeypatch, tmp_path):
    # `Senzacarattere` sta nel voices.json della fixture ma il Task 2 l'ha
    # scartata: la rotta non deve servirla piu' della lista.
    r = client.get("/api/voice_sample?voice=voxcpm:v2:it-IT/Senzacarattere")
    assert r.status_code == 404
```

- [ ] **Step 2: Lancia i test e verifica che falliscano**

```
python -m pytest test/test_voxcpm_api.py -q
```

Atteso: FAIL — nessuna voce con `engine == "voxcpm"`, e `404` sulla rotta
`/api/voice_sample`, che non esiste.

- [ ] **Step 3: Importa il motore in `audiobook_app.py`**

Accanto agli altri import opzionali di motore, in cima al file:

```python
try:
    import voxcpm_catalog
    import voxcpm_tts
except Exception as _voxcpm_err:      # noqa: BLE001
    # Il catalogo e' un dato importato e il motore e' opzionale: se manca,
    # l'app parte lo stesso con tre motori invece di quattro.
    print(f"VoxCPM non disponibile: {_voxcpm_err}")
    voxcpm_catalog = None
    voxcpm_tts = None
```

- [ ] **Step 4: Fondi le voci in `_fetch_voices`**

Subito dopo il blocco Speechify (che finisce con
`print(f"Error merging Speechify voices: {e}")`), aggiungi:

```python
    # 5. VoxCPM2 (opzionale) — gated su endpoint, chiave, tariffa e catalogo.
    if voxcpm_tts is not None and voxcpm_tts.is_available():
        try:
            vox_dict = voxcpm_catalog.get_voices()  # -> {"it": [entry, ...]}
            for lc_short, v_list in vox_dict.items():
                if lc_short not in languages:
                    # Il catalogo e' una variabile (D10): una lingua nuova
                    # apre la sua sezione senza che nessuno rilasci codice.
                    languages[lc_short] = {
                        "name": LOCALE_NAMES.get(lc_short, lc_short.upper()),
                        "voices": []
                    }
                languages[lc_short]["voices"].extend(v_list)
        except Exception as e:
            # Un catalogo illeggibile toglie un motore, non l'applicazione.
            print(f"Error merging VoxCPM voices: {e}")
```

- [ ] **Step 5: Pubblica lo stato del motore in `api_voices`**

Dentro `api_voices()`, accanto a `_premium_status`:

```python
        # Stato VoxCPM per il tab premium: se il motore non e' disponibile la
        # UI non mostra il modello, invece di mostrarlo con la combo vuota.
        # `personas` e' l'elenco dei CARATTERI presenti nel catalogo di oggi:
        # arriva da li' e non da una costante, cosi' un carattere nuovo non
        # richiede un rilascio (D10).
        if voxcpm_tts is not None:
            try:
                disponibile = bool(voxcpm_tts.is_available())
                voices["_voxcpm"] = {
                    "available": disponibile,
                    "model_label": voxcpm_catalog.MODEL_LABEL,
                    "personas": voxcpm_catalog.personas() if disponibile else [],
                }
            except Exception:
                voices["_voxcpm"] = {"available": False, "model_label": "",
                                     "personas": []}
```

- [ ] **Step 6: Apri la rotta del campione**

Subito dopo `api_voices()`:

```python
@app.route("/api/voice_sample")
def api_voice_sample():
    """Il `.wav` di riferimento di una voce di catalogo.

    Sostituisce l'anteprima di lettura per le voci VoxCPM (§5.2): l'anteprima
    costerebbe un'accensione del worker per pochi secondi di audio, mentre il
    campione e' un file che esiste gia' e che dice esattamente come suonera'
    la voce, perche' e' proprio quello che il modello clonera'.

    Non e' un file statico: il catalogo sta in una cartella importata e
    configurabile, e solo `voxcpm_catalog` sa quali voci sono valide.
    """
    voice_id = (request.args.get("voice") or "").strip()
    if voxcpm_catalog is None:
        return jsonify({"error": "voxcpm non disponibile"}), 404
    try:
        percorso = voxcpm_catalog.sample_path(voice_id)
    except ValueError as e:
        # Id malformato, motore sbagliato, o voce non piu' in catalogo dopo una
        # rigenerazione: dal punto di vista del browser sono la stessa cosa,
        # una richiesta a cui non si puo' rispondere.
        messaggio = str(e)
        codice = 404 if "non presente nel catalogo" in messaggio else 400
        return jsonify({"error": messaggio}), codice
    except FileNotFoundError:
        return jsonify({"error": "campione non disponibile"}), 404
    return send_file(percorso, mimetype="audio/wav", conditional=True)
```

- [ ] **Step 7: Lancia i test e verifica che passino**

```
python -m pytest test/test_voxcpm_api.py test/test_voices_endpoint.py -q
```

Atteso: PASS. La suite delle voci esistente gira insieme perché questo task
tocca la funzione che la produce.

- [ ] **Step 8: Commit**

```
git add audiobook_app.py test/test_voxcpm_api.py
git commit -m "feat(voxcpm): le voci arrivano al wizard, e il campione si ascolta"
```

---

### Task 9: VoxCPM dentro `run_generation`

Il motore sa fare un capitolo; ora il libro. Il gancio esiste già ed è quello
che usa Speechify: una **pre-sintesi parallela** riempie un dizionario, e
l'assemblaggio sequenziale — che non cambia di una riga — lo legge invece di
richiamare l'API una seconda volta. VoxCPM ci si innesta cambiando solo
l'unità: dove Speechify pre-sintetizza *un chunk per volta*, VoxCPM
pre-sintetizza *un capitolo per volta* (§7.3).

Da questa differenza discende l'unica cosa strana del task, e va detta prima
perché altrimenti sembra un errore. Il worker restituisce **un PCM per job**,
cioè per capitolo, concatenato: i confini fra i chunk non tornano indietro, e
non c'è modo di ricavarli. Ma la catena a valle assembla per chunk. Quindi:

> il PCM del capitolo si scrive nel file-parte del **primo** chunk del
> capitolo, e agli altri chunk dello stesso capitolo tocca un file vuoto.

`pcm_concat` concatena i pezzi in ordine, e un pezzo vuoto non aggiunge nulla:
l'audio esce identico, i marcatori M4B restano allineati perché la durata del
capitolo si accumula tutta sul suo primo pezzo, e nessun altro punto della
catena va toccato. L'alternativa — chiedere al worker le lunghezze dei singoli
chunk — vorrebbe dire modificare `abm-voxcpm-worker`, che §12 mette
esplicitamente fra i **non toccati**.

Due conseguenze da tenere a mente:

- **Il riuso dei chunk lavora per capitolo.** Un capitolo si salta solo se
  *tutti* i suoi chunk sono riusabili: rigenerarne uno solo costerebbe
  comunque l'intero job, e il PCM parziale non si potrebbe ricucire.
- **La VELOCITÀ la applica l'app.** L'azione `generate` del worker non ha un
  parametro di velocità (ce l'ha `assemble`, che D9 lascia fuori). Il PCM
  scaricato passa quindi per un `atempo` di ffmpeg, una volta per capitolo.
  Il campo VELOCITÀ del pannello resta quello di sempre, −30%…+30% (§5.2), e
  quell'intervallo sta comodamente dentro il dominio di `atempo`.

**Files:**
- Modify: `generation_engine.py:203-204` (import), `:3208-3224`
  (`_engine_for_voice`), `:1535-1554` (`_friendly_voice_name`), `:4175-4182`
  (i flag di motore), `:4464` (`_speechify_pre`, dove nasce il gemello),
  `:4489` (il ramo dentro `_synthesize_chunk`), `:4657-4682` (dove va la
  pre-sintesi), più le due funzioni nuove a livello di modulo
- Modify: `voxcpm_tts.py` (in coda: `jobs_in_flight()`, `apply_rate()`)
- Test: `test/test_voxcpm_generation.py`

**Interfaces:**
- Consumes: dal Task 1 — `voice_utils.is_voxcpm_voice`; dal Task 7 —
  `voxcpm_tts.synthesize_chapter`; dal Task 4 — `concurrency()`.
- Produces:
  - `voxcpm_tts.jobs_in_flight() -> int` — capitoli in volo insieme,
    default 2, floor 1.
  - `voxcpm_tts.apply_rate(pcm_path, rate, sample_rate) -> bool` — applica la
    velocità al PCM sul posto. `False` se non c'era nulla da fare.
  - `generation_engine._voxcpm_chapter_groups(plan, reusable) -> list` di
    `(chapter_index, [indice_chunk, ...])`, in ordine di piano.
  - `generation_engine._voxcpm_pre_pass(plan, voice, rate, work_dir, job_id,
    reusable, cancelled=None) -> dict` — `{indice_chunk: risultato}`.
  - `_engine_for_voice(voice)` che ritorna `"voxcpm"`.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_voxcpm_generation.py`:

```python
"""VoxCPM dentro la catena di generazione: scelta motore, raggruppamento in
capitoli, pre-sintesi.

`synthesize_chapter` e' sostituita da un doppio: qui si prova come il libro
viene diviso in job e dove finisce l'audio, non come si parla con RunPod.
"""
import os

import pytest

import generation_engine
import voxcpm_tts

VOCE = "voxcpm:v2:it-IT/Stefano"


def blocco(testo, capitolo):
    return {"text": testo, "chapter_index": capitolo}


PIANO = [blocco("a", 0), blocco("b", 0), blocco("c", 1),
         blocco("d", 2), blocco("e", 2), blocco("f", 2)]


def test_il_motore_si_riconosce_dal_prefisso():
    assert generation_engine._engine_for_voice(VOCE) == "voxcpm"
    assert generation_engine._engine_for_voice("voxcpm:mine:abc") == "voxcpm"
    # Gli altri tre non si spostano.
    assert generation_engine._engine_for_voice("gemini:flash25:Zephyr") == "gemini"
    assert generation_engine._engine_for_voice("speechify:simba-3.2:harper_32") == "speechify"
    assert generation_engine._engine_for_voice("it-IT-IsabellaNeural") == "edge"
    assert generation_engine._engine_for_voice("") == "edge"


def test_nome_amichevole_senza_locale_ne_prefisso():
    assert generation_engine._friendly_voice_name(VOCE) == "Stefano"
    assert generation_engine._friendly_voice_name("voxcpm:v2:en-GB/Rufus") == "Rufus"


def test_i_chunk_si_raggruppano_per_capitolo():
    gruppi = generation_engine._voxcpm_chapter_groups(PIANO, set())
    assert gruppi == [(0, [0, 1]), (1, [2]), (2, [3, 4, 5])]


def test_un_capitolo_tutto_riusabile_si_salta():
    gruppi = generation_engine._voxcpm_chapter_groups(PIANO, {0, 1})
    assert gruppi == [(1, [2]), (2, [3, 4, 5])]


def test_un_capitolo_riusabile_a_meta_si_rifa_intero():
    # Rigenerare un solo chunk costerebbe comunque il job intero, e il PCM
    # parziale non si potrebbe ricucire: non c'e' mezza misura.
    gruppi = generation_engine._voxcpm_chapter_groups(PIANO, {3, 4})
    assert gruppi == [(0, [0, 1]), (1, [2]), (2, [3, 4, 5])]


class FintaSintesi:
    """Al posto di voxcpm_tts.synthesize_chapter: scrive byte finti."""

    def __init__(self, errore=None):
        self.chiamate = []
        self.errore = errore

    def __call__(self, chunks, voice_id, dest_path, **kw):
        self.chiamate.append({"chunks": list(chunks), "voice": voice_id,
                              "dest": dest_path, "key": kw.get("key", "")})
        if self.errore:
            raise self.errore
        with open(dest_path, "wb") as f:
            f.write(b"\x11\x22" * len(chunks))
        return {"sample_rate": 48000, "chars": sum(len(c) for c in chunks),
                "audio_seconds": 1.0 * len(chunks), "tts_seconds": 0.5,
                "jobs": 1, "redone": 0, "bounced": 0, "failed_chunks": 0,
                "bytes": 2 * len(chunks)}


@pytest.fixture
def sintesi_finta(monkeypatch):
    f = FintaSintesi()
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", f)
    monkeypatch.setattr(voxcpm_tts, "apply_rate", lambda *a, **k: False)
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "1")   # deterministico nei test
    return f


def test_un_job_per_capitolo_con_i_testi_del_capitolo(tmp_path, sintesi_finta):
    generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path, "job-1", set())
    assert [c["chunks"] for c in sintesi_finta.chiamate] == [
        ["a", "b"], ["c"], ["d", "e", "f"]]


def test_l_audio_finisce_sul_primo_chunk_del_capitolo(tmp_path, sintesi_finta):
    # Il worker torna un PCM per capitolo e i confini fra i chunk non tornano
    # indietro: si scrive tutto sul primo pezzo, e gli altri restano vuoti.
    # `pcm_concat` li concatena in ordine e un pezzo vuoto non aggiunge nulla.
    generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path, "job-1", set())
    assert os.path.getsize(tmp_path / "chunk_000000.pcm") == 4
    assert os.path.getsize(tmp_path / "chunk_000001.pcm") == 0
    assert os.path.getsize(tmp_path / "chunk_000003.pcm") == 6
    assert os.path.getsize(tmp_path / "chunk_000004.pcm") == 0
    assert os.path.getsize(tmp_path / "chunk_000005.pcm") == 0


def test_ogni_chunk_ha_un_risultato(tmp_path, sintesi_finta):
    pre = generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path,
                                             "job-1", set())
    assert sorted(pre) == [0, 1, 2, 3, 4, 5]
    assert pre[0]["sample_rate"] == 48000
    # I chunk di coda non hanno audio proprio: non devono contarsi due volte.
    assert pre[1]["chars"] == 0
    assert pre[1]["audio_seconds"] == 0.0


def test_i_capitoli_riusabili_non_entrano_nella_pre_sintesi(tmp_path, sintesi_finta):
    pre = generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path,
                                             "job-1", {0, 1})
    assert [c["chunks"] for c in sintesi_finta.chiamate] == [["c"], ["d", "e", "f"]]
    assert 0 not in pre and 1 not in pre


def test_la_chiave_r2_distingue_job_e_capitolo(tmp_path, sintesi_finta):
    generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path, "job-7", set())
    chiavi = [c["key"] for c in sintesi_finta.chiamate]
    assert chiavi == ["voxcpm/job-7/ch000000.pcm",
                      "voxcpm/job-7/ch000001.pcm",
                      "voxcpm/job-7/ch000002.pcm"]
    assert len(set(chiavi)) == 3


def test_un_capitolo_perso_ferma_il_libro(tmp_path, monkeypatch):
    # §9.4: esauriti i ritentativi, e' un fallimento del job con rimborso, non
    # un capitolo muto consegnato all'utente.
    f = FintaSintesi(errore=voxcpm_tts.VoxcpmJobError("chunk a silenzio"))
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", f)
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "1")
    with pytest.raises(voxcpm_tts.VoxcpmJobError):
        generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path,
                                           "job-1", set())


def test_annullamento_ferma_le_accensioni(tmp_path, sintesi_finta):
    with pytest.raises(Exception):
        generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path,
                                           "job-1", set(),
                                           cancelled=lambda: True)
    assert sintesi_finta.chiamate == []


def test_la_velocita_si_applica_al_pcm_del_capitolo(tmp_path, monkeypatch):
    f = FintaSintesi()
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", f)
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "1")
    applicate = []
    monkeypatch.setattr(voxcpm_tts, "apply_rate",
                        lambda p, r, sr: applicate.append((os.path.basename(p), r, sr)))
    generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+15%", tmp_path, "job-1", set())
    # Una volta per capitolo, non una per chunk: l'audio sta tutto li'.
    assert applicate == [("chunk_000000.pcm", "+15%", 48000),
                         ("chunk_000002.pcm", "+15%", 48000),
                         ("chunk_000003.pcm", "+15%", 48000)]
```

Aggiungi in coda a `test/test_voxcpm_tts.py` (il file del Task 4) le prove
delle due funzioni nuove:

```python
def test_jobs_in_flight_ha_un_floor(monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "0")
    assert voxcpm_tts.jobs_in_flight() == 1
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "4")
    assert voxcpm_tts.jobs_in_flight() == 4
    monkeypatch.delenv("ABM_VOXCPM_JOBS", raising=False)
    assert voxcpm_tts.jobs_in_flight() == 2


def test_apply_rate_non_fa_niente_a_velocita_normale(tmp_path):
    p = tmp_path / "x.pcm"
    p.write_bytes(b"\x00\x01" * 100)
    for neutro in ("+0%", "0%", "", None):
        assert voxcpm_tts.apply_rate(str(p), neutro, 48000) is False
    assert p.stat().st_size == 200


def test_apply_rate_accelera_il_pcm(tmp_path):
    # ffmpeg vero su un PCM di silenzio: +30% deve accorciare il file.
    p = tmp_path / "x.pcm"
    p.write_bytes(b"\x00\x00" * 48000)          # 1 s a 48 kHz, 16 bit mono
    assert voxcpm_tts.apply_rate(str(p), "+30%", 48000) is True
    assert 60000 < p.stat().st_size < 84000     # ~1/1,3 di 96000 byte
```

- [ ] **Step 2: Lancia i test e verifica che falliscano**

```
python -m pytest test/test_voxcpm_generation.py -q
```

Atteso: FAIL —
`AttributeError: module 'generation_engine' has no attribute '_voxcpm_chapter_groups'`.

- [ ] **Step 3: Aggiungi a `voxcpm_tts.py` la concorrenza dei job e la velocità**

In coda al modulo:

```python
def jobs_in_flight():
    """Capitoli sottomessi insieme. Floor a 1.

    Il default e' 2 e non 24 come la concorrenza dei chunk: quella misura il
    batch dentro un worker, questa quanti worker si accendono. Ogni job in
    piu' e' un'accensione in piu' se l'endpoint deve scalare, e l'accensione
    e' il costo dominante (§9.2).
    """
    return max(1, _i("ABM_VOXCPM_JOBS", 2))


def apply_rate(pcm_path, rate, sample_rate):
    """Applica la velocita' di lettura al PCM, sul posto. Ritorna True se fatto.

    L'azione `generate` del worker non ha un parametro di velocita': ce l'ha
    `assemble`, che D9 lascia fuori dal perimetro. La velocita' la mette
    quindi l'app, con un `atempo` di ffmpeg sul PCM grezzo. L'intervallo del
    pannello e' -30%..+30% (§5.2), comodamente dentro il dominio 0,5-2,0 di
    `atempo`: un solo filtro basta, nessuna catena.
    """
    try:
        pct = float(str(rate or "0").replace("%", "").replace("+", "").strip())
    except (TypeError, ValueError):
        return False
    tempo = 1.0 + pct / 100.0
    if abs(tempo - 1.0) < 0.005:
        return False
    tempo = max(0.5, min(2.0, tempo))

    import subprocess
    sr = int(sample_rate or 48000)
    tmp = pcm_path + ".rate"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", pcm_path,
           "-filter:a", f"atempo={tempo:.4f}",
           "-f", "s16le", "-ar", str(sr), "-ac", "1", tmp]
    subprocess.run(cmd, check=True)
    os.replace(tmp, pcm_path)
    return True
```

- [ ] **Step 4: Riconosci il motore in `generation_engine.py`**

Riga 204, accanto agli altri import da `voice_utils`:

```python
from voice_utils import is_voxcpm_voice as _is_voxcpm_voice
```

In `_engine_for_voice`, aggiungi il ramo e la riga di docstring. Il controllo
va **prima** degli altri: il prefisso è disgiunto, ma l'ordine rende evidente
che i quattro motori sono una catena di prefissi e non una gerarchia.

```python
def _engine_for_voice(voice):
    """Sceglie il motore TTS dal voice ID.

    Prefissi:
      - "voxcpm:..."    -> VoxCPM2 su RunPod (PCM native, job per capitolo)
      - "speechify:..." -> Speechify Simba-3.2 (PCM native)
      - "gemini:..."  -> Gemini TTS (PCM native)
      - "gcloud:..."  -> Google Cloud TTS Chirp3-HD (MP3)
      - altrimenti    -> Microsoft Edge TTS (MP3, default)
    """
    if not voice:
        return "edge"
    if _is_voxcpm_voice(voice):
        return "voxcpm"
    if _is_speechify_voice(voice):
        return "speechify"
    # I rami gemini:/gcloud:/edge che seguono restano invariati.
```

In `_friendly_voice_name`, subito dopo il ramo Speechify:

```python
    if _is_voxcpm_voice(v):
        # 'voxcpm:v2:it-IT/Stefano' -> 'Stefano'. Il locale serve a distinguere
        # le voci dentro il catalogo, non a chi legge l'email di consegna.
        return v.split("/")[-1].strip()
```

- [ ] **Step 5: Scrivi le due funzioni della pre-sintesi**

A livello di modulo in `generation_engine.py`, accanto alle altre funzioni di
supporto della generazione:

```python
def _voxcpm_chapter_groups(plan, reusable):
    """I chunk del piano raggruppati per capitolo, in ordine.

    Ritorna `[(chapter_index, [indice_chunk, ...]), ...]`, saltando i capitoli
    i cui chunk sono TUTTI riusabili da un tentativo precedente.

    Il riuso e' per capitolo e non per chunk perche' l'unita' di lavoro e' il
    capitolo (§7.3): rigenerare un solo chunk costerebbe comunque il job
    intero, e il PCM che torna e' del capitolo, non ricucibile a pezzi.
    """
    ordine = []
    per_capitolo = {}
    for i, blocco in enumerate(plan):
        ci = blocco.get("chapter_index", 0)
        if ci not in per_capitolo:
            per_capitolo[ci] = []
            ordine.append(ci)
        per_capitolo[ci].append(i)
    return [(ci, per_capitolo[ci]) for ci in ordine
            if not set(per_capitolo[ci]) <= set(reusable)]


def _voxcpm_pre_pass(plan, voice, rate, work_dir, job_id, reusable,
                     cancelled=None):
    """Sintetizza il libro un capitolo per job. Ritorna {indice_chunk: esito}.

    Gemella della pre-sintesi Speechify poco piu' sotto, con un'unita' diversa:
    li' un chunk per chiamata, qui un capitolo per job (§7.3). L'assemblaggio
    sequenziale non cambia: legge i file-parte gia' scritti.

    Il worker restituisce UN PCM per job, e i confini fra i chunk non tornano
    indietro. L'audio del capitolo si scrive percio' nel file-parte del suo
    PRIMO chunk, e gli altri chunk dello stesso capitolo ricevono un file
    vuoto: `pcm_concat` li concatena in ordine e un pezzo vuoto non aggiunge
    nulla, quindi l'audio esce identico e i marcatori M4B restano allineati.
    Chiedere al worker le lunghezze dei singoli chunk vorrebbe dire modificare
    `abm-voxcpm-worker`, che la spec mette fra i non toccati.

    Raises:
        _CancelledError: annullamento richiesto.
        voxcpm_tts.VoxcpmJobError: capitolo perso a ritentativi esauriti. E' un
            fallimento del job con rimborso (§9.4), non un capitolo muto.
    """
    import concurrent.futures as _cf

    gruppi = _voxcpm_chapter_groups(plan, reusable)
    esiti = {}

    def _uno(gruppo):
        ci, indici = gruppo
        if cancelled is not None and cancelled():
            raise _CancelledError("Job cancelled")
        testa = indici[0]
        dest = str(work_dir / f"chunk_{testa:06d}.pcm")
        stats = voxcpm_tts.synthesize_chapter(
            [plan[i]["text"] for i in indici], voice, dest,
            # Un job = un capitolo: la chiave e' univoca e permette di risalire
            # dal file su R2 al job che l'ha prodotto.
            key=f"voxcpm/{job_id}/ch{ci:06d}.pcm",
            cancelled=cancelled)
        voxcpm_tts.apply_rate(dest, rate, stats.get("sample_rate") or 48000)
        return ci, indici, stats

    with _cf.ThreadPoolExecutor(max_workers=voxcpm_tts.jobs_in_flight()) as _ex:
        for ci, indici, stats in _ex.map(_uno, gruppi):
            for posto, i in enumerate(indici):
                if posto == 0:
                    esiti[i] = stats
                    continue
                # Coda del capitolo: file vuoto, e un esito a zero perche' le
                # misure del capitolo sono gia' contate sul primo chunk.
                parte = work_dir / f"chunk_{i:06d}.pcm"
                with open(parte, "wb"):
                    pass
                esiti[i] = {"sample_rate": stats.get("sample_rate") or 48000,
                            "chars": 0, "audio_seconds": 0.0,
                            "tts_seconds": 0.0, "jobs": 0, "redone": 0,
                            "bounced": 0, "failed_chunks": 0, "bytes": 0}
    return esiti
```

- [ ] **Step 6: Innesta il ramo in `run_generation`**

Ai flag di motore (riga ~4176):

```python
    use_voxcpm = (engine == "voxcpm")
    use_pcm = use_gemini or use_speechify or use_voxcpm
```

e la riga del sample rate poco sotto diventa:

```python
    _pcm_sr = (48000 if (use_speechify or use_voxcpm)
               else 24000) if use_pcm else 24000
    if use_speechify:
        _pcm_sr = job.get("speechify_sample_rate", 48000)
```

Accanto a `_speechify_pre = {}` (riga ~4464):

```python
        _voxcpm_pre = {}
```

Dentro `_synthesize_chunk`, subito prima del ramo `if use_speechify:`:

```python
            if use_voxcpm:
                # L'audio l'ha gia' scritto la pre-sintesi per capitolo: qui
                # non si chiama nessuna API, si consegna il file-parte. Per i
                # chunk di coda quel file e' vuoto ed e' corretto che lo sia,
                # perche' l'audio del capitolo sta tutto sul primo.
                part_path = str(work_dir / f"chunk_{i:06d}.pcm")
                return _voxcpm_pre.get(i, {"reused": True}), part_path
```

E dove oggi c'è la pre-sintesi Speechify (riga ~4657), subito prima di essa:

```python
        # Pre-sintesi VoxCPM: un job per capitolo, jobs_in_flight() in volo.
        # L'assemblaggio sotto resta sequenziale e legge i .pcm gia' prodotti
        # (via _voxcpm_pre), come per Speechify.
        if use_voxcpm:
            job["progress_message"] = (
                "Accensione del motore vocale, circa tre minuti...")
            _voxcpm_pre = _voxcpm_pre_pass(
                plan, voice, rate, work_dir, job_id, _reusable_chunks,
                cancelled=_check_cancelled)
            job["progress_message"] = "Assembling audio..."
```

Il messaggio di attesa non è cosmetico: il cold start è di circa 180 secondi
(§9.1) e la barra deve dichiarare l'attesa invece di fingere un progresso che
non c'è.

- [ ] **Step 7: Lancia i test e verifica che passino**

```
python -m pytest test/test_voxcpm_generation.py test/test_voxcpm_tts.py -q
```

Atteso: PASS.

- [ ] **Step 8: Verifica che gli altri tre motori non si siano mossi**

Questo task tocca il cuore di `run_generation`: la prova che nulla sia
cambiato per Edge, Google, Gemini e Speechify è la suite intera.

```
python -m pytest test/ -q
```

Atteso: nessun test rotto rispetto alla linea di base (1964 passed,
16 skipped, più i test nuovi di questo piano).

- [ ] **Step 9: Documenta le variabili**

In `md_files/PARAMETRI_CONFIGURAZIONE.md`:

```
| `ABM_VOXCPM_JOBS` | `2` | Capitoli VoxCPM sottomessi insieme. Ogni job in piu' e' un'accensione in piu' se l'endpoint deve scalare. |
```

- [ ] **Step 10: Commit**

```
git add generation_engine.py voxcpm_tts.py test/test_voxcpm_generation.py test/test_voxcpm_tts.py
git add -f md_files/PARAMETRI_CONFIGURAZIONE.md
git commit -m "feat(voxcpm): un capitolo per job dentro la catena che non cambia"
```

---

### Task 10: Il prezzo si mostra, e si incassa

Il Task 5 ha reso `free_quota.decision()` consapevole di VoxCPM; ma quella
funzione la chiamano gli endpoint, e gli endpoint oggi si accorgono solo di
due motori. Questo task porta VoxCPM nei quattro punti dove i soldi si
muovono — stima, ordine PayPal, addebito alla generazione, enforcement
dell'ottimizzazione combinata — e chiude l'anteprima, che per VoxCPM non
esiste.

Il rischio da non correre ha già un nome nel codice: **l'incidente «402
Speechify»**, quando la UI diceva «gratis» e il backend rispondeva 402 perché
i due punti leggevano soglie diverse. Il commento a `audiobook_app.py:12126`
lo racconta. La regola che ne è uscita, e che questo task rispetta alla
lettera: *nessun punto legge una soglia per conto suo*. Tutti passano da
`free_quota`, cioè dal Task 5.

Un'osservazione sulla forma. Il ramo di addebito Speechify a
`audiobook_app.py:10221` porta un `TODO(refactor)` che segnala novanta righe
duplicate dal ramo Gemini. Non le duplichiamo una terza volta e non facciamo
nemmeno il refactor: quel ramo è già descritto come «specchio LEAN» — nessun
budget Google, nessun preflight RPD — che è esattamente la forma di cui
VoxCPM ha bisogno. Si allarga la condizione del ramo esistente invece di
scriverne uno nuovo. Un ramo in meno da tenere allineato, e nessuna riga
riscritta su un percorso di pagamento in produzione.

**Files:**
- Modify: `audiobook_app.py:515` (import), `:522-527`
  (`_max_text_chars_for_voice`), `:9382-9420` (anteprima), `:9828-9835`
  (guardia di configurazione in `/api/generate`), `:10221` (condizione del
  ramo di addebito premium), `:12074-12130` (`api_combined_estimate`),
  `:12273-12285` (`api_paypal_create_order_gemini`), `:12507-12512`
  (enforcement dell'ottimizzazione combinata)
- Test: `test/test_voxcpm_pricing_api.py`

**Interfaces:**
- Consumes: dal Task 1 — `voice_utils.is_voxcpm_voice`; dal Task 4 —
  `voxcpm_tts.estimate_book_cost()`, `is_available()`; dal Task 5 —
  `free_quota.decision()` già consapevole di VoxCPM.
- Produces:
  - `audiobook_app._is_voxcpm_voice` (alias di modulo, come i due omologhi).
  - In `/api/combined_estimate`: le chiavi `voxcpm_eur` (float) e
    `voxcpm_breakdown` (dict con `chars`, `chars_total`, `user_price_eur`,
    `is_free`, `model_label`, `cost_usd`). `total_eur`, `is_free`,
    `threshold_eur`, `free_quota` restano quelli di sempre.
  - `MAX_VOXCPM_TEXT_CHARS` (int), il cap caratteri del motore.
  - In `/api/preview`: l'errore `voxcpm_preview_unsupported` (400).

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_voxcpm_pricing_api.py`:

```python
"""Il prezzo VoxCPM lungo i quattro punti dove i soldi si muovono.

La prova che conta e' l'ultima: stima e generazione devono dire la stessa
cosa. Quando divergono nasce l'incidente "402 Speechify" (UI gratis, backend
402, job fermo a 0%).
"""
import os

import pytest

import audiobook_app
import voxcpm_catalog

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
VOCE = "voxcpm:v2:it-IT/Stefano"


class Cap:
    def __init__(self, index, text):
        self.index = index
        self.text = text


class Info:
    language = "it"

    def __init__(self, capitoli):
        self.chapters = capitoli


@pytest.fixture
def motore(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave")
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "4.00")
    monkeypatch.setenv("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.50")
    monkeypatch.setenv("ABM_VOXCPM_MIN_COST_EUR", "0.50")
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    voxcpm_catalog.invalidate_cache()
    audiobook_app._invalidate_voices_cache()
    yield
    voxcpm_catalog.invalidate_cache()
    audiobook_app._invalidate_voices_cache()


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        yield c


@pytest.fixture
def job_grande(motore):
    """Job con 250.000 caratteri: a 4,00 EUR/Mchar fa 1,00 EUR, sopra soglia."""
    jid = "job-vox-1"
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[jid] = {
            "info": Info([Cap(0, "a" * 100_000), Cap(1, "b" * 150_000)]),
            "client_id": "cid-vox", "status": "analyzed",
        }
    yield jid
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop(jid, None)


@pytest.fixture
def job_piccolo(motore):
    """25.000 caratteri: 0,10 EUR, sotto soglia."""
    jid = "job-vox-2"
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[jid] = {
            "info": Info([Cap(0, "a" * 25_000)]),
            "client_id": "cid-vox2", "status": "analyzed",
        }
    yield jid
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop(jid, None)


def stima(client, job_id, **extra):
    corpo = {"job_id": job_id, "voice_id": VOCE, "ai_opt_enabled": False}
    corpo.update(extra)
    return client.post("/api/combined_estimate", json=corpo).get_json()


def test_la_stima_espone_il_prezzo_voxcpm(client, job_grande):
    d = stima(client, job_grande)
    assert d["voxcpm_eur"] == 1.00
    assert d["total_eur"] == 1.00
    assert d["is_free"] is False
    assert d["gemini_eur"] == 0.0 and d["speechify_eur"] == 0.0


def test_il_dettaglio_dice_caratteri_e_modello(client, job_grande):
    b = stima(client, job_grande)["voxcpm_breakdown"]
    assert b["chars"] == 250_000
    assert b["chars_total"] == 250_000
    assert b["model_label"] == "VoxCPM2"
    assert b["is_free"] is False


def test_sotto_soglia_la_stima_dice_gratis(client, job_piccolo):
    d = stima(client, job_piccolo)
    assert d["is_free"] is True
    assert d["total_eur"] == 0.0
    assert d["threshold_eur"] == 0.50


def test_la_soglia_e_quella_di_voxcpm(client, job_grande, monkeypatch):
    # Il cuore dell'incidente "402 Speechify": se qui si leggesse la soglia
    # Gemini, un totale fra le due soglie sarebbe gratis per la UI e 402 per
    # il backend.
    monkeypatch.setenv("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.80")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.20")
    assert stima(client, job_grande)["threshold_eur"] == 0.80


def test_la_quota_gratuita_compare_nella_stima(client, job_piccolo):
    d = stima(client, job_piccolo)
    assert d["free_quota"] is not None
    assert d["quota_exhausted"] is False


def test_solo_i_selezionati_entrano_nel_conto(client, job_grande):
    d = stima(client, job_grande, selected_chapters=[0])
    assert d["voxcpm_breakdown"]["chars"] == 100_000
    assert d["voxcpm_eur"] == 0.40


def test_la_stima_non_e_confusa_dall_ottimizzazione(client, job_grande):
    d = stima(client, job_grande, ai_opt_enabled=True)
    # Sul ramo premium combinato la quota LLM resta grezza e si somma: e' la
    # regola gia' in vigore per Gemini e Speechify, non una nuova.
    assert d["llm_eur"] > 0
    assert d["voxcpm_eur"] == 1.00


def test_l_ordine_paypal_rifiuta_un_importo_diverso(client, job_grande):
    r = client.post("/api/paypal_create_order_gemini",
                    json={"job_id": job_grande, "voice_id": VOCE,
                          "amount_eur": 0.10})
    assert r.status_code == 400


def test_generate_rifiuta_voxcpm_non_configurato(client, job_grande, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "")
    r = client.post("/api/generate",
                    json={"job_id": job_grande, "voice": VOCE})
    assert r.status_code == 400
    assert r.get_json()["error"] == "voxcpm_not_configured"


def test_l_anteprima_non_esiste_per_voxcpm(client, motore):
    # §5.2: l'anteprima e' sostituita dall'ascolto del campione. Senza questo
    # rifiuto esplicito la voce cadrebbe nel ramo Edge e verrebbe letta da
    # un'altra voce, che e' peggio di un errore.
    r = client.get(f"/api/preview?job_id=nessuno&voice={VOCE}")
    assert r.status_code == 400
    assert r.get_json()["error"] == "voxcpm_preview_unsupported"


def test_il_cap_caratteri_e_quello_di_voxcpm(motore, monkeypatch):
    monkeypatch.setenv("ABM_MAX_VOXCPM_TEXT_CHARS", "1234")
    import importlib
    importlib.reload(audiobook_app)
    assert audiobook_app._max_text_chars_for_voice(VOCE) == 1234
    importlib.reload(audiobook_app)


def test_stima_e_addebito_dicono_lo_stesso_numero(client, job_grande):
    # L'invariante che l'incidente ha prodotto: un solo punto di decisione.
    import free_quota
    d = stima(client, job_grande)
    dec = free_quota.decision("cid-vox", VOCE, 1.00, job_grande)
    assert d["total_eur"] == dec["due_eur"]
    assert d["is_free"] == dec["is_free"]
```

- [ ] **Step 2: Lancia i test e verifica che falliscano**

```
python -m pytest test/test_voxcpm_pricing_api.py -q
```

Atteso: FAIL — `KeyError: 'voxcpm_eur'` sulla stima, e `200` invece di `400`
sull'anteprima.

- [ ] **Step 3: Importa il predicato e dai al motore il suo cap**

Riga 515 di `audiobook_app.py`, accanto agli altri due:

```python
from voice_utils import is_voxcpm_voice as _is_voxcpm_voice
```

Accanto a `MAX_SPEECHIFY_TEXT_CHARS`, dove sono definiti gli altri cap:

```python
# Cap caratteri VoxCPM. Allineato a quello Speechify: il limite non e' del
# motore ma del portafoglio dell'utente e del tempo di attesa.
MAX_VOXCPM_TEXT_CHARS = int(os.environ.get("ABM_MAX_VOXCPM_TEXT_CHARS",
                                           str(MAX_SPEECHIFY_TEXT_CHARS)))
```

e in `_max_text_chars_for_voice`, prima del ramo Speechify:

```python
    if _is_voxcpm_voice(voice):
        return MAX_VOXCPM_TEXT_CHARS
```

- [ ] **Step 4: Metti il prezzo dentro `api_combined_estimate`**

Subito dopo il blocco `speechify_eur` (che finisce con la chiusura di
`speechify_breakdown`):

```python
    voxcpm_eur = 0.0
    voxcpm_breakdown = {}
    if _is_voxcpm_voice(voice_id):
        try:
            est_vox = voxcpm_tts.estimate_book_cost(chs, language=lang)
        except Exception as e:
            return jsonify({"error": f"estimate failed: {e}"}), 500
        voxcpm_eur = round(est_vox["user_price_eur"], 2)
        _premium_list_eur = round(est_vox.get("list_price_eur", 0.0), 2)
        voxcpm_breakdown = {
            "chars": est_vox["chars_total"],
            "chars_total": est_vox["chars_total"],
            "user_price_eur": est_vox["user_price_eur"],
            "is_free": est_vox["is_free"],
            "model_label": est_vox["model_label"],
            # Il costo GPU misurato (§8.3) viaggia con la stima perche' e'
            # quello che l'audit del Task 11 confronta col listino.
            "cost_usd": est_vox["cost_usd"],
        }
```

La riga di `_has_premium` diventa:

```python
    _has_premium = (_is_gemini_voice(voice_id) or _is_speechify_voice(voice_id)
                    or _is_voxcpm_voice(voice_id))
```

Il totale:

```python
    total = round(gemini_eur + speechify_eur + voxcpm_eur + llm_eur, 2)
```

La catena delle soglie prende il suo primo ramo:

```python
    if _is_voxcpm_voice(voice_id):
        threshold = free_quota._premium_threshold_eur(voice_id)
    elif _is_speechify_voice(voice_id):
```

Si legge da `free_quota` e non da `os.environ` di proposito: è il punto dove
l'incidente «402 Speechify» è nato, e una seconda lettura della stessa
variabile è esattamente il modo in cui le due si separano nel tempo. Gli
altri due rami restano come sono — questo task non li tocca.

E nel `jsonify` finale, accanto agli omologhi:

```python
        "voxcpm_eur": voxcpm_eur,
        "voxcpm_breakdown": voxcpm_breakdown,
```

- [ ] **Step 5: Metti il prezzo dentro l'ordine PayPal**

In `api_paypal_create_order_gemini`, dopo il blocco `speechify_eur` (riga
~12279):

```python
    voxcpm_eur = 0.0
    if _is_voxcpm_voice(voice_id):
        try:
            est = voxcpm_tts.estimate_book_cost(chs, language="it")
        except Exception as e:
            return jsonify({"error": f"estimate failed: {e}"}), 500
        voxcpm_eur = round(est["user_price_eur"], 2)
        _premium_list_eur = round(est.get("list_price_eur", 0.0), 2)
```

`_has_premium` prende lo stesso terzo ramo dello Step 4, e ovunque la somma
`gemini_eur + speechify_eur` compaia in questa funzione va aggiunto
`+ voxcpm_eur`. Il confronto server-side con `amount_eur` non cambia forma:
cambia solo il numero che gli si mette davanti.

- [ ] **Step 6: Guardia di configurazione e addebito in `/api/generate`**

Accanto alle due guardie esistenti (riga ~9828):

```python
    if _is_voxcpm_voice(voice):
        if voxcpm_tts is None or not voxcpm_tts.is_available():
            return jsonify({"error": "voxcpm_not_configured"}), 400
```

E la condizione del ramo di addebito premium a riga ~10221 si allarga:

```python
    if _is_speechify_voice(voice) or _is_voxcpm_voice(voice):
```

Aggiungi sopra quel ramo, al commento che già lo descrive come «specchio
LEAN», questa riga:

```python
    # VoxCPM entra qui e non in un terzo ramo: il percorso e' identico —
    # stessa tasca job["payment"], stesso gate soglia/consumo token, nessun
    # budget Google e nessun preflight RPD da rilasciare. Duplicare le
    # novanta righe una terza volta darebbe tre copie da tenere allineate su
    # un percorso di pagamento.
```

- [ ] **Step 7: Enforcement dell'ottimizzazione combinata**

A riga ~12507, accanto a `_is_combined_speechify`:

```python
    # Stessa ragione del ramo Speechify sopra: il flusso auto_generate chiama
    # run_generation direttamente e salta il preflight di /api/generate. Senza
    # questo, un audiolibro VoxCPM col costo LLM sotto soglia uscirebbe senza
    # incassare la quota TTS.
    _is_combined_voxcpm = (auto_generate
                           and _is_voxcpm_voice(data.get("voice", ""))
                           and voxcpm_tts is not None
                           and voxcpm_tts.is_available())
```

e la condizione sotto:

```python
    if (estimated_cost > LLM_FREE_THRESHOLD_EUR
            and not _is_combined_gemini and not _is_combined_speechify
            and not _is_combined_voxcpm):
```

- [ ] **Step 8: Chiudi l'anteprima**

In `api_preview`, subito dopo la lettura di `voice` e prima di qualunque
sintesi:

```python
    if _is_voxcpm_voice(voice):
        # §5.2: per VoxCPM l'anteprima e' sostituita dall'ascolto del campione
        # (/api/voice_sample). Un'anteprima costerebbe l'accensione di un
        # worker — circa tre minuti e il prezzo di un capitolo — per pochi
        # secondi di audio. Il rifiuto esplicito serve anche a non far cadere
        # la voce nel ramo Edge, che la leggerebbe con un'altra voce.
        return jsonify({"error": "voxcpm_preview_unsupported"}), 400
```

- [ ] **Step 9: Lancia i test e verifica che passino**

```
python -m pytest test/test_voxcpm_pricing_api.py -q
```

Atteso: PASS, 12 test.

- [ ] **Step 10: Verifica che i percorsi di pagamento esistenti reggano**

Questo task tocca stima, ordine e addebito: la prova che Gemini e Speechify
non si siano mossi è la suite intera dei pagamenti.

```
python -m pytest test/ -q -k "quota or payment or paypal or estimate or premium"
```

Atteso: nessun test rotto.

- [ ] **Step 11: Documenta la variabile**

In `md_files/PARAMETRI_CONFIGURAZIONE.md`:

```
| `ABM_MAX_VOXCPM_TEXT_CHARS` | come `ABM_MAX_SPEECHIFY_TEXT_CHARS` | Cap caratteri per un libro con voce VoxCPM. |
```

- [ ] **Step 12: Commit**

```
git add audiobook_app.py test/test_voxcpm_pricing_api.py
git add -f md_files/PARAMETRI_CONFIGURAZIONE.md
git commit -m "feat(voxcpm): un solo punto di decisione per il prezzo, anche per il terzo motore"
```

---

### Task 11: Il costo reale, job per job

§8.4 chiede una scheda VoxCPM in `/admin/audit-premium` accanto a Gemini e
Speechify. Non serve un modulo nuovo: Speechify non ne ha uno. Scrive nello
stesso JSONL mensile di `gemini_cost_audit.py` con `provider: "speechify"`, e
il commento di `_write_speechify_audit` spiega perché il costo provider va nel
campo che si chiama `google_cost_eur_actual` — l'aggregato è
provider-agnostico e quel campo, malgrado il nome, significa «costo vivo».
VoxCPM diventa il terzo `provider`, e la scheda esce dai filtri che già ci
sono.

Il numero che l'audit confronta col listino, qui, non è una fattura: è tempo
di GPU. Il worker rendiconta `tts_seconds` e `chars` per job, e il costo
misurato del §8.3 — $0,91 per milione di caratteri su RTX 4090 — li traduce
in euro. È una stima ancorata a una misura, non un estratto conto, e il
record lo dichiara scrivendo anche i secondi di GPU: se un giorno il prezzo
della scheda cambia, l'audit storico si ricalcola senza rigenerare nulla.

Questo task chiude anche il rimborso. Un job VoxCPM fallito deve pescare dalla
tasca premium `job["payment"]` — quella di `_refund_gemini_payment` — e non
dalla tasca dell'ottimizzazione: sono i due `if use_speechify:` che nel codice
scelgono fra `_refund_gemini_payment` e `_refund_job_payment`.

**Files:**
- Modify: `generation_engine.py:~4470` (accumulo di `job["voxcpm_actual"]`),
  `:3466` (dopo `_write_speechify_audit`, la funzione nuova), `:5416-5427`
  (rimborso e audit su tutti i chunk falliti), `:5488-5497` (rimborso e audit
  su output vuoto), `:5561-5564` (audit a fine corsa)
- Modify: `audiobook_app.py:3771`, `:3998` (conteggi premium delle sessioni),
  `:6854-6860` (scheda dei job premium in volo)
- Test: `test/test_voxcpm_audit.py`

**Interfaces:**
- Consumes: dal Task 4 — `voxcpm_tts.compute_user_price_eur()`,
  `cost_usd_per_mchar()`; dal Task 9 — il dizionario di ritorno di
  `_voxcpm_pre_pass`.
- Produces:
  - `job["voxcpm_actual"] = {"chars", "audio_seconds", "tts_seconds", "jobs",
    "redone", "bounced", "failed_chunks"}`.
  - `generation_engine._write_voxcpm_audit(job_id, job, voice_id, language,
    outcome)`, stessa firma dei due omologhi.
  - Record di audit con `provider == "voxcpm"` e `model_key == "v2"`, letti
    dagli endpoint `/admin/api/gemini_cost_audit*` senza modifiche.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_voxcpm_audit.py`:

```python
"""Il record di audit di un job VoxCPM.

Il costo qui e' tempo di GPU, non una fattura: si verifica che finisca nel
campo che l'aggregato legge come costo vivo, e che i secondi di GPU restino
scritti per poter ricalcolare domani.
"""
import json
import os

import pytest

import generation_engine
import gemini_cost_audit

VOCE = "voxcpm:v2:it-IT/Stefano"


@pytest.fixture
def audit_isolato(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "4.00")
    monkeypatch.setenv("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.50")
    return tmp_path


def leggi(dir_dati):
    righe = []
    for fp in sorted(dir_dati.glob("gemini_cost_audit_*.jsonl")):
        with open(fp, encoding="utf-8") as f:
            righe.extend(json.loads(r) for r in f if r.strip())
    return righe


def job_finito(charged=1.00):
    return {
        "voxcpm_actual": {"chars": 250_000, "audio_seconds": 9000.0,
                          "tts_seconds": 315.0, "jobs": 12, "redone": 1,
                          "bounced": 3, "failed_chunks": 0},
        "payment": {"total_eur": charged, "method": "paypal",
                    "source": "order", "token": "tok-1234567890"},
        "rate": "+0%",
    }


def test_il_record_dichiara_il_provider(audit_isolato):
    generation_engine._write_voxcpm_audit("job-1", job_finito(), VOCE, "it",
                                          "completed")
    r = leggi(audit_isolato)[0]
    assert r["provider"] == "voxcpm"
    assert r["model_key"] == "v2"
    assert r["outcome"] == "completed"
    assert r["language"] == "it"


def test_il_costo_gpu_va_nel_campo_del_costo_vivo(audit_isolato):
    # 250.000 caratteri a $0,91/Mchar = $0,2275, convertiti in EUR.
    r = generation_engine._write_voxcpm_audit("job-1", job_finito(), VOCE,
                                              "it", "completed") or leggi(audit_isolato)[0]
    r = leggi(audit_isolato)[0]
    assert 0.15 < r["google_cost_eur_actual"] < 0.25
    assert r["user_price_eur_charged"] == 1.00
    assert r["margin_eur_actual"] == round(1.00 - r["google_cost_eur_actual"], 4)


def test_i_secondi_di_gpu_restano_scritti(audit_isolato):
    # Il costo e' una stima ancorata a una misura: se il prezzo della scheda
    # cambia, l'audit storico si ricalcola solo se i secondi ci sono.
    generation_engine._write_voxcpm_audit("job-1", job_finito(), VOCE, "it",
                                          "completed")
    r = leggi(audit_isolato)[0]
    assert r["gpu_seconds"] == 315.0
    assert r["cost_usd_per_mchar"] == 0.91
    assert r["worker_jobs"] == 12
    assert r["worker_bounced"] == 3


def test_il_dovuto_si_ricalcola_dai_caratteri_reali(audit_isolato):
    generation_engine._write_voxcpm_audit("job-1", job_finito(charged=0.40),
                                          VOCE, "it", "completed")
    r = leggi(audit_isolato)[0]
    assert r["user_price_eur_should_have_been"] == 1.00
    assert r["delta_eur"] == 0.60      # 1,00 dovuto - 0,40 incassato


def test_una_voce_di_un_altro_motore_non_scrive_nulla(audit_isolato):
    generation_engine._write_voxcpm_audit("job-1", job_finito(),
                                          "speechify:simba-3.2:harper_32",
                                          "en", "completed")
    assert leggi(audit_isolato) == []


def test_un_job_senza_misure_non_solleva(audit_isolato):
    # Best-effort e non fatale, come i due omologhi: un audit che esplode non
    # deve portarsi via un audiolibro gia' consegnato.
    generation_engine._write_voxcpm_audit("job-1", {}, VOCE, "it",
                                          "failed_no_output_refunded")
    r = leggi(audit_isolato)[0]
    assert r["chars_total"] == 0
    assert r["google_cost_eur_actual"] == 0.0


def test_l_aggregato_vede_i_record_voxcpm(audit_isolato):
    generation_engine._write_voxcpm_audit("job-1", job_finito(), VOCE, "it",
                                          "completed")
    a = gemini_cost_audit.aggregate(model="v2")
    assert a["count"] == 1
    assert a["revenue_eur"] == 1.00
    assert a["margin_eur"] > 0.7


def test_un_job_gratis_sopra_soglia_lascia_traccia(audit_isolato, capsys):
    # Stessa vigilanza del ramo Speechify: un job completato sopra soglia con
    # zero incassato e' un margine negativo che qualcuno deve vedere.
    generation_engine._write_voxcpm_audit("job-1", job_finito(charged=0.0),
                                          VOCE, "it", "completed")
    assert "AUDIT WARNING" in capsys.readouterr().out
```

- [ ] **Step 2: Lancia i test e verifica che falliscano**

```
python -m pytest test/test_voxcpm_audit.py -q
```

Atteso: FAIL —
`AttributeError: module 'generation_engine' has no attribute '_write_voxcpm_audit'`.

- [ ] **Step 3: Accumula le misure reali durante la generazione**

In `run_generation`, subito dopo la chiamata a `_voxcpm_pre_pass` aggiunta dal
Task 9:

```python
            # Misure reali del worker, sommate sui capitoli: e' la base
            # dell'audit (§8.4). Solo i chunk di testa portano numeri; quelli
            # di coda hanno esiti a zero e sommarli e' innocuo.
            job["voxcpm_actual"] = {
                "chars": sum(int(v.get("chars", 0) or 0) for v in _voxcpm_pre.values()),
                "audio_seconds": round(sum(float(v.get("audio_seconds", 0) or 0)
                                           for v in _voxcpm_pre.values()), 2),
                "tts_seconds": round(sum(float(v.get("tts_seconds", 0) or 0)
                                         for v in _voxcpm_pre.values()), 2),
                "jobs": sum(int(v.get("jobs", 0) or 0) for v in _voxcpm_pre.values()),
                "redone": sum(int(v.get("redone", 0) or 0) for v in _voxcpm_pre.values()),
                "bounced": sum(int(v.get("bounced", 0) or 0) for v in _voxcpm_pre.values()),
                "failed_chunks": sum(int(v.get("failed_chunks", 0) or 0)
                                     for v in _voxcpm_pre.values()),
            }
```

- [ ] **Step 4: Scrivi il writer dell'audit**

Subito dopo `_write_speechify_audit` in `generation_engine.py`:

```python
def _write_voxcpm_audit(job_id, job, voice_id, language, outcome):
    """Append audit record al termine di un job VoxCPM. Best-effort, non fatale.

    Terzo `provider` dello stesso JSONL mensile: l'aggregato di
    `gemini_cost_audit` e' provider-agnostico e non va toccato. Il costo vivo
    va in `google_cost_eur_actual` per la stessa ragione per cui ce lo mette
    Speechify — il nome del campo e' storico, il significato e' "costo
    sostenuto dal backend".

    Qui pero' quel costo non e' una fattura ma tempo di GPU stimato dai
    caratteri col valore misurato del §8.3. Il record porta percio' anche
    `gpu_seconds` e `cost_usd_per_mchar`: se domani cambia il prezzo della
    scheda, l'audit storico si ricalcola senza rigenerare nulla.
    """
    try:
        if not _is_voxcpm_voice(voice_id):
            return
        actual = job.get("voxcpm_actual") or {}
        # --- Pagamento: stessa tasca premium job["payment"] degli altri due ---
        payment = job.get("payment") or {}
        charged = float(payment.get("total_eur", 0) or 0)
        payment_method = payment.get("method", "") or ""
        payment_source = payment.get("source", "") or ""
        payment_token_full = payment.get("token", "") or ""
        if charged <= 0:
            _legacy_amt = float(job.get("payment_amount_eur", 0) or 0)
            if _legacy_amt > 0:
                charged = _legacy_amt
                payment_method = job.get("payment_type", "") or payment_method
                payment_token_full = job.get("payment_token", "") or payment_token_full
                payment_source = payment_source or "legacy_fallback"
        payment_token_short = ((payment_token_full[:8] + "...")
                               if len(payment_token_full) > 12
                               else payment_token_full)
        _llm_quota = payment.get("llm_eur")
        _combined_total_eur = (round(charged + float(_llm_quota or 0), 4)
                               if _llm_quota is not None else round(charged, 4))

        # --- Costo GPU + prezzo "dovuto" sui caratteri effettivamente letti ---
        chars = int(actual.get("chars", 0) or 0)
        gpu_seconds = round(float(actual.get("tts_seconds", 0) or 0), 2)
        provider_cost_eur = 0.0
        should_have_been = 0.0
        cost_usd_mchar = 0.0
        try:
            price = voxcpm_tts.compute_user_price_eur(chars)
            cost_usd_mchar = voxcpm_tts.cost_usd_per_mchar()
            provider_cost_eur = float(price.get("cost_usd", 0.0) or 0.0) * float(
                speechify_tts.usd_eur_rate())
            should_have_been = float(price.get("user_price_eur", 0.0) or 0.0)
        except Exception:
            provider_cost_eur = 0.0
            should_have_been = 0.0
        delta_eur = round(should_have_been - charged, 4)
        delta_pct = (round((delta_eur / provider_cost_eur * 100), 2)
                     if provider_cost_eur > 0 else 0.0)
        rate_raw = job.get("rate", "+0%")
        try:
            rate_pct_val = int(str(rate_raw).replace("%", "").replace("+", "").strip() or 0)
        except (TypeError, ValueError):
            rate_pct_val = 0

        rec = {
            "job_id": job_id,
            "provider": "voxcpm",
            "model_key": "v2",
            "language": language or "",
            "rate_pct": rate_pct_val,
            "rate_step": max(-3, min(3, round(rate_pct_val / 10.0))),
            "chars_total": chars,
            "billable_chars": chars,
            "input_tokens_est": 0,
            "input_tokens_actual": 0,
            "output_tokens_est": 0,
            "output_tokens_actual": 0,
            "audio_seconds_est": 0.0,
            "audio_seconds_actual": round(float(actual.get("audio_seconds", 0) or 0), 2),
            "google_cost_eur_est": 0.0,
            "google_cost_eur_actual": round(provider_cost_eur, 4),
            "user_price_eur_charged": charged,
            "user_price_eur_should_have_been": round(should_have_been, 2),
            "delta_eur": delta_eur,
            "delta_pct": delta_pct,
            "margin_eur_actual": round(charged - provider_cost_eur, 4),
            "combined_total_eur": _combined_total_eur,
            "outcome": outcome,
            "payment_method": payment_method,
            "payment_token_short": payment_token_short,
            "payment_source": payment_source,
            # Specifici di VoxCPM: la base per ricalcolare, e la salute del
            # worker (rimbalzi e capitoli rifatti) accanto al costo.
            "gpu_seconds": gpu_seconds,
            "cost_usd_per_mchar": cost_usd_mchar,
            "worker_jobs": int(actual.get("jobs", 0) or 0),
            "worker_redone": int(actual.get("redone", 0) or 0),
            "worker_bounced": int(actual.get("bounced", 0) or 0),
            "worker_failed_chunks": int(actual.get("failed_chunks", 0) or 0),
        }
        _reused_n = int(job.get("chunks_reused", 0) or 0)
        if _reused_n:
            rec["chunks_reused"] = _reused_n
        _cancel_meta = job.get("cancel_meta")
        if isinstance(_cancel_meta, dict):
            rec["cancel_paid_eur"] = round(float(_cancel_meta.get("paid_eur", 0) or 0), 2)
            rec["cancel_retained_eur"] = round(float(_cancel_meta.get("retained_eur", 0) or 0), 2)
            rec["cancel_refund_eur"] = round(float(_cancel_meta.get("refund_eur", 0) or 0), 2)
            rec["cancel_progress_pct"] = int(_cancel_meta.get("progress_pct", 0) or 0)
            rec["cancel_partial_audio_delivered"] = bool(
                _cancel_meta.get("partial_audio_delivered", False))
        gemini_cost_audit.append_record(rec)
        try:
            _free_thr = float(os.environ.get("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.50"))
        except (TypeError, ValueError):
            _free_thr = 0.50
        if outcome == "completed" and charged <= 0.0 and should_have_been > _free_thr:
            print(f"[{job_id}] AUDIT WARNING: completed VoxCPM job sopra soglia "
                  f"({should_have_been:.2f}€) senza pagamento registrato "
                  f"(payment_method={payment_method or 'NONE'}).")
    except Exception as e:
        print(f"[{job_id}] voxcpm audit write failed (non-fatal): {e}")
```

`speechify_tts.usd_eur_rate()` è riusata di proposito: il tasso di cambio è
del portafoglio, non del motore, e averne due che divergono renderebbe i due
audit non confrontabili.

- [ ] **Step 5: Chiama il writer e rimborsa dalla tasca giusta**

Tre punti, tutti già scritti per Speechify. Alla riga ~5416:

```python
                if use_speechify or use_voxcpm:
                    _refund_gemini_payment(job_id, job, f"all_chunks_failed: {failed_chunks}/{_tot_chunks_safe}")
```

e subito sotto:

```python
            if use_voxcpm:
                try:
                    _write_voxcpm_audit(job_id, job, voice,
                                        _audit_language(job, info),
                                        "failed_all_chunks_refunded")
                except Exception:
                    pass
```

Alla riga ~5488, accanto al ramo `elif use_speechify:` dell'output vuoto:

```python
            elif use_voxcpm:
                # Premium: rimborso sulla tasca job["payment"], come Speechify.
                try:
                    _write_voxcpm_audit(job_id, job, voice,
                                        _audit_language(job, info),
                                        "failed_no_output_refunded")
                except Exception:
                    pass
                try:
                    _refund_gemini_payment(job_id, job, "no_output: assembly failed")
                except Exception as _ref_err:
                    print(f"[{job_id}] Refund failed (non-fatal): {_ref_err}")
```

E a fine corsa, riga ~5563:

```python
        elif use_voxcpm:
            _write_voxcpm_audit(job_id, job, voice, _audit_language(job, info), "completed")
```

- [ ] **Step 6: Fai vedere VoxCPM al pannello admin**

Tre conteggi in `audiobook_app.py` che oggi dicono «premium» intendendo due
motori. Riga ~3771:

```python
            _is_gemini_voice(s.get("voice", ""))
            or _is_speechify_voice(s.get("voice", ""))
            or _is_voxcpm_voice(s.get("voice", ""))
```

Riga ~3998:

```python
                and (_is_gemini_voice(voice_raw) or _is_speechify_voice(voice_raw)
                     or _is_voxcpm_voice(voice_raw))
```

Riga ~6854, nella scheda dei job premium in volo:

```python
            is_gem = _is_gemini_voice(voice)
            is_spe = _is_speechify_voice(voice)
            is_vox = _is_voxcpm_voice(voice)
            if not (is_gem or is_spe or is_vox):
                continue
```

Il `model_key` che quella funzione ricava da `voice.split(":")[1]` vale già
`"v2"` per gli id VoxCPM, e coincide con quello scritto nel record: il filtro
per modello del pannello funziona senza altro lavoro.

- [ ] **Step 7: Lancia i test e verifica che passino**

```
python -m pytest test/test_voxcpm_audit.py -q
```

Atteso: PASS, 8 test.

- [ ] **Step 8: Verifica che l'audit esistente non si sia mosso**

```
python -m pytest test/ -q -k "audit"
```

Atteso: nessun test rotto. I record Gemini e Speechify hanno campi in meno
rispetto a quelli VoxCPM, ma l'aggregato legge per chiave con default: un
campo in più non li disturba.

- [ ] **Step 9: Commit**

```
git add generation_engine.py audiobook_app.py test/test_voxcpm_audit.py
git commit -m "feat(voxcpm): il costo e' tempo di GPU, e l'audit lo scrive con i suoi secondi"
```

---

### Task 12: Il pannello Impostazioni audio

Il principio del §5.1 in una riga: con Gemini e Simba i menù sono **manopole
del motore**, con VoxCPM sono **filtri su un catalogo**. L'utente vede la
stessa griglia e fa gli stessi gesti; cambia solo cosa succede dietro. Per
questo il tab premium non prende un layout dedicato: prende un terzo ramo
accanto a quello Gemini e a quello Simba, dentro le funzioni che già
esistono.

Tre cose vanno capite prima di scrivere il codice.

**ACCENTO diventa un filtro vero.** Per Gemini è una direttiva di stile
(«leggi con accento britannico»), per VoxCPM è la variante di locale della
voce: `en-GB` e `en-US` sono voci diverse, non la stessa voce con
un'istruzione. La riga del DOM è la stessa (`geminiAccentRow`), come già fa
Simba; a cambiare è chi la riempie e cosa filtra.

**CARATTERE filtra le voci, ma non è simmetrico.** §5.3: nel catalogo ogni
voce ha esattamente un carattere, perché il carattere è inciso nel campione
da cui il modello clona. Quindi *carattere → voci* restringe davvero, mentre
*voce → caratteri* restituisce sempre uno. Il comportamento definito dalla
spec, e da implementare alla lettera: il menù CARATTERE filtra la lista VOCE;
alla selezione di una voce, CARATTERE si allinea al valore di quella voce e
resta visibile come informazione; **nessuno dei due campi si svuota mai**. Un
menù che si svuotasse fingerebbe di offrire un'alternativa che non esiste.

**L'anteprima sparisce, il campione la sostituisce.** Il Task 10 ha già
chiuso `/api/preview` per le voci VoxCPM. Qui si nasconde il bottone e si
mostra al suo posto il player del `.wav` di riferimento — quello da cui la
voce viene clonata, cioè esattamente come suonerà.

E una cosa che si applica a tutto il task: **niente elenchi cablati**. I
caratteri, i locali e le lingue arrivano da `/api/voices`, mai da una
costante nel JavaScript. È la D10, ed è la ragione per cui `_SPEECHIFY_ACCENTS`
non ha un gemello VoxCPM.

**Files:**
- Modify: `templates/_fragments/html_head.html:420-446` (le righe del tab
  premium), `:490-503` (la sezione anteprima)
- Modify: `static/js/app.js:1078-1108` (`updModelsPremium`), `:1124-1147`
  (`_isSpeechifyModelSelected`, `_onPremiumModelChanged`), `:1183-1245`
  (il ramo di `updVoicesPremium`), `:1967-1975` (`_updatePreviewBtn`), più le
  funzioni nuove accanto a quelle Speechify
- Test: `test/test_voxcpm_frontend_assets.py`

**Interfaces:**
- Consumes: dal Task 8 — `voices["_voxcpm"] = {available, model_label,
  personas}` e le entry con `engine: "voxcpm"`, `locale`, `persona`,
  `sample_url`.
- Produces (chiavi i18n usate qui, tradotte nel Task 13):
  `lbl_model_voxcpm`, `lbl_character`, `character_all`, `voxcpm_sample_title`,
  `voxcpm_sample_hint`, `persona_*`.
- Produces (JS, usati dal Task 13): `_isVoxcpmVoiceId(id)`,
  `_isVoxcpmModelSelected()`, `_voxcpmPersonaLabel(chiave)`.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_voxcpm_frontend_assets.py`, sulla falsariga di
`test_speechify_frontend_assets.py`: asserzioni statiche sul sorgente, che è
la convenzione del progetto per il frontend.

```python
"""Il tab premium sa di VoxCPM: markup, filtri, campione al posto dell'anteprima.

Asserzioni statiche sul sorgente, come test_speechify_frontend_assets.py: nel
progetto non c'e' un runner JS, e questi test difendono la presenza dei
meccanismi, non il loro comportamento a runtime.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates/_fragments/html_head.html").read_text(encoding="utf-8")
JS = (ROOT / "static/js/app.js").read_text(encoding="utf-8")


def test_il_markup_ha_carattere_e_campione():
    assert 'id="voxcpmCharacterRow"' in HTML
    assert 'id="voxcpmCharacter"' in HTML
    assert 'id="voxcpmSampleRow"' in HTML
    assert 'id="voxcpmSample"' in HTML


def test_carattere_precede_la_voce_nel_markup():
    # CARATTERE filtra VOCE: nell'ordine di lettura il filtro viene prima
    # della cosa filtrata, come gia' l'accento per Simba.
    i_car = HTML.find('id="voxcpmCharacterRow"')
    i_voce = HTML.find('id="vvPremium"')
    assert i_car != -1 and i_voce != -1 and i_car < i_voce


def test_il_campione_e_un_player_non_un_bottone():
    # §5.2: si ascolta un file che esiste gia', non si genera nulla.
    i = HTML.find('id="voxcpmSampleRow"')
    blocco = HTML[i:i + 600]
    assert "<audio" in blocco
    assert "onclick" not in blocco


def test_il_modello_compare_fra_i_premium():
    assert "lbl_model_voxcpm" in JS
    assert "updModelsPremium" in JS
    assert "_isVoxcpmModelSelected" in JS
    assert "_isVoxcpmVoiceId" in JS


def test_il_modello_dipende_dalla_disponibilita_del_motore():
    # Motore non configurato -> nessuna voce e nessun modello: la stessa
    # regola per cui Simba compare solo se il catalogo espone voci speechify.
    assert "_voxcpm" in JS
    assert "voxcpm:" in JS


def test_i_caratteri_arrivano_dal_catalogo():
    # D10: un carattere nuovo non deve richiedere un rilascio. Se comparisse
    # un array di caratteri nel sorgente, sarebbe la firma dell'errore.
    assert "personas" in JS
    for cablato in ("audiobook-slow", "grave-narrator", "warm-pro",
                    "neutral-pro", "casual-drawl"):
        assert cablato not in JS, f"carattere cablato nel sorgente: {cablato}"


def test_i_locali_voxcpm_arrivano_dal_catalogo():
    # Idem per gli accenti: nessun gemello di _SPEECHIFY_ACCENTS.
    assert "_VOXCPM_ACCENTS" not in JS
    assert "_populateVoxcpmAccents" in JS


def test_la_selezione_sopravvive_ai_rebuild():
    # Stessa ragione documentata per _speechifyVoiceSel: il dropdown si
    # ricostruisce a ogni cambio di tab/modello e senza una fonte di verita'
    # fuori dal DOM la scelta dell'utente si perde.
    for nome in ("_voxcpmAccentSel", "_voxcpmVoiceSel", "_voxcpmCharacterSel"):
        assert nome in JS


def test_carattere_si_allinea_alla_voce_e_non_si_svuota():
    # §5.3: alla selezione di una voce, CARATTERE mostra il valore di quella
    # voce. E' un'etichetta, non un'alternativa.
    assert "_syncVoxcpmCharacterToVoice" in JS


def test_l_anteprima_lascia_il_posto_al_campione():
    assert "voxcpmSampleRow" in JS
    assert "sample_url" in JS
    # Il bottone anteprima non deve restare attivo su una voce VoxCPM: il
    # backend la respinge con 400 (Task 10) e l'utente vedrebbe un errore.
    i = JS.find("function _updatePreviewBtn")
    assert "_isVoxcpmVoiceId" in JS[i:i + 700]
```

- [ ] **Step 2: Lancia i test e verifica che falliscano**

```
python -m pytest test/test_voxcpm_frontend_assets.py -q
```

Atteso: FAIL — `assert 'id="voxcpmCharacterRow"' in HTML`.

- [ ] **Step 3: Aggiungi le righe al markup**

In `templates/_fragments/html_head.html`, fra `geminiAccentRow` e la riga
della voce (così CARATTERE, che filtra, precede VOCE, che è filtrata):

```html
        <div class="form-row" id="voxcpmCharacterRow" hidden>
          <div class="form-group" style="flex:1 1 100%">
            <label for="voxcpmCharacter" data-t="lbl_character">Carattere</label>
            <select id="voxcpmCharacter"></select>
          </div>
        </div>
```

E dopo la riga dell'emozione Simba, la sezione del campione:

```html
        <div class="form-row" id="voxcpmSampleRow" hidden>
          <div class="form-group" style="flex:1 1 100%">
            <label data-t="voxcpm_sample_title">Ascolta la voce</label>
            <audio id="voxcpmSample" controls preload="none"></audio>
            <div class="model-rate-hint" data-t="voxcpm_sample_hint">
              Il campione da cui la voce viene clonata: il libro suonerà così.
            </div>
          </div>
        </div>
```

`preload="none"` non è un dettaglio: il pannello può mostrare decine di voci
e caricare il `.wav` di ognuna al primo render sprecherebbe banda per audio
che nessuno ascolterà.

- [ ] **Step 4: Riconosci il motore lato client**

In `static/js/app.js`, accanto a `_isSpeechifyModelSelected`:

```javascript
function _isVoxcpmVoiceId(id){return typeof id==='string'&&id.indexOf('voxcpm:')===0;}

function _isVoxcpmModelSelected(){
  const vm=document.getElementById('vmPremium');
  return !!(vm&&vm.value==='voxcpm');
}

// Selezioni VoxCPM persistite fuori dal DOM. Stessa ragione documentata per
// _speechifyAccentSel/_speechifyVoiceSel: i dropdown si ricostruiscono a ogni
// cambio di tab, modello o lingua, e senza una fonte di verita' esterna la
// scelta dell'utente si perde a ogni rebuild.
let _voxcpmAccentSel='';
let _voxcpmVoiceSel='';
let _voxcpmCharacterSel='';   // '' = tutti i caratteri
```

- [ ] **Step 5: Metti il modello fra i premium**

In `updModelsPremium`, dopo il blocco `if(isEnglish){...}` di Simba:

```javascript
  // VoxCPM2: presente in ogni lingua per cui il catalogo espone voci. A
  // differenza di Simba non e' legato all'inglese, e a differenza di Gemini
  // non e' sempre presente: se il motore non e' configurato, /api/voices non
  // manda ne' le voci ne' _voxcpm.available, e il modello non compare.
  const _voxStatus=(voices&&voices._voxcpm)||null;
  const _langData=voices&&voices[lang];
  const _hasVox=!!(_voxStatus&&_voxStatus.available
                   &&_langData&&Array.isArray(_langData.voices)
                   &&_langData.voices.some(v=>v&&_isVoxcpmVoiceId(v.id)));
  if(_hasVox){
    addOpt('voxcpm',t('lbl_model_voxcpm')||'VoxCPM2 · La tua voce');
  }
```

Il default non cambia: la riga `if(isEnglish && ...simba...)` resta la prima
scelta e `prev` continua a vincere quando è ancora valido. VoxCPM si
seleziona, non si impone.

- [ ] **Step 6: Mostra e nascondi le righe giuste**

In `_onPremiumModelChanged`, sostituisci il corpo con questa versione a tre
rami. Le due righe che c'erano continuano a fare quello che facevano:

```javascript
function _onPremiumModelChanged(){
  const styleRow=document.getElementById('geminiStyleRow');
  const emoRow=document.getElementById('speechifyEmotionRow');
  const accentRow=document.getElementById('geminiAccentRow');
  const carRow=document.getElementById('voxcpmCharacterRow');
  const sampleRow=document.getElementById('voxcpmSampleRow');
  const simba=_isSpeechifyModelSelected();
  const vox=_isVoxcpmModelSelected();
  // Istruzioni di stile: solo Gemini. Emozione: solo Simba. Carattere e
  // campione: solo VoxCPM.
  if(styleRow)styleRow.hidden=simba||vox;
  if(emoRow)emoRow.hidden=!simba;
  if(carRow)carRow.hidden=!vox;
  if(sampleRow)sampleRow.hidden=!vox;
  if(vox){
    _populateVoxcpmAccents();
    _populateVoxcpmCharacters();
    if(accentRow)accentRow.hidden=false;
  }else if(simba){
    _populateSpeechifyAccents();
    _populateSpeechifyEmotions();
    if(accentRow)accentRow.hidden=false;
  }else{
    if(typeof _updateAccentDropdown==='function')_updateAccentDropdown();
  }
  updVoicesPremium();
  if(typeof _onPreviewParamsChanged==='function')_onPreviewParamsChanged();
}
```

- [ ] **Step 7: Riempi ACCENTO e CARATTERE dal catalogo**

Accanto a `_populateSpeechifyAccents`:

```javascript
// Le voci VoxCPM della lingua corrente, comunque filtrate. Sorgente unica
// dei tre dropdown: cosi' un accento o un carattere compaiono se e solo se
// esiste una voce che li porta.
function _voxcpmVoicesForLang(){
  const vlEl=document.getElementById('vlPremium');
  const lang=(vlEl&&vlEl.value)||'it';
  const d=voices&&voices[lang];
  const arr=(d&&Array.isArray(d.voices))?d.voices:[];
  return arr.filter(v=>v&&_isVoxcpmVoiceId(v.id));
}

function _populateVoxcpmAccents(){
  const acc=document.getElementById('geminiAccent');
  if(!acc)return;
  // I locali si ricavano dalle voci, non da una tabella: il catalogo e' una
  // variabile (D10) e una lingua puo' guadagnare varianti senza rilascio.
  const locali=[];
  for(const v of _voxcpmVoicesForLang()){
    if(v.locale&&locali.indexOf(v.locale)<0)locali.push(v.locale);
  }
  locali.sort();
  const prev=(locali.indexOf(_voxcpmAccentSel)>=0)?_voxcpmAccentSel:'';
  acc.innerHTML='';
  for(const loc of locali){
    const o=document.createElement('option');
    o.value=loc;
    o.textContent=_voxcpmLocaleLabel(loc);
    acc.appendChild(o);
  }
  acc.value=prev||(locali.length?locali[0]:'');
  _voxcpmAccentSel=acc.value;
  acc.onchange=()=>{
    _voxcpmAccentSel=acc.value;
    _populateVoxcpmCharacters();
    updVoicesPremium();
    if(typeof _onPreviewParamsChanged==='function')_onPreviewParamsChanged();
  };
}

function _populateVoxcpmCharacters(){
  const sel=document.getElementById('voxcpmCharacter');
  if(!sel)return;
  const loc=_voxcpmAccentSel;
  const chiavi=[];
  for(const v of _voxcpmVoicesForLang()){
    if(loc&&v.locale!==loc)continue;
    if(v.persona&&chiavi.indexOf(v.persona)<0)chiavi.push(v.persona);
  }
  chiavi.sort();
  const prev=(chiavi.indexOf(_voxcpmCharacterSel)>=0)?_voxcpmCharacterSel:'';
  sel.innerHTML='';
  // "Tutti" e' la prima voce e il default: CARATTERE e' un filtro, e un
  // filtro deve poter non filtrare.
  const tutti=document.createElement('option');
  tutti.value='';
  tutti.textContent=t('character_all')||'Tutti';
  sel.appendChild(tutti);
  for(const k of chiavi){
    const o=document.createElement('option');
    o.value=k;
    o.textContent=_voxcpmPersonaLabel(k);
    sel.appendChild(o);
  }
  sel.value=prev;
  _voxcpmCharacterSel=sel.value;
  sel.onchange=()=>{
    _voxcpmCharacterSel=sel.value;
    updVoicesPremium();
    if(typeof _onPreviewParamsChanged==='function')_onPreviewParamsChanged();
  };
}
```

`_voxcpmPersonaLabel` e `_voxcpmLocaleLabel` prendono la loro forma
definitiva nel Task 13. Perché il pannello funzioni anche eseguendo i task in
ordine, aggiungi qui queste versioni minime, che il Task 13 sostituirà con la
catena di ricadute completa:

```javascript
// Etichetta leggibile di un carattere. Il Task 13 la sostituisce con la
// catena dizionario -> stringhe del catalogo -> chiave.
// Nota su t(): quando non trova la chiave la restituisce tal quale, quindi
// il confronto con la chiave e' l'unico modo di sapere se ha tradotto.
function _voxcpmPersonaLabel(chiave){
  if(!chiave)return '';
  const k='persona_'+String(chiave).replace(/-/g,'_');
  const tradotta=t(k);
  return (tradotta&&tradotta!==k)?tradotta:chiave;
}

// Etichetta di un locale. Il Task 13 ci aggiunge Intl.DisplayNames; per ora
// il codice grezzo, che e' brutto ma non e' mai sbagliato.
function _voxcpmLocaleLabel(loc){
  if(!loc)return '';
  const k='accent_'+String(loc).toLowerCase().replace(/-/g,'_');
  const tradotta=t(k);
  return (tradotta&&tradotta!==k)?tradotta:loc;
}
```

- [ ] **Step 8: Aggiungi il ramo a `updVoicesPremium`**

Subito prima del ramo Simba, dentro `updVoicesPremium`:

```javascript
  // --- Ramo VoxCPM2: voci filtrate per lingua, locale (ACCENTO) e persona
  // (CARATTERE). Qui i menu' non compongono una richiesta al motore: sono
  // filtri su un catalogo (§5.1).
  if(vmEl&&vmEl.value==='voxcpm'){
    const loc=_voxcpmAccentSel;
    const car=_voxcpmCharacterSel;
    const lista=_voxcpmVoicesForLang().filter(v=>{
      if(loc&&v.locale!==loc)return false;
      if(car&&v.persona!==car)return false;
      return true;
    });
    const prevVoice=_voxcpmVoiceSel||sel.value;
    sel.innerHTML='';
    let lg='';
    for(const v of lista){
      if(v.gender!==lg){
        const g=document.createElement('optgroup');
        g.label=v.gender==='Female'?'♀':(v.gender==='Male'?'♂':'•');
        sel.appendChild(g);lg=v.gender;
      }
      const o=document.createElement('option');
      o.value=v.id;
      // Nome, genere e carattere sulla stessa riga (§5.2): il carattere e'
      // l'informazione che distingue due voci dello stesso genere.
      o.textContent=(v.gender_icon?v.gender_icon+' ':'')+(v.name||v.id.split('/').pop())
                    +' · '+_voxcpmPersonaLabel(v.persona);
      sel.lastElementChild.appendChild(o);
    }
    if(prevVoice&&Array.prototype.some.call(sel.options,o=>o.value===prevVoice))sel.value=prevVoice;
    _voxcpmVoiceSel=sel.value;
    _syncVoxcpmCharacterToVoice();
    _loadVoxcpmSample();
    sel.onchange=()=>{
      _voxcpmVoiceSel=sel.value;
      _syncVoxcpmCharacterToVoice();
      _loadVoxcpmSample();
      if(typeof _onPreviewParamsChanged==='function')_onPreviewParamsChanged();
    };
    return;
  }
```

E le due funzioni che il ramo chiama, accanto alle altre VoxCPM:

```javascript
// Record di catalogo della voce VoxCPM selezionata, o null.
function _voxcpmSelectedVoice(){
  const sel=document.getElementById('vvPremium');
  const id=sel?sel.value:'';
  if(!_isVoxcpmVoiceId(id))return null;
  for(const v of _voxcpmVoicesForLang())if(v.id===id)return v;
  return null;
}

// §5.3: ogni voce ha esattamente un carattere, perche' il carattere e' inciso
// nel campione da cui il modello clona. Scelta una voce, CARATTERE mostra il
// suo valore: e' un'etichetta, non un'alternativa. E non si svuota mai —
// verso "voce -> carattere" la risposta e' sempre una sola, e un campo vuoto
// fingerebbe che ce ne siano altre.
function _syncVoxcpmCharacterToVoice(){
  const sel=document.getElementById('voxcpmCharacter');
  const v=_voxcpmSelectedVoice();
  if(!sel||!v||!v.persona)return;
  if(!Array.prototype.some.call(sel.options,o=>o.value===v.persona)){
    const o=document.createElement('option');
    o.value=v.persona;o.textContent=_voxcpmPersonaLabel(v.persona);
    sel.appendChild(o);
  }
  sel.value=v.persona;
  _voxcpmCharacterSel=v.persona;
}

// Carica il campione della voce nel player. Il .wav non si scarica finche'
// l'utente non preme play (preload="none" nel markup).
function _loadVoxcpmSample(){
  const audio=document.getElementById('voxcpmSample');
  const v=_voxcpmSelectedVoice();
  if(!audio)return;
  audio.pause();
  if(v&&v.sample_url){audio.src=v.sample_url;}
  else{audio.removeAttribute('src');}
  audio.load();
}
```

Nota sull'allineamento del carattere: dopo `_syncVoxcpmCharacterToVoice` il
valore di `_voxcpmCharacterSel` è quello della voce, quindi il filtro si
stringe a quel carattere. È il comportamento voluto — l'utente vede da cosa
sta scegliendo — e per riaprire la lista intera gli basta rimettere
CARATTERE su «Tutti», che resta sempre la prima opzione.

- [ ] **Step 9: Spegni il bottone dell'anteprima**

In `_updatePreviewBtn`:

```javascript
function _updatePreviewBtn(){
  const btn=document.getElementById('btnPrev');
  if(!btn)return;
  // Su VoxCPM l'anteprima non esiste: si ascolta il campione (§5.2), e
  // /api/preview risponde 400 per queste voci. Spegnere il bottone evita
  // all'utente un errore per una funzione che gli e' stata sostituita.
  const sez=document.getElementById('previewSection');
  const vox=_isVoxcpmVoiceId(getCurrentVoiceId());
  if(sez)sez.hidden=vox;
  if(vox){btn.disabled=true;btn.classList.remove('loading');return;}
  const ok=!!(bookData&&bookData.preview_text&&!generating&&!jobDone);
  btn.disabled=!ok;
  btn.classList.remove('loading');
  const txt=document.getElementById('prevTxt');
  if(txt)txt.textContent=t(_previewGenerated?'btn_regen_preview':'btn_gen_preview');
}
```

- [ ] **Step 10: Lancia i test e verifica che passino**

```
python -m pytest test/test_voxcpm_frontend_assets.py test/test_speechify_frontend_assets.py test/test_app_js_tab_logic.py -q
```

Atteso: PASS. I due test esistenti girano insieme perché questo task tocca le
funzioni che coprono.

- [ ] **Step 11: Prova il pannello a mano**

I test statici verificano che i meccanismi ci siano, non che si comportino
bene. Avvia l'app con il motore configurato e verifica di persona:

1. Scegli una lingua con voci VoxCPM: il modello «VoxCPM2 · La tua voce»
   compare fra i premium.
2. Selezionalo: spariscono istruzioni di stile ed emozione, compaiono
   ACCENTO, CARATTERE e il player del campione.
3. Cambia ACCENTO: la lista VOCE si restringe alle voci di quel locale, e
   CARATTERE ai caratteri presenti in quel locale.
4. Metti CARATTERE su un valore: VOCE si restringe. Rimettilo su «Tutti»: si
   riapre.
5. Scegli una voce: CARATTERE mostra il carattere di quella voce; nessuno dei
   due campi resta vuoto.
6. Premi play sul campione: si sente la voce.
7. Torna su Gemini e su Simba: i due pannelli sono esattamente come prima.

- [ ] **Step 12: Commit**

```
git add static/js/app.js test/test_voxcpm_frontend_assets.py
git add -f templates/_fragments/html_head.html
git commit -m "feat(voxcpm): i menu' del pannello diventano filtri su un catalogo"
```

---

### Task 13: I caratteri parlano la lingua dell'utente

Il pannello del Task 12 funziona già, ma mostra `warm-young` e `it-IT`:
chiavi tecniche, scritte per il modello e non per chi legge. Questo task le
traduce — e lo fa senza mai dipendere da quali voci esistono.

La regola è quella della spec (§5.2 e §12.1): **un dizionario con ricadute**.
Davanti a una chiave che conosce, il dizionario dà la traduzione nella lingua
dell'interfaccia. Davanti a una che non conosce — un carattere nuovo nel
catalogo, generato dopo l'ultimo rilascio — ricade sulle stringhe che il
catalogo si porta dietro (`description.role`), e in ultima istanza sulla
chiave stessa. Nessun passaggio si rompe, nessuno mostra una casella vuota.

Vale la pena dire perché un dizionario non contraddice la D10, visto che la
D10 vieta gli elenchi cablati. La differenza sta in **chi decide cosa
esiste**: l'elenco delle voci, dei locali e dei caratteri lo decide sempre
`voices.json`, e il dizionario non ne aggiunge né ne toglie uno. Il
dizionario è solo un *abbellimento* delle chiavi che il catalogo ha già
prodotto. Per questo nessun test di questo task confronta il dizionario col
catalogo: un carattere tradotto ma sparito è innocuo, e uno presente ma non
tradotto si vede lo stesso.

Per gli accenti la ricaduta è ancora migliore del dizionario: il browser sa
già dire «italiano (Italia)» in sei lingue, e lo fa con `Intl.DisplayNames`.
Le trentotto varianti del catalogo di oggi — e quelle di domani — prendono
un'etichetta leggibile senza che nessuno scriva trentotto righe per lingua,
che è esattamente ciò che la D10 chiede di non fare.

**Files:**
- Modify: `templates/_fragments/i18n_data.js` (in coda, dopo l'ultimo
  `Object.assign`)
- Modify: `static/js/app.js` (`_voxcpmPersonaLabel` del Task 12, e la riga
  dell'etichetta accento in `_populateVoxcpmAccents`)
- Test: `test/test_voxcpm_i18n.py`

**Interfaces:**
- Consumes: dal Task 3 — il campo `persona_role` dell'entry; dal Task 12 —
  `_voxcpmPersonaLabel(chiave)` nella sua versione minima, e la chiamata a
  `t('accent_…')` dentro `_populateVoxcpmAccents`.
- Produces:
  - Chiavi i18n in it/en/fr/es/de/zh: `lbl_model_voxcpm`, `lbl_character`,
    `character_all`, `voxcpm_sample_title`, `voxcpm_sample_hint`, e
    `persona_<chiave_con_underscore>` per i caratteri noti.
  - `_voxcpmLocaleLabel(loc) -> string` in `app.js`.
  - `_voxcpmPersonaLabel(chiave) -> string` nella versione definitiva.

Sulle lingue: sei, non sette. `hi` non compare, esattamente come nei blocchi
premium vicini (`lbl_model_simba`, `lbl_emotion`, `accent_*`): `t()` ricade
su `L.en` per le chiavi che l'hindi non ha, e questo task segue la
convenzione del codice che gli sta accanto invece di inventarne una propria.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_voxcpm_i18n.py`. Serve un lettore diverso da quello di
`test_i18n_completeness.py`: quello guarda solo il blocco base di `L`, mentre
le chiavi premium arrivano dagli `Object.assign` in coda al file.

```python
"""Le etichette del pannello VoxCPM esistono nelle sei lingue.

Il file i18n mette le chiavi in due posti: il blocco base `L.<lingua>:{...}`
e gli `Object.assign(L.<lingua>,{...})` in coda. Le chiavi premium stanno nei
secondi, quindi qui si guardano entrambi — test_i18n_completeness.py legge
solo il primo, ed e' il motivo per cui non copre queste chiavi.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N = (ROOT / "templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
JS = (ROOT / "static/js/app.js").read_text(encoding="utf-8")

LANGS = ["it", "en", "fr", "es", "de", "zh"]

CHIAVI_PANNELLO = [
    "lbl_model_voxcpm", "lbl_character", "character_all",
    "voxcpm_sample_title", "voxcpm_sample_hint",
]
# Snapshot dei caratteri del catalogo al 2026-08-28. NON e' un requisito:
# serve solo a verificare che il dizionario copra le sei lingue in modo
# uniforme. Nessun test confronta questa lista con voices.json (D10).
CHIAVI_PERSONA = [
    "persona_audiobook_slow", "persona_bright_lively", "persona_casual_drawl",
    "persona_deep_adventure", "persona_elder_sage", "persona_grave_narrator",
    "persona_intimate", "persona_neutral_pro", "persona_poised_dry",
    "persona_warm_pro", "persona_warm_young", "persona_weathered",
]


def _blocchi(lang):
    """Tutti i frammenti che assegnano chiavi a una lingua."""
    fuori = re.findall(
        r"Object\.assign\(L\.%s\s*,\s*\{(.*?)\}\s*\)\s*;" % re.escape(lang),
        I18N, re.DOTALL)
    return "\n".join(fuori)


def _ha(lang, chiave):
    return re.search(r'(?:^|[,{])\s*"?%s"?\s*:' % re.escape(chiave),
                     _blocchi(lang)) is not None


def test_le_etichette_del_pannello_ci_sono_in_tutte_le_lingue():
    mancanti = [f"{l}.{k}" for l in LANGS for k in CHIAVI_PANNELLO if not _ha(l, k)]
    assert not mancanti, f"chiavi mancanti: {mancanti}"


def test_i_caratteri_noti_sono_tradotti_in_tutte_le_lingue():
    mancanti = [f"{l}.{k}" for l in LANGS for k in CHIAVI_PERSONA if not _ha(l, k)]
    assert not mancanti, f"chiavi mancanti: {mancanti}"


def test_le_traduzioni_non_sono_la_chiave_tecnica():
    # Una traduzione uguale alla chiave sarebbe peggio di nessuna traduzione:
    # passerebbe il test sopra fingendo un lavoro non fatto.
    for lang in LANGS:
        blocco = _blocchi(lang)
        for k in CHIAVI_PERSONA:
            m = re.search(r'%s\s*:\s*"([^"]*)"' % re.escape(k), blocco)
            if m:
                assert m.group(1).strip(), f"{lang}.{k} vuota"
                assert m.group(1) != k.replace("persona_", "").replace("_", "-")


def test_la_traduzione_ricade_e_non_si_rompe():
    # §5.2: dizionario -> stringhe del catalogo -> chiave. Un carattere nuovo
    # non deve richiedere un rilascio.
    i = JS.find("function _voxcpmPersonaLabel")
    assert i != -1
    corpo = JS[i:i + 800]
    assert "persona_" in corpo
    assert "persona_role" in corpo   # l'anello di mezzo
    assert "return" in corpo


def test_gli_accenti_si_traducono_senza_elenchi():
    # 38 varianti oggi, ignote domani: l'etichetta viene dal browser, non da
    # 38 righe per lingua.
    i = JS.find("function _voxcpmLocaleLabel")
    assert i != -1
    corpo = JS[i:i + 600]
    assert "Intl.DisplayNames" in corpo
    assert "catch" in corpo          # ricaduta sul codice grezzo
    assert "_voxcpmLocaleLabel(" in JS.split("function _voxcpmLocaleLabel")[0] \
        or "_voxcpmLocaleLabel(loc)" in JS


def test_il_dizionario_dei_caratteri_non_e_in_app_js():
    # D10: le chiavi stanno nelle traduzioni, l'elenco di cosa esiste sta nel
    # catalogo. app.js non deve contenere ne' l'uno ne' l'altro.
    for cablato in ("warm-young", "audiobook-slow", "elder-sage"):
        assert cablato not in JS
```

- [ ] **Step 2: Lancia i test e verifica che falliscano**

```
python -m pytest test/test_voxcpm_i18n.py -q
```

Atteso: FAIL — `chiavi mancanti: ['it.lbl_model_voxcpm', ...]`.

- [ ] **Step 3: Aggiungi le etichette del pannello**

In coda a `templates/_fragments/i18n_data.js`, una riga per lingua. Il file
tiene le chiavi su una riga sola per blocco: rispetta lo stile.

```javascript
Object.assign(L.it,{lbl_model_voxcpm:"VoxCPM2 · La tua voce",lbl_character:"Carattere",character_all:"Tutti",voxcpm_sample_title:"Ascolta la voce",voxcpm_sample_hint:"Il campione da cui la voce viene clonata: il libro suonerà così."});
Object.assign(L.en,{lbl_model_voxcpm:"VoxCPM2 · Your voice",lbl_character:"Character",character_all:"All",voxcpm_sample_title:"Listen to the voice",voxcpm_sample_hint:"The sample the voice is cloned from: the book will sound like this."});
Object.assign(L.fr,{lbl_model_voxcpm:"VoxCPM2 · Votre voix",lbl_character:"Caractère",character_all:"Tous",voxcpm_sample_title:"Écouter la voix",voxcpm_sample_hint:"L'échantillon dont la voix est clonée : le livre sonnera ainsi."});
Object.assign(L.es,{lbl_model_voxcpm:"VoxCPM2 · Tu voz",lbl_character:"Carácter",character_all:"Todos",voxcpm_sample_title:"Escuchar la voz",voxcpm_sample_hint:"La muestra de la que se clona la voz: el libro sonará así."});
Object.assign(L.de,{lbl_model_voxcpm:"VoxCPM2 · Deine Stimme",lbl_character:"Charakter",character_all:"Alle",voxcpm_sample_title:"Stimme anhören",voxcpm_sample_hint:"Die Aufnahme, aus der die Stimme geklont wird: so wird das Buch klingen."});
Object.assign(L.zh,{lbl_model_voxcpm:"VoxCPM2 · 你的声音",lbl_character:"性格",character_all:"全部",voxcpm_sample_title:"试听声音",voxcpm_sample_hint:"声音克隆所用的样本：整本书将是这个音色。"});
```

Il suffisso «La tua voce» promette la clonazione, che questo piano non porta:
finché il piano 2 non esiste, l'etichetta è comunque corretta — la voce è
*sua* nel senso che l'ha scelta dal catalogo — e cambiarla dopo costerebbe
una riga per lingua.

- [ ] **Step 4: Aggiungi il dizionario dei caratteri**

Sempre in coda, sei righe. I dodici caratteri sono quelli del catalogo di
oggi; l'elenco è una fotografia, non un contratto.

```javascript
Object.assign(L.it,{persona_audiobook_slow:"Narrativo lento",persona_bright_lively:"Brillante e vivace",persona_casual_drawl:"Colloquiale strascicato",persona_deep_adventure:"Profondo avventuroso",persona_elder_sage:"Anziano saggio",persona_grave_narrator:"Narratore grave",persona_intimate:"Intimo",persona_neutral_pro:"Neutro professionale",persona_poised_dry:"Posato e asciutto",persona_warm_pro:"Caldo professionale",persona_warm_young:"Caldo e giovane",persona_weathered:"Vissuto"});
Object.assign(L.en,{persona_audiobook_slow:"Slow narration",persona_bright_lively:"Bright and lively",persona_casual_drawl:"Casual drawl",persona_deep_adventure:"Deep and adventurous",persona_elder_sage:"Elder sage",persona_grave_narrator:"Grave narrator",persona_intimate:"Intimate",persona_neutral_pro:"Neutral professional",persona_poised_dry:"Poised and dry",persona_warm_pro:"Warm professional",persona_warm_young:"Warm and young",persona_weathered:"Weathered"});
Object.assign(L.fr,{persona_audiobook_slow:"Narration lente",persona_bright_lively:"Clair et vif",persona_casual_drawl:"Décontracté et traînant",persona_deep_adventure:"Grave et aventureux",persona_elder_sage:"Sage âgé",persona_grave_narrator:"Narrateur grave",persona_intimate:"Intime",persona_neutral_pro:"Neutre professionnel",persona_poised_dry:"Posé et sobre",persona_warm_pro:"Chaleureux professionnel",persona_warm_young:"Chaleureux et jeune",persona_weathered:"Marqué par le temps"});
Object.assign(L.es,{persona_audiobook_slow:"Narración pausada",persona_bright_lively:"Brillante y vivaz",persona_casual_drawl:"Coloquial arrastrado",persona_deep_adventure:"Profundo y aventurero",persona_elder_sage:"Anciano sabio",persona_grave_narrator:"Narrador grave",persona_intimate:"Íntimo",persona_neutral_pro:"Neutro profesional",persona_poised_dry:"Sereno y sobrio",persona_warm_pro:"Cálido profesional",persona_warm_young:"Cálido y joven",persona_weathered:"Curtido"});
Object.assign(L.de,{persona_audiobook_slow:"Ruhige Erzählstimme",persona_bright_lively:"Hell und lebhaft",persona_casual_drawl:"Lässig gedehnt",persona_deep_adventure:"Tief und abenteuerlich",persona_elder_sage:"Weiser Ältester",persona_grave_narrator:"Ernster Erzähler",persona_intimate:"Intim",persona_neutral_pro:"Neutral professionell",persona_poised_dry:"Gelassen und trocken",persona_warm_pro:"Warm professionell",persona_warm_young:"Warm und jung",persona_weathered:"Verwittert"});
Object.assign(L.zh,{persona_audiobook_slow:"舒缓朗读",persona_bright_lively:"明亮活泼",persona_casual_drawl:"慵懒随意",persona_deep_adventure:"低沉冒险",persona_elder_sage:"长者智慧",persona_grave_narrator:"庄重叙述",persona_intimate:"亲密低语",persona_neutral_pro:"中性专业",persona_poised_dry:"沉稳干练",persona_warm_pro:"温暖专业",persona_warm_young:"温暖年轻",persona_weathered:"沧桑"});
```

- [ ] **Step 5: Completa la catena di ricadute**

In `static/js/app.js`, sostituisci la versione minima che il Task 12 aveva
messo come segnaposto:

```javascript
// Etichetta leggibile di un carattere, in tre gradini (§5.2).
//   1. il dizionario delle traduzioni, se conosce la chiave;
//   2. il `role` che il catalogo si porta dietro — non tradotto, ma
//      descrittivo e sempre presente;
//   3. la chiave tecnica.
// Il terzo gradino non e' un ripiego elegante: e' cio' che permette a un
// carattere generato dopo l'ultimo rilascio di comparire lo stesso (D10).
function _voxcpmPersonaLabel(chiave,voce){
  if(!chiave)return '';
  const k='persona_'+String(chiave).replace(/-/g,'_');
  const tradotta=t(k);
  if(tradotta&&tradotta!==k)return tradotta;
  if(voce&&voce.persona_role)return voce.persona_role;
  return chiave;
}
```

`t()` restituisce la chiave quando non la trova, quindi il confronto
`tradotta!==k` è ciò che distingue «tradotto» da «non tradotto».

La firma guadagna un secondo parametro, e i due punti che la chiamano con la
voce sotto mano vanno aggiornati. In `updVoicesPremium`, dentro il ramo
VoxCPM:

```javascript
      o.textContent=(v.gender_icon?v.gender_icon+' ':'')+(v.name||v.id.split('/').pop())
                    +' · '+_voxcpmPersonaLabel(v.persona,v);
```

e in `_syncVoxcpmCharacterToVoice`:

```javascript
    o.value=v.persona;o.textContent=_voxcpmPersonaLabel(v.persona,v);
```

La chiamata dentro `_populateVoxcpmCharacters` resta a un parametro: lì la
voce non c'è, perché il menù elenca caratteri e non voci, e il secondo
gradino salta. È accettabile — quel menù mostra caratteri già presenti nel
catalogo, e se uno non è tradotto compare come chiave finché il dizionario
non lo raggiunge.

- [ ] **Step 6: Dai un nome leggibile agli accenti**

Sempre in `app.js`, accanto alle altre funzioni VoxCPM:

```javascript
// Etichetta di un locale ('it-IT' -> 'italiano (Italia)'). Anche qui tre
// gradini: la chiave accent_* se esiste gia' per un altro motore, poi
// Intl.DisplayNames — che il browser localizza nella lingua dell'interfaccia
// e che copre i locali di domani senza righe nuove (D10) — e infine il
// codice grezzo, che e' brutto ma non e' mai sbagliato.
function _voxcpmLocaleLabel(loc){
  if(!loc)return '';
  const k='accent_'+String(loc).toLowerCase().replace(/-/g,'_');
  const tradotta=t(k);
  if(tradotta&&tradotta!==k)return tradotta;
  try{
    const dn=new Intl.DisplayNames([cl||'en'],{type:'language'});
    const nome=dn.of(loc);
    if(nome&&nome!==loc)return nome;
  }catch(e){/* Intl assente o locale non riconosciuto: si scende. */}
  return loc;
}
```

e in `_populateVoxcpmAccents` sostituisci la riga dell'etichetta:

```javascript
    o.textContent=_voxcpmLocaleLabel(loc);
```

Nota sulla variabile della lingua: `cl` è la variabile globale che `app.js`
usa per la lingua dell'interfaccia (`let cl='en'`, appena sopra `t()`). La
funzione consulta quella, non una fonte nuova: se le due divergessero,
l'utente vedrebbe i caratteri in una lingua e gli accenti in un'altra.

- [ ] **Step 7: Lancia i test e verifica che passino**

```
python -m pytest test/test_voxcpm_i18n.py test/test_i18n_completeness.py test/test_voxcpm_frontend_assets.py -q
```

Atteso: PASS. Il test di completezza esistente gira insieme perché questo
task tocca il file che legge.

- [ ] **Step 8: Guarda il pannello nelle sei lingue**

Avvia l'app e cambia lingua dall'interfaccia. In ognuna delle sei:
ACCENTO mostra nomi di lingua, non codici; CARATTERE mostra descrizioni, non
chiavi con il trattino; la riga della voce dice nome, genere e carattere.

- [ ] **Step 9: Commit**

```
git add static/js/app.js test/test_voxcpm_i18n.py
git add -f templates/_fragments/i18n_data.js
git commit -m "feat(voxcpm): caratteri e accenti nella lingua di chi legge"
```

---

### Task 14: Il collaudo che nessun test automatico può fare

Tredici task hanno prodotto codice verificato da doppi. Ma nessuna riga di
questo piano ha mai parlato con una GPU vera: il worker che risponde è sempre
stato un finto, e il `.wav` che torna sempre un header di quarantaquattro
byte. Il primo libro letto da VoxCPM va ascoltato da un essere umano, e la
procedura per farlo va scritta prima, non improvvisata la sera del rilascio.

Questo task chiude tre conti aperti: il documento di collaudo manuale (§14),
la tabella delle variabili completa (§13), e la suite intera contro la
baseline. Non aggiunge funzionalità: verifica che quelle aggiunte stiano
insieme.

**Files:**
- Create: `docs/MANUAL_TESTS_VOXCPM.md`
- Modify: `md_files/PARAMETRI_CONFIGURAZIONE.md` (verifica, non aggiunta)
- Test: nessun file nuovo — qui gira tutto quello che esiste

**Interfaces:**
- Consumes: tutto ciò che i Task 1–13 hanno prodotto.
- Produces: niente che il codice usi. Il prodotto è un documento e una
  suite verde.

- [ ] **Step 1: Verifica che le variabili siano tutte documentate**

La regola del `CLAUDE.md` dice che ogni variabile va scritta nello stesso
commit che la introduce, e i task precedenti l'hanno seguita. Questo passo
controlla che nessuna sia sfuggita — è un conteggio, non una riscrittura.

```
python -c "import re,io; t=io.open('md_files/PARAMETRI_CONFIGURAZIONE.md',encoding='utf-8').read(); att=['ABM_VOXCPM_ENDPOINT_ID','ABM_VOXCPM_API_KEY','ABM_VOXCPM_CATALOG_DIR','ABM_VOXCPM_RATE_EUR_PER_MCHAR','ABM_VOXCPM_COST_USD_PER_MCHAR','ABM_VOXCPM_FREE_THRESHOLD_EUR','ABM_VOXCPM_MIN_COST_EUR','ABM_VOXCPM_CONCURRENCY','ABM_VOXCPM_JOBS','ABM_VOXCPM_QUEUE_TIMEOUT_S','ABM_VOXCPM_JOB_TIMEOUT_S','ABM_VOXCPM_POLL_S','ABM_MAX_VOXCPM_TEXT_CHARS']; m=[v for v in att if v not in t]; print('MANCANTI:',m) if m else print('tutte documentate')"
```

Se ne manca qualcuna, aggiungila alla sezione delle voci PREMIUM con default
e significato, nello stile delle righe vicine.

- [ ] **Step 2: Scrivi la procedura di collaudo manuale**

Crea `docs/MANUAL_TESTS_VOXCPM.md`, sullo schema di
`docs/MANUAL_TESTS_GEMINI_PAYMENT.md`. Copre solo il catalogo: registrazione
e voce propria sono del piano 2, e il documento lo dice per non far credere
che qualcuno le abbia già provate.

````markdown
# Collaudo manuale — VoxCPM2, voci di catalogo

Da eseguire su GPU vera prima del rilascio. La suite automatica parla sempre
con un worker finto: tutto ciò che segue verifica le cose che un doppio non
può dire — come suona la voce, quanto costa davvero un boot, e se il libro
finito ha i capitoli al posto giusto.

**Fuori da questo documento:** registrazione della propria voce, gate di
qualità, recupero via email, cancellazione. Sono del piano 2 e non sono mai
state provate.

## Prerequisiti

- `ABM_VOXCPM_ENDPOINT_ID` e `ABM_VOXCPM_API_KEY` di un endpoint attivo.
- `ABM_VOXCPM_RATE_EUR_PER_MCHAR` e `ABM_VOXCPM_MIN_COST_EUR` ai valori
  commerciali decisi (§13 della spec: si fissano prima del deploy).
- `data/voci_inventate/` presente, con `voices.json` e i `.wav`.
- Un EPUB breve: tre o quattro capitoli, meno di 20.000 caratteri. Un libro
  lungo qui non aggiunge informazione e costa GPU.

## 1. Il motore compare, e solo se configurato

1. Avvia l'app, apri il wizard, vai al tab **Voci PREMIUM**.
2. Nel menù MODELLO c'è **VoxCPM2 · La tua voce**. → _atteso: sì_
3. Ferma l'app, svuota `ABM_VOXCPM_ENDPOINT_ID`, riavvia.
4. Il modello **non** compare, e gli altri tre funzionano. → _atteso: sì_
5. Rimetti l'endpoint e riavvia.

## 2. I filtri fanno quello che dicono

1. Scegli VoxCPM2. Compaiono ACCENTO, CARATTERE e il player del campione;
   spariscono istruzioni di stile ed emozione.
2. Cambia ACCENTO: la lista VOCE si restringe a quel locale.
3. Scegli un CARATTERE: la lista VOCE si restringe ancora.
4. Scegli una voce: CARATTERE mostra il carattere di quella voce.
5. Nessuno dei due menù resta mai vuoto. → _atteso: sì_
6. Premi play sul campione: si sente la voce, e il nome che si legge è quello
   della voce scelta.

## 3. Il prezzo detto è il prezzo pagato

Questo è il punto in cui l'incidente del 402 Speechify si ripeterebbe, se
dovesse ripetersi.

1. Con la quota mensile **capiente**, annota il prezzo mostrato nella riga
   costo. → _atteso: gratis o l'importo di listino_
2. Avvia la generazione. Non deve comparire nessuna richiesta di pagamento
   che la stima non avesse annunciato. → _atteso: sì_
3. Esaurisci la quota (o abbassa `ABM_FREE_QUOTA_EUR_PER_MONTH`), ricarica,
   e rileggi la stima.
4. Il modale di pagamento chiede **lo stesso numero** che la riga costo
   mostrava. → _atteso: sì_

## 4. Un libro intero, dal caricamento all'M4B

1. Carica l'EPUB, scegli una voce VoxCPM, lascia la velocità a 0%.
2. Avvia. Il primo messaggio di avanzamento parla di accensione del motore.
   → _atteso: «Accensione del motore vocale, circa tre minuti…»_
3. Annota **quanto passa** prima del primo capitolo pronto. È il cold start:
   se supera i cinque minuti, va segnalato prima del rilascio.
4. A fine generazione scarica l'M4B e aprilo in un lettore con i capitoli.
5. Verifica, ascoltando:
   - la voce è quella del campione, non un'altra;
   - i marcatori di capitolo cadono all'inizio dei capitoli;
   - non ci sono tagli, doppioni o silenzi lunghi fra un chunk e l'altro;
   - il testo letto è tutto il testo, inizio e fine compresi.

## 5. La velocità

1. Rigenera lo stesso libro con la velocità a **−20%** e a **+20%**.
2. La lettura rallenta e accelera, e la voce **non** cambia timbro.
   → _atteso: sì (è `atempo`, non un cambio di frequenza)_
3. La durata dell'M4B si muove nella direzione giusta.

## 6. Il riuso non ricompra

1. Rigenera lo stesso libro, stessa voce, stessi capitoli.
2. I capitoli già fatti si riusano: nessun job nuovo, nessun costo nuovo.
   → _atteso: sì_
3. Cambia il testo di **un solo** capitolo e rigenera: si rifà quel capitolo
   e basta.

## 7. L'audit dice la verità

1. Apri `/admin/audit-premium`.
2. I job VoxCPM ci sono, con `provider: voxcpm`. → _atteso: sì_
3. Il costo scritto corrisponde ai caratteri letti.
4. Cerca `AUDIT WARNING` nel log: non deve essercene nessuno per un libro
   sopra soglia. → _atteso: nessuno_

## 8. Cosa fare se qualcosa non torna

Prima di toccare il codice, guarda il log del worker su RunPod: la
tassonomia degli errori (§9.4) distingue un motore compromesso — che si
ritenta — da una coda satura, che non si ritenta. I due si assomigliano nel
messaggio e non nella cura.
````

- [ ] **Step 3: Lancia la suite intera**

```
python -m pytest test/ -q
```

Atteso: **1964 passati più i nuovi di questo piano, 16 saltati, zero
falliti.** La baseline è di `ac1ba45` (§14): ogni fallimento che non ci fosse
allora è di questo lavoro, e va risolto prima del commit — non annotato come
preesistente.

Se un test esistente fallisce, il sospetto va per primo ai tre punti che
questo piano ha allargato invece di duplicare: il ramo di consumo del
pagamento (Task 10), i contatori dell'admin (Task 11), e
`_onPremiumModelChanged` (Task 12).

- [ ] **Step 4: Commit**

```
git add -f docs/MANUAL_TESTS_VOXCPM.md md_files/PARAMETRI_CONFIGURAZIONE.md
git commit -m "docs(voxcpm): procedura di collaudo su GPU vera"
```

- [ ] **Step 5: Consegna**

Il piano è finito quando queste tre cose sono vere insieme:

1. la suite è verde;
2. `docs/MANUAL_TESTS_VOXCPM.md` esiste e nessuno l'ha ancora eseguito;
3. i due valori commerciali — `ABM_VOXCPM_RATE_EUR_PER_MCHAR` e
   `ABM_VOXCPM_MIN_COST_EUR` — sono ancora da fissare, e il rilascio è
   bloccato finché non lo sono (§13: sono decisioni commerciali, non
   implementative).

Il punto 3 non è un difetto del piano: è la sua ultima riga. Un motore che
funziona con il listino sbagliato è peggio di un motore spento.

---

