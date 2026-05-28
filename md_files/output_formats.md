# Output Format Flow

Documento di riferimento per il modo in cui il parametro `output_format` propagato dal frontend pilota la generazione audio nel backend e quali pulsanti di download appaiono al termine.

## 1. Formati disponibili

| Formato | Contenitore | Caratteristiche |
|---------|-------------|-----------------|
| **MP3** | MP3 48 kbps mono (default edge-tts) | File unico (concat di tutti i capitoli) |
| **M4B** | MPEG-4 audiobook | Capitoli embedded, cover 1400×1400, metadati iTunes. Richiede FFmpeg. Validato via `ffprobe`. |
| **ZIP** | Archivio chapter MP3 | Un MP3 per capitolo, cover inclusa |
| **Podcast RSS** | iTunes/PSP-1 XML | Enclosures per capitolo, formato podcast privato |
| **ABM** | ZIP archivio "optimized book" | Manifest + testi capitoli ottimizzati + cover; re-importabile come progetto |

Note:
- ABM è generato solo durante l'ottimizzazione AI del testo, **non** durante la generazione TTS.
- M4B è prodotto solo quando `output_format == 'm4b'` (skipped per `mp3`, `zip`, `zip_rss`).

## 2. Derivazione frontend (`templates/_fragments/app.js:373`)

```js
singleFile = (outputFormat === 'm4b' || outputFormat === 'mp3')
```

Il campo URL podcast è visibile **solo** quando `outputFormat === 'zip_rss'`.

## 3. Dispatch backend (`generation_engine.py:run_generation`)

| `output_format` | `singleFile` | Audio prodotto | ZIP | M4B | RSS | Flag `podcast_ready` |
|-----------------|--------------|----------------|-----|-----|-----|----------------------|
| `m4b`           | true  | 1 MP3 unico (concat tutti i capitoli) | — | ✅ FFmpeg + capitoli + cover 1400×1400 | — | false |
| `mp3`           | true  | 1 MP3 unico (concat tutti i capitoli) | — | — | — | false |
| `zip`           | false | 1 MP3 per capitolo | ✅ capitoli + cover | — | — | false |
| `zip_rss`       | false | 1 MP3 per capitolo | ✅ capitoli + RSS + cover | — | ✅ XML pre-generato e incluso nello ZIP | true |

Punti chiave nel codice:
- M4B saltato per `output_format in ('mp3', 'zip', 'zip_rss')` (~`generation_engine.py:1500`).
- RSS generato ed embedded **solo** per `zip_rss` (~`generation_engine.py:1475–1492`); il flag `podcast_rss_included` viene impostato a true al successo.
- Cover normalizzata a 1400×1400 in `audio_utils.py` prima dell'embedding M4B.
- **Storage cleanup post-ZIP**: per `output_format in ('zip', 'zip_rss')`, subito dopo la creazione dello ZIP (~`generation_engine.py:2647–2675`) si verifica l'integrità con `zipfile.is_zipfile()` e si rimuovono i singoli MP3 da `output_dir` (sono pure duplicazioni del contenuto ZIP). Per `zip_rss` la purge avviene solo se `podcast_rss_included` è True (altrimenti il fallback in `/api/download_podcast` ricostruisce lo ZIP dai singoli MP3). `job["podcast_mp3s"]` mantiene comunque la lista dei path originali per logging/audit, ma i file fisici sono assenti — non è un problema perché il download serve lo ZIP direttamente.

## 4. Pulsanti di download post-generazione (`templates/_fragments/app.js:1620–1650`)

Tutti i pulsanti sono nascosti per default; vengono mostrati condizionalmente in base a `output_format` e alla presenza di `.abm`.

| `output_format` | `btnD` (id=btnD) | `btnP` (id=btnP) | `btnA` (id=btnA) |
|-----------------|------------------|------------------|------------------|
| `m4b`           | "Scarica audiolibro (M4B)" → `downloadFile('m4b')` | hidden | mostrato solo se ottimizzazione AI completata (`has_abm`) |
| `mp3`           | "Scarica audiolibro (MP3)" → `downloadFile('mp3')` | hidden | idem |
| `zip`           | "Scarica audiolibro (ZIP)" → `downloadFile('zip')` | hidden | idem |
| `zip_rss`       | **hidden** | "Scarica podcast" → `downloadPodcastZip()` → `/api/download_podcast/{job_id}` | idem |

### Regole vincolanti

- **`btnM`** ("Scarica M4B") è stato **rimosso** dal markup: in modalità M4B duplicava `btnD`, negli altri casi era sempre nascosto.
- **`btnA`** ("Scarica .ABM") appare **solo** quando `has_abm` è true, condizione valutata server-side come:
  `job["ai_optimized"]` **OR** presenza fisica di `.abm` su disco (`audiobook_app.py:3169`). È supplementare al pulsante primario.
- **`btnP`** usa l'endpoint dedicato `/api/download_podcast/{job_id}`:
  - Se `podcast_rss_included` è true → serve direttamente lo ZIP pre-costruito.
  - Altrimenti richiede `base_url` per rigenerare RSS on-the-fly.
- **`btnD`** è il download primario per `m4b`/`mp3`/`zip`. È **l'unico** pulsante mostrato quando non è stata fatta ottimizzazione AI.

## 5. Tabella incrociata "cosa vedo a fine job"

| Caso d'uso | Pulsanti visibili |
|------------|-------------------|
| `mp3` senza AI | `btnD (MP3)` |
| `mp3` + AI | `btnD (MP3)` + `btnA (ABM)` |
| `m4b` senza AI | `btnD (M4B)` |
| `m4b` + AI | `btnD (M4B)` + `btnA (ABM)` |
| `zip` senza AI | `btnD (ZIP)` |
| `zip` + AI | `btnD (ZIP)` + `btnA (ABM)` |
| `zip_rss` senza AI | `btnP (Podcast)` |
| `zip_rss` + AI | `btnP (Podcast)` + `btnA (ABM)` |

## 6. Errori e degradazione

| Componente | Retry | Fallback |
|------------|-------|----------|
| M4B conversion (FFmpeg) | 2 tentativi | MP3 (o ZIP) consegnati comunque; flag `m4b_failed` settato |
| RSS embedding nello ZIP | — | Se `podcast_rss_included` non viene settato, `/api/download_podcast` rigenera l'XML on-the-fly (richiede `ABM_BASE_URL`) |
| Cover non disponibile | — | M4B/ZIP generati senza cover; processo non bloccato |

Il principio operativo è "fail-soft sui formati derivati": l'output audio base (MP3/ZIP) non viene mai bloccato dal fallimento di una post-produzione (M4B, RSS).

## 7. Riferimenti puntuali al codice

- Frontend: `templates/_fragments/app.js`
  - `singleFile` derivation: `~:373`
  - Completion panel buttons: `~:1620–1650`
- Backend: `generation_engine.py`
  - `run_generation()` dispatch
  - RSS embedding: `~:1475–1492`
  - M4B gating: `~:1500`
- Endpoint download:
  - `/api/download/{job_id}` (generico, m4b/mp3/zip)
  - `/api/download_podcast/{job_id}` (zip_rss dedicato)
  - `/dl/{token}` + `/dl/{token}/m4b` + `/dl/{token}/abm` (modalità batch email)
- ABM presence check: `audiobook_app.py:~3169`

## 8. Quando consultare questo documento

Toccare logica `output_format`, mapping format → pulsanti, embedding M4B/RSS, endpoint `/api/download*`, ZIP packaging, ABM export, regole di visibilità dei pulsanti di download.
