// ═══════════════════ LANGUAGE DROPDOWN ═══════════════════
const LANG_FLAGS={'it':'🇮🇹','en':'🇬🇧','fr':'🇫🇷','es':'🇪🇸','de':'🇩🇪','zh':'🇨🇳','hi':'🇮🇳'};
function toggleLangDropdown(){
  const el=document.getElementById('langDropdown');
  const trigger=document.getElementById('langCurrent');
  if(!el)return;
  const opening=!el.classList.contains('open');
  el.classList.toggle('open');
  if(trigger)trigger.setAttribute('aria-expanded',opening?'true':'false');
  if(opening){
    // Focus first option on open
    const opts=el.querySelectorAll('.lang-option');
    if(opts.length){opts[0].tabIndex=0;opts[0].focus();}
  }
}
function closeLangDropdown(){
  const el=document.getElementById('langDropdown');
  const trigger=document.getElementById('langCurrent');
  const wasOpen=el&&el.classList.contains('open');
  if(el)el.classList.remove('open');
  if(trigger)trigger.setAttribute('aria-expanded','false');
  document.querySelectorAll('.lang-option').forEach(o=>o.tabIndex=-1);
  if(wasOpen&&trigger)trigger.focus();
}
function handleLangKey(e){
  const dropdown=document.getElementById('langDropdown');
  const isOpen=dropdown&&dropdown.classList.contains('open');
  if(e.key==='Enter'||e.key===' '||(e.key==='ArrowDown'&&!isOpen)){
    e.preventDefault();
    if(isOpen&&(e.key==='Enter'||e.key===' ')){
      closeLangDropdown();
    }else{
      toggleLangDropdown();
    }
  }else if(e.key==='Escape'&&isOpen){
    e.preventDefault();
    closeLangDropdown();
  }
}
function handleLangOptionKey(e,code){
  const dropdown=document.getElementById('langDropdown');
  const opts=dropdown?dropdown.querySelectorAll('.lang-option'):[];
  let idx=Array.from(opts).indexOf(document.activeElement);
  if(e.key==='Enter'||e.key===' '){
    e.preventDefault();
    selectLang(code);
  }else if(e.key==='ArrowDown'){
    e.preventDefault();
    idx=Math.min(idx+1,opts.length-1);
    opts.forEach(o=>o.tabIndex=-1);
    opts[idx].tabIndex=0;opts[idx].focus();
  }else if(e.key==='ArrowUp'){
    e.preventDefault();
    idx=Math.max(idx-1,0);
    opts.forEach(o=>o.tabIndex=-1);
    opts[idx].tabIndex=0;opts[idx].focus();
  }else if(e.key==='Escape'){
    e.preventDefault();
    closeLangDropdown();
  }
}
function selectLang(code){
  const codeEl=document.getElementById('langCode');
  const flagEl=document.getElementById('langFlag');
  if(codeEl)codeEl.textContent=code.toUpperCase();
  if(flagEl)flagEl.textContent=LANG_FLAGS[code]||'';
  document.querySelectorAll('.lang-option').forEach(opt=>{
    const sel=opt.dataset.lang===code;
    opt.classList.toggle('active',sel);
    opt.setAttribute('aria-selected',sel?'true':'false');
  });
  closeLangDropdown();
  setLang(code);
}

// Sync dropdown with current language on init
function syncLangDropdown(){
  const cur=cl||'en';
  const codeEl=document.getElementById('langCode');
  const flagEl=document.getElementById('langFlag');
  if(codeEl)codeEl.textContent=cur.toUpperCase();
  if(flagEl)flagEl.textContent=LANG_FLAGS[cur]||'';
  document.querySelectorAll('.lang-option').forEach(opt=>{
    const sel=opt.dataset.lang===cur;
    opt.classList.toggle('active',sel);
    opt.setAttribute('aria-selected',sel?'true':'false');
  });
}

// Close dropdown when clicking outside
document.addEventListener('click',function(e){if(!e.target.closest('.lang-switcher'))closeLangDropdown()});

// ── Focus trap for modals (auto via MutationObserver) ──
let _lastFocused=null;
const _modalTraps=new Map();
function _trapFocusIn(el){
  const focusable=el.querySelectorAll(
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  );
  if(!focusable.length)return;
  const handler=function(e){
    if(e.key!=='Tab')return;
    const first=focusable[0], last=focusable[focusable.length-1];
    if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
    else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
  };
  el.addEventListener('keydown',handler);
  _modalTraps.set(el,handler);
}
function _releaseFocusTrap(el){
  const handler=_modalTraps.get(el);
  if(handler){el.removeEventListener('keydown',handler);_modalTraps.delete(el);}
}
function restoreFocus(){
  if(_lastFocused&&typeof _lastFocused.focus==='function'){
    try{_lastFocused.focus();}catch(e){}
  }
  _lastFocused=null;
}
// Auto-detect modal open/close via MutationObserver
(function(){
  const observer=new MutationObserver(function(mutations){
    for(const m of mutations){
      if(m.type==='attributes'&&m.attributeName==='class'){
        const el=m.target;
        if(!el.classList.contains('modal-overlay'))continue;
        if(el.classList.contains('open')){
          _lastFocused=document.activeElement;
          // Focus first focusable element after a tick (only if user hasn't already focused something inside)
          setTimeout(()=>{
            if(el.contains(document.activeElement))return;
            const focusable=el.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])');
            if(focusable.length){focusable[0].focus();}
            _trapFocusIn(el);
          },80);
        }else{
          _releaseFocusTrap(el);
          restoreFocus();
        }
      }
    }
  });
  document.querySelectorAll('.modal-overlay').forEach(function(m){
    observer.observe(m,{attributes:true,attributeFilter:['class']});
  });
})();

// Keyboard shortcuts handler (inside DOMContentLoaded for safety)
function setupKeyboardShortcuts(){
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'){
      closeDonateModalX();
      closeAbmGuide();
      previewStop();
      const aboutModal=document.getElementById('aboutModal');
      if(aboutModal)aboutModal.classList.remove('open');
      closeLangDropdown();
      restoreFocus();
    }
  });
}

let cl='en';
function t(k, replacements){
  let s=(L[cl]||L.en)[k]||(L.en)[k]||k;
  if(replacements){
    for(let key in replacements){
      s=s.replace(new RegExp('{'+key+'}','g'), replacements[key]);
    }
  }
  return s;
}
function applyI18n(){
  document.querySelectorAll('[data-t]').forEach(e=>{
    const k=e.getAttribute('data-t'), v=t(k);
    if(e.tagName==='OPTION') {
      e.textContent = v;
    } else {
      const tt = e.querySelector('.tooltip-trigger');
      if (tt) {
        // Cerca il nodo di testo che contiene il titolo (es. "Carica il file")
        // Di solito è il primo figlio se la struttura è <div>Title<span tooltip>...</div>
        let tn = Array.from(e.childNodes).find(n => n.nodeType === 3 && n.textContent.trim().length > 1);
        if (tn) tn.textContent = v;
        else e.insertBefore(document.createTextNode(v), tt);
      } else {
        // Caso normale: se non ha figli HTML, usa textContent (veloce)
        if (e.children.length === 0) {
          // FAQ answers may contain HTML links (e.g. free books list)
          if (e.classList.contains('faq-answer') && /<[a-z][\s\S]*>/i.test(v)) {
            e.innerHTML = v;
          } else {
            e.textContent = v;
          }
        } else {
          // Se ha figli (es. icone), cerca il nodo di testo da aggiornare
          let tn = Array.from(e.childNodes).find(n => n.nodeType === 3 && n.textContent.trim().length > 0);
          if (tn) tn.textContent = v;
          // Se non c'è un nodo di testo ma ci sono figli, aggiungiamo il testo alla fine (fallback)
          else e.appendChild(document.createTextNode(v));
        }
      }
    }
  });
  document.querySelectorAll('[data-t-title]').forEach(e=>{
    const k=e.getAttribute('data-t-title'), v=t(k);
    if(v) e.title=v;
  });
  document.querySelectorAll('.lsw button').forEach(b=>b.classList.toggle('on',b.dataset.l===cl));
  document.documentElement.lang=cl;
  const btnExp=document.getElementById('btnExport');
  if(btnExp)btnExp.title=t('btn_export_abm_tip');
  const btnAbmInfo=document.getElementById('btnAbmInfo');
  if(btnAbmInfo)btnAbmInfo.title=t('btn_export_abm_tip');
  // Le opzioni del dropdown accento sono costruite dinamicamente (non data-t):
  // ri-popolale al cambio lingua UI cosi' le etichette si traducono.
  if(typeof _updateAccentDropdown==='function')_updateAccentDropdown();
}
function setLang(l){cl=l;applyI18n();buildAbout();applySEO(l);try{localStorage.setItem('abm_l',l)}catch(e){}
  // Sync URL with selected language (SEO: URL ↔ content coherence)
  var p='/'+l+'/';if(location.pathname!==p)history.replaceState(null,'',p);
  // Visible SEO block removed from template — language sync handled by UI only
  // Notify widgets that render i18n-aware content (feedback, news) so
  // they can re-render with the freshly selected UI language.
  try{window.dispatchEvent(new CustomEvent('abm:langchange',{detail:{lang:l}}));}catch(e){}
}
function detectLang(){
  // INIT_LANG è iniettato server-side: rispetta la lingua della URL (/it/, /en/, ecc.)
  if(typeof INIT_LANG!=='undefined'&&L[INIT_LANG])return INIT_LANG;
  try{const s=localStorage.getItem('abm_l');if(s&&L[s])return s}catch(e){}
  const n=(navigator.language||navigator.userLanguage||'en').toLowerCase().split('-')[0];
  return L[n]?n:'en';
}

// ═══════════════════ STATE ═══════════════════
let voices={},bookData=null,jobId=null,singleFile=true,generating=false,jobDone=false,hbInterval=null,_analyzedHbInterval=null,isTxtFile=false,emailRegistered=false;
let previewListened=false,_langWarnResolve=null;
let _googleTtsBudget=null; // {available, chars_remaining, chars_limit} or null
let aiOptEnabled=false,llmAvailable=false,optimizedChapters=[];
let wizMode='audio'; // 'audio' | 'translate'
let trPaymentToken=null,trEstimate=null,trEmailRegistered=false,trAutoOutName='';
let lastVoucherEmail='';
try{lastVoucherEmail=localStorage.getItem('abm_v_email')||''}catch(e){}

// ═══════════════════ THEME ═══════════════════
function detectTheme(){
  try{const s=localStorage.getItem('abm_th');if(s)return s}catch(e){}
  return window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';
}
function applyTheme(th){
  if(th==='dark'){document.documentElement.setAttribute('data-theme','dark');document.getElementById('themeBtn').textContent='☀️'}
  else{document.documentElement.removeAttribute('data-theme');document.getElementById('themeBtn').textContent='🌙'}
  try{localStorage.setItem('abm_th',th)}catch(e){}
}
function toggleTheme(){
  const cur=document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';
  applyTheme(cur);
}

// ═══════════════════ INIT ═══════════════════
document.addEventListener('DOMContentLoaded',()=>{
  applyTheme(detectTheme());
  cl=detectLang();applyI18n();buildAbout();applySEO(cl);
  syncLangDropdown();
  setupKeyboardShortcuts();
  // Fix Chromium bug: nested <details> toggle scrolls page to top
  var _seoX=0,_seoY=0;
  var seoBlock=document.getElementById('seoContent');
  if(seoBlock){
    seoBlock.addEventListener('mousedown',function(){_seoX=window.scrollX;_seoY=window.scrollY});
    seoBlock.addEventListener('toggle',function(e){
      if(e.target.tagName==='DETAILS'){
        // Double rAF + setTimeout: Chrome nested-details bug resets scroll asynchronously
        var sx=_seoX,sy=_seoY;
        requestAnimationFrame(function(){
          requestAnimationFrame(function(){window.scrollTo(sx,sy)});
        });
        setTimeout(function(){window.scrollTo(sx,sy)},100);
      }
    }, true);
  }
  

  // Global scroll guard: Chrome loses scroll position on focus when page CSS
  // creates complex overflow/position context. Save on mousedown, restore if
  // focused element was already fully visible (no legitimate scroll needed).
  var _gsx=0,_gsy=0,_skipUntil=0;
  function _saveScroll(){_gsx=window.scrollX;_gsy=window.scrollY}
  document.addEventListener("mousedown",_saveScroll);
  document.addEventListener("keydown",function(e){if(e.key==="Tab")_saveScroll()});
  document.addEventListener("focusin",function(e){
    if(Date.now()<_skipUntil)return;
    // Skip for elements inside open modals (position:fixed, unaffected by page scroll)
    if(e.target.closest('.modal-overlay.open'))return;
    var r=e.target.getBoundingClientRect();
    if(r.top>=0&&r.left>=0&&r.bottom<=window.innerHeight&&r.right<=window.innerWidth){
      var sx=_gsx,sy=_gsy;
      requestAnimationFrame(function(){
        requestAnimationFrame(function(){
          if(window.scrollX!==sx||window.scrollY!==sy)window.scrollTo(sx,sy);
        });
      });
    }
  });
  // Allow intentional scrollIntoView calls to bypass the guard for 600ms.
  window._bypassScrollGuard=function(fn){
    _skipUntil=Date.now()+600; fn();
  };
  // Safe DOM element setup with null checks
  const lsw=document.getElementById('lsw');
  if(lsw)lsw.onclick=e=>{if(e.target.dataset.l)setLang(e.target.dataset.l)};
  const themeBtn=document.getElementById('themeBtn');
  if(themeBtn)themeBtn.onclick=toggleTheme;
  const aboutBtn=document.getElementById('aboutBtn');
  if(aboutBtn)aboutBtn.onclick=e=>{e.preventDefault();openAbout()};
  const aboutClose=document.getElementById('aboutClose');
  if(aboutClose)aboutClose.onclick=()=>{const m=document.getElementById('aboutModal');if(m)m.classList.remove('open')};
  const aboutModal=document.getElementById('aboutModal');
  if(aboutModal)aboutModal.onclick=e=>{if(e.target===e.currentTarget)e.target.classList.remove('open')};
  // Monitor modal handlers
  const monClose=document.getElementById('monClose');
  if(monClose)monClose.onclick=closeMonitor;
  const monModal=document.getElementById('monModal');
  if(monModal)monModal.onclick=e=>{if(e.target===e.currentTarget)closeMonitor()};
  // ABM guide modal handlers
  const abmGuideModal=document.getElementById('abmGuideModal');
  if(abmGuideModal)abmGuideModal.onclick=e=>{if(e.target===e.currentTarget)closeAbmGuide()};
  var dc=document.getElementById('donateCard');if(dc)dc.style.display='';
  setupUpload();loadVoices();
  // Wizard generation button
  const btnGenerate=document.getElementById('btnGenerate');
  if(btnGenerate)btnGenerate.onclick=onGenerateClick;
  // Payment modal (Gemini Premium) listeners
  document.getElementById('btnPayCancel')?.addEventListener('click', closePaymentModal);
  document.getElementById('btnPayCancel2')?.addEventListener('click', closePaymentModal);
  document.getElementById('btnPayConfirm')?.addEventListener('click', onPayConfirm);
  document.querySelectorAll('.pay-tab').forEach(el => {
    el.addEventListener('click', () => switchPayTab(el.dataset.paytab));
  });
  document.getElementById('geminiPayVoucherCode')?.addEventListener('blur', validateVoucherForPayment);
  document.getElementById('geminiPayVoucherEmail')?.addEventListener('blur', validateVoucherForPayment);
  // Download buttons (panel 5)
  const btnD=document.getElementById('btnD');
  if(btnD)btnD.onclick=()=>downloadFile('zip');
  const btnM=document.getElementById('btnM');
  if(btnM)btnM.onclick=()=>downloadFile('m4b');
  const btnA=document.getElementById('btnA');
  if(btnA)btnA.onclick=()=>downloadFile('abm');
  const btnP=document.getElementById('btnP');
  if(btnP)btnP.onclick=downloadPodcast;
  const btnN=document.getElementById('btnN');
  if(btnN)btnN.onclick=confirmReset;
  // Cancel buttons (panel 4)
  const btnC=document.getElementById('btnC');
  if(btnC)btnC.onclick=cancelJob;
  const btnCancelOpt=document.getElementById('btnCancelOpt');
  if(btnCancelOpt)btnCancelOpt.onclick=cancelOptimization;
  window.addEventListener('beforeunload',onBeforeUnload);
  const vOutSel=document.getElementById('vOut');
  if(vOutSel)vOutSel.addEventListener('change',onOutputChange);
  // Speed slider: sync slider → hidden #vr select (mockup-inspired)
  const speedSlider=document.getElementById('speedSlider');
  const speedLabel=document.getElementById('speedLabel');
  const vrSel=document.getElementById('vr');
  const SPEED_LABEL_KEYS=['sp_vs','sp_s','sp_ss','sp_n','sp_sf','sp_f','sp_vf'];
  const SPEED_VALUES=['-30%','-20%','-10%','+0%','+10%','+20%','+30%'];
  function _setSpeed(idx){
    vrSel.value=SPEED_VALUES[idx];
    speedLabel.textContent=t(SPEED_LABEL_KEYS[idx]);
  }
  if(speedSlider&&speedLabel&&vrSel){
    speedSlider.addEventListener('input',function(){
      var idx=parseInt(this.value)+3;
      _setSpeed(idx);
      _onPreviewParamsChanged();
      if(typeof requestCombinedEstimate==='function')requestCombinedEstimate();
    });
    // Also sync on change (for keyboard/accessibility)
    speedSlider.addEventListener('change',function(){
      var idx=parseInt(this.value)+3;
      _setSpeed(idx);
    });
  }
  // Initialize output format to M4B by default
  setTimeout(()=>{const s=document.getElementById('vOut');if(s){s.value='m4b';onOutputChange();}},50);
  // Chapter selection handlers
  const selAll=document.getElementById('selAll');if(selAll)selAll.onclick=chSelAll;
  const selNone=document.getElementById('selNone');if(selNone)selNone.onclick=chSelNone;
  const selInv=document.getElementById('selInv');if(selInv)selInv.onclick=chSelInvert;
  const chAll=document.getElementById('chAll');if(chAll)chAll.onchange=chMasterToggle;
  // AI toggle init
  _initAiOptToggle();
  // Tab bar (Standard / Premium) + Premium controls
  document.querySelectorAll('.tab-bar .tab').forEach(btn=>{
    btn.addEventListener('click',()=>switchAudioTab(btn.dataset.tab));
  });
  const vlPrem=document.getElementById('vlPremium');
  if(vlPrem)vlPrem.addEventListener('change',()=>{
    const src=document.getElementById('vl');
    if(src){src.value=vlPrem.value;updVoices();}
    if(typeof updModelsPremium==='function')updModelsPremium();
    updVoicesPremium();
    if(typeof _onPremiumModelChanged==='function')_onPremiumModelChanged();
    // La lingua entra nella stima (cluster rate-log + ratio chars/token).
    if(typeof requestCombinedEstimate==='function')requestCombinedEstimate();
  });
  const vmPrem=document.getElementById('vmPremium');
  if(vmPrem)vmPrem.addEventListener('change',()=>{
    // _onPremiumModelChanged() gestisce il toggle stile/emozioni, ripopola
    // voci/accenti/emozioni e propaga il cambio al sig di preview.
    if(typeof _onPremiumModelChanged==='function')_onPremiumModelChanged();
    if(typeof requestCombinedEstimate==='function')requestCombinedEstimate();
  });
  const gStyle=document.getElementById('geminiStyle');
  if(gStyle){
    gStyle.addEventListener('input',(e)=>{
      const counter=document.getElementById('styleCounter');
      if(counter)counter.textContent=e.target.value.length;
    });
    // Lo stile entra nella firma solo per voci Gemini. Trigger su 'change'
    // (perdita focus o invio) per non riprocessare a ogni tasto premuto.
    gStyle.addEventListener('change',()=>{_onPreviewParamsChanged();});
  }
  // Cost estimate triggers (no re-estimate on voice change)
  document.getElementById('aiToggle')?.addEventListener('change',requestCombinedEstimate);
  // Toggle lettura parentesi: cambia il conteggio caratteri -> ristima costo.
  document.getElementById('readRoundParens')?.addEventListener('change',requestCombinedEstimate);
  document.getElementById('readSquareBrackets')?.addEventListener('change',requestCombinedEstimate);
  // Initialize wizard
  updateWizardSteps(1);
});

let outputFormat='m4b';
let podcastBaseUrl='';
// wizardState centralizza lo stato del wizard. audioTab: 'standard' | 'premium'.
const wizardState = { audioTab: 'standard' };
function onOutputChange(){
  const sel=document.getElementById('vOut');
  outputFormat=sel?sel.value:'m4b';
  singleFile=(outputFormat==='m4b'||outputFormat==='mp3');
  const podcastUrlGroup=document.getElementById('podcastUrlGroup');
  if(podcastUrlGroup)podcastUrlGroup.style.display=(outputFormat==='zip_rss')?'':'none';
  const podcastUrlInput=document.getElementById('podcastUrlInput');
  if(podcastUrlInput){
    podcastBaseUrl=podcastUrlInput.value.trim();
    if(!podcastUrlInput._abmBound){
      podcastUrlInput._abmBound=true;
      podcastUrlInput.addEventListener('input',()=>{podcastBaseUrl=podcastUrlInput.value.trim();});
    }
  }
  _updateSummary&&_updateSummary();
  updateSelection();
}
// TXT input: only single-file formats make sense (no per-chapter split).
// Show m4b + single mp3, hide zip/podcast. Non-TXT restores all options.
function _applyOutputOptionsForType(isTxt){
  const sel=document.getElementById('vOut');
  if(!sel)return;
  ['zip','zip_rss'].forEach(v=>{
    const opt=sel.querySelector('option[value="'+v+'"]');
    if(opt){opt.hidden=isTxt;opt.disabled=isTxt;opt.style.display=isTxt?'none':'';}
  });
  if(isTxt&&(sel.value==='zip'||sel.value==='zip_rss'))sel.value='m4b';
}
// Backward-compat shim for old toggle button refs
function toggleOut(el){
  if(!el)return;
  const v=el.dataset?el.dataset.v:null;
  const sel=document.getElementById('vOut');
  if(sel){sel.value=(v==='single')?'m4b':'zip';onOutputChange();}
}

// ═══════════════════ UPLOAD + LOCK ═══════════════════
function setupUpload(){
  const z=document.getElementById('uz'),fi=document.getElementById('fi');
  z.onclick=()=>{if(!generating&&!jobDone)fi.click()};
  ['dragenter','dragover'].forEach(e=>z.addEventListener(e,ev=>{ev.preventDefault();if(!generating&&!jobDone)z.classList.add('dg')}));
  ['dragleave','drop'].forEach(e=>z.addEventListener(e,ev=>{ev.preventDefault();z.classList.remove('dg')}));
  z.addEventListener('drop',ev=>{if(generating||jobDone)return;const f=ev.dataTransfer.files;if(f.length)handleFile(f[0])});
  fi.addEventListener('change',()=>{if(!generating&&!jobDone&&fi.files.length)handleFile(fi.files[0])});
}

// ═══════════════════ WIZARD NAVIGATION ═══════════════════
let _wizStep=1, _wizMaxStep=1;
function goToStep(n){
  if(n<1||n>5)return;
  if(n>_wizMaxStep+1)return; // can always go to next step
  if(n===_wizMaxStep+1)_unlockStep(n); // auto-unlock next step
  // Pause preview audio when switching panels (don't invalidate generated preview)
  if(n!==_wizStep){const a=document.getElementById('previewAudioWiz');if(a)a.pause();}
  const panels=document.querySelectorAll('.panel');
  panels.forEach(p=>p.classList.remove('active'));
  let panelId='panel'+n;
  if(wizMode==='translate'&&n===3)panelId='panelT3';
  if(wizMode==='translate'&&n===4)panelId='panelT4';
  const target=document.getElementById(panelId);
  if(target)target.classList.add('active');
  _wizStep=n;
  updateWizardSteps(n);
  // Auto-update summary when entering panel 4
  if(n===4&&wizMode==='audio')_updateSummary();
  var dc=document.getElementById('donateCard');
  if(dc)dc.style.display=n===1?'':'none';
  // Scroll to top so header + wizard dots are visible; bypass the global
  // focusin scroll-guard so the scroll restore doesn't fight this move.
  window._bypassScrollGuard(function(){
    window.scrollTo({top:0,behavior:'instant'});
    const hdr=document.querySelector('header');
    if(hdr)hdr.scrollIntoView({behavior:'smooth',block:'start'});
    // Move focus to first focusable element inside new panel
    const focusable=target?target.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled])'):[];
    if(focusable.length)focusable[0].focus();
  });
}
function updateWizardSteps(n){
  const dots=document.querySelectorAll('.wizard-step-dot');
  const connectors=document.querySelectorAll('.wizard-connector');
  dots.forEach((d,i)=>{
    const step=i+1;
    d.classList.remove('active','done','locked');
    if(step===n)d.classList.add('active');
    else if(step<n)d.classList.add('done');
    else if(step>_wizMaxStep)d.classList.add('locked');
  });
  connectors.forEach(c=>{
    const cn=parseInt(c.dataset.connector);
    c.classList.toggle('done',cn<n);
  });
  _applyWizModeLabels();
}
function _applyWizModeLabels(){
  const dots=document.querySelectorAll('.wizard-step-dot');
  if(dots.length<5)return;
  const l3=dots[2].querySelector('.label'),l4=dots[3].querySelector('.label');
  if(l3)l3.textContent=t(wizMode==='translate'?'wiz_step3_tr':'wiz_step3');
  if(l4)l4.textContent=t(wizMode==='translate'?'wiz_step4_tr':'wiz_step4');
}
function _unlockStep(n){if(n>_wizMaxStep)_wizMaxStep=n;updateWizardSteps(_wizStep)}

function lockUI(){
  generating=true;
  document.getElementById('fi').disabled=true;
  const btnExp=document.getElementById('btnExport');if(btnExp)btnExp.disabled=true;
  const card=document.getElementById('mainCard');if(card)card.classList.add('locked');
  previewStop(); _updatePreviewBtn();
  // Hide back buttons during generation
  ['btnBack4','btnUploadAnother','btnGoToAudio','btnGoToGenerate'].forEach(id=>{
    const el=document.getElementById(id);if(el)el.style.display='none';
  });
  // Show cancel area
  const cnA=document.getElementById('cnA');if(cnA)cnA.style.display='';
  _updateGenNoticeWarning();
}
function unlockUI(){
  generating=false;
  document.getElementById('fi').disabled=false;
  const btnExp=document.getElementById('btnExport');if(btnExp)btnExp.disabled=!bookData;
  const card=document.getElementById('mainCard');if(card)card.classList.remove('locked');
  _updatePreviewBtn();
  // Restore back buttons
  const btnBack4=document.getElementById('btnBack4');if(btnBack4)btnBack4.style.display='';
  const btnUploadAnother=document.getElementById('btnUploadAnother');if(btnUploadAnother)btnUploadAnother.style.display='';
  const btnGoToAudio=document.getElementById('btnGoToAudio');if(btnGoToAudio)btnGoToAudio.style.display='';
  const btnGoToGenerate=document.getElementById('btnGoToGenerate');if(btnGoToGenerate)btnGoToGenerate.style.display='';
}

function handleFile(file){
  if(generating||jobDone)return;
  const fn=file.name.toLowerCase();
  if(!fn.endsWith('.epub')&&!fn.endsWith('.pdf')&&!fn.endsWith('.txt')&&!fn.endsWith('.abm')){showErr('aerr',t('err_epub'));return}
  // Pre-check dimensione: evita upload destinati al 413 server-side
  const maxMb=window.ABM_MAX_UPLOAD_MB||50;
  if(file.size>maxMb*1024*1024){showErr('aerr',t('err_file_too_large',{size:(file.size/1048576).toFixed(1),mb:maxMb}));return}
  document.getElementById('uz').classList.add('ok');
  document.getElementById('ufn').textContent='✓ '+file.name;
  document.getElementById('ufn').style.display='block';
  const s1sum=document.getElementById('s1sum');if(s1sum)s1sum.textContent='✓ '+file.name;
  document.getElementById('utx').textContent=t('upload_ok');
  document.getElementById('aerr').innerHTML='';
  // Show upload progress
  showUploadProgress(file);
  analyzeEpub(file);
}
function showUploadProgress(file){
  const progress=document.getElementById('uploadProgress');
  const fill=document.getElementById('uploadProgressFill');
  const status=document.getElementById('uploadStatus');
  const percent=document.getElementById('uploadPercent');
  progress.style.display='block';
  // Simulate progress (actual XHR upload would give real progress)
  let p=0;
  const totalSize=file.size;
  const interval=setInterval(()=>{
    p+=Math.random()*12;
    if(p>=85){p=85;clearInterval(interval)}
    fill.style.width=p+'%';
    percent.textContent=Math.round(p)+'%';
    const uploaded=Math.round((p/100)*totalSize);
    status.textContent=fmtBytes(uploaded)+' / '+fmtBytes(totalSize);
  },150);
  // Store interval to clear when done
  window._uploadProgressInterval=interval;
}
function hideUploadProgress(){
  const progress=document.getElementById('uploadProgress');
  const fill=document.getElementById('uploadProgressFill');
  fill.style.width='100%';
  document.getElementById('uploadPercent').textContent='100%';
  setTimeout(()=>{progress.style.display='none';fill.style.width='0%'},500);
  if(window._uploadProgressInterval){clearInterval(window._uploadProgressInterval);window._uploadProgressInterval=null}
}

async function analyzeEpub(file){
  const lo=document.getElementById('alo');lo.classList.add('vis');
  // Sospensione admin: blocca gia` al caricamento, evitando di uploadare il file
  // (fino a 50MB) per poi essere bloccati. Il backend ricontrolla comunque
  // (guardia autoritativa in /api/analyze).
  try{const sr=await fetch('/api/admin/suspend');if(sr.ok){const sd=await sr.json();if(sd.suspended){showErr('aerr','System under maintenance. Please try again in a few minutes.');lo.classList.remove('vis');return}}}catch(_){}
  const fd=new FormData();fd.append('epub',file);
  try{
    const r=await fetch('/api/analyze',{method:'POST',body:fd});
    let d;
    // Risposta non-JSON (es. pagina HTML 413/5xx di nginx o Werkzeug): messaggio
    // sensato invece di "JSON.parse: unexpected character".
    try{d=await r.json()}catch(_){d={error:'Error: HTTP '+r.status}}
    if(d.error==='file_too_large'){d.error=t('err_file_too_large',{size:(file.size/1048576).toFixed(1),mb:d.max_mb||window.ABM_MAX_UPLOAD_MB||50})}
    if(d.error){showErr('aerr',d.error);lo.classList.remove('vis');hideUploadProgress();return}
    if(d.existing_job_id && d.is_running){
      jobId=d.existing_job_id;
      lo.classList.remove('vis');hideUploadProgress();
      let pct=0;
      if(d.status==='optimizing'){
        const cur=d.opt_progress_current||0, tot=d.opt_progress_total||1;
        pct=Math.round((cur/tot)*100);
      }else if(d.status==='generating'){
        const cur=d.progress_current||0, tot=d.progress_total||1;
        pct=Math.round((cur/tot)*100);
      }
      // Show the wizard first so the live progress bar is already in place,
      // pre-populate with the snapshot, then attach SSE so subsequent ticks
      // update both the wizard and the modal in-place.
      _showWizProgress();
      _setWizPct(pct);
      _showJobRunningModal(pct,jobId);
      if(d.status==='optimizing'){_listenOptProgressWiz()}
      else if(d.status==='generating'){listenProgress()}
      return;
    }
    bookData=d;jobId=d.job_id;lo.classList.remove('vis');hideUploadProgress();
    _startAnalyzedHeartbeat();
    isTxtFile=(d.file_type==='txt');
    const isAbmFile=(d.file_type==='abm');
    llmAvailable=!!d.llm_available;optimizedChapters=d.optimized_chapters||[];aiOptEnabled=false;
    _updateAiOptUI();
    if(d.language){
      const lc=d.language.split('-')[0].toLowerCase();
      const sel=document.getElementById('vl');
      if(sel.querySelector('option[value="'+lc+'"]')){sel.value=lc;}
    }
    updVoices();
    if(typeof syncLanguageOptions==='function')syncLanguageOptions();
    const _vOut=document.getElementById('vOut');
    _applyOutputOptionsForType(isTxtFile);
    document.getElementById('fgOut').style.display='';
    if(_vOut){_vOut.value='m4b';onOutputChange();}
    const btnExp=document.getElementById('btnExport');
    if(btnExp)btnExp.disabled=false;
    fillPreview(d);
    _updatePreviewBtn();
    // Unlock panel 2 and navigate to it
    _unlockStep(2);
    goToStep(2);
  }catch(e){showErr('aerr','Error: '+e.message);lo.classList.remove('vis')}
}

// ═══════════════════ VOICES ═══════════════════
async function loadVoices(){
  // Soft-load. Failures are not user-facing errors: the UI degrades to no
  // voice options but the page still renders. We must NOT log to
  // console.error because Googlebot's renderer reports those as critical
  // issues in Search Console (the /api/voices endpoint can return 499 when
  // the crawler aborts the connection before the response is ready).
  try{
    const r=await fetch('/api/voices',{headers:{'Accept':'application/json'}});
    if(!r.ok)return;
    const ct=(r.headers.get('content-type')||'').toLowerCase();
    if(ct.indexOf('application/json')===-1)return;
    const txt=await r.text();
    if(!txt)return;
    let data;
    try{ data=JSON.parse(txt); }
    catch(parseErr){return;}
    if(!data||typeof data!=='object')return;
    if(data._google_tts){
        _googleTtsBudget=data._google_tts;
        delete data._google_tts;
    }
    else{
        _googleTtsBudget=null;
    }
    // Stato Premium (capability/admin_disabled) salvato in variabile dedicata
    // e rimosso dal dict, cosi` fillLangs() non lo tratta come una lingua.
    if(data._premium_status){
        _premiumStatus=data._premium_status;
        delete data._premium_status;
    }else{
        _premiumStatus=null;
    }
    // Disponibilita' traduzione libro: se il backend non ha un modello di
    // traduzione configurato (ABM_TRANSLATE_MODEL) la feature e' nascosta.
    if('_translate_available' in data){
        _translateAvailable=(data._translate_available!==false);
        delete data._translate_available;
    }else{
        _translateAvailable=true; // retrocompat: server senza il flag
    }
    voices=data;
    _applyPremiumAvailability();
    _applyTranslateAvailability();
    fillLangs();
  }catch(e){
    /* swallow: see comment above */
  }
}

// Mostra/nasconde il tab "Voci PREMIUM" in base allo stato Premium dal backend.
// Tre casi distinti:
//   1) Capability OK + voci presenti      → tab visibile, cliccabile normalmente
//   2) Capability OK ma admin_disabled    → tab visibile MA cliccare apre popup
//      di manutenzione (vedi switchAudioTab). Cosi` l'utente sa che la feature
//      esiste ed e' temporaneamente sospesa, invece di vedere combo vuote.
//   3) Capability KO (non configurata)    → tab nascosto (come prima)
// La flag globale `_premiumMaintenance` viene letta da switchAudioTab() per
// bloccare il passaggio al tab con un modal. `_premiumStatus` e` popolata da
// loadVoices() leggendo la meta `_premium_status` di /api/voices.
let _premiumMaintenance=false;
let _premiumStatus=null;
// Disponibilita' della feature "traduzione libro". Popolata da loadVoices()
// leggendo la meta `_translate_available` di /api/voices. Se false il bottone
// "Traduci" e' nascosto (il server non ha ABM_TRANSLATE_MODEL configurato).
let _translateAvailable=true;
function _applyTranslateAvailability(){
  const btn=document.getElementById('btnTranslate');
  if(btn)btn.hidden=!_translateAvailable;
}
function _applyPremiumAvailability(){
  let hasPremium=false;
  try{
    for(const k in voices){
      const list=(voices[k]&&voices[k].voices)||[];
      for(const v of list){
        if(v&&typeof v.id==='string'&&v.id.startsWith('gemini:')){hasPremium=true;break;}
      }
      if(hasPremium)break;
    }
  }catch(_e){}
  // Distinzione admin-disabled vs non-configured tramite meta `_premiumStatus`.
  const ps=_premiumStatus;
  const capOk=ps?!!ps.capability_ok:false;
  const adminDisabled=ps?!!ps.admin_disabled:false;
  _premiumMaintenance=(capOk&&adminDisabled);
  const showTab=hasPremium||_premiumMaintenance;
  const btn=document.getElementById('tabPremiumBtn');
  const panel=document.getElementById('tabPremium');
  if(btn)btn.hidden=!showTab;
  if(!showTab){
    if(panel)panel.hidden=true;
    if(wizardState&&wizardState.audioTab==='premium'&&typeof switchAudioTab==='function'){
      switchAudioTab('standard');
    }
  }else if(_premiumMaintenance&&wizardState&&wizardState.audioTab==='premium'){
    // Edge case: kill-switch attivato mentre il tab Premium era aperto.
    // Forza il ritorno a Standard cosi` l'utente non resta su un pannello
    // svuotato. Il prossimo click su Premium mostrera` il popup.
    if(panel)panel.hidden=true;
    if(typeof switchAudioTab==='function')switchAudioTab('standard');
  }
  // Premium hint: se la tab è diventata indisponibile (nessuna voce / manutenzione)
  // rimuovi badge e coachmark; se è disponibile e siamo nello step Audio, rivaluta.
  if(!_premiumTabAvailable()){
    _dismissPremiumHint();
    const _b=document.getElementById('premiumTabBadge');
    if(_b)_b.hidden=true;
  }else if(_wizStep===3 && wizMode==='audio'){
    maybeShowPremiumHint();
  }
}

// Modal dedicato per la manutenzione del tab Premium. Costruito on-demand via
// DOM API (no innerHTML) cosi` non collide con altri modali e si autodistrugge
// alla chiusura. Stesso wrapper .modal-overlay/.modal usato altrove per CSS.
function _showPremiumMaintenanceModal(){
  const msgKey='premium_maintenance_msg';
  const titleKey='premium_maintenance_title';
  const fallbackMsg='The [PREMIUM Voices] feature is under maintenance and will be re-enabled in the next few hours.';
  const fallbackTitle='Feature under maintenance';
  let msg=fallbackMsg, ttl=fallbackTitle;
  try{
    const m=(typeof t==='function')?t(msgKey):msgKey;
    if(m&&m!==msgKey)msg=m;
    const tt=(typeof t==='function')?t(titleKey):titleKey;
    if(tt&&tt!==titleKey)ttl=tt;
  }catch(_e){}
  let okLabel='OK';
  try{const ok=(typeof t==='function')?t('sel_too_large_ok'):null;if(ok&&ok!=='sel_too_large_ok')okLabel=ok;}catch(_e){}
  const prev=document.getElementById('premiumMaintModal');
  if(prev&&prev.parentNode)prev.parentNode.removeChild(prev);
  const overlay=document.createElement('div');
  overlay.className='modal-overlay open';
  overlay.id='premiumMaintModal';
  overlay.setAttribute('role','dialog');
  overlay.setAttribute('aria-modal','true');
  const modal=document.createElement('div');
  modal.className='modal';
  modal.style.maxWidth='460px';
  // Stesso layout di #selTooLargeModal: head (titolo + close), body (testo + button OK).
  const head=document.createElement('div');
  head.className='modal-head';
  const headSpan=document.createElement('span');
  headSpan.textContent=ttl;
  head.appendChild(headSpan);
  const closeBtn=document.createElement('button');
  closeBtn.className='modal-close';
  closeBtn.setAttribute('aria-label','Close');
  closeBtn.textContent='×';
  head.appendChild(closeBtn);
  const bodyDiv=document.createElement('div');
  bodyDiv.className='modal-body';
  const msgP=document.createElement('p');
  msgP.style.margin='0 0 18px';
  msgP.style.lineHeight='1.6';
  msgP.style.fontSize='.92rem';
  msgP.textContent=msg;
  bodyDiv.appendChild(msgP);
  const actions=document.createElement('div');
  actions.style.display='flex';
  actions.style.gap='10px';
  actions.style.flexWrap='wrap';
  actions.style.justifyContent='flex-end';
  const okBtn=document.createElement('button');
  okBtn.type='button';
  okBtn.className='btn btn-ok';
  okBtn.textContent=okLabel;
  actions.appendChild(okBtn);
  bodyDiv.appendChild(actions);
  modal.appendChild(head);
  modal.appendChild(bodyDiv);
  overlay.appendChild(modal);
  const close=()=>{if(overlay.parentNode)overlay.parentNode.removeChild(overlay);};
  okBtn.addEventListener('click',close);
  closeBtn.addEventListener('click',close);
  overlay.addEventListener('click',(e)=>{if(e.target===overlay)close();});
  document.body.appendChild(overlay);
}
function fillLangs(){
  const sel=document.getElementById('vl');
  if(!sel) return;
  const oldVal = sel.value;
  sel.innerHTML='';
  
  // Ordine alfabetico basato sul nome tradotto. Il `count` mostrato accanto al
  // nome riflette solo le voci effettivamente visibili nel tab Standard: voci
  // gemini: escluse (vivono nel tab Premium), altrimenti "(64)" comparirebbe
  // identico tra i due tab anche quando in Standard si vedono 4 voci Edge.
  const sortedLangs = Object.entries(voices).map(([c, l]) => {
    let ln = c;
    if (L[cl] && L[cl].langs && L[cl].langs[c]) {
      ln = L[cl].langs[c];
    } else if (L['en'] && L['en'].langs && L['en'].langs[c]) {
      ln = L['en'].langs[c];
    } else {
      ln = l.name || c;
    }
    const standardCount = (Array.isArray(l.voices) ? l.voices : []).filter(v => !(v && typeof v.id === 'string' && v.id.startsWith('gemini:'))).length;
    return { code: c, name: ln, count: standardCount };
  }).sort((a, b) => a.name.localeCompare(b.name, cl));

  for(const l of sortedLangs){
    const o=document.createElement('option');
    o.value=l.code;
    o.textContent=l.name+' ('+l.count+')';
    sel.appendChild(o);
  }
  sel.onchange=()=>{
    updVoices();
    const dst=document.getElementById('vlPremium');
    if(dst){
      // Propaga la lingua al tab Premium solo se compatibile con il catalogo
      // Gemini; altrimenti lascia la precedente selezione Premium intatta
      // (evita il side-effect "value=stringa non presente" che azzera il select).
      const ok=Array.from(dst.options).some(o=>o.value===sel.value);
      if(ok){
        dst.value=sel.value;
        // La lingua premium è cambiata: ricostruisci i modelli e risincronizza
        // le righe dipendenti dal modello. Simba è solo inglese, quindi
        // passando a una lingua non-EN updModelsPremium NON ripropone Simba e
        // il modello torna a Gemini. Senza questo il modello resterebbe su
        // Simba anche per lingue incompatibili (es. italiano).
        if(typeof updModelsPremium==='function')updModelsPremium();
        if(typeof _onPremiumModelChanged==='function')_onPremiumModelChanged();
        else updVoicesPremium&&updVoicesPremium();
      }else{
        updVoicesPremium&&updVoicesPremium();
      }
    }
    // La lingua entra nella stima (cluster rate-log + ratio chars/token).
    if(typeof requestCombinedEstimate==='function')requestCombinedEstimate();
  };

  if(oldVal && voices[oldVal]) sel.value = oldVal;
  else {
    // Pre-selezione logica:
    let defaultLang = 'it';
    if(bookData && bookData.language) {
      defaultLang = bookData.language.split('-')[0].toLowerCase();
    } else if(voices[cl]) {
      defaultLang = cl;
    }
    if(voices[defaultLang]) sel.value=defaultLang;
    else if(Object.keys(voices).length>0) sel.value=Object.keys(voices)[0];
  }

  updVoices();
  syncLanguageOptions();
}

// Popola il selettore #vlPremium SOLO con le lingue per cui esiste almeno una
// voce Premium (id `gemini:`). Le lingue Edge che Gemini non supporta vengono
// escluse: l'utente le vede comunque nel tab Standard, mentre nel tab Premium
// il dropdown elenca esclusivamente l'offerta effettiva di Gemini TTS.
// Va chiamata dopo aver popolato #vl in fillLangs(), così la pre-selezione
// corrente di #vl viene rispettata (con fallback alla prima lingua disponibile
// se quella corrente non ha voci Premium).
function syncLanguageOptions(){
  const src=document.getElementById('vl');
  const dst=document.getElementById('vlPremium');
  if(!src||!dst)return;
  const currentVal=src.value;
  // Filtra: una lingua entra nel Premium dropdown solo se voices[lang].voices
  // contiene almeno una voce con id che inizia per "gemini:".
  const hasPremium=lc=>{
    const v=voices&&voices[lc];
    if(!v||!Array.isArray(v.voices))return false;
    return v.voices.some(x=>x&&typeof x.id==='string'&&x.id.startsWith('gemini:'));
  };
  // Mantieni l'ordine di #vl (priorità it, en, fr, de, es, pt poi alfabetico).
  const ordered=[];
  for(const o of src.options){
    if(hasPremium(o.value))ordered.push(o);
  }
  // Conta le voci Gemini DISTINTE per lingua (non le entry duplicate per
  // model_key): nella UI Premium l'utente sceglie prima il modello e poi la
  // voce, quindi il count rilevante è quello delle voci uniche disponibili.
  const geminiCount=lc=>{
    const v=voices&&voices[lc];
    if(!v||!Array.isArray(v.voices))return 0;
    const names=new Set();
    for(const x of v.voices){
      if(x&&typeof x.id==='string'&&x.id.startsWith('gemini:')){
        const parts=x.id.split(':');
        names.add(parts[parts.length-1]);
      }
    }
    return names.size;
  };
  while(dst.firstChild)dst.removeChild(dst.firstChild);
  for(const o of ordered){
    const clone=o.cloneNode(true);
    // Riscrive "Italiano (64)" → "Italiano (30)" per riflettere il numero di
    // voci Gemini effettive (regardless of model). Mantiene il nome tradotto
    // dell'opzione di origine senza re-eseguire la lookup i18n.
    const baseName=(o.textContent||'').replace(/\s*\(\d+\)\s*$/,'');
    clone.textContent=baseName+' ('+geminiCount(o.value)+')';
    dst.appendChild(clone);
  }
  // Pre-selezione: rispetta #vl se compatibile, altrimenti prima disponibile.
  if(ordered.some(o=>o.value===currentVal))dst.value=currentVal;
  else if(ordered.length>0)dst.value=ordered[0].value;
  if(typeof updModelsPremium==='function')updModelsPremium();
  // updModelsPremium può forzare il modello a Simba (default EN) via .value, che
  // NON emette 'change': sincronizza esplicitamente i controlli dipendenti dal
  // modello (riga accento/emozione/stile). Senza, su un nuovo libro la riga
  // accento Simba resta nascosta finché l'utente non cambia modello a mano.
  if(typeof _onPremiumModelChanged==='function')_onPremiumModelChanged();
  else if(typeof updVoicesPremium==='function')updVoicesPremium();
}
function _isGoogleVoice(id){return id&&id.startsWith('gcloud:')}
function _isGeminiVoice(id){return id&&id.startsWith('gemini:')}
function _googleTtsAffordable(){
  // True se Google TTS è disponibile e ha caratteri sufficienti per il libro corrente.
  // Se non c'è ancora un libro analizzato, basta che il budget non sia esaurito.
  if(!_googleTtsBudget||!_googleTtsBudget.available)return false;
  const remaining=_googleTtsBudget.chars_remaining||0;
  if(remaining<=0)return false;
  const bookChars=(bookData&&bookData.total_chars)||0;
  if(bookChars>0&&bookChars>remaining)return false;
  return true;
}
function updVoices(){
  const lc=document.getElementById('vl').value,sel=document.getElementById('vv');
  const oldVoice=sel.value;
  sel.innerHTML='';
  if(!voices[lc])return;
  const lang=voices[lc];
  // Separa voci per engine, edge prima poi google
  // SKIP gemini in Standard tab — voci premium gestite da updVoicesPremium()
  const edgeVoices=lang.voices.filter(v=>{
    if(v.id&&v.id.startsWith('gemini:'))return false; // SKIP gemini in Standard tab
    return (v.engine||'edge')==='edge';
  });
  // Mostra le voci Google solo se il budget mensile copre il libro corrente
  const googleVoices=_googleTtsAffordable()?lang.voices.filter(v=>{
    if(v.id&&v.id.startsWith('gemini:'))return false; // SKIP gemini in Standard tab
    return v.engine==='google';
  }):[];
  let lg='';
  // Voci Microsoft Edge
  for(const v of edgeVoices){
    if(v.gender!==lg){const g=document.createElement('optgroup');g.label=v.gender==='Female'?'♀':'♂';sel.appendChild(g);lg=v.gender}
    const o=document.createElement('option');o.value=v.id;o.textContent=v.gender_icon+' '+v.name+' ('+v.locale+')';
    sel.lastElementChild.appendChild(o);
  }
  // Voci Google HD (se presenti)
  if(googleVoices.length>0){
    lg='';
    for(const v of googleVoices){
      if(v.gender!==lg){
        const g=document.createElement('optgroup');
        const gLabel=v.gender==='Female'?'♀':(v.gender==='Male'?'♂':'⚥');
        g.label=gLabel+' Google HD';
        sel.appendChild(g);lg=v.gender;
      }
      const o=document.createElement('option');o.value=v.id;
      o.textContent=v.gender_icon+' '+v.name+' ('+v.locale+') ★';
      o.classList.add('gcloud-voice');
      sel.lastElementChild.appendChild(o);
    }
  }
  // Voci Gemini TTS NON inserite nella select Standard (vedi tab Premium).
  // Preserve user's prior voice selection if still available in the rebuilt list.
  // Setting sel.value to a non-existent option silently fails (sel.value becomes ''),
  // so we can detect a real restore by comparing back.
  let restored=false;
  if(oldVoice){
    sel.value=oldVoice;
    restored=(sel.value===oldVoice);
  }
  if(!restored){
    const dv=edgeVoices.find(v=>v.id.includes('Isabella')||v.id.includes('Guy')||v.id.includes('Davis'))||edgeVoices[0]||lang.voices[0];
    if(dv)sel.value=dv.id;
  }
  // Su cambio voce: _onPreviewParamsChanged() gestisce il reset dello stato
  // anteprima in base alla signature dei parametri (no cache su nuove combo,
  // restore se gia` generata in passato). Sostituisce _resetPreviewState().
  sel.onchange=()=>{_updateVoiceChip();checkVoiceMismatch();_onPreviewParamsChanged();};
  _updateVoiceChip();checkVoiceMismatch();
  // Reset speed to "Normal" (+0%) only when the voice actually changed (language change or first build).
  // When the previous selection is preserved (e.g. applyI18n→fillLangs→updVoices triggered by a modal),
  // keep the user's current speed.
  if(!restored){
    var vrSel2=document.getElementById('vr');
    if(vrSel2)vrSel2.value='+0%';
    var ss=document.getElementById('speedSlider');
    if(ss)ss.value=0;
    var sl=document.getElementById('speedLabel');
    if(sl)sl.textContent=t('sp_n');
  }
}

// ═══════════════════ PREMIUM (Gemini) VOICE TAB ═══════════════════

// Popola #vmPremium in base alla lingua premium corrente. Per l'inglese aggiunge
// l'opzione "Simba (English)" (id modello 'simba-3.2') e la preseleziona come
// default; per le altre lingue elenca solo i modelli Gemini.
function updModelsPremium(){
  const vlEl=document.getElementById('vlPremium');
  const vmEl=document.getElementById('vmPremium');
  if(!vmEl)return;
  const lang=(vlEl&&vlEl.value)||'it';
  const prev=vmEl.value;
  vmEl.innerHTML='';
  const addOpt=(val,label)=>{const o=document.createElement('option');o.value=val;o.textContent=label;vmEl.appendChild(o);};
  const isEnglish=(lang==='en');
  // Modelli Gemini (sempre presenti). Le etichette usano i18n se disponibili.
  addOpt('flash25', t('lbl_model_flash25')||'Standard');
  addOpt('flash31', t('lbl_model_flash31')||'Avanzato');
  if(isEnglish){
    // Speechify Simba disponibile solo se il catalogo espone voci speechify per 'en'.
    const en=voices&&voices['en'];
    const arr=en&&Array.isArray(en.voices)?en.voices:[];
    const hasSimba=arr.some(v=>v&&typeof v.id==='string'&&v.id.startsWith('speechify:simba-3.2:'));
    if(hasSimba){
      addOpt('simba-3.2', t('lbl_model_simba')||'Simba (English)');
    }
  }
  // Default: su inglese preferisci Simba (se presente), altrimenti mantieni la
  // scelta precedente se ancora valida, altrimenti il primo modello.
  let target=null;
  if(isEnglish && vmEl.querySelector('option[value="simba-3.2"]')) target='simba-3.2';
  else if(prev && vmEl.querySelector('option[value="'+prev+'"]')) target=prev;
  else target=vmEl.options.length?vmEl.options[0].value:'flash25';
  vmEl.value=target;
}

// Accenti Speechify Simba: locale che filtrano le 8 voci _32 e valorizzano
// il campo language inviato all'API.
const _SPEECHIFY_ACCENTS=[['en-US','American English'],['en-GB','British English']];

// Selezione Speechify persistita fuori dal DOM: il dropdown `geminiAccent` è
// CONDIVISO con Gemini e viene ripopolato da _updateAccentDropdown() con codici
// accento Gemini; leggere `prev` dal solo DOM fa perdere la scelta dell'utente
// (accento -> reset en-US, voce -> reset alla prima = harper_32). Queste due
// variabili sono la fonte di verità per accento e voce Speechify, aggiornate
// solo dagli onchange utente e usate per ripristinare dopo ogni rebuild.
let _speechifyAccentSel='';
let _speechifyVoiceSel='';

function _isSpeechifyModelSelected(){
  const vm=document.getElementById('vmPremium');
  return !!(vm&&vm.value==='simba-3.2');
}

// Mostra/nasconde i controlli in base al modello premium selezionato e
// (ri)popola voci/emozioni/accento coerentemente.
function _onPremiumModelChanged(){
  const styleRow=document.getElementById('geminiStyleRow');
  const emoRow=document.getElementById('speechifyEmotionRow');
  const accentRow=document.getElementById('geminiAccentRow');
  const simba=_isSpeechifyModelSelected();
  if(styleRow)styleRow.hidden=simba;
  if(emoRow)emoRow.hidden=!simba;
  if(simba){
    _populateSpeechifyAccents();
    _populateSpeechifyEmotions();
    if(accentRow)accentRow.hidden=false;   // accento (locale) sempre visibile per Simba
  }else{
    // Gemini: ripristina l'accento gemini gestito da _updateAccentDropdown().
    if(typeof _updateAccentDropdown==='function')_updateAccentDropdown();
  }
  updVoicesPremium();
  if(typeof _onPreviewParamsChanged==='function')_onPreviewParamsChanged();
}

function _populateSpeechifyAccents(){
  const acc=document.getElementById('geminiAccent');
  if(!acc)return;
  // Fonte di verità: la selezione Speechify persistita, NON acc.value (che può
  // contenere un codice accento Gemini se il dropdown condiviso è stato appena
  // ripopolato da _updateAccentDropdown()). Fallback ad acc.value solo se non
  // c'è ancora una scelta Speechify registrata.
  const prev=(_speechifyAccentSel&&_SPEECHIFY_ACCENTS.some(a=>a[0]===_speechifyAccentSel))?_speechifyAccentSel:acc.value;
  acc.innerHTML='';
  for(const [code,label] of _SPEECHIFY_ACCENTS){
    const o=document.createElement('option');o.value=code;o.textContent=label;acc.appendChild(o);
  }
  acc.value=(_SPEECHIFY_ACCENTS.some(a=>a[0]===prev))?prev:'en-US';
  _speechifyAccentSel=acc.value;
  acc.onchange=()=>{_speechifyAccentSel=acc.value;updVoicesPremium();if(typeof _onPreviewParamsChanged==='function')_onPreviewParamsChanged();};
}

function _populateSpeechifyEmotions(){
  const sel=document.getElementById('speechifyEmotion');
  if(!sel)return;
  const emotions=['angry','cheerful','sad','terrified','relaxed','fearful','surprised','calm','assertive','energetic','warm','direct','bright'];
  const prev=sel.value;
  sel.innerHTML='';
  const none=document.createElement('option');none.value='';none.textContent=t('emotion_none')||'None (neutral)';sel.appendChild(none);
  for(const e of emotions){
    const o=document.createElement('option');o.value=e;o.textContent=(t('emotion_'+e)||e);sel.appendChild(o);
  }
  sel.value=prev||'';
  sel.onchange=()=>{if(typeof _onPreviewParamsChanged==='function')_onPreviewParamsChanged();};
}

function updVoicesPremium(){
  const vlEl=document.getElementById('vlPremium');
  const vmEl=document.getElementById('vmPremium');
  const sel=document.getElementById('vvPremium');
  if(!sel)return;
  // --- Ramo Speechify Simba-3.2: voci filtrate per accento (locale), non per lingua ---
  if(vmEl&&vmEl.value==='simba-3.2'){
    const accEl=document.getElementById('geminiAccent');
    const locale=(accEl&&accEl.value)||'en-US';
    const en=voices&&voices['en'];
    const arr=en&&Array.isArray(en.voices)?en.voices:[];
    const spx=arr.filter(v=>v&&typeof v.id==='string'&&v.id.startsWith('speechify:simba-3.2:')&&v.locale===locale);
    // Preserva la voce scelta dall'utente attraverso il rebuild: senza questo,
    // ogni ricostruzione (cambio tab/modello/re-analyze) azzera la selezione
    // alla prima voce del locale corrente. Fonte di verità = _speechifyVoiceSel.
    const prevVoice=_speechifyVoiceSel||sel.value;
    sel.innerHTML='';
    let lg='';
    for(const v of spx){
      if(v.gender!==lg){const g=document.createElement('optgroup');g.label=v.gender==='Female'?'♀':'♂';sel.appendChild(g);lg=v.gender;}
      const o=document.createElement('option');o.value=v.id;
      o.textContent=(v.gender_icon?v.gender_icon+' ':'')+(v.name||v.id.split(':').pop());
      sel.lastElementChild.appendChild(o);
    }
    // Ripristina la voce se ancora presente nel locale corrente; altrimenti resta
    // la prima (comportamento corretto quando l'utente cambia accento).
    if(prevVoice&&Array.prototype.some.call(sel.options,o=>o.value===prevVoice))sel.value=prevVoice;
    _speechifyVoiceSel=sel.value;
    sel.onchange=()=>{_speechifyVoiceSel=sel.value;if(typeof _onPreviewParamsChanged==='function')_onPreviewParamsChanged();};
    return;
  }
  // --- Ramo Gemini (esistente) ---
  const lang=(vlEl&&vlEl.value)||'it';
  const modelKey=(vmEl&&vmEl.value)||'flash25';
  sel.innerHTML='';
  // Costruisce la lista voci Premium da voices[lang].voices filtrando per engine=gemini
  // e per modelKey (encoded nell'id come "gemini:<modelKey>:<voiceName>").
  const langData=voices[lang];
  const all=langData&&Array.isArray(langData.voices)?langData.voices:[];
  const prefix='gemini:'+modelKey+':';
  // Filtra per modello selezionato e lingua (voci Gemini sono multilingue).
  const premiumVoices=all.filter(v=>{
    if(!v||!v.id)return false;
    if(!v.id.startsWith(prefix))return false;
    if(v.lang&&v.lang!==lang&&v.lang!=='multi')return false;
    return true;
  });
  // Raggruppa per gender con <optgroup label="♀|♂">, replicando il pattern
  // del combo Edge (updVoices). Il backend ordina già Female prima di Male.
  let lg='';
  for(const v of premiumVoices){
    if(v.gender!==lg){
      const g=document.createElement('optgroup');
      g.label=v.gender==='Female'?'♀':(v.gender==='Male'?'♂':'•');
      sel.appendChild(g);
      lg=v.gender;
    }
    const opt=document.createElement('option');
    opt.value=v.id;
    opt.textContent=(v.gender_icon?v.gender_icon+' ':'')+(v.name||v.label||v.id.split(':').pop());
    const target=sel.lastElementChild&&sel.lastElementChild.tagName==='OPTGROUP'?sel.lastElementChild:sel;
    target.appendChild(opt);
  }
  sel.onchange=()=>{_updateAccentDropdown();_onPreviewParamsChanged();};
  // Dropdown accento: dipende da lingua + voce premium correnti.
  if(typeof _updateAccentDropdown==='function')_updateAccentDropdown();
  // Rate hint viene popolato dalla stima del backend (renderEstimate); qui niente fallback statico.
}

function updateModelRateHint(data){
  // Rate per-minute derivato dall'ultima stima del backend, così rate x minuti = totale.
  // data: payload di /api/combined_estimate (può essere null se non ancora disponibile).
  const hint=document.getElementById('modelRateHint');
  if(!hint)return;
  if(!data||!data.gemini_breakdown){hint.textContent='';return;}
  const mins=Number(data.gemini_breakdown.audio_minutes||0);
  const eur=Number(data.gemini_eur||0);
  if(!(mins>0)||!(eur>0)){hint.textContent='';return;}
  const ratePerMin=eur/mins;
  const tmpl=(window.t&&t('model_rate_per_min'))||'~€{r}/min audio (stima)';
  hint.textContent=tmpl.replace('{r}',ratePerMin.toFixed(4));
}

// ═══════════════ Premium hint (coachmark + badge) ═══════════════
// Stato persistente client-side: una sola chiave JSON in localStorage.
//   { shows:<int>, lastDay:"YYYY-MM-DD", discovered:<bool> }
// - coachmark: max _PREMIUM_HINT_MAX apparizioni totali, 1/giorno, mai dopo discovery.
// - badge: visibile finché !discovered e tab Premium disponibile.
const _PREMIUM_HINT_KEY='abm_premium_hint';
const _PREMIUM_HINT_MAX=3;
let _premiumCoachTimer=null;

function _premiumHintLoad(){
  try{
    const raw=localStorage.getItem(_PREMIUM_HINT_KEY);
    if(!raw)return{shows:0,lastDay:'',discovered:false};
    const o=JSON.parse(raw);
    return{shows:(o.shows|0),lastDay:String(o.lastDay||''),discovered:!!o.discovered};
  }catch(e){return{shows:0,lastDay:'',discovered:false};}
}
function _premiumHintSave(s){
  try{localStorage.setItem(_PREMIUM_HINT_KEY,JSON.stringify(s));}catch(e){}
}
function _premiumHintToday(){
  const d=new Date();
  const m=String(d.getMonth()+1).padStart(2,'0');
  const day=String(d.getDate()).padStart(2,'0');
  return d.getFullYear()+'-'+m+'-'+day;
}
// La tab Premium è "utilizzabile" solo se visibile e non in manutenzione.
function _premiumTabAvailable(){
  const btn=document.getElementById('tabPremiumBtn');
  return !!btn && !btn.hidden && !_premiumMaintenance;
}
function _showPremiumCoach(){
  const coach=document.getElementById('premiumCoach');
  const btn=document.getElementById('tabPremiumBtn');
  if(!coach||!btn)return false;
  // Allinea la bolla all'inizio del tab Premium.
  coach.style.left=(btn.offsetLeft)+'px';
  coach.hidden=false;
  // Punta la freccia al centro della parola "PREMIUM" nella tab (fallback: centro tab).
  try{
    const tn=btn.firstChild;
    const txt=(tn&&tn.textContent)||'';
    const i=txt.toUpperCase().indexOf('PREMIUM');
    const coachX=coach.getBoundingClientRect().left;
    let targetX;
    if(tn&&i>=0&&document.createRange){
      const rng=document.createRange();
      rng.setStart(tn,i); rng.setEnd(tn,i+7);
      const rr=rng.getBoundingClientRect();
      targetX=rr.left+rr.width/2;
    }else{
      const br=btn.getBoundingClientRect();
      targetX=br.left+br.width/2;
    }
    coach.style.setProperty('--arrow-left',(targetX-coachX-6)+'px'); // -6 = metà larghezza freccia
  }catch(e){}
  if(_premiumCoachTimer)clearTimeout(_premiumCoachTimer);
  _premiumCoachTimer=setTimeout(_dismissPremiumHint,12000);
  return true;
}
function _dismissPremiumHint(){
  const coach=document.getElementById('premiumCoach');
  if(coach)coach.hidden=true;
  if(_premiumCoachTimer){clearTimeout(_premiumCoachTimer);_premiumCoachTimer=null;}
}
function _markPremiumDiscovered(){
  const st=_premiumHintLoad();
  if(!st.discovered){st.discovered=true;_premiumHintSave(st);}
  _dismissPremiumHint();
  const badge=document.getElementById('premiumTabBadge');
  if(badge)badge.hidden=true;
}
// Valuta e (se del caso) mostra badge + coachmark. Idempotente.
function maybeShowPremiumHint(){
  if(!_premiumTabAvailable())return;
  if(wizardState && wizardState.audioTab==='premium')return;
  const st=_premiumHintLoad();
  if(st.discovered)return;
  // Badge: sempre quando non scoperto e tab disponibile.
  const badge=document.getElementById('premiumTabBadge');
  if(badge)badge.hidden=false;
  // Coachmark: gate cap totale + 1/giorno.
  if(st.shows>=_PREMIUM_HINT_MAX)return;
  if(st.lastDay===_premiumHintToday())return;
  if(!_showPremiumCoach())return;
  st.shows++; st.lastDay=_premiumHintToday(); _premiumHintSave(st);
}

function switchAudioTab(tab){
  const prev=wizardState.audioTab;
  // Guard Premium #1: kill-switch admin (manutenzione). Se le voci PREMIUM
  // sono temporaneamente disabilitate dall'admin, il tab resta visibile ma
  // cliccarlo NON cambia tab — mostra solo un popup di manutenzione. Cosi`
  // l'utente sa che la funzionalita` esiste e tornera`, invece di vedere
  // combo lingua/voce svuotate che fanno sembrare l'app rotta.
  if(tab==='premium'&&prev!=='premium'&&_premiumMaintenance){
    _showPremiumMaintenanceModal();
    return;
  }
  // Guard Premium #2: blocca lo switch se la selezione capitoli supera il cap
  // Gemini (`max_gemini_text_chars`, di norma 800k). Il warning va mostrato
  // SOLO al click sul tab Premium — non in `tryGoToAudioSettings()` dove
  // bloccherebbe l'utente che vuole solo usare voci Standard (cap 1.5M).
  if(tab==='premium'&&prev!=='premium'){
    const cap=(bookData&&bookData.max_gemini_text_chars)|0;
    if(cap>0){
      const chars=_computeSelectedChars();
      if(chars>cap){
        _dismissPremiumHint();
        _showSelTooLargeModal(chars,cap);
        return; // niente switch: il tab resta su Standard
      }
    }
  }
  wizardState.audioTab=tab;
  // Premium hint: qualsiasi switch riuscito chiude il coachmark; aprire la tab
  // Premium = "scoperta" → soppressione definitiva di coachmark e badge.
  _dismissPremiumHint();
  if(tab==='premium')_markPremiumDiscovered();
  document.querySelectorAll('.tab-bar .tab').forEach(t=>{
    const active=t.dataset.tab===tab;
    t.classList.toggle('active',active);
    t.setAttribute('aria-selected',active?'true':'false');
  });
  const tStd=document.getElementById('tabStandard');
  const tPrm=document.getElementById('tabPremium');
  if(tStd)tStd.hidden=(tab!=='standard');
  if(tPrm)tPrm.hidden=(tab!=='premium');
  // Il box stima costo è rilevante solo per il tab Premium (Standard è gratis).
  const cpBox=document.getElementById('costPreviewBox');
  if(cpBox)cpBox.hidden=(tab!=='premium');
  // Fallback class per browser senza :has(): tinge la border-bottom della tab-bar
  // del colore dorato quando Premium è attivo.
  document.querySelectorAll('.tab-bar').forEach(b=>{
    b.classList.toggle('tabbar-premium-active',tab==='premium');
  });
  // Mantieni la selezione voce in entrambi i tab: tornando al tab di origine,
  // l'anteprima eventualmente già generata (firma in _knownPreviewSigs) deve
  // restare disponibile. La voce "attiva" è risolta da getCurrentVoiceId() in
  // base al tab corrente, quindi non serve azzerare l'altro tab.
  if(tab==='premium'){
    // Sincronizza i controlli dipendenti dal modello (accento/emozione/stile)
    // all'ingresso nel tab: il modello può essere già impostato a Simba senza
    // che sia scattato un evento 'change', lasciando la riga accento nascosta.
    if(typeof _onPremiumModelChanged==='function')_onPremiumModelChanged();
    else updVoicesPremium();
  }
  if(prev!==tab){
    // Pausa la riproduzione corrente e ricalibra il player sull'anteprima
    // del tab attivo: se la firma è in _knownPreviewSigs ricarica l'audio,
    // altrimenti nasconde il player ma NON cancella le firme note.
    const a=document.getElementById('previewAudioWiz');if(a)a.pause();
    if(typeof _onPreviewParamsChanged==='function')_onPreviewParamsChanged();
  }
  if(typeof requestCombinedEstimate==='function')requestCombinedEstimate();
}

// Helper: ritorna l'id della voce attualmente attiva, in base al tab selezionato.
function getCurrentVoiceId(){
  if(wizardState.audioTab==='premium'){
    const el=document.getElementById('vvPremium');
    return el?el.value:'';
  }
  const el=document.getElementById('vv');
  return el?el.value:'';
}

// ── Combined cost estimate (debounced + cached) ──
// Trigger: tab change / model change / ai_opt toggle / chapter selection change.
// no re-estimate on voice change (cost is per-model, not per-voice)
let estimateDebounceTimer=null;
const _estimateCache={key:null,value:null};
// Lettura opzionale del testo tra parentesi (default: rimosso).
function getParenFlags(){
  return {
    read_round_parens:!!document.getElementById('readRoundParens')?.checked,
    read_square_brackets:!!document.getElementById('readSquareBrackets')?.checked,
  };
}
function getEstimateCacheKey(){
  const tab=wizardState.audioTab||'standard';
  const model=(tab==='premium')?(document.getElementById('vmPremium')?.value||'flash25'):'none';
  const aiOpt=document.getElementById('aiToggle')?.checked?'1':'0';
  const chapters=(typeof _getSelectedChapterIndexes==='function'?_getSelectedChapterIndexes():[]).join(',');
  const rate=document.getElementById('vr')?.value||'+0%';
  const langEl=(tab==='premium')?document.getElementById('vlPremium'):document.getElementById('vl');
  const lang=(langEl&&langEl.value)||cl||'';
  const pf=getParenFlags();
  const paren=(pf.read_round_parens?'1':'0')+(pf.read_square_brackets?'1':'0');
  return (jobId||'')+'|'+tab+'|'+model+'|'+aiOpt+'|'+rate+'|'+lang+'|'+chapters+'|'+paren;
}
function requestCombinedEstimate(){
  if(estimateDebounceTimer)clearTimeout(estimateDebounceTimer);
  estimateDebounceTimer=setTimeout(_doCombinedEstimate,300);
}
async function _doCombinedEstimate(){
  if(!jobId){renderEstimate(null);return;}
  const key=getEstimateCacheKey();
  if(_estimateCache.key===key&&_estimateCache.value){renderEstimate(_estimateCache.value);return;}
  const voiceId=(typeof getCurrentVoiceId==='function')?getCurrentVoiceId():'';
  const selected=(typeof _getSelectedChapterIndexes==='function')?_getSelectedChapterIndexes():[];
  if(!selected||selected.length===0){renderEstimate(null);return;}
  // Lingua TTS scelta in "Impostazioni audio": prevale su metadata libro
  // per stima durata/costo (cluster rate-log + ratio chars/token).
  const selLangEl=(wizardState.audioTab==='premium')
    ?document.getElementById('vlPremium')
    :document.getElementById('vl');
  const selLang=(selLangEl&&selLangEl.value)||cl||'';
  const payload={
    job_id:jobId,
    voice_id:voiceId||'',
    selected_chapters:selected,
    ai_opt_enabled:!!document.getElementById('aiToggle')?.checked,
    rate:document.getElementById('vr')?.value||'+0%',
    lang:selLang,
    ...getParenFlags(),
  };
  try{
    const r=await fetch('/api/combined_estimate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if(!r.ok)throw new Error('estimate failed');
    const data=await r.json();
    if(getEstimateCacheKey()!==key)return;
    if(data.paypal_client_id!==undefined){
      llmConfig.paypalClientId=data.paypal_client_id||"";
      llmConfig.paypalMode=data.paypal_mode||"sandbox";
      llmConfig.paypalAvailable=!!data.paypal_available;
    }
    _estimateCache.key=key;
    _estimateCache.value=data;
    renderEstimate(data);
  }catch(e){
    console.warn('combined_estimate error:',e);
    if(getEstimateCacheKey()===key)renderEstimate(null);
  }
}
function renderEstimate(data){
  const valueEl=document.getElementById('costPreviewValue');
  const detailEl=document.getElementById('costPreviewDetail');
  const labelEl=document.querySelector('#costPreviewBox .cost-label');
  const costAmount=document.getElementById('costAmount');
  // Label condizionale: "audiolibro" se tutti i capitoli selezionati, "capitoli selezionati" altrimenti.
  if(labelEl){
    let isPartial=false;
    try{
      const allCbs=(typeof _getAllCheckboxes==='function')?_getAllCheckboxes():[];
      const selCount=(typeof _getSelectedChapterIndexes==='function')?_getSelectedChapterIndexes().length:0;
      isPartial=(allCbs&&allCbs.length>0&&selCount>0&&selCount<allCbs.length);
    }catch(_){}
    const key=isPartial?'cost_estimate_label_partial':'cost_estimate_label';
    const fallback=isPartial?'Stima costo capitoli selezionati':'Stima costo audiolibro';
    labelEl.textContent=(window.t&&t(key))||fallback;
    labelEl.setAttribute('data-t',key);
  }
  if(!data){
    if(valueEl)valueEl.textContent='—';
    if(detailEl)detailEl.textContent='';
    updateModelRateHint(null);
    return;
  }
  // Nota: data.gemini_overloaded e' una proprieta' informativa restituita dal
  // server per il modello selezionato; la valutazione del blocco avviene solo
  // al click di "Prosegui" (vedi onGenerateClick), non qui — l'utente puo'
  // continuare ad esplorare modelli/voci senza popup intrusivi.
  if(valueEl){
    if(data.is_free){valueEl.textContent=(window.t&&t('cost_free'))||'Gratis';}
    else{valueEl.textContent='€'+Number(data.total_eur).toFixed(2);}
  }
  if(detailEl){
    const mins=Number(data.gemini_breakdown&&data.gemini_breakdown.audio_minutes||0);
    // La stima minuti scala ora con rate_pct (vedi gemini_tts.estimate_audio_seconds):
    // la label velocità deve quindi riflettere il rate selezionato dallo slider.
    const rateStep=(data.rate_step!=null)?Number(data.rate_step)
                   :(data.gemini_breakdown&&data.gemini_breakdown.rate_step!=null?Number(data.gemini_breakdown.rate_step):0);
    const SPEED_KEYS=['sp_vs','sp_s','sp_ss','sp_n','sp_sf','sp_f','sp_vf'];
    const speedLabel=(window.t&&t(SPEED_KEYS[Math.max(0,Math.min(6,rateStep+3))]))||'normale';
    const minsTmpl=(window.t&&t('cost_minutes_detail_speed'))||'≈ {n} min audio (velocità: {speed})';
    const minsStr=(mins>0)?minsTmpl.replace('{n}',mins.toFixed(1)).replace('{speed}',speedLabel):'';
    if(data.is_free){
      const threshold=Number(data.threshold_eur||0).toFixed(2);
      const base='≤ €'+threshold+' '+((window.t&&t('cost_under_threshold'))||'sotto soglia');
      detailEl.textContent=minsStr?(base+' · '+minsStr):base;
    }else{
      // La voce "Voci PREMIUM €X" è ridondante col totale in grande; mostriamo
      // solo l'addendo AI quando presente (per spiegare la differenza dal solo Premium).
      const parts=[];
      if(data.llm_eur>0)parts.push('+ Ottimizzazione testo AI €'+Number(data.llm_eur).toFixed(2));
      const extra=parts.join(' ');
      const segs=[];
      if(extra)segs.push(extra);
      if(minsStr)segs.push(minsStr);
      detailEl.textContent=segs.join(' · ');
    }
  }
  if(costAmount)costAmount.textContent='€'+Number(data.total_eur).toFixed(2);
  updateModelRateHint(data);
}

// ═══════════════════ PAYMENT MODAL (parametrico) ═══════════════════
// _payState: stato runtime del popup. _payCtx: comportamento del flusso corrente.
// Il campo `gemini` è letto dal flusso di generazione premium (stima rimborso):
// va preservato — vale 0 per i flussi non-premium (es. traduzione).
let _payState = { total: 0, gemini: 0, token: null, method: null };
let _payCtx = null;
let _generatingModal = false;

async function onGenerateClick() {
  if (_generatingModal) return;
  _generatingModal = true;
  try {
    // Guard cap: se la voce attiva e' PREMIUM e la selezione supera il cap
    // Gemini (max_gemini_text_chars), blocca PRIMA di stima/pagamento. La guard
    // su switchAudioTab scatta solo al cambio tab: se l'utente entra in Premium
    // con selezione valida e poi aggiunge capitoli oltre il cap, senza questo
    // controllo arriverebbe a pagare un job non generabile.
    const _activeVoice=(typeof getCurrentVoiceId==='function')?getCurrentVoiceId():'';
    if(_isGeminiVoiceId(_activeVoice)){
      const _cap=(bookData&&bookData.max_gemini_text_chars)|0;
      if(_cap>0){
        const _chars=_computeSelectedChars();
        if(_chars>_cap){_showSelTooLargeModal(_chars,_cap);return;}
      }
    }
    await _doCombinedEstimate();
    const est = _estimateCache && _estimateCache.value;
    // Preflight RPD: blocca PRIMA della richiesta pagamento.
    if (est && est.gemini_overloaded) {
      try { _showGeminiOverloadModal(est.gemini_overload_info||{}); } catch(_e){}
      return;
    }
    if (!est || est.is_free) {
      return startCombinedGeneration();
    }
    // Voci STANDARD: il costo (solo LLM) si paga dentro startCombinedGeneration
    // col modal condiviso Buono/PayPal (_showPaymentModal), al momento del
    // Generate — quando la selezione capitoli è definitiva e l'importo non può
    // più cambiare. Il modale combinato (con riga "Voci PREMIUM") è riservato
    // alle voci PREMIUM: aprirlo qui per le standard duplicherebbe il pagamento.
    if (wizardState.audioTab !== 'premium') {
      return startCombinedGeneration(null);
    }
    openPaymentModal(est);
  } finally {
    _generatingModal = false;
  }
}

// Apre il popup geminiPayModal parametrizzato da un contesto:
//   lines: [{labelKey, amount}]  (1 o 2 righe; le righe in eccesso vengono nascoste)
//   total: number
//   geminiAmount?: number  (importo premium per la stima rimborso; default 0)
//   voucherPurpose: string  (passato a /api/voucher_validate, solo audit)
//   paypal: { endpoint, buildBody:()=>({...}) }
//   onConfirm: (token)=>void
//   onCancel?: ()=>void  (chiusura senza conferma; usato dai flussi promise-based)
function _openPayModalCtx(ctx) {
  _payCtx = ctx;
  _payConfirmed = false;
  _payState = { total: ctx.total, gemini: ctx.geminiAmount || 0, token: null, method: null };
  // Mappa fissa ctx.lines[i] -> (etichetta, importo) nel markup.
  const rowMap = [
    { labelId: 'payLineGeminiLabel', amountId: 'payLineGemini' },
    { labelId: 'payLineLlmLabel', amountId: 'payLineLlm' },
  ];
  rowMap.forEach((ids, i) => {
    const line = ctx.lines[i];
    const amtEl = document.getElementById(ids.amountId);
    const labEl = document.getElementById(ids.labelId);
    const rowEl = amtEl ? amtEl.closest('.pay-line') : null;
    if (line) {
      if (labEl) {
        labEl.setAttribute('data-t', line.labelKey);
        labEl.textContent = (typeof t === 'function') ? t(line.labelKey) : line.labelKey;
      }
      if (amtEl) amtEl.textContent = (line.amount > 0) ? `€${line.amount.toFixed(2)}` : '—';
      if (rowEl) rowEl.style.display = '';
    } else {
      if (rowEl) rowEl.style.display = 'none';
    }
  });
  const tot = document.getElementById('payModalTotal');
  if (tot) tot.textContent = `€${ctx.total.toFixed(2)}`;
  const vErr = document.getElementById('payVoucherError');
  if (vErr) { vErr.textContent = ''; vErr.style.color = ''; }
  const pErr = document.getElementById('payPaypalError');
  if (pErr) pErr.textContent = '';
  const btn = document.getElementById('btnPayConfirm');
  if (btn) btn.disabled = true;
  _geminiPayCaptured = false;  // nuova sessione modal: nessun capture ancora
  const vc = document.getElementById('geminiPayVoucherCode'); if (vc) vc.value = '';
  const ve = document.getElementById('geminiPayVoucherEmail');
  if (ve && typeof lastVoucherEmail === 'string') ve.value = lastVoucherEmail;
  switchPayTab('voucher');
  const modal = document.getElementById('geminiPayModal');
  if (modal) modal.hidden = false;
}

// Chiamante Gemini: costruisce il contesto e apre il popup.
function openPaymentModal(estimate) {
  _openPayModalCtx({
    // Importo premium = engine attivo (Gemini o Speechify, mutuamente esclusivi:
    // una sola voce premium selezionata). Usare solo gemini_eur mostrerebbe "—"
    // per le voci Speechify pur avendo un totale a pagamento.
    lines: [
      { labelKey: 'pay_premium_voices', amount: (Number(estimate.gemini_eur)||0)+(Number(estimate.speechify_eur)||0) },
      { labelKey: 'pay_text_ai_optimization', amount: estimate.llm_eur },
    ],
    total: estimate.total_eur,
    geminiAmount: (Number(estimate.gemini_eur)||0)+(Number(estimate.speechify_eur)||0),
    voucherPurpose: 'gemini',
    paypal: {
      endpoint: '/api/paypal_create_order_gemini',
      buildBody: () => {
        const _selLangEl = (wizardState.audioTab === 'premium') ? document.getElementById('vlPremium') : document.getElementById('vl');
        const _selLang = (_selLangEl && _selLangEl.value) || cl || '';
        return { job_id: jobId, voice_id: (typeof getCurrentVoiceId === 'function') ? getCurrentVoiceId() : '', selected_chapters: (typeof _getSelectedChapterIndexes === 'function') ? _getSelectedChapterIndexes() : [], ai_opt_enabled: !!document.getElementById('aiToggle')?.checked, rate: document.getElementById('vr')?.value || '+0%', lang: _selLang, amount_eur: _payState.total };
      },
    },
    onConfirm: (token) => startCombinedGeneration(token),
  });
}

// True dopo onPayConfirm nella sessione modal corrente: distingue la chiusura
// post-conferma dall'annullo (X / Annulla). Reset a ogni _openPayModalCtx.
let _payConfirmed = false;
function closePaymentModal() {
  const modal = document.getElementById('geminiPayModal');
  if (modal) modal.hidden = true;
  // Chiusura senza conferma = annullo: notifica il flusso chiamante (una sola
  // volta). I contesti senza onCancel (premium/traduzione) non sono toccati.
  const ctx = _payCtx;
  if (ctx && !_payConfirmed && typeof ctx.onCancel === 'function') {
    _payCtx = null;
    ctx.onCancel();
  }
}

// ─────────── PayPal buttons in combined payment modal ───────────
let _paypalGeminiButtonsInstance = null;
// Anti doppio-addebito: true dopo un capture PayPal andato a buon fine nella
// sessione modal corrente. Blocca la creazione di un secondo ordine se l'utente
// ri-clicca il bottone PayPal invece di premere Conferma. Reset all'apertura del
// modal. Vedi incidente doppio pagamento K1Rpn (2026-07).
let _geminiPayCaptured = false;
function _payPaypalErr(msg){const e=document.getElementById('payPaypalError');if(e){e.style.color='';e.textContent=msg||''}}
async function renderPaypalGeminiButtons(){
  const container=document.getElementById('paypalGeminiContainer');
  if(!container)return;
  container.innerHTML='';_payPaypalErr('');
  if(!llmConfig.paypalAvailable||!llmConfig.paypalClientId){_payPaypalErr((typeof t==='function'&&t('pay_paypal_unavailable'))||'PayPal non disponibile');return}
  try{await _loadPaypalSdk(llmConfig.paypalClientId)}catch(e){_payPaypalErr((typeof t==='function'&&t('pay_paypal_load_failed'))||'Caricamento PayPal fallito');return}
  if(typeof paypal==='undefined'||!window.paypal||!window.paypal.Buttons){_payPaypalErr((typeof t==='function'&&t('pay_paypal_unavailable'))||'PayPal non disponibile');return}
  if(_paypalGeminiButtonsInstance){try{_paypalGeminiButtonsInstance.close()}catch(e){}_paypalGeminiButtonsInstance=null}
  _paypalGeminiButtonsInstance=window.paypal.Buttons({
    style:{layout:'vertical',color:'gold',shape:'rect',label:'pay'},
    createOrder:async function(){
      // Anti doppio-addebito: se un capture è gia' andato a buon fine in questa
      // sessione, NON creare un secondo ordine. L'utente deve premere Conferma.
      if(_geminiPayCaptured){
        _payPaypalErr((typeof t==='function'&&t('pay_paypal_captured'))||'Pagamento completato — clicca Conferma');
        throw new Error('payment already captured');
      }
      // Endpoint e body dal contesto del flusso corrente (_payCtx). Il server
      // ricalcola l'importo: il body è autoritativo solo per i parametri, non
      // per l'importo da addebitare.
      const _ep=(_payCtx&&_payCtx.paypal&&_payCtx.paypal.endpoint)||'/api/paypal_create_order_gemini';
      const _body=(_payCtx&&_payCtx.paypal&&typeof _payCtx.paypal.buildBody==='function')?_payCtx.paypal.buildBody():{job_id:jobId};
      const r=await fetch(_ep,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(_body)});
      const d=await r.json();if(!r.ok)throw new Error(d.error||'create failed');return d.order_id;
    },
    onApprove:async function(data){
      try{
        const r=await fetch('/api/paypal_capture_order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order_id:data.orderID,job_id:jobId})});
        const d=await r.json();
        if(d.error||!d.payment_token){_payPaypalErr(d.error||((typeof t==='function'&&t('pay_paypal_capture_failed'))||'Cattura pagamento fallita'));return}
        _geminiPayCaptured=true;  // capture ok: blocca ulteriori creazioni ordine
        _payState.token=d.payment_token;_payState.method='paypal';
        const btn=document.getElementById('btnPayConfirm');if(btn)btn.disabled=false;
        const errEl=document.getElementById('payPaypalError');if(errEl){errEl.style.color='#27ae60';errEl.textContent=(typeof t==='function'&&t('pay_paypal_captured'))||'Pagamento completato — clicca Conferma'}
      }catch(e){_payPaypalErr(((typeof t==='function'&&t('pay_paypal_error'))||'Errore PayPal: ')+(e.message||''))}
    },
    onError:function(err){_payPaypalErr(((typeof t==='function'&&t('pay_paypal_error'))||'Errore PayPal: ')+(err&&err.message?err.message:''))},
    onCancel:function(){}
  });
  try{_paypalGeminiButtonsInstance.render('#paypalGeminiContainer')}catch(e){_payPaypalErr(((typeof t==='function'&&t('pay_paypal_error'))||'Errore PayPal: ')+(e.message||''))}
}

function switchPayTab(tab) {
  document.querySelectorAll('.pay-tab').forEach(el => {
    el.classList.toggle('active', el.dataset.paytab === tab);
  });
  const pv = document.getElementById('payPanelVoucher');
  if (pv) pv.hidden = (tab !== 'voucher');
  const pp = document.getElementById('payPanelPaypal');
  if (pp) pp.hidden = (tab !== 'paypal');
  if (tab === 'paypal' && typeof renderPaypalGeminiButtons === 'function') {
    renderPaypalGeminiButtons();
  }
}

async function validateVoucherForPayment() {
  const code = (document.getElementById('geminiPayVoucherCode')?.value || '').trim();
  const email = (document.getElementById('geminiPayVoucherEmail')?.value || '').trim();
  const errEl = document.getElementById('payVoucherError');
  if (!errEl) return;
  errEl.style.color = '';
  errEl.textContent = '';
  if (!code || !email) {
    errEl.textContent = (typeof t === 'function' && t('pay_err_empty')) || 'Inserisci codice e email';
    return;
  }
  try {
    const r = await fetch('/api/voucher_validate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ code, email, purpose: (_payCtx && _payCtx.voucherPurpose) || 'gemini', amount_eur: _payState.total }),
    });
    const d = await r.json();
    if (!d.valid) {
      const map = {
        not_found: (typeof t === 'function' && t('pay_err_voucher_not_found')) || 'Buono non trovato',
        email_mismatch: (typeof t === 'function' && t('pay_err_email_mismatch')) || 'Email non corrispondente',
        revoked: (typeof t === 'function' && t('pay_err_revoked')) || 'Buono revocato',
        insufficient: (typeof t === 'function' && t('pay_err_insufficient')) || 'Saldo insufficiente',
        expired: (typeof t === 'function' && t('pay_err_expired')) || 'Buono scaduto',
        used: (typeof t === 'function' && t('pay_err_used')) || 'Buono già utilizzato',
      };
      errEl.textContent = map[d.reason] || ((typeof t === 'function' && t('pay_err_unknown')) || 'Errore validazione');
      return;
    }
    _payState.token = code;
    _payState.method = 'voucher';
    // Memorizza l'email del voucher per precompilare (senza registrarla) il box
    // di notifica durante la generazione: l'utente la conferma esplicitamente.
    lastVoucherEmail = email;
    try { localStorage.setItem('abm_v_email', email); } catch (e) {}
    const btn = document.getElementById('btnPayConfirm');
    if (btn) btn.disabled = false;
    errEl.style.color = '#27ae60';
    const rem = (typeof d.remaining_eur === 'number') ? d.remaining_eur.toFixed(2) : '0.00';
    errEl.textContent = ((typeof t === 'function' && t('pay_ok_remaining')) || 'Saldo disponibile') + ` €${rem}`;
  } catch (e) {
    errEl.textContent = (typeof t === 'function' && t('pay_err_network')) || 'Errore di rete';
  }
}

function onPayConfirm() {
  if (!_payState.token) return;
  const _cb = _payCtx && _payCtx.onConfirm;
  const _tok = _payState.token;
  _payConfirmed = true;  // la close che segue NON deve scattare come annullo
  closePaymentModal();
  if (typeof _cb === 'function') _cb(_tok);
}

// ═══════════════════ PREVIEW AUDIO ═══════════════════
let _prevLoading=false, _previewGenerated=false;
// Firma dell'anteprima attualmente caricata nel player (voce|rate|stile)
// e set delle firme già generate in questa sessione (cache-hit lato server garantito).
let _currentPreviewSig=null;
const _knownPreviewSigs=new Set();

function _isGeminiVoiceId(v){return typeof v==='string' && v.startsWith('gemini:');}
function _isSpeechifyVoiceId(v){return typeof v==='string' && v.startsWith('speechify:');}

// Catalogo accenti per lingua (mirror di gemini_tts.ACCENT_VARIANTS lato backend).
// Ogni voce: [code, i18nKey]. Il primo e' il default. Solo le lingue qui elencate
// hanno un dropdown; le altre vengono comunque ancorate lato server al loro
// accento di default. Mantenere allineato col backend.
const _ACCENT_CATALOG={
  en:[['us','accent_en_us'],['gb','accent_en_gb'],['au','accent_en_au'],['in','accent_en_in']],
  es:[['es','accent_es_es'],['419','accent_es_419']],
  pt:[['br','accent_pt_br'],['pt','accent_pt_pt']],
  fr:[['fr','accent_fr_fr'],['ca','accent_fr_ca']],
  zh:[['cn','accent_zh_cn'],['tw','accent_zh_tw']],
  de:[['de','accent_de_de'],['at','accent_de_at'],['ch','accent_de_ch']],
  ar:[['eg','accent_ar_eg'],['sa','accent_ar_sa'],['ae','accent_ar_ae']]
};

// Lingua TTS premium corrente (combo vlPremium), normalizzata a 2 lettere.
function _premiumLang(){
  try{
    const el=document.getElementById('vlPremium');
    return (el&&el.value?el.value:'').split('-')[0].toLowerCase();
  }catch(_){return '';}
}

// Valore accento selezionato (solo se il dropdown e' visibile). '' = default lato server.
function _getAccentVariant(){
  const row=document.getElementById('geminiAccentRow');
  if(!row||row.hidden)return '';
  const sel=document.getElementById('geminiAccent');
  return (sel&&sel.value?sel.value:'').trim();
}

// Popola e mostra/nasconde il dropdown accento. Visibile solo per voci Gemini
// premium su lingue con >1 variante. Preserva la scelta utente se ancora valida.
function _updateAccentDropdown(){
  const row=document.getElementById('geminiAccentRow');
  const sel=document.getElementById('geminiAccent');
  if(!row||!sel)return;
  const isGem=_isGeminiVoiceId((typeof getCurrentVoiceId==='function')?getCurrentVoiceId():'');
  const opts=isGem?_ACCENT_CATALOG[_premiumLang()]:null;
  if(!opts||opts.length<2){
    // Lingua senza varianti d'accento (es. Italiano): nascondi E svuota il
    // select, così non resta l'accento della lingua precedente nel DOM e
    // _getAccentVariant non puo' restituire un valore stantio.
    row.hidden=true;
    sel.innerHTML='';
    sel.value='';
    return;
  }
  const prev=sel.value;
  sel.innerHTML='';
  for(const pair of opts){
    const o=document.createElement('option');
    o.value=pair[0];
    o.textContent=t(pair[1]);
    sel.appendChild(o);
  }
  if(prev&&opts.some(p=>p[0]===prev))sel.value=prev;
  row.hidden=false;
  sel.onchange=()=>{_onPreviewParamsChanged();};
}

function _getSelectedChaptersKey(){
  try{
    const sel=(typeof _getSelectedChapterIndexes==='function')?_getSelectedChapterIndexes():[];
    return sel.slice().sort((a,b)=>a-b).join(',');
  }catch(_){return '';}
}

function _getPreviewSig(){
  const voice=(typeof getCurrentVoiceId==='function')?getCurrentVoiceId():'';
  const rate=document.getElementById('vr')?.value||'+0%';
  const style=_isGeminiVoiceId(voice)
    ? ((document.getElementById('geminiStyle')?.value||'').trim().slice(0,200))
    : '';
  const accent=_isGeminiVoiceId(voice)?_getAccentVariant():'';
  const emo=_isSpeechifyVoiceId(voice)?(document.getElementById('speechifyEmotion')?.value||''):'';
  return voice+'|'+rate+'|'+style+'|'+accent+'|'+emo+'|'+_getSelectedChaptersKey();
}

function _buildPreviewUrl(){
  const voice=getCurrentVoiceId();
  const rate=document.getElementById('vr').value;
  const style=_isGeminiVoiceId(voice)
    ? ((document.getElementById('geminiStyle')?.value||'').trim().slice(0,200))
    : '';
  // Lingua TTS scelta dall'utente: il backend la usa per il rate sample
  // empirico (gemini_tts_rate_log) cosi' i campioni vengono raggruppati
  // per lingua REALE della voce, non per metadata libro.
  let _selLang='';
  try{
    const _audioTab=(typeof wizardState!=='undefined'&&wizardState&&wizardState.audioTab)?wizardState.audioTab:'';
    const _el=(_audioTab==='premium')
      ?document.getElementById('vlPremium')
      :document.getElementById('vl');
    _selLang=(_el&&_el.value)?_el.value:'';
  }catch(_){ _selLang=''; }
  let u='/api/preview_audio/'+bookData.job_id
    +'?voice='+encodeURIComponent(voice)
    +'&rate='+encodeURIComponent(rate);
  if(style)u+='&style='+encodeURIComponent(style);
  if(_selLang)u+='&lang='+encodeURIComponent(_selLang);
  const accent=_isGeminiVoiceId(voice)?_getAccentVariant():'';
  if(accent)u+='&accent='+encodeURIComponent(accent);
  if(_isSpeechifyVoiceId(voice)){
    const _emo=(document.getElementById('speechifyEmotion')?.value||'');
    if(_emo)u+='&speechify_emotion='+encodeURIComponent(_emo);
  }
  const _pf=getParenFlags();
  if(_pf.read_round_parens)u+='&read_round_parens=1';
  if(_pf.read_square_brackets)u+='&read_square_brackets=1';
  const sel=(typeof _getSelectedChapterIndexes==='function')?_getSelectedChapterIndexes():[];
  sel.forEach(i=>{u+='&selected_chapters='+encodeURIComponent(i);});
  return u;
}

function _updatePreviewBtn(){
  const btn=document.getElementById('btnPrev');
  if(!btn)return;
  const ok=!!(bookData&&bookData.preview_text&&!generating&&!jobDone);
  btn.disabled=!ok;
  btn.classList.remove('loading');
  const txt=document.getElementById('prevTxt');
  if(txt)txt.textContent=t(_previewGenerated?'btn_regen_preview':'btn_gen_preview');
}

// Chiamato quando un parametro che influisce sull'anteprima cambia
// (voce, modello, velocità, stile). Decide se:
//  - non fare nulla (firma invariata)
//  - mostrare direttamente il player con audio cached (firma già generata)
//  - nascondere il player e riabilitare il bottone Rigenera (firma nuova)
function _onPreviewParamsChanged(){
  if(!bookData||!bookData.preview_text)return;
  const newSig=_getPreviewSig();
  if(newSig===_currentPreviewSig)return;
  const audio=document.getElementById('previewAudioWiz');
  const wrap=document.getElementById('previewAudioWrap');
  const btn=document.getElementById('btnPrev');
  if(_knownPreviewSigs.has(newSig)){
    // Anteprima già in cache lato server: carica direttamente nel player.
    if(audio){audio.src=_buildPreviewUrl();audio.load();}
    if(wrap)wrap.classList.add('visible');
    _currentPreviewSig=newSig;
    _previewGenerated=true;
    _updatePreviewBtn();
    if(btn)btn.disabled=true;
  } else {
    // Nuova combinazione: nascondi player, abilita "Rigenera anteprima".
    if(audio){audio.pause();audio.removeAttribute('src');audio.load();}
    if(wrap)wrap.classList.remove('visible');
    _currentPreviewSig=null;
    _updatePreviewBtn();
    if(btn)btn.disabled=!(bookData&&bookData.preview_text&&!generating&&!jobDone);
  }
}

function _resetPreviewState(){
  _previewGenerated=false;
  _currentPreviewSig=null;
  const wrap=document.getElementById('previewAudioWrap');
  if(wrap)wrap.classList.remove('visible');
  const audio=document.getElementById('previewAudioWiz');
  if(audio){audio.pause();audio.removeAttribute('src');audio.load();}
  _updatePreviewBtn();
  // Re-enable button
  const btn=document.getElementById('btnPrev');
  if(btn)btn.disabled=false;
  _prevLoading=false;
}

function previewStop(){
  _prevLoading=false;
  _previewGenerated=false;
  const audio=document.getElementById('previewAudioWiz');
  if(audio){audio.pause();audio.removeAttribute('src');audio.load();}
  const wrap=document.getElementById('previewAudioWrap');
  if(wrap)wrap.classList.remove('visible');
  _updatePreviewBtn();
}

async function previewRead(){
  if(_prevLoading)return;
  if(!bookData||!bookData.preview_text)return;

  _prevLoading=true;
  const btn=document.getElementById('btnPrev');
  const prevTxt=document.getElementById('prevTxt');
  const _origTxt=prevTxt?prevTxt.textContent:'';
  btn.disabled=true;
  btn.classList.add('loading');
  if(prevTxt)prevTxt.textContent=t('prev_loading')||'Generazione anteprima in corso…';
  const _restoreBtn=()=>{btn.classList.remove('loading');if(prevTxt)prevTxt.textContent=_origTxt;};

  // Hide previous player if any
  const wrap=document.getElementById('previewAudioWrap');
  if(wrap)wrap.classList.remove('visible');

  const voice=getCurrentVoiceId();
  const audio=document.getElementById('previewAudioWiz');
  const _sigAtRequest=_getPreviewSig();
  const url=_buildPreviewUrl();

  // Voci Gemini: prefetch via fetch() per intercettare 429 (cap superato) e 503 (non configurato).
  if(_isGeminiVoice(voice)){
    // Client-side timeout via AbortController, model-aware.
    // Catena server: HTTP Google -> wrapper ThreadPoolExecutor -> handler.
    //   flash25:  HTTP 25s -> wrapper 30s -> client 35s (5s buffer).
    //   flash31:  HTTP 60s -> wrapper 65s -> client 70s (5s buffer).
    // flash31 e` strutturalmente piu` lento (RPM cap 3/300 vs 10/750 +
    // audio gen piu` lenta lato Google); senza buffer il client abortiva
    // mentre il server stava completando con successo, generando il falso
    // positivo "Il servizio TTS impiega troppo tempo".
    const _ctrl=new AbortController();
    const _toMs = voice.indexOf(':flash31:') !== -1 ? 70000 : 35000;
    const _toHandle=setTimeout(()=>{try{_ctrl.abort();}catch(_){}},_toMs);
    try{
      const r=await fetch(url,{signal:_ctrl.signal});
      clearTimeout(_toHandle);
      if(r.status===429){
        const data=await r.json().catch(()=>({}));
        const minutes=Math.ceil((data.reset_in_seconds||0)/60);
        const msg=t('gemini_preview_cap_exceeded')
          .replace('{n}',data.used||0).replace('{cap}',data.cap||5).replace('{min}',minutes);
        alert(msg);
        _prevLoading=false;btn.disabled=false;_restoreBtn();
        return;
      }
      if(r.status===503){
        // 503 ha 3 sotto-casi distinti:
        // - code=quota_exhausted: RPD server-wide per il modello -> suggerisci altro modello
        // - code=budget_exceeded: budget EUR daily -> suggerisci voci Standard
        // - default (no code): servizio non configurato (env mancanti)
        const data=await r.json().catch(()=>({}));
        const c=data && data.code;
        if(c==='quota_exhausted'){
          alert((data && data.error)||t('gemini_quota_exhausted')||'Il modello voci PREMIUM ha raggiunto il limite giornaliero. Riprova piu` tardi o seleziona un modello differente.');
        }else if(c==='budget_exceeded'){
          alert((data && data.error)||t('gemini_budget_exceeded')||'Le voci PREMIUM hanno raggiunto il budget giornaliero. Riprova piu` tardi o seleziona una voce Standard.');
        }else{
          alert(t('gemini_not_configured'));
        }
        _prevLoading=false;btn.disabled=false;_restoreBtn();
        return;
      }
      // 502 con code=empty_response: il modello ha risposto ma senza audio
      // (finish_reason=OTHER tipicamente, instabilita` model-specific
      // su combo voce/rate/lingua). Suggeriamo retry o cambio voce/modello
      // perche` lo stesso payload sullo stesso modello tende a restituire
      // lo stesso esito (non e` transient di rete).
      if(r.status===502){
        const data=await r.json().catch(()=>({}));
        if(data && data.code==='empty_response'){
          const reason=data.finish_reason||'unknown';
          const tmpl=t('gemini_empty_response')||'Il modello TTS non ha prodotto audio (motivo: {reason}). Riprova o seleziona una voce o un modello differente.';
          alert(tmpl.replace('{reason}',reason));
        }else{
          alert((data && data.error) || t('prev_error'));
        }
        _prevLoading=false;btn.disabled=false;_restoreBtn();
        return;
      }
      // 504: timeout server-side (il servizio TTS non ha risposto entro 30s).
      // Tipicamente indica overload temporaneo del modello: invito a retry.
      if(r.status===504){
        alert(t('gemini_timeout')||'Il servizio TTS impiega troppo tempo a rispondere. Riprova tra qualche secondo o seleziona una voce differente.');
        _prevLoading=false;btn.disabled=false;_restoreBtn();
        return;
      }
      if(!r.ok){
        // Tentativo di parse JSON per estrarre error message strutturato.
        const data=await r.json().catch(()=>({}));
        _prevLoading=false;btn.disabled=false;_restoreBtn();
        alert((data && data.error) || t('prev_error'));
        return;
      }
      const blob=await r.blob();
      const blobUrl=URL.createObjectURL(blob);
      audio.oncanplay=()=>{
        _prevLoading=false;
        _restoreBtn();
        btn.disabled=true;
        _previewGenerated=true;
        _currentPreviewSig=_sigAtRequest;
        _knownPreviewSigs.add(_sigAtRequest);
        _updatePreviewBtn();
        if(wrap)wrap.classList.add('visible');
        previewListened=true;
        audio.oncanplay=null;
        URL.revokeObjectURL(blobUrl);
      };
      audio.onerror=()=>{
        if(audio.error&&audio.error.code===audio.MEDIA_ERR_ABORTED)return;
        URL.revokeObjectURL(blobUrl);
        _prevLoading=false;
        _restoreBtn();
        btn.disabled=false;
        if(wrap)wrap.classList.remove('visible');
        alert(t('prev_error'));
      };
      audio.src=blobUrl;
      audio.load();
      return;
    }catch(err){
      clearTimeout(_toHandle);
      console.error('[gemini-preview] fetch error:',err);
      _prevLoading=false;btn.disabled=false;_restoreBtn();
      // AbortError = timeout client-side (25s). Mostriamo il messaggio
      // timeout invece di generico prev_error: l'utente capisce che il
      // problema e` lentezza del servizio, non un suo errore.
      if(err && err.name==='AbortError'){
        alert(t('gemini_timeout')||'Il servizio TTS impiega troppo tempo a rispondere. Riprova tra qualche secondo o seleziona una voce differente.');
      }else{
        alert(t('prev_error'));
      }
      return;
    }
  }

  audio.oncanplay=()=>{
    _prevLoading=false;
    _restoreBtn();
    btn.disabled=true;
    _previewGenerated=true;
    _currentPreviewSig=_sigAtRequest;
    _knownPreviewSigs.add(_sigAtRequest);
    _updatePreviewBtn();
    if(wrap)wrap.classList.add('visible');
    previewListened=true;
    audio.oncanplay=null;
  };
  audio.onerror=()=>{
    if(audio.error&&audio.error.code===audio.MEDIA_ERR_ABORTED)return;
    _prevLoading=false;
    _restoreBtn();
    btn.disabled=false;
    if(wrap)wrap.classList.remove('visible');
    alert(t('prev_error'));
  };

  audio.src=url;
  audio.load();
}

// ═══════════════════ PREVIEW (Book info - Step 3) ═══════════════════
function fillPreview(d){
  // Panel 2: book info bar
  document.getElementById('bkT').textContent=d.title;
  document.getElementById('bkA').textContent=d.author?(t('by')+' '+d.author):'';
  const coverImg=document.getElementById('bkCover');
  const coverPlaceholder=document.getElementById('coverPlaceholder');
  console.log('[cover] has_cover='+d.has_cover+', job_id='+d.job_id);
  if(d.has_cover&&d.job_id){
    coverImg.src='/api/cover/'+d.job_id;
    coverImg.style.display='';
    if(coverPlaceholder)coverPlaceholder.style.display='none';
    coverImg.onload=function(){console.log('[cover] loaded OK: '+this.naturalWidth+'x'+this.naturalHeight)};
    coverImg.onerror=function(){console.log('[cover] load FAILED');this.style.display='none';if(coverPlaceholder)coverPlaceholder.style.display=''};
  }else{coverImg.style.display='none';coverImg.src='';if(coverPlaceholder)coverPlaceholder.style.display=''}
  // Stats in book info bar
  const chCount=document.getElementById('bookChCount');
  if(chCount)chCount.textContent=d.total_chapters+' '+(d.total_chapters===1?(t('sum_c')||'chapter'):(t('sum_cs')||'chapters'));
  const totalChars=document.getElementById('bookTotalChars');
  if(totalChars)totalChars.textContent=(d.total_words||0).toLocaleString()+' '+(t('sum_w')||'words');
  const bookLangEl=document.getElementById('bookLang');
  if(bookLangEl&&d.language)bookLangEl.textContent=d.language.toUpperCase();
  else if(bookLangEl)bookLangEl.textContent='';

  const smC=document.getElementById('smC');if(smC)smC.textContent=d.total_chapters;
  const smW=document.getElementById('smW');if(smW)smW.textContent=(d.total_words||0).toLocaleString();
  const smD=document.getElementById('smD');if(smD)smD.textContent=fmtDur(d.estimated_minutes);
  const selTot=document.getElementById('selTot');if(selTot)selTot.textContent=d.total_chapters;

  // Build chapter rows as divs + populate old #chl table for backward compat
  const rows=document.getElementById('chapterRows');
  const chl=document.getElementById('chl');
  if(rows)rows.innerHTML='';
  if(chl)chl.innerHTML='';
  for(const ch of d.chapters){
    // New wizard chapter rows
    if(rows){
      const row=document.createElement('div');
      row.className='chapter-row';
      row.dataset.idx=ch.index;
      row.dataset.words=ch.words;
      row.dataset.mins=ch.estimated_minutes;
      const cb=document.createElement('input');
      cb.type='checkbox';cb.checked=true;cb.dataset.idx=ch.index;
      cb.addEventListener('change',()=>{row.classList.toggle('unchecked',!cb.checked);updateSelection()});
      const num=document.createElement('span');
      num.className='ch-num';num.textContent=ch.index+'.';
      const title=document.createElement('span');
      title.className='ch-title';title.textContent=ch.title.substring(0,60);
      const chars=document.createElement('span');
      chars.className='ch-chars';chars.textContent=fmtDur(ch.estimated_minutes);
      row.appendChild(cb);row.appendChild(num);row.appendChild(title);row.appendChild(chars);
      row.addEventListener('click',e=>{if(e.target.tagName==='INPUT')return;cb.checked=!cb.checked;row.classList.toggle('unchecked',!cb.checked);updateSelection()});
      rows.appendChild(row);
    }
    // Old #chl table (backward compat for selection queries)
    if(chl){
      const tr=document.createElement('tr');
      tr.dataset.idx=ch.index;
      tr.dataset.words=ch.words;
      tr.dataset.mins=ch.estimated_minutes;
      const selTd=document.createElement('td');
      selTd.className='col-sel';
      const tcb=document.createElement('input');
      tcb.type='checkbox';tcb.checked=true;tcb.dataset.idx=ch.index;
      tcb.addEventListener('change',()=>{tr.classList.toggle('unchecked',!tcb.checked);updateSelection()});
      selTd.appendChild(tcb);
      tr.innerHTML='<td><span class="cn">'+ch.index+'.</span>'+esc(ch.title.substring(0,60))+'</td><td>'+ch.words.toLocaleString()+'</td><td>'+fmtDur(ch.estimated_minutes)+'</td>';
      tr.insertBefore(selTd,tr.firstChild);
      tr.addEventListener('click',e=>{if(e.target.tagName==='INPUT')return;tcb.checked=!tcb.checked;tr.classList.toggle('unchecked',!tcb.checked);updateSelection()});
      chl.appendChild(tr);
    }
  }
  // Master checkbox
  const chAll=document.getElementById('chAll');
  if(chAll)chAll.checked=true;
  updateSelection();
  _updateVoiceChip();checkVoiceMismatch();
}

function updateSelection(){
  // Clear any stale "selection too large" error: the user is changing the selection
  // in response to it, so the previous message is no longer relevant.
  const s3errEl=document.getElementById('s3err');if(s3errEl)s3errEl.innerHTML='';
  let boxes=document.querySelectorAll('#chl .col-sel input[type=checkbox]');
  if(!boxes.length)boxes=document.querySelectorAll('#chapterRows .chapter-row input[type=checkbox]');
  let cnt=0,words=0,mins=0;
  boxes.forEach(cb=>{
    if(cb.checked){cnt++;const row=cb.closest('tr')||cb.closest('.chapter-row');words+=parseInt(row.dataset.words||0);mins+=parseFloat(row.dataset.mins||0)}
  });
  // Update wizard counter
  const selCnt=document.getElementById('selCnt');if(selCnt)selCnt.textContent=cnt;
  const selectedCount=document.getElementById('selectedCount');
  if(selectedCount)selectedCount.innerHTML='<b>'+cnt+'</b> <span data-t="sel_selected">'+t('sel_selected')+'</span>';

  // Selection bar
  const selBar=document.getElementById('selBar');if(selBar)selBar.classList.add('vis');
  document.querySelectorAll('#chl .col-sel').forEach(td=>td.style.display='');
  document.querySelectorAll('#chl tr').forEach(tr=>tr.style.cursor='pointer');

  // Update summary to reflect selection
  const smC=document.getElementById('smC');if(smC)smC.textContent=cnt+' / '+(bookData?bookData.total_chapters:boxes.length);
  const smW=document.getElementById('smW');if(smW)smW.textContent=words.toLocaleString();
  const smD=document.getElementById('smD');if(smD)smD.textContent=fmtDur(mins);

  // Sync wizard chapter rows with their checkboxes
  document.querySelectorAll('#chapterRows .chapter-row').forEach(row=>{
    const wizardCb=row.querySelector('input[type=checkbox]');
    if(wizardCb)row.classList.toggle('unchecked',!wizardCb.checked);
  });

  // Master checkbox state
  const all=boxes.length;
  const master=document.getElementById('chAll');
  if(master){master.checked=cnt===all;master.indeterminate=cnt>0&&cnt<all}
  // Disable generate buttons if none selected
  const btnGenerate=document.getElementById('btnGenerate');
  if(btnGenerate)btnGenerate.disabled=(cnt===0);
  const btnGoToGenerate=document.getElementById('btnGoToGenerate');
  if(btnGoToGenerate)btnGoToGenerate.disabled=(cnt===0);
  const btnGoToAudio=document.getElementById('btnGoToAudio');
  if(btnGoToAudio)btnGoToAudio.disabled=(cnt===0);
  // Reset AI optimization on chapter selection change — cost estimate must be recomputed
  if(aiOptEnabled){
    const aiToggle=document.getElementById('aiToggle');
    if(aiToggle)aiToggle.checked=false;
    toggleAIOptimization();
  }
  _updateAiOptUI();
  if(typeof requestCombinedEstimate==='function')requestCombinedEstimate();
  // L'anteprima è estratta dai capitoli selezionati: invalida la cache lato client.
  if(typeof _onPreviewParamsChanged==='function')_onPreviewParamsChanged();
}

function _getAllCheckboxes(){let cbs=document.querySelectorAll('#chl .col-sel input[type=checkbox]');if(!cbs.length)cbs=document.querySelectorAll('#chapterRows .chapter-row input[type=checkbox]');return cbs}
function _getSelectedChapterIndexes(){const idxs=[];_getAllCheckboxes().forEach(cb=>{if(cb.checked)idxs.push(parseInt(cb.dataset.idx))});return idxs}
function _allSelectedOptimized(){const sel=_getSelectedChapterIndexes();if(!sel.length)return false;return sel.every(idx=>optimizedChapters.includes(idx))}
function chSelAll(){_getAllCheckboxes().forEach(cb=>{cb.checked=true;const row=cb.closest('tr')||cb.closest('.chapter-row');if(row)row.classList.remove('unchecked')});updateSelection()}
function chSelNone(){_getAllCheckboxes().forEach(cb=>{cb.checked=false;const row=cb.closest('tr')||cb.closest('.chapter-row');if(row)row.classList.add('unchecked')});updateSelection()}
function chSelInvert(){_getAllCheckboxes().forEach(cb=>{cb.checked=!cb.checked;const row=cb.closest('tr')||cb.closest('.chapter-row');if(row)row.classList.toggle('unchecked',!cb.checked)});updateSelection()}
function chMasterToggle(){const v=document.getElementById('chAll').checked;_getAllCheckboxes().forEach(cb=>{cb.checked=v;const row=cb.closest('tr')||cb.closest('.chapter-row');if(row)row.classList.toggle('unchecked',!v)});updateSelection()}

// ═══════════════════ TRANSLATE WIZARD ═══════════════════
function _rememberLastLang(code){
  // Memorizza l'ultima lingua usata (avvio generazione audio o traduzione)
  // per la preselezione del target traduzione (spec 2026-06-07).
  const c=String(code||'').toLowerCase().split('-')[0];
  if(!/^[a-z]{2,3}$/.test(c))return;
  try{localStorage.setItem('abm_last_lang',c)}catch(e){}
}
function goToTranslate(){
  if(!jobId||generating)return;
  if(!_translateAvailable){showErr('p2info',t('tr_unavailable')||'Translation not available on this server');return}
  if(_getSelectedChapterIndexes().length===0){showErr('p2info',t('sel_err_none')||'Select at least one chapter');return}
  wizMode='translate';
  trPaymentToken=null;
  _trFillLangSelects();
  _trPrefillOutName();
  _trFetchTranslatedName();
  goToStep(3);
  trUpdateEstimate();
}

function _trFillLangSelects(){
  const langs=Object.keys(voices).filter(c=>!c.startsWith('_')).map(c=>{
    let ln=c;
    if(L[cl]&&L[cl].langs&&L[cl].langs[c])ln=L[cl].langs[c];
    else if(L.en&&L.en.langs&&L.en.langs[c])ln=L.en.langs[c];
    else ln=(voices[c]&&voices[c].name)||c;
    return {code:c,name:ln};
  }).sort((a,b)=>a.name.localeCompare(b.name,cl));
  ['trSrcLang','trDstLang'].forEach(id=>{
    const sel=document.getElementById(id);if(!sel)return;
    const old=sel.value;
    sel.innerHTML='';
    for(const l of langs){
      const o=document.createElement('option');
      o.value=l.code;o.textContent=l.name;
      sel.appendChild(o);
    }
    if(old&&voices[old]){sel.value=old;sel._trRestored=true;}else{sel._trRestored=false;}
    if(!sel._trBound){sel._trBound=true;sel.addEventListener('change',()=>{trUpdateEstimate();if(sel.id==='trDstLang')_trFetchTranslatedName();});}
  });
  // Origine precompilata dalla lingua del libro se nota
  const src=document.getElementById('trSrcLang');
  if(src&&bookData&&bookData.language){
    const lc=bookData.language.split('-')[0].toLowerCase();
    if(src.querySelector('option[value="'+lc+'"]'))src.value=lc;
  }
  // Preselezione destinazione: ultima lingua usata (abm_last_lang) o lingua
  // UI, solo alla prima apertura (nessun valore di sessione ripristinato) e
  // mai uguale all'origine (spec 2026-06-07-last-lang-target-preselect).
  const dstSel=document.getElementById('trDstLang');
  if(dstSel&&!dstSel._trRestored){
    let srcLang=(src&&src.value)||'';
    if(!srcLang&&bookData&&bookData.language)srcLang=bookData.language.split('-')[0].toLowerCase();
    let saved='';
    try{saved=(localStorage.getItem('abm_last_lang')||'').toLowerCase()}catch(e){}
    for(const cand of [saved,cl]){
      if(cand&&cand!==srcLang&&dstSel.querySelector('option[value="'+cand+'"]')){dstSel.value=cand;break}
    }
  }
}

function _trPrefillOutName(){
  const el=document.getElementById('trOutName');if(!el)return;
  let base=(bookData&&(bookData.original_filename||bookData.filename))||'';
  if(!base)base=(bookData&&bookData.title)||'translated';
  base=base.replace(/\.[^.]+$/,'');
  el.value=base;
  trAutoOutName=base;
}
let _trTitleReqSeq=0;
function _trNameLoading(on){
  // Mostra/nasconde lo spinner di attesa sul campo nome file tradotto.
  const w=document.getElementById('trOutNameWrap');
  if(w)w.classList.toggle('loading',!!on);
}
async function _trFetchTranslatedName(){
  // Titolo tradotto come nome file. Spinner durante la traduzione; fallimento
  // silenzioso. Guardie sotto: trAutoOutName (no edit manuali), requestedTarget
  // + _trTitleReqSeq (no risposte stantie / non piu' recenti).
  const el=document.getElementById('trOutName');if(!el||!jobId)return;
  const dst=document.getElementById('trDstLang');
  const src=document.getElementById('trSrcLang');
  if(!dst||!dst.value)return;
  if(el.value!==trAutoOutName)return; // utente ha editato: non interferire
  const requestedTarget=dst.value;
  const myReq=++_trTitleReqSeq;
  _trNameLoading(true);
  // Timeout 30s: la prima richiesta (non in cache) traduce via LLM lato server
  // e puo' durare alcuni secondi; con un timeout troppo basso il client abortiva
  // mentre il server completava+cacheava, e il titolo compariva solo al ritorno.
  const ctrl=new AbortController();
  const tmr=setTimeout(()=>ctrl.abort(),30000);
  try{
    const url=new URL('/api/translate_title/'+jobId,window.location.origin);
    url.searchParams.append('target',requestedTarget);
    if(src&&src.value)url.searchParams.append('source',src.value);
    const d=await fetch(url.toString(),{signal:ctrl.signal}).then(r=>r.json());
    const cur=document.getElementById('trDstLang');
    if(d&&d.title&&el.value===trAutoOutName&&cur&&cur.value===requestedTarget){
      el.value=d.title;
      trAutoOutName=d.title;
    }
  }catch(e){/* silenzioso: resta il prefill */}
  finally{
    clearTimeout(tmr);
    // Solo la richiesta piu' recente controlla lo spinner: una richiesta piu'
    // nuova (cambio lingua) gestisce il proprio stato.
    if(myReq===_trTitleReqSeq)_trNameLoading(false);
  }
}
async function trUpdateEstimate(){
  if(!jobId)return null;
  try{
    const url=new URL('/api/translate_estimate/'+jobId,window.location.origin);
    url.searchParams.append('target',document.getElementById('trDstLang').value||'');
    url.searchParams.append('optimize',document.getElementById('aiToggleTr').checked?'1':'0');
    _getSelectedChapterIndexes().forEach(i=>url.searchParams.append('selected_chapters',i));
    const est=await fetch(url.toString()).then(r=>r.json());
    if(est.error)return null;
    trEstimate=est;
    const amt=document.getElementById('costAmountTr');
    const det=document.getElementById('costDetailTr');
    if(amt)amt.textContent=est.requires_payment?('€ '+est.due_eur.toFixed(2)):(t('cost_free')||'€ 0.00');
    if(det)det.textContent=(t('tr_cost_detail')||'{0} characters').replace('{0}',(est.chars||0).toLocaleString());
    const sb=document.getElementById('btnStartTranslate');
    if(sb)sb.disabled=(est.available===false);
    if(est.available===false)showErr('trErr',t('tr_unavailable')||'Translation not available on this server');
    return est;
  }catch(e){return null}
}

async function startTranslation(){
  if(!jobId||generating||window._trStarting)return;
  window._trStarting=true;
  try{
    const src=document.getElementById('trSrcLang').value;
    const dst=document.getElementById('trDstLang').value;
    if(src===dst){showErr('trErr',t('tr_err_same_lang'));return}
    _rememberLastLang(dst);
    const est=await trUpdateEstimate();
    if(!est)return;
    if(est.requires_payment&&!trPaymentToken){
      // Pagamento unico (traduzione + eventuale ottimizzazione) col popup
      // premium parametrico: voucher + PayPal. Caricare prima la config PayPal.
      await _loadLlmPaymentConfig();
      _openPayModalCtx({
        lines:[{labelKey:'tr_pay_label',amount:est.due_eur}],
        total:est.due_eur,
        voucherPurpose:'translate',
        paypal:{
          endpoint:'/api/paypal_create_order_translate',
          buildBody:()=>({job_id:jobId,target_lang:dst,
            optimize:document.getElementById('aiToggleTr').checked,
            selected_chapters:_getSelectedChapterIndexes(),
            amount_eur:est.due_eur}),
        },
        onConfirm:(token)=>{trPaymentToken=token;_submitTranslation(token,src,dst);},
      });
      return; // l'invio prosegue in onConfirm dopo la conferma del popup
    }
    _submitTranslation(trPaymentToken,src,dst);
  }finally{window._trStarting=false}
}

// Invia POST /api/translate e avvia l'ascolto del progress. payToken può essere
// null (traduzione gratis sotto soglia). Guardia anti doppio-avvio su generating.
async function _submitTranslation(payToken,src,dst){
  if(generating)return;
  const payload={
    job_id:jobId,
    source_lang:src,target_lang:dst,
    output_format:document.getElementById('trFormat').value,
    output_name:(document.getElementById('trOutName').value||'').trim(),
    optimize:document.getElementById('aiToggleTr').checked,
    selected_chapters:_getSelectedChapterIndexes(),
    batch:false,lang:cl
  };
  if(payToken)payload.payment_token=payToken;
  try{
    const r=await fetch('/api/translate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    if(d.error){trPaymentToken=null;showErr('trErr',d.error);return}
    document.getElementById('trErr').innerHTML='';
    const _bcR=document.getElementById('btnCancelTr');
    if(_bcR){const _spR=_bcR.querySelector('span');if(_spR)_spR.textContent=t('tr_btn_cancel')||'Cancel';_bcR.onclick=cancelTranslation;}
    generating=true;
    lockUI();
    goToStep(4);
    const area=document.getElementById('emailLateAreaTr');if(area)area.classList.add('visible');
    _trAutofillEmailLate();
    _listenTranslateProgress();
  }catch(e){showErr('trErr','Error: '+e.message)}
}

function _trAutofillEmailLate(){
  if(trEmailRegistered)return;
  let stored='';
  try{stored=(localStorage.getItem('abm_v_email')||'').trim();}catch(e){}
  if(!stored||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(stored))return;
  const input=document.getElementById('notifyEmailLateTr');
  if(input&&!input.value)input.value=stored;
}

function _listenTranslateProgress(){
  const myJobId=jobId;
  const es=new EventSource('/api/translate_progress/'+myJobId);
  es.onmessage=ev=>{
    const d=JSON.parse(ev.data);
    const fill=document.getElementById('trProgressFill');
    const pct=document.getElementById('trProgressPct');
    const phase=document.getElementById('trProgressPhase');
    const total=d.tr_total_chars||1;
    const done=Math.min(d.tr_streamed_chars||d.tr_processed_chars||0,total);
    const p=Math.round(done/total*100);
    if(fill)fill.style.width=p+'%';
    if(pct)pct.textContent=p+'%';
    if(phase)phase.textContent=(t('tr_progress_chapter')||'Chapter {0} of {1}')
      .replace('{0}',d.tr_current_chapter_num||0)
      .replace('{1}',d.tr_progress_total||0);
    if(d.status==='error'){
      es.close();generating=false;unlockUI();
      showErr('trErr4',d.error||'Translation error');
      const bc=document.getElementById('btnCancelTr');
      if(bc){const sp=bc.querySelector('span');if(sp)sp.textContent=t('btn_back')||'Back';bc.onclick=()=>{goToStep(3);};}
      return;
    }
    if(d.status==='cancelled'){
      es.close();generating=false;unlockUI();
      trPaymentToken=null;
      showErr('trErr4',t('tr_cancelled'));goToStep(3);return;
    }
    if(d.status==='translated'){es.close();generating=false;unlockUI();_showTranslationDone(d);return}
  };
  es.onerror=()=>{es.close();setTimeout(()=>{if(generating)_listenTranslateProgress()},3000)};
}

async function cancelTranslation(){
  if(!jobId)return;
  try{await fetch('/api/translate_cancel/'+jobId,{method:'POST'})}catch(e){}
}

async function submitEmailLateTr(){
  const email=(document.getElementById('notifyEmailLateTr').value||'').trim();
  if(!email||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))return;
  lastVoucherEmail=email;try{localStorage.setItem('abm_v_email',email)}catch(e){}
  try{
    const r=await fetch('/api/register_email',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId,email:email,download_type:'translated',lang:cl})});
    const d=await r.json();
    if(d.error){alert(d.error);return}
    trEmailRegistered=true;
    const area=document.getElementById('emailLateAreaTr');
    _setEmailLateConfirm(area,'✅ '+(t('email_late_ok')||'Email registered!'));
  }catch(e){alert('Error: '+e.message)}
}

function _showTranslationDone(d){
  _unlockStep(5);
  jobDone=true;
  ['btnD','btnM','btnA','btnP'].forEach(id=>{const b=document.getElementById(id);if(b)b.style.display='none'});
  const btnD=document.getElementById('btnD');
  if(btnD){
    btnD.style.display='';
    const fmt=(document.getElementById('trFormat').value||'').toUpperCase();
    btnD.innerHTML='&#x2B07;&#xFE0F; <span>'+esc(t('tr_btn_download')||'Download translation')+' ('+esc(fmt)+')</span>';
    btnD.onclick=()=>{window.location='/api/download_translation/'+jobId};
  }
  const btnAdopt=document.getElementById('btnTrAdopt');
  if(btnAdopt){btnAdopt.style.display='';btnAdopt.onclick=adoptTranslation;}
  const h=document.getElementById('panel5Heading');
  if(h)h.textContent=t('tr_done')||'Translation complete!';
  goToStep(5);
}

async function adoptTranslation(){
  if(!jobId)return;
  try{
    const r=await fetch('/api/translate_adopt/'+jobId,{method:'POST'});
    const d=await r.json();
    if(d.error){alert(d.error);return}
    if(bookData){
      bookData.language=d.language;
      bookData.title=d.title||bookData.title;
      bookData.chapters=(d.chapters||[]).map(c=>({
        index:c.index,title:c.title,words:c.words,chars:c.chars,
        estimated_minutes:c.estimated_minutes||0
      }));
      bookData.total_chapters=bookData.chapters.length;
      bookData.total_words=bookData.chapters.reduce((s,c)=>s+(c.words||0),0);
      bookData.estimated_minutes=0;
      bookData.ai_optimized=!!d.ai_optimized;
    }
    optimizedChapters=d.ai_optimized?(d.chapters||[]).map(c=>c.index):[];
    wizMode='audio';
    jobDone=false;
    const btnAdopt=document.getElementById('btnTrAdopt');
    if(btnAdopt)btnAdopt.style.display='none';
    _renderChaptersAfterAdopt(d);
    // Riallinea la voce alla nuova lingua del libro
    if(bookData&&bookData.language){
      const lc=bookData.language.split('-')[0].toLowerCase();
      const vlSel=document.getElementById('vl');
      if(vlSel&&vlSel.querySelector('option[value="'+lc+'"]'))vlSel.value=lc;
    }
    goToStep(3); // pannello voci (audio)
    fillLangs(); // ripreseleziona la lingua = nuova lingua del libro
  }catch(e){alert('Error: '+e.message)}
}

function _renderChaptersAfterAdopt(d){
  // bookData già aggiornato con la forma adottata: riusa fillPreview che
  // ripopola #chapterRows, #bookLang, contatori e stato selezione (tutti
  // i capitoli selezionati di default).
  if(bookData)fillPreview(bookData);
  const bookLangEl=document.getElementById('bookLang');
  if(bookLangEl&&bookData&&bookData.language)bookLangEl.textContent=bookData.language.toUpperCase();
  _updateAiOptUI();
}

// ═══════════════════ EXPORT ABM ═══════════════════
function exportAbm(){
  if(!jobId){showErr('s3err','No file analyzed yet');return}
  const a=document.createElement('a');
  a.href='/api/export_abm/'+jobId;
  const suffix=optimizedChapters.length>0?'_optimized':'';
  a.download=(bookData&&bookData.title?bookData.title:'project')+suffix+'.abm';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
function openAbmGuide(){
  document.getElementById('abmGuideTitle').textContent=t('abm_guide_title');
  document.getElementById('abmGuideBody').innerHTML=t('abm_guide_body');
  document.getElementById('abmGuideModal').classList.add('open');
}
function closeAbmGuide(){document.getElementById('abmGuideModal').classList.remove('open')}

// ═══════════════════ AI TEXT OPTIMIZATION ═══════════════════
function _initAiOptToggle(){
  // New wizard toggle switch
  const aiToggle=document.getElementById('aiToggle');
  if(aiToggle){
    aiToggle.checked=false;
    aiToggle.onchange=function(){toggleAIOptimization()};
  }
  // Legacy toggle buttons (backward compat for old accordion UI)
  const btnOff=document.getElementById('optNone');
  const btnOn=document.getElementById('optEnable');
  if(btnOff)btnOff.onclick=function(){
    aiOptEnabled=false;
    btnOff.classList.add('on');if(btnOn)btnOn.classList.remove('on');
    const aiOptInfo=document.getElementById('aiOptInfo');if(aiOptInfo)aiOptInfo.style.display='none';
    const costEstimate=document.getElementById('costEstimate');if(costEstimate)costEstimate.classList.remove('visible');
    const aiToggle=document.getElementById('aiToggle');if(aiToggle)aiToggle.checked=false;
    _updateAiOptCard();
  };
  if(btnOn)btnOn.onclick=function(){
    aiOptEnabled=true;
    btnOn.classList.add('on');if(btnOff)btnOff.classList.remove('on');
    const aiOptInfo=document.getElementById('aiOptInfo');if(aiOptInfo)aiOptInfo.style.display='';
    const aiToggle=document.getElementById('aiToggle');if(aiToggle)aiToggle.checked=true;
    toggleAIOptimization();
  };
}

function toggleAIOptimization(){
  const aiToggle=document.getElementById('aiToggle');
  aiOptEnabled=aiToggle?aiToggle.checked:!aiOptEnabled;
  if(aiToggle)aiToggle.checked=aiOptEnabled;

  // Legacy toggle sync
  const btnOff=document.getElementById('optNone'),btnOn=document.getElementById('optEnable');
  if(btnOff&&btnOn){
    if(aiOptEnabled){btnOn.classList.add('on');btnOff.classList.remove('on')}
    else{btnOff.classList.add('on');btnOn.classList.remove('on')}
  }

  const aiOptInfo=document.getElementById('aiOptInfo');
  const costEstimate=document.getElementById('costEstimate');
  if(aiOptEnabled){
    if(aiOptInfo)aiOptInfo.style.display='';
    _fetchCostEstimate();
  }else{
    if(aiOptInfo)aiOptInfo.style.display='none';
    if(costEstimate)costEstimate.classList.remove('visible');
  }
  _updateAiOptCard();
  _updateSummary();
}

function _updateAiOptCard(){
  const card=document.getElementById('aiOptCard');
  if(!card)return;
  if(aiOptEnabled&&!_allSelectedOptimized())card.classList.add('enabled');
  else card.classList.remove('enabled');
}

async function _fetchCostEstimate(){
  if(!jobId)return;
  // Con voci PREMIUM il costo LLM (anche oltre soglia) e' bundlato nel
  // pagamento combinato Premium+AI gestito dal modale aperto da onGenerateClick.
  // Saltare il popup voucher LLM-only per evitare una doppia richiesta di pagamento.
  if(wizardState.audioTab==='premium'){
    const costEl=document.getElementById('costEstimate');if(costEl)costEl.classList.remove('visible');
    return;
  }
  try{
    let url=new URL('/api/optimize_estimate/'+jobId, window.location.origin);
    const selLang=document.getElementById('vl').value||cl;
    url.searchParams.append('lang',selLang);
    // Collect selected chapters
    _getSelectedChapterIndexes().forEach(idx=>url.searchParams.append('selected_chapters',idx));
    const est=await fetch(url.toString()).then(r=>r.json());
    if(est.error){return}
    const costEl=document.getElementById('costEstimate');
    if(est.requires_payment){
      // Oneroso: mostra la stima nella card AI. Il pagamento (buono o PayPal)
      // avviene al click Genera col modal condiviso del flusso premium, quando
      // la selezione capitoli è definitiva (vedi startCombinedGeneration).
      const amountEl=document.getElementById('costAmount');
      if(amountEl)amountEl.textContent='€ '+Number(est.cost_eur).toFixed(2);
      const detEl=document.getElementById('costDetail');
      if(detEl)detEl.textContent=Number(est.chars).toLocaleString(cl||'it')+' char';
      if(costEl)costEl.classList.add('visible');
    }else{
      // Free (below threshold): hide cost UI completely — say nothing
      if(costEl)costEl.classList.remove('visible');
    }
  }catch(e){/* ignore estimate errors */}
}

function _updateAiOptUI(){
  const card=document.getElementById('aiOptCard');
  if(!card)return;
  if(llmAvailable){
    card.style.display='';
    if(_allSelectedOptimized()){
      const already=document.getElementById('aiAlreadyOpt');if(already)already.style.display='';
      const aiOptInfo=document.getElementById('aiOptInfo');if(aiOptInfo)aiOptInfo.style.display='none';
      aiOptEnabled=false;
      const aiToggle=document.getElementById('aiToggle');if(aiToggle){aiToggle.checked=false;aiToggle.disabled=true}
      // Legacy
      const optNone=document.getElementById('optNone');if(optNone)optNone.classList.add('on');
      const optEnable=document.getElementById('optEnable');if(optEnable)optEnable.classList.remove('on');
    }else{
      const already=document.getElementById('aiAlreadyOpt');if(already)already.style.display='none';
      const aiToggle=document.getElementById('aiToggle');if(aiToggle)aiToggle.disabled=false;
    }
  }else{
    card.style.display='none';
    aiOptEnabled=false;
  }
  _updateAiOptCard();
}

function _updateSummary(){
  // Book title + author
  const sumTitle=document.getElementById('summaryBookTitle');
  if(sumTitle){
    let t=bookData?bookData.title:'—';
    if(bookData&&bookData.author)t+=' ('+bookData.author+')';
    sumTitle.textContent=t;
  }

  // Count selected chapters
  let cnt=0;
  let boxes=document.querySelectorAll('#chl .col-sel input[type=checkbox]');
  if(!boxes.length)boxes=document.querySelectorAll('#chapterRows .chapter-row input[type=checkbox]');
  boxes.forEach(cb=>{if(cb.checked)cnt++});
  const sumCh=document.getElementById('summaryChapters');
  if(sumCh)sumCh.textContent=cnt+'/'+(bookData?bookData.total_chapters:'—');

  const vr=document.getElementById('vr');
  const sumVoice=document.getElementById('summaryVoice');
  if(sumVoice){
    let voiceName;
    if(wizardState.audioTab==='premium'){
      const vvP=document.getElementById('vvPremium');
      const vSel=vvP&&vvP.selectedIndex>=0?vvP.options[vvP.selectedIndex]:null;
      voiceName=vSel?vSel.text:'—';
    }else{
      const vv=document.getElementById('vv');
      const vSel=vv&&vv.selectedIndex>=0?vv.options[vv.selectedIndex]:null;
      voiceName=vSel?vSel.text.replace(/\s*\(.*?\)\s*/g,'').replace(/Microsoft\s+/g,'').trim():'—';
    }
    const rate=vr?vr.options[vr.selectedIndex].text:'Normal';
    sumVoice.textContent=voiceName+' — '+rate;
  }

  const sumFormat=document.getElementById('summaryFormat');
  if(sumFormat){
    const fmtKey={m4b:'out_m4b',zip:'out_zip',zip_rss:'out_zip_rss',mp3:'out_mp3'}[outputFormat]||'out_m4b';
    sumFormat.textContent=t(fmtKey)||outputFormat.toUpperCase();
  }

  const sumAI=document.getElementById('summaryAI');
  if(sumAI)sumAI.innerHTML=aiOptEnabled?'<span style="color:#16a34a">&#x25CF; '+((t('ai_opt_on')||'Enabled').split(',')[0])+'</span>':'<span style="color:var(--txm)">&#x25CB; '+(t('ai_opt_off')||'Disabled')+'</span>';
}

// ═══════════════════ PAYMENT (LLM optimization) ═══════════════════
let llmConfig={rate:1.1,threshold:0.5,bonus:10,expiry:180,paypalClientId:"",paypalMode:"sandbox",paypalAvailable:false};
let paypalSdkLoaded=false;
let _paypalSdkPromise=null;

function _loadPaypalSdk(clientId){
  if(paypalSdkLoaded&&window.paypal)return Promise.resolve();
  if(_paypalSdkPromise)return _paypalSdkPromise;
  _paypalSdkPromise=new Promise(function(resolve,reject){
    var s=document.createElement('script');
    s.src='https://www.paypal.com/sdk/js?client-id='+encodeURIComponent(clientId)+'&currency=EUR&intent=capture';
    s.onload=function(){paypalSdkLoaded=true;resolve()};
    s.onerror=function(){_paypalSdkPromise=null;reject(new Error('Failed to load PayPal SDK'))};
    document.head.appendChild(s);
  });
  return _paypalSdkPromise;
}

// Carica in llmConfig i parametri di pagamento (rate, soglia, PayPal) da
// /api/llm_available. Idempotente, best-effort: usato dai flussi che non
// passano da /api/combined_estimate (es. traduzione). Fallimento silenzioso.
async function _loadLlmPaymentConfig(){
  try{
    const cfg=await fetch('/api/llm_available').then(r=>r.json());
    llmConfig.rate=cfg.rate_eur_per_mchar||1.1;
    llmConfig.threshold=cfg.free_threshold_eur||0.5;
    llmConfig.bonus=cfg.voucher_bonus_percent||10;
    llmConfig.expiry=cfg.voucher_expiry_days||180;
    llmConfig.paypalClientId=cfg.paypal_client_id||"";
    llmConfig.paypalMode=cfg.paypal_mode||"sandbox";
    llmConfig.paypalAvailable=!!cfg.paypal_available;
  }catch(e){/* best-effort */}
}

function _showPaymentModal(costEur,chars,orderOpts){
  // Ottimizzazione AI standalone (voci standard): riusa il modal condiviso
  // Buono/PayPal del flusso premium (_openPayModalCtx) come adapter
  // promise-based — risolve col payment_token alla conferma, null all'annullo.
  // orderOpts (optional): {endpoint, body} override della create-order PayPal
  // per flussi alternativi. Il path voucher non ne è influenzato.
  return new Promise(function(resolve){
    _openPayModalCtx({
      lines:[{labelKey:'pay_text_ai_optimization',amount:costEur}],
      total:costEur,
      voucherPurpose:'llm',
      paypal:{
        endpoint:(orderOpts&&orderOpts.endpoint)||'/api/paypal_create_order',
        buildBody:function(){
          if(orderOpts&&orderOpts.body)return orderOpts.body;
          // Stessi capitoli usati per la stima: il server ricalcola l'importo
          // sul medesimo subset (capitoli già ottimizzati esclusi lato server).
          return {job_id:jobId,selected_chapters:(typeof _getSelectedChapterIndexes==='function')?_getSelectedChapterIndexes():[]};
        }
      },
      onConfirm:function(token){resolve(token)},
      onCancel:function(){resolve(null)}
    });
  });
}

async function _validateLanguage() {
  if(!bookData) return true;
  // 1. Case: Language unknown (no metadata and no AI detection)
  if(!bookData.language && !previewListened) {
    return await _showLangWarning();
  }
  // 2. Case: Mismatch between detected/metadata language and selected voice
  const bookLang = bookData.language ? bookData.language.split('-')[0].toLowerCase() : '';
  const voiceLang = (wizardState.audioTab === 'premium')
    ? document.getElementById('vlPremium').value
    : document.getElementById('vl').value;
  if(bookLang && voiceLang && bookLang !== voiceLang && !previewListened) {
    // Show the same warning modal (it asks to verify voice/language)
    return await _showLangWarning();
  }
  return true;
}

async function startCombinedGeneration(combinedPaymentToken){
  if(!jobId||generating)return;

  // Check admin suspend
  try{
    const sr=await fetch('/api/admin/suspend');
    if(sr.ok){const sd=await sr.json();if(sd.suspended){alert('System under maintenance. Please try again in a few minutes.');return}}
  }catch(e){}

  if(!(await _validateLanguage()))return;
  // Donate modal for returning users — saltato per Voci PREMIUM: chiedere
  // una donazione subito dopo (o in luogo di) un pagamento Premium e' UX
  // contraddittoria. La generazione gratis con voci Standard mantiene il prompt.
  if(wizardState.audioTab!=='premium' && _shouldShowDonateModal()){await _showDonateModal();}
  _markGeneration();

  // Collect selected chapters
  let selectedChapters=_getSelectedChapterIndexes();
  if(selectedChapters.length===0){showS3Err(t('sel_err_none')||'Select at least one chapter');return}
  document.getElementById('s3err').innerHTML='';

  // Generate button → loading state
  const btnGen=document.getElementById('btnGenerate');
  const genBtns=document.getElementById('genButtons');
  if(btnGen)btnGen.disabled=true;
  if(btnGen)btnGen.innerHTML='<div class="sp"></div><span>'+t('btn_gen')+'...</span>';

  if(aiOptEnabled&&!_allSelectedOptimized()){
    // ── AI optimization flow ──
    // Payment check
    var paymentToken=combinedPaymentToken||null;
    try{
      let url=new URL('/api/optimize_estimate/'+jobId, window.location.origin);
      const selLang=(wizardState.audioTab==='premium')
        ?document.getElementById('vlPremium').value||cl
        :document.getElementById('vl').value||cl;
      url.searchParams.append('lang',selLang);
      // Passa la voce cosi' il server applica il cap corretto (Gemini ha MAX_GEMINI_TEXT_CHARS piu' restrittivo).
      const _voiceForEst=(typeof getCurrentVoiceId==='function')?getCurrentVoiceId():'';
      if(_voiceForEst)url.searchParams.append('voice',_voiceForEst);
      if(selectedChapters&&selectedChapters.length>0){
        selectedChapters.forEach(idx=>url.searchParams.append('selected_chapters',idx));
      }
      var est=await fetch(url.toString()).then(r=>r.json());
      if(est.error){showS3Err(est.error);if(btnGen){btnGen.disabled=false;btnGen.innerHTML='<span data-t="btn_gen">'+t('btn_gen')+'</span>'}return}
      if(est.requires_payment&&!paymentToken){
        // Pagamento al Generate: config PayPal aggiornata, poi modal condiviso
        // Buono/PayPal (stesso strumento delle voci premium).
        await _loadLlmPaymentConfig();
        paymentToken=await _showPaymentModal(est.cost_eur,est.chars);
        if(!paymentToken){if(btnGen){btnGen.disabled=false;btnGen.innerHTML='<span data-t="btn_gen">'+t('btn_gen')+'</span>'}return}
      }
    }catch(e){showS3Err('Estimate error: '+e.message);if(btnGen){btnGen.disabled=false;btnGen.innerHTML='<span data-t="btn_gen">'+t('btn_gen')+'</span>'}return}

    _showWizProgress();
    _setCancelButtonMode('opt');
    lockUI();
    try{
      console.log('[startCombinedGeneration] preparing /api/optimize payload', {jobId, paymentToken: !!paymentToken, selectedChapters, audioTab: wizardState.audioTab});
      const selLangEl=(wizardState.audioTab==='premium')
        ?document.getElementById('vlPremium')
        :document.getElementById('vl');
      const selLang=(selLangEl&&selLangEl.value)||cl;
      _rememberLastLang(selLang);
      const vrEl=document.getElementById('vr');
      const voiceId=getCurrentVoiceId();
      var payload={job_id:jobId,batch:false,lang:selLang};
      if(paymentToken)payload.payment_token=paymentToken;
      if(selectedChapters)payload.selected_chapters=selectedChapters;
      // Always use auto_generate in wizard flow
      payload.auto_generate=true;
      payload.voice=voiceId;
      payload.rate=(vrEl&&vrEl.value)||'+0%';
      payload.single_file=singleFile;
      payload.output_format=outputFormat;
      payload.podcast_base_url=podcastBaseUrl;
      Object.assign(payload,getParenFlags());
      console.log('[startCombinedGeneration] POST /api/optimize', payload);
      var r=await fetch('/api/optimize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      console.log('[startCombinedGeneration] /api/optimize response', r.status);
      var d=await r.json();
      console.log('[startCombinedGeneration] /api/optimize body', d);
      if(d.error){
        if(d.error_code==='selection_too_large'){
          const gp=document.getElementById('generationProgress');if(gp)gp.style.display='none';
          const pf=document.getElementById('panel4Footer');if(pf)pf.style.display='';
          _showSelTooLargeModal(d.chars_selected,d.chars_limit);unlockUI();return;
        }
        if(d.error_code==='llm_concurrent_limit'){
          const gp=document.getElementById('generationProgress');if(gp)gp.style.display='none';
          const pf=document.getElementById('panel4Footer');if(pf)pf.style.display='';
          showErr('s3err',t('llm_concurrent_limit')||d.error);
        }else{showPErr(d.error)}
        unlockUI();return;
      }
      _listenOptProgressWiz();
      // QR di trasferimento gia' in fase di ottimizzazione: il wizard imposta
      // sempre auto_generate=true, quindi il job produrra' l'audio in autonomia
      // e il claim (email_registered=True) garantisce il download token al
      // COMPLETE. Mostrarlo subito permette all'utente di trasferire su app e
      // abbandonare la pagina durante l'ottimizzazione (anche lunga), senza
      // dover attendere il passaggio alla generazione.
      _showTransferQr(jobId, 'transferStartImg', 'transferStartArea');
    }catch(e){
      console.error('[startCombinedGeneration] exception during /api/optimize', e);
      showPErr('Error: '+e.message);
      const pMsgEl=document.getElementById('pMsg');
      if(pMsgEl){pMsgEl.textContent='Errore: '+e.message;pMsgEl.style.color='var(--err)';}
      unlockUI();
    }
  }else{
    // ── Direct TTS generation ──
    _showWizProgress();
    _setCancelButtonMode('gen');
    lockUI();
    try{
      var _genLang=(wizardState.audioTab==='premium')
        ?(document.getElementById('vlPremium')?.value||cl)
        :(document.getElementById('vl')?.value||cl);
      _rememberLastLang(_genLang);
      var genPayload={job_id:jobId,voice:getCurrentVoiceId(),rate:document.getElementById('vr').value,single_file:singleFile,output_format:outputFormat,podcast_base_url:podcastBaseUrl,lang:_genLang,...getParenFlags()};
      if(selectedChapters)genPayload.selected_chapters=selectedChapters;
      if(combinedPaymentToken)genPayload.payment_token=combinedPaymentToken;
      if(_isGeminiVoiceId(getCurrentVoiceId())){
        var _gs=(document.getElementById('geminiStyle')?.value||'').trim().slice(0,200);
        if(_gs)genPayload.gemini_style_instruction=_gs;
        var _ga=_getAccentVariant();
        if(_ga)genPayload.gemini_accent=_ga;
      }
      if(_isSpeechifyVoiceId(getCurrentVoiceId())){
        var _emo=(document.getElementById('speechifyEmotion')?.value||'');
        if(_emo)genPayload.speechify_emotion=_emo;
      }
      var gr=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(genPayload)});
      var gd=await gr.json();
      if(gd.error){
        if(gd.error_code==='selection_too_large'){
          const gp=document.getElementById('generationProgress');if(gp)gp.style.display='none';
          const pf=document.getElementById('panel4Footer');if(pf)pf.style.display='';
          _showSelTooLargeModal(gd.chars_selected,gd.chars_limit);unlockUI();return;
        }
        if(gd.error_code==='concurrent_limit'){
          const gp=document.getElementById('generationProgress');if(gp)gp.style.display='none';
          const pf=document.getElementById('panel4Footer');if(pf)pf.style.display='';
          showErr('s3err',t('concurrent_limit')||gd.error);
          unlockUI();return;
        }
        if(gd.error_code==='google_tts_budget'){
          document.getElementById('pMsg').innerHTML=(t('google_tts_budget_err')||gd.error);
          document.getElementById('pMsg').style.color='var(--err)';
          document.getElementById('cnA').innerHTML='<button class="btn btn-ok" id="btnRetryWiz">🔄 '+(t('btn_retry')||'Retry generation')+'</button>';
          document.getElementById('btnRetryWiz').onclick=retryGeneration;
          unlockUI();return;
        }
        if(gd.error_code==='gemini_overload'){
          // Pre-flight block sincrono: nessun job avviato, nessun payment consumato.
          unlockUI();generating=false;
          document.getElementById('cnA').style.display='none';
          try{console.log('[abm] gemini_overload (sync /api/generate):', gd);}catch(e){}
          _showGeminiOverloadModal(gd);
          return;
        }
        showPErr(gd.error);unlockUI();return;
      }
      if(gd.auto_batch_email){emailRegistered=true;_showAutoBatchNotice(gd.auto_batch_email);_updateGenNoticeWarning();}
      _showTransferQr(jobId, 'transferStartImg', 'transferStartArea');
      listenProgress();
    }catch(e){showPErr('Error: '+e.message);unlockUI()}
  }
}

function _setWizPct(pct){
  const p=Math.max(0,Math.min(100,Math.round(pct||0)));
  const pBar=document.getElementById('pBar');if(pBar)pBar.style.width=p+'%';
  const pPct=document.getElementById('pPct');if(pPct)pPct.textContent=p+'%';
  const progressFill=document.getElementById('progressFill');if(progressFill)progressFill.style.width=p+'%';
  const progressPct=document.getElementById('progressPct');if(progressPct)progressPct.textContent=p+'%';
}

var _jobRunningModalJobId=null;
function _showJobRunningModal(pct,forJobId){
  _jobRunningModalJobId=forJobId||jobId||null;
  var pctVal=Math.round(pct||0);
  var msg=t('job_already_running',{pct:pctVal});
  var modal=document.getElementById('jobRunningModal');
  if(!modal){
    // Fallback: show a styled modal inserted into body
    var el=document.createElement('div');
    el.id='jobRunningModal';
    el.className='modal-overlay open';
    el.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:9999';
    el.innerHTML='<div class="modal" style="max-width:480px"><div class="modal-head"><h2>'+t('job_already_running_title')+'</h2></div><div class="modal-body">'+msg+'</div></div>';
    el._dynamic=true;
    el.onclick=function(ev){if(ev.target===el){el.remove();_jobRunningModalJobId=null;resetAll();}};
    document.body.appendChild(el);
    return;
  }
  var msgEl=document.getElementById('jobRunningMsg');
  if(msgEl){
    var span='<span id="jobRunningPct">'+pctVal+'</span>';
    msgEl.innerHTML=t('job_already_running',{pct:span});
  }
  var title=document.getElementById('jobRunningTitle');
  if(title)title.textContent=t('job_already_running_title')||title.textContent;
  modal.classList.add('open');
  modal.style.display='';
  var closeBtn=document.getElementById('jobRunningClose');
  if(closeBtn)closeBtn.onclick=function(){_hideJobRunningModal();};
  modal.onclick=function(ev){if(ev.target===modal)_hideJobRunningModal();};
}
function _hideJobRunningModal(reset,forJobId){
  // If forJobId is provided, only hide if it matches the modal's tracked job.
  // Prevents an SSE for a different in-progress job from closing a modal
  // that is showing the user a different job's status.
  if(forJobId!=null&&_jobRunningModalJobId!=null&&forJobId!==_jobRunningModalJobId)return;
  var modal=document.getElementById('jobRunningModal');
  if(!modal){_jobRunningModalJobId=null;return}
  if(modal._dynamic){modal.remove();}
  else{modal.classList.remove('open');}
  _jobRunningModalJobId=null;
  if(reset!==false)resetAll(); // reset only when user manually closes the modal
}
function _updateJobRunningPct(pct,forJobId){
  // Only update the modal if the SSE tick belongs to the job the modal is
  // tracking. With multiple concurrent jobs the user may have several SSE
  // streams alive, all targeting the same DOM element.
  if(forJobId!=null&&_jobRunningModalJobId!=null&&forJobId!==_jobRunningModalJobId)return;
  const span=document.getElementById('jobRunningPct');
  if(span)span.textContent=Math.round(pct||0);
}

// Popup mostrato quando il pre-flight rileva che le voci PREMIUM sono
// sature (RPD esaurito): rimborso gia' emesso, l'utente puo' tornare alla
// scelta voce e scegliere un'altra opzione (altro modello PREMIUM o voci
// Standard). Niente redirect alla home.
function _showGeminiOverloadModal(d){
  // Helper: t() ritorna la chiave stessa se la traduzione manca, quindi
  // l'idioma "t(k)||fallback" non scatta mai (la chiave e' truthy).
  // _tf invece riconosce il caso "non tradotto" e usa il fallback.
  function _tf(k, fallback){var v=t(k); return (v===k||!v)?fallback:v;}
  // Cleanup eventuale modal residuo
  var old=document.getElementById('geminiOverloadModal');
  if(old)old.remove();
  // Distingue caso preventivo (controllo PRIMA del pagamento → nessun rimborso da mostrare)
  // dal caso post-pagamento (refund_method valorizzato → mostriamo la riga rimborso).
  var hasRefund=!!(d&&d.refund_method);
  var refundLine='';
  if(hasRefund){
    if(d.refund_method==='paypal'&&d.refund_voucher_code){
      refundLine='<p style="margin:8px 0 0;color:#374151">'+esc(_tf('gemini_overload_refund_paypal','L\'importo ti e\' stato rimborsato sotto forma di voucher'))+
        ' <code style="background:rgba(0,0,0,.06);color:#111;padding:2px 6px;border-radius:4px;font-weight:600">'+esc(d.refund_voucher_code)+'</code> '+
        esc(_tf('gemini_overload_refund_email_hint','(anche via email).'))+'</p>';
    }else if(d.refund_method==='voucher'){
      refundLine='<p style="margin:8px 0 0;color:#374151">'+esc(_tf('gemini_overload_refund_voucher','L\'importo e\' stato riaccreditato sul voucher che hai usato.'))+'</p>';
    }
  }
  // Retry hint (solo se >0 e sotto 24h)
  var retryLine='';
  var rs=Number(d&&d.retry_after_sec||0);
  if(rs>0&&rs<86400){
    var h=Math.ceil(rs/3600);
    retryLine='<p style="margin:8px 0 0;color:#6b7280;font-size:.92em">'+
      esc(_tf('gemini_overload_retry_hint','Le voci PREMIUM tornano disponibili tra circa {h} h.').replace('{h}',h))+'</p>';
  }
  // Testo del popup: preventivo (no pagamento) vs post-pagamento.
  var title, body, btnLabel;
  if(hasRefund){
    title=esc(_tf('gemini_overload_title','Voci PREMIUM temporaneamente non disponibili'));
    body=esc(_tf('gemini_overload_body',
      'Le voci PREMIUM non sono disponibili in questo momento. La generazione non e\' partita e hai ricevuto il rimborso integrale. Puoi proseguire scegliendo:'));
    btnLabel=esc(_tf('gemini_overload_btn','Torna alla scelta voce'));
  }else{
    title=esc(_tf('gemini_overload_title_pre','Voci PREMIUM temporaneamente non disponibili'));
    body=esc(_tf('gemini_overload_body_pre',
      'Le voci PREMIUM hanno raggiunto il limite giornaliero di utilizzo. Per proseguire puoi scegliere:'));
    btnLabel=esc(_tf('gemini_overload_btn_pre','Ho capito'));
  }
  var optA=esc(_tf('gemini_overload_opt_a','un altro modello di voci PREMIUM'));
  var optB=esc(_tf('gemini_overload_opt_b','le voci Standard (sempre disponibili, gratuite)'));
  var el=document.createElement('div');
  el.id='geminiOverloadModal';
  el.className='modal-overlay open';
  el.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:9999;color:#111';
  el.innerHTML=
    '<div class="modal" style="max-width:540px;background:#fff;color:#111;border-radius:12px;padding:0;box-shadow:0 10px 40px rgba(0,0,0,.25)">'+
      '<div class="modal-head" style="padding:18px 22px 12px;border-bottom:1px solid #e5e7eb"><h2 style="margin:0;font-size:1.15em;color:#111;font-weight:700">'+title+'</h2></div>'+
      '<div class="modal-body" style="padding:14px 22px 18px;color:#111;line-height:1.5">'+
        '<p style="margin:0 0 10px;color:#1f2937">'+body+'</p>'+
        '<ul style="margin:0 0 6px;padding-left:22px;color:#1f2937"><li>'+optA+'</li><li>'+optB+'</li></ul>'+
        refundLine+retryLine+
        '<div style="margin-top:18px;text-align:right">'+
          '<button id="geminiOverloadBtn" class="btn btn-primary" style="padding:8px 16px;border-radius:8px;background:var(--ac,#4f46e5);color:#fff;border:none;font-weight:600;cursor:pointer">'+btnLabel+'</button>'+
        '</div>'+
      '</div>'+
    '</div>';
  document.body.appendChild(el);
  function dismiss(){
    el.remove();
    // Pulisci eventuale errore inline residuo nello step di progress
    var pra=document.getElementById('pra');if(pra)pra.innerHTML='';
    // Torna allo step 3 (scelta voce/audio)
    try{goToStep(3);}catch(e){}
    // Libera lo stato wizard per consentire un nuovo avvio.
    // IMPORTANTE: NON azzerare jobId. Nel preflight sincrono il job rimane
    // in status="analyzed" lato server e l'utente puo' cambiare modello /
    // tab voce e ripartire. Azzerando jobId rompiamo /api/combined_estimate
    // (che richiede jobId) e la "STIMA COSTO CAPITOLI SELEZIONATI" non si
    // ricalcola piu' al cambio modello.
    try{
      jobDone=false;generating=false;
      var gp=document.getElementById('generationProgress');if(gp)gp.style.display='none';
      var p4f=document.getElementById('panel4Footer');if(p4f)p4f.style.display='';
      var gan=document.getElementById('generationActiveNotice');if(gan)gan.style.display='none';
    }catch(e){}
    // Ricalcola la stima per il modello/voce attualmente selezionato.
    try{if(typeof requestCombinedEstimate==='function')requestCombinedEstimate();}catch(e){}
  }
  var btn=document.getElementById('geminiOverloadBtn');
  if(btn)btn.onclick=dismiss;
  el.onclick=function(ev){if(ev.target===el)dismiss();};
}

function _showWizProgress(){
  _stopAnalyzedHeartbeat();
  const genProgress=document.getElementById('generationProgress');if(genProgress)genProgress.style.display='';
  const panel4Footer=document.getElementById('panel4Footer');if(panel4Footer)panel4Footer.style.display='none';
  const genActiveNotice=document.getElementById('generationActiveNotice');if(genActiveNotice)genActiveNotice.style.display='flex';
  const aiOptCard=document.getElementById('aiOptCard');if(aiOptCard)aiOptCard.style.display='none';
  const summaryBox=document.getElementById('summaryBox');if(summaryBox)summaryBox.style.display='none';
  const emailLateArea=document.getElementById('emailLateArea');if(emailLateArea)emailLateArea.classList.add('visible');
  const pBar=document.getElementById('pBar');if(pBar)pBar.style.width='0%';
  const pPct=document.getElementById('pPct');if(pPct)pPct.textContent='0%';
  const pMsg=document.getElementById('pMsg');if(pMsg)pMsg.textContent=t('starting');
  const progressFill=document.getElementById('progressFill');if(progressFill)progressFill.style.width='0%';
  const progressPct=document.getElementById('progressPct');if(progressPct)progressPct.textContent='0%';
  const progressPhase=document.getElementById('progressPhase');
  if(progressPhase){
    const phaseLabel=(aiOptEnabled&&!_allSelectedOptimized())?(t('s4_opt_title')||'AI Optimization + Generation'):(t('s4_title')||'Generation');
    progressPhase.textContent=phaseLabel;
  }
  const s3err=document.getElementById('s3err');if(s3err)s3err.innerHTML='';
}

function _listenOptProgressWiz(){
  var myJobId=jobId;
  _ensureEmailAreaVisible();
  _updateGenNoticeWarning();
  _autoRegisterEmailFromStorage(myJobId);
  var es=new EventSource('/api/optimize_progress/'+myJobId);
  es.onmessage=function(ev){
    var d=JSON.parse(ev.data);
    if(d.status==='error'){
      es.close();_hideJobRunningModal(true,myJobId);_setCancelButtonMode('gen');showPErr(d.error||'Optimization error');unlockUI();return;
    }
    if(d.status==='cancelled'){
      es.close();_hideJobRunningModal(true,myJobId);_setCancelButtonMode('gen');
      document.getElementById('pMsg').textContent=t('opt_cancelled')||'Optimization cancelled';
      unlockUI();return;
    }
    if(d.status==='optimized'){
      es.close();
      _setCancelButtonMode('gen');
      (async()=>{try{const est=await fetch('/api/optimize_estimate/'+jobId).then(r=>r.json());if(est.optimized_chapters)optimizedChapters=est.optimized_chapters;}catch(e){}})();
      aiOptEnabled=false;
      _updateAiOptUI();
      document.getElementById('pMsg').textContent=t('opt_done')||'Text optimization complete!';
      document.getElementById('pBar').style.width='100%';
      document.getElementById('pPct').textContent='100%';
      const progressFill=document.getElementById('progressFill');if(progressFill)progressFill.style.width='100%';
      const progressPct=document.getElementById('progressPct');if(progressPct)progressPct.textContent='100%';
      const progressPhase=document.getElementById('progressPhase');if(progressPhase)progressPhase.textContent=t('opt_done')||'Optimization complete';
      // Show proceed button in cnA
      var cnA=document.getElementById('cnA');
      cnA.innerHTML='<div style="display:flex;flex-direction:column;gap:10px;align-items:center;margin-top:12px">'
        +'<button class="btn btn-ok" id="btnProceedGen" style="width:100%;max-width:400px">🎧 '+(t('opt_proceed_gen')||'Generate audiobook')+'</button>'
        +'<button class="btn btn-g" id="btnDownloadAbm" style="width:100%;max-width:400px">📥 '+(t('opt_download_abm')||'Download optimized project (.abm)')+'</button>'
        +'</div>';
      document.getElementById('btnProceedGen').onclick=function(){
        var bpg=document.getElementById('btnProceedGen');if(bpg.disabled)return;
        bpg.disabled=true;bpg.style.opacity='0.6';bpg.style.cursor='not-allowed';
        var bda=document.getElementById('btnDownloadAbm');if(bda){bda.disabled=true;bda.style.opacity='0.6';bda.style.cursor='not-allowed';}
        startGen();
      };
      document.getElementById('btnDownloadAbm').onclick=function(){
        fetch('/api/export_abm/'+jobId).then(function(r){if(!r.ok)throw new Error('Export failed');return r.blob();})
        .then(function(blob){var a=document.createElement('a');a.href=URL.createObjectURL(blob);
          a.download=(bookData&&bookData.title?bookData.title:'project')+'_optimized.abm';
          a.click();URL.revokeObjectURL(a.href);
        }).catch(function(e){alert('Error: '+e.message)});
      };
      unlockUI();return;
    }
    if(d.auto_generate_started){
      es.close();
      _setCancelButtonMode('gen');
      const progressPhase=document.getElementById('progressPhase');if(progressPhase)progressPhase.textContent=t('s4_title')||'Generation';
      _showTransferQr(jobId, 'transferStartImg', 'transferStartArea');
      listenProgress();
      return;
    }
    // Update wizard + old progress
    var totalChars=d.opt_total_chars_extended||d.opt_total_chars||1;
    var doneChars=d.opt_processed_chars||0;
    var curChChars=d.opt_current_chapter_chars||0;
    var streamedChars=Math.min(d.opt_streamed_chars||0,curChChars);
    var workedChars=doneChars+streamedChars;
    var pct=Math.min(100,Math.round(workedChars/totalChars*100));
    document.getElementById('pBar').style.width=pct+'%';
    document.getElementById('pPct').textContent=pct+'%';
    document.getElementById('pMsg').textContent=d.opt_progress_message||'';
    const progressFill=document.getElementById('progressFill');if(progressFill)progressFill.style.width=pct+'%';
    const progressPct=document.getElementById('progressPct');if(progressPct)progressPct.textContent=pct+'%';
    const progressPhase=document.getElementById('progressPhase');if(progressPhase&&d.opt_progress_message)progressPhase.textContent=d.opt_progress_message;
    _updateJobRunningPct(pct,myJobId);

    var pChEl=document.getElementById('pCh');
    if(pChEl&&d.opt_current_chapter){pChEl.textContent='Cap. '+(d.opt_current_chapter_num||'?')+'/'+(d.opt_progress_total||'?')+': '+String(d.opt_current_chapter).substring(0,40);}
    if(d.opt_progress_total>0){var xChEl=document.getElementById('xCh');if(xChEl){xChEl.textContent=(d.opt_current_chapter_num||0)+' / '+d.opt_progress_total;xChEl.closest('.ps').style.display=''}}
    if(d.opt_elapsed_seconds>0){var el=document.getElementById('xEl');if(el){el.textContent=fmtTime(d.opt_elapsed_seconds);el.closest('.ps').style.display=''}}
    if(workedChars>0&&d.opt_elapsed_seconds>1&&totalChars>0){
      var cps=workedChars/d.opt_elapsed_seconds;
      var left=Math.max(0,totalChars-workedChars);
      var eta=Math.round(left/cps);
      var xEtaEl=document.getElementById('xEta');if(xEtaEl){xEtaEl.textContent=eta>0?'~'+fmtTime(eta):t('almost');xEtaEl.closest('.ps').style.display=''}
      var xSpdEl=document.getElementById('xSpd');if(xSpdEl){xSpdEl.textContent=Math.round(cps)+' '+t('cps');xSpdEl.closest('.ps').style.display=''}
    }
    if(workedChars>0){var xSzEl=document.getElementById('xSz');if(xSzEl){xSzEl.textContent=workedChars.toLocaleString(cl||'it')+' char';xSzEl.closest('.ps').style.display=''}}
  };
  es.onerror=function(){es.close()};
}

function showS3Err(msg){
  var s3err=document.getElementById('s3err');
  if(s3err){s3err.textContent=msg;s3err.style.color='var(--err)'}
}

// ═══════════════════ GENERATION ═══════════════════
function _showLangWarning(){
  return new Promise(resolve=>{
    _langWarnResolve=function(val){
      document.getElementById('langWarnModal').classList.remove('open');
      _langWarnResolve=null;
      resolve(val);
    };
    applyI18n();
    document.getElementById('langWarnModal').classList.add('open');
  });
}

// ═══════════════════ DONATE MODAL ═══════════════════
let _donateModalResolve=null;

function _shouldShowDonateModal(){
  // Show only if client has generated before (not first time) and not suppressed
  try{
    const gen=localStorage.getItem('abm_gen_count');
    if(!gen||parseInt(gen)<2)return false; // need 2+ generations
    const suppress=localStorage.getItem('abm_donate_dismiss');
    if(suppress){
      const until=parseInt(suppress);
      if(Date.now()<until)return false; // still suppressed
      localStorage.removeItem('abm_donate_dismiss'); // expired
    }
    return true;
  }catch(e){return false}
}

function _markGeneration(){
  // Increment generation counter so next time the modal can show
  try{
    const c=parseInt(localStorage.getItem('abm_gen_count')||'0');
    localStorage.setItem('abm_gen_count',String(c+1));
  }catch(e){}
}

function _suppressDonate(days){
  try{localStorage.setItem('abm_donate_dismiss',String(Date.now()+days*86400000))}catch(e){}
}

function _showDonateModal(){
  return new Promise(resolve=>{
    _donateModalResolve=resolve;
    applyI18n(); // ensure texts are up-to-date
    document.getElementById('donateModal').classList.add('open');
  });
}

function closeDonateModalX(){
  const m=document.getElementById('donateModal');
  if(!m||!m.classList.contains('open'))return;
  m.classList.remove('open');
  _suppressDonate(7); // X close → reappear after 7 days
  if(_donateModalResolve){_donateModalResolve(true);_donateModalResolve=null}
}

function onDonateModal(action){
  document.getElementById('donateModal').classList.remove('open');
  _suppressDonate(30); // donate or "already donated" → suppress 30 days
  if(_donateModalResolve){_donateModalResolve(true);_donateModalResolve=null}
}

function openDonateFromFooter(){
  applyI18n();
  document.getElementById('donateModal').classList.add('open');
}

async function startGen(){
  // Direct TTS generation (called from startCombinedGeneration or from old optimize→proceed flow)
  try{const sr=await fetch('/api/admin/suspend');if(sr.ok){const sd=await sr.json();if(sd.suspended){alert('System under maintenance. Please try again in a few minutes.');return}}}catch(e){}
  if(!(await _validateLanguage()))return;
  let selectedChapters=_getSelectedChapterIndexes();
  if(selectedChapters.length===0){showErr('s3err',t('sel_err_none'));return}
  document.getElementById('s3err').innerHTML='';
  _showWizProgress();
  _setCancelButtonMode('gen');
  lockUI();
  try{
    const _genLang2=(wizardState.audioTab==='premium')
      ?(document.getElementById('vlPremium')?.value||cl)
      :(document.getElementById('vl')?.value||cl);
    _rememberLastLang(_genLang2);
    const payload={job_id:jobId,voice:getCurrentVoiceId(),rate:document.getElementById('vr').value,single_file:singleFile,output_format:outputFormat,podcast_base_url:podcastBaseUrl,lang:_genLang2,...getParenFlags()};
    if(selectedChapters)payload.selected_chapters=selectedChapters;
    if(_isGeminiVoiceId(getCurrentVoiceId())){
      const _gs=(document.getElementById('geminiStyle')?.value||'').trim().slice(0,200);
      if(_gs)payload.gemini_style_instruction=_gs;
      const _ga=_getAccentVariant();
      if(_ga)payload.gemini_accent=_ga;
    }
    if(_isSpeechifyVoiceId(getCurrentVoiceId())){
      const _emo=(document.getElementById('speechifyEmotion')?.value||'');
      if(_emo)payload.speechify_emotion=_emo;
    }
    const r=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    if(d.error){
      if(d.error_code==='selection_too_large'){
        const gp=document.getElementById('generationProgress');if(gp)gp.style.display='none';
        const pf=document.getElementById('panel4Footer');if(pf)pf.style.display='';
        showErr('s3err',d.error);unlockUI();return;
      }
      if(d.error_code==='concurrent_limit'){
        const gp=document.getElementById('generationProgress');if(gp)gp.style.display='none';
        const pf=document.getElementById('panel4Footer');if(pf)pf.style.display='';
        showErr('s3err',t('concurrent_limit')||d.error);
        unlockUI();return
      }
      if(d.error_code==='google_tts_budget'){
        document.getElementById('pMsg').innerHTML=(t('google_tts_budget_err')||d.error);document.getElementById('pMsg').style.color='var(--err)';
        document.getElementById('cnA').innerHTML='<button class="btn btn-ok" id="btnRetryWiz">🔄 '+(t('btn_retry')||'Retry generation')+'</button>';
        document.getElementById('btnRetryWiz').onclick=retryGeneration;unlockUI();return
      }
      if(d.error_code==='gemini_overload'){
        unlockUI();generating=false;
        document.getElementById('cnA').style.display='none';
        try{console.log('[abm] gemini_overload (sync /api/generate):', d);}catch(e){}
        _showGeminiOverloadModal(d);
        return;
      }
      showPErr(d.error);unlockUI();return
    }
    if(d.auto_batch_email){
      // Batch implicito server-side: l'email del pagamento e' gia' registrata
      // (email_registered=True sul job). Allinea il flag client cosi'
      // _updateGenNoticeWarning() nasconde il banner ATTENZIONE (contraddittorio)
      // e onBeforeUnload non invia il cancel-beacon.
      emailRegistered=true;
      _showAutoBatchNotice(d.auto_batch_email);
      _updateGenNoticeWarning();
    }
    _showTransferQr(jobId, 'transferStartImg', 'transferStartArea');
    listenProgress();
  }catch(e){showPErr('Error: '+e.message);unlockUI()}
}

function _showAutoBatchNotice(maskedEmail){
  // Job PREMIUM pagato portato in modalità batch: rende esplicito all'utente
  // che riceverà l'audiolibro via email (sull'indirizzo del pagamento) anche
  // se chiude la pagina. Banner persistente nell'area di generazione.
  if(!maskedEmail)return;
  let n=document.getElementById('autoBatchNotice');
  if(!n){
    n=document.createElement('div');
    n.id='autoBatchNotice';
    n.className='al al-ok';
    n.style.marginTop='10px';
    const host=document.getElementById('generationProgress')||document.getElementById('cnA');
    if(host&&host.parentNode){host.parentNode.insertBefore(n,host);}
    else if(host){host.appendChild(n);}
  }
  const tmpl=t('auto_batch_notify')||"Pagamento ricevuto: ti invieremo l'audiolibro via email a {email}. Puoi chiudere questa pagina.";
  n.textContent=tmpl.replace('{email}',maskedEmail);
  n.style.display='block';
  _lockEmailLateBoxAutoBatch(maskedEmail);
}

function _lockEmailLateBoxAutoBatch(maskedEmail){
  // Job pagato con email gia' registrata (auto-batch su voucher o PayPal): la
  // notifica e' garantita, l'utente non deve inserire nulla. Mostriamo il box
  // di notifica precompilato e DISABILITATO (sola lettura) per coerenza, senza
  // il bottone d'invio. L'email reale (digitata per il voucher) e' in
  // localStorage; per PayPal usiamo l'indirizzo mascherato del pagamento.
  const input=document.getElementById('notifyEmailLate');
  if(input){
    let real='';
    try{real=(localStorage.getItem('abm_v_email')||'').trim();}catch(e){}
    input.value=(real&&/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(real))?real:(maskedEmail||'');
    input.disabled=true;
    input.readOnly=true;
  }
  const btn=document.getElementById('btnSubmitEmailLate');
  if(btn)btn.disabled=true;
}

// Su smartphone/tablet il QR di trasferimento e' inutile: non c'e' un secondo
// dispositivo che lo inquadri. Il bottone naviga direttamente al deep link
// /t/<token> (App Link/Universal Link): apre l'app se installata, altrimenti la
// pagina store di fallback. L'iPad in UA-desktop (default iPadOS 13+) sfugge
// all'UA-sniff ma viene preso dal ramo touch (pointer:coarse + maxTouchPoints>1).
function _isMobileLike(){
  try{
    if(/Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent||'')) return true;
    var coarse = !!(window.matchMedia && window.matchMedia('(pointer:coarse)').matches);
    return coarse && (navigator.maxTouchPoints||0) > 1;
  }catch(_e){ return false; }
}

// Package Android + custom scheme dell'app (stabili). Servono a costruire i
// deep link (intent:// su Android, abm:// su iOS).
var ABM_ANDROID_PKG = 'it.abm.audiobook_maker_mobile';
var ABM_SCHEME = 'abm';

function _isAndroidUA(){ try{ return /Android/i.test(navigator.userAgent||''); }catch(_e){ return false; } }
function _isIOSUA(){
  try{
    var ua = navigator.userAgent||'';
    if(/iPhone|iPad|iPod/i.test(ua)) return true;
    // iPad in UA-desktop (iPadOS 13+): Mac con touch screen.
    return /Macintosh/i.test(ua) && (navigator.maxTouchPoints||0) > 1;
  }catch(_e){ return false; }
}

// URL PRIMARIO (CTA) per aprire il job nell'app dal dispositivo stesso.
// Android: intent:// (scheme=abm) con package + fallback https. Serve perche'
// Chrome NON devia all'app una navigazione https SAME-ORIGIN
// (audiobook-maker.com -> audiobook-maker.com/t/...): regola App Links a tutela
// della navigazione web. L'intent:// bypassa la soppressione; app assente ->
// Chrome apre S.browser_fallback_url (pagina /t/ con lo store).
// iOS/altro: https (Universal Link) come CTA principale; su iOS il custom scheme
// abm:// e' offerto a parte come link secondario (vedi _appSchemeUrl).
function _appOpenUrl(token){
  var https = window.location.origin + '/t/' + encodeURIComponent(token);
  if(_isAndroidUA()){
    return 'intent://' + window.location.host + '/t/' + encodeURIComponent(token) +
           '#Intent;scheme=' + ABM_SCHEME + ';package=' + ABM_ANDROID_PKG +
           ';S.browser_fallback_url=' + encodeURIComponent(https) + ';end';
  }
  return https;
}

// Custom scheme abm://<host>/t/<token>: bypassa la soppressione same-origin di
// Safari (apre l'app anche se cliccato dentro la webapp sullo stesso dominio).
// Se l'app NON e' installata Safari mostra un errore: scelta accettata su iOS
// (bottone unico "Apri nell'app"), dove l'Universal Link same-origin sarebbe
// comunque inaffidabile.
function _appSchemeUrl(token){
  return ABM_SCHEME + '://' + window.location.host + '/t/' + encodeURIComponent(token);
}

// Su mobile ricabla il bottone dell'area transfer perche' apra il deep link
// dell'app invece del modale col QR ingrandito, e ne cambia la label:
// - Android: intent:// (apre l'app o va al sito) -> "Sposta su ..."
// - iOS: custom scheme abm:// (unico gancio affidabile) -> "Apri nell'app"
// - altro mobile: https.
function _bindTransferButtonForMobile(boxId, token){
  if(!_isMobileLike() || !token) return;
  var box = document.getElementById(boxId);
  if(!box) return;
  var btn = box.querySelector('button');
  if(!btn) return;
  var ios = _isIOSUA();
  var url = ios ? _appSchemeUrl(token) : _appOpenUrl(token);
  btn.onclick = function(){ window.location.href = url; };
  var span = btn.querySelector('[data-t]');
  if(span){
    var key = ios ? 'transfer_open_in_app' : 'transfer_cta_mobile';
    span.setAttribute('data-t', key);
    try{ if(typeof t==='function') span.textContent = t(key); }catch(_e){}
  }
}

async function _showTransferQr(jobId, imgId, boxId){
  if(!jobId) return;
  try{
    const r = await fetch('/api/transfer_qr/' + encodeURIComponent(jobId));
    if(!r.ok) return;
    const d = await r.json();
    if(d && d.qr){
      const img = document.getElementById(imgId);
      const box = document.getElementById(boxId);
      if(img){ img.src = d.qr; }
      if(box){ box.hidden = false; }
      if(d.token){ _bindTransferButtonForMobile(boxId, d.token); }
    }
  }catch(e){ /* best-effort: nessun QR, nessun errore visibile */ }
}

// Popup col QR ingrandito, aperto dal bottone "Trasferisci sull'app". Il QR e`
// gia` stato scaricato da _showTransferQr in una img nascosta (holderId); qui lo
// si mostra in grande. Stesso wrapper .modal-overlay/.modal degli altri modali,
// costruito on-demand e autodistrutto alla chiusura.
function openTransferQrModal(holderId){
  const holder=document.getElementById(holderId||'transferStartImg');
  const src=holder?holder.src:'';
  if(!src) return;
  let ttl='Transfer to the app', hint='';
  try{const x=(typeof t==='function')?t('transfer_title'):null;if(x&&x!=='transfer_title')ttl=x;}catch(_e){}
  try{const x=(typeof t==='function')?t('transfer_hint'):null;if(x&&x!=='transfer_hint')hint=x;}catch(_e){}
  const prev=document.getElementById('transferQrModal');
  if(prev&&prev.parentNode)prev.parentNode.removeChild(prev);
  const overlay=document.createElement('div');
  overlay.className='modal-overlay open';
  overlay.id='transferQrModal';
  overlay.setAttribute('role','dialog');
  overlay.setAttribute('aria-modal','true');
  const modal=document.createElement('div');
  modal.className='modal';
  modal.style.maxWidth='360px';
  modal.style.textAlign='center';
  const head=document.createElement('div');
  head.className='modal-head';
  const headSpan=document.createElement('span');
  headSpan.textContent=ttl;
  head.appendChild(headSpan);
  const closeBtn=document.createElement('button');
  closeBtn.className='modal-close';
  closeBtn.setAttribute('aria-label','Close');
  closeBtn.textContent='×';
  head.appendChild(closeBtn);
  const bodyDiv=document.createElement('div');
  bodyDiv.className='modal-body';
  const img=document.createElement('img');
  img.src=src;
  img.alt='QR';
  img.style.width='280px';
  img.style.height='280px';
  img.style.maxWidth='100%';
  img.style.display='block';
  img.style.margin='0 auto';
  bodyDiv.appendChild(img);
  if(hint){
    const p=document.createElement('p');
    p.className='muted';
    p.style.fontSize='.85rem';
    p.style.marginTop='12px';
    // Solo "AudioBook Maker & Player" e` cliccabile (verso /get-app).
    const APP='AudioBook Maker & Player';
    const a=document.createElement('a');
    a.href='/get-app';
    a.target='_blank';
    a.rel='noopener';
    a.textContent=APP;
    a.style.color='inherit';
    a.style.textDecoration='underline';
    const i=hint.indexOf(APP);
    if(i>=0){
      p.appendChild(document.createTextNode(hint.slice(0,i)));
      p.appendChild(a);
      p.appendChild(document.createTextNode(hint.slice(i+APP.length)));
    }else{
      a.textContent=hint; // fallback: tutta la riga
      p.appendChild(a);
    }
    bodyDiv.appendChild(p);
  }
  modal.appendChild(head);
  modal.appendChild(bodyDiv);
  overlay.appendChild(modal);
  const close=()=>{if(overlay.parentNode)overlay.parentNode.removeChild(overlay);};
  closeBtn.addEventListener('click',close);
  overlay.addEventListener('click',(e)=>{if(e.target===overlay)close();});
  document.body.appendChild(overlay);
}

function listenProgress(){
  let retries=0;
  const maxRetries=5;
  const myJobId=jobId;
  _ensureEmailAreaVisible();
  _updateGenNoticeWarning();
  _autoRegisterEmailFromStorage(myJobId);
  function connect(){
    const es=new EventSource('/api/progress/'+myJobId+'?lang='+encodeURIComponent(cl||'en'));
    es.onmessage=ev=>{
      retries=0;
      const d=JSON.parse(ev.data);
      if(d.status==='error'){
        es.close();
        unlockUI();
        generating=false;
        document.getElementById('cnA').style.display='none';
        try{console.log('[abm] job error payload:', d);}catch(e){}
        if(d.error_kind==='gemini_overload'){
          // Restiamo nel wizard per mostrare il modal Gemini overload;
          // no resetAll. Passiamo myJobId per evitare di chiudere modal
          // di altri job concorrenti.
          _hideJobRunningModal(false,myJobId);
          _showGeminiOverloadModal(d);
        }else{
          _hideJobRunningModal(true,myJobId);
          showPErr(d.error||'Errore');
        }
        return;
      }
      if(d.status==='cancelled'){es.close();_hideJobRunningModal(true,myJobId);document.getElementById('pMsg').textContent=t('cancelled_msg');document.getElementById('pMsg').style.color='var(--err)';document.getElementById('cnA').style.display='none';unlockUI();generating=false;_renderGeminiCancelSummary(d);return}

      const pct=d.progress_total>0?Math.round(d.progress_current/d.progress_total*100):0;
      window._sseLastProgressPct=pct;
      // Reidrata _payState dopo reload pagina: il server espone paid_eur
      // (quota gemini effettivamente pagata) nello stream SSE; senza questo,
      // il modal di cancel mostrerebbe "Importo versato: 0.00 EUR" dopo F5.
      if(typeof d.paid_eur==='number' && d.paid_eur>0 && !(_payState && _payState.gemini>0)){
        if(!_payState) _payState={total:0,gemini:0,llm:0,token:null,method:null};
        _payState.gemini=d.paid_eur;
        if(d.paid_method && !_payState.method) _payState.method=d.paid_method;
      }
      _updateGeminiCancelLockUI(pct);
      // Update both old and new progress elements
      document.getElementById('pPct').textContent=pct+'%';
      document.getElementById('pBar').style.width=pct+'%';
      document.getElementById('pMsg').textContent=d.progress_message||'';
      const progressFill=document.getElementById('progressFill');if(progressFill)progressFill.style.width=pct+'%';
      const progressPct=document.getElementById('progressPct');if(progressPct)progressPct.textContent=pct+'%';
      const progressPhase=document.getElementById('progressPhase');if(progressPhase&&d.progress_message)progressPhase.textContent=d.progress_message;
      _updateJobRunningPct(pct,myJobId);

      if(d.current_chapter)
        document.getElementById('pCh').textContent='Cap. '+d.current_chapter_num+'/'+d.total_chapters+': '+d.current_chapter.substring(0,40);
      if(d.progress_total>0)
        document.getElementById('xBlk').textContent=d.progress_current+' / '+d.progress_total;
      if(d.total_chapters>0)
        document.getElementById('xCh').textContent=d.current_chapter_num+' / '+d.total_chapters;
      if(d.elapsed_seconds>0)
        document.getElementById('xEl').textContent=fmtTime(d.elapsed_seconds);

      if(d.processed_chars>0&&d.elapsed_seconds>1&&d.total_chars>0){
        const cps=d.processed_chars/d.elapsed_seconds;
        const left=d.total_chars-d.processed_chars;
        const eta=Math.round(left/cps);
        document.getElementById('xEta').textContent=eta>0?'~'+fmtTime(eta):t('almost');
        document.getElementById('xSpd').textContent=Math.round(cps)+' '+t('cps');
      }
      if(d.bytes_generated>0)
        document.getElementById('xSz').textContent=fmtBytes(d.bytes_generated);

      let msg=d.progress_message||'';
      if(msg==="Converting to M4B..."){msg=t('converting_m4b')||msg}
      document.getElementById('pMsg').textContent=msg;

      // M4B sub-bar update
      const m4bWrap=document.getElementById('m4bProgressWrap');
      const m4bBar=document.getElementById('m4bProgressBar');
      const m4bPct=document.getElementById('m4bPct');
      const m4bMsg=document.getElementById('m4bMsg');
      if(m4bWrap&&m4bBar&&m4bPct&&m4bMsg){
        if(d.m4b_progress_total&&d.m4b_progress_total>0){
          m4bWrap.style.display='block';
          m4bBar.value=d.m4b_progress_current||0;
          m4bPct.textContent=(d.m4b_progress_current||0)+'%';
          m4bMsg.textContent=d.m4b_progress_message||'';
        }else{
          m4bWrap.style.display='none';
        }
      }

      if(d.status==='done'||d.status==='partial'){
        // 'partial' = completato con alcuni chunk saltati (oltre soglia): il
        // file è comunque prodotto e consegnato. Va trattato come stato
        // terminale, altrimenti la schermata di avanzamento resta bloccata.
        // Il ramo `d.failed_chunks>0` sotto mostra già l'avviso adeguato.
        es.close();
        generating=false;jobDone=true;
        _hideJobRunningModal(false,myJobId); // don't reset — keep jobId for download buttons
        unlockUI();
        document.getElementById('pPct').textContent='100%';
        document.getElementById('pBar').style.width='100%';
        document.getElementById('pMsg').textContent=t('done_msg');
        document.getElementById('pMsg').style.color='var(--ok)';
        const progressFill=document.getElementById('progressFill');if(progressFill)progressFill.style.width='100%';
        const progressPct=document.getElementById('progressPct');if(progressPct)progressPct.textContent='100%';
        const progressPhase=document.getElementById('progressPhase');if(progressPhase)progressPhase.textContent=t('done_t');
        const m4bWrap=document.getElementById('m4bProgressWrap');if(m4bWrap)m4bWrap.style.display='none';

        if(d.m4b_failed){
          const warn=document.createElement('div');warn.className='al al-warn';warn.style.marginTop='10px';
          warn.textContent=t('m4b_warn_mp3');document.getElementById('pra').appendChild(warn);
        }
        if(d.failed_chunks>0){
          document.getElementById('pMsg').textContent=t('done_msg')+' (⚠ '+d.failed_chunks+' chunk skipped)';
          document.getElementById('pMsg').style.color='#d97706';
        }
        document.getElementById('xEta').textContent='-';

        // Navigate to panel 5 (completion)
        _unlockStep(5);
        // Dettagli generazione: titolo libro + righe localizzate dal server
        // (stessi testi del blocco email di completamento; gen_details_html
        // è HTML server-generated con campi utente già escaped).
        const genDet=document.getElementById('genDetails');
        if(genDet){
          let h='';
          if(bookData&&bookData.title)h+='<div class="gen-details-title">'+esc(bookData.title)+'</div>';
          if(d.gen_details_html)h+='<div class="gen-details-lines">'+d.gen_details_html+'</div>';
          genDet.innerHTML=h;
          genDet.style.display=h?'':'none';
        }
        // Populate panel 5 download buttons
        const btnD=document.getElementById('btnD');
        const btnM=document.getElementById('btnM');
        const btnA=document.getElementById('btnA');
        const btnP=document.getElementById('btnP');
        const dlA=document.getElementById('dlA');
        if(dlA)dlA.style.display=''; // ensure visible (may have been hidden by goBackToChapters)
        if(btnD)btnD.style.display='none';
        if(btnM)btnM.style.display='none';
        if(btnA)btnA.style.display='none';
        if(btnP)btnP.style.display='none';
        if(outputFormat==='zip_rss'){
          // Podcast: ZIP with chapter MP3s + RSS XML — btnP is the only primary download
          if(btnP){btnP.style.display=d.has_podcast?'':'none';btnP.onclick=()=>downloadPodcastZip();}
        } else if(singleFile){
          if(btnD)btnD.style.display='';
          // Single file (M4B / MP3): btnD repurposed as primary download button
          if(btnD){
            if(outputFormat==='mp3'){
              btnD.innerHTML='<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>'+t('btn_dl_mp3')+'</span>';
              btnD.onclick=()=>downloadFile('mp3');
            } else if(d.m4b_failed && d.m4b_fallback_zip){
              // M4B fallito: offri il kit ZIP (MP3 + capitoli + script ffmpeg)
              btnD.innerHTML='&#x2B07;&#xFE0F; <span>'+t('btn_dl_m4b_kit')+'</span>';
              btnD.onclick=()=>downloadFile('m4bkit');
            } else {
              btnD.innerHTML='<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>'+t('btn_dl_m4b')+'</span>';
              btnD.onclick=()=>downloadFile('m4b');
            }
          }
        } else {
          // Chapter ZIP: btnD is the primary ZIP download
          if(btnD){
            btnD.style.display='';
            btnD.innerHTML='&#x2B07;&#xFE0F; <span>'+t('btn_dl')+'</span>';
            btnD.onclick=()=>downloadFile('zip');
          }
        }
        // ABM button (always supplementary, when optimized text is available)
        if(btnA&&d.has_abm){btnA.style.display='';btnA.onclick=()=>downloadFile('abm');}
        const btnBackCh=document.getElementById('btnBackCh');if(btnBackCh)btnBackCh.style.display=(bookData&&bookData.total_chapters>1)?'':'none';
        // Expiry info
        const expiryRow=document.getElementById('expiryRow');
        if(expiryRow&&d.expires_at){
          expiryRow.style.display='';
          const expiryInfo=document.getElementById('expiryInfo');
          if(expiryInfo){
            const expDate=new Date(d.expires_at*1000);
            expiryInfo.textContent=(t('expiry_info')||'File available until')+' '+expDate.toLocaleString();
          }
        }
        document.getElementById('cnA').style.display='none';
        goToStep(5);
        _showTransferQr(myJobId, 'transferDoneImg', 'transferDoneArea');

        // Heartbeat
        hbInterval=setInterval(()=>{if(jobId)navigator.sendBeacon('/api/heartbeat/'+jobId)},10000);
        if(jobId)navigator.sendBeacon('/api/heartbeat/'+jobId);
        document._hbVis=()=>{if(!document.hidden&&jobId&&jobDone)navigator.sendBeacon('/api/heartbeat/'+jobId)};
        document.addEventListener('visibilitychange',document._hbVis);
      }
    };
    es.onerror=()=>{
      es.close();
      if(retries<maxRetries&&generating){retries++;setTimeout(connect,retries*2000);}
    };
  }
  connect();
}

function retryGeneration(){
  document.getElementById('cnA').innerHTML='<button class="btn btn-danger" id="btnC">⏹️ '+(t('btn_cancel')||'Cancel')+'</button>';
  document.getElementById('btnC').onclick=cancelJob;
  document.querySelectorAll('#pra .ps').forEach(el=>{el.style.display=''});
  document.getElementById('pMsg').textContent='';document.getElementById('pMsg').style.color='';
  document.getElementById('pPct').textContent='0%';
  startGen();
}

// Imposta label + handler del bottone Annulla in base al contesto:
//   'opt' = ottimizzazione AI in corso  →  'Annulla ottimizzazione' / cancelOptimization
//   'gen' = generazione audio TTS       →  'Annulla' / cancelJob
function _setCancelButtonMode(mode){
  var btnC=document.getElementById('btnC');
  var btnCancelOpt=document.getElementById('btnCancelOpt');
  if(mode==='opt'){
    if(btnC)btnC.style.display='none';
    if(btnCancelOpt){btnCancelOpt.style.display='';btnCancelOpt.onclick=cancelOptimization}
  }else{
    if(btnC){btnC.style.display='';btnC.onclick=cancelJob}
    if(btnCancelOpt)btnCancelOpt.style.display='none';
  }
}

function cancelOptimization(){
  if(!jobId)return;
  try{navigator.sendBeacon('/api/cancel_optimize/'+jobId);}catch(e){}
  document.getElementById('pMsg').textContent=t('opt_cancelled')||'Optimisation cancelled';
  _setCancelButtonMode('gen');
  unlockUI();
  const genProgress=document.getElementById('generationProgress');if(genProgress)genProgress.style.display='none';
  const panel4Footer=document.getElementById('panel4Footer');if(panel4Footer)panel4Footer.style.display='';
  const genActiveNotice=document.getElementById('generationActiveNotice');if(genActiveNotice)genActiveNotice.style.display='none';
  const emailLateArea=document.getElementById('emailLateArea');if(emailLateArea)emailLateArea.classList.remove('visible');
  const aiOptCard=document.getElementById('aiOptCard');if(aiOptCard)aiOptCard.style.display='';
  const summaryBox=document.getElementById('summaryBox');if(summaryBox)summaryBox.style.display='';
  const btnGen=document.getElementById('btnGenerate');if(btnGen){btnGen.disabled=false;btnGen.innerHTML='<span data-t="btn_gen">'+t('btn_gen')+'</span>'}
  const cnA=document.getElementById('cnA');if(cnA)cnA.style.display='none';
}

// Helper: crea un modal-overlay neutro (titolo + body container + footer).
// Ritorna {root, body, footer, close(v?)} dove close rimuove l'overlay e
// (se passata) risolve la Promise associata.
function _mkCancelModal(modalId, titleText, resolveFn){
  var old=document.getElementById(modalId); if(old)old.remove();
  var ov=document.createElement('div');
  ov.id=modalId;
  ov.className='modal-overlay open';
  ov.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:9999;color:#111';
  var box=document.createElement('div');
  box.className='modal';
  box.style.cssText='max-width:520px;background:#fff;color:#111;border-radius:12px;padding:0;box-shadow:0 10px 40px rgba(0,0,0,.25)';
  var head=document.createElement('div');
  head.className='modal-head';
  head.style.cssText='padding:18px 22px 12px;border-bottom:1px solid #e5e7eb';
  var h2=document.createElement('h2');
  h2.style.cssText='margin:0;font-size:1.15em;color:#111;font-weight:700';
  h2.textContent=titleText;
  head.appendChild(h2);
  var body=document.createElement('div');
  body.className='modal-body';
  body.style.cssText='padding:14px 22px 18px;color:#111;line-height:1.5';
  var footer=document.createElement('div');
  footer.style.cssText='margin-top:18px;text-align:right';
  body.appendChild(footer);
  box.appendChild(head);
  box.appendChild(body);
  ov.appendChild(box);
  document.body.appendChild(ov);
  var settled=false;
  function close(v){
    if(settled) return;
    settled=true;
    ov.remove();
    if(resolveFn) resolveFn(v);
  }
  ov.addEventListener('click', function(ev){ if(ev.target===ov) close(false); });
  return {root:ov, body:body, footer:footer, close:close};
}

// Modal di conferma cancel per voci PREMIUM (Gemini): l'utente sta per
// rinunciare a parte dell'importo gia' versato. Promise<bool>.
function _confirmCancelGeminiModal(paid, pct){
  return new Promise(function(resolve){
    function _tf(k, fallback){var v=t(k); return (v===k||!v)?fallback:v;}
    var paidNum=Number(paid)||0;
    var pctNum=Math.max(0,Math.min(100, Math.round(Number(pct)||0)));
    var refundEst=Math.max(0, paidNum * (100 - pctNum) / 100 - 0.34);
    var m=_mkCancelModal('cancelConfirmModal',
      _tf('cancel_confirm_title','Annullare la generazione?'), resolve);
    var p=document.createElement('p');
    p.style.cssText='margin:0 0 12px;color:#1f2937';
    p.textContent=_tf('cancel_confirm_body','Stai per annullare la generazione delle voci PREMIUM. Riceverai l\'audio parziale già generato, ma una parte dell\'importo versato sarà trattenuta per coprire il costo del servizio già consumato.');
    m.body.insertBefore(p, m.footer);
    var ul=document.createElement('ul');
    ul.style.cssText='margin:0 0 12px;padding-left:8px;color:#1f2937;list-style:none';
    var lines=[
      _tf('cancel_confirm_paid','Importo versato: {paid} EUR').replace('{paid}', paidNum.toFixed(2)),
      _tf('cancel_confirm_progress','Avanzamento attuale: {pct}%').replace('{pct}', String(pctNum)),
      _tf('cancel_confirm_refund_est','Rimborso stimato: ~{refund} EUR').replace('{refund}', refundEst.toFixed(2))
    ];
    lines.forEach(function(txt){
      var li=document.createElement('li');
      li.style.cssText='margin:4px 0';
      li.textContent='• '+txt;
      ul.appendChild(li);
    });
    m.body.insertBefore(ul, m.footer);
    var btnNo=document.createElement('button');
    btnNo.className='btn';
    btnNo.style.cssText='padding:8px 16px;border-radius:8px;background:#e5e7eb;color:#111;border:none;font-weight:600;cursor:pointer;margin-right:8px';
    btnNo.textContent=_tf('cancel_confirm_no','Continua generazione');
    btnNo.addEventListener('click', function(){ m.close(false); });
    var btnYes=document.createElement('button');
    btnYes.className='btn btn-danger';
    btnYes.style.cssText='padding:8px 16px;border-radius:8px;background:#dc2626;color:#fff;border:none;font-weight:600;cursor:pointer';
    btnYes.textContent=_tf('cancel_confirm_yes','Sì, annulla');
    btnYes.addEventListener('click', function(){ m.close(true); });
    m.footer.appendChild(btnNo);
    m.footer.appendChild(btnYes);
  });
}

// Modal informativo: il server ha rifiutato il cancel perche' il job e'
// oltre la soglia di lock (ABM_GEMINI_CANCEL_LOCK_PCT).
function _showCancelLockedModal(lockPct){
  function _tf(k, fallback){var v=t(k); return (v===k||!v)?fallback:v;}
  var lockNum=Math.max(0,Math.min(100, Math.round(Number(lockPct)||70)));
  var m=_mkCancelModal('cancelLockedModal',
    _tf('cancel_locked_title','Annullamento non disponibile'), null);
  var p=document.createElement('p');
  p.style.cssText='margin:0 0 12px;color:#1f2937';
  p.textContent=_tf('cancel_locked_body','La generazione è ormai oltre il {lock}% del completamento. Per non perdere quasi tutto l\'importo versato, attendi il completamento.').replace('{lock}', String(lockNum));
  m.body.insertBefore(p, m.footer);
  var btnOk=document.createElement('button');
  btnOk.className='btn btn-primary';
  btnOk.style.cssText='padding:8px 16px;border-radius:8px;background:var(--ac,#4f46e5);color:#fff;border:none;font-weight:600;cursor:pointer';
  btnOk.textContent=_tf('news_modal_ok','Ho capito');
  btnOk.addEventListener('click', function(){ m.close(); });
  m.footer.appendChild(btnOk);
}

// Renderizza link MP3 parziale + refund summary post-cancel voci PREMIUM.
// d e' il payload SSE con campi opzionali partial_download_url e cancel_meta
// (paid_eur, retained_eur, refund_eur, progress_pct, partial_audio_delivered).
function _renderGeminiCancelSummary(d){
  if(!d || (!d.cancel_meta && !d.partial_download_url)) return;
  function _tf(k, fb){var v=t(k); return (v===k||!v)?fb:v;}
  var host=document.getElementById('pra');
  if(!host) return;
  var existing=document.getElementById('geminiCancelSummary');
  if(existing) existing.remove();
  var box=document.createElement('div');
  box.id='geminiCancelSummary';
  box.style.cssText='margin-top:18px;padding:16px;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;color:#111;max-width:560px';
  if(d.partial_download_url){
    var dlWrap=document.createElement('div');
    dlWrap.style.cssText='margin-bottom:12px;text-align:center';
    var a=document.createElement('a');
    a.href=d.partial_download_url;
    a.setAttribute('rel','noopener');
    a.style.cssText='display:inline-block;background:#8b5cf6;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600';
    a.textContent=_tf('cancel_partial_dl','Scarica audio parziale (MP3)');
    dlWrap.appendChild(a);
    box.appendChild(dlWrap);
  }
  var cm=d.cancel_meta||{};
  var paid=Number(cm.paid_eur||0).toFixed(2);
  var ret=Number(cm.retained_eur||0).toFixed(2);
  var ref=Number(cm.refund_eur||0).toFixed(2);
  var summary=document.createElement('p');
  summary.style.cssText='margin:0;color:#374151;font-size:.95em;text-align:center';
  summary.textContent=_tf('cancel_summary','Versati {paid} EUR · Trattenuti {retained} EUR · Rimborsati {refund} EUR').replace('{paid}',paid).replace('{retained}',ret).replace('{refund}',ref);
  box.appendChild(summary);
  host.appendChild(box);
}

// Disabilita il pulsante Cancel quando il job voci PREMIUM e' oltre la
// soglia client-side (default 70). La gate finale e' comunque server-side
// in /api/cancel (ABM_GEMINI_CANCEL_LOCK_PCT). Tooltip via title attribute.
var _GEMINI_CANCEL_LOCK_PCT_CLIENT = 70;
function _updateGeminiCancelLockUI(pct){
  var btnC = document.getElementById('btnC');
  if(!btnC) return;
  var voice = (typeof getCurrentVoiceId==='function') ? getCurrentVoiceId() : '';
  if(!_isGeminiVoiceId(voice)){
    if(btnC.disabled && btnC.dataset.lockedByCancelFloor==='1'){
      btnC.disabled=false;
      btnC.title='';
      delete btnC.dataset.lockedByCancelFloor;
    }
    return;
  }
  var p = Math.max(0, Math.min(100, Math.round(Number(pct)||0)));
  if(p > _GEMINI_CANCEL_LOCK_PCT_CLIENT){
    function _tf(k, fb){var v=t(k); return (v===k||!v)?fb:v;}
    btnC.disabled=true;
    btnC.dataset.lockedByCancelFloor='1';
    btnC.title=_tf('cancel_locked_body','La generazione è ormai oltre il {lock}% del completamento.').replace('{lock}', String(_GEMINI_CANCEL_LOCK_PCT_CLIENT));
  } else if(btnC.dataset.lockedByCancelFloor==='1'){
    btnC.disabled=false;
    btnC.title='';
    delete btnC.dataset.lockedByCancelFloor;
  }
}

function _completeCancelUI(){
  generating=false;
  unlockUI();
  const genProgress=document.getElementById('generationProgress');if(genProgress)genProgress.style.display='none';
  const panel4Footer=document.getElementById('panel4Footer');if(panel4Footer)panel4Footer.style.display='';
  const genActiveNotice=document.getElementById('generationActiveNotice');if(genActiveNotice)genActiveNotice.style.display='none';
  const emailLateArea=document.getElementById('emailLateArea');if(emailLateArea)emailLateArea.classList.remove('visible');
  const aiOptCard2=document.getElementById('aiOptCard');if(aiOptCard2)aiOptCard2.style.display='';
  const summaryBox2=document.getElementById('summaryBox');if(summaryBox2)summaryBox2.style.display='';
  document.getElementById('pBar').style.width='0%';document.getElementById('pPct').textContent='0%';
  const progressFill=document.getElementById('progressFill');if(progressFill)progressFill.style.width='0%';
  const progressPct=document.getElementById('progressPct');if(progressPct)progressPct.textContent='0%';
  ['xBlk','xCh','xEl','xEta','xSz','xSpd'].forEach(id=>{const el=document.getElementById(id);if(el)el.textContent='—'});
  document.getElementById('pMsg').textContent='';document.getElementById('pMsg').style.color='';
  document.querySelectorAll('#pra .ps').forEach(el=>{el.style.display=''});
  const btnGen=document.getElementById('btnGenerate');if(btnGen){btnGen.disabled=false;const sp=document.createElement('span');sp.setAttribute('data-t','btn_gen');sp.textContent=t('btn_gen');btnGen.replaceChildren(sp);}
  const cnA=document.getElementById('cnA');if(cnA)cnA.style.display='none';
  updateSelection();
}

function cancelJob(){
  if(!jobId||!generating)return;
  var voice=(typeof getCurrentVoiceId==='function')?getCurrentVoiceId():'';
  if(_isGeminiVoiceId(voice)){
    // Snapshot autoritativo dal server: paid_eur viene letto da
    // job.payment.total_eur (stessa fonte usata dal refund handler).
    // Evita race condition con SSE quando l'utente fa F5 e clicca cancel
    // prima che arrivi il primo evento progress (con _payState.gemini
    // ancora a 0 -> modal mostrava "Importo versato: 0.00 EUR").
    var paidFallback=(window._payState && _payState.gemini) ? Number(_payState.gemini)||0 : 0;
    var pctFallback=Number(window._sseLastProgressPct||0);
    fetch('/api/cancel_preview/'+jobId,{credentials:'same-origin'}).then(function(r){
      return r.ok ? r.json() : null;
    }).catch(function(){return null;}).then(function(d){
      if(d && d.locked){
        _showCancelLockedModal(Number(d.lock_pct)||70);
        return;
      }
      var paid=d && typeof d.paid_eur==='number' ? d.paid_eur : paidFallback;
      var pct=d && typeof d.progress_pct==='number' ? d.progress_pct : pctFallback;
      _confirmCancelGeminiModal(paid, pct).then(function(yes){
        if(!yes) return;
        // force=1: il modale di conferma è già un'azione esplicita dell'utente,
        // by-passa la guardia server email_registered (che resta attiva solo per
        // l'unload implicito della pagina).
        fetch('/api/cancel/'+jobId+'?force=1',{method:'POST',credentials:'same-origin'}).then(function(r){
          if(r.status===409){
            return r.json().then(function(d){
              _showCancelLockedModal((d&&d.lock_pct)||70);
              return null;
            });
          }
          _completeCancelUI();
          return null;
        }).catch(function(){
          try{navigator.sendBeacon('/api/cancel/'+jobId+'?force=1');}catch(e){}
          _completeCancelUI();
        });
      });
    });
    return;
  }
  navigator.sendBeacon('/api/cancel/'+jobId+'?force=1');
  _completeCancelUI();
}

function retryGen(){retryGeneration()}

function _fmtBytes(n){
  if(!n||n<1024)return (n||0)+' B';
  if(n<1048576)return (n/1024).toFixed(0)+' KB';
  return (n/1048576).toFixed(1)+' MB';
}
function _setBtnLoading(btn,labelHtml){
  if(!btn)return;
  btn.disabled=true;
  btn.classList.add('btn-loading');
  btn.innerHTML='<span>'+labelHtml+'</span>';
}
function _clearBtnLoading(btn,html){
  if(!btn)return;
  btn.classList.remove('btn-loading');
  btn.disabled=false;
  if(html!==undefined)btn.innerHTML=html;
}
// Top-of-page transient toast for download start (matches /dl/<token> page UX).
let _dlToastEl=null,_dlToastTimer=null;
function _showDlToast(msg){
  if(!_dlToastEl){
    _dlToastEl=document.createElement('div');
    _dlToastEl.className='dl-toast';
    document.body.appendChild(_dlToastEl);
  }
  _dlToastEl.innerHTML='<span class="spin"></span>'+msg;
  requestAnimationFrame(()=>_dlToastEl.classList.add('show'));
  clearTimeout(_dlToastTimer);
  _dlToastTimer=setTimeout(()=>{if(_dlToastEl)_dlToastEl.classList.remove('show')},6500);
}
function _hideDlToast(){
  clearTimeout(_dlToastTimer);
  if(_dlToastEl)_dlToastEl.classList.remove('show');
}
async function _streamToBlob(response,onProgress){
  const cl=parseInt(response.headers.get('Content-Length')||'0',10);
  if(!response.body||!response.body.getReader){
    return await response.blob();
  }
  const reader=response.body.getReader();
  const chunks=[];
  let received=0;
  while(true){
    const{done,value}=await reader.read();
    if(done)break;
    chunks.push(value);
    received+=value.length;
    if(onProgress){
      try{onProgress(received,cl)}catch(_e){}
    }
  }
  const type=response.headers.get('Content-Type')||'application/octet-stream';
  return new Blob(chunks,{type});
}

async function downloadFile(type){
  if(!jobId)return;
  // Bottone su cui mostrare spinner/disable durante il download. In modalita'
  // M4B/MP3/ZIP/kit il bottone primario VISIBILE e' btnD (btnM resta sempre
  // display:none, vedi panel 5). Mappare 'm4b' a btnM applicava lo spinner a
  // un bottone nascosto, lasciando btnD cliccabile (doppio download) e senza
  // feedback. Solo 'abm' usa il bottone supplementare btnA.
  const btnId = (type === 'abm') ? 'btnA' : 'btnD';

  const btn=document.getElementById(btnId);
  const originalHtml = btn.innerHTML;
  _setBtnLoading(btn,t('dl_preparing')||'Preparing…');
  _showDlToast(t('dl_hint')||'The download will start shortly. Large files may take a few seconds.');
  const maxDlRetries=3;
  for(let attempt=1;attempt<=maxDlRetries;attempt++){
    try{
      navigator.sendBeacon('/api/heartbeat/'+jobId);
      const r=await fetch('/api/download/'+jobId + (type ? '?type='+type : ''));
      if(r.status===404){
        if(attempt<maxDlRetries){await new Promise(ok=>setTimeout(ok,1500));continue}
        showPErr(t('dl_expired')||'File non più disponibile. Riconverti il libro.');
        _clearBtnLoading(btn,originalHtml);
        return;
      }
      if(r.status===429){
        const txt=await r.text();
        const m=txt.match(/Wait (\d+) seconds/);
        const sec=m?m[1]:'60';
        showPErr(t('dl_cooldown').replace('%s', sec));
        _clearBtnLoading(btn,originalHtml);
        return;
      }
      if(r.status===410){
        showPErr(t('dl_deleted')||'File removed after too many downloads. Please reconvert the book.');
        _clearBtnLoading(btn,originalHtml);
        return;
      }
      if(!r.ok){
        const txt=await r.text();
        showPErr(txt||'Download failed');
        _clearBtnLoading(btn,originalHtml);
        return;
      }
      const isLastDl=(r.headers.get('X-Download-Last')==='1');
      // Se il server ha fatto fallback (es. M4B non disponibile → MP3), il client
      // deve trattare la risposta come del tipo effettivamente servito, non come
      // quello richiesto: altrimenti il safety net qui sotto aggiungerebbe una
      // seconda estensione (es. "X.mp3.m4b") al filename già corretto.
      const fallbackKind=(r.headers.get('X-Fallback')||'').toLowerCase();
      const effectiveType=fallbackKind || type;
      const dlLabel=t('dl_downloading')||'Downloading…';
      const blob=await _streamToBlob(r,(rx,total)=>{
        if(total>0){
          const pct=Math.min(100,Math.floor(rx*100/total));
          btn.innerHTML='<span>'+dlLabel+' '+pct+'%</span>';
        }else{
          btn.innerHTML='<span>'+dlLabel+' '+_fmtBytes(rx)+'</span>';
        }
      });
      const cd=r.headers.get('Content-Disposition')||'';
      // Parse Content-Disposition robustly: RFC 5987 filename*=, quoted filename="...", or bare filename=foo.
      // The previous regex stopped at apostrophes, truncating titles like "L'isola" and losing the extension.
      let fname='';
      let mm=cd.match(/filename\*\s*=\s*[^']+''([^;\n]+)/i);
      if(mm){try{fname=decodeURIComponent(mm[1].trim())}catch(e){fname=''}}
      if(!fname){mm=cd.match(/filename\s*=\s*"([^"]+)"/i);if(mm)fname=mm[1]}
      if(!fname){mm=cd.match(/filename\s*=\s*([^;\n]+)/i);if(mm)fname=mm[1].trim()}
      let defName = 'audiobook.zip';
      if(effectiveType === 'm4b') defName = 'audiobook.m4b';
      if(effectiveType === 'abm') defName = 'project.abm';
      if(effectiveType === 'mp3') defName = 'audiobook.mp3';
      if(effectiveType === 'm4bkit') defName = 'audiobook.zip';
      if(!fname) fname=defName;
      // Safety net: enforce the expected extension if the parsed filename is missing it.
      const extByType={zip:'.zip',m4b:'.m4b',mp3:'.mp3',abm:'.abm',m4bkit:'.zip'};
      const expectedExt=extByType[effectiveType];
      if(expectedExt && !fname.toLowerCase().endsWith(expectedExt)) fname += expectedExt;

      const a=document.createElement('a');
      a.href=URL.createObjectURL(blob);
      a.download=fname;
      document.body.appendChild(a);a.click();
      setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},1000);
      
      let successT = t('btn_dl');
      if(type === 'm4b') successT = t('btn_dl_m4b');
      if(type === 'abm') successT = t('btn_dl_abm');
      if(type === 'mp3') successT = t('btn_dl_mp3');
      if(type === 'm4bkit') successT = t('btn_dl_m4b_kit');
      _clearBtnLoading(btn,'✅ <span>'+successT+'</span>');
      if(isLastDl)showDlLastWarning();
      return;
    }catch(e){
      if(attempt<maxDlRetries){await new Promise(ok=>setTimeout(ok,1500));continue}
      showPErr('Download error: '+e.message);
      _clearBtnLoading(btn,originalHtml);
    }
  }
}

async function downloadPodcast(){
  if(!jobId)return;
  const baseUrl=prompt(t('podcast_url_prompt'),'https://example.com/podcast');
  if(!baseUrl)return;
  const btn=document.getElementById('btnP');
  const restoreHtml='🎙️ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';
  _setBtnLoading(btn,t('dl_preparing')||'Preparing…');
  _showDlToast(t('dl_hint')||'The download will start shortly. Large files may take a few seconds.');
  try{
    navigator.sendBeacon('/api/heartbeat/'+jobId);
    const r=await fetch('/api/download_podcast/'+jobId+'?base_url='+encodeURIComponent(baseUrl));
    if(r.status===429){
      const txt=await r.text();
      const m=txt.match(/Wait (\d+) seconds/);
      const sec=m?m[1]:'60';
      showPErr(t('dl_cooldown').replace('%s', sec));
      _clearBtnLoading(btn,restoreHtml);
      return;
    }
    if(r.status===410){
      showPErr(t('dl_deleted')||'File removed after too many downloads. Please reconvert the book.');
      _clearBtnLoading(btn,restoreHtml);
      return;
    }
    if(!r.ok){
      const txt=await r.text();
      showPErr(txt||'Download failed');
      _clearBtnLoading(btn,restoreHtml);
      return;
    }
    const isLastDl=(r.headers.get('X-Download-Last')==='1');
    const dlLabel=t('dl_downloading')||'Downloading…';
    const blob=await _streamToBlob(r,(rx,total)=>{
      if(total>0){
        const pct=Math.min(100,Math.floor(rx*100/total));
        btn.innerHTML='<span>'+dlLabel+' '+pct+'%</span>';
      }else{
        btn.innerHTML='<span>'+dlLabel+' '+_fmtBytes(rx)+'</span>';
      }
    });
    const cd=r.headers.get('Content-Disposition')||'';
    const m=cd.match(/filename[^;=\n]*=['"]?([^'";\n]*)/);
    const fname=m?m[1]:'podcast.zip';
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download=fname;
    document.body.appendChild(a);a.click();
    setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},1000);
    _clearBtnLoading(btn,'✅ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>');
    if(isLastDl)showDlLastWarning();
  }catch(e){
    showPErr('Download error: '+e.message);
    _clearBtnLoading(btn,restoreHtml);
  }
}

async function downloadPodcastZip(){
  if(!jobId)return;
  const btn=document.getElementById('btnP');
  const restoreHtml='🎙️ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';
  _setBtnLoading(btn,t('dl_preparing')||'Preparing…');
  _showDlToast(t('dl_hint')||'The download will start shortly. Large files may take a few seconds.');
  try{
    navigator.sendBeacon('/api/heartbeat/'+jobId);
    const r=await fetch('/api/download_podcast/'+jobId+(podcastBaseUrl?'?base_url='+encodeURIComponent(podcastBaseUrl):''));
    if(r.status===429){const txt=await r.text();const m=txt.match(/Wait (\d+) seconds/);const sec=m?m[1]:'60';showPErr(t('dl_cooldown').replace('%s', sec));_clearBtnLoading(btn,restoreHtml);return}
    if(r.status===410){showPErr(t('dl_deleted')||'File removed after too many downloads. Please reconvert the book.');_clearBtnLoading(btn,restoreHtml);return}
    if(!r.ok){const tx=await r.text();showPErr(tx||'Download failed');_clearBtnLoading(btn,restoreHtml);return}
    const isLastDl=(r.headers.get('X-Download-Last')==='1');
    const dlLabel=t('dl_downloading')||'Downloading…';
    const blob=await _streamToBlob(r,(rx,total)=>{
      if(total>0){
        const pct=Math.min(100,Math.floor(rx*100/total));
        btn.innerHTML='<span>'+dlLabel+' '+pct+'%</span>';
      }else{
        btn.innerHTML='<span>'+dlLabel+' '+_fmtBytes(rx)+'</span>';
      }
    });
    const cd=r.headers.get('Content-Disposition')||'';
    const m=cd.match(/filename[^;=\n]*=['\"]?([^'\";\n]*)/);
    const fname=m?m[1]:'podcast.zip';
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);a.download=fname;
    document.body.appendChild(a);a.click();
    setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},1000);
    _clearBtnLoading(btn,'✅ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>');
    if(isLastDl)showDlLastWarning();
  }catch(e){
    showPErr('Download error: '+e.message);
    _clearBtnLoading(btn,restoreHtml);
  }
}

function onBeforeUnload(e){
  if(generating&&!jobDone&&jobId&&!emailRegistered){
    // Cancel solo se la generazione è in corso E l'utente NON ha registrato email
    navigator.sendBeacon('/api/cancel/'+jobId);
  }
}

async function goBackToChapters(){
  if(!jobId||!bookData)return;
  _stopAnalyzedHeartbeat();
  if(hbInterval){clearInterval(hbInterval);hbInterval=null}
  if(document._hbVis){document.removeEventListener('visibilitychange',document._hbVis);document._hbVis=null}
  try{await fetch('/api/reset_to_chapters/'+jobId,{method:'POST'})}catch(e){console.warn('[goBack] reset failed:',e)}
  jobDone=false;generating=false;
  emailRegistered=false;
  // Reset chapter selection — uncheck all
  _getAllCheckboxes().forEach(cb=>{cb.checked=false});
  // Reset AI optimization state (keep optimizedChapters so previously optimized chapters remain tracked)
  aiOptEnabled=false;
  const aiToggle=document.getElementById('aiToggle');if(aiToggle){aiToggle.checked=false;aiToggle.disabled=false}
  const aiOptInfo=document.getElementById('aiOptInfo');if(aiOptInfo)aiOptInfo.style.display='none';
  const aiAlreadyOpt=document.getElementById('aiAlreadyOpt');if(aiAlreadyOpt)aiAlreadyOpt.style.display='none';
  const costEstimate=document.getElementById('costEstimate');if(costEstimate)costEstimate.classList.remove('visible');
  _updateAiOptCard();
  // Hide generation/download UI
  const dlA=document.getElementById('dlA');if(dlA)dlA.style.display='none';
  const genDet=document.getElementById('genDetails');if(genDet){genDet.style.display='none';genDet.innerHTML='';}
  ['transferStartArea','transferDoneArea'].forEach(function(id){var b=document.getElementById(id);if(b)b.hidden=true;});
  ['transferStartImg','transferDoneImg'].forEach(function(id){var im=document.getElementById(id);if(im)im.src='';});
  const btnD=document.getElementById('btnD');if(btnD){btnD.style.display='none';btnD.innerHTML='&#x2B07;&#xFE0F; <span data-t="btn_dl">'+t('btn_dl')+'</span>';}
  const btnM=document.getElementById('btnM');if(btnM)btnM.style.display='none';
  const btnA=document.getElementById('btnA');if(btnA)btnA.style.display='none';
  const btnP=document.getElementById('btnP');if(btnP)btnP.style.display='none';
  const dlLastNotice=document.getElementById('dlLastNotice');if(dlLastNotice)dlLastNotice.style.display='none';
  const btnBackCh=document.getElementById('btnBackCh');if(btnBackCh)btnBackCh.style.display='none';
  const genProgress=document.getElementById('generationProgress');if(genProgress)genProgress.style.display='none';
  const panel4Footer=document.getElementById('panel4Footer');if(panel4Footer)panel4Footer.style.display='';
  _resetEmailLateArea();
  const btnGenGoBack=document.getElementById('btnGenerate');if(btnGenGoBack){btnGenGoBack.disabled=false;btnGenGoBack.innerHTML='<span data-t="btn_gen">'+t('btn_gen')+'</span>'}
  document.getElementById('pMsg').style.color='';
  ['xBlk','xCh','xEl','xEta','xSz','xSpd'].forEach(id=>{const el=document.getElementById(id);if(el)el.textContent='—'});
  document.getElementById('pBar').style.width='0%';document.getElementById('pPct').textContent='0%';
  // Reset wizard progress
  const progressFill=document.getElementById('progressFill');if(progressFill)progressFill.style.width='0%';
  const progressPct=document.getElementById('progressPct');if(progressPct)progressPct.textContent='0%';
  const progressPhase=document.getElementById('progressPhase');if(progressPhase)progressPhase.textContent='—';
  const cnA=document.getElementById('cnA');if(cnA)cnA.style.display='none';
  const genActiveNotice=document.getElementById('generationActiveNotice');if(genActiveNotice)genActiveNotice.style.display='none';
  const aiOptCard=document.getElementById('aiOptCard');if(aiOptCard)aiOptCard.style.display='';
  const summaryBox=document.getElementById('summaryBox');if(summaryBox)summaryBox.style.display='';
  const expiryRow=document.getElementById('expiryRow');if(expiryRow)expiryRow.style.display='none';
  unlockUI();
  updateSelection();_updatePreviewBtn();_updateSummary();
  goToStep(2);
}

function _startAnalyzedHeartbeat(){
  if(_analyzedHbInterval)clearInterval(_analyzedHbInterval);
  _analyzedHbInterval=setInterval(()=>{if(jobId)navigator.sendBeacon('/api/heartbeat/'+jobId)},25000);
}
function _stopAnalyzedHeartbeat(){
  if(_analyzedHbInterval){clearInterval(_analyzedHbInterval);_analyzedHbInterval=null}
}
function resetAll(){
  _stopAnalyzedHeartbeat();
  if(hbInterval){clearInterval(hbInterval);hbInterval=null}
  if(document._hbVis){document.removeEventListener('visibilitychange',document._hbVis);document._hbVis=null}
  generating=false;jobDone=false;
  wizMode='audio';trPaymentToken=null;trEstimate=null;trEmailRegistered=false;
  unlockUI();
  _wizStep=1;_wizMaxStep=1;
  updateWizardSteps(1);
  const panels=document.querySelectorAll('.panel');
  panels.forEach(p=>p.classList.remove('active'));
  const panel1=document.getElementById('panel1');if(panel1)panel1.classList.add('active');
  document.getElementById('uz').classList.remove('ok');
  document.getElementById('ufn').style.display='none';
  document.getElementById('fi').value='';
  const chl=document.getElementById('chl');if(chl)chl.innerHTML='';
  const chapterRows=document.getElementById('chapterRows');if(chapterRows)chapterRows.innerHTML='';
  document.getElementById('s3err').innerHTML='';
  const selBar=document.getElementById('selBar');if(selBar)selBar.classList.remove('vis');
  singleFile=true;isTxtFile=false;outputFormat='m4b';podcastBaseUrl='';
  _applyOutputOptionsForType(false);
  document.getElementById('fgOut').style.display='';
  const _vOutR=document.getElementById('vOut');if(_vOutR){_vOutR.value='m4b';onOutputChange();}
  previewStop();
  bookData=null;jobId=null;
  emailRegistered=false;previewListened=false;
  _currentPreviewSig=null;_knownPreviewSigs.clear();
  ['bkCover','s4bkCover'].forEach(id=>{var el=document.getElementById(id);if(el){el.style.display='none';el.src=''}});
  const coverPlaceholder=document.getElementById('coverPlaceholder');if(coverPlaceholder)coverPlaceholder.style.display='';
  // Reset wizard generation UI
  const genProgress=document.getElementById('generationProgress');if(genProgress)genProgress.style.display='none';
  const panel4Footer=document.getElementById('panel4Footer');if(panel4Footer)panel4Footer.style.display='';
  const genActiveNotice=document.getElementById('generationActiveNotice');if(genActiveNotice)genActiveNotice.style.display='none';
  _resetEmailLateArea();
  // Reset translate (panel T3/T4) UI
  const trOutName=document.getElementById('trOutName');if(trOutName)trOutName.value='';
  trAutoOutName='';
  trPaymentToken=null;
  const aiToggleTr=document.getElementById('aiToggleTr');if(aiToggleTr)aiToggleTr.checked=false;
  const trErr=document.getElementById('trErr');if(trErr)trErr.innerHTML='';
  const trErr4=document.getElementById('trErr4');if(trErr4)trErr4.innerHTML='';
  const _bcReset=document.getElementById('btnCancelTr');
  if(_bcReset){const _spReset=_bcReset.querySelector('span');if(_spReset)_spReset.textContent=t('tr_btn_cancel')||'Cancel';_bcReset.onclick=cancelTranslation;}
  const trProgressFill=document.getElementById('trProgressFill');if(trProgressFill)trProgressFill.style.width='0%';
  const trProgressPct=document.getElementById('trProgressPct');if(trProgressPct)trProgressPct.textContent='0%';
  const trProgressPhase=document.getElementById('trProgressPhase');if(trProgressPhase)trProgressPhase.textContent='—';
  const emailLateAreaTr=document.getElementById('emailLateAreaTr');if(emailLateAreaTr)emailLateAreaTr.classList.remove('visible');
  const notifyEmailLateTr=document.getElementById('notifyEmailLateTr');if(notifyEmailLateTr)notifyEmailLateTr.value='';
  const btnTrAdopt=document.getElementById('btnTrAdopt');if(btnTrAdopt)btnTrAdopt.style.display='none';
  const cnA=document.getElementById('cnA');if(cnA)cnA.style.display='none';
  const btnGen=document.getElementById('btnGenerate');if(btnGen){btnGen.disabled=false;btnGen.innerHTML='<span data-t="btn_gen">'+t('btn_gen')+'</span>'}
  const dlA=document.getElementById('dlA');if(dlA)dlA.style.display='none';
  const genDet=document.getElementById('genDetails');if(genDet){genDet.style.display='none';genDet.innerHTML='';}
  ['transferStartArea','transferDoneArea'].forEach(function(id){var b=document.getElementById(id);if(b)b.hidden=true;});
  ['transferStartImg','transferDoneImg'].forEach(function(id){var im=document.getElementById(id);if(im)im.src='';});
  const btnD=document.getElementById('btnD');if(btnD){btnD.style.display='none';btnD.innerHTML='&#x2B07;&#xFE0F; <span data-t="btn_dl">'+t('btn_dl')+'</span>';}
  const btnM=document.getElementById('btnM');if(btnM)btnM.style.display='none';
  const btnA=document.getElementById('btnA');if(btnA)btnA.style.display='none';
  const btnP=document.getElementById('btnP');if(btnP)btnP.style.display='none';
  const dlLastNotice=document.getElementById('dlLastNotice');if(dlLastNotice)dlLastNotice.style.display='none';
  const btnBackCh=document.getElementById('btnBackCh');if(btnBackCh)btnBackCh.style.display='none';
  // Reset AI toggle
  const aiToggle=document.getElementById('aiToggle');if(aiToggle){aiToggle.checked=false;aiToggle.disabled=false}
  aiOptEnabled=false;optimizedChapters=[];
  const aiOptCard3=document.getElementById('aiOptCard');if(aiOptCard3){aiOptCard3.classList.remove('enabled');aiOptCard3.style.display='';}
  const summaryBox3=document.getElementById('summaryBox');if(summaryBox3)summaryBox3.style.display='';
  const aiOptInfo=document.getElementById('aiOptInfo');if(aiOptInfo)aiOptInfo.style.display='none';
  const aiAlreadyOpt=document.getElementById('aiAlreadyOpt');if(aiAlreadyOpt)aiAlreadyOpt.style.display='none';
  const costEstimate=document.getElementById('costEstimate');if(costEstimate)costEstimate.classList.remove('visible');
  // Reset old progress
  document.getElementById('pBar').style.width='0%';document.getElementById('pPct').textContent='0%';
  document.getElementById('pMsg').style.color='';
  ['xBlk','xCh','xEl','xEta','xSz','xSpd'].forEach(id=>{const el=document.getElementById(id);if(el)el.textContent='—'});
  // Reset wizard progress
  const progressFill=document.getElementById('progressFill');if(progressFill)progressFill.style.width='0%';
  const progressPct=document.getElementById('progressPct');if(progressPct)progressPct.textContent='0%';
  const progressPhase=document.getElementById('progressPhase');if(progressPhase)progressPhase.textContent='—';
  // Reset book info
  document.getElementById('bkT').textContent='';document.getElementById('bkA').textContent='';
  const bookChCount=document.getElementById('bookChCount');if(bookChCount)bookChCount.textContent='—';
  const bookTotalChars=document.getElementById('bookTotalChars');if(bookTotalChars)bookTotalChars.textContent='—';
  const bookLangEl=document.getElementById('bookLang');if(bookLangEl)bookLangEl.textContent='—';
  const selCnt=document.getElementById('selCnt');if(selCnt)selCnt.textContent='0';
  const selectedCount=document.getElementById('selectedCount');if(selectedCount)selectedCount.innerHTML='<b>0</b> <span data-t="sel_selected">'+t('sel_selected')+'</span>';
  // Reset summary
  const sumCh=document.getElementById('summaryChapters');if(sumCh)sumCh.textContent='—';
  const sumVoice=document.getElementById('summaryVoice');if(sumVoice)sumVoice.textContent='—';
  const sumFormat=document.getElementById('summaryFormat');if(sumFormat)sumFormat.textContent='—';
  const sumAI=document.getElementById('summaryAI');if(sumAI)sumAI.textContent='—';
  const expiryRow=document.getElementById('expiryRow');if(expiryRow)expiryRow.style.display='none';
  applyI18n();
  window.scrollTo({top:0,behavior:'smooth'});
}

// ═══════════════════ WIZARD HELPERS ═══════════════════
function confirmReset(){
  if(generating){if(!confirm(t('confirm_reset_warn')||'Generation in progress. Are you sure?'))return}
  resetAll();
}

// showCoupon()/validateCoupon() rimossi: il prepagamento voucher al toggle è
// stato sostituito dal pagamento al Generate col modal condiviso Buono/PayPal
// (_showPaymentModal). UI coupon inline (couponRow) rimossa dal markup.

function _ensureEmailAreaVisible(){
  // Safety net: garantisce che l'area email sia visibile anche se
  // _showWizProgress() non ha potuto eseguire (es. DOM mancante).
  const genProgress=document.getElementById('generationProgress');
  if(genProgress&&genProgress.style.display==='none')genProgress.style.display='';
  const emailArea=document.getElementById('emailLateArea');
  if(emailArea&&!emailArea.classList.contains('visible'))emailArea.classList.add('visible');
}

function _updateGenNoticeWarning(){
  _ensureEmailAreaVisible();
  const notice=document.getElementById('generationActiveNotice');
  const txt=document.getElementById('genActiveNoticeText');
  if(!notice||!txt)return;
  if(emailRegistered){
    // Email recepita: il banner di avviso è fuorviante (la conferma verde
    // sotto la progress bar comunica già lo stato safe). Nascondiamo il
    // banner ATTENZIONE per evitare il messaggio contraddittorio.
    notice.classList.remove('warn');
    notice.style.display='none';
  }else{
    notice.style.display='';
    notice.classList.add('warn');
    const w=t('gen_active_notice_warn');
    if(w)txt.textContent=w;
  }
}

let _emailLateAreaHTML=null;
function _setEmailLateConfirm(area,msg){
  if(!area)return;
  // Salva il markup originale (input+bottone, gia' i18n-izzato) prima di
  // distruggerlo: serve a _resetEmailLateArea() per ripristinare il campo
  // alla generazione successiva nella stessa sessione.
  if(_emailLateAreaHTML===null&&area.querySelector('#notifyEmailLate'))_emailLateAreaHTML=area.innerHTML;
  while(area.firstChild)area.removeChild(area.firstChild);
  const span=document.createElement('span');
  span.style.color='var(--ok)';
  span.style.fontSize='.84rem';
  span.textContent=msg;
  area.appendChild(span);
}

function _resetEmailLateArea(){
  // Ripristina lo stato iniziale dell'area email tra una generazione e la
  // successiva: rimuove la conferma verde stantia ("Email recepita") del job
  // precedente e ricostruisce input+bottone distrutti da _setEmailLateConfirm.
  // Nasconde anche il banner auto-batch del job precedente.
  const area=document.getElementById('emailLateArea');
  if(area){
    area.classList.remove('visible');
    if(!area.querySelector('#notifyEmailLate')&&_emailLateAreaHTML!==null){
      area.innerHTML=_emailLateAreaHTML;
      const input=document.getElementById('notifyEmailLate');
      if(input)input.value='';
    }
  }
  // Riattiva input e bottone eventualmente disabilitati dall'auto-batch del job
  // precedente (_lockEmailLateBoxAutoBatch), cosi' il job successivo riparte con
  // il box modificabile.
  const inp=document.getElementById('notifyEmailLate');
  if(inp){inp.disabled=false;inp.readOnly=false;inp.value='';}
  const sb=document.getElementById('btnSubmitEmailLate');
  if(sb)sb.disabled=false;
  const abn=document.getElementById('autoBatchNotice');
  if(abn)abn.style.display='none';
}

async function _autoRegisterEmailFromStorage(myJobId){
  // Pre-popola il campo di notifica con l'email del voucher (o un'email
  // gia' usata in passato) ma NON la registra: la conferma deve essere
  // esplicita via pulsante. Evita di "ereditare" silenziosamente l'email
  // del buono per la notifica, quando l'utente potrebbe volerla diversa.
  if(emailRegistered)return false;
  let stored='';
  try{stored=(localStorage.getItem('abm_v_email')||'').trim();}catch(e){}
  if(!stored||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(stored))return false;
  const input=document.getElementById('notifyEmailLate');
  if(input&&!input.value)input.value=stored;
  return false;
}

async function submitEmailLate(){
  const email=(document.getElementById('notifyEmailLate').value||'').trim();
  if(!email||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))return;
  lastVoucherEmail=email;try{localStorage.setItem('abm_v_email',email)}catch(e){}
  try{
    const dlType=(outputFormat==='zip_rss')?'podcast':(singleFile?'audio':'chapters');
    const latePayload={job_id:jobId,email:email,download_type:dlType,lang:cl};
    if(dlType==='podcast'){const urlInput=document.getElementById('podcastUrlInput');latePayload.base_url=urlInput?urlInput.value.trim():'';}
    const r=await fetch('/api/register_email',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(latePayload)});
    const d=await r.json();
    if(d.error){alert(d.error);return}
    emailRegistered=true;
    const noticeEl=document.getElementById('genActiveNoticeText');
    if(noticeEl&&t('gen_active_notice_email'))noticeEl.textContent=t('gen_active_notice_email').replace('{0}',email);
    const area=document.getElementById('emailLateArea');
    _setEmailLateConfirm(area,'✅ '+(t('email_late_ok')||'Email registered!'));
    _updateGenNoticeWarning();
  }catch(e){alert('Error: '+e.message)}
}

// ═══════════════════ HELPERS ═══════════════════
function fmtDur(m){if(m<1)return'< 1 min';if(m<60)return Math.round(m)+' min';const h=Math.floor(m/60);const r=Math.round(m%60);return h+'h '+(r>0?r+'min':'')}
function fmtTime(s){if(s<60)return s+'s';const m=Math.floor(s/60);const r=s%60;if(m<60)return m+'m'+(r>0?' '+r+'s':'');return Math.floor(m/60)+'h '+(m%60>0?(m%60)+'m':'')}
function fmtBytes(b){if(b<1024)return b+' B';if(b<1048576)return(b/1024).toFixed(0)+' KB';return(b/1048576).toFixed(1)+' MB'}
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function showErr(id,m){document.getElementById(id).innerHTML='<div class="al al-e fi">'+esc(m)+'</div>'}
function showPErr(m){document.getElementById('pra').innerHTML='<div class="al al-e fi">'+esc(m)+'</div>'}

function showDlLastWarning(){
  const el=document.getElementById('dlLastNotice');
  if(!el)return;
  const titleEl=el.querySelector('[data-t="dl_last_title"]');
  const bodyEl=el.querySelector('[data-t="dl_last_body"]');
  if(titleEl)titleEl.textContent=t('dl_last_title')||'Ultimo download disponibile';
  if(bodyEl)bodyEl.textContent=t('dl_last_body')||'Questo era l’ultimo download consentito per questo file. Il file verrà rimosso dal server e i prossimi tentativi falliranno: salva subito una copia.';
  el.style.display='';
  try{el.scrollIntoView({behavior:'smooth',block:'nearest'})}catch(e){}
}

// ═══════════════════ SOCIAL SHARE ═══════════════════
const SHARE_URL='https://audiobook-maker.com';
function _shareText(){return t('share_text')+' '+SHARE_URL}
function updateShareLinks(){
  var txt=encodeURIComponent(t('share_text'));
  var url=encodeURIComponent(SHARE_URL);
  var full=encodeURIComponent(t('share_text')+' '+SHARE_URL);
  var el;
  el=document.getElementById('shX');if(el)el.href='https://x.com/intent/tweet?text='+txt+'&url='+url;
  el=document.getElementById('shFb');if(el)el.href='https://www.facebook.com/sharer/sharer.php?u='+url;
  el=document.getElementById('shWa');if(el)el.href='https://wa.me/?text='+full;
  el=document.getElementById('shTg');if(el)el.href='https://t.me/share/url?url='+url+'&text='+txt;
  el=document.getElementById('shLi');if(el)el.href='https://www.linkedin.com/sharing/share-offsite/?url='+url;
  el=document.getElementById('shRd');if(el)el.href='https://www.reddit.com/submit?url='+url+'&title='+txt;
  // Footer share buttons
  el=document.getElementById('fShX');if(el)el.href='https://x.com/intent/tweet?text='+txt+'&url='+url;
  el=document.getElementById('fShFb');if(el)el.href='https://www.facebook.com/sharer/sharer.php?u='+url;
  el=document.getElementById('fShWa');if(el)el.href='https://wa.me/?text='+full;
  el=document.getElementById('fShTg');if(el)el.href='https://t.me/share/url?url='+url+'&text='+txt;
  el=document.getElementById('fShLi');if(el)el.href='https://www.linkedin.com/sharing/share-offsite/?url='+url;
  el=document.getElementById('fShRd');if(el)el.href='https://www.reddit.com/submit?url='+url+'&title='+txt;
}
function copyShareLink(e){
  var tipId=e&&e.target&&e.target.id==='fShCopy'?'fShCopiedTip':'shCopiedTip';
  navigator.clipboard.writeText(SHARE_URL).then(function(){
    var tip=document.getElementById(tipId);
    if(tip){tip.classList.add('show');setTimeout(function(){tip.classList.remove('show')},2000)}
  }).catch(function(){});
}
// Init share buttons (panel 5 + footer)
document.addEventListener('DOMContentLoaded',function(){
  var cb=document.getElementById('shCopy');if(cb)cb.onclick=copyShareLink;
  var fcb=document.getElementById('fShCopy');if(fcb)fcb.onclick=copyShareLink;
  updateShareLinks();
});
// Re-update share links on language change (hook into existing applyI18n)
var _origApplyI18n=applyI18n;
applyI18n=function(){
  _origApplyI18n();
  updateShareLinks();
  checkVoiceMismatch();
  _updateVoiceChip();
  if(typeof voices!=='undefined' && Object.keys(voices).length>0) fillLangs();
};

// ═══════════════════ VOICE CHIP + MISMATCH ═══════════════════
function _updateVoiceChip(){
  const chip=document.getElementById('voiceChip');
  const chipTxt=document.getElementById('voiceChipTxt');
  const chipLink=document.getElementById('voiceChipLink');
  if(!chip||!chipTxt||!chipLink)return;
  const vl=document.getElementById('vl');
  const vv=document.getElementById('vv');
  if(!vl||!vv||!vl.value||!vl.options[vl.selectedIndex]){chip.classList.remove('vis');return;}
  const langName=vl.options[vl.selectedIndex].text.replace(/\s*\(\d+\)\s*$/,'');
  let voiceName=vv.options[vv.selectedIndex]?vv.options[vv.selectedIndex].text:'';
  if(voiceName){
    // Clean up voice name: remove "Microsoft", "Online (Natural)", and all "(...)" parts
    voiceName = voiceName.replace(/Microsoft\s+/g, '')
                         .replace(/Online\s*\(Natural\)\s*/g, '')
                         .replace(/\s*-\s*[\w\s]+\s*\([^)]+\)\s*/g, '')
                         .replace(/\s*\(.*?\)/g, '')
                         .trim();
  }
  if(!langName){chip.classList.remove('vis');return;}
  const isGV=_isGoogleVoice(vv.value);
  const engineTag=isGV?' [Google HD]':'';
  chipTxt.textContent=langName+(voiceName?' — '+voiceName:'')+ engineTag;
  const _lbl={it:'✏️ Cambia',en:'✏️ Change',fr:'✏️ Modifier',es:'✏️ Cambiar',de:'✏️ Ändern',zh:'✏️ 更改'};
  chipLink.textContent=_lbl[cl]||_lbl.en;
  chip.classList.add('vis');
}

function checkVoiceMismatch(){
  const banner=document.getElementById('voiceMismatch');
  if(!banner)return;
  if(!bookData||!bookData.language){banner.style.display='none';return;}
  const bookLang=bookData.language.split('-')[0].toLowerCase();
  // Only warn for well-known, unambiguous language codes
  const known=['it','en','fr','es','de','zh','hi','pt','nl','pl','ru','ja','ko'];
  if(!known.includes(bookLang)){banner.style.display='none';return;}
  const voiceLang=document.getElementById('vl').value;
  if(bookLang===voiceLang){banner.style.display='none';return;}
  const _names={
    it:{it:'italiano',en:'Italian',fr:'italien',es:'italiano',de:'Italienisch',zh:'意大利语',hi:'इतालवी'},
    en:{it:'inglese',en:'English',fr:'anglais',es:'inglés',de:'Englisch',zh:'英语',hi:'अंग्रेज़ी'},
    fr:{it:'francese',en:'French',fr:'français',es:'francés',de:'Französisch',zh:'法语',hi:'फ़्रेंच'},
    es:{it:'spagnolo',en:'Spanish',fr:'espagnol',es:'español',de:'Spanisch',zh:'西班牙语',hi:'स्पेनिश'},
    de:{it:'tedesco',en:'German',fr:'allemand',es:'alemán',de:'Deutsch',zh:'德语',hi:'जर्मन'},
    zh:{it:'cinese',en:'Chinese',fr:'chinois',es:'chino',de:'Chinesisch',zh:'中文',hi:'चीनी'},
    hi:{it:'hindi',en:'Hindi',fr:'hindi',es:'hindi',de:'Hindi',zh:'印地语',hi:'हिन्दी'},
    pt:{it:'portoghese',en:'Portuguese',fr:'portugais',es:'portugués',de:'Portugiesisch',zh:'葡萄牙语',hi:'पुर्तगाली'},
    ru:{it:'russo',en:'Russian',fr:'russe',es:'ruso',de:'Russisch',zh:'俄语',hi:'रूसी'},
    ja:{it:'giapponese',en:'Japanese',fr:'japonais',es:'japonés',de:'Japanisch',zh:'日语',hi:'जापानी'},
    ko:{it:'coreano',en:'Korean',fr:'coréen',es:'coreano',de:'Koreanisch',zh:'韩语',hi:'कोरियाई'},
    nl:{it:'olandese',en:'Dutch',fr:'néerlandais',es:'neerlandés',de:'Niederländisch',zh:'荷兰语',hi:'डच'},
    pl:{it:'polacco',en:'Polish',fr:'polonais',es:'polaco',de:'Polnisch',zh:'波兰语',hi:'पोलिश'},
  };
  const dn=(_names[bookLang]||{})[cl]||bookLang;
  const _fix=`<a class="vm-link" onclick="autoFixVoice('${bookLang}')">`;
  const _msgs={
    it:`⚠️ Il libro sembra in <strong>${dn}</strong>, ma hai selezionato una voce in un'altra lingua. ${_fix}Seleziona voce ${dn} →</a>`,
    en:`⚠️ The book appears to be in <strong>${dn}</strong>, but a different voice language is selected. ${_fix}Switch to ${dn} voice →</a>`,
    fr:`⚠️ Le livre semble être en <strong>${dn}</strong>, mais une autre langue de voix est sélectionnée. ${_fix}Passer en voix ${dn} →</a>`,
    es:`⚠️ El libro parece estar en <strong>${dn}</strong>, pero está seleccionado otro idioma de voz. ${_fix}Cambiar a voz ${dn} →</a>`,
    de:`⚠️ Das Buch scheint auf <strong>${dn}</strong> zu sein, aber eine andere Stimmensprache ist gewählt. ${_fix}Zu ${dn}-Stimme wechseln →</a>`,
    zh:`⚠️ 本书似乎是<strong>${dn}</strong>，但选择了不同语言的语音。${_fix}切换到${dn}语音 →</a>`,
    hi:`⚠️ यह पुस्तक <strong>${dn}</strong> में लगती है, लेकिन किसी अन्य भाषा की आवाज़ चुनी गई है। ${_fix}${dn} आवाज़ पर स्विच करें →</a>`,
  };
  banner.innerHTML=_msgs[cl]||_msgs.en;
  banner.style.display='';
}

function autoFixVoice(langCode){
  const sel=document.getElementById('vl');
  if(!sel||!sel.querySelector('option[value="'+langCode+'"]'))return;
  sel.value=langCode;
  updVoices();
  // Propaga la lingua anche al tab PREMIUM: i selettori Premium
  // (vlPremium/vvPremium) sono distinti da quelli Standard, quindi senza questa
  // propagazione il click sul warning cambiava solo le voci Standard e la voce
  // Premium restava nella lingua sbagliata (il fix sembrava non funzionare).
  const prem=document.getElementById('vlPremium');
  if(prem&&Array.from(prem.options).some(o=>o.value===langCode)){
    prem.value=langCode;
    if(typeof updVoicesPremium==='function')updVoicesPremium();
  }else if(wizardState&&wizardState.audioTab==='premium'){
    // La lingua del libro non ha voci Premium: ripiega sul tab Standard, dove la
    // voce è già stata impostata nella lingua corretta, così la selezione resta
    // coerente con il warning.
    if(typeof switchAudioTab==='function')switchAudioTab('standard');
  }
  if(typeof requestCombinedEstimate==='function')requestCombinedEstimate();
  goToAudioSettings();
  // Brief highlight sui selettori del tab attivo per confermare il cambio.
  const isPrem=wizardState&&wizardState.audioTab==='premium';
  const langEl=isPrem?document.getElementById('vlPremium'):document.getElementById('vl');
  const voiceEl=isPrem?document.getElementById('vvPremium'):document.getElementById('vv');
  [langEl,voiceEl].forEach(el=>{
    if(!el)return;
    el.style.transition='box-shadow .25s';
    el.style.boxShadow='0 0 0 3px var(--ac)';
    setTimeout(()=>{el.style.boxShadow='none'},1400);
  });
}

function goToAudioSettings(){goToStep(3)}

function _computeSelectedChars(){
  if(!bookData||!Array.isArray(bookData.chapters))return 0;
  const sel=new Set(_getSelectedChapterIndexes());
  let total=0;
  bookData.chapters.forEach(ch=>{if(sel.has(ch.index))total+=(ch.chars||0)});
  return total;
}
function _showSelTooLargeModal(charsSelected,limit){
  const body=document.getElementById('selTooLargeBody');
  if(body){
    // Premium variant quando il `limit` corrisponde al cap Gemini (es. 800k):
    // messaggio dice "fissato per le voci PREMIUM" e invita a usare Voci Standard.
    // Altrimenti (cap Standard ~1.5M) usa il messaggio generico.
    const _premCap=(bookData&&bookData.max_gemini_text_chars)|0;
    const isPrem=(_premCap>0 && limit===_premCap);
    const k=isPrem?'sel_too_large_body_premium':'sel_too_large_body';
    const tpl=t(k,{chars:(charsSelected||0).toLocaleString(),limit:(limit||0).toLocaleString()});
    body.textContent=(tpl&&tpl!==k)?tpl:('Selection too large: '+(charsSelected||0).toLocaleString()+' characters (limit '+(limit||0).toLocaleString()+'). Please reduce the chapter selection.');
  }
  const m=document.getElementById('selTooLargeModal');if(m)m.classList.add('open');
}
function closeSelTooLargeModal(){const m=document.getElementById('selTooLargeModal');if(m)m.classList.remove('open')}
function tryGoToAudioSettings(){
  const sel=_getSelectedChapterIndexes();
  if(sel.length===0){showErr('s3err',t('sel_err_none'));return}
  const s3err=document.getElementById('s3err');if(s3err)s3err.innerHTML='';
  // Cap qui SEMPRE quello Standard (`max_text_chars`, ~1.5M): a questo step
  // l'utente non ha ancora dichiarato di voler usare Premium. Il cap Gemini
  // (`max_gemini_text_chars`, ~800k) viene invece controllato in
  // `switchAudioTab('premium')` — l'unico punto in cui l'intento Premium è
  // esplicito. Cosi` chi resta su Standard non viene bloccato a torto.
  const _capStd=(bookData&&bookData.max_text_chars)|0;
  if(_capStd>0){
    const chars=_computeSelectedChars();
    if(chars>_capStd){_showSelTooLargeModal(chars,_capStd);return}
  }
  // "Prosegui" è l'ingresso del percorso TTS (principale): riasserisci sempre
  // wizMode='audio'. Senza questo, dopo un giro nel percorso traduzione
  // (goToTranslate imposta 'translate') goToStep(3) mostrerebbe di nuovo panelT3.
  wizMode='audio';
  goToStep(3);
  // Mostra (se del caso) badge + coachmark Voci PREMIUM. Deferred: a questo punto
  // la tab Premium potrebbe non essere ancora popolata da loadVoices/_applyPremiumAvailability.
  setTimeout(maybeShowPremiumHint,0);
}

// ═══════════════════ COOKIE CONSENT BANNER (Consent Mode v2) ═══════════════════
(function(){
  const STORAGE_KEY='abm_cookie_consent';
  const T={
    it:{title:'Cookie e privacy',body:'Usiamo Google Analytics per misurare il traffico in forma aggregata. Nessun cookie analitico viene impostato senza il tuo consenso. Puoi modificare la scelta in qualsiasi momento dal link "Cookie" nel footer.',accept:'Accetta',reject:'Rifiuta'},
    en:{title:'Cookies & privacy',body:'We use Google Analytics to measure aggregate traffic. No analytics cookies are set without your consent. You can change your choice anytime from the "Cookie" link in the footer.',accept:'Accept',reject:'Reject'},
    fr:{title:'Cookies et confidentialité',body:'Nous utilisons Google Analytics pour mesurer le trafic agrégé. Aucun cookie analytique n\'est défini sans votre consentement. Vous pouvez modifier votre choix à tout moment depuis le lien "Cookie" en pied de page.',accept:'Accepter',reject:'Refuser'},
    es:{title:'Cookies y privacidad',body:'Usamos Google Analytics para medir el tráfico agregado. No se establece ninguna cookie analítica sin tu consentimiento. Puedes cambiar tu elección en cualquier momento desde el enlace "Cookie" en el pie de página.',accept:'Aceptar',reject:'Rechazar'},
    de:{title:'Cookies & Datenschutz',body:'Wir verwenden Google Analytics zur Messung des aggregierten Traffics. Ohne Ihre Zustimmung werden keine Analyse-Cookies gesetzt. Sie können Ihre Wahl jederzeit über den Link "Cookie" im Footer ändern.',accept:'Akzeptieren',reject:'Ablehnen'},
    zh:{title:'Cookie 和隐私',body:'我们使用 Google Analytics 衡量聚合流量。未经您的同意，不会设置任何分析 Cookie。您可以随时通过页脚中的"Cookie"链接更改选择。',accept:'接受',reject:'拒绝'}
  };
  function tr(){
    const l=(document.documentElement.lang||'en').slice(0,2).toLowerCase();
    return T[l]||T.en;
  }
  function applyConsent(granted){
    if(typeof gtag!=='function')return;
    const v=granted?'granted':'denied';
    gtag('consent','update',{
      ad_storage:v,ad_user_data:v,ad_personalization:v,analytics_storage:v
    });
  }
  function setChoice(choice){
    try{localStorage.setItem(STORAGE_KEY,choice);}catch(e){}
    applyConsent(choice==='granted');
    hide();
  }
  function build(){
    if(document.getElementById('cookieBanner'))return;
    const t=tr();
    const div=document.createElement('div');
    div.id='cookieBanner';
    div.setAttribute('role','dialog');
    div.setAttribute('aria-labelledby','cbTitle');
    div.setAttribute('aria-describedby','cbBody');
    const h=document.createElement('h3');
    h.id='cbTitle';
    h.textContent=t.title;
    const p=document.createElement('p');
    p.id='cbBody';
    p.textContent=t.body;
    const acts=document.createElement('div');
    acts.className='cb-actions';
    const bReject=document.createElement('button');
    bReject.type='button';
    bReject.className='cb-reject';
    bReject.textContent=t.reject;
    bReject.addEventListener('click',()=>setChoice('denied'));
    const bAccept=document.createElement('button');
    bAccept.type='button';
    bAccept.className='cb-accept';
    bAccept.textContent=t.accept;
    bAccept.addEventListener('click',()=>setChoice('granted'));
    acts.appendChild(bReject);
    acts.appendChild(bAccept);
    div.appendChild(h);
    div.appendChild(p);
    div.appendChild(acts);
    document.body.appendChild(div);
  }
  function show(){build();const el=document.getElementById('cookieBanner');if(el)el.classList.add('show');}
  function hide(){const el=document.getElementById('cookieBanner');if(el)el.classList.remove('show');}
  function init(){
    let saved=null;
    try{saved=localStorage.getItem(STORAGE_KEY);}catch(e){}
    if(saved!=='granted'&&saved!=='denied')show();
    // Riapertura del banner su richiesta dalla pagina Privacy (link ?cookies=1).
    try{if(/[?&]cookies=1(?:&|$)/.test(location.search))show();}catch(e){}
    // Link footer unificato "Cookie e privacy": testo localizzato (tr().title),
    // naviga a /privacy. La gestione del consenso vive nella pagina Privacy.
    const link=document.getElementById('privacyLink');
    if(link)link.textContent=tr().title;
  }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',init);
  }else{
    init();
  }
})();

// ─── Community Live Stats + Modal ──────────────────────────────────────
(function(){
  const FLAGS={it:'🇮🇹',en:'🇬🇧',fr:'🇫🇷',es:'🇪🇸',de:'🇩🇪',zh:'🇨🇳',pt:'🇵🇹',ja:'🇯🇵',ru:'🇷🇺',ko:'🇰🇷',ar:'🇸🇦',hi:'🇮🇳',nl:'🇳🇱',pl:'🇵🇱',tr:'🇹🇷',sv:'🇸🇪',cs:'🇨🇿',el:'🇬🇷',he:'🇮🇱',th:'🇹🇭',uk:'🇺🇦',vi:'🇻🇳',id:'🇮🇩',ro:'🇷🇴',hu:'🇭🇺',da:'🇩🇰',fi:'🇫🇮',no:'🇳🇴',nb:'🇳🇴',sk:'🇸🇰'};

  function animateCount(el,target,duration){
    if(!el) return;
    const start=performance.now();
    (function tick(now){
      const t=Math.min(1,(now-start)/duration);
      const eased=1-Math.pow(1-t,4);
      el.textContent=Math.round(target*eased);
      if(t<1) requestAnimationFrame(tick);
    })(performance.now());
  }

  async function loadLiveStats(){
    const ls=document.getElementById('liveStats');
    const numEl=document.getElementById('lsToday');
    if(!ls||!numEl) return;
    try{
      const r=await fetch('/api/community/stats/today');
      if(!r.ok) return;
      const data=await r.json();
      const count=parseInt(data.count,10)||0;
      ls.hidden=false;
      if(count>0){
        animateCount(numEl,count,1200);
      }else{
        numEl.textContent=count;
      }
    }catch(e){/* silent */}
  }

  function renderStatsRows(data){
    const rows=document.getElementById('smRows');
    const empty=document.getElementById('smEmpty');
    if(!rows) return;
    const top=Array.isArray(data.top)?data.top:[];
    const other=parseInt(data.other,10)||0;
    if(top.length===0 && other===0){
      rows.innerHTML='';
      if(empty) empty.hidden=false;
      return;
    }
    if(empty) empty.hidden=true;
    const max=Math.max(...top.map(r=>r.count),other,1);
    const rowHtml=(flag,code,pct,count,other)=>{
      const cls=other?' other':'';
      return '<div class="stats-row">'+
        '<span class="stats-row-label"><span class="flag">'+flag+'</span><span class="code">'+code+'</span></span>'+
        '<div class="stats-row-bar"><div class="stats-row-bar-fill'+cls+'" data-target="'+pct+'" style="width:0%"></div></div>'+
        '<span class="stats-row-num" data-target="'+count+'">0</span>'+
      '</div>';
    };
    let html='';
    for(const r of top){
      const lang=String(r.lang||'').toLowerCase();
      const flag=FLAGS[lang]||'🌐';
      const code=lang.toUpperCase().slice(0,3)||'??';
      const pct=Math.round(r.count/max*100);
      html+=rowHtml(flag,code,pct,r.count,false);
    }
    if(other>0){
      const pct=Math.round(other/max*100);
      html+=rowHtml('🌐','ALT',pct,other,true);
    }
    rows.innerHTML=html;
  }

  async function openStatsModal(ev){
    if(ev) ev.preventDefault();
    const modal=document.getElementById('statsModal');
    if(!modal) return;
    modal.hidden=false;
    const big=document.getElementById('smBigNum');
    if(big) big.textContent='0';
    const rows=document.getElementById('smRows');
    if(rows) rows.innerHTML='';
    try{
      const r=await fetch('/api/community/stats/month');
      if(!r.ok) throw new Error('http '+r.status);
      const data=await r.json();
      renderStatsRows(data);
      animateCount(big,parseInt(data.monthly,10)||0,1400);
      requestAnimationFrame(()=>requestAnimationFrame(()=>{
        modal.querySelectorAll('.stats-row-bar-fill').forEach(b=>{
          b.style.width=(b.dataset.target||'0')+'%';
        });
      }));
      modal.querySelectorAll('.stats-row-num').forEach(n=>{
        animateCount(n,parseInt(n.dataset.target,10)||0,1400);
      });
    }catch(e){/* error inline non bloccante */}
  }

  function closeStatsModal(){
    const modal=document.getElementById('statsModal');
    if(modal) modal.hidden=true;
  }

  function init(){
    loadLiveStats();
    const more=document.getElementById('lsMore');
    if(more) more.addEventListener('click',openStatsModal);
    const close=document.getElementById('statsModalClose');
    if(close) close.addEventListener('click',closeStatsModal);
    const overlay=document.getElementById('statsModal');
    if(overlay) overlay.addEventListener('click',e=>{ if(e.target===overlay) closeStatsModal(); });
    document.addEventListener('keydown',e=>{
      if(e.key==='Escape' && overlay && !overlay.hidden) closeStatsModal();
    });
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init);
  else init();
})();

/* ─── NEWS ─── */
(function(){
  const SEEN_KEY='abm_news_seen_v2';
  function loadSeen(){
    try{return JSON.parse(localStorage.getItem(SEEN_KEY)||'[]');}
    catch(e){return [];}
  }
  function markSeen(id){
    try{
      const seen=loadSeen();
      if(!seen.includes(id)){seen.push(id);localStorage.setItem(SEEN_KEY,JSON.stringify(seen));}
    }catch(e){}
  }
  function fmtDate(ts){
    try{const d=new Date(ts*1000);return d.toLocaleDateString()+' '+d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});}catch(e){return '';}
  }
  function tt(k,fb){
    const lang=document.documentElement.lang||'en';
    const dict=(typeof L!=='undefined'&&L[lang])?L[lang]:null;
    return (dict&&dict[k])||fb||k;
  }
  function tagLabel(tag){return tt('news_tag_'+tag,tag);}
  function uiLang(){
    // Prefer the JS-side current-language variable (cl) when available;
    // it is the canonical source of truth set by setLang(). Fall back to
    // the html lang attribute for early-page or out-of-context calls.
    if(typeof cl!=='undefined'&&cl) return String(cl).slice(0,2).toLowerCase();
    return (document.documentElement.lang||'en').slice(0,2).toLowerCase();
  }
  function pickI18n(orig,i18n,srcLang){
    const ui=uiLang();
    const dict=(i18n&&typeof i18n==='object')?i18n:{};
    const localized=(dict[ui]||'').trim();
    const enFallback=(dict.en||'').trim();
    const src=(srcLang||'').toLowerCase();
    // Prefer UI-language translation; if missing, fall back to English;
    // only then fall back to the original source text.
    let display=localized;
    if(!display && ui!=='en') display=enFallback;
    if(!display) display=orig;
    const hasTr=!!display && display!==orig && (!src || src!==ui);
    return {text:display, hasTr, orig, localized:display};
  }
  function attachI18nToggle(btn,onSet,info){
    if(!info.hasTr){btn.hidden=true;return;}
    btn.hidden=false;
    let showOrig=false;
    const sync=()=>{
      const lbl=tt(showOrig?'comment_show_translation':'comment_show_original','');
      btn.title=lbl||(showOrig?'Show translation':'Show original');
      btn.setAttribute('aria-label',btn.title);
      btn.classList.toggle('active',showOrig);
    };
    sync();
    btn.addEventListener('click',(e)=>{
      e.stopPropagation();
      showOrig=!showOrig;
      onSet(showOrig);
      sync();
    });
  }
  function buildItem(it){
    const div=document.createElement('div');
    div.className='news-item';
    const titleInfo=pickI18n(it.title||'',it.title_i18n||{},it.lang||'');
    const bodyInfo=pickI18n(it.body||'',it.body_i18n||{},it.lang||'');
    const hasTr=titleInfo.hasTr||bodyInfo.hasTr;
    div.innerHTML=`
      <div class="news-item-head">
        <span class="news-item-tag ${it.tag}">${tagLabel(it.tag)}</span>
        <span class="news-item-date">${fmtDate(it.created_at)}</span>
      </div>
      <h4 class="news-item-title"></h4>
      <p class="news-item-body"></p>
      <div class="news-item-foot">
        <button type="button" class="news-i18n-btn" hidden aria-label="">🌐</button>
      </div>`;
    const titleEl=div.querySelector('.news-item-title');
    const bodyEl=div.querySelector('.news-item-body');
    titleEl.textContent=titleInfo.text;
    bodyEl.textContent=bodyInfo.text;
    if(hasTr){
      const btn=div.querySelector('.news-i18n-btn');
      attachI18nToggle(btn,(showOrig)=>{
        titleEl.textContent=showOrig?titleInfo.orig:titleInfo.localized||titleInfo.orig;
        bodyEl.textContent=showOrig?bodyInfo.orig:bodyInfo.localized||bodyInfo.orig;
      },{hasTr:true,orig:'',localized:''});
    }
    return div;
  }
  function showModal(item){
    const overlay=document.getElementById('newsModal');
    if(!overlay) return;
    const tagEl=document.getElementById('newsModalTag');
    const titleEl=document.getElementById('newsModalTitle');
    const bodyEl=document.getElementById('newsModalBody');
    const okBtn=document.getElementById('newsModalOk');
    const closeBtn=document.getElementById('newsModalClose');
    if(tagEl){tagEl.className='news-modal-tag '+item.tag;tagEl.textContent=tagLabel(item.tag);}
    const tInfo=pickI18n(item.title||'',item.title_i18n||{},item.lang||'');
    const bInfo=pickI18n(item.body||'',item.body_i18n||{},item.lang||'');
    if(titleEl) titleEl.textContent=tInfo.text;
    if(bodyEl) bodyEl.textContent=bInfo.text;
    if(okBtn) okBtn.textContent=tt('news_modal_ok','OK');
    overlay.hidden=false;
    document.body.style.overflow='hidden';
    function close(){
      overlay.hidden=true;
      document.body.style.overflow='';
      markSeen(item.id);
    }
    if(okBtn) okBtn.onclick=close;
    if(closeBtn) closeBtn.onclick=close;
    overlay.onclick=(e)=>{if(e.target===overlay) close();};
  }
  async function loadNews(){
    const card=document.getElementById('newsCard');
    const list=document.getElementById('newsList');
    const listMore=document.getElementById('newsListMore');
    const toggleMore=document.getElementById('newsToggleMore');
    const empty=document.getElementById('newsEmpty');
    if(!card||!list) return;
    let data;
    try{
      const r=await fetch('/api/community/news');
      if(!r.ok) return;
      data=await r.json();
    }catch(e){return;}
    const items=(data&&data.items)||[];
    if(!items.length){
      card.hidden=true;
      return;
    }
    card.hidden=false;
    list.innerHTML='';
    if(listMore) listMore.innerHTML='';
    if(empty) empty.hidden=true;
    // Show only the latest by default
    list.appendChild(buildItem(items[0]));
    // Hide rest behind expand button
    const rest=items.slice(1);
    if(rest.length&&listMore&&toggleMore){
      for(const it of rest) listMore.appendChild(buildItem(it));
      toggleMore.hidden=false;
      listMore.hidden=true;
      toggleMore.onclick=()=>{
        const open=!listMore.hidden;
        listMore.hidden=open;
        toggleMore.classList.toggle('open',!open);
        const lbl=toggleMore.querySelector('[data-t]');
        if(lbl){
          lbl.setAttribute('data-t',open?'news_show_more':'news_show_less');
          lbl.textContent=tt(open?'news_show_more':'news_show_less');
        }
      };
    }else if(toggleMore){
      toggleMore.hidden=true;
    }
    // One-time modal popup for items flagged as banner, never seen before
    const seen=loadSeen();
    const popup=items.find(it=>it.banner && !seen.includes(it.id));
    if(popup) showModal(popup);
  }
  function init(){
    loadNews();
    // Re-fetch + re-render when the UI language changes so headlines and
    // bodies pick up the freshly selected localized variants.
    window.addEventListener('abm:langchange',()=>{ loadNews(); });
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init);
  else init();
})();

/* ─── FEEDBACK ─── */
(function(){
  let currentRating=0;
  let lastItems=[];
  const MY_FB_KEY='abm_my_feedbacks';
  function tt(k,fb){
    const lang=document.documentElement.lang||'en';
    const dict=(typeof L!=='undefined')?L[lang]:null;
    return (dict&&dict[k])||fb||k;
  }
  function fmtDate(ts){try{const d=new Date(ts*1000);return d.toLocaleDateString()+' '+d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});}catch(e){return '';}}
  function loadMyFeedbacks(){
    try{const raw=localStorage.getItem(MY_FB_KEY);if(!raw) return [];
      const arr=JSON.parse(raw);return Array.isArray(arr)?arr:[];
    }catch(e){return [];}
  }
  function saveMyFeedbacks(list){
    try{localStorage.setItem(MY_FB_KEY,JSON.stringify(list.slice(0,30)));}catch(e){}
  }
  function rememberMyFeedback(id,token){
    if(!id||!token) return;
    const list=loadMyFeedbacks().filter(e=>e&&e.id!==id);
    list.unshift({id,token,ts:Date.now()});
    saveMyFeedbacks(list);
  }
  function tokenForFeedback(id){
    const e=loadMyFeedbacks().find(x=>x&&x.id===id);
    return e?e.token:null;
  }
  function forgetMyFeedback(id){
    saveMyFeedbacks(loadMyFeedbacks().filter(e=>e&&e.id!==id));
  }
  function applyPlaceholders(node){
    node.querySelectorAll('[data-t-ph]').forEach(el=>{
      el.setAttribute('placeholder',tt(el.getAttribute('data-t-ph')));
    });
  }
  function renderStars(){
    const wrap=document.getElementById('fbStars');
    if(!wrap) return;
    wrap.innerHTML='';
    for(let i=1;i<=5;i++){
      const b=document.createElement('button');
      b.type='button';
      b.className='fbw-star';
      b.dataset.val=String(i);
      b.setAttribute('role','radio');
      b.setAttribute('aria-checked','false');
      b.setAttribute('aria-label',i+' / 5');
      b.textContent='★';
      b.addEventListener('click',()=>{
        currentRating=i;
        wrap.querySelectorAll('.fbw-star').forEach((s,idx)=>{
          const on=(idx<i);
          s.classList.toggle('active',on);
          s.setAttribute('aria-checked',on?'true':'false');
        });
      });
      wrap.appendChild(b);
    }
  }
  function renderHistogram(hist,total){
    const c=document.getElementById('fbHistogram');
    if(!c) return;
    c.innerHTML='';
    for(let r=5;r>=1;r--){
      const cnt=hist[r-1]||0;
      const pct=total?Math.round((cnt/total)*100):0;
      const row=document.createElement('div');
      row.className='fbw-hist-row';
      row.innerHTML=`<span>${r}★</span><div class="fbw-hist-bar"><div class="fbw-hist-fill" style="width:0"></div></div><span>${cnt}</span>`;
      c.appendChild(row);
      // animate next frame
      requestAnimationFrame(()=>requestAnimationFrame(()=>{
        row.querySelector('.fbw-hist-fill').style.width=pct+'%';
      }));
    }
  }
  function uiLang(){
    if(typeof cl!=='undefined'&&cl) return String(cl).slice(0,2).toLowerCase();
    return (document.documentElement.lang||'en').slice(0,2).toLowerCase();
  }
  function pickI18n(orig,i18n,srcLang){
    const ui=uiLang();
    const dict=(i18n&&typeof i18n==='object')?i18n:{};
    const localized=(dict[ui]||'').trim();
    const enFallback=(dict.en||'').trim();
    const src=(srcLang||'').toLowerCase();
    // Prefer UI-language translation; if missing, fall back to English;
    // only then fall back to the original source text.
    let display=localized;
    if(!display && ui!=='en') display=enFallback;
    if(!display) display=orig;
    const hasTr=!!display && display!==orig && (!src || src!==ui);
    return {text:display, hasTr, orig, localized:display};
  }
  function attachI18nToggle(btn,bodyEl,info){
    if(!info.hasTr){btn.hidden=true;return;}
    btn.hidden=false;
    let showOrig=false;
    const sync=()=>{
      const lbl=tt(showOrig?'comment_show_translation':'comment_show_original','');
      btn.title=lbl||(showOrig?'Show translation':'Show original');
      btn.setAttribute('aria-label',btn.title);
      btn.classList.toggle('active',showOrig);
    };
    sync();
    btn.addEventListener('click',(e)=>{
      e.stopPropagation();
      showOrig=!showOrig;
      bodyEl.textContent=showOrig?info.orig:info.localized;
      sync();
    });
  }
  async function deleteOwnFeedback(id){
    const token=tokenForFeedback(id);
    if(!token) return false;
    try{
      const r=await fetch('/api/community/feedback/'+encodeURIComponent(id),{
        method:'DELETE',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({token}),
      });
      if(r.ok){forgetMyFeedback(id);return true;}
      // 404/403: stale entry, drop the local token anyway
      if(r.status===404||r.status===403) forgetMyFeedback(id);
    }catch(e){}
    return false;
  }
  function renderRecent(items){
    const list=document.getElementById('fbRecent');
    if(!list) return;
    list.innerHTML='';
    const C_LANG=document.documentElement.lang||'it';
    function escHtml(s){return (s||'').replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));}
    const withComment=items.filter(it=>it.comment).slice(0,15);
    for(const it of withComment){
      const div=document.createElement('div');
      div.className='fbw-comment';
      const stars='★'.repeat(it.rating||0)+'☆'.repeat(5-(it.rating||0));
      const info=pickI18n(it.comment||'',it.comment_i18n||{},it.comment_lang||'');
      const owned=!!tokenForFeedback(it.id);
      div.innerHTML=`
        <div class="fbw-comment-head">
          <span class="fbw-comment-name"></span>
          <span class="fbw-comment-rating">${stars}</span>
        </div>
        <p class="fbw-comment-body"></p>
        <div class="fbw-comment-foot">
          <button type="button" class="fbw-i18n-btn" hidden aria-label="">🌐</button>
          <span class="fbw-comment-date">${fmtDate(it.created_at)}</span>
          ${owned?'<button type="button" class="fbw-del-btn" aria-label="">🗑</button>':''}
        </div>`;
      div.querySelector('.fbw-comment-name').textContent=it.name||tt('fb_anonymous','Anonymous');
      const body=div.querySelector('.fbw-comment-body');
      body.textContent=info.text;
      attachI18nToggle(div.querySelector('.fbw-i18n-btn'),body,info);
      // Admin reply
      if(it.admin_reply_at > 0){
        const replyDiv=document.createElement('div');
        replyDiv.className='fbw-admin-reply';
        const replyText=it.admin_reply_text||'';
        const replyI18n=it.admin_reply_i18n||{};
        const replyLang=it.admin_reply_lang||'it';
        const replyContent=replyI18n[C_LANG]||replyI18n['it']||replyText;
        replyDiv.innerHTML=`<div class="fbw-admin-reply-head"><span class="fbw-admin-badge">Admin</span><span class="fbw-comment-date">${fmtDate(it.admin_reply_at)}</span></div><p class="fbw-admin-reply-body">${escHtml(replyContent)}</p>`;
        div.appendChild(replyDiv);
      }
      const delBtn=div.querySelector('.fbw-del-btn');
      if(delBtn){
        const lbl=tt('comment_delete','Delete your comment');
        delBtn.title=lbl;delBtn.setAttribute('aria-label',lbl);
        delBtn.addEventListener('click',async(e)=>{
          e.stopPropagation();
          const msg=tt('comment_delete_confirm','Delete your comment? This cannot be undone.');
          if(!window.confirm(msg)) return;
          delBtn.disabled=true;
          const ok=await deleteOwnFeedback(it.id);
          if(ok){loadFeedback();}
          else{delBtn.disabled=false;showMsg(tt('comment_delete_failed','Could not delete the comment.'),'err');}
        });
      }
      list.appendChild(div);
    }
  }
  async function loadFeedback(){
    let data;
    try{
      const r=await fetch('/api/community/feedback');
      if(!r.ok) return;
      data=await r.json();
    }catch(e){return;}
    const avg=document.getElementById('fbAvg');
    const tot=document.getElementById('fbTotal');
    if(avg){
      const v=data.total?Math.max(0,Math.min(5,Number(data.avg)||0)):0;
      const fg=avg.querySelector('.fbw-rating-fg');
      if(fg) fg.style.width=(v/5*100)+'%';
      avg.setAttribute('aria-label',data.total?v.toFixed(1)+' / 5':'0 / 5');
      avg.setAttribute('content',data.total?v.toFixed(1):'0');
    }
    if(tot){
      tot.textContent=data.total?'· '+data.total+' '+tt('fb_total_reviews'):'';
      tot.setAttribute('content',data.total?String(data.total):'0');
    }
    renderHistogram(data.histogram||[0,0,0,0,0],data.total||0);
    lastItems=data.items||[];
    renderRecent(lastItems);
  }
  function showMsg(text,kind){
    const el=document.getElementById('fbMsg');
    if(!el) return;
    el.className='fbw-msg '+kind;
    el.textContent=text;
    el.hidden=false;
    if(kind==='ok') setTimeout(()=>{el.hidden=true;},4000);
  }
  async function submitFeedback(ev){
    ev.preventDefault();
    if(currentRating<1){
      showMsg(tt('fb_missing_rating'),'err');return;
    }
    const name=(document.getElementById('fbName')||{}).value||'';
    const comment=(document.getElementById('fbComment')||{}).value||'';
    const honeypot=(document.getElementById('fbHoneypot')||{}).value||'';
    const submitBtn=document.getElementById('fbSubmit');
    const originalBtnText=submitBtn?submitBtn.textContent:'';
    if(submitBtn){
      submitBtn.disabled=true;
      submitBtn.classList.add('btn-loading');
      submitBtn.textContent=tt('fb_sending','Sending...');
    }
    try{
      const r=await fetch('/api/community/feedback',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({rating:currentRating,name,comment,website:honeypot}),
      });
      if(r.status===429){showMsg(tt('fb_rate_limit'),'err');return;}
      if(r.status===400){
        try{
          const errData=await r.json();
          if(errData && errData.error==='inappropriate_content'){
            showMsg(tt('fb_inappropriate'),'err');return;
          }
          if(errData && errData.error==='missing_rating'){
            showMsg(tt('fb_missing_rating'),'err');return;
          }
          if(errData && errData.error==='name_too_long'){
            showMsg(tt('fb_name_too_long'),'err');return;
          }
          if(errData && errData.error==='comment_too_long'){
            showMsg(tt('fb_comment_too_long'),'err');return;
          }
        }catch(e){}
        showMsg(tt('fb_invalid'),'err');return;
      }
      if(!r.ok){showMsg(tt('fb_invalid'),'err');return;}
      try{
        const data=await r.json();
        if(data&&data.id&&data.delete_token) rememberMyFeedback(data.id,data.delete_token);
      }catch(e){}
      showMsg(tt('fb_thanks'),'ok');
      const form=document.getElementById('fbForm');
      if(form) form.reset();
      currentRating=0;
      document.querySelectorAll('#fbStars .fbw-star').forEach(s=>{
        s.classList.remove('active');
        s.setAttribute('aria-checked','false');
      });
      loadFeedback();
    }catch(e){
      showMsg(tt('fb_invalid'),'err');
    }finally{
      if(submitBtn){
        submitBtn.disabled=false;
        submitBtn.classList.remove('btn-loading');
        submitBtn.textContent=originalBtnText;
      }
    }
  }
  function init(){
    const w=document.getElementById('fbWidget');
    if(!w) return;
    applyPlaceholders(w);
    renderStars();
    const toggle=document.getElementById('fbToggle');
    const panel=document.getElementById('fbPanel');
    if(toggle&&panel){
      toggle.addEventListener('click',()=>{
        const open=!panel.hidden;
        panel.hidden=open;
        toggle.setAttribute('aria-expanded',(!open).toString());
      });
    }
    const form=document.getElementById('fbForm');
    if(form) form.addEventListener('submit',submitFeedback);
    // Re-render the comment list when the user picks a different UI lang.
    window.addEventListener('abm:langchange',()=>{ renderRecent(lastItems); });
    loadFeedback();
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init);
  else init();
})();