# Voci campionate — piano 1/3: fondamenta backend

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** i moduli di base che rendono una registrazione dell'utente una voce VoxCPM usabile: frasi guidate, conversione e gate acustico, verifica ASR, store con identità/stati/dispositivi, resolver del campione dentro `voxcpm_tts`. Nessun endpoint, nessun pagamento, nessuna email, nessun frontend: sono i piani 2 e 3.

**Architecture:** tre moduli nuovi, tutti foglia rispetto ad `audiobook_app`. `voice_clone_prompts` legge un JSON tracciato in git e lo ricarica se cambia. `voice_clone_audio` fa parlare ffmpeg (probe, conversione, loudness) e numpy (misure portate da `tools/voice_prompts/audio.py` del worker, senza scipy né librosa) e incapsula faster-whisper con lock, timeout e scarico dalla memoria. `voice_clone` tiene i record in `_voice_clones.json` via `community_store.JsonStore`, genera token e codici, gestisce la bozza `sample_ok`, i dispositivi, la tabella delle transizioni e il resolver `resolve(voice_id)` che `voxcpm_tts.clone_block` chiama per gli id `voxcpm:mine:<token>`.

**Tech Stack:** Python 3.11, numpy 1.26, faster-whisper 1.2 (CPU, int8), zhconv, ffmpeg/ffprobe di sistema, `community_store.JsonStore`, `storage_backend` (boto3/R2), pytest.

**Spec:** `docs/superpowers/specs/2026-09-09-voci-campionate-design.md` (§4, §5, §6, §9, §10 per la sola tabella delle transizioni, §14, §15, §16).

## Global Constraints

- **Branch `voci-campionate`**, commit su questo branch. **Nessun `git push` senza conferma esplicita dell'utente nel turno corrente**: push su `main` = deploy in produzione.
- **Staging solo per path espliciti** (`git add <file>`), mai `git add -A` o `git add .`: la working copy porta modifiche di altre sessioni (`static/css/style.css`, `static/js/app.js`, `templates/_fragments/html_head.html`) che non appartengono a questo lavoro.
- **Conventional Commits** (`feat(voice-clone): ...`, `test(voice-clone): ...`), senza trailer di attribuzione.
- **Windows PowerShell** in sviluppo: comandi singoli, niente `&&`. `python -m pytest test/<file> -v --tb=short`.
- **Nessun segreto in doc, log o test**: `token`, `manage_token`, `resume_token`, `owner_email` non compaiono mai nei log né nelle viste pubbliche (`public_view`). Le credenziali di `start_ABM_VOXCPM.ps1` non si riportano da nessuna parte.
- **Nessuna modifica al worker RunPod** (spec §5.4): la verifica ASR gira sul server dell'app.
- **Nessun import di `audiobook_app`** dai moduli nuovi (convenzione 1 del repo). La data dir arriva con `voice_clone.init(data_dir)` e `voice_clone_audio.init(data_dir)` chiamate all'avvio (il cablaggio in `audiobook_app` è del piano 2; qui i test le chiamano direttamente).
- **Dipendenze nuove**: `numpy`, `faster-whisper`, `zhconv` in `requirements.txt` (Task 8). Niente scipy, librosa, soxr: dove il worker li usa, qui lavorano ffmpeg (highpass, loudness) o numpy (banda, trim).
- **ffmpeg opzionale nei test**: ogni test che lo usa è decorato con `pytest.mark.skipif(shutil.which("ffmpeg") is None, ...)`. `faster_whisper` non si importa mai nei test: il modello è un doppio iniettato via `voice_clone_audio._new_model`.
- **Valori dalla spec §14** (default): `ABM_VOICE_CLONE_MIN_SEC=12`, `ABM_VOICE_CLONE_MAX_SEC=20`, `ABM_VOICE_CLONE_MAX_CER=0.25`, `ABM_VOICE_CLONE_ASR=1`, `ABM_VOICE_CLONE_ASR_MODEL=base`, `ABM_VOICE_CLONE_ASR_TIMEOUT_SEC=120`, `ABM_VOICE_CLONE_SAMPLE_TTL_H=24`, `ABM_VOICE_CLONE_RETENTION_DAYS=365`, `ABM_VOICE_CLONE_MAX_UPLOAD_MB=20`. Le restanti (`ENABLED`, `EUR_CLONED_VOICE`, `REGEN_MAX`, `DEMO_RETRIES`) sono del piano 2.
- **Deviazione dichiarata dalla spec §6.1 («indici in memoria»)**: `voice_clone` cerca i record con una scansione lineare di `JsonStore.all()` sotto un lock di modulo. Il file conta decine di record, la lettura è in microsecondi e la scansione non può andare fuori sincrono con il file. Se un giorno servisse un indice, si aggiunge dietro le stesse funzioni `_find*`.
- **Tag del file non tracciati**: `*.md` è in `.gitignore`; il piano e la spec si aggiungono con `git add -f`. `voice_clone_prompts.json` non è ignorato.
- **Pulizia**: nessun file temporaneo nella radice del repo a fine task; i wav sintetici dei test nascono in `tmp_path`.

---

## File Structure

| File | Responsabilità |
|------|----------------|
| `voice_clone_prompts.json` (nuovo, radice) | Le frasi guidate per lingua, schema `abm-voice-clone-prompts/1` |
| `voice_clone_prompts.py` (nuovo) | `languages()`, `prompt_for(lang, gender)`, `prompt_version(text)`; ricarica su mtime |
| `voice_clone_audio.py` (nuovo) | `probe()`, `convert()`, `normalize()`, misure numpy (`measure`, `Gate`, `apply_gate`), `prepare_sample()` (pipeline intera), `cer()`, `check_transcript()` con faster-whisper |
| `voice_clone.py` (nuovo) | `init()`, store `_voice_clones.json`, id/codici/token, `create_draft()`, `purge_stale_drafts()`, `transition()`, `resolve()`, `check_use()`, `mine()`, `touch_used()`, `claim()/confirm()/forget()/revoke_device()`, `public_view()`, `offered_languages()` |
| `storage_backend.py` (modifica) | `download_file(key, local_path)`: manca, e `resolve()` ne ha bisogno |
| `voxcpm_tts.py` (modifica, righe ~840-870 e ~1070) | `clone_block` e lingua del job per gli id `voxcpm:mine:*` |
| `requirements.txt`, `md_files/PARAMETRI_CONFIGURAZIONE.md` | dipendenze e variabili del piano 1 |
| `test/test_voice_clone_prompts.py`, `test/test_voice_clone_audio.py`, `test/test_voice_clone_asr.py`, `test/test_voice_clone.py`, `test/test_voice_clone_devices.py`, `test/test_voxcpm_tts_mine.py` | test dei task |

---

### Task 1: Frasi guidate (`voice_clone_prompts`)

**Files:**
- Create: `voice_clone_prompts.json`
- Create: `voice_clone_prompts.py`
- Test: `test/test_voice_clone_prompts.py`

**Interfaces:**
- Produces: `languages() -> list[str]` (codici a due lettere, ordinati, con frase usabile per entrambi i generi); `prompt_for(lang: str, gender: str) -> str | None` (`gender` in `"m"`, `"f"`); `prompt_version(text: str) -> str` (`"sha1:" + 16 hex`); `PROMPTS_PATH` (str, sovrascrivibile nei test); `invalidate_cache()`.

- [ ] **Step 1: Scrivere il JSON delle frasi**

Contenuto esatto di `voice_clone_prompts.json` (le nove frasi approvate il 2026-09-09; hindi con variante di genere):

```json
{
  "schema": "abm-voice-clone-prompts/1",
  "prompts": {
    "it": {"text": "Ogni mattina apro la finestra prima di fare il caffè, e ascolto la strada che si sveglia. Passa il furgone del pane, poi qualcuno con il cane, poi il silenzio. Non ho fretta. Leggo qualche pagina, e ne rileggo una frase a voce alta. Solo allora comincia la mia giornata."},
    "en": {"text": "Every morning I open the window before making coffee, and I listen to the street waking up. The bread van goes by, then someone with a dog, then silence. I am in no hurry. I read a few pages, and read one sentence again out loud. Only then does my day begin."},
    "fr": {"text": "Chaque matin, j'ouvre la fenêtre avant de préparer le café, et j'écoute la rue qui se réveille. Le camion du boulanger passe, puis quelqu'un avec son chien, puis le silence. Rien ne presse. Je lis quelques pages, et j'en relis une phrase à voix haute. C'est alors que ma journée commence."},
    "es": {"text": "Cada mañana abro la ventana antes de preparar el café, y escucho la calle que despierta. Pasa la furgoneta del pan, luego alguien con su perro, luego el silencio. No tengo prisa. Leo unas páginas, y vuelvo a leer una frase en voz alta. Solo entonces empieza mi día."},
    "de": {"text": "Jeden Morgen öffne ich das Fenster, bevor ich Kaffee koche, und höre, wie die Straße erwacht. Der Bäckerwagen fährt vorbei, dann jemand mit Hund, dann Stille. Ich habe keine Eile. Ich lese ein paar Seiten und lese einen Satz noch einmal laut. Erst dann beginnt mein Tag."},
    "nl": {"text": "Elke ochtend open ik het raam voordat ik koffie zet, en luister ik hoe de straat wakker wordt. De bakkerswagen rijdt voorbij, dan iemand met een hond, dan stilte. Ik heb geen haast. Ik lees een paar bladzijden, en lees één zin nog eens hardop. Pas dan begint mijn dag."},
    "pt": {"text": "Todas as manhãs abro a janela antes de fazer o café, e escuto a rua que acorda. Passa o padeiro, depois uma bicicleta devagar, depois o silêncio. Não tenho pressa. Leio algumas páginas, e volto a ler uma frase em voz alta. Só então começa o meu dia."},
    "hi": {"text_by_gender": {
      "m": "हर सुबह कॉफ़ी बनाने से पहले मैं खिड़की खोलता हूँ, और सुनता हूँ कि गली कैसे जागती है। दूध वाला गुज़रता है, फिर कोई कुत्ते के साथ, फिर सन्नाटा। मुझे जल्दी नहीं है। मैं कुछ पन्ने पढ़ता हूँ, और एक वाक्य ज़ोर से दोबारा पढ़ता हूँ। तभी मेरा दिन शुरू होता है।",
      "f": "हर सुबह कॉफ़ी बनाने से पहले मैं खिड़की खोलती हूँ, और सुनती हूँ कि गली कैसे जागती है। दूध वाला गुज़रता है, फिर कोई कुत्ते के साथ, फिर सन्नाटा। मुझे जल्दी नहीं है। मैं कुछ पन्ने पढ़ती हूँ, और एक वाक्य ज़ोर से दोबारा पढ़ती हूँ। तभी मेरा दिन शुरू होता है।"
    }},
    "zh": {"text": "每天早上，我先打开窗户，再去煮咖啡，听着街道慢慢醒来。送面包的车开过去了，然后是遛狗的人，然后是一片安静。我不着急。读几页书，再把最喜欢的那句大声念一遍。到那时，我的一天才真正开始。"}
  }
}
```

Salvare in UTF-8 senza BOM. Verifica: `python -c "import json; d=json.load(open('voice_clone_prompts.json', encoding='utf-8')); print(sorted(d['prompts']))"` stampa le nove chiavi.

- [ ] **Step 2: Scrivere i test**

`test/test_voice_clone_prompts.py`:

```python
"""Frasi guidate delle voci campionate (spec §4)."""
import json
import os
import time
import warnings

import pytest

import voice_clone_prompts as vcp

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _pulizia():
    vcp.invalidate_cache()
    yield
    vcp.invalidate_cache()


def _scrivi(path, prompts):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"schema": "abm-voice-clone-prompts/1", "prompts": prompts}, fh)


def test_file_reale_ha_le_nove_lingue():
    assert vcp.languages() == ["de", "en", "es", "fr", "hi", "it", "nl", "pt", "zh"]


def test_prompt_for_testo_unico_ignora_il_genere():
    assert vcp.prompt_for("it", "m") == vcp.prompt_for("it", "f")
    assert vcp.prompt_for("it", "f").startswith("Ogni mattina")


def test_prompt_for_hindi_cambia_col_genere():
    m, f = vcp.prompt_for("hi", "m"), vcp.prompt_for("hi", "f")
    assert m != f
    assert "खोलता" in m and "खोलती" in f


def test_lingua_sconosciuta_o_genere_sconosciuto():
    assert vcp.prompt_for("xx", "m") is None
    assert vcp.prompt_for("it", "x") is None


def test_text_by_gender_ripiega_su_text(tmp_path, monkeypatch):
    p = tmp_path / "p.json"
    _scrivi(p, {"aa": {"text": "base", "text_by_gender": {"m": "maschile"}},
                "bb": {"text_by_gender": {"m": "solo m"}},
                "cc": {"text": "   "}})
    monkeypatch.setattr(vcp, "PROMPTS_PATH", str(p))
    vcp.invalidate_cache()
    assert vcp.prompt_for("aa", "m") == "maschile"
    assert vcp.prompt_for("aa", "f") == "base"
    assert vcp.prompt_for("bb", "f") is None
    # bb ha solo il maschile, cc e' vuota: nessuna delle due e' offerta
    assert vcp.languages() == ["aa"]


def test_ricarica_quando_cambia_mtime(tmp_path, monkeypatch):
    p = tmp_path / "p.json"
    _scrivi(p, {"aa": {"text": "uno"}})
    monkeypatch.setattr(vcp, "PROMPTS_PATH", str(p))
    vcp.invalidate_cache()
    assert vcp.prompt_for("aa", "m") == "uno"
    _scrivi(p, {"aa": {"text": "due"}})
    os.utime(p, (time.time() + 5, time.time() + 5))   # mtime diverso anche su fs a 1 s
    assert vcp.prompt_for("aa", "m") == "due"


def test_file_illeggibile_vale_nessuna_lingua(tmp_path, monkeypatch):
    p = tmp_path / "p.json"
    p.write_text("{non json", encoding="utf-8")
    monkeypatch.setattr(vcp, "PROMPTS_PATH", str(p))
    vcp.invalidate_cache()
    assert vcp.languages() == []
    assert vcp.prompt_for("it", "m") is None


def test_prompt_version_stabile_e_corta():
    v = vcp.prompt_version("Ogni mattina")
    assert v == vcp.prompt_version("Ogni mattina")
    assert v.startswith("sha1:") and len(v) == 5 + 16
    assert v != vcp.prompt_version("Ogni sera")


def test_lingue_attive_del_catalogo_senza_frase_sono_un_warning():
    """Spec §4: una lingua accesa nel catalogo VoxCPM senza frase non rompe
    nulla, non compare nel wizard. Il test lo segnala, non fallisce."""
    path = os.path.join(REPO, "voxcpm2", "voci_inventate", "voices.json")
    if not os.path.exists(path):
        pytest.skip("catalogo VoxCPM non presente in questa working copy")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    attive = {e["code"] for e in data.get("languages") or [] if e.get("enabled")}
    senza = sorted(attive - set(vcp.languages()))
    if senza:
        warnings.warn(f"lingue VoxCPM attive senza frase guidata: {senza}")
    assert True
```

- [ ] **Step 3: Eseguire i test e vederli fallire**

Run: `python -m pytest test/test_voice_clone_prompts.py -v --tb=short`
Expected: errore di import `No module named 'voice_clone_prompts'`.

- [ ] **Step 4: Scrivere il modulo**

`voice_clone_prompts.py`:

```python
"""Frasi guidate delle voci campionate (spec voci-campionate §4).

Modulo foglia: solo stdlib. Il file JSON e' tracciato in git e si ricarica
da solo quando cambia l'mtime, cosi' correggere una frase non richiede un
restart. Il record della voce salva la frase letta cosi' com'era
(`prompt_text` + `prompt_version`): cambiare il file vale solo per le
registrazioni future.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import unicodedata

SCHEMA = "abm-voice-clone-prompts/1"
PROMPTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "voice_clone_prompts.json")
_GENDERS = ("m", "f")

_lock = threading.Lock()
_cache = None        # dict lingua -> {"m": testo, "f": testo}
_cache_mtime = None


def invalidate_cache():
    global _cache, _cache_mtime
    with _lock:
        _cache = None
        _cache_mtime = None


def _clean(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def _normalize(raw):
    """`{"text": ...}` o `{"text_by_gender": {"m":..,"f":..}}` -> {"m","f"}.

    Un genere senza variante ripiega su `text`; se resta un buco la lingua
    non e' offerta (spec §4): meglio assente che una frase mancante a meta'
    wizard.
    """
    if not isinstance(raw, dict):
        return None
    base = _clean(raw.get("text"))
    per = raw.get("text_by_gender") if isinstance(raw.get("text_by_gender"), dict) else {}
    out = {}
    for g in _GENDERS:
        t = _clean(per.get(g)) or base
        if not t:
            return None
        out[g] = t
    return out


def _load():
    global _cache, _cache_mtime
    try:
        mtime = os.stat(PROMPTS_PATH).st_mtime
    except OSError:
        mtime = None
    with _lock:
        if _cache is not None and _cache_mtime == mtime:
            return _cache
    data = {}
    if mtime is not None:
        try:
            with open(PROMPTS_PATH, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict) and raw.get("schema") == SCHEMA:
                for lang, entry in (raw.get("prompts") or {}).items():
                    norm = _normalize(entry)
                    if norm:
                        data[str(lang).strip().lower()] = norm
            else:
                print(f"[voice_clone_prompts] schema inatteso in {PROMPTS_PATH}")
        except Exception as e:
            print(f"[voice_clone_prompts] file non leggibile ({PROMPTS_PATH}): {e}")
            data = {}
    with _lock:
        _cache, _cache_mtime = data, mtime
    return data


def languages():
    """Codici lingua con una frase usabile per entrambi i generi, ordinati."""
    return sorted(_load().keys())


def prompt_for(lang, gender):
    """La frase da leggere, o None se lingua o genere non sono offerti."""
    if gender not in _GENDERS:
        return None
    entry = _load().get((lang or "").strip().lower())
    return entry[gender] if entry else None


def prompt_version(text):
    """`sha1:<16 hex>` del testo in NFC: identifica la frase salvata nel record."""
    norm = unicodedata.normalize("NFC", text or "")
    return "sha1:" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 5: Eseguire i test**

Run: `python -m pytest test/test_voice_clone_prompts.py -v --tb=short`
Expected: 9 PASS (il test sul catalogo reale passa con warning se il catalogo ha lingue attive senza frase, oppure è SKIPPED se `voxcpm2/` manca).

- [ ] **Step 6: Commit**

```
git add voice_clone_prompts.json voice_clone_prompts.py test/test_voice_clone_prompts.py
git commit -m "feat(voice-clone): frasi guidate per lingua con ricarica su mtime"
```

---

### Task 2: Misure acustiche e gate (`voice_clone_audio`, parte numpy)

**Files:**
- Create: `voice_clone_audio.py`
- Test: `test/test_voice_clone_audio.py`

**Interfaces:**
- Produces: `Metrics` (dataclass: `duration, snr_db, snr_hi_db, clarity, speech_ratio, bandwidth_hz, clip_runs, longest_gap, peak_dbfs, dc_offset, lufs, reasons: list[str]`), `Gate` (dataclass di soglie), `measure(x: np.ndarray, sr: int) -> Metrics`, `apply_gate(mt: Metrics, sr: int, g: Gate | None = None) -> Metrics` (riempie `reasons` con chiavi i18n `vc_gate_*`, prima = motivo principale), `trim_edges(x, sr, pad_ms=300.0) -> np.ndarray`, `read_wav(path) -> (np.ndarray float32, sr)`, `write_wav(path, x, sr)`, `gate_from_env() -> Gate`, `SAMPLE_RATE = 24000`.
- Consumes: niente dei task precedenti.

- [ ] **Step 1: Scrivere i test con segnali sintetici**

`test/test_voice_clone_audio.py`:

```python
"""Gate acustico delle voci campionate (spec §5.2, §5.3), senza ffmpeg.

I segnali sono sintetici e deterministici: raffiche di rumore bianco a
-20 dBFS (il "parlato") separate da pause, sopra un fondo bianco a -80 dBFS.
Le misure del worker (`tools/voice_prompts/audio.py`) le trattano come
parlato pulito; ogni difetto e' costruito alterando una cosa sola.
"""
import numpy as np
import pytest

import voice_clone_audio as vca

SR = vca.SAMPLE_RATE


def _db(v):
    return 10.0 ** (v / 20.0)


def _parlato(seconds=15.0, burst=0.45, pause=0.15, level_db=-20.0,
             floor_db=-80.0, lowpass_hz=None, seed=7):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    x = rng.standard_normal(n).astype(np.float32) * _db(floor_db)
    t = 0.0
    while t < seconds:
        a, b = int(t * SR), min(n, int((t + burst) * SR))
        x[a:b] += rng.standard_normal(b - a).astype(np.float32) * _db(level_db)
        t += burst + pause
    if lowpass_hz:
        spec = np.fft.rfft(x.astype(np.float64))
        freq = np.fft.rfftfreq(n, 1.0 / SR)
        spec[freq > lowpass_hz] = 0.0
        x = np.fft.irfft(spec, n=n).astype(np.float32)
    return x


def test_parlato_pulito_passa():
    mt = vca.apply_gate(vca.measure(_parlato(), SR), SR)
    assert mt.reasons == [], mt
    assert 12.0 <= mt.duration <= 20.0
    assert mt.snr_db >= 22.0 and mt.clarity >= 36.0
    assert 0.55 <= mt.speech_ratio <= 0.98
    assert mt.bandwidth_hz >= 0.78 * SR / 2
    assert mt.clip_runs == 0


def test_troppo_breve():
    mt = vca.apply_gate(vca.measure(_parlato(seconds=6.0), SR), SR)
    assert mt.reasons[0] == "vc_gate_short"


def test_troppo_lunga():
    mt = vca.apply_gate(vca.measure(_parlato(seconds=24.0), SR), SR)
    assert mt.reasons[0] == "vc_gate_long"


def test_fondo_rumoroso():
    mt = vca.apply_gate(vca.measure(_parlato(floor_db=-32.0), SR), SR)
    assert "vc_gate_noise" in mt.reasons


def test_pausa_interna_lunga():
    x = _parlato(seconds=15.0)
    x[int(6.0 * SR):int(7.6 * SR)] = 0.0          # buco da 1,6 s
    mt = vca.apply_gate(vca.measure(x, SR), SR)
    assert "vc_gate_pauses" in mt.reasons
    assert mt.longest_gap > 1.0


def test_poco_parlato():
    mt = vca.apply_gate(vca.measure(_parlato(burst=0.3, pause=0.5), SR), SR)
    assert "vc_gate_pauses" in mt.reasons


def test_nessuna_pausa():
    """Micro-pause sotto i 40 ms: la maschera le chiude come occlusive,
    quindi per il VAD e' parlato continuo senza una pausa vera."""
    mt = vca.apply_gate(vca.measure(_parlato(burst=0.10, pause=0.03), SR), SR)
    assert "vc_gate_nopause" in mt.reasons
    assert mt.speech_ratio > 0.98


def test_banda_tagliata():
    mt = vca.apply_gate(vca.measure(_parlato(lowpass_hz=6000), SR), SR)
    assert "vc_gate_band" in mt.reasons
    assert mt.bandwidth_hz < 7000


def test_clipping():
    x = np.clip(_parlato(level_db=-2.0) * 4.0, -1.0, 1.0)
    mt = vca.apply_gate(vca.measure(x, SR), SR)
    assert "vc_gate_clip" in mt.reasons
    assert mt.clip_runs > 4


def test_gate_da_env(monkeypatch):
    monkeypatch.setenv("ABM_VOICE_CLONE_MIN_SEC", "3")
    monkeypatch.setenv("ABM_VOICE_CLONE_MAX_SEC", "8")
    g = vca.gate_from_env()
    assert (g.min_sec, g.max_sec) == (3.0, 8.0)
    mt = vca.apply_gate(vca.measure(_parlato(seconds=6.0), SR), SR, g)
    assert "vc_gate_short" not in mt.reasons


def test_trim_edges_taglia_i_silenzi_ma_lascia_il_margine():
    core = _parlato(seconds=4.0)
    x = np.concatenate([np.zeros(2 * SR, np.float32), core, np.zeros(3 * SR, np.float32)])
    y = vca.trim_edges(x, SR, pad_ms=300.0)
    assert abs(len(y) / SR - 4.6) < 0.15          # 4 s + 2 x 0,3 s


def test_wav_roundtrip(tmp_path):
    x = _parlato(seconds=2.0)
    p = tmp_path / "a.wav"
    vca.write_wav(str(p), x, SR)
    y, sr = vca.read_wav(str(p))
    assert sr == SR and len(y) == len(x)
    assert np.max(np.abs(y - x)) < 1e-3
```

- [ ] **Step 2: Eseguire i test e vederli fallire**

Run: `python -m pytest test/test_voice_clone_audio.py -v --tb=short`
Expected: `No module named 'voice_clone_audio'`.

- [ ] **Step 3: Scrivere la prima parte del modulo**

`voice_clone_audio.py` (questa parte; probe/conversione/ASR si aggiungono nei task 3 e 4 in coda allo stesso file):

```python
"""Conversione, misure, gate e verifica ASR dei campioni vocali (spec §5).

Le misure sono il porting di `tools/voice_prompts/audio.py` del worker
VoxCPM, ridotto a numpy: dove il worker usa scipy (highpass, K-weighting
del loudness) o librosa (STFT) qui lavorano ffmpeg (`highpass`, `ebur128`)
o un framing rfft esplicito. Le soglie sono quelle del worker, cosi' un
campione che passa qui e' dello stesso ordine di qualita' delle voci di
catalogo.
"""
from __future__ import annotations

import math
import os
import wave
from dataclasses import dataclass, field, asdict

import numpy as np

EPS = 1e-12
SAMPLE_RATE = 24000          # il wav che VoxCPM riceve (spec §5.1)
TARGET_LUFS = -23.0          # come `normalize()` del worker
PEAK_DBFS = -1.0
CLARITY_HI_HZ = 4000.0
CLARITY_W = 0.40


# ---------------------------------------------------------------------------
# wav s16 mono
# ---------------------------------------------------------------------------
def read_wav(path):
    """wav PCM s16 mono -> (float32 in [-1, 1], sample rate)."""
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError(f"atteso wav s16 mono: {path}")
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return x, sr


def write_wav(path, x, sr):
    y = np.clip(np.asarray(x, dtype=np.float32), -1.0, 1.0)
    pcm = (y * 32767.0).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm)


# ---------------------------------------------------------------------------
# VAD energetico e metriche (porting numpy del worker)
# ---------------------------------------------------------------------------
def frame_db(x, sr, win_ms=25.0, hop_ms=10.0):
    win = max(64, int(sr * win_ms / 1000))
    hop = max(16, int(sr * hop_ms / 1000))
    if len(x) < win:
        return np.array([-120.0]), hop
    n = 1 + (len(x) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    frames = x[idx]
    rms = np.sqrt(np.mean(frames * frames, axis=1) + EPS)
    return 20.0 * np.log10(rms + EPS), hop


def speech_mask(db):
    """Maschera di parlato: soglia adattiva sul rumore di fondo."""
    floor = float(np.percentile(db, 10))
    peak = float(np.percentile(db, 95))
    thr = max(floor + 8.0, peak - 35.0)
    m = db > thr
    if m.any():
        idx = np.flatnonzero(m)
        for a, b in zip(idx[:-1], idx[1:]):
            if 1 < b - a <= 4:          # occlusive, non pause
                m[a:b] = True
    return m, floor, thr


def speech_segments(m, hop, sr):
    out, start = [], None
    for i, v in enumerate(m):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start * hop / sr, i * hop / sr))
            start = None
    if start is not None:
        out.append((start * hop / sr, len(m) * hop / sr))
    return out


def _power_frames(x, n_fft, hop):
    """|rfft|^2 dei fotogrammi con finestra di Hann; (frames, bins)."""
    x = np.asarray(x, dtype=np.float64)
    if len(x) < n_fft + hop:
        return None
    n = 1 + (len(x) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    return np.abs(np.fft.rfft(x[idx] * np.hanning(n_fft), axis=1)) ** 2


def speech_bandwidth(x, sr, m, hop):
    """Frequenza oltre la quale lo spettro medio del parlato crolla.

    Come nel worker (n_fft 2048, media sui fotogrammi di parlato, media
    mobile su 5 bin, riferimento = massimo nei primi n_fft/8 bin, banda =
    ultimo bin sopra ref-50 dB), ma con framing rfft senza `librosa.stft`:
    i fotogrammi non sono centrati, quindi si allineano alla maschera per
    indice fino al piu' corto dei due.
    """
    n_fft = 2048
    S = _power_frames(x, n_fft, hop)
    if S is None:
        return 0.0
    frames = min(S.shape[0], len(m))
    sel = m[:frames]
    if sel.sum() < 3:
        sel = np.ones(frames, dtype=bool)
    spec = S[:frames][sel].mean(axis=0)
    spec_db = 10.0 * np.log10(spec + EPS)
    spec_db = np.convolve(spec_db, np.ones(5) / 5.0, mode="same")
    ref = float(spec_db[: n_fft // 8].max())
    above = np.flatnonzero(spec_db > ref - 50.0)
    if len(above) == 0:
        return 0.0
    return float(above[-1] * sr / n_fft)


def band_snr(x, sr, f_lo=0.0, n_fft=1024, hop=256):
    """SNR in dB dentro una banda: 40% di fotogrammi piu' forti contro il
    20% piu' deboli, stessa selezione per ogni banda (vedi worker)."""
    S = _power_frames(x, n_fft, hop)
    if S is None:
        return 0.0
    freq = np.fft.rfftfreq(n_fft, 1.0 / sr)
    tot = S.sum(axis=1)
    voice = tot > np.percentile(tot, 60)
    floor = tot <= np.percentile(tot, 20)
    if not voice.any() or not floor.any():
        return 0.0
    band = S[:, freq >= f_lo].sum(axis=1)
    return float(10.0 * np.log10(band[voice].mean() / max(band[floor].mean(), EPS)))


def clipping_runs(x, thr=0.999, run=3):
    hot = np.abs(x) >= thr
    if not hot.any():
        return 0
    d = np.diff(hot.astype(np.int8))
    starts = np.flatnonzero(d == 1) + 1
    ends = np.flatnonzero(d == -1) + 1
    if hot[0]:
        starts = np.r_[0, starts]
    if hot[-1]:
        ends = np.r_[ends, len(hot)]
    return int(np.sum((ends - starts) >= run))


def trim_edges(x, sr, pad_ms=300.0):
    """Toglie i silenzi ai due estremi lasciando `pad_ms` di margine."""
    db, hop = frame_db(x, sr)
    m, _, _ = speech_mask(db)
    if not m.any():
        return x
    idx = np.flatnonzero(m)
    pad = int(sr * pad_ms / 1000)
    a = max(0, idx[0] * hop - pad)
    b = min(len(x), idx[-1] * hop + hop + pad)
    return x[a:b]


@dataclass
class Metrics:
    duration: float
    snr_db: float
    snr_hi_db: float
    clarity: float
    speech_ratio: float
    bandwidth_hz: float
    clip_runs: int
    longest_gap: float
    peak_dbfs: float
    dc_offset: float
    lufs: float = float("nan")      # la misura ffmpeg (Task 3); nan = non misurata
    reasons: list = field(default_factory=list)

    def as_dict(self):
        d = asdict(self)
        if not math.isfinite(d["lufs"]):
            d["lufs"] = None
        return d


def measure(x, sr):
    x = np.asarray(x, dtype=np.float32)
    db, hop = frame_db(x, sr)
    m, floor, _ = speech_mask(db)
    spd = db[m]
    snr = float(np.median(spd) - floor) if spd.size else 0.0
    segs = speech_segments(m, hop, sr)
    gap = 0.0
    for (_, e), (s2, _) in zip(segs[:-1], segs[1:]):
        gap = max(gap, s2 - e)
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    snr_lo = band_snr(x, sr, 0.0)
    snr_hi = band_snr(x, sr, CLARITY_HI_HZ)
    return Metrics(
        duration=round(len(x) / sr, 3),
        snr_db=round(snr, 2),
        snr_hi_db=round(snr_hi, 2),
        clarity=round(snr_lo + CLARITY_W * snr_hi, 2),
        speech_ratio=round(float(m.mean()), 4),
        bandwidth_hz=round(speech_bandwidth(x, sr, m, hop), 1),
        clip_runs=clipping_runs(x),
        longest_gap=round(gap, 3),
        peak_dbfs=round(20.0 * math.log10(peak + EPS), 2),
        dc_offset=round(float(np.mean(x)), 6) if x.size else 0.0,
    )


@dataclass
class Gate:
    """Soglie del worker (`Gate` di audio.py) piu' la finestra di durata D7."""
    min_sec: float = 12.0
    max_sec: float = 20.0
    min_snr_db: float = 22.0
    min_clarity: float = 36.0
    min_speech_ratio: float = 0.55
    max_speech_ratio: float = 0.98
    min_bandwidth_ratio: float = 0.78   # rispetto a Nyquist
    max_clip_runs: int = 4
    max_gap: float = 1.0


def _env_float(name, default):
    raw = (os.environ.get(name) or "").strip().replace(",", ".")
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def gate_from_env():
    return Gate(min_sec=_env_float("ABM_VOICE_CLONE_MIN_SEC", 12.0),
                max_sec=_env_float("ABM_VOICE_CLONE_MAX_SEC", 20.0))


def apply_gate(mt, sr, g=None):
    """Riempie `mt.reasons` con le chiavi i18n della spec §5.3, nell'ordine
    in cui l'utente le deve sentire: prima la durata (si vede a occhio),
    poi il rumore, le pause, la banda, la distorsione."""
    g = g or gate_from_env()
    nyq = sr / 2.0
    why = []
    if mt.duration < g.min_sec:
        why.append("vc_gate_short")
    elif mt.duration > g.max_sec:
        why.append("vc_gate_long")
    if mt.snr_db < g.min_snr_db or mt.clarity < g.min_clarity:
        why.append("vc_gate_noise")
    if mt.speech_ratio < g.min_speech_ratio or mt.longest_gap > g.max_gap:
        why.append("vc_gate_pauses")
    if mt.speech_ratio > g.max_speech_ratio:
        why.append("vc_gate_nopause")
    if mt.bandwidth_hz < g.min_bandwidth_ratio * nyq:
        why.append("vc_gate_band")
    if mt.clip_runs > g.max_clip_runs:
        why.append("vc_gate_clip")
    mt.reasons = why
    return mt
```

- [ ] **Step 4: Eseguire i test**

Run: `python -m pytest test/test_voice_clone_audio.py -v --tb=short`
Expected: 12 PASS. Se un test sintetico cade per pochi dB (le soglie sono tarate su voci vere), correggere il **livello del segnale di prova** nella fixture `_parlato` (es. `floor_db` più basso per il caso pulito, più alto per `test_fondo_rumoroso`), mai le soglie di `Gate`: quelle sono la spec.

- [ ] **Step 5: Commit**

```
git add voice_clone_audio.py test/test_voice_clone_audio.py
git commit -m "feat(voice-clone): misure acustiche e gate del campione (porting numpy)"
```

---

### Task 3: Probe, conversione e normalizzazione con ffmpeg

**Files:**
- Modify: `voice_clone_audio.py` (in coda)
- Test: `test/test_voice_clone_audio.py` (in coda)

**Interfaces:**
- Produces: `class SampleRejected(Exception)` con attributo `reason` (chiave i18n) e `detail` (str); `probe(path) -> {"duration": float, "codec": str, "sample_rate": int, "channels": int}` (solleva `SampleRejected("vc_gate_format")` se non c'è audio); `convert(src, dst_wav)` (ffmpeg → wav mono 24 kHz s16, highpass 60 Hz); `loudness_lufs(wav_path) -> float` (ffmpeg `ebur128`; `nan` se non misurabile); `normalize(x, sr) -> (np.ndarray, float lufs_misurata)` (trim + guadagno a `TARGET_LUFS` + tetto `PEAK_DBFS`); `prepare_sample(src_path, dst_wav, *, gate=None) -> Metrics` (pipeline intera: probe → convert → normalize → measure → apply_gate; scrive `dst_wav` solo se il gate passa, altrimenti solleva `SampleRejected` con `reason = metrics.reasons[0]` e attributo `metrics`); `ACCEPTED_EXT = ("wav", "mp3", "webm", "opus", "ogg", "m4a", "mp4")`; `MAX_PROBE_SEC = 60.0`, `MIN_PROBE_SEC = 3.0`.
- Consumes: Task 2 (`measure`, `apply_gate`, `trim_edges`, `read_wav`, `write_wav`, `Gate`).

- [ ] **Step 1: Aggiungere i test ffmpeg**

In coda a `test/test_voice_clone_audio.py`:

```python
import shutil
import subprocess

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                  reason="ffmpeg/ffprobe non installati")


def _wav_parlato(tmp_path, name="in.wav", **kw):
    p = tmp_path / name
    vca.write_wav(str(p), _parlato(**kw), SR)
    return str(p)


def _codifica(src, dst, *args):
    """Ricodifica con ffmpeg; SKIP se la build locale non ha l'encoder."""
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, *args, dst],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"encoder assente in questa build di ffmpeg: {r.stderr[-120:]}")
    return dst


@needs_ffmpeg
def test_probe_legge_durata_e_canali(tmp_path):
    src = _wav_parlato(tmp_path, seconds=15.0)
    info = vca.probe(src)
    assert abs(info["duration"] - 15.0) < 0.2
    assert info["channels"] == 1 and info["sample_rate"] == SR


@needs_ffmpeg
def test_probe_rifiuta_un_file_senza_audio(tmp_path):
    p = tmp_path / "x.mp3"
    p.write_bytes(b"non sono audio" * 100)
    with pytest.raises(vca.SampleRejected) as ei:
        vca.probe(str(p))
    assert ei.value.reason == "vc_gate_format"


@needs_ffmpeg
def test_convert_da_opus_stereo_48k(tmp_path):
    """Il caso MediaRecorder: webm/opus a 48 kHz. Esce wav mono 24 kHz s16."""
    src = _wav_parlato(tmp_path, seconds=14.0)
    webm = _codifica(src, str(tmp_path / "rec.webm"), "-ac", "2", "-ar", "48000",
                     "-c:a", "libopus", "-b:a", "96k")
    out = str(tmp_path / "out.wav")
    vca.convert(webm, out)
    x, sr = vca.read_wav(out)
    assert sr == SR and abs(len(x) / SR - 14.0) < 0.3


@needs_ffmpeg
def test_loudness_e_normalize(tmp_path):
    src = _wav_parlato(tmp_path, seconds=14.0, level_db=-34.0)
    lu = vca.loudness_lufs(src)
    assert lu < -30.0                     # parte piano (rumore bianco: K-weighting ~ +3 dB)
    x, sr = vca.read_wav(src)
    y, lu_in = vca.normalize(x, sr)
    assert abs(lu_in - lu) < 0.5
    out = str(tmp_path / "norm.wav")
    vca.write_wav(out, y, sr)
    assert abs(vca.loudness_lufs(out) - vca.TARGET_LUFS) < 1.5
    assert 20.0 * np.log10(np.max(np.abs(y))) <= vca.PEAK_DBFS + 0.1


@needs_ffmpeg
def test_prepare_sample_passa_e_scrive_il_wav(tmp_path):
    src = _wav_parlato(tmp_path, seconds=15.0)
    dst = str(tmp_path / "sample.wav")
    mt = vca.prepare_sample(src, dst)
    assert mt.reasons == [] and os.path.exists(dst)
    assert abs(mt.lufs - vca.TARGET_LUFS) < 1.5


@needs_ffmpeg
def test_prepare_sample_rifiuta_e_non_scrive(tmp_path):
    src = _wav_parlato(tmp_path, seconds=6.0)
    dst = str(tmp_path / "sample.wav")
    with pytest.raises(vca.SampleRejected) as ei:
        vca.prepare_sample(src, dst)
    assert ei.value.reason == "vc_gate_short"
    assert ei.value.metrics.duration < 12.0
    assert not os.path.exists(dst)


@needs_ffmpeg
def test_prepare_sample_mp3_64k_cade_per_banda(tmp_path):
    src = _wav_parlato(tmp_path, seconds=15.0)
    mp3 = _codifica(src, str(tmp_path / "low.mp3"), "-ar", "22050",
                    "-c:a", "libmp3lame", "-b:a", "32k")
    with pytest.raises(vca.SampleRejected) as ei:
        vca.prepare_sample(mp3, str(tmp_path / "s.wav"))
    assert "vc_gate_band" in ei.value.metrics.reasons
```

Aggiungere `import os` in testa al file di test.

- [ ] **Step 2: Eseguire e vedere fallire**

Run: `python -m pytest test/test_voice_clone_audio.py -v --tb=short -k "probe or convert or loudness or prepare"`
Expected: `AttributeError: module 'voice_clone_audio' has no attribute 'probe'` (o SKIPPED senza ffmpeg: in quel caso installarlo prima di proseguire, il task non è verificabile senza).

- [ ] **Step 3: Aggiungere probe, convert, loudness, normalize, prepare_sample**

In coda a `voice_clone_audio.py`:

```python
# ---------------------------------------------------------------------------
# ffmpeg: probe, conversione, loudness
# ---------------------------------------------------------------------------
import json
import re
import shutil
import subprocess
import sys
import tempfile

_SUBPROCESS_FLAGS = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
_TEXT = {"text": True, "encoding": "utf-8", "errors": "replace"}
ACCEPTED_EXT = ("wav", "mp3", "webm", "opus", "ogg", "m4a", "mp4")
MIN_PROBE_SEC = 3.0
MAX_PROBE_SEC = 60.0
_FFMPEG_TIMEOUT = 120


class SampleRejected(Exception):
    """Il campione non va bene. `reason` e' una chiave i18n `vc_gate_*`."""

    def __init__(self, reason, detail="", metrics=None):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.metrics = metrics


def _tool(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} non trovato nel PATH")
    return path


def probe(path):
    """Il primo stream audio del file: durata, codec, sample rate, canali."""
    cmd = [_tool("ffprobe"), "-v", "error", "-print_format", "json",
           "-show_streams", "-show_format", path]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30, **_TEXT, **_SUBPROCESS_FLAGS)
        data = json.loads(r.stdout or "{}")
    except (subprocess.SubprocessError, ValueError) as e:
        raise SampleRejected("vc_gate_format", f"ffprobe: {e}")
    audio = [s for s in data.get("streams") or [] if s.get("codec_type") == "audio"]
    if r.returncode != 0 or not audio:
        raise SampleRejected("vc_gate_format", "nessuno stream audio")
    s = audio[0]
    dur = s.get("duration") or (data.get("format") or {}).get("duration") or 0
    try:
        dur = float(dur)
    except (TypeError, ValueError):
        dur = 0.0
    if dur <= 0.0:
        # webm di MediaRecorder spesso non dichiara la durata: la si misura
        # decodificando, e' l'unico modo affidabile.
        dur = _decoded_seconds(path)
    if dur < MIN_PROBE_SEC:
        raise SampleRejected("vc_gate_short", f"{dur:.1f}s")
    if dur > MAX_PROBE_SEC:
        raise SampleRejected("vc_gate_long", f"{dur:.1f}s")
    return {"duration": round(dur, 3), "codec": str(s.get("codec_name") or ""),
            "sample_rate": int(s.get("sample_rate") or 0), "channels": int(s.get("channels") or 0)}


def _decoded_seconds(path):
    cmd = [_tool("ffmpeg"), "-v", "error", "-i", path, "-f", "null", "-",
           "-stats", "-loglevel", "info"]
    r = subprocess.run(cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT, **_TEXT, **_SUBPROCESS_FLAGS)
    m = re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
    if not m:
        return 0.0
    h, mi, s = m[-1]
    return int(h) * 3600 + int(mi) * 60 + float(s)


def convert(src, dst_wav):
    """Qualunque ingresso -> wav mono 24 kHz s16 con highpass a 60 Hz (§5.1)."""
    cmd = [_tool("ffmpeg"), "-y", "-v", "error", "-i", src, "-vn", "-ac", "1",
           "-ar", str(SAMPLE_RATE), "-af", "highpass=f=60", "-c:a", "pcm_s16le",
           "-f", "wav", dst_wav]
    r = subprocess.run(cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT, **_TEXT, **_SUBPROCESS_FLAGS)
    if r.returncode != 0 or not os.path.exists(dst_wav) or os.path.getsize(dst_wav) < 100:
        raise SampleRejected("vc_gate_format", (r.stderr or "")[-300:])


_EBU_I = re.compile(r"\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS")


def loudness_lufs(wav_path):
    """Loudness integrata BS.1770 via `ebur128` di ffmpeg. nan se assente."""
    cmd = [_tool("ffmpeg"), "-v", "info", "-nostats", "-i", wav_path,
           "-af", "ebur128=framelog=quiet", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT, **_TEXT, **_SUBPROCESS_FLAGS)
    found = _EBU_I.findall(r.stderr or "")
    return float(found[-1]) if found else float("nan")


def normalize(x, sr):
    """dc -> trim 300 ms -> guadagno a TARGET_LUFS -> tetto PEAK_DBFS.

    Ritorna (segnale, loudness misurata prima del guadagno). La misura passa
    da ffmpeg su un wav temporaneo: il guadagno e' lineare, quindi la
    loudness finale e' esattamente quella misurata piu' il guadagno.
    """
    y = np.asarray(x, dtype=np.float32)
    y = y - float(np.mean(y))
    y = trim_edges(y, sr, pad_ms=300.0)
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        write_wav(tmp, y, sr)
        lu = loudness_lufs(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    gain_db = 0.0 if not math.isfinite(lu) else TARGET_LUFS - lu
    y = y * (10.0 ** (gain_db / 20.0))
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    ceil = 10.0 ** (PEAK_DBFS / 20.0)
    if peak > ceil:
        y = y * (ceil / peak)
    return y.astype(np.float32), lu


def prepare_sample(src_path, dst_wav, *, gate=None):
    """Pipeline intera (§5.1-5.3). Scrive `dst_wav` solo se il gate passa."""
    probe(src_path)
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        convert(src_path, tmp)
        x, sr = read_wav(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    y, _lu_in = normalize(x, sr)
    mt = apply_gate(measure(y, sr), sr, gate)
    if mt.reasons:
        raise SampleRejected(mt.reasons[0], "; ".join(mt.reasons), metrics=mt)
    write_wav(dst_wav, y, sr)
    mt.lufs = round(loudness_lufs(dst_wav), 2)     # misurata sul file consegnato
    return mt
```

- [ ] **Step 4: Eseguire tutti i test del modulo**

Run: `python -m pytest test/test_voice_clone_audio.py -v --tb=short`
Expected: 19 PASS. Se `test_prepare_sample_mp3_64k_cade_per_banda` non cade per banda con la versione locale di lame, abbassare ulteriormente `-b:a` a `24k`: il caso da coprire è «sorgente a banda tagliata», il bitrate esatto non è nella spec.

- [ ] **Step 5: Commit**

```
git add voice_clone_audio.py test/test_voice_clone_audio.py
git commit -m "feat(voice-clone): conversione ffmpeg, loudness e pipeline del campione"
```

---

### Task 4: Verifica ASR con faster-whisper (`check_transcript`)

**Files:**
- Modify: `voice_clone_audio.py` (in coda)
- Test: `test/test_voice_clone_asr.py`

**Interfaces:**
- Produces: `init(data_dir)` (imposta la cartella dei modelli `<data_dir>/whisper`); `cer(ref, hyp) -> float`; `flatten(s) -> str`; `class AsrUnavailable(Exception)`; `check_transcript(wav_path, language, expected_text, *, timeout=None) -> {"cer": float, "heard": str, "seconds": float}` (solleva `AsrUnavailable` su errore/timeout/lock occupato); `asr_enabled() -> bool` (`ABM_VOICE_CLONE_ASR != "0"`); `max_cer() -> float` (`ABM_VOICE_CLONE_MAX_CER`, default 0.25); `_new_model(name, download_root)` (fabbrica sostituibile nei test); `unload_asr()`; `ASR_IDLE_UNLOAD_SEC = 600`.
- Consumes: niente oltre il modulo stesso.

- [ ] **Step 1: Scrivere i test con un modello finto**

`test/test_voice_clone_asr.py`:

```python
"""Verifica ASR del campione (spec §5.4) con un modello finto: faster_whisper
non si importa mai qui."""
import threading
import time

import pytest

import voice_clone_audio as vca


class _Seg:
    def __init__(self, text):
        self.text = text
        self.words = [1]


class _Modello:
    """Doppio di WhisperModel: ritorna la frase che gli si dice, con ritardo."""

    def __init__(self, testo="", ritardo=0.0, errore=None):
        self.testo, self.ritardo, self.errore = testo, ritardo, errore
        self.chiamate = []

    def transcribe(self, path, **kw):
        self.chiamate.append((path, kw))
        if self.ritardo:
            time.sleep(self.ritardo)
        if self.errore:
            raise self.errore
        return iter([_Seg(self.testo)]), None


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    vca.init(str(tmp_path))
    vca.unload_asr()
    monkeypatch.delenv("ABM_VOICE_CLONE_ASR", raising=False)
    monkeypatch.delenv("ABM_VOICE_CLONE_MAX_CER", raising=False)
    yield
    vca.unload_asr()


def _usa(monkeypatch, **kw):
    """Sostituisce la fabbrica del modello; ritorna la lista delle istanze
    create, cosi' i test contano i caricamenti."""
    istanze = []

    def _fabbrica(name, root):
        istanze.append(_Modello(**kw))
        return istanze[-1]
    monkeypatch.setattr(vca, "_new_model", _fabbrica)
    return istanze


def test_cer_e_flatten_come_il_worker():
    assert vca.flatten("Ogni mattina, apro la finestra!") == "ognimattinaaprolafinestra"
    assert vca.cer("abc", "abc") == 0.0
    assert vca.cer("abcd", "abxd") == 0.25
    assert vca.cer("", "x") == 1.0
    # cinese: tradizionale e semplificato sono la stessa lettura
    assert vca.cer("心裡", "心里") == 0.0


def test_check_transcript_ok(monkeypatch, tmp_path):
    ist = _usa(monkeypatch, testo="Ogni mattina apro la finestra.")
    out = vca.check_transcript(str(tmp_path / "s.wav"), "it", "Ogni mattina apro la finestra")
    assert out["cer"] == 0.0 and out["heard"].startswith("Ogni")
    assert out["seconds"] >= 0.0
    assert ist[0].chiamate[0][1]["language"] == "it"
    assert ist[0].chiamate[0][1]["beam_size"] == 1


def test_modello_caricato_una_volta_sola(monkeypatch, tmp_path):
    ist = _usa(monkeypatch, testo="x")
    vca.check_transcript(str(tmp_path / "a.wav"), "it", "x")
    vca.check_transcript(str(tmp_path / "b.wav"), "it", "x")
    assert len(ist) == 1


def test_cer_alto_e_solo_un_numero(monkeypatch, tmp_path):
    _usa(monkeypatch, testo="tutta un'altra frase che non c'entra")
    out = vca.check_transcript(str(tmp_path / "s.wav"), "it", "Ogni mattina apro la finestra")
    assert out["cer"] > vca.max_cer()


def test_timeout_solleva_unavailable(monkeypatch, tmp_path):
    _usa(monkeypatch, testo="x", ritardo=1.0)
    with pytest.raises(vca.AsrUnavailable):
        vca.check_transcript(str(tmp_path / "s.wav"), "it", "x", timeout=0.2)


def test_errore_del_modello_solleva_unavailable(monkeypatch, tmp_path):
    _usa(monkeypatch, testo="x", errore=RuntimeError("ctranslate2 esploso"))
    with pytest.raises(vca.AsrUnavailable):
        vca.check_transcript(str(tmp_path / "s.wav"), "it", "x")


def test_caricamento_fallito_solleva_unavailable(monkeypatch, tmp_path):
    def _boom(name, root):
        raise OSError("download fallito")
    monkeypatch.setattr(vca, "_new_model", _boom)
    with pytest.raises(vca.AsrUnavailable):
        vca.check_transcript(str(tmp_path / "s.wav"), "it", "x")


def test_lock_occupato_solleva_unavailable(monkeypatch, tmp_path):
    _usa(monkeypatch, testo="x", ritardo=0.8)
    esiti = []

    def _prima():
        try:
            esiti.append(vca.check_transcript(str(tmp_path / "a.wav"), "it", "x", timeout=5))
        except Exception as e:
            esiti.append(e)
    t = threading.Thread(target=_prima, daemon=True)
    t.start()
    time.sleep(0.1)
    with pytest.raises(vca.AsrUnavailable):
        vca.check_transcript(str(tmp_path / "b.wav"), "it", "x", timeout=0.1)
    t.join(5)
    assert isinstance(esiti[0], dict)


def test_unload_dopo_inattivita(monkeypatch, tmp_path):
    ist = _usa(monkeypatch, testo="x")
    monkeypatch.setattr(vca, "ASR_IDLE_UNLOAD_SEC", 0.2)
    vca.check_transcript(str(tmp_path / "a.wav"), "it", "x")
    time.sleep(0.6)
    assert vca._asr_model is None
    vca.check_transcript(str(tmp_path / "b.wav"), "it", "x")
    assert len(ist) == 2


def test_env_interruttore_e_soglia(monkeypatch):
    assert vca.asr_enabled() is True
    monkeypatch.setenv("ABM_VOICE_CLONE_ASR", "0")
    assert vca.asr_enabled() is False
    monkeypatch.setenv("ABM_VOICE_CLONE_MAX_CER", "0,3")
    assert vca.max_cer() == 0.3
```

- [ ] **Step 2: Eseguire e vedere fallire**

Run: `python -m pytest test/test_voice_clone_asr.py -v --tb=short`
Expected: `AttributeError: module 'voice_clone_audio' has no attribute 'init'`.

- [ ] **Step 3: Aggiungere la parte ASR al modulo**

In coda a `voice_clone_audio.py`:

```python
# ---------------------------------------------------------------------------
# Verifica ASR: faster-whisper su CPU, un lock, scarico dopo inattivita'
# ---------------------------------------------------------------------------
import threading
import time
import unicodedata

ASR_IDLE_UNLOAD_SEC = 600
_data_dir = None
_asr_lock = threading.Lock()       # una trascrizione alla volta (§5.4)
_asr_state_lock = threading.Lock()
_asr_model = None
_asr_last_used = 0.0
_asr_timer = None
_zh_conv = None


class AsrUnavailable(Exception):
    """Verifica non eseguibile ora (errore, timeout, CPU occupata): il
    campione non passa, risposta `vc_gate_asr_unavailable` (§5.4)."""


def init(data_dir):
    """Cartella dati: i modelli whisper vanno in `<data_dir>/whisper`."""
    global _data_dir
    _data_dir = str(data_dir)


def asr_enabled():
    return (os.environ.get("ABM_VOICE_CLONE_ASR") or "1").strip() != "0"


def max_cer():
    return _env_float("ABM_VOICE_CLONE_MAX_CER", 0.25)


def _asr_model_name():
    return (os.environ.get("ABM_VOICE_CLONE_ASR_MODEL") or "base").strip() or "base"


def _asr_timeout():
    return _env_float("ABM_VOICE_CLONE_ASR_TIMEOUT_SEC", 120.0)


def _hans(s):
    """Cinese tradizionale -> semplificato, come nel worker: si confrontano
    le letture, non le grafie."""
    global _zh_conv
    if not re.search(r"[㐀-鿿]", s):
        return s
    if _zh_conv is None:
        try:
            from zhconv import convert as _zh_conv
        except ImportError:
            return s
    return _zh_conv(s, "zh-cn")


def flatten(s):
    """Solo lettere e cifre, minuscole, niente spazi (`_flatten` del worker)."""
    s = unicodedata.normalize("NFKC", _hans(s or "")).lower()
    return "".join(c for c in s if c.isalnum())


def cer(ref, hyp):
    """Distanza di edit sui caratteri, normalizzata sulla lunghezza attesa."""
    a, b = flatten(ref), flatten(hyp)
    if not a:
        return 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return round(prev[-1] / len(a), 4)


def _new_model(name, download_root):
    """Fabbrica del modello: i test la sostituiscono."""
    from faster_whisper import WhisperModel
    return WhisperModel(name, device="cpu", compute_type="int8", download_root=download_root)


def _whisper_dir():
    base = _data_dir or os.environ.get("ABM_DATA_DIR") or tempfile.gettempdir()
    path = os.path.join(base, "whisper")
    os.makedirs(path, exist_ok=True)
    return path


def unload_asr():
    global _asr_model, _asr_timer
    with _asr_state_lock:
        _asr_model = None
        if _asr_timer is not None:
            _asr_timer.cancel()
            _asr_timer = None


def _unload_if_idle():
    global _asr_model, _asr_timer
    with _asr_state_lock:
        _asr_timer = None
        if _asr_model is not None and time.monotonic() - _asr_last_used >= ASR_IDLE_UNLOAD_SEC:
            _asr_model = None
            print("[voice_clone_audio] modello whisper scaricato per inattivita'")


def _arm_unload_timer():
    global _asr_timer
    with _asr_state_lock:
        if _asr_timer is not None:
            _asr_timer.cancel()
        _asr_timer = threading.Timer(ASR_IDLE_UNLOAD_SEC + 0.05, _unload_if_idle)
        _asr_timer.daemon = True
        _asr_timer.start()


def _get_model():
    global _asr_model
    with _asr_state_lock:
        if _asr_model is not None:
            return _asr_model
    name = _asr_model_name()
    t0 = time.monotonic()
    model = _new_model(name, _whisper_dir())
    print(f"[voice_clone_audio] modello whisper '{name}' caricato in {time.monotonic() - t0:.1f}s")
    with _asr_state_lock:
        _asr_model = model
    return model


def _transcribe(wav_path, language):
    model = _get_model()
    segs, _ = model.transcribe(wav_path, language=language, beam_size=1, word_timestamps=True)
    return " ".join((s.text or "").strip() for s in segs).strip()


def check_transcript(wav_path, language, expected_text, *, timeout=None):
    """CER fra la frase guidata e quel che whisper sente nel campione.

    Gira in un thread con timeout; il lock `_asr_lock` serializza le
    trascrizioni. Un lock non ottenuto entro `timeout`, un errore del
    modello o un thread che non torna in tempo valgono `AsrUnavailable`:
    niente stato intermedio, l'utente riprova (§5.4).
    """
    global _asr_last_used
    timeout = _asr_timeout() if timeout is None else float(timeout)
    if not _asr_lock.acquire(timeout=timeout):
        raise AsrUnavailable("verifica gia' in corso")
    try:
        esito = {}

        def _run():
            try:
                esito["heard"] = _transcribe(wav_path, language)
            except BaseException as e:      # noqa: BLE001 - riportato al chiamante
                esito["error"] = e
        t0 = time.monotonic()
        th = threading.Thread(target=_run, name="vc-asr", daemon=True)
        th.start()
        th.join(timeout)
        if th.is_alive():
            raise AsrUnavailable(f"timeout dopo {timeout:.0f}s")
        if "error" in esito:
            raise AsrUnavailable(f"{type(esito['error']).__name__}: {esito['error']}")
        seconds = round(time.monotonic() - t0, 2)
    finally:
        _asr_lock.release()
    with _asr_state_lock:
        _asr_last_used = time.monotonic()
    _arm_unload_timer()
    heard = esito.get("heard", "")
    return {"cer": cer(expected_text, heard), "heard": heard, "seconds": seconds}
```

Nota sul timeout: il thread scaduto resta vivo finché `transcribe` non torna, ma il lock è già stato rilasciato dal chiamante; una nuova richiesta partirebbe in parallelo su una CPU già occupata. È accettato: il timeout (120 s) è un caso patologico e il rate limit del piano 2 (10/ora per cid) limita il danno.

- [ ] **Step 4: Eseguire i test**

Run: `python -m pytest test/test_voice_clone_asr.py -v --tb=short`
Expected: 10 PASS.

Poi tutto il modulo: `python -m pytest test/test_voice_clone_audio.py test/test_voice_clone_asr.py -v --tb=short` → verde.

- [ ] **Step 5: Commit**

```
git add voice_clone_audio.py test/test_voice_clone_asr.py
git commit -m "feat(voice-clone): verifica ASR del campione con faster-whisper su CPU"
```

---

### Task 5: Store, identità e bozza del campione (`voice_clone`)

**Files:**
- Create: `voice_clone.py`
- Test: `test/test_voice_clone.py`

**Interfaces:**
- Produces:
  - `init(data_dir)` (dopo `community_store.init`); `store() -> JsonStore`; `voices_dir() -> str` (`<data_dir>/voices`); `voice_dir(token) -> str`.
  - `STATES` (tupla), `TRANSITIONS: dict[str, set[str]]`, `HAS_SAMPLE: frozenset` (stati in cui il wav esiste), `class VoiceGone(ValueError)`, `class BadTransition(ValueError)`.
  - `new_token() -> str` (32 hex), `new_voice_code() -> str` (`XXXX-XXXX-XXXX`, alfabeto `ABCDEFGHJKMNPQRSTUVWXYZ23456789`), `normalize_voice_code(s) -> str`, `voice_id_of(rec) -> str` (`voxcpm:mine:<token>`), `token_of(voice_id) -> str | None`, `email_hash(email) -> str`.
  - `create_draft(cid, *, lang, locale, gender, prompt_text, sample_wav, original_path, original_ext, metrics: dict, ui_lang, now=None) -> dict` (record completo; stato `sample_ok`, sposta i file in `voice_dir(token)/sample.wav` e `original.<ext>`, sostituisce la bozza precedente dello stesso cid cancellandone i file).
  - `get(clone_id) -> dict | None`, `by_token(token)`, `by_voice_code(code)`, `by_manage_token(t)`, `by_resume_token(t, now=None)` (None se scaduto), `draft_for_cid(cid, now=None) -> dict | None`.
  - `transition(clone_id, new_state, patch=None, now=None) -> dict` (verifica `TRANSITIONS`, aggiorna `state` e `state_changed_at`).
  - `purge_stale_drafts(now=None) -> int` (bozze `sample_ok` scadute: file e record rimossi).
  - `remove_files(rec)` (locale + R2 `voices/<token>/`, best effort).
  - `public_view(rec) -> dict` (senza `token`, `manage_token`, `resume_token`, `owner_email`, `pending_confirm`, `confirm_locks`; con `voice_id` solo se `state == "ready"`).
  - `offered_languages() -> dict[str, list[str]]` (lingua → locali attivi del catalogo VoxCPM, solo lingue con frase guidata).
- Consumes: `community_store.init/JsonStore` (esistente), `voice_clone_prompts.languages()` (Task 1), `voxcpm_catalog.voices()` (esistente), `storage_backend.is_enabled/upload_file/delete_prefix` (esistente).

- [ ] **Step 1: Scrivere i test**

`test/test_voice_clone.py`:

```python
"""Store, identita', bozza e transizioni delle voci campionate (spec §6, §10)."""
import os
import time

import pytest

import community_store
import storage_backend
import voice_clone as vc
import voxcpm_catalog

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
PROMPT = "Ogni mattina apro la finestra prima di fare il caffe."


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    yield
    voxcpm_catalog.invalidate_cache()


def _file(tmp_path, name, content=b"RIFF-finto"):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def bozza(tmp_path, cid="cid-uno", **kw):
    args = dict(lang="it", locale="it-IT", gender="f", prompt_text=PROMPT,
                sample_wav=_file(tmp_path, f"{cid}-s.wav"),
                original_path=_file(tmp_path, f"{cid}-o.webm", b"webm"),
                original_ext="webm", metrics={"duration": 16.4, "snr_db": 31.2},
                ui_lang="it")
    args.update(kw)
    return vc.create_draft(cid, **args)


def test_codici_e_token():
    tok = vc.new_token()
    assert len(tok) == 32 and int(tok, 16) >= 0
    code = vc.new_voice_code()
    assert len(code) == 14 and code.count("-") == 2
    assert not set(code.replace("-", "")) & set("01ILO")
    assert vc.normalize_voice_code(" ab7k q2md-4h9x ") == "AB7K-Q2MD-4H9X"
    assert vc.token_of("voxcpm:mine:" + tok) == tok
    assert vc.token_of("voxcpm:v2:it-IT/Valentina") is None
    assert vc.token_of("voxcpm:mine:") is None


def test_create_draft_sposta_i_file_e_salva_il_record(tmp_path):
    rec = bozza(tmp_path)
    assert rec["state"] == "sample_ok" and rec["id"].startswith("vc_")
    assert rec["prompt_text"] == PROMPT and rec["prompt_version"].startswith("sha1:")
    d = vc.voice_dir(rec["token"])
    assert os.path.exists(os.path.join(d, "sample.wav"))
    assert os.path.exists(os.path.join(d, "original.webm"))
    assert rec["sample"]["original_ext"] == "webm" and rec["sample"]["snr_db"] == 31.2
    assert rec["devices"] == [{"cid": "cid-uno", "added_at": rec["created_at"], "via": "creator"}]
    assert rec["expires_at"] == rec["created_at"] + 24 * 3600
    assert vc.get(rec["id"])["token"] == rec["token"]
    assert vc.by_token(rec["token"])["id"] == rec["id"]
    assert vc.by_voice_code(rec["voice_code"].lower().replace("-", ""))["id"] == rec["id"]
    assert vc.by_manage_token(rec["manage_token"])["id"] == rec["id"]


def test_create_draft_rifiuta_lingua_o_genere_fuori_offerta(tmp_path):
    with pytest.raises(ValueError):
        bozza(tmp_path, lang="xx", locale="xx-XX")
    with pytest.raises(ValueError):
        bozza(tmp_path, gender="x")
    with pytest.raises(ValueError):
        bozza(tmp_path, locale="it-CH")       # locale non attivo nel catalogo


def test_nuova_bozza_dello_stesso_cid_sostituisce_la_precedente(tmp_path):
    a = bozza(tmp_path)
    b = bozza(tmp_path)
    assert vc.get(a["id"]) is None
    assert not os.path.exists(vc.voice_dir(a["token"]))
    assert vc.draft_for_cid("cid-uno")["id"] == b["id"]


def test_draft_for_cid_ignora_le_scadute(tmp_path):
    rec = bozza(tmp_path)
    assert vc.draft_for_cid("cid-uno", now=rec["expires_at"] + 1) is None
    assert vc.purge_stale_drafts(now=rec["expires_at"] + 1) == 1
    assert vc.get(rec["id"]) is None
    assert not os.path.exists(vc.voice_dir(rec["token"]))


def test_transizioni_ammesse_e_vietate(tmp_path):
    rec = bozza(tmp_path)
    vc.transition(rec["id"], "paid", {"payment": {"type": "voucher", "amount_eur": 5.0}})
    vc.transition(rec["id"], "demos_generating")
    vc.transition(rec["id"], "demos_ready")
    with pytest.raises(vc.BadTransition):
        vc.transition(rec["id"], "sample_ok")
    got = vc.transition(rec["id"], "ready")
    assert got["state"] == "ready" and got["state_changed_at"] >= rec["created_at"]
    assert got["ready_at"] == got["state_changed_at"]
    with pytest.raises(vc.BadTransition):
        vc.transition(rec["id"], "paid")
    with pytest.raises(vc.VoiceGone):
        vc.transition("vc_inesistente", "paid")


def test_public_view_non_espone_segreti(tmp_path):
    rec = bozza(tmp_path)
    pub = vc.public_view(rec)
    for k in ("token", "manage_token", "resume_token", "owner_email", "pending_confirm", "confirm_locks"):
        assert k not in pub
    assert "voice_id" not in pub            # non e' ready
    assert pub["voice_code"] == rec["voice_code"]
    vc.transition(rec["id"], "paid"); vc.transition(rec["id"], "demos_generating")
    vc.transition(rec["id"], "demos_ready"); ready = vc.transition(rec["id"], "ready")
    assert vc.public_view(ready)["voice_id"] == "voxcpm:mine:" + rec["token"]


def test_resume_token_scade(tmp_path):
    rec = bozza(tmp_path)
    t = rec["resume_token"]["value"]
    assert vc.by_resume_token(t, now=rec["created_at"] + 10)["id"] == rec["id"]
    assert vc.by_resume_token(t, now=rec["resume_token"]["expires_at"] + 1) is None
    assert vc.by_resume_token("sconosciuto") is None


def test_offered_languages_interseca_catalogo_e_frasi():
    off = vc.offered_languages()
    assert off == {"it": ["it-IT"], "en": ["en-GB", "en-US"]} or off == {"it": ["it-IT"], "en": ["en-US"]}


def test_remove_files_chiama_r2_se_attivo(tmp_path, monkeypatch):
    rec = bozza(tmp_path)
    cancellati = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: cancellati.append(p))
    vc.remove_files(rec)
    assert cancellati == ["voices/" + rec["token"] + "/"]
    assert not os.path.exists(vc.voice_dir(rec["token"]))
```

Nota su `test_offered_languages_interseca_catalogo_e_frasi`: la fixture dichiara `en` con locali `en-US` e `en-GB` ma le voci `en-GB` potrebbero mancare nel file; la funzione prende i locali **dalle voci** caricate (`voxcpm_catalog.voices()`), quindi il test accetta entrambe le forme. Nella fixture non c'è una voce `fr`, quindi `fr` non è offerta anche se ha la frase.

- [ ] **Step 2: Eseguire e vedere fallire**

Run: `python -m pytest test/test_voice_clone.py -v --tb=short`
Expected: `No module named 'voice_clone'`.

- [ ] **Step 3: Scrivere il modulo**

`voice_clone.py`:

```python
"""Voci campionate: store, identita', stati, dispositivi, resolver (spec §6,
§9, §10).

Il record vive in `_voice_clones.json` (community_store.JsonStore: lock,
scrittura atomica, .bak). I file del campione stanno in
`<data_dir>/voices/<token>/`, fuori dal tiering hot/cold dei job, con copia
su R2 sotto `voices/<token>/`. Nessun import di audiobook_app: la data dir
arriva da `init()`.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import threading
import time

import community_store
import storage_backend
import voice_clone_prompts
import voxcpm_catalog

VOICE_ID_PREFIX = "voxcpm:mine:"
R2_PREFIX = "voices/"
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # niente 0/O, 1/I/L
RESUME_TOKEN_DAYS = 30

STATES = ("sample_ok", "paid", "demos_generating", "demos_ready", "ready",
          "demo_failed", "refunded", "expired", "deleted")
TRANSITIONS = {
    "sample_ok": {"paid"},
    "paid": {"demos_generating", "refunded"},
    "demos_generating": {"demos_ready", "demo_failed", "refunded"},
    "demos_ready": {"ready", "demos_generating", "refunded"},
    "demo_failed": {"demos_generating", "refunded"},
    "ready": {"expired", "deleted"},
    "refunded": set(), "expired": set(), "deleted": set(),
}
HAS_SAMPLE = frozenset({"sample_ok", "paid", "demos_generating", "demos_ready",
                        "demo_failed", "ready"})
_STAMP_ON_ENTER = {"ready": "ready_at", "paid": "paid_at", "refunded": "refunded_at",
                   "expired": "expired_at", "deleted": "deleted_at"}

_lock = threading.RLock()
_data_dir = None
_store = None


class VoiceGone(ValueError):
    """Voce inesistente o senza campione (cancellata, rimborsata, scaduta)."""


class BadTransition(ValueError):
    """Passaggio di stato non previsto dalla tabella."""


def init(data_dir):
    global _data_dir, _store
    _data_dir = str(data_dir)
    _store = community_store.JsonStore("_voice_clones.json")
    os.makedirs(voices_dir(), exist_ok=True)


def store():
    if _store is None:
        raise RuntimeError("voice_clone.init() must be called first")
    return _store


def voices_dir():
    return os.path.join(_data_dir, "voices")


def voice_dir(token):
    return os.path.join(voices_dir(), token)


def _now(now):
    return int(now if now is not None else time.time())


def _env_int(name, default):
    raw = (os.environ.get(name) or "").strip()
    try:
        return int(float(raw.replace(",", "."))) if raw else default
    except ValueError:
        return default


def sample_ttl_sec():
    return _env_int("ABM_VOICE_CLONE_SAMPLE_TTL_H", 24) * 3600


def retention_sec():
    return _env_int("ABM_VOICE_CLONE_RETENTION_DAYS", 365) * 86400


# ---------------------------------------------------------------------------
# identita'
# ---------------------------------------------------------------------------
def new_token():
    return secrets.token_hex(16)


def new_voice_code():
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
    return "-".join((raw[0:4], raw[4:8], raw[8:12]))


def normalize_voice_code(s):
    raw = "".join(c for c in (s or "").upper() if c.isalnum())
    return "-".join((raw[0:4], raw[4:8], raw[8:12])) if len(raw) == 12 else raw


def voice_id_of(rec):
    return VOICE_ID_PREFIX + rec["token"]


def token_of(voice_id):
    if not isinstance(voice_id, str) or not voice_id.startswith(VOICE_ID_PREFIX):
        return None
    tok = voice_id[len(VOICE_ID_PREFIX):]
    return tok if len(tok) == 32 and all(c in "0123456789abcdef" for c in tok) else None


def email_hash(email):
    return hashlib.sha256((email or "").strip().lower().encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# ricerca (scansione lineare: decine di record, vedi piano §Global Constraints)
# ---------------------------------------------------------------------------
def _all():
    return store().all(include_archived=True)


def _find(pred):
    for rec in _all():
        if pred(rec):
            return rec
    return None


def get(clone_id):
    return store().get(clone_id) if clone_id else None


def by_token(token):
    return _find(lambda r: r.get("token") == token) if token else None


def by_voice_code(code):
    code = normalize_voice_code(code)
    return _find(lambda r: r.get("voice_code") == code) if code else None


def by_manage_token(token):
    return _find(lambda r: r.get("manage_token") == token) if token else None


def by_resume_token(token, now=None):
    if not token:
        return None
    rec = _find(lambda r: (r.get("resume_token") or {}).get("value") == token)
    if rec is None or (rec["resume_token"].get("expires_at") or 0) < _now(now):
        return None
    return rec


def draft_for_cid(cid, now=None):
    t = _now(now)
    return _find(lambda r: r.get("state") == "sample_ok"
                 and any(d.get("cid") == cid for d in r.get("devices") or [])
                 and (r.get("expires_at") or 0) > t)


def offered_languages():
    """Lingua -> locali attivi, per le sole lingue con frase guidata (D3)."""
    con_frase = set(voice_clone_prompts.languages())
    out = {}
    for rec in voxcpm_catalog.voices():
        if rec["lang"] in con_frase:
            out.setdefault(rec["lang"], set()).add(rec["locale"])
    return {k: sorted(v) for k, v in out.items()}


# ---------------------------------------------------------------------------
# file
# ---------------------------------------------------------------------------
def r2_key(token, name):
    return f"{R2_PREFIX}{token}/{name}"


def upload_to_r2(rec, name):
    """Copia `voice_dir/<name>` su R2, se attivo. Best effort: un fallimento
    lascia il locale come unica copia e lo scrive a stdout."""
    if not storage_backend.is_enabled():
        return False
    path = os.path.join(voice_dir(rec["token"]), name)
    try:
        storage_backend.upload_file(path, r2_key(rec["token"], name))
        return True
    except Exception as e:
        print(f"[voice_clone] upload R2 fallito per {rec['id']}/{name}: {e}")
        return False


def remove_files(rec):
    """Cancella cartella locale e prefisso R2 della voce. Non solleva."""
    shutil.rmtree(voice_dir(rec["token"]), ignore_errors=True)
    if storage_backend.is_enabled():
        try:
            storage_backend.delete_prefix(r2_key(rec["token"], ""))
        except Exception as e:
            print(f"[voice_clone] delete R2 fallita per {rec['id']}: {e}")


# ---------------------------------------------------------------------------
# bozza
# ---------------------------------------------------------------------------
def create_draft(cid, *, lang, locale, gender, prompt_text, sample_wav,
                 original_path, original_ext, metrics, ui_lang, now=None):
    """Il campione approvato dal gate diventa una voce in stato `sample_ok`.

    Un solo draft per cid (§3.3): il precedente viene cancellato con i suoi
    file. Lingua, locale e genere devono essere fra quelli offerti.
    """
    offerte = offered_languages()
    if lang not in offerte or locale not in offerte[lang]:
        raise ValueError(f"lingua/locale non offerti: {lang}/{locale}")
    if gender not in ("m", "f"):
        raise ValueError(f"genere non valido: {gender!r}")
    if not (prompt_text or "").strip():
        raise ValueError("prompt_text vuoto")
    t = _now(now)
    token = new_token()
    with _lock:
        while by_token(token) is not None:
            token = new_token()
        code = new_voice_code()
        while by_voice_code(code) is not None:
            code = new_voice_code()
        prev = _find(lambda r: r.get("state") == "sample_ok"
                     and any(d.get("cid") == cid for d in r.get("devices") or []))
        if prev is not None:
            remove_files(prev)
            store().delete(prev["id"])
        d = voice_dir(token)
        os.makedirs(d, exist_ok=True)
        shutil.move(sample_wav, os.path.join(d, "sample.wav"))
        shutil.move(original_path, os.path.join(d, "original." + original_ext))
        rec = {
            "id": "vc_" + secrets.token_hex(6),
            "token": token,
            "voice_code": code,
            "state": "sample_ok",
            "state_changed_at": t,
            "manage_token": new_token(),
            "resume_token": {"value": new_token(), "expires_at": t + RESUME_TOKEN_DAYS * 86400},
            "owner_email": None, "owner_email_hash": None,
            "lang": lang, "locale": locale, "gender": gender,
            "prompt_text": prompt_text,
            "prompt_version": voice_clone_prompts.prompt_version(prompt_text),
            "sample": dict(metrics or {}, original_ext=original_ext),
            "demo": None, "payment": None,
            "devices": [{"cid": cid, "added_at": t, "via": "creator"}],
            "pending_confirm": None, "confirm_locks": {},
            "consent_at": t, "ui_lang": ui_lang,
            "created_at": t, "ready_at": None, "last_used_at": t,
            "expires_at": t + sample_ttl_sec(), "expiry_warned_at": None,
            "archived": False, "deleted_at": None, "delete_reason": None,
        }
        store().add(rec)
    upload_to_r2(rec, "sample.wav")
    upload_to_r2(rec, "original." + original_ext)
    return rec


def purge_stale_drafts(now=None):
    """Bozze `sample_ok` oltre la TTL: file e record via. Ritorna quante."""
    t = _now(now)
    n = 0
    with _lock:
        for rec in _all():
            if rec.get("state") == "sample_ok" and (rec.get("expires_at") or 0) <= t:
                remove_files(rec)
                store().delete(rec["id"])
                n += 1
    return n


# ---------------------------------------------------------------------------
# stati
# ---------------------------------------------------------------------------
def transition(clone_id, new_state, patch=None, now=None):
    if new_state not in STATES:
        raise BadTransition(f"stato sconosciuto: {new_state}")
    with _lock:
        rec = get(clone_id)
        if rec is None:
            raise VoiceGone(clone_id)
        cur = rec.get("state")
        if new_state not in TRANSITIONS.get(cur, set()):
            raise BadTransition(f"{clone_id}: {cur} -> {new_state}")
        t = _now(now)
        upd = dict(patch or {})
        upd["state"] = new_state
        upd["state_changed_at"] = t
        stamp = _STAMP_ON_ENTER.get(new_state)
        if stamp:
            upd.setdefault(stamp, t)
        return store().update(clone_id, upd)


# ---------------------------------------------------------------------------
# vista pubblica
# ---------------------------------------------------------------------------
_SECRET_KEYS = ("token", "manage_token", "resume_token", "owner_email",
                "pending_confirm", "confirm_locks")


def public_view(rec):
    pub = {k: v for k, v in rec.items() if k not in _SECRET_KEYS}
    if rec.get("state") == "ready":
        pub["voice_id"] = voice_id_of(rec)
    return pub
```

- [ ] **Step 4: Eseguire i test**

Run: `python -m pytest test/test_voice_clone.py -v --tb=short`
Expected: 11 PASS.

- [ ] **Step 5: Commit**

```
git add voice_clone.py test/test_voice_clone.py
git commit -m "feat(voice-clone): store delle voci campionate, identita', bozza e transizioni"
```

---

### Task 6: Resolver, autorizzazione, `mine`, rinnovo (`voice_clone` + `storage_backend.download_file`)

**Files:**
- Modify: `voice_clone.py` (in coda)
- Modify: `storage_backend.py` (dopo `get_range`, riga ~112)
- Test: `test/test_voice_clone.py` (in coda), `test/test_cloud_offload.py` non si tocca

**Interfaces:**
- Produces:
  - `storage_backend.download_file(key, local_path) -> bool` (False se l'oggetto manca; solleva su altri errori).
  - `voice_clone.resolve(voice_id) -> {"wav_path": str, "prompt_text": str, "lang": str, "locale": str}` (solleva `VoiceGone` se id malformato, record assente o stato non in `HAS_SAMPLE`; scarica da R2 se il locale manca; `FileNotFoundError` se manca ovunque).
  - `voice_clone.check_use(voice_id, cid, lang, locale) -> str` (`""` ok, altrimenti `"voice_gone"` | `"voice_not_authorized"` | `"voice_lang_mismatch"`).
  - `voice_clone.authorized(voice_id, cid) -> bool` (stato `ready` e cid nei dispositivi).
  - `voice_clone.mine(cid, now=None) -> list[dict]` (le voci non terminali con quel cid, come `public_view` più `owner: bool` e `pending: bool`; ordinate: ready prima, poi per `created_at` decrescente).
  - `voice_clone.touch_used(clone_id, now=None) -> dict | None` (`last_used_at` e `expires_at = last_used_at + retention`, solo su `ready`).
  - `voice_clone.language_of(voice_id) -> str | None` (lingua a due lettere del record, per `voxcpm_tts`).
- Consumes: Task 5.

- [ ] **Step 1: Aggiungere i test**

In coda a `test/test_voice_clone.py`:

```python
def _pronta(tmp_path, cid="cid-uno", **kw):
    rec = bozza(tmp_path, cid=cid, **kw)
    vc.transition(rec["id"], "paid"); vc.transition(rec["id"], "demos_generating")
    vc.transition(rec["id"], "demos_ready")
    return vc.transition(rec["id"], "ready")


def test_resolve_ritorna_wav_e_frase(tmp_path):
    rec = _pronta(tmp_path)
    out = vc.resolve(vc.voice_id_of(rec))
    assert out["wav_path"] == os.path.join(vc.voice_dir(rec["token"]), "sample.wav")
    assert out["prompt_text"] == PROMPT and out["lang"] == "it" and out["locale"] == "it-IT"
    assert vc.language_of(vc.voice_id_of(rec)) == "it"


def test_resolve_vale_anche_prima_di_ready_ma_non_dopo_la_fine(tmp_path):
    rec = bozza(tmp_path)
    vid = vc.voice_id_of(rec)
    assert vc.resolve(vid)["prompt_text"] == PROMPT       # sample_ok: le demo lo usano
    vc.transition(rec["id"], "paid"); vc.transition(rec["id"], "refunded")
    with pytest.raises(vc.VoiceGone):
        vc.resolve(vid)
    with pytest.raises(vc.VoiceGone):
        vc.resolve("voxcpm:mine:" + "0" * 32)
    with pytest.raises(vc.VoiceGone):
        vc.resolve("voxcpm:v2:it-IT/Valentina")


def test_resolve_scarica_da_r2_se_il_locale_manca(tmp_path, monkeypatch):
    rec = _pronta(tmp_path)
    wav = os.path.join(vc.voice_dir(rec["token"]), "sample.wav")
    os.remove(wav)
    richieste = []

    def _dl(key, path):
        richieste.append(key)
        with open(path, "wb") as fh:
            fh.write(b"RIFF-da-r2")
        return True
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "download_file", _dl)
    assert vc.resolve(vc.voice_id_of(rec))["wav_path"] == wav
    assert richieste == ["voices/" + rec["token"] + "/sample.wav"]
    assert open(wav, "rb").read() == b"RIFF-da-r2"


def test_resolve_senza_locale_ne_r2(tmp_path, monkeypatch):
    rec = _pronta(tmp_path)
    os.remove(os.path.join(vc.voice_dir(rec["token"]), "sample.wav"))
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "download_file", lambda k, p: False)
    with pytest.raises(FileNotFoundError):
        vc.resolve(vc.voice_id_of(rec))


def test_check_use_ordine_dei_rifiuti(tmp_path):
    rec = bozza(tmp_path)
    vid = vc.voice_id_of(rec)
    assert vc.check_use(vid, "cid-uno", "it", "it-IT") == "voice_gone"        # non ready
    _ = vc.transition(rec["id"], "paid"); vc.transition(rec["id"], "demos_generating")
    vc.transition(rec["id"], "demos_ready"); vc.transition(rec["id"], "ready")
    assert vc.check_use(vid, "cid-due", "it", "it-IT") == "voice_not_authorized"
    assert vc.check_use(vid, "cid-uno", "en", "en-US") == "voice_lang_mismatch"
    assert vc.check_use(vid, "cid-uno", "it", "it-CH") == "voice_lang_mismatch"
    assert vc.check_use(vid, "cid-uno", "it", "it-IT") == ""
    assert vc.check_use("voxcpm:mine:zz", "cid-uno", "it", "it-IT") == "voice_gone"
    assert vc.authorized(vid, "cid-uno") and not vc.authorized(vid, "cid-due")


def test_mine_elenca_le_voci_del_dispositivo(tmp_path):
    a = _pronta(tmp_path, cid="cid-uno")
    b = bozza(tmp_path, cid="cid-uno", lang="en", locale="en-US")   # bozza in sospeso
    _pronta(tmp_path, cid="cid-altro")
    got = vc.mine("cid-uno")
    assert [g["id"] for g in got] == [a["id"], b["id"]]
    assert got[0]["owner"] is True and got[0]["pending"] is False
    assert got[0]["voice_id"] == vc.voice_id_of(a) and "voice_id" not in got[1]
    assert got[1]["pending"] is True
    assert "token" not in got[0] and "manage_token" not in got[0]


def test_mine_esclude_gli_stati_terminali(tmp_path):
    rec = _pronta(tmp_path)
    vc.transition(rec["id"], "deleted")
    assert vc.mine("cid-uno") == []


def test_touch_used_rinnova_la_scadenza(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOICE_CLONE_RETENTION_DAYS", "10")
    rec = _pronta(tmp_path)
    got = vc.touch_used(rec["id"], now=rec["created_at"] + 100)
    assert got["last_used_at"] == rec["created_at"] + 100
    assert got["expires_at"] == rec["created_at"] + 100 + 10 * 86400
    bozza_ = bozza(tmp_path, cid="cid-tre")
    assert vc.touch_used(bozza_["id"]) is None          # non ready: niente rinnovo
```

E in `test/test_voice_clone.py` un test per `storage_backend.download_file` con client finto:

```python
def test_storage_download_file_usa_il_client(monkeypatch, tmp_path):
    class _Client:
        def download_file(self, Bucket, Key, Filename):
            with open(Filename, "wb") as fh:
                fh.write(b"ok")
    monkeypatch.setattr(storage_backend, "_get_client", lambda: _Client())
    monkeypatch.setattr(storage_backend, "_BUCKET", "b")
    dest = tmp_path / "giu" / "x.wav"
    assert storage_backend.download_file("voices/t/sample.wav", str(dest)) is True
    assert dest.read_bytes() == b"ok"

    class _Manca:
        def download_file(self, **kw):
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "404"}}, "GetObject")
    monkeypatch.setattr(storage_backend, "_get_client", lambda: _Manca())
    assert storage_backend.download_file("voices/t/no.wav", str(tmp_path / "no.wav")) is False
```

- [ ] **Step 2: Eseguire e vedere fallire**

Run: `python -m pytest test/test_voice_clone.py -v --tb=short -k "resolve or check_use or mine or touch or download"`
Expected: `AttributeError` su `resolve` / `download_file`.

- [ ] **Step 3: `storage_backend.download_file`**

Dopo `get_range` in `storage_backend.py`:

```python
def download_file(key, local_path):
    """Scarica l'oggetto in `local_path` (cartella creata se manca), via un
    file temporaneo accanto alla destinazione cosi' un download interrotto
    non lascia un file a meta'. Ritorna False se l'oggetto non esiste;
    solleva su altri errori."""
    os.makedirs(os.path.dirname(os.path.abspath(local_path)) or ".", exist_ok=True)
    tmp = local_path + ".part"
    try:
        _get_client().download_file(Bucket=_BUCKET, Key=_full_key(key), Filename=tmp)
    except ClientError as e:
        code = str(getattr(e, "response", {}).get("Error", {}).get("Code", ""))
        try:
            os.remove(tmp)
        except OSError:
            pass
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise
    os.replace(tmp, local_path)
    return True
```

(`ClientError` è già importato in testa al modulo; verificarlo con `grep -n ClientError storage_backend.py`.)

- [ ] **Step 4: Resolver, autorizzazione, `mine`, `touch_used`**

In coda a `voice_clone.py`:

```python
# ---------------------------------------------------------------------------
# uso in generazione (§9)
# ---------------------------------------------------------------------------
def _record_for_voice_id(voice_id):
    tok = token_of(voice_id)
    rec = by_token(tok) if tok else None
    if rec is None:
        raise VoiceGone(f"voce campione sconosciuta: {voice_id!r}")
    return rec


def _ensure_local(rec, name):
    """Il file locale, scaricato da R2 se manca (§5.5: nuovo server)."""
    path = os.path.join(voice_dir(rec["token"]), name)
    if os.path.exists(path):
        return path
    if storage_backend.is_enabled():
        try:
            if storage_backend.download_file(r2_key(rec["token"], name), path):
                return path
        except Exception as e:
            print(f"[voice_clone] download R2 fallito per {rec['id']}/{name}: {e}")
    raise FileNotFoundError(path)


def resolve(voice_id):
    """Per `voxcpm_tts.clone_block`: wav normalizzato e frase letta."""
    rec = _record_for_voice_id(voice_id)
    if rec.get("state") not in HAS_SAMPLE:
        raise VoiceGone(f"voce {rec['id']} in stato {rec.get('state')}")
    return {"wav_path": _ensure_local(rec, "sample.wav"),
            "prompt_text": rec["prompt_text"], "lang": rec["lang"], "locale": rec["locale"]}


def language_of(voice_id):
    try:
        return _record_for_voice_id(voice_id)["lang"]
    except VoiceGone:
        return None


def _has_cid(rec, cid):
    return any(d.get("cid") == cid for d in rec.get("devices") or [])


def check_use(voice_id, cid, lang, locale):
    """'' se la voce si puo' usare per questo libro, altrimenti il codice
    d'errore della spec §9: gone (D16: solo `ready`), not_authorized, lang_mismatch."""
    try:
        rec = _record_for_voice_id(voice_id)
    except VoiceGone:
        return "voice_gone"
    if rec.get("state") != "ready":
        return "voice_gone"
    if not _has_cid(rec, cid):
        return "voice_not_authorized"
    if (lang or "").lower() != rec["lang"] or (locale or "") != rec["locale"]:
        return "voice_lang_mismatch"
    return ""


def authorized(voice_id, cid):
    try:
        rec = _record_for_voice_id(voice_id)
    except VoiceGone:
        return False
    return rec.get("state") == "ready" and _has_cid(rec, cid)


_TERMINAL = frozenset({"refunded", "expired", "deleted"})


def mine(cid, now=None):
    """Le voci del dispositivo, pronte e in sospeso, senza segreti (§3.6)."""
    out = []
    for rec in _all():
        if rec.get("state") in _TERMINAL or not _has_cid(rec, cid):
            continue
        if rec.get("state") == "sample_ok" and (rec.get("expires_at") or 0) <= _now(now):
            continue
        pub = public_view(rec)
        pub["owner"] = any(d.get("cid") == cid and d.get("via") == "creator"
                           for d in rec.get("devices") or [])
        pub["pending"] = rec.get("state") != "ready"
        out.append(pub)
    out.sort(key=lambda p: (p["pending"], -(p.get("created_at") or 0)))
    return out


def touch_used(clone_id, now=None):
    """Rinnovo della retention a ogni uso (D15). Solo su voci `ready`."""
    with _lock:
        rec = get(clone_id)
        if rec is None or rec.get("state") != "ready":
            return None
        t = _now(now)
        return store().update(clone_id, {"last_used_at": t, "expires_at": t + retention_sec()})
```

- [ ] **Step 5: Eseguire i test**

Run: `python -m pytest test/test_voice_clone.py test/test_cloud_offload.py -v --tb=short`
Expected: tutti PASS (i test di `test_cloud_offload` restano verdi: `download_file` è una funzione nuova, nessuna esistente cambia).

- [ ] **Step 6: Commit**

```
git add voice_clone.py storage_backend.py test/test_voice_clone.py
git commit -m "feat(voice-clone): resolver del campione, autorizzazione d'uso e rinnovo"
```

---

### Task 7: Dispositivi: claim, conferma, forget, revoca

**Files:**
- Modify: `voice_clone.py` (in coda)
- Test: `test/test_voice_clone_devices.py`

**Interfaces:**
- Produces:
  - `claim(voice_code, cid, now=None) -> tuple[str, dict, str | None]`: `("ok", rec, None)` se il cid è già autorizzato; `("pending", rec, confirm_code)` altrimenti (codice a 6 cifre in chiaro, da spedire al proprietario nel piano 2; nel record solo `sha256`). Solleva `VoiceGone` se il codice non esiste o la voce è terminale; `ValueError("locked")` se il cid è nel blocco di 15 minuti.
  - `confirm(voice_code, cid, confirm_code, now=None) -> str`: `"ok"` (cid aggiunto con `via: code`), `"wrong"` (tentativi rimasti), `"locked"` (5 tentativi esauriti: `pending_confirm` annullato, `confirm_locks[cid] = now + 900`), `"expired"` (oltre 15 minuti), `"none"` (nessuna richiesta per quel cid). Solleva `VoiceGone` come `claim`.
  - `forget(clone_id, cid) -> bool` (toglie il legame con il cid, anche se era l'ultimo: la voce sopravvive e si recupera col codice-voce. Ritorna False se il cid non c'era).
  - `revoke_device(manage_token, cid) -> bool` (per la pagina `/vc/<manage_token>/devices` del piano 2).
  - `devices_view(rec) -> list[dict]` (`{"cid_tail": ultimi 4, "added_at", "via"}`, per la stessa pagina).
  - Costanti: `CONFIRM_TTL_SEC = 900`, `CONFIRM_MAX_TRIES = 5`, `CONFIRM_LOCK_SEC = 900`.
- Consumes: Task 5-6.

- [ ] **Step 1: Scrivere i test**

`test/test_voice_clone_devices.py`:

```python
"""Claim, conferma, forget e revoca dei dispositivi (spec §6.3, §6.4)."""
import hashlib
import os

import pytest

import community_store
import storage_backend
import voice_clone as vc
import voxcpm_catalog

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    yield
    voxcpm_catalog.invalidate_cache()


def _pronta(tmp_path, cid="cid-owner"):
    s = tmp_path / f"{cid}-s.wav"; s.write_bytes(b"RIFF")
    o = tmp_path / f"{cid}-o.webm"; o.write_bytes(b"webm")
    rec = vc.create_draft(cid, lang="it", locale="it-IT", gender="m", prompt_text="frase",
                          sample_wav=str(s), original_path=str(o), original_ext="webm",
                          metrics={}, ui_lang="it")
    vc.transition(rec["id"], "paid"); vc.transition(rec["id"], "demos_generating")
    vc.transition(rec["id"], "demos_ready")
    return vc.transition(rec["id"], "ready")


def test_claim_da_cid_gia_autorizzato(tmp_path):
    rec = _pronta(tmp_path)
    esito, got, code = vc.claim(rec["voice_code"], "cid-owner")
    assert esito == "ok" and got["id"] == rec["id"] and code is None


def test_claim_da_cid_nuovo_crea_il_codice_hashato(tmp_path):
    rec = _pronta(tmp_path)
    esito, got, code = vc.claim(rec["voice_code"].lower(), "cid-nuovo", now=1000)
    assert esito == "pending" and len(code) == 6 and code.isdigit()
    pc = vc.get(rec["id"])["pending_confirm"]
    assert pc["cid"] == "cid-nuovo" and pc["tries"] == 0
    assert pc["expires_at"] == 1000 + vc.CONFIRM_TTL_SEC
    assert pc["code_hash"] == hashlib.sha256(code.encode()).hexdigest()
    assert code not in str(vc.get(rec["id"]))


def test_claim_sconosciuto_o_terminale(tmp_path):
    with pytest.raises(vc.VoiceGone):
        vc.claim("AAAA-BBBB-CCCC", "cid-x")
    rec = _pronta(tmp_path)
    vc.transition(rec["id"], "deleted")
    with pytest.raises(vc.VoiceGone):
        vc.claim(rec["voice_code"], "cid-x")


def test_una_nuova_richiesta_sostituisce_la_precedente(tmp_path):
    rec = _pronta(tmp_path)
    _, _, c1 = vc.claim(rec["voice_code"], "cid-a", now=1000)
    _, _, c2 = vc.claim(rec["voice_code"], "cid-b", now=1001)
    assert vc.confirm(rec["voice_code"], "cid-a", c1, now=1002) == "none"
    assert vc.confirm(rec["voice_code"], "cid-b", c2, now=1002) == "ok"


def test_confirm_ok_aggiunge_il_dispositivo(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = vc.claim(rec["voice_code"], "cid-nuovo", now=1000)
    assert vc.confirm(rec["voice_code"], "cid-nuovo", code, now=1100) == "ok"
    got = vc.get(rec["id"])
    assert got["pending_confirm"] is None
    assert {"cid": "cid-nuovo", "added_at": 1100, "via": "code"} in got["devices"]
    assert vc.authorized(vc.voice_id_of(got), "cid-nuovo")
    assert vc.claim(rec["voice_code"], "cid-nuovo")[0] == "ok"


def test_confirm_scaduto(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = vc.claim(rec["voice_code"], "cid-nuovo", now=1000)
    assert vc.confirm(rec["voice_code"], "cid-nuovo", code, now=1000 + vc.CONFIRM_TTL_SEC + 1) == "expired"
    assert vc.get(rec["id"])["pending_confirm"] is None


def test_cinque_tentativi_poi_blocco(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = vc.claim(rec["voice_code"], "cid-nuovo", now=1000)
    for _ in range(4):
        assert vc.confirm(rec["voice_code"], "cid-nuovo", "000000", now=1001) == "wrong"
    assert vc.confirm(rec["voice_code"], "cid-nuovo", "000000", now=1001) == "locked"
    got = vc.get(rec["id"])
    assert got["pending_confirm"] is None
    assert got["confirm_locks"]["cid-nuovo"] == 1001 + vc.CONFIRM_LOCK_SEC
    # il codice giusto ormai non vale, e un nuovo claim e' bloccato
    assert vc.confirm(rec["voice_code"], "cid-nuovo", code, now=1002) == "none"
    with pytest.raises(ValueError, match="locked"):
        vc.claim(rec["voice_code"], "cid-nuovo", now=1002)
    assert vc.claim(rec["voice_code"], "cid-nuovo", now=1001 + vc.CONFIRM_LOCK_SEC + 1)[0] == "pending"


def test_forget_e_revoke(tmp_path):
    rec = _pronta(tmp_path)
    _, _, code = vc.claim(rec["voice_code"], "cid-b", now=1000)
    vc.confirm(rec["voice_code"], "cid-b", code, now=1001)
    assert vc.forget(rec["id"], "cid-b") is True
    assert vc.forget(rec["id"], "cid-b") is False
    assert not vc.authorized(vc.voice_id_of(rec), "cid-b")
    assert vc.revoke_device(rec["manage_token"], "cid-owner") is True
    assert vc.revoke_device("token-sbagliato", "cid-owner") is False
    assert vc.get(rec["id"])["devices"] == []
    assert vc.get(rec["id"])["state"] == "ready"        # la voce sopravvive


def test_devices_view_mostra_solo_la_coda_del_cid(tmp_path):
    rec = _pronta(tmp_path, cid="abcd1234efgh")
    view = vc.devices_view(vc.get(rec["id"]))
    assert view == [{"cid_tail": "efgh", "added_at": rec["created_at"], "via": "creator"}]
```

- [ ] **Step 2: Eseguire e vedere fallire**

Run: `python -m pytest test/test_voice_clone_devices.py -v --tb=short`
Expected: `AttributeError: module 'voice_clone' has no attribute 'claim'`.

- [ ] **Step 3: Implementare**

In coda a `voice_clone.py`:

```python
# ---------------------------------------------------------------------------
# dispositivi (§6.3, §6.4)
# ---------------------------------------------------------------------------
CONFIRM_TTL_SEC = 900
CONFIRM_MAX_TRIES = 5
CONFIRM_LOCK_SEC = 900


def _by_code_alive(voice_code):
    rec = by_voice_code(voice_code)
    if rec is None or rec.get("state") in _TERMINAL:
        raise VoiceGone("codice-voce sconosciuto")
    return rec


def _code_hash(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def claim(voice_code, cid, now=None):
    """Primo passo del recupero/dono: o il cid e' gia' dentro, o parte un
    codice di conferma per il proprietario. Il codice in chiaro torna al
    chiamante (che lo spedisce) e nel record resta solo l'hash."""
    t = _now(now)
    with _lock:
        rec = _by_code_alive(voice_code)
        if _has_cid(rec, cid):
            return "ok", rec, None
        if (rec.get("confirm_locks") or {}).get(cid, 0) > t:
            raise ValueError("locked")
        code = f"{secrets.randbelow(1000000):06d}"
        rec = store().update(rec["id"], {"pending_confirm": {
            "cid": cid, "code_hash": _code_hash(code),
            "expires_at": t + CONFIRM_TTL_SEC, "tries": 0}})
        return "pending", rec, code


def confirm(voice_code, cid, confirm_code, now=None):
    t = _now(now)
    with _lock:
        rec = _by_code_alive(voice_code)
        pc = rec.get("pending_confirm")
        if not pc or pc.get("cid") != cid:
            return "none"
        if (pc.get("expires_at") or 0) < t:
            store().update(rec["id"], {"pending_confirm": None})
            return "expired"
        if pc.get("code_hash") == _code_hash((confirm_code or "").strip()):
            devices = list(rec.get("devices") or [])
            devices.append({"cid": cid, "added_at": t, "via": "code"})
            store().update(rec["id"], {"pending_confirm": None, "devices": devices})
            return "ok"
        pc = dict(pc, tries=int(pc.get("tries") or 0) + 1)
        if pc["tries"] >= CONFIRM_MAX_TRIES:
            locks = dict(rec.get("confirm_locks") or {})
            locks[cid] = t + CONFIRM_LOCK_SEC
            store().update(rec["id"], {"pending_confirm": None, "confirm_locks": locks})
            return "locked"
        store().update(rec["id"], {"pending_confirm": pc})
        return "wrong"


def _drop_device(rec, cid):
    devices = [d for d in rec.get("devices") or [] if d.get("cid") != cid]
    if len(devices) == len(rec.get("devices") or []):
        return False
    store().update(rec["id"], {"devices": devices})
    return True


def forget(clone_id, cid):
    """«Rimuovi da questo dispositivo»: solo il legame, la voce sopravvive."""
    with _lock:
        rec = get(clone_id)
        return bool(rec) and _drop_device(rec, cid)


def revoke_device(manage_token, cid):
    """Revoca dal proprietario (link con manage_token)."""
    with _lock:
        rec = by_manage_token(manage_token)
        return bool(rec) and _drop_device(rec, cid)


def devices_view(rec):
    return [{"cid_tail": str(d.get("cid") or "")[-4:], "added_at": d.get("added_at"),
             "via": d.get("via")} for d in rec.get("devices") or []]
```

- [ ] **Step 4: Eseguire i test**

Run: `python -m pytest test/test_voice_clone_devices.py test/test_voice_clone.py -v --tb=short`
Expected: tutti PASS.

- [ ] **Step 5: Commit**

```
git add voice_clone.py test/test_voice_clone_devices.py
git commit -m "feat(voice-clone): claim con codice di conferma, forget e revoca dei dispositivi"
```

---

### Task 8: `voxcpm_tts` risolve gli id `mine`, dipendenze e documentazione

**Files:**
- Modify: `voxcpm_tts.py` (`clone_block`, righe ~840-870; lingua del job, riga ~1070)
- Modify: `requirements.txt`
- Modify: `md_files/PARAMETRI_CONFIGURAZIONE.md` (§3.5 «Voci e lingue», dopo le righe `ABM_VOXCPM_*`)
- Test: `test/test_voxcpm_tts_mine.py`

**Interfaces:**
- Produces: `voxcpm_tts.clone_block(voice_id)` accetta `voxcpm:mine:<token>` (stesso dict di prima: `prompt_wav_b64`, `prompt_format`, `prompt_text`, `reference_wav_b64`, `reference_format`); `voxcpm_tts._lingua_voce(voice_id) -> str` (due lettere, catalogo o record clone).
- Consumes: `voice_clone.resolve`, `voice_clone.language_of`, `voice_clone.VoiceGone` (Task 6).

- [ ] **Step 1: Scrivere i test**

`test/test_voxcpm_tts_mine.py`:

```python
"""`clone_block` e lingua del job per le voci campionate (spec §9)."""
import base64
import os

import pytest

import community_store
import storage_backend
import voice_clone as vc
import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    yield
    voxcpm_catalog.invalidate_cache()


def _voce(tmp_path, wav=b"RIFF-mio-campione"):
    s = tmp_path / "s.wav"; s.write_bytes(wav)
    o = tmp_path / "o.webm"; o.write_bytes(b"webm")
    return vc.create_draft("cid-x", lang="it", locale="it-IT", gender="f",
                           prompt_text="Ogni mattina apro la finestra",
                           sample_wav=str(s), original_path=str(o), original_ext="webm",
                           metrics={}, ui_lang="it")


def test_clone_block_per_voce_mine(tmp_path):
    rec = _voce(tmp_path)
    blocco = voxcpm_tts.clone_block(vc.voice_id_of(rec))
    assert base64.b64decode(blocco["prompt_wav_b64"]) == b"RIFF-mio-campione"
    assert blocco["prompt_text"] == "Ogni mattina apro la finestra"
    assert blocco["reference_wav_b64"] == blocco["prompt_wav_b64"]
    assert blocco["prompt_format"] == blocco["reference_format"] == "wav"


def test_clone_block_mine_e_in_cache(tmp_path):
    rec = _voce(tmp_path)
    vid = vc.voice_id_of(rec)
    a = voxcpm_tts.clone_block(vid)
    os.remove(os.path.join(vc.voice_dir(rec["token"]), "sample.wav"))
    assert voxcpm_tts.clone_block(vid) == a          # servito dalla cache
    voxcpm_tts.invalidate_clone_cache()
    with pytest.raises(FileNotFoundError):
        voxcpm_tts.clone_block(vid)


def test_clone_block_mine_sconosciuta_solleva_value_error():
    with pytest.raises(ValueError):
        voxcpm_tts.clone_block("voxcpm:mine:" + "a" * 32)


def test_clone_block_catalogo_invariato():
    blocco = voxcpm_tts.clone_block("voxcpm:v2:it-IT/Stefano")
    assert blocco["prompt_text"].startswith("Quando il treno")


def test_lingua_voce(tmp_path):
    rec = _voce(tmp_path)
    assert voxcpm_tts._lingua_voce(vc.voice_id_of(rec)) == "it"
    assert voxcpm_tts._lingua_voce("voxcpm:v2:it-IT/Stefano") == "it"
    with pytest.raises(ValueError):
        voxcpm_tts._lingua_voce("voxcpm:mine:" + "b" * 32)
```

- [ ] **Step 2: Eseguire e vedere fallire**

Run: `python -m pytest test/test_voxcpm_tts_mine.py -v --tb=short`
Expected: `test_clone_block_per_voce_mine` fallisce con `ValueError: voice id VoxCPM non valido: 'voxcpm:mine:...'` (da `parse_voice_id`); `test_lingua_voce` con `AttributeError`.

- [ ] **Step 3: Modificare `clone_block` e la lingua del job**

In `voxcpm_tts.py` (`clone_block`, riga ~840), sostituire le righe che vanno da `rec = voxcpm_catalog.parse_voice_id(voice_id)` alla chiusura del dict `blocco = {...}` (lasciando intatti il controllo cache prima e l'inserimento in `_clone_cache` dopo) con:

```python
    tok = voice_clone_token(voice_id)
    if tok is not None:
        import voice_clone       # foglia rispetto a questo modulo; import qui
        # per non caricare lo store quando si servono solo voci di catalogo
        try:
            risolta = voice_clone.resolve(voice_id)
        except voice_clone.VoiceGone as e:
            # stessa famiglia d'errore delle voci di catalogo sparite (§9.4)
            raise ValueError(str(e)) from e
        wav_path, prompt_text = risolta["wav_path"], risolta["prompt_text"]
    else:
        rec = voxcpm_catalog.parse_voice_id(voice_id)
        wav_path, prompt_text = voxcpm_catalog.sample_path(voice_id), rec["transcript"]
    with open(wav_path, "rb") as f:
        wav = base64.b64encode(f.read()).decode("ascii")
    blocco = {
        "prompt_wav_b64": wav,
        "prompt_format": "wav",
        "prompt_text": prompt_text,
        "reference_wav_b64": wav,
        "reference_format": "wav",
    }
```

e aggiungere, sopra `clone_block`:

```python
def voice_clone_token(voice_id):
    """Il token se `voice_id` e' una voce campionata (`voxcpm:mine:<token>`),
    altrimenti None. Non apre lo store: e' solo sintassi."""
    prefix = "voxcpm:mine:"
    if not isinstance(voice_id, str) or not voice_id.startswith(prefix):
        return None
    tok = voice_id[len(prefix):]
    return tok if tok else None


def _lingua_voce(voice_id):
    """La lingua a due lettere della voce: dal catalogo o dal record clone.
    ValueError se la voce non esiste, come `parse_voice_id`."""
    if voice_clone_token(voice_id) is not None:
        import voice_clone
        lang = voice_clone.language_of(voice_id)
        if not lang:
            raise ValueError(f"voce campione sconosciuta: {voice_id!r}")
        return lang.lower()
    return voxcpm_catalog.parse_voice_id(voice_id)["locale"].split("-")[0].lower()
```

Poi in `synthesize_chapter` (riga ~1070) sostituire:

```python
    lingua = voxcpm_catalog.parse_voice_id(voice_id)["locale"].split(
        "-")[0].lower()
```

con:

```python
    lingua = _lingua_voce(voice_id)
```

Aggiornare il docstring di `clone_block` con una riga: «Per gli id `voxcpm:mine:<token>` il campione e la frase vengono da `voice_clone.resolve`; la cache è la stessa, per `voice_id`.»

- [ ] **Step 4: Eseguire i test del motore**

Run: `python -m pytest test/test_voxcpm_tts_mine.py test/test_voxcpm_tts.py test/test_voxcpm_tts_runpod.py test/test_voxcpm_catalog.py test/test_voxcpm_chunk_size.py test/test_voxcpm_generation.py -v --tb=short`
Expected: tutti PASS. In particolare `test_voxcpm_catalog.py:193` (parse_voice_id rifiuta `mine`) resta valido: il catalogo continua a non conoscere le voci clonate.

- [ ] **Step 5: Dipendenze**

In `requirements.txt` aggiungere:

```
numpy>=1.26  # misure acustiche del campione vocale (voice_clone_audio)
faster-whisper>=1.2  # verifica ASR del campione vocale su CPU (voice_clone_audio); porta ctranslate2
zhconv  # cinese tradizionale->semplificato nel CER (voice_clone_audio)
```

Verifica: `python -m pip install -r requirements.txt` non cambia nulla in locale (già installati: numpy 1.26.4, faster-whisper 1.2.1, zhconv 1.4.3).

- [ ] **Step 6: Documentazione delle variabili**

In `md_files/PARAMETRI_CONFIGURAZIONE.md`, §3.5 «Voci e lingue», dopo l'ultima riga `ABM_VOXCPM_*` della tabella, aggiungere (le righe restano nella stessa tabella; colonna File/Riga con il numero reale al momento del commit, controllato con `grep -n`):

```
| `ABM_VOICE_CLONE_MIN_SEC` / `ABM_VOICE_CLONE_MAX_SEC` | `12` / `20` — finestra di durata accettata dal gate del campione vocale (voci campionate, D7). Il target dichiarato all'utente resta 15-18 s. | `voice_clone_audio.py` | `gate_from_env` |
| `ABM_VOICE_CLONE_MAX_CER` | `0.25` — soglia di CER (faster-whisper contro la frase guidata) sopra la quale il campione e' respinto con `vc_gate_text`. Da calibrare su registrazioni reali nelle nove lingue prima del rilascio. Accetta la virgola decimale. | `voice_clone_audio.py` | `max_cer` |
| `ABM_VOICE_CLONE_ASR` | `1` — `0` salta la verifica ASR (solo sviluppo). | `voice_clone_audio.py` | `asr_enabled` |
| `ABM_VOICE_CLONE_ASR_MODEL` | `base` — modello faster-whisper su CPU (`base` ~150 MB, `small` ~460 MB), scaricato al primo uso in `ABM_DATA_DIR/whisper/`, caricato a richiesta e scaricato dalla RAM dopo 600 s di inattivita' (`ASR_IDLE_UNLOAD_SEC`). Impronta stimata 0,4-0,6 GB per `base`: verificare contro la RAM libera di produzione. | `voice_clone_audio.py` | `_asr_model_name` |
| `ABM_VOICE_CLONE_ASR_TIMEOUT_SEC` | `120` — timeout della trascrizione; scaduto, il campione non passa (`vc_gate_asr_unavailable`). | `voice_clone_audio.py` | `_asr_timeout` |
| `ABM_VOICE_CLONE_SAMPLE_TTL_H` | `24` — vita di un campione approvato ma non pagato (`sample_ok`); oltre, file e record vengono rimossi da `purge_stale_drafts`. | `voice_clone.py` | `sample_ttl_sec` |
| `ABM_VOICE_CLONE_RETENTION_DAYS` | `365` — retention della voce, rinnovata a ogni uso (`touch_used`). | `voice_clone.py` | `retention_sec` |
```

E una riga nel «Riepilogo» finale se elenca le variabili per modulo (controllare `grep -n "Riepilogo" md_files/PARAMETRI_CONFIGURAZIONE.md`).

Nota: `md_files/` è in `.gitignore`; il file resta fuori da git come oggi. Aggiornarlo è comunque parte del task (pre-push checklist del repo).

- [ ] **Step 7: Suite completa**

Run: `python -m pytest test/ -q --tb=short`
Expected: verde (i test ffmpeg possono essere SKIPPED su una macchina senza ffmpeg; qui c'è ffmpeg 8.1).

- [ ] **Step 8: Commit**

```
git add voxcpm_tts.py requirements.txt test/test_voxcpm_tts_mine.py
git commit -m "feat(voice-clone): voxcpm_tts risolve le voci campionate; dipendenze numpy, faster-whisper, zhconv"
```

---

## Cosa resta ai piani 2 e 3

- **Piano 2**: `payment.voice_clone_price_eur()` e purpose `voice_clone`; `commit` (consumo pagamento + `transition(paid)` + check-and-set `owner_email_hash`); thread demo (`clone_block` + job RunPod `generate` con due chunk, pcm → wav 48 kHz, `demo_try_*`, `regen_used`), `recover()` all'avvio, cleanup giornaliero (`purge_stale_drafts`, retention/`expired`, avviso 30 giorni, rimborsi automatici a 7/30 giorni), le cinque email, endpoint `/api/voice_clone/*`, `/api/paypal_create_order_voice_clone`, pagine `/vc/<token>/...`, `_mine` in `/api/voices`, guardie `check_use` in generate/preview, `touch_used` a fine job, tag `abm_voice="user-voice"`, log business `VOICE_CLONE_*`, digest admin, `voice_clone.init` e `voice_clone_audio.init` in `audiobook_app`.
- **Piano 3**: wizard `static/js/voice_clone.js`, markup, combo `audio_cascade.js`, i18n (`vc_gate_*` incluse), test JS, `docs/MANUAL_TESTS_VOCI_CAMPIONATE.md`, paragrafo privacy.
