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
    var fd = new FormData();
    fd.append('file', blob, filename);
    fd.append('lang', $('vcLang').value);
    fd.append('locale', $('vcLocale').value);
    fd.append('gender', $('vcGender').value);
    var wait = $('vcUploading'); if (wait) wait.hidden = false;
    var blk = $('vcSampleBlock'); if (blk) blk.hidden = true;
    vcErr('');
    vcFetch('/api/voice_clone/sample', {method: 'POST', body: fd}).then(function (r) {
      if (wait) wait.hidden = true;
      if (!r.ok) { vcErr(vcApiErrMsg(r.data, 'vc_err_generic')); return; }
      S.cur = {clone_id: r.data.clone_id, view: r.data, lang: $('vcLang').value, locale: $('vcLocale').value, gender: $('vcGender').value, voice_code: null};
      var a = $('vcSampleAudio');
      if (a) { a.src = '/api/voice_clone/' + encodeURIComponent(r.data.clone_id) + '/sample.wav?ts=' + Date.now(); }
      if (blk) blk.hidden = false;
    }).catch(function () { if (wait) wait.hidden = true; vcErr(tt('vc_err_generic')); });
  }

  function vcInitPanel2() {
    vcStopMedia();
    var blk = $('vcSampleBlock'); if (blk) blk.hidden = true;
    var wait = $('vcUploading'); if (wait) wait.hidden = true;
    var timer = $('vcTimer'); if (timer) timer.textContent = '0.0 s';
    vcFillLangs();
    vcLoadPrompt();
    $('vcRecBtn').onclick = function () { if (S.media) vcStopMedia(); else vcStartRecording(); };
    $('vcFile').onchange = function () {
      var f = this.files && this.files[0]; if (!f) return;
      var chk = vcUploadCheck(f.name, f.size, (S.cfg && S.cfg.max_upload_mb) || 20);
      if (!chk.ok) { vcErr(tt(chk.reason === 'too_large' ? 'vc_err_too_large' : 'vc_gate_format', {mb: (S.cfg && S.cfg.max_upload_mb) || 20})); this.value = ''; return; }
      vcUploadSample(f, f.name);
      this.value = '';
    };
    $('vcSampleRedo').onclick = function () { if (blk) blk.hidden = true; var a = $('vcSampleAudio'); if (a) { a.pause(); a.removeAttribute('src'); } };
    $('vcSampleNext').onclick = function () { if (S.cur && S.cur.clone_id) vcShow(3); };
    $('vcP2Back').onclick = function () { vcStopMedia(); vcShow(1); };
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
