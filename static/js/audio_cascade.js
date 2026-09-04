'use strict';
/* Cascata lingua -> modello -> accento -> voce del pannello Impostazioni audio.
 *
 * FUNZIONE PURA: nessun accesso al DOM, nessuna globale dell'app. app.js la
 * chiama e riversa il risultato nei <select>; tutta la logica che puo'
 * rompersi vive qui, dove `node --test` la raggiunge senza un browser.
 *
 * La lingua non e' una scelta dell'utente: e' una proprieta' del libro. Questa
 * funzione riceve la lingua e decide COSA RESTA POSSIBILE, riportando in
 * `changes` cio' che ha dovuto spostare — che e' poi il testo che l'utente
 * legge quando forza la lingua.
 */

/* Varianti d'accento premium. Specchio di gemini_tts.ACCENT_VARIANTS. */
var ACCENT_CATALOG = {
  en: [['us', 'accent_en_us'], ['gb', 'accent_en_gb'], ['au', 'accent_en_au'], ['in', 'accent_en_in']],
  es: [['es', 'accent_es_es'], ['419', 'accent_es_419']],
  pt: [['br', 'accent_pt_br'], ['pt', 'accent_pt_pt']],
  fr: [['fr', 'accent_fr_fr'], ['ca', 'accent_fr_ca']],
  zh: [['cn', 'accent_zh_cn'], ['tw', 'accent_zh_tw']],
  de: [['de', 'accent_de_de'], ['at', 'accent_de_at'], ['ch', 'accent_de_ch']],
  ar: [['eg', 'accent_ar_eg'], ['sa', 'accent_ar_sa'], ['ae', 'accent_ar_ae']]
};

function _voci(catalog, lang) {
  var dati = catalog && catalog[lang];
  return (dati && Array.isArray(dati.voices)) ? dati.voices : [];
}

function _haPrefisso(voci, prefisso) {
  for (var i = 0; i < voci.length; i++) {
    var id = voci[i] && voci[i].id;
    if (typeof id === 'string' && id.indexOf(prefisso) === 0) return true;
  }
  return false;
}

/* Vero se l'id appartiene a un motore a pagamento. Stessa fonte di verita'
   di modelliPer/vociPremium: mai il campo `engine` del catalogo, sempre il
   prefisso dell'id — e' quello, non la vetrina, a decidere la cassa. Un
   `engine` mancante o sbagliato su una voce a pagamento non deve mai farla
   scivolare nel tab gratuito. */
function _ePremium(id) {
  if (typeof id !== 'string') return false;
  return id.indexOf('gemini:') === 0
      || id.indexOf('voxcpm:') === 0
      || id.indexOf('speechify:') === 0;
}

/* Modelli premium disponibili per la lingua. L'ordine e' quello mostrato:
   VOXCPM2 primo dove c'e', poi i due Gemini, Simba in coda sull'inglese. */
function modelliPer(catalog, lang) {
  var voci = _voci(catalog, lang);
  var out = [];
  var voxAttivo = !!(catalog && catalog._voxcpm && catalog._voxcpm.available);
  if (voxAttivo && _haPrefisso(voci, 'voxcpm:')) out.push('voxcpm');
  if (_haPrefisso(voci, 'gemini:')) { out.push('flash25'); out.push('flash31'); }
  if (lang === 'en' && _haPrefisso(voci, 'speechify:simba-3.2:')) out.push('simba-3.2');
  return out;
}

/* Voci del tab Standard: solo il motore gratuito, filtrate per locale. */
function vociStandard(catalog, lang, locale) {
  var out = [];
  var voci = _voci(catalog, lang);
  for (var i = 0; i < voci.length; i++) {
    var v = voci[i];
    if (!v || _ePremium(v.id)) continue;
    if (locale && v.locale !== locale) continue;
    out.push(v);
  }
  return out;
}

function localiStandard(catalog, lang) {
  var visti = {}, out = [];
  var voci = vociStandard(catalog, lang, '');
  for (var i = 0; i < voci.length; i++) {
    var loc = voci[i].locale || '';
    if (loc && !visti[loc]) { visti[loc] = true; out.push(loc); }
  }
  return out;
}

/* Voci premium per modello.
 *
 * L'id porta gia' il modello: gemini_tts.get_voices() emette
 * `gemini:<model_key>:<Nome>`, quindi il prefisso completo separa i due
 * modelli Gemini da solo. Il campo `model_key` c'e' anche nel catalogo, ma
 * filtrare sull'id non dipende dalla sua presenza: se un domani sparisse, un
 * filtro su model_key lascerebbe passare le voci di ENTRAMBI i modelli
 * silenziosamente, mentre questo non restituisce nulla e il difetto si vede. */
function vociPremium(catalog, lang, model) {
  var prefisso = model === 'voxcpm' ? 'voxcpm:'
               : model === 'simba-3.2' ? 'speechify:simba-3.2:'
               : 'gemini:' + model + ':';
  var out = [];
  var voci = _voci(catalog, lang);
  for (var i = 0; i < voci.length; i++) {
    var v = voci[i];
    var id = v && v.id;
    if (typeof id !== 'string' || id.indexOf(prefisso) !== 0) continue;
    out.push(v);
  }
  return out;
}

function _preserva(valore, disponibili) {
  return (valore && disponibili.indexOf(valore) !== -1) ? valore : null;
}

/* Voci gratuite preferite come default, nell'ordine. Il catalogo arriva in
   ordine alfabetico di ShortName, quindi per l'inglese la prima voce e'
   australiana: senza questa preferenza un libro inglese si aprirebbe su
   en-AU e due sole voci, mentre il vecchio updVoices() proponeva una voce
   americana. La preferenza e' sul NOME dentro l'id, non sul locale: e' la
   stessa regola di prima, riportata qui dove si sceglie. */
var VOCI_STANDARD_PREFERITE = ['Isabella', 'Guy', 'Davis'];

function _vocePreferita(voci) {
  for (var i = 0; i < voci.length; i++) {
    var id = voci[i] && voci[i].id;
    if (typeof id !== 'string') continue;
    for (var k = 0; k < VOCI_STANDARD_PREFERITE.length; k++) {
      if (id.indexOf(VOCI_STANDARD_PREFERITE[k]) !== -1) return voci[i];
    }
  }
  return null;
}

function _idsDi(voci) {
  var out = [];
  for (var i = 0; i < voci.length; i++) out.push(voci[i].id);
  return out;
}

function resolveAudioSelection(input) {
  input = input || {};
  var catalog = input.catalog || {};
  var current = input.current || {};
  var lang = String(input.lang || '').split('-')[0].toLowerCase();
  var changes = [];
  var segna = function (what, from, to, reason) {
    if (from === to) return;
    changes.push({what: what, from: from || '', to: to || '', reason: reason});
  };

  /* ── Modelli premium ─────────────────────────────────────────────── */
  var models = modelliPer(catalog, lang);
  var premiumEnabled = models.length > 0;
  var premiumReason = premiumEnabled ? '' : 'no_premium_voices';

  var model = _preserva(current.model, models) || (models.length ? models[0] : '');
  if (current.model && model !== current.model) {
    segna('model', current.model, model,
          premiumEnabled ? 'model_unavailable_in_lang' : 'no_premium_voices');
  }

  /* ── Tab ─────────────────────────────────────────────────────────── */
  var tab = current.tab === 'premium' ? 'premium' : 'standard';
  if (tab === 'premium' && !premiumEnabled) {
    segna('tab', 'premium', 'standard', 'no_premium_voices');
    tab = 'standard';
  }

  /* ── Accento e voce, tab Standard ────────────────────────────────── */
  var accentiStd = localiStandard(catalog, lang);
  var accentoStd = _preserva(current.standardAccent, accentiStd);
  if (!accentoStd) {
    /* Nessun accento da conservare: e' la voce predefinita a decidere il
       locale, non l'ordine del catalogo. Quando l'utente ha gia' scelto un
       accento valido invece si rispetta quello, altrimenti sceglierlo non
       servirebbe a niente. */
    var prefLang = _vocePreferita(vociStandard(catalog, lang, ''));
    accentoStd = (prefLang && prefLang.locale)
                 || (accentiStd.length ? accentiStd[0] : '');
  }
  if (current.standardAccent && accentoStd !== current.standardAccent) {
    segna('accent', current.standardAccent, accentoStd, 'accent_unavailable_in_lang');
  }
  /* Con un solo locale il filtro non serve: mostra tutte le voci gratuite. */
  var vociStd = vociStandard(catalog, lang, accentiStd.length > 1 ? accentoStd : '');
  var idsStd = _idsDi(vociStd);
  var voceStd = _preserva(current.standardVoice, idsStd);
  if (!voceStd) {
    var prefVoce = _vocePreferita(vociStd);
    voceStd = (prefVoce && prefVoce.id) || (idsStd.length ? idsStd[0] : '');
  }
  if (current.standardVoice && voceStd !== current.standardVoice) {
    segna('voice', current.standardVoice, voceStd, 'voice_unavailable_in_lang');
  }

  /* ── Accento e voce, tab PREMIUM ─────────────────────────────────── */
  /* L'accento premium esiste solo per i modelli Gemini: VOXCPM2 e Simba
     hanno cataloghi propri, gestiti da app.js fuori da questa cascata. */
  var eGemini = (model === 'flash25' || model === 'flash31');
  /* Copia, non riferimento: ACCENT_CATALOG e' condivisa fra tutte le
     chiamate (e' anche su `window`). Un .reverse()/.sort() di chi consuma
     il risultato non deve corrompere la tabella per la sessione intera. */
  var accentiPrem = (eGemini && ACCENT_CATALOG[lang])
    ? ACCENT_CATALOG[lang].map(function (coppia) { return coppia.slice(); })
    : [];
  var codiciPrem = [];
  for (var k = 0; k < accentiPrem.length; k++) codiciPrem.push(accentiPrem[k][0]);
  var accentoPrem = _preserva(current.premiumAccent, codiciPrem)
                    || (codiciPrem.length ? codiciPrem[0] : '');

  var vociPrem = premiumEnabled ? vociPremium(catalog, lang, model) : [];
  var idsPrem = _idsDi(vociPrem);
  var vocePrem = _preserva(current.premiumVoice, idsPrem)
                 || (idsPrem.length ? idsPrem[0] : '');
  if (current.premiumVoice && vocePrem !== current.premiumVoice) {
    segna('voice', current.premiumVoice, vocePrem, 'voice_unavailable_in_lang');
  }

  return {
    lang: lang,
    premiumEnabled: premiumEnabled,
    premiumReason: premiumReason,
    tab: tab,
    standard: {accents: accentiStd, accent: accentoStd,
               voices: vociStd, voice: voceStd},
    premium: {models: models, model: model,
              accents: accentiPrem, accent: accentoPrem,
              voices: vociPrem, voice: vocePrem},
    changes: changes
  };
}

/* Doppia esposizione: `window` per il browser (script `defer`, nessun
   bundler), `module.exports` per node --test. */
if (typeof window !== 'undefined') {
  window.resolveAudioSelection = resolveAudioSelection;
  window.ACCENT_CATALOG = ACCENT_CATALOG;
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {resolveAudioSelection: resolveAudioSelection,
                    ACCENT_CATALOG: ACCENT_CATALOG,
                    modelliPer: modelliPer};
}
