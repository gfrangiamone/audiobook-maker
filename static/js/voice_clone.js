/* Voci campionate (spec docs/superpowers/specs/2026-09-09-voci-campionate-design.md §3):
   bottone «Campiona la tua voce», modal a cinque pannelli, registratore,
   pagamento, avanzamento, ripresa e gestione «Le tue voci».
   La parte pura (VcCore) non tocca il DOM ed e' testata con node:test;
   il ramo DOM parte solo nel browser. Caricato prima di app.js: app.js
   chiama vcSyncButton() dopo ogni cambio di modello/lingua/tab. */
(function () {
  'use strict';

  /* ---------- nucleo puro ---------- */

  var GATE_REASONS = ['short', 'long', 'noise', 'pauses', 'nopause', 'band', 'clip', 'transcript', 'format', 'asr'];
  var ACCEPTED_EXT = ['wav', 'mp3', 'webm', 'opus', 'ogg', 'm4a', 'mp4'];

  function vcPanelFor(state) {
    if (state === 'sample_ok') return 3;
    if (state === 'paid' || state === 'demos_generating' || state === 'demos_ready' || state === 'demo_failed') return 4;
    return 0;
  }

  /* Il server manda la chiave i18n gia' intera ('vc_gate_short'), il nucleo
     accetta anche il motivo nudo ('short'): senza questa normalizzazione ogni
     scarto cadeva su vc_gate_generic e l'utente leggeva sempre «Campione non
     accettato», senza sapere che cosa correggere. */
  function vcGateKey(reason) {
    var r = String(reason == null ? '' : reason).replace(/^vc_gate_/, '');
    return GATE_REASONS.indexOf(r) >= 0 ? 'vc_gate_' + r : 'vc_gate_generic';
  }

  /* Il gate scarta per piu' motivi insieme (durata + rumore + pause) ma la
     risposta ne mette uno solo in `reason`: la lista intera viaggia in
     metrics.reasons. Mostrarli tutti evita all'utente il ping-pong «correggo
     un difetto, scopro il successivo». */
  function vcGateKeys(d) {
    var mt = (d && d.metrics) || {};
    var raw = (Array.isArray(mt.reasons) && mt.reasons.length) ? mt.reasons : [d && d.reason];
    var out = [];
    for (var i = 0; i < raw.length; i++) {
      var k = vcGateKey(raw[i]);
      if (k !== 'vc_gate_generic' && out.indexOf(k) < 0) out.push(k);
    }
    return out.length ? out : ['vc_gate_generic'];
  }

  function vcPending(mine) {
    if (!Array.isArray(mine)) return null;
    for (var i = 0; i < mine.length; i++) if (mine[i] && mine[i].pending) return mine[i];
    return null;
  }

  function vcHasReadyFor(mine, lang) {
    if (!Array.isArray(mine)) return false;
    for (var i = 0; i < mine.length; i++) {
      var m = mine[i];
      if (m && m.state === 'ready' && m.voice_id && m.lang === lang) return true;
    }
    return false;
  }

  function vcButtonKey(mine) {
    if (vcPending(mine)) return 'vc_btn_resume';
    return (Array.isArray(mine) && mine.length) ? 'vc_btn_mine' : 'vc_btn_start';
  }

  function vcVisible(cfg, voxAvailable, lang) {
    if (!cfg || !cfg.enabled || !voxAvailable) return false;
    var langs = cfg.languages || {};
    return Array.isArray(langs[lang]) && langs[lang].length > 0;
  }

  function vcUploadCheck(name, size, maxMb) {
    var m = /\.([A-Za-z0-9]+)$/.exec(name || '');
    var ext = m ? m[1].toLowerCase() : '';
    if (ACCEPTED_EXT.indexOf(ext) < 0) return {ok: false, reason: 'format'};
    if (size > maxMb * 1024 * 1024) return {ok: false, reason: 'too_large'};
    return {ok: true, ext: ext};
  }

  function vcRecordExt(mime) {
    var base = String(mime || '').split(';')[0].trim();
    if (base === 'audio/mp4') return 'mp4';
    if (base === 'audio/ogg') return 'ogg';
    return 'webm';
  }

  var VcCore = {
    vcPanelFor: vcPanelFor, vcGateKey: vcGateKey, vcGateKeys: vcGateKeys, vcPending: vcPending,
    vcHasReadyFor: vcHasReadyFor, vcButtonKey: vcButtonKey, vcVisible: vcVisible,
    vcUploadCheck: vcUploadCheck, vcRecordExt: vcRecordExt,
    ACCEPTED_EXT: ACCEPTED_EXT,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = VcCore;

  /* ---------- ramo DOM ---------- */

  if (typeof window === 'undefined') return;
  window.VcCore = VcCore;

  var S = {cfg: null, mine: [], cur: null, media: null, es: null};
  window._vcState = S;
  window._vcJustCreated = null;

  function $(id) { return document.getElementById(id); }
  function _val(id) { var el = $(id); return el ? el.value : ''; }
  function tt(k, r) { return (typeof t === 'function') ? t(k, r) : k; }

  /* Il motivo dello scarto va letto dove si e' sbagliato: finche' il pannello
     2 e' a schermo il messaggio esce sotto registrazione e caricamento, non in
     cima al modal (li' l'utente, che guardava il bottone, non lo vedeva). */
  function vcErr(msg) {
    var p2 = $('vcP2'); var sotto = $('vcErr2');
    var tgt = (sotto && p2 && !p2.hidden) ? sotto : $('vcErr');
    [$('vcErr'), $('vcErr2')].forEach(function (e) {
      if (e) { e.hidden = true; e.textContent = ''; }
    });
    if (!msg || !tgt) return;
    tgt.textContent = msg; tgt.hidden = false;
  }

  /* La registrazione resta ascoltabile anche quando il campione viene
     scartato: e' l'unico modo per accorgersi da soli di aver letto male, il
     campione del server nasce solo se il controllo passa. L'URL precedente va
     revocato o ogni tentativo si lascia dietro un blob in memoria. */
  function vcSetLocalAudio(blob) {
    if (S.localUrl) { try { URL.revokeObjectURL(S.localUrl); } catch (e) {} S.localUrl = null; }
    var a = $('vcLocalAudio'); var blk = $('vcLocalBlock');
    if (!a || !blk) return;
    try { a.pause(); } catch (e) {}
    if (!blob) { a.removeAttribute('src'); blk.hidden = true; return; }
    S.localUrl = URL.createObjectURL(blob);
    a.src = S.localUrl; blk.hidden = false;
  }

  /* Perche' il campione e' stato scartato: tutti i motivi, e per la durata
     anche i secondi misurati e la finestra ammessa (che arriva dalla config,
     non e' cablata nella frase). Se l'ASR ha capito altro glielo si fa
     leggere: e' l'unico modo perche' capisca che cosa ha sbagliato. */
  function vcRejectMsg(d) {
    var cfg = S.cfg || {};
    var mt = (d && d.metrics) || {};
    var dur = Number(mt.duration);
    var rep = {got: isFinite(dur) && dur > 0 ? dur.toFixed(1) : '?',
               min: Math.round(Number(cfg.min_sec) || 12),
               max: Math.round(Number(cfg.max_sec) || 20)};
    var keys = vcGateKeys(d);
    var msg = keys.map(function (k) { return tt(k, rep); }).join(' ');
    var heard = (d && d.heard || '').trim();
    if (heard && keys.indexOf('vc_gate_transcript') >= 0) msg += ' ' + tt('vc_gate_heard', {heard: heard});
    return msg;
  }

  /* Messaggio per una risposta d'errore dell'API: chiave i18n per codice,
     altrimenti il testo generico. Mai il testo grezzo del server. */
  function vcApiErrMsg(d, fallbackKey) {
    var code = d && d.error_code;
    if (code === 'rate_limited') return tt('vc_err_rate_limited', {n: (d && d.retry_after) || 60});
    if (code === 'sample_rejected') return vcRejectMsg(d);
    /* Il limite va detto: senza il segnaposto l'utente leggeva «il limite e' {mb} MB». */
    if (code === 'too_large') return tt('vc_err_too_large', {mb: (S.cfg && S.cfg.max_upload_mb) || 20});
    var k = code ? 'vc_err_' + code : (fallbackKey || 'vc_err_generic');
    var s = tt(k);
    return (s && s !== k) ? s : tt(fallbackKey || 'vc_err_generic');
  }

  function vcFetch(url, opts) {
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        return {ok: r.ok, status: r.status, data: d};
      });
    });
  }

  function vcPost(url, body) {
    return vcFetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  }

  function vcRefreshMine() {
    return vcFetch('/api/voice_clone/mine').then(function (r) {
      S.mine = (r.ok && Array.isArray(r.data.voices)) ? r.data.voices : [];
      return S.mine;
    }).catch(function () { S.mine = []; return S.mine; });
  }
  window.vcRefreshMine = vcRefreshMine;

  function vcLang() {
    return (typeof bookLangState === 'object' && bookLangState && bookLangState.code) ? bookLangState.code : 'it';
  }

  function vcVoxSelected() {
    var vm = $('vmPremium');
    var voxOk = (typeof voices === 'object' && voices && voices._voxcpm && voices._voxcpm.available);
    var inPremium = !!(typeof wizardState === 'object' && wizardState && wizardState.audioTab === 'premium');
    return !!(vm && vm.value === 'voxcpm' && voxOk && inPremium);
  }

  /* Il microfono accanto alla combo compare solo con il modello VoxCPM scelto
     sulla scheda PREMIUM, feature attiva e lingua del libro offerta. Il bottone
     non porta etichetta: lo stato (crea / le tue voci / riprendi) lo decide
     vcOpen(), e la ripresa ha comunque il suo banner sotto la combo. */
  function vcSyncButton() {
    var row = $('vcBtnRow'); var btn = $('vcOpenBtn'); var banner = $('vcResumeBanner');
    if (!btn) return;
    var show = vcVoxSelected() && vcVisible(S.cfg, true, vcLang());
    btn.hidden = !show;
    var tip = tt('vc_btn_tip');
    btn.title = tip; btn.setAttribute('aria-label', tip);
    var pend = show && !!vcPending(S.mine);
    if (row) row.hidden = !pend;
    if (banner) banner.hidden = !pend;
  }
  window.vcSyncButton = vcSyncButton;

  function vcShow(n) {
    ['vcP1', 'vcPSetup', 'vcP2', 'vcP3', 'vcP4', 'vcPMine'].forEach(function (id) { var e = $(id); if (e) e.hidden = true; });
    var id = (n === 'mine' || n === 'setup') ? ('vcP' + n.charAt(0).toUpperCase() + n.slice(1)) : ('vcP' + n);
    var e = $(id); if (e) e.hidden = false;
    vcErr('');
    var m = $('vcModal'); if (m) m.hidden = false;
    var hooks = S.panelHooks || {};
    if (typeof hooks[id] === 'function') hooks[id]();
  }
  window.vcShow = vcShow;

  function vcClose() {
    var m = $('vcModal'); if (m) m.hidden = true;
    if (S.es) { try { S.es.close(); } catch (e) {} S.es = null; }
    if (S.esTimer) { clearTimeout(S.esTimer); S.esTimer = null; }
    if (typeof S.abortMedia === 'function') S.abortMedia();
    /* Il blob della registrazione locale muore col modal: tenerlo vivo
       significherebbe un URL object mai revocato per ogni apertura. */
    vcSetLocalAudio(null);
  }
  window.vcClose = vcClose;

  /* Apre il wizard dal bottone: in sospeso -> pannello dello stato;
     con voci -> «Le tue voci»; altrimenti condizioni. */
  function vcOpen(force) {
    vcRefreshMine().then(function (mine) {
      if (force) return vcShow(force);
      var p = vcPending(mine);
      if (p) return vcResume(p.id);
      vcShow(mine.length ? 'mine' : 1);
    });
  }
  window.vcOpen = vcOpen;

  /* Ripresa di una procedura: rilegge la vista e apre il pannello dello stato. */
  function vcResume(cloneId) {
    var rec = null;
    for (var i = 0; i < S.mine.length; i++) if (S.mine[i].id === cloneId) rec = S.mine[i];
    if (!rec) return vcShow(1);
    S.cur = {clone_id: rec.id, view: rec, voice_code: rec.voice_code || null};
    var n = vcPanelFor(rec.state);
    if (n === 0) return vcShow('mine');
    vcShow(n);
  }
  window.vcResume = vcResume;

  function vcInitPanel1() {
    /* Il codice-voce di un'altra persona si aggiunge anche senza aver mai
       campionato la propria: da qui si salta alla sezione che lo accetta. */
    var claim = $('vcP1Claim');
    if (claim) claim.onclick = function () { if (S.busy) return; vcShow('mine'); };
    var c = $('vcConsent'); var next = $('vcP1Next');
    if (!c || !next) return;
    c.checked = false; next.disabled = true;
    c.onchange = function () { next.disabled = !c.checked; };
    next.onclick = function () { if (c.checked) vcShow('setup'); };
    var cancel = $('vcP1Cancel'); if (cancel) cancel.onclick = vcClose;
    var price = $('vcP1Price');
    if (price && S.cfg) price.textContent = S.cfg.free ? tt('vc_price_free') : tt('vc_price', {p: Number(S.cfg.price_eur).toFixed(2)});
  }

  /* ---------- pannello delle scelte: lingua, accento, voce ---------- */

  /* L'icona della voce segue la scelta: e' l'unica delle tre che cambia
     davvero forma, e rende evidente che la combo si puo' toccare. */
  function vcSyncGenderIcon() {
    var g = $('vcGender'); if (!g) return;
    var f = $('vcGenderIcoF'); var m = $('vcGenderIcoM');
    if (f) f.hidden = g.value !== 'f';
    if (m) m.hidden = g.value !== 'm';
  }

  function vcInitPanelSetup() {
    var ls = $('vcLang');
    /* Solo alla prima apertura: ripopolare azzererebbe la scelta appena
       fatta ogni volta che si torna indietro dal brano. */
    if (ls && !ls.options.length) vcFillLangs();
    vcSyncGenderIcon();
    var g = $('vcGender'); if (g) g.onchange = vcSyncGenderIcon;
    var back = $('vcSetupBack'); if (back) back.onclick = function () { if (S.busy) return; vcShow(1); };
    var next = $('vcSetupNext'); if (next) next.onclick = function () { if (S.busy) return; vcShow(2); };
  }

  /* ---------- pannello 2: campione ---------- */

  var REC_MAX_MS = 25000;

  function vcFillLangs() {
    var ls = $('vcLang'); var loc = $('vcLocale');
    if (!ls || !loc || !S.cfg) return;
    var langs = S.cfg.languages || {};
    ls.innerHTML = '';
    Object.keys(langs).sort().forEach(function (l) {
      var o = document.createElement('option'); o.value = l;
      o.textContent = (typeof _langLabel === 'function') ? _langLabel(l) : l.toUpperCase();
      ls.appendChild(o);
    });
    var cur = vcLang();
    if (langs[cur]) ls.value = cur;
    vcFillLocales();
    ls.onchange = vcFillLocales;
  }

  function vcFillLocales() {
    var ls = $('vcLang'); var loc = $('vcLocale');
    var list = (S.cfg && S.cfg.languages && S.cfg.languages[ls.value]) || [];
    loc.innerHTML = '';
    list.forEach(function (l) {
      var o = document.createElement('option'); o.value = l;
      o.textContent = (typeof _voxcpmLocaleLabel === 'function') ? _voxcpmLocaleLabel(l) : l;
      loc.appendChild(o);
    });
    var pre = (typeof _voxcpmAccentSel === 'string') ? _voxcpmAccentSel : '';
    if (pre && list.indexOf(pre) >= 0) loc.value = pre;
    /* Una lingua con un solo accento non e' una scelta: la combo sparisce ma
       resta popolata, cosi' il valore inviato al server non cambia. */
    var wrap = $('vcLocaleWrap'); if (wrap) wrap.hidden = list.length < 2;
  }

  function vcLoadPrompt() {
    var box = $('vcPromptText'); if (!box) return;
    box.textContent = '…';
    var lang = $('vcLang').value; var gender = $('vcGender').value;
    vcFetch('/api/voice_clone/prompt?lang=' + encodeURIComponent(lang) + '&gender=' + encodeURIComponent(gender)).then(function (r) {
      if (!r.ok) { box.textContent = ''; vcErr(vcApiErrMsg(r.data)); return; }
      box.textContent = r.data.text || '';
      S.promptVersion = r.data.version;
    });
  }

  /* Registrare e caricare sono due strade alternative: mentre una e' in corso
     l'altra non serve, e il riquadro tratteggiato ruberebbe la scena
     all'attesa. Sparisce, e lo spinner resta l'unica cosa che si muove. */
  function vcSetUploadVisible(on) {
    var blk = $('vcUpBlock'); if (blk) blk.hidden = !on;
  }

  function vcSetRecording(on) {
    var b = $('vcRecBtn'); var dot = $('vcRecDot'); var ann = $('vcRecCancel');
    if (b) b.textContent = tt(on ? 'vc_rec_stop' : 'vc_rec_start');
    if (dot) dot.hidden = !on;
    /* «Annulla» esiste solo mentre si registra: fuori da li' non c'e' niente
       da buttare via e resterebbe un bottone senza effetto. */
    if (ann) ann.hidden = !on;
    /* Solo la partenza nasconde: lo stop porta dritto alla verifica, che
       tiene il riquadro nascosto senza farlo lampeggiare per un callback. */
    if (on) vcSetUploadVisible(false);
  }

  /* Chi si accorge a meta' frase di aver letto male butta via il tentativo
     senza aspettare il verdetto del server: vcAbortMedia marca la sessione
     come abbandonata, cosi' rec.onstop non carica nulla. */
  function vcCancelRecording() {
    if (!S.media) return;
    vcAbortMedia();
    var timer = $('vcTimer'); if (timer) timer.textContent = '0.0 s';
    var meter = $('vcLevel'); if (meter) meter.value = 0;
    vcErr('');
  }

  /* Quale microfono sta registrando. Finche' il permesso non e' stato dato il
     browser restituisce dispositivi senza id ne' nome: in quel caso resta la
     sola voce «predefinito» e la lista viene rifatta dopo il primo
     getUserMedia, quando i nomi diventano leggibili. */
  function vcFillMics(preferito) {
    var sel = $('vcMic'); var wrap = $('vcMicWrap');
    if (!sel) return Promise.resolve();
    var md = navigator.mediaDevices;
    if (!md || !md.enumerateDevices) { if (wrap) wrap.hidden = true; return Promise.resolve(); }
    var tenere = preferito || sel.value;
    return md.enumerateDevices().then(function (devs) {
      var ins = (devs || []).filter(function (d) { return d.kind === 'audioinput' && d.deviceId; });
      sel.innerHTML = '';
      if (!ins.length) {
        var o0 = document.createElement('option');
        o0.value = ''; o0.textContent = tt('vc_mic_default');
        sel.appendChild(o0);
      } else {
        ins.forEach(function (d, i) {
          var o = document.createElement('option');
          o.value = d.deviceId;
          o.textContent = d.label || (tt('vc_mic') + ' ' + (i + 1));
          sel.appendChild(o);
        });
      }
      if (tenere) { sel.value = tenere; if (sel.value !== tenere) sel.selectedIndex = 0; }
      if (wrap) wrap.hidden = false;
    }).catch(function () {});
  }

  /* Guardia anti doppio invio: mentre il campione e' in upload, niente
     seconda registrazione, niente secondo file, niente uscita dal pannello
     (due risposte concorrenti scriverebbero S.cur/vcSampleAudio a caso). */
  function vcSetBusy(on) {
    S.busy = !!on;
    var b = $('vcRecBtn'); if (b) b.disabled = !!on;
    var f = $('vcFile'); if (f) f.disabled = !!on;
    var back = $('vcP2Back'); if (back) back.disabled = !!on;
    var back3 = $('vcP3Back'); if (back3) back3.disabled = !!on;
    var pay = $('vcPayBtn'); if (pay) pay.disabled = !!on;
    ['vcApprove', 'vcReject', 'vcRejectYes', 'vcRejectNo', 'vcReject2', 'vcRetry',
      'vcClaimBtn', 'vcConfirmBtn', 'vcNewVoice'].forEach(function (id) {
      var e = $(id); if (e) e.disabled = !!on;
    });
  }

  function vcStopMedia() {
    var m = S.media; S.media = null;
    if (!m) return;
    try { if (m.rec && m.rec.state !== 'inactive') m.rec.stop(); } catch (e) {}
    try { if (m.timer) clearInterval(m.timer); } catch (e) {}
    try { if (m.stream) m.stream.getTracks().forEach(function (tr) { tr.stop(); }); } catch (e) {}
    try { if (m.ctx) m.ctx.close(); } catch (e) {}
    vcSetRecording(false);
  }
  S.stopMedia = vcStopMedia;

  /* Annullamento esplicito della registrazione in corso (chiusura del modal,
     «Indietro» dal pannello 2): marca la sessione come abbandonata PRIMA di
     fermarla, cosi' rec.onstop (che arriva dopo, in modo asincrono, quando
     S.media e' gia' stato azzerato da vcStopMedia) sa di non dover caricare
     nulla. Lo stop dal bottone e quello automatico a 25 s restano conferme:
     passano da vcStopMedia() senza mai passare da qui. */
  function vcAbortMedia() {
    if (S.media) S.media.aborted = true;
    vcStopMedia();
    /* Qui la registrazione non diventa un campione: il riquadro torna. */
    vcSetUploadVisible(true);
  }
  S.abortMedia = vcAbortMedia;

  /* Registrazione: niente cancellazione dell'eco, niente soppressione del
     rumore, niente guadagno automatico (spec §3.3): il modello vuole la voce
     com'e'. Livello con AnalyserNode; stop automatico a 25 s. */
  function vcStartRecording() {
    if (!navigator.mediaDevices || !window.MediaRecorder) { vcErr(tt('vc_err_no_mic')); return; }
    vcErr('');
    var vincoli = {echoCancellation: false, noiseSuppression: false, autoGainControl: false};
    var voluto = _val('vcMic');
    if (voluto) vincoli.deviceId = {exact: voluto};
    navigator.mediaDevices.getUserMedia({audio: vincoli}).then(function (stream) {
      /* Col permesso appena concesso i nomi dei dispositivi diventano
         leggibili: si rifa' la lista e si seleziona quello che sta davvero
         registrando, cosi' l'utente vede su che microfono sta parlando. */
      var tr0 = stream.getAudioTracks()[0];
      var conf = (tr0 && tr0.getSettings) ? tr0.getSettings() : {};
      vcFillMics(conf.deviceId || voluto);
      var mime = '';
      ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'].some(function (m) {
        if (MediaRecorder.isTypeSupported(m)) { mime = m; return true; } return false;
      });
      var rec = mime ? new MediaRecorder(stream, {mimeType: mime}) : new MediaRecorder(stream);
      var chunks = [];
      var ctx = new (window.AudioContext || window.webkitAudioContext)();
      var src = ctx.createMediaStreamSource(stream);
      var an = ctx.createAnalyser(); an.fftSize = 512; src.connect(an);
      var buf = new Uint8Array(an.fftSize);
      var t0 = Date.now();
      var meter = $('vcLevel'); var timer = $('vcTimer');
      var tick = setInterval(function () {
        an.getByteTimeDomainData(buf);
        var peak = 0;
        for (var i = 0; i < buf.length; i++) { var v = Math.abs(buf[i] - 128) / 128; if (v > peak) peak = v; }
        if (meter) meter.value = peak;
        var el = (Date.now() - t0) / 1000;
        if (timer) timer.textContent = el.toFixed(1) + ' s';
        if (el * 1000 >= REC_MAX_MS) vcStopMedia();
      }, 100);
      var session = {rec: rec, stream: stream, ctx: ctx, timer: tick, aborted: false};
      rec.ondataavailable = function (ev) { if (ev.data && ev.data.size) chunks.push(ev.data); };
      rec.onstop = function () {
        /* Pulizia solo se S.media appartiene ancora a QUESTA registrazione.
           Uno stop manuale ha gia' azzerato S.media (e chiamato vcStopMedia)
           in modo sincrono prima che questo callback arrivi: qui S.media e'
           gia' null o, se nel frattempo e' partita una nuova registrazione,
           punta al rec della sessione successiva. In entrambi i casi va
           lasciato stare, altrimenti si ripulirebbe/ucciderebbe la
           registrazione nuova al posto di questa. Solo lo stop non richiesto
           dall'utente (dispositivo scollegato) lascia S.media ancora
           puntato su questo rec: e' l'unico caso in cui la pulizia serve
           qui, timer/pallino/stream compresi. */
        if (S.media && S.media.rec === rec) vcStopMedia();
        /* `session` e' catturato per closure, non riletto da S.media (che a
           questo punto e' gia' null per qualunque stop passato da
           vcStopMedia): e' l'unico modo per sapere, qui, se QUESTA sessione
           e' stata annullata da vcAbortMedia invece che confermata. */
        if (session.aborted) return;
        var blob = new Blob(chunks, {type: rec.mimeType || mime || 'audio/webm'});
        var ext = vcRecordExt(rec.mimeType || mime);
        vcUploadSample(blob, 'sample.' + ext);
      };
      S.media = session;
      vcSetRecording(true);
      rec.start();
    }).catch(function () { vcErr(tt('vc_err_no_mic')); });
  }

  function vcUploadSample(blob, filename) {
    if (S.busy) return;
    vcSetBusy(true);
    vcSetLocalAudio(blob);
    var fd = new FormData();
    fd.append('file', blob, filename);
    fd.append('lang', _val('vcLang'));
    fd.append('locale', _val('vcLocale'));
    fd.append('gender', _val('vcGender'));
    var wait = $('vcUploading'); if (wait) wait.hidden = false;
    vcSetUploadVisible(false);
    var blk = $('vcSampleBlock'); if (blk) blk.hidden = true;
    vcErr('');
    vcFetch('/api/voice_clone/sample', {method: 'POST', body: fd}).then(function (r) {
      if (wait) wait.hidden = true;
      vcSetBusy(false);
      /* Solo lo scarto riapre la strada alternativa: col campione accettato
         un «scegli un file» ancora li' inviterebbe a rifare quel che e' fatto. */
      if (!r.ok) { vcSetUploadVisible(true); vcErr(vcApiErrMsg(r.data, 'vc_err_generic')); return; }
      S.cur = {clone_id: r.data.clone_id, view: r.data, lang: _val('vcLang'), locale: _val('vcLocale'), gender: _val('vcGender'), voice_code: null};
      var a = $('vcSampleAudio');
      if (a) { a.src = '/api/voice_clone/' + encodeURIComponent(r.data.clone_id) + '/sample.wav?ts=' + Date.now(); }
      /* Campione accettato: si ascolta quello normalizzato dal server, non la
         copia locale, altrimenti resterebbero due lettori uno sopra l'altro. */
      vcSetLocalAudio(null);
      if (blk) blk.hidden = false;
    }).catch(function () { if (wait) wait.hidden = true; vcSetUploadVisible(true); vcSetBusy(false); vcErr(tt('vc_err_generic')); });
  }

  function vcInitPanel2() {
    vcStopMedia();
    vcSetBusy(false);
    var blk = $('vcSampleBlock'); if (blk) blk.hidden = true;
    var wait = $('vcUploading'); if (wait) wait.hidden = true;
    vcSetUploadVisible(true);
    var timer = $('vcTimer'); if (timer) timer.textContent = '0.0 s';
    var nome = $('vcUpName'); if (nome) nome.textContent = '';
    vcSetLocalAudio(null);
    /* Il limite va scritto, non promesso: `data-t` applica t() senza
       sostituzioni, quindi un {mb} nella frase resterebbe a video tale e
       quale. Il numero sta in un elemento suo, cosi' sopravvive anche a un
       cambio di lingua dell'interfaccia. */
    var mb = $('vcUpMb');
    if (mb) mb.textContent = ((S.cfg && S.cfg.max_upload_mb) || 20) + ' MB';
    vcFillMics();
    vcLoadPrompt();
    $('vcRecBtn').onclick = function () { if (S.busy) return; if (S.media) vcStopMedia(); else vcStartRecording(); };
    $('vcRecCancel').onclick = vcCancelRecording;
    $('vcFile').onchange = function () {
      if (S.busy) { this.value = ''; return; }
      var f = this.files && this.files[0]; if (!f) return;
      if (nome) nome.textContent = f.name;
      var chk = vcUploadCheck(f.name, f.size, (S.cfg && S.cfg.max_upload_mb) || 20);
      if (!chk.ok) { vcErr(tt(chk.reason === 'too_large' ? 'vc_err_too_large' : 'vc_gate_format', {mb: (S.cfg && S.cfg.max_upload_mb) || 20})); this.value = ''; return; }
      vcUploadSample(f, f.name);
      this.value = '';
    };
    $('vcSampleRedo').onclick = function () {
      if (blk) blk.hidden = true;
      vcSetUploadVisible(true);
      var a = $('vcSampleAudio'); if (a) { a.pause(); a.removeAttribute('src'); }
      /* Si riparte da zero: via anche la copia locale e il nome del file, o
         resterebbero a schermo appesi al tentativo precedente. */
      vcSetLocalAudio(null);
      if (nome) nome.textContent = '';
      var tm = $('vcTimer'); if (tm) tm.textContent = '0.0 s';
    };
    $('vcSampleNext').onclick = function () { if (S.cur && S.cur.clone_id) vcShow(3); };
    $('vcP2Back').onclick = function () { if (S.busy) return; vcAbortMedia(); vcShow('setup'); };
  }

  /* ---------- pannello 3: email e pagamento ---------- */

  function vcEmailsOk() {
    var a = ($('vcEmail').value || '').trim(); var b = ($('vcEmail2').value || '').trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(a)) { vcErr(tt('vc_err_email_bad')); return false; }
    if (a.toLowerCase() !== b.toLowerCase()) { vcErr(tt('vc_err_email_mismatch')); return false; }
    if (S.emailTaken) { vcErr(tt('vc_err_email_has_voice')); return false; }
    return true;
  }

  /* L'indirizzo si verifica appena e' stato battuto: accorgersi a pagamento
     avvenuto che quella email ha gia' una voce e' il momento peggiore per
     accorgersene. Finche' risulta occupata il bottone paga resta spento. */
  function vcCheckEmailTaken() {
    var a = ($('vcEmail').value || '').trim(); var b = ($('vcEmail2').value || '').trim();
    if (!S.cur || !S.cur.clone_id) return;
    if (a.toLowerCase() !== b.toLowerCase()) return;
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(a)) return;
    vcPost('/api/voice_clone/check_email', {clone_id: S.cur.clone_id, email: a}).then(function (r) {
      if (!r.ok) return;
      var era = !!S.emailTaken;
      S.emailTaken = !!r.data.taken;
      var pb = $('vcPayBtn');
      if (S.emailTaken) { vcErr(tt('vc_err_email_has_voice')); if (pb) pb.disabled = true; }
      else { if (era) vcErr(''); if (pb) pb.disabled = false; }
    });
  }

  function vcCommit(paymentToken) {
    var body = {clone_id: S.cur.clone_id, email: $('vcEmail').value.trim(), email2: $('vcEmail2').value.trim(),
                payment_token: paymentToken || ''};
    vcSetBusy(true);
    vcPost('/api/voice_clone/commit', body).then(function (r) {
      vcSetBusy(false);
      if (!r.ok) {
        var m = $('vcModal'); if (m) m.hidden = false;
        vcShow(3); vcErr(vcApiErrMsg(r.data)); return;
      }
      S.cur.voice_code = r.data.voice_code || null;
      S.cur.view = {id: r.data.clone_id, state: 'paid'};
      vcShow(4);
    }).catch(function () { vcSetBusy(false); vcShow(3); vcErr(tt('vc_err_generic')); });
  }

  /* Gratis -> commit diretto. A pagamento -> il modal di pagamento gia' in
     uso per le voci premium (PayPal o voucher), poi commit col token. Il
     modal del wizard si nasconde intanto: i due hanno lo stesso z-index. */
  function vcPay() {
    if (!S.cur || !S.cur.clone_id) { vcShow(2); return; }
    if (!vcEmailsOk()) return;
    vcErr('');
    if (S.cfg && S.cfg.free) { vcCommit(''); return; }
    if (typeof _openPayModalCtx !== 'function') { vcErr(tt('vc_err_generic')); return; }
    var price = Number(S.cfg.price_eur) || 0;
    var m = $('vcModal'); if (m) m.hidden = true;
    _openPayModalCtx({
      lines: [{labelKey: 'vc_pay_line', amount: price}],
      total: price, geminiAmount: 0,
      voucherPurpose: 'voice_clone',
      // Incassato il pagamento non resta nulla da decidere: l'elaborazione del
      // campione parte subito, senza il giro di conferma del flusso premium.
      autoConfirm: true,
      titleKey: 'vc_pay_title', noticeKey: 'vc_pay_notice',
      paypal: {endpoint: '/api/paypal_create_order_voice_clone',
               buildBody: function () { return {clone_id: S.cur.clone_id}; },
               captureJobId: 'vc:' + S.cur.clone_id},
      onConfirm: function (token) { vcCommit(token); },
      onCancel: function () { if (m) m.hidden = false; vcShow(3); },
    });
    // Precompila il campo email del buono con quella gia' battuta sul
    // pannello 3: evita di ridigitarla, l'utente puo' comunque cambiarla.
    var ve = document.getElementById('geminiPayVoucherEmail');
    if (ve) ve.value = $('vcEmail').value.trim();
  }

  function vcInitPanel3() {
    var price = $('vcPrice');
    if (price && S.cfg) price.textContent = S.cfg.free ? tt('vc_price_free') : tt('vc_price', {p: Number(S.cfg.price_eur).toFixed(2)});
    var pb = $('vcPayBtn'); if (pb) { pb.disabled = false; pb.textContent = tt(S.cfg && S.cfg.free ? 'vc_pay_btn_free' : 'vc_pay_btn'); pb.onclick = vcPay; }
    $('vcP3Back').onclick = function () { if (S.busy) return; vcShow(2); };
    /* La bozza vive sul server da quando il campione e' stato accettato, ma
       l'utente che aveva chiuso la finestra non lo sa: riaprendo si ritrovava
       davanti al pagamento senza capire quale campione stesse pagando. Qui il
       campione si riascolta, si rifa' o si butta via. */
    var sam = $('vcP3Sample');
    if (sam && S.cur && S.cur.clone_id) {
      sam.src = '/api/voice_clone/' + encodeURIComponent(S.cur.clone_id) + '/sample.wav?ts=' + Date.now();
    }
    var redo = $('vcP3Redo');
    if (redo) redo.onclick = function () { if (S.busy) return; vcShow(2); };
    /* Conferma in linea come il rifiuto delle prove: una finestra di conferma
       del browser bloccherebbe tutto e stonerebbe col resto del wizard. */
    var ask = $('vcP3DiscardAsk'); if (ask) ask.hidden = true;
    var del = $('vcP3Discard');
    if (del) del.onclick = function () { if (S.busy) return; if (ask) ask.hidden = false; };
    var no = $('vcP3DiscardNo');
    if (no) no.onclick = function () { if (S.busy) return; if (ask) ask.hidden = true; };
    var si = $('vcP3DiscardYes');
    if (si) si.onclick = vcDiscardDraft;
    S.emailTaken = false;
    var e1 = $('vcEmail'); if (e1) e1.onblur = vcCheckEmailTaken;
    var e2 = $('vcEmail2'); if (e2) { e2.onblur = vcCheckEmailTaken; e2.onchange = vcCheckEmailTaken; }
  }

  /* Prima del pagamento non esiste il link di gestione (l'email si indica
     qui): senza questa via d'uscita la bozza resterebbe in piedi fino alla
     scadenza e il bottone del campionamento direbbe «riprendi» per sempre. */
  function vcDiscardDraft() {
    if (S.busy || !S.cur || !S.cur.clone_id) return;
    var id = S.cur.clone_id;
    vcErr('');
    vcSetBusy(true);
    vcPost('/api/voice_clone/' + encodeURIComponent(id) + '/discard', {}).then(function (r) {
      vcSetBusy(false);
      if (!r.ok) { vcErr(vcApiErrMsg(r.data)); return; }
      S.cur = {};
      var ask2 = $('vcP3DiscardAsk'); if (ask2) ask2.hidden = true;
      var sam = $('vcP3Sample');
      if (sam) { try { sam.pause(); } catch (e) {} sam.removeAttribute('src'); }
      vcRefreshMine().then(function () { vcSyncButton(); vcShow(1); });
    }).catch(function () { vcSetBusy(false); vcErr(tt('vc_err_generic')); });
  }

  /* ---------- pannello 4: attesa, demo, decisione ---------- */

  function vcRenderP4(view) {
    S.cur.view = view;
    var st = view.state;
    var show = function (id, on) { var e = $(id); if (e) e.hidden = !on; };
    var demosOn = st === 'demos_ready';
    show('vcWait', st === 'paid' || st === 'demos_generating');
    show('vcDemos', demosOn);
    show('vcFailed', st === 'demo_failed');
    show('vcDone', st === 'ready');
    show('vcRefunded', st === 'refunded' || st === 'expired' || st === 'deleted');
    if (!demosOn) {
      /* Retry o cambio di stato: le due prove smettono di
         suonare, non restano in sottofondo dietro lo spinner o l'esito. */
      ['vcDemoCommon', 'vcDemoExtra'].forEach(function (id) {
        var a = $(id);
        if (a) { try { a.pause(); a.currentTime = 0; } catch (e) {} }
      });
    }
    if (demosOn) {
      var du = view.demo_urls || {};
      var c = $('vcDemoCommon'); var x = $('vcDemoExtra');
      if (c && du.common) c.src = du.common + '?ts=' + Date.now();
      if (x && du.extra) x.src = du.extra + '?ts=' + Date.now();
      var rc = $('vcRejectConfirm'); if (rc) rc.hidden = true;
    }
  }

  /* Avanzamento via SSE: ogni evento e' la vista pubblica; il flusso chiude
     da solo su uno stato finale. Alla chiusura senza stato finale (rete,
     1800 s) si rilegge `mine`. Un solo EventSource per volta (S.es): si
     chiude prima di aprirne un altro, alla chiusura del modal e su stato
     finale; un evento tardivo per un clone_id diverso viene scartato. */
  function vcWatch(retryDelay) {
    if (S.es) { try { S.es.close(); } catch (e) {} S.es = null; }
    if (S.esTimer) { clearTimeout(S.esTimer); S.esTimer = null; }
    if (!S.cur || !S.cur.clone_id || !window.EventSource) return;
    var cloneId = S.cur.clone_id;
    var es = new EventSource('/api/voice_clone/progress/' + encodeURIComponent(cloneId));
    S.es = es;
    es.onmessage = function (ev) {
      if (!S.cur || S.cur.clone_id !== cloneId) { try { es.close(); } catch (e) {} return; }
      var v; try { v = JSON.parse(ev.data); } catch (e) { return; }
      if (!v || !v.state) return;
      vcRenderP4(v);
      if (vcPanelFor(v.state) !== 4 || v.state === 'demos_ready' || v.state === 'demo_failed') { es.close(); S.es = null; }
    };
    /* Rete instabile: non lasciamo il pannello 4 fermo senza avanzamento.
       Rileggiamo `mine` e, se lo stato resta di attesa e il pannello 4 e'
       ancora quello mostrato, riproviamo con un backoff crescente (mai un
       loop stretto) finche' l'utente non chiude il modal o lo stato cambia. */
    es.onerror = function () {
      es.close(); if (S.es === es) S.es = null;
      if (!S.cur || S.cur.clone_id !== cloneId) return;
      var delay = Math.min(Number(retryDelay) || 3000, 30000);
      vcRefreshMine().then(function () {
        if (!S.cur || S.cur.clone_id !== cloneId) return;
        var rec = null;
        for (var i = 0; i < S.mine.length; i++) if (S.mine[i].id === cloneId) rec = S.mine[i];
        if (!rec) return;
        vcRenderP4(rec);
        var p4 = $('vcP4');
        var stillWaiting = rec.state === 'paid' || rec.state === 'demos_generating';
        if (stillWaiting && p4 && !p4.hidden) {
          S.esTimer = setTimeout(function () {
            S.esTimer = null;
            if (S.cur && S.cur.clone_id === cloneId) vcWatch(Math.min(delay * 2, 30000));
          }, delay);
        }
      });
    };
  }

  /* Ogni azione passa dalla guardia anti doppio invio: bottoni disabilitati
     mentre e' in corso, nessuna seconda richiesta finche' la prima non e'
     tornata (successo, errore applicativo o di rete). */
  function vcAction(name, body) {
    if (S.busy) return Promise.resolve(null);
    vcErr('');
    vcSetBusy(true);
    return vcPost('/api/voice_clone/' + encodeURIComponent(S.cur.clone_id) + '/' + name, body || {}).then(function (r) {
      vcSetBusy(false);
      if (!r.ok) { vcErr(vcApiErrMsg(r.data)); return null; }
      vcRenderP4(r.data);
      return r.data;
    }).catch(function () { vcSetBusy(false); vcErr(tt('vc_err_generic')); return null; });
  }

  function vcAfterApprove(view) {
    window._vcJustCreated = view.voice_id || null;
    vcRefreshMine().then(function () {
      if (typeof loadVoices === 'function') {
        Promise.resolve(loadVoices()).then(function () {
          if (typeof updVoicesPremium === 'function') updVoicesPremium();
          vcSyncButton();
        });
      }
    });
  }

  function vcInitPanel4() {
    var cb = $('vcCodeBox');
    if (cb) {
      cb.hidden = !S.cur.voice_code;
      var c = $('vcCode'); if (c) c.textContent = S.cur.voice_code || '';
    }
    $('vcApprove').onclick = function () { vcAction('approve').then(function (v) { if (v) vcAfterApprove(v); }); };
    $('vcReject').onclick = function () { if (S.busy) return; var rc = $('vcRejectConfirm'); if (rc) rc.hidden = false; };
    $('vcRejectNo').onclick = function () { if (S.busy) return; var rc = $('vcRejectConfirm'); if (rc) rc.hidden = true; };
    $('vcRejectYes').onclick = function () { vcAction('reject').then(function (v) { if (v) vcRefreshMine().then(vcSyncButton); }); };
    $('vcReject2').onclick = function () { vcAction('reject').then(function (v) { if (v) vcRefreshMine().then(vcSyncButton); }); };
    $('vcRetry').onclick = function () { vcAction('retry').then(function (v) { if (v) vcWatch(); }); };
    $('vcDoneClose').onclick = function () { if (S.busy) return; vcClose(); };
    $('vcRefundedClose').onclick = function () { if (S.busy) return; vcClose(); };
    vcRenderP4(S.cur.view || {state: 'paid'});
    var st = (S.cur.view || {}).state;
    if (st === 'paid' || st === 'demos_generating') vcWatch();
  }

  /* ---------- pannello «Le tue voci» ---------- */

  function vcStateLabel(m) {
    if (m.state === 'ready') return tt('vc_state_ready');
    if (m.state === 'sample_ok') return tt('vc_state_sample_ok');
    if (m.state === 'paid' || m.state === 'demos_generating') return tt('vc_state_generating');
    if (m.state === 'demos_ready') return tt('vc_state_demos_ready');
    if (m.state === 'demo_failed') return tt('vc_state_demo_failed');
    return m.state;
  }

  function vcRenderMine() {
    var ul = $('vcMineList'); if (!ul) return;
    ul.innerHTML = '';
    if (!S.mine.length) {
      var li0 = document.createElement('li'); li0.className = 'vc-small'; li0.textContent = tt('vc_mine_empty'); ul.appendChild(li0); return;
    }
    S.mine.forEach(function (m) {
      var li = document.createElement('li'); li.className = 'vc-mine-item';
      var head = document.createElement('div');
      var lab = (typeof _voxcpmLocaleLabel === 'function') ? _voxcpmLocaleLabel(m.locale) : m.locale;
      head.textContent = (m.owner ? tt('vc_voice_own') : tt('vc_voice_shared')) + ' · ' + lab + ' · ' + tt(m.gender === 'f' ? 'vc_gender_f' : 'vc_gender_m') + ' — ' + vcStateLabel(m);
      li.appendChild(head);
      if (m.owner && m.voice_code) {
        var code = document.createElement('div'); code.className = 'vc-code'; code.textContent = m.voice_code; li.appendChild(code);
      }
      if (m.sample_url) {
        /* Si riascolta il campione registrato, non una prova sintetizzata:
           era la fonte dell'equivoco («questa non e' la mia voce»). */
        var cap = document.createElement('p'); cap.className = 'vc-small'; cap.textContent = tt('vc_mine_sample');
        li.appendChild(cap);
        var row = document.createElement('div'); row.className = 'vc-sample-row';
        var a = document.createElement('audio'); a.controls = true; a.preload = 'none'; a.src = m.sample_url;
        row.appendChild(a);
        /* «Rimanda l'email» sta qui a destra del player, come icona con
           tooltip: e' un ripiego raro, non merita una riga di bottoni. */
        if (m.owner && m.voice_code) {
          var rb = document.createElement('button');
          rb.type = 'button'; rb.className = 'vc-icon-btn';
          rb.title = tt('vc_resend'); rb.setAttribute('aria-label', tt('vc_resend'));
          rb.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"'
            + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            + '<rect x="3" y="5" width="18" height="14" rx="2"></rect>'
            + '<path d="m3 7 9 6 9-6"></path></svg>';
          rb.onclick = function () { vcAction2(m.id, 'resend').then(function (ok) { if (ok) vcErr(tt('vc_resend_ok')); }); };
          row.appendChild(rb);
        }
        li.appendChild(row);
      }
      var act = document.createElement('div'); act.className = 'vc-actions';
      var mk = function (key, fn) { var b = document.createElement('button'); b.type = 'button'; b.className = 'btn btn-outline btn-sm'; b.textContent = tt(key); b.onclick = fn; act.appendChild(b); return b; };
      if (m.pending) mk('vc_resume_btn', function () { vcResume(m.id); });
      if (!m.owner) mk('vc_forget', function () { vcAction2(m.id, 'forget').then(function (ok) { if (ok) vcOpen('mine'); }); });
      if (act.childNodes.length) li.appendChild(act);
      ul.appendChild(li);
    });
  }

  function vcAction2(id, name) {
    if (S.busy) return Promise.resolve(false);
    vcErr('');
    vcSetBusy(true);
    return vcPost('/api/voice_clone/' + encodeURIComponent(id) + '/' + name, {}).then(function (r) {
      vcSetBusy(false);
      if (!r.ok) { vcErr(vcApiErrMsg(r.data)); return false; }
      return true;
    }).catch(function () { vcSetBusy(false); vcErr(tt('vc_err_generic')); return false; });
  }

  function vcReloadCombo() {
    if (typeof loadVoices !== 'function') return;
    Promise.resolve(loadVoices()).then(function () {
      if (typeof updVoicesPremium === 'function') updVoicesPremium();
      vcSyncButton();
    });
  }

  function vcClaim() {
    if (S.busy) return;
    var code = ($('vcClaimCode').value || '').trim().toUpperCase();
    if (!code) return;
    vcErr('');
    vcSetBusy(true);
    vcPost('/api/voice_clone/claim', {voice_code: code}).then(function (r) {
      vcSetBusy(false);
      if (!r.ok) { vcErr(vcApiErrMsg(r.data)); return; }
      var row = $('vcConfirmRow');
      if (r.data.status === 'pending') { if (row) row.hidden = false; $('vcConfirmCode').value = ''; $('vcConfirmCode').focus(); return; }
      if (row) row.hidden = true;
      vcOpen('mine'); vcReloadCombo();
    }).catch(function () { vcSetBusy(false); vcErr(tt('vc_err_generic')); });
  }

  function vcConfirm() {
    if (S.busy) return;
    var code = ($('vcClaimCode').value || '').trim().toUpperCase();
    var cc = ($('vcConfirmCode').value || '').trim();
    if (!code || !cc) return;
    vcErr('');
    vcSetBusy(true);
    vcPost('/api/voice_clone/confirm', {voice_code: code, confirm_code: cc}).then(function (r) {
      vcSetBusy(false);
      if (!r.ok) { vcErr(vcApiErrMsg(r.data)); return; }
      var row = $('vcConfirmRow'); if (row) row.hidden = true;
      $('vcClaimCode').value = ''; $('vcConfirmCode').value = '';
      vcOpen('mine'); vcReloadCombo();
    }).catch(function () { vcSetBusy(false); vcErr(tt('vc_err_generic')); });
  }

  function vcInitPanelMine() {
    vcRenderMine();
    var row = $('vcConfirmRow'); if (row) row.hidden = true;
    /* Chi arriva qui senza voci proprie ci arriva per il codice-voce: la
       sezione si apre da sola invece di restare una riga da scoprire. */
    var box = $('vcClaimBox'); if (box) box.open = !S.mine.length;
    $('vcClaimBtn').onclick = vcClaim;
    $('vcConfirmBtn').onclick = vcConfirm;
    $('vcMineClose').onclick = function () { if (S.busy) return; vcClose(); };
    $('vcNewVoice').onclick = function () { if (S.busy) return; vcShow(1); };
  }

  function vcInit() {
    var btn = $('vcOpenBtn'); if (btn) btn.onclick = function () { vcOpen(); };
    var rb = $('vcResumeBtn'); if (rb) rb.onclick = function () { vcOpen(); };
    var close = $('vcClose'); if (close) close.onclick = vcClose;
    /* Niente chiusura sul click fuori: il wizard e' modale sul serio, perche'
       una registrazione o un pagamento in corso non devono sparire per un
       click di troppo sullo sfondo. Si esce solo dalla X o dai bottoni. */
    S.panelHooks = S.panelHooks || {};
    S.panelHooks.vcP1 = vcInitPanel1;
    S.panelHooks.vcPSetup = vcInitPanelSetup;
    S.panelHooks.vcP2 = vcInitPanel2;
    S.panelHooks.vcP3 = vcInitPanel3;
    S.panelHooks.vcP4 = vcInitPanel4;
    S.panelHooks.vcPMine = vcInitPanelMine;
    /* Il deep link ?vc=<id> va letto e ripulito dall'URL SUBITO, prima della
       fetch di config: cosi' l'id resta su S.resumeId anche se la fetch
       fallisce (rete instabile al primo carico), invece di andare perso
       insieme al ramo .then() di successo che in quel caso non arriva mai
       ad eseguire. */
    var q = new URLSearchParams(location.search);
    var vc = q.get('vc');
    if (vc) {
      q.delete('vc');
      var qs = q.toString();
      history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
      S.resumeId = vc;
    }
    vcFetch('/api/voice_clone/config').then(function (r) {
      S.cfg = r.ok ? r.data : null;
      return vcRefreshMine();
    }).then(function () {
      vcSyncButton();
      /* La ripresa da ?vc=<id> richiede che app.js abbia gia' popolato la
         pagina (combo voci, bookLangState): rimandata al prossimo giro di
         event loop. Se l'id non compare piu' in `mine` (campione scaduto o
         eliminato nel frattempo) si apre comunque il pannello «Le tue voci»
         con un messaggio dedicato invece di restare sul pannello 1 muto. */
      if (S.resumeId) {
        setTimeout(function () {
          var id = S.resumeId;
          var found = false;
          for (var i = 0; i < S.mine.length; i++) if (S.mine[i].id === id) { found = true; break; }
          if (found) { vcResume(id); }
          else { vcShow('mine'); vcErr(tt('vc_err_voice_gone')); }
        }, 0);
      }
    }).catch(function () { S.cfg = null; vcSyncButton(); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', vcInit);
  else vcInit();
})();
