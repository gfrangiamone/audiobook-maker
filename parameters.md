# Parametri funzionali temporali - audiobook_app.py

## 1. Costanti di configurazione (hardcoded)

| Parametro | Riga | Valore | Descrizione |
|---|---|---|---|
| `EMAIL_FILE_RETENTION_SEC` | 97 | `86400` (24h) | Retention dei file dopo invio email |
| `ADMIN_DIGEST_INTERVAL_SEC` | 104 | `21600` (6h) | Intervallo minimo tra un digest admin e il successivo |
| `_CLIENT_COOKIE_MAX_AGE` | 116 | `31536000` (1 anno) | Durata del cookie di identificazione client |
| `CHAPTER_SILENCE_SEC` | 1595 | `3` | Secondi di silenzio inseriti all'inizio di ogni capitolo |
| `CLEANUP_GRACE_AFTER_DOWNLOAD_SEC` | 3849 | `300` (5 min) | Grazia dopo download diretto prima di cancellare i file |
| `CLEANUP_HEARTBEAT_TIMEOUT_SEC` | 3850 | `60` (1 min) | Timeout heartbeat: se il browser non fa poll per 60s, e' considerato chiuso |
| `CLEANUP_INTERVAL_SEC` | 3851 | `60` (1 min) | Frequenza del ciclo di pulizia in background |
| `CLEANUP_ORPHAN_DIR_AGE_SEC` | 3852 | `7200` (2h) | Eta' minima delle cartelle orfane prima della rimozione |

## 2. Timeout operativi

| Parametro | Riga | Valore | Descrizione |
|---|---|---|---|
| **SMTP timeout** | 246/251 | `30s` | Timeout connessione al server SMTP |
| **TTS preview timeout** | 2622 | `30s` | Timeout per la generazione dell'anteprima audio (via `concurrent.futures`) |
| **Heartbeat in-generation** | 961 | `60s` | Durante la generazione, se nessun poll per 60s -> job abbandonato (tollerante al throttling Chrome) |
| **Heartbeat cleanup (analyzed)** | 3890 | `180s` (60x3) | Per job in stato "analyzed", heartbeat moltiplicato x3 |

## 3. Retry e backoff TTS

| Parametro | Riga | Valore | Descrizione |
|---|---|---|---|
| **Exponential backoff** | 695-700 | `2^attempt` (1s, 2s, 4s) | Attesa tra i retry di edge-tts in caso di errore |
| **Silence fallback** | 676/684/705 | `1s` | Se tutti i retry falliscono, viene generato 1s di silenzio al posto del chunk |

## 4. Tempi calcolati/stimati

| Parametro | Riga | Formula | Descrizione |
|---|---|---|---|
| `estimated_duration_minutes` | 771/863 | `total_words / 150` | Stima della durata dell'audiobook in minuti (150 parole/min) |
| `elapsed_seconds` | 975/1079 | `time.time() - start_time` | Tempo trascorso dall'inizio della generazione |
| `duration_min` (log) | 2348 | `delta.total_seconds() / 60` | Durata sessione utente nei log/export |

## 5. Parametri temporali nel podcast RSS

| Parametro | Riga | Descrizione |
|---|---|---|
| `_mp3_duration_seconds()` | 1447 | Stima durata MP3 via ffprobe (o fallback da dimensione file) |
| `_fmt_duration()` | 1466 | Formatta durata in HH:MM:SS per il tag `<itunes:duration>` |
| `pub_date` offset | 1564 | Ogni episodio e' retrodatato di N ore (`now - timedelta(hours=...)`) per ordinarli |

## 6. Timer lato frontend (JavaScript embedded)

| Parametro | Riga | Valore | Descrizione |
|---|---|---|---|
| `setInterval(updateLiveTimers, 1000)` | 2311 | 1s | Aggiornamento live dei timer sessione in corso nella pagina log |
| `setTimeout(... 2000)` | 3255/3598 | 2s | Reset del testo del pulsante "Copia" / tooltip dopo 2 secondi |

## Riepilogo

L'applicazione gestisce circa 20 parametri temporali distinti, raggruppabili in:

- **Retention & cleanup**: 24h file email, 5min grazia post-download, 2h cartelle orfane, 60s ciclo pulizia
- **Heartbeat**: 60s (generazione), 180s (analyzed), 60s (cleanup)
- **Timeout**: 30s SMTP, 30s preview TTS
- **TTS retry**: backoff esponenziale 1/2/4s, silenzio fallback 1s
- **Audio**: 3s silenzio tra capitoli, stima durata a 150 wpm
- **Admin digest**: max 1 ogni 6 ore
- **Cookie**: durata 1 anno
