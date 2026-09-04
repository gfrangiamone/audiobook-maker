# Collaudo manuale — lingua del libro e cascata dei modelli

Da eseguire sull'istanza locale, con l'interfaccia in italiano, prima di
autorizzare il push.

Nota: in locale `_translate_available` è `false`, quindi il pulsante
«Traduci il libro» non compare da nessuna parte in questo documento. Non è
un difetto.

Le etichette citate qui sotto sono il testo che compare davvero
nell'interfaccia (locale `it`), preso da `templates/_fragments/i18n_data.js`
e dal DOM in `templates/_fragments/html_head.html` — non parafrasi.

## Prerequisiti

- App avviata in locale, wizard aperto fino al pannello «Impostazioni
  audio» (panel 3), lingua interfaccia italiano.
- Un EPUB con `dc:language` in italiano, uno in svedese, uno in spagnolo,
  uno in inglese. Bastano pochi capitoli ciascuno.
- Un file `.txt` breve, senza indicazioni di lingua nei metadati (i `.txt`
  non ne hanno mai) e abbastanza ambiguo da non farsi riconoscere dal
  rilevamento automatico — oppure con `ABM_LLM_API_KEY` non configurata sul
  processo locale, che disattiva del tutto il rilevamento.

## 1. Lingua dai metadati

1. Carica l'EPUB italiano.
2. Apri le Impostazioni audio.
   → _atteso: sulla riga sopra i tab compaiono, in sequenza — l'etichetta
   «Lingua del libro», il nome del libro in grassetto «Italiano», e accanto,
   in carattere più piccolo, «dai metadati». Nessuna combo per scegliere la
   lingua: solo l'icona ⚙ per forzarla._
3. Guarda il tab «Voci Standard (gratis)» (attivo di default).
   → _atteso: nessuna riga ACCENTO — l'italiano ha un solo locale nel
   catalogo gratuito — solo il menu VOCE._
4. Passa al tab «★ Voci PREMIUM».
   → _atteso: tre voci nel menu MODELLO, con «Audiobook Maker (VOXCPM2)»
   già selezionato._

## 2. Lingua senza voci PREMIUM

1. Carica l'EPUB svedese.
   → _atteso: il tab «★ Voci PREMIUM» è visibilmente spento (opacità
   ridotta, cursore "non permesso"), e sotto la barra dei tab compare
   l'avviso «Le voci PREMIUM non sono disponibili in Svedese.»_
2. Prova a cliccare sul tab spento.
   → _atteso: non succede nulla, resti sul tab «Voci Standard (gratis)» —
   è un `<button disabled>`, non riceve il click._

## 3. Molti accenti

1. Carica l'EPUB spagnolo, resta sul tab «Voci Standard (gratis)».
   → _atteso: compare la riga «Accento» con più opzioni (non una sola)._
2. Cambia l'accento nel menu.
   → _atteso: il menu VOCE sotto si aggiorna, mostrando solo le voci di
   quel locale._

## 4. Quattro modelli in inglese

1. Carica l'EPUB inglese, vai al tab «★ Voci PREMIUM».
   → _atteso: quattro voci nel menu MODELLO, nell'ordine «Audiobook Maker
   (VOXCPM2)», «Standard», «Avanzato», «Express (solo inglese)» — l'ultima
   esiste solo per l'inglese._
   Nota: il numero di modelli dipende dal catalogo voci effettivamente
   caricato (in particolare dalle voci VOXCPM2 disponibili in quel momento,
   che sono un dato importato, non una costante di codice). Se compaiono
   meno di quattro modelli, verifica prima se l'inglese ha voci VOXCPM2 nel
   catalogo corrente: non è necessariamente un difetto di questa funzione.
2. Seleziona «Avanzato».
   → _atteso: compare la riga «Accento di lettura» con quattro varianti._

## 5. Lingua non rilevata

1. Carica il `.txt` senza lingua nei metadati e senza rilevamento
   automatico disponibile (vedi Prerequisiti).
   → _atteso: la riga della lingua mostra «non rilevata, ipotizzata» in un
   colore di avviso (ambra), al posto di «dai metadati» o «rilevata dal
   testo»._
2. Avvia la generazione senza premere play sull'anteprima.
   → _atteso: compare il modale «Lingua non riconosciuta», con il testo
   «Non è stato possibile riconoscere automaticamente la lingua del libro.
   Verifica che la lingua e la voce selezionate siano corrette,
   eventualmente ascoltando l'anteprima.» e i pulsanti «Annulla» /
   «Conferma»._

## 6. Forzatura, andata e ritorno

1. EPUB italiano, tab «★ Voci PREMIUM», modello «Audiobook Maker
   (VOXCPM2)». Clicca l'icona ⚙ accanto alla riga della lingua, apri il
   modale «Forza la lingua del libro», scegli «Svedese» dall'elenco, clicca
   «Conferma».
   → _atteso: il tab «★ Voci PREMIUM» si disabilita con l'avviso «Le voci
   PREMIUM non sono disponibili in Svedese.», l'app torna sul tab «Voci
   Standard (gratis)», e sotto la riga della lingua compare la nota:
   «Lingua impostata su Svedese. Modello e voce riportati al valore
   predefinito. Voce riportata al valore predefinito.»
   La frase sulla voce compare due volte di seguito: una per il reset di
   modello+voce, una per il reset della sola voce. È il testo letterale che
   il codice produce (`_showCascadeNote()` in `static/js/app.js` accoda una
   frase per ciascun tipo di cambiamento, senza deduplicare), non un errore
   di battitura di questo documento._
2. Riapri il modale (⚙), scegli di nuovo «Italiano», clicca «Conferma».
   → _atteso: il pulsante «★ Voci PREMIUM» torna cliccabile (non più
   attenuato) — resta comunque sul tab «Voci Standard (gratis)» finché non
   lo clicchi tu, la forzatura non ci riporta automaticamente su PREMIUM.
   La riga della lingua ora mostra «impostata da te» al posto di «dai
   metadati»._

## 7. Preservazione del modello

1. EPUB italiano, tab «★ Voci PREMIUM», modello «Avanzato». Forza il
   francese con lo stesso modale del punto 6.
   → _atteso: il menu MODELLO resta su «Avanzato» — esiste anche in
   francese. La riga della lingua dice «Francese» / «impostata da te». La
   nota sotto dice «Lingua impostata su Francese. Voce riportata al valore
   predefinito.» — non compare mai la frase sul modello, perché il modello
   non è cambiato. La frase sulla voce compare comunque: cambiare la
   lingua invalida anche la voce del tab «Voci Standard (gratis)», pur
   restando quel tab non visibile in questo momento._

## 8. L'avviso «niente voci PREMIUM» si vede con qualunque tab

1. Carica l'EPUB svedese del punto 2. Resta sul tab «Voci Standard
   (gratis)», quello attivo di default.
   → _atteso: l'avviso «Le voci PREMIUM non sono disponibili in Svedese.»
   è visibile subito sotto la barra dei tab, sopra il contenuto del tab
   Standard — non è nascosto dentro il tab PREMIUM spento, dove non lo
   vedresti mai._
2. Cambia l'accento o la voce sul tab Standard.
   → _atteso: l'avviso resta al suo posto, non sparisce e non si sposta:
   non dipende da quale tab è aperto né da cosa scegli dentro quel tab._

## 9. La forzatura sopravvive al riavvio

1. Forza una lingua diversa da quella dei metadati, scegli una voce di
   quella lingua e avvia una generazione.
2. Riavvia il server mentre il job è in corso (o interrompilo) e lascia che
   il recovery all'avvio lo riprenda.
   → _atteso: il job riprende con la stessa voce scelta al momento della
   forzatura, non con una voce nella lingua originale dei metadati. La
   persistenza passa dalla voce salvata sul job (`job["voice"]` in
   `audiobook_app.py`), non da un campo «lingua forzata» separato: se il
   job riprende con la voce giusta, riprende anche con la lingua giusta._

## 10. Contratto mobile

1. Con l'app in esecuzione:
   ```bash
   curl -s http://127.0.0.1:5601/api/voices | python -c "import json,sys; d=json.load(sys.stdin); print(all(v.get('engine') for k,x in d.items() if not k.startswith('_') for v in x.get('voices',[])))"
   ```
   → _atteso: `True`. Ogni voce di ogni lingua porta ancora il campo
   `engine`, e le sole chiavi che iniziano per `_` (`_voxcpm`,
   `_premium_status`, …) sono metadati, non lingue — la forma del catalogo
   verso le app mobili non è cambiata da questo lavoro._
