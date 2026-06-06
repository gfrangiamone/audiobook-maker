# Email completamento — dettagli di generazione (Design)

Data: 2026-06-06 · Branch: main · Stato: approvato

## Obiettivo

Arricchire l'email "Il tuo audiolibro è pronto" con i parametri di generazione,
subito sotto il paragrafo body esistente.

## Contenuto del blocco dettagli

Helper `_email_generation_details(job, lang) -> str` (HTML), frasi composte:

1. **Sempre** — "Hai generato questo audiolibro in lingua **{codice ISO}**
   utilizzando **{Voci Standard | Voci PREMIUM}**." Una sola delle due etichette,
   quella effettiva (`_is_gemini_voice(voice)`). Codice lingua: dal locale della
   voce edge (`it-IT-IsabellaNeural` → `it-IT`); per PREMIUM dal campo lingua del
   job (se assente al generate, salvarlo lì — modifica minima).
2. **Sempre** — "Hai scelto la voce **{nome amichevole}** a velocità
   **{normale | +10% | -20% …}**." Nome derivato dall'ID: edge = segmento finale
   senza suffisso "Neural" (camelCase → spazi, es. "Andrew Multilingual");
   PREMIUM = ultimo token (`gemini:flash25:Zephyr` → "Zephyr"). Rate "+0%" →
   "normale" (localizzato); altrimenti valore raw.
3. **Solo PREMIUM** — "Hai utilizzato il modello **{Gemini Flash 2.5 TTS |
   Gemini Flash 3.1 TTS}**." Mappa `flash25`/`flash31`; id modello sconosciuto →
   frase omessa.
4. **Solo PREMIUM e solo se valorizzate** — "Istruzioni di stile: \"{testo}\"."
   Testo utente → `html.escape` obbligatorio.
5. **Sempre** — "Il testo è stato ottimizzato con l'AI prima della generazione
   audio." / "Il testo non è stato ottimizzato con l'AI." (`job["ai_optimized"]`).

## i18n

Nuove chiavi con placeholder `{...}` nelle 7 lingue di `_email_i18n`
(it/en/fr/es/de/pt/zh), formattate in Python (`str.format`). Nomi modello e
codici ISO identici in tutte le lingue. Entità HTML per gli accenti, come le
chiavi esistenti.

## Vincoli

- Solo `_send_completion_email` (non email ottimizzazione né traduzione).
- Helper difensivo: campo mancante ⇒ frase omessa, mai email rotta
  (try/except attorno alla composizione; su errore blocco vuoto).
- Deroga naming provider: nelle EMAIL i modelli TTS PREMIUM usano il nome reale
  ("Gemini Flash 2.5 TTS"); nella UI web restano le etichette generiche.

## Test

Unit su `_email_generation_details`: standard vs premium; rate +0% vs +10%;
stile presente/assente + escaping HTML; ai_optimized true/false; lingua email
sconosciuta → fallback en; voce malformata → blocco senza crash.
