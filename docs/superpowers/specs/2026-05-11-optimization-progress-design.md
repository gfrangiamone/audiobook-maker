# Design: Distribuzione del Progresso di Ottimizzazione AI

Data: 2026-05-11

## Problema

La barra di avanzamento dell'ottimizzazione AI rimane ferma al 99% per molto tempo. Questo accade perché:
1. Il frontend applica un `cap` a 99% finché non arriva il messaggio `status === 'optimized'` (app.js:1391).
2. Il backend ha già finito l'elaborazione dei capitoli, ma sta eseguendo attività finali (generazione .abm, invio email, aggiornamento stato) senza inviare messaggi di progresso intermedi.

L'utente percepisce un blocco a 99% anche se il sistema sta ancora lavorando.

## Obiettivo

Distribuire il 100% della barra di avanzamento tra:
- Elaborazione capitoli (la maggior parte).
- Attività di finalizzazione (generazione .abm, aggiornamento stato, eventuale invio email).

In modo che la percentuale scenda progressivamente verso il 100% senza stalli artificiali.

## Approccio Scelto: Pesi Estesi su Caratteri (Variante A — Percentuale Fissa)

Il backend estende il denominatore del progresso con un peso di finalizzazione calcolato come percentuale fissa dei caratteri totali, con un minimo assoluto.

### Formula

```python
FINALIZATION_WEIGHT = max(MIN_FINALIZATION_CHARS, total_chars * FINALIZATION_RATIO)
```

Dove:
- `FINALIZATION_RATIO = 0.03` (3% dei caratteri totali).
- `MIN_FINALIZATION_CHARS = 3000` (minimo equivalente a ~600 parole di un capitolo piccolo).

Il totale esteso diventa:
```python
total_chars_extended = total_chars + FINALIZATION_WEIGHT
```

### Data Flow

1. **Inizio ottimizzazione** — il backend calcola `total_chars_extended` e lo salva in `job["opt_total_chars_extended"]`.
2. **Durante i capitoli** — `opt_processed_chars` viene incrementato normalmente (come ora). La percentuale frontend è `processed / total_chars_extended`.
3. **Fase di finalizzazione** — dopo l'ultimo capitolo, il backend esegue le attività finali e incrementa `opt_processed_chars` verso `total_chars_extended`:
   - 30% del `FINALIZATION_WEIGHT` durante la generazione .abm.
   - 70% del `FINALIZATION_WEIGHT` durante l'invio email / aggiornamento stato finale.
   - Ogni step emette un messaggio SSE con `opt_progress_message` aggiornato.
4. **Completamento** — quando `opt_processed_chars >= total_chars_extended`, la percentuale frontend arriva a 100% e lo status passa a `"optimized"`.

### Modifiche ai File

| File | Modifica |
|------|----------|
| `generation_engine.py` | Aggiungere costanti `FINALIZATION_RATIO = 0.03`, `MIN_FINALIZATION_CHARS = 3000`. Calcolare `total_chars_extended` all'inizio di `run_optimization`. Durante la finalizzazione, emettere progresso SSE intermedi e incrementare `opt_processed_chars`. |
| `app.js` | Rimuovere `Math.min(99, ...)` al calcolo della percentuale (linea 1391). Sostituire con `Math.min(100, Math.round(workedChars / totalChars * 100))`. Usare `opt_total_chars_extended` se disponibile, altrimenti fallback su `opt_total_chars`. |

### Error Handling

- Se la generazione .abm fallisce: si logga l'errore, ma il progresso continua a 70% del peso di finalizzazione. Il job termina comunque a 100% con stato `"optimized"`.
- Se l'invio email fallisce: stesso comportamento — progresso arriva a 100%, stato `"optimized"`, errore loggato.
- L'utente non vede mai la barra bloccata al 99% per un errore non critico.

### Testing

1. Test manuale con un libro piccolo (1 capitolo, ~2000 parole): la barra deve salire velocemente durante il capitolo e completare l'ultimo 3% durante la finalizzazione.
2. Test manuale con un libro grande (20+ capitoli): il peso di finalizzazione rimane ~3% del totale, quindi la distribuzione è proporzionata.
3. Verifica che l'ETA rimanga significativa: la velocità `cps` è calcolata sui caratteri effettivamente processati, quindi la base di calcolo è coerente.

### Note Implementative

- Non è necessario modificare la struttura dei messaggi SSE: `opt_processed_chars`, `opt_total_chars` e `opt_progress_message` sono sufficienti.
- Il frontend deve solo usare il nuovo totale esteso quando disponibile.
- Retrocompatibilità: se il backend vecchio non invia `opt_total_chars_extended`, il frontend usa `opt_total_chars` e mantiene il vecchio comportamento (con cap a 99).