// Pages of project tiles on the dashboard. Needs motion.js, sortable.js and core.js.
(function () {
  function $(selector, root) { return (root || document).querySelector(selector); }
  var reloadQuietly = AgentHub.reload;
  // Pages of project tiles. All pages sit side by side on a track that slides by spring.
  // Pages turn by the dots and arrows, by swiping (finger), and by holding a carried tile at
  // the left or right edge. Past the last page a new page opens. Empty slots and the "+" tile
  // never move.
  var pagesBox = $("#pages");
  if (pagesBox) {
    var SIZE = Number(pagesBox.dataset.size);
    var GAP = 128;  // distance between pages, must match .track in dashboard.css (room for tile shadows)
    var track = $("#track");
    var pager = $("#pager");
    var edges = document.querySelectorAll(".edge");
    var ARROWS = {
      left: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 6l-8 6 8 6z"/></svg>',
      right: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l8 6-8 6z"/></svg>'
    };
    // On a phone held upright the pages do not sit side by side: one column, scroll down (CSS).
    var compact = window.matchMedia("(max-width: 560px)");
    var index = Number(pagesBox.dataset.current) - 1;  // 0-based page that is shown
    var before = "";
    var startGrid = null;
    var flipTimer = null;
    var flipDir = 0;
    var swipe = null;

    var grids = function () { return Array.prototype.slice.call(track.querySelectorAll(".grid")); };
    var tilesOf = function (grid) { return Array.prototype.slice.call(grid.querySelectorAll(".tile[data-id]")); };
    var order = function () {
      var ids = [];
      grids().forEach(function (grid) { tilesOf(grid).forEach(function (t) { ids.push(t.dataset.id); }); });
      return ids.join();
    };
    var stride = function () {
      var style = getComputedStyle(pagesBox);
      var inner = pagesBox.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      return inner + GAP;
    };

    var lastX = null;
    var lastT = 0;
    var leanSpeed = 0;
    var leanTimer = null;
    var pageX = Motion.spring(0, Motion.MOVE, function (value) {
      track.style.transform = "translate3d(" + value + "px,0,0)";
      // The pager hangs on the track: its position moves the worm, its speed leans the arrows.
      var now = performance.now();
      if (lastX !== null && now > lastT) leanSpeed = leanSpeed * 0.6 + ((value - lastX) / (now - lastT)) * 1000 * 0.4;
      lastX = value;
      lastT = now;
      clearTimeout(leanTimer);
      leanTimer = setTimeout(function () { leanSpeed = 0; leanArrows(); }, 120);
      leanArrows();
      drawWorm();
    });
    pageX.set(-index * stride());

    // A tile plays its entrance animation once. Moving it in the DOM would restart it (smaller and
    // see-through again), so a tile that has entered, or is about to be carried, never animates again.
    track.addEventListener("animationend", function (event) {
      if (event.target.classList.contains("tile")) event.target.classList.add("entered");
    });

    // Tabbing must not scroll the clipped track sideways, and hidden pages are not reachable.
    pagesBox.addEventListener("scroll", function () { pagesBox.scrollLeft = 0; });
    var markInert = function () {
      grids().forEach(function (grid, i) { grid.inert = !compact.matches && i !== index; });
    };
    markInert();
    window.addEventListener("resize", function () { pageX.set(-index * stride()); });
    compact.addEventListener("change", markInert);
    renderPager();

    function arrowElement(target, count, side, label) {
      var element;
      if (target >= 0 && target < count) {
        element = document.createElement("a");
        element.className = "pager-arrow";
        element.href = "/?page=" + (target + 1);
        element.dataset.page = target + 1;
        element.setAttribute("aria-label", label);
      } else {
        element = document.createElement("span");
        element.className = "pager-arrow off";
        element.setAttribute("aria-hidden", "true");
      }
      element.innerHTML = ARROWS[side];
      return element;
    }

    // Dots and arrows are built once and then only updated, so a pressed one can spring back.
    // The current page is a "worm" that hangs on the position of the track (see drawWorm).
    function dotElements() { return pager.querySelectorAll(".dot"); }

    function syncArrow(side, target, count, label) {
      var old = side === "left" ? pager.firstElementChild : pager.lastElementChild;
      var wantLink = target >= 0 && target < count;
      if (old && old.classList.contains("pager-arrow") && (old.tagName === "A") === wantLink) {
        if (wantLink) {
          old.href = "/?page=" + (target + 1);
          old.dataset.page = target + 1;
          old.setAttribute("aria-label", label);
        }
        return;
      }
      var fresh = arrowElement(target, count, side, label);
      if (old) pager.replaceChild(fresh, old); else pager.appendChild(fresh);
    }

    function renderPager() {
      var count = grids().length;
      var texts = pager.dataset;
      pager.hidden = count < 2;
      pager.classList.add("live");
      var dots = $(".dots", pager);
      if (dotElements().length !== count) {  // the number of pages changed: rebuild the dots
        dots.textContent = "";
        for (var n = 0; n < count; n++) {
          var dot = document.createElement("a");
          dot.className = "dot";
          dot.href = "/?page=" + (n + 1);
          dot.dataset.page = n + 1;
          dot.setAttribute("aria-label", texts.labelPage.replace("{n}", n + 1));
          dots.appendChild(dot);
        }
      }
      if (!$(".worm", dots)) {
        var worm = document.createElement("i");
        worm.className = "worm";
        worm.setAttribute("aria-hidden", "true");
        dots.appendChild(worm);
      }
      Array.prototype.forEach.call(dotElements(), function (dot, n) {
        if (n === index) dot.setAttribute("aria-current", "page"); else dot.removeAttribute("aria-current");
      });
      syncArrow("left", index - 1, count, texts.labelPrev);
      syncArrow("right", index + 1, count, texts.labelNext);
      drawWorm();
    }

    // The current page marker travels with the track, so it follows a finger 1:1, stretches while
    // it moves from one dot to the next (front end first, then the tail), and overshoots a little
    // where the track is pulled past its end.
    function drawWorm() {
      var worm = $(".worm", pager);
      var dots = dotElements();
      if (!worm || !dots.length) return;
      var pitch = dots.length > 1 ? dots[1].offsetLeft - dots[0].offsetLeft : 24;
      var position = -pageX.value / stride();
      var inside = Math.min(Math.max(position, 0), dots.length - 1);
      var over = position - inside;
      var whole = Math.floor(inside);
      var part = inside - whole;
      var front = part < 0.5 ? 0 : (part - 0.5) * 2;
      var left = dots[0].offsetLeft + pitch * (whole + front) + over * pitch * 0.5;
      worm.style.transform = "translateX(" + left + "px)";
      worm.style.width = 10 + pitch * (part < 0.5 ? part * 2 : (1 - part) * 2) + "px";
    }

    // The arrows lean into the direction the pages are travelling and settle when they stop.
    function leanArrows() {
      var arrows = pager.querySelectorAll(".pager-arrow");
      if (arrows.length < 2) return;
      var amount = Math.max(-1, Math.min(1, -leanSpeed / 1800)) * 7;
      arrows[0].style.transform = amount < -0.2 ? "translateX(" + amount + "px)" : "";
      arrows[1].style.transform = amount > 0.2 ? "translateX(" + amount + "px)" : "";
    }
    // Slide to a page. The spring starts from where the track is right now, so a new
    // request while it is still moving continues smoothly. `velocity` is a flick's speed.
    function goTo(n, options) {
      var count = grids().length;
      index = Math.min(Math.max(n, 0), count - 1);
      var velocity = options && options.velocity;
      var params = options && options.flick ? Motion.SNAP : Motion.MOVE;
      pageX.k = Math.pow((2 * Math.PI) / params.response, 2);
      pageX.c = 2 * params.damping * Math.sqrt(pageX.k);
      pageX.to(-index * stride(), velocity === undefined ? undefined : { velocity: velocity });
      try { history.replaceState(null, "", "/?page=" + (index + 1)); } catch (e) {}
      if (!sorter.dragging()) markInert();
      renderPager();
    }

    pager.addEventListener("click", function (event) {
      var link = event.target.closest("[data-page]");
      if (!link) return;
      event.preventDefault();
      goTo(Number(link.dataset.page) - 1);
    });

    document.addEventListener("keydown", function (event) {
      if (compact.matches || event.target.closest("input, textarea, select, dialog") || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === "ArrowLeft") goTo(index - 1);
      else if (event.key === "ArrowRight") goTo(index + 1);
    });

    // Swiping with a finger: the track follows 1:1 (with rubber-banding at both ends), and on
    // release the flick's velocity decides where it comes to rest.
    pagesBox.addEventListener("pointerdown", function (event) {
      if (event.pointerType === "mouse" || compact.matches || sorter.dragging()) return;
      pageX.stop();  // grab the track while it is still moving
      swipe = {
        id: event.pointerId, x: event.clientX, y: event.clientY, base: pageX.value,
        active: false, history: [{ t: performance.now(), x: event.clientX, y: 0 }]
      };
    });

    document.addEventListener("pointermove", function (event) {
      if (!swipe || event.pointerId !== swipe.id) return;
      if (sorter.dragging()) { swipe = null; return; }  // a tile is carried: no page swipe
      var dx = event.clientX - swipe.x;
      var dy = event.clientY - swipe.y;
      if (!swipe.active) {
        if (Math.abs(dy) > 10 && Math.abs(dy) > Math.abs(dx)) { swipe = null; return; }  // vertical: not ours
        if (Math.abs(dx) <= 10) return;
        swipe.active = true;
        sorter.cancelPress();
      }
      var min = -(grids().length - 1) * stride();
      var position = swipe.base + dx;
      if (position > 0) position = Motion.rubberband(position, pagesBox.clientWidth);
      else if (position < min) position = min - Motion.rubberband(min - position, pagesBox.clientWidth);
      pageX.set(position);
      swipe.history.push({ t: performance.now(), x: event.clientX, y: 0 });
      if (swipe.history.length > 6) swipe.history.shift();
    });

    function endSwipe(event) {
      if (!swipe || event.pointerId !== swipe.id) return;
      var state = swipe;
      swipe = null;
      if (!state.active) return;
      var velocity = Motion.velocityOf(state.history).x;
      var projected = pageX.value + Motion.project(velocity);  // where the flick would come to rest
      var target = Math.round(-projected / stride());
      // At most one page per swipe, like a pager.
      target = Math.min(Math.max(target, index - 1), index + 1);
      goTo(target, { velocity: velocity, flick: true });
    }
    document.addEventListener("pointerup", endSwipe);
    document.addEventListener("pointercancel", endSwipe);

    // Turn the page after a carried tile rested at an edge for a moment.
    function flip() {
      var dir = flipDir;
      flipDir = 0;  // lets the next move arm the timer again
      var all = grids();
      var target = index + dir;
      if (target < 0) return;
      if (target >= all.length) {
        // A new page only opens if the last page holds a project besides the carried one.
        var carried = $(".tile.drag-slot");
        var others = tilesOf(all[all.length - 1]).filter(function (t) { return t !== carried; });
        if (!others.length) return;
        var fresh = document.createElement("div");
        fresh.className = "grid";
        track.appendChild(fresh);
      }
      goTo(target);
    }

    function checkEdges(x) {
      if (compact.matches) return;  // one column: no page edges
      var zone = Math.min(96, window.innerWidth * 0.08);
      var dir = x > window.innerWidth - zone ? 1 : x < zone ? -1 : 0;
      edges[0].classList.toggle("hot", dir === -1);
      edges[1].classList.toggle("hot", dir === 1);
      if (dir === flipDir) return;
      clearTimeout(flipTimer);
      flipDir = dir;
      if (dir) flipTimer = setTimeout(flip, 650);
    }

    // Carrying a tile: it follows the pointer, the others make room, it lands in its slot.
    var sorter = Motion.sortable({
      itemSelector: ".tile[data-id]",
      items: function () { return track.querySelectorAll(".tile[data-id]"); },
      containerFor: function (el) {
        var grid = el.closest("#track .grid");
        // Upright phone: below the last tile still counts as the end of the list.
        if (!grid && compact.matches && el.closest("#pages")) { var all = grids(); return all[all.length - 1]; }
        return grid;
      },
      axis: function () { return compact.matches ? "y" : "xy"; },
      gapHost: function (tile) { return compact.matches ? track : tile.closest(".grid"); },
      endSelector: ".tile.plus, .tile.ghost",
      ignore: ".tile-delete",
      onPick: function (tile) {
        Array.prototype.forEach.call(track.querySelectorAll(".tile"), function (t) { t.classList.add("entered"); });
        before = order();
        startGrid = tile.closest(".grid");
        pageX.stop();
        grids().forEach(function (grid) { grid.inert = false; });
        document.body.classList.add("dragging-tile");
      },
      onMove: function (x) { checkEdges(x); },
      onDrop: function (info) {
        document.body.classList.remove("dragging-tile");
        clearTimeout(flipTimer);
        flipDir = 0;
        Array.prototype.forEach.call(edges, function (edge) { edge.classList.remove("hot"); });

        // A page we opened but did not use disappears again.
        grids().forEach(function (grid) { if (!grid.querySelector(".tile")) grid.remove(); });
        var tile = info.item;
        var endGrid = tile.closest(".grid");
        var all = grids();
        if (!compact.matches) goTo(all.indexOf(endGrid));
        if (order() === before && endGrid === startGrid) return;
        fetch("/projects/move", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            id: Number(tile.dataset.id),
            page: all.indexOf(endGrid) + 1,
            index: tilesOf(endGrid).indexOf(tile)
          })
        }).then(function (response) {
          return response.ok ? response.json() : null;
        }).then(function (result) {
          // Another page, or a full page that pushed a tile on: let the server lay it out.
          if (!result) reloadQuietly();
          else if (endGrid !== startGrid || tilesOf(endGrid).length > SIZE) reloadQuietly("/?page=" + result.page);
        }).catch(function () { reloadQuietly(); });
      }
    });
  }
})();
