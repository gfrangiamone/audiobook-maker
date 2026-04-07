# Parametri di Configurazione - Audiobook Maker

Raccolta completa di tutti i parametri di funzionamento dell'applicazione, con indicazione del valore attuale/default, del file sorgente e della riga.

---

## 1. Variabili d'ambiente (prefisso `ABM_`)

Parametri configurabili dall'esterno tramite variabili d'ambiente sul server.

| Parametro | Valore default | File | Riga |
|-----------|---------------|------|------|
| `ABM_DATA_DIR` | `"/var/lib/audiobook-maker/data"` | `audiobook_app.py` | 77 |
| `ABM_SMTP_HOST` | `""` (vuoto) | `audiobook_app.py` | 91 |
| `ABM_SMTP_PORT` | `587` | `audiobook_app.py` | 92 |
| `ABM_SMTP_USER` | `""` (vuoto) | `audiobook_app.py` | 93 |
| `ABM_SMTP_PASS` | `""` (vuoto) | `audiobook_app.py` | 94 |
| `ABM_SMTP_FROM` | `SMTP_USER` oppure `"noreply@audiobook-maker.com"` | `audiobook_app.py` | 95 |
| `ABM_BASE_URL` | `""` (vuoto, con rstrip di `/`) | `audiobook_app.py` | 96 |
| `ABM_ADMIN_EMAIL` | `""` (vuoto, se vuoto il digest admin e' disabilitato) | `audiobook_app.py` | 103 |
| `ABM_MAX_CONCURRENT_PER_CLIENT` | `2` | `audiobook_app.py` | 112 |
| `ABM_GOOGLE_CREDENTIALS_FILE` | `""` (vuoto, oppure path al file JSON service account Google Cloud) | `google_tts.py` | 69 |
| `GOOGLE_APPLICATION_CREDENTIALS` | `""` (alternativa standard Google SDK al parametro sopra) | `google_tts.py` | 70 |
| `ABM_GOOGLE_TTS_MONTHLY_LIMIT` | `1000000` (1M caratteri/mese, free tier Google Cloud TTS) | `google_tts.py` | 33 |

---

## 2. Configurazione Flask

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `MAX_CONTENT_LENGTH` | `200 * 1024 * 1024` (200 MB) | `audiobook_app.py` | 73 |

---

## 3. Costanti applicative principali (`audiobook_app.py`)

### 3.1 Percorsi e directory

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `SCRIPT_DIR` | `Path(__file__).parent.resolve()` | `audiobook_app.py` | 33 |
| `UPLOAD_DIR` | `Path(_DATA_DIR)` (derivato da `ABM_DATA_DIR`) | `audiobook_app.py` | 78 |
| `_TOKENS_FILE` | `UPLOAD_DIR / "_download_tokens.json"` | `audiobook_app.py` | 157 |

### 3.2 Email e notifiche

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `SMTP_HOST` | da `ABM_SMTP_HOST` | `audiobook_app.py` | 91 |
| `SMTP_PORT` | da `ABM_SMTP_PORT` (int) | `audiobook_app.py` | 92 |
| `SMTP_USER` | da `ABM_SMTP_USER` | `audiobook_app.py` | 93 |
| `SMTP_PASS` | da `ABM_SMTP_PASS` | `audiobook_app.py` | 94 |
| `SMTP_FROM` | da `ABM_SMTP_FROM` o fallback | `audiobook_app.py` | 95 |
| `BASE_URL` | da `ABM_BASE_URL` (con rstrip) | `audiobook_app.py` | 96 |
| `EMAIL_FILE_RETENTION_SEC` | `86400` (24 ore) | `audiobook_app.py` | 97 |
| `ADMIN_EMAIL` | da `ABM_ADMIN_EMAIL` | `audiobook_app.py` | 103 |
| `ADMIN_DIGEST_INTERVAL_SEC` | `86400` (24 ore) | `audiobook_app.py` | 104 |

### 3.3 Rate limiting e tracking client

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `MAX_CONCURRENT_PER_CLIENT` | da `ABM_MAX_CONCURRENT_PER_CLIENT` (default `2`) | `audiobook_app.py` | 112 |
| `_CLIENT_COOKIE_NAME` | `"abm_cid"` | `audiobook_app.py` | 115 |
| `_CLIENT_COOKIE_MAX_AGE` | `31536000` (1 anno in secondi) | `audiobook_app.py` | 116 |

### 3.4 Generazione audio

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `CHUNK_MAX_CHARS` | `2000` (caratteri max per chunk TTS) | `audiobook_app.py` | 627 |
| `CHAPTER_SILENCE_SEC` | `3` (secondi di silenzio tra capitoli) | `audiobook_app.py` | 1595 |

### 3.5 Voci e lingue

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `LANGUAGE_NAMES` | Dict di 60+ codici lingua -> nomi | `audiobook_app.py` | 555 |

### 3.6 Cleanup (pulizia automatica)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `CLEANUP_GRACE_AFTER_DOWNLOAD_SEC` | `300` (5 min dopo download diretto) | `audiobook_app.py` | 3870 |
| `CLEANUP_HEARTBEAT_TIMEOUT_SEC` | `60` (heartbeat perso = browser chiuso) | `audiobook_app.py` | 3871 |
| `CLEANUP_INTERVAL_SEC` | `60` (check ogni 60 secondi) | `audiobook_app.py` | 3872 |
| `CLEANUP_ORPHAN_DIR_AGE_SEC` | `7200` (2 ore, cartelle orfane rimosse) | `audiobook_app.py` | 3873 |

### 3.7 SEO e template

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `_SEO_DATA` | Dict con dati SEO per 6 lingue (it, en, fr, es, de, zh) | `audiobook_app.py` | 3749 |
| `_SUPPORTED_LANGS` | `['it', 'en', 'fr', 'es', 'de', 'zh']` | `audiobook_app.py` | 3795 |
| `HTML_TEMPLATES` | Dict di template HTML pre-renderizzati per lingua | `audiobook_app.py` | 3799 |
| `HTML_TEMPLATE` | Fallback al template inglese | `audiobook_app.py` | 3809 |

---

## 4. Costanti di parsing EPUB (`epub_to_tts.py`)

### 4.1 Filtri HTML

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `TAGS_TO_REMOVE_WITH_CONTENT` | Set di 25 tag HTML scartati (script, style, nav, aside, footer, header, figcaption, figure, table, svg, math, code, pre, sup, sub, noscript, iframe, object, embed, canvas, form, input, select, textarea, button, map, area) | `epub_to_tts.py` | 48 |
| `BLOCK_TAGS` | Set di tag blocco: `p, div, h1-h6, li, blockquote, section, article, br, hr` | `epub_to_tts.py` | 57 |
| `HEADING_TAGS` | `{"h1", "h2", "h3", "h4", "h5", "h6"}` | `epub_to_tts.py` | 63 |

### 4.2 Filtri CSS e EPUB semantici

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `CLASSES_TO_SKIP` | Set di 40+ pattern di classi CSS da escludere | `epub_to_tts.py` | 66 |
| `EPUB_TYPES_TO_SKIP` | Set di 30+ tipi semantici EPUB3 da escludere | `epub_to_tts.py` | 94 |

### 4.3 Filtri filename

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `NON_CONTENT_FILENAMES_EXACT` | Set di 15+ nomi file esatti da escludere (toc, nav, cover, colophon...) | `epub_to_tts.py` | 112 |
| `NON_CONTENT_FILENAMES_SUBSTR` | Set di 8 sottostringhe filename da escludere | `epub_to_tts.py` | 120 |

### 4.4 Pulizia testo

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `LINE_SKIP_PATTERNS` | Lista di 5 regex per righe da saltare (numeri pagina, separatori...) | `epub_to_tts.py` | 127 |
| `NOISE_PATTERNS` | Lista di 18 coppie (regex, sostituzione) per pulizia inline | `epub_to_tts.py` | 138 |
| `ABBREVIATIONS` | Dict di 50+ abbreviazioni -> espansione per TTS naturale | `epub_to_tts.py` | 180 |

### 4.5 Marker di pausa TTS

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `CHAPTER_PAUSE` | `"\n\n...\n\n"` (pausa lunga tra capitoli) | `epub_to_tts.py` | 236 |
| `SECTION_PAUSE` | `"\n\n"` (pausa media tra sezioni) | `epub_to_tts.py` | 237 |

---

## 5. Costanti di parsing PDF (`pdf_to_tts.py`)

### 5.1 Soglie e margini

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `SMALL_TEXT_RATIO` | `0.85` (testo < 85% del body text = nota/didascalia, scartato) | `pdf_to_tts.py` | 110 |
| `HEADER_MARGIN_RATIO` | `0.08` (top 8% della pagina = header) | `pdf_to_tts.py` | 113 |
| `FOOTER_MARGIN_RATIO` | `0.08` (bottom 8% della pagina = footer) | `pdf_to_tts.py` | 114 |

### 5.2 Pattern di riconoscimento

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `CAPTION_PATTERNS` | Lista di 6 regex multilingua per didascalie figure/tabelle | `pdf_to_tts.py` | 117 |
| `NON_CONTENT_TITLES` | Set di 80+ titoli di sezioni non-contenuto da escludere (multilingua) | `pdf_to_tts.py` | 141 |
| `FOOTNOTE_SUPERSCRIPT_RE` | Regex compilata per footnote nel testo | `pdf_to_tts.py` | 180 |
| `PAGE_NUMBER_RE` | Regex compilata: `r"^\s*[-—–]?\s*\d{1,4}\s*[-—–]?\s*$"` | `pdf_to_tts.py` | 185 |
| `MIN_REPEAT_FOR_HEADER` | `3` (minimo ripetizioni per header/footer statistico) | `pdf_to_tts.py` | 188 |

---

## 6. Google Cloud TTS (`google_tts.py`)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `GOOGLE_TTS_MONTHLY_LIMIT` | `1000000` (da `ABM_GOOGLE_TTS_MONTHLY_LIMIT`) | `google_tts.py` | 33 |
| `VOICES_CACHE_TTL` | `3600` (1 ora, cache voci Google) | `google_tts.py` | 42 |
| `_usage_file_path` | `Path(data_dir) / "google_tts_usage.json"` | `google_tts.py` | 51 |
| `_MONITORING_STABILIZATION_LAG_SEC` | `900` (15 min, intervallo escluso dalle query Cloud Monitoring per usare solo metriche stabilizzate) | `google_tts.py` | 380 |
| `_MAX_CHARS_PER_REQUEST` | `2200` (bound massimo caratteri/richiesta TTS per sanity check, = `CHUNK_MAX_CHARS` + 10% tolleranza) | `google_tts.py` | 610 |

---

## 7. Versione (`version.py`)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `__version__` | `"3.5.0"` | `version.py` | 7 |
| `__updated_date__` | Dinamico: `datetime.now().strftime("%Y-%m")` | `version.py` | 10 |

---

## 8. SEO Content (`seo_content.py`)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `_URL_RE` | Regex compilata per rilevamento URL nel testo | `seo_content.py` | 31 |
| `_CONTENT` | Dict con contenuti SEO visibili per 6 lingue | `seo_content.py` | 43 |

---

## Riepilogo

| Categoria | Numero parametri |
|-----------|:---:|
| Variabili d'ambiente (`ABM_*`) | 12 |
| Configurazione Flask | 1 |
| Costanti applicative (`audiobook_app.py`) | 24 |
| Costanti parsing EPUB (`epub_to_tts.py`) | 12 |
| Costanti parsing PDF (`pdf_to_tts.py`) | 8 |
| Google Cloud TTS (`google_tts.py`) | 5 |
| Versione (`version.py`) | 2 |
| SEO Content (`seo_content.py`) | 2 |
| **Totale** | **66** |
