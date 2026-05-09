# Piano di implementazione — Feedback, News e Live Stats

**Data:** 2026-05-09
**Branch base:** `main` (commit `c4e58c5` "unify donation text and add donation panel to main page completion")
**Mockup di riferimento:** `mockup/feedback_widget.html`
**Versione target:** 3.13 → 3.14

---

## 1. Obiettivo

Trasferire i tre nuovi widget prototipizzati nel mockup all'interno dell'app reale, **senza riscrivere il template** ma **innestandoli nei punti coerenti** della struttura attuale (header → live-stats → wizard-steps → main-card → resources-section). Si mantiene il pattern già adottato (Flask single-file, fragments HTML, i18n via `data-t`, ABM_DATA_DIR per persistenza, ADMIN_TOKEN per pagine protette).

I tre interventi sono:

| Feature | Posizione | Persistenza | Admin |
|---|---|---|---|
| **A. Feedback widget** | Sotto `.resources-section`, prima del footer | `<DATA_DIR>/feedback.json` | Tab "Feedback" su `/admin/community` |
| **B. News (banner + pannello)** | Banner dopo `<header>`, pannello sotto Feedback | `<DATA_DIR>/news.json` | Tab "News" su `/admin/community` |
| **C. Live Stats** | Riga sotto la `tagline` nell'header | Derivate da `activity_YYYY-MM.log` (già esistenti) | nessuna (read-only) |

---

## 2. Open questions — decisioni proposte

Prima di scendere nel dettaglio, ecco le decisioni che propongo con la motivazione. Ogni voce è **da confermare** prima di partire con l'implementazione.

### 2.1 Storage: JSON file su `ABM_DATA_DIR` (non SQLite)
- **Motivazione:** repo non usa SQLite altrove; volumi attesi bassi (≲ qualche migliaio di feedback all'anno, ≲ 50 news/anno); pattern già consolidato con `activity_YYYY-MM.log`.
- **Implementazione:** modulo `community_store.py` con `read()/write()/append()` e write atomico (`tmp + os.replace`) sotto `threading.Lock` per file. Backup automatico `*.bak` mantenuto al rename precedente.
- **Path:** `<DATA_DIR>/feedback.json`, `<DATA_DIR>/news.json`. Stesso volume persistente già usato dai job.

### 2.2 News multilingua: testo neutro **single-language**
- **Motivazione:** frequenza di pubblicazione bassa, overhead di tradurre 6 lingue alto. L'autore sceglie la lingua di pubblicazione, viene mostrata così com'è. Tag e UI vicina (titoli colonne, tag "feature/fix/info") restano localizzati via `data-t`.
- **Schema:** `{ id, lang, tag, title, body, banner, created_at, archived }`.
- **Future iteration:** se servisse, si può aggiungere campo opzionale `translations: { en: {...}, fr: {...} }` retro-compatibile.

### 2.3 Archiviazione vs eliminazione: **soft-delete**
- **Motivazione:** consente "ri-pubblicare" una vecchia news, mantiene storico moderazione, evita perdite. L'eliminazione definitiva è disponibile come azione separata.
- **Schema:** flag `archived: bool` su entrambi feedback e news. UI admin filtra per default ai non-archiviati con toggle "Mostra archiviati".

### 2.4 Anti-spam feedback: rate-limit + honeypot + validazione
- **Motivazione:** captcha penalizza UX e privacy; il volume atteso non giustifica friction. Combinazione classica e leggera.
- **Implementazione:**
  - **Rate-limit** in memoria: 1 feedback/IP/ora + 5/IP/giorno (LRU dict con TTL); flush al restart, sufficiente.
  - **Honeypot field** `<input name="website" style="display:none">` ignorato dagli umani; submit con valore non-vuoto → 204 silenzioso.
  - **Validazione:** stelle 1–5 obbligatorie; commento opzionale `length ≤ 800`; nome opzionale `length ≤ 60`; trim + collapse whitespace; URL/HTML strippati.

### 2.5 Stats: derivate dai log attività esistenti
- **Motivazione:** `_log_activity()` già scrive una riga per ogni operazione "complete" su `activity_YYYY-MM.log` con campo `voice`. La lingua TTS si deriva con `voice.split("-")[0]` (es. `it-IT-IsabellaNeural` → `it`). Niente nuovi contatori da gestire.
- **Cache:** in-memory, TTL 60s per `today` e 5min per `monthly_by_lang`. Lock dedicato. Dimensione trascurabile.
- **Retention:** invariata (i log mensili esistono già; nessuna policy nuova). Per "questo mese" si parsa solo `activity_YYYY-MM.log` corrente, ~1MB tipico.
- **"Operation"** considerata: ogni riga con `operation == "complete"` (audiolibro generato con successo). Da confermare guardando le costanti in `audiobook_app.py`.

---

## 3. Architettura comune

### 3.1 Nuovo modulo `community_store.py`
Singolo file con tre store + helpers, ~250 righe.

```python
# community_store.py — stub interfaccia
class JsonStore:
    def __init__(self, path: Path): ...
    def read_all(self) -> list[dict]: ...
    def append(self, item: dict) -> dict: ...      # assegna id, created_at
    def update(self, item_id: str, patch: dict) -> dict | None: ...
    def delete(self, item_id: str) -> bool: ...     # hard delete

def init(data_dir: str | Path) -> None: ...
def feedback() -> JsonStore: ...
def news() -> JsonStore: ...
def stats_today() -> dict: ...                       # {count: int}
def stats_month_by_lang() -> dict: ...               # {top: [...], other: int, total: int, monthly: int}
```

- Tutti gli ID sono `secrets.token_hex(8)` (stringa di 16 char).
- `created_at` ISO-8601 UTC.
- Ogni record ha `archived: bool` di default `False`.

### 3.2 Endpoint pubblici (3) e admin (5)

| Metodo | Path | Auth | Scopo |
|---|---|---|---|
| GET  | `/api/community/feedback` | — | lista feedback non-archiviati + media stelle + istogramma |
| POST | `/api/community/feedback` | — | crea feedback (rate-limit + honeypot) |
| GET  | `/api/community/news` | — | lista news non-archiviate (banner + lista) |
| GET  | `/api/community/stats/today` | — | `{count: int}` (cache 60s) |
| GET  | `/api/community/stats/month` | — | top4 + altre + totale (cache 5min) |
| GET  | `/admin/community` | token | pagina HTML con due tab |
| POST | `/admin/api/feedback/<id>/archive` | token | soft-delete |
| POST | `/admin/api/feedback/<id>` | token | hard-delete |
| POST | `/admin/api/news` | token | crea news |
| POST | `/admin/api/news/<id>/archive` | token | soft-delete |
| POST | `/admin/api/news/<id>` | token | hard-delete / update |

L'auth admin riusa il pattern già esistente (vedi `/admin/vouchers` e `/api/admin/suspend`): controllo header `X-Admin-Token` o body `token` confrontato con `ADMIN_TOKEN`. La pagina HTML mostra il `tokenInput` come `/admin/vouchers`.

### 3.3 Notifiche email
Riuso `email_service._send_email(to, subject, html)` già presente.
- Trigger: nuovo feedback ricevuto.
- Destinatario: `ABM_ADMIN_EMAIL` (se vuoto, skip silenzioso).
- Throttling: max 1 email ogni 30 minuti (semplice timestamp ultimo invio in memoria; se busy, si "compatta" in un batch all'invio successivo).

---

## 4. Phase 1 — Live Stats (read-only, rischio minimo)

### 4.1 Backend
**File:** `audiobook_app.py`

Aggiunte nella sezione "Activity log" (dopo riga ~977):

```python
_stats_cache = {"today": (0, 0.0), "month": (None, 0.0)}  # (value, expires_at)
_stats_lock = threading.Lock()

def _stats_today_count() -> int:
    """Conta righe operation=='complete' nel log del mese corrente con date odierna."""
    # parsing semplice: split("#"), check ts startswith today, op == 'complete'
    ...

def _stats_month_by_lang() -> dict:
    """Aggrega per lingua TTS le generazioni completate del mese corrente.
    Voce → lingua: voice.split('-')[0] lowercased.
    Restituisce {monthly: int, top: [{lang, count}], other: int}."""
    ...
```

Endpoint:
```python
@app.route("/api/community/stats/today")
def api_stats_today():
    return jsonify({"count": _stats_today_count()})

@app.route("/api/community/stats/month")
def api_stats_month():
    return jsonify(_stats_month_by_lang())
```

### 4.2 HTML — `templates/_fragments/html_head.html`
Inserire **subito dopo** `</header>` (riga ~175) e **prima** della news banner zone (Phase 2):

```html
<!-- LIVE STATS -->
<div class="live-stats" id="liveStats" hidden>
  <span>📚 <span id="lsToday">0</span> <span data-t="ls_books_today"></span></span>
  <span class="ls-sep">·</span>
  <a href="#" class="ls-link" id="lsMore" data-t="ls_more"></a>
</div>

<!-- STATS MODAL -->
<div class="stats-modal-overlay" id="statsModal" role="dialog" aria-modal="true" aria-labelledby="statsModalTitle" hidden>
  <div class="stats-modal">
    <div class="stats-modal-head">
      <h3 id="statsModalTitle" data-t="stats_modal_title"></h3>
      <button class="stats-modal-close" id="statsModalClose" aria-label="Close">&times;</button>
    </div>
    <div class="stats-modal-body">
      <div class="stats-big">
        <div class="stats-big-num" id="smBigNum">0</div>
        <div class="stats-big-label" data-t="stats_modal_monthly"></div>
      </div>
      <div class="stats-section-title" data-t="stats_modal_by_lang"></div>
      <div id="smRows"><!-- popolata da JS, max 4 + ALT --></div>
      <div class="stats-modal-footer" data-t="stats_modal_footer"></div>
    </div>
  </div>
</div>
```

### 4.3 CSS — `static/css/style.css`
Append delle classi del mockup (sezione `.live-stats`, `.stats-modal-*`, `.stats-row*`). ~80 righe nuove sotto un commento `/* ─── LIVE STATS & MODAL ─── */`.

### 4.4 JS — `static/js/app.js`
Append (sezione nuova in fondo o vicino a `applyI18n`):

```js
// ── Live stats ──
async function loadLiveStats(){
  try{
    const r = await fetch('/api/community/stats/today');
    if(!r.ok) return;
    const {count} = await r.json();
    const ls = document.getElementById('liveStats');
    if(count > 0){
      ls.hidden = false;
      animateCount(document.getElementById('lsToday'), count, 1200);
    }
  }catch(e){ /* silent */ }
}
function animateCount(el, target, duration){
  if(!el) return;
  const start = performance.now();
  (function tick(now){
    const t = Math.min(1,(now-start)/duration);
    const eased = 1 - Math.pow(1-t,4);
    el.textContent = Math.round(target*eased);
    if(t<1) requestAnimationFrame(tick);
  })(performance.now());
}

// ── Stats modal ──
async function openStatsModal(ev){
  if(ev) ev.preventDefault();
  const modal = document.getElementById('statsModal');
  modal.hidden = false;
  modal.classList.add('open');
  document.getElementById('smBigNum').textContent = '0';
  document.getElementById('smRows').innerHTML = '';
  try{
    const r = await fetch('/api/community/stats/month');
    const data = await r.json();   // {monthly, top:[{lang, count}], other}
    renderStatsRows(data);
    animateCount(document.getElementById('smBigNum'), data.monthly, 1400);
    requestAnimationFrame(()=>requestAnimationFrame(()=>{
      modal.querySelectorAll('.stats-row-bar-fill').forEach(b=>{
        b.style.width = b.dataset.target+'%';
      });
    }));
    modal.querySelectorAll('.stats-row-num').forEach(n=>{
      animateCount(n, parseInt(n.dataset.target,10), 1400);
    });
  }catch(e){ /* mostra errore inline */ }
}
function renderStatsRows(data){
  const FLAGS = {it:'🇮🇹', en:'🇬🇧', fr:'🇫🇷', es:'🇪🇸', de:'🇩🇪', zh:'🇨🇳', pt:'🇵🇹', ja:'🇯🇵', ru:'🇷🇺' /* … */};
  const max = Math.max(...data.top.map(r=>r.count), data.other||0, 1);
  const html = data.top.map(r=>{
    const pct = Math.round(r.count/max*100);
    const flag = FLAGS[r.lang] || '🌐';
    const code = r.lang.toUpperCase();
    return `<div class="stats-row">
      <span class="stats-row-label"><span class="flag">${flag}</span><span class="code">${code}</span></span>
      <div class="stats-row-bar"><div class="stats-row-bar-fill" data-target="${pct}" style="width:0%"></div></div>
      <span class="stats-row-num" data-target="${r.count}">0</span>
    </div>`;
  }).join('');
  let other = '';
  if(data.other > 0){
    const pct = Math.round(data.other/max*100);
    other = `<div class="stats-row">
      <span class="stats-row-label"><span class="flag">🌐</span><span class="code">ALT</span></span>
      <div class="stats-row-bar"><div class="stats-row-bar-fill other" data-target="${pct}" style="width:0%"></div></div>
      <span class="stats-row-num" data-target="${data.other}">0</span>
    </div>`;
  }
  document.getElementById('smRows').innerHTML = html + other;
}
document.addEventListener('DOMContentLoaded', ()=>{
  loadLiveStats();
  document.getElementById('lsMore')?.addEventListener('click', openStatsModal);
  document.getElementById('statsModalClose')?.addEventListener('click', ()=>{
    document.getElementById('statsModal').hidden = true;
  });
});
```

### 4.5 i18n — `i18n/*.json`
Aggiungere chiavi (in `ui` section):
```
ls_books_today, ls_more, stats_modal_title, stats_modal_monthly,
stats_modal_by_lang, stats_modal_footer
```

### 4.6 Test manuale Phase 1
1. Restart app → riga live-stats visibile solo se `count > 0`.
2. Genera un audiolibro completo → `count` aumenta entro 60s.
3. Click su "altre stats" → modale, count-up + barre animate.
4. Cambia lingua → testi tradotti.
5. Toggle dark/light → modale leggibile in entrambi.

---

## 5. Phase 2 — News (banner + pannello)

### 5.1 Backend — `audiobook_app.py`
```python
@app.route("/api/community/news")
def api_news_list():
    items = [n for n in community_store.news().read_all() if not n.get("archived")]
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return jsonify({"items": items[:10]})  # max 10 più recenti

@app.route("/admin/api/news", methods=["POST"])
def admin_api_news_create():
    if not _check_admin_token(request): return jsonify({"error":"forbidden"}), 403
    data = request.json or {}
    item = {
        "lang":  data.get("lang", "it")[:2],
        "tag":   data.get("tag", "info"),
        "title": (data.get("title") or "").strip()[:120],
        "body":  (data.get("body")  or "").strip()[:600],
        "banner": bool(data.get("banner", False)),
        "archived": False,
    }
    if not item["title"] or item["tag"] not in ("feature","fix","info"):
        return jsonify({"error":"invalid"}), 400
    return jsonify(community_store.news().append(item))
```

### 5.2 HTML — `templates/_fragments/html_head.html`
**Banner**: subito sotto `.live-stats`:
```html
<div class="news-banner" id="newsBanner" hidden>
  <span class="nb-tag" id="nbTag"></span>
  <span class="nb-text" id="nbText"></span>
  <button class="nb-close" id="nbClose" aria-label="Dismiss">×</button>
</div>
```

**Pannello collassabile**: nuova posizione sotto `.resources-section` (riga ~588), prima del feedback widget di Phase 3:
```html
<section class="community-card news-card" id="newsCard">
  <div class="news-head" onclick="toggleNewsPanel()" role="button" tabindex="0">
    <h3>
      <span class="news-pulse-dot" aria-hidden="true"></span>
      <span data-t="news_panel_title"></span>
      <span class="news-count" id="newsCount" hidden>(0)</span>
    </h3>
    <span class="news-chevron">▾</span>
  </div>
  <div class="news-body" id="newsBody">
    <ul class="news-list" id="newsList"></ul>
  </div>
</section>
```

### 5.3 CSS — `static/css/style.css`
Append `.news-banner`, `.news-card`, `.news-head`, `.news-body`, `.news-list`, `.news-item`, `.news-tag` (con varianti `.feature/.fix/.info`), `.news-pulse-dot` (animazione `@keyframes pulse`). ~120 righe.

### 5.4 JS — `static/js/app.js`
- `loadNews()` chiamato a DOMContentLoaded; popola banner (la più recente con `banner:true`) + lista.
- localStorage: `abm_news_dismissed_v1 = {ids:[id1, id2], sessions: 0}`. Auto-dismiss dopo 2 sessioni:
  - Su ogni page-load: se l'id banner è già in `ids`, incrementa `sessions`; nascondi quando `sessions >= 2`.
  - Pulsante × → aggiunge id a `ids` con `sessions: 99` (forzato già visto).
- `toggleNewsPanel()`: collapse/expand con `max-height` transition come nel mockup.

### 5.5 Notifica autore in admin
Form HTML in `/admin/community` (Tab News): select tag + input title + textarea + checkbox banner + bottone Pubblica. Submit POST con header `X-Admin-Token`.

### 5.6 i18n
```
news_panel_title, news_empty, news_dismiss, news_published_at,
news_tag_feature, news_tag_fix, news_tag_info
```

---

## 6. Phase 3 — Feedback widget

### 6.1 Backend — `audiobook_app.py`
```python
_feedback_rate = {}   # ip -> [(timestamp, count_hour), (timestamp, count_day)]
_feedback_rate_lock = threading.Lock()

def _check_feedback_rate(ip: str) -> bool:
    """True se l'IP è entro i limiti (1/h, 5/giorno)."""
    ...

@app.route("/api/community/feedback", methods=["GET"])
def api_feedback_list():
    items = [f for f in community_store.feedback().read_all() if not f.get("archived")]
    items.sort(key=lambda x: x["created_at"], reverse=True)
    # Aggrega: media + istogramma 1-5
    n = len(items) or 1
    avg = round(sum(f["stars"] for f in items)/n, 2) if items else 0
    hist = [0]*5
    for f in items: hist[f["stars"]-1] += 1
    return jsonify({
        "items": [{"id":f["id"],"stars":f["stars"],"name":f.get("name",""),
                   "comment":f.get("comment",""),"created_at":f["created_at"]}
                  for f in items[:50]],
        "avg": avg, "total": len(items), "histogram": hist,
    })

@app.route("/api/community/feedback", methods=["POST"])
def api_feedback_create():
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
    data = request.json or {}
    # Honeypot
    if (data.get("website") or "").strip(): return ("", 204)
    # Rate-limit
    if not _check_feedback_rate(ip): return jsonify({"error":"rate_limit"}), 429
    # Validation
    try: stars = int(data.get("stars"))
    except: return jsonify({"error":"invalid_stars"}), 400
    if stars < 1 or stars > 5: return jsonify({"error":"invalid_stars"}), 400
    item = {
        "stars":   stars,
        "name":    _sanitize((data.get("name") or "").strip(), 60),
        "comment": _sanitize((data.get("comment") or "").strip(), 800),
        "lang":    (data.get("lang") or "")[:2],
        "ip_hash": _hash_ip(ip),
        "archived": False,
    }
    saved = community_store.feedback().append(item)
    _notify_admin_new_feedback(saved)   # email throttled
    return jsonify({"ok": True, "id": saved["id"]})
```

`_sanitize`: strip HTML tags via regex semplice + collapse whitespace.
`_hash_ip`: `hashlib.sha256(ip+SALT).hexdigest()[:16]` (no IP raw on disk).

### 6.2 HTML — fragment "feedback widget"
Inserito **dopo** `<section class="community-card social-card">` (riga ~587) e **prima** di `</section>` resources-section.

Adatta il markup `.fbw` del mockup; due stati (collapsed `#fb1` / expanded `#fb2`) gestiti da `toggleFbw()`.

### 6.3 JS — `static/js/app.js`
- `loadFeedback()` su DOMContentLoaded: popola istogramma + lista commenti.
- Form submit: valida stelle, costruisce JSON, fetch POST, on-success ricarica lista e mostra toast "Grazie per il feedback".
- Stelle interattive: 5 `<button>` con stato `aria-pressed` e classe `.active`.

### 6.4 CSS
Stile classi `.fbw*` come nel mockup, ~150 righe.

### 6.5 Email notification
```python
def _notify_admin_new_feedback(item: dict) -> None:
    if not ADMIN_EMAIL: return
    now = time.time()
    if now - _feedback_email_last_ts < 1800: return  # 30 min throttle
    _feedback_email_last_ts = now
    subj = f"[ABM] Nuovo feedback: {item['stars']}★"
    html = render_feedback_email(item)
    try: email_service._send_email(ADMIN_EMAIL, subj, html)
    except Exception as e: print(f"[feedback-email] {e}")
```

### 6.6 i18n
```
fb_title, fb_avg, fb_total_reviews, fb_histogram, fb_form_title,
fb_stars_label, fb_name_ph, fb_comment_ph, fb_submit, fb_thanks,
fb_rate_limit, fb_invalid, fb_recent_label, fb_anonymous
```

---

## 7. Admin UI — `/admin/community`

Singola pagina HTML servita inline (come `/admin/vouchers`), due tab top "Feedback" / "News".

**Auth:** input `X-Admin-Token` salvato in `localStorage.abm_admin_token`. Comportamento identico a `/admin/vouchers` (vedi righe 2262–2498 di `audiobook_app.py`).

**Layout:**
- Tab **Feedback**: stats (totale, media, distribuzione %) + tabella `(data, stelle, nome, commento, IP-hash, azioni)`. Azioni: archivia / elimina.
- Tab **News**: form pubblicazione + stats (totali per tag) + tabella `(data, lang, tag, title, banner, azioni)`. Azioni: archivia / elimina / toggle banner.

Filtro "Mostra archiviati" su entrambi i tab.

---

## 8. File toccati — riepilogo

| File | Azione | Linee stimate |
|---|---|---:|
| `community_store.py` | **nuovo** | ~250 |
| `audiobook_app.py` | aggiunte (endpoint + helper stats + admin page + auth helper) | +~600 |
| `templates/_fragments/html_head.html` | aggiunte (live-stats, news-banner, news-card, feedback widget, stats-modal) | +~150 |
| `static/css/style.css` | aggiunte (live-stats, stats-modal, news, fbw) | +~400 |
| `static/js/app.js` | aggiunte (loadLiveStats, openStatsModal, loadNews, loadFeedback, submitFeedback, toggleNewsPanel) | +~350 |
| `i18n/{it,en,fr,es,de,zh}.json` | aggiunte chiavi (~30 nuove × 6 lingue) | +~180 |
| `email_service.py` | (nessuna modifica, riuso `_send_email`) | 0 |
| `version.py` | bump `3.13` → `3.14` | 1 |
| `PARAMETRI_CONFIGURAZIONE.md` | doc nuove env vars (nessuna nuova in realtà; doc i nuovi file su DATA_DIR) | +~30 |
| **`.gitignore`** | rimuovere riga `mockup/` quando si rimuove la cartella (post-implementazione) | -1 |

Nessuna nuova variabile d'ambiente richiesta (riusa `ABM_DATA_DIR`, `ABM_ADMIN_EMAIL`, `ABM_ADMIN_TOKEN`).

---

## 9. Sequenza di implementazione consigliata

1. **PR #1 — Phase 1 Live Stats** (basso rischio, read-only)
   - `community_store.py` (solo helper stats, niente JsonStore)
   - Endpoint `/api/community/stats/{today,month}`
   - Frammento HTML + CSS + JS
   - i18n
   - Test: visualizza in dev con log fittizio.

2. **PR #2 — Phase 2 News**
   - `JsonStore` + `news()` su community_store
   - Endpoint pubblici + admin
   - Frammento HTML banner + pannello + admin page tab "News"
   - localStorage logic per dismiss
   - i18n.

3. **PR #3 — Phase 3 Feedback**
   - `feedback()` store + rate-limit + sanitize + IP hash
   - Endpoint pubblici + admin + email notification
   - Frammento HTML widget + admin page tab "Feedback"
   - i18n.

4. **PR #4 — polish**
   - Doc utente su `Guida_Utente_AudiobookMaker.docx` (se rilevante)
   - Bump version, changelog
   - Pulizia `mockup/` (opzionale: lasciare come reference, oppure spostare in `docs/mockups/`).

Ogni PR è autosufficiente e deployabile.

---

## 10. Testing checklist (per ogni PR)

**Phase 1 — Stats**
- [ ] `count=0` → riga live-stats nascosta
- [ ] `count>0` → animazione 0→target in 1.2s
- [ ] Modale: count-up del totale + barre animate da 0% → target
- [ ] 4 lingue + ALT (aggregato) max 5 righe
- [ ] Lingua sconosciuta → flag `🌐` + code 2 lettere uppercase
- [ ] Cache 60s/5min rispettata (verificare con header `X-Cache: HIT/MISS`)

**Phase 2 — News**
- [ ] Banner mostra solo news più recente con `banner:true`
- [ ] Click × → dismiss permanente per quell'id
- [ ] Auto-dismiss dopo 2 sessioni senza click manuale
- [ ] Pannello collassato di default; click → espande con transition
- [ ] Tag colorato corretto (feature=verde, fix=arancio, info=blu)
- [ ] Pubblicazione admin → news visibile su homepage entro reload
- [ ] Archive → scompare da pubblico, resta in admin con flag

**Phase 3 — Feedback**
- [ ] Submit valido → toast "grazie", lista aggiornata
- [ ] Stelle assenti → 400
- [ ] Honeypot compilato → 204 silenzioso, nessun record
- [ ] 2° feedback dallo stesso IP entro 1h → 429
- [ ] Comment > 800 char → troncato a 800
- [ ] HTML in nome/commento → strippato
- [ ] Email admin ricevuta entro 30s (con `ABM_ADMIN_EMAIL` configurato)
- [ ] 2° feedback entro 30min → email NON inviata (throttle)
- [ ] Admin archive → scompare da `/api/community/feedback`
- [ ] IP raw mai presente nel JSON (solo hash)

**Cross-cutting**
- [ ] Dark mode: tutti i widget leggibili
- [ ] Mobile (≤480px): widget non sforano, modale full-screen-ish
- [ ] 6 lingue: tutte le label tradotte (zero `data-t` vuoti)
- [ ] Lighthouse score homepage non peggiora di > 2 punti
- [ ] Nessun JS error in console su homepage clean

---

## 11. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| Parsing log mensile lento al primo hit | Cache 5min; in più il file è < 5MB anche con 50k operazioni |
| `feedback.json` cresce indefinitamente | Endpoint pubblico già limita a 50 più recenti. Admin può archiviare. Hard-delete via admin se serve. |
| Concorrenza scrittura JSON | Lock per file + atomic rename (`tmp + os.replace`). Backup `.bak` precedente conservato. |
| Spam burst da molti IP diversi | Rate-limit per IP + honeypot; se persiste, aggiungere captcha in fase successiva. |
| ADMIN_TOKEN non impostato | Endpoint admin restituiscono 404 (come già `/admin/vouchers`); l'app pubblica funziona comunque. |
| Cambi schema futuri al JSON | Tutti i record hanno `id`+`created_at`; nuovi campi sempre con default lato lettura. Niente migrazioni necessarie nel breve. |

---

## 12. Decisioni esplicite — DA CONFERMARE prima di implementare

1. ☐ Storage JSON su DATA_DIR (sez. 2.1) — OK?
2. ☐ News single-language (sez. 2.2) — OK?
3. ☐ Soft-delete + hard-delete come azione separata (sez. 2.3) — OK?
4. ☐ Anti-spam senza captcha (sez. 2.4) — OK?
5. ☐ Stats da activity log (sez. 2.5) — OK?
6. ☐ Endpoint pubblici sotto `/api/community/*` (vs `/api/public/*` o altro) — OK?
7. ☐ Pagina admin unica `/admin/community` con due tab (vs due pagine separate `/admin/feedback` e `/admin/news`) — OK?
8. ☐ Sequenza Phase 1 → 2 → 3 in PR separati — OK?

Confermate queste otto decisioni e si parte con la PR #1.
