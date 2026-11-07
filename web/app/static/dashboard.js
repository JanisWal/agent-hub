// Behaviour of the logged-in pages: greeting, settings drawer, dialogs, project pages and dragging.
(function () {
  function $(selector, root) { return (root || document).querySelector(selector); }
  function reloadQuietly(url) {
    try { sessionStorage.setItem("noanim", "1"); } catch (e) {}  // no entrance animation again
    if (url) location.assign(url); else location.reload();
  }

  // Greeting by the visitor's local time: 5-11 morning, 11-17 midday, otherwise evening.
  var greeting = $("#greeting");
  if (greeting) {
    var hour = new Date().getHours();
    var part = hour >= 5 && hour < 11 ? "morning" : hour >= 11 && hour < 17 ? "noon" : "evening";
    greeting.textContent = greeting.dataset[part] + ", " + greeting.dataset.name;
  }

  // Settings drawer: slides out of the top right corner, the handle rides along.
  var drawer = $("#settings");
  var toggle = $("#settings-toggle");
  if (drawer && toggle) {
    var setOpen = function (open) {
      drawer.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", String(open));
    };
    var isOpen = function () { return drawer.classList.contains("open"); };
    toggle.addEventListener("click", function () { setOpen(!isOpen()); });
    document.addEventListener("click", function (event) {
      if (isOpen() && !event.target.closest("#settings")) setOpen(false);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && isOpen()) setOpen(false);
    });
  }

  // Dialogs: "Abbrechen" buttons close the dialog they are in.
  document.addEventListener("click", function (event) {
    var close = event.target.closest("[data-close]");
    if (close) close.closest("dialog").close();
  });

  var createDialog = $("#create-dialog");
  var newProject = $("#new-project");
  if (createDialog && newProject) {
    newProject.addEventListener("click", function () {
      createDialog.showModal();
      $("input", createDialog).focus();
    });
    createDialog.addEventListener("close", function () {
      var form = $("form", createDialog);
      form.reset();
      AgentHub.clear(form);
    });
  }

  // Deleting: step 1 asks "sure?", step 2 asks for the password, both can be cancelled.
  var deleteDialog = $("#delete-dialog");
  if (deleteDialog) {
    var step1 = $('[data-step="1"]', deleteDialog);
    var step2 = $('[data-step="2"]', deleteDialog);
    var wrong = $("#delete-error");
    var password = $('input[name="password"]', deleteDialog);
    var projectId = null;

    deleteDialog.addEventListener("close", function () {
      step1.hidden = false;
      step2.hidden = true;
      wrong.hidden = true;
      password.value = "";
      AgentHub.clear(step2);
    });

    document.addEventListener("click", function (event) {
      var button = event.target.closest(".tile-delete");
      if (!button) return;
      projectId = button.dataset.id;
      $("#delete-name").textContent = $(".tile-name", button.closest(".tile")).textContent;
      deleteDialog.showModal();
    });

    $("[data-yes]", deleteDialog).addEventListener("click", function () {
      step1.hidden = true;
      step2.hidden = false;
      password.focus();
    });

    step2.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!AgentHub.validate(step2)) return;
      wrong.hidden = true;
      fetch("/projects/" + projectId + "/delete", { method: "POST", body: new FormData(step2) })
        .then(function (response) {
          if (response.status === 403) {
            wrong.hidden = false;
            password.select();
          } else {
            reloadQuietly();
          }
        })
        .catch(function () { wrong.hidden = false; });
    });
  }

  // Pages of project tiles. All pages sit side by side on a track that slides by spring.
  // Pages turn by the dots and arrows, by swiping (finger), and by holding a carried tile at
  // the left or right edge. Past the last page a new page opens. Empty slots and the "+" tile
  // never move.
  var pagesBox = $("#pages");
  if (pagesBox) {
    var SIZE = Number(pagesBox.dataset.size);
    var GAP = 48;  // distance between pages, must match .track in theme.css
    var track = $("#track");
    var pager = $("#pager");
    var edges = document.querySelectorAll(".edge");
    var ARROWS = {
      left: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 6l-8 6 8 6z"/></svg>',
      right: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l8 6-8 6z"/></svg>'
    };
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

    var pageX = Motion.spring(0, Motion.MOVE, function (value) {
      track.style.transform = "translate3d(" + value + "px,0,0)";
    });
    pageX.set(-index * stride());

    // Tabbing must not scroll the clipped track sideways, and hidden pages are not reachable.
    pagesBox.addEventListener("scroll", function () { pagesBox.scrollLeft = 0; });
    var markInert = function () {
      grids().forEach(function (grid, i) { grid.inert = i !== index; });
    };
    markInert();
    window.addEventListener("resize", function () { pageX.set(-index * stride()); });

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

    // Redraw the dots and arrows (the number of pages can change while dragging).
    function renderPager() {
      var count = grids().length;
      var texts = pager.dataset;
      pager.hidden = count < 2;
      pager.textContent = "";
      pager.appendChild(arrowElement(index - 1, count, "left", texts.labelPrev));
      var dots = document.createElement("span");
      dots.className = "dots";
      for (var n = 0; n < count; n++) {
        var dot = document.createElement("a");
        dot.className = "dot" + (n === index ? " active" : "");
        dot.href = "/?page=" + (n + 1);
        dot.dataset.page = n + 1;
        dot.setAttribute("aria-label", texts.labelPage.replace("{n}", n + 1));
        if (n === index) dot.setAttribute("aria-current", "page");
        dots.appendChild(dot);
      }
      pager.appendChild(dots);
      pager.appendChild(arrowElement(index + 1, count, "right", texts.labelNext));
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
      if (event.target.closest("input, textarea, select, dialog") || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === "ArrowLeft") goTo(index - 1);
      else if (event.key === "ArrowRight") goTo(index + 1);
    });

    // Swiping with a finger: the track follows 1:1 (with rubber-banding at both ends), and on
    // release the flick's velocity decides where it comes to rest.
    pagesBox.addEventListener("pointerdown", function (event) {
      if (event.pointerType === "mouse" || sorter.dragging()) return;
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
      containerFor: function (el) { return el.closest("#track .grid"); },
      axis: "xy",
      endSelector: ".tile.plus, .tile.ghost",
      ignore: ".tile-delete",
      onPick: function (tile) {
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
        goTo(all.indexOf(endGrid));
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
