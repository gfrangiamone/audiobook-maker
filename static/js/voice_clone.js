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

  function vcInit() {
    var btn = $('vcOpenBtn'); if (btn) btn.onclick = function () { vcOpen(); };
    var rb = $('vcResumeBtn'); if (rb) rb.onclick = function () { vcOpen(); };
    var close = $('vcClose'); if (close) close.onclick = vcClose;
    var modal = $('vcModal');
    if (modal) modal.addEventListener('click', function (ev) { if (ev.target === modal) vcClose(); });
    S.panelHooks = S.panelHooks || {};
    S.panelHooks.vcP1 = vcInitPanel1;
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
