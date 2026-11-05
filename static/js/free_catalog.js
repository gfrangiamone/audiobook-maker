/* Catalogo audiolibri gratuiti: ricerca e filtri nell'indice (stato, lingua).
   Senza JS l'indice resta una lista completa. */
(function () {
  'use strict';

  function norm(s) {
    return (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  }

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
  }
})();
