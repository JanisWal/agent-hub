// The segment slider (DESIGN.md, "Segmentschalter"): a glass thumb lies under the chosen item and springs to a new one.
// Two ways to choose, like iOS (Janis, 14.11.2026): click an item, or press the chosen one and drag the thumb to
// another, which lights up while the thumb is over it; on release the thumb glides there with the speed of the gesture.
// Works across (file tabs) and upright (stations of the project page); the direction comes from the CSS of the box.
// Springs from motion.js, only transform, interruptible; with reduced motion the thumb jumps.
var Segment = (function () {
  "use strict";

  // box: the row or column. options: thumb (element), items() -> elements, current() -> element,
  // enabled(el) -> bool (default true), pick(el) after a drag (the caller selects it and calls place()).
  function attach(box, options) {
    var thumb = options.thumb;
    var enabled = options.enabled || function () { return true; };
    var pos = 0, scale = 1, axis = "x";
    function render() {
      thumb.style.transform = (axis === "x" ? "translateX(" + pos + "px)" : "translateY(" + pos + "px)") +
        (scale !== 1 ? " scale(" + scale + ")" : "");
    }
    var move = Motion.spring(0, Motion.MOVE, function (v) { pos = v; render(); }, 0.05);
    var lift = Motion.spring(1, Motion.LIFT, function (v) { scale = v; render(); }, 0.001);

    function upright() {
      var direction = getComputedStyle(box).flexDirection;
      return direction === "column" || direction === "column-reverse";
    }
    function start(el) { return axis === "x" ? el.offsetLeft : el.offsetTop; }
    function size(el) { return axis === "x" ? el.offsetWidth : el.offsetHeight; }

    function place(instant) {
      var el = options.current();
      if (!el || !size(el)) return;
      axis = upright() ? "y" : "x";
      thumb.classList.toggle("upright", axis === "y");
      thumb.style[axis === "x" ? "width" : "height"] = size(el) + "px";
      thumb.style[axis === "x" ? "height" : "width"] = "";
      // A finger on the chosen item drags the thumb instead of scrolling the page; the others still scroll.
      options.items().forEach(function (item) { item.style.touchAction = item === el ? "none" : ""; });
      if (instant) move.set(start(el)); else move.to(start(el));
    }

    // --- dragging the thumb: only from the chosen item, 4 px before it counts (a click stays a click)
    var drag = null, swallowClick = false;
    function usable() { return options.items().filter(enabled); }
    function under(centre) {
      var best = null, distance = Infinity;
      usable().forEach(function (el) {
        var d = Math.abs(start(el) + size(el) / 2 - centre);
        if (d < distance) { distance = d; best = el; }
      });
      return best;
    }
    function mark(el) {
      options.items().forEach(function (item) { item.classList.toggle("seg-over", item === el); });
    }

    box.addEventListener("pointerdown", function (event) {
      var item = event.target.closest ? event.target.closest("[data-seg]") : null;
      if (!item || item !== options.current() || event.button > 0) return;
      drag = { id: event.pointerId, from: axis === "x" ? event.clientX : event.clientY, base: pos, moved: false,
               history: [] };
    });
    box.addEventListener("pointermove", function (event) {
      if (!drag || event.pointerId !== drag.id) return;
      var now = axis === "x" ? event.clientX : event.clientY;
      if (!drag.moved) {
        if (Math.abs(now - drag.from) < 4) return;
        drag.moved = true;
        try { box.setPointerCapture(event.pointerId); } catch (e) {}
        box.classList.add("seg-dragging");
        lift.to(1.04);
      }
      event.preventDefault();
      var items = usable();
      var low = start(items[0]), high = start(items[items.length - 1]) + size(items[items.length - 1]) - size(options.current());
      var target = drag.base + now - drag.from;
      if (target < low) target = low - Motion.rubberband(low - target, size(box));            // a rubber band at both ends
      if (target > high) target = high + Motion.rubberband(target - high, size(box));
      move.set(target);
      drag.history.push({ x: axis === "x" ? now : 0, y: axis === "y" ? now : 0, t: performance.now() });
      if (drag.history.length > 12) drag.history.shift();
      mark(under(target + size(options.current()) / 2));
    });
    function end(event) {
      if (!drag || event.pointerId !== drag.id) return;
      var was = drag;
      drag = null;
      if (!was.moved) return;
      box.classList.remove("seg-dragging");
      swallowClick = true;
      setTimeout(function () { swallowClick = false; }, 0);
      lift.to(1);
      mark(null);
      var velocity = Motion.velocityOf(was.history)[axis];
      var landing = pos + Motion.project(velocity, 0.99) + size(options.current()) / 2;   // a flick carries a little further
      var el = under(landing);
      var current = options.current();
      if (el && el !== current) options.pick(el);
      var target = options.current();
      move.to(start(target), { velocity: velocity });
    }
    box.addEventListener("pointerup", end);
    box.addEventListener("pointercancel", end);
    box.addEventListener("click", function (event) {   // the click that ends a drag chooses nothing more
      if (swallowClick) { event.preventDefault(); event.stopPropagation(); }
    }, true);

    if (window.ResizeObserver) new ResizeObserver(function () { place(true); }).observe(box);
    return { place: place };
  }

  return { attach: attach };
})();
