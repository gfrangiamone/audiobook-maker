# Admin Reply to User Feedback — Design

**Data:** 2026-05-13
**Feature:** Admin risponde ai commenti utente nella sezione Community del sito.

---

## 1. Obiettivo e sommario

L'admin scrive la risposta in italiano dall'interfaccia `/admin/community`. Il sistema la traduce automaticamente in tutte le 7 lingue UI (it/en/fr/es/de/zh/hi) via DeepSeek LLM, con stored one-shot. La risposta viene mostrata sotto il commento utente nel frontend, nella lingua scelta dal browser del visitatore.

---

## 2. Architettura dati

### Aggiornamento `feedback.json` — item schema

Ogni feedback item guadagna tre campi:

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `admin_reply_text` | `str` | Testo originale della risposta (sempre in italiano) |
| `admin_reply_i18n` | `dict[str, str]` | Dizionario lingue: `{"it": "", "en": "", "fr": "", "es": "", "de": "", "zh": "", "hi": ""}` |
| `admin_reply_lang` | `str` | Lingua sorgente, sempre `"it"` |
| `admin_reply_at` | `int` | Unix timestamp pubblicazione risposta, `0` se non pubblicata |

### Comportamento

- Una risposta per commento (singola, non modificabile dopo pubblicazione, non eliminabile).
- Una volta pubblicata la risposta, il campo `admin_reply_text` è definivo.
- L'admin scrive in italiano; `community_translator.translate()` genera `admin_reply_i18n` per tutte le 7 lingue.

---

## 3. Flusso — Backend

### 3.1 Endpoint `POST /admin/api/feedback/<item_id>/reply`

**Autenticazione:** admin token via `X-Admin-Token` header.

**Request body (JSON):**
```json
{ "reply": "Testo della risposta admin in italiano." }
```

**Validazioni:**
- `reply` deve essere stringa non vuota, max 2000 caratteri, stripped.
- Se `admin_reply_at > 0` → errore `409 Conflict` ("reply already posted").

**Processo:**
1. Validazione input.
2. Chiamata a `community_translator.translate({"reply": reply_text})` con `timeout=90s`.
3. Se LLM non disponibile → errore `503`.
4. Se traduzione fallisce → errore `500` ("translation failed").
5. `patch = {"admin_reply_text": reply_text, "admin_reply_lang": "it", "admin_reply_i18n": {lg: result[lg]["reply"] for lg in LANGS}, "admin_reply_at": int(time.time())}`.
6. `community_store.feedback().update(item_id, patch)`.
7. Risposta `200` con `{"ok": true, "at": admin_reply_at}`.

### 3.2 Aggiornamento `GET /api/community/feedback` (pubblico)

I campi `admin_reply_text`, `admin_reply_i18n`, `admin_reply_lang`, `admin_reply_at` vengono inclusi nell'output pubblico per ogni item. Questo è il solo cambiamento all'endpoint esistente.

---

## 4. Flusso — Frontend Admin

### 4.1 UI tab Feedback (`/admin/community`)

Nella tabella feedback, ogni riga mostra:

- **Se `admin_reply_at == 0`**: un pulsante "Rispondi" che apre un modal/textarea per comporre la risposta.
- **Se `admin_reply_at > 0`**: la risposta in italiano (admin_reply_text) con timestamp, senza azioni.

### 4.2 Modal "Rispondi"

- Textarea con max 2000 caratteri e counter.
- Pulsante "Invia risposta" → `POST /admin/api/feedback/<item_id>/reply`.
- Loading state durante la chiamata.
- In caso di errore: messaggio visibile, retry possibile.
- Il modal NON si chiude su errore — l'admin può correggere e ritentare.

### 4.3 Feedback list refresh

Dopo l'invio riuscito, la riga si aggiorna mostrando la risposta e il timestamp.

---

## 5. Flusso — Frontend Pubblico

### 5.1 Sezione Feedback (widget community)

Per ogni item con `admin_reply_at > 0`:
- La risposta admin appare **sotto** il commento utente.
- Separatore visivo (border-top, background leggermente diverso).
- Badge testuale "Admin" con colore accentato.
- Testo mostrato: `admin_reply_i18n[lang] || admin_reply_text` (fallback italiano se traduzione mancante).

### 5.2 Lingua di visualizzazione

- `lang = detected from browser (it/en/fr/es/de/zh/hi)`, default `it`.
- Se `admin_reply_i18n[lang]` è vuoto, fallback a `admin_reply_text` (italiano).

---

## 6. Dipendenze e riutilizzo

| Componente | Riutilizzo |
|------------|------------|
| `community_translator.translate()` | Già esistente, stesso prompt/pattern |
| `community_store.feedback()` | Già esistente, `update()` usato per archive/unarchive |
| `JsonStore.update()` | Aggiunge campi senza toccare esistenti |
| `LANGS` costante | `community_translator.LANGS` |

Nessuna modifica a `community_moderator.py` o `community_store.py` (solo utilizzo di metodi esistenti).

---

## 7. Edge case e gestione errori

| Scenario | Comportamento |
|----------|---------------|
| LLM non configurato | Errore 503 + messaggio "LLM non disponibile" |
| Traduzione LLM fallisce | Errore 500 + messaggio "Traduzione fallita, ritenta" |
| Risposta già pubblicata | Errore 409 + "Risposta già inviata" |
| Item non trovato | Errore 404 |
| `admin_reply_i18n[lang]` vuoto | Fallback a `admin_reply_text` (italiano) |
| Testo > 2000 chars | Reject con errore 400 |

---

## 8. File da modificare

| File | Modifiche |
|------|-----------|
| `audiobook_app.py` | Nuovo endpoint `POST /admin/api/feedback/<item_id>/reply`; aggiunta campi reply in `GET /api/community/feedback`; aggiunta UI nel tab Feedback admin |
| `i18n/*.json` | Aggiungere chiavi per label "Admin", "Rispondi", "Risposta admin" (opzionale, la UI è admin-only) |

Nessun nuovo file Python. Nessuna modifica a moduli esistenti (community_store, community_translator, community_moderator).

---

## 9. Sommario implementazione

1. **Backend endpoint** — `POST /admin/api/feedback/<item_id>/reply` con traduzione LLM one-shot e persistenza `admin_reply_*`.
2. **Update public endpoint** — `GET /api/community/feedback` include i 4 campi reply.
3. **Admin UI** — pulsante "Rispondi" + modal textarea nel tab Feedback.
4. **Frontend pubblico** — reply admin sotto commento utente con fallback lingua.

---

## 10. Approvazione

Design approvato dall'utente. Procedere con scrittura del piano di implementazione.