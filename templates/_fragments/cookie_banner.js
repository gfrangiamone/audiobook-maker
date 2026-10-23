// Banner di consenso cookie, inline in cima al <body> (index_page.py): per chi
// arriva la prima volta il suo testo e' l'elemento LCP della home e deve esserci
// gia' al primo paint. Autonomo: usa solo <html lang> e gtag. Mai il tag di
// chiusura dello script qui dentro, nemmeno nei commenti: chiuderebbe l'inline.
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
  }
  // Link footer unificato "Cookie e privacy": testo localizzato (tr().title),
  // naviga a /privacy. La gestione del consenso vive nella pagina Privacy.
  // Il footer viene dopo questo script: si aspetta la fine del parsing.
  function privacyLink(){
    const link=document.getElementById('privacyLink');
    if(link)link.textContent=tr().title;
  }
  init();
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',privacyLink);
  }else{
    privacyLink();
  }
})();
