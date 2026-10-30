/* Donazione PayPal in una finestra popup, con overlay modale sulla pagina.
   PayPal non si lascia incorniciare (X-Frame-Options: SAMEORIGIN), quindi
   niente iframe: i link a[data-donate-popup] aprono il modulo di donazione in
   una finestra dimensionata e la pagina mostra #ppDonateOverlay (classe
   .open). Dentro l'overlay, [data-pp-reopen] riporta in primo piano (o riapre)
   la finestra e [data-pp-close] chiude finestra e overlay; quando l'utente
   chiude la finestra PayPal l'overlay sparisce da solo. Popup bloccato: il
   link prosegue normalmente in una nuova scheda.
   Usato dalla SPA (html_head.html) e da templates/pages/dl_page.html. */
(function(){
  var W=480,H=720,win=null,url='',poll=null;

  function overlay(){return document.getElementById('ppDonateOverlay')}

  function openWin(){
    var x=(window.screenX||0)+Math.max(0,((window.outerWidth||W)-W)/2);
    var y=(window.screenY||0)+Math.max(0,((window.outerHeight||H)-H)/2);
    var w=window.open('','abm_donate','popup,width='+W+',height='+H+',left='+Math.round(x)+',top='+Math.round(y));
    if(!w)return null;
    // Finestra ancora vuota (stessa origine): si toglie l'opener prima di
    // navigare, cosi' la pagina PayPal non raggiunge la nostra ma il riferimento
    // resta per close() e per il controllo di .closed.
    try{w.opener=null}catch(e){}
    w.location.href=url;
    return w;
  }

  function hide(){
    clearInterval(poll);poll=null;
    var o=overlay();if(o)o.classList.remove('open');
  }

  function close(){
    if(win&&!win.closed){try{win.close()}catch(e){}}
    win=null;hide();
  }

  function show(){
    var o=overlay();if(!o)return;
    o.classList.add('open');
    clearInterval(poll);
    poll=setInterval(function(){if(!win||win.closed){win=null;hide()}},500);
  }

  document.addEventListener('click',function(e){
    var t=e.target;if(!t||!t.closest)return;
    var a=t.closest('a[data-donate-popup]');
    if(a){
      url=a.href;
      var w=openWin();
      if(!w)return;
      e.preventDefault();
      win=w;show();
      return;
    }
    if(t.closest('[data-pp-reopen]')){
      if(win&&!win.closed){try{win.focus()}catch(e2){}return}
      win=openWin();
      if(win)show();else hide();
      return;
    }
    if(t.closest('[data-pp-close]'))close();
  });

  document.addEventListener('keydown',function(e){
    var o=overlay();
    if(e.key==='Escape'&&o&&o.classList.contains('open'))close();
  });
})();
