# Nome File e Titolo Tradotti — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Il nome file output del wizard traduzione viene proposto già tradotto nella lingua di destinazione, e il titolo del libro viene tradotto nei metadati dell'output (.abm/.epub/.txt) e nel percorso audio dopo l'adozione.

**Architecture:** Il titolo del libro viene accodato al batch `translate_titles` già esistente in `run_translation` (zero chiamate LLM extra) e salvato in `job["translated_title"]`, usato dal manifest e dall'adopt. Un nuovo endpoint `GET /api/translate_title/<job_id>` traduce il solo titolo per la proposta UI (cache per lingua nel job, fallback silenzioso). Il frontend aggiorna il campo `trOutName` solo se l'utente non l'ha editato (guardia `trAutoOutName`).

**Tech Stack:** Python/Flask, `translation_core` (backend `ABM_TRANSLATE_*`), vanilla JS, pytest.

**Spec:** `docs/superpowers/specs/2026-06-06-translated-title-filename-design.md`

**Branch:** `TRADUZ` (lavorare e committare qui; mai push senza conferma esplicita).

**Convenzioni vincolanti:**
- Shell di sviluppo: PowerShell. Niente `&&` per concatenare; comandi singoli.
- Validare la sintassi Python prima di committare: `python -m py_compile <file>`.
- I file `.md` sono in `.gitignore`: per committare piani/doc usare `git add -f`.
- Test in `test/` (non `tests/`). Eseguire con: `$env:PYTHONPATH='.'; pytest test/<file> -v --tb=short`
- Sorgenti Python: apostrofi ASCII nei commenti (`e'`, non `è`).

---

## File Structure

| File | Azione | Responsabilità |
|---|---|---|
| `generation_engine.py` | **Modify** | `run_translation`: titolo libro nel batch titoli, `translated_title` nel job, manifest con titolo tradotto (righe ~2501-2519). |
| `audiobook_app.py` | **Modify** | Nuovo endpoint `/api/translate_title` (dopo `api_translate_estimate`, riga ~8620); adopt: `info.title` tradotto (riga ~8867). |
| `static/js/app.js` | **Modify** | Stato `trAutoOutName` (riga 238), `_trPrefillOutName` (1886), nuova `_trFetchTranslatedName`, trigger in `goToTranslate` (1853) e nel listener change (1876), reset (3851). |
| `test/test_run_translation.py` | **Append** | Batch con titolo libro, `translated_title`, fallback. |
| `test/test_translate_endpoints.py` | **Append** | Endpoint translate_title (successo/cache/same-lang/non-config/errore), adopt col titolo. |
| `test/test_app_js_tr_title.py` | **Create** | Test statici sul source JS (pattern `test_app_js_estimate.py`). |

**Riferimenti verificati (stato attuale branch TRADUZ, HEAD `1a4d6ba`):**
- `run_translation` batch titoli: `generation_engine.py:2501-2507`; `manifest_src`: `:2515-2519`; salvataggi `job["translated_*"]`: `:2525-2529`.
- `api_translate_estimate`: `audiobook_app.py:8620`; `api_translate_adopt`: `:8845-8888` — la risposta include GIÀ `"title": info.title` (`:8883`); `info.language` impostata a `:8867`.
- `audiobook_app` importa `translation_core` (riga 125); helper test `_check_job_owner` mockato via `_own()` in `test/test_translate_endpoints.py:50-52`.
- Frontend: stato translate `app.js:238` (`let trPaymentToken=null,trEstimate=null,trEmailRegistered=false;`); `goToTranslate`: `:1847-1856`; binding change select lingue: `:1876` (`if(!sel._trBound){...addEventListener('change',trUpdateEstimate)}`); `_trPrefillOutName`: `:1886-1892`; reset `trOutName` in `resetAll`: `:3851`; `adoptTranslation` usa GIÀ `d.title` (`:2071`) — **nessuna modifica frontend per l'adopt**.
- Convenzioni test: `test/test_run_translation.py` (fixture `fake_llm` mocka `tc.translate_titles` con `[x + "_EN" for x in titles]`); `test/test_translate_endpoints.py` (`_seed`, `_own`, fixture autouse `_bootstrap` che forza `translation_core.is_available` → True); `test/test_app_js_estimate.py` (test statici su source JS).

---

### Task 1: `generation_engine.run_translation` — titolo libro nel batch + `translated_title`

**Files:**
- Modify: `generation_engine.py:2501-2529`
- Test: `test/test_run_translation.py` (append)

- [x] **Step 1.1: Scrivi i test falliti**

Append a `test/test_run_translation.py` (gli helper `_seed_job`, `fake_llm`, `_Info` esistono già nel file; il mock `translate_titles` di `fake_llm` ritorna `x + "_EN"` per ogni elemento):

```python
# ── Titolo libro tradotto (spec 2026-06-06-translated-title-filename) ──

def test_run_translation_translates_book_title(fake_llm, tmp_path):
    job_id, job = _seed_job(tmp_path)
    ge.run_translation(job_id)
    assert job["translated_title"] == "Libro_EN"
    # Il writer txt mette il titolo del manifest in intestazione
    body = Path(job["translated_path"]).read_text(encoding="utf-8")
    assert "Libro_EN" in body
    # I titoli capitoli NON includono il titolo libro
    assert [c["title"] for c in job["translated_chapters"]] == ["Uno_EN", "Due_EN"]


def test_run_translation_title_appended_to_batch(fake_llm, tmp_path, monkeypatch):
    captured = {}
    def _tt(provider, titles, s, t, **kw):
        captured["titles"] = list(titles)
        return [x + "_EN" for x in titles]
    monkeypatch.setattr(tc, "translate_titles", _tt)
    job_id, job = _seed_job(tmp_path)
    ge.run_translation(job_id)
    assert captured["titles"] == ["Uno", "Due", "Libro"]


def test_run_translation_empty_book_title(fake_llm, tmp_path):
    job_id, job = _seed_job(tmp_path)
    job["info"].title = ""
    ge.run_translation(job_id)
    assert job["translated_title"] == ""
    assert job["status"] == "translated"


def test_run_translation_blank_translated_title_falls_back(fake_llm, tmp_path, monkeypatch):
    def _tt(provider, titles, s, t, **kw):
        out = [x + "_EN" for x in titles]
        out[-1] = "  "  # traduzione del titolo libro vuota
        return out
    monkeypatch.setattr(tc, "translate_titles", _tt)
    job_id, job = _seed_job(tmp_path)
    ge.run_translation(job_id)
    assert job["translated_title"] == "Libro"  # fallback: originale
```

- [x] **Step 1.2: Esegui — verifica fallimento**

Run: `$env:PYTHONPATH='.'; pytest test/test_run_translation.py -v --tb=short -k title`
Expected: FAIL con `KeyError: 'translated_title'`

- [x] **Step 1.3: Implementa in `run_translation`**

Sostituire il blocco di traduzione titoli (`generation_engine.py:2501-2507`):

```python
        job["tr_progress_message"] = "Translating chapter titles..."
        titles = [c["title"] for c in out_chapters]
        book_title = (getattr(info, "title", "") or "").strip()
        if book_title:
            # Il titolo del libro viaggia nello stesso batch dei titoli
            # capitoli: un elemento in piu', zero chiamate LLM extra
            # (spec 2026-06-06-translated-title-filename).
            titles.append(book_title)
        translated_titles = translation_core.translate_titles(
            provider, titles, source, target,
            model=model, usage=usage, log=_log)
        translated_title = ""
        if book_title:
            translated_title = (translated_titles[-1] or "").strip() or book_title
            translated_titles = translated_titles[:len(out_chapters)]
        for c, t in zip(out_chapters, translated_titles):
            c["title"] = (t or "").strip() or c["title"]
```

Poi nel `manifest_src` (`:2515-2519`) sostituire la riga del titolo:

```python
        manifest_src = {
            "title": translated_title or (getattr(info, "title", "") or ""),
            "author": getattr(info, "author", "") or "",
            "original_filename": job.get("original_filename", ""),
        }
```

Infine, accanto agli altri salvataggi (`:2525-2529`, dopo `job["translated_optimized"] = optimize`):

```python
        job["translated_title"] = translated_title
```

Nota: `translate_titles` garantisce una lista della stessa lunghezza dell'input
(su errore ritorna gli originali), quindi `translated_titles[-1]` è sempre il
titolo libro quando `book_title` è presente e il troncamento
`[:len(out_chapters)]` riallinea i titoli capitolo.

- [x] **Step 1.4: Valida ed esegui tutto il file**

Run: `python -m py_compile generation_engine.py`
Run: `$env:PYTHONPATH='.'; pytest test/test_run_translation.py -v --tb=short`
Expected: PASS (tutti, vecchi e nuovi — il mock `fake_llm` traduce anche il titolo accodato, e i test esistenti restano validi perché i titoli capitolo vengono riallineati)

- [x] **Step 1.5: Commit**

```
git add generation_engine.py test/test_run_translation.py
git commit -m "feat(translate): titolo libro tradotto nel batch titoli + translated_title nel job"
```

---

### Task 2: Endpoint `GET /api/translate_title/<job_id>`

**Files:**
- Modify: `audiobook_app.py` (inserire la nuova route subito dopo la funzione `api_translate_estimate`, riga ~8620)
- Test: `test/test_translate_endpoints.py` (append)

- [x] **Step 2.1: Scrivi i test falliti**

Append a `test/test_translate_endpoints.py` (helper `_seed`/`_own` e fixture `client`/`_bootstrap` esistono già; `_Info.title == "Libro"`, `_Info.language == "it"`):

```python
# ── /api/translate_title (spec 2026-06-06-translated-title-filename) ──

def _mock_title_llm(monkeypatch, replies):
    """Mocka il layer LLM del titolo; ritorna la lista delle chiamate."""
    calls = []
    monkeypatch.setattr(audiobook_app.translation_core, "resolve_backend",
                        lambda: "apikey")
    monkeypatch.setattr(audiobook_app.translation_core, "make_client_provider",
                        lambda b: ((lambda: None), "m", "http://x"))
    def _tt(provider, titles, s, t, **kw):
        calls.append(list(titles))
        return replies
    monkeypatch.setattr(audiobook_app.translation_core, "translate_titles", _tt)
    return calls


def test_translate_title_returns_translation(client, monkeypatch):
    _seed()
    calls = _mock_title_llm(monkeypatch, ["The Book"])
    with _own():
        r = client.get("/api/translate_title/TJ1?target=en&source=it")
    assert r.status_code == 200
    assert r.get_json()["title"] == "The Book"
    assert calls == [["Libro"]]


def test_translate_title_cached_second_call(client, monkeypatch):
    _seed()
    calls = _mock_title_llm(monkeypatch, ["The Book"])
    with _own():
        client.get("/api/translate_title/TJ1?target=en&source=it")
        r2 = client.get("/api/translate_title/TJ1?target=en&source=it")
    assert r2.get_json()["title"] == "The Book"
    assert len(calls) == 1  # seconda risposta dalla cache


def test_translate_title_same_lang_no_llm(client, monkeypatch):
    _seed()
    calls = _mock_title_llm(monkeypatch, ["BOOM"])
    with _own():
        r = client.get("/api/translate_title/TJ1?target=it&source=it")
    assert r.get_json()["title"] == "Libro"
    assert calls == []


def test_translate_title_unavailable_empty(client, monkeypatch):
    _seed()
    monkeypatch.setattr(audiobook_app.translation_core, "is_available",
                        lambda: False)
    with _own():
        r = client.get("/api/translate_title/TJ1?target=en&source=it")
    assert r.status_code == 200
    assert r.get_json()["title"] == ""


def test_translate_title_bad_target_empty(client, monkeypatch):
    _seed()
    with _own():
        r = client.get("/api/translate_title/TJ1?target=123&source=it")
    assert r.get_json()["title"] == ""


def test_translate_title_llm_error_silent(client, monkeypatch):
    _seed()
    monkeypatch.setattr(audiobook_app.translation_core, "resolve_backend",
                        lambda: "apikey")
    monkeypatch.setattr(audiobook_app.translation_core, "make_client_provider",
                        lambda b: ((lambda: None), "m", "http://x"))
    def _boom(*a, **kw):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(audiobook_app.translation_core, "translate_titles", _boom)
    with _own():
        r = client.get("/api/translate_title/TJ1?target=en&source=it")
    assert r.status_code == 200
    assert r.get_json()["title"] == ""


def test_translate_title_source_fallback_info_language(client, monkeypatch):
    """Senza ?source usa info.language ("it")."""
    _seed()
    calls = _mock_title_llm(monkeypatch, ["The Book"])
    with _own():
        r = client.get("/api/translate_title/TJ1?target=en")
    assert r.get_json()["title"] == "The Book"
    assert len(calls) == 1
```

- [x] **Step 2.2: Esegui — verifica fallimento**

Run: `$env:PYTHONPATH='.'; pytest test/test_translate_endpoints.py -v --tb=short -k translate_title`
Expected: FAIL con 404 (route inesistente)

- [x] **Step 2.3: Implementa l'endpoint**

In `audiobook_app.py`, subito dopo la funzione `api_translate_estimate` (route a riga ~8620, inserire dopo il suo `return`):

```python
@app.route("/api/translate_title/<job_id>")
def api_translate_title(job_id):
    """Traduce il solo titolo del libro per la proposta del nome file nel
    wizard traduzione. Cortesia pre-acquisto: nessun pagamento, cache per
    lingua nel job, fallimento silenzioso (title vuoto, HTTP 200).
    Spec: docs/superpowers/specs/2026-06-06-translated-title-filename-design.md
    """
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return err, sc
    info = job.get("info")
    title = (getattr(info, "title", "") or "").strip()[:300]
    target = (request.args.get("target") or "").strip().lower().split("-")[0]
    source = (request.args.get("source") or "").strip().lower().split("-")[0]
    if not source:
        source = (getattr(info, "language", "") or "").strip().lower().split("-")[0]
    import re as _re_tt
    if not title or not _re_tt.fullmatch(r"[a-z]{2,3}", target or "") \
            or not _re_tt.fullmatch(r"[a-z]{2,3}", source or ""):
        return jsonify({"title": ""})
    if source == target:
        return jsonify({"title": title})
    cache = job.setdefault("tr_title_cache", {})
    if target in cache:
        return jsonify({"title": cache[target], "cached": True})
    if not translation_core.is_available():
        return jsonify({"title": ""})
    try:
        backend = translation_core.resolve_backend()
        provider, model, _base = translation_core.make_client_provider(backend)
        out = translation_core.translate_titles(
            provider, [title], source, target,
            model=model, usage=translation_core.UsageTracker())
        translated = (out[0] or "").strip() or title
    except Exception as e:
        print(f"[tr-title] {job_id}: traduzione titolo fallita (non-fatal): {e}")
        return jsonify({"title": ""})
    cache[target] = translated
    return jsonify({"title": translated})
```

Nota stile: l'`import re as _re_tt` inline segue il pattern già usato negli
endpoint translate (`_re2`, `_re3` in `api_translate`).

- [x] **Step 2.4: Valida ed esegui tutto il file**

Run: `python -m py_compile audiobook_app.py`
Run: `$env:PYTHONPATH='.'; pytest test/test_translate_endpoints.py -v --tb=short`
Expected: PASS (tutti, vecchi e nuovi)

- [x] **Step 2.5: Commit**

```
git add audiobook_app.py test/test_translate_endpoints.py
git commit -m "feat(translate): endpoint /api/translate_title con cache per lingua"
```

---

### Task 3: Adopt — `info.title` tradotto

**Files:**
- Modify: `audiobook_app.py:8867` (dentro `api_translate_adopt`)
- Test: `test/test_translate_endpoints.py` (append)

La risposta dell'endpoint include GIÀ `"title": info.title` (`:8883`) e il
frontend `adoptTranslation()` aggiorna GIÀ `bookData.title` (`app.js:2071`):
serve solo impostare `info.title` lato server.

- [x] **Step 3.1: Scrivi i test falliti**

Append a `test/test_translate_endpoints.py`:

```python
# ── Adopt col titolo tradotto ──────────────────────────────────────────

def _seed_translated(**extra):
    job = _seed(status="translated")
    job["translated_chapters"] = [
        {"index": 1, "title": "One_EN", "text": "Translated text one."}]
    job["translated_lang"] = "en"
    job.update(extra)
    return job


def test_adopt_sets_translated_title(client):
    job = _seed_translated(translated_title="The Book")
    with _own():
        r = client.post("/api/translate_adopt/TJ1")
    assert r.status_code == 200
    assert r.get_json()["title"] == "The Book"
    assert job["info"].title == "The Book"


def test_adopt_without_translated_title_keeps_original(client):
    job = _seed_translated()
    with _own():
        r = client.post("/api/translate_adopt/TJ1")
    assert r.get_json()["title"] == "Libro"
    assert job["info"].title == "Libro"
```

- [x] **Step 3.2: Esegui — verifica fallimento**

Run: `$env:PYTHONPATH='.'; pytest test/test_translate_endpoints.py -v --tb=short -k adopt`
Expected: `test_adopt_sets_translated_title` FAIL (`title` resta "Libro"); `test_adopt_without_translated_title_keeps_original` PASS già ora (comportamento invariato)

- [x] **Step 3.3: Implementa**

In `api_translate_adopt`, subito dopo `info.language = job.get("translated_lang", info.language)` (`audiobook_app.py:8867`):

```python
    # Titolo tradotto dal batch titoli del job (se prodotto): cosi' i
    # metadati M4B/MP3, la pagina download e le email del percorso audio
    # usano il titolo nella lingua di destinazione.
    info.title = job.get("translated_title") or info.title
```

- [x] **Step 3.4: Valida ed esegui**

Run: `python -m py_compile audiobook_app.py`
Run: `$env:PYTHONPATH='.'; pytest test/test_translate_endpoints.py -v --tb=short`
Expected: PASS (tutti)

- [x] **Step 3.5: Commit**

```
git add audiobook_app.py test/test_translate_endpoints.py
git commit -m "feat(translate): adopt propaga il titolo tradotto a info.title"
```

---

### Task 4: Frontend — proposta nome file tradotto

**Files:**
- Modify: `static/js/app.js` (righe 238, 1853, 1876, 1886-1892, 3851)
- Test: Create `test/test_app_js_tr_title.py`

- [x] **Step 4.1: Scrivi i test falliti (statici sul source, pattern `test_app_js_estimate.py`)**

```python
# test/test_app_js_tr_title.py
"""Test statici su app.js: proposta nome file tradotto
(spec 2026-06-06-translated-title-filename)."""
from pathlib import Path

APP = Path("static/js/app.js").read_text(encoding="utf-8")


def test_has_fetch_translated_name():
    assert "function _trFetchTranslatedName" in APP


def test_uses_translate_title_endpoint():
    assert "/api/translate_title/" in APP


def test_guard_user_edits():
    # Aggiorna il campo solo se contiene ancora il valore auto-impostato
    assert "el.value===trAutoOutName" in APP


def test_state_var_reset():
    assert "trAutoOutName=''" in APP


def test_prefill_records_auto_value():
    assert "trAutoOutName=base" in APP


def test_fetch_triggered_from_panel_and_change():
    # definizione + chiamata in goToTranslate + chiamata nel listener change
    assert APP.count("_trFetchTranslatedName(") >= 3


def test_timeout_abort_present():
    assert "function _trFetchTranslatedName" in APP
    fn = APP.split("function _trFetchTranslatedName", 1)[1][:900]
    assert "AbortController" in fn
```

- [x] **Step 4.2: Esegui — verifica fallimento**

Run: `$env:PYTHONPATH='.'; pytest test/test_app_js_tr_title.py -v --tb=short`
Expected: FAIL su tutti (funzione assente)

- [x] **Step 4.3: Implementa in `app.js`**

**(a)** Stato (riga 238) — aggiungere `trAutoOutName`:

```javascript
let trPaymentToken=null,trEstimate=null,trEmailRegistered=false,trAutoOutName='';
```

**(b)** `_trPrefillOutName` (riga 1886-1892) — registrare il valore auto-impostato:

```javascript
function _trPrefillOutName(){
  const el=document.getElementById('trOutName');if(!el)return;
  let base=(bookData&&(bookData.original_filename||bookData.filename))||'';
  if(!base)base=(bookData&&bookData.title)||'translated';
  base=base.replace(/\.[^.]+$/,'');
  el.value=base;
  trAutoOutName=base;
}
```

**(c)** Nuova funzione, subito dopo `_trPrefillOutName`:

```javascript
async function _trFetchTranslatedName(){
  // Propone il titolo tradotto come nome file; non sovrascrive mai un
  // valore editato a mano (guardia trAutoOutName). Fallimento silenzioso.
  const el=document.getElementById('trOutName');if(!el||!jobId)return;
  const dst=document.getElementById('trDstLang');
  const src=document.getElementById('trSrcLang');
  if(!dst||!dst.value)return;
  const ctrl=new AbortController();
  const tmr=setTimeout(()=>ctrl.abort(),12000);
  try{
    const url=new URL('/api/translate_title/'+jobId,window.location.origin);
    url.searchParams.append('target',dst.value);
    if(src&&src.value)url.searchParams.append('source',src.value);
    const d=await fetch(url.toString(),{signal:ctrl.signal}).then(r=>r.json());
    if(d&&d.title&&el.value===trAutoOutName){
      el.value=d.title;
      trAutoOutName=d.title;
    }
  }catch(e){/* silenzioso: resta il prefill */}
  finally{clearTimeout(tmr)}
}
```

**(d)** Trigger all'apertura del pannello — in `goToTranslate` (riga 1853), dopo `_trPrefillOutName();`:

```javascript
  _trPrefillOutName();
  _trFetchTranslatedName();
```

**(e)** Trigger al cambio lingua destinazione — nel binding (riga 1876) sostituire:

```javascript
    if(!sel._trBound){sel._trBound=true;sel.addEventListener('change',trUpdateEstimate);}
```

con:

```javascript
    if(!sel._trBound){sel._trBound=true;sel.addEventListener('change',()=>{trUpdateEstimate();if(id==='trDstLang')_trFetchTranslatedName();});}
```

(`id` è la variabile del `forEach(['trSrcLang','trDstLang'])` che racchiude il blocco.)

**(f)** Reset — in `resetAll` accanto al reset di `trOutName` (riga 3851):

```javascript
  const trOutName=document.getElementById('trOutName');if(trOutName)trOutName.value='';
  trAutoOutName='';
```

- [x] **Step 4.4: Esegui i test**

Run: `$env:PYTHONPATH='.'; pytest test/test_app_js_tr_title.py -v --tb=short`
Expected: PASS (7 test)

Run anche i test JS esistenti (regressione rapida sul file modificato):
`$env:PYTHONPATH='.'; pytest test/test_app_js_estimate.py test/test_app_js_payment_modal.py test/test_app_js_tab_logic.py -v --tb=short`
Expected: PASS

- [x] **Step 4.5: Commit**

```
git add static/js/app.js test/test_app_js_tr_title.py
git commit -m "feat(translate): proposta nome file tradotto nel pannello (fetch + guardia edit utente)"
```

---

### Task 5: Regressione completa e chiusura

**Files:**
- Modify: `docs/superpowers/specs/2026-06-06-translated-title-filename-design.md` (stato)

- [x] **Step 5.1: Lint sintassi + suite completa**

Run: `python -m py_compile audiobook_app.py generation_engine.py`
Run: `$env:PYTHONPATH='.'; pytest test/ --tb=short -q`
Expected: nessuna nuova failure rispetto allo stato pre-piano (failure note pre-esistenti: 4 in `test_paypal_create_gemini` da ordering/reload nella suite completa — passano in isolamento).

- [x] **Step 5.2: Aggiorna stato spec e committa**

Nella spec, cambiare `**Stato:** approvato (brainstorming concluso)` in `**Stato:** implementato (2026-06-06)`. Marcare i checkbox di questo piano come `[x]`.

```
git add -f docs/superpowers/specs/2026-06-06-translated-title-filename-design.md docs/superpowers/plans/2026-06-06-translated-title-filename.md
git commit -m "docs(translate): chiusura spec + piano titolo/nome file tradotti"
```

**NON pushare:** il push si fa solo su conferma esplicita dell'utente.

---

## Note trasversali per l'esecutore

1. **Nomi da verificare sul codice reale** prima di modificare (se differiscono, adeguare il codice nuovo, mai il vecchio): `_check_job_owner`, `translation_core` (import in `audiobook_app.py:125`), `tc.translate_titles` (firma: `provider, titles, source, target, *, model, usage, log=print, dry_run=False`), `job["translated_*"]`.
2. I numeri di riga sono riferiti a HEAD `1a4d6ba` e possono slittare di qualche riga: cercare gli ancoraggi testuali citati, non fidarsi del numero.
3. **Mai** importare `audiobook_app` da `generation_engine`/`translation_core` (incidente double-import documentato).
4. `test_translate_endpoints.py` ha la fixture autouse `_bootstrap` che forza `translation_core.is_available` → True e pulisce `jobs`: i nuovi test la ereditano automaticamente.
5. UI: nessuna nuova stringa i18n (la proposta è un valore di campo, non un messaggio).
