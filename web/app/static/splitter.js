// Splitters between two tiles of a column (DESIGN.md, "Trenner"; Janis, 14.11.2026): a thin rounded bar that shows
// when the pointer is over the gap; drag it up or down to give one tile more height than the other, like the divider
// between two windows. Arrow keys move it in steps, a double click puts it back. The choice is kept per browser
// (localStorage, a convenience: nothing breaks without it), except under the status tile, which always opens at its
// resting height. Only on wide windows, where the tiles share a column.
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
    function headerOnly(tile) {   // the height at which only the header is left
      var style = getComputedStyle(tile), head = tile.querySelector(":scope > header");
      return (head ? head.offsetHeight : 0) + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + 2;
    }
    function folded(tile) {   // where the content starts to fade (with an extra: all but the extra shows)
      return extra(tile) ? bottom(tile, true) : headerOnly(tile);
    }
    // Snap points (Janis, 22.11.2026): the heights at which a part of the tile ends, top to bottom: only the header,
    // then the bottom of each part (for the status: the headline, the bar, the numbers, the text), with the tile's own
    // padding below, so a snapped tile never cuts a part in half.
    function edges(tile) {
      var top = tile.getBoundingClientRect().top, style = getComputedStyle(tile);
      var pad = parseFloat(style.paddingBottom) + (parseFloat(style.borderBottomWidth) || 0);
      var list = [headerOnly(tile)];
      Array.prototype.forEach.call(tile.children, function (child) {
        if (child.tagName === "HEADER" || child.offsetParent === null || !child.getBoundingClientRect().height) return;
        var low = child.getBoundingClientRect().bottom + (parseFloat(getComputedStyle(child).marginBottom) || 0);
        if (low - top + pad > list[list.length - 1] + 4) list.push(low - top + pad);
      });
      return list;
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
        // smaller than its content: it cuts off what does not fit (22.11.2026: before, text stood over other parts)
        tile.classList.toggle("m-folded", col.classList.contains("split-set") && height < full - 1);
        tile.classList.toggle("m-shut", share === 0);
        tile.classList.toggle("m-headonly", col.classList.contains("split-set") && height <= headerOnly(tile) + 4);
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
      var high = Math.max(1 - (headerOnly(b) - fixed(b)) / inner, 0.5);
      if (extra(a)) high = Math.min(high, (needed(a) - fa) / inner);   // not further than the text reaches
      // down to its header, like every tile (22.11.2026: the status could not be pushed up further than its numbers)
      var low = Math.min((headerOnly(a) - fa) / inner, 0.5);
      return { top: ra.top, fixed: fa, total: inner, sum: ra.height + rb.height, low: low, high: Math.max(high, low) };
    }
    function clamp(value, box) { return Math.min(Math.max(value, box.low), box.high); }
    var SNAP = 18;   // px: a split this close to the edge of a part snaps to it
    function snaps(box) {   // every edge of the upper tile and of the lower one, as the share of the upper tile
      var out = [];
      edges(a).forEach(function (h, i) { out.push({ r: (h - box.fixed) / box.total, tile: "a", i: i }); });
      edges(b).forEach(function (h, i) { out.push({ r: (box.sum - h - box.fixed) / box.total, tile: "b", i: i }); });
      return out.filter(function (s) { return s.r >= box.low - 1e-6 && s.r <= box.high + 1e-6; });
    }
    function nearest(ratio, box) {
      var best = null;
      snaps(box).forEach(function (s) {
        var d = Math.abs(s.r - ratio) * box.total;
        if (d <= SNAP && (!best || d < best.d)) best = { d: d, s: s };
      });
      return best ? best.s : null;
    }
    // A tile with an extra (the status) always opens at its resting height, never at a height pulled for another
    // project with a longer or shorter text (Janis, 18.11.2026): its choice lasts only while the page is open.
    var kept = !extra(a), pulled = null;
    function chosen() { return kept ? load(name) : pulled; }
    function keep(value) { if (kept) store(name, value); else pulled = value; }
    if (!kept) store(name, null);   // a height saved before 18.11.2026 is not read any more; remove after 01.01.2027
    // The edge it snapped to, not a number (Janis, 22.11.2026): when the text of a part changes (a new status, other
    // numbers), the tile follows that edge and stays at the same part.
    var snapped = null;
    function resnap() {
      if (!snapped || !col.offsetParent) return;
      var box = limits(), tile = snapped.tile === "a" ? a : b, list = edges(tile);
      var h = list[Math.min(snapped.i, list.length - 1)];
      apply(clamp(snapped.tile === "a" ? (h - box.fixed) / box.total : (box.sum - h - box.fixed) / box.total, box));
    }
    function keepSnap(value) {
      snapped = value;
      if (kept) store(name + ":snap", value ? value.tile + ":" + value.i : null);
    }
    var saved = chosen();
    if (kept) {
      var mark = null;
      try { mark = /^([ab]):([0-9]+)$/.exec(localStorage.getItem(KEY + name + ":snap") || ""); } catch (e) {}
      if (mark) snapped = { tile: mark[1], i: parseInt(mark[2], 10) };
    }
    // A tile with an extra rests at first where everything but its text shows: snapped to that edge, so it stays there
    // when the headline or the numbers change; that is its place until the user pulls it elsewhere.
    function rest() {
      if (!col.offsetParent || !col.getBoundingClientRect().height) return;
      if (snapped) { resnap(); return; }
      if (!extra(a) || chosen() > 0) return;
      var parts = Array.prototype.filter.call(a.children, function (child) {
        return child.tagName !== "HEADER" && !child.classList.contains("split-extra") && child.offsetParent !== null &&
          child.getBoundingClientRect().height;
      }).length;
      snapped = { tile: "a", i: parts };
      resnap();
    }
    if (saved > 0 && saved < 1) apply(saved);
    rest();
    // A part changed (a new status, a longer list): the tile follows the edge it snapped to.
    if (window.MutationObserver) [a, b].forEach(function (tile) {
      new MutationObserver(function () { requestAnimationFrame(rest); })
        .observe(tile, { childList: true, subtree: true, characterData: true });
    });
    window.addEventListener("resize", function () { if (chosen() > 0) fade(); else rest(); });
    window.addEventListener("load", rest);
    // When the view shows: at once before the next frame is painted (no jump), and once more when it has settled.
    document.addEventListener("agenthub:view", function () { requestAnimationFrame(rest); setTimeout(rest, 30); });
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
      var ratio = clamp((height - drag.box.fixed) / drag.box.total, drag.box);
      drag.snap = nearest(ratio, drag.box);   // close to the edge of a part: it snaps there
      apply(drag.snap ? drag.snap.r : ratio);
    });
    function end(event) {
      if (!drag || event.pointerId !== drag.id) return;
      var snap = drag.snap || null;
      drag = null;
      split.classList.remove("active");
      document.documentElement.classList.remove("splitting");
      keep(parseFloat(col.style.getPropertyValue("--split")) || null);
      keepSnap(snap);
    }
    split.addEventListener("pointerup", end);
    split.addEventListener("pointercancel", end);
    split.addEventListener("dblclick", function () { keep(null); keepSnap(null); apply(null); rest(); });
    split.addEventListener("keydown", function (event) {
      var step = { ArrowUp: -0.05, ArrowDown: 0.05 }[event.key];
      if (step === undefined) return;
      event.preventDefault();
      var box = limits();
      var now = col.classList.contains("split-set") ? parseFloat(col.style.getPropertyValue("--split"))
        : (a.getBoundingClientRect().height - box.fixed) / box.total;
      var next = clamp(now + step, box);
      apply(next);
      keep(next);
      keepSnap(null);
    });
  });
})();
