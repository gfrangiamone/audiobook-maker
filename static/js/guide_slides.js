/* Guide a slide: trasforma le <section> di .guide-deck in slide da sfogliare.
   Ogni <section> e' una slide; una sezione con dei <h3> si divide in una
   slide per l'introduzione e una per ogni <h3>. L'HTML servito resta un
   articolo continuo (indicizzazione, lettura senza JS); qui si spostano solo
   i nodi. Etichette dai data-* del contenitore, nella lingua della pagina. */
(function () {
  "use strict";
  var deck = document.querySelector(".guide-deck");
  if (!deck) return;
  var KEY = "abm_guide_deck_off";
  var d = deck.dataset;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text) n.textContent = text;
    return n;
  }

  // costruzione delle slide
  var slides = [];
  Array.prototype.slice.call(deck.children).forEach(function (sec) {
    if (sec.tagName !== "SECTION") return;
    var h2 = sec.querySelector("h2");
    var parent = h2 ? h2.textContent : "";
    var cur = el("section", "slide");
    sec.parentNode.insertBefore(cur, sec);
    var parts = [cur];
    Array.prototype.slice.call(sec.childNodes).forEach(function (n) {
      if (n.nodeType === 1 && n.tagName === "H3") {
        cur = el("section", "slide");
        if (parent) cur.appendChild(el("p", "slide-kicker", parent));
        parts[parts.length - 1].parentNode.insertBefore(cur, sec);
        parts.push(cur);
      }
      cur.appendChild(n);
    });
    sec.parentNode.removeChild(sec);
    parts.forEach(function (p) {
      var h = p.querySelector("h2,h3");
      p.dataset.title = h ? h.textContent.replace(/^\d+\.\s*/, "") : "";
      slides.push(p);
    });
  });
  if (slides.length < 2) return;
  slides.forEach(function (s, i) { s.id = "slide-" + (i + 1); });

  // barra di navigazione
  var progress = el("div", "deck-progress");
  progress.appendChild(el("i"));
  deck.insertBefore(progress, deck.firstChild);
  var bar = el("nav", "deck-bar");
  bar.setAttribute("aria-label", d.navLabel || "Slides");
  var prev = el("button", "deck-prev", "‹ " + (d.prev || "Back"));
  var next = el("button", "deck-next", (d.next || "Next") + " ›");
  prev.type = next.type = "button";
  var sel = el("select");
  sel.setAttribute("aria-label", d.navLabel || "Slides");
  slides.forEach(function (s, i) {
    var o = el("option", "", (i + 1) + ". " + s.dataset.title);
    o.value = String(i);
    sel.appendChild(o);
  });
  bar.appendChild(prev);
  bar.appendChild(sel);
  bar.appendChild(next);
  deck.appendChild(bar);
  var allWrap = el("p", "deck-all");
  var allBtn = el("button");
  allBtn.type = "button";
  allWrap.appendChild(allBtn);
  deck.appendChild(allWrap);

  var idx = 0;
  function pauseAudio(s) {
    Array.prototype.forEach.call(s.querySelectorAll("audio"), function (a) { a.pause(); });
  }
  function show(i, fromUser) {
    i = Math.max(0, Math.min(slides.length - 1, i));
    pauseAudio(slides[idx]);
    slides[idx].classList.remove("is-current");
    idx = i;
    slides[idx].classList.add("is-current");
    sel.value = String(idx);
    prev.disabled = idx === 0;
    next.disabled = idx === slides.length - 1;
    progress.firstChild.style.width = ((idx + 1) / slides.length * 100) + "%";
    if (fromUser) {
      try { history.replaceState(null, "", "#slide-" + (idx + 1)); } catch (e) {}
      var top = deck.getBoundingClientRect().top;
      if (top < 0) window.scrollTo(0, window.pageYOffset + top - 12);
    }
  }
  function setDeck(on) {
    deck.classList.toggle("is-deck", on);
    allBtn.textContent = on ? (d.all || "Show all on one page") : (d.deck || "Show as slides");
    try { on ? localStorage.removeItem(KEY) : localStorage.setItem(KEY, "1"); } catch (e) {}
  }

  prev.addEventListener("click", function () { show(idx - 1, true); });
  next.addEventListener("click", function () { show(idx + 1, true); });
  sel.addEventListener("change", function () { show(parseInt(sel.value, 10), true); });
  allBtn.addEventListener("click", function () { setDeck(!deck.classList.contains("is-deck")); });
  document.addEventListener("keydown", function (e) {
    if (!deck.classList.contains("is-deck") || e.altKey || e.ctrlKey || e.metaKey) return;
    var t = e.target && e.target.tagName;
    if (t === "INPUT" || t === "SELECT" || t === "TEXTAREA" || t === "AUDIO") return;
    if (e.key === "ArrowRight") { show(idx + 1, true); e.preventDefault(); }
    if (e.key === "ArrowLeft") { show(idx - 1, true); e.preventDefault(); }
  });
  var x0 = null;
  deck.addEventListener("touchstart", function (e) { x0 = e.touches[0].clientX; }, { passive: true });
  deck.addEventListener("touchend", function (e) {
    if (x0 === null || !deck.classList.contains("is-deck")) return;
    var dx = e.changedTouches[0].clientX - x0;
    x0 = null;
    if (e.target.closest && e.target.closest("audio,select,.tablewrap,dl")) return;
    if (Math.abs(dx) > 70) show(idx + (dx < 0 ? 1 : -1), true);
  }, { passive: true });

  window.addEventListener("hashchange", function () {
    var h = /^#slide-(\d+)$/.exec(location.hash);
    if (h) show(parseInt(h[1], 10) - 1, false);
  });

  var off = false;
  try { off = localStorage.getItem(KEY) === "1"; } catch (e) {}
  var m = /^#slide-(\d+)$/.exec(location.hash);
  slides[0].classList.add("is-current");
  show(m ? parseInt(m[1], 10) - 1 : 0, false);
  setDeck(!off);
})();
