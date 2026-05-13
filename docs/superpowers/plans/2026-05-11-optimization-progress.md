# Distribuzione Progresso Ottimizzazione AI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distribuire il 100% della barra di avanzamento dell'ottimizzazione AI tra elaborazione capitoli e attività di finalizzazione, eliminando lo stallo al 99%.

**Architecture:** Estendere il denominatore del progresso con un peso di finalizzazione calcolato come `max(3000, total_chars * 0.03)`. Durante la fase di finalizzazione (generazione .abm, invio email), il backend emette messaggi SSE intermedi incrementando progressivamente `opt_processed_chars` fino al totale esteso. Il frontend rimuove il cap a 99% e usa il totale esteso quando disponibile.

**Tech Stack:** Python (Flask), JavaScript vanilla, SSE.

---

### Task 1: Backend — Estendere il progresso in `generation_engine.py`

**Files:**
- Modify: `generation_engine.py:1049-1068` (calcolo totali iniziali)
- Modify: `generation_engine.py:1105-1175` (fase di finalizzazione)

---

- [ ] **Step 1: Aggiungere costanti e calcolo totale esteso**

Dopo il calcolo di `total_chars` (linea 1050), aggiungere:

```python
    FINALIZATION_RATIO = 0.03
    MIN_FINALIZATION_CHARS = 3000
    finalization_weight = max(MIN_FINALIZATION_CHARS, int(total_chars * FINALIZATION_RATIO))
    total_chars_extended = total_chars + finalization_weight
```

Poi aggiornare l'inizializzazione del job (dopo linea 1068):

```python
    job["opt_total_chars"] = total_chars
    job["opt_total_chars_extended"] = total_chars_extended
    job["opt_finalization_weight"] = finalization_weight
```

Mantenere `job["opt_total_chars"]` per retrocompatibilità frontend.

---

- [ ] **Step 2: Aggiungere helper per emettere progresso di finalizzazione**

Aggiungere una funzione helper nella sezione `run_optimization` (prima del blocco `try`, dopo l'inizializzazione del job):

```python
    def _emit_finalization_progress(phase_name, fraction_done):
        """fraction_done: 0.0 -> 1.0 within finalization phase"""
        job["opt_processed_chars"] = total_chars + int(finalization_weight * fraction_done)
        job["opt_progress_message"] = phase_name
        job["opt_elapsed_seconds"] = round(time.time() - start_time)
        # Force immediate SSE flush by updating a timestamp
        job["opt_progress_ts"] = time.time()
```

---

- [ ] **Step 3: Iniettare progresso durante la finalizzazione**

Nella sezione di finalizzazione (dopo il ciclo for dei capitoli, prima di `job["status"] = "optimized"`), sostituire il blocco esistente con uno che emetta progresso.

Prima di `if auto_generate:` (linea 1129), aggiungere:

```python
        # --- Finalization progress ---
        _emit_finalization_progress("Finalizing optimization...", 0.0)

        # Generate .abm snapshot (30% of finalization weight)
        try:
            _emit_finalization_progress("Generating optimized project archive...", 0.15)
            abm_path, abm_name = _generate_optimized_abm(job_id)
            job["optimized_abm_path"] = abm_path
            job["optimized_abm_name"] = abm_name
            _emit_finalization_progress("Project archive created.", 0.30)
        except Exception as e:
            print(f"[{job_id}] Failed to generate .abm snapshot: {e}")
            _emit_finalization_progress("Project archive failed (non-critical).", 0.30)

        total_elapsed = time.time() - start_time
        job["opt_progress_current"] = total_chapters
        job["opt_elapsed_seconds"] = round(total_elapsed)
        job["opt_completed_at"] = time.time()
        # Track per-chapter optimization status
        optimized = set(job.get("optimized_chapters", []))
        optimized.update(ch.index for ch in chapters_to_opt)
        job["optimized_chapters"] = list(optimized)
        job["ai_optimized"] = True
        # Segna il job come completato per il recovery voucher all'avvio
        if job.get("payment_type"):
            payment._mark_paid_opt_done(job_id)

        print(f"[{job_id}] LLM optimization completed in {total_elapsed:.1f}s")
        _log_activity(job_id, job.get("original_filename", ""), "OPT_COMPLETE",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      "", job.get("browser_lang", ""))
```

Poi, prima del blocco `if auto_generate:`, aggiungere il progresso per l'invio email (batch mode):

```python
        if auto_generate:
            _emit_finalization_progress("Preparing audio generation...", 0.50)
            # ... existing auto_generate logic ...
        elif job.get("email_registered"):
            _emit_finalization_progress("Sending completion email...", 0.70)
            try:
                _send_optimization_email(job_id)
                _emit_finalization_progress("Completion email sent.", 1.0)
            except Exception as e:
                print(f"[{job_id}] Optimization email error: {e}")
                _emit_finalization_progress("Email failed (non-critical).", 1.0)
            job["status"] = "optimized"
        else:
            _emit_finalization_progress("Optimization complete!", 1.0)
            job["status"] = "optimized"
            job["last_poll"] = time.time()
```

Nota: assicurarsi che `_emit_finalization_progress(1.0)` venga chiamato in tutti i rami prima dello stato `"optimized"`.

---

- [ ] **Step 4: Syntax check backend**

Run: `python -m py_compile generation_engine.py`
Expected: No output (success).

---

- [ ] **Step 5: Commit parziale backend**

```bash
git add generation_engine.py
git commit -m "feat(opt): distribuzione progresso durante finalizzazione ottimizzazione AI"
```

---

### Task 2: Frontend — Aggiornare calcolo percentuale in `app.js`

**Files:**
- Modify: `static/js/app.js:1386-1397` (calcolo percentuale ottimizzazione)

---

- [ ] **Step 1: Modificare il calcolo della percentuale**

Sostituire il blocco esistente (linee ~1386-1397):

```javascript
    var totalChars=d.opt_total_chars||1;
    var doneChars=d.opt_processed_chars||0;
    var curChChars=d.opt_current_chapter_chars||0;
    var streamedChars=Math.min(d.opt_streamed_chars||0,curChChars);
    var workedChars=doneChars+streamedChars;
    var pct=doneChars>=totalChars?100:Math.min(99,Math.round(workedChars/totalChars*100));
```

Con:

```javascript
    var totalChars=d.opt_total_chars_extended||d.opt_total_chars||1;
    var doneChars=d.opt_processed_chars||0;
    var curChChars=d.opt_current_chapter_chars||0;
    var streamedChars=Math.min(d.opt_streamed_chars||0,curChChars);
    var workedChars=doneChars+streamedChars;
    var pct=Math.min(100,Math.round(workedChars/totalChars*100));
```

Cambiamenti:
1. `totalChars` usa `opt_total_chars_extended` se disponibile, altrimenti fallback su `opt_total_chars`.
2. Rimosso `doneChars>=totalChars?100:` perché `Math.min(100, ...)` copre già il caso.
3. Rimosso `Math.min(99, ...)` — ora la percentuale può raggiungere 100 naturalmente.

---

- [ ] **Step 2: Commit parziale frontend**

```bash
git add static/js/app.js
git commit -m "feat(ui): rimosso cap 99% su progresso ottimizzazione, supporto total_chars_extended"
```

---

### Task 3: Verifica Manuale

**Files:**
- N/A (test manuale)

---

- [ ] **Step 1: Avviare l'applicazione**

Run: `python audiobook_app.py`
Expected: Server in ascolto su http://localhost:5601.

---

- [ ] **Step 2: Test con un libro di esempio**

1. Caricare un file EPUB/PDF di test.
2. Avviare l'ottimizzazione AI (con o senza pagamento).
3. Osservare la barra di avanzamento: non deve rimanere a 99% per più di qualche secondo.
4. Alla fine dell'ultimo capitolo, la barra deve salire gradualmente verso il 100% durante la finalizzazione.

---

- [ ] **Step 3: Test retrocompatibilità**

1. Verificare che un job avviato prima dell'aggiornamento (senza `opt_total_chars_extended`) mostri comunque il progresso corretto usando `opt_total_chars`.

---

- [ ] **Step 4: Commit finale**

```bash
git add docs/superpowers/plans/2026-05-11-optimization-progress.md
git commit -m "docs(plan): piano implementazione distribuzione progresso ottimizzazione AI"
```

---

## Self-Review

**1. Spec coverage:**
- Formula `max(3000, total_chars * 0.03)` → Step 1, Task 1.
- Emettere progresso SSE durante finalizzazione → Step 2-3, Task 1.
- Rimozione cap 99% e uso `opt_total_chars_extended` → Step 1, Task 2.
- Retrocompatibilità → inclusa in entrambi i task.
- Error handling non critico → incluso in Step 3, Task 1.

**2. Placeholder scan:** Nessun TBD, TODO, o riferimento indefinito.

**3. Type consistency:** `opt_total_chars_extended` usato coerentemente in backend e frontend. `_emit_finalization_progress` definita e usata nello stesso task.
