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
   (VOXCPM2)». Clicca il bottone ⚙ «Cambia» accanto alla riga della lingua,
   apri il modale «Forza la lingua del libro», scegli «Svedese» dall'elenco,
   clicca «Conferma».
   → _atteso: il tab «★ Voci PREMIUM» si disabilita con l'avviso «Le voci
   PREMIUM non sono disponibili in Svedese.», l'app torna sul tab «Voci
   Standard (gratis)», e sotto la riga della lingua compare la nota:
   «Lingua impostata su Svedese. Le voci PREMIUM non coprono questa lingua:
   ora sei sulle Voci Standard. Voce impostata su <nome della voce svedese
   scelta dalla cascata>.»
   Ogni frase nomina il valore nuovo. Se ne leggi una che dice «riportato al
   valore predefinito», è una regressione: quella formula descriveva il
   codice e non diceva all'utente che cosa avesse in mano adesso._
2. Senza toccare altro, guarda la riga della lingua.
   → _atteso: accanto a ⚙ «Cambia» è comparso un secondo bottone, ↩ «Riporta
   a Italiano». Sul libro appena caricato non c'era: nasce solo quando la
   lingua attiva è diversa da quella che il libro dichiara._
3. Riapri il modale (⚙), scegli «Tedesco», conferma, e guarda di nuovo il
   bottone di ritorno.
   → _atteso: dice ancora ↩ «Riporta a Italiano», non «Riporta a Svedese».
   Non è un «annulla l'ultima scelta»: riporta alla lingua dichiarata dal
   libro, qualunque giro di forzature tu abbia fatto nel frattempo._
4. Clicca ↩ «Riporta a Italiano».
   → _atteso: la lingua torna «Italiano», la provenienza torna a dire «dai
   metadati» (non «impostata da te»), il pulsante «★ Voci PREMIUM» torna
   cliccabile e il bottone ↩ sparisce. Voce e modello si rifanno dalla
   cascata come su un libro italiano appena caricato._
5. Ripeti il punto 1 su un file di cui la riga della lingua dice «lingua
   ipotizzata» (nessun metadato, testo troppo corto per il riconoscimento).
   → _atteso: dopo la forzatura il bottone ↩ NON compare. Non c'è nessuna
   «lingua del libro» a cui tornare: quella di partenza l'aveva tirata a
   indovinare l'app, e un bottone che promettesse di ripristinarla starebbe
   promettendo un dato che non esiste._
6. Riapri il modale (⚙) sul libro del punto 4, scegli di nuovo «Italiano»,
   clicca «Conferma».
   → _atteso: il pulsante «★ Voci PREMIUM» torna cliccabile (non più
   attenuato) — resta comunque sul tab «Voci Standard (gratis)» finché non
   lo clicchi tu, la forzatura non ci riporta automaticamente su PREMIUM.
   La riga della lingua ora mostra «impostata da te» al posto di «dai
   metadati», e il bottone ↩ non c'è: la lingua attiva e quella del libro
   coincidono, anche se ci sei arrivato forzandola._

## 7. Preservazione del modello

1. EPUB italiano, tab «★ Voci PREMIUM», modello «Gemini 3.1 TTS». Forza il
   francese con lo stesso modale del punto 6.
   → _atteso: il menu MODELLO resta su «Gemini 3.1 TTS» — esiste anche in
   francese. La riga della lingua dice «Francese» / «impostata da te». La
   nota sotto dice soltanto «Lingua impostata su Francese.» — non compare la
   frase sul modello, perché il modello non è cambiato, e non compare
   nemmeno quella sulla voce: l'unica voce reimpostata è quella del tab
   «Voci Standard (gratis)», che in questo momento non stai guardando, e la
   nota parla solo del tab che hai davanti. La voce PREMIUM invece resta
   quella che avevi scelto: le voci del modello «Gemini 3.1 TTS» sono le stesse in
   tutte le lingue._
2. Senza forzare altro, clicca il tab «Voci Standard (gratis)» e guarda il
   menu VOCE.
   → _atteso: la voce Standard è effettivamente cambiata, ed è ora una voce
   francese: il silenzio della nota al punto 1 non vuol dire che non sia
   successo niente, vuol dire che non è successo niente nel tab che avevi
   davanti. Se al punto 1 la nota avesse invece annunciato il reset di
   questa voce, sarebbe stata la regressione D3._

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
