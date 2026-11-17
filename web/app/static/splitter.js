// Splitters between two tiles of a column (DESIGN.md, "Trenner"; Janis, 14.11.2026): a thin rounded bar that shows
// when the pointer is over the gap; drag it up or down to give one tile more height than the other, like the divider
// between two windows. Arrow keys move it in steps, a double click puts it back. The choice is kept per browser
// (localStorage, a convenience: nothing breaks without it). Only on wide windows, where the tiles share a column.
(function () {
  "use strict";
  var KEY = "split:";
  function load(name) { try { return parseFloat(localStorage.getItem(KEY + name)); } catch (e) { return NaN; } }
  function store(name, value) {
    try { if (value === null) localStorage.removeItem(KEY + name); else localStorage.setItem(KEY + name, String(value)); } catch (e) {}
  }

  document.querySelectorAll(".m-split").forEach(function (split) {
    var col = split.parentNode, name = split.dataset.split;
    var a = split.previousElementSibling, b = split.nextElementSibling;
    if (!a || !b) return;
    // A tile may give way down to its header (Janis, 14.11.2026): below its usual minimum its content fades out
    // (--fold from 1 to 0), so the other tile can show all it has. The usual minimum is read before the CSS of a
    // shared column sets it to 0.
    var natural = [a, b].map(function (tile) { return parseFloat(getComputedStyle(tile).minHeight) || 80; });
    function extra(tile) { return tile.querySelector(":scope > .split-extra"); }
    // A tile with a part marked .split-extra (the status text, Janis 17.11.2026) rests where everything but that part
    // shows, with its own padding below (harmonious, not cut), and opens only as far as that part reaches (no empty
    // block). Measured from where the children really are, margins included.
    function bottom(tile, withoutExtra) {
      var top = tile.getBoundingClientRect().top, low = 0, style = getComputedStyle(tile);
      Array.prototype.forEach.call(tile.children, function (child) {
        if (withoutExtra && child.classList.contains("split-extra")) return;
        if (child.offsetParent === null || !child.getBoundingClientRect().height) return;
        low = Math.max(low, child.getBoundingClientRect().bottom + (parseFloat(getComputedStyle(child).marginBottom) || 0));
      });
      return low - top + parseFloat(style.paddingBottom) + (parseFloat(style.borderBottomWidth) || 0);
    }
    function folded(tile) {   // the height at which only the header is left (or, with an extra, all but the extra)
      if (extra(tile)) return bottom(tile, true);
      var style = getComputedStyle(tile), head = tile.querySelector(":scope > header");
      return (head ? head.offsetHeight : 0) + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + 2;
    }
    // What the tile needs to show all it has: padding, header and every visible child with the gaps between them
    // (14.11.2026: a hint taller than the minimum ran out of the tile, after a reload with a saved height).
    function needed(tile) {
      if (extra(tile)) return bottom(tile, false);
      var style = getComputedStyle(tile), gap = parseFloat(style.rowGap) || 0, sum = 0, count = 0;
      Array.prototype.forEach.call(tile.children, function (child) {
        if (child.offsetParent === null && getComputedStyle(child).position !== "fixed") return;   // hidden
        sum += child.offsetHeight;
        count++;
      });
      return sum + Math.max(0, count - 1) * gap + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
    }
    function fade() {
      // A hidden view (the Manager while the board shows) has no heights: measuring it would fold every tile shut
      // (14.11.2026: chat and files were empty after switching from the board until the page was loaded again).
      if (!col.offsetParent || !col.getBoundingClientRect().height) return;
      [a, b].forEach(function (tile, i) {
        var low = folded(tile), height = tile.getBoundingClientRect().height;
        var full = Math.max(natural[i], needed(tile));
        var share = col.classList.contains("split-set") && full > low + 1
          ? Math.min(Math.max((height - low) / (full - low), 0), 1) : 1;
        tile.style.setProperty("--fold", share.toFixed(3));
        tile.classList.toggle("m-folded", share < 1);
        tile.classList.toggle("m-shut", share === 0);
      });
    }

    function apply(ratio) {   // the share of the upper tile; the CSS takes it only on wide windows
      if (ratio === null) {
        col.classList.remove("split-set");
        col.style.removeProperty("--split");
        split.removeAttribute("aria-valuenow");
        fade();
        return;
      }
      col.classList.add("split-set");
      col.style.setProperty("--split", ratio.toFixed(4));
      split.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
      fade();
    }
    // With a flex basis of 0 a tile never gets smaller than its padding and border: they stay, the share splits the rest.
    function fixed(tile) {
      var s = getComputedStyle(tile);
      return ["paddingTop", "paddingBottom", "borderTopWidth", "borderBottomWidth"]
        .reduce(function (sum, key) { return sum + (parseFloat(s[key]) || 0); }, 0);
    }
    function limits() {   // each tile keeps at least its header
      var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      var fa = fixed(a), inner = ra.height + rb.height - fa - fixed(b);
      var high = Math.max(1 - (folded(b) - fixed(b)) / inner, 0.5);
      if (extra(a)) high = Math.min(high, (needed(a) - fa) / inner);   // not further than the text reaches
      return { top: ra.top, fixed: fa, total: inner, low: Math.min((folded(a) - fa) / inner, extra(a) ? 1 : 0.5),
               high: Math.max(high, Math.min((folded(a) - fa) / inner, 1)) };
    }
    function clamp(value, box) { return Math.min(Math.max(value, box.low), box.high); }
    var saved = load(name);
    // A tile with an extra rests folded at first (its text hidden): that is its place until the user pulls it out.
    function rest() {
      if (!extra(a) || load(name) > 0 || !col.offsetParent || !col.getBoundingClientRect().height) return;
      var box = limits();
      apply(box.low);
    }
    if (saved > 0 && saved < 1) apply(saved); else rest();
    window.addEventListener("resize", function () { if (load(name) > 0) fade(); else rest(); });
    window.addEventListener("load", rest);
    document.addEventListener("agenthub:view", function () { setTimeout(rest, 30); });
    // Shown again (another station) or resized: measure anew.
    if (window.ResizeObserver) new ResizeObserver(function () { fade(); }).observe(col);
    window.addEventListener("load", fade);   // fonts and pictures may change the heights after the first look
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fade);

    var drag = null;
    split.addEventListener("pointerdown", function (event) {
      if (event.button > 0) return;
      event.preventDefault();
      var box = limits();
      drag = { id: event.pointerId, box: box, offset: event.clientY - (box.top + a.getBoundingClientRect().height) };
      try { split.setPointerCapture(event.pointerId); } catch (e) {}
      split.classList.add("active");
      document.documentElement.classList.add("splitting");
    });
    split.addEventListener("pointermove", function (event) {
      if (!drag || event.pointerId !== drag.id) return;
      var height = event.clientY - drag.offset - drag.box.top;
      apply(clamp((height - drag.box.fixed) / drag.box.total, drag.box));
    });
    function end(event) {
      if (!drag || event.pointerId !== drag.id) return;
      drag = null;
      split.classList.remove("active");
      document.documentElement.classList.remove("splitting");
      store(name, parseFloat(col.style.getPropertyValue("--split")) || null);
    }
    split.addEventListener("pointerup", end);
    split.addEventListener("pointercancel", end);
    split.addEventListener("dblclick", function () { store(name, null); apply(null); rest(); });
    split.addEventListener("keydown", function (event) {
      var step = { ArrowUp: -0.05, ArrowDown: 0.05 }[event.key];
      if (step === undefined) return;
      event.preventDefault();
      var box = limits();
      var now = col.classList.contains("split-set") ? parseFloat(col.style.getPropertyValue("--split"))
        : (a.getBoundingClientRect().height - box.fixed) / box.total;
      var next = clamp(now + step, box);
      apply(next);
      store(name, next);
    });
  });
})();
