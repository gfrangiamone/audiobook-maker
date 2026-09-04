# Cascata lingua → modello → accento → voce — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Togliere la lingua dalle combo del pannello Impostazioni audio e farne lo stato del libro, lasciando dentro i tab la sola catena modello → accento → voce, con forzatura manuale della lingua.

**Architecture:** La logica di selezione viene estratta da `app.js` in una funzione pura senza DOM (`resolveAudioSelection`) che riceve lingua, catalogo e selezione corrente e restituisce la selezione risolta più l'elenco dei cambiamenti. `app.js` diventa il renderer che riversa quel risultato nei `<select>`. Il server guadagna un solo campo (`language_source`) nella risposta di analyze; nient'altro cambia lato backend, e il canale della lingua resta il campo `lang` già esistente nei payload.

**Tech Stack:** Python 3.12 + Flask (backend), JavaScript senza framework né bundler (`static/js/app.js`, script `defer`), pytest, `node:test` (libreria standard di Node v24.14.1 — nessuna dipendenza nuova).

**Spec:** `docs/superpowers/specs/2026-09-04-audio-language-model-cascade-design.md`

## Global Constraints

- **Nessuna dipendenza nuova.** `package.json` resta `{"dependencies": {"firebase": "^12.12.1"}}`. Il runner dei test JS è `node --test`, built-in.
- **Nessun nome di fornitore nell'interfaccia utente.** Vietate nelle stringhe visibili: `Gemini`, `Google`, `Speechify`, `Simba`, `Microsoft`, `Edge`, `Azure`. Etichette ammesse: «Standard», «Avanzato», «Audiobook Maker (VOXCPM2)». Nei commenti e negli identificatori di codice i nomi restano.
- **Testo UI monolingua → inglese.** Ogni fallback non localizzato e ogni stringa di sistema si scrivono in inglese, mai in italiano.
- **7 locali i18n**, tutti obbligatori per ogni chiave nuova, in `templates/_fragments/i18n_data.js`: `it`, `en`, `fr`, `es`, `de`, `zh`, `hi`.
- **I1 — `/api/voices` deve emettere `engine` su ogni voce.** Il client mobile assume `'edge'` quando il campo manca e mostrerebbe come gratuite le 1.635 voci a pagamento presenti nella stessa risposta. Non è un varco verso la generazione gratuita — il cancello del pagamento riclassifica la voce dal prefisso del suo id, non dal catalogo — ma l'utente mobile finirebbe su un `402` che l'app non sa spiegare, e la quota gratuita ne pagherebbe una parte.
- **La classificazione premium resta ancorata all'id della voce.** `voice_utils.is_gemini_voice` / `is_speechify_voice` / `is_voxcpm_voice` sono l'unica fonte. Nessun percorso di pagamento deve mai iniziare a leggere il campo `engine` del catalogo: sposterebbe la cassa su un dato di vetrina.
- **I2 — `lang` deve restare facoltativo in `/api/generate`.** Il client mobile non lo manda e dipende dal ripiego `client > metadati libro > "it"` di `audiobook_app.py:10078`.
- **I3 — la forma di `/api/voices` non cambia.** Chiavi di primo livello = codici lingua con `name` e `voices[]`; chiavi `_*` = metadati; per voce servono `id`, `name`, `gender`, `locale`, `engine`.
- **NON rimuovere** `google_cost_eur`, `google_cost_actual`, `pricing_cost_actual`, `margin_eur_actual` in `generation_engine.py:3663-3736`: sono campi di costo generici con fallback per i job storici.
- **Nessun `git push`.** Solo commit locali, fino a collaudo manuale fatto e confermato dall'utente.
- **Mai `git add -A`, `git add .`, `git commit -a`.** Il working tree contiene modifiche di altre sessioni che lavorano sulla stessa copia (`.gitignore`, `version.py`, `voxcpm_catalog.py`, `md_files/`, `test/fixtures/` e altri): uno `add` generico se le porterebbe dentro. Ogni commit elenca i suoi path. Vietati anche `git reset`, `git checkout -- .`, `git stash` e `git stash pop`.

---

### Task 1: Rete di protezione del contratto mobile

Prima di tutto il resto. Sono test di caratterizzazione: **devono passare sul codice di oggi**. Servono a far fallire rumorosamente i task successivi se rompono le app già pubblicate.

**Files:**
- Create: `test/test_mobile_contract.py`

**Interfaces:**
- Consuma: `audiobook_app.get_voices()`, la route `/api/generate`.
- Produce: nulla di importabile. È una rete, non un componente.

- [ ] **Step 1: Scrivere il test I1 (ogni voce ha `engine`)**

```python
"""Contratto backend delle app mobile GIA' PUBBLICATE.

Il client Flutter (repo audiobook-maker-mobile) filtra le voci gratuite con
`engine: (j['engine'] ?? 'edge')`: quando il campo manca assume 'edge'. Nella
stessa risposta viaggiano oltre 1.600 voci a pagamento. Se `engine` sparisse,
il mobile non fallirebbe: le mostrerebbe come gratuite.

Questi test non descrivono un comportamento nuovo. Fissano quello attuale,
perche' l'aggiornamento delle app mobile non ha tempi certi e il backend deve
restare compatibile con le versioni gia' sugli store.
"""
import pytest

import audiobook_app


def test_ogni_voce_espone_engine():
    catalogo = audiobook_app.get_voices()
    senza_engine = []
    for codice, dati in catalogo.items():
        if codice.startswith("_"):
            continue
        for voce in dati.get("voices", []):
            if not voce.get("engine"):
                senza_engine.append(f"{codice}/{voce.get('id', '?')}")
    assert not senza_engine, (
        "voci senza 'engine' (il mobile le mostrerebbe come gratuite): "
        + ", ".join(senza_engine[:20])
    )


def test_engine_edge_non_copre_le_voci_a_pagamento():
    """Le voci a pagamento devono avere un engine DIVERSO da 'edge'."""
    catalogo = audiobook_app.get_voices()
    travestite = []
    for codice, dati in catalogo.items():
        if codice.startswith("_"):
            continue
        for voce in dati.get("voices", []):
            vid = str(voce.get("id", ""))
            a_pagamento = vid.startswith(("gemini:", "voxcpm:", "speechify:"))
            if a_pagamento and voce.get("engine") == "edge":
                travestite.append(vid)
    assert not travestite, (
        "voci a pagamento marcate engine='edge': " + ", ".join(travestite[:20])
    )


def test_forma_del_catalogo_invariata():
    """I3: chiavi di primo livello = lingue con name/voices, `_*` = metadati."""
    catalogo = audiobook_app.get_voices()
    lingue = [k for k in catalogo if not k.startswith("_")]
    assert lingue, "nessuna lingua nel catalogo"
    for codice in lingue:
        dati = catalogo[codice]
        assert isinstance(dati, dict), f"{codice} non e' un oggetto"
        assert "name" in dati, f"{codice} senza 'name'"
        assert isinstance(dati.get("voices"), list), f"{codice} senza 'voices'"
    campione = catalogo[lingue[0]]["voices"][0]
    for chiave in ("id", "name", "gender", "locale", "engine"):
        assert chiave in campione, f"voce senza '{chiave}'"


def test_il_cancello_del_pagamento_non_guarda_il_catalogo():
    """Il premium si riconosce dal PREFISSO DELL'ID, mai dal campo `engine`.

    `engine` e' materiale da vetrina: lo legge il client per raggruppare le
    voci. La cassa e' altrove — /api/generate riclassifica la voce dall'id che
    riceve (voice_utils.is_gemini_voice e sorelle, tre startswith) e pretende
    un payment_token o la quota gratuita, altrimenti 402.

    Questo test esiste perche' quella separazione non si perda in un
    refactoring: se un domani la classificazione premium passasse dal catalogo,
    un catalogo sbagliato diventerebbe un varco. Oggi non lo e', e non deve
    diventarlo.
    """
    import voice_utils

    assert voice_utils.is_gemini_voice("gemini:flash25:Achernar")
    assert voice_utils.is_speechify_voice("speechify:simba-3.2:beatrice_32")
    assert voice_utils.is_voxcpm_voice("voxcpm:v2:it-IT/Bianca")
    assert not voice_utils.is_gemini_voice("it-IT-IsabellaNeural")

    # Nessuno dei tre predicati accetta un dizionario-voce: lavorano su
    # stringhe. Se qualcuno li cambiasse per leggere `engine`, questo cade.
    for predicato in (voice_utils.is_gemini_voice,
                      voice_utils.is_speechify_voice,
                      voice_utils.is_voxcpm_voice):
        assert predicato({"engine": "gemini", "id": "it-IT-IsabellaNeural"}) is False


def test_generate_pretende_il_pagamento_sulle_voci_premium():
    """Il ramo 402 vive nel route, keyed sull'id della voce."""
    import pathlib
    sorgente = pathlib.Path("audiobook_app.py").read_text(encoding="utf-8")
    assert 'if _is_speechify_voice(voice) or _is_voxcpm_voice(voice):' in sorgente
    assert '"error": "payment_required"' in sorgente


- [ ] **Step 2: Eseguire e verificare che PASSA sul codice di oggi**

Run: `python -m pytest test/test_mobile_contract.py -v`
Expected: 5 PASSED. Se uno fallisce, **fermarsi**: il contratto è già rotto e va capito prima di procedere.

- [ ] **Step 3: Verificare che il test morda davvero**

Rompere di proposito il contratto e controllare che il test se ne accorga. In una shell Python:

```bash
python -c "
import audiobook_app
orig = audiobook_app.get_voices
def rotto():
    c = orig()
    for k, v in c.items():
        if not k.startswith('_'):
            for voce in v.get('voices', []):
                voce.pop('engine', None)
            break
    return c
audiobook_app.get_voices = rotto
import pytest, sys
sys.exit(pytest.main(['test/test_mobile_contract.py::test_ogni_voce_espone_engine', '-q']))
"
```

Expected: FAILED con l'elenco delle voci senza `engine`. Se passa, il test non serve a nulla e va corretto.

- [ ] **Step 4: Scrivere il test I2 (`lang` facoltativo in `/api/generate`)**

Aggiungere in coda a `test/test_mobile_contract.py`. Il body è quello che manda davvero il client Flutter (`abm_api_client.dart:283-290`): **senza `lang`**.

```python
def test_generate_accetta_body_senza_lang(monkeypatch, tmp_path):
    """I2: il mobile non manda `lang`. Il server deve ripiegare, non rifiutare.

    Body reale del client Flutter (abm_api_client.dart): job_id, voice,
    output_format, rate, selected_chapters, batch_mode.
    """
    import json

    app = audiobook_app.app
    app.config["TESTING"] = True

    avviati = {}

    def _finto_avvio(*args, **kwargs):
        avviati["chiamato"] = True

    monkeypatch.setattr(
        audiobook_app.threading, "Thread",
        lambda *a, **k: type("T", (), {"start": lambda self: _finto_avvio(),
                                       "daemon": True})(),
        raising=False,
    )

    with app.test_client() as client:
        resp = client.post(
            "/api/generate",
            data=json.dumps({
                "job_id": "job-inesistente",
                "voice": "it-IT-IsabellaNeural",
                "output_format": "mp3",
                "rate": "+0%",
                "selected_chapters": [0],
                "batch_mode": True,
            }),
            content_type="application/json",
        )

    # Il job non esiste: 404/400 sono risposte legittime. Cio' che NON deve
    # accadere e' un rifiuto per `lang` mancante (400 con quel messaggio) o un
    # 500 da KeyError.
    assert resp.status_code != 500, f"500 su body senza lang: {resp.data[:400]}"
    corpo = resp.get_data(as_text=True).lower()
    assert "lang" not in corpo or "missing" not in corpo, (
        f"/api/generate sembra pretendere `lang`: {corpo[:400]}"
    )
```

- [ ] **Step 5: Eseguire la suite completa del file**

Run: `python -m pytest test/test_mobile_contract.py -v`
Expected: 6 PASSED.

Se `test_generate_accetta_body_senza_lang` non arriva a una risposta per via delle dipendenze del route, semplificarlo così: leggere il sorgente e asserire che il ripiego esiste, invece di simulare la richiesta.

```python
def test_generate_ha_il_ripiego_su_lang_assente():
    """Variante statica di I2, se il route non e' testabile in isolamento."""
    import pathlib
    sorgente = pathlib.Path("audiobook_app.py").read_text(encoding="utf-8")
    assert '_ui_lang_pre = (data.get("lang") or "")' in sorgente, (
        "sparito il ripiego su `lang` assente: il mobile non manda quel campo"
    )
```

- [ ] **Step 6: Commit**

```bash
git add test/test_mobile_contract.py
git commit -m "test: fissa il contratto backend delle app mobile pubblicate

I1: ogni voce di /api/voices porta `engine` (il mobile assume 'edge'
quando manca, e mostrerebbe come gratuite 1.635 voci a pagamento).
Fissa anche la separazione fra vetrina e cassa: il premium si riconosce
dal prefisso dell'id, mai da `engine`.
I2: /api/generate accetta un body senza `lang`.
I3: la forma del catalogo voci non cambia.

Test di caratterizzazione: passano sul codice di oggi, servono a far
fallire rumorosamente i commit successivi.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3"
```

---

### Task 2: Rimozione Google HD — backend

`google_tts.is_available()` restituisce `False` incondizionatamente dal commit `63c1ef6`. È codice morto.

**Files:**
- Delete: `google_tts.py` (745 righe)
- Modify: `audiobook_app.py` (47 occorrenze), `generation_engine.py` (16), `tts_split.py` (3), `gemini_tts.py` (1)
- Modify: `test/test_engine_dispatch.py`, `test/test_atomic_json_store.py`, `test/test_assembly_priority.py`, `test/test_tts_split_pcm.py`

**Interfaces:**
- Consuma: la rete di Task 1.
- Produce: un backend senza il motore `google`. Il dispatch di `generation_engine` non restituirà più `"google"`.

- [ ] **Step 1: Censire con precisione**

```bash
grep -n "gcloud\|google_tts\|_google_tts\|is_google_voice\|Google HD" audiobook_app.py generation_engine.py tts_split.py gemini_tts.py > /tmp/google_census.txt
wc -l /tmp/google_census.txt
```

Leggere il file per intero prima di toccare qualsiasi cosa. **Marcare le righe da NON toccare**: in `generation_engine.py:3663-3736` i campi `google_cost_eur`, `google_cost_actual`, `pricing_cost_actual`, `margin_eur_actual` restano. Hanno «google» nel nome ma sono campi di costo generici con fallback per i job storici: rimuoverli renderebbe illeggibili i job già archiviati.

- [ ] **Step 2: Far girare i test toccati PRIMA di modificare, per avere la baseline**

Run: `python -m pytest test/test_engine_dispatch.py test/test_atomic_json_store.py test/test_assembly_priority.py test/test_tts_split_pcm.py test/test_mobile_contract.py -v`
Expected: tutti PASSED. Annotare quanti sono.

- [ ] **Step 3: Rimuovere il blocco `_google_tts` da `/api/voices`**

In `audiobook_app.py`, dentro `api_voices()` (route a riga 7935), eliminare:

```python
        # Includi info budget Google TTS come chiave speciale _google_tts
        if google_tts is not None and google_tts.is_available():
            used, remaining, limit = google_tts.get_usage()
            voices["_google_tts"] = {
                "available": remaining > 0,
                "chars_remaining": remaining,
                "chars_limit": limit,
            }
```

- [ ] **Step 4: Eseguire subito la rete di Task 1**

Run: `python -m pytest test/test_mobile_contract.py -v`
Expected: 6 PASSED. Questo è il punto in cui la rete guadagna il suo posto: si è appena toccata la route che serve il mobile.

- [ ] **Step 5: Rimuovere il resto dal backend**

Nell'ordine, guidati da `/tmp/google_census.txt`:

1. `audiobook_app.py`: l'import di `google_tts`, la route `/api/admin/google_tts_status` (riga 9034), il thread `_google_tts_reconcile_loop` (16997) e il suo avvio, `_has_active_google_tts_jobs` (454), il blocco di riserva budget (10633-10648) con `google_tts_reserved`, e il ramo `error_code: "google_tts_budget"`.
2. `generation_engine.py`: il ramo di dispatch a riga 3336-3337 —

```python
        if _google_tts is not None and _google_tts.is_google_voice(voice):
            return "google"
```

   — l'import di `_google_tts`, e `_google_tts_refund_unused` (2653) con le sue chiamate.
3. `tts_split.py`: il ramo di split dedicato alle voci `gcloud:`.
4. `gemini_tts.py`: il riferimento residuo.
5. `rm google_tts.py`.

Dopo ogni file, eseguire `python -c "import audiobook_app"` per scoprire subito un import rimasto appeso.

- [ ] **Step 6: Adeguare i test**

`test/test_engine_dispatch.py` e `test/test_atomic_json_store.py` citano il motore `google`. **Non cancellarli**: rimuovere i soli casi sul motore rimosso e lasciare intatti quelli sugli altri motori. Se un test verifica che `_engine_for_voice("gcloud:...")` restituisce `"google"`, va eliminato quel caso; se ne verifica il comportamento su `gemini:`/`voxcpm:`/edge, resta.

- [ ] **Step 7: Eseguire la suite intera**

Run: `python -m pytest test/ -q`
Expected: nessun fallimento nuovo rispetto alla baseline dello Step 2. Confrontare il numero di test passati: deve calare solo dei casi rimossi allo Step 6.

- [ ] **Step 8: Commit**

```bash
git add audiobook_app.py generation_engine.py tts_split.py gemini_tts.py test/test_engine_dispatch.py test/test_atomic_json_store.py test/test_assembly_priority.py test/test_tts_split_pcm.py
git rm google_tts.py
git commit -m "refactor(tts): elimina Google HD dal backend

is_available() restituiva False incondizionatamente da 63c1ef6: il
motore era gia' spento, restava solo il costo di leggerlo.

Restano i campi di costo google_cost_eur/google_cost_actual/
pricing_cost_actual/margin_eur_actual: hanno quel nome ma sono generici,
con fallback per i job storici.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3"
```

---

### Task 3: Rimozione Google HD — frontend

**Files:**
- Modify: `static/js/app.js` (15 occorrenze), `templates/_fragments/i18n_data.js` (7), `static/css/style.css` (classe `.gcloud-voice`)

**Interfaces:**
- Consuma: il backend di Task 2, che non serve più voci `gcloud:`.
- Produce: `updVoices()` senza il ramo Google. Il tab Standard mostra un solo motore — è ciò che rende inutile la riga MODELLO nel Task 6.

- [ ] **Step 1: Rimuovere `_isGoogleVoice` e `_googleTtsAffordable`**

In `static/js/app.js`, eliminare (righe ~995-1004):

```js
function _isGoogleVoice(id){return id&&id.startsWith('gcloud:')}
function _googleTtsAffordable(){
  // ... corpo intero
}
```

Eliminare anche la variabile `_googleTtsBudget` e ogni sua assegnazione.

- [ ] **Step 2: Ripulire `updVoices()`**

In `updVoices()` (riga 1005), eliminare la costante `googleVoices` e tutto il blocco `if(googleVoices.length>0){...}` che costruisce l'optgroup `gLabel+' Google HD'`. Il filtro `edgeVoices` resta identico.

- [ ] **Step 3: Rimuovere le stringhe i18n**

In `templates/_fragments/i18n_data.js`, eliminare le 7 chiavi che citano Google HD (una per locale). Verificare che nessuna resti referenziata:

```bash
grep -rn "Google HD\|gcloud" static/js/app.js templates/
```

Expected: nessun risultato.

- [ ] **Step 4: Rimuovere la classe CSS**

In `static/css/style.css`, eliminare la regola `.gcloud-voice`.

- [ ] **Step 5: Verificare a mano nel browser**

Avviare l'app, caricare un EPUB, aprire le Impostazioni audio.
Expected: il tab «Voci Standard» mostra le sole voci gratuite, nessun optgroup «Google HD», nessun errore in console.

- [ ] **Step 6: Eseguire la suite**

Run: `python -m pytest test/ -q`
Expected: verde. `test/test_app_js_tab_logic.py` legge `app.js` come testo: se un suo assert citava una stringa rimossa, correggerlo ora.

- [ ] **Step 7: Commit**

```bash
git add static/js/app.js templates/_fragments/i18n_data.js static/css/style.css
git commit -m "refactor(ui): elimina Google HD dal pannello voci

Il tab Standard resta con un motore solo: e' cio' che rende inutile la
riga MODELLO in quel tab.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3"
```

---

### Task 4: `language_source` nella risposta di analyze

**Files:**
- Modify: `audiobook_app.py:9243`, `9296`, `9406-9407`
- Test: `test/test_language_source.py` (create)

**Interfaces:**
- Consuma: `language_detected`, già calcolata a `audiobook_app.py:9277-9282`.
- Produce: nella risposta di `/api/analyze` e nel dict del job, la chiave `language_source` con valori `"metadata"` | `"detected"` | `"unknown"`. Il Task 6 la legge dal client.

- [ ] **Step 1: Scrivere i test (falliscono)**

```python
"""Provenienza della lingua del libro nella risposta di /api/analyze.

Tre valori: `metadata` (scritta nel file), `detected` (dedotta dall'IA
leggendo il testo), `unknown` (nessuna delle due). Il client li distingue
per decidere se avvisare l'utente prima di generare.
"""
import pathlib

SORGENTE = pathlib.Path("audiobook_app.py").read_text(encoding="utf-8")


def _derive(language, language_detected):
    """Copia della regola, per testarla senza montare l'app intera."""
    from audiobook_app import _derive_language_source
    return _derive_language_source(language, language_detected)


def test_lingua_dai_metadati():
    assert _derive("it", False) == "metadata"


def test_lingua_rilevata_dall_ia():
    assert _derive("sv", True) == "detected"


def test_lingua_assente():
    assert _derive("", False) == "unknown"


def test_lingua_assente_anche_se_solo_spazi():
    assert _derive("   ", False) == "unknown"


def test_language_source_nella_risposta_analyze():
    assert '"language_source"' in SORGENTE, (
        "la risposta di /api/analyze non espone language_source"
    )


def test_language_source_anche_sul_job_ripreso():
    """Riga 9243: il ramo del job gia' esistente non deve perdere la
    provenienza, altrimenti un job ripreso torna a sembrare `unknown`."""
    assert SORGENTE.count('"language_source"') >= 2, (
        "language_source emesso in un solo punto: il ramo del job ripreso "
        "lo perde"
    )
```

- [ ] **Step 2: Eseguire e verificare il fallimento**

Run: `python -m pytest test/test_language_source.py -v`
Expected: FAIL con `ImportError: cannot import name '_derive_language_source'`.

- [ ] **Step 3: Implementare la derivazione**

In `audiobook_app.py`, sopra il route di analyze:

```python
def _derive_language_source(language, language_detected):
    """Provenienza della lingua del libro, per il client.

    `metadata` = scritta nel file (dc:language dell'EPUB, metadati del PDF).
    `detected` = dedotta dall'IA leggendo il testo.
    `unknown`  = nessuna delle due: il client ripieghera' sul locale
                 dell'interfaccia e marchera' la lingua come ipotizzata,
                 il che fa scattare l'avviso prima della generazione.
    """
    if not (language or "").strip():
        return "unknown"
    return "detected" if language_detected else "metadata"
```

- [ ] **Step 4: Emetterlo nei tre punti**

1. Riga ~9296, nel dict del job, accanto a `"language_detected"`:

```python
                         "language_source": _derive_language_source(
                             info.language, language_detected)}
```

2. Riga ~9407, nella risposta di analyze, accanto a `"language_detected"`:

```python
        "language_source": _derive_language_source(
            info.language, language_detected),
```

3. Riga ~9243, nel ramo del job già esistente, accanto a
   `"language_detected": existing_job.get("language_detected", False)`:

```python
                "language_source": existing_job.get("language_source", "unknown"),
```

- [ ] **Step 5: Eseguire i test**

Run: `python -m pytest test/test_language_source.py test/test_lang_detect.py test/test_mobile_contract.py -v`
Expected: tutti PASSED. `test_lang_detect.py` (23 test) deve passare **intatto**: è la prova che il rilevamento non è stato toccato.

- [ ] **Step 6: Commit**

```bash
git add audiobook_app.py test/test_language_source.py
git commit -m "feat(analyze): la risposta dice da dove viene la lingua del libro

metadata / detected / unknown. Il dato c'era gia' (language_detected) ma
il client lo buttava via: senza, non puo' distinguere una lingua scritta
nel file da una indovinata.

Campo additivo: i client che lo ignorano si comportano come prima.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3"
```

---

### Task 5: La cascata come funzione pura

Il cuore. Nessun DOM, nessuna globale dell'app: si può testare davvero.

**Files:**
- Create: `static/js/audio_cascade.js`
- Create: `test/js/audio_cascade.test.js`
- Create: `test/test_js_cascade.py`
- Modify: `templates/_fragments/html_tail.html:3`

**Interfaces:**
- Consuma: nulla. È il fondo dello stack.
- Produce:

```js
resolveAudioSelection({lang, catalog, current}) → {
  lang: string,                       // lingua risolta, 2 lettere
  premiumEnabled: boolean,
  premiumReason: '' | 'no_premium_voices',
  tab: 'standard' | 'premium',
  standard: {accents: string[], accent: string, voices: object[], voice: string},
  premium:  {models: string[], model: string,
             accents: Array<[string, string]>, accent: string,
             voices: object[], voice: string},
  changes: Array<{what: 'tab'|'model'|'accent'|'voice', from: string, to: string, reason: string}>
}
```

  `current` ha la stessa forma di ritorno, in versione ridotta:
  `{tab, standardAccent, standardVoice, model, premiumAccent, premiumVoice}`.
  Tutti i campi sono facoltativi: assenti = prima costruzione.

- [ ] **Step 1: Scrivere i test (falliscono)**

```javascript
// test/js/audio_cascade.test.js
const test = require('node:test');
const assert = require('node:assert');
const {resolveAudioSelection} = require('../../static/js/audio_cascade.js');

/* Catalogo minimo, nella forma di /api/voices. Volutamente piccolo: i numeri
   veri (75 lingue, 1.957 voci) non rendono un test piu' vero, solo piu' lento
   da leggere quando fallisce. */
const CATALOGO = {
  _voxcpm: {available: true, model_label: 'VoxCPM2', personas: []},
  _premium_status: {capability_ok: true, admin_disabled: false},
  _translate_available: false,
  it: {name: 'Italian', voices: [
    {id: 'it-IT-IsabellaNeural', name: 'Isabella', gender: 'Female', locale: 'it-IT', engine: 'edge'},
    {id: 'it-IT-DiegoNeural', name: 'Diego', gender: 'Male', locale: 'it-IT', engine: 'edge'},
    {id: 'gemini:flash25:Achernar', name: 'Achernar', gender: 'Female', locale: 'it-IT', engine: 'gemini'},
    {id: 'voxcpm:v2:it-IT/Bianca', name: 'Bianca', gender: 'Female', locale: 'it-IT', engine: 'voxcpm'},
  ]},
  en: {name: 'English', voices: [
    {id: 'en-US-AvaNeural', name: 'Ava', gender: 'Female', locale: 'en-US', engine: 'edge'},
    {id: 'en-GB-SoniaNeural', name: 'Sonia', gender: 'Female', locale: 'en-GB', engine: 'edge'},
    {id: 'gemini:flash25:Puck', name: 'Puck', gender: 'Male', locale: 'en-US', engine: 'gemini', model_key: 'flash25'},
    {id: 'gemini:flash31:Puck', name: 'Puck', gender: 'Male', locale: 'en-US', engine: 'gemini', model_key: 'flash31'},
    {id: 'voxcpm:v2:en-US/Grace', name: 'Grace', gender: 'Female', locale: 'en-US', engine: 'voxcpm'},
    {id: 'speechify:simba-3.2:beatrice_32', name: 'Beatrice', gender: 'Female', locale: 'en-GB', engine: 'speechify'},
  ]},
  fr: {name: 'French', voices: [
    {id: 'fr-FR-DeniseNeural', name: 'Denise', gender: 'Female', locale: 'fr-FR', engine: 'edge'},
    {id: 'gemini:flash25:Kore', name: 'Kore', gender: 'Female', locale: 'fr-FR', engine: 'gemini'},
  ]},
  sv: {name: 'Swedish', voices: [
    {id: 'sv-SE-SofieNeural', name: 'Sofie', gender: 'Female', locale: 'sv-SE', engine: 'edge'},
  ]},
  es: {name: 'Spanish', voices: [
    {id: 'es-ES-ElviraNeural', name: 'Elvira', gender: 'Female', locale: 'es-ES', engine: 'edge'},
    {id: 'es-MX-DaliaNeural', name: 'Dalia', gender: 'Female', locale: 'es-MX', engine: 'edge'},
    {id: 'es-AR-ElenaNeural', name: 'Elena', gender: 'Female', locale: 'es-AR', engine: 'edge'},
    {id: 'gemini:flash25:Lyra', name: 'Lyra', gender: 'Female', locale: 'es-ES', engine: 'gemini'},
  ]},
};

test('italiano: premium attivo, tre modelli, VOXCPM2 di default', () => {
  const r = resolveAudioSelection({lang: 'it', catalog: CATALOGO, current: {}});
  assert.strictEqual(r.premiumEnabled, true);
  assert.deepStrictEqual(r.premium.models, ['voxcpm', 'flash25', 'flash31']);
  assert.strictEqual(r.premium.model, 'voxcpm');
});

test('italiano: un solo locale, niente riga accento in Standard', () => {
  const r = resolveAudioSelection({lang: 'it', catalog: CATALOGO, current: {}});
  assert.strictEqual(r.standard.accents.length, 1);
});

test('inglese: quattro modelli, Simba incluso', () => {
  const r = resolveAudioSelection({lang: 'en', catalog: CATALOGO, current: {}});
  assert.deepStrictEqual(r.premium.models,
    ['voxcpm', 'flash25', 'flash31', 'simba-3.2']);
});

test('i due modelli Gemini non condividono le voci', () => {
  /* Condividono il prefisso `gemini:` ma non l'id completo. Se il filtro
     tornasse al solo prefisso corto, ogni modello mostrerebbe anche le voci
     dell'altro e l'utente sceglierebbe una voce che il suo modello non ha. */
  const std = resolveAudioSelection({
    lang: 'en', catalog: CATALOGO, current: {tab: 'premium', model: 'flash25'}});
  const avz = resolveAudioSelection({
    lang: 'en', catalog: CATALOGO, current: {tab: 'premium', model: 'flash31'}});
  assert.deepStrictEqual(std.premium.voices.map(v => v.id), ['gemini:flash25:Puck']);
  assert.deepStrictEqual(avz.premium.voices.map(v => v.id), ['gemini:flash31:Puck']);
});

test('inglese con modello Avanzato: quattro varianti di accento', () => {
  const r = resolveAudioSelection({
    lang: 'en', catalog: CATALOGO, current: {tab: 'premium', model: 'flash31'}});
  assert.strictEqual(r.premium.model, 'flash31');
  assert.strictEqual(r.premium.accents.length, 4);
});

test('svedese: premium spento, col motivo', () => {
  const r = resolveAudioSelection({lang: 'sv', catalog: CATALOGO, current: {}});
  assert.strictEqual(r.premiumEnabled, false);
  assert.strictEqual(r.premiumReason, 'no_premium_voices');
  assert.strictEqual(r.tab, 'standard');
});

test('spagnolo: tre locali, riga accento visibile in Standard', () => {
  const r = resolveAudioSelection({lang: 'es', catalog: CATALOGO, current: {}});
  assert.deepStrictEqual(r.standard.accents.sort(),
    ['es-AR', 'es-ES', 'es-MX']);
});

test('catalogo senza Speechify: Simba assente anche in inglese', () => {
  const senzaSimba = JSON.parse(JSON.stringify(CATALOGO));
  senzaSimba.en.voices = senzaSimba.en.voices.filter(
    v => !v.id.startsWith('speechify:'));
  const r = resolveAudioSelection({lang: 'en', catalog: senzaSimba, current: {}});
  assert.ok(!r.premium.models.includes('simba-3.2'));
});

test('catalogo senza VoxCPM: il modello non compare', () => {
  const senzaVox = JSON.parse(JSON.stringify(CATALOGO));
  senzaVox._voxcpm = {available: false, model_label: '', personas: []};
  const r = resolveAudioSelection({lang: 'it', catalog: senzaVox, current: {}});
  assert.ok(!r.premium.models.includes('voxcpm'));
  assert.strictEqual(r.premium.model, 'flash25');
});

test('it -> sv con VOXCPM2 attivo: si scende a Standard e lo si dice', () => {
  const r = resolveAudioSelection({
    lang: 'sv', catalog: CATALOGO,
    current: {tab: 'premium', model: 'voxcpm', premiumVoice: 'voxcpm:v2:it-IT/Bianca'}});
  assert.strictEqual(r.tab, 'standard');
  const cambiati = r.changes.map(c => c.what);
  assert.ok(cambiati.includes('tab'), 'il cambio di tab non e` segnalato');
  assert.ok(cambiati.includes('model'), 'il cambio di modello non e` segnalato');
});

test('it -> fr con Avanzato attivo: il modello si preserva', () => {
  const r = resolveAudioSelection({
    lang: 'fr', catalog: CATALOGO,
    current: {tab: 'premium', model: 'flash31'}});
  assert.strictEqual(r.premium.model, 'flash31');
  assert.ok(!r.changes.some(c => c.what === 'model'),
    'un modello preservato non deve comparire fra i cambiamenti');
});

test('en -> it con Simba attivo: il modello non e` preservabile', () => {
  const r = resolveAudioSelection({
    lang: 'it', catalog: CATALOGO,
    current: {tab: 'premium', model: 'simba-3.2'}});
  assert.strictEqual(r.premium.model, 'voxcpm');
  assert.ok(r.changes.some(c => c.what === 'model'));
});

test('la cascata e` idempotente', () => {
  const primo = resolveAudioSelection({lang: 'en', catalog: CATALOGO, current: {}});
  const stato = {
    tab: primo.tab,
    standardAccent: primo.standard.accent,
    standardVoice: primo.standard.voice,
    model: primo.premium.model,
    premiumAccent: primo.premium.accent,
    premiumVoice: primo.premium.voice,
  };
  const secondo = resolveAudioSelection({lang: 'en', catalog: CATALOGO, current: stato});
  assert.deepStrictEqual(secondo.changes, [],
    'la seconda applicazione non deve cambiare nulla');
  assert.strictEqual(secondo.premium.model, primo.premium.model);
  assert.strictEqual(secondo.standard.voice, primo.standard.voice);
});

test('lingua sconosciuta al catalogo: non esplode', () => {
  const r = resolveAudioSelection({lang: 'xx', catalog: CATALOGO, current: {}});
  assert.strictEqual(r.premiumEnabled, false);
  assert.deepStrictEqual(r.standard.voices, []);
});
```

- [ ] **Step 2: Eseguire e verificare il fallimento**

Run: `node --test test/js/`
Expected: FAIL, `Cannot find module '../../static/js/audio_cascade.js'`.

- [ ] **Step 3: Implementare la cascata**

```javascript
// static/js/audio_cascade.js
'use strict';
/* Cascata lingua -> modello -> accento -> voce del pannello Impostazioni audio.
 *
 * FUNZIONE PURA: nessun accesso al DOM, nessuna globale dell'app. app.js la
 * chiama e riversa il risultato nei <select>; tutta la logica che puo'
 * rompersi vive qui, dove `node --test` la raggiunge senza un browser.
 *
 * La lingua non e' una scelta dell'utente: e' una proprieta' del libro. Questa
 * funzione riceve la lingua e decide COSA RESTA POSSIBILE, riportando in
 * `changes` cio' che ha dovuto spostare — che e' poi il testo che l'utente
 * legge quando forza la lingua.
 */

/* Varianti d'accento premium. Specchio di gemini_tts.ACCENT_VARIANTS. */
var ACCENT_CATALOG = {
  en: [['us', 'accent_en_us'], ['gb', 'accent_en_gb'], ['au', 'accent_en_au'], ['in', 'accent_en_in']],
  es: [['es', 'accent_es_es'], ['419', 'accent_es_419']],
  pt: [['br', 'accent_pt_br'], ['pt', 'accent_pt_pt']],
  fr: [['fr', 'accent_fr_fr'], ['ca', 'accent_fr_ca']],
  zh: [['cn', 'accent_zh_cn'], ['tw', 'accent_zh_tw']],
  de: [['de', 'accent_de_de'], ['at', 'accent_de_at'], ['ch', 'accent_de_ch']],
  ar: [['eg', 'accent_ar_eg'], ['sa', 'accent_ar_sa'], ['ae', 'accent_ar_ae']]
};

function _voci(catalog, lang) {
  var dati = catalog && catalog[lang];
  return (dati && Array.isArray(dati.voices)) ? dati.voices : [];
}

function _haPrefisso(voci, prefisso) {
  for (var i = 0; i < voci.length; i++) {
    var id = voci[i] && voci[i].id;
    if (typeof id === 'string' && id.indexOf(prefisso) === 0) return true;
  }
  return false;
}

/* Modelli premium disponibili per la lingua. L'ordine e' quello mostrato:
   VOXCPM2 primo dove c'e', poi i due Gemini, Simba in coda sull'inglese. */
function modelliPer(catalog, lang) {
  var voci = _voci(catalog, lang);
  var out = [];
  var voxAttivo = !!(catalog && catalog._voxcpm && catalog._voxcpm.available);
  if (voxAttivo && _haPrefisso(voci, 'voxcpm:')) out.push('voxcpm');
  if (_haPrefisso(voci, 'gemini:')) { out.push('flash25'); out.push('flash31'); }
  if (lang === 'en' && _haPrefisso(voci, 'speechify:simba-3.2:')) out.push('simba-3.2');
  return out;
}

/* Voci del tab Standard: solo il motore gratuito, filtrate per locale. */
function vociStandard(catalog, lang, locale) {
  var out = [];
  var voci = _voci(catalog, lang);
  for (var i = 0; i < voci.length; i++) {
    var v = voci[i];
    if (!v || (v.engine || 'edge') !== 'edge') continue;
    if (locale && v.locale !== locale) continue;
    out.push(v);
  }
  return out;
}

function localiStandard(catalog, lang) {
  var visti = {}, out = [];
  var voci = vociStandard(catalog, lang, '');
  for (var i = 0; i < voci.length; i++) {
    var loc = voci[i].locale || '';
    if (loc && !visti[loc]) { visti[loc] = true; out.push(loc); }
  }
  return out;
}

/* Voci premium per modello.
 *
 * L'id porta gia' il modello: gemini_tts.get_voices() emette
 * `gemini:<model_key>:<Nome>`, quindi il prefisso completo separa i due
 * modelli Gemini da solo. Il campo `model_key` c'e' anche nel catalogo, ma
 * filtrare sull'id non dipende dalla sua presenza: se un domani sparisse, un
 * filtro su model_key lascerebbe passare le voci di ENTRAMBI i modelli
 * silenziosamente, mentre questo non restituisce nulla e il difetto si vede. */
function vociPremium(catalog, lang, model) {
  var prefisso = model === 'voxcpm' ? 'voxcpm:'
               : model === 'simba-3.2' ? 'speechify:simba-3.2:'
               : 'gemini:' + model + ':';
  var out = [];
  var voci = _voci(catalog, lang);
  for (var i = 0; i < voci.length; i++) {
    var v = voci[i];
    var id = v && v.id;
    if (typeof id !== 'string' || id.indexOf(prefisso) !== 0) continue;
    out.push(v);
  }
  return out;
}

function _preserva(valore, disponibili) {
  return (valore && disponibili.indexOf(valore) !== -1) ? valore : null;
}

function _idsDi(voci) {
  var out = [];
  for (var i = 0; i < voci.length; i++) out.push(voci[i].id);
  return out;
}

function resolveAudioSelection(input) {
  input = input || {};
  var catalog = input.catalog || {};
  var current = input.current || {};
  var lang = String(input.lang || '').split('-')[0].toLowerCase();
  var changes = [];
  var segna = function (what, from, to, reason) {
    if (from === to) return;
    changes.push({what: what, from: from || '', to: to || '', reason: reason});
  };

  /* ── Modelli premium ─────────────────────────────────────────────── */
  var models = modelliPer(catalog, lang);
  var premiumEnabled = models.length > 0;
  var premiumReason = premiumEnabled ? '' : 'no_premium_voices';

  var model = _preserva(current.model, models) || (models.length ? models[0] : '');
  if (current.model && model !== current.model) {
    segna('model', current.model, model,
          premiumEnabled ? 'model_unavailable_in_lang' : 'no_premium_voices');
  }

  /* ── Tab ─────────────────────────────────────────────────────────── */
  var tab = current.tab === 'premium' ? 'premium' : 'standard';
  if (tab === 'premium' && !premiumEnabled) {
    segna('tab', 'premium', 'standard', 'no_premium_voices');
    tab = 'standard';
  }

  /* ── Accento e voce, tab Standard ────────────────────────────────── */
  var accentiStd = localiStandard(catalog, lang);
  var accentoStd = _preserva(current.standardAccent, accentiStd)
                   || (accentiStd.length ? accentiStd[0] : '');
  if (current.standardAccent && accentoStd !== current.standardAccent) {
    segna('accent', current.standardAccent, accentoStd, 'accent_unavailable_in_lang');
  }
  /* Con un solo locale il filtro non serve: mostra tutte le voci gratuite. */
  var vociStd = vociStandard(catalog, lang, accentiStd.length > 1 ? accentoStd : '');
  var idsStd = _idsDi(vociStd);
  var voceStd = _preserva(current.standardVoice, idsStd)
                || (idsStd.length ? idsStd[0] : '');
  if (current.standardVoice && voceStd !== current.standardVoice) {
    segna('voice', current.standardVoice, voceStd, 'voice_unavailable_in_lang');
  }

  /* ── Accento e voce, tab PREMIUM ─────────────────────────────────── */
  /* L'accento premium esiste solo per i modelli Gemini: VOXCPM2 e Simba
     hanno cataloghi propri, gestiti da app.js fuori da questa cascata. */
  var eGemini = (model === 'flash25' || model === 'flash31');
  var accentiPrem = (eGemini && ACCENT_CATALOG[lang]) ? ACCENT_CATALOG[lang] : [];
  var codiciPrem = [];
  for (var k = 0; k < accentiPrem.length; k++) codiciPrem.push(accentiPrem[k][0]);
  var accentoPrem = _preserva(current.premiumAccent, codiciPrem)
                    || (codiciPrem.length ? codiciPrem[0] : '');

  var vociPrem = premiumEnabled ? vociPremium(catalog, lang, model) : [];
  var idsPrem = _idsDi(vociPrem);
  var vocePrem = _preserva(current.premiumVoice, idsPrem)
                 || (idsPrem.length ? idsPrem[0] : '');
  if (current.premiumVoice && vocePrem !== current.premiumVoice) {
    segna('voice', current.premiumVoice, vocePrem, 'voice_unavailable_in_lang');
  }

  return {
    lang: lang,
    premiumEnabled: premiumEnabled,
    premiumReason: premiumReason,
    tab: tab,
    standard: {accents: accentiStd, accent: accentoStd,
               voices: vociStd, voice: voceStd},
    premium: {models: models, model: model,
              accents: accentiPrem, accent: accentoPrem,
              voices: vociPrem, voice: vocePrem},
    changes: changes
  };
}

/* Doppia esposizione: `window` per il browser (script `defer`, nessun
   bundler), `module.exports` per node --test. */
if (typeof window !== 'undefined') {
  window.resolveAudioSelection = resolveAudioSelection;
  window.ACCENT_CATALOG = ACCENT_CATALOG;
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {resolveAudioSelection: resolveAudioSelection,
                    ACCENT_CATALOG: ACCENT_CATALOG,
                    modelliPer: modelliPer};
}
```

- [ ] **Step 4: Eseguire i test JS**

Run: `node --test test/js/`
Expected: 14 pass, 0 fail. Se `idempotente` fallisce, il colpevole è quasi sempre un `segna()` chiamato anche quando `from === to`: la guardia è dentro `segna`, verificare di non aver aggiunto push diretti a `changes`.

- [ ] **Step 5: Scrivere il wrapper pytest**

```python
"""Esegue i test della cascata JS dentro pytest.

La cascata e' logica pura in JavaScript: i test a grep su app.js — quelli
che verificano che il sorgente CONTENGA certe stringhe — passerebbero con la
cascata rotta. Qui si esegue davvero, con node:test (libreria standard di
Node, nessuna dipendenza aggiunta).
"""
import pathlib
import shutil
import subprocess

import pytest

RADICE = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node non installato: la cascata JS non e' verificabile")
def test_cascata_audio_js():
    esito = subprocess.run(
        ["node", "--test", "test/js/"],
        cwd=RADICE, capture_output=True, text=True, timeout=120,
    )
    assert esito.returncode == 0, (
        "test della cascata JS falliti:\n" + esito.stdout + esito.stderr
    )
```

- [ ] **Step 6: Eseguire il wrapper**

Run: `python -m pytest test/test_js_cascade.py -v`
Expected: PASSED.

- [ ] **Step 7: Caricare lo script nella pagina**

In `templates/_fragments/html_tail.html:3`, **prima** di `app.js` (gli script `defer` girano in ordine di dichiarazione):

```html
<script defer src="/static/js/audio_cascade.js?v=__APP_VERSION__"></script>
<script defer src="/static/js/app.js?v=__APP_VERSION__"></script>
```

- [ ] **Step 8: Commit**

```bash
git add static/js/audio_cascade.js test/js/audio_cascade.test.js test/test_js_cascade.py templates/_fragments/html_tail.html
git commit -m "feat(audio): la cascata lingua->modello->accento->voce, senza DOM

Funzione pura in un file suo, con 14 test eseguiti da node:test (libreria
standard, nessuna dipendenza nuova) e un wrapper perche' pytest resti
l'unico comando d'ingresso.

I test JS di questo repo leggono app.js come testo e verificano che
contenga certe stringhe: su logica pura passerebbero anche rotta.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3"
```

---

### Task 6: La lingua esce dai tab

Il task grosso, e atomico: non si può togliere `#vl` senza aggiornare nello stesso commit i 32 punti che lo leggono.

**Files:**
- Modify: `templates/_fragments/html_head.html:385`, `400-419`
- Modify: `static/js/app.js` — rimozione di `fillLangs()` (861-931) e `syncLanguageOptions()` (940-1004), nuova `applyBookLanguage()`, aggiornamento dei 32 lettori
- Modify: `templates/_fragments/i18n_data.js` (chiavi nuove × 7 locali)
- Modify: `static/css/style.css`
- Modify: `test/test_app_js_tab_logic.py`

**Interfaces:**
- Consuma: `resolveAudioSelection()` da Task 5, `language_source` da Task 4.
- Produce: lo stato globale `bookLangState = {code, source}` con `source ∈ {'metadata','detected','assumed','forced'}`, e `applyBookLanguage()` che chiama la cascata e rende il risultato. Il Task 8 chiama entrambi.

- [ ] **Step 1: Aggiungere le chiavi i18n**

In `templates/_fragments/i18n_data.js`, per **tutti e 7** i locali (`it`, `en`, `fr`, `es`, `de`, `zh`, `hi`). Valori italiani e inglesi qui sotto; per gli altri cinque tradurre con lo stesso registro.

```js
// it:
lbl_book_lang:"Lingua del libro",
lang_src_metadata:"dai metadati",
lang_src_detected:"rilevata dal testo",
lang_src_assumed:"non rilevata, ipotizzata",
lang_src_forced:"impostata da te",
tip_force_lang:"Forza la lingua del libro",
premium_no_lang:"Le voci PREMIUM non sono disponibili in {lang}.",
lbl_accent_std:"Accento",

// en:
lbl_book_lang:"Book language",
lang_src_metadata:"from metadata",
lang_src_detected:"detected from the text",
lang_src_assumed:"not detected, assumed",
lang_src_forced:"set by you",
tip_force_lang:"Force the book language",
premium_no_lang:"PREMIUM voices are not available in {lang}.",
lbl_accent_std:"Accent",
```

Verifica: `grep -c "lbl_book_lang" templates/_fragments/i18n_data.js` deve dare `7`.

- [ ] **Step 2: Riscrivere il markup del pannello**

In `templates/_fragments/html_head.html`, sostituire la riga 385 (`<div id="voiceMismatch" ...>`) con la riga della lingua del libro:

```html
      <div class="book-lang-row" id="bookLangRow">
        <span class="book-lang-label" data-t="lbl_book_lang"></span>
        <strong class="book-lang-name" id="bookLangName"></strong>
        <span class="book-lang-src" id="bookLangSrc"></span>
        <!-- `hidden` fino al Task 8, che porta openForceLangModal(): fra i due
             commit il pulsante esisterebbe senza la sua funzione. -->
        <button type="button" id="forceLangBtn" class="icon-btn" hidden
                data-t-title="tip_force_lang" aria-haspopup="dialog"
                onclick="openForceLangModal()">&#9881;</button>
      </div>
      <div class="al al-i" id="cascadeNote" hidden role="status" aria-live="polite"></div>
```

Sostituire il contenuto di `#tabStandard` (righe 400-406), togliendo `#vl` e aggiungendo la riga accento:

```html
      <div class="tab-panel" id="tabStandard" role="tabpanel" aria-labelledby="tabStandardBtn">
        <div class="form-row" id="stdAccentRow" hidden>
          <div class="form-group" style="flex:1 1 100%">
            <label for="stdAccent" data-t="lbl_accent_std"></label>
            <select id="stdAccent"></select>
          </div>
        </div>
        <div class="form-row">
          <div class="form-group" style="flex:1 1 100%">
            <label for="vv" data-t="lbl_voice"></label>
            <select id="vv"><option data-t="voice_ph"></option></select>
          </div>
        </div>
      </div>
```

In `#tabPremium` (righe 408-417) togliere il gruppo `vlPremium` e lasciare il modello da solo:

```html
        <div class="form-row">
          <div class="form-group" style="flex:1 1 100%">
            <label for="vmPremium" data-t="lbl_model">Modello</label>
            <select id="vmPremium"></select>
            <div class="model-rate-hint" id="modelRateHint"></div>
          </div>
        </div>
        <div class="form-row" id="premiumOffRow" hidden>
          <div class="al al-w" id="premiumOffMsg"></div>
        </div>
```

- [ ] **Step 3: Introdurre lo stato della lingua e `applyBookLanguage()`**

In `static/js/app.js`, al posto di `fillLangs()` e `syncLanguageOptions()` (righe 861-1004, entrambe da eliminare):

```js
/* Lingua del libro: non e' una scelta dell'utente, e' una proprieta' del
   libro. `source` dice da dove viene, e serve a decidere se avvisare prima
   di generare: 'metadata' e 'detected' arrivano dal server, 'assumed' e'
   il ripiego sul locale dell'interfaccia quando il server dice 'unknown',
   'forced' e' la correzione manuale. */
let bookLangState={code:'',source:'unknown'};

function _langLabel(code){
  if(L[cl]&&L[cl].langs&&L[cl].langs[code])return L[cl].langs[code];
  if(L['en']&&L['en'].langs&&L['en'].langs[code])return L['en'].langs[code];
  const d=voices&&voices[code];
  return (d&&d.name)||code;
}

/* Legge la lingua dalla risposta di analyze. Quando il server non l'ha
   trovata si ripiega sul locale dell'interfaccia — ma marcandolo, perche' e'
   la marcatura a far scattare l'avviso in _validateLanguage(). */
function initBookLanguage(){
  const src=(bookData&&bookData.language_source)||'unknown';
  let code=((bookData&&bookData.language)||'').split('-')[0].toLowerCase();
  if(src==='unknown'||!code||!voices[code]){
    code=(voices&&voices[cl])?cl:(Object.keys(voices)[0]||'');
    bookLangState={code:code,source:'assumed'};
  }else{
    bookLangState={code:code,source:src};
  }
  applyBookLanguage();
}

/* Chiama la cascata e riversa il risultato nel DOM. Nessuna decisione qui:
   e' un renderer. */
function applyBookLanguage(){
  if(!bookLangState.code)return;
  const esito=resolveAudioSelection({
    lang:bookLangState.code,
    catalog:voices,
    current:{
      tab:(wizardState&&wizardState.audioTab)||'standard',
      standardAccent:document.getElementById('stdAccent')?.value||'',
      standardVoice:document.getElementById('vv')?.value||'',
      model:document.getElementById('vmPremium')?.value||'',
      premiumAccent:document.getElementById('geminiAccent')?.value||'',
      premiumVoice:document.getElementById('vvPremium')?.value||''
    }
  });

  // Riga lingua del libro
  const nm=document.getElementById('bookLangName');
  if(nm)nm.textContent=_langLabel(bookLangState.code);
  const sr=document.getElementById('bookLangSrc');
  if(sr){
    sr.textContent=t('lang_src_'+bookLangState.source)||'';
    sr.classList.toggle('is-warn',bookLangState.source==='assumed');
  }

  // Tab PREMIUM: spento con il motivo, se la lingua non ha voci a pagamento
  const btn=document.getElementById('tabPremiumBtn');
  if(btn)btn.disabled=!esito.premiumEnabled;
  const offRow=document.getElementById('premiumOffRow');
  const offMsg=document.getElementById('premiumOffMsg');
  if(offRow)offRow.hidden=esito.premiumEnabled;
  if(offMsg&&!esito.premiumEnabled){
    offMsg.textContent=(t('premium_no_lang')||'')
      .replace('{lang}',_langLabel(bookLangState.code));
  }
  if(!esito.premiumEnabled&&wizardState&&wizardState.audioTab==='premium'){
    switchAudioTab('standard');
  }

  // Tab Standard: accento (solo se >1) e voci
  const accRow=document.getElementById('stdAccentRow');
  const accSel=document.getElementById('stdAccent');
  if(accRow&&accSel){
    if(esito.standard.accents.length<2){
      accRow.hidden=true;accSel.innerHTML='';accSel.value='';
    }else{
      accSel.innerHTML='';
      for(const loc of esito.standard.accents){
        const o=document.createElement('option');
        o.value=loc;o.textContent=loc;accSel.appendChild(o);
      }
      accSel.value=esito.standard.accent;
      accRow.hidden=false;
      accSel.onchange=()=>{applyBookLanguage();_onPreviewParamsChanged();};
    }
  }
  _renderStandardVoices(esito.standard);

  // Tab PREMIUM: modello (solo se >1), poi le righe dipendenti
  const vm=document.getElementById('vmPremium');
  if(vm&&esito.premiumEnabled){
    vm.innerHTML='';
    for(const m of esito.premium.models){
      const o=document.createElement('option');
      o.value=m;o.textContent=_modelLabel(m);vm.appendChild(o);
    }
    vm.value=esito.premium.model;
    const vmRow=vm.closest('.form-row');
    if(vmRow)vmRow.hidden=esito.premium.models.length<2;
    if(typeof _onPremiumModelChanged==='function')_onPremiumModelChanged();
  }

  _showCascadeNote(esito.changes);
  if(typeof requestCombinedEstimate==='function')requestCombinedEstimate();
}

/* Etichette dei modelli. Nessun nome di fornitore: sono etichette di
   prodotto, non di motore. */
function _modelLabel(m){
  if(m==='voxcpm')return t('lbl_model_voxcpm')||'Audiobook Maker (VOXCPM2)';
  if(m==='flash25')return t('lbl_model_flash25')||'Standard';
  if(m==='flash31')return t('lbl_model_flash31')||'Avanzato';
  if(m==='simba-3.2')return t('lbl_model_simba')||'Express';
  return m;
}

/* Voci del tab Standard, raggruppate per genere come prima. */
function _renderStandardVoices(std){
  const sel=document.getElementById('vv');
  if(!sel)return;
  sel.innerHTML='';
  let lg='';
  for(const v of std.voices){
    if(v.gender!==lg){
      const g=document.createElement('optgroup');
      g.label=v.gender==='Female'?'♀':'♂';
      sel.appendChild(g);lg=v.gender;
    }
    const o=document.createElement('option');
    o.value=v.id;o.textContent=v.gender_icon+' '+v.name+' ('+v.locale+')';
    sel.lastElementChild.appendChild(o);
  }
  sel.value=std.voice;
  sel.onchange=()=>{_updateVoiceChip();_onPreviewParamsChanged();};
  _updateVoiceChip();
}

/* La nota di cosa e' cambiato. L'elenco arriva dalla cascata: non si
   ricostruisce con confronti sparsi. */
function _showCascadeNote(changes){
  const box=document.getElementById('cascadeNote');
  if(!box)return;
  if(!changes||!changes.length){box.hidden=true;box.textContent='';return;}
  const pezzi=[];
  if(changes.some(c=>c.what==='tab'||c.what==='model'))pezzi.push(t('note_model_reset'));
  if(changes.some(c=>c.what==='voice'))pezzi.push(t('note_voice_reset'));
  if(changes.some(c=>c.what==='accent'))pezzi.push(t('note_accent_reset'));
  box.textContent=(t('note_lang_set')||'').replace('{lang}',_langLabel(bookLangState.code))
                  +' '+pezzi.join(' ');
  box.hidden=false;
}
```

Aggiungere anche le 4 chiavi i18n usate qui (`note_lang_set`, `note_model_reset`, `note_voice_reset`, `note_accent_reset`) nei 7 locali. In italiano: `note_lang_set:"Lingua impostata su {lang}."`, `note_model_reset:"Modello e voce riportati al valore predefinito."`, `note_voice_reset:"Voce riportata al valore predefinito."`, `note_accent_reset:"Accento riportato al valore predefinito."`. In inglese: `"Language set to {lang}."`, `"Model and voice reset to the default."`, `"Voice reset to the default."`, `"Accent reset to the default."`.

- [ ] **Step 4: Eliminare `updVoices()` e redirigere i suoi call-site**

`_renderStandardVoices()` la sostituisce, ma `updVoices()` (riga 1005) ha
cinque chiamanti che vanno risolti nello stesso commit, altrimenti restano
riferimenti a una funzione che non esiste più:

| riga | contesto | cosa farne |
|---|---|---|
| 406 | handler che propagava la lingua premium alla combo standard | rimuovere l'intero handler: le due combo non esistono più |
| 666 | inizializzazione | `applyBookLanguage();` |
| 891, 929 | dentro `fillLangs()` | spariscono con `fillLangs()` |
| 5310 | dentro `autoFixVoice()` | resta fino al Task 7, che elimina la funzione |

Quindi: eliminare il corpo di `updVoices()`, sistemare 406 e 666, e lasciare
`autoFixVoice()` intatta — è il Task 7 a portarla via. Se dopo questo step
`grep -n "updVoices()" static/js/app.js` mostra ancora la riga 5310, è
corretto: quel riferimento muore col Task 7.

Fra i due commit `autoFixVoice()` contiene quindi una chiamata a una funzione
inesistente, ma è **irraggiungibile**: la sua unica via d'accesso era il
pulsante dentro `#voiceMismatch`, che questo stesso task ha appena tolto dal
markup. Nessun percorso vivo può innescarla.

- [ ] **Step 5: Aggiornare i 32 lettori delle vecchie combo**

```bash
grep -n "getElementById('vl')\|getElementById('vlPremium')" static/js/app.js
```

Sostituire **ogni** occorrenza con `bookLangState.code`. Le sostituzioni non banali, per riga:

| riga | prima | dopo |
|---|---|---|
| 2166 `_premiumLang()` | legge `#vlPremium` | `return bookLangState.code;` |
| 3223-3224 `_validateLanguage()` | `voiceLang` da due combo | `const voiceLang=bookLangState.code;` |
| 3266, 3292, 3352, 3781 (payload `lang`) | ternario sul tab | `bookLangState.code||cl` |
| 1743, 1763, 1975, 2240 | ternario sul tab | `bookLangState.code` |
| 3063 | `#vl`.value \|\| cl | `bookLangState.code||cl` |
| 403-405, 663, 2956 | riferimenti in init/adopt | vedi Step 5 |

I payload continuano a mandare `lang`: è il canale su cui viaggia la forzatura (I2 riguarda il **server**, che deve tollerarne l'assenza — il client web lo manda comunque).

- [ ] **Step 6: Aggiornare i punti di ingresso**

- Riga 726: `fillLangs();` → `initBookLanguage();`
- Riga 5235: `if(typeof voices!=='undefined' && ...) fillLangs();` → `... applyBookLanguage();`
- Riga 2960, in `adoptTranslation()`: `fillLangs();` →

```js
  bookLangState={code:(d.language||'').split('-')[0].toLowerCase(),source:'metadata'};
  applyBookLanguage();
```

- Riga 667: `syncLanguageOptions()` → rimuovere la chiamata.

- [ ] **Step 7: Semplificare `_validateLanguage()`**

Con una lingua sola non c'è più un mismatch fra due combo: resta il solo caso della lingua ipotizzata.

```js
async function _validateLanguage() {
  if(!bookData) return true;
  // La lingua e' ipotizzata (il server non l'ha trovata e nessuno l'ha
  // corretta): chiedi conferma prima di spendere una generazione.
  if(bookLangState.source==='assumed' && !previewListened) {
    return await _showLangWarning();
  }
  return true;
}
```

- [ ] **Step 8: Stile della riga lingua**

In `static/css/style.css`:

```css
.book-lang-row{display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap}
.book-lang-label{color:var(--fg2)}
.book-lang-src{color:var(--fg2);font-size:.9em}
.book-lang-src.is-warn{color:var(--warn)}
.icon-btn{background:none;border:1px solid var(--bd);border-radius:6px;
          cursor:pointer;padding:2px 8px;line-height:1.6}
```

Se `--fg2`, `--warn` o `--bd` non esistono nel file, usare le variabili equivalenti già in uso (cercare `--err` e `--ac`, presenti in `autoFixVoice`).

- [ ] **Step 9: Aggiornare i test a grep**

`test/test_app_js_tab_logic.py` cita `vlPremium` e `fillLangs`. **Non cancellare i test**: cambiarne l'oggetto. `test_validateLanguage_uses_vlPremium` diventa:

```python
def test_validateLanguage_legge_lo_stato_unico_della_lingua():
    """La guardia non confronta piu' due combo: ne esiste una sola fonte."""
    corpo = _estrai_funzione(APP_JS, "_validateLanguage")
    assert "bookLangState" in corpo
    assert "vlPremium" not in corpo, "residuo della vecchia combo premium"
```

- [ ] **Step 10: Eseguire tutto**

Run: `python -m pytest test/ -q && node --test test/js/`
Expected: verde su entrambi.

- [ ] **Step 11: Verifica manuale nel browser**

Caricare un EPUB italiano. Expected: sopra i tab si legge «Lingua del libro: Italiano (dai metadati)»; il tab Standard mostra solo la voce (l'italiano ha un locale solo); il tab PREMIUM mostra tre modelli con VOXCPM2 selezionato; nessun errore in console.

- [ ] **Step 12: Commit**

```bash
git add static/js/app.js templates/_fragments/html_head.html templates/_fragments/i18n_data.js static/css/style.css test/test_app_js_tab_logic.py
git commit -m "feat(audio): la lingua esce dai tab e diventa stato del libro

Sparivano fillLangs() e syncLanguageOptions(): la seconda elencava le
lingue di UN SOLO modello e le etichettava col suo conteggio, e quando la
lingua corrente non era coperta la cambiava in silenzio.

Dentro i tab resta la sola catena modello -> accento -> voce, con la
regola gia' in uso per l'accento estesa al modello: niente tendine con
una sola voce dentro.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3"
```

---

### Task 7: Via il banner di mismatch

Esisteva solo perché le due combo potevano divergere. Tolta la divergenza, sparisce la classe di problemi.

**Files:**
- Modify: `static/js/app.js` — rimozione di `checkVoiceMismatch()` (5266-5304) e `autoFixVoice()` (5306-5337)
- Modify: `static/css/style.css` (`.vm-link`)

**Interfaces:**
- Consuma: `bookLangState` di Task 6.
- Produce: nulla. È solo rimozione.

- [ ] **Step 1: Eliminare le due funzioni**

Rimuovere `checkVoiceMismatch()` e `autoFixVoice()` per intero, comprese le tabelle inline dei nomi di 13 lingue × 7 locali e i 7 messaggi tradotti a mano — testo che, oltre a essere morto, aggirava il file i18n.

- [ ] **Step 2: Eliminare le chiamate**

```bash
grep -n "checkVoiceMismatch()\|autoFixVoice(" static/js/app.js
```

Punti attesi: 1061, 1062 (dentro il vecchio `updVoices`, già sostituito da `_renderStandardVoices` in Task 6), 2574, 5233. Rimuoverle tutte.

- [ ] **Step 3: Eliminare lo stile**

In `static/css/style.css`, rimuovere `.vm-link`.

- [ ] **Step 4: Verificare che non resti nulla**

```bash
grep -rn "voiceMismatch\|autoFixVoice\|vm-link" static/ templates/
```
Expected: nessun risultato.

- [ ] **Step 5: Eseguire tutto**

Run: `python -m pytest test/ -q && node --test test/js/`
Expected: verde.

- [ ] **Step 6: Commit**

```bash
git add static/js/app.js static/css/style.css
git commit -m "refactor(audio): via il banner di mismatch e la sua auto-correzione

Esisteva solo perche' le due combo lingua potevano divergere. Con una
lingua sola il mismatch non e' piu' rappresentabile.

Se ne vanno anche 13 lingue x 7 locali di nomi cablati nel JS, che
aggiravano il file i18n.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3"
```

---

### Task 8: Il modale di forzatura

**Files:**
- Modify: `templates/_fragments/html_head.html` (nuovo modale accanto a `#langWarnModal`, riga ~1007)
- Modify: `static/js/app.js` (`openForceLangModal`, `confirmForceLang`)
- Modify: `templates/_fragments/i18n_data.js`

**Interfaces:**
- Consuma: `bookLangState` e `applyBookLanguage()` da Task 6, `resolveAudioSelection` da Task 5.
- Produce: `openForceLangModal()`, già referenziata dall'`onclick` del markup di Task 6.

- [ ] **Step 1: Aggiungere le chiavi i18n**

Nei 7 locali. Italiano / inglese:

```js
// it:
force_lang_title:"Forza la lingua del libro",
force_lang_hint:"Scegli la lingua in cui il libro è scritto. L'elenco delle voci si aggiorna di conseguenza.",
force_lang_premium_yes:"con voci PREMIUM",
force_lang_ok:"Conferma",
force_lang_cancel:"Annulla",

// en:
force_lang_title:"Force the book language",
force_lang_hint:"Pick the language the book is written in. The voice list updates accordingly.",
force_lang_premium_yes:"with PREMIUM voices",
force_lang_ok:"Confirm",
force_lang_cancel:"Cancel",
```

- [ ] **Step 2: Aggiungere il markup del modale**

In `templates/_fragments/html_head.html`, accanto a `#langWarnModal`:

```html
    <div class="modal" id="forceLangModal" role="dialog" aria-modal="true"
         aria-labelledby="forceLangTitle">
      <div class="modal-box">
        <h3 id="forceLangTitle" data-t="force_lang_title"></h3>
        <p class="subtitle" data-t="force_lang_hint"></p>
        <select id="forceLangSelect" size="12" style="width:100%"></select>
        <div class="modal-actions">
          <button type="button" class="btn-ghost" data-t="force_lang_cancel"
                  onclick="closeForceLangModal()"></button>
          <button type="button" class="btn" data-t="force_lang_ok"
                  onclick="confirmForceLang()"></button>
        </div>
      </div>
    </div>
```

- [ ] **Step 3: Rendere visibile il pulsante**

Il Task 6 lo aveva lasciato `hidden` perché la sua funzione non esisteva
ancora. In `templates/_fragments/html_head.html`, togliere `hidden` da
`#forceLangBtn`.

- [ ] **Step 4: Implementare apertura e conferma**

In `static/js/app.js`:

```js
/* Elenco: l'unione di tutte le lingue dei modelli disponibili. Il motore
   gratuito le copre tutte, quindi sono tutte quelle del catalogo. Accanto a
   ciascuna si dice se ha voci a pagamento, cosi' la scelta e' informata
   prima di farla invece che scoperta dopo. */
function openForceLangModal(){
  const sel=document.getElementById('forceLangSelect');
  if(!sel)return;
  sel.innerHTML='';
  const righe=Object.keys(voices)
    .filter(c=>!c.startsWith('_'))
    .map(c=>({code:c,name:_langLabel(c),
              premium:resolveAudioSelection({lang:c,catalog:voices,current:{}}).premiumEnabled}))
    .sort((a,b)=>a.name.localeCompare(b.name,cl));
  for(const r of righe){
    const o=document.createElement('option');
    o.value=r.code;
    o.textContent=r.name+(r.premium?' — '+(t('force_lang_premium_yes')||''):'');
    sel.appendChild(o);
  }
  sel.value=bookLangState.code;
  applyI18n();
  document.getElementById('forceLangModal').classList.add('open');
}

function closeForceLangModal(){
  document.getElementById('forceLangModal').classList.remove('open');
}

function confirmForceLang(){
  const sel=document.getElementById('forceLangSelect');
  const scelta=sel&&sel.value;
  closeForceLangModal();
  if(!scelta||scelta===bookLangState.code)return;
  // L'utente ha dichiarato lui la lingua: da qui in poi e' affidabile, e
  // l'avviso prima della generazione non ha piu' ragione di scattare.
  bookLangState={code:scelta,source:'forced'};
  _rememberLastLang(scelta);
  applyBookLanguage();   // preserva il preservabile e scrive la nota
}
```

- [ ] **Step 5: Verificare a mano il caso che conta**

Caricare un EPUB italiano, andare nel tab PREMIUM, selezionare VOXCPM2. Aprire il modale, scegliere lo svedese, confermare.
Expected: il tab PREMIUM si spegne col motivo scritto; si torna a Standard; sotto la riga della lingua compare «Lingua impostata su svedese. Modello e voce riportati al valore predefinito.»

Poi riaprire il modale e tornare all'italiano.
Expected: il tab PREMIUM torna attivo, la riga della lingua dice «impostata da te».

- [ ] **Step 6: Verificare il caso di preservazione**

Con un EPUB italiano, tab PREMIUM, modello «Avanzato». Forzare il francese.
Expected: «Avanzato» resta selezionato (esiste anche in francese) e la nota **non** parla di modello.

- [ ] **Step 7: Eseguire tutto**

Run: `python -m pytest test/ -q && node --test test/js/`
Expected: verde.

- [ ] **Step 8: Commit**

```bash
git add static/js/app.js templates/_fragments/html_head.html templates/_fragments/i18n_data.js
git commit -m "feat(audio): l'utente puo' correggere la lingua del libro

Elenca l'unione delle lingue disponibili dicendo quali hanno voci a
pagamento, cosi' la scelta e' informata prima di farla. La conferma
preserva cio' che resta valido e scrive cosa ha dovuto spostare.

L'elenco dei cambiamenti arriva dalla cascata, che sa gia' cosa ha
cambiato: non si ricostruisce con confronti sparsi.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3"
```

---

### Task 9: Collaudo manuale e rilascio

**Files:**
- Create: `docs/MANUAL_TESTS_AUDIO_LANGUAGE.md`
- Modify: `version.py`
- Modify: `md_files/PARAMETRI_CONFIGURAZIONE.md` (se cita Google HD)

**Interfaces:**
- Consuma: tutto il resto.
- Produce: il documento che l'utente segue prima di autorizzare il push.

- [ ] **Step 1: Scrivere il documento di collaudo**

`docs/MANUAL_TESTS_AUDIO_LANGUAGE.md`, nello stile di `MANUAL_TESTS_VOXCPM.md` (passi numerati, «→ _atteso: …_»):

```markdown
# Collaudo manuale — lingua del libro e cascata dei modelli

Da eseguire sull'istanza locale prima di autorizzare il push.
Nota: in locale `_translate_available` è `false`, quindi il pulsante
«Traduci il libro» non compare. Non è un difetto.

## 1. Lingua dai metadati
1. Caricare un EPUB italiano con `dc:language` valorizzato.
2. Aprire le Impostazioni audio.
   → _atteso: «Lingua del libro: Italiano (dai metadati)», nessuna combo lingua._
3. Guardare il tab Standard.
   → _atteso: nessuna riga ACCENTO (l'italiano ha un locale solo), solo la voce._
4. Passare al tab PREMIUM.
   → _atteso: tre modelli, VOXCPM2 selezionato._

## 2. Lingua senza voci a pagamento
1. Caricare un EPUB svedese.
   → _atteso: il tab PREMIUM è disabilitato e dice perché._
2. Provare a cliccarlo.
   → _atteso: non cambia tab._

## 3. Molti accenti
1. Caricare un EPUB spagnolo, tab Standard.
   → _atteso: la riga ACCENTO compare con più varianti._
2. Cambiare accento.
   → _atteso: l'elenco delle voci si restringe a quel locale._

## 4. Quattro modelli in inglese
1. Caricare un EPUB inglese, tab PREMIUM.
   → _atteso: quattro modelli._
2. Selezionare «Avanzato».
   → _atteso: la riga ACCENTO premium mostra quattro varianti._

## 5. Lingua non rilevata
1. Caricare un TXT senza metadati, con il rilevamento IA spento.
   → _atteso: «non rilevata, ipotizzata», in evidenza._
2. Avviare la generazione senza ascoltare l'anteprima.
   → _atteso: compare l'avviso sulla lingua._

## 6. Forzatura, andata e ritorno
1. EPUB italiano, tab PREMIUM, VOXCPM2. Forzare lo svedese.
   → _atteso: si torna a Standard, con la nota di cosa è cambiato._
2. Riportare la lingua all'italiano.
   → _atteso: il tab PREMIUM torna attivo, la riga dice «impostata da te»._

## 7. Preservazione
1. EPUB italiano, PREMIUM, modello «Avanzato». Forzare il francese.
   → _atteso: «Avanzato» resta, la nota NON parla di modello._

## 8. La forzatura sopravvive al riavvio
1. Forzare una lingua e avviare una generazione.
2. Riavviare il server mentre il job è in corso, lasciare che il recovery riprenda.
   → _atteso: il job riprende con la lingua FORZATA, non con quella dei metadati._

## 9. Contratto mobile
1. `curl -s http://127.0.0.1:5601/api/voices | python -c "import json,sys; d=json.load(sys.stdin); print(all(v.get('engine') for k,x in d.items() if not k.startswith('_') for v in x.get('voices',[])))"`
   → _atteso: `True`._
```

- [ ] **Step 2: Alzare la versione**

In `version.py`: `__version__ = "3.49.0"`. Serve anche a invalidare la cache di `audio_cascade.js` e `app.js`, che usano `?v=__APP_VERSION__`.

- [ ] **Step 3: Ripulire la documentazione dai riferimenti a Google HD**

```bash
grep -rn "Google HD\|google_tts\|GOOGLE_TTS" md_files/ docs/ --include=*.md
```

Aggiornare `md_files/PARAMETRI_CONFIGURAZIONE.md` se elenca variabili d'ambiente del motore rimosso. Non toccare le spec storiche in `docs/superpowers/specs/`: sono un archivio di decisioni, non documentazione viva.

- [ ] **Step 4: Eseguire tutta la suite un'ultima volta**

Run: `python -m pytest test/ -q && node --test test/js/`
Expected: verde su entrambi. Annotare il totale dei test.

- [ ] **Step 5: Commit**

```bash
git add -f docs/MANUAL_TESTS_AUDIO_LANGUAGE.md && git add version.py md_files/PARAMETRI_CONFIGURAZIONE.md
git commit -m "docs: collaudo manuale della lingua del libro, versione 3.49.0

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Jk6d9oqY4Sj4h2vvKzFjT3"
```

- [ ] **Step 6: Fermarsi**

**Nessun push.** Consegnare all'utente `docs/MANUAL_TESTS_AUDIO_LANGUAGE.md` e attendere che il collaudo sia fatto e confermato. Su questo progetto un push su `main` è già un deploy in produzione, senza gate di test.
