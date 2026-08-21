/* news_md.js — Markdown-lite renderer per le news pubblicate sul sito.
 *
 * Sintassi supportata (volutamente minima): **grassetto**, *corsivo*,
 * [testo](url), elenchi puntati con "- ", riga vuota = nuovo paragrafo,
 * a capo singolo = <br>. Nient'altro: niente titoli, immagini, codice, HTML.
 *
 * Il body delle news resta Markdown grezzo nello store e nell'API (cosi' la
 * traduzione LLM lavora sul sorgente): la conversione in HTML avviene solo qui,
 * a video, ed e' l'unico punto in cui testo redazionale diventa markup.
 *
 * Sicurezza: l'escape dell'input e' il PRIMO passo, quindi nessun tag presente
 * nel testo puo' sopravvivere; i soli tag in output sono quelli generati da
 * questo file. Gli URL passano da una whitelist di schema (http/https/mailto o
 * path assoluto interno): tutto il resto — javascript:, data:, //host — perde
 * il link e conserva la sola etichetta.
 *
 * Usato dalla pagina pubblica (widget news + modale banner) e dall'anteprima
 * del pannello admin. Nessuna dipendenza: caricabile anche da node nei test.
 */
(function (root) {
  'use strict';

  // Marcatore interno per i link gia' resi: NUL, impossibile nel testo
  // redazionale e comunque rimosso dall'input prima dell'uso.
  var SENT = String.fromCharCode(0);

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* URL ammesso -> lo ritorna; altrimenti stringa vuota (link scartato).
   * Nota: `url` arriva gia' escapato, quindi eventuali entita' HTML iniettate
   * (&#106;avascript:) non tornano mai a essere uno schema valido. */
  function safeUrl(url) {
    var u = String(url || '').trim();
    if (!u) return '';
    if (/^https?:\/\/[^\s]+$/i.test(u)) return u;
    if (/^mailto:[^\s@]+@[^\s@]+$/i.test(u)) return u;
    if (/^\/(?!\/)[^\s]*$/.test(u)) return u;  // path interno, mai //host
    return '';
  }

  function emphasis(s) {
    return s
      .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
  }

  /* Inline su testo GIA' escapato: prima i link (messi da parte come segnaposto
   * per non farli attraversare dalle regex di enfasi), poi grassetto/corsivo. */
  function inline(s) {
    var links = [];
    s = s.replace(/\[([^\]\n]*)\]\(([^)\s]*)\)/g, function (m, label, url) {
      var text = emphasis(label);
      var href = safeUrl(url);
      if (!href) return text;  // schema non ammesso: resta la sola etichetta
      var external = /^(https?:|mailto:)/i.test(href);
      var attrs = external
        ? ' target="_blank" rel="noopener noreferrer nofollow"'
        : '';
      links.push('<a href="' + href + '"' + attrs + '>' + text + '</a>');
      return SENT + 'L' + (links.length - 1) + SENT;
    });
    s = emphasis(s);
    return s.replace(new RegExp(SENT + 'L(\\d+)' + SENT, 'g'), function (m, i) {
      return links[Number(i)];
    });
  }

  function isBullet(line) {
    return /^\s*[-*]\s+\S/.test(line);
  }

  function bulletText(line) {
    return line.replace(/^\s*[-*]\s+/, '');
  }

  /* Markdown-lite -> HTML. Ritorna stringa vuota su input vuoto. */
  function toHtml(src) {
    var text = String(src == null ? '' : src).split(SENT).join('');
    if (!text.trim()) return '';
    var lines = escapeHtml(text).replace(/\r\n?/g, '\n').split('\n');
    var out = [];
    var para = [];
    var list = [];

    function flushPara() {
      if (!para.length) return;
      out.push('<p>' + para.join('<br>') + '</p>');
      para = [];
    }

    function flushList() {
      if (!list.length) return;
      out.push('<ul>' + list.map(function (li) {
        return '<li>' + li + '</li>';
      }).join('') + '</ul>');
      list = [];
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (!line.trim()) {          // riga vuota: chiude il blocco corrente
        flushPara();
        flushList();
      } else if (isBullet(line)) { // voce di elenco
        flushPara();
        list.push(inline(bulletText(line).trim()));
      } else {                     // riga di paragrafo
        flushList();
        para.push(inline(line.trim()));
      }
    }
    flushPara();
    flushList();
    return out.join('');
  }

  /* Rende `src` dentro l'elemento `el` (no-op se l'elemento non esiste). */
  function render(el, src) {
    if (!el) return;
    el.innerHTML = toHtml(src);
  }

  var api = { toHtml: toHtml, render: render, escapeHtml: escapeHtml };
  root.ABMNewsMd = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
