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

    function apply(ratio) {   // the share of the upper tile; the CSS takes it only on wide windows
      if (ratio === null) {
        col.classList.remove("split-set");
        col.style.removeProperty("--split");
        split.removeAttribute("aria-valuenow");
        return;
      }
      col.classList.add("split-set");
      col.style.setProperty("--split", ratio.toFixed(4));
      split.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
    }
    function limits() {   // each tile keeps at least its own minimum height
      var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      var total = ra.height + rb.height;
      var minA = parseFloat(getComputedStyle(a).minHeight) || 80, minB = parseFloat(getComputedStyle(b).minHeight) || 80;
      return { top: ra.top, total: total, low: Math.min(minA / total, 0.5), high: Math.max(1 - minB / total, 0.5) };
    }
    function clamp(value, box) { return Math.min(Math.max(value, box.low), box.high); }
    var saved = load(name);
    if (saved > 0 && saved < 1) apply(saved);

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
      apply(clamp(height / drag.box.total, drag.box));
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
    split.addEventListener("dblclick", function () { apply(null); store(name, null); });
    split.addEventListener("keydown", function (event) {
      var step = { ArrowUp: -0.05, ArrowDown: 0.05 }[event.key];
      if (step === undefined) return;
      event.preventDefault();
      var box = limits();
      var now = col.classList.contains("split-set") ? parseFloat(col.style.getPropertyValue("--split"))
        : a.getBoundingClientRect().height / box.total;
      var next = clamp(now + step, box);
      apply(next);
      store(name, next);
    });
  });
})();
