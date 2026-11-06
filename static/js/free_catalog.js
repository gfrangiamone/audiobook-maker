/* Catalogo audiolibri gratuiti: ricerca e filtri nell'indice (stato, lingua) e
   frecce degli scaffali. Senza JS l'indice resta una lista completa e gli
   scaffali scorrono con la loro barra. */
(function () {
  'use strict';

  function norm(s) {
    return (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  }

  // --- Scaffali: frecce al posto della barra, nascoste agli estremi ----------
  var shelfUpdates = [];
  function refreshShelves() {
    shelfUpdates.forEach(function (f) { f(); });
  }
  Array.prototype.slice.call(document.querySelectorAll('.fc-shelf')).forEach(function (box) {
    var row = box.querySelector('.fc-shelf-row');
    var prev = box.querySelector('.fc-shelf-prev');
    var next = box.querySelector('.fc-shelf-next');
    if (!row || !prev || !next) return;
    box.classList.add('fc-js');
    var update = function () {
      prev.hidden = row.scrollLeft <= 2;
      next.hidden = row.scrollLeft >= row.scrollWidth - row.clientWidth - 2;
    };
    [prev, next].forEach(function (b) {
      b.addEventListener('click', function () {
        var step = Math.max(row.clientWidth * 0.8, 160) * Number(b.getAttribute('data-dir'));
        row.scrollBy({ left: step, behavior: 'smooth' });
      });
    });
    row.addEventListener('scroll', update, { passive: true });
    shelfUpdates.push(update);
    update();
  });
  window.addEventListener('resize', refreshShelves);

  // --- Indice: ricerca per titolo/autore + filtri per stato e lingua --------
  var list = document.getElementById('fc-list');
  if (list) {
    var q = document.getElementById('fc-q');
    var langSel = document.getElementById('fc-lang');
    var empty = document.getElementById('fc-empty');
    var cards = Array.prototype.slice.call(list.querySelectorAll('.fc-card'));
    var shelf = Array.prototype.slice.call(document.querySelectorAll('.fc-shelf-item[data-lang]'));
    var shelfBox = shelf.length ? shelf[0].closest('.fc-shelf') : null;
    var buttons = Array.prototype.slice.call(document.querySelectorAll('.fc-filters button'));
    var filter = 'all';
    var apply = function () {
      var term = norm(q ? q.value.trim() : '');
      var lang = langSel ? langSel.value : '';
      var shown = 0;
      cards.forEach(function (c) {
        var ok = (filter === 'all' || c.getAttribute('data-status') === filter) &&
                 (!lang || c.getAttribute('data-lang') === lang) &&
                 (!term || norm(c.getAttribute('data-search')).indexOf(term) !== -1);
        c.hidden = !ok;
        if (ok) shown++;
      });
      if (empty) empty.hidden = shown !== 0;
      // Lo scaffale dei disponibili segue la lingua scelta.
      var onShelf = 0;
      shelf.forEach(function (s) {
        var ok = !lang || s.getAttribute('data-lang') === lang;
        s.hidden = !ok;
        if (ok) onShelf++;
      });
      if (shelfBox) shelfBox.hidden = onShelf === 0;
      refreshShelves();
    };
    buttons.forEach(function (b) {
      b.addEventListener('click', function () {
        filter = b.getAttribute('data-f');
        buttons.forEach(function (o) {
          o.classList.toggle('on', o === b);
          o.setAttribute('aria-pressed', o === b ? 'true' : 'false');
        });
        apply();
      });
    });
    if (q) q.addEventListener('input', apply);
    if (langSel) langSel.addEventListener('change', apply);
    apply();

    // --- Lingua: su schermi stretti la sigla (IT) al posto del nome, per
    // lasciare spazio alla ricerca; aprendo la lista tornano i nomi interi.
    if (langSel && window.matchMedia) {
      var narrow = window.matchMedia('(max-width: 639px)');
      var opts = Array.prototype.slice.call(langSel.options);
      opts.forEach(function (o) { o.setAttribute('data-long', o.textContent); });
      var label = function (full) {
        opts.forEach(function (o) {
          var s = o.getAttribute('data-short');
          o.textContent = !full && narrow.matches && s ? s : o.getAttribute('data-long');
        });
      };
      var short = function () { label(false); };
      langSel.addEventListener('focus', function () { label(true); });
      langSel.addEventListener('blur', short);
      langSel.addEventListener('change', function () { langSel.blur(); short(); });
      if (narrow.addEventListener) narrow.addEventListener('change', short);
      else if (narrow.addListener) narrow.addListener(short);
      short();
    }
  }
})();
