// Motion: a small spring engine and a drag-to-reorder controller. No dependencies.
// Rules follow Apple's "Designing Fluid Interfaces" (see .claude/skills/apple-design):
//  - springs described by damping ratio and response, not by fixed durations,
//  - every animation starts from the value that is on screen right now (interruptible),
//  - the release velocity of a gesture is handed to the spring,
//  - only transform and opacity are animated,
//  - prefers-reduced-motion: no springs, values jump to their target.
var Motion = (function () {
  "use strict";

  var reducedQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  var running = [];
  var frame = null;
  var lastTime = 0;

  var MOVE = { response: 0.4, damping: 1 };    // reposition and page change: smooth, no overshoot
  var LIFT = { response: 0.25, damping: 1 };   // a picked-up item grows
  var SNAP = { response: 0.35, damping: 0.85 }; // after a flick: a little bounce, the gesture had momentum
  var LEAN = { response: 0.35, damping: 0.7 };  // the carried item leans into its direction and sways back

  function reduced() { return reducedQuery.matches; }

  function enqueue(spring) {
    if (!spring.queued) { spring.queued = true; running.push(spring); }
    if (frame === null) { lastTime = performance.now(); frame = requestAnimationFrame(tick); }
  }

  function tick(now) {
    frame = null;
    var dt = Math.min((now - lastTime) / 1000, 1 / 30);
    lastTime = now;
    var list = running;
    running = [];
    list.forEach(function (s) {
      s.queued = false;
      if (!s.active) return;
      var steps = Math.max(1, Math.ceil(dt * 240));
      var h = dt / steps;
      for (var i = 0; i < steps; i++) {
        s.velocity += (-s.k * (s.value - s.target) - s.c * s.velocity) * h;
        s.value += s.velocity * h;
      }
      if (Math.abs(s.value - s.target) < s.precision && Math.abs(s.velocity) < s.precision * 20) {
        s.value = s.target;
        s.velocity = 0;
        s.active = false;
      }
      s.update(s.value);
      if (s.active) enqueue(s);
    });
    if (running.length && frame === null) frame = requestAnimationFrame(tick);
  }

  // A number that springs toward a target. `update(value)` is called on every change.
  function spring(initial, params, update, precision) {
    var k = Math.pow((2 * Math.PI) / params.response, 2);
    var s = {
      value: initial, velocity: 0, target: initial, active: false, queued: false,
      k: k, c: 2 * params.damping * Math.sqrt(k),
      precision: precision || 0.05,
      update: update || function () {}
    };
    // Spring to `target`, optionally starting with the velocity of a gesture (units per second).
    s.to = function (target, options) {
      s.target = target;
      if (options && options.velocity !== undefined) s.velocity = options.velocity;
      if (reduced()) {
        s.value = target; s.velocity = 0; s.active = false;
        s.update(target);
        return s;
      }
      s.active = true;
      enqueue(s);
      return s;
    };
    // Follow the finger 1:1: stop and take the value.
    s.set = function (value) {
      s.value = value; s.target = value; s.velocity = 0; s.active = false;
      s.update(value);
      return s;
    };
    // Change the value but keep the velocity (used when the layout moves under a running spring).
    s.jump = function (value) { s.value = value; s.update(value); return s; };
    s.stop = function () { s.active = false; return s; };
    return s;
  }

  // Where a flick with this release velocity (px/s) comes to rest, like scroll deceleration.
  function project(velocity, rate) {
    rate = rate || 0.998;
    return (velocity / 1000) * rate / (1 - rate);
  }

  // Resistance that grows the further the finger is dragged past a boundary.
  function rubberband(overshoot, dimension, constant) {
    constant = constant || 0.55;
    return (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot));
  }

  // Velocity (px/s) over the last ~100 ms of pointer positions; zero if the pointer rested.
  function velocityOf(history) {
    var last = history[history.length - 1];
    if (!last || performance.now() - last.t > 100) return { x: 0, y: 0 };
    var first = history[0];
    for (var i = 0; i < history.length; i++) {
      if (last.t - history[i].t <= 100) { first = history[i]; break; }
    }
    var dt = Math.max(last.t - first.t, 1) / 1000;
    return { x: (last.x - first.x) / dt, y: (last.y - first.y) / dt };
  }

  // Each moved element carries two springs (x and y, never one on the distance).
  function offsetOf(el) {
    if (!el.__offset) {
      var offset = {};
      var update = function () {
        var x = offset.x.value, y = offset.y.value;
        el.style.transform = x || y ? "translate3d(" + x + "px," + y + "px,0)" : "";
      };
      offset.x = spring(0, MOVE, update);
      offset.y = spring(0, MOVE, update);
      el.__offset = offset;
    }
    return el.__offset;
  }

  // FLIP: remember where the items are, change the DOM, then let every item glide from its old
  // spot to its new one. A running glide is continued from where it is, with its velocity.
  // With `origin` (the element that moved) the change travels outward as a wave: the farther an
  // item is from the origin, the later it sets off (up to 110 ms).
  function flip(items, mutate, origin) {
    var before = items.map(function (el) { return el.getBoundingClientRect(); });
    mutate();
    var from = null;
    if (origin) {
      var r = origin.getBoundingClientRect();
      from = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }
    items.forEach(function (el, i) {
      var after = el.getBoundingClientRect();
      var dx = before[i].left - after.left;
      var dy = before[i].top - after.top;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) return;
      var offset = offsetOf(el);
      clearTimeout(offset.timer);
      offset.x.stop(); offset.y.stop();
      offset.x.jump(offset.x.value + dx);
      offset.y.jump(offset.y.value + dy);
      var go = function () { offset.x.to(0); offset.y.to(0); };
      var delay = from
        ? Math.min(Math.hypot(after.left + after.width / 2 - from.x, after.top + after.height / 2 - from.y) / 10, 110)
        : 0;
      if (delay > 8 && !reduced()) offset.timer = setTimeout(go, delay);
      else go();
    });
  }

  function whenSettled(springs, done) {
    (function check() {
      if (springs.every(function (s) { return !s.active; })) done();
      else requestAnimationFrame(check);
    })();
  }

  // Drag to reorder with mouse, pen or finger.
  //   itemSelector   what can be picked up
  //   items()        all items (for the gliding of the others)
  //   containerFor(el)  the list element under an element, or null
  //   axis           "xy" for grids, "y" for vertical lists (or a function that answers it now)
  //   endSelector    elements (free slots) that mean "put it at the end"
  //   ignore         presses on these never start a drag (buttons)
  //   gapHost(item)  element the red gap is placed in (it must slide away with the list)
  //   onPick(item), onMove(x, y), onDrop(info)
  // A mouse starts dragging after 5 px, a finger after a short press (so scrolling and swiping
  // still work). The picked item follows the pointer 1:1, the others make room, and on release
  // the item springs into its slot with the velocity of the finger.
  function sortable(o) {
    var press = null;
    var drag = null;
    var swallowClick = false;

    function cancelPress() {
      if (press) { clearTimeout(press.timer); press = null; }
    }

    document.addEventListener("pointerdown", function (e) {
      if (drag || press || (e.pointerType === "mouse" && e.button !== 0)) return;
      var item = e.target.closest && e.target.closest(o.itemSelector);
      if (!item || (o.ignore && e.target.closest(o.ignore))) return;
      press = {
        item: item, id: e.pointerId, x: e.clientX, y: e.clientY,
        lastX: e.clientX, lastY: e.clientY, touch: e.pointerType !== "mouse", timer: null
      };
      if (press.touch) {
        press.timer = setTimeout(function () { if (press) begin(press.lastX, press.lastY); }, o.longPress || 380);
      }
    });

    document.addEventListener("pointermove", function (e) {
      if (press && e.pointerId === press.id) {
        press.lastX = e.clientX;
        press.lastY = e.clientY;
        var moved = Math.hypot(e.clientX - press.x, e.clientY - press.y);
        if (press.touch) { if (moved > 10) cancelPress(); }  // the finger moved: scroll or swipe
        else if (moved > 5) begin(e.clientX, e.clientY);
      }
      if (drag && e.pointerId === drag.id) move(e.clientX, e.clientY);
    });

    function release(e) {
      if (press && e.pointerId === press.id) cancelPress();
      if (drag && e.pointerId === drag.id) end();
    }
    document.addEventListener("pointerup", release);
    document.addEventListener("pointercancel", release);

    // No scrolling, text selection, context menu or link click while an item is carried.
    document.addEventListener("touchmove", function (e) { if (drag) e.preventDefault(); }, { passive: false });
    document.addEventListener("contextmenu", function (e) { if (drag || (press && press.touch)) e.preventDefault(); });
    document.addEventListener("click", function (e) {
      if (swallowClick) { e.preventDefault(); e.stopPropagation(); }
    }, true);

    function begin(x, y) {
      var item = press.item;
      var id = press.id;
      var grabX = press.x;  // where the finger first touched: the item keeps this offset to the pointer
      var grabY = press.y;
      var rect = item.getBoundingClientRect();
      cancelPress();
      var clone = item.cloneNode(true);
      clone.removeAttribute("data-id");
      clone.removeAttribute("id");
      clone.classList.add("drag-clone");
      clone.style.cssText = "left:" + rect.left + "px;top:" + rect.top + "px;width:" + rect.width + "px;height:" + rect.height + "px;";
      document.body.appendChild(clone);
      item.classList.add("drag-slot");  // invisible, but its place stays reserved while the clone travels
      // The red gap is its own element, fixed where the item was taken from. It belongs to the
      // list (so it slides away with its page) and has nothing to do with the item or its move.
      var host = o.gapHost ? o.gapHost(item) : (item.offsetParent || item.parentNode);
      if (getComputedStyle(host).position === "static") host.style.position = "relative";
      // Layout pixels (offset*), not screen pixels: a parent that is scaled (for example while it
      // plays its entrance animation) would otherwise shrink the gap twice.
      var box;
      if (item.offsetParent === host) {
        box = { left: item.offsetLeft, top: item.offsetTop, width: item.offsetWidth, height: item.offsetHeight };
      } else {
        var hostRect = host.getBoundingClientRect();
        box = { left: rect.left - hostRect.left - host.clientLeft, top: rect.top - hostRect.top - host.clientTop, width: rect.width, height: rect.height };
      }
      var gap = document.createElement("div");
      gap.className = "drag-gap";
      gap.style.cssText = "left:" + box.left + "px;top:" + box.top + "px;width:" + box.width + "px;height:" + box.height +
        "px;border-radius:" + getComputedStyle(item).borderRadius + ";";
      host.appendChild(gap);
      var state = {
        item: item, clone: clone, id: id, grabX: grabX, grabY: grabY, left: rect.left, top: rect.top,
        w: rect.width, h: rect.height, rest: null, pending: null, markedNode: null, gap: gap,
        startContainer: o.containerFor(item), history: [{ t: performance.now(), x: x, y: y }]
      };
      // Every picked item draws itself, so the landing animation still works after `drag` is cleared.
      var draw = function () {
        clone.style.transform =
          "translate3d(" + state.xs.value + "px," + state.ys.value + "px,0) rotate(" + state.rot.value +
          "deg) scale(" + state.scale.value + ")";
      };
      state.xs = spring(0, MOVE, draw);
      state.ys = spring(0, MOVE, draw);
      state.scale = spring(1, LIFT, draw, 0.001);
      state.rot = spring(0, LEAN, draw, 0.01);
      state.xs.set(x - grabX);  // the pointer has already moved a little since it went down
      state.ys.set(y - grabY);
      drag = state;
      swallowClick = true;
      document.documentElement.classList.add("dragging-active");
      if (window.getSelection) window.getSelection().removeAllRanges();
      clone.classList.add("lifted");
      state.scale.to(1.05);
      if (navigator.vibrate) { try { navigator.vibrate(8); } catch (err) {} }
      if (o.onPick) o.onPick(item);
    }

    function move(x, y) {
      var d = drag;
      d.xs.set(x - d.grabX);
      d.ys.set(y - d.grabY);
      d.history.push({ t: performance.now(), x: x, y: y });
      if (d.history.length > 6) d.history.shift();
      var v = velocityOf(d.history);
      // The carried item leans a little into the direction it is moved, and sways back at rest.
      d.rot.to(Math.max(-6, Math.min(6, (v.x / 1000) * 2.4)));
      clearTimeout(d.rest);
      d.rest = setTimeout(function () { d.rot.to(0); }, 140);
      aim(d);  // nothing is rearranged while carrying: the target below just lifts a little
      autoscroll(d, y);
      if (o.onMove) o.onMove(x, y);
    }
    function axisNow() { return typeof o.axis === "function" ? o.axis() : o.axis; }

    // Near the top or bottom edge of the window a carried item scrolls the page (lists that scroll).
    function autoscroll(d, y) {
      var zone = 90;
      var edge = y < zone ? -(zone - y) / zone : y > window.innerHeight - zone ? (y - (window.innerHeight - zone)) / zone : 0;
      var scrolls = document.documentElement.scrollHeight > window.innerHeight + 2;
      d.scrollSpeed = scrolls ? edge * 18 : 0;
      if (d.scrollSpeed && !d.scroller) {
        d.scroller = setInterval(function () {
          if (drag !== d || !d.scrollSpeed) { clearInterval(d.scroller); d.scroller = null; return; }
          window.scrollBy(0, d.scrollSpeed);
          aim(d);  // the items moved under the finger
        }, 16);
      }
    }

    function endAnchor(container, others) {
      var last = others[others.length - 1];
      return last ? last.nextSibling : container.firstChild;
    }

    // The item you carry only chooses a target while you move: the slot stays where it is (the
    // gap you took it from), and the item under the middle of the carried one lifts a little.
    // The rearranging happens when you let go.
    function mark(d, el) {
      var node = el === d.item ? d.gap : el;  // over its own place: the red gap itself is the target
      if (d.markedNode === node) return;
      if (d.markedNode) d.markedNode.classList.remove("drop-target");
      d.markedNode = node;
      if (node) node.classList.add("drop-target");
    }

    function aim(d) {
      if (drag !== d) return;
      var x = d.left + d.w / 2 + d.xs.value;
      var y = d.top + d.h / 2 + d.ys.value;
      d.pending = null;
      var el = document.elementFromPoint(x, y);
      var container = el && o.containerFor(el);
      if (!container) { mark(d, null); return; }
      var item = d.item;
      var over = el.closest(o.itemSelector);
      if (over === item) { mark(d, item); return; }  // back over its own gap: nothing changes
      if (over) {
        // Only the middle of a target counts, so grazing its edge targets nothing.
        var r = over.getBoundingClientRect();
        var zoneX = axisNow() === "y" ? 0 : r.width * 0.2;
        var zoneY = r.height * 0.22;
        if (x < r.left + zoneX || x > r.right - zoneX || y < r.top + zoneY || y > r.bottom - zoneY) { mark(d, null); return; }
      }
      var others = Array.prototype.filter.call(container.querySelectorAll(o.itemSelector), function (i) { return i !== item; });
      var anchor;
      if (over && container.contains(over)) {
        var before = item.parentNode === container &&
          (item.compareDocumentPosition(over) & Node.DOCUMENT_POSITION_FOLLOWING);
        anchor = before ? over.nextSibling : over;
      } else if (item.parentNode !== container) {
        anchor = endAnchor(container, others);
      } else if (axisNow() === "y"
          ? others.length && y > others[others.length - 1].getBoundingClientRect().bottom
          : o.endSelector && el.closest(o.endSelector)) {
        anchor = endAnchor(container, others);
      } else {
        mark(d, null);
        return;
      }
      mark(d, over || null);
      if (anchor === item || (item.parentNode === container && item.nextSibling === anchor)) return;
      d.pending = { container: container, anchor: anchor };
    }
    function end() {
      var d = drag;
      drag = null;
      document.documentElement.classList.remove("dragging-active");
      var velocity = velocityOf(d.history);
      clearTimeout(d.rest);
      clearInterval(d.scroller);
      mark(d, null);
      d.gap.classList.add("leaving");  // the red gap fades out where it is; it does not travel
      if (d.pending) {
        // Let go: now the item takes its new place and the others glide to make room.
        var pending = d.pending;
        flip(Array.prototype.slice.call(o.items()), function () {
          pending.container.insertBefore(d.item, pending.anchor);
        }, d.item);
      }
      var slot = d.item.getBoundingClientRect();
      var glide = d.item.__offset;  // the slot may still be gliding into place: aim at where it ends up
      d.clone.classList.remove("lifted");
      d.scale.to(1);
      d.rot.to(0);
      d.xs.to(slot.left - (glide ? glide.x.value : 0) - d.left, { velocity: velocity.x });
      d.ys.to(slot.top - (glide ? glide.y.value : 0) - d.top, { velocity: velocity.y });
      var finish = function () {
        d.clone.remove();
        d.item.classList.remove("drag-slot");
        d.gap.remove();
        setTimeout(function () { swallowClick = false; }, 60);
        if (o.onDrop) o.onDrop({ item: d.item, container: o.containerFor(d.item), from: d.startContainer });
      };
      whenSettled([d.xs, d.ys, d.scale, d.rot], finish);
    }

    return {
      cancelPress: cancelPress,
      dragging: function () { return drag !== null; }
    };
  }

  return {
    MOVE: MOVE, LIFT: LIFT, SNAP: SNAP, LEAN: LEAN,
    reduced: reduced, spring: spring, project: project, rubberband: rubberband,
    velocityOf: velocityOf, flip: flip, sortable: sortable
  };
})();
