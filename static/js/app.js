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
      closeFreeBooks();
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
function t(k){return(L[cl]||L.en)[k]||(L.en)[k]||k}
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
          e.textContent = v;
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
  document.querySelectorAll('.lsw button').forEach(b=>b.classList.toggle('on',b.dataset.l===cl));
  document.documentElement.lang=cl;
  const btnExp=document.getElementById('btnExport');
  if(btnExp)btnExp.title=t('btn_export_abm_tip');
}
function setLang(l){cl=l;applyI18n();buildAbout();applySEO();try{localStorage.setItem('abm_l',l)}catch(e){}
  // Sync URL with selected language (SEO: URL ↔ content coherence)
  var p='/'+l+'/';if(location.pathname!==p)history.replaceState(null,'',p);
  // Switch visible SEO content block to match selected language
  if(typeof switchSeoLang==='function')switchSeoLang(l);
}
function detectLang(){
  // INIT_LANG è iniettato server-side: rispetta la lingua della URL (/it/, /en/, ecc.)
  if(typeof INIT_LANG!=='undefined'&&L[INIT_LANG])return INIT_LANG;
  try{const s=localStorage.getItem('abm_l');if(s&&L[s])return s}catch(e){}
  const n=(navigator.language||navigator.userLanguage||'en').toLowerCase().split('-')[0];
  return L[n]?n:'en';
}

// ═══════════════════ STATE ═══════════════════
let voices={},bookData=null,jobId=null,singleFile=true,generating=false,jobDone=false,hbInterval=null,isTxtFile=false,emailPromptShown=false,emailRegistered=false,emailCheckTimer=null,smtpAvailable=false;
let previewListened=false,_langWarnResolve=null;
let _googleTtsBudget=null; // {available, chars_remaining, chars_limit} or null
let aiOptEnabled=false,llmAvailable=false,aiAlreadyOptimized=false;
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
  cl=detectLang();applyI18n();buildAbout();applySEO();
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
  const fbBtn=document.getElementById('fbBtn');
  if(fbBtn)fbBtn.onclick=openFreeBooks;
  const fbClose=document.getElementById('fbClose');
  if(fbClose)fbClose.onclick=closeFreeBooks;
  const fbModal=document.getElementById('fbModal');
  if(fbModal)fbModal.onclick=e=>{if(e.target===e.currentTarget)closeFreeBooks()};
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
  // Email modal handlers
  const emSubmit=document.getElementById('emSubmit');
  if(emSubmit)emSubmit.onclick=submitEmail;
  const emSkip=document.getElementById('emSkip');
  if(emSkip)emSkip.onclick=skipEmail;
  const emClose=document.getElementById('emClose');
  if(emClose)emClose.onclick=skipEmail;
  // Email modal: persistent — no dismiss on overlay click (only explicit Skip or Submit)
  const emailModal=document.getElementById('emailModal');
  if(emailModal)emailModal.onclick=e=>{if(e.target===e.currentTarget)e.stopPropagation()};
  
  setupUpload();loadVoices();
  document.getElementById('btnG').onclick=startGen;
  document.getElementById('btnD').onclick=()=>downloadFile('zip');
  document.getElementById('btnM').onclick=()=>downloadFile('m4b');
  document.getElementById('btnP').onclick=downloadPodcast;
  document.getElementById('btnN').onclick=resetAll;
  document.getElementById('btnC').onclick=cancelJob;
  window.addEventListener('beforeunload',onBeforeUnload);
  document.getElementById('toS').onclick=function(){toggleOut(this)};
  document.getElementById('toC').onclick=function(){toggleOut(this)};
  // Initialize to M4B (toS) by default on load with a slight delay
  setTimeout(() => toggleOut(document.getElementById('toS')), 50);
  // Chapter selection handlers
  document.getElementById('selAll').onclick=chSelAll;
  document.getElementById('selNone').onclick=chSelNone;
  document.getElementById('selInv').onclick=chSelInvert;
  document.getElementById('chAll').onchange=chMasterToggle;
  _initAiOptToggle();
});

function toggleOut(el){
  el.closest('.tg').querySelectorAll('button').forEach(b=>b.classList.remove('on'));
  el.classList.add('on');singleFile=el.dataset.v==='single';
  document.getElementById('podHint').style.display=singleFile?'none':'';
  // Chapter selection UI is now ALWAYS visible
  updateSelection();
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

// ═══════════════════ ACCORDION ═══════════════════
function toggleStep(id){
  const el=document.getElementById(id);
  if(el.classList.contains('disabled')||el.classList.contains('locked'))return;
  el.classList.toggle('collapsed');
  if(!el.classList.contains('collapsed')){
    setTimeout(()=>el.scrollIntoView({behavior:'smooth',block:'nearest'}),100);
  }
}
function activateStep(id){
  const el=document.getElementById(id);
  el.classList.remove('collapsed','disabled');
  el.style.display='';
  setTimeout(()=>el.scrollIntoView({behavior:'smooth',block:'nearest'}),150);
}
function collapseStep(id){document.getElementById(id).classList.add('collapsed')}
function disableStep(id){const el=document.getElementById(id);el.classList.add('collapsed','disabled')}

function lockUI(){
  generating=true;
  ['s1','s2','s3'].forEach(id=>{const el=document.getElementById(id);el.classList.add('locked','collapsed','done')});
  document.getElementById('fi').disabled=true;
  const btnExp=document.getElementById('btnExport');if(btnExp)btnExp.disabled=true;
  previewStop(); _updatePreviewBtn();
}
function unlockUI(){
  generating=false;
  ['s1','s2','s3'].forEach(id=>document.getElementById(id).classList.remove('locked'));
  document.getElementById('fi').disabled=false;
  const btnExp=document.getElementById('btnExport');if(btnExp)btnExp.disabled=!bookData;
  _updatePreviewBtn();
}

function handleFile(file){
  if(generating||jobDone)return;
  const fn=file.name.toLowerCase();
  if(!fn.endsWith('.epub')&&!fn.endsWith('.pdf')&&!fn.endsWith('.txt')&&!fn.endsWith('.abm')){showErr('aerr',t('err_epub'));return}
  document.getElementById('uz').classList.add('ok');
  document.getElementById('ufn').textContent='✓ '+file.name;
  document.getElementById('ufn').style.display='block';
  document.getElementById('s1sum').textContent='✓ '+file.name;
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
  disableStep('s2');disableStep('s3');
  const fd=new FormData();fd.append('epub',file);
  try{
    const r=await fetch('/api/analyze',{method:'POST',body:fd});
    const d=await r.json();
    if(d.error){showErr('aerr',d.error);lo.classList.remove('vis');hideUploadProgress();return}
    bookData=d;jobId=d.job_id;lo.classList.remove('vis');hideUploadProgress();
    isTxtFile=(d.file_type==='txt');
    const isAbmFile=(d.file_type==='abm');
    llmAvailable=!!d.llm_available;aiAlreadyOptimized=!!d.ai_optimized;aiOptEnabled=false;
    _updateAiOptUI();
    if(d.language){
      const lc=d.language.split('-')[0].toLowerCase();
      const sel=document.getElementById('vl');
      if(sel.querySelector('option[value="'+lc+'"]')){sel.value=lc;}
    }
    // Rigenera la lista voci ora che bookData.total_chars è noto: serve a
    // nascondere proattivamente le voci Google se il libro supera il budget mensile.
    updVoices();
    // Set output mode based on file type
    if(isTxtFile){
      // TXT: force single file, hide output toggle and chapter table
      toggleOut(document.getElementById('toS'));
      document.getElementById('fgOut').style.display='none';
    }else{
      // EPUB/PDF/ABM: default to M4B mode
      document.getElementById('fgOut').style.display='';
      toggleOut(document.getElementById('toS'));
    }
    // Export button: always enabled after analysis
    const btnExp=document.getElementById('btnExport');
    if(btnExp)btnExp.disabled=false;
    fillPreview(d);
    _updatePreviewBtn();
    collapseStep('s1');document.getElementById('s1').classList.add('done');
    activateStep('s2');
    if(!isTxtFile)activateStep('s3');
    else{
      // TXT single chapter: skip step 3 preview, go straight to generate from s2
      activateStep('s3');
    }
  }catch(e){showErr('aerr','Error: '+e.message);lo.classList.remove('vis')}
}

// ═══════════════════ VOICES ═══════════════════
async function loadVoices(){
  try{
    const r=await fetch('/api/voices');
    const data=await r.json();
    console.log("[debug] loadVoices data keys:", Object.keys(data));
    // Estrai budget Google TTS e rimuovi la chiave speciale
    if(data._google_tts){
        _googleTtsBudget=data._google_tts;
        console.log("[debug] _googleTtsBudget:", _googleTtsBudget);
        delete data._google_tts;
    }
    else{
        console.warn("[debug] _google_tts info missing in API response");
        _googleTtsBudget=null;
    }
    voices=data;
    fillLangs();
  }catch(e){
    console.error('loadVoices failed:', e);
    alert('Failed to load TTS voices. Check server connection or logs. Error: ' + e.message);
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
  sel.onchange=()=>{_updateVoiceChip();checkVoiceMismatch();};
  _updateVoiceChip();checkVoiceMismatch();
  // Reset speed to "Normal" (+0%) whenever language or voice changes
  const vrSel=document.getElementById('vr');
  if(vrSel)vrSel.value='+0%';
}

// ═══════════════════ PREVIEW AUDIO ═══════════════════
let _prevWords=[], _prevText='', _prevDuration=0, _prevLoading=false;

function _updatePreviewBtn(){
  const btn=document.getElementById('btnPrev');
  if(!btn)return;
  const ok=!!(bookData&&bookData.preview_text&&!generating&&!jobDone);
  btn.disabled=!ok;
  btn.classList.remove('loading');
}

// Mostra: 'loading' (spinner) | 'play' (icona ▶) | 'pause' (icona ⏸)
function _prevShowState(state){
  const spinner=document.getElementById('prevSpinner');
  const btn    =document.getElementById('prevPlayBtn');
  const iPlay  =document.getElementById('prevIconPlay');
  const iPause =document.getElementById('prevIconPause');
  spinner.style.display = state==='loading' ? '' : 'none';
  btn.style.display     = state!=='loading' ? '' : 'none';
  iPlay.style.display   = state==='play'    ? '' : 'none';
  iPause.style.display  = state==='pause'   ? '' : 'none';
}

// Toglie play/pausa — se l'audio è finito, ricomincia dall'inizio
function prevPlayPause(){
  const audio=document.getElementById('prevAudio');
  if(!audio.src)return;
  if(audio.paused){
    if(audio.ended||audio.currentTime>=audio.duration-0.1){
      audio.currentTime=0;
      _prevWords.forEach(w=>w.classList.remove('hi'));
      document.getElementById('prevProgressFill').style.width='0%';
      document.getElementById('prevTime').textContent='0:00';
    }
    audio.play().catch(e=>console.error('[preview]',e));
  } else {
    audio.pause();
  }
}

function _prevBuildText(text){
  _prevText=text; _prevWords=[];
  const box=document.getElementById('prevText');
  box.innerHTML='';
  text.split(/(\s+)/).forEach(tok=>{
    if(/^\s+$/.test(tok)){
      box.appendChild(document.createTextNode(tok));
    } else {
      const sp=document.createElement('span');
      sp.className='pw'; sp.textContent=tok;
      _prevWords.push(sp); box.appendChild(sp);
    }
  });
}

function _prevHighlightAt(currentTime){
  if(!_prevWords.length||!_prevDuration)return;
  const idx=Math.min(
    Math.floor((currentTime/_prevDuration)*_prevWords.length),
    _prevWords.length-1
  );
  _prevWords.forEach((w,i)=>w.classList.toggle('hi',i===idx));
  _prevWords[idx].scrollIntoView({block:'nearest',behavior:'smooth'});
}

function prevSeek(ev){
  const audio=document.getElementById('prevAudio');
  if(!audio.src||!_prevDuration)return;
  const rect=ev.currentTarget.getBoundingClientRect();
  const ratio=(ev.clientX-rect.left)/rect.width;
  audio.currentTime=Math.max(0,Math.min(1,ratio))*_prevDuration;
}

function previewStop(){
  _prevLoading=false;
  const audio=document.getElementById('prevAudio');
  audio.pause(); audio.removeAttribute('src'); audio.load();
  _prevWords.forEach(w=>w.classList.remove('hi'));
  const m=document.getElementById('prevModal');
  if(m)m.classList.remove('open');
  const pf=document.getElementById('prevProgressFill');
  if(pf)pf.style.width='0%';
  const pt=document.getElementById('prevTime');
  if(pt)pt.textContent='0:00';
  _prevDuration=0;
  const spinner=document.getElementById('prevSpinner');
  const playBtn=document.getElementById('prevPlayBtn');
  if(spinner)spinner.style.display='none';
  if(playBtn)playBtn.style.display='none';
  _updatePreviewBtn();
}

async function previewRead(){
  if(_prevLoading)return;
  if(!bookData||!bookData.preview_text)return;

  _prevLoading=true;
  document.getElementById('btnPrev').disabled=true;
  document.getElementById('btnPrev').classList.add('loading');

  _prevShowState('loading');
  _prevBuildText(bookData.preview_text);
  document.getElementById('prevModal').classList.add('open');

  const voice=document.getElementById('vv').value;
  const rate =document.getElementById('vr').value;
  const audio=document.getElementById('prevAudio');

  const url='/api/preview_audio/'+bookData.job_id
    +'?voice='+encodeURIComponent(voice)
    +'&rate='+encodeURIComponent(rate);

  audio.ontimeupdate=()=>{
    const dur=audio.duration;
    if(!dur||!isFinite(dur))return;
    _prevDuration=dur;
    document.getElementById('prevProgressFill').style.width=(audio.currentTime/dur*100)+'%';
    const s=Math.floor(audio.currentTime);
    document.getElementById('prevTime').textContent=Math.floor(s/60)+':'+(s%60<10?'0':'')+(s%60);
    _prevHighlightAt(audio.currentTime);
  };
  // Sincronizza icona con stato audio
  audio.onplay  =()=>{previewListened=true;_prevShowState('pause')};
  audio.onpause =()=>{ if(!audio.ended) _prevShowState('play'); };
  audio.onended =()=>{
    _prevLoading=false;
    _prevShowState('play');  // ▶ per replay
    _prevWords.forEach(w=>w.classList.remove('hi'));
    _updatePreviewBtn();
  };
  audio.onerror=()=>{
    if(audio.error&&audio.error.code===audio.MEDIA_ERR_ABORTED)return;
    _prevLoading=false;
    document.getElementById('prevModal').classList.remove('open');
    _updatePreviewBtn();
    alert(t('prev_error'));
  };
  // Pronto: mostra ▶ senza avviare automaticamente
  audio.oncanplay=()=>{
    _prevLoading=false;
    _prevShowState('play');
    _updatePreviewBtn();
    audio.oncanplay=null;
  };

  audio.src=url;
  audio.load();
}

// ═══════════════════ PREVIEW (Book info - Step 3) ═══════════════════
function fillPreview(d){
  document.getElementById('bkT').textContent=d.title;
  document.getElementById('bkA').textContent=d.author?(t('by')+' '+d.author):'';
  // Cover image
  const coverImg=document.getElementById('bkCover');
  console.log('[cover] has_cover='+d.has_cover+', job_id='+d.job_id);
  if(d.has_cover&&d.job_id){
    coverImg.src='/api/cover/'+d.job_id;
    coverImg.style.display='';
    coverImg.onload=function(){console.log('[cover] loaded OK: '+this.naturalWidth+'x'+this.naturalHeight)};
    coverImg.onerror=function(){console.log('[cover] load FAILED');this.style.display='none'};
  }else{coverImg.style.display='none';coverImg.src=''}
  document.getElementById('smC').textContent=d.total_chapters;
  document.getElementById('smW').textContent=d.total_words.toLocaleString();
  document.getElementById('smD').textContent=fmtDur(d.estimated_minutes);
  document.getElementById('selTot').textContent=d.total_chapters;  const tb=document.getElementById('chl');tb.innerHTML='';
  for(const ch of d.chapters){
    const tr=document.createElement('tr');
    tr.dataset.idx=ch.index;
    tr.dataset.words=ch.words;
    tr.dataset.mins=ch.estimated_minutes;
    const selTd=document.createElement('td');
    selTd.className='col-sel';
    selTd.style.display=singleFile?'none':'';
    const cb=document.createElement('input');
    cb.type='checkbox';cb.checked=true;cb.dataset.idx=ch.index;
    cb.addEventListener('change',()=>{tr.classList.toggle('unchecked',!cb.checked);updateSelection()});
    selTd.appendChild(cb);
    tr.innerHTML='<td><span class="cn">'+ch.index+'.</span>'+esc(ch.title.substring(0,60))+'</td><td>'+ch.words.toLocaleString()+'</td><td>'+fmtDur(ch.estimated_minutes)+'</td>';
    tr.insertBefore(selTd,tr.firstChild);
    tr.style.cursor=singleFile?'':'pointer';
    tr.addEventListener('click',e=>{if(singleFile||e.target.tagName==='INPUT')return;cb.checked=!cb.checked;tr.classList.toggle('unchecked',!cb.checked);updateSelection()});
    tb.appendChild(tr);
  }
  // Master checkbox
  document.getElementById('chAll').checked=true;
  updateSelection();
  document.getElementById('s3sum').textContent=d.title.substring(0,25)+(d.title.length>25?'..':'')+' — '+d.total_chapters+' cap., '+d.total_words.toLocaleString()+' '+t('sum_w').toLowerCase();
  _updateVoiceChip();checkVoiceMismatch();
}

function updateSelection(){
  const boxes=document.querySelectorAll('#chl .col-sel input[type=checkbox]');
  let cnt=0,words=0,mins=0;
  boxes.forEach(cb=>{
    if(cb.checked){cnt++;const tr=cb.closest('tr');words+=parseInt(tr.dataset.words||0);mins+=parseFloat(tr.dataset.mins||0)}
  });
  document.getElementById('selCnt').textContent=cnt;
  
  // Selection UI is now always visible
  document.getElementById('thSel').style.display='';
  document.querySelectorAll('#chl .col-sel').forEach(td=>td.style.display='');
  document.querySelectorAll('#chl tr').forEach(tr=>tr.style.cursor='pointer');
  document.getElementById('selBar').classList.add('vis');

  // Update summary to reflect selection
  document.getElementById('smC').textContent=cnt+' / '+(bookData?bookData.total_chapters:boxes.length);
  document.getElementById('smW').textContent=words.toLocaleString();
  document.getElementById('smD').textContent=fmtDur(mins);

  // Master checkbox state
  const all=boxes.length;
  const master=document.getElementById('chAll');
  master.checked=cnt===all;
  master.indeterminate=cnt>0&&cnt<all;
  // Disable generate if none selected
  document.getElementById('btnG').disabled=(cnt===0);
}

function chSelAll(){document.querySelectorAll('#chl .col-sel input[type=checkbox]').forEach(cb=>{cb.checked=true;cb.closest('tr').classList.remove('unchecked')});updateSelection()}
function chSelNone(){document.querySelectorAll('#chl .col-sel input[type=checkbox]').forEach(cb=>{cb.checked=false;cb.closest('tr').classList.add('unchecked')});updateSelection()}
function chSelInvert(){document.querySelectorAll('#chl .col-sel input[type=checkbox]').forEach(cb=>{cb.checked=!cb.checked;cb.closest('tr').classList.toggle('unchecked',!cb.checked)});updateSelection()}
function chMasterToggle(){const v=document.getElementById('chAll').checked;document.querySelectorAll('#chl .col-sel input[type=checkbox]').forEach(cb=>{cb.checked=v;cb.closest('tr').classList.toggle('unchecked',!v)});updateSelection()}

// ═══════════════════ EXPORT ABM ═══════════════════
function exportAbm(){
  if(!jobId){showErr('s3err','No file analyzed yet');return}
  const a=document.createElement('a');
  a.href='/api/export_abm/'+jobId;
  a.download='';
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
  // Toggle buttons for AI optimization
  const btnOff=document.getElementById('optNone');
  const btnOn=document.getElementById('optEnable');
  if(!btnOff||!btnOn)return;
  btnOff.onclick=function(){
    aiOptEnabled=false;
    btnOff.classList.add('on');btnOn.classList.remove('on');
    document.getElementById('aiOptInfo').style.display='none';
    _updateOptButtons();
  };
  btnOn.onclick=function(){
    aiOptEnabled=true;
    btnOn.classList.add('on');btnOff.classList.remove('on');
    document.getElementById('aiOptInfo').style.display='';
    _updateOptButtons();
  };
}

function _updateOptButtons(){
  var btnOpt=document.getElementById('btnOptimize');
  if(btnOpt)btnOpt.style.display=(aiOptEnabled&&!aiAlreadyOptimized)?'':'none';
}

function _updateAiOptUI(){
  const wrap=document.getElementById('fgOptimizeWrap');
  if(!wrap)return;
  if(llmAvailable){
    wrap.style.display='';
    if(aiAlreadyOptimized){
      document.getElementById('aiAlreadyOpt').style.display='';
      document.getElementById('aiOptInfo').style.display='none';
      aiOptEnabled=false;
      document.getElementById('optNone').classList.add('on');
      document.getElementById('optEnable').classList.remove('on');
    }else{
      document.getElementById('aiAlreadyOpt').style.display='none';
    }
  }else{
    wrap.style.display='none';
    aiOptEnabled=false;
  }
  _updateOptButtons();
}

// Track whether the optimization email prompt has been shown
let optEmailPromptShown=false;

function _showOptEmailModal(){
  // Reuse the existing email modal but with optimization-specific content
  return new Promise(function(resolve){
    const modal=document.getElementById('optBatchModal');
    const errEl=document.getElementById('optBatchErr');
    const okEl=document.getElementById('optBatchOk');
    const btnsEl=document.getElementById('optBatchBtns');
    errEl.style.display='none';okEl.style.display='none';btnsEl.style.display='flex';
    document.getElementById('optAutoGen').checked=false;
    var emailEl=document.getElementById('optBatchEmail');
    emailEl.removeAttribute('readonly');emailEl.style.background='';emailEl.style.color='';
    emailEl.value=lastVoucherEmail;
    applyI18n();
    modal.classList.add('open');
    document.getElementById('optBatchClose').onclick=function(){modal.classList.remove('open');resolve(null)};
    document.getElementById('optBatchCancel').onclick=function(){modal.classList.remove('open');resolve(null)};
    document.getElementById('optBatchSubmit').onclick=function(){
      var email=document.getElementById('optBatchEmail').value.trim();
      if(!email||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)){
        errEl.textContent=t('opt_batch_email_err')||'Enter a valid email address';
        errEl.style.display='';return;
      }
      lastVoucherEmail=email;
      try{localStorage.setItem('abm_v_email',email)}catch(e){}
      errEl.style.display='none';
      var autoGen=document.getElementById('optAutoGen').checked;
      // Register email and batch params on the server
      var payload={
        job_id:jobId,batch:true,
        email:email,
        auto_generate:autoGen,
        lang:cl
      };
      if(autoGen){
        payload.voice=document.getElementById('vv').value;
        payload.rate=document.getElementById('vr').value;
        payload.single_file=singleFile;
      }
      fetch('/api/register_opt_email',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
      .then(function(r){return r.json()})
      .then(function(d){
        if(d.error){errEl.textContent=d.error;errEl.style.display='';return}
        btnsEl.style.display='none';
        var emailEl=document.getElementById('optBatchEmail');
        emailEl.setAttribute('readonly','readonly');
        emailEl.style.background='var(--srf2)';
        emailEl.style.color='var(--txd)';
        var msgKey=autoGen?'opt_batch_started_auto':'opt_batch_started';
        okEl.textContent=t(msgKey)||'Email registered! You can close this page.';
        okEl.style.display='';
        optEmailPromptShown=true;
        resolve({email:email,autoGenerate:autoGen});
      })
      .catch(function(e){errEl.textContent='Error: '+e.message;errEl.style.display=''});
    };
  });
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

async function startOptimization(){
  if(!jobId){return}

  // Check sospensione nuovi processi (admin toggle)
  try{
    const sr = await fetch('/api/admin/suspend');
    if(sr.ok){
      const sd = await sr.json();
      if(sd.suspended){
        alert('System under maintenance. Please try again in a few minutes.');
        return;
      }
    }
  }catch(e){}

  if(!(await _validateLanguage())) return;
  document.getElementById('s3err').innerHTML='';
  
  // Collect selected chapters from UI
  let selectedChapters=[];
  document.querySelectorAll('#chl .col-sel input[type=checkbox]').forEach(cb=>{
    if(cb.checked)selectedChapters.push(parseInt(cb.dataset.idx));
  });
  console.log('[optimize] selected chapters:', selectedChapters.length, '/', bookData?.total_chapters, 'indices:', JSON.stringify(selectedChapters));
  if(selectedChapters.length===0){showS3Err(t('sel_err_none')||'Select at least one chapter');return}


  // ── Check cost estimate first ──
  var paymentToken=null;
  try{
    let url=new URL('/api/optimize_estimate/'+jobId, window.location.origin);
    const selLang = document.getElementById('vl').value || cl;
    url.searchParams.append('lang', selLang);
    if(selectedChapters&&selectedChapters.length>0){
        selectedChapters.forEach(idx => url.searchParams.append('selected_chapters', idx));
    }
    var est=await fetch(url.toString()).then(function(r){return r.json()});
    if(est.error){showS3Err(est.error);return}
    if(est.requires_payment){
      // Refresh config from server
      try{var cfg=await fetch('/api/llm_available').then(function(r){return r.json()});
        llmConfig.rate=cfg.rate_eur_per_mchar||1.1;
        llmConfig.threshold=cfg.free_threshold_eur||0.5;
        llmConfig.bonus=cfg.voucher_bonus_percent||10;
        llmConfig.expiry=cfg.voucher_expiry_days||180;
        llmConfig.paypalClientId=cfg.paypal_client_id||"";
        llmConfig.paypalMode=cfg.paypal_mode||"sandbox";
        llmConfig.paypalAvailable=!!cfg.paypal_available;
      }catch(e){}
      paymentToken=await _showPaymentModal(est.cost_eur,est.chars);
      if(!paymentToken){return} // user cancelled
    }
  }catch(e){showS3Err('Estimate error: '+e.message);return}

  document.getElementById('btnG').disabled=true;
  document.getElementById('btnOptimize').disabled=true;
  optEmailPromptShown=false;
  // Show step 4 with optimization progress
  var s4=document.getElementById('s4');s4.style.display='';s4.classList.remove('collapsed');s4.classList.add('fi');
  document.getElementById('s4t').textContent=t('s4_opt_title')||'AI Text Optimization';
  if(bookData){
    document.getElementById('s4bkT').textContent=bookData.title||'';
    document.getElementById('s4bkA').textContent=bookData.author?(t('by')+' '+bookData.author):'';
    var sc=document.getElementById('s4bkCover'),s3c=document.getElementById('bkCover');
    if(s3c.src&&s3c.style.display!=='none'){sc.src=s3c.src;sc.style.display=''}
    else{sc.style.display='none';sc.src=''}
  }
  document.getElementById('pMsg').textContent=t('opt_starting')||'Starting AI text optimization...';
  document.getElementById('pBar').style.width='0%';
  document.getElementById('pPct').textContent='0%';
  // Hide generation-specific stats
  document.querySelectorAll('#pra .ps').forEach(function(el){el.style.display='none'});
  // Riallinea il bottone Annulla al contesto ottimizzazione AI: cambia label e handler
  _setCancelButtonMode('opt');
  lockUI();
  setTimeout(function(){const genPanel=document.getElementById('s3');if(genPanel)genPanel.scrollIntoView({behavior:'smooth',block:'start'})},200);
  try{
    const selLang = document.getElementById('vl').value || cl;
    var payload={job_id:jobId,batch:false,lang:selLang};
    if(paymentToken)payload.payment_token=paymentToken;
    if(selectedChapters)payload.selected_chapters=selectedChapters;
    var r=await fetch('/api/optimize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    var d=await r.json();
    if(d.error){
      if(d.error_code==='llm_concurrent_limit'){
        document.getElementById('pMsg').textContent=t('llm_concurrent_limit')||d.error;
        document.getElementById('pMsg').style.color='var(--err)';
      }else{showPErr(d.error)}
      unlockUI();return;
    }
    listenOptProgress();
  }catch(e){showPErr('Error: '+e.message);unlockUI()}
}

function showS3Err(msg){
  var s3err=document.getElementById('s3err');
  if(s3err){s3err.textContent=msg;s3err.style.color='var(--err)'}
}

function listenOptProgress(){
  var es=new EventSource('/api/optimize_progress/'+jobId);
  es.onmessage=function(ev){
    var d=JSON.parse(ev.data);
    if(d.status==='error'){
      es.close();_setCancelButtonMode('gen');showPErr(d.error||'Optimization error');unlockUI();return;
    }
    if(d.status==='cancelled'){
      es.close();
      _setCancelButtonMode('gen');
      document.getElementById('pMsg').textContent=t('opt_cancelled')||'Optimization cancelled';
      unlockUI();return;
    }
    if(d.status==='optimized'){
      es.close();
      _setCancelButtonMode('gen');
      aiAlreadyOptimized=true;aiOptEnabled=false;
      _updateAiOptUI();
      document.getElementById('pMsg').textContent=t('opt_done')||'Text optimization complete!';
      document.getElementById('pBar').style.width='100%';
      document.getElementById('pPct').textContent='100%';
      // Show buttons: generate audiobook + download .ABM
      var cnA=document.getElementById('cnA');
      cnA.innerHTML='<div style="display:flex;flex-direction:column;gap:10px;align-items:center;margin-top:12px">'
        +'<button class="btn btn-ok" id="btnProceedGen" style="width:100%;max-width:400px">&#x1F3A7; '+(t('opt_proceed_gen')||'Generate audiobook')+'</button>'
        +'<button class="btn btn-g" id="btnDownloadAbm" style="width:100%;max-width:400px">&#x1F4E5; '+(t('opt_download_abm')||'Download optimized project (.abm)')+'</button>'
        +'</div>';
      document.getElementById('btnProceedGen').onclick=function(){
        var bpg=document.getElementById('btnProceedGen');
        if(bpg.disabled)return;
        bpg.disabled=true;
        bpg.style.opacity='0.6';
        bpg.style.cursor='not-allowed';
        var bda=document.getElementById('btnDownloadAbm');
        if(bda){bda.disabled=true;bda.style.opacity='0.6';bda.style.cursor='not-allowed';}
        document.getElementById('s4').style.display='none';
        unlockUI();
        document.getElementById('btnG').disabled=false;
        if(document.getElementById('btnOptimize'))document.getElementById('btnOptimize').disabled=false;
        startGen();
      };
      document.getElementById('btnDownloadAbm').onclick=function(){
        fetch('/api/export_abm/'+jobId).then(function(r){
          if(!r.ok)throw new Error('Export failed');
          return r.blob();
        }).then(function(blob){
          var a=document.createElement('a');a.href=URL.createObjectURL(blob);
          a.download=(bookData&&bookData.title?bookData.title:'project')+'_optimized.abm';
          a.click();URL.revokeObjectURL(a.href);
        }).catch(function(e){alert('Error: '+e.message)});
      };
      unlockUI();return;
    }
    if(d.auto_generate_started){
      es.close();
      _setCancelButtonMode('gen');
      document.getElementById('s4t').textContent=t('s4_title')||'Generation';
      // L'email è già registrata lato server (batch mode). Evita il re-prompt nella fase TTS.
      emailRegistered=true;emailPromptShown=true;
      listenProgress();
      return;
    }
    // Update optimization progress (character-based for smooth updates).
    // IMPORTANTE: sia numeratore sia denominatore devono essere in unità di
    // caratteri di INPUT. opt_processed_chars somma i char *originali* dei
    // capitoli completati; opt_streamed_chars è output LLM (espanso), quindi
    // lo limitiamo alla dimensione del capitolo corrente per evitare che la
    // barra sfori prima che il capitolo termini.
    var totalChars=d.opt_total_chars||1;
    var doneChars=d.opt_processed_chars||0;
    var curChChars=d.opt_current_chapter_chars||0;
    var streamedChars=Math.min(d.opt_streamed_chars||0,curChChars);
    var workedChars=doneChars+streamedChars;
    var pct=Math.min(99,Math.round(workedChars/totalChars*100));
    document.getElementById('pBar').style.width=pct+'%';
    document.getElementById('pPct').textContent=pct+'%';
    document.getElementById('pMsg').textContent=d.opt_progress_message||'';

    // Chapter title (pCh)
    var pChEl=document.getElementById('pCh');
    if(pChEl&&d.opt_current_chapter){
      pChEl.textContent='Cap. '+(d.opt_current_chapter_num||'?')+'/'+(d.opt_progress_total||'?')+': '+String(d.opt_current_chapter).substring(0,40);
    }

    // Chapter counter (xCh)
    if(d.opt_progress_total>0){
      var xChEl=document.getElementById('xCh');
      if(xChEl){xChEl.textContent=(d.opt_current_chapter_num||0)+' / '+d.opt_progress_total;xChEl.closest('.ps').style.display=''}
    }

    // Elapsed (xEl)
    if(d.opt_elapsed_seconds>0){
      var el=document.getElementById('xEl');
      if(el){el.textContent=fmtTime(d.opt_elapsed_seconds);el.closest('.ps').style.display=''}
    }

    // ETA (xEta) + Speed (xSpd) — calcolati sui char/sec reali
    if(workedChars>0&&d.opt_elapsed_seconds>1&&totalChars>0){
      var cps=workedChars/d.opt_elapsed_seconds;
      var left=Math.max(0,totalChars-workedChars);
      var eta=Math.round(left/cps);
      var xEtaEl=document.getElementById('xEta');
      if(xEtaEl){xEtaEl.textContent=eta>0?'~'+fmtTime(eta):t('almost');xEtaEl.closest('.ps').style.display=''}
      var xSpdEl=document.getElementById('xSpd');
      if(xSpdEl){xSpdEl.textContent=Math.round(cps)+' '+t('cps');xSpdEl.closest('.ps').style.display=''}
    }

    // Generated chars so far (xSz) — mostrato come numero di caratteri ottimizzati
    if(workedChars>0){
      var xSzEl=document.getElementById('xSz');
      if(xSzEl){xSzEl.textContent=workedChars.toLocaleString(cl||'it')+' char';xSzEl.closest('.ps').style.display=''}
    }
    // After 5 seconds, show email modal if SMTP available and not yet shown
    if(!optEmailPromptShown&&smtpAvailable&&d.opt_elapsed_seconds>=5){
      optEmailPromptShown=true;
      _showOptEmailModal();
    }
  };
  es.onerror=function(){es.close()};
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
    if(!gen||parseInt(gen)<1)return false; // first-time user → skip
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
  _suppressDonate(3); // X close → reappear after 3 days
  if(_donateModalResolve){_donateModalResolve(true);_donateModalResolve=null}
}

function onDonateModal(action){
  document.getElementById('donateModal').classList.remove('open');
  _suppressDonate(30); // donate or "already donated" → suppress 30 days
  if(_donateModalResolve){_donateModalResolve(true);_donateModalResolve=null}
}

async function startGen(){
  // Check sospensione nuovi processi (admin toggle) — prima di qualsiasi modifica UI
  try{
    const sr = await fetch('/api/admin/suspend');
    if(sr.ok){
      const sd = await sr.json();
      if(sd.suspended){
        alert('System under maintenance. Please try again in a few minutes.');
        return;
      }
    }
  }catch(e){}

  if(!(await _validateLanguage())) return;
  // Donate modal: show for returning users before generation starts
  if(_shouldShowDonateModal()){
    await _showDonateModal();
  }
  // Mark this generation so the modal can appear next time
  _markGeneration();
  // Collect selected chapter indices
  let selectedChapters=[];
  document.querySelectorAll('#chl .col-sel input[type=checkbox]').forEach(cb=>{
    if(cb.checked)selectedChapters.push(parseInt(cb.dataset.idx));
  });
  console.log('[generate] selected chapters:', selectedChapters.length, '/', bookData?.total_chapters, 'indices:', JSON.stringify(selectedChapters));
  if(selectedChapters.length===0){showErr('s3err',t('sel_err_none'));return}
  // Check if "all" chapters are selected to optionally send null or full list
  // The backend supports filtering, so always sending them is safer.

  document.getElementById('s3err').innerHTML='';
  document.getElementById('btnG').disabled=true;
  // Set s2 summary for collapsed state
  const vSel=document.getElementById('vv');
  const vName=vSel.options[vSel.selectedIndex]?vSel.options[vSel.selectedIndex].text:'';
  const rSel=document.getElementById('vr');
  const rName=rSel.options[rSel.selectedIndex]?rSel.options[rSel.selectedIndex].text:'';
  document.getElementById('s2sum').textContent=vName+' — '+rName;
  lockUI();
  const s4=document.getElementById('s4');s4.style.display='';s4.classList.remove('collapsed');s4.classList.add('fi');
  if(bookData){document.getElementById('s4bkT').textContent=bookData.title||'';document.getElementById('s4bkA').textContent=bookData.author?(t('by')+' '+bookData.author):'';var sc=document.getElementById('s4bkCover'),s3c=document.getElementById('bkCover');if(s3c.src&&s3c.style.display!=='none'){sc.src=s3c.src;sc.style.display='';sc.onerror=function(){this.style.display='none'}}else{sc.style.display='none';sc.src=''}}
  document.getElementById('pMsg').textContent=t('starting');
  // Scroll to generation panel (s3 or btnG) instead of step 4 to keep button visible
  setTimeout(()=>{const genPanel=document.getElementById('s3');const btnG=document.getElementById('btnG');if(genPanel)genPanel.scrollIntoView({behavior:'smooth',block:'start'})},200);
  try{
    const payload={job_id:jobId,voice:document.getElementById('vv').value,rate:document.getElementById('vr').value,single_file:singleFile};
    if(selectedChapters)payload.selected_chapters=selectedChapters;
    const r=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)});
    const d=await r.json();
    if(d.error){
      if(d.error_code==='concurrent_limit'){
        // Show error in pMsg without destroying pra DOM structure
        document.getElementById('pMsg').textContent=t('concurrent_limit')||d.error;
        document.getElementById('pMsg').style.color='var(--err)';
        document.getElementById('pBar').style.width='0%';
        document.getElementById('pPct').textContent='';
        document.getElementById('pCh').textContent='';
        document.querySelectorAll('#pra .ps').forEach(function(el){el.style.display='none'});
        // Replace cancel button with retry
        document.getElementById('cnA').innerHTML=
          '<button class="btn btn-ok" id="btnRetry">🔄 '+(t('btn_retry')||'Retry generation')+'</button>';
        document.getElementById('btnRetry').onclick=retryGen;
        unlockUI();return
      }
      if(d.error_code==='google_tts_budget'){
        document.getElementById('pMsg').innerHTML=(t('google_tts_budget_err')||d.error);
        document.getElementById('pMsg').style.color='var(--err)';
        document.getElementById('pBar').style.width='0%';
        document.getElementById('pPct').textContent='';
        document.getElementById('pCh').textContent='';
        document.querySelectorAll('#pra .ps').forEach(function(el){el.style.display='none'});
        document.getElementById('cnA').innerHTML=
          '<button class="btn btn-ok" id="btnRetry">🔄 '+(t('btn_retry')||'Retry generation')+'</button>';
        document.getElementById('btnRetry').onclick=retryGen;
        unlockUI();return
      }
      showPErr(d.error);
      unlockUI();return
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
      retries=0;  // Reset su messaggio ricevuto
      const d=JSON.parse(ev.data);
      if(d.status==='error'){es.close();showPErr(d.error);unlockUI();generating=false;document.getElementById('cnA').style.display='none';document.getElementById('emailModal').classList.remove('open');return}
      if(d.status==='cancelled'){es.close();document.getElementById('pMsg').textContent=t('cancelled_msg');document.getElementById('pMsg').style.color='var(--err)';document.getElementById('cnA').style.display='none';document.getElementById('emailModal').classList.remove('open');unlockUI();generating=false;return}

      const pct=d.progress_total>0?Math.round(d.progress_current/d.progress_total*100):0;
      document.getElementById('pPct').textContent=pct+'%';
      document.getElementById('pBar').style.width=pct+'%';
      document.getElementById('pMsg').textContent=d.progress_message||'';

      if(d.current_chapter)
        document.getElementById('pCh').textContent='Cap. '+d.current_chapter_num+'/'+d.total_chapters+': '+d.current_chapter.substring(0,40);
      if(d.progress_total>0)
        document.getElementById('xBlk').textContent=d.progress_current+' / '+d.progress_total;
      if(d.total_chapters>0)
        document.getElementById('xCh').textContent=d.current_chapter_num+' / '+d.total_chapters;
      if(d.elapsed_seconds>0)
        document.getElementById('xEl').textContent=fmtTime(d.elapsed_seconds);

      // ETA basata su chars/sec reale
      if(d.processed_chars>0&&d.elapsed_seconds>1&&d.total_chars>0){
        const cps=d.processed_chars/d.elapsed_seconds;
        const left=d.total_chars-d.processed_chars;
        const eta=Math.round(left/cps);
        document.getElementById('xEta').textContent=eta>0?'~'+fmtTime(eta):t('almost');
        document.getElementById('xSpd').textContent=Math.round(cps)+' '+t('cps');
        // Email prompt: after 5s elapsed, ETA > 1min, chapter mode, SMTP available
        if(!emailPromptShown&&!emailRegistered&&smtpAvailable&&d.elapsed_seconds>=5&&(d.elapsed_seconds+eta)>60){
          emailPromptShown=true;
          showEmailModal();
        }
      }
      if(d.bytes_generated>0)
        document.getElementById('xSz').textContent=fmtBytes(d.bytes_generated);

      // Update progress message (including M4B conversion feedback)
      let msg = d.progress_message || '';
      if(msg === "Converting to M4B...") {
          msg = t('converting_m4b') || msg;
      }
      document.getElementById('pMsg').textContent=msg;

      if(d.status==='done'){
        es.close();
        generating=false;
        jobDone=true;
        document.getElementById('pPct').textContent='100%';
        document.getElementById('pBar').style.width='100%';
        document.getElementById('pMsg').textContent=t('done_msg');
        document.getElementById('pMsg').style.color='var(--ok)';

        // M4B retry/fallback warning
        if(d.m4b_failed){
          const warn = document.createElement('div');
          warn.className = 'al al-warn';
          warn.style.marginTop = '10px';
          warn.textContent = t('m4b_warn_mp3');
          document.getElementById('pra').appendChild(warn);
        }

        if(d.failed_chunks>0){
          document.getElementById('pMsg').textContent=t('done_msg')+' (⚠ '+d.failed_chunks+' chunk skipped)';
          document.getElementById('pMsg').style.color='#d97706';
        }
        document.getElementById('xEta').textContent='-';
        document.getElementById('dlA').style.display='block';
        document.getElementById('dlA').classList.add('fi');
        
        // Dynamic main download button (btnD) based on Step 2 selection
        const btnD = document.getElementById('btnD');
        if (singleFile) {
          // M4B choice
          btnD.innerHTML = '&#x1F4D6;&#xFE0F; ' + (t('btn_dl_m4b') || 'Download Audiolibro M4B');
          btnD.onclick = () => downloadFile('m4b');
        } else {
          // ZIP choice
          btnD.innerHTML = '&#x1F4C2;&#xFE0F; ' + t('out_zip');
          btnD.onclick = () => downloadFile('zip');
        }

        // Secondary download buttons
        document.getElementById('btnM').style.display = (singleFile ? false : d.output_m4b) ? '' : 'none';
        document.getElementById('btnA').style.display = d.has_abm ? '' : 'none';
        document.getElementById('btnA').onclick = () => downloadFile('abm');
        document.getElementById('btnP').style.display = d.has_podcast ? '' : 'none';
        // Show "back to chapters" button if the book has multiple chapters
        document.getElementById('btnBackCh').style.display=(bookData&&bookData.total_chapters>1)?'':'none';
        document.getElementById('s4t').textContent=t('done_t');
        document.getElementById('cnA').style.display='none';
        document.getElementById('emailModal').classList.remove('open');
        // Heartbeat: segnala al server che il client è ancora sulla pagina
        hbInterval=setInterval(()=>{if(jobId)navigator.sendBeacon('/api/heartbeat/'+jobId)},10000);
        // Manda subito il primo heartbeat (evita gap iniziale)
        if(jobId)navigator.sendBeacon('/api/heartbeat/'+jobId);
        // Heartbeat extra quando la tab torna in primo piano
        // (Chrome throttla setInterval in background, ma visibilitychange NO)
        document._hbVis=()=>{if(!document.hidden&&jobId&&jobDone)navigator.sendBeacon('/api/heartbeat/'+jobId)};
        document.addEventListener('visibilitychange',document._hbVis);
        // UI resta locked fino a "nuovo"
      }
    };
    es.onerror=()=>{
      es.close();
      if(retries<maxRetries&&generating){
        retries++;
        // Riconnessione progressiva: 2s, 4s, 6s, 8s, 10s
        setTimeout(connect,retries*2000);
      }
    };
  }
  connect();
}

// Imposta label + handler del bottone Annulla in base al contesto:
//   'opt' = ottimizzazione AI in corso  →  'Annulla ottimizzazione' / cancelOptimization
//   'gen' = generazione audio TTS       →  'Annulla' / cancelJob
function _setCancelButtonMode(mode){
  var btnC=document.getElementById('btnC');
  if(!btnC)return;
  if(mode==='opt'){
    btnC.innerHTML='\u23F9\uFE0F '+(t('btn_cancel_opt')||'Cancel optimization');
    btnC.onclick=cancelOptimization;
  }else{
    btnC.innerHTML='\u23F9\uFE0F '+(t('btn_cancel')||'Cancel');
    btnC.onclick=cancelJob;
  }
}

function cancelOptimization(){
  if(!jobId)return;
  try{navigator.sendBeacon('/api/cancel_optimize/'+jobId);}catch(e){}
  document.getElementById('pMsg').textContent=t('opt_cancelled')||'Optimization cancelled';
  // Ripristina label di default per i cicli successivi
  _setCancelButtonMode('gen');
  unlockUI();
  document.getElementById('btnG').disabled=false;
  if(document.getElementById('btnOptimize'))document.getElementById('btnOptimize').disabled=false;
  var s4=document.getElementById('s4');if(s4)s4.style.display='none';
}

function cancelJob(){
  if(!jobId||!generating)return;
  navigator.sendBeacon('/api/cancel/'+jobId+'?force=1');
  generating=false;
  unlockUI();
  document.getElementById('s4').style.display='none';
  document.getElementById('dlA').style.display='none';
  document.getElementById('btnP').style.display='none';
  document.getElementById('btnBackCh').style.display='none';
  document.getElementById('cnA').style.display='';
  document.getElementById('pBar').style.width='0%';
  document.getElementById('pPct').textContent='0%';
  document.getElementById('pCh').textContent='';
  document.getElementById('xBlk').textContent='—';
  document.getElementById('xCh').textContent='—';
  document.getElementById('xEl').textContent='—';
  document.getElementById('xEta').textContent='—';
  document.getElementById('xSz').textContent='—';
  document.getElementById('xSpd').textContent='—';
  // Restore progress area if it was hidden
  document.querySelectorAll('#pra .ps').forEach(function(el){el.style.display=''});
  document.getElementById('pMsg').textContent='';
  document.getElementById('pMsg').style.color='';
  document.getElementById('btnG').disabled=false;
  // Keep step 3 OPEN (remove collapsed class) so user can restart generation
  const s3=document.getElementById('s3');
  if(s3){
    s3.classList.remove('collapsed');
    s3.classList.remove('locked');
  }
  // Scroll to step 3 to show the panel
  setTimeout(()=>{if(s3)s3.scrollIntoView({behavior:'smooth',block:'start'})},100);
}

function retryGen(){
  // Restore cancel button
  document.getElementById('cnA').innerHTML=
    '<button class="btn btn-g" id="btnC" style="border-color:var(--err);color:var(--err)">\u23F9\uFE0F '+(t('btn_cancel')||'Cancel')+'</button>';
  document.getElementById('btnC').onclick=cancelJob;
  // Restore progress area
  document.querySelectorAll('#pra .ps').forEach(function(el){el.style.display=''});
  document.getElementById('pMsg').textContent='';
  document.getElementById('pMsg').style.color='';
  document.getElementById('pPct').textContent='0%';
  // Retry generation
  startGen();
}

// ═══════════════════ EMAIL NOTIFICATION ═══════════════════
function showEmailModal(){
  const m=document.getElementById('emailModal');
  document.getElementById('emTitle').textContent='📧 '+t('email_title');
  document.getElementById('emDesc').textContent=t('email_desc');
  document.getElementById('emDlLabel').textContent=t('email_dl_type');
  document.getElementById('emDlAudioL').textContent=t('email_dl_audio');
  document.getElementById('emDlPodcastL').textContent=t('email_dl_podcast');
  document.getElementById('emBaseUrlLabel').textContent=t('email_base_url');
  document.getElementById('emEmail').placeholder=t('email_placeholder');
  document.getElementById('emEmail').value=lastVoucherEmail;
  document.getElementById('emSubmit').textContent=t('email_btn');
  document.getElementById('emSkip').textContent=t('email_skip');
  document.getElementById('emErr').style.display='none';
  document.getElementById('emOk').style.display='none';
  document.getElementById('emBtns').style.display='flex';
  document.getElementById('emDlType').style.display=singleFile?'none':'';
  document.getElementById('emBaseUrlWrap').style.display='none';
  // Reset radio to "audio" every time modal opens
  document.querySelectorAll('input[name="emDl"]').forEach((r,i)=>{r.checked=i===0});
  // Radio change: show/hide base URL field
  document.querySelectorAll('input[name="emDl"]').forEach(r=>{
    r.onchange=()=>{
      document.getElementById('emBaseUrlWrap').style.display=
        document.querySelector('input[name="emDl"]:checked').value==='podcast'?'':'none';
    };
  });
  m.classList.add('open');
}

async function submitEmail(){
  const email=document.getElementById('emEmail').value.trim();
  const errEl=document.getElementById('emErr');
  errEl.style.display='none';
  // Validate email client-side
  if(!email||!/^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/.test(email)){
    errEl.textContent=t('email_invalid');errEl.style.display='block';return;
  }
  lastVoucherEmail=email;
  try{localStorage.setItem('abm_v_email',email)}catch(e){}
  const dlType=document.querySelector('input[name="emDl"]:checked').value;
  const baseUrl=document.getElementById('emBaseUrl').value.trim();
  if(dlType==='podcast'&&!baseUrl){
    errEl.textContent=t('email_base_url');errEl.style.display='block';return;
  }
  try{
    const r=await fetch('/api/register_email',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({job_id:jobId,email:email,download_type:dlType,base_url:baseUrl,lang:cl})});
    const d=await r.json();
    if(d.error){
      errEl.textContent=d.error==='Email service not configured on this server'?t('email_unavail'):d.error;
      errEl.style.display='block';return;
    }
    emailRegistered=true;
    document.getElementById('emBtns').style.display='none';
    document.getElementById('emDlType').style.display='none';
    document.getElementById('emBaseUrlWrap').style.display='none';
    document.getElementById('emEmail').style.display='none';
    document.getElementById('emDesc').style.display='none';
    document.getElementById('emOk').textContent=t('email_ok');
    document.getElementById('emOk').style.display='block';
    // Show inline status indicator in step 4
    document.getElementById('emailStatusText').textContent=t('email_ok');
    document.getElementById('emailStatus').style.display='block';
    // Auto-close after 5 seconds
    setTimeout(()=>{document.getElementById('emailModal').classList.remove('open')},5000);
  }catch(e){errEl.textContent='Error: '+e.message;errEl.style.display='block'}
}

function skipEmail(){
  document.getElementById('emailModal').classList.remove('open');
}

// Check SMTP availability on page load
async function checkSmtp(){
  try{
    const r=await fetch('/api/email_available');
    const d=await r.json();
    smtpAvailable=d.available===true;
  }catch(e){smtpAvailable=false}
}
checkSmtp();

async function downloadFile(type){
  if(!jobId)return;
  let btnId = 'btnD';
  if(type === 'm4b') btnId = 'btnM';
  if(type === 'abm') btnId = 'btnA';
  if(type === 'zip') btnId = 'btnD';
  
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
      if(!r.ok){
        const txt=await r.text();
        showPErr(txt||'Download failed');
        btn.disabled=false;btn.innerHTML=originalHtml;
        return;
      }
      const blob=await r.blob();
      const cd=r.headers.get('Content-Disposition')||'';
      const m=cd.match(/filename[^;=\n]*=['"]?([^'";\n]*)/);
      let defName = 'audiobook.zip';
      if(type === 'm4b') defName = 'audiobook.m4b';
      if(type === 'abm') defName = 'project.abm';
      const fname=m?m[1]:defName;
      
      const a=document.createElement('a');
      a.href=URL.createObjectURL(blob);
      a.download=fname;
      document.body.appendChild(a);a.click();
      setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},1000);
      
      let successT = t('btn_dl');
      if(type === 'm4b') successT = t('btn_dl_m4b');
      if(type === 'abm') successT = t('btn_dl_abm');
      btn.innerHTML='✅ <span>'+successT+'</span>';
      btn.disabled=false;
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
    if(!r.ok){
      const txt=await r.text();
      showPErr(txt||'Download failed');
      btn.disabled=false;btn.innerHTML='🎙️ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';
      return;
    }
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
  }catch(e){
    showPErr('Download error: '+e.message);
    btn.disabled=false;btn.innerHTML='🎙️ <span data-t="btn_dl_podcast">'+t('btn_dl_podcast')+'</span>';
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
  // Stop heartbeat
  if(hbInterval){clearInterval(hbInterval);hbInterval=null}
  if(document._hbVis){document.removeEventListener('visibilitychange',document._hbVis);document._hbVis=null}
  // Ask backend to reset job status
  try{
    const r=await fetch('/api/reset_to_chapters/'+jobId,{method:'POST'});
    const d=await r.json();
    if(d.error){showErr('s3err',d.error);return}
  }catch(e){
    // If backend fails, still allow UI reset (job data might be lost on restart)
    console.warn('[goBack] reset endpoint failed:',e);
  }
  // Reset UI state
  jobDone=false;
  generating=false;
  emailPromptShown=false;emailRegistered=false;
  // Hide step 4
  document.getElementById('s4').style.display='none';
  document.getElementById('dlA').style.display='none';
  document.getElementById('btnM').style.display='none';
  document.getElementById('btnP').style.display='none';
  document.getElementById('btnBackCh').style.display='none';
  document.getElementById('cnA').style.display='';
  document.getElementById('pBar').style.width='0%';
  document.getElementById('pPct').textContent='0%';
  document.getElementById('pMsg').style.color='';
  ['xBlk','xCh','xEl','xEta','xSz','xSpd'].forEach(id=>document.getElementById(id).textContent='-');
  document.getElementById('emailModal').classList.remove('open');
  // Unlock steps and reopen chapter selection
  unlockUI();
  ['s1','s2','s3'].forEach(id=>document.getElementById(id).classList.remove('done'));
  document.getElementById('s1').classList.add('collapsed');
  document.getElementById('s1').classList.add('done');
  document.getElementById('s2').classList.add('collapsed');
  document.getElementById('s2').classList.add('done');
  // Re-activate step 3 (chapter selection)
  activateStep('s3');
  // Re-enable generate button
  document.getElementById('btnG').disabled=false;
  updateSelection();
  _updatePreviewBtn();
}

function resetAll(){
  if(hbInterval){clearInterval(hbInterval);hbInterval=null}
  if(document._hbVis){document.removeEventListener('visibilitychange',document._hbVis);document._hbVis=null}
  generating=false;
  jobDone=false;
  unlockUI();
  document.getElementById('s4').style.display='none';
  // Accordion: s1 open, s2+s3 disabled collapsed
  document.getElementById('s1').classList.remove('collapsed','disabled','done');
  disableStep('s2');disableStep('s3');
  ['s2','s3'].forEach(id=>document.getElementById(id).classList.remove('done'));
  document.getElementById('dlA').style.display='none';
  document.getElementById('btnM').style.display='none';
  document.getElementById('btnP').style.display='none';
  document.getElementById('btnBackCh').style.display='none';
  document.getElementById('podHint').style.display='none';
  document.getElementById('cnA').style.display='';
  document.getElementById('btnG').disabled=false;
  document.getElementById('pBar').style.width='0%';
  document.getElementById('pPct').textContent='0%';
  document.getElementById('pMsg').style.color='';
  ['xBlk','xCh','xEl','xEta','xSz','xSpd'].forEach(id=>document.getElementById(id).textContent='-');
  document.getElementById('uz').classList.remove('ok');
  document.getElementById('ufn').style.display='none';
  document.getElementById('fi').value='';
  document.getElementById('chl').innerHTML='';
  document.getElementById('s3err').innerHTML='';
  document.getElementById('selBar').classList.remove('vis');
  document.getElementById('thSel').style.display='none';
  singleFile=true;isTxtFile=false;
  document.getElementById('fgOut').style.display='';
  document.querySelectorAll('.tg button').forEach(b=>b.classList.remove('on'));
  document.getElementById('toS').classList.add('on');
  previewStop(); _prevText=''; _prevWords=[];
  bookData=null;jobId=null;
  emailPromptShown=false;emailRegistered=false;previewListened=false;
  document.getElementById('emailModal').classList.remove('open');
  // Reset email modal fields
  document.getElementById('emEmail').value=lastVoucherEmail;document.getElementById('emEmail').style.display='';
  document.getElementById('emBaseUrl').value='';
  document.getElementById('emDesc').style.display='';
  document.querySelectorAll('input[name="emDl"]').forEach((r,i)=>{r.checked=i===0});
  ['bkCover','s4bkCover'].forEach(id=>{var el=document.getElementById(id);el.style.display='none';el.src=''});
  ['s1sum','s2sum','s3sum'].forEach(id=>document.getElementById(id).textContent='');
  applyI18n();
  window.scrollTo({top:0,behavior:'smooth'});
}

// ═══════════════════ HELPERS ═══════════════════
function fmtDur(m){if(m<1)return'< 1 min';if(m<60)return Math.round(m)+' min';const h=Math.floor(m/60);const r=Math.round(m%60);return h+'h '+(r>0?r+'min':'')}
function fmtTime(s){if(s<60)return s+'s';const m=Math.floor(s/60);const r=s%60;if(m<60)return m+'m'+(r>0?' '+r+'s':'');return Math.floor(m/60)+'h '+(m%60>0?(m%60)+'m':'')}
function fmtBytes(b){if(b<1024)return b+' B';if(b<1048576)return(b/1024).toFixed(0)+' KB';return(b/1048576).toFixed(1)+' MB'}
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function showErr(id,m){document.getElementById(id).innerHTML='<div class="al al-e fi">'+esc(m)+'</div>'}
function showPErr(m){document.getElementById('pra').innerHTML='<div class="al al-e fi">'+esc(m)+'</div>'}

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
}
function copyShareLink(){
  navigator.clipboard.writeText(SHARE_URL).then(function(){
    var tip=document.getElementById('shCopiedTip');
    if(tip){tip.classList.add('show');setTimeout(function(){tip.classList.remove('show')},2000)}
  }).catch(function(){});
}
// Init share copy button
document.addEventListener('DOMContentLoaded',function(){
  var cb=document.getElementById('shCopy');if(cb)cb.onclick=copyShareLink;
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

function goToAudioSettings(){
  const s2=document.getElementById('s2');
  if(!s2||s2.classList.contains('disabled'))return;
  s2.classList.remove('collapsed');
  setTimeout(()=>s2.scrollIntoView({behavior:'smooth',block:'nearest'}),80);
}