// Motion: a small spring engine and FLIP. No dependencies. (Drag to reorder: sortable.js.)
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

  return {
    MOVE: MOVE, LIFT: LIFT, SNAP: SNAP, LEAN: LEAN,
    reduced: reduced, spring: spring, project: project, rubberband: rubberband,
    velocityOf: velocityOf, flip: flip
  };
})();
