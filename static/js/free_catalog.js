/* Catalogo audiolibri gratuiti: ricerca e filtri nell'indice. Senza JS
   l'indice resta una lista completa. */
(function () {
  'use strict';

  function norm(s) {
    return (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  }

  // --- Indice: ricerca per titolo/autore + filtro per stato ----------------
  var list = document.getElementById('fc-list');
  if (list) {
    var q = document.getElementById('fc-q');
    var empty = document.getElementById('fc-empty');
    var cards = Array.prototype.slice.call(list.querySelectorAll('.fc-card'));
    var buttons = Array.prototype.slice.call(document.querySelectorAll('.fc-filters button'));
    var filter = 'all';
    var apply = function () {
      var term = norm(q ? q.value.trim() : '');
      var shown = 0;
      cards.forEach(function (c) {
        var ok = (filter === 'all' || c.getAttribute('data-status') === filter) &&
                 (!term || norm(c.getAttribute('data-search')).indexOf(term) !== -1);
        c.hidden = !ok;
        if (ok) shown++;
      });
      if (empty) empty.hidden = shown !== 0;
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
  }
})();
