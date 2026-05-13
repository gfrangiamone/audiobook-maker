# Admin Reply to User Feedback — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow admin to reply to user feedback comments from `/admin/community`, with one-shot LLM translation into all 7 UI languages, shown under each comment on the public widget.

**Architecture:** `POST /admin/api/feedback/<item_id>/reply` endpoint → LLM translate one-shot → persist `admin_reply_text/i18n/lang/at` fields. Public endpoint includes these fields; frontend renders reply under user comment.

**Tech Stack:** Flask (audiobook_app.py), community_translator (LLM), app.js (public widget), inline admin HTML.

---

## File Map

| File | Role |
|------|------|
| `audiobook_app.py:3198` | Existing `admin_api_feedback_update` — add new route below it |
| `audiobook_app.py:3023-3031` | Public `GET /api/community/feedback` — add 4 admin_reply fields |
| `audiobook_app.py:3279-3395` | Admin UI tab Feedback — add reply button + modal |
| `static/js/app.js:2851` | `renderRecent(items)` — render admin reply under each comment |
| `templates/_fragments/html_head.html:564-601` | Feedback widget HTML structure (no changes needed) |

---

## Task 1: Backend — POST /admin/api/feedback/<item_id>/reply

**Files:**
- Modify: `audiobook_app.py:3198` (add route after `admin_api_feedback_update`)

- [ ] **Step 1: Add the new endpoint after line 3213**

In `audiobook_app.py`, after the existing `admin_api_feedback_update` function (which ends around line 3213), add:

```python
@app.route("/admin/api/feedback/<item_id>/reply", methods=["POST"])
def admin_api_feedback_reply(item_id):
    """Post an admin reply to a feedback item.
    Translates the reply into all 7 UI languages via LLM.
    One reply per item — returns 409 if already replied.
    """
    if not _admin_auth_ok(_admin_auth_from_request()):
        return ("forbidden", 403)
    body = request.get_json(silent=True) or {}
    reply_text = (body.get("reply") or "").strip()
    # Validate
    if not reply_text:
        return jsonify({"error": "reply text required"}), 400
    if len(reply_text) > 2000:
        return jsonify({"error": "reply text exceeds 2000 characters"}), 400
    # Check existing reply
    store = community_store.feedback()
    existing = store.get(item_id)
    if not existing:
        return jsonify({"error": "feedback item not found"}), 404
    if existing.get("admin_reply_at", 0) > 0:
        return jsonify({"error": "reply already posted", "admin_reply_at": existing.get("admin_reply_at")}), 409
    # Translate via LLM
    if not community_translator.is_available():
        return jsonify({"error": "llm unavailable"}), 503
    try:
        result = community_translator.translate({"reply": reply_text})
    except Exception as e:
        print(f"[feedback-reply] translate raised for {item_id}: {e!s}")
        result = None
    if not result:
        return jsonify({"error": "translation failed, please retry"}), 500
    now = int(time.time())
    patch = {
        "admin_reply_text": reply_text,
        "admin_reply_lang": "it",
        "admin_reply_i18n": {
            lg: (result.get(lg) or {}).get("reply", "")
            for lg in community_translator.LANGS
        },
        "admin_reply_at": now,
    }
    try:
        community_store.feedback().update(item_id, patch)
    except Exception as e:
        print(f"[feedback-reply] persist failed for {item_id}: {e!s}")
        return jsonify({"error": "persist failed"}), 500
    return jsonify({"ok": True, "at": now})
```

- [ ] **Step 2: Verify syntax**

Run: `python -m py_compile audiobook_app.py`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add audiobook_app.py
git commit -m "feat(admin): add POST /admin/api/feedback/<item_id>/reply endpoint"
```

---

## Task 2: Backend — Include admin reply fields in public GET /api/community/feedback

**Files:**
- Modify: `audiobook_app.py:3023-3031` (public_items append in GET /api/community/feedback)

- [ ] **Step 1: Add admin_reply fields to the public_items dict**

In `audiobook_app.py` around line 3023, find the `public_items.append(...)` block inside `GET /api/community/feedback` and add the 4 admin_reply fields:

Change from:
```python
    public_items.append({
        "id": it.get("id"),
        "rating": it.get("rating"),
        "name": it.get("name") or "",
        "comment": it.get("comment") or "",
        "comment_lang": it.get("comment_lang") or "",
        "comment_i18n": it.get("comment_i18n") or {},
        "created_at": it.get("created_at", 0),
    })
```

To:
```python
    public_items.append({
        "id": it.get("id"),
        "rating": it.get("rating"),
        "name": it.get("name") or "",
        "comment": it.get("comment") or "",
        "comment_lang": it.get("comment_lang") or "",
        "comment_i18n": it.get("comment_i18n") or {},
        "created_at": it.get("created_at", 0),
        "admin_reply_at": it.get("admin_reply_at", 0),
        "admin_reply_lang": it.get("admin_reply_lang") or "",
        "admin_reply_text": it.get("admin_reply_text") or "",
        "admin_reply_i18n": it.get("admin_reply_i18n") or {},
    })
```

- [ ] **Step 2: Verify syntax**

Run: `python -m py_compile audiobook_app.py`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add audiobook_app.py
git commit -m "feat(api): include admin_reply fields in GET /api/community/feedback"
```

---

## Task 3: Admin UI — Add reply button and modal to Feedback tab

**Files:**
- Modify: `audiobook_app.py:3279-3395` (inline JS in admin_community_page)

- [ ] **Step 1: Add reply button to the feedback table rows**

In the feedback table row rendering (around line 3378), after the existing action buttons (Archive, Delete), add a "Rispondi" button for items that have no reply yet.

In the `tb.innerHTML=` template inside `loadFb()`, find this section:
```javascript
      <td>
        <button class="sm secondary" data-id="${it.id}" data-act="${it.archived?'unarchive':'archive'}">${it.archived?'Riattiva':'Archivia'}</button>
        <button class="sm danger" data-id="${it.id}" data-act="delete">Elimina</button>
      </td>
```

Replace the `<td>` content with:
```javascript
      <td>
        ${it.admin_reply_at > 0
          ? `<span style="font-size:.8rem;color:var(--muted)">${fmtDate(it.admin_reply_at)}</span>`
          : `<button class="sm" style="background:var(--accent)" data-id="${it.id}" onclick="openReplyModal(this)">Rispondi</button>`
        }
        <button class="sm secondary" data-id="${it.id}" data-act="${it.archived?'unarchive':'archive'}">${it.archived?'Riattiva':'Archivia'}</button>
        <button class="sm danger" data-id="${it.id}" data-act="delete">Elimina</button>
      </td>
```

- [ ] **Step 2: Add modal HTML and openReplyModal JS function**

Find the `</style>` tag in the HTML (around line 3271) and add modal CSS before it:
```css
.reply-modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:999}
.reply-modal{background:var(--panel);border-radius:12px;padding:24px;max-width:500px;width:90%;max-height:90vh;overflow-y:auto}
.reply-modal h3{margin:0 0 16px;font-size:1.1rem;color:var(--accent)}
.reply-modal textarea{width:100%;min-height:120px;resize:vertical;font:inherit}
.reply-modal .chars{margin-top:6px;font-size:.75rem;color:var(--muted);text-align:right}
.reply-modal .err{color:var(--err);margin:10px 0;font-size:.85rem}
.reply-modal-btns{display:flex;gap:10px;margin-top:14px;justify-content:flex-end}
```

- [ ] **Step 3: Add modal HTML and JS functions before `</body>`**

Find the `</body>` closing tag in the HTML (line ~3455) and add before it:
```html
<div class="reply-modal-overlay" id="replyModal" hidden>
  <div class="reply-modal">
    <h3>Rispondi al commento</h3>
    <div id="replyOriginal" style="font-size:.85rem;color:var(--muted);margin-bottom:12px;padding:8px;background:#0f172a;border-radius:6px;max-height:100px;overflow-y:auto"></div>
    <textarea id="replyText" maxlength="2000" placeholder="Scrivi la risposta in italiano..." rows="5"></textarea>
    <div class="chars"><span id="replyCharCount">0</span>/2000</div>
    <div class="err" id="replyErr" hidden></div>
    <div class="reply-modal-btns">
      <button class="secondary" onclick="closeReplyModal()">Annulla</button>
      <button id="replySubmit" onclick="submitReply()">Invia risposta</button>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Add JS functions after the existing `loadFb` function definition**

Find the end of `loadFb` function (around line 3395) and after the `loadFb();` call at line 3453, add:

```javascript
let _replyItemId = null;
function openReplyModal(btn){
  const id = btn.dataset.id;
  _replyItemId = id;
  const item = (window._fbItems || []).find(it => it.id === id);
  if(!item){return;}
  document.getElementById('replyOriginal').textContent =
    ((item.comment_i18n||{}).it)||item.comment||'(senza commento)';
  document.getElementById('replyText').value = '';
  document.getElementById('replyCharCount').textContent = '0';
  document.getElementById('replyErr').hidden = true;
  document.getElementById('replyModal').hidden = false;
  document.getElementById('replyText').focus();
}
function closeReplyModal(){
  document.getElementById('replyModal').hidden = true;
  _replyItemId = null;
}
document.getElementById('replyText').addEventListener('input',function(){
  document.getElementById('replyCharCount').textContent = this.value.length;
});
async function submitReply(){
  if(!_replyItemId) return;
  const text = document.getElementById('replyText').value.trim();
  if(!text){document.getElementById('replyErr').textContent='Testo richiesto';document.getElementById('replyErr').hidden=false;return;}
  if(text.length > 2000){document.getElementById('replyErr').textContent='Max 2000 caratteri';document.getElementById('replyErr').hidden=false;return;}
  const btn = document.getElementById('replySubmit');
  btn.disabled = true;
  const errEl = document.getElementById('replyErr');
  errEl.hidden = true;
  try {
    const r = await fetch('/admin/api/feedback/'+_replyItemId+'/reply',{
      method:'POST', headers:HDR,
      body:JSON.stringify({reply:text})
    });
    const d = await r.json().catch(()=>({}));
    if(!r.ok){
      errEl.textContent = d.error || ('Errore '+r.status);
      errEl.hidden = false;
    } else {
      closeReplyModal();
      loadFb();
    }
  } catch(e){
    errEl.textContent = 'Errore di rete';
    errEl.hidden = false;
  } finally {
    btn.disabled = false;
  }
}
```

- [ ] **Step 5: Store items globally for modal access**

In `loadFb()`, after `const items = d.items || [];`, add:
```javascript
  window._fbItems = items;
```

- [ ] **Step 6: Verify syntax**

Run: `python -m py_compile audiobook_app.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add audiobook_app.py
git commit -m "feat(admin): add reply UI to Feedback tab in /admin/community"
```

---

## Task 4: Public Frontend — Show admin reply under user comment

**Files:**
- Modify: `static/js/app.js:2851-2892` (renderRecent function)

- [ ] **Step 1: Add admin reply rendering in renderRecent**

In `renderRecent(items)` around line 2876 (after `attachI18nToggle(...)` and before `const delBtn=...`), add admin reply rendering:

Find:
```javascript
      attachI18nToggle(div.querySelector('.fbw-i18n-btn'),body,info);
      const delBtn=div.querySelector('.fbw-del-btn');
```

Replace with:
```javascript
      attachI18nToggle(div.querySelector('.fbw-i18n-btn'),body,info);
      // Admin reply
      if(it.admin_reply_at > 0){
        const replyDiv=document.createElement('div');
        replyDiv.className='fbw-admin-reply';
        const replyText=it.admin_reply_text||'';
        const replyI18n=it.admin_reply_i18n||{};
        const replyLang=it.admin_reply_lang||'it';
        const replyContent=replyI18n[C_LANG]||replyI18n['it']||replyText;
        replyDiv.innerHTML=`<div class="fbw-admin-reply-head"><span class="fbw-admin-badge">Admin</span><span class="fbw-comment-date">${fmtDate(it.admin_reply_at)}</span></div><p class="fbw-admin-reply-body">${escHtml(replyContent)}</p>`;
        div.appendChild(replyDiv);
      }
      const delBtn=div.querySelector('.fbw-del-btn');
```

- [ ] **Step 2: Add C_LANG helper and escHtml helper at top of renderRecent**

In `renderRecent` function, add these two helpers at the start of the function body:
```javascript
  const C_LANG = document.documentElement.lang || 'it';
  function escHtml(s){return (s||'').replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));}
```

- [ ] **Step 3: Add CSS for fbw-admin-reply in the styles**

Find the style block in `html_head.html` around line 564 or search for `fbw-comment` class in the CSS and add:

```css
.fbw-admin-reply{margin-top:12px;padding:10px 12px;background:rgba(139,92,246,.1);border-radius:8px;border-left:3px solid #8b5cf6}
.fbw-admin-reply-head{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.fbw-admin-badge{background:#8b5cf6;color:#fff;padding:1px 7px;border-radius:999px;font-size:.7rem;font-weight:700}
.fbw-admin-reply-body{margin:0;font-size:.9rem;color:#c4b5fd}
```

- [ ] **Step 4: Verify app.js syntax**

Run: `python -m py_compile static/js/app.js` (Python can't validate JS, but check for obvious syntax errors by looking for balanced braces in the modified section)

Alternative: use a JS linter or check manually.

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js templates/_fragments/html_head.html
git commit -m "feat(feedback): render admin reply under user comment in public widget"
```

---

## Verification Checklist

After all tasks:

- [ ] `python -m py_compile audiobook_app.py` — no errors
- [ ] `POST /admin/api/feedback/<item_id>/reply` with empty body → 400
- [ ] `POST /admin/api/feedback/<item_id>/reply` with reply > 2000 chars → 400
- [ ] `POST /admin/api/feedback/<item_id>/reply` on already-replied item → 409
- [ ] `GET /api/community/feedback` includes `admin_reply_at`, `admin_reply_lang`, `admin_reply_text`, `admin_reply_i18n` fields
- [ ] Admin `/admin/community` shows "Rispondi" button for items without reply
- [ ] Admin `/admin/community` shows timestamp instead of button for items with reply
- [ ] Public feedback widget shows admin reply under user comment (with Admin badge, translated per browser lang, fallback to Italian)
- [ ] LLM fallback: if `admin_reply_i18n[lang]` is empty, shows `admin_reply_text` (Italian)