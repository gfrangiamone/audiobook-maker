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

  function vcGateKey(reason) {
    return GATE_REASONS.indexOf(reason) >= 0 ? 'vc_gate_' + reason : 'vc_gate_generic';
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

  function vcRegenAllowed(view) {
    return !!(view && Number(view.regen_left) > 0);
  }

  var VcCore = {
    vcPanelFor: vcPanelFor, vcGateKey: vcGateKey, vcPending: vcPending,
    vcHasReadyFor: vcHasReadyFor, vcButtonKey: vcButtonKey, vcVisible: vcVisible,
    vcUploadCheck: vcUploadCheck, vcRecordExt: vcRecordExt, vcRegenAllowed: vcRegenAllowed,
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

  function vcErr(msg) {
    var e = $('vcErr');
    if (!e) return;
    if (!msg) { e.hidden = true; e.textContent = ''; return; }
    e.textContent = msg; e.hidden = false;
  }

  /* Messaggio per una risposta d'errore dell'API: chiave i18n per codice,
     altrimenti il testo generico. Mai il testo grezzo del server. */
  function vcApiErrMsg(d, fallbackKey) {
    var code = d && d.error_code;
    if (code === 'rate_limited') return tt('vc_err_rate_limited', {n: (d && d.retry_after) || 60});
    if (code === 'sample_rejected') return tt(vcGateKey(d.reason));
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

  /* Il bottone compare solo con il modello VoxCPM scelto sulla scheda PREMIUM,
     feature attiva e lingua del libro offerta; l'etichetta segue lo stato. */
  function vcSyncButton() {
    var row = $('vcBtnRow'); var btn = $('vcOpenBtn'); var banner = $('vcResumeBanner');
    if (!row || !btn) return;
    var show = vcVoxSelected() && vcVisible(S.cfg, true, vcLang());
    row.hidden = !show;
    if (!show) { if (banner) banner.hidden = true; return; }
    btn.textContent = tt(vcButtonKey(S.mine));
    btn.title = tt('vc_btn_tip');
    if (banner) banner.hidden = !vcPending(S.mine);
  }
  window.vcSyncButton = vcSyncButton;

  function vcShow(n) {
    ['vcP1', 'vcP2', 'vcP3', 'vcP4', 'vcPMine'].forEach(function (id) { var e = $(id); if (e) e.hidden = true; });
    var id = n === 'mine' ? 'vcPMine' : 'vcP' + n;
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
    if (typeof S.stopMedia === 'function') S.stopMedia();
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
    var c = $('vcConsent'); var next = $('vcP1Next');
    if (!c || !next) return;
    c.checked = false; next.disabled = true;
    c.onchange = function () { next.disabled = !c.checked; };
    next.onclick = function () { if (c.checked) vcShow(2); };
    var cancel = $('vcP1Cancel'); if (cancel) cancel.onclick = vcClose;
    var price = $('vcP1Price');
    if (price && S.cfg) price.textContent = S.cfg.free ? tt('vc_price_free') : tt('vc_price', {p: Number(S.cfg.price_eur).toFixed(2)});
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
    ls.onchange = function () { vcFillLocales(); vcLoadPrompt(); };
    loc.onchange = vcLoadPrompt;
    var g = $('vcGender'); if (g) g.onchange = vcLoadPrompt;
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

  function vcSetRecording(on) {
    var b = $('vcRecBtn'); var dot = $('vcRecDot');
    if (b) b.textContent = tt(on ? 'vc_rec_stop' : 'vc_rec_start');
    if (dot) dot.hidden = !on;
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
    ['vcApprove', 'vcRegen', 'vcRegenSel', 'vcReject', 'vcRejectYes', 'vcRejectNo', 'vcReject2', 'vcRetry'].forEach(function (id) {
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

  /* Registrazione: niente cancellazione dell'eco, niente soppressione del
     rumore, niente guadagno automatico (spec §3.3): il modello vuole la voce
     com'e'. Livello con AnalyserNode; stop automatico a 25 s. */
  function vcStartRecording() {
    if (!navigator.mediaDevices || !window.MediaRecorder) { vcErr(tt('vc_err_no_mic')); return; }
    vcErr('');
    navigator.mediaDevices.getUserMedia({audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false}}).then(function (stream) {
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
        var blob = new Blob(chunks, {type: rec.mimeType || mime || 'audio/webm'});
        var ext = vcRecordExt(rec.mimeType || mime);
        vcUploadSample(blob, 'sample.' + ext);
      };
      S.media = {rec: rec, stream: stream, ctx: ctx, timer: tick};
      vcSetRecording(true);
      rec.start();
    }).catch(function () { vcErr(tt('vc_err_no_mic')); });
  }

  function vcUploadSample(blob, filename) {
    if (S.busy) return;
    vcSetBusy(true);
    var fd = new FormData();
    fd.append('file', blob, filename);
    fd.append('lang', _val('vcLang'));
    fd.append('locale', _val('vcLocale'));
    fd.append('gender', _val('vcGender'));
    var wait = $('vcUploading'); if (wait) wait.hidden = false;
    var blk = $('vcSampleBlock'); if (blk) blk.hidden = true;
    vcErr('');
    vcFetch('/api/voice_clone/sample', {method: 'POST', body: fd}).then(function (r) {
      if (wait) wait.hidden = true;
      vcSetBusy(false);
      if (!r.ok) { vcErr(vcApiErrMsg(r.data, 'vc_err_generic')); return; }
      S.cur = {clone_id: r.data.clone_id, view: r.data, lang: _val('vcLang'), locale: _val('vcLocale'), gender: _val('vcGender'), voice_code: null};
      var a = $('vcSampleAudio');
      if (a) { a.src = '/api/voice_clone/' + encodeURIComponent(r.data.clone_id) + '/sample.wav?ts=' + Date.now(); }
      if (blk) blk.hidden = false;
    }).catch(function () { if (wait) wait.hidden = true; vcSetBusy(false); vcErr(tt('vc_err_generic')); });
  }

  function vcInitPanel2() {
    vcStopMedia();
    vcSetBusy(false);
    var blk = $('vcSampleBlock'); if (blk) blk.hidden = true;
    var wait = $('vcUploading'); if (wait) wait.hidden = true;
    var timer = $('vcTimer'); if (timer) timer.textContent = '0.0 s';
    vcFillLangs();
    vcLoadPrompt();
    $('vcRecBtn').onclick = function () { if (S.busy) return; if (S.media) vcStopMedia(); else vcStartRecording(); };
    $('vcFile').onchange = function () {
      if (S.busy) { this.value = ''; return; }
      var f = this.files && this.files[0]; if (!f) return;
      var chk = vcUploadCheck(f.name, f.size, (S.cfg && S.cfg.max_upload_mb) || 20);
      if (!chk.ok) { vcErr(tt(chk.reason === 'too_large' ? 'vc_err_too_large' : 'vc_gate_format', {mb: (S.cfg && S.cfg.max_upload_mb) || 20})); this.value = ''; return; }
      vcUploadSample(f, f.name);
      this.value = '';
    };
    $('vcSampleRedo').onclick = function () { if (blk) blk.hidden = true; var a = $('vcSampleAudio'); if (a) { a.pause(); a.removeAttribute('src'); } };
    $('vcSampleNext').onclick = function () { if (S.cur && S.cur.clone_id) vcShow(3); };
    $('vcP2Back').onclick = function () { if (S.busy) return; vcStopMedia(); vcShow(1); };
  }

  /* ---------- pannello 3: email, brano extra, pagamento ---------- */

  function vcLoadExtraTexts() {
    var sel = $('vcExtraSel'); if (!sel || !S.cur) return;
    var loc = S.cur.locale || (S.cur.view && S.cur.view.locale) || '';
    var key = (S.cur.clone_id || '') + '|' + loc;
    /* Un ritorno su questo pannello (es. dopo un errore di commit) rifa' lo
       show del pannello 3 e quindi il suo hook: se l'elenco e' gia' quello
       giusto non lo ricarichiamo, altrimenti la scelta dell'utente sparisce. */
    if (S.extraLoadedFor === key && sel.options.length) return;
    sel.innerHTML = '';
    vcFetch('/api/voice_clone/demo_texts?locale=' + encodeURIComponent(loc)).then(function (r) {
      if (!r.ok) { vcErr(vcApiErrMsg(r.data)); return; }
      (r.data.extra || []).forEach(function (x) {
        var o = document.createElement('option'); o.value = x.id;
        o.textContent = (x.text || '').slice(0, 90) + ((x.text || '').length > 90 ? '…' : '');
        sel.appendChild(o);
      });
      S.extraLoadedFor = key;
    });
  }

  function vcEmailsOk() {
    var a = ($('vcEmail').value || '').trim(); var b = ($('vcEmail2').value || '').trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(a)) { vcErr(tt('vc_err_email_bad')); return false; }
    if (a.toLowerCase() !== b.toLowerCase()) { vcErr(tt('vc_err_email_mismatch')); return false; }
    return true;
  }

  function vcCommit(paymentToken) {
    var body = {clone_id: S.cur.clone_id, email: $('vcEmail').value.trim(), email2: $('vcEmail2').value.trim(),
                extra_id: $('vcExtraSel').value, payment_token: paymentToken || ''};
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
    vcLoadExtraTexts();
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
      /* Regenerate/retry o cambio di stato: le due prove smettono di
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
      var left = Number(view.regen_left) || 0;
      var rl = $('vcRegenLeft'); if (rl) rl.textContent = tt('vc_regen_left', {n: left});
      var rb = $('vcRegen'); if (rb) rb.disabled = S.busy || !vcRegenAllowed(view);
      var rs = $('vcRegenSel'); if (rs) rs.disabled = S.busy || !vcRegenAllowed(view);
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
    var sel = $('vcRegenSel');
    if (sel) {
      var cloneId = S.cur.clone_id;
      var loc = (S.cur.view && S.cur.view.locale) || S.cur.locale || '';
      var regenKey = cloneId + '|' + loc;
      /* Come vcLoadExtraTexts sul pannello 3: rientrare piu' volte nel
         pannello 4 (regenerate, retry, evento SSE) non deve ripetere la
         fetch ne' scartare la selezione dell'utente se l'elenco e' gia'
         quello giusto. */
      if (S.regenLoadedFor === regenKey && sel.options.length) return;
      sel.innerHTML = '';
      vcFetch('/api/voice_clone/demo_texts?locale=' + encodeURIComponent(loc)).then(function (r) {
        if (!r.ok) return;
        if (!S.cur || S.cur.clone_id !== cloneId) return;
        (r.data.extra || []).forEach(function (x) {
          var o = document.createElement('option'); o.value = x.id;
          o.textContent = (x.text || '').slice(0, 60) + '…';
          sel.appendChild(o);
        });
        if (S.cur.view && S.cur.view.extra_id) sel.value = S.cur.view.extra_id;
        S.regenLoadedFor = regenKey;
      });
    }
    $('vcApprove').onclick = function () { vcAction('approve').then(function (v) { if (v) vcAfterApprove(v); }); };
    $('vcRegen').onclick = function () { vcAction('regenerate', {extra_id: sel ? sel.value : ''}).then(function (v) { if (v) vcWatch(); }); };
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

  function vcInit() {
    var btn = $('vcOpenBtn'); if (btn) btn.onclick = function () { vcOpen(); };
    var rb = $('vcResumeBtn'); if (rb) rb.onclick = function () { vcOpen(); };
    var close = $('vcClose'); if (close) close.onclick = vcClose;
    var modal = $('vcModal');
    if (modal) modal.addEventListener('click', function (ev) { if (ev.target === modal) vcClose(); });
    S.panelHooks = S.panelHooks || {};
    S.panelHooks.vcP1 = vcInitPanel1;
    S.panelHooks.vcP2 = vcInitPanel2;
    S.panelHooks.vcP3 = vcInitPanel3;
    S.panelHooks.vcP4 = vcInitPanel4;
    vcFetch('/api/voice_clone/config').then(function (r) {
      S.cfg = r.ok ? r.data : null;
      return vcRefreshMine();
    }).then(function () {
      vcSyncButton();
      var q = new URLSearchParams(location.search);
      var vc = q.get('vc');
      if (vc) {
        q.delete('vc');
        var qs = q.toString();
        history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
        S.resumeId = vc;
      }
    }).catch(function () { S.cfg = null; });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', vcInit);
  else vcInit();
})();
