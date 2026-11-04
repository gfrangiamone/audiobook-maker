/* Catalogo audiolibri gratuiti: ricerca e filtri nell'indice, salti ai
   capitoli nella pagina del libro. Senza JS l'indice resta una lista completa
   e il player funziona lo stesso. */
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

  // --- Libro: capitoli cliccabili e capitolo corrente evidenziato ----------
  var audio = document.getElementById('fc-audio');
  var box = document.getElementById('fc-chapters');
  if (audio && box) {
    var chs = Array.prototype.slice.call(box.querySelectorAll('button[data-t]'));
    var starts = chs.map(function (b) { return parseFloat(b.getAttribute('data-t')) || 0; });
    // Sul telefono una lista lunga spinge giu' download e app: parte chiusa.
    if (chs.length > 8 && window.matchMedia('(max-width: 639px)').matches) box.open = false;
    chs.forEach(function (b, i) {
      b.addEventListener('click', function () {
        audio.currentTime = starts[i];
        var p = audio.play();
        if (p && p.catch) p.catch(function () {});
      });
    });
    var current = -1;
    audio.addEventListener('timeupdate', function () {
      var t = audio.currentTime, idx = -1;
      for (var i = 0; i < starts.length; i++) { if (starts[i] <= t + 0.5) idx = i; else break; }
      if (idx !== current) {
        if (current >= 0) chs[current].classList.remove('on');
        if (idx >= 0) chs[idx].classList.add('on');
        current = idx;
      }
    });
  }
})();
