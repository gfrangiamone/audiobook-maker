// ═══════════════════ LANGUAGE DROPDOWN ═══════════════════
const LANG_FLAGS={'it':'🇮🇹','en':'🇬🇧','fr':'🇫🇷','es':'🇪🇸','de':'🇩🇪','zh':'🇨🇳'};
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
  if(btnGenerate)btnGenerate.onclick=startCombinedGeneration;
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
      if(_previewGenerated)_resetPreviewState();
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
  // Initialize wizard
  updateWizardSteps(1);
});

let outputFormat='m4b';
let podcastBaseUrl='';
function onOutputChange(){
  const sel=document.getElementById('vOut');
  outputFormat=sel?sel.value:'m4b';
  singleFile=(outputFormat==='m4b'||outputFormat==='mp3');
  const podcastUrlGroup=document.getElementById('podcastUrlGroup');
  if(podcastUrlGroup)podcastUrlGroup.style.display=(outputFormat==='zip_rss')?'':'none';
  const podcastUrlInput=document.getElementById('podcastUrlInput');
  if(podcastUrlInput)podcastBaseUrl=podcastUrlInput.value.trim();
  _updateSummary&&_updateSummary();
  updateSelection();
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
  const target=document.getElementById('panel'+n);
  if(target)target.classList.add('active');
  _wizStep=n;
  updateWizardSteps(n);
  // Auto-update summary when entering panel 4
  if(n===4)_updateSummary();
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
  const fd=new FormData();fd.append('epub',file);
  try{
    const r=await fetch('/api/analyze',{method:'POST',body:fd});
    const d=await r.json();
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
      if(d.status==='optimizing'){_listenOptProgressWiz()}
      else if(d.status==='generating'){listenProgress()}
      _showJobRunningModal(pct);
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
    const _vOut=document.getElementById('vOut');
    if(isTxtFile){
      if(_vOut){_vOut.value='m4b';onOutputChange();}
      document.getElementById('fgOut').style.display='none';
    }else{
      document.getElementById('fgOut').style.display='';
      if(_vOut){_vOut.value='m4b';onOutputChange();}
    }
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
  try{
    const r=await fetch('/api/voices',{headers:{'Accept':'application/json'}});
    if(!r.ok){console.error('loadVoices HTTP '+r.status);return;}
    const ct=(r.headers.get('content-type')||'').toLowerCase();
    if(ct.indexOf('application/json')===-1){console.error('loadVoices: unexpected content-type',ct);return;}
    const txt=await r.text();
    if(!txt){console.error('loadVoices: empty response body');return;}
    let data;
    try{ data=JSON.parse(txt); }
    catch(parseErr){console.error('loadVoices: JSON parse failed',parseErr);return;}
    if(!data||typeof data!=='object'){console.error('loadVoices: invalid payload');return;}
    if(data._google_tts){
        _googleTtsBudget=data._google_tts;
        delete data._google_tts;
    }
    else{
        _googleTtsBudget=null;
    }
    voices=data;
    fillLangs();
  }catch(e){
    console.error('loadVoices failed:', e&&e.message);
  }
}
function fillLangs(){
  const sel=document.getElementById('vl');
  if(!sel) return;
  const oldVal = sel.value;
  sel.innerHTML='';
  
  // Ordine alfabetico basato sul nome tradotto
  const sortedLangs = Object.entries(voices).map(([c, l]) => {
    let ln = c;
    if (L[cl] && L[cl].langs && L[cl].langs[c]) {
      ln = L[cl].langs[c];
    } else if (L['en'] && L['en'].langs && L['en'].langs[c]) {
      ln = L['en'].langs[c];
    } else {
      ln = l.name || c;
    }
    return { code: c, name: ln, count: l.voices.length };
  }).sort((a, b) => a.name.localeCompare(b.name, cl));

  for(const l of sortedLangs){
    const o=document.createElement('option');
    o.value=l.code;
    o.textContent=l.name+' ('+l.count+')';
    sel.appendChild(o);
  }
  sel.onchange=updVoices;
  
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
}
function _isGoogleVoice(id){return id&&id.startsWith('gcloud:')}
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
  const lc=document.getElementById('vl').value,sel=document.getElementById('vv');sel.innerHTML='';
  if(!voices[lc])return;
  const lang=voices[lc];
  // Separa voci per engine, edge prima poi google
  const edgeVoices=lang.voices.filter(v=>(v.engine||'edge')==='edge');
  // Mostra le voci Google solo se il budget mensile copre il libro corrente
  const googleVoices=_googleTtsAffordable()?lang.voices.filter(v=>v.engine==='google'):[];
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
  const dv=edgeVoices.find(v=>v.id.includes('Isabella')||v.id.includes('Guy')||v.id.includes('Davis'))||lang.voices[0];
  if(dv)sel.value=dv.id;
  sel.onchange=()=>{_updateVoiceChip();checkVoiceMismatch();if(_previewGenerated)_resetPreviewState();};
  _updateVoiceChip();checkVoiceMismatch();
  // Reset speed to "Normal" (+0%) whenever language or voice changes
  var vrSel2=document.getElementById('vr');
  if(vrSel2)vrSel2.value='+0%';
  var ss=document.getElementById('speedSlider');
  if(ss)ss.value=0;
  var sl=document.getElementById('speedLabel');
  if(sl)sl.textContent=t('sp_n');
}

// ═══════════════════ PREVIEW AUDIO ═══════════════════
let _prevLoading=false, _previewGenerated=false;

function _updatePreviewBtn(){
  const btn=document.getElementById('btnPrev');
  if(!btn)return;
  const ok=!!(bookData&&bookData.preview_text&&!generating&&!jobDone);
  btn.disabled=!ok;
  btn.classList.remove('loading');
  const txt=document.getElementById('prevTxt');
  if(txt)txt.textContent=t(_previewGenerated?'btn_regen_preview':'btn_gen_preview');
}

function _resetPreviewState(){
  _previewGenerated=false;
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
  btn.disabled=true;
  btn.classList.add('loading');

  // Hide previous player if any
  const wrap=document.getElementById('previewAudioWrap');
  if(wrap)wrap.classList.remove('visible');

  const voice=document.getElementById('vv').value;
  const rate =document.getElementById('vr').value;
  const audio=document.getElementById('previewAudioWiz');

  const url='/api/preview_audio/'+bookData.job_id
    +'?voice='+encodeURIComponent(voice)
    +'&rate='+encodeURIComponent(rate);

  audio.oncanplay=()=>{
    _prevLoading=false;
    btn.classList.remove('loading');
    btn.disabled=true;
    _previewGenerated=true;
    _updatePreviewBtn();
    if(wrap)wrap.classList.add('visible');
    previewListened=true;
    audio.oncanplay=null;
  };
  audio.onerror=()=>{
    if(audio.error&&audio.error.code===audio.MEDIA_ERR_ABORTED)return;
    _prevLoading=false;
    btn.classList.remove('loading');
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
}

function _getAllCheckboxes(){let cbs=document.querySelectorAll('#chl .col-sel input[type=checkbox]');if(!cbs.length)cbs=document.querySelectorAll('#chapterRows .chapter-row input[type=checkbox]');return cbs}
function _getSelectedChapterIndexes(){const idxs=[];_getAllCheckboxes().forEach(cb=>{if(cb.checked)idxs.push(parseInt(cb.dataset.idx))});return idxs}
function _allSelectedOptimized(){const sel=_getSelectedChapterIndexes();if(!sel.length)return false;return sel.every(idx=>optimizedChapters.includes(idx))}
function chSelAll(){_getAllCheckboxes().forEach(cb=>{cb.checked=true;const row=cb.closest('tr')||cb.closest('.chapter-row');if(row)row.classList.remove('unchecked')});updateSelection()}
function chSelNone(){_getAllCheckboxes().forEach(cb=>{cb.checked=false;const row=cb.closest('tr')||cb.closest('.chapter-row');if(row)row.classList.add('unchecked')});updateSelection()}
function chSelInvert(){_getAllCheckboxes().forEach(cb=>{cb.checked=!cb.checked;const row=cb.closest('tr')||cb.closest('.chapter-row');if(row)row.classList.toggle('unchecked',!cb.checked)});updateSelection()}
function chMasterToggle(){const v=document.getElementById('chAll').checked;_getAllCheckboxes().forEach(cb=>{cb.checked=v;const row=cb.closest('tr')||cb.closest('.chapter-row');if(row)row.classList.toggle('unchecked',!v)});updateSelection()}

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
    const couponRow=document.getElementById('couponRow');if(couponRow)couponRow.classList.remove('visible');
    const couponResult=document.getElementById('couponResult');if(couponResult)couponResult.textContent='';
    window._couponPaymentToken=null;
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
      // Onerous: hide cost UI and open the rich popup directly
      if(costEl)costEl.classList.remove('visible');
      if(!window._couponPaymentToken){
        try{var cfg=await fetch('/api/llm_available').then(r=>r.json());
          llmConfig.rate=cfg.rate_eur_per_mchar||1.1;
          llmConfig.threshold=cfg.free_threshold_eur||0.5;
          llmConfig.bonus=cfg.voucher_bonus_percent||10;
          llmConfig.expiry=cfg.voucher_expiry_days||180;
          llmConfig.paypalClientId=cfg.paypal_client_id||"";
          llmConfig.paypalMode=cfg.paypal_mode||"sandbox";
          llmConfig.paypalAvailable=!!cfg.paypal_available;
        }catch(e){}
        const token=await _showPaymentModal(est.cost_eur,est.chars);
        if(token){
          window._couponPaymentToken=token;
          const result=document.getElementById('couponResult');
          if(result){result.textContent='✅ '+(t('pay_voucher_valid')||'Voucher valid!');result.className='coupon-result success'}
        }else{
          // Popup closed without validating: turn AI optimization off
          const aiToggle=document.getElementById('aiToggle');
          if(aiToggle)aiToggle.checked=false;
          aiOptEnabled=false;
          const aiOptInfo=document.getElementById('aiOptInfo');if(aiOptInfo)aiOptInfo.style.display='none';
          _updateAiOptCard();_updateSummary();
        }
      }
    }else{
      // Free (below threshold): hide cost UI completely — say nothing
      if(costEl)costEl.classList.remove('visible');
      const couponRow=document.getElementById('couponRow');if(couponRow)couponRow.classList.remove('visible');
      const couponResult=document.getElementById('couponResult');if(couponResult)couponResult.textContent='';
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

  const vv=document.getElementById('vv'),vr=document.getElementById('vr');
  const sumVoice=document.getElementById('summaryVoice');
  if(sumVoice&&vv){
    const vSel=vv.options[vv.selectedIndex];
    const voiceName=vSel?vSel.text.replace(/\s*\(.*?\)\s*/g,'').replace(/Microsoft\s+/g,'').trim():'—';
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

function _loadPaypalSdk(clientId){
  return new Promise(function(resolve,reject){
    if(paypalSdkLoaded&&window.paypal){resolve();return}
    var s=document.createElement('script');
    s.src='https://www.paypal.com/sdk/js?client-id='+encodeURIComponent(clientId)+'&currency=EUR&intent=capture';
    s.onload=function(){paypalSdkLoaded=true;resolve()};
    s.onerror=function(){reject(new Error('Failed to load PayPal SDK'))};
    document.head.appendChild(s);
  });
}

async function _showPaymentModal(costEur,chars){
  return new Promise(async function(resolve){
    var modal=document.getElementById('payModal');
    var errEl=document.getElementById('payErr');
    var okEl=document.getElementById('payOk');
    errEl.style.display='none';okEl.style.display='none';
    document.getElementById('payCostValue').textContent='€ '+costEur.toFixed(2);
    document.getElementById('payCostDetails').textContent=chars.toLocaleString()+' char × '+llmConfig.rate.toFixed(2)+' €/M';
    document.getElementById('payVoucherCode').value='';
    document.getElementById('payVoucherEmail').value=lastVoucherEmail;
    applyI18n();
    // pay_desc contiene tag HTML (<b>) e placeholder {chars} → calcolo dinamico della soglia in caratteri
    // soglia_char = floor(threshold_eur / rate_eur_per_Mchar * 1_000_000), arrotondato per difetto a migliaia
    var thresholdChars=Math.floor((llmConfig.threshold/llmConfig.rate)*1000000/1000)*1000;
    var charsStr=thresholdChars.toLocaleString(cl||'it');
    document.getElementById('payDescText').innerHTML=t('pay_desc').replace('{chars}',charsStr);
    modal.classList.add('open');

    var resolved=false;
    function done(token){if(resolved)return;resolved=true;modal.classList.remove('open');resolve(token)}
    document.getElementById('payClose').onclick=function(){done(null)};
    document.getElementById('payVoucherSubmit').onclick=async function(){
      errEl.style.display='none';
      var code=document.getElementById('payVoucherCode').value.trim().toUpperCase();
      var email=document.getElementById('payVoucherEmail').value.trim();
      if(!code||!email){errEl.textContent=t('pay_err_generic');errEl.style.display='';return}
      try{
        var r=await fetch('/api/voucher_validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:code,email:email})});
        var d=await r.json();
        if(d.error){errEl.textContent=d.error;errEl.style.display='';return}
        lastVoucherEmail=email; // Save for pre-filling notification email
        try{localStorage.setItem('abm_v_email',email)}catch(e){}
        okEl.textContent=t('pay_voucher_valid');okEl.style.display='';
        setTimeout(function(){done(d.payment_token)},800);
      }catch(e){errEl.textContent='Error: '+e.message;errEl.style.display=''}
    };

    /* PayPal SDK loading disabled — payment via voucher only.
       Backend PayPal routes are preserved for potential future re-enablement.
    if(llmConfig.paypalAvailable&&llmConfig.paypalClientId){
      try{
        await _loadPaypalSdk(llmConfig.paypalClientId);
        document.getElementById('payPaypalLoading').style.display='none';
        window.paypal.Buttons({
          style:{layout:'vertical',color:'gold',shape:'rect',label:'pay'},
          createOrder:async function(){
            var r=await fetch('/api/paypal_create_order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId})});
            var d=await r.json();
            if(d.error)throw new Error(d.error);
            return d.order_id;
          },
          onApprove:async function(data){
            try{
              var r=await fetch('/api/paypal_capture_order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order_id:data.orderID,job_id:jobId})});
              var d=await r.json();
              if(d.error){errEl.textContent=d.error;errEl.style.display='';return}
              okEl.textContent=t('pay_success');okEl.style.display='';
              setTimeout(function(){done(d.payment_token)},800);
            }catch(e){errEl.textContent='Error: '+e.message;errEl.style.display=''}
          },
          onError:function(err){errEl.textContent=t('pay_err_generic');errEl.style.display='';console.error(err)},
          onCancel:function(){}
        }).render('#paypal-button-container');
      }catch(e){
        document.getElementById('payPaypalLoading').textContent='PayPal unavailable: '+e.message;
      }
    }else{
      document.getElementById('payPaypalLoading').textContent='PayPal not configured';
    }
    */
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
  const voiceLang = document.getElementById('vl').value;
  if(bookLang && voiceLang && bookLang !== voiceLang && !previewListened) {
    // Show the same warning modal (it asks to verify voice/language)
    return await _showLangWarning();
  }
  return true;
}

async function startCombinedGeneration(){
  if(!jobId||generating)return;

  // Check admin suspend
  try{
    const sr=await fetch('/api/admin/suspend');
    if(sr.ok){const sd=await sr.json();if(sd.suspended){alert('System under maintenance. Please try again in a few minutes.');return}}
  }catch(e){}

  if(!(await _validateLanguage()))return;
  // Donate modal for returning users
  if(_shouldShowDonateModal()){await _showDonateModal();}
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
    var paymentToken=null;
    try{
      let url=new URL('/api/optimize_estimate/'+jobId, window.location.origin);
      const selLang=document.getElementById('vl').value||cl;
      url.searchParams.append('lang',selLang);
      if(selectedChapters&&selectedChapters.length>0){
        selectedChapters.forEach(idx=>url.searchParams.append('selected_chapters',idx));
      }
      var est=await fetch(url.toString()).then(r=>r.json());
      if(est.error){showS3Err(est.error);if(btnGen){btnGen.disabled=false;btnGen.innerHTML='<span data-t="btn_gen">'+t('btn_gen')+'</span>'}return}
      if(est.requires_payment){
        // Reuse token already validated via the popup (showCoupon)
        if(window._couponPaymentToken){
          paymentToken=window._couponPaymentToken;
        }else{
          try{var cfg=await fetch('/api/llm_available').then(r=>r.json());
            llmConfig.rate=cfg.rate_eur_per_mchar||1.1;
            llmConfig.threshold=cfg.free_threshold_eur||0.5;
            llmConfig.bonus=cfg.voucher_bonus_percent||10;
            llmConfig.expiry=cfg.voucher_expiry_days||180;
            llmConfig.paypalClientId=cfg.paypal_client_id||"";
            llmConfig.paypalMode=cfg.paypal_mode||"sandbox";
            llmConfig.paypalAvailable=!!cfg.paypal_available;
          }catch(e){}
          paymentToken=await _showPaymentModal(est.cost_eur,est.chars);
          if(!paymentToken){if(btnGen){btnGen.disabled=false;btnGen.innerHTML='<span data-t="btn_gen">'+t('btn_gen')+'</span>'}return}
        }
      }
    }catch(e){showS3Err('Estimate error: '+e.message);if(btnGen){btnGen.disabled=false;btnGen.innerHTML='<span data-t="btn_gen">'+t('btn_gen')+'</span>'}return}

    _showWizProgress();
    _setCancelButtonMode('opt');
    lockUI();
    try{
      const selLang=document.getElementById('vl').value||cl;
      var payload={job_id:jobId,batch:false,lang:selLang};
      if(paymentToken)payload.payment_token=paymentToken;
      if(selectedChapters)payload.selected_chapters=selectedChapters;
      // Always use auto_generate in wizard flow
      payload.auto_generate=true;
      payload.voice=document.getElementById('vv').value;
      payload.rate=document.getElementById('vr').value;
      payload.single_file=singleFile;
      payload.output_format=outputFormat;
      payload.podcast_base_url=podcastBaseUrl;
      var r=await fetch('/api/optimize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      var d=await r.json();
      if(d.error){
        if(d.error_code==='llm_concurrent_limit'){
          document.getElementById('pMsg').textContent=t('llm_concurrent_limit')||d.error;
          document.getElementById('pMsg').style.color='var(--err)';
        }else{showPErr(d.error)}
        unlockUI();return;
      }
      _listenOptProgressWiz();
    }catch(e){showPErr('Error: '+e.message);unlockUI()}
  }else{
    // ── Direct TTS generation ──
    _showWizProgress();
    _setCancelButtonMode('gen');
    lockUI();
    try{
      var genPayload={job_id:jobId,voice:document.getElementById('vv').value,rate:document.getElementById('vr').value,single_file:singleFile,output_format:outputFormat,podcast_base_url:podcastBaseUrl};
      if(selectedChapters)genPayload.selected_chapters=selectedChapters;
      var gr=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(genPayload)});
      var gd=await gr.json();
      if(gd.error){
        if(gd.error_code==='concurrent_limit'){
          document.getElementById('pMsg').textContent=t('concurrent_limit')||gd.error;
          document.getElementById('pMsg').style.color='var(--err)';
          document.getElementById('pBar').style.width='0%';
          document.getElementById('pPct').textContent='';
          document.getElementById('cnA').innerHTML='<button class="btn btn-ok" id="btnRetryWiz">🔄 '+(t('btn_retry')||'Retry generation')+'</button>';
          document.getElementById('btnRetryWiz').onclick=retryGeneration;
          unlockUI();return;
        }
        if(gd.error_code==='google_tts_budget'){
          document.getElementById('pMsg').innerHTML=(t('google_tts_budget_err')||gd.error);
          document.getElementById('pMsg').style.color='var(--err)';
          document.getElementById('cnA').innerHTML='<button class="btn btn-ok" id="btnRetryWiz">🔄 '+(t('btn_retry')||'Retry generation')+'</button>';
          document.getElementById('btnRetryWiz').onclick=retryGeneration;
          unlockUI();return;
        }
        showPErr(gd.error);unlockUI();return;
      }
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

function _showJobRunningModal(pct){
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
    el.onclick=function(ev){if(ev.target===el){el.remove();resetAll();}};
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
  if(closeBtn)closeBtn.onclick=_hideJobRunningModal;
  modal.onclick=function(ev){if(ev.target===modal)_hideJobRunningModal();};
}
function _hideJobRunningModal(reset){
  var modal=document.getElementById('jobRunningModal');
  if(!modal)return;
  if(modal._dynamic){modal.remove();}
  else{modal.classList.remove('open');}
  if(reset!==false)resetAll(); // reset only when user manually closes the modal
}
function _updateJobRunningPct(pct){
  const span=document.getElementById('jobRunningPct');
  if(span)span.textContent=Math.round(pct||0);
}

function _showWizProgress(){
  _stopAnalyzedHeartbeat();
  const genProgress=document.getElementById('generationProgress');if(genProgress)genProgress.style.display='';
  const panel4Footer=document.getElementById('panel4Footer');if(panel4Footer)panel4Footer.style.display='none';
  const genActiveNotice=document.getElementById('generationActiveNotice');if(genActiveNotice)genActiveNotice.style.display='flex';
  const aiOptCard=document.getElementById('aiOptCard');if(aiOptCard)aiOptCard.style.display='none';
  const summaryBox=document.getElementById('summaryBox');if(summaryBox)summaryBox.style.display='none';
  const emailLateArea=document.getElementById('emailLateArea');if(emailLateArea)emailLateArea.classList.add('visible');
  document.getElementById('pBar').style.width='0%';
  document.getElementById('pPct').textContent='0%';
  document.getElementById('pMsg').textContent=t('starting');
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
  var es=new EventSource('/api/optimize_progress/'+jobId);
  es.onmessage=function(ev){
    var d=JSON.parse(ev.data);
    if(d.status==='error'){
      es.close();_hideJobRunningModal();_setCancelButtonMode('gen');showPErr(d.error||'Optimization error');unlockUI();return;
    }
    if(d.status==='cancelled'){
      es.close();_hideJobRunningModal();_setCancelButtonMode('gen');
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
    _updateJobRunningPct(pct);

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

// Old startOptimization kept for backward compat (called from batch flow, etc.)
async function startOptimization(){
  if(!jobId)return;
  try{const sr=await fetch('/api/admin/suspend');if(sr.ok){const sd=await sr.json();if(sd.suspended){alert('System under maintenance. Please try again in a few minutes.');return}}}catch(e){}
  if(!(await _validateLanguage()))return;
  document.getElementById('s3err').innerHTML='';
  let selectedChapters=_getSelectedChapterIndexes();
  if(selectedChapters.length===0){showS3Err(t('sel_err_none')||'Select at least one chapter');return}
  var paymentToken=null;
  try{
    let url=new URL('/api/optimize_estimate/'+jobId,window.location.origin);
    const selLang=document.getElementById('vl').value||cl;url.searchParams.append('lang',selLang);
    if(selectedChapters&&selectedChapters.length>0)selectedChapters.forEach(idx=>url.searchParams.append('selected_chapters',idx));
    var est=await fetch(url.toString()).then(r=>r.json());
    if(est.error){showS3Err(est.error);return}
    if(est.requires_payment){
      try{var cfg=await fetch('/api/llm_available').then(r=>r.json());
        llmConfig.rate=cfg.rate_eur_per_mchar||1.1;llmConfig.threshold=cfg.free_threshold_eur||0.5;
        llmConfig.bonus=cfg.voucher_bonus_percent||10;llmConfig.expiry=cfg.voucher_expiry_days||180;
        llmConfig.paypalClientId=cfg.paypal_client_id||"";llmConfig.paypalMode=cfg.paypal_mode||"sandbox";llmConfig.paypalAvailable=!!cfg.paypal_available;
      }catch(e){}
      paymentToken=await _showPaymentModal(est.cost_eur,est.chars);
      if(!paymentToken)return;
    }
  }catch(e){showS3Err('Estimate error: '+e.message);return}
  _showWizProgress();
  _setCancelButtonMode('opt');
  lockUI();
  try{
    const selLang=document.getElementById('vl').value||cl;
    var payload={job_id:jobId,batch:false,lang:selLang};
    if(paymentToken)payload.payment_token=paymentToken;
    if(selectedChapters)payload.selected_chapters=selectedChapters;
    var r=await fetch('/api/optimize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    var d=await r.json();
    if(d.error){
      if(d.error_code==='llm_concurrent_limit'){document.getElementById('pMsg').textContent=t('llm_concurrent_limit')||d.error;document.getElementById('pMsg').style.color='var(--err)';}
      else{showPErr(d.error)}unlockUI();return;
    }
    _listenOptProgressWiz();
  }catch(e){showPErr('Error: '+e.message);unlockUI()}
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
    const payload={job_id:jobId,voice:document.getElementById('vv').value,rate:document.getElementById('vr').value,single_file:singleFile,output_format:outputFormat,podcast_base_url:podcastBaseUrl};
    if(selectedChapters)payload.selected_chapters=selectedChapters;
    const r=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    if(d.error){
      if(d.error_code==='concurrent_limit'){
        document.getElementById('pMsg').textContent=t('concurrent_limit')||d.error;document.getElementById('pMsg').style.color='var(--err)';
        document.getElementById('pBar').style.width='0%';document.getElementById('pPct').textContent='';
        document.getElementById('cnA').innerHTML='<button class="btn btn-ok" id="btnRetryWiz">🔄 '+(t('btn_retry')||'Retry generation')+'</button>';
        document.getElementById('btnRetryWiz').onclick=retryGeneration;unlockUI();return
      }
      if(d.error_code==='google_tts_budget'){
        document.getElementById('pMsg').innerHTML=(t('google_tts_budget_err')||d.error);document.getElementById('pMsg').style.color='var(--err)';
        document.getElementById('cnA').innerHTML='<button class="btn btn-ok" id="btnRetryWiz">🔄 '+(t('btn_retry')||'Retry generation')+'</button>';
        document.getElementById('btnRetryWiz').onclick=retryGeneration;unlockUI();return
      }
      showPErr(d.error);unlockUI();return
    }
    listenProgress();
  }catch(e){showPErr('Error: '+e.message);unlockUI()}
}

function listenProgress(){
  let retries=0;
  const maxRetries=5;
  function connect(){
    const es=new EventSource('/api/progress/'+jobId);
    es.onmessage=ev=>{
      retries=0;
      const d=JSON.parse(ev.data);
      if(d.status==='error'){es.close();_hideJobRunningModal();showPErr(d.error);unlockUI();generating=false;document.getElementById('cnA').style.display='none';return}
      if(d.status==='cancelled'){es.close();_hideJobRunningModal();document.getElementById('pMsg').textContent=t('cancelled_msg');document.getElementById('pMsg').style.color='var(--err)';document.getElementById('cnA').style.display='none';unlockUI();generating=false;return}

      const pct=d.progress_total>0?Math.round(d.progress_current/d.progress_total*100):0;
      // Update both old and new progress elements
      document.getElementById('pPct').textContent=pct+'%';
      document.getElementById('pBar').style.width=pct+'%';
      document.getElementById('pMsg').textContent=d.progress_message||'';
      const progressFill=document.getElementById('progressFill');if(progressFill)progressFill.style.width=pct+'%';
      const progressPct=document.getElementById('progressPct');if(progressPct)progressPct.textContent=pct+'%';
      const progressPhase=document.getElementById('progressPhase');if(progressPhase&&d.progress_message)progressPhase.textContent=d.progress_message;
      _updateJobRunningPct(pct);

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

      if(d.status==='done'){
        es.close();
        generating=false;jobDone=true;
        _hideJobRunningModal(false); // don't reset — keep jobId for download buttons
        unlockUI();
        document.getElementById('pPct').textContent='100%';
        document.getElementById('pBar').style.width='100%';
        document.getElementById('pMsg').textContent=t('done_msg');
        document.getElementById('pMsg').style.color='var(--ok)';
        const progressFill=document.getElementById('progressFill');if(progressFill)progressFill.style.width='100%';
        const progressPct=document.getElementById('progressPct');if(progressPct)progressPct.textContent='100%';
        const progressPhase=document.getElementById('progressPhase');if(progressPhase)progressPhase.textContent=t('done_t');

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

function cancelJob(){
  if(!jobId||!generating)return;
  navigator.sendBeacon('/api/cancel/'+jobId+'?force=1');
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
  const btnGen=document.getElementById('btnGenerate');if(btnGen){btnGen.disabled=false;btnGen.innerHTML='<span data-t="btn_gen">'+t('btn_gen')+'</span>'}
  const cnA=document.getElementById('cnA');if(cnA)cnA.style.display='none';
  updateSelection();
}

function retryGen(){retryGeneration()}

async function downloadFile(type){
  if(!jobId)return;
  let btnId = 'btnD';
  if(type === 'm4b') btnId = 'btnM';
  if(type === 'abm') btnId = 'btnA';
  if(type === 'zip') btnId = 'btnD';
  if(type === 'mp3') btnId = 'btnD';

  const btn=document.getElementById(btnId);
  const originalHtml = btn.innerHTML;
  btn.disabled=true;btn.textContent='⏳...';
  const maxDlRetries=3;
  for(let attempt=1;attempt<=maxDlRetries;attempt++){
    try{
      navigator.sendBeacon('/api/heartbeat/'+jobId);
      const r=await fetch('/api/download/'+jobId + (type ? '?type='+type : ''));
      if(r.status===404){
        if(attempt<maxDlRetries){await new Promise(ok=>setTimeout(ok,1500));continue}
        showPErr(t('dl_expired')||'File non più disponibile. Riconverti il libro.');
        btn.disabled=false;btn.innerHTML=originalHtml;
        return;
      }
      if(r.status===429){
        const txt=await r.text();
        const m=txt.match(/Wait (\d+) seconds/);
        const sec=m?m[1]:'60';
        showPErr(t('dl_cooldown').replace('%s', sec));
        btn.disabled=false;btn.innerHTML=originalHtml;
        return;
      }
      if(r.status===410){
        showPErr(t('dl_deleted')||'File removed after too many downloads. Please reconvert the book.');
        btn.disabled=false;btn.innerHTML=originalHtml;
        return;
      }
      if(!r.ok){
        const txt=await r.text();
        showPErr(txt||'Download failed');
        btn.disabled=false;btn.innerHTML=originalHtml;
        return;
      }
      const isLastDl=(r.headers.get('X-Download-Last')==='1');
      const blob=await r.blob();
      const cd=r.headers.get('Content-Disposition')||'';
      // Parse Content-Disposition robustly: RFC 5987 filename*=, quoted filename="...", or bare filename=foo.
      // The previous regex stopped at apostrophes, truncating titles like "L'isola" and losing the extension.
      let fname='';
      let mm=cd.match(/filename\*\s*=\s*[^']+''([^;\n]+)/i);
      if(mm){try{fname=decodeURIComponent(mm[1].trim())}catch(e){fname=''}}
      if(!fname){mm=cd.match(/filename\s*=\s*"([^"]+)"/i);if(mm)fname=mm[1]}
      if(!fname){mm=cd.match(/filename\s*=\s*([^;\n]+)/i);if(mm)fname=mm[1].trim()}
      let defName = 'audiobook.zip';
      if(type === 'm4b') defName = 'audiobook.m4b';
      if(type === 'abm') defName = 'project.abm';
      if(type === 'mp3') defName = 'audiobook.mp3';
      if(!fname) fname=defName;
      // Safety net: enforce the expected extension if the parsed filename is missing it.
      const extByType={zip:'.zip',m4b:'.m4b',mp3:'.mp3',abm:'.abm'};
      const expectedExt=extByType[type];
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
      btn.innerHTML='✅ <span>'+successT+'</span>';
      btn.disabled=false;
      if(isLastDl)showDlLastWarning();
      return;
    }catch(e){
      if(attempt<maxDlRetries){await new Promise(ok=>setTimeout(ok,1500));continue}
      showPErr('Download error: '+e.message);
      btn.disabled=false;btn.innerHTML=originalHtml;
    }
  }
}

async function downloadPodcast(){
  if(!jobId)return;
  const baseUrl=prompt(t('podcast_url_prompt'),'https://example.com/podcast');
  if(!baseUrl)return;
  const btn=document.getElementById('btnP');
  btn.disabled=true;btn.textContent='⏳...';
  try{
    navigator.sendBeacon('/api/heartbeat/'+jobId);
    const r=await fetch('/api/download_podcast/'+jobId+'?base_url='+encodeURIComponent(baseUrl));
    if(r.status===429){
      const txt=await r.text();
      const m=txt.match(/Wait (\d+) seconds/);
      const sec=m?m[1]:'60';
      showPErr(t('dl_cooldown').replace('%s', sec));
      btn.disabled=false;btn.innerHTML='🎙️ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';
      return;
    }
    if(r.status===410){
      showPErr(t('dl_deleted')||'File removed after too many downloads. Please reconvert the book.');
      btn.disabled=false;btn.innerHTML='🎙️ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';
      return;
    }
    if(!r.ok){
      const txt=await r.text();
      showPErr(txt||'Download failed');
      btn.disabled=false;btn.innerHTML='🎙️ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';
      return;
    }
    const isLastDl=(r.headers.get('X-Download-Last')==='1');
    const blob=await r.blob();
    const cd=r.headers.get('Content-Disposition')||'';
    const m=cd.match(/filename[^;=\n]*=['"]?([^'";\n]*)/);
    const fname=m?m[1]:'podcast.zip';
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download=fname;
    document.body.appendChild(a);a.click();
    setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},1000);
    btn.innerHTML='✅ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';
    btn.disabled=false;
    if(isLastDl)showDlLastWarning();
  }catch(e){
    showPErr('Download error: '+e.message);
    btn.disabled=false;btn.innerHTML='🎙️ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';
  }
}

async function downloadPodcastZip(){
  if(!jobId)return;
  const btn=document.getElementById('btnP');
  btn.disabled=true;btn.textContent='⏳...';
  try{
    navigator.sendBeacon('/api/heartbeat/'+jobId);
    const r=await fetch('/api/download_podcast/'+jobId+(podcastBaseUrl?'?base_url='+encodeURIComponent(podcastBaseUrl):''));
    if(r.status===429){const txt=await r.text();const m=txt.match(/Wait (\d+) seconds/);const sec=m?m[1]:'60';showPErr(t('dl_cooldown').replace('%s', sec));btn.disabled=false;btn.innerHTML='🎙️ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';return}
    if(r.status===410){showPErr(t('dl_deleted')||'File removed after too many downloads. Please reconvert the book.');btn.disabled=false;btn.innerHTML='🎙️ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';return}
    if(!r.ok){const t=await r.text();showPErr(t||'Download failed');btn.disabled=false;btn.innerHTML='🎙️ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';return}
    const isLastDl=(r.headers.get('X-Download-Last')==='1');
    const blob=await r.blob();
    const cd=r.headers.get('Content-Disposition')||'';
    const m=cd.match(/filename[^;=\n]*=['\"]?([^'\";\n]*)/);
    const fname=m?m[1]:'podcast.zip';
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);a.download=fname;
    document.body.appendChild(a);a.click();
    setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},1000);
    if(isLastDl)showDlLastWarning();
  }catch(e){showPErr('Download error: '+e.message)}
  btn.disabled=false;btn.innerHTML='🎙️ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';
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
  const couponRow=document.getElementById('couponRow');if(couponRow)couponRow.classList.remove('visible');
  _updateAiOptCard();
  // Hide generation/download UI
  const dlA=document.getElementById('dlA');if(dlA)dlA.style.display='none';
  const btnD=document.getElementById('btnD');if(btnD){btnD.style.display='none';btnD.innerHTML='&#x2B07;&#xFE0F; <span data-t="btn_dl">'+t('btn_dl')+'</span>';}
  const btnM=document.getElementById('btnM');if(btnM)btnM.style.display='none';
  const btnA=document.getElementById('btnA');if(btnA)btnA.style.display='none';
  const btnP=document.getElementById('btnP');if(btnP)btnP.style.display='none';
  const dlLastNotice=document.getElementById('dlLastNotice');if(dlLastNotice)dlLastNotice.style.display='none';
  const btnBackCh=document.getElementById('btnBackCh');if(btnBackCh)btnBackCh.style.display='none';
  const genProgress=document.getElementById('generationProgress');if(genProgress)genProgress.style.display='none';
  const panel4Footer=document.getElementById('panel4Footer');if(panel4Footer)panel4Footer.style.display='';
  const emailLateArea=document.getElementById('emailLateArea');if(emailLateArea)emailLateArea.classList.remove('visible');
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
  document.getElementById('fgOut').style.display='';
  const _vOutR=document.getElementById('vOut');if(_vOutR){_vOutR.value='m4b';onOutputChange();}
  previewStop();
  bookData=null;jobId=null;
  emailRegistered=false;previewListened=false;
  ['bkCover','s4bkCover'].forEach(id=>{var el=document.getElementById(id);if(el){el.style.display='none';el.src=''}});
  const coverPlaceholder=document.getElementById('coverPlaceholder');if(coverPlaceholder)coverPlaceholder.style.display='';
  // Reset wizard generation UI
  const genProgress=document.getElementById('generationProgress');if(genProgress)genProgress.style.display='none';
  const panel4Footer=document.getElementById('panel4Footer');if(panel4Footer)panel4Footer.style.display='';
  const genActiveNotice=document.getElementById('generationActiveNotice');if(genActiveNotice)genActiveNotice.style.display='none';
  const emailLateArea=document.getElementById('emailLateArea');if(emailLateArea)emailLateArea.classList.remove('visible');
  const cnA=document.getElementById('cnA');if(cnA)cnA.style.display='none';
  const btnGen=document.getElementById('btnGenerate');if(btnGen){btnGen.disabled=false;btnGen.innerHTML='<span data-t="btn_gen">'+t('btn_gen')+'</span>'}
  const dlA=document.getElementById('dlA');if(dlA)dlA.style.display='none';
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
  const couponRow=document.getElementById('couponRow');if(couponRow)couponRow.classList.remove('visible');
  const couponResult=document.getElementById('couponResult');if(couponResult)couponResult.innerHTML='';
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

async function showCoupon(){
  // Open the rich payment modal (more explanatory space) for voucher entry
  if(!jobId)return;
  try{
    let url=new URL('/api/optimize_estimate/'+jobId, window.location.origin);
    const selLang=document.getElementById('vl').value||cl;
    url.searchParams.append('lang',selLang);
    _getSelectedChapterIndexes().forEach(idx=>url.searchParams.append('selected_chapters',idx));
    const est=await fetch(url.toString()).then(r=>r.json());
    if(est.error||!est.requires_payment)return;
    try{
      var cfg=await fetch('/api/llm_available').then(r=>r.json());
      llmConfig.rate=cfg.rate_eur_per_mchar||1.1;
      llmConfig.threshold=cfg.free_threshold_eur||0.5;
      llmConfig.bonus=cfg.voucher_bonus_percent||10;
      llmConfig.expiry=cfg.voucher_expiry_days||180;
      llmConfig.paypalClientId=cfg.paypal_client_id||"";
      llmConfig.paypalMode=cfg.paypal_mode||"sandbox";
      llmConfig.paypalAvailable=!!cfg.paypal_available;
    }catch(e){}
    const token=await _showPaymentModal(est.cost_eur,est.chars);
    if(token){
      window._couponPaymentToken=token;
      const result=document.getElementById('couponResult');
      if(result){result.textContent='✅ '+(t('pay_voucher_valid')||'Voucher valid!');result.className='coupon-result success'}
      const amountEl=document.getElementById('costAmount');if(amountEl)amountEl.textContent='€ 0.00';
    }
  }catch(e){/* ignore */}
}

async function validateCoupon(){
  const code=(document.getElementById('couponCode').value||'').trim().toUpperCase();
  const email=(document.getElementById('couponEmail').value||'').trim()||lastVoucherEmail||prompt('Email:','');
  if(!code||!email)return;
  const result=document.getElementById('couponResult');
  if(result){result.innerHTML='<div class="sp"></div>';result.className='coupon-result'}
  try{
    const r=await fetch('/api/voucher_validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:code,email:email})});
    const d=await r.json();
    if(d.error){if(result){result.textContent=d.error;result.className='coupon-result error'}return}
    lastVoucherEmail=email;try{localStorage.setItem('abm_v_email',email)}catch(e){}
    if(result){result.textContent='✅ '+(t('pay_voucher_valid')||'Voucher valid!');result.className='coupon-result success'}
    const amountEl=document.getElementById('costAmount');if(amountEl)amountEl.textContent='€ 0.00';
    window._couponPaymentToken=d.payment_token;
  }catch(e){if(result){result.textContent='Error: '+e.message;result.className='coupon-result error'}}
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
    if(area)area.innerHTML='<span style="color:var(--ok);font-size:.84rem">✅ '+(t('email_late_ok')||'Email registered!')+'</span>';
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
  const known=['it','en','fr','es','de','zh','pt','nl','pl','ru','ja','ko'];
  if(!known.includes(bookLang)){banner.style.display='none';return;}
  const voiceLang=document.getElementById('vl').value;
  if(bookLang===voiceLang){banner.style.display='none';return;}
  const _names={
    it:{it:'italiano',en:'Italian',fr:'italien',es:'italiano',de:'Italienisch',zh:'意大利语'},
    en:{it:'inglese',en:'English',fr:'anglais',es:'inglés',de:'Englisch',zh:'英语'},
    fr:{it:'francese',en:'French',fr:'français',es:'francés',de:'Französisch',zh:'法语'},
    es:{it:'spagnolo',en:'Spanish',fr:'espagnol',es:'español',de:'Spanisch',zh:'西班牙语'},
    de:{it:'tedesco',en:'German',fr:'allemand',es:'alemán',de:'Deutsch',zh:'德语'},
    zh:{it:'cinese',en:'Chinese',fr:'chinois',es:'chino',de:'Chinesisch',zh:'中文'},
    pt:{it:'portoghese',en:'Portuguese',fr:'portugais',es:'portugués',de:'Portugiesisch',zh:'葡萄牙语'},
    ru:{it:'russo',en:'Russian',fr:'russe',es:'ruso',de:'Russisch',zh:'俄语'},
    ja:{it:'giapponese',en:'Japanese',fr:'japonais',es:'japonés',de:'Japanisch',zh:'日语'},
    ko:{it:'coreano',en:'Korean',fr:'coréen',es:'coreano',de:'Koreanisch',zh:'韩语'},
    nl:{it:'olandese',en:'Dutch',fr:'néerlandais',es:'neerlandés',de:'Niederländisch',zh:'荷兰语'},
    pl:{it:'polacco',en:'Polish',fr:'polonais',es:'polaco',de:'Polnisch',zh:'波兰语'},
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
  };
  banner.innerHTML=_msgs[cl]||_msgs.en;
  banner.style.display='';
}

function autoFixVoice(langCode){
  const sel=document.getElementById('vl');
  if(!sel||!sel.querySelector('option[value="'+langCode+'"]'))return;
  sel.value=langCode;
  updVoices();
  goToAudioSettings();
  // Brief highlight on both selectors to confirm the change
  [document.getElementById('vl'),document.getElementById('vv')].forEach(el=>{
    if(!el)return;
    el.style.transition='box-shadow .25s';
    el.style.boxShadow='0 0 0 3px var(--ac)';
    setTimeout(()=>{el.style.boxShadow='none'},1400);
  });
}

function goToAudioSettings(){goToStep(3)}

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
    const link=document.getElementById('cookieSettingsBtn');
    if(link){
      link.textContent=tr().title;
      link.addEventListener('click',function(e){e.preventDefault();show();});
    }
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
    const localized=(i18n&&typeof i18n==='object')?(i18n[ui]||''):'';
    const src=(srcLang||'').toLowerCase();
    const hasTr=!!localized && localized!==orig && (!src || src!==ui);
    return {text:hasTr?localized:orig, hasTr, orig, localized};
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
    const localized=(i18n&&typeof i18n==='object')?(i18n[ui]||''):'';
    const src=(srcLang||'').toLowerCase();
    const hasTr=!!localized && localized!==orig && (!src || src!==ui);
    return {text:hasTr?localized:orig, hasTr, orig, localized};
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