# Admin kill job da /admin/log-activity — Design

Data: 2026-06-04 · Stato: approvato

## Obiettivo

L'admin può interrompere un job in corso (generazione TTS o ottimizzazione AI)
direttamente dal pannello `/admin/log-activity`, con conferma esplicita che
chiarisce gli effetti in termini di rimborso all'utente.

## Decisioni

- **Scope**: job in stato `generating` (→ `POST /api/cancel/<sid>?force=1`) e
  `optimizing` (→ `POST /api/cancel_optimize/<sid>`).
- **Politica refund**: identica al cancel utente — nessuna nuova logica
  money-critical. Gemini trattiene i costi già sostenuti (no bonus);
  ottimizzazione LLM rimborsa l'intero importo (voucher: riaccredito
  sull'originale; PayPal: voucher di rimborso via email, senza bonus su cancel).
- Il guard persistente `payment.has_refund_for_job` evita refund duplicati.

## Backend

- Endpoint esistenti riusati: `cancel` (bypass admin lock Gemini + guard email
  con `force=1` + auth admin), `cancel_optimize`, `cancel_preview` (admin
  bypass già in `_check_job_owner`).
- Unica aggiunta: riga activity `ADMIN_CANCEL` quando il cancel è innescato da
  un caller admin (in `api_cancel` e `api_cancel_optimize`), per tracciabilità
  nel pannello stesso.
- Auth: cookie HttpOnly `abm_admin_session` (automatico nei fetch della
  pagina); fallback header `X-Admin-Token`.

## Frontend (/admin/log-activity)

- Bottone "⛔ Interrompi" sulle card `card-in-progress`, visibile solo per
  status `generating`/`optimizing` (il polling `updateLiveProgress` già
  distingue gli stati).
- Click → `GET /api/cancel_preview/<sid>` → modale di conferma con:
  - file, job_id, tipo operazione, progresso %;
  - importo pagato e metodo;
  - effetti refund espliciti (non pagato → nessun rimborso; ottimizzazione →
    rimborso integrale; Gemini → al netto costi, senza bonus; nota guard
    anti-duplicato).
- Conferma → POST endpoint corretto → toast esito; card aggiornata dal polling
  esistente (5s). Errori (409/terminato) nel toast.

## Test

- `test_cancel_endpoint_lock.py` copre già il bypass admin.
- Nuovo test: riga `ADMIN_CANCEL` loggata su cancel admin, non su cancel utente.
