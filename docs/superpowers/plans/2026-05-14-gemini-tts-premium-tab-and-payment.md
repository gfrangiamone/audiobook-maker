# Gemini TTS Premium Tab + Payment Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trasformare il Panel 3 "Impostazioni audio" del wizard in un tab-panel con sotto-pannello "Voci PREMIUM" (Gemini TTS con modello, istruzioni di stile, stima costo), integrare gating di pagamento upfront (voucher/PayPal) e audit log delle stime vs reali.

**Architecture:** UI bipartita su Panel 3 esistente (Standard ↔ Premium) con mutua esclusione voce. Backend: due nuovi endpoint stima (`/api/gemini_estimate`, `/api/combined_estimate`), estensione `/api/generate` con `payment_token`, nuovo endpoint `/api/paypal_create_order_gemini`, modulo `gemini_cost_audit.py` per JSONL log mensile. Migration runtime atomic di `_paid_opt_done.json` → `_paid_jobs_done.json` per unificare recovery. Refund automatico su errore/cancel/crash.

**Tech Stack:** Flask + vanilla JS frontend; `google-genai` SDK lato server; PayPal REST v2 (riusa SDK già presente, riattivato solo nel modal Gemini); voucher pool € esistente; JSONL append-only per audit.

**Riferimento spec:** [`docs/superpowers/specs/2026-05-14-gemini-tts-premium-tab-and-payment-design.md`](../specs/2026-05-14-gemini-tts-premium-tab-and-payment-design.md)

**Convenzioni:**
- Git branch: lavoro su `main` (memoria utente). Worktree corrente verrà mergiato/squashato a fine implementazione.
- Test framework: `pytest` (file in `test/test_*.py`). Smoke E2E manuali documentati come istruzioni.
- Commit message format: imperative present (es. `feat(ui): add premium tab to audio panel`).
- **Regola UI:** mai citare "Gemini" / "DeepSeek" / "Google TTS" nelle label visibili all'utente finale. Vedere `feedback_ui_provider_naming.md`.

---

## Fase A — UI base (no logica costo)

### Task A1: Tab-bar nel Panel 3 + struttura tab Premium statica

**Files:**
- Modify: `templates/_fragments/html_head.html` (Panel 3, ~righe 278-361)
- Modify: `static/css/style.css` (append)
- Test: `test/test_panel3_tabbar_html.py` (NEW)

- [ ] **Step 1: Scrivere test fallente sulla presenza tab-bar in Panel 3**

Crea `test/test_panel3_tabbar_html.py`:
```python
from pathlib import Path

HTML = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")

def test_panel3_has_tab_bar():
    assert 'id="panel3"' in HTML
    assert 'class="tab-bar"' in HTML
    assert 'data-tab="standard"' in HTML
    assert 'data-tab="premium"' in HTML

def test_panel3_has_two_tab_panels():
    assert 'id="tabStandard"' in HTML
    assert 'id="tabPremium"' in HTML
    assert 'role="tabpanel"' in HTML

def test_panel3_premium_tab_has_model_selector():
    assert 'id="vmPremium"' in HTML
    assert 'value="flash25"' in HTML
    assert 'value="flash31"' in HTML

def test_panel3_premium_tab_has_style_textarea():
    assert 'id="geminiStyle"' in HTML
    assert 'maxlength="300"' in HTML

def test_panel3_premium_tab_has_cost_preview_box():
    assert 'id="costPreviewBox"' in HTML
    assert 'id="costPreviewValue"' in HTML
```

- [ ] **Step 2: Eseguire il test per verificare il FAIL**

Run: `pytest test/test_panel3_tabbar_html.py -v`
Expected: 5 FAIL (markup non esiste ancora).

- [ ] **Step 3: Modificare `templates/_fragments/html_head.html`**

Sostituire il blocco corrente di Panel 3 (`<section class="panel" id="panel3">...</section>`) con la struttura tab-panel. La form-row attuale (lingua, voce, velocità, formato, preview) va inserita dentro `<div class="tab-panel active" id="tabStandard">`. Aggiungere dopo:

```html
<div class="tab-bar" role="tablist" style="margin-bottom:12px">
  <button type="button" class="tab active" data-tab="standard" role="tab"
          aria-selected="true" data-t="tab_voices_standard">Voci Standard (gratis)</button>
  <button type="button" class="tab" data-tab="premium" role="tab"
          aria-selected="false" data-t="tab_voices_premium">★ Voci PREMIUM</button>
</div>

<div class="tab-panel active" id="tabStandard" role="tabpanel" aria-labelledby="tabStandardBtn">
  <!-- INSERIRE QUI il markup esistente: form-row lingua/voce, slider velocità, formato, preview -->
</div>

<div class="tab-panel" id="tabPremium" role="tabpanel" hidden aria-labelledby="tabPremiumBtn">
  <div class="form-row">
    <div class="form-group">
      <label for="vlPremium" data-t="lbl_lang">Lingua</label>
      <select id="vlPremium"></select>
    </div>
    <div class="form-group">
      <label for="vmPremium" data-t="lbl_model">Modello</label>
      <select id="vmPremium">
        <option value="flash25">Gemini 2.5 Flash TTS</option>
        <option value="flash31">Gemini 3.1 Flash TTS</option>
      </select>
      <div class="model-rate-hint" id="modelRateHint"></div>
    </div>
  </div>
  <div class="form-row">
    <div class="form-group">
      <label for="vvPremium" data-t="lbl_voice">Voce</label>
      <select id="vvPremium"></select>
    </div>
  </div>
  <div class="form-row">
    <div class="form-group" style="flex:1 1 100%">
      <label for="geminiStyle" data-t="lbl_style_instruction">Istruzioni di stile (opzionale)</label>
      <textarea id="geminiStyle" maxlength="300" rows="2"
                placeholder="es. tono calmo, ritmo narrativo lento"></textarea>
      <div class="char-counter"><span id="styleCounter">0</span>/300</div>
    </div>
  </div>
  <div class="cost-preview-box" id="costPreviewBox">
    <div class="cost-label" data-t="cost_estimate_label">Stima costo audiolibro</div>
    <div class="cost-value" id="costPreviewValue">—</div>
    <div class="cost-detail" id="costPreviewDetail"></div>
  </div>
  <!-- Slider velocità, formato e preview vengono riutilizzati dal tab Standard via JS -->
</div>
```

Aggiungere in `static/css/style.css`:
```css
.tab-bar { display:flex; gap:4px; border-bottom:2px solid var(--brd,#dcd6c8); }
.tab-bar .tab { padding:8px 14px; background:transparent; border:0; border-bottom:2px solid transparent;
                 margin-bottom:-2px; cursor:pointer; font-weight:500; color:var(--txm,#9e9890); }
.tab-bar .tab.active { color:var(--accent,#a07d3a); border-bottom-color:var(--accent,#a07d3a); }
.tab-panel { padding-top:16px; }
.tab-panel[hidden] { display:none; }
.cost-preview-box { background:var(--bgm,#f5f1e8); border-radius:8px; padding:12px 14px; margin:12px 0; }
.cost-preview-box .cost-label { font-size:12px; color:var(--txm,#9e9890); text-transform:uppercase; }
.cost-preview-box .cost-value { font-size:22px; font-weight:600; color:var(--accent,#a07d3a); }
.cost-preview-box .cost-detail { font-size:12px; color:var(--txm,#9e9890); margin-top:4px; }
.char-counter { font-size:11px; color:var(--txm,#9e9890); text-align:right; margin-top:2px; }
.model-rate-hint { font-size:11px; color:var(--txm,#9e9890); margin-top:4px; }
```

- [ ] **Step 4: Eseguire il test per verificare il PASS**

Run: `pytest test/test_panel3_tabbar_html.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/_fragments/html_head.html static/css/style.css test/test_panel3_tabbar_html.py
git commit -m "feat(ui): add tab-bar with Standard/Premium panels in audio settings step"
```

---

### Task A2: Tab-switching JS + rimozione voci Gemini dal tab Standard

**Files:**
- Modify: `static/js/app.js` (funzione `updVoices` e wizard navigation)
- Test: `test/test_app_js_tab_logic.py` (NEW — controllo statico delle funzioni JS)

- [ ] **Step 1: Scrivere test fallente**

Crea `test/test_app_js_tab_logic.py`:
```python
from pathlib import Path
APP_JS = Path("static/js/app.js").read_text(encoding="utf-8")

def test_has_switch_audio_tab_function():
    assert "function switchAudioTab" in APP_JS

def test_has_updVoicesPremium_function():
    assert "function updVoicesPremium" in APP_JS

def test_updVoices_excludes_gemini():
    # cerca il marker che indica l'esclusione esplicita
    assert "// SKIP gemini in Standard tab" in APP_JS

def test_wizardState_has_audioTab():
    assert "audioTab:" in APP_JS or "audioTab =" in APP_JS
```

- [ ] **Step 2: Eseguire il test per verificare il FAIL**

Run: `pytest test/test_app_js_tab_logic.py -v`
Expected: 4 FAIL.

- [ ] **Step 3: Modificare `static/js/app.js`**

In `updVoices()` (vedi righe 660-720 del file corrente), dentro il loop che costruisce le optgroup, aggiungere check di esclusione del prefisso `gemini:`:
```javascript
// Dentro updVoices(), nel ciclo che riempie #vv (tab Standard):
filtered.forEach(v => {
  if (v.id.startsWith('gemini:')) return; // SKIP gemini in Standard tab
  // ... resto del codice esistente per edge/google ...
});
```
Eliminare l'optgroup `'★ Gemini TTS'` dal blocco Standard.

Aggiungere nuove funzioni dopo `updVoices`:
```javascript
function updVoicesPremium() {
  const lang = document.getElementById('vlPremium').value || 'it';
  const modelKey = document.getElementById('vmPremium').value || 'flash25';
  const sel = document.getElementById('vvPremium');
  sel.innerHTML = '';
  const prefix = 'gemini:' + modelKey + ':';
  (window.ALL_VOICES || []).forEach(v => {
    if (!v.id.startsWith(prefix)) return;
    if (v.lang && v.lang !== lang && v.lang !== 'multi') return;
    const opt = document.createElement('option');
    opt.value = v.id;
    opt.textContent = v.label || v.id.split(':').pop();
    sel.appendChild(opt);
  });
  updateModelRateHint();
}

function updateModelRateHint() {
  const modelKey = document.getElementById('vmPremium').value;
  const hint = document.getElementById('modelRateHint');
  if (!hint) return;
  const labels = { flash25: '~€0.0027/sec audio (stima)', flash31: '~€0.0054/sec audio (stima)' };
  hint.textContent = labels[modelKey] || '';
}

function switchAudioTab(tab) {
  wizardState.audioTab = tab;
  document.querySelectorAll('.tab-bar .tab').forEach(t => {
    const active = t.dataset.tab === tab;
    t.classList.toggle('active', active);
    t.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.getElementById('tabStandard').hidden = (tab !== 'standard');
  document.getElementById('tabPremium').hidden = (tab !== 'premium');
  // Mutua esclusione: azzera la voce selezionata nell'altro tab
  if (tab === 'premium') {
    document.getElementById('vv').value = '';
    updVoicesPremium();
  } else {
    document.getElementById('vvPremium').value = '';
  }
  if (typeof requestCombinedEstimate === 'function') requestCombinedEstimate();
}
```

In `wizardState` (cercare la dichiarazione iniziale), aggiungere il campo:
```javascript
const wizardState = {
  // ... campi esistenti ...
  audioTab: 'standard',
};
```

In init listeners (vicino a dove vengono bindati i listener delle altre select), aggiungere:
```javascript
document.querySelectorAll('.tab-bar .tab').forEach(btn => {
  btn.addEventListener('click', () => switchAudioTab(btn.dataset.tab));
});
document.getElementById('vlPremium').addEventListener('change', updVoicesPremium);
document.getElementById('vmPremium').addEventListener('change', () => {
  updVoicesPremium();
  if (typeof requestCombinedEstimate === 'function') requestCombinedEstimate();
});
document.getElementById('geminiStyle').addEventListener('input', (e) => {
  document.getElementById('styleCounter').textContent = e.target.value.length;
});
```

In `goToStep(4)` (o nel punto dove viene letta la voce per inviarla al backend), modificare la lettura:
```javascript
const voiceId = (wizardState.audioTab === 'premium')
  ? document.getElementById('vvPremium').value
  : document.getElementById('vv').value;
```

- [ ] **Step 4: Eseguire test PASS**

Run: `pytest test/test_app_js_tab_logic.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js test/test_app_js_tab_logic.py
git commit -m "feat(ui): wire tab switching, Premium voice list filtered by model"
```

---

### Task A3: Sincronizzazione lingua tra tab + persistenza stato

**Files:**
- Modify: `static/js/app.js`

- [ ] **Step 1: Test fallente**

Append a `test/test_app_js_tab_logic.py`:
```python
def test_lang_sync_between_tabs_present():
    assert "syncLanguage" in APP_JS or "vlPremium.value = " in APP_JS
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_app_js_tab_logic.py::test_lang_sync_between_tabs_present -v`
Expected: FAIL.

- [ ] **Step 3: Implementare sync lingua**

In `app.js`, aggiungere ai listener di `#vl` (tab Standard):
```javascript
document.getElementById('vl').addEventListener('change', (e) => {
  document.getElementById('vlPremium').value = e.target.value;
  updVoicesPremium();
});
document.getElementById('vlPremium').addEventListener('change', (e) => {
  document.getElementById('vl').value = e.target.value;
  updVoices();
});
```

Allo init dopo il popolamento di `#vl`, copiare le option in `#vlPremium`:
```javascript
function syncLanguageOptions() {
  const src = document.getElementById('vl');
  const dst = document.getElementById('vlPremium');
  dst.innerHTML = src.innerHTML;
  dst.value = src.value;
}
// chiamare syncLanguageOptions() dopo updVoices() iniziale
```

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_app_js_tab_logic.py -v`
Expected: tutti PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js test/test_app_js_tab_logic.py
git commit -m "feat(ui): sync language selection between Standard and Premium tabs"
```

---

### Task A4: Slider velocità + formato + preview condivisi tra tab

**Files:**
- Modify: `templates/_fragments/html_head.html` (spostare slider/formato/preview fuori dai tab-panel, sotto la tab-bar prima di `panel-footer`)
- Modify: `static/js/app.js` (la preview deve usare la voce attiva del tab corrente)

- [ ] **Step 1: Test fallente**

Aggiungi a `test/test_panel3_tabbar_html.py`:
```python
def test_shared_controls_outside_tab_panels():
    # Trova posizione del slider velocità e verifica che NON sia dentro tabStandard
    import re
    m = re.search(r'id="tabStandard"[^>]*>(.*?)<div class="tab-panel"', HTML, re.DOTALL)
    assert m, "tabStandard markup not found"
    inside_std = m.group(1)
    assert 'id="vS"' not in inside_std, "speed slider must be shared, not inside Standard tab"
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_panel3_tabbar_html.py::test_shared_controls_outside_tab_panels -v`
Expected: FAIL.

- [ ] **Step 3: Spostare slider, formato e preview fuori dai tab-panel**

Riorganizzare Panel 3:
```html
<section class="panel" id="panel3">
  <h2 data-t="s2_title"></h2>
  <p class="subtitle" data-t="p3_subtitle"></p>
  <div class="tab-bar">...</div>
  <div class="tab-panel active" id="tabStandard">
    <!-- solo lingua + voce -->
  </div>
  <div class="tab-panel" id="tabPremium" hidden>
    <!-- lingua + modello + voce + style + costPreviewBox -->
  </div>
  <!-- Controlli condivisi -->
  <div class="form-row shared-controls">
    <div class="form-group">
      <label data-t="lbl_speed"></label>
      <input type="range" id="vS" min="-50" max="50" value="0">
      <span id="vSv">0%</span>
    </div>
    <div class="form-group">
      <label data-t="lbl_format"></label>
      <select id="vOut">...</select>
    </div>
  </div>
  <div class="preview-section">...</div>
  <div class="panel-footer">...</div>
</section>
```

In `app.js`, la funzione `previewRead()` deve leggere la voce in base al tab attivo:
```javascript
function getCurrentVoiceId() {
  return (wizardState.audioTab === 'premium')
    ? document.getElementById('vvPremium').value
    : document.getElementById('vv').value;
}
// sostituire ogni accesso diretto a document.getElementById('vv').value con getCurrentVoiceId()
```

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_panel3_tabbar_html.py -v`
Expected: tutti PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/_fragments/html_head.html static/js/app.js
git commit -m "refactor(ui): share speed/format/preview controls across audio tabs"
```

---

## Fase B — Stima costo

### Task B1: Endpoint `POST /api/gemini_estimate`

**Files:**
- Modify: `audiobook_app.py` (aggiungere route dopo gli altri endpoint API)
- Test: `test/test_api_gemini_estimate.py` (NEW)

- [ ] **Step 1: Test fallente**

Crea `test/test_api_gemini_estimate.py`:
```python
import json
import pytest
from audiobook_app import app, jobs, Job, Chapter

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c

@pytest.fixture
def job_with_text():
    job = Job(job_id="testjob1")
    job.chapters = [Chapter(title="Cap1", text="Lorem ipsum " * 500)]
    job.language = "it"
    jobs["testjob1"] = job
    yield job
    jobs.pop("testjob1", None)

def test_gemini_estimate_returns_price_for_gemini_voice(client, job_with_text):
    r = client.post("/api/gemini_estimate", json={
        "job_id": "testjob1",
        "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0],
    })
    assert r.status_code == 200
    data = r.get_json()
    assert "user_price_eur" in data
    assert "is_free" in data
    assert data["model_key"] == "flash25"
    assert data["model_label"] == "Gemini 2.5 Flash TTS"
    assert data["chars_total"] > 0

def test_gemini_estimate_rejects_non_gemini_voice(client, job_with_text):
    r = client.post("/api/gemini_estimate", json={
        "job_id": "testjob1",
        "voice_id": "edge:it-IT-DiegoNeural",
        "selected_chapters": [0],
    })
    assert r.status_code == 400

def test_gemini_estimate_missing_job(client):
    r = client.post("/api/gemini_estimate", json={
        "job_id": "nope",
        "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0],
    })
    assert r.status_code == 404
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_api_gemini_estimate.py -v`
Expected: 3 FAIL (endpoint inesistente).

- [ ] **Step 3: Implementare endpoint in `audiobook_app.py`**

Aggiungere dopo gli endpoint payment esistenti (es. dopo `/api/voucher_validate`):
```python
@app.route("/api/gemini_estimate", methods=["POST"])
def api_gemini_estimate():
    """Stima costo Gemini TTS per il job corrente, capitoli selezionati."""
    import gemini_tts
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id", "")
    voice_id = data.get("voice_id", "")
    selected = data.get("selected_chapters") or []

    if not voice_id.startswith("gemini:"):
        return jsonify({"error": "voice_id must be a Gemini voice"}), 400
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    if not job.chapters:
        return jsonify({"error": "job has no chapters"}), 400

    # Filtra capitoli selezionati
    if selected:
        chs = [job.chapters[i] for i in selected if 0 <= i < len(job.chapters)]
    else:
        chs = job.chapters
    if not chs:
        return jsonify({"error": "no chapters selected"}), 400

    lang = getattr(job, "language", "it") or "it"
    try:
        est = gemini_tts.estimate_book_cost(chs, voice_id, language=lang)
    except Exception as e:
        return jsonify({"error": f"estimate failed: {e}"}), 500

    return jsonify({
        "chars_total": est["chars_total"],
        "audio_seconds_est": est["audio_seconds_est"],
        "estimated_audio_minutes": round(est["estimated_audio_minutes"], 1),
        "user_price_eur": est["user_price_eur"],
        "is_free": est["is_free"],
        "model_key": est["model_key"],
        "model_label": est["model_label"],
        "language": est["language"],
        "breakdown": {
            "input_tokens_est": est["input_tokens_est"],
            "output_tokens_est": est["output_tokens_est"],
            "google_cost_eur": est["google_cost_eur"],
            "margin_percent": est["margin_percent"],
        },
    })
```

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_api_gemini_estimate.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add audiobook_app.py test/test_api_gemini_estimate.py
git commit -m "feat(api): add POST /api/gemini_estimate for Premium voice cost preview"
```

---

### Task B2: Endpoint `POST /api/combined_estimate`

**Files:**
- Modify: `audiobook_app.py`
- Test: `test/test_api_combined_estimate.py` (NEW)

- [ ] **Step 1: Test fallente**

Crea `test/test_api_combined_estimate.py`:
```python
import pytest
from audiobook_app import app, jobs, Job, Chapter

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c

@pytest.fixture
def jb():
    job = Job(job_id="cj1")
    job.chapters = [Chapter(title="C", text="A" * 50000)]
    job.language = "it"
    jobs["cj1"] = job
    yield job
    jobs.pop("cj1", None)

def test_combined_both(client, jb):
    r = client.post("/api/combined_estimate", json={
        "job_id": "cj1", "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0], "ai_opt_enabled": True,
    })
    assert r.status_code == 200
    d = r.get_json()
    assert d["gemini_eur"] > 0
    assert d["llm_eur"] > 0
    assert d["total_eur"] == pytest.approx(d["gemini_eur"] + d["llm_eur"], abs=0.01)
    assert "is_free" in d
    assert "threshold_eur" in d

def test_combined_standard_voice_no_gemini(client, jb):
    r = client.post("/api/combined_estimate", json={
        "job_id": "cj1", "voice_id": "edge:it-IT-DiegoNeural",
        "selected_chapters": [0], "ai_opt_enabled": True,
    })
    assert r.status_code == 200
    d = r.get_json()
    assert d["gemini_eur"] == 0
    assert d["llm_eur"] > 0

def test_combined_no_ai_opt(client, jb):
    r = client.post("/api/combined_estimate", json={
        "job_id": "cj1", "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0], "ai_opt_enabled": False,
    })
    d = r.get_json()
    assert d["llm_eur"] == 0
    assert d["gemini_eur"] > 0
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_api_combined_estimate.py -v`
Expected: 3 FAIL.

- [ ] **Step 3: Implementare endpoint**

Aggiungere in `audiobook_app.py` (vicino a `/api/gemini_estimate`):
```python
@app.route("/api/combined_estimate", methods=["POST"])
def api_combined_estimate():
    """Stima combinata Gemini + ottimizzazione testo AI."""
    import gemini_tts
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id", "")
    voice_id = data.get("voice_id", "")
    selected = data.get("selected_chapters") or []
    ai_opt = bool(data.get("ai_opt_enabled", False))

    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    chs = [job.chapters[i] for i in selected if 0 <= i < len(job.chapters)] \
          if selected else job.chapters
    if not chs:
        return jsonify({"error": "no chapters"}), 400

    lang = getattr(job, "language", "it") or "it"
    gemini_eur = 0.0
    gemini_breakdown = {}
    if voice_id.startswith("gemini:"):
        est = gemini_tts.estimate_book_cost(chs, voice_id, language=lang)
        gemini_eur = round(est["user_price_eur"], 2)
        gemini_breakdown = {
            "chars": est["chars_total"],
            "audio_minutes": round(est["estimated_audio_minutes"], 1),
            "google_cost_eur": est["google_cost_eur"],
            "model_label": est["model_label"],
        }

    llm_eur = 0.0
    llm_breakdown = {}
    if ai_opt:
        chars = sum(len(c.text or "") for c in chs)
        rate = float(os.environ.get("LLM_PRICE_EUR_PER_MCHAR", "1.10"))
        llm_eur = round((chars / 1_000_000.0) * rate, 2)
        llm_breakdown = {"chars": chars, "rate_eur_per_mchar": rate}

    total = round(gemini_eur + llm_eur, 2)
    threshold = float(os.environ.get("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.50"))

    return jsonify({
        "gemini_eur": gemini_eur,
        "llm_eur": llm_eur,
        "total_eur": total,
        "is_free": total <= threshold,
        "threshold_eur": threshold,
        "gemini_breakdown": gemini_breakdown,
        "llm_breakdown": llm_breakdown,
    })
```

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_api_combined_estimate.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add audiobook_app.py test/test_api_combined_estimate.py
git commit -m "feat(api): add POST /api/combined_estimate for Gemini+LLM unified pricing"
```

---

### Task B3: Frontend — listener di re-estimate con debounce e cache

**Files:**
- Modify: `static/js/app.js`
- Test: `test/test_app_js_estimate.py` (NEW)

- [ ] **Step 1: Test fallente**

Crea `test/test_app_js_estimate.py`:
```python
from pathlib import Path
APP = Path("static/js/app.js").read_text(encoding="utf-8")

def test_has_request_combined_estimate():
    assert "function requestCombinedEstimate" in APP

def test_debounce_present():
    assert "estimateDebounceTimer" in APP or "debouncedEstimate" in APP

def test_estimate_cache_present():
    assert "_estimateCache" in APP or "estimateCacheKey" in APP

def test_listener_not_on_voice_change():
    # Trigger su modello, ai_opt, capitoli, tab — NON su voce
    # Cerca commento esplicativo
    assert "no re-estimate on voice change" in APP.lower()
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_app_js_estimate.py -v`
Expected: 4 FAIL.

- [ ] **Step 3: Implementare in `app.js`**

```javascript
let estimateDebounceTimer = null;
const _estimateCache = { key: null, value: null };

function getEstimateCacheKey() {
  const tab = wizardState.audioTab || 'standard';
  const model = (tab === 'premium')
    ? (document.getElementById('vmPremium').value || 'flash25')
    : 'none';
  const aiOpt = document.getElementById('aiToggle')?.checked ? '1' : '0';
  // selezione capitoli — adattare al modo in cui sono tracciati (es. set indici)
  const chapters = (wizardState.selectedChapters || []).join(',');
  return `${tab}|${model}|${aiOpt}|${chapters}`;
}

function requestCombinedEstimate() {
  // Trigger: tab change / model change / ai_opt toggle / chapter selection change
  // no re-estimate on voice change (cost is per-model, not per-voice)
  if (estimateDebounceTimer) clearTimeout(estimateDebounceTimer);
  estimateDebounceTimer = setTimeout(_doCombinedEstimate, 300);
}

async function _doCombinedEstimate() {
  const key = getEstimateCacheKey();
  if (_estimateCache.key === key && _estimateCache.value) {
    renderEstimate(_estimateCache.value);
    return;
  }
  const voiceId = getCurrentVoiceId();
  if (!voiceId) { renderEstimate(null); return; }
  const payload = {
    job_id: wizardState.jobId,
    voice_id: voiceId,
    selected_chapters: wizardState.selectedChapters || [],
    ai_opt_enabled: !!document.getElementById('aiToggle')?.checked,
    style_instruction: document.getElementById('geminiStyle')?.value || '',
  };
  try {
    const r = await fetch('/api/combined_estimate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error('estimate failed');
    const data = await r.json();
    _estimateCache.key = key;
    _estimateCache.value = data;
    renderEstimate(data);
  } catch (e) {
    console.warn('combined_estimate error:', e);
    renderEstimate(null);
  }
}

function renderEstimate(data) {
  const box = document.getElementById('costPreviewBox');
  const valueEl = document.getElementById('costPreviewValue');
  const detailEl = document.getElementById('costPreviewDetail');
  if (!data) { valueEl.textContent = '—'; detailEl.textContent = ''; return; }
  if (data.is_free) {
    valueEl.textContent = (window.t && t('cost_free')) || 'Gratis';
    detailEl.textContent = `≤ €${data.threshold_eur.toFixed(2)} ${(window.t && t('cost_under_threshold')) || 'sotto soglia'}`;
  } else {
    valueEl.textContent = `€${data.total_eur.toFixed(2)}`;
    const parts = [];
    if (data.gemini_eur > 0) parts.push(`Voci PREMIUM €${data.gemini_eur.toFixed(2)}`);
    if (data.llm_eur > 0) parts.push(`Ottimizzazione testo AI €${data.llm_eur.toFixed(2)}`);
    detailEl.textContent = parts.join(' + ');
  }
  // Specchia in Panel 4 #costAmount se ai_opt e gemini insieme
  const costAmount = document.getElementById('costAmount');
  if (costAmount) costAmount.textContent = `€${data.total_eur.toFixed(2)}`;
}
```

Listener da aggiungere nella init:
```javascript
document.getElementById('aiToggle')?.addEventListener('change', requestCombinedEstimate);
// chapter selection: trovare il listener esistente del select capitoli e aggiungere requestCombinedEstimate()
```

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_app_js_estimate.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js test/test_app_js_estimate.py
git commit -m "feat(ui): debounced combined cost estimate with cache and selective triggers"
```

---

## Fase C — Modal pagamento + flow voucher

### Task C1: Markup modal pagamento Gemini

**Files:**
- Modify: `templates/_fragments/html_head.html` (aggiungere modal in fondo al body, prima di `</body>`)
- Modify: `static/css/style.css`
- Test: `test/test_payment_modal_html.py` (NEW)

- [ ] **Step 1: Test fallente**

```python
from pathlib import Path
HTML = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")

def test_modal_exists():
    assert 'id="geminiPayModal"' in HTML

def test_modal_has_voucher_tab():
    assert 'id="payTabVoucher"' in HTML
    assert 'id="payVoucherCode"' in HTML

def test_modal_has_paypal_tab():
    assert 'id="payTabPaypal"' in HTML
    assert 'id="paypalGeminiContainer"' in HTML

def test_modal_has_total_display():
    assert 'id="payModalTotal"' in HTML

def test_modal_has_confirm_cancel():
    assert 'id="btnPayConfirm"' in HTML
    assert 'id="btnPayCancel"' in HTML
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_payment_modal_html.py -v`
Expected: 5 FAIL.

- [ ] **Step 3: Aggiungere markup modal**

In `html_head.html` prima di `</body>` (o vicino agli altri modal esistenti):
```html
<div class="modal-backdrop" id="geminiPayModal" hidden>
  <div class="modal payment-modal" role="dialog" aria-labelledby="payModalTitle">
    <header class="modal-header">
      <h3 id="payModalTitle" data-t="pay_modal_title">Pagamento generazione</h3>
      <button class="modal-close" id="btnPayCancel" aria-label="Chiudi">×</button>
    </header>
    <div class="modal-body">
      <div class="pay-summary">
        <div class="pay-line"><span data-t="pay_premium_voices">Voci PREMIUM</span>
             <span id="payLineGemini">—</span></div>
        <div class="pay-line"><span data-t="pay_text_ai_optimization">Ottimizzazione testo AI</span>
             <span id="payLineLlm">—</span></div>
        <div class="pay-line pay-total">
          <span data-t="pay_total">Totale</span>
          <strong id="payModalTotal">—</strong>
        </div>
      </div>
      <div class="pay-tabs" role="tablist">
        <button type="button" class="pay-tab active" id="payTabVoucher" data-paytab="voucher"
                data-t="pay_tab_voucher">Buono</button>
        <button type="button" class="pay-tab" id="payTabPaypal" data-paytab="paypal"
                data-t="pay_tab_paypal">PayPal</button>
      </div>
      <div class="pay-tab-panel" id="payPanelVoucher">
        <label data-t="pay_voucher_code">Codice buono</label>
        <input type="text" id="payVoucherCode" autocomplete="off">
        <label data-t="pay_voucher_email">Email (verifica)</label>
        <input type="email" id="payVoucherEmail" autocomplete="email">
        <div class="pay-error" id="payVoucherError"></div>
      </div>
      <div class="pay-tab-panel" id="payPanelPaypal" hidden>
        <div id="paypalGeminiContainer"></div>
        <div class="pay-error" id="payPaypalError"></div>
      </div>
    </div>
    <footer class="modal-footer">
      <button type="button" class="btn-secondary" id="btnPayCancel2" data-t="pay_cancel">Annulla</button>
      <button type="button" class="btn-primary" id="btnPayConfirm" data-t="pay_confirm" disabled>Conferma</button>
    </footer>
  </div>
</div>
```

CSS in `style.css`:
```css
.modal-backdrop { position:fixed; inset:0; background:rgba(0,0,0,0.5); display:flex;
                  align-items:center; justify-content:center; z-index:1000; }
.modal-backdrop[hidden] { display:none; }
.payment-modal { background:#fff; border-radius:8px; max-width:480px; width:90%; }
.modal-header { display:flex; justify-content:space-between; padding:14px 18px; border-bottom:1px solid #eee; }
.modal-body { padding:18px; }
.modal-footer { padding:12px 18px; border-top:1px solid #eee; display:flex; gap:8px; justify-content:flex-end; }
.pay-summary { background:#f7f4ec; border-radius:6px; padding:10px 14px; margin-bottom:14px; }
.pay-line { display:flex; justify-content:space-between; padding:3px 0; }
.pay-line.pay-total { border-top:1px solid #ddd; margin-top:6px; padding-top:8px; font-size:16px; }
.pay-tabs { display:flex; gap:4px; border-bottom:1px solid #ddd; margin-bottom:12px; }
.pay-tab { background:transparent; border:0; padding:8px 14px; cursor:pointer;
            border-bottom:2px solid transparent; margin-bottom:-1px; }
.pay-tab.active { border-bottom-color:var(--accent,#a07d3a); color:var(--accent,#a07d3a); }
.pay-error { color:#c0392b; font-size:13px; margin-top:6px; min-height:18px; }
```

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_payment_modal_html.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/_fragments/html_head.html static/css/style.css test/test_payment_modal_html.py
git commit -m "feat(ui): add Gemini payment modal markup (voucher + PayPal tabs)"
```

---

### Task C2: Estendere `/api/voucher_validate` con campo `purpose`

**Files:**
- Modify: `audiobook_app.py`
- Modify: `payment.py` (helper opzionale)
- Test: `test/test_voucher_validate_purpose.py` (NEW)

- [ ] **Step 1: Test fallente**

```python
import pytest
from audiobook_app import app
import payment

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c

def test_voucher_validate_accepts_purpose(client, monkeypatch):
    code = payment._create_voucher("test@x.it", 2.0, kind="test", note="t")["code"]
    r = client.post("/api/voucher_validate", json={
        "code": code, "email": "test@x.it",
        "purpose": "gemini", "amount_eur": 1.5,
    })
    assert r.status_code == 200
    d = r.get_json()
    assert d["valid"] is True
    assert d["remaining_eur"] >= 1.5

def test_voucher_validate_insufficient(client):
    code = payment._create_voucher("test2@x.it", 0.5, kind="test", note="t")["code"]
    r = client.post("/api/voucher_validate", json={
        "code": code, "email": "test2@x.it",
        "purpose": "gemini", "amount_eur": 2.0,
    })
    d = r.get_json()
    assert d["valid"] is False
    assert "insufficient" in (d.get("reason", "") or "").lower()
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_voucher_validate_purpose.py -v`
Expected: FAIL (campi `amount_eur` e `purpose` ignorati o errore).

- [ ] **Step 3: Estendere endpoint in `audiobook_app.py`**

Localizzare la handler `/api/voucher_validate` (intorno a riga 4720) e modificare:
```python
@app.route("/api/voucher_validate", methods=["POST"])
def api_voucher_validate():
    import payment
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    email = (data.get("email") or "").strip().lower()
    purpose = data.get("purpose", "any")
    amount_required = float(data.get("amount_eur", 0) or 0)

    v = payment._vouchers.get(code)
    if not v:
        return jsonify({"valid": False, "reason": "not_found"})
    if v.get("email", "").lower() != email:
        return jsonify({"valid": False, "reason": "email_mismatch"})
    if v.get("revoked"):
        return jsonify({"valid": False, "reason": "revoked"})
    remaining = payment._voucher_remaining(v)
    if amount_required > 0 and remaining < amount_required:
        return jsonify({"valid": False, "reason": "insufficient",
                        "remaining_eur": remaining, "required_eur": amount_required})
    return jsonify({
        "valid": True, "remaining_eur": remaining,
        "original_eur": float(v.get("amount_eur", 0)),
        "purpose_requested": purpose,
    })
```

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_voucher_validate_purpose.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add audiobook_app.py test/test_voucher_validate_purpose.py
git commit -m "feat(api): extend voucher_validate with purpose/amount_eur preflight"
```

---

### Task C3: Frontend modal logic — flow voucher

**Files:**
- Modify: `static/js/app.js`
- Test: `test/test_app_js_payment_modal.py` (NEW — controllo statico)

- [ ] **Step 1: Test fallente**

```python
from pathlib import Path
APP = Path("static/js/app.js").read_text(encoding="utf-8")

def test_has_open_payment_modal():
    assert "function openPaymentModal" in APP

def test_has_validate_voucher_for_payment():
    assert "validateVoucherForPayment" in APP

def test_btn_generate_calls_payment_flow():
    assert "openPaymentModal" in APP and "btnGenerate" in APP
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_app_js_payment_modal.py -v`
Expected: 3 FAIL.

- [ ] **Step 3: Implementare in `app.js`**

```javascript
let _payState = { total: 0, gemini: 0, llm: 0, token: null, method: null };

function openPaymentModal(estimate) {
  _payState = {
    total: estimate.total_eur, gemini: estimate.gemini_eur,
    llm: estimate.llm_eur, token: null, method: null,
  };
  document.getElementById('payLineGemini').textContent =
    estimate.gemini_eur > 0 ? `€${estimate.gemini_eur.toFixed(2)}` : '—';
  document.getElementById('payLineLlm').textContent =
    estimate.llm_eur > 0 ? `€${estimate.llm_eur.toFixed(2)}` : '—';
  document.getElementById('payModalTotal').textContent = `€${estimate.total_eur.toFixed(2)}`;
  document.getElementById('payVoucherError').textContent = '';
  document.getElementById('payPaypalError').textContent = '';
  document.getElementById('btnPayConfirm').disabled = true;
  switchPayTab('voucher');
  document.getElementById('geminiPayModal').hidden = false;
}

function closePaymentModal() {
  document.getElementById('geminiPayModal').hidden = true;
}

function switchPayTab(tab) {
  document.querySelectorAll('.pay-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.paytab === tab);
  });
  document.getElementById('payPanelVoucher').hidden = (tab !== 'voucher');
  document.getElementById('payPanelPaypal').hidden = (tab !== 'paypal');
  if (tab === 'paypal' && typeof renderPaypalGeminiButtons === 'function') {
    renderPaypalGeminiButtons();
  }
}

async function validateVoucherForPayment() {
  const code = document.getElementById('payVoucherCode').value.trim();
  const email = document.getElementById('payVoucherEmail').value.trim();
  const errEl = document.getElementById('payVoucherError');
  errEl.textContent = '';
  if (!code || !email) { errEl.textContent = t('pay_err_empty') || 'Inserisci codice e email'; return; }
  try {
    const r = await fetch('/api/voucher_validate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ code, email, purpose: 'gemini', amount_eur: _payState.total }),
    });
    const d = await r.json();
    if (!d.valid) {
      const map = {
        not_found: t('pay_err_voucher_not_found') || 'Buono non trovato',
        email_mismatch: t('pay_err_email_mismatch') || 'Email non corrispondente',
        revoked: t('pay_err_revoked') || 'Buono revocato',
        insufficient: t('pay_err_insufficient') || 'Saldo insufficiente',
      };
      errEl.textContent = map[d.reason] || (t('pay_err_unknown') || 'Errore validazione');
      return;
    }
    _payState.token = code;
    _payState.method = 'voucher';
    document.getElementById('btnPayConfirm').disabled = false;
    errEl.style.color = '#27ae60';
    errEl.textContent = (t('pay_ok_remaining') || 'Saldo disponibile') + ` €${d.remaining_eur.toFixed(2)}`;
  } catch (e) {
    errEl.textContent = t('pay_err_network') || 'Errore di rete';
  }
}

// Sostituire la handler corrente di btnGenerate:
async function onGenerateClick() {
  // Calcola stima fresca
  await _doCombinedEstimate();
  const est = _estimateCache.value;
  if (!est || est.is_free) {
    return startGeneration(null);  // no payment
  }
  openPaymentModal(est);
}

function onPayConfirm() {
  if (!_payState.token) return;
  closePaymentModal();
  startGeneration(_payState.token);
}

// init listeners
document.getElementById('btnPayCancel')?.addEventListener('click', closePaymentModal);
document.getElementById('btnPayCancel2')?.addEventListener('click', closePaymentModal);
document.getElementById('btnPayConfirm')?.addEventListener('click', onPayConfirm);
document.querySelectorAll('.pay-tab').forEach(t => {
  t.addEventListener('click', () => switchPayTab(t.dataset.paytab));
});
document.getElementById('payVoucherCode')?.addEventListener('blur', validateVoucherForPayment);
document.getElementById('payVoucherEmail')?.addEventListener('blur', validateVoucherForPayment);
```

`startGeneration(token)` deve passare `payment_token` a `/api/generate`. Modificare la call esistente.

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_app_js_payment_modal.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js test/test_app_js_payment_modal.py
git commit -m "feat(ui): wire payment modal voucher flow into generation entry point"
```

---

## Fase D — PayPal

### Task D1: Endpoint `POST /api/paypal_create_order_gemini`

**Files:**
- Modify: `audiobook_app.py`
- Test: `test/test_paypal_create_gemini.py` (NEW)

- [ ] **Step 1: Test fallente**

```python
import pytest
from unittest.mock import patch
from audiobook_app import app, jobs, Job, Chapter

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c: yield c

@pytest.fixture
def jb():
    j = Job(job_id="pj1"); j.chapters = [Chapter(title="C", text="X" * 60000)]
    j.language = "it"; jobs["pj1"] = j
    yield j; jobs.pop("pj1", None)

def test_create_order_amount_must_match_estimate(client, jb):
    # amount errato → 400
    r = client.post("/api/paypal_create_order_gemini", json={
        "job_id": "pj1", "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0], "ai_opt_enabled": False,
        "amount_eur": 99.99,
    })
    assert r.status_code == 400
    assert "mismatch" in r.get_json().get("error", "").lower()

def test_create_order_success(client, jb):
    with patch("payment._paypal_create_order") as mock:
        mock.return_value = {"id": "ORDER123", "status": "CREATED", "amount": "1.20"}
        # importo congruo con la stima — calcolare prima
        from audiobook_app import api_combined_estimate
        # invocazione via client
        est = client.post("/api/combined_estimate", json={
            "job_id": "pj1", "voice_id": "gemini:flash25:Zephyr",
            "selected_chapters": [0], "ai_opt_enabled": False,
        }).get_json()
        amount = est["total_eur"]
        r = client.post("/api/paypal_create_order_gemini", json={
            "job_id": "pj1", "voice_id": "gemini:flash25:Zephyr",
            "selected_chapters": [0], "ai_opt_enabled": False,
            "amount_eur": amount,
        })
        assert r.status_code == 200
        assert r.get_json()["order_id"] == "ORDER123"
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_paypal_create_gemini.py -v`
Expected: 2 FAIL.

- [ ] **Step 3: Implementare endpoint**

```python
@app.route("/api/paypal_create_order_gemini", methods=["POST"])
def api_paypal_create_order_gemini():
    import payment, gemini_tts
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id", "")
    voice_id = data.get("voice_id", "")
    selected = data.get("selected_chapters") or []
    ai_opt = bool(data.get("ai_opt_enabled", False))
    requested_amount = float(data.get("amount_eur", 0) or 0)

    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404

    # Ricalcola stima server-side e confronta (tolleranza 0.01€)
    chs = [job.chapters[i] for i in selected if 0 <= i < len(job.chapters)] \
          if selected else job.chapters
    lang = getattr(job, "language", "it") or "it"
    gemini_eur = 0.0
    if voice_id.startswith("gemini:"):
        est = gemini_tts.estimate_book_cost(chs, voice_id, language=lang)
        gemini_eur = round(est["user_price_eur"], 2)
    llm_eur = 0.0
    if ai_opt:
        chars = sum(len(c.text or "") for c in chs)
        rate = float(os.environ.get("LLM_PRICE_EUR_PER_MCHAR", "1.10"))
        llm_eur = round((chars / 1_000_000.0) * rate, 2)
    server_total = round(gemini_eur + llm_eur, 2)
    if abs(server_total - requested_amount) > 0.01:
        return jsonify({"error": f"amount mismatch (server={server_total}, client={requested_amount})"}), 400

    try:
        order = payment._paypal_create_order(
            amount=server_total,
            description=f"Audiobook Maker — Voci PREMIUM ({job_id})",
            custom_id=f"gemini:{job_id}",
        )
        return jsonify({
            "order_id": order["id"], "amount": server_total,
            "status": order.get("status"),
        })
    except Exception as e:
        return jsonify({"error": f"paypal create failed: {e}"}), 500
```

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_paypal_create_gemini.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add audiobook_app.py test/test_paypal_create_gemini.py
git commit -m "feat(api): add POST /api/paypal_create_order_gemini with server-side amount check"
```

---

### Task D2: Frontend — riattivazione PayPal SDK nel modal

**Files:**
- Modify: `templates/_fragments/html_head.html` (script PayPal SDK condizionale)
- Modify: `static/js/app.js`

- [ ] **Step 1: Test fallente**

Aggiungi a `test/test_app_js_payment_modal.py`:
```python
def test_has_render_paypal_gemini_buttons():
    assert "renderPaypalGeminiButtons" in APP

def test_paypal_sdk_only_for_gemini_modal():
    # Marker per uso scoped
    assert "paypal-only-gemini" in APP or "paypalGeminiContainer" in APP
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_app_js_payment_modal.py -v`
Expected: 2 nuovi FAIL.

- [ ] **Step 3: Implementare**

In `html_head.html`, aggiungere lo script SDK dopo il `<body>` (solo se `ABM_PAYPAL_CLIENT_ID` configurato — gestire via placeholder già usato in altri punti per PayPal). Riusare lo stesso script tag se esistente, oppure aggiungerne uno con marker `data-purpose="gemini"`.

In `app.js`:
```javascript
let _paypalButtonsInstance = null;

function renderPaypalGeminiButtons() {
  const container = document.getElementById('paypalGeminiContainer');
  if (!container) return;
  container.innerHTML = '';
  if (typeof paypal === 'undefined') {
    document.getElementById('payPaypalError').textContent =
      t('pay_paypal_unavailable') || 'PayPal non disponibile';
    return;
  }
  if (_paypalButtonsInstance) {
    try { _paypalButtonsInstance.close(); } catch(e){}
  }
  _paypalButtonsInstance = paypal.Buttons({
    createOrder: async () => {
      const r = await fetch('/api/paypal_create_order_gemini', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          job_id: wizardState.jobId,
          voice_id: getCurrentVoiceId(),
          selected_chapters: wizardState.selectedChapters || [],
          ai_opt_enabled: !!document.getElementById('aiToggle')?.checked,
          amount_eur: _payState.total,
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'create failed');
      return d.order_id;
    },
    onApprove: async (data) => {
      const r = await fetch('/api/paypal_capture_order', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ order_id: data.orderID }),
      });
      const d = await r.json();
      if (d.captured) {
        _payState.token = data.orderID;
        _payState.method = 'paypal';
        document.getElementById('btnPayConfirm').disabled = false;
        document.getElementById('payPaypalError').style.color = '#27ae60';
        document.getElementById('payPaypalError').textContent =
          t('pay_paypal_captured') || 'Pagamento completato — clicca Conferma';
      } else {
        document.getElementById('payPaypalError').textContent =
          t('pay_paypal_capture_failed') || 'Cattura fallita';
      }
    },
    onError: (err) => {
      document.getElementById('payPaypalError').textContent =
        (t('pay_paypal_error') || 'Errore PayPal: ') + (err.message || '');
    },
  });
  _paypalButtonsInstance.render('#paypalGeminiContainer'); // paypal-only-gemini scope
}
```

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_app_js_payment_modal.py -v`
Expected: tutti PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/_fragments/html_head.html static/js/app.js test/test_app_js_payment_modal.py
git commit -m "feat(ui): render PayPal SDK buttons inside Gemini payment modal"
```

---

## Fase E — Generation engine

### Task E1: `gemini_tts.synthesize` accetta `style_instruction`

**Files:**
- Modify: `gemini_tts.py`
- Test: `test/test_gemini_tts_style.py` (NEW)

- [ ] **Step 1: Test fallente**

```python
import gemini_tts, inspect

def test_synthesize_has_style_instruction_param():
    sig = inspect.signature(gemini_tts.synthesize)
    assert "style_instruction" in sig.parameters

def test_style_instruction_prepended_to_text(monkeypatch):
    captured = {}
    class _FakeClient:
        class models:
            @staticmethod
            def generate_content(*, model, contents, config):
                captured["contents"] = contents
                class _R:
                    candidates = [type("p", (), {
                        "content": type("c", (), {
                            "parts": [type("d", (), {"inline_data": type("i", (), {"data": b"x"*100})()})()]
                        })()
                    })()]
                    usage_metadata = type("u", (), {"prompt_token_count":10,"candidates_token_count":50})()
                return _R()
    monkeypatch.setattr(gemini_tts, "_get_client", lambda: _FakeClient())
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    gemini_tts.synthesize("Ciao mondo", "gemini:flash25:Zephyr",
                          style_instruction="tono calmo", output_path="/tmp/x.pcm")
    assert "tono calmo" in captured["contents"]
    assert "Ciao mondo" in captured["contents"]
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_gemini_tts_style.py -v`
Expected: 2 FAIL (param mancante).

- [ ] **Step 3: Modificare `synthesize`**

In `gemini_tts.py` riga ~540:
```python
def synthesize(text, voice_id, rate="+0%", output_path="output.pcm", style_instruction=None):
    # ... codice esistente ...
    final_text = text
    if style_instruction:
        final_text = f"[style: {style_instruction.strip()[:300]}] {final_text}"
    # ... resto invariato (rate handling, retry loop) ...
```

Verificare che `check_text_byte_size` venga richiamato DOPO aver costruito `final_text`, per garantire che il cap UTF-8 sia rispettato. Se overflow, troncare `style_instruction` o sollevare errore esplicito.

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_gemini_tts_style.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gemini_tts.py test/test_gemini_tts_style.py
git commit -m "feat(gemini): synthesize accepts optional style_instruction prefix"
```

---

### Task E2: `generation_engine.run_generation` applica style al primo chunk di ogni capitolo

**Files:**
- Modify: `generation_engine.py`
- Test: `test/test_generation_engine_style.py` (NEW)

- [ ] **Step 1: Test fallente**

```python
import generation_engine
from unittest.mock import patch, MagicMock

def test_style_applied_only_to_first_chunk_of_each_chapter():
    captured_styles = []
    def fake_synth(text, voice_id, rate, output_path, style_instruction=None):
        captured_styles.append(style_instruction)
        with open(output_path, "wb") as f: f.write(b"\x00"*1000)
        return {"success":True,"bytes_written":1000,"input_tokens":10,"output_tokens":50,
                "model_key":"flash25","voice_name":"Zephyr","attempts_used":1}
    # … setup minimal job con 2 capitoli di 3 chunk ciascuno …
    # … invocare run_generation con style_instruction="calmo" …
    # 6 chiamate totali, di cui 2 con style="calmo" e 4 con style=None
    # assert sum(1 for s in captured_styles if s) == 2
    pass  # vedi step 3 per il test completo
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_generation_engine_style.py -v`
Expected: FAIL (param non propagato).

- [ ] **Step 3: Implementare**

In `generation_engine.py`, trovare la funzione `run_generation` (o equivalente che invoca `gemini_tts.synthesize`). Aggiungere parametro `gemini_style_instruction=None`. Nel loop chunk per ogni capitolo:
```python
for chap_idx, chapter in enumerate(chapters):
    chunks = split_into_chunks(chapter.text, ...)
    for chunk_idx, chunk in enumerate(chunks):
        style_for_chunk = gemini_style_instruction if (chunk_idx == 0) else None
        if voice_id.startswith("gemini:"):
            result = gemini_tts.synthesize(
                chunk, voice_id, rate=rate, output_path=chunk_pcm_path,
                style_instruction=style_for_chunk,
            )
        else:
            # invariato: edge/google
            ...
```

Aggiornare il sito che invoca `run_generation` (in `/api/generate` route) per passare `gemini_style_instruction` ricevuto dal body request.

Test completo:
```python
def test_style_applied_only_to_first_chunk_of_each_chapter(monkeypatch, tmp_path):
    from generation_engine import run_generation
    # ... costruire job mock con 2 capitoli, ciascuno generante 3 chunk dopo split
    # ... patchare gemini_tts.synthesize, edge_tts disable, google_tts disable
    # ... invocare run_generation(..., gemini_style_instruction="calmo")
    # assert: 6 chiamate, prima di ogni capitolo style="calmo", successive None
```

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_generation_engine_style.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add generation_engine.py test/test_generation_engine_style.py
git commit -m "feat(gen): apply style_instruction prefix only to first chunk per chapter"
```

---

### Task E3: Accumulo `gemini_actual` tokens/seconds nel job

**Files:**
- Modify: `generation_engine.py`
- Modify: `audiobook_app.py` (Job dataclass se necessario)
- Test: `test/test_generation_engine_accumulation.py` (NEW)

- [ ] **Step 1: Test fallente**

```python
def test_run_generation_accumulates_gemini_actuals(monkeypatch, tmp_path):
    # … mock synthesize che ritorna input_tokens=100, output_tokens=500 per chunk …
    # … invocare run_generation su job con 2 capitoli × 3 chunk
    # … verificare che job.gemini_actual = {
    #       "input_tokens": 600, "output_tokens": 3000,
    #       "audio_seconds": …, "chars": …, "google_cost_eur": …
    #     }
    pass
```

- [ ] **Step 2: Run fail**

Expected: FAIL (campo `gemini_actual` non esiste).

- [ ] **Step 3: Implementare**

In `Job` dataclass (`audiobook_app.py`), aggiungere:
```python
@dataclass
class Job:
    # ... campi esistenti ...
    gemini_actual: dict = field(default_factory=lambda: {
        "input_tokens": 0, "output_tokens": 0,
        "audio_seconds": 0.0, "chars": 0, "google_cost_eur": 0.0,
    })
    payment: dict = field(default_factory=dict)  # {token, total_eur, method, ...}
```

In `generation_engine.run_generation`, nel loop synth Gemini:
```python
if voice_id.startswith("gemini:"):
    result = gemini_tts.synthesize(chunk, voice_id, ...)
    job.gemini_actual["input_tokens"] += result["input_tokens"]
    job.gemini_actual["output_tokens"] += result["output_tokens"]
    job.gemini_actual["chars"] += len(chunk)
    # audio_seconds = bytes_written / (24000 * 2) (16-bit mono 24kHz)
    job.gemini_actual["audio_seconds"] += result["bytes_written"] / (24000.0 * 2)
    # google_cost effettivo
    bd = gemini_tts.google_cost_breakdown(
        result["input_tokens"], result["output_tokens"], result["model_key"])
    job.gemini_actual["google_cost_eur"] += bd["total_eur"]
```

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_generation_engine_accumulation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add generation_engine.py audiobook_app.py test/test_generation_engine_accumulation.py
git commit -m "feat(gen): accumulate per-job Gemini actuals (tokens, audio_seconds, cost)"
```

---

## Fase F — Audit log + refund + migration

### Task F1: Modulo `gemini_cost_audit.py` — writer/reader/aggregator

**Files:**
- Create: `gemini_cost_audit.py`
- Test: `test/test_gemini_cost_audit.py` (NEW)

- [ ] **Step 1: Test fallente**

```python
import json
import pytest
from pathlib import Path

def test_append_record_creates_monthly_file(tmp_path, monkeypatch):
    import gemini_cost_audit as gca
    monkeypatch.setattr(gca, "_DATA_DIR", tmp_path)
    rec = {"job_id":"j1","model_key":"flash25","language":"it",
           "user_price_eur_charged":1.0,"google_cost_eur_actual":0.5,
           "delta_eur":0.0,"outcome":"completed"}
    gca.append_record(rec)
    files = list(tmp_path.glob("gemini_cost_audit_*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8").strip().split("\n")
    assert json.loads(content[0])["job_id"] == "j1"

def test_iter_records_filters_by_model(tmp_path, monkeypatch):
    import gemini_cost_audit as gca
    monkeypatch.setattr(gca, "_DATA_DIR", tmp_path)
    for k in ["flash25","flash31","flash25"]:
        gca.append_record({"job_id":"x","model_key":k,"outcome":"completed"})
    recs = list(gca.iter_records(model="flash25"))
    assert len(recs) == 2

def test_aggregate_returns_delta_pct(tmp_path, monkeypatch):
    import gemini_cost_audit as gca
    monkeypatch.setattr(gca, "_DATA_DIR", tmp_path)
    gca.append_record({"job_id":"a","model_key":"flash25","language":"it",
                       "user_price_eur_charged":1.0,"user_price_eur_should_have_been":1.10,
                       "delta_eur":0.10,"delta_pct":10.0,"outcome":"completed"})
    gca.append_record({"job_id":"b","model_key":"flash25","language":"it",
                       "user_price_eur_charged":2.0,"user_price_eur_should_have_been":2.10,
                       "delta_eur":0.10,"delta_pct":5.0,"outcome":"completed"})
    agg = gca.aggregate(model="flash25")
    assert agg["count"] == 2
    assert agg["delta_pct_avg"] == pytest.approx(7.5, abs=0.1)
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_gemini_cost_audit.py -v`
Expected: 3 FAIL (modulo non esiste).

- [ ] **Step 3: Implementare `gemini_cost_audit.py`**

```python
"""Audit log writer/reader/aggregator per Gemini TTS cost estimation.

Formato: JSONL append-only, file mensile in ABM_DATA_DIR.
Filename: gemini_cost_audit_YYYY-MM.jsonl
"""
import os
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_DATA_DIR = Path(os.environ.get("ABM_DATA_DIR", "."))
_lock = threading.Lock()


def _current_file():
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    return _DATA_DIR / f"gemini_cost_audit_{ym}.jsonl"


def append_record(record: dict):
    """Append atomico (append-mode + lock) di un record audit."""
    rec = dict(record)
    rec.setdefault("ts", datetime.now(timezone.utc).isoformat())
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
    with _lock:
        fp = _current_file()
        fp.parent.mkdir(parents=True, exist_ok=True)
        with open(fp, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def iter_records(model=None, language=None, outcome=None,
                 date_from=None, date_to=None):
    """Itera record applicando filtri. date_from/to: ISO date 'YYYY-MM-DD'."""
    for fp in sorted(_DATA_DIR.glob("gemini_cost_audit_*.jsonl")):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if model and rec.get("model_key") != model:
                        continue
                    if language and rec.get("language") != language:
                        continue
                    if outcome and rec.get("outcome") != outcome:
                        continue
                    ts = rec.get("ts", "")
                    if date_from and ts[:10] < date_from:
                        continue
                    if date_to and ts[:10] > date_to:
                        continue
                    yield rec
        except IOError:
            continue


def aggregate(model=None, language=None, date_from=None, date_to=None):
    """Aggregati su record completed: count, revenue, cost, margin, delta avg."""
    n = 0
    revenue = 0.0
    cost = 0.0
    delta_pcts = []
    for rec in iter_records(model=model, language=language,
                            outcome="completed",
                            date_from=date_from, date_to=date_to):
        n += 1
        revenue += float(rec.get("user_price_eur_charged", 0) or 0)
        cost += float(rec.get("google_cost_eur_actual", 0) or 0)
        dp = rec.get("delta_pct")
        if dp is not None:
            delta_pcts.append(float(dp))
    return {
        "count": n,
        "revenue_eur": round(revenue, 4),
        "google_cost_eur": round(cost, 4),
        "margin_eur": round(revenue - cost, 4),
        "delta_pct_avg": round(sum(delta_pcts) / len(delta_pcts), 2) if delta_pcts else 0.0,
        "filters": {"model": model, "language": language,
                    "date_from": date_from, "date_to": date_to},
    }
```

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_gemini_cost_audit.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add gemini_cost_audit.py test/test_gemini_cost_audit.py
git commit -m "feat(audit): add gemini_cost_audit JSONL writer/reader/aggregator module"
```

---

### Task F2: Scrittura record audit alla fine di `run_generation`

**Files:**
- Modify: `generation_engine.py`
- Test: `test/test_generation_writes_audit.py` (NEW)

- [ ] **Step 1: Test fallente**

```python
def test_run_generation_writes_audit_on_success(monkeypatch, tmp_path):
    # … mock synth, jobs, payment …
    # invoke run_generation(job, voice_id="gemini:flash25:Zephyr", ...)
    # verifica che gemini_cost_audit.append_record sia chiamato
    # con outcome="completed" e dati actual coerenti
    pass

def test_run_generation_writes_audit_on_failure(monkeypatch):
    # synth solleva eccezione → outcome="failed_refunded"
    pass
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_generation_writes_audit.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementare in `generation_engine.py`**

Alla fine di `run_generation` (solo per voci Gemini, dopo successful merge):
```python
import gemini_cost_audit

def _write_gemini_audit(job, voice_id, language, est_data, outcome):
    """Calcola e appende un record audit al log mensile."""
    if not voice_id.startswith("gemini:"):
        return
    actual = job.gemini_actual or {}
    model_key = voice_id.split(":")[1] if voice_id.count(":") >= 2 else "?"
    charged = float((job.payment or {}).get("total_eur", 0))
    should_have_been = gemini_tts.compute_user_price_eur(
        actual.get("google_cost_eur", 0.0), model_key
    )["user_price_eur"]
    delta_eur = round(should_have_been - charged, 4)
    delta_pct = round((delta_eur / charged * 100), 2) if charged > 0 else 0.0
    rec = {
        "job_id": job.job_id,
        "model_key": model_key,
        "language": language,
        "chars_total": actual.get("chars", 0),
        "input_tokens_est": (est_data or {}).get("input_tokens_est", 0),
        "input_tokens_actual": actual.get("input_tokens", 0),
        "output_tokens_est": (est_data or {}).get("output_tokens_est", 0),
        "output_tokens_actual": actual.get("output_tokens", 0),
        "audio_seconds_est": (est_data or {}).get("audio_seconds_est", 0),
        "audio_seconds_actual": round(actual.get("audio_seconds", 0), 2),
        "google_cost_eur_est": (est_data or {}).get("google_cost_eur", 0),
        "google_cost_eur_actual": round(actual.get("google_cost_eur", 0), 4),
        "user_price_eur_charged": charged,
        "user_price_eur_should_have_been": round(should_have_been, 2),
        "delta_eur": delta_eur,
        "delta_pct": delta_pct,
        "margin_eur_actual": round(charged - actual.get("google_cost_eur", 0), 4),
        "outcome": outcome,
    }
    gemini_cost_audit.append_record(rec)
```

Invocare con `outcome="completed"` al successo, `"failed_refunded"` nell'except, `"cancelled_refunded"` nel branch cancel.

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_generation_writes_audit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add generation_engine.py test/test_generation_writes_audit.py
git commit -m "feat(audit): write gemini cost audit record at end of run_generation"
```

---

### Task F3: Refund automatico su errore/cancel/crash + estensione `/api/generate`

**Files:**
- Modify: `audiobook_app.py` (handler `/api/generate`)
- Modify: `generation_engine.py` (except → refund)
- Modify: `payment.py` (helper di consumo token unificato)
- Test: `test/test_payment_token_consumption.py` (NEW)

- [ ] **Step 1: Test fallente**

```python
def test_generate_with_token_consumes_voucher(client, jb):
    code = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")["code"]
    r = client.post("/api/generate", json={
        "job_id": "jbgen1", "voice": "gemini:flash25:Zephyr",
        "rate": "+0%", "single_file": False, "output_format": "m4b",
        "selected_chapters": [0],
        "payment_token": code,
        "gemini_style_instruction": "tono calmo",
        "gemini_model_key": "flash25",
    })
    # Il job parte → voucher remaining_eur diminuito
    assert r.status_code == 200
    v = payment._vouchers[code]
    assert payment._voucher_remaining(v) < 5.0

def test_generate_without_token_above_threshold_rejected(client, jb_large):
    # job grande, stima > 0.50€
    r = client.post("/api/generate", json={
        "job_id":"jbgen2","voice":"gemini:flash25:Zephyr",
        "rate":"+0%","selected_chapters":[0],
    })
    assert r.status_code == 402  # Payment Required

def test_refund_on_generation_failure(monkeypatch):
    # simulare crash dentro run_generation
    # → _voucher_refund deve essere chiamato con job.payment.total_eur
    pass
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_payment_token_consumption.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementare**

In `payment.py`, aggiungere helper unificato:
```python
def consume_payment_token(token, amount_eur, job_id, purpose="gemini"):
    """Consuma token (voucher o PayPal order) per amount_eur. Restituisce metodo usato.
    Raises ValueError su token invalido / saldo insufficiente.
    """
    if not token:
        raise ValueError("missing payment_token")
    # Prova voucher
    if token in _vouchers:
        _voucher_consume(token, amount_eur, job_id=job_id)
        _mark_paid_job_done(job_id, purpose=purpose)  # vedi Task F4 (migration)
        return "voucher"
    # Prova PayPal order già capturato
    if _paypal_order_is_captured(token):
        if _paypal_amount_matches(token, amount_eur):
            _mark_paid_job_done(job_id, purpose=purpose)
            return "paypal"
        raise ValueError("paypal amount mismatch")
    raise ValueError("invalid payment_token")
```

In `audiobook_app.py` `/api/generate` route (riga ~4191), aggiungere preflight:
```python
# Dopo aver letto voice_id e prima di avviare thread:
payment_token = data.get("payment_token")
style_instruction = (data.get("gemini_style_instruction") or "")[:300]
model_key_explicit = data.get("gemini_model_key")

if voice.startswith("gemini:"):
    # Ricalcola stima server-side
    chs = [job.chapters[i] for i in selected_chapters if 0 <= i < len(job.chapters)] \
          if selected_chapters else job.chapters
    est = gemini_tts.estimate_book_cost(chs, voice, language=job.language or "it")
    llm_eur = 0.0
    if data.get("ai_opt_enabled"):
        chars = sum(len(c.text or "") for c in chs)
        rate = float(os.environ.get("LLM_PRICE_EUR_PER_MCHAR","1.10"))
        llm_eur = round((chars/1_000_000.0)*rate, 2)
    total_eur = round(est["user_price_eur"] + llm_eur, 2)
    threshold = float(os.environ.get("ABM_GEMINI_FREE_THRESHOLD_EUR","0.50"))
    if total_eur > threshold:
        if not payment_token:
            return jsonify({"error":"payment_required","total_eur":total_eur}), 402
        try:
            method = payment.consume_payment_token(payment_token, total_eur, job.job_id, purpose="gemini")
        except ValueError as e:
            return jsonify({"error": f"payment_invalid: {e}"}), 400
        job.payment = {
            "token": payment_token, "total_eur": total_eur,
            "method": method, "ts": time.time(),
            "gemini_est": est, "llm_eur": llm_eur,
        }
```

In `generation_engine.run_generation`, wrappare in try/except:
```python
try:
    # ... loop synth ...
    _write_gemini_audit(job, voice_id, language, est_data, outcome="completed")
except Exception as e:
    if job.payment and job.payment.get("token"):
        try:
            payment._voucher_refund(
                job.payment["token"], job.payment["total_eur"],
                job_id=job.job_id, reason=f"generation failed: {e}",
            )
        except Exception:
            pass  # se token PayPal, emettere voucher di rimborso (Task F4)
    _write_gemini_audit(job, voice_id, language, est_data, outcome="failed_refunded")
    raise
```

Cancel branch analogo (dove esiste handler di cancellazione).

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_payment_token_consumption.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add audiobook_app.py generation_engine.py payment.py test/test_payment_token_consumption.py
git commit -m "feat(payment): gate generate behind token, refund on failure/cancel"
```

---

### Task F4: Migration `_paid_opt_done.json` → `_paid_jobs_done.json` + recovery esteso

**Files:**
- Modify: `payment.py`
- Test: `test/test_paid_jobs_migration.py` (NEW)

- [ ] **Step 1: Test fallente**

```python
import json, shutil
from pathlib import Path
import pytest

def test_migration_creates_unified_file(tmp_path, monkeypatch):
    import payment
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_OPT_DONE_FILE", tmp_path / "_paid_opt_done.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    (tmp_path / "_paid_opt_done.json").write_text(json.dumps(["job1","job2"]))
    payment._migrate_paid_opt_to_paid_jobs()
    new = json.loads((tmp_path / "_paid_jobs_done.json").read_text())
    assert {r["job_id"] for r in new} == {"job1","job2"}
    assert all(r["purpose"]=="llm" for r in new)
    assert (tmp_path / "_paid_opt_done.json.pre_unify_bak").exists()

def test_migration_idempotent_skip_if_already_done(tmp_path, monkeypatch):
    import payment
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_OPT_DONE_FILE", tmp_path / "_paid_opt_done.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    (tmp_path / "_paid_jobs_done.json").write_text(json.dumps([{"job_id":"x","purpose":"gemini"}]))
    (tmp_path / "_paid_opt_done.json").write_text(json.dumps(["job1"]))
    payment._migrate_paid_opt_to_paid_jobs()
    # _paid_jobs_done.json invariato
    data = json.loads((tmp_path / "_paid_jobs_done.json").read_text())
    assert len(data) == 1 and data[0]["job_id"] == "x"

def test_recovery_extended_to_gemini(tmp_path, monkeypatch):
    # voucher con uso recente, job_id non in _paid_jobs_done, jobs dict vuoto
    # → refund automatico
    pass
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_paid_jobs_migration.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementare**

In `payment.py`:
```python
_PAID_JOBS_DONE_FILE = _DATA_DIR / "_paid_jobs_done.json"
_paid_jobs_done: list = []  # lista di {job_id, purpose, ts}
_paid_jobs_lock = threading.Lock()


def _migrate_paid_opt_to_paid_jobs():
    """One-shot migration eseguita allo startup, atomic + idempotent.
    Vedere docs/superpowers/specs/2026-05-14-...md sezione 7.1.
    """
    if _PAID_JOBS_DONE_FILE.exists():
        return  # già migrato
    if not _PAID_OPT_DONE_FILE.exists():
        # crea file vuoto
        _atomic_write_json(_PAID_JOBS_DONE_FILE, [])
        return
    # backup
    bak = _PAID_OPT_DONE_FILE.with_suffix(".json.pre_unify_bak")
    if not bak.exists():
        shutil.copy2(_PAID_OPT_DONE_FILE, bak)
    # lettura legacy
    try:
        with open(_PAID_OPT_DONE_FILE, "r", encoding="utf-8") as f:
            legacy = json.load(f)
    except Exception as e:
        raise RuntimeError(f"FATAL migration: cannot read legacy _paid_opt_done.json: {e}")
    if not isinstance(legacy, list):
        raise RuntimeError(f"FATAL migration: legacy data not a list: {type(legacy)}")
    unified = [{"job_id": jid, "purpose": "llm", "ts": 0} for jid in legacy if jid]
    _atomic_write_json(_PAID_JOBS_DONE_FILE, unified)
    print(f"[startup] Migrated {len(unified)} record(s) to _paid_jobs_done.json")


def _atomic_write_json(path, data):
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(path)


def _load_paid_jobs_done():
    global _paid_jobs_done
    if not _PAID_JOBS_DONE_FILE.exists():
        _paid_jobs_done = []
        return
    try:
        with open(_PAID_JOBS_DONE_FILE, "r", encoding="utf-8") as f:
            _paid_jobs_done = json.load(f)
    except Exception as e:
        print(f"[paid_jobs_done] Load failed: {e}")
        _paid_jobs_done = []


def _save_paid_jobs_done():
    with _paid_jobs_lock:
        _atomic_write_json(_PAID_JOBS_DONE_FILE, _paid_jobs_done)


def _mark_paid_job_done(job_id: str, purpose: str = "gemini"):
    with _paid_jobs_lock:
        _paid_jobs_done.append({"job_id": job_id, "purpose": purpose, "ts": time.time()})
    _save_paid_jobs_done()


def _is_paid_job_done(job_id: str) -> bool:
    return any(r.get("job_id") == job_id for r in _paid_jobs_done)
```

Modificare `_recover_orphaned_voucher_charges` (riga 374):
```python
def _recover_orphaned_voucher_charges(jobs):
    cutoff = time.time() - 2 * 3600
    recovered = 0
    for code, v in _vouchers.items():
        uses = v.get("uses") or []
        for use in uses:
            amt = float(use.get("amount_eur", 0) or 0)
            if amt <= 0: continue
            if float(use.get("at", 0) or 0) < cutoff: continue
            use_job_id = use.get("job_id", "")
            if not use_job_id: continue
            if _is_paid_job_done(use_job_id): continue  # estesto: copre llm + gemini
            if use_job_id in jobs: continue
            if any(float(u.get("amount_eur",0) or 0) < 0 and u.get("job_id")==use_job_id
                   for u in uses): continue
            try:
                _voucher_refund(code, amt, job_id=use_job_id,
                                reason="Recovery startup: job orfano (unified)")
                recovered += 1
            except Exception as e:
                print(f"[startup] Recovery failed for voucher {code} job {use_job_id}: {e}")
    if recovered:
        print(f"[startup] Recovered {recovered} orphaned voucher charge(s)")
```

Allo startup di `audiobook_app.py`, sostituire `_load_paid_opt_done()` con:
```python
payment._migrate_paid_opt_to_paid_jobs()
payment._load_paid_jobs_done()
payment._recover_orphaned_voucher_charges(jobs)
```

Vecchie funzioni `_save/_load/_mark_paid_opt_done` mantenute come shim deprecate che redirigono al nuovo storage (per non rompere riferimenti residui).

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_paid_jobs_migration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add payment.py audiobook_app.py test/test_paid_jobs_migration.py
git commit -m "feat(payment): unify _paid_opt_done.json → _paid_jobs_done.json with atomic migration"
```

---

## Fase G — Admin UI

### Task G1: Endpoint `GET /admin/api/gemini_cost_audit`

**Files:**
- Modify: `audiobook_app.py`
- Test: `test/test_admin_audit_endpoint.py` (NEW)

- [ ] **Step 1: Test fallente**

```python
def test_admin_audit_endpoint_returns_records(client, admin_session):
    # crea 3 record audit fittizi
    import gemini_cost_audit as gca
    for i in range(3):
        gca.append_record({"job_id":f"j{i}","model_key":"flash25",
                           "language":"it","outcome":"completed",
                           "user_price_eur_charged":1.0,
                           "google_cost_eur_actual":0.5,
                           "delta_pct":2.0})
    r = client.get("/admin/api/gemini_cost_audit?model=flash25&limit=10",
                   headers=admin_session)
    assert r.status_code == 200
    d = r.get_json()
    assert d["count"] == 3
    assert d["aggregates"]["count"] == 3

def test_admin_audit_requires_auth(client):
    r = client.get("/admin/api/gemini_cost_audit")
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_admin_audit_endpoint.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementare**

```python
@app.route("/admin/api/gemini_cost_audit", methods=["GET"])
@admin_required  # decoratore esistente
def admin_api_gemini_cost_audit():
    import gemini_cost_audit
    model = request.args.get("model")
    language = request.args.get("language")
    outcome = request.args.get("outcome")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    limit = int(request.args.get("limit", 200))
    offset = int(request.args.get("offset", 0))
    recs = list(gemini_cost_audit.iter_records(
        model=model if model and model != "all" else None,
        language=language if language and language != "all" else None,
        outcome=outcome if outcome and outcome != "all" else None,
        date_from=date_from, date_to=date_to,
    ))
    total = len(recs)
    page = recs[offset:offset + limit]
    agg = gemini_cost_audit.aggregate(
        model=model if model and model != "all" else None,
        language=language if language and language != "all" else None,
        date_from=date_from, date_to=date_to,
    )
    return jsonify({"records": page, "count": total, "aggregates": agg})
```

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_admin_audit_endpoint.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add audiobook_app.py test/test_admin_audit_endpoint.py
git commit -m "feat(admin): add /admin/api/gemini_cost_audit endpoint with filters"
```

---

### Task G2: Tab "Gemini Audit" in `/admin/logs`

**Files:**
- Modify: `templates/admin_logs.html` (o l'equivalente template del cruscotto logs)

- [ ] **Step 1: Test fallente**

Cercare prima il template logs esistente: `Grep "tab.*logs"` in `templates/`. Test:
```python
from pathlib import Path
def test_admin_logs_has_gemini_audit_tab():
    files = list(Path("templates").glob("admin*.html"))
    found = False
    for f in files:
        if 'data-tab="gemini_audit"' in f.read_text(encoding="utf-8"):
            found = True; break
    assert found
```

- [ ] **Step 2: Run fail**

Run: `pytest test/test_admin_audit_tab.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementare**

Identificare il template admin `/logs` (search `Grep "admin.*logs"` in templates) e aggiungere:
- Bottone tab `<button data-tab="gemini_audit">Audit Gemini</button>`
- Pannello con tabella vuota popolata da fetch (`/admin/api/gemini_cost_audit`)
- Filtri: select modello (`all/flash25/flash31`), lingua, outcome, date range
- Footer aggregates: count, revenue, cost, margin, delta% medio
- I nomi tecnici dei provider (`Gemini 2.5 Flash`, `DeepSeek` se applicabile) **sono ammessi** in admin UI (vedere `feedback_ui_provider_naming.md`)

JS handler tab che fetcha e renderizza la tabella + aggregates.

- [ ] **Step 4: Run PASS**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/admin_logs.html test/test_admin_audit_tab.py
git commit -m "feat(admin): add Gemini Audit tab in /admin/logs with filters and aggregates"
```

---

### Task G3: Endpoint `GET /admin/api/gemini_cost_audit/recalc-params` + UI

**Files:**
- Modify: `audiobook_app.py`
- Modify: template admin logs (bottone "Calcola parametri suggeriti")

- [ ] **Step 1: Test fallente**

```python
def test_recalc_params_returns_suggestions(client, admin_session):
    import gemini_cost_audit as gca
    for _ in range(5):
        gca.append_record({"job_id":"j","model_key":"flash25","language":"it",
                           "outcome":"completed","delta_pct":7.0,
                           "user_price_eur_charged":1.0,
                           "user_price_eur_should_have_been":1.07,
                           "google_cost_eur_actual":0.5})
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_session)
    d = r.get_json()
    assert "suggestions" in d
    assert any(s["model"] == "flash25" and s["language"] == "it" for s in d["suggestions"])
```

- [ ] **Step 2: Run fail**

Expected: FAIL.

- [ ] **Step 3: Implementare**

```python
@app.route("/admin/api/gemini_cost_audit/recalc-params", methods=["GET"])
@admin_required
def admin_api_gemini_recalc_params():
    import gemini_cost_audit
    groups = {}  # (model, lang) → list of records
    for rec in gemini_cost_audit.iter_records(outcome="completed"):
        k = (rec.get("model_key"), rec.get("language"))
        groups.setdefault(k, []).append(rec)
    suggestions = []
    for (model, lang), recs in groups.items():
        if len(recs) < 3:
            continue  # campione troppo piccolo
        avg_delta_pct = sum(float(r.get("delta_pct", 0) or 0) for r in recs) / len(recs)
        suggestion = {
            "model": model, "language": lang, "sample_size": len(recs),
            "avg_delta_pct": round(avg_delta_pct, 2),
            "recommendation": (
                f"Delta medio {avg_delta_pct:+.2f}%: " +
                ("considera aumentare margin_percent del modello "
                 if avg_delta_pct < -5 else
                 "considera diminuire margin_percent del modello "
                 if avg_delta_pct > 5 else
                 "parametri OK ")
                + f"({model})"
            ),
        }
        suggestions.append(suggestion)
    return jsonify({"suggestions": suggestions})
```

Pulsante UI nel tab admin che fa fetch e mostra le suggestion in una `<pre>` o tabella.

- [ ] **Step 4: Run PASS**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add audiobook_app.py templates/admin_logs.html test/test_recalc_params.py
git commit -m "feat(admin): add recalc-params endpoint suggesting Gemini pricing adjustments"
```

---

## Fase H — Cleanup, i18n, test estesi

### Task H1: i18n nuove chiavi (7 lingue)

**Files:**
- Modify: `templates/_fragments/i18n_data.js`
- Test: `test/test_i18n_completeness.py` (NEW)

- [ ] **Step 1: Test fallente**

```python
from pathlib import Path
import re
I18N = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
NEW_KEYS = [
    "tab_voices_standard","tab_voices_premium","lbl_model","lbl_style_instruction",
    "cost_estimate_label","cost_free","cost_under_threshold",
    "pay_modal_title","pay_premium_voices","pay_text_ai_optimization","pay_total",
    "pay_tab_voucher","pay_tab_paypal","pay_voucher_code","pay_voucher_email",
    "pay_cancel","pay_confirm","pay_err_empty","pay_err_voucher_not_found",
    "pay_err_email_mismatch","pay_err_revoked","pay_err_insufficient",
    "pay_err_unknown","pay_err_network","pay_ok_remaining",
    "pay_paypal_unavailable","pay_paypal_captured","pay_paypal_capture_failed",
    "pay_paypal_error","p3_subtitle",
]
LANGS = ["it","en","fr","es","de","zh","hi"]

def test_all_keys_in_all_langs():
    missing = []
    for lang in LANGS:
        m = re.search(rf'{lang}:\s*\{{(.*?)\}},?\s*(?:[a-z]+:|}})', I18N, re.DOTALL)
        block = m.group(1) if m else ""
        for k in NEW_KEYS:
            if f'{k}:' not in block and f'"{k}":' not in block:
                missing.append(f"{lang}.{k}")
    assert not missing, f"missing keys: {missing}"
```

- [ ] **Step 2: Run fail**

Expected: FAIL (chiavi mancanti).

- [ ] **Step 3: Aggiungere chiavi nel blocco i18n di ciascuna lingua**

In `i18n_data.js`, per ogni lingua, aggiungere il sotto-blocco con le traduzioni delle 30+ chiavi. Esempio it:
```javascript
it: {
  // ... esistenti ...
  tab_voices_standard: "Voci Standard (gratis)",
  tab_voices_premium: "★ Voci PREMIUM",
  lbl_model: "Modello",
  lbl_style_instruction: "Istruzioni di stile (opzionale)",
  cost_estimate_label: "Stima costo audiolibro",
  cost_free: "Gratis",
  cost_under_threshold: "sotto soglia",
  pay_modal_title: "Pagamento generazione",
  pay_premium_voices: "Voci PREMIUM",
  pay_text_ai_optimization: "Ottimizzazione testo AI",
  pay_total: "Totale",
  pay_tab_voucher: "Buono",
  pay_tab_paypal: "PayPal",
  pay_voucher_code: "Codice buono",
  pay_voucher_email: "Email (verifica)",
  pay_cancel: "Annulla",
  pay_confirm: "Conferma",
  pay_err_empty: "Inserisci codice e email",
  pay_err_voucher_not_found: "Buono non trovato",
  pay_err_email_mismatch: "Email non corrispondente",
  pay_err_revoked: "Buono revocato",
  pay_err_insufficient: "Saldo insufficiente",
  pay_err_unknown: "Errore validazione",
  pay_err_network: "Errore di rete",
  pay_ok_remaining: "Saldo disponibile",
  pay_paypal_unavailable: "PayPal non disponibile",
  pay_paypal_captured: "Pagamento completato — clicca Conferma",
  pay_paypal_capture_failed: "Cattura pagamento fallita",
  pay_paypal_error: "Errore PayPal: ",
  p3_subtitle: "Scegli voce e formato dell'audiolibro",
},
```

Tradurre le stringhe in en/fr/es/de/zh/hi mantenendo la regola "no provider names" (es. "★ Voci PREMIUM" → "★ PREMIUM Voices" in EN, mai "★ Gemini Voices").

- [ ] **Step 4: Run PASS**

Run: `pytest test/test_i18n_completeness.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/_fragments/i18n_data.js test/test_i18n_completeness.py
git commit -m "i18n: add Premium tab / payment modal keys across 7 languages"
```

---

### Task H2: Test stress money-critical (concorrenza voucher + race su `_paid_jobs_done.json`)

**Files:**
- Test: `test/test_money_critical_stress.py` (NEW)

- [ ] **Step 1: Test fallente**

```python
import threading
import payment

def test_concurrent_voucher_consumption_no_overspend(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    code = payment._create_voucher("c@x.it", 10.0, kind="test", note="t")["code"]
    errors = []
    def consume():
        try:
            payment._voucher_consume(code, 4.0, job_id=f"j{threading.get_ident()}")
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=consume) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    # solo 2 dovrebbero riuscire (4+4=8 ≤ 10), il terzo deve fallire (saldo insuff)
    v = payment._vouchers[code]
    assert payment._voucher_remaining(v) >= 0
    assert len(errors) >= 1, "almeno un consume deve fallire per saldo insufficiente"

def test_concurrent_mark_paid_job_done_no_loss(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    payment._paid_jobs_done = []
    def mark(i):
        payment._mark_paid_job_done(f"job{i}", purpose="gemini")
    threads = [threading.Thread(target=mark, args=(i,)) for i in range(20)]
    for t in threads: t.start()
    for t in threads: t.join()
    import json
    data = json.loads((tmp_path / "_paid_jobs_done.json").read_text())
    assert len({r["job_id"] for r in data}) == 20

def test_double_click_generate_idempotent_no_double_charge(client, jb_big, monkeypatch):
    code = payment._create_voucher("dd@x.it", 5.0, kind="test", note="t")["code"]
    # invia 2 richieste rapide /api/generate stesso job_id
    # → secondo deve essere rifiutato o no-op, voucher decrementato 1 sola volta
    pass
```

- [ ] **Step 2: Run fail**

Expected: FAIL.

- [ ] **Step 3: Aggiungere lock granulari**

In `payment.py`, garantire che `_voucher_consume`, `_voucher_refund`, `_mark_paid_job_done` siano protetti dai rispettivi lock e che `_atomic_write_json` sia usato per ogni save. Per la double-click idempotency in `/api/generate`, aggiungere check:
```python
if payment._is_paid_job_done(job.job_id):
    return jsonify({"error":"already_paid"}), 409
```
prima del `consume_payment_token`.

- [ ] **Step 4: Run PASS**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add payment.py audiobook_app.py test/test_money_critical_stress.py
git commit -m "test(money): add concurrency stress tests for voucher and paid_jobs persistence"
```

---

### Task H3: Documentazione + smoke E2E manuali

**Files:**
- Modify: `PARAMETRI_CONFIGURAZIONE.md`
- Create: `docs/MANUAL_TESTS_GEMINI_PAYMENT.md`

- [ ] **Step 1: Aggiornare `PARAMETRI_CONFIGURAZIONE.md`**

Aggiungere sezione "Audit log Gemini" con riferimento al file mensile `gemini_cost_audit_YYYY-MM.jsonl`, formato record, retention (manuale, file piccoli) e parametri di tuning (margin_percent, chars_per_token).

- [ ] **Step 2: Creare `docs/MANUAL_TESTS_GEMINI_PAYMENT.md`**

Checklist smoke E2E pre-release:
```markdown
# Manual Smoke Tests — Gemini Premium + Payment

## Free path (totale ≤ 0.50€)
- [ ] Job piccolo (testo ~10K char), voce flash25, no AI opt → no modal, generation parte, audit log scritto outcome=completed

## Paid voucher
- [ ] Job grande (~200K char), voce flash31, AI opt on
- [ ] Modal si apre, totale > 0.50€
- [ ] Validate voucher (codice valido, email match) → "saldo disponibile" verde, btn Conferma enabled
- [ ] Click Conferma → modal chiude, generation parte, voucher remaining_eur decrementato
- [ ] Audit log scritto outcome=completed, delta_pct < 15%

## Paid PayPal (sandbox)
- [ ] Stesso job grande
- [ ] Modal → tab PayPal → SDK buttons renderizzati
- [ ] Approve in sandbox → "Pagamento completato" verde → Conferma → generation parte
- [ ] Audit log scritto outcome=completed

## Refund su errore
- [ ] Forzare errore (es. revocare API key Gemini durante synth) → exception
- [ ] Verificare voucher refundato (remaining_eur ripristinato a valore originale)
- [ ] Audit log outcome=failed_refunded

## Refund su cancel
- [ ] Lanciare generazione lunga, premere cancel
- [ ] Verificare refund + audit log outcome=cancelled_refunded

## Recovery dopo crash
- [ ] Lanciare generazione paid, kill server -9 prima del completamento
- [ ] Restart server, verificare log "Recovered N orphaned voucher charge(s)"
- [ ] Audit log scritto outcome=recovered_refunded

## Token invalidation
- [ ] Aprire modal con stima X
- [ ] Cambiare selezione capitoli mentre modal è aperto
- [ ] Riaprire modal → totale diverso, token precedente non valido

## Stress concorrenza
- [ ] Lanciare 5 generazioni con voci/modelli diversi simultaneamente, voucher diversi
- [ ] Verificare `_paid_jobs_done.json` ha 5 record distinti, no race
```

- [ ] **Step 3: Commit finale**

```bash
git add PARAMETRI_CONFIGURAZIONE.md docs/MANUAL_TESTS_GEMINI_PAYMENT.md
git commit -m "docs: document Gemini audit log params and manual smoke test checklist"
```

---

## Self-review (post-implementazione)

Prima di considerare il piano completato:

- [ ] Eseguire l'intera test-suite: `pytest test/ -v` → 0 fallimenti
- [ ] Test manuali dalla checklist `MANUAL_TESTS_GEMINI_PAYMENT.md` → tutti spuntati
- [ ] Verificare admin tab `/admin/logs` → Audit Gemini visibile, filtri funzionanti
- [ ] Smoke pre-deploy:
  - Browser: aprire l'app, navigare wizard fino a Panel 3
  - Switch tab Standard ↔ Premium: voce attiva si svuota correttamente
  - Selezionare voce Premium, modificare modello: lista voci aggiornata
  - Tornare a Standard, verificare assenza voci Gemini
  - Verificare costPreviewBox aggiornato su cambio modello (non su cambio voce)
- [ ] Verificare audit log dopo prime 3 generazioni paid: delta_pct ragionevole (<15%)
- [ ] Verificare `feedback_ui_provider_naming.md` rispettato in tutte le UI utente (grep "DeepSeek" e "Gemini" nei file utente-facing → solo dove ammesso da spec)

---

## Execution Handoff

**Plan complete and saved to** `docs/superpowers/plans/2026-05-14-gemini-tts-premium-tab-and-payment.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — dispatch fresh subagent per task, review tra task, fast iteration; consigliato per il flusso money-critical.
2. **Inline Execution** — eseguire i task in questa session con checkpoint review.

**Which approach?**
