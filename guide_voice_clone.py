"""
Guida SEO/GEO «Audiolibri con la tua voce»: /guide/voice-cloning-audiobook/.

Contenuti in 7 lingue, registrati in guide_content.py. Passi e FAQ stanno qui
come dati strutturati: da una sola fonte nascono sia l'HTML visibile sia il
JSON-LD HowTo/FAQPage, così testo e schema non possono divergere.

Le etichette fra «» sono quelle reali dell'interfaccia (i18n_data.js): se
cambiano là vanno aggiornate anche qui. Nessun provider nominato.
"""

from __future__ import annotations

import html as _html
import json as _json
import re as _re

GUIDE_ID = "voice-cloning-audiobook"
PUBLISHED = "2026-09-17"
SECTION = "Voice Cloning"

META = {
    "en": {
        "title": "How to Create an Audiobook in Your Own Voice (Voice Cloning Guide) | Audiobook Maker",
        "h1": "How to Create an Audiobook Read in Your Own Voice",
        "kw": "audiobook in my own voice, clone my voice audiobook, voice cloning audiobook, narrate audiobook with my voice, ai voice clone text to speech, personal voice audiobook, epub to audiobook my voice",
        "desc": "Step-by-step guide: record a 25-second sample of your voice, approve two test clips and turn any EPUB, PDF or TXT into an audiobook narrated in your own voice. Refund voucher if you are not satisfied.",
    },
    "it": {
        "title": "Come Creare un Audiolibro con la Tua Voce (Guida alla Clonazione Vocale) | Audiobook Maker",
        "h1": "Come creare un audiolibro letto con la tua voce",
        "kw": "audiolibro con la mia voce, clonare la propria voce audiolibro, clonazione vocale audiolibro, leggere un libro con la mia voce, voce clonata ai, sintesi vocale con la mia voce, epub in audiolibro con la mia voce",
        "desc": "Guida passo passo: registra 25 secondi della tua voce, ascolta e approva due prove e trasforma qualsiasi EPUB, PDF o TXT in un audiolibro letto con la tua voce. Voucher di rimborso se non sei soddisfatto.",
    },
    "fr": {
        "title": "Créer un Livre Audio avec Votre Propre Voix (Guide du Clonage Vocal) | Audiobook Maker",
        "h1": "Comment créer un livre audio lu avec votre propre voix",
        "kw": "livre audio avec ma voix, cloner sa voix livre audio, clonage vocal livre audio, lire un livre avec ma voix, voix clonée ia, synthèse vocale avec ma voix, epub en livre audio avec ma voix",
        "desc": "Guide pas à pas : enregistrez 25 secondes de votre voix, écoutez et approuvez deux essais, puis transformez n'importe quel EPUB, PDF ou TXT en livre audio lu avec votre voix. Bon de remboursement si vous n'êtes pas satisfait.",
    },
    "es": {
        "title": "Cómo Crear un Audiolibro con Tu Propia Voz (Guía de Clonación de Voz) | Audiobook Maker",
        "h1": "Cómo crear un audiolibro leído con tu propia voz",
        "kw": "audiolibro con mi voz, clonar mi voz audiolibro, clonación de voz audiolibro, leer un libro con mi voz, voz clonada ia, texto a voz con mi voz, epub a audiolibro con mi voz",
        "desc": "Guía paso a paso: graba 25 segundos de tu voz, escucha y aprueba dos pruebas y convierte cualquier EPUB, PDF o TXT en un audiolibro leído con tu voz. Vale de reembolso si no quedas satisfecho.",
    },
    "de": {
        "title": "Hörbuch mit der eigenen Stimme erstellen (Anleitung Stimmklonen) | Audiobook Maker",
        "h1": "So erstellen Sie ein Hörbuch, gelesen mit Ihrer eigenen Stimme",
        "kw": "hörbuch mit eigener stimme, eigene stimme klonen hörbuch, stimmklonen hörbuch, buch mit meiner stimme vorlesen, ki stimme klonen, text to speech eigene stimme, epub zu hörbuch eigene stimme",
        "desc": "Schritt-für-Schritt-Anleitung: 25 Sekunden Ihrer Stimme aufnehmen, zwei Hörproben anhören und freigeben und jedes EPUB, PDF oder TXT in ein Hörbuch mit Ihrer Stimme verwandeln. Erstattungsgutschein, wenn Sie nicht zufrieden sind.",
    },
    "zh": {
        "title": "如何用你自己的声音制作有声书（声音克隆指南）| Audiobook Maker",
        "h1": "如何制作用你自己的声音朗读的有声书",
        "kw": "用自己的声音做有声书, 克隆自己的声音, 声音克隆有声书, 用我的声音朗读电子书, ai声音克隆, 自己声音的文字转语音, epub转有声书",
        "desc": "分步指南：录制约25秒的声音样本，试听并确认两段试听音频，然后把任意 EPUB、PDF 或 TXT 转换成用你自己的声音朗读的有声书。不满意可获得等值退款代金券。",
    },
    "hi": {
        "title": "अपनी आवाज़ में ऑडियोबुक कैसे बनाएँ (वॉइस क्लोनिंग गाइड) | Audiobook Maker",
        "h1": "अपनी ही आवाज़ में पढ़ी गई ऑडियोबुक कैसे बनाएँ",
        "kw": "अपनी आवाज़ में ऑडियोबुक, अपनी आवाज़ क्लोन करें, वॉइस क्लोनिंग ऑडियोबुक, मेरी आवाज़ में किताब पढ़ें, ai वॉइस क्लोन, अपनी आवाज़ में टेक्स्ट टू स्पीच, epub से ऑडियोबुक",
        "desc": "चरण-दर-चरण गाइड: अपनी आवाज़ के 25 सेकंड रिकॉर्ड करें, दो ट्रायल सुनकर स्वीकृत करें और किसी भी EPUB, PDF या TXT को अपनी आवाज़ में पढ़ी गई ऑडियोबुक में बदलें. संतुष्ट न होने पर रिफंड वाउचर.",
    },
}

# Lingue in cui si può campionare la voce (voice_clone_prompts.languages()).
_SAMPLE_LANGS = {
    "en": "English, Italian, French, Spanish, German, Portuguese, Dutch, Chinese and Hindi",
    "it": "italiano, inglese, francese, spagnolo, tedesco, portoghese, olandese, cinese e hindi",
    "fr": "français, anglais, italien, espagnol, allemand, portugais, néerlandais, chinois et hindi",
    "es": "español, inglés, italiano, francés, alemán, portugués, neerlandés, chino e hindi",
    "de": "Deutsch, Englisch, Italienisch, Französisch, Spanisch, Portugiesisch, Niederländisch, Chinesisch und Hindi",
    "zh": "中文、英语、意大利语、法语、西班牙语、德语、葡萄牙语、荷兰语和印地语",
    "hi": "हिंदी, अंग्रेज़ी, इतालवी, फ़्रेंच, स्पेनिश, जर्मन, पुर्तगाली, डच और चीनी",
}

_T = {
    "en": {
        "intro": (
            "<p><strong>Short answer:</strong> with Audiobook Maker you can have any book read in <strong>your own voice</strong>. "
            "Record 22&ndash;25 seconds of your voice reading a short passage, listen to two test clips generated with your cloned voice "
            "and, if you like them, pick the voice in the <strong>★ PREMIUM Voices</strong> tab: every EPUB, PDF or TXT becomes an audiobook narrated by you. "
            "If the result does not convince you, you reject it and get a voucher worth what you paid.</p>"
            "<p>It is ideal for parents who want to read bedtime stories even when they are away, for authors who want to narrate their own books, "
            "for teachers recording course material and for anyone who wants to leave a book in their voice to the people they love.</p>"
        ),
        "need_h2": "What you need",
        "need": [
            "A <strong>quiet room</strong> and a microphone: the one in your phone, laptop or a headset is enough.",
            "About <strong>5 minutes</strong> for the sampling and 1&ndash;4 minutes to wait for the test clips.",
            "A valid <strong>email address</strong>: you will receive the voice code and the link to manage or delete the voice.",
            "The book to convert, in <strong>EPUB, PDF or TXT</strong> format.",
            "The sample can be recorded in " + _SAMPLE_LANGS["en"] + ".",
        ],
        "steps_h2": "Step by step: from your voice to the audiobook",
        "steps": [
            ("Open the voice sampling wizard",
             "On the Audiobook Maker home page open the <strong>★ PREMIUM Voices</strong> tab and click <strong>«Sample your voice»</strong>. "
             "Read the conditions and tick <strong>«This is my voice and I have the right to use it»</strong>: you can only sample your own voice."),
            ("Choose language, accent and voice type",
             "Select the language and accent you will speak with and whether the voice is female or male. "
             "These choices decide the passage you will be asked to read and the books the voice will be offered for."),
            ("Record or upload the sample",
             "Press <strong>«Record»</strong> and read the passage aloud, calmly and without stopping, in 22&ndash;25 seconds. "
             "Alternatively use <strong>«Choose an audio file…»</strong> to upload a recording (wav, mp3, m4a, ogg or webm, up to 20 MB). "
             "You can listen to it again and redo it as many times as you want."),
            ("Pass the automatic quality check",
             "The sample is analysed and transcribed automatically: too short or too long, background noise, long pauses, distortion, "
             "phone-quality audio or a passage that does not match the text are reported with a precise hint on how to fix them."),
            ("Enter your email and pay",
             "Give the voice a name (optional), type your email twice and press <strong>«Pay and generate the trials»</strong>. "
             "The price is shown before payment; right after, you receive the <strong>voice code</strong> by email."),
            ("Listen to the two test clips",
             "In 1&ndash;4 minutes two short passages read with your cloned voice are ready: a <strong>common passage</strong> and a "
             "<strong>chosen passage</strong>. Listen to them carefully, ideally with headphones."),
            ("Approve or reject",
             "If you like the result press <strong>«Approve»</strong>. Otherwise press <strong>«Reject and request a refund»</strong>, "
             "write in a few words why: the voice is deleted and you receive by email a voucher worth what you paid, usable for the Premium services."),
            ("Generate the audiobook in your voice",
             "Upload your EPUB, PDF or TXT, open <strong>★ PREMIUM Voices</strong> and pick your voice from the <strong>«Your voices»</strong> group "
             "at the top of the list (it appears when the book language matches the voice language). Check the cost estimate and start the generation: "
             "you get MP3 files or an M4B audiobook with chapters, narrated in your voice."),
        ],
        "tips_h2": "Tips for a sample that sounds like you",
        "tips": [
            "Record in a small room with curtains, carpets or furniture: bare rooms add echo that the clone will copy.",
            "Keep the microphone 15&ndash;20 cm from your mouth and do not shout: a distorted sample produces a distorted voice.",
            "Read with the tone you want in the audiobook: calm and natural for novels, a bit livelier for children's stories.",
            "Turn off fans, air conditioning and notifications; do not record near a window facing the street.",
            "Do not use voice messages or phone calls as a source: narrow-band audio is rejected by the quality check.",
        ],
        "devices_h2": "Using your voice on other devices and with your family",
        "devices": (
            "<p>The voice is immediately available on the device where you created it. To use it on another phone, tablet or computer, "
            "open the wizard there, choose <strong>«Did someone give you a voice code?»</strong> and fill in <strong>«Add with a voice code»</strong> "
            "with the voice code, the name of the device and a short introduction.</p>"
            "<p>The voice owner receives an email with that introduction and a <strong>confirmation code valid for 24 hours</strong>: only after entering it "
            "is the device authorised. This way you can share your voice with your partner, children or grandparents, and nobody can use it without your consent.</p>"
        ),
        "privacy_h2": "Privacy and control over your voice",
        "privacy": [
            "Only you can sample your voice, and the consent is required explicitly before recording.",
            "From the link in the email you can see the authorised devices or <strong>delete the voice</strong> at any time.",
            "On each device you can use <strong>«Remove from this device»</strong> to take the voice off that device only.",
            "The voice expires after <strong>one year without use</strong> (each audiobook renews it); you are reminded by email 30 days before.",
            "Keep the voice code private: whoever has it can ask you to use your voice, but still needs your confirmation.",
        ],
        "faq_h2": "Frequently asked questions",
        "faq": [
            ("How long does the voice sample need to be?",
             "22 to 25 seconds of continuous speech reading the passage shown by the wizard. Shorter or much longer recordings are rejected by the automatic check, which tells you what to fix."),
            ("Can I narrate a book in a language different from my sample?",
             "The voice is offered for books in the language and accent you chose when sampling. To narrate in another language, sample your voice again in that language."),
            ("What happens if I do not like my cloned voice?",
             "After listening to the two test clips you can reject the voice, writing briefly why. The voice is deleted and you receive by email a voucher worth what you paid, usable for the Premium services of the platform."),
            ("Can someone else use my voice without permission?",
             "No. A new device needs the voice code and your approval: you receive an email with the name of the device and the introduction written by the requester, and only the confirmation code you give them (valid 24 hours) authorises it."),
            ("Which files can I turn into an audiobook with my voice?",
             "EPUB, PDF and TXT files, the same formats as the standard voices. The result can be MP3 files or an M4B audiobook with chapters, compatible with Apple Books and the main audiobook players."),
            ("How long does my voice stay available?",
             "As long as you use it: the voice expires after one year of inactivity and every audiobook generated renews the period. You receive a reminder email before it expires and can delete it earlier from the management link."),
        ],
    },
    "it": {
        "intro": (
            "<p><strong>In breve:</strong> con Audiobook Maker puoi far leggere qualsiasi libro alla <strong>tua voce</strong>. "
            "Registri 22&ndash;25 secondi della tua voce leggendo un breve brano, ascolti due prove generate con la voce clonata "
            "e, se ti piacciono, scegli la voce nella scheda <strong>★ Voci PREMIUM</strong>: ogni EPUB, PDF o TXT diventa un audiolibro letto da te. "
            "Se il risultato non ti convince, rifiuti e ricevi un voucher pari a quanto hai speso.</p>"
            "<p>È l'ideale per i genitori che vogliono leggere la favola della buonanotte anche quando sono lontani, per gli autori che vogliono narrare "
            "i propri libri, per gli insegnanti che registrano materiale didattico e per chi desidera lasciare un libro con la propria voce alle persone care.</p>"
        ),
        "need_h2": "Cosa ti serve",
        "need": [
            "Una <strong>stanza silenziosa</strong> e un microfono: basta quello del telefono, del portatile o di un auricolare.",
            "Circa <strong>5 minuti</strong> per il campionamento e 1&ndash;4 minuti di attesa per le prove.",
            "Un <strong>indirizzo email</strong> valido: riceverai il codice-voce e il link per gestire o eliminare la voce.",
            "Il libro da convertire, in formato <strong>EPUB, PDF o TXT</strong>.",
            "Il campione può essere registrato in " + _SAMPLE_LANGS["it"] + ".",
        ],
        "steps_h2": "Passo passo: dalla tua voce all'audiolibro",
        "steps": [
            ("Apri la procedura di campionamento",
             "Nella home di Audiobook Maker apri la scheda <strong>★ Voci PREMIUM</strong> e fai clic su <strong>«Campiona la tua voce»</strong>. "
             "Leggi le condizioni e spunta <strong>«È la mia voce e ho il diritto di usarla»</strong>: puoi campionare solo la tua voce."),
            ("Scegli lingua, accento e tipo di voce",
             "Seleziona la lingua e l'accento con cui parlerai e se la voce è femminile o maschile. "
             "Queste scelte decidono il brano che ti verrà proposto e i libri per cui la voce sarà disponibile."),
            ("Registra o carica il campione",
             "Premi <strong>«Registra»</strong> e leggi il brano ad alta voce, con calma e senza fermarti, in 22&ndash;25 secondi. "
             "In alternativa usa <strong>«Scegli un file audio…»</strong> per caricare una registrazione (wav, mp3, m4a, ogg o webm, fino a 20 MB). "
             "Puoi riascoltarla e rifarla tutte le volte che vuoi."),
            ("Supera la verifica automatica di qualità",
             "Il campione viene analizzato e trascritto automaticamente: durata sbagliata, rumore di fondo, pause lunghe, distorsione, "
             "audio di qualità telefonica o un brano che non corrisponde al testo vengono segnalati con l'indicazione precisa di cosa correggere."),
            ("Inserisci l'email e paga",
             "Dai un nome alla voce (facoltativo), scrivi due volte la tua email e premi <strong>«Paga e genera le prove»</strong>. "
             "Il prezzo è indicato prima del pagamento; subito dopo ricevi via email il <strong>codice-voce</strong>."),
            ("Ascolta le due prove",
             "In 1&ndash;4 minuti sono pronti due brevi brani letti con la tua voce clonata: un <strong>brano comune</strong> e un "
             "<strong>brano scelto</strong>. Ascoltali con attenzione, meglio se in cuffia."),
            ("Approva o rifiuta",
             "Se il risultato ti piace premi <strong>«Approva»</strong>. Altrimenti premi <strong>«Rifiuta e chiedi rimborso»</strong> "
             "e scrivi in poche parole il motivo: la voce viene eliminata e ricevi via email un voucher del valore speso, utilizzabile per i servizi Premium."),
            ("Genera l'audiolibro con la tua voce",
             "Carica il tuo EPUB, PDF o TXT, apri <strong>★ Voci PREMIUM</strong> e scegli la tua voce nel gruppo <strong>«Le tue voci»</strong> "
             "in cima all'elenco (compare quando la lingua del libro coincide con quella della voce). Controlla la stima del costo e avvia la generazione: "
             "ottieni file MP3 o un audiolibro M4B con capitoli, letto con la tua voce."),
        ],
        "tips_h2": "Consigli per un campione che ti somigli",
        "tips": [
            "Registra in una stanza piccola con tende, tappeti o mobili: gli ambienti spogli aggiungono un'eco che la voce clonata ricopierà.",
            "Tieni il microfono a 15&ndash;20 cm dalla bocca e non alzare la voce: un campione distorto produce una voce distorta.",
            "Leggi con il tono che vuoi nell'audiolibro: calmo e naturale per i romanzi, un po' più vivace per le storie per bambini.",
            "Spegni ventilatori, condizionatori e notifiche; non registrare vicino a una finestra che dà sulla strada.",
            "Non usare come sorgente messaggi vocali o telefonate: l'audio a banda stretta viene scartato dalla verifica di qualità.",
        ],
        "devices_h2": "Usare la tua voce su altri dispositivi e in famiglia",
        "devices": (
            "<p>La voce è subito disponibile sul dispositivo su cui l'hai creata. Per usarla su un altro telefono, tablet o computer "
            "apri lì la procedura, scegli <strong>«Hai ricevuto un codice-voce da un’altra persona?»</strong> e compila <strong>«Aggiungi con codice-voce»</strong> "
            "con il codice-voce, il nome del dispositivo e una breve presentazione.</p>"
            "<p>Il proprietario della voce riceve un'email con la presentazione e un <strong>codice di conferma valido 24 ore</strong>: solo dopo averlo inserito "
            "il dispositivo è autorizzato. Così puoi condividere la tua voce con il partner, i figli o i nonni, e nessuno può usarla senza il tuo consenso.</p>"
        ),
        "privacy_h2": "Privacy e controllo della tua voce",
        "privacy": [
            "Puoi campionare solo la tua voce, e il consenso è richiesto esplicitamente prima della registrazione.",
            "Dal link nell'email vedi i dispositivi autorizzati e puoi <strong>eliminare la voce</strong> in qualsiasi momento.",
            "Su ogni dispositivo puoi usare <strong>«Rimuovi da questo dispositivo»</strong> per toglierla solo da lì.",
            "La voce scade dopo <strong>un anno senza utilizzo</strong> (ogni audiolibro rinnova la scadenza); te lo ricordiamo via email 30 giorni prima.",
            "Tieni riservato il codice-voce: chi lo possiede può chiederti di usare la tua voce, ma serve comunque la tua conferma.",
        ],
        "faq_h2": "Domande frequenti",
        "faq": [
            ("Quanto deve durare il campione della voce?",
             "Da 22 a 25 secondi di parlato continuo, leggendo il brano proposto dalla procedura. Registrazioni più corte o troppo lunghe vengono scartate dalla verifica automatica, che ti dice cosa correggere."),
            ("Posso leggere un libro in una lingua diversa da quella del campione?",
             "La voce viene proposta per i libri nella lingua e nell'accento scelti durante il campionamento. Per narrare in un'altra lingua campiona di nuovo la tua voce in quella lingua."),
            ("Cosa succede se la voce clonata non mi piace?",
             "Dopo aver ascoltato le due prove puoi rifiutare la voce scrivendo brevemente il motivo. La voce viene eliminata e ricevi via email un voucher del valore speso, utilizzabile per i servizi Premium della piattaforma."),
            ("Qualcun altro può usare la mia voce senza permesso?",
             "No. Un nuovo dispositivo richiede il codice-voce e la tua approvazione: ricevi un'email con il nome del dispositivo e la presentazione di chi lo chiede, e solo il codice di conferma che gli comunichi (valido 24 ore) lo autorizza."),
            ("Quali file posso trasformare in audiolibro con la mia voce?",
             "File EPUB, PDF e TXT, gli stessi formati delle voci standard. Il risultato può essere in file MP3 o un audiolibro M4B con capitoli, compatibile con Apple Books e i principali lettori di audiolibri."),
            ("Per quanto tempo resta disponibile la mia voce?",
             "Finché la usi: la voce scade dopo un anno di inattività e ogni audiolibro generato rinnova il periodo. Prima della scadenza ricevi un'email di promemoria e puoi eliminarla prima dal link di gestione."),
        ],
    },
    "fr": {
        "intro": (
            "<p><strong>En bref :</strong> avec Audiobook Maker, vous pouvez faire lire n'importe quel livre par <strong>votre propre voix</strong>. "
            "Enregistrez 22&ndash;25 secondes de votre voix en lisant un court extrait, écoutez deux essais générés avec votre voix clonée "
            "et, s'ils vous plaisent, choisissez la voix dans l'onglet <strong>★ Voix PREMIUM</strong> : chaque EPUB, PDF ou TXT devient un livre audio lu par vous. "
            "Si le résultat ne vous convainc pas, vous le refusez et recevez un bon d'une valeur égale à ce que vous avez payé.</p>"
            "<p>C'est idéal pour les parents qui veulent lire l'histoire du soir même à distance, pour les auteurs qui souhaitent narrer leurs propres livres, "
            "pour les enseignants qui enregistrent leurs cours et pour tous ceux qui veulent laisser un livre avec leur voix à leurs proches.</p>"
        ),
        "need_h2": "Ce dont vous avez besoin",
        "need": [
            "Une <strong>pièce calme</strong> et un microphone : celui du téléphone, de l'ordinateur portable ou d'un casque suffit.",
            "Environ <strong>5 minutes</strong> pour l'échantillonnage et 1&ndash;4 minutes d'attente pour les essais.",
            "Une <strong>adresse e-mail</strong> valide : vous recevrez le code-voix et le lien pour gérer ou supprimer la voix.",
            "Le livre à convertir, au format <strong>EPUB, PDF ou TXT</strong>.",
            "L'échantillon peut être enregistré en " + _SAMPLE_LANGS["fr"] + ".",
        ],
        "steps_h2": "Pas à pas : de votre voix au livre audio",
        "steps": [
            ("Ouvrez l'assistant d'échantillonnage",
             "Sur la page d'accueil d'Audiobook Maker, ouvrez l'onglet <strong>★ Voix PREMIUM</strong> et cliquez sur <strong>«Échantillonnez votre voix»</strong>. "
             "Lisez les conditions et cochez <strong>«C'est ma voix et j'ai le droit de l'utiliser»</strong> : vous ne pouvez échantillonner que votre propre voix."),
            ("Choisissez la langue, l'accent et le type de voix",
             "Sélectionnez la langue et l'accent avec lesquels vous parlerez et indiquez si la voix est féminine ou masculine. "
             "Ces choix déterminent l'extrait à lire et les livres pour lesquels la voix sera proposée."),
            ("Enregistrez ou importez l'échantillon",
             "Appuyez sur <strong>«Enregistrer»</strong> et lisez l'extrait à voix haute, calmement et sans vous arrêter, en 22&ndash;25 secondes. "
             "Vous pouvez aussi utiliser <strong>«Choisir un fichier audio…»</strong> pour importer un enregistrement (wav, mp3, m4a, ogg ou webm, jusqu'à 20 Mo). "
             "Vous pouvez le réécouter et le refaire autant de fois que vous le souhaitez."),
            ("Passez le contrôle de qualité automatique",
             "L'échantillon est analysé et transcrit automatiquement : durée incorrecte, bruit de fond, longues pauses, distorsion, "
             "son de qualité téléphonique ou extrait ne correspondant pas au texte sont signalés avec une indication précise pour corriger."),
            ("Indiquez votre e-mail et payez",
             "Donnez un nom à la voix (facultatif), saisissez deux fois votre e-mail et appuyez sur <strong>«Payer et générer les essais»</strong>. "
             "Le prix est affiché avant le paiement ; juste après, vous recevez le <strong>code-voix</strong> par e-mail."),
            ("Écoutez les deux essais",
             "En 1&ndash;4 minutes, deux courts extraits lus avec votre voix clonée sont prêts : un <strong>extrait commun</strong> et un "
             "<strong>extrait choisi</strong>. Écoutez-les attentivement, de préférence au casque."),
            ("Approuvez ou refusez",
             "Si le résultat vous plaît, appuyez sur <strong>«Approuver»</strong>. Sinon, appuyez sur <strong>«Refuser et demander un remboursement»</strong> "
             "et écrivez brièvement pourquoi : la voix est supprimée et vous recevez par e-mail un bon de la valeur payée, utilisable pour les services Premium."),
            ("Générez le livre audio avec votre voix",
             "Importez votre EPUB, PDF ou TXT, ouvrez <strong>★ Voix PREMIUM</strong> et choisissez votre voix dans le groupe <strong>«Vos voix»</strong> "
             "en haut de la liste (il apparaît lorsque la langue du livre correspond à celle de la voix). Vérifiez l'estimation du coût et lancez la génération : "
             "vous obtenez des fichiers MP3 ou un livre audio M4B avec chapitres, lu avec votre voix."),
        ],
        "tips_h2": "Conseils pour un échantillon qui vous ressemble",
        "tips": [
            "Enregistrez dans une petite pièce avec rideaux, tapis ou meubles : les pièces vides ajoutent un écho que la voix clonée reproduira.",
            "Placez le micro à 15&ndash;20 cm de la bouche et ne criez pas : un échantillon saturé produit une voix saturée.",
            "Lisez avec le ton souhaité pour le livre audio : calme et naturel pour les romans, un peu plus vivant pour les histoires pour enfants.",
            "Éteignez ventilateurs, climatisation et notifications ; n'enregistrez pas près d'une fenêtre donnant sur la rue.",
            "N'utilisez pas de messages vocaux ou d'appels téléphoniques comme source : l'audio à bande étroite est refusé par le contrôle de qualité.",
        ],
        "devices_h2": "Utiliser votre voix sur d'autres appareils et en famille",
        "devices": (
            "<p>La voix est immédiatement disponible sur l'appareil où vous l'avez créée. Pour l'utiliser sur un autre téléphone, une tablette ou un ordinateur, "
            "ouvrez-y l'assistant, choisissez <strong>«Quelqu’un vous a donné un code-voix ?»</strong> et remplissez <strong>«Ajouter avec un code-voix»</strong> "
            "avec le code-voix, le nom de l'appareil et une courte présentation.</p>"
            "<p>Le propriétaire de la voix reçoit un e-mail avec cette présentation et un <strong>code de confirmation valable 24 heures</strong> : l'appareil n'est "
            "autorisé qu'après sa saisie. Vous pouvez ainsi partager votre voix avec votre conjoint, vos enfants ou vos grands-parents, et personne ne peut l'utiliser sans votre accord.</p>"
        ),
        "privacy_h2": "Confidentialité et contrôle de votre voix",
        "privacy": [
            "Seule votre propre voix peut être échantillonnée, et le consentement est demandé explicitement avant l'enregistrement.",
            "Depuis le lien de l'e-mail, vous voyez les appareils autorisés et pouvez <strong>supprimer la voix</strong> à tout moment.",
            "Sur chaque appareil, <strong>«Retirer de cet appareil»</strong> retire la voix de cet appareil uniquement.",
            "La voix expire après <strong>un an sans utilisation</strong> (chaque livre audio renouvelle l'échéance) ; un rappel est envoyé par e-mail 30 jours avant.",
            "Gardez le code-voix confidentiel : qui le possède peut vous demander d'utiliser votre voix, mais votre confirmation reste nécessaire.",
        ],
        "faq_h2": "Questions fréquentes",
        "faq": [
            ("Quelle doit être la durée de l'échantillon de voix ?",
             "De 22 à 25 secondes de parole continue, en lisant l'extrait proposé par l'assistant. Les enregistrements trop courts ou trop longs sont refusés par le contrôle automatique, qui indique quoi corriger."),
            ("Puis-je lire un livre dans une autre langue que celle de l'échantillon ?",
             "La voix est proposée pour les livres dans la langue et l'accent choisis lors de l'échantillonnage. Pour narrer dans une autre langue, échantillonnez à nouveau votre voix dans cette langue."),
            ("Que se passe-t-il si ma voix clonée ne me plaît pas ?",
             "Après avoir écouté les deux essais, vous pouvez refuser la voix en expliquant brièvement pourquoi. La voix est supprimée et vous recevez par e-mail un bon de la valeur payée, utilisable pour les services Premium de la plateforme."),
            ("Quelqu'un d'autre peut-il utiliser ma voix sans autorisation ?",
             "Non. Un nouvel appareil nécessite le code-voix et votre accord : vous recevez un e-mail avec le nom de l'appareil et la présentation du demandeur, et seul le code de confirmation que vous lui communiquez (valable 24 heures) l'autorise."),
            ("Quels fichiers puis-je transformer en livre audio avec ma voix ?",
             "Des fichiers EPUB, PDF et TXT, comme pour les voix standard. Le résultat peut être des fichiers MP3 ou un livre audio M4B avec chapitres, compatible avec Apple Books et les principaux lecteurs de livres audio."),
            ("Combien de temps ma voix reste-t-elle disponible ?",
             "Tant que vous l'utilisez : la voix expire après un an d'inactivité et chaque livre audio généré renouvelle la période. Vous recevez un rappel par e-mail avant l'expiration et pouvez la supprimer plus tôt depuis le lien de gestion."),
        ],
    },
    "es": {
        "intro": (
            "<p><strong>En resumen:</strong> con Audiobook Maker puedes hacer que cualquier libro lo lea <strong>tu propia voz</strong>. "
            "Graba 22&ndash;25 segundos de tu voz leyendo un breve fragmento, escucha dos pruebas generadas con tu voz clonada "
            "y, si te gustan, elige la voz en la pestaña <strong>★ Voces PREMIUM</strong>: cada EPUB, PDF o TXT se convierte en un audiolibro leído por ti. "
            "Si el resultado no te convence, lo rechazas y recibes un vale por el importe pagado.</p>"
            "<p>Es ideal para padres que quieren leer el cuento de buenas noches aunque estén lejos, para autores que desean narrar sus propios libros, "
            "para profesores que graban material didáctico y para quien quiere dejar un libro con su voz a sus seres queridos.</p>"
        ),
        "need_h2": "Qué necesitas",
        "need": [
            "Una <strong>habitación silenciosa</strong> y un micrófono: basta el del móvil, el portátil o unos auriculares.",
            "Unos <strong>5 minutos</strong> para el muestreo y 1&ndash;4 minutos de espera para las pruebas.",
            "Una <strong>dirección de correo</strong> válida: recibirás el código de voz y el enlace para gestionar o eliminar la voz.",
            "El libro que quieres convertir, en formato <strong>EPUB, PDF o TXT</strong>.",
            "La muestra puede grabarse en " + _SAMPLE_LANGS["es"] + ".",
        ],
        "steps_h2": "Paso a paso: de tu voz al audiolibro",
        "steps": [
            ("Abre el asistente de muestreo de voz",
             "En la página de inicio de Audiobook Maker abre la pestaña <strong>★ Voces PREMIUM</strong> y haz clic en <strong>«Muestra tu voz»</strong>. "
             "Lee las condiciones y marca <strong>«Es mi voz y tengo derecho a usarla»</strong>: solo puedes muestrear tu propia voz."),
            ("Elige idioma, acento y tipo de voz",
             "Selecciona el idioma y el acento con los que hablarás y si la voz es femenina o masculina. "
             "Estas opciones deciden el fragmento que te propondremos leer y los libros para los que estará disponible la voz."),
            ("Graba o sube la muestra",
             "Pulsa <strong>«Grabar»</strong> y lee el fragmento en voz alta, con calma y sin detenerte, en 22&ndash;25 segundos. "
             "También puedes usar <strong>«Elige un archivo de audio…»</strong> para subir una grabación (wav, mp3, m4a, ogg o webm, hasta 20 MB). "
             "Puedes volver a escucharla y repetirla todas las veces que quieras."),
            ("Supera la verificación automática de calidad",
             "La muestra se analiza y transcribe automáticamente: duración incorrecta, ruido de fondo, pausas largas, distorsión, "
             "audio de calidad telefónica o un fragmento que no coincide con el texto se señalan con una indicación precisa de qué corregir."),
            ("Introduce tu correo y paga",
             "Ponle un nombre a la voz (opcional), escribe dos veces tu correo y pulsa <strong>«Pagar y generar las pruebas»</strong>. "
             "El precio se muestra antes del pago; justo después recibes por correo el <strong>código de voz</strong>."),
            ("Escucha las dos pruebas",
             "En 1&ndash;4 minutos están listos dos fragmentos breves leídos con tu voz clonada: un <strong>fragmento común</strong> y un "
             "<strong>fragmento elegido</strong>. Escúchalos con atención, mejor con auriculares."),
            ("Aprueba o rechaza",
             "Si el resultado te gusta pulsa <strong>«Aprobar»</strong>. Si no, pulsa <strong>«Rechazar y solicitar reembolso»</strong> "
             "y escribe brevemente el motivo: la voz se elimina y recibes por correo un vale por el importe pagado, utilizable para los servicios Premium."),
            ("Genera el audiolibro con tu voz",
             "Sube tu EPUB, PDF o TXT, abre <strong>★ Voces PREMIUM</strong> y elige tu voz en el grupo <strong>«Tus voces»</strong> "
             "al principio de la lista (aparece cuando el idioma del libro coincide con el de la voz). Revisa la estimación del coste e inicia la generación: "
             "obtienes archivos MP3 o un audiolibro M4B con capítulos, leído con tu voz."),
        ],
        "tips_h2": "Consejos para una muestra que se parezca a ti",
        "tips": [
            "Graba en una habitación pequeña con cortinas, alfombras o muebles: las salas vacías añaden un eco que la voz clonada copiará.",
            "Mantén el micrófono a 15&ndash;20 cm de la boca y no grites: una muestra distorsionada produce una voz distorsionada.",
            "Lee con el tono que quieres en el audiolibro: tranquilo y natural para novelas, algo más animado para cuentos infantiles.",
            "Apaga ventiladores, aire acondicionado y notificaciones; no grabes junto a una ventana que da a la calle.",
            "No uses mensajes de voz ni llamadas telefónicas como fuente: el audio de banda estrecha es rechazado por la verificación de calidad.",
        ],
        "devices_h2": "Usar tu voz en otros dispositivos y en familia",
        "devices": (
            "<p>La voz está disponible de inmediato en el dispositivo donde la creaste. Para usarla en otro móvil, tableta u ordenador, "
            "abre allí el asistente, elige <strong>«¿Alguien te ha dado un código de voz?»</strong> y completa <strong>«Añadir con un código de voz»</strong> "
            "con el código de voz, el nombre del dispositivo y una breve presentación.</p>"
            "<p>El propietario de la voz recibe un correo con esa presentación y un <strong>código de confirmación válido 24 horas</strong>: solo después de introducirlo "
            "el dispositivo queda autorizado. Así puedes compartir tu voz con tu pareja, tus hijos o tus abuelos, y nadie puede usarla sin tu consentimiento.</p>"
        ),
        "privacy_h2": "Privacidad y control de tu voz",
        "privacy": [
            "Solo puedes muestrear tu propia voz, y el consentimiento se pide de forma explícita antes de grabar.",
            "Desde el enlace del correo ves los dispositivos autorizados y puedes <strong>eliminar la voz</strong> en cualquier momento.",
            "En cada dispositivo puedes usar <strong>«Quitar de este dispositivo»</strong> para quitarla solo de ahí.",
            "La voz caduca tras <strong>un año sin uso</strong> (cada audiolibro renueva el plazo); te lo recordamos por correo 30 días antes.",
            "Mantén en privado el código de voz: quien lo tenga puede pedirte usar tu voz, pero sigue necesitando tu confirmación.",
        ],
        "faq_h2": "Preguntas frecuentes",
        "faq": [
            ("¿Cuánto debe durar la muestra de voz?",
             "De 22 a 25 segundos de habla continua, leyendo el fragmento que propone el asistente. Las grabaciones demasiado cortas o largas son rechazadas por la verificación automática, que te indica qué corregir."),
            ("¿Puedo narrar un libro en un idioma distinto al de la muestra?",
             "La voz se ofrece para libros en el idioma y el acento elegidos durante el muestreo. Para narrar en otro idioma, vuelve a muestrear tu voz en ese idioma."),
            ("¿Qué pasa si no me gusta mi voz clonada?",
             "Después de escuchar las dos pruebas puedes rechazar la voz explicando brevemente por qué. La voz se elimina y recibes por correo un vale por el importe pagado, utilizable para los servicios Premium de la plataforma."),
            ("¿Puede otra persona usar mi voz sin permiso?",
             "No. Un dispositivo nuevo necesita el código de voz y tu aprobación: recibes un correo con el nombre del dispositivo y la presentación de quien lo solicita, y solo el código de confirmación que le des (válido 24 horas) lo autoriza."),
            ("¿Qué archivos puedo convertir en audiolibro con mi voz?",
             "Archivos EPUB, PDF y TXT, los mismos formatos que con las voces estándar. El resultado pueden ser archivos MP3 o un audiolibro M4B con capítulos, compatible con Apple Books y los principales reproductores de audiolibros."),
            ("¿Cuánto tiempo sigue disponible mi voz?",
             "Mientras la uses: la voz caduca tras un año de inactividad y cada audiolibro generado renueva el plazo. Antes de la caducidad recibes un correo de aviso y puedes eliminarla antes desde el enlace de gestión."),
        ],
    },
    "de": {
        "intro": (
            "<p><strong>Kurz gesagt:</strong> Mit Audiobook Maker können Sie jedes Buch mit <strong>Ihrer eigenen Stimme</strong> vorlesen lassen. "
            "Nehmen Sie 22&ndash;25 Sekunden Ihrer Stimme auf, während Sie einen kurzen Text lesen, hören Sie sich zwei mit Ihrer geklonten Stimme erzeugte Hörproben an "
            "und wählen Sie die Stimme, wenn sie Ihnen gefällt, im Tab <strong>★ PREMIUM-Stimmen</strong>: Jedes EPUB, PDF oder TXT wird zu einem Hörbuch, gelesen von Ihnen. "
            "Überzeugt Sie das Ergebnis nicht, lehnen Sie ab und erhalten einen Gutschein in Höhe des bezahlten Betrags.</p>"
            "<p>Ideal für Eltern, die auch aus der Ferne die Gutenachtgeschichte vorlesen möchten, für Autorinnen und Autoren, die ihre eigenen Bücher sprechen wollen, "
            "für Lehrkräfte, die Unterrichtsmaterial aufnehmen, und für alle, die ihren Liebsten ein Buch mit der eigenen Stimme hinterlassen möchten.</p>"
        ),
        "need_h2": "Was Sie brauchen",
        "need": [
            "Einen <strong>ruhigen Raum</strong> und ein Mikrofon: das des Smartphones, Laptops oder eines Headsets genügt.",
            "Etwa <strong>5 Minuten</strong> für die Aufnahme und 1&ndash;4 Minuten Wartezeit für die Hörproben.",
            "Eine gültige <strong>E-Mail-Adresse</strong>: Sie erhalten den Stimmcode und den Link zum Verwalten oder Löschen der Stimme.",
            "Das Buch, das Sie umwandeln möchten, im Format <strong>EPUB, PDF oder TXT</strong>.",
            "Die Stimmprobe kann auf " + _SAMPLE_LANGS["de"] + " aufgenommen werden.",
        ],
        "steps_h2": "Schritt für Schritt: von Ihrer Stimme zum Hörbuch",
        "steps": [
            ("Öffnen Sie den Assistenten für die Stimmaufnahme",
             "Öffnen Sie auf der Startseite von Audiobook Maker den Tab <strong>★ PREMIUM-Stimmen</strong> und klicken Sie auf <strong>«Stimme aufnehmen»</strong>. "
             "Lesen Sie die Bedingungen und setzen Sie das Häkchen bei <strong>«Das ist meine Stimme, und ich habe das Recht, sie zu nutzen»</strong>: Sie können nur Ihre eigene Stimme aufnehmen."),
            ("Wählen Sie Sprache, Akzent und Stimmtyp",
             "Wählen Sie die Sprache und den Akzent, in denen Sie sprechen, und ob die Stimme weiblich oder männlich ist. "
             "Diese Angaben bestimmen den Text, den Sie vorlesen, und die Bücher, für die die Stimme angeboten wird."),
            ("Nehmen Sie die Stimmprobe auf oder laden Sie sie hoch",
             "Drücken Sie <strong>«Aufnehmen»</strong> und lesen Sie den Text laut, ruhig und ohne Unterbrechung in 22&ndash;25 Sekunden vor. "
             "Alternativ laden Sie mit <strong>«Audiodatei auswählen…»</strong> eine Aufnahme hoch (wav, mp3, m4a, ogg oder webm, bis 20 MB). "
             "Sie können sie beliebig oft anhören und wiederholen."),
            ("Bestehen Sie die automatische Qualitätsprüfung",
             "Die Stimmprobe wird automatisch analysiert und transkribiert: falsche Länge, Hintergrundgeräusche, lange Pausen, Verzerrung, "
             "Audio in Telefonqualität oder ein Text, der nicht zur Vorlage passt, werden mit einem genauen Hinweis zur Behebung gemeldet."),
            ("E-Mail angeben und bezahlen",
             "Geben Sie der Stimme einen Namen (optional), tragen Sie Ihre E-Mail-Adresse zweimal ein und drücken Sie <strong>«Bezahlen und Hörproben erzeugen»</strong>. "
             "Der Preis wird vor der Zahlung angezeigt; direkt danach erhalten Sie den <strong>Stimmcode</strong> per E-Mail."),
            ("Hören Sie die beiden Hörproben an",
             "In 1&ndash;4 Minuten sind zwei kurze Passagen mit Ihrer geklonten Stimme fertig: eine <strong>gemeinsame Passage</strong> und eine "
             "<strong>gewählte Passage</strong>. Hören Sie sie aufmerksam an, am besten mit Kopfhörern."),
            ("Freigeben oder ablehnen",
             "Gefällt Ihnen das Ergebnis, drücken Sie <strong>«Genehmigen»</strong>. Andernfalls drücken Sie <strong>«Ablehnen und Rückerstattung verlangen»</strong> "
             "und nennen kurz den Grund: Die Stimme wird gelöscht und Sie erhalten per E-Mail einen Gutschein in Höhe des bezahlten Betrags für die Premium-Dienste."),
            ("Erzeugen Sie das Hörbuch mit Ihrer Stimme",
             "Laden Sie Ihr EPUB, PDF oder TXT hoch, öffnen Sie <strong>★ PREMIUM-Stimmen</strong> und wählen Sie Ihre Stimme in der Gruppe <strong>«Deine Stimmen»</strong> "
             "oben in der Liste (sie erscheint, wenn die Sprache des Buchs der Sprache der Stimme entspricht). Prüfen Sie die Kostenschätzung und starten Sie die Erzeugung: "
             "Sie erhalten MP3-Dateien oder ein M4B-Hörbuch mit Kapiteln, gelesen mit Ihrer Stimme."),
        ],
        "tips_h2": "Tipps für eine Stimmprobe, die wie Sie klingt",
        "tips": [
            "Nehmen Sie in einem kleinen Raum mit Vorhängen, Teppichen oder Möbeln auf: Kahle Räume erzeugen Hall, den die geklonte Stimme übernimmt.",
            "Halten Sie das Mikrofon 15&ndash;20 cm vom Mund entfernt und sprechen Sie nicht zu laut: Eine übersteuerte Probe ergibt eine übersteuerte Stimme.",
            "Lesen Sie in dem Ton, den Sie im Hörbuch möchten: ruhig und natürlich für Romane, etwas lebhafter für Kindergeschichten.",
            "Schalten Sie Ventilatoren, Klimaanlage und Benachrichtigungen aus; nehmen Sie nicht neben einem Fenster zur Straße auf.",
            "Verwenden Sie keine Sprachnachrichten oder Telefonate als Quelle: Schmalbandiges Audio wird von der Qualitätsprüfung abgelehnt.",
        ],
        "devices_h2": "Ihre Stimme auf anderen Geräten und in der Familie nutzen",
        "devices": (
            "<p>Die Stimme steht sofort auf dem Gerät zur Verfügung, auf dem Sie sie erstellt haben. Um sie auf einem anderen Smartphone, Tablet oder Computer zu nutzen, "
            "öffnen Sie dort den Assistenten, wählen <strong>«Hat dir jemand einen Stimmcode gegeben?»</strong> und füllen <strong>«Mit Stimmcode hinzufügen»</strong> "
            "mit dem Stimmcode, dem Gerätenamen und einer kurzen Vorstellung aus.</p>"
            "<p>Der Eigentümer der Stimme erhält eine E-Mail mit dieser Vorstellung und einem <strong>24 Stunden gültigen Bestätigungscode</strong>: Erst nach dessen Eingabe "
            "ist das Gerät freigegeben. So können Sie Ihre Stimme mit Partner, Kindern oder Großeltern teilen, und niemand kann sie ohne Ihre Zustimmung verwenden.</p>"
        ),
        "privacy_h2": "Datenschutz und Kontrolle über Ihre Stimme",
        "privacy": [
            "Sie können nur Ihre eigene Stimme aufnehmen; die Einwilligung wird vor der Aufnahme ausdrücklich abgefragt.",
            "Über den Link in der E-Mail sehen Sie die freigegebenen Geräte und können <strong>die Stimme jederzeit löschen</strong>.",
            "Auf jedem Gerät entfernt <strong>«Von diesem Gerät entfernen»</strong> die Stimme nur von diesem Gerät.",
            "Die Stimme verfällt nach <strong>einem Jahr ohne Nutzung</strong> (jedes Hörbuch verlängert die Frist); 30 Tage vorher erhalten Sie eine Erinnerung per E-Mail.",
            "Halten Sie den Stimmcode geheim: Wer ihn besitzt, kann die Nutzung Ihrer Stimme anfragen, braucht aber weiterhin Ihre Bestätigung.",
        ],
        "faq_h2": "Häufige Fragen",
        "faq": [
            ("Wie lang muss die Stimmprobe sein?",
             "22 bis 25 Sekunden durchgehendes Sprechen, beim Vorlesen des vom Assistenten vorgeschlagenen Textes. Zu kurze oder zu lange Aufnahmen werden von der automatischen Prüfung abgelehnt, die Ihnen sagt, was zu korrigieren ist."),
            ("Kann ich ein Buch in einer anderen Sprache als der meiner Stimmprobe vorlesen lassen?",
             "Die Stimme wird für Bücher in der Sprache und dem Akzent angeboten, die Sie bei der Aufnahme gewählt haben. Für eine andere Sprache nehmen Sie Ihre Stimme in dieser Sprache erneut auf."),
            ("Was passiert, wenn mir meine geklonte Stimme nicht gefällt?",
             "Nach dem Anhören der beiden Hörproben können Sie die Stimme ablehnen und kurz begründen, warum. Die Stimme wird gelöscht und Sie erhalten per E-Mail einen Gutschein in Höhe des bezahlten Betrags für die Premium-Dienste der Plattform."),
            ("Kann jemand anderes meine Stimme ohne Erlaubnis nutzen?",
             "Nein. Ein neues Gerät braucht den Stimmcode und Ihre Zustimmung: Sie erhalten eine E-Mail mit dem Gerätenamen und der Vorstellung der anfragenden Person, und erst der Bestätigungscode, den Sie weitergeben (24 Stunden gültig), gibt das Gerät frei."),
            ("Welche Dateien kann ich mit meiner Stimme in ein Hörbuch umwandeln?",
             "EPUB-, PDF- und TXT-Dateien, dieselben Formate wie bei den Standardstimmen. Das Ergebnis sind MP3-Dateien oder ein M4B-Hörbuch mit Kapiteln, kompatibel mit Apple Books und den gängigen Hörbuch-Playern."),
            ("Wie lange bleibt meine Stimme verfügbar?",
             "Solange Sie sie nutzen: Die Stimme verfällt nach einem Jahr ohne Nutzung, und jedes erzeugte Hörbuch verlängert die Frist. Vor dem Ablauf erhalten Sie eine Erinnerung per E-Mail und können sie über den Verwaltungslink auch früher löschen."),
        ],
    },
    "zh": {
        "intro": (
            "<p><strong>简要回答：</strong>使用 Audiobook Maker，你可以让任何一本书由<strong>你自己的声音</strong>朗读。"
            "朗读一小段文字，录制 22&ndash;25 秒的声音样本，试听两段用你的克隆声音生成的试听音频；"
            "满意的话，在<strong>★ 高级语音</strong>选项卡中选择这个声音：每个 EPUB、PDF 或 TXT 都会变成由你朗读的有声书。"
            "如果对结果不满意，可以拒绝并获得与支付金额等值的代金券。</p>"
            "<p>它非常适合出门在外也想给孩子讲睡前故事的父母、想亲自朗读自己作品的作者、录制教学材料的老师，"
            "以及想用自己的声音为亲人留下一本书的每一个人。</p>"
        ),
        "need_h2": "你需要准备什么",
        "need": [
            "一个<strong>安静的房间</strong>和一个麦克风：手机、笔记本电脑或耳机自带的麦克风即可。",
            "大约 <strong>5 分钟</strong>用于录制样本，另需等待 1&ndash;4 分钟生成试听音频。",
            "一个有效的<strong>电子邮箱</strong>：你将收到语音代码以及管理或删除声音的链接。",
            "要转换的书籍，格式为 <strong>EPUB、PDF 或 TXT</strong>。",
            "声音样本可以使用以下语言录制：" + _SAMPLE_LANGS["zh"] + "。",
        ],
        "steps_h2": "分步操作：从你的声音到有声书",
        "steps": [
            ("打开声音样本录制向导",
             "在 Audiobook Maker 首页打开<strong>★ 高级语音</strong>选项卡，点击<strong>「录制你的声音样本」</strong>。"
             "阅读条款并勾选<strong>「这是我的声音，我有权使用它」</strong>：你只能录制自己的声音。"),
            ("选择语言、口音和声音类型",
             "选择你将使用的语言和口音，以及声音是女声还是男声。"
             "这些选择决定你需要朗读的文字，以及这个声音可用于哪些书籍。"),
            ("录制或上传样本",
             "点击<strong>「开始录制」</strong>，用 22&ndash;25 秒平稳、连续地大声朗读这段文字。"
             "也可以通过<strong>「选择音频文件…」</strong>上传录音（wav、mp3、m4a、ogg 或 webm，最大 20 MB）。"
             "你可以反复试听并重新录制。"),
            ("通过自动质量检测",
             "系统会自动分析并转写样本：时长不符、背景噪音、停顿过长、失真、电话音质，或朗读内容与文字不一致，"
             "都会给出具体的修改提示。"),
            ("填写邮箱并付款",
             "为声音命名（可选），输入两次邮箱地址，然后点击<strong>「付款并生成试听」</strong>。"
             "付款前会显示价格；付款后你会立即通过邮件收到<strong>语音代码</strong>。"),
            ("试听两段音频",
             "1&ndash;4 分钟后，两段用你的克隆声音朗读的短音频即可试听：<strong>通用段落</strong>和<strong>所选段落</strong>。"
             "请仔细聆听，最好戴上耳机。"),
            ("通过或拒绝",
             "如果满意，点击<strong>「通过」</strong>。否则点击<strong>「拒绝并申请退款」</strong>，"
             "并简单写明原因：声音将被删除，你会通过邮件收到与支付金额等值的代金券，可用于平台的高级服务。"),
            ("用你的声音生成有声书",
             "上传你的 EPUB、PDF 或 TXT，打开<strong>★ 高级语音</strong>，在列表顶部的<strong>「你录制的声音」</strong>分组中选择你的声音"
             "（当书籍语言与声音语言一致时才会显示）。确认费用预估后开始生成："
             "你将得到 MP3 文件或带章节的 M4B 有声书，全部由你的声音朗读。"),
        ],
        "tips_h2": "让样本更像你的小技巧",
        "tips": [
            "在有窗帘、地毯或家具的小房间里录音：空旷的房间会产生回声，克隆声音也会把回声复制下来。",
            "麦克风距离嘴巴 15&ndash;20 厘米，不要大喊：失真的样本会生成失真的声音。",
            "用你希望有声书呈现的语气朗读：小说平稳自然，儿童故事可以稍微活泼一些。",
            "关闭风扇、空调和通知提示音；不要在临街的窗边录音。",
            "不要使用语音消息或电话录音作为来源：窄带音频会被质量检测拒绝。",
        ],
        "devices_h2": "在其他设备上或与家人共享你的声音",
        "devices": (
            "<p>声音在创建它的设备上可以立即使用。若要在另一部手机、平板或电脑上使用，"
            "请在该设备上打开向导，选择<strong>「别人给了你一个语音代码？」</strong>，然后在<strong>「使用语音代码添加」</strong>中"
            "填写语音代码、设备名称和一段简短的自我介绍。</p>"
            "<p>声音的所有者会收到一封包含该介绍和<strong>24 小时内有效的确认码</strong>的邮件：只有输入确认码后，"
            "设备才会获得授权。这样你就可以把自己的声音分享给伴侣、孩子或祖父母，而未经你的同意，任何人都无法使用它。</p>"
        ),
        "privacy_h2": "隐私与对声音的掌控",
        "privacy": [
            "你只能录制自己的声音，录制前必须明确表示同意。",
            "通过邮件中的链接，你可以查看已授权的设备，或随时<strong>删除声音</strong>。",
            "在任意设备上，<strong>「从此设备移除」</strong>只会把声音从该设备上移除。",
            "声音在<strong>一年未使用</strong>后过期（每生成一本有声书都会重新计算）；到期前 30 天会通过邮件提醒你。",
            "请妥善保管语音代码：持有代码的人可以申请使用你的声音，但仍需你的确认。",
        ],
        "faq_h2": "常见问题",
        "faq": [
            ("声音样本需要多长？",
             "22 到 25 秒的连续朗读，内容为向导提供的文字。过短或过长的录音会被自动检测拒绝，并提示你需要修改的地方。"),
            ("可以用与样本不同的语言朗读书籍吗？",
             "声音只会用于与录制时所选语言和口音相同的书籍。若要用其他语言朗读，请用该语言重新录制你的声音。"),
            ("如果我不喜欢克隆出来的声音怎么办？",
             "试听两段音频后，你可以拒绝该声音并简单说明原因。声音会被删除，你会通过邮件收到与支付金额等值的代金券，可用于平台的高级服务。"),
            ("别人能在未经允许的情况下使用我的声音吗？",
             "不能。新设备需要语音代码和你的批准：你会收到一封邮件，其中包含设备名称和申请人的自我介绍，只有你提供给对方的确认码（24 小时内有效）才能授权该设备。"),
            ("哪些文件可以用我的声音转换成有声书？",
             "EPUB、PDF 和 TXT 文件，与标准语音支持的格式相同。结果可以是 MP3 文件，或带章节的 M4B 有声书，兼容 Apple Books 和主流有声书播放器。"),
            ("我的声音可以保留多久？",
             "只要你在使用就会一直保留：声音在一年未使用后过期，每生成一本有声书都会重新计算期限。到期前你会收到提醒邮件，也可以随时通过管理链接提前删除。"),
        ],
    },
    "hi": {
        "intro": (
            "<p><strong>संक्षेप में:</strong> Audiobook Maker के साथ आप किसी भी किताब को <strong>अपनी ही आवाज़</strong> में पढ़वा सकते हैं. "
            "एक छोटा अंश पढ़ते हुए अपनी आवाज़ के 22&ndash;25 सेकंड रिकॉर्ड करें, अपनी क्लोन की गई आवाज़ में बने दो ट्रायल सुनें "
            "और पसंद आने पर <strong>★ प्रीमियम आवाज़ें</strong> टैब में वह आवाज़ चुनें: हर EPUB, PDF या TXT आपकी आवाज़ में पढ़ी गई ऑडियोबुक बन जाती है. "
            "अगर नतीजा पसंद न आए, तो आप उसे अस्वीकार करके चुकाई गई राशि के बराबर वाउचर पाते हैं.</p>"
            "<p>यह उन माता-पिता के लिए आदर्श है जो दूर रहकर भी बच्चों को सोते समय कहानी सुनाना चाहते हैं, उन लेखकों के लिए जो अपनी किताबें ख़ुद पढ़ना चाहते हैं, "
            "पाठ्य सामग्री रिकॉर्ड करने वाले शिक्षकों के लिए, और हर उस व्यक्ति के लिए जो अपनों के लिए अपनी आवाज़ में एक किताब छोड़ना चाहता है.</p>"
        ),
        "need_h2": "आपको क्या चाहिए",
        "need": [
            "एक <strong>शांत कमरा</strong> और माइक्रोफ़ोन: फ़ोन, लैपटॉप या हेडसेट का माइक्रोफ़ोन काफ़ी है.",
            "सैंपल के लिए लगभग <strong>5 मिनट</strong> और ट्रायल बनने के लिए 1&ndash;4 मिनट का इंतज़ार.",
            "एक मान्य <strong>ईमेल पता</strong>: आपको वॉइस कोड और आवाज़ को प्रबंधित करने या हटाने का लिंक मिलेगा.",
            "बदलने के लिए किताब, <strong>EPUB, PDF या TXT</strong> फ़ॉर्मैट में.",
            "सैंपल इन भाषाओं में रिकॉर्ड किया जा सकता है: " + _SAMPLE_LANGS["hi"] + ".",
        ],
        "steps_h2": "चरण-दर-चरण: आपकी आवाज़ से ऑडियोबुक तक",
        "steps": [
            ("आवाज़ का नमूना देने की प्रक्रिया खोलें",
             "Audiobook Maker के होम पेज पर <strong>★ प्रीमियम आवाज़ें</strong> टैब खोलें और <strong>«अपनी आवाज़ का नमूना दें»</strong> पर क्लिक करें. "
             "शर्तें पढ़ें और <strong>«यह मेरी आवाज़ है और इसे उपयोग करने का मुझे अधिकार है»</strong> पर टिक करें: आप केवल अपनी ही आवाज़ का नमूना दे सकते हैं."),
            ("भाषा, लहजा और आवाज़ का प्रकार चुनें",
             "वह भाषा और लहजा चुनें जिसमें आप बोलेंगे, और बताएँ कि आवाज़ महिला की है या पुरुष की. "
             "इन्हीं से तय होता है कि आपको कौन-सा अंश पढ़ना है और यह आवाज़ किन किताबों के लिए उपलब्ध होगी."),
            ("सैंपल रिकॉर्ड या अपलोड करें",
             "<strong>«रिकॉर्ड करें»</strong> दबाएँ और अंश को 22&ndash;25 सेकंड में शांति से, बिना रुके, ज़ोर से पढ़ें. "
             "या <strong>«एक ऑडियो फ़ाइल चुनें…»</strong> से कोई रिकॉर्डिंग अपलोड करें (wav, mp3, m4a, ogg या webm, 20 MB तक). "
             "आप इसे जितनी बार चाहें सुन और दोबारा रिकॉर्ड कर सकते हैं."),
            ("स्वचालित गुणवत्ता जाँच पास करें",
             "सैंपल का अपने-आप विश्लेषण और ट्रांसक्रिप्शन होता है: गलत अवधि, पृष्ठभूमि का शोर, लंबे विराम, विकृति, "
             "फ़ोन जैसी गुणवत्ता वाला ऑडियो या पाठ से मेल न खाता अंश होने पर ठीक करने का सटीक सुझाव दिखाया जाता है."),
            ("ईमेल डालें और भुगतान करें",
             "आवाज़ को नाम दें (वैकल्पिक), अपना ईमेल दो बार लिखें और <strong>«भुगतान करें और नमूने बनाएं»</strong> दबाएँ. "
             "कीमत भुगतान से पहले दिखाई जाती है; उसके तुरंत बाद आपको ईमेल से <strong>वॉइस कोड</strong> मिलता है."),
            ("दोनों ट्रायल सुनें",
             "1&ndash;4 मिनट में आपकी क्लोन की गई आवाज़ में पढ़े गए दो छोटे अंश तैयार हो जाते हैं: एक <strong>सामान्य अंश</strong> और एक "
             "<strong>चुना गया अंश</strong>. इन्हें ध्यान से सुनें, हो सके तो हेडफ़ोन लगाकर."),
            ("स्वीकृत या अस्वीकार करें",
             "नतीजा पसंद आए तो <strong>«स्वीकृत करें»</strong> दबाएँ. वरना <strong>«अस्वीकार करें और रिफंड मांगें»</strong> दबाएँ "
             "और थोड़े शब्दों में कारण लिखें: आवाज़ हटा दी जाती है और आपको ईमेल से चुकाई गई राशि का वाउचर मिलता है, जिसे प्रीमियम सेवाओं में इस्तेमाल किया जा सकता है."),
            ("अपनी आवाज़ में ऑडियोबुक बनाएँ",
             "अपनी EPUB, PDF या TXT फ़ाइल अपलोड करें, <strong>★ प्रीमियम आवाज़ें</strong> खोलें और सूची में सबसे ऊपर <strong>«आपकी आवाज़ें»</strong> समूह से अपनी आवाज़ चुनें "
             "(यह तब दिखता है जब किताब की भाषा आवाज़ की भाषा से मेल खाती है). लागत का अनुमान देखें और जनरेशन शुरू करें: "
             "आपको MP3 फ़ाइलें या अध्यायों वाली M4B ऑडियोबुक मिलती है, आपकी आवाज़ में."),
        ],
        "tips_h2": "ऐसे सैंपल के लिए सुझाव जो आप जैसा लगे",
        "tips": [
            "पर्दों, कालीन या फ़र्नीचर वाले छोटे कमरे में रिकॉर्ड करें: ख़ाली कमरों की गूँज क्लोन की गई आवाज़ में भी आ जाती है.",
            "माइक्रोफ़ोन को मुँह से 15&ndash;20 सेमी दूर रखें और चिल्लाएँ नहीं: विकृत सैंपल से विकृत आवाज़ बनती है.",
            "उसी लहजे में पढ़ें जो आप ऑडियोबुक में चाहते हैं: उपन्यासों के लिए शांत और स्वाभाविक, बच्चों की कहानियों के लिए थोड़ा जीवंत.",
            "पंखे, एसी और नोटिफ़िकेशन बंद कर दें; सड़क की ओर खुलने वाली खिड़की के पास रिकॉर्ड न करें.",
            "वॉइस मैसेज या फ़ोन कॉल को स्रोत के रूप में इस्तेमाल न करें: नैरो-बैंड ऑडियो गुणवत्ता जाँच में अस्वीकार हो जाता है.",
        ],
        "devices_h2": "दूसरे डिवाइस पर और परिवार के साथ अपनी आवाज़ का उपयोग",
        "devices": (
            "<p>आवाज़ उसी डिवाइस पर तुरंत उपलब्ध होती है जिस पर आपने उसे बनाया. किसी दूसरे फ़ोन, टैबलेट या कंप्यूटर पर इस्तेमाल करने के लिए "
            "वहाँ प्रक्रिया खोलें, <strong>«क्या किसी ने आपको वॉइस कोड दिया है?»</strong> चुनें और <strong>«वॉइस कोड से जोड़ें»</strong> में "
            "वॉइस कोड, डिवाइस का नाम और एक छोटा परिचय भरें.</p>"
            "<p>आवाज़ के मालिक को उस परिचय के साथ एक ईमेल और <strong>24 घंटे तक मान्य पुष्टि कोड</strong> मिलता है: उसे डालने के बाद ही "
            "डिवाइस अधिकृत होता है. इस तरह आप अपनी आवाज़ जीवनसाथी, बच्चों या दादा-दादी के साथ साझा कर सकते हैं, और आपकी सहमति के बिना कोई उसका उपयोग नहीं कर सकता.</p>"
        ),
        "privacy_h2": "आपकी आवाज़ पर गोपनीयता और नियंत्रण",
        "privacy": [
            "आप केवल अपनी ही आवाज़ का नमूना दे सकते हैं, और रिकॉर्डिंग से पहले स्पष्ट सहमति माँगी जाती है.",
            "ईमेल के लिंक से आप अधिकृत डिवाइस देख सकते हैं और कभी भी <strong>आवाज़ हटा</strong> सकते हैं.",
            "हर डिवाइस पर <strong>«इस डिवाइस से हटाएं»</strong> आवाज़ को सिर्फ़ उसी डिवाइस से हटाता है.",
            "आवाज़ <strong>एक साल तक उपयोग न होने</strong> पर समाप्त हो जाती है (हर ऑडियोबुक से अवधि फिर शुरू होती है); 30 दिन पहले ईमेल से याद दिलाया जाता है.",
            "वॉइस कोड गोपनीय रखें: जिसके पास कोड है वह आपकी आवाज़ के उपयोग का अनुरोध कर सकता है, पर फिर भी आपकी पुष्टि ज़रूरी है.",
        ],
        "faq_h2": "अक्सर पूछे जाने वाले प्रश्न",
        "faq": [
            ("आवाज़ का सैंपल कितना लंबा होना चाहिए?",
             "22 से 25 सेकंड तक लगातार बोलना, प्रक्रिया द्वारा दिया गया अंश पढ़ते हुए. बहुत छोटी या बहुत लंबी रिकॉर्डिंग स्वचालित जाँच में अस्वीकार हो जाती है, जो बताती है कि क्या ठीक करना है."),
            ("क्या मैं सैंपल से अलग भाषा में किताब पढ़वा सकता हूँ?",
             "आवाज़ उन्हीं किताबों के लिए दिखाई जाती है जिनकी भाषा और लहजा सैंपल देते समय चुने गए थे. किसी दूसरी भाषा के लिए उस भाषा में अपनी आवाज़ का नया नमूना दें."),
            ("अगर मुझे अपनी क्लोन की गई आवाज़ पसंद न आए तो क्या होगा?",
             "दोनों ट्रायल सुनने के बाद आप संक्षेप में कारण लिखकर आवाज़ अस्वीकार कर सकते हैं. आवाज़ हटा दी जाती है और आपको ईमेल से चुकाई गई राशि का वाउचर मिलता है, जिसे प्लेटफ़ॉर्म की प्रीमियम सेवाओं में इस्तेमाल किया जा सकता है."),
            ("क्या कोई और मेरी अनुमति के बिना मेरी आवाज़ इस्तेमाल कर सकता है?",
             "नहीं. नए डिवाइस के लिए वॉइस कोड और आपकी मंज़ूरी चाहिए: आपको डिवाइस के नाम और अनुरोध करने वाले के परिचय के साथ ईमेल मिलता है, और केवल आपके द्वारा दिया गया पुष्टि कोड (24 घंटे तक मान्य) ही उसे अधिकृत करता है."),
            ("मैं अपनी आवाज़ में किन फ़ाइलों को ऑडियोबुक बना सकता हूँ?",
             "EPUB, PDF और TXT फ़ाइलें, वही फ़ॉर्मैट जो मानक आवाज़ों के लिए हैं. नतीजा MP3 फ़ाइलें या अध्यायों वाली M4B ऑडियोबुक हो सकता है, जो Apple Books और प्रमुख ऑडियोबुक प्लेयर के साथ काम करती है."),
            ("मेरी आवाज़ कितने समय तक उपलब्ध रहती है?",
             "जब तक आप उसका उपयोग करते हैं: आवाज़ एक साल तक उपयोग न होने पर समाप्त होती है और हर बनाई गई ऑडियोबुक अवधि को फिर से शुरू करती है. समाप्ति से पहले आपको याद दिलाने वाला ईमेल मिलता है, और आप प्रबंधन लिंक से उसे पहले भी हटा सकते हैं."),
        ],
    },
}

LANGS = tuple(_T.keys())


def _li(items):
    return "\n".join(f"  <li>{x}</li>" for x in items)


def body(lang: str) -> str:
    """HTML del corpo della guida; lingue sconosciute ricadono sull'inglese."""
    t = _T.get(lang) or _T["en"]
    steps = "\n".join(
        f'  <li id="step-{i}"><strong>{name}</strong> &mdash; {text}</li>'
        for i, (name, text) in enumerate(t["steps"], 1))
    faq = "\n".join(
        f"<details><summary>{q}</summary>\n<p>{a}</p>\n</details>" for q, a in t["faq"])
    return (
        f"\n{t['intro']}\n\n"
        f'<h2 id="what-you-need">{t["need_h2"]}</h2>\n<ul>\n{_li(t["need"])}\n</ul>\n\n'
        f'<h2 id="steps">{t["steps_h2"]}</h2>\n<ol>\n{steps}\n</ol>\n\n'
        f'<h2 id="tips">{t["tips_h2"]}</h2>\n<ul>\n{_li(t["tips"])}\n</ul>\n\n'
        f'<h2 id="other-devices">{t["devices_h2"]}</h2>\n{t["devices"]}\n\n'
        f'<h2 id="privacy">{t["privacy_h2"]}</h2>\n<ul>\n{_li(t["privacy"])}\n</ul>\n\n'
        f'<h2 id="faq">{t["faq_h2"]}</h2>\n{faq}\n'
    )


_TAG_RE = _re.compile(r"<[^>]+>")


def _plain(s: str) -> str:
    return " ".join(_html.unescape(_TAG_RE.sub("", s)).split())


def _ld_json(obj) -> str:
    # "</" chiuderebbe il tag <script> che ospita il JSON-LD.
    return _json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def extra_ld(lang: str, canonical: str, meta: dict) -> list:
    """JSON-LD HowTo + FAQPage, generati dagli stessi dati del testo visibile."""
    t = _T.get(lang) or _T["en"]
    in_lang = {"zh": "zh-Hans"}.get(lang, lang if lang in _T else "en")
    howto = {
        "@context": "https://schema.org",
        "@type": "HowTo",
        "name": meta.get("h1", meta.get("title", "")),
        "description": meta.get("desc", ""),
        "inLanguage": in_lang,
        "totalTime": "PT15M",
        "supply": [{"@type": "HowToSupply", "name": "EPUB, PDF, TXT"}],
        "tool": [{"@type": "HowToTool", "name": "Microphone"}],
        "step": [
            {"@type": "HowToStep", "position": i, "name": _plain(name), "text": _plain(text),
             **({"url": f"{canonical}#step-{i}"} if canonical else {})}
            for i, (name, text) in enumerate(t["steps"], 1)
        ],
    }
    faq = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "inLanguage": in_lang,
        "mainEntity": [
            {"@type": "Question", "name": _plain(q),
             "acceptedAnswer": {"@type": "Answer", "text": _plain(a)}}
            for q, a in t["faq"]
        ],
    }
    return [_ld_json(howto), _ld_json(faq)]
